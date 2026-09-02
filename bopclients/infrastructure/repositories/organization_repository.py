"""Database repository for Organizations, Memberships, and Users."""

from typing import List, Optional
from bopclients.domain.organization import Organization, OrganizationMember, OrganizationSettings
from bopclients.domain.user import User
from bopclients.domain.enums import MemberRole
from bopclients.application.interfaces.repositories import IOrganizationRepository, IUserRepository
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class UserRepository(BaseTenantRepository, IUserRepository):
    """Repository for User entity persistence."""

    def save(self, user: User) -> User:
        p = self._placeholder()
        sql = f"""
        INSERT INTO users (id, email, full_name, created_at)
        VALUES ({p}, {p}, {p}, {p})
        ON CONFLICT(email) DO UPDATE SET full_name = EXCLUDED.full_name
        """
        self.db.execute(sql, (user.id, user.email, user.full_name, user.created_at))
        self.db.commit()
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

    def save(self, org: Organization) -> Organization:
        p = self._placeholder()
        sql = f"""
        INSERT INTO organizations (id, name, slug, description, website, country, default_language, timezone, created_at, updated_at)
        VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        self.db.execute(
            sql,
            (
                org.id,
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
        self.db.commit()
        return org

    def get_by_id(self, org_id: str) -> Optional[Organization]:
        p = self._placeholder()
        sql = f"SELECT * FROM organizations WHERE id = {p}"
        rows = self.db.fetch_dicts(sql, (org_id,))
        if not rows:
            return None
        r = rows[0]
        return Organization(
            id=r["id"],
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

    def get_by_slug(self, slug: str) -> Optional[Organization]:
        p = self._placeholder()
        sql = f"SELECT * FROM organizations WHERE slug = {p}"
        rows = self.db.fetch_dicts(sql, (slug,))
        if not rows:
            return None
        r = rows[0]
        return Organization(
            id=r["id"],
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

    def add_member(self, member: OrganizationMember) -> OrganizationMember:
        org_id = self._validate_tenant(member.organization_id)
        p = self._placeholder()
        sql = f"""
        INSERT INTO organization_members (id, organization_id, user_id, role, created_at)
        VALUES ({p}, {p}, {p}, {p}, {p})
        ON CONFLICT(organization_id, user_id) DO UPDATE SET role = EXCLUDED.role
        """
        role_str = member.role.value if isinstance(member.role, MemberRole) else str(member.role)
        self.db.execute(sql, (member.id, org_id, member.user_id, role_str, member.created_at))
        self.db.commit()
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
