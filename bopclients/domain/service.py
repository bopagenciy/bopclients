"""Service domain entity representing what an organization offers/sells."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Optional
from bopclients.domain.enums import ServiceCategory


@dataclass
class Service:
    """Product/service offered by an organization."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    name: str = ""
    description: str = ""
    category: str = ServiceCategory.MARKETING.value
    active: bool = True
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        if not self.organization_id:
            raise ValueError("organization_id required")
        if not self.name.strip():
            raise ValueError("Service name cannot be empty")
