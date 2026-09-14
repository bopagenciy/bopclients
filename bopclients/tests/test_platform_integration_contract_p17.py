"""Automated test suite for BopClients P17.1 Bop Platform Integration Contract & Cross-App Tenant Foundation."""

from datetime import datetime, timezone, timedelta
import json
import pytest
import uuid

from bopclients.domain.enums import MemberRole
from bopclients.domain.organization import Organization
from bopclients.domain.integration.app_id import (
    BopAppId,
    LOCAL_APPLICATION_ID,
    validate_application_id,
    is_known_application_id,
)
from bopclients.domain.integration.entity_ref import BopEntityRef
from bopclients.domain.integration.events import BopIntegrationEvent
from bopclients.domain.integration.exceptions import (
    InvalidEntityRef,
    InvalidIntegrationEvent,
    CrossTenantIntegrationEvent,
    UnsupportedEventVersion,
    DuplicateIntegrationEvent,
    UnknownLocalTenantIntegrationError,
)
from bopclients.domain.integration.registry import BopEventRegistry
from bopclients.domain.integration.outbox import OutboxStatus
from bopclients.domain.integration.inbox import InboxStatus

from bopclients.infrastructure.db.connection import create_database_connection, SQLiteConnectionAdapter
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.integration_outbox_repository import IntegrationOutboxRepository
from bopclients.infrastructure.repositories.integration_inbox_repository import IntegrationInboxRepository
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.settings import RuntimeSettings


@pytest.fixture
def sqlite_db():
    """Create disposable SQLite in-memory connection migrated to 20260902_007."""
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)
    yield db
    db.close()


# ==============================================================================
# 1. APPLICATION IDENTITY & EXTENSIBILITY TESTS
# ==============================================================================

