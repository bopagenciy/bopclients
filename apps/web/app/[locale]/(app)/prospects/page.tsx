'use client';

import React, { useEffect, useState, useCallback, useTransition, Suspense } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams, usePathname } from 'next/navigation';
import { useI18n } from '@/lib/i18n/context';
import { useAuth } from '@/lib/auth/context';
import { DataTable, Column } from '@/components/ui/DataTable';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { EmptyState } from '@/components/states/EmptyState';
import { ErrorState } from '@/components/states/ErrorState';
import {
  Users,
  Search,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Building,
  Sparkles,
  ArrowUpDown,
  Download,
  FolderPlus,
  RefreshCw,
  Flame,
  CheckSquare,
  Square,
  MinusSquare,
  X,
  Target,
  AlertCircle,
  CheckCircle2,
} from 'lucide-react';
import {
  Prospect,
  Campaign,
  bulkAddToCampaign,
  bulkRecalculateScore,
  bulkRecalculatePriority,
  bulkResearch,
  exportProspectsCsv,
  exportSelectedProspectsCsv,
} from '@/lib/api';

interface SignalItem {
  id: string;
  prospect_id: string;
  category: string;
  display_key: string;
  signal_type: string;
  confidence: number;
  headline: string;
  summary?: string | null;
  source_url?: string | null;
  detected_at: string;
  created_at: string;
}

