"""Ideal Customer Profile (ICP) and Target Market domain entities."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import List, Optional


@dataclass
class TargetMarket:
    """Geographic and demographic targeting parameters for an ICP or Campaign."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    icp_id: str = ""
    country: str = "US"
    region: Optional[str] = None  # State / Province, e.g., "FL"
    city: Optional[str] = None
    postal_code: Optional[str] = None
    radius_miles: float = 10.0
    language: str = "en"


@dataclass
class IdealCustomerProfile:
    """Ideal Customer Profile (ICP) defining target criteria for prospecting."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    name: str = ""
    description: str = ""
    industries: List[str] = field(default_factory=list)
    company_sizes: List[str] = field(default_factory=list)
    decision_maker_roles: List[str] = field(default_factory=list)
    pain_points: List[str] = field(default_factory=list)
    desired_signals: List[str] = field(default_factory=list)
    excluded_signals: List[str] = field(default_factory=list)
    countries: List[str] = field(default_factory=lambda: ["US"])
    languages: List[str] = field(default_factory=lambda: ["en"])
    target_markets: List[TargetMarket] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        if not self.organization_id:
            raise ValueError("organization_id required")
        if not self.name.strip():
            raise ValueError("ICP name cannot be empty")
