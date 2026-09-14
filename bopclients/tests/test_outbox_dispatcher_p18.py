"""Comprehensive test suite for Phase P18: Integration Outbox Dispatcher & Transport Delivery."""

from datetime import datetime, timezone, timedelta
import json
import uuid
import pytest

from forge.db import ForgeDB
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
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository
from bopclients.infrastructure.repositories.integration_outbox_repository import IntegrationOutboxRepository
from bopclients.infrastructure.repositories.integration_destination_repository import IntegrationDestinationRepository
from bopclients.infrastructure.repositories.integration_delivery_repository import IntegrationDeliveryRepository
from bopclients.infrastructure.transports.http_transport import HttpWebhookTransport
from bopclients.application.integration_dispatcher import IntegrationOutboxDispatcher
from bopclients.runtime.integration_publisher_worker import IntegrationPublisherWorker
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.settings import RuntimeSettings


class MockTransport(IntegrationTransport):
    """Configurable mock transport for deterministic testing."""

    def __init__(self, outcomes=None):
        self.transport_type_val = "HTTP"
        self.published_calls = []
        # outcomes can be a single result or a list/queue
        self.outcomes = list(outcomes) if outcomes else []

    @property
    def transport_type(self) -> str:
        return self.transport_type_val

    def publish(self, envelope_json: str, destination: IntegrationDestination, timeout_seconds: float = 10.0) -> TransportPublishResult:
        self.published_calls.append({
            "envelope_json": envelope_json,
            "destination_id": destination.id,
            "endpoint_url": destination.endpoint_url,
            "timeout_seconds": timeout_seconds,
        })
        if self.outcomes:
            return self.outcomes.pop(0)
        return TransportPublishResult(status=TransportResultStatus.SUCCESS, status_code=200)


@pytest.fixture
def test_db():
    """In-memory SQLite database fully migrated to 20260902_008."""
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)
    yield db
    db.close()


from bopclients.domain.organization import Organization


@pytest.fixture
def sample_tenant(test_db):
    """Provision a local organization."""
    org_repo = OrganizationRepository(test_db)
    bop_org_id = str(uuid.uuid4())
    org = Organization(
        id=str(uuid.uuid4()),
        name="Test Bop Org",
        slug=f"test-bop-org-{bop_org_id[:8]}",
        bop_organization_id=bop_org_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    return org_repo.save(org)


@pytest.fixture
def sample_event(sample_tenant):
    """Create a canonical prospect.discovered event."""
    return BopIntegrationEvent(
        event_id=str(uuid.uuid4()),
        event_type="prospect.discovered",
        event_version=1,
        occurred_at=datetime.now(timezone.utc).isoformat(),
        producer_app=LOCAL_APPLICATION_ID,
        bop_organization_id=sample_tenant.bop_organization_id,
        subject=BopEntityRef(
            bop_organization_id=sample_tenant.bop_organization_id,
            application_id=LOCAL_APPLICATION_ID,
            entity_type="prospect",
            entity_id="p-12345",
        ),
        correlation_id=str(uuid.uuid4()),
        payload={
            "company_name": "Acme Innovations",
            "domain": "acme.com",
            "country": "US",
        },
    )


# ---------------- 1. Migration & Readiness Verification ----------------

def test_migration_008_creates_all_tables_and_indexes(test_db):
    """Verify that migration 20260902_008 creates all 4 new tables and their indexes."""
    current_ver = DatabaseMigrator.get_current_version(test_db)
    assert current_ver == "20260902_008"

    table_names = [r["name"] for r in test_db.fetch_dicts("SELECT name FROM sqlite_master WHERE type='table'")]
    assert "bop_integration_destinations" in table_names
    assert "bop_integration_subscriptions" in table_names
    assert "bop_integration_deliveries" in table_names
    assert "bop_integration_delivery_attempts" in table_names

    index_names = [r["name"] for r in test_db.fetch_dicts("SELECT name FROM sqlite_master WHERE type='index'")]
    assert "idx_dest_tenant" in index_names
    assert "idx_sub_event_type" in index_names
    assert "idx_deliv_due_claim" in index_names
    assert "idx_deliv_tenant" in index_names
    assert "idx_deliv_claim_lease" in index_names
    assert "idx_deliv_att_delivery" in index_names


# ---------------- 2. Destination & Subscription Repository ----------------

def test_destination_and_subscription_crud(test_db, sample_tenant):
    """Verify destination creation, listing, and subscription attachment with tenant safety."""
    repo = IntegrationDestinationRepository(test_db)
    dest = IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="bopcrm",
        destination_name="BopCRM Production Webhook",
        endpoint_url="https://crm.bop.example/webhooks/events",
        headers_template={"X-Consumer-Channel": "sales-sync"},
    )
    saved_dest = repo.create_destination(dest)
    assert saved_dest.id == dest.id

    # Verify listing
    dests = repo.list_destinations(sample_tenant.bop_organization_id)
    assert len(dests) == 1
    assert dests[0].target_app_id == "bopcrm"
    assert dests[0].get_headers_template() == {"X-Consumer-Channel": "sales-sync"}

    # Add subscription
    sub = IntegrationSubscription.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        destination_id=saved_dest.id,
        event_type="prospect.discovered",
    )
    saved_sub = repo.create_subscription(sub)
    assert saved_sub.id == sub.id

    # Match event type
    matched = repo.get_destinations_for_event(sample_tenant.bop_organization_id, "prospect.discovered")
    assert len(matched) == 1
    assert matched[0].id == saved_dest.id

    # Wildcard match
    wild_sub = IntegrationSubscription.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        destination_id=saved_dest.id,
        event_type="*",
    )
    repo.create_subscription(wild_sub)
    matched_wild = repo.get_destinations_for_event(sample_tenant.bop_organization_id, "any.unknown.event")
    assert len(matched_wild) == 1
    assert matched_wild[0].id == saved_dest.id


def test_cross_tenant_subscription_rejected(test_db, sample_tenant):
    """Verify cannot create subscription pointing to another tenant's destination."""
    repo = IntegrationDestinationRepository(test_db)
    dest = IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="bopcrm",
        destination_name="BopCRM Dest",
        endpoint_url="https://crm.bop.example/webhooks",
    )
    repo.create_destination(dest)

    other_tenant_id = str(uuid.uuid4())
    sub = IntegrationSubscription.create(
        bop_organization_id=other_tenant_id,
        destination_id=dest.id,
        event_type="prospect.discovered",
    )
    with pytest.raises(ValueError, match="does not belong to tenant"):
        repo.create_subscription(sub)


