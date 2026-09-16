import { describe, it, expect, vi, beforeEach } from 'vitest';
import enMessages from '../messages/en.json';
import esMessages from '../messages/es.json';
import {
  getOrganizationInvitations,
  createOrganizationInvitation,
  revokeOrganizationInvitation,
  getPublicInvitation,
  acceptInvitation,
  registerAndAcceptInvitation,
} from '../lib/api/client';

describe('Phase P24: Team Invitations Frontend & Contract Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // =========================================================================
  // 1. LOCALIZATION 100% PARITY TESTS
  // =========================================================================
  describe('Localization Key Parity', () => {
    it('en.json and es.json must have complete settings.invitations parity', () => {
      const enInv = (enMessages as any).settings?.invitations;
      const esInv = (esMessages as any).settings?.invitations;

      expect(enInv).toBeDefined();
      expect(esInv).toBeDefined();

      const enKeys = Object.keys(enInv).sort();
      const esKeys = Object.keys(esInv).sort();

      expect(enKeys).toEqual(esKeys);
      expect(enKeys.length).toBeGreaterThan(15);
    });

    it('en.json and es.json must have complete invite acceptance parity', () => {
      const enInvite = (enMessages as any).invite;
      const esInvite = (esMessages as any).invite;

      expect(enInvite).toBeDefined();
      expect(esInvite).toBeDefined();

      const enKeys = Object.keys(enInvite).sort();
      const esKeys = Object.keys(esInvite).sort();

      expect(enKeys).toEqual(esKeys);
      expect(enKeys.length).toBeGreaterThan(15);
    });
  });

  // =========================================================================
  // 2. API CLIENT METHOD INTEGRATION TESTS
  // =========================================================================
  describe('Invitations API Client Helpers', () => {
    it('createOrganizationInvitation calls correct endpoint with payload', async () => {
      const mockResponse = {
        id: 'inv-123',
        organization_id: 'org-abc',
        email: 'colleague@example.com',
        role: 'member',
        status: 'pending',
        raw_token: 'secret-token-xyz',
        invite_url: '/invite/secret-token-xyz',
      };

      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 201,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockResponse,
      } as Response);

      const result = await createOrganizationInvitation({
        email: 'colleague@example.com',
        role: 'member',
      });

      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/proxy/api/v1/organizations/current/invitations',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ email: 'colleague@example.com', role: 'member' }),
        })
      );
      expect(result.id).toBe('inv-123');
      expect(result.raw_token).toBe('secret-token-xyz');
    });

    it('getOrganizationInvitations passes status_filter param when provided', async () => {
      const mockInvitations = [
        {
          id: 'inv-1',
          email: 'user1@example.com',
          role: 'member',
          status: 'pending',
        },
      ];

      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockInvitations,
      } as Response);

      const result = await getOrganizationInvitations('pending');

      expect(fetchSpy).toHaveBeenCalledWith(
        expect.stringContaining('/api/proxy/api/v1/organizations/current/invitations?status_filter=pending'),
        expect.objectContaining({ method: 'GET' })
      );
      expect(result.length).toBe(1);
    });

    it('revokeOrganizationInvitation sends DELETE request to correct invitation URL', async () => {
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 204,
        headers: new Headers(),
        json: async () => ({}),
      } as Response);

      await revokeOrganizationInvitation('inv-999');

      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/proxy/api/v1/organizations/current/invitations/inv-999',
        expect.objectContaining({ method: 'DELETE' })
      );
    });

    it('getPublicInvitation calls public token inspect endpoint', async () => {
      const mockMetadata = {
        id: 'inv-123',
        organization_name: 'Acme Corp',
        organization_slug: 'acme-corp',
        email: 'newhire@example.com',
        role: 'admin',
        status: 'pending',
        expires_at: '2026-09-25T00:00:00Z',
        is_expired: false,
      };

      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockMetadata,
      } as Response);

      const result = await getPublicInvitation('raw-token-123');

      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/proxy/api/v1/invitations/raw-token-123',
        expect.objectContaining({ method: 'GET' })
      );
      expect(result.organization_name).toBe('Acme Corp');
      expect(result.role).toBe('admin');
    });

    it('acceptInvitation sends token to /api/v1/invitations/accept', async () => {
      const mockAcceptResult = {
        membership_id: 'mem-1',
        organization_id: 'org-abc',
        organization_name: 'Acme Corp',
        organization_slug: 'acme-corp',
        user_id: 'user-789',
        role: 'member',
        accepted_at: '2026-09-16T12:00:00Z',
      };

      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockAcceptResult,
      } as Response);

      const result = await acceptInvitation('token-abc');

      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/proxy/api/v1/invitations/accept',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ token: 'token-abc' }),
        })
      );
      expect(result.membership_id).toBe('mem-1');
    });

    it('registerAndAcceptInvitation sends full payload to /register-and-accept', async () => {
      const mockRegisterResult = {
        membership_id: 'mem-2',
        organization_id: 'org-abc',
        organization_name: 'Acme Corp',
        organization_slug: 'acme-corp',
        user_id: 'new-user-1',
        role: 'viewer',
        accepted_at: '2026-09-16T12:00:00Z',
        access_token: 'jwt-access',
        refresh_token: 'jwt-refresh',
      };

      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 201,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockRegisterResult,
      } as Response);

      const payload = {
        token: 'invite-tok-xyz',
        name: 'John Doe',
        password: 'Password123!',
        locale: 'es',
      };

      const result = await registerAndAcceptInvitation(payload);

      expect(fetchSpy).toHaveBeenCalledWith(
        '/api/proxy/api/v1/invitations/register-and-accept',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify(payload),
        })
      );
      expect(result.access_token).toBe('jwt-access');
    });
  });
});
