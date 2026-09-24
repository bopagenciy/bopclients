import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
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
import type {
  DiscoveryPreviewResponse,
} from '../lib/api/types';

// Mock Next.js navigation
const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/es/discovery',
}));

describe('Phase P30.5G.5H.3C: Discovery Preview Funnel Diagnostics UI Test Suite', () => {
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
      id: 'eec5070e-ee69-4274-8bd2-d881353d4ff9',
      name: 'Prospección de Asociaciones Médicas — Cali',
      status: 'active',
      icp_id: 'icp-123',
    },
  ];

  beforeEach(() => {
    vi.restoreAllMocks();
    mockPush.mockReset();

    container = document.createElement('div');
    document.body.appendChild(container);
    root = ReactDOMClient.createRoot(container);

    vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
      user: mockAuthUser,
      activeOrg: mockActiveOrg,
      activeRole: 'ADMIN',
      organizations: [],
      isLoading: false,
      isAuthenticated: true,
      login: vi.fn(),
      logout: vi.fn(),
      switchOrg: vi.fn(),
      hasRole: (roles) => roles.includes('ADMIN') || roles.includes('OWNER'),
      refreshSession: vi.fn(),
    });
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  it('renders diagnostics panel explaining zero candidates when provider returns 0 results (ES)', async () => {
    vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
      locale: 'es',
      dictionary: esMessages,
      t: (key: string, params?: Record<string, string | number>) => translate('es', key, params),
    });

    const mockResponse: DiscoveryPreviewResponse = {
      status: 'completed',
      organization_id: mockActiveOrg.bop_organization_id,
      campaign_id: mockCampaigns[0].id,
      provider: 'web_search',
      tasks_executed: 1,
      candidates_count: 0,
      candidates: [],
      diagnostics: {
        provider_results_received: 0,
        results_missing_required_fields: 0,
        results_rejected_by_classifier: 0,
        results_accepted_by_classifier: 0,
        directory_candidates_retained: 0,
        candidates_returned_to_preview: 0,
        rejection_reasons: {},
      },
      prospects_inserted: 0,
      sources_inserted: 0,
      database_writes: 0,
      warnings: [],
      errors: [],
    };

    global.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/campaigns')) {
        return { ok: true, status: 200, json: async () => ({ items: mockCampaigns, total: mockCampaigns.length }) };
      }
      if (url.includes('/api/v1/discovery/preview')) {
        return { ok: true, status: 200, json: async () => mockResponse };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    await act(async () => {
      root.render(<DiscoveryPage />);
    });

    const previewBtn = container.querySelector('[data-testid="web-search-preview-button"]') as HTMLButtonElement;
    expect(previewBtn).not.toBeNull();
    await act(async () => {
      previewBtn.click();
    });

    const diagnosticsPanel = container.querySelector('[data-testid="preview-diagnostics-panel"]');
    expect(diagnosticsPanel).not.toBeNull();
    expect(diagnosticsPanel?.textContent).toContain('Diagnóstico del Embudo de Búsqueda');
    expect(diagnosticsPanel?.textContent).toContain('Resultados recibidos');
    expect(diagnosticsPanel?.textContent).toContain('El motor de búsqueda no devolvió resultados para esta consulta.');

    // Verify empty candidates notice is also present
    const emptyState = container.querySelector('[data-testid="preview-empty-state"]');
    expect(emptyState).not.toBeNull();
  });

  it('renders diagnostics panel with rejection reasons breakdown when classifier filters all results (ES)', async () => {
    vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
      locale: 'es',
      dictionary: esMessages,
      t: (key: string, params?: Record<string, string | number>) => translate('es', key, params),
    });

    const mockResponse: DiscoveryPreviewResponse = {
      status: 'completed',
      organization_id: mockActiveOrg.bop_organization_id,
      campaign_id: mockCampaigns[0].id,
      provider: 'web_search',
      tasks_executed: 1,
      candidates_count: 0,
      candidates: [],
      diagnostics: {
        provider_results_received: 6,
        results_missing_required_fields: 0,
        results_rejected_by_classifier: 6,
        results_accepted_by_classifier: 0,
        directory_candidates_retained: 0,
        candidates_returned_to_preview: 0,
        rejection_reasons: {
          EXCLUDED_FACILITY: 3,
          NEGATIVE_KEYWORD_MATCH: 2,
          MISSING_ORGANIZATION_MARKER: 1,
        },
      },
      prospects_inserted: 0,
      sources_inserted: 0,
      database_writes: 0,
      warnings: [],
      errors: [],
    };

    global.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/campaigns')) {
        return { ok: true, status: 200, json: async () => ({ items: mockCampaigns, total: mockCampaigns.length }) };
      }
      if (url.includes('/api/v1/discovery/preview')) {
        return { ok: true, status: 200, json: async () => mockResponse };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    await act(async () => {
      root.render(<DiscoveryPage />);
    });

    const previewBtn = container.querySelector('[data-testid="web-search-preview-button"]') as HTMLButtonElement;
    await act(async () => {
      previewBtn.click();
    });

    const diagnosticsPanel = container.querySelector('[data-testid="preview-diagnostics-panel"]');
    expect(diagnosticsPanel).not.toBeNull();
    expect(diagnosticsPanel?.textContent).toContain('Motivos de descarte');

    // Check specific rejection tags
    const facilityTag = container.querySelector('[data-testid="rejection-reason-EXCLUDED_FACILITY"]');
    expect(facilityTag).not.toBeNull();
    expect(facilityTag?.textContent).toContain('Centro o clínica excluida:');
    expect(facilityTag?.textContent).toContain('3');

    const negKeywordTag = container.querySelector('[data-testid="rejection-reason-NEGATIVE_KEYWORD_MATCH"]');
    expect(negKeywordTag).not.toBeNull();
    expect(negKeywordTag?.textContent).toContain('Término negativo coincidente:');
    expect(negKeywordTag?.textContent).toContain('2');

    const markerTag = container.querySelector('[data-testid="rejection-reason-MISSING_ORGANIZATION_MARKER"]');
    expect(markerTag).not.toBeNull();
    expect(markerTag?.textContent).toContain('Sin indicador de organización:');
    expect(markerTag?.textContent).toContain('1');
  });

  it('renders diagnostics panel in English locale (EN)', async () => {
    vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
      locale: 'en',
      dictionary: enMessages,
      t: (key: string, params?: Record<string, string | number>) => translate('en', key, params),
    });

    const mockResponse: DiscoveryPreviewResponse = {
      status: 'completed',
      organization_id: mockActiveOrg.bop_organization_id,
      campaign_id: mockCampaigns[0].id,
      provider: 'web_search',
      tasks_executed: 1,
      candidates_count: 2,
      candidates: [
        {
          candidate_id: 'cand-01',
          name: 'Sociedad Colombiana de Pediatría',
          entity_archetype: 'PROFESSIONAL_ASSOCIATION',
          qualification_status: 'READY_FOR_COMMERCIAL_REVIEW',
          geographic_evidence_status: 'VERIFIED_LOCAL_PRESENCE',
          current_activity_status: 'CURRENT_ACTIVITY_EVIDENCED',
          source_url: 'https://scp.com.co',
          source_host: 'scp.com.co',
          organization_website: 'https://scp.com.co',
          is_commercial_review_ready: true,
          qualification_reasons: [],
          missing_evidence: [],
        },
        {
          candidate_id: 'cand-02',
          name: 'Colegio Médico de Cali',
          entity_archetype: 'PROFESSIONAL_ASSOCIATION',
          qualification_status: 'READY_FOR_COMMERCIAL_REVIEW',
          geographic_evidence_status: 'VERIFIED_LOCAL_PRESENCE',
          current_activity_status: 'CURRENT_ACTIVITY_EVIDENCED',
          source_url: 'https://medicoscali.org',
          source_host: 'medicoscali.org',
          organization_website: 'https://medicoscali.org',
          is_commercial_review_ready: true,
          qualification_reasons: [],
          missing_evidence: [],
        },
      ],
      diagnostics: {
        provider_results_received: 5,
        results_missing_required_fields: 0,
        results_rejected_by_classifier: 3,
        results_accepted_by_classifier: 2,
        directory_candidates_retained: 0,
        candidates_returned_to_preview: 2,
        rejection_reasons: {
          EXCLUDED_FACILITY: 3,
        },
      },
      prospects_inserted: 0,
      sources_inserted: 0,
      database_writes: 0,
      warnings: [],
      errors: [],
    };

    global.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/campaigns')) {
        return { ok: true, status: 200, json: async () => ({ items: mockCampaigns, total: mockCampaigns.length }) };
      }
      if (url.includes('/api/v1/discovery/preview')) {
        return { ok: true, status: 200, json: async () => mockResponse };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    await act(async () => {
      root.render(<DiscoveryPage />);
    });

    const previewBtn = container.querySelector('[data-testid="web-search-preview-button"]') as HTMLButtonElement;
    await act(async () => {
      previewBtn.click();
    });

    const diagnosticsPanel = container.querySelector('[data-testid="preview-diagnostics-panel"]');
    expect(diagnosticsPanel).not.toBeNull();
    expect(diagnosticsPanel?.textContent).toContain('Search Funnel Diagnostics');
    expect(diagnosticsPanel?.textContent).toContain('Results Received');
    expect(diagnosticsPanel?.textContent).toContain('Results Discarded (Filtered)');
    expect(diagnosticsPanel?.textContent).toContain('Matches Accepted');
    expect(diagnosticsPanel?.textContent).toContain('Candidates Displayed');

    const facilityTag = container.querySelector('[data-testid="rejection-reason-EXCLUDED_FACILITY"]');
    expect(facilityTag).not.toBeNull();
    expect(facilityTag?.textContent).toContain('Excluded Medical Facility:');
    expect(facilityTag?.textContent).toContain('3');

    // Both cards rendered
    expect(container.querySelector('[data-testid="candidate-card-cand-01"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="candidate-card-cand-02"]')).not.toBeNull();
  });

  it('gracefully handles missing/null diagnostics with fallback message without crashing', async () => {
    vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
      locale: 'es',
      dictionary: esMessages,
      t: (key: string, params?: Record<string, string | number>) => translate('es', key, params),
    });

    const mockResponse: DiscoveryPreviewResponse = {
      status: 'completed',
      organization_id: mockActiveOrg.bop_organization_id,
      campaign_id: mockCampaigns[0].id,
      provider: 'web_search',
      tasks_executed: 1,
      candidates_count: 0,
      candidates: [],
      diagnostics: null, // explicitly null
      prospects_inserted: 0,
      sources_inserted: 0,
      database_writes: 0,
      warnings: [],
      errors: [],
    };

    global.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/campaigns')) {
        return { ok: true, status: 200, json: async () => ({ items: mockCampaigns, total: mockCampaigns.length }) };
      }
      if (url.includes('/api/v1/discovery/preview')) {
        return { ok: true, status: 200, json: async () => mockResponse };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    await act(async () => {
      root.render(<DiscoveryPage />);
    });

    const previewBtn = container.querySelector('[data-testid="web-search-preview-button"]') as HTMLButtonElement;
    await act(async () => {
      previewBtn.click();
    });

    const diagnosticsPanel = container.querySelector('[data-testid="preview-diagnostics-panel"]');
    expect(diagnosticsPanel).not.toBeNull();
    expect(diagnosticsPanel?.textContent).toContain('Diagnóstico del Embudo de Búsqueda');
    expect(diagnosticsPanel?.textContent).toContain('No disponible');

    // Make sure no broken metrics or zeros are displayed
    expect(diagnosticsPanel?.textContent).not.toContain('Resultados del proveedor');
  });
});