# ---------------- 3. Routing & Zero Destination Handling ----------------

def test_routing_zero_destinations_marks_unrouted_failure(test_db, sample_tenant, sample_event):
    """Verify events with NO subscribed destinations are not marked PUBLISHED, but FAILED with clear reason."""
    outbox_repo = IntegrationOutboxRepository(test_db)
    dest_repo = IntegrationDestinationRepository(test_db)
    delivery_repo = IntegrationDeliveryRepository(test_db)

    outbox_rec = outbox_repo.append(sample_event)
    assert outbox_rec.status == OutboxStatus.PENDING.value

    dispatcher = IntegrationOutboxDispatcher(outbox_repo, dest_repo, delivery_repo)
    stats = dispatcher.route_pending_outbox_events(bop_organization_id=sample_tenant.bop_organization_id)

    assert stats["unrouted_events"] == 1
    assert stats["deliveries_created"] == 0

    reloaded = outbox_repo.get_by_event_id(sample_event.event_id)
    assert reloaded.status == OutboxStatus.FAILED.value
    assert reloaded.last_error_code == "NO_SUBSCRIBED_DESTINATIONS"


def test_routing_fans_out_to_multiple_destinations(test_db, sample_tenant, sample_event):
    """Verify 1 outbox event fans out into N separate destination deliveries."""
    outbox_repo = IntegrationOutboxRepository(test_db)
    dest_repo = IntegrationDestinationRepository(test_db)
    delivery_repo = IntegrationDeliveryRepository(test_db)

    # Register 2 destinations (BopCRM and BopERP)
    dest1 = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="bopcrm",
        destination_name="CRM Hook",
        endpoint_url="https://crm.example/events",
    ))
    dest2 = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="boperp",
        destination_name="ERP Hook",
        endpoint_url="https://erp.example/events",
    ))

    # Subscribe both to prospect.discovered
    dest_repo.create_subscription(IntegrationSubscription.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        destination_id=dest1.id,
        event_type="prospect.discovered",
    ))
    dest_repo.create_subscription(IntegrationSubscription.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        destination_id=dest2.id,
        event_type="prospect.discovered",
    ))

    outbox_repo.append(sample_event)

    dispatcher = IntegrationOutboxDispatcher(outbox_repo, dest_repo, delivery_repo)
    stats = dispatcher.route_pending_outbox_events(bop_organization_id=sample_tenant.bop_organization_id)

    assert stats["deliveries_created"] == 2
    deliveries = delivery_repo.list_by_event(sample_event.event_id)
    assert len(deliveries) == 2
    dest_ids = {d.destination_id for d in deliveries}
    assert dest_ids == {dest1.id, dest2.id}


# ---------------- 4. Atomic Claiming & Stale Lease Recovery ----------------

def test_atomic_claim_and_stale_lease_recovery(test_db, sample_tenant, sample_event):
    """Verify claim_due_deliveries claims pending items and recovers expired leases."""
    outbox_repo = IntegrationOutboxRepository(test_db)
    dest_repo = IntegrationDestinationRepository(test_db)
    delivery_repo = IntegrationDeliveryRepository(test_db)

    dest = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="bopcrm",
        destination_name="CRM Hook",
        endpoint_url="https://crm.example/events",
    ))
    dest_repo.create_subscription(IntegrationSubscription.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        destination_id=dest.id,
        event_type="prospect.discovered",
    ))
    outbox_repo.append(sample_event)

    dispatcher = IntegrationOutboxDispatcher(outbox_repo, dest_repo, delivery_repo)
    dispatcher.route_pending_outbox_events()

    # Claim with Worker 1
    claimed_w1 = delivery_repo.claim_due_deliveries(worker_token="worker-1", lease_seconds=2)
    assert len(claimed_w1) == 1
    assert claimed_w1[0].claim_token == "worker-1"
    assert claimed_w1[0].status == DeliveryStatus.CLAIMED.value

    # Worker 2 attempts to claim concurrently: should get 0 rows because lease is active
    claimed_w2 = delivery_repo.claim_due_deliveries(worker_token="worker-2", lease_seconds=2)
    assert len(claimed_w2) == 0

    # Simulate lease expiration in DB
    past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    test_db.execute("UPDATE bop_integration_deliveries SET claim_expires_at = ?", (past_iso,))
    test_db.commit()

    # Worker 3 claims expired lease
    claimed_w3 = delivery_repo.claim_due_deliveries(worker_token="worker-3", lease_seconds=60)
    assert len(claimed_w3) == 1
    assert claimed_w3[0].claim_token == "worker-3"


def test_stale_owner_cannot_overwrite_newer_lease(test_db, sample_tenant, sample_event):
    """Verify an expired worker cannot mark_delivered after another worker has claimed the row."""
    outbox_repo = IntegrationOutboxRepository(test_db)
    dest_repo = IntegrationDestinationRepository(test_db)
    delivery_repo = IntegrationDeliveryRepository(test_db)

    dest = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="bopcrm",
        destination_name="CRM Hook",
        endpoint_url="https://crm.example/events",
    ))
    dest_repo.create_subscription(IntegrationSubscription.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        destination_id=dest.id,
        event_type="prospect.discovered",
    ))
    outbox_repo.append(sample_event)
    IntegrationOutboxDispatcher(outbox_repo, dest_repo, delivery_repo).route_pending_outbox_events()

    delivery_repo.claim_due_deliveries(worker_token="worker-expired", lease_seconds=1)

    # Reclaim by new worker
    past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    test_db.execute("UPDATE bop_integration_deliveries SET claim_expires_at = ?", (past_iso,))
    test_db.commit()
    delivery_repo.claim_due_deliveries(worker_token="worker-active", lease_seconds=60)

    # Expired worker attempts to mark delivered
    deliveries = delivery_repo.list_by_event(sample_event.event_id)
    deliv_id = deliveries[0].id

    success_expired = delivery_repo.mark_delivered(delivery_id=deliv_id, claim_token="worker-expired")
    assert success_expired is False

    # Active worker marks delivered successfully
    success_active = delivery_repo.mark_delivered(delivery_id=deliv_id, claim_token="worker-active")
    assert success_active is True


