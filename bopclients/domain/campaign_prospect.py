"""CampaignProspect domain entity representing prospect membership in a campaign."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Optional


@dataclass
class CampaignProspect:
    """Junction entity linking a Prospect to a Campaign within an Organization."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    campaign_id: str = ""
    prospect_id: str = ""
    status: str = "added"  # e.g., "added", "in_progress", "contacted", "bounced", "converted"
    relevance_score: Optional[float] = None
    added_at: str = field(
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
        if not self.campaign_id:
            raise ValueError("campaign_id required")
        if not self.prospect_id:
            raise ValueError("prospect_id required")
