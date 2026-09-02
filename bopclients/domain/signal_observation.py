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
            title_part = (
                self.evidence.get("rfp_title")
                or self.evidence.get("job_title")
                or self.evidence.get("location_name")
                or self.evidence.get("funding_round")
                or self.evidence.get("matched_rule")
                or ""
            )
            semantic_id = str(title_part).strip().lower()

        raw_key = f"{self.provider}:{self.prospect_id}:{self.signal_type}:{norm_url}:{self.external_id or ''}:{semantic_id}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:32]

    def compute_content_fingerprint(self) -> str:
        """Compute content fingerprint to detect meaningful state updates (e.g. currentness/due_date/funding_amount changes)."""
        ev_str = ""
        if isinstance(self.evidence, dict):
            cur = self.evidence.get("currentness", "")
            due = self.evidence.get("due_date", "")
            amt = self.evidence.get("funding_amount", "")
            snip = str(self.evidence.get("snippet", ""))[:100]
            ev_str = f"{cur}:{due}:{amt}:{snip}"
        raw_key = f"{self.confidence:.2f}:{ev_str}"
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:16]

    def compute_semantic_event_key(self) -> str:
        """Compute logical semantic event key for cross-provider event grouping and corroboration."""
        ev = self.evidence if isinstance(self.evidence, dict) else {}
        date_win = (self.published_at or self.first_seen_at or "")[:7]  # YYYY-MM window

        if self.signal_type == "new_funding":
            f_round = (ev.get("funding_round") or ev.get("matched_rule") or "funding").strip().lower().replace(" ", "_")
            return f"new_funding:{self.prospect_id}:{f_round}:{date_win}"

        elif self.signal_type == "public_request_for_proposal":
            sol_id = self.external_id or ev.get("solicitation_number") or ev.get("rfp_title") or "rfp"
            norm_sol = str(sol_id).strip().lower().replace(" ", "_")
            return f"public_request_for_proposal:{self.prospect_id}:{norm_sol}"

        elif self.signal_type == "vendor_search":
            v_id = self.external_id or ev.get("opportunity_title") or ev.get("matched_rule") or "vendor_search"
            norm_v = str(v_id).strip().lower().replace(" ", "_")
            return f"vendor_search:{self.prospect_id}:{norm_v}"

        sub_id = (
            self.external_id
            or ev.get("location_name")
            or ev.get("service_name")
            or f"{ev.get('executive_role', '')}:{ev.get('executive_name', '')}"
            or ev.get("matched_rule")
            or ""
        )
        norm_sub = str(sub_id).strip().lower().replace(" ", "_")
        return f"{self.signal_type}:{self.prospect_id}:{norm_sub}"

    def validate(self) -> None:
        if not self.organization_id:
            raise ValueError("organization_id is required")
        if not self.prospect_id:
            raise ValueError("prospect_id is required")
        if not self.signal_type.strip():
            raise ValueError("signal_type cannot be empty")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {self.confidence}")
