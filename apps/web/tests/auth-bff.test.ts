import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiClient } from '../lib/api/client';

describe('Auth BFF Security Policy', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    vi.restoreAllMocks();
  });

  it('should NEVER store tokens or credentials in localStorage or sessionStorage', async () => {
    // Mock successful fetch
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: true, user: { id: 'usr-1', email: 'test@bop.com' } }),
    } as Response);

    await apiClient('/api/auth/session');

    // Assert that client-side storage was NOT touched for any auth artifacts
    expect(localStorage.getItem('token')).toBeNull();
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(localStorage.getItem('refresh_token')).toBeNull();
    expect(localStorage.getItem('bop_access_token')).toBeNull();
    expect(localStorage.getItem('bop_session_token')).toBeNull();

    expect(sessionStorage.getItem('token')).toBeNull();
    expect(sessionStorage.getItem('access_token')).toBeNull();
    expect(sessionStorage.getItem('refresh_token')).toBeNull();
    expect(sessionStorage.getItem('bop_access_token')).toBeNull();
    expect(sessionStorage.getItem('bop_session_token')).toBeNull();
  });

  it('should always include credentials in browser fetch calls', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [] }),
    } as Response);
    global.fetch = fetchSpy;

    await apiClient('/api/v1/prospects');

    expect(fetchSpy).toHaveBeenCalled();
    const callArgs = fetchSpy.mock.calls[0];
    expect(callArgs[0]).toBe('/api/proxy/api/v1/prospects');
    expect(callArgs[1]?.credentials).toBe('include');
  });
});
