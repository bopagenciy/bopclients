"""Enrichment application service for single-prospect and campaign-batch analysis."""

from typing import List, Optional
from bopclients.domain.exceptions import TenantAccessError
from bopclients.application.enrichment_dto import ProspectAnalysisResult
from bopclients.application.enrichment_orchestrator import EnrichmentOrchestrator
from bopclients.application.interfaces.repositories import (
    ICampaignRepository,
    IProspectRepository,
)


class EnrichmentService:
    """Application use-case service handling prospect enrichment and batch campaign analysis."""

    def __init__(
        self,
        orchestrator: EnrichmentOrchestrator,
        campaign_repo: ICampaignRepository,
        prospect_repo: IProspectRepository,
    ):
        self.orchestrator = orchestrator
        self.campaign_repo = campaign_repo
        self.prospect_repo = prospect_repo

    def analyze_prospect(
        self, org_id: str, prospect_id: str, campaign_id: Optional[str] = None
    ) -> ProspectAnalysisResult:
        """Analyze and enrich a single prospect with full tenant validation."""
        if campaign_id:
            camp = self.campaign_repo.get_by_id(org_id, campaign_id)
            if not camp:
                raise TenantAccessError(f"Campaign '{campaign_id}' not found for tenant '{org_id}'")

        return self.orchestrator.analyze_prospect(org_id, prospect_id, campaign_id)

    def analyze_campaign(
        self, org_id: str, campaign_id: str, limit: int = 50
    ) -> List[ProspectAnalysisResult]:
        """Analyze a batch of prospects in a campaign, continuing on individual prospect errors."""
        camp = self.campaign_repo.get_by_id(org_id, campaign_id)
        if not camp:
            raise TenantAccessError(f"Campaign '{campaign_id}' not found for tenant '{org_id}'")

        prospects = self.prospect_repo.list_prospects_by_campaign(org_id, campaign_id, limit=limit)
        results: List[ProspectAnalysisResult] = []

        for p in prospects:
            try:
                res = self.orchestrator.analyze_prospect(org_id, p.id, campaign_id)
                results.append(res)
            except Exception as exc:
                # Batch continues on individual prospect failure!
                results.append(
                    ProspectAnalysisResult(
                        prospect_id=p.id,
                        research_run_id="",
                        enrichment_status="failed",
                        errors=[str(exc)],
                    )
                )

        return results
