"""DTOs for Prospect Enrichment, Signal Detection, Opportunity Scoring, and Analysis Results."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import List, Optional, Dict, Any
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore


@dataclass
class EnrichmentSnapshot:
    """Normalized snapshot of enrichment data for signal detectors."""

    provider: str = "forge"
    prospect_id: str = ""
    website_url: Optional[str] = None
    website_reachable: bool = False
    scrape_status: str = "no_website"  # success, partial_timeout, timeout, forbidden, dns_failure, no_website

    emails: List[str] = field(default_factory=list)
    phones: List[str] = field(default_factory=list)

    technologies: List[str] = field(default_factory=list)
    cms: Optional[str] = None

    ssl_valid: Optional[bool] = None
    response_time_ms: Optional[float] = None
    http_status: Optional[int] = None

    has_contact_page: bool = False
    has_booking: bool = False
    has_chatbot: bool = False
    has_analytics: bool = False

    raw_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectedSignalDTO:
    """Signal detected by an ISignalDetector before persistence."""

    type: str
    value: Optional[str] = None
    confidence: float = 1.0
    source: str = "web_scrape"
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ServiceRecommendation:
    """Commercial service recommendation derived from detected opportunity signals."""

    service_id: str
    service_name: str
    relevance_score: int  # 0 to 100
    reasoning: str
    supporting_signals: List[str] = field(default_factory=list)


@dataclass
class ProspectAnalysisResult:
    """Full result summary of prospect enrichment, signal detection, and opportunity scoring."""

    prospect_id: str
    research_run_id: str
    enrichment_status: str
    signals_detected: List[Signal] = field(default_factory=list)
    lead_score: Optional[LeadScore] = None
    service_recommendations: List[ServiceRecommendation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
