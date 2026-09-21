import io
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, status, Query, HTTPException, Response, Request
from fastapi.responses import StreamingResponse
from bopclients.api.schemas.prospects import (
    ProspectFilterParams,
    ProspectCreate,
    ProspectResponse,
    ProspectUpdate,
    ProspectDetailResponse,
    BulkAddToCampaignRequest,
    BulkAddToCampaignResponse,
    BulkRecalculateScoreRequest,
    BulkRecalculateScoreResponse,
    BulkRecalculatePriorityRequest,
    BulkRecalculatePriorityResponse,
    BulkResearchRequest,
    BulkResearchResponse,
    BulkExportRequest,
    CrmHandoffResponse,
    CrmHandoffStatusResponse,
    BulkCrmHandoffRequest,
    BulkCrmHandoffResponse,
)
from bopclients.api.pagination import PaginationParams, PaginatedResponse, validate_sort_field
from bopclients.api.dependencies import require_permission, get_container
from bopclients.api.errors import resolve_request_locale
from bopclients.domain.auth.context import TenantContext
from bopclients.domain.auth.policy import Permission
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.prospect import Prospect
from bopclients.domain.research_run import ResearchRun
from bopclients.domain.exceptions import EntityNotFoundError
from bopclients.runtime.container import RuntimeContainer

router = APIRouter(prefix="/api/v1/prospects", tags=["Prospects"])

ALLOWED_PROSPECT_SORT_FIELDS = {
    "created_at",
    "updated_at",
    "name",
    "industry",
    "city",
    "state",
    "country",
    "lead_score",
    "priority",
}


def _csv_escape(val: Any) -> str:
    """Safely format and escape a cell for CSV export to prevent formula injection."""
    if val is None:
        return ""
    s = str(val)
    # Mitigate CSV / spreadsheet formula injection attacks
    if s.startswith(("=", "+", "-", "@")):
        s = "'" + s
    if '"' in s or "," in s or "\n" in s or "\r" in s:
        s = '"' + s.replace('"', '""') + '"'
    return s


