"""Overture discovery provider implementing product-level IDiscoveryProvider via FORGE Gateway."""

import logging
import math
import re
from typing import List, Optional, Dict, Any, Tuple, Set

from bopclients.domain.exceptions import DiscoveryProviderError
from bopclients.application.search_dto import DiscoveryTask
from bopclients.application.interfaces.search_interfaces import IDiscoveryProvider
from bopclients.application.interfaces.forge_gateways import (
    IForgeDiscoveryGateway,
    DiscoveryQuery,
    DiscoveredBusiness,
)
from forge.discovery.overture import _CATEGORY_TO_INDUSTRY, _INDUSTRY_TO_CATEGORIES

logger = logging.getLogger("bopclients.providers.overture")

EARTH_RADIUS_MILES = 3958.8


def haversine_distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two points in miles using the Haversine formula."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return EARTH_RADIUS_MILES * c


CANONICAL_CATEGORY_MAPPINGS: Dict[str, str] = {
    "medical_association": "association_or_organization",
    "scientific_society": "association_or_organization",
    "professional_association": "professional_association",
    "non_profit": "non_governmental_organization",
}

CATEGORY_ALIASES: Dict[str, str] = {
    "asociación médica": "medical_association",
    "asociacion medica": "medical_association",
    "asociaciones médicas": "medical_association",
    "asociaciones medicas": "medical_association",
    "medical association": "medical_association",
    "medical associations": "medical_association",
    "sociedad científica": "scientific_society",
    "sociedad cientifica": "scientific_society",
    "sociedades científicas": "scientific_society",
    "sociedades cientificas": "scientific_society",
    "scientific society": "scientific_society",
    "scientific societies": "scientific_society",
    "colegio profesional": "professional_association",
    "colegios profesionales": "professional_association",
    "colegio médico": "professional_association",
    "colegio medico": "professional_association",
    "colegios médicos": "professional_association",
    "colegios medicos": "professional_association",
    "professional association": "professional_association",
    "professional associations": "professional_association",
    "organización gremial": "professional_association",
    "organizacion gremial": "professional_association",
    "organizaciones gremiales": "professional_association",
    "gremio": "professional_association",
    "gremios": "professional_association",
    "organización sin fines de lucro": "non_profit",
    "organizacion sin fines de lucro": "non_profit",
    "organizaciones sin fines de lucro": "non_profit",
    "health nonprofit": "non_profit",
    "health non-profit": "non_profit",
    "nonprofit": "non_profit",
    "non-profit": "non_profit",
}

OVERTURE_DIRECT_CATEGORIES: Set[str] = {
    "association_or_organization",
    "professional_association",
    "non_governmental_organization",
}

EXCLUDED_FACILITY_CATEGORIES: Set[str] = {
    "clinic",
    "hospital",
    "doctor",
    "dentist",
    "medical_office",
    "pharmacy",
    "drugstore",
    "optician",
    "physiotherapist",
    "chiropractor",
}


from bopclients.application.discovery.candidate_classifier import (
    CandidateClassificationStatus,
    CandidateClassificationRequest,
    ClassificationDecision,
    IOrganizationCandidateClassifier,
    OrganizationCandidateClassifier,
    SPECIALTY_LOGIA_ROOTS,
    SPECIALTY_OTHER_PATTERNS,
)


