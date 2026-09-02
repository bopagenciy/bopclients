"""Manual Integration Validation for BopClients P13.2 Worker Recovery Time Semantics & Real Retry Execution."""

import os
import time
import uuid
import threading
from datetime import datetime, timezone, timedelta
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck
from bopclients.runtime.container import build_runtime_container
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.domain.organization import Organization
from bopclients.domain.prospect import Prospect
from bopclients.domain.research_run import ResearchRun
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.application.signal_provider import OfficialWebsiteSignalProvider


class ProviderCallCounterDecorator:
    """Decorator wrapping provider to count invocation executions for verification."""

    def __init__(self, target_provider):
        self.target_provider = target_provider
        self.call_count = 0

    @property
    def provider_name(self):
        return self.target_provider.provider_name

    @property
    def capabilities(self):
        return self.target_provider.capabilities

    def discover_signals(self, prospect, existing_signals=None, enrichment_snapshot=None, contacts=None, context=None):
        self.call_count += 1
        return self.target_provider.discover_signals(
            prospect=prospect,
            existing_signals=existing_signals,
            enrichment_snapshot=enrichment_snapshot,
            contacts=contacts,
            context=context,
        )


def run_manual_worker_recovery_validation():
    print("=================================================================")
    print("BOPCLIENTS P13.2 — WORKER RECOVERY TIME SEMANTICS & REAL RETRY TEST")
    print("=================================================================")

    pg_url = os.environ.get("BOPCLIENTS_TEST_POSTGRES_URL", "postgresql://bop:bop_test_password@localhost:55432/bopclients_test").strip()
    print(f"BACKEND:             PostgreSQL")
    print(f"Target DB URL:       {pg_url.split('@')[-1] if '@' in pg_url else pg_url}")

    try:
        db = create_database_connection(pg_url)
    except Exception as ex:
        print(f"RESULT: SKIPPED_POSTGRES_URL_NOT_CONFIGURED ({ex})")
        return

    try:
        # 1. Migration to 20260902_004
        print("\n--- 1. EXECUTING MIGRATION 20260902_004 ON LIVE POSTGRESQL ---")
        applied_ver = DatabaseMigrator.migrate(db)
        print(f"SCHEMA VERSION:       {applied_ver} (Expected: 20260902_004)")

        # 2. Cleanup test tables
        db.execute("DELETE FROM research_runs")
        db.execute("DELETE FROM signal_observations")
        db.execute("DELETE FROM monitoring_schedules")
        db.commit()

        # 3. Environment Settings & Container Setup
        os.environ["BOPCLIENTS_ENV"] = "production"
        os.environ["DATABASE_URL"] = pg_url
        os.environ["ENABLED_PUBLIC_SIGNAL_PROVIDERS"] = "official_website"
        settings = RuntimeSettings.from_env()

        container = build_runtime_container(settings, db=db)

        # Wrap official_website provider in registry to count executions
        base_provider = container.provider_registry.get("official_website")
        counter_provider = ProviderCallCounterDecorator(base_provider)
        container.provider_registry._providers["official_website"] = counter_provider

        # 4. ATTEMPT A & SIMULATED ABRUPT WORKER CRASH
        print("\n--- 2. ATTEMPT A & SIMULATED ABRUPT WORKER CRASH ---")
        ts = int(time.time() * 1000)
        org = container.org_repo.save(Organization(name=f"Rec Org {ts}", slug=f"rec-org-{ts}"))
        p = container.prospect_repo.save_prospect(org.id, Prospect(name="Rec Prospect", website_url="https://recprospect.com"))
        s = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p.id)

        # Set past due
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        s.next_check_at = (now_dt - timedelta(days=1)).isoformat()
        container.schedule_repo.save(org.id, s)

        # Attempt A: Claim schedule atomically with attempt_id_A
        attempt_id_A = f"attempt-A-{ts}"
        lease_token_A = f"lease-A-{ts}"
        claimed_A = container.schedule_repo.claim_due_work(
            org.id, s.id, lease_token=lease_token_A, lease_duration_seconds=300, now_iso=now_iso, execution_attempt_id=attempt_id_A
        )

        # Create Attempt A ResearchRun
        rr_A = ResearchRun(
            organization_id=org.id,
            prospect_id=p.id,
            monitoring_schedule_id=s.id,
            execution_attempt_id=attempt_id_A,
            run_type="signal_monitoring",
            status="running",
            started_at=(now_dt - timedelta(minutes=30)).isoformat(), # Stale timestamp
        )
        container.research_run_repo.save(org.id, rr_A)

        # Provider side-effect: Invoke provider scan (Call #1) & persist 1 SignalObservation for Event E
        counter_provider.discover_signals(p)
        obs_E1 = PublicSignalObservation(
            organization_id=org.id,
            prospect_id=p.id,
            provider="official_website",
            signal_type="buying_intent",
            category="rfp_announcement",
            intent_strength="high",
            source_type="official_website",
            source_url="https://recprospect.com/rfp-2026",
            fingerprint="fp-event-e-12345",
            evidence="RFP for Software Development",
            first_seen_at=now_iso,
            last_seen_at=now_iso,
            created_at=now_iso,
        )
        container.observation_repo.save(org.id, obs_E1)

        # Count observations BEFORE recovery
        obs_count_before = len(container.observation_repo.list_for_prospect(org.id, p.id))

        print(f"ATTEMPT A CLAIMED:                    {claimed_A}")
        print(f"PROVIDER INVOCATIONS ATTEMPT A:       {counter_provider.call_count}")
        print(f"OBSERVATION COUNT AFTER A:            {obs_count_before}")
        print(f"ATTEMPT A RESEARCHRUN:                {rr_A.status}")
        print(f"ATTEMPT A SCHEDULE FINALIZED:         False")
        print(f"CRASH SIMULATED:                      True")

        # Expire Attempt A lease on schedule so it becomes due for Attempt B
        container.schedule_repo.release_lease(org.id, s.id, lease_token_A)
        s_db = container.schedule_repo.get_by_id(org.id, s.id)
        s_db.next_check_at = (now_dt - timedelta(minutes=25)).isoformat()
        container.schedule_repo.save(org.id, s_db)

        # 5. RECOVERY PASS: Attempt A -> failed WORKER_EXECUTION_LOST
        print("\n--- 3. OPERATIONAL RECOVERY PASS ---")
        rec_res = container.recovery_service.reconcile_stale_runs(now_dt=now_dt, stale_after_seconds=900)
        rr_A_after = container.research_run_repo.get_by_id(org.id, rr_A.id)

        print(f"RECOVERY CANDIDATES FOUND:            {rec_res.candidates_found}")
        print(f"RECOVERY RECOVERED COUNT:             {rec_res.recovered_count}")
        print(f"RUN A STATUS AFTER RECOVERY:          {rr_A_after.status} ({rr_A_after.error_message})")

        # 6. ATTEMPT B: REAL MONITORING WORKER RETRY
        print("\n--- 4. ATTEMPT B — REAL MONITORING WORKER RETRY ---")
        worker_b_res = container.worker.run(now_dt=now_dt + timedelta(minutes=35))

        print(f"WORKER ITEMS ATTEMPTED:               {worker_b_res.items_attempted}")
        print(f"WORKER ITEMS CLAIMED:                 {worker_b_res.items_claimed}")
        print(f"WORKER SUCCESS COUNT:                 {worker_b_res.success_count}")
        print(f"PROVIDER INVOCATIONS TOTAL:           {counter_provider.call_count}")

        # Audit final state
        final_obs = container.observation_repo.list_for_prospect(org.id, p.id)
        final_runs = container.research_run_repo.list_by_organization(org.id)
        sched_final = container.schedule_repo.get_by_id(org.id, s.id)

        dedupe_valid = (len(final_obs) == 1)

        print("\n--- 5. FINAL ASSERTIONS ---")
        print(f"PROVIDER TOTAL INVOCATIONS:           {counter_provider.call_count}")
        print(f"OBSERVATION COUNT AFTER A:            {obs_count_before}")
        print(f"OBSERVATION COUNT AFTER B:            {len(final_obs)}")
        print(f"DEDUPLICATION VALID:                  {dedupe_valid}")
        print(f"FAILURE COUNT:                        {sched_final.failure_count}")
        print(f"NEXT CHECK UPDATED:                   {sched_final.next_check_at > now_iso}")
        print(f"CURRENT EXECUTION ATTEMPT:            {sched_final.current_execution_attempt_id}")
        print(f"LEASE ACTIVE:                         {sched_final.is_leased()}")

        print("\n--- 6. RESEARCHRUN HISTORY ---")
        for r in sorted(final_runs, key=lambda x: x.created_at):
            print(f"  - Run ID: {r.id[:8]}... | Status: {r.status:<10} | Attempt ID: {r.execution_attempt_id} | Err: {r.error_message or 'None'}")

        assert counter_provider.call_count == 2
        assert len(final_obs) == 1
        assert sched_final.failure_count == 0
        assert sched_final.current_execution_attempt_id is None
        assert not sched_final.is_leased()

        print("\n==================================================")
        print("P13.2 WORKER RECOVERY EXECUTION AUDIT SUCCESSFUL")
        print("==================================================")

    finally:
        db.close()


if __name__ == "__main__":
    run_manual_worker_recovery_validation()
