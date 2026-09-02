"""PublicSignalObservation domain entity representing raw public event observations."""

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from bopclients.domain.enums import SignalCategory, IntentStrength


@dataclass
class PublicSignalObservation:
    """Raw public signal observation entity for temporal traceability and deduplication."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    prospect_id: str = ""
    provider: str = "official_website"
    signal_type: str = ""
    category: str = SignalCategory.COMPANY_ACTIVITY.value
    intent_strength: str = IntentStrength.NONE.value
    source_type: str = "official_company_site"
    source_url: str = ""
    external_id: Optional[str] = None
    confidence: float = 1.0
    evidence: Dict[str, Any] = field(default_factory=dict)
    raw_metadata: Dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""
    published_at: Optional[str] = None
    first_seen_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if not self.fingerprint:
            self.fingerprint = self.compute_fingerprint()

    def compute_fingerprint(self) -> str:
        """Compute stable identity fingerprint separating observation identity from cosmetic content edits."""
        norm_url = (self.source_url or "").strip().lower()
        semantic_id = ""
        if isinstance(self.evidence, dict):
            # Prefer stable semantic identifier: rfp_title > job_title > location_name > matched_rule
            title_part = (
                self.evidence.get("rfp_title")
                or self.evidence.get("job_title")
                or self.evidence.get("location_name")
                or self.evidence.get("matched_rule")
                or ""
            )
            semantic_id = str(title_part).strip().lower()

        raw_key = f"{self.provider}:{self.prospect_id}:{self.signal_type}:{norm_url}:{self.external_id or ''}:{semantic_id}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:32]

    def compute_content_fingerprint(self) -> str:
        """Compute content fingerprint to detect meaningful state updates (e.g. currentness/due_date changes)."""
        ev_str = ""
        if isinstance(self.evidence, dict):
            cur = self.evidence.get("currentness", "")
            due = self.evidence.get("due_date", "")
            snip = str(self.evidence.get("snippet", ""))[:100]
            ev_str = f"{cur}:{due}:{snip}"
        raw_key = f"{self.confidence:.2f}:{ev_str}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]

    def validate(self) -> None:
        if not self.organization_id:
            raise ValueError("organization_id is required")
        if not self.prospect_id:
            raise ValueError("prospect_id is required")
        if not self.signal_type.strip():
            raise ValueError("signal_type cannot be empty")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")
