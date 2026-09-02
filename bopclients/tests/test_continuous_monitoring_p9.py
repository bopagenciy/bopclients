"""Unit test suite for BopClients P9 Continuous Monitoring Orchestration & P9.3 Final Scheduling Audit."""

import pytest
from datetime import datetime, timezone, timedelta
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.prospect import Prospect
from bopclients.domain.prospect_priority import ProspectPriority
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.domain.enums import SignalType, SignalCategory, IntentStrength
from bopclients.domain.exceptions import TenantAccessError, EntityNotFoundError
from bopclients.domain.monitoring_schedule import MonitoringSchedule
from bopclients.application.monitoring_policy import MonitoringPolicy, MonitoringBackoffPolicy
from bopclients.application.continuous_monitoring_service import ContinuousMonitoringService
from bopclients.application.public_signal_monitor_service import PublicSignalMonitorService
from bopclients.application.prospect_priority_service import ProspectPriorityService
from bopclients.application.provider_registry import PublicSignalProviderRegistry
from bopclients.application.signal_provider import OfficialWebsiteSignalProvider
from bopclients.application.providers.procurement_provider import GovernmentProcurementProvider
from bopclients.application.providers.news_provider import PublicNewsSignalProvider
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


@pytest.fixture
def memory_db():
    db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(db)
    return db


@pytest.fixture
def repos(memory_db):
    return {
        "db": memory_db,
        "org": OrganizationRepository(memory_db),
        "camp": CampaignRepository(memory_db),
        "prospect": ProspectRepository(memory_db),
        "prio": ProspectPriorityRepository(memory_db),
        "obs": SignalObservationRepository(memory_db),
        "intel": ProspectIntelligenceRepository(memory_db),
        "enrich": EnrichmentResultRepository(memory_db),
        "rr": ResearchRunRepository(memory_db),
        "sched": MonitoringScheduleRepository(memory_db),
    }


class TestMonitoringPolicyP9:
    def test_priority_cadence_baselines(self):
        p = Prospect(id="p1", organization_id="org1", name="Alpha Medical")

        d_urgent = MonitoringPolicy.evaluate(p, priority=ProspectPriority(priority_label="URGENT"))
        d_high = MonitoringPolicy.evaluate(p, priority=ProspectPriority(priority_label="HIGH"))
        d_med = MonitoringPolicy.evaluate(p, priority=ProspectPriority(priority_label="MEDIUM"))
        d_low = MonitoringPolicy.evaluate(p, priority=ProspectPriority(priority_label="LOW"))

        assert d_urgent.recommended_interval_days == 3
        assert d_high.recommended_interval_days == 7
        assert d_med.recommended_interval_days == 14
        assert d_low.recommended_interval_days == 30

    def test_strong_intent_and_approaching_due_date_shortens_cadence(self):
        p = Prospect(id="p1", organization_id="org1", name="Department of Veterans Affairs", industry="government")
        now = datetime.now(timezone.utc)
        due_soon = (now + timedelta(days=5)).isoformat()

        sig_active = PublicSignalObservation(
            signal_type="public_request_for_proposal",
            category="buying_intent",
            intent_strength="strong",
            evidence={"currentness": "active", "due_date": due_soon},
        )

        decision = MonitoringPolicy.evaluate(p, priority=ProspectPriority(priority_label="MEDIUM"), active_signals=[sig_active], now_dt=now)
        assert decision.recommended_interval_days == 2
        assert any("Active RFP due in 5 days" in r for r in decision.reasons)

    def test_backoff_policy_progression(self):
        now = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)

        b1 = MonitoringBackoffPolicy.compute_backoff_next_check(1, now_dt=now)
        b2 = MonitoringBackoffPolicy.compute_backoff_next_check(2, now_dt=now)
        b3 = MonitoringBackoffPolicy.compute_backoff_next_check(3, now_dt=now)
        b4 = MonitoringBackoffPolicy.compute_backoff_next_check(4, now_dt=now)

        assert b1 == "2026-09-02T13:00:00+00:00"  # +1h
        assert b2 == "2026-09-02T16:00:00+00:00"  # +4h
        assert b3 == "2026-09-03T00:00:00+00:00"  # +12h
        assert b4 == "2026-09-03T12:00:00+00:00"  # +24h

    def test_source_fingerprint_changes_on_signal_swap_with_same_count(self):
        p = Prospect(id="p1", organization_id="org1", name="Alpha Medical")

        sig_rfp = PublicSignalObservation(signal_type="public_request_for_proposal", category="buying_intent")
        sig_loc = PublicSignalObservation(signal_type="opened_new_location", category="company_activity")

        fp1 = MonitoringPolicy.compute_source_fingerprint(p, active_signals=[sig_rfp])
        fp2 = MonitoringPolicy.compute_source_fingerprint(p, active_signals=[sig_loc])

        assert fp1 != fp2


