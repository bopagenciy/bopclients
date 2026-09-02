"""Service orchestrating public signal monitoring across multiple providers with registry routing, semantic event corroboration & failure isolation."""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.domain.research_run import ResearchRun
from bopclients.domain.exceptions import EntityNotFoundError, TenantAccessError
from bopclients.application.signal_provider import IPublicSignalProvider, OfficialWebsiteSignalProvider
from bopclients.application.signal_activation_policy import SignalActivationPolicy
from bopclients.application.signal_monitor_dto import (
    ProspectSignalMonitorResult,
    SignalMonitorPlan,
    PublicSignalDiscoveryResult,
    ProviderValidationLevel,
)
from bopclients.application.provider_registry import PublicSignalProviderRegistry, ProviderApplicabilityPolicy
from bopclients.infrastructure.repositories.signal_observation_repository import SignalObservationRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.application.prospect_priority_service import ProspectPriorityService


class PublicSignalMonitorService:
    """Application service managing multi-provider public signal discovery, deduplication, semantic event corroboration, and signal reconciliation."""

    def __init__(
        self,
        observation_repo: SignalObservationRepository,
        prospect_repo: ProspectRepository,
        campaign_repo: CampaignRepository,
        research_run_repo: ResearchRunRepository,
        activation_policy: Optional[SignalActivationPolicy] = None,
        priority_service: Optional[ProspectPriorityService] = None,
        registry: Optional[PublicSignalProviderRegistry] = None,
        providers: Optional[List[IPublicSignalProvider]] = None,
    ):
        self.observation_repo = observation_repo
        self.prospect_repo = prospect_repo
        self.campaign_repo = campaign_repo
        self.research_run_repo = research_run_repo
        self.activation_policy = activation_policy or SignalActivationPolicy()
        self.priority_service = priority_service

        self.registry = registry or PublicSignalProviderRegistry()
        if providers:
            for prov in providers:
                self.registry.register(prov)

        # Default fallback provider if registry is empty
        if not self.registry.list_all():
            self.registry.register(OfficialWebsiteSignalProvider())

    def monitor_prospect(
        self,
        organization_id: str,
        prospect_id: str,
        country: Optional[str] = None,
        provider_names: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
        recompute_priority: bool = False,
    ) -> ProspectSignalMonitorResult:
        """Monitor public signals for a single prospect with multi-provider routing, semantic event deduplication & failure isolation."""
        prospect = self.prospect_repo.get_prospect_by_id(organization_id, prospect_id)
        if not prospect:
            p = self.prospect_repo._placeholder()
            sql_check = f"SELECT organization_id FROM prospects WHERE id = {p}"
            p_rows = self.prospect_repo.db.fetch_dicts(sql_check, (prospect_id,))
            if p_rows and p_rows[0]["organization_id"] != organization_id:
                raise TenantAccessError(f"Cross-tenant access rejected for prospect '{prospect_id}'")
            raise EntityNotFoundError(f"Prospect '{prospect_id}' not found for tenant '{organization_id}'")

        result = ProspectSignalMonitorResult(
            prospect_id=prospect_id,
            provider="multi_provider",
            checked_at=datetime.now(timezone.utc).isoformat(),
        )

        active_providers = self.registry.list_all()
        if provider_names:
            active_providers = [p for p in active_providers if p.provider_name.lower() in [n.lower() for n in provider_names]]

        all_observations: List[PublicSignalObservation] = []

        # 1. Execute Signal Discovery per Provider with Standardized Statuses
        for prov in active_providers:
            prov_name = prov.provider_name
            caps = prov.capabilities

            if not caps.configured:
                status_code = caps.validation_level if caps.validation_level in ("SKIPPED_NO_KEY", "SKIPPED_NO_BACKEND") else "SKIPPED_NO_KEY"
                warn_msg = f"PROVIDER_NOT_CONFIGURED: Provider '{prov_name}' skipped ({status_code})."
                result.warnings.append(warn_msg)
                result.provider_results[prov_name] = {
                    "status": status_code,
                    "validation_level": caps.validation_level,
                    "observations_found": 0,
                    "observations_created": 0,
                    "signals_activated": 0,
                    "warnings": [warn_msg],
                    "errors": [],
                }
                continue

            is_app, app_reason = ProviderApplicabilityPolicy.is_applicable(prov, prospect, country=country, context=context)
            if not is_app:
                warn_msg = f"Provider '{prov_name}' skipped: {app_reason}"
                result.warnings.append(warn_msg)
                result.provider_results[prov_name] = {
                    "status": "SKIPPED_NOT_APPLICABLE",
                    "validation_level": caps.validation_level,
                    "observations_found": 0,
                    "observations_created": 0,
                    "signals_activated": 0,
                    "warnings": [warn_msg],
                    "errors": [],
                }
                continue

            try:
                disc_res = prov.discover_signals(prospect, context=context)
                result.warnings.extend([f"[{prov_name}] {w}" for w in disc_res.warnings])
                result.errors.extend([f"[{prov_name}] {e}" for e in disc_res.errors])

                prov_obs = disc_res.observations
                for obs in prov_obs:
                    obs.organization_id = organization_id
                    obs.prospect_id = prospect_id
                    all_observations.append(obs)

                status_code = "SUCCESS" if len(prov_obs) > 0 else "SUCCESS_NO_SIGNALS"
                result.provider_results[prov_name] = {
                    "status": status_code,
                    "validation_level": disc_res.validation_level,
                    "observations_found": len(prov_obs),
                    "observations_created": 0,
                    "signals_activated": 0,
                    "warnings": disc_res.warnings,
                    "errors": disc_res.errors,
                }
            except Exception as err:
                err_msg = f"Provider '{prov_name}' failed for prospect '{prospect_id}': {err}"
                result.errors.append(err_msg)
                result.provider_results[prov_name] = {
                    "status": "FAILED",
                    "validation_level": caps.validation_level,
                    "observations_found": 0,
                    "observations_created": 0,
                    "signals_activated": 0,
                    "warnings": [],
                    "errors": [err_msg],
                }

        result.observations_found = len(all_observations)

        # 2. Persist & Deduplicate Observations Idempotently
        saved_observations: List[PublicSignalObservation] = []
        for obs in all_observations:
            existing = self.observation_repo.find_by_fingerprint(
                organization_id, prospect_id, obs.provider, obs.fingerprint
            )
            saved = self.observation_repo.save(organization_id, obs)
            saved_observations.append(saved)
            if existing:
                result.observations_reused += 1
            else:
                result.observations_created += 1

        # 3. Group Observations by SEMANTIC EVENT KEY for Logical Event Corroboration & Activation
        obs_by_event_key: Dict[str, List[PublicSignalObservation]] = {}
        for obs in saved_observations:
            event_key = obs.compute_semantic_event_key()
            obs_by_event_key.setdefault(event_key, []).append(obs)

        for event_key, obs_group in obs_by_event_key.items():
            primary_obs = max(obs_group, key=lambda o: o.confidence)
            supporting_obs = [o for o in obs_group if o.id != primary_obs.id]

            should_activate, signal_obj, act_reason = self.activation_policy.evaluate_activation(
                primary_obs,
                prospect_website_url=prospect.website_url,
                supporting_observations=supporting_obs,
            )
            if should_activate and signal_obj:
                self.prospect_repo.add_signal(organization_id, signal_obj)
                result.signals_activated += 1
                if primary_obs.provider in result.provider_results:
                    result.provider_results[primary_obs.provider]["signals_activated"] += 1

        # 4. Reconcile Expirations on Existing Active Signals
        current_signals = self.prospect_repo.list_signals(organization_id, prospect_id)
        retained_sigs, expired_sigs, exp_reasons = self.activation_policy.reconcile_expirations(
            organization_id, prospect_id, current_signals, saved_observations
        )

        for exp_sig in expired_sigs:
            self.prospect_repo.delete_signal_by_type(organization_id, prospect_id, exp_sig.type)
            result.signals_expired += 1

        if expired_sigs:
            result.warnings.extend([f"Expired signal '{s.type}': {r}" for s, r in zip(expired_sigs, exp_reasons)])

        # 5. Optionally Recompute Priorities for Campaigns Containing this Prospect
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
        country: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
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
                    organization_id, p_id, country=country, context=context, recompute_priority=recompute_priority
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

    def recommend_monitor_plan(
        self, organization_id: str, prospect_id: str, country: Optional[str] = None, context: Optional[Dict[str, Any]] = None
    ) -> SignalMonitorPlan:
        """Recommend customized signal monitoring plan based on prospect, country, and available providers."""
        prospect = self.prospect_repo.get_prospect_by_id(organization_id, prospect_id)
        if not prospect:
            raise EntityNotFoundError(f"Prospect '{prospect_id}' not found for tenant '{organization_id}'")

        applicable = self.registry.resolve_for_prospect(prospect, country=country, context=context)
        prov_names = [p.provider_name for p in applicable]

        return SignalMonitorPlan(
            prospect_id=prospect_id,
            provider_names=prov_names if prov_names else ["official_website"],
            recommended_interval_days=14,
            signals_to_watch=["public_request_for_proposal", "vendor_search", "opened_new_location", "hiring_marketing"],
            reason=f"Recommended monitoring using {len(prov_names)} applicable provider(s) for country '{country or 'GLOBAL'}'",
        )
