import { describe, it, expect, vi, beforeEach } from 'vitest';
import enMessages from '../messages/en.json';
import esMessages from '../messages/es.json';
import {
  requestPasswordReset,
  confirmPasswordReset,
  confirmEmailVerification,
  resendEmailVerification,
} from '../lib/api/client';

describe('Phase P26: Account Recovery & Email Verification - Frontend Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // =========================================================================
  // 1. LOCALIZATION PARITY TESTS
  // =========================================================================
  describe('P26 Account Recovery Localization Parity', () => {
    it('en.json and es.json must have complete auth recovery & verification parity', () => {
      const enAuth = (enMessages as any).auth;
      const esAuth = (esMessages as any).auth;

      expect(enAuth).toBeDefined();
      expect(esAuth).toBeDefined();

      const requiredP26Keys = [
        'forgot_password_link',
        'forgot_password_title',
        'forgot_password_subtitle',
        'send_reset_link',
        'sending_reset_link',
        'reset_link_sent',
        'back_to_login',
        'reset_password_title',
        'reset_password_subtitle',
        'new_password_label',
        'confirm_password_label',
        'passwords_do_not_match',
        'password_min_length',
        'reset_password_button',
        'resetting_password',
        'password_reset_success',
        'invalid_or_expired_token',
        'verify_email_title',
        'verifying_email',
        'email_verified_success',
        'email_verification_failed',
        'unverified_email_banner',
        'resend_verification',
        'resending_verification',
        'verification_email_sent',
      ];

      for (const key of requiredP26Keys) {
        expect(enAuth[key], `Missing English key: auth.${key}`).toBeDefined();
        expect(esAuth[key], `Missing Spanish key: auth.${key}`).toBeDefined();
      }

      const enKeys = Object.keys(enAuth).sort();
      const esKeys = Object.keys(esAuth).sort();
      expect(enKeys).toEqual(esKeys);
    });
  });

  // =========================================================================
  // 2. API CLIENT METHOD INTEGRATION TESTS
  // =========================================================================
  describe('P26 API Client Helpers', () => {
    it('requestPasswordReset calls /api/v1/auth/password-reset/request', async () => {
      const mockResponse = {
        success: true,
        message: 'If the email is registered, you will receive reset instructions.',
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockResponse,
      } as Response);

      const result = await requestPasswordReset({
        email: 'user@example.com',
        locale: 'es',
      });

      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [url, init] = (global.fetch as any).mock.calls[0];
      expect(url).toBe('/api/proxy/api/v1/auth/password-reset/request');
      expect(init.method).toBe('POST');
      expect(JSON.parse(init.body)).toEqual({
        email: 'user@example.com',
        locale: 'es',
      });
      expect(result).toEqual(mockResponse);
    });

    it('confirmPasswordReset calls /api/v1/auth/password-reset/confirm', async () => {
      const mockResponse = {
        success: true,
        message: 'Password reset successfully.',
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockResponse,
      } as Response);

      const result = await confirmPasswordReset({
        token: 'raw-secret-token-xyz',
        new_password: 'NewStrongPassword123!',
      });

      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [url, init] = (global.fetch as any).mock.calls[0];
      expect(url).toBe('/api/proxy/api/v1/auth/password-reset/confirm');
      expect(init.method).toBe('POST');
      expect(JSON.parse(init.body)).toEqual({
        token: 'raw-secret-token-xyz',
        new_password: 'NewStrongPassword123!',
      });
      expect(result).toEqual(mockResponse);
    });

    it('confirmEmailVerification calls /api/v1/auth/email-verification/confirm', async () => {
      const mockResponse = {
        success: true,
        message: 'Email address verified successfully.',
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockResponse,
      } as Response);

      const result = await confirmEmailVerification({
        token: 'verify-token-abc',
      });

      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [url, init] = (global.fetch as any).mock.calls[0];
      expect(url).toBe('/api/proxy/api/v1/auth/email-verification/confirm');
      expect(init.method).toBe('POST');
      expect(JSON.parse(init.body)).toEqual({
        token: 'verify-token-abc',
      });
      expect(result).toEqual(mockResponse);
    });

    it('resendEmailVerification calls /api/v1/auth/email-verification/resend', async () => {
      const mockResponse = {
        success: true,
        message: 'Verification email sent.',
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockResponse,
      } as Response);

      const result = await resendEmailVerification({
        locale: 'es',
      });

      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [url, init] = (global.fetch as any).mock.calls[0];
      expect(url).toBe('/api/proxy/api/v1/auth/email-verification/resend');
      expect(init.method).toBe('POST');
      expect(JSON.parse(init.body)).toEqual({
        locale: 'es',
      });
      expect(result).toEqual(mockResponse);
    });
  });
});
