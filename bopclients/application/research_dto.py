"""Data Transfer Objects (DTOs) and claim models for P4 Prospect Research and Intelligence."""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from bopclients.domain.prospect import Prospect
from bopclients.domain.contact import Contact
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.service import Service
from bopclients.domain.icp import IdealCustomerProfile
from bopclients.domain.prospect_source import ProspectSource
from bopclients.application.enrichment_dto import EnrichmentSnapshot, ServiceRecommendation


@dataclass
class ResearchClaim:
    """Individual evidence-backed claim supporting prospect research."""

    id: str = ""
    claim_type: str = ""  # e.g., "website_latency", "booking_absence", "icp_fit"
    statement: str = ""
    classification: str = "observed"  # "observed", "derived", "inferred"
    confidence: float = 1.0
    evidence_refs: List[str] = field(default_factory=list)  # e.g., ["signal:no_booking"]
    source_refs: List[str] = field(default_factory=list)    # e.g., ["enrichment:forge"]


@dataclass
class CommercialOpportunity:
    """Specific commercial sales opportunity identified for a prospect."""

    opportunity_type: str = ""  # e.g., "booking_automation", "website_modernization", "analytics_setup"
    title: str = ""
    description: str = ""
    confidence: float = 1.0
    supporting_signals: List[str] = field(default_factory=list)
    supporting_claims: List[str] = field(default_factory=list)
    matched_services: List[str] = field(default_factory=list)
    priority: str = "medium"  # "low", "medium", "high"


@dataclass
class ProspectResearchContext:
    """Structured input context passed to research providers (Strictly tenant-scoped)."""

    organization_id: str
    prospect: Prospect
    enrichment_snapshot: Optional[EnrichmentSnapshot] = None
    signals: List[Signal] = field(default_factory=list)
    lead_score: Optional[LeadScore] = None
    services: List[Service] = field(default_factory=list)
    icp: Optional[IdealCustomerProfile] = None
    contacts: List[Contact] = field(default_factory=list)
    sources: List[ProspectSource] = field(default_factory=list)


@dataclass
class ProspectResearchDraft:
    """Structured sales research draft emitted by a research provider prior to policy validation."""

    executive_summary: str = ""
    business_profile: Dict[str, Any] = field(default_factory=dict)
    claims: List[ResearchClaim] = field(default_factory=list)
    commercial_opportunities: List[CommercialOpportunity] = field(default_factory=list)
    recommended_services: List[ServiceRecommendation] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)
    overall_confidence: float = 1.0
    confidence_label: str = "high"  # "low", "medium", "high"


@dataclass
class ProspectResearchResult:
    """Final validated sales research result returned to application callers."""

    prospect_id: str
    research_run_id: str
    provider: str
    executive_summary: str
    business_profile: Dict[str, Any]
    claims: List[ResearchClaim]
    commercial_opportunities: List[CommercialOpportunity]
    recommended_services: List[ServiceRecommendation]
    risks: List[str]
    unknowns: List[str]
    confidence: float
    confidence_label: str
    research_version: str
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    usage_metadata: Optional[Dict[str, int]] = None
    created_at: str = ""


@dataclass
class AIResearchRequest:
    """Sanitized, tenant-safe payload for external LLM research requests."""

    organization_id: str
    prospect_name: str
    industry: Optional[str]
    country: Optional[str]
    website_url: Optional[str]
    observed_signals: List[Dict[str, Any]]
    available_services: List[Dict[str, Any]]
    icp_description: Optional[str]
    evidence_catalog: Dict[str, Any] = field(default_factory=dict)
    allowed_evidence_refs: List[str] = field(default_factory=list)
    allowed_source_refs: List[str] = field(default_factory=list)
    allowed_service_ids: List[str] = field(default_factory=list)


@dataclass
class AIResearchResponse:
    """Structured response contract from external LLM provider."""

    executive_summary: str
    business_profile_notes: str
    proposed_claims: List[Dict[str, Any]]
    proposed_opportunities: List[Dict[str, Any]]
    perceived_risks: List[str]
    perceived_unknowns: List[str]
    usage_metadata: Optional[Dict[str, int]] = None
