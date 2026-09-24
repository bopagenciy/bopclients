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
  AlertCircle,
  AlertTriangle,
  RotateCcw,
  ExternalLink,
  Layers,
  Users,
  Search,
  Globe,
  X,
  Info,
  Activity,
} from 'lucide-react';
import {
  SearchIntent,
  SearchPlan,
  DiscoveryExecutionResult,
  DiscoveredProspectSummary,
  DiscoveryPreviewRequest,
  DiscoveryPreviewResponse,
  DiscoveryCandidateSummary,
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

function formatApiError(err: any, fallbackMessage: string): string {
  if (!err) return fallbackMessage;
  let msg = err.error?.message || err.message || fallbackMessage;
  if (err.error?.details) {
    if (typeof err.error.details === 'string') {
      msg = `${msg} (${err.error.details})`;
    } else if (Array.isArray(err.error.details)) {
      const dStr = err.error.details.map((d: any) => d.msg || JSON.stringify(d)).join(', ');
      if (dStr) msg = `${msg} (${dStr})`;
    } else if (typeof err.error.details === 'object') {
      const detailEntries = Object.entries(err.error.details).map(([k, v]) => `${k}: ${v}`);
      if (detailEntries.length > 0) {
        msg = `${msg} (${detailEntries.join(', ')})`;
      }
    }
  } else if (err.detail) {
    if (typeof err.detail === 'string') {
      msg = err.detail;
    } else if (Array.isArray(err.detail)) {
      const dStr = err.detail.map((d: any) => d.msg || JSON.stringify(d)).join(', ');
      if (dStr) msg = `${msg} (${dStr})`;
    }
  }
  return msg;
}

function formatEnumFallback(value: string): string {
  if (!value) return '';
  return value
    .toLowerCase()
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

function formatEntityArchetype(t: (k: string, p?: any) => string, archetype?: string | null): string {
  if (!archetype) return t('discovery.enums.archetype.UNKNOWN');
  const key = `discovery.enums.archetype.${archetype}`;
  const translated = t(key);
  if (translated === key) {
    return formatEnumFallback(archetype);
  }
  return translated;
}

function formatGeographicStatus(t: (k: string, p?: any) => string, status?: string | null): string {
  if (!status) return t('discovery.enums.geographic.UNKNOWN');
  const key = `discovery.enums.geographic.${status}`;
  const translated = t(key);
  if (translated === key) {
    return formatEnumFallback(status);
  }
  return translated;
}

function formatActivityStatus(t: (k: string, p?: any) => string, status?: string | null): string {
  if (!status) return t('discovery.enums.activity.UNKNOWN');
  const key = `discovery.enums.activity.${status}`;
  const translated = t(key);
  if (translated === key) {
    return formatEnumFallback(status);
  }
  return translated;
}

function formatSectorOrClassification(
  t: (k: string, p?: any) => string,
  category?: string | null,
  classificationStatus?: string | null
): string {
  if (category) {
    const key = `discovery.enums.sector.${category}`;
    const translated = t(key);
    if (translated !== key) return translated;
    return formatEnumFallback(category);
  }
  if (classificationStatus) {
    const key = `discovery.enums.classification.${classificationStatus}`;
    const translated = t(key);
    if (translated !== key) return translated;
    return formatEnumFallback(classificationStatus);
  }
  return '';
}

function formatRejectionReason(t: (k: string, p?: any) => string, reasonKey: string): string {
  const key = `discovery.diagnostics.reasons.${reasonKey}`;
  const translated = t(key);
  if (translated !== key) return translated;
  return formatEnumFallback(reasonKey);
}

function getQualificationBadge(status?: string | null) {
  switch (status) {
    case 'READY_FOR_COMMERCIAL_REVIEW':
      return {
        variant: 'success' as const,
        labelKey: 'discovery.status_ready',
        fallback: 'Ready for Commercial Review',
        className: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30',
      };
    case 'SEARCH_MATCH':
      return {
        variant: 'warning' as const,
        labelKey: 'discovery.status_search_match',
        fallback: 'Search Match (Requires Qualification)',
        className: 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30',
      };
    case 'INSUFFICIENT_EVIDENCE':
      return {
        variant: 'outline' as const,
        labelKey: 'discovery.status_insufficient',
        fallback: 'Insufficient Evidence',
        className: 'bg-slate-500/10 text-slate-600 dark:text-slate-400 border-slate-500/30',
      };
    case 'REJECTED':
      return {
        variant: 'danger' as const,
        labelKey: 'discovery.status_rejected',
        fallback: 'Rejected',
        className: 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/30',
      };
    default:
      return {
        variant: 'outline' as const,
        labelKey: status ? `discovery.enums.qualification.${status}` : null,
        fallback: status ? formatEnumFallback(status) : 'Unknown Status',
        className: '',
      };
  }
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

  // Ephemeral Controlled Preview States (Phase P30.5G.5G)
  const [previewing, setPreviewing] = useState(false);
  const [previewResult, setPreviewResult] = useState<DiscoveryPreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  // Guard against race conditions and stale in-flight preview responses
  const selectedCampaignRef = React.useRef(selectedCampaignId);
  useEffect(() => {
    selectedCampaignRef.current = selectedCampaignId;
  }, [selectedCampaignId]);

  // Invalidate preview results when campaign or active organization changes
  useEffect(() => {
    setPreviewResult(null);
    setPreviewError(null);
  }, [selectedCampaignId, activeOrg]);

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
        throw new Error(formatApiError(err, `Failed to parse intent (${res.status})`));
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
        throw new Error(formatApiError(err, `Failed to generate search plan (${res.status})`));
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
        throw new Error(formatApiError(err, `Failed to execute discovery (${res.status})`));
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

  // Controlled Web Search Preview (ephemeral, 0 writes)
  const handlePreview = async (usePlan: boolean = false) => {
    if (!selectedCampaignId) return;

    const requestCampaignId = selectedCampaignId;
    setPreviewing(true);
    setPreviewError(null);
    setPreviewResult(null);

    try {
      const payload: DiscoveryPreviewRequest = {
        campaign_id: requestCampaignId,
        raw_query: !usePlan && prompt.trim() ? prompt.trim() : undefined,
        search_plan: usePlan && plan ? plan : undefined,
      };

      const res = await fetch('/api/proxy/api/v1/discovery/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        credentials: 'include',
      });

      const data: DiscoveryPreviewResponse = await res.json().catch(() => null);

      // Discard response if selected campaign changed while request was in-flight
      if (selectedCampaignRef.current !== requestCampaignId) {
        return;
      }

      if (!res.ok) {
        const msg = formatApiError(data, `Preview request failed (${res.status})`);
        setPreviewError(msg);
        return;
      }

      if (!data) {
        setPreviewError('Failed to parse preview response');
        return;
      }

      setPreviewResult(data);
    } catch (err: any) {
      if (selectedCampaignRef.current === requestCampaignId) {
        setPreviewError(err.message || 'Error executing discovery preview');
      }
    } finally {
      if (selectedCampaignRef.current === requestCampaignId) {
        setPreviewing(false);
      }
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

          <div className="flex items-center justify-end gap-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              data-testid="web-search-preview-button"
              disabled={previewing || !selectedCampaignId}
              onClick={() => handlePreview(false)}
            >
              {previewing ? (
                <>
                  <div className="animate-spin h-3.5 w-3.5 border-2 border-surface border-t-transparent rounded-full mr-2" />
                  {t('discovery.previewing')}
                </>
              ) : (
                <>
                  <Search className="w-3.5 h-3.5 mr-1.5 text-brand-gold" />
                  {t('discovery.preview_button')}
                </>
              )}
            </Button>
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

      {/* Preview Error State */}
      {previewError && (
        <ErrorState
          message={previewError}
          onRetry={() => setPreviewError(null)}
        />
      )}

      {/* Controlled Discovery Preview Results Panel */}
      {previewResult && (
        <div
          data-testid="discovery-preview-panel"
          className="p-5 rounded-lg border border-border bg-surface space-y-4 animate-in fade-in duration-200"
        >
          {/* Panel Header */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border pb-3">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <Search className="w-5 h-5 text-brand-gold" />
                <h2 className="text-base font-bold text-foreground">
                  {t('discovery.preview_title')}
                </h2>
                <Badge
                  size="sm"
                  variant={
                    previewResult.status === 'completed'
                      ? 'success'
                      : previewResult.status === 'failed'
                      ? 'danger'
                      : 'warning'
                  }
                >
                  {previewResult.status === 'completed'
                    ? t('discovery.status_completed')
                    : previewResult.status === 'failed'
                    ? t('discovery.status_failed')
                    : t('discovery.status_partial')}
                </Badge>
                <Badge
                  size="sm"
                  variant="outline"
                  className="text-brand-gold border-brand-gold/30 bg-brand-gold/5 font-mono text-[10px]"
                >
                  {t('discovery.zero_writes_badge')}
                </Badge>
              </div>
              <p className="text-xs text-foreground-muted mt-1">
                {t('discovery.preview_subtitle')}
              </p>
            </div>

            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setPreviewResult(null);
                  setPreviewError(null);
                }}
                className="text-xs text-foreground-muted hover:text-foreground"
              >
                <X className="w-3.5 h-3.5 mr-1" />
                {t('discovery.clear_preview')}
              </Button>
            </div>
          </div>

          {/* Ephemeral Notice Banner */}
          <div className="p-3 bg-surface-subtle border border-border/80 rounded-md text-xs text-foreground-muted flex items-start gap-2">
            <Info className="w-4 h-4 text-brand-gold shrink-0 mt-0.5" />
            <span>{t('discovery.preview_disclaimer')}</span>
          </div>

          {/* Context Bar */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs bg-surface-subtle/50 p-2.5 rounded-md border border-border/60">
            <div>
              <span className="text-foreground-muted block text-[11px]">{t('discovery.selected_campaign_label')}:</span>
              <span className="font-semibold text-foreground truncate block">
                {campaigns.find((c) => c.id === previewResult.campaign_id)?.name || previewResult.campaign_id || '—'}
              </span>
            </div>
            <div>
              <span className="text-foreground-muted block text-[11px]">{t('discovery.provider_label')}:</span>
              <span className="font-mono text-foreground">{previewResult.provider}</span>
            </div>
            <div>
              <span className="text-foreground-muted block text-[11px]">{t('discovery.tasks_executed')}:</span>
              <span className="font-bold text-foreground">{previewResult.tasks_executed}</span>
            </div>
            <div>
              <span className="text-foreground-muted block text-[11px]">{t('discovery.candidates_found')}:</span>
              <span className="font-bold text-foreground">{previewResult.candidates_count}</span>
            </div>
          </div>

          {/* Errors Banner (Envelope failure or task errors) */}
          {previewResult.errors && previewResult.errors.length > 0 && (
            <div data-testid="preview-errors-alert" className="p-3 bg-rose-50 dark:bg-rose-950/20 border border-rose-200 dark:border-rose-900/40 rounded-md space-y-1 text-xs">
              <div className="flex items-center gap-1.5 text-rose-700 dark:text-rose-400 font-semibold">
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                <span>{t('discovery.preview_failed_title')} ({previewResult.errors.length})</span>
              </div>
              <ul className="text-rose-700/90 dark:text-rose-400/90 space-y-1 pl-5 list-disc text-[11px]">
                {previewResult.errors.map((err, idx) => (
                  <li key={idx}>{err}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Warnings Banner */}
          {previewResult.warnings && previewResult.warnings.length > 0 && (
            <div data-testid="preview-warnings-alert" className="p-3 bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-900/40 rounded-md space-y-1 text-xs text-amber-800 dark:text-amber-400">
              <div className="flex items-center gap-1.5 font-semibold">
                <AlertTriangle className="w-4 h-4 flex-shrink-0" />
                <span>{t('discovery.warnings_title')} ({previewResult.warnings.length})</span>
              </div>
              <ul className="space-y-0.5 pl-5 list-disc text-[11px]">
                {previewResult.warnings.map((w, idx) => (
                  <li key={idx}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Funnel Diagnostics Panel (P30.5G.5H.3C) */}
          {previewResult.status !== 'failed' && (
            <div
              data-testid="preview-diagnostics-panel"
              className="p-3 bg-surface-subtle/50 rounded-lg border border-border/70 space-y-2 text-xs"
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold text-foreground flex items-center gap-1.5">
                  <Activity className="w-3.5 h-3.5 text-brand-gold" />
                  {t('discovery.diagnostics.title')}
                </span>
                {!previewResult.diagnostics && (
                  <span className="text-[11px] text-foreground-muted font-mono italic">
                    {t('discovery.diagnostics.not_available')}
                  </span>
                )}
              </div>

              {previewResult.diagnostics ? (
                <div className="space-y-2.5">
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-[11px]">
                    <div className="p-2 rounded bg-surface border border-border/40">
                      <span className="text-foreground-muted block">{t('discovery.diagnostics.provider_results_received')}</span>
                      <span className="font-bold text-foreground text-sm font-mono">{previewResult.diagnostics.provider_results_received}</span>
                    </div>
                    <div className="p-2 rounded bg-surface border border-border/40">
                      <span className="text-foreground-muted block">{t('discovery.diagnostics.results_rejected')}</span>
                      <span className="font-bold text-amber-600 dark:text-amber-400 text-sm font-mono">{previewResult.diagnostics.results_rejected_by_classifier}</span>
                    </div>
                    <div className="p-2 rounded bg-surface border border-border/40">
                      <span className="text-foreground-muted block">{t('discovery.diagnostics.results_accepted')}</span>
                      <span className="font-bold text-emerald-600 dark:text-emerald-400 text-sm font-mono">{previewResult.diagnostics.results_accepted_by_classifier}</span>
                    </div>
                    <div className="p-2 rounded bg-surface border border-border/40">
                      <span className="text-foreground-muted block">{t('discovery.diagnostics.candidates_returned')}</span>
                      <span className="font-bold text-foreground text-sm font-mono">{previewResult.diagnostics.candidates_returned_to_preview}</span>
                    </div>
                  </div>

                  {previewResult.diagnostics.provider_results_received === 0 && (
                    <p className="text-[11px] text-foreground-muted italic text-center">
                      {t('discovery.diagnostics.zero_results_notice')}
                    </p>
                  )}

                  {previewResult.diagnostics.rejection_reasons && Object.keys(previewResult.diagnostics.rejection_reasons).length > 0 && (
                    <div className="pt-1.5 border-t border-border/40 space-y-1">
                      <span className="text-[11px] font-medium text-foreground-muted block">
                        {t('discovery.diagnostics.rejection_reasons_title')}:
                      </span>
                      <div className="flex flex-wrap gap-1.5">
                        {Object.entries(previewResult.diagnostics.rejection_reasons).map(([code, count]) => (
                          <span
                            key={code}
                            data-testid={`rejection-reason-${code}`}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-amber-500/10 text-amber-700 dark:text-amber-400 border border-amber-500/20 text-[10px]"
                          >
                            <span>{formatRejectionReason(t, code)}:</span>
                            <span className="font-mono font-bold">{count}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : null}
            </div>
          )}

          {/* Empty Candidates State (Only when not failed) */}
          {previewResult.status !== 'failed' && previewResult.candidates.length === 0 && (
            <div data-testid="preview-empty-state" className="py-8 text-center border border-dashed border-border rounded-lg bg-surface-subtle/30 space-y-2">
              <Search className="w-6 h-6 text-foreground-muted mx-auto opacity-50" />
              <p className="text-xs font-medium text-foreground">
                {t('discovery.preview_empty')}
              </p>
            </div>
          )}

          {/* Candidates Cards List */}
          {previewResult.candidates.length > 0 && (
            <div className="space-y-3 pt-1">
              <h3 className="text-xs font-bold text-foreground">
                {t('discovery.candidates_discovered', { count: previewResult.candidates.length })}
              </h3>
              <div className="space-y-3">
                {previewResult.candidates.map((candidate, idx) => {
                  const badge = getQualificationBadge(candidate.qualification_status);
                  const badgeText = badge.labelKey
                    ? (t(badge.labelKey) !== badge.labelKey ? t(badge.labelKey) : badge.fallback)
                    : badge.fallback;
                  const hasOfficialWebsite = Boolean(candidate.organization_website && candidate.organization_website !== 'UNKNOWN');

                  return (
                    <div
                      key={candidate.candidate_id || idx}
                      data-testid={`candidate-card-${candidate.candidate_id || idx}`}
                      className="p-4 rounded-lg border border-border bg-surface-subtle/40 hover:border-border/80 transition-all space-y-3"
                    >
                      {/* Card Top Row: Name, Archetype, Classification, Qualification Badge */}
                      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-2">
                        <div className="space-y-1">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-bold text-sm text-foreground">
                              {candidate.name}
                            </span>
                            {candidate.entity_archetype && (
                              <Badge size="sm" variant="outline" className="font-mono text-[10px] bg-surface">
                                {t('discovery.archetype_label')}: {formatEntityArchetype(t, candidate.entity_archetype)}
                              </Badge>
                            )}
                            {(candidate.category || candidate.classification_status) && (
                              <Badge size="sm" variant="default" className="text-[10px]">
                                {formatSectorOrClassification(t, candidate.category, candidate.classification_status)}
                              </Badge>
                            )}
                          </div>

                          {candidate.title && candidate.title !== candidate.name && (
                            <p className="text-xs text-foreground-muted italic line-clamp-1">
                              {candidate.title}
                            </p>
                          )}
                        </div>

                        <div className="shrink-0">
                          <Badge
                            size="sm"
                            variant={badge.variant}
                            className={badge.className}
                          >
                            {badgeText}
                          </Badge>
                        </div>
                      </div>

                      {/* Card Evidence & Provenance Details Grid */}
                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs pt-1 border-t border-border/50">
                        {/* Official Website vs Unknown */}
                        <div>
                          <span className="text-foreground-muted block text-[11px] mb-0.5">
                            {t('discovery.official_website_label')}:
                          </span>
                          {hasOfficialWebsite ? (
                            <a
                              href={candidate.organization_website!}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-brand-gold hover:underline inline-flex items-center gap-1 font-mono text-[11px]"
                            >
                              <Globe className="w-3 h-3 shrink-0" />
                              <span className="truncate">{candidate.organization_website}</span>
                              <ExternalLink className="w-2.5 h-2.5 shrink-0" />
                            </a>
                          ) : (
                            <span className="text-amber-600 dark:text-amber-400 text-[11px] italic flex items-center gap-1">
                              <AlertTriangle className="w-3 h-3 shrink-0" />
                              {t('discovery.official_website_unknown')}
                            </span>
                          )}
                        </div>

                        {/* Source Provenance Link */}
                        <div>
                          <span className="text-foreground-muted block text-[11px] mb-0.5">
                            {t('discovery.source_provenance_label')}:
                          </span>
                          {candidate.source_url ? (
                            <a
                              href={candidate.source_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-foreground hover:text-brand-gold inline-flex items-center gap-1 font-mono text-[11px] truncate max-w-full"
                            >
                              <ExternalLink className="w-3 h-3 shrink-0" />
                              <span className="truncate">{candidate.source_host || candidate.source_url}</span>
                            </a>
                          ) : (
                            <span className="text-foreground-muted text-[11px]">—</span>
                          )}
                        </div>

                        {/* Geographic Evidence */}
                        <div>
                          <span className="text-foreground-muted block text-[11px] mb-0.5">
                            {t('discovery.geo_evidence_label')}:
                          </span>
                          <span className="text-foreground text-[11px]">
                            {formatGeographicStatus(t, candidate.geographic_evidence_status)}
                            {[candidate.city, candidate.state, candidate.country].filter(Boolean).length > 0 && (
                              <span className="text-foreground-muted font-sans ml-1">
                                ({[candidate.city, candidate.state, candidate.country].filter(Boolean).join(', ')})
                              </span>
                            )}
                          </span>
                        </div>

                        {/* Current Activity Evidence */}
                        <div>
                          <span className="text-foreground-muted block text-[11px] mb-0.5">
                            {t('discovery.current_activity_label')}:
                          </span>
                          <span className="text-foreground text-[11px]">
                            {formatActivityStatus(t, candidate.current_activity_status)}
                          </span>
                        </div>
                      </div>

                      {/* Excerpt Snippet */}
                      {candidate.snippet && (
                        <p className="text-xs text-foreground-muted bg-surface/60 p-2 rounded border border-border/40 line-clamp-3">
                          &ldquo;{candidate.snippet}&rdquo;
                        </p>
                      )}

                      {/* Qualification Reasons & Missing Evidence */}
                      {((candidate.qualification_reasons && candidate.qualification_reasons.length > 0) ||
                        (candidate.missing_evidence && candidate.missing_evidence.length > 0)) && (
                        <div className="space-y-1.5 pt-1 border-t border-border/50 text-[11px]">
                          {candidate.qualification_reasons && candidate.qualification_reasons.length > 0 && (
                            <div className="flex flex-wrap items-center gap-1">
                              <span className="text-foreground-muted font-medium mr-1">
                                {t('discovery.qualification_reasons_label')}:
                              </span>
                              {candidate.qualification_reasons.map((r, rIdx) => (
                                <span
                                  key={rIdx}
                                  className="inline-flex items-center px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 font-mono text-[10px]"
                                >
                                  {r}
                                </span>
                              ))}
                            </div>
                          )}

                          {candidate.missing_evidence && candidate.missing_evidence.length > 0 && (
                            <div className="flex flex-wrap items-center gap-1">
                              <span className="text-amber-600 dark:text-amber-400 font-medium mr-1">
                                {t('discovery.missing_evidence_label')}:
                              </span>
                              {candidate.missing_evidence.map((m, mIdx) => (
                                <span
                                  key={mIdx}
                                  className="inline-flex items-center px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-700 dark:text-amber-400 font-mono text-[10px] border border-amber-500/20"
                                >
                                  {m}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

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

          <div className="flex items-center justify-end gap-2 pt-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              data-testid="plan-search-preview-button"
              disabled={previewing || !selectedCampaignId}
              onClick={() => handlePreview(true)}
            >
              {previewing ? (
                <>
                  <div className="animate-spin h-3.5 w-3.5 border-2 border-surface border-t-transparent rounded-full mr-2" />
                  {t('discovery.previewing')}
                </>
              ) : (
                <>
                  <Search className="w-3.5 h-3.5 mr-1.5 text-brand-gold" />
                  {t('discovery.preview_button')}
                </>
              )}
            </Button>
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
                {executionResult.status === 'failed' ? (
                  <AlertCircle className="w-4 h-4 text-danger" />
                ) : (
                  <CheckCircle2 className="w-4 h-4 text-success" />
                )}
                {t('discovery.results_title')}
              </h2>
              <p className="text-xs text-foreground-muted mt-0.5">
                {executionResult.status === 'failed'
                  ? 'Discovery execution encountered errors and no prospects were imported'
                  : 'Campaign pipeline updated with deduplicated discovery records'}
              </p>
            </div>
            <Badge
              size="sm"
              variant={
                executionResult.status === 'completed'
                  ? 'success'
                  : executionResult.status === 'failed'
                  ? 'danger'
                  : 'warning'
              }
            >
              {executionResult.status === 'completed'
                ? t('discovery.status_completed')
                : executionResult.status === 'failed'
                ? t('discovery.status_failed')
                : t('discovery.status_partial')}
            </Badge>
          </div>

          {/* Execution Errors if any */}
          {executionResult.errors && executionResult.errors.length > 0 && (
            <div className="p-3 bg-rose-50 border border-rose-200/80 rounded-md space-y-1 text-xs">
              <div className="flex items-center gap-1.5 text-rose-700 font-semibold">
                <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                <span>{t('discovery.errors_title')} ({executionResult.errors.length})</span>
              </div>
              <ul className="text-rose-700/90 space-y-1 pl-5 list-disc">
                {executionResult.errors.map((err, idx) => (
                  <li key={idx}>{err}</li>
                ))}
              </ul>
            </div>
          )}

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
