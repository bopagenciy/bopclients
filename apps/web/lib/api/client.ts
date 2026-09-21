/**
 * BopClients BFF Client API Fetcher
 *
 * Security Policy:
 * 1. Zero credentials stored in localStorage or sessionStorage.
 * 2. Session and access tokens are managed strictly via HttpOnly cookies by the BFF.
 * 3. All client requests hit /api/proxy or /api/auth with credentials: 'include'.
 * 4. Consumes canonical P19 error envelope with localized message_key resolution.
 */

import { translate } from '@/lib/i18n';
import { Locale } from '@/lib/i18n/types';
import type {
  Organization,
  OrganizationMember,
  OrganizationUpdateInput,
  BulkExportRequest,
  BulkResearchRequest,
  BulkResearchResponse,
  BulkAddToCampaignRequest,
  BulkAddToCampaignResponse,
  BulkRecalculateScoreRequest,
  BulkRecalculateScoreResponse,
  BulkRecalculatePriorityRequest,
  BulkRecalculatePriorityResponse,
  OrganizationInvitation,
  InvitationCreateInput,
  InvitationResendInput,
  InvitationPublicMetadata,
  InvitationAcceptResult,
  PasswordResetRequestInput,
  PasswordResetConfirmInput,
  PasswordResetResponse,
  EmailVerificationConfirmInput,
  EmailVerificationResponse,
  EmailVerificationResendInput,
  EmailVerificationResendResponse,
  CrmHandoffResponse,
  CrmHandoffStatusResponse,
  BulkCrmHandoffRequest,
  BulkCrmHandoffResponse,
  ResearchRun,
  PaginatedResponse,
  ProspectIntelligenceResponse,
} from './types';

export interface FetchOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined>;
}

export interface ApiClientError {
  status: number;
  code?: string;
  message: string;
  message_key?: string;
  request_id?: string;
  data: any;
}

export async function apiClient<T>(
  endpoint: string,
  options: FetchOptions = {}
): Promise<T> {
  const { params, ...fetchOptions } = options;

  let url = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;

  // If calling an API route that is not /api/auth or /api/proxy, route through proxy
  if (!url.startsWith('/api/proxy') && !url.startsWith('/api/auth')) {
    url = `/api/proxy${url.startsWith('/') ? '' : '/'}${url}`;
  }

  if (params) {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) {
        searchParams.append(key, String(value));
      }
    }
    const queryString = searchParams.toString();
    if (queryString) {
      url += (url.includes('?') ? '&' : '?') + queryString;
    }
  }

  const res = await fetch(url, {
    ...fetchOptions,
    headers: {
      'Content-Type': 'application/json',
      ...fetchOptions.headers,
    },
    credentials: 'include',
  });

  if (!res.ok) {
    let errorData: any;
    try {
      errorData = await res.json();
    } catch {
      errorData = { error: { message: res.statusText } };
    }

    if (res.status === 401 && typeof window !== 'undefined') {
      // Unauthorized, redirect to login if in browser
      const pathname = window.location.pathname;
      const locale = (pathname.startsWith('/es') ? 'es' : 'en') as Locale;
      if (!pathname.includes('/login')) {
        window.location.href = `/${locale}/login?expired=true`;
      }
    }

    // Determine current locale for error translation
    let currentLocale: Locale = 'en';
    if (typeof window !== 'undefined') {
      currentLocale = window.location.pathname.startsWith('/es') ? 'es' : 'en';
    }

    // Parse Canonical P19 Error Envelope: { error: { code, message, message_key, request_id, details } }
    let parsedMessage = '';
    let parsedCode: string | undefined = undefined;
    let parsedMessageKey: string | undefined = undefined;
    let parsedRequestId: string | undefined = undefined;

    if (errorData && typeof errorData === 'object' && errorData.error) {
      const err = errorData.error;
      parsedCode = err.code;
      parsedMessageKey = err.message_key;
      parsedRequestId = err.request_id;

      // Attempt localization via message_key
      if (parsedMessageKey) {
        const localized = translate(currentLocale, parsedMessageKey);
        if (localized && localized !== parsedMessageKey) {
          parsedMessage = localized;
        }
      }

      if (!parsedMessage) {
        parsedMessage = err.message || 'An unexpected error occurred';
      }
    } else if (errorData && errorData.detail) {
      // FastAPI default validation fallback
      if (Array.isArray(errorData.detail)) {
        parsedMessage = errorData.detail.map((d: any) => d.msg || JSON.stringify(d)).join(', ');
      } else if (typeof errorData.detail === 'string') {
        parsedMessage = errorData.detail;
      } else {
        parsedMessage = JSON.stringify(errorData.detail);
      }
    } else {
      parsedMessage = res.statusText || 'API request failed';
    }

    const clientError: ApiClientError = {
      status: res.status,
      code: parsedCode,
      message: parsedMessage,
      message_key: parsedMessageKey,
      request_id: parsedRequestId,
      data: errorData,
    };

    throw clientError;
  }

  return res.json();
}

