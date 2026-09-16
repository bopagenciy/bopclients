"""Targeted test suite for Phase P25: Transactional Email Delivery Foundation."""

import pytest
import uuid
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from bopclients.domain.email import (
    EmailCategory,
    EmailDeliveryStatus,
    TransactionalEmailMessage,
    EmailDeliveryResult,
)
from bopclients.application.email_templates import render_invitation_email
from bopclients.infrastructure.email.in_memory_sender import InMemoryEmailSender
from bopclients.infrastructure.email.null_sender import NullEmailSender
from bopclients.infrastructure.email.resend_sender import ResendEmailSender
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.container import build_runtime_container
from bopclients.api.app import create_bopclients_api_app
from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.domain.enums import MemberRole, InvitationStatus


@pytest.fixture
def email_test_context():
    """Builds a test environment with InMemoryEmailSender and pre-seeded orgs/users."""
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)

    settings = RuntimeSettings(
        database_url="sqlite:///:memory:",
        auth_signing_key="p25-test-signing-key-minimum-32-chars-long!",
        auth_token_expire_seconds=3600,
        email_provider="in_memory",
        email_from="support@bopclients.com",
        email_api_key="re_test_key_secret",
        app_url="https://app.bopclients.com",
        invitation_dev_token_exposure=True,
    )
    container = build_runtime_container(settings=settings, db=db)
    app = create_bopclients_api_app(container=container, settings=settings)
    client = TestClient(app)

    # Seed Org A
    org_a = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Acme Corp",
        slug="acme-corp",
    )
    container.org_repo.save(org_a)

    # Seed Org B (cross-tenant)
    org_b = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="Beta LLC",
        slug="beta-llc",
    )
    container.org_repo.save(org_b)

    # Seed Owner of Org A
    owner_user = container.auth_service.register_user(
        email="owner@acme.com",
        name="Alice Owner",
        password="Password123!",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=owner_user.id,
            role=MemberRole.OWNER,
        )
    )

    # Seed Admin of Org A
    admin_user = container.auth_service.register_user(
        email="admin@acme.com",
        name="Bob Admin",
        password="Password123!",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=admin_user.id,
            role=MemberRole.ADMIN,
        )
    )

    # Seed Member of Org A
    member_user = container.auth_service.register_user(
        email="member@acme.com",
        name="Charlie Member",
        password="Password123!",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=member_user.id,
            role=MemberRole.MEMBER,
        )
    )

    # Seed Owner of Org B
    owner_b = container.auth_service.register_user(
        email="owner@beta.com",
        name="Zoe Beta",
        password="Password123!",
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_b.id,
            user_id=owner_b.id,
            role=MemberRole.OWNER,
        )
    )

    # Auth tokens
    owner_tokens, _ = container.auth_service.authenticate("owner@acme.com", "Password123!")
    admin_tokens, _ = container.auth_service.authenticate("admin@acme.com", "Password123!")
    member_tokens, _ = container.auth_service.authenticate("member@acme.com", "Password123!")
    owner_b_tokens, _ = container.auth_service.authenticate("owner@beta.com", "Password123!")

    return {
        "client": client,
        "container": container,
        "settings": settings,
        "org_a": org_a,
        "org_b": org_b,
        "owner_user": owner_user,
        "admin_user": admin_user,
        "member_user": member_user,
        "owner_b": owner_b,
        "owner_token": owner_tokens.access_token,
        "admin_token": admin_tokens.access_token,
        "member_token": member_tokens.access_token,
        "owner_b_token": owner_b_tokens.access_token,
    }


# =========================================================================
# 1. SENDER IMPLEMENTATION LIFECYCLE TESTS
# =========================================================================

def test_in_memory_sender_lifecycle():
    """Verify InMemoryEmailSender records messages and supports clearing."""
    sender = InMemoryEmailSender()
    assert sender.get_sent_messages() == []

    msg = TransactionalEmailMessage(
        to="test@example.com",
        from_email="noreply@example.com",
        subject="Hello World",
        html_body="<p>Test</p>",
        text_body="Test",
        category=EmailCategory.TEAM_INVITATION,
    )
    result = sender.send(msg)

    assert result.is_success is True
    assert result.status == EmailDeliveryStatus.SENT
    assert result.message_id is not None
    assert len(sender.get_sent_messages()) == 1
    assert sender.get_sent_messages()[0].to == "test@example.com"

    sender.clear()
    assert len(sender.get_sent_messages()) == 0


