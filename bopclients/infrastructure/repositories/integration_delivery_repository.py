"""Database repository for tenant-safe integration deliveries and delivery attempts."""

from datetime import datetime, timezone, timedelta
from typing import List, Optional, Any, Tuple
import uuid

from bopclients.domain.integration.delivery import (
    DeliveryRecord,
    DeliveryAttemptRecord,
    DeliveryStatus,
    TransportResultStatus,
)
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository
from bopclients.runtime.settings import sanitize_error_message


class IntegrationDeliveryRepository(BaseTenantRepository):
    """Repository managing destination deliveries, distributed atomic claims, and attempt logs."""

    @staticmethod
    def _sanitize_error_code(code: Optional[str], max_length: int = 50) -> Optional[str]:
        if not code:
            return None
        clean = str(code).strip()
        return clean[:max_length] if len(clean) > max_length else clean

    @classmethod
    def _row_to_delivery(cls, r: dict) -> DeliveryRecord:
        return DeliveryRecord(
            id=r["id"],
            event_id=r["event_id"],
            destination_id=r["destination_id"],
            bop_organization_id=r["bop_organization_id"],
            status=r["status"],
            attempt_count=int(r["attempt_count"]),
            max_attempts=int(r["max_attempts"]),
            next_attempt_at=r["next_attempt_at"],
            claim_token=r.get("claim_token"),
            claim_expires_at=r.get("claim_expires_at"),
            delivered_at=r.get("delivered_at"),
            last_error_code=r.get("last_error_code"),
            last_error_message=r.get("last_error_message"),
            created_at=r.get("created_at", ""),
            updated_at=r.get("updated_at", ""),
        )

    @classmethod
    def _row_to_attempt(cls, r: dict) -> DeliveryAttemptRecord:
        return DeliveryAttemptRecord(
            id=r["id"],
            delivery_id=r["delivery_id"],
            attempt_number=int(r["attempt_number"]),
            started_at=r["started_at"],
            finished_at=r["finished_at"],
            status=r["status"],
            status_code=int(r["status_code"]) if r.get("status_code") is not None else None,
            error_code=r.get("error_code"),
            error_message=r.get("error_message"),
            response_body_sample=r.get("response_body_sample"),
        )

    # ---------------- Delivery Creation & Lookup ----------------

    def create_delivery(
        self,
        event_id: str,
        destination_id: str,
        bop_organization_id: str,
        max_attempts: int = 5,
        available_at: Optional[datetime] = None,
        delivery_id: Optional[str] = None,
        commit: bool = True,
    ) -> Optional[DeliveryRecord]:
        """Create a delivery row for (event_id, destination_id) idempotently.

        If already exists, returns the existing record.
        """
        self._validate_tenant(bop_organization_id)
        existing = self.get_by_event_and_destination(event_id, destination_id)
        if existing:
            return existing

        p = self._placeholder()
        d_id = delivery_id or str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        next_attempt = (available_at or datetime.now(timezone.utc)).isoformat()

        sql = f"""
            INSERT INTO bop_integration_deliveries (
                id, event_id, destination_id, bop_organization_id, status,
                attempt_count, max_attempts, next_attempt_at,
                created_at, updated_at
            ) VALUES ({p}, {p}, {p}, {p}, 'PENDING', 0, {p}, {p}, {p}, {p})
        """
        try:
            self.db.execute(
                sql,
                (
                    d_id,
                    event_id,
                    destination_id,
                    bop_organization_id,
                    max_attempts,
                    next_attempt,
                    now_iso,
                    now_iso,
                ),
            )
            if commit:
                self._commit_if_not_in_tx()
            return self.get_by_id(d_id)
        except Exception:
            # Handle possible race condition on UNIQUE(event_id, destination_id)
            return self.get_by_event_and_destination(event_id, destination_id)

    def get_by_id(self, delivery_id: str) -> Optional[DeliveryRecord]:
        """Fetch delivery by ID."""
        p = self._placeholder()
        sql = f"SELECT * FROM bop_integration_deliveries WHERE id = {p}"
        rows = self.db.fetch_dicts(sql, (delivery_id,))
        if not rows:
            return None
        return self._row_to_delivery(rows[0])

    def get_by_event_and_destination(self, event_id: str, destination_id: str) -> Optional[DeliveryRecord]:
        """Fetch delivery by unique event and destination pair."""
        p = self._placeholder()
        sql = f"SELECT * FROM bop_integration_deliveries WHERE event_id = {p} AND destination_id = {p}"
        rows = self.db.fetch_dicts(sql, (event_id, destination_id))
        if not rows:
            return None
        return self._row_to_delivery(rows[0])

    def list_by_event(self, event_id: str) -> List[DeliveryRecord]:
        """List all delivery records associated with an event."""
        p = self._placeholder()
        sql = f"SELECT * FROM bop_integration_deliveries WHERE event_id = {p} ORDER BY created_at ASC"
        rows = self.db.fetch_dicts(sql, (event_id,))
        return [self._row_to_delivery(r) for r in rows]

    # ---------------- Atomic Claiming ----------------

    def claim_due_deliveries(
        self,
        worker_token: str,
        lease_seconds: int = 60,
        batch_size: int = 25,
        bop_organization_id: Optional[str] = None,
        commit: bool = True,
    ) -> List[DeliveryRecord]:
        """Atomically claim due deliveries for processing.

        Recovers expired leases where claim_expires_at < now.
        For PostgreSQL, uses SELECT ... FOR UPDATE SKIP LOCKED inside transaction to prevent worker contention.
        For SQLite, uses atomic UPDATE predicate with timestamp checks.
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        lease_expires_iso = (now + timedelta(seconds=lease_seconds)).isoformat()
        p = self._placeholder()
        is_pg = getattr(self.db, "backend_name", "") == "postgresql"

        claimed_ids: List[str] = []

        if is_pg:
            # PostgreSQL concurrency-safe selection with FOR UPDATE SKIP LOCKED
            tenant_filter = f"AND bop_organization_id = {p}" if bop_organization_id else ""
            select_sql = f"""
                SELECT id FROM bop_integration_deliveries
                WHERE (
                    (status IN ('PENDING', 'RETRY_PENDING') AND next_attempt_at <= {p} AND (claim_expires_at IS NULL OR claim_expires_at <= {p}))
                    OR (status = 'CLAIMED' AND claim_expires_at IS NOT NULL AND claim_expires_at <= {p})
                )
                {tenant_filter}
                ORDER BY next_attempt_at ASC, created_at ASC
                LIMIT {p}
                FOR UPDATE SKIP LOCKED
            """
            params: Tuple[Any, ...]
            if bop_organization_id:
                params = (now_iso, now_iso, now_iso, bop_organization_id, batch_size)
            else:
                params = (now_iso, now_iso, now_iso, batch_size)

            rows = self.db.fetch_dicts(select_sql, params)
            if not rows:
                return []
            candidate_ids = [r["id"] for r in rows]

            # Atomic update on locked candidate rows
            for c_id in candidate_ids:
                upd_sql = f"""
                    UPDATE bop_integration_deliveries
                    SET status = 'CLAIMED',
                        claim_token = {p},
                        claim_expires_at = {p},
                        updated_at = {p}
                    WHERE id = {p}
                """
                self.db.execute(upd_sql, (worker_token, lease_expires_iso, now_iso, c_id))
                claimed_ids.append(c_id)

            if commit:
                self._commit_if_not_in_tx()

        else:
            # SQLite safe claim query: select candidate IDs then atomically update with lease checks
            tenant_filter = f"AND bop_organization_id = {p}" if bop_organization_id else ""
            candidate_sql = f"""
                SELECT id FROM bop_integration_deliveries
                WHERE (
                    (status IN ('PENDING', 'RETRY_PENDING') AND next_attempt_at <= {p} AND (claim_expires_at IS NULL OR claim_expires_at <= {p}))
                    OR (status = 'CLAIMED' AND claim_expires_at IS NOT NULL AND claim_expires_at <= {p})
                )
                {tenant_filter}
                ORDER BY next_attempt_at ASC, created_at ASC
                LIMIT {p}
            """
            params = (now_iso, now_iso, now_iso, bop_organization_id, batch_size) if bop_organization_id else (now_iso, now_iso, now_iso, batch_size)
            rows = self.db.fetch_dicts(candidate_sql, params)

            for r in rows:
                cid = r["id"]
                upd_sql = f"""
                    UPDATE bop_integration_deliveries
                    SET status = 'CLAIMED',
                        claim_token = {p},
                        claim_expires_at = {p},
                        updated_at = {p}
                    WHERE id = {p}
                      AND (
                          (status IN ('PENDING', 'RETRY_PENDING') AND (claim_expires_at IS NULL OR claim_expires_at <= {p}))
                          OR (status = 'CLAIMED' AND claim_expires_at <= {p})
                      )
                """
                cnt = self._execute_rowcount(upd_sql, (worker_token, lease_expires_iso, now_iso, cid, now_iso, now_iso))
                if cnt > 0:
                    claimed_ids.append(cid)

            if commit:
                self._commit_if_not_in_tx()


        if not claimed_ids:
            return []

        # Re-fetch claimed records
        result = []
        for cid in claimed_ids:
            rec = self.get_by_id(cid)
            if rec:
                result.append(rec)
        return result

    # ---------------- Completion & Failure Transitions ----------------

    def mark_delivered(
        self,
        delivery_id: str,
        claim_token: str,
        delivered_at: Optional[datetime] = None,
        commit: bool = True,
    ) -> bool:
        """Mark delivery DELIVERED atomically.

        Guards against stale owner overwrites: requires claim_token match.
        """
        p = self._placeholder()
        now_iso = (delivered_at or datetime.now(timezone.utc)).isoformat()
        sql = f"""
            UPDATE bop_integration_deliveries
            SET status = 'DELIVERED',
                delivered_at = {p},
                claim_token = NULL,
                claim_expires_at = NULL,
                last_error_code = NULL,
                last_error_message = NULL,
                updated_at = {p}
            WHERE id = {p} AND claim_token = {p}
        """
        cnt = self._execute_rowcount(sql, (now_iso, now_iso, delivery_id, claim_token))
        if commit:
            self._commit_if_not_in_tx()
        return cnt > 0


    def mark_attempt_failed(
        self,
        delivery_id: str,
        claim_token: str,
        error_code: str,
        error_message: str,
        is_permanent: bool = False,
        retry_delay_seconds: Optional[int] = None,
        increment_attempts: bool = True,
        commit: bool = True,
    ) -> Tuple[bool, str]:
        """Record delivery failure, increment attempt_count if network attempt was made, and transition to RETRY_PENDING or DEAD_LETTER.

        Returns (success: bool, new_status: str).
        Guards against stale owner overwrites: requires claim_token match.
        """
        rec = self.get_by_id(delivery_id)
        if not rec or rec.claim_token != claim_token:
            return False, rec.status if rec else DeliveryStatus.PENDING.value

        p = self._placeholder()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        new_attempts = (rec.attempt_count + 1) if increment_attempts else rec.attempt_count

        safe_code = self._sanitize_error_code(error_code)
        safe_msg = sanitize_error_message(error_message, max_length=500)

        if is_permanent or new_attempts >= rec.max_attempts:
            new_status = DeliveryStatus.DEAD_LETTER.value
            next_attempt_iso = now_iso
        else:
            new_status = DeliveryStatus.RETRY_PENDING.value
            delay = retry_delay_seconds if retry_delay_seconds is not None else (2 ** max(1, new_attempts) * 10)
            next_attempt_iso = (now + timedelta(seconds=delay)).isoformat()

        sql = f"""
            UPDATE bop_integration_deliveries
            SET status = {p},
                attempt_count = {p},
                next_attempt_at = {p},
                claim_token = NULL,
                claim_expires_at = NULL,
                last_error_code = {p},
                last_error_message = {p},
                updated_at = {p}
            WHERE id = {p} AND claim_token = {p}
        """
        cnt = self._execute_rowcount(
            sql,
            (new_status, new_attempts, next_attempt_iso, safe_code, safe_msg, now_iso, delivery_id, claim_token),
        )
        if commit:
            self._commit_if_not_in_tx()
        return cnt > 0, new_status

    # ---------------- Delivery Attempt Audit Logs ----------------

    def log_attempt(
        self,
        delivery_id: str,
        attempt_number: int,
        started_at: datetime,
        finished_at: datetime,
        status: str,
        status_code: Optional[int] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        response_body_sample: Optional[str] = None,
        commit: bool = True,
    ) -> DeliveryAttemptRecord:
        """Insert an immutable delivery attempt audit row."""
        p = self._placeholder()
        att_id = str(uuid.uuid4())
        safe_code = self._sanitize_error_code(error_code)
        safe_msg = sanitize_error_message(error_message, max_length=500)
        safe_body = response_body_sample[:1000] if response_body_sample else None

        sql = f"""
            INSERT INTO bop_integration_delivery_attempts (
                id, delivery_id, attempt_number, started_at, finished_at,
                status, status_code, error_code, error_message, response_body_sample
            ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        self.db.execute(
            sql,
            (
                att_id,
                delivery_id,
                attempt_number,
                started_at.isoformat(),
                finished_at.isoformat(),
                status,
                status_code,
                safe_code,
                safe_msg,
                safe_body,
            ),
        )
        if commit:
            self._commit_if_not_in_tx()

        return DeliveryAttemptRecord(
            id=att_id,
            delivery_id=delivery_id,
            attempt_number=attempt_number,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            status=status,
            status_code=status_code,
            error_code=safe_code,
            error_message=safe_msg,
            response_body_sample=safe_body,
        )

    def list_attempts(self, delivery_id: str) -> List[DeliveryAttemptRecord]:
        """List all attempt logs for a given delivery."""
        p = self._placeholder()
        sql = f"""
            SELECT * FROM bop_integration_delivery_attempts
            WHERE delivery_id = {p}
            ORDER BY attempt_number ASC
        """
        rows = self.db.fetch_dicts(sql, (delivery_id,))
        return [self._row_to_attempt(r) for r in rows]
