"""
Tests for CRM-I1D.1A: Secure Transport Compatibility in Bop Clients
Covers test requirements A through O plus closure verification tests:
A. Default auth mode is HMAC_SHA256
B. Explicit BEARER auth mode creates destination correctly
C. BEARER sends exact header 'Authorization: Bearer <PAT>'
D. BEARER mode does not calculate or attach HMAC headers
E. Bearer token resolution failure fails safely (SECRET_RESOLUTION_FAILURE)
F. Bearer delivery does not leak token in error messages, logs, or results
G. HMAC transport continues to work identically
H. SSRF blocked targets remain blocked
I. Allowlisted local loopback permitted only when configured and non-prod
J. Allowlisted local loopback blocked in production
K. Multi-tenant isolation: Bearer tokens resolved per-tenant/destination
L. Outbox dispatcher works transparently with BEARER destination
M. Database persistence round-trip preserves auth_mode
N. db_migrator upgrades schema idempotently
O. Invalid auth_mode rejected at domain validation
Closure tests:
- Legacy database upgrade & pre-existing row preservation
- Headers template immutability (cannot spoof Authorization header)
- Local allowlist scope (arbitrary RFC1918 subnets strictly blocked)
"""

import json
import logging
import uuid
from datetime import datetime, timezone
import pytest
from unittest.mock import MagicMock
import httpx

from bopclients.domain.organization import Organization
from bopclients.domain.integration import (
    IntegrationDestination,
    IntegrationSubscription,
    DestinationTransportType,
    DestinationAuthMode,
    TransportResultStatus,
    TransportPublishResult,
    OutboxStatus,
    DeliveryStatus,
    BopIntegrationEvent,
    BopEntityRef,
    LOCAL_APPLICATION_ID,
)
from bopclients.infrastructure.transports.http_transport import (
    HttpWebhookTransport,
    validate_url_ssrf,
    SafeSyncBackend,
)
from bopclients.infrastructure.repositories.organization_repository import (
    OrganizationRepository,
)
from bopclients.infrastructure.repositories.integration_destination_repository import (
    IntegrationDestinationRepository,
)
from bopclients.infrastructure.repositories.integration_outbox_repository import (
    IntegrationOutboxRepository,
)
from bopclients.infrastructure.repositories.integration_delivery_repository import (
    IntegrationDeliveryRepository,
)
from bopclients.application.integration_dispatcher import IntegrationOutboxDispatcher
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.infrastructure.db.connection import create_database_connection


# -------------------------------------------------------------------------
# Test A: Default auth mode is HMAC_SHA256
# -------------------------------------------------------------------------
def test_a_default_auth_mode_is_hmac():
    dest = IntegrationDestination.create(
        bop_organization_id="org_1",
        target_app_id="bopcrm",
        destination_name="CRM Dest",
        endpoint_url="https://example.com/webhook",
        secret_key_ref="BOP_INTEGRATION_SECRET_TEST_1",
    )
    assert dest.auth_mode == DestinationAuthMode.HMAC_SHA256.value


# -------------------------------------------------------------------------
# Test B: Explicit BEARER auth mode creates destination correctly
# -------------------------------------------------------------------------
def test_b_explicit_bearer_auth_mode():
    dest = IntegrationDestination.create(
        bop_organization_id="org_1",
        target_app_id="bopcrm",
        destination_name="CRM Gateway",
        endpoint_url="https://crm.example.com/api/v1/events/gateway/",
        secret_key_ref="BOP_INTEGRATION_SECRET_CRM_PAT",
        auth_mode=DestinationAuthMode.BEARER.value,
    )
    assert dest.auth_mode == DestinationAuthMode.BEARER.value
    assert dest.secret_key_ref == "BOP_INTEGRATION_SECRET_CRM_PAT"


