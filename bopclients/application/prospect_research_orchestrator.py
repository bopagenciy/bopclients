"""Prospect Research Orchestrator executing sales intelligence generation, policy validation, and persistence."""

import json
import hashlib
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from bopclients.domain.research_run import ResearchRun
from bopclients.domain.prospect_intelligence import ProspectIntelligence
from bopclients.domain.service import Service
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.exceptions import TenantAccessError, DiscoveryExecutionError, AIResearchError
from bopclients.application.enrichment_dto import EnrichmentSnapshot
from bopclients.application.research_dto import (
    ProspectResearchContext,
    ProspectResearchResult,
    ResearchClaim,
    CommercialOpportunity,
)
from bopclients.application.interfaces.research_interfaces import IProspectResearchProvider
from bopclients.application.research_validation_policy import ResearchValidationPolicy
from bopclients.application.interfaces.repositories import (
    IProspectRepository,
    IResearchRunRepository,
    IEnrichmentResultRepository,
    IProspectIntelligenceRepository,
    IServiceRepository,
    IICPRepository,
)


def compute_services_fingerprint(services: List[Service]) -> str:
    """Compute deterministic SHA-256 fingerprint of active organization services."""
    active_tuples = sorted([(s.id, s.category or s.name) for s in services if getattr(s, 'active', True)])
    raw = json.dumps(active_tuples, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def compute_signals_fingerprint(signals: List[Signal]) -> str:
    """Compute deterministic SHA-256 fingerprint of prospect signals."""
    sig_tuples = sorted([(s.type, float(s.confidence), str(s.value or '')) for s in signals])
    raw = json.dumps(sig_tuples, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def compute_lead_score_fingerprint(lead_score: Optional[LeadScore]) -> Optional[str]:
    """Compute deterministic SHA-256 fingerprint of prospect lead score."""
    if not lead_score:
        return None
    raw = f"{lead_score.score}:{lead_score.scoring_version}:{lead_score.explanation or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class ProspectResearchOrchestrator:
    """Orchestrates prospect research generation, evidence validation, and intelligence snapshot persistence."""

    def __init__(
        self,
        research_provider: IProspectResearchProvider,
        validation_policy: ResearchValidationPolicy,
        prospect_repo: IProspectRepository,
        research_run_repo: IResearchRunRepository,
        enrichment_result_repo: IEnrichmentResultRepository,
        prospect_intel_repo: IProspectIntelligenceRepository,
        service_repo: IServiceRepository,
        icp_repo: Optional[IICPRepository] = None,
    ):
        self.research_provider = research_provider
        self.validation_policy = validation_policy
        self.prospect_repo = prospect_repo
        self.research_run_repo = research_run_repo
        self.enrichment_result_repo = enrichment_result_repo
        self.prospect_intel_repo = prospect_intel_repo
        self.service_repo = service_repo
        self.icp_repo = icp_repo

    def research_prospect(
        self,
        org_id: str,
        prospect_id: str,
        campaign_id: Optional[str] = None,
    ) -> ProspectResearchResult:
        """Generate evidence-backed sales research intelligence for a single prospect."""
        prospect = self.prospect_repo.get_prospect_by_id(org_id, prospect_id)
        if not prospect:
            raise TenantAccessError(f"Prospect '{prospect_id}' not found for organization '{org_id}'")

        start_time = datetime.now(timezone.utc).isoformat()

        # 1. Initialize ResearchRun
        run = ResearchRun(
            organization_id=org_id,
            campaign_id=campaign_id,
            prospect_id=prospect_id,
            run_type="prospect_research",
            status="pending",
        )
        run = self.research_run_repo.save(org_id, run)
        self.research_run_repo.update_status(org_id, run.id, status="running", started_at=start_time)

        try:
            # 2. Gather Context (EnrichmentResult, Signals, LeadScore, Services, ICP, Contacts, Sources)
            latest_enrich = self.enrichment_result_repo.get_latest(org_id, prospect_id)
            snapshot = None
            if latest_enrich:
                data = latest_enrich.data or {}
                snapshot = EnrichmentSnapshot(
                    prospect_id=prospect_id,
                    website_url=latest_enrich.website_url,
                    website_reachable=(latest_enrich.status == "success"),
                    scrape_status=latest_enrich.status,
                    http_status=data.get("http_status"),
                    response_time_ms=data.get("response_time_ms"),
                    ssl_valid=data.get("ssl_valid"),
                    emails=data.get("emails", []),
                    technologies=data.get("technologies", []),
                    cms=data.get("cms"),
                    provider=latest_enrich.provider,
                )

            signals = self.prospect_repo.list_signals(org_id, prospect_id)
            lead_score = self.prospect_repo.get_lead_score(org_id, prospect_id)
            services = self.service_repo.list_by_organization(org_id)
            icps = self.icp_repo.list_by_organization(org_id) if self.icp_repo else []
            icp = icps[0] if icps else None
            contacts = self.prospect_repo.list_contacts(org_id, prospect_id)
            sources = self.prospect_repo.list_prospect_sources(org_id, prospect_id)

            ctx = ProspectResearchContext(
                organization_id=org_id,
                prospect=prospect,
                enrichment_snapshot=snapshot,
                signals=signals,
                lead_score=lead_score,
                services=services,
                icp=icp,
                contacts=contacts,
                sources=sources,
            )

            # Build allowed references for validation
            allowed_ev = [f"signal:{s.type}" for s in signals]
            allowed_src = [f"provider:{s.source}" for s in signals]
            if snapshot:
                allowed_src.append(f"enrichment:{prospect_id}")
            allowed_svc = [s.category or s.name for s in services if getattr(s, 'active', True)] + [s.name for s in services if getattr(s, 'active', True)]
            sig_conf_map = {f"signal:{s.type}": s.confidence for s in signals}

            # 3. Execute Research Provider
            draft = self.research_provider.research(ctx)

            # 4. Validate Draft via ResearchValidationPolicy
            sanitized_draft, warnings, rejected_claims = self.validation_policy.validate(
                draft,
                verified_contacts=contacts,
                allowed_evidence_refs=allowed_ev,
                allowed_source_refs=allowed_src,
                allowed_service_ids=allowed_svc,
                signal_confidence_map=sig_conf_map,
            )

            # 5. Persist ProspectIntelligence snapshot with deterministic fingerprints
            latest_sig_time = max((s.detected_at for s in signals), default=None)
            usage_meta = getattr(draft, "usage_metadata", None)

            intel_data = {
                "executive_summary": sanitized_draft.executive_summary,
                "business_profile": sanitized_draft.business_profile,
                "claims": [
                    {
                        "id": c.id,
                        "claim_type": c.claim_type,
                        "statement": c.statement,
                        "classification": c.classification,
                        "confidence": c.confidence,
                        "evidence_refs": c.evidence_refs,
                        "source_refs": c.source_refs,
                    }
                    for c in sanitized_draft.claims
                ],
                "commercial_opportunities": [
                    {
                        "opportunity_type": o.opportunity_type,
                        "title": o.title,
                        "description": o.description,
                        "confidence": o.confidence,
                        "supporting_signals": o.supporting_signals,
                        "supporting_claims": o.supporting_claims,
                        "matched_services": o.matched_services,
                        "priority": o.priority,
                    }
                    for o in sanitized_draft.commercial_opportunities
                ],
                "risks": sanitized_draft.risks,
                "unknowns": sanitized_draft.unknowns,
                "usage_metadata": usage_meta,
                "ai_provider": "gemini" if "gemini" in self.research_provider.name else self.research_provider.name,
                "ai_model": getattr(self.research_provider, "config", None).model if hasattr(self.research_provider, "config") else "deterministic",
                "api_mode": getattr(self.research_provider, "API_MODE", "deterministic"),
                "prompt_version": "v1",
                "research_version": "v1.0",
                "generated_from": {
                    "enrichment_updated_at": latest_enrich.completed_at if latest_enrich else None,
                    "signals_latest_at": latest_sig_time,
                    "active_signals_fingerprint": compute_signals_fingerprint(signals),
                    "lead_score_fingerprint": compute_lead_score_fingerprint(lead_score),
                    "active_services_fingerprint": compute_services_fingerprint(services),
                    "services_count": len(services),
                },
            }

            intel_entity = ProspectIntelligence(
                organization_id=org_id,
                prospect_id=prospect_id,
                provider=self.research_provider.name,
                research_version="v1.0",
                confidence=sanitized_draft.overall_confidence,
                data=intel_data,
            )
            self.prospect_intel_repo.save(org_id, intel_entity)

            # 6. Complete ResearchRun
            end_time = datetime.now(timezone.utc).isoformat()
            self.research_run_repo.update_status(org_id, run.id, status="completed", completed_at=end_time)

            return ProspectResearchResult(
                prospect_id=prospect_id,
                research_run_id=run.id,
                provider=self.research_provider.name,
                executive_summary=sanitized_draft.executive_summary,
                business_profile=sanitized_draft.business_profile,
                claims=sanitized_draft.claims,
                commercial_opportunities=sanitized_draft.commercial_opportunities,
                recommended_services=sanitized_draft.recommended_services,
                risks=sanitized_draft.risks,
                unknowns=sanitized_draft.unknowns,
                confidence=sanitized_draft.overall_confidence,
                confidence_label=sanitized_draft.confidence_label,
                research_version="v1.0",
                warnings=warnings,
                created_at=end_time,
            )

        except Exception as exc:
            end_time = datetime.now(timezone.utc).isoformat()
            self.research_run_repo.update_status(
                org_id, run.id, status="failed", completed_at=end_time, error_message=str(exc)
            )
            if isinstance(exc, (TenantAccessError, AIResearchError)):
                raise
            raise DiscoveryExecutionError(f"Prospect research failed: {exc}") from exc


def is_intelligence_stale(
    intelligence: Optional[ProspectIntelligence],
    latest_enrichment_completed_at: Optional[str] = None,
    latest_signal_detected_at: Optional[str] = None,
    current_signals: Optional[List[Signal]] = None,
    lead_score: Optional[LeadScore] = None,
    current_services: Optional[List[Service]] = None,
) -> bool:
    """Determine if a ProspectIntelligence snapshot is stale using timestamp comparisons and fingerprints."""
    if not intelligence:
        return True

    gf = (intelligence.data or {}).get("generated_from", {})

    if latest_enrichment_completed_at and gf.get("enrichment_updated_at") != latest_enrichment_completed_at:
        if latest_enrichment_completed_at > intelligence.created_at:
            return True

    if latest_signal_detected_at and gf.get("signals_latest_at") != latest_signal_detected_at:
        if latest_signal_detected_at > intelligence.created_at:
            return True

    if current_signals is not None:
        if gf.get("active_signals_fingerprint") != compute_signals_fingerprint(current_signals):
            return True

    if lead_score is not None:
        if gf.get("lead_score_fingerprint") != compute_lead_score_fingerprint(lead_score):
            return True

    if current_services is not None:
        if gf.get("active_services_fingerprint") != compute_services_fingerprint(current_services):
            return True

    return False
