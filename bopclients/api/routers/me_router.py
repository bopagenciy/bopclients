"""User account and preferences endpoints (/api/v1/me)."""

from typing import List
from fastapi import APIRouter, Depends, status
from bopclients.api.schemas.auth import (
    UserResponse,
    UserPreferencesUpdate,
    UserOrganizationsResponse,
    UserOrganizationItem,
)
from bopclients.api.dependencies import get_current_user, get_container
from bopclients.domain.auth.context import UserPrincipal
from bopclients.runtime.container import RuntimeContainer
from bopclients.domain.user import SUPPORTED_LOCALES

router = APIRouter(prefix="/api/v1/me", tags=["User Profile"])


@router.get(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user profile",
)
async def get_my_profile(
    current_user: UserPrincipal = Depends(get_current_user),
    container: RuntimeContainer = Depends(get_container),
) -> UserResponse:
    user = container.user_repo.get_by_id(current_user.user_id)
    memberships = container.org_repo.get_user_memberships(current_user.user_id)
    org_list = [
        {
            "id": m["organization_id"],
            "bop_organization_id": m["bop_organization_id"],
            "name": m["organization_name"],
            "slug": m["organization_slug"],
            "role": m["role"],
        }
        for m in memberships
    ]
    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        name=user.full_name,
        locale=user.locale,
        is_active=user.is_active,
        email_verified_at=user.email_verified_at,
        is_verified=user.is_verified,
        created_at=user.created_at,
        organizations=org_list,
    )


@router.get(
    "/organizations",
    response_model=UserOrganizationsResponse,
    status_code=status.HTTP_200_OK,
    summary="List organizations current user belongs to",
)
async def get_my_organizations(
    current_user: UserPrincipal = Depends(get_current_user),
    container: RuntimeContainer = Depends(get_container),
) -> UserOrganizationsResponse:
    memberships = container.org_repo.get_user_memberships(current_user.user_id)
    items = [
        UserOrganizationItem(
            organization_id=m["organization_id"],
            bop_organization_id=m["bop_organization_id"],
            organization_name=m["organization_name"],
            organization_slug=m["organization_slug"],
            role=m["role"],
            default_language=m["default_language"],
            country=m["country"],
            joined_at=m["joined_at"],
        )
        for m in memberships
    ]
    return UserOrganizationsResponse(items=items)


@router.get(
    "/memberships",
    response_model=List[UserOrganizationItem],
    status_code=status.HTTP_200_OK,
    summary="List memberships current user belongs to",
)
async def get_my_memberships(
    current_user: UserPrincipal = Depends(get_current_user),
    container: RuntimeContainer = Depends(get_container),
) -> List[UserOrganizationItem]:
    memberships = container.org_repo.get_user_memberships(current_user.user_id)
    return [
        UserOrganizationItem(
            organization_id=m["organization_id"],
            bop_organization_id=m["bop_organization_id"],
            organization_name=m["organization_name"],
            organization_slug=m["organization_slug"],
            role=m["role"],
            default_language=m["default_language"],
            country=m["country"],
            joined_at=m["joined_at"],
        )
        for m in memberships
    ]


@router.patch(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update user profile",
)
@router.patch(
    "/preferences",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update user preferences",
)
async def update_my_preferences(
    payload: UserPreferencesUpdate,
    current_user: UserPrincipal = Depends(get_current_user),
    container: RuntimeContainer = Depends(get_container),
) -> UserResponse:
    user = container.user_repo.get_by_id(current_user.user_id)
    if payload.locale is not None:
        clean_locale = payload.locale.strip().lower()
        if clean_locale not in SUPPORTED_LOCALES:
            raise ValueError(f"Invalid locale '{payload.locale}'. Must be one of {sorted(SUPPORTED_LOCALES)}")
        user.locale = clean_locale

    name_val = payload.full_name or payload.name
    if name_val is not None and name_val.strip():
        user.full_name = name_val.strip()

    container.user_repo.save(user)

    memberships = container.org_repo.get_user_memberships(current_user.user_id)
    org_list = [
        {
            "id": m["organization_id"],
            "bop_organization_id": m["bop_organization_id"],
            "name": m["organization_name"],
            "slug": m["organization_slug"],
            "role": m["role"],
        }
        for m in memberships
    ]

    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        name=user.full_name,
        locale=user.locale,
        is_active=user.is_active,
        created_at=user.created_at,
        organizations=org_list,
    )
