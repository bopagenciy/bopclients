"""Target Market endpoints (/api/v1/target-markets)."""

import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query
from bopclients.api.schemas.icps import TargetMarketResponse, TargetMarketCreate, TargetMarketUpdate
from bopclients.api.pagination import PaginationParams, PaginatedResponse
from bopclients.api.dependencies import require_permission, get_container
from bopclients.domain.auth.context import TenantContext
from bopclients.domain.auth.policy import Permission
from bopclients.domain.exceptions import EntityNotFoundError
from bopclients.runtime.container import RuntimeContainer

router = APIRouter(prefix="/api/v1/target-markets", tags=["Target Markets"])


@router.get(
    "",
    response_model=PaginatedResponse[TargetMarketResponse],
    status_code=status.HTTP_200_OK,
    summary="List tenant target markets",
)
async def list_target_markets(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    tenant: TenantContext = Depends(require_permission(Permission.ICP_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> PaginatedResponse[TargetMarketResponse]:
    params = PaginationParams(page=page, page_size=page_size)
    p = container.icp_repo._placeholder()
    sql = f"""
    SELECT tm.* FROM target_markets tm
    JOIN ideal_customer_profiles icp ON tm.icp_id = icp.id
    WHERE icp.organization_id = {p}
    ORDER BY tm.country ASC, tm.city ASC
    """
    rows = container.icp_repo.db.fetch_dicts(sql, (tenant.organization_id,))
    total = len(rows)
    items = rows[params.offset : params.offset + params.limit]

    responses = [
        TargetMarketResponse(
            id=r["id"],
            icp_id=r.get("icp_id"),
            country=r["country"],
            region=r.get("region"),
            city=r.get("city"),
            postal_code=r.get("postal_code"),
            radius_miles=r.get("radius_miles"),
            language=r.get("language", "en"),
        )
        for r in items
    ]
    return PaginatedResponse.create(items=responses, total_items=total, params=params)


@router.post(
    "",
    response_model=TargetMarketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create target market",
)
async def create_target_market(
    payload: TargetMarketCreate,
    tenant: TenantContext = Depends(require_permission(Permission.ICP_MANAGE)),
    container: RuntimeContainer = Depends(get_container),
) -> TargetMarketResponse:
    if not payload.icp_id:
        raise ValueError("icp_id is required to create a target market.")

    icp = container.icp_repo.get_by_id(tenant.organization_id, payload.icp_id)
    if not icp:
        raise EntityNotFoundError(f"ICP profile '{payload.icp_id}' not found.")

    market_id = str(uuid.uuid4())
    p = container.icp_repo._placeholder()
    sql = f"""
    INSERT INTO target_markets (id, organization_id, icp_id, country, region, city, postal_code, radius_miles, language)
    VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
    """
    container.icp_repo.db.execute(
        sql,
        (
            market_id,
            tenant.organization_id,
            payload.icp_id,
            payload.country,
            payload.region,
            payload.city,
            payload.postal_code,
            payload.radius_miles,
            payload.language,
        ),
    )
    container.icp_repo.db.commit()

    return TargetMarketResponse(
        id=market_id,
        icp_id=payload.icp_id,
        country=payload.country,
        region=payload.region,
        city=payload.city,
        postal_code=payload.postal_code,
        radius_miles=payload.radius_miles,
        language=payload.language,
    )


@router.get(
    "/{market_id}",
    response_model=TargetMarketResponse,
    status_code=status.HTTP_200_OK,
    summary="Get target market by ID",
)
async def get_target_market(
    market_id: str,
    tenant: TenantContext = Depends(require_permission(Permission.ICP_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> TargetMarketResponse:
    p = container.icp_repo._placeholder()
    sql = f"""
    SELECT tm.* FROM target_markets tm
    JOIN ideal_customer_profiles icp ON tm.icp_id = icp.id
    WHERE icp.organization_id = {p} AND tm.id = {p}
    """
    rows = container.icp_repo.db.fetch_dicts(sql, (tenant.organization_id, market_id))
    if not rows:
        raise EntityNotFoundError(f"Target market '{market_id}' not found.")
    r = rows[0]
    return TargetMarketResponse(
        id=r["id"],
        icp_id=r.get("icp_id"),
        country=r["country"],
        region=r.get("region"),
        city=r.get("city"),
        postal_code=r.get("postal_code"),
        radius_miles=r.get("radius_miles"),
        language=r.get("language", "en"),
    )


@router.patch(
    "/{market_id}",
    response_model=TargetMarketResponse,
    status_code=status.HTTP_200_OK,
    summary="Update target market",
)
async def update_target_market(
    market_id: str,
    payload: TargetMarketUpdate,
    tenant: TenantContext = Depends(require_permission(Permission.ICP_MANAGE)),
    container: RuntimeContainer = Depends(get_container),
) -> TargetMarketResponse:
    p = container.icp_repo._placeholder()
    sql = f"""
    SELECT tm.* FROM target_markets tm
    JOIN ideal_customer_profiles icp ON tm.icp_id = icp.id
    WHERE icp.organization_id = {p} AND tm.id = {p}
    """
    rows = container.icp_repo.db.fetch_dicts(sql, (tenant.organization_id, market_id))
    if not rows:
        raise EntityNotFoundError(f"Target market '{market_id}' not found.")

    current = dict(rows[0])
    country = payload.country if payload.country is not None else current["country"]
    region = payload.region if payload.region is not None else current.get("region")
    city = payload.city if payload.city is not None else current.get("city")
    postal_code = payload.postal_code if payload.postal_code is not None else current.get("postal_code")
    radius_miles = payload.radius_miles if payload.radius_miles is not None else current.get("radius_miles")
    language = payload.language if payload.language is not None else current.get("language", "en")

    update_sql = f"""
    UPDATE target_markets SET
        country = {p}, region = {p}, city = {p}, postal_code = {p},
        radius_miles = {p}, language = {p}
    WHERE id = {p}
    """
    container.icp_repo.db.execute(
        update_sql,
        (country, region, city, postal_code, radius_miles, language, market_id),
    )
    container.icp_repo.db.commit()

    return TargetMarketResponse(
        id=market_id,
        icp_id=current.get("icp_id"),
        country=country,
        region=region,
        city=city,
        postal_code=postal_code,
        radius_miles=radius_miles,
        language=language,
    )
