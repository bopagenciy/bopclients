"""Application service for structured candidate qualification.

Distinguishes raw search matches, verified organization identities,
ICP-matching candidates, and candidates ready for human commercial review.
General-purpose across B2B verticals (medical, construction, industrial, software, restaurants).
"""

import re
import urllib.parse
from typing import Optional, Dict, Any, List, Set, Tuple

from bopclients.domain.candidate_qualification import (
    CandidateQualificationStatus,
    EntityArchetype,
    GeographicEvidenceStatus,
    CurrentActivityStatus,
    CandidateQualificationResult,
)
from bopclients.application.search_dto import DiscoveryTask
from bopclients.application.discovery.candidate_classifier import (
    ClassificationDecision,
    CandidateClassificationStatus,
)


class OrganizationCandidateQualifier:
    """Evaluates identity, source authority, geographic scope, and operational freshness."""

    ARCHIVE_HOSTS: Set[str] = {
        "oocities.org",
        "oocities.com",
        "geocities.ws",
        "geocities.com",
        "archive.org",
        "web.archive.org",
        "waybackmachine.org",
    }

    DIRECTORY_HOSTS: Set[str] = {
        "paginasamarillas.com.co",
        "paginasamarillas.com",
        "yellowpages.com",
        "yelp.com",
        "tripadvisor.com",
        "directorioempresas.co",
        "directorio.com.co",
        "directorios.com",
        "guiamedica.com.co",
        "doctoralia.co",
        "wikipedia.org",
        "linkedin.com",
        "facebook.com",
        "instagram.com",
        "twitter.com",
        "x.com",
    }

    # Department / state mappings for Colombian cities
    REGIONAL_CITY_MAP: Dict[str, str] = {
        "cali": "valle",
        "medellin": "antioquia",
        "medellín": "antioquia",
        "bogota": "cundinamarca",
        "bogotá": "cundinamarca",
        "barranquilla": "atlantico",
        "bucaramanga": "santander",
    }

    def qualify(
        self,
        candidate_name: str,
        target_intent: str,
        base_classification: ClassificationDecision,
        raw_title: str,
        url: str,
        snippet: str,
        task: DiscoveryTask,
    ) -> CandidateQualificationResult:
        """Perform comprehensive qualification on a discovered candidate."""
        clean_url = (url or "").strip()
        parsed = urllib.parse.urlparse(clean_url)
        host = (parsed.netloc or "").lower().strip()
        if host.startswith("www."):
            host = host[4:]

        combined_text = f"{raw_title} {snippet} {parsed.path}".lower()
        target_norm = (target_intent or "medical_association").strip().lower()

        # 1. Determine Entity Archetype
        archetype = self._determine_archetype(
            candidate_name=candidate_name,
            raw_title=raw_title,
            snippet=snippet,
            path=parsed.path,
            host=host,
            combined_text=combined_text,
            target_norm=target_norm,
        )

        # 2. Source URL vs Organization Website
        org_website = self._determine_organization_website(
            archetype=archetype,
            parsed_url=parsed,
            host=host,
        )

        # 3. Determine Geographic Evidence Status
        geo_status = self._determine_geographic_status(
            combined_text=combined_text,
            task=task,
        )

        # 4. Determine Current Activity Status
        activity_status = self._determine_activity_status(
            host=host,
            archetype=archetype,
            combined_text=combined_text,
        )

        # 5. Evaluate Commercial Review Gate
        missing_evidence: List[str] = []
        qualification_reasons: List[str] = []

        if not base_classification.is_valid:
            # Base classification rejected or insufficient
            if base_classification.status == CandidateClassificationStatus.INSUFFICIENT_EVIDENCE:
                q_status = CandidateQualificationStatus.INSUFFICIENT_EVIDENCE
            else:
                q_status = CandidateQualificationStatus.REJECTED
            is_ready = False
            missing_evidence.append(base_classification.reason or "BASE_CLASSIFICATION_FAILED")
        else:
            # Base classification passed; evaluate qualification gates
            is_ready = True

            # Gate A: Archetype compatibility with target intent
            archetype_ok, arch_err = self._check_archetype_compatibility(target_norm, archetype)
            if not archetype_ok:
                is_ready = False
                missing_evidence.append(arch_err)
            else:
                qualification_reasons.append("COMPATIBLE_ENTITY_ARCHETYPE")

            # Gate B: Geographic satisfaction
            geo_ok, geo_err = self._check_geographic_satisfaction(geo_status, task)
            if not geo_ok:
                is_ready = False
                missing_evidence.append(geo_err)
            else:
                qualification_reasons.append("GEOGRAPHIC_CRITERIA_SATISFIED")

            # Gate C: Source authority & website
            if host in self.DIRECTORY_HOSTS or archetype == EntityArchetype.DIRECTORY_LISTING or org_website == "UNKNOWN" or not org_website:
                is_ready = False
                missing_evidence.append("OFFICIAL_ORGANIZATION_WEBSITE_UNKNOWN")
            else:
                qualification_reasons.append("OFFICIAL_DOMAIN_IDENTIFIED")

            # Gate D: Current activity requirement
            if activity_status == CurrentActivityStatus.HISTORICAL_ACTIVITY_ONLY:
                is_ready = False
                missing_evidence.append("HISTORICAL_ARCHIVE_LACKS_CURRENT_ACTIVITY_EVIDENCE")
            elif activity_status == CurrentActivityStatus.CURRENT_ACTIVITY_EVIDENCED:
                qualification_reasons.append("CURRENT_ACTIVITY_EVIDENCED")

            if is_ready:
                q_status = CandidateQualificationStatus.READY_FOR_COMMERCIAL_REVIEW
                qualification_reasons.append("READY_FOR_COMMERCIAL_REVIEW")
            else:
                q_status = CandidateQualificationStatus.SEARCH_MATCH
                qualification_reasons.append("SEARCH_MATCH_REQUIRES_ADDITIONAL_QUALIFICATION")

        return CandidateQualificationResult(
            qualification_status=q_status,
            entity_archetype=archetype,
            geographic_evidence_status=geo_status,
            current_activity_status=activity_status,
            source_url=clean_url,
            source_host=host,
            organization_website=org_website,
            is_commercial_review_ready=is_ready,
            qualification_reasons=qualification_reasons,
            missing_evidence=missing_evidence,
            raw_details={
                "base_status": base_classification.status.value,
                "base_reason": base_classification.reason,
            },
        )

    def _determine_archetype(
        self,
        candidate_name: str,
        raw_title: str,
        snippet: str,
        path: str,
        host: str,
        combined_text: str,
        target_norm: str,
    ) -> EntityArchetype:
        """Differentiate entity archetype using lexical, path, and source signals."""
        # 1. Directory Listing
        if host in self.DIRECTORY_HOSTS or re.search(
            r"\b(?:directorio|directorios|gu[íi]a de empresas|p[aá]ginas amarillas|listado de empresas|perfil en directorio)\b",
            combined_text,
        ):
            return EntityArchetype.DIRECTORY_LISTING

        # 2. Historical Archive Reference
        if host in self.ARCHIVE_HOSTS or re.search(
            r"\b(?:sitio archivado|p[aá]gina archivada|archivo hist[oó]rico|geocities archive|historical archive)\b",
            combined_text,
        ):
            return EntityArchetype.HISTORICAL_REFERENCE

        # 3. Student Organization
        if re.search(
            r"\b(?:estudiantes? de medicina|estudiantil(?:es)?|asociaci[oó]n cient[íi]fica de estudiantes|"
            r"rama estudiantil|cap[íi]tulo estudiantil|student association|student club|semillero estudiantil|"
            r"estudiantes de ingenier[íi]a|club de programaci[oó]n|coding club|university club)\b",
            combined_text,
        ):
            return EntityArchetype.STUDENT_ORGANIZATION

        # 4. Internal Academic / Training Program or Course
        path_lower = (path or "").lower()
        has_program_path = bool(re.search(r"/(?:programas?|diplomados?|cursos?|capacitacion|training|courses?|catalogo|catalog)/", path_lower))
        has_program_text = bool(re.search(
            r"\b(?:diplomado[s]?|curso[s]?|capacitaci[oó]n|oferta acad[eé]mica|programa[s]? de formaci[oó]n|"
            r"m[oó]dulo[s]? de formaci[oó]n|plan de estudios|syllabus|curriculum|training program)\b",
            combined_text,
        ))
        is_standalone_association = bool(re.search(
            r"^(?:colegio m[eé]dico|asociaci[oó]n m[eé]dica|sociedad m[eé]dica|sociedad colombiana)\b",
            raw_title.strip().lower(),
        ))
        if (has_program_path or has_program_text) and not is_standalone_association:
            return EntityArchetype.INTERNAL_PROGRAM

        # 5. Article or Publication / Recipe
        has_article_path = bool(re.search(r"/(?:noticias?|blog|articulos?|post|news|recetas?|recipe)/", path_lower))
        has_article_text = bool(re.search(
            r"\b(?:c[oó]mo preparar|receta de|recetas para|art[íi]culo cient[íi]fico|noticia sobre|blog post|"
            r"gu[íi]a de compra|cat[aá]logo de productos)\b",
            combined_text,
        ))
        if has_article_path or has_article_text:
            return EntityArchetype.ARTICLE_OR_PUBLICATION

        # 6. Federation / Umbrella Group
        if re.search(
            r"\b(?:federaci[oó]n|federacion|confederaci[oó]n|confederacion|asociaci[oó]n de sociedades|"
            r"asociaci[oó]n de asociaciones|sociedad de sociedades|national federation)\b",
            combined_text,
        ):
            return EntityArchetype.FEDERATION

        # 7. Professional Association
        if target_norm in ("medical_association", "scientific_society", "professional_association", "association_or_organization") or "association" in target_norm:
            if re.search(
                r"\b(?:sociedad|asociaci[oó]n|colegio|gremio|society|association)\b",
                candidate_name.lower(),
            ):
                return EntityArchetype.PROFESSIONAL_ASSOCIATION

        # 8. Commercial Enterprise
        if target_norm in ("construction", "industrial_distributor", "b2b_software", "restaurant") or re.search(
            r"\b(?:s\.?a\.?s\.?|s\.?a\.?|ltda\.?|inc\.?|corp\.?|llc|empresa|constructora|distribuidora|restaurant|restaurante|trattoria|bistro)\b",
            combined_text,
        ):
            return EntityArchetype.COMMERCIAL_ENTERPRISE

        return EntityArchetype.INDEPENDENT_ORGANIZATION

    def _determine_organization_website(
        self,
        archetype: EntityArchetype,
        parsed_url: urllib.parse.ParseResult,
        host: str,
    ) -> str:
        """Distinguish source URL evidence from authoritative organization website."""
        if archetype in (
            EntityArchetype.DIRECTORY_LISTING,
            EntityArchetype.HISTORICAL_REFERENCE,
            EntityArchetype.INTERNAL_PROGRAM,
            EntityArchetype.ARTICLE_OR_PUBLICATION,
            EntityArchetype.STUDENT_ORGANIZATION,
            EntityArchetype.UNKNOWN,
        ):
            return "UNKNOWN"

        if host in self.DIRECTORY_HOSTS or host in self.ARCHIVE_HOSTS:
            return "UNKNOWN"

        if not host:
            return "UNKNOWN"

        scheme = parsed_url.scheme or "https"
        return f"{scheme}://{host}"

    def _determine_geographic_status(
        self,
        combined_text: str,
        task: DiscoveryTask,
    ) -> GeographicEvidenceStatus:
        """Classify candidate geographic evidence truthfully without invented GPS."""
        city_req = (task.city or "").strip().lower()
        region_req = (task.region or "").strip().lower()
        country_req = (task.country or "CO").strip().upper()

        if city_req:
            # Check explicit local city mentions
            if re.search(r"\b" + re.escape(city_req) + r"\b", combined_text):
                return GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE

            # Check regional department/state
            regional_keyword = self.REGIONAL_CITY_MAP.get(city_req)
            if regional_keyword and re.search(r"\b" + re.escape(regional_keyword) + r"\b", combined_text):
                return GeographicEvidenceStatus.VERIFIED_REGIONAL_PRESENCE
            if region_req and re.search(r"\b" + re.escape(region_req) + r"\b", combined_text):
                return GeographicEvidenceStatus.VERIFIED_REGIONAL_PRESENCE

            # Check national scope
            if re.search(r"\b(?:colombiana|colombiano|de colombia|en colombia|nacional|national|united states|u\.s\.)\b", combined_text):
                return GeographicEvidenceStatus.NATIONAL_SCOPE

            # Check explicit mismatch with another major city
            disjoint_cities = [c for c in self.REGIONAL_CITY_MAP.keys() if c != city_req]
            for dc in disjoint_cities:
                if re.search(r"\b" + re.escape(dc) + r"\b", combined_text) and not re.search(r"\b" + re.escape(city_req) + r"\b", combined_text):
                    return GeographicEvidenceStatus.GEOGRAPHIC_MISMATCH

            return GeographicEvidenceStatus.LOCATION_UNVERIFIED

        # Nationwide or state-level task without specific city constraint
        if re.search(r"\b(?:colombiana|colombiano|de colombia|nacional|national|united states|u\.s\.)\b", combined_text):
            return GeographicEvidenceStatus.NATIONAL_SCOPE
        if region_req and re.search(r"\b" + re.escape(region_req) + r"\b", combined_text):
            return GeographicEvidenceStatus.VERIFIED_REGIONAL_PRESENCE

        return GeographicEvidenceStatus.LOCATION_UNVERIFIED

    def _determine_activity_status(
        self,
        host: str,
        archetype: EntityArchetype,
        combined_text: str,
    ) -> CurrentActivityStatus:
        """Classify operational freshness signals without declaring organizations defunct."""
        if host in self.ARCHIVE_HOSTS or archetype == EntityArchetype.HISTORICAL_REFERENCE:
            return CurrentActivityStatus.HISTORICAL_ACTIVITY_ONLY

        if re.search(r"\b(?:p[aá]gina inactiva|disuelta|liquidada|sitio hist[oó]rico \(19\d\d|199\d\b)\b", combined_text):
            return CurrentActivityStatus.HISTORICAL_ACTIVITY_ONLY

        # Freshness markers (current year range or active schedule)
        if re.search(r"\b(?:202[4-6]|actualizado|agenda 202[5-6]|congreso 202[5-6]|vigente|contacto directo)\b", combined_text):
            return CurrentActivityStatus.CURRENT_ACTIVITY_EVIDENCED

        return CurrentActivityStatus.CURRENT_STATUS_UNKNOWN

    def _check_archetype_compatibility(
        self, target_norm: str, archetype: EntityArchetype
    ) -> Tuple[bool, str]:
        """Validate whether entity archetype satisfies the target ICP intent."""
        is_assoc_target = (
            target_norm in ("medical_association", "scientific_society", "professional_association", "association_or_organization")
            or "association" in target_norm
        )

        if is_assoc_target:
            if archetype == EntityArchetype.INTERNAL_PROGRAM:
                return False, "INTERNAL_PROGRAM_NOT_ORGANIZATION"
            if archetype == EntityArchetype.STUDENT_ORGANIZATION:
                return False, "STUDENT_ORGANIZATION_EXCLUDED_FOR_PROFESSIONAL_TARGET"
            if archetype == EntityArchetype.ARTICLE_OR_PUBLICATION:
                return False, "ARTICLE_OR_PUBLICATION_NOT_ORGANIZATION"
            if archetype == EntityArchetype.DIRECTORY_LISTING:
                return False, "DIRECTORY_LISTING_NOT_ORGANIZATION"
            if archetype in (
                EntityArchetype.PROFESSIONAL_ASSOCIATION,
                EntityArchetype.FEDERATION,
                EntityArchetype.INDEPENDENT_ORGANIZATION,
            ):
                return True, ""
            return False, f"INCOMPATIBLE_ARCHETYPE ({archetype.value})"

        if target_norm in ("construction", "construction_company"):
            if archetype == EntityArchetype.INTERNAL_PROGRAM:
                return False, "EDUCATIONAL_PROGRAM_NOT_CONTRACTOR"
            if archetype == EntityArchetype.ARTICLE_OR_PUBLICATION:
                return False, "ARTICLE_NOT_CONTRACTOR"
            if archetype in (EntityArchetype.COMMERCIAL_ENTERPRISE, EntityArchetype.INDEPENDENT_ORGANIZATION):
                return True, ""
            return False, f"INCOMPATIBLE_ARCHETYPE ({archetype.value})"

        if target_norm in ("industrial_distributor", "wholesale_distributor"):
            if archetype == EntityArchetype.ARTICLE_OR_PUBLICATION:
                return False, "PRODUCT_CATALOG_NOT_DISTRIBUTOR"
            if archetype in (EntityArchetype.COMMERCIAL_ENTERPRISE, EntityArchetype.INDEPENDENT_ORGANIZATION):
                return True, ""
            return False, f"INCOMPATIBLE_ARCHETYPE ({archetype.value})"

        if target_norm in ("b2b_software", "software", "saas"):
            if archetype == EntityArchetype.STUDENT_ORGANIZATION:
                return False, "ACADEMIC_CLUB_NOT_B2B_COMPANY"
            if archetype in (EntityArchetype.COMMERCIAL_ENTERPRISE, EntityArchetype.INDEPENDENT_ORGANIZATION):
                return True, ""
            return False, f"INCOMPATIBLE_ARCHETYPE ({archetype.value})"

        if target_norm in ("restaurant", "restaurants"):
            if archetype == EntityArchetype.ARTICLE_OR_PUBLICATION:
                return False, "RECIPE_NOT_DINING_ESTABLISHMENT"
            if archetype in (EntityArchetype.COMMERCIAL_ENTERPRISE, EntityArchetype.INDEPENDENT_ORGANIZATION):
                return True, ""
            return False, f"INCOMPATIBLE_ARCHETYPE ({archetype.value})"

        # General-purpose default
        if archetype in (
            EntityArchetype.INTERNAL_PROGRAM,
            EntityArchetype.ARTICLE_OR_PUBLICATION,
            EntityArchetype.DIRECTORY_LISTING,
            EntityArchetype.HISTORICAL_REFERENCE,
        ):
            return False, f"CONTENT_OR_CATALOG_NOT_TARGET_ENTITY ({archetype.value})"

        return True, ""

    def _check_geographic_satisfaction(
        self, geo_status: GeographicEvidenceStatus, task: DiscoveryTask
    ) -> Tuple[bool, str]:
        """Validate whether geographic evidence satisfies task location policy."""
        city_req = (task.city or "").strip()
        allow_national = bool(task.metadata.get("allow_national", False))

        if city_req:
            if geo_status in (
                GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE,
                GeographicEvidenceStatus.VERIFIED_REGIONAL_PRESENCE,
            ):
                return True, ""

            if geo_status == GeographicEvidenceStatus.NATIONAL_SCOPE:
                if allow_national:
                    return True, ""
                return False, "LOCAL_PHYSICAL_PRESENCE_UNVERIFIED_FOR_NATIONAL_SCOPE"

            if geo_status == GeographicEvidenceStatus.GEOGRAPHIC_MISMATCH:
                return False, "GEOGRAPHIC_MISMATCH_WITH_TARGET_CITY"

            return False, "LOCATION_UNVERIFIED_FOR_TARGET_CITY"

        # Nationwide task (no city required)
        if geo_status in (
            GeographicEvidenceStatus.NATIONAL_SCOPE,
            GeographicEvidenceStatus.VERIFIED_LOCAL_PRESENCE,
            GeographicEvidenceStatus.VERIFIED_REGIONAL_PRESENCE,
        ):
            return True, ""

        return True, ""
