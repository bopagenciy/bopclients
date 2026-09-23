"""Source-neutral organization candidate classifier for discovery verification.

Decouples lexical organization markers, clinical specialty recognition, and facility
exclusion rules from provider-specific categories and geographic assumptions.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import re
from typing import List, Set, Optional, Dict, Any, Tuple


class CandidateClassificationStatus(str, Enum):
    """Structured decision status for organization candidate classification."""

    ACCEPTED_CANDIDATE = "ACCEPTED_CANDIDATE"
    REJECTED = "REJECTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


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


@dataclass
class CandidateClassificationRequest:
    """Standardized input for source-neutral candidate classification."""

    name: str
    target_intent: str = "medical_association"  # e.g., "medical_association", "scientific_society", "professional_association", "non_profit", "construction", "industrial_distributor", "b2b_software"
    canonical_category_hints: Set[str] = field(default_factory=set)
    canonical_facility_hints: Set[str] = field(default_factory=set)
    negative_keywords: List[str] = field(default_factory=list)
    raw_metadata: Dict[str, Any] = field(default_factory=dict)

    # General-Purpose Structured Criteria (additive, backward-compatible):
    target_organization_types: List[str] = field(default_factory=list)
    target_business_activities: List[str] = field(default_factory=list)
    target_offerings: List[str] = field(default_factory=list)
    target_specializations: List[str] = field(default_factory=list)
    excluded_organization_types: List[str] = field(default_factory=list)
    excluded_attributes: List[str] = field(default_factory=list)


@dataclass
class ClassificationDecision:
    """Truthful classification outcome with explicit status and explanatory code."""

    status: CandidateClassificationStatus
    is_valid: bool
    reason: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class IOrganizationCandidateClassifier(ABC):
    """Abstract contract for source-neutral candidate organization classification."""

    @abstractmethod
    def classify(self, request: CandidateClassificationRequest) -> ClassificationDecision:
        """Classify candidate organization using two-independent-signals and defensive exclusion policies."""
        ...


class OrganizationCandidateClassifier(IOrganizationCandidateClassifier):
    """Source-neutral organization candidate classifier implementing sector-aware verification."""

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

    # Sector: Construction Company
    CONSTRUCTION_EVIDENCE_PATTERN = re.compile(
        r"\b(?:constructora[s]?|construcci[oó]n|construcciones|construction|builders?|general\s+contractors?|"
        r"contratista[s]?(?:\s+generales?)?|obras\s+civiles|ingenier[íi]a\s+civil|civil\s+engineering|"
        r"edificaciones|infraestructura|urbanizaciones|desarrollos\s+urbanos|remodelaciones|"
        r"commercial\s+construction|residential\s+construction|heavy\s+civil|contracting\s+services?|civil\s+works?)\b",
        re.IGNORECASE,
    )
    REAL_ESTATE_NOISE_PATTERN = re.compile(
        r"\b(?:inmobiliaria[s]?|inmobiliario[s]?|bienes\s+ra[íi]ces|real\s+estate|realtor[s]?|inmuebles|"
        r"bienesraices|leasing\s+inmobiliario|corretaje\s+inmobiliario|propiedades|realty|property\s+management)\b",
        re.IGNORECASE,
    )

    # Sector: Industrial Distributor
    INDUSTRIAL_DIST_EVIDENCE_PATTERN = re.compile(
        r"\b(?:distribuidora[s]?|distribuidor[es]?|distribuci[oó]n|distributor[s]?|distribution|mayorista[s]?|"
        r"wholesale[rs]?|suministros?\s+industriales?|industrial\s+suppl(?:y|ies)|proveedor\s+industrial|"
        r"industrial\s+provider|herramientas?\s+industriales?|industrial\s+tools?|abrasivos?|abrasives?|"
        r"seguridad\s+industrial|safety\s+supplies?|epp|ppe|equipos?\s+industriales?|industrial\s+equipment|"
        r"rodamientos|torniller[íi]a|v[aá]lvulas|ferreter[íi]a\s+industrial|industrial\s+hardware|"
        r"mangueras\s+industriales|soldadura|welding\s+supplies)\b",
        re.IGNORECASE,
    )
    RETAIL_STORE_NOISE_PATTERN = re.compile(
        r"\b(?:supermercado[s]?|supermarket[s]?|tienda\s+de\s+ropa|clothing\s+store|boutique[s]?|zapater[íi]a[s]?|"
        r"shoe\s+store|comercio\s+minorista|consumer\s+goods|department\s+store|tienda\s+por\s+departamentos)\b",
        re.IGNORECASE,
    )

    # Sector: B2B Software Company
    B2B_SOFTWARE_EVIDENCE_PATTERN = re.compile(
        r"\b(?:software(?:\s+(?:development|developers?|engineers?|company|solutions?|empresarial|para\s+empresas))?|"
        r"saas|b2b\s+software|cloud\s+services?|servicios\s+cloud|plataforma\s+(?:digital|cloud|de\s+software|saas)|"
        r"desarrollo\s+de\s+software|desarrolladora\s+de\s+software|sistemas\s+de\s+informaci[oó]n|"
        r"soluciones\s+tecnol[oó]gicas|erp|crm|api|enterprise\s+software|software\s+b2b|tech\s+solutions?|"
        r"it\s+consulting|consultor[íi]a\s+(?:ti|it|de\s+software))\b",
        re.IGNORECASE,
    )
    ELECTRONICS_RETAIL_NOISE_PATTERN = re.compile(
        r"\b(?:tienda\s+de\s+(?:computadores|computadoras|electr[oó]nica|tecnolog[íi]a|celulares)|"
        r"venta\s+de\s+(?:celulares|repuestos|computadores|computadoras|accesorios)|"
        r"reparaci[oó]n\s+de\s+(?:computadores|celulares)|electronics?\s+store|computer\s+repair|"
        r"phone\s+repair|cell\s+phone\s+store|retail\s+hardware|tienda\s+de\s+audio)\b",
        re.IGNORECASE,
    )

    def is_genuine_association_name(self, name: str, category_hints: Optional[Set[str]] = None) -> bool:
        """Evaluate whether name and hints establish institutional organization identity."""
        clean_name = (name or "").strip()
        if not clean_name:
            return False

        if self.FACILITY_PREFIX_PATTERN.search(clean_name):
            return False

        if category_hints and any(h in category_hints for h in ("association", "non_profit", "professional_association", "non_governmental_organization")):
            return True

        return bool(self.ASSOCIATION_MARKER_PATTERN.search(clean_name))

    def has_medical_or_scientific_specialization(
        self,
        name: str,
        category_hints: Optional[Set[str]] = None,
        raw_metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Evaluate whether name, hints, or metadata provide verified medical/scientific specialization evidence."""
        clean_name = (name or "").strip()
        if clean_name and self.MEDICAL_SCIENTIFIC_PATTERN.search(clean_name):
            return True

        if category_hints:
            for hint in category_hints:
                if hint and self.MEDICAL_SCIENTIFIC_PATTERN.search(hint):
                    return True

        if raw_metadata:
            ind = str(raw_metadata.get("industry") or raw_metadata.get("forge_industry") or "").strip()
            if ind and self.MEDICAL_SCIENTIFIC_PATTERN.search(ind):
                return True
            cat = str(raw_metadata.get("category") or "").strip()
            if cat and self.MEDICAL_SCIENTIFIC_PATTERN.search(cat):
                return True

        return False

    def classify(self, request: CandidateClassificationRequest) -> ClassificationDecision:
        name = (request.name or "").strip()
        if not name:
            return ClassificationDecision(
                status=CandidateClassificationStatus.INSUFFICIENT_EVIDENCE,
                is_valid=False,
                reason="MISSING_ORGANIZATION_NAME",
            )

        target_norm = (request.target_intent or "").strip().lower()

        # Build full candidate context for textual evidence analysis
        context_parts = [name]
        for h in request.canonical_category_hints:
            context_parts.append(str(h))
        if isinstance(request.raw_metadata, dict):
            for k in ("title", "description", "snippet", "category", "industry", "forge_industry"):
                val = request.raw_metadata.get(k)
                if val and isinstance(val, str):
                    context_parts.append(val)
        full_text = " ".join(context_parts)

        # Determine target sector
        is_medical_assoc = target_norm in ("medical_association", "scientific_society")
        is_prof_assoc = target_norm == "professional_association"
        is_non_profit = target_norm == "non_profit"
        is_explicit_assoc = any(ot in ("association", "society", "colegio", "federation", "gremio") for ot in request.target_organization_types)
        is_general_assoc = target_norm in ("association", "society") or is_explicit_assoc

        is_construction = (
            target_norm in ("construction", "construction_company", "general_contractor", "builder", "obras_civiles", "civil_engineering", "contratista")
            or any(act in ("construction", "contracting", "civil_engineering") for act in request.target_business_activities)
            or any(ot in ("construction_company", "contractor", "builder") for ot in request.target_organization_types)
            or any(ind in ("construction", "general_contractor", "civil_engineering") for ind in request.canonical_category_hints)
        )

        is_distribution = (
            target_norm in ("industrial_distributor", "wholesale_distributor", "industrial_supplies", "industrial_tools", "abrasives", "safety_supplies", "distribuidor_industrial", "wholesale")
            or any(act in ("distribution", "wholesale") for act in request.target_business_activities)
            or any(ot in ("distributor", "wholesaler") for ot in request.target_organization_types)
            or any(ind in ("industrial_distributor", "wholesale_distributor", "industrial_supplies") for ind in request.canonical_category_hints)
        )

        is_software = (
            target_norm in ("b2b_software", "software", "saas", "software_development", "technology_company", "technology", "tecnologia", "cloud_services", "it_consulting")
            or any(act in ("software_development", "saas", "cloud_services") for act in request.target_business_activities)
            or any(ot in ("software_company", "saas_company") for ot in request.target_organization_types)
            or any(ind in ("software", "b2b_software", "saas", "technology") for ind in request.canonical_category_hints)
        )

        is_any_association = is_medical_assoc or is_prof_assoc or is_non_profit or is_general_assoc

        # ---------------------------------------------------------
        # 1. Association Target Facility and Contradiction Gates
        # ---------------------------------------------------------
        if is_any_association or any(ot in ("clinic", "hospital") for ot in request.excluded_organization_types):
            # Facility Prefix Exclusion
            if self.FACILITY_PREFIX_PATTERN.search(name):
                return ClassificationDecision(
                    status=CandidateClassificationStatus.REJECTED,
                    is_valid=False,
                    reason=f"EXCLUDED_FACILITY_NAME ({name})",
                )

            # Canonical Facility Category Exclusion
            if request.canonical_facility_hints:
                hint_str = ", ".join(sorted(request.canonical_facility_hints))
                return ClassificationDecision(
                    status=CandidateClassificationStatus.REJECTED,
                    is_valid=False,
                    reason=f"EXCLUDED_FACILITY_CATEGORY ({hint_str})",
                )

        if is_any_association:
            # Contradictory Entity Evidence (fails closed)
            if isinstance(request.raw_metadata, dict):
                if (
                    request.raw_metadata.get("contradictory") is True
                    or request.raw_metadata.get("is_facility") is True
                ):
                    return ClassificationDecision(
                        status=CandidateClassificationStatus.REJECTED,
                        is_valid=False,
                        reason=f"CONTRADICTORY_ENTITY_EVIDENCE ({name})",
                    )
                alts = request.raw_metadata.get("alternate_categories") or []
                if isinstance(alts, list):
                    alt_lower = [str(a).lower().strip() for a in alts]
                    if any(a in ("clinic", "hospital", "doctor", "dentist", "medical_office", "pharmacy", "medical_center") for a in alt_lower):
                        return ClassificationDecision(
                            status=CandidateClassificationStatus.REJECTED,
                            is_valid=False,
                            reason=f"CONTRADICTORY_ENTITY_EVIDENCE (category claims association but alternates include facility {alts})",
                        )

            # Dual-nature contradictory naming
            if re.search(r"\b(?:asociaci[oó]n|sociedad)\s+(?:y|e)\s+(?:cl[íi]nica|hospital|consultorio)\b", name, re.IGNORECASE):
                return ClassificationDecision(
                    status=CandidateClassificationStatus.REJECTED,
                    is_valid=False,
                    reason=f"CONTRADICTORY_ENTITY_EVIDENCE ({name})",
                )

        # ---------------------------------------------------------
        # 2. Negative Keyword and Excluded Attribute Gates (Universal)
        # ---------------------------------------------------------
        is_genuine_assoc = self.is_genuine_association_name(name, request.canonical_category_hints)
        neg_keywords = [k.strip().lower() for k in (request.negative_keywords or []) if k.strip()]
        for ex_attr in (request.excluded_attributes or []):
            clean_ex = ex_attr.strip().lower()
            if clean_ex and clean_ex not in neg_keywords:
                neg_keywords.append(clean_ex)

        for neg in neg_keywords:
            if neg in request.canonical_category_hints:
                return ClassificationDecision(
                    status=CandidateClassificationStatus.REJECTED,
                    is_valid=False,
                    reason=f"EXCLUDED_BY_CATEGORY_KEYWORD ({neg})",
                )
            if re.search(r"\b" + re.escape(neg) + r"\b", full_text, re.IGNORECASE):
                # Clinical/hospital terminology in genuine association names does NOT exclude them
                if is_any_association and is_genuine_assoc and neg in ("clinic", "clínica", "clinica", "hospital", "hospitales", "medical_office"):
                    continue
                return ClassificationDecision(
                    status=CandidateClassificationStatus.REJECTED,
                    is_valid=False,
                    reason=f"EXCLUDED_BY_NEGATIVE_KEYWORD ({neg})",
                )

        # Check explicit excluded organization types
        for ex_org in (request.excluded_organization_types or []):
            ex_norm = ex_org.strip().lower()
            if ex_norm in ("real_estate", "inmobiliaria"):
                if self.REAL_ESTATE_NOISE_PATTERN.search(full_text):
                    return ClassificationDecision(
                        status=CandidateClassificationStatus.REJECTED,
                        is_valid=False,
                        reason=f"EXCLUDED_REAL_ESTATE_AGENCY ({name})",
                    )
            elif ex_norm in ("retail", "retail_store"):
                if self.RETAIL_STORE_NOISE_PATTERN.search(full_text):
                    return ClassificationDecision(
                        status=CandidateClassificationStatus.REJECTED,
                        is_valid=False,
                        reason=f"EXCLUDED_RETAIL_STORE ({name})",
                    )
            elif ex_norm in ("electronics_store", "tienda_electronica"):
                if self.ELECTRONICS_RETAIL_NOISE_PATTERN.search(full_text):
                    return ClassificationDecision(
                        status=CandidateClassificationStatus.REJECTED,
                        is_valid=False,
                        reason=f"EXCLUDED_ELECTRONICS_RETAILER ({name})",
                    )

        # ---------------------------------------------------------
        # 3. Sector-Specific Classification Policies
        # ---------------------------------------------------------

        # --- Policy A: Association Organizations ---
        if is_any_association:
            # Pillar 1: Organization-Type Evidence
            if not is_genuine_assoc:
                return ClassificationDecision(
                    status=CandidateClassificationStatus.REJECTED,
                    is_valid=False,
                    reason=f"NOT_AN_ASSOCIATION ({name})",
                )

            # Pillar 2: Sector Specialization
            if is_medical_assoc:
                if not self.has_medical_or_scientific_specialization(name, request.canonical_category_hints, request.raw_metadata):
                    return ClassificationDecision(
                        status=CandidateClassificationStatus.REJECTED,
                        is_valid=False,
                        reason=f"UNVERIFIED_MEDICAL_SPECIALIZATION ({name})",
                    )
            elif is_prof_assoc:
                has_prof_name = bool(self.PROFESSIONAL_ASSOC_PATTERN.search(name))
                has_prof_hint = "professional_association" in request.canonical_category_hints
                if not (has_prof_name or has_prof_hint):
                    return ClassificationDecision(
                        status=CandidateClassificationStatus.REJECTED,
                        is_valid=False,
                        reason=f"NOT_A_PROFESSIONAL_ASSOCIATION ({name})",
                    )

            return ClassificationDecision(
                status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
                is_valid=True,
                reason=None,
                details={"target_intent": target_norm, "name": name, "sector": "association"},
            )

        # --- Policy B: Construction Companies ---
        if is_construction:
            # Noise exclusion: Real estate agency
            if self.REAL_ESTATE_NOISE_PATTERN.search(full_text):
                # If name explicitly indicates real estate rather than contracting
                if self.REAL_ESTATE_NOISE_PATTERN.search(name) or not self.CONSTRUCTION_EVIDENCE_PATTERN.search(name):
                    return ClassificationDecision(
                        status=CandidateClassificationStatus.REJECTED,
                        is_valid=False,
                        reason=f"EXCLUDED_REAL_ESTATE_AGENCY ({name})",
                    )

            # Positive evidence: construction company or contracting activity
            if self.CONSTRUCTION_EVIDENCE_PATTERN.search(full_text):
                return ClassificationDecision(
                    status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
                    is_valid=True,
                    reason=None,
                    details={"target_intent": target_norm, "name": name, "sector": "construction"},
                )

            return ClassificationDecision(
                status=CandidateClassificationStatus.INSUFFICIENT_EVIDENCE,
                is_valid=False,
                reason=f"INSUFFICIENT_EVIDENCE_FOR_CONSTRUCTION ({name})",
                details={"target_intent": target_norm, "name": name},
            )

        # --- Policy C: Industrial Distributors ---
        if is_distribution:
            # Noise exclusion: Unrelated retail store
            if self.RETAIL_STORE_NOISE_PATTERN.search(full_text):
                return ClassificationDecision(
                    status=CandidateClassificationStatus.REJECTED,
                    is_valid=False,
                    reason=f"EXCLUDED_RETAIL_STORE ({name})",
                )

            # Positive evidence: wholesale/distribution or industrial supplies/tools/safety
            if self.INDUSTRIAL_DIST_EVIDENCE_PATTERN.search(full_text):
                return ClassificationDecision(
                    status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
                    is_valid=True,
                    reason=None,
                    details={"target_intent": target_norm, "name": name, "sector": "industrial_distribution"},
                )

            return ClassificationDecision(
                status=CandidateClassificationStatus.INSUFFICIENT_EVIDENCE,
                is_valid=False,
                reason=f"INSUFFICIENT_EVIDENCE_FOR_INDUSTRIAL_DISTRIBUTION ({name})",
                details={"target_intent": target_norm, "name": name},
            )

        # --- Policy D: B2B Software Companies ---
        if is_software:
            # Noise exclusion: Electronics retailer / computer repair shop
            if self.ELECTRONICS_RETAIL_NOISE_PATTERN.search(full_text):
                return ClassificationDecision(
                    status=CandidateClassificationStatus.REJECTED,
                    is_valid=False,
                    reason=f"EXCLUDED_ELECTRONICS_RETAILER ({name})",
                )

            # Positive evidence: B2B software, SaaS, software development, cloud platform
            if self.B2B_SOFTWARE_EVIDENCE_PATTERN.search(full_text):
                return ClassificationDecision(
                    status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
                    is_valid=True,
                    reason=None,
                    details={"target_intent": target_norm, "name": name, "sector": "b2b_software"},
                )

            return ClassificationDecision(
                status=CandidateClassificationStatus.INSUFFICIENT_EVIDENCE,
                is_valid=False,
                reason=f"INSUFFICIENT_EVIDENCE_FOR_B2B_SOFTWARE ({name})",
                details={"target_intent": target_norm, "name": name},
            )

        # --- Policy E: General / Unspecified Intent Fallback ---
        # When evidence is insufficient, return INSUFFICIENT_EVIDENCE rather than inventing a match
        return ClassificationDecision(
            status=CandidateClassificationStatus.INSUFFICIENT_EVIDENCE,
            is_valid=False,
            reason=f"INSUFFICIENT_EVIDENCE ({name})",
            details={"target_intent": target_norm, "name": name},
        )
