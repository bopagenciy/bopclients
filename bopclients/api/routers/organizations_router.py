"""Organization and tenant management endpoints (/api/v1/organizations)."""

import uuid
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, status
from bopclients.api.schemas.organizations import (
    OrganizationResponse,
    OrganizationCreate,
    OrganizationUpdate,
    MemberResponse,
    MemberCreateRequest,
    MemberRoleUpdate,
)
from bopclients.api.dependencies import get_tenant_context, get_container, require_permission, get_current_user
from bopclients.domain.auth.context import TenantContext, UserPrincipal
from bopclients.domain.auth.policy import Permission, AuthorizationPolicy
from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.domain.enums import MemberRole
from bopclients.domain.exceptions import EntityNotFoundError, ValidationError
from bopclients.runtime.container import RuntimeContainer

router = APIRouter(prefix="/api/v1/organizations", tags=["Organizations"])


@router.get(
    "/current",
    response_model=OrganizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get active organization profile",
)
async def get_current_organization(
    tenant: TenantContext = Depends(require_permission(Permission.ORGANIZATION_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> OrganizationResponse:
    org = container.org_repo.get_by_id(tenant.organization_id)
    if not org:
        raise EntityNotFoundError("Organization not found.")

    return OrganizationResponse(
        id=org.id,
        bop_organization_id=org.bop_organization_id,
        name=org.name,
        slug=org.slug,
        description=org.description,
        website=org.website,
        country=org.country,
        default_language=org.default_language,
        timezone=org.timezone,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )


@router.patch(
    "/current",
    response_model=OrganizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update active organization settings",
)
async def update_current_organization(
    payload: OrganizationUpdate,
    tenant: TenantContext = Depends(require_permission(Permission.ORGANIZATION_MANAGE)),
    container: RuntimeContainer = Depends(get_container),
) -> OrganizationResponse:
    org = container.org_repo.get_by_id(tenant.organization_id)
    if not org:
        raise EntityNotFoundError("Organization not found.")

    if payload.name is not None:
        org.name = payload.name
    if payload.description is not None:
        org.description = payload.description
    if payload.website is not None:
        org.website = payload.website
    if payload.country is not None:
        org.country = payload.country
    if payload.default_language is not None:
        org.default_language = payload.default_language
    if payload.timezone is not None:
        org.timezone = payload.timezone

    org.updated_at = datetime.now(timezone.utc).isoformat()
    updated = container.org_repo.save(org)

    return OrganizationResponse(
        id=updated.id,
        bop_organization_id=updated.bop_organization_id,
        name=updated.name,
        slug=updated.slug,
        description=updated.description,
        website=updated.website,
        country=updated.country,
        default_language=updated.default_language,
        timezone=updated.timezone,
        created_at=updated.created_at,
        updated_at=updated.updated_at,
    )


@router.get(
    "/current/members",
    response_model=List[MemberResponse],
    status_code=status.HTTP_200_OK,
    summary="List members in active organization",
)
async def list_organization_members(
    tenant: TenantContext = Depends(require_permission(Permission.MEMBERS_READ)),
    container: RuntimeContainer = Depends(get_container),
) -> List[MemberResponse]:
    members = container.org_repo.get_members(tenant.organization_id)
    res = []
    for m in members:
        user = container.user_repo.get_by_id(m.user_id)
        res.append(
            MemberResponse(
                id=m.id,
                organization_id=m.organization_id,
                user_id=m.user_id,
                role=m.role.value if isinstance(m.role, MemberRole) else str(m.role),
                created_at=m.created_at,
                email=user.email if user else None,
                full_name=user.full_name if user else None,
            )
        )
    return res


@router.post(
    "/current/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add user to active organization",
)
async def add_organization_member(
    payload: MemberCreateRequest,
    tenant: TenantContext = Depends(require_permission(Permission.MEMBERS_MANAGE)),
    container: RuntimeContainer = Depends(get_container),
) -> MemberResponse:
    user = None
    if payload.user_id:
        user = container.user_repo.get_by_id(payload.user_id)
    elif payload.email:
        user = container.user_repo.get_by_email(payload.email)

    if not user:
        raise EntityNotFoundError(f"Target user not found.")

    normalized_role = AuthorizationPolicy.normalize_role(payload.role)

    member = OrganizationMember(
        id=str(uuid.uuid4()),
        organization_id=tenant.organization_id,
        user_id=user.id,
        role=normalized_role,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    saved = container.org_repo.add_member(member)

    return MemberResponse(
        id=saved.id,
        organization_id=saved.organization_id,
        user_id=saved.user_id,
        role=saved.role.value if isinstance(saved.role, MemberRole) else str(saved.role),
        created_at=saved.created_at,
        email=user.email,
        full_name=user.full_name,
    )


@router.patch(
    "/current/members/{user_id}",
    response_model=MemberResponse,
    status_code=status.HTTP_200_OK,
    summary="Update organization member role",
)
async def update_member_role(
    user_id: str,
    payload: MemberRoleUpdate,
    tenant: TenantContext = Depends(require_permission(Permission.MEMBERS_MANAGE)),
    container: RuntimeContainer = Depends(get_container),
) -> MemberResponse:
    existing = container.org_repo.get_member(tenant.organization_id, user_id)
    if not existing:
        raise EntityNotFoundError(f"Member '{user_id}' not found in organization.")

    normalized_role = AuthorizationPolicy.normalize_role(payload.role)
    existing.role = normalized_role
    saved = container.org_repo.add_member(existing)

    user = container.user_repo.get_by_id(user_id)

    return MemberResponse(
        id=saved.id,
        organization_id=saved.organization_id,
        user_id=saved.user_id,
        role=saved.role.value if isinstance(saved.role, MemberRole) else str(saved.role),
        created_at=saved.created_at,
        email=user.email if user else None,
        full_name=user.full_name if user else None,
    )


@router.get(
    "",
    status_code=status.HTTP_200_OK,
    summary="List organizations accessible to current user",
)
async def list_user_organizations(
    current_user: UserPrincipal = Depends(get_current_user),
    container: RuntimeContainer = Depends(get_container),
):
    memberships = container.org_repo.get_user_memberships(current_user.user_id)
    items = []
    for m in memberships:
        items.append(
            {
                "id": m["organization_id"],
                "bop_organization_id": m["bop_organization_id"],
                "name": m["organization_name"],
                "slug": m["organization_slug"],
                "role": m["role"],
                "default_language": m["default_language"],
                "country": m["country"],
                "joined_at": m["joined_at"],
            }
        )
    return {"items": items}


@router.get(
    "/{org_id}",
    response_model=OrganizationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get organization details by ID (membership required)",
)
async def get_organization_by_id(
    org_id: str,
    current_user: UserPrincipal = Depends(get_current_user),
    container: RuntimeContainer = Depends(get_container),
) -> OrganizationResponse:
    # Check if user is a member of this org to prevent cross-tenant enumeration
    membership = container.org_repo.get_member(org_id, current_user.user_id)
    if not membership:
        raise EntityNotFoundError("Organization not found.")

    org = container.org_repo.get_by_id(org_id)
    if not org:
        raise EntityNotFoundError("Organization not found.")

    return OrganizationResponse(
        id=org.id,
        bop_organization_id=org.bop_organization_id,
        name=org.name,
        slug=org.slug,
        description=org.description,
        website=org.website,
        country=org.country,
        default_language=org.default_language,
        timezone=org.timezone,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )
