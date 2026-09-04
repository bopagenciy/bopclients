"""Repository for tenant-isolated persistence of MonitoringSchedule entities."""

import json
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Any
from bopclients.domain.monitoring_schedule import MonitoringSchedule
from bopclients.domain.exceptions import TenantAccessError
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class MonitoringScheduleRepository(BaseTenantRepository):
    """Repository managing monitoring_schedules table persistence for tenant operations and internal system workers."""

    def save(self, organization_id: str, schedule: MonitoringSchedule) -> MonitoringSchedule:
        """Save or update a monitoring schedule entity with strict tenant ownership validation."""
        organization_id = self._validate_tenant(organization_id)
        if schedule.organization_id and schedule.organization_id != organization_id:
            raise TenantAccessError("Cross-tenant schedule persistence rejected.")

        schedule.organization_id = organization_id
        schedule.validate()

        p = self._placeholder()
        now = datetime.now(timezone.utc).isoformat()

        check_sql = f"""
            SELECT id FROM monitoring_schedules
            WHERE organization_id = {p} AND scope_key = {p}
        """
        rows = self.db.fetch_dicts(check_sql, (organization_id, schedule.scope_key))

        if rows:
            old_id = rows[0]["id"]
            update_sql = f"""
                UPDATE monitoring_schedules SET
                    status = {p},
                    next_check_at = {p},
                    last_check_at = {p},
                    last_success_at = {p},
                    last_failure_at = {p},
                    recommended_interval_days = {p},
                    provider_names = {p},
                    operations = {p},
                    failure_count = {p},
                    last_error = {p},
                    lease_token = {p},
                    lease_expires_at = {p},
                    current_execution_attempt_id = {p},
                    policy_version = {p},
                    source_fingerprint = {p},
                    data = {p},
                    updated_at = {p}
                WHERE organization_id = {p} AND id = {p}
            """
            self.db.execute(
                update_sql,
                (
                    schedule.status,
                    schedule.next_check_at,
                    schedule.last_check_at,
                    schedule.last_success_at,
                    schedule.last_failure_at,
                    schedule.recommended_interval_days,
                    json.dumps(schedule.provider_names),
                    json.dumps(schedule.operations),
                    schedule.failure_count,
                    schedule.last_error,
                    schedule.lease_token,
                    schedule.lease_expires_at,
                    schedule.current_execution_attempt_id,
                    schedule.policy_version,
                    schedule.source_fingerprint,
                    json.dumps(schedule.data or {}),
                    now,
                    organization_id,
                    old_id,
                ),
            )
            schedule.id = old_id
            schedule.updated_at = now
        else:
            insert_sql = f"""
                INSERT INTO monitoring_schedules (
                    id, organization_id, prospect_id, campaign_id, scope_key, status,
                    next_check_at, last_check_at, last_success_at, last_failure_at,
                    recommended_interval_days, provider_names, operations, failure_count,
                    last_error, lease_token, lease_expires_at, current_execution_attempt_id, policy_version,
                    source_fingerprint, data, created_at, updated_at
                ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """
            self.db.execute(
                insert_sql,
                (
                    schedule.id,
                    organization_id,
                    schedule.prospect_id,
                    schedule.campaign_id,
                    schedule.scope_key,
                    schedule.status,
                    schedule.next_check_at,
                    schedule.last_check_at,
                    schedule.last_success_at,
                    schedule.last_failure_at,
                    schedule.recommended_interval_days,
                    json.dumps(schedule.provider_names),
                    json.dumps(schedule.operations),
                    schedule.failure_count,
                    schedule.last_error,
                    schedule.lease_token,
                    schedule.lease_expires_at,
                    schedule.current_execution_attempt_id,
                    schedule.policy_version,
                    schedule.source_fingerprint,
                    json.dumps(schedule.data or {}),
                    now,
                    now,
                ),
            )

        self.db.commit()
        return schedule

    def get_by_id(self, organization_id: str, schedule_id: str) -> Optional[MonitoringSchedule]:
        """Fetch schedule by ID with tenant boundary isolation."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()

        query = f"SELECT * FROM monitoring_schedules WHERE organization_id = {p} AND id = {p}"
        rows = self.db.fetch_dicts(query, (organization_id, schedule_id))
        if not rows:
            return None
        return self._map_row_to_entity(rows[0])

    def get_by_prospect_and_campaign(
        self, organization_id: str, prospect_id: str, campaign_id: Optional[str] = None
    ) -> Optional[MonitoringSchedule]:
        """Fetch schedule for a prospect & optional campaign scope."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()

        scope_key = f"{prospect_id}:{campaign_id or '__GLOBAL__'}"
        query = f"SELECT * FROM monitoring_schedules WHERE organization_id = {p} AND scope_key = {p}"
        rows = self.db.fetch_dicts(query, (organization_id, scope_key))
        if not rows:
            return None
        return self._map_row_to_entity(rows[0])

    def list_for_prospect(self, organization_id: str, prospect_id: str) -> List[MonitoringSchedule]:
        """List all schedules for a prospect across campaigns in a tenant."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()

        query = f"SELECT * FROM monitoring_schedules WHERE organization_id = {p} AND prospect_id = {p} ORDER BY created_at ASC"
        rows = self.db.fetch_dicts(query, (organization_id, prospect_id))
        return [self._map_row_to_entity(r) for r in rows]

    def list_due(
        self, organization_id: str, now_iso: Optional[str] = None, limit: Optional[int] = None
    ) -> List[MonitoringSchedule]:
        """List due active schedules sorted deterministically by next_check_at ASC, prospect_id ASC."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()
        ref_iso = now_iso or datetime.now(timezone.utc).isoformat()

        query = f"""
            SELECT * FROM monitoring_schedules
            WHERE organization_id = {p}
              AND status = 'active'
              AND next_check_at <= {p}
              AND (lease_expires_at IS NULL OR lease_expires_at <= {p})
            ORDER BY next_check_at ASC, prospect_id ASC, id ASC
        """
        params = [organization_id, ref_iso, ref_iso]
        if limit:
            query += f" LIMIT {p}"
            params.append(limit)
        rows = self.db.fetch_dicts(query, tuple(params))
        return [self._map_row_to_entity(r) for r in rows]

    def list_due_system(
        self, now_iso: Optional[str] = None, limit: Optional[int] = None
    ) -> List[MonitoringSchedule]:
        """System-scoped infrastructure query fetching due active schedules across ALL organizations.

        INTERNAL WORKER PRIVILEGED API ONLY. Do NOT expose to client-facing endpoints or tenant controllers.
        """
        p = self._placeholder()
        ref_iso = now_iso or datetime.now(timezone.utc).isoformat()

        query = f"""
            SELECT * FROM (
                SELECT *,
                       ROW_NUMBER() OVER (
                           PARTITION BY organization_id
                           ORDER BY next_check_at ASC, prospect_id ASC, id ASC
                       ) AS tenant_round
                FROM monitoring_schedules
                WHERE status = 'active'
                  AND next_check_at <= {p}
                  AND (lease_expires_at IS NULL OR lease_expires_at <= {p})
            ) sub
            ORDER BY tenant_round ASC, next_check_at ASC, organization_id ASC, prospect_id ASC, id ASC
        """
        params = [ref_iso, ref_iso]
        if limit:
            query += f" LIMIT {p}"
            params.append(limit)
        rows = self.db.fetch_dicts(query, tuple(params))
        return [self._map_row_to_entity(r) for r in rows]

    def claim_due_work(
        self,
        organization_id: str,
        schedule_id: str,
        lease_token: str,
        lease_duration_seconds: int = 300,
        now_iso: Optional[str] = None,
        execution_attempt_id: Optional[str] = None,
    ) -> bool:
        """Atomic claim/lease of a due active schedule setting lease_token, lease_expires_at, and current_execution_attempt_id in a single UPDATE."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()

        ref_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00")) if now_iso else datetime.now(timezone.utc)
        now_iso_str = ref_dt.isoformat()
        lease_expires_iso = (ref_dt + timedelta(seconds=lease_duration_seconds)).isoformat()

        update_sql = f"""
            UPDATE monitoring_schedules
            SET lease_token = {p},
                lease_expires_at = {p},
                current_execution_attempt_id = {p},
                updated_at = {p}
            WHERE organization_id = {p} AND id = {p} AND status = 'active'
              AND next_check_at <= {p}
              AND (lease_expires_at IS NULL OR lease_expires_at <= {p})
        """
        count = self._execute_rowcount(
            update_sql,
            (lease_token, lease_expires_iso, execution_attempt_id, now_iso_str, organization_id, schedule_id, now_iso_str, now_iso_str),
        )
        self.db.commit()
        return count > 0

    def claim_force_work(
        self,
        organization_id: str,
        schedule_id: str,
        lease_token: str,
        lease_duration_seconds: int = 300,
        now_iso: Optional[str] = None,
        execution_attempt_id: Optional[str] = None,
    ) -> bool:
        """Atomic claim/lease for explicit force_monitor setting lease_token, lease_expires_at, and current_execution_attempt_id in a single UPDATE."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()

        ref_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00")) if now_iso else datetime.now(timezone.utc)
        now_iso_str = ref_dt.isoformat()
        lease_expires_iso = (ref_dt + timedelta(seconds=lease_duration_seconds)).isoformat()

        update_sql = f"""
            UPDATE monitoring_schedules
            SET lease_token = {p},
                lease_expires_at = {p},
                current_execution_attempt_id = {p},
                updated_at = {p}
            WHERE organization_id = {p} AND id = {p} AND status IN ('active', 'paused')
              AND (lease_expires_at IS NULL OR lease_expires_at <= {p})
        """
        count = self._execute_rowcount(
            update_sql,
            (lease_token, lease_expires_iso, execution_attempt_id, now_iso_str, organization_id, schedule_id, now_iso_str),
        )
        self.db.commit()
        return count > 0

    def renew_lease(
        self,
        organization_id: str,
        schedule_id: str,
        lease_token: str,
        lease_duration_seconds: int = 300,
        now_iso: Optional[str] = None,
    ) -> bool:
        """Extend lease duration for an active execution IF AND ONLY IF lease_token ownership matches."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()

        if not lease_token:
            return False

        ref_dt = datetime.fromisoformat(now_iso.replace("Z", "+00:00")) if now_iso else datetime.now(timezone.utc)
        now_iso_str = ref_dt.isoformat()
        new_expires_iso = (ref_dt + timedelta(seconds=lease_duration_seconds)).isoformat()

        query = f"""
            UPDATE monitoring_schedules
            SET lease_expires_at = {p}, updated_at = {p}
            WHERE organization_id = {p} AND id = {p} AND lease_token = {p}
        """
        count = self._execute_rowcount(query, (new_expires_iso, now_iso_str, organization_id, schedule_id, lease_token))
        self.db.commit()
        return count > 0

    def release_lease(
        self,
        organization_id: str,
        schedule_id: str,
        lease_token: str,
        execution_attempt_id: Optional[str] = None,
    ) -> bool:
        """Release lease token enforcing lease_token ownership matching and ensuring stale owner attempt ID does not clear newer owner."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()
        now_iso = datetime.now(timezone.utc).isoformat()

        if not lease_token:
            return False

        if execution_attempt_id:
            query = f"""
                UPDATE monitoring_schedules
                SET lease_token = NULL, lease_expires_at = NULL, current_execution_attempt_id = NULL, updated_at = {p}
                WHERE organization_id = {p} AND id = {p} AND lease_token = {p}
                  AND (current_execution_attempt_id IS NULL OR current_execution_attempt_id = {p})
            """
            count = self._execute_rowcount(query, (now_iso, organization_id, schedule_id, lease_token, execution_attempt_id))
        else:
            query = f"""
                UPDATE monitoring_schedules
                SET lease_token = NULL, lease_expires_at = NULL, current_execution_attempt_id = NULL, updated_at = {p}
                WHERE organization_id = {p} AND id = {p} AND lease_token = {p}
            """
            count = self._execute_rowcount(query, (now_iso, organization_id, schedule_id, lease_token))

        self.db.commit()
        return count > 0

    def update_schedule_after_execution(
        self,
        organization_id: str,
        schedule_id: str,
        expected_lease_token: str,
        schedule: MonitoringSchedule,
    ) -> bool:
        """Save schedule state update after execution verifying expected_lease_token ownership is still intact."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()
        now = datetime.now(timezone.utc).isoformat()

        update_sql = f"""
            UPDATE monitoring_schedules SET
                status = {p},
                next_check_at = {p},
                last_check_at = {p},
                last_success_at = {p},
                last_failure_at = {p},
                recommended_interval_days = {p},
                provider_names = {p},
                operations = {p},
                failure_count = {p},
                last_error = {p},
                lease_token = NULL,
                lease_expires_at = NULL,
                current_execution_attempt_id = NULL,
                policy_version = {p},
                source_fingerprint = {p},
                data = {p},
                updated_at = {p}
            WHERE organization_id = {p} AND id = {p} AND lease_token = {p}
        """
        count = self._execute_rowcount(
            update_sql,
            (
                schedule.status,
                schedule.next_check_at,
                schedule.last_check_at,
                schedule.last_success_at,
                schedule.last_failure_at,
                schedule.recommended_interval_days,
                json.dumps(schedule.provider_names),
                json.dumps(schedule.operations),
                schedule.failure_count,
                schedule.last_error,
                schedule.policy_version,
                schedule.source_fingerprint,
                json.dumps(schedule.data) if schedule.data else None,
                now,
                organization_id,
                schedule_id,
                expected_lease_token,
            ),
        )
        self.db.commit()
        return count > 0

    def update_schedule_status(self, organization_id: str, schedule_id: str, status: str) -> bool:
        """Update status (active, paused, disabled) tenant-safely."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()

        if status not in ("active", "paused", "disabled"):
            raise ValueError(f"Invalid status '{status}'.")

        now_iso = datetime.now(timezone.utc).isoformat()
        query = f"UPDATE monitoring_schedules SET status = {p}, updated_at = {p} WHERE organization_id = {p} AND id = {p}"
        self.db.execute(query, (status, now_iso, organization_id, schedule_id))
        self.db.commit()
        return True

    def delete_schedule(self, organization_id: str, schedule_id: str) -> bool:
        """Delete schedule tenant-safely."""
        organization_id = self._validate_tenant(organization_id)
        p = self._placeholder()

        query = f"DELETE FROM monitoring_schedules WHERE organization_id = {p} AND id = {p}"
        self.db.execute(query, (organization_id, schedule_id))
        self.db.commit()
        return True

    def _map_row_to_entity(self, row: Any) -> MonitoringSchedule:
        """Map raw DB cursor dict row to MonitoringSchedule entity."""
        d = dict(row) if not isinstance(row, dict) else row
        return MonitoringSchedule(
            id=d["id"],
            organization_id=d["organization_id"],
            prospect_id=d["prospect_id"],
            campaign_id=d.get("campaign_id"),
            scope_key=d["scope_key"],
            status=d["status"],
            next_check_at=d["next_check_at"],
            last_check_at=d.get("last_check_at"),
            last_success_at=d.get("last_success_at"),
            last_failure_at=d.get("last_failure_at"),
            recommended_interval_days=d.get("recommended_interval_days", 14),
            provider_names=json.loads(d.get("provider_names") or "[]"),
            operations=json.loads(d.get("operations") or "[]"),
            failure_count=d.get("failure_count", 0),
            last_error=d.get("last_error"),
            lease_token=d.get("lease_token"),
            lease_expires_at=d.get("lease_expires_at"),
            current_execution_attempt_id=d.get("current_execution_attempt_id"),
            policy_version=d.get("policy_version", "v1.0"),
            source_fingerprint=d.get("source_fingerprint", ""),
            data=json.loads(d.get("data") or "{}"),
            created_at=d["created_at"],
            updated_at=d["updated_at"],
        )
