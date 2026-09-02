"""Database repository for Services (Tenant Isolated)."""

from typing import List, Optional
from bopclients.domain.service import Service
from bopclients.application.interfaces.repositories import IServiceRepository
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class ServiceRepository(BaseTenantRepository, IServiceRepository):
    """Repository for managing tenant Service offerings."""

    def save(self, org_id: str, service: Service) -> Service:
        org_id = self._validate_tenant(org_id)
        service.organization_id = org_id
        p = self._placeholder()
        sql = f"""
        INSERT INTO services (id, organization_id, name, description, category, active, created_at)
        VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        self.db.execute(
            sql,
            (
                service.id,
                org_id,
                service.name,
                service.description,
                service.category,
                1 if service.active else 0,
                service.created_at,
            ),
        )
        self.db.commit()
        return service

    def get_by_id(self, org_id: str, service_id: str) -> Optional[Service]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT * FROM services WHERE organization_id = {p} AND id = {p}"
        rows = self.db.fetch_dicts(sql, (org_id, service_id))
        if not rows:
            return None
        r = rows[0]
        return Service(
            id=r["id"],
            organization_id=r["organization_id"],
            name=r["name"],
            description=r.get("description", ""),
            category=r["category"],
            active=bool(r.get("active", 1)),
            created_at=r["created_at"],
        )

    def list_by_organization(self, org_id: str) -> List[Service]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT * FROM services WHERE organization_id = {p} ORDER BY created_at DESC"
        rows = self.db.fetch_dicts(sql, (org_id,))
        res = []
        for r in rows:
            res.append(
                Service(
                    id=r["id"],
                    organization_id=r["organization_id"],
                    name=r["name"],
                    description=r.get("description", ""),
                    category=r["category"],
                    active=bool(r.get("active", 1)),
                    created_at=r["created_at"],
                )
            )
        return res