# -------------------------------------------------------------------------
# Test C & D: BEARER sends exact header 'Authorization: Bearer <PAT>'
# and does NOT calculate or attach HMAC headers
# -------------------------------------------------------------------------
def test_c_and_d_bearer_headers():
    sent_requests = []

    def mock_handler(request: httpx.Request):
        sent_requests.append(request)
        return httpx.Response(200, json={"status": "received", "event_id": "evt_123"})

    transport_mock = httpx.MockTransport(mock_handler)
    mock_client = httpx.Client(transport=transport_mock)

    dest = IntegrationDestination.create(
        bop_organization_id="org_1",
        target_app_id="bopcrm",
        destination_name="CRM Gateway",
        endpoint_url="https://crm.example.com/api/v1/events/gateway/",
        secret_key_ref="BOP_INTEGRATION_SECRET_CRM_PAT",
        auth_mode=DestinationAuthMode.BEARER.value,
    )

    payload = json.dumps({"event_id": "evt_1", "prospect_id": "p_1"})

    def resolver(ref: str):
        if ref == "BOP_INTEGRATION_SECRET_CRM_PAT":
            return "pat_secret_value_12345"
        return None

    transport = HttpWebhookTransport(
        client=mock_client,
        secret_resolver=resolver,
    )

    res = transport.publish(payload, dest)
    assert res.status == TransportResultStatus.SUCCESS
    assert len(sent_requests) == 1

    req = sent_requests[0]
    # Header check
    assert req.headers.get("Authorization") == "Bearer pat_secret_value_12345"
    # Ensure NO HMAC signature header present
    assert "X-Bop-Signature-256" not in req.headers


# -------------------------------------------------------------------------
# Test E: Bearer token resolution failure fails safely (SECRET_RESOLUTION_FAILURE)
# -------------------------------------------------------------------------
def test_e_bearer_resolution_failure():
    dest = IntegrationDestination.create(
        bop_organization_id="org_1",
        target_app_id="bopcrm",
        destination_name="CRM Gateway",
        endpoint_url="https://crm.example.com/api/v1/events/gateway/",
        secret_key_ref="BOP_INTEGRATION_SECRET_MISSING",
        auth_mode=DestinationAuthMode.BEARER.value,
    )
    payload = json.dumps({"event_id": "evt_1"})

    def resolver(ref: str):
        return None

    transport = HttpWebhookTransport(
        secret_resolver=resolver,
    )
    res = transport.publish(payload, dest)
    assert res.status == TransportResultStatus.PERMANENT_FAILURE
    assert res.error_code == "SECRET_RESOLUTION_FAILURE"


# -------------------------------------------------------------------------
# Test F: Bearer delivery does not leak token in error messages, logs, or results
# -------------------------------------------------------------------------
def test_f_no_token_leak_on_error(caplog):
    secret_pat = "super_secret_pat_9876543210"

    def mock_error_handler(request: httpx.Request):
        return httpx.Response(500, text="Internal Server Error with failure")

    transport_mock = httpx.MockTransport(mock_error_handler)
    mock_client = httpx.Client(transport=transport_mock)

    dest = IntegrationDestination.create(
        bop_organization_id="org_1",
        target_app_id="bopcrm",
        destination_name="CRM Gateway",
        endpoint_url="https://crm.example.com/api/v1/events/gateway/",
        secret_key_ref="BOP_INTEGRATION_SECRET_CRM_PAT",
        auth_mode=DestinationAuthMode.BEARER.value,
    )
    payload = json.dumps({"event_id": "evt_1"})

    transport = HttpWebhookTransport(
        client=mock_client,
        secret_resolver=lambda ref: secret_pat,
    )

    with caplog.at_level(logging.DEBUG):
        res = transport.publish(payload, dest)

    assert res.status == TransportResultStatus.TRANSIENT_FAILURE
    assert secret_pat not in (res.error_message or "")
    assert secret_pat not in (res.error_code or "")
    assert secret_pat not in (res.response_body_sample or "")
    assert secret_pat not in repr(dest)
    assert secret_pat not in caplog.text


# -------------------------------------------------------------------------
# Test G: HMAC transport continues to work identically
# -------------------------------------------------------------------------
def test_g_hmac_transport_preservation():
    sent_requests = []

    def mock_handler(request: httpx.Request):
        sent_requests.append(request)
        return httpx.Response(200, json={"ok": True})

    transport_mock = httpx.MockTransport(mock_handler)
    mock_client = httpx.Client(transport=transport_mock)

    dest = IntegrationDestination.create(
        bop_organization_id="org_1",
        target_app_id="bopcrm",
        destination_name="Webhook Dest",
        endpoint_url="https://example.com/webhook",
        secret_key_ref="BOP_INTEGRATION_SECRET_HMAC_KEY",
        auth_mode=DestinationAuthMode.HMAC_SHA256.value,
    )
    payload = json.dumps({"foo": "bar"})

    transport = HttpWebhookTransport(
        client=mock_client,
        secret_resolver=lambda ref: "my_hmac_secret_value_123",
    )

    res = transport.publish(payload, dest)
    assert res.status == TransportResultStatus.SUCCESS
    assert len(sent_requests) == 1

    req = sent_requests[0]
    assert "Authorization" not in req.headers
    assert "X-Bop-Signature-256" in req.headers
    assert "X-Bop-Timestamp" in req.headers
    assert req.headers["X-Bop-Signature-256"].startswith("sha256=")


