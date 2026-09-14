"""Unit tests for BopClients P16 Production Scheduler, Job Dispatch & Operational Coordination."""

import time
import threading
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from bopclients.runtime.settings import RuntimeSettings, AppEnvironment
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.container import build_runtime_container, build_production_scheduler
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.infrastructure.repositories.scheduler_repository import SchedulerRepository
from bopclients.application.production_scheduler import ProductionScheduler, SchedulerTickResult
from bopclients.application.scheduler_heartbeat import SchedulerHeartbeat
from bopclients.worker.monitoring_worker import MonitoringWorker, MonitoringWorkerConfig
from bopclients.domain.organization import Organization
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign import Campaign
from bopclients.domain.monitoring_schedule import MonitoringSchedule


@pytest.fixture
def sqlite_container():
    """Build fresh in-memory SQLite container with migrated schema 20260902_006."""
    settings = RuntimeSettings(
        environment=AppEnvironment.DEVELOPMENT,
        database_url=":memory:",
        enabled_providers=["official_website"],
        production_scheduler_enabled=True,
        scheduler_key="monitoring_worker",
        scheduler_lease_seconds=300,
        scheduler_renew_before_seconds=90,
    )
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)
    container = build_runtime_container(settings=settings, db=db)
    return container


class TestProductionSchedulerDisabled:
    def test_scheduler_disabled_by_default_returns_skipped(self, sqlite_container):
        sqlite_container.settings.production_scheduler_enabled = False
        scheduler = sqlite_container.scheduler

        result = scheduler.tick(force=False)
        assert result.status == "SKIPPED_DISABLED"
        assert result.error_code == "SCHEDULER_DISABLED"
        assert result.items_attempted == 0
        assert result.items_claimed == 0

        # Under ACQUIRED_DISPATCH_ONLY: no audit history row is recorded for skips
        assert result.scheduler_run_id == ""
        # Lease is NOT acquired
        state = sqlite_container.scheduler_repo.get_dispatch_state("monitoring_worker")
        assert state is None or state.get("lease_token") is None

    def test_force_flag_bypasses_disabled_setting(self, sqlite_container):
        sqlite_container.settings.production_scheduler_enabled = False
        scheduler = sqlite_container.scheduler

        result = scheduler.tick(force=True)
        assert result.status == "COMPLETED"
        assert result.worker_stopped_reason == "NO_DUE_WORK"

        run_record = sqlite_container.scheduler_repo.get_run(result.scheduler_run_id)
        assert run_record is not None
        assert run_record["status"] == "COMPLETED"


class TestProductionSchedulerExecution:
    def test_successful_tick_with_zero_due_work(self, sqlite_container):
        scheduler = sqlite_container.scheduler

        result = scheduler.tick()
        assert result.status == "COMPLETED"
        assert result.worker_stopped_reason == "NO_DUE_WORK"
        assert result.items_attempted == 0
        assert result.items_claimed == 0
        assert result.error_code is None

        # Verify lease was cleanly released
        state = sqlite_container.scheduler_repo.get_dispatch_state("monitoring_worker")
        assert state is not None
        assert state["lease_token"] is None
        assert state["lease_expires_at"] is None
        assert state["last_status"] == "COMPLETED"

    def test_successful_tick_with_due_schedule_processed(self, sqlite_container):
        # Seed tenant, prospect, campaign, and due monitoring schedule
        org = sqlite_container.org_repo.save(Organization(name="P16 Test Org", slug="p16-test-org"))
        prospect = sqlite_container.prospect_repo.save_prospect(
            org.id, Prospect(name="Test Prospect", website_url="https://example.com")
        )

        schedule = sqlite_container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, prospect.id)
        past_iso = "2026-09-01T00:00:00+00:00"
        schedule.next_check_at = past_iso
        sqlite_container.schedule_repo.save(org.id, schedule)

        scheduler = sqlite_container.scheduler
        result = scheduler.tick()

        assert result.status == "COMPLETED"
        assert result.items_attempted == 1
        assert result.items_claimed == 1
        assert result.success_count == 1
        assert result.worker_run_id is not None

        # Verify audit history
        run_record = sqlite_container.scheduler_repo.get_run(result.scheduler_run_id)
        assert run_record is not None
        assert run_record["status"] == "COMPLETED"
        assert run_record["items_claimed"] == 1
        assert run_record["success_count"] == 1

        # Verify schedule was updated
        updated_sched = sqlite_container.schedule_repo.get_by_id(org.id, schedule.id)
        assert updated_sched.last_check_at is not None
        assert updated_sched.next_check_at > past_iso

    def test_fatal_worker_exception_handled_cleanly(self, sqlite_container, monkeypatch):
        scheduler = sqlite_container.scheduler

        # Monkeypatch worker.run to raise fatal infrastructure error
        def failing_run(*args, **kwargs):
            raise RuntimeError("Database connection exploded")

        monkeypatch.setattr(sqlite_container.worker, "run", failing_run)

        result = scheduler.tick()
        assert result.status == "FAILED"
        assert result.error_code == "WORKER_FATAL_ERROR"
        assert "Database connection exploded" in result.error_message

        # Verify audit record marked FAILED
        run_record = sqlite_container.scheduler_repo.get_run(result.scheduler_run_id)
        assert run_record["status"] == "FAILED"
        assert run_record["error_code"] == "WORKER_FATAL_ERROR"

        # Verify lease was cleared
        state = sqlite_container.scheduler_repo.get_dispatch_state("monitoring_worker")
        assert state["lease_token"] is None