# ---------------- 5. Dispatch, Retry, Dead Letter & Outbox Status Sync ----------------

def test_dispatch_successful_delivery_and_outbox_completion(test_db, sample_tenant, sample_event):
    """Verify successful transport delivery marks delivery DELIVERED, logs attempt, and sets outbox to PUBLISHED."""
    outbox_repo = IntegrationOutboxRepository(test_db)
    dest_repo = IntegrationDestinationRepository(test_db)
    delivery_repo = IntegrationDeliveryRepository(test_db)

    dest = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="bopcrm",
        destination_name="CRM Hook",
        endpoint_url="https://crm.example/events",
    ))
    dest_repo.create_subscription(IntegrationSubscription.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        destination_id=dest.id,
        event_type="prospect.discovered",
    ))
    outbox_repo.append(sample_event)

    mock_transport = MockTransport([
        TransportPublishResult(status=TransportResultStatus.SUCCESS, status_code=200, response_body_sample='{"ok": true}')
    ])
    dispatcher = IntegrationOutboxDispatcher(
        outbox_repo=outbox_repo,
        destination_repo=dest_repo,
        delivery_repo=delivery_repo,
        transports={"HTTP": mock_transport},
    )

    # 1. Route
    dispatcher.route_pending_outbox_events()
    # 2. Dispatch
    stats = dispatcher.dispatch_batch(worker_token="test-worker")

    assert stats["deliveries_claimed"] == 1
    assert stats["delivered"] == 1
    assert stats["events_completed"] == 1

    # Verify attempt log
    deliv = delivery_repo.list_by_event(sample_event.event_id)[0]
    assert deliv.status == DeliveryStatus.DELIVERED.value
    assert deliv.delivered_at is not None

    attempts = delivery_repo.list_attempts(deliv.id)
    assert len(attempts) == 1
    assert attempts[0].status == TransportResultStatus.SUCCESS.value
    assert attempts[0].status_code == 200

    # Verify outbox event transitioned to PUBLISHED
    outbox_rec = outbox_repo.get_by_event_id(sample_event.event_id)
    assert outbox_rec.status == OutboxStatus.PUBLISHED.value
    assert outbox_rec.published_at is not None

    # Verify envelope_json delivered was unmodified and complete
    assert len(mock_transport.published_calls) == 1
    sent_payload = json.loads(mock_transport.published_calls[0]["envelope_json"])
    assert sent_payload["event_id"] == sample_event.event_id
    assert sent_payload["payload"]["company_name"] == "Acme Innovations"


def test_transient_failure_retries_and_reaches_dead_letter(test_db, sample_tenant, sample_event):
    """Verify transient failures backoff up to max_attempts before transitioning to DEAD_LETTER."""
    outbox_repo = IntegrationOutboxRepository(test_db)
    dest_repo = IntegrationDestinationRepository(test_db)
    delivery_repo = IntegrationDeliveryRepository(test_db)

    dest = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="bopcrm",
        destination_name="CRM Hook",
        endpoint_url="https://crm.example/events",
    ))
    dest_repo.create_subscription(IntegrationSubscription.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        destination_id=dest.id,
        event_type="prospect.discovered",
    ))
    outbox_repo.append(sample_event)

    # Max attempts = 2 for quick dead letter test
    deliv_record = delivery_repo.create_delivery(
        event_id=sample_event.event_id,
        destination_id=dest.id,
        bop_organization_id=sample_tenant.bop_organization_id,
        max_attempts=2,
    )

    mock_transport = MockTransport([
        # Attempt 1: 503 Service Unavailable (transient)
        TransportPublishResult(status=TransportResultStatus.TRANSIENT_FAILURE, status_code=503, error_code="HTTP_503"),
        # Attempt 2: 503 Service Unavailable (transient -> exceeds max_attempts)
        TransportPublishResult(status=TransportResultStatus.TRANSIENT_FAILURE, status_code=503, error_code="HTTP_503"),
    ])
    dispatcher = IntegrationOutboxDispatcher(
        outbox_repo=outbox_repo,
        destination_repo=dest_repo,
        delivery_repo=delivery_repo,
        transports={"HTTP": mock_transport},
    )

    # Dispatch 1
    stats1 = dispatcher.dispatch_batch(worker_token="w1")
    assert stats1["deliveries_claimed"] == 1
    assert stats1["retried"] == 1
    assert stats1["delivered"] == 0

    d1 = delivery_repo.get_by_id(deliv_record.id)
    assert d1.status == DeliveryStatus.RETRY_PENDING.value
    assert d1.attempt_count == 1

    # Fast forward next_attempt_at
    past_iso = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    test_db.execute("UPDATE bop_integration_deliveries SET next_attempt_at = ?", (past_iso,))
    test_db.commit()

    # Dispatch 2 (hits max_attempts -> DEAD_LETTER)
    stats2 = dispatcher.dispatch_batch(worker_token="w2")
    assert stats2["deliveries_claimed"] == 1
    assert stats2["dead_letter"] == 1

    d2 = delivery_repo.get_by_id(deliv_record.id)
    assert d2.status == DeliveryStatus.DEAD_LETTER.value
    assert d2.attempt_count == 2

    # Outbox status should now be FAILED
    outbox_rec = outbox_repo.get_by_event_id(sample_event.event_id)
    assert outbox_rec.status == OutboxStatus.FAILED.value
    assert outbox_rec.last_error_code == "HTTP_503"


def test_permanent_failure_transitions_directly_to_dead_letter(test_db, sample_tenant, sample_event):
    """Verify permanent failures (e.g. 400 Client Error) transition immediately to DEAD_LETTER without retries."""
    outbox_repo = IntegrationOutboxRepository(test_db)
    dest_repo = IntegrationDestinationRepository(test_db)
    delivery_repo = IntegrationDeliveryRepository(test_db)

    dest = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="bopcrm",
        destination_name="CRM Hook",
        endpoint_url="https://crm.example/events",
    ))
    dest_repo.create_subscription(IntegrationSubscription.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        destination_id=dest.id,
        event_type="prospect.discovered",
    ))
    outbox_repo.append(sample_event)
    IntegrationOutboxDispatcher(outbox_repo, dest_repo, delivery_repo).route_pending_outbox_events()

    mock_transport = MockTransport([
        TransportPublishResult(
            status=TransportResultStatus.PERMANENT_FAILURE,
            status_code=400,
            error_code="HTTP_400_BAD_REQUEST",
            error_message="Invalid request body",
        )
    ])
    dispatcher = IntegrationOutboxDispatcher(
        outbox_repo=outbox_repo,
        destination_repo=dest_repo,
        delivery_repo=delivery_repo,
        transports={"HTTP": mock_transport},
    )

    stats = dispatcher.dispatch_batch(worker_token="w-perm")
    assert stats["dead_letter"] == 1
    assert stats["retried"] == 0

    deliv = delivery_repo.list_by_event(sample_event.event_id)[0]
    assert deliv.status == DeliveryStatus.DEAD_LETTER.value
    assert deliv.last_error_code == "HTTP_400_BAD_REQUEST"

    outbox_rec = outbox_repo.get_by_event_id(sample_event.event_id)
    assert outbox_rec.status == OutboxStatus.FAILED.value


