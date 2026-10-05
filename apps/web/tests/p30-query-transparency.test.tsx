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

describe('Phase P30.5G.5H.4C: Discovery Query Transparency UI Test Suite', () => {
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
      status: 'active',
      icp_id: 'icp-123',
    },
    {
      id: 'camp-bogota-2',
      name: 'Prospección de Asociaciones Médicas — Bogotá',
      status: 'active',
      icp_id: 'icp-456',
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

  it('Scenario A: Renders localized labels in Spanish ("Tu Búsqueda" and "Consulta Enviada al Buscador")', async () => {
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
      candidates_count: 1,
      candidates: [
        {
          candidate_id: 'c-1',
          name: 'Sociedad Colombiana de Pediatría Regional Valle',
          qualification_status: 'READY_FOR_COMMERCIAL_REVIEW',
        },
      ],
      executed_query: 'asociaciones médicas Cali',
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

    // Enter prompt into prompt textarea
    const textarea = container.querySelector('textarea') as HTMLTextAreaElement;
    expect(textarea).not.toBeNull();
    await act(async () => {
      setInputValue(textarea, 'Asociaciones médicas y sociedades científicas de especialidades médicas en Cali, Colombia');
    });

    // Click preview
    const previewBtn = container.querySelector('[data-testid="web-search-preview-button"]') as HTMLButtonElement;
    expect(previewBtn).not.toBeNull();
    await act(async () => {
      previewBtn.click();
    });

    const transparencyCard = container.querySelector('[data-testid="query-transparency-card"]');
    expect(transparencyCard).not.toBeNull();

    const submittedLabel = container.querySelector('[data-testid="submitted-query-label"]');
    const executedLabel = container.querySelector('[data-testid="executed-query-label"]');
    expect(submittedLabel?.textContent).toContain('Tu Búsqueda');
    expect(executedLabel?.textContent).toContain('Consulta Enviada al Buscador');

    const submittedText = container.querySelector('[data-testid="submitted-query-text"]');
    const executedText = container.querySelector('[data-testid="executed-query-text"]');
    expect(submittedText?.textContent).toContain('Asociaciones médicas y sociedades científicas de especialidades médicas en Cali, Colombia');
    expect(executedText?.textContent).toContain('asociaciones médicas Cali');
  });

  it('Scenario A (EN): Renders localized labels in English ("Your Search" and "Query Sent to Search Provider")', async () => {
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
      candidates_count: 0,
      candidates: [],
      executed_query: 'medical associations Cali',
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

    const textarea = container.querySelector('textarea') as HTMLTextAreaElement;
    await act(async () => {
      setInputValue(textarea, 'Medical associations and scientific societies in Cali');
    });

    const previewBtn = container.querySelector('[data-testid="web-search-preview-button"]') as HTMLButtonElement;
    await act(async () => {
      previewBtn.click();
    });

    const submittedLabel = container.querySelector('[data-testid="submitted-query-label"]');
    const executedLabel = container.querySelector('[data-testid="executed-query-label"]');
    expect(submittedLabel?.textContent).toContain('Your Search');
    expect(executedLabel?.textContent).toContain('Query Sent to Search Provider');

    const executedText = container.querySelector('[data-testid="executed-query-text"]');
    expect(executedText?.textContent).toContain('medical associations Cali');
  });

  it('Scenario B & C: Shows "Not available" / "No disponible" fallback if executed_query is null or missing', async () => {
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
      tasks_executed: 0,
      candidates_count: 0,
      candidates: [],
      executed_query: null,
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

    const executedText = container.querySelector('[data-testid="executed-query-text"]');
    expect(executedText?.textContent).toContain('No disponible');
  });

  it('Scenario D: Clear preview button clears both submitted and executed queries', async () => {
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
      executed_query: 'asociaciones médicas Cali',
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

    expect(container.querySelector('[data-testid="query-transparency-card"]')).not.toBeNull();

    // Click "Limpiar Vista Previa" / Clear Preview
    const clearBtn = container.querySelector('button.text-foreground-muted') as HTMLButtonElement;
    expect(clearBtn).not.toBeNull();
    await act(async () => {
      clearBtn.click();
    });

    expect(container.querySelector('[data-testid="query-transparency-card"]')).toBeNull();
  });

  it('Scenario E: Switching campaigns clears transparency card', async () => {
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
      executed_query: 'asociaciones médicas Cali',
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

    expect(container.querySelector('[data-testid="query-transparency-card"]')).not.toBeNull();

    // Switch campaign via campaign selector dropdown
    const campaignSelect = container.querySelector('select') as HTMLSelectElement;
    expect(campaignSelect).not.toBeNull();
    await act(async () => {
      campaignSelect.value = mockCampaigns[1].id;
      campaignSelect.dispatchEvent(new Event('change', { bubbles: true }));
    });

    expect(container.querySelector('[data-testid="query-transparency-card"]')).toBeNull();
  });

  it('Scenario F: Stale response protection prevents rendering when campaign changed in-flight', async () => {
    vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
      locale: 'es',
      dictionary: esMessages,
      t: (key: string, params?: Record<string, string | number>) => translate('es', key, params),
    });

    let resolvePreview: (val: any) => void;
    const previewPromise = new Promise((resolve) => {
      resolvePreview = resolve;
    });

    global.fetch = vi.fn().mockImplementation(async (url: string) => {
      if (url.includes('/api/v1/campaigns')) {
        return { ok: true, status: 200, json: async () => ({ items: mockCampaigns, total: mockCampaigns.length }) };
      }
      if (url.includes('/api/v1/discovery/preview')) {
        await previewPromise;
        return {
          ok: true,
          status: 200,
          json: async () => ({
            status: 'completed',
            organization_id: mockActiveOrg.bop_organization_id,
            campaign_id: mockCampaigns[0].id,
            provider: 'web_search',
            tasks_executed: 1,
            candidates_count: 0,
            candidates: [],
            executed_query: 'asociaciones médicas Cali',
            prospects_inserted: 0,
            sources_inserted: 0,
            database_writes: 0,
            warnings: [],
            errors: [],
          }),
        };
      }
      return { ok: true, status: 200, json: async () => ({}) };
    });

    await act(async () => {
      root.render(<DiscoveryPage />);
    });

    // Start preview for campaign 0
    const previewBtn = container.querySelector('[data-testid="web-search-preview-button"]') as HTMLButtonElement;
    let clickPromise: Promise<void>;
    act(() => {
      clickPromise = Promise.resolve(previewBtn.click());
    });

    // Change campaign to campaign 1 while request is in-flight
    const campaignSelect = container.querySelector('select') as HTMLSelectElement;
    await act(async () => {
      campaignSelect.value = mockCampaigns[1].id;
      campaignSelect.dispatchEvent(new Event('change', { bubbles: true }));
    });

    // Now let preview response resolve
    await act(async () => {
      resolvePreview!(true);
      await clickPromise;
    });

    // Stale response must be discarded
    expect(container.querySelector('[data-testid="query-transparency-card"]')).toBeNull();
  });
});
