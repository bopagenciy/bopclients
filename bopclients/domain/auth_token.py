"""Auth token domain entity and type enum for password reset and email verification."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import uuid


class AuthTokenType(str, Enum):
    """Supported authentication token types."""
    PASSWORD_RESET = "password_reset"
    EMAIL_VERIFICATION = "email_verification"


@dataclass
class AuthToken:
    """Domain entity representing a persistent single-use authentication token."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    token_hash: str = ""
    token_type: AuthTokenType = AuthTokenType.PASSWORD_RESET
    expires_at: str = ""
    consumed_at: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        """Validate token invariants."""
        if not self.user_id or not self.user_id.strip():
            raise ValueError("user_id cannot be empty")
        if not self.token_hash or len(self.token_hash) != 64:
            raise ValueError("token_hash must be a 64-character SHA-256 hexadecimal string")
        if not self.expires_at:
            raise ValueError("expires_at cannot be empty")
        if not isinstance(self.token_type, AuthTokenType):
            try:
                self.token_type = AuthTokenType(str(self.token_type))
            except ValueError:
                raise ValueError(f"Invalid token_type: {self.token_type}")

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        """Check whether token expiration has passed."""
        if not self.expires_at:
            return True
        current_time = now or datetime.now(timezone.utc)
        try:
            exp_time = datetime.fromisoformat(self.expires_at)
            if exp_time.tzinfo is None:
                exp_time = exp_time.replace(tzinfo=timezone.utc)
            return current_time >= exp_time
        except (ValueError, TypeError):
            return True

    def is_valid(self, now: Optional[datetime] = None) -> bool:
        """Check whether token is unconsumed and unexpired."""
        return self.consumed_at is None and not self.is_expired(now=now)
