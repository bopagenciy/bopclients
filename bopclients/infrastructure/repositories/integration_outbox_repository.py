"""Database repository for tenant-safe integration outbox persistence."""

from datetime import datetime, timezone, timedelta
from typing import List, Optional, Any
import uuid

from bopclients.domain.integration.app_id import LOCAL_APPLICATION_ID
from bopclients.domain.integration.events import BopIntegrationEvent
from bopclients.domain.integration.exceptions import (
    DuplicateIntegrationEvent,
    CrossTenantIntegrationEvent,
    UnknownLocalTenantIntegrationError,
)
from bopclients.domain.integration.outbox import OutboxRecord, OutboxStatus
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class IntegrationOutboxRepository(BaseTenantRepository):
    """Repository managing tenant-isolated outbox event persistence and publication lifecycle."""

    def __init__(self, db: Any, org_repo: Optional[Any] = None):
        super().__init__(db)
        self.org_repo = org_repo


    @staticmethod
    def _sanitize_error_code(code: Optional[str], max_length: int = 50) -> Optional[str]:
        if not code:
            return None
        clean = str(code).strip()
        return clean[:max_length] if len(clean) > max_length else clean

    @staticmethod
    def _sanitize_error_message(msg: Optional[str], max_length: int = 500) -> Optional[str]:
        if not msg:
            return None
        clean = str(msg).strip()
        return clean[:max_length] if len(clean) > max_length else clean

    @classmethod
    def _row_to_record(cls, r: dict) -> OutboxRecord:
        return OutboxRecord(
            id=r["id"],
            event_id=r["event_id"],
            bop_organization_id=r["bop_organization_id"],
            event_type=r["event_type"],
            event_version=int(r["event_version"]),
            producer_app=r["producer_app"],
            subject_application_id=r["subject_application_id"],
            subject_entity_type=r["subject_entity_type"],
            subject_entity_id=r["subject_entity_id"],
            envelope_json=r["envelope_json"],
            status=r["status"],
            attempt_count=int(r["attempt_count"]),
            available_at=r["available_at"],
            created_at=r["created_at"],
            published_at=r.get("published_at"),
            last_error_code=r.get("last_error_code"),
            last_error_message=r.get("last_error_message"),
        )

    def append(
        self,
        event: BopIntegrationEvent,
        available_at: Optional[datetime] = None,
        commit: bool = True,
        allow_existing: bool = False,
    ) -> OutboxRecord:
        """Atomically append an integration event into the outbox table.

        Args:
            event: Canonical BopIntegrationEvent to store.
            available_at: Optional earliest delivery timestamp (defaults to occurred_at/now).
            commit: Whether to commit transaction immediately (delegated if caller is in an active transaction).
            allow_existing: If True, returns existing record instead of raising DuplicateIntegrationEvent.

        Returns:
            Stored or existing OutboxRecord.
        """
        # Validate event envelope and cross-tenant invariants
        event.validate()

        # Invariant: local outbound event produced by bopclients must belong to an existing local organization
        if event.producer_app == LOCAL_APPLICATION_ID:
            tenant_exists = False
            if self.org_repo is not None and hasattr(self.org_repo, "get_by_bop_organization_id"):
                tenant_exists = (self.org_repo.get_by_bop_organization_id(event.bop_organization_id) is not None)
            else:
                p = self._placeholder()
                check_sql = f"SELECT 1 FROM organizations WHERE bop_organization_id = {p} LIMIT 1"
                rows = self.db.fetch_dicts(check_sql, (event.bop_organization_id,))
                tenant_exists = bool(rows)
            if not tenant_exists:
                raise UnknownLocalTenantIntegrationError(
                    f"Local outbound event for producer '{LOCAL_APPLICATION_ID}' rejected: "
                    f"tenant '{event.bop_organization_id}' does not exist in local organizations"
                )

        existing = self.get_by_event_id(event.event_id)
        if existing:
            if allow_existing:
                return existing
            raise DuplicateIntegrationEvent(f"Outbox event with event_id '{event.event_id}' already exists")

        rec_id = str(uuid.uuid4())
        avail_dt = available_at or datetime.now(timezone.utc)
        avail_iso = avail_dt.isoformat()
        now_iso = datetime.now(timezone.utc).isoformat()
        envelope_json = event.to_json()

        p = self._placeholder()
        sql = f"""
            INSERT INTO bop_integration_outbox (
                id, event_id, bop_organization_id, event_type, event_version,
                producer_app, subject_bop_org_id, subject_application_id, subject_entity_type, subject_entity_id,
                correlation_id, causation_id, envelope_json, status, attempt_count, available_at, created_at
            ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        try:
            self.db.execute(
                sql,
                (
                    rec_id,
                    event.event_id,
                    event.bop_organization_id,
                    event.event_type,
                    event.event_version,
                    event.producer_app,
                    event.subject.bop_organization_id,
                    event.subject.application_id,
                    event.subject.entity_type,
                    event.subject.entity_id,
                    event.correlation_id,
                    event.causation_id,
                    envelope_json,
                    OutboxStatus.PENDING.value,
                    0,
                    avail_iso,
                    now_iso,
                ),
            )
            if commit:
                self._commit_if_not_in_tx()
        except Exception as e:
            # Handle unique constraint collision in concurrent scenarios
            err_str = str(e).lower()
            if "unique" in err_str or "duplicate" in err_str:
                if allow_existing:
                    ex = self.get_by_event_id(event.event_id)
                    if ex:
                        return ex
                raise DuplicateIntegrationEvent(f"Outbox event with event_id '{event.event_id}' already exists: {e}")
            raise

        return OutboxRecord(
            id=rec_id,
            event_id=event.event_id,
            bop_organization_id=event.bop_organization_id,
            event_type=event.event_type,
            event_version=event.event_version,
            producer_app=event.producer_app,
            subject_application_id=event.subject.application_id,
            subject_entity_type=event.subject.entity_type,
            subject_entity_id=event.subject.entity_id,
            envelope_json=envelope_json,
            status=OutboxStatus.PENDING.value,
            attempt_count=0,
            available_at=avail_iso,
            created_at=now_iso,
        )

    def get_by_event_id(
        self,
        event_id: str,
        bop_organization_id: Optional[str] = None,
    ) -> Optional[OutboxRecord]:
        """Fetch outbox record by event UUID with optional tenant boundary check."""
        p = self._placeholder()
        if bop_organization_id:
            sql = f"SELECT * FROM bop_integration_outbox WHERE event_id = {p} AND bop_organization_id = {p}"
            rows = self.db.fetch_dicts(sql, (event_id, bop_organization_id))
        else:
            sql = f"SELECT * FROM bop_integration_outbox WHERE event_id = {p}"
            rows = self.db.fetch_dicts(sql, (event_id,))

        if not rows:
            return None
        return self._row_to_record(rows[0])

    def list_pending(
        self,
        limit: int = 50,
        bop_organization_id: Optional[str] = None,
        before_dt: Optional[datetime] = None,
    ) -> List[OutboxRecord]:
        """List PENDING outbox records available for delivery."""
        p = self._placeholder()
        cutoff = (before_dt or datetime.now(timezone.utc)).isoformat()

        if bop_organization_id:
            sql = f"""
                SELECT * FROM bop_integration_outbox
                WHERE status = 'PENDING' AND available_at <= {p} AND bop_organization_id = {p}
                ORDER BY available_at ASC, created_at ASC
                LIMIT {p}
            """
            rows = self.db.fetch_dicts(sql, (cutoff, bop_organization_id, limit))
        else:
            sql = f"""
                SELECT * FROM bop_integration_outbox
                WHERE status = 'PENDING' AND available_at <= {p}
                ORDER BY available_at ASC, created_at ASC
                LIMIT {p}
            """
            rows = self.db.fetch_dicts(sql, (cutoff, limit))

        return [self._row_to_record(r) for r in rows]

    def enqueue(
        self,
        event: BopIntegrationEvent,
        available_at: Optional[datetime] = None,
        commit: bool = True,
        allow_existing: bool = False,
    ) -> OutboxRecord:
        """Alias for append(). Enqueue an integration event into the outbox table."""
        return self.append(event=event, available_at=available_at, commit=commit, allow_existing=allow_existing)

    def get_event(
        self,
        event_id: str,
        bop_organization_id: Optional[str] = None,
    ) -> Optional[BopIntegrationEvent]:
        """Load and reconstruct original canonical BopIntegrationEvent from stored envelope JSON."""
        record = self.get_by_event_id(event_id, bop_organization_id)
        if not record or not record.envelope_json:
            return None
        return BopIntegrationEvent.from_json(record.envelope_json)

    def mark_published(
        self,
        event_id: str,
        published_at: Optional[datetime] = None,
        bop_organization_id: Optional[str] = None,
        commit: bool = True,
    ) -> bool:
        """Mark outbox record as successfully PUBLISHED.

        Idempotent: returns True if already PUBLISHED.
        """
        existing = self.get_by_event_id(event_id, bop_organization_id)
        if not existing:
            return False
        if existing.status == OutboxStatus.PUBLISHED.value:
            return True

        p = self._placeholder()
        pub_iso = (published_at or datetime.now(timezone.utc)).isoformat()

        if bop_organization_id:
            sql = f"""
                UPDATE bop_integration_outbox
                SET status = 'PUBLISHED',
                    published_at = {p},
                    last_error_code = NULL,
                    last_error_message = NULL
                WHERE event_id = {p} AND bop_organization_id = {p}
            """
            params = (pub_iso, event_id, bop_organization_id)
        else:
            sql = f"""
                UPDATE bop_integration_outbox
                SET status = 'PUBLISHED',
                    published_at = {p},
                    last_error_code = NULL,
                    last_error_message = NULL
                WHERE event_id = {p}
            """
            params = (pub_iso, event_id)

        count = self._execute_rowcount(sql, params)
        if commit:
            self._commit_if_not_in_tx()
        return count > 0

    def mark_failed(
        self,
        event_id: str,
        error_code: str,
        error_message: str,
        retry_delay_seconds: Optional[int] = None,
        bop_organization_id: Optional[str] = None,
        commit: bool = True,
    ) -> bool:
        """Record delivery failure, increment attempts, and update retry or terminal status.

        Guarantees envelope_json remains untouched and byte-identical.
        Guarantees PUBLISHED records cannot regress to FAILED or PENDING.
        """
        p = self._placeholder()
        safe_code = self._sanitize_error_code(error_code)
        safe_msg = self._sanitize_error_message(error_message)

        if retry_delay_seconds is not None and retry_delay_seconds > 0:
            next_avail = (datetime.now(timezone.utc) + timedelta(seconds=retry_delay_seconds)).isoformat()
            new_status = OutboxStatus.PENDING.value
        else:
            next_avail = datetime.now(timezone.utc).isoformat()
            new_status = OutboxStatus.FAILED.value

        if bop_organization_id:
            sql = f"""
                UPDATE bop_integration_outbox
                SET status = {p},
                    attempt_count = attempt_count + 1,
                    available_at = {p},
                    last_error_code = {p},
                    last_error_message = {p}
                WHERE event_id = {p} AND bop_organization_id = {p} AND status != 'PUBLISHED'
            """
            params = (new_status, next_avail, safe_code, safe_msg, event_id, bop_organization_id)
        else:
            sql = f"""
                UPDATE bop_integration_outbox
                SET status = {p},
                    attempt_count = attempt_count + 1,
                    available_at = {p},
                    last_error_code = {p},
                    last_error_message = {p}
                WHERE event_id = {p} AND status != 'PUBLISHED'
            """
            params = (new_status, next_avail, safe_code, safe_msg, event_id)

        count = self._execute_rowcount(sql, params)
        if commit:
            self._commit_if_not_in_tx()
        return count > 0
