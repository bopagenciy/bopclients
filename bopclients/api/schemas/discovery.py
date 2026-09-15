"""Pydantic schemas for discovery workflow endpoints."""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class SearchIntentRequest(BaseModel):
    """Natural language prospecting intent input."""

    raw_query: str = Field(..., min_length=2, description="Natural language description of target prospects")
    campaign_id: Optional[str] = Field(default=None, description="Optional target campaign ID to associate intent with")
    context: Optional[Dict[str, Any]] = Field(default=None, description="Optional additional context (e.g. ICP parameters)")


class SearchIntentResponse(BaseModel):
    """Parsed structured search intent."""

    organization_id: str
    campaign_id: Optional[str] = None
    raw_query: str
    industries: List[str] = Field(default_factory=list)
    business_categories: List[str] = Field(default_factory=list)
    countries: List[str] = Field(default_factory=list)
    regions: List[str] = Field(default_factory=list)
    cities: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    company_size_min: Optional[int] = None
    company_size_max: Optional[int] = None
    decision_maker_roles: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    services_to_offer: List[str] = Field(default_factory=list)
    desired_signals: List[str] = Field(default_factory=list)
    max_results: int = 100


class SearchPlanRequest(BaseModel):
    """Request payload to generate a SearchPlan, accepting parsed or refined SearchIntent fields."""

    organization_id: Optional[str] = None
    campaign_id: Optional[str] = None
    raw_query: str
    industries: List[str] = Field(default_factory=list)
    business_categories: List[str] = Field(default_factory=list)
    countries: List[str] = Field(default_factory=list)
    regions: List[str] = Field(default_factory=list)
    cities: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    company_size_min: Optional[int] = None
    company_size_max: Optional[int] = None
    decision_maker_roles: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
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


class DiscoveryExecutionRequest(BaseModel):
    """Request to execute discovery into an active campaign."""

    campaign_id: str = Field(..., description="Target active campaign ID (required)")
    raw_query: Optional[str] = Field(default=None, description="Optional raw query to parse & execute in one call")
    search_plan: Optional[SearchPlanRequest] = Field(default=None, description="Optional pre-approved SearchPlan to execute")


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
