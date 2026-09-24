export type Role = 'OWNER' | 'ADMIN' | 'MEMBER' | 'VIEWER';

export interface User {
  id: string;
  email: string;
  full_name?: string | null;
  locale?: string | null;
  is_active: boolean;
  is_superuser: boolean;
  email_verified_at?: string | null;
  is_verified?: boolean;
  created_at: string;
}

export interface Organization {
  id: string;
  bop_organization_id: string;
  name: string;
  slug: string;
  role?: Role;
  created_at?: string;
  updated_at?: string;
}

export interface Membership {
  id: string;
  organization_id: string;
  bop_organization_id: string;
  organization_name: string;
  user_id: string;
  role: Role;
  is_active: boolean;
}

export interface OrganizationMember {
  id: string;
  organization_id: string;
  user_id: string;
  role: Role | string;
  created_at: string;
  email?: string | null;
  full_name?: string | null;
}

export interface OrganizationUpdateInput {
  name?: string;
  description?: string;
  website?: string;
  country?: string;
  default_language?: string;
  timezone?: string;
}

export interface SessionContext {
  user: User;
  active_organization: Organization;
  active_role: Role;
  organizations: {
    id: string;
    bop_organization_id: string;
    name: string;
    slug: string;
    role: Role;
  }[];
}

export interface PaginatedResponse<T> {
  items: T[];
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
}

export interface Prospect {
  id: string;
  organization_id: string;
  name: string;
  website_url?: string | null;
  phone?: string | null;
  email?: string | null;
  address?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string;
  postal_code?: string | null;
  industry?: string | null;
  source?: string | null;
  created_at: string;
  updated_at: string;
  // P22 hydration summary fields
  lead_score?: number | null;
  priority_tier?: 'low' | 'medium' | 'high' | 'urgent' | null;
  campaign_count?: number;
  campaign_names?: string[];
  signals_count?: number;
}

export interface BulkAddToCampaignRequest {
  prospect_ids: string[];
  campaign_id: string;
}

export interface BulkAddToCampaignResponse {
  success: boolean;
  campaign_id: string;
  added_count: number;
  already_present_count: number;
  prospect_ids_added: string[];
  prospect_ids_skipped: string[];
}

export interface BulkRecalculateScoreRequest {
  prospect_ids: string[];
}

export interface BulkRecalculateScoreResponse {
  success: boolean;
  total_requested: number;
  processed_count: number;
  scored_count: number;
  failed_count: number;
  results: {
    prospect_id: string;
    score: number | null;
    status: string;
    error?: string | null;
  }[];
}

export interface BulkRecalculatePriorityRequest {
  prospect_ids: string[];
  campaign_id?: string | null;
}

export interface BulkRecalculatePriorityResponse {
  success: boolean;
  total_requested: number;
  processed_count: number;
  prioritized_count: number;
  failed_count: number;
  results: {
    prospect_id: string;
    priority_tier: string | null;
    priority_score: number | null;
    status: string;
    error?: string | null;
  }[];
}

export interface BulkResearchRequest {
  prospect_ids: string[];
  campaign_id?: string | null;
  run_type?: string;
}

export interface BulkResearchResponse {
  success: boolean;
  total_requested: number;
  triggered_count: number;
  skipped_count: number;
  runs: {
    prospect_id: string;
    run_id?: string | null;
    status: string;
    display_key?: string | null;
    reason?: string | null;
  }[];
}

export interface BulkExportRequest {
  prospect_ids?: string[];
  search?: string;
  campaign_id?: string;
  priority?: string;
  score_min?: number;
  score_max?: number;
  unscored?: boolean;
  has_signals?: boolean;
  industry?: string;
  city?: string;
  state?: string;
  country?: string;
}

export interface Campaign {
  id: string;
  organization_id: string;
  icp_id?: string | null;
  name: string;
  description?: string | null;
  status: string;
  display_key: string;
  created_at: string;
  updated_at: string;
}

export interface TargetMarket {
  id: string;
  icp_id?: string | null;
  country: string;
  region?: string | null;
  city?: string | null;
  postal_code?: string | null;
  radius_miles?: number | null;
  language: string;
}

export interface ICP {
  id: string;
  organization_id: string;
  name: string;
  description?: string | null;
  industries: string[];
  company_sizes: string[];
  decision_maker_roles: string[];
  pain_points: string[];
  desired_signals: string[];
  excluded_signals: string[];
  countries: string[];
  languages: string[];
  target_markets?: TargetMarket[];
  created_at: string;
}

export interface Signal {
  id: string;
  prospect_id: string;
  category: string;
  display_key: string;
  signal_type: string;
  confidence: number;
  headline: string;
  summary?: string | null;
  source_url?: string | null;
  detected_at: string;
  created_at: string;
}

export interface ResearchRun {
  id: string;
  organization_id: string;
  prospect_id?: string | null;
  campaign_id?: string | null;
  run_type?: string | null;
  status: string;
  display_key: string;
  started_at?: string | null;
  completed_at?: string | null;
  error_message?: string | null;
  created_at: string;
}

