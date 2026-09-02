"""Registry and Applicability Policy for Public Signal Providers in BopClients P8."""

from typing import List, Optional, Dict, Any, Tuple
from bopclients.domain.prospect import Prospect
from bopclients.application.signal_provider import IPublicSignalProvider


class ProviderApplicabilityPolicy:
    """Policy evaluating if a provider applies to a prospect based on country, capabilities, and status."""

    @classmethod
    def is_applicable(
        cls,
        provider: IPublicSignalProvider,
        prospect: Prospect,
        country: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, str]:
        """Evaluate if provider is applicable for the prospect, government entity status, and market."""
        caps = provider.capabilities
        if not caps.configured:
            return False, f"Provider '{provider.provider_name}' is not configured (missing API key or credentials)"

        ctx = context or {}

        # 1. Government Entity Applicability Check for Procurement Provider
        if provider.provider_name == "government_procurement":
            is_gov_ctx = ctx.get("is_government_entity", False)
            p_ind = (prospect.industry or "").strip().lower()
            is_gov_ind = p_ind in ("government", "public_sector", "municipality", "federal_agency")

            if not (is_gov_ctx or is_gov_ind):
                return False, f"Provider '{provider.provider_name}' is only applicable to verified public sector/government entities (prospect '{prospect.name}' is commercial)"

        # 2. Country / Market Applicability
        if country:
            country_norm = country.strip().upper()
            applicable = caps.applicable_countries
            if "GLOBAL" not in applicable and country_norm not in applicable:
                return False, f"Provider '{provider.provider_name}' is not applicable for market '{country_norm}' (supports {applicable})"

        return True, "Provider is applicable"


class PublicSignalProviderRegistry:
    """Central registry for managing, resolving, and routing public signal discovery providers."""

    def __init__(self):
        self._providers: Dict[str, IPublicSignalProvider] = {}

    def register(self, provider: IPublicSignalProvider) -> None:
        """Register a signal provider implementation."""
        name = provider.provider_name.lower().strip()
        if not name:
            raise ValueError("Provider name cannot be empty")
        self._providers[name] = provider

    def get(self, name: str) -> Optional[IPublicSignalProvider]:
        """Fetch provider by name."""
        return self._providers.get(name.lower().strip())

    def list_all(self) -> List[IPublicSignalProvider]:
        """List all registered providers."""
        return list(self._providers.values())

    def for_capability(self, capability_flag: str) -> List[IPublicSignalProvider]:
        """Filter registered providers supporting a specific capability flag."""
        matched = []
        for prov in self._providers.values():
            if getattr(prov.capabilities, capability_flag, False):
                matched.append(prov)
        return matched

    def resolve_for_prospect(
        self,
        prospect: Prospect,
        country: Optional[str] = None,
        required_names: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[IPublicSignalProvider]:
        """Resolve applicable and configured providers for a given prospect."""
        selected = []
        for name, prov in self._providers.items():
            if required_names and name not in [n.lower().strip() for n in required_names]:
                continue
            is_app, _ = ProviderApplicabilityPolicy.is_applicable(prov, prospect, country=country, context=context)
            if is_app:
                selected.append(prov)
        return selected