def _prospect_to_response(
    p: Prospect,
    lead_score: Optional[int] = None,
    priority_tier: Optional[str] = None,
    campaign_count: Optional[int] = None,
    campaign_names: Optional[List[str]] = None,
    signals_count: Optional[int] = None,
) -> ProspectResponse:
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
        lead_score=lead_score,
        priority_tier=priority_tier,
        campaign_count=campaign_count if campaign_count is not None else 0,
        campaign_names=campaign_names or [],
        signals_count=signals_count if signals_count is not None else 0,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _hydrate_prospect_summaries(
    db: Any, placeholder: str, org_id: str, prospect_ids: List[str]
) -> Dict[str, Dict[str, Any]]:
    """Hydrate operational summary fields (lead_score, priority_tier, campaign info, signal counts) in bulk batches."""
    if not prospect_ids:
        return {}

    summaries: Dict[str, Dict[str, Any]] = {
        pid: {
            "lead_score": None,
            "priority_tier": None,
            "campaign_count": 0,
            "campaign_names": [],
            "signals_count": 0,
        }
        for pid in prospect_ids
    }

    in_clause = ", ".join([placeholder] * len(prospect_ids))

    # 1. Hydrate lead scores
    try:
        sql_scores = f"""
            SELECT prospect_id, score
            FROM lead_scores
            WHERE organization_id = {placeholder} AND prospect_id IN ({in_clause})
        """
        score_rows = db.fetch_dicts(sql_scores, tuple([org_id] + prospect_ids))
        for r in score_rows:
            pid = r["prospect_id"]
            if pid in summaries:
                summaries[pid]["lead_score"] = r.get("score")
    except Exception:
        pass

    # 2. Hydrate latest priority tier
    try:
        sql_priorities = f"""
            SELECT prospect_id, priority_label
            FROM prospect_priorities
            WHERE organization_id = {placeholder} AND prospect_id IN ({in_clause})
            ORDER BY updated_at DESC
        """
        priority_rows = db.fetch_dicts(sql_priorities, tuple([org_id] + prospect_ids))
        for r in priority_rows:
            pid = r["prospect_id"]
            if pid in summaries and summaries[pid]["priority_tier"] is None:
                summaries[pid]["priority_tier"] = r.get("priority_label")
    except Exception:
        pass

    # 3. Hydrate campaign memberships and names
    try:
        sql_campaigns = f"""
            SELECT cp.prospect_id, c.name as campaign_name
            FROM campaign_prospects cp
            JOIN campaigns c ON cp.campaign_id = c.id AND cp.organization_id = c.organization_id
            WHERE cp.organization_id = {placeholder} AND cp.prospect_id IN ({in_clause})
            ORDER BY c.name ASC
        """
        camp_rows = db.fetch_dicts(sql_campaigns, tuple([org_id] + prospect_ids))
        for r in camp_rows:
            pid = r["prospect_id"]
            if pid in summaries:
                summaries[pid]["campaign_count"] += 1
                cname = r.get("campaign_name")
                if cname and cname not in summaries[pid]["campaign_names"]:
                    summaries[pid]["campaign_names"].append(cname)
    except Exception:
        pass

    # 4. Hydrate signals count
    try:
        sql_signals = f"""
            SELECT prospect_id, COUNT(*) as sig_cnt
            FROM signals
            WHERE organization_id = {placeholder} AND prospect_id IN ({in_clause})
            GROUP BY prospect_id
        """
        sig_rows = db.fetch_dicts(sql_signals, tuple([org_id] + prospect_ids))
        for r in sig_rows:
            pid = r["prospect_id"]
            if pid in summaries:
                summaries[pid]["signals_count"] = int(r.get("sig_cnt", 0))
    except Exception:
        pass

    return summaries


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
    priority: Optional[str] = Query(default=None),
    score_min: Optional[int] = Query(default=None, ge=0, le=100),
    score_max: Optional[int] = Query(default=None, ge=0, le=100),
    unscored: Optional[bool] = Query(default=None),
    has_signals: Optional[bool] = Query(default=None),
    industry: Optional[str] = Query(default=None),
    city: Optional[str] = Query(default=None),
    state_code: Optional[str] = Query(default=None, alias="state"),
    country: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    sort_by: Optional[str] = Query(default="created_at"),
    sort_dir: Optional[str] = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> PaginatedResponse[ProspectResponse]:
    params = PaginationParams(page=page, page_size=page_size)
    if sort_by:
        sort_clean = sort_by.strip().lower()
        if sort_clean not in ALLOWED_PROSPECT_SORT_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid sort field '{sort_by}'. Must be one of: {sorted(ALLOWED_PROSPECT_SORT_FIELDS)}",
            )
        sort_col = sort_clean
    else:
        sort_col = "created_at"

    sort_order = "ASC" if sort_dir and sort_dir.lower() == "asc" else "DESC"

    db = container.prospect_repo.db
    p = container.prospect_repo._placeholder()

    conditions = [f"p.organization_id = {p}"]
    query_args: List[Any] = [tenant.organization_id]

    join_sql = ""
    if campaign_id:
        join_sql += f" JOIN campaign_prospects cp ON p.id = cp.prospect_id AND cp.organization_id = {p}"
        query_args.append(tenant.organization_id)
        conditions.append(f"cp.campaign_id = {p}")
        query_args.append(campaign_id)

    if priority:
        join_sql += f" JOIN prospect_priorities pp_filter ON p.id = pp_filter.prospect_id AND pp_filter.organization_id = {p}"
        query_args.append(tenant.organization_id)
        conditions.append(f"LOWER(pp_filter.priority_label) = LOWER({p})")
        query_args.append(priority)

    if unscored:
        conditions.append(
            f"NOT EXISTS (SELECT 1 FROM lead_scores ls_u WHERE ls_u.prospect_id = p.id AND ls_u.organization_id = {p})"
        )
        query_args.append(tenant.organization_id)
    else:
        if score_min is not None:
            conditions.append(
                f"EXISTS (SELECT 1 FROM lead_scores ls_min WHERE ls_min.prospect_id = p.id AND ls_min.organization_id = {p} AND ls_min.score >= {p})"
            )
            query_args.extend([tenant.organization_id, score_min])
        if score_max is not None:
            conditions.append(
                f"EXISTS (SELECT 1 FROM lead_scores ls_max WHERE ls_max.prospect_id = p.id AND ls_max.organization_id = {p} AND ls_max.score <= {p})"
            )
            query_args.extend([tenant.organization_id, score_max])

    if has_signals is True:
        conditions.append(
            f"EXISTS (SELECT 1 FROM signals s_has WHERE s_has.prospect_id = p.id AND s_has.organization_id = {p})"
        )
        query_args.append(tenant.organization_id)
    elif has_signals is False:
        conditions.append(
            f"NOT EXISTS (SELECT 1 FROM signals s_has WHERE s_has.prospect_id = p.id AND s_has.organization_id = {p})"
        )
        query_args.append(tenant.organization_id)

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

    search_query = (q or search or "").strip()
    if search_query:
        term = f"%{search_query.lower()}%"
        conditions.append(f"(LOWER(p.name) LIKE {p} OR LOWER(COALESCE(p.website_url, '')) LIKE {p})")
        query_args.extend([term, term])

    where_clause = " AND ".join(conditions)

    # Order by clause handling
    if sort_col == "lead_score":
        order_clause = f"COALESCE((SELECT ls_ord.score FROM lead_scores ls_ord WHERE ls_ord.prospect_id = p.id AND ls_ord.organization_id = p.organization_id LIMIT 1), -1) {sort_order}, p.created_at DESC"
    elif sort_col == "priority":
        order_clause = f"COALESCE((SELECT pp_ord.priority_score FROM prospect_priorities pp_ord WHERE pp_ord.prospect_id = p.id AND pp_ord.organization_id = p.organization_id ORDER BY pp_ord.updated_at DESC LIMIT 1), -1) {sort_order}, p.created_at DESC"
    else:
        order_clause = f"p.{sort_col} {sort_order}, p.id ASC"

    # 1. Count query
    count_sql = f"SELECT COUNT(*) as total FROM prospects p {join_sql} WHERE {where_clause}"
    count_rows = db.fetch_dicts(count_sql, tuple(query_args))
    total_items = count_rows[0]["total"] if count_rows else 0

    # 2. Select query
    select_sql = f"""
    SELECT p.* FROM prospects p {join_sql}
    WHERE {where_clause}
    ORDER BY {order_clause}
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

    pids = [pr.id for pr in prospects]
    hydrated = _hydrate_prospect_summaries(db, p, tenant.organization_id, pids)

    responses = [
        _prospect_to_response(
            pr,
            lead_score=hydrated.get(pr.id, {}).get("lead_score"),
            priority_tier=hydrated.get(pr.id, {}).get("priority_tier"),
            campaign_count=hydrated.get(pr.id, {}).get("campaign_count", 0),
            campaign_names=hydrated.get(pr.id, {}).get("campaign_names", []),
            signals_count=hydrated.get(pr.id, {}).get("signals_count", 0),
        )
        for pr in prospects
    ]
    return PaginatedResponse.create(items=responses, total_items=total_items, params=params)


def _generate_prospects_csv(
    db: Any, placeholder: str, org_id: str, prospects: List[Prospect]
) -> str:
    """Generate CSV string with formula injection protection and bulk hydration."""
    pids = [pr.id for pr in prospects]
    hydrated = _hydrate_prospect_summaries(db, placeholder, org_id, pids)

    headers = [
        "ID",
        "Company Name",
        "Website",
        "Phone",
        "Email",
        "City",
        "State",
        "Country",
        "Industry",
        "Source",
        "Lead Score",
        "Priority Tier",
        "Campaigns",
        "Signals Count",
        "Created At",
    ]

    lines = [",".join(headers)]
    for pr in prospects:
        info = hydrated.get(pr.id, {})
        camp_str = "; ".join(info.get("campaign_names", []))
        row = [
            _csv_escape(pr.id),
            _csv_escape(pr.name),
            _csv_escape(pr.website_url),
            _csv_escape(pr.phone),
            _csv_escape(pr.email),
            _csv_escape(pr.city),
            _csv_escape(pr.state),
            _csv_escape(pr.country),
            _csv_escape(pr.industry),
            _csv_escape(pr.source),
            _csv_escape(info.get("lead_score")),
            _csv_escape(info.get("priority_tier")),
            _csv_escape(camp_str),
            _csv_escape(info.get("signals_count", 0)),
            _csv_escape(pr.created_at),
        ]
        lines.append(",".join(row))

    return "\r\n".join(lines)


@router.get(
    "/export",
    status_code=status.HTTP_200_OK,
    summary="Export filtered prospects as CSV (max 1000)",
)
async def export_prospects_csv(
    campaign_id: Optional[str] = Query(default=None),
    priority: Optional[str] = Query(default=None),
    score_min: Optional[int] = Query(default=None, ge=0, le=100),
    score_max: Optional[int] = Query(default=None, ge=0, le=100),
    unscored: Optional[bool] = Query(default=None),
    has_signals: Optional[bool] = Query(default=None),
    industry: Optional[str] = Query(default=None),
    city: Optional[str] = Query(default=None),
    state_code: Optional[str] = Query(default=None, alias="state"),
    country: Optional[str] = Query(default=None),
    source: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    sort_by: Optional[str] = Query(default="created_at"),
    sort_dir: Optional[str] = Query(default="desc"),
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_READ)),
    container: RuntimeContainer = Depends(get_container),
):
    if sort_by:
        sort_clean = sort_by.strip().lower()
        if sort_clean not in ALLOWED_PROSPECT_SORT_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid sort field '{sort_by}'. Must be one of: {sorted(ALLOWED_PROSPECT_SORT_FIELDS)}",
            )
        sort_col = sort_clean
    else:
        sort_col = "created_at"

    sort_order = "ASC" if sort_dir and sort_dir.lower() == "asc" else "DESC"

    db = container.prospect_repo.db
    p = container.prospect_repo._placeholder()

    conditions = [f"p.organization_id = {p}"]
    query_args: List[Any] = [tenant.organization_id]

    join_sql = ""
    if campaign_id:
        join_sql += f" JOIN campaign_prospects cp ON p.id = cp.prospect_id AND cp.organization_id = {p}"
        query_args.append(tenant.organization_id)
        conditions.append(f"cp.campaign_id = {p}")
        query_args.append(campaign_id)

    if priority:
        join_sql += f" JOIN prospect_priorities pp_filter ON p.id = pp_filter.prospect_id AND pp_filter.organization_id = {p}"
        query_args.append(tenant.organization_id)
        conditions.append(f"LOWER(pp_filter.priority_label) = LOWER({p})")
        query_args.append(priority)

    if unscored:
        conditions.append(
            f"NOT EXISTS (SELECT 1 FROM lead_scores ls_u WHERE ls_u.prospect_id = p.id AND ls_u.organization_id = {p})"
        )
        query_args.append(tenant.organization_id)
    else:
        if score_min is not None:
            conditions.append(
                f"EXISTS (SELECT 1 FROM lead_scores ls_min WHERE ls_min.prospect_id = p.id AND ls_min.organization_id = {p} AND ls_min.score >= {p})"
            )
            query_args.extend([tenant.organization_id, score_min])
        if score_max is not None:
            conditions.append(
                f"EXISTS (SELECT 1 FROM lead_scores ls_max WHERE ls_max.prospect_id = p.id AND ls_max.organization_id = {p} AND ls_max.score <= {p})"
            )
            query_args.extend([tenant.organization_id, score_max])

    if has_signals is True:
        conditions.append(
            f"EXISTS (SELECT 1 FROM signals s_has WHERE s_has.prospect_id = p.id AND s_has.organization_id = {p})"
        )
        query_args.append(tenant.organization_id)
    elif has_signals is False:
        conditions.append(
            f"NOT EXISTS (SELECT 1 FROM signals s_has WHERE s_has.prospect_id = p.id AND s_has.organization_id = {p})"
        )
        query_args.append(tenant.organization_id)

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

    search_query = (q or search or "").strip()
    if search_query:
        term = f"%{search_query.lower()}%"
        conditions.append(f"(LOWER(p.name) LIKE {p} OR LOWER(COALESCE(p.website_url, '')) LIKE {p})")
        query_args.extend([term, term])

    where_clause = " AND ".join(conditions)

    if sort_col == "lead_score":
        order_clause = f"COALESCE((SELECT ls_ord.score FROM lead_scores ls_ord WHERE ls_ord.prospect_id = p.id AND ls_ord.organization_id = p.organization_id LIMIT 1), -1) {sort_order}, p.created_at DESC"
    elif sort_col == "priority":
        order_clause = f"COALESCE((SELECT pp_ord.priority_score FROM prospect_priorities pp_ord WHERE pp_ord.prospect_id = p.id AND pp_ord.organization_id = p.organization_id ORDER BY pp_ord.updated_at DESC LIMIT 1), -1) {sort_order}, p.created_at DESC"
    else:
        order_clause = f"p.{sort_col} {sort_order}, p.id ASC"

    select_sql = f"""
    SELECT p.* FROM prospects p {join_sql}
    WHERE {where_clause}
    ORDER BY {order_clause}
    LIMIT 1000
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

    csv_data = _generate_prospects_csv(db, p, tenant.organization_id, prospects)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"prospects_export_{timestamp}.csv"

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/csv; charset=utf-8",
        },
    )


