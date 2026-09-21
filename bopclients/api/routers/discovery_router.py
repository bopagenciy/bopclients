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
)
from bopclients.api.dependencies import require_permission, get_container
from bopclients.domain.auth.context import TenantContext
from bopclients.domain.auth.policy import Permission
from bopclients.domain.search_intent import SearchIntent
from bopclients.domain.exceptions import EntityNotFoundError, TenantAccessError, SearchPlanningError
from bopclients.runtime.container import RuntimeContainer
from bopclients.application.search_dto import SearchPlan, DiscoveryTask, SearchWarning

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
                "radius_miles": t.radius_miles,
                "limit": t.limit,
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
                radius_miles=float(t.query_params.get("radius_miles", 10.0)) if t.query_params.get("radius_miles") is not None else 10.0,
                limit=t.query_params.get("limit", 100),
                priority=t.priority,
            )
            for t in plan_req.tasks if hasattr(plan_req, "tasks") and plan_req.tasks
        ]
        # If tasks were empty in search_plan, construct via planner
        if not tasks:
            intent = SearchIntent(
                organization_id=org_id,
                campaign_id=camp_id,
                target_market_id=plan_req.target_market_id,
                raw_query=plan_req.raw_query,
                industries=plan_req.industries,
                business_categories=plan_req.business_categories,
                countries=plan_req.countries,
                regions=plan_req.regions,
                cities=plan_req.cities,
                radius_miles=plan_req.radius_miles,
                languages=plan_req.languages,
                company_size_min=plan_req.company_size_min,
                company_size_max=plan_req.company_size_max,
                company_sizes=plan_req.company_sizes,
                decision_maker_roles=plan_req.decision_maker_roles,
                keywords=plan_req.keywords,
                negative_keywords=plan_req.negative_keywords,
                services_to_offer=plan_req.services_to_offer,
                desired_signals=plan_req.desired_signals,
                max_results=plan_req.max_results or 100,
            )
            plan = container.search_service.plan_search(intent)
        else:
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
