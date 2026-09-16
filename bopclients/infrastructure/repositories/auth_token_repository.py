"""Database repository for AuthToken persistence."""

from datetime import datetime, timezone
from typing import Optional
from bopclients.domain.auth_token import AuthToken, AuthTokenType
from bopclients.application.interfaces.repositories import IAuthTokenRepository
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class AuthTokenRepository(BaseTenantRepository, IAuthTokenRepository):
    """Repository managing auth_tokens table."""

    @staticmethod
    def _row_to_token(r: dict) -> AuthToken:
        type_str = r["token_type"].lower() if isinstance(r["token_type"], str) else r["token_type"]
        return AuthToken(
            id=r["id"],
            user_id=r["user_id"],
            token_hash=r["token_hash"],
            token_type=AuthTokenType(type_str),
            expires_at=r["expires_at"],
            consumed_at=r.get("consumed_at"),
            created_at=r["created_at"],
        )

    def save(self, token: AuthToken, commit: bool = True) -> AuthToken:
        """Persist a single-use authentication token."""
        token.validate()
        p = self._placeholder()
        type_str = token.token_type.value if isinstance(token.token_type, AuthTokenType) else str(token.token_type)

        sql = f"""
        INSERT INTO auth_tokens (id, user_id, token_hash, token_type, expires_at, consumed_at, created_at)
        VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
        ON CONFLICT(id) DO UPDATE SET
            consumed_at = EXCLUDED.consumed_at
        """
        self.db.execute(
            sql,
            (token.id, token.user_id, token.token_hash, type_str, token.expires_at, token.consumed_at, token.created_at),
        )
        if commit:
            self._commit_if_not_in_tx()
        return token

    def get_by_token_hash(self, token_hash: str) -> Optional[AuthToken]:
        """Fetch token record by SHA-256 token hash."""
        p = self._placeholder()
        sql = f"SELECT id, user_id, token_hash, token_type, expires_at, consumed_at, created_at FROM auth_tokens WHERE token_hash = {p}"
        rows = self.db.fetch_dicts(sql, (token_hash,))
        if not rows:
            return None
        return self._row_to_token(rows[0])

    def consume_token(self, token_id: str, consumed_at: Optional[str] = None, commit: bool = True) -> bool:
        """Mark token consumed atomically, preventing replay."""
        p = self._placeholder()
        now_iso = consumed_at or datetime.now(timezone.utc).isoformat()
        sql = f"UPDATE auth_tokens SET consumed_at = {p} WHERE id = {p} AND consumed_at IS NULL"
        self.db.execute(sql, (now_iso, token_id))
        if commit:
            self._commit_if_not_in_tx()
        return True

    def revoke_active_tokens_for_user(self, user_id: str, token_type: AuthTokenType, commit: bool = True) -> int:
        """Revoke any active, unconsumed tokens of a given type for a user."""
        p = self._placeholder()
        now_iso = datetime.now(timezone.utc).isoformat()
        type_str = token_type.value if isinstance(token_type, AuthTokenType) else str(token_type)
        sql = f"UPDATE auth_tokens SET consumed_at = {p} WHERE user_id = {p} AND token_type = {p} AND consumed_at IS NULL"
        self.db.execute(sql, (now_iso, user_id, type_str))
        if commit:
            self._commit_if_not_in_tx()
        return True