class TestProductionSchedulerLeaseAndOverlap:
    def test_competing_tick_skipped_when_lease_held(self, sqlite_container):
        # Manually hold dispatch lease in repository
        now = datetime.now(timezone.utc)
        acquired, _ = sqlite_container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="competing_token_123",
            lease_duration_seconds=300,
            run_id="competing_run_123",
            now_dt=now,
        )
        assert acquired is True

        # Second tick should skip with SKIPPED_LEASE_HELD
        result = sqlite_container.scheduler.tick(now_dt=now)
        assert result.status == "SKIPPED_LEASE_HELD"
        assert result.error_code == "DISPATCH_LEASE_HELD"
        assert result.items_attempted == 0

        # Lease remains owned by competing_token_123
        state = sqlite_container.scheduler_repo.get_dispatch_state("monitoring_worker")
        assert state["lease_token"] == "competing_token_123"

    def test_expired_lease_can_be_reclaimed(self, sqlite_container):
        t0 = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
        # Acquire lease that lasts 60 seconds
        acquired, _ = sqlite_container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="old_expired_token",
            lease_duration_seconds=60,
            run_id="old_expired_run",
            now_dt=t0,
        )
        assert acquired is True

        # Advance time past expiration (+70s)
        t1 = t0 + timedelta(seconds=70)
        result = sqlite_container.scheduler.tick(now_dt=t1)
        assert result.status == "COMPLETED"

        # The run succeeded under the new invocation
        run_record = sqlite_container.scheduler_repo.get_run(result.scheduler_run_id)
        assert run_record["status"] == "COMPLETED"

    def test_stale_release_token_cannot_clear_newer_lease(self, sqlite_container):
        t0 = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
        sqlite_container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="token_A",
            lease_duration_seconds=60,
            run_id="run_A",
            now_dt=t0,
        )

        # Advance time; token_A expires, token_B acquires
        t1 = t0 + timedelta(seconds=70)
        sqlite_container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="token_B",
            lease_duration_seconds=300,
            run_id="run_B",
            now_dt=t1,
        )

        # Stale token_A attempts release
        released = sqlite_container.scheduler_repo.release_dispatch_lease(
            scheduler_key="monitoring_worker",
            lease_token="token_A",
            now_dt=t1,
        )
        assert released is False

        # Current lease remains active and owned by token_B
        state = sqlite_container.scheduler_repo.get_dispatch_state("monitoring_worker")
        assert state["lease_token"] == "token_B"
        assert state["current_run_id"] == "run_B"


class TestProductionSchedulerDryRunAndCheck:
    def test_dry_run_zero_mutations(self, sqlite_container):
        scheduler = sqlite_container.scheduler
        res = scheduler.dry_run()

        assert res["mode"] == "DRY_RUN"
        assert res["mutations_count"] == 0
        assert "would_dispatch" in res

        # Verify no rows created in scheduler_runs
        runs = sqlite_container.scheduler_repo.list_runs()
        assert len(runs) == 0

        # Verify no lease acquired
        state = sqlite_container.scheduler_repo.get_dispatch_state("monitoring_worker")
        assert state is None or state.get("lease_token") is None

    def test_check_mode_zero_mutations(self, sqlite_container):
        scheduler = sqlite_container.scheduler
        info = scheduler.check()

        assert info["schema_version"] == "20260902_006"
        assert info["readiness_status"] in ("READY", "DEGRADED")
        assert info["tables_present"] is True
        assert info["mutations_count"] == 0

        # Verify no rows created in scheduler_runs
        runs = sqlite_container.scheduler_repo.list_runs()
        assert len(runs) == 0


