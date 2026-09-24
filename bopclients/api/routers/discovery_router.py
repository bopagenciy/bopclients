"""Discovery endpoints (/api/v1/discovery) for natural language search intent, planning, and execution."""

import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, status, HTTPException
from bopclients.api.schemas.discovery import (
    SearchIntentRequest,
    SearchIntentResponse,
    SearchPlanRequest,
    SearchPlanResponse,
    DiscoveryTaskResponse,
    DiscoveryExecutionRequest,
    DiscoveryExecutionResponse,
    DiscoveredProspectSummary,
    DiscoveryPreviewRequest,
    DiscoveryPreviewResponse,
    DiscoveryPreviewDiagnostics,
    DiscoveryCandidateSummary,
)
from bopclients.api.dependencies import require_permission, get_container, get_tenant_context
from bopclients.domain.enums import MemberRole
from bopclients.domain.auth.context import TenantContext
from bopclients.domain.auth.policy import Permission
from bopclients.domain.search_intent import SearchIntent
from bopclients.domain.exceptions import EntityNotFoundError, TenantAccessError, SearchPlanningError
from bopclients.runtime.container import RuntimeContainer
from bopclients.application.search_dto import SearchPlan, DiscoveryTask, SearchWarning
from bopclients.domain.normalizers import CategoryNormalizer
from bopclients.infrastructure.providers.overture_provider import EXCLUDED_FACILITY_CATEGORIES, haversine_distance_miles

router = APIRouter(prefix="/api/v1/discovery", tags=["Discovery"])


def _intent_to_response(intent: SearchIntent) -> SearchIntentResponse:
    return SearchIntentResponse(
        organization_id=intent.organization_id,
        campaign_id=intent.campaign_id,
        target_market_id=intent.target_market_id,
        raw_query=intent.raw_query,
        industries=intent.industries or [],
        business_categories=intent.business_categories or [],
        countries=intent.countries or [],
        regions=intent.regions or [],
        cities=intent.cities or [],
        radius_miles=intent.radius_miles,
        languages=intent.languages or [],
        company_size_min=intent.company_size_min,
        company_size_max=intent.company_size_max,
        company_sizes=intent.company_sizes or [],
        decision_maker_roles=intent.decision_maker_roles or [],
        keywords=intent.keywords or [],
        negative_keywords=intent.negative_keywords or [],
        services_to_offer=intent.services_to_offer or [],
        desired_signals=intent.desired_signals or [],
        max_results=intent.max_results or 100,
    )


def _plan_to_response(plan: SearchPlan) -> SearchPlanResponse:
    tasks = [
        DiscoveryTaskResponse(
            task_id=t.id,
            provider=t.provider,
            query_params={
                "query": t.query,
                "category": t.category,
                "city": t.city,
                "region": t.region,
                "country": t.country,
                "postal_code": t.postal_code,
                "latitude": t.latitude,
                "longitude": t.longitude,
                "radius_miles": t.radius_miles,
                "limit": t.limit,
                "negative_keywords": t.negative_keywords,
            },
            priority=t.priority,
            status="pending",
            estimated_items=t.limit,
        )
        for t in plan.tasks
    ]
    warning_msgs = [w.message for w in plan.warnings]
    return SearchPlanResponse(
        organization_id=plan.organization_id,
        campaign_id=plan.campaign_id,
        tasks=tasks,
        warnings=warning_msgs,
        estimated_total_cost_credits=0.0,
        generated_at=getattr(plan, "created_at", datetime.now(timezone.utc).isoformat()),
    )


@router.post(
    "/intents",
    response_model=SearchIntentResponse,
    status_code=status.HTTP_200_OK,
    summary="Parse natural language prospecting query into structured SearchIntent",
)
async def parse_intent(
    payload: SearchIntentRequest,
    tenant: TenantContext = Depends(require_permission(Permission.CAMPAIGN_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> SearchIntentResponse:
    org_id = tenant.organization_id

    if payload.campaign_id:
        camp = container.campaign_repo.get_by_id(org_id, payload.campaign_id)
        if not camp:
            raise EntityNotFoundError(f"Campaign '{payload.campaign_id}' not found.")

    intent = container.search_service.parse_search_intent(
        org_id=org_id,
        campaign_id=payload.campaign_id,
        raw_query=payload.raw_query,
        context=payload.context,
        target_market_id=payload.target_market_id,
    )
    return _intent_to_response(intent)


@router.post(
    "/plans",
    response_model=SearchPlanResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate SearchPlan preview from SearchIntent without executing discovery",
)
async def plan_search(
    payload: SearchPlanRequest,
    tenant: TenantContext = Depends(require_permission(Permission.CAMPAIGN_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> SearchPlanResponse:
    org_id = tenant.organization_id

    if payload.campaign_id:
        camp = container.campaign_repo.get_by_id(org_id, payload.campaign_id)
        if not camp:
            raise EntityNotFoundError(f"Campaign '{payload.campaign_id}' not found.")

    intent = SearchIntent(
        organization_id=org_id,
        campaign_id=payload.campaign_id,
        target_market_id=payload.target_market_id,
        raw_query=payload.raw_query,
        industries=payload.industries,
        business_categories=payload.business_categories,
        countries=payload.countries,
        regions=payload.regions,
        cities=payload.cities,
        radius_miles=payload.radius_miles,
        languages=payload.languages,
        company_size_min=payload.company_size_min,
        company_size_max=payload.company_size_max,
        company_sizes=payload.company_sizes,
        decision_maker_roles=payload.decision_maker_roles,
        keywords=payload.keywords,
        negative_keywords=payload.negative_keywords,
        services_to_offer=payload.services_to_offer,
        desired_signals=payload.desired_signals,
        max_results=payload.max_results or 100,
    )

    plan = container.search_service.plan_search(intent)
    return _plan_to_response(plan)


def _validate_submitted_tasks(
    tasks: List[DiscoveryTask],
    plan_req: Any,
    camp: Any,
    icp: Any,
    container: RuntimeContainer,
) -> None:
    """Validate submitted tasks against server-authoritative campaign, ICP, market and provider constraints.

    Guards against client-side payload tampering:
    - Provider must be supported and registered in the orchestrator.
    - Limit must be within safe bounds (1 <= limit <= 1000).
    - Radius must be within safe bounds (0 < radius <= 100.0) and respect target market limits.
    - Category must be supported, not an excluded facility, and authorized for the campaign.
    - Required exclusions (negative keywords) must be preserved.
    - Geography must match configured target markets unless an authorized override exists.
    - No unexpected extra tasks or unauthorized category injections.
    """
    if not tasks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Execution plan must contain at least one task.",
        )

    # 1. Registered providers check (Tamper E)
    allowed_providers = {"overture"}
    orchestrator = getattr(container.search_service, "orchestrator", None) if container.search_service else None
    if orchestrator and hasattr(orchestrator, "providers"):
        allowed_providers.update(orchestrator.providers.keys())

    target_markets = icp.target_markets if icp and hasattr(icp, "target_markets") and icp.target_markets else []
    max_market_radius = max((float(m.radius_miles) for m in target_markets if m.radius_miles is not None), default=100.0)
    icp_industries = [CategoryNormalizer.normalize(ind) for ind in (getattr(icp, "industries", []) or [])]
    icp_industries = [i for i in icp_industries if i]

    # Required negative keywords from ICP or association domain policy
    camp_name = (getattr(camp, "name", "") or "").lower()
    is_association_campaign = (
        any("association" in ind or "society" in ind for ind in icp_industries)
        or "asociaciones" in camp_name
        or "asociación" in camp_name
        or "association" in camp_name
    )

    seen_task_keys = set()

    for task in tasks:
        # Web search / Tavily preview-only enforcement
        if task.provider.lower() in ("web_search", "tavily"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Direct prospect import is not authorized for web search / Tavily. Preview mode only.",
            )

        # Provider validation (E)
        if task.provider.lower() not in allowed_providers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported discovery provider '{task.provider}'.",
            )

        # Execution limit validation (F)
        if task.limit <= 0 or task.limit > 1000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task limit {task.limit} is invalid or exceeds maximum allowed limit of 1000.",
            )

        # Radius validation (A)
        if task.radius_miles <= 0 or task.radius_miles > 100.0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task radius {task.radius_miles} miles exceeds maximum supported discovery radius (100 miles).",
            )
        if target_markets and task.radius_miles > max_market_radius * 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Task radius {task.radius_miles} miles exceeds configured target market bounds ({max_market_radius} miles).",
            )

        # Category validation (C)
        task_cat = (task.category or "").strip().lower()
        if not task_cat:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Task category cannot be empty.",
            )

        # Excluded facility category check for association campaigns (C)
        if is_association_campaign and task_cat in EXCLUDED_FACILITY_CATEGORIES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Category '{task_cat}' is an excluded facility category and cannot be targeted.",
            )

        # Check if category matches task's own negative keywords
        task_negs = [nk.strip().lower() for nk in (task.negative_keywords or []) if nk.strip()]
        if task_cat in task_negs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Category '{task_cat}' conflicts with configured negative keywords.",
            )

        # Provider category support check
        if orchestrator and hasattr(orchestrator, "providers"):
            provider_inst = orchestrator.providers.get(task.provider.lower())
            if provider_inst and hasattr(provider_inst, "is_category_supported"):
                if not provider_inst.is_category_supported(task_cat):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Category '{task_cat}' is not supported by provider '{task.provider}'.",
                    )

        # Required exclusions preservation check (B)
        if is_association_campaign:
            has_facility_exclusions = any(
                nk in ("clinic", "clínica", "clinica", "hospital", "medical_office")
                for nk in task_negs
            )
            if not has_facility_exclusions:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Association discovery requires explicit clinic/hospital exclusions.",
                )

        # Geographic alignment with Target Market (D)
        if target_markets:
            market_cities = {m.city.lower() for m in target_markets if m.city}
            market_countries = {m.country.upper() for m in target_markets if m.country}
            task_city = (task.city or "").strip().lower()
            task_country = (task.country or "").strip().upper()

            city_matched = not market_cities or task_city in market_cities
            country_matched = not market_countries or task_country in market_countries
            if not (city_matched and country_matched):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Task geographic center '{task.city}, {task.country}' does not match campaign target markets.",
                )

        # Coordinate recovery and integrity validation
        resolver = getattr(container.search_service.search_planner, "location_resolver", None) if getattr(container, "search_service", None) and hasattr(container.search_service, "search_planner") else None
        canonical_loc = resolver.resolve(country=task.country, city=task.city, postal_code=task.postal_code) if resolver else None

        if task.latitude is None or task.longitude is None:
            if canonical_loc and canonical_loc.latitude is not None and canonical_loc.longitude is not None:
                task.latitude = canonical_loc.latitude
                task.longitude = canonical_loc.longitude
            elif task.provider.lower() == "overture" and (task.country or "US").upper() != "US":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Task geographic center '{task.city}, {task.country}' has no valid coordinates and cannot be resolved.",
                )
        else:
            if canonical_loc and canonical_loc.latitude is not None and canonical_loc.longitude is not None:
                dist = haversine_distance_miles(task.latitude, task.longitude, canonical_loc.latitude, canonical_loc.longitude)
                allowed_deviation = max(task.radius_miles or 25.0, 30.0)
                if dist > allowed_deviation:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Task coordinates ({task.latitude:.4f}, {task.longitude:.4f}) deviate from canonical location '{task.city}, {task.country}'.",
                    )

        # Unexpected task check (G)
        task_key = (task.provider.lower(), task_cat, (task.country or "").upper(), (task.city or "").lower())
        if task_key in seen_task_keys:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate task detected for '{task_cat}' in '{task.city}'.",
            )
        seen_task_keys.add(task_key)

        # Verify task category is consistent with campaign ICP industries
        if icp_industries:
            cat_norm = CategoryNormalizer.normalize(task_cat)
            if cat_norm not in icp_industries and task_cat not in icp_industries:
                alias_matched = any(
                    CategoryNormalizer.normalize(ind) == cat_norm
                    for ind in icp_industries
                )
                if not alias_matched:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Unexpected task category '{task_cat}' is not authorized for this campaign.",
                    )


@router.post(
    "/execute",
    response_model=DiscoveryExecutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute discovery plan and import discovered businesses as campaign prospects",
)
async def execute_discovery(
    payload: DiscoveryExecutionRequest,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_UPDATE)),
    container: RuntimeContainer = Depends(get_container),
) -> DiscoveryExecutionResponse:
    org_id = tenant.organization_id
    camp_id = payload.campaign_id

    camp = container.campaign_repo.get_by_id(org_id, camp_id)
    if not camp:
        raise EntityNotFoundError(f"Campaign '{camp_id}' not found.")

    status_val = camp.status.value if hasattr(camp.status, "value") else str(camp.status)
    if status_val.lower() != "active":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Campaign '{camp_id}' status is '{status_val}'. Discovery execution requires an 'active' campaign.",
        )

    # Build or reconstruct SearchPlan
    if payload.search_plan:
        plan_req = payload.search_plan

        # Validate tenant and campaign alignment if provided in plan
        if getattr(plan_req, "organization_id", None) and plan_req.organization_id != org_id:
            raise TenantAccessError(f"Search plan organization '{plan_req.organization_id}' does not match authenticated organization '{org_id}'.")
        if getattr(plan_req, "campaign_id", None) and plan_req.campaign_id != camp_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Search plan campaign '{plan_req.campaign_id}' does not match target campaign '{camp_id}'.",
            )

        tasks = [
            DiscoveryTask(
                id=t.task_id or str(uuid.uuid4()),
                provider=t.provider,
                query=t.query_params.get("query"),
                category=t.query_params.get("category"),
                city=t.query_params.get("city"),
                region=t.query_params.get("region"),
                country=t.query_params.get("country", "US"),
                postal_code=t.query_params.get("postal_code"),
                latitude=float(t.query_params["latitude"]) if t.query_params.get("latitude") is not None else None,
                longitude=float(t.query_params["longitude"]) if t.query_params.get("longitude") is not None else None,
                radius_miles=float(t.query_params.get("radius_miles", 10.0)) if t.query_params.get("radius_miles") is not None else 10.0,
                limit=int(t.query_params.get("limit", 100)) if t.query_params.get("limit") is not None else 100,
                priority=t.priority,
                negative_keywords=t.query_params.get("negative_keywords") or [],
            )
            for t in plan_req.tasks if hasattr(plan_req, "tasks") and plan_req.tasks
        ]
        # If tasks were empty in search_plan, construct via planner using campaign context and intent parsing
        if not tasks:
            raw_q = getattr(plan_req, "raw_query", None)
            if not raw_q:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="search_plan must contain tasks or a valid raw_query.",
                )
            intent = container.search_service.parse_search_intent(
                org_id=org_id,
                campaign_id=camp_id,
                raw_query=raw_q,
                target_market_id=getattr(plan_req, "target_market_id", None),
            )
            # Overlay any explicit plan_req criteria provided by caller while preserving campaign ICP defaults
            if getattr(plan_req, "industries", None):
                intent.industries = list(plan_req.industries)
            if getattr(plan_req, "business_categories", None):
                intent.business_categories = list(plan_req.business_categories)
            if getattr(plan_req, "countries", None):
                intent.countries = list(plan_req.countries)
            if getattr(plan_req, "regions", None):
                intent.regions = list(plan_req.regions)
            if getattr(plan_req, "cities", None):
                intent.cities = list(plan_req.cities)
            if getattr(plan_req, "radius_miles", None) is not None:
                intent.radius_miles = float(plan_req.radius_miles)
            if getattr(plan_req, "languages", None):
                intent.languages = list(plan_req.languages)
            if getattr(plan_req, "company_size_min", None) is not None:
                intent.company_size_min = plan_req.company_size_min
            if getattr(plan_req, "company_size_max", None) is not None:
                intent.company_size_max = plan_req.company_size_max
            if getattr(plan_req, "company_sizes", None):
                intent.company_sizes = list(plan_req.company_sizes)
            if getattr(plan_req, "decision_maker_roles", None):
                intent.decision_maker_roles = list(plan_req.decision_maker_roles)
            if getattr(plan_req, "keywords", None):
                for kw in plan_req.keywords:
                    if kw not in intent.keywords:
                        intent.keywords.append(kw)
            if getattr(plan_req, "negative_keywords", None):
                for nk in plan_req.negative_keywords:
                    if nk not in intent.negative_keywords:
                        intent.negative_keywords.append(nk)
            if getattr(plan_req, "services_to_offer", None):
                intent.services_to_offer = list(plan_req.services_to_offer)
            if getattr(plan_req, "desired_signals", None):
                for sig in plan_req.desired_signals:
                    if sig not in intent.desired_signals:
                        intent.desired_signals.append(sig)
            if getattr(plan_req, "max_results", None):
                intent.max_results = int(plan_req.max_results)

            plan = container.search_service.plan_search(intent)
        else:
            icp = container.icp_repo.get_by_id(org_id, camp.icp_id) if (camp.icp_id and getattr(container, "icp_repo", None)) else None
            _validate_submitted_tasks(tasks, plan_req, camp, icp, container)
            plan = SearchPlan(
                id=str(uuid.uuid4()),
                organization_id=org_id,
                campaign_id=camp_id,
                tasks=tasks,
            )
    elif payload.raw_query:
        intent = container.search_service.parse_search_intent(
            org_id=org_id,
            campaign_id=camp_id,
            raw_query=payload.raw_query,
        )
        plan = container.search_service.plan_search(intent)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'search_plan' or 'raw_query' must be provided for discovery execution.",
        )

    result = container.search_service.execute_search(
        org_id=org_id,
        campaign_id=camp_id,
        search_plan=plan,
    )

    imported_summaries = [
        DiscoveredProspectSummary(
            id=p.id,
            name=p.name,
            website_url=p.website_url,
            phone=p.phone,
            city=p.city,
            state=p.state,
            country=p.country,
            industry=p.industry,
            source=p.source,
        )
        for p in (result.imported_prospects or [])
    ]

    exec_status = "completed"
    if result.tasks_failed > 0 and result.tasks_succeeded > 0:
        exec_status = "partial"
    elif result.tasks_failed > 0 and result.tasks_succeeded == 0:
        exec_status = "failed"

    return DiscoveryExecutionResponse(
        status=exec_status,
        campaign_id=camp_id,
        tasks_executed=result.tasks_total,
        tasks_succeeded=result.tasks_succeeded,
        tasks_failed=result.tasks_failed,
        discovered_businesses_count=result.total_discovered_raw,
        prospects_created=result.prospects_created,
        prospects_reused=result.prospects_reused,
        total_imported_prospects=result.total_imported_prospects,
        imported_prospects=imported_summaries,
        errors=result.errors or [],
    )