# -------------------------------------------------------------------------
# Test H: SSRF blocked targets remain blocked
# -------------------------------------------------------------------------
def test_h_ssrf_blocked_targets():
    # Cloud metadata (even with allow_insecure_http=True)
    with pytest.raises(ValueError, match="disallowed IP address"):
        validate_url_ssrf("http://169.254.169.254/latest/meta-data/", allow_insecure_http=True)

    # Loopback without allowlist
    with pytest.raises(ValueError, match="loopback"):
        validate_url_ssrf("http://127.0.0.1:8000/api", allow_insecure_http=True)

    # Localhost without allowlist
    with pytest.raises(ValueError, match="loopback"):
        validate_url_ssrf("http://localhost:8000/api", allow_insecure_http=True)


# -------------------------------------------------------------------------
# Test I: Allowlisted local loopback permitted only when configured and non-prod
# -------------------------------------------------------------------------
def test_i_allowlisted_local_loopback():
    allowed = {("127.0.0.1", 8000), ("localhost", 8000)}
    # Loopback matching allowlist must pass validation without raising
    validate_url_ssrf("http://127.0.0.1:8000/api/v1/events/", allowed_local_destinations=allowed)

    # Loopback not matching allowed port must be rejected
    with pytest.raises(ValueError, match="loopback"):
        validate_url_ssrf("http://127.0.0.1:9000/api/v1/events/", allow_insecure_http=True, allowed_local_destinations=allowed)


# -------------------------------------------------------------------------
# Test J: Allowlisted local loopback blocked in production
# -------------------------------------------------------------------------
def test_j_allowlist_blocked_in_production():
    settings = RuntimeSettings(
        environment="production",
        integration_local_destinations_allowlist=["127.0.0.1:8000", "localhost:8000"],
    )
    # The production guard in Settings clears the allowlist
    allowed = settings.parse_allowed_local_destinations()
    assert allowed == set()

    # When allowed is empty and in production, loopback is rejected
    with pytest.raises(ValueError, match="loopback"):
        validate_url_ssrf("http://127.0.0.1:8000/api", allow_insecure_http=True, allowed_local_destinations=allowed)


# -------------------------------------------------------------------------
# Test K: Multi-tenant isolation: Bearer tokens resolved per-tenant/destination
# -------------------------------------------------------------------------
def test_k_multi_tenant_isolation():
    sent_auth = {}

    def mock_handler(request: httpx.Request):
        sent_auth[request.headers.get("X-Target-Org")] = request.headers.get("Authorization")
        return httpx.Response(200, json={"ok": True})

    transport_mock = httpx.MockTransport(mock_handler)
    mock_client = httpx.Client(transport=transport_mock)

    dest_a = IntegrationDestination.create(
        bop_organization_id="tenant_a",
        target_app_id="bopcrm",
        destination_name="CRM Alpha",
        endpoint_url="https://crm.example.com/api/v1/events/gateway/",
        secret_key_ref="BOP_INTEGRATION_SECRET_PAT_TENANT_A",
        auth_mode=DestinationAuthMode.BEARER.value,
        headers_template={"X-Target-Org": "tenant_a"},
    )
    dest_b = IntegrationDestination.create(
        bop_organization_id="tenant_b",
        target_app_id="bopcrm",
        destination_name="CRM Beta",
        endpoint_url="https://crm.example.com/api/v1/events/gateway/",
        secret_key_ref="BOP_INTEGRATION_SECRET_PAT_TENANT_B",
        auth_mode=DestinationAuthMode.BEARER.value,
        headers_template={"X-Target-Org": "tenant_b"},
    )

    secrets = {
        "BOP_INTEGRATION_SECRET_PAT_TENANT_A": "token_for_tenant_a",
        "BOP_INTEGRATION_SECRET_PAT_TENANT_B": "token_for_tenant_b",
    }

    transport = HttpWebhookTransport(
        client=mock_client,
        secret_resolver=lambda ref: secrets.get(ref),
    )

    payload_a = json.dumps({"tenant": "tenant_a"})
    payload_b = json.dumps({"tenant": "tenant_b"})

    transport.publish(payload_a, dest_a)
    transport.publish(payload_b, dest_b)

    assert sent_auth["tenant_a"] == "Bearer token_for_tenant_a"
    assert sent_auth["tenant_b"] == "Bearer token_for_tenant_b"


