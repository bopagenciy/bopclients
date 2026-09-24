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
        self.providers = {}
        for p in providers:
            p_name = p.name.lower()
            self.providers[p_name] = p
            if p_name == "web_search":
                self.providers["tavily"] = p
        self.prospect_service = prospect_service
        self.research_run_repo = research_run_repo
        self.campaign_repo = campaign_repo

    def execute_plan(
        self, plan: SearchPlan, max_results_override: Optional[int] = None
    ) -> SearchExecutionResult:
        org_id = plan.organization_id
        campaign_id = plan.campaign_id

        # Safety Gate: Fail closed if any task targets Tavily in live import mode
        from bopclients.infrastructure.providers.tavily_transport import TavilyWebSearchTransport
        for task in plan.tasks:
            p_name = (task.provider or "").strip().lower()
            if p_name == "tavily":
                raise DiscoveryExecutionError(
                    "Direct prospect import is not authorized for Tavily provider. Preview mode only."
                )
            prov = self.providers.get(p_name)
            if prov and hasattr(prov, "_transport") and isinstance(prov._transport, TavilyWebSearchTransport):
                raise DiscoveryExecutionError(
                    "Direct prospect import is not authorized for Tavily provider. Preview mode only."
                )

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

    def preview_plan(
        self, plan: SearchPlan, max_results_override: Optional[int] = None
    ) -> SearchExecutionResult:
        """Execute search plan in strictly bounded, zero-persistence preview mode.

        Guarantees:
        1. ZERO prospect inserts (ProspectService.add_prospect is never called).
        2. ZERO prospect source inserts.
        3. ZERO campaign prospect inserts.
        4. ZERO ResearchRun database records saved or updated.
        5. ZERO CRM synchronization or outbox dispatches.
        6. ZERO AI/Gemini research worker jobs.
        7. Strict budget enforcement (for web_search/Tavily: max 1 query, max 5 results).
        """
        from datetime import datetime, timezone
        org_id = plan.organization_id
        campaign_id = plan.campaign_id

        # Validate campaign tenant ownership if campaign_id is supplied
        if campaign_id and self.campaign_repo:
            camp = self.campaign_repo.get_by_id(org_id, campaign_id)
            if not camp:
                raise TenantAccessError(
                    f"Execution rejected: Campaign '{campaign_id}' not found for organization '{org_id}'"
                )

        # Web search / Tavily pilot constraints check:
        web_tasks = [
            t for t in plan.tasks
            if (t.provider or "").strip().lower() in ("web_search", "tavily")
        ]
        if len(web_tasks) > 1:
            raise DiscoveryExecutionError(
                f"Controlled preview budget violation: Maximum 1 web search query allowed (received {len(web_tasks)})."
            )

        for wt in web_tasks:
            if wt.limit > 5:
                raise DiscoveryExecutionError(
                    f"Controlled preview budget violation: Task '{wt.id}' limit ({wt.limit}) exceeds maximum allowed of 5 results."
                )
            if wt.limit <= 0:
                raise DiscoveryExecutionError(
                    f"Controlled preview budget violation: Task '{wt.id}' limit ({wt.limit}) must be > 0."
                )
            wt.metadata["organization_id"] = org_id

        total_raw = 0
        candidates: List[Dict[str, Any]] = []
        batch_seen_keys: Set[Tuple[str, str]] = set()
        execution_warnings: List[SearchWarning] = list(plan.warnings)
        execution_errors: List[str] = []

        tasks_total = len(plan.tasks)
        tasks_succeeded = 0
        tasks_failed = 0

        max_results_limit = max_results_override or 5

        for task in plan.tasks:
            p_name = (task.provider or "").strip().lower()
            provider = self.providers.get(p_name)
            if not provider and p_name == "tavily":
                provider = self.providers.get("web_search")

            if not provider or not provider.supports(task):
                tasks_failed += 1
                msg = f"No active or enabled discovery provider registered for '{task.provider}'."
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
                if p_name in ("web_search", "tavily"):
                    task.limit = min(task.limit or 5, 5)

                discovered_batch = provider.discover(task)
                tasks_succeeded += 1
                total_raw += len(discovered_batch)

                for biz in discovered_batch:
                    if len(candidates) >= max_results_limit:
                        break

                    ext_id = biz.overture_id or ""
                    norm_url = (biz.website_url or "").strip().lower().rstrip("/")
                    batch_key = (ext_id, norm_url)

                    if batch_key in batch_seen_keys and (ext_id or norm_url):
                        continue
                    if ext_id or norm_url:
                        batch_seen_keys.add(batch_key)

                    candidate_info = {
                        "candidate_id": biz.overture_id,
                        "name": biz.name,
                        "website_url": biz.website_url,
                        "category": biz.category,
                        "city": biz.city,
                        "state": biz.state,
                        "country": task.country or "CO",
                        "geographic_scope": biz.raw_data.get("geographic_scope") if biz.raw_data else None,
                        "classification_status": biz.raw_data.get("classification_status") if biz.raw_data else None,
                        "classification_details": biz.raw_data.get("classification_details") if biz.raw_data else None,
                        "title": biz.raw_data.get("title") if biz.raw_data else None,
                        "snippet": biz.raw_data.get("snippet") if biz.raw_data else None,
                        "source": p_name,
                        # Structured Candidate Qualification:
                        "qualification_status": biz.raw_data.get("qualification_status") if biz.raw_data else None,
                        "entity_archetype": biz.raw_data.get("entity_archetype") if biz.raw_data else None,
                        "geographic_evidence_status": biz.raw_data.get("geographic_evidence_status") if biz.raw_data else None,
                        "current_activity_status": biz.raw_data.get("current_activity_status") if biz.raw_data else None,
                        "source_url": biz.raw_data.get("source_url") if biz.raw_data else None,
                        "source_host": biz.raw_data.get("source_host") if biz.raw_data else None,
                        "organization_website": biz.raw_data.get("organization_website") if biz.raw_data else None,
                        "is_commercial_review_ready": biz.raw_data.get("is_commercial_review_ready") if biz.raw_data else None,
                        "qualification_reasons": biz.raw_data.get("qualification_reasons") if biz.raw_data else None,
                        "missing_evidence": biz.raw_data.get("missing_evidence") if biz.raw_data else None,
                    }
                    candidates.append(candidate_info)

            except Exception as task_err:
                tasks_failed += 1
                msg = f"Discovery preview task '{task.id}' failed: {task_err}"
                execution_errors.append(msg)
                execution_warnings.append(
                    SearchWarning(
                        code="TASK_EXECUTION_FAILED",
                        message=msg,
                        details={"task_id": task.id},
                    )
                )

        # Collect preview funnel diagnostics if provided by discovery task
        preview_diagnostics: Optional[Dict[str, Any]] = None
        for task in plan.tasks:
            if isinstance(task.metadata, dict) and "diagnostics" in task.metadata:
                d = task.metadata["diagnostics"]
                if preview_diagnostics is None:
                    preview_diagnostics = {
                        "provider_results_received": d.get("provider_results_received", 0),
                        "results_missing_required_fields": d.get("results_missing_required_fields", 0),
                        "results_rejected_by_classifier": d.get("results_rejected_by_classifier", 0),
                        "results_accepted_by_classifier": d.get("results_accepted_by_classifier", 0),
                        "directory_candidates_retained": d.get("directory_candidates_retained", 0),
                        "candidates_returned_to_preview": len(candidates),
                        "rejection_reasons": dict(d.get("rejection_reasons") or {}),
                    }
                else:
                    preview_diagnostics["provider_results_received"] += d.get("provider_results_received", 0)
                    preview_diagnostics["results_missing_required_fields"] += d.get("results_missing_required_fields", 0)
                    preview_diagnostics["results_rejected_by_classifier"] += d.get("results_rejected_by_classifier", 0)
                    preview_diagnostics["results_accepted_by_classifier"] += d.get("results_accepted_by_classifier", 0)
                    preview_diagnostics["directory_candidates_retained"] += d.get("directory_candidates_retained", 0)
                    preview_diagnostics["candidates_returned_to_preview"] = len(candidates)
                    for r_code, r_cnt in (d.get("rejection_reasons") or {}).items():
                        preview_diagnostics["rejection_reasons"][r_code] = preview_diagnostics["rejection_reasons"].get(r_code, 0) + r_cnt

        if preview_diagnostics is not None:
            preview_diagnostics["candidates_returned_to_preview"] = len(candidates)

        end_time = datetime.now(timezone.utc).isoformat()

        return SearchExecutionResult(
            plan_id=plan.id,
            organization_id=org_id,
            campaign_id=campaign_id,
            research_run_id="",  # Zero DB writes: no research run record
            tasks_total=tasks_total,
            tasks_succeeded=tasks_succeeded,
            tasks_failed=tasks_failed,
            total_discovered_raw=total_raw,
            prospects_created=0,  # Zero prospect inserts
            prospects_reused=0,
            total_imported_prospects=0,  # Zero prospect imports
            imported_prospects=[],  # Zero prospect imports
            candidates=candidates,  # Transient candidate list
            warnings=execution_warnings,
            errors=execution_errors,
            diagnostics=preview_diagnostics,
            executed_at=end_time,
        )
