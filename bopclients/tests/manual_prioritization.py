"""Manual integration test script for BopClients P6 Prospect Prioritization & Research Orchestration."""

from datetime import datetime, timezone, timedelta
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.service import Service
from bopclients.domain.icp import IdealCustomerProfile
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.contact import Contact
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.enrichment_result import EnrichmentResult
from bopclients.domain.prospect_intelligence import ProspectIntelligence
from bopclients.domain.enums import CampaignStatus, SignalType, SignalCategory, IntentStrength
from bopclients.application.priority_scorer import RuleBasedPriorityScorer
from bopclients.application.signal_provider import DeterministicExistingDataSignalProvider
from bopclients.application.research_orchestration_policy import ResearchOrchestrationPolicy
from bopclients.application.prospect_priority_service import ProspectPriorityService
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.prospect_priority_repository import ProspectPriorityRepository
from bopclients.infrastructure.repositories.prospect_intelligence_repository import ProspectIntelligenceRepository
from bopclients.infrastructure.repositories.enrichment_result_repository import EnrichmentResultRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


def run_manual_prioritization_test():
    """Execute 3 controlled prospect prioritization scenarios and print formatted report."""
    print("\n==================================================")
    print("BOPCLIENTS P6 — PROSPECT PRIORITIZATION MANUAL TEST")
    print("==================================================\n")

    db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(db)

    org_repo = OrganizationRepository(db)
    camp_repo = CampaignRepository(db)
    prospect_repo = ProspectRepository(db)
    prio_repo = ProspectPriorityRepository(db)
    intel_repo = ProspectIntelligenceRepository(db)
    res_repo = EnrichmentResultRepository(db)
    rr_repo = ResearchRunRepository(db)

    # 1. Setup Organization, Campaign, and Services
    org = org_repo.save(Organization(name="Priority Growth Agency", slug="prio-agency"))
    camp = camp_repo.save(org.id, Campaign(name="Q3 Growth Campaign", status=CampaignStatus.ACTIVE))

    now_iso = datetime.now(timezone.utc).isoformat()
    old_iso = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()

    # 2. Setup Prospect A: High LeadScore, Recent Verified Buying Intent (RFP), Fresh Research
    p_a = prospect_repo.save_prospect(
        org.id, Prospect(name="Apex Medical Center", website_url="https://apexmedical.com", industry="healthcare")
    )
    prospect_repo.add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p_a.id))
    prospect_repo.save_lead_score(org.id, LeadScore(organization_id=org.id, prospect_id=p_a.id, score=85))
    prospect_repo.add_contact(org.id, Contact(organization_id=org.id, prospect_id=p_a.id, name="Dr. Robert Smith", title="Medical Director"))
    res_repo.save(
        org.id,
        EnrichmentResult(
            organization_id=org.id,
            prospect_id=p_a.id,
            status="success",
            website_url="https://apexmedical.com",
            data={"http_status": 200, "technologies": ["WordPress", "Google Analytics"]},
            started_at=now_iso,
            completed_at=now_iso,
        )
    )
    prospect_repo.add_signal(
        org.id,
        Signal(
            organization_id=org.id,
            prospect_id=p_a.id,
            type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            category=SignalCategory.BUYING_INTENT.value,
            intent_strength=IntentStrength.STRONG.value,
            confidence=0.95,
            source="public_rfp_registry",
            evidence={"rfp_title": "RFP for Medical Marketing Agency", "url": "https://apexmedical.com/rfp"},
            detected_at=now_iso,
        )
    )
    prospect_repo.add_signal(
        org.id,
        Signal(
            organization_id=org.id,
            prospect_id=p_a.id,
            type=SignalType.HIRING_MARKETING.value,
            category=SignalCategory.COMPANY_ACTIVITY.value,
            intent_strength=IntentStrength.MEDIUM.value,
            confidence=0.90,
            source="jobs_page",
            evidence={"title": "Marketing Coordinator"},
            detected_at=now_iso,
        )
    )
    intel_repo.save(
        org.id,
        ProspectIntelligence(
            organization_id=org.id,
            prospect_id=p_a.id,
            provider="deterministic",
            confidence=0.85,
            data={"summary": "Verified growth clinic expanding operations."},
            created_at=now_iso,
            updated_at=now_iso,
        )
    )

    # 3. Setup Prospect B: High LeadScore, Stale Research (45d), Need Signals Only (No Intent)
    p_b = prospect_repo.save_prospect(
        org.id, Prospect(name="Beacon Dental Partners", website_url="https://beacondental.com", industry="dentist")
    )
    prospect_repo.add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p_b.id))
    prospect_repo.save_lead_score(org.id, LeadScore(organization_id=org.id, prospect_id=p_b.id, score=80))
    res_repo.save(
        org.id,
        EnrichmentResult(
            organization_id=org.id,
            prospect_id=p_b.id,
            status="success",
            website_url="https://beacondental.com",
            data={"http_status": 200, "technologies": ["Squarespace"]},
            started_at=old_iso,
            completed_at=old_iso,
        )
    )
    prospect_repo.add_signal(
        org.id,
        Signal(
            organization_id=org.id,
            prospect_id=p_b.id,
            type=SignalType.NO_BOOKING.value,
            category=SignalCategory.NEED.value,
            intent_strength=IntentStrength.NONE.value,
            confidence=0.80,
            detected_at=old_iso,
        )
    )
    intel_repo.save(
        org.id,
        ProspectIntelligence(
            organization_id=org.id,
            prospect_id=p_b.id,
            provider="deterministic",
            confidence=0.40,
            data={"summary": "Stale evidence research snapshot."},
            created_at=old_iso,
            updated_at=old_iso,
        )
    )

    # 4. Setup Prospect C: Low LeadScore, Moderate Confidence, No Intent Signals
    p_c = prospect_repo.save_prospect(
        org.id, Prospect(name="Crestline Auto Repair", website_url="https://crestlineauto.com", industry="auto")
    )
    prospect_repo.add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p_c.id))
    prospect_repo.save_lead_score(org.id, LeadScore(organization_id=org.id, prospect_id=p_c.id, score=35))
    res_repo.save(
        org.id,
        EnrichmentResult(
            organization_id=org.id,
            prospect_id=p_c.id,
            status="success",
            website_url="https://crestlineauto.com",
            data={"http_status": 200},
            started_at=now_iso,
            completed_at=now_iso,
        )
    )
    intel_repo.save(
        org.id,
        ProspectIntelligence(
            organization_id=org.id,
            prospect_id=p_c.id,
            provider="deterministic",
            confidence=0.60,
            data={"summary": "Auto repair shop."},
            created_at=now_iso,
            updated_at=now_iso,
        )
    )

    # 5. Run Priority Service Batch Prioritization
    service = ProspectPriorityService(
        priority_repo=prio_repo,
        prospect_repo=prospect_repo,
        campaign_repo=camp_repo,
        intel_repo=intel_repo,
        enrichment_repo=res_repo,
        research_run_repo=rr_repo,
    )

    result = service.prioritize_campaign(org.id, camp.id)
    top_prospects = result["items"]

    # 6. Print Formatted Report
    for idx, prio in enumerate(top_prospects, 1):
        p_obj = prospect_repo.get_prospect_by_id(org.id, prio.prospect_id)
        ls_obj = prospect_repo.get_lead_score(org.id, prio.prospect_id)
        intel_obj = intel_repo.get_latest(org.id, prio.prospect_id)

        considered = prio.data.get("considered_signals", {})
        need_sigs = considered.get("need", [])
        act_sigs = considered.get("company_activity", [])
        intent_sigs = considered.get("buying_intent", [])

        contribs = prio.data.get("contributing_signals", {})
        bd = prio.data.get("component_breakdown", {})

        next_act = prio.data.get("next_research_action", {})
        readiness = prio.data.get("outreach_readiness", {})

        print(f"RANK #{idx}: {p_obj.name.upper()}")
        print(f"  LEAD SCORE                          : {ls_obj.score if ls_obj else 0}/100")
        print(f"  RESEARCH CONFIDENCE                 : {intel_obj.confidence:.2f}" if intel_obj else "  RESEARCH CONFIDENCE                 : None")
        print(f"  NEED SIGNALS CONSIDERED             : {need_sigs}")
        print(f"  COMPANY ACTIVITY SIGNALS CONSIDERED : {act_sigs}")
        print(f"  BUYING INTENT SIGNALS CONSIDERED    : {intent_sigs}")
        print("  CONTRIBUTING SIGNALS                :")
        for cat, items in contribs.items():
            if items:
                print(f"    - [{cat.upper()}] : {[i['type'] + ' (raw ' + str(i['raw_contribution']) + ')' for i in items]}")
            else:
                print(f"    - [{cat.upper()}] : None")
        print("  COMPONENT BREAKDOWN                 :")
        for k, v in bd.items():
            print(f"    - {k:25s}: raw {v['raw_total']:.1f} / applied {v['applied_total']:.1f} (cap {v['cap']:.1f}, cap_applied={v['cap_applied']})")
        print(f"  PRIORITY SCORE                      : {prio.priority_score}/100")
        print(f"  PRIORITY LABEL                      : {prio.priority_label.upper()}")
        print("  REASONS                             :")
        for r in prio.data.get("reasons", []):
            print(f"    * [{r.get('factor')}] {r.get('reason')}")
        print(f"  NEXT RESEARCH ACTION                : [{next_act.get('priority', 'low').upper()}] {next_act.get('action')}")
        print(f"                                        Reason: {next_act.get('reason')}")
        print(f"  OUTREACH READINESS                  : [{readiness.get('status', 'not_ready').upper()}]")
        for rea in readiness.get("reasons", []):
            print(f"                                        * {rea}")
        print("--------------------------------------------------\n")

    print(f"PRIORITIZATION BATCH SUCCESSFUL: {result['successful_count']}/{result['total_processed']} prospects prioritized.")
    print("==================================================\n")


if __name__ == "__main__":
    run_manual_prioritization_test()
