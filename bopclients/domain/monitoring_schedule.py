"""MonitoringSchedule domain entity representing scheduled continuous monitoring state."""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any


@dataclass
class MonitoringSchedule:
    """Domain entity for prospect monitoring schedule state."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    prospect_id: str = ""
    campaign_id: Optional[str] = None
    scope_key: str = ""
    status: str = "active"  # active, paused, disabled
    next_check_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_check_at: Optional[str] = None
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    recommended_interval_days: int = 14
    provider_names: List[str] = field(default_factory=list)
    operations: List[str] = field(default_factory=list)
    failure_count: int = 0
    last_error: Optional[str] = None
    lease_token: Optional[str] = None
    lease_expires_at: Optional[str] = None
    policy_version: str = "v1.0"
    source_fingerprint: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if not self.scope_key:
            c_part = self.campaign_id or "__GLOBAL__"
            self.scope_key = f"{self.prospect_id}:{c_part}"

    def validate(self) -> None:
        if not self.organization_id:
            raise ValueError("organization_id is required")
        if not self.prospect_id:
            raise ValueError("prospect_id is required")
        if self.status not in ("active", "paused", "disabled"):
            raise ValueError(f"Invalid status '{self.status}'. Must be active, paused, or disabled.")

    def is_due(self, now_iso: Optional[str] = None) -> bool:
        """Check if schedule is due for monitoring execution."""
        if self.status != "active":
            return False
        ref_iso = now_iso or datetime.now(timezone.utc).isoformat()
        return self.next_check_at <= ref_iso

    def is_leased(self, now_iso: Optional[str] = None) -> bool:
        """Check if schedule is currently leased by another active worker."""
        if not self.lease_token or not self.lease_expires_at:
            return False
        ref_iso = now_iso or datetime.now(timezone.utc).isoformat()
        return self.lease_expires_at > ref_iso