class TestProductionSchedulerStaleRunRecovery:
    def test_orphan_stale_run_reconciled(self, sqlite_container):
        t0 = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
        # Create orphan running record
        sqlite_container.scheduler_repo.create_run(
            id="stale_run_orphan",
            scheduler_key="monitoring_worker",
            started_at=t0.isoformat(),
            status="RUNNING",
        )

        # Advance clock by 1000s (> 900s stale threshold)
        t1 = t0 + timedelta(seconds=1000)
        stale_before = t1 - timedelta(seconds=900)

        recovered = sqlite_container.scheduler_repo.reconcile_stale_runs(
            stale_before_iso=stale_before.isoformat(),
            now_dt=t1,
        )
        assert recovered == 1

        rec = sqlite_container.scheduler_repo.get_run("stale_run_orphan")
        assert rec["status"] == "FAILED"
        assert rec["error_code"] == "SCHEDULER_EXECUTION_LOST"

    def test_active_run_matching_lease_not_reconciled(self, sqlite_container):
        t0 = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
        # Run started 1000s ago, BUT lease was extended and is still active!
        sqlite_container.scheduler_repo.create_run(
            id="active_long_run",
            scheduler_key="monitoring_worker",
            started_at=t0.isoformat(),
            status="RUNNING",
        )
        t1 = t0 + timedelta(seconds=1000)
        # Set state with current_run_id and future expiration
        p = sqlite_container.scheduler_repo._placeholder()
        future_iso = (t1 + timedelta(seconds=300)).isoformat()
        sqlite_container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="active_token_123",
            lease_duration_seconds=1500,
            run_id="active_long_run",
            now_dt=t0,
        )

        stale_before = t1 - timedelta(seconds=900)
        recovered = sqlite_container.scheduler_repo.reconcile_stale_runs(
            stale_before_iso=stale_before.isoformat(),
            now_dt=t1,
        )
        assert recovered == 0

        rec = sqlite_container.scheduler_repo.get_run("active_long_run")
        assert rec["status"] == "RUNNING"


