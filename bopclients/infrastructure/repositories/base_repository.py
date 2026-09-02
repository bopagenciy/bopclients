"""Base tenant-aware repository enforcing strict tenant isolation (organization_id scoping)."""

from typing import Any
from bopclients.domain.exceptions import TenantAccessError


class BaseTenantRepository:
    """Base repository class providing database helper methods and tenant boundary validation."""

    def __init__(self, db: Any):
        """Initialize with a database interface (ForgeDB or DB connection)."""
        self.db = db

    def _validate_tenant(self, org_id: str) -> str:
        """Validate that a valid, non-empty tenant organization_id is provided."""
        if not org_id or not isinstance(org_id, str) or not org_id.strip():
            raise TenantAccessError("Repository operation rejected: missing or invalid organization_id")
        return org_id.strip()

    def _placeholder(self) -> str:
        """Return parameter placeholder string for current backend (%s or ?)."""
        return "%s" if getattr(self.db, "is_postgres", False) else "?"
