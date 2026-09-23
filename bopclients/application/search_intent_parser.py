"""Rule-based search intent parser implementation for Spanish and English prospecting prompts."""

import re
from typing import List, Optional, Dict, Any
from bopclients.domain.search_intent import SearchIntent
from bopclients.domain.normalizers import CategoryNormalizer, CountryNormalizer
from bopclients.application.interfaces.search_interfaces import ISearchIntentParser


class RuleBasedSearchIntentParser(ISearchIntentParser):
    """Deterministic rule-based intent parser recognizing cities, countries, categories, and services."""

    _KNOWN_CITIES = [
        "miami", "orlando", "new york", "los angeles",
        "cali", "bogotá", "bogota", "madrid", "barcelona"
    ]

    _KNOWN_COUNTRIES = {
        "estados unidos": "US", "usa": "US", "us": "US", "eeuu": "US",
        "colombia": "CO", "españa": "ES", "espana": "ES", "alemania": "DE",
        "canadá": "CA", "canada": "CA", "suiza": "CH", "argentina": "AR"
    }

    _KNOWN_REGIONS = {
        "florida": ("US", "FL"),
        "fl": ("US", "FL"),
        "new jersey": ("US", "NJ"),
        "nj": ("US", "NJ"),
        "california": ("US", "CA"),
        "ca": ("US", "CA"),
        "valle del cauca": ("CO", "VALLE"),
        "valle": ("CO", "VALLE"),
        "cundinamarca": ("CO", "CUNDINAMARCA"),
        "antioquia": ("CO", "ANTIOQUIA"),
    }

    _CATEGORY_KEYWORDS = {
        "dentist": "dentist", "dentists": "dentist", "dentista": "dentist", "dentistas": "dentist",
        "clínica dental": "dentist", "clinica dental": "dentist", "dental office": "dentist", "dental clinic": "dentist",
        "consultorio dental": "dentist", "odontología": "dentist", "odontologia": "dentist",
        # Lawyers
        "lawyer": "lawyer", "lawyers": "lawyer", "abogado": "lawyer", "abogados": "lawyer", "legal": "lawyer", "attorney": "lawyer",
        # Restaurants
        "restaurant": "restaurant", "restaurants": "restaurant", "restaurante": "restaurant", "restaurantes": "restaurant",
        # Marketing
        "agencia de marketing": "marketing", "agencias de marketing": "marketing", "marketing agency": "marketing", "marketing": "marketing",
        # Medical Associations
        "asociación médica": "medical_association", "asociacion medica": "medical_association",
        "asociaciones médicas": "medical_association", "asociaciones medicas": "medical_association",
        "medical association": "medical_association", "medical associations": "medical_association",
        # Scientific Societies
        "sociedad científica": "scientific_society", "sociedad cientifica": "scientific_society",
        "sociedades científicas": "scientific_society", "sociedades cientificas": "scientific_society",
        "scientific society": "scientific_society", "scientific societies": "scientific_society",
        # Professional Associations / Gremios
        "colegio profesional": "professional_association", "colegios profesionales": "professional_association",
        "colegio médico": "professional_association", "colegios médicos": "professional_association",
        "colegio medico": "professional_association", "colegios medicos": "professional_association",
        "professional association": "professional_association", "professional associations": "professional_association",
        "organización gremial": "professional_association", "organizacion gremial": "professional_association",
        "organizaciones gremiales": "professional_association",
        "gremio": "professional_association", "gremios": "professional_association",
        # Non-profit
        "organización sin fines de lucro": "non_profit", "organizacion sin fines de lucro": "non_profit",
        "organizaciones sin fines de lucro": "non_profit",
        "health nonprofit": "non_profit", "health non-profit": "non_profit",
        "nonprofit": "non_profit", "non-profit": "non_profit",
        # Clinics & Doctors
        "clínicas": "clinic", "clinicas": "clinic", "clínica": "clinic", "clinica": "clinic",
        "médicos": "clinic", "medicos": "clinic", "médico": "clinic", "medico": "clinic",
        "doctor": "clinic", "doctors": "clinic",
        # Hospitals
        "hospitales": "hospital", "hospital": "hospital", "hospitals": "hospital",
        # Medical Offices / Consultorios
        "consultorios médicos": "medical_office", "consultorios medicos": "medical_office",
        "consultorio médico": "medical_office", "consultorio medico": "medical_office",
        "consultorios": "medical_office", "consultorio": "medical_office",
        "medical office": "medical_office", "medical offices": "medical_office",
        # Pharmacies
        "farmacias": "pharmacy", "farmacia": "pharmacy", "pharmacies": "pharmacy", "pharmacy": "pharmacy",
        # Generic Health
        "servicios de salud": "healthcare", "sector salud": "healthcare", "salud": "healthcare",
        # Construction / General Contractors
        "construction company": "construction", "construction companies": "construction",
        "construction": "construction", "construcción": "construction", "construccion": "construction",
        "empresa de construcción": "construction", "empresas de construcción": "construction",
        "empresa de construccion": "construction", "empresas de construccion": "construction",
        "general contractor": "general_contractor", "general contractors": "general_contractor",
        "contratista general": "general_contractor", "contratistas generales": "general_contractor",
        "constructora": "construction", "constructoras": "construction",
        # Industrial Distribution / Supplies
        "industrial distributor": "industrial_distributor", "industrial distributors": "industrial_distributor",
        "distribuidor industrial": "industrial_distributor", "distribuidores industriales": "industrial_distributor",
        "distribución industrial": "industrial_distributor", "distribucion industrial": "industrial_distributor",
        "suministros industriales": "industrial_supplies", "industrial supplies": "industrial_supplies",
        "wholesale distributor": "wholesale_distributor", "distribuidor mayorista": "wholesale_distributor",
        # B2B Software / Technology
        "b2b software": "b2b_software", "software b2b": "b2b_software",
        "software company": "b2b_software", "software companies": "b2b_software",
        "empresa de software": "b2b_software", "empresas de software": "b2b_software",
        "software": "b2b_software", "saas": "b2b_software",
    }

    @staticmethod
    def _is_negated(text: str, match_start: int, match_end: int) -> bool:
        """Evaluate whether a matched category keyword falls within bounded negation scope."""
        preceding = text[:match_start]
        clauses = re.split(r'[\.;\n]', preceding)
        current_clause = clauses[-1]

        affirmative_patterns = [
            r'\b(?:pero|but|busco|buscar|quiero|queremos|encontrar|find|search\s+for|incluir|include)\b'
        ]
        exclusion_pattern = (
            r'\b(?:excluir|excluyendo|sin\s+incluir|exclude|excluding|excepto|except|sin|without|no|not|ni|nor)\b'
        )

        excl_matches = list(re.finditer(exclusion_pattern, current_clause, re.IGNORECASE))
        if not excl_matches:
            return False

        last_excl = excl_matches[-1]
        text_between = current_clause[last_excl.end():]
        for aff in affirmative_patterns:
            if re.search(aff, text_between, re.IGNORECASE):
                return False

        excl_word = last_excl.group(0).lower()
        words_between = text_between.strip().split()

        if excl_word in ('no', 'not', 'sin', 'without', 'ni', 'nor'):
            return len(words_between) <= 4

        if excl_word in ('excluir', 'excluyendo', 'sin incluir', 'exclude', 'excluding', 'excepto', 'except'):
            return True

        return False

    _SERVICE_KEYWORDS = {
        "marketing": "marketing",
        "diseño web": "web_development",
        "diseno web": "web_development",
        "web design": "web_development",
        "página web": "web_development",
        "pagina web": "web_development",
        "páginas web": "web_development",
        "paginas web": "web_development",
        "automatización": "automation",
        "automatizacion": "automation",
        "automation": "automation",
        "inteligencia artificial": "ai_solutions",
        "ia": "ai_solutions",
        "ai": "ai_solutions",
        "abogados": "legal_services",
    }

    def parse(
        self,
        organization_id: str,
        campaign_id: Optional[str],
        raw_query: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> SearchIntent:
        if not organization_id:
            raise ValueError("organization_id required")
        if not raw_query or not raw_query.strip():
            raise ValueError("raw_query cannot be empty")

        clean_query = raw_query.strip().lower()

        # Extract Categories with bounded negation scope and longest-match precedence
        sorted_kw = sorted(self._CATEGORY_KEYWORDS.items(), key=lambda x: len(x[0]), reverse=True)
        occupied_spans = set()
        matched_tokens = []

        for kw, cat in sorted_kw:
            for m in re.finditer(r'\b' + re.escape(kw) + r'\b', clean_query):
                span_range = range(m.start(), m.end())
                if any(idx in occupied_spans for idx in span_range):
                    continue
                for idx in span_range:
                    occupied_spans.add(idx)
                matched_tokens.append((m.start(), m.end(), kw, cat))

        # Preserve query order of appearance
        matched_tokens.sort(key=lambda x: x[0])

        positive_cats: List[str] = []
        negative_keywords: List[str] = []

        for start, end, kw, cat in matched_tokens:
            norm_cat = CategoryNormalizer.normalize(cat)
            if not norm_cat:
                continue
            if self._is_negated(clean_query, start, end):
                if norm_cat not in negative_keywords:
                    negative_keywords.append(norm_cat)
            else:
                if norm_cat not in positive_cats:
                    positive_cats.append(norm_cat)

        # Excluded categories must never be added as affirmative targets
        industries = [c for c in positive_cats if c not in negative_keywords]

        # Salud (generic healthcare) must not override or pollute specific association/medical categories
        if any(c in industries for c in ("medical_association", "scientific_society", "professional_association", "clinic")):
            industries = [c for c in industries if c != "healthcare"]

        # Extract Cities
        cities: List[str] = []
        for city in self._KNOWN_CITIES:
            if re.search(r'\b' + re.escape(city) + r'\b', clean_query):
                c_title = city.title()
                if c_title not in cities:
                    cities.append(c_title)

        # Extract Countries
        countries: List[str] = []
        for country_name, code in self._KNOWN_COUNTRIES.items():
            if re.search(r'\b' + re.escape(country_name) + r'\b', clean_query):
                if code not in countries:
                    countries.append(code)

        # Extract Regions / States
        regions: List[str] = []
        for reg_name, (cntry, reg_code) in self._KNOWN_REGIONS.items():
            if re.search(r'\b' + re.escape(reg_name) + r'\b', clean_query):
                if reg_name == "new york" and "New York" in cities:
                    continue
                if reg_code not in regions:
                    regions.append(reg_code)
                if cntry not in countries:
                    countries.append(cntry)

        # If cities found in known DB (e.g., Miami -> US), auto-infer country if not specified
        if cities and not countries:
            for city in cities:
                if city.lower() in ["miami", "orlando", "new york", "los angeles"]:
                    if "US" not in countries:
                        countries.append("US")
                elif city.lower() in ["cali", "bogotá", "bogota"]:
                    if "CO" not in countries:
                        countries.append("CO")
                elif city.lower() in ["madrid", "barcelona"]:
                    if "ES" not in countries:
                        countries.append("ES")

        # Extract Services Offered
        services: List[str] = []
        for kw, srv in self._SERVICE_KEYWORDS.items():
            if re.search(r'\b' + re.escape(kw) + r'\b', clean_query):
                if srv not in services:
                    services.append(srv)

        # Extract Desired Signals
        desired_signals: List[str] = []
        if "automatización" in clean_query or "automatizacion" in clean_query or "automation" in clean_query:
            desired_signals.append("no_automation")
        if "página web" in clean_query or "pagina web" in clean_query or "diseño" in clean_query or "web design" in clean_query:
            desired_signals.append("old_website")

        # Extract Company Size (e.g., "10 a 100 empleados" or "10 to 100 employees")
        company_min, company_max = None, None
        size_match = re.search(r'(\d+)\s*(?:a|to|-)\s*(\d+)\s*(?:empleados|employees)', clean_query)
        if size_match:
            company_min = int(size_match.group(1))
            company_max = int(size_match.group(2))

        # Extract Languages (e.g., "español", "spanish")
        languages: List[str] = []
        if "español" in clean_query or "espanol" in clean_query or "spanish" in clean_query:
            languages.append("es")
        if "inglés" in clean_query or "ingles" in clean_query or "english" in clean_query:
            languages.append("en")

        intent = SearchIntent(
            organization_id=organization_id,
            campaign_id=campaign_id,
            raw_query=raw_query,
            target_entity_type="business",
            industries=industries,
            business_categories=industries,
            countries=countries if countries else ["US"],
            regions=regions,
            cities=cities,
            languages=languages,
            company_size_min=company_min,
            company_size_max=company_max,
            negative_keywords=negative_keywords,
            services_to_offer=services,
            desired_signals=desired_signals,
            max_results=100,
        )
        intent.validate()
        return intent
