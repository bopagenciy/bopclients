"""Database repository for Prospects, CampaignProspects, Contacts, Signals, LeadScores, and ProspectSources (Tenant Isolated)."""

import json
from typing import List, Optional
from bopclients.domain.prospect import Prospect
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.contact import Contact
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.prospect_source import ProspectSource
from bopclients.domain.exceptions import TenantAccessError
from bopclients.application.interfaces.repositories import IProspectRepository
from bopclients.infrastructure.repositories.base_repository import BaseTenantRepository


class ProspectRepository(BaseTenantRepository, IProspectRepository):
    """Repository for Prospect and related sub-entities with complete organization_id tenant boundary enforcement."""

    def save_prospect(self, org_id: str, prospect: Prospect) -> Prospect:
        org_id = self._validate_tenant(org_id)
        prospect.organization_id = org_id
        p = self._placeholder()
        sql = f"""
        INSERT INTO prospects (
            id, organization_id, forge_record_id, name, website_url,
            phone, email, address, city, state, country, postal_code, latitude,
            longitude, industry, source, source_external_id, created_at, updated_at
        ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        self.db.execute(
            sql,
            (
                prospect.id,
                org_id,
                prospect.forge_record_id,
                prospect.name,
                prospect.website_url,
                prospect.phone,
                prospect.email,
                prospect.address,
                prospect.city,
                prospect.state,
                prospect.country,
                prospect.postal_code,
                prospect.latitude,
                prospect.longitude,
                prospect.industry,
                prospect.source,
                prospect.source_external_id,
                prospect.created_at,
                prospect.updated_at,
            ),
        )
        self.db.commit()
        return prospect

    def get_prospect_by_id(self, org_id: str, prospect_id: str) -> Optional[Prospect]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT * FROM prospects WHERE organization_id = {p} AND id = {p}"
        rows = self.db.fetch_dicts(sql, (org_id, prospect_id))
        if not rows:
            return None
        r = rows[0]
        return Prospect(
            id=r["id"],
            organization_id=r["organization_id"],
            forge_record_id=r.get("forge_record_id"),
            name=r["name"],
            website_url=r.get("website_url"),
            phone=r.get("phone"),
            email=r.get("email"),
            address=r.get("address"),
            city=r.get("city"),
            state=r.get("state"),
            country=r.get("country", "US"),
            postal_code=r.get("postal_code"),
            latitude=r.get("latitude"),
            longitude=r.get("longitude"),
            industry=r.get("industry"),
            source=r.get("source", "overture"),
            source_external_id=r.get("source_external_id"),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )

    def find_existing_prospect(
        self,
        org_id: str,
        forge_record_id: Optional[str] = None,
        website_url: Optional[str] = None,
        external_id: Optional[str] = None,
    ) -> Optional[Prospect]:
        """Find an existing prospect within the organization by forge_record_id, normalized website, or external_id."""
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()

        # Priority 1: Match by forge_record_id
        if forge_record_id:
            sql = f"SELECT id FROM prospects WHERE organization_id = {p} AND forge_record_id = {p} LIMIT 1"
            rows = self.db.fetch_dicts(sql, (org_id, forge_record_id))
            if rows:
                return self.get_prospect_by_id(org_id, rows[0]["id"])

        # Priority 2: Match by normalized website_url
        if website_url:
            norm_url = website_url.strip().lower().rstrip("/")
            sql = f"SELECT id FROM prospects WHERE organization_id = {p} AND LOWER(RTRIM(website_url, '/')) = {p} LIMIT 1"
            rows = self.db.fetch_dicts(sql, (org_id, norm_url))
            if rows:
                return self.get_prospect_by_id(org_id, rows[0]["id"])

        # Priority 3: Match by source_external_id
        if external_id:
            sql = f"SELECT id FROM prospects WHERE organization_id = {p} AND source_external_id = {p} LIMIT 1"
            rows = self.db.fetch_dicts(sql, (org_id, external_id))
            if rows:
                return self.get_prospect_by_id(org_id, rows[0]["id"])

        return None

    def add_prospect_to_campaign(
        self, org_id: str, campaign_prospect: CampaignProspect
    ) -> CampaignProspect:
        """Associate a Prospect with a Campaign in the organization."""
        org_id = self._validate_tenant(org_id)
        if campaign_prospect.organization_id != org_id:
            raise TenantAccessError("CampaignProspect organization_id mismatch")

        # Validate that prospect exists for tenant
        prospect = self.get_prospect_by_id(org_id, campaign_prospect.prospect_id)
        if not prospect:
            raise TenantAccessError(
                f"Prospect '{campaign_prospect.prospect_id}' not found for tenant '{org_id}'"
            )

        # Validate that campaign exists for tenant
        p = self._placeholder()
        camp_rows = self.db.fetch_dicts(
            f"SELECT id FROM campaigns WHERE organization_id = {p} AND id = {p}",
            (org_id, campaign_prospect.campaign_id),
        )
        if not camp_rows:
            raise TenantAccessError(
                f"Campaign '{campaign_prospect.campaign_id}' not found for tenant '{org_id}'"
            )

        sql = f"""
        INSERT INTO campaign_prospects (
            id, organization_id, campaign_id, prospect_id, status, relevance_score, added_at, created_at, updated_at
        ) VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        ON CONFLICT(organization_id, campaign_id, prospect_id) DO UPDATE SET updated_at = EXCLUDED.updated_at
        """
        self.db.execute(
            sql,
            (
                campaign_prospect.id,
                org_id,
                campaign_prospect.campaign_id,
                campaign_prospect.prospect_id,
                campaign_prospect.status,
                campaign_prospect.relevance_score,
                campaign_prospect.added_at,
                campaign_prospect.created_at,
                campaign_prospect.updated_at,
            ),
        )
        self.db.commit()
        return campaign_prospect

    def list_prospects_by_campaign(
        self, org_id: str, campaign_id: str, limit: int = 100, offset: int = 0
    ) -> List[Prospect]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"""
        SELECT p.* FROM prospects p
        JOIN campaign_prospects cp ON p.organization_id = cp.organization_id AND p.id = cp.prospect_id
        WHERE cp.organization_id = {p} AND cp.campaign_id = {p}
        ORDER BY cp.added_at DESC LIMIT {limit} OFFSET {offset}
        """
        rows = self.db.fetch_dicts(sql, (org_id, campaign_id))
        res = []
        for r in rows:
            res.append(
                Prospect(
                    id=r["id"],
                    organization_id=r["organization_id"],
                    forge_record_id=r.get("forge_record_id"),
                    name=r["name"],
                    website_url=r.get("website_url"),
                    phone=r.get("phone"),
                    email=r.get("email"),
                    address=r.get("address"),
                    city=r.get("city"),
                    state=r.get("state"),
                    country=r.get("country", "US"),
                    postal_code=r.get("postal_code"),
                    latitude=r.get("latitude"),
                    longitude=r.get("longitude"),
                    industry=r.get("industry"),
                    source=r.get("source", "overture"),
                    source_external_id=r.get("source_external_id"),
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
            )
        return res

    def list_prospect_campaigns(self, org_id: str, prospect_id: str) -> List[CampaignProspect]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT * FROM campaign_prospects WHERE organization_id = {p} AND prospect_id = {p}"
        rows = self.db.fetch_dicts(sql, (org_id, prospect_id))
        return [
            CampaignProspect(
                id=r["id"],
                organization_id=r["organization_id"],
                campaign_id=r["campaign_id"],
                prospect_id=r["prospect_id"],
                status=r.get("status", "added"),
                relevance_score=r.get("relevance_score"),
                added_at=r["added_at"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def add_contact(self, org_id: str, contact: Contact) -> Contact:
        org_id = self._validate_tenant(org_id)
        contact.organization_id = org_id
        prospect = self.get_prospect_by_id(org_id, contact.prospect_id)
        if not prospect:
            raise ValueError(f"Prospect '{contact.prospect_id}' not found for tenant '{org_id}'")

        p = self._placeholder()
        sql = f"""
        INSERT INTO contacts (id, organization_id, prospect_id, name, first_name, last_name, title, email, phone, linkedin_url, instagram_url, facebook_url)
        VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        self.db.execute(
            sql,
            (
                contact.id,
                org_id,
                contact.prospect_id,
                contact.name,
                contact.first_name,
                contact.last_name,
                contact.title,
                contact.email,
                contact.phone,
                contact.linkedin_url,
                contact.instagram_url,
                contact.facebook_url,
            ),
        )
        self.db.commit()
        return contact

    def list_contacts(self, org_id: str, prospect_id: str) -> List[Contact]:
        org_id = self._validate_tenant(org_id)
        prospect = self.get_prospect_by_id(org_id, prospect_id)
        if not prospect:
            return []
        p = self._placeholder()
        sql = f"SELECT * FROM contacts WHERE organization_id = {p} AND prospect_id = {p}"
        rows = self.db.fetch_dicts(sql, (org_id, prospect_id))
        return [
            Contact(
                id=r["id"],
                organization_id=r["organization_id"],
                prospect_id=r["prospect_id"],
                name=r["name"],
                first_name=r.get("first_name"),
                last_name=r.get("last_name"),
                title=r.get("title"),
                email=r.get("email"),
                phone=r.get("phone"),
                linkedin_url=r.get("linkedin_url"),
                instagram_url=r.get("instagram_url"),
                facebook_url=r.get("facebook_url"),
            )
            for r in rows
        ]

    def add_signal(self, org_id: str, signal: Signal) -> Signal:
        org_id = self._validate_tenant(org_id)
        signal.organization_id = org_id
        p = self._placeholder()

        evidence_json = json.dumps(signal.evidence) if signal.evidence is not None else None

        check_sql = f"SELECT id FROM signals WHERE organization_id = {p} AND prospect_id = {p} AND type = {p}"
        existing = self.db.fetch_dicts(check_sql, (org_id, signal.prospect_id, signal.type))

        if existing:
            sql = f"""
            UPDATE signals
            SET value = {p}, confidence = {p}, source = {p}, evidence = {p}, detected_at = {p}
            WHERE organization_id = {p} AND prospect_id = {p} AND type = {p}
            """
            self.db.execute(
                sql,
                (
                    signal.value,
                    signal.confidence,
                    signal.source,
                    evidence_json,
                    signal.detected_at,
                    org_id,
                    signal.prospect_id,
                    signal.type,
                ),
            )
        else:
            sql = f"""
            INSERT INTO signals (id, organization_id, prospect_id, type, value, confidence, source, evidence, detected_at)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})
            """
            self.db.execute(
                sql,
                (
                    signal.id,
                    org_id,
                    signal.prospect_id,
                    signal.type,
                    signal.value,
                    signal.confidence,
                    signal.source,
                    evidence_json,
                    signal.detected_at,
                ),
            )
        self.db.commit()
        return signal

    def delete_signal_by_type(self, org_id: str, prospect_id: str, signal_type: str) -> None:
        """Remove a stale signal when conclusive evidence indicates the condition no longer exists."""
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"DELETE FROM signals WHERE organization_id = {p} AND prospect_id = {p} AND type = {p}"
        self.db.execute(sql, (org_id, prospect_id, signal_type))
        self.db.commit()

    def list_signals(self, org_id: str, prospect_id: str) -> List[Signal]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT * FROM signals WHERE organization_id = {p} AND prospect_id = {p} ORDER BY detected_at DESC"
        rows = self.db.fetch_dicts(sql, (org_id, prospect_id))
        res = []
        for r in rows:
            ev_raw = r.get("evidence")
            ev_dict = json.loads(ev_raw) if ev_raw and isinstance(ev_raw, str) else ev_raw
            res.append(
                Signal(
                    id=r["id"],
                    organization_id=r["organization_id"],
                    prospect_id=r["prospect_id"],
                    type=r["type"],
                    value=r.get("value"),
                    confidence=float(r.get("confidence", 1.0)),
                    source=r.get("source", "bopclients_detector"),
                    evidence=ev_dict,
                    detected_at=r["detected_at"],
                )
            )
        return res

    def save_lead_score(self, org_id: str, score: LeadScore) -> LeadScore:
        org_id = self._validate_tenant(org_id)
        score.organization_id = org_id
        p = self._placeholder()

        check_sql = f"SELECT id FROM lead_scores WHERE organization_id = {p} AND prospect_id = {p}"
        existing = self.db.fetch_dicts(check_sql, (org_id, score.prospect_id))

        if existing:
            sql = f"""
            UPDATE lead_scores
            SET score = {p}, scoring_version = {p}, explanation = {p}, created_at = {p}
            WHERE organization_id = {p} AND prospect_id = {p}
            """
            self.db.execute(
                sql,
                (
                    score.score,
                    score.scoring_version,
                    score.explanation,
                    score.created_at,
                    org_id,
                    score.prospect_id,
                ),
            )
        else:
            sql = f"""
            INSERT INTO lead_scores (id, organization_id, prospect_id, score, scoring_version, explanation, created_at)
            VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
            """
            self.db.execute(
                sql,
                (
                    score.id,
                    org_id,
                    score.prospect_id,
                    score.score,
                    score.scoring_version,
                    score.explanation,
                    score.created_at,
                ),
            )
        self.db.commit()
        return score

    def get_lead_score(self, org_id: str, prospect_id: str) -> Optional[LeadScore]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT * FROM lead_scores WHERE organization_id = {p} AND prospect_id = {p}"
        rows = self.db.fetch_dicts(sql, (org_id, prospect_id))
        if not rows:
            return None
        r = rows[0]
        return LeadScore(
            id=r["id"],
            organization_id=r["organization_id"],
            prospect_id=r["prospect_id"],
            score=r["score"],
            scoring_version=r.get("scoring_version", "v1.0"),
            explanation=r.get("explanation"),
            created_at=r["created_at"],
        )

    def add_prospect_source(self, org_id: str, source: ProspectSource) -> ProspectSource:
        org_id = self._validate_tenant(org_id)
        source.organization_id = org_id
        p = self._placeholder()

        # Check existing provenance source to avoid duplicate identical rows
        if source.external_id:
            check_sql = f"""
            SELECT * FROM prospect_sources
            WHERE organization_id = {p} AND prospect_id = {p} AND source_type = {p} AND external_id = {p}
            LIMIT 1
            """
            rows = self.db.fetch_dicts(check_sql, (org_id, source.prospect_id, source.source_type, source.external_id))
            if rows:
                r = rows[0]
                return ProspectSource(
                    id=r["id"],
                    organization_id=r["organization_id"],
                    prospect_id=r["prospect_id"],
                    source_type=r["source_type"],
                    source_url=r.get("source_url"),
                    external_id=r.get("external_id"),
                    collected_at=r["collected_at"],
                )

        sql = f"""
        INSERT INTO prospect_sources (id, organization_id, prospect_id, source_type, source_url, external_id, collected_at)
        VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p})
        """
        self.db.execute(
            sql,
            (
                source.id,
                org_id,
                source.prospect_id,
                source.source_type,
                source.source_url,
                source.external_id,
                source.collected_at,
            ),
        )
        self.db.commit()
        return source

    def list_prospect_sources(self, org_id: str, prospect_id: str) -> List[ProspectSource]:
        org_id = self._validate_tenant(org_id)
        p = self._placeholder()
        sql = f"SELECT * FROM prospect_sources WHERE organization_id = {p} AND prospect_id = {p} ORDER BY collected_at DESC"
        rows = self.db.fetch_dicts(sql, (org_id, prospect_id))
        return [
            ProspectSource(
                id=r["id"],
                organization_id=r["organization_id"],
                prospect_id=r["prospect_id"],
                source_type=r["source_type"],
                source_url=r.get("source_url"),
                external_id=r.get("external_id"),
                collected_at=r["collected_at"],
            )
            for r in rows
        ]
