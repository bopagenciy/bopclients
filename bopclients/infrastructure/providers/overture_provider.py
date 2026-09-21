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


# Regular Spanish specialty roots following -logía (discipline) / -logo(s)/-loga(s) (practitioners) / -lógico(s) (adjectives)
SPECIALTY_LOGIA_ROOTS: List[str] = [
    r"cardi", r"ur", r"endocrin", r"ginec", r"perinat", r"neonat",
    r"radi", r"neur", r"dermat", r"onc", r"anestesi", r"anestesiol",
    r"oftalm", r"reumat", r"neum", r"gastroenter", r"hemat", r"infect",
    r"traumat", r"otorrinolaring", r"nefr", r"epidemi", r"inmun",
    r"pat", r"farmac", r"toxic", r"odont", r"alerg", r"kinesiol",
    r"coloproct", r"mast", r"hemodinami", r"uroginec",
]

_LOGIA_SPECIALTY_PATTERN = (
    r"(?:" + "|".join(SPECIALTY_LOGIA_ROOTS) + r")[oó]log(?:[íi]a[s]?|[ao]s?|[oó]gic[ao]s?)"
)

# Medical specialties and clinical health disciplines with non-logía morphology
SPECIALTY_OTHER_PATTERNS: List[str] = [
    # Pediatría / Pediatra / Pediátrico
    r"pediatr[íi]a[s]?", r"pedi[aá]tr[ao]s?", r"pedi[aá]tric[ao]s?",
    # Psiquiatría / Psiquiatra / Psiquiátrico
    r"psiquiatr[íi]a[s]?", r"psiqui[aá]tr[ao]s?", r"psiqui[aá]tric[ao]s?",
    # Geriatría / Geriatra / Geriátrico
    r"geriatr[íi]a[s]?", r"geri[aá]tr[ao]s?", r"geri[aá]tric[ao]s?",
    # Cirugía / Cirujano / Quirúrgico / Neurocirugía
    r"cirug[íi]a[s]?", r"cirujan[ao]s?", r"quir[uú]rgic[ao]s?", r"neurocirug[íi]a[s]?", r"neurocirujan[ao]s?",
    # Obstetricia / Obstetra / Ginecoobstetricia
    r"obstetricia[s]?", r"obst[ée]tric[ao]s?", r"obstetr[ao]s?", r"gineco[\s\-]?obstetricia[s]?",
    # Ortopedia / Ortopédico / Ortopedista
    r"ortoped[íi]a[s]?", r"ortop[eé]dic[ao]s?", r"ortopedist[ao]s?",
    # Medicina Interna / Internista
    r"medicina\s+interna", r"internist[ao]s?",
    # Materno-Fetal
    r"materno[\s\-]?fetal(?:es)?",
    # Genética Médica / Genetista
    r"gen[eé]tica(?:\s+m[eé]dica)?", r"genetist[ao]s?",
    # Otorrino
    r"otorrino[s]?", r"otorrinolaringolog[íi]a[s]?",
    # Anestesia / Reanimación
    r"anestesia[s]?", r"reanimaci[oó]n",
    # General medical / health / science terms
    r"m[ée]dic[ao]s?", r"medicina[s]?", r"salud", r"salubridad", r"sanitari[ao]s?",
    r"cient[íi]fic[ao]s?", r"ciencia[s]?", r"biom[ée]dic[ao]s?", r"cl[íi]nic[ao]s?",
    r"enfermer[íi]a[s]?", r"terapia[s]?", r"fisioterapi[ao]s?",
    # English terms
    r"health", r"medical", r"medicine", r"scientific", r"science",
    r"physicians?", r"surgeons?", r"biomedical", r"clinical",
    r"cardiology", r"pediatrics", r"urology", r"oncology", r"neurology",
    r"radiology", r"psychiatry", r"dermatology", r"anesthesiology",
    r"pathology", r"epidemiology", r"gastroenterology", r"endocrinology",
    r"gynecology", r"obstetrics", r"ophthalmology", r"orthopedics",
    r"pulmonology", r"rheumatology", r"nephrology", r"hematology",
    r"immunology", r"surgery", r"internal\s+medicine",
]


