"""Manual Integration Test for BopClients P11 Production Runtime Readiness & Execution."""

import os
import tempfile
from datetime import datetime, timezone
from bopclients.runtime.settings import RuntimeSettings, AppEnvironment
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.container import build_runtime_container, build_monitoring_worker
from bopclients.domain.organization import Organization
from bopclients.domain.prospect import Prospect
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


def run_manual_production_runtime_validation():
    print("=================================================================")
    print("BOPCLIENTS P11 — PRODUCTION RUNTIME INTEGRATION MANUAL VALIDATION")
    print("=================================================================")
    print("VALIDATION MODE:     PRODUCTION_LIKE_TEMP_SQLITE")
    print("LIVE DEPLOYMENT:     NOT_PERFORMED")
    print("SAM LIVE VALIDATION: NOT_PERFORMED")
    print("NEWS LIVE VALIDATION:NOT_PERFORMED")
    print("=================================================================")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db_file:
        tmp_db_path = tmp_db_file.name

    try:
        # 1. Test Settings Safe Summary & Secret Masking
        os.environ["BOPCLIENTS_ENV"] = "production"
        os.environ["DATABASE_URL"] = f"sqlite:///{tmp_db_path}"
        os.environ["ENABLED_PUBLIC_SIGNAL_PROVIDERS"] = "official_website,government_procurement"
        os.environ["SAM_GOV_API_KEY"] = "secret_sam_key_12345"

        settings = RuntimeSettings.from_env()
        summary = settings.safe_summary()
        print("\n--- 1. RUNTIME SETTINGS SAFE SUMMARY ---")
        print(f"  - Environment:         {summary['environment']}")
        print(f"  - Database URL:        {summary['database_url']}")
        print(f"  - Enabled Providers:   {summary['enabled_providers']}")
        print(f"  - SAM Gov Configured:  {summary['sam_gov_configured']}")
        print(f"  - Secret Token Leak:   {'secret_sam_key_12345' in str(summary)} (Must be False)")

        # 2. Test Readiness BEFORE Migration -> Must be NOT_READY (missing schema version)
        raw_db = ForgeDB(_SQLiteBackend(db_path=tmp_db_path))
        r_before = RuntimeReadinessCheck.check(settings, db=raw_db)
        print("\n--- 2. READINESS CHECK BEFORE MIGRATION ---")
        print(f"  - Readiness Status:    {r_before.status.value} (Must be NOT_READY)")
        print(f"  - Schema Version:      {r_before.schema_version}")
        print(f"  - Expected Version:    {r_before.expected_schema_version}")
        print(f"  - Error Summary:       {r_before.errors}")

        # 3. Apply Schema Migration
        print("\n--- 3. EXECUTING DATABASE MIGRATION ---")
        applied_version = DatabaseMigrator.migrate(raw_db)
        print(f"  - Applied Version:     {applied_version}")
        status_info = DatabaseMigrator.status(raw_db)
        print(f"  - Migration Up To Date:{status_info['is_up_to_date']}")

        # 4. Test Readiness AFTER Migration -> Must be READY
        r_after = RuntimeReadinessCheck.check(settings, db=raw_db)
        print("\n--- 4. READINESS CHECK AFTER MIGRATION ---")
        print(f"  - Readiness Status:    {r_after.status.value} (Must be READY)")
        print(f"  - Schema Version:      {r_after.schema_version}")
        print(f"  - Provider Matrix:     {r_after.provider_matrix}")

        # 5. Build Runtime Container & Execute Worker Dry Run
        container = build_runtime_container(settings, db=raw_db)
        print("\n--- 5. RUNTIME CONTAINER COMPOSITION ROOT WIRING ---")
        print(f"  - Registered Providers:{[p.provider_name for p in container.provider_registry.list_all()]}")

        # Seed sample organization & schedule
        org = container.org_repo.save(Organization(name="Prod Org", slug="prod-org"))
        p = container.prospect_repo.save_prospect(org.id, Prospect(name="Prod Prospect", website_url="https://example.com"))
        s = container.continuous_monitoring_service.ensure_schedule_for_prospect(org.id, p.id)
        s.next_check_at = "2026-09-01T00:00:00+00:00"
        container.schedule_repo.save(org.id, s)

        worker = container.worker
        worker.config.dry_run = True
        dry_res = worker.run(now_dt=datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc))
        print("\n--- 6. WORKER DRY-RUN EXECUTION ---")
        print(f"  - Stopped Reason:      {dry_res.stopped_reason}")
        print(f"  - Items Discovered:    {dry_res.items_discovered}")
        print(f"  - Items Attempted:     {dry_res.items_attempted}")

        # 6. Execute Real Worker Run
        worker.config.dry_run = False
        real_res = worker.run(now_dt=datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc))
        print("\n--- 7. WORKER REAL RUN EXECUTION ---")
        print(f"  - Stopped Reason:      {real_res.stopped_reason}")
        print(f"  - Items Attempted:     {real_res.items_attempted}")
        print(f"  - Items Claimed:       {real_res.items_claimed}")
        print(f"  - Success Count:       {real_res.success_count}")

        print("\n==================================================")
        print("P11 PRODUCTION RUNTIME MANUAL VALIDATION SUCCESSFUL")
        print("==================================================")

    finally:
        if 'raw_db' in locals() and hasattr(raw_db, "close"):
            try:
                raw_db.close()
            except Exception:
                pass
        if os.path.exists(tmp_db_path):
            try:
                os.remove(tmp_db_path)
            except Exception:
                pass


if __name__ == "__main__":
    run_manual_production_runtime_validation()
