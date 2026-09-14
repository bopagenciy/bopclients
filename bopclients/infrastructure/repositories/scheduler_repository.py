"""SchedulerRepository managing distributed scheduler lease and execution audit history."""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List, Tuple

from bopclients.runtime.settings import sanitize_error_message

logger = logging.getLogger("bopclients.repository.scheduler")


class SchedulerRepository:
    """Repository managing distributed scheduler state and append-only run history."""

    def __init__(self, db: Any):
        self.db = db

    def _placeholder(self) -> str:
        """Return parameter placeholder string for current backend (%s or ?)."""
        if hasattr(self.db, "placeholder"):
            return self.db.placeholder
        return "%s" if getattr(self.db, "backend_name", "") == "postgresql" else "?"

    def _is_postgres(self) -> bool:
        """Check if active connection is PostgreSQL."""
        return getattr(self.db, "backend_name", "") == "postgresql"

    def _execute_rowcount(self, sql: str, params: Optional[Tuple[Any, ...]] = None) -> int:
        """Execute query and return affected rowcount atomically."""
        if hasattr(self.db, "execute_rowcount"):
            return self.db.execute_rowcount(sql, params)
        p = params or ()
        if hasattr(self.db, "_backend") and hasattr(self.db._backend, "_conn"):
            cur = self.db._backend._conn.cursor()
            cur.execute(sql, p)
            return cur.rowcount
        elif hasattr(self.db, "backend") and hasattr(self.db.backend, "_conn"):
            cur = self.db.backend._conn.cursor()
            cur.execute(sql, p)
            return cur.rowcount
        res = self.db.execute(sql, p)
        if hasattr(res, "rowcount"):
            return res.rowcount
        return 1

    def try_acquire_dispatch(
        self,
        scheduler_key: str,
        lease_token: Optional[str] = None,
        lease_duration_seconds: int = 300,
        run_id: Optional[str] = None,
        now_dt: Optional[datetime] = None,
        owner_token: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Atomically attempt to acquire distributed dispatch lease for a scheduler key.

        Returns:
            (True, "ACQUIRED") if lease was acquired.
            (False, "LEASE_HELD") if another dispatcher holds an active lease.
        """
        token = lease_token or owner_token or ""
        now = now_dt or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        expires_iso = (now + timedelta(seconds=lease_duration_seconds)).isoformat()
        p = self._placeholder()
        is_pg = self._is_postgres()

        # 1. Ensure state row exists idempotently
        if is_pg:
            ensure_sql = f"""
                INSERT INTO scheduler_dispatch_state (scheduler_key, updated_at)
                VALUES ({p}, {p})
                ON CONFLICT (scheduler_key) DO NOTHING
            """
        else:
            ensure_sql = f"""
                INSERT OR IGNORE INTO scheduler_dispatch_state (scheduler_key, updated_at)
                VALUES ({p}, {p})
            """
        self.db.execute(ensure_sql, (scheduler_key, now_iso))

        # 2. Lock and inspect state row
        if is_pg:
            lock_sql = f"""
                SELECT scheduler_key, lease_token, lease_expires_at, current_run_id
                FROM scheduler_dispatch_state
                WHERE scheduler_key = {p}
                FOR UPDATE
            """
        else:
            lock_sql = f"""
                SELECT scheduler_key, lease_token, lease_expires_at, current_run_id
                FROM scheduler_dispatch_state
                WHERE scheduler_key = {p}
            """

        rows = self.db.fetch_dicts(lock_sql, (scheduler_key,))
        if not rows:
            self.db.commit()
            return False, "ERROR_NOT_FOUND"

        current_state = rows[0]
        lease_expires_at = current_state.get("lease_expires_at")

        # 3. Evaluate if lease is currently active
        if lease_expires_at and lease_expires_at > now_iso:
            self.db.commit()
            return False, "LEASE_HELD"

        # 4. Acquire lease atomically
        update_sql = f"""
            UPDATE scheduler_dispatch_state
            SET lease_token = {p},
                lease_expires_at = {p},
                current_run_id = {p},
                last_started_at = {p},
                last_status = 'RUNNING',
                updated_at = {p}
            WHERE scheduler_key = {p}
        """
        self.db.execute(update_sql, (token, expires_iso, run_id, now_iso, now_iso, scheduler_key))
        self.db.commit()
        return True, "ACQUIRED"

    def renew_dispatch_lease(
        self,
        scheduler_key: str,
        lease_token: Optional[str] = None,
        lease_duration_seconds: int = 300,
        now_dt: Optional[datetime] = None,
        owner_token: Optional[str] = None,
    ) -> bool:
        """Extend lease duration IF AND ONLY IF lease_token ownership matches."""
        token = lease_token or owner_token
        if not token:
            return False

        now = now_dt or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        new_expires_iso = (now + timedelta(seconds=lease_duration_seconds)).isoformat()
        p = self._placeholder()

        update_sql = f"""
            UPDATE scheduler_dispatch_state
            SET lease_expires_at = {p},
                updated_at = {p}
            WHERE scheduler_key = {p} AND lease_token = {p}
        """
        count = self._execute_rowcount(update_sql, (new_expires_iso, now_iso, scheduler_key, token))
        self.db.commit()
        return count > 0

    def release_dispatch_lease(
        self,
        scheduler_key: str,
        lease_token: Optional[str] = None,
        run_id: Optional[str] = None,
        status: str = "COMPLETED",
        worker_run_id: Optional[str] = None,
        now_dt: Optional[datetime] = None,
        owner_token: Optional[str] = None,
    ) -> bool:
        """Release lease token enforcing lease_token ownership matching."""
        token = lease_token or owner_token
        if not token:
            return False

        now = now_dt or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        p = self._placeholder()

        update_sql = f"""
            UPDATE scheduler_dispatch_state
            SET lease_token = NULL,
                lease_expires_at = NULL,
                current_run_id = NULL,
                last_completed_at = {p},
                last_status = {p},
                last_worker_run_id = {p},
                updated_at = {p}
            WHERE scheduler_key = {p} AND lease_token = {p}
        """
        count = self._execute_rowcount(update_sql, (now_iso, status, worker_run_id, now_iso, scheduler_key, token))
        self.db.commit()
        return count > 0

    def create_run(
        self,
        id: str,
        scheduler_key: str,
        started_at: str,
        status: str = "RUNNING",
    ) -> None:
        """Insert append-only scheduler run audit record."""
        p = self._placeholder()
        insert_sql = f"""
            INSERT INTO scheduler_runs (
                id, scheduler_key, started_at, status, created_at
            ) VALUES ({p}, {p}, {p}, {p}, {p})
        """
        self.db.execute(insert_sql, (id, scheduler_key, started_at, status, started_at))
        self.db.commit()

    def complete_run(
        self,
        id: str,
        completed_at: str,
        status: str,
        worker_run_id: Optional[str] = None,
        worker_stopped_reason: Optional[str] = None,
        items_attempted: int = 0,
        items_claimed: int = 0,
        success_count: int = 0,
        failure_count: int = 0,
        backpressure_count: int = 0,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """Finalize scheduler run audit record with metrics and terminal status."""
        safe_msg = sanitize_error_message(error_message)
        p = self._placeholder()
        update_sql = f"""
            UPDATE scheduler_runs
            SET completed_at = {p},
                status = {p},
                worker_run_id = {p},
                worker_stopped_reason = {p},
                items_attempted = {p},
                items_claimed = {p},
                success_count = {p},
                failure_count = {p},
                backpressure_count = {p},
                error_code = {p},
                error_message = {p}
            WHERE id = {p}
        """
        count = self._execute_rowcount(
            update_sql,
            (
                completed_at,
                status,
                worker_run_id,
                worker_stopped_reason,
                items_attempted,
                items_claimed,
                success_count,
                failure_count,
                backpressure_count,
                error_code,
                safe_msg,
                id,
            ),
        )
        self.db.commit()
        return count > 0

    def fail_run(
        self,
        id: str,
        completed_at: str,
        error_code: str,
        error_message: str,
    ) -> bool:
        """Mark scheduler run record as failed."""
        safe_msg = sanitize_error_message(error_message)
        p = self._placeholder()
        update_sql = f"""
            UPDATE scheduler_runs
            SET completed_at = {p},
                status = 'FAILED',
                error_code = {p},
                error_message = {p}
            WHERE id = {p}
        """
        count = self._execute_rowcount(update_sql, (completed_at, error_code, safe_msg, id))
        self.db.commit()
        return count > 0

    def list_stale_runs(self, stale_before_iso: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Query orphan running scheduler runs started prior to stale threshold."""
        p = self._placeholder()
        sql = f"""
            SELECT * FROM scheduler_runs
            WHERE status = 'RUNNING' AND started_at < {p}
            ORDER BY started_at ASC
            LIMIT {p}
        """
        return self.db.fetch_dicts(sql, (stale_before_iso, limit))

    def reconcile_stale_runs(
        self,
        stale_before_iso: str,
        now_dt: Optional[datetime] = None,
        limit: int = 100,
    ) -> int:
        """Reconcile stale scheduler runs to FAILED if no active matching lease is held.

        Returns:
            Number of orphan scheduler runs recovered.
        """
        now = now_dt or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        candidates = self.list_stale_runs(stale_before_iso, limit=limit)
        recovered_count = 0
        p = self._placeholder()

        for c in candidates:
            # Check state for candidate's scheduler_key
            state_sql = f"""
                SELECT lease_token, lease_expires_at, current_run_id
                FROM scheduler_dispatch_state
                WHERE scheduler_key = {p}
            """
            state_rows = self.db.fetch_dicts(state_sql, (c["scheduler_key"],))
            if state_rows:
                state = state_rows[0]
                # If current lease is active and matches candidate run id, do NOT recover
                if state.get("current_run_id") == c["id"]:
                    lease_exp = state.get("lease_expires_at")
                    if lease_exp and lease_exp > now_iso:
                        continue

            # Otherwise, run is stale and no active lease matches: recover
            update_sql = f"""
                UPDATE scheduler_runs
                SET status = 'FAILED',
                    error_code = 'SCHEDULER_EXECUTION_LOST',
                    error_message = 'Scheduler run abandoned or lost before completion',
                    completed_at = {p}
                WHERE id = {p} AND status = 'RUNNING'
            """
            updated = self._execute_rowcount(update_sql, (now_iso, c["id"]))
            if updated > 0:
                recovered_count += 1

        self.db.commit()
        return recovered_count

    def get_dispatch_state(self, scheduler_key: str) -> Optional[Dict[str, Any]]:
        """Fetch current scheduler dispatch state record."""
        p = self._placeholder()
        sql = f"SELECT * FROM scheduler_dispatch_state WHERE scheduler_key = {p}"
        rows = self.db.fetch_dicts(sql, (scheduler_key,))
        return rows[0] if rows else None

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Fetch scheduler run record by ID."""
        p = self._placeholder()
        sql = f"SELECT * FROM scheduler_runs WHERE id = {p}"
        rows = self.db.fetch_dicts(sql, (run_id,))
        return rows[0] if rows else None

    def list_runs(self, scheduler_key: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """List recent scheduler runs."""
        p = self._placeholder()
        if scheduler_key:
            sql = f"SELECT * FROM scheduler_runs WHERE scheduler_key = {p} ORDER BY started_at DESC LIMIT {p}"
            return self.db.fetch_dicts(sql, (scheduler_key, limit))
        sql = f"SELECT * FROM scheduler_runs ORDER BY started_at DESC LIMIT {p}"
        return self.db.fetch_dicts(sql, (limit,))
