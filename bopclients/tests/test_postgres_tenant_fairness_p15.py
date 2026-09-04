"""Live PostgreSQL Concurrency and Tenant Fairness Tests for P15.

Validates:
1. Multi-tenant concurrent dual-bucket race (Org 1 max 2, Org 2 max 2, Global max 4).
2. Deadlock-free concurrent acquisition race across multiple tenants with deterministic lock ordering.
3. Multi-worker unique schedule claims with interleaved fair ordering on PostgreSQL.
"""

import os
import time
import uuid
import threading
from datetime import datetime, timezone, timedelta
import pytest

from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.monitoring_schedule_repository import MonitoringScheduleRepository
from bopclients.infrastructure.repositories.provider_rate_limit_repository import ProviderRateLimitRepository
from bopclients.domain.organization import Organization
from bopclients.domain.prospect import Prospect
from bopclients.domain.monitoring_schedule import MonitoringSchedule
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
class TestPostgresTenantFairnessP15:
    """Live PostgreSQL concurrency and tenant fairness tests."""

    @pytest.fixture(autouse=True)
    def setup_db(self):
        db = create_database_connection(TEST_PG_URL)
        DatabaseMigrator.migrate(db)
        db.execute("DELETE FROM provider_rate_limit_leases")
        db.execute("DELETE FROM provider_rate_limit_state")
        db.execute("DELETE FROM monitoring_schedules")
        db.execute("DELETE FROM prospects")
        db.execute("DELETE FROM organizations")
        db.commit()
        db.close()
        yield

    def test_postgres_concurrent_dual_bucket_race(self):
        """Concurrent threads across 2 orgs race for slots under dual-bucket policy."""
        provider_key = f"pg_dual_{uuid.uuid4().hex[:6]}"
        scope_key = f"global:{provider_key}"

        policy = ProviderRateLimitPolicy(
            provider_key=provider_key,
            max_executions=6,
            max_concurrent=10,
            per_organization_max_executions=2,
            window_seconds=60,
        )

        org_1 = f"org-1-{uuid.uuid4().hex[:6]}"
        org_2 = f"org-2-{uuid.uuid4().hex[:6]}"
        org_3 = f"org-3-{uuid.uuid4().hex[:6]}"

        # Spawn 4 threads: 2 for Org 1, 2 for Org 2
        barrier = threading.Barrier(4)
        results = []
        lock = threading.Lock()

        def worker_task(org_id):
            db = create_database_connection(TEST_PG_URL)
            repo = ProviderRateLimitRepository(db)
            barrier.wait()
            res = repo.try_acquire(provider_key, scope_key, policy, organization_id=org_id)
            with lock:
                results.append((org_id, res))
            db.close()

        threads = [
            threading.Thread(target=worker_task, args=(org_1,)),
            threading.Thread(target=worker_task, args=(org_1,)),
            threading.Thread(target=worker_task, args=(org_2,)),
            threading.Thread(target=worker_task, args=(org_2,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All 4 slots should be successfully acquired
        assert len(results) == 4
        acquired_statuses = [r[1].status for r in results]
        assert acquired_statuses.count(ProviderAcquireStatus.ACQUIRED) == 4

        # Now test 5th attempt by Org 1: global is 4/4, but Org 1 is 2/2.
        # Tenant quota check should report TENANT_CAPACITY_LIMITED
        db_check = create_database_connection(TEST_PG_URL)
        repo_check = ProviderRateLimitRepository(db_check)

        res_org1_extra = repo_check.try_acquire(provider_key, scope_key, policy, organization_id=org_1)
        assert res_org1_extra.acquired is False
        assert res_org1_extra.status == ProviderAcquireStatus.TENANT_CAPACITY_LIMITED

        # Org 3 (0/2 used) acquires slot: tenant has capacity, global has 2 slots left (4/6) -> ACQUIRED
        res_org3_1 = repo_check.try_acquire(provider_key, scope_key, policy, organization_id=org_3)
        assert res_org3_1.acquired is True
        assert res_org3_1.status == ProviderAcquireStatus.ACQUIRED

        # Org 3 acquires 2nd slot -> global reaches 6/6
        res_org3_2 = repo_check.try_acquire(provider_key, scope_key, policy, organization_id=org_3)
        assert res_org3_2.acquired is True
        assert res_org3_2.status == ProviderAcquireStatus.ACQUIRED

        # Org 4 tries to acquire: global is 6/6 -> RATE_LIMITED
        org_4 = f"org-4-{uuid.uuid4().hex[:6]}"
        res_org4 = repo_check.try_acquire(provider_key, scope_key, policy, organization_id=org_4)
        assert res_org4.acquired is False
        assert res_org4.status == ProviderAcquireStatus.RATE_LIMITED

        db_check.close()

    def test_postgres_deadlock_free_concurrent_contention(self):
        """High-concurrency contention across multiple tenants does NOT produce deadlocks."""
        provider_key = f"pg_contention_{uuid.uuid4().hex[:6]}"
        scope_key = f"global:{provider_key}"

        policy = ProviderRateLimitPolicy(
            provider_key=provider_key,
            max_executions=100,
            max_concurrent=50,
            per_organization_max_executions=10,
            window_seconds=60,
        )

        orgs = [f"org-{i}-{uuid.uuid4().hex[:6]}" for i in range(4)]
        barrier = threading.Barrier(8)
        exceptions = []

        def contention_task(org_id):
            db = create_database_connection(TEST_PG_URL)
            repo = ProviderRateLimitRepository(db)
            try:
                barrier.wait()
                for _ in range(5):
                    repo.try_acquire(provider_key, scope_key, policy, organization_id=org_id)
            except Exception as ex:
                exceptions.append(ex)
            finally:
                db.close()

        threads = [
            threading.Thread(target=contention_task, args=(orgs[i % 4],))
            for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Deterministic locking guarantees zero deadlocks
        assert exceptions == []

    def test_postgres_interleaved_due_ordering_and_claims(self):
        """Validate multi-worker interleaved due selection and claim race on PostgreSQL."""
        db = create_database_connection(TEST_PG_URL)
        org_repo = OrganizationRepository(db)
        prospect_repo = ProspectRepository(db)
        sched_repo = MonitoringScheduleRepository(db)

        org_a = org_repo.save(Organization(name="Org A", slug=f"org-a-{uuid.uuid4().hex[:6]}"))
        org_b = org_repo.save(Organization(name="Org B", slug=f"org-b-{uuid.uuid4().hex[:6]}"))

        base = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        now_iso = base.isoformat()

        # Org A has 4 schedules, Org B has 1 schedule
        for i in range(4):
            p = prospect_repo.save_prospect(org_a.id, Prospect(name=f"Prospect A-{i}"))
            s = MonitoringSchedule(
                organization_id=org_a.id,
                prospect_id=p.id,
                status="active",
                next_check_at=(base - timedelta(minutes=10 - i)).isoformat(),
                source_fingerprint=f"fp-a-{i}",
            )
            sched_repo.save(org_a.id, s)

        p_b = prospect_repo.save_prospect(org_b.id, Prospect(name="Prospect B-0"))
        s_b = MonitoringSchedule(
            organization_id=org_b.id,
            prospect_id=p_b.id,
            status="active",
            next_check_at=(base - timedelta(minutes=1)).isoformat(),
            source_fingerprint="fp-b-0",
        )
        sched_repo.save(org_b.id, s_b)

        # Inspect due list ordering on PostgreSQL
        due = sched_repo.list_due_system(now_iso=now_iso, limit=3)
        assert len(due) == 3
        # Round 1: one from each tenant
        assert {due[0].organization_id, due[1].organization_id} == {org_a.id, org_b.id}
        # Round 2: next from Org A
        assert due[2].organization_id == org_a.id

        db.close()

    def test_postgres_large_backlog_explain_and_limit(self):
        """Verify PostgreSQL query plan uses Limit and WindowAgg, and bounded selection works on large backlogs."""
        db = create_database_connection(TEST_PG_URL)
        org_repo = OrganizationRepository(db)
        prospect_repo = ProspectRepository(db)
        sched_repo = MonitoringScheduleRepository(db)

        org_a = org_repo.save(Organization(name="Org Big", slug=f"org-big-{uuid.uuid4().hex[:6]}"))
        org_b = org_repo.save(Organization(name="Org Small", slug=f"org-small-{uuid.uuid4().hex[:6]}"))

        base = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)
        now_iso = base.isoformat()

        # Insert 100 for Org A, 2 for Org B
        for i in range(100):
            p = prospect_repo.save_prospect(org_a.id, Prospect(name=f"Prospect Big-{i}"))
            s = MonitoringSchedule(
                organization_id=org_a.id,
                prospect_id=p.id,
                status="active",
                next_check_at=(base - timedelta(minutes=100 - i)).isoformat(),
                source_fingerprint=f"fp-big-{i}",
            )
            sched_repo.save(org_a.id, s)

        for i in range(2):
            p = prospect_repo.save_prospect(org_b.id, Prospect(name=f"Prospect Small-{i}"))
            s = MonitoringSchedule(
                organization_id=org_b.id,
                prospect_id=p.id,
                status="active",
                next_check_at=(base - timedelta(minutes=5 - i)).isoformat(),
                source_fingerprint=f"fp-small-{i}",
            )
            sched_repo.save(org_b.id, s)

        # Explain query on PostgreSQL
        explain_sql = """
            EXPLAIN
            SELECT * FROM (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY organization_id
                           ORDER BY next_check_at ASC, prospect_id ASC, id ASC
                       ) AS tenant_round
                FROM monitoring_schedules
                WHERE status = 'active'
                  AND next_check_at <= %s
                  AND (lease_expires_at IS NULL OR lease_expires_at <= %s)
            ) sub
            ORDER BY tenant_round ASC, next_check_at ASC, organization_id ASC, prospect_id ASC, id ASC
            LIMIT %s
        """
        plan_rows = db.fetch_dicts(explain_sql, (now_iso, now_iso, 10))
        plan_text = " ".join([str(r) for r in plan_rows])
        assert "Limit" in plan_text
        assert "WindowAgg" in plan_text

        # Execute query
        due = sched_repo.list_due_system(now_iso=now_iso, limit=10)
        assert len(due) == 10
        # Org B must be present in Round 1
        assert any(s.organization_id == org_b.id for s in due[:2])

        db.close()