@router.post(
    "/export",
    status_code=status.HTTP_200_OK,
    summary="Export explicitly selected prospects as CSV (max 1000)",
)
async def export_selected_prospects_csv(
    payload: BulkExportRequest,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_READ)),
    container: RuntimeContainer = Depends(get_container),
):
    db = container.prospect_repo.db
    p = container.prospect_repo._placeholder()

    if not payload.prospect_ids:
        # Export all up to 1000
        sql = f"SELECT * FROM prospects WHERE organization_id = {p} ORDER BY created_at DESC LIMIT 1000"
        rows = db.fetch_dicts(sql, (tenant.organization_id,))
    else:
        in_clause = ", ".join([p] * len(payload.prospect_ids))
        sql = f"SELECT * FROM prospects WHERE organization_id = {p} AND id IN ({in_clause}) ORDER BY created_at DESC LIMIT 1000"
        rows = db.fetch_dicts(sql, tuple([tenant.organization_id] + payload.prospect_ids))

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

    csv_data = _generate_prospects_csv(db, p, tenant.organization_id, prospects)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"prospects_export_{timestamp}.csv"

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": "text/csv; charset=utf-8",
        },
    )


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
    cp_items = []
    for cp in campaign_prospects:
        camp = container.campaign_repo.get_by_id(org_id, cp.campaign_id)
        cp_items.append(
            {
                "id": cp.id,
                "campaign_id": cp.campaign_id,
                "campaign_name": camp.name if camp else None,
                "status": cp.status.value if hasattr(cp.status, "value") else str(cp.status),
                "priority": int(getattr(cp, "relevance_score", 0) or 0),
                "added_at": cp.added_at,
            }
        )

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
    intel = container.intel_repo.get_latest(org_id, prospect_id)
    intel_summary = None
    if intel:
        intel_data = getattr(intel, "data", None) if isinstance(getattr(intel, "data", None), dict) else {}
        intel_summary = {
            "summary_text": getattr(intel, "summary_text", None) or intel_data.get("summary_text") or intel_data.get("executive_summary"),
            "key_insights": getattr(intel, "key_insights", None) or intel_data.get("key_insights") or [],
            "recommended_angle": getattr(intel, "recommended_angle", None) or intel_data.get("recommended_angle"),
            "generated_at": getattr(intel, "generated_at", None) or getattr(intel, "created_at", None),
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


@router.get(
    "/{prospect_id}/score",
    status_code=status.HTTP_200_OK,
    summary="Get latest lead score for a prospect",
)
async def get_prospect_score(
    prospect_id: str,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_READ)),
    container: RuntimeContainer = Depends(get_container),
):
    org_id = tenant.organization_id
    prospect = container.prospect_repo.get_prospect_by_id(org_id, prospect_id)
    if not prospect:
        raise EntityNotFoundError(f"Prospect '{prospect_id}' not found.")

    scores = container.prospect_repo.get_lead_scores_by_prospect(org_id, prospect_id)
    if not scores:
        return {
            "prospect_id": prospect_id,
            "organization_id": org_id,
            "score": None,
            "explanation": "Not scored yet",
            "calculated_at": None,
        }

    s = scores[0]
    return {
        "prospect_id": prospect_id,
        "organization_id": org_id,
        "score": s.score,
        "explanation": s.explanation,
        "confidence": getattr(s, "confidence", None),
        "components": getattr(s, "components", None),
        "calculated_at": getattr(s, "calculated_at", getattr(s, "created_at", None)),
    }


