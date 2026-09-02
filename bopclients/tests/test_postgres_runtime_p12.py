"""Automated integration test suite for BopClients P12 PostgreSQL Runtime & Multi-Worker Readiness."""

import os
import time
import pytest
import threading
from datetime import datetime, timezone
from bopclients.runtime.settings import RuntimeSettings, AppEnvironment
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.container import build_runtime_container
from bopclients.infrastructure.db.connection import create_database_connection, PostgresConnectionAdapter, SQLiteConnectionAdapter
from bopclients.domain.organization import Organization
from bopclients.domain.prospect import Prospect

# Detect PostgreSQL test DB availability
TEST_PG_URL = os.environ.get("BOPCLIENTS_TEST_POSTGRES_URL", "postgresql://bop:bop_test_password@localhost:55432/bopclients_test").strip()

HAS_POSTGRES_TEST_DB = False
try:
    _test_conn = create_database_connection(TEST_PG_URL)
    _test_conn.execute("SELECT 1")
    _test_conn.close()
    HAS_POSTGRES_TEST_DB = True
except Exception:
    HAS_POSTGRES_TEST_DB = False


class TestDatabaseConnectionFactoryP12:
    def test_connection_factory_sqlite(self):
        conn = create_database_connection(":memory:")
        assert isinstance(conn, SQLiteConnectionAdapter)
        assert conn.backend_name == "sqlite"
        assert conn.placeholder == "?"
        conn.close()

    @pytest.mark.skipif(not HAS_POSTGRES_TEST_DB, reason="PostgreSQL test DB not available")
    def test_connection_factory_postgres(self):
        conn = create_database_connection(TEST_PG_URL)
        assert isinstance(conn, PostgresConnectionAdapter)
        assert conn.backend_name == "postgresql"
        assert conn.placeholder == "%s"
        conn.close()


@pytest.mark.skipif(not HAS_POSTGRES_TEST_DB, reason="PostgreSQL test DB not available")
class TestPostgresRuntimeP12:
    def test_postgres_migration_and_readiness(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            ver = DatabaseMigrator.migrate(db)
            assert ver == DatabaseMigrator.EXPECTED_VERSION
            status = DatabaseMigrator.status(db)
            assert status["is_up_to_date"] is True

            settings = RuntimeSettings(database_url=TEST_PG_URL, enabled_providers=["official_website"])
            res = RuntimeReadinessCheck.check(settings, db=db)
            assert res.status == ReadinessStatus.READY
            assert res.database_connected is True
            assert res.tables_present is True
            assert res.provider_matrix["official_website"] == "READY"
        finally:
            db.close()

    def test_postgres_tenant_isolation(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            DatabaseMigrator.migrate(db)
            settings = RuntimeSettings(database_url=TEST_PG_URL, enabled_providers=["official_website"])
            container = build_runtime_container(settings, db=db)

            ts = int(time.time() * 1000)
            org_a = container.org_repo.save(Organization(name=f"Unit Org A {ts}", slug=f"unit-org-a-{ts}"))
            org_b = container.org_repo.save(Organization(name=f"Unit Org B {ts}", slug=f"unit-org-b-{ts}"))

            p_a = container.prospect_repo.save_prospect(org_a.id, Prospect(name="Prospect Org A", website_url="https://orga.com"))
            p_b = container.prospect_repo.save_prospect(org_b.id, Prospect(name="Prospect Org B", website_url="https://orgb.com"))

            # Org A cannot view Org B prospects
            assert container.prospect_repo.get_prospect_by_id(org_a.id, p_b.id) is None
            assert container.prospect_repo.get_prospect_by_id(org_b.id, p_a.id) is None
        finally:
            db.close()

    def test_postgres_atomic_claim_concurrency_race(self):
        db_init = create_database_connection(TEST_PG_URL)
        try:
            DatabaseMigrator.migrate(db_init)
            settings = RuntimeSettings(database_url=TEST_PG_URL, enabled_providers=["official_website"])
            container = build_runtime_container(settings, db=db_init)

            ts = int(time.time() * 1000)
            org = container.org_repo.save(Organization(name=f"Race Org {ts}", slug=f"race-org-{ts}"))
            p = container.prospect_repo.save_prospect(org.id, Prospect(name="Race Prospect", website_url="https://race.com"))
            schedule = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p.id)

            schedule.next_check_at = "2026-09-01T00:00:00+00:00"
            container.schedule_repo.save(org.id, schedule)

            # Concurrent claim race with two independent Postgres connections
            db1 = create_database_connection(TEST_PG_URL)
            db2 = create_database_connection(TEST_PG_URL)
            c1 = build_runtime_container(settings, db=db1)
            c2 = build_runtime_container(settings, db=db2)

            barrier = threading.Barrier(2)
            results = {}

            def worker_race(w_name, repo_inst):
                barrier.wait()
                now_str = datetime.now(timezone.utc).isoformat()
                res = repo_inst.claim_due_work(org.id, schedule.id, lease_token=f"token-{w_name}", lease_duration_seconds=300, now_iso=now_str)
                results[w_name] = res

            t1 = threading.Thread(target=worker_race, args=("W1", c1.schedule_repo))
            t2 = threading.Thread(target=worker_race, args=("W2", c2.schedule_repo))
            t1.start()
            t2.start()
            t1.join()
            t2.join()

            db1.close()
            db2.close()

            # Exactly one worker wins the claim race
            assert sum(1 for v in results.values() if v is True) == 1
        finally:
            db_init.close()

    def test_postgres_stale_owner_lease_renewal_rejected(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            DatabaseMigrator.migrate(db)
            settings = RuntimeSettings(database_url=TEST_PG_URL, enabled_providers=["official_website"])
            container = build_runtime_container(settings, db=db)

            ts = int(time.time() * 1000)
            org = container.org_repo.save(Organization(name=f"Stale Org {ts}", slug=f"stale-org-{ts}"))
            p = container.prospect_repo.save_prospect(org.id, Prospect(name="Stale Prospect", website_url="https://stale.com"))
            schedule = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p.id)

            schedule.next_check_at = "2026-09-01T00:00:00+00:00"
            container.schedule_repo.save(org.id, schedule)

            now_str = datetime.now(timezone.utc).isoformat()
            claimed = container.schedule_repo.claim_due_work(org.id, schedule.id, lease_token="token-valid-owner", lease_duration_seconds=300, now_iso=now_str)
            assert claimed is True

            # Attempt lease renewal with wrong lease token
            renewed = container.schedule_repo.renew_lease(org.id, schedule.id, lease_token="token-stale-hacker", lease_duration_seconds=300, now_iso=now_str)
            assert renewed is False

            # Verify original owner token preserved in DB
            s_db = container.schedule_repo.get_by_id(org.id, schedule.id)
            assert s_db.lease_token == "token-valid-owner"
        finally:
            db.close()
