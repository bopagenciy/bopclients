import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import * as ReactDOMClient from 'react-dom/client';

// @ts-ignore
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

import DiscoveryPage from '../app/[locale]/(app)/discovery/page';
import * as AuthContext from '../lib/auth/context';
import * as I18nContext from '../lib/i18n/context';
import { translate } from '../lib/i18n';
import enMessages from '../messages/en.json';
import esMessages from '../messages/es.json';
import type { DiscoveryPreviewResponse } from '../lib/api/types';

// Mock Next.js navigation
const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/es/discovery',
}));

function setInputValue(el: HTMLInputElement | HTMLTextAreaElement, value: string) {
  const prototype = el instanceof HTMLInputElement ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype;
  const nativeSetter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
  if (nativeSetter) {
    nativeSetter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
}

describe('Phase P30.5G.5H.5D: Cross-Source Entity Bundling UI Test Suite', () => {
  let container: HTMLDivElement;
  let root: ReactDOMClient.Root;

  const mockAuthUser = {
    id: 'user-bop-1',
    email: 'admin@bopagencia.local',
    full_name: 'Admin Bop Agencia',
    locale: 'es',
    is_active: true,
    is_superuser: false,
    created_at: '2026-09-01T00:00:00Z',
  };

  const mockActiveOrg = {
    id: 'org-7a656f63',
    bop_organization_id: '7a656f63-4344-4b21-97a9-f0bee5d451b3',
    name: 'Bop Agencia',
    slug: 'bop-agencia',
    role: 'ADMIN',
  };

  const mockCampaigns = [
    {
      id: 'camp-cali-1',
      name: 'Prospección de Asociaciones Médicas — Cali',
      description: 'Campaña piloto para agremiaciones médicas en Cali',
      status: 'active',
      created_at: '2026-09-15T00:00:00Z',
    },
  ];

  const mockBundledPreviewResponse: DiscoveryPreviewResponse = {
    status: 'completed',
    organization_id: mockActiveOrg.bop_organization_id,
    campaign_id: mockCampaigns[0].id,
    provider: 'web_search',
    tasks_executed: 2,
    candidates_count: 1,
    candidates: [
      {
        candidate_id: 'web-239bd54f7e1a546c',
        name: 'Asociación Colombiana de Sociedades Científicas',
        category: 'medical_association',
        city: null,
        state: null,
        country: 'CO',
        geographic_scope: 'NATIONAL_SCOPE',
        classification_status: 'ACCEPTED_CANDIDATE',
        classification_details: {
          target_intent: 'medical_association',
          name: 'Asociación Colombiana de Sociedades Científicas',
          sector: 'association',
        },
        title: 'Asociación Colombiana de Sociedades Científicas',
        snippet: 'Federación médica científica en Colombia.',
        source: 'web_search',
        qualification_status: 'SEARCH_MATCH',
        entity_archetype: 'PROFESSIONAL_ASSOCIATION',
        geographic_evidence_status: 'LOCATION_UNVERIFIED',
        current_activity_status: 'CURRENT_STATUS_UNKNOWN',
        source_url: 'https://sociedadescientificas.com',
        source_host: 'sociedadescientificas.com',
        organization_website: 'https://sociedadescientificas.com',
        is_commercial_review_ready: false,
        qualification_reasons: ['COMPATIBLE_ENTITY_ARCHETYPE'],
        missing_evidence: ['LOCATION_UNVERIFIED_FOR_TARGET_CITY'],
        sources_count: 3,
        sources: [
          {
            source_url: 'https://sociedadescientificas.com',
            source_host: 'sociedadescientificas.com',
            source_type: 'OFFICIAL_WEBSITE',
            platform: null,
            title: 'Asociación Colombiana de Sociedades Científicas',
            snippet: 'Sitio oficial de la asociación.',
          },
          {
            source_url: 'https://facebook.com/sociedadescientificas',
            source_host: 'facebook.com',
            source_type: 'SOCIAL_PROFILE',
            platform: 'facebook.com',
            title: 'Asociación Colombiana de Sociedades Científicas - Inicio',
            snippet: 'Canal en Facebook.',
          },
          {
            source_url: 'https://x.com/acsc_colombia',
            source_host: 'x.com',
            source_type: 'SOCIAL_PROFILE',
            platform: 'x.com',
            title: 'Asociación Colombiana de Sociedades Científicas (@acsc_colombia)',
            snippet: 'Canal oficial en X.',
          },
        ],
      },
    ],
    executed_query: 'asociaciones médicas Cali',
    executed_queries: [
      'asociaciones médicas Cali',
      'sociedades científicas Cali',
    ],
    diagnostics: {
      provider_results_received: 10,
      results_missing_required_fields: 0,
      results_rejected_by_classifier: 4,
      results_accepted_by_classifier: 6,
      directory_candidates_retained: 1,
      duplicate_candidates_removed: 0,
      source_records_bundled: 2,
      candidates_returned_to_preview: 1,
      rejection_reasons: {
        MISSING_SECTOR_MATCH: 3,
        MISSING_ORGANIZATION_MARKER: 1,
      },
    },
    prospects_inserted: 0,
    sources_inserted: 0,
    database_writes: 0,
    warnings: [],
    errors: [],
  };

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = ReactDOMClient.createRoot(container);

    vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
      user: mockAuthUser as any,
      activeOrg: mockActiveOrg as any,
      organizations: [mockActiveOrg as any],
      isLoading: false,
      login: vi.fn(),
      logout: vi.fn(),
      switchOrg: vi.fn(),
      refreshUser: vi.fn(),
    });

    global.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/campaigns')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ items: mockCampaigns, total: mockCampaigns.length }),
        };
      }
      if (url.includes('/api/v1/discovery/preview')) {
        return {
          ok: true,
          status: 200,
          json: async () => mockBundledPreviewResponse,
        };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.restoreAllMocks();
  });

  it('renders bundled sources found count and breakdown badges in Spanish without raw JSON leakage', async () => {
    vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
      locale: 'es',
      dictionary: esMessages,
      t: (key: string, params?: Record<string, string | number>) => translate('es', key, params),
    });

    await act(async () => {
      root.render(<DiscoveryPage />);
    });

    const textarea = container.querySelector('textarea') as HTMLTextAreaElement;
    expect(textarea).not.toBeNull();
    await act(async () => {
      setInputValue(textarea, 'Asociaciones médicas y sociedades científicas en Cali');
    });

    const previewBtn = container.querySelector('[data-testid="web-search-preview-button"]') as HTMLButtonElement;
    expect(previewBtn).not.toBeNull();

    await act(async () => {
      previewBtn.click();
    });

    // 1. Verify sources found badge on candidate card
    expect(container.textContent).toContain('Fuentes encontradas: 3');

    // 2. Verify source items rendered compactly with localized source types
    expect(container.textContent).toContain('Sitio Web Oficial');
    expect(container.textContent).toContain('sociedadescientificas.com');
    expect(container.textContent).toContain('facebook.com');
    expect(container.textContent).toContain('x.com');

    // 3. Verify diagnostics funnel includes bundled metric
    expect(container.textContent).toContain('Fuentes unificadas');
    expect(container.textContent).toContain('2');

    // 4. Verify no raw JSON leakage
    expect(container.textContent).not.toContain('"sources"');
    expect(container.textContent).not.toContain('"source_type"');
  });

  it('renders bundled sources found count and breakdown badges in English without raw JSON leakage', async () => {
    vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
      locale: 'en',
      dictionary: enMessages,
      t: (key: string, params?: Record<string, string | number>) => translate('en', key, params),
    });

    await act(async () => {
      root.render(<DiscoveryPage />);
    });

    const textarea = container.querySelector('textarea') as HTMLTextAreaElement;
    expect(textarea).not.toBeNull();
    await act(async () => {
      setInputValue(textarea, 'Medical associations in Cali Colombia');
    });

    const previewBtn = container.querySelector('[data-testid="web-search-preview-button"]') as HTMLButtonElement;
    expect(previewBtn).not.toBeNull();

    await act(async () => {
      previewBtn.click();
    });

    // 1. Verify sources found badge on candidate card
    expect(container.textContent).toContain('Sources found: 3');

    // 2. Verify source items rendered compactly with localized source types
    expect(container.textContent).toContain('Official Website');
    expect(container.textContent).toContain('sociedadescientificas.com');
    expect(container.textContent).toContain('facebook.com');
    expect(container.textContent).toContain('x.com');

    // 3. Verify diagnostics funnel includes bundled metric in English
    expect(container.textContent).toContain('Sources Bundled');

    // 4. Verify no raw JSON leakage
    expect(container.textContent).not.toContain('"sources"');
    expect(container.textContent).not.toContain('"source_type"');
  });
});