def test_null_email_sender_reports_not_configured():
    """Verify NullEmailSender truthfully reports not configured without failing abruptly."""
    sender = NullEmailSender()
    msg = TransactionalEmailMessage(
        to="test@example.com",
        from_email="noreply@example.com",
        subject="Hello World",
        html_body="<p>Test</p>",
        text_body="Test",
        category=EmailCategory.TEAM_INVITATION,
    )
    result = sender.send(msg)

    assert result.is_success is False
    assert result.status == EmailDeliveryStatus.NOT_CONFIGURED
    assert "Transactional email provider is not configured" in result.error


def test_resend_sender_mock_http_success_and_error():
    """Verify ResendEmailSender interacts with Resend API over HTTP and handles responses cleanly."""
    mock_http_client = MagicMock()
    sender = ResendEmailSender(
        api_key="re_valid_api_key_12345",
        default_from="BopClients <team@bopclients.com>",
        client=mock_http_client,
    )
    msg = TransactionalEmailMessage(
        to="invitee@customer.com",
        from_email="BopClients <team@bopclients.com>",
        subject="You are invited",
        html_body="<p>Welcome</p>",
        text_body="Welcome",
        category=EmailCategory.TEAM_INVITATION,
    )

    # Success case: 200 OK from Resend API
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "resend_msg_98765"}
    mock_http_client.post.return_value = mock_resp

    res = sender.send(msg)
    assert res.is_success is True
    assert res.status == EmailDeliveryStatus.SENT
    assert res.message_id == "resend_msg_98765"

    # Verify headers & payload
    mock_http_client.post.assert_called_once()
    _, kwargs = mock_http_client.post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer re_valid_api_key_12345"
    assert kwargs["json"]["to"] == ["invitee@customer.com"]
    assert kwargs["json"]["subject"] == "You are invited"

    # API Error case: 422 Unprocessable Entity
    mock_err_resp = MagicMock()
    mock_err_resp.is_success = False
    mock_err_resp.status_code = 422
    mock_err_resp.json.return_value = {"statusCode": 422, "message": "Domain is not verified"}
    mock_http_client.post.return_value = mock_err_resp

    res = sender.send(msg)
    assert res.is_success is False
    assert res.status == EmailDeliveryStatus.FAILED
    assert "Domain is not verified" in res.error
    # Verify API key is NOT leaked into the error string
    assert "re_valid_api_key_12345" not in res.error


def test_provider_failure_sanitization_masks_sensitive_body(email_test_context):
    """Verify provider error with sensitive raw body/headers is never surfaced to API result."""
    ctx = email_test_context
    client = ctx["client"]
    container = ctx["container"]
    headers = {
        "Authorization": f"Bearer {ctx['owner_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }

    # Configure Resend sender with mock returning raw sensitive payload
    sensitive_provider_body = {
        "statusCode": 500,
        "message": "Internal error: secret_api_key_abc failed with Authorization: Bearer re_12345",
        "debug": {
            "token": "raw_sensitive_token_leak",
            "headers": {"Authorization": "Bearer re_valid_api_key_12345"},
        },
    }
    mock_err_resp = MagicMock()
    mock_err_resp.is_success = False
    mock_err_resp.status_code = 500
    mock_err_resp.json.return_value = sensitive_provider_body
    mock_http_client = MagicMock()
    mock_http_client.post.return_value = mock_err_resp

    resend_sender = ResendEmailSender(
        api_key="re_valid_api_key_12345",
        default_from="BopClients <invites@bopclients.com>",
        client=mock_http_client,
    )
    # Swap sender in invitation service
    container.invitation_service.email_sender = resend_sender

    res = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "leaktest@acme.com", "role": "member"},
        headers=headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["delivery_status"] == "failed"
    error_str = data.get("delivery_error") or ""

    # Asserts: sensitive info, headers, tokens, and raw keys must NOT be present
    assert "raw_sensitive_token_leak" not in error_str
    assert "re_valid_api_key_12345" not in error_str
    assert "Authorization" not in error_str
    assert "Bearer" not in error_str
    assert "secret_api_key_abc" not in error_str
    # Verify it maps to safe generic message
    assert "Email provider delivery failed" in error_str


# =========================================================================
# 2. BILINGUAL TEMPLATE RENDERING TESTS
# =========================================================================

