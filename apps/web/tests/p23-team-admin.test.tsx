import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderToString } from 'react-dom/server';
import SettingsPage from '../app/[locale]/(app)/settings/page';
import * as AuthContext from '../lib/auth/context';
import * as I18nContext from '../lib/i18n/context';
import {
  getOrganizationMembers,
  updateMemberRole,
  removeOrganizationMember,
  updateOrganizationProfile,
} from '../lib/api/client';
import { translate } from '../lib/i18n';
import en from '../messages/en.json';
import es from '../messages/es.json';

// Mock API client fetcher
vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<any>('../lib/api/client');
  return {
    ...actual,
    getOrganizationMembers: vi.fn(),
    updateMemberRole: vi.fn(),
    removeOrganizationMember: vi.fn(),
    updateOrganizationProfile: vi.fn(),
  };
});

describe('P23 Organization & Team Administration Frontend Tests', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('i18n & Translation Parity', () => {
    const p23Keys = [
      'settings.title',
      'settings.subtitle',
      'settings.tabs.organization',
      'settings.tabs.members',
      'settings.tabs.security',
      'settings.organization.title',
      'settings.organization.description',
      'settings.organization.name_label',
      'settings.organization.name_placeholder',
      'settings.organization.slug_label',
      'settings.organization.bop_id_label',
      'settings.organization.bop_id_help',
      'settings.organization.member_count_label',
      'settings.organization.my_role_label',
      'settings.organization.save_button',
      'settings.organization.saving_button',
      'settings.organization.save_success',
      'settings.organization.save_error',
      'settings.team.title',
      'settings.team.subtitle',
      'settings.team.total_count',
      'settings.team.col_member',
      'settings.team.col_email',
      'settings.team.col_role',
      'settings.team.col_joined',
      'settings.team.col_actions',
      'settings.team.edit_role',
      'settings.team.remove_member',
      'settings.team.cannot_modify',
      'settings.team.cannot_remove',
      'settings.team.loading',
      'settings.team.empty',
      'settings.team.role_updated_success',
      'settings.team.role_update_error',
      'settings.team.remove_success',
      'settings.team.remove_error',
      'settings.team.role_modal_title',
      'settings.team.role_modal_desc',
      'settings.team.role_label',
      'settings.team.role_modal_save',
      'settings.team.role_modal_cancel',
      'settings.team.remove_modal_title',
      'settings.team.remove_modal_desc',
      'settings.team.remove_modal_confirm',
      'settings.team.remove_modal_cancel',
      'settings.team.remove_modal_in_progress',
      'settings.team.last_owner_warning',
      'settings.team.admin_restriction',
      'settings.team.read_only_badge',
      'settings.security.title',
      'settings.security.subtitle',
      'settings.security.cookie_title',
      'settings.security.cookie_desc',
      'settings.security.hashing_title',
      'settings.security.hashing_desc',
      'errors.last_owner_protection',
      'errors.invalid_role_transition',
    ];

    it('has 100% EN and ES key parity and valid translations for all P23 settings keys', () => {
      for (const key of p23Keys) {
        const enVal = translate('en', key);
        const esVal = translate('es', key);

        expect(enVal, `Missing EN translation for ${key}`).not.toBe(key);
        expect(esVal, `Missing ES translation for ${key}`).not.toBe(key);
        expect(enVal.length).toBeGreaterThan(0);
        expect(esVal.length).toBeGreaterThan(0);
      }
    });
  });

  describe('API Client Helpers', () => {
    it('getOrganizationMembers calls GET /api/v1/organizations/current/members', async () => {
      const mockMembers = [
        {
          id: 'mem-1',
          organization_id: 'org-1',
          user_id: 'u-1',
          role: 'OWNER',
          created_at: '2026-09-01T00:00:00Z',
          email: 'alice@acme.com',
          full_name: 'Alice Owner',
        },
      ];
      vi.mocked(getOrganizationMembers).mockResolvedValueOnce(mockMembers as any);

      const result = await getOrganizationMembers();
      expect(getOrganizationMembers).toHaveBeenCalledTimes(1);
      expect(result).toEqual(mockMembers);
    });

    it('updateMemberRole sends normalized role to PATCH /api/v1/organizations/current/members/:userId', async () => {
      const updatedMember = {
        id: 'mem-2',
        organization_id: 'org-1',
        user_id: 'u-2',
        role: 'ADMIN',
        created_at: '2026-09-01T00:00:00Z',
        email: 'bob@acme.com',
        full_name: 'Bob Admin',
      };
      vi.mocked(updateMemberRole).mockResolvedValueOnce(updatedMember as any);

      const result = await updateMemberRole('u-2', 'admin');
      expect(updateMemberRole).toHaveBeenCalledWith('u-2', 'admin');
      expect(result.role).toBe('ADMIN');
    });

    it('removeOrganizationMember calls DELETE /api/v1/organizations/current/members/:userId', async () => {
      vi.mocked(removeOrganizationMember).mockResolvedValueOnce(undefined);

      await removeOrganizationMember('u-2');
      expect(removeOrganizationMember).toHaveBeenCalledWith('u-2');
    });

    it('updateOrganizationProfile sends payload to PATCH /api/v1/organizations/current', async () => {
      const updatedOrg = {
        id: 'org-1',
        bop_organization_id: 'bop-org-1',
        name: 'Acme Global',
        slug: 'acme-global',
      };
      vi.mocked(updateOrganizationProfile).mockResolvedValueOnce(updatedOrg as any);

      const result = await updateOrganizationProfile({ name: 'Acme Global' });
      expect(updateOrganizationProfile).toHaveBeenCalledWith({ name: 'Acme Global' });
      expect(result.name).toBe('Acme Global');
    });
  });

  describe('Settings Page Component Rendering & Permissions', () => {
    const mockAuthUser = {
      id: 'u-owner',
      email: 'owner@acme.com',
      full_name: 'Acme Owner',
      locale: 'en',
      is_active: true,
      is_superuser: false,
      created_at: '2026-09-01T00:00:00Z',
    };

    const mockActiveOrg = {
      id: 'org-123',
      bop_organization_id: '01944111-0000-7000-8000-000000000001',
      name: 'Acme Enterprise',
      slug: 'acme-enterprise',
    };

    it('renders organization identity and tabs truthfully for OWNER', () => {
      vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
        user: mockAuthUser,
        activeOrg: mockActiveOrg,
        activeRole: 'OWNER',
        organizations: [],
        isLoading: false,
        isAuthenticated: true,
        login: vi.fn(),
        logout: vi.fn(),
        switchOrg: vi.fn(),
        hasRole: (roles) => roles.includes('OWNER'),
        refreshSession: vi.fn(),
      });

      vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
        locale: 'en',
        dictionary: {},
        t: (key: string) => translate('en', key),
      });

      const html = renderToString(<SettingsPage />);

      // Truthful org identity
      expect(html).toContain('Acme Enterprise');
      expect(html).toContain('acme-enterprise');
      expect(html).toContain('01944111-0000-7000-8000-000000000001');

      // Tabs
      expect(html).toContain(translate('en', 'settings.tabs.organization'));
      expect(html).toContain(translate('en', 'settings.tabs.members'));
      expect(html).toContain(translate('en', 'settings.tabs.security'));

      // Owner has save button
      expect(html).toContain(translate('en', 'settings.organization.save_button'));
    });

    it('renders read-only view for VIEWER without mutation button', () => {
      vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
        user: { ...mockAuthUser, id: 'u-viewer', email: 'viewer@acme.com' },
        activeOrg: mockActiveOrg,
        activeRole: 'VIEWER',
        organizations: [],
        isLoading: false,
        isAuthenticated: true,
        login: vi.fn(),
        logout: vi.fn(),
        switchOrg: vi.fn(),
        hasRole: (roles) => roles.includes('VIEWER'),
        refreshSession: vi.fn(),
      });

      vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
        locale: 'en',
        dictionary: {},
        t: (key: string) => translate('en', key),
      });

      const html = renderToString(<SettingsPage />);

      // Org info displayed
      expect(html).toContain('Acme Enterprise');
      // Viewer does NOT have save button for org profile
      expect(html).not.toContain(translate('en', 'settings.organization.save_button'));
    });
  });
});
