"""FORGE Adapter Gateways connecting BopClients product layer to FORGE engine."""

import logging
from typing import List, Dict, Any, Optional
from bopclients.application.interfaces.forge_gateways import (
    IForgeDiscoveryGateway,
    IForgeEnrichmentGateway,
    DiscoveryQuery,
    DiscoveredBusiness,
    EnrichmentTask,
)
from forge.discovery.overture import OvertureDiscovery
from forge.enrichment.pipeline import EnrichmentPipeline

logger = logging.getLogger("bopclients.gateways.forge")


class ForgeDiscoveryGatewayAdapter(IForgeDiscoveryGateway):
    """Adapter wrapping FORGE OvertureDiscovery engine."""

    def __init__(self, overture_discovery: Optional[OvertureDiscovery] = None):
        self._discovery = overture_discovery or OvertureDiscovery()

    def discover_businesses(self, query: DiscoveryQuery) -> List[DiscoveredBusiness]:
        """Discover business targets using FORGE OvertureDiscovery engine."""
        logger.info("BopClients Gateway -> Querying FORGE discovery engine (zip=%s, city=%s, industry=%s)",
                    query.zip_code, query.city, query.industry)

        raw_results = self._discovery.search(
            zip_code=query.zip_code,
            city=query.city,
            state=query.state,
            latitude=query.latitude,
            longitude=query.longitude,
            radius_miles=query.radius_miles,
            industry=query.industry,
            limit=query.limit,
        )

        discovered: List[DiscoveredBusiness] = []
        for item in raw_results:
            discovered.append(
                DiscoveredBusiness(
                    overture_id=item.get("overture_id") or item.get("id", ""),
                    name=item.get("name", "Unknown Business"),
                    address=item.get("address"),
                    city=item.get("city"),
                    state=item.get("state"),
                    zip_code=item.get("zip"),
                    latitude=item.get("lat"),
                    longitude=item.get("lon"),
                    phone=item.get("phone"),
                    website_url=item.get("website_url") or item.get("website"),
                    category=item.get("category"),
                    forge_industry=item.get("forge_industry"),
                    raw_data=item,
                )
            )
        return discovered


class ForgeEnrichmentGatewayAdapter(IForgeEnrichmentGateway):
    """Adapter wrapping FORGE EnrichmentPipeline engine."""

    def __init__(self, db_pool: Any):
        self.db_pool = db_pool

    def enrich_batch(self, task: EnrichmentTask) -> List[Dict[str, Any]]:
        """Enrich a batch of prospects using FORGE EnrichmentPipeline."""
        logger.info("BopClients Gateway -> Starting FORGE enrichment batch (%d records, mode=%s)",
                    len(task.business_records), task.mode)

        # Upsert businesses into FORGE DB first
        for record in task.business_records:
            self.db_pool.upsert_business(record)

        pipeline = EnrichmentPipeline(
            db_pool=self.db_pool,
            web_scraper_workers=task.workers,
        )
        stats = pipeline.run(mode=task.mode, max_records=len(task.business_records))
        logger.info("FORGE enrichment complete: %s", stats.summary())

        # Return updated business records from FORGE DB
        return self.db_pool.fetch_dicts("SELECT * FROM businesses ORDER BY last_enriched_at DESC LIMIT %s", (len(task.business_records),))
