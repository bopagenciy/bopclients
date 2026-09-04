"""ProviderRateLimitRepository implementing distributed rate limiting & concurrency state management."""

import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Optional, Dict, Tuple
from bopclients.domain.rate_limit import (
    ProviderRateLimitPolicy,
    ProviderAcquireStatus,
    ProviderAcquireResult,
)

logger = logging.getLogger("bopclients.repositories.provider_rate_limit")


class ProviderRateLimitRepository:
    """Repository managing distributed provider rate limit state and concurrency leases."""

    def __init__(self, db: Any):
        self.db = db

    def _placeholder(self) -> str:
        """Return parameter placeholder string (%s or ?)."""
        if hasattr(self.db, "placeholder"):
            return self.db.placeholder
        return "%s" if getattr(self.db, "backend_name", "") == "postgresql" else "?"

    def _execute_rowcount(self, sql: str, params: Optional[Tuple[Any, ...]] = None) -> int:
        """Execute statement and return affected row count."""
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

    def try_acquire(
        self,
        provider_key: str,
        scope_key: str,
        policy: ProviderRateLimitPolicy,
        now_dt: Optional[datetime] = None,
    ) -> ProviderAcquireResult:
        """Atomically acquire a rate limit and concurrency lease slot for a provider scope.
        
        Evaluates active cooldown, concurrency leases, and request window counters in a single
        atomic transaction with PostgreSQL row locks (SELECT FOR UPDATE).
        """
        permit_id = str(uuid.uuid4())

        # If policy is disabled, grant immediately without consuming slot
        if not policy.enabled:
            return ProviderAcquireResult(
                status=ProviderAcquireStatus.PROVIDER_DISABLED,
                acquired=True,
                provider_key=provider_key,
                scope_key=scope_key,
                permit_id=permit_id,
                reason="Provider rate limiting is disabled",
            )

        now = now_dt or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        lease_token = f"lease-{uuid.uuid4().hex}"
        p = self._placeholder()
        is_pg = (p == "%s")

        try:
            # 1. Ensure state row exists idempotently
            init_id = str(uuid.uuid4())
            if is_pg:
                ensure_sql = f"""
                    INSERT INTO provider_rate_limit_state (id, provider_key, scope_key, window_started_at, execution_count, updated_at)
                    VALUES ({p}, {p}, {p}, {p}, 0, {p})
                    ON CONFLICT (provider_key, scope_key) DO NOTHING
                """
            else:
                ensure_sql = f"""
                    INSERT OR IGNORE INTO provider_rate_limit_state (id, provider_key, scope_key, window_started_at, execution_count, updated_at)
                    VALUES ({p}, {p}, {p}, {p}, 0, {p})
                """
            self.db.execute(ensure_sql, (init_id, provider_key, scope_key, now_iso, now_iso))

            # 2. Query and lock state row
            if is_pg:
                select_sql = f"""
                    SELECT id, window_started_at, execution_count, cooldown_until, last_status_code
                    FROM provider_rate_limit_state
                    WHERE provider_key = {p} AND scope_key = {p}
                    FOR UPDATE
                """
            else:
                select_sql = f"""
                    SELECT id, window_started_at, execution_count, cooldown_until, last_status_code
                    FROM provider_rate_limit_state
                    WHERE provider_key = {p} AND scope_key = {p}
                """
            rows = self.db.fetch_dicts(select_sql, (provider_key, scope_key))
            if not rows:
                self.db.rollback()
                return ProviderAcquireResult(
                    status=ProviderAcquireStatus.RATE_LIMITED,
                    acquired=False,
                    provider_key=provider_key,
                    scope_key=scope_key,
                    permit_id=permit_id,
                    reason="Failed to inspect rate limit state row",
                )

            state = rows[0]

            # 3. Check Cooldown
            cooldown_until = state.get("cooldown_until")
            if cooldown_until and cooldown_until > now_iso:
                self.db.commit()
                diff_sec = max(1, int((datetime.fromisoformat(cooldown_until.replace("Z", "+00:00")) - now).total_seconds()))
                return ProviderAcquireResult(
                    status=ProviderAcquireStatus.COOLDOWN_ACTIVE,
                    acquired=False,
                    provider_key=provider_key,
                    scope_key=scope_key,
                    permit_id=permit_id,
                    retry_not_before=cooldown_until,
                    retry_after_seconds=diff_sec,
                    reason=f"Provider cooldown active until {cooldown_until}",
                )

            # 4. Check Concurrency Leases
            count_sql = f"""
                SELECT COUNT(*) AS active_count
                FROM provider_rate_limit_leases
                WHERE provider_key = {p} AND scope_key = {p} AND expires_at > {p}
            """
            cnt_rows = self.db.fetch_dicts(count_sql, (provider_key, scope_key, now_iso))
            active_leases = cnt_rows[0]["active_count"] if cnt_rows else 0

            if active_leases >= policy.max_concurrent:
                earliest_sql = f"""
                    SELECT MIN(expires_at) AS earliest_expiry
                    FROM provider_rate_limit_leases
                    WHERE provider_key = {p} AND scope_key = {p} AND expires_at > {p}
                """
                early_rows = self.db.fetch_dicts(earliest_sql, (provider_key, scope_key, now_iso))
                earliest = early_rows[0]["earliest_expiry"] if early_rows and early_rows[0]["earliest_expiry"] else now_iso
                diff_sec = max(1, int((datetime.fromisoformat(earliest.replace("Z", "+00:00")) - now).total_seconds()))
                self.db.commit()
                return ProviderAcquireResult(
                    status=ProviderAcquireStatus.CONCURRENCY_LIMITED,
                    acquired=False,
                    provider_key=provider_key,
                    scope_key=scope_key,
                    permit_id=permit_id,
                    retry_not_before=earliest,
                    retry_after_seconds=diff_sec,
                    reason=f"Max concurrency reached ({active_leases}/{policy.max_concurrent})",
                )

            # 5. Check Fixed Window & Execution Rate
            window_started_str = state["window_started_at"]
            window_started_dt = datetime.fromisoformat(window_started_str.replace("Z", "+00:00"))
            window_expires_dt = window_started_dt + timedelta(seconds=policy.window_seconds)

            if now >= window_expires_dt:
                # Window expired, advance to new window
                curr_window_started_iso = now_iso
                curr_execution_count = 0
                curr_window_expires_dt = now + timedelta(seconds=policy.window_seconds)
            else:
                curr_window_started_iso = window_started_str
                curr_execution_count = state.get("execution_count", 0)
                curr_window_expires_dt = window_expires_dt

            if curr_execution_count >= policy.max_executions:
                diff_sec = max(1, int((curr_window_expires_dt - now).total_seconds()))
                self.db.commit()
                return ProviderAcquireResult(
                    status=ProviderAcquireStatus.RATE_LIMITED,
                    acquired=False,
                    provider_key=provider_key,
                    scope_key=scope_key,
                    permit_id=permit_id,
                    retry_not_before=curr_window_expires_dt.isoformat(),
                    retry_after_seconds=diff_sec,
                    reason=f"Max execution rate reached ({curr_execution_count}/{policy.max_executions}) in window",
                )

            # 6. Acquisition Succeeded: Insert Lease & Increment Execution Count
            new_execution_count = curr_execution_count + 1
            lease_expires_iso = (now + timedelta(seconds=policy.request_lease_duration_seconds)).isoformat()
            lease_id = str(uuid.uuid4())

            insert_lease_sql = f"""
                INSERT INTO provider_rate_limit_leases (id, provider_key, scope_key, lease_token, permit_id, expires_at, created_at)
                VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
            """
            self.db.execute(
                insert_lease_sql,
                (lease_id, provider_key, scope_key, lease_token, permit_id, lease_expires_iso, now_iso),
            )

            update_state_sql = f"""
                UPDATE provider_rate_limit_state
                SET window_started_at = {p},
                    execution_count = {p},
                    updated_at = {p}
                WHERE provider_key = {p} AND scope_key = {p}
            """
            self.db.execute(update_state_sql, (curr_window_started_iso, new_execution_count, now_iso, provider_key, scope_key))

            self.db.commit()

            return ProviderAcquireResult(
                status=ProviderAcquireStatus.ACQUIRED,
                acquired=True,
                provider_key=provider_key,
                scope_key=scope_key,
                permit_id=permit_id,
                lease_token=lease_token,
                reason="Slot successfully acquired",
            )

        except Exception as ex:
            try:
                self.db.rollback()
            except Exception:
                pass
            logger.error(f"Error acquiring provider slot for {provider_key}:{scope_key}: {ex}")
            raise

    def release_lease(self, provider_key: str, scope_key: str, lease_token: str) -> bool:
        """Release an active concurrency lease by token.
        
        Stale/non-owner releases have no effect on other workers' active leases.
        """
        if not lease_token:
            return False
        p = self._placeholder()
        sql = f"""
            DELETE FROM provider_rate_limit_leases
            WHERE provider_key = {p} AND scope_key = {p} AND lease_token = {p}
        """
        rc = self._execute_rowcount(sql, (provider_key, scope_key, lease_token))
        self.db.commit()
        return rc > 0

    def record_cooldown(
        self,
        provider_key: str,
        scope_key: str,
        status_code: int,
        cooldown_seconds: int,
        now_dt: Optional[datetime] = None,
    ) -> None:
        """Record a cooldown deadline on 429/503 responses, propagating to subsequent workers."""
        now = now_dt or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        cooldown_until = (now + timedelta(seconds=cooldown_seconds)).isoformat()
        p = self._placeholder()
        is_pg = (p == "%s")

        init_id = str(uuid.uuid4())
        if is_pg:
            ensure_sql = f"""
                INSERT INTO provider_rate_limit_state (id, provider_key, scope_key, window_started_at, execution_count, updated_at)
                VALUES ({p}, {p}, {p}, {p}, 0, {p})
                ON CONFLICT (provider_key, scope_key) DO NOTHING
            """
        else:
            ensure_sql = f"""
                INSERT OR IGNORE INTO provider_rate_limit_state (id, provider_key, scope_key, window_started_at, execution_count, updated_at)
                VALUES ({p}, {p}, {p}, {p}, 0, {p})
            """
        self.db.execute(ensure_sql, (init_id, provider_key, scope_key, now_iso, now_iso))

        update_sql = f"""
            UPDATE provider_rate_limit_state
            SET cooldown_until = {p},
                last_status_code = {p},
                last_retry_after_seconds = {p},
                updated_at = {p}
            WHERE provider_key = {p} AND scope_key = {p}
        """
        self.db.execute(update_sql, (cooldown_until, status_code, cooldown_seconds, now_iso, provider_key, scope_key))
        self.db.commit()

    def get_state(
        self, provider_key: str, scope_key: str, now_dt: Optional[datetime] = None
    ) -> Optional[Dict[str, Any]]:
        """Fetch current rate limit state and active concurrency count for diagnostics."""
        now = now_dt or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        p = self._placeholder()
        query = f"SELECT * FROM provider_rate_limit_state WHERE provider_key = {p} AND scope_key = {p}"
        rows = self.db.fetch_dicts(query, (provider_key, scope_key))
        if not rows:
            return None
        st = dict(rows[0])
        cnt_sql = f"""
            SELECT COUNT(*) AS active_count
            FROM provider_rate_limit_leases
            WHERE provider_key = {p} AND scope_key = {p} AND expires_at > {p}
        """
        cnt_rows = self.db.fetch_dicts(cnt_sql, (provider_key, scope_key, now_iso))
        st["active_leases_count"] = cnt_rows[0]["active_count"] if cnt_rows else 0
        return st

    def cleanup_expired_leases(
        self,
        provider_key: Optional[str] = None,
        scope_key: Optional[str] = None,
        now_dt: Optional[datetime] = None,
    ) -> int:
        """Prune expired concurrency leases from table (maintenance only, not required for correctness)."""
        now = now_dt or datetime.now(timezone.utc)
        now_iso = now.isoformat()
        p = self._placeholder()
        where_clauses = [f"expires_at <= {p}"]
        params = [now_iso]
        if provider_key:
            where_clauses.append(f"provider_key = {p}")
            params.append(provider_key)
        if scope_key:
            where_clauses.append(f"scope_key = {p}")
            params.append(scope_key)

        sql = f"DELETE FROM provider_rate_limit_leases WHERE {' AND '.join(where_clauses)}"
        rc = self._execute_rowcount(sql, tuple(params))
        self.db.commit()
        return rc
