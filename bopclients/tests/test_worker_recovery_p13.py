"""Unit and Integration test suite for BopClients P13.3 Worker Recovery Critical Coverage & Retry Idempotency."""

import time
import pytest
from datetime import datetime, timezone, timedelta
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend

from bopclients.domain.organization import Organization
from bopclients.domain.prospect import Prospect
from bopclients.domain.research_run import ResearchRun
from bopclients.domain.monitoring_schedule import MonitoringSchedule
from bopclients.domain.signal_observation import PublicSignalObservation

from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.container import build_runtime_container
from bopclients.infrastructure.db.connection import SQLiteConnectionAdapter
from bopclients.application.research_run_recovery_service import ResearchRunRecoveryService


@pytest.fixture
def test_db():
    db = SQLiteConnectionAdapter(":memory:")
    DatabaseMigrator.migrate(db)
    yield db
    db.close()


@pytest.fixture
def container(test_db):
    settings = RuntimeSettings(
        environment="test",
        database_url=":memory:",
        enabled_providers=["official_website"],
        research_run_recovery_enabled=True,
        research_run_stale_after_seconds=900,
        lease_duration_seconds=300,
        research_run_recovery_limit=100,
    )
    return build_runtime_container(settings, db=test_db)


class TestWorkerRecoveryP13_3:
    """Comprehensive test suite evaluating ResearchRun time semantics, attempt correlation, and recovery resilience."""

    def test_schema_version_004_migration(self, test_db):
        ver = DatabaseMigrator.get_current_version(test_db)
        assert ver in ("20260902_004", "20260902_005", "20260902_006", "20260902_007")
        status = DatabaseMigrator.status(test_db)
        assert status["is_up_to_date"] is True

    def test_stale_after_seconds_must_exceed_lease_duration(self):
        s = RuntimeSettings(lease_duration_seconds=300, research_run_stale_after_seconds=200)
        with pytest.raises(ValueError, match="research_run_stale_after_seconds must be strictly greater than lease_duration_seconds"):
            s.validate()

    def test_expired_same_attempt_is_recovered(self, container):
        """Scenario 1: Attempt A execution_attempt_id=A, schedule attempt=A, lease expired 5 minutes before now -> Recovered."""
        org = container.org_repo.save(Organization(name="Org ExpSame", slug="org-expsame"))
        p = container.prospect_repo.save_prospect(org.id, Prospect(name="Prospect ExpSame"))
        s = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p.id)

        now = datetime.now(timezone.utc)
        attempt_A = "attempt-A-expired"
        stale_started = (now - timedelta(minutes=30)).isoformat()

        # Run A created 30 mins ago
        rr_A = ResearchRun(
            organization_id=org.id,
            prospect_id=p.id,
            monitoring_schedule_id=s.id,
            execution_attempt_id=attempt_A,
            run_type="signal_monitoring",
            status="running",
            started_at=stale_started,
        )
        container.research_run_repo.save(org.id, rr_A)

        # Schedule set with attempt_A, but lease_expires_at was 5 minutes in the past
        s.lease_token = "token-A"
        s.lease_expires_at = (now - timedelta(minutes=5)).isoformat()
        s.current_execution_attempt_id = attempt_A
        container.schedule_repo.save(org.id, s)

        # Recovery pass
        rec_res = container.recovery_service.reconcile_stale_runs(now_dt=now, stale_after_seconds=900)
        assert rec_res.candidates_found == 1
        assert rec_res.recovered_count == 1
        assert rec_res.recovered_run_ids == [rr_A.id]

        fetched_A = container.research_run_repo.get_by_id(org.id, rr_A.id)
        assert fetched_A.status == "failed"
        assert "WORKER_EXECUTION_LOST" in fetched_A.error_message

    def test_active_same_attempt_is_skipped(self, container):
        """Scenario 2: Attempt A execution_attempt_id=A, schedule attempt=A, lease active 5 minutes in future -> Skipped."""
        org = container.org_repo.save(Organization(name="Org ActSame", slug="org-actsame"))
        p = container.prospect_repo.save_prospect(org.id, Prospect(name="Prospect ActSame"))
        s = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p.id)

        now = datetime.now(timezone.utc)
        attempt_A = "attempt-A-active"
        stale_started = (now - timedelta(minutes=20)).isoformat()

        rr_A = ResearchRun(
            organization_id=org.id,
            prospect_id=p.id,
            monitoring_schedule_id=s.id,
            execution_attempt_id=attempt_A,
            run_type="signal_monitoring",
            status="running",
            started_at=stale_started,
        )
        container.research_run_repo.save(org.id, rr_A)

        # Schedule set with attempt_A, lease active 5 minutes in the future
        s.lease_token = "token-A"
        s.lease_expires_at = (now + timedelta(minutes=5)).isoformat()
        s.current_execution_attempt_id = attempt_A
        container.schedule_repo.save(org.id, s)

        rec_res = container.recovery_service.reconcile_stale_runs(now_dt=now, stale_after_seconds=900)
        assert rec_res.recovered_count == 0
        assert rec_res.skipped_active_lease == 1

        fetched_A = container.research_run_repo.get_by_id(org.id, rr_A.id)
        assert fetched_A.status == "running"

    def test_active_different_attempt_recovers_stale_A(self, container):
        """Scenario 3: Run A stale (attempt A), schedule active lease belongs to attempt B -> Run A recovered, Run B untouched."""
        org = container.org_repo.save(Organization(name="Org ActDiff", slug="org-actdiff"))
        p = container.prospect_repo.save_prospect(org.id, Prospect(name="Prospect ActDiff"))
        s = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p.id)

        now = datetime.now(timezone.utc)
        attempt_A = "attempt-A-stale"
        attempt_B = "attempt-B-active"

        # Run A started 30 mins ago
        rr_A = ResearchRun(
            organization_id=org.id,
            prospect_id=p.id,
            monitoring_schedule_id=s.id,
            execution_attempt_id=attempt_A,
            run_type="signal_monitoring",
            status="running",
            started_at=(now - timedelta(minutes=30)).isoformat(),
        )
        container.research_run_repo.save(org.id, rr_A)

        # Run B started NOW
        rr_B = ResearchRun(
            organization_id=org.id,
            prospect_id=p.id,
            monitoring_schedule_id=s.id,
            execution_attempt_id=attempt_B,
            run_type="signal_monitoring",
            status="running",
            started_at=now.isoformat(),
        )
        container.research_run_repo.save(org.id, rr_B)

        # Schedule has active lease belonging to Attempt B
        s.lease_token = "token-B"
        s.lease_expires_at = (now + timedelta(minutes=5)).isoformat()
        s.current_execution_attempt_id = attempt_B
        container.schedule_repo.save(org.id, s)

        rec_res = container.recovery_service.reconcile_stale_runs(now_dt=now, stale_after_seconds=900)
        assert rec_res.recovered_count == 1
        assert rec_res.recovered_run_ids == [rr_A.id]

        fetched_A = container.research_run_repo.get_by_id(org.id, rr_A.id)
        assert fetched_A.status == "failed"

        fetched_B = container.research_run_repo.get_by_id(org.id, rr_B.id)
        assert fetched_B.status == "running"

    def test_completed_and_failed_runs_unchanged_by_recovery(self, container):
        """Completed and failed ResearchRuns are never mutated by recovery pass."""
        org = container.org_repo.save(Organization(name="Org Done", slug="org-done"))
        p = container.prospect_repo.save_prospect(org.id, Prospect(name="Prospect Done"))
        
        now = datetime.now(timezone.utc)
        stale_time = (now - timedelta(minutes=30)).isoformat()

        rr_comp = ResearchRun(
            organization_id=org.id, prospect_id=p.id, run_type="signal_monitoring",
            status="completed", started_at=stale_time, completed_at=stale_time
        )
        container.research_run_repo.save(org.id, rr_comp)

        rr_fail = ResearchRun(
            organization_id=org.id, prospect_id=p.id, run_type="signal_monitoring",
            status="failed", started_at=stale_time, completed_at=stale_time, error_message="Previous error"
        )
        container.research_run_repo.save(org.id, rr_fail)

        rec_res = container.recovery_service.reconcile_stale_runs(now_dt=now, stale_after_seconds=900)
        assert rec_res.candidates_found == 0
        assert rec_res.recovered_count == 0

        assert container.research_run_repo.get_by_id(org.id, rr_comp.id).status == "completed"
        assert container.research_run_repo.get_by_id(org.id, rr_fail.id).status == "failed"

    def test_recovery_limit_and_deterministic_stale_ordering(self, container):
        """Recovery limit bounds candidate list, ordered deterministically by started_at ASC."""
        org = container.org_repo.save(Organization(name="Org Limit", slug="org-limit"))
        p = container.prospect_repo.save_prospect(org.id, Prospect(name="Prospect Limit"))

        now = datetime.now(timezone.utc)
        # Create 5 stale running runs at different start times
        runs = []
        for i in range(5):
            t = (now - timedelta(minutes=60 - i * 5)).isoformat()
            rr = ResearchRun(
                organization_id=org.id, prospect_id=p.id, run_type="signal_monitoring",
                status="running", started_at=t
            )
            runs.append(container.research_run_repo.save(org.id, rr))

        # Reconcile with limit=2
        rec_res = container.recovery_service.reconcile_stale_runs(now_dt=now, stale_after_seconds=900, limit=2)
        assert rec_res.candidates_found == 2
        assert rec_res.recovered_count == 2
        # Oldest 2 runs recovered
        assert rec_res.recovered_run_ids == [runs[0].id, runs[1].id]

    def test_stale_owner_release_cannot_clear_newer_owner_attempt_id(self, container):
        """Stale owner Attempt A cannot release or clear Attempt B's lease or attempt ID."""
        org = container.org_repo.save(Organization(name="Org StaleOwner", slug="org-staleowner"))
        p = container.prospect_repo.save_prospect(org.id, Prospect(name="Prospect StaleOwner"))
        s = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p.id)

        now_iso = datetime.now(timezone.utc).isoformat()
        s.next_check_at = "2026-09-01T00:00:00+00:00"
        container.schedule_repo.save(org.id, s)

        # Attempt B claims schedule
        container.schedule_repo.claim_due_work(
            org.id, s.id, lease_token="token-B", lease_duration_seconds=300, now_iso=now_iso, execution_attempt_id="attempt-B"
        )

        # Stale Attempt A tries releasing with wrong token "token-A"
        released = container.schedule_repo.release_lease(
            org.id, s.id, lease_token="token-A", execution_attempt_id="attempt-A"
        )
        assert released is False

        sched_db = container.schedule_repo.get_by_id(org.id, s.id)
        assert sched_db.lease_token == "token-B"
        assert sched_db.current_execution_attempt_id == "attempt-B"

    def test_recovery_disabled_flag_skips_recovery_pass(self, container):
        """Recovery disabled configuration skips recovery pass execution."""
        org = container.org_repo.save(Organization(name="Org RecDis", slug="org-recdis"))
        p = container.prospect_repo.save_prospect(org.id, Prospect(name="Prospect RecDis"))
        s = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p.id)

        stale_started = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        rr_stale = ResearchRun(
            organization_id=org.id,
            prospect_id=p.id,
            monitoring_schedule_id=s.id,
            execution_attempt_id="attempt-dis-1",
            run_type="signal_monitoring",
            status="running",
            started_at=stale_started,
        )
        container.research_run_repo.save(org.id, rr_stale)

        # Disable recovery in worker config
        container.worker.config.research_run_recovery_enabled = False
        run_res = container.worker.run()

        assert run_res.recovery_result is None
        fetched = container.research_run_repo.get_by_id(org.id, rr_stale.id)
        assert fetched.status == "running"

    def test_worker_dry_run_never_mutates_stale_runs(self, container):
        """Worker dry-run mode never mutates stale ResearchRuns."""
        org = container.org_repo.save(Organization(name="Org Dry", slug="org-dry"))
        p = container.prospect_repo.save_prospect(org.id, Prospect(name="Prospect Dry"))
        s = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p.id)

        stale_started = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        rr_stale = ResearchRun(
            organization_id=org.id,
            prospect_id=p.id,
            monitoring_schedule_id=s.id,
            execution_attempt_id="attempt-dry-1",
            run_type="signal_monitoring",
            status="running",
            started_at=stale_started,
        )
        container.research_run_repo.save(org.id, rr_stale)

        container.worker.config.dry_run = True
        run_res = container.worker.run()

        assert run_res.stopped_reason == "DRY_RUN"
        fetched = container.research_run_repo.get_by_id(org.id, rr_stale.id)
        assert fetched.status == "running"

    def test_real_worker_retry_execution_after_crash_and_recovery(self, container):
        """End-to-end real worker retry: crash A -> recovery A -> worker.run() processes B."""
        org = container.org_repo.save(Organization(name="Org Retry", slug="org-retry"))
        p = container.prospect_repo.save_prospect(org.id, Prospect(name="Prospect Retry", website_url="https://retry.org"))
        s = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p.id)

        now = datetime.now(timezone.utc)
        s.next_check_at = (now - timedelta(days=1)).isoformat()
        container.schedule_repo.save(org.id, s)

        # Attempt A crashed 30 mins ago
        attempt_A = "attempt-A-crash"
        rr_A = ResearchRun(
            organization_id=org.id,
            prospect_id=p.id,
            monitoring_schedule_id=s.id,
            execution_attempt_id=attempt_A,
            run_type="signal_monitoring",
            status="running",
            started_at=(now - timedelta(minutes=30)).isoformat(),
        )
        container.research_run_repo.save(org.id, rr_A)

        # 1. Recovery pass reconciles A to failed
        rec_res = container.recovery_service.reconcile_stale_runs(now_dt=now, stale_after_seconds=900)
        assert rec_res.recovered_count == 1

        # 2. MonitoringWorker executes real retry pass
        worker_res = container.worker.run(now_dt=now + timedelta(minutes=35))
        assert worker_res.items_attempted == 1
        assert worker_res.items_claimed == 1
        assert worker_res.success_count == 1

        # 3. Schedule finalized and ownership cleared
        sched_final = container.schedule_repo.get_by_id(org.id, s.id)
        assert sched_final.lease_token is None
        assert sched_final.lease_expires_at is None
        assert sched_final.current_execution_attempt_id is None
        assert sched_final.failure_count == 0

        # 4. History check
        runs = container.research_run_repo.list_by_organization(org.id)
        assert len(runs) == 2
        statuses = {r.status for r in runs}
        assert statuses == {"failed", "completed"}
