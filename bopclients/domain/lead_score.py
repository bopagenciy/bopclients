"""Lead Score domain entity."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Optional


@dataclass
class LeadScore:
    """Lead Score entity for evaluating prospect relevance and qualification."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    prospect_id: str = ""
    score: int = 0  # 0 to 100
    scoring_version: str = "v1.0"
    explanation: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        if not self.organization_id:
            raise ValueError("organization_id required")
        if not self.prospect_id:
            raise ValueError("prospect_id required")
        if not (0 <= self.score <= 100):
            raise ValueError(f"Score must be between 0 and 100, got {self.score}")
