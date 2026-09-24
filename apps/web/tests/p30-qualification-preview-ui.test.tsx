import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import * as ReactDOMClient from 'react-dom/client';
import { renderToString } from 'react-dom/server';

// @ts-ignore
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

import DiscoveryPage from '../app/[locale]/(app)/discovery/page';
import * as AuthContext from '../lib/auth/context';
import * as I18nContext from '../lib/i18n/context';
import { translate } from '../lib/i18n';
import enMessages from '../messages/en.json';
import esMessages from '../messages/es.json';
import { previewDiscovery } from '../lib/api/client';
import type {
  DiscoveryPreviewRequest,
  DiscoveryPreviewResponse,
  DiscoveryCandidateSummary,
} from '../lib/api/types';

// Mock Next.js navigation
const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/en/discovery',
}));

describe('Phase P30.5G.5G: Qualification Preview UI Foundation Test Suite', () => {
  let container: HTMLDivElement;
  let root: ReactDOMClient.Root;

  const mockAuthUser = {
    id: 'user-bop-1',
    email: 'admin@bopagencia.local',
    full_name: 'Admin Bop Agencia',
    locale: 'en',
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
      name: 'Colombian Medical Associations',
      status: 'active',
      icp_id: 'icp-123',
    },
    {
      id: 'camp-legal-002',
      name: 'Legal Tech Outbound',
      status: 'paused',
      icp_id: null,
    },
  ];

  beforeEach(() => {
    vi.restoreAllMocks();
    mockPush.mockReset();

    // Default mock auth & i18n
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

    vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
      locale: 'en',
      dictionary: enMessages,
      t: (key: string, params?: Record<string, string | number>) => translate('en', key, params),
    });

    // Default global fetch
    global.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/api/proxy/api/v1/campaigns')) {
        return {
          ok: true,
          status: 200,
          json: async () => ({ items: mockCampaigns, total: mockCampaigns.length }),
        };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({}),
      };
    });

    container = document.createElement('div');
    document.body.appendChild(container);
    root = ReactDOMClient.createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
  });

  // =========================================================================
  // 1. LOCALIZATION & TRANSLATION PARITY (EN / ES)
  // =========================================================================
  describe('1. Localization & Translation Parity', () => {
    const requiredPreviewKeys = [
      'discovery.preview_button',
      'discovery.previewing',
      'discovery.preview_title',
      'discovery.preview_subtitle',
      'discovery.preview_disclaimer',
      'discovery.preview_failed_title',
      'discovery.preview_empty',
      'discovery.status_ready',
      'discovery.status_search_match',
      'discovery.status_insufficient',
      'discovery.status_rejected',
      'discovery.archetype_label',
      'discovery.source_provenance_label',
      'discovery.official_website_label',
      'discovery.official_website_unknown',
      'discovery.geo_evidence_label',
      'discovery.current_activity_label',
      'discovery.qualification_reasons_label',
      'discovery.missing_evidence_label',
      'discovery.zero_writes_badge',
      'discovery.provider_label',
      'discovery.selected_campaign_label',
      'discovery.clear_preview',
      'discovery.classification_label',
      'discovery.candidates_found',
      'discovery.candidates_discovered',
    ];

    it('all preview keys exist in both en.json and es.json with 100% parity', () => {
      for (const key of requiredPreviewKeys) {
        const enVal = translate('en', key);
        const esVal = translate('es', key);

        expect(enVal, `Missing EN key: ${key}`).not.toBe(key);
        expect(esVal, `Missing ES key: ${key}`).not.toBe(key);
        expect(enVal.length).toBeGreaterThan(0);
        expect(esVal.length).toBeGreaterThan(0);
      }
    });

    it('Spanish translations contain truthful domain terminology without English fallbacks', () => {
      expect(translate('es', 'discovery.preview_button')).toBe('Vista Previa de Búsqueda Web');
      expect(translate('es', 'discovery.status_ready')).toBe('Listo para Revisión Comercial');
      expect(translate('es', 'discovery.status_search_match')).toBe('Coincidencia de Búsqueda (Requiere Calificación)');
      expect(translate('es', 'discovery.zero_writes_badge')).toContain('0 Prospectos Creados');
    });
  });

  // =========================================================================
  // 2. API CLIENT METHOD VERIFICATION
  // =========================================================================
  describe('2. API Client previewDiscovery Fetcher', () => {
    it('sends POST request to /api/proxy/api/v1/discovery/preview with credentials and payload', async () => {
      const mockResult: DiscoveryPreviewResponse = {
        status: 'completed',
        organization_id: '7a656f63-4344-4b21-97a9-f0bee5d451b3',
        campaign_id: 'eec5070e-ee69-4274-8bd2-d881353d4ff9',
        provider: 'tavily',
        tasks_executed: 1,
        candidates_count: 1,
        candidates: [
          {
            candidate_id: 'cand-1',
            name: 'Asociación Colombiana de Cirugía',
            qualification_status: 'SEARCH_MATCH',
            entity_archetype: 'INDUSTRY_DIRECTORY',
          },
        ],
        prospects_inserted: 0,
        sources_inserted: 0,
        database_writes: 0,
        warnings: [],
        errors: [],
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockResult,
      });

      const payload: DiscoveryPreviewRequest = {
        campaign_id: 'eec5070e-ee69-4274-8bd2-d881353d4ff9',
        raw_query: 'asociaciones medicas colombia',
      };

      const result = await previewDiscovery(payload);

      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [url, options] = (global.fetch as any).mock.calls[0];
      expect(url).toBe('/api/proxy/api/v1/discovery/preview');
      expect(options.method).toBe('POST');
      expect(options.credentials).toBe('include');
      expect(JSON.parse(options.body)).toEqual(payload);
      expect(result.database_writes).toBe(0);
      expect(result.prospects_inserted).toBe(0);
      expect(result.candidates.length).toBe(1);
    });
  });

  // =========================================================================
  // 3. NO AUTOMATIC PREVIEW ON MOUNT & DOUBLE SUBMISSION PREVENTION
  // =========================================================================
  describe('3. Lifecycle Controls & Double Submission Prevention', () => {
    it('does NOT trigger preview requests on initial component mount or campaign load', async () => {
      let previewCallCount = 0;
      global.fetch = vi.fn().mockImplementation(async (url: string) => {
        if (url.includes('/api/v1/discovery/preview')) {
          previewCallCount++;
        }
        if (url.includes('/api/v1/campaigns')) {
          return {
            ok: true,
            status: 200,
            json: async () => ({ items: mockCampaigns, total: mockCampaigns.length }),
          };
        }
        return { ok: true, status: 200, json: async () => ({}) };
      });

      await act(async () => {
        root.render(<DiscoveryPage />);
      });

      expect(previewCallCount).toBe(0);
    });

    it('disables preview button while request is in flight to prevent double submission', async () => {
      let resolvePreview: any;
      const previewPromise = new Promise((resolve) => {
        resolvePreview = resolve;
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
          return previewPromise;
        }
        return { ok: true, status: 200, json: async () => ({}) };
      });

      await act(async () => {
        root.render(<DiscoveryPage />);
      });

      const previewBtn = container.querySelector('[data-testid="web-search-preview-button"]') as HTMLButtonElement;
      expect(previewBtn).not.toBeNull();
      expect(previewBtn.disabled).toBe(false);

      // Trigger preview click
      act(() => {
        previewBtn.click();
      });

      // While in flight, button must be disabled and display loading state
      expect(previewBtn.disabled).toBe(true);
      expect(previewBtn.textContent).toContain('Requesting Preview...');

      // Resolve the preview request
      await act(async () => {
        resolvePreview({
          ok: true,
          status: 200,
          json: async () => ({
            status: 'completed',
            organization_id: mockActiveOrg.bop_organization_id,
            campaign_id: mockCampaigns[0].id,
            provider: 'tavily',
            tasks_executed: 1,
            candidates_count: 0,
            candidates: [],
            prospects_inserted: 0,
            sources_inserted: 0,
            database_writes: 0,
            warnings: [],
            errors: [],
          }),
        });
      });

      // Button is re-enabled after completion
      expect(previewBtn.disabled).toBe(false);
      expect(previewBtn.textContent).toContain('Web Search Preview');
    });

    it('changing selected campaign invalidates existing preview results to prevent stale display', async () => {
      const mockResult: DiscoveryPreviewResponse = {
        status: 'completed',
        organization_id: mockActiveOrg.bop_organization_id,
        campaign_id: mockCampaigns[0].id,
        provider: 'tavily',
        tasks_executed: 1,
        candidates_count: 1,
        candidates: [
          {
            candidate_id: 'cand-01',
            name: 'Medical Association Candidate',
            qualification_status: 'SEARCH_MATCH',
          },
        ],
        prospects_inserted: 0,
        sources_inserted: 0,
        database_writes: 0,
        warnings: [],
        errors: [],
      };

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
            json: async () => mockResult,
          };
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

      expect(container.querySelector('[data-testid="discovery-preview-panel"]')).not.toBeNull();

      // Change campaign dropdown to campaign 2
      const campaignSelect = container.querySelector('select') as HTMLSelectElement;
      expect(campaignSelect).not.toBeNull();

      await act(async () => {
        campaignSelect.value = mockCampaigns[1].id;
        campaignSelect.dispatchEvent(new Event('change', { bubbles: true }));
      });

      // Preview panel must be invalidated and cleared
      expect(container.querySelector('[data-testid="discovery-preview-panel"]')).toBeNull();
    });

    it('discards in-flight response if selected campaign changes before response arrives', async () => {
      let resolvePreview: any;
      const previewPromise = new Promise((resolve) => {
        resolvePreview = resolve;
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
          return previewPromise;
        }
        return { ok: true, status: 200, json: async () => ({}) };
      });

      await act(async () => {
        root.render(<DiscoveryPage />);
      });

      const previewBtn = container.querySelector('[data-testid="web-search-preview-button"]') as HTMLButtonElement;
      act(() => {
        previewBtn.click();
      });

      // Switch campaign while preview is in flight
      const campaignSelect = container.querySelector('select') as HTMLSelectElement;
      await act(async () => {
        campaignSelect.value = mockCampaigns[1].id;
        campaignSelect.dispatchEvent(new Event('change', { bubbles: true }));
      });

      // Now resolve the previous campaign's in-flight request
      await act(async () => {
        resolvePreview({
          ok: true,
          status: 200,
          json: async () => ({
            status: 'completed',
            organization_id: mockActiveOrg.bop_organization_id,
            campaign_id: mockCampaigns[0].id,
            provider: 'tavily',
            tasks_executed: 1,
            candidates_count: 1,
            candidates: [
              {
                candidate_id: 'cand-01',
                name: 'Old Campaign Candidate',
                qualification_status: 'SEARCH_MATCH',
              },
            ],
            prospects_inserted: 0,
            sources_inserted: 0,
            database_writes: 0,
            warnings: [],
            errors: [],
          }),
        });
      });

      // Must NOT display old campaign's preview results
      expect(container.querySelector('[data-testid="discovery-preview-panel"]')).toBeNull();
    });
  });

  // =========================================================================
  // 4. STRUCTURED QUALIFICATION PRESENTATION
  // =========================================================================
  describe('4. Candidate Presentation & Structured Qualification Details', () => {
    it('renders SEARCH_MATCH with amber badge and missing evidence tags', async () => {
      const mockResult: DiscoveryPreviewResponse = {
        status: 'completed',
        organization_id: mockActiveOrg.bop_organization_id,
        campaign_id: mockCampaigns[0].id,
        provider: 'tavily',
        tasks_executed: 1,
        candidates_count: 1,
        candidates: [
          {
            candidate_id: 'cand-dir-01',
            name: 'Directorio Médico de Colombia',
            title: 'Listado de Asociaciones y Médicos Especialistas',
            snippet: 'Portal informativo con directorios y artículos sobre medicina general.',
            entity_archetype: 'INDUSTRY_DIRECTORY',
            qualification_status: 'SEARCH_MATCH',
            is_commercial_review_ready: false,
            source_url: 'https://directoriomedico.co/asociaciones',
            source_host: 'directoriomedico.co',
            organization_website: 'UNKNOWN',
            geographic_evidence_status: 'CONFIRMED',
            current_activity_status: 'ACTIVE_RECENT',
            qualification_reasons: ['valid_organization_name', 'target_market_match'],
            missing_evidence: ['no_official_domain_evidenced', 'directory_aggregator_archetype'],
          },
        ],
        prospects_inserted: 0,
        sources_inserted: 0,
        database_writes: 0,
        warnings: [],
        errors: [],
      };

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
            json: async () => mockResult,
          };
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

      const panel = container.querySelector('[data-testid="discovery-preview-panel"]');
      expect(panel).not.toBeNull();

      // Zero DB writes badge
      expect(panel?.textContent).toContain('0 Prospects Created • 0 DB Writes • Ephemeral');

      // Candidate card
      const card = container.querySelector('[data-testid="candidate-card-cand-dir-01"]');
      expect(card).not.toBeNull();
      expect(card?.textContent).toContain('Directorio Médico de Colombia');
      expect(card?.textContent).toContain('Industry Directory');
      expect(card?.textContent).not.toContain('INDUSTRY_DIRECTORY');
      expect(card?.textContent).toContain('Search Match (Requires Qualification)');

      // Unknown official website warning (source host only)
      expect(card?.textContent).toContain('Official Website Unknown (Source Page Only)');
      expect(card?.textContent).toContain('directoriomedico.co');

      // Qualification reasons & missing evidence
      expect(card?.textContent).toContain('valid_organization_name');
      expect(card?.textContent).toContain('no_official_domain_evidenced');
      expect(card?.textContent).toContain('directory_aggregator_archetype');
    });

    it('renders READY_FOR_COMMERCIAL_REVIEW with green badge and verified official website', async () => {
      const mockResult: DiscoveryPreviewResponse = {
        status: 'completed',
        organization_id: mockActiveOrg.bop_organization_id,
        campaign_id: mockCampaigns[0].id,
        provider: 'tavily',
        tasks_executed: 1,
        candidates_count: 1,
        candidates: [
          {
            candidate_id: 'cand-assoc-02',
            name: 'Sociedad Colombiana de Cardiología',
            title: 'Sociedad Colombiana de Cardiología y Cirugía Cardiovascular',
            snippet: 'Gremio médico científico que agrupa a los cardiólogos de Colombia.',
            entity_archetype: 'PROFESSIONAL_ASSOCIATION',
            qualification_status: 'READY_FOR_COMMERCIAL_REVIEW',
            is_commercial_review_ready: true,
            source_url: 'https://scc.org.co/quienes-somos',
            source_host: 'scc.org.co',
            organization_website: 'https://scc.org.co',
            geographic_evidence_status: 'CONFIRMED',
            current_activity_status: 'ACTIVE_RECENT',
            city: 'Bogotá',
            country: 'Colombia',
            qualification_reasons: ['official_domain_verified', 'target_market_match', 'active_operating_status'],
            missing_evidence: [],
          },
        ],
        prospects_inserted: 0,
        sources_inserted: 0,
        database_writes: 0,
        warnings: [],
        errors: [],
      };

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
            json: async () => mockResult,
          };
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

      const card = container.querySelector('[data-testid="candidate-card-cand-assoc-02"]');
      expect(card).not.toBeNull();
      expect(card?.textContent).toContain('Sociedad Colombiana de Cardiología');
      expect(card?.textContent).toContain('Professional Association');
      expect(card?.textContent).not.toContain('PROFESSIONAL_ASSOCIATION');
      expect(card?.textContent).toContain('Ready for Commercial Review');

      // Verified official domain present
      expect(card?.innerHTML).toContain('https://scc.org.co');
      expect(card?.textContent).not.toContain('Official Website Unknown');

      // Location details
      expect(card?.textContent).toContain('Bogotá, Colombia');
    });
  });

  // =========================================================================
  // 5. ENVELOPE FAILURE & EMPTY STATE HANDLING
  // =========================================================================
  describe('5. Envelope Failures & Zero Results Handling', () => {
    it('handles HTTP 200 with status="failed" and renders error alert, never showing success', async () => {
      const mockFailedEnvelope: DiscoveryPreviewResponse = {
        status: 'failed',
        organization_id: mockActiveOrg.bop_organization_id,
        campaign_id: mockCampaigns[0].id,
        provider: 'tavily',
        tasks_executed: 0,
        candidates_count: 0,
        candidates: [],
        prospects_inserted: 0,
        sources_inserted: 0,
        database_writes: 0,
        warnings: [],
        errors: ['Tavily search API key is not configured or enabled'],
      };

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
            json: async () => mockFailedEnvelope,
          };
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

      const panel = container.querySelector('[data-testid="discovery-preview-panel"]');
      expect(panel).not.toBeNull();

      // Failed badge must be displayed
      expect(panel?.textContent).toContain('Failed');
      expect(panel?.textContent).not.toContain('Completed');

      // Error banner
      const errorsAlert = container.querySelector('[data-testid="preview-errors-alert"]');
      expect(errorsAlert).not.toBeNull();
      expect(errorsAlert?.textContent).toContain('Preview Request Failed (1)');
      expect(errorsAlert?.textContent).toContain('Tavily search API key is not configured or enabled');

      // Must NOT display "Search completed successfully"
      expect(panel?.textContent).not.toContain('Search completed successfully');
    });

    it('renders clean empty state when search completes successfully with zero candidates', async () => {
      const mockEmptyResult: DiscoveryPreviewResponse = {
        status: 'completed',
        organization_id: mockActiveOrg.bop_organization_id,
        campaign_id: mockCampaigns[0].id,
        provider: 'tavily',
        tasks_executed: 1,
        candidates_count: 0,
        candidates: [],
        prospects_inserted: 0,
        sources_inserted: 0,
        database_writes: 0,
        warnings: [],
        errors: [],
      };

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
            json: async () => mockEmptyResult,
          };
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

      const emptyState = container.querySelector('[data-testid="preview-empty-state"]');
      expect(emptyState).not.toBeNull();
      expect(emptyState?.textContent).toContain('Search completed successfully. Zero candidates discovered for this criteria.');
    });

    it('allows clearing the preview panel with the Clear Preview button', async () => {
      const mockResult: DiscoveryPreviewResponse = {
        status: 'completed',
        organization_id: mockActiveOrg.bop_organization_id,
        campaign_id: mockCampaigns[0].id,
        provider: 'tavily',
        tasks_executed: 1,
        candidates_count: 1,
        candidates: [
          {
            candidate_id: 'cand-01',
            name: 'Test Candidate',
            qualification_status: 'SEARCH_MATCH',
          },
        ],
        prospects_inserted: 0,
        sources_inserted: 0,
        database_writes: 0,
        warnings: [],
        errors: [],
      };

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
            json: async () => mockResult,
          };
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

      expect(container.querySelector('[data-testid="discovery-preview-panel"]')).not.toBeNull();

      // Find and click Clear Preview button
      const clearBtn = container.querySelector('button:has(svg.lucide-x)') as HTMLButtonElement;
      await act(async () => {
        clearBtn.click();
      });

      // Panel is dismissed
      expect(container.querySelector('[data-testid="discovery-preview-panel"]')).toBeNull();
    });
  });

  // =========================================================================
  // 8. PHASE P30.5G.5H.2: COMPREHENSIVE LOCALIZATION & PRESENTATION POLISH
  // =========================================================================
  describe('8. Phase P30.5G.5H.2: Comprehensive Localization and Presentation Polish', () => {
    it('renders English preview labels and localized enums without raw enum leakage', async () => {
      vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
        locale: 'en',
        dictionary: enMessages,
        t: (key: string, params?: Record<string, string | number>) => translate('en', key, params),
      });

      const mockResponse: DiscoveryPreviewResponse = {
        status: 'completed',
        organization_id: mockActiveOrg.bop_organization_id,
        campaign_id: mockCampaigns[0].id,
        provider: 'tavily',
        tasks_executed: 1,
        candidates_count: 1,
        candidates: [
          {
            candidate_id: 'cand-dir-01',
            name: 'Sociedades Afiliadas - Academia Nacional de Medicina',
            entity_archetype: 'DIRECTORY_LISTING',
            qualification_status: 'SEARCH_MATCH',
            geographic_evidence_status: 'LOCATION_UNVERIFIED',
            current_activity_status: 'CURRENT_STATUS_UNKNOWN',
            source_url: 'https://anmedcolombia.org.co/sociedades-afiliadas/',
            source_host: 'anmedcolombia.org.co',
            organization_website: 'UNKNOWN',
            is_commercial_review_ready: false,
            qualification_reasons: [],
            missing_evidence: ['DIRECTORY_LISTING_NOT_ORGANIZATION', 'UNRESOLVED_COMPOSITE_DIRECTORY_ENTITY'],
          },
        ],
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

      const panel = container.querySelector('[data-testid="discovery-preview-panel"]');
      expect(panel).not.toBeNull();

      // Context bar English labels
      expect(panel?.textContent).toContain('Tasks Executed:');
      expect(panel?.textContent).toContain('Candidates Found:');
      expect(panel?.textContent).toContain('Candidates Discovered (1)');

      // Candidate card English localized enums
      const card = container.querySelector('[data-testid="candidate-card-cand-dir-01"]');
      expect(card).not.toBeNull();
      expect(card?.textContent).toContain('Directory Listing');
      expect(card?.textContent).toContain('Search Match (Requires Qualification)');
      expect(card?.textContent).toContain('Location Unverified');
      expect(card?.textContent).toContain('Current Status Unknown');

      // Assert NO raw enum leakage in presentation badges and fields
      expect(card?.textContent).not.toContain('Entity Archetype: DIRECTORY_LISTING');
      expect(card?.textContent).not.toContain('LOCATION_UNVERIFIED');
      expect(card?.textContent).not.toContain('CURRENT_STATUS_UNKNOWN');
    });

    it('renders Spanish preview labels and localized enums without raw enum leakage', async () => {
      vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
        locale: 'es',
        dictionary: esMessages,
        t: (key: string, params?: Record<string, string | number>) => translate('es', key, params),
      });

      const mockResponse: DiscoveryPreviewResponse = {
        status: 'completed',
        organization_id: mockActiveOrg.bop_organization_id,
        campaign_id: mockCampaigns[0].id,
        provider: 'tavily',
        tasks_executed: 1,
        candidates_count: 1,
        candidates: [
          {
            candidate_id: 'cand-dir-es-01',
            name: 'Sociedades Afiliadas - Academia Nacional de Medicina',
            entity_archetype: 'DIRECTORY_LISTING',
            qualification_status: 'SEARCH_MATCH',
            geographic_evidence_status: 'LOCATION_UNVERIFIED',
            current_activity_status: 'CURRENT_STATUS_UNKNOWN',
            source_url: 'https://anmedcolombia.org.co/sociedades-afiliadas/',
            source_host: 'anmedcolombia.org.co',
            organization_website: 'UNKNOWN',
            is_commercial_review_ready: false,
            qualification_reasons: [],
            missing_evidence: ['DIRECTORY_LISTING_NOT_ORGANIZATION', 'UNRESOLVED_COMPOSITE_DIRECTORY_ENTITY'],
          },
        ],
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

      const panel = container.querySelector('[data-testid="discovery-preview-panel"]');
      expect(panel).not.toBeNull();

      // Context bar Spanish labels
      expect(panel?.textContent).toContain('Tareas Ejecutadas:');
      expect(panel?.textContent).toContain('Candidatos Encontrados:');
      expect(panel?.textContent).toContain('Candidatos Descubiertos (1)');

      // Candidate card Spanish localized enums
      const card = container.querySelector('[data-testid="candidate-card-cand-dir-es-01"]');
      expect(card).not.toBeNull();
      expect(card?.textContent).toContain('Directorio / Listado');
      expect(card?.textContent).toContain('Coincidencia de Búsqueda (Requiere Calificación)');
      expect(card?.textContent).toContain('Ubicación No Verificada');
      expect(card?.textContent).toContain('Estado Actual Desconocido');

      // Assert NO raw enum leakage in presentation badges and fields
      expect(card?.textContent).not.toContain('Arquetipo de Entidad: DIRECTORY_LISTING');
      expect(card?.textContent).not.toContain('LOCATION_UNVERIFIED');
      expect(card?.textContent).not.toContain('CURRENT_STATUS_UNKNOWN');
    });

    it('renders READY_FOR_COMMERCIAL_REVIEW in Spanish without raw enum leakage', async () => {
      vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
        locale: 'es',
        dictionary: esMessages,
        t: (key: string, params?: Record<string, string | number>) => translate('es', key, params),
      });

      const mockResponse: DiscoveryPreviewResponse = {
        status: 'completed',
        organization_id: mockActiveOrg.bop_organization_id,
        campaign_id: mockCampaigns[0].id,
        provider: 'tavily',
        tasks_executed: 1,
        candidates_count: 1,
        candidates: [
          {
            candidate_id: 'cand-ready-es-01',
            name: 'Sociedad Colombiana de Pediatría Regional Valle',
            entity_archetype: 'PROFESSIONAL_ASSOCIATION',
            qualification_status: 'READY_FOR_COMMERCIAL_REVIEW',
            geographic_evidence_status: 'VERIFIED_LOCAL_PRESENCE',
            current_activity_status: 'CURRENT_ACTIVITY_EVIDENCED',
            source_url: 'https://scpvalle.org',
            source_host: 'scpvalle.org',
            organization_website: 'https://scpvalle.org',
            city: 'Cali',
            state: 'Valle del Cauca',
            country: 'CO',
            is_commercial_review_ready: true,
            qualification_reasons: ['COMPATIBLE_ENTITY_ARCHETYPE'],
            missing_evidence: [],
          },
        ],
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

      const card = container.querySelector('[data-testid="candidate-card-cand-ready-es-01"]');
      expect(card).not.toBeNull();
      expect(card?.textContent).toContain('Asociación Profesional');
      expect(card?.textContent).toContain('Listo para Revisión Comercial');
      expect(card?.textContent).toContain('Presencia Local Verificada');
      expect(card?.textContent).toContain('Actividad Actual Evidenciada');

      // Assert NO raw enum leakage
      expect(card?.textContent).not.toContain('PROFESSIONAL_ASSOCIATION');
      expect(card?.textContent).not.toContain('READY_FOR_COMMERCIAL_REVIEW');
      expect(card?.textContent).not.toContain('VERIFIED_LOCAL_PRESENCE');
      expect(card?.textContent).not.toContain('CURRENT_ACTIVITY_EVIDENCED');
    });

    it('gracefully formats unknown future enums with safe readable title-case fallback without crashing', async () => {
      vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
        locale: 'en',
        dictionary: enMessages,
        t: (key: string, params?: Record<string, string | number>) => translate('en', key, params),
      });

      const mockResponse: DiscoveryPreviewResponse = {
        status: 'completed',
        organization_id: mockActiveOrg.bop_organization_id,
        campaign_id: mockCampaigns[0].id,
        provider: 'tavily',
        tasks_executed: 1,
        candidates_count: 1,
        candidates: [
          {
            candidate_id: 'cand-future-01',
            name: 'Future Tech Entity',
            entity_archetype: 'CUSTOM_FUTURE_ARCHETYPE',
            qualification_status: 'PROVISIONAL_NEEDS_VALIDATION',
            geographic_evidence_status: 'FUTURE_GEO_VERIFICATION_TIER',
            current_activity_status: 'UNKNOWN_ACTIVITY_MARKER',
            source_url: 'https://futuretech.io',
            source_host: 'futuretech.io',
            organization_website: 'https://futuretech.io',
            is_commercial_review_ready: false,
            qualification_reasons: [],
            missing_evidence: [],
          },
        ],
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

      const card = container.querySelector('[data-testid="candidate-card-cand-future-01"]');
      expect(card).not.toBeNull();

      // Safe readable title-case fallback
      expect(card?.textContent).toContain('Custom Future Archetype');
      expect(card?.textContent).toContain('Provisional Needs Validation');
      expect(card?.textContent).toContain('Future Geo Verification Tier');
      expect(card?.textContent).toContain('Unknown Activity Marker');

      // No raw enum strings with underscores
      expect(card?.textContent).not.toContain('CUSTOM_FUTURE_ARCHETYPE');
      expect(card?.textContent).not.toContain('PROVISIONAL_NEEDS_VALIDATION');
      expect(card?.textContent).not.toContain('FUTURE_GEO_VERIFICATION_TIER');
      expect(card?.textContent).not.toContain('UNKNOWN_ACTIVITY_MARKER');
    });
  });
});
