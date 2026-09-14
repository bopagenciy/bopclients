"""Campaign endpoints (/api/v1/campaigns)."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query
from bopclients.api.schemas.campaigns import CampaignCreate, CampaignUpdate, CampaignResponse
from bopclients.api.pagination import PaginationParams, PaginatedResponse
from bopclients.api.dependencies import require_permission, get_container
from bopclients.domain.auth.context import TenantContext
from bopclients.domain.auth.policy import Permission
from bopclients.domain.campaign import Campaign
from bopclients.domain.enums import CampaignStatus
from bopclients.domain.exceptions import EntityNotFoundError
from bopclients.runtime.container import RuntimeContainer

router = APIRouter(prefix="/api/v1/campaigns", tags=["Campaigns"])


def _campaign_to_response(c: Campaign) -> CampaignResponse:
    status_str = c.status.value if isinstance(c.status, CampaignStatus) else str(c.status)
    return CampaignResponse(
        id=c.id,
        organization_id=c.organization_id,
        icp_id=c.icp_id,
        name=c.name,
        description=c.description,
        status=status_str,
        display_key=f"campaign.status.{status_str.lower()}",
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


@router.get(
    "",
    response_model=PaginatedResponse[CampaignResponse],
    status_code=status.HTTP_200_OK,
    summary="List tenant campaigns",
)
async def list_campaigns(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    tenant: TenantContext = Depends(require_permission(Permission.CAMPAIGN_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> PaginatedResponse[CampaignResponse]:
    params = PaginationParams(page=page, page_size=page_size)
    campaigns = container.campaign_repo.list_by_organization(tenant.organization_id)
    total = len(campaigns)

    # Slice for in-memory pagination
    items = campaigns[params.offset : params.offset + params.limit]
    responses = [_campaign_to_response(c) for c in items]
    return PaginatedResponse.create(items=responses, total_items=total, params=params)


@router.post(
    "",
    response_model=CampaignResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create campaign",
)
async def create_campaign(
    payload: CampaignCreate,
    tenant: TenantContext = Depends(require_permission(Permission.CAMPAIGN_CREATE)),
    container: RuntimeContainer = Depends(get_container),
) -> CampaignResponse:
    now = datetime.now(timezone.utc).isoformat()
    status_enum = CampaignStatus.DRAFT
    if payload.status:
        try:
            status_enum = CampaignStatus(payload.status.lower())
        except ValueError:
            pass

    campaign = Campaign(
        id=str(uuid.uuid4()),
        organization_id=tenant.organization_id,
        icp_id=payload.icp_id,
        name=payload.name,
        description=payload.description,
        status=status_enum,
        created_at=now,
        updated_at=now,
    )
    saved = container.campaign_repo.save(tenant.organization_id, campaign)
    return _campaign_to_response(saved)


@router.get(
    "/{campaign_id}",
    response_model=CampaignResponse,
    status_code=status.HTTP_200_OK,
    summary="Get campaign by ID",
)
async def get_campaign(
    campaign_id: str,
    tenant: TenantContext = Depends(require_permission(Permission.CAMPAIGN_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> CampaignResponse:
    campaign = container.campaign_repo.get_by_id(tenant.organization_id, campaign_id)
    if not campaign:
        raise EntityNotFoundError(f"Campaign '{campaign_id}' not found.")
    return _campaign_to_response(campaign)


@router.patch(
    "/{campaign_id}",
    response_model=CampaignResponse,
    status_code=status.HTTP_200_OK,
    summary="Update campaign",
)
async def update_campaign(
    campaign_id: str,
    payload: CampaignUpdate,
    tenant: TenantContext = Depends(require_permission(Permission.CAMPAIGN_UPDATE)),
    container: RuntimeContainer = Depends(get_container),
) -> CampaignResponse:
    campaign = container.campaign_repo.get_by_id(tenant.organization_id, campaign_id)
    if not campaign:
        raise EntityNotFoundError(f"Campaign '{campaign_id}' not found.")

    if payload.name is not None:
        campaign.name = payload.name
    if payload.description is not None:
        campaign.description = payload.description
    if payload.icp_id is not None:
        campaign.icp_id = payload.icp_id
    if payload.status is not None:
        try:
            campaign.status = CampaignStatus(payload.status.lower())
        except ValueError:
            pass

    campaign.updated_at = datetime.now(timezone.utc).isoformat()
    # Replace in DB
    sql = f"""
    UPDATE campaigns SET name = {container.campaign_repo._placeholder()},
                         description = {container.campaign_repo._placeholder()},
                         icp_id = {container.campaign_repo._placeholder()},
                         status = {container.campaign_repo._placeholder()},
                         updated_at = {container.campaign_repo._placeholder()}
    WHERE organization_id = {container.campaign_repo._placeholder()} AND id = {container.campaign_repo._placeholder()}
    """
    status_str = campaign.status.value if isinstance(campaign.status, CampaignStatus) else str(campaign.status)
    container.campaign_repo.db.execute(
        sql,
        (campaign.name, campaign.description, campaign.icp_id, status_str, campaign.updated_at, tenant.organization_id, campaign_id),
    )
    container.campaign_repo.db.commit()

    return _campaign_to_response(campaign)


@router.delete(
    "/{campaign_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete or archive campaign",
)
async def delete_campaign(
    campaign_id: str,
    tenant: TenantContext = Depends(require_permission(Permission.CAMPAIGN_DELETE)),
    container: RuntimeContainer = Depends(get_container),
):
    campaign = container.campaign_repo.get_by_id(tenant.organization_id, campaign_id)
    if not campaign:
        raise EntityNotFoundError(f"Campaign '{campaign_id}' not found.")

    sql = f"DELETE FROM campaigns WHERE organization_id = {container.campaign_repo._placeholder()} AND id = {container.campaign_repo._placeholder()}"
    container.campaign_repo.db.execute(sql, (tenant.organization_id, campaign_id))
    container.campaign_repo.db.commit()
