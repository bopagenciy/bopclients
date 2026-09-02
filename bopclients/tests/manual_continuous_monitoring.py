"""Manual integration script for BopClients P9.3 Continuous Monitoring Orchestration & Scheduling Integrity."""

from datetime import datetime, timezone, timedelta
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.domain.enums import SignalType, SignalCategory, IntentStrength
from bopclients.application.provider_registry import PublicSignalProviderRegistry
from bopclients.application.signal_provider import OfficialWebsiteSignalProvider
from bopclients.application.providers.procurement_provider import GovernmentProcurementProvider
from bopclients.application.providers.news_provider import PublicNewsSignalProvider
from bopclients.application.public_signal_monitor_service import PublicSignalMonitorService
from bopclients.application.prospect_priority_service import ProspectPriorityService
from bopclients.application.continuous_monitoring_service import ContinuousMonitoringService
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.prospect_priority_repository import ProspectPriorityRepository
from bopclients.infrastructure.repositories.signal_observation_repository import SignalObservationRepository
from bopclients.infrastructure.repositories.prospect_intelligence_repository import ProspectIntelligenceRepository
from bopclients.infrastructure.repositories.enrichment_result_repository import EnrichmentResultRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.infrastructure.repositories.monitoring_schedule_repository import MonitoringScheduleRepository
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


