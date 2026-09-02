"""DDL schema definitions for BopClients multi-tenant SaaS tables.

Supports both SQLite (validated locally) and PostgreSQL syntax (designed for compatibility).
"""

from typing import List

# DDL statements for creating BopClients tables
BOPCLIENTS_DDL_TABLES: List[str] = [
    # 1. users (Global identity)
    """
    CREATE TABLE IF NOT EXISTS users (
        id VARCHAR(36) PRIMARY KEY,
        email VARCHAR(255) UNIQUE NOT NULL,
        full_name VARCHAR(255) NOT NULL,
        created_at VARCHAR(50) NOT NULL
    );
    """,
    # 2. organizations (Tenant Root)
    """
    CREATE TABLE IF NOT EXISTS organizations (
        id VARCHAR(36) PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        slug VARCHAR(100) UNIQUE NOT NULL,
        description TEXT,
        website VARCHAR(255),
        country VARCHAR(10) NOT NULL DEFAULT 'US',
        default_language VARCHAR(10) NOT NULL DEFAULT 'en',
        timezone VARCHAR(50) NOT NULL DEFAULT 'UTC',
        created_at VARCHAR(50) NOT NULL,
        updated_at VARCHAR(50) NOT NULL
    );
    """,
    # 3. organization_members
    """
    CREATE TABLE IF NOT EXISTS organization_members (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        user_id VARCHAR(36) NOT NULL,
        role VARCHAR(20) NOT NULL DEFAULT 'member',
        created_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE (organization_id, user_id)
    );
    """,
    # 4. organization_settings
    """
    CREATE TABLE IF NOT EXISTS organization_settings (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        key VARCHAR(100) NOT NULL,
        value TEXT NOT NULL,
        updated_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
        UNIQUE (organization_id, key)
    );
    """,
    # 5. services (what the org sells)
    """
    CREATE TABLE IF NOT EXISTS services (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        category VARCHAR(100) NOT NULL,
        active BOOLEAN NOT NULL DEFAULT 1,
        created_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE
    );
    """,
    # 6. ideal_customer_profiles
    """
    CREATE TABLE IF NOT EXISTS ideal_customer_profiles (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        name VARCHAR(255) NOT NULL,
        description TEXT,
        industries TEXT,  -- JSON array
        company_sizes TEXT,  -- JSON array
        decision_maker_roles TEXT,  -- JSON array
        pain_points TEXT,  -- JSON array
        desired_signals TEXT,  -- JSON array
        excluded_signals TEXT,  -- JSON array
        countries TEXT,  -- JSON array
        languages TEXT,  -- JSON array
        created_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
        UNIQUE (organization_id, id)
    );
    """,
    # 7. target_markets (Tenant Owned directly via organization_id)
    """
    CREATE TABLE IF NOT EXISTS target_markets (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        icp_id VARCHAR(36) NOT NULL,
        country VARCHAR(10) NOT NULL DEFAULT 'US',
        region VARCHAR(100),
        city VARCHAR(100),
        postal_code VARCHAR(20),
        radius_miles REAL DEFAULT 10.0,
        language VARCHAR(10) DEFAULT 'en',
        FOREIGN KEY (organization_id, icp_id) REFERENCES ideal_customer_profiles(organization_id, id) ON DELETE CASCADE
    );
    """,
    # 8. campaigns
    """
    CREATE TABLE IF NOT EXISTS campaigns (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        icp_id VARCHAR(36),
        name VARCHAR(255) NOT NULL,
        description TEXT,
        status VARCHAR(50) NOT NULL DEFAULT 'draft',
        created_at VARCHAR(50) NOT NULL,
        updated_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
        FOREIGN KEY (organization_id, icp_id) REFERENCES ideal_customer_profiles(organization_id, id) ON DELETE SET NULL,
        UNIQUE (organization_id, id)
    );
    """,
    # 9. prospects (Tenant Owned - identity decoupled from campaign)
    """
    CREATE TABLE IF NOT EXISTS prospects (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        forge_record_id VARCHAR(255),
        name VARCHAR(255) NOT NULL,
        website_url TEXT,
        phone VARCHAR(50),
        email VARCHAR(255),
        address TEXT,
        city VARCHAR(100),
        state VARCHAR(100),
        country VARCHAR(10) DEFAULT 'US',
        postal_code VARCHAR(20),
        latitude REAL,
        longitude REAL,
        industry VARCHAR(100),
        source VARCHAR(50) DEFAULT 'overture',
        source_external_id VARCHAR(255),
        created_at VARCHAR(50) NOT NULL,
        updated_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
        UNIQUE (organization_id, id)
    );
    """,
    # 10. campaign_prospects (Junction table linking Campaign and Prospect)
    """
    CREATE TABLE IF NOT EXISTS campaign_prospects (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        campaign_id VARCHAR(36) NOT NULL,
        prospect_id VARCHAR(36) NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'added',
        relevance_score REAL,
        added_at VARCHAR(50) NOT NULL,
        created_at VARCHAR(50) NOT NULL,
        updated_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id, campaign_id) REFERENCES campaigns(organization_id, id) ON DELETE CASCADE,
        FOREIGN KEY (organization_id, prospect_id) REFERENCES prospects(organization_id, id) ON DELETE CASCADE,
        UNIQUE (organization_id, campaign_id, prospect_id)
    );
    """,
    # 11. contacts (Tenant Owned directly via organization_id)
    """
    CREATE TABLE IF NOT EXISTS contacts (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        prospect_id VARCHAR(36) NOT NULL,
        name VARCHAR(255) NOT NULL,
        first_name VARCHAR(100),
        last_name VARCHAR(100),
        title VARCHAR(100),
        email VARCHAR(255),
        phone VARCHAR(50),
        linkedin_url TEXT,
        instagram_url TEXT,
        facebook_url TEXT,
        FOREIGN KEY (organization_id, prospect_id) REFERENCES prospects(organization_id, id) ON DELETE CASCADE
    );
    """,
    # 12. signals (Tenant Owned directly via organization_id)
    """
    CREATE TABLE IF NOT EXISTS signals (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        prospect_id VARCHAR(36) NOT NULL,
        type VARCHAR(100) NOT NULL,
        value TEXT,
        confidence REAL DEFAULT 1.0,
        source VARCHAR(100) DEFAULT 'web_scrape',
        evidence TEXT,
        detected_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id, prospect_id) REFERENCES prospects(organization_id, id) ON DELETE CASCADE
    );
    """,
    # 13. lead_scores (Tenant Owned directly via organization_id)
    """
    CREATE TABLE IF NOT EXISTS lead_scores (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        prospect_id VARCHAR(36) NOT NULL,
        score INTEGER NOT NULL,
        scoring_version VARCHAR(20) DEFAULT 'v1.0',
        explanation TEXT,
        created_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id, prospect_id) REFERENCES prospects(organization_id, id) ON DELETE CASCADE,
        UNIQUE (organization_id, prospect_id)
    );
    """,
    # 14. prospect_sources (Tenant Owned directly via organization_id)
    """
    CREATE TABLE IF NOT EXISTS prospect_sources (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        prospect_id VARCHAR(36) NOT NULL,
        source_type VARCHAR(50) NOT NULL,
        source_url TEXT,
        external_id VARCHAR(255),
        collected_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id, prospect_id) REFERENCES prospects(organization_id, id) ON DELETE CASCADE
    );
    """,
    # 15. research_runs (Tenant Owned directly via organization_id)
    """
    CREATE TABLE IF NOT EXISTS research_runs (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        campaign_id VARCHAR(36),
        prospect_id VARCHAR(36),
        run_type VARCHAR(100) NOT NULL,
        status VARCHAR(50) NOT NULL DEFAULT 'pending',
        started_at VARCHAR(50),
        completed_at VARCHAR(50),
        error_message TEXT,
        created_at VARCHAR(50) NOT NULL,
        updated_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
        FOREIGN KEY (organization_id, campaign_id) REFERENCES campaigns(organization_id, id) ON DELETE CASCADE,
        FOREIGN KEY (organization_id, prospect_id) REFERENCES prospects(organization_id, id) ON DELETE CASCADE
    );
    """,
    # 16. enrichment_results (Tenant Owned directly via organization_id)
    """
    CREATE TABLE IF NOT EXISTS enrichment_results (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        prospect_id VARCHAR(36) NOT NULL,
        provider VARCHAR(50) NOT NULL DEFAULT 'forge',
        status VARCHAR(50) NOT NULL DEFAULT 'success',
        website_url TEXT,
        data TEXT NOT NULL,
        started_at VARCHAR(50) NOT NULL,
        completed_at VARCHAR(50) NOT NULL,
        created_at VARCHAR(50) NOT NULL,
        updated_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id, prospect_id) REFERENCES prospects(organization_id, id) ON DELETE CASCADE,
        UNIQUE (organization_id, prospect_id, provider)
    );
    """,
    # 17. prospect_intelligence (Tenant Owned directly via organization_id)
    """
    CREATE TABLE IF NOT EXISTS prospect_intelligence (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        prospect_id VARCHAR(36) NOT NULL,
        provider VARCHAR(50) NOT NULL DEFAULT 'deterministic',
        research_version VARCHAR(20) NOT NULL DEFAULT 'v1.0',
        confidence REAL DEFAULT 1.0,
        data TEXT NOT NULL,
        created_at VARCHAR(50) NOT NULL,
        updated_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id, prospect_id) REFERENCES prospects(organization_id, id) ON DELETE CASCADE,
        UNIQUE (organization_id, prospect_id, provider)
    );
    """,
    # 18. prospect_priorities (Tenant Owned directly via organization_id)
    """
    CREATE TABLE IF NOT EXISTS prospect_priorities (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        campaign_id VARCHAR(36) NOT NULL,
        prospect_id VARCHAR(36) NOT NULL,
        priority_score INTEGER NOT NULL,
        priority_label VARCHAR(20) NOT NULL,
        lead_score_component REAL NOT NULL DEFAULT 0.0,
        intent_signal_component REAL NOT NULL DEFAULT 0.0,
        research_confidence_component REAL NOT NULL DEFAULT 0.0,
        freshness_component REAL NOT NULL DEFAULT 0.0,
        policy_version VARCHAR(20) NOT NULL DEFAULT 'v1.0',
        data TEXT NOT NULL,
        created_at VARCHAR(50) NOT NULL,
        updated_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id, campaign_id) REFERENCES campaigns(organization_id, id) ON DELETE CASCADE,
        FOREIGN KEY (organization_id, prospect_id) REFERENCES prospects(organization_id, id) ON DELETE CASCADE,
        UNIQUE (organization_id, campaign_id, prospect_id)
    );
    """,
    # 19. signal_observations (Tenant Owned directly via organization_id)
    """
    CREATE TABLE IF NOT EXISTS signal_observations (
        id VARCHAR(36) PRIMARY KEY,
        organization_id VARCHAR(36) NOT NULL,
        prospect_id VARCHAR(36) NOT NULL,
        provider VARCHAR(50) NOT NULL,
        signal_type VARCHAR(50) NOT NULL,
        category VARCHAR(50) NOT NULL,
        intent_strength VARCHAR(20) NOT NULL,
        source_type VARCHAR(50) NOT NULL,
        source_url TEXT NOT NULL,
        external_id VARCHAR(255),
        confidence REAL NOT NULL DEFAULT 1.0,
        evidence TEXT,
        raw_metadata TEXT,
        fingerprint VARCHAR(64) NOT NULL,
        published_at VARCHAR(50),
        first_seen_at VARCHAR(50) NOT NULL,
        last_seen_at VARCHAR(50) NOT NULL,
        created_at VARCHAR(50) NOT NULL,
        FOREIGN KEY (organization_id, prospect_id) REFERENCES prospects(organization_id, id) ON DELETE CASCADE,
        UNIQUE (organization_id, prospect_id, provider, fingerprint)
    );
    """,
]

