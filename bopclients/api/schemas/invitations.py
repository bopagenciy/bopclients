"""Pydantic schemas for Team Invitations API."""

from typing import Optional
from pydantic import BaseModel, Field


class InvitationCreateRequest(BaseModel):
    """Payload for creating a new team invitation."""

    email: str = Field(description="Invited user email address")
    role: str = Field(default="member", description="Assigned role: admin, member, or viewer")


class InvitationResponse(BaseModel):
    """Detailed invitation envelope returned to tenant administrators."""

    id: str
    organization_id: str
    email: str
    role: str
    status: str
    invited_by_user_id: str
    expires_at: str
    created_at: str
    accepted_at: Optional[str] = None
    revoked_at: Optional[str] = None
    delivery_status: str = Field(
        default="not_configured",
        description="Delivery status of the invitation email (e.g. not_configured, pending, delivered, failed).",
    )
    raw_token: Optional[str] = Field(
        default=None,
        description="Dev/test only raw token. Never exposed in production (None by default).",
    )
    invite_url: Optional[str] = Field(
        default=None,
        description="Dev/test only invite URL. Never exposed in production (None by default).",
    )


class InvitationPublicResponse(BaseModel):
    """Sanitized invitation metadata for public acceptance page."""

    id: str
    organization_name: str
    organization_slug: str
    email: str
    role: str
    status: str
    expires_at: str
    is_expired: bool


class InvitationAcceptRequest(BaseModel):
    """Payload for accepting an invitation by authenticated user."""

    token: str = Field(description="Raw invitation token")


class InvitationRegisterAcceptRequest(BaseModel):
    """Payload for registering and accepting an invitation simultaneously."""

    token: str = Field(description="Raw invitation token")
    name: str = Field(min_length=1, max_length=255, description="Full name of user")
    password: str = Field(min_length=8, description="User password (min 8 chars)")
    locale: str = Field(default="en", description="Preferred locale ('en' or 'es')")


class InvitationAcceptResponse(BaseModel):
    """Response returned upon successful invitation acceptance."""

    membership_id: str
    organization_id: str
    organization_name: str
    organization_slug: str
    user_id: str
    role: str
    accepted_at: str
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: Optional[str] = None
    expires_in: Optional[int] = None
