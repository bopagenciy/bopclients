"""Prospect Source domain entity for data provenance and auditability."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Optional


@dataclass
class ProspectSource:
    """Provenance tracking record for data origin of a prospect."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    prospect_id: str = ""
    source_type: str = "overture"  # ProspectSourceType value
    source_url: Optional[str] = None
    external_id: Optional[str] = None
    collected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        if not self.prospect_id:
            raise ValueError("prospect_id required")
        if not self.source_type:
            raise ValueError("source_type required")
