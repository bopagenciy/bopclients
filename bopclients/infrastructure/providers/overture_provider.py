"""Overture discovery provider implementing product-level IDiscoveryProvider via FORGE Gateway."""

from typing import List
from bopclients.domain.exceptions import DiscoveryProviderError
from bopclients.application.search_dto import DiscoveryTask
from bopclients.application.interfaces.search_interfaces import IDiscoveryProvider
from bopclients.application.interfaces.forge_gateways import (
    IForgeDiscoveryGateway,
    DiscoveryQuery,
    DiscoveredBusiness,
)


class OvertureDiscoveryProvider(IDiscoveryProvider):
    """Discovery provider using FORGE Overture Parquet engine adapter."""

    def __init__(self, discovery_gateway: IForgeDiscoveryGateway):
        self.discovery_gateway = discovery_gateway

    @property
    def name(self) -> str:
        return "overture"

    @property
    def capabilities(self) -> dict:
        return {
            "supports_postal_code_us": True,
            "supports_coordinates": True,
            "supports_country_only": False,
            "supports_international_city_without_coords": False,
        }

    def supports(self, task: DiscoveryTask) -> bool:
        return task.provider.lower() == "overture"

    def discover(self, task: DiscoveryTask) -> List[DiscoveredBusiness]:
        if not self.supports(task):
            raise DiscoveryProviderError(f"OvertureDiscoveryProvider does not support provider '{task.provider}'")

        try:
            query = DiscoveryQuery(
                zip_code=task.postal_code,
                city=task.city,
                state=task.region,
                latitude=task.latitude,
                longitude=task.longitude,
                radius_miles=task.radius_miles,
                industry=task.category,
                limit=task.limit,
            )
            return self.discovery_gateway.discover_businesses(query)
        except Exception as e:
            raise DiscoveryProviderError(f"Overture discovery execution failed for task '{task.id}': {e}") from e
