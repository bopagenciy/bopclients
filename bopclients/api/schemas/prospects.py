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
    """Standard prospect response model."""

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
