import { NextRequest, NextResponse } from 'next/server';

const API_BASE_URL = process.env.BOPCLIENTS_API_URL || 'http://127.0.0.1:8100';

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { email, password } = body;

    if (!email || !password) {
      return NextResponse.json(
        { detail: 'Email and password are required' },
        { status: 400 }
      );
    }

    // Call backend login
    const backendRes = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
      cache: 'no-store',
    });

    if (!backendRes.ok) {
      const err = await backendRes.json().catch(() => ({ detail: 'Authentication failed' }));
      return NextResponse.json(err, { status: backendRes.status });
    }

    const data = await backendRes.json();
    const accessToken = data.access_token;
    const refreshToken = data.refresh_token;

    // Fetch user organizations using this access token
    let organizations: any[] = [];
    let activeOrg: any = null;

    try {
      const orgsRes = await fetch(`${API_BASE_URL}/api/v1/me/organizations`, {
        headers: {
          Authorization: `Bearer ${accessToken}`,
        },
        cache: 'no-store',
      });
      if (orgsRes.ok) {
        const orgsData = await orgsRes.json();
        organizations = orgsData.items || [];
        if (organizations.length > 0) {
          activeOrg = organizations[0];
        }
      }
    } catch {
      // Ignore org lookup errors during login
    }

    const isProd = process.env.NODE_ENV === 'production';
    const response = NextResponse.json({
      success: true,
      user: {
        id: data.user_id,
        email: data.email,
        full_name: data.full_name,
        locale: data.locale,
        is_verified: data.user?.is_verified ?? data.is_verified,
        email_verified_at: data.user?.email_verified_at ?? data.email_verified_at,
      },
      active_organization: activeOrg
        ? {
            id: activeOrg.organization_id,
            bop_organization_id: activeOrg.bop_organization_id,
            name: activeOrg.organization_name,
            slug: activeOrg.organization_slug,
            role: activeOrg.role,
          }
        : null,
      organizations: organizations.map((o) => ({
        id: o.organization_id,
        bop_organization_id: o.bop_organization_id,
        name: o.organization_name,
        slug: o.organization_slug,
        role: o.role,
      })),
    });

    // Set secure HttpOnly cookies
    response.cookies.set({
      name: 'bop_access_token',
      value: accessToken,
      httpOnly: true,
      secure: isProd,
      sameSite: 'lax',
      path: '/',
      maxAge: data.expires_in || 3600,
    });

    response.cookies.set({
      name: 'bop_session_token',
      value: refreshToken,
      httpOnly: true,
      secure: isProd,
      sameSite: 'lax',
      path: '/',
      maxAge: 30 * 24 * 60 * 60, // 30 days
    });

    if (activeOrg) {
      response.cookies.set({
        name: 'bop_active_org',
        value: activeOrg.bop_organization_id,
        httpOnly: true,
        secure: isProd,
        sameSite: 'lax',
        path: '/',
        maxAge: 30 * 24 * 60 * 60,
      });
    }

    return response;
  } catch (error: any) {
    return NextResponse.json(
      { detail: error.message || 'Internal server error' },
      { status: 500 }
    );
  }
}
