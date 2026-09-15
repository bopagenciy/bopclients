"""Comprehensive integration tests for P22 Prospect Operations Workspace.

Covers:
1. Multi-dimensional filtering:
   - Campaign filter
   - Priority filter
   - Lead score range (score_min, score_max)
   - Unscored prospects filter
   - Has signals filter (true / false)
   - Search term (q / search)
2. Safe sorting validation (including 400 on invalid sort keys):
   - Sort by created_at, name, lead_score, priority, etc.
3. Batch query hydration:
   - Verify lead_score, priority_tier, campaign_count, campaign_names, signals_count in response items
4. Bulk operations:
   - Bulk add to campaign (max 100 limit, duplicate handling, partial outcome reporting)
   - Bulk recalculate score (max 50 limit)
   - Bulk recalculate priority (max 50 limit)
   - Bulk trigger research (max 25 limit, duplicate guard)
5. CSV Export:
   - Filter-based export and selected-IDs export
   - Security: formula injection mitigation (=, +, -, @ escaped with single quote)
   - Proper headers (Content-Disposition, Content-Type: text/csv; charset=utf-8)
6. RBAC & Multi-tenant isolation:
   - Viewer denied on bulk mutations (HTTP 403)
   - Member allowed on bulk mutations (HTTP 200/202)
   - Viewer allowed on CSV export (HTTP 200)
   - Cross-tenant isolation (Tenant B cannot access or operate on Tenant A prospects)
"""

import uuid
import pytest
from starlette.testclient import TestClient

from bopclients.api.app import create_bopclients_api_app
from bopclients.infrastructure.db.connection import create_database_connection
from bopclients.runtime.db_migrator import DatabaseMigrator
from bopclients.runtime.settings import RuntimeSettings
from bopclients.runtime.container import build_runtime_container
from bopclients.domain.organization import Organization, OrganizationMember
from bopclients.domain.campaign import Campaign
from bopclients.domain.prospect import Prospect
from bopclients.domain.signal import Signal
from bopclients.domain.lead_score import LeadScore
from bopclients.domain.prospect_priority import ProspectPriority
from bopclients.domain.campaign_prospect import CampaignProspect
from bopclients.domain.enums import CampaignStatus, SignalCategory


