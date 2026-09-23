"""Ideal Customer Profile (ICP) and Target Market domain entities."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import List, Optional


@dataclass
class TargetMarket:
    """Geographic and demographic targeting parameters for an ICP or Campaign."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    icp_id: str = ""
    country: str = "US"
    region: Optional[str] = None  # State / Province, e.g., "FL"
    city: Optional[str] = None
    postal_code: Optional[str] = None
    radius_miles: float = 10.0
    language: str = "en"


@dataclass
class IdealCustomerProfile:
    """Ideal Customer Profile (ICP) defining target criteria for prospecting."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    organization_id: str = ""
    name: str = ""
    description: str = ""
    industries: List[str] = field(default_factory=list)
    company_sizes: List[str] = field(default_factory=list)
    decision_maker_roles: List[str] = field(default_factory=list)
    pain_points: List[str] = field(default_factory=list)
    desired_signals: List[str] = field(default_factory=list)
    excluded_signals: List[str] = field(default_factory=list)
    countries: List[str] = field(default_factory=lambda: ["US"])
    languages: List[str] = field(default_factory=lambda: ["en"])
    target_markets: List[TargetMarket] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # General-Purpose ICP Fields (additive, backward-compatible):
    target_organization_types: List[str] = field(default_factory=list)
    target_industries: List[str] = field(default_factory=list)
    target_business_activities: List[str] = field(default_factory=list)
    target_offerings: List[str] = field(default_factory=list)
    target_specializations: List[str] = field(default_factory=list)
    required_attributes: List[str] = field(default_factory=list)
    excluded_attributes: List[str] = field(default_factory=list)
    excluded_organization_types: List[str] = field(default_factory=list)
    tenant_offerings: List[str] = field(default_factory=list)

    def validate(self) -> None:
        if not self.organization_id:
            raise ValueError("organization_id required")
        if not self.name.strip():
            raise ValueError("ICP name cannot be empty")

    def get_effective_organization_types(self) -> List[str]:
        """Derive or return target organization types separately from industry."""
        if self.target_organization_types:
            return list(self.target_organization_types)
        derived: List[str] = []
        for ind in self.industries:
            ind_lower = ind.lower()
            if any(term in ind_lower for term in ("association", "asociaci", "society", "sociedad", "colegio", "federaci", "gremio")):
                if "association" not in derived:
                    derived.append("association")
            elif any(term in ind_lower for term in ("distributor", "distribuid", "wholesale", "mayorista")):
                if "distributor" not in derived:
                    derived.append("distributor")
            elif any(term in ind_lower for term in ("construction", "construcc", "contractor", "contratista", "builder", "software", "saas", "tech", "tecnolog")):
                if "company" not in derived:
                    derived.append("company")
        return derived

    def get_effective_industries(self) -> List[str]:
        """Return target industries separately from organization type."""
        if self.target_industries:
            return list(self.target_industries)
        return list(self.industries)

    def get_effective_business_activities(self) -> List[str]:
        """Derive or return target business activities."""
        if self.target_business_activities:
            return list(self.target_business_activities)
        derived: List[str] = []
        for ind in self.industries:
            ind_lower = ind.lower()
            if any(term in ind_lower for term in ("construction", "construcc", "contractor", "contratista", "builder", "obras")):
                if "construction" not in derived:
                    derived.append("construction")
            elif any(term in ind_lower for term in ("distributor", "distribuid", "wholesale", "mayorista")):
                if "distribution" not in derived:
                    derived.append("distribution")
            elif any(term in ind_lower for term in ("software", "saas", "tecnolog", "tech")):
                if "software_development" not in derived:
                    derived.append("software_development")
        return derived

    def get_effective_target_offerings(self) -> List[str]:
        """Return products or services offered by the target organization."""
        if self.target_offerings:
            return list(self.target_offerings)
        return []

    def get_effective_specializations(self) -> List[str]:
        """Return target specializations."""
        if self.target_specializations:
            return list(self.target_specializations)
        return []

    def get_effective_required_attributes(self) -> List[str]:
        """Return required attributes without fabricating requirements."""
        if self.required_attributes:
            return list(self.required_attributes)
        return list(self.desired_signals)

    def get_effective_excluded_organization_types(self) -> List[str]:
        """Derive or return excluded organization types."""
        if self.excluded_organization_types:
            return list(self.excluded_organization_types)
        derived: List[str] = []
        for sig in self.excluded_signals:
            sig_lower = sig.lower().strip()
            if sig_lower in ("clinic", "clínica", "clinica", "hospital", "hospitales", "consultorio", "retail", "real_estate", "inmobiliaria", "individual_contractor"):
                norm = "clinic" if sig_lower in ("clinic", "clínica", "clinica") else sig_lower
                norm = "hospital" if norm in ("hospital", "hospitales") else norm
                norm = "real_estate" if norm in ("real_estate", "inmobiliaria") else norm
                if norm not in derived:
                    derived.append(norm)
        return derived

    def get_effective_excluded_attributes(self) -> List[str]:
        """Derive or return excluded attributes and negative criteria."""
        if self.excluded_attributes:
            return list(self.excluded_attributes)
        return list(self.excluded_signals)

    def get_effective_tenant_offerings(self) -> List[str]:
        """Return tenant's own services offered (strictly separate from target offerings)."""
        if self.tenant_offerings:
            return list(self.tenant_offerings)
        return []

    def get_effective_geographic_targets(self) -> List[TargetMarket]:
        """Return geographic targeting parameters."""
        return list(self.target_markets)
