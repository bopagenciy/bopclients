'use client';

import React, { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
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
} from 'lucide-react';

interface ProspectItem {
  id: string;
  name: string;
  website_url?: string;
  phone?: string;
  email?: string;
  city?: string;
  state?: string;
  country?: string;
  industry?: string;
  source?: string;
  created_at: string;
}

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

export default function ProspectsPage() {
  const { t, locale } = useI18n();
  const { activeOrg } = useAuth();

  const [prospects, setProspects] = useState<ProspectItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Pagination & filtering state
  const [page, setPage] = useState(1);
  const [pageSize] = useState(15);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [searchQuery, setSearchQuery] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');

  // Selected prospect for detail modal
  const [selectedProspect, setSelectedProspect] = useState<ProspectItem | null>(null);
  const [prospectSignals, setProspectSignals] = useState<SignalItem[]>([]);
  const [loadingSignals, setLoadingSignals] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);

  // Debounce search query
  useEffect(() => {
    const handler = setTimeout(() => {
      setDebouncedSearch(searchQuery);
      setPage(1);
    }, 300);
    return () => clearTimeout(handler);
  }, [searchQuery]);

  const loadProspects = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (debouncedSearch.trim()) {
        params.append('search', debouncedSearch.trim());
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
  }, [page, pageSize, debouncedSearch]);

  useEffect(() => {
    loadProspects();
  }, [loadProspects, activeOrg]);

  // Load signals when a prospect is selected
  const handleSelectProspect = async (p: ProspectItem) => {
    setSelectedProspect(p);
    setIsModalOpen(true);
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

  const columns: Column<ProspectItem>[] = [
    {
      header: t('prospects.columns.company'),
      accessorKey: 'name',
      cell: (row) => (
        <div className="font-medium text-foreground flex items-center gap-2">
          <Building className="w-4 h-4 text-brand-gold shrink-0" />
          <Link
            href={`/${locale}/prospects/${row.id}`}
            className="truncate hover:text-brand-gold hover:underline transition-colors"
          >
            {row.name}
          </Link>
        </div>
      ),
    },
    {
      header: t('prospects.columns.email'),
      accessorKey: 'email',
      cell: (row) => (
        <span className="text-xs text-foreground-muted font-mono truncate">
          {row.email || '—'}
        </span>
      ),
    },
    {
      header: 'Industry',
      accessorKey: 'industry',
      cell: (row) => (
        <Badge size="sm" variant="default">
          {row.industry || 'General'}
        </Badge>
      ),
    },
    {
      header: 'Location',
      cell: (row) => {
        const parts = [row.city, row.state, row.country].filter(Boolean);
        return (
          <span className="text-xs text-foreground-muted">
            {parts.length > 0 ? parts.join(', ') : '—'}
          </span>
        );
      },
    },
    {
      header: 'Source',
      accessorKey: 'source',
      cell: (row) => (
        <span className="text-xs text-foreground-muted font-mono">
          {row.source || 'forge_discovery'}
        </span>
      ),
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
            handleSelectProspect(row);
          }}
        >
          {t('common.view')}
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      {/* Page Title */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            {t('prospects.title')}
          </h1>
          <p className="text-xs text-foreground-muted">
            {t('prospects.subtitle')}
          </p>
        </div>
        <div className="text-xs font-medium text-foreground-muted">
          Total: <span className="font-bold text-foreground">{total}</span>
        </div>
      </div>

      {/* Filters & Search */}
      <div className="flex flex-col sm:flex-row items-center gap-3">
        <div className="relative flex-1 w-full">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-foreground-muted" />
          <input
            type="text"
            className="w-full h-9 pl-9 pr-3 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark"
            placeholder={t('prospects.search_placeholder')}
            value={searchQuery}
            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearchQuery(e.target.value)}
          />
        </div>
        <Button size="sm" variant="secondary" onClick={() => loadProspects()}>
          {t('common.refresh')}
        </Button>
      </div>

      {/* Error or Table View */}
      {error ? (
        <ErrorState message={error} onRetry={loadProspects} />
      ) : prospects.length === 0 && !loading ? (
        <EmptyState
          title={t('prospects.empty')}
          description="Try modifying your search criteria or running a new discovery pipeline."
          icon={<Users className="w-6 h-6 text-brand-gold" />}
        />
      ) : (
        <div className="space-y-4">
          <DataTable
            columns={columns}
            data={prospects}
            isLoading={loading}
            emptyMessage={t('prospects.empty')}
            onRowClick={(row) => handleSelectProspect(row)}
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
                onClick={() => setPage((p) => Math.max(p - 1, 1))}
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
                onClick={() => setPage((p) => Math.min(p + 1, totalPages))}
              >
                {t('prospects.pagination.next')}
                <ChevronRight className="w-3.5 h-3.5 ml-1" />
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Prospect Detail Modal */}
      {selectedProspect && (
        <Modal
          isOpen={isModalOpen}
          onClose={() => setIsModalOpen(false)}
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
                <p className="text-foreground-muted font-medium">Email</p>
                <p className="font-mono text-foreground">{selectedProspect.email || '—'}</p>
              </div>
              <div>
                <p className="text-foreground-muted font-medium">Phone</p>
                <p className="font-mono text-foreground">{selectedProspect.phone || '—'}</p>
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

            {/* Real Enrichment Signals (NO hardcoded fake signals) */}
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
                          <p className="text-[11px] text-foreground-muted line-clamp-1">{sig.summary}</p>
                        )}
                        <p className="text-[10px] text-foreground-muted font-mono">{sig.signal_type}</p>
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
