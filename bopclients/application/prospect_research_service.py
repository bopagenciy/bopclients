"""Application Service managing Prospect Research lifecycle and campaign batch operations."""

from typing import List, Dict, Any, Optional
from bopclients.domain.exceptions import TenantAccessError
from bopclients.application.research_dto import ProspectResearchResult
from bopclients.application.interfaces.research_interfaces import IProspectResearchProvider
from bopclients.application.providers.deterministic_research_provider import DeterministicResearchProvider
from bopclients.application.providers.gemini_research_provider import GeminiProspectResearchProvider
from bopclients.application.prospect_research_orchestrator import ProspectResearchOrchestrator
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository


class ProspectResearchService:
    """High-level application service executing prospect research and batch campaign analysis."""

    def __init__(
        self,
        orchestrator: ProspectResearchOrchestrator,
        campaign_repo: CampaignRepository,
        prospect_repo: ProspectRepository,
    ):
        self.orchestrator = orchestrator
        self.campaign_repo = campaign_repo
        self.prospect_repo = prospect_repo

    def _resolve_provider(self, provider_name: str) -> IProspectResearchProvider:
        """Resolve research provider instance by name. Fails explicitly if unsupported or unconfigured."""
        if provider_name in ("deterministic", "default"):
            return DeterministicResearchProvider()
        elif provider_name in ("gemini", "ai_gemini"):
            return GeminiProspectResearchProvider()
        else:
            raise ValueError(f"Unsupported prospect research provider: '{provider_name}'")

    def research_prospect(
        self,
        org_id: str,
        prospect_id: str,
        campaign_id: Optional[str] = None,
        provider: str = "deterministic",
    ) -> ProspectResearchResult:
        """Research a single prospect for an organization (Defaults safely to deterministic provider)."""
        resolved = self._resolve_provider(provider)
        original_provider = self.orchestrator.research_provider
        try:
            self.orchestrator.research_provider = resolved
            return self.orchestrator.research_prospect(org_id, prospect_id, campaign_id)
        finally:
            self.orchestrator.research_provider = original_provider

    def refresh_research(
        self,
        org_id: str,
        prospect_id: str,
        campaign_id: Optional[str] = None,
        provider: str = "deterministic",
    ) -> ProspectResearchResult:
        """Re-generate research intelligence snapshot for a prospect."""
        return self.research_prospect(org_id, prospect_id, campaign_id, provider=provider)

    def research_campaign(
        self,
        org_id: str,
        campaign_id: str,
        limit: int = 100,
        provider: str = "deterministic",
    ) -> Dict[str, Any]:
        """Batch research all prospects attached to an active campaign."""
        camp = self.campaign_repo.get_campaign(org_id, campaign_id)
        if not camp:
            raise TenantAccessError(f"Campaign '{campaign_id}' not found for organization '{org_id}'")

        prospects = self.prospect_repo.list_prospects_by_campaign(org_id, campaign_id)
        selected = prospects[:limit]

        results: List[ProspectResearchResult] = []
        errors: List[str] = []

        for p in selected:
            try:
                res = self.research_prospect(org_id, p.id, campaign_id, provider=provider)
                results.append(res)
            except Exception as exc:
                errors.append(f"Failed research for prospect '{p.id}': {exc}")

        return {
            "campaign_id": campaign_id,
            "total_prospects": len(selected),
            "succeeded": len(results),
            "failed": len(errors),
            "results": results,
            "errors": errors,
        }