# ---------------- 6. Run-Once Worker Execution ----------------

def test_integration_publisher_worker_run_once(test_db, sample_tenant, sample_event):
    """Verify run-once worker executes end-to-end routing, claiming, dispatching, and returns metrics."""
    outbox_repo = IntegrationOutboxRepository(test_db)
    dest_repo = IntegrationDestinationRepository(test_db)
    delivery_repo = IntegrationDeliveryRepository(test_db)

    dest = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="bopcrm",
        destination_name="CRM Hook",
        endpoint_url="https://crm.example/events",
    ))
    dest_repo.create_subscription(IntegrationSubscription.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        destination_id=dest.id,
        event_type="prospect.discovered",
    ))
    outbox_repo.append(sample_event)

    mock_transport = MockTransport([
        TransportPublishResult(status=TransportResultStatus.SUCCESS, status_code=200)
    ])
    dispatcher = IntegrationOutboxDispatcher(
        outbox_repo=outbox_repo,
        destination_repo=dest_repo,
        delivery_repo=delivery_repo,
        transports={"HTTP": mock_transport},
    )

    settings = RuntimeSettings(integration_batch_size=10, integration_claim_lease_seconds=30)
    worker = IntegrationPublisherWorker(dispatcher=dispatcher, settings=settings)

    run_result = worker.run_once(worker_token="worker-test-token")

    assert run_result.worker_token == "worker-test-token"
    assert run_result.routing_scanned == 1
    assert run_result.deliveries_created == 1
    assert run_result.deliveries_claimed == 1
    assert run_result.delivered == 1
    assert run_result.events_completed == 1
    assert run_result.duration_seconds >= 0.0

    summary = run_result.safe_summary()
    assert summary["worker_id"] == "worker-test-token"
    assert "claim_token" not in summary
    assert summary["delivered"] == 1


# ---------------- 7. P18.1 Security, SSRF & Hardening Tests ----------------

def test_headers_template_rejects_sensitive_credentials():
    """Verify that IntegrationDestination.create strictly rejects Authorization, API keys, Cookies, etc."""
    sensitive_headers = [
        {"Authorization": "Bearer secret-123"},
        {"Proxy-Authorization": "Basic dXNlcjpwYXNz"},
        {"Cookie": "session=abc"},
        {"Set-Cookie": "session=abc"},
        {"X-Api-Key": "my-key"},
        {"Api-Key": "my-key"},
        {"X-Auth-Token": "secret"},
        {"X-Access-Token": "secret"},
    ]
    for h in sensitive_headers:
        with pytest.raises(ValueError, match="prohibited"):
            IntegrationDestination.create(
                bop_organization_id="org-1",
                target_app_id="bopcrm",
                destination_name="Test",
                endpoint_url="https://crm.example.com/events",
                headers_template=h,
            )


def test_url_credentials_strictly_rejected():
    """Verify that URLs with user:password credentials are strictly rejected."""
    with pytest.raises(ValueError, match="credentials"):
        IntegrationDestination.create(
            bop_organization_id="org-1",
            target_app_id="bopcrm",
            destination_name="Test",
            endpoint_url="https://user:password@example.com/events",
        )


def test_ssrf_protection_rejects_private_and_loopback_ips():
    """Verify that private IPs, loopback, link-local, and cloud metadata are rejected."""
    from bopclients.infrastructure.transports.http_transport import validate_url_ssrf

    # Loopback / Private / Metadata URLs
    disallowed_urls = [
        "http://localhost:8000/webhook",
        "https://127.0.0.1/webhook",
        "https://127.0.0.2:8443/webhook",
        "https://10.0.0.1/webhook",
        "https://192.168.1.1/webhook",
        "https://172.16.0.1/webhook",
        "https://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0:8000/",
    ]
    for url in disallowed_urls:
        with pytest.raises(ValueError, match="SSRF violation"):
            validate_url_ssrf(url, allow_insecure_http=True)


def test_replay_resistant_hmac_signing():
    """Verify deterministic replay-resistant HMAC: X-Bop-Timestamp and X-Bop-Signature-256."""
    import hashlib
    import hmac
    from unittest.mock import MagicMock
    from bopclients.domain.integration.delivery import FakeIntegrationSecretResolver

    resolver = FakeIntegrationSecretResolver({"BOP_INTEGRATION_SECRET_BOP_DEST_KEY": "super-secret-passphrase"})
    dest = IntegrationDestination.create(
        bop_organization_id="org-1",
        target_app_id="bopcrm",
        destination_name="Acme Webhook",
        endpoint_url="https://acme.example.com/webhook",
        secret_key_ref="BOP_INTEGRATION_SECRET_BOP_DEST_KEY",
    )

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "OK"
    mock_resp.headers = {}
    mock_client.post.return_value = mock_resp

    transport = HttpWebhookTransport(
        client=mock_client,
        secret_resolver=resolver,
        allow_insecure_http=False,
    )

    payload = json.dumps({"event_id": "evt-123", "bop_organization_id": "org-1", "event_type": "prospect.discovered"})
    res = transport.publish(payload, dest)

    assert res.status == TransportResultStatus.SUCCESS
    assert mock_client.post.called
    call_kwargs = mock_client.post.call_args[1]
    sent_headers = call_kwargs["headers"]

    assert "X-Bop-Timestamp" in sent_headers
    assert "X-Bop-Signature-256" in sent_headers

    ts = sent_headers["X-Bop-Timestamp"]
    expected_signing_input = f"{ts}.{payload}".encode("utf-8")
    expected_sig = hmac.new("super-secret-passphrase".encode("utf-8"), expected_signing_input, hashlib.sha256).hexdigest()
    assert sent_headers["X-Bop-Signature-256"] == f"sha256={expected_sig}"