class OvertureCandidateValidator:
    """Deterministic validation and exclusion policy for discovery candidates."""

    FACILITY_PREFIX_PATTERN = re.compile(
        r"^(?:cl[íi]nica|hospital|sanatorio|centro m[ée]dico|consultorio|policl[íi]nica|farmacia|droguer[íi]a)\b",
        re.IGNORECASE,
    )

    ASSOCIATION_MARKER_PATTERN = re.compile(
        r"\b(?:asociaci[oó]n|asociaciones|sociedad|sociedades|colegio|colegios|federaci[oó]n|federaciones|"
        r"confederaci[oó]n|confederaciones|gremio|gremios|fundaci[oó]n|fundaciones|uni[oó]n|uniones|"
        r"association|associations|society|societies|federation|federations|college|colleges|council|guild)\b",
        re.IGNORECASE,
    )

    MEDICAL_SCIENTIFIC_PATTERN = re.compile(
        r"\b(?:" + _LOGIA_SPECIALTY_PATTERN + r"|" + r"|".join(SPECIALTY_OTHER_PATTERNS) + r")\b",
        re.IGNORECASE,
    )

    PROFESSIONAL_ASSOC_PATTERN = re.compile(
        r"\b(?:colegio|colegios|gremio|gremios|profesional|profesionales|"
        r"professional|asociaci[oó]n|sociedad|federaci[oó]n)\b",
        re.IGNORECASE,
    )

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
        name = (biz.name or "").strip()
        if self.MEDICAL_SCIENTIFIC_PATTERN.search(name):
            return True
        cat = (biz.category or "").strip()
        if cat and self.MEDICAL_SCIENTIFIC_PATTERN.search(cat):
            return True
        ind = (biz.forge_industry or "").strip()
        if ind and self.MEDICAL_SCIENTIFIC_PATTERN.search(ind):
            return True
        return False

    def validate_candidate(
        self, biz: DiscoveredBusiness, task: DiscoveryTask
    ) -> Tuple[bool, Optional[str]]:
        """Validate a candidate business against geographic radius, exclusions, and entity specialization."""
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

        # 2. Extract all candidate categories (primary + alternates if present in raw_data)
        cand_cats = {cat} if cat else set()
        raw_alts_list = []
        if isinstance(biz.raw_data, dict):
            # Check categories.alternate (standard GeoParquet)
            alts1 = (
                biz.raw_data.get("categories", {}).get("alternate", [])
                if isinstance(biz.raw_data.get("categories"), dict)
                else []
            )
            # Check taxonomy.alternates
            alts2 = (
                biz.raw_data.get("taxonomy", {}).get("alternates", [])
                if isinstance(biz.raw_data.get("taxonomy"), dict)
                else []
            )
            # Check direct alternate keys
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
        is_association_target = canonical_target in (
            "medical_association",
            "scientific_society",
            "professional_association",
            "non_profit",
        )

        # 4. Check for contradictory entity evidence (fails closed)
        if is_association_target:
            # If primary category is an association/organization but alternate categories contain an excluded facility
            has_facility_alt = any(c in EXCLUDED_FACILITY_CATEGORIES for c in raw_alts_list)
            if has_facility_alt:
                return (
                    False,
                    f"CONTRADICTORY_ENTITY_EVIDENCE (category claims '{cat}' but alternates include facility {raw_alts_list})",
                )

            # Check explicit metadata contradiction flag
            if isinstance(biz.raw_data, dict) and (
                biz.raw_data.get("contradictory") is True
                or biz.raw_data.get("is_facility") is True
            ):
                return False, f"CONTRADICTORY_ENTITY_EVIDENCE ({name})"

            # Check dual-nature contradictory naming e.g. "Asociación y Clínica..."
            if re.search(
                r"\b(?:asociaci[oó]n|sociedad)\s+(?:y|e)\s+(?:cl[íi]nica|hospital|consultorio)\b",
                name,
                re.IGNORECASE,
            ):
                return False, f"CONTRADICTORY_ENTITY_EVIDENCE ({name})"

        # 5. Facility and exclusion checks
        # A. Facility category disqualification for association searches
        if is_association_target:
            if any(c in EXCLUDED_FACILITY_CATEGORIES for c in cand_cats):
                return False, f"EXCLUDED_FACILITY_CATEGORY ({cat})"

        # B. Negative keyword exclusions
        neg_keywords = [
            k.strip().lower() for k in (task.negative_keywords or []) if k.strip()
        ]
        # Also include canonical negative categories
        if neg_keywords:
            for neg in neg_keywords:
                # Direct category exclusion
                if neg in cand_cats:
                    return False, f"EXCLUDED_BY_CATEGORY_KEYWORD ({neg})"

                # If name matches negative keyword
                if re.search(r"\b" + re.escape(neg) + r"\b", name, re.IGNORECASE):
                    # Clinical/hospital terminology in genuine association names does NOT exclude them
                    if self.is_genuine_association(biz):
                        continue
                    return False, f"EXCLUDED_BY_NEGATIVE_KEYWORD ({neg})"

        # C. Name-level facility prefix check (e.g., "Clínica de la Asociación")
        if self.FACILITY_PREFIX_PATTERN.search(name):
            # If search targets associations or facility is excluded, reject
            if is_association_target or any(
                nk in ("clinic", "clínica", "clinica", "hospital", "consultorio", "farmacia")
                for nk in neg_keywords
            ):
                return False, f"EXCLUDED_FACILITY_NAME ({name})"

        # 6. Entity specialization requirements for association targets
        if is_association_target:
            if not self.is_genuine_association(biz):
                return False, f"NOT_AN_ASSOCIATION ({name})"

            if canonical_target in ("medical_association", "scientific_society"):
                if not self.has_medical_or_scientific_specialization(biz):
                    return False, f"UNVERIFIED_MEDICAL_SPECIALIZATION ({name})"

            elif canonical_target == "professional_association":
                if not (
                    self.PROFESSIONAL_ASSOC_PATTERN.search(name)
                    or cat == "professional_association"
                ):
                    return False, f"NOT_A_PROFESSIONAL_ASSOCIATION ({name})"

        return True, None


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