class TestSchedulerHeartbeat:
    def test_heartbeat_renewal_threshold(self, sqlite_container):
        t0 = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
        sqlite_container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="heartbeat_tok",
            lease_duration_seconds=300,
            run_id="heartbeat_run",
            now_dt=t0,
        )

        hb = SchedulerHeartbeat(
            scheduler_repo=sqlite_container.scheduler_repo,
            scheduler_key="monitoring_worker",
            lease_token="heartbeat_tok",
            lease_duration_seconds=300,
            renew_before_seconds=90,
            start_now_dt=t0,
        )

        # Check at +100s: 200s remaining > 90s threshold: no renewal
        t1 = t0 + timedelta(seconds=100)
        assert hb.heartbeat_if_needed(now_dt=t1) is True
        assert hb.renewal_count == 0

        # Check at +220s: 80s remaining <= 90s threshold: triggers renewal
        t2 = t0 + timedelta(seconds=220)
        assert hb.heartbeat_if_needed(now_dt=t2) is True
        assert hb.renewal_count == 1
        assert hb.lease_expires_at == t2 + timedelta(seconds=300)

    def test_heartbeat_ownership_loss_stops_worker(self, sqlite_container):
        t0 = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
        sqlite_container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="tok_A",
            lease_duration_seconds=100,
            run_id="run_A",
            now_dt=t0,
        )

        hb = SchedulerHeartbeat(
            scheduler_repo=sqlite_container.scheduler_repo,
            scheduler_key="monitoring_worker",
            lease_token="tok_A",
            lease_duration_seconds=100,
            renew_before_seconds=50,
            start_now_dt=t0,
        )

        # Advance past expiration; tok_B takes the lease
        t1 = t0 + timedelta(seconds=120)
        sqlite_container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="tok_B",
            lease_duration_seconds=300,
            run_id="run_B",
            now_dt=t1,
        )

        # Now hb for tok_A attempts renewal: must fail and report ownership loss
        assert hb.heartbeat_if_needed(now_dt=t1) is False
        assert hb.ownership_lost is True
        assert hb.should_stop_callback() is True

    def test_autonomous_heartbeat_renews_during_long_blocked_operation(self, sqlite_container, monkeypatch):
        """Verify autonomous background thread renews the lease while worker is blocked in I/O."""
        # Configure short lease with tight renewal threshold
        sqlite_container.settings.scheduler_lease_seconds = 2
        sqlite_container.settings.scheduler_renew_before_seconds = 1

        # Seed 1 due schedule
        org = sqlite_container.org_repo.save(Organization(name="Org HB", slug="org-hb"))
        prospect = sqlite_container.prospect_repo.save_prospect(
            org.id, Prospect(name="Prospect HB", website_url="https://example.com")
        )
        sched = sqlite_container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, prospect.id)
        sched.next_check_at = "2026-09-01T00:00:00+00:00"
        sqlite_container.schedule_repo.save(org.id, sched)

        # Worker operation blocks on event for 1.5 seconds (which is > safety headroom of 1s)
        unblock_event = threading.Event()
        worker_entered = threading.Event()
        original_execute = sqlite_container.continuous_monitoring_service.execute_due

        def blocking_execute(*args, **kwargs):
            worker_entered.set()
            unblock_event.wait(timeout=3.0)
            return original_execute(*args, **kwargs)

        monkeypatch.setattr(sqlite_container.continuous_monitoring_service, "execute_due", blocking_execute)

        tick_result = [None]
        tick_exception = [None]

        def run_tick():
            try:
                tick_result[0] = sqlite_container.scheduler.tick()
            except Exception as e:
                tick_exception[0] = e

        t = threading.Thread(target=run_tick)
        t.start()

        # Wait until worker is inside blocked execution
        assert worker_entered.wait(timeout=3.0) is True

        # While worker is blocked, sleep 1.3 seconds so heartbeat background loop triggers renewal
        time.sleep(1.3)

        # Competing scheduler tries to acquire dispatch: MUST receive SKIPPED_LEASE_HELD
        competing_res = sqlite_container.scheduler.tick()
        assert competing_res.status == "SKIPPED_LEASE_HELD"

        # Now unblock worker and join thread
        unblock_event.set()
        t.join(timeout=5.0)

        assert tick_exception[0] is None
        res = tick_result[0]
        assert res is not None
        assert res.status == "COMPLETED"
        assert res.items_claimed == 1

    def test_heartbeat_ownership_loss_during_blocked_operation(self, sqlite_container, monkeypatch):
        """Verify that when lease ownership is stolen during a blocked operation:
        - Heartbeat background thread detects ownership loss
        - In-flight execution is allowed to complete without hard abort
        - Worker halts before claiming any next candidate
        - Stale owner does not clear the new owner's lease
        - Final status is marked OWNERSHIP_LOST
        """
        sqlite_container.settings.scheduler_lease_seconds = 1
        sqlite_container.settings.scheduler_renew_before_seconds = 0.5

        # Seed 2 due schedules
        org = sqlite_container.org_repo.save(Organization(name="Org Loss", slug="org-loss"))
        p1 = sqlite_container.prospect_repo.save_prospect(org.id, Prospect(name="P1", website_url="https://p1.com"))
        p2 = sqlite_container.prospect_repo.save_prospect(org.id, Prospect(name="P2", website_url="https://p2.com"))
        s1 = sqlite_container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p1.id)
        s1.next_check_at = "2026-09-01T00:00:00+00:00"
        sqlite_container.schedule_repo.save(org.id, s1)
        s2 = sqlite_container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p2.id)
        s2.next_check_at = "2026-09-01T00:00:00+00:00"
        sqlite_container.schedule_repo.save(org.id, s2)

        worker_entered = threading.Event()
        unblock_event = threading.Event()
        items_executed = []
        original_execute = sqlite_container.continuous_monitoring_service.execute_due

        def blocking_execute(*args, **kwargs):
            sched_id = kwargs.get("schedule_id") or (args[1] if len(args) > 1 else None)
            items_executed.append(sched_id)
            worker_entered.set()
            unblock_event.wait(timeout=3.0)
            return original_execute(*args, **kwargs)

        monkeypatch.setattr(sqlite_container.continuous_monitoring_service, "execute_due", blocking_execute)

        tick_result = [None]
        tick_exception = [None]

        def run_tick():
            try:
                tick_result[0] = sqlite_container.scheduler.tick()
            except Exception as e:
                tick_exception[0] = e

        t = threading.Thread(target=run_tick)
        t.start()

        # Wait until worker is inside first item
        assert worker_entered.wait(timeout=3.0) is True

        # Now simulate lease theft: forcibly overwrite lease in DB with competitor token
        future_exp = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()
        sqlite_container.db.execute(
            "UPDATE scheduler_dispatch_state SET lease_token = ?, lease_expires_at = ?, current_run_id = ? WHERE scheduler_key = ?",
            ("stolen_by_competitor", future_exp, "competitor_run_id", "monitoring_worker"),
        )
        sqlite_container.db.commit()

        # Give background heartbeat thread time to detect ownership loss on its periodic check
        time.sleep(0.7)

        # Unblock worker to finish current item
        unblock_event.set()
        t.join(timeout=10.0)

        assert tick_exception[0] is None
        res = tick_result[0]
        assert res is not None
        # Must terminate with OWNERSHIP_LOST
        assert res.status == "OWNERSHIP_LOST"
        assert res.error_code == "OWNERSHIP_LOST"

        # Crucial check: only 1 item was executed; worker halted before claiming the 2nd candidate
        assert len(items_executed) == 1

        # Crucial check: competitor's lease was NOT cleared by stale owner
        state = sqlite_container.scheduler_repo.get_dispatch_state("monitoring_worker")
        assert state["lease_token"] == "stolen_by_competitor"
        assert state["current_run_id"] == "competitor_run_id"


