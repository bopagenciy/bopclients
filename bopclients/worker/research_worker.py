"""Durable Research Worker for claiming and executing pending ResearchRuns."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import time
from typing import List, Dict, Any, Optional, Callable
import uuid

from bopclients.application.prospect_research_service import ProspectResearchService
from bopclients.application.research_dto import ProspectResearchResult
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.application.research_run_recovery_service import ResearchRunRecoveryService

logger = logging.getLogger("bopclients.worker.research_worker")


@dataclass
class ResearchWorkerItemResult:
    """Outcome summary for a single ResearchRun evaluation."""

    run_id: str
    organization_id: str
    prospect_id: Optional[str]
    status: str  # "completed", "failed", "skipped"
    error_message: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class ResearchWorkerRunResult:
    """Outcome summary for a research worker run_once batch execution."""

    worker_id: str
    started_at: str
    finished_at: str
    duration_seconds: float
    scanned: int
    claimed: int
    completed: int
    failed: int
    skipped: int
    items: List[ResearchWorkerItemResult] = field(default_factory=list)

    def safe_summary(self) -> Dict[str, Any]:
        return {
            "worker_id": self.worker_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "scanned": self.scanned,
            "claimed": self.claimed,
            "completed": self.completed,
            "failed": self.failed,
            "skipped": self.skipped,
            "items_count": len(self.items),
        }


class ResearchWorker:
    """Durable worker that claims pending ResearchRuns and executes prospect research orchestrator."""

    def __init__(
        self,
        research_run_repo: ResearchRunRepository,
        research_service: ProspectResearchService,
        recovery_service: Optional[ResearchRunRecoveryService] = None,
    ):
        self.research_run_repo = research_run_repo
        self.research_service = research_service
        self.recovery_service = recovery_service

    def claim_and_execute_run(
        self,
        org_id: str,
        run_id: str,
        worker_id: Optional[str] = None,
        provider: str = "deterministic",
    ) -> Optional[ProspectResearchResult]:
        """Atomically claim a specific pending ResearchRun and execute it."""
        attempt_id = str(uuid.uuid4())
        start_iso = datetime.now(timezone.utc).isoformat()
        t0 = time.monotonic()

        # Atomic claim predicate: status must be 'pending'
        claimed = self.research_run_repo.claim_run(
            org_id=org_id,
            run_id=run_id,
            execution_attempt_id=attempt_id,
            started_at_iso=start_iso,
            worker_id=worker_id,
        )
        if not claimed:
            logger.info(f"ResearchRun '{run_id}' could not be claimed (already running, completed, or not found).")
            return None

        run = claimed
        if not run or not run.prospect_id:
            logger.error(f"Claimed run '{run_id}' has missing prospect_id or was not found.")
            self.research_run_repo.update_status(
                org_id=org_id,
                run_id=run_id,
                status="failed",
                completed_at=datetime.now(timezone.utc).isoformat(),
                error_message="Invalid run: missing prospect_id",
            )
            return None

        try:
            logger.info(f"Executing prospect research for prospect '{run.prospect_id}' (run_id='{run_id}', provider='{provider}')")
            result = self.research_service.research_prospect(
                org_id=org_id,
                prospect_id=run.prospect_id,
                campaign_id=run.campaign_id,
                run_id=run.id,
                provider=provider,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            logger.info(f"ResearchRun '{run_id}' completed successfully in {elapsed_ms:.1f}ms.")
            return result
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000.0
            err_msg = str(exc)
            logger.error(f"ResearchRun '{run_id}' failed after {elapsed_ms:.1f}ms: {err_msg}", exc_info=True)
            self.research_run_repo.update_status(
                org_id=org_id,
                run_id=run_id,
                status="failed",
                completed_at=datetime.now(timezone.utc).isoformat(),
                error_message=err_msg,
                execution_attempt_id=run.execution_attempt_id,
                expected_status="running",
            )
            raise

    def run_once(
        self,
        batch_size: int = 10,
        org_id: Optional[str] = None,
        worker_id: Optional[str] = None,
        provider: str = "deterministic",
        recover_stale: bool = True,
    ) -> ResearchWorkerRunResult:
        """Run one bounded pass claiming and executing pending ResearchRuns."""
        w_id = worker_id or f"research-worker-{uuid.uuid4().hex[:8]}"
        t_start = time.monotonic()
        start_iso = datetime.now(timezone.utc).isoformat()

        # 1. Recovery pass for stale runs
        if recover_stale and self.recovery_service:
            try:
                self.recovery_service.reconcile_stale_runs()
            except Exception as ex:
                logger.warning(f"Error during research worker startup recovery pass: {ex}")

        # 2. Fetch pending candidate runs
        candidates = self.research_run_repo.list_pending_runs(org_id=org_id, limit=batch_size)
        scanned = len(candidates)
        claimed_count = 0
        completed_count = 0
        failed_count = 0
        skipped_count = 0
        items: List[ResearchWorkerItemResult] = []

        for candidate in candidates:
            t_item = time.monotonic()
            try:
                result = self.claim_and_execute_run(
                    org_id=candidate.organization_id,
                    run_id=candidate.id,
                    worker_id=w_id,
                    provider=provider,
                )
            except Exception:
                result = None
            item_duration = (time.monotonic() - t_item) * 1000.0

            if result is None:
                # Check status after attempt
                updated = self.research_run_repo.get_by_id(candidate.organization_id, candidate.id)
                if updated and updated.status == "failed":
                    claimed_count += 1
                    failed_count += 1
                    items.append(
                        ResearchWorkerItemResult(
                            run_id=candidate.id,
                            organization_id=candidate.organization_id,
                            prospect_id=candidate.prospect_id,
                            status="failed",
                            error_message=updated.error_message,
                            duration_ms=item_duration,
                        )
                    )
                else:
                    skipped_count += 1
                    items.append(
                        ResearchWorkerItemResult(
                            run_id=candidate.id,
                            organization_id=candidate.organization_id,
                            prospect_id=candidate.prospect_id,
                            status="skipped",
                            error_message="Could not claim run (concurrency conflict or already active)",
                            duration_ms=item_duration,
                        )
                    )
            else:
                claimed_count += 1
                completed_count += 1
                items.append(
                    ResearchWorkerItemResult(
                        run_id=candidate.id,
                        organization_id=candidate.organization_id,
                        prospect_id=candidate.prospect_id,
                        status="completed",
                        duration_ms=item_duration,
                    )
                )

        total_duration = time.monotonic() - t_start
        finish_iso = datetime.now(timezone.utc).isoformat()

        return ResearchWorkerRunResult(
            worker_id=w_id,
            started_at=start_iso,
            finished_at=finish_iso,
            duration_seconds=total_duration,
            scanned=scanned,
            claimed=claimed_count,
            completed=completed_count,
            failed=failed_count,
            skipped=skipped_count,
            items=items,
        )

    def run_continuous(
        self,
        batch_size: int = 10,
        poll_interval: float = 2.0,
        org_id: Optional[str] = None,
        worker_id: Optional[str] = None,
        provider: str = "deterministic",
        should_stop: Optional[Callable[[], bool]] = None,
        max_iterations: Optional[int] = None,
    ) -> int:
        """Run persistent polling loop processing pending ResearchRuns until stopped.

        Args:
            batch_size: Maximum pending research runs to claim per sweep.
            poll_interval: Sleep seconds when idle (no pending runs found).
            org_id: Optional tenant filter.
            worker_id: Optional diagnostic worker identifier.
            provider: Research provider name (default: deterministic).
            should_stop: Optional callable returning True when loop should terminate.
            max_iterations: Optional loop iteration cap (primarily for test harnesses).

        Returns:
            Total completed runs across all iterations.
        """
        iteration = 0
        total_completed = 0
        logger.info(
            f"Starting persistent research worker loop (poll_interval={poll_interval}s, batch_size={batch_size})"
        )
        while True:
            if should_stop and should_stop():
                logger.info("Stop condition met, exiting continuous research worker loop.")
                break
            if max_iterations is not None and iteration >= max_iterations:
                break

            result = self.run_once(
                batch_size=batch_size,
                org_id=org_id,
                worker_id=worker_id,
                provider=provider,
                recover_stale=(iteration == 0 or iteration % 10 == 0),
            )
            total_completed += result.completed
            iteration += 1

            if result.scanned == 0 and (max_iterations is None or iteration < max_iterations):
                time.sleep(poll_interval)

        return total_completed