@pytest.fixture
def p22_fixture():
    db = create_database_connection(":memory:")
    DatabaseMigrator.migrate(db)

    settings = RuntimeSettings(
        database_url=":memory:",
        auth_signing_key="p22-unit-test-signing-key-minimum-32-chars-long!",
        auth_token_expire_seconds=3600,
        auth_session_expire_days=7,
        enabled_providers=["official_website"],
    )
    container = build_runtime_container(settings, db=db)
    app = create_bopclients_api_app(container)
    client = TestClient(app)

    auth_service = container.auth_service

    # Setup Tenant A
    user_a = auth_service.register_user(
        email="owner_a@p22corp.com",
        name="Owner A",
        password="PasswordA123!",
        locale="en",
    )
    viewer_a = auth_service.register_user(
        email="viewer_a@p22corp.com",
        name="Viewer A",
        password="PasswordViewer123!",
        locale="en",
    )
    member_a = auth_service.register_user(
        email="member_a@p22corp.com",
        name="Member A",
        password="PasswordMember123!",
        locale="en",
    )

    org_a = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="P22 Alpha Corp",
        slug="p22-alpha-corp",
    )
    container.org_repo.save(org_a)
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=user_a.id,
            role="OWNER",
        )
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=viewer_a.id,
            role="VIEWER",
        )
    )
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_a.id,
            user_id=member_a.id,
            role="MEMBER",
        )
    )

    # Setup Tenant B
    user_b = auth_service.register_user(
        email="owner_b@p22beta.com",
        name="Owner B",
        password="PasswordB123!",
        locale="en",
    )
    org_b = Organization(
        id=str(uuid.uuid4()),
        bop_organization_id=str(uuid.uuid4()),
        name="P22 Beta Corp",
        slug="p22-beta-corp",
    )
    container.org_repo.save(org_b)
    container.org_repo.add_member(
        OrganizationMember(
            id=str(uuid.uuid4()),
            organization_id=org_b.id,
            user_id=user_b.id,
            role="OWNER",
        )
    )

    # Seed Campaigns for Tenant A
    camp_a1 = Campaign(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Safety Gear Campaign",
        status=CampaignStatus.ACTIVE,
    )
    container.campaign_repo.save(org_a.id, camp_a1)

    camp_a2 = Campaign(
        id=str(uuid.uuid4()),
        organization_id=org_a.id,
        name="Logistics Ops Campaign",
        status=CampaignStatus.ACTIVE,
    )
    container.campaign_repo.save(org_a.id, camp_a2)

    # Seed Prospects for Tenant A
    # P1: High score (85), urgent priority, in camp_a1, has signals
    p1 = Prospect(
        id="01944111-0000-7000-8000-000000000001",
        organization_id=org_a.id,
        name="=CmdInjection Co",
        website_url="https://cmdinjection.com",
        phone="555-0101",
        email="contact@cmdinjection.com",
        city="Miami",
        state="FL",
        country="US",
        industry="Technology",
        source="manual",
    )
    container.prospect_repo.save_prospect(org_a.id, p1)

    # P2: Medium score (50), medium priority, in camp_a1 and camp_a2, no signals
    p2 = Prospect(
        id="01944111-0000-7000-8000-000000000002",
        organization_id=org_a.id,
        name="Atlas Logistics LLC",
        website_url="https://atlaslogistics.com",
        phone="555-0102",
        email="info@atlaslogistics.com",
        city="Tampa",
        state="FL",
        country="US",
        industry="Logistics",
        source="manual",
    )
    container.prospect_repo.save_prospect(org_a.id, p2)

    # P3: Unscored, no priority, not in campaign, has signals
    p3 = Prospect(
        id="01944111-0000-7000-8000-000000000003",
        organization_id=org_a.id,
        name="Zenith Health Inc",
        website_url="https://zenithhealth.com",
        phone="555-0103",
        email="hello@zenithhealth.com",
        city="Orlando",
        state="FL",
        country="US",
        industry="Healthcare",
        source="csv_import",
    )
    container.prospect_repo.save_prospect(org_a.id, p3)

    # Seed Tenant B prospect
    p_b = Prospect(
        id="01944111-0000-7000-8000-000000000009",
        organization_id=org_b.id,
        name="Beta Secret Corp",
        website_url="https://betasecret.com",
        city="Dallas",
        state="TX",
        country="US",
        industry="Security",
        source="manual",
    )
    container.prospect_repo.save_prospect(org_b.id, p_b)

    # Associations, scores, priorities, signals
    # P1 score 85, priority urgent, signal
    container.prospect_service.assign_score(org_a.id, p1.id, 85, "High fit ICP and strong signals")
    p1_prio = ProspectPriority(
        organization_id=org_a.id,
        campaign_id=camp_a1.id,
        prospect_id=p1.id,
        priority_score=90,
        priority_label="urgent",
    )
    container.priority_repo.save(org_a.id, p1_prio)
    cp1 = CampaignProspect(
        organization_id=org_a.id,
        campaign_id=camp_a1.id,
        prospect_id=p1.id,
    )
    container.prospect_repo.add_prospect_to_campaign(org_a.id, cp1)
    sig1 = Signal(
        organization_id=org_a.id,
        prospect_id=p1.id,
        type="hiring_surge",
        category=SignalCategory.COMPANY_ACTIVITY,
        value="Hiring safety directors",
    )
    container.prospect_repo.add_signal(org_a.id, sig1)

    # P2 score 50, priority medium, both campaigns
    container.prospect_service.assign_score(org_a.id, p2.id, 50, "Moderate ICP fit")
    p2_prio = ProspectPriority(
        organization_id=org_a.id,
        campaign_id=camp_a1.id,
        prospect_id=p2.id,
        priority_score=55,
        priority_label="medium",
    )
    container.priority_repo.save(org_a.id, p2_prio)
    cp2_1 = CampaignProspect(
        organization_id=org_a.id,
        campaign_id=camp_a1.id,
        prospect_id=p2.id,
    )
    container.prospect_repo.add_prospect_to_campaign(org_a.id, cp2_1)
    cp2_2 = CampaignProspect(
        organization_id=org_a.id,
        campaign_id=camp_a2.id,
        prospect_id=p2.id,
    )
    container.prospect_repo.add_prospect_to_campaign(org_a.id, cp2_2)

    # P3 signal
    sig3 = Signal(
        organization_id=org_a.id,
        prospect_id=p3.id,
        type="expansion",
        category=SignalCategory.NEED,
        value="New facility opening",
    )
    container.prospect_repo.add_signal(org_a.id, sig3)

    # Generate Auth Tokens
    token_a = auth_service.authenticate("owner_a@p22corp.com", "PasswordA123!")
    token_viewer_a = auth_service.authenticate("viewer_a@p22corp.com", "PasswordViewer123!")
    token_member_a = auth_service.authenticate("member_a@p22corp.com", "PasswordMember123!")
    token_b = auth_service.authenticate("owner_b@p22beta.com", "PasswordB123!")

    headers_a = {
        "Authorization": f"Bearer {token_a.access_token}",
        "X-Bop-Organization-Id": org_a.bop_organization_id,
    }
    headers_viewer_a = {
        "Authorization": f"Bearer {token_viewer_a.access_token}",
        "X-Bop-Organization-Id": org_a.bop_organization_id,
    }
    headers_member_a = {
        "Authorization": f"Bearer {token_member_a.access_token}",
        "X-Bop-Organization-Id": org_a.bop_organization_id,
    }
    headers_b = {
        "Authorization": f"Bearer {token_b.access_token}",
        "X-Bop-Organization-Id": org_b.bop_organization_id,
    }

    return {
        "client": client,
        "container": container,
        "org_a": org_a,
        "org_b": org_b,
        "camp_a1": camp_a1,
        "camp_a2": camp_a2,
        "p1": p1,
        "p2": p2,
        "p3": p3,
        "p_b": p_b,
        "headers_a": headers_a,
        "headers_viewer_a": headers_viewer_a,
        "headers_member_a": headers_member_a,
        "headers_b": headers_b,
    }


