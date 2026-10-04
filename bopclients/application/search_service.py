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

        # D. Structured General-Purpose ICP Context:
        if hasattr(icp, "get_effective_organization_types"):
            eff_org_types = icp.get_effective_organization_types()
            if eff_org_types and not getattr(intent, "target_organization_types", None):
                intent.target_organization_types = list(eff_org_types)

        if hasattr(icp, "get_effective_business_activities"):
            eff_acts = icp.get_effective_business_activities()
            if eff_acts and not getattr(intent, "target_business_activities", None):
                intent.target_business_activities = list(eff_acts)

        if hasattr(icp, "get_effective_target_offerings"):
            eff_offs = icp.get_effective_target_offerings()
            if eff_offs and not getattr(intent, "target_offerings", None):
                intent.target_offerings = list(eff_offs)

        if hasattr(icp, "get_effective_specializations"):
            eff_specs = icp.get_effective_specializations()
            if eff_specs and not getattr(intent, "target_specializations", None):
                intent.target_specializations = list(eff_specs)

        if hasattr(icp, "get_effective_excluded_organization_types"):
            eff_ex_orgs = icp.get_effective_excluded_organization_types()
            if eff_ex_orgs:
                intent.excluded_organization_types = list(eff_ex_orgs)
                for ex in eff_ex_orgs:
                    if ex not in intent.negative_keywords:
                        intent.negative_keywords.append(ex)

        if hasattr(icp, "get_effective_excluded_attributes"):
            eff_ex_attrs = icp.get_effective_excluded_attributes()
            if eff_ex_attrs:
                intent.excluded_attributes = list(eff_ex_attrs)
                for ex in eff_ex_attrs:
                    if ex not in intent.negative_keywords:
                        intent.negative_keywords.append(ex)

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

    def synthesize_preview_query(
        self,
        raw_query: Optional[str] = None,
        campaign: Optional[Any] = None,
        icp: Optional[Any] = None,
        target_market: Optional[Any] = None,
        category: Optional[str] = None,
        city: Optional[str] = None,
        region: Optional[str] = None,
        country: Optional[str] = None,
    ) -> str:
        """Deterministically synthesize a concise, high-signal provider query from ICP, campaign, and geography.

        Priority order:
        A. Derive the strongest concise organization/sector concept from structured ICP metadata.
        B. Add the most specific target geography (city -> region -> country).
        C. Avoid long sentence-style queries and redundant geographic terms.
        D. Safely fall back to raw_query if structured context is absent or incomplete.
        """
        clean_raw = (raw_query or "").strip()
        # Strip common conversational noise prefixes and suffixes
        for prefix in (
            "por favor buscar", "por favor busque", "por favor busca", "por favor",
            "buscar", "busque", "busca", "encuentra", "encontrar",
            "please search for", "please search", "please find", "search for", "find",
        ):
            if clean_raw.lower().startswith(prefix):
                clean_raw = clean_raw[len(prefix):].strip()
                break
        for suffix in ("muchas gracias", "gracias", "por favor", "thank you", "thanks", "please"):
            if clean_raw.lower().endswith(suffix):
                clean_raw = clean_raw[:-len(suffix)].strip()
                break

        # Step 1: Derive core sector / organization concept from structured ICP or Category
        concept = None

        if icp:
            target_org_types = getattr(icp, "target_organization_types", None) or []
            target_industries = getattr(icp, "target_industries", None) or []
            target_specializations = getattr(icp, "target_specializations", None) or []
            industries = getattr(icp, "industries", None) or []

            # Filter generic industries like "salud", "healthcare", "general", "business"
            specific_industries = [
                ind.strip() for ind in (target_industries or industries)
                if ind and ind.strip().lower() not in ("salud", "healthcare", "general", "business", "servicios", "services")
            ]

            is_assoc = (
                any("asociaci" in ot.lower() or "sociedad" in ot.lower() or "association" in ot.lower() or "society" in ot.lower() for ot in target_org_types)
                or any("asociaci" in ind.lower() or "sociedad" in ind.lower() or "association" in ind.lower() or "society" in ind.lower() for ind in specific_industries)
                or category == "medical_association"
            )

            # Determine language context from target market, country, or raw query
            tm_lang = (getattr(target_market, "language", None) or "").strip().lower()
            tm_country = (getattr(target_market, "country", None) or country or "").strip().upper()
            is_spanish = tm_lang.startswith("es") or tm_country == "CO" or any(w in clean_raw.lower() for w in ("asociaciones", "sociedades", "médicas", "en", "colombia"))

            if is_assoc:
                if is_spanish:
                    concept = "asociaciones médicas"
                else:
                    concept = "medical associations"

                if target_specializations:
                    concept = f"{concept} {target_specializations[0].strip()}"
            elif specific_industries:
                primary = specific_industries[0]
                org_types_str = " ".join(target_org_types).lower()
                if "contractor" in org_types_str and "construction" in primary.lower():
                    concept = "construction contractors"
                elif "distributor" in org_types_str and "industrial" in primary.lower():
                    concept = "industrial distributors"
                elif "software" in primary.lower():
                    concept = "B2B software companies"
                elif "restaurant" in primary.lower():
                    concept = "restaurants"
                else:
                    # General-purpose ICP handling: combine industry and organization type if complementary
                    if target_org_types:
                        first_ot = target_org_types[0].strip()
                        if first_ot.lower() not in primary.lower():
                            concept = f"{primary} {first_ot}".strip()
                        else:
                            concept = primary
                    else:
                        concept = primary
            elif target_org_types:
                concept = " ".join(target_org_types)

        # Step 1.1: If no ICP concept, check structured category
        if not concept and category:
            cat_map = {
                "medical_association": "asociaciones médicas" if (getattr(target_market, "country", None) or country or "").upper() == "CO" else "medical associations",
                "construction": "construction contractors",
                "industrial_distributor": "industrial distributors",
                "b2b_software": "B2B software companies",
                "restaurant": "restaurants",
            }
            if category in cat_map:
                concept = cat_map[category]
            elif category.strip():
                concept = category.replace("_", " ")

        # Step 1.2: Check if operator raw query provides a specific business target
        raw_target = None
        if clean_raw:
            # Strip location phrases like "en Cali", "in Florida" from raw query
            target_candidate = re.sub(
                r"\b(?:en|in)\s+[a-záéíóúñ\s]+$", "", clean_raw, flags=re.IGNORECASE
            ).strip()
            # If target_candidate is specific (not just a generic entity descriptor)
            generic_targets = {
                "organizaciones", "empresas", "organizations", "companies",
                "asociaciones", "asociacion", "sociedades", "sociedad",
                "entidades", "entities"
            }
            if target_candidate and target_candidate.lower() not in generic_targets:
                raw_target = target_candidate

        # Prefer clear raw operator intent over an administrative or stale campaign title
        if not concept:
            if raw_target:
                concept = raw_target
            elif campaign and getattr(campaign, "name", None):
                c_name = campaign.name.lower()
                if "asociaciones médicas" in c_name or "asociación médica" in c_name:
                    concept = "asociaciones médicas"
                elif "medical association" in c_name:
                    concept = "medical associations"
                elif "construcci" in c_name or "construction" in c_name:
                    concept = "construction contractors"
                elif "distribuidor" in c_name or "distributor" in c_name:
                    concept = "industrial distributors"
                elif "software" in c_name:
                    concept = "B2B software companies"
                elif "restaurant" in c_name:
                    concept = "restaurants"

        # If still no concept derived from structured sources or operator target, fall back to clean raw query
        if not concept:
            if clean_raw:
                concept = clean_raw
            else:
                concept = "organizations"

        # Step 2: Determine target geography (city -> region -> country)
        g_city = (getattr(target_market, "city", None) or city or "").strip()
        g_region = (getattr(target_market, "region", None) or region or "").strip()
        g_country = (getattr(target_market, "country", None) or country or "").strip()

        if not target_market and not g_city and not g_region:
            q_lower = clean_raw.lower()
            if "cali" in q_lower:
                g_city = "Cali"
                if not g_region:
                    g_region = "Valle del Cauca"
            elif "medellin" in q_lower or "medellín" in q_lower:
                g_city = "Medellín"
                if not g_region:
                    g_region = "Antioquia"
            elif "bogota" in q_lower or "bogotá" in q_lower:
                g_city = "Bogotá"
                if not g_region:
                    g_region = "Cundinamarca"
            elif "miami" in q_lower:
                g_city = "Miami"
                if not g_region:
                    g_region = "Florida"
            elif "florida" in q_lower:
                g_region = "Florida"
            elif "new jersey" in q_lower:
                g_region = "New Jersey"

        if g_country.upper() == "CO":
            g_country = "Colombia"

        geo_target = ""
        if g_city:
            geo_target = g_city
        elif g_region:
            geo_target = g_region
        elif g_country:
            geo_target = g_country

        # Step 3: Combine concept and geography avoiding duplicate or conflicting tokens
        combined = concept.strip()
        if geo_target:
            # Strip trailing prepositional phrases or conflicting location tokens from concept
            known_locations = {
                "cali", "valle", "bogota", "bogotá", "medellin", "medellín",
                "barranquilla", "cartagena", "miami", "florida", "new jersey",
                "boston", "colombia"
            }
            geo_tokens_set = {t.lower().strip(" ,.-") for t in geo_target.split()}

            # Remove conflicting locations from concept if present
            concept_words = combined.split()
            filtered_words = [
                w for w in concept_words
                if w.lower().strip(" ,.-") not in known_locations or w.lower().strip(" ,.-") in geo_tokens_set
            ]
            if filtered_words:
                combined = " ".join(filtered_words)

            concept_tokens = [t.lower().strip(" ,.-") for t in combined.split()]
            geo_tokens = [t.lower().strip(" ,.-") for t in geo_target.split()]

            # If all geo tokens already appear in concept, do not duplicate
            if not all(gt in concept_tokens for gt in geo_tokens):
                combined = f"{combined} {geo_target}".strip()

        # Deduplicate adjacent identical words
        words = combined.split()
        deduped = []
        for w in words:
            if not deduped or w.lower() != deduped[-1].lower():
                deduped.append(w)

        return " ".join(deduped)

    def create_web_search_preview_plan(
        self,
        org_id: str,
        query: str,
        campaign_id: Optional[str] = None,
        category: Optional[str] = None,
        country: Optional[str] = None,
        city: Optional[str] = None,
        region: Optional[str] = None,
        limit: int = 5,
        negative_keywords: Optional[List[str]] = None,
    ) -> SearchPlan:
        """Construct a single-query, budget-bounded web search plan for controlled preview."""
        import uuid
        from bopclients.application.search_dto import DiscoveryTask

        campaign = None
        icp = None
        target_market = None

        if campaign_id and self.campaign_repo:
            campaign = self.campaign_repo.get_by_id(org_id, campaign_id)
            if campaign and campaign.icp_id and self.icp_repo:
                icp = self.icp_repo.get_by_id(org_id, campaign.icp_id)
                if icp and getattr(icp, "target_markets", None):
                    target_market = icp.target_markets[0]

        # Synthesize concise, high-signal query
        synthesized_query = self.synthesize_preview_query(
            raw_query=query,
            campaign=campaign,
            icp=icp,
            target_market=target_market,
            category=category,
            city=city,
            region=region,
            country=country,
        )

        # Resolve effective geography: ICP target_market takes highest precedence
        if target_market:
            eff_city = getattr(target_market, "city", None)
            eff_region = getattr(target_market, "region", None)
            eff_country = getattr(target_market, "country", None) or country or "CO"
        else:
            eff_city = city
            eff_region = region
            eff_country = country or "CO"

            # If not explicitly provided, infer from query text
            q_lower = query.lower()
            if not eff_city:
                if "cali" in q_lower:
                    eff_city = "Cali"
                    eff_region = eff_region or "Valle del Cauca"
                elif "medellin" in q_lower or "medellín" in q_lower:
                    eff_city = "Medellín"
                    eff_region = eff_region or "Antioquia"
                elif "bogota" in q_lower or "bogotá" in q_lower:
                    eff_city = "Bogotá"
                    eff_region = eff_region or "Cundinamarca"
                elif "miami" in q_lower:
                    eff_city = "Miami"
                    eff_region = eff_region or "Florida"

            if not eff_region:
                if "florida" in q_lower:
                    eff_region = "Florida"
                elif "new jersey" in q_lower:
                    eff_region = "New Jersey"

        # Determine effective category
        if category:
            eff_category = category
        elif icp:
            norm_inds = [CategoryNormalizer.normalize(ind) for ind in (getattr(icp, "target_industries", None) or getattr(icp, "industries", None) or [])]
            valid_norms = [n for n in norm_inds if n and n != "healthcare"]
            eff_category = valid_norms[0] if valid_norms else "medical_association"
        else:
            eff_category = "medical_association"

        clamped_limit = min(max(1, limit), 5)

        # Negative keywords configuration
        if negative_keywords is not None:
            negs = list(negative_keywords)
        elif eff_category in ("medical_association", "scientific_society") or "asociaci" in synthesized_query or "medical" in synthesized_query:
            negs = ["hospital", "clinica", "clínica", "consultorio", "eps", "ips"]
        elif eff_category in ("construction", "builder"):
            negs = ["inmobiliaria", "real estate", "bienes raices"]
        elif eff_category in ("industrial_distributor", "wholesale"):
            negs = ["supermercado", "supermarket", "retail", "minorista"]
        elif eff_category in ("b2b_software", "technology"):
            negs = ["tienda", "reparacion", "celulares", "hardware"]
        else:
            negs = []

        # Merge any excluded attributes configured on ICP
        if icp and getattr(icp, "excluded_attributes", None):
            for ex in icp.excluded_attributes:
                if ex and ex.strip().lower() not in negs:
                    negs.append(ex.strip().lower())

        task = DiscoveryTask(
            id=str(uuid.uuid4()),
            provider="web_search",
            query=synthesized_query,
            category=eff_category,
            country=eff_country,
            city=eff_city,
            region=eff_region,
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
