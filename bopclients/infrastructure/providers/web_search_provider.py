"""Offline foundation for complementary web-search discovery provider.

Provides an offline-capable, bounded web discovery adapter implementing IDiscoveryProvider.
Operates exclusively with pluggable transport abstractions (offline synthetic fixtures by default).
Contains zero network calls, zero external HTTP dependencies, and enforces disabled-by-default
and tenant authorization gates.
"""

from abc import ABC, abstractmethod
from enum import Enum
import hashlib
import re
from typing import List, Dict, Any, Optional, Set

from bopclients.application.interfaces.search_interfaces import IDiscoveryProvider
from bopclients.application.search_dto import DiscoveryTask
from bopclients.application.interfaces.forge_gateways import DiscoveredBusiness
from bopclients.application.discovery.candidate_classifier import (
    CandidateClassificationRequest,
    CandidateClassificationStatus,
    ClassificationDecision,
    IOrganizationCandidateClassifier,
    OrganizationCandidateClassifier,
)
from bopclients.application.discovery.candidate_qualifier import (
    OrganizationCandidateQualifier,
)
from bopclients.domain.candidate_qualification import (
    EntityArchetype,
    GeographicEvidenceStatus,
)
from bopclients.domain.exceptions import DiscoveryExecutionError, TenantAccessError


class GeographicScope(str, Enum):
    """Institutional geographic coverage semantics for discovered organizations."""

    PHYSICAL_LOCATION_VERIFIED = "PHYSICAL_LOCATION_VERIFIED"
    REGIONAL_COVERAGE_EVIDENCED = "REGIONAL_COVERAGE_EVIDENCED"
    NATIONAL_SCOPE = "NATIONAL_SCOPE"
    LOCATION_UNVERIFIED = "LOCATION_UNVERIFIED"


