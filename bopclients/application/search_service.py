"""Search application service providing parse_search_intent, plan_search, and execute_search use cases."""

from typing import Optional, Dict, Any
from bopclients.domain.search_intent import SearchIntent
from bopclients.domain.exceptions import TenantAccessError
from bopclients.application.search_dto import SearchPlan, SearchExecutionResult
from bopclients.application.interfaces.search_interfaces import (
    ISearchIntentParser,
    ISearchPlanner,
)
from bopclients.application.discovery_orchestrator import DiscoveryOrchestrator
from bopclients.application.interfaces.repositories import ICampaignRepository


class SearchService:
    """Use case handler for Natural Language Search Intent parsing, planning, and execution."""

    def __init__(
        self,
        intent_parser: ISearchIntentParser,
        search_planner: ISearchPlanner,
        orchestrator: DiscoveryOrchestrator,
        campaign_repo: Optional[ICampaignRepository] = None,
    ):
        self.intent_parser = intent_parser
        self.search_planner = search_planner
        self.orchestrator = orchestrator
        self.campaign_repo = campaign_repo

    def parse_search_intent(
        self,
        org_id: str,
        campaign_id: Optional[str],
        raw_query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> SearchIntent:
        """Parse natural language query into a structured SearchIntent."""
        if campaign_id and self.campaign_repo:
            camp = self.campaign_repo.get_by_id(org_id, campaign_id)
            if not camp:
                raise TenantAccessError(
                    f"SearchIntent parsing failed: Campaign '{campaign_id}' not found for organization '{org_id}'"
                )

        return self.intent_parser.parse(
            organization_id=org_id,
            campaign_id=campaign_id,
            raw_query=raw_query,
            context=context,
        )

    def plan_search(self, intent: SearchIntent) -> SearchPlan:
        """Generate an executable SearchPlan without executing discovery (Dry Run / Plan Only)."""
        if intent.campaign_id and self.campaign_repo:
            camp = self.campaign_repo.get_by_id(intent.organization_id, intent.campaign_id)
            if not camp:
                raise TenantAccessError(
                    f"Search planning failed: Campaign '{intent.campaign_id}' not found for organization '{intent.organization_id}'"
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