class TestApplicationIdentity:
    def test_canonical_application_enum_values(self):
        assert BopAppId.BOPCLIENTS.value == "bopclients"
        assert BopAppId.BOPCRM.value == "bopcrm"
        assert BopAppId.BOPERP.value == "boperp"
        assert BopAppId.BOPSOCIAL.value == "bopsocial"
        assert BopAppId.BOPCHATBOT.value == "bopchatbot"
        assert BopAppId.BOPASSISTANT.value == "bopassistant"
        assert LOCAL_APPLICATION_ID == "bopclients"

    def test_validate_registered_application_id(self):
        assert validate_application_id("bopclients") == "bopclients"
        assert validate_application_id("BopCRM ") == "bopcrm"
        assert validate_application_id("BopERP") == "boperp"
        assert is_known_application_id("bopclients") is True

    def test_validate_extensible_future_bop_app_id(self):
        # Future valid Bop app ID passes wire syntax validation without breaking older code
        assert validate_application_id("bopinventory") == "bopinventory"
        assert is_known_application_id("bopinventory") is False
        assert validate_application_id("bop_support_desk") == "bop_support_desk"
        assert validate_application_id("bop-billing-v2") == "bop-billing-v2"

    def test_reject_invalid_application_id_syntax(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_application_id("")
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_application_id("   ")
        with pytest.raises(ValueError, match="Must start with a lowercase letter"):
            validate_application_id("123app")
        with pytest.raises(ValueError, match="must be a string"):
            validate_application_id(123)  # type: ignore


# ==============================================================================
# 2. CROSS-APP ENTITY REFERENCE (BopEntityRef) & OPAQUE ENTITY ID TESTS
# ==============================================================================

class TestBopEntityRef:
    def test_valid_opaque_entity_ids(self):
        org_uuid = str(uuid.uuid4())
        valid_ids = [
            "12345",
            "crm-lead-001",
            "01JABCDEF1234567890",
            "550e8400-e29b-41d4-a716-446655440000",
            "custom:urn:ref#99",
        ]
        for eid in valid_ids:
            ref = BopEntityRef(
                bop_organization_id=org_uuid,
                application_id="bopclients",
                entity_type="prospect",
                entity_id=eid,
            )
            assert ref.entity_id == eid
            assert ref.app_id == "bopclients"

    def test_entity_ref_immutability(self):
        org_uuid = str(uuid.uuid4())
        ref = BopEntityRef(
            bop_organization_id=org_uuid,
            application_id="bopclients",
            entity_type="prospect",
            entity_id="p1",
        )
        with pytest.raises(AttributeError):
            ref.entity_id = "p2"  # type: ignore

    def test_entity_ref_rejects_invalid_uuid(self):
        with pytest.raises(InvalidEntityRef, match="not a valid UUID"):
            BopEntityRef(
                bop_organization_id="not-a-uuid",
                application_id="bopclients",
                entity_type="prospect",
                entity_id="p1",
            )

    def test_entity_ref_rejects_empty_or_oversized_entity_id(self):
        org_uuid = str(uuid.uuid4())
        with pytest.raises(InvalidEntityRef, match="non-empty string"):
            BopEntityRef(bop_organization_id=org_uuid, application_id="bopclients", entity_type="prospect", entity_id="")
        with pytest.raises(InvalidEntityRef, match="exceeds maximum length"):
            BopEntityRef(bop_organization_id=org_uuid, application_id="bopclients", entity_type="prospect", entity_id="x" * 150)

    def test_entity_ref_serialization_roundtrip(self):
        org_uuid = str(uuid.uuid4())
        ref = BopEntityRef(
            bop_organization_id=org_uuid,
            application_id="bopclients",
            entity_type="prospect",
            entity_id="crm-lead-001",
        )
        d = ref.to_dict()
        assert d == {
            "bop_organization_id": org_uuid,
            "application_id": "bopclients",
            "entity_type": "prospect",
            "entity_id": "crm-lead-001",
        }
        reconstructed = BopEntityRef.from_dict(d)
        assert reconstructed == ref
        assert reconstructed.entity_id == "crm-lead-001"

    def test_identical_entity_id_distinct_across_tenants(self):
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        ref_a = BopEntityRef(bop_organization_id=tenant_a, application_id="bopcrm", entity_type="lead", entity_id="123")
        ref_b = BopEntityRef(bop_organization_id=tenant_b, application_id="bopcrm", entity_type="lead", entity_id="123")

        assert ref_a.entity_id == ref_b.entity_id
        assert ref_a.bop_organization_id != ref_b.bop_organization_id
        assert ref_a != ref_b


# ==============================================================================
# 3. EVENT ENVELOPE (BopIntegrationEvent) & VALIDATION TESTS
# ==============================================================================

class TestBopIntegrationEvent:
    def test_root_event_with_causation_id_none_roundtrip(self):
        org_uuid = str(uuid.uuid4())
        event_uuid = str(uuid.uuid4())
        subject = BopEntityRef(
            bop_organization_id=org_uuid,
            application_id="bopclients",
            entity_type="prospect",
            entity_id="crm-lead-001",
        )
        event = BopIntegrationEvent(
            event_id=event_uuid,
            event_type="prospect.discovered",
            event_version=1,
            occurred_at="2026-09-14T10:00:00.000000Z",
            producer_app="bopclients",
            bop_organization_id=org_uuid,
            subject=subject,
            correlation_id=str(uuid.uuid4()),
            causation_id=None,  # Root event
            payload={"prospect_id": "crm-lead-001", "display_name": "Acme", "source_provider": "overture"},
            metadata={},
        )

        assert event.causation_id is None
        assert event.source_app == "bopclients"
        assert event.entity_ref == subject

        # Roundtrip JSON
        json_str = event.to_json()
        reconstructed = BopIntegrationEvent.from_json(json_str)
        assert reconstructed == event
        assert reconstructed.causation_id is None
        assert reconstructed.subject.entity_id == "crm-lead-001"

    def test_derived_event_with_parent_causation_id(self):
        org_uuid = str(uuid.uuid4())
        parent_eid = str(uuid.uuid4())
        child_eid = str(uuid.uuid4())
        subject = BopEntityRef(bop_organization_id=org_uuid, application_id="bopclients", entity_type="prospect", entity_id="123")
        event = BopIntegrationEvent(
            event_id=child_eid,
            event_type="prospect.qualified",
            event_version=1,
            occurred_at="2026-09-14T10:00:00.000000Z",
            producer_app="bopclients",
            bop_organization_id=org_uuid,
            subject=subject,
            correlation_id=str(uuid.uuid4()),
            causation_id=parent_eid,
            payload={"prospect_id": "123", "lead_score": 90, "priority": "HIGH", "qualification_summary": "Active RFP"},
        )
        assert event.causation_id == parent_eid

    def test_deterministic_repeated_serialization(self):
        org_uuid = str(uuid.uuid4())
        event_uuid = str(uuid.uuid4())
        subject = BopEntityRef(bop_organization_id=org_uuid, application_id="bopclients", entity_type="prospect", entity_id="p1")
        event = BopIntegrationEvent(
            event_id=event_uuid,
            event_type="prospect.discovered",
            event_version=1,
            occurred_at="2026-09-14T00:00:00Z",
            producer_app="bopclients",
            bop_organization_id=org_uuid,
            subject=subject,
            correlation_id=str(uuid.uuid4()),
            payload={"b": 2, "a": 1},
        )
        assert event.to_json() == event.to_json()

    def test_cross_tenant_mismatch_raises_cross_tenant_integration_event(self):
        org_a = str(uuid.uuid4())
        org_b = str(uuid.uuid4())
        subject_b = BopEntityRef(
            bop_organization_id=org_b,
            application_id="bopclients",
            entity_type="prospect",
            entity_id="p1",
        )
        with pytest.raises(CrossTenantIntegrationEvent, match="Tenant mismatch"):
            BopIntegrationEvent(
                event_id=str(uuid.uuid4()),
                event_type="prospect.discovered",
                event_version=1,
                occurred_at=datetime.now(timezone.utc).isoformat(),
                producer_app="bopclients",
                bop_organization_id=org_a,  # Tenant A envelope + Tenant B subject
                subject=subject_b,
                correlation_id=str(uuid.uuid4()),
                payload={},
            )

    def test_future_wire_compatible_app_id_survives_roundtrip(self):
        org_uuid = str(uuid.uuid4())
        subject = BopEntityRef(
            bop_organization_id=org_uuid,
            application_id="bopinventory",
            entity_type="item",
            entity_id="item-99",
        )
        event = BopIntegrationEvent(
            event_id=str(uuid.uuid4()),
            event_type="inventory.stocked",
            event_version=1,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            producer_app="bopinventory",
            bop_organization_id=org_uuid,
            subject=subject,
            correlation_id=str(uuid.uuid4()),
            payload={"sku": "SKU-1"},
        )
        json_str = event.to_json()
        reconstructed = BopIntegrationEvent.from_json(json_str)
        assert reconstructed.producer_app == "bopinventory"
        assert reconstructed.subject.application_id == "bopinventory"


# ==============================================================================
# 4. SECRET SCANNER TESTS
# ==============================================================================

class TestSecretScanner:
    @pytest.fixture
    def envelope_factory(self):
        org_uuid = str(uuid.uuid4())
        subject = BopEntityRef(bop_organization_id=org_uuid, application_id="bopclients", entity_type="prospect", entity_id="1")
        def _make(payload, metadata=None):
            return BopIntegrationEvent(
                event_id=str(uuid.uuid4()),
                event_type="prospect.discovered",
                event_version=1,
                occurred_at=datetime.now(timezone.utc).isoformat(),
                producer_app="bopclients",
                bop_organization_id=org_uuid,
                subject=subject,
                correlation_id=str(uuid.uuid4()),
                payload=payload,
                metadata=metadata or {},
            )
        return _make

    def test_secrets_rejected(self, envelope_factory):
        rejected_keys = ["api_key", "access_token", "password", "client_secret", "bearer", "private_key", "credentials"]
        for rk in rejected_keys:
            with pytest.raises(InvalidIntegrationEvent, match="forbidden security sensitive key"):
                envelope_factory(payload={rk: "secret_value_12345"})

    def test_legitimate_false_positives_allowed(self, envelope_factory):
        allowed_payload = {
            "token_count": 512,
            "secretary_name": "Alice Smith",
            "authentication_method": "oauth2_pkce",
            "author_name": "Bob",
        }
        event = envelope_factory(payload=allowed_payload)
        assert event.payload["token_count"] == 512
        assert event.payload["secretary_name"] == "Alice Smith"

    def test_secret_values_never_logged_in_exception(self, envelope_factory):
        secret_content = "CRITICAL_PRIVATE_KEY_VALUE_XYZ999"
        try:
            envelope_factory(payload={"api_key": secret_content})
            pytest.fail("Should have raised InvalidIntegrationEvent")
        except InvalidIntegrationEvent as ex:
            assert secret_content not in str(ex)
            assert "api_key" in str(ex)


# ==============================================================================
# 5. INITIAL EVENT PAYLOAD CONTRACT TESTS (v1)
# ==============================================================================

class TestInitialEventPayloadContracts:
    @pytest.fixture
    def test_tenant(self):
        org_id = str(uuid.uuid4())
        subject = BopEntityRef(
            bop_organization_id=org_id,
            application_id="bopclients",
            entity_type="prospect",
            entity_id="crm-lead-001",
        )
        return org_id, subject

    def test_prospect_discovered_v1(self, test_tenant):
        org_id, subject = test_tenant
        payload = {
            "prospect_id": "crm-lead-001",
            "campaign_id": "camp_123",
            "display_name": "Acme Solar Systems",
            "website": "https://acmesolar.com",
            "source_provider": "official_website",
            "source_external_id": "ext_987",
        }
        event = BopEventRegistry.build_event(
            event_type=BopEventRegistry.EVENT_PROSPECT_DISCOVERED,
            bop_organization_id=org_id,
            subject=subject,
            payload=payload,
        )
        assert event.event_type == "prospect.discovered"
        assert event.event_version == 1

        # Extra key rejected
        with pytest.raises(InvalidIntegrationEvent, match="unauthorized field"):
            BopEventRegistry.build_event(
                event_type=BopEventRegistry.EVENT_PROSPECT_DISCOVERED,
                bop_organization_id=org_id,
                subject=subject,
                payload={**payload, "unknown_field": "val"},
            )

    def test_prospect_qualified_v1(self, test_tenant):
        org_id, subject = test_tenant
        payload = {
            "prospect_id": "crm-lead-001",
            "lead_score": 88,
            "priority": "HIGH",
            "qualification_summary": "RFP active and verified budget",
        }
        event = BopEventRegistry.build_event(
            event_type=BopEventRegistry.EVENT_PROSPECT_QUALIFIED,
            bop_organization_id=org_id,
            subject=subject,
            payload=payload,
        )
        assert event.payload["lead_score"] == 88

    def test_buying_intent_detected_v1(self, test_tenant):
        org_id, subject = test_tenant
        payload = {
            "prospect_id": "crm-lead-001",
            "signal_id": "sig_555",
            "signal_type": "public_request_for_proposal",
            "confidence": 0.95,
            "source": "official_site",
            "observed_at": "2026-09-14T10:00:00Z",
            "evidence_reference": "rfp_2026",
        }
        event = BopEventRegistry.build_event(
            event_type=BopEventRegistry.EVENT_BUYING_INTENT_DETECTED,
            bop_organization_id=org_id,
            subject=subject,
            payload=payload,
        )
        assert event.payload["confidence"] == 0.95

    def test_prospect_ready_for_crm_v1_zero_pii(self, test_tenant):
        org_id, subject = test_tenant
        payload = {
            "prospect_id": "crm-lead-001",
            "lead_score": 95,
            "priority": "URGENT",
            "recommended_action": "handoff_to_rep",
            "human_review_required": False,
        }
        event = BopEventRegistry.build_event(
            event_type=BopEventRegistry.EVENT_PROSPECT_READY_FOR_CRM,
            bop_organization_id=org_id,
            subject=subject,
            payload=payload,
        )
        assert event.payload["priority"] == "URGENT"

        # Including primary_contact or PII raises error
        with pytest.raises(InvalidIntegrationEvent, match="PII fields"):
            BopEventRegistry.build_event(
                event_type=BopEventRegistry.EVENT_PROSPECT_READY_FOR_CRM,
                bop_organization_id=org_id,
                subject=subject,
                payload={
                    **payload,
                    "primary_contact": {"name": "John Doe", "email": "john@acme.com"},
                },
            )


# ==============================================================================
# 6. SQLITE MIGRATION, NOT NULL DB INVARIANT & BACKFILL STABILITY TESTS
# ==============================================================================

class TestSQLiteMigrationP17:
    def test_blank_database_migrates_to_007(self):
        db = create_database_connection(":memory:")
        ver = DatabaseMigrator.migrate(db)
        assert ver == "20260902_007"

        status = DatabaseMigrator.status(db)
        assert status["current_version"] == "20260902_007"
        assert status["is_up_to_date"] is True

        # Verify NOT NULL constraint at SQLite database level
        try:
            db.execute(
                "INSERT INTO organizations (id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("org_null_test", "Null Test", "null-test", "now", "now"),
            )
            pytest.fail("Insert without bop_organization_id should have failed at DB level")
        except Exception as e:
            assert "NOT NULL constraint failed" in str(e)

        db.close()

    def test_006_to_007_upgrade_backfills_and_enforces_not_null(self):
        db = SQLiteConnectionAdapter(":memory:")
        db.execute("""
            CREATE TABLE organizations (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                slug VARCHAR(100) UNIQUE NOT NULL,
                description TEXT,
                website VARCHAR(255),
                country VARCHAR(10) NOT NULL DEFAULT 'US',
                default_language VARCHAR(10) NOT NULL DEFAULT 'en',
                timezone VARCHAR(50) NOT NULL DEFAULT 'UTC',
                created_at VARCHAR(50) NOT NULL,
                updated_at VARCHAR(50) NOT NULL
            );
        """)
        DatabaseMigrator._apply_003_upgrades(db, is_pg=False)
        DatabaseMigrator._apply_004_upgrades(db, is_pg=False)
        DatabaseMigrator._apply_005_upgrades(db, is_pg=False)
        DatabaseMigrator._apply_006_upgrades(db, is_pg=False)
        DatabaseMigrator.ensure_version_table(db)
        db.execute("INSERT INTO bopclients_schema_version (version, applied_at) VALUES (?, ?)", ("20260902_006", datetime.now(timezone.utc).isoformat()))
        db.commit()

        # Insert organization without bop_organization_id in 006
        db.execute(
            "INSERT INTO organizations (id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("org_legacy_1", "Legacy Corp", "legacy-corp", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"),
        )
        db.commit()

        # Apply 007 migration
        new_ver = DatabaseMigrator.migrate(db)
        assert new_ver == "20260902_007"

        # Verify backfill
        row = db.fetch_dicts("SELECT id, name, bop_organization_id FROM organizations WHERE id = ?", ("org_legacy_1",))[0]
        assigned_uuid = row["bop_organization_id"]
        assert assigned_uuid is not None
        uuid.UUID(assigned_uuid)

        # Rerun migration: stable backfill
        DatabaseMigrator.migrate(db)
        row_after = db.fetch_dicts("SELECT id, bop_organization_id FROM organizations WHERE id = ?", ("org_legacy_1",))[0]
        assert row_after["bop_organization_id"] == assigned_uuid

        # Verify NOT NULL enforced at DB level after migration
        try:
            db.execute(
                "INSERT INTO organizations (id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("org_fail", "Fail", "fail", "now", "now"),
            )
            pytest.fail("Should have failed NOT NULL check")
        except Exception as e:
            assert "NOT NULL constraint failed" in str(e)

        db.close()