function ProspectsWorkspaceContent() {
  const { t, locale } = useI18n();
  const { activeOrg, hasRole } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  const isOperator = hasRole(['OWNER', 'ADMIN', 'MEMBER']);

  // Read URL params or defaults
  const initialSearch = searchParams.get('search') || searchParams.get('q') || '';
  const initialCampaignId = searchParams.get('campaign_id') || '';
  const initialPriority = searchParams.get('priority') || '';
  const initialScoreMin = searchParams.get('score_min') || '';
  const initialScoreMax = searchParams.get('score_max') || '';
  const initialUnscored = searchParams.get('unscored') === 'true';
  const initialHasSignals = searchParams.get('has_signals') === 'true';
  const initialSortBy = searchParams.get('sort_by') || 'created_at';
  const initialSortDir = (searchParams.get('sort_dir') || 'desc') as 'asc' | 'desc';
  const initialPage = parseInt(searchParams.get('page') || '1', 10) || 1;

  // State
  const [prospects, setProspects] = useState<Prospect[]>([]);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filter state
  const [searchQuery, setSearchQuery] = useState(initialSearch);
  const [campaignId, setCampaignId] = useState(initialCampaignId);
  const [priorityFilter, setPriorityFilter] = useState(initialPriority);
  const [scoreRange, setScoreRange] = useState<'all' | 'high' | 'med' | 'low' | 'unscored'>(
    initialUnscored
      ? 'unscored'
      : initialScoreMin === '70'
      ? 'high'
      : initialScoreMin === '40'
      ? 'med'
      : initialScoreMax === '39'
      ? 'low'
      : 'all'
  );
  const [hasSignals, setHasSignals] = useState(initialHasSignals);
  const [sortBy, setSortBy] = useState(initialSortBy);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>(initialSortDir);
  const [page, setPage] = useState(initialPage);
  const pageSize = 15;
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);

  // Multi-selection state (tracked by ID)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  // Bulk actions status & modal
  const [bulkActionLoading, setBulkActionLoading] = useState(false);
  const [actionFeedback, setActionFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null);
  const [isCampaignModalOpen, setIsCampaignModalOpen] = useState(false);
  const [targetCampaignId, setTargetCampaignId] = useState('');

  // Quick detail preview modal
  const [selectedProspect, setSelectedProspect] = useState<Prospect | null>(null);
  const [prospectSignals, setProspectSignals] = useState<SignalItem[]>([]);
  const [loadingSignals, setLoadingSignals] = useState(false);
  const [isDetailModalOpen, setIsDetailModalOpen] = useState(false);

  // Load campaigns for dropdowns
  useEffect(() => {
    async function loadCampaigns() {
      try {
        const res = await fetch('/api/proxy/api/v1/campaigns?page_size=100', {
          credentials: 'include',
        });
        if (res.ok) {
          const data = await res.json();
          setCampaigns(data.items || []);
        }
      } catch {
        // Dropdowns will remain empty
      }
    }
    loadCampaigns();
  }, [activeOrg]);

  // Sync state to URL search parameters
  const updateUrlParams = useCallback(
    (newParams: Record<string, string | number | boolean | undefined | null>) => {
      const current = new URLSearchParams(searchParams.toString());
      for (const [k, v] of Object.entries(newParams)) {
        if (v === undefined || v === null || v === '' || v === false) {
          current.delete(k);
        } else {
          current.set(k, String(v));
        }
      }
      startTransition(() => {
        router.replace(`${pathname}?${current.toString()}`, { scroll: false });
      });
    },
    [pathname, router, searchParams]
  );

  // Fetch prospects
  const loadProspects = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
        sort_by: sortBy,
        sort_dir: sortDir,
      });

      if (searchQuery.trim()) params.set('search', searchQuery.trim());
      if (campaignId) params.set('campaign_id', campaignId);
      if (priorityFilter) params.set('priority', priorityFilter);
      if (hasSignals) params.set('has_signals', 'true');

      if (scoreRange === 'unscored') {
        params.set('unscored', 'true');
      } else if (scoreRange === 'high') {
        params.set('score_min', '70');
        params.set('score_max', '100');
      } else if (scoreRange === 'med') {
        params.set('score_min', '40');
        params.set('score_max', '69');
      } else if (scoreRange === 'low') {
        params.set('score_min', '0');
        params.set('score_max', '39');
      }

      const res = await fetch(`/api/proxy/api/v1/prospects?${params.toString()}`, {
        credentials: 'include',
      });

      if (!res.ok) {
        throw new Error(`Failed to load prospects (Status: ${res.status})`);
      }

      const data = await res.json();
      setProspects(data.items || []);
      const totalItems = data.total_items ?? 0;
      setTotal(totalItems);
      setTotalPages(data.total_pages ?? (totalItems > 0 ? Math.ceil(totalItems / pageSize) : 1));
    } catch (err: any) {
      setError(err.message || 'Error fetching prospects');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, sortBy, sortDir, searchQuery, campaignId, priorityFilter, hasSignals, scoreRange]);

  useEffect(() => {
    loadProspects();
  }, [loadProspects, activeOrg]);

  // Handle Sort Toggle
  const handleSort = (field: string) => {
    let nextDir: 'asc' | 'desc' = 'desc';
    if (sortBy === field) {
      nextDir = sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      nextDir = field === 'name' ? 'asc' : 'desc';
    }
    setSortBy(field);
    setSortDir(nextDir);
    setPage(1);
    updateUrlParams({ sort_by: field, sort_dir: nextDir, page: 1 });
  };

  // Selection handlers
  const allCurrentPageSelected =
    prospects.length > 0 && prospects.every((p) => selectedIds.has(p.id));
  const someCurrentPageSelected =
    prospects.some((p) => selectedIds.has(p.id)) && !allCurrentPageSelected;

  const toggleSelectAll = () => {
    const next = new Set(selectedIds);
    if (allCurrentPageSelected) {
      prospects.forEach((p) => next.delete(p.id));
    } else {
      prospects.forEach((p) => next.add(p.id));
    }
    setSelectedIds(next);
  };

  const toggleSelectRow = (id: string) => {
    const next = new Set(selectedIds);
    if (next.has(id)) {
      next.delete(id);
    } else {
      next.add(id);
    }
    setSelectedIds(next);
  };

  const clearSelection = () => {
    setSelectedIds(new Set());
  };

  // Bulk: Add to Campaign
  const handleBulkAddToCampaign = async () => {
    if (!targetCampaignId) return;
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (ids.length > 100) {
      setActionFeedback({
        type: 'error',
        message: t('prospects.bulk.max_limit_exceeded'),
      });
      return;
    }

    setBulkActionLoading(true);
    setActionFeedback(null);
    try {
      const res = await bulkAddToCampaign({
        campaign_id: targetCampaignId,
        prospect_ids: ids,
      });
      setIsCampaignModalOpen(false);
      setTargetCampaignId('');
      clearSelection();
      setActionFeedback({
        type: 'success',
        message: t('prospects.bulk.success_added', {
          count: res.added_count,
          skipped: res.already_present_count,
        }),
      });
      loadProspects();
    } catch (err: any) {
      setActionFeedback({
        type: 'error',
        message: err.message || 'Failed to add prospects to campaign',
      });
    } finally {
      setBulkActionLoading(false);
    }
  };

  // Bulk: Recalculate Score
  const handleBulkRecalculateScore = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (ids.length > 50) {
      setActionFeedback({
        type: 'error',
        message: t('prospects.bulk.max_limit_exceeded'),
      });
      return;
    }

    setBulkActionLoading(true);
    setActionFeedback(null);
    try {
      const res = await bulkRecalculateScore({ prospect_ids: ids });
      setActionFeedback({
        type: 'success',
        message: t('prospects.bulk.success_scored', {
          count: res.processed_count,
          scored: res.scored_count,
          failed: res.failed_count,
        }),
      });
      loadProspects();
    } catch (err: any) {
      setActionFeedback({
        type: 'error',
        message: err.message || 'Failed to recalculate scores',
      });
    } finally {
      setBulkActionLoading(false);
    }
  };

  // Bulk: Recalculate Priority
  const handleBulkRecalculatePriority = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (ids.length > 50) {
      setActionFeedback({
        type: 'error',
        message: t('prospects.bulk.max_limit_exceeded'),
      });
      return;
    }

    setBulkActionLoading(true);
    setActionFeedback(null);
    try {
      const res = await bulkRecalculatePriority({
        prospect_ids: ids,
        campaign_id: campaignId || undefined,
      });
      setActionFeedback({
        type: 'success',
        message: t('prospects.bulk.success_prioritized', {
          count: res.processed_count,
          prioritized: res.prioritized_count,
          failed: res.failed_count,
        }),
      });
      loadProspects();
    } catch (err: any) {
      setActionFeedback({
        type: 'error',
        message: err.message || 'Failed to recalculate priorities',
      });
    } finally {
      setBulkActionLoading(false);
    }
  };

  // Bulk: Trigger Research
  const handleBulkResearch = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;
    if (ids.length > 25) {
      setActionFeedback({
        type: 'error',
        message: t('prospects.bulk.max_limit_exceeded'),
      });
      return;
    }

    setBulkActionLoading(true);
    setActionFeedback(null);
    try {
      const res = await bulkResearch({
        prospect_ids: ids,
        campaign_id: campaignId || undefined,
        run_type: 'bulk_enrichment',
      });
      setActionFeedback({
        type: 'success',
        message: t('prospects.bulk.success_research', {
          count: res.triggered_count,
          skipped: res.skipped_count,
        }),
      });
    } catch (err: any) {
      setActionFeedback({
        type: 'error',
        message: err.message || 'Failed to trigger research runs',
      });
    } finally {
      setBulkActionLoading(false);
    }
  };

  // CSV Export: Selected or Filtered All
  const handleExportSelectedCsv = async () => {
    const ids = Array.from(selectedIds);
    if (ids.length === 0) return;

    setBulkActionLoading(true);
    try {
      const blob = await exportSelectedProspectsCsv({ prospect_ids: ids });
      const downloadUrl = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = downloadUrl;
      a.download = `prospects_selected_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(downloadUrl);
    } catch (err: any) {
      setActionFeedback({
        type: 'error',
        message: err.message || 'CSV export failed',
      });
    } finally {
      setBulkActionLoading(false);
    }
  };

  const handleExportFilteredCsv = async () => {
    setBulkActionLoading(true);
    try {
      const filters: Record<string, any> = {};
      if (searchQuery.trim()) filters.search = searchQuery.trim();
      if (campaignId) filters.campaign_id = campaignId;
      if (priorityFilter) filters.priority = priorityFilter;
      if (hasSignals) filters.has_signals = true;
      if (scoreRange === 'unscored') filters.unscored = true;
      else if (scoreRange === 'high') {
        filters.score_min = 70;
        filters.score_max = 100;
      } else if (scoreRange === 'med') {
        filters.score_min = 40;
        filters.score_max = 69;
      } else if (scoreRange === 'low') {
        filters.score_min = 0;
        filters.score_max = 39;
      }

      const blob = await exportProspectsCsv(filters);
      const downloadUrl = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = downloadUrl;
      a.download = `prospects_filtered_${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(downloadUrl);
    } catch (err: any) {
      setActionFeedback({
        type: 'error',
        message: err.message || 'CSV export failed',
      });
    } finally {
      setBulkActionLoading(false);
    }
  };

  // Quick Signal Modal
  const handleSelectProspectQuickModal = async (p: Prospect) => {
    setSelectedProspect(p);
    setIsDetailModalOpen(true);
    setLoadingSignals(true);
    try {
      const res = await fetch(`/api/proxy/api/v1/prospects/${p.id}/signals`, {
        credentials: 'include',
      });
      if (res.ok) {
        const data = await res.json();
        setProspectSignals(Array.isArray(data) ? data : data.items || []);
      } else {
        setProspectSignals([]);
      }
    } catch {
      setProspectSignals([]);
    } finally {
      setLoadingSignals(false);
    }
  };

  // Reset Filters
  const handleResetFilters = () => {
    setSearchQuery('');
    setCampaignId('');
    setPriorityFilter('');
    setScoreRange('all');
    setHasSignals(false);
    setSortBy('created_at');
    setSortDir('desc');
    setPage(1);
    startTransition(() => {
      router.replace(pathname, { scroll: false });
    });
  };

  // Priority Badge Color Helper
  const renderPriorityBadge = (tier?: string | null) => {
    if (!tier) return <span className="text-xs text-foreground-muted">—</span>;
    const tLower = tier.toLowerCase();
    const variant =
      tLower === 'urgent'
        ? 'danger'
        : tLower === 'high'
        ? 'warning'
        : tLower === 'medium'
        ? 'info'
        : 'default';
    return (
      <Badge size="sm" variant={variant}>
        {tier.toUpperCase()}
      </Badge>
    );
  };

  // Score Badge Color Helper
  const renderScoreBadge = (score?: number | null) => {
    if (score === null || score === undefined) {
      return <span className="text-xs text-foreground-muted">—</span>;
    }
    const colorClass =
      score >= 70
        ? 'text-emerald-500 font-bold'
        : score >= 40
        ? 'text-amber-500 font-semibold'
        : 'text-foreground-muted font-medium';
    return (
      <div className="flex items-center gap-1">
        <Flame
          className={`w-3.5 h-3.5 ${
            score >= 70 ? 'text-emerald-500 fill-emerald-500' : 'text-foreground-muted'
          }`}
        />
        <span className={`text-xs font-mono ${colorClass}`}>{score}</span>
      </div>
    );
  };

  // Table Columns
  const columns: Column<Prospect>[] = [
    {
      header: (
        <div className="flex items-center justify-center cursor-pointer" onClick={toggleSelectAll}>
          {allCurrentPageSelected ? (
            <CheckSquare className="w-4 h-4 text-brand-gold" />
          ) : someCurrentPageSelected ? (
            <MinusSquare className="w-4 h-4 text-brand-gold" />
          ) : (
            <Square className="w-4 h-4 text-foreground-muted hover:text-foreground" />
          )}
        </div>
      ),
      className: 'w-10 text-center',
      cell: (row) => (
        <div
          className="flex items-center justify-center cursor-pointer"
          onClick={(e) => {
            e.stopPropagation();
            toggleSelectRow(row.id);
          }}
        >
          {selectedIds.has(row.id) ? (
            <CheckSquare className="w-4 h-4 text-brand-gold" />
          ) : (
            <Square className="w-4 h-4 text-foreground-muted hover:text-foreground" />
          )}
        </div>
      ),
    },
    {
      header: (
        <button
          type="button"
          onClick={() => handleSort('name')}
          className="flex items-center gap-1 font-semibold uppercase hover:text-brand-gold transition-colors"
        >
          {t('prospects.columns.company')}
          <ArrowUpDown className="w-3 h-3 opacity-60" />
        </button>
      ),
      accessorKey: 'name',
      cell: (row) => {
        const returnTo = `${pathname}?${searchParams.toString()}`;
        return (
          <div className="font-medium text-foreground flex items-center gap-2">
            <Building className="w-4 h-4 text-brand-gold shrink-0" />
            <Link
              href={`/${locale}/prospects/${row.id}?return_to=${encodeURIComponent(returnTo)}`}
              className="truncate hover:text-brand-gold hover:underline transition-colors font-medium"
            >
              {row.name}
            </Link>
          </div>
        );
      },
    },
    {
      header: (
        <button
          type="button"
          onClick={() => handleSort('priority')}
          className="flex items-center gap-1 font-semibold uppercase hover:text-brand-gold transition-colors"
        >
          {t('prospects.columns.priority')}
          <ArrowUpDown className="w-3 h-3 opacity-60" />
        </button>
      ),
      cell: (row) => renderPriorityBadge(row.priority_tier),
    },
    {
      header: (
        <button
          type="button"
          onClick={() => handleSort('lead_score')}
          className="flex items-center gap-1 font-semibold uppercase hover:text-brand-gold transition-colors"
        >
          {t('prospects.columns.lead_score')}
          <ArrowUpDown className="w-3 h-3 opacity-60" />
        </button>
      ),
      cell: (row) => renderScoreBadge(row.lead_score),
    },
    {
      header: t('prospects.columns.campaigns'),
      cell: (row) => {
        const count = row.campaign_count ?? 0;
        if (count === 0) return <span className="text-xs text-foreground-muted font-mono">0</span>;
        const names = row.campaign_names || [];
        return (
          <div className="flex items-center gap-1.5" title={names.join(', ')}>
            <Badge size="sm" variant="default" className="text-[10px] font-mono">
              {count}
            </Badge>
            {names.length > 0 && (
              <span className="text-xs text-foreground-muted truncate max-w-[120px]">
                {names[0]}
                {names.length > 1 && ` (+${names.length - 1})`}
              </span>
            )}
          </div>
        );
      },
    },
    {
      header: t('prospects.columns.signals'),
      cell: (row) => {
        const count = row.signals_count ?? 0;
        if (count === 0) return <span className="text-xs text-foreground-muted font-mono">0</span>;
        return (
          <Badge size="sm" variant="info" className="text-[10px] font-mono gap-1">
            <Sparkles className="w-2.5 h-2.5 text-brand-gold" />
            {count}
          </Badge>
        );
      },
    },
    {
      header: t('prospects.columns.industry'),
      accessorKey: 'industry',
      cell: (row) => (
        <span className="text-xs text-foreground-muted truncate max-w-[120px] block">
          {row.industry || '—'}
        </span>
      ),
    },
    {
      header: t('prospects.columns.location'),
      cell: (row) => {
        const parts = [row.city, row.state, row.country].filter(Boolean);
        return (
          <span className="text-xs text-foreground-muted truncate max-w-[140px] block">
            {parts.length > 0 ? parts.join(', ') : '—'}
          </span>
        );
      },
    },
    {
      header: t('prospects.columns.actions'),
      className: 'text-right',
      cell: (row) => (
        <Button
          size="sm"
          variant="ghost"
          onClick={(e) => {
            e.stopPropagation();
            handleSelectProspectQuickModal(row);
          }}
        >
          {t('common.view')}
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      {/* Page Title & Operational Metric */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            {t('prospects.title')}
          </h1>
          <p className="text-xs text-foreground-muted">
            {t('prospects.subtitle')}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            size="sm"
            variant="outline"
            onClick={handleExportFilteredCsv}
            disabled={loading || bulkActionLoading || total === 0}
            title={t('prospects.bulk.export_all')}
          >
            <Download className="w-4 h-4 mr-1.5 text-brand-gold" />
            {t('prospects.bulk.export_all')}
          </Button>
          <div className="text-xs font-medium text-foreground-muted border-l border-border pl-3">
            Total: <span className="font-bold text-foreground">{total}</span>
          </div>
        </div>
      </div>

      {/* Action Notification Alert */}
      {actionFeedback && (
        <div
          className={`p-3 rounded-lg border flex items-center justify-between text-xs ${
            actionFeedback.type === 'success'
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
              : 'bg-red-500/10 border-red-500/30 text-red-400'
          }`}
        >
          <div className="flex items-center gap-2">
            {actionFeedback.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 shrink-0" />
            )}
            <span>{actionFeedback.message}</span>
          </div>
          <button
            type="button"
            onClick={() => setActionFeedback(null)}
            className="hover:opacity-75 transition-opacity"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Filter & Search Toolbar */}
      <div className="p-3.5 rounded-lg bg-surface border border-border space-y-3">
        {/* Row 1: Search & Core Selects */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <div className="relative md:col-span-2">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-foreground-muted" />
            <input
              type="text"
              className="w-full h-9 pl-9 pr-3 rounded-md border border-border bg-surface-subtle/50 text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-1 focus:ring-brand-gold"
              placeholder={t('prospects.search_placeholder')}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  setPage(1);
                  updateUrlParams({ search: searchQuery, page: 1 });
                }
              }}
            />
          </div>

          <div>
            <select
              value={campaignId}
              onChange={(e) => {
                const val = e.target.value;
                setCampaignId(val);
                setPage(1);
                updateUrlParams({ campaign_id: val, page: 1 });
              }}
              aria-label={t('prospects.filter_campaign')}
              className="w-full h-9 px-3 rounded-md border border-border bg-surface-subtle/50 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-brand-gold"
            >
              <option value="">{t('prospects.filter_all_campaigns')}</option>
              {campaigns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          <div>
            <select
              value={priorityFilter}
              onChange={(e) => {
                const val = e.target.value;
                setPriorityFilter(val);
                setPage(1);
                updateUrlParams({ priority: val, page: 1 });
              }}
              aria-label={t('prospects.filter_priority')}
              className="w-full h-9 px-3 rounded-md border border-border bg-surface-subtle/50 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-brand-gold"
            >
              <option value="">{t('prospects.filter_all_priorities')}</option>
              <option value="urgent">{t('prospects.priorities.urgent')}</option>
              <option value="high">{t('prospects.priorities.high')}</option>
              <option value="medium">{t('prospects.priorities.medium')}</option>
              <option value="low">{t('prospects.priorities.low')}</option>
            </select>
          </div>
        </div>

        {/* Row 2: Secondary Quick Filters */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-border/60">
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={scoreRange}
              onChange={(e) => {
                const val = e.target.value as any;
                setScoreRange(val);
                setPage(1);
                const p: any = { page: 1 };
                if (val === 'unscored') {
                  p.unscored = true;
                  p.score_min = undefined;
                  p.score_max = undefined;
                } else if (val === 'high') {
                  p.score_min = 70;
                  p.score_max = 100;
                  p.unscored = undefined;
                } else if (val === 'med') {
                  p.score_min = 40;
                  p.score_max = 69;
                  p.unscored = undefined;
                } else if (val === 'low') {
                  p.score_min = 0;
                  p.score_max = 39;
                  p.unscored = undefined;
                } else {
                  p.score_min = undefined;
                  p.score_max = undefined;
                  p.unscored = undefined;
                }
                updateUrlParams(p);
              }}
              aria-label={t('prospects.filter_score_range')}
              className="h-8 px-2.5 rounded-md border border-border bg-surface-subtle/50 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-brand-gold"
            >
              <option value="all">{t('prospects.filter_all_scores')}</option>
              <option value="high">{t('prospects.filter_score_high')}</option>
              <option value="med">{t('prospects.filter_score_med')}</option>
              <option value="low">{t('prospects.filter_score_low')}</option>
              <option value="unscored">{t('prospects.filter_unscored')}</option>
            </select>

            <Button
              size="sm"
              variant={hasSignals ? 'secondary' : 'outline'}
              className={`h-8 text-xs ${hasSignals ? 'border-brand-gold/60 text-brand-gold' : ''}`}
              onClick={() => {
                const next = !hasSignals;
                setHasSignals(next);
                setPage(1);
                updateUrlParams({ has_signals: next ? true : undefined, page: 1 });
              }}
            >
              <Sparkles className="w-3 h-3 mr-1.5 text-brand-gold" />
              {t('prospects.filter_with_signals')}
            </Button>

            <Button
              size="sm"
              variant="ghost"
              className="h-8 text-xs text-foreground-muted hover:text-foreground"
              onClick={handleResetFilters}
            >
              {t('prospects.filter_reset')}
            </Button>
          </div>

          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              className="h-8 text-xs"
              onClick={() => {
                setPage(1);
                updateUrlParams({ search: searchQuery, page: 1 });
                loadProspects();
              }}
            >
              <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
              {t('common.refresh')}
            </Button>
          </div>
        </div>
      </div>

      {/* Floating Bulk Actions Toolbar */}
      {selectedIds.size > 0 && (
        <div className="p-3 rounded-lg bg-surface border-2 border-brand-gold/50 shadow-lg flex flex-wrap items-center justify-between gap-3 animate-in fade-in slide-in-from-top-2">
          <div className="flex items-center gap-3">
            <span className="text-xs font-semibold text-foreground px-2 py-1 rounded bg-brand-gold/10 text-brand-gold">
              {t('prospects.bulk.selected_count', { count: selectedIds.size })}
            </span>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 text-xs text-foreground-muted hover:text-foreground"
              onClick={clearSelection}
            >
              {t('prospects.bulk.clear_selection')}
            </Button>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {isOperator && (
              <>
                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 text-xs"
                  onClick={() => setIsCampaignModalOpen(true)}
                  disabled={bulkActionLoading}
                >
                  <FolderPlus className="w-3.5 h-3.5 mr-1 text-brand-gold" />
                  {t('prospects.bulk.add_to_campaign')}
                </Button>

                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 text-xs"
                  onClick={handleBulkRecalculateScore}
                  disabled={bulkActionLoading || selectedIds.size > 50}
                  title={selectedIds.size > 50 ? 'Max 50 items' : undefined}
                >
                  <Flame className="w-3.5 h-3.5 mr-1 text-brand-gold" />
                  {t('prospects.bulk.recalculate_score')}
                </Button>

                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 text-xs"
                  onClick={handleBulkRecalculatePriority}
                  disabled={bulkActionLoading || selectedIds.size > 50}
                  title={selectedIds.size > 50 ? 'Max 50 items' : undefined}
                >
                  <Target className="w-3.5 h-3.5 mr-1 text-brand-gold" />
                  {t('prospects.bulk.recalculate_priority')}
                </Button>

                <Button
                  size="sm"
                  variant="outline"
                  className="h-8 text-xs"
                  onClick={handleBulkResearch}
                  disabled={bulkActionLoading || selectedIds.size > 25}
                  title={selectedIds.size > 25 ? 'Max 25 items' : undefined}
                >
                  <Sparkles className="w-3.5 h-3.5 mr-1 text-brand-gold" />
                  {t('prospects.bulk.run_research')}
                </Button>
              </>
            )}

            <Button
              size="sm"
              variant="secondary"
              className="h-8 text-xs"
              onClick={handleExportSelectedCsv}
              disabled={bulkActionLoading}
            >
              <Download className="w-3.5 h-3.5 mr-1 text-brand-gold" />
              {t('prospects.bulk.export_selected')}
            </Button>
          </div>
        </div>
      )}

      {/* Main Table or State */}
      {error ? (
        <ErrorState message={error} onRetry={loadProspects} />
      ) : prospects.length === 0 && !loading ? (
        <EmptyState
          title={t('prospects.empty')}
          description="Try modifying your filters or running a discovery plan."
          icon={<Users className="w-6 h-6 text-brand-gold" />}
        />
      ) : (
        <div className="space-y-4">
          <DataTable
            columns={columns}
            data={prospects}
            isLoading={loading}
            emptyMessage={t('prospects.empty')}
            onRowClick={(row) => handleSelectProspectQuickModal(row)}
          />

          {/* Pagination Controls */}
          <div className="flex items-center justify-between px-2 text-xs text-foreground-muted">
            <div>
              {t('prospects.pagination.showing', {
                start: total === 0 ? 0 : (page - 1) * pageSize + 1,
                end: Math.min(page * pageSize, total),
                total: total,
              })}
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={page <= 1 || loading}
                onClick={() => {
                  const next = Math.max(page - 1, 1);
                  setPage(next);
                  updateUrlParams({ page: next });
                }}
              >
                <ChevronLeft className="w-3.5 h-3.5 mr-1" />
                {t('prospects.pagination.previous')}
              </Button>
              <span className="px-2 font-medium">
                {t('prospects.pagination.page', { page, pages: totalPages })}
              </span>
              <Button
                size="sm"
                variant="outline"
                disabled={page >= totalPages || loading}
                onClick={() => {
                  const next = Math.min(page + 1, totalPages);
                  setPage(next);
                  updateUrlParams({ page: next });
                }}
              >
                {t('prospects.pagination.next')}
                <ChevronRight className="w-3.5 h-3.5 ml-1" />
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Bulk Add to Campaign */}
      <Modal
        isOpen={isCampaignModalOpen}
        onClose={() => setIsCampaignModalOpen(false)}
        title={t('prospects.bulk.modal_campaign_title')}
        description={`${selectedIds.size} prospects selected`}
      >
        <div className="space-y-4 pt-2">
          <div>
            <label className="block text-xs font-semibold text-foreground mb-1.5">
              {t('prospects.bulk.modal_campaign_select')}
            </label>
            <select
              value={targetCampaignId}
              onChange={(e) => setTargetCampaignId(e.target.value)}
              className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-brand-gold"
            >
              <option value="">{t('prospects.bulk.modal_campaign_choose')}</option>
              {campaigns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-border">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setIsCampaignModalOpen(false)}
              disabled={bulkActionLoading}
            >
              {t('common.cancel')}
            </Button>
            <Button
              size="sm"
              onClick={handleBulkAddToCampaign}
              disabled={!targetCampaignId || bulkActionLoading}
            >
              {bulkActionLoading ? 'Adding...' : t('prospects.bulk.modal_campaign_submit')}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Modal: Quick Prospect Detail & Real Enrichment Signals */}
      {selectedProspect && (
        <Modal
          isOpen={isDetailModalOpen}
          onClose={() => setIsDetailModalOpen(false)}
          title={selectedProspect.name}
          description={`ID: ${selectedProspect.id}`}
        >
          <div className="space-y-4 text-xs">
            <div className="grid grid-cols-2 gap-3 p-3 rounded-lg bg-surface-subtle/50 border border-border">
              <div>
                <p className="text-foreground-muted font-medium">Industry</p>
                <p className="font-semibold text-foreground">{selectedProspect.industry || '—'}</p>
              </div>
              <div>
                <p className="text-foreground-muted font-medium">Location</p>
                <p className="font-semibold text-foreground">
                  {[selectedProspect.city, selectedProspect.state, selectedProspect.country]
                    .filter(Boolean)
                    .join(', ') || '—'}
                </p>
              </div>
              <div>
                <p className="text-foreground-muted font-medium">Lead Score</p>
                <div className="pt-0.5">{renderScoreBadge(selectedProspect.lead_score)}</div>
              </div>
              <div>
                <p className="text-foreground-muted font-medium">Priority Tier</p>
                <div className="pt-0.5">{renderPriorityBadge(selectedProspect.priority_tier)}</div>
              </div>
            </div>

            {selectedProspect.website_url && (
              <div className="flex items-center gap-2 text-foreground-muted">
                <ExternalLink className="w-3.5 h-3.5 text-brand-gold" />
                <a
                  href={selectedProspect.website_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-brand-gold hover:underline font-mono"
                >
                  {selectedProspect.website_url}
                </a>
              </div>
            )}

            {/* Link to Full Dossier with Return URL */}
            <div className="pt-1 flex justify-end">
              <Link
                href={`/${locale}/prospects/${selectedProspect.id}?return_to=${encodeURIComponent(
                  `${pathname}?${searchParams.toString()}`
                )}`}
                className="text-xs text-brand-gold hover:underline font-medium flex items-center gap-1"
              >
                <span>View Full Dossier</span>
                <ExternalLink className="w-3 h-3" />
              </Link>
            </div>

            {/* Real Enrichment Signals */}
            <div className="space-y-2 pt-2 border-t border-border">
              <div className="flex items-center justify-between">
                <span className="font-semibold text-foreground flex items-center gap-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-brand-gold" />
                  {t('prospects.detail.signals')}
                </span>
                <span className="text-[11px] text-foreground-muted font-mono">
                  {prospectSignals.length} detected
                </span>
              </div>

              {loadingSignals ? (
                <p className="text-[11px] text-foreground-muted py-2">Loading signals...</p>
              ) : prospectSignals.length === 0 ? (
                <p className="text-[11px] text-foreground-muted py-2">
                  {t('prospects.detail.no_signals')}
                </p>
              ) : (
                <div className="space-y-1.5 max-h-40 overflow-y-auto">
                  {prospectSignals.map((sig) => (
                    <div
                      key={sig.id}
                      className="p-2 rounded border border-border/70 bg-surface-subtle/30 flex items-center justify-between"
                    >
                      <div className="space-y-0.5 max-w-[75%]">
                        <div className="flex items-center gap-1.5">
                          <Badge size="sm" variant="default" className="text-[9px] py-0 px-1">
                            {sig.category}
                          </Badge>
                          <span className="font-semibold text-xs text-foreground truncate">
                            {sig.headline || sig.signal_type}
                          </span>
                        </div>
                        {sig.summary && (
                          <p className="text-[11px] text-foreground-muted line-clamp-1">
                            {sig.summary}
                          </p>
                        )}
                        <p className="text-[10px] text-foreground-muted font-mono">
                          {sig.signal_type}
                        </p>
                      </div>
                      <Badge size="sm" variant="outline">
                        {sig.confidence ? `${Math.round(sig.confidence * 100)}%` : 'Active'}
                      </Badge>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

export default function ProspectsPage() {
  return (
    <Suspense fallback={<div className="p-8 text-xs text-foreground-muted">Loading workspace...</div>}>
      <ProspectsWorkspaceContent />
    </Suspense>
  );
}
