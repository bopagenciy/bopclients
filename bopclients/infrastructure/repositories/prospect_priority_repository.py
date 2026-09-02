"""ProspectPriorityRepository enforcing tenant boundary isolation for prospect prioritization snapshots."""

import json
from typing import Optional, List, Any
from datetime import datetime, timezone
from bopclients.domain.exceptions import TenantAccessError
from bopclients.domain.prospect_priority import ProspectPriority
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class ProspectPriorityRepository(BaseTenantRepository):
    """Repository managing prospect_priorities table with multi-tenant security."""

    def save(self, organization_id: str, priority: ProspectPriority) -> ProspectPriority:
        """Save or update prospect priority snapshot enforcing tenant isolation."""
        organization_id = self._validate_tenant(organization_id)
        priority.organization_id = organization_id
        priority.validate()

        now = datetime.now(timezone.utc).isoformat()
        data_json = json.dumps(priority.data)
        p = self._placeholder()

        # Check existing row
        sql_check = f"""
            SELECT id FROM prospect_priorities
            WHERE organization_id = {p} AND campaign_id = {p} AND prospect_id = {p}
        """
        rows = self.db.fetch_dicts(sql_check, (organization_id, priority.campaign_id, priority.prospect_id))

        if rows:
            p_id = rows[0]["id"]
            sql_update = f"""
                UPDATE prospect_priorities
                SET priority_score = {p},
                    priority_label = {p},
                    lead_score_component = {p},
                    intent_signal_component = {p},
                    research_confidence_component = {p},
                    freshness_component = {p},
                    policy_version = {p},
                    data = {p},
                    updated_at = {p}
                WHERE organization_id = {p} AND id = {p}
            """
            self.db.execute(
                sql_update,
                (
                    priority.priority_score,
                    priority.priority_label,
                    priority.lead_score_component,
                    priority.intent_signal_component,
                    priority.research_confidence_component,
                    priority.freshness_component,
                    priority.policy_version,
                    data_json,
                    now,
                    organization_id,
                    p_id,
                ),
            )
            priority.id = p_id
            priority.updated_at = now
        else:
            sql_insert = f"""
                INSERT INTO prospect_priorities (
                    id, organization_id, campaign_id, prospect_id,
                    priority_score, priority_label,
                    lead_score_component, intent_signal_component,
                    research_confidence_component, freshness_component,
                    policy_version, data, created_at, updated_at
                ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """
            self.db.execute(
                sql_insert,
                (
                    priority.id,
                    organization_id,
                    priority.campaign_id,
                    priority.prospect_id,
                    priority.priority_score,
                    priority.priority_label,
                    priority.lead_score_component,
                    priority.intent_signal_component,
                    priority.research_confidence_component,
                    priority.freshness_component,
                    priority.policy_version,
                    data_json,
                    now,
                    now,
                ),
            )
            priority.created_at = now
            priority.updated_at = now

        self.db.commit()
        return priority

    def get(self, organization_id: str, campaign_id: str, prospect_id: str) -> Optional[ProspectPriority]:
        """Fetch latest priority snapshot for a prospect in a campaign, scoped to tenant."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()

        sql = f"""
            SELECT * FROM prospect_priorities
            WHERE organization_id = {p} AND campaign_id = {p} AND prospect_id = {p}
        """
        rows = self.db.fetch_dicts(sql, (organization_id, campaign_id, prospect_id))
        if not rows:
            return None

        return self._map_row(rows[0])

    def get_top_for_campaign(
        self, organization_id: str, campaign_id: str, limit: Optional[int] = None
    ) -> List[ProspectPriority]:
        """Fetch priority snapshots for a campaign ordered by priority_score DESC, strictly scoped to tenant."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()

        sql = f"""
            SELECT * FROM prospect_priorities
            WHERE organization_id = {p} AND campaign_id = {p}
            ORDER BY priority_score DESC, updated_at DESC, prospect_id ASC
        """
        params: List[Any] = [organization_id, campaign_id]
        if limit is not None and limit > 0:
            sql += f" LIMIT {p}"
            params.append(limit)

        rows = self.db.fetch_dicts(sql, tuple(params))
        return [self._map_row(r) for r in rows]

    def _map_row(self, r: dict) -> ProspectPriority:
        data_raw = r.get("data")
        try:
            data_dict = json.loads(data_raw) if data_raw and isinstance(data_raw, str) else data_raw or {}
        except Exception:
            data_dict = {}

        return ProspectPriority(
            id=r["id"],
            organization_id=r["organization_id"],
            campaign_id=r["campaign_id"],
            prospect_id=r["prospect_id"],
            priority_score=int(r["priority_score"]),
            priority_label=r["priority_label"],
            lead_score_component=float(r.get("lead_score_component", 0.0)),
            intent_signal_component=float(r.get("intent_signal_component", 0.0)),
            research_confidence_component=float(r.get("research_confidence_component", 0.0)),
            freshness_component=float(r.get("freshness_component", 0.0)),
            policy_version=r.get("policy_version", "v1.0"),
            data=data_dict,
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
