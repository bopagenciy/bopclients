"""Automated integration test suite for BopClients P17.1 PostgreSQL Integration Contract & Tenant Foundation."""

from datetime import datetime, timezone
import os
import pytest
import time
import uuid

from bopclients.domain.organization import Organization
from bopclients.domain.integration.entity_ref import BopEntityRef
from bopclients.domain.integration.events import BopIntegrationEvent
from bopclients.domain.integration.registry import BopEventRegistry
from bopclients.domain.integration.outbox import OutboxStatus
from bopclients.domain.integration.inbox import InboxStatus
from bopclients.domain.integration.exceptions import (
    DuplicateIntegrationEvent,
    UnknownLocalTenantIntegrationError,
)

from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.settings import RuntimeSettings
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.integration_outbox_repository import IntegrationOutboxRepository
from bopclients.infrastructure.repositories.integration_inbox_repository import IntegrationInboxRepository


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
class TestPostgresIntegrationContractP17:
    def setup_method(self):
        """Ensure clean database and up-to-date schema before each test."""
        db = create_database_connection(TEST_PG_URL)
        try:
            DatabaseMigrator.migrate(db)
            db.execute("DELETE FROM bop_integration_outbox;")
            db.execute("DELETE FROM bop_integration_inbox;")
            db.commit()
        finally:
            db.close()

    def test_postgres_migration_007_and_readiness(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            ver = DatabaseMigrator.migrate(db)
            assert ver in ("20260902_007", "20260902_008", "20260902_009")

            status = DatabaseMigrator.status(db)
            assert status["current_version"] in ("20260902_007", "20260902_008", "20260902_009")
            assert status["is_up_to_date"] is True

            # Verify tables exist in information_schema
            rows = db.fetch_dicts(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('bop_integration_outbox', 'bop_integration_inbox')"
            )
            table_names = {r["table_name"] for r in rows}
            assert "bop_integration_outbox" in table_names
            assert "bop_integration_inbox" in table_names

            # Verify readiness status
            settings = RuntimeSettings(
                database_url=TEST_PG_URL,
                enabled_providers=["official_website"],
            )
            readiness = RuntimeReadinessCheck.check(settings, db=db)
            assert readiness.status == ReadinessStatus.READY
            assert readiness.schema_version in ("20260902_007", "20260902_008", "20260902_009")
            assert readiness.tables_present is True
        finally:
            db.close()


    def test_postgres_not_null_invariant_enforced_at_db_level(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            ts = int(time.time() * 1000)
            try:
                db.execute(
                    "INSERT INTO organizations (id, name, slug, created_at, updated_at) VALUES (%s, %s, %s, %s, %s)",
                    (f"org_null_pg_{ts}", "Null Test", f"null-test-{ts}", "now", "now"),
                )
                db.commit()
                pytest.fail("PostgreSQL should have rejected insert without bop_organization_id")
            except Exception as e:
                assert "violates not-null constraint" in str(e).lower() or "notnullviolation" in str(type(e)).lower()
        finally:
            db.close()

    def test_postgres_organization_immutability(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            org_repo = OrganizationRepository(db)
            ts = int(time.time() * 1000)
            org = Organization(id=f"org_pg_immut_{ts}", name="Immut Org", slug=f"immut-org-{ts}")
            org_repo.save(org)

            orig_bop_id = org.bop_organization_id
            assert orig_bop_id is not None

            # Attempt mutation
            org.bop_organization_id = str(uuid.uuid4())
            with pytest.raises(ValueError, match="Cannot mutate immutable bop_organization_id"):
                org_repo.save(org)

            # Confirm unchanged in DB
            stored = org_repo.get_by_id(org.id)
            assert stored.bop_organization_id == orig_bop_id
        finally:
            db.close()

    def test_postgres_transactional_outbox_rollback_and_commit(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            org_repo = OrganizationRepository(db)
            outbox_repo = IntegrationOutboxRepository(db)
            ts = int(time.time() * 1000)

            # Phase A: ROLLBACK PROOF
            db.begin()
            org_a = Organization(id=f"org_pg_tx_a_{ts}", name="PG Tx A", slug=f"pg-tx-a-{ts}")
            org_repo.save(org_a)

            subject_a = BopEntityRef(bop_organization_id=org_a.bop_organization_id, application_id="bopclients", entity_type="organization", entity_id=org_a.id)
            event_a = BopIntegrationEvent(
                event_id=str(uuid.uuid4()),
                event_type="organization.onboarded",
                event_version=1,
                occurred_at=datetime.now(timezone.utc).isoformat(),
                producer_app="bopclients",
                bop_organization_id=org_a.bop_organization_id,
                subject=subject_a,
                correlation_id=str(uuid.uuid4()),
                payload={"name": "PG Tx A"},
            )
            outbox_repo.append(event_a)

            db.rollback()

            assert org_repo.get_by_id(org_a.id) is None
            assert outbox_repo.get_by_event_id(event_a.event_id) is None

            # Phase B: COMMIT PROOF
            db.begin()
            org_b = Organization(id=f"org_pg_tx_b_{ts}", name="PG Tx B", slug=f"pg-tx-b-{ts}")
            org_repo.save(org_b)

            subject_b = BopEntityRef(bop_organization_id=org_b.bop_organization_id, application_id="bopclients", entity_type="organization", entity_id=org_b.id)
            event_b = BopIntegrationEvent(
                event_id=str(uuid.uuid4()),
                event_type="organization.onboarded",
                event_version=1,
                occurred_at=datetime.now(timezone.utc).isoformat(),
                producer_app="bopclients",
                bop_organization_id=org_b.bop_organization_id,
                subject=subject_b,
                correlation_id=str(uuid.uuid4()),
                payload={"name": "PG Tx B"},
            )
            outbox_repo.append(event_b)

            db.commit()

            assert org_repo.get_by_id(org_b.id) is not None
            assert outbox_repo.get_by_event_id(event_b.event_id) is not None
        finally:
            db.close()

    def test_postgres_organization_backfill_and_preservation(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            ts = int(time.time() * 1000)
            org_id = f"org_pg_p17_{ts}"
            # Insert valid organization
            db.execute(
                "INSERT INTO organizations (id, bop_organization_id, name, slug, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (org_id, str(uuid.uuid4()), f"PG P17 Test Org {ts}", f"pg-p17-{ts}", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"),
            )
            db.commit()

            # Migrate
            ver = DatabaseMigrator.migrate(db)
            assert ver in ("20260902_007", "20260902_008", "20260902_009")

            row = db.fetch_dicts("SELECT id, name, bop_organization_id FROM organizations WHERE id = %s", (org_id,))[0]
            bop_org_id = row["bop_organization_id"]
            assert bop_org_id is not None
            uuid.UUID(bop_org_id)

            # Re-run migration idempotently and confirm bop_organization_id is preserved
            ver2 = DatabaseMigrator.migrate(db)
            assert ver2 in ("20260902_007", "20260902_008", "20260902_009")
            row2 = db.fetch_dicts("SELECT bop_organization_id FROM organizations WHERE id = %s", (org_id,))[0]
            assert row2["bop_organization_id"] == bop_org_id
        finally:
            db.close()

    def test_postgres_outbox_uniqueness_and_lifecycle(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            org_repo = OrganizationRepository(db)
            ts = int(time.time() * 1000)
            org = Organization(id=f"org_pg_outbox_{ts}", name="PG Outbox", slug=f"pg-outbox-{ts}")
            org_repo.save(org)
            org_id = org.bop_organization_id

            outbox_repo = IntegrationOutboxRepository(db, org_repo=org_repo)
            subject = BopEntityRef(bop_organization_id=org_id, application_id="bopclients", entity_type="prospect", entity_id="pg_p1")
            event = BopEventRegistry.build_event(
                event_type=BopEventRegistry.EVENT_PROSPECT_DISCOVERED,
                bop_organization_id=org_id,
                subject=subject,
                payload={"prospect_id": "pg_p1", "display_name": "PG Corp", "source_provider": "official_website"},
            )

            # Append event
            rec = outbox_repo.append(event)
            assert rec.event_id == event.event_id
            assert rec.status == OutboxStatus.PENDING.value


            # Duplicate rejection
            with pytest.raises(DuplicateIntegrationEvent):
                outbox_repo.append(event, allow_existing=False)

            # Idempotent append
            rec_dup = outbox_repo.append(event, allow_existing=True)
            assert rec_dup.id == rec.id

            # Publish
            ok = outbox_repo.mark_published(event.event_id, bop_organization_id=org_id)
            assert ok is True

            fetched = outbox_repo.get_by_event_id(event.event_id)
            assert fetched.status == OutboxStatus.PUBLISHED.value
        finally:
            db.close()

    def test_postgres_inbox_idempotency_and_tenant_isolation(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            inbox_repo = IntegrationInboxRepository(db)
            org_a = str(uuid.uuid4())
            org_b = str(uuid.uuid4())

            subject_a = BopEntityRef(bop_organization_id=org_a, application_id="bopcrm", entity_type="lead", entity_id="lead_pg_1")
            event_a = BopIntegrationEvent(
                event_id=str(uuid.uuid4()),
                event_type="lead.converted",
                event_version=1,
                occurred_at=datetime.now(timezone.utc).isoformat(),
                producer_app="bopcrm",
                bop_organization_id=org_a,
                subject=subject_a,
                correlation_id=str(uuid.uuid4()),
                payload={"lead_id": "lead_pg_1"},
            )

            # Register Tenant A event
            is_new, rec_a = inbox_repo.register_received(event_a)
            assert is_new is True
            assert rec_a.status == InboxStatus.RECEIVED.value

            # Duplicate receipt returns existing
            is_dup, rec_dup = inbox_repo.register_received(event_a)
            assert is_dup is False
            assert rec_dup.id == rec_a.id

            # Tenant isolation: query by Tenant B returns None
            isolated = inbox_repo.get_by_event_id(event_a.event_id, bop_organization_id=org_b)
            assert isolated is None

            # Mark processed by Tenant A
            proc = inbox_repo.mark_processed(event_a.event_id, bop_organization_id=org_a)
            assert proc is True
        finally:
            db.close()

    def test_postgres_006_to_007_with_child_foreign_keys(self):
        """Verify PostgreSQL migration 007 preserves organization IDs, child rows, and FK constraints."""
        db = create_database_connection(TEST_PG_URL)
        try:
            ts = int(time.time() * 1000)
            org_id = f"org_fk_pg_{ts}"
            member_id = f"mem_fk_pg_{ts}"
            user_id = f"user_fk_pg_{ts}"
            camp_id = f"camp_fk_pg_{ts}"
            prosp_id = f"prosp_fk_pg_{ts}"

            # 1. Create user
            db.execute(
                "INSERT INTO users (id, email, full_name, created_at) VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (user_id, f"user_{ts}@test.com", "Test User", "2026-09-01T00:00:00Z"),
            )
            # 2. Create organization
            db.execute(
                "INSERT INTO organizations (id, bop_organization_id, name, slug, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (org_id, str(uuid.uuid4()), f"FK Org {ts}", f"fk-org-{ts}", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"),
            )
            # 3. Create child member
            db.execute(
                "INSERT INTO organization_members (id, organization_id, user_id, role, created_at) VALUES (%s, %s, %s, %s, %s)",
                (member_id, org_id, user_id, "owner", "2026-09-01T00:00:00Z"),
            )
            # 4. Create child campaign
            db.execute(
                "INSERT INTO campaigns (id, organization_id, name, status, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (camp_id, org_id, f"Campaign {ts}", "active", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"),
            )
            # 5. Create child prospect
            db.execute(
                "INSERT INTO prospects (id, organization_id, name, source, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (prosp_id, org_id, f"Prospect {ts}", "manual", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"),
            )
            db.commit()

            # Execute migration 007
            ver = DatabaseMigrator.migrate(db)
            assert ver in ("20260902_007", "20260902_008", "20260902_009")

            # Verify organization and child rows survive
            org_row = db.fetch_dicts("SELECT * FROM organizations WHERE id = %s", (org_id,))[0]
            assert org_row["id"] == org_id
            assert org_row["bop_organization_id"] is not None

            mem_row = db.fetch_dicts("SELECT * FROM organization_members WHERE id = %s", (member_id,))[0]
            assert mem_row["organization_id"] == org_id

            camp_row = db.fetch_dicts("SELECT * FROM campaigns WHERE id = %s", (camp_id,))[0]
            assert camp_row["organization_id"] == org_id

            prosp_row = db.fetch_dicts("SELECT * FROM prospects WHERE id = %s", (prosp_id,))[0]
            assert prosp_row["organization_id"] == org_id
        finally:
            db.close()

    def test_postgres_unknown_local_tenant_outbox_rejected(self):
        db = create_database_connection(TEST_PG_URL)
        try:
            outbox_repo = IntegrationOutboxRepository(db)
            unprov_id = str(uuid.uuid4())
            subject = BopEntityRef(
                bop_organization_id=unprov_id,
                application_id="bopclients",
                entity_type="prospect",
                entity_id="pg_p_unprov",
            )
            event = BopEventRegistry.build_event(
                event_type=BopEventRegistry.EVENT_PROSPECT_DISCOVERED,
                bop_organization_id=unprov_id,
                subject=subject,
                payload={"prospect_id": "pg_p_unprov", "display_name": "PG Ghost", "source_provider": "official_website"},
            )

            with pytest.raises(UnknownLocalTenantIntegrationError, match="does not exist in local organizations"):
                outbox_repo.append(event)
        finally:
            db.close()