# -------------------------------------------------------------------------
# Test L: Outbox dispatcher works transparently with BEARER destination
# -------------------------------------------------------------------------
def test_l_outbox_dispatcher_transparent_bearer():
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)

    org_repo = OrganizationRepository(db)
    outbox_repo = IntegrationOutboxRepository(db)
    dest_repo = IntegrationDestinationRepository(db)
    delivery_repo = IntegrationDeliveryRepository(db)

    bop_org_id = str(uuid.uuid4())
    org = Organization(
        id=str(uuid.uuid4()),
        name="Dispatcher Tenant",
        slug=f"tenant-{bop_org_id[:8]}",
        bop_organization_id=bop_org_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )
    org_repo.save(org)

    dest = dest_repo.create_destination(IntegrationDestination.create(
        bop_organization_id=bop_org_id,
        target_app_id="bopcrm",
        destination_name="BopCRM Bearer",
        endpoint_url="https://example.com/crm/gateway",
        secret_key_ref="BOP_INTEGRATION_SECRET_DISPATCHER_PAT",
        auth_mode=DestinationAuthMode.BEARER.value,
    ))

    dest_repo.create_subscription(IntegrationSubscription.create(
        bop_organization_id=bop_org_id,
        destination_id=dest.id,
        event_type="prospect.ready_for_crm",
    ))

    event = BopIntegrationEvent(
        event_id=str(uuid.uuid4()),
        event_type="prospect.ready_for_crm",
        event_version=2,
        occurred_at=datetime.now(timezone.utc).isoformat(),
        producer_app=LOCAL_APPLICATION_ID,
        bop_organization_id=bop_org_id,
        subject=BopEntityRef(
            bop_organization_id=bop_org_id,
            application_id=LOCAL_APPLICATION_ID,
            entity_type="prospect",
            entity_id="p-123",
        ),
        correlation_id=str(uuid.uuid4()),
        payload={"company_name": "Test Co"},
    )
    outbox_repo.append(event)

    sent = []

    def mock_handler(request: httpx.Request):
        sent.append(request)
        return httpx.Response(200, json={"status": "ok"})

    transport_mock = httpx.MockTransport(mock_handler)
    mock_client = httpx.Client(transport=transport_mock)

    transport = HttpWebhookTransport(
        client=mock_client,
        secret_resolver=lambda ref: "secret_pat_from_dispatcher",
    )

    dispatcher = IntegrationOutboxDispatcher(
        outbox_repo=outbox_repo,
        destination_repo=dest_repo,
        delivery_repo=delivery_repo,
        transports={DestinationTransportType.HTTP.value: transport},
    )

    # 1. Route pending outbox
    route_stats = dispatcher.route_pending_outbox_events(bop_organization_id=bop_org_id)
    assert route_stats["deliveries_created"] == 1

    # 2. Dispatch batch
    stats = dispatcher.dispatch_batch(worker_token="worker_test")
    assert stats["delivered"] == 1
    assert stats["dead_letter"] == 0
    assert len(sent) == 1
    assert sent[0].headers.get("Authorization") == "Bearer secret_pat_from_dispatcher"

    # Outbox status should be marked published
    outbox_row = outbox_repo.get_by_event_id(event.event_id)
    assert outbox_row.status == OutboxStatus.PUBLISHED.value


# -------------------------------------------------------------------------
# Test M: Database persistence round-trip preserves auth_mode
# -------------------------------------------------------------------------
def test_m_db_persistence_round_trip():
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)

    repo = IntegrationDestinationRepository(db)

    dest_bearer = repo.create_destination(IntegrationDestination.create(
        bop_organization_id="org_m",
        target_app_id="bopcrm",
        destination_name="Bearer Dest",
        endpoint_url="https://example.com/webhook1",
        secret_key_ref="BOP_INTEGRATION_SECRET_REF1",
        auth_mode=DestinationAuthMode.BEARER.value,
    ))
    dest_hmac = repo.create_destination(IntegrationDestination.create(
        bop_organization_id="org_m",
        target_app_id="bopcrm",
        destination_name="HMAC Dest",
        endpoint_url="https://example.com/webhook2",
        secret_key_ref="BOP_INTEGRATION_SECRET_REF2",
        auth_mode=DestinationAuthMode.HMAC_SHA256.value,
    ))

    loaded_bearer = repo.get_destination(dest_bearer.id, bop_organization_id="org_m")
    loaded_hmac = repo.get_destination(dest_hmac.id, bop_organization_id="org_m")

    assert loaded_bearer is not None
    assert loaded_bearer.auth_mode == DestinationAuthMode.BEARER.value

    assert loaded_hmac is not None
    assert loaded_hmac.auth_mode == DestinationAuthMode.HMAC_SHA256.value


