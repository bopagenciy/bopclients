"""Application service coordinating secure organization invitations lifecycle."""

import hashlib
import logging
import re
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple, Any

from bopclients.domain.invitation import OrganizationInvitation
from bopclients.domain.organization import OrganizationMember
from bopclients.domain.user import User
from bopclients.domain.enums import MemberRole, InvitationStatus
from bopclients.domain.auth.policy import AuthorizationPolicy
from bopclients.domain.exceptions import (
    MemberRolePermissionError,
    ValidationError,
    InvitationNotFoundError,
    InvitationExpiredError,
    InvitationAlreadyAcceptedError,
    InvitationRevokedError,
    AlreadyOrganizationMemberError,
    DuplicateInvitationError,
    InvitationEmailMismatchError,
)
from bopclients.infrastructure.repositories.invitation_repository import InvitationRepository
from bopclients.infrastructure.repositories.organization_repository import OrganizationRepository, UserRepository
from bopclients.domain.email import (
    TransactionalEmailMessage,
    EmailCategory,
    EmailDeliveryResult,
    EmailDeliveryStatus,
)
from bopclients.application.interfaces.email_sender import ITransactionalEmailSender
from bopclients.application.email_templates import render_invitation_email

logger = logging.getLogger("bopclients.application.invitation")
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InvitationService:
    """Service managing team invitation creation, listing, revocation, and atomic onboarding."""

    def __init__(
        self,
        inv_repo: InvitationRepository,
        org_repo: OrganizationRepository,
        user_repo: UserRepository,
        auth_service: Optional[Any] = None,
        invitation_expiry_days: int = 7,
        email_sender: Optional[ITransactionalEmailSender] = None,
        app_url: str = "http://localhost:3000",
        default_from: Optional[str] = None,
    ):
        self.inv_repo = inv_repo
        self.org_repo = org_repo
        self.user_repo = user_repo
        self.auth_service = auth_service
        self.invitation_expiry_days = invitation_expiry_days
        self.email_sender = email_sender
        self.app_url = app_url.rstrip("/") if app_url else "http://localhost:3000"
        self.default_from = default_from

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """Compute deterministic SHA-256 hash of raw invitation token."""
        return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()

    def create_invitation(
        self,
        inviter_user_id: str,
        org_id: str,
        email: str,
        role: MemberRole | str = MemberRole.MEMBER,
        locale: str = "en",
    ) -> Tuple[OrganizationInvitation, str, EmailDeliveryResult]:
        """Create a new secure invitation to join an organization and dispatch email.

        Enforces RBAC, email validation, duplicate prevention, and conflict checks.
        Returns:
            Tuple of (OrganizationInvitation, raw_token, EmailDeliveryResult).
            The raw_token is NEVER stored in the database.
        """
        # 1. Verify inviter exists and has membership in target organization
        inviter_member = self.org_repo.get_member(org_id, inviter_user_id)
        if not inviter_member:
            raise MemberRolePermissionError("User is not a member of the target organization.")

        actor_role = AuthorizationPolicy.normalize_role(inviter_member.role)
        if actor_role not in (MemberRole.OWNER, MemberRole.ADMIN):
            raise MemberRolePermissionError(f"Role '{actor_role.value.upper()}' lacks required permission to invite members.")

        # 2. Normalize and validate target role
        target_role = AuthorizationPolicy.normalize_role(role)
        if target_role == MemberRole.OWNER:
            raise ValidationError("Cannot invite a user with the OWNER role.")

        if actor_role == MemberRole.ADMIN and target_role in (MemberRole.OWNER, MemberRole.ADMIN):
            raise MemberRolePermissionError("Admins cannot invite Owners or other Admins.")

        # 3. Normalize and validate target email
        norm_email = email.strip().lower()
        if not EMAIL_REGEX.match(norm_email):
            raise ValidationError(f"Invalid email address: '{email}'")

        # 4. Check if user already exists and is already a member of this organization
        existing_user = self.user_repo.get_by_email(norm_email)
        if existing_user:
            existing_membership = self.org_repo.get_member(org_id, existing_user.id)
            if existing_membership:
                raise AlreadyOrganizationMemberError("User is already a member of this organization.")

        # 5. Check if active pending invitation already exists for this email in this org
        existing_invite = self.inv_repo.get_pending_by_email(org_id, norm_email)
        if existing_invite:
            if not existing_invite.is_expired():
                raise DuplicateInvitationError("A pending invitation already exists for this email.")
            else:
                # Mark existing expired invitation
                self.inv_repo.update_status(existing_invite.id, InvitationStatus.EXPIRED)

        # 6. Generate secure raw token and SHA-256 hash
        raw_token = secrets.token_urlsafe(32)
        token_hash = self.hash_token(raw_token)

        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(days=self.invitation_expiry_days)).isoformat()
        now_iso = now.isoformat()

        invitation = OrganizationInvitation(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            email_normalized=norm_email,
            role=target_role,
            token_hash=token_hash,
            status=InvitationStatus.PENDING,
            invited_by_user_id=inviter_user_id,
            expires_at=expires_at,
            created_at=now_iso,
            updated_at=now_iso,
        )

        saved = self.inv_repo.save(invitation)
        logger.info(
            f"Created invitation {saved.id} for {saved.email_normalized} to org {saved.organization_id} with role {saved.role.value}"
        )

        # 7. Dispatch transactional email
        delivery_result = self._dispatch_invitation_email(
            invitation=saved,
            raw_token=raw_token,
            inviter_user_id=inviter_user_id,
            locale=locale,
        )

        return saved, raw_token, delivery_result

    def resend_invitation(
        self,
        actor_user_id: str,
        org_id: str,
        invitation_id: str,
        locale: str = "en",
    ) -> Tuple[OrganizationInvitation, str, EmailDeliveryResult]:
        """Resend an existing pending invitation with mandatory token rotation.

        Generates a new token, updates token_hash and resets expiration to 7 days,
        invalidating the previous token. Dispatches a new email.
        """
        actor_member = self.org_repo.get_member(org_id, actor_user_id)
        if not actor_member:
            raise MemberRolePermissionError("User is not a member of the target organization.")

        actor_role = AuthorizationPolicy.normalize_role(actor_member.role)
        if actor_role not in (MemberRole.OWNER, MemberRole.ADMIN):
            raise MemberRolePermissionError(f"Role '{actor_role.value.upper()}' lacks required permission to resend invitations.")

        invitation = self.inv_repo.get_by_id(org_id, invitation_id)
        if not invitation:
            raise InvitationNotFoundError("Invitation not found.")

        if actor_role == MemberRole.ADMIN and invitation.role in (MemberRole.OWNER, MemberRole.ADMIN):
            raise MemberRolePermissionError("Admins cannot resend invitations for Owners or Admins.")

        if invitation.status == InvitationStatus.ACCEPTED:
            raise InvitationAlreadyAcceptedError("Cannot resend an invitation that has already been accepted.")

        if invitation.status == InvitationStatus.REVOKED:
            raise InvitationRevokedError("Cannot resend a revoked invitation.")

        # Token Rotation Invariant: Always issue fresh token & invalidate prior
        raw_token = secrets.token_urlsafe(32)
        new_token_hash = self.hash_token(raw_token)

        now = datetime.now(timezone.utc)
        new_expires_at = (now + timedelta(days=self.invitation_expiry_days)).isoformat()
        now_iso = now.isoformat()

        invitation.token_hash = new_token_hash
        invitation.status = InvitationStatus.PENDING
        invitation.expires_at = new_expires_at
        invitation.updated_at = now_iso

        saved = self.inv_repo.save(invitation)
        logger.info(
            f"Rotated token and refreshed invitation {saved.id} for {saved.email_normalized} in org {org_id}"
        )

        delivery_result = self._dispatch_invitation_email(
            invitation=saved,
            raw_token=raw_token,
            inviter_user_id=actor_user_id,
            locale=locale,
        )

        return saved, raw_token, delivery_result

    def _dispatch_invitation_email(
        self,
        invitation: OrganizationInvitation,
        raw_token: str,
        inviter_user_id: str,
        locale: str = "en",
    ) -> EmailDeliveryResult:
        """Internal helper to render and dispatch transactional email."""
        if not self.email_sender:
            return EmailDeliveryResult(
                status=EmailDeliveryStatus.NOT_CONFIGURED,
                error="No transactional email sender configured.",
            )

        norm_locale = (locale or "en").strip().lower()
        invite_url = f"{self.app_url}/{norm_locale}/invite/{raw_token}"

        org = self.org_repo.get_by_id(invitation.organization_id)
        org_name = org.name if org else "BopClients"

        inviter_user = self.user_repo.get_by_id(inviter_user_id)
        inviter_name = inviter_user.full_name if inviter_user else ""

        role_str = invitation.role.value if isinstance(invitation.role, MemberRole) else str(invitation.role)

        subject, html_body, text_body = render_invitation_email(
            organization_name=org_name,
            role=role_str,
            invite_url=invite_url,
            locale=norm_locale,
            inviter_name=inviter_name,
        )

        message = TransactionalEmailMessage(
            to=invitation.email_normalized,
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            category=EmailCategory.TEAM_INVITATION,
            from_email=self.default_from,
            metadata={
                "invitation_id": invitation.id,
                "organization_id": invitation.organization_id,
                "role": role_str,
            },
        )

        try:
            return self.email_sender.send(message)
        except Exception as exc:
            logger.error(f"Unexpected exception sending invitation email: {exc}")
            return EmailDeliveryResult(
                status=EmailDeliveryStatus.FAILED,
                error="Internal error occurred while dispatching email.",
            )

    def list_invitations(
        self,
        org_id: str,
        status: Optional[InvitationStatus | str] = None,
    ) -> List[OrganizationInvitation]:
        """List invitations for an organization, lazily expiring any pending invitations past expiry."""
        st = None
        if status:
            if isinstance(status, str):
                st = InvitationStatus(status.strip().lower())
            else:
                st = status

        invites = self.inv_repo.list_by_organization(org_id, status=st)
        now = datetime.now(timezone.utc)
        for inv in invites:
            if inv.status == InvitationStatus.PENDING and inv.is_expired(now):
                inv.status = InvitationStatus.EXPIRED
                self.inv_repo.update_status(inv.id, InvitationStatus.EXPIRED)
        return invites

    def revoke_invitation(
        self,
        actor_user_id: str,
        org_id: str,
        invitation_id: str,
    ) -> OrganizationInvitation:
        """Revoke a pending invitation.

        Enforces RBAC: Admins cannot revoke invitations to roles higher than they can assign.
        """
        actor_member = self.org_repo.get_member(org_id, actor_user_id)
        if not actor_member:
            raise MemberRolePermissionError("User is not a member of the target organization.")

        actor_role = AuthorizationPolicy.normalize_role(actor_member.role)
        if actor_role not in (MemberRole.OWNER, MemberRole.ADMIN):
            raise MemberRolePermissionError(f"Role '{actor_role.value.upper()}' lacks required permission to revoke invitations.")

        invitation = self.inv_repo.get_by_id(org_id, invitation_id)
        if not invitation:
            raise InvitationNotFoundError("Invitation not found.")

        if actor_role == MemberRole.ADMIN and invitation.role in (MemberRole.OWNER, MemberRole.ADMIN):
            raise MemberRolePermissionError("Admins cannot revoke invitations for Owners or Admins.")

        if invitation.status == InvitationStatus.ACCEPTED:
            raise InvitationAlreadyAcceptedError("Cannot revoke an invitation that has already been accepted.")

        if invitation.status == InvitationStatus.REVOKED:
            return invitation

        now_iso = datetime.now(timezone.utc).isoformat()
        invitation.status = InvitationStatus.REVOKED
        invitation.revoked_at = now_iso
        invitation.updated_at = now_iso

        self.inv_repo.update_status(
            invitation.id,
            status=InvitationStatus.REVOKED,
            revoked_at=now_iso,
        )
        logger.info(f"Revoked invitation {invitation.id} in org {org_id} by user {actor_user_id}")
        return invitation

    def get_invitation_by_token(self, raw_token: str) -> OrganizationInvitation:
        """Lookup an invitation by raw token, verifying validity and non-expiration."""
        if not raw_token or not raw_token.strip():
            raise InvitationNotFoundError("Invitation token is required.")

        token_hash = self.hash_token(raw_token)
        invitation = self.inv_repo.get_by_token_hash(token_hash)
        if not invitation:
            raise InvitationNotFoundError("Invitation not found or invalid token.")

        if invitation.status == InvitationStatus.ACCEPTED:
            raise InvitationAlreadyAcceptedError("This invitation has already been accepted.")

        if invitation.status == InvitationStatus.REVOKED:
            raise InvitationRevokedError("This invitation has been revoked.")

        if invitation.status == InvitationStatus.EXPIRED or invitation.is_expired():
            if invitation.status != InvitationStatus.EXPIRED:
                self.inv_repo.update_status(invitation.id, InvitationStatus.EXPIRED)
                invitation.status = InvitationStatus.EXPIRED
            raise InvitationExpiredError("This invitation has expired.")

        return invitation

    def accept_invitation(
        self,
        raw_token: str,
        user: User,
    ) -> Tuple[OrganizationInvitation, OrganizationMember]:
        """Atomically accept an invitation for an authenticated user.

        Verifies matching email, non-membership, and transitions status to ACCEPTED.
        """
        invitation = self.get_invitation_by_token(raw_token)

        # Verify email match
        user_email = user.email.strip().lower()
        if user_email != invitation.email_normalized:
            raise InvitationEmailMismatchError(
                f"Authenticated user email '{user_email}' does not match invitation email '{invitation.email_normalized}'"
            )

        # Check if already a member
        existing = self.org_repo.get_member(invitation.organization_id, user.id)
        if existing:
            raise AlreadyOrganizationMemberError("User is already a member of this organization.")

        now_iso = datetime.now(timezone.utc).isoformat()

        # Atomic transaction: insert member + update invitation
        member = OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=invitation.organization_id,
            user_id=user.id,
            role=invitation.role,
            created_at=now_iso,
        )

        self.org_repo.add_member(member, commit=False)

        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = now_iso
        invitation.updated_at = now_iso

        self.inv_repo.update_status(
            invitation.id,
            status=InvitationStatus.ACCEPTED,
            accepted_at=now_iso,
            commit=False,
        )

        # Commit both operations together
        if hasattr(self.inv_repo.db, "commit"):
            self.inv_repo.db.commit()

        logger.info(
            f"User {user.id} ({user.email}) accepted invitation {invitation.id} into org {invitation.organization_id} with role {invitation.role.value}"
        )
        return invitation, member

    def register_and_accept(
        self,
        raw_token: str,
        name: str,
        password: str,
        locale: str = "en",
    ) -> Tuple[OrganizationInvitation, OrganizationMember, User, Any]:
        """Register a new user using their invitation email and atomically onboard them.

        Creates user, accepts invitation, and authenticates session.
        """
        if not self.auth_service:
            raise RuntimeError("AuthService is required for register_and_accept.")

        invitation = self.get_invitation_by_token(raw_token)

        existing_user = self.user_repo.get_by_email(invitation.email_normalized)
        if existing_user:
            raise ValidationError("An account with this email already exists. Please log in to accept the invitation.")

        # Register user
        user = self.auth_service.register_user(
            email=invitation.email_normalized,
            name=name,
            password=password,
            locale=locale,
        )

        try:
            # Accept invitation
            inv, member = self.accept_invitation(raw_token, user)

            # Authenticate session
            token_pair, authed_user = self.auth_service.authenticate(
                email=invitation.email_normalized,
                password=password,
            )
        except Exception:
            # Rollback newly registered user if membership onboarding fails
            try:
                p = self.user_repo._placeholder() if hasattr(self.user_repo, "_placeholder") else "?"
                self.user_repo.db.execute(f"DELETE FROM users WHERE id = {p}", (user.id,))
                if hasattr(self.user_repo.db, "commit"):
                    self.user_repo.db.commit()
            except Exception:
                pass
            raise

        return inv, member, authed_user, token_pair
