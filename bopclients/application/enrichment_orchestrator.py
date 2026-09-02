"""Enrichment Orchestrator executing enrichment pipelines, signal detectors, and opportunity scoring."""

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.research_run import ResearchRun
from bopclients.domain.enrichment_result import EnrichmentResult
from bopclients.domain.exceptions import TenantAccessError, DiscoveryExecutionError
from bopclients.application.enrichment_dto import ProspectAnalysisResult
from bopclients.application.interfaces.enrichment_interfaces import (
    IEnrichmentProvider,
    ISignalDetector,
    IOpportunityScorer,
)
from bopclients.application.interfaces.repositories import (
    IProspectRepository,
    IResearchRunRepository,
    IEnrichmentResultRepository,
    IServiceRepository,
    IICPRepository,
)


class EnrichmentOrchestrator:
    """Orchestrates prospect enrichment, deterministic signal detection, and opportunity scoring."""

    def __init__(
        self,
        enrichment_provider: IEnrichmentProvider,
        signal_detectors: List[ISignalDetector],
        opportunity_scorer: IOpportunityScorer,
        prospect_repo: IProspectRepository,
        research_run_repo: IResearchRunRepository,
        enrichment_result_repo: IEnrichmentResultRepository,
        service_repo: IServiceRepository,
        icp_repo: Optional[IICPRepository] = None,
    ):
        self.enrichment_provider = enrichment_provider
        self.signal_detectors = signal_detectors
        self.opportunity_scorer = opportunity_scorer
        self.prospect_repo = prospect_repo
        self.research_run_repo = research_run_repo
        self.enrichment_result_repo = enrichment_result_repo
        self.service_repo = service_repo
        self.icp_repo = icp_repo

    def analyze_prospect(
        self,
        org_id: str,
        prospect_id: str,
        campaign_id: Optional[str] = None,
    ) -> ProspectAnalysisResult:
        """Enrich a single prospect, detect signals, and calculate opportunity score."""
        prospect = self.prospect_repo.get_prospect_by_id(org_id, prospect_id)
        if not prospect:
            raise TenantAccessError(f"Prospect '{prospect_id}' not found for organization '{org_id}'")

        start_time = datetime.now(timezone.utc).isoformat()

        # 1. Initialize ResearchRun
        run = ResearchRun(
            organization_id=org_id,
            campaign_id=campaign_id,
            prospect_id=prospect_id,
            run_type="enrichment",
            status="pending",
        )
        run = self.research_run_repo.save(org_id, run)
        self.research_run_repo.update_status(org_id, run.id, status="running", started_at=start_time)

        warnings: List[str] = []
        errors: List[str] = []

        try:
            # 2. Execute Enrichment Provider
            snapshot = self.enrichment_provider.enrich(org_id, prospect)
            end_time = datetime.now(timezone.utc).isoformat()

            # 3. Save EnrichmentResult snapshot
            res_entity = EnrichmentResult(
                organization_id=org_id,
                prospect_id=prospect.id,
                provider=self.enrichment_provider.name,
                status=snapshot.scrape_status,
                website_url=snapshot.website_url,
                data=snapshot.raw_metadata or {
                    "emails": snapshot.emails,
                    "technologies": snapshot.technologies,
                    "cms": snapshot.cms,
                    "ssl_valid": snapshot.ssl_valid,
                    "response_time_ms": snapshot.response_time_ms,
                    "http_status": snapshot.http_status,
                },
                started_at=start_time,
                completed_at=end_time,
            )
            self.enrichment_result_repo.save(org_id, res_entity)

            # 4. Run Signal Detectors
            detected_dtos = []
            for detector in self.signal_detectors:
                try:
                    dtos = detector.detect(prospect, snapshot)
                    detected_dtos.extend(dtos)
                except Exception as det_err:
                    warnings.append(f"Detector '{detector.name}' failed: {det_err}")

            # 5. Persist Signals idempotently & Reconcile stale signals on conclusive runs
            detected_types = {dto.type for dto in detected_dtos}
            conclusive_run = snapshot.website_reachable and snapshot.scrape_status in ("success", "partial_timeout")

            if conclusive_run:
                # Remove stale detector-managed signals if conclusive evidence shows condition no longer exists
                existing_signals = self.prospect_repo.list_signals(org_id, prospect.id)
                managed_types = {"no_chatbot", "no_booking", "no_analytics", "no_ssl", "website_slow"}
                for old_sig in existing_signals:
                    if old_sig.type in managed_types and old_sig.type not in detected_types:
                        self.prospect_repo.delete_signal_by_type(org_id, prospect.id, old_sig.type)

            saved_signals: List[Signal] = []
            for dto in detected_dtos:
                sig_entity = Signal(
                    organization_id=org_id,
                    prospect_id=prospect.id,
                    type=dto.type,
                    value=dto.value or "",
                    confidence=dto.confidence,
                    source=dto.source,
                    evidence=dto.evidence,
                )
                saved_sig = self.prospect_repo.add_signal(org_id, sig_entity)
                saved_signals.append(saved_sig)

            # Re-fetch active signals for prospect after reconciliation
            active_signals = self.prospect_repo.list_signals(org_id, prospect.id)

            # 6. Fetch Services & ICP for Opportunity Scoring
            services = self.service_repo.list_by_organization(org_id)
            icps = self.icp_repo.list_by_organization(org_id) if self.icp_repo else []
            icp = icps[0] if icps else None

            # 7. Score Opportunity using active reconciled signals
            score_num, explanation, recommendations = self.opportunity_scorer.score(
                org_id=org_id,
                prospect=prospect,
                signals=active_signals,
                services=services,
                icp=icp,
            )

            lead_score = LeadScore(
                organization_id=org_id,
                prospect_id=prospect.id,
                score=score_num,
                scoring_version="v1.1",
                explanation=explanation,
            )
            saved_score = self.prospect_repo.save_lead_score(org_id, lead_score)

            # 8. Complete ResearchRun
            self.research_run_repo.update_status(
                org_id, run.id, status="completed", completed_at=end_time
            )

            return ProspectAnalysisResult(
                prospect_id=prospect.id,
                research_run_id=run.id,
                enrichment_status=snapshot.scrape_status,
                signals_detected=saved_signals,
                lead_score=saved_score,
                service_recommendations=recommendations,
                warnings=warnings,
                errors=errors,
                started_at=start_time,
                completed_at=end_time,
            )

        except Exception as exc:
            end_time = datetime.now(timezone.utc).isoformat()
            self.research_run_repo.update_status(
                org_id, run.id, status="failed", completed_at=end_time, error_message=str(exc)
            )
            raise DiscoveryExecutionError(f"Prospect enrichment analysis failed: {exc}") from exc