# ==============================================================================
# 7. ORGANIZATION IMMUTABILITY & REPOSITORY TESTS
# ==============================================================================

class TestOrganizationImmutability:
    def test_bop_organization_id_cannot_be_mutated_via_repository(self, sqlite_db):
        repo = OrganizationRepository(sqlite_db)
        org = Organization(name="Stable Corp", slug="stable-corp")
        repo.save(org)

        original_bop_id = org.bop_organization_id
        assert original_bop_id is not None

        # Attempt mutation of bop_organization_id
        org.bop_organization_id = str(uuid.uuid4())
        with pytest.raises(ValueError, match="Cannot mutate immutable bop_organization_id"):
            repo.save(org)

        # Confirm DB was not modified
        stored = repo.get_by_id(org.id)
        assert stored.bop_organization_id == original_bop_id


# ==============================================================================
# 8. TRANSACTIONAL OUTBOX TESTS (ATOMIC COMMIT & ROLLBACK)
# ==============================================================================

class TestTransactionalOutbox:
    def test_sqlite_transaction_rollback_and_commit(self, sqlite_db):
        org_repo = OrganizationRepository(sqlite_db)
        outbox_repo = IntegrationOutboxRepository(sqlite_db)

        # --- Phase A: ROLLBACK PROOF ---
        sqlite_db.begin()

        org_a = Organization(id="org-tx-a", name="Tx Corp A", slug="tx-corp-a")
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
            payload={"name": "Tx Corp A"},
        )
        outbox_repo.append(event_a)

        # Rollback transaction
        sqlite_db.rollback()

        # Both must be ABSENT
        assert org_repo.get_by_id(org_a.id) is None
        assert outbox_repo.get_by_event_id(event_a.event_id) is None

        # --- Phase B: COMMIT PROOF ---
        sqlite_db.begin()

        org_b = Organization(id="org-tx-b", name="Tx Corp B", slug="tx-corp-b")
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
            payload={"name": "Tx Corp B"},
        )
        outbox_repo.append(event_b)

        sqlite_db.commit()

        # Both must be PRESENT
        assert org_repo.get_by_id(org_b.id) is not None
        assert outbox_repo.get_by_event_id(event_b.event_id) is not None

    def test_outbox_envelope_immutability_through_failure_and_publication(self, sqlite_db):
        org_repo = OrganizationRepository(sqlite_db)
        org = Organization(id="org-outbox-imm", name="Imm Corp", slug="imm-corp")
        org_repo.save(org)
        org_id = org.bop_organization_id
        outbox_repo = IntegrationOutboxRepository(sqlite_db, org_repo=org_repo)
        subject = BopEntityRef(bop_organization_id=org_id, application_id="bopclients", entity_type="prospect", entity_id="123")
        event = BopEventRegistry.build_event(
            event_type=BopEventRegistry.EVENT_PROSPECT_DISCOVERED,
            bop_organization_id=org_id,
            subject=subject,
            payload={"prospect_id": "123", "display_name": "Test Co", "source_provider": "official_website"},
        )
        rec = outbox_repo.append(event)
        initial_envelope_json = rec.envelope_json

        # Mark failed
        outbox_repo.mark_failed(event.event_id, "ERR_NET", "Connection timeout", retry_delay_seconds=30)
        rec_failed = outbox_repo.get_by_event_id(event.event_id)
        assert rec_failed.envelope_json == initial_envelope_json

        # Mark published
        outbox_repo.mark_published(event.event_id)
        rec_pub = outbox_repo.get_by_event_id(event.event_id)
        assert rec_pub.envelope_json == initial_envelope_json
        assert rec_pub.envelope_json == event.to_json()


