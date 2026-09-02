"""User domain entity."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Optional


@dataclass
class User:
    """User entity representing a person with access to BopClients."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    email: str = ""
    full_name: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        """Validate user invariants."""
        if not self.email or "@" not in self.email:
            raise ValueError(f"Invalid user email: '{self.email}'")
        if not self.full_name.strip():
            raise ValueError("User full_name cannot be empty")
