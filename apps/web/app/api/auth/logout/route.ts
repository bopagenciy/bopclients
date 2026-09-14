import { NextRequest, NextResponse } from 'next/server';
import { validateSameOrigin } from '@/lib/security/csrf';

const API_BASE_URL = process.env.BOPCLIENTS_API_URL || 'http://127.0.0.1:8100';

export async function POST(request: NextRequest) {
  const csrfBlock = validateSameOrigin(request);
  if (csrfBlock) return csrfBlock;
  try {
    const accessToken = request.cookies.get('bop_access_token')?.value;
    const sessionToken = request.cookies.get('bop_session_token')?.value;

    // Best-effort backend session revocation
    if (accessToken || sessionToken) {
      try {
        await fetch(`${API_BASE_URL}/api/v1/auth/logout`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
          },
          body: sessionToken ? JSON.stringify({ refresh_token: sessionToken }) : undefined,
          cache: 'no-store',
        });
      } catch {
        // Continue clearing cookies even if backend call fails
      }
    }

    const response = NextResponse.json({ success: true });

    // Clear all auth cookies
    response.cookies.set({
      name: 'bop_access_token',
      value: '',
      httpOnly: true,
      path: '/',
      maxAge: 0,
    });

    response.cookies.set({
      name: 'bop_session_token',
      value: '',
      httpOnly: true,
      path: '/',
      maxAge: 0,
    });

    response.cookies.set({
      name: 'bop_active_org',
      value: '',
      httpOnly: true,
      path: '/',
      maxAge: 0,
    });

    return response;
  } catch (error: any) {
    return NextResponse.json(
      { detail: error.message || 'Logout failed' },
      { status: 500 }
    );
  }
}