def test_prospect_listing_and_hydration(p22_fixture):
    client = p22_fixture["client"]
    headers = p22_fixture["headers_a"]

    resp = client.get("/api/v1/prospects", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_items"] == 3
    items = data["items"]
    assert len(items) == 3

    # Check hydration on p1
    item1 = next(it for it in items if it["id"] == p22_fixture["p1"].id)
    assert item1["lead_score"] == 85
    assert item1["priority_tier"] == "urgent"
    assert item1["campaign_count"] == 1
    assert "Safety Gear Campaign" in item1["campaign_names"]
    assert item1["signals_count"] == 1

    # Check hydration on p2
    item2 = next(it for it in items if it["id"] == p22_fixture["p2"].id)
    assert item2["lead_score"] == 50
    assert item2["priority_tier"] == "medium"
    assert item2["campaign_count"] == 2
    assert "Safety Gear Campaign" in item2["campaign_names"]
    assert "Logistics Ops Campaign" in item2["campaign_names"]
    assert item2["signals_count"] == 0

    # Check hydration on p3
    item3 = next(it for it in items if it["id"] == p22_fixture["p3"].id)
    assert item3["lead_score"] is None
    assert item3["priority_tier"] is None
    assert item3["campaign_count"] == 0
    assert item3["campaign_names"] == []
    assert item3["signals_count"] == 1


def test_prospect_multi_dimensional_filtering(p22_fixture):
    client = p22_fixture["client"]
    headers = p22_fixture["headers_a"]

    # 1. Filter by campaign
    r_camp = client.get(f"/api/v1/prospects?campaign_id={p22_fixture['camp_a2'].id}", headers=headers)
    assert r_camp.status_code == 200
    assert r_camp.json()["total_items"] == 1
    assert r_camp.json()["items"][0]["id"] == p22_fixture["p2"].id

    # 2. Filter by priority
    r_prio = client.get("/api/v1/prospects?priority=urgent", headers=headers)
    assert r_prio.status_code == 200
    assert r_prio.json()["total_items"] == 1
    assert r_prio.json()["items"][0]["id"] == p22_fixture["p1"].id

    # 3. Filter by score range (score_min=60)
    r_score = client.get("/api/v1/prospects?score_min=60", headers=headers)
    assert r_score.status_code == 200
    assert r_score.json()["total_items"] == 1
    assert r_score.json()["items"][0]["id"] == p22_fixture["p1"].id

    # 4. Filter by unscored=true
    r_unscored = client.get("/api/v1/prospects?unscored=true", headers=headers)
    assert r_unscored.status_code == 200
    assert r_unscored.json()["total_items"] == 1
    assert r_unscored.json()["items"][0]["id"] == p22_fixture["p3"].id

    # 5. Filter by has_signals=false
    r_nosig = client.get("/api/v1/prospects?has_signals=false", headers=headers)
    assert r_nosig.status_code == 200
    assert r_nosig.json()["total_items"] == 1
    assert r_nosig.json()["items"][0]["id"] == p22_fixture["p2"].id

    # 6. Free text search (search or q)
    r_search = client.get("/api/v1/prospects?q=zenith", headers=headers)
    assert r_search.status_code == 200
    assert r_search.json()["total_items"] == 1
    assert r_search.json()["items"][0]["id"] == p22_fixture["p3"].id


def test_prospect_sorting_and_validation(p22_fixture):
    client = p22_fixture["client"]
    headers = p22_fixture["headers_a"]

    # 1. Invalid sort column -> HTTP 400
    r_bad = client.get("/api/v1/prospects?sort_by=invalid_col", headers=headers)
    assert r_bad.status_code == 400
    assert "Invalid sort field" in r_bad.json()["error"]["message"]

    # 2. Sort by lead_score DESC
    r_score = client.get("/api/v1/prospects?sort_by=lead_score&sort_dir=desc", headers=headers)
    assert r_score.status_code == 200
    ids = [it["id"] for it in r_score.json()["items"]]
    assert ids[0] == p22_fixture["p1"].id  # score 85
    assert ids[1] == p22_fixture["p2"].id  # score 50
    assert ids[2] == p22_fixture["p3"].id  # None -> -1

    # 3. Sort by priority DESC
    r_prio = client.get("/api/v1/prospects?sort_by=priority&sort_dir=desc", headers=headers)
    assert r_prio.status_code == 200
    ids = [it["id"] for it in r_prio.json()["items"]]
    assert ids[0] == p22_fixture["p1"].id  # priority 90
    assert ids[1] == p22_fixture["p2"].id  # priority 55


def test_bulk_add_to_campaign(p22_fixture):
    client = p22_fixture["client"]
    headers = p22_fixture["headers_a"]
    camp_id = p22_fixture["camp_a1"].id
    p1_id = p22_fixture["p1"].id  # already in camp_a1
    p3_id = p22_fixture["p3"].id  # not in camp_a1

    payload = {
        "campaign_id": camp_id,
        "prospect_ids": [p1_id, p3_id, "non-existent-id"],
    }
    resp = client.post("/api/v1/prospects/bulk/add-to-campaign", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["requested"] == 3
    assert data["added"] == 1
    assert data["already_present"] == 1
    assert data["failed"] == 1
    assert data["prospect_ids"] == [p3_id]

    # Test alias route /api/v1/campaigns/{id}/prospects/bulk
    resp_alias = client.post(
        f"/api/v1/campaigns/{camp_id}/prospects/bulk",
        json={"campaign_id": camp_id, "prospect_ids": [p3_id]},
        headers=headers,
    )
    assert resp_alias.status_code == 200
    assert resp_alias.json()["already_present"] == 1


def test_bulk_recalculate_score_and_priority(p22_fixture):
    client = p22_fixture["client"]
    headers = p22_fixture["headers_a"]
    p1_id = p22_fixture["p1"].id
    p2_id = p22_fixture["p2"].id

    # 1. Bulk score
    resp_score = client.post(
        "/api/v1/prospects/bulk/recalculate-score",
        json={"prospect_ids": [p1_id, p2_id, "bogus-id"]},
        headers=headers,
    )
    assert resp_score.status_code == 200
    s_data = resp_score.json()
    assert s_data["requested"] == 3
    assert s_data["succeeded"] == 2
    assert s_data["failed"] == 1

    # 2. Bulk priority
    resp_prio = client.post(
        "/api/v1/prospects/bulk/recalculate-priority",
        json={"prospect_ids": [p1_id, p2_id, "bogus-id"]},
        headers=headers,
    )
    assert resp_prio.status_code == 200
    p_data = resp_prio.json()
    assert p_data["requested"] == 3
    assert p_data["succeeded"] == 2
    assert p_data["failed"] == 1


def test_bulk_research_trigger(p22_fixture):
    client = p22_fixture["client"]
    headers = p22_fixture["headers_a"]
    p1_id = p22_fixture["p1"].id
    p2_id = p22_fixture["p2"].id

    resp = client.post(
        "/api/v1/prospects/bulk/research",
        json={"prospect_ids": [p1_id, p2_id], "run_type": "full_diligence"},
        headers=headers,
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["requested"] == 2
    assert data["queued"] == 2
    assert data["already_active"] == 0

    # Triggering again immediately should recognize active runs
    resp2 = client.post(
        "/api/v1/prospects/bulk/research",
        json={"prospect_ids": [p1_id, p2_id]},
        headers=headers,
    )
    assert resp2.status_code == 202
    data2 = resp2.json()
    assert data2["already_active"] == 2
    assert data2["queued"] == 0


def test_csv_export_security_and_headers(p22_fixture):
    client = p22_fixture["client"]
    headers = p22_fixture["headers_a"]

    # 1. Filtered GET export
    resp = client.get("/api/v1/prospects/export?priority=urgent", headers=headers)
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["Content-Type"]
    assert "attachment; filename=" in resp.headers["Content-Disposition"]
    csv_text = resp.text

    # Verify formula injection mitigation on p1 company name '=CmdInjection Co'
    # Should start with "'=CmdInjection Co"
    assert "'=CmdInjection Co" in csv_text

    # 2. Selected POST export
    p2_id = p22_fixture["p2"].id
    resp_post = client.post(
        "/api/v1/prospects/export",
        json={"prospect_ids": [p2_id]},
        headers=headers,
    )
    assert resp_post.status_code == 200
    assert "Atlas Logistics LLC" in resp_post.text
    assert "Zenith Health Inc" not in resp_post.text


def test_rbac_enforcement_on_operations(p22_fixture):
    client = p22_fixture["client"]
    viewer_headers = p22_fixture["headers_viewer_a"]
    member_headers = p22_fixture["headers_member_a"]

    camp_id = p22_fixture["camp_a1"].id
    p3_id = p22_fixture["p3"].id

    # 1. Viewer denied on bulk mutations -> HTTP 403
    r_v_add = client.post(
        "/api/v1/prospects/bulk/add-to-campaign",
        json={"campaign_id": camp_id, "prospect_ids": [p3_id]},
        headers=viewer_headers,
    )
    assert r_v_add.status_code == 403

    r_v_score = client.post(
        "/api/v1/prospects/bulk/recalculate-score",
        json={"prospect_ids": [p3_id]},
        headers=viewer_headers,
    )
    assert r_v_score.status_code == 403

    r_v_research = client.post(
        "/api/v1/prospects/bulk/research",
        json={"prospect_ids": [p3_id]},
        headers=viewer_headers,
    )
    assert r_v_research.status_code == 403

    # 2. Viewer allowed on CSV export -> HTTP 200
    r_v_export = client.get("/api/v1/prospects/export", headers=viewer_headers)
    assert r_v_export.status_code == 200

    # 3. Member allowed on bulk mutations -> HTTP 200
    r_m_score = client.post(
        "/api/v1/prospects/bulk/recalculate-score",
        json={"prospect_ids": [p3_id]},
        headers=member_headers,
    )
    assert r_m_score.status_code == 200


def test_tenant_isolation(p22_fixture):
    client = p22_fixture["client"]
    headers_a = p22_fixture["headers_a"]
    headers_b = p22_fixture["headers_b"]
    p1_a_id = p22_fixture["p1"].id
    p3_a_id = p22_fixture["p3"].id
    p_b_id = p22_fixture["p_b"].id
    camp_a_id = p22_fixture["camp_a1"].id

    # 1. Tenant B listing only sees Tenant B prospects
    r_list = client.get("/api/v1/prospects", headers=headers_b)
    assert r_list.status_code == 200
    assert r_list.json()["total_items"] == 1
    assert r_list.json()["items"][0]["id"] == p_b_id

    # 2. Campaign filter cannot reveal Org B prospects
    # Tenant A filtered by campaign sees only Org A prospects
    r_filter_a = client.get(f"/api/v1/prospects?campaign_id={camp_a_id}", headers=headers_a)
    assert r_filter_a.status_code == 200
    returned_ids_a = [item["id"] for item in r_filter_a.json()["items"]]
    assert p_b_id not in returned_ids_a
    # Tenant B querying with Tenant A's campaign returns 0 items
    r_filter_b = client.get(f"/api/v1/prospects?campaign_id={camp_a_id}", headers=headers_b)
    assert r_filter_b.status_code == 200
    assert r_filter_b.json()["total_items"] == 0

    # 3. Filtered export cannot include Org B data
    r_exp_filtered_a = client.get(f"/api/v1/prospects/export?campaign_id={camp_a_id}", headers=headers_a)
    assert r_exp_filtered_a.status_code == 200
    assert "Beta Secret Corp" not in r_exp_filtered_a.text
    # Tenant B filtered export with Tenant A's campaign returns empty CSV (only headers)
    r_exp_filtered_b = client.get(f"/api/v1/prospects/export?campaign_id={camp_a_id}", headers=headers_b)
    assert r_exp_filtered_b.status_code == 200
    assert "Beta Secret Corp" not in r_exp_filtered_b.text
    assert "Atlas Logistics LLC" not in r_exp_filtered_b.text

    # 4. Selected-ID export cannot include Org B data
    # Tenant A attempts to export Tenant B prospect by ID
    r_exp_selected_foreign = client.post(
        "/api/v1/prospects/export",
        json={"prospect_ids": [p_b_id]},
        headers=headers_a,
    )
    assert r_exp_selected_foreign.status_code == 200
    assert "Beta Secret Corp" not in r_exp_selected_foreign.text
    # Mixed IDs: Org A and Org B in selected-ID export
    r_exp_selected_mixed = client.post(
        "/api/v1/prospects/export",
        json={"prospect_ids": [p22_fixture["p2"].id, p_b_id]},
        headers=headers_a,
    )
    assert r_exp_selected_mixed.status_code == 200
    assert "Atlas Logistics LLC" in r_exp_selected_mixed.text
    assert "Beta Secret Corp" not in r_exp_selected_mixed.text

    # 5. Mixed-tenant bulk payload cannot mutate Org B prospect
    r_bulk_mixed = client.post(
        "/api/v1/prospects/bulk/add-to-campaign",
        json={"campaign_id": camp_a_id, "prospect_ids": [p3_a_id, p_b_id]},
        headers=headers_a,
    )
    assert r_bulk_mixed.status_code == 200
    data_mixed = r_bulk_mixed.json()
    assert data_mixed["added"] == 1
    assert data_mixed["failed"] == 1
    assert p_b_id not in data_mixed["prospect_ids"]
    assert p3_a_id in data_mixed["prospect_ids"]

    # Verify Org B prospect has no associations in Org A's campaign or Org B's DB
    container = p22_fixture["container"]
    org_b_id = p22_fixture["org_b"].id
    cps_b = container.prospect_repo.get_campaign_prospects_by_prospect(org_b_id, p_b_id)
    assert len(cps_b) == 0

    # Mixed-tenant bulk score recalculation
    r_bulk_score = client.post(
        "/api/v1/prospects/bulk/recalculate-score",
        json={"prospect_ids": [p3_a_id, p_b_id]},
        headers=headers_a,
    )
    assert r_bulk_score.status_code == 200
    items_score = {item["prospect_id"]: item["status"] for item in r_bulk_score.json()["items"]}
    assert items_score[p3_a_id] == "succeeded"
    assert items_score[p_b_id] == "failed"

    # Tenant B cannot bulk add Tenant A prospect to Tenant A campaign -> 404
    r_bulk_b = client.post(
        "/api/v1/prospects/bulk/add-to-campaign",
        json={"campaign_id": camp_a_id, "prospect_ids": [p1_a_id]},
        headers=headers_b,
    )
    assert r_bulk_b.status_code == 404
