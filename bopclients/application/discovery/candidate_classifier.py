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
    target_intent: str = "medical_association"  # e.g., "medical_association", "scientific_society", "professional_association", "non_profit"
    canonical_category_hints: Set[str] = field(default_factory=set)
    canonical_facility_hints: Set[str] = field(default_factory=set)
    negative_keywords: List[str] = field(default_factory=list)
    raw_metadata: Dict[str, Any] = field(default_factory=dict)


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
    """Source-neutral organization candidate classifier implementing two-independent-signals policy."""

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
        is_association_target = target_norm in (
            "medical_association",
            "scientific_society",
            "professional_association",
            "non_profit",
        )

        # 1. Facility Prefix Exclusion
        if self.FACILITY_PREFIX_PATTERN.search(name):
            return ClassificationDecision(
                status=CandidateClassificationStatus.REJECTED,
                is_valid=False,
                reason=f"EXCLUDED_FACILITY_NAME ({name})",
            )

        # 2. Canonical Facility Category Exclusion
        if request.canonical_facility_hints:
            hint_str = ", ".join(sorted(request.canonical_facility_hints))
            return ClassificationDecision(
                status=CandidateClassificationStatus.REJECTED,
                is_valid=False,
                reason=f"EXCLUDED_FACILITY_CATEGORY ({hint_str})",
            )

        # 3. Contradictory Entity Evidence (fails closed)
        if is_association_target:
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
                # Check alternate category facility contradictions
                alts = request.raw_metadata.get("alternate_categories") or []
                if isinstance(alts, list):
                    alt_lower = [str(a).lower().strip() for a in alts]
                    if any(a in ("clinic", "hospital", "doctor", "dentist", "medical_office", "pharmacy", "medical_center") for a in alt_lower):
                        return ClassificationDecision(
                            status=CandidateClassificationStatus.REJECTED,
                            is_valid=False,
                            reason=f"CONTRADICTORY_ENTITY_EVIDENCE (category claims association but alternates include facility {alts})",
                        )

            # Dual-nature contradictory naming e.g. "Asociación y Clínica..."
            if re.search(r"\b(?:asociaci[oó]n|sociedad)\s+(?:y|e)\s+(?:cl[íi]nica|hospital|consultorio)\b", name, re.IGNORECASE):
                return ClassificationDecision(
                    status=CandidateClassificationStatus.REJECTED,
                    is_valid=False,
                    reason=f"CONTRADICTORY_ENTITY_EVIDENCE ({name})",
                )

        # 4. Negative Keyword Exclusions
        is_genuine = self.is_genuine_association_name(name, request.canonical_category_hints)
        neg_keywords = [k.strip().lower() for k in (request.negative_keywords or []) if k.strip()]
        if neg_keywords:
            for neg in neg_keywords:
                # Direct category hint exclusion
                if neg in request.canonical_category_hints:
                    return ClassificationDecision(
                        status=CandidateClassificationStatus.REJECTED,
                        is_valid=False,
                        reason=f"EXCLUDED_BY_CATEGORY_KEYWORD ({neg})",
                    )

                # Name keyword matching
                if re.search(r"\b" + re.escape(neg) + r"\b", name, re.IGNORECASE):
                    # Clinical/hospital terminology in genuine association names does NOT exclude them
                    if is_genuine:
                        continue
                    return ClassificationDecision(
                        status=CandidateClassificationStatus.REJECTED,
                        is_valid=False,
                        reason=f"EXCLUDED_BY_NEGATIVE_KEYWORD ({neg})",
                    )

        # 5. Organization-Type Evidence (Two-Independent-Signals: Pillar 1)
        if is_association_target and not is_genuine:
            return ClassificationDecision(
                status=CandidateClassificationStatus.REJECTED,
                is_valid=False,
                reason=f"NOT_AN_ASSOCIATION ({name})",
            )

        # 6. Sector Specialization (Two-Independent-Signals: Pillar 2)
        if target_norm in ("medical_association", "scientific_society"):
            if not self.has_medical_or_scientific_specialization(name, request.canonical_category_hints, request.raw_metadata):
                return ClassificationDecision(
                    status=CandidateClassificationStatus.REJECTED,
                    is_valid=False,
                    reason=f"UNVERIFIED_MEDICAL_SPECIALIZATION ({name})",
                )
        elif target_norm == "professional_association":
            has_prof_name = bool(self.PROFESSIONAL_ASSOC_PATTERN.search(name))
            has_prof_hint = "professional_association" in request.canonical_category_hints
            if not (has_prof_name or has_prof_hint):
                return ClassificationDecision(
                    status=CandidateClassificationStatus.REJECTED,
                    is_valid=False,
                    reason=f"NOT_A_PROFESSIONAL_ASSOCIATION ({name})",
                )

        # All gates passed -> Accepted as candidate
        return ClassificationDecision(
            status=CandidateClassificationStatus.ACCEPTED_CANDIDATE,
            is_valid=True,
            reason=None,
            details={"target_intent": target_norm, "name": name},
        )
