"""Database repository for Organizations, Memberships, and Users."""

import uuid
from typing import List, Optional
from bopclients.domain.organization import Organization, OrganizationMember, OrganizationSettings
from bopclients.domain.user import User
from bopclients.domain.enums import MemberRole
from bopclients.application.interfaces.repositories import IOrganizationRepository, IUserRepository
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class UserRepository(BaseTenantRepository, IUserRepository):
    """Repository for User entity persistence."""

    def save(self, user: User, commit: bool = True) -> User:
        p = self._placeholder()
        sql = f"""
        INSERT INTO users (id, email, full_name, created_at)
        VALUES ({p}, {p}, {p}, {p})
        ON CONFLICT(email) DO UPDATE SET full_name = EXCLUDED.full_name
        """
        self.db.execute(sql, (user.id, user.email, user.full_name, user.created_at))
        if commit:
            self._commit_if_not_in_tx()
        return user

    def get_by_id(self, user_id: str) -> Optional[User]:
        p = self._placeholder()
        sql = f"SELECT id, email, full_name, created_at FROM users WHERE id = {p}"
        rows = self.db.fetch_dicts(sql, (user_id,))
        if not rows:
            return None
        r = rows[0]
        return User(id=r["id"], email=r["email"], full_name=r["full_name"], created_at=r["created_at"])

    def get_by_email(self, email: str) -> Optional[User]:
        p = self._placeholder()
        sql = f"SELECT id, email, full_name, created_at FROM users WHERE LOWER(email) = LOWER({p})"
        rows = self.db.fetch_dicts(sql, (email,))
        if not rows:
            return None
        r = rows[0]
        return User(id=r["id"], email=r["email"], full_name=r["full_name"], created_at=r["created_at"])


class OrganizationRepository(BaseTenantRepository, IOrganizationRepository):
    """Repository for Organization and Membership persistence."""

    @staticmethod
    def _row_to_org(r: dict) -> Organization:
        return Organization(
            id=r["id"],
            bop_organization_id=r.get("bop_organization_id") or "",
            name=r["name"],
            slug=r["slug"],
            description=r.get("description"),
            website=r.get("website"),
            country=r.get("country", "US"),
            default_language=r.get("default_language", "en"),
            timezone=r.get("timezone", "UTC"),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )

    def save(self, org: Organization, commit: bool = True) -> Organization:
        """Persist or update organization ensuring global identity immutability and transactional safety."""
        p = self._placeholder()
        existing = self.get_by_id(org.id)

        if existing is not None:
            # Immutability check: existing bop_organization_id cannot be changed
            if existing.bop_organization_id and org.bop_organization_id != existing.bop_organization_id:
                raise ValueError(
                    f"Cannot mutate immutable bop_organization_id on organization '{org.id}': "
                    f"existing='{existing.bop_organization_id}', attempted='{org.bop_organization_id}'"
                )

            # Update fields omitting bop_organization_id from SET clause
            sql = f"""
            UPDATE organizations
            SET name = {p}, slug = {p}, description = {p}, website = {p},
                country = {p}, default_language = {p}, timezone = {p}, updated_at = {p}
            WHERE id = {p}
            """
            self.db.execute(
                sql,
                (
                    org.name,
                    org.slug,
                    org.description,
                    org.website,
                    org.country,
                    org.default_language,
                    org.timezone,
                    org.updated_at,
                    org.id,
                ),
            )
        else:
            # Insert new organization requiring/generating bop_organization_id
            bop_org_id = org.bop_organization_id or str(uuid.uuid4())
            org.bop_organization_id = bop_org_id

            sql = f"""
            INSERT INTO organizations (
                id, bop_organization_id, name, slug, description, website,
                country, default_language, timezone, created_at, updated_at
            ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """
            self.db.execute(
                sql,
                (
                    org.id,
                    bop_org_id,
                    org.name,
                    org.slug,
                    org.description,
                    org.website,
                    org.country,
                    org.default_language,
                    org.timezone,
                    org.created_at,
                    org.updated_at,
                ),
            )

        if commit:
            self._commit_if_not_in_tx()
        return org

    def get_by_id(self, org_id: str) -> Optional[Organization]:
        p = self._placeholder()
        sql = f"SELECT * FROM organizations WHERE id = {p}"
        rows = self.db.fetch_dicts(sql, (org_id,))
        if not rows:
            return None
        return self._row_to_org(rows[0])

    def get_by_slug(self, slug: str) -> Optional[Organization]:
        p = self._placeholder()
        sql = f"SELECT * FROM organizations WHERE slug = {p}"
        rows = self.db.fetch_dicts(sql, (slug,))
        if not rows:
            return None
        return self._row_to_org(rows[0])

    def get_by_bop_organization_id(self, bop_org_id: str) -> Optional[Organization]:
        p = self._placeholder()
        sql = f"SELECT * FROM organizations WHERE bop_organization_id = {p}"
        rows = self.db.fetch_dicts(sql, (bop_org_id,))
        if not rows:
            return None
        return self._row_to_org(rows[0])

    def add_member(self, member: OrganizationMember, commit: bool = True) -> OrganizationMember:
        org_id = self._validate_tenant(member.organization_id)
        p = self._placeholder()
        sql = f"""
        INSERT INTO organization_members (id, organization_id, user_id, role, created_at)
        VALUES ({p}, {p}, {p}, {p}, {p})
        ON CONFLICT(organization_id, user_id) DO UPDATE SET role = EXCLUDED.role
        """
        role_str = member.role.value if isinstance(member.role, MemberRole) else str(member.role)
        self.db.execute(sql, (member.id, org_id, member.user_id, role_str, member.created_at))
        if commit:
            self._commit_if_not_in_tx()
        return member

    def get_members(self, org_id: str) -> List[OrganizationMember]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT id, organization_id, user_id, role, created_at FROM organization_members WHERE organization_id = {p}"
        rows = self.db.fetch_dicts(sql, (org_id,))
        res = []
        for r in rows:
            res.append(
                OrganizationMember(
                    id=r["id"],
                    organization_id=r["organization_id"],
                    user_id=r["user_id"],
                    role=MemberRole(r["role"]),
                    created_at=r["created_at"],
                )
            )
        return res

    def get_member(self, org_id: str, user_id: str) -> Optional[OrganizationMember]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT id, organization_id, user_id, role, created_at FROM organization_members WHERE organization_id = {p} AND user_id = {p}"
        rows = self.db.fetch_dicts(sql, (org_id, user_id))
        if not rows:
            return None
        r = rows[0]
        return OrganizationMember(
            id=r["id"],
            organization_id=r["organization_id"],
            user_id=r["user_id"],
            role=MemberRole(r["role"]),
            created_at=r["created_at"],
        )
