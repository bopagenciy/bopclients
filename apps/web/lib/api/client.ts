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
import type {
  BulkAddToCampaignRequest,
  BulkAddToCampaignResponse,
  BulkRecalculateScoreRequest,
  BulkRecalculateScoreResponse,
  BulkRecalculatePriorityRequest,
  BulkRecalculatePriorityResponse,
  BulkResearchRequest,
  BulkResearchResponse,
  BulkExportRequest,
  Organization,
  OrganizationMember,
  OrganizationUpdateInput,
} from './types';

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
