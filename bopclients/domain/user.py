"""User domain entity."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Optional, Set

SUPPORTED_LOCALES: Set[str] = {"en", "es"}


@dataclass(init=False)
class User:
    """User entity representing a person with access to BopClients."""

    id: str
    email: str
    full_name: str
    password_hash: Optional[str]
    is_active: bool
    locale: str
    created_at: str

    def __init__(
        self,
        id: Optional[str] = None,
        email: str = "",
        full_name: str = "",
        name: Optional[str] = None,
        password_hash: Optional[str] = None,
        is_active: bool = True,
        locale: str = "en",
        created_at: Optional[str] = None,
    ):
        self.id = id if id is not None else str(uuid.uuid4())
        self.email = email
        self.full_name = name if (name is not None and not full_name) else full_name
        self.password_hash = password_hash
        self.is_active = is_active
        self.locale = locale
        self.created_at = created_at if created_at is not None else datetime.now(timezone.utc).isoformat()

    @property
    def name(self) -> str:
        return self.full_name

    @name.setter
    def name(self, val: str) -> None:
        self.full_name = val

    def validate(self) -> None:
        """Validate user invariants."""
        if not self.email or "@" not in self.email:
            raise ValueError(f"Invalid user email: '{self.email}'")
        if not self.full_name.strip():
            raise ValueError("User full_name cannot be empty")
        if self.locale not in SUPPORTED_LOCALES:
            raise ValueError(f"Unsupported user locale: '{self.locale}'. Must be one of {sorted(SUPPORTED_LOCALES)}")

    def __repr__(self) -> str:
        """Safe string representation strictly concealing password_hash."""
        return (
            f"User(id={self.id!r}, email={self.email!r}, full_name={self.full_name!r}, "
            f"password_hash=***REDACTED***, "
            f"is_active={self.is_active}, locale={self.locale!r}, created_at={self.created_at!r})"
        )
