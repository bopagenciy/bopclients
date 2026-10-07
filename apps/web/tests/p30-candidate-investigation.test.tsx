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
import type { DiscoveryPreviewResponse, CandidateInvestigationResponse } from '../lib/api/types';

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

describe('Phase P30.5G.5H.6B.1: Candidate Investigation & Requalification UI Test Suite', () => {
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

  const mockPreviewResponse: DiscoveryPreviewResponse = {
    status: 'completed',
    organization_id: mockActiveOrg.bop_organization_id,
    campaign_id: mockCampaigns[0].id,
    provider: 'web_search',
    tasks_executed: 1,
    candidates_count: 1,
    candidates: [
      {
        candidate_id: 'cand-smv-1',
        name: 'Sociedad Médica del Valle',
        category: 'medical_association',
        city: 'Cali',
        state: 'Valle del Cauca',
        country: 'CO',
        geographic_scope: 'LOCATION_UNVERIFIED',
        classification_status: 'ACCEPTED_CANDIDATE',
        title: 'Sociedad Médica del Valle',
        snippet: 'Listado en directorio.',
        source: 'web_search',
        qualification_status: 'SEARCH_MATCH',
        entity_archetype: 'PROFESSIONAL_ASSOCIATION',
        geographic_evidence_status: 'LOCATION_UNVERIFIED',
        current_activity_status: 'CURRENT_STATUS_UNKNOWN',
        source_url: 'https://directorio.com/smv',
        source_host: 'directorio.com',
        organization_website: 'UNKNOWN',
        is_commercial_review_ready: false,
        qualification_reasons: ['COMPATIBLE_ENTITY_ARCHETYPE'],
        missing_evidence: ['OFFICIAL_ORGANIZATION_WEBSITE_UNKNOWN'],
        sources_count: 1,
        sources: [
          {
            source_url: 'https://directorio.com/smv',
            source_host: 'directorio.com',
            source_type: 'DIRECTORY_LISTING',
            platform: null,
            title: 'Directorio',
            snippet: 'Perfil en directorio.',
          },
        ],
      },
    ],
    prospects_inserted: 0,
    sources_inserted: 0,
    database_writes: 0,
    warnings: [],
    errors: [],
  };

  const mockInvestigationResponse: CandidateInvestigationResponse = {
    status: 'completed',
    candidate_id: 'cand-smv-1',
    candidate_name: 'Sociedad Médica del Valle',
    investigation_objective: 'OFFICIAL_WEBSITE',
    investigation_query: 'Sociedad Médica del Valle sitio web oficial',
    results_received: 1,
    previous_qualification_status: 'SEARCH_MATCH',
    qualification_status: 'READY_FOR_COMMERCIAL_REVIEW',
    qualification_changed: true,
    is_commercial_review_ready: true,
    qualification_reasons: [
      'COMPATIBLE_ENTITY_ARCHETYPE',
      'GEOGRAPHIC_CRITERIA_SATISFIED',
      'OFFICIAL_DOMAIN_IDENTIFIED',
      'READY_FOR_COMMERCIAL_REVIEW',
    ],
    missing_evidence: [],
    entity_archetype: 'PROFESSIONAL_ASSOCIATION',
    organization_website: 'https://sociedadmedicavalle.org',
    geographic_evidence_status: 'VERIFIED_LOCAL_PRESENCE',
    current_activity_status: 'CURRENT_ACTIVITY_EVIDENCED',
    sources_count: 2,
    sources: [
      {
        source_url: 'https://directorio.com/smv',
        source_host: 'directorio.com',
        source_type: 'DIRECTORY_LISTING',
        platform: null,
        title: 'Directorio',
        snippet: 'Perfil en directorio.',
      },
      {
        source_url: 'https://sociedadmedicavalle.org',
        source_host: 'sociedadmedicavalle.org',
        source_type: 'OFFICIAL_WEBSITE',
        platform: null,
        title: 'Sociedad Médica del Valle - Sitio Oficial',
        snippet: 'Sitio institucional en Cali 2026.',
      },
    ],
    new_sources_added: 1,
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

    vi.spyOn(I18nContext, 'useI18n').mockReturnValue({
      locale: 'es',
      dictionary: esMessages,
      t: (key: string, params?: Record<string, any>) => translate('es', key, params),
      setLocale: vi.fn(),
    });
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.restoreAllMocks();
  });

  it('renders Investigate Candidate button on SEARCH_MATCH candidates and handles investigation flow', async () => {
    let investigatePayload: any = null;

    globalThis.fetch = vi.fn().mockImplementation((url: string, opts?: any) => {
      if (url.includes('/api/v1/campaigns')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ items: mockCampaigns, total: mockCampaigns.length }),
        });
      }
      if (url.includes('/api/v1/discovery/preview')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(mockPreviewResponse),
        });
      }
      if (url.includes('/api/v1/discovery/candidates/investigate')) {
        investigatePayload = JSON.parse(opts.body);
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve(mockInvestigationResponse),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) });
    });

    // 1. Initial render
    await act(async () => {
      root.render(<DiscoveryPage />);
    });

    const textarea = container.querySelector('textarea') as HTMLTextAreaElement;
    expect(textarea).not.toBeNull();
    await act(async () => {
      setInputValue(textarea, 'Sociedad Médica Cali');
    });

    // 2. Trigger preview
    const previewBtn = container.querySelector('[data-testid="web-search-preview-button"]') as HTMLButtonElement;
    expect(previewBtn).not.toBeNull();

    await act(async () => {
      previewBtn.click();
    });

    // Verify candidate card rendered as SEARCH_MATCH
    const investigateBtn = container.querySelector('[data-testid="investigate-candidate-btn-cand-smv-1"]') as HTMLButtonElement;
    expect(investigateBtn).not.toBeNull();
    expect(investigateBtn.textContent).toContain('Investigar');

    // Strict Non-Goal: No promote-to-prospect button exists
    expect(container.querySelector('[data-testid="promote-to-prospect-btn"]')).toBeNull();

    // 3. Click Investigate Candidate
    await act(async () => {
      investigateBtn.click();
    });

    // Verify correct payload was sent
    expect(investigatePayload).not.toBeNull();
    expect(investigatePayload.candidate_name).toBe('Sociedad Médica del Valle');
    expect(investigatePayload.candidate_id).toBe('cand-smv-1');

    // 4. Verify candidate updated to READY_FOR_COMMERCIAL_REVIEW
    const reportBanner = container.querySelector('[data-testid="investigation-report-cand-smv-1"]');
    expect(reportBanner).not.toBeNull();
    expect(reportBanner?.textContent).toContain('Investigado');
    expect(reportBanner?.textContent).toContain('Sociedad Médica del Valle sitio web oficial');

    // Investigate button disappears when status moves out of SEARCH_MATCH
    const updatedInvestigateBtn = container.querySelector('[data-testid="investigate-candidate-btn-cand-smv-1"]');
    expect(updatedInvestigateBtn).toBeNull();
  });
});
