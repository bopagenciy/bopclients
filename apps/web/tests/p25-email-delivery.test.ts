import { describe, it, expect, vi, beforeEach } from 'vitest';
import enMessages from '../messages/en.json';
import esMessages from '../messages/es.json';
import {
  createOrganizationInvitation,
  resendOrganizationInvitation,
} from '../lib/api/client';

describe('Phase P25: Transactional Email Delivery Foundation - Frontend Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // =========================================================================
  // 1. LOCALIZATION PARITY TESTS
  // =========================================================================
  describe('P25 Email Delivery Localization Parity', () => {
    it('en.json and es.json must have complete settings.invitations parity including P25 delivery keys', () => {
      const enInv = (enMessages as any).settings?.invitations;
      const esInv = (esMessages as any).settings?.invitations;

      expect(enInv).toBeDefined();
      expect(esInv).toBeDefined();

      const requiredP25Keys = [
        'col_delivery',
        'delivery_sent',
        'delivery_failed',
        'delivery_not_configured',
        'resend_button',
        'resending',
        'resend_success',
        'resend_error',
      ];

      for (const key of requiredP25Keys) {
        expect(enInv[key], `Missing English key: ${key}`).toBeDefined();
        expect(esInv[key], `Missing Spanish key: ${key}`).toBeDefined();
      }

      const enKeys = Object.keys(enInv).sort();
      const esKeys = Object.keys(esInv).sort();
      expect(enKeys).toEqual(esKeys);
    });
  });

  // =========================================================================
  // 2. API CLIENT METHOD INTEGRATION TESTS
  // =========================================================================
  describe('P25 Email Delivery & Resend API Client Helpers', () => {
    it('createOrganizationInvitation passes locale and returns delivery_status', async () => {
      const mockResponse = {
        id: 'inv-456',
        organization_id: 'org-abc',
        email: 'collaborator@example.com',
        role: 'member',
        status: 'pending',
        delivery_status: 'sent',
        delivery_error: null,
      };

      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 201,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockResponse,
      } as Response);

      const result = await createOrganizationInvitation({
        email: 'collaborator@example.com',
        role: 'member',
        locale: 'es',
      });

      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const [url, init] = fetchSpy.mock.calls[0];
      expect(url).toBe('/api/proxy/api/v1/organizations/current/invitations');
      expect(init?.method).toBe('POST');
      expect(JSON.parse(init?.body as string)).toEqual({
        email: 'collaborator@example.com',
        role: 'member',
        locale: 'es',
      });

      expect(result.delivery_status).toBe('sent');
      expect(result.delivery_error).toBeNull();
    });

    it('resendOrganizationInvitation calls post on resend endpoint with locale', async () => {
      const mockResponse = {
        id: 'inv-456',
        organization_id: 'org-abc',
        email: 'collaborator@example.com',
        role: 'member',
        status: 'pending',
        delivery_status: 'sent',
        delivery_error: null,
        raw_token: 'new-rotated-token-123',
      };

      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockResponse,
      } as Response);

      const result = await resendOrganizationInvitation('inv-456', 'en');

      expect(fetchSpy).toHaveBeenCalledTimes(1);
      const [url, init] = fetchSpy.mock.calls[0];
      expect(url).toBe('/api/proxy/api/v1/organizations/current/invitations/inv-456/resend');
      expect(init?.method).toBe('POST');
      expect(JSON.parse(init?.body as string)).toEqual({
        locale: 'en',
      });

      expect(result.delivery_status).toBe('sent');
      expect(result.raw_token).toBe('new-rotated-token-123');
    });

    it('resendOrganizationInvitation handles server error faithfully', async () => {
      vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
        ok: false,
        status: 410,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({
          error: {
            code: 'INVITATION_REVOKED',
            message: 'Cannot resend a revoked invitation.',
          },
        }),
      } as Response);

      await expect(resendOrganizationInvitation('inv-revoked', 'es')).rejects.toThrow();
    });
  });
});