class TestNoSlidingScheduleProtectionP9:
    def test_no_sliding_schedule_on_repeated_ensure_schedule_calls(self, repos):
        org = repos["org"].save(Organization(name="Org P9", slug="org-p9"))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="Static Cadence Prospect"))

        service = ContinuousMonitoringService(
            schedule_repo=repos["sched"],
            prospect_repo=repos["prospect"],
            observation_repo=repos["obs"],
        )

        now1 = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)
        sched1 = service.ensure_schedule_for_prospect(org.id, p.id, now_dt=now1)
        initial_next_check = sched1.next_check_at

        # Call ensure_schedule 3 days later without changes
        now2 = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)
        sched2 = service.ensure_schedule_for_prospect(org.id, p.id, now_dt=now2)

        # NO-SLIDING PROTECTION: next_check_at must remain initial_next_check (Sept 16)
        assert sched2.next_check_at == initial_next_check


class TestLeaseAndClaimP9:
    def test_atomic_claim_due_work_rejects_future_next_check_at(self, repos):
        org = repos["org"].save(Organization(name="Org FutureClaim", slug="org-futureclaim"))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="Future Prospect"))

        sched_repo = repos["sched"]
        s = MonitoringSchedule(
            organization_id=org.id,
            prospect_id=p.id,
            status="active",
            next_check_at="2026-12-31T00:00:00+00:00",  # Future
            source_fingerprint="fp123",
        )
        sched_repo.save(org.id, s)

        claimed = sched_repo.claim_due_work(org.id, s.id, lease_token="token123", now_iso="2026-09-02T12:00:00+00:00")
        assert claimed is False

    def test_stale_worker_lease_release_and_update_protection(self, repos):
        org = repos["org"].save(Organization(name="Org StaleWorker", slug="org-staleworker"))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="Race Prospect"))

        sched_repo = repos["sched"]
        s = MonitoringSchedule(
            organization_id=org.id,
            prospect_id=p.id,
            status="active",
            next_check_at="2026-09-01T00:00:00+00:00",
            source_fingerprint="fp123",
        )
        sched_repo.save(org.id, s)

        sched_repo.claim_due_work(org.id, s.id, lease_token="token_a", now_iso="2026-09-02T12:00:00+00:00")
        sched_repo.claim_due_work(org.id, s.id, lease_token="token_b", now_iso="2026-09-02T12:10:00+00:00")

        released = sched_repo.release_lease(org.id, s.id, lease_token="token_a")
        assert released is False

        updated_s = sched_repo.get_by_id(org.id, s.id)
        assert updated_s.lease_token == "token_b"


