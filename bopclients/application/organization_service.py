"""Organization application use cases."""

from typing import List, Optional
from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.domain.user import User
from bopclients.domain.enums import MemberRole
from bopclients.domain.exceptions import TenantAccessError
from bopclients.application.dtos import CreateOrganizationCommand, CreateServiceCommand
from bopclients.application.interfaces.repositories import (
    IOrganizationRepository,
    IUserRepository,
    IServiceRepository,
)
from bopclients.domain.service import Service


class OrganizationService:
    """Use case handler for Organizations, Users, Memberships, and Services."""

    def __init__(
        self,
        org_repo: IOrganizationRepository,
        user_repo: IUserRepository,
        service_repo: IServiceRepository,
    ):
        self.org_repo = org_repo
        self.user_repo = user_repo
        self.service_repo = service_repo

    def create_organization(self, cmd: CreateOrganizationCommand) -> Organization:
        """Create a new Organization and assign the initial Owner."""
        # 1. Create or retrieve owner user
        owner_user = self.user_repo.get_by_email(cmd.owner_email)
        if not owner_user:
            owner_user = User(email=cmd.owner_email, full_name=cmd.owner_name or cmd.owner_email)
            owner_user.validate()
            self.user_repo.save(owner_user)

        # 2. Create organization
        org = Organization(
            name=cmd.name,
            slug=cmd.slug,
            description=cmd.description,
            website=cmd.website,
            country=cmd.country,
            default_language=cmd.default_language,
            timezone=cmd.timezone,
        )
        org.validate()
        saved_org = self.org_repo.save(org)

        # 3. Add owner membership
        member = OrganizationMember(
            organization_id=saved_org.id,
            user_id=owner_user.id,
            role=MemberRole.OWNER,
        )
        self.org_repo.add_member(member)

        return saved_org

    def add_member(
        self, requester_user_id: str, org_id: str, target_email: str, target_name: str, role: MemberRole
    ) -> OrganizationMember:
        """Add a user to an organization with a specific role."""
        requester_membership = self.org_repo.get_member(org_id, requester_user_id)
        if not requester_membership or requester_membership.role not in (MemberRole.OWNER, MemberRole.ADMIN):
            raise TenantAccessError("Only Owners or Admins can add organization members.")

        target_user = self.user_repo.get_by_email(target_email)
        if not target_user:
            target_user = User(email=target_email, full_name=target_name or target_email)
            self.user_repo.save(target_user)

        new_member = OrganizationMember(
            organization_id=org_id,
            user_id=target_user.id,
            role=role,
        )
        return self.org_repo.add_member(new_member)

    def add_service(self, cmd: CreateServiceCommand) -> Service:
        """Add a service offering to an organization."""
        service = Service(
            organization_id=cmd.organization_id,
            name=cmd.name,
            description=cmd.description,
            category=cmd.category,
            active=cmd.active,
        )
        service.validate()
        return self.service_repo.save(cmd.organization_id, service)

    def list_services(self, org_id: str) -> List[Service]:
        """List active services for an organization."""
        return self.service_repo.list_by_organization(org_id)
