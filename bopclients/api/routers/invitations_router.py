"""Public and onboarding endpoints for Team Invitations (/api/v1/invitations)."""

import logging
from fastapi import APIRouter, Depends, status
from bopclients.api.dependencies import get_container, get_current_user
from bopclients.domain.auth.context import UserPrincipal
from bopclients.domain.enums import MemberRole
from bopclients.domain.exceptions import EntityNotFoundError
from bopclients.api.schemas.invitations import (
    InvitationPublicResponse,
    InvitationAcceptRequest,
    InvitationRegisterAcceptRequest,
    InvitationAcceptResponse,
)
from bopclients.runtime.container import RuntimeContainer

logger = logging.getLogger("bopclients.api.invitations")
router = APIRouter(prefix="/api/v1/invitations", tags=["Invitations"])


@router.get(
    "/{token}",
    response_model=InvitationPublicResponse,
    status_code=status.HTTP_200_OK,
    summary="Inspect invitation metadata by raw token (Public)",
)
async def get_invitation_by_token(
    token: str,
    container: RuntimeContainer = Depends(get_container),
) -> InvitationPublicResponse:
    """Inspect invitation details prior to accepting. Does not leak sensitive tokens or internal IDs."""
    invitation = container.invitation_service.get_invitation_by_token(token)
    org = container.org_repo.get_by_id(invitation.organization_id)
    if not org:
        raise EntityNotFoundError("Organization not found.")

    return InvitationPublicResponse(
        id=invitation.id,
        organization_name=org.name,
        organization_slug=org.slug,
        email=invitation.email_normalized,
        role=invitation.role.value if isinstance(invitation.role, MemberRole) else str(invitation.role),
        status=invitation.status.value,
        expires_at=invitation.expires_at,
        is_expired=invitation.is_expired(),
    )


@router.post(
    "/accept",
    response_model=InvitationAcceptResponse,
    status_code=status.HTTP_200_OK,
    summary="Accept team invitation for authenticated user",
)
async def accept_invitation(
    payload: InvitationAcceptRequest,
    current_user: UserPrincipal = Depends(get_current_user),
    container: RuntimeContainer = Depends(get_container),
) -> InvitationAcceptResponse:
    """Atomically accept an invitation for the logged-in user.

    Validates that current user's email matches the invitation email.
    """
    user = container.user_repo.get_by_id(current_user.user_id)
    if not user:
        raise EntityNotFoundError("Authenticated user not found.")

    invitation, member = container.invitation_service.accept_invitation(
        raw_token=payload.token,
        user=user,
    )

    org = container.org_repo.get_by_id(invitation.organization_id)
    org_name = org.name if org else ""
    org_slug = org.slug if org else ""

    return InvitationAcceptResponse(
        membership_id=member.id,
        organization_id=member.organization_id,
        organization_name=org_name,
        organization_slug=org_slug,
        user_id=member.user_id,
        role=member.role.value if isinstance(member.role, MemberRole) else str(member.role),
        accepted_at=invitation.accepted_at or "",
    )


@router.post(
    "/register-and-accept",
    response_model=InvitationAcceptResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register account and accept team invitation (Public)",
)
async def register_and_accept_invitation(
    payload: InvitationRegisterAcceptRequest,
    container: RuntimeContainer = Depends(get_container),
) -> InvitationAcceptResponse:
    """Create a new user account with invitation email and atomically accept the invitation."""
    invitation, member, authed_user, token_pair = container.invitation_service.register_and_accept(
        raw_token=payload.token,
        name=payload.name,
        password=payload.password,
        locale=payload.locale,
    )

    org = container.org_repo.get_by_id(invitation.organization_id)
    org_name = org.name if org else ""
    org_slug = org.slug if org else ""

    return InvitationAcceptResponse(
        membership_id=member.id,
        organization_id=member.organization_id,
        organization_name=org_name,
        organization_slug=org_slug,
        user_id=member.user_id,
        role=member.role.value if isinstance(member.role, MemberRole) else str(member.role),
        accepted_at=invitation.accepted_at or "",
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
    )
