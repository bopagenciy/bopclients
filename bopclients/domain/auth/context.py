"""User, Tenant, and Request context definitions for authenticated API requests."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any
from bopclients.domain.enums import MemberRole


@dataclass(frozen=True, init=False)
class UserPrincipal:
    """Authenticated user identity extracted from validated access token."""

    user_id: str
    email: str
    full_name: str
    locale: str
    is_active: bool
    session_id: Optional[str]
    email_verified_at: Optional[str]

    def __init__(
        self,
        user_id: str,
        email: str,
        full_name: str = "",
        name: Optional[str] = None,
        locale: str = "en",
        is_active: bool = True,
        session_id: Optional[str] = None,
        email_verified_at: Optional[str] = None,
    ):
        object.__setattr__(self, "user_id", user_id)
        object.__setattr__(self, "email", email)
        object.__setattr__(self, "full_name", name if (name is not None and not full_name) else full_name)
        object.__setattr__(self, "locale", locale)
        object.__setattr__(self, "is_active", is_active)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "email_verified_at", email_verified_at)

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def name(self) -> str:
        return self.full_name


@dataclass(frozen=True)
class TenantContext:
    """Resolved and verified organization tenant scope for the current request."""

    organization_id: str
    bop_organization_id: str
    role: MemberRole
    membership_id: str

    @property
    def is_owner(self) -> bool:
        return self.role == MemberRole.OWNER

    @property
    def is_admin(self) -> bool:
        return self.role in (MemberRole.OWNER, MemberRole.ADMIN)

    def can_perform(self, permission: Any) -> bool:
        """Check if active tenant role permits the given permission."""
        from bopclients.domain.auth.policy import AuthorizationPolicy
        return AuthorizationPolicy.has_permission(self.role, permission)


@dataclass(frozen=True)
class RequestContext:
    """Audit and execution context associated with the incoming HTTP request."""

    request_id: str
    principal: Optional[UserPrincipal] = None
    tenant: Optional[TenantContext] = None
    locale: str = "en"
    ip_address: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def actor_user_id(self) -> Optional[str]:
        return self.principal.user_id if self.principal else None

    @property
    def organization_id(self) -> Optional[str]:
        return self.tenant.organization_id if self.tenant else None

    @property
    def bop_organization_id(self) -> Optional[str]:
        return self.tenant.bop_organization_id if self.tenant else None
