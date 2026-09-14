import { NextRequest, NextResponse } from 'next/server';

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

/**
 * Validates that state-changing requests originate from the same frontend application origin.
 * Rejects cross-origin requests with HTTP 403.
 */
export function validateSameOrigin(request: NextRequest): NextResponse | null {
  if (SAFE_METHODS.has(request.method.toUpperCase())) {
    return null; // Safe methods do not mutate state
  }

  const originHeader = request.headers.get('origin');
  const refererHeader = request.headers.get('referer');

  // Determine allowed origins from explicit server-side app origin configuration
  const serverOrigin = request.nextUrl.origin;
  const configuredAppUrl = process.env.BOPCLIENTS_APP_URL || process.env.NEXT_PUBLIC_APP_URL;
  const configuredOrigins = process.env.ALLOWED_ORIGINS
    ? process.env.ALLOWED_ORIGINS.split(',').map((o) => o.trim())
    : [];

  const allowedOrigins = new Set([
    serverOrigin,
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost:3100',
    'http://127.0.0.1:3100',
    ...(configuredAppUrl ? [new URL(configuredAppUrl).origin] : []),
    ...configuredOrigins,
  ]);

  let requestOrigin = originHeader;

  // Fallback to Referer if Origin is absent
  if (!requestOrigin && refererHeader) {
    try {
      requestOrigin = new URL(refererHeader).origin;
    } catch {
      requestOrigin = null;
    }
  }

  // If origin is missing on a mutation or not in allowed list, reject with 403
  if (!requestOrigin || !allowedOrigins.has(requestOrigin)) {
    return NextResponse.json(
      {
        error: {
          code: 'CSRF_REJECTED',
          message: 'Cross-origin mutation request rejected by BFF Same-Origin Policy',
          message_key: 'errors.forbidden',
        },
      },
      { status: 403 }
    );
  }

  return null;
}