# ==============================================================================
# 9. INBOX IDEMPOTENCY & FAILED RETRY SEMANTICS
# ==============================================================================

class TestInboxSemantics:
    def test_inbox_idempotency_and_failed_redelivery_semantics(self, sqlite_db):
        inbox_repo = IntegrationInboxRepository(sqlite_db)
        org_id = str(uuid.uuid4())
        subject = BopEntityRef(bop_organization_id=org_id, application_id="bopcrm", entity_type="lead", entity_id="crm-100")
        event = BopIntegrationEvent(
            event_id=str(uuid.uuid4()),
            event_type="lead.converted",
            event_version=1,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            producer_app="bopcrm",
            bop_organization_id=org_id,
            subject=subject,
            correlation_id=str(uuid.uuid4()),
            payload={"deal_value": 50000},
        )

        # 1. First receipt -> new
        is_new, r1 = inbox_repo.register_received(event)
        assert is_new is True
        assert r1.status == InboxStatus.RECEIVED.value

        # 2. Mark processed
        inbox_repo.mark_processed(event.event_id)

        # 3. Redelivery of processed event -> no state regression
        is_new_dup, r2 = inbox_repo.register_received(event)
        assert is_new_dup is False
        assert r2.status == InboxStatus.PROCESSED.value

        # 4. Another event that fails
        event_fail = BopIntegrationEvent(
            event_id=str(uuid.uuid4()),
            event_type="lead.converted",
            event_version=1,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            producer_app="bopcrm",
            bop_organization_id=org_id,
            subject=subject,
            correlation_id=str(uuid.uuid4()),
            payload={"deal_value": 10000},
        )
        inbox_repo.register_received(event_fail)
        inbox_repo.mark_failed(event_fail.event_id, "HANDLER_ERROR", "DB transient error")

        # 5. Redelivery of failed event -> returns existing FAILED record deterministically
        is_new_f, r_fail = inbox_repo.register_received(event_fail)
        assert is_new_f is False
        assert r_fail.status == InboxStatus.FAILED.value
        assert r_fail.last_error_code == "HANDLER_ERROR"


# ==============================================================================
# 10. MULTI-TENANT ISOLATION TESTS
# ==============================================================================

class TestMultiTenantIsolation:
    def test_tenant_boundary_enforcement(self, sqlite_db):
        org_repo = OrganizationRepository(sqlite_db)
        org_obj_a = Organization(id="org-boundary-a", name="Org A", slug="org-a")
        org_obj_b = Organization(id="org-boundary-b", name="Org B", slug="org-b")
        org_repo.save(org_obj_a)
        org_repo.save(org_obj_b)
        org_a = org_obj_a.bop_organization_id
        org_b = org_obj_b.bop_organization_id

        outbox_repo = IntegrationOutboxRepository(sqlite_db, org_repo=org_repo)
        inbox_repo = IntegrationInboxRepository(sqlite_db)

        # Event for Org A
        subject_a = BopEntityRef(bop_organization_id=org_a, application_id="bopclients", entity_type="prospect", entity_id="123")
        event_a = BopEventRegistry.build_event(
            event_type=BopEventRegistry.EVENT_PROSPECT_DISCOVERED,
            bop_organization_id=org_a,
            subject=subject_a,
            payload={"prospect_id": "123", "display_name": "A Co", "source_provider": "official_website"},
        )
        outbox_repo.append(event_a)

        # Query pending Org B returns 0
        assert len(outbox_repo.list_pending(bop_organization_id=org_b)) == 0
        assert len(outbox_repo.list_pending(bop_organization_id=org_a)) == 1

        # Attempt mark_published with Org B tenant context -> rejects mutation
        ok = outbox_repo.mark_published(event_a.event_id, bop_organization_id=org_b)
        assert ok is False

        # Attempt mark_failed with Org B tenant context -> rejects mutation
        ok_fail = outbox_repo.mark_failed(event_a.event_id, "ERR", "msg", bop_organization_id=org_b)
        assert ok_fail is False

        # Status still PENDING for Org A
        rec = outbox_repo.get_by_event_id(event_a.event_id, bop_organization_id=org_a)
        assert rec.status == OutboxStatus.PENDING.value


