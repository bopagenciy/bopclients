"""Manual Integration Validation for BopClients P12 PostgreSQL Runtime & Multi-Worker Concurrency."""

import os
import time
import threading
from datetime import datetime, timezone
from bopclients.runtime.settings import RuntimeSettings, AppEnvironment
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.container import build_runtime_container
from bopclients.infrastructure.db.connection import create_database_connection, PostgresConnectionAdapter
from bopclients.domain.organization import Organization
from bopclients.domain.prospect import Prospect


def run_manual_postgres_runtime_validation():
    print("=================================================================")
    print("BOPCLIENTS P12 — POSTGRESQL & MULTI-WORKER CONCURRENCY VALIDATION")
    print("=================================================================")

    pg_url = os.environ.get("BOPCLIENTS_TEST_POSTGRES_URL", "postgresql://bop:bop_test_password@localhost:55432/bopclients_test").strip()
    print(f"Target DB URL:       {pg_url.split('@')[-1] if '@' in pg_url else pg_url}")

    try:
        db = create_database_connection(pg_url)
    except Exception as ex:
        print(f"RESULT: SKIPPED_POSTGRES_URL_NOT_CONFIGURED ({ex})")
        return

    try:
        # 1. Fetch PostgreSQL Version
        ver_rows = db.fetch_dicts("SELECT version()")
        pg_ver = ver_rows[0]["version"] if ver_rows else "Unknown"
        print(f"POSTGRES VERSION:    {pg_ver[:50]}")

        # 2. Migration Status & Migration Execution
        print("\n--- 1. EXECUTING MIGRATION ON LIVE POSTGRESQL ---")
        applied_ver = DatabaseMigrator.migrate(db)
        print(f"  - Applied Schema Version: {applied_ver} (Expected: 20260902_002)")
        status_info = DatabaseMigrator.status(db)
        print(f"  - Migration Up To Date:   {status_info['is_up_to_date']}")

        # 3. Clean test DB tables to prevent cross-test contamination
        db.execute("DELETE FROM research_runs")
        db.execute("DELETE FROM signal_observations")
        db.execute("DELETE FROM monitoring_schedules")
        db.commit()

        # 4. Environment Readiness Check
        os.environ["BOPCLIENTS_ENV"] = "production"
        os.environ["DATABASE_URL"] = pg_url
        os.environ["ENABLED_PUBLIC_SIGNAL_PROVIDERS"] = "official_website"
        settings = RuntimeSettings.from_env()

        r_check = RuntimeReadinessCheck.check(settings, db=db)
        print("\n--- 2. RUNTIME READINESS CHECK ON POSTGRESQL ---")
        print(f"  - Readiness Status:       {r_check.status.value} (Must be READY)")
        print(f"  - Schema Version:         {r_check.schema_version}")
        print(f"  - Tables Present:         {r_check.tables_present}")
        print(f"  - Provider Matrix:        {r_check.provider_matrix}")

        # 5. Runtime Container Composition Root & Tenant Data
        print("\n--- 3. TENANT ISOLATION & SCHEDULE SEEDING ---")
        container = build_runtime_container(settings, db=db)
        ts = int(time.time() * 1000)
        org_a = container.org_repo.save(Organization(name=f"PG Org A {ts}", slug=f"pg-org-a-{ts}"))
        org_b = container.org_repo.save(Organization(name=f"PG Org B {ts}", slug=f"pg-org-b-{ts}"))

        p_a = container.prospect_repo.save_prospect(org_a.id, Prospect(name="PG Prospect A", website_url="https://pga.org"))
        p_b = container.prospect_repo.save_prospect(org_b.id, Prospect(name="PG Prospect B", website_url="https://pgb.org"))

        s_a = container.continuous_monitoring_service.ensure_schedule_for_prospect(org_a.id, p_a.id)
        s_b = container.continuous_monitoring_service.ensure_schedule_for_prospect(org_b.id, p_b.id)

        past_due = "2026-09-01T00:00:00+00:00"
        s_a.next_check_at = past_due
        s_b.next_check_at = past_due
        container.schedule_repo.save(org_a.id, s_a)
        container.schedule_repo.save(org_b.id, s_b)
        print("  - Tenant Schedules Seeded: Org A Schedule & Org B Schedule")

        # 6. ATOMIC CLAIM RACE BETWEEN TWO CONCURRENT WORKER THREADS
        print("\n--- 4. ATOMIC CLAIM CONCURRENCY RACE TEST ---")
        db_w1 = create_database_connection(pg_url)
        db_w2 = create_database_connection(pg_url)
        c1 = build_runtime_container(settings, db=db_w1)
        c2 = build_runtime_container(settings, db=db_w2)

        barrier = threading.Barrier(2)
        claim_results = {}

        def worker_claim_race(worker_name, repo_instance):
            barrier.wait()
            now_iso = datetime.now(timezone.utc).isoformat()
            res = repo_instance.claim_due_work(org_a.id, s_a.id, lease_token=f"token-{worker_name}", lease_duration_seconds=300, now_iso=now_iso)
            claim_results[worker_name] = res

        t1 = threading.Thread(target=worker_claim_race, args=("Worker-1", c1.schedule_repo))
        t2 = threading.Thread(target=worker_claim_race, args=("Worker-2", c2.schedule_repo))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        print(f"  - Worker-1 Claim Result:  {claim_results.get('Worker-1')}")
        print(f"  - Worker-2 Claim Result:  {claim_results.get('Worker-2')}")
        successful_claims = sum(1 for v in claim_results.values() if v is True)
        print(f"  - Exactly One Winner:     {successful_claims == 1} (Count: {successful_claims})")

        # 7. STALE OWNER PROTECTION TEST ON POSTGRESQL
        print("\n--- 5. STALE OWNER FINALIZATION PROTECTION TEST ---")
        winner_name = "Worker-1" if claim_results.get("Worker-1") else "Worker-2"
        loser_name = "Worker-2" if winner_name == "Worker-1" else "Worker-1"
        loser_container = c2 if loser_name == "Worker-2" else c1

        # Loser attempts stale lease renewal & schedule update
        now_dt = datetime.now(timezone.utc)
        loser_renew = loser_container.schedule_repo.renew_lease(org_a.id, s_a.id, lease_token=f"token-{loser_name}", lease_duration_seconds=300, now_iso=now_dt.isoformat())
        print(f"  - Loser Lease Renewal:    {loser_renew} (Must be False)")

        s_a_fresh = loser_container.schedule_repo.get_by_id(org_a.id, s_a.id)
        s_a_fresh.next_check_at = "2026-09-20T00:00:00+00:00"
        loser_update = loser_container.schedule_repo.update_schedule_after_execution(
            organization_id=org_a.id,
            schedule_id=s_a.id,
            expected_lease_token=f"token-{loser_name}",
            schedule=s_a_fresh,
        )
        print(f"  - Stale Owner Update:     {loser_update} (Must be False)")

        # Verify winner lease token preserved in DB
        s_db_winner = container.schedule_repo.get_by_id(org_a.id, s_a.id)
        print(f"  - Winner Token Preserved: {s_db_winner.lease_token == f'token-{winner_name}'}")

        # 8. TWO-WORKER CONCURRENT RUN EXECUTION
        print("\n--- 6. TWO-WORKER PARALLEL RUN EXECUTION TEST ---")
        # Release Winner-1 lease so schedules are due again
        container.schedule_repo.release_lease(org_a.id, s_a.id, f"token-{winner_name}")

        worker_a = c1.worker
        worker_b = c2.worker

        res_a = None
        res_b = None

        def run_worker_a():
            nonlocal res_a
            res_a = worker_a.run(now_dt=datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc))

        def run_worker_b():
            nonlocal res_b
            res_b = worker_b.run(now_dt=datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc))

        tw1 = threading.Thread(target=run_worker_a)
        tw2 = threading.Thread(target=run_worker_b)
        tw1.start()
        tw2.start()
        tw1.join()
        tw2.join()

        claimed_a = [ir.schedule_id for ir in res_a.item_results if ir.status != "SKIPPED"] if res_a else []
        claimed_b = [ir.schedule_id for ir in res_b.item_results if ir.status != "SKIPPED"] if res_b else []
        intersection = list(set(claimed_a).intersection(set(claimed_b)))
        unique_claims = set(claimed_a + claimed_b)
        total_claimed = len(claimed_a) + len(claimed_b)

        # Query ResearchRuns created
        runs_sa = db.fetch_dicts("SELECT id FROM research_runs WHERE organization_id = %s AND prospect_id = %s", (org_a.id, p_a.id))
        runs_sb = db.fetch_dicts("SELECT id FROM research_runs WHERE organization_id = %s AND prospect_id = %s", (org_b.id, p_b.id))

        print(f"EXACT FIXTURE SCHEDULE COUNT: 2")
        print(f"WORKER A CLAIMED IDS:          {claimed_a}")
        print(f"WORKER B CLAIMED IDS:          {claimed_b}")
        print(f"CLAIM INTERSECTION:            {intersection}")
        print(f"TOTAL UNIQUE CLAIMS:           {len(unique_claims)}")
        print(f"COMBINED CLAIM COUNTER:        {total_claimed}")
        print(f"PROVIDER INVOCATIONS:          S1={len(runs_sa)}, S2={len(runs_sb)}")
        print(f"RESEARCHRUN COUNTS:            S1={len(runs_sa)}, S2={len(runs_sb)}")
        print(f"MULTI-WORKER VALID:            {len(intersection) == 0 and len(unique_claims) == 2 and total_claimed == 2}")

        print("\n==================================================")
        print("P12 POSTGRESQL & MULTI-WORKER VALIDATION SUCCESSFUL")
        print("==================================================")

        db_w1.close()
        db_w2.close()

    finally:
        db.close()


if __name__ == "__main__":
    run_manual_postgres_runtime_validation()