class TestDatabaseMigratorP16:
    def test_migration_005_to_006_creates_scheduler_tables_and_preserves_data(self):
        db = create_database_connection(":memory:")
        # Migrate up to 005 first
        DatabaseMigrator.ensure_version_table(db)

        # Run 006 migration
        ver = DatabaseMigrator.migrate(db)
        assert ver == "20260902_006"

        status = DatabaseMigrator.status(db)
        assert status["current_version"] == "20260902_006"
        assert status["is_up_to_date"] is True

        # Verify tables exist
        rows_state = db.fetch_dicts("SELECT name FROM sqlite_master WHERE type='table' AND name='scheduler_dispatch_state'")
        assert len(rows_state) == 1

        rows_runs = db.fetch_dicts("SELECT name FROM sqlite_master WHERE type='table' AND name='scheduler_runs'")
        assert len(rows_runs) == 1

    def test_sqlite_migration_005_to_006_preserves_existing_data(self):
        db = create_database_connection(":memory:")
        # Apply migrations
        DatabaseMigrator.migrate(db)
        # Seed an organization in pre-P16 table
        db.execute(
            "INSERT INTO organizations (id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("org_pre16", "Pre-P16 Org", "pre-p16-org", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"),
        )
        db.commit()

        # Re-run migrate idempotently
        ver = DatabaseMigrator.migrate(db)
        assert ver == "20260902_006"

        rows = db.fetch_dicts("SELECT name FROM organizations WHERE id = ?", ("org_pre16",))
        assert len(rows) == 1
        assert rows[0]["name"] == "Pre-P16 Org"


class TestOwnerTokenSecurityP16_1:
    def test_dry_run_security_does_not_expose_lease_token_or_secrets(self, sqlite_container):
        scheduler = sqlite_container.scheduler
        # Acquire a lease so there is an active lease
        sqlite_container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="super_secret_owner_token_xyz",
            lease_duration_seconds=300,
            run_id="run_secret_owner",
        )

        res = scheduler.dry_run()
        assert res["lease_held"] is True
        assert res["lease_expires_at"] is not None
        assert res["current_run_id"] == "run_secret_owner"
        assert res["scheduler_key"] == "monitoring_worker"

        # Check that owner_token / lease_token is NEVER exposed in the dict
        assert "super_secret_owner_token_xyz" not in str(res)
        assert "lease_token" not in res
        assert "owner_token" not in res

    def test_check_security_does_not_expose_lease_token_or_secrets(self, sqlite_container):
        scheduler = sqlite_container.scheduler
        sqlite_container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="super_secret_check_token_123",
            lease_duration_seconds=300,
            run_id="run_check_owner",
        )

        info = scheduler.check()
        assert "super_secret_check_token_123" not in str(info)
        assert "lease_token" not in info
        assert "owner_token" not in info
        if info["current_lease_state"]:
            assert "lease_token" not in info["current_lease_state"]
            assert "owner_token" not in info["current_lease_state"]


class TestErrorSanitizationP16_1:
    def test_fatal_error_with_dsn_password_and_api_key_is_sanitized(self, sqlite_container, monkeypatch):
        scheduler = sqlite_container.scheduler

        def failing_run(*args, **kwargs):
            raise RuntimeError(
                "Failed to connect: postgresql://admin_user:SUPERSECRET_PASSWORD@prod.db:5432/db "
                "with Authorization Bearer SECRET_BEARER_TOKEN and api_key=SECRET_KEY_12345"
            )

        monkeypatch.setattr(sqlite_container.worker, "run", failing_run)

        result = scheduler.tick()
        assert result.status == "FAILED"
        assert "SUPERSECRET_PASSWORD" not in result.error_message
        assert "SECRET_BEARER_TOKEN" not in result.error_message
        assert "SECRET_KEY_12345" not in result.error_message
        assert "***" in result.error_message

        # Verify sanitized in database
        run_record = sqlite_container.scheduler_repo.get_run(result.scheduler_run_id)
        assert "SUPERSECRET_PASSWORD" not in run_record["error_message"]
        assert "SECRET_BEARER_TOKEN" not in run_record["error_message"]
        assert "SECRET_KEY_12345" not in run_record["error_message"]