# ==============================================================================
# 11. P17.2 CONTRACT INTEGRITY, STATE MACHINE & MIGRATION SAFETY TESTS
# ==============================================================================

class TestContractHardeningP17_2:
    def test_strict_uuid4_validation_rejects_other_versions_and_malformed(self):
        org_id = str(uuid.uuid4())
        subject = BopEntityRef(bop_organization_id=org_id, application_id="bopclients", entity_type="prospect", entity_id="p-1")

        # 1. Valid UUID4 -> accepted
        valid_eid = str(uuid.uuid4())
        event = BopIntegrationEvent(
            event_id=valid_eid,
            event_type="prospect.discovered",
            event_version=1,
            occurred_at="2026-09-14T10:00:00.000000Z",
            producer_app="bopclients",
            bop_organization_id=org_id,
            subject=subject,
            correlation_id=str(uuid.uuid4()),
            causation_id=None,
            payload={"prospect_id": "p-1", "display_name": "Co", "source_provider": "overture"},
        )
        assert event.event_id == valid_eid
        assert event.causation_id is None

        # 2. UUID1 -> rejected
        uuid1_str = str(uuid.uuid1())
        with pytest.raises(InvalidIntegrationEvent, match="must be UUID version 4"):
            BopIntegrationEvent(
                event_id=uuid1_str,
                event_type="prospect.discovered",
                event_version=1,
                occurred_at="2026-09-14T10:00:00.000000Z",
                producer_app="bopclients",
                bop_organization_id=org_id,
                subject=subject,
                correlation_id=str(uuid.uuid4()),
                payload={"prospect_id": "p-1", "display_name": "Co", "source_provider": "overture"},
            )

        # 3. UUID5 -> rejected
        uuid5_str = str(uuid.uuid5(uuid.NAMESPACE_DNS, "example.com"))
        with pytest.raises(InvalidIntegrationEvent, match="must be UUID version 4"):
            BopIntegrationEvent(
                event_id=uuid5_str,
                event_type="prospect.discovered",
                event_version=1,
                occurred_at="2026-09-14T10:00:00.000000Z",
                producer_app="bopclients",
                bop_organization_id=org_id,
                subject=subject,
                correlation_id=str(uuid.uuid4()),
                payload={"prospect_id": "p-1", "display_name": "Co", "source_provider": "overture"},
            )

        # 4. Malformed UUID -> rejected
        with pytest.raises(InvalidIntegrationEvent, match="not a valid UUID"):
            BopIntegrationEvent(
                event_id="malformed-uuid-1234",
                event_type="prospect.discovered",
                event_version=1,
                occurred_at="2026-09-14T10:00:00.000000Z",
                producer_app="bopclients",
                bop_organization_id=org_id,
                subject=subject,
                correlation_id=str(uuid.uuid4()),
                payload={"prospect_id": "p-1", "display_name": "Co", "source_provider": "overture"},
            )

    def test_entity_id_whitespace_semantics(self):
        org_id = str(uuid.uuid4())

        # "ABC 123" -> accepted unchanged
        ref_space = BopEntityRef(bop_organization_id=org_id, application_id="bopclients", entity_type="prospect", entity_id="ABC 123")
        assert ref_space.entity_id == "ABC 123"

        # " CUST-01 " -> accepted with exact leading/trailing spaces preserved
        ref_padded = BopEntityRef(bop_organization_id=org_id, application_id="bopclients", entity_type="prospect", entity_id=" CUST-01 ")
        assert ref_padded.entity_id == " CUST-01 "
        assert ref_padded.entity_id != "CUST-01"

        # "   " (whitespace-only) -> rejected
        with pytest.raises(InvalidEntityRef, match="whitespace-only"):
            BopEntityRef(bop_organization_id=org_id, application_id="bopclients", entity_type="prospect", entity_id="   ")

    def test_subject_vs_payload_prospect_id_equality(self):
        org_id = str(uuid.uuid4())
        subject = BopEntityRef(bop_organization_id=org_id, application_id="bopclients", entity_type="prospect", entity_id="prospect_100")

        # Matching prospect_id -> valid
        event = BopEventRegistry.build_event(
            event_type="prospect.discovered",
            bop_organization_id=org_id,
            subject=subject,
            payload={"prospect_id": "prospect_100", "display_name": "Match Co", "source_provider": "overture"},
        )
        assert event.payload["prospect_id"] == "prospect_100"

        # Mismatched prospect_id -> rejected
        with pytest.raises(InvalidIntegrationEvent, match="must equal subject.entity_id"):
            BopEventRegistry.build_event(
                event_type="prospect.discovered",
                bop_organization_id=org_id,
                subject=subject,
                payload={"prospect_id": "prospect_DIFFERENT", "display_name": "Mismatch Co", "source_provider": "overture"},
            )

    def test_producer_app_vs_subject_application_distinction(self):
        org_id = str(uuid.uuid4())
        # Entity belongs to bopclients, but event is emitted by bopcrm
        subject = BopEntityRef(bop_organization_id=org_id, application_id="bopclients", entity_type="prospect", entity_id="p-1")
        event = BopIntegrationEvent(
            event_id=str(uuid.uuid4()),
            event_type="crm.lead_synced",
            event_version=1,
            occurred_at="2026-09-14T10:00:00.000000Z",
            producer_app="bopcrm",
            bop_organization_id=org_id,
            subject=subject,
            correlation_id=str(uuid.uuid4()),
            payload={"crm_status": "synced"},
        )
        assert event.producer_app == "bopcrm"
        assert event.subject.application_id == "bopclients"
        assert event.bop_organization_id == event.subject.bop_organization_id

    def test_cross_tenant_exception_catchable_specifically(self):
        org_a = str(uuid.uuid4())
        org_b = str(uuid.uuid4())
        subject_b = BopEntityRef(bop_organization_id=org_b, application_id="bopclients", entity_type="prospect", entity_id="p-1")

        caught = False
        try:
            BopIntegrationEvent(
                event_id=str(uuid.uuid4()),
                event_type="prospect.discovered",
                event_version=1,
                occurred_at="2026-09-14T10:00:00.000000Z",
                producer_app="bopclients",
                bop_organization_id=org_a,
                subject=subject_b,
                correlation_id=str(uuid.uuid4()),
                payload={"prospect_id": "p-1", "display_name": "Mismatch", "source_provider": "overture"},
            )
        except CrossTenantIntegrationEvent:
            caught = True
        assert caught is True

    def test_buying_intent_preserves_p6_p8_classification(self, sqlite_db):
        org_id = str(uuid.uuid4())
        subject = BopEntityRef(bop_organization_id=org_id, application_id="bopclients", entity_type="prospect", entity_id="p-intent")

        # 1. Valid BUYING_INTENT signal (public_request_for_proposal / vendor_search) -> accepted
        valid_event = BopEventRegistry.build_event(
            event_type=BopEventRegistry.EVENT_BUYING_INTENT_DETECTED,
            bop_organization_id=org_id,
            subject=subject,
            payload={
                "prospect_id": "p-intent",
                "signal_id": "sig_1",
                "signal_type": "public_request_for_proposal",
                "confidence": 0.9,
                "source": "official_site",
                "observed_at": "2026-09-14T10:00:00.000000Z",
                "evidence_reference": "rfp_123",
            },
        )
        assert valid_event.payload["signal_type"] == "public_request_for_proposal"

        # 2. NEED signal (website_slow) -> rejected
        with pytest.raises(InvalidIntegrationEvent, match="not classified as BUYING_INTENT"):
            BopEventRegistry.build_event(
                event_type=BopEventRegistry.EVENT_BUYING_INTENT_DETECTED,
                bop_organization_id=org_id,
                subject=subject,
                payload={
                    "prospect_id": "p-intent",
                    "signal_id": "sig_2",
                    "signal_type": "website_slow",
                    "confidence": 0.9,
                    "source": "audit",
                    "observed_at": "2026-09-14T10:00:00.000000Z",
                },
            )

        # 3. COMPANY_ACTIVITY signal (hiring_marketing, recent_news) -> rejected
        with pytest.raises(InvalidIntegrationEvent, match="not classified as BUYING_INTENT"):
            BopEventRegistry.build_event(
                event_type=BopEventRegistry.EVENT_BUYING_INTENT_DETECTED,
                bop_organization_id=org_id,
                subject=subject,
                payload={
                    "prospect_id": "p-intent",
                    "signal_id": "sig_3",
                    "signal_type": "hiring_marketing",
                    "confidence": 0.8,
                    "source": "careers_page",
                    "observed_at": "2026-09-14T10:00:00.000000Z",
                },
            )

        # 4. Timezone-naive observed_at -> rejected
        with pytest.raises(InvalidIntegrationEvent, match="explicit timezone"):
            BopEventRegistry.build_event(
                event_type=BopEventRegistry.EVENT_BUYING_INTENT_DETECTED,
                bop_organization_id=org_id,
                subject=subject,
                payload={
                    "prospect_id": "p-intent",
                    "signal_id": "sig_4",
                    "signal_type": "vendor_search",
                    "confidence": 0.95,
                    "source": "sec_filing",
                    "observed_at": "2026-09-14T10:00:00",  # Naive
                },
            )

    def test_outbox_lossless_persistence_and_roundtrip(self, sqlite_db):
        org_repo = OrganizationRepository(sqlite_db)
        org = Organization(id="org-roundtrip", name="Roundtrip Co", slug="roundtrip-co")
        org_repo.save(org)
        org_id = org.bop_organization_id

        outbox = IntegrationOutboxRepository(sqlite_db, org_repo=org_repo)
        subject = BopEntityRef(bop_organization_id=org_id, application_id="bopclients", entity_type="prospect", entity_id="p-123")
        event = BopEventRegistry.build_event(
            event_type="prospect.discovered",
            bop_organization_id=org_id,
            subject=subject,
            payload={"prospect_id": "p-123", "display_name": "Acme", "source_provider": "overture"},
        )
        original_json = event.to_json()

        # Enqueue
        outbox.enqueue(event)

        # Reconstruct via get_event
        loaded = outbox.get_event(event.event_id)
        assert loaded is not None
        assert loaded.to_json() == original_json

        # Mark failed
        outbox.mark_failed(event.event_id, "E500", "Simulated delivery timeout", retry_delay_seconds=10)
        loaded_failed = outbox.get_event(event.event_id)
        assert loaded_failed is not None
        assert loaded_failed.to_json() == original_json

        # Mark published
        outbox.mark_published(event.event_id)
        loaded_pub = outbox.get_event(event.event_id)
        assert loaded_pub is not None
        assert loaded_pub.to_json() == original_json

    def test_inbox_lossless_persistence_and_roundtrip(self, sqlite_db):
        inbox = IntegrationInboxRepository(sqlite_db)
        org_id = str(uuid.uuid4())
        subject = BopEntityRef(bop_organization_id=org_id, application_id="bopcrm", entity_type="deal", entity_id="deal-999")
        event = BopIntegrationEvent(
            event_id=str(uuid.uuid4()),
            event_type="deal.won",
            event_version=1,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            producer_app="bopcrm",
            bop_organization_id=org_id,
            subject=subject,
            correlation_id=str(uuid.uuid4()),
            payload={"amount": 25000},
        )
        original_json = event.to_json()

        is_new, rec = inbox.register_received(event)
        assert is_new is True

        loaded = inbox.get_event(event.event_id)
        assert loaded is not None
        assert loaded.to_json() == original_json

    def test_nested_transaction_depth_tracking_prevents_premature_commit(self, sqlite_db):
        org_repo = OrganizationRepository(sqlite_db)
        outbox_repo = IntegrationOutboxRepository(sqlite_db, org_repo=org_repo)
        org_id = str(uuid.uuid4())

        org = Organization(id="org-nested-tx", name="Nested Corp", slug="nested-corp")
        subject = BopEntityRef(bop_organization_id=org.bop_organization_id, application_id="bopclients", entity_type="organization", entity_id=org.id)
        event = BopIntegrationEvent(
            event_id=str(uuid.uuid4()),
            event_type="organization.onboarded",
            event_version=1,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            producer_app="bopclients",
            bop_organization_id=org.bop_organization_id,
            subject=subject,
            correlation_id=str(uuid.uuid4()),
            payload={"name": "Nested Corp"},
        )

        # Outer transaction with inner nested transaction block
        try:
            with sqlite_db.transaction():
                org_repo.save(org)
                with sqlite_db.transaction():
                    outbox_repo.append(event)
                # Outer block raises error -> entire transaction must roll back
                raise RuntimeError("Outer business operation failed")
        except RuntimeError:
            pass

        # Verify neither organization nor outbox record was prematurely committed by inner transaction
        assert org_repo.get_by_id(org.id) is None
        assert outbox_repo.get_by_event_id(event.event_id) is None

    def test_outbox_state_machine_invariants(self, sqlite_db):
        org_repo = OrganizationRepository(sqlite_db)
        org = Organization(id="org-sm-test", name="SM Corp", slug="sm-corp")
        org_repo.save(org)
        org_id = org.bop_organization_id

        outbox = IntegrationOutboxRepository(sqlite_db, org_repo=org_repo)
        subject = BopEntityRef(bop_organization_id=org_id, application_id="bopclients", entity_type="prospect", entity_id="p-sm")
        event = BopEventRegistry.build_event(
            event_type="prospect.discovered",
            bop_organization_id=org_id,
            subject=subject,
            payload={"prospect_id": "p-sm", "display_name": "SM Co", "source_provider": "overture"},
        )
        outbox.append(event)

        # Publish record
        assert outbox.mark_published(event.event_id) is True

        # PUBLISHED cannot regress to FAILED
        outbox.mark_failed(event.event_id, "ERR", "Late failure")
        rec = outbox.get_by_event_id(event.event_id)
        assert rec.status == OutboxStatus.PUBLISHED.value

        # mark_published twice is idempotent
        assert outbox.mark_published(event.event_id) is True

    def test_inbox_state_machine_invariants(self, sqlite_db):
        inbox = IntegrationInboxRepository(sqlite_db)
        org_id = str(uuid.uuid4())
        subject = BopEntityRef(bop_organization_id=org_id, application_id="bopcrm", entity_type="lead", entity_id="lead-sm")
        event = BopIntegrationEvent(
            event_id=str(uuid.uuid4()),
            event_type="lead.converted",
            event_version=1,
            occurred_at="2026-09-14T10:00:00.000000Z",
            producer_app="bopcrm",
            bop_organization_id=org_id,
            subject=subject,
            correlation_id=str(uuid.uuid4()),
            payload={"value": 100},
        )
        inbox.register_received(event)
        inbox.mark_processed(event.event_id)

        # PROCESSED cannot regress to FAILED
        inbox.mark_failed(event.event_id, "ERR", "Should not regress")
        rec = inbox.get_by_event_id(event.event_id)
        assert rec.status == InboxStatus.PROCESSED.value

    def test_sqlite_006_to_007_with_real_child_foreign_keys(self):
        """Construct realistic schema with child FKs and verify 006 -> 007 rebuild preserves all relationships."""
        db = create_database_connection(":memory:")
        try:
            # 1. Migrate up to schema
            DatabaseMigrator.migrate(db)

            # 2. Populate organizations and child tables with real FK references
            org_id = "org-fk-test"
            user_id = "user-fk-test"
            camp_id = "camp-fk-test"
            prosp_id = "prosp-fk-test"

            db.execute(
                "INSERT INTO users (id, email, full_name, created_at) VALUES (?, ?, ?, ?)",
                (user_id, "test@fk.com", "FK User", "2026-09-01T00:00:00Z"),
            )
            db.execute(
                "INSERT INTO organizations (id, bop_organization_id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (org_id, str(uuid.uuid4()), "FK Test Org", "fk-test-org", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"),
            )
            db.execute(
                "INSERT INTO organization_members (id, organization_id, user_id, role, created_at) VALUES (?, ?, ?, ?, ?)",
                ("mem-1", org_id, user_id, "owner", "2026-09-01T00:00:00Z"),
            )
            db.execute(
                "INSERT INTO campaigns (id, organization_id, name, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (camp_id, org_id, "FK Campaign", "active", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"),
            )
            db.execute(
                "INSERT INTO prospects (id, organization_id, name, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (prosp_id, org_id, "FK Prospect", "overture", "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z"),
            )
            db.commit()

            # 3. Simulate upgrade run to 007
            DatabaseMigrator.migrate(db)

            # 4. Verify organization.id and all child rows survive
            org_rows = db.fetch_dicts("SELECT * FROM organizations WHERE id = ?", (org_id,))
            assert len(org_rows) == 1
            assert org_rows[0]["id"] == org_id
            assert org_rows[0]["bop_organization_id"] is not None

            mem_rows = db.fetch_dicts("SELECT * FROM organization_members WHERE id = 'mem-1'")
            assert len(mem_rows) == 1
            assert mem_rows[0]["organization_id"] == org_id

            camp_rows = db.fetch_dicts("SELECT * FROM campaigns WHERE id = ?", (camp_id,))
            assert len(camp_rows) == 1
            assert camp_rows[0]["organization_id"] == org_id

            prosp_rows = db.fetch_dicts("SELECT * FROM prospects WHERE id = ?", (prosp_id,))
            assert len(prosp_rows) == 1
            assert prosp_rows[0]["organization_id"] == org_id

            # 5. Verify PRAGMA foreign_key_check returns 0 violations
            fk_violations = db.fetch_dicts("PRAGMA foreign_key_check;")
            assert len(fk_violations) == 0
        finally:
            db.close()


