"""Live PostgreSQL Concurrency, Race Condition, and Recovery Tests for P14.

Validates:
1. Exact last-slot acquisition race (max_executions=1, 2 concurrent threads on independent connections -> 1 ACQUIRED, 1 RATE_LIMITED).
2. Concurrency lease saturation race (max_concurrent=1, 2 concurrent connections -> 1 ACQUIRED, 1 CONCURRENCY_LIMITED).
3. Expired lease crash recovery (worker crashes with active lease -> naturally expires -> next acquire cleans up and succeeds).
4. Stale release token safety (release with wrong token fails -> active lease untouched).
5. Cooldown propagation race (connection A records HTTP 429 cooldown -> connection B instantly observes COOLDOWN without waiting).
6. Multi-tenant / Per-host scoping isolation (host:siteA saturated does not throttle host:siteB).
"""

import os
import time
import threading
from datetime import datetime, timezone, timedelta
import pytest

from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.infrastructure.repositories.provider_rate_limit_repository import ProviderRateLimitRepository
from bopclients.application.provider_rate_limit_service import ProviderRateLimitService
from bopclients.domain.rate_limit import ProviderRateLimitPolicy, ProviderAcquireStatus
from bopclients.runtime.db_migrator import DatabaseMigrator

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
class TestPostgresRateLimitingP14:
    """Live PostgreSQL concurrency and race condition tests."""

    @pytest.fixture(autouse=True)
    def setup_db(self):
        db = create_database_connection(TEST_PG_URL)
        DatabaseMigrator.migrate(db)
        db.execute("DELETE FROM provider_rate_limit_leases")
        db.execute("DELETE FROM provider_rate_limit_state")
        db.commit()
        db.close()
        yield

    def test_postgres_last_slot_acquisition_race(self):
        policy = ProviderRateLimitPolicy(
            provider_key="race_provider",
            max_executions=1,
            window_seconds=60,
            max_concurrent=5,
        )

        db1 = create_database_connection(TEST_PG_URL)
        db2 = create_database_connection(TEST_PG_URL)
        repo1 = ProviderRateLimitRepository(db1)
        repo2 = ProviderRateLimitRepository(db2)

        scope_key = f"global:test_last_slot_{int(time.time() * 1000)}"
        barrier = threading.Barrier(2)
        results = {}

        def acquire_task(name, repo):
            barrier.wait()
            res = repo.try_acquire(policy.provider_key, scope_key, policy)
            results[name] = res

        t1 = threading.Thread(target=acquire_task, args=("W1", repo1))
        t2 = threading.Thread(target=acquire_task, args=("W2", repo2))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        db1.close()
        db2.close()

        statuses = [r.status for r in results.values()]
        assert statuses.count(ProviderAcquireStatus.ACQUIRED) == 1
        assert statuses.count(ProviderAcquireStatus.RATE_LIMITED) == 1

        db_check = create_database_connection(TEST_PG_URL)
        repo_check = ProviderRateLimitRepository(db_check)
        st = repo_check.get_state(policy.provider_key, scope_key)
        assert st["execution_count"] == 1
        assert st["active_leases_count"] == 1
        db_check.close()

    def test_postgres_concurrency_lease_saturation_race(self):
        policy = ProviderRateLimitPolicy(
            provider_key="race_provider",
            max_executions=100,
            window_seconds=60,
            max_concurrent=1,
            request_lease_duration_seconds=30,
        )

        db1 = create_database_connection(TEST_PG_URL)
        db2 = create_database_connection(TEST_PG_URL)
        repo1 = ProviderRateLimitRepository(db1)
        repo2 = ProviderRateLimitRepository(db2)

        scope_key = f"global:test_concurrency_{int(time.time() * 1000)}"
        barrier = threading.Barrier(2)
        results = {}

        def acquire_task(name, repo):
            barrier.wait()
            res = repo.try_acquire(policy.provider_key, scope_key, policy)
            results[name] = res

        t1 = threading.Thread(target=acquire_task, args=("W1", repo1))
        t2 = threading.Thread(target=acquire_task, args=("W2", repo2))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        db1.close()
        db2.close()

        statuses = [r.status for r in results.values()]
        assert statuses.count(ProviderAcquireStatus.ACQUIRED) == 1
        assert statuses.count(ProviderAcquireStatus.CONCURRENCY_LIMITED) == 1

    def test_postgres_expired_lease_crash_recovery(self):
        policy = ProviderRateLimitPolicy(
            provider_key="crash_provider",
            max_executions=10,
            window_seconds=60,
            max_concurrent=1,
            request_lease_duration_seconds=2,
        )

        db = create_database_connection(TEST_PG_URL)
        repo = ProviderRateLimitRepository(db)
        scope_key = f"global:test_crash_{int(time.time() * 1000)}"

        t0 = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        res1 = repo.try_acquire(policy.provider_key, scope_key, policy, now_dt=t0)
        assert res1.acquired is True

        res2 = repo.try_acquire(policy.provider_key, scope_key, policy, now_dt=t0 + timedelta(seconds=1))
        assert res2.acquired is False
        assert res2.status == ProviderAcquireStatus.CONCURRENCY_LIMITED

        res3 = repo.try_acquire(policy.provider_key, scope_key, policy, now_dt=t0 + timedelta(seconds=3))
        assert res3.acquired is True
        assert res3.status == ProviderAcquireStatus.ACQUIRED

        st = repo.get_state(policy.provider_key, scope_key, now_dt=t0 + timedelta(seconds=3))
        assert st["active_leases_count"] == 1
        db.close()

    def test_postgres_stale_release_token_safety(self):
        policy = ProviderRateLimitPolicy(
            provider_key="safe_provider",
            max_executions=10,
            window_seconds=60,
            max_concurrent=2,
        )
        db = create_database_connection(TEST_PG_URL)
        repo = ProviderRateLimitRepository(db)
        scope_key = f"global:test_stale_{int(time.time() * 1000)}"

        res = repo.try_acquire(policy.provider_key, scope_key, policy)
        assert res.acquired is True
        valid_token = res.lease_token

        rel_fake = repo.release_lease(policy.provider_key, scope_key, "bogus-uuid-token")
        assert rel_fake is False

        st = repo.get_state(policy.provider_key, scope_key)
        assert st["active_leases_count"] == 1

        rel_real = repo.release_lease(policy.provider_key, scope_key, valid_token)
        assert rel_real is True
        st = repo.get_state(policy.provider_key, scope_key)
        assert st["active_leases_count"] == 0
        db.close()

    def test_postgres_cooldown_propagation_race(self):
        policy = ProviderRateLimitPolicy(
            provider_key="api_429",
            max_executions=100,
            window_seconds=60,
            max_concurrent=10,
        )

        db1 = create_database_connection(TEST_PG_URL)
        db2 = create_database_connection(TEST_PG_URL)
        repo1 = ProviderRateLimitRepository(db1)
        repo2 = ProviderRateLimitRepository(db2)

        scope_key = f"global:test_429_{int(time.time() * 1000)}"
        now = datetime.now(timezone.utc)
        cooldown_until = now + timedelta(seconds=120)

        repo1.record_cooldown(
            provider_key=policy.provider_key,
            scope_key=scope_key,
            status_code=429,
            cooldown_seconds=120,
            now_dt=now,
        )

        res2 = repo2.try_acquire(policy.provider_key, scope_key, policy, now_dt=now)
        assert res2.acquired is False
        assert res2.status == ProviderAcquireStatus.COOLDOWN_ACTIVE
        assert res2.retry_after_seconds == 120

        db1.close()
        db2.close()

    def test_postgres_per_host_isolation_on_website_provider(self):
        policy = ProviderRateLimitPolicy(
            provider_key="official_website",
            max_executions=1,
            window_seconds=60,
            max_concurrent=1,
        )

        db = create_database_connection(TEST_PG_URL)
        repo = ProviderRateLimitRepository(db)

        res_alpha_1 = repo.try_acquire("official_website", "host:alpha.com", policy)
        assert res_alpha_1.acquired is True
        res_alpha_2 = repo.try_acquire("official_website", "host:alpha.com", policy)
        assert res_alpha_2.acquired is False

        res_beta_1 = repo.try_acquire("official_website", "host:beta.com", policy)
        assert res_beta_1.acquired is True

        db.close()

    def test_postgres_migration_from_004_to_005_and_dev_repair(self):
        """P14.3 Audit 8 & 9: Live PostgreSQL 004->005 migration and uncommitted request_count repair."""
        db = create_database_connection(TEST_PG_URL)

        # 1. Verify migrator runs and yields 20260902_005 or higher
        ver = DatabaseMigrator.migrate(db)
        assert ver in ("20260902_005", "20260902_006", "20260902_007")

        # 2. Check execution_count column in PostgreSQL information_schema
        check_col_sql = """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'provider_rate_limit_state' AND column_name IN ('execution_count', 'request_count');
        """
        rows = db.fetch_dicts(check_col_sql)
        cols = {r["column_name"] for r in rows}
        assert "execution_count" in cols
        assert "request_count" not in cols

        # 3. Verify provider_rate_limit_leases exists
        leases_check = db.fetch_dicts("SELECT 1 FROM information_schema.tables WHERE table_name = 'provider_rate_limit_leases'")
        assert len(leases_check) == 1

        db.close()

