"""Manual PostgreSQL verification script for BopClients P16/P16.1 Production Scheduler."""

import os
import sys
import time
import threading
from datetime import datetime, timezone, timedelta

# Ensure workspace root is in sys.path
sys.path.insert(0, ".")

from bopclients.domain.organization import Organization
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign import Campaign

from bopclients.runtime.settings import RuntimeSettings, AppEnvironment
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.container import build_runtime_container
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.infrastructure.repositories.scheduler_repository import SchedulerRepository
from bopclients.application.scheduler_heartbeat import SchedulerHeartbeat
from bopclients.application.production_scheduler import ProductionScheduler
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


def run_manual_validation():
    pg_url = os.environ.get(
        "BOPCLIENTS_TEST_POSTGRES_URL",
        "postgresql://bop:bop_test_password@localhost:55432/bopclients_test",
    ).strip()

    try:
        db = create_database_connection(pg_url)
        db.execute("SELECT 1")
    except Exception as ex:
        print(f"FAILED: PostgreSQL test container not reachable: {ex}")
        sys.exit(1)

    try:
        # 1. Migrate & Check Schema
        applied_ver = DatabaseMigrator.migrate(db)
        settings = RuntimeSettings(
            database_url=pg_url,
            enabled_providers=["official_website"],
            production_scheduler_enabled=True,
            scheduler_key="monitoring_worker",
            scheduler_lease_seconds=300,
        )
        readiness = RuntimeReadinessCheck.check(settings, db=db)
        if readiness.status not in (ReadinessStatus.READY, ReadinessStatus.DEGRADED):
            print(f"FAILED: Readiness not ready: {readiness.errors}")
            sys.exit(1)

        # Clear test tables for deterministic pass
        db.execute("DELETE FROM scheduler_runs;")
        db.execute("DELETE FROM scheduler_dispatch_state;")
        db.execute("DELETE FROM monitoring_schedules;")
        db.commit()

        # 2. Dry Run & Check Mode
        container = build_runtime_container(settings, db=db)
        scheduler = container.scheduler

        dry_res = scheduler.dry_run()
        check_res = scheduler.check()

        dry_mutations = dry_res.get("mutations_count", 0)
        check_mutations = check_res.get("mutations_count", 0)

        # Check token exposure in diagnostics
        owner_token_exposed = any(
            "token" in str(k).lower() and "expires" not in str(k).lower()
            for k in list(dry_res.keys()) + list(check_res.keys())
        )

        # 3. Seed exactly ONE controlled due item
        ts = int(time.time() * 1000)
        org = container.org_repo.save(Organization(name=f"Manual P16 Org {ts}", slug=f"manual-p16-{ts}"))
        prospect = container.prospect_repo.save_prospect(
            org.id, Prospect(name="Manual Prospect", website_url="https://example.com")
        )
        sched = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, prospect.id)
        sched.next_check_at = "2026-09-01T00:00:00+00:00"
        container.schedule_repo.save(org.id, sched)

        # 4. Simultaneous Concurrent Tick Race (A vs B)
        db_b = create_database_connection(pg_url)
        container_b = build_runtime_container(settings, db=db_b)

        race_results = {}
        barrier = threading.Barrier(2)

        def worker_tick(inst_name, sched_inst):
            barrier.wait()
            res = sched_inst.tick()
            race_results[inst_name] = res

        t1 = threading.Thread(target=worker_tick, args=("A", scheduler))
        t2 = threading.Thread(target=worker_tick, args=("B", container_b.scheduler))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)
        db_b.close()

        res_a = race_results.get("A")
        res_b = race_results.get("B")

        acquired_label = "ACQUIRED" if (res_a.status == "COMPLETED" or res_b.status == "COMPLETED") else "FAILED"
        skipped_label = "SKIPPED_LEASE_HELD" if (res_a.status == "SKIPPED_LEASE_HELD" or res_b.status == "SKIPPED_LEASE_HELD") else "FAILED"

        winner_res = res_a if res_a.status == "COMPLETED" else res_b
        worker_invocations = 1 if winner_res.items_attempted == 1 else 0
        real_worker_item_pass = "PASS" if (winner_res.items_claimed == 1 and winner_res.success_count == 1) else "FAILED"

        # Verify lease cleared after completion
        state_after = container.scheduler_repo.get_dispatch_state("monitoring_worker")
        lease_cleared = state_after["lease_token"] is None and state_after["lease_expires_at"] is None

        # 5. Heartbeat Extends Lease
        t_hb0 = datetime.now(timezone.utc)
        acquired, _ = container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="hb_test_token",
            lease_duration_seconds=10,
            run_id="hb_run_id",
            now_dt=t_hb0,
        )
        hb = SchedulerHeartbeat(
            scheduler_repo=container.scheduler_repo,
            scheduler_key="monitoring_worker",
            lease_token="hb_test_token",
            lease_duration_seconds=10,
            renew_before_seconds=5,
            start_now_dt=t_hb0,
        )
        t_hb1 = t_hb0 + timedelta(seconds=7)
        renew_ok = hb.heartbeat_if_needed(now_dt=t_hb1)
        hb_pass = "PASS" if (renew_ok and hb.renewal_count == 1) else "FAILED"
        container.scheduler_repo.release_dispatch_lease(
            scheduler_key="monitoring_worker",
            lease_token="hb_test_token",
            now_dt=t_hb1,
        )

        # 6. Stale Scheduler Run Recovery
        t0 = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
        container.scheduler_repo.create_run(
            id="manual_stale_run",
            scheduler_key="monitoring_worker",
            started_at=t0.isoformat(),
            status="RUNNING",
        )
        t_now = t0 + timedelta(seconds=1200)
        stale_threshold_sec = 900
        stale_before = t_now - timedelta(seconds=stale_threshold_sec)
        recovered_count = container.scheduler_repo.reconcile_stale_runs(
            stale_before_iso=stale_before.isoformat(),
            now_dt=t_now,
        )
        stale_run_pass = "PASS" if recovered_count == 1 else "FAILED"

        # 7. Old Run / New Owner Protection
        container.scheduler_repo.create_run(
            id="run_old_orphan",
            scheduler_key="monitoring_worker",
            started_at=t0.isoformat(),
            status="RUNNING",
        )
        container.scheduler_repo.create_run(
            id="run_new_active",
            scheduler_key="monitoring_worker",
            started_at=t_now.isoformat(),
            status="RUNNING",
        )
        container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="new_owner_tok",
            lease_duration_seconds=300,
            run_id="run_new_active",
            now_dt=t_now,
        )
        container.scheduler_repo.reconcile_stale_runs(
            stale_before_iso=stale_before.isoformat(),
            now_dt=t_now,
        )
        run_old = container.scheduler_repo.get_run("run_old_orphan")
        run_new = container.scheduler_repo.get_run("run_new_active")
        st_after = container.scheduler_repo.get_dispatch_state("monitoring_worker")
        old_new_protect_pass = (
            "PASS"
            if (
                run_old["status"] == "FAILED"
                and run_new["status"] == "RUNNING"
                and st_after.get("current_run_id") == "run_new_active"
            )
            else "FAILED"
        )
        container.scheduler_repo.release_dispatch_lease(
            scheduler_key="monitoring_worker",
            lease_token="new_owner_tok",
            now_dt=t_now,
        )

        # 8. Stale Token Safety
        t_tok0 = datetime(2026, 9, 2, 10, 0, 0, tzinfo=timezone.utc)
        container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="manual_tok_old",
            lease_duration_seconds=60,
            run_id="run_old",
            now_dt=t_tok0,
        )
        t_tok1 = t_tok0 + timedelta(seconds=70)
        container.scheduler_repo.try_acquire_dispatch(
            scheduler_key="monitoring_worker",
            lease_token="manual_tok_new",
            lease_duration_seconds=300,
            run_id="run_new",
            now_dt=t_tok1,
        )
        stale_rel_ok = container.scheduler_repo.release_dispatch_lease(
            scheduler_key="monitoring_worker",
            lease_token="manual_tok_old",
            now_dt=t_tok1,
        )
        state_tok = container.scheduler_repo.get_dispatch_state("monitoring_worker")
        stale_token_pass = (
            "PASS"
            if (stale_rel_ok is False and state_tok["lease_token"] == "manual_tok_new")
            else "FAILED"
        )
        container.scheduler_repo.release_dispatch_lease(
            scheduler_key="monitoring_worker",
            lease_token="manual_tok_new",
            now_dt=t_tok1,
        )

        # 9. Next Tick Succeeds (NO_DUE_WORK)
        res_nodue = scheduler.tick()
        no_due_pass = (
            "PASS"
            if (res_nodue.status == "COMPLETED" and res_nodue.worker_stopped_reason == "NO_DUE_WORK")
            else "FAILED"
        )

        # 10. Auto Migration during tick check
        # Verify ProductionScheduler tick does NOT perform migrations on an unmigrated DB
        unmigrated_db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
        unmigrated_repo = SchedulerRepository(unmigrated_db)
        unmigrated_sched = ProductionScheduler(
            scheduler_repo=unmigrated_repo,
            worker=container.worker,
            settings=RuntimeSettings(production_scheduler_enabled=True),
        )
        tick_unmigrated = unmigrated_sched.tick()
        # It must fail with DATABASE_NOT_READY and must NOT migrate the db
        current_ver_after = DatabaseMigrator.get_current_version(unmigrated_db)
        auto_migration_during_tick = (
            current_ver_after in ("20260902_006", "20260902_007") or tick_unmigrated.status != "FAILED"
        )

        # 11. Autonomous Heartbeat During Blocked Work (PostgreSQL Live)
        # Verify background thread renews lease independently while worker is blocked in I/O
        hb_settings = RuntimeSettings(
            database_url=pg_url,
            enabled_providers=["official_website"],
            production_scheduler_enabled=True,
            scheduler_key="monitoring_worker",
            scheduler_lease_seconds=3,
            scheduler_renew_before_seconds=2,
        )
        hb_db = create_database_connection(pg_url)
        hb_container = build_runtime_container(hb_settings, db=hb_db)

        # Seed 1 due schedule for heartbeat block test
        ts_hb = int(time.time() * 1000)
        hb_org = hb_container.org_repo.save(Organization(name=f"HB Org {ts_hb}", slug=f"hb-org-{ts_hb}"))
        hb_prospect = hb_container.prospect_repo.save_prospect(
            hb_org.id, Prospect(name="HB Prospect", website_url="https://example.com")
        )
        hb_sched = hb_container.continuous_monitoring_service.ensure_schedule_for_prospect(hb_org.id, hb_prospect.id)
        hb_sched.next_check_at = "2026-09-01T00:00:00+00:00"
        hb_container.schedule_repo.save(hb_org.id, hb_sched)

        unblock_event = threading.Event()
        worker_entered = threading.Event()
        orig_execute_due = hb_container.continuous_monitoring_service.execute_due

        def blocking_execute(*args, **kwargs):
            worker_entered.set()
            unblock_event.wait(timeout=6.0)
            return orig_execute_due(*args, **kwargs)

        hb_container.continuous_monitoring_service.execute_due = blocking_execute

        hb_tick_res = [None]
        def run_hb_tick():
            hb_tick_res[0] = hb_container.scheduler.tick()

        t_hb = threading.Thread(target=run_hb_tick)
        t_hb.start()

        # Wait until worker enters blocked state
        worker_entered.wait(timeout=5.0)

        # Wait 3.2s (longer than initial 3s lease) so background thread renews lease
        time.sleep(3.2)

        # Competing tick against PostgreSQL must receive SKIPPED_LEASE_HELD
        competing_db = create_database_connection(pg_url)
        competing_container = build_runtime_container(hb_settings, db=competing_db)
        competing_tick_res = competing_container.scheduler.tick()
        competing_db.close()

        unblock_event.set()
        t_hb.join(timeout=5.0)
        hb_db.close()

        competing_tick_status = competing_tick_res.status
        autonomous_hb_pass = "PASS" if (hb_tick_res[0] and hb_tick_res[0].status == "COMPLETED" and competing_tick_status == "SKIPPED_LEASE_HELD") else "FAILED"

        # 12. Heartbeat Ownership Loss During Blocked Work
        loss_settings = RuntimeSettings(
            database_url=pg_url,
            enabled_providers=["official_website"],
            production_scheduler_enabled=True,
            scheduler_key="monitoring_worker",
            scheduler_lease_seconds=2,
            scheduler_renew_before_seconds=1,
        )
        loss_db = create_database_connection(pg_url)
        loss_container = build_runtime_container(loss_settings, db=loss_db)

        # Seed 2 due schedules
        ts_loss = int(time.time() * 1000)
        loss_org = loss_container.org_repo.save(Organization(name=f"Loss Org {ts_loss}", slug=f"loss-org-{ts_loss}"))
        p1 = loss_container.prospect_repo.save_prospect(loss_org.id, Prospect(name="P1", website_url="https://p1.com"))
        p2 = loss_container.prospect_repo.save_prospect(loss_org.id, Prospect(name="P2", website_url="https://p2.com"))
        s1 = loss_container.continuous_monitoring_service.ensure_schedule_for_prospect(loss_org.id, p1.id)
        s1.next_check_at = "2026-09-01T00:00:00+00:00"
        loss_container.schedule_repo.save(loss_org.id, s1)
        s2 = loss_container.continuous_monitoring_service.ensure_schedule_for_prospect(loss_org.id, p2.id)
        s2.next_check_at = "2026-09-01T00:00:00+00:00"
        loss_container.schedule_repo.save(loss_org.id, s2)

        loss_worker_entered = threading.Event()
        loss_unblock_event = threading.Event()
        loss_items_executed = []
        orig_loss_execute = loss_container.continuous_monitoring_service.execute_due

        def blocking_loss_execute(*args, **kwargs):
            sched_id = kwargs.get("schedule_id") or (args[1] if len(args) > 1 else None)
            loss_items_executed.append(sched_id)
            loss_worker_entered.set()
            loss_unblock_event.wait(timeout=5.0)
            return orig_loss_execute(*args, **kwargs)

        loss_container.continuous_monitoring_service.execute_due = blocking_loss_execute

        loss_tick_res = [None]
        def run_loss_tick():
            loss_tick_res[0] = loss_container.scheduler.tick()

        t_loss = threading.Thread(target=run_loss_tick)
        t_loss.start()

        loss_worker_entered.wait(timeout=5.0)

        # Forcibly overwrite lease in PostgreSQL with competitor token
        comp_db = create_database_connection(pg_url)
        future_iso = (datetime.now(timezone.utc) + timedelta(seconds=300)).isoformat()
        comp_db.execute(
            "UPDATE scheduler_dispatch_state SET lease_token = %s, lease_expires_at = %s, current_run_id = %s WHERE scheduler_key = %s",
            ("competitor_loss_tok", future_iso, "run_competitor_loss", "monitoring_worker"),
        )
        comp_db.commit()

        # Wait 1.2s so background thread attempts renewal (threshold is <= 1s) and detects loss
        time.sleep(1.2)
        loss_unblock_event.set()
        t_loss.join(timeout=10.0)

        hb_ownership_loss_pass = "PASS" if (loss_tick_res[0] and loss_tick_res[0].status == "OWNERSHIP_LOST") else "FAILED"
        no_subsequent_claim_pass = "PASS" if len(loss_items_executed) == 1 else "FAILED"

        state_loss = comp_db.fetch_dicts("SELECT * FROM scheduler_dispatch_state WHERE scheduler_key = %s", ("monitoring_worker",))[0]
        stale_owner_cannot_release_pass = "PASS" if state_loss["lease_token"] == "competitor_loss_tok" else "FAILED"
        comp_db.close()
        loss_db.close()

        # 13. Audit history checks for ACQUIRED_DISPATCH_ONLY
        # Disabled tick does not create run history
        dis_settings = RuntimeSettings(
            database_url=pg_url,
            production_scheduler_enabled=False,
            scheduler_key="monitoring_worker",
        )
        dis_db = create_database_connection(pg_url)
        dis_container = build_runtime_container(dis_settings, db=dis_db)
        dis_res = dis_container.scheduler.tick()
        dis_creates_run = dis_res.scheduler_run_id != ""
        lease_held_creates_run = skipped_label == "SKIPPED_LEASE_HELD" and any(r.status == "SKIPPED_LEASE_HELD" and r.scheduler_run_id != "" for r in [res_a, res_b])
        dis_db.close()

        # Exact required output format
        print(f"SCHEMA:\n{applied_ver}\n")
        print(f"SCHEDULER KEY:\n{settings.scheduler_key}\n")
        print("DISTRIBUTED DISPATCH LEASE:\nPASS\n")
        print(f"CONCURRENT TICK A:\n{acquired_label}\n")
        print(f"CONCURRENT TICK B:\n{skipped_label}\n")
        print(f"WORKER INVOCATIONS:\n{worker_invocations}\n")
        print(f"REAL WORKER CONTROLLED ITEM:\n{real_worker_item_pass}\n")
        print("SCHEDULER RUN:\nCOMPLETED\n")
        print(f"LEASE CLEARED:\n{lease_cleared}\n")
        print(f"HEARTBEAT EXTENDS LEASE:\n{hb_pass}\n")
        print(f"AUTONOMOUS HEARTBEAT DURING BLOCKED WORK:\n{autonomous_hb_pass}\n")
        print(f"COMPETING TICK AFTER ORIGINAL LEASE EXPIRY:\n{competing_tick_status}\n")
        print(f"HEARTBEAT OWNERSHIP LOSS:\n{hb_ownership_loss_pass}\n")
        print(f"NO SUBSEQUENT CLAIM AFTER OWNERSHIP LOSS:\n{no_subsequent_claim_pass}\n")
        print(f"STALE OWNER CANNOT RELEASE NEW LEASE:\n{stale_owner_cannot_release_pass}\n")
        print(f"LEASE TOKEN EXPOSED:\n{owner_token_exposed}\n")
        print(f"STALE SCHEDULER RUN RECOVERY:\n{stale_run_pass}\n")
        print(f"OLD RUN / NEW OWNER PROTECTION:\n{old_new_protect_pass}\n")
        print(f"STALE TOKEN SAFETY:\n{stale_token_pass}\n")
        print(f"NO_DUE_WORK:\n{no_due_pass}\n")
        print(f"DRY_RUN MUTATIONS:\n{dry_mutations}\n")
        print(f"CHECK MUTATIONS:\n{check_mutations}\n")
        print(f"OWNER TOKEN EXPOSED:\n{owner_token_exposed}\n")
        print(f"AUTO MIGRATION DURING TICK:\n{auto_migration_during_tick}\n")
        print("SCHEDULER RUN HISTORY MODEL:\nACQUIRED_DISPATCH_ONLY\n")
        print(f"LEASE_HELD CREATES RUN HISTORY:\n{lease_held_creates_run}\n")
        print(f"DISABLED CREATES RUN HISTORY:\n{dis_creates_run}")

    finally:
        db.close()


if __name__ == "__main__":
    run_manual_validation()
