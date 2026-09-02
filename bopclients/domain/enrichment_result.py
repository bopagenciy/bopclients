"""EnrichmentResult domain entity representing snapshot of enrichment execution per tenant prospect."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Dict, Any, Optional


@dataclass
class EnrichmentResult:
    """Snapshot entity storing enrichment raw/derived data for a tenant prospect."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    prospect_id: str = ""
    provider: str = "forge"
    status: str = "success"  # success, partial_timeout, timeout, forbidden, dns_failure, no_website
    website_url: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        """Validate domain invariants."""
        if not self.organization_id:
            raise ValueError("organization_id required")
        if not self.prospect_id:
            raise ValueError("prospect_id required")
        if not self.provider.strip():
            raise ValueError("provider cannot be empty")
