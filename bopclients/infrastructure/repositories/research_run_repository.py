"""Database repository for ResearchRun execution tracking (Tenant Isolated)."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from bopclients.domain.research_run import ResearchRun
from bopclients.domain.exceptions import TenantAccessError
from bopclients.application.interfaces.repositories import IResearchRunRepository
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class ResearchRunRepository(BaseTenantRepository, IResearchRunRepository):
    """Repository for managing ResearchRun execution tracking with complete tenant isolation."""

    def _row_to_entity(self, r: Dict[str, Any]) -> ResearchRun:
        return ResearchRun(
            id=r["id"],
            organization_id=r["organization_id"],
            campaign_id=r.get("campaign_id"),
            prospect_id=r.get("prospect_id"),
            monitoring_schedule_id=r.get("monitoring_schedule_id"),
            execution_attempt_id=r.get("execution_attempt_id"),
            run_type=r["run_type"],
            status=r.get("status", "pending"),
            started_at=r.get("started_at"),
            completed_at=r.get("completed_at"),
            error_message=r.get("error_message"),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )

    def save(self, org_id: str, run: ResearchRun) -> ResearchRun:
        org_id = self._validate_tenant(org_id)
        run.organization_id = org_id
        p = self._placeholder()

        # Validate campaign_id belongs to tenant if provided
        if run.campaign_id:
            c_rows = self.db.fetch_dicts(
                f"SELECT id FROM campaigns WHERE organization_id = {p} AND id = {p}",
                (org_id, run.campaign_id),
            )
            if not c_rows:
                raise TenantAccessError(
                    f"ResearchRun rejected: Campaign '{run.campaign_id}' not found for organization '{org_id}'"
                )

        # Validate prospect_id belongs to tenant if provided
        if run.prospect_id:
            p_rows = self.db.fetch_dicts(
                f"SELECT id FROM prospects WHERE organization_id = {p} AND id = {p}",
                (org_id, run.prospect_id),
            )
            if not p_rows:
                raise TenantAccessError(
                    f"ResearchRun rejected: Prospect '{run.prospect_id}' not found for organization '{org_id}'"
                )

        # Check global existence of run.id for tenant isolation safety
        global_check = f"SELECT organization_id FROM research_runs WHERE id = {p}"
        existing_global = self.db.fetch_dicts(global_check, (run.id,))

        if existing_global:
            if existing_global[0]["organization_id"] != org_id:
                raise TenantAccessError(f"Cross-tenant ResearchRun update rejected for run '{run.id}'")

            sql = f"""
            UPDATE research_runs SET
                monitoring_schedule_id = {p},
                execution_attempt_id = {p},
                status = {p},
                started_at = {p},
                completed_at = {p},
                error_message = {p},
                updated_at = {p}
            WHERE organization_id = {p} AND id = {p}
            """
            self.db.execute(
                sql,
                (
                    run.monitoring_schedule_id,
                    run.execution_attempt_id,
                    run.status,
                    run.started_at,
                    run.completed_at,
                    run.error_message,
                    run.updated_at,
                    org_id,
                    run.id,
                ),
            )
        else:
            sql = f"""
            INSERT INTO research_runs (
                id, organization_id, campaign_id, prospect_id, monitoring_schedule_id, execution_attempt_id,
                run_type, status, started_at, completed_at, error_message, created_at, updated_at
            ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """
            self.db.execute(
                sql,
                (
                    run.id,
                    org_id,
                    run.campaign_id,
                    run.prospect_id,
                    run.monitoring_schedule_id,
                    run.execution_attempt_id,
                    run.run_type,
                    run.status,
                    run.started_at,
                    run.completed_at,
                    run.error_message,
                    run.created_at,
                    run.updated_at,
                ),
            )
        self.db.commit()
        return run

    def get_by_id(self, org_id: str, run_id: str) -> Optional[ResearchRun]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT * FROM research_runs WHERE organization_id = {p} AND id = {p}"
        rows = self.db.fetch_dicts(sql, (org_id, run_id))
        if not rows:
            return None
        return self._row_to_entity(rows[0])

    def update_status(
        self,
        org_id: str,
        run_id: str,
        status: str,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        error_message: Optional[str] = None,
        execution_attempt_id: Optional[str] = None,
        expected_status: Optional[str] = None,
    ) -> Optional[ResearchRun]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        now_iso = datetime.now(timezone.utc).isoformat()
        where_clauses = [f"organization_id = {p}", f"id = {p}"]
        where_params = [org_id, run_id]

        if expected_status:
            where_clauses.append(f"status = {p}")
            where_params.append(expected_status)
        if execution_attempt_id:
            where_clauses.append(f"execution_attempt_id = {p}")
            where_params.append(execution_attempt_id)

        where_sql = " AND ".join(where_clauses)
        sql = f"""
        UPDATE research_runs SET
            status = {p},
            started_at = COALESCE({p}, started_at),
            completed_at = COALESCE({p}, completed_at),
            error_message = COALESCE({p}, error_message),
            updated_at = {p}
        WHERE {where_sql}
        """
        full_params = tuple([status, started_at, completed_at, error_message, now_iso] + where_params)
        count = self._execute_rowcount(sql, full_params)
        self.db.commit()
        if count > 0:
            return self.get_by_id(org_id, run_id)
        return None

    def list_by_organization(
        self,
        org_id: str,
        campaign_id: Optional[str] = None,
        prospect_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ResearchRun]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        query_parts = [f"organization_id = {p}"]
        params = [org_id]

        if campaign_id:
            query_parts.append(f"campaign_id = {p}")
            params.append(campaign_id)

        if prospect_id:
            query_parts.append(f"prospect_id = {p}")
            params.append(prospect_id)

        where_clause = " AND ".join(query_parts)
        sql = f"SELECT * FROM research_runs WHERE {where_clause} ORDER BY created_at DESC LIMIT {limit} OFFSET {offset}"

        rows = self.db.fetch_dicts(sql, tuple(params))
        return [self._row_to_entity(r) for r in rows]

    def list_stale_running_runs(
        self,
        stale_before_iso: str,
        limit: int = 100,
    ) -> List[ResearchRun]:
        """Fetch running ResearchRuns started on or before stale_before_iso across all organizations (System Scoped)."""
        p = self._placeholder()
        sql = f"""
            SELECT * FROM research_runs
            WHERE status = 'running' AND started_at IS NOT NULL AND started_at <= {p}
            ORDER BY started_at ASC, organization_id ASC, id ASC
            LIMIT {limit}
        """
        rows = self.db.fetch_dicts(sql, (stale_before_iso,))
        return [self._row_to_entity(r) for r in rows]

    def mark_stale_run_failed(
        self,
        org_id: str,
        run_id: str,
        error_message: str,
        completed_at_iso: str,
    ) -> bool:
        """Atomically mark a running ResearchRun as failed if status is still 'running'."""
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"""
            UPDATE research_runs SET
                status = 'failed',
                error_message = {p},
                completed_at = {p},
                updated_at = {p}
            WHERE organization_id = {p} AND id = {p} AND status = 'running'
        """
        count = self._execute_rowcount(sql, (error_message, completed_at_iso, completed_at_iso, org_id, run_id))
        self.db.commit()
        return count > 0

    def claim_run(
        self,
        org_id: str,
        run_id: str,
        execution_attempt_id: Optional[str] = None,
        started_at_iso: Optional[str] = None,
        worker_id: Optional[str] = None,
    ) -> Optional[ResearchRun]:
        """Atomically transition a ResearchRun from 'pending' to 'running' with exclusive execution lease.

        Returns the claimed ResearchRun if successfully claimed, or None if already claimed or not pending.
        """
        org_id = self._validate_tenant(org_id)
        attempt_id = execution_attempt_id or worker_id or str(uuid.uuid4())
        started_iso = started_at_iso or datetime.now(timezone.utc).isoformat()
        p = self._placeholder()
        sql = f"""
            UPDATE research_runs SET
                status = 'running',
                execution_attempt_id = {p},
                started_at = {p},
                updated_at = {p}
            WHERE organization_id = {p} AND id = {p} AND status = 'pending'
        """
        count = self._execute_rowcount(sql, (attempt_id, started_iso, started_iso, org_id, run_id))
        self.db.commit()
        if count > 0:
            return self.get_by_id(org_id, run_id)
        return None

    def list_pending_runs(
        self,
        org_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[ResearchRun]:
        """Fetch pending ResearchRuns ordered by created_at ASC."""
        p = self._placeholder()
        params = []
        where_clause = "status = 'pending'"
        if org_id:
            org_id = self._validate_tenant(org_id)
            where_clause += f" AND organization_id = {p}"
            params.append(org_id)

        sql = f"SELECT * FROM research_runs WHERE {where_clause} ORDER BY created_at ASC LIMIT {int(limit)}"
        rows = self.db.fetch_dicts(sql, tuple(params))
        return [self._row_to_entity(r) for r in rows]
