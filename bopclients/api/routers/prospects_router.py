"""Prospect endpoints (/api/v1/prospects)."""

import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, status, Query
from bopclients.api.schemas.prospects import (
    ProspectFilterParams,
    ProspectCreate,
    ProspectResponse,
    ProspectUpdate,
    ProspectDetailResponse,
)
from bopclients.api.pagination import PaginationParams, PaginatedResponse, validate_sort_field
from bopclients.api.dependencies import require_permission, get_container
from bopclients.domain.auth.context import TenantContext
from bopclients.domain.auth.policy import Permission
from bopclients.domain.prospect import Prospect
from bopclients.domain.exceptions import EntityNotFoundError
from bopclients.runtime.container import RuntimeContainer

router = APIRouter(prefix="/api/v1/prospects", tags=["Prospects"])

ALLOWED_PROSPECT_SORT_FIELDS = {"created_at", "name", "industry", "city", "country"}


def _prospect_to_response(p: Prospect) -> ProspectResponse:
    return ProspectResponse(
        id=p.id,
        organization_id=p.organization_id,
        forge_record_id=p.forge_record_id,
        name=p.name,
        website_url=p.website_url,
        phone=p.phone,
        email=p.email,
        address=p.address,
        city=p.city,
        state=p.state,
        country=p.country,
        postal_code=p.postal_code,
        industry=p.industry,
        source=p.source,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.get(
    "",
    response_model=PaginatedResponse[ProspectResponse],
    status_code=status.HTTP_200_OK,
    summary="List and filter tenant prospects",
)
async def list_prospects(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    campaign_id: Optional[str] = Query(default=None),
    industry: Optional[str] = Query(default=None),
    city: Optional[str] = Query(default=None),
    state_code: Optional[str] = Query(default=None, alias="state"),
    country: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    sort_by: Optional[str] = Query(default="created_at"),
    sort_dir: Optional[str] = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> PaginatedResponse[ProspectResponse]:
    params = PaginationParams(page=page, page_size=page_size)
    sort_col = validate_sort_field(sort_by, ALLOWED_PROSPECT_SORT_FIELDS, "created_at")
    sort_order = "ASC" if sort_dir and sort_dir.lower() == "asc" else "DESC"

    db = container.prospect_repo.db
    p = container.prospect_repo._placeholder()

    conditions = [f"p.organization_id = {p}"]
    query_args: List[Any] = [tenant.organization_id]

    join_sql = ""
    if campaign_id:
        join_sql = f"JOIN campaign_prospects cp ON p.id = cp.prospect_id AND cp.organization_id = {p}"
        query_args.append(tenant.organization_id)
        conditions.append(f"cp.campaign_id = {p}")
        query_args.append(campaign_id)

    if industry:
        conditions.append(f"LOWER(p.industry) = LOWER({p})")
        query_args.append(industry)
    if city:
        conditions.append(f"LOWER(p.city) = LOWER({p})")
        query_args.append(city)
    if state_code:
        conditions.append(f"LOWER(p.state) = LOWER({p})")
        query_args.append(state_code)
    if country:
        conditions.append(f"LOWER(p.country) = LOWER({p})")
        query_args.append(country)
    if source:
        conditions.append(f"LOWER(p.source) = LOWER({p})")
        query_args.append(source)
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        conditions.append(f"(LOWER(p.name) LIKE {p} OR LOWER(p.website_url) LIKE {p})")
        query_args.extend([term, term])

    where_clause = " AND ".join(conditions)

    # 1. Count query
    count_sql = f"SELECT COUNT(*) as total FROM prospects p {join_sql} WHERE {where_clause}"
    count_rows = db.fetch_dicts(count_sql, tuple(query_args))
    total_items = count_rows[0]["total"] if count_rows else 0

    # 2. Select query
    select_sql = f"""
    SELECT p.* FROM prospects p {join_sql}
    WHERE {where_clause}
    ORDER BY p.{sort_col} {sort_order}
    LIMIT {params.limit} OFFSET {params.offset}
    """
    rows = db.fetch_dicts(select_sql, tuple(query_args))

    prospects = [
        Prospect(
            id=r["id"],
            organization_id=r["organization_id"],
            forge_record_id=r.get("forge_record_id"),
            name=r["name"],
            website_url=r.get("website_url"),
            phone=r.get("phone"),
            email=r.get("email"),
            address=r.get("address"),
            city=r.get("city"),
            state=r.get("state"),
            country=r.get("country", "US"),
            postal_code=r.get("postal_code"),
            industry=r.get("industry"),
            source=r.get("source"),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
        for r in rows
    ]

    responses = [_prospect_to_response(pr) for pr in prospects]
    return PaginatedResponse.create(items=responses, total_items=total_items, params=params)


@router.get(
    "/{prospect_id}",
    response_model=ProspectDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get aggregated prospect detail view",
)
async def get_prospect_detail(
    prospect_id: str,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> ProspectDetailResponse:
    org_id = tenant.organization_id
    prospect = container.prospect_repo.get_prospect_by_id(org_id, prospect_id)
    if not prospect:
        raise EntityNotFoundError(f"Prospect '{prospect_id}' not found.")

    # 1. Campaign associations
    campaign_prospects = container.prospect_repo.get_campaign_prospects_by_prospect(org_id, prospect_id)
    cp_items = [
        {
            "id": cp.id,
            "campaign_id": cp.campaign_id,
            "status": cp.status.value if hasattr(cp.status, "value") else str(cp.status),
            "priority": cp.priority,
            "added_at": cp.added_at,
        }
        for cp in campaign_prospects
    ]

    # 2. Lead score
    lead_scores = container.prospect_repo.get_lead_scores_by_prospect(org_id, prospect_id)
    latest_score = None
    if lead_scores:
        s = lead_scores[0]
        latest_score = {
            "score": s.score,
            "confidence": s.confidence,
            "components": s.components,
            "calculated_at": s.calculated_at,
        }

    # 3. Priority
    priorities = container.priority_repo.get_by_prospect(org_id, prospect_id)
    latest_priority = None
    if priorities:
        p_row = priorities[0]
        latest_priority = {
            "tier": p_row.tier.value if hasattr(p_row.tier, "value") else str(p_row.tier),
            "score": p_row.score,
            "reasons": p_row.reasons,
            "updated_at": p_row.updated_at,
        }

    # 4. Intelligence summary
    intel = container.intel_repo.get_by_prospect_id(org_id, prospect_id)
    intel_summary = None
    if intel:
        intel_summary = {
            "summary_text": intel.summary_text,
            "key_insights": intel.key_insights,
            "recommended_angle": intel.recommended_angle,
            "generated_at": intel.generated_at,
        }

    # 5. Recent signals
    signals = container.prospect_repo.get_signals_by_prospect(org_id, prospect_id)
    recent_signals = [
        {
            "id": sig.id,
            "category": sig.category.value if hasattr(sig.category, "value") else str(sig.category),
            "display_key": f"signal.category.{(sig.category.value if hasattr(sig.category, 'value') else str(sig.category)).lower()}",
            "signal_type": sig.signal_type,
            "confidence": sig.confidence,
            "headline": sig.headline,
            "detected_at": sig.detected_at,
        }
        for sig in signals[:10]
    ]

    # 6. Monitoring schedule
    schedule = container.schedule_repo.get_by_prospect(org_id, prospect_id)
    sched_dict = None
    if schedule:
        sched_dict = {
            "id": schedule.id,
            "status": schedule.status,
            "next_check_at": schedule.next_check_at,
            "last_check_at": schedule.last_check_at,
            "recommended_interval_days": schedule.recommended_interval_days,
        }

    return ProspectDetailResponse(
        prospect=_prospect_to_response(prospect),
        campaign_associations=cp_items,
        lead_score=latest_score,
        priority=latest_priority,
        intelligence_summary=intel_summary,
        recent_signals=recent_signals,
        monitoring_schedule=sched_dict,
    )


@router.get(
    "/{prospect_id}/intelligence",
    status_code=status.HTTP_200_OK,
    summary="Get intelligence snapshot for a prospect",
)
async def get_prospect_intelligence(
    prospect_id: str,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_READ)),
    container: RuntimeContainer = Depends(get_container),
):
    org_id = tenant.organization_id
    prospect = container.prospect_repo.get_prospect_by_id(org_id, prospect_id)
    if not prospect:
        raise EntityNotFoundError(f"Prospect '{prospect_id}' not found.")

    intel = container.intel_repo.get_latest(org_id, prospect_id)
    return {
        "prospect_id": prospect_id,
        "organization_id": org_id,
        "intelligence": intel.data if intel else None,
        "confidence": intel.confidence if intel else None,
        "research_version": intel.research_version if intel else None,
    }


@router.patch(
    "/{prospect_id}",
    response_model=ProspectResponse,
    status_code=status.HTTP_200_OK,
    summary="Update prospect details",
)
async def update_prospect(
    prospect_id: str,
    payload: ProspectUpdate,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_UPDATE)),
    container: RuntimeContainer = Depends(get_container),
) -> ProspectResponse:
    org_id = tenant.organization_id
    prospect = container.prospect_repo.get_prospect_by_id(org_id, prospect_id)
    if not prospect:
        raise EntityNotFoundError(f"Prospect '{prospect_id}' not found.")

    if payload.name is not None:
        prospect.name = payload.name
    if payload.website_url is not None:
        prospect.website_url = payload.website_url
    if payload.phone is not None:
        prospect.phone = payload.phone
    if payload.email is not None:
        prospect.email = payload.email
    if payload.address is not None:
        prospect.address = payload.address
    if payload.city is not None:
        prospect.city = payload.city
    if payload.state is not None:
        prospect.state = payload.state
    if payload.postal_code is not None:
        prospect.postal_code = payload.postal_code
    if payload.industry is not None:
        prospect.industry = payload.industry

    prospect.updated_at = datetime.now(timezone.utc).isoformat()
    p = container.prospect_repo._placeholder()
    sql = f"""
    UPDATE prospects SET
        name = {p}, website_url = {p}, phone = {p}, email = {p},
        address = {p}, city = {p}, state = {p}, postal_code = {p},
        industry = {p}, updated_at = {p}
    WHERE organization_id = {p} AND id = {p}
    """
    container.prospect_repo.db.execute(
        sql,
        (
            prospect.name,
            prospect.website_url,
            prospect.phone,
            prospect.email,
            prospect.address,
            prospect.city,
            prospect.state,
            prospect.postal_code,
            prospect.industry,
            prospect.updated_at,
            org_id,
            prospect_id,
        ),
    )
    container.prospect_repo.db.commit()

    return _prospect_to_response(prospect)


@router.post(
    "",
    response_model=ProspectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new prospect manually",
)
async def create_prospect(
    payload: ProspectCreate,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_UPDATE)),
    container: RuntimeContainer = Depends(get_container),
) -> ProspectResponse:
    org_id = tenant.organization_id
    company_name = (payload.company_name or payload.name or "").strip()
    if not company_name:
        company_name = "Untitled Prospect"

    website_url = payload.website_url or payload.website
    email = payload.email or payload.contact_email

    prospect = Prospect(
        id=str(uuid.uuid4()),
        organization_id=org_id,
        name=company_name,
        website_url=website_url,
        phone=payload.phone,
        email=email,
        address=payload.address,
        city=payload.city,
        state=payload.state,
        country=payload.country or "US",
        postal_code=payload.postal_code,
        industry=payload.industry,
        source=payload.source or "manual",
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    saved = container.prospect_repo.save_prospect(org_id, prospect)
    return _prospect_to_response(saved)