export interface MonitoringOverview {
  organization_id: string;
  total_schedules: number;
  active_schedules: number;
  paused_schedules: number;
  failing_schedules: number;
}

export interface MonitoringHealth {
  status: string;
  organization_id: string;
  active_monitors: number;
  degraded_monitors: number;
}

export interface Destination {
  id: string;
  bop_organization_id: string;
  target_app_id: string;
  destination_name: string;
  transport_type: string;
  endpoint_url: string;
  secret_key_ref?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ApiError {
  detail?: string | { message: string; code?: string };
  code?: string;
  status?: number;
}

export interface SearchIntent {
  organization_id: string;
  campaign_id?: string | null;
  target_market_id?: string | null;
  raw_query: string;
  industries: string[];
  business_categories: string[];
  countries: string[];
  regions: string[];
  cities: string[];
  radius_miles?: number | null;
  languages: string[];
  company_size_min?: number | null;
  company_size_max?: number | null;
  company_sizes?: string[];
  decision_maker_roles: string[];
  keywords: string[];
  negative_keywords?: string[];
  services_to_offer: string[];
  desired_signals: string[];
  max_results: number;
}

export interface DiscoveryTask {
  task_id: string;
  provider: string;
  query_params: Record<string, any>;
  priority: number;
  status: string;
  estimated_items?: number | null;
}

export interface SearchPlan {
  organization_id: string;
  campaign_id?: string | null;
  tasks: DiscoveryTask[];
  warnings: string[];
  estimated_total_cost_credits: number;
  generated_at: string;
}

export interface DiscoveredProspectSummary {
  id: string;
  name: string;
  website_url?: string | null;
  phone?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  industry?: string | null;
  source?: string | null;
}

export interface DiscoveryExecutionResult {
  status: 'completed' | 'partial' | 'failed';
  campaign_id: string;
  tasks_executed: number;
  tasks_succeeded: number;
  tasks_failed: number;
  discovered_businesses_count: number;
  prospects_created: number;
  prospects_reused: number;
  total_imported_prospects: number;
  imported_prospects: DiscoveredProspectSummary[];
  errors: string[];
}

export interface DiscoveryCandidateSummary {
  candidate_id: string;
  name: string;
  website_url?: string | null;
  category?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  geographic_scope?: string | null;
  classification_status?: string | null;
  classification_details?: Record<string, any> | null;
  title?: string | null;
  snippet?: string | null;
  source?: string | null;
  // Structured Candidate Qualification
  qualification_status?: 'SEARCH_MATCH' | 'READY_FOR_COMMERCIAL_REVIEW' | 'INSUFFICIENT_EVIDENCE' | 'REJECTED' | string | null;
  entity_archetype?: string | null;
  geographic_evidence_status?: string | null;
  current_activity_status?: string | null;
  source_url?: string | null;
  source_host?: string | null;
  organization_website?: string | null;
  is_commercial_review_ready?: boolean | null;
  qualification_reasons?: string[] | null;
  missing_evidence?: string[] | null;
}

export interface DiscoveryPreviewRequest {
  campaign_id?: string | null;
  raw_query?: string | null;
  search_plan?: SearchPlan | null;
  provider?: string;
}

export interface DiscoveryPreviewDiagnostics {
  provider_results_received: number;
  results_missing_required_fields: number;
  results_rejected_by_classifier: number;
  results_accepted_by_classifier: number;
  directory_candidates_retained: number;
  candidates_returned_to_preview: number;
  rejection_reasons?: Record<string, number>;
}

export interface DiscoveryPreviewResponse {
  status: 'completed' | 'partial' | 'failed' | string;
  organization_id: string;
  campaign_id?: string | null;
  provider: string;
  tasks_executed: number;
  candidates_count: number;
  candidates: DiscoveryCandidateSummary[];
  prospects_inserted: number;
  sources_inserted: number;
  database_writes: number;
  warnings: string[];
  errors: string[];
  diagnostics?: DiscoveryPreviewDiagnostics | null;
}

export interface LeadScoreDetail {
  prospect_id: string;
  organization_id: string;
  score: number | null;
  explanation?: string | null;
  confidence?: number | null;
  components?: Record<string, any> | null;
  calculated_at?: string | null;
}

export interface PriorityDetail {
  prospect_id: string;
  organization_id: string;
  campaign_id?: string | null;
  tier: 'low' | 'medium' | 'high' | 'urgent' | null;
  score: number | null;
  reasons: string[];
  lead_score_component?: number | null;
  intent_signal_component?: number | null;
  research_confidence_component?: number | null;
  freshness_component?: number | null;
  updated_at?: string | null;
}

export interface CampaignProspectItem {
  id: string;
  organization_id: string;
  campaign_id: string;
  prospect_id: string;
  name: string;
  website_url?: string | null;
  phone?: string | null;
  email?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  industry?: string | null;
  source?: string | null;
  status: string;
  priority?: number;
  added_at: string;
}

export interface ProspectDetail {
  prospect: Prospect;
  campaign_associations: {
    id: string;
    campaign_id: string;
    campaign_name?: string | null;
    status: string;
    priority?: number;
    added_at: string;
  }[];
  lead_score?: {
    score: number;
    confidence?: number | null;
    components?: Record<string, any> | null;
    calculated_at: string;
  } | null;
  priority?: {
    tier: 'low' | 'medium' | 'high' | 'urgent' | string;
    score: number;
    reasons: string[];
    updated_at: string;
  } | null;
  intelligence_summary?: {
    summary_text?: string | null;
    key_insights?: string[];
    recommended_angle?: string | null;
    generated_at?: string;
  } | null;
  recent_signals: {
    id: string;
    category: string;
    display_key: string;
    signal_type: string;
    confidence: number;
    headline: string;
    detected_at: string;
  }[];
  monitoring_schedule?: {
    id: string;
    status: string;
    next_check_at?: string;
    last_check_at?: string;
    recommended_interval_days?: number;
  } | null;
}

export interface OrganizationInvitation {
  id: string;
  organization_id: string;
  email: string;
  role: Role | string;
  status: 'pending' | 'accepted' | 'revoked' | 'expired' | string;
  invited_by_user_id: string;
  expires_at: string;
  created_at: string;
  accepted_at?: string | null;
  revoked_at?: string | null;
  delivery_status?: 'sent' | 'failed' | 'not_configured' | string;
  delivery_error?: string | null;
  raw_token?: string | null;
  invite_url?: string | null;
}

export interface InvitationCreateInput {
  email: string;
  role?: string;
  locale?: string;
}

export interface InvitationResendInput {
  locale?: string;
}

export interface InvitationPublicMetadata {
  id: string;
  organization_name: string;
  organization_slug: string;
  email: string;
  role: string;
  status: string;
  expires_at: string;
  is_expired: boolean;
}

export interface InvitationAcceptResult {
  membership_id: string;
  organization_id: string;
  organization_name: string;
  organization_slug: string;
  user_id: string;
  role: string;
  accepted_at: string;
  access_token?: string | null;
  refresh_token?: string | null;
  token_type?: string | null;
  expires_in?: number | null;
}

export interface PasswordResetRequestInput {
  email: string;
  locale?: string;
}

export interface PasswordResetConfirmInput {
  token: string;
  new_password: string;
}

export interface PasswordResetResponse {
  success: boolean;
  message: string;
}

export interface EmailVerificationConfirmInput {
  token: string;
}

export interface EmailVerificationResponse {
  success: boolean;
  message: string;
  user?: User;
}

export interface EmailVerificationResendInput {
  locale?: string;
}

export interface EmailVerificationResendResponse {
  success: boolean;
  message: string;
}

export type CrmHandoffState = 'NOT_SENT' | 'QUEUED' | 'DELIVERING' | 'DELIVERED' | 'FAILED';

export interface CrmHandoffResponse {
  prospect_id: string;
  status: CrmHandoffState;
  event_id: string;
  correlation_id: string;
  requested_at: string;
  destination_count: number;
  is_idempotent_replay: boolean;
  message: string;
}

export interface CrmHandoffStatusResponse {
  prospect_id: string;
  status: CrmHandoffState;
  event_id?: string | null;
  correlation_id?: string | null;
  requested_at?: string | null;
  delivered_at?: string | null;
  attempt_count: number;
  last_error_message?: string | null;
  destination_count: number;
  destinations: string[];
}

export interface BulkCrmHandoffRequest {
  prospect_ids: string[];
}

export interface BulkCrmHandoffResponse {
  requested: number;
  queued: number;
  already_queued_or_delivered: number;
  failed: number;
  errors: Record<string, string>;
}

export interface ResearchClaim {
  id: string;
  claim_type: string;
  statement: string;
  classification: 'observed' | 'derived' | 'inferred' | string;
  confidence: number;
  evidence_refs?: string[];
  source_refs?: string[];
}

export interface CommercialOpportunity {
  opportunity_type: string;
  title: string;
  description: string;
  confidence: number;
  supporting_signals?: string[];
  supporting_claims?: string[];
  matched_services?: string[];
  priority?: 'low' | 'medium' | 'high' | 'urgent' | string;
}

export interface ProspectIntelligenceData {
  executive_summary?: string;
  business_profile?: Record<string, any>;
  claims?: ResearchClaim[];
  commercial_opportunities?: CommercialOpportunity[];
  risks?: string[];
  unknowns?: string[];
  usage_metadata?: Record<string, any> | null;
  ai_provider?: string;
  ai_model?: string;
  api_mode?: string;
  prompt_version?: string;
  research_version?: string;
  generated_from?: {
    enrichment_updated_at?: string | null;
    signals_latest_at?: string | null;
    active_signals_fingerprint?: string;
    lead_score_fingerprint?: string;
    active_services_fingerprint?: string;
    services_count?: number;
  };
}

export interface ProspectIntelligenceResponse {
  prospect_id: string;
  organization_id: string;
  intelligence: ProspectIntelligenceData | null;
  confidence?: number | null;
  research_version?: string | null;
}
