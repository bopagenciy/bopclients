"""Static geographical location resolver implementation for known cities and regions."""

from typing import Dict, Optional, Tuple
from bopclients.domain.normalizers import CountryNormalizer
from bopclients.application.search_dto import ResolvedLocation
from bopclients.application.interfaces.search_interfaces import ILocationResolver


class StaticLocationResolver(ILocationResolver):
    """Deterministic location resolver matching known test and production cities."""

    # Map (country_code, city_lowercase) -> (region_code, postal_code, lat, lon)
    _KNOWN_CITIES: Dict[Tuple[str, str], Tuple[Optional[str], Optional[str], Optional[float], Optional[float]]] = {
        ("US", "miami"): ("FL", "33101", 25.7617, -80.1918),
        ("US", "orlando"): ("FL", "32801", 28.5383, -81.3792),
        ("US", "new york"): ("NY", "10001", 40.7128, -74.0060),
        ("US", "los angeles"): ("CA", "90001", 34.0522, -118.2437),
        ("CO", "cali"): ("VALLE", "760001", 3.4516, -76.5320),
        ("CO", "bogota"): ("CUNDINAMARCA", "110111", 4.7110, -74.0721),
        ("CO", "bogotá"): ("CUNDINAMARCA", "110111", 4.7110, -74.0721),
        ("ES", "madrid"): ("MADRID", "28001", 40.4168, -3.7038),
        ("ES", "barcelona"): ("CATALUNYA", "08001", 41.3851, 2.1734),
    }

    def resolve(
        self,
        country: str,
        region: Optional[str] = None,
        city: Optional[str] = None,
        postal_code: Optional[str] = None,
    ) -> Optional[ResolvedLocation]:
        norm_country = CountryNormalizer.normalize(country)

        # If postal code provided directly
        if postal_code:
            return ResolvedLocation(
                country_code=norm_country,
                region_code=region.upper() if region else None,
                city=city.title() if city else None,
                postal_code=postal_code,
            )

        # If city provided, look up in known database
        if city:
            clean_city = city.strip().lower()
            key = (norm_country, clean_city)
            if key in self._KNOWN_CITIES:
                reg, zip_code, lat, lon = self._KNOWN_CITIES[key]
                return ResolvedLocation(
                    country_code=norm_country,
                    region_code=reg or (region.upper() if region else None),
                    city=city.title(),
                    postal_code=zip_code,
                    latitude=lat,
                    longitude=lon,
                )

        # Fallback for country/region without city postal code resolution
        return ResolvedLocation(
            country_code=norm_country,
            region_code=region.upper() if region else None,
            city=city.title() if city else None,
            postal_code=None,
        )
