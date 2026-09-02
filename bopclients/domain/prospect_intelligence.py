"""ProspectIntelligence domain entity representing evidence-backed AI/deterministic sales research."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Dict, Any, Optional


@dataclass
class ProspectIntelligence:
    """Domain entity storing calculated sales research, evidence claims, and commercial opportunities for a prospect."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    prospect_id: str = ""
    provider: str = "deterministic"  # "deterministic" or "ai_gemini"
    research_version: str = "v1.0"
    confidence: float = 1.0  # 0.0 to 1.0
    data: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        if not self.organization_id:
            raise ValueError("organization_id required")
        if not self.prospect_id:
            raise ValueError("prospect_id required")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")
