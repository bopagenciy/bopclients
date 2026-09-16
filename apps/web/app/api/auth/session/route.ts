import { NextRequest, NextResponse } from 'next/server';

const API_BASE_URL = process.env.BOPCLIENTS_API_URL || 'http://127.0.0.1:8100';

export async function GET(request: NextRequest) {
  let accessToken = request.cookies.get('bop_access_token')?.value;
  const sessionToken = request.cookies.get('bop_session_token')?.value;
  let activeOrgBopId = request.cookies.get('bop_active_org')?.value;

  if (!accessToken && !sessionToken) {
    return NextResponse.json({ detail: 'Unauthenticated' }, { status: 401 });
  }

  let newAccessToken: string | null = null;

  // Helper to fetch profile with token
  const fetchProfile = async (token: string) => {
    return fetch(`${API_BASE_URL}/api/v1/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: 'no-store',
    });
  };

  let meRes: Response | null = null;
  if (accessToken) {
    meRes = await fetchProfile(accessToken);
  }

  // If accessToken expired or absent, try refresh
  if ((!meRes || meRes.status === 401) && sessionToken) {
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
        meRes = await fetchProfile(newAccessToken);
      }
    }
  }

  if (!meRes || !meRes.ok) {
    return NextResponse.json({ detail: 'Session invalid or expired' }, { status: 401 });
  }

  const userData = await meRes.json();
  const orgs = userData.organizations || [];

  // Determine active organization
  let activeOrg = orgs.find((o: any) => o.bop_organization_id === activeOrgBopId);
  if (!activeOrg && orgs.length > 0) {
    activeOrg = orgs[0];
    activeOrgBopId = activeOrg.bop_organization_id;
  }

  const responsePayload = {
    user: {
      id: userData.id,
      email: userData.email,
      full_name: userData.full_name || userData.name,
      locale: userData.locale,
      is_verified: userData.is_verified,
      email_verified_at: userData.email_verified_at,
    },
    active_organization: activeOrg
      ? {
          id: activeOrg.id,
          bop_organization_id: activeOrg.bop_organization_id,
          name: activeOrg.name,
          slug: activeOrg.slug,
          role: activeOrg.role,
        }
      : null,
    active_role: activeOrg ? activeOrg.role : 'VIEWER',
    organizations: orgs.map((o: any) => ({
      id: o.id,
      bop_organization_id: o.bop_organization_id,
      name: o.name,
      slug: o.slug,
      role: o.role,
    })),
  };

  const response = NextResponse.json(responsePayload);

  // If token was refreshed, update the access token cookie
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

  // Ensure active org cookie matches
  if (activeOrgBopId) {
    const isProd = process.env.NODE_ENV === 'production';
    response.cookies.set({
      name: 'bop_active_org',
      value: activeOrgBopId,
      httpOnly: true,
      secure: isProd,
      sameSite: 'lax',
      path: '/',
      maxAge: 30 * 24 * 60 * 60,
    });
  }

  return response;
}