@router.post(
    "/{prospect_id}/score/recalculate",
    status_code=status.HTTP_200_OK,
    summary="Recalculate lead score for a prospect based on signals and ICP fit",
)
async def recalculate_prospect_score(
    prospect_id: str,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_UPDATE)),
    container: RuntimeContainer = Depends(get_container),
):
    org_id = tenant.organization_id
    prospect = container.prospect_repo.get_prospect_by_id(org_id, prospect_id)
    if not prospect:
        raise EntityNotFoundError(f"Prospect '{prospect_id}' not found.")

    signals = container.prospect_repo.get_signals_by_prospect(org_id, prospect_id)

    icp = None
    cps = container.prospect_repo.get_campaign_prospects_by_prospect(org_id, prospect_id)
    if cps and cps[0].campaign_id:
        camp = container.campaign_repo.get_by_id(org_id, cps[0].campaign_id)
        if camp and camp.icp_id:
            icp = container.icp_repo.get_by_id(org_id, camp.icp_id)

    score, explanation, recommendations = container.opportunity_scorer.score(
        org_id=org_id,
        prospect=prospect,
        signals=signals,
        services=[],
        icp=icp,
    )

    lead_score = container.prospect_service.assign_score(
        org_id=org_id,
        prospect_id=prospect_id,
        score=score,
        explanation=explanation,
    )

    return {
        "prospect_id": prospect_id,
        "organization_id": org_id,
        "score": lead_score.score,
        "explanation": lead_score.explanation,
        "calculated_at": lead_score.calculated_at,
    }


