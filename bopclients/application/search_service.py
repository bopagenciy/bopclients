import re
from typing import Optional, Dict, Any, List
from bopclients.domain.search_intent import SearchIntent
from bopclients.domain.exceptions import TenantAccessError
from bopclients.domain.normalizers import CategoryNormalizer
from bopclients.application.search_dto import SearchPlan, SearchExecutionResult
from bopclients.application.interfaces.search_interfaces import (
    ISearchIntentParser,
    ISearchPlanner,
)
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.application.interfaces.repositories import ICampaignRepository, IICPRepository


class SearchService:
    """Use case handler for Natural Language Search Intent parsing, planning, and execution."""

    def __init__(
        self,
        intent_parser: ISearchIntentParser,
        search_planner: ISearchPlanner,
        orchestrator: DiscoveryOrchestrator,
        campaign_repo: Optional[ICampaignRepository] = None,
        icp_repo: Optional[IICPRepository] = None,
    ):
        self.intent_parser = intent_parser
        self.search_planner = search_planner
        self.orchestrator = orchestrator
        self.campaign_repo = campaign_repo
        self.icp_repo = icp_repo

    def parse_search_intent(
        self,
        org_id: str,
        campaign_id: Optional[str],
        raw_query: str,
        context: Optional[Dict[str, Any]] = None,
        target_market_id: Optional[str] = None,
    ) -> SearchIntent:
        """Parse natural language query into a structured SearchIntent, enriched with campaign ICP and market context."""
        # 1. Parse raw natural language intent
        intent = self.intent_parser.parse(
            organization_id=org_id,
            campaign_id=campaign_id,
            raw_query=raw_query,
            context=context,
        )

        # 2. Enrich with Campaign, ICP, and Target Market context if campaign_id is provided
        if campaign_id and self.campaign_repo:
            camp = self.campaign_repo.get_by_id(org_id, campaign_id)
            if not camp:
                raise TenantAccessError(
                    f"SearchIntent parsing failed: Campaign '{campaign_id}' not found for organization '{org_id}'"
                )

            if camp.icp_id and self.icp_repo:
                icp = self.icp_repo.get_by_id(org_id, camp.icp_id)
                if icp:
                    self._enrich_intent_with_icp_context(
                        intent=intent,
                        icp=icp,
                        org_id=org_id,
                        target_market_id=target_market_id,
                    )

        return intent

    def _enrich_intent_with_icp_context(
        self,
        intent: SearchIntent,
        icp: Any,
        org_id: str,
        target_market_id: Optional[str] = None,
    ) -> None:
        """Apply ICP commercial context and Target Market geography to SearchIntent."""
        # A. ICP Industries:
        # If user did not specify industries in prompt, use compatible ICP industries as defaults
        if not intent.industries:
            default_industries: List[str] = []
            for ind in (icp.industries or []):
                norm = CategoryNormalizer.normalize(ind)
                # Never reintroduce an explicitly excluded category
                if norm and norm not in intent.negative_keywords and norm not in default_industries:
                    default_industries.append(norm)

            # Drop generic healthcare if specific associations/clinics are present
            if any(c in default_industries for c in ("medical_association", "scientific_society", "professional_association", "clinic")):
                default_industries = [c for c in default_industries if c != "healthcare"]

            if default_industries:
                intent.industries = default_industries
                intent.business_categories = list(default_industries)

        # B. ICP Company Sizes:
        # If user did not specify company size in prompt, use ICP size configuration
        if intent.company_size_min is None and intent.company_size_max is None:
            if icp.company_sizes:
                intent.company_sizes = list(icp.company_sizes)
                mins: List[int] = []
                maxs: List[int] = []
                for s in icp.company_sizes:
                    m = re.match(r'(\d+)(?:\s*(?:-|a|to)\s*(\d+))?', s.strip())
                    if m:
                        mins.append(int(m.group(1)))
                        if m.group(2):
                            maxs.append(int(m.group(2)))
                if mins:
                    intent.company_size_min = min(mins)
                if maxs:
                    intent.company_size_max = max(maxs)
        elif not intent.company_sizes:
            intent.company_sizes = [f"{intent.company_size_min or 1}-{intent.company_size_max or 'Any'}"]

        # C. Target Market Resolution:
        markets = icp.target_markets or []
        chosen_market = None

        if target_market_id:
            matched = [m for m in markets if m.id == target_market_id]
            if not matched:
                raise TenantAccessError(
                    f"Target market '{target_market_id}' does not belong to the selected campaign's ICP in organization '{org_id}'"
                )
            chosen_market = matched[0]
        elif len(markets) == 1:
            chosen_market = markets[0]
        elif len(markets) > 1:
            # Check for unambiguous match to prompt stated city
            prompt_cities = [c.lower() for c in intent.cities]
            city_matches = [m for m in markets if m.city and m.city.lower() in prompt_cities]
            if len(city_matches) == 1:
                chosen_market = city_matches[0]
            else:
                # Ambiguous or no match: require explicit user selection (do NOT silently default)
                chosen_market = None
                if "MULTIPLE_TARGET_MARKETS_REQUIRE_SELECTION" not in intent.warnings:
                    intent.warnings.append("MULTIPLE_TARGET_MARKETS_REQUIRE_SELECTION")

        if chosen_market:
            # Location precedence:
            if not intent.cities:
                intent.target_market_id = chosen_market.id
                if chosen_market.city:
                    intent.cities = [chosen_market.city]
                if chosen_market.region:
                    intent.regions = [chosen_market.region]
                if chosen_market.country:
                    intent.countries = [chosen_market.country]
                if chosen_market.postal_code:
                    intent.postal_codes = [chosen_market.postal_code]
                intent.radius_miles = chosen_market.radius_miles
                if not intent.languages and chosen_market.language:
                    intent.languages = [chosen_market.language]
            else:
                if any(c.lower() == (chosen_market.city or "").lower() for c in intent.cities):
                    intent.target_market_id = chosen_market.id
                    if chosen_market.region and not intent.regions:
                        intent.regions = [chosen_market.region]
                    if chosen_market.country and not intent.countries:
                        intent.countries = [chosen_market.country]
                    if chosen_market.postal_code and not intent.postal_codes:
                        intent.postal_codes = [chosen_market.postal_code]
                    intent.radius_miles = chosen_market.radius_miles
                    if not intent.languages and chosen_market.language:
                        intent.languages = [chosen_market.language]
                else:
                    # Explicit user location override: clear incompatible inherited fields
                    intent.target_market_id = None
                    intent.regions = []
                    intent.postal_codes = []
                    intent.radius_miles = None

    def plan_search(self, intent: SearchIntent) -> SearchPlan:
        """Generate an executable SearchPlan without executing discovery (Dry Run / Plan Only)."""
        if intent.campaign_id and self.campaign_repo:
            camp = self.campaign_repo.get_by_id(intent.organization_id, intent.campaign_id)
            if not camp:
                raise TenantAccessError(
                    f"Search planning failed: Campaign '{intent.campaign_id}' not found for organization '{intent.organization_id}'"
                )

            # Re-validate target_market_id if provided
            if intent.target_market_id and self.icp_repo and camp.icp_id:
                icp = self.icp_repo.get_by_id(intent.organization_id, camp.icp_id)
                if not icp or not any(m.id == intent.target_market_id for m in (icp.target_markets or [])):
                    raise TenantAccessError(
                        f"Target market '{intent.target_market_id}' does not belong to campaign '{intent.campaign_id}' ICP in organization '{intent.organization_id}'"
                    )

        return self.search_planner.plan(intent)

    def execute_search(
        self, org_id: str, campaign_id: Optional[str], search_plan: SearchPlan
    ) -> SearchExecutionResult:
        """Execute a SearchPlan via DiscoveryOrchestrator with full tenant and active campaign policy validation."""
        target_campaign_id = campaign_id or search_plan.campaign_id

        if not target_campaign_id:
            from bopclients.domain.exceptions import SearchPlanningError
            raise SearchPlanningError(
                "Discovery execution requires an active campaign_id. Campaign-less execution is restricted to plan_search (plan only)."
            )

        if search_plan.organization_id != org_id:
            raise TenantAccessError("SearchPlan organization_id mismatch")

        if campaign_id and search_plan.campaign_id and campaign_id != search_plan.campaign_id:
            raise TenantAccessError("SearchPlan campaign_id mismatch")

        # Fail-closed guard: block unsafe execution when target market selection is ambiguous
        if any(w.code == "MULTIPLE_TARGET_MARKETS_REQUIRE_SELECTION" for w in search_plan.warnings):
            from bopclients.domain.exceptions import SearchPlanningError
            raise SearchPlanningError(
                "Discovery execution blocked: Multiple target markets are configured for this campaign ICP. Explicit target market selection is required."
            )

        if self.campaign_repo:
            camp = self.campaign_repo.get_by_id(org_id, target_campaign_id)
            if not camp:
                raise TenantAccessError(
                    f"Execution failed: Campaign '{target_campaign_id}' not found for organization '{org_id}'"
                )

            # Enforce Campaign Status Policy: Only "active" campaigns can execute discovery
            status_val = camp.status.value if hasattr(camp.status, "value") else str(camp.status)
            if status_val != "active":
                raise TenantAccessError(
                    f"Execution rejected: Campaign '{target_campaign_id}' status is '{status_val}'. Discovery execution is only allowed for 'active' campaigns."
                )

        return self.orchestrator.execute_plan(search_plan)

    def preview_search(
        self, org_id: str, campaign_id: Optional[str], search_plan: SearchPlan
    ) -> SearchExecutionResult:
        """Execute a search plan in dry-run preview mode without inserting prospects or database records."""
        from bopclients.domain.exceptions import SearchPlanningError
        if search_plan.organization_id != org_id:
            raise TenantAccessError("SearchPlan organization_id mismatch")

        if campaign_id and search_plan.campaign_id and campaign_id != search_plan.campaign_id:
            raise TenantAccessError("SearchPlan campaign_id mismatch")

        if campaign_id and self.campaign_repo:
            camp = self.campaign_repo.get_by_id(org_id, campaign_id)
            if not camp:
                raise TenantAccessError(
                    f"Preview failed: Campaign '{campaign_id}' not found for organization '{org_id}'"
                )

        # Budget and task validation for web search preview
        web_tasks = [
            t for t in search_plan.tasks
            if (t.provider or "").strip().lower() in ("web_search", "tavily")
        ]
        if len(web_tasks) > 1:
            raise SearchPlanningError(
                f"Controlled preview budget violation: Maximum 1 web search query allowed (received {len(web_tasks)})."
            )

        for wt in web_tasks:
            if wt.limit > 5:
                raise SearchPlanningError(
                    f"Controlled preview budget violation: Task limit ({wt.limit}) exceeds maximum allowed of 5 results."
                )

        return self.orchestrator.preview_plan(search_plan)

    def create_web_search_preview_plan(
        self,
        org_id: str,
        query: str,
        campaign_id: Optional[str] = None,
        category: str = "medical_association",
        country: str = "CO",
        city: Optional[str] = "Cali",
        region: Optional[str] = "Valle del Cauca",
        limit: int = 5,
        negative_keywords: Optional[List[str]] = None,
    ) -> SearchPlan:
        """Construct a single-query, budget-bounded web search plan for controlled preview."""
        import uuid
        from bopclients.application.search_dto import DiscoveryTask

        clamped_limit = min(max(1, limit), 5)
        default_negs = ["hospital", "clinica", "clínica", "consultorio", "eps", "ips"]
        negs = list(negative_keywords) if negative_keywords is not None else default_negs

        task = DiscoveryTask(
            id=str(uuid.uuid4()),
            provider="web_search",
            query=query.strip(),
            category=category,
            country=country,
            city=city,
            region=region,
            limit=clamped_limit,
            priority=1,
            negative_keywords=negs,
            metadata={"organization_id": org_id, "preview": True},
        )

        return SearchPlan(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            campaign_id=campaign_id,
            intent_id="web_preview",
            tasks=[task],
        )
