"""Authentication and user account schemas."""

from typing import Optional, List, Any
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """User authentication request body."""

    email: str = Field(description="User email address")
    password: str = Field(description="Plaintext password to authenticate")


class UserProfileItem(BaseModel):
    """User summary item within login response."""
    id: str
    email: str
    name: str
    locale: str = "en"


class LoginResponse(BaseModel):
    """Successful authentication response containing JWT and user profile."""

    access_token: str = Field(description="Short-lived HMAC-SHA256 JWT access token")
    token_type: str = Field(default="Bearer", description="Authorization scheme type")
    expires_in: int = Field(description="Access token lifespan in seconds")
    refresh_token: Optional[str] = Field(default=None, description="Longer-lived session token")
    user_id: str
    email: str
    full_name: str
    locale: str = Field(default="en", description="User preferred product language code (en, es)")
    user: Optional[UserProfileItem] = None


class RefreshTokenRequest(BaseModel):
    """Token refresh request."""

    refresh_token: str = Field(description="Opaque session refresh token")


class LogoutResponse(BaseModel):
    """Logout confirmation response."""

    success: bool = True
    message: str = "Session successfully terminated."


class UserResponse(BaseModel):
    """Authenticated user profile response."""

    id: str
    email: str
    full_name: str
    name: Optional[str] = None
    locale: str
    is_active: bool
    created_at: str
    organizations: Optional[List[Any]] = None


class UserPreferencesUpdate(BaseModel):
    """User preferences update request body."""

    locale: Optional[str] = Field(default=None, description="Preferred UI language code: 'en' or 'es'")
    full_name: Optional[str] = Field(default=None, description="User display name")
    name: Optional[str] = Field(default=None, description="Alias for full_name")


class UserOrganizationItem(BaseModel):
    """Organization membership summary for user organizations list."""

    organization_id: str
    bop_organization_id: str
    organization_name: str
    organization_slug: str
    role: str
    default_language: str
    country: str
    joined_at: str


class UserOrganizationsResponse(BaseModel):
    """List of organizations accessible to the current user."""

    items: List[UserOrganizationItem]