@router.post(
    "/preview",
    response_model=DiscoveryPreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute discovery preview returning candidate entities without database persistence",
)
async def preview_discovery(
    payload: DiscoveryPreviewRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    container: RuntimeContainer = Depends(get_container),
) -> DiscoveryPreviewResponse:
    org_id = tenant.organization_id

    # 1. Role Authorization Gate: Admin/Owner only
    if tenant.role not in (MemberRole.ADMIN, MemberRole.OWNER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tenant administrators may initiate discovery preview.",
        )

    # 2. Campaign Validation if campaign_id is provided
    camp_id = payload.campaign_id
    if camp_id:
        camp = container.campaign_repo.get_by_id(org_id, camp_id)
        if not camp:
            raise EntityNotFoundError(f"Campaign '{camp_id}' not found.")

    provider_name = (payload.provider or "web_search").strip().lower()

    # 3. Provider Gate & Tenant Authorization check for web_search / tavily
    if provider_name in ("web_search", "tavily"):
        orchestrator = container.discovery_orchestrator or (
            container.search_service.orchestrator if container.search_service else None
        )
        web_prov = orchestrator.providers.get("web_search") if orchestrator else None
        if not web_prov or not web_prov.enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Web search discovery provider is disabled by default. Explicit configuration required.",
            )
        if web_prov.authorized_tenants is not None and org_id not in web_prov.authorized_tenants:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Tenant '{org_id}' is not authorized for web search discovery.",
            )

    # 4. Construct SearchPlan
    if payload.search_plan:
        plan_req = payload.search_plan
        # Validate tenant match
        if getattr(plan_req, "organization_id", None) and plan_req.organization_id != org_id:
            raise TenantAccessError(f"Search plan organization '{plan_req.organization_id}' does not match authenticated organization '{org_id}'.")

        tasks = [
            DiscoveryTask(
                id=t.task_id or str(uuid.uuid4()),
                provider=t.provider,
                query=t.query_params.get("query"),
                category=t.query_params.get("category"),
                city=t.query_params.get("city"),
                region=t.query_params.get("region"),
                country=t.query_params.get("country", "CO"),
                postal_code=t.query_params.get("postal_code"),
                limit=int(t.query_params.get("limit", 5)) if t.query_params.get("limit") is not None else 5,
                priority=t.priority,
                negative_keywords=t.query_params.get("negative_keywords") or [],
                metadata={"organization_id": org_id, "preview": True},
            )
            for t in plan_req.tasks if hasattr(plan_req, "tasks") and plan_req.tasks
        ]

        if not tasks and getattr(plan_req, "raw_query", None):
            plan = container.search_service.create_web_search_preview_plan(
                org_id=org_id,
                query=plan_req.raw_query,
                campaign_id=camp_id,
                limit=min(getattr(plan_req, "max_results", 5) or 5, 5),
            )
        elif not tasks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="search_plan must contain tasks or a valid raw_query.",
            )
        else:
            # Enforce budget: maximum 1 web search task, limit <= 5
            web_tasks = [t for t in tasks if t.provider.lower() in ("web_search", "tavily")]
            if len(web_tasks) > 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Controlled preview budget violation: Maximum 1 web search query allowed (received {len(web_tasks)}).",
                )
            for wt in web_tasks:
                if wt.limit > 5:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Controlled preview budget violation: Task limit ({wt.limit}) exceeds maximum allowed of 5 results.",
                    )
            plan = SearchPlan(
                id=str(uuid.uuid4()),
                organization_id=org_id,
                campaign_id=camp_id,
                tasks=tasks,
            )
    elif payload.raw_query:
        plan = container.search_service.create_web_search_preview_plan(
            org_id=org_id,
            query=payload.raw_query,
            campaign_id=camp_id,
            limit=5,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'search_plan' or 'raw_query' must be provided for discovery preview.",
        )

    # 5. Execute preview (zero persistence)
    result = container.search_service.preview_search(
        org_id=org_id,
        campaign_id=camp_id,
        search_plan=plan,
    )

    candidate_summaries = [
        DiscoveryCandidateSummary(
            candidate_id=c.get("candidate_id", ""),
            name=c.get("name", ""),
            website_url=c.get("website_url"),
            category=c.get("category"),
            city=c.get("city"),
            state=c.get("state"),
            country=c.get("country"),
            geographic_scope=c.get("geographic_scope"),
            classification_status=c.get("classification_status"),
            classification_details=c.get("classification_details"),
            title=c.get("title"),
            snippet=c.get("snippet"),
            source=c.get("source"),
            qualification_status=c.get("qualification_status"),
            entity_archetype=c.get("entity_archetype"),
            geographic_evidence_status=c.get("geographic_evidence_status"),
            current_activity_status=c.get("current_activity_status"),
            source_url=c.get("source_url"),
            source_host=c.get("source_host"),
            organization_website=c.get("organization_website"),
            is_commercial_review_ready=c.get("is_commercial_review_ready"),
            qualification_reasons=c.get("qualification_reasons"),
            missing_evidence=c.get("missing_evidence"),
        )
        for c in (result.candidates or [])
    ]

    exec_status = "completed"
    if result.tasks_failed > 0 and result.tasks_succeeded == 0:
        exec_status = "failed"
    elif result.tasks_failed > 0 and result.tasks_succeeded > 0:
        exec_status = "partial"

    warning_msgs = [w.message for w in result.warnings]

    diagnostics_obj = None
    if getattr(result, "diagnostics", None):
        d_dict = dict(result.diagnostics)
        d_dict["candidates_returned_to_preview"] = len(candidate_summaries)
        diagnostics_obj = DiscoveryPreviewDiagnostics(**d_dict)

    return DiscoveryPreviewResponse(
        status=exec_status,
        organization_id=org_id,
        campaign_id=camp_id,
        provider=provider_name,
        tasks_executed=result.tasks_total,
        candidates_count=len(candidate_summaries),
        candidates=candidate_summaries,
        prospects_inserted=0,
        sources_inserted=0,
        database_writes=0,
        warnings=warning_msgs,
        errors=result.errors or [],
        diagnostics=diagnostics_obj,
    )
