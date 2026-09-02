"""Unit test suite for BopClients P10/P10.1 MonitoringWorker Execution Infrastructure."""

import pytest
from datetime import datetime, timezone, timedelta
from bopclients.domain.organization import Organization
from bopclients.domain.campaign import Campaign
from bopclients.domain.prospect import Prospect
from bopclients.domain.monitoring_schedule import MonitoringSchedule
from bopclients.application.continuous_monitoring_service import ContinuousMonitoringService
from bopclients.application.public_signal_monitor_service import PublicSignalMonitorService
from bopclients.application.lease_heartbeat import LeaseHeartbeat
from bopclients.application.provider_registry import PublicSignalProviderRegistry
from bopclients.worker.monitoring_worker import MonitoringWorker, MonitoringWorkerConfig
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


class TestSystemScopedDueQueryP10:
    def test_list_due_system_filtering_and_ordering(self, repos):
        org_a = repos["org"].save(Organization(name="Org A", slug="org-a"))
        org_b = repos["org"].save(Organization(name="Org B", slug="org-b"))

        p_a1 = repos["prospect"].save_prospect(org_a.id, Prospect(name="Prospect A1"))
        p_b1 = repos["prospect"].save_prospect(org_b.id, Prospect(name="Prospect B1"))

        now_iso = "2026-09-02T12:00:00+00:00"

        s_a1 = MonitoringSchedule(organization_id=org_a.id, prospect_id=p_a1.id, status="active", next_check_at="2026-09-01T10:00:00+00:00", source_fingerprint="fp1")
        s_b1 = MonitoringSchedule(organization_id=org_b.id, prospect_id=p_b1.id, status="active", next_check_at="2026-09-01T08:00:00+00:00", source_fingerprint="fp2")
        s_paused = MonitoringSchedule(organization_id=org_a.id, prospect_id=p_a1.id, campaign_id="c1", status="paused", next_check_at="2026-09-01T05:00:00+00:00", source_fingerprint="fp3")
        s_future = MonitoringSchedule(organization_id=org_b.id, prospect_id=p_b1.id, campaign_id="c2", status="active", next_check_at="2026-09-10T00:00:00+00:00", source_fingerprint="fp4")

        repos["sched"].save(org_a.id, s_a1)
        repos["sched"].save(org_b.id, s_b1)
        repos["sched"].save(org_a.id, s_paused)
        repos["sched"].save(org_b.id, s_future)

        system_due = repos["sched"].list_due_system(now_iso=now_iso)
        assert len(system_due) == 2
        assert system_due[0].id == s_b1.id
        assert system_due[1].id == s_a1.id


class TestLeaseHeartbeatP10_1:
    def test_lease_heartbeat_threshold_and_renewal(self, repos):
        org = repos["org"].save(Organization(name="Org HB", slug="org-hb"))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="HB Prospect"))

        sched_repo = repos["sched"]
        s = MonitoringSchedule(organization_id=org.id, prospect_id=p.id, status="active", next_check_at="2026-09-01T00:00:00+00:00", source_fingerprint="fp")
        sched_repo.save(org.id, s)

        token = "token_hb_1"
        now = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)
        claimed = sched_repo.claim_due_work(org.id, s.id, lease_token=token, lease_duration_seconds=300, now_iso=now.isoformat())
        assert claimed is True

        hb = LeaseHeartbeat(
            schedule_repo=sched_repo,
            organization_id=org.id,
            schedule_id=s.id,
            lease_token=token,
            lease_duration_seconds=300,
            renew_before_seconds=90,
            start_now_dt=now,
        )

        # Remaining 180s (> 90s threshold) -> NO UPDATE executed
        t1 = now + timedelta(seconds=120)
        res1 = hb.heartbeat_if_needed(now_dt=t1)
        assert res1 is True
        assert hb.lease_renewal_count == 0

        # Remaining 75s (<= 90s threshold) -> UPDATE executed
        t2 = now + timedelta(seconds=225)
        res2 = hb.heartbeat_if_needed(now_dt=t2)
        assert res2 is True
        assert hb.lease_renewal_count == 1

    def test_lease_ownership_loss_during_provider_execution(self, repos):
        org = repos["org"].save(Organization(name="Org Lost", slug="org-lost"))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="Lost Prospect"))

        service = ContinuousMonitoringService(schedule_repo=repos["sched"], prospect_repo=repos["prospect"], research_run_repo=repos["rr"])
        sched = service.ensure_schedule_for_prospect(org.id, p.id)
        sched.next_check_at = "2026-09-01T00:00:00+00:00"
        sched.provider_names = ["stealing_provider"]
        repos["sched"].save(org.id, sched)

        class StealingProvider:
            provider_name = "stealing_provider"
            capabilities = type("Caps", (), {
                "configured": True,
                "validation_level": "FIXTURE_VALIDATED",
                "supports_rfp": False,
                "supports_company_news": False,
            })()
            def discover_signals(self, prospect, context=None):
                from bopclients.application.signal_monitor_dto import PublicSignalDiscoveryResult
                # Simulate Worker B taking over lease in DB
                sql = "UPDATE monitoring_schedules SET lease_token = ? WHERE organization_id = ? AND id = ?"
                repos["db"].execute(sql, ("worker-B-token", org.id, sched.id))
                repos["db"].commit()
                return PublicSignalDiscoveryResult()

        reg = PublicSignalProviderRegistry()
        reg.register(StealingProvider())
        sig_service = PublicSignalMonitorService(
            observation_repo=repos["obs"],
            prospect_repo=repos["prospect"],
            campaign_repo=repos["camp"],
            research_run_repo=repos["rr"],
            registry=reg,
        )
        service.signal_monitor_service = sig_service

        res = service.execute_due(org.id, sched.id, now_dt=datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc))

        assert res.status == "SKIPPED"
        assert res.skip_reason == "LEASE_OWNERSHIP_LOST"
        assert any("LEASE_OWNERSHIP_LOST" in w for w in res.warnings)
        assert res.next_check_at is None

        # Verify Worker B token remains untouched in DB and schedule failure_count is 0
        s_db = repos["sched"].get_by_id(org.id, sched.id)
        assert s_db.lease_token == "worker-B-token"
        assert s_db.failure_count == 0

        # Verify orphan ResearchRun status is failed
        rr_db = repos["rr"].get_by_id(org.id, res.research_run_id)
        assert rr_db.status == "failed"


