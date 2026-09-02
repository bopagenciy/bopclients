"""Unit test suite for BopClients P11 Production Runtime Readiness & Deployment Infrastructure."""

import os
import pytest
from datetime import datetime, timezone
from bopclients.runtime.settings import RuntimeSettings, AppEnvironment
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.container import build_runtime_container, build_monitoring_worker
from bopclients.domain.organization import Organization
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.db.migrations import run_p1_migrations
from forge.db import ForgeDB
from forge.db_schema import _SQLiteBackend


@pytest.fixture
def memory_db():
    db = ForgeDB(_SQLiteBackend(db_path=":memory:"))
    run_p1_migrations(db)
    return db


class TestRuntimeSettingsP11:
    def test_settings_default_environment_and_defaults(self):
        settings = RuntimeSettings(environment=AppEnvironment.DEVELOPMENT)
        assert settings.environment == AppEnvironment.DEVELOPMENT
        assert settings.worker_batch_size == 25
        assert settings.worker_max_items == 100

    def test_settings_safe_summary_secret_masking(self):
        settings = RuntimeSettings(
            environment=AppEnvironment.PRODUCTION,
            database_url="postgresql://user:secretpass123@localhost:5432/bopdb",
            sam_gov_api_key="secret_sam_key_abc",
            gemini_api_key="secret_gemini_key_xyz",
        )
        summary = settings.safe_summary()
        assert summary["environment"] == "production"
        assert summary["database_url"] == "postgresql://user:***@localhost:5432/bopdb"
        assert summary["sam_gov_configured"] is True
        assert summary["gemini_configured"] is True
        assert "secretpass123" not in str(summary)
        assert "secret_sam_key_abc" not in str(summary)

    def test_settings_validation_bounds(self):
        s1 = RuntimeSettings(worker_batch_size=0)
        with pytest.raises(ValueError, match="Worker batch size"):
            s1.validate()

        s2 = RuntimeSettings(lease_duration_seconds=100, lease_renew_before_seconds=120)
        with pytest.raises(ValueError, match="lease_renew_before_seconds must be strictly less"):
            s2.validate()

    def test_settings_unsupported_scheme_fail_closed(self):
        from bopclients.infrastructure.db.connection import create_database_connection
        with pytest.raises(ValueError, match="Unsupported database URL scheme"):
            create_database_connection("mysql://user:pass@localhost:3306/bopdb")

    def test_settings_in_memory_sqlite_in_production_fail_closed(self):
        settings = RuntimeSettings(environment=AppEnvironment.PRODUCTION, database_url=":memory:")
        with pytest.raises(ValueError, match="In-memory SQLite database is not persistent"):
            settings.validate()


class TestDatabaseMigratorP11:
    def test_migrator_status_unmigrated_and_migrate(self, memory_db):
        status1 = DatabaseMigrator.status(memory_db)
        assert status1["current_version"] == "unmigrated"
        assert status1["is_up_to_date"] is False

        ver = DatabaseMigrator.migrate(memory_db)
        assert ver == DatabaseMigrator.EXPECTED_VERSION

        status2 = DatabaseMigrator.status(memory_db)
        assert status2["current_version"] == DatabaseMigrator.EXPECTED_VERSION
        assert status2["is_up_to_date"] is True

    def test_migrator_idempotency(self, memory_db):
        v1 = DatabaseMigrator.migrate(memory_db)
        v2 = DatabaseMigrator.migrate(memory_db)
        assert v1 == v2 == DatabaseMigrator.EXPECTED_VERSION

    def test_migration_adoption_of_existing_p10_db_preserves_sentinel_data(self, memory_db):
        # Seed sentinel organization data in P10-era DB without schema version table
        org_repo = OrganizationRepository(memory_db)
        org = org_repo.save(Organization(name="Pre-migrated Org", slug="pre-migrated"))

        # Run migration on existing populated DB
        applied_ver = DatabaseMigrator.migrate(memory_db)
        assert applied_ver == DatabaseMigrator.EXPECTED_VERSION

        # Verify sentinel data preserved intact
        fetched_org = org_repo.get_by_id(org.id)
        assert fetched_org is not None
        assert fetched_org.name == "Pre-migrated Org"

    def test_migration_newer_schema_version_fail_closed(self, memory_db):
        DatabaseMigrator.ensure_version_table(memory_db)
        memory_db.execute("INSERT INTO bopclients_schema_version (version, applied_at) VALUES ('20260903_999', '2026-09-03T00:00:00')")
        memory_db.commit()

        with pytest.raises(ValueError, match="newer than expected version"):
            DatabaseMigrator.migrate(memory_db)


class TestRuntimeReadinessCheckP11:
    def test_readiness_not_ready_unmigrated_db(self, memory_db):
        settings = RuntimeSettings(enabled_providers=["official_website"])
        res = RuntimeReadinessCheck.check(settings, db=memory_db)
        assert res.status == ReadinessStatus.NOT_READY
        assert any("schema version mismatch" in err for err in res.errors)

    def test_readiness_ready_migrated_db(self, memory_db):
        DatabaseMigrator.migrate(memory_db)
        settings = RuntimeSettings(enabled_providers=["official_website"])
        res = RuntimeReadinessCheck.check(settings, db=memory_db)
        assert res.status == ReadinessStatus.READY
        assert res.database_connected is True
        assert res.tables_present is True
        assert res.provider_matrix["official_website"] == "READY"

    def test_readiness_degraded_when_optional_provider_unconfigured(self, memory_db):
        DatabaseMigrator.migrate(memory_db)
        settings = RuntimeSettings(enabled_providers=["official_website", "government_procurement"])
        res = RuntimeReadinessCheck.check(settings, db=memory_db)
        assert res.status == ReadinessStatus.DEGRADED
        assert res.provider_matrix["government_procurement"] == "SKIPPED_NO_KEY"
        assert any("SAM_GOV_API_KEY is unconfigured" in w for w in res.warnings)

    def test_readiness_degraded_when_public_news_enabled(self, memory_db):
        DatabaseMigrator.migrate(memory_db)
        settings = RuntimeSettings(enabled_providers=["official_website", "public_news"])
        res = RuntimeReadinessCheck.check(settings, db=memory_db)
        assert res.status == ReadinessStatus.DEGRADED
        assert res.provider_matrix["public_news"] == "SKIPPED_NO_BACKEND"


class TestRuntimeContainerP11:
    def test_container_wiring_and_provider_filtering(self, memory_db):
        DatabaseMigrator.migrate(memory_db)
        settings = RuntimeSettings(enabled_providers=["official_website"])
        container = build_runtime_container(settings, db=memory_db)

        providers = container.provider_registry.list_all()
        assert len(providers) == 1
        assert providers[0].provider_name == "official_website"
        assert container.worker is not None