@router.get(
    "/{prospect_id}/priority",
    status_code=status.HTTP_200_OK,
    summary="Get latest priority calculation for a prospect",
)
async def get_prospect_priority(
    prospect_id: str,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_READ)),
    container: RuntimeContainer = Depends(get_container),
):
    org_id = tenant.organization_id
    prospect = container.prospect_repo.get_prospect_by_id(org_id, prospect_id)
    if not prospect:
        raise EntityNotFoundError(f"Prospect '{prospect_id}' not found.")

    priorities = container.priority_repo.get_by_prospect(org_id, prospect_id)
    if not priorities:
        return {
            "prospect_id": prospect_id,
            "organization_id": org_id,
            "priority": None,
            "message": "No priority calculated yet",
        }

    p_row = priorities[0]
    return {
        "prospect_id": prospect_id,
        "organization_id": org_id,
        "campaign_id": p_row.campaign_id,
        "tier": p_row.tier.value if hasattr(p_row.tier, "value") else str(p_row.tier),
        "score": p_row.score,
        "reasons": p_row.reasons,
        "lead_score_component": p_row.lead_score_component,
        "intent_signal_component": p_row.intent_signal_component,
        "research_confidence_component": p_row.research_confidence_component,
        "freshness_component": p_row.freshness_component,
        "updated_at": p_row.updated_at,
    }


