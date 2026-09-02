"""Manual integration test for BopClients P4: Sales Intelligence & Prospect Research."""

import time
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.service import Service
from bopclients.domain.icp import IdealCustomerProfile
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal import Signal
from bopclients.domain.enrichment_result import EnrichmentResult
from bopclients.domain.enums import CampaignStatus
from bopclients.application.providers.deterministic_research_provider import DeterministicResearchProvider
from bopclients.application.research_validation_policy import ResearchValidationPolicy
from bopclients.application.prospect_research_orchestrator import ProspectResearchOrchestrator
from bopclients.application.prospect_research_service import ProspectResearchService
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.repositories.enrichment_result_repository import EnrichmentResultRepository
from bopclients.infrastructure.repositories.prospect_intelligence_repository import ProspectIntelligenceRepository
from bopclients.infrastructure.repositories.service_repository import ServiceRepository
from bopclients.infrastructure.repositories.icp_repository import ICPRepository
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


def run_manual_prospect_research():
    """Manual integration test demonstrating P4 Prospect Research on 2 prospects (High evidence vs Low evidence)."""
    start_time = time.time()
    db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(db)

    org_repo = OrganizationRepository(db)
    camp_repo = CampaignRepository(db)
    prospect_repo = ProspectRepository(db)
    rr_repo = ResearchRunRepository(db)
    res_repo = EnrichmentResultRepository(db)
    intel_repo = ProspectIntelligenceRepository(db)
    service_repo = ServiceRepository(db)
    icp_repo = ICPRepository(db)

    org = org_repo.save(Organization(name="Growth AI Agency", slug="growth-ai"))
    camp = camp_repo.save(org.id, Campaign(name="Miami Dentists Outreach P4", status=CampaignStatus.ACTIVE))

    # Organization Services Sold
    s1 = service_repo.save(org.id, Service(name="Web Development", category="web_development", description="Modern web redesign"))
    s2 = service_repo.save(org.id, Service(name="Automation & AI Chatbot", category="automation", description="Booking & AI assistant"))
    s3 = service_repo.save(org.id, Service(name="Digital Marketing", category="marketing", description="SEO & Analytics setup"))

    # Organization ICP
    icp = icp_repo.save(org.id, IdealCustomerProfile(name="Dental Clinics", industries=["dentist"], countries=["US"]))

    # Prospect 1: High Evidence (Success enrichment with 3 signals)
    p1 = prospect_repo.save_prospect(
        org.id,
        Prospect(name="Miami Dental Group", website_url="https://miamidentalgroup.com", industry="dentist", country="US")
    )
    res_repo.save(
        org.id,
        EnrichmentResult(
            organization_id=org.id,
            prospect_id=p1.id,
            status="success",
            website_url="https://miamidentalgroup.com",
            data={"http_status": 200, "response_time_ms": 2400.0, "ssl_valid": True, "technologies": ["PHP"]}
        )
    )
    prospect_repo.add_signal(org.id, Signal(organization_id=org.id, prospect_id=p1.id, type="website_slow", value="2400ms", confidence=0.6))
    prospect_repo.add_signal(org.id, Signal(organization_id=org.id, prospect_id=p1.id, type="no_chatbot", value="No AI chatbot", confidence=0.9))
    prospect_repo.add_signal(org.id, Signal(organization_id=org.id, prospect_id=p1.id, type="no_booking", value="No booking system", confidence=0.85))

    # Prospect 2: Low Evidence (Timeout enrichment with 0 signals)
    p2 = prospect_repo.save_prospect(
        org.id,
        Prospect(name="Orlando Medical Center", website_url="https://orlandomedical.com", industry="doctor", country="US")
    )
    res_repo.save(
        org.id,
        EnrichmentResult(
            organization_id=org.id,
            prospect_id=p2.id,
            status="timeout",
            website_url="https://orlandomedical.com",
            data={"http_status": None}
        )
    )

    # Initialize P4 Research Pipeline
    provider = DeterministicResearchProvider()
    policy = ResearchValidationPolicy()
    orchestrator = ProspectResearchOrchestrator(
        provider, policy, prospect_repo, rr_repo, res_repo, intel_repo, service_repo, icp_repo
    )
    service = ProspectResearchService(orchestrator, camp_repo, prospect_repo)

    print("\n[MANUAL PROSPECT RESEARCH TEST P4]")
    print("Executing Prospect Research on 2 prospects...\n")

    for idx, prospect in enumerate([p1, p2], 1):
        res = service.research_prospect(org.id, prospect.id, camp.id)
        
        print(f"==================================================")
        print(f"PROSPECT {idx}: {prospect.name}")
        print(f"==================================================")
        print(f"RESEARCH CONFIDENCE: {res.confidence_label.upper()} ({res.confidence:.2f})")
        print(f"\n[EXECUTIVE SUMMARY]\n{res.executive_summary}\n")

        print("[CLAIMS & CLASSIFICATIONS]")
        for c in res.claims:
            print(f"  * [{c.classification.upper()}] {c.statement} (Conf: {c.confidence:.2f}) -> Ev: {c.evidence_refs}")

        print("\n[COMMERCIAL OPPORTUNITIES]")
        if res.commercial_opportunities:
            for opp in res.commercial_opportunities:
                print(f"  * [{opp.priority.upper()}] {opp.title}: {opp.description}")
                print(f"    Services Matched: {opp.matched_services}")
        else:
            print("  (None identified)")

        print("\n[RISKS]")
        for r in res.risks:
            print(f"  ! {r}")
        if not res.risks:
            print("  (None identified)")

        print("\n[UNKNOWNS]")
        for u in res.unknowns:
            print(f"  ? {u}")

        print("\n")

    duration = time.time() - start_time
    print(f"Manual prospect research completed in {duration:.2f}s.\n")


if __name__ == "__main__":
    run_manual_prospect_research()
