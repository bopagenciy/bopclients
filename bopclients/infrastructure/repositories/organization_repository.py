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

    @staticmethod
    def _row_to_user(r: dict) -> User:
        return User(
            id=r["id"],
            email=r["email"],
            full_name=r["full_name"],
            password_hash=r.get("password_hash"),
            is_active=bool(r.get("is_active", True)),
            locale=r.get("locale") or "en",
            email_verified_at=r.get("email_verified_at"),
            created_at=r["created_at"],
        )

    def save(self, user: User, commit: bool = True) -> User:
        p = self._placeholder()
        user.email = user.email.strip().lower()
        user.validate()
        sql = f"""
        INSERT INTO users (id, email, full_name, password_hash, is_active, locale, email_verified_at, created_at)
        VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        ON CONFLICT(email) DO UPDATE SET
            full_name = EXCLUDED.full_name,
            password_hash = COALESCE(EXCLUDED.password_hash, users.password_hash),
            is_active = EXCLUDED.is_active,
            locale = EXCLUDED.locale,
            email_verified_at = COALESCE(EXCLUDED.email_verified_at, users.email_verified_at)
        """
        self.db.execute(
            sql,
            (user.id, user.email, user.full_name, user.password_hash, user.is_active, user.locale, user.email_verified_at, user.created_at),
        )
        if commit:
            self._commit_if_not_in_tx()
        return user

    def get_by_id(self, user_id: str) -> Optional[User]:
        p = self._placeholder()
        sql = f"SELECT id, email, full_name, password_hash, is_active, locale, email_verified_at, created_at FROM users WHERE id = {p}"
        rows = self.db.fetch_dicts(sql, (user_id,))
        if not rows:
            return None
        return self._row_to_user(rows[0])

    def get_by_email(self, email: str) -> Optional[User]:
        p = self._placeholder()
        normalized = email.strip().lower()
        sql = f"SELECT id, email, full_name, password_hash, is_active, locale, email_verified_at, created_at FROM users WHERE LOWER(email) = {p}"
        rows = self.db.fetch_dicts(sql, (normalized,))
        if not rows:
            return None
        return self._row_to_user(rows[0])


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
            role_val = r["role"].lower() if isinstance(r["role"], str) else r["role"]
            res.append(
                OrganizationMember(
                    id=r["id"],
                    organization_id=r["organization_id"],
                    user_id=r["user_id"],
                    role=MemberRole(role_val),
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
        role_val = r["role"].lower() if isinstance(r["role"], str) else r["role"]
        return OrganizationMember(
            id=r["id"],
            organization_id=r["organization_id"],
            user_id=r["user_id"],
            role=MemberRole(role_val),
            created_at=r["created_at"],
        )

    def remove_member(self, org_id: str, user_id: str, commit: bool = True) -> bool:
        """Remove a member from an organization. Does not delete global user."""
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"DELETE FROM organization_members WHERE organization_id = {p} AND user_id = {p}"
        self.db.execute(sql, (org_id, user_id))
        if commit:
            self._commit_if_not_in_tx()
        return True

    def get_user_memberships(self, user_id: str) -> List[dict]:
        """Fetch all organizations and roles for a specific user."""
        p = self._placeholder()
        sql = f"""
        SELECT
            m.id as membership_id,
            m.role,
            m.created_at as joined_at,
            o.id as organization_id,
            o.bop_organization_id,
            o.name as organization_name,
            o.slug as organization_slug,
            o.default_language,
            o.country
        FROM organization_members m
        JOIN organizations o ON m.organization_id = o.id
        WHERE m.user_id = {p}
        ORDER BY o.name ASC
        """
        return self.db.fetch_dicts(sql, (user_id,))
