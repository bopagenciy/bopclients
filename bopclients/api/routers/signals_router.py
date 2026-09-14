"""Signal endpoints (/api/v1/prospects/{id}/signals)."""

from typing import List, Optional
from fastapi import APIRouter, Depends, status, Query
from bopclients.api.schemas.signals import SignalResponse
from bopclients.api.dependencies import require_permission, get_container
from bopclients.domain.auth.context import TenantContext
from bopclients.domain.auth.policy import Permission
from bopclients.domain.exceptions import EntityNotFoundError
from bopclients.runtime.container import RuntimeContainer

router = APIRouter(prefix="/api/v1/prospects", tags=["Signals"])


@router.get(
    "/{prospect_id}/signals",
    response_model=List[SignalResponse],
    status_code=status.HTTP_200_OK,
    summary="List signals for a specific prospect",
)
async def get_prospect_signals(
    prospect_id: str,
    category: Optional[str] = Query(default=None, description="Filter by category: NEED, COMPANY_ACTIVITY, BUYING_INTENT"),
    tenant: TenantContext = Depends(require_permission(Permission.SIGNALS_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> List[SignalResponse]:
    org_id = tenant.organization_id
    prospect = container.prospect_repo.get_prospect_by_id(org_id, prospect_id)
    if not prospect:
        raise EntityNotFoundError(f"Prospect '{prospect_id}' not found.")

    signals = container.prospect_repo.get_signals_by_prospect(org_id, prospect_id)

    if category and category.strip():
        cat_clean = category.strip().upper()
        signals = [s for s in signals if (s.category.value if hasattr(s.category, "value") else str(s.category)).upper() == cat_clean]

    res = []
    for s in signals:
        cat_str = (s.category.value if hasattr(s.category, "value") else str(s.category)).upper()
        res.append(
            SignalResponse(
                id=s.id,
                prospect_id=s.prospect_id,
                category=cat_str,
                display_key=f"signal.category.{cat_str.lower()}",
                signal_type=s.signal_type,
                confidence=s.confidence,
                headline=s.headline,
                summary=s.summary,
                source_url=s.source_url,
                detected_at=s.detected_at,
                created_at=s.created_at,
            )
        )
    return res
