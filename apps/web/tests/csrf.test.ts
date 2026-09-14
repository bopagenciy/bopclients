import { describe, it, expect } from 'vitest';
import { NextRequest } from 'next/server';
import { validateSameOrigin } from '../lib/security/csrf';

describe('BFF CSRF Same-Origin Security', () => {
  it('should accept safe read-only methods (GET, HEAD) regardless of origin', () => {
    const req = new NextRequest('http://localhost:3000/api/proxy/api/v1/prospects', {
      method: 'GET',
      headers: {
        origin: 'https://attacker.com',
      },
    });

    const result = validateSameOrigin(req);
    expect(result).toBeNull(); // Allowed
  });

  it('should accept state-changing methods (POST, PUT, DELETE) from same origin', () => {
    const req = new NextRequest('http://localhost:3000/api/proxy/api/v1/campaigns', {
      method: 'POST',
      headers: {
        origin: 'http://localhost:3000',
      },
    });

    const result = validateSameOrigin(req);
    expect(result).toBeNull(); // Allowed
  });

  it('should reject state-changing methods from foreign cross-origin with 403', async () => {
    const req = new NextRequest('http://localhost:3000/api/proxy/api/v1/campaigns', {
      method: 'POST',
      headers: {
        origin: 'https://evil-site.com',
      },
    });

    const response = validateSameOrigin(req);
    expect(response).not.toBeNull();
    expect(response?.status).toBe(403);

    const body = await response?.json();
    expect(body.error.code).toBe('CSRF_REJECTED');
  });

  it('should reject state-changing methods when origin and referer are completely absent', async () => {
    const req = new NextRequest('http://localhost:3000/api/auth/switch-org', {
      method: 'POST',
    });

    const response = validateSameOrigin(req);
    expect(response).not.toBeNull();
    expect(response?.status).toBe(403);
  });
});