def test_email_template_rendering_en_and_es():
    """Verify bilingual templates render responsive HTML and text fallback with XSS protection."""
    # English
    subject_en, html_en, text_en = render_invitation_email(
        organization_name="Acme Corp",
        inviter_name="Alice Owner",
        role="admin",
        invite_url="https://app.bopclients.com/invite/tok_en123",
        locale="en",
    )
    assert "Invitation to join Acme Corp on BopClients" in subject_en
    assert "Alice Owner" in html_en
    assert "Administrador" not in html_en
    assert "https://app.bopclients.com/invite/tok_en123" in html_en
    assert "7 days" in text_en

    # Spanish
    subject_es, html_es, text_es = render_invitation_email(
        organization_name="Acme Corp",
        inviter_name="Alice Owner",
        role="admin",
        invite_url="https://app.bopclients.com/es/invite/tok_es123",
        locale="es",
    )
    assert "Invitación para unirse a Acme Corp en BopClients" in subject_es
    assert "Administrador" in html_es
    assert "Aceptar Invitación" in html_es or "Aceptar" in html_es
    assert "7 días" in text_es
    assert "https://app.bopclients.com/es/invite/tok_es123" in html_es

    # HTML escaping for malicious input
    _, html_xss, _ = render_invitation_email(
        organization_name="<script>alert('xss')</script>",
        inviter_name="<b onmouseover='alert(1)'>Hacker</b>",
        role="member",
        invite_url="https://app.bopclients.com/invite/test",
        locale="en",
    )
    assert "<script>" not in html_xss
    assert "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in html_xss
    assert "&lt;b onmouseover=" in html_xss


# =========================================================================
# 3. END-TO-END INVITATION CREATION & DISPATCH
# =========================================================================

def test_invitation_creation_dispatches_email(email_test_context):
    """Creating an invitation automatically triggers email delivery and reports truthful delivery_status."""
    ctx = email_test_context
    client = ctx["client"]
    container = ctx["container"]
    headers = {
        "Authorization": f"Bearer {ctx['owner_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }

    res = client.post(
        "/api/v1/organizations/current/invitations",
        json={
            "email": "colleague@acme.com",
            "role": "member",
            "locale": "es",
        },
        headers=headers,
    )
    assert res.status_code == 201
    data = res.json()
    assert data["email"] == "colleague@acme.com"
    assert data["role"] == "member"
    assert data["delivery_status"] == "sent"
    assert data["delivery_error"] is None

    # Check that email was recorded in InMemoryEmailSender
    sent_msgs = container.email_sender.get_sent_messages()
    assert len(sent_msgs) == 1
    sent = sent_msgs[0]
    assert sent.to == "colleague@acme.com"
    assert "Invitación para unirse a Acme Corp" in sent.subject
    assert "/es/invite/" in sent.html_body


# =========================================================================
# 4. TOKEN ROTATION ON RESEND
# =========================================================================

def test_resend_invitation_rotates_token_and_resends_email(email_test_context):
    """Resending an invitation rotates the raw token, invalidates old token, and sends new email."""
    ctx = email_test_context
    client = ctx["client"]
    container = ctx["container"]
    headers = {
        "Authorization": f"Bearer {ctx['owner_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }

    # 1. Create initial invitation
    create_res = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "resendee@acme.com", "role": "member"},
        headers=headers,
    )
    assert create_res.status_code == 201
    inv_id = create_res.json()["id"]

    # In dev mode, raw_token is returned in response
    old_raw_token = create_res.json().get("raw_token")
    assert old_raw_token is not None

    # Get original token hash from DB
    db = container.db
    orig_row = db.fetch_dicts("SELECT token_hash, expires_at FROM organization_invitations WHERE id = ?", (inv_id,))[0]
    orig_hash = orig_row["token_hash"]

    # Initial emails sent: 1
    assert len(container.email_sender.get_sent_messages()) == 1

    # 2. Resend invitation
    resend_res = client.post(
        f"/api/v1/organizations/current/invitations/{inv_id}/resend",
        json={"locale": "en"},
        headers=headers,
    )
    assert resend_res.status_code == 200
    resend_data = resend_res.json()
    assert resend_data["id"] == inv_id
    assert resend_data["delivery_status"] == "sent"

    new_raw_token = resend_data.get("raw_token")
    assert new_raw_token is not None
    assert new_raw_token != old_raw_token

    # 3. Verify DB row updated with new hash and refreshed expiration
    updated_row = db.fetch_dicts("SELECT token_hash, expires_at FROM organization_invitations WHERE id = ?", (inv_id,))[0]
    new_hash = updated_row["token_hash"]
    assert new_hash != orig_hash

    # 4. Total emails sent: 2
    assert len(container.email_sender.get_sent_messages()) == 2

    # 5. Old token is INVALID
    old_inspect = client.get(f"/api/v1/invitations/{old_raw_token}")
    assert old_inspect.status_code == 404

    # 6. New token is VALID
    new_inspect = client.get(f"/api/v1/invitations/{new_raw_token}")
    assert new_inspect.status_code == 200
    assert new_inspect.json()["organization_name"] == "Acme Corp"


