import { describe, it, expect, vi, beforeEach } from 'vitest';
import enMessages from '../messages/en.json';
import esMessages from '../messages/es.json';
import openApiSchema from '../openapi_p19.json';
import {
  handoffProspectToCrm,
  getProspectCrmHandoffStatus,
  bulkProspectCrmHandoff,
} from '../lib/api/client';

describe('Phase P27: Bop CRM Handoff & Cross-App Integration - Frontend Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // =========================================================================
  // 1. LOCALIZATION PARITY TESTS
  // =========================================================================
  describe('P27 CRM Handoff Localization Parity', () => {
    it('en.json and es.json must have complete CRM handoff translation parity', () => {
      const enPD = (enMessages as any).prospect_detail;
      const esPD = (esMessages as any).prospect_detail;

      expect(enPD).toBeDefined();
      expect(esPD).toBeDefined();

      const requiredP27Keys = [
        'send_to_crm',
        'sending_to_crm',
        'crm_status_not_sent',
        'crm_status_queued',
        'crm_status_delivering',
        'crm_status_delivered',
        'crm_status_failed',
        'crm_handoff_success',
        'crm_already_sent',
        'crm_handoff_failed',
        'crm_destination_not_configured',
        'crm_handoff_info',
        'crm_retry_button',
      ];

      for (const key of requiredP27Keys) {
        expect(enPD[key], `Missing English key: prospect_detail.${key}`).toBeDefined();
        expect(esPD[key], `Missing Spanish key: prospect_detail.${key}`).toBeDefined();
      }
    });
  });

  // =========================================================================
  // 2. API CLIENT FUNCTION TESTS
  // =========================================================================
  describe('P27 CRM Handoff API Client Functions', () => {
    it('handoffProspectToCrm issues POST to /api/v1/prospects/{prospect_id}/crm-handoff', async () => {
      const mockResponse = {
        prospect_id: 'p-123',
        status: 'QUEUED',
        event_id: 'evt-uuid-456',
        correlation_id: 'corr-uuid-789',
        requested_at: '2026-09-16T12:00:00Z',
        destination_count: 1,
        is_idempotent_replay: false,
        message: 'Queued',
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockResponse,
      });

      const res = await handoffProspectToCrm('p-123');
      expect(global.fetch).toHaveBeenCalledTimes(1);

      const [url, init] = (global.fetch as any).mock.calls[0];
      expect(url).toContain('/api/proxy/api/v1/prospects/p-123/crm-handoff');
      expect(init.method).toBe('POST');
      expect(res.status).toBe('QUEUED');
      expect(res.is_idempotent_replay).toBe(false);
    });

    it('getProspectCrmHandoffStatus issues GET to /api/v1/prospects/{prospect_id}/crm-handoff', async () => {
      const mockStatus = {
        prospect_id: 'p-123',
        status: 'DELIVERED',
        event_id: 'evt-uuid-456',
        correlation_id: 'corr-uuid-789',
        requested_at: '2026-09-16T12:00:00Z',
        delivered_at: '2026-09-16T12:01:00Z',
        attempt_count: 1,
        last_error_message: null,
        destination_count: 1,
        destinations: ['dest-1'],
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockStatus,
      });

      const res = await getProspectCrmHandoffStatus('p-123');
      expect(global.fetch).toHaveBeenCalledTimes(1);

      const [url, init] = (global.fetch as any).mock.calls[0];
      expect(url).toContain('/api/proxy/api/v1/prospects/p-123/crm-handoff');
      expect(init.method).toBe('GET');
      expect(res.status).toBe('DELIVERED');
      expect(res.destination_count).toBe(1);
    });

    it('bulkProspectCrmHandoff issues POST to /api/v1/prospects/bulk/crm-handoff', async () => {
      const mockBulk = {
        requested: 2,
        queued: 2,
        already_queued_or_delivered: 0,
        failed: 0,
        errors: {},
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockBulk,
      });

      const res = await bulkProspectCrmHandoff({ prospect_ids: ['p-1', 'p-2'] });
      expect(global.fetch).toHaveBeenCalledTimes(1);

      const [url, init] = (global.fetch as any).mock.calls[0];
      expect(url).toContain('/api/proxy/api/v1/prospects/bulk/crm-handoff');
      expect(init.method).toBe('POST');
      expect(JSON.parse(init.body)).toEqual({ prospect_ids: ['p-1', 'p-2'] });
      expect(res.queued).toBe(2);
    });
  });

  // =========================================================================
  // 3. OPENAPI FIDELITY TESTS
  // =========================================================================
  describe('P27 OpenAPI Schema Fidelity', () => {
    it('OpenAPI schema includes CRM handoff endpoints', () => {
      const paths = (openApiSchema as any).paths;
      expect(paths['/api/v1/prospects/{prospect_id}/crm-handoff']).toBeDefined();
      expect(paths['/api/v1/prospects/{prospect_id}/crm-handoff'].post).toBeDefined();
      expect(paths['/api/v1/prospects/{prospect_id}/crm-handoff'].get).toBeDefined();

      expect(paths['/api/v1/prospects/bulk/crm-handoff']).toBeDefined();
      expect(paths['/api/v1/prospects/bulk/crm-handoff'].post).toBeDefined();
    });

    it('OpenAPI schema includes CrmHandoffResponse and CrmHandoffStatusResponse models', () => {
      const schemas = (openApiSchema as any).components.schemas;
      expect(schemas.CrmHandoffResponse).toBeDefined();
      expect(schemas.CrmHandoffStatusResponse).toBeDefined();
      expect(schemas.BulkCrmHandoffRequest).toBeDefined();
      expect(schemas.BulkCrmHandoffResponse).toBeDefined();
    });
  });
});
