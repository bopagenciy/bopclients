"""ContinuousMonitoringService orchestrating prospect monitoring schedules, due work, and explicit triggers."""

import uuid
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from bopclients.domain.monitoring_schedule import MonitoringSchedule
from bopclients.domain.exceptions import TenantAccessError, EntityNotFoundError
from bopclients.application.monitoring_dto import (
    MonitoringPlanDecision,
    DueMonitoringWork,
    MonitoringExecutionResult,
)
from bopclients.application.monitoring_policy import MonitoringPolicy, MonitoringBackoffPolicy
from bopclients.application.public_signal_monitor_service import PublicSignalMonitorService
from bopclients.application.prospect_priority_service import ProspectPriorityService
from bopclients.infrastructure.repositories.monitoring_schedule_repository import MonitoringScheduleRepository
from bopclients.infrastructure.repositories.prospect_repository import ProspectRepository
from bopclients.infrastructure.repositories.campaign_repository import CampaignRepository
from bopclients.infrastructure.repositories.prospect_priority_repository import ProspectPriorityRepository
from bopclients.infrastructure.repositories.signal_observation_repository import SignalObservationRepository
from bopclients.infrastructure.repositories.research_run_repository import ResearchRunRepository
from bopclients.domain.research_run import ResearchRun


class ContinuousMonitoringService:
    """Application service for monitoring schedule planning, due-work queries, and explicit execution."""

    NON_FAILURE_SKIP_LEVELS = {"SKIPPED_NO_KEY", "SKIPPED_NO_BACKEND", "SKIPPED_NOT_APPLICABLE"}

    def __init__(
        self,
        schedule_repo: MonitoringScheduleRepository,
        prospect_repo: ProspectRepository,
        campaign_repo: Optional[CampaignRepository] = None,
        priority_repo: Optional[ProspectPriorityRepository] = None,
        observation_repo: Optional[SignalObservationRepository] = None,
        research_run_repo: Optional[ResearchRunRepository] = None,
        signal_monitor_service: Optional[PublicSignalMonitorService] = None,
        priority_service: Optional[ProspectPriorityService] = None,
    ):
        self.schedule_repo = schedule_repo
        self.prospect_repo = prospect_repo
        self.campaign_repo = campaign_repo
        self.priority_repo = priority_repo
        self.observation_repo = observation_repo
        self.research_run_repo = research_run_repo
        self.signal_monitor_service = signal_monitor_service
        self.priority_service = priority_service

    def _get_active_signals_for_prospect(self, organization_id: str, prospect_id: str) -> List[Any]:
        """Fetch active signal observations for a prospect using observation_repo if available."""
        if not self.observation_repo:
            return []
        try:
            all_obs = self.observation_repo.list_for_prospect(organization_id, prospect_id)
            active = []
            for o in all_obs:
                ev = getattr(o, "evidence", {}) if not isinstance(o, dict) else o.get("evidence", {})
                if isinstance(ev, dict) and ev.get("currentness") == "active":
                    active.append(o)
            return active
        except Exception:
            return []

    def ensure_schedule_for_prospect(
        self,
        organization_id: str,
        prospect_id: str,
        campaign_id: Optional[str] = None,
        now_dt: Optional[datetime] = None,
    ) -> MonitoringSchedule:
        """Create or update a monitoring schedule for a prospect without sliding valid next_check_at forward."""
        if not organization_id:
            raise TenantAccessError("organization_id is required for schedule operations.")

        # 1. Fetch prospect
        prospect = self.prospect_repo.get_prospect_by_id(organization_id, prospect_id)
        if not prospect:
            raise EntityNotFoundError(f"Prospect '{prospect_id}' not found for tenant '{organization_id}'.")

        # 2. Fetch priority & active signals
        priority = None
        if self.priority_repo and campaign_id:
            priority = self.priority_repo.get(organization_id, campaign_id, prospect_id)

        active_signals = self._get_active_signals_for_prospect(organization_id, prospect_id)

        # 3. Evaluate policy decision
        decision = MonitoringPolicy.evaluate(
            prospect=prospect,
            priority=priority,
            active_signals=active_signals,
            now_dt=now_dt,
        )

        # 4. Check existing schedule
        existing = self.schedule_repo.get_by_prospect_and_campaign(
            organization_id, prospect_id, campaign_id
        )

        now_iso = (now_dt or datetime.now(timezone.utc)).isoformat()

        if existing:
            # NO-SLIDING PROTECTION: If fingerprint is unchanged and schedule active, preserve existing next_check_at
            fingerprint_unchanged = existing.source_fingerprint == decision.source_fingerprint
            if fingerprint_unchanged and existing.status in ("active", "paused"):
                target_next_check = existing.next_check_at
            else:
                target_next_check = decision.next_check_at

            existing.recommended_interval_days = decision.recommended_interval_days
            existing.next_check_at = target_next_check
            existing.provider_names = decision.provider_names
            existing.operations = decision.operations
            existing.policy_version = decision.policy_version
            existing.source_fingerprint = decision.source_fingerprint
            existing.data = {
                "reasons": decision.reasons,
                "executable_operations": decision.executable_operations,
                "recommended_operations": decision.recommended_operations,
            }
            existing.updated_at = now_iso
            return self.schedule_repo.save(organization_id, existing)

        # Create new schedule
        new_sched = MonitoringSchedule(
            organization_id=organization_id,
            prospect_id=prospect_id,
            campaign_id=campaign_id,
            status="active",
            next_check_at=decision.next_check_at,
            recommended_interval_days=decision.recommended_interval_days,
            provider_names=decision.provider_names,
            operations=decision.operations,
            policy_version=decision.policy_version,
            source_fingerprint=decision.source_fingerprint,
            data={
                "reasons": decision.reasons,
                "executable_operations": decision.executable_operations,
                "recommended_operations": decision.recommended_operations,
            },
            created_at=now_iso,
            updated_at=now_iso,
        )
        return self.schedule_repo.save(organization_id, new_sched)

    def ensure_schedules_for_campaign(
        self, organization_id: str, campaign_id: str, now_dt: Optional[datetime] = None
    ) -> List[MonitoringSchedule]:
        """Ensure monitoring schedules exist for all prospects in a campaign with failure isolation."""
        if not organization_id:
            raise TenantAccessError("organization_id is required.")

        prospect_ids = self.prospect_repo.list_prospect_ids_for_campaign(organization_id, campaign_id)
        schedules = []
        for p_id in prospect_ids:
            try:
                sched = self.ensure_schedule_for_prospect(organization_id, p_id, campaign_id, now_dt=now_dt)
                schedules.append(sched)
            except Exception:
                pass
        return schedules

    def list_due(
        self, organization_id: str, now_dt: Optional[datetime] = None, limit: Optional[int] = None
    ) -> List[DueMonitoringWork]:
        """List active due monitoring work sorted deterministically by next_check_at ASC."""
        if not organization_id:
            raise TenantAccessError("organization_id is required.")

        ref_iso = (now_dt or datetime.now(timezone.utc)).isoformat()
        schedules = self.schedule_repo.list_due(organization_id, now_iso=ref_iso, limit=limit)

        due_list = []
        for s in schedules:
            ex_ops = s.data.get("executable_operations", ["monitor_public_signals"]) if isinstance(s.data, dict) else ["monitor_public_signals"]
            rec_ops = s.data.get("recommended_operations", []) if isinstance(s.data, dict) else []
            due_list.append(
                DueMonitoringWork(
                    schedule_id=s.id,
                    organization_id=s.organization_id,
                    prospect_id=s.prospect_id,
                    campaign_id=s.campaign_id,
                    due_at=s.next_check_at,
                    provider_names=s.provider_names,
                    operations=s.operations,
                    executable_operations=ex_ops,
                    recommended_operations=rec_ops,
                    reasons=s.data.get("reasons", []) if isinstance(s.data, dict) else [],
                    failure_count=s.failure_count,
                    policy_version=s.policy_version,
                )
            )
        return due_list

    def evaluate_execution_status(
        self,
        ops_attempted: List[str],
        ops_succeeded: List[str],
        ops_failed: List[str],
        provider_results: Dict[str, Any],
    ) -> str:
        """Single source of truth policy classifying monitoring execution status into SUCCESS, PARTIAL_SUCCESS, FAILED, or SKIPPED."""
        if not ops_attempted:
            return "SKIPPED"

        # Check provider statuses
        real_successes = 0
        real_failures = 0
        real_skips = 0

        for p_name, res in provider_results.items():
            st = res.get("status", "") if isinstance(res, dict) else ""
            if st in self.NON_FAILURE_SKIP_LEVELS:
                real_skips += 1
            elif st in ("SUCCESS", "SUCCESS_NO_SIGNALS", "PARTIAL_SUCCESS", "FIXTURE_VALIDATED"):
                real_successes += 1
            elif st == "FAILED" or res.get("errors"):
                real_failures += 1
            else:
                real_successes += 1

        if ops_failed:
            real_failures += len(ops_failed)

        if real_successes > 0 and real_failures == 0:
            return "SUCCESS"
        elif real_successes > 0 and real_failures > 0:
            return "PARTIAL_SUCCESS"
        elif real_failures > 0:
            return "FAILED"
        elif real_skips > 0 or not ops_succeeded:
            return "SKIPPED"
        else:
            return "SUCCESS"

    def execute_due(
        self, organization_id: str, schedule_id: str, now_dt: Optional[datetime] = None, force: bool = False
    ) -> MonitoringExecutionResult:
        """Atomically claim and execute due monitoring work for a single schedule."""
        if not organization_id:
            raise TenantAccessError("organization_id is required.")

        schedule = self.schedule_repo.get_by_id(organization_id, schedule_id)
        if not schedule:
            raise EntityNotFoundError(f"Schedule '{schedule_id}' not found for tenant '{organization_id}'.")

        now = now_dt or datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # Validation of due status and active schedule status
        if not force:
            if schedule.status != "active":
                return MonitoringExecutionResult(
                    schedule_id=schedule_id,
                    organization_id=organization_id,
                    prospect_id=schedule.prospect_id,
                    campaign_id=schedule.campaign_id,
                    research_run_id=None,
                    started_at=now_iso,
                    completed_at=now_iso,
                    status="SKIPPED",
                    operations_attempted=[],
                    operations_succeeded=[],
                    operations_failed=[],
                    provider_results={},
                    warnings=[f"Schedule status is '{schedule.status}', not active."],
                )
            if schedule.next_check_at > now_iso:
                return MonitoringExecutionResult(
                    schedule_id=schedule_id,
                    organization_id=organization_id,
                    prospect_id=schedule.prospect_id,
                    campaign_id=schedule.campaign_id,
                    research_run_id=None,
                    started_at=now_iso,
                    completed_at=now_iso,
                    status="SKIPPED",
                    operations_attempted=[],
                    operations_succeeded=[],
                    operations_failed=[],
                    provider_results={},
                    warnings=["Schedule is not yet due for execution."],
                )
        else:
            if schedule.status == "disabled":
                return MonitoringExecutionResult(
                    schedule_id=schedule_id,
                    organization_id=organization_id,
                    prospect_id=schedule.prospect_id,
                    campaign_id=schedule.campaign_id,
                    research_run_id=None,
                    started_at=now_iso,
                    completed_at=now_iso,
                    status="SKIPPED",
                    operations_attempted=[],
                    operations_succeeded=[],
                    operations_failed=[],
                    provider_results={},
                    warnings=["Disabled schedule cannot be force run."],
                )

        lease_token = f"lease-{uuid.uuid4().hex}"

        if not force:
            claimed = self.schedule_repo.claim_due_work(
                organization_id=organization_id,
                schedule_id=schedule_id,
                lease_token=lease_token,
                lease_duration_seconds=300,
                now_iso=now_iso,
            )
        else:
            claimed = self.schedule_repo.claim_force_work(
                organization_id=organization_id,
                schedule_id=schedule_id,
                lease_token=lease_token,
                lease_duration_seconds=300,
                now_iso=now_iso,
            )

        if not claimed:
            return MonitoringExecutionResult(
                schedule_id=schedule_id,
                organization_id=organization_id,
                prospect_id=schedule.prospect_id,
                campaign_id=schedule.campaign_id,
                research_run_id=None,
                started_at=now_iso,
                completed_at=now_iso,
                status="SKIPPED",
                operations_attempted=[],
                operations_succeeded=[],
                operations_failed=[],
                provider_results={},
                warnings=["Schedule claim failed; already leased by another process or not eligible."],
            )

        # Create ResearchRun tracking
        rr_id = None
        if self.research_run_repo:
            rr = ResearchRun(
                organization_id=organization_id,
                campaign_id=schedule.campaign_id,
                prospect_id=schedule.prospect_id,
                run_type="signal_monitoring",
                status="running",
                started_at=now_iso,
                created_at=now_iso,
                updated_at=now_iso,
            )
            saved_rr = self.research_run_repo.save(organization_id, rr)
            rr_id = saved_rr.id

        ex_ops = schedule.data.get("executable_operations", ["monitor_public_signals"]) if isinstance(schedule.data, dict) else ["monitor_public_signals"]
        ops_attempted = list(ex_ops)
        ops_succeeded = []
        ops_failed = []
        prov_results = {}
        warnings = []
        errors = []

        prio_before = None
        prio_after = None

        if self.priority_repo and schedule.campaign_id:
            p_obj = self.priority_repo.get(organization_id, schedule.campaign_id, schedule.prospect_id)
            if p_obj:
                prio_before = p_obj.priority_score

        try:
            # 1. Execute executable operation: monitor_public_signals
            if "monitor_public_signals" in ex_ops and self.signal_monitor_service:
                mon_res = self.signal_monitor_service.monitor_prospect(
                    organization_id=organization_id,
                    prospect_id=schedule.prospect_id,
                    provider_names=schedule.provider_names,
                    recompute_priority=False,
                )
                prov_results = mon_res.provider_results
                warnings.extend(mon_res.warnings)
                errors.extend(mon_res.errors)

                success_providers = [p for p, r in prov_results.items() if isinstance(r, dict) and r.get("status") in ("SUCCESS", "SUCCESS_NO_SIGNALS", "FIXTURE_VALIDATED")]
                failed_providers = [p for p, r in prov_results.items() if isinstance(r, dict) and (r.get("status") == "FAILED" or r.get("errors"))]

                if success_providers:
                    ops_succeeded.append("monitor_public_signals")
                elif failed_providers or mon_res.errors:
                    ops_failed.append("monitor_public_signals")

            # 2. Recompute priority after signal monitoring
            if self.priority_service and schedule.campaign_id:
                prio_res = self.priority_service.prioritize_prospect(
                    organization_id=organization_id,
                    campaign_id=schedule.campaign_id,
                    prospect_id=schedule.prospect_id,
                )
                prio_after = prio_res.priority_score

            # 3. Single source of truth execution status evaluation
            exec_status = self.evaluate_execution_status(
                ops_attempted=ops_attempted,
                ops_succeeded=ops_succeeded,
                ops_failed=ops_failed,
                provider_results=prov_results,
            )

            # 4. RELOAD POST-EXECUTION CURRENT STATE for MonitoringPolicy decision
            prospect = self.prospect_repo.get_prospect_by_id(organization_id, schedule.prospect_id)
            priority = self.priority_repo.get(organization_id, schedule.campaign_id, schedule.prospect_id) if (self.priority_repo and schedule.campaign_id) else None
            post_active_signals = self._get_active_signals_for_prospect(organization_id, schedule.prospect_id)

            new_decision = MonitoringPolicy.evaluate(
                prospect=prospect,
                priority=priority,
                active_signals=post_active_signals,
                available_providers=schedule.provider_names,
                now_dt=now,
            )

            completed_iso = datetime.now(timezone.utc).isoformat()

            # 5. Update schedule state based on execution status policy
            if exec_status in ("SUCCESS", "PARTIAL_SUCCESS"):
                schedule.last_check_at = completed_iso
                schedule.last_success_at = completed_iso
                schedule.failure_count = 0
                schedule.last_error = None
                schedule.next_check_at = new_decision.next_check_at
                schedule.source_fingerprint = new_decision.source_fingerprint
                schedule.data = {
                    "reasons": new_decision.reasons,
                    "executable_operations": new_decision.executable_operations,
                    "recommended_operations": new_decision.recommended_operations,
                }

            elif exec_status == "FAILED":
                schedule.last_check_at = completed_iso
                schedule.last_failure_at = completed_iso
                schedule.failure_count += 1
                schedule.last_error = (errors[0] if errors else "Execution failed")[:255]
                schedule.next_check_at = MonitoringBackoffPolicy.compute_backoff_next_check(schedule.failure_count, now_dt=now)

            else:  # SKIPPED
                schedule.last_check_at = completed_iso
                schedule.next_check_at = new_decision.next_check_at
                schedule.source_fingerprint = new_decision.source_fingerprint
                schedule.data = {
                    "reasons": new_decision.reasons,
                    "executable_operations": new_decision.executable_operations,
                    "recommended_operations": new_decision.recommended_operations,
                }

            schedule.updated_at = completed_iso

            # Guarded update ensures stale worker whose lease was reclaimed cannot overwrite state
            updated = self.schedule_repo.update_schedule_after_execution(
                organization_id=organization_id,
                schedule_id=schedule_id,
                expected_lease_token=lease_token,
                schedule=schedule,
            )

            persisted_next_check = None
            if updated:
                persisted_next_check = schedule.next_check_at
            else:
                warnings.append("LEASE_OWNERSHIP_LOST: Lease token expired or reclaimed during execution; state update skipped.")

            # Update ResearchRun tracking if present
            if self.research_run_repo and rr_id:
                rr_status = "completed" if exec_status in ("SUCCESS", "PARTIAL_SUCCESS", "SKIPPED") else "failed"
                self.research_run_repo.update_status(
                    organization_id,
                    rr_id,
                    status=rr_status,
                    error_message=schedule.last_error,
                )

            return MonitoringExecutionResult(
                schedule_id=schedule_id,
                organization_id=organization_id,
                prospect_id=schedule.prospect_id,
                campaign_id=schedule.campaign_id,
                research_run_id=rr_id,
                started_at=now_iso,
                completed_at=completed_iso,
                status=exec_status,
                operations_attempted=ops_attempted,
                operations_succeeded=ops_succeeded,
                operations_failed=ops_failed,
                provider_results=prov_results,
                priority_before=prio_before,
                priority_after=prio_after,
                warnings=warnings,
                errors=errors,
                next_check_at=persisted_next_check,  # SINGLE SOURCE OF TRUTH: exact persisted value
            )

        finally:
            # Release lease token with ownership check in finally block
            self.schedule_repo.release_lease(organization_id, schedule_id, lease_token)

    def force_monitor(
        self, organization_id: str, schedule_id: str, now_dt: Optional[datetime] = None
    ) -> MonitoringExecutionResult:
        """Force immediate monitoring execution bypassing next_check_at timestamp."""
        return self.execute_due(organization_id, schedule_id, now_dt=now_dt, force=True)

    def pause_schedule(self, organization_id: str, schedule_id: str) -> bool:
        """Pause schedule tenant-safely."""
        return self.schedule_repo.update_schedule_status(organization_id, schedule_id, "paused")

    def resume_schedule(self, organization_id: str, schedule_id: str) -> bool:
        """Resume schedule tenant-safely."""
        return self.schedule_repo.update_schedule_status(organization_id, schedule_id, "active")

    def disable_schedule(self, organization_id: str, schedule_id: str) -> bool:
        """Disable schedule tenant-safely."""
        return self.schedule_repo.update_schedule_status(organization_id, schedule_id, "disabled")
