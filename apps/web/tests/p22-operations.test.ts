import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  bulkAddToCampaign,
  bulkRecalculateScore,
  bulkRecalculatePriority,
  bulkResearch,
  exportProspectsCsv,
  exportSelectedProspectsCsv,
} from '../lib/api/client';
import en from '../messages/en.json';
import es from '../messages/es.json';
import { translate } from '../lib/i18n';

describe('P22 Prospect Operations & Daily Productivity Frontend Contract', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('has 100% translation key parity for all P22 operations and bulk features', () => {
    const p22Keys = [
      'prospects.search_placeholder',
      'prospects.filter_all_priorities',
      'prospects.filter_all_campaigns',
      'prospects.filter_with_signals',
      'prospects.filter_all_scores',
      'prospects.filter_score_high',
      'prospects.filter_score_med',
      'prospects.filter_score_low',
      'prospects.filter_unscored',
      'prospects.filter_reset',
      'prospects.bulk.selected_count',
      'prospects.bulk.select_all',
      'prospects.bulk.clear_selection',
      'prospects.bulk.add_to_campaign',
      'prospects.bulk.recalculate_score',
      'prospects.bulk.recalculate_priority',
      'prospects.bulk.run_research',
      'prospects.bulk.export_selected',
      'prospects.bulk.export_all',
      'prospects.bulk.modal_campaign_title',
      'prospects.bulk.modal_campaign_select',
      'prospects.bulk.modal_campaign_choose',
      'prospects.bulk.modal_campaign_submit',
      'prospects.bulk.success_added',
      'prospects.bulk.success_scored',
      'prospects.bulk.success_prioritized',
      'prospects.bulk.success_research',
      'prospects.bulk.max_limit_exceeded',
      'prospects.columns.lead_score',
      'prospects.columns.campaigns',
      'prospects.columns.signals',
      'campaigns.view_in_workspace',
    ];

    for (const key of p22Keys) {
      const enVal = translate('en', key);
      const esVal = translate('es', key);
      expect(enVal, `Missing EN translation for ${key}`).not.toBe(key);
      expect(esVal, `Missing ES translation for ${key}`).not.toBe(key);
      expect(enVal.length).toBeGreaterThan(0);
      expect(esVal.length).toBeGreaterThan(0);
    }
  });

  it('bulkAddToCampaign calls the correct proxy endpoint with credentials', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        campaign_id: 'c-1',
        added_count: 2,
        already_present_count: 0,
        prospect_ids_added: ['p-1', 'p-2'],
        prospect_ids_skipped: [],
      }),
    } as Response);
    global.fetch = fetchSpy;

    const res = await bulkAddToCampaign({
      campaign_id: 'c-1',
      prospect_ids: ['p-1', 'p-2'],
    });

    expect(res.added_count).toBe(2);
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/proxy/api/v1/prospects/bulk/add-to-campaign',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({ campaign_id: 'c-1', prospect_ids: ['p-1', 'p-2'] }),
      })
    );
  });

  it('bulkRecalculateScore and bulkRecalculatePriority call correct endpoints', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        total_requested: 1,
        processed_count: 1,
        scored_count: 1,
        prioritized_count: 1,
        failed_count: 0,
        results: [],
      }),
    } as Response);
    global.fetch = fetchSpy;

    await bulkRecalculateScore({ prospect_ids: ['p-1'] });
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/proxy/api/v1/prospects/bulk/recalculate-score',
      expect.objectContaining({ method: 'POST' })
    );

    await bulkRecalculatePriority({ prospect_ids: ['p-1'], campaign_id: 'c-1' });
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/proxy/api/v1/prospects/bulk/recalculate-priority',
      expect.objectContaining({ method: 'POST' })
    );
  });

  it('bulkResearch triggers batch enrichment runs with campaign context', async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        success: true,
        total_requested: 2,
        triggered_count: 2,
        skipped_count: 0,
        runs: [],
      }),
    } as Response);
    global.fetch = fetchSpy;

    const res = await bulkResearch({
      prospect_ids: ['p-1', 'p-2'],
      campaign_id: 'c-1',
      run_type: 'bulk_enrichment',
    });

    expect(res.triggered_count).toBe(2);
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/proxy/api/v1/prospects/bulk/research',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({
          prospect_ids: ['p-1', 'p-2'],
          campaign_id: 'c-1',
          run_type: 'bulk_enrichment',
        }),
      })
    );
  });

  it('exportProspectsCsv and exportSelectedProspectsCsv download CSV blobs via proxy', async () => {
    const mockBlob = new Blob(['name,email\nAcme,info@acme.com'], { type: 'text/csv' });
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => mockBlob,
    } as Response);
    global.fetch = fetchSpy;

    const blob1 = await exportProspectsCsv({ search: 'Acme', priority: 'high' });
    expect(blob1).toBe(mockBlob);
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/proxy/api/v1/prospects/export?search=Acme&priority=high',
      expect.objectContaining({ credentials: 'include' })
    );

    const blob2 = await exportSelectedProspectsCsv({ prospect_ids: ['p-1', 'p-2'] });
    expect(blob2).toBe(mockBlob);
    expect(fetchSpy).toHaveBeenCalledWith(
      '/api/proxy/api/v1/prospects/export',
      expect.objectContaining({
        method: 'POST',
        credentials: 'include',
        body: JSON.stringify({ prospect_ids: ['p-1', 'p-2'] }),
      })
    );
  });
});
