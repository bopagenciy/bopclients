"""Organization tenant and membership schemas."""

from typing import Optional, List
from pydantic import BaseModel, Field


class OrganizationResponse(BaseModel):
    """Organization tenant profile response."""

    id: str
    bop_organization_id: str
    name: str
    slug: str
    description: Optional[str] = None
    website: Optional[str] = None
    country: str
    default_language: str
    timezone: str
    created_at: str
    updated_at: str


class OrganizationCreate(BaseModel):
    """Organization tenant creation request body."""

    name: str = Field(description="Organization display name")
    slug: Optional[str] = Field(default=None, description="URL-safe unique identifier")
    description: Optional[str] = Field(default=None)
    website: Optional[str] = Field(default=None)
    country: str = Field(default="US")
    default_language: str = Field(default="en")
    timezone: str = Field(default="UTC")


class OrganizationUpdate(BaseModel):
    """Organization tenant settings update request body."""

    name: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    country: Optional[str] = None
    default_language: Optional[str] = None
    timezone: Optional[str] = None


class MemberResponse(BaseModel):
    """Organization member response."""

    id: str
    organization_id: str
    user_id: str
    role: str
    created_at: str
    email: Optional[str] = None
    full_name: Optional[str] = None


class MemberCreateRequest(BaseModel):
    """Add existing user or invite to organization request body."""

    user_id: Optional[str] = None
    email: Optional[str] = None
    role: str = Field(default="member", description="Member role: owner, admin, member, viewer")


class MemberRoleUpdate(BaseModel):
    """Update existing member role request body."""

    role: str = Field(description="Updated role: owner, admin, member, viewer")
