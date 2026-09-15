import { describe, it, expect } from 'vitest';
import en from '../messages/en.json';
import es from '../messages/es.json';
import { translate } from '../lib/i18n';

describe('P21 Prospecting Workflows & Discovery Contract Test', () => {
  it('contains all discovery translation keys in both languages', () => {
    const requiredDiscoveryKeys = [
      'discovery.title',
      'discovery.subtitle',
      'discovery.prompt_label',
      'discovery.prompt_placeholder',
      'discovery.campaign_label',
      'discovery.language_notice',
      'discovery.parse_button',
      'discovery.intent_title',
      'discovery.plan_button',
      'discovery.plan_title',
      'discovery.execute_button',
      'discovery.results_title',
      'discovery.tasks_executed',
      'discovery.discovered_count',
      'discovery.created_count',
      'discovery.reused_count',
      'discovery.view_campaign_prospects',
      'discovery.view_prospects',
    ];

    for (const key of requiredDiscoveryKeys) {
      const enVal = translate('en', key);
      const esVal = translate('es', key);
      expect(enVal, `Missing EN translation for ${key}`).not.toBe(key);
      expect(esVal, `Missing ES translation for ${key}`).not.toBe(key);
      expect(enVal.length).toBeGreaterThan(0);
      expect(esVal.length).toBeGreaterThan(0);
    }
  });

  it('contains prospect detail and scoring tooltip translations in both languages', () => {
    const requiredDossierKeys = [
      'prospect_detail.title',
      'prospect_detail.subtitle',
      'prospect_detail.lead_score_title',
      'prospect_detail.lead_score_tooltip',
      'prospect_detail.priority_title',
      'prospect_detail.priority_tooltip',
      'prospect_detail.evidence_observed',
      'prospect_detail.evidence_derived',
      'prospect_detail.evidence_inferred',
      'prospect_detail.recalculate_score',
      'prospect_detail.recalculate_priority',
      'prospect_detail.research_button',
    ];

    for (const key of requiredDossierKeys) {
      const enVal = translate('en', key);
      const esVal = translate('es', key);
      expect(enVal, `Missing EN translation for ${key}`).not.toBe(key);
      expect(esVal, `Missing ES translation for ${key}`).not.toBe(key);
      expect(enVal.length).toBeGreaterThan(0);
      expect(esVal.length).toBeGreaterThan(0);
    }

    // Check specific tooltip content explaining the metric
    const enScoreTooltip = translate('en', 'prospect_detail.lead_score_tooltip');
    expect(enScoreTooltip).toContain('0-100');
    expect(enScoreTooltip.toLowerCase()).toContain('fit');

    const esScoreTooltip = translate('es', 'prospect_detail.lead_score_tooltip');
    expect(esScoreTooltip).toContain('0-100');
    expect(esScoreTooltip.toLowerCase()).toContain('ajuste');
  });

  it('contains campaign workflow enhancements in both languages', () => {
    expect(translate('en', 'campaigns.run_discovery')).toBe('Run Discovery');
    expect(translate('es', 'campaigns.run_discovery')).toBe('Ejecutar Descubrimiento');

    expect(translate('en', 'campaigns.prospects_tab')).toBe('Campaign Prospects');
    expect(translate('es', 'campaigns.prospects_tab')).toBe('Prospectos de la Campaña');
  });
});