class OvertureCandidateValidator:
    """Deterministic validation and exclusion policy for Overture discovery candidates.

    Adapts Overture provider-specific categories and coordinates, delegating core
    lexical organization and medical specialty reasoning to the source-neutral classifier.
    """

    FACILITY_PREFIX_PATTERN = OrganizationCandidateClassifier.FACILITY_PREFIX_PATTERN
    ASSOCIATION_MARKER_PATTERN = OrganizationCandidateClassifier.ASSOCIATION_MARKER_PATTERN
    MEDICAL_SCIENTIFIC_PATTERN = OrganizationCandidateClassifier.MEDICAL_SCIENTIFIC_PATTERN
    PROFESSIONAL_ASSOC_PATTERN = OrganizationCandidateClassifier.PROFESSIONAL_ASSOC_PATTERN

    def __init__(self, classifier: Optional[IOrganizationCandidateClassifier] = None):
        self.classifier = classifier or OrganizationCandidateClassifier()

    def is_genuine_association(self, biz: DiscoveredBusiness) -> bool:
        name = (biz.name or "").strip()
        cat = (biz.category or "").lower().strip()

        # If name starts with an explicit facility entity prefix, it is fundamentally a facility
        if self.FACILITY_PREFIX_PATTERN.search(name):
            return False

        # If primary category is an excluded facility, it is not an association
        if cat in EXCLUDED_FACILITY_CATEGORIES:
            return False

        # Must have association category or explicit association marker in name
        if cat in OVERTURE_DIRECT_CATEGORIES:
            return True
        if self.ASSOCIATION_MARKER_PATTERN.search(name):
            return True

        return False

    def has_medical_or_scientific_specialization(self, biz: DiscoveredBusiness) -> bool:
        hints = {biz.category} if biz.category else set()
        meta = dict(biz.raw_data) if isinstance(biz.raw_data, dict) else {}
        if biz.forge_industry:
            meta["forge_industry"] = biz.forge_industry
        if biz.category:
            meta["category"] = biz.category
        return self.classifier.has_medical_or_scientific_specialization(
            biz.name, category_hints=hints, raw_metadata=meta
        )

    def validate_candidate(
        self, biz: DiscoveredBusiness, task: DiscoveryTask
    ) -> Tuple[bool, Optional[str]]:
        """Validate an Overture candidate business against radius, exclusions, and entity specialization."""
        name = (biz.name or "").strip()
        cat = (biz.category or "").lower().strip()

        # 1. Radius validation (Haversine great-circle distance)
        if task.latitude is not None and task.longitude is not None:
            if biz.latitude is None or biz.longitude is None:
                # If candidate lacks coordinates:
                # For exact postal code match in legacy US tests, allow if zip matches exactly
                # and target is not a specialized association search
                task_cat_norm = (task.category or "").strip().lower()
                canonical_target = CATEGORY_ALIASES.get(task_cat_norm, task_cat_norm)
                is_assoc = canonical_target in (
                    "medical_association",
                    "scientific_society",
                    "professional_association",
                    "non_profit",
                )
                if (
                    not is_assoc
                    and (
                        (
                            task.postal_code
                            and biz.zip_code
                            and task.postal_code.strip() == biz.zip_code.strip()
                        )
                        or (
                            task.city
                            and biz.city
                            and task.city.strip().lower() == biz.city.strip().lower()
                        )
                    )
                ):
                    pass
                else:
                    return False, "MISSING_COORDINATES_FAIL_CLOSED"
            else:
                dist = haversine_distance_miles(
                    task.latitude, task.longitude, biz.latitude, biz.longitude
                )
                if dist > (task.radius_miles + 1e-6):
                    return (
                        False,
                        f"EXCEEDS_RADIUS ({dist:.2f} mi > {task.radius_miles:.2f} mi)",
                    )

        # 2. Extract candidate category hints and facility hints from Overture
        cand_cats = {cat} if cat else set()
        raw_alts_list = []
        if isinstance(biz.raw_data, dict):
            alts1 = (
                biz.raw_data.get("categories", {}).get("alternate", [])
                if isinstance(biz.raw_data.get("categories"), dict)
                else []
            )
            alts2 = (
                biz.raw_data.get("taxonomy", {}).get("alternates", [])
                if isinstance(biz.raw_data.get("taxonomy"), dict)
                else []
            )
            alts3 = biz.raw_data.get("alternate_categories", [])
            alts4 = (
                biz.raw_data.get("categories", {}).get("alternates", [])
                if isinstance(biz.raw_data.get("categories"), dict)
                else []
            )

            for alt_group in (alts1, alts2, alts3, alts4):
                if isinstance(alt_group, list):
                    for alt in alt_group:
                        if alt:
                            norm_alt = str(alt).lower().strip()
                            cand_cats.add(norm_alt)
                            raw_alts_list.append(norm_alt)

        # 3. Canonical target classification
        task_cat_norm = (task.category or "").strip().lower()
        canonical_target = CATEGORY_ALIASES.get(task_cat_norm, task_cat_norm)

        # Canonical category hints
        cat_hints = set()
        if cat in OVERTURE_DIRECT_CATEGORIES or any(c in OVERTURE_DIRECT_CATEGORIES for c in cand_cats):
            cat_hints.add("association")
        if cat == "professional_association" or "professional_association" in cand_cats:
            cat_hints.add("professional_association")
        if cat == "non_governmental_organization" or "non_governmental_organization" in cand_cats:
            cat_hints.add("non_profit")

        # Facility hints
        facility_hints = set()
        if cat in EXCLUDED_FACILITY_CATEGORIES:
            facility_hints.add(cat)

        # Build raw metadata dict preserving alternate categories
        meta = dict(biz.raw_data) if isinstance(biz.raw_data, dict) else {}
        if raw_alts_list:
            meta["alternate_categories"] = raw_alts_list
        if biz.forge_industry:
            meta["forge_industry"] = biz.forge_industry
        if cat:
            meta["category"] = cat

        req = CandidateClassificationRequest(
            name=name,
            target_intent=canonical_target,
            canonical_category_hints=cat_hints,
            canonical_facility_hints=facility_hints,
            negative_keywords=list(task.negative_keywords or []),
            raw_metadata=meta,
        )

        decision = self.classifier.classify(req)
        return decision.is_valid, decision.reason


