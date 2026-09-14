"""Database repository for tenant-safe integration destinations and subscriptions."""

from datetime import datetime, timezone
from typing import List, Optional, Any, Tuple
import json

from bopclients.domain.integration.destination import (
    IntegrationDestination,
    IntegrationSubscription,
    DestinationTransportType,
)
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class IntegrationDestinationRepository(BaseTenantRepository):
    """Repository managing outbound integration destinations and subscriptions per tenant."""

    @classmethod
    def _row_to_destination(cls, r: dict) -> IntegrationDestination:
        return IntegrationDestination(
            id=r["id"],
            bop_organization_id=r["bop_organization_id"],
            target_app_id=r["target_app_id"],
            destination_name=r["destination_name"],
            transport_type=r.get("transport_type", DestinationTransportType.HTTP.value),
            endpoint_url=r["endpoint_url"],
            secret_key_ref=r.get("secret_key_ref"),
            headers_template_json=r.get("headers_template_json"),
            is_active=bool(r.get("is_active", True)),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )

    @classmethod
    def _row_to_subscription(cls, r: dict) -> IntegrationSubscription:
        return IntegrationSubscription(
            id=r["id"],
            bop_organization_id=r["bop_organization_id"],
            destination_id=r["destination_id"],
            event_type=r["event_type"],
            is_active=bool(r.get("is_active", True)),
            created_at=r["created_at"],
        )

    # ---------------- Destination CRUD ----------------

    def create_destination(
        self,
        destination: IntegrationDestination,
        commit: bool = True,
    ) -> IntegrationDestination:
        """Persist a new integration destination scoped to its tenant."""
        self._validate_tenant(destination.bop_organization_id)
        p = self._placeholder()
        sql = f"""
            INSERT INTO bop_integration_destinations (
                id, bop_organization_id, target_app_id, destination_name,
                transport_type, endpoint_url, secret_key_ref,
                headers_template_json, is_active, created_at, updated_at
            ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        self.db.execute(
            sql,
            (
                destination.id,
                destination.bop_organization_id,
                destination.target_app_id,
                destination.destination_name,
                destination.transport_type,
                destination.endpoint_url,
                destination.secret_key_ref,
                destination.headers_template_json,
                destination.is_active,
                destination.created_at,
                destination.updated_at,
            ),
        )
        if commit:
            self._commit_if_not_in_tx()
        return destination

    def get_destination(self, destination_id: str, bop_organization_id: Optional[str] = None) -> Optional[IntegrationDestination]:
        """Fetch destination by ID, optionally validating tenant ownership."""
        p = self._placeholder()
        if bop_organization_id:
            sql = f"SELECT * FROM bop_integration_destinations WHERE id = {p} AND bop_organization_id = {p}"
            rows = self.db.fetch_dicts(sql, (destination_id, bop_organization_id))
        else:
            sql = f"SELECT * FROM bop_integration_destinations WHERE id = {p}"
            rows = self.db.fetch_dicts(sql, (destination_id,))
        if not rows:
            return None
        return self._row_to_destination(rows[0])

    def list_destinations(
        self,
        bop_organization_id: str,
        only_active: bool = True,
    ) -> List[IntegrationDestination]:
        """List destinations for a tenant."""
        self._validate_tenant(bop_organization_id)
        p = self._placeholder()
        if only_active:
            sql = f"""
                SELECT * FROM bop_integration_destinations
                WHERE bop_organization_id = {p} AND is_active = true
                ORDER BY created_at ASC
            """
            rows = self.db.fetch_dicts(sql, (bop_organization_id,))
        else:
            sql = f"""
                SELECT * FROM bop_integration_destinations
                WHERE bop_organization_id = {p}
                ORDER BY created_at ASC
            """
            rows = self.db.fetch_dicts(sql, (bop_organization_id,))
        return [self._row_to_destination(r) for r in rows]

    def set_destination_active(
        self,
        destination_id: str,
        bop_organization_id: str,
        is_active: bool,
        commit: bool = True,
    ) -> bool:
        """Enable or disable a destination."""
        self._validate_tenant(bop_organization_id)
        p = self._placeholder()
        now_iso = datetime.now(timezone.utc).isoformat()
        sql = f"""
            UPDATE bop_integration_destinations
            SET is_active = {p}, updated_at = {p}
            WHERE id = {p} AND bop_organization_id = {p}
        """
        count = self._execute_rowcount(sql, (is_active, now_iso, destination_id, bop_organization_id))
        if commit:
            self._commit_if_not_in_tx()
        return count > 0

    # ---------------- Subscription CRUD ----------------

    def create_subscription(
        self,
        subscription: IntegrationSubscription,
        commit: bool = True,
    ) -> IntegrationSubscription:
        """Persist a new subscription mapping event_type to a destination."""
        self._validate_tenant(subscription.bop_organization_id)
        # Invariant: destination must belong to same tenant
        dest = self.get_destination(subscription.destination_id, subscription.bop_organization_id)
        if not dest:
            raise ValueError(
                f"Cannot subscribe to destination '{subscription.destination_id}': "
                f"destination does not exist or does not belong to tenant '{subscription.bop_organization_id}'"
            )

        p = self._placeholder()
        sql = f"""
            INSERT INTO bop_integration_subscriptions (
                id, bop_organization_id, destination_id, event_type, is_active, created_at
            ) VALUES ({p}, {p}, {p}, {p}, {p}, {p})
        """
        self.db.execute(
            sql,
            (
                subscription.id,
                subscription.bop_organization_id,
                subscription.destination_id,
                subscription.event_type,
                subscription.is_active,
                subscription.created_at,
            ),
        )
        if commit:
            self._commit_if_not_in_tx()
        return subscription

    def list_subscriptions(
        self,
        bop_organization_id: str,
        only_active: bool = True,
    ) -> List[IntegrationSubscription]:
        """List subscriptions for a tenant."""
        self._validate_tenant(bop_organization_id)
        p = self._placeholder()
        if only_active:
            sql = f"""
                SELECT * FROM bop_integration_subscriptions
                WHERE bop_organization_id = {p} AND is_active = true
                ORDER BY created_at ASC
            """
            rows = self.db.fetch_dicts(sql, (bop_organization_id,))
        else:
            sql = f"""
                SELECT * FROM bop_integration_subscriptions
                WHERE bop_organization_id = {p}
                ORDER BY created_at ASC
            """
            rows = self.db.fetch_dicts(sql, (bop_organization_id,))
        return [self._row_to_subscription(r) for r in rows]

    def get_destinations_for_event(
        self,
        bop_organization_id: str,
        event_type: str,
    ) -> List[IntegrationDestination]:
        """Find all active destinations subscribed to an event type (exact match or wildcard '*').

        Strictly enforces tenant isolation: both destination and subscription must belong to bop_organization_id.
        """
        self._validate_tenant(bop_organization_id)
        p = self._placeholder()
        sql = f"""
            SELECT d.* FROM bop_integration_destinations d
            JOIN bop_integration_subscriptions s ON d.id = s.destination_id
            WHERE d.bop_organization_id = {p}
              AND s.bop_organization_id = {p}
              AND d.is_active = true
              AND s.is_active = true
              AND (s.event_type = {p} OR s.event_type = '*')
            ORDER BY d.created_at ASC
        """
        rows = self.db.fetch_dicts(sql, (bop_organization_id, bop_organization_id, event_type))
        # Deduplicate destinations in case both specific and wildcard subscriptions match
        seen_ids = set()
        result = []
        for r in rows:
            dest = self._row_to_destination(r)
            if dest.id not in seen_ids:
                seen_ids.add(dest.id)
                result.append(dest)
        return result
