'use client';

import React, { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { useSearchParams, useRouter } from 'next/navigation';
import { useI18n } from '@/lib/i18n/context';
import { useAuth } from '@/lib/auth/context';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { DataTable, Column } from '@/components/ui/DataTable';
import { ErrorState } from '@/components/states/ErrorState';
import { PermissionGate } from '@/components/navigation/PermissionGate';
import {
  Compass,
  Sparkles,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  ExternalLink,
  Layers,
  Users,
} from 'lucide-react';
import {
  SearchIntent,
  SearchPlan,
  DiscoveryExecutionResult,
  DiscoveredProspectSummary,
} from '@/lib/api/types';

interface CampaignItem {
  id: string;
  name: string;
  status: string;
  icp_id?: string | null;
}

interface TargetMarketItem {
  id: string;
  country: string;
  region?: string | null;
  city?: string | null;
  postal_code?: string | null;
  radius_miles?: number | null;
  language: string;
}

export default function DiscoveryPage() {
  const { t, locale } = useI18n();
  const { activeOrg } = useAuth();
  const searchParams = useSearchParams();
  const router = useRouter();

  const preselectedCampaignId = searchParams.get('campaignId') || '';

  // Campaigns list for selector
  const [campaigns, setCampaigns] = useState<CampaignItem[]>([]);
  const [selectedCampaignId, setSelectedCampaignId] = useState<string>(preselectedCampaignId);

  // Target markets for selected campaign ICP
  const [targetMarkets, setTargetMarkets] = useState<TargetMarketItem[]>([]);
  const [selectedMarketId, setSelectedMarketId] = useState<string>('');

  // Discovery Pipeline States
  const [prompt, setPrompt] = useState('');
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);

  const [parsing, setParsing] = useState(false);
  const [intent, setIntent] = useState<SearchIntent | null>(null);

  const [planning, setPlanning] = useState(false);
  const [plan, setPlan] = useState<SearchPlan | null>(null);

  const [executing, setExecuting] = useState(false);
  const [executionResult, setExecutionResult] = useState<DiscoveryExecutionResult | null>(null);

  const [error, setError] = useState<string | null>(null);

  // Fetch campaigns
  useEffect(() => {
    async function loadCampaigns() {
      try {
        const res = await fetch('/api/proxy/api/v1/campaigns', { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          const items: CampaignItem[] = data.items || [];
          setCampaigns(items);
          if (!selectedCampaignId && items.length > 0) {
            const active = items.find((c) => c.status?.toLowerCase() === 'active');
            if (active) setSelectedCampaignId(active.id);
            else setSelectedCampaignId(items[0].id);
          }
        }
      } catch {
        // Handled silently
      }
    }
    loadCampaigns();
  }, [activeOrg, selectedCampaignId]);

  // Fetch target markets whenever selected campaign changes
  useEffect(() => {
    setSelectedMarketId('');
    setTargetMarkets([]);
    if (!selectedCampaignId) return;

    const camp = campaigns.find((c) => c.id === selectedCampaignId);
    if (!camp?.icp_id) return;

    fetch(`/api/proxy/api/v1/icps/${camp.icp_id}`, { credentials: 'include' })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.target_markets && Array.isArray(data.target_markets)) {
          setTargetMarkets(data.target_markets);
        }
      })
      .catch(() => {});
  }, [selectedCampaignId, campaigns]);

  // Step 1: Parse Intent
  const handleParseIntent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;

    setParsing(true);
    setError(null);
    setIntent(null);
    setPlan(null);
    setExecutionResult(null);

    try {
      const res = await fetch('/api/proxy/api/v1/discovery/intents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          raw_query: prompt.trim(),
          campaign_id: selectedCampaignId || undefined,
          target_market_id: selectedMarketId || undefined,
        }),
        credentials: 'include',
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || `Failed to parse intent (${res.status})`);
      }

      const data: SearchIntent = await res.json();
      setIntent(data);
      setStep(2);
    } catch (err: any) {
      setError(err.message || 'Error parsing search intent');
    } finally {
      setParsing(false);
    }
  };

  // Step 2: Generate Plan
  const handleGeneratePlan = async () => {
    if (!intent) return;
    setPlanning(true);
    setError(null);
    setPlan(null);

    try {
      const res = await fetch('/api/proxy/api/v1/discovery/plans', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...intent,
          campaign_id: selectedCampaignId || undefined,
        }),
        credentials: 'include',
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || `Failed to generate search plan (${res.status})`);
      }

      const data: SearchPlan = await res.json();
      setPlan(data);
      setStep(3);
    } catch (err: any) {
      setError(err.message || 'Error generating search plan');
    } finally {
      setPlanning(false);
    }
  };

  // Step 3: Execute Discovery
  const handleExecute = async () => {
    const activeCamp = campaigns.find((c) => c.id === selectedCampaignId);
    if (activeCamp && activeCamp.status?.toLowerCase() !== 'active') {
      setError(t('discovery.campaign_inactive', { name: activeCamp.name, status: activeCamp.status }));
      return;
    }

    setExecuting(true);
    setError(null);
    setExecutionResult(null);

    try {
      const res = await fetch('/api/proxy/api/v1/discovery/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          search_plan: plan,
          campaign_id: selectedCampaignId,
        }),
        credentials: 'include',
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || `Failed to execute discovery (${res.status})`);
      }

      const data: DiscoveryExecutionResult = await res.json();
      setExecutionResult(data);
      setStep(4);
    } catch (err: any) {
      setError(err.message || 'Error executing discovery plan');
    } finally {
      setExecuting(false);
    }
  };

  // Result table columns
  const prospectColumns: Column<DiscoveredProspectSummary>[] = [
    {
      header: t('prospects.columns.name'),
      accessorKey: 'name',
      cell: (row) => (
        <div className="font-semibold text-foreground flex items-center gap-1.5">
          <Link
            href={`/${locale}/prospects/${row.id}`}
            className="hover:text-brand-gold flex items-center gap-1 transition-colors"
          >
            <span>{row.name}</span>
            <ExternalLink className="w-3 h-3 text-foreground-muted" />
          </Link>
        </div>
      ),
    },
    {
      header: t('prospects.columns.industry'),
      accessorKey: 'industry',
      cell: (row) => (
        <span className="text-xs text-foreground-muted">{row.industry || '—'}</span>
      ),
    },
    {
      header: 'Location',
      cell: (row) => {
        const loc = [row.city, row.state, row.country].filter(Boolean).join(', ');
        return <span className="text-xs text-foreground-muted">{loc || '—'}</span>;
      },
    },
    {
      header: 'Source',
      accessorKey: 'source',
      cell: (row) => (
        <Badge size="sm" variant="outline">
          {row.source || 'forge'}
        </Badge>
      ),
    },
  ];

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Page Header */}
      <div>
        <div className="flex items-center gap-2 mb-1">
          <Compass className="w-6 h-6 text-brand-gold" />
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            {t('discovery.title')}
          </h1>
        </div>
        <p className="text-xs text-foreground-muted">
          {t('discovery.subtitle')}
        </p>
      </div>

      {/* Language / Provider Boundary Notice */}
      <div className="p-3 bg-surface-subtle border border-border/80 rounded-lg text-xs text-foreground-muted flex items-start gap-2">
        <Sparkles className="w-4 h-4 text-brand-gold shrink-0 mt-0.5" />
        <span>{t('discovery.language_notice')}</span>
      </div>

      {/* Error Alert */}
      {error && <ErrorState message={error} onRetry={() => setError(null)} />}

      {/* Step 1: Input & Campaign Selector */}
      <div className="p-5 rounded-lg border border-border bg-surface space-y-4">
        <form onSubmit={handleParseIntent} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="md:col-span-2">
              <label className="block text-xs font-semibold text-foreground mb-1">
                {t('discovery.prompt_label')} *
              </label>
              <textarea
                rows={3}
                required
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder={t('discovery.prompt_placeholder')}
                className="w-full p-2.5 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark resize-none"
              />
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-foreground mb-1">
                  {t('discovery.campaign_label')} *
                </label>
                <select
                  value={selectedCampaignId}
                  onChange={(e) => setSelectedCampaignId(e.target.value)}
                  className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-brand-dark"
                >
                  <option value="">{t('discovery.campaign_placeholder')}</option>
                  {campaigns.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({c.status})
                    </option>
                  ))}
                </select>
                {campaigns.length === 0 && (
                  <p className="text-[11px] text-danger mt-1">
                    {t('discovery.no_active_campaigns')}
                  </p>
                )}
              </div>

              {targetMarkets.length > 1 && (
                <div>
                  <label className="block text-xs font-semibold text-foreground mb-1">
                    Target Market
                  </label>
                  <select
                    value={selectedMarketId}
                    onChange={(e) => setSelectedMarketId(e.target.value)}
                    className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-brand-dark"
                  >
                    <option value="">Select Target Market...</option>
                    {targetMarkets.map((tm) => (
                      <option key={tm.id} value={tm.id}>
                        {[tm.city, tm.region, tm.country].filter(Boolean).join(', ')}{tm.radius_miles ? ` (${tm.radius_miles} mi)` : ''}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          </div>

          <div className="flex justify-end">
            <PermissionGate permission="campaign.create">
              <Button type="submit" size="sm" disabled={parsing || !prompt.trim()}>
                {parsing ? (
                  <>
                    <div className="animate-spin h-3.5 w-3.5 border-2 border-surface border-t-transparent rounded-full mr-2" />
                    {t('discovery.parsing')}
                  </>
                ) : (
                  <>
                    {t('discovery.parse_button')}
                    <ArrowRight className="w-3.5 h-3.5 ml-1.5" />
                  </>
                )}
              </Button>
            </PermissionGate>
          </div>
        </form>
      </div>

      {/* Step 2: Parsed Search Intent Preview */}
      {intent && (
        <div className="p-5 rounded-lg border border-border bg-surface space-y-4 animate-in fade-in duration-200">
          <div className="flex items-center justify-between border-b border-border pb-3">
            <div>
              <h2 className="text-sm font-bold text-foreground flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-brand-gold" />
                {t('discovery.intent_title')}
              </h2>
              <p className="text-xs text-foreground-muted mt-0.5">
                {t('discovery.intent_subtitle')}
              </p>
            </div>
            <Badge size="sm" variant="outline">
              Lang: {intent.languages?.[0]?.toUpperCase() || '—'}
            </Badge>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-3 text-xs">
            <div className="p-3 bg-surface-subtle rounded-md">
              <p className="text-foreground-muted font-medium mb-1">{t('discovery.target_industries')}</p>
              <div className="flex flex-wrap gap-1">
                {intent.industries && intent.industries.length > 0 ? (
                  intent.industries.map((ind) => (
                    <Badge key={ind} size="sm" variant="default">
                      {ind}
                    </Badge>
                  ))
                ) : (
                  <span className="text-foreground-muted">—</span>
                )}
              </div>
            </div>

            <div className="p-3 bg-surface-subtle rounded-md">
              <p className="text-foreground-muted font-medium mb-1">{t('discovery.target_locations')}</p>
              <div className="flex flex-wrap items-center gap-1">
                {intent.cities && intent.cities.length > 0 ? (
                  intent.cities.map((loc) => (
                    <Badge key={loc} size="sm" variant="outline">
                      {loc}
                    </Badge>
                  ))
                ) : (
                  <span className="text-foreground-muted">—</span>
                )}
                {intent.radius_miles ? (
                  <Badge size="sm" variant="outline" className="text-brand-dark border-brand-dark/30">
                    {intent.radius_miles} mi
                  </Badge>
                ) : null}
              </div>
            </div>

            <div className="p-3 bg-surface-subtle rounded-md">
              <p className="text-foreground-muted font-medium mb-1">{t('discovery.company_size')}</p>
              <span className="text-foreground font-mono">
                {intent.company_sizes && intent.company_sizes.length > 0
                  ? intent.company_sizes.join(', ')
                  : `${intent.company_size_min || 1} - ${intent.company_size_max || 'Any'}`}
              </span>
            </div>
          </div>

          {intent.keywords && intent.keywords.length > 0 && (
            <div className="text-xs">
              <span className="text-foreground-muted mr-2">{t('discovery.extracted_keywords')}</span>
              <span className="font-mono text-foreground">{intent.keywords.join(', ')}</span>
            </div>
          )}

          {intent.negative_keywords && intent.negative_keywords.length > 0 && (
            <div className="text-xs">
              <span className="text-danger font-medium mr-2">{t('discovery.excluded_keywords')}</span>
              <span className="font-mono text-danger/90">{intent.negative_keywords.join(', ')}</span>
            </div>
          )}

          <div className="flex justify-end pt-2">
            <PermissionGate permission="campaign.create">
              <Button size="sm" onClick={handleGeneratePlan} disabled={planning}>
                {planning ? (
                  <>
                    <div className="animate-spin h-3.5 w-3.5 border-2 border-surface border-t-transparent rounded-full mr-2" />
                    {t('discovery.planning')}
                  </>
                ) : (
                  <>
                    {t('discovery.plan_button')}
                    <ArrowRight className="w-3.5 h-3.5 ml-1.5" />
                  </>
                )}
              </Button>
            </PermissionGate>
          </div>
        </div>
      )}

      {/* Step 3: Search Plan Preview */}
      {plan && (
        <div className="p-5 rounded-lg border border-border bg-surface space-y-4 animate-in fade-in duration-200">
          <div className="flex items-center justify-between border-b border-border pb-3">
            <div>
              <h2 className="text-sm font-bold text-foreground flex items-center gap-2">
                <Layers className="w-4 h-4 text-brand-gold" />
                {t('discovery.plan_title')}
              </h2>
              <p className="text-xs text-foreground-muted mt-0.5">
                {t('discovery.plan_subtitle')}
              </p>
            </div>
            <Badge size="sm" variant="default">
              {t('discovery.plan_tasks_count', { count: plan.tasks?.length || 0 })}
            </Badge>
          </div>

          {/* Warnings */}
          {plan.warnings && plan.warnings.length > 0 && (
            <div className="p-3 bg-warning/10 border border-warning/30 rounded-md text-xs text-warning space-y-1">
              <div className="font-semibold flex items-center gap-1">
                <AlertTriangle className="w-4 h-4" />
                {t('discovery.warnings_title')}
              </div>
              <ul className="list-disc list-inside space-y-0.5 text-[11px]">
                {plan.warnings.map((w, idx) => (
                  <li key={idx}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Tasks Breakdown */}
          <div className="space-y-2">
            {plan.tasks?.map((task, idx) => (
              <div
                key={task.task_id || idx}
                className="p-3 bg-surface-subtle rounded-md border border-border/60 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs"
              >
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <Badge size="sm" variant="outline">
                      {task.provider}
                    </Badge>
                    <span className="font-semibold text-foreground">
                      {task.query_params?.query || 'General Search'}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 text-foreground-muted text-[11px]">
                    {task.query_params?.city && <span>City: {task.query_params.city}</span>}
                    {task.query_params?.region && <span>Region: {task.query_params.region}</span>}
                    {task.query_params?.country && <span>Country: {task.query_params.country}</span>}
                    {task.query_params?.category && <span>Category: {task.query_params.category}</span>}
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <span className="text-[11px] text-foreground-muted font-mono">
                    Limit: {task.query_params?.limit || task.estimated_items || 100}
                  </span>
                </div>
              </div>
            ))}
          </div>

          <div className="flex justify-end pt-2">
            <PermissionGate permission="campaign.create">
              <Button
                size="sm"
                onClick={handleExecute}
                disabled={executing || !selectedCampaignId}
              >
                {executing ? (
                  <>
                    <div className="animate-spin h-3.5 w-3.5 border-2 border-surface border-t-transparent rounded-full mr-2" />
                    {t('discovery.executing')}
                  </>
                ) : (
                  <>
                    <Sparkles className="w-3.5 h-3.5 mr-1.5 text-brand-gold" />
                    {t('discovery.execute_button')}
                  </>
                )}
              </Button>
            </PermissionGate>
          </div>
        </div>
      )}

      {/* Step 4: Execution Results */}
      {executionResult && (
        <div className="p-5 rounded-lg border border-border bg-surface space-y-5 animate-in fade-in duration-200">
          <div className="flex items-center justify-between border-b border-border pb-3">
            <div>
              <h2 className="text-sm font-bold text-foreground flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-success" />
                {t('discovery.results_title')}
              </h2>
              <p className="text-xs text-foreground-muted mt-0.5">
                Campaign pipeline updated with deduplicated discovery records
              </p>
            </div>
            <Badge
              size="sm"
              variant={executionResult.status === 'completed' ? 'success' : 'warning'}
            >
              {executionResult.status === 'completed'
                ? t('discovery.status_completed')
                : t('discovery.status_partial')}
            </Badge>
          </div>

          {/* Metric Counters */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs">
            <div className="p-3 bg-surface-subtle rounded-md text-center">
              <p className="text-foreground-muted">{t('discovery.tasks_executed')}</p>
              <p className="text-xl font-bold text-foreground mt-1">
                {executionResult.tasks_executed || 0}
              </p>
            </div>
            <div className="p-3 bg-surface-subtle rounded-md text-center">
              <p className="text-foreground-muted">{t('discovery.discovered_count')}</p>
              <p className="text-xl font-bold text-foreground mt-1">
                {executionResult.discovered_businesses_count || 0}
              </p>
            </div>
            <div className="p-3 bg-surface-subtle rounded-md text-center">
              <p className="text-foreground-muted">{t('discovery.created_count')}</p>
              <p className="text-xl font-bold text-success mt-1">
                {executionResult.prospects_created || 0}
              </p>
            </div>
            <div className="p-3 bg-surface-subtle rounded-md text-center">
              <p className="text-foreground-muted">{t('discovery.reused_count')}</p>
              <p className="text-xl font-bold text-brand-gold mt-1">
                {executionResult.prospects_reused || 0}
              </p>
            </div>
            <div className="p-3 bg-surface-subtle rounded-md text-center">
              <p className="text-foreground-muted">{t('discovery.imported_count')}</p>
              <p className="text-xl font-bold text-foreground mt-1">
                {executionResult.total_imported_prospects || 0}
              </p>
            </div>
          </div>

          {/* Discovered Prospects Table */}
          {executionResult.imported_prospects && executionResult.imported_prospects.length > 0 ? (
            <div className="space-y-2">
              <h3 className="text-xs font-bold text-foreground">
                Imported Entities ({executionResult.imported_prospects.length})
              </h3>
              <DataTable
                columns={prospectColumns}
                data={executionResult.imported_prospects}
                isLoading={false}
                emptyMessage={t('discovery.no_results')}
              />
            </div>
          ) : (
            <p className="text-xs text-foreground-muted text-center py-4">
              {t('discovery.no_results')}
            </p>
          )}

          {/* Outcome Navigation CTAs */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-border">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setStep(1);
                setIntent(null);
                setPlan(null);
                setExecutionResult(null);
              }}
            >
              <RotateCcw className="w-3.5 h-3.5 mr-1.5" />
              New Discovery Query
            </Button>

            <div className="flex items-center gap-2">
              {selectedCampaignId && (
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => router.push(`/${locale}/campaigns/${selectedCampaignId}`)}
                >
                  <Users className="w-3.5 h-3.5 mr-1.5" />
                  {t('discovery.view_campaign_prospects')}
                </Button>
              )}
              <Button
                size="sm"
                onClick={() => router.push(`/${locale}/prospects`)}
              >
                {t('discovery.view_prospects')}
                <ArrowRight className="w-3.5 h-3.5 ml-1.5" />
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