# -------------------------------------------------------------------------
# Test N: db_migrator upgrades schema idempotently
# -------------------------------------------------------------------------
def test_n_db_migrator_idempotent():
    db = create_database_connection(":memory:")
    v1 = DatabaseMigrator.migrate(db)
    assert v1 == DatabaseMigrator.EXPECTED_VERSION

    # Second run must be clean and idempotent
    v2 = DatabaseMigrator.migrate(db)
    assert v2 == DatabaseMigrator.EXPECTED_VERSION

    rows = db.fetch_dicts("PRAGMA table_info(bop_integration_destinations)")
    columns = {row["name"]: row for row in rows}
    assert "auth_mode" in columns
    # Verify default value
    assert "HMAC_SHA256" in str(columns["auth_mode"]["dflt_value"])


# -------------------------------------------------------------------------
# Test O: Invalid auth_mode rejected at domain validation
# -------------------------------------------------------------------------
def test_o_invalid_auth_mode_rejected():
    with pytest.raises(ValueError, match="Invalid auth_mode"):
        IntegrationDestination.create(
            bop_organization_id="org_o",
            target_app_id="bopcrm",
            destination_name="Invalid Auth Dest",
            endpoint_url="https://example.com/webhook",
            secret_key_ref="BOP_INTEGRATION_SECRET_REFO",
            auth_mode="BASIC_AUTH",
        )


# =========================================================================
# CRM-I1D.1A.1 CLOSURE VERIFICATION TESTS
# =========================================================================

def test_closure_migration_upgrade_path_and_legacy_destination_rows():
    """Verify Section 2: auth_mode upgrade on an existing database where version 20260902_011 is recorded.

    Ensures:
    - Pre-existing table without auth_mode is upgraded.
    - Existing destination rows without auth_mode receive HMAC_SHA256 as effective default.
    - Loaded destination from legacy schema has auth_mode='HMAC_SHA256'.
    """
    db = create_database_connection(":memory:")
    DatabaseMigrator.ensure_version_table(db)

    # 1. Create a legacy bop_integration_destinations table WITHOUT auth_mode
    legacy_table_sql = """
        CREATE TABLE bop_integration_destinations (
            id VARCHAR(36) PRIMARY KEY,
            bop_organization_id VARCHAR(36) NOT NULL,
            target_app_id VARCHAR(50) NOT NULL,
            destination_name VARCHAR(100) NOT NULL,
            transport_type VARCHAR(20) NOT NULL DEFAULT 'HTTP',
            endpoint_url VARCHAR(500) NOT NULL,
            secret_key_ref VARCHAR(100),
            headers_template_json TEXT,
            is_active BOOLEAN NOT NULL DEFAULT true,
            created_at VARCHAR(50) NOT NULL,
            updated_at VARCHAR(50) NOT NULL
        );
    """
    db.execute(legacy_table_sql)

    # 2. Insert a pre-existing legacy destination row
    dest_id = str(uuid.uuid4())
    org_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    db.execute(
        """
        INSERT INTO bop_integration_destinations (
            id, bop_organization_id, target_app_id, destination_name,
            transport_type, endpoint_url, secret_key_ref, headers_template_json,
            is_active, created_at, updated_at
        ) VALUES (?, ?, 'bopcrm', 'Legacy HMAC Dest', 'HTTP', 'https://example.com/legacy', 'BOP_INTEGRATION_SECRET_LEGACY', NULL, 1, ?, ?)
        """,
        (dest_id, org_id, now_iso, now_iso),
    )

    # 3. Simulate an installation that already has schema version 20260902_011 recorded
    db.execute(
        "INSERT INTO bopclients_schema_version (version, applied_at) VALUES (?, ?)",
        (DatabaseMigrator.EXPECTED_VERSION, now_iso),
    )
    db.commit()

    # Verify column auth_mode does not exist yet
    cols_before = {r["name"] for r in db.fetch_dicts("PRAGMA table_info(bop_integration_destinations)")}
    assert "auth_mode" not in cols_before

    # 4. Run DatabaseMigrator.migrate(db) to execute upgrade reconciliation
    version_result = DatabaseMigrator.migrate(db)
    assert version_result == DatabaseMigrator.EXPECTED_VERSION

    # Verify column auth_mode was added with default HMAC_SHA256
    pragma_rows = db.fetch_dicts("PRAGMA table_info(bop_integration_destinations)")
    cols_after = {r["name"]: r for r in pragma_rows}
    assert "auth_mode" in cols_after
    assert "HMAC_SHA256" in str(cols_after["auth_mode"]["dflt_value"])

    # 5. Load the legacy row through IntegrationDestinationRepository
    repo = IntegrationDestinationRepository(db)
    loaded_legacy = repo.get_destination(dest_id, bop_organization_id=org_id)
    assert loaded_legacy is not None
    assert loaded_legacy.auth_mode == DestinationAuthMode.HMAC_SHA256.value
    assert loaded_legacy.destination_name == "Legacy HMAC Dest"