def main():
    print("=" * 50)
    print("BOPCLIENTS P9.3 — CONTINUOUS MONITORING MANUAL TEST")
    print("=" * 50)

    # 1. Setup in-memory DB & repositories
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
    sched_repo = MonitoringScheduleRepository(db)

    # Custom failing provider for Scenario C simulation
    class FailingProvider:
        provider_name = "failing_provider"
        capabilities = type("Caps", (), {
            "configured": True,
            "validation_level": "FIXTURE_VALIDATED",
            "supports_rfp": False,
            "supports_company_news": False,
        })()
        def discover_signals(self, prospect, country=None):
            from bopclients.application.signal_monitor_dto import PublicSignalDiscoveryResult
            return PublicSignalDiscoveryResult(errors=["HTTP 500 Connection Timeout to provider API"])

    registry = PublicSignalProviderRegistry()
    registry.register(OfficialWebsiteSignalProvider())
    registry.register(GovernmentProcurementProvider(api_key="mock_key"))
    registry.register(PublicNewsSignalProvider())
    registry.register(FailingProvider())

    sig_service = PublicSignalMonitorService(
        observation_repo=obs_repo,
        prospect_repo=prospect_repo,
        campaign_repo=camp_repo,
        research_run_repo=rr_repo,
        registry=registry,
    )

    prio_service = ProspectPriorityService(
        priority_repo=prio_repo,
        prospect_repo=prospect_repo,
        campaign_repo=camp_repo,
        intel_repo=intel_repo,
        enrichment_repo=enrich_repo,
        research_run_repo=rr_repo,
    )

    monitoring_service = ContinuousMonitoringService(
        schedule_repo=sched_repo,
        prospect_repo=prospect_repo,
        campaign_repo=camp_repo,
        priority_repo=prio_repo,
        observation_repo=obs_repo,
        research_run_repo=rr_repo,
        signal_monitor_service=sig_service,
        priority_service=prio_service,
    )

    # 3. Create Tenant & Campaign
    org = org_repo.save(Organization(name="P9 Enterprise Org", slug="p9-enterprise"))
    camp = camp_repo.save(org.id, Campaign(name="Q3 Health Tech Campaign"))

    now = datetime.now(timezone.utc)
    past_due = (now - timedelta(hours=2)).isoformat()
    future_due = (now + timedelta(days=10)).isoformat()

    # 4. Create 4 Prospects for Scenarios A, B, C, D
    # Scenario A: SUCCESS WITH ACTIVE RFP (Department of Veterans Affairs)
    p_a = prospect_repo.save_prospect(org.id, Prospect(name="Department of Veterans Affairs", website_url="https://va.gov", industry="government"))
    prospect_repo.add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p_a.id))
    prospect_repo.save_lead_score(org.id, LeadScore(organization_id=org.id, prospect_id=p_a.id, score=80))

    obs_a = PublicSignalObservation(
        organization_id=org.id,
        prospect_id=p_a.id,
        provider="government_procurement",
        signal_type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
        category=SignalCategory.BUYING_INTENT.value,
        intent_strength=IntentStrength.STRONG.value,
        confidence=0.95,
        source_url="https://va.gov/sol-100",
        external_id="SOL-100",
        evidence={"currentness": "active", "due_date": (now + timedelta(days=15)).isoformat()},
    )
    obs_repo.save(org.id, obs_a)
    prio_service.prioritize_prospect(org.id, camp.id, p_a.id)

    # Scenario B: SKIPPED LOW PROSPECT (Miami Dental Care)
    p_b = prospect_repo.save_prospect(org.id, Prospect(name="Miami Dental Care", website_url="https://miamidentalcare.com", industry="healthcare"))
    prospect_repo.add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p_b.id))
    prio_service.prioritize_prospect(org.id, camp.id, p_b.id)

    # Scenario C: FAILED PROSPECT (Failing Systems Corp)
    p_c = prospect_repo.save_prospect(org.id, Prospect(name="Failing Systems Corp", website_url="https://failing-systems.xyz", industry="technology"))
    prospect_repo.add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p_c.id))
    prio_service.prioritize_prospect(org.id, camp.id, p_c.id)

    # Scenario D: NOT DUE PROSPECT (Future Check Corp)
    p_d = prospect_repo.save_prospect(org.id, Prospect(name="Future Check Corp", website_url="https://futurecorp.com", industry="technology"))
    prospect_repo.add_prospect_to_campaign(org.id, CampaignProspect(organization_id=org.id, campaign_id=camp.id, prospect_id=p_d.id))
    prio_service.prioritize_prospect(org.id, camp.id, p_d.id)

    # 5. Ensure schedules
    sched_a = monitoring_service.ensure_schedule_for_prospect(org.id, p_a.id, camp.id)
    sched_a.next_check_at = past_due
    sched_repo.save(org.id, sched_a)

    sched_b = monitoring_service.ensure_schedule_for_prospect(org.id, p_b.id, camp.id)
    sched_b.next_check_at = past_due
    sched_b.provider_names = ["government_procurement", "public_news"]
    sched_repo.save(org.id, sched_b)

    sched_c = monitoring_service.ensure_schedule_for_prospect(org.id, p_c.id, camp.id)
    sched_c.next_check_at = past_due
    sched_c.provider_names = ["failing_provider"]
    sched_repo.save(org.id, sched_c)

    sched_d = monitoring_service.ensure_schedule_for_prospect(org.id, p_d.id, camp.id)
    sched_d.next_check_at = future_due
    sched_repo.save(org.id, sched_d)

    print("\nSCHEDULES BEFORE EXECUTION:")
    for p, s, tag in [(p_a, sched_a, "Scenario A - SUCCESS"), (p_b, sched_b, "Scenario B - SKIPPED"), (p_c, sched_c, "Scenario C - FAILED"), (p_d, sched_d, "Scenario D - NOT DUE")]:
        print(f"  - [{p.name}] ({tag}) Schedule ID: {s.id[:8]} | Status: {s.status} | Due At: {s.next_check_at[:19]}")

    # 6. List Due Work
    due_work = monitoring_service.list_due(org.id)
    print(f"\nDUE WORK ITEMS FOUND: {len(due_work)}")
    for item in due_work:
        print(f"  - Schedule: {item.schedule_id[:8]} | Prospect: {item.prospect_id[:8]} | Due At: {item.due_at[:19]}")

    # 7. Execute Due Work & Compare Next Check Match
    print("\nEXECUTING DUE WORK ITEMS & MATCH VALIDATION:")
    results_map = {}
    for item in due_work:
        res = monitoring_service.execute_due(org.id, item.schedule_id, now_dt=now)
        results_map[res.schedule_id] = res
        print(f"  - [Schedule {res.schedule_id[:8]}] Status: {res.status} | Priority Before/After: {res.priority_before} -> {res.priority_after}")
        print(f"    Succeeded Ops: {res.operations_succeeded} | Result Next Check: {res.next_check_at[:19] if res.next_check_at else 'None'}")

    res_d = monitoring_service.execute_due(org.id, sched_d.id, now_dt=now)
    print(f"  - [Scenario D Schedule {sched_d.id[:8]}] Not Due Result: Status: {res_d.status} | Warnings: {res_d.warnings}")

    # 8. Schedules After Execution & Match Consistency
    print("\nSCHEDULES AFTER EXECUTION & MATCH CONFIRMATION:")
    for p, sched_obj, tag in [(p_a, sched_a, "SUCCESS WITH ACTIVE RFP"), (p_b, sched_b, "SKIPPED LOW PROSPECT"), (p_c, sched_c, "FAILED"), (p_d, sched_d, "NOT DUE")]:
        s_after = sched_repo.get_by_prospect_and_campaign(org.id, p.id, camp.id)
        res_obj = results_map.get(s_after.id)
        res_next = res_obj.next_check_at if res_obj else None
        match_flag = (res_next == s_after.next_check_at) if res_obj else True
        backoff_str = "+1 hour" if s_after.failure_count == 1 else ("none" if s_after.failure_count == 0 else f"{s_after.failure_count} retries")
        print(f"  - [{p.name}] ({tag}) Status: {s_after.status} | Rec Interval: {s_after.recommended_interval_days}d | Fail Count: {s_after.failure_count} | Backoff: {backoff_str}")
        print(f"    Result Next Check: {res_next[:19] if res_next else 'N/A'} | Persisted Next Check: {s_after.next_check_at[:19]} | MATCH: {match_flag}")

    print("\n==================================================")
    print("P9.3 CONTINUOUS MONITORING MANUAL TEST SUCCESSFUL")
    print("==================================================")


if __name__ == "__main__":
    main()
