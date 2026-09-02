"""PublicSignalMonitorService orchestrating signal discovery, observation persistence, activation, and expiration."""

from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from bopclients.domain.research_run import ResearchRun
from bopclients.domain.exceptions import TenantAccessError, EntityNotFoundError
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.application.signal_monitor_dto import (
    ProspectSignalMonitorResult,
    PublicSignalDiscoveryResult,
    SignalMonitorPlan,
)
from bopclients.application.signal_provider import IPublicSignalProvider, OfficialWebsiteSignalProvider
from bopclients.application.signal_activation_policy import SignalActivationPolicy
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.signal_observation_repository import SignalObservationRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.application.prospect_priority_service import ProspectPriorityService


class PublicSignalMonitorService:
    """Service orchestrating public signal monitoring across providers with complete tenant boundary safety."""

    def __init__(
        self,
        observation_repo: SignalObservationRepository,
        prospect_repo: ProspectRepository,
        campaign_repo: CampaignRepository,
        research_run_repo: ResearchRunRepository,
        priority_service: Optional[ProspectPriorityService] = None,
        providers: Optional[List[IPublicSignalProvider]] = None,
        activation_policy: Optional[SignalActivationPolicy] = None,
    ):
        self.observation_repo = observation_repo
        self.prospect_repo = prospect_repo
        self.campaign_repo = campaign_repo
        self.research_run_repo = research_run_repo
        self.priority_service = priority_service
        self.providers = providers or [OfficialWebsiteSignalProvider()]
        self.activation_policy = activation_policy or SignalActivationPolicy()

    def monitor_prospect(
        self,
        organization_id: str,
        prospect_id: str,
        providers: Optional[List[IPublicSignalProvider]] = None,
        recompute_priority: bool = False,
    ) -> ProspectSignalMonitorResult:
        """Monitor public signals for a single prospect with provider failure isolation."""
        prospect = self.prospect_repo.get_prospect_by_id(organization_id, prospect_id)
        if not prospect:
            raise EntityNotFoundError(f"Prospect '{prospect_id}' not found for tenant '{organization_id}'")

        now_iso = datetime.now(timezone.utc).isoformat()
        active_providers = providers or self.providers
        result = ProspectSignalMonitorResult(
            prospect_id=prospect_id, provider="multi_provider", checked_at=now_iso
        )

        all_observations: List[PublicSignalObservation] = []

        # 1. Discover observations from each provider independently
        for prov in active_providers:
            try:
                disc_res: PublicSignalDiscoveryResult = prov.discover_signals(prospect)
                result.warnings.extend(disc_res.warnings)
                result.errors.extend(disc_res.errors)

                for obs in disc_res.observations:
                    obs.organization_id = organization_id
                    all_observations.append(obs)
            except Exception as err:
                result.errors.append(f"Provider '{prov.provider_name}' failed for prospect '{prospect_id}': {err}")

        result.observations_found = len(all_observations)

        # 2. Persist & deduplicate observations idempotently
        for obs in all_observations:
            existing = self.observation_repo.find_by_fingerprint(
                organization_id, prospect_id, obs.provider, obs.fingerprint
            )
            saved = self.observation_repo.save(organization_id, obs)
            if existing:
                result.observations_reused += 1
            else:
                result.observations_created += 1

            # 3. Evaluate Activation Policy
            should_activate, signal_obj, act_reason = self.activation_policy.evaluate_activation(
                saved, prospect_website_url=prospect.website_url
            )
            if should_activate and signal_obj:
                self.prospect_repo.add_signal(organization_id, signal_obj)
                result.signals_activated += 1

        # 4. Reconcile Expirations on existing active Signals
        current_signals = self.prospect_repo.list_signals(organization_id, prospect_id)
        retained_sigs, expired_sigs, exp_reasons = self.activation_policy.reconcile_expirations(
            organization_id, prospect_id, current_signals, all_observations
        )

        for exp_sig in expired_sigs:
            self.prospect_repo.delete_signal_by_type(organization_id, prospect_id, exp_sig.type)
            result.signals_expired += 1

        if expired_sigs:
            result.warnings.extend([f"Expired signal '{s.type}': {r}" for s, r in zip(expired_sigs, exp_reasons)])

        # 5. Optionally recompute priorities for campaigns containing this prospect
        if recompute_priority and self.priority_service:
            camp_prospects = self.prospect_repo.list_prospect_campaigns(organization_id, prospect_id)
            for cp in camp_prospects:
                try:
                    self.priority_service.prioritize_prospect(organization_id, cp.campaign_id, prospect_id)
                except Exception as p_err:
                    result.warnings.append(f"Priority recomputation failed for campaign '{cp.campaign_id}': {p_err}")

        return result

    def monitor_campaign(
        self,
        organization_id: str,
        campaign_id: str,
        limit: Optional[int] = None,
        recompute_priority: bool = False,
    ) -> Dict[str, Any]:
        """Monitor public signals for all prospects in a campaign with failure isolation & ResearchRun tracking."""
        campaign = self.campaign_repo.get_by_id(organization_id, campaign_id)
        if not campaign:
            raise EntityNotFoundError(f"Campaign '{campaign_id}' not found for tenant '{organization_id}'")

        cps = self.prospect_repo.list_prospects_by_campaign(organization_id, campaign_id)
        if limit:
            cps = cps[:limit]

        run = self.research_run_repo.save(
            organization_id,
            ResearchRun(
                organization_id=organization_id,
                campaign_id=campaign_id,
                run_type="signal_monitoring",
                status="running",
            ),
        )

        successful_count = 0
        failed_count = 0
        errors_dict: Dict[str, str] = {}
        monitor_results: List[ProspectSignalMonitorResult] = []

        for cp in cps:
            p_id = getattr(cp, "prospect_id", cp.id)
            try:
                mon_res = self.monitor_prospect(
                    organization_id, p_id, recompute_priority=recompute_priority
                )
                monitor_results.append(mon_res)
                successful_count += 1
            except Exception as err:
                failed_count += 1
                errors_dict[p_id] = str(err)

        run.status = "completed" if successful_count > 0 else "failed"
        run.completed_at = datetime.now(timezone.utc).isoformat()

        if errors_dict:
            run.error_message = f"Batch finished with {failed_count} errors out of {len(cps)} prospects."

        self.research_run_repo.save(organization_id, run)

        return {
            "research_run_id": run.id,
            "status": run.status,
            "total_processed": len(cps),
            "successful_count": successful_count,
            "failed_count": failed_count,
            "results": monitor_results,
            "errors": errors_dict,
        }

    def recommend_monitor_plan(self, organization_id: str, prospect_id: str) -> SignalMonitorPlan:
        """Generate a monitoring plan recommendation DTO for a prospect."""
        prospect = self.prospect_repo.get_prospect_by_id(organization_id, prospect_id)
        if not prospect:
            raise EntityNotFoundError(f"Prospect '{prospect_id}' not found for tenant '{organization_id}'")

        prov_names = [p.provider_name for p in self.providers]
        signals_to_watch = [
            "public_request_for_proposal",
            "vendor_search",
            "hiring_marketing",
            "hiring_sales",
            "opened_new_location",
            "recent_website_change",
        ]

        return SignalMonitorPlan(
            prospect_id=prospect_id,
            provider_names=prov_names,
            recommended_interval_days=14,
            signals_to_watch=signals_to_watch,
            reason="Official website monitoring for RFP, vendor search, and growth activity signals.",
        )
