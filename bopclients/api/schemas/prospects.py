"""Prospect schemas including aggregated detail view."""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ProspectFilterParams(BaseModel):
    """Filter criteria for prospect search and listing."""

    campaign_id: Optional[str] = None
    industry: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    source: Optional[str] = None
    search: Optional[str] = Field(default=None, description="Free text search over company name or website")
    sort_by: Optional[str] = Field(default="created_at", description="Field to sort by: created_at, name, industry")
    sort_dir: Optional[str] = Field(default="desc", description="Sort direction: asc, desc")


class ProspectCreate(BaseModel):
    """Create prospect payload."""

    name: Optional[str] = None
    company_name: Optional[str] = None
    website: Optional[str] = None
    website_url: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: str = "US"
    postal_code: Optional[str] = None
    industry: Optional[str] = None
    source: str = "manual"


class ProspectUpdate(BaseModel):
    """Update prospect contact details."""

    name: Optional[str] = None
    website_url: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    industry: Optional[str] = None


class ProspectResponse(BaseModel):
    """Standard prospect response model with operational summary fields."""

    id: str
    organization_id: str
    forge_record_id: Optional[str] = None
    name: str
    website_url: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: str = "US"
    postal_code: Optional[str] = None
    industry: Optional[str] = None
    source: Optional[str] = None
    lead_score: Optional[int] = None
    priority_tier: Optional[str] = None
    campaign_count: Optional[int] = None
    campaign_names: List[str] = Field(default_factory=list)
    signals_count: Optional[int] = None
    created_at: str
    updated_at: str


class ProspectDetailResponse(BaseModel):
    """Aggregated prospect view combining prospect entity, score, priority, intelligence, and signals."""

    prospect: ProspectResponse
    campaign_associations: List[Dict[str, Any]] = Field(default_factory=list)
    lead_score: Optional[Dict[str, Any]] = None
    priority: Optional[Dict[str, Any]] = None
    intelligence_summary: Optional[Dict[str, Any]] = None
    recent_signals: List[Dict[str, Any]] = Field(default_factory=list)
    monitoring_schedule: Optional[Dict[str, Any]] = None


class BulkAddToCampaignRequest(BaseModel):
    """Payload for adding multiple prospects to a campaign."""

    campaign_id: str
    prospect_ids: List[str] = Field(..., min_length=1, max_length=100)


class BulkAddToCampaignResponse(BaseModel):
    """Result of bulk add to campaign."""

    campaign_id: str
    requested: int
    added: int
    already_present: int
    failed: int
    prospect_ids: List[str] = Field(default_factory=list)


class BulkRecalculateScoreRequest(BaseModel):
    """Payload for bulk lead score recalculation."""

    prospect_ids: List[str] = Field(..., min_length=1, max_length=50)


class BulkRecalculateScoreResponse(BaseModel):
    """Result of bulk lead score recalculation."""

    requested: int
    succeeded: int
    failed: int
    items: List[Dict[str, Any]] = Field(default_factory=list)


class BulkRecalculatePriorityRequest(BaseModel):
    """Payload for bulk priority recalculation."""

    prospect_ids: List[str] = Field(..., min_length=1, max_length=50)
    campaign_id: Optional[str] = None


class BulkRecalculatePriorityResponse(BaseModel):
    """Result of bulk priority recalculation."""

    requested: int
    succeeded: int
    failed: int
    items: List[Dict[str, Any]] = Field(default_factory=list)


class BulkResearchRequest(BaseModel):
    """Payload for bulk triggering research."""

    prospect_ids: List[str] = Field(..., min_length=1, max_length=25)
    campaign_id: Optional[str] = None
    run_type: str = "full_diligence"


class BulkResearchResponse(BaseModel):
    """Result of bulk research trigger."""

    requested: int
    queued: int
    already_active: int
    failed: int
    run_ids: List[str] = Field(default_factory=list)


class BulkExportRequest(BaseModel):
    """Payload for exporting selected prospect IDs."""

    prospect_ids: Optional[List[str]] = Field(default=None, max_length=1000)


class CrmHandoffResponse(BaseModel):
    """Result of triggering prospect handoff to Bop CRM."""

    prospect_id: str
    status: str
    event_id: str
    correlation_id: str
    requested_at: str
    destination_count: int
    is_idempotent_replay: bool
    message: str


class CrmHandoffStatusResponse(BaseModel):
    """Current CRM handoff delivery and synchronization status."""

    prospect_id: str
    status: str
    event_id: Optional[str] = None
    correlation_id: Optional[str] = None
    requested_at: Optional[str] = None
    delivered_at: Optional[str] = None
    attempt_count: int = 0
    last_error_message: Optional[str] = None
    destination_count: int = 0
    destinations: List[str] = Field(default_factory=list)


class BulkCrmHandoffRequest(BaseModel):
    """Payload for triggering CRM handoff for multiple prospects."""

    prospect_ids: List[str] = Field(..., min_length=1, max_length=50)


class BulkCrmHandoffResponse(BaseModel):
    """Result of bulk CRM handoff trigger."""

    requested: int
    queued: int
    already_queued_or_delivered: int
    failed: int
    errors: Dict[str, str] = Field(default_factory=dict)
