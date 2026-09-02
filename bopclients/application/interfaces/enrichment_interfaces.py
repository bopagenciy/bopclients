"""Abstract interfaces for Enrichment Providers, Signal Detectors, and Opportunity Scorers."""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Tuple
from bopclients.domain.prospect import Prospect
from bopclients.domain.service import Service
from bopclients.domain.icp import IdealCustomerProfile
from bopclients.domain.signal import Signal
from bopclients.application.enrichment_dto import (
    EnrichmentSnapshot,
    DetectedSignalDTO,
    ServiceRecommendation,
)


class IEnrichmentProvider(ABC):
    """Abstract enrichment provider fetching public web and technical data for a prospect."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def supports(self, prospect: Prospect) -> bool: ...

    @abstractmethod
    def enrich(self, org_id: str, prospect: Prospect) -> EnrichmentSnapshot: ...


class ISignalDetector(ABC):
    """Abstract signal detector inspecting prospect snapshot to emit commercial signals."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def detect(
        self,
        prospect: Prospect,
        snapshot: EnrichmentSnapshot,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[DetectedSignalDTO]: ...


class IOpportunityScorer(ABC):
    """Abstract opportunity scorer calculating LeadScore (0-100) and Service Recommendations."""

    @abstractmethod
    def score(
        self,
        org_id: str,
        prospect: Prospect,
        signals: List[Signal],
        services: List[Service],
        icp: Optional[IdealCustomerProfile] = None,
    ) -> Tuple[int, str, List[ServiceRecommendation]]: ...
