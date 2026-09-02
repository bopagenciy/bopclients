"""Manual integration test script for BopClients P5 Google Gemini Prospect Research."""

import os
import sys
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.service import Service
from bopclients.domain.icp import IdealCustomerProfile
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal import Signal
from bopclients.domain.enrichment_result import EnrichmentResult
from bopclients.domain.enums import CampaignStatus
from bopclients.application.ai_config import AIResearchConfig
from bopclients.application.providers.gemini_research_provider import GeminiProspectResearchProvider
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


def run_manual_gemini_research():
    """Execute live manual Gemini API prospect research if GEMINI_API_KEY is present."""
    config = AIResearchConfig()
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()

    print("\n[MANUAL GEMINI RESEARCH TEST P5.3]")
    print(f"MODEL: {config.model}")
    print("API MODE: generateContent_legacy")
    print("STRUCTURED OUTPUT: JSON Schema")
    print(f"PROVIDER: gemini:{config.model}")

    if not api_key:
        print("RESULT: SKIPPED_NO_KEY (GEMINI_API_KEY is not set in environment).\n")
        return

    print("\nGEMINI_API_KEY detected. Executing 1 controlled prospect research against Google Gemini API...\n")

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

    org = org_repo.save(Organization(name="Gemini Live Agency", slug="gemini-live"))
    camp = camp_repo.save(org.id, Campaign(name="Gemini Outreach Campaign", status=CampaignStatus.ACTIVE))

    service_repo.save(org.id, Service(name="Web Development", category="web_development"))
    service_repo.save(org.id, Service(name="Automation & AI Chatbot", category="automation"))

    icp_repo.save(org.id, IdealCustomerProfile(name="Medical & Dental Clinics", industries=["dentist"], countries=["US"]))

    p = prospect_repo.save_prospect(
        org.id,
        Prospect(name="Biscayne Dental Center", website_url="https://biscaynedental.com", industry="dentist", country="US")
    )
    res_repo.save(
        org.id,
        EnrichmentResult(
            organization_id=org.id,
            prospect_id=p.id,
            status="success",
            website_url="https://biscaynedental.com",
            data={"http_status": 200, "response_time_ms": 2300.0, "ssl_valid": True}
        )
    )
    prospect_repo.add_signal(org.id, Signal(organization_id=org.id, prospect_id=p.id, type="no_booking", confidence=0.85))
    prospect_repo.add_signal(org.id, Signal(organization_id=org.id, prospect_id=p.id, type="no_chatbot", confidence=0.90))

    provider = GeminiProspectResearchProvider(config=config)
    policy = ResearchValidationPolicy()
    orchestrator = ProspectResearchOrchestrator(
        provider, policy, prospect_repo, rr_repo, res_repo, intel_repo, service_repo, icp_repo
    )
    service = ProspectResearchService(orchestrator, camp_repo, prospect_repo)

    res = service.research_prospect(org.id, p.id, camp.id, provider="gemini")

    print(f"==================================================")
    print(f"PROSPECT: {p.name}")
    print(f"==================================================")
    print(f"PROVIDER PROVENANCE: {res.provider}")
    print(f"RESEARCH CONFIDENCE: {res.confidence_label.upper()} ({res.confidence:.2f})")
    print(f"USAGE METADATA: {res.usage_metadata}")
    print(f"\n[EXECUTIVE SUMMARY]\n{res.executive_summary}\n")

    print("[VALIDATED CLAIMS]")
    for c in res.claims:
        print(f"  * [{c.classification.upper()}] {c.statement} (Conf: {c.confidence:.2f}) -> Ev: {c.evidence_refs}")

    print("\n[COMMERCIAL OPPORTUNITIES]")
    for opp in res.commercial_opportunities:
        print(f"  * [{opp.priority.upper()}] {opp.title}: {opp.description}")
        print(f"    Services Matched: {opp.matched_services}")

    print("\n[RISKS]")
    for r in res.risks:
        print(f"  ! {r}")

    print("\n[UNKNOWNS]")
    for u in res.unknowns:
        print(f"  ? {u}")

    print("\n[VALIDATION WARNINGS]")
    for w in res.warnings:
        print(f"  - {w}")
    if not res.warnings:
        print("  (None)")

    print("\nRESULT: SUCCESS\n")


if __name__ == "__main__":
    run_manual_gemini_research()
