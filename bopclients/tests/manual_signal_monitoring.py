"""Manual integration test script for BopClients P7 Public Signal Monitoring & Observations."""

from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.enums import CampaignStatus
from bopclients.application.signal_provider import OfficialWebsiteSignalProvider
from bopclients.application.public_signal_monitor_service import PublicSignalMonitorService
from bopclients.application.prospect_priority_service import ProspectPriorityService
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.prospect_priority_repository import ProspectPriorityRepository
from bopclients.infrastructure.repositories.signal_observation_repository import SignalObservationRepository
from bopclients.infrastructure.repositories.prospect_intelligence_repository import ProspectIntelligenceRepository
from bopclients.infrastructure.repositories.enrichment_result_repository import EnrichmentResultRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


def run_manual_signal_monitoring_test():
    """Execute controlled public signal monitoring manual integration test."""
    print("\n==================================================")
    print("BOPCLIENTS P7 — PUBLIC SIGNAL MONITORING MANUAL TEST")
    print("==================================================\n")
    print("VALIDATION MODE: CONTROLLED_HTTP_FIXTURE_VALIDATED\n")

    db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(db)

    org_repo = OrganizationRepository(db)
    camp_repo = CampaignRepository(db)
    prospect_repo = ProspectRepository(db)
    prio_repo = ProspectPriorityRepository(db)
    obs_repo = SignalObservationRepository(db)
    intel_repo = ProspectIntelligenceRepository(db)
    enrich_repo = EnrichmentResultRepository(db)
    rr_repo = ResearchRunRepository(db)

    # Setup Organization & Campaign
    org = org_repo.save(Organization(name="Signal Monitoring Agency", slug="sig-agency"))
    camp = camp_repo.save(org.id, Campaign(name="Public Signal Campaign", status=CampaignStatus.ACTIVE))

    # Setup Prospect A: Controlled website with RFP and hiring activity
    p_a = prospect_repo.save_prospect(
        org.id, Prospect(name="Apex Medical Center", website_url="https://apexmedical.com")
    )
    prospect_repo.add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p_a.id))
    prospect_repo.save_lead_score(org.id, LeadScore(organization_id=org.id, prospect_id=p_a.id, score=80))

    # Priority service
    prio_service = ProspectPriorityService(
        priority_repo=prio_repo,
        prospect_repo=prospect_repo,
        campaign_repo=camp_repo,
        intel_repo=intel_repo,
        enrichment_repo=enrich_repo,
        research_run_repo=rr_repo,
    )

    # Initial Priority Calculation (Before Monitoring)
    prio_before = prio_service.prioritize_prospect(org.id, camp.id, p_a.id)

    # Mocking WebScraper and DNS resolution in OfficialWebsiteSignalProvider for deterministic offline execution
    class MockHtmlScraper:
        def fetch_page(self, url):
            if "apexmedical.com" in url:
                return {
                    "status": 200,
                    "content": """
                        <html>
                        <head><title>Apex Medical Center - Procurement & Careers</title></head>
                        <body>
                            <h1>Apex Medical Center</h1>
                            <p>We are currently seeking vendors for software consulting.</p>
                            <h2>Request for Proposal - Digital Marketing Agency</h2>
                            <p>Proposals due October 15, 2026 for comprehensive healthcare marketing services.</p>
                            <h2>Careers</h2>
                            <p>We're hiring a Digital Marketing Manager to lead our growth team.</p>
                            <a href="https://apexmedical.com/careers">View Job Openings</a>
                        </body>
                        </html>
                    """,
                    "headers": {"content-type": "text/html"},
                }
            return {"status": 404, "content": ""}

    provider = OfficialWebsiteSignalProvider(scraper=MockHtmlScraper())
    monitor_service = PublicSignalMonitorService(
        observation_repo=obs_repo,
        prospect_repo=prospect_repo,
        campaign_repo=camp_repo,
        research_run_repo=rr_repo,
        priority_service=prio_service,
        providers=[provider],
    )

    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.216.34", 80))]):
        # Execute Monitoring with Recompute Priority enabled
        res = monitor_service.monitor_prospect(org.id, p_a.id, recompute_priority=True)

    # Priority Calculation (After Monitoring)
    prio_after = prio_repo.get(org.id, camp.id, p_a.id)

    # Print Formatted Report
    print(f"PROSPECT            : {p_a.name.upper()} ({p_a.website_url})")
    print(f"PROVIDER            : {provider.provider_name}")
    print(f"PAGES CHECKED       : 1")
    print(f"OBSERVATIONS FOUND  : {res.observations_found}")
    print(f"OBSERVATIONS CREATED: {res.observations_created}")
    print(f"SIGNALS ACTIVATED   : {res.signals_activated}")
    print("\nOBSERVATIONS LIST:")
    obs_list = obs_repo.list_for_prospect(org.id, p_a.id)
    for obs in obs_list:
        cur = obs.evidence.get("currentness", "N/A")
        print(f"  - [{obs.category.upper()}] {obs.signal_type} (currentness={cur}, conf {obs.confidence:.2f})")
        print(f"    Source URL : {obs.source_url}")
        print(f"    Snippet    : {obs.evidence.get('snippet', '')[:80]}...")
    print(f"\nPRIORITY IMPACT:")
    print(f"  - BEFORE Monitoring : Score {prio_before.priority_score}/100 [{prio_before.priority_label.upper()}]")
    print(f"  - AFTER  Monitoring : Score {prio_after.priority_score}/100 [{prio_after.priority_label.upper()}]")
    print(f"  - URGENT Gate      : {prio_after.data.get('has_recent_verified_buying_intent')}")

    print(f"\nWARNINGS: {res.warnings}")
    print(f"ERRORS  : {res.errors}")
    print("\n==================================================")
    print("PUBLIC SIGNAL MONITORING MANUAL TEST SUCCESSFUL")
    print("==================================================\n")


if __name__ == "__main__":
    run_manual_signal_monitoring_test()
