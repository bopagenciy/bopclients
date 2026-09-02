"""DTOs and structures for Search Planning, Discovery Tasks, Location Resolution, and Execution Results."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import List, Optional, Dict, Any
from bopclients.domain.prospect import Prospect


@dataclass
class ResolvedLocation:
    """Resolved geographical entity for discovery execution."""

    country_code: str = "US"
    region_code: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_miles: float = 10.0


@dataclass
class DiscoveryTask:
    """Individual executable discovery task targeted at a specific provider."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    provider: str = "overture"  # e.g., "overture", "google_maps", "web_search", "linkedin"
    query: Optional[str] = None
    category: Optional[str] = None
    country: str = "US"
    region: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_miles: float = 10.0
    limit: int = 100
    priority: int = 1
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchWarning:
    """Structured warning emitted during search planning or execution."""

    code: str  # e.g., "LOCATION_NOT_RESOLVED", "PROVIDER_NOT_AVAILABLE", "COUNTRY_LEVEL_SEARCH_NOT_SUPPORTED"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchPlan:
    """Executable search plan containing ordered discovery tasks and planning warnings."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    campaign_id: Optional[str] = None
    intent_id: str = ""
    tasks: List[DiscoveryTask] = field(default_factory=list)
    warnings: List[SearchWarning] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class SearchExecutionResult:
    """Summary result of search plan execution."""

    plan_id: str = ""
    organization_id: str = ""
    campaign_id: Optional[str] = None
    research_run_id: str = ""
    tasks_total: int = 0
    tasks_succeeded: int = 0
    tasks_failed: int = 0
    total_discovered_raw: int = 0
    prospects_created: int = 0
    prospects_reused: int = 0
    total_imported_prospects: int = 0
    imported_prospects: List[Prospect] = field(default_factory=list)
    warnings: List[SearchWarning] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    executed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
