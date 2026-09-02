"""Data Transfer Objects (DTOs) for P9 Continuous Monitoring Orchestration."""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class MonitoringPlanDecision:
    """Decision output produced by MonitoringPolicy for a prospect schedule."""

    recommended_interval_days: int
    next_check_at: str
    provider_names: List[str]
    operations: List[str]  # Combined operations for backwards compatibility
    executable_operations: List[str] = field(default_factory=lambda: ["monitor_public_signals"])
    recommended_operations: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    policy_version: str = "v1.0"
    source_fingerprint: str = ""


@dataclass
class DueMonitoringWork:
    """Item representing a schedule due for monitoring execution."""

    schedule_id: str
    organization_id: str
    prospect_id: str
    campaign_id: Optional[str]
    due_at: str
    provider_names: List[str]
    operations: List[str]
    executable_operations: List[str] = field(default_factory=lambda: ["monitor_public_signals"])
    recommended_operations: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    failure_count: int = 0
    policy_version: str = "v1.0"


@dataclass
class MonitoringExecutionResult:
    """Result summary of a continuous monitoring execution attempt."""

    schedule_id: str
    organization_id: str
    prospect_id: str
    campaign_id: Optional[str]
    research_run_id: Optional[str]
    started_at: str
    completed_at: str
    status: str  # SUCCESS, PARTIAL_SUCCESS, FAILED, SKIPPED
    operations_attempted: List[str]
    operations_succeeded: List[str]
    operations_failed: List[str]
    provider_results: Dict[str, Any]
    priority_before: Optional[int] = None
    priority_after: Optional[int] = None
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    next_check_at: Optional[str] = None
