import { NextRequest, NextResponse } from 'next/server';
import { validateSameOrigin } from '@/lib/security/csrf';

const API_BASE_URL = process.env.BOPCLIENTS_API_URL || 'http://127.0.0.1:8100';

export async function POST(request: NextRequest) {
  const csrfBlock = validateSameOrigin(request);
  if (csrfBlock) return csrfBlock;
  try {
    const accessToken = request.cookies.get('bop_access_token')?.value;
    if (!accessToken) {
      return NextResponse.json({ detail: 'Unauthenticated' }, { status: 401 });
    }

    const body = await request.json();
    const targetBopOrgId = body.bop_organization_id;

    if (!targetBopOrgId) {
      return NextResponse.json(
        { detail: 'bop_organization_id is required' },
        { status: 400 }
      );
    }

    // Verify membership via backend
    const meRes = await fetch(`${API_BASE_URL}/api/v1/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      cache: 'no-store',
    });

    if (!meRes.ok) {
      return NextResponse.json({ detail: 'Failed to verify memberships' }, { status: meRes.status });
    }

    const userData = await meRes.json();
    const orgs = userData.organizations || [];
    const targetOrg = orgs.find((o: any) => o.bop_organization_id === targetBopOrgId);

    if (!targetOrg) {
      return NextResponse.json(
        { detail: 'You are not a member of the requested organization' },
        { status: 403 }
      );
    }

    const isProd = process.env.NODE_ENV === 'production';
    const response = NextResponse.json({
      success: true,
      active_organization: targetOrg,
    });

    response.cookies.set({
      name: 'bop_active_org',
      value: targetBopOrgId,
      httpOnly: true,
      secure: isProd,
      sameSite: 'lax',
      path: '/',
      maxAge: 30 * 24 * 60 * 60,
    });

    return response;
  } catch (error: any) {
    return NextResponse.json(
      { detail: error.message || 'Failed to switch organization' },
      { status: 500 }
    );
  }
}