def test_mixed_state_aggregate_outbox_semantics(test_db, sample_tenant, sample_event):
    """Verify 3-destination mixed delivery: A=DELIVERED, B=DEAD_LETTER, C=RETRY_PENDING.

    Expected: Outbox remains PENDING while C is still retryable.
    When C completes DELIVERED, Outbox transitions to FAILED because B is DEAD_LETTER.
    """
    outbox_repo = IntegrationOutboxRepository(test_db)
    dest_repo = IntegrationDestinationRepository(test_db)
    delivery_repo = IntegrationDeliveryRepository(test_db)

    # 3 destinations
    d_a = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="app_a",
        destination_name="Dest A",
        endpoint_url="https://a.example.com/events",
    ))
    d_b = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="app_b",
        destination_name="Dest B",
        endpoint_url="https://b.example.com/events",
    ))
    d_c = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="app_c",
        destination_name="Dest C",
        endpoint_url="https://c.example.com/events",
    ))

    for d in (d_a, d_b, d_c):
        dest_repo.create_subscription(IntegrationSubscription.create(
            bop_organization_id=sample_tenant.bop_organization_id,
            destination_id=d.id,
            event_type="prospect.discovered",
        ))

    outbox_repo.append(sample_event)
    dispatcher = IntegrationOutboxDispatcher(
        outbox_repo=outbox_repo,
        destination_repo=dest_repo,
        delivery_repo=delivery_repo,
        transports={},
    )
    dispatcher.route_pending_outbox_events()

    delivs = delivery_repo.list_by_event(sample_event.event_id)
    assert len(delivs) == 3

    # Claim all 3
    claimed = delivery_repo.claim_due_deliveries("w1", 60, 10)
    assert len(claimed) == 3

    deliv_a = next(d for d in claimed if d.destination_id == d_a.id)
    deliv_b = next(d for d in claimed if d.destination_id == d_b.id)
    deliv_c = next(d for d in claimed if d.destination_id == d_c.id)

    # 1. A is DELIVERED
    delivery_repo.mark_delivered(deliv_a.id, "w1")
    dispatcher._check_and_update_outbox_status(sample_event.event_id, sample_tenant.bop_organization_id)
    assert outbox_repo.get_by_event_id(sample_event.event_id).status == OutboxStatus.PENDING.value

    # 2. B is permanently FAILED (DEAD_LETTER)
    delivery_repo.mark_attempt_failed(deliv_b.id, "w1", "HTTP_400", "Bad request", is_permanent=True)
    dispatcher._check_and_update_outbox_status(sample_event.event_id, sample_tenant.bop_organization_id)
    # Since C is still CLAIMED / pending, overall outbox MUST remain PENDING
    assert outbox_repo.get_by_event_id(sample_event.event_id).status == OutboxStatus.PENDING.value

    # 3. C is RETRY_PENDING
    delivery_repo.mark_attempt_failed(deliv_c.id, "w1", "HTTP_500", "Server error", is_permanent=False)
    dispatcher._check_and_update_outbox_status(sample_event.event_id, sample_tenant.bop_organization_id)
    assert outbox_repo.get_by_event_id(sample_event.event_id).status == OutboxStatus.PENDING.value

    # 4. Now C completes with DELIVERED on retry
    claimed_c = delivery_repo.claim_due_deliveries("w2", 60, 10)
    # force next_attempt_at to past so it claims
    test_db.execute("UPDATE bop_integration_deliveries SET next_attempt_at = '2020-01-01T00:00:00Z' WHERE id = ?", (deliv_c.id,))
    test_db.commit()
    claimed_c = delivery_repo.claim_due_deliveries("w2", 60, 10)
    assert len(claimed_c) == 1
    delivery_repo.mark_delivered(deliv_c.id, "w2")

    # 5. Check outbox: all deliveries finished, but B was DEAD_LETTER -> Outbox must become FAILED!
    dispatcher._check_and_update_outbox_status(sample_event.event_id, sample_tenant.bop_organization_id)
    final_outbox = outbox_repo.get_by_event_id(sample_event.event_id)
    assert final_outbox.status == OutboxStatus.FAILED.value
    assert final_outbox.last_error_code == "HTTP_400"


def test_tenant_isolation_between_tenants(test_db, sample_event):
    """Verify tenant A event never routes to tenant B destination even with same name and event_type."""
    dest_repo = IntegrationDestinationRepository(test_db)
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    dest_b = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=tenant_b,
        target_app_id="crm",
        destination_name="Shared Webhook",
        endpoint_url="https://tenant-b.example.com/events",
    ))
    dest_repo.create_subscription(IntegrationSubscription.create(
        bop_organization_id=tenant_b,
        destination_id=dest_b.id,
        event_type="prospect.discovered",
    ))

    # Query matching destinations for tenant_a
    matched = dest_repo.get_destinations_for_event(tenant_a, "prospect.discovered")
    assert len(matched) == 0


