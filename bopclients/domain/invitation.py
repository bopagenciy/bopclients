"""Organization invitation domain entity and invariant validation."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid
import re

from bopclients.domain.enums import MemberRole, InvitationStatus


EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class OrganizationInvitation:
    """Represents a secure invitation to join an organization."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    email_normalized: str = ""
    role: MemberRole = MemberRole.MEMBER
    token_hash: str = ""
    status: InvitationStatus = InvitationStatus.PENDING
    invited_by_user_id: str = ""
    expires_at: str = ""
    accepted_at: Optional[str] = None
    revoked_at: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        """Validate invitation invariants."""
        if not self.organization_id or not self.organization_id.strip():
            raise ValueError("organization_id cannot be empty")

        if not self.email_normalized or not EMAIL_REGEX.match(self.email_normalized.strip()):
            raise ValueError(f"Invalid email address: '{self.email_normalized}'")

        if not self.invited_by_user_id or not self.invited_by_user_id.strip():
            raise ValueError("invited_by_user_id cannot be empty")

        if not self.token_hash or len(self.token_hash) != 64:
            raise ValueError("token_hash must be a 64-character SHA-256 hexadecimal string")

        if self.role == MemberRole.OWNER:
            raise ValueError("Cannot invite a user with OWNER role")

        if not self.expires_at:
            raise ValueError("expires_at cannot be empty")

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        """Check if invitation has expired based on current UTC time."""
        if not self.expires_at:
            return False
        current_time = now or datetime.now(timezone.utc)
        try:
            exp_time = datetime.fromisoformat(self.expires_at)
            # Ensure timezone awareness
            if exp_time.tzinfo is None:
                exp_time = exp_time.replace(tzinfo=timezone.utc)
            return current_time >= exp_time
        except (ValueError, TypeError):
            return True

    def is_pending(self, now: Optional[datetime] = None) -> bool:
        """Return True if invitation status is PENDING and not expired."""
        return self.status == InvitationStatus.PENDING and not self.is_expired(now=now)