@router.post(
    "/{prospect_id}/priority/recalculate",
    status_code=status.HTTP_200_OK,
    summary="Recalculate priority for a prospect",
)
async def recalculate_prospect_priority(
    prospect_id: str,
    campaign_id: Optional[str] = Query(default=None),
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_UPDATE)),
    container: RuntimeContainer = Depends(get_container),
):
    org_id = tenant.organization_id
    prospect = container.prospect_repo.get_prospect_by_id(org_id, prospect_id)
    if not prospect:
        raise EntityNotFoundError(f"Prospect '{prospect_id}' not found.")

    target_camp_id = campaign_id
    if not target_camp_id:
        cps = container.prospect_repo.get_campaign_prospects_by_prospect(org_id, prospect_id)
        if cps:
            target_camp_id = cps[0].campaign_id

    if not target_camp_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prospect must be associated with a campaign to calculate priority.",
        )

    scores = container.prospect_repo.get_lead_scores_by_prospect(org_id, prospect_id)
    lead_score = scores[0] if scores else None
    signals = container.prospect_repo.get_signals_by_prospect(org_id, prospect_id)
    intel = container.intel_repo.get_latest(org_id, prospect_id)

    calculated = container.priority_scorer.calculate_priority(
        organization_id=org_id,
        campaign_id=target_camp_id,
        prospect=prospect,
        lead_score=lead_score,
        signals=signals,
        intelligence=intel,
    )

    saved = container.priority_repo.save(org_id, calculated)
    return {
        "prospect_id": prospect_id,
        "organization_id": org_id,
        "campaign_id": target_camp_id,
        "tier": saved.tier.value if hasattr(saved.tier, "value") else str(saved.tier),
        "score": saved.score,
        "reasons": saved.reasons,
        "lead_score_component": saved.lead_score_component,
        "intent_signal_component": saved.intent_signal_component,
        "research_confidence_component": saved.research_confidence_component,
        "freshness_component": saved.freshness_component,
        "updated_at": saved.updated_at,
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


# ==============================================================================
# Bulk Operations & CSV Export Endpoints (Phase P22)
# ==============================================================================


@router.post(
    "/bulk/add-to-campaign",
    response_model=BulkAddToCampaignResponse,
    status_code=status.HTTP_200_OK,
    summary="Add multiple prospects to a campaign in bulk (max 100)",
)
async def bulk_add_to_campaign(
    payload: BulkAddToCampaignRequest,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_UPDATE)),
    container: RuntimeContainer = Depends(get_container),
) -> BulkAddToCampaignResponse:
    org_id = tenant.organization_id
    campaign = container.campaign_repo.get_by_id(org_id, payload.campaign_id)
    if not campaign:
        raise EntityNotFoundError(f"Campaign '{payload.campaign_id}' not found.")

    added = 0
    already_present = 0
    failed = 0
    added_ids: List[str] = []

    p = container.prospect_repo._placeholder()

    for pid in payload.prospect_ids:
        try:
            prospect = container.prospect_repo.get_prospect_by_id(org_id, pid)
            if not prospect:
                failed += 1
                continue

            check_sql = f"SELECT id FROM campaign_prospects WHERE organization_id = {p} AND campaign_id = {p} AND prospect_id = {p}"
            exists = container.prospect_repo.db.fetch_dicts(check_sql, (org_id, payload.campaign_id, pid))
            if exists:
                already_present += 1
                continue

            cp = CampaignProspect(
                id=str(uuid.uuid4()),
                organization_id=org_id,
                campaign_id=payload.campaign_id,
                prospect_id=pid,
                status="added",
            )
            container.prospect_repo.add_prospect_to_campaign(org_id, cp)
            added += 1
            added_ids.append(pid)
        except Exception:
            failed += 1

    return BulkAddToCampaignResponse(
        campaign_id=payload.campaign_id,
        requested=len(payload.prospect_ids),
        added=added,
        already_present=already_present,
        failed=failed,
        prospect_ids=added_ids,
    )


