"""Prospect domain entity."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Optional


@dataclass
class Prospect:
    """Prospect entity representing a business/lead in BopClients."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    forge_record_id: Optional[str] = None  # Reference to FORGE businesses.id
    name: str = ""
    website_url: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: str = "US"
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    industry: Optional[str] = None
    source: str = "overture"
    source_external_id: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        if not self.organization_id:
            raise ValueError("organization_id required")
        if not self.name.strip():
            raise ValueError("Prospect name cannot be empty")