def test_closure_header_template_cannot_override_authorization():
    """Verify Section 4: Destination headers_template_json cannot override Authorization header in BEARER mode."""
    sent_requests = []

    def mock_handler(request: httpx.Request):
        sent_requests.append(request)
        return httpx.Response(200, json={"status": "received"})

    transport_mock = httpx.MockTransport(mock_handler)
    mock_client = httpx.Client(transport=transport_mock)

    # Attempt to inject custom authorization header via headers_template
    # Note: destination.create rejects sensitive headers directly in template validation,
    # but even if an unvalidated template reached the transport, the transport explicitly drops 'authorization'.
    dest = IntegrationDestination(
        id=str(uuid.uuid4()),
        bop_organization_id="tenant_override_test",
        target_app_id="bopcrm",
        destination_name="Override Dest",
        transport_type=DestinationTransportType.HTTP.value,
        endpoint_url="https://crm.example.com/api/v1/events/gateway/",
        secret_key_ref="BOP_INTEGRATION_SECRET_REAL_PAT",
        headers_template_json=json.dumps({
            "Authorization": "Bearer MALICIOUS_INJECTED_OVERRIDE",
            "authorization": "Bearer MALICIOUS_LOWER",
            "X-Custom-Header": "AllowedCustomVal",
        }),
        is_active=True,
        created_at=datetime.now(timezone.utc).isoformat(),
        updated_at=datetime.now(timezone.utc).isoformat(),
        auth_mode=DestinationAuthMode.BEARER.value,
    )

    payload = json.dumps({"event_id": "evt_override"})

    transport = HttpWebhookTransport(
        client=mock_client,
        secret_resolver=lambda ref: "AUTHENTIC_PAT_VALUE",
    )

    res = transport.publish(payload, dest)
    assert res.status == TransportResultStatus.SUCCESS
    assert len(sent_requests) == 1

    req = sent_requests[0]
    # Injected authorization headers must be discarded in favor of authentic resolved secret
    assert req.headers.get("Authorization") == "Bearer AUTHENTIC_PAT_VALUE"
    assert req.headers.get("X-Custom-Header") == "AllowedCustomVal"


def test_closure_ssrf_scope_rejects_arbitrary_rfc1918_private_ips():
    """Verify Section 5: Local allowlist exception is constrained to configured host:port.

    Arbitrary RFC1918 private subnets (10.x.x.x, 172.16-31.x.x, 192.168.x.x) remain blocked.
    """
    # Configure allowlist ONLY for specific loopback port
    allowed = {("127.0.0.1", 8000)}

    # Permitted loopback target
    validate_url_ssrf("http://127.0.0.1:8000/api", allowed_local_destinations=allowed)

    # Prohibited arbitrary private targets (RFC1918)
    with pytest.raises(ValueError, match="disallowed IP address"):
        validate_url_ssrf("http://10.0.0.1:8000/api", allowed_local_destinations=allowed, allow_insecure_http=True)

    with pytest.raises(ValueError, match="disallowed IP address"):
        validate_url_ssrf("http://192.168.1.50:8000/api", allowed_local_destinations=allowed, allow_insecure_http=True)

    with pytest.raises(ValueError, match="disallowed IP address"):
        validate_url_ssrf("http://172.16.0.1:8000/api", allowed_local_destinations=allowed, allow_insecure_http=True)
