"""Provider capability domain model for capability-based discovery provider routing.

Defines operational capabilities, supported geographic scopes, coordinate requirements,
supported organization categories, search methods, and authorization/budget constraints
for discovery providers (e.g., Overture, Web Search).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Set, Optional, Dict, Any


class SearchGeographicScope(str, Enum):
    """Geographic scope granularity of a search request."""

    POINT_RADIUS = "point_radius"
    CITY = "city"
    STATE_REGION = "state_region"
    COUNTRY = "country"
    UNKNOWN = "unknown"


@dataclass
class ProviderCapability:
    """Represents the operational capabilities, constraints, and requirements of a discovery provider."""

    provider_id: str
    supported_geographic_scopes: Set[SearchGeographicScope] = field(default_factory=set)
    requires_coordinates: bool = False
    supported_categories: Optional[Set[str]] = None  # None means source-neutral / arbitrary queryable
    supported_search_methods: List[str] = field(default_factory=list)
    enabled: bool = True
    requires_tenant_authorization: bool = False
    requires_budget: bool = False
    max_results_limit: int = 1000

    def supports_geographic_scope(self, scope: SearchGeographicScope) -> bool:
        """Check if provider supports the requested geographic scope."""
        return scope in self.supported_geographic_scopes

    def is_category_supported(self, category: Optional[str]) -> bool:
        """Verify whether provider supports the requested organization category."""
        if not category or category.strip().lower() in ("general", "any", "all"):
            return True

        cat_norm = category.strip().lower()

        # If provider is source-neutral (e.g. web search), it supports general B2B categories,
        # but facility exclusions still apply when association context is targeted.
        if self.supported_categories is None:
            from bopclients.infrastructure.providers.overture_provider import EXCLUDED_FACILITY_CATEGORIES
            return cat_norm not in EXCLUDED_FACILITY_CATEGORIES

        if cat_norm in self.supported_categories:
            return True

        from bopclients.infrastructure.providers.overture_provider import (
            CATEGORY_ALIASES,
            CANONICAL_CATEGORY_MAPPINGS,
            OVERTURE_DIRECT_CATEGORIES,
        )
        canonical = CATEGORY_ALIASES.get(cat_norm, cat_norm)
        if canonical in self.supported_categories:
            return True
        if canonical in CANONICAL_CATEGORY_MAPPINGS:
            return True
        if canonical in OVERTURE_DIRECT_CATEGORIES:
            return True

        return False

    def can_handle(
        self,
        scope: SearchGeographicScope,
        category: Optional[str],
        has_coordinates: bool = False,
    ) -> bool:
        """Evaluate whether this provider can handle the given scope, category, and coordinate availability."""
        if self.requires_coordinates and not has_coordinates:
            return False
        if not self.supports_geographic_scope(scope):
            return False
        if not self.is_category_supported(category):
            return False
        return True


def get_overture_capability(enabled: bool = True) -> ProviderCapability:
    """Generate canonical capability specification for Overture Maps discovery provider."""
    from bopclients.infrastructure.providers.overture_provider import (
        OVERTURE_DIRECT_CATEGORIES,
        CANONICAL_CATEGORY_MAPPINGS,
    )
    from forge.discovery.overture import _CATEGORY_TO_INDUSTRY, _INDUSTRY_TO_CATEGORIES

    cats: Set[str] = set(OVERTURE_DIRECT_CATEGORIES)
    cats.update(CANONICAL_CATEGORY_MAPPINGS.keys())
    cats.update(_CATEGORY_TO_INDUSTRY.keys())
    cats.update(_INDUSTRY_TO_CATEGORIES.keys())

    return ProviderCapability(
        provider_id="overture",
        supported_geographic_scopes={
            SearchGeographicScope.POINT_RADIUS,
            SearchGeographicScope.CITY,
        },
        requires_coordinates=True,
        supported_categories=cats,
        supported_search_methods=["spatial_radius", "canonical_category_filter"],
        enabled=enabled,
        requires_tenant_authorization=False,
        requires_budget=False,
        max_results_limit=1000,
    )


def get_web_search_capability(
    enabled: bool = False,
    authorized_tenants: Optional[Set[str]] = None,
) -> ProviderCapability:
    """Generate canonical capability specification for Web Search discovery provider."""
    return ProviderCapability(
        provider_id="web_search",
        supported_geographic_scopes={
            SearchGeographicScope.POINT_RADIUS,
            SearchGeographicScope.CITY,
            SearchGeographicScope.STATE_REGION,
            SearchGeographicScope.COUNTRY,
        },
        requires_coordinates=False,
        supported_categories=None,  # Source-neutral / general B2B categories
        supported_search_methods=["keyword_query", "entity_classification"],
        enabled=enabled,
        requires_tenant_authorization=True,
        requires_budget=False,
        max_results_limit=20,
    )


class ProviderCapabilityRegistry:
    """Registry maintaining active discovery provider capabilities for search planning and routing."""

    def __init__(self, capabilities: Optional[Dict[str, ProviderCapability]] = None):
        self._capabilities: Dict[str, ProviderCapability] = dict(capabilities or {})
        if not self._capabilities:
            self.register(get_overture_capability(enabled=True))
            self.register(get_web_search_capability(enabled=False))

    def register(self, capability: ProviderCapability) -> None:
        """Register or update a provider capability."""
        self._capabilities[capability.provider_id.lower().strip()] = capability

    def get(self, provider_id: str) -> Optional[ProviderCapability]:
        """Retrieve capability by provider ID."""
        return self._capabilities.get(provider_id.lower().strip())

    def list_capabilities(self) -> List[ProviderCapability]:
        """List all registered provider capabilities."""
        return list(self._capabilities.values())
