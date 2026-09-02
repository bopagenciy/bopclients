"""SignalObservationRepository managing signal_observations persistence with multi-tenant security."""

import json
from typing import Optional, List, Any
from datetime import datetime, timezone
from bopclients.domain.exceptions import TenantAccessError
from bopclients.domain.signal_observation import PublicSignalObservation
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class SignalObservationRepository(BaseTenantRepository):
    """Repository managing signal_observations table with complete tenant isolation."""

    def save(self, organization_id: str, observation: PublicSignalObservation) -> PublicSignalObservation:
        """Save or update signal observation idempotently per (org_id, prospect_id, provider, fingerprint)."""
        organization_id = self._validate_tenant(organization_id)
        observation.organization_id = organization_id
        observation.validate()

        now = datetime.now(timezone.utc).isoformat()
        p = self._placeholder()
        ev_json = json.dumps(observation.evidence) if observation.evidence else None
        meta_json = json.dumps(observation.raw_metadata) if observation.raw_metadata else None

        # Check existing row by fingerprint for tenant
        check_sql = f"""
            SELECT id, first_seen_at FROM signal_observations
            WHERE organization_id = {p} AND prospect_id = {p} AND provider = {p} AND fingerprint = {p}
        """
        rows = self.db.fetch_dicts(check_sql, (organization_id, observation.prospect_id, observation.provider, observation.fingerprint))

        if rows:
            old_id = rows[0]["id"]
            sql_update = f"""
                UPDATE signal_observations SET
                    last_seen_at = {p},
                    confidence = {p},
                    evidence = {p},
                    raw_metadata = {p}
                WHERE organization_id = {p} AND id = {p}
            """
            self.db.execute(sql_update, (now, observation.confidence, ev_json, meta_json, organization_id, old_id))
            observation.id = old_id
            observation.last_seen_at = now
            observation.first_seen_at = rows[0]["first_seen_at"]
        else:
            sql_insert = f"""
                INSERT INTO signal_observations (
                    id, organization_id, prospect_id, provider, signal_type, category,
                    intent_strength, source_type, source_url, external_id, confidence,
                    evidence, raw_metadata, fingerprint, published_at, first_seen_at,
                    last_seen_at, created_at
                ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """
            self.db.execute(
                sql_insert,
                (
                    observation.id,
                    organization_id,
                    observation.prospect_id,
                    observation.provider,
                    observation.signal_type,
                    observation.category,
                    observation.intent_strength,
                    observation.source_type,
                    observation.source_url,
                    observation.external_id,
                    observation.confidence,
                    ev_json,
                    meta_json,
                    observation.fingerprint,
                    observation.published_at,
                    observation.first_seen_at,
                    now,
                    now,
                ),
            )
            observation.last_seen_at = now
            observation.created_at = now

        self.db.commit()
        return observation

    def list_for_prospect(
        self, organization_id: str, prospect_id: str, limit: int = 100
    ) -> List[PublicSignalObservation]:
        """Fetch observations for a prospect strictly isolated to organization_id."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()

        # Cross-tenant ownership check
        sql_check = f"SELECT organization_id FROM prospects WHERE id = {p}"
        p_rows = self.db.fetch_dicts(sql_check, (prospect_id,))
        if p_rows and p_rows[0]["organization_id"] != organization_id:
            raise TenantAccessError(f"Cross-tenant observation access rejected for prospect '{prospect_id}'")

        sql = f"""
            SELECT * FROM signal_observations
            WHERE organization_id = {p} AND prospect_id = {p}
            ORDER BY last_seen_at DESC LIMIT {limit}
        """
        rows = self.db.fetch_dicts(sql, (organization_id, prospect_id))
        return [self._map_row(r) for r in rows]

    def find_by_fingerprint(
        self, organization_id: str, prospect_id: str, provider: str, fingerprint: str
    ) -> Optional[PublicSignalObservation]:
        """Find single observation by fingerprint scoped to tenant."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()

        # Cross-tenant ownership check
        sql_check = f"SELECT organization_id FROM prospects WHERE id = {p}"
        p_rows = self.db.fetch_dicts(sql_check, (prospect_id,))
        if p_rows and p_rows[0]["organization_id"] != organization_id:
            raise TenantAccessError(f"Cross-tenant observation access rejected for prospect '{prospect_id}'")

        sql = f"""
            SELECT * FROM signal_observations
            WHERE organization_id = {p} AND prospect_id = {p} AND provider = {p} AND fingerprint = {p}
        """
        rows = self.db.fetch_dicts(sql, (organization_id, prospect_id, provider, fingerprint))
        if not rows:
            return None
        return self._map_row(rows[0])

    def _map_row(self, r: dict) -> PublicSignalObservation:
        ev_raw = r.get("evidence")
        ev_dict = json.loads(ev_raw) if ev_raw and isinstance(ev_raw, str) else ev_raw or {}

        meta_raw = r.get("raw_metadata")
        meta_dict = json.loads(meta_raw) if meta_raw and isinstance(meta_raw, str) else meta_raw or {}

        return PublicSignalObservation(
            id=r["id"],
            organization_id=r["organization_id"],
            prospect_id=r["prospect_id"],
            provider=r["provider"],
            signal_type=r["signal_type"],
            category=r["category"],
            intent_strength=r["intent_strength"],
            source_type=r["source_type"],
            source_url=r["source_url"],
            external_id=r.get("external_id"),
            confidence=float(r.get("confidence", 1.0)),
            evidence=ev_dict,
            raw_metadata=meta_dict,
            fingerprint=r["fingerprint"],
            published_at=r.get("published_at"),
            first_seen_at=r["first_seen_at"],
            last_seen_at=r["last_seen_at"],
            created_at=r["created_at"],
        )
