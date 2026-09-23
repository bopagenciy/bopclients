"""Default search planner implementation converting SearchIntent into executable SearchPlan."""

from typing import List, Set, Optional, Tuple, Dict
from bopclients.domain.search_intent import SearchIntent
from bopclients.domain.exceptions import SearchPlanningError
from bopclients.domain.provider_capability import (
    ProviderCapability,
    ProviderCapabilityRegistry,
    SearchGeographicScope,
    get_overture_capability,
    get_web_search_capability,
)
from bopclients.application.search_dto import (
    SearchPlan,
    DiscoveryTask,
    SearchWarning,
    ResolvedLocation,
)
from bopclients.application.interfaces.search_interfaces import ISearchPlanner, ILocationResolver


class DefaultSearchPlanner(ISearchPlanner):
    """Generates structured DiscoveryTasks for target discovery providers based on capabilities and geographic scope."""

    def __init__(
        self,
        location_resolver: ILocationResolver,
        capability_registry: Optional[ProviderCapabilityRegistry] = None,
    ):
        self.location_resolver = location_resolver
        self.capability_registry = capability_registry or ProviderCapabilityRegistry()

    def plan(self, intent: SearchIntent) -> SearchPlan:
        intent.validate()

        tasks: List[DiscoveryTask] = []
        warnings: List[SearchWarning] = []
        seen_task_keys: Set[Tuple[str, str, str, str, str]] = set()

        # Emit warnings for desired signals that cannot be evaluated during raw discovery
        for sig in intent.desired_signals:
            warnings.append(
                SearchWarning(
                    code="SIGNAL_FILTER_REQUIRES_ENRICHMENT",
                    message=f"Signal filter '{sig}' cannot be evaluated during discovery phase. It will be evaluated during subsequent enrichment.",
                    details={"signal": sig},
                )
            )

        # Emit warning for company size constraint: raw discovery providers do not support employee-size filtering
        if intent.company_sizes:
            warnings.append(
                SearchWarning(
                    code="EXACT_SIZE_FILTER_REQUIRES_ENRICHMENT",
                    message=(
                        f"Raw discovery providers do not support employee-size filtering. "
                        f"Configured company size constraints ({', '.join(intent.company_sizes)}) cannot be evaluated during discovery "
                        f"and require post-discovery company research."
                    ),
                    details={
                        "company_sizes": intent.company_sizes,
                        "provider_filtering_supported": False,
                    },
                )
            )

        # Emit warnings attached to intent
        for w_code in getattr(intent, "warnings", []):
            if w_code == "MULTIPLE_TARGET_MARKETS_REQUIRE_SELECTION":
                warnings.append(
                    SearchWarning(
                        code="MULTIPLE_TARGET_MARKETS_REQUIRE_SELECTION",
                        message="Multiple target markets are configured for this campaign ICP. Explicit target market selection is required to apply geographic targeting.",
                    )
                )

        # Categories: WHO WE SEARCH (strictly industries/business_categories, NEVER services_to_offer)
        raw_cats = intent.industries or intent.business_categories
        categories = [c for c in raw_cats if c not in (intent.services_to_offer or [])] or raw_cats or ["general"]

        countries = intent.countries or ["US"]
        regions = intent.regions or []
        cities = intent.cities or []

        # Resolve geographic search targets
        geo_targets = []
        if cities:
            for country in countries:
                for city in cities:
                    reg = regions[0] if regions else None
                    resolved_loc = self.location_resolver.resolve(
                        country=country,
                        region=reg,
                        city=city,
                    )
                    has_coords = bool(
                        resolved_loc
                        and resolved_loc.latitude is not None
                        and resolved_loc.longitude is not None
                    )
                    scope = (
                        SearchGeographicScope.POINT_RADIUS
                        if has_coords
                        else SearchGeographicScope.CITY
                    )
                    geo_targets.append((country, reg, city, resolved_loc, scope, has_coords))
        elif regions:
            for country in countries:
                for reg in regions:
                    resolved_loc = self.location_resolver.resolve(
                        country=country,
                        region=reg,
                    )
                    geo_targets.append(
                        (country, reg, None, resolved_loc, SearchGeographicScope.STATE_REGION, False)
                    )
        else:
            for country in countries:
                resolved_loc = self.location_resolver.resolve(
                    country=country,
                )
                if resolved_loc and resolved_loc.postal_code:
                    has_coords = bool(resolved_loc.latitude is not None and resolved_loc.longitude is not None)
                    scope = SearchGeographicScope.POINT_RADIUS if has_coords else SearchGeographicScope.CITY
                    geo_targets.append((country, resolved_loc.region_code, resolved_loc.city, resolved_loc, scope, has_coords))
                else:
                    geo_targets.append(
                        (country, None, None, resolved_loc, SearchGeographicScope.COUNTRY, False)
                    )

        overture_cap = self.capability_registry.get("overture")
        web_cap = self.capability_registry.get("web_search")

        for country, region, city, resolved_loc, scope, has_coords in geo_targets:
            for category in categories:
                # 1. Deterministic evaluation for Overture
                overture_qualified = bool(
                    overture_cap
                    and overture_cap.enabled
                    and overture_cap.is_category_supported(category)
                    and has_coords
                    and scope in (SearchGeographicScope.POINT_RADIUS, SearchGeographicScope.CITY)
                )

                if overture_qualified:
                    task_key = (
                        "overture",
                        category.lower(),
                        (resolved_loc.country_code if resolved_loc else country).upper(),
                        (resolved_loc.region_code or region or "").upper(),
                        ((resolved_loc.city if resolved_loc else city) or "").lower(),
                    )
                    if task_key in seen_task_keys:
                        continue
                    seen_task_keys.add(task_key)

                    task = DiscoveryTask(
                        provider="overture",
                        category=category,
                        country=resolved_loc.country_code if resolved_loc else country,
                        region=resolved_loc.region_code if resolved_loc else region,
                        city=resolved_loc.city if resolved_loc else city,
                        postal_code=resolved_loc.postal_code if resolved_loc else None,
                        latitude=resolved_loc.latitude if resolved_loc else None,
                        longitude=resolved_loc.longitude if resolved_loc else None,
                        radius_miles=intent.radius_miles if intent.radius_miles is not None else (resolved_loc.radius_miles if resolved_loc else 10.0),
                        limit=min(intent.max_results, overture_cap.max_results_limit),
                        priority=1,
                        negative_keywords=list(intent.negative_keywords),
                    )
                    tasks.append(task)
                    continue

                # 2. Deterministic evaluation for Web Search
                web_qualified = bool(
                    web_cap
                    and web_cap.is_category_supported(category)
                    and web_cap.supports_geographic_scope(scope)
                )

                if web_qualified:
                    loc_parts = []
                    if city:
                        loc_parts.append(city)
                    if region:
                        loc_parts.append(region)
                    if country and not city:
                        loc_parts.append(country)
                    loc_label = ", ".join(loc_parts) if loc_parts else (country or "")

                    # Construct truthful query without fabricating coordinates
                    cat_readable = category.replace("_", " ")
                    if intent.raw_query and len(categories) == 1:
                        query_str = intent.raw_query.strip()
                    else:
                        prep = "en" if country == "CO" or any(l in ("es", "es-CO") for l in intent.languages) else "in"
                        query_str = f"{cat_readable} {prep} {loc_label}".strip()

                    task_key = (
                        "web_search",
                        category.lower(),
                        country.upper(),
                        (region or "").upper(),
                        (city or "").lower(),
                    )
                    if task_key in seen_task_keys:
                        continue
                    seen_task_keys.add(task_key)

                    task = DiscoveryTask(
                        provider="web_search",
                        query=query_str,
                        category=category,
                        country=country,
                        region=region,
                        city=city,
                        postal_code=None,
                        latitude=None,   # Zero fabricated coordinates
                        longitude=None,  # Zero fabricated coordinates
                        radius_miles=intent.radius_miles if intent.radius_miles is not None else 10.0,
                        limit=min(intent.max_results, web_cap.max_results_limit if web_cap.enabled else 5),
                        priority=1,
                        negative_keywords=list(intent.negative_keywords),
                        metadata={"organization_id": intent.organization_id},
                    )
                    tasks.append(task)

                    if not web_cap.enabled:
                        warnings.append(
                            SearchWarning(
                                code="PROVIDER_DISABLED",
                                message="Web search discovery provider is disabled by default. Explicit configuration required.",
                                details={"provider": "web_search", "category": category},
                            )
                        )
                    continue

                # 3. Explicit diagnostics when no provider can handle request
                if not overture_cap and not web_cap:
                    warnings.append(
                        SearchWarning(
                            code="NO_SUITABLE_PROVIDER",
                            message=f"No discovery provider is available or permitted for category '{category}' in geography '{scope.value}'.",
                            details={"category": category, "geographic_scope": scope.value},
                        )
                    )
                elif overture_cap and not overture_cap.is_category_supported(category) and (not web_cap or not web_cap.is_category_supported(category)):
                    warnings.append(
                        SearchWarning(
                            code="UNSUPPORTED_CATEGORY",
                            message=f"Category '{category}' is not supported by available discovery providers.",
                            details={"category": category},
                        )
                    )
                elif scope in (SearchGeographicScope.STATE_REGION, SearchGeographicScope.COUNTRY) and not web_cap:
                    warnings.append(
                        SearchWarning(
                            code="COUNTRY_LEVEL_SEARCH_NOT_SUPPORTED",
                            message=f"Overture provider requires specific city or postal code for country '{country}'.",
                            details={"country": country, "city": city},
                        )
                    )
                else:
                    warnings.append(
                        SearchWarning(
                            code="NO_SUITABLE_PROVIDER",
                            message=f"No discovery provider is capable of handling category '{category}' for geography '{scope.value}'.",
                            details={"category": category, "geographic_scope": scope.value},
                        )
                    )

        plan = SearchPlan(
            organization_id=intent.organization_id,
            campaign_id=intent.campaign_id,
            intent_id=intent.id,
            tasks=tasks,
            warnings=warnings,
        )
        return plan
