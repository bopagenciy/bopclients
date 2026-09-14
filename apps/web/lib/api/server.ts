import { cookies } from 'next/headers';

const API_BASE_URL = process.env.BOPCLIENTS_API_URL || 'http://127.0.0.1:8100';

export interface BackendRequestOptions extends RequestInit {
  organizationId?: string;
  token?: string;
}

export async function fetchBackend(
  endpoint: string,
  options: BackendRequestOptions = {}
) {
  const cookieStore = cookies();
  const token = options.token || cookieStore.get('bop_access_token')?.value;
  const activeOrgId = options.organizationId || cookieStore.get('bop_active_org')?.value;

  const url = `${API_BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  if (activeOrgId) {
    headers['X-Bop-Organization-Id'] = activeOrgId;
  }

  return fetch(url, {
    ...options,
    headers,
    cache: options.cache || 'no-store',
  });
}

export function getAuthCookies() {
  const cookieStore = cookies();
  return {
    accessToken: cookieStore.get('bop_access_token')?.value,
    sessionToken: cookieStore.get('bop_session_token')?.value,
    activeOrg: cookieStore.get('bop_active_org')?.value,
  };
}
