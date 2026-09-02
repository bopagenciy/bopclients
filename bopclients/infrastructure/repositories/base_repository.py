"""Base tenant-aware repository enforcing strict tenant isolation (organization_id scoping)."""

from typing import Any, Optional, Tuple
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
        if hasattr(self.db, "placeholder"):
            return self.db.placeholder
        return "%s" if getattr(self.db, "backend_name", "") == "postgresql" else "?"

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
