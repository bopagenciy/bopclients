"""SearchIntent domain entity representing structured user prospecting intent."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import List, Optional


@dataclass
class SearchIntent:
    """Structured representation of natural language user search intent."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    campaign_id: Optional[str] = None

    raw_query: str = ""
    objective: str = "prospecting"
    target_entity_type: str = "business"  # e.g., "business", "individual"

    industries: List[str] = field(default_factory=list)
    business_categories: List[str] = field(default_factory=list)

    countries: List[str] = field(default_factory=list)
    regions: List[str] = field(default_factory=list)
    cities: List[str] = field(default_factory=list)
    postal_codes: List[str] = field(default_factory=list)

    languages: List[str] = field(default_factory=list)

    company_size_min: Optional[int] = None
    company_size_max: Optional[int] = None
    company_sizes: List[str] = field(default_factory=list)

    target_market_id: Optional[str] = None
    radius_miles: Optional[float] = None

    decision_maker_roles: List[str] = field(default_factory=list)

    keywords: List[str] = field(default_factory=list)
    negative_keywords: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    desired_signals: List[str] = field(default_factory=list)
    excluded_signals: List[str] = field(default_factory=list)

    services_to_offer: List[str] = field(default_factory=list)

    max_results: int = 100

    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def validate(self) -> None:
        """Validate domain invariants."""
        if not self.organization_id:
            raise ValueError("organization_id required")
        if not self.raw_query.strip():
            raise ValueError("raw_query cannot be empty")
        if self.max_results <= 0:
            raise ValueError("max_results must be greater than 0")
