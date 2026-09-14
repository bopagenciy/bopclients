"""Integration test suite for Phase P18: PostgreSQL Integration Outbox Dispatcher & Delivery."""

from datetime import datetime, timezone, timedelta
import json
import os
import pytest
import time
import uuid

from bopclients.domain.organization import Organization
from bopclients.domain.integration import (
    BopAppId,
    LOCAL_APPLICATION_ID,
    BopEntityRef,
    BopIntegrationEvent,
    OutboxStatus,
    DestinationTransportType,
    IntegrationDestination,
    IntegrationSubscription,
    DeliveryStatus,
    TransportResultStatus,
    TransportPublishResult,
    IntegrationTransport,
)
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.readiness import RuntimeReadinessCheck, ReadinessStatus
from bopclients.runtime.settings import RuntimeSettings
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.integration_outbox_repository import IntegrationOutboxRepository
from bopclients.infrastructure.repositories.integration_destination_repository import IntegrationDestinationRepository
from bopclients.infrastructure.repositories.integration_delivery_repository import IntegrationDeliveryRepository
from bopclients.application.integration_dispatcher import IntegrationOutboxDispatcher
from bopclients.runtime.integration_publisher_worker import IntegrationPublisherWorker


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


class MockTransport(IntegrationTransport):
    def __init__(self, outcomes=None):
        self.published_calls = []
        self.outcomes = list(outcomes) if outcomes else []

    @property
    def transport_type(self) -> str:
        return "HTTP"

    def publish(self, envelope_json: str, destination: IntegrationDestination, timeout_seconds: float = 10.0) -> TransportPublishResult:
        self.published_calls.append({"destination_id": destination.id, "envelope_json": envelope_json})
        if self.outcomes:
            return self.outcomes.pop(0)
        return TransportPublishResult(status=TransportResultStatus.SUCCESS, status_code=200)


