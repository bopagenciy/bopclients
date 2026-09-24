"""Domain models and contracts for structured candidate qualification.

Provides additive qualification statuses, entity archetypes, geographic evidence states,
and operational activity indicators to distinguish raw search matches from prospects
ready for human commercial review.
"""

from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


class CandidateQualificationStatus(str, Enum):
    """Structured commercial readiness status for discovery candidates."""

    READY_FOR_COMMERCIAL_REVIEW = "READY_FOR_COMMERCIAL_REVIEW"
    SEARCH_MATCH = "SEARCH_MATCH"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECTED = "REJECTED"


class EntityArchetype(str, Enum):
    """Categorization of evidenced entity identity."""

    INDEPENDENT_ORGANIZATION = "INDEPENDENT_ORGANIZATION"
    FEDERATION = "FEDERATION"
    PROFESSIONAL_ASSOCIATION = "PROFESSIONAL_ASSOCIATION"
    STUDENT_ORGANIZATION = "STUDENT_ORGANIZATION"
    COMMERCIAL_ENTERPRISE = "COMMERCIAL_ENTERPRISE"
    INTERNAL_PROGRAM = "INTERNAL_PROGRAM"
    ARTICLE_OR_PUBLICATION = "ARTICLE_OR_PUBLICATION"
    DIRECTORY_LISTING = "DIRECTORY_LISTING"
    HISTORICAL_REFERENCE = "HISTORICAL_REFERENCE"
    UNKNOWN = "UNKNOWN"


class GeographicEvidenceStatus(str, Enum):
    """Truthful geographic qualification relative to ICP target market."""

    VERIFIED_LOCAL_PRESENCE = "VERIFIED_LOCAL_PRESENCE"
    VERIFIED_REGIONAL_PRESENCE = "VERIFIED_REGIONAL_PRESENCE"
    NATIONAL_SCOPE = "NATIONAL_SCOPE"
    LOCATION_UNVERIFIED = "LOCATION_UNVERIFIED"
    GEOGRAPHIC_MISMATCH = "GEOGRAPHIC_MISMATCH"


class CurrentActivityStatus(str, Enum):
    """Evidenced temporal/operational status of candidate."""

    CURRENT_ACTIVITY_EVIDENCED = "CURRENT_ACTIVITY_EVIDENCED"
    HISTORICAL_ACTIVITY_ONLY = "HISTORICAL_ACTIVITY_ONLY"
    CURRENT_STATUS_UNKNOWN = "CURRENT_STATUS_UNKNOWN"


@dataclass
class CandidateQualificationResult:
    """Comprehensive qualification assessment outcome for a discovered entity."""

    qualification_status: CandidateQualificationStatus
    entity_archetype: EntityArchetype
    geographic_evidence_status: GeographicEvidenceStatus
    current_activity_status: CurrentActivityStatus
    source_url: str
    source_host: str
    organization_website: Optional[str] = "UNKNOWN"
    is_commercial_review_ready: bool = False
    qualification_reasons: List[str] = field(default_factory=list)
    missing_evidence: List[str] = field(default_factory=list)
    raw_details: Dict[str, Any] = field(default_factory=dict)