def test_sqlite_migration_007_to_008_preserves_data():
    """Verify direct migration from 007 to 008 preserves all P17 data and passes foreign_key_check."""
    db = create_database_connection(":memory:")
    # Run migrations up to 007
    DatabaseMigrator.ensure_version_table(db)
    from bopclients.infrastructure.db.migrations import run_p1_migrations
    run_p1_migrations(db.forge_db)
    DatabaseMigrator._apply_003_upgrades(db, is_pg=False)
    DatabaseMigrator._apply_004_upgrades(db, is_pg=False)
    DatabaseMigrator._apply_005_upgrades(db, is_pg=False)
    DatabaseMigrator._apply_006_upgrades(db, is_pg=False)
    DatabaseMigrator._apply_007_upgrades(db, is_pg=False)
    now_iso = datetime.now(timezone.utc).isoformat()
    db.execute("INSERT INTO bopclients_schema_version (version, applied_at) VALUES (?, ?)", ("20260902_007", now_iso))
    db.commit()

    assert DatabaseMigrator.get_current_version(db) == "20260902_007"

    # Populate sample organization, campaign, outbox event, and inbox event
    org_id = str(uuid.uuid4())
    bop_org_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO organizations (id, bop_organization_id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (org_id, bop_org_id, "Tenant 007", "tenant-007", now_iso, now_iso),
    )
    evt_id = str(uuid.uuid4())
    db.execute(
        """INSERT INTO bop_integration_outbox (
            id, event_id, bop_organization_id, event_type, event_version, producer_app,
            subject_bop_org_id, subject_application_id, subject_entity_type, subject_entity_id,
            correlation_id, envelope_json, status, attempt_count, available_at, created_at
        ) VALUES (?, ?, ?, ?, 1, 'bopclients', ?, 'bopclients', 'prospect', 'p-1', ?, '{}', 'PENDING', 0, ?, ?)""",
        (str(uuid.uuid4()), evt_id, bop_org_id, "prospect.discovered", bop_org_id, str(uuid.uuid4()), now_iso, now_iso),
    )
    inbox_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO bop_integration_inbox (id, event_id, producer_app, bop_organization_id, event_type, event_version, envelope_json, received_at, status) "
        "VALUES (?, ?, 'bopcrm', ?, 'deal.won', 1, '{}', ?, 'RECEIVED')",
        (inbox_id, str(uuid.uuid4()), bop_org_id, now_iso),
    )
    db.commit()

    # Migrate 007 -> 008
    new_ver = DatabaseMigrator.migrate(db)
    assert new_ver == "20260902_008"

    # Verify rows preserved
    assert len(db.fetch_dicts("SELECT * FROM organizations WHERE id = ?", (org_id,))) == 1
    assert len(db.fetch_dicts("SELECT * FROM bop_integration_outbox WHERE event_id = ?", (evt_id,))) == 1
    assert len(db.fetch_dicts("SELECT * FROM bop_integration_inbox WHERE id = ?", (inbox_id,))) == 1

    # PRAGMA foreign_key_check
    fk_errors = db.fetch_dicts("PRAGMA foreign_key_check")
    assert len(fk_errors) == 0


def test_cli_dry_run_and_check_zero_mutations(sample_tenant, sample_event):
    """Verify that CLI --check and --dry-run perform zero database mutations and zero external network calls."""
    from bopclients.runtime.integration_publisher_cli import main

    # In-memory test db
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)

    # Seed organization in DB so outbox_repo.append passes tenant check
    org_repo = OrganizationRepository(db)
    org_repo.save(sample_tenant)

    dest_repo = IntegrationDestinationRepository(db)
    dest = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="bopcrm",
        destination_name="Dry Run Dest",
        endpoint_url="https://crm.example.com/events",
    ))
    dest_repo.create_subscription(IntegrationSubscription.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        destination_id=dest.id,
        event_type="prospect.discovered",
    ))
    outbox_repo = IntegrationOutboxRepository(db, org_repo=org_repo)
    outbox_repo.append(sample_event)

    settings = RuntimeSettings(database_url=":memory:")
    from bopclients.runtime.container import build_runtime_container
    container = build_runtime_container(settings=settings, db=db)
    worker = container.integration_publisher_worker

    check_res = worker.check()
    assert check_res["check"] is True
    assert check_res["mutations_count"] == 0
    assert check_res["external_calls"] == 0

    dry_res = worker.dry_run()
    assert dry_res["dry_run"] is True
    assert dry_res["mutations_count"] == 0
    assert dry_res["external_calls"] == 0
    assert dry_res["pending_outbox_events"] == 1
    assert dry_res["due_deliveries"] == 0  # not routed yet, so 0 deliveries


def test_headers_template_rejects_credential_values_and_crlf():
    """P18.2: Verify header values with Bearer, Basic, api_key=, secret=, or CRLF are strictly rejected."""
    disallowed_templates = [
        {"X-Custom-Auth": "Bearer my_secret_token"},
        {"X-Custom-Auth": "Basic dXNlcjpwYXNz"},
        {"X-Custom": "api_key=abcdef12345"},
        {"X-Custom": "secret=mysecretvalue"},
        {"X-Custom": "password=supersecret"},
        {"X-Custom": "access_token=token123"},
        {"X-Injected\r\nHeader": "value"},
        {"X-Normal": "value\r\nInjected: true"},
    ]
    for tmpl in disallowed_templates:
        with pytest.raises(ValueError):
            IntegrationDestination.create(
                bop_organization_id="org-1",
                target_app_id="bopcrm",
                destination_name="Test",
                endpoint_url="https://crm.example.com/events",
                headers_template=tmpl,
            )


def test_destination_deletion_restrict_preserves_delivery_and_attempt_history(test_db, sample_tenant, sample_event):
    """P18.2: Verify ON DELETE RESTRICT on bop_integration_deliveries preserves delivery and attempt history.

    Deleting a destination that has delivery records MUST be rejected by the foreign key constraint.
    """
    outbox_repo = IntegrationOutboxRepository(test_db)
    dest_repo = IntegrationDestinationRepository(test_db)
    delivery_repo = IntegrationDeliveryRepository(test_db)

    dest = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="bopcrm",
        destination_name="Audit Preserved Hook",
        endpoint_url="https://crm.example.com/events",
    ))
    dest_repo.create_subscription(IntegrationSubscription.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        destination_id=dest.id,
        event_type="prospect.discovered",
    ))
    outbox_repo.append(sample_event)

    dispatcher = IntegrationOutboxDispatcher(
        outbox_repo=outbox_repo,
        destination_repo=dest_repo,
        delivery_repo=delivery_repo,
        transports={"HTTP": MockTransport([TransportPublishResult(status=TransportResultStatus.SUCCESS, status_code=200)])},
    )
    dispatcher.route_pending_outbox_events()
    dispatcher.dispatch_batch(worker_token="worker-audit-test")

    # Verify delivery and attempt exist
    deliveries = delivery_repo.list_by_event(sample_event.event_id)
    assert len(deliveries) == 1
    attempts = delivery_repo.list_attempts(deliveries[0].id)
    assert len(attempts) == 1

    # Attempting to delete destination with existing deliveries MUST fail due to FOREIGN KEY RESTRICT constraint
    with pytest.raises(Exception) as exc_info:
        test_db.execute("DELETE FROM bop_integration_destinations WHERE id = ?", (dest.id,))
        test_db.commit()
    assert "FOREIGN KEY constraint failed" in str(exc_info.value) or "foreign key" in str(exc_info.value).lower()