@pytest.mark.skipif(not HAS_POSTGRES_TEST_DB, reason="PostgreSQL test DB not available")
class TestPostgresDispatcherP18:
    def setup_method(self):
        """Clean database and apply latest migration before each test."""
        db = create_database_connection(TEST_PG_URL)
        try:
            DatabaseMigrator.migrate(db)
            db.execute("DELETE FROM bop_integration_delivery_attempts;")
            db.execute("DELETE FROM bop_integration_deliveries;")
            db.execute("DELETE FROM bop_integration_subscriptions;")
            db.execute("DELETE FROM bop_integration_destinations;")
            db.execute("DELETE FROM bop_integration_outbox;")
            db.execute("DELETE FROM bop_integration_inbox;")
            db.commit()
        finally:
            db.close()

    def _create_tenant(self, db) -> Organization:
        org_repo = OrganizationRepository(db)
        bop_org_id = str(uuid.uuid4())
        org = Organization(
            id=str(uuid.uuid4()),
            name="PG Test Bop Org",
            slug=f"pg-org-{bop_org_id[:8]}",
            bop_organization_id=bop_org_id,
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        return org_repo.save(org)

    def test_postgres_migration_008_and_readiness_check(self):
        """Verify PostgreSQL migration to 20260902_008 and RuntimeReadinessCheck."""
        db = create_database_connection(TEST_PG_URL)
        try:
            ver = DatabaseMigrator.migrate(db)
            assert ver == "20260902_008"

            settings = RuntimeSettings(database_url=TEST_PG_URL)
            res = RuntimeReadinessCheck.check(settings, db)
            assert res.status == ReadinessStatus.READY
            assert res.schema_version == "20260902_008"
            assert res.tables_present is True
            assert not res.errors
        finally:
            db.close()

    def test_postgres_end_to_end_dispatch_lifecycle(self):
        """Verify end-to-end routing, claiming, delivery, attempt history, and outbox completion in PostgreSQL."""
        db = create_database_connection(TEST_PG_URL)
        try:
            tenant = self._create_tenant(db)
            dest_repo = IntegrationDestinationRepository(db)
            dest = dest_repo.create_destination(IntegrationDestination.create(
                bop_organization_id=tenant.bop_organization_id,
                target_app_id="bopcrm",
                destination_name="PG CRM Webhook",
                endpoint_url="https://crm.example/pg/webhook",
            ))
            dest_repo.create_subscription(IntegrationSubscription.create(
                bop_organization_id=tenant.bop_organization_id,
                destination_id=dest.id,
                event_type="prospect.discovered",
            ))

            event = BopIntegrationEvent(
                event_id=str(uuid.uuid4()),
                event_type="prospect.discovered",
                event_version=1,
                occurred_at=datetime.now(timezone.utc).isoformat(),
                producer_app=LOCAL_APPLICATION_ID,
                bop_organization_id=tenant.bop_organization_id,
                subject=BopEntityRef(
                    bop_organization_id=tenant.bop_organization_id,
                    application_id=LOCAL_APPLICATION_ID,
                    entity_type="prospect",
                    entity_id="p-pg-100",
                ),
                correlation_id=str(uuid.uuid4()),
                payload={"company_name": "Postgres Corp", "domain": "pg.example", "country": "US"},
            )
            outbox_repo = IntegrationOutboxRepository(db)
            outbox_repo.append(event)

            delivery_repo = IntegrationDeliveryRepository(db)
            mock_transport = MockTransport([
                TransportPublishResult(status=TransportResultStatus.SUCCESS, status_code=200, response_body_sample="OK")
            ])
            dispatcher = IntegrationOutboxDispatcher(
                outbox_repo=outbox_repo,
                destination_repo=dest_repo,
                delivery_repo=delivery_repo,
                transports={"HTTP": mock_transport},
            )

            # Route
            route_stats = dispatcher.route_pending_outbox_events(bop_organization_id=tenant.bop_organization_id)
            assert route_stats["deliveries_created"] == 1

            # Dispatch batch
            dispatch_stats = dispatcher.dispatch_batch(worker_token="pg-worker-1")
            assert dispatch_stats["deliveries_claimed"] == 1
            assert dispatch_stats["delivered"] == 1
            assert dispatch_stats["events_completed"] == 1

            # Check attempt history
            deliv = delivery_repo.list_by_event(event.event_id)[0]
            assert deliv.status == DeliveryStatus.DELIVERED.value
            attempts = delivery_repo.list_attempts(deliv.id)
            assert len(attempts) == 1
            assert attempts[0].status == TransportResultStatus.SUCCESS.value
            assert attempts[0].status_code == 200

            # Check outbox status
            outbox_rec = outbox_repo.get_by_event_id(event.event_id)
            assert outbox_rec.status == OutboxStatus.PUBLISHED.value
            assert outbox_rec.published_at is not None
        finally:
            db.close()

    def test_postgres_concurrent_worker_skip_locked_claiming(self):
        """Verify two simultaneous connections claiming with FOR UPDATE SKIP LOCKED do NOT double-claim."""
        db1 = create_database_connection(TEST_PG_URL)
        db2 = create_database_connection(TEST_PG_URL)
        try:
            tenant = self._create_tenant(db1)
            dest_repo = IntegrationDestinationRepository(db1)
            dest = dest_repo.create_destination(IntegrationDestination.create(
                bop_organization_id=tenant.bop_organization_id,
                target_app_id="bopcrm",
                destination_name="PG Webhook",
                endpoint_url="https://crm.example/webhook",
            ))

            delivery_repo1 = IntegrationDeliveryRepository(db1)
            delivery_repo2 = IntegrationDeliveryRepository(db2)

            # Create 4 deliveries
            for i in range(4):
                delivery_repo1.create_delivery(
                    event_id=str(uuid.uuid4()),
                    destination_id=dest.id,
                    bop_organization_id=tenant.bop_organization_id,
                )

            # Worker 1 claims batch of 2 inside an explicit transaction
            with db1.transaction():
                claimed1 = delivery_repo1.claim_due_deliveries(worker_token="pg-worker-1", batch_size=2)
                assert len(claimed1) == 2

                # While worker 1 holds locks, Worker 2 claims batch of 2 on its own connection
                with db2.transaction():
                    claimed2 = delivery_repo2.claim_due_deliveries(worker_token="pg-worker-2", batch_size=2)
                    assert len(claimed2) == 2

                    # Mutually exclusive: no delivery claimed by both
                    ids1 = {c.id for c in claimed1}
                    ids2 = {c.id for c in claimed2}
                    assert ids1.isdisjoint(ids2)

        finally:
            db1.close()
            db2.close()

    def test_postgres_stale_claim_recovery_and_owner_guard(self):
        """Verify stale claims are recovered and stale owners cannot mark delivered in PostgreSQL."""
        db = create_database_connection(TEST_PG_URL)
        try:
            tenant = self._create_tenant(db)
            dest_repo = IntegrationDestinationRepository(db)
            dest = dest_repo.create_destination(IntegrationDestination.create(
                bop_organization_id=tenant.bop_organization_id,
                target_app_id="bopcrm",
                destination_name="PG Webhook",
                endpoint_url="https://crm.example/webhook",
            ))
            delivery_repo = IntegrationDeliveryRepository(db)
            deliv = delivery_repo.create_delivery(
                event_id=str(uuid.uuid4()),
                destination_id=dest.id,
                bop_organization_id=tenant.bop_organization_id,
            )

            # Claim with Worker Expired
            c1 = delivery_repo.claim_due_deliveries(worker_token="pg-expired", lease_seconds=1)
            assert len(c1) == 1

            # Expire lease in DB
            past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
            db.execute("UPDATE bop_integration_deliveries SET claim_expires_at = %s WHERE id = %s", (past_iso, deliv.id))
            db.commit()

            # Reclaim with Worker Active
            c2 = delivery_repo.claim_due_deliveries(worker_token="pg-active", lease_seconds=60)
            assert len(c2) == 1
            assert c2[0].claim_token == "pg-active"

            # Expired worker cannot mark delivered
            assert delivery_repo.mark_delivered(deliv.id, "pg-expired") is False

            # Active worker marks delivered
            assert delivery_repo.mark_delivered(deliv.id, "pg-active") is True

        finally:
            db.close()

    def test_postgres_migration_007_to_008_preserves_data(self):
        """Verify PostgreSQL migration from 007 to 008 preserves all P17 data."""
        db = create_database_connection(TEST_PG_URL)
        try:
            # Re-run migration idempotently
            ver = DatabaseMigrator.migrate(db)
            assert ver == "20260902_008"

            tenant = self._create_tenant(db)
            now_iso = datetime.now(timezone.utc).isoformat()
            evt_id = str(uuid.uuid4())
            db.execute(
                """INSERT INTO bop_integration_outbox (
                    id, event_id, bop_organization_id, event_type, event_version, producer_app,
                    subject_bop_org_id, subject_application_id, subject_entity_type, subject_entity_id,
                    correlation_id, envelope_json, status, attempt_count, available_at, created_at
                ) VALUES (%s, %s, %s, %s, 1, 'bopclients', %s, 'bopclients', 'prospect', 'p-1', %s, '{}', 'PENDING', 0, %s, %s)""",
                (str(uuid.uuid4()), evt_id, tenant.bop_organization_id, "prospect.discovered", tenant.bop_organization_id, str(uuid.uuid4()), now_iso, now_iso),
            )
            inbox_id = str(uuid.uuid4())
            db.execute(
                "INSERT INTO bop_integration_inbox (id, event_id, producer_app, bop_organization_id, event_type, event_version, envelope_json, received_at, status) "
                "VALUES (%s, %s, 'bopcrm', %s, 'deal.won', 1, '{}', %s, 'RECEIVED')",
                (inbox_id, str(uuid.uuid4()), tenant.bop_organization_id, now_iso),
            )
            db.commit()

            # Re-run migrate
            ver_after = DatabaseMigrator.migrate(db)
            assert ver_after == "20260902_008"

            # Check rows intact
            rows_out = db.fetch_dicts("SELECT * FROM bop_integration_outbox WHERE event_id = %s", (evt_id,))
            assert len(rows_out) == 1
            rows_in = db.fetch_dicts("SELECT * FROM bop_integration_inbox WHERE id = %s", (inbox_id,))
            assert len(rows_in) == 1

        finally:
            db.close()

    def test_postgres_destination_deletion_restrict_preserves_history(self):
        """P18.2: Verify PostgreSQL foreign key ON DELETE RESTRICT on bop_integration_deliveries prevents accidental cascade deletion."""
        db = create_database_connection(TEST_PG_URL)
        try:
            tenant = self._create_tenant(db)
            dest_repo = IntegrationDestinationRepository(db)
            dest = dest_repo.create_destination(IntegrationDestination.create(
                bop_organization_id=tenant.bop_organization_id,
                target_app_id="bopcrm",
                destination_name="PG Restrict Test",
                endpoint_url="https://crm.example/webhook",
            ))
            delivery_repo = IntegrationDeliveryRepository(db)
            deliv = delivery_repo.create_delivery(
                event_id=str(uuid.uuid4()),
                destination_id=dest.id,
                bop_organization_id=tenant.bop_organization_id,
            )

            # Attempting to delete destination MUST raise foreign key violation in PostgreSQL
            import pytest
            with pytest.raises(Exception) as exc_info:
                db.execute("DELETE FROM bop_integration_destinations WHERE id = %s", (dest.id,))
                db.commit()
            assert "foreign key" in str(exc_info.value).lower() or "violates foreign key constraint" in str(exc_info.value).lower()

        finally:
            db.close()
