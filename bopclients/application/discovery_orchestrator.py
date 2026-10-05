"""Discovery Orchestrator executing SearchPlans, deduplicating raw results, and updating ResearchRuns."""

from typing import List, Dict, Set, Optional, Tuple, Any
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
        MAX_PREVIEW_QUERIES = 2
        web_tasks = [
            t for t in plan.tasks
            if (t.provider or "").strip().lower() in ("web_search", "tavily")
        ]
        if len(web_tasks) > MAX_PREVIEW_QUERIES:
            raise DiscoveryExecutionError(
                f"Controlled preview budget violation: Maximum {MAX_PREVIEW_QUERIES} web search queries allowed (received {len(web_tasks)})."
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
        execution_warnings: List[SearchWarning] = list(plan.warnings)
        execution_errors: List[str] = []

        tasks_total = len(plan.tasks)
        tasks_succeeded = 0
        tasks_failed = 0
        executed_queries: List[str] = []

        # Multi-task candidate aggregation buffer before fair presentation
        task_candidates: List[List[Dict[str, Any]]] = []
        max_task_candidates = 5

        # Shared multi-tenant or directory hosts where multiple legitimate entities reside
        from bopclients.application.discovery.candidate_qualifier import (
            OrganizationCandidateQualifier,
            EntityArchetype,
        )
        SHARED_PLATFORM_HOSTS = set(OrganizationCandidateQualifier.DIRECTORY_HOSTS) | set(
            OrganizationCandidateQualifier.ARCHIVE_HOSTS
        ) | {
            "gov.co", "valledelcauca.gov.co", "cali.gov.co", "bogota.gov.co",
            "medellin.gov.co", "usa.gov", "nih.gov", "who.int", "paho.org",
            "medium.com", "blogspot.com", "wordpress.com", "wixsite.com",
            "sites.google.com", "github.io", "github.com", "facebook.com",
            "instagram.com", "twitter.com", "x.com", "linkedin.com", "youtube.com"
        }

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
                if task.query and task.query not in executed_queries:
                    executed_queries.append(task.query)

                if p_name in ("web_search", "tavily"):
                    task.limit = min(task.limit or 5, 5)

                discovered_batch = provider.discover(task)
                tasks_succeeded += 1
                total_raw += len(discovered_batch)

                this_task_list: List[Dict[str, Any]] = []

                for biz in discovered_batch:
                    if len(this_task_list) >= max_task_candidates:
                        break

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
                    this_task_list.append(candidate_info)

                task_candidates.append(this_task_list)

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

        # FAIR COMBINATION: Interleave results across tasks to ensure Query 2 is never starved
        interleaved: List[Dict[str, Any]] = []
        max_len = max((len(t) for t in task_candidates), default=0)
        for i in range(max_len):
            for t_list in task_candidates:
                if i < len(t_list):
                    interleaved.append(t_list[i])

        # STAGED ENTITY-SAFE DEDUPLICATION:
        # LEVEL 1: Exact normalized URL
        # LEVEL 2: Existing external candidate_id
        # LEVEL 3: Consistent normalized organization identity AND compatible first-party host
        import re
        import urllib.parse
        import unicodedata

        candidates: List[Dict[str, Any]] = []
        seen_exact_urls: Set[str] = set()
        seen_candidate_ids: Set[str] = set()
        seen_first_party_entities: Set[Tuple[str, str]] = set()  # (clean_name_key, clean_host)
        duplicate_candidates_removed = 0
        source_records_bundled = 0
        final_candidate_cap = max_results_override or (10 if len(web_tasks) > 1 else 5)

        def _clean_name_key(n: str) -> str:
            if not n:
                return ""
            k = re.sub(r"[^a-zA-Z0-9áéíóúñÁÉÍÓÚÑ]", "", n.lower())
            return k

        def _clean_entity_name_for_bundling(name: str) -> str:
            if not name:
                return ""
            cleaned = re.sub(r"\s*\(@?[a-zA-Z0-9_.-]+\)", "", name)
            cleaned = re.sub(
                r"\s+[-–—|/]\s*(?:facebook|twitter|instagram|linkedin|youtube|x|photos\s+and\s+videos|fotos\s+y\s+videos|inicio|home|perfil|profile)\b.*",
                "",
                cleaned,
                flags=re.IGNORECASE,
            )
            cleaned = re.sub(r"\s+@([a-zA-Z0-9_.-]+)$", "", cleaned)
            return cleaned.strip()

        def _tokenize_entity_name(name: str) -> List[str]:
            if not name:
                return []
            cleaned_name = _clean_entity_name_for_bundling(name)
            normalized = unicodedata.normalize("NFKD", cleaned_name.lower())
            ascii_text = "".join(c for c in normalized if not unicodedata.combining(c))
            clean = re.sub(r"[^a-z0-9\s]", " ", ascii_text)
            stopwords = {
                "de", "del", "la", "el", "los", "las", "y", "en", "por", "para", "con",
                "of", "the", "and", "in", "for", "at", "by", "un", "una", "unos", "unas",
                "facebook", "twitter", "instagram", "linkedin", "youtube"
            }
            tokens = [t for t in clean.split() if t and t not in stopwords]
            return tokens

        def _determine_source_evidence(c: Dict[str, Any]) -> Dict[str, Any]:
            c_url = (c.get("website_url") or c.get("source_url") or "").strip()
            c_norm = c_url.lower().rstrip("/")
            p = urllib.parse.urlparse(c_norm)
            c_host = (p.netloc or "").lower().strip()
            if c_host.startswith("www."):
                c_host = c_host[4:]
            c_arch = c.get("entity_archetype")
            c_org_web = c.get("organization_website") or ""

            social_domains = {
                "facebook.com", "x.com", "twitter.com", "linkedin.com", "instagram.com", "youtube.com"
            }
            gov_domains = {
                "gov.co", "valledelcauca.gov.co", "cali.gov.co", "bogota.gov.co",
                "medellin.gov.co", "usa.gov", "nih.gov", "who.int", "paho.org"
            }

            c_platform = None
            for sd in social_domains:
                if c_host == sd or c_host.endswith(f".{sd}"):
                    c_platform = sd
                    break

            if c_platform:
                src_type = "SOCIAL_PROFILE"
            elif any(c_host == gd or c_host.endswith(f".{gd}") for gd in gov_domains) or c_host.endswith(".gov") or c_host.endswith(".gov.co"):
                src_type = "GOVERNMENT_SOURCE"
            elif c_arch in ("DIRECTORY_LISTING", EntityArchetype.DIRECTORY_LISTING.value):
                src_type = "DIRECTORY_LISTING"
            elif c_org_web and c_org_web != "UNKNOWN":
                p_org = urllib.parse.urlparse(c_org_web if "://" in c_org_web else f"https://{c_org_web}")
                org_h = (p_org.netloc or "").lower().strip()
                if org_h.startswith("www."):
                    org_h = org_h[4:]
                if org_h == c_host or c_host.endswith(f".{org_h}"):
                    src_type = "OFFICIAL_WEBSITE"
                else:
                    src_type = "THIRD_PARTY_PAGE"
            else:
                src_type = "THIRD_PARTY_PAGE"

            return {
                "source_url": c_url,
                "source_host": c_host,
                "source_type": src_type,
                "platform": c_platform,
                "title": c.get("title") or c.get("name"),
                "snippet": c.get("snippet"),
            }

        def _candidate_canonical_priority(c: Dict[str, Any]) -> int:
            src = _determine_source_evidence(c)
            st = src["source_type"]
            if st == "OFFICIAL_WEBSITE":
                return 100
            if st == "GOVERNMENT_SOURCE":
                return 60
            if st == "SOCIAL_PROFILE":
                plat = src.get("platform")
                if plat == "linkedin.com":
                    return 50
                if plat in ("x.com", "twitter.com"):
                    return 45
                if plat == "facebook.com":
                    return 40
                return 35
            if st == "THIRD_PARTY_PAGE":
                return 20
            return 10

        def _can_bundle_candidates(cand_a: Dict[str, Any], cand_b: Dict[str, Any]) -> bool:
            # 1. Country compatibility check
            country_a = (cand_a.get("country") or "").strip().upper()
            country_b = (cand_b.get("country") or "").strip().upper()
            if country_a and country_b and country_a != country_b:
                return False

            # 2. Source evidence & Directory publisher exclusion
            src_a = _determine_source_evidence(cand_a)
            src_b = _determine_source_evidence(cand_b)
            st_a = src_a["source_type"]
            st_b = src_b["source_type"]
            h_a = src_a["source_host"]
            h_b = src_b["source_host"]

            # Genuine directory listings must NEVER bundle with an organization
            if st_a == "DIRECTORY_LISTING" or st_b == "DIRECTORY_LISTING":
                return False

            # 3. Archetype compatibility check (for non-social candidates)
            arch_a = cand_a.get("entity_archetype")
            arch_b = cand_b.get("entity_archetype")
            if st_a != "SOCIAL_PROFILE" and st_b != "SOCIAL_PROFILE":
                if arch_a and arch_b and arch_a != arch_b:
                    return False

            # 4. Normalized full institutional name token concordance
            tokens_a = _tokenize_entity_name(cand_a.get("name") or "")
            tokens_b = _tokenize_entity_name(cand_b.get("name") or "")

            # Specificity threshold: must have >= 3 significant tokens
            if len(tokens_a) < 3 or len(tokens_b) < 3:
                return False

            if tokens_a != tokens_b:
                return False

            # 5. Source & Anchor compatibility
            has_official = (st_a == "OFFICIAL_WEBSITE" or st_b == "OFFICIAL_WEBSITE")
            both_social = (st_a == "SOCIAL_PROFILE" and st_b == "SOCIAL_PROFILE")
            same_first_party_domain = (bool(h_a) and h_a == h_b and not (h_a in SHARED_PLATFORM_HOSTS))
            has_gov = (st_a == "GOVERNMENT_SOURCE" or st_b == "GOVERNMENT_SOURCE")

            if has_official or both_social or same_first_party_domain or has_gov:
                return True

            return False

        for cand in interleaved:
            c_id = cand.get("candidate_id") or ""
            raw_url = cand.get("website_url") or ""
            norm_url = raw_url.strip().lower().rstrip("/")
            parsed = urllib.parse.urlparse(norm_url)
            host = (parsed.netloc or "").lower().strip()
            if host.startswith("www."):
                host = host[4:]

            c_name = cand.get("name") or ""
            name_key = _clean_name_key(c_name)
            arch = cand.get("entity_archetype")

            # Level 1: Exact URL check
            if norm_url and norm_url in seen_exact_urls:
                duplicate_candidates_removed += 1
                continue

            # Level 2: Candidate external ID check
            if c_id and c_id in seen_candidate_ids:
                duplicate_candidates_removed += 1
                continue

            # Level 3: First-party domain entity deduplication (/inicio vs /contacto on same site)
            org_web = cand.get("organization_website") or ""
            org_host = ""
            if org_web and org_web != "UNKNOWN":
                parsed_org = urllib.parse.urlparse(org_web if "://" in org_web else f"https://{org_web}")
                org_host = (parsed_org.netloc or "").lower().strip()
                if org_host.startswith("www."):
                    org_host = org_host[4:]

            is_shared_platform = (
                host in SHARED_PLATFORM_HOSTS
                or any(host.endswith(f".{sph}") for sph in SHARED_PLATFORM_HOSTS)
                or arch == EntityArchetype.DIRECTORY_LISTING.value
                or arch == "DIRECTORY_LISTING"
            )

            is_verified_first_party = (
                not is_shared_platform
                and bool(org_host)
                and (org_host == host or host.endswith(f".{org_host}"))
            )

            if is_verified_first_party and host and name_key:
                first_party_key = (name_key, host)
                if first_party_key in seen_first_party_entities:
                    duplicate_candidates_removed += 1
                    continue
                seen_first_party_entities.add(first_party_key)

            if norm_url:
                seen_exact_urls.add(norm_url)
            if c_id:
                seen_candidate_ids.add(c_id)

            # STAGE 4: CROSS-SOURCE ENTITY BUNDLING & SOCIAL PROFILE AGGREGATION
            cand_source = _determine_source_evidence(cand)
            cand["sources"] = [cand_source]
            cand["sources_count"] = 1

            # Check if this candidate can bundle into an existing candidate
            bundled = False
            for existing in candidates:
                if _can_bundle_candidates(existing, cand):
                    bundled = True
                    source_records_bundled += 1

                    # Add new source to existing candidate's sources list if not already present
                    if not any(s.get("source_url") == cand_source["source_url"] for s in existing.get("sources", [])):
                        existing["sources"].append(cand_source)
                        existing["sources_count"] = len(existing["sources"])

                    # Canonical selection:
                    # If incoming candidate has higher canonical priority (e.g. verified official website
                    # while existing was social profile), upgrade canonical display fields
                    if _candidate_canonical_priority(cand) > _candidate_canonical_priority(existing):
                        merged_sources = existing["sources"]
                        existing.update(cand)
                        existing["sources"] = merged_sources
                        existing["sources_count"] = len(merged_sources)

                    break

            if not bundled:
                if len(candidates) < final_candidate_cap:
                    candidates.append(cand)

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
                        "duplicate_candidates_removed": duplicate_candidates_removed,
                        "source_records_bundled": source_records_bundled,
                        "candidates_returned_to_preview": len(candidates),
                        "rejection_reasons": dict(d.get("rejection_reasons") or {}),
                    }
                else:
                    preview_diagnostics["provider_results_received"] += d.get("provider_results_received", 0)
                    preview_diagnostics["results_missing_required_fields"] += d.get("results_missing_required_fields", 0)
                    preview_diagnostics["results_rejected_by_classifier"] += d.get("results_rejected_by_classifier", 0)
                    preview_diagnostics["results_accepted_by_classifier"] += d.get("results_accepted_by_classifier", 0)
                    preview_diagnostics["directory_candidates_retained"] += d.get("directory_candidates_retained", 0)
                    preview_diagnostics["duplicate_candidates_removed"] = duplicate_candidates_removed
                    preview_diagnostics["source_records_bundled"] = source_records_bundled
                    preview_diagnostics["candidates_returned_to_preview"] = len(candidates)
                    for r_code, r_cnt in (d.get("rejection_reasons") or {}).items():
                        preview_diagnostics["rejection_reasons"][r_code] = preview_diagnostics["rejection_reasons"].get(r_code, 0) + r_cnt

        if preview_diagnostics is not None:
            preview_diagnostics["candidates_returned_to_preview"] = len(candidates)
            preview_diagnostics["duplicate_candidates_removed"] = duplicate_candidates_removed
            preview_diagnostics["source_records_bundled"] = source_records_bundled

        end_time = datetime.now(timezone.utc).isoformat()
        primary_query = executed_queries[0] if executed_queries else None

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
            executed_query=primary_query,
            executed_queries=executed_queries if executed_queries else None,
            executed_at=end_time,
        )
