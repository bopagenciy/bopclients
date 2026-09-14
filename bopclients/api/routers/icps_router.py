"""Ideal Customer Profile (ICP) endpoints (/api/v1/icps)."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query
from bopclients.api.schemas.icps import ICPCreate, ICPUpdate, ICPResponse, TargetMarketResponse
from bopclients.api.pagination import PaginationParams, PaginatedResponse
from bopclients.api.dependencies import require_permission, get_container
from bopclients.domain.auth.context import TenantContext
from bopclients.domain.auth.policy import Permission
from bopclients.domain.icp import IdealCustomerProfile, TargetMarket
from bopclients.domain.exceptions import EntityNotFoundError
from bopclients.runtime.container import RuntimeContainer

router = APIRouter(prefix="/api/v1/icps", tags=["Ideal Customer Profiles"])


def _icp_to_response(icp: IdealCustomerProfile) -> ICPResponse:
    markets = [
        TargetMarketResponse(
            id=tm.id,
            icp_id=tm.icp_id,
            country=tm.country,
            region=tm.region,
            city=tm.city,
            postal_code=tm.postal_code,
            radius_miles=tm.radius_miles,
            language=tm.language,
        )
        for tm in icp.target_markets
    ]
    return ICPResponse(
        id=icp.id,
        organization_id=icp.organization_id,
        name=icp.name,
        description=icp.description,
        industries=icp.industries,
        company_sizes=icp.company_sizes,
        decision_maker_roles=icp.decision_maker_roles,
        pain_points=icp.pain_points,
        desired_signals=icp.desired_signals,
        excluded_signals=icp.excluded_signals,
        countries=icp.countries,
        languages=icp.languages,
        target_markets=markets,
        created_at=icp.created_at,
    )


@router.get(
    "",
    response_model=PaginatedResponse[ICPResponse],
    status_code=status.HTTP_200_OK,
    summary="List tenant ICP profiles",
)
async def list_icps(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    tenant: TenantContext = Depends(require_permission(Permission.ICP_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> PaginatedResponse[ICPResponse]:
    params = PaginationParams(page=page, page_size=page_size)
    icps = container.icp_repo.list_by_organization(tenant.organization_id)
    total = len(icps)
    items = icps[params.offset : params.offset + params.limit]
    responses = [_icp_to_response(i) for i in items]
    return PaginatedResponse.create(items=responses, total_items=total, params=params)


@router.post(
    "",
    response_model=ICPResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create ICP profile",
)
async def create_icp(
    payload: ICPCreate,
    tenant: TenantContext = Depends(require_permission(Permission.ICP_MANAGE)),
    container: RuntimeContainer = Depends(get_container),
) -> ICPResponse:
    now = datetime.now(timezone.utc).isoformat()
    icp_id = str(uuid.uuid4())

    markets = [
        TargetMarket(
            id=str(uuid.uuid4()),
            icp_id=icp_id,
            country=tm.country,
            region=tm.region,
            city=tm.city,
            postal_code=tm.postal_code,
            radius_miles=tm.radius_miles,
            language=tm.language,
        )
        for tm in payload.target_markets
    ]

    icp = IdealCustomerProfile(
        id=icp_id,
        organization_id=tenant.organization_id,
        name=payload.name,
        description=payload.description,
        industries=payload.industries,
        company_sizes=payload.company_sizes,
        decision_maker_roles=payload.decision_maker_roles,
        pain_points=payload.pain_points,
        desired_signals=payload.desired_signals,
        excluded_signals=payload.excluded_signals,
        countries=payload.countries,
        languages=payload.languages,
        target_markets=markets,
        created_at=now,
    )
    saved = container.icp_repo.save(tenant.organization_id, icp)
    return _icp_to_response(saved)


@router.get(
    "/{icp_id}",
    response_model=ICPResponse,
    status_code=status.HTTP_200_OK,
    summary="Get ICP profile by ID",
)
async def get_icp(
    icp_id: str,
    tenant: TenantContext = Depends(require_permission(Permission.ICP_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> ICPResponse:
    icp = container.icp_repo.get_by_id(tenant.organization_id, icp_id)
    if not icp:
        raise EntityNotFoundError(f"ICP profile '{icp_id}' not found.")
    return _icp_to_response(icp)


@router.patch(
    "/{icp_id}",
    response_model=ICPResponse,
    status_code=status.HTTP_200_OK,
    summary="Update ICP profile",
)
async def update_icp(
    icp_id: str,
    payload: ICPUpdate,
    tenant: TenantContext = Depends(require_permission(Permission.ICP_MANAGE)),
    container: RuntimeContainer = Depends(get_container),
) -> ICPResponse:
    icp = container.icp_repo.get_by_id(tenant.organization_id, icp_id)
    if not icp:
        raise EntityNotFoundError(f"ICP profile '{icp_id}' not found.")

    if payload.name is not None:
        icp.name = payload.name
    if payload.description is not None:
        icp.description = payload.description
    if payload.industries is not None:
        icp.industries = payload.industries
    if payload.company_sizes is not None:
        icp.company_sizes = payload.company_sizes
    if payload.decision_maker_roles is not None:
        icp.decision_maker_roles = payload.decision_maker_roles
    if payload.pain_points is not None:
        icp.pain_points = payload.pain_points
    if payload.desired_signals is not None:
        icp.desired_signals = payload.desired_signals
    if payload.excluded_signals is not None:
        icp.excluded_signals = payload.excluded_signals
    if payload.countries is not None:
        icp.countries = payload.countries
    if payload.languages is not None:
        icp.languages = payload.languages

    # Update in DB
    import json
    p = container.icp_repo._placeholder()
    sql = f"""
    UPDATE ideal_customer_profiles SET
        name = {p}, description = {p}, industries = {p}, company_sizes = {p},
        decision_maker_roles = {p}, pain_points = {p}, desired_signals = {p},
        excluded_signals = {p}, countries = {p}, languages = {p}
    WHERE organization_id = {p} AND id = {p}
    """
    container.icp_repo.db.execute(
        sql,
        (
            icp.name,
            icp.description,
            json.dumps(icp.industries),
            json.dumps(icp.company_sizes),
            json.dumps(icp.decision_maker_roles),
            json.dumps(icp.pain_points),
            json.dumps(icp.desired_signals),
            json.dumps(icp.excluded_signals),
            json.dumps(icp.countries),
            json.dumps(icp.languages),
            tenant.organization_id,
            icp_id,
        ),
    )
    container.icp_repo.db.commit()

    return _icp_to_response(icp)
