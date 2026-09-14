import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiClient } from '../lib/api/client';

describe('Canonical P19 Error Contract & Localization', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('should parse canonical P19 error envelope and translate message_key', async () => {
    // Mock backend 404 response with canonical P19 envelope
    const mockP19Error = {
      error: {
        code: 'RESOURCE_NOT_FOUND',
        message: 'The requested campaign was not found',
        message_key: 'errors.not_found',
        request_id: 'req-abc-123',
      },
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => mockP19Error,
    } as Response);

    try {
      await apiClient('/api/v1/campaigns/non-existent');
      expect.fail('Should have thrown ApiClientError');
    } catch (err: any) {
      expect(err.status).toBe(404);
      expect(err.code).toBe('RESOURCE_NOT_FOUND');
      expect(err.request_id).toBe('req-abc-123');
      expect(err.message_key).toBe('errors.not_found');
      // Resolved to translation: "Resource Not Found"
      expect(err.message).toBe('Resource Not Found');
    }
  });

  it('should fall back to safe error.message when message_key is unknown', async () => {
    const mockP19Error = {
      error: {
        code: 'CUSTOM_DOMAIN_ERROR',
        message: 'Specific domain constraint violation',
        message_key: 'custom.unmapped.error',
        request_id: 'req-xyz-456',
      },
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => mockP19Error,
    } as Response);

    try {
      await apiClient('/api/v1/prospects');
      expect.fail('Should have thrown ApiClientError');
    } catch (err: any) {
      expect(err.status).toBe(400);
      expect(err.message).toBe('Specific domain constraint violation');
    }
  });

  it('should support FastAPI default validation detail as secondary fallback', async () => {
    const mockFastApiError = {
      detail: 'Invalid query parameter',
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      json: async () => mockFastApiError,
    } as Response);

    try {
      await apiClient('/api/v1/prospects?page=-1');
      expect.fail('Should have thrown ApiClientError');
    } catch (err: any) {
      expect(err.status).toBe(422);
      expect(err.message).toBe('Invalid query parameter');
    }
  });
});
