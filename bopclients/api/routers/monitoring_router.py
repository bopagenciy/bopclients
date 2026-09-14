"""Continuous monitoring schedule endpoints (/api/v1/prospects/{id}/monitoring)."""

from fastapi import APIRouter, Depends, status
from bopclients.api.schemas.monitoring import MonitoringScheduleResponse, MonitoringScheduleUpdate
from bopclients.api.dependencies import require_permission, get_container
from bopclients.domain.auth.context import TenantContext
from bopclients.domain.auth.policy import Permission
from bopclients.domain.monitoring_schedule import MonitoringSchedule
from bopclients.domain.exceptions import EntityNotFoundError
from bopclients.runtime.container import RuntimeContainer

router = APIRouter(prefix="/api/v1/monitoring", tags=["Monitoring"])


def _schedule_to_response(s: MonitoringSchedule) -> MonitoringScheduleResponse:
    st = s.status or "ACTIVE"
    return MonitoringScheduleResponse(
        id=s.id,
        organization_id=s.organization_id,
        prospect_id=s.prospect_id,
        status=st,
        display_key=f"monitoring.status.{st.lower()}",
        next_check_at=s.next_check_at,
        last_check_at=s.last_check_at,
        last_success_at=s.last_success_at,
        last_failure_at=s.last_failure_at,
        recommended_interval_days=s.recommended_interval_days,
        failure_count=s.failure_count,
        last_error=s.last_error,
    )


@router.get(
    "/prospects/{prospect_id}",
    response_model=MonitoringScheduleResponse,
    status_code=status.HTTP_200_OK,
    summary="Get monitoring schedule for a prospect",
)
@router.get(
    "/{prospect_id}/monitoring",
    response_model=MonitoringScheduleResponse,
    status_code=status.HTTP_200_OK,
    summary="Get monitoring schedule for a prospect",
)
async def get_prospect_monitoring(
    prospect_id: str,
    tenant: TenantContext = Depends(require_permission(Permission.MONITORING_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> MonitoringScheduleResponse:
    org_id = tenant.organization_id
    prospect = container.prospect_repo.get_prospect_by_id(org_id, prospect_id)
    if not prospect:
        raise EntityNotFoundError(f"Prospect '{prospect_id}' not found.")

    schedule = container.schedule_repo.get_by_prospect(org_id, prospect_id)
    if not schedule:
        raise EntityNotFoundError(f"Monitoring schedule for prospect '{prospect_id}' not found.")

    return _schedule_to_response(schedule)


@router.patch(
    "/prospects/{prospect_id}",
    response_model=MonitoringScheduleResponse,
    status_code=status.HTTP_200_OK,
    summary="Update monitoring schedule for a prospect",
)
@router.patch(
    "/{prospect_id}/monitoring",
    response_model=MonitoringScheduleResponse,
    status_code=status.HTTP_200_OK,
    summary="Update monitoring schedule for a prospect",
)
async def update_prospect_monitoring(
    prospect_id: str,
    payload: MonitoringScheduleUpdate,
    tenant: TenantContext = Depends(require_permission(Permission.MONITORING_MANAGE)),
    container: RuntimeContainer = Depends(get_container),
) -> MonitoringScheduleResponse:
    org_id = tenant.organization_id
    prospect = container.prospect_repo.get_prospect_by_id(org_id, prospect_id)
    if not prospect:
        raise EntityNotFoundError(f"Prospect '{prospect_id}' not found.")

    schedule = container.schedule_repo.get_by_prospect(org_id, prospect_id)
    if not schedule:
        raise EntityNotFoundError(f"Monitoring schedule for prospect '{prospect_id}' not found.")

    if payload.status is not None:
        schedule.status = payload.status.upper()
    if payload.recommended_interval_days is not None:
        schedule.recommended_interval_days = payload.recommended_interval_days

    saved = container.schedule_repo.save(org_id, schedule)
    return _schedule_to_response(saved)


@router.get(
    "/overview",
    status_code=status.HTTP_200_OK,
    summary="Get tenant continuous monitoring overview",
)
async def get_monitoring_overview(
    tenant: TenantContext = Depends(require_permission(Permission.MONITORING_READ)),
    container: RuntimeContainer = Depends(get_container),
):
    org_id = tenant.organization_id
    p = container.schedule_repo._placeholder()
    sql = f"""
    SELECT
        COUNT(*) as total_schedules,
        SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_schedules,
        SUM(CASE WHEN status = 'paused' THEN 1 ELSE 0 END) as paused_schedules,
        SUM(CASE WHEN failure_count > 0 THEN 1 ELSE 0 END) as failing_schedules
    FROM monitoring_schedules
    WHERE organization_id = {p}
    """
    rows = container.schedule_repo.db.fetch_dicts(sql, (org_id,))
    data = rows[0] if rows else {}
    return {
        "organization_id": org_id,
        "total_schedules": data.get("total_schedules") or 0,
        "active_schedules": data.get("active_schedules") or 0,
        "paused_schedules": data.get("paused_schedules") or 0,
        "failing_schedules": data.get("failing_schedules") or 0,
    }


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Get tenant monitoring health status",
)
async def get_monitoring_health(
    tenant: TenantContext = Depends(require_permission(Permission.MONITORING_READ)),
    container: RuntimeContainer = Depends(get_container),
):
    org_id = tenant.organization_id
    p = container.schedule_repo._placeholder()
    sql = f"""
    SELECT
        COUNT(*) as total,
        SUM(CASE WHEN failure_count > 3 THEN 1 ELSE 0 END) as degraded
    FROM monitoring_schedules
    WHERE organization_id = {p} AND status = 'active'
    """
    rows = container.schedule_repo.db.fetch_dicts(sql, (org_id,))
    total = rows[0].get("total", 0) if rows else 0
    degraded = rows[0].get("degraded", 0) if rows else 0

    status_str = "DEGRADED" if degraded and degraded > 0 else "HEALTHY"
    return {
        "status": status_str,
        "organization_id": org_id,
        "active_monitors": total or 0,
        "degraded_monitors": degraded or 0,
    }