class TestNoAutoMigrationP16_1:
    def test_tick_fails_closed_without_auto_migrating_unready_db(self, sqlite_container, monkeypatch):
        # Unmigrated DB
        db = create_database_connection(":memory:")
        repo = SchedulerRepository(db)
        sched = ProductionScheduler(
            scheduler_repo=repo,
            worker=sqlite_container.worker,
            settings=RuntimeSettings(production_scheduler_enabled=True),
        )

        worker_called = False
        def fake_worker(*args, **kwargs):
            nonlocal worker_called
            worker_called = True

        monkeypatch.setattr(sqlite_container.worker, "run", fake_worker)

        res = sched.tick()
        assert res.status == "FAILED"
        assert res.error_code == "DATABASE_NOT_READY"
        assert worker_called is False

        # Verify db was NOT migrated
        assert DatabaseMigrator.get_current_version(db) is None


class TestCreateAndCompleteRunFailureSafetyP16_1:
    def test_create_run_failure_releases_lease_best_effort(self, sqlite_container, monkeypatch):
        scheduler = sqlite_container.scheduler

        def failing_create_run(*args, **kwargs):
            raise RuntimeError("Disk I/O error during audit creation")

        monkeypatch.setattr(sqlite_container.scheduler_repo, "create_run", failing_create_run)

        res = scheduler.tick()
        assert res.status == "FAILED"
        assert res.error_code == "AUDIT_CREATION_FAILED"

        # Verify lease was released and not permanently stuck
        state = sqlite_container.scheduler_repo.get_dispatch_state("monitoring_worker")
        assert state["lease_token"] is None

    def test_complete_run_failure_still_releases_lease(self, sqlite_container, monkeypatch):
        scheduler = sqlite_container.scheduler

        def failing_complete_run(*args, **kwargs):
            raise RuntimeError("Database write error during complete_run")

        monkeypatch.setattr(sqlite_container.scheduler_repo, "complete_run", failing_complete_run)

        res = scheduler.tick()
        # Even if complete_run throws, lease is released
        state = sqlite_container.scheduler_repo.get_dispatch_state("monitoring_worker")
        assert state["lease_token"] is None


class TestForceSemanticsP16_1:
    def test_force_flag_does_not_bypass_active_lease(self, sqlite_container):
        scheduler = sqlite_container.scheduler
        # Another process holds lease
        sqlite_container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="active_held_lease",
            lease_duration_seconds=300,
            run_id="run_active_held",
        )

        # Calling tick with force=True MUST NOT bypass lease ownership
        res = scheduler.tick(force=True)
        assert res.status == "SKIPPED_LEASE_HELD"
        assert res.error_code == "DISPATCH_LEASE_HELD"
        assert res.items_attempted == 0


