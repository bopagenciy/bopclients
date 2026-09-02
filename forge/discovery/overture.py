"""
Overture Maps discovery client for FORGE.

Queries the Overture Maps places dataset (free, open GeoParquet on S3)
via DuckDB to discover businesses by location and industry.

Usage:
    from discovery.overture import OvertureDiscovery

    disco = OvertureDiscovery()
    results = disco.search(zip_code="33602", industry="restaurant", limit=500)
    disco.close()
"""

from __future__ import annotations

import logging
import re
import time
from typing import List, Optional, Tuple

from forge.discovery.zip_centroids import get_zip_centroid

logger = logging.getLogger(__name__)

# Overture Maps S3 default release path (can be overridden by FORGE_OVERTURE_RELEASE env var)
DEFAULT_OVERTURE_RELEASE = "2026-08-19.0"
OVERTURE_PLACES_PATH_TEMPLATE = "s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*"

# Approximate conversion: 1 mile ~ 0.0145 degrees at mid-latitudes
MILES_TO_DEGREES = 0.0145

# Maximum query time in seconds
QUERY_TIMEOUT_SECONDS = 60


def get_overture_places_path() -> str:
    """Resolve the Overture Maps S3 places path."""
    import os

    release = os.getenv("FORGE_OVERTURE_RELEASE", os.getenv("OVERTURE_RELEASE", DEFAULT_OVERTURE_RELEASE)).strip()
    return OVERTURE_PLACES_PATH_TEMPLATE.format(release=release)


# Map Overture primary categories -> FORGE industry slugs
_CATEGORY_TO_INDUSTRY: dict[str, str] = {
    # Food & Drink
    "restaurant": "restaurant",
    "fast_food_restaurant": "restaurant",
    "bar": "bar",
    "pub": "bar",
    "cafe": "cafe",
    "coffee_shop": "cafe",
    "bakery": "bakery",
    "pizza_restaurant": "restaurant",
    "ice_cream_shop": "restaurant",
    "food_court": "restaurant",
    # Retail
    "clothing_store": "retail",
    "shoe_store": "retail",
    "jewelry_store": "retail",
    "department_store": "retail",
    "shopping_mall": "retail",
    "convenience_store": "retail",
    "grocery_store": "grocery",
    "supermarket": "grocery",
    "discount_store": "retail",
    "electronics_store": "retail",
    "furniture_store": "retail",
    "hardware_store": "retail",
    "pet_store": "retail",
    "bookstore": "retail",
    "toy_store": "retail",
    # Health & Medical
    "doctor": "healthcare",
    "dentist": "healthcare",
    "hospital": "healthcare",
    "pharmacy": "healthcare",
    "optician": "healthcare",
    "veterinarian": "veterinary",
    "physiotherapist": "healthcare",
    "chiropractor": "healthcare",
    # Professional Services
    "lawyer": "legal",
    "accountant": "accounting",
    "insurance_agency": "insurance",
    "real_estate_agency": "real_estate",
    "bank": "finance",
    "financial_advisor": "finance",
    # Automotive
    "car_dealer": "automotive",
    "car_repair": "automotive",
    "car_wash": "automotive",
    "gas_station": "automotive",
    # Beauty & Personal Care
    "hair_salon": "beauty",
    "beauty_salon": "beauty",
    "spa": "beauty",
    "nail_salon": "beauty",
    "barber_shop": "beauty",
    # Fitness & Recreation
    "gym": "fitness",
    "fitness_center": "fitness",
    "yoga_studio": "fitness",
    "sports_club": "fitness",
    # Accommodation
    "hotel": "hospitality",
    "motel": "hospitality",
    "bed_and_breakfast": "hospitality",
    "resort": "hospitality",
    # Home Services
    "plumber": "home_services",
    "electrician": "home_services",
    "locksmith": "home_services",
    "moving_company": "home_services",
    "storage_facility": "home_services",
    # Education
    "school": "education",
    "university": "education",
    "tutoring_service": "education",
    "driving_school": "education",
    # Entertainment
    "movie_theater": "entertainment",
    "night_club": "entertainment",
    "bowling_alley": "entertainment",
    "amusement_park": "entertainment",
}

