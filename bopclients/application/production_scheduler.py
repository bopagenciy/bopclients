import re
import uuid
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Callable

from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.worker.monitoring_worker import MonitoringWorker, MonitoringWorkerRunResult
from bopclients.infrastructure.repositories.scheduler_repository import SchedulerRepository
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.application.scheduler_heartbeat import SchedulerHeartbeat

logger = logging.getLogger("bopclients.scheduler")


def sanitize_error_message(err: Any, max_length: int = 500) -> Optional[str]:
    """Sanitize error messages ensuring passwords, DSNs, auth headers, API keys, and tokens are masked."""
    if err is None:
        return None
    text = str(err)
    # Mask passwords in connection URIs (e.g. postgresql://user:password@host/db)
    text = re.sub(r"://([^:]+):([^@]+)@", r"://\1:***@", text)
    # Mask authorization headers / bearer tokens
    text = re.sub(r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]+", r"\1***", text)
    # Mask explicit api keys, secrets, tokens, and passwords
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password|passwd|pwd)\s*([:=])\s*['\"]?[^\s,'\"]+['\"]?", r"\1\2***", text)
    # Strip traceback preamble if present
    if "Traceback (most recent call last)" in text:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = lines[-1] if lines else "Unhandled Exception"
    if len(text) > max_length:
        text = text[: max_length - 3] + "..."
    return text


