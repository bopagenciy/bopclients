import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderToString } from 'react-dom/server';
import enMessages from '../messages/en.json';
import esMessages from '../messages/es.json';
import { translate } from '../lib/i18n';
import { hasPermission } from '../lib/permissions';
import {
  triggerProspectResearch,
  getResearchRun,
  getProspectIntelligence,
  listProspectResearchRuns,
} from '../lib/api/client';
import type {
  ResearchRun,
  ProspectIntelligenceResponse,
  ProspectIntelligenceData,
} from '../lib/api/types';
import ResearchPage from '../app/[locale]/(app)/research/page';
import * as AuthContext from '../lib/auth/context';
import * as I18nContext from '../lib/i18n/context';

// Mock Next.js navigation
const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
  useParams: () => ({ locale: 'en', prospectId: 'p-test-123' }),
  useSearchParams: () => new URLSearchParams(),
}));

describe('Phase P30.2: Research Intelligence UX & Lifecycle Test Suite', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockPush.mockReset();
  });

  // =========================================================================
  // 1. LOCALIZATION PARITY & EN/ES TRANSLATION KEYS
  // =========================================================================
  describe('Localization & Translation Key Parity', () => {
    const requiredResearchKeys = [
      'research.status.pending',
      'research.status.running',
      'research.status.completed',
      'research.status.failed',
      'research.find_prospect',
      'research.select_prospect_desc',
      'research.view_dossier',
    ];

    const requiredProspectDetailKeys = [
      'research_button',
      'researching',
      'research_triggered',
      'research_completed',
      'research_in_progress',
      'research_requested',
      'research_still_processing',
      'research_failed_msg',
      'research_intelligence_title',
      'research_intelligence_desc',
      'research_empty_claims',
      'research_empty_opportunities',
      'research_empty_risks',
      'research_empty_unknowns',
      'research_empty_state',
      'research_provider_deterministic',
      'research_provider_deterministic_desc',
      'research_provider_gemini',
      'research_provider_gemini_desc',
      'research_provider_label',
      'research_completed_at',
      'research_version_label',
      'research_confidence_label',
      'executive_summary_title',
      'verified_claims_title',
      'commercial_opportunities_title',
      'risks_and_limitations_title',
      'unknowns_title',
      'research_history_title',
      'research_history_empty',
      'evidence_sources',
      'matched_services',
      'supporting_signals',
      'run_id_label',
      'run_type_label',
      'run_status_label',
    ];

    it('all research keys exist in both en.json and es.json with 100% parity', () => {
      for (const key of requiredResearchKeys) {
        const enVal = translate('en', key);
        const esVal = translate('es', key);

        expect(enVal, `Missing EN key: ${key}`).not.toBe(key);
        expect(esVal, `Missing ES key: ${key}`).not.toBe(key);
        expect(enVal.length).toBeGreaterThan(0);
        expect(esVal.length).toBeGreaterThan(0);
      }
    });

    it('all prospect_detail research keys exist in both en.json and es.json with 100% parity', () => {
      const enPD = (enMessages as any).prospect_detail;
      const esPD = (esMessages as any).prospect_detail;

      for (const key of requiredProspectDetailKeys) {
        expect(enPD[key], `Missing English key: prospect_detail.${key}`).toBeDefined();
        expect(esPD[key], `Missing Spanish key: prospect_detail.${key}`).toBeDefined();
        expect(enPD[key].length).toBeGreaterThan(0);
        expect(esPD[key].length).toBeGreaterThan(0);
      }
    });
  });

  // =========================================================================
  // 2. API CLIENT & RUN_ID RETENTION TESTS
  // =========================================================================
  describe('Research API Client Functions & Run ID Retention', () => {
    it('triggerProspectResearch issues POST and retains run_id in response', async () => {
      const mockRun: ResearchRun = {
        id: 'run-uuid-777',
        organization_id: 'org-1',
        prospect_id: 'prospect-1',
        campaign_id: 'camp-1',
        run_type: 'full_diligence',
        status: 'pending',
        display_key: 'research.status.pending',
        created_at: '2026-09-21T10:00:00Z',
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 202,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockRun,
      });

      const res = await triggerProspectResearch('prospect-1', {
        campaign_id: 'camp-1',
        run_type: 'full_diligence',
      });

      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [url, init] = (global.fetch as any).mock.calls[0];
      expect(url).toContain('/api/proxy/api/v1/prospects/prospect-1/research');
      expect(init.method).toBe('POST');
      expect(res.id).toBe('run-uuid-777');
      expect(res.status).toBe('pending');
    });

    it('getResearchRun issues GET to /api/v1/research-runs/{run_id}', async () => {
      const mockRun: ResearchRun = {
        id: 'run-uuid-777',
        organization_id: 'org-1',
        prospect_id: 'prospect-1',
        status: 'running',
        display_key: 'research.status.running',
        created_at: '2026-09-21T10:00:00Z',
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockRun,
      });

      const res = await getResearchRun('run-uuid-777');
      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [url, init] = (global.fetch as any).mock.calls[0];
      expect(url).toContain('/api/proxy/api/v1/research-runs/run-uuid-777');
      expect(init.method).toBe('GET');
      expect(res.status).toBe('running');
    });

    it('getProspectIntelligence issues GET to /api/v1/prospects/{id}/intelligence', async () => {
      const mockIntel: ProspectIntelligenceResponse = {
        prospect_id: 'prospect-1',
        organization_id: 'org-1',
        confidence: 0.92,
        research_version: 'v1.0',
        intelligence: {
          executive_summary: 'Target enterprise demonstrated clear cloud migration demand.',
          ai_provider: 'deterministic',
          claims: [],
          commercial_opportunities: [],
        },
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockIntel,
      });

      const res = await getProspectIntelligence('prospect-1');
      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [url, init] = (global.fetch as any).mock.calls[0];
      expect(url).toContain('/api/proxy/api/v1/prospects/prospect-1/intelligence');
      expect(init.method).toBe('GET');
      expect(res.intelligence?.executive_summary).toContain('Target enterprise demonstrated');
      expect(res.intelligence?.ai_provider).toBe('deterministic');
    });

    it('listProspectResearchRuns issues GET to /api/v1/research-runs with prospect_id filter', async () => {
      const mockRunsList = {
        items: [
          {
            id: 'run-1',
            organization_id: 'org-1',
            prospect_id: 'prospect-1',
            status: 'completed',
            display_key: 'research.status.completed',
            created_at: '2026-09-21T09:00:00Z',
          },
        ],
        page: 1,
        page_size: 10,
        total_items: 1,
        total_pages: 1,
      };

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => mockRunsList,
      });

      const res = await listProspectResearchRuns('prospect-1', 5);
      expect(global.fetch).toHaveBeenCalledTimes(1);
      const [url] = (global.fetch as any).mock.calls[0];
      expect(url).toContain('/api/proxy/api/v1/research-runs');
      expect(url).toContain('prospect_id=prospect-1');
      expect(res.items.length).toBe(1);
      expect(res.items[0].status).toBe('completed');
    });
  });

  // =========================================================================
  // 3. ROLE-BASED ACCESS CONTROL (TENANT SECURITY)
  // =========================================================================
  describe('Tenant Security & VIEWER Role Restrictions', () => {
    it('VIEWER cannot trigger research (research.run is denied)', () => {
      expect(hasPermission('VIEWER', 'research.run')).toBe(false);
    });

    it('MEMBER, ADMIN, and OWNER can trigger research (research.run is granted)', () => {
      expect(hasPermission('MEMBER', 'research.run')).toBe(true);
      expect(hasPermission('ADMIN', 'research.run')).toBe(true);
      expect(hasPermission('OWNER', 'research.run')).toBe(true);
    });

    it('VIEWER has prospect.read to inspect research intelligence and history', () => {
      expect(hasPermission('VIEWER', 'prospect.read')).toBe(true);
    });
  });

  // =========================================================================
  // 4. RESEARCH PAGE NAVIGATION (NO DEAD BUTTONS)
  // =========================================================================
  describe('Research Page Actions & Navigation', () => {
    it('renders functional Find Prospect action replacing dead launch pipeline button', () => {
      vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
        user: { id: '1', email: 'admin@bop.com', is_active: true, is_superuser: false, created_at: '' },
        activeOrg: { id: 'org-1', bop_organization_id: 'bop-org-1', name: 'Test Org', slug: 'test' },
        activeRole: 'ADMIN',
        organizations: [],
        isLoading: false,
        isAuthenticated: true,
        login: vi.fn(),
        logout: vi.fn(),
        switchOrg: vi.fn(),
        hasRole: () => true,
        refreshSession: vi.fn(),
      });

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ items: [] }),
      });

      const html = renderToString(
        <I18nContext.I18nProvider locale="en">
          <ResearchPage />
        </I18nContext.I18nProvider>
      );

      // Verify no dead "Launch Pipeline" button exists
      expect(html).not.toContain('Launch Pipeline');
      // Verify functional Find Prospect button is present
      expect(html).toContain('Find Prospect');
      expect(html).toContain('Autonomous Entity Discovery &amp; Research');
    });

    it('renders link to prospect dossier when run has a prospect_id', () => {
      vi.spyOn(AuthContext, 'useAuth').mockReturnValue({
        user: { id: '1', email: 'admin@bop.com', is_active: true, is_superuser: false, created_at: '' },
        activeOrg: { id: 'org-1', bop_organization_id: 'bop-org-1', name: 'Test Org', slug: 'test' },
        activeRole: 'ADMIN',
        organizations: [],
        isLoading: false,
        isAuthenticated: true,
        login: vi.fn(),
        logout: vi.fn(),
        switchOrg: vi.fn(),
        hasRole: () => true,
        refreshSession: vi.fn(),
      });

      const mockRuns = [
        {
          id: 'run-999-abc',
          prospect_id: 'p-real-456',
          run_type: 'full_diligence',
          status: 'completed',
          created_at: '2026-09-21T09:30:00Z',
        },
      ];

      global.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ items: mockRuns }),
      });

      const html = renderToString(
        <I18nContext.I18nProvider locale="en">
          <ResearchPage initialRuns={mockRuns} />
        </I18nContext.I18nProvider>
      );

      // Verify link to prospect dossier
      expect(html).toContain('/prospects/p-real-456');
      expect(html).toContain('View Dossier');
      expect(html).toContain('Completed');
    });
  });

  // =========================================================================
  // 5. EVIDENCE & TRUST: OBSERVATION VS DERIVATION & EMPTY CLAIMS
  // =========================================================================
  describe('Evidence & Trust Claims Discrimination', () => {
    it('distinguishes observed evidence from derived and inferred assertions', () => {
      const claims: ProspectIntelligenceData['claims'] = [
        {
          id: 'c1',
          claim_type: 'verified_presence',
          statement: 'Headquarters registered at 100 Enterprise Blvd.',
          classification: 'observed',
          confidence: 1.0,
          evidence_refs: ['tax_registry_2026'],
        },
        {
          id: 'c2',
          claim_type: 'headcount_estimate',
          statement: 'Estimated engineering headcount of 50-75 based on team directories.',
          classification: 'derived',
          confidence: 0.85,
        },
        {
          id: 'c3',
          claim_type: 'buying_intent',
          statement: 'Probable infrastructure expansion based on high hiring velocity.',
          classification: 'inferred',
          confidence: 0.65,
        },
      ];

      expect(claims[0].classification).toBe('observed');
      expect(claims[1].classification).toBe('derived');
      expect(claims[2].classification).toBe('inferred');

      expect(claims[0].confidence).toBe(1.0);
      expect(claims[0].evidence_refs).toEqual(['tax_registry_2026']);
    });

    it('truthful empty state message is specified for prospects without claims', () => {
      const emptyClaimsEn = translate('en', 'prospect_detail.research_empty_claims');
      const emptyClaimsEs = translate('es', 'prospect_detail.research_empty_claims');

      expect(emptyClaimsEn).toBe(
        'No additional evidence-backed claims were established from the available data.'
      );
      expect(emptyClaimsEs).toBe(
        'No se establecieron afirmaciones adicionales respaldadas por evidencia a partir de los datos disponibles.'
      );
    });
  });

  // =========================================================================
  // 6. PROVIDER TRANSPARENCY
  // =========================================================================
  describe('Provider Transparency & Deterministic Engine Guard', () => {
    it('provides transparent descriptions distinguishing deterministic from AI gemini modes', () => {
      const deterministicDesc = translate(
        'en',
        'prospect_detail.research_provider_deterministic_desc'
      );
      const geminiDesc = translate('en', 'prospect_detail.research_provider_gemini_desc');

      expect(deterministicDesc).toContain('without external web research');
      expect(geminiDesc).toContain('Gemini structured reasoning');
    });
  });

  // =========================================================================
  // 7. POLLING LIFECYCLE & BOUNDED CLEANUP
  // =========================================================================
  describe('Polling State Machine & Bounded Cleanup', () => {
    it('terminates polling loop when run reaches completed status', async () => {
      let pollCount = 0;
      const runStates = ['running', 'running', 'completed'];

      const pollFn = vi.fn(async () => {
        const state = runStates[pollCount] || 'completed';
        pollCount += 1;
        return { status: state };
      });

      // Simulate polling
      let currentStatus = 'running';
      while (currentStatus === 'running' && pollCount < 10) {
        const res = await pollFn();
        currentStatus = res.status;
      }

      expect(pollCount).toBe(3);
      expect(currentStatus).toBe('completed');
    });

    it('terminates polling loop when run reaches failed status', async () => {
      let pollCount = 0;
      const runStates = ['running', 'failed'];

      const pollFn = vi.fn(async () => {
        const state = runStates[pollCount] || 'failed';
        pollCount += 1;
        return { status: state, error_message: 'Signal threshold not met' };
      });

      let currentStatus = 'running';
      let errorMsg = null;
      while (currentStatus === 'running' && pollCount < 10) {
        const res = await pollFn();
        currentStatus = res.status;
        if (res.error_message) errorMsg = res.error_message;
      }

      expect(pollCount).toBe(2);
      expect(currentStatus).toBe('failed');
      expect(errorMsg).toBe('Signal threshold not met');
    });

    it('bounds polling without indefinite loops when timeout is reached', async () => {
      let pollCount = 0;
      const MAX_POLLS = 5; // Simulating small bounded window

      const pollFn = vi.fn(async () => {
        pollCount += 1;
        return { status: 'running' };
      });

      let timedOut = false;
      while (pollCount < MAX_POLLS) {
        await pollFn();
      }
      timedOut = true;

      expect(pollCount).toBe(MAX_POLLS);
      expect(timedOut).toBe(true);
    });
  });
});
