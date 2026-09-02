"""Abstract gateway contract separating BopClients SaaS product layer from FORGE engine."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Dict, Any


@dataclass
class DiscoveryQuery:
    """Query parameters for FORGE discovery engine."""

    zip_code: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    radius_miles: float = 10.0
    industry: Optional[str] = None
    limit: int = 1000


@dataclass
class DiscoveredBusiness:
    """Standardized business record returned from FORGE discovery engine."""

    overture_id: str
    name: str
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phone: Optional[str] = None
    website_url: Optional[str] = None
    category: Optional[str] = None
    forge_industry: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None


@dataclass
class EnrichmentTask:
    """Enrichment request for a set of business records."""

    business_records: List[Dict[str, Any]]
    mode: str = "email"  # "email", "ai", "both"
    workers: int = 5


class IForgeDiscoveryGateway(ABC):
    """Gateway interface for discovering business targets via FORGE engine."""

    @abstractmethod
    def discover_businesses(self, query: DiscoveryQuery) -> List[DiscoveredBusiness]: ...


class IForgeEnrichmentGateway(ABC):
    """Gateway interface for enriching prospect records via FORGE engine."""

    @abstractmethod
    def enrich_batch(self, task: EnrichmentTask) -> List[Dict[str, Any]]: ...