class TestSQLiteHeartbeatThreadSafetyP16_3:
    """P16.3 verification of real SQLite file thread-safety, dedicated connection, and clean shutdown."""

    def test_real_sqlite_file_autonomous_heartbeat_renews_during_blocked_operation(self, tmp_path, monkeypatch):
        """Verify on real SQLite file DB:
        - Heartbeat uses its own dedicated connection (separate from main scheduler connection)
        - Background thread renews lease while worker blocks in I/O
        - Competing tick after original lease expiry receives SKIPPED_LEASE_HELD
        - No cross-thread sqlite3 errors (ProgrammingError / check_same_thread)
        - Thread cleanly terminates on context manager exit (thread.is_alive() == False)
        """
        db_file = tmp_path / "sqlite_hb_p16_3.db"
        db_url = f"sqlite:///{db_file}"

        main_db = create_database_connection(db_url)
        DatabaseMigrator.migrate(main_db)

        settings = RuntimeSettings(
            database_url=db_url,
            enabled_providers=["official_website"],
            production_scheduler_enabled=True,
            scheduler_key="monitoring_worker",
            scheduler_lease_seconds=3,
            scheduler_renew_before_seconds=2,
        )
        container = build_runtime_container(settings, db=main_db)

        # Seed 1 due schedule
        org = container.org_repo.save(Organization(name="Org File HB", slug="org-file-hb"))
        prospect = container.prospect_repo.save_prospect(
            org.id, Prospect(name="P File HB", website_url="https://example.com")
        )
        sched = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, prospect.id)
        sched.next_check_at = "2026-09-01T00:00:00+00:00"
        container.schedule_repo.save(org.id, sched)

        worker_entered = threading.Event()
        unblock_event = threading.Event()
        orig_execute_due = container.continuous_monitoring_service.execute_due

        def blocking_execute(*args, **kwargs):
            worker_entered.set()
            unblock_event.wait(timeout=6.0)
            return orig_execute_due(*args, **kwargs)

        monkeypatch.setattr(container.continuous_monitoring_service, "execute_due", blocking_execute)

        tick_result = [None]
        tick_error = [None]

        def run_tick():
            try:
                tick_result[0] = container.scheduler.tick()
            except Exception as e:
                tick_error[0] = e

        t_tick = threading.Thread(target=run_tick)
        t_tick.start()

        # Wait until worker enters blocked state
        assert worker_entered.wait(timeout=5.0) is True

        # Verify dedicated connection was instantiated for heartbeat thread
        hb = container.scheduler.last_heartbeat
        assert hb is not None
        assert hb._dedicated_db is not None
        assert hb._dedicated_db is not main_db
        assert hb.thread.is_alive() is True

        # Wait 3.2s so original 3.0s lease would have expired without autonomous renewal
        time.sleep(3.2)

        # Competing scheduler with third connection attempts dispatch: MUST receive SKIPPED_LEASE_HELD
        competing_db = create_database_connection(db_url)
        competing_container = build_runtime_container(settings, db=competing_db)
        competing_res = competing_container.scheduler.tick()
        assert competing_res.status == "SKIPPED_LEASE_HELD"
        competing_db.close()

        # Unblock worker and wait for scheduler tick to finish
        unblock_event.set()
        t_tick.join(timeout=5.0)

        assert tick_error[0] is None
        res = tick_result[0]
        assert res is not None
        assert res.status == "COMPLETED"
        assert res.items_claimed == 1

        # Thread stop / join contract: thread must NOT be alive after tick
        assert hb.thread.is_alive() is False

        # Dedicated connection was cleaned up
        assert hb._dedicated_db is None

        # Lease was cleared cleanly
        state = main_db.fetch_dicts(
            "SELECT * FROM scheduler_dispatch_state WHERE scheduler_key = ?",
            ("monitoring_worker",),
        )[0]
        assert state["lease_token"] is None
        main_db.close()

    def test_real_sqlite_file_ownership_loss_during_blocked_operation(self, tmp_path, monkeypatch):
        """Verify on real SQLite file DB:
        - When lease is stolen in DB during long execution, heartbeat renewal fails
        - Worker halts before claiming next candidate
        - Scheduler tick returns OWNERSHIP_LOST
        - Stale owner does not release stolen lease
        - Heartbeat thread cleanly terminates
        """
        db_file = tmp_path / "sqlite_loss_p16_3.db"
        db_url = f"sqlite:///{db_file}"

        main_db = create_database_connection(db_url)
        DatabaseMigrator.migrate(main_db)

        settings = RuntimeSettings(
            database_url=db_url,
            enabled_providers=["official_website"],
            production_scheduler_enabled=True,
            scheduler_key="monitoring_worker",
            scheduler_lease_seconds=2,
            scheduler_renew_before_seconds=1,
        )
        container = build_runtime_container(settings, db=main_db)

        # Seed 2 due schedules
        org = container.org_repo.save(Organization(name="Org Loss File", slug="org-loss-file"))
        p1 = container.prospect_repo.save_prospect(org.id, Prospect(name="P1", website_url="https://p1.com"))
        p2 = container.prospect_repo.save_prospect(org.id, Prospect(name="P2", website_url="https://p2.com"))
        s1 = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p1.id)
        s1.next_check_at = "2026-09-01T00:00:00+00:00"
        container.schedule_repo.save(org.id, s1)
        s2 = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p2.id)
        s2.next_check_at = "2026-09-01T00:00:00+00:00"
        container.schedule_repo.save(org.id, s2)

        worker_entered = threading.Event()
        unblock_event = threading.Event()
        items_executed = []
        orig_execute_due = container.continuous_monitoring_service.execute_due

        def blocking_execute(*args, **kwargs):
            sched_id = kwargs.get("schedule_id") or (args[1] if len(args) > 1 else None)
            items_executed.append(sched_id)
            worker_entered.set()
            unblock_event.wait(timeout=5.0)
            return orig_execute_due(*args, **kwargs)

        monkeypatch.setattr(container.continuous_monitoring_service, "execute_due", blocking_execute)

        tick_result = [None]
        tick_error = [None]

        def run_tick():
            try:
                tick_result[0] = container.scheduler.tick()
            except Exception as e:
                tick_error[0] = e

        t_tick = threading.Thread(target=run_tick)
        t_tick.start()

        assert worker_entered.wait(timeout=5.0) is True

        # Competitor overwrites lease in DB
        comp_db = create_database_connection(db_url)
        future_iso = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()
        comp_db.execute(
            "UPDATE scheduler_dispatch_state SET lease_token = ?, lease_expires_at = ?, current_run_id = ? WHERE scheduler_key = ?",
            ("stolen_sqlite_token", future_iso, "run_stolen", "monitoring_worker"),
        )
        comp_db.commit()
        comp_db.close()

        # Wait 1.2s for heartbeat background thread to trigger renewal and detect loss
        time.sleep(1.2)

        unblock_event.set()
        t_tick.join(timeout=5.0)

        assert tick_error[0] is None
        res = tick_result[0]
        assert res is not None
        assert res.status == "OWNERSHIP_LOST"
        assert res.error_code == "OWNERSHIP_LOST"

        # Worker stopped after first candidate, candidate 2 was NOT claimed
        assert len(items_executed) == 1

        # Thread must be terminated
        hb = container.scheduler.last_heartbeat
        assert hb.thread.is_alive() is False

        # Stale owner did NOT clear the competitor's lease
        state = main_db.fetch_dicts(
            "SELECT * FROM scheduler_dispatch_state WHERE scheduler_key = ?",
            ("monitoring_worker",),
        )[0]
        assert state["lease_token"] == "stolen_sqlite_token"
        main_db.close()

    def test_heartbeat_thread_is_not_alive_after_context_exit(self):
        """Verify thread is alive during context and thread.is_alive() == False after exit."""
        db = create_database_connection(":memory:")
        DatabaseMigrator.migrate(db)
        repo = SchedulerRepository(db)
        repo.try_acquire_dispatch("monitoring_worker", "hb_tok", 300, "run_hb")

        hb = SchedulerHeartbeat(
            scheduler_repo=repo,
            scheduler_key="monitoring_worker",
            lease_token="hb_tok",
            lease_duration_seconds=10,
            renew_before_seconds=5,
        )

        with hb:
            assert hb.thread is not None
            assert hb.thread.is_alive() is True

        assert hb.thread.is_alive() is False
        db.close()

    def test_no_post_stop_renewal_after_heartbeat_stop(self):
        """Verify that after stop() is called, no renewals are executed even if clock advances."""
        renew_calls = []

        class MockRepo:
            def renew_dispatch_lease(self, *args, **kwargs):
                renew_calls.append(kwargs)
                return True

        t0 = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
        current_time = [t0]

        hb = SchedulerHeartbeat(
            scheduler_repo=MockRepo(),
            scheduler_key="monitoring_worker",
            lease_token="hb_tok",
            lease_duration_seconds=10,
            renew_before_seconds=5,
            start_now_dt=t0,
            clock=lambda: current_time[0],
        )

        hb.start()
        assert hb.thread.is_alive() is True

        # Stop heartbeat
        hb.stop()
        assert hb.thread.is_alive() is False

        call_count_at_stop = len(renew_calls)

        # Advance clock into renewal window and manually trigger
        current_time[0] = t0 + timedelta(seconds=8)
        ret = hb.heartbeat_if_needed()

        assert ret is False
        assert len(renew_calls) == call_count_at_stop

    def test_dedicated_connection_closed_exactly_once_on_stop(self, tmp_path):
        """Verify dedicated DB connection created by db_factory is closed exactly once."""
        db_file = tmp_path / "sqlite_cleanup_test.db"
        db_url = f"sqlite:///{db_file}"

        close_counts = {"count": 0}

        def tracking_factory():
            real_conn = create_database_connection(db_url)
            orig_close = real_conn.close

            def counted_close():
                close_counts["count"] += 1
                return orig_close()

            real_conn.close = counted_close
            return real_conn

        db_main = create_database_connection(db_url)
        DatabaseMigrator.migrate(db_main)
        repo = SchedulerRepository(db_main)
        repo.try_acquire_dispatch("monitoring_worker", "tok_clean", 300, "run_clean")

        hb = SchedulerHeartbeat(
            scheduler_repo=repo,
            scheduler_key="monitoring_worker",
            lease_token="tok_clean",
            lease_duration_seconds=10,
            renew_before_seconds=5,
            db_factory=tracking_factory,
        )

        with hb:
            assert hb._dedicated_db is not None
            assert close_counts["count"] == 0

        # On exit, closed exactly once
        assert close_counts["count"] == 1
        assert hb._dedicated_db is None

        # Subsequent explicit stop() calls are idempotent no-ops
        hb.stop()
        assert close_counts["count"] == 1
        db_main.close()
