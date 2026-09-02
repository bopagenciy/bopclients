"""ResearchRunRecoveryService for reconciling orphan running ResearchRuns from crashed worker executions."""

import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from bopclients.domain.research_run import ResearchRun
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.repositories.monitoring_schedule_repository import MonitoringScheduleRepository

logger = logging.getLogger("bopclients.recovery")


def _parse_iso(iso_str: str) -> datetime:
    """Safely parse ISO 8601 string to a timezone-aware UTC datetime."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass
class ResearchRunRecoveryItem:
    """Detail summary of a single candidate ResearchRun recovery evaluation."""

    run_id: str
    organization_id: str
    prospect_id: Optional[str]
    monitoring_schedule_id: Optional[str]
    execution_attempt_id: Optional[str]
    started_at: Optional[str]
    recovered: bool
    reason: str  # STALE_NO_ACTIVE_LEASE, ACTIVE_LEASE_PRESENT, NO_LONGER_RUNNING, SCHEDULE_NOT_FOUND, AMBIGUOUS_CORRELATION
    error_message: Optional[str] = None


@dataclass
class ResearchRunRecoveryResult:
    """Execution result summary for a ResearchRun recovery reconciliation pass."""

    started_at: str
    completed_at: str
    duration_ms: float
    stale_threshold_seconds: int
    candidates_found: int
    recovered_count: int
    skipped_active_lease: int
    skipped_no_longer_running: int
    error_count: int
    recovered_run_ids: List[str] = field(default_factory=list)
    items: List[ResearchRunRecoveryItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class ResearchRunRecoveryService:
    """Service reconciling orphan 'running' ResearchRuns when worker processes crash abruptly."""

    def __init__(
        self,
        research_run_repo: ResearchRunRepository,
        schedule_repo: MonitoringScheduleRepository,
    ):
        self.research_run_repo = research_run_repo
        self.schedule_repo = schedule_repo

    def reconcile_stale_runs(
        self,
        now_dt: Optional[datetime] = None,
        stale_after_seconds: int = 900,
        limit: int = 100,
    ) -> ResearchRunRecoveryResult:
        """Reconcile stale 'running' ResearchRuns whose worker executions were lost.
        
        Args:
            now_dt: Optional reference datetime (defaults to UTC now).
            stale_after_seconds: Stale threshold in seconds (default 900s / 15 minutes).
            limit: Maximum candidate runs to process per recovery pass.
            
        Returns:
            ResearchRunRecoveryResult detailing recovery outcomes.
        """
        ref_dt = now_dt or datetime.now(timezone.utc)
        if ref_dt.tzinfo is None:
            ref_dt = ref_dt.replace(tzinfo=timezone.utc)

        start_time = time.time()
        start_iso = ref_dt.isoformat()
        stale_before_dt = ref_dt - timedelta(seconds=stale_after_seconds)
        stale_before_iso = stale_before_dt.isoformat()

        logger.info(f"Starting ResearchRun recovery pass (stale before: {stale_before_iso}, limit: {limit})...")

        candidates = self.research_run_repo.list_stale_running_runs(stale_before_iso, limit=limit)
        result_items: List[ResearchRunRecoveryItem] = []
        recovered_ids: List[str] = []
        recovered_count = 0
        skipped_active_lease = 0
        skipped_no_longer_running = 0
        error_count = 0
        warnings: List[str] = []

        for run in candidates:
            try:
                # 1. Inspect matching schedule lease state if schedule ID is available
                has_active_lease_for_this_attempt = False
                if run.monitoring_schedule_id:
                    sched = self.schedule_repo.get_by_id(run.organization_id, run.monitoring_schedule_id)
                    if sched and sched.lease_token and sched.lease_expires_at:
                        lease_exp_dt = _parse_iso(sched.lease_expires_at)
                        # Check if schedule lease is currently active (expires strictly after ref_dt / now)
                        if lease_exp_dt > ref_dt:
                            # Schedule has an active non-expired lease.
                            # Check if active lease belongs to THIS specific candidate attempt
                            if sched.current_execution_attempt_id and run.execution_attempt_id:
                                if sched.current_execution_attempt_id == run.execution_attempt_id:
                                    has_active_lease_for_this_attempt = True
                            else:
                                # Fallback if attempt IDs are unpopulated
                                has_active_lease_for_this_attempt = True

                # 2. If matching schedule has an active non-expired lease FOR THIS ATTEMPT, protect active execution
                if has_active_lease_for_this_attempt:
                    skipped_active_lease += 1
                    result_items.append(
                        ResearchRunRecoveryItem(
                            run_id=run.id,
                            organization_id=run.organization_id,
                            prospect_id=run.prospect_id,
                            monitoring_schedule_id=run.monitoring_schedule_id,
                            execution_attempt_id=run.execution_attempt_id,
                            started_at=run.started_at,
                            recovered=False,
                            reason="ACTIVE_LEASE_PRESENT",
                        )
                    )
                    continue

                # 3. Atomically transition orphan run status running -> failed
                err_msg = "WORKER_EXECUTION_LOST: execution exceeded stale threshold without active matching attempt"
                marked = self.research_run_repo.mark_stale_run_failed(
                    org_id=run.organization_id,
                    run_id=run.id,
                    error_message=err_msg,
                    completed_at_iso=start_iso,
                )

                if marked:
                    recovered_count += 1
                    recovered_ids.append(run.id)
                    result_items.append(
                        ResearchRunRecoveryItem(
                            run_id=run.id,
                            organization_id=run.organization_id,
                            prospect_id=run.prospect_id,
                            monitoring_schedule_id=run.monitoring_schedule_id,
                            execution_attempt_id=run.execution_attempt_id,
                            started_at=run.started_at,
                            recovered=True,
                            reason="STALE_NO_ACTIVE_LEASE",
                        )
                    )
                else:
                    skipped_no_longer_running += 1
                    result_items.append(
                        ResearchRunRecoveryItem(
                            run_id=run.id,
                            organization_id=run.organization_id,
                            prospect_id=run.prospect_id,
                            monitoring_schedule_id=run.monitoring_schedule_id,
                            execution_attempt_id=run.execution_attempt_id,
                            started_at=run.started_at,
                            recovered=False,
                            reason="NO_LONGER_RUNNING",
                        )
                    )

            except Exception as ex:
                error_count += 1
                warn_msg = f"Error recovering ResearchRun '{run.id}': {ex}"
                logger.warning(warn_msg)
                warnings.append(warn_msg)
                result_items.append(
                    ResearchRunRecoveryItem(
                        run_id=run.id,
                        organization_id=run.organization_id,
                        prospect_id=run.prospect_id,
                        monitoring_schedule_id=run.monitoring_schedule_id,
                        execution_attempt_id=run.execution_attempt_id,
                        started_at=run.started_at,
                        recovered=False,
                        reason="ERROR",
                        error_message=str(ex),
                    )
                )

        end_dt = datetime.now(timezone.utc)
        duration_ms = round((time.time() - start_time) * 1000, 2)

        res = ResearchRunRecoveryResult(
            started_at=start_iso,
            completed_at=end_dt.isoformat(),
            duration_ms=duration_ms,
            stale_threshold_seconds=stale_after_seconds,
            candidates_found=len(candidates),
            recovered_count=recovered_count,
            skipped_active_lease=skipped_active_lease,
            skipped_no_longer_running=skipped_no_longer_running,
            error_count=error_count,
            recovered_run_ids=recovered_ids,
            items=result_items,
            warnings=warnings,
        )
        logger.info(f"ResearchRun recovery pass completed: {recovered_count} recovered, {skipped_active_lease} active lease skipped, {error_count} errors.")
        return res
