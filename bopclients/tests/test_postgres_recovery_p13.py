"""Dedicated live PostgreSQL integration test for P13.1 ResearchRun recovery attempt correlation."""

import os
import time
import pytest
import threading
from datetime import datetime, timezone, timedelta

from bopclients.domain.organization import Organization
from bopclients.domain.prospect import Prospect
from bopclients.domain.research_run import ResearchRun

from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.container import build_runtime_container
from bopclients.infrastructure.db.connection import create_database_connection, PostgresConnectionAdapter

TEST_PG_URL = os.environ.get(
    "BOPCLIENTS_TEST_POSTGRES_URL",
    "postgresql://bop:bop_test_password@localhost:55432/bopclients_test",
).strip()


class TestPostgresRecoveryP13:
    """Live PostgreSQL integration test suite for P13.1 ResearchRun recovery concurrency."""

    @pytest.mark.skipif(not TEST_PG_URL, reason="BOPCLIENTS_TEST_POSTGRES_URL not configured")
    def test_postgres_recovery_concurrency_race_with_active_new_attempt(self):
        try:
            db_admin = create_database_connection(TEST_PG_URL)
        except Exception:
            pytest.skip("PostgreSQL test container not available on localhost:55432")

        try:
            # 1. Migrate DB to 20260902_004
            DatabaseMigrator.migrate(db_admin)
            settings = RuntimeSettings(database_url=TEST_PG_URL, enabled_providers=["official_website"])
            container_admin = build_runtime_container(settings, db=db_admin)

            # 2. Seed tenant, orphan stale ResearchRun A, and active ResearchRun B
            ts = int(time.time() * 1000)
            org = container_admin.org_repo.save(Organization(name=f"PG Recovery Org {ts}", slug=f"pg-rec-org-{ts}"))
            p = container_admin.prospect_repo.save_prospect(org.id, Prospect(name="PG Rec Prospect"))
            s = container_admin.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p.id)

            now_dt = datetime.now(timezone.utc)
            now_iso = now_dt.isoformat()

            # Attempt A crashed 30 mins ago
            attempt_A = f"pg-attempt-A-{ts}"
            stale_started = (now_dt - timedelta(minutes=30)).isoformat()
            rr_A = ResearchRun(
                organization_id=org.id,
                prospect_id=p.id,
                monitoring_schedule_id=s.id,
                execution_attempt_id=attempt_A,
                run_type="signal_monitoring",
                status="running",
                started_at=stale_started,
            )
            container_admin.research_run_repo.save(org.id, rr_A)

            # Attempt B claims schedule NOW
            attempt_B = f"pg-attempt-B-{ts}"
            s.next_check_at = (now_dt - timedelta(minutes=5)).isoformat()
            container_admin.schedule_repo.save(org.id, s)
            container_admin.schedule_repo.claim_due_work(
                org.id, s.id, lease_token=f"token-B-{ts}", lease_duration_seconds=600, now_iso=now_iso, execution_attempt_id=attempt_B
            )

            rr_B = ResearchRun(
                organization_id=org.id,
                prospect_id=p.id,
                monitoring_schedule_id=s.id,
                execution_attempt_id=attempt_B,
                run_type="signal_monitoring",
                status="running",
                started_at=now_iso,
            )
            container_admin.research_run_repo.save(org.id, rr_B)

            # 3. Two independent recovery service connections race over stale Attempt A while Attempt B is active
            db_r1 = create_database_connection(TEST_PG_URL)
            db_r2 = create_database_connection(TEST_PG_URL)
            c1 = build_runtime_container(settings, db=db_r1)
            c2 = build_runtime_container(settings, db=db_r2)

            barrier = threading.Barrier(2)
            results = {}

            def recovery_worker_race(worker_name, recovery_service):
                barrier.wait()
                res = recovery_service.reconcile_stale_runs(now_dt=now_dt, stale_after_seconds=900)
                results[worker_name] = res

            t1 = threading.Thread(target=recovery_worker_race, args=("RecWorker-1", c1.recovery_service))
            t2 = threading.Thread(target=recovery_worker_race, args=("RecWorker-2", c2.recovery_service))

            t1.start()
            t2.start()
            t1.join()
            t2.join()

            # 4. Assert exactly one recovery process succeeded in marking Attempt A failed, while Attempt B remains running
            rec_count_1 = results["RecWorker-1"].recovered_count if "RecWorker-1" in results else 0
            rec_count_2 = results["RecWorker-2"].recovered_count if "RecWorker-2" in results else 0
            total_recovered = rec_count_1 + rec_count_2
            assert total_recovered == 1

            # 5. Verify DB final statuses
            fetched_A = container_admin.research_run_repo.get_by_id(org.id, rr_A.id)
            assert fetched_A.status == "failed"
            assert "WORKER_EXECUTION_LOST" in fetched_A.error_message

            fetched_B = container_admin.research_run_repo.get_by_id(org.id, rr_B.id)
            assert fetched_B.status == "running"

            db_r1.close()
            db_r2.close()

        finally:
            db_admin.close()