# Reverse lookup: FORGE industry -> list of Overture categories
_INDUSTRY_TO_CATEGORIES: dict[str, list[str]] = {}
for _cat, _ind in _CATEGORY_TO_INDUSTRY.items():
    _INDUSTRY_TO_CATEGORIES.setdefault(_ind, []).append(_cat)


class OvertureDiscoveryError(Exception):
    """Base error for Overture discovery issues."""


class OvertureDiscovery:
    """
    Discovers businesses from the Overture Maps open dataset via DuckDB.

    DuckDB queries remote GeoParquet files on S3 directly -- no bulk download
    required. First queries may be slow while DuckDB fetches Parquet metadata.
    """

    def __init__(self, release_path: Optional[str] = None):
        """Initialize DuckDB with spatial and httpfs extensions."""
        try:
            import duckdb
        except ImportError:
            raise OvertureDiscoveryError(
                "DuckDB is required for Overture Maps discovery. "
                "Install it with: pip install duckdb"
            )

        self._places_path = release_path or get_overture_places_path()
        self._conn = duckdb.connect(database=":memory:")
        self._setup_extensions()

    def _setup_extensions(self):
        """Install and load required DuckDB extensions."""
        logger.info("Setting up DuckDB extensions (httpfs, spatial)...")
        try:
            self._conn.execute("INSTALL httpfs; LOAD httpfs;")
            self._conn.execute("INSTALL spatial; LOAD spatial;")
            self._conn.execute("SET s3_region='us-west-2';")
            # Anonymous access -- Overture data is public
            self._conn.execute("SET s3_access_key_id='';")
            self._conn.execute("SET s3_secret_access_key='';")
        except Exception as exc:  # Catch-and-reraise: wrap in domain-specific error
            raise OvertureDiscoveryError(
                f"Failed to initialize DuckDB extensions: {exc}. Check your internet connection."
            )
        logger.info("DuckDB extensions ready.")

    def geocode_zip(self, zip_code: str) -> Tuple[float, float]:
        """
        Convert a US ZIP code to (latitude, longitude).

        Uses the bundled centroid database for fast lookup.

        Args:
            zip_code: 5-digit US ZIP code.

        Returns:
            Tuple of (latitude, longitude).

        Raises:
            OvertureDiscoveryError: If the ZIP code is unknown.
        """
        result = get_zip_centroid(zip_code)
        if result is None:
            raise OvertureDiscoveryError(
                f"ZIP code not found in database: {zip_code}. "
                "Try providing latitude/longitude directly."
            )
        return result["lat"], result["lon"]

    def _resolve_location(
        self,
        zip_code: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
    ) -> tuple:
        """Resolve search inputs to (lat, lon) coordinates."""
        if latitude is not None and longitude is not None:
            return latitude, longitude
        elif zip_code:
            lat, lon = self.geocode_zip(zip_code)
            logger.info("Geocoded ZIP %s -> (%.4f, %.4f)", zip_code, lat, lon)
            return lat, lon
        else:
            raise OvertureDiscoveryError("Provide either zip_code or (latitude, longitude).")

    def _inspect_columns(self, places_path: str) -> set[str]:
        """Inspect available physical column names in the Parquet file."""
        try:
            res = self._conn.execute(
                f"SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet('{places_path}', filename=true, hive_partitioning=1) LIMIT 0)"
            ).fetchall()
            return {r[0].lower() for r in res}
        except Exception as e:
            logger.debug("Failed to inspect Parquet columns: %s", e)
            return {"categories", "bbox", "geometry", "names", "addresses", "phones", "websites"}

    @staticmethod
    def _detect_category_sql(cols: set[str], industry: Optional[str]) -> tuple[str, str]:
        """Dynamically build SELECT category projection and WHERE filter based on physical columns.

        Returns (select_expr, category_filter_clause).
        """
        has_categories = "categories" in cols
        has_taxonomy = "taxonomy" in cols
        has_basic = "basic_category" in cols

        # Select projection
        if has_categories and has_taxonomy:
            select_expr = "COALESCE(categories.primary, taxonomy.primary) AS category"
        elif has_categories:
            select_expr = "categories.primary AS category"
        elif has_taxonomy:
            select_expr = "taxonomy.primary AS category"
        elif has_basic:
            select_expr = "basic_category AS category"
        else:
            select_expr = "NULL AS category"

        if not industry:
            return select_expr, ""

        if industry.lower() in _INDUSTRY_TO_CATEGORIES:
            cats = _INDUSTRY_TO_CATEGORIES[industry.lower()]
            cat_list = ", ".join(f"'{c}'" for c in cats)
            logger.info("Filtering to industry '%s' -> categories: %s", industry, cats)
            if has_categories:
                filter_clause = (
                    f"AND (categories.primary IN ({cat_list}) "
                    f"OR list_has_any(categories.alternate, [{cat_list}]))"
                )
            elif has_taxonomy:
                filter_clause = (
                    f"AND (taxonomy.primary IN ({cat_list}) "
                    f"OR list_has_any(taxonomy.alternates, [{cat_list}]))"
                )
            elif has_basic:
                filter_clause = f"AND basic_category IN ({cat_list})"
            else:
                filter_clause = ""
            return select_expr, filter_clause

        safe_industry = re.sub(r"[^a-zA-Z0-9_\-\s]", "", industry.lower().strip())
        if not safe_industry:
            logger.warning("Industry '%s' rejected, invalid characters.", industry)
            return select_expr, ""

        logger.info(
            "Industry '%s' has no mapping; filtering raw category (sanitized: '%s').",
            industry,
            safe_industry,
        )
        if has_categories:
            filter_clause = (
                f"AND (LOWER(COALESCE(categories.primary, '')) = '{safe_industry}' "
                f"OR list_has_any(categories.alternate, ['{safe_industry}']))"
            )
        elif has_taxonomy:
            filter_clause = (
                f"AND (LOWER(COALESCE(taxonomy.primary, '')) = '{safe_industry}' "
                f"OR list_has_any(taxonomy.alternates, ['{safe_industry}']))"
            )
        elif has_basic:
            filter_clause = f"AND LOWER(COALESCE(basic_category, '')) = '{safe_industry}'"
        else:
            filter_clause = ""

        return select_expr, filter_clause

    def _build_overture_sql(
        self,
        min_lat: float,
        max_lat: float,
        min_lon: float,
        max_lon: float,
        industry: Optional[str],
        limit: int,
        places_path: Optional[str] = None,
        cols: Optional[set[str]] = None,
    ) -> str:
        """Build the DuckDB SQL query for Overture Maps using Parquet bbox predicate pushdown."""
        path = places_path or (self._places_path if self else get_overture_places_path())
        available_cols = cols or (self._inspect_columns(path) if self else {"categories", "bbox", "geometry"})

        cat_projection, cat_filter = OvertureDiscovery._detect_category_sql(available_cols, industry)

        has_bbox = "bbox" in available_cols
        if has_bbox:
            geom_where = (
                f"bbox.xmin <= {max_lon} AND bbox.xmax >= {min_lon} "
                f"AND bbox.ymin <= {max_lat} AND bbox.ymax >= {min_lat}"
            )
            lat_expr = "COALESCE(bbox.ymin, ST_Y(geometry))"
            lon_expr = "COALESCE(bbox.xmin, ST_X(geometry))"
        else:
            geom_where = (
                f"ST_Y(geometry) BETWEEN {min_lat} AND {max_lat} "
                f"AND ST_X(geometry) BETWEEN {min_lon} AND {max_lon}"
            )
            lat_expr = "ST_Y(geometry)"
            lon_expr = "ST_X(geometry)"

        return f"""
        SELECT
            id                                          AS overture_id,
            names.primary                               AS name,
            addresses[1].freeform                       AS address,
            addresses[1].locality                       AS city,
            addresses[1].region                         AS state,
            addresses[1].postcode                       AS zip,
            {lat_expr}                                  AS lat,
            {lon_expr}                                  AS lon,
            CASE WHEN phones IS NOT NULL AND len(phones) > 0
                 THEN phones[1] ELSE NULL END           AS phone,
            CASE WHEN websites IS NOT NULL AND len(websites) > 0
                 THEN websites[1] ELSE NULL END         AS website_url,
            {cat_projection}
        FROM read_parquet('{path}', filename=true, hive_partitioning=1)
        WHERE
            {geom_where}
            {cat_filter}
        LIMIT {limit}
        """

    def _execute_query(self, sql: str, label: str) -> tuple:
        """Execute a DuckDB query and return (rows, columns).

        Raises OvertureDiscoveryError on timeout or connection failure.
        """
        start = time.time()
        try:
            result = self._conn.execute(sql)
            rows = result.fetchall()
            columns = [desc[0] for desc in result.description]
        except Exception as exc:  # Catch-and-reraise: wrap in domain-specific error with context
            elapsed = time.time() - start
            err_str = str(exc).lower()
            if elapsed >= QUERY_TIMEOUT_SECONDS or "timeout" in err_str:
                raise OvertureDiscoveryError(
                    f"Query timed out after {elapsed:.0f}s. Try a smaller radius or more specific industry."
                )
            if "unable to connect" in err_str or "http" in err_str or "404" in err_str or "403" in err_str:
                raise OvertureDiscoveryError(
                    f"Could not reach or read Overture Maps release at {self._places_path}: {exc}. "
                    "Check network connection or specify a valid release via FORGE_OVERTURE_RELEASE."
                )
            raise OvertureDiscoveryError(f"DuckDB query failed: {exc}")

        elapsed = time.time() - start
        logger.info("Overture query returned %d rows in %.1fs", len(rows), elapsed)
        return rows, columns

    @staticmethod
    def _format_results(rows: list, columns: list) -> List[dict]:
        """Convert raw DuckDB rows to dicts with forge_industry mapping and website key alias."""
        results: List[dict] = []
        for row in rows:
            record = dict(zip(columns, row))
            raw_cat = record.get("category") or ""
            record["forge_industry"] = _CATEGORY_TO_INDUSTRY.get(raw_cat.lower())
            # Ensure backwards compatibility: populate both website_url and website
            website_val = record.get("website_url") or record.get("website")
            record["website_url"] = website_val
            record["website"] = website_val
            results.append(record)
        return results

    def search(
        self,
        zip_code: Optional[str] = None,
        city: Optional[str] = None,
        state: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius_miles: float = 10,
        industry: Optional[str] = None,
        limit: int = 1000,
    ) -> List[dict]:
        """Search Overture Maps for businesses near a location.

        Provide EITHER zip_code OR (latitude, longitude).
        """
        lat, lon = self._resolve_location(zip_code, latitude, longitude)

        delta = radius_miles * MILES_TO_DEGREES

        sql = self._build_overture_sql(
            lat - delta, lat + delta, lon - delta, lon + delta, industry, limit
        )

        label = f"({lat:.4f}, {lon:.4f}) r={radius_miles}mi"
        if industry:
            label += f" industry={industry}"
        logger.info("Querying Overture Maps: %s ...", label)

        rows, columns = self._execute_query(sql, label)
        if not rows:
            logger.warning("No businesses found matching criteria: %s", label)
            return []

        return self._format_results(rows, columns)

    def close(self):
        """Close the DuckDB connection and release resources."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:  # Non-critical: best-effort cleanup on close
                pass
            self._conn = None
            logger.info("DuckDB connection closed.")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        self.close()
