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
    negative_keywords: List[str] = field(default_factory=list)
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
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[SearchWarning] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    diagnostics: Optional[Dict[str, Any]] = None
    executed_query: Optional[str] = None
    executed_queries: Optional[List[str]] = None
    executed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


from pydantic import BaseModel, Field


class CandidateSourceEvidence(BaseModel):
    """Provenance record for an individual source discovery attached to an entity bundle."""

    source_url: str
    source_host: str
    source_type: str = "UNKNOWN"
    platform: Optional[str] = None
    title: Optional[str] = None
    snippet: Optional[str] = None


class CandidateInvestigationRequest(BaseModel):
    """Input payload to investigate a single candidate in preview."""

    candidate_id: Optional[str] = Field(default=None, description="Candidate ID from preview")
    candidate_name: str = Field(..., min_length=1, description="Entity name of the candidate")
    entity_archetype: Optional[str] = Field(default=None, description="Current entity archetype")
    organization_website: Optional[str] = Field(default=None, description="Current official website if known")
    category: Optional[str] = Field(default=None, description="Category / industry")
    city: Optional[str] = Field(default=None, description="Target city context")
    state: Optional[str] = Field(default=None, description="Target state / department context")
    country: Optional[str] = Field(default="CO", description="Country code")
    campaign_id: Optional[str] = Field(default=None, description="Optional target campaign ID")
    target_intent: Optional[str] = Field(default=None, description="Target ICP intent")
    current_qualification_status: Optional[str] = Field(default=None, description="Current qualification status")
    geographic_evidence_status: Optional[str] = Field(default=None, description="Current geographic evidence status")
    current_activity_status: Optional[str] = Field(default=None, description="Current operational activity status")
    qualification_reasons: List[str] = Field(default_factory=list, description="Current qualification reasons")
    missing_evidence: List[str] = Field(default_factory=list, description="Current missing evidence codes")
    sources: List[CandidateSourceEvidence] = Field(default_factory=list, description="Existing source bundle")
    title: Optional[str] = Field(default=None, description="Candidate title")
    snippet: Optional[str] = Field(default=None, description="Candidate excerpt / snippet")
    target_objective: Optional[str] = Field(default=None, description="Optional target objective override ('OFFICIAL_WEBSITE', 'LOCAL_PRESENCE', 'CURRENT_ACTIVITY')")


class CandidateInvestigationResponse(BaseModel):
    """Result of single-candidate investigation and requalification."""

    status: str = Field(..., description="'completed' or 'failed'")
    candidate_id: str
    candidate_name: str
    investigation_objective: str = Field(..., description="Evidence objective pursued ('OFFICIAL_WEBSITE', 'LOCAL_PRESENCE', 'CURRENT_ACTIVITY')")
    investigation_query: Optional[str] = Field(default=None, description="Targeted query dispatched to provider")
    results_received: int = 0
    previous_qualification_status: str
    qualification_status: str
    qualification_changed: bool = False
    is_commercial_review_ready: bool = False
    qualification_reasons: List[str] = Field(default_factory=list)
    missing_evidence: List[str] = Field(default_factory=list)
    entity_archetype: Optional[str] = None
    organization_website: Optional[str] = None
    geographic_evidence_status: Optional[str] = None
    current_activity_status: Optional[str] = None
    sources_count: int = 1
    sources: List[CandidateSourceEvidence] = Field(default_factory=list)
    new_sources_added: int = 0
    database_writes: int = 0
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
