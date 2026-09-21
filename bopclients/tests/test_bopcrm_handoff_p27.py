"""Targeted tests for Phase P27: Bop CRM Handoff & Cross-App Integration Foundation."""

import pytest
import uuid
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.domain.enums import MemberRole
from bopclients.domain.prospect import Prospect
from bopclients.domain.prospect_priority import ProspectPriority
from bopclients.domain.integration.destination import (
    IntegrationDestination,
    IntegrationSubscription,
)
from bopclients.domain.integration.delivery import DeliveryStatus
from bopclients.domain.integration.registry import BopEventRegistry
from bopclients.domain.integration.exceptions import InvalidIntegrationEvent
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.container import build_runtime_container
from bopclients.api.app import create_bopclients_api_app


@pytest.fixture
def crm_ctx():
    """Builds an isolated test environment with two organizations, roles, and repositories."""
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)

    settings = RuntimeSettings(
        database_url="sqlite:///:memory:",
        auth_signing_key="p27-crm-handoff-test-secret-key-min-32-chars!",
        auth_token_expire_seconds=3600,
    )
    container = build_runtime_container(settings=settings, db=db)
    app = create_bopclients_api_app(container=container, settings=settings)
    client = TestClient(app)

    # 1. Organization A
    org_a = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Tenant Alpha",
        slug="tenant-alpha",
    )
    container.org_repo.save(org_a)

    # 2. Organization B
    org_b = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Tenant Beta",
        slug="tenant-beta",
    )
    container.org_repo.save(org_b)

    # 3. Users in Org A: Admin, Member, Viewer
    admin_user = container.auth_service.register_user(
        email="admin@alpha.com",
        name="Admin Alice",
        password="Password123!",
        locale="en",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=admin_user.id,
            role=MemberRole.ADMIN,
        )
    )

    member_user = container.auth_service.register_user(
        email="member@alpha.com",
        name="Member Bob",
        password="Password123!",
        locale="en",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=member_user.id,
            role=MemberRole.MEMBER,
        )
    )

    viewer_user = container.auth_service.register_user(
        email="viewer@alpha.com",
        name="Viewer Charlie",
        password="Password123!",
        locale="en",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=viewer_user.id,
            role=MemberRole.VIEWER,
        )
    )

    # 4. Prospects in Org A & Org B
    prospect_a = Prospect(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Solaris Energy Corp",
        website_url="https://solaris-energy.example.com",
        city="Denver",
        state="CO",
        country="USA",
        industry="Clean Energy",
        source="discovery",
    )
    container.prospect_repo.save_prospect(org_a.id, prospect_a)

    from bopclients.domain.campaign import Campaign

    campaign = Campaign(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Alpha Q1 Outreach",
    )
    container.campaign_repo.save(org_a.id, campaign)

    container.priority_repo.save(
        org_a.id,
        ProspectPriority(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            campaign_id=campaign.id,
            prospect_id=prospect_a.id,
            priority_score=88,
            priority_label="high",
        ),
    )

    prospect_b = Prospect(
        id=str(uuid.uuid4()),
        organization_id=org_b.id,
        name="Beta Holdings Inc",
        website_url="https://beta-holdings.example.com",
        city="Austin",
        state="TX",
        country="USA",
        industry="Logistics",
        source="outreach",
    )
    container.prospect_repo.save_prospect(org_b.id, prospect_b)

    def login(email: str, bop_org_id: str):
        res = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "Password123!"},
            headers={"X-Bop-Organization-Id": bop_org_id},
        )
        token = res.json()["access_token"]
        return {"Authorization": f"Bearer {token}", "X-Bop-Organization-Id": bop_org_id}

    return {
        "client": client,
        "container": container,
        "org_a": org_a,
        "org_b": org_b,
        "admin_headers": login("admin@alpha.com", org_a.bop_organization_id),
        "member_headers": login("member@alpha.com", org_a.bop_organization_id),
        "viewer_headers": login("viewer@alpha.com", org_a.bop_organization_id),
        "prospect_a": prospect_a,
        "prospect_b": prospect_b,
    }