@router.post(
    "/bulk/recalculate-score",
    response_model=BulkRecalculateScoreResponse,
    status_code=status.HTTP_200_OK,
    summary="Recalculate lead scores for multiple prospects in bulk (max 50)",
)
async def bulk_recalculate_score(
    payload: BulkRecalculateScoreRequest,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_UPDATE)),
    container: RuntimeContainer = Depends(get_container),
) -> BulkRecalculateScoreResponse:
    org_id = tenant.organization_id
    succeeded = 0
    failed = 0
    items: List[Dict[str, Any]] = []

    for pid in payload.prospect_ids:
        try:
            prospect = container.prospect_repo.get_prospect_by_id(org_id, pid)
            if not prospect:
                failed += 1
                items.append({"prospect_id": pid, "status": "failed", "error": "Prospect not found"})
                continue

            signals = container.prospect_repo.get_signals_by_prospect(org_id, pid)
            icp = None
            cps = container.prospect_repo.get_campaign_prospects_by_prospect(org_id, pid)
            if cps and cps[0].campaign_id:
                camp = container.campaign_repo.get_by_id(org_id, cps[0].campaign_id)
                if camp and camp.icp_id:
                    icp = container.icp_repo.get_by_id(org_id, camp.icp_id)

            score, explanation, _ = container.opportunity_scorer.score(
                org_id=org_id,
                prospect=prospect,
                signals=signals,
                services=[],
                icp=icp,
            )

            lead_score = container.prospect_service.assign_score(
                org_id=org_id,
                prospect_id=pid,
                score=score,
                explanation=explanation,
            )
            succeeded += 1
            items.append({"prospect_id": pid, "status": "succeeded", "score": lead_score.score})
        except Exception as exc:
            failed += 1
            items.append({"prospect_id": pid, "status": "failed", "error": str(exc)})

    return BulkRecalculateScoreResponse(
        requested=len(payload.prospect_ids),
        succeeded=succeeded,
        failed=failed,
        items=items,
    )


@router.post(
    "/bulk/recalculate-priority",
    response_model=BulkRecalculatePriorityResponse,
    status_code=status.HTTP_200_OK,
    summary="Recalculate priorities for multiple prospects in bulk (max 50)",
)
async def bulk_recalculate_priority(
    payload: BulkRecalculatePriorityRequest,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_UPDATE)),
    container: RuntimeContainer = Depends(get_container),
) -> BulkRecalculatePriorityResponse:
    org_id = tenant.organization_id
    succeeded = 0
    failed = 0
    items: List[Dict[str, Any]] = []

    for pid in payload.prospect_ids:
        try:
            prospect = container.prospect_repo.get_prospect_by_id(org_id, pid)
            if not prospect:
                failed += 1
                items.append({"prospect_id": pid, "status": "failed", "error": "Prospect not found"})
                continue

            target_camp_id = payload.campaign_id
            if not target_camp_id:
                cps = container.prospect_repo.get_campaign_prospects_by_prospect(org_id, pid)
                if cps:
                    target_camp_id = cps[0].campaign_id

            if not target_camp_id:
                failed += 1
                items.append(
                    {
                        "prospect_id": pid,
                        "status": "failed",
                        "error": "Prospect must be associated with a campaign to calculate priority",
                    }
                )
                continue

            scores = container.prospect_repo.get_lead_scores_by_prospect(org_id, pid)
            lead_score = scores[0] if scores else None
            signals = container.prospect_repo.get_signals_by_prospect(org_id, pid)
            intel = container.intel_repo.get_latest(org_id, pid)

            calculated = container.priority_scorer.calculate_priority(
                organization_id=org_id,
                campaign_id=target_camp_id,
                prospect=prospect,
                lead_score=lead_score,
                signals=signals,
                intelligence=intel,
            )

            saved = container.priority_repo.save(org_id, calculated)
            succeeded += 1
            items.append(
                {
                    "prospect_id": pid,
                    "status": "succeeded",
                    "priority_score": saved.score,
                    "priority_tier": saved.tier.value if hasattr(saved.tier, "value") else str(saved.tier),
                }
            )
        except Exception as exc:
            failed += 1
            items.append({"prospect_id": pid, "status": "failed", "error": str(exc)})

    return BulkRecalculatePriorityResponse(
        requested=len(payload.prospect_ids),
        succeeded=succeeded,
        failed=failed,
        items=items,
    )


