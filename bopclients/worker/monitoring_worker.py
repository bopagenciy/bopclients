"""MonitoringWorker application runner processing due monitoring schedules with budget controls and observability."""

import uuid
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Callable
from bopclients.domain.exceptions import BopClientsDomainError
from bopclients.domain.rate_limit import ProviderCallBudget
from bopclients.application.monitoring_dto import MonitoringExecutionResult
from bopclients.application.continuous_monitoring_service import ContinuousMonitoringService
from bopclients.infrastructure.repositories.monitoring_schedule_repository import MonitoringScheduleRepository

logger = logging.getLogger("bopclients.worker")


@dataclass
class MonitoringWorkerConfig:
    """Configuration options for MonitoringWorker execution budget and lease parameters."""

    batch_size: int = 25
    max_items: int = 100
    max_run_seconds: int = 600
    lease_duration_seconds: int = 300
    lease_renew_before_seconds: int = 90
    research_run_recovery_enabled: bool = True
    research_run_stale_after_seconds: int = 900
    research_run_recovery_limit: int = 100
    max_provider_calls_per_run: Optional[int] = None
    dry_run: bool = False

    def validate(self):
        if self.batch_size <= 0:
            raise ValueError("batch_size must be greater than 0.")
        if self.max_items <= 0:
            raise ValueError("max_items must be greater than 0.")
        if self.max_run_seconds <= 0:
            raise ValueError("max_run_seconds must be greater than 0.")
        if self.lease_duration_seconds <= 0:
            raise ValueError("lease_duration_seconds must be greater than 0.")
        if self.lease_renew_before_seconds <= 0:
            raise ValueError("lease_renew_before_seconds must be greater than 0.")
        if self.lease_renew_before_seconds >= self.lease_duration_seconds:
            raise ValueError("lease_renew_before_seconds must be strictly less than lease_duration_seconds.")
        if self.research_run_stale_after_seconds <= 0:
            raise ValueError("research_run_stale_after_seconds must be greater than 0.")
        if self.research_run_recovery_limit <= 0:
            raise ValueError("research_run_recovery_limit must be greater than 0.")
        if self.max_provider_calls_per_run is not None and self.max_provider_calls_per_run <= 0:
            raise ValueError("max_provider_calls_per_run must be greater than 0.")


@dataclass
class MonitoringWorkerItemResult:
    """Summary result of a single schedule processed by MonitoringWorker."""

    schedule_id: str
    organization_id: str
    prospect_id: str
    campaign_id: Optional[str]
    status: str  # SUCCESS, PARTIAL_SUCCESS, FAILED, SKIPPED, DRY_RUN
    started_at: str
    completed_at: str
    duration_ms: float
    execution_result: Optional[MonitoringExecutionResult] = None
    skip_reason: Optional[str] = None
    warning_summary: Optional[str] = None
    error_summary: Optional[str] = None


