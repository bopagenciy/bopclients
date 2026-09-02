"""ResearchRun domain entity representing research and prospecting execution tracking."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Optional


@dataclass
class ResearchRun:
    """Entity representing an execution run of research, discovery, or enrichment."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    campaign_id: Optional[str] = None
    prospect_id: Optional[str] = None
    monitoring_schedule_id: Optional[str] = None
    execution_attempt_id: Optional[str] = None
    run_type: str = "discovery"  # e.g., "discovery", "enrichment", "website_audit", "social_research", "intent_research", "signal_monitoring"
    status: str = "pending"  # e.g., "pending", "running", "completed", "failed", "cancelled"
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
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
        if not self.run_type.strip():
            raise ValueError("run_type cannot be empty")
        valid_statuses = {"pending", "running", "completed", "failed", "cancelled"}
        if self.status not in valid_statuses:
            raise ValueError(f"Invalid status '{self.status}'. Must be one of {valid_statuses}")