# =========================================================================
# 5. RBAC & TENANT ISOLATION ON RESEND
# =========================================================================

def test_resend_invitation_rbac_and_tenant_isolation(email_test_context):
    """Verify RBAC and cross-tenant boundaries for resending invitations."""
    ctx = email_test_context
    client = ctx["client"]
    headers_owner = {
        "Authorization": f"Bearer {ctx['owner_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }
    headers_admin = {
        "Authorization": f"Bearer {ctx['admin_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }
    headers_member = {
        "Authorization": f"Bearer {ctx['member_token']}",
        "X-Bop-Organization-Id": ctx["org_a"].bop_organization_id,
    }
    headers_org_b = {
        "Authorization": f"Bearer {ctx['owner_b_token']}",
        "X-Bop-Organization-Id": ctx["org_b"].bop_organization_id,
    }

    # Create admin invitation in Org A
    inv_admin_res = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "futureadmin@acme.com", "role": "admin"},
        headers=headers_owner,
    )
    admin_inv_id = inv_admin_res.json()["id"]

    # Create member invitation in Org A
    inv_member_res = client.post(
        "/api/v1/organizations/current/invitations",
        json={"email": "futuremember@acme.com", "role": "member"},
        headers=headers_owner,
    )
    member_inv_id = inv_member_res.json()["id"]

    # 1. MEMBER role cannot resend invitations (403)
    res = client.post(
        f"/api/v1/organizations/current/invitations/{member_inv_id}/resend",
        json={},
        headers=headers_member,
    )
    assert res.status_code == 403

    # 2. ADMIN role cannot resend ADMIN invitations (403)
    res = client.post(
        f"/api/v1/organizations/current/invitations/{admin_inv_id}/resend",
        json={},
        headers=headers_admin,
    )
    assert res.status_code == 403

    # 3. ADMIN can resend MEMBER invitations (200)
    res = client.post(
        f"/api/v1/organizations/current/invitations/{member_inv_id}/resend",
        json={},
        headers=headers_admin,
    )
    assert res.status_code == 200

    # 4. Cross-tenant isolation: Org B owner cannot resend Org A's invitation (404)
    res = client.post(
        f"/api/v1/organizations/current/invitations/{member_inv_id}/resend",
        json={},
        headers=headers_org_b,
    )
    assert res.status_code == 404

    # 5. Revoked invitation cannot be resent (410 GONE)
    client.delete(
        f"/api/v1/organizations/current/invitations/{member_inv_id}",
        headers=headers_owner,
    )
    res = client.post(
        f"/api/v1/organizations/current/invitations/{member_inv_id}/resend",
        json={},
        headers=headers_owner,
    )
    assert res.status_code == 410
    assert res.json()["error"]["code"] == "INVITATION_REVOKED"


# =========================================================================
# 6. SECRET HYGIENE
# =========================================================================

def test_secret_hygiene(email_test_context):
    """RuntimeSettings safe_summary and API responses never expose email_api_key."""
    settings = email_test_context["settings"]
    summary = settings.safe_summary()

    # Verify secret is masked in safe_summary
    assert "email_api_key" not in summary
    assert "re_test_key_secret" not in str(summary)

    # Verify list invitations response does not contain any secrets or tokens
    client = email_test_context["client"]
    headers = {
        "Authorization": f"Bearer {email_test_context['owner_token']}",
        "X-Bop-Organization-Id": email_test_context["org_a"].bop_organization_id,
    }
    res = client.get("/api/v1/organizations/current/invitations", headers=headers)
    assert res.status_code == 200
    res_str = res.text
    assert "re_test_key_secret" not in res_str
    assert "token_hash" not in res_str