class IWebSearchTransport(ABC):
    """Abstract transport interface for web search queries."""

    @abstractmethod
    def search(
        self,
        query: str,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        count: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Execute web search query and return raw search response dictionary."""
        ...


class OfflineFixtureWebSearchTransport(IWebSearchTransport):
    """Deterministic offline fixture transport for unit testing and offline development.

    GUARANTEE: Makes zero external network calls, opens no HTTP connections, and operates
    strictly on synthetic test fixtures.
    """

    def __init__(self, fixtures: Optional[Dict[str, Dict[str, Any]]] = None):
        self.fixtures: Dict[str, Dict[str, Any]] = {}
        if fixtures:
            for k, v in fixtures.items():
                self.fixtures[k.lower().strip()] = v
        self.call_log: List[Dict[str, Any]] = []

    def register_fixture(self, query: str, response: Dict[str, Any]) -> None:
        """Register a synthetic query-response fixture."""
        self.fixtures[query.lower().strip()] = response

    def search(
        self,
        query: str,
        country: Optional[str] = None,
        search_lang: Optional[str] = None,
        count: int = 20,
        offset: int = 0,
    ) -> Dict[str, Any]:
        norm_key = (query or "").lower().strip()
        self.call_log.append(
            {
                "query": query,
                "country": country,
                "search_lang": search_lang,
                "count": count,
                "offset": offset,
            }
        )
        return self.fixtures.get(
            norm_key,
            {
                "query": {"original": query, "more_results_available": False},
                "web": {"results": []},
            },
        )


class WebSearchDiscoveryProvider(IDiscoveryProvider):
    """Source-neutral discovery provider querying web search engines through pluggable transport.

    Enforces:
    1. Disabled by default (requires explicit configuration to activate).
    2. Tenant authorization check before execution.
    3. Query budget limits (max 5 queries per run, max 20 results per query, no deep pagination).
    4. Two-independent-signals classification via OrganizationCandidateClassifier.
    5. Truthful geographic scope attribution without inventing GPS coordinates.
    6. Zero remote network calls in default/offline mode.
    """

    PROVIDER_NAME = "web_search"
    MAX_QUERIES_PER_RUN = 5
    MAX_RESULTS_PER_QUERY = 20

    # Regional marker patterns for Colombian departments and cities
    REGIONAL_PATTERNS = re.compile(
        r"\b(?:valle|valle del cauca|cali|antioquia|medell[íi]n|cundinamarca|bogot[aá]|atl[aá]ntico|barranquilla|"
        r"santander|bucaramanga|eje cafetero|costa atl[aá]ntica|cap[íi]tulo\s+\w+)\b",
        re.IGNORECASE,
    )

    # National marker patterns
    NATIONAL_PATTERNS = re.compile(
        r"\b(?:colombiana|colombiano|colombianos|colombianas|de colombia|en colombia|nacional|nacionales)\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        transport: Optional[IWebSearchTransport] = None,
        classifier: Optional[IOrganizationCandidateClassifier] = None,
        qualifier: Optional[OrganizationCandidateQualifier] = None,
        enabled: bool = False,
        authorized_tenants: Optional[Set[str]] = None,
        max_queries_per_run: int = MAX_QUERIES_PER_RUN,
        max_results_per_query: int = MAX_RESULTS_PER_QUERY,
    ):
        self._transport = transport or OfflineFixtureWebSearchTransport()
        self._classifier = classifier or OrganizationCandidateClassifier()
        self._qualifier = qualifier or OrganizationCandidateQualifier()
        self.enabled = enabled
        self.authorized_tenants = set(authorized_tenants or [])
        self.max_queries_per_run = max_queries_per_run
        self.max_results_per_query = max_results_per_query
        self.last_diagnostics: Optional[Dict[str, Any]] = None

    @property
    def name(self) -> str:
        return self.PROVIDER_NAME

    @property
    def capability(self):
        from bopclients.domain.provider_capability import get_web_search_capability
        return get_web_search_capability(enabled=self.enabled, authorized_tenants=self.authorized_tenants)

    @property
    def capabilities(self) -> dict:
        return {
            "supports_postal_code_us": True,
            "supports_coordinates": False,
            "supports_country_only": True,
            "supports_state_region": True,
            "supports_international_city_without_coords": True,
            "supports_radius_miles_exact": False,
            "supports_negative_filtering": True,
        }

    def supports(self, task: DiscoveryTask) -> bool:
        """Verify whether task is intended for web_search/tavily and provider is currently enabled."""
        p_name = (task.provider or "").strip().lower()
        if p_name not in (self.PROVIDER_NAME, "tavily"):
            return False
        return self.enabled

    def is_category_supported(self, category: str) -> bool:
        """Verify whether category is supported by web search provider."""
        from bopclients.infrastructure.providers.overture_provider import EXCLUDED_FACILITY_CATEGORIES
        cat = (category or "").strip().lower()
        if cat in EXCLUDED_FACILITY_CATEGORIES:
            return False
        return True

    def authorize_tenant(self, organization_id: str) -> None:
        """Explicitly authorize a tenant for web search discovery."""
        if organization_id:
            self.authorized_tenants.add(organization_id)

    def revoke_tenant(self, organization_id: str) -> None:
        """Revoke tenant authorization for web search discovery."""
        self.authorized_tenants.discard(organization_id)

    def determine_geographic_scope(
        self,
        name: str,
        snippet: str,
        task: DiscoveryTask,
        archetype: Optional[EntityArchetype] = None,
    ) -> GeographicScope:
        """Classify candidate geographic coverage truthfully without inventing coordinates."""
        if archetype == EntityArchetype.DIRECTORY_LISTING:
            return GeographicScope.LOCATION_UNVERIFIED

        combined_text = f"{name} {snippet}".strip()

        # Check for explicit regional evidence
        has_regional = bool(self.REGIONAL_PATTERNS.search(combined_text))
        has_national = bool(self.NATIONAL_PATTERNS.search(combined_text))

        if has_regional:
            return GeographicScope.REGIONAL_COVERAGE_EVIDENCED
        if has_national:
            return GeographicScope.NATIONAL_SCOPE

        # If city/region in task matches query context but not explicitly evidenced in text
        if task.city or task.region:
            return GeographicScope.LOCATION_UNVERIFIED

        return GeographicScope.LOCATION_UNVERIFIED

    def discover(self, task: DiscoveryTask) -> List[DiscoveredBusiness]:
        """Execute web discovery task using offline transport and source-neutral classification."""
        # 1. Gate: Provider must be enabled
        if not self.enabled:
            raise DiscoveryExecutionError(
                f"WebSearchDiscoveryProvider is disabled by default. Explicit configuration required."
            )

        # 2. Gate: Tenant authorization check
        org_id = str(task.metadata.get("organization_id") or "")
        if self.authorized_tenants is not None:
            if not org_id or org_id not in self.authorized_tenants:
                raise TenantAccessError(
                    f"Tenant '{org_id}' is not authorized for web search discovery."
                )

        # 3. Query string validation
        query = (task.query or "").strip()
        if not query:
            # Construct bounded institutional query from task fields
            cat = task.category or "medical_association"
            parts = [cat.replace("_", " ")]
            if task.city:
                parts.append(task.city)
            if task.country and task.country.upper() == "CO":
                parts.append("Colombia")
            query = " ".join(parts)

        # 4. Enforce query bounds
        count = min(task.limit or self.max_results_per_query, self.max_results_per_query)
        country_code = (task.country or "CO").lower()
        search_lang = task.metadata.get("search_lang", "es")

        # 5. Fetch raw search response via transport
        response = self._transport.search(
            query=query,
            country=country_code,
            search_lang=search_lang,
            count=count,
            offset=0,  # Strict: no deep pagination
        )

        web_data = response.get("web", {})
        results = web_data.get("results", []) if isinstance(web_data, dict) else []

        provider_results_received = len(results) if isinstance(results, list) else 0
        results_missing_required_fields = 0
        results_rejected_by_classifier = 0
        results_accepted_by_classifier = 0
        directory_candidates_retained = 0
        rejection_reasons: Dict[str, int] = {}

        discovered: List[DiscoveredBusiness] = []

        for item in results:
            if not isinstance(item, dict):
                results_missing_required_fields += 1
                continue

            raw_title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            snippet = str(item.get("description") or "").strip()

            if not raw_title or not url:
                results_missing_required_fields += 1
                continue

            # Clean name from page title (e.g., strip " | Inicio", " - Inicio", etc.)
            clean_name = re.sub(r"\s+[|]\s+.*$", "", raw_title).strip()
            clean_name = re.sub(r"\s+[-–—]\s+(?:inicio|home|portal|sitio oficial|official website|official site)\b.*$", "", clean_name, flags=re.IGNORECASE).strip()

            # Classify using OrganizationCandidateClassifier
            canonical_target = task.category or "medical_association"
            # Web search results do not have authoritative taxonomy hints; must prove association from lexical evidence
            cat_hints: Set[str] = set()

            req = CandidateClassificationRequest(
                name=clean_name,
                target_intent=canonical_target,
                canonical_category_hints=cat_hints,
                negative_keywords=list(task.negative_keywords or []),
                raw_metadata={
                    "title": raw_title,
                    "description": snippet,
                    "url": url,
                    "provider": self.PROVIDER_NAME,
                },
            )

            decision = self._classifier.classify(req)
            if not decision.is_valid:
                results_rejected_by_classifier += 1
                reason_str = str(decision.reason or "").upper()
                if "EXCLUDED_FACILITY" in reason_str or "CONTRADICTORY_ENTITY_EVIDENCE" in reason_str:
                    code = "EXCLUDED_FACILITY"
                elif "NEGATIVE_KEYWORD" in reason_str or "CATEGORY_KEYWORD" in reason_str:
                    code = "NEGATIVE_KEYWORD_MATCH"
                elif "NOT_AN_ASSOCIATION" in reason_str or "NOT_A_PROFESSIONAL_ASSOCIATION" in reason_str or "MISSING_ORGANIZATION_NAME" in reason_str:
                    code = "MISSING_ORGANIZATION_MARKER"
                elif "UNVERIFIED_MEDICAL_SPECIALIZATION" in reason_str or "INSUFFICIENT_EVIDENCE" in reason_str or "SECTOR" in reason_str:
                    code = "MISSING_SECTOR_MATCH"
                else:
                    code = "OTHER_CLASSIFICATION_REJECTION"
                rejection_reasons[code] = rejection_reasons.get(code, 0) + 1
                continue

            results_accepted_by_classifier += 1

            # Determine structured candidate qualification
            qual = self._qualifier.qualify(
                candidate_name=clean_name,
                target_intent=canonical_target,
                base_classification=decision,
                raw_title=raw_title,
                url=url,
                snippet=snippet,
                task=task,
            )

            if qual.entity_archetype == EntityArchetype.DIRECTORY_LISTING:
                directory_candidates_retained += 1

            # Determine institutional geography truthfully
            geo_scope = self.determine_geographic_scope(
                clean_name, snippet, task, archetype=qual.entity_archetype
            )

            # Generate stable synthetic external id from URL
            url_hash = hashlib.sha256(url.strip().lower().encode("utf-8")).hexdigest()[:16]
            ext_id = f"web-{url_hash}"

            is_locally_evidenced = (
                geo_scope == GeographicScope.REGIONAL_COVERAGE_EVIDENCED
                and qual.entity_archetype != EntityArchetype.DIRECTORY_LISTING
                and qual.geographic_evidence_status in (
                    GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE,
                    GeographicEvidenceStatus.VERIFIED_REGIONAL_PRESENCE,
                )
            )

            biz = DiscoveredBusiness(
                overture_id=ext_id,
                name=clean_name,
                website_url=url,
                category=canonical_target,
                latitude=None,  # Zero invented coordinates
                longitude=None,  # Zero invented coordinates
                city=task.city if is_locally_evidenced else None,
                state=task.region if is_locally_evidenced else None,
                raw_data={
                    "title": raw_title,
                    "snippet": snippet,
                    "country": task.country or "CO",
                    "url": url,
                    "provider": self.PROVIDER_NAME,
                    "geographic_scope": geo_scope.value,
                    "classification_status": decision.status.value,
                    "classification_details": decision.details,
                    # Structured candidate qualification fields:
                    "qualification_status": qual.qualification_status.value,
                    "entity_archetype": qual.entity_archetype.value,
                    "geographic_evidence_status": qual.geographic_evidence_status.value,
                    "current_activity_status": qual.current_activity_status.value,
                    "source_url": qual.source_url,
                    "source_host": qual.source_host,
                    "organization_website": qual.organization_website,
                    "is_commercial_review_ready": qual.is_commercial_review_ready,
                    "qualification_reasons": qual.qualification_reasons,
                    "missing_evidence": qual.missing_evidence,
                },
            )
            discovered.append(biz)

        diagnostics = {
            "provider_results_received": provider_results_received,
            "results_missing_required_fields": results_missing_required_fields,
            "results_rejected_by_classifier": results_rejected_by_classifier,
            "results_accepted_by_classifier": results_accepted_by_classifier,
            "directory_candidates_retained": directory_candidates_retained,
            "candidates_returned_to_preview": len(discovered),
            "rejection_reasons": rejection_reasons,
        }
        if not isinstance(task.metadata, dict):
            task.metadata = {}
        task.metadata["diagnostics"] = diagnostics
        self.last_diagnostics = diagnostics

        return discovered