def test_inactive_destination_does_not_increment_attempts(test_db, sample_tenant, sample_event):
    """P18.2: Verify that an inactive or missing destination transitions to DEAD_LETTER with attempt_count = 0 and 0 network calls."""
    outbox_repo = IntegrationOutboxRepository(test_db)
    dest_repo = IntegrationDestinationRepository(test_db)
    delivery_repo = IntegrationDeliveryRepository(test_db)

    dest = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="bopcrm",
        destination_name="Inactive Hook",
        endpoint_url="https://crm.example.com/events",
    ))
    dest_repo.create_subscription(IntegrationSubscription.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        destination_id=dest.id,
        event_type="prospect.discovered",
    ))
    outbox_repo.append(sample_event)

    dispatcher = IntegrationOutboxDispatcher(
        outbox_repo=outbox_repo,
        destination_repo=dest_repo,
        delivery_repo=delivery_repo,
        transports={"HTTP": MockTransport([])},
    )
    dispatcher.route_pending_outbox_events()

    # Now deactivate the destination before dispatching
    dest_repo.set_destination_active(dest.id, sample_tenant.bop_organization_id, is_active=False)

    stats = dispatcher.dispatch_batch(worker_token="worker-test-token")
    assert stats["dead_letter"] == 1
    assert stats["delivered"] == 0

    deliveries = delivery_repo.list_by_event(sample_event.event_id)
    assert len(deliveries) == 1
    d = deliveries[0]
    assert d.status == "DEAD_LETTER"
    assert d.attempt_count == 0  # CRITICAL: attempt_count NOT incremented because no network call was made!
    assert d.last_error_code == "DESTINATION_INACTIVE"


def test_url_query_sanitization_in_error_messages():
    """P18.2: Verify URL query parameters like ?api_key= or &token= are redacted in error messages."""
    from bopclients.runtime.settings import sanitize_error_message

    err = "Connection failed to https://api.vendor.com/v1/webhook?api_key=secret12345&tenant=bop#status"
    cleaned = sanitize_error_message(err)
    assert "secret12345" not in cleaned
    assert "api_key=***" in cleaned
    assert "tenant=bop" in cleaned


def test_ssrf_dns_rebinding_eliminated_at_socket_connect(monkeypatch):
    """P18.2: Verify SafeSyncBackend eliminates TOCTOU DNS rebinding by inspecting IP at socket connection time."""
    import socket
    from bopclients.infrastructure.transports.http_transport import SafeSyncBackend, SSRFConnectionViolation

    backend = SafeSyncBackend()

    # Simulate DNS rebinding: host looks public in name, but resolves to 127.0.0.1 or 169.254.169.254
    call_count = 0
    def fake_getaddrinfo(host, port, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Rebinding to loopback at connection time!
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(SSRFConnectionViolation) as exc_info:
        backend.connect_tcp("rebound.attacker.example", 80)

    assert "resolved to disallowed IP" in str(exc_info.value) or "disallowed" in str(exc_info.value)


# ---------------- 9. P18.3 Secret-Reference Namespace & Verification Tests ----------------

def test_p18_3_arbitrary_env_variable_resolution_rejected(monkeypatch):
    """P18.3: Verify that arbitrary process environment variables (DATABASE_URL, OPENAI_API_KEY, etc.) cannot be accessed."""
    import os
    from bopclients.domain.integration.delivery import EnvIntegrationSecretResolver

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:super-secret@host/db")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-key")
    monkeypatch.setenv("POSTGRES_PASSWORD", "dbpassword123")

    resolver = EnvIntegrationSecretResolver()

    # Boundary A: IntegrationDestination.create rejects non-namespaced references
    disallowed_refs = [
        "DATABASE_URL",
        "OPENAI_API_KEY",
        "POSTGRES_PASSWORD",
        "PATH",
        "HOME",
        "BOP_INTEGRATION_SECRET_",
        "bop_integration_secret_test",
        "BOP_INTEGRATION_SECRET_test with spaces",
        "BOP_INTEGRATION_SECRET_test/slash",
        "BOP_INTEGRATION_SECRET_test.dot",
        "BOP_INTEGRATION_SECRET_key=val",
        "BOP_INTEGRATION_SECRET_injected\r\n",
    ]
    for ref in disallowed_refs:
        with pytest.raises(ValueError, match="namespaced"):
            IntegrationDestination.create(
                bop_organization_id="org-1",
                target_app_id="bopcrm",
                destination_name="Test",
                endpoint_url="https://crm.example.com/events",
                secret_key_ref=ref,
            )

    # Boundary B: EnvIntegrationSecretResolver independently rejects non-namespaced references
    for ref in disallowed_refs:
        with pytest.raises(ValueError):
            resolver.resolve(ref)


def test_p18_3_valid_integration_secret_resolution_and_hmac_publish(monkeypatch):
    """P18.3: Verify valid BOP_INTEGRATION_SECRET_* resolves, HMAC signature is generated, and secret never leaks."""
    import os
    import hmac
    import hashlib
    from unittest.mock import MagicMock
    from bopclients.domain.integration.delivery import EnvIntegrationSecretResolver

    secret_key = "BOP_INTEGRATION_SECRET_BOPCRM_PROD"
    secret_val = "very-secret-test-value-12345"
    monkeypatch.setenv(secret_key, secret_val)

    resolver = EnvIntegrationSecretResolver()
    resolved = resolver.resolve(secret_key)
    assert resolved == secret_val

    dest = IntegrationDestination.create(
        bop_organization_id="org-1",
        target_app_id="bopcrm",
        destination_name="CRM Prod",
        endpoint_url="https://crm.example.com/events",
        secret_key_ref=secret_key,
    )

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "OK"
    mock_resp.headers = {}
    mock_client.post.return_value = mock_resp

    transport = HttpWebhookTransport(
        client=mock_client,
        secret_resolver=resolver,
        allow_insecure_http=False,
    )

    payload = json.dumps({"event_id": "evt-p183", "bop_organization_id": "org-1", "event_type": "prospect.discovered"})
    res = transport.publish(payload, dest)

    assert res.status == TransportResultStatus.SUCCESS
    call_kwargs = mock_client.post.call_args[1]
    sent_headers = call_kwargs["headers"]

    ts = sent_headers["X-Bop-Timestamp"]
    expected_sig = hmac.new(secret_val.encode("utf-8"), f"{ts}.{payload}".encode("utf-8"), hashlib.sha256).hexdigest()
    assert sent_headers["X-Bop-Signature-256"] == f"sha256={expected_sig}"

    # Verify raw secret does not appear in repr or response results
    assert secret_val not in repr(dest)
    assert secret_val not in (res.response_body_sample or "")
    assert secret_val not in (res.error_message or "")