def _seed_crm_destination(container, bop_org_id: str) -> IntegrationDestination:
    """Helper to register an active Bop CRM destination and subscription."""
    dest = IntegrationDestination.create(
        bop_organization_id=bop_org_id,
        target_app_id="bopcrm",
        destination_name="Production Bop CRM Webhook",
        endpoint_url="https://crm.bopagenciy.internal/webhooks/handoff",
    )
    container.destination_repo.create_destination(dest)

    sub = IntegrationSubscription.create(
        bop_organization_id=bop_org_id,
        destination_id=dest.id,
        event_type="prospect.ready_for_crm",
    )
    container.destination_repo.create_subscription(sub)
    return dest


class TestBopCrmHandoffP27:

    def test_crm_destination_not_configured_returns_409(self, crm_ctx):
        """When no destination is configured for prospect.ready_for_crm, return 409."""
        client = crm_ctx["client"]
        headers = crm_ctx["admin_headers"]
        prospect_a = crm_ctx["prospect_a"]

        res = client.post(
            f"/api/v1/prospects/{prospect_a.id}/crm-handoff",
            headers=headers,
        )
        assert res.status_code == 409
        body = res.json()
        assert body["error"]["code"] == "CRM_DESTINATION_NOT_CONFIGURED"

    def test_crm_handoff_success_emits_v2_event_and_enqueues_outbox(self, crm_ctx):
        """When destination is configured, handoff creates outbox event v2 and delivery row."""
        client = crm_ctx["client"]
        container = crm_ctx["container"]
        headers = crm_ctx["admin_headers"]
        prospect_a = crm_ctx["prospect_a"]
        org_a = crm_ctx["org_a"]

        dest = _seed_crm_destination(container, org_a.bop_organization_id)

        res = client.post(
            f"/api/v1/prospects/{prospect_a.id}/crm-handoff",
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["prospect_id"] == prospect_a.id
        assert data["status"] == "QUEUED"
        assert data["destination_count"] == 1
        assert data["is_idempotent_replay"] is False
        event_id = data["event_id"]

        # Verify Outbox record
        outbox_rec = container.outbox_repo.get_by_event_id(event_id, bop_organization_id=org_a.bop_organization_id)
        assert outbox_rec is not None
        assert outbox_rec.event_type == "prospect.ready_for_crm"
        assert outbox_rec.event_version == 2
        assert outbox_rec.subject_entity_id == prospect_a.id
        assert outbox_rec.status == "PENDING"

        # Verify event envelope payload
        event = container.outbox_repo.get_event(event_id, bop_organization_id=org_a.bop_organization_id)
        assert event is not None
        assert event.bop_organization_id == org_a.bop_organization_id
        payload = event.payload
        assert payload["company_name"] == "Solaris Energy Corp"
        assert payload["lead_score"] == 88
        assert payload["priority"] == "HIGH"
        assert payload["location"] == "Denver, CO, USA"
        assert payload["website"] == "https://solaris-energy.example.com"
        assert payload["industry"] == "Clean Energy"

        # Verify Delivery record
        deliveries = container.delivery_repo.list_by_event(event_id)
        assert len(deliveries) == 1
        assert deliveries[0].destination_id == dest.id
        assert deliveries[0].status == DeliveryStatus.PENDING.value

    def test_crm_handoff_deterministic_idempotency(self, crm_ctx):
        """Repeated handoff calls for the same prospect return is_idempotent_replay: True."""
        client = crm_ctx["client"]
        container = crm_ctx["container"]
        headers = crm_ctx["admin_headers"]
        prospect_a = crm_ctx["prospect_a"]
        org_a = crm_ctx["org_a"]

        _seed_crm_destination(container, org_a.bop_organization_id)

        # 1st call
        res1 = client.post(f"/api/v1/prospects/{prospect_a.id}/crm-handoff", headers=headers)
        assert res1.status_code == 200
        assert res1.json()["is_idempotent_replay"] is False
        event_id_1 = res1.json()["event_id"]

        # 2nd call
        res2 = client.post(f"/api/v1/prospects/{prospect_a.id}/crm-handoff", headers=headers)
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["is_idempotent_replay"] is True
        assert data2["event_id"] == event_id_1

        # Verify only 1 record exists in outbox
        outbox_pending = container.outbox_repo.list_pending(limit=10, bop_organization_id=org_a.bop_organization_id)
        assert len(outbox_pending) == 1

    def test_crm_handoff_tenant_isolation_prevents_cross_tenant_access(self, crm_ctx):
        """Cannot hand off prospect from Org B while authenticated in Org A."""
        client = crm_ctx["client"]
        container = crm_ctx["container"]
        headers_a = crm_ctx["admin_headers"]
        prospect_b = crm_ctx["prospect_b"]
        org_a = crm_ctx["org_a"]

        _seed_crm_destination(container, org_a.bop_organization_id)

        res = client.post(
            f"/api/v1/prospects/{prospect_b.id}/crm-handoff",
            headers=headers_a,
        )
        assert res.status_code == 404

    def test_crm_handoff_rbac(self, crm_ctx):
        """VIEWER gets 403 on POST handoff, but 200 on GET status. MEMBER gets 200."""
        client = crm_ctx["client"]
        container = crm_ctx["container"]
        viewer_headers = crm_ctx["viewer_headers"]
        member_headers = crm_ctx["member_headers"]
        prospect_a = crm_ctx["prospect_a"]
        org_a = crm_ctx["org_a"]

        _seed_crm_destination(container, org_a.bop_organization_id)

        # 1. Viewer cannot trigger handoff (403)
        res_viewer = client.post(
            f"/api/v1/prospects/{prospect_a.id}/crm-handoff",
            headers=viewer_headers,
        )
        assert res_viewer.status_code == 403

        # 2. Viewer can query handoff status (200)
        res_status = client.get(
            f"/api/v1/prospects/{prospect_a.id}/crm-handoff",
            headers=viewer_headers,
        )
        assert res_status.status_code == 200
        assert res_status.json()["status"] == "NOT_SENT"

        # 3. Member can trigger handoff (200)
        res_member = client.post(
            f"/api/v1/prospects/{prospect_a.id}/crm-handoff",
            headers=member_headers,
        )
        assert res_member.status_code == 200
        assert res_member.json()["status"] == "QUEUED"

    def test_crm_handoff_status_lifecycle(self, crm_ctx):
        """GET /crm-handoff reflects truthful lifecycle: NOT_SENT -> QUEUED -> DELIVERED."""
        client = crm_ctx["client"]
        container = crm_ctx["container"]
        headers = crm_ctx["admin_headers"]
        prospect_a = crm_ctx["prospect_a"]
        org_a = crm_ctx["org_a"]

        _seed_crm_destination(container, org_a.bop_organization_id)

        # 1. Before handoff: NOT_SENT
        s0 = client.get(f"/api/v1/prospects/{prospect_a.id}/crm-handoff", headers=headers).json()
        assert s0["status"] == "NOT_SENT"

        # 2. After handoff: QUEUED
        client.post(f"/api/v1/prospects/{prospect_a.id}/crm-handoff", headers=headers)
        s1 = client.get(f"/api/v1/prospects/{prospect_a.id}/crm-handoff", headers=headers).json()
        assert s1["status"] == "QUEUED"
        assert s1["event_id"] is not None

        # 3. Simulate successful delivery
        event_id = s1["event_id"]
        deliveries = container.delivery_repo.list_by_event(event_id)
        assert len(deliveries) == 1
        d = deliveries[0]

        now_iso = datetime.now(timezone.utc).isoformat()
        container.db.execute(
            f"UPDATE bop_integration_deliveries SET status = 'DELIVERED', delivered_at = {container.destination_repo._placeholder()} WHERE id = {container.destination_repo._placeholder()}",
            (now_iso, d.id),
        )
        container.outbox_repo.mark_published(event_id=event_id, bop_organization_id=org_a.bop_organization_id)

        s2 = client.get(f"/api/v1/prospects/{prospect_a.id}/crm-handoff", headers=headers).json()
        assert s2["status"] == "DELIVERED"
        assert s2["delivered_at"] is not None

    def test_bulk_crm_handoff(self, crm_ctx):
        """Bulk CRM handoff queues multiple prospects with summary metrics."""
        client = crm_ctx["client"]
        container = crm_ctx["container"]
        headers = crm_ctx["admin_headers"]
        prospect_a = crm_ctx["prospect_a"]
        org_a = crm_ctx["org_a"]

        # Create another prospect in Org A
        prospect_a2 = Prospect(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            name="Lunar Aerospace",
        )
        container.prospect_repo.save_prospect(org_a.id, prospect_a2)

        _seed_crm_destination(container, org_a.bop_organization_id)

        res = client.post(
            "/api/v1/prospects/bulk/crm-handoff",
            json={"prospect_ids": [prospect_a.id, prospect_a2.id]},
            headers=headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["requested"] == 2
        assert data["queued"] == 2
        assert data["already_queued_or_delivered"] == 0

        # Repeating the bulk handoff flags them as already queued
        res2 = client.post(
            "/api/v1/prospects/bulk/crm-handoff",
            json={"prospect_ids": [prospect_a.id, prospect_a2.id]},
            headers=headers,
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["requested"] == 2
        assert data2["queued"] == 0
        assert data2["already_queued_or_delivered"] == 2

    def test_payload_validator_v1_and_v2_compatibility(self):
        """BopEventRegistry maintains strict v1 zero-PII check while permitting v2 handoff schema."""
        # 1. v1 valid
        v1_payload = {
            "prospect_id": "p-1",
            "lead_score": 90,
            "priority": "HIGH",
            "recommended_action": "review",
            "human_review_required": False,
        }
        BopEventRegistry.validate_event_payload("prospect.ready_for_crm", 1, v1_payload)

        # 2. v1 rejects extra business fields
        with pytest.raises(InvalidIntegrationEvent):
            BopEventRegistry.validate_event_payload(
                "prospect.ready_for_crm",
                1,
                {**v1_payload, "company_name": "Acme Inc"},
            )

        # 3. v2 accepts rich business handoff fields
        v2_payload = {
            "prospect_id": "p-1",
            "company_name": "Acme Inc",
            "website": "https://acme.com",
            "industry": "Manufacturing",
            "location": "Dallas, TX",
            "lead_score": 90,
            "priority": "HIGH",
            "source": "manual",
            "prospect_url": "/prospects/p-1",
            "recommended_action": "handoff_to_crm",
            "human_review_required": False,
        }
        BopEventRegistry.validate_event_payload("prospect.ready_for_crm", 2, v2_payload)

        # 4. v2 rejects unauthorized keys
        with pytest.raises(InvalidIntegrationEvent):
            BopEventRegistry.validate_event_payload(
                "prospect.ready_for_crm",
                2,
                {**v2_payload, "unauthorized_secret": "xyz"},
            )

    def test_destination_matching_unrelated_event_or_inactive_subscription_returns_409(self, crm_ctx):
        """Unrelated event type or inactive subscription raises 409 CRM_DESTINATION_NOT_CONFIGURED."""
        client = crm_ctx["client"]
        container = crm_ctx["container"]
        headers = crm_ctx["admin_headers"]
        prospect_a = crm_ctx["prospect_a"]
        org_a = crm_ctx["org_a"]

        # 1. Destination exists, but subscribed only to another event
        dest = IntegrationDestination.create(
            bop_organization_id=org_a.bop_organization_id,
            target_app_id="other_app",
            destination_name="Unrelated Webhook",
            endpoint_url="https://other.example.com/webhook",
        )
        container.destination_repo.create_destination(dest)
        sub = IntegrationSubscription.create(
            bop_organization_id=org_a.bop_organization_id,
            destination_id=dest.id,
            event_type="buying_intent.detected",
        )
        container.destination_repo.create_subscription(sub)

        res1 = client.post(f"/api/v1/prospects/{prospect_a.id}/crm-handoff", headers=headers)
        assert res1.status_code == 409
        assert res1.json()["error"]["code"] == "CRM_DESTINATION_NOT_CONFIGURED"

        # 2. Add subscription to prospect.ready_for_crm but disabled
        sub_disabled = IntegrationSubscription.create(
            bop_organization_id=org_a.bop_organization_id,
            destination_id=dest.id,
            event_type="prospect.ready_for_crm",
            is_active=False,
        )
        container.destination_repo.create_subscription(sub_disabled)

        res2 = client.post(f"/api/v1/prospects/{prospect_a.id}/crm-handoff", headers=headers)
        assert res2.status_code == 409
        assert res2.json()["error"]["code"] == "CRM_DESTINATION_NOT_CONFIGURED"

        # 3. Add wildcard subscription '*' -> now works
        sub_wildcard = IntegrationSubscription.create(
            bop_organization_id=org_a.bop_organization_id,
            destination_id=dest.id,
            event_type="*",
            is_active=True,
        )
        container.destination_repo.create_subscription(sub_wildcard)

        res3 = client.post(f"/api/v1/prospects/{prospect_a.id}/crm-handoff", headers=headers)
        assert res3.status_code == 200
        assert res3.json()["status"] == "QUEUED"

    def test_bulk_crm_handoff_limits_and_mixed_tenant_security(self, crm_ctx):
        """Bulk limit >50 rejected with 422, VIEWER rejected with 403, foreign prospect rejected in errors dict."""
        client = crm_ctx["client"]
        container = crm_ctx["container"]
        admin_headers = crm_ctx["admin_headers"]
        viewer_headers = crm_ctx["viewer_headers"]
        prospect_a = crm_ctx["prospect_a"]
        prospect_b = crm_ctx["prospect_b"]
        org_a = crm_ctx["org_a"]

        _seed_crm_destination(container, org_a.bop_organization_id)

        # 1. > 50 prospects rejected by schema validation (422)
        excess_ids = [str(uuid.uuid4()) for _ in range(51)]
        res_limit = client.post(
            "/api/v1/prospects/bulk/crm-handoff",
            json={"prospect_ids": excess_ids},
            headers=admin_headers,
        )
        assert res_limit.status_code == 422

        # 2. Viewer cannot trigger bulk handoff (403)
        res_viewer = client.post(
            "/api/v1/prospects/bulk/crm-handoff",
            json={"prospect_ids": [prospect_a.id]},
            headers=viewer_headers,
        )
        assert res_viewer.status_code == 403

        # 3. Mixed-tenant bulk handoff: prospect_a is Org A, prospect_b is Org B
        res_mixed = client.post(
            "/api/v1/prospects/bulk/crm-handoff",
            json={"prospect_ids": [prospect_a.id, prospect_b.id]},
            headers=admin_headers,
        )
        assert res_mixed.status_code == 200
        data = res_mixed.json()
        assert data["requested"] == 2
        assert data["queued"] == 1
        assert data["failed"] == 1
        assert prospect_b.id in data["errors"]

    def test_transport_transient_retry_preserves_event_and_updates_status(self, crm_ctx):
        """When transport fails transiently, attempt is recorded, event is preserved, status is DELIVERING."""
        from bopclients.domain.integration.transport import IntegrationTransport, TransportPublishResult
        from bopclients.domain.integration.delivery import TransportResultStatus
        from bopclients.application.integration_dispatcher import IntegrationOutboxDispatcher

        class MockFailingTransport(IntegrationTransport):
            @property
            def transport_type(self) -> str:
                return "HTTP"
            def publish(self, envelope_json: str, destination, timeout_seconds: float = 10.0) -> TransportPublishResult:
                return TransportPublishResult(
                    status=TransportResultStatus.TRANSIENT_FAILURE,
                    status_code=500,
                    error_code="SERVER_ERROR",
                    error_message="HTTP 500 Internal Server Error",
                    retry_after_seconds=30,
                )

        client = crm_ctx["client"]
        container = crm_ctx["container"]
        headers = crm_ctx["admin_headers"]
        prospect_a = crm_ctx["prospect_a"]
        org_a = crm_ctx["org_a"]

        _seed_crm_destination(container, org_a.bop_organization_id)

        # 1. Trigger handoff
        res = client.post(f"/api/v1/prospects/{prospect_a.id}/crm-handoff", headers=headers)
        assert res.status_code == 200
        event_id = res.json()["event_id"]

        # 2. Dispatch batch with failing transport
        dispatcher = IntegrationOutboxDispatcher(
            outbox_repo=container.outbox_repo,
            destination_repo=container.destination_repo,
            delivery_repo=container.delivery_repo,
            transports={"HTTP": MockFailingTransport()},
        )
        dispatch_res = dispatcher.dispatch_batch(worker_token="worker-1", batch_size=10)
        assert dispatch_res["retried"] == 1
        assert dispatch_res["delivered"] == 0

        # 3. Verify delivery state transitioned to RETRY_PENDING
        deliveries = container.delivery_repo.list_by_event(event_id)
        assert len(deliveries) == 1
        d = deliveries[0]
        assert d.status == DeliveryStatus.RETRY_PENDING.value
        assert d.attempt_count == 1
        assert d.last_error_code == "SERVER_ERROR"

        # 4. Verify attempt was recorded
        attempts = container.delivery_repo.list_attempts(d.id)
        assert len(attempts) == 1
        assert attempts[0].status == TransportResultStatus.TRANSIENT_FAILURE.value
        assert attempts[0].status_code == 500

        # 5. Verify parent outbox record still exists, status is PENDING, envelope unchanged
        outbox = container.outbox_repo.get_by_event_id(event_id, bop_organization_id=org_a.bop_organization_id)
        assert outbox is not None
        assert outbox.status == "PENDING"

        # 6. Verify client status is DELIVERING
        status_res = client.get(f"/api/v1/prospects/{prospect_a.id}/crm-handoff", headers=headers).json()
        assert status_res["status"] == "DELIVERING"
        assert status_res["attempt_count"] == 1
        assert "500 Internal Server Error" in status_res["last_error_message"]


def test_p28_prospect_detail_regression(crm_ctx):
    """Proves P28.3 Prospect Detail fix:
    A. Prospect with intelligence returns HTTP 200.
    B. Prospect without intelligence returns HTTP 200.
    C. Existing response schema remains compatible.
    D. CRM handoff status remains accessible.
    E. Cross-tenant prospect remains inaccessible (HTTP 404).
    """
    client = crm_ctx["client"]
    container = crm_ctx["container"]
    org_a = crm_ctx["org_a"]
    headers_a = crm_ctx["admin_headers"]
    prospect_a = crm_ctx["prospect_a"]
    prospect_b = crm_ctx["prospect_b"]

    # B. Prospect WITHOUT intelligence
    res_no_intel = client.get(f"/api/v1/prospects/{prospect_a.id}", headers=headers_a)
    assert res_no_intel.status_code == 200
    data_no_intel = res_no_intel.json()

    # C. Existing response schema remains compatible
    assert "prospect" in data_no_intel
    assert data_no_intel["prospect"]["id"] == prospect_a.id
    assert "campaign_associations" in data_no_intel
    assert "lead_score" in data_no_intel
    assert "priority" in data_no_intel
    assert "recent_signals" in data_no_intel
    assert "monitoring_schedule" in data_no_intel
    assert data_no_intel.get("intelligence_summary") is None

    # D. CRM handoff status remains accessible
    _seed_crm_destination(container, org_a.bop_organization_id)
    res_crm_status = client.get(f"/api/v1/prospects/{prospect_a.id}/crm-handoff", headers=headers_a)
    assert res_crm_status.status_code == 200
    assert res_crm_status.json()["status"] == "NOT_SENT"

    # A. Prospect WITH intelligence
    from bopclients.domain.prospect_intelligence import ProspectIntelligence
    intel_entity = ProspectIntelligence(
        organization_id=org_a.id,
        prospect_id=prospect_a.id,
        provider="deterministic",
        research_version="v1.0",
        confidence=0.95,
        data={
            "summary_text": "High-growth solar manufacturer expanding supply chain.",
            "key_insights": ["Expanding production lines", "Procuring industrial supplies"],
            "recommended_angle": "Pitch bulk supply volume discounts",
        },
    )
    container.intel_repo.save(org_a.id, intel_entity)

    res_with_intel = client.get(f"/api/v1/prospects/{prospect_a.id}", headers=headers_a)
    assert res_with_intel.status_code == 200
    data_with_intel = res_with_intel.json()
    assert data_with_intel["intelligence_summary"] is not None
    assert data_with_intel["intelligence_summary"]["summary_text"] == "High-growth solar manufacturer expanding supply chain."
    assert "Expanding production lines" in data_with_intel["intelligence_summary"]["key_insights"]
    assert data_with_intel["intelligence_summary"]["recommended_angle"] == "Pitch bulk supply volume discounts"

    # E. Cross-tenant prospect remains inaccessible
    res_cross = client.get(f"/api/v1/prospects/{prospect_b.id}", headers=headers_a)
    assert res_cross.status_code == 404


class TestP28CanonicalProspectUrl:
    """Targeted tests for Phase P28.5 Canonical Prospect URL & Reverse Navigation."""

    def test_a_local_public_web_url_produces_correct_nextjs_url(self, crm_ctx):
        """A. Local public web URL produces the correct Next.js prospect URL."""
        from bopclients.application.crm_handoff_service import (
            validate_web_public_url,
            build_canonical_prospect_url,
        )
        client = crm_ctx["client"]
        container = crm_ctx["container"]
        headers = crm_ctx["admin_headers"]
        prospect_a = crm_ctx["prospect_a"]
        org_a = crm_ctx["org_a"]

        _seed_crm_destination(container, org_a.bop_organization_id)

        res = client.post(
            f"/api/v1/prospects/{prospect_a.id}/crm-handoff",
            headers=headers,
        )
        assert res.status_code == 200
        event_id = res.json()["event_id"]

        event = container.outbox_repo.get_event(event_id, bop_organization_id=org_a.bop_organization_id)
        assert event is not None
        prospect_url = event.payload.get("prospect_url")
        assert prospect_url == f"http://localhost:3011/en/prospects/{prospect_a.id}"

        # Also verify direct builder
        built = build_canonical_prospect_url("http://localhost:3011", prospect_a.id, "en")
        assert built == f"http://localhost:3011/en/prospects/{prospect_a.id}"

    def test_b_api_origin_never_leaks_into_prospect_url(self, crm_ctx):
        """B. API origin never leaks into prospect_url."""
        from bopclients.application.crm_handoff_service import (
            validate_web_public_url,
            build_canonical_prospect_url,
        )
        # 1. Direct validation rejects API host and port 8100
        with pytest.raises(ValueError, match=r"8100"):
            validate_web_public_url("http://127.0.0.1:8100")
        with pytest.raises(ValueError, match=r"8100"):
            validate_web_public_url("http://localhost:8100")
        with pytest.raises(ValueError, match=r"8100"):
            build_canonical_prospect_url("http://127.0.0.1:8100", "p-123")

        # 2. Service ignores API base_url passed to trigger_handoff
        container = crm_ctx["container"]
        org_a = crm_ctx["org_a"]
        _seed_crm_destination(container, org_a.bop_organization_id)

        from bopclients.domain.prospect import Prospect
        prospect_safe = Prospect(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            name="Safe Prospect",
        )
        container.prospect_repo.save_prospect(org_a.id, prospect_safe)

        res = container.crm_handoff_service.trigger_handoff(
            bop_organization_id=org_a.bop_organization_id,
            organization_id=org_a.id,
            prospect_id=prospect_safe.id,
            requested_by_user_id="user-1",
            base_url="http://127.0.0.1:8100",  # simulating API request host
        )
        event = container.outbox_repo.get_event(res["event_id"], bop_organization_id=org_a.bop_organization_id)
        assert ":8100" not in event.payload["prospect_url"]
        assert event.payload["prospect_url"].startswith("http://localhost:3011")

    def test_c_docker_internal_host_never_leaks(self):
        """C. Docker-internal host never leaks."""
        from bopclients.application.crm_handoff_service import validate_web_public_url
        with pytest.raises(ValueError, match=r"internal host"):
            validate_web_public_url("http://backend:3000")
        with pytest.raises(ValueError, match=r"internal host"):
            validate_web_public_url("http://web:3000")
        with pytest.raises(ValueError, match=r"internal host"):
            validate_web_public_url("http://django-crm-backend:8000")
        with pytest.raises(ValueError, match=r"internal host"):
            validate_web_public_url("http://api.internal")

    def test_d_configured_production_https_origin_works(self):
        """D. Configured production HTTPS origin works."""
        from bopclients.application.crm_handoff_service import build_canonical_prospect_url
        prod_url = build_canonical_prospect_url(
            web_public_url="https://clients.bopagenciy.com",
            prospect_id="b0000004-0000-4000-8000-000000000004",
            locale="en",
            is_production=True,
        )
        assert prod_url == "https://clients.bopagenciy.com/en/prospects/b0000004-0000-4000-8000-000000000004"

        # Trailing slash is properly normalized
        prod_url_slash = build_canonical_prospect_url(
            web_public_url="https://clients.bopagenciy.com/",
            prospect_id="b0000004-0000-4000-8000-000000000004",
            locale="en",
            is_production=True,
        )
        assert prod_url_slash == "https://clients.bopagenciy.com/en/prospects/b0000004-0000-4000-8000-000000000004"

        # HTTP rejected in production
        with pytest.raises(ValueError, match=r"HTTPS"):
            build_canonical_prospect_url(
                web_public_url="http://clients.bopagenciy.com",
                prospect_id="b0000004-0000-4000-8000-000000000004",
                is_production=True,
            )

    def test_e_prospect_id_preserved(self):
        """E. Prospect ID preserved exactly."""
        from bopclients.application.crm_handoff_service import build_canonical_prospect_url
        pid = "b0000004-0000-4000-8000-000000000004"
        url = build_canonical_prospect_url("http://localhost:3011", pid, "en")
        assert url.endswith(f"/prospects/{pid}")

    def test_f_correct_supported_locale_path_used(self):
        """F. Correct supported locale path used."""
        from bopclients.application.crm_handoff_service import build_canonical_prospect_url
        pid = "test-pid-1"
        url_en = build_canonical_prospect_url("http://localhost:3011", pid, "en")
        assert url_en == f"http://localhost:3011/en/prospects/{pid}"

        url_es = build_canonical_prospect_url("http://localhost:3011", pid, "es")
        assert url_es == f"http://localhost:3011/es/prospects/{pid}"

        url_es_sub = build_canonical_prospect_url("http://localhost:3011", pid, "es-MX")
        assert url_es_sub == f"http://localhost:3011/es/prospects/{pid}"

        # Unknown locale falls back safely to default 'en'
        url_fallback = build_canonical_prospect_url("http://localhost:3011", pid, "de")
        assert url_fallback == f"http://localhost:3011/en/prospects/{pid}"

    def test_g_existing_event_idempotency_unchanged(self, crm_ctx):
        """G. Existing event idempotency unchanged."""
        client = crm_ctx["client"]
        container = crm_ctx["container"]
        headers = crm_ctx["admin_headers"]
        prospect_a = crm_ctx["prospect_a"]
        org_a = crm_ctx["org_a"]

        _seed_crm_destination(container, org_a.bop_organization_id)

        res1 = client.post(f"/api/v1/prospects/{prospect_a.id}/crm-handoff", headers=headers)
        assert res1.status_code == 200
        assert res1.json()["is_idempotent_replay"] is False
        event_id1 = res1.json()["event_id"]

        res2 = client.post(f"/api/v1/prospects/{prospect_a.id}/crm-handoff", headers=headers)
        assert res2.status_code == 200
        assert res2.json()["is_idempotent_replay"] is True
        assert res2.json()["event_id"] == event_id1

        # Confirm only one outbox record exists
        outbox_rows = container.outbox_repo.list_pending()
        matching = [r for r in outbox_rows if r.event_id == event_id1]
        assert len(matching) == 1

    def test_h_missing_public_url_fails_safely_not_api_url(self):
        """H. Missing public URL configuration fails safely rather than returning an API URL."""
        from bopclients.application.crm_handoff_service import build_canonical_prospect_url
        pid = "test-pid-2"
        # In production, missing web_public_url raises ValueError
        with pytest.raises(ValueError, match=r"BOPCLIENTS_WEB_PUBLIC_URL is required"):
            build_canonical_prospect_url("", pid, is_production=True)

        with pytest.raises(ValueError, match=r"BOPCLIENTS_WEB_PUBLIC_URL is required"):
            build_canonical_prospect_url("   ", pid, is_production=True)

        # In dev, missing web_public_url safely defaults to frontend port 3011, NEVER API port 8100
        dev_url = build_canonical_prospect_url("", pid, is_production=False)
        assert dev_url == f"http://localhost:3011/en/prospects/{pid}"
        assert ":8100" not in dev_url
