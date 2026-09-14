"""Integration outbox and destination administrative endpoints (/api/v1/integrations)."""

from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query
from bopclients.api.schemas.integrations import (
    DestinationCreate,
    DestinationUpdate,
    DestinationResponse,
    DeliveryResponse,
)
from bopclients.api.pagination import PaginationParams, PaginatedResponse
from bopclients.api.dependencies import require_permission, get_container
from bopclients.domain.auth.context import TenantContext
from bopclients.domain.auth.policy import Permission
from bopclients.domain.integration.destination import IntegrationDestination
from bopclients.domain.exceptions import EntityNotFoundError
from bopclients.runtime.container import RuntimeContainer

router = APIRouter(prefix="/api/v1/integrations", tags=["Integrations"])


def _dest_to_response(d: IntegrationDestination) -> DestinationResponse:
    return DestinationResponse(
        id=d.id,
        bop_organization_id=d.bop_organization_id,
        target_app_id=d.target_app_id,
        destination_name=d.destination_name,
        transport_type=d.transport_type,
        endpoint_url=d.endpoint_url,
        secret_key_ref=d.secret_key_ref,
        is_active=d.is_active,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


@router.get(
    "/destinations",
    status_code=status.HTTP_200_OK,
    summary="List tenant integration destinations (ADMIN/OWNER)",
)
async def list_destinations(
    tenant: TenantContext = Depends(require_permission(Permission.INTEGRATION_READ)),
    container: RuntimeContainer = Depends(get_container),
):
    destinations = container.destination_repo.list_destinations(tenant.bop_organization_id, only_active=False)
    return {"items": [_dest_to_response(d) for d in destinations]}


@router.get(
    "/outbox",
    status_code=status.HTTP_200_OK,
    summary="List tenant outbox events (ADMIN/OWNER)",
)
async def list_outbox_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    tenant: TenantContext = Depends(require_permission(Permission.INTEGRATION_READ)),
    container: RuntimeContainer = Depends(get_container),
):
    p = container.outbox_repo._placeholder()
    sql = f"""
    SELECT id, event_id, bop_organization_id, event_type, status, attempt_count, created_at
    FROM bop_integration_outbox
    WHERE bop_organization_id = {p}
    ORDER BY created_at DESC
    LIMIT {page_size}
    """
    rows = container.outbox_repo.db.fetch_dicts(sql, (tenant.bop_organization_id,))
    return {"items": rows}


@router.get(
    "/inbox",
    status_code=status.HTTP_200_OK,
    summary="List tenant inbox events (ADMIN/OWNER)",
)
async def list_inbox_events(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    tenant: TenantContext = Depends(require_permission(Permission.INTEGRATION_READ)),
    container: RuntimeContainer = Depends(get_container),
):
    p = container.destination_repo._placeholder()
    sql = f"""
    SELECT * FROM bop_integration_inbox
    WHERE bop_organization_id = {p}
    ORDER BY received_at DESC
    LIMIT {page_size}
    """
    rows = container.destination_repo.db.fetch_dicts(sql, (tenant.bop_organization_id,))
    return {"items": rows}


@router.post(
    "/destinations",
    response_model=DestinationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register new integration destination (ADMIN/OWNER)",
)
async def create_destination(
    payload: DestinationCreate,
    tenant: TenantContext = Depends(require_permission(Permission.INTEGRATION_MANAGE)),
    container: RuntimeContainer = Depends(get_container),
) -> DestinationResponse:
    destination = IntegrationDestination.create(
        bop_organization_id=tenant.bop_organization_id,
        target_app_id=payload.target_app_id,
        destination_name=payload.destination_name,
        endpoint_url=payload.endpoint_url,
        transport_type=payload.transport_type,
        secret_key_ref=payload.secret_key_ref,
        headers_template=payload.headers_template,
    )
    saved = container.destination_repo.save(destination)
    return _dest_to_response(saved)


@router.patch(
    "/destinations/{destination_id}",
    response_model=DestinationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update destination settings or deactivation (ADMIN/OWNER)",
)
async def update_destination(
    destination_id: str,
    payload: DestinationUpdate,
    tenant: TenantContext = Depends(require_permission(Permission.INTEGRATION_MANAGE)),
    container: RuntimeContainer = Depends(get_container),
) -> DestinationResponse:
    destination = container.destination_repo.get_by_id(tenant.bop_organization_id, destination_id)
    if not destination:
        raise EntityNotFoundError(f"Destination '{destination_id}' not found.")

    if payload.destination_name is not None:
        destination.destination_name = payload.destination_name
    if payload.endpoint_url is not None:
        destination.endpoint_url = payload.endpoint_url
    if payload.is_active is not None:
        destination.is_active = payload.is_active
    if payload.secret_key_ref is not None:
        destination.secret_key_ref = payload.secret_key_ref
    if payload.headers_template is not None:
        destination.headers_template = payload.headers_template

    destination.validate()
    from datetime import datetime, timezone
    destination.updated_at = datetime.now(timezone.utc).isoformat()
    saved = container.destination_repo.save(destination)
    return _dest_to_response(saved)


@router.get(
    "/deliveries",
    response_model=PaginatedResponse[DeliveryResponse],
    status_code=status.HTTP_200_OK,
    summary="List delivery statuses for tenant outbox events (ADMIN/OWNER)",
)
async def list_deliveries(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    destination_id: Optional[str] = Query(default=None),
    tenant: TenantContext = Depends(require_permission(Permission.INTEGRATION_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> PaginatedResponse[DeliveryResponse]:
    params = PaginationParams(page=page, page_size=page_size)
    p = container.delivery_repo._placeholder()

    conditions = [f"bop_organization_id = {p}"]
    args = [tenant.bop_organization_id]

    if status_filter:
        conditions.append(f"status = {p}")
        args.append(status_filter.upper())
    if destination_id:
        conditions.append(f"destination_id = {p}")
        args.append(destination_id)

    where_sql = " AND ".join(conditions)
    count_sql = f"SELECT COUNT(*) as total FROM bop_integration_deliveries WHERE {where_sql}"
    count_rows = container.delivery_repo.db.fetch_dicts(count_sql, tuple(args))
    total_items = count_rows[0]["total"] if count_rows else 0

    select_sql = f"""
    SELECT * FROM bop_integration_deliveries WHERE {where_sql}
    ORDER BY created_at DESC
    LIMIT {params.limit} OFFSET {params.offset}
    """
    rows = container.delivery_repo.db.fetch_dicts(select_sql, tuple(args))

    items = [
        DeliveryResponse(
            id=r["id"],
            event_id=r["event_id"],
            destination_id=r["destination_id"],
            bop_organization_id=r["bop_organization_id"],
            status=r["status"],
            display_key=f"delivery.status.{r['status'].lower()}",
            attempt_count=r["attempt_count"],
            max_attempts=r["max_attempts"],
            next_attempt_at=r["next_attempt_at"],
            delivered_at=r.get("delivered_at"),
            last_error_code=r.get("last_error_code"),
            last_error_message=r.get("last_error_message"),
            created_at=r["created_at"],
        )
        for r in rows
    ]

    return PaginatedResponse.create(items=items, total_items=total_items, params=params)
