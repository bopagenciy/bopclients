"""Database repository for Organization Invitation persistence."""

from datetime import datetime, timezone
from typing import List, Optional
from bopclients.domain.invitation import OrganizationInvitation
from bopclients.domain.enums import MemberRole, InvitationStatus
from bopclients.application.interfaces.repositories import IInvitationRepository
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class InvitationRepository(BaseTenantRepository, IInvitationRepository):
    """Repository for OrganizationInvitation persistence and queries."""

    @staticmethod
    def _row_to_invitation(r: dict) -> OrganizationInvitation:
        role_val = r["role"].lower() if isinstance(r["role"], str) else r["role"]
        status_val = r["status"].lower() if isinstance(r["status"], str) else r["status"]
        return OrganizationInvitation(
            id=r["id"],
            organization_id=r["organization_id"],
            email_normalized=r["email_normalized"],
            role=MemberRole(role_val),
            token_hash=r["token_hash"],
            status=InvitationStatus(status_val),
            invited_by_user_id=r["invited_by_user_id"],
            expires_at=r["expires_at"],
            accepted_at=r.get("accepted_at"),
            revoked_at=r.get("revoked_at"),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )

    def save(self, invitation: OrganizationInvitation, commit: bool = True) -> OrganizationInvitation:
        """Persist or update an invitation enforcing tenant boundaries."""
        org_id = self._validate_tenant(invitation.organization_id)
        invitation.organization_id = org_id
        invitation.validate()

        p = self._placeholder()
        role_str = invitation.role.value if isinstance(invitation.role, MemberRole) else str(invitation.role)
        status_str = invitation.status.value if isinstance(invitation.status, InvitationStatus) else str(invitation.status)
        now_iso = datetime.now(timezone.utc).isoformat()
        if not invitation.updated_at:
            invitation.updated_at = now_iso

        sql = f"""
        INSERT INTO organization_invitations (
            id, organization_id, email_normalized, role, token_hash,
            status, invited_by_user_id, expires_at, accepted_at, revoked_at,
            created_at, updated_at
        ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        ON CONFLICT(id) DO UPDATE SET
            role = EXCLUDED.role,
            status = EXCLUDED.status,
            accepted_at = EXCLUDED.accepted_at,
            revoked_at = EXCLUDED.revoked_at,
            updated_at = EXCLUDED.updated_at
        """
        self.db.execute(
            sql,
            (
                invitation.id,
                invitation.organization_id,
                invitation.email_normalized,
                role_str,
                invitation.token_hash,
                status_str,
                invitation.invited_by_user_id,
                invitation.expires_at,
                invitation.accepted_at,
                invitation.revoked_at,
                invitation.created_at,
                invitation.updated_at,
            ),
        )
        if commit:
            self._commit_if_not_in_tx()
        return invitation

    def get_by_id(self, org_id: str, invitation_id: str) -> Optional[OrganizationInvitation]:
        """Fetch invitation by ID strictly scoped to organization tenant boundary."""
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT * FROM organization_invitations WHERE organization_id = {p} AND id = {p}"
        rows = self.db.fetch_dicts(sql, (org_id, invitation_id))
        if not rows:
            return None
        return self._row_to_invitation(rows[0])

    def get_by_token_hash(self, token_hash: str) -> Optional[OrganizationInvitation]:
        """Fetch invitation by unique SHA-256 token hash (for acceptance/inspection)."""
        p = self._placeholder()
        sql = f"SELECT * FROM organization_invitations WHERE token_hash = {p}"
        rows = self.db.fetch_dicts(sql, (token_hash,))
        if not rows:
            return None
        return self._row_to_invitation(rows[0])

    def list_by_organization(
        self, org_id: str, status: Optional[InvitationStatus] = None
    ) -> List[OrganizationInvitation]:
        """List invitations for an organization, optionally filtered by status, ordered newest first."""
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        if status:
            status_str = status.value if isinstance(status, InvitationStatus) else str(status)
            sql = f"""
            SELECT * FROM organization_invitations
            WHERE organization_id = {p} AND status = {p}
            ORDER BY created_at DESC
            """
            rows = self.db.fetch_dicts(sql, (org_id, status_str))
        else:
            sql = f"""
            SELECT * FROM organization_invitations
            WHERE organization_id = {p}
            ORDER BY created_at DESC
            """
            rows = self.db.fetch_dicts(sql, (org_id,))
        return [self._row_to_invitation(r) for r in rows]

    def get_pending_by_email(
        self, org_id: str, email_normalized: str
    ) -> Optional[OrganizationInvitation]:
        """Fetch active pending invitation for an email in an organization."""
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        norm_email = email_normalized.strip().lower()
        sql = f"""
        SELECT * FROM organization_invitations
        WHERE organization_id = {p} AND email_normalized = {p} AND status = 'pending'
        ORDER BY created_at DESC LIMIT 1
        """
        rows = self.db.fetch_dicts(sql, (org_id, norm_email))
        if not rows:
            return None
        return self._row_to_invitation(rows[0])

    def update_status(
        self,
        invitation_id: str,
        status: InvitationStatus,
        accepted_at: Optional[str] = None,
        revoked_at: Optional[str] = None,
        commit: bool = True,
    ) -> bool:
        """Update invitation status and timestamps atomically."""
        p = self._placeholder()
        status_str = status.value if isinstance(status, InvitationStatus) else str(status)
        now_iso = datetime.now(timezone.utc).isoformat()
        sql = f"""
        UPDATE organization_invitations
        SET status = {p}, accepted_at = COALESCE({p}, accepted_at), revoked_at = COALESCE({p}, revoked_at), updated_at = {p}
        WHERE id = {p}
        """
        self.db.execute(sql, (status_str, accepted_at, revoked_at, now_iso, invitation_id))
        if commit:
            self._commit_if_not_in_tx()
        return True
