"""Organization and membership domain entities."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Dict, Any, Optional
from bopclients.domain.enums import MemberRole


@dataclass
class Organization:
    """Organization entity representing a business tenant in BopClients."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    bop_organization_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    slug: str = ""
    description: Optional[str] = None
    website: Optional[str] = None
    country: str = "US"
    default_language: str = "en"
    timezone: str = "UTC"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        """Validate organization invariants."""
        if not self.name.strip():
            raise ValueError("Organization name cannot be empty")
        if not self.slug.strip():
            raise ValueError("Organization slug cannot be empty")
        if not self.bop_organization_id or not self.bop_organization_id.strip():
            raise ValueError("Organization bop_organization_id cannot be empty")
        try:
            uuid.UUID(self.bop_organization_id.strip())
        except (ValueError, AttributeError):
            raise ValueError(f"Organization bop_organization_id '{self.bop_organization_id}' must be a valid UUID")


@dataclass
class OrganizationMember:
    """User membership in an Organization with assigned Role."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    user_id: str = ""
    role: MemberRole = MemberRole.MEMBER
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        if not self.organization_id:
            raise ValueError("organization_id required")
        if not self.user_id:
            raise ValueError("user_id required")


@dataclass
class OrganizationSettings:
    """Key-value organization configuration settings."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    key: str = ""
    value: str = ""
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
