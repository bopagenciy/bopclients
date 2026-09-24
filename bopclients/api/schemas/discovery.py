"""Pydantic schemas for discovery workflow endpoints."""

from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field


class SearchIntentRequest(BaseModel):
    """Natural language prospecting intent input."""

    raw_query: str = Field(..., min_length=2, description="Natural language description of target prospects")
    campaign_id: Optional[str] = Field(default=None, description="Optional target campaign ID to associate intent with")
    target_market_id: Optional[str] = Field(default=None, description="Optional target market ID")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Optional additional context (e.g. ICP parameters)")


class SearchIntentResponse(BaseModel):
    """Parsed structured search intent."""

    organization_id: str
    campaign_id: Optional[str] = None
    target_market_id: Optional[str] = None
    radius_miles: Optional[float] = None
    raw_query: str
    industries: List[str] = Field(default_factory=list)
    business_categories: List[str] = Field(default_factory=list)
    countries: List[str] = Field(default_factory=list)
    regions: List[str] = Field(default_factory=list)
    cities: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    company_size_min: Optional[int] = None
    company_size_max: Optional[int] = None
    company_sizes: List[str] = Field(default_factory=list)
    decision_maker_roles: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    negative_keywords: List[str] = Field(default_factory=list)
    services_to_offer: List[str] = Field(default_factory=list)
    desired_signals: List[str] = Field(default_factory=list)
    max_results: int = 100


class SearchPlanRequest(BaseModel):
    """Request payload to generate a SearchPlan, accepting parsed or refined SearchIntent fields."""

    organization_id: Optional[str] = None
    campaign_id: Optional[str] = None
    target_market_id: Optional[str] = None
    radius_miles: Optional[float] = None
    raw_query: str
    industries: List[str] = Field(default_factory=list)
    business_categories: List[str] = Field(default_factory=list)
    countries: List[str] = Field(default_factory=list)
    regions: List[str] = Field(default_factory=list)
    cities: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    company_size_min: Optional[int] = None
    company_size_max: Optional[int] = None
    company_sizes: List[str] = Field(default_factory=list)
    decision_maker_roles: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    negative_keywords: List[str] = Field(default_factory=list)
    services_to_offer: List[str] = Field(default_factory=list)
    desired_signals: List[str] = Field(default_factory=list)
    max_results: int = 100


class DiscoveryTaskResponse(BaseModel):
    """Representation of an individual discovery task in a SearchPlan."""

    task_id: str
    provider: str
    query_params: Dict[str, Any]
    priority: int = 1
    status: str = "pending"
    estimated_items: Optional[int] = None


class SearchPlanResponse(BaseModel):
    """Previewable SearchPlan before execution."""

    organization_id: str
    campaign_id: Optional[str] = None
    tasks: List[DiscoveryTaskResponse] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    estimated_total_cost_credits: float = 0.0
    generated_at: str


class SearchPlanExecutionPayload(BaseModel):
    """Pre-approved search plan payload submitted for execution with tasks or plan parameters."""

    organization_id: Optional[str] = None
    campaign_id: Optional[str] = None
    target_market_id: Optional[str] = None
    radius_miles: Optional[float] = None
    raw_query: Optional[str] = None
    tasks: List[DiscoveryTaskResponse] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    estimated_total_cost_credits: Optional[float] = 0.0
    generated_at: Optional[str] = None
    industries: List[str] = Field(default_factory=list)
    business_categories: List[str] = Field(default_factory=list)
    countries: List[str] = Field(default_factory=list)
    regions: List[str] = Field(default_factory=list)
    cities: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    company_size_min: Optional[int] = None
    company_size_max: Optional[int] = None
    company_sizes: List[str] = Field(default_factory=list)
    decision_maker_roles: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    negative_keywords: List[str] = Field(default_factory=list)
    services_to_offer: List[str] = Field(default_factory=list)
    desired_signals: List[str] = Field(default_factory=list)
    max_results: Optional[int] = 100


