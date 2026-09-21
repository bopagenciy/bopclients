"""Discovery Orchestrator executing SearchPlans, deduplicating raw results, and updating ResearchRuns."""

from typing import List, Dict, Set, Optional, Tuple
from bopclients.domain.prospect import Prospect
from bopclients.domain.research_run import ResearchRun
from bopclients.domain.exceptions import DiscoveryExecutionError, TenantAccessError
from bopclients.application.search_dto import (
    SearchPlan,
    SearchExecutionResult,
    SearchWarning,
)
from bopclients.application.dtos import AddProspectCommand
from bopclients.application.interfaces.search_interfaces import IDiscoveryProvider
from bopclients.application.prospect_service import ProspectService
from bopclients.application.interfaces.repositories import IResearchRunRepository, ICampaignRepository


class DiscoveryOrchestrator:
    """Orchestrates multi-provider discovery execution, batch deduplication, and ResearchRun tracking."""

    def __init__(
        self,
        providers: List[IDiscoveryProvider],
        prospect_service: ProspectService,
        research_run_repo: IResearchRunRepository,
        campaign_repo: Optional[ICampaignRepository] = None,
    ):
        self.providers = {p.name.lower(): p for p in providers}
        self.prospect_service = prospect_service
        self.research_run_repo = research_run_repo
        self.campaign_repo = campaign_repo

    def execute_plan(
        self, plan: SearchPlan, max_results_override: Optional[int] = None
    ) -> SearchExecutionResult:
        org_id = plan.organization_id
        campaign_id = plan.campaign_id

        # Validate campaign tenant ownership if campaign_id is supplied
        if campaign_id and self.campaign_repo:
            camp = self.campaign_repo.get_by_id(org_id, campaign_id)
            if not camp:
                raise TenantAccessError(
                    f"Execution rejected: Campaign '{campaign_id}' not found for organization '{org_id}'"
                )

        # 1. Initialize ResearchRun in pending status
        run = ResearchRun(
            organization_id=org_id,
            campaign_id=campaign_id,
            run_type="discovery",
            status="pending",
        )
        run = self.research_run_repo.save(org_id, run)

        # 2. Update status to running
        from datetime import datetime, timezone
        start_time = datetime.now(timezone.utc).isoformat()
        self.research_run_repo.update_status(org_id, run.id, status="running", started_at=start_time)

        total_raw = 0
        imported_prospects: List[Prospect] = []
        imported_prospect_ids: Set[str] = set()
        batch_seen_keys: Set[Tuple[str, str]] = set()
        execution_warnings: List[SearchWarning] = list(plan.warnings)
        execution_errors: List[str] = []

        tasks_total = len(plan.tasks)
        tasks_succeeded = 0
        tasks_failed = 0

        prospects_created = 0
        prospects_reused = 0

        max_results_limit = max_results_override or 1000

        try:
            for task in plan.tasks:
                if len(imported_prospects) >= max_results_limit:
                    break

                provider = self.providers.get(task.provider.lower())
                if not provider or not provider.supports(task):
                    tasks_failed += 1
                    msg = f"No active discovery provider registered for '{task.provider}'."
                    execution_errors.append(msg)
                    execution_warnings.append(
                        SearchWarning(
                            code="PROVIDER_NOT_AVAILABLE",
                            message=msg,
                            details={"task_id": task.id},
                        )
                    )
                    continue

                try:
                    # Enforce remaining limit on task
                    task.limit = min(task.limit, max_results_limit - len(imported_prospects))
                    discovered_batch = provider.discover(task)
                    tasks_succeeded += 1
                    total_raw += len(discovered_batch)

                    if task.metadata.get("source_sample_truncated"):
                        diag = task.metadata.get("diagnostics", {})
                        execution_warnings.append(
                            SearchWarning(
                                code="SOURCE_SAMPLE_TRUNCATED",
                                message=(
                                    f"Source query for category '{task.category}' reached the limit of {task.limit} candidates. "
                                    "Candidate sample was truncated before local validation; complete source coverage is not guaranteed."
                                ),
                                details={
                                    "task_id": task.id,
                                    "category": task.category,
                                    "limit": task.limit,
                                    "diagnostics": diag,
                                },
                            )
                        )

                    for biz in discovered_batch:
                        if len(imported_prospects) >= max_results_limit:
                            break

                        ext_id = biz.overture_id or ""
                        norm_url = (biz.website_url or "").strip().lower().rstrip("/")
                        batch_key = (ext_id, norm_url)

                        # Skip duplicate raw item within the same batch
                        if batch_key in batch_seen_keys and (ext_id or norm_url):
                            continue
                        if ext_id or norm_url:
                            batch_seen_keys.add(batch_key)

                        # Check if prospect already exists before adding to count created/reused
                        existing = self.prospect_service.prospect_repo.find_existing_prospect(
                            org_id,
                            forge_record_id=biz.overture_id,
                            website_url=biz.website_url,
                        )

                        cmd = AddProspectCommand(
                            organization_id=org_id,
                            campaign_id=campaign_id,
                            forge_record_id=biz.overture_id,
                            name=biz.name,
                            website_url=biz.website_url,
                            phone=biz.phone,
                            address=biz.address,
                            city=biz.city,
                            state=biz.state,
                            postal_code=biz.zip_code,
                            industry=biz.forge_industry or biz.category,
                            source=(task.provider or "overture").lower(),
                        )
                        prospect = self.prospect_service.add_prospect(cmd)

                        if prospect.id not in imported_prospect_ids:
                            imported_prospect_ids.add(prospect.id)
                            imported_prospects.append(prospect)
                            if existing:
                                prospects_reused += 1
                            else:
                                prospects_created += 1

                except Exception as task_err:
                    tasks_failed += 1
                    msg = f"Discovery task '{task.id}' failed: {task_err}"
                    execution_errors.append(msg)
                    execution_warnings.append(
                        SearchWarning(
                            code="TASK_EXECUTION_FAILED",
                            message=msg,
                            details={"task_id": task.id},
                        )
                    )

            # Determine final ResearchRun status:
            # Policy: If at least one task succeeded -> completed; if ALL tasks failed -> failed.
            end_time = datetime.now(timezone.utc).isoformat()
            if tasks_succeeded == 0 and tasks_failed > 0:
                final_status = "failed"
                err_msg = "; ".join(execution_errors) or "All discovery tasks failed during execution."
            else:
                final_status = "completed"
                err_msg = "; ".join(execution_errors) if execution_errors else None

            self.research_run_repo.update_status(
                org_id,
                run.id,
                status=final_status,
                completed_at=end_time,
                error_message=err_msg,
            )

            return SearchExecutionResult(
                plan_id=plan.id,
                organization_id=org_id,
                campaign_id=campaign_id,
                research_run_id=run.id,
                tasks_total=tasks_total,
                tasks_succeeded=tasks_succeeded,
                tasks_failed=tasks_failed,
                total_discovered_raw=total_raw,
                prospects_created=prospects_created,
                prospects_reused=prospects_reused,
                total_imported_prospects=len(imported_prospects),
                imported_prospects=imported_prospects,
                warnings=execution_warnings,
                errors=execution_errors,
                executed_at=end_time,
            )

        except Exception as fatal_err:
            end_time = datetime.now(timezone.utc).isoformat()
            self.research_run_repo.update_status(
                org_id,
                run.id,
                status="failed",
                completed_at=end_time,
                error_message=str(fatal_err),
            )
            raise DiscoveryExecutionError(f"Fatal error during discovery orchestration: {fatal_err}") from fatal_err
