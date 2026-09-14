"""Automated integration test suite for BopClients P16 PostgreSQL Distributed Scheduler Coordination."""

import os
import time
import pytest
import threading
from datetime import datetime, timezone, timedelta

from bopclients.runtime.settings import RuntimeSettings, AppEnvironment
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.container import build_runtime_container
from bopclients.infrastructure.db.connection import create_database_connection, PostgresConnectionAdapter
from bopclients.infrastructure.repositories.scheduler_repository import SchedulerRepository
from bopclients.application.production_scheduler import ProductionScheduler
from bopclients.application.scheduler_heartbeat import SchedulerHeartbeat

TEST_PG_URL = os.environ.get(
    "BOPCLIENTS_TEST_POSTGRES_URL",
    "postgresql://bop:bop_test_password@localhost:55432/bopclients_test",
).strip()

HAS_POSTGRES_TEST_DB = False
try:
    _test_conn = create_database_connection(TEST_PG_URL)
    _test_conn.execute("SELECT 1")
    _test_conn.close()
    HAS_POSTGRES_TEST_DB = True
except Exception:
    HAS_POSTGRES_TEST_DB = False


@pytest.mark.skipif(not HAS_POSTGRES_TEST_DB, reason="PostgreSQL test DB not available")
class TestPostgresSchedulerP16:
    def setup_method(self):
        """Ensure clean database and up-to-date schema before each test."""
        db = create_database_connection(TEST_PG_URL)
        try:
            DatabaseMigrator.migrate(db)
            # Clear scheduler tables for test isolation
            db.execute("DELETE FROM scheduler_runs;")
            db.execute("DELETE FROM scheduler_dispatch_state;")
            db.commit()
        finally:
            db.close()

    def test_postgres_migration_006_and_readiness(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            ver = DatabaseMigrator.migrate(db)
            assert ver in ("20260902_006", "20260902_007")

            status = DatabaseMigrator.status(db)
            assert status["current_version"] in ("20260902_006", "20260902_007")
            assert status["is_up_to_date"] is True

            settings = RuntimeSettings(
                database_url=TEST_PG_URL,
                enabled_providers=["official_website"],
                production_scheduler_enabled=True,
            )
            res = RuntimeReadinessCheck.check(settings, db=db)
            assert res.status == ReadinessStatus.READY
            assert res.database_connected is True
            assert res.tables_present is True

            # Verify tables in postgres schema
            rows = db.fetch_dicts(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('scheduler_dispatch_state', 'scheduler_runs')"
            )
            table_names = {r["table_name"] for r in rows}
            assert "scheduler_dispatch_state" in table_names
            assert "scheduler_runs" in table_names
        finally:
            db.close()

    def test_postgres_concurrent_scheduler_tick_race(self):
        """Two independent PostgreSQL connections launch simultaneous ticks on the same key. Exactly one must acquire."""
        db_a = create_database_connection(TEST_PG_URL)
        db_b = create_database_connection(TEST_PG_URL)

        try:
            settings_a = RuntimeSettings(
                database_url=TEST_PG_URL,
                enabled_providers=["official_website"],
                production_scheduler_enabled=True,
                scheduler_key="monitoring_worker",
                scheduler_lease_seconds=300,
            )
            settings_b = RuntimeSettings(
                database_url=TEST_PG_URL,
                enabled_providers=["official_website"],
                production_scheduler_enabled=True,
                scheduler_key="monitoring_worker",
                scheduler_lease_seconds=300,
            )

            container_a = build_runtime_container(settings_a, db=db_a)
            container_b = build_runtime_container(settings_b, db=db_b)

            results = []
            barrier = threading.Barrier(2)

            def run_tick(scheduler, label):
                barrier.wait()
                res = scheduler.tick()
                results.append((label, res))

            t1 = threading.Thread(target=run_tick, args=(container_a.scheduler, "A"))
            t2 = threading.Thread(target=run_tick, args=(container_b.scheduler, "B"))

            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)

            assert len(results) == 2
            statuses = [res.status for _, res in results]

            # Exactly one COMPLETED, one SKIPPED_LEASE_HELD
            assert "COMPLETED" in statuses
            assert "SKIPPED_LEASE_HELD" in statuses

            # Under ACQUIRED_DISPATCH_ONLY: only acquired dispatches create scheduler_runs
            runs = container_a.scheduler_repo.list_runs("monitoring_worker")
            assert len(runs) == 1
            assert runs[0]["status"] == "COMPLETED"

        finally:
            db_a.close()
            db_b.close()

    def test_postgres_lease_expiry_reclaim(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            repo = SchedulerRepository(db)
            t0 = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)

            # Scheduler A acquires short lease (60s)
            acquired_a, _ = repo.try_acquire_dispatch(
                scheduler_key="monitoring_worker",
                lease_token="token_a_pg",
                lease_duration_seconds=60,
                run_id="run_a_pg",
                now_dt=t0,
            )
            assert acquired_a is True

            # Scheduler B attempts at t0+30s: fails
            t_mid = t0 + timedelta(seconds=30)
            acquired_mid, reason_mid = repo.try_acquire_dispatch(
                scheduler_key="monitoring_worker",
                lease_token="token_b_pg",
                lease_duration_seconds=60,
                run_id="run_b_pg",
                now_dt=t_mid,
            )
            assert acquired_mid is False
            assert reason_mid == "LEASE_HELD"

            # Scheduler B attempts at t0+70s (after expiration): succeeds
            t_after = t0 + timedelta(seconds=70)
            acquired_b, _ = repo.try_acquire_dispatch(
                scheduler_key="monitoring_worker",
                lease_token="token_b_pg",
                lease_duration_seconds=120,
                run_id="run_b_pg",
                now_dt=t_after,
            )
            assert acquired_b is True

            state = repo.get_dispatch_state("monitoring_worker")
            assert state["lease_token"] == "token_b_pg"
            assert state["current_run_id"] == "run_b_pg"
        finally:
            db.close()

    def test_postgres_stale_release_token_safety(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            repo = SchedulerRepository(db)
            t0 = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)

            repo.try_acquire_dispatch(
                scheduler_key="monitoring_worker",
                lease_token="tok_old",
                lease_duration_seconds=60,
                run_id="run_old",
                now_dt=t0,
            )

            # Expire and acquire by new owner
            t1 = t0 + timedelta(seconds=70)
            repo.try_acquire_dispatch(
                scheduler_key="monitoring_worker",
                lease_token="tok_new",
                lease_duration_seconds=300,
                run_id="run_new",
                now_dt=t1,
            )

            # Stale owner attempts release
            released = repo.release_dispatch_lease(
                scheduler_key="monitoring_worker",
                lease_token="tok_old",
                now_dt=t1,
            )
            assert released is False

            # Current lease remains active with tok_new
            state = repo.get_dispatch_state("monitoring_worker")
            assert state["lease_token"] == "tok_new"
            assert state["current_run_id"] == "run_new"
        finally:
            db.close()

    def test_postgres_stale_run_recovery_and_new_owner_protected(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            repo = SchedulerRepository(db)
            t0 = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)

            # 1. Run A started long ago and abandoned
            repo.create_run(
                id="run_A_crashed",
                scheduler_key="monitoring_worker",
                started_at=t0.isoformat(),
                status="RUNNING",
            )

            # 2. Run B is currently active with valid lease
            t1 = t0 + timedelta(seconds=1200)
            repo.create_run(
                id="run_B_active",
                scheduler_key="monitoring_worker",
                started_at=t1.isoformat(),
                status="RUNNING",
            )
            repo.try_acquire_dispatch(
                scheduler_key="monitoring_worker",
                lease_token="tok_B",
                lease_duration_seconds=300,
                run_id="run_B_active",
                now_dt=t1,
            )

            # Run stale recovery (stale threshold 900s)
            stale_before = t1 - timedelta(seconds=900)
            recovered = repo.reconcile_stale_runs(
                stale_before_iso=stale_before.isoformat(),
                now_dt=t1,
            )

            assert recovered == 1

            # Run A recovered to FAILED
            rec_a = repo.get_run("run_A_crashed")
            assert rec_a["status"] == "FAILED"
            assert rec_a["error_code"] == "SCHEDULER_EXECUTION_LOST"

            # Run B is UNTOUCHED
            rec_b = repo.get_run("run_B_active")
            assert rec_b["status"] == "RUNNING"

            # Lease remains held by B
            state = repo.get_dispatch_state("monitoring_worker")
            assert state["lease_token"] == "tok_B"
            assert state["current_run_id"] == "run_B_active"
        finally:
            db.close()

    def test_postgres_heartbeat_renewal_keeps_ownership(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            repo = SchedulerRepository(db)
            t0 = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)

            repo.try_acquire_dispatch(
                scheduler_key="monitoring_worker",
                lease_token="tok_hb",
                lease_duration_seconds=100,
                run_id="run_hb",
                now_dt=t0,
            )

            hb = SchedulerHeartbeat(
                scheduler_repo=repo,
                scheduler_key="monitoring_worker",
                lease_token="tok_hb",
                lease_duration_seconds=100,
                renew_before_seconds=40,
                start_now_dt=t0,
            )

            # Advance to +70s (30s remaining <= 40s threshold) -> renew
            t1 = t0 + timedelta(seconds=70)
            renewed = hb.heartbeat_if_needed(now_dt=t1)
            assert renewed is True
            assert hb.renewal_count == 1

            # Competing scheduler at +80s should be denied because lease was renewed
            t2 = t0 + timedelta(seconds=80)
            acquired_comp, _ = repo.try_acquire_dispatch(
                scheduler_key="monitoring_worker",
                lease_token="tok_comp",
                lease_duration_seconds=100,
                run_id="run_comp",
                now_dt=t2,
            )
            assert acquired_comp is False

            # Verify lease in DB extends to t1 + 100s
            state = repo.get_dispatch_state("monitoring_worker")
            assert state["lease_token"] == "tok_hb"
            expected_exp = (t1 + timedelta(seconds=100)).isoformat()
            assert state["lease_expires_at"] == expected_exp
        finally:
            db.close()

    def test_postgres_migration_preserves_pre_p16_data(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            # Ensure schema 006 is present
            ver = DatabaseMigrator.migrate(db)
            assert ver in ("20260902_006", "20260902_007")

            import uuid
            ts = int(time.time() * 1000)
            org_id = f"org_pg_pres_{ts}"
            bop_org_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO organizations (id, bop_organization_id, name, slug, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (org_id, bop_org_id, f"PG Preserved Org {ts}", f"pg-pres-{ts}", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"),
            )
            db.commit()

            # Re-run migration idempotently
            ver_after = DatabaseMigrator.migrate(db)
            assert ver_after in ("20260902_006", "20260902_007")

            # Verify data is fully preserved
            rows = db.fetch_dicts("SELECT name FROM organizations WHERE id = %s", (org_id,))
            assert len(rows) == 1
            assert rows[0]["name"] == f"PG Preserved Org {ts}"
        finally:
            db.close()
