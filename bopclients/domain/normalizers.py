"""Category and Country normalizers for BopClients Search Intent."""

from typing import Dict, List, Optional


class CategoryNormalizer:
    """Normalizes natural language business categories/industries into canonical taxonomy keys."""

    _MAPPINGS: Dict[str, str] = {
        # Dentists
        "dentist": "dentist",
        "dentistas": "dentist",
        "dentista": "dentist",
        "dental clinic": "dentist",
        "clínica dental": "dentist",
        "clinica dental": "dentist",
        "dental office": "dentist",
        "consultorio dental": "dentist",
        "odontología": "dentist",
        "odontologia": "dentist",
        "odontólogo": "dentist",
        "odontologo": "dentist",
        # Lawyers / Legal
        "lawyer": "lawyer",
        "abogado": "lawyer",
        "abogados": "lawyer",
        "attorney": "lawyer",
        "law firm": "lawyer",
        "firmas de abogados": "lawyer",
        "bufete de abogados": "lawyer",
        "legal": "lawyer",
        "servicios legales": "lawyer",
        # Restaurants
        "restaurant": "restaurant",
        "restaurante": "restaurant",
        "restaurantes": "restaurant",
        "food": "restaurant",
        "comida": "restaurant",
        # Marketing Agencies
        "marketing": "marketing",
        "marketing agency": "marketing",
        "agencia de marketing": "marketing",
        "agencias de marketing": "marketing",
        "diseño web": "marketing",
        "web design": "marketing",
        "publicidad": "marketing",
        # Healthcare / Clinics
        "clinic": "clinic",
        "clínica": "clinic",
        "clinica": "clinic",
        "clínicas": "clinic",
        "clinicas": "clinic",
        "doctor": "clinic",
        "médico": "clinic",
        "medico": "clinic",
        "salud": "clinic",
    }

    @classmethod
    def normalize(cls, raw_category: str) -> str:
        """Return canonical category key or lowercase stripped fallback."""
        if not raw_category:
            return ""
        clean = raw_category.strip().lower()
        return cls._MAPPINGS.get(clean, clean)


class CountryNormalizer:
    """Normalizes natural language country names and codes into ISO-3166-1 alpha-2 codes."""

    _MAPPINGS: Dict[str, str] = {
        "united states": "US",
        "usa": "US",
        "us": "US",
        "eeuu": "US",
        "ee.uu.": "US",
        "estados unidos": "US",
        "colombia": "CO",
        "co": "CO",
        "spain": "ES",
        "españa": "ES",
        "espana": "ES",
        "es": "ES",
        "germany": "DE",
        "alemania": "DE",
        "de": "DE",
        "canada": "CA",
        "canadá": "CA",
        "ca": "CA",
        "switzerland": "CH",
        "suiza": "CH",
        "ch": "CH",
        "argentina": "AR",
        "ar": "AR",
        "mexico": "MX",
        "méxico": "MX",
        "mx": "MX",
    }

    @classmethod
    def normalize(cls, raw_country: str) -> str:
        """Return 2-letter ISO country code or uppercase fallback."""
        if not raw_country:
            return "US"
        clean = raw_country.strip().lower()
        return cls._MAPPINGS.get(clean, raw_country.strip().upper()[:2])
