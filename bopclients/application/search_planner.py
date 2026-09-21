"""Default search planner implementation converting SearchIntent into executable SearchPlan."""

from typing import List, Set, Optional, Tuple
from bopclients.domain.search_intent import SearchIntent
from bopclients.domain.exceptions import SearchPlanningError
from bopclients.application.search_dto import (
    SearchPlan,
    DiscoveryTask,
    SearchWarning,
)
from bopclients.application.interfaces.search_interfaces import ISearchPlanner, ILocationResolver


class DefaultSearchPlanner(ISearchPlanner):
    """Generates structured DiscoveryTasks for target discovery providers while emitting warnings for unsupported constraints."""

    def __init__(self, location_resolver: ILocationResolver):
        self.location_resolver = location_resolver

    def plan(self, intent: SearchIntent) -> SearchPlan:
        intent.validate()

        tasks: List[DiscoveryTask] = []
        warnings: List[SearchWarning] = []
        seen_task_keys: Set[Tuple[str, str, str, str]] = set()

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
        cities = intent.cities or [None]  # type: ignore

        for country in countries:
            for city in cities:
                resolved_loc = self.location_resolver.resolve(
                    country=country,
                    city=city,
                )

                if not resolved_loc or (not resolved_loc.city and not resolved_loc.postal_code):
                    warnings.append(
                        SearchWarning(
                            code="COUNTRY_LEVEL_SEARCH_NOT_SUPPORTED",
                            message=f"Overture provider requires specific city or postal code for country '{country}'.",
                            details={"country": country, "city": city},
                        )
                    )
                    continue

                for category in categories:
                    task_key = (
                        "overture",
                        category.lower(),
                        resolved_loc.country_code,
                        (resolved_loc.city or "").lower(),
                    )
                    if task_key in seen_task_keys:
                        continue
                    seen_task_keys.add(task_key)

                    task = DiscoveryTask(
                        provider="overture",
                        category=category,
                        country=resolved_loc.country_code,
                        region=resolved_loc.region_code,
                        city=resolved_loc.city,
                        postal_code=resolved_loc.postal_code,
                        latitude=resolved_loc.latitude,
                        longitude=resolved_loc.longitude,
                        radius_miles=intent.radius_miles if intent.radius_miles is not None else resolved_loc.radius_miles,
                        limit=min(intent.max_results, 1000),
                        priority=1,
                        negative_keywords=list(intent.negative_keywords),
                    )
                    tasks.append(task)

        plan = SearchPlan(
            organization_id=intent.organization_id,
            campaign_id=intent.campaign_id,
            intent_id=intent.id,
            tasks=tasks,
            warnings=warnings,
        )
        return plan