class OvertureDiscoveryProvider(IDiscoveryProvider):
    """Discovery provider using FORGE Overture Parquet engine adapter with safe validation."""

    def __init__(
        self,
        discovery_gateway: IForgeDiscoveryGateway,
        validator: Optional[OvertureCandidateValidator] = None,
    ):
        self.discovery_gateway = discovery_gateway
        self.validator = validator or OvertureCandidateValidator()

    @property
    def name(self) -> str:
        return "overture"

    @property
    def capabilities(self) -> dict:
        return {
            "supports_postal_code_us": True,
            "supports_coordinates": True,
            "supports_country_only": False,
            "supports_international_city_without_coords": False,
            "supports_radius_miles_exact": True,
            "supports_negative_filtering": True,
        }

    def is_category_supported(self, category: Optional[str]) -> bool:
        if not category or category.lower() in ("general", "any", "all"):
            return True
        cat_norm = category.strip().lower()
        canonical = CATEGORY_ALIASES.get(cat_norm, cat_norm)
        if canonical in CANONICAL_CATEGORY_MAPPINGS:
            return True
        if canonical in OVERTURE_DIRECT_CATEGORIES:
            return True
        if canonical in _CATEGORY_TO_INDUSTRY or canonical in _INDUSTRY_TO_CATEGORIES:
            return True
        return False

    def map_category_to_query_industry(self, category: Optional[str]) -> Optional[str]:
        if not category or category.lower() in ("general", "any", "all"):
            return None
        cat_norm = category.strip().lower()
        canonical = CATEGORY_ALIASES.get(cat_norm, cat_norm)
        if canonical in CANONICAL_CATEGORY_MAPPINGS:
            return CANONICAL_CATEGORY_MAPPINGS[canonical]
        return canonical

    def supports(self, task: DiscoveryTask) -> bool:
        if task.provider.lower() != "overture":
            return False
        if task.category and not self.is_category_supported(task.category):
            return False
        return True

    def discover(self, task: DiscoveryTask) -> List[DiscoveredBusiness]:
        if task.provider.lower() != "overture":
            raise DiscoveryProviderError(
                f"OvertureDiscoveryProvider does not support provider '{task.provider}'"
            )

        if task.category and not self.is_category_supported(task.category):
            raise DiscoveryProviderError(
                f"Unsupported category '{task.category}' for Overture provider"
            )

        try:
            query_industry = self.map_category_to_query_industry(task.category)
            query = DiscoveryQuery(
                zip_code=task.postal_code,
                city=task.city,
                state=task.region,
                latitude=task.latitude,
                longitude=task.longitude,
                radius_miles=task.radius_miles,
                industry=query_industry,
                limit=task.limit,
                negative_keywords=list(task.negative_keywords or []),
            )
            raw_results = self.discovery_gateway.discover_businesses(query)

            validated_candidates: List[DiscoveredBusiness] = []
            rejected_radius = 0
            rejected_missing_coords = 0
            rejected_exclusions = 0
            rejected_classification = 0
            rejected_contradictory = 0

            for biz in raw_results:
                is_valid, reason = self.validator.validate_candidate(biz, task)
                if is_valid:
                    validated_candidates.append(biz)
                else:
                    reason_str = str(reason or "")
                    if "EXCEEDS_RADIUS" in reason_str:
                        rejected_radius += 1
                    elif "MISSING_COORDINATES" in reason_str:
                        rejected_missing_coords += 1
                    elif "CONTRADICTORY" in reason_str:
                        rejected_contradictory += 1
                    elif "EXCLUDED_" in reason_str:
                        rejected_exclusions += 1
                    else:
                        rejected_classification += 1

                    logger.info(
                        "Excluded candidate '%s' (category=%s): %s",
                        biz.name,
                        biz.category,
                        reason,
                    )

            is_truncated = len(raw_results) >= task.limit
            task.metadata["diagnostics"] = {
                "raw_retrieved": len(raw_results),
                "sample_truncated": is_truncated,
                "accepted": len(validated_candidates),
                "rejected_radius": rejected_radius,
                "rejected_missing_coords": rejected_missing_coords,
                "rejected_exclusions": rejected_exclusions,
                "rejected_classification": rejected_classification,
                "rejected_contradictory": rejected_contradictory,
            }
            if is_truncated:
                task.metadata["source_sample_truncated"] = True

            return validated_candidates
        except DiscoveryProviderError:
            raise
        except Exception as e:
            raise DiscoveryProviderError(
                f"Overture discovery execution failed for task '{task.id}': {e}"
            ) from e
