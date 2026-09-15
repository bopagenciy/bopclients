'use client';

import React, { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { useI18n } from '@/lib/i18n/context';
import { DataTable, Column } from '@/components/ui/DataTable';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/states/EmptyState';
import { ErrorState } from '@/components/states/ErrorState';
import {
  Megaphone,
  ArrowLeft,
  Compass,
  ExternalLink,
  Users,
  Target,
  Calendar,
} from 'lucide-react';
import { CampaignProspectItem } from '@/lib/api/types';

interface CampaignDetail {
  id: string;
  name: string;
  description?: string;
  status: string;
  icp_id?: string;
  created_at: string;
}

export default function CampaignDetailPage() {
  const { t, locale } = useI18n();
  const params = useParams();
  const router = useRouter();
  const campaignId = params?.campaignId as string;

  const [campaign, setCampaign] = useState<CampaignDetail | null>(null);
  const [prospects, setProspects] = useState<CampaignProspectItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination state
  const [page, setPage] = useState(1);
  const [pageSize] = useState(15);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);

  const fetchCampaignData = useCallback(async () => {
    if (!campaignId) return;
    setLoading(true);
    setError(null);

    try {
      // 1. Fetch Campaign metadata
      const campRes = await fetch(`/api/proxy/api/v1/campaigns/${campaignId}`, {
        credentials: 'include',
      });
      if (!campRes.ok) {
        throw new Error(`Failed to load campaign details (${campRes.status})`);
      }
      const campData = await campRes.json();
      setCampaign(campData);

      // 2. Fetch Campaign Prospects
      const pParams = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      const prosRes = await fetch(
        `/api/proxy/api/v1/campaigns/${campaignId}/prospects?${pParams.toString()}`,
        { credentials: 'include' }
      );
      if (prosRes.ok) {
        const prosData = await prosRes.json();
        setProspects(prosData.items || []);
        setTotal(prosData.total || 0);
        setTotalPages(prosData.pages || 1);
      } else {
        setProspects([]);
      }
    } catch (err: any) {
      setError(err.message || 'Error loading campaign');
    } finally {
      setLoading(false);
    }
  }, [campaignId, page, pageSize]);

  useEffect(() => {
    fetchCampaignData();
  }, [fetchCampaignData]);

  const columns: Column<CampaignProspectItem>[] = [
    {
      header: t('prospects.columns.name'),
      accessorKey: 'name',
      cell: (row) => (
        <div>
          <Link
            href={`/${locale}/prospects/${row.prospect_id}`}
            className="font-semibold text-foreground hover:text-brand-gold flex items-center gap-1.5 transition-colors"
          >
            <span>{row.name}</span>
            <ExternalLink className="w-3 h-3 text-foreground-muted" />
          </Link>
          <div className="flex items-center gap-2 text-xs text-foreground-muted mt-0.5">
            {row.city && <span>{row.city}</span>}
            {row.state && <span>{row.state}</span>}
            {row.country && <span>({row.country})</span>}
          </div>
        </div>
      ),
    },
    {
      header: t('prospects.columns.industry'),
      accessorKey: 'industry',
      cell: (row) => (
        <span className="text-xs text-foreground-muted">
          {row.industry || '—'}
        </span>
      ),
    },
    {
      header: t('prospects.columns.status'),
      accessorKey: 'status',
      cell: (row) => {
        const s = (row.status || 'discovered').toLowerCase();
        const variant =
          s === 'qualified'
            ? 'success'
            : s === 'engaged'
            ? 'info'
            : s === 'disqualified'
            ? 'danger'
            : 'default';
        return <Badge size="sm" variant={variant}>{row.status}</Badge>;
      },
    },
    {
      header: 'Priority Rank',
      cell: (row) => {
        return (
          <div className="flex items-center gap-2">
            {row.priority !== undefined && row.priority !== null ? (
              <Badge size="sm" variant="outline">
                P{row.priority}
              </Badge>
            ) : (
              <span className="text-xs text-foreground-muted">—</span>
            )}
          </div>
        );
      },
    },
    {
      header: 'Added',
      accessorKey: 'added_at',
      cell: (row) => (
        <span className="text-xs text-foreground-muted font-mono">
          {row.added_at ? new Date(row.added_at).toLocaleDateString() : '—'}
        </span>
      ),
    },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (row) => (
        <Button
          size="sm"
          variant="ghost"
          onClick={() => router.push(`/${locale}/prospects/${row.prospect_id}`)}
        >
          {t('common.view')}
        </Button>
      ),
    },
  ];

  if (loading && !campaign) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="animate-spin h-8 w-8 border-2 border-brand-gold border-t-transparent rounded-full" />
      </div>
    );
  }

  if (error || !campaign) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" onClick={() => router.push(`/${locale}/campaigns`)}>
          <ArrowLeft className="w-4 h-4 mr-1.5" />
          {t('campaigns.title')}
        </Button>
        <ErrorState message={error || 'Campaign not found'} onRetry={fetchCampaignData} />
      </div>
    );
  }

  const s = (campaign.status || '').toLowerCase();
  const statusVariant =
    s === 'active'
      ? 'success'
      : s === 'paused'
      ? 'warning'
      : s === 'completed'
      ? 'info'
      : 'default';

  return (
    <div className="space-y-6">
      {/* Header & Breadcrumb */}
      <div className="space-y-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => router.push(`/${locale}/campaigns`)}
          className="-ml-2 text-foreground-muted hover:text-foreground"
        >
          <ArrowLeft className="w-4 h-4 mr-1.5" />
          {t('campaigns.title')}
        </Button>

        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <h1 className="text-2xl font-bold tracking-tight text-foreground">
                {campaign.name}
              </h1>
              <Badge size="sm" variant={statusVariant}>
                {campaign.status}
              </Badge>
            </div>
            {campaign.description && (
              <p className="text-xs text-foreground-muted max-w-2xl">
                {campaign.description}
              </p>
            )}
          </div>

          <Button
            size="sm"
            onClick={() => router.push(`/${locale}/discovery?campaignId=${campaign.id}`)}
          >
            <Compass className="w-4 h-4 mr-1.5 text-brand-gold" />
            {t('campaigns.run_discovery')}
          </Button>
        </div>
      </div>

      {/* Campaign Meta Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="p-4 rounded-lg border border-border bg-surface flex items-center gap-3">
          <div className="p-2.5 rounded-md bg-brand-gold/10 text-brand-gold">
            <Users className="w-5 h-5" />
          </div>
          <div>
            <p className="text-xs text-foreground-muted">{t('campaigns.prospects_tab')}</p>
            <p className="text-lg font-bold text-foreground">{total}</p>
          </div>
        </div>

        <div className="p-4 rounded-lg border border-border bg-surface flex items-center gap-3">
          <div className="p-2.5 rounded-md bg-brand-dark/10 text-brand-dark dark:text-brand-gold">
            <Target className="w-5 h-5" />
          </div>
          <div>
            <p className="text-xs text-foreground-muted">Linked ICP</p>
            <p className="text-xs font-semibold text-foreground font-mono">
              {campaign.icp_id ? `ICP-${campaign.icp_id.slice(0, 8)}` : 'None'}
            </p>
          </div>
        </div>

        <div className="p-4 rounded-lg border border-border bg-surface flex items-center gap-3">
          <div className="p-2.5 rounded-md bg-surface-subtle text-foreground-muted">
            <Calendar className="w-5 h-5" />
          </div>
          <div>
            <p className="text-xs text-foreground-muted">Created</p>
            <p className="text-xs font-semibold text-foreground font-mono">
              {new Date(campaign.created_at).toLocaleDateString()}
            </p>
          </div>
        </div>
      </div>

      {/* Campaign Prospects Table */}
      <div className="space-y-3">
        <h2 className="text-lg font-bold tracking-tight text-foreground">
          {t('campaigns.prospects_tab')} ({total})
        </h2>

        {prospects.length === 0 && !loading ? (
          <EmptyState
            title={t('campaigns.empty_prospects')}
            description="Run discovery or import target accounts to populate this campaign pipeline."
            icon={<Megaphone className="w-6 h-6 text-brand-gold" />}
            actionLabel={t('campaigns.run_discovery')}
            onAction={() => router.push(`/${locale}/discovery?campaignId=${campaign.id}`)}
          />
        ) : (
          <div className="space-y-4">
            <DataTable
              columns={columns}
              data={prospects}
              isLoading={loading}
              emptyMessage={t('campaigns.empty_prospects')}
            />

            {/* Pagination */}
            <div className="flex items-center justify-between px-2 text-xs text-foreground-muted">
              <span>
                {t('prospects.pagination.showing', {
                  start: prospects.length === 0 ? 0 : (page - 1) * pageSize + 1,
                  end: Math.min(page * pageSize, total),
                  total,
                })}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={page <= 1 || loading}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  {t('prospects.pagination.previous')}
                </Button>
                <span className="font-mono">
                  {t('prospects.pagination.page', { page, pages: totalPages })}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={page >= totalPages || loading}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                >
                  {t('prospects.pagination.next')}
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