class DiscoveryExecutionRequest(BaseModel):
    """Request to execute discovery into an active campaign."""

    campaign_id: str = Field(..., description="Target active campaign ID (required)")
    raw_query: Optional[str] = Field(default=None, description="Optional raw query to parse & execute in one call")
    search_plan: Optional[Union[SearchPlanExecutionPayload, SearchPlanRequest]] = Field(
        default=None, description="Optional pre-approved SearchPlan or plan parameters to execute"
    )


class DiscoveredProspectSummary(BaseModel):
    """Summary of an imported prospect from discovery."""

    id: str
    name: str
    website_url: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    source: Optional[str] = None


class DiscoveryExecutionResponse(BaseModel):
    """Outcome of running discovery and importing prospects."""

    status: str = Field(..., description="'completed', 'partial', or 'failed'")
    campaign_id: str
    tasks_executed: int
    tasks_succeeded: int
    tasks_failed: int
    discovered_businesses_count: int
    prospects_created: int
    prospects_reused: int
    total_imported_prospects: int
    imported_prospects: List[DiscoveredProspectSummary] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class DiscoveryCandidateSummary(BaseModel):
    """Summary of a candidate returned during preview without database persistence."""

    candidate_id: str
    name: str
    website_url: Optional[str] = None
    category: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    geographic_scope: Optional[str] = None
    classification_status: Optional[str] = None
    classification_details: Optional[Dict[str, Any]] = None
    title: Optional[str] = None
    snippet: Optional[str] = None
    source: Optional[str] = None
    # Structured Candidate Qualification:
    qualification_status: Optional[str] = None
    entity_archetype: Optional[str] = None
    geographic_evidence_status: Optional[str] = None
    current_activity_status: Optional[str] = None
    source_url: Optional[str] = None
    source_host: Optional[str] = None
    organization_website: Optional[str] = None
    is_commercial_review_ready: Optional[bool] = None
    qualification_reasons: Optional[List[str]] = None
    missing_evidence: Optional[List[str]] = None


class DiscoveryPreviewRequest(BaseModel):
    """Request payload for controlled single-query preview."""

    campaign_id: Optional[str] = Field(default=None, description="Optional target campaign ID")
    raw_query: Optional[str] = Field(default=None, description="Search query string")
    search_plan: Optional[Union[SearchPlanExecutionPayload, SearchPlanRequest]] = Field(
        default=None, description="Optional search plan to preview"
    )
    provider: str = Field(default="web_search", description="Discovery provider ('web_search' or 'overture')")


class DiscoveryPreviewDiagnostics(BaseModel):
    """Aggregate ephemeral diagnostics for discovery preview execution."""

    provider_results_received: int = Field(default=0, description="Total raw results returned by provider")
    results_missing_required_fields: int = Field(default=0, description="Results dropped due to missing title or URL")
    results_rejected_by_classifier: int = Field(default=0, description="Results rejected by candidate classifier")
    results_accepted_by_classifier: int = Field(default=0, description="Results accepted by candidate classifier")
    directory_candidates_retained: int = Field(default=0, description="Directory listing candidates retained as SEARCH_MATCH")
    candidates_returned_to_preview: int = Field(default=0, description="Total candidates returned in preview payload")
    rejection_reasons: Dict[str, int] = Field(default_factory=dict, description="Rejection counts grouped by stable reason code")


class DiscoveryPreviewResponse(BaseModel):
    """Outcome of running discovery in preview mode with zero persistence."""

    status: str = Field(..., description="'completed', 'partial', or 'failed'")
    organization_id: str
    campaign_id: Optional[str] = None
    provider: str
    tasks_executed: int = 0
    candidates_count: int = 0
    candidates: List[DiscoveryCandidateSummary] = Field(default_factory=list)
    prospects_inserted: int = 0
    sources_inserted: int = 0
    database_writes: int = 0
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    diagnostics: Optional[DiscoveryPreviewDiagnostics] = Field(
        default=None, description="Optional ephemeral preview funnel diagnostics"
    )
