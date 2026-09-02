"""AI Prospect Research Provider contract adapter stub for future LLM integration."""

from bopclients.application.research_dto import (
    ProspectResearchContext,
    ProspectResearchDraft,
    AIResearchRequest,
    AIResearchResponse,
)
from bopclients.application.interfaces.research_interfaces import (
    IProspectResearchProvider,
    IAIProspectResearchProvider,
)
from bopclients.application.providers.deterministic_research_provider import DeterministicResearchProvider


class AIProspectResearchProviderStub(IAIProspectResearchProvider):
    """Contract adapter stub for future LLM research API integration (Defaults safely to DeterministicProvider)."""

    def __init__(self, fallback_provider: IProspectResearchProvider = None):
        self.fallback_provider = fallback_provider or DeterministicResearchProvider()

    @property
    def name(self) -> str:
        # Returns honest stub provider name if fallback is used
        return f"ai_stub:{self.fallback_provider.name}"

    def generate_ai_research(self, request: AIResearchRequest) -> AIResearchResponse:
        """Contract placeholder for invoking structured LLM research API."""
        return AIResearchResponse(
            executive_summary=f"AI analysis stub for {request.prospect_name}.",
            business_profile_notes=f"Target industry: {request.industry or 'Unknown'}",
            proposed_claims=[],
            proposed_opportunities=[],
            perceived_risks=["LLM integration pending API configuration"],
            perceived_unknowns=["Decision maker unknown"],
        )

    def research(self, context: ProspectResearchContext) -> ProspectResearchDraft:
        """Executes research by delegating safely to deterministic fallback provider."""
        return self.fallback_provider.research(context)
