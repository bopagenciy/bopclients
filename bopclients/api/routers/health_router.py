"""Operational health and readiness check endpoints (/health, /ready)."""

from datetime import datetime, timezone
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus

router = APIRouter(tags=["Operations"])


@router.get("/health", status_code=status.HTTP_200_OK, summary="Liveness check")
@router.get("/health/live", status_code=status.HTTP_200_OK, summary="Liveness check")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/ready", summary="Readiness check")
@router.get("/health/ready", summary="Readiness check")
async def readiness(request: Request):
    container = getattr(request.app.state, "container", None)
    if not container:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "NOT_READY", "error": "Application container not initialized."},
        )

    result = RuntimeReadinessCheck.check(container.settings, db=container.db)
    summary = result.safe_summary()
    http_status = (
        status.HTTP_200_OK
        if result.status in (ReadinessStatus.READY, ReadinessStatus.DEGRADED)
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=http_status, content=summary)