@router.post(
    "/bulk/research",
    response_model=BulkResearchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger research runs for multiple prospects in bulk (max 25)",
)
async def bulk_research(
    payload: BulkResearchRequest,
    tenant: TenantContext = Depends(require_permission(Permission.RESEARCH_RUN)),
    container: RuntimeContainer = Depends(get_container),
) -> BulkResearchResponse:
    org_id = tenant.organization_id

    if payload.campaign_id:
        campaign = container.campaign_repo.get_by_id(org_id, payload.campaign_id)
        if not campaign:
            raise EntityNotFoundError(f"Campaign '{payload.campaign_id}' not found.")

    queued = 0
    already_active = 0
    failed = 0
    run_ids: List[str] = []

    for pid in payload.prospect_ids:
        try:
            prospect = container.prospect_repo.get_prospect_by_id(org_id, pid)
            if not prospect:
                failed += 1
                continue

            existing_runs = container.research_run_repo.list_by_organization(
                org_id, prospect_id=pid, limit=5
            )
            active_run = next((r for r in existing_runs if r.status in ("pending", "running")), None)
            if active_run:
                already_active += 1
                run_ids.append(active_run.id)
                continue

            now = datetime.now(timezone.utc).isoformat()
            run = ResearchRun(
                id=str(uuid.uuid4()),
                organization_id=org_id,
                prospect_id=pid,
                campaign_id=payload.campaign_id,
                run_type=payload.run_type,
                status="pending",
                created_at=now,
                updated_at=now,
            )
            saved = container.research_run_repo.save(org_id, run)
            queued += 1
            run_ids.append(saved.id)
        except Exception:
            failed += 1

    return BulkResearchResponse(
        requested=len(payload.prospect_ids),
        queued=queued,
        already_active=already_active,
        failed=failed,
        run_ids=run_ids,
    )


# ------------------------------------------------------------------------------
# BOP CRM Handoff Endpoints (P27)
# ------------------------------------------------------------------------------

@router.post(
    "/bulk/crm-handoff",
    response_model=BulkCrmHandoffResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger bulk handoff of prospects to Bop CRM",
)
@router.post(
    "/bulk-crm-handoff",
    response_model=BulkCrmHandoffResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def bulk_prospect_crm_handoff(
    payload: BulkCrmHandoffRequest,
    request: Request,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_UPDATE)),
    container: RuntimeContainer = Depends(get_container),
) -> BulkCrmHandoffResponse:
    user_id = getattr(request.state, "user_id", "system")
    locale = resolve_request_locale(request)
    res = container.crm_handoff_service.bulk_handoff(
        bop_organization_id=tenant.bop_organization_id,
        organization_id=tenant.organization_id,
        prospect_ids=payload.prospect_ids,
        requested_by_user_id=user_id,
        locale=locale,
    )
    return BulkCrmHandoffResponse(**res)


@router.post(
    "/{prospect_id}/crm-handoff",
    response_model=CrmHandoffResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger handoff of a prospect to Bop CRM",
)
async def handoff_prospect_to_crm(
    prospect_id: str,
    request: Request,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_UPDATE)),
    container: RuntimeContainer = Depends(get_container),
) -> CrmHandoffResponse:
    user_id = getattr(request.state, "user_id", "system")
    locale = resolve_request_locale(request)
    res = container.crm_handoff_service.trigger_handoff(
        bop_organization_id=tenant.bop_organization_id,
        organization_id=tenant.organization_id,
        prospect_id=prospect_id,
        requested_by_user_id=user_id,
        locale=locale,
    )
    return CrmHandoffResponse(**res)


@router.get(
    "/{prospect_id}/crm-handoff",
    response_model=CrmHandoffStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Bop CRM handoff status for a prospect",
)
async def get_prospect_crm_handoff_status(
    prospect_id: str,
    tenant: TenantContext = Depends(require_permission(Permission.PROSPECT_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> CrmHandoffStatusResponse:
    res = container.crm_handoff_service.get_handoff_status(
        bop_organization_id=tenant.bop_organization_id,
        organization_id=tenant.organization_id,
        prospect_id=prospect_id,
    )
    return CrmHandoffStatusResponse(**res)
