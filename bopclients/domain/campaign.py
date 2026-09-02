"""Campaign domain entity."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Optional
from bopclients.domain.enums import CampaignStatus


@dataclass
class Campaign:
    """Prospecting campaign representing a targeted search initiative."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    icp_id: Optional[str] = None
    name: str = ""
    description: Optional[str] = None
    status: CampaignStatus = CampaignStatus.DRAFT
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        if not self.organization_id:
            raise ValueError("organization_id required")
        if not self.name.strip():
            raise ValueError("Campaign name cannot be empty")
