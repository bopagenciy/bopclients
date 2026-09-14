export type Role = 'OWNER' | 'ADMIN' | 'MEMBER' | 'VIEWER';

export interface User {
  id: string;
  email: string;
  full_name?: string | null;
  locale?: string | null;
  is_active: boolean;
  is_superuser: boolean;
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
