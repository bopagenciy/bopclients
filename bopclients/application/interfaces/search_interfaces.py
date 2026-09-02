"""Abstract interfaces for Search Intent Parsing, Search Planning, Location Resolution, and Discovery Providers."""

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from bopclients.domain.search_intent import SearchIntent
from bopclients.application.search_dto import (
    SearchPlan,
    DiscoveryTask,
    ResolvedLocation,
)
from bopclients.application.interfaces.forge_gateways import DiscoveredBusiness


class ISearchIntentParser(ABC):
    """Abstract parser translating natural language queries into structured SearchIntent."""

    @abstractmethod
    def parse(
        self,
        organization_id: str,
        campaign_id: Optional[str],
        raw_query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> SearchIntent: ...


class IAISearchIntentParser(ISearchIntentParser, ABC):
    """Interface placeholder for future LLM/AI-driven Search Intent Parser."""

    pass


class ILocationResolver(ABC):
    """Abstract geographical location resolver."""

    @abstractmethod
    def resolve(
        self,
        country: str,
        region: Optional[str] = None,
        city: Optional[str] = None,
        postal_code: Optional[str] = None,
    ) -> Optional[ResolvedLocation]: ...


class ISearchPlanner(ABC):
    """Abstract search planner converting SearchIntent into an executable SearchPlan."""

    @abstractmethod
    def plan(self, intent: SearchIntent) -> SearchPlan: ...


class IDiscoveryProvider(ABC):
    """Abstract discovery provider executing individual DiscoveryTasks."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def supports(self, task: DiscoveryTask) -> bool: ...

    @abstractmethod
    def discover(self, task: DiscoveryTask) -> List[DiscoveredBusiness]: ...
