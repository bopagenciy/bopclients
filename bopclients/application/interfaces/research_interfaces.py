"""Abstract interfaces for P4 Prospect Research providers and AI adapters."""

from abc import ABC, abstractmethod
from bopclients.application.research_dto import (
    ProspectResearchContext,
    ProspectResearchDraft,
    AIResearchRequest,
    AIResearchResponse,
)


class IProspectResearchProvider(ABC):
    """Interface for sales research providers generating structured ProspectResearchDrafts."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identification string, e.g., 'deterministic' or 'ai_gemini'."""
        ...

    @abstractmethod
    def research(self, context: ProspectResearchContext) -> ProspectResearchDraft:
        """Analyze prospect context and produce evidence-backed research draft."""
        ...


class IAIProspectResearchProvider(IProspectResearchProvider):
    """Interface adapter contract for future external LLM API research providers."""

    @abstractmethod
    def generate_ai_research(self, request: AIResearchRequest) -> AIResearchResponse:
        """Invoke external LLM provider with structured request payload."""
        ...
