"""Research orchestration endpoints."""

import uuid
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, status, Query
from bopclients.api.schemas.research import ResearchTriggerRequest, ResearchRunResponse
from bopclients.api.pagination import PaginationParams, PaginatedResponse
from bopclients.api.dependencies import require_permission, get_container
from bopclients.domain.auth.context import TenantContext
from bopclients.domain.auth.policy import Permission
from bopclients.domain.research_run import ResearchRun
from bopclients.domain.exceptions import EntityNotFoundError
from bopclients.runtime.container import RuntimeContainer

router = APIRouter(tags=["Research"])


def _run_to_response(r: ResearchRun) -> ResearchRunResponse:
    st = r.status or "pending"
    return ResearchRunResponse(
        id=r.id,
        organization_id=r.organization_id,
        prospect_id=r.prospect_id,
        campaign_id=r.campaign_id,
        run_type=r.run_type,
        status=st,
        display_key=f"research.status.{st.lower()}",
        started_at=r.started_at,
        completed_at=r.completed_at,
        error_message=r.error_message,
        created_at=r.created_at,
    )


@router.post(
    "/api/v1/prospects/{prospect_id}/research",
    response_model=ResearchRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger asynchronous research run for a prospect",
)
async def trigger_prospect_research(
    prospect_id: str,
    payload: ResearchTriggerRequest,
    tenant: TenantContext = Depends(require_permission(Permission.RESEARCH_RUN)),
    container: RuntimeContainer = Depends(get_container),
) -> ResearchRunResponse:
    org_id = tenant.organization_id
    prospect = container.prospect_repo.get_prospect_by_id(org_id, prospect_id)
    if not prospect:
        raise EntityNotFoundError(f"Prospect '{prospect_id}' not found.")

    if payload.campaign_id:
        campaign = container.campaign_repo.get_by_id(org_id, payload.campaign_id)
        if not campaign:
            raise EntityNotFoundError(f"Campaign '{payload.campaign_id}' not found.")

    # Idempotency / Duplicate Guard: If there is an existing pending or running research run for this prospect, return it
    existing_runs = container.research_run_repo.list_by_organization(
        org_id,
        prospect_id=prospect_id,
        limit=5,
    )
    active_run = next((r for r in existing_runs if r.status in ("pending", "running")), None)
    if active_run:
        return _run_to_response(active_run)

    now = datetime.now(timezone.utc).isoformat()
    run = ResearchRun(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        prospect_id=prospect_id,
        campaign_id=payload.campaign_id,
        run_type=payload.run_type,
        status="pending",
        created_at=now,
        updated_at=now,
    )
    saved = container.research_run_repo.save(org_id, run)
    return _run_to_response(saved)


@router.get(
    "/api/v1/research-runs",
    response_model=PaginatedResponse[ResearchRunResponse],
    status_code=status.HTTP_200_OK,
    summary="List tenant research runs",
)
async def list_research_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    prospect_id: Optional[str] = Query(default=None),
    campaign_id: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> PaginatedResponse[ResearchRunResponse]:
    params = PaginationParams(page=page, page_size=page_size)
    org_id = tenant.organization_id

    p = container.research_run_repo._placeholder()
    conditions = [f"organization_id = {p}"]
    args = [org_id]

    if prospect_id:
        conditions.append(f"prospect_id = {p}")
        args.append(prospect_id)
    if campaign_id:
        conditions.append(f"campaign_id = {p}")
        args.append(campaign_id)
    if status_filter:
        conditions.append(f"LOWER(status) = LOWER({p})")
        args.append(status_filter)

    where_sql = " AND ".join(conditions)
    count_sql = f"SELECT COUNT(*) as total FROM research_runs WHERE {where_sql}"
    count_rows = container.research_run_repo.db.fetch_dicts(count_sql, tuple(args))
    total_items = count_rows[0]["total"] if count_rows else 0

    select_sql = f"""
    SELECT * FROM research_runs WHERE {where_sql}
    ORDER BY created_at DESC
    LIMIT {params.limit} OFFSET {params.offset}
    """
    rows = container.research_run_repo.db.fetch_dicts(select_sql, tuple(args))
    runs = [container.research_run_repo._row_to_entity(r) for r in rows]

    responses = [_run_to_response(r) for r in runs]
    return PaginatedResponse.create(items=responses, total_items=total_items, params=params)