@dataclass
class SchedulerTickResult:
    """Summary result of a single production scheduler tick invocation."""

    scheduler_run_id: str
    scheduler_key: str
    status: str  # COMPLETED, SKIPPED_LEASE_HELD, SKIPPED_DISABLED, FAILED, OWNERSHIP_LOST
    started_at: str
    completed_at: str
    duration_ms: float
    worker_run_id: Optional[str] = None
    worker_stopped_reason: Optional[str] = None
    items_attempted: int = 0
    items_claimed: int = 0
    success_count: int = 0
    failure_count: int = 0
    backpressure_count: int = 0
    recovered_runs_count: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None

    def safe_summary(self) -> Dict[str, Any]:
        """Return safe dictionary summary without sensitive tokens."""
        return {
            "scheduler_run_id": self.scheduler_run_id,
            "scheduler_key": self.scheduler_key,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": round(self.duration_ms, 2),
            "worker_run_id": self.worker_run_id,
            "worker_stopped_reason": self.worker_stopped_reason,
            "items_attempted": self.items_attempted,
            "items_claimed": self.items_claimed,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "backpressure_count": self.backpressure_count,
            "recovered_runs_count": self.recovered_runs_count,
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


class ProductionScheduler:
    """Production scheduler layer coordinating periodic worker execution with distributed lease protection."""

    def __init__(
        self,
        scheduler_repo: SchedulerRepository,
        worker: MonitoringWorker,
        settings: Optional[RuntimeSettings] = None,
        schedule_repo: Optional[Any] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.scheduler_repo = scheduler_repo
        self.worker = worker
        self.settings = settings or RuntimeSettings.from_env()
        self.schedule_repo = schedule_repo
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def tick(
        self,
        force: bool = False,
        now_dt: Optional[datetime] = None,
    ) -> SchedulerTickResult:
        """Execute a single production scheduler tick.

        1. Inspect operational policy (enabled flag) and runtime readiness.
        2. Reconcile stale orphan scheduler runs.
        3. Acquire distributed scheduler dispatch lease.
        4. Dispatch one MonitoringWorker.run() with cooperative heartbeat.
        5. Persist run outcome into scheduler_runs.
        6. Release scheduler dispatch lease.
        7. Return structured tick result.
        """
        start_mono = time.monotonic()
        now = now_dt or self.clock()
        now_iso = now.isoformat()
        scheduler_key = self.settings.scheduler_key
        run_id = str(uuid.uuid4())
        lease_token = str(uuid.uuid4())

        logger.info(f"Production scheduler tick started (run_id={run_id[:8]}, key='{scheduler_key}')")

        # 1. Inspect Enabled Flag
        if not self.settings.production_scheduler_enabled and not force:
            logger.info(f"Production scheduler disabled in configuration. Skipping tick.")
            duration_ms = (time.monotonic() - start_mono) * 1000.0
            end_iso = (now_dt or self.clock()).isoformat()

            # Under ACQUIRED_DISPATCH_ONLY: do NOT record in scheduler_runs
            return SchedulerTickResult(
                scheduler_run_id="",
                scheduler_key=scheduler_key,
                status="SKIPPED_DISABLED",
                started_at=now_iso,
                completed_at=end_iso,
                duration_ms=duration_ms,
                error_code="SCHEDULER_DISABLED",
                error_message="Production scheduler is disabled in runtime configuration",
            )

        # 2. Inspect Runtime Readiness (Fail-Closed)
        try:
            readiness = RuntimeReadinessCheck.check(self.settings, db=self.scheduler_repo.db)
            if readiness.status == ReadinessStatus.NOT_READY:
                err_msg = f"Runtime readiness NOT_READY: {'; '.join(readiness.errors)}"
                safe_err_msg = sanitize_error_message(err_msg)
                logger.error(f"Production scheduler startup aborted: {safe_err_msg}")
                duration_ms = (time.monotonic() - start_mono) * 1000.0
                end_iso = (now_dt or self.clock()).isoformat()

                # Under ACQUIRED_DISPATCH_ONLY: do NOT record in scheduler_runs
                return SchedulerTickResult(
                    scheduler_run_id="",
                    scheduler_key=scheduler_key,
                    status="FAILED",
                    started_at=now_iso,
                    completed_at=end_iso,
                    duration_ms=duration_ms,
                    error_code="DATABASE_NOT_READY",
                    error_message=safe_err_msg,
                )
        except Exception as check_ex:
            safe_ex = sanitize_error_message(check_ex)
            logger.critical(f"Pre-flight readiness evaluation failed: {safe_ex}")
            duration_ms = (time.monotonic() - start_mono) * 1000.0
            end_iso = (now_dt or self.clock()).isoformat()
            return SchedulerTickResult(
                scheduler_run_id="",
                scheduler_key=scheduler_key,
                status="FAILED",
                started_at=now_iso,
                completed_at=end_iso,
                duration_ms=duration_ms,
                error_code="DATABASE_NOT_READY",
                error_message=safe_ex,
            )

        # 3. Reconcile Stale Orphan Scheduler Runs
        recovered_runs = 0
        try:
            stale_threshold_sec = self.settings.scheduler_recovery_stale_after_seconds
            stale_before = now - timedelta(seconds=stale_threshold_sec)
            recovered_runs = self.scheduler_repo.reconcile_stale_runs(
                stale_before_iso=stale_before.isoformat(),
                now_dt=now,
                limit=self.settings.scheduler_recovery_limit,
            )
            if recovered_runs > 0:
                logger.info(f"Reconciled {recovered_runs} stale orphan scheduler runs to FAILED")
        except Exception as rec_ex:
            logger.warning(f"Error during scheduler stale run reconciliation: {sanitize_error_message(rec_ex)}")

        # 4. Acquire Distributed Dispatch Lease
        try:
            acquired, reason = self.scheduler_repo.try_acquire_dispatch(
                scheduler_key=scheduler_key,
                lease_token=lease_token,
                lease_duration_seconds=self.settings.scheduler_lease_seconds,
                run_id=run_id,
                now_dt=now,
            )
        except Exception as lease_ex:
            safe_lease_ex = sanitize_error_message(lease_ex)
            logger.error(f"Error acquiring scheduler dispatch lease: {safe_lease_ex}")
            duration_ms = (time.monotonic() - start_mono) * 1000.0
            end_iso = (now_dt or self.clock()).isoformat()
            return SchedulerTickResult(
                scheduler_run_id="",
                scheduler_key=scheduler_key,
                status="FAILED",
                started_at=now_iso,
                completed_at=end_iso,
                duration_ms=duration_ms,
                error_code="DATABASE_ERROR",
                error_message=safe_lease_ex,
            )

        if not acquired:
            logger.info(f"Scheduler tick skipped: dispatch lease currently held for key '{scheduler_key}' ({reason})")
            duration_ms = (time.monotonic() - start_mono) * 1000.0
            end_iso = (now_dt or self.clock()).isoformat()

            # Under ACQUIRED_DISPATCH_ONLY: do NOT record in scheduler_runs
            return SchedulerTickResult(
                scheduler_run_id="",
                scheduler_key=scheduler_key,
                status="SKIPPED_LEASE_HELD",
                started_at=now_iso,
                completed_at=end_iso,
                duration_ms=duration_ms,
                recovered_runs_count=recovered_runs,
                error_code="DISPATCH_LEASE_HELD",
                error_message="Dispatch lease currently held by active scheduler",
            )

        # 5. Lease Acquired: Create RUNNING record and setup Heartbeat
        try:
            self.scheduler_repo.create_run(run_id, scheduler_key, now_iso, status="RUNNING")
        except Exception as create_ex:
            safe_create_ex = sanitize_error_message(create_ex)
            logger.error(f"Failed to create scheduler_run record: {safe_create_ex}")
            try:
                self.scheduler_repo.release_dispatch_lease(
                    scheduler_key=scheduler_key,
                    lease_token=lease_token,
                    status="FAILED",
                    now_dt=now,
                )
            except Exception:
                pass
            duration_ms = (time.monotonic() - start_mono) * 1000.0
            end_iso = (now_dt or self.clock()).isoformat()
            return SchedulerTickResult(
                scheduler_run_id=run_id,
                scheduler_key=scheduler_key,
                status="FAILED",
                started_at=now_iso,
                completed_at=end_iso,
                duration_ms=duration_ms,
                error_code="AUDIT_CREATION_FAILED",
                error_message=safe_create_ex,
            )

        db_factory = None
        db_url = getattr(self.settings, "database_url", "")
        if not db_url or db_url == ":memory:" or db_url.endswith(":memory:"):
            db_inst = getattr(self.scheduler_repo, "db", None)
            if db_inst and hasattr(db_inst, "_db_path") and db_inst._db_path not in (":memory:", ""):
                db_url = db_inst._db_path

        if db_url and not db_url.endswith(":memory:") and db_url != ":memory:":
            db_factory = lambda: create_database_connection(db_url)

        # Effective clock for heartbeat: if now_dt was provided, anchor to now_dt
        heartbeat_clock = (lambda: now) if now_dt is not None else self.clock
        heartbeat = SchedulerHeartbeat(
            scheduler_repo=self.scheduler_repo,
            scheduler_key=scheduler_key,
            lease_token=lease_token,
            lease_duration_seconds=self.settings.scheduler_lease_seconds,
            renew_before_seconds=self.settings.scheduler_renew_before_seconds,
            start_now_dt=now,
            clock=heartbeat_clock,
            db_factory=db_factory,
        )
        self.last_heartbeat = heartbeat

        # 6. Execute MonitoringWorker.run() within autonomous heartbeat context
        worker_result: Optional[MonitoringWorkerRunResult] = None
        fatal_error: Optional[Exception] = None

        try:
            with heartbeat:
                worker_result = self.worker.run(now_dt=now, should_stop=heartbeat.should_stop_callback)
        except Exception as ex:
            fatal_error = ex
            logger.critical(f"Fatal worker infrastructure failure during scheduler dispatch: {sanitize_error_message(ex)}")

        end_time = now_dt or self.clock()
        end_iso = end_time.isoformat()
        duration_ms = (time.monotonic() - start_mono) * 1000.0

        # 7. Evaluate Execution Outcome
        if fatal_error:
            status = "FAILED"
            error_code = "WORKER_FATAL_ERROR"
            error_message = sanitize_error_message(fatal_error)
            w_run_id = None
            w_stopped = "FATAL_ERROR"
            attempted = claimed = success = failure = backpressure = 0
        elif heartbeat.ownership_lost:
            status = "OWNERSHIP_LOST"
            error_code = "OWNERSHIP_LOST"
            error_message = "Scheduler lost lease ownership during worker execution"
            w_run_id = worker_result.worker_run_id if worker_result else None
            w_stopped = worker_result.stopped_reason if worker_result else "OWNERSHIP_LOST"
            attempted = worker_result.items_attempted if worker_result else 0
            claimed = worker_result.items_claimed if worker_result else 0
            success = worker_result.success_count if worker_result else 0
            failure = worker_result.failed_count if worker_result else 0
            backpressure = worker_result.backpressure_count if worker_result else 0
        else:
            status = "COMPLETED"
            error_code = None
            error_message = None
            w_run_id = worker_result.worker_run_id
            w_stopped = worker_result.stopped_reason
            attempted = worker_result.items_attempted
            claimed = worker_result.items_claimed
            success = worker_result.success_count
            failure = worker_result.failed_count
            backpressure = worker_result.backpressure_count

        # 8. Finalize Scheduler Run Record
        try:
            self.scheduler_repo.complete_run(
                id=run_id,
                completed_at=end_iso,
                status=status,
                worker_run_id=w_run_id,
                worker_stopped_reason=w_stopped,
                items_attempted=attempted,
                items_claimed=claimed,
                success_count=success,
                failure_count=failure,
                backpressure_count=backpressure,
                error_code=error_code,
                error_message=error_message,
            )
        except Exception as ex:
            logger.error(f"Failed to finalize scheduler run record {run_id[:8]}: {ex}")

        # 9. Release Lease if Still Owned
        try:
            self.scheduler_repo.release_dispatch_lease(
                scheduler_key=scheduler_key,
                lease_token=lease_token,
                run_id=run_id,
                status=status,
                worker_run_id=w_run_id,
                now_dt=end_time,
            )
        except Exception as rel_ex:
            logger.warning(f"Error releasing scheduler dispatch lease: {rel_ex}")

        logger.info(
            f"Production scheduler tick {status} (run_id={run_id[:8]}, worker={w_run_id[:8] if w_run_id else 'none'}, "
            f"items_claimed={claimed}, success={success}, duration={duration_ms:.2f}ms)"
        )

        return SchedulerTickResult(
            scheduler_run_id=run_id,
            scheduler_key=scheduler_key,
            status=status,
            started_at=now_iso,
            completed_at=end_iso,
            duration_ms=duration_ms,
            worker_run_id=w_run_id,
            worker_stopped_reason=w_stopped,
            items_attempted=attempted,
            items_claimed=claimed,
            success_count=success,
            failure_count=failure,
            backpressure_count=backpressure,
            recovered_runs_count=recovered_runs,
            error_code=error_code,
            error_message=error_message,
        )

    def dry_run(self, now_dt: Optional[datetime] = None) -> Dict[str, Any]:
        """Perform read-only scheduling decision inspection without acquiring leases or mutating DB."""
        now = now_dt or self.clock()
        now_iso = now.isoformat()
        readiness = RuntimeReadinessCheck.check(self.settings, db=self.scheduler_repo.db)

        current_lease = None
        if readiness.tables_present:
            try:
                current_lease = self.scheduler_repo.get_dispatch_state(self.settings.scheduler_key)
            except Exception:
                current_lease = None

        lease_active = False
        if current_lease and current_lease.get("lease_expires_at"):
            lease_active = current_lease["lease_expires_at"] > now_iso

        due_count = 0
        if self.schedule_repo and hasattr(self.schedule_repo, "list_due_system"):
            try:
                candidates = self.schedule_repo.list_due_system(now_iso=now_iso, limit=self.settings.worker_max_items)
                due_count = len(candidates)
            except Exception:
                due_count = 0

        would_dispatch = bool(
            self.settings.production_scheduler_enabled
            and readiness.status in (ReadinessStatus.READY, ReadinessStatus.DEGRADED)
            and not lease_active
        )

        return {
            "mode": "DRY_RUN",
            "scheduler_key": self.settings.scheduler_key,
            "production_scheduler_enabled": self.settings.production_scheduler_enabled,
            "readiness_status": readiness.status.value,
            "lease_held": lease_active,
            "lease_currently_active": lease_active,
            "lease_expires_at": current_lease.get("lease_expires_at") if current_lease else None,
            "current_run_id": current_lease.get("current_run_id") if current_lease else None,
            "due_items_count": due_count,
            "would_dispatch": would_dispatch,
            "mutations_count": 0,
        }

    def check(self) -> Dict[str, Any]:
        """Validate scheduler configuration, schema, database readiness without mutations."""
        readiness = RuntimeReadinessCheck.check(self.settings, db=self.scheduler_repo.db)
        state = None
        if readiness.tables_present:
            try:
                state = self.scheduler_repo.get_dispatch_state(self.settings.scheduler_key)
            except Exception:
                state = None

        return {
            "environment": self.settings.environment.value,
            "database_url": self.settings.mask_database_url(),
            "schema_version": readiness.schema_version,
            "expected_schema_version": readiness.expected_schema_version,
            "scheduler_enabled": self.settings.production_scheduler_enabled,
            "scheduler_key": self.settings.scheduler_key,
            "scheduler_lease_seconds": self.settings.scheduler_lease_seconds,
            "scheduler_renew_before_seconds": self.settings.scheduler_renew_before_seconds,
            "readiness_status": readiness.status.value,
            "database_connected": readiness.database_connected,
            "tables_present": readiness.tables_present,
            "current_lease_state": {
                "lease_held": bool(state and state.get("lease_expires_at")),
                "last_status": state.get("last_status") if state else None,
                "last_started_at": state.get("last_started_at") if state else None,
                "last_completed_at": state.get("last_completed_at") if state else None,
            }
            if state
            else None,
            "warnings": readiness.warnings,
            "errors": readiness.errors,
            "mutations_count": 0,
        }
