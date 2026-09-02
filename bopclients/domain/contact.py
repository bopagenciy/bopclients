"""Contact domain entity."""

from dataclasses import dataclass, field
import uuid
from typing import Optional


@dataclass
class Contact:
    """Person/Contact associated with a Prospect."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    prospect_id: str = ""
    name: str = ""
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    title: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    instagram_url: Optional[str] = None
    facebook_url: Optional[str] = None

    def validate(self) -> None:
        if not self.prospect_id:
            raise ValueError("prospect_id required")
        if not self.name.strip():
            raise ValueError("Contact name cannot be empty")
