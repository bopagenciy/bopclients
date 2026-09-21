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
        "hospital": "hospital",
        "hospitales": "hospital",
        "consultorio": "medical_office",
        "consultorios": "medical_office",
        "consultorio médico": "medical_office",
        "consultorios médicos": "medical_office",
        "consultorio medico": "medical_office",
        "consultorios medicos": "medical_office",
        "medical office": "medical_office",
        "medical offices": "medical_office",
        "farmacia": "pharmacy",
        "farmacias": "pharmacy",
        "pharmacy": "pharmacy",
        "pharmacies": "pharmacy",
        "salud": "healthcare",
        # Medical Associations
        "asociación médica": "medical_association",
        "asociacion medica": "medical_association",
        "asociaciones médicas": "medical_association",
        "asociaciones medicas": "medical_association",
        "medical association": "medical_association",
        "medical associations": "medical_association",
        # Scientific Societies
        "sociedad científica": "scientific_society",
        "sociedad cientifica": "scientific_society",
        "sociedades científicas": "scientific_society",
        "sociedades cientificas": "scientific_society",
        "scientific society": "scientific_society",
        "scientific societies": "scientific_society",
        # Professional Associations / Gremios
        "colegio profesional": "professional_association",
        "colegios profesionales": "professional_association",
        "colegio médico": "professional_association",
        "colegios médicos": "professional_association",
        "colegio medico": "professional_association",
        "colegios medicos": "professional_association",
        "professional association": "professional_association",
        "professional associations": "professional_association",
        "organización gremial": "professional_association",
        "organizacion gremial": "professional_association",
        "organizaciones gremiales": "professional_association",
        "gremio": "professional_association",
        "gremios": "professional_association",
        # Non-profit
        "organización sin fines de lucro": "non_profit",
        "organizacion sin fines de lucro": "non_profit",
        "organizaciones sin fines de lucro": "non_profit",
        "health nonprofit": "non_profit",
        "health non-profit": "non_profit",
        "nonprofit": "non_profit",
        "non-profit": "non_profit",
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
