"""Signal domain entity representing a buying/opportunity signal."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Optional


@dataclass
class Signal:
    """Signal entity representing a business opportunity or tech indicator on a prospect."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    prospect_id: str = ""
    type: str = ""  # SignalType value, e.g., "website_slow", "no_chatbot"
    value: Optional[str] = None
    confidence: float = 1.0  # 0.0 to 1.0
    source: str = "web_scrape"
    evidence: Optional[dict] = None
    detected_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        if not self.organization_id:
            raise ValueError("organization_id required")
        if not self.prospect_id:
            raise ValueError("prospect_id required")
        if not self.type.strip():
            raise ValueError("Signal type cannot be empty")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")
