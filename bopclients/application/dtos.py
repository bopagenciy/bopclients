"""Application DTOs (Data Transfer Objects) for commands and queries."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CreateOrganizationCommand:
    """Command to register a new Organization."""

    name: str
    slug: str
    description: Optional[str] = None
    website: Optional[str] = None
    country: str = "US"
    default_language: str = "en"
    timezone: str = "UTC"
    owner_email: str = ""
    owner_name: str = ""


@dataclass
class CreateServiceCommand:
    """Command to add a Service offering to an Organization."""

    organization_id: str
    name: str
    description: str
    category: str
    active: bool = True


@dataclass
class CreateICPCommand:
    """Command to define an Ideal Customer Profile (ICP)."""

    organization_id: str
    name: str
    description: str
    industries: List[str] = field(default_factory=list)
    company_sizes: List[str] = field(default_factory=list)
    decision_maker_roles: List[str] = field(default_factory=list)
    pain_points: List[str] = field(default_factory=list)
    desired_signals: List[str] = field(default_factory=list)
    excluded_signals: List[str] = field(default_factory=list)
    countries: List[str] = field(default_factory=lambda: ["US"])
    languages: List[str] = field(default_factory=lambda: ["en"])


@dataclass
class CreateCampaignCommand:
    """Command to create a Prospecting Campaign."""

    organization_id: str
    name: str
    icp_id: Optional[str] = None
    description: Optional[str] = None


@dataclass
class AddProspectCommand:
    """Command to add a Prospect to an Organization campaign."""

    organization_id: str
    name: str
    campaign_id: Optional[str] = None
    forge_record_id: Optional[str] = None
    website_url: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: str = "US"
    postal_code: Optional[str] = None
    industry: Optional[str] = None
    source: str = "overture"


@dataclass
class RecordSignalCommand:
    """Command to record a buying signal for a prospect."""

    organization_id: str
    prospect_id: str
    signal_type: str
    value: Optional[str] = None
    confidence: float = 1.0
    source: str = "web_scrape"