/**
 * P22 Prospect Operations & Bulk API Helpers
 */

export async function bulkAddToCampaign(
  payload: BulkAddToCampaignRequest
): Promise<BulkAddToCampaignResponse> {
  return apiClient<BulkAddToCampaignResponse>('/api/v1/prospects/bulk/add-to-campaign', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function bulkRecalculateScore(
  payload: BulkRecalculateScoreRequest
): Promise<BulkRecalculateScoreResponse> {
  return apiClient<BulkRecalculateScoreResponse>('/api/v1/prospects/bulk/recalculate-score', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function bulkRecalculatePriority(
  payload: BulkRecalculatePriorityRequest
): Promise<BulkRecalculatePriorityResponse> {
  return apiClient<BulkRecalculatePriorityResponse>('/api/v1/prospects/bulk/recalculate-priority', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function bulkResearch(
  payload: BulkResearchRequest
): Promise<BulkResearchResponse> {
  return apiClient<BulkResearchResponse>('/api/v1/prospects/bulk/research', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function exportProspectsCsv(
  filters?: Record<string, string | number | boolean | undefined>
): Promise<Blob> {
  const searchParams = new URLSearchParams();
  if (filters) {
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== '') {
        searchParams.append(key, String(value));
      }
    }
  }
  const qs = searchParams.toString();
  const url = `/api/proxy/api/v1/prospects/export${qs ? `?${qs}` : ''}`;
  const res = await fetch(url, {
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`CSV export failed with status ${res.status}`);
  }
  return res.blob();
}

export async function exportSelectedProspectsCsv(
  payload: BulkExportRequest
): Promise<Blob> {
  const url = '/api/proxy/api/v1/prospects/export';
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`CSV export failed with status ${res.status}`);
  }
  return res.blob();
}

/**
 * P23 Organization & Team Member Management API Helpers
 */
export async function getCurrentOrganization(): Promise<Organization> {
  return apiClient<Organization>('/api/v1/organizations/current', {
    method: 'GET',
  });
}

export async function updateOrganizationProfile(
  payload: OrganizationUpdateInput
): Promise<Organization> {
  return apiClient<Organization>('/api/v1/organizations/current', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
}

export async function getOrganizationMembers(): Promise<OrganizationMember[]> {
  return apiClient<OrganizationMember[]>('/api/v1/organizations/current/members', {
    method: 'GET',
  });
}

export async function updateMemberRole(
  userId: string,
  role: string
): Promise<OrganizationMember> {
  return apiClient<OrganizationMember>(`/api/v1/organizations/current/members/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify({ role: role.toLowerCase() }),
  });
}

export async function removeOrganizationMember(userId: string): Promise<void> {
  return apiClient<void>(`/api/v1/organizations/current/members/${userId}`, {
    method: 'DELETE',
  });
}

/**
 * P24 Team Invitations API Helpers
 */
export async function getOrganizationInvitations(status?: string): Promise<OrganizationInvitation[]> {
  return apiClient<OrganizationInvitation[]>('/api/v1/organizations/current/invitations', {
    method: 'GET',
    params: status ? { status_filter: status } : undefined,
  });
}

export async function createOrganizationInvitation(
  payload: InvitationCreateInput
): Promise<OrganizationInvitation> {
  return apiClient<OrganizationInvitation>('/api/v1/organizations/current/invitations', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function revokeOrganizationInvitation(invitationId: string): Promise<void> {
  return apiClient<void>(`/api/v1/organizations/current/invitations/${invitationId}`, {
    method: 'DELETE',
  });
}

export async function resendOrganizationInvitation(
  invitationId: string,
  locale?: string
): Promise<OrganizationInvitation> {
  return apiClient<OrganizationInvitation>(`/api/v1/organizations/current/invitations/${invitationId}/resend`, {
    method: 'POST',
    body: JSON.stringify({ locale: locale || 'en' }),
  });
}

export async function getPublicInvitation(token: string): Promise<InvitationPublicMetadata> {
  return apiClient<InvitationPublicMetadata>(`/api/v1/invitations/${token}`, {
    method: 'GET',
  });
}

export async function acceptInvitation(token: string): Promise<InvitationAcceptResult> {
  return apiClient<InvitationAcceptResult>('/api/v1/invitations/accept', {
    method: 'POST',
    body: JSON.stringify({ token }),
  });
}

export async function registerAndAcceptInvitation(
  payload: { token: string; name: string; password: string; locale?: string }
): Promise<InvitationAcceptResult> {
  return apiClient<InvitationAcceptResult>('/api/v1/invitations/register-and-accept', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * P26 Account Recovery & Email Verification API Helpers
 */
export async function requestPasswordReset(
  payload: PasswordResetRequestInput
): Promise<PasswordResetResponse> {
  return apiClient<PasswordResetResponse>('/api/v1/auth/password-reset/request', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function confirmPasswordReset(
  payload: PasswordResetConfirmInput
): Promise<PasswordResetResponse> {
  return apiClient<PasswordResetResponse>('/api/v1/auth/password-reset/confirm', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function confirmEmailVerification(
  payload: EmailVerificationConfirmInput
): Promise<EmailVerificationResponse> {
  return apiClient<EmailVerificationResponse>('/api/v1/auth/email-verification/confirm', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function resendEmailVerification(
  payload?: EmailVerificationResendInput
): Promise<EmailVerificationResendResponse> {
  return apiClient<EmailVerificationResendResponse>('/api/v1/auth/email-verification/resend', {
    method: 'POST',
    body: JSON.stringify(payload || {}),
  });
}

/**
 * P27 BOP CRM Handoff API Helpers
 */
export async function handoffProspectToCrm(
  prospectId: string
): Promise<CrmHandoffResponse> {
  return apiClient<CrmHandoffResponse>(`/api/v1/prospects/${prospectId}/crm-handoff`, {
    method: 'POST',
  });
}

export async function getProspectCrmHandoffStatus(
  prospectId: string
): Promise<CrmHandoffStatusResponse> {
  return apiClient<CrmHandoffStatusResponse>(`/api/v1/prospects/${prospectId}/crm-handoff`, {
    method: 'GET',
  });
}

export async function bulkProspectCrmHandoff(
  payload: BulkCrmHandoffRequest
): Promise<BulkCrmHandoffResponse> {
  return apiClient<BulkCrmHandoffResponse>('/api/v1/prospects/bulk/crm-handoff', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * P30 Prospect Research & Intelligence API Helpers
 */
export async function triggerProspectResearch(
  prospectId: string,
  payload: { campaign_id?: string; run_type?: string } = { run_type: 'full_diligence' }
): Promise<ResearchRun> {
  return apiClient<ResearchRun>(`/api/v1/prospects/${prospectId}/research`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getResearchRun(runId: string): Promise<ResearchRun> {
  return apiClient<ResearchRun>(`/api/v1/research-runs/${runId}`, {
    method: 'GET',
  });
}

export async function getProspectIntelligence(
  prospectId: string
): Promise<ProspectIntelligenceResponse> {
  return apiClient<ProspectIntelligenceResponse>(`/api/v1/prospects/${prospectId}/intelligence`, {
    method: 'GET',
  });
}

export async function listProspectResearchRuns(
  prospectId: string,
  limit: number = 10
): Promise<PaginatedResponse<ResearchRun>> {
  return apiClient<PaginatedResponse<ResearchRun>>('/api/v1/research-runs', {
    method: 'GET',
    params: {
      prospect_id: prospectId,
      page: 1,
      page_size: limit,
    },
  });
}
