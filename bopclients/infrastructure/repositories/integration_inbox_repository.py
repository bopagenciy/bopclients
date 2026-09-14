"""Database repository for tenant-safe integration inbox idempotency."""

from datetime import datetime, timezone
from typing import Optional, Tuple
import uuid

from bopclients.domain.integration.events import BopIntegrationEvent
from bopclients.domain.integration.inbox import InboxRecord, InboxStatus
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class IntegrationInboxRepository(BaseTenantRepository):
    """Repository managing idempotent inbound event receipt and processing state."""

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
    def _row_to_record(cls, r: dict) -> InboxRecord:
        return InboxRecord(
            id=r["id"],
            event_id=r["event_id"],
            producer_app=r["producer_app"],
            bop_organization_id=r["bop_organization_id"],
            event_type=r["event_type"],
            event_version=int(r["event_version"]),
            received_at=r["received_at"],
            envelope_json=r.get("envelope_json"),
            processed_at=r.get("processed_at"),
            status=r["status"],
            last_error_code=r.get("last_error_code") or r.get("error_code"),
            last_error_message=r.get("last_error_message") or r.get("error_message"),
        )

    def register_received(
        self,
        event: BopIntegrationEvent,
        received_at: Optional[datetime] = None,
        commit: bool = True,
    ) -> Tuple[bool, InboxRecord]:
        """Idempotently register an incoming external integration event.

        Args:
            event: Canonical BopIntegrationEvent received from external application.
            received_at: Optional timestamp of receipt (defaults to now).
            commit: Whether to commit transaction immediately.

        Returns:
            Tuple of (is_new: bool, record: InboxRecord).
            If event_id was already recorded:
            - If status == PROCESSED: returns (False, existing_record) without regression.
            - If status == FAILED: returns (False, existing_record) for deterministic retry inspection.
        """
        event.validate()

        existing = self.get_by_event_id(event.event_id)
        if existing:
            return False, existing

        rec_id = str(uuid.uuid4())
        rec_iso = (received_at or datetime.now(timezone.utc)).isoformat()
        envelope_json = event.to_json()
        p = self._placeholder()

        sql = f"""
            INSERT INTO bop_integration_inbox (
                id, event_id, producer_app, bop_organization_id,
                event_type, event_version, envelope_json, received_at, status
            ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        try:
            self.db.execute(
                sql,
                (
                    rec_id,
                    event.event_id,
                    event.producer_app,
                    event.bop_organization_id,
                    event.event_type,
                    event.event_version,
                    envelope_json,
                    rec_iso,
                    InboxStatus.RECEIVED.value,
                ),
            )
            if commit:
                self._commit_if_not_in_tx()
            return True, InboxRecord(
                id=rec_id,
                event_id=event.event_id,
                producer_app=event.producer_app,
                bop_organization_id=event.bop_organization_id,
                event_type=event.event_type,
                event_version=event.event_version,
                received_at=rec_iso,
                envelope_json=envelope_json,
                status=InboxStatus.RECEIVED.value,
            )
        except Exception as e:
            err_str = str(e).lower()
            if "unique" in err_str or "duplicate" in err_str:
                ex = self.get_by_event_id(event.event_id)
                if ex:
                    return False, ex
            raise

    def get_by_event_id(
        self,
        event_id: str,
        bop_organization_id: Optional[str] = None,
    ) -> Optional[InboxRecord]:
        """Fetch inbox record by event UUID with optional tenant boundary check."""
        p = self._placeholder()
        if bop_organization_id:
            sql = f"SELECT * FROM bop_integration_inbox WHERE event_id = {p} AND bop_organization_id = {p}"
            rows = self.db.fetch_dicts(sql, (event_id, bop_organization_id))
        else:
            sql = f"SELECT * FROM bop_integration_inbox WHERE event_id = {p}"
            rows = self.db.fetch_dicts(sql, (event_id,))

        if not rows:
            return None
        return self._row_to_record(rows[0])

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

    def mark_processed(
        self,
        event_id: str,
        processed_at: Optional[datetime] = None,
        bop_organization_id: Optional[str] = None,
        commit: bool = True,
    ) -> bool:
        """Mark inbox record as PROCESSED."""
        p = self._placeholder()
        proc_iso = (processed_at or datetime.now(timezone.utc)).isoformat()

        if bop_organization_id:
            sql = f"""
                UPDATE bop_integration_inbox
                SET status = 'PROCESSED',
                    processed_at = {p},
                    last_error_code = NULL,
                    last_error_message = NULL
                WHERE event_id = {p} AND bop_organization_id = {p}
            """
            params = (proc_iso, event_id, bop_organization_id)
        else:
            sql = f"""
                UPDATE bop_integration_inbox
                SET status = 'PROCESSED',
                    processed_at = {p},
                    last_error_code = NULL,
                    last_error_message = NULL
                WHERE event_id = {p}
            """
            params = (proc_iso, event_id)

        count = self._execute_rowcount(sql, params)
        if commit:
            self._commit_if_not_in_tx()
        return count > 0

    def mark_failed(
        self,
        event_id: str,
        error_code: str,
        error_message: str,
        bop_organization_id: Optional[str] = None,
        commit: bool = True,
    ) -> bool:
        """Mark inbox record as FAILED with bounded error storage.

        Guarantees PROCESSED records cannot regress to FAILED.
        """
        p = self._placeholder()
        safe_code = self._sanitize_error_code(error_code)
        safe_msg = self._sanitize_error_message(error_message)

        if bop_organization_id:
            sql = f"""
                UPDATE bop_integration_inbox
                SET status = 'FAILED',
                    last_error_code = {p},
                    last_error_message = {p}
                WHERE event_id = {p} AND bop_organization_id = {p} AND status != 'PROCESSED'
            """
            params = (safe_code, safe_msg, event_id, bop_organization_id)
        else:
            sql = f"""
                UPDATE bop_integration_inbox
                SET status = 'FAILED',
                    last_error_code = {p},
                    last_error_message = {p}
                WHERE event_id = {p} AND status != 'PROCESSED'
            """
            params = (safe_code, safe_msg, event_id)

        count = self._execute_rowcount(sql, params)
        if commit:
            self._commit_if_not_in_tx()
        return count > 0
