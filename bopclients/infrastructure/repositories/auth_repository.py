"""Repositories for Auth Session persistence and Login Attempt rate-limiting."""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class AuthSessionRepository(BaseTenantRepository):
    """Repository managing bop_auth_sessions table."""

    def create_session(
        self,
        user_id: str,
        token_hash: str,
        expires_at: str,
        session_id: Optional[str] = None,
        user_agent_hash: Optional[str] = None,
        ip_address: Optional[str] = None,
        commit: bool = True,
    ) -> Dict[str, Any]:
        """Insert a new session with hashed token."""
        sid = session_id or str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        p = self._placeholder()

        sql = f"""
        INSERT INTO bop_auth_sessions (
            id, user_id, token_hash, created_at, expires_at, revoked_at, last_used_at, user_agent_hash, ip_address
        ) VALUES ({p}, {p}, {p}, {p}, {p}, NULL, {p}, {p}, {p})
        """
        self.db.execute(
            sql,
            (sid, user_id, token_hash, created_at, expires_at, created_at, user_agent_hash, ip_address),
        )
        if commit:
            self._commit_if_not_in_tx()

        return {
            "id": sid,
            "user_id": user_id,
            "token_hash": token_hash,
            "created_at": created_at,
            "expires_at": expires_at,
            "revoked_at": None,
            "last_used_at": created_at,
        }

    def get_session_by_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Fetch session by ID."""
        p = self._placeholder()
        sql = f"SELECT * FROM bop_auth_sessions WHERE id = {p}"
        rows = self.db.fetch_dicts(sql, (session_id,))
        return rows[0] if rows else None

    def get_active_session_by_hash(self, token_hash: str) -> Optional[Dict[str, Any]]:
        """Fetch unrevoked, unexpired session matching token_hash."""
        p = self._placeholder()
        now_iso = datetime.now(timezone.utc).isoformat()
        sql = f"""
        SELECT * FROM bop_auth_sessions
        WHERE token_hash = {p} AND revoked_at IS NULL AND expires_at > {p}
        """
        rows = self.db.fetch_dicts(sql, (token_hash, now_iso))
        return rows[0] if rows else None

    def touch_session(self, session_id: str, commit: bool = True) -> None:
        """Update last_used_at timestamp on active session."""
        p = self._placeholder()
        now_iso = datetime.now(timezone.utc).isoformat()
        sql = f"UPDATE bop_auth_sessions SET last_used_at = {p} WHERE id = {p} AND revoked_at IS NULL"
        self.db.execute(sql, (now_iso, session_id))
        if commit:
            self._commit_if_not_in_tx()

    def revoke_session(self, session_id: str, commit: bool = True) -> bool:
        """Revoke a single session by setting revoked_at."""
        p = self._placeholder()
        now_iso = datetime.now(timezone.utc).isoformat()
        sql = f"UPDATE bop_auth_sessions SET revoked_at = {p} WHERE id = {p} AND revoked_at IS NULL"
        self.db.execute(sql, (now_iso, session_id))
        if commit:
            self._commit_if_not_in_tx()
        return True

    def revoke_session_by_token_hash(self, token_hash: str, commit: bool = True) -> bool:
        """Revoke a single session by token_hash."""
        p = self._placeholder()
        now_iso = datetime.now(timezone.utc).isoformat()
        sql = f"UPDATE bop_auth_sessions SET revoked_at = {p} WHERE token_hash = {p} AND revoked_at IS NULL"
        self.db.execute(sql, (now_iso, token_hash))
        if commit:
            self._commit_if_not_in_tx()
        return True

    def revoke_all_user_sessions(self, user_id: str, commit: bool = True) -> None:
        """Revoke all active sessions for a user (e.g. password change)."""
        p = self._placeholder()
        now_iso = datetime.now(timezone.utc).isoformat()
        sql = f"UPDATE bop_auth_sessions SET revoked_at = {p} WHERE user_id = {p} AND revoked_at IS NULL"
        self.db.execute(sql, (now_iso, user_id))
        if commit:
            self._commit_if_not_in_tx()


class LoginAttemptRepository(BaseTenantRepository):
    """Repository managing bop_auth_login_attempts table for brute-force tracking."""

    def record_attempt(
        self,
        identifier_hash: str,
        is_successful: bool,
        attempt_time: Optional[str] = None,
        commit: bool = True,
    ) -> None:
        """Log a login attempt."""
        p = self._placeholder()
        aid = str(uuid.uuid4())
        t = attempt_time or datetime.now(timezone.utc).isoformat()
        is_succ = True if is_successful else False

        sql = f"""
        INSERT INTO bop_auth_login_attempts (id, identifier_hash, attempt_time, is_successful)
        VALUES ({p}, {p}, {p}, {p})
        """
        self.db.execute(sql, (aid, identifier_hash, t, is_succ))
        if commit:
            self._commit_if_not_in_tx()

    def count_recent_failures(self, identifier_hash: str, window_seconds: int = 900) -> int:
        """Count failed login attempts within sliding window."""
        p = self._placeholder()
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
        sql = f"""
        SELECT COUNT(*) as failure_count FROM bop_auth_login_attempts
        WHERE identifier_hash = {p} AND is_successful = {p} AND attempt_time >= {p}
        """
        rows = self.db.fetch_dicts(sql, (identifier_hash, False, cutoff))
        if rows:
            return int(rows[0]["failure_count"])
        return 0

    def clear_failures(self, identifier_hash: str, commit: bool = True) -> None:
        """Clear failed attempts for an identifier upon successful login."""
        p = self._placeholder()
        sql = f"DELETE FROM bop_auth_login_attempts WHERE identifier_hash = {p}"
        self.db.execute(sql, (identifier_hash,))
        if commit:
            self._commit_if_not_in_tx()
