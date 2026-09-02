"""Database repository for Ideal Customer Profiles (Tenant Isolated)."""

import json
from typing import List, Optional
from bopclients.domain.icp import IdealCustomerProfile, TargetMarket
from bopclients.application.interfaces.repositories import IICPRepository
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class ICPRepository(BaseTenantRepository, IICPRepository):
    """Repository for managing Ideal Customer Profiles and Target Markets."""

    def save(self, org_id: str, icp: IdealCustomerProfile) -> IdealCustomerProfile:
        org_id = self._validate_tenant(org_id)
        icp.organization_id = org_id
        p = self._placeholder()

        sql = f"""
        INSERT INTO ideal_customer_profiles (
            id, organization_id, name, description, industries, company_sizes,
            decision_maker_roles, pain_points, desired_signals, excluded_signals,
            countries, languages, created_at
        ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        self.db.execute(
            sql,
            (
                icp.id,
                org_id,
                icp.name,
                icp.description,
                json.dumps(icp.industries),
                json.dumps(icp.company_sizes),
                json.dumps(icp.decision_maker_roles),
                json.dumps(icp.pain_points),
                json.dumps(icp.desired_signals),
                json.dumps(icp.excluded_signals),
                json.dumps(icp.countries),
                json.dumps(icp.languages),
                icp.created_at,
            ),
        )

        # Save TargetMarkets
        for tm in icp.target_markets:
            tm.icp_id = icp.id
            tm_sql = f"""
            INSERT INTO target_markets (id, icp_id, country, region, city, postal_code, radius_miles, language)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """
            self.db.execute(
                tm_sql,
                (tm.id, tm.icp_id, tm.country, tm.region, tm.city, tm.postal_code, tm.radius_miles, tm.language),
            )

        self.db.commit()
        return icp

    def get_by_id(self, org_id: str, icp_id: str) -> Optional[IdealCustomerProfile]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT * FROM ideal_customer_profiles WHERE organization_id = {p} AND id = {p}"
        rows = self.db.fetch_dicts(sql, (org_id, icp_id))
        if not rows:
            return None
        r = rows[0]

        # Fetch TargetMarkets
        tm_sql = f"SELECT * FROM target_markets WHERE icp_id = {p}"
        tm_rows = self.db.fetch_dicts(tm_sql, (icp_id,))
        tms = [
            TargetMarket(
                id=tm["id"],
                icp_id=tm["icp_id"],
                country=tm["country"],
                region=tm.get("region"),
                city=tm.get("city"),
                postal_code=tm.get("postal_code"),
                radius_miles=tm.get("radius_miles", 10.0),
                language=tm.get("language", "en"),
            )
            for tm in tm_rows
        ]

        return IdealCustomerProfile(
            id=r["id"],
            organization_id=r["organization_id"],
            name=r["name"],
            description=r.get("description", ""),
            industries=json.loads(r["industries"]) if r.get("industries") else [],
            company_sizes=json.loads(r["company_sizes"]) if r.get("company_sizes") else [],
            decision_maker_roles=json.loads(r["decision_maker_roles"]) if r.get("decision_maker_roles") else [],
            pain_points=json.loads(r["pain_points"]) if r.get("pain_points") else [],
            desired_signals=json.loads(r["desired_signals"]) if r.get("desired_signals") else [],
            excluded_signals=json.loads(r["excluded_signals"]) if r.get("excluded_signals") else [],
            countries=json.loads(r["countries"]) if r.get("countries") else ["US"],
            languages=json.loads(r["languages"]) if r.get("languages") else ["en"],
            target_markets=tms,
            created_at=r["created_at"],
        )

    def list_by_organization(self, org_id: str) -> List[IdealCustomerProfile]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT id FROM ideal_customer_profiles WHERE organization_id = {p} ORDER BY created_at DESC"
        rows = self.db.fetch_dicts(sql, (org_id,))
        res = []
        for r in rows:
            icp = self.get_by_id(org_id, r["id"])
            if icp:
                res.append(icp)
        return res
