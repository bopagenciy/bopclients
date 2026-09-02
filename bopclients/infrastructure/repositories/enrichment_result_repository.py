"""SQLite/Postgres repository implementation for EnrichmentResult snapshots (Tenant Isolated)."""

import json
from typing import Optional, List, Any
from bopclients.domain.enrichment_result import EnrichmentResult
from bopclients.domain.exceptions import TenantAccessError
from bopclients.application.interfaces.repositories import IEnrichmentResultRepository


class EnrichmentResultRepository(IEnrichmentResultRepository):
    """Repository managing latest enrichment snapshot persistence with tenant validation."""

    def __init__(self, db: Any):
        self.db = db

    def _placeholder(self) -> str:
        return "?" if getattr(self.db, "backend_name", "sqlite") == "sqlite" else "%s"

    def _validate_tenant(self, org_id: str) -> str:
        if not org_id or not org_id.strip():
            raise TenantAccessError("Missing or empty organization_id")
        return org_id

    def save(self, org_id: str, result: EnrichmentResult) -> EnrichmentResult:
        org_id = self._validate_tenant(org_id)
        result.organization_id = org_id
        result.validate()

        p = self._placeholder()
        data_json = json.dumps(result.data)

        # Check existing result to upsert latest snapshot, preserving last-known-good fields on timeout
        check_sql = f"SELECT * FROM enrichment_results WHERE organization_id = {p} AND prospect_id = {p} AND provider = {p}"
        existing_rows = self.db.fetch_dicts(check_sql, (org_id, result.prospect_id, result.provider))

        if existing_rows:
            old_row = existing_rows[0]
            old_data = json.loads(old_row["data"]) if isinstance(old_row["data"], str) else old_row["data"]

            # If current run is inconclusive (timeout/error) and has empty data, preserve last-known-good data
            if result.status in ("timeout", "dns_failure", "forbidden", "error") and old_data:
                merged_data = dict(old_data)
                merged_data.update(result.data)
                for key in ("technologies", "emails", "cms", "ssl_valid"):
                    if not result.data.get(key) and old_data.get(key):
                        merged_data[key] = old_data[key]
                result.data = merged_data

            data_json = json.dumps(result.data)

            sql = f"""
            UPDATE enrichment_results
            SET status = {p}, website_url = {p}, data = {p}, started_at = {p}, completed_at = {p}, updated_at = {p}
            WHERE organization_id = {p} AND prospect_id = {p} AND provider = {p}
            """
            self.db.execute(
                sql,
                (
                    result.status,
                    result.website_url,
                    data_json,
                    result.started_at,
                    result.completed_at,
                    result.updated_at,
                    org_id,
                    result.prospect_id,
                    result.provider,
                ),
            )
        else:
            sql = f"""
            INSERT INTO enrichment_results
            (id, organization_id, prospect_id, provider, status, website_url, data, started_at, completed_at, created_at, updated_at)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """
            self.db.execute(
                sql,
                (
                    result.id,
                    org_id,
                    result.prospect_id,
                    result.provider,
                    result.status,
                    result.website_url,
                    data_json,
                    result.started_at,
                    result.completed_at,
                    result.created_at,
                    result.updated_at,
                ),
            )
        self.db.commit()
        return result

    def get_latest(
        self, org_id: str, prospect_id: str, provider: str = "forge"
    ) -> Optional[EnrichmentResult]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT * FROM enrichment_results WHERE organization_id = {p} AND prospect_id = {p} AND provider = {p} LIMIT 1"
        rows = self.db.fetch_dicts(sql, (org_id, prospect_id, provider))
        if not rows:
            return None
        r = rows[0]
        data_dict = json.loads(r["data"]) if isinstance(r["data"], str) else r["data"]
        return EnrichmentResult(
            id=r["id"],
            organization_id=r["organization_id"],
            prospect_id=r["prospect_id"],
            provider=r["provider"],
            status=r["status"],
            website_url=r.get("website_url"),
            data=data_dict,
            started_at=r["started_at"],
            completed_at=r["completed_at"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
