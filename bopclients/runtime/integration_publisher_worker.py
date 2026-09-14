"""Run-once integration publisher worker for batch outbox routing and transport delivery."""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time
from typing import Dict, Any, Optional
import uuid

from bopclients.application.integration_dispatcher import IntegrationOutboxDispatcher
from bopclients.runtime.settings import RuntimeSettings

logger = logging.getLogger("bopclients.runtime.integration_publisher")


@dataclass
class IntegrationPublisherRunResult:
    """Outcome summary for a run-once publisher execution."""

    worker_id: str
    claim_token: str
    started_at: str
    finished_at: str
    duration_seconds: float
    routing_scanned: int
    deliveries_created: int
    unrouted_events: int
    deliveries_claimed: int
    delivered: int
    retried: int
    dead_letter: int
    events_completed: int

    @property
    def worker_token(self) -> str:
        """Backward-compatible alias for worker_id."""
        return self.worker_id

    def safe_summary(self) -> Dict[str, Any]:
        """Return safe dictionary summary."""
        return {
            "worker_id": self.worker_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "routing_scanned": self.routing_scanned,
            "deliveries_created": self.deliveries_created,
            "unrouted_events": self.unrouted_events,
            "deliveries_claimed": self.deliveries_claimed,
            "delivered": self.delivered,
            "retried": self.retried,
            "dead_letter": self.dead_letter,
            "events_completed": self.events_completed,
        }


class IntegrationPublisherWorker:
    """Worker executing one run-once sweep of outbox routing and delivery dispatch."""

    def __init__(
        self,
        dispatcher: IntegrationOutboxDispatcher,
        settings: RuntimeSettings,
    ):
        self.dispatcher = dispatcher
        self.settings = settings

    def run_once(
        self,
        worker_id: Optional[str] = None,
        worker_token: Optional[str] = None,
        batch_size: Optional[int] = None,
        bop_organization_id: Optional[str] = None,
    ) -> IntegrationPublisherRunResult:
        """Execute one bounded run-once batch cycle.

        1. Route pending outbox events into deliveries.
        2. Claim due deliveries with an unpredictable internal UUID claim_token and execute transport dispatches.
        3. Return structured metrics.
        """
        # Diagnostic instance label
        inst_id = worker_id or worker_token or f"worker-{uuid.uuid4().hex[:8]}"
        # Internal unpredictable claim lease token
        claim_token = str(uuid.uuid4())
        batch = batch_size or self.settings.integration_batch_size
        lease_sec = self.settings.integration_claim_lease_seconds
        timeout_sec = self.settings.integration_http_read_timeout

        start_time = time.monotonic()
        start_iso = datetime.now(timezone.utc).isoformat()

        logger.info(f"Starting integration publisher run_once (worker_id={inst_id}, batch={batch})")

        # Phase 1: Route pending outbox events
        route_stats = self.dispatcher.route_pending_outbox_events(
            limit=batch,
            bop_organization_id=bop_organization_id,
        )

        # Phase 2: Claim and dispatch due deliveries with unpredictable internal claim_token
        dispatch_stats = self.dispatcher.dispatch_batch(
            worker_token=claim_token,
            batch_size=batch,
            lease_seconds=lease_sec,
            timeout_seconds=timeout_sec,
            bop_organization_id=bop_organization_id,
        )

        end_time = time.monotonic()
        finish_iso = datetime.now(timezone.utc).isoformat()
        duration = round(end_time - start_time, 4)

        result = IntegrationPublisherRunResult(
            worker_id=inst_id,
            claim_token=claim_token,
            started_at=start_iso,
            finished_at=finish_iso,
            duration_seconds=duration,
            routing_scanned=route_stats.get("pending_scanned", 0),
            deliveries_created=route_stats.get("deliveries_created", 0),
            unrouted_events=route_stats.get("unrouted_events", 0),
            deliveries_claimed=dispatch_stats.get("deliveries_claimed", 0),
            delivered=dispatch_stats.get("delivered", 0),
            retried=dispatch_stats.get("retried", 0),
            dead_letter=dispatch_stats.get("dead_letter", 0),
            events_completed=dispatch_stats.get("events_completed", 0),
        )

        logger.info(
            f"Integration publisher run_once completed in {duration}s: "
            f"claimed={result.deliveries_claimed}, delivered={result.delivered}, "
            f"retried={result.retried}, dead_letter={result.dead_letter}, "
            f"events_completed={result.events_completed}"
        )

        return result

    def dry_run(
        self,
        batch_size: Optional[int] = None,
        bop_organization_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Perform non-mutating preview of outbox events and due deliveries without claiming or network calls."""
        batch = batch_size or self.settings.integration_batch_size
        pending = self.dispatcher.outbox_repo.list_pending(limit=batch, bop_organization_id=bop_organization_id)

        # Non-mutating inspection of due deliveries
        p = self.dispatcher.delivery_repo._placeholder()
        now_iso = datetime.now(timezone.utc).isoformat()
        tenant_filter = f"AND bop_organization_id = {p}" if bop_organization_id else ""
        sql = f"""
            SELECT count(*) as cnt FROM bop_integration_deliveries
            WHERE (
                (status IN ('PENDING', 'RETRY_PENDING') AND next_attempt_at <= {p} AND (claim_expires_at IS NULL OR claim_expires_at <= {p}))
                OR (status = 'CLAIMED' AND claim_expires_at IS NOT NULL AND claim_expires_at <= {p})
            ) {tenant_filter}
        """
        params = (now_iso, now_iso, now_iso, bop_organization_id) if bop_organization_id else (now_iso, now_iso, now_iso)
        rows = self.dispatcher.delivery_repo.db.fetch_dicts(sql, params)
        due_count = rows[0]["cnt"] if rows else 0

        return {
            "dry_run": True,
            "mutations_count": 0,
            "external_calls": 0,
            "pending_outbox_events": len(pending),
            "due_deliveries": due_count,
            "publisher_enabled": self.settings.integration_publisher_enabled,
            "allow_insecure_http": self.settings.integration_allow_insecure_http,
        }

    def check(self) -> Dict[str, Any]:
        """Check status of integration dispatcher tables, schema version, and readiness."""
        db = self.dispatcher.delivery_repo.db
        from bopclients.runtime.readiness import RuntimeReadinessCheck
        readiness = RuntimeReadinessCheck.check(self.settings, db=db)

        return {
            "check": True,
            "mutations_count": 0,
            "external_calls": 0,
            "schema_version": readiness.schema_version,
            "readiness_status": readiness.status.value,
            "tables_present": readiness.tables_present,
            "publisher_enabled": self.settings.integration_publisher_enabled,
            "allow_insecure_http": self.settings.integration_allow_insecure_http,
        }