# ==============================================================================
# 12. P17.3 BUYING-INTENT SEMANTICS & OUTBOUND TENANT INTEGRITY
# ==============================================================================

class TestP17_3_BuyingIntentAndOutboxIntegrity:
    """Rigorous tests for P17.3 Buying-Intent classification inheritance and outbox local-tenant integrity."""

    def test_unknown_local_tenant_outbox_rejected(self, sqlite_db):
        """Producer 'bopclients' with unprovisioned bop_organization_id must be rejected from outbox."""
        outbox = IntegrationOutboxRepository(sqlite_db)
        unprovisioned_org_id = str(uuid.uuid4())
        subject = BopEntityRef(
            bop_organization_id=unprovisioned_org_id,
            application_id="bopclients",
            entity_type="prospect",
            entity_id="p-unprov",
        )
        event = BopEventRegistry.build_event(
            event_type="prospect.discovered",
            bop_organization_id=unprovisioned_org_id,
            subject=subject,
            payload={"prospect_id": "p-unprov", "display_name": "Ghost Corp", "source_provider": "overture"},
        )

        with pytest.raises(UnknownLocalTenantIntegrationError, match="does not exist in local organizations"):
            outbox.append(event)

        # Confirm 0 rows written
        rows = sqlite_db.fetch_dicts("SELECT COUNT(*) AS cnt FROM bop_integration_outbox")
        assert rows[0]["cnt"] == 0

    def test_known_local_tenant_outbox_accepted(self, sqlite_db):
        """Producer 'bopclients' with provisioned local bop_organization_id must be accepted into outbox."""
        org_repo = OrganizationRepository(sqlite_db)
        org = Organization(id="org-p173-known", name="P173 Corp", slug="p173-corp")
        org_repo.save(org)

        outbox = IntegrationOutboxRepository(sqlite_db, org_repo=org_repo)
        subject = BopEntityRef(
            bop_organization_id=org.bop_organization_id,
            application_id="bopclients",
            entity_type="prospect",
            entity_id="p-known",
        )
        event = BopEventRegistry.build_event(
            event_type="prospect.discovered",
            bop_organization_id=org.bop_organization_id,
            subject=subject,
            payload={"prospect_id": "p-known", "display_name": "Valid Corp", "source_provider": "overture"},
        )

        rec = outbox.append(event)
        assert rec is not None
        assert rec.event_id == event.event_id
        assert rec.bop_organization_id == org.bop_organization_id

        # Confirm 1 row written
        stored = outbox.get_by_event_id(event.event_id)
        assert stored is not None
        assert stored.bop_organization_id == org.bop_organization_id

    def test_inbox_decoupled_from_local_tenant_provisioning(self, sqlite_db):
        """Inbound events for unprovisioned tenants must be durably received without error."""
        inbox = IntegrationInboxRepository(sqlite_db)
        unprovisioned_org_id = str(uuid.uuid4())
        subject = BopEntityRef(
            bop_organization_id=unprovisioned_org_id,
            application_id="bopcrm",
            entity_type="lead",
            entity_id="lead-ext-01",
        )
        event = BopIntegrationEvent(
            event_id=str(uuid.uuid4()),
            event_type="lead.converted",
            event_version=1,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            producer_app="bopcrm",
            bop_organization_id=unprovisioned_org_id,
            subject=subject,
            correlation_id=str(uuid.uuid4()),
            payload={"deal_size": 50000},
        )

        is_new, rec = inbox.register_received(event)
        assert is_new is True
        assert rec.status == InboxStatus.RECEIVED.value
        assert rec.bop_organization_id == unprovisioned_org_id

    def test_distinct_failures_unknown_tenant_vs_cross_tenant_mismatch(self, sqlite_db):
        """Verify that unknown local tenant and cross-tenant mismatch are distinct, separately handled errors."""
        org_repo = OrganizationRepository(sqlite_db)
        org = Organization(id="org-distinct-test", name="Distinct Corp", slug="distinct-corp")
        org_repo.save(org)

        outbox = IntegrationOutboxRepository(sqlite_db, org_repo=org_repo)

        # 1. Cross-tenant mismatch: envelope org != subject org -> raises CrossTenantIntegrationEvent
        other_org_id = str(uuid.uuid4())
        subject_mismatch = BopEntityRef(
            bop_organization_id=other_org_id,
            application_id="bopclients",
            entity_type="prospect",
            entity_id="p-mis",
        )
        with pytest.raises(CrossTenantIntegrationEvent, match="Tenant mismatch: envelope bop_organization_id"):
            BopIntegrationEvent(
                event_id=str(uuid.uuid4()),
                event_type="prospect.discovered",
                event_version=1,
                occurred_at=datetime.now(timezone.utc).isoformat(),
                producer_app="bopclients",
                bop_organization_id=org.bop_organization_id,  # Local known
                subject=subject_mismatch,  # Different org
                correlation_id=str(uuid.uuid4()),
                payload={"prospect_id": "p-mis", "display_name": "Mismatch Co", "source_provider": "overture"},
            )

        # 2. Unknown local tenant: envelope org == subject org, but tenant not provisioned locally -> raises UnknownLocalTenantIntegrationError
        unprov_id = str(uuid.uuid4())
        subject_matched_unprov = BopEntityRef(
            bop_organization_id=unprov_id,
            application_id="bopclients",
            entity_type="prospect",
            entity_id="p-unprov-matched",
        )
        event_unprov = BopIntegrationEvent(
            event_id=str(uuid.uuid4()),
            event_type="prospect.discovered",
            event_version=1,
            occurred_at=datetime.now(timezone.utc).isoformat(),
            producer_app="bopclients",
            bop_organization_id=unprov_id,
            subject=subject_matched_unprov,
            correlation_id=str(uuid.uuid4()),
            payload={"prospect_id": "p-unprov-matched", "display_name": "Unprov Co", "source_provider": "overture"},
        )
        with pytest.raises(UnknownLocalTenantIntegrationError):
            outbox.append(event_unprov)

    def test_company_activity_signals_all_rejected_from_buying_intent(self):
        """Every signal classified as COMPANY_ACTIVITY must be rejected from buying_intent.detected."""
        org_id = str(uuid.uuid4())
        subject = BopEntityRef(
            bop_organization_id=org_id,
            application_id="bopclients",
            entity_type="prospect",
            entity_id="p-activity",
        )

        company_activity_signals = [
            "hiring_marketing",
            "hiring_sales",
            "opened_new_location",
            "new_funding",
            "website_relaunch",
            "new_service_launch",
            "active_ads",
            "recent_news",
            "location_expansion",
            "leadership_change",
            "technology_change",
            "recent_website_change",
            "new_contact_found",
            "new_signal_detected",
        ]

        for sig in company_activity_signals:
            payload = {
                "prospect_id": "p-activity",
                "signal_id": f"sig_{sig}",
                "signal_type": sig,
                "confidence": 0.85,
                "source": "monitoring",
                "observed_at": "2026-09-14T10:00:00.000000Z",
                "evidence_reference": "ref_act",
            }
            with pytest.raises(InvalidIntegrationEvent, match="not classified as BUYING_INTENT"):
                BopEventRegistry.build_event(
                    event_type=BopEventRegistry.EVENT_BUYING_INTENT_DETECTED,
                    bop_organization_id=org_id,
                    subject=subject,
                    payload=payload,
                )

    def test_need_signals_all_rejected_from_buying_intent(self):
        """Every signal classified as NEED must be rejected from buying_intent.detected."""
        org_id = str(uuid.uuid4())
        subject = BopEntityRef(
            bop_organization_id=org_id,
            application_id="bopclients",
            entity_type="prospect",
            entity_id="p-need",
        )

        need_signals = [
            "website_slow",
            "no_chatbot",
            "no_booking",
            "no_analytics",
            "no_ssl",
        ]

        for sig in need_signals:
            payload = {
                "prospect_id": "p-need",
                "signal_id": f"sig_{sig}",
                "signal_type": sig,
                "confidence": 0.90,
                "source": "audit",
                "observed_at": "2026-09-14T10:00:00.000000Z",
                "evidence_reference": "ref_need",
            }
            with pytest.raises(InvalidIntegrationEvent, match="not classified as BUYING_INTENT"):
                BopEventRegistry.build_event(
                    event_type=BopEventRegistry.EVENT_BUYING_INTENT_DETECTED,
                    bop_organization_id=org_id,
                    subject=subject,
                    payload=payload,
                )

    def test_canonical_buying_intent_signals_accepted(self):
        """Canonical BUYING_INTENT signals (vendor_search, public_request_for_proposal) must be accepted."""
        org_id = str(uuid.uuid4())
        subject = BopEntityRef(
            bop_organization_id=org_id,
            application_id="bopclients",
            entity_type="prospect",
            entity_id="p-bi",
        )

        canonical_bi_signals = [
            "vendor_search",
            "public_request_for_proposal",
        ]

        for sig in canonical_bi_signals:
            payload = {
                "prospect_id": "p-bi",
                "signal_id": f"sig_{sig}",
                "signal_type": sig,
                "confidence": 0.95,
                "source": "official_site",
                "observed_at": "2026-09-14T10:00:00.000000Z",
                "evidence_reference": "ref_bi",
            }
            event = BopEventRegistry.build_event(
                event_type=BopEventRegistry.EVENT_BUYING_INTENT_DETECTED,
                bop_organization_id=org_id,
                subject=subject,
                payload=payload,
            )
            assert event.payload["signal_type"] == sig
            assert event.payload["confidence"] == 0.95