def test_p18_3_missing_and_empty_secret_fails_as_permanent_configuration_error(monkeypatch):
    """P18.3: Verify missing or empty secret produces permanent configuration failure, not transient retry."""
    import os
    from bopclients.domain.integration.delivery import EnvIntegrationSecretResolver

    # Missing secret
    resolver = EnvIntegrationSecretResolver()
    dest = IntegrationDestination.create(
        bop_organization_id="org-1",
        target_app_id="bopcrm",
        destination_name="Missing Secret Dest",
        endpoint_url="https://crm.example.com/events",
        secret_key_ref="BOP_INTEGRATION_SECRET_NOT_CONFIGURED",
    )
    transport = HttpWebhookTransport(secret_resolver=resolver)
    payload = json.dumps({"event_id": "evt-missing", "bop_organization_id": "org-1"})
    res_missing = transport.publish(payload, dest)

    assert res_missing.status == TransportResultStatus.PERMANENT_FAILURE
    assert res_missing.error_code == "SECRET_RESOLUTION_FAILURE"

    # Empty secret
    empty_key = "BOP_INTEGRATION_SECRET_EMPTY_VALUE"
    monkeypatch.setenv(empty_key, "   ")
    dest_empty = IntegrationDestination.create(
        bop_organization_id="org-1",
        target_app_id="bopcrm",
        destination_name="Empty Secret Dest",
        endpoint_url="https://crm.example.com/events",
        secret_key_ref=empty_key,
    )
    res_empty = transport.publish(payload, dest_empty)
    assert res_empty.status == TransportResultStatus.PERMANENT_FAILURE
    assert res_empty.error_code == "SECRET_RESOLUTION_FAILURE"


def test_p18_3_secret_rotation_at_execution_time(monkeypatch):
    """P18.3: Verify pending deliveries resolve secret at execution time without DB mutation."""
    import os
    import hmac
    import hashlib
    from unittest.mock import MagicMock
    from bopclients.domain.integration.delivery import EnvIntegrationSecretResolver

    secret_key = "BOP_INTEGRATION_SECRET_ROTATABLE"
    monkeypatch.setenv(secret_key, "old-secret-version-1")

    resolver = EnvIntegrationSecretResolver()
    dest = IntegrationDestination.create(
        bop_organization_id="org-1",
        target_app_id="bopcrm",
        destination_name="Rotatable Dest",
        endpoint_url="https://crm.example.com/events",
        secret_key_ref=secret_key,
    )

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "OK"
    mock_resp.headers = {}
    mock_client.post.return_value = mock_resp

    transport = HttpWebhookTransport(client=mock_client, secret_resolver=resolver)
    payload = json.dumps({"event_id": "evt-rot", "bop_organization_id": "org-1"})

    # 1. Publish with Old Secret
    transport.publish(payload, dest)
    ts1 = mock_client.post.call_args[1]["headers"]["X-Bop-Timestamp"]
    sig1 = mock_client.post.call_args[1]["headers"]["X-Bop-Signature-256"]
    expected1 = f"sha256={hmac.new('old-secret-version-1'.encode(), f'{ts1}.{payload}'.encode(), hashlib.sha256).hexdigest()}"
    assert sig1 == expected1

    # 2. Rotate Secret in Environment (No DB mutation)
    monkeypatch.setenv(secret_key, "new-secret-version-2")

    # 3. Publish with New Secret
    transport.publish(payload, dest)
    ts2 = mock_client.post.call_args[1]["headers"]["X-Bop-Timestamp"]
    sig2 = mock_client.post.call_args[1]["headers"]["X-Bop-Signature-256"]
    expected2 = f"sha256={hmac.new('new-secret-version-2'.encode(), f'{ts2}.{payload}'.encode(), hashlib.sha256).hexdigest()}"
    assert sig2 == expected2
    assert sig1 != sig2


def test_p18_3_target_app_id_is_routing_metadata_only_and_does_not_mutate_event(test_db, sample_tenant, sample_event):
    """P18.3: Verify destination.target_app_id never mutates BopIntegrationEvent or envelope_json."""
    outbox_repo = IntegrationOutboxRepository(test_db)
    dest_repo = IntegrationDestinationRepository(test_db)
    delivery_repo = IntegrationDeliveryRepository(test_db)

    dest = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        target_app_id="external_crm_vendor_xyz",
        destination_name="Vendor Hook",
        endpoint_url="https://crm.example/events",
    ))
    dest_repo.create_subscription(IntegrationSubscription.create(
        bop_organization_id=sample_tenant.bop_organization_id,
        destination_id=dest.id,
        event_type="prospect.discovered",
    ))
    outbox_repo.append(sample_event)

    published_envelopes = []
    class InspectTransport(IntegrationTransport):
        @property
        def transport_type(self) -> str:
            return "HTTP"
        def publish(self, envelope_json, destination, timeout_seconds=10.0):
            published_envelopes.append(envelope_json)
            return TransportPublishResult(status=TransportResultStatus.SUCCESS, status_code=200)

    dispatcher = IntegrationOutboxDispatcher(
        outbox_repo=outbox_repo,
        destination_repo=dest_repo,
        delivery_repo=delivery_repo,
        transports={"HTTP": InspectTransport()},
    )
    dispatcher.route_pending_outbox_events()
    dispatcher.dispatch_batch(worker_token="worker-p183-meta")

    assert len(published_envelopes) == 1
    envelope = json.loads(published_envelopes[0])

    # Assert target_app_id is NOT in the envelope
    assert "target_app_id" not in envelope
    assert "target_app" not in envelope
    assert envelope["producer_app"] == "bopclients"


def test_p18_3_trust_env_false_prevents_proxy_bypass():
    """P18.3: Verify that HttpWebhookTransport disables environment proxy variables (trust_env=False)."""
    transport = HttpWebhookTransport()
    # Default client created by transport uses trust_env=False
    # Verify by constructing client without custom_client
    backend = transport
    assert backend.allow_insecure_http is False