class TestMonitoringWorkerExecutionP10_1:
    def test_dry_run_zero_side_effects(self, repos):
        org = repos["org"].save(Organization(name="Org Dry", slug="org-dry"))
        p = repos["prospect"].save_prospect(org.id, Prospect(name="Dry Prospect"))

        service = ContinuousMonitoringService(schedule_repo=repos["sched"], prospect_repo=repos["prospect"])
        sched = service.ensure_schedule_for_prospect(org.id, p.id)
        sched.next_check_at = "2026-09-01T00:00:00+00:00"
        repos["sched"].save(org.id, sched)

        config = MonitoringWorkerConfig(dry_run=True)
        worker = MonitoringWorker(repos["sched"], service, config)

        res = worker.run(now_dt=datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc))

        assert res.stopped_reason == "DRY_RUN"
        assert res.items_discovered == 1
        assert res.items_attempted == 0
        assert res.items_claimed == 0

        s_after = repos["sched"].get_by_id(org.id, sched.id)
        assert s_after.next_check_at == "2026-09-01T00:00:00+00:00"

    def test_max_items_budget_enforcement(self, repos):
        org = repos["org"].save(Organization(name="Org Budget", slug="org-budget"))
        service = ContinuousMonitoringService(schedule_repo=repos["sched"], prospect_repo=repos["prospect"])

        for i in range(5):
            p = repos["prospect"].save_prospect(org.id, Prospect(name=f"Prospect {i}"))
            s = service.ensure_schedule_for_prospect(org.id, p.id)
            s.next_check_at = "2026-09-01T00:00:00+00:00"
            repos["sched"].save(org.id, s)

        config = MonitoringWorkerConfig(batch_size=2, max_items=3)
        worker = MonitoringWorker(repos["sched"], service, config)

        res = worker.run(now_dt=datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc))

        assert res.stopped_reason == "MAX_ITEMS_REACHED"
        assert res.items_attempted == 3

    def test_cooperative_stop_signal_handling(self, repos):
        org = repos["org"].save(Organization(name="Org Stop", slug="org-stop"))
        service = ContinuousMonitoringService(schedule_repo=repos["sched"], prospect_repo=repos["prospect"])

        for i in range(3):
            p = repos["prospect"].save_prospect(org.id, Prospect(name=f"Prospect {i}"))
            s = service.ensure_schedule_for_prospect(org.id, p.id)
            s.next_check_at = "2026-09-01T00:00:00+00:00"
            repos["sched"].save(org.id, s)

        config = MonitoringWorkerConfig(batch_size=10, max_items=10)
        worker = MonitoringWorker(repos["sched"], service, config)

        stop_requested = False
        def stop_check():
            return stop_requested

        orig_execute = service.execute_due
        def execute_and_stop(organization_id, schedule_id, now_dt=None, force=False):
            nonlocal stop_requested
            res = orig_execute(organization_id, schedule_id, now_dt=now_dt, force=force)
            stop_requested = True
            return res

        service.execute_due = execute_and_stop

        res = worker.run(now_dt=datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc), should_stop=stop_check)

        assert res.stopped_reason == "STOP_REQUESTED"
        assert res.items_attempted == 1

    def test_config_validation_rejects_invalid_renew_threshold(self):
        with pytest.raises(ValueError, match="renew_before_seconds"):
            MonitoringWorkerConfig(lease_duration_seconds=300, lease_renew_before_seconds=300).validate()