@dataclass
class MonitoringWorkerRunResult:
    """Overall execution summary for a MonitoringWorker run."""

    worker_run_id: str
    started_at: str
    completed_at: str
    duration_ms: float
    items_discovered: int
    items_attempted: int
    items_claimed: int
    items_completed: int
    success_count: int
    partial_success_count: int
    failed_count: int
    skipped_count: int
    lease_busy_count: int
    organization_count: int
    stopped_reason: str  # NO_DUE_WORK, MAX_ITEMS_REACHED, MAX_DURATION_REACHED, DRY_RUN, STOP_REQUESTED, FATAL_ERROR, PROVIDER_BUDGET_EXHAUSTED
    item_results: List[MonitoringWorkerItemResult] = field(default_factory=list)
    recovery_result: Optional[Any] = None
    provider_calls_attempted: int = 0
    provider_calls_executed: int = 0
    provider_rate_limited: int = 0
    provider_tenant_capacity_limited: int = 0
    provider_concurrency_limited: int = 0
    provider_cooldown_skips: int = 0
    provider_budget_skips: int = 0
    backpressure_count: int = 0
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class MonitoringWorker:
    """Stateless worker runner executing due monitoring schedules using ContinuousMonitoringService."""

    def __init__(
        self,
        schedule_repo: MonitoringScheduleRepository,
        monitoring_service: ContinuousMonitoringService,
        config: Optional[MonitoringWorkerConfig] = None,
        recovery_service: Optional[Any] = None,
    ):
        self.schedule_repo = schedule_repo
        self.monitoring_service = monitoring_service
        self.config = config or MonitoringWorkerConfig()
        self.recovery_service = recovery_service
        self.config.validate()
        self.stop_requested = False

    def request_stop(self):
        """Cooperative signal to stop processing after current item finishes."""
        self.stop_requested = True

    def run(
        self,
        now_dt: Optional[datetime] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> MonitoringWorkerRunResult:
        """Run worker backlog processing loop within configured run budgets."""
        worker_run_id = str(uuid.uuid4())
        start_time = now_dt or datetime.now(timezone.utc)
        start_iso = start_time.isoformat()
        start_mono = time.monotonic()

        logger.info(f"Starting MonitoringWorker run {worker_run_id[:8]} (dry_run={self.config.dry_run})")

        seen_schedule_ids = set()
        org_items_count: Dict[str, int] = {}
        item_results: List[MonitoringWorkerItemResult] = []

        items_discovered = 0
        items_attempted = 0
        items_claimed = 0
        items_completed = 0
        success_count = 0
        partial_success_count = 0
        failed_count = 0
        skipped_count = 0
        lease_busy_count = 0

        provider_calls_attempted = 0
        provider_calls_executed = 0
        provider_rate_limited = 0
        provider_tenant_capacity_limited = 0
        provider_concurrency_limited = 0
        provider_cooldown_skips = 0
        provider_budget_skips = 0
        backpressure_count = 0

        stopped_reason = "NO_DUE_WORK"

        # RECOVERY PASS (If enabled and not dry-run)
        recovery_result = None
        if self.recovery_service and self.config.research_run_recovery_enabled and not self.config.dry_run:
            try:
                recovery_result = self.recovery_service.reconcile_stale_runs(
                    now_dt=start_time,
                    stale_after_seconds=self.config.research_run_stale_after_seconds,
                    limit=self.config.research_run_recovery_limit,
                )
            except Exception as ex:
                logger.warning(f"Error during worker startup recovery pass: {ex}")

        # DRY RUN MODE
        if self.config.dry_run:
            due_candidates = self.schedule_repo.list_due_system(
                now_iso=start_iso, limit=self.config.max_items
            )
            items_discovered = len(due_candidates)
            org_set = {s.organization_id for s in due_candidates}

            for s in due_candidates:
                item_results.append(
                    MonitoringWorkerItemResult(
                        schedule_id=s.id,
                        organization_id=s.organization_id,
                        prospect_id=s.prospect_id,
                        campaign_id=s.campaign_id,
                        status="DRY_RUN",
                        started_at=start_iso,
                        completed_at=start_iso,
                        duration_ms=0.0,
                        skip_reason="DRY_RUN",
                    )
                )

            end_time = datetime.now(timezone.utc)
            end_iso = end_time.isoformat()
            duration_ms = (time.monotonic() - start_mono) * 1000.0

            return MonitoringWorkerRunResult(
                worker_run_id=worker_run_id,
                started_at=start_iso,
                completed_at=end_iso,
                duration_ms=duration_ms,
                items_discovered=items_discovered,
                items_attempted=0,
                items_claimed=0,
                items_completed=0,
                success_count=0,
                partial_success_count=0,
                failed_count=0,
                skipped_count=len(due_candidates),
                lease_busy_count=0,
                organization_count=len(org_set),
                stopped_reason="DRY_RUN",
                item_results=item_results,
            )

        # REAL EXECUTION LOOP
        run_call_budget = ProviderCallBudget(max_calls=self.config.max_provider_calls_per_run)

        try:
            while items_attempted < self.config.max_items:
                elapsed_sec = time.monotonic() - start_mono
                if elapsed_sec >= self.config.max_run_seconds:
                    stopped_reason = "MAX_DURATION_REACHED"
                    break

                if self.stop_requested or (should_stop and should_stop()):
                    stopped_reason = "STOP_REQUESTED"
                    break

                fetch_limit = min(self.config.batch_size, self.config.max_items - items_attempted)
                due_batch = self.schedule_repo.list_due_system(
                    now_iso=start_time.isoformat(), limit=fetch_limit
                )

                # Filter candidate items not yet seen in this run
                candidates = [s for s in due_batch if s.id not in seen_schedule_ids]
                if not candidates:
                    stopped_reason = "NO_DUE_WORK"
                    break

                items_discovered += len(candidates)

                processed_in_batch = 0
                for s in candidates:
                    if items_attempted >= self.config.max_items:
                        stopped_reason = "MAX_ITEMS_REACHED"
                        break

                    elapsed_sec = time.monotonic() - start_mono
                    if elapsed_sec >= self.config.max_run_seconds:
                        stopped_reason = "MAX_DURATION_REACHED"
                        break

                    if self.stop_requested or (should_stop and should_stop()):
                        stopped_reason = "STOP_REQUESTED"
                        break

                    if (
                        self.config.max_provider_calls_per_run is not None
                        and (provider_calls_executed >= self.config.max_provider_calls_per_run or run_call_budget.is_exhausted)
                    ):
                        stopped_reason = "PROVIDER_BUDGET_EXHAUSTED"
                        break

                    seen_schedule_ids.add(s.id)
                    items_attempted += 1
                    processed_in_batch += 1

                    item_start = datetime.now(timezone.utc)
                    item_start_iso = item_start.isoformat()

                    try:
                        exec_attempt_id = str(uuid.uuid4())
                        try:
                            exec_res = self.monitoring_service.execute_due(
                                organization_id=s.organization_id,
                                schedule_id=s.id,
                                now_dt=item_start,
                                execution_attempt_id=exec_attempt_id,
                                call_budget=run_call_budget,
                            )
                        except TypeError:
                            exec_res = self.monitoring_service.execute_due(
                                organization_id=s.organization_id,
                                schedule_id=s.id,
                                now_dt=item_start,
                            )

                        item_end = datetime.now(timezone.utc)
                        item_dur_ms = (item_end - item_start).total_seconds() * 1000.0

                        # Check if claim succeeded
                        if exec_res.skip_reason == "LEASE_BUSY":
                            lease_busy_count += 1
                            skipped_count += 1
                        else:
                            items_claimed += 1
                            items_completed += 1
                            org_items_count[s.organization_id] = org_items_count.get(s.organization_id, 0) + 1

                            if exec_res.skip_reason == "LEASE_OWNERSHIP_LOST":
                                skipped_count += 1
                            elif exec_res.status == "SUCCESS":
                                success_count += 1
                            elif exec_res.status == "PARTIAL_SUCCESS":
                                partial_success_count += 1
                            elif exec_res.status == "FAILED":
                                failed_count += 1
                            elif exec_res.status in ("SKIPPED", "SKIPPED_BACKPRESSURE"):
                                skipped_count += 1

                            if exec_res.status == "SKIPPED_BACKPRESSURE" or exec_res.skip_reason in (
                                "BACKPRESSURE",
                                "PROVIDER_BACKPRESSURE",
                            ):
                                backpressure_count += 1

                            # Tally provider-level execution metrics
                            for p_name, p_res in (exec_res.provider_results or {}).items():
                                provider_calls_attempted += 1
                                p_st = p_res.get("status", "") if isinstance(p_res, dict) else ""
                                if p_st in ("SUCCESS", "SUCCESS_NO_SIGNALS", "PARTIAL_SUCCESS", "FAILED"):
                                    provider_calls_executed += 1
                                elif p_st == "SKIPPED_RATE_LIMITED":
                                    provider_rate_limited += 1
                                elif p_st == "SKIPPED_TENANT_CAPACITY_LIMITED":
                                    provider_tenant_capacity_limited += 1
                                elif p_st == "SKIPPED_CONCURRENCY_LIMITED":
                                    provider_concurrency_limited += 1
                                elif p_st == "SKIPPED_COOLDOWN":
                                    provider_cooldown_skips += 1
                                elif p_st == "SKIPPED_BUDGET_EXHAUSTED":
                                    provider_budget_skips += 1

                        item_results.append(
                            MonitoringWorkerItemResult(
                                schedule_id=s.id,
                                organization_id=s.organization_id,
                                prospect_id=s.prospect_id,
                                campaign_id=s.campaign_id,
                                status=exec_res.status,
                                started_at=item_start_iso,
                                completed_at=item_end.isoformat(),
                                duration_ms=item_dur_ms,
                                execution_result=exec_res,
                                skip_reason=exec_res.skip_reason,
                                warning_summary="; ".join(exec_res.warnings) if exec_res.warnings else None,
                                error_summary="; ".join(exec_res.errors) if exec_res.errors else None,
                            )
                        )

                    except Exception as ex:
                        # Per-item exception isolation: item failure does not crash worker run!
                        item_end = datetime.now(timezone.utc)
                        item_dur_ms = (item_end - item_start).total_seconds() * 1000.0
                        failed_count += 1
                        err_msg = str(ex)[:255]
                        item_results.append(
                            MonitoringWorkerItemResult(
                                schedule_id=s.id,
                                organization_id=s.organization_id,
                                prospect_id=s.prospect_id,
                                campaign_id=s.campaign_id,
                                status="FAILED",
                                started_at=item_start_iso,
                                completed_at=item_end.isoformat(),
                                duration_ms=item_dur_ms,
                                error_summary=err_msg,
                            )
                        )

                    if (
                        self.config.max_provider_calls_per_run is not None
                        and (provider_calls_executed >= self.config.max_provider_calls_per_run or run_call_budget.is_exhausted)
                    ):
                        stopped_reason = "PROVIDER_BUDGET_EXHAUSTED"
                        break

                if stopped_reason == "PROVIDER_BUDGET_EXHAUSTED":
                    break

                if processed_in_batch == 0:
                    stopped_reason = "NO_DUE_WORK"
                    break

        except Exception as fatal_ex:
            logger.critical(f"Fatal worker infrastructure exception: {fatal_ex}")
            stopped_reason = "FATAL_ERROR"

        end_time = datetime.now(timezone.utc)
        end_iso = end_time.isoformat()
        duration_ms = (end_time - start_time).total_seconds() * 1000.0

        org_count = len({r.organization_id for r in item_results})

        logger.info(
            f"Completed MonitoringWorker run {worker_run_id[:8]}: {items_completed} completed, "
            f"{success_count} success, {failed_count} failed, reason={stopped_reason}"
        )

        if items_attempted >= self.config.max_items and stopped_reason == "NO_DUE_WORK":
            stopped_reason = "MAX_ITEMS_REACHED"

        return MonitoringWorkerRunResult(
            worker_run_id=worker_run_id,
            started_at=start_iso,
            completed_at=end_iso,
            duration_ms=duration_ms,
            items_discovered=items_discovered,
            items_attempted=items_attempted,
            items_claimed=items_claimed,
            items_completed=items_completed,
            success_count=success_count,
            partial_success_count=partial_success_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            lease_busy_count=lease_busy_count,
            organization_count=org_count,
            stopped_reason=stopped_reason,
            item_results=item_results,
            recovery_result=recovery_result,
            provider_calls_attempted=provider_calls_attempted,
            provider_calls_executed=provider_calls_executed,
            provider_rate_limited=provider_rate_limited,
            provider_tenant_capacity_limited=provider_tenant_capacity_limited,
            provider_concurrency_limited=provider_concurrency_limited,
            provider_cooldown_skips=provider_cooldown_skips,
            provider_budget_skips=provider_budget_skips,
            backpressure_count=backpressure_count,
        )
