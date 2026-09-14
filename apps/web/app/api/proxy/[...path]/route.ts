import { NextRequest, NextResponse } from 'next/server';
import { validateSameOrigin } from '@/lib/security/csrf';

const API_BASE_URL = process.env.BOPCLIENTS_API_URL || 'http://127.0.0.1:8100';

async function forwardRequest(request: NextRequest, { params }: { params: { path: string[] } }) {
  // 1. CSRF Protection: Validate same-origin for all mutating methods (POST, PUT, PATCH, DELETE)
  const csrfBlock = validateSameOrigin(request);
  if (csrfBlock) {
    return csrfBlock;
  }

  // 2. Read authoritative credentials exclusively from server-managed HttpOnly cookies
  let accessToken = request.cookies.get('bop_access_token')?.value;
  const sessionToken = request.cookies.get('bop_session_token')?.value;
  const activeOrgId = request.cookies.get('bop_active_org')?.value;

  const pathSegments = params.path || [];
  // Security: Reject empty paths, path traversal, or attempts to abuse path segments
  for (const seg of pathSegments) {
    if (seg === '..' || seg === '.' || seg.includes('/') || seg.includes('\\')) {
      return NextResponse.json(
        { error: { code: 'INVALID_PATH', message: 'Invalid path segment in proxy request' } },
        { status: 400 }
      );
    }
  }

  const pathStr = pathSegments.join('/');
  // Security: Strictly enforce relative API path under configured BOPCLIENTS_API_URL
  if (pathStr.startsWith('http:') || pathStr.startsWith('https:') || pathStr.startsWith('//')) {
    return NextResponse.json(
      { error: { code: 'INVALID_PROXY_TARGET', message: 'Open proxy target rejected' } },
      { status: 400 }
    );
  }

  const backendPath = pathStr.startsWith('api/v1')
    ? `/${pathStr}`
    : `/api/v1/${pathStr}`;

  const search = request.nextUrl.search;
  // Construct destination URL strictly bound to configured API_BASE_URL
  const targetUrl = new URL(`${backendPath}${search}`, API_BASE_URL).toString();

  const method = request.method;
  let body: any = undefined;
  if (method !== 'GET' && method !== 'HEAD') {
    try {
      body = await request.text();
    } catch {
      // No body
    }
  }

  // 3. Strict Header Allowlist: Strip client-supplied Authorization and Tenant headers
  const buildHeaders = (token?: string) => {
    const headers: Record<string, string> = {
      'Content-Type': request.headers.get('content-type') || 'application/json',
      'Accept': request.headers.get('accept') || 'application/json',
    };
    // Authoritative token from server cookie only
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    // Authoritative tenant ID from validated session cookie only
    if (activeOrgId) {
      headers['X-Bop-Organization-Id'] = activeOrgId;
    }
    return headers;
  };

  let backendRes = await fetch(targetUrl, {
    method,
    headers: buildHeaders(accessToken),
    body,
    cache: 'no-store',
  });

  let newAccessToken: string | null = null;

  // Auto-refresh token if 401 and session token exists
  if (backendRes.status === 401 && sessionToken) {
    const refreshRes = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: sessionToken }),
      cache: 'no-store',
    });

    if (refreshRes.ok) {
      const refreshData = await refreshRes.json();
      newAccessToken = refreshData.access_token;
      if (newAccessToken) {
        backendRes = await fetch(targetUrl, {
          method,
          headers: buildHeaders(newAccessToken),
          body,
          cache: 'no-store',
        });
      }
    }
  }

  const resBody = await backendRes.text();
  const response = new NextResponse(resBody, {
    status: backendRes.status,
    headers: {
      'Content-Type': backendRes.headers.get('content-type') || 'application/json',
    },
  });

  if (newAccessToken) {
    const isProd = process.env.NODE_ENV === 'production';
    response.cookies.set({
      name: 'bop_access_token',
      value: newAccessToken,
      httpOnly: true,
      secure: isProd,
      sameSite: 'lax',
      path: '/',
      maxAge: 3600,
    });
  }

  return response;
}

export const GET = forwardRequest;
export const POST = forwardRequest;
export const PUT = forwardRequest;
export const PATCH = forwardRequest;
export const DELETE = forwardRequest;
