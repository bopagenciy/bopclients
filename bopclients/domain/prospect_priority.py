"""ProspectPriority domain entity representing prioritization snapshots for sales operation."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Dict, Any, List, Optional


@dataclass
class NextResearchAction:
    """Actionable recommendation for research/intelligence next steps."""

    action: str = "none"  # none, refresh_enrichment, refresh_research, find_contact, monitor_public_signals
    priority: str = "low"  # low, medium, high, urgent
    reason: str = ""
    not_before: Optional[str] = None


@dataclass
class OutreachReadiness:
    """Outreach readiness status (human review gate)."""

    status: str = "not_ready"  # not_ready, research_needed, ready_for_human_review
    reasons: List[str] = field(default_factory=list)


@dataclass
class PriorityComponentScore:
    """Component contribution to total priority score."""

    factor: str  # lead_score, intent_signals, research_confidence, freshness
    score: float
    max_possible: float
    reason: str


@dataclass
class ProspectPriority:
    """Domain entity representing calculated priority of a prospect within a campaign."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    campaign_id: str = ""
    prospect_id: str = ""
    priority_score: int = 0  # 0 to 100
    priority_label: str = "low"  # low, medium, high, urgent
    lead_score_component: float = 0.0
    intent_signal_component: float = 0.0
    research_confidence_component: float = 0.0
    freshness_component: float = 0.0
    policy_version: str = "v1.0"
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
        if not self.campaign_id:
            raise ValueError("campaign_id required")
        if not self.prospect_id:
            raise ValueError("prospect_id required")
        if not (0 <= self.priority_score <= 100):
            raise ValueError(f"Priority score must be between 0 and 100, got {self.priority_score}")
        if self.priority_label not in ("low", "medium", "high", "urgent"):
            raise ValueError(f"Invalid priority_label '{self.priority_label}'")
