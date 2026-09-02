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

    _CATEGORY_KEYWORDS = {
        "dentist": "dentist", "dentists": "dentist", "dentista": "dentist", "dentistas": "dentist",
        "clínica dental": "dentist", "clinica dental": "dentist", "dental office": "dentist", "dental clinic": "dentist",
        "lawyer": "lawyer", "lawyers": "lawyer", "abogado": "lawyer", "abogados": "lawyer", "legal": "lawyer", "attorney": "lawyer",
        "restaurant": "restaurant", "restaurants": "restaurant", "restaurante": "restaurant", "restaurantes": "restaurant",
        "agencia de marketing": "marketing", "marketing agency": "marketing", "marketing": "marketing",
        "clínicas": "clinic", "clinicas": "clinic", "clínica": "clinic", "clinica": "clinic", "médicos": "clinic", "medicos": "clinic"
    }

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

        # Extract Categories
        industries: List[str] = []
        for kw, cat in self._CATEGORY_KEYWORDS.items():
            if re.search(r'\b' + re.escape(kw) + r'\b', clean_query):
                norm_cat = CategoryNormalizer.normalize(cat)
                if norm_cat and norm_cat not in industries:
                    industries.append(norm_cat)

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
            cities=cities,
            languages=languages,
            company_size_min=company_min,
            company_size_max=company_max,
            services_to_offer=services,
            desired_signals=desired_signals,
            max_results=100,
        )
        intent.validate()
        return intent
