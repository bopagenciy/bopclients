"""ProspectPriorityService orchestrating prospect prioritization, buying signal discovery, and campaign research actions."""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from bopclients.domain.exceptions import TenantAccessError, EntityNotFoundError
from bopclients.domain.prospect_priority import ProspectPriority, NextResearchAction, OutreachReadiness
from bopclients.domain.research_run import ResearchRun
from bopclients.application.priority_scorer import IPriorityScorer, RuleBasedPriorityScorer
from bopclients.application.signal_provider import IPublicSignalProvider, DeterministicExistingDataSignalProvider
from bopclients.application.research_orchestration_policy import ResearchOrchestrationPolicy
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_priority_repository import ProspectPriorityRepository
from bopclients.infrastructure.repositories.prospect_intelligence_repository import ProspectIntelligenceRepository
from bopclients.infrastructure.repositories.enrichment_result_repository import EnrichmentResultRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository

logger = logging.getLogger("bopclients.application.priority_service")


class ProspectPriorityService:
    """Application service for prospect prioritization, buying signal discovery, and orchestration."""

    def __init__(
        self,
        priority_repo: ProspectPriorityRepository,
        prospect_repo: ProspectRepository,
        campaign_repo: CampaignRepository,
        intel_repo: ProspectIntelligenceRepository,
        enrichment_repo: EnrichmentResultRepository,
        research_run_repo: ResearchRunRepository,
        scorer: Optional[IPriorityScorer] = None,
        signal_provider: Optional[IPublicSignalProvider] = None,
        orchestration_policy: Optional[ResearchOrchestrationPolicy] = None,
    ):
        self.priority_repo = priority_repo
        self.prospect_repo = prospect_repo
        self.campaign_repo = campaign_repo
        self.intel_repo = intel_repo
        self.enrichment_repo = enrichment_repo
        self.research_run_repo = research_run_repo
        self.scorer = scorer or RuleBasedPriorityScorer()
        self.signal_provider = signal_provider or DeterministicExistingDataSignalProvider()
        self.orchestration_policy = orchestration_policy or ResearchOrchestrationPolicy()

    def prioritize_prospect(
        self, organization_id: str, campaign_id: str, prospect_id: str
    ) -> ProspectPriority:
        """Prioritize a single prospect in a campaign with full signal discovery and orchestration."""
        if not organization_id:
            raise TenantAccessError("organization_id is required for prioritization operations.")

        # 1. Fetch prospect (tenant-isolated)
        prospect = self.prospect_repo.get_prospect_by_id(organization_id, prospect_id)
        if not prospect:
            raise EntityNotFoundError(f"Prospect '{prospect_id}' not found for tenant '{organization_id}'.")

        # 2. Fetch campaign (tenant-isolated)
        campaign = self.campaign_repo.get_by_id(organization_id, campaign_id)
        if not campaign:
            raise EntityNotFoundError(f"Campaign '{campaign_id}' not found for tenant '{organization_id}'.")

        # 3. Fetch lead score (tenant-isolated)
        lead_score = self.prospect_repo.get_lead_score(organization_id, prospect_id)

        # 4. Fetch existing signals (tenant-isolated)
        existing_signals = self.prospect_repo.list_signals(organization_id, prospect_id)

        # 5. Fetch enrichment snapshot (tenant-isolated)
        enrichment_result = self.enrichment_repo.get_latest(organization_id, prospect_id)
        enrichment_snap = None
        if enrichment_result and enrichment_result.status == "success":
            from bopclients.application.research_dto import EnrichmentSnapshot
            data_dict = enrichment_result.data if isinstance(enrichment_result.data, dict) else {}
            enrichment_snap = EnrichmentSnapshot(
                scrape_status=data_dict.get("scrape_status", "success"),
                http_status=data_dict.get("http_status", 200),
                technologies=data_dict.get("technologies", []),
                cms=data_dict.get("cms"),
                response_time_ms=data_dict.get("response_time_ms", 0.0),
                updated_at=enrichment_result.updated_at,
            )

        # 6. Fetch contacts (tenant-isolated)
        contacts = self.prospect_repo.list_contacts(organization_id, prospect_id)

        # 7. Discover new public signals
        new_signals = self.signal_provider.discover_signals(
            prospect, existing_signals, enrichment_snap, contacts
        )

        all_signals = list(existing_signals)
        for sig in new_signals:
            if not any(s.type == sig.type for s in all_signals):
                all_signals.append(sig)

        # 8. Fetch latest intelligence (tenant-isolated)
        intelligence = self.intel_repo.get_latest(organization_id, prospect_id)

        # 9. Calculate priority score and label
        priority = self.scorer.calculate_priority(
            organization_id=organization_id,
            campaign_id=campaign_id,
            prospect=prospect,
            lead_score=lead_score,
            signals=all_signals,
            intelligence=intelligence,
            enrichment_snapshot=enrichment_snap,
        )

        # 10. Evaluate orchestration policy for next action and outreach readiness
        next_action, outreach_readiness = self.orchestration_policy.evaluate_orchestration(
            prospect=prospect,
            priority=priority,
            lead_score=lead_score,
            signals=all_signals,
            intelligence=intelligence,
            enrichment_snapshot=enrichment_snap,
            contacts=contacts,
        )

        # Embed orchestration results into priority.data
        priority.data["next_research_action"] = {
            "action": next_action.action,
            "priority": next_action.priority,
            "reason": next_action.reason,
            "not_before": next_action.not_before,
        }
        priority.data["outreach_readiness"] = {
            "status": outreach_readiness.status,
            "reasons": outreach_readiness.reasons,
        }

        # 11. Save idempotent snapshot
        saved_priority = self.priority_repo.save(organization_id, priority)
        return saved_priority

    def prioritize_campaign(
        self, organization_id: str, campaign_id: str, limit: Optional[int] = None
    ) -> Dict[str, Any]:
        """Prioritize all prospects in a campaign in batch with failure isolation."""
        if not organization_id:
            raise TenantAccessError("organization_id is required for prioritization operations.")

        campaign = self.campaign_repo.get_by_id(organization_id, campaign_id)
        if not campaign:
            raise EntityNotFoundError(f"Campaign '{campaign_id}' not found for tenant '{organization_id}'.")

        # Create ResearchRun for prioritization tracking
        run = self.research_run_repo.save(
            organization_id,
            ResearchRun(
                organization_id=organization_id,
                campaign_id=campaign_id,
                run_type="prioritization",
                status="running",
                started_at=datetime.now(timezone.utc).isoformat(),
            ),
        )

        # Fetch enrolled campaign prospects
        prospects = self.prospect_repo.list_prospects_by_campaign(organization_id, campaign_id, limit=limit or 1000)

        items: List[ProspectPriority] = []
        errors: Dict[str, str] = {}

        for p in prospects:
            try:
                prio = self.prioritize_prospect(organization_id, campaign_id, p.id)
                items.append(prio)
            except Exception as err:
                logger.error(f"Failed to prioritize prospect '{p.id}' in campaign '{campaign_id}': {err}")
                errors[p.id] = str(err)

        # Complete ResearchRun
        if len(items) > 0:
            run.status = "completed"
        else:
            run.status = "failed"
        run.completed_at = datetime.now(timezone.utc).isoformat()
        if errors:
            run.error_message = f"Failed prospects: {list(errors.keys())}"
        self.research_run_repo.save(organization_id, run)

        items.sort(key=lambda p: p.priority_score, reverse=True)

        return {
            "campaign_id": campaign_id,
            "total_processed": len(items) + len(errors),
            "successful_count": len(items),
            "failed_count": len(errors),
            "errors": errors,
            "items": items,
            "research_run_id": run.id,
            "policy_version": self.scorer.POLICY_VERSION if hasattr(self.scorer, "POLICY_VERSION") else "v1.0",
        }

    def get_top_prospects(
        self, organization_id: str, campaign_id: str, limit: int = 20
    ) -> List[ProspectPriority]:
        """Fetch top prospects for a campaign ordered by priority_score DESC."""
        return self.priority_repo.get_top_for_campaign(organization_id, campaign_id, limit=limit)

    def get_next_research_action(
        self, organization_id: str, campaign_id: str, prospect_id: str
    ) -> NextResearchAction:
        """Fetch current recommended next research action for a prospect."""
        prio = self.priority_repo.get(organization_id, campaign_id, prospect_id)
        if not prio or "next_research_action" not in prio.data:
            prio = self.prioritize_prospect(organization_id, campaign_id, prospect_id)

        act_data = prio.data.get("next_research_action", {})
        return NextResearchAction(
            action=act_data.get("action", "none"),
            priority=act_data.get("priority", "low"),
            reason=act_data.get("reason", ""),
            not_before=act_data.get("not_before"),
        )
