"""SQLite/Postgres repository implementation for ProspectIntelligence snapshots (Tenant Isolated)."""

import json
from typing import Optional, Any
from bopclients.domain.prospect_intelligence import ProspectIntelligence
from bopclients.domain.exceptions import TenantAccessError
from bopclients.application.interfaces.repositories import IProspectIntelligenceRepository


class ProspectIntelligenceRepository(IProspectIntelligenceRepository):
    """Repository managing latest prospect intelligence snapshot persistence with tenant validation."""

    def __init__(self, db: Any):
        self.db = db

    def _placeholder(self) -> str:
        return "?" if getattr(self.db, "backend_name", "sqlite") == "sqlite" else "%s"

    def _validate_tenant(self, org_id: str) -> str:
        if not org_id or not org_id.strip():
            raise TenantAccessError("Missing or empty organization_id")
        return org_id

    def save(self, org_id: str, intelligence: ProspectIntelligence) -> ProspectIntelligence:
        org_id = self._validate_tenant(org_id)
        intelligence.organization_id = org_id
        intelligence.validate()

        p = self._placeholder()
        data_json = json.dumps(intelligence.data)

        # Check existing result to upsert latest intelligence snapshot
        check_sql = f"SELECT id FROM prospect_intelligence WHERE organization_id = {p} AND prospect_id = {p} AND provider = {p}"
        existing = self.db.fetch_dicts(check_sql, (org_id, intelligence.prospect_id, intelligence.provider))

        if existing:
            sql = f"""
            UPDATE prospect_intelligence
            SET research_version = {p}, confidence = {p}, data = {p}, created_at = {p}, updated_at = {p}
            WHERE organization_id = {p} AND prospect_id = {p} AND provider = {p}
            """
            self.db.execute(
                sql,
                (
                    intelligence.research_version,
                    intelligence.confidence,
                    data_json,
                    intelligence.created_at,
                    intelligence.updated_at,
                    org_id,
                    intelligence.prospect_id,
                    intelligence.provider,
                ),
            )
        else:
            sql = f"""
            INSERT INTO prospect_intelligence
            (id, organization_id, prospect_id, provider, research_version, confidence, data, created_at, updated_at)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """
            self.db.execute(
                sql,
                (
                    intelligence.id,
                    org_id,
                    intelligence.prospect_id,
                    intelligence.provider,
                    intelligence.research_version,
                    intelligence.confidence,
                    data_json,
                    intelligence.created_at,
                    intelligence.updated_at,
                ),
            )
        self.db.commit()
        return intelligence

    def get_latest(
        self, org_id: str, prospect_id: str, provider: str = "deterministic"
    ) -> Optional[ProspectIntelligence]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT * FROM prospect_intelligence WHERE organization_id = {p} AND prospect_id = {p} AND provider = {p} LIMIT 1"
        rows = self.db.fetch_dicts(sql, (org_id, prospect_id, provider))
        if not rows:
            return None
        r = rows[0]
        data_dict = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        return ProspectIntelligence(
            id=r["id"],
            organization_id=r["organization_id"],
            prospect_id=r["prospect_id"],
            provider=r["provider"],
            research_version=r["research_version"],
            confidence=float(r["confidence"]),
            data=data_dict,
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