# Indexes for multi-tenant isolation and performance
BOPCLIENTS_DDL_INDEXES: List[str] = [
    "CREATE INDEX IF NOT EXISTS idx_members_org ON organization_members(organization_id);",
    "CREATE INDEX IF NOT EXISTS idx_members_user ON organization_members(user_id);",
    "CREATE INDEX IF NOT EXISTS idx_services_org ON services(organization_id);",
    "CREATE INDEX IF NOT EXISTS idx_icps_org ON ideal_customer_profiles(organization_id);",
    "CREATE INDEX IF NOT EXISTS idx_target_markets_org ON target_markets(organization_id);",
    "CREATE INDEX IF NOT EXISTS idx_campaigns_org ON campaigns(organization_id);",
    "CREATE INDEX IF NOT EXISTS idx_prospects_org ON prospects(organization_id);",
    "CREATE INDEX IF NOT EXISTS idx_prospects_forge ON prospects(organization_id, forge_record_id);",
    "CREATE INDEX IF NOT EXISTS idx_prospects_website ON prospects(organization_id, website_url);",
    "CREATE INDEX IF NOT EXISTS idx_cp_org_campaign ON campaign_prospects(organization_id, campaign_id);",
    "CREATE INDEX IF NOT EXISTS idx_cp_org_prospect ON campaign_prospects(organization_id, prospect_id);",
    "CREATE INDEX IF NOT EXISTS idx_contacts_org_prospect ON contacts(organization_id, prospect_id);",
    "CREATE INDEX IF NOT EXISTS idx_signals_org_prospect ON signals(organization_id, prospect_id);",
    "CREATE INDEX IF NOT EXISTS idx_lead_scores_org_prospect ON lead_scores(organization_id, prospect_id);",
    "CREATE INDEX IF NOT EXISTS idx_sources_org_prospect ON prospect_sources(organization_id, prospect_id);",
    "CREATE INDEX IF NOT EXISTS idx_research_runs_org ON research_runs(organization_id);",
    "CREATE INDEX IF NOT EXISTS idx_research_runs_org_campaign ON research_runs(organization_id, campaign_id);",
    "CREATE INDEX IF NOT EXISTS idx_research_runs_org_prospect ON research_runs(organization_id, prospect_id);",
    "CREATE INDEX IF NOT EXISTS idx_intelligence_org_prospect ON prospect_intelligence(organization_id, prospect_id);",
    "CREATE INDEX IF NOT EXISTS idx_enrichment_results_org_prospect ON enrichment_results(organization_id, prospect_id);",
    "CREATE INDEX IF NOT EXISTS idx_priorities_org_campaign_prospect ON prospect_priorities(organization_id, campaign_id, prospect_id);",
    "CREATE INDEX IF NOT EXISTS idx_observations_org_prospect ON signal_observations(organization_id, prospect_id);",
    "CREATE INDEX IF NOT EXISTS idx_observations_fingerprint ON signal_observations(organization_id, prospect_id, fingerprint);",
]
