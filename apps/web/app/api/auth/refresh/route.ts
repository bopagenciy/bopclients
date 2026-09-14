import { NextRequest, NextResponse } from 'next/server';

const API_BASE_URL = process.env.BOPCLIENTS_API_URL || 'http://127.0.0.1:8100';

export async function POST(request: NextRequest) {
  try {
    const sessionToken = request.cookies.get('bop_session_token')?.value;

    if (!sessionToken) {
      return NextResponse.json({ detail: 'No session token found' }, { status: 401 });
    }

    const backendRes = await fetch(`${API_BASE_URL}/api/v1/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: sessionToken }),
      cache: 'no-store',
    });

    if (!backendRes.ok) {
      const err = await backendRes.json().catch(() => ({ detail: 'Token refresh failed' }));
      return NextResponse.json(err, { status: backendRes.status });
    }

    const data = await backendRes.json();
    const isProd = process.env.NODE_ENV === 'production';

    const response = NextResponse.json({ success: true });
    response.cookies.set({
      name: 'bop_access_token',
      value: data.access_token,
      httpOnly: true,
      secure: isProd,
      sameSite: 'lax',
      path: '/',
      maxAge: data.expires_in || 3600,
    });

    return response;
  } catch (error: any) {
    return NextResponse.json(
      { detail: error.message || 'Token refresh error' },
      { status: 500 }
    );
  }
}