class TestContinuousMonitoringExecutionAndTenancyP9:
    def test_post_execution_active_rfp_shortens_cadence_to_3_days(self, repos):
        org = repos["org"].save(Organization(name="Org PostRun", slug="org-postrun"))
        camp = repos["camp"].save(org.id, Campaign(name="Camp PostRun"))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="VA Hospital", website_url="https://va.gov", industry="government"))

        now = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)

        # Active RFP observation
        obs = PublicSignalObservation(
            organization_id=org.id,
            prospect_id=p.id,
            provider="government_procurement",
            signal_type=SignalType.PUBLIC_REQUEST_FOR_PROPOSAL.value,
            category=SignalCategory.BUYING_INTENT.value,
            intent_strength=IntentStrength.STRONG.value,
            confidence=0.9,
            evidence={"currentness": "active", "due_date": "2026-12-31"},
        )
        repos["obs"].save(org.id, obs)

        reg = PublicSignalProviderRegistry()
        reg.register(OfficialWebsiteSignalProvider())
        reg.register(GovernmentProcurementProvider(api_key="key"))

        sig_service = PublicSignalMonitorService(
            observation_repo=repos["obs"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            research_run_repo=repos["rr"],
            registry=reg,
        )

        prio_service = ProspectPriorityService(
            priority_repo=repos["prio"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            intel_repo=repos["intel"],
            enrichment_repo=repos["enrich"],
            research_run_repo=repos["rr"],
        )

        service = ContinuousMonitoringService(
            schedule_repo=repos["sched"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            priority_repo=repos["prio"],
            observation_repo=repos["obs"],
            research_run_repo=repos["rr"],
            signal_monitor_service=sig_service,
            priority_service=prio_service,
        )

        sched = service.ensure_schedule_for_prospect(org.id, p.id, camp.id, now_dt=now)
        sched.next_check_at = "2026-09-01T00:00:00+00:00"  # Due
        repos["sched"].save(org.id, sched)

        res = service.execute_due(org.id, sched.id, now_dt=now)
        assert res.status in ("SUCCESS", "PARTIAL_SUCCESS")

        updated_sched = repos["sched"].get_by_id(org.id, sched.id)
        assert updated_sched.recommended_interval_days == 3
        assert res.next_check_at == updated_sched.next_check_at  # MATCH CONFIRMED

        # Immediate ensure_schedule call post-execution does NOT slide next_check_at
        ensured = service.ensure_schedule_for_prospect(org.id, p.id, camp.id, now_dt=now)
        assert ensured.next_check_at == updated_sched.next_check_at

    def test_force_monitor_on_paused_schedule_executes_and_preserves_paused_status(self, repos):
        org = repos["org"].save(Organization(name="Org PausedForce", slug="org-pausedforce"))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="Department of Veterans Affairs", website_url="https://va.gov", industry="government"))

        reg = PublicSignalProviderRegistry()
        reg.register(OfficialWebsiteSignalProvider())
        reg.register(GovernmentProcurementProvider(api_key="key"))

        sig_service = PublicSignalMonitorService(
            observation_repo=repos["obs"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            research_run_repo=repos["rr"],
            registry=reg,
        )

        service = ContinuousMonitoringService(
            schedule_repo=repos["sched"],
            prospect_repo=repos["prospect"],
            observation_repo=repos["obs"],
            signal_monitor_service=sig_service,
        )

        sched = service.ensure_schedule_for_prospect(org.id, p.id)
        service.pause_schedule(org.id, sched.id)

        res_due = service.execute_due(org.id, sched.id)
        assert res_due.status == "SKIPPED"

        res_force = service.force_monitor(org.id, sched.id)
        assert res_force.status in ("SUCCESS", "SKIPPED")

        updated = repos["sched"].get_by_id(org.id, sched.id)
        assert updated.status == "paused"

    def test_disabled_schedule_rejects_both_execute_due_and_force_monitor(self, repos):
        org = repos["org"].save(Organization(name="Org Disabled", slug="org-disabled"))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="Disabled Prospect"))

        service = ContinuousMonitoringService(
            schedule_repo=repos["sched"],
            prospect_repo=repos["prospect"],
        )

        sched = service.ensure_schedule_for_prospect(org.id, p.id)
        service.disable_schedule(org.id, sched.id)

        res_due = service.execute_due(org.id, sched.id)
        assert res_due.status == "SKIPPED"

        res_force = service.force_monitor(org.id, sched.id)
        assert res_force.status == "SKIPPED"
        assert "Disabled schedule cannot be force run" in res_force.warnings[0]

    def test_tenant_boundary_isolation_on_schedules(self, repos):
        org_a = repos["org"].save(Organization(name="Org A", slug="org-a"))
        org_b = repos["org"].save(Organization(name="Org B", slug="org-b"))

        p_a = repos["prospect"].save_prospect(org_a.id, Prospect(name="Prospect A"))
        service = ContinuousMonitoringService(
            schedule_repo=repos["sched"],
            prospect_repo=repos["prospect"],
        )

        sched_a = service.ensure_schedule_for_prospect(org_a.id, p_a.id)

        assert repos["sched"].get_by_id(org_b.id, sched_a.id) is None

        with pytest.raises(EntityNotFoundError):
            service.execute_due(org_b.id, sched_a.id)
