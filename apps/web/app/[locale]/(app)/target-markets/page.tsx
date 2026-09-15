'use client';

import React, { useEffect, useState, useCallback } from 'react';
import { useI18n } from '@/lib/i18n/context';
import { useAuth } from '@/lib/auth/context';
import { DataTable, Column } from '@/components/ui/DataTable';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { EmptyState } from '@/components/states/EmptyState';
import { ErrorState } from '@/components/states/ErrorState';
import { PermissionGate } from '@/components/navigation/PermissionGate';
import { Globe2, Plus, Edit2, AlertCircle } from 'lucide-react';

interface TargetMarketItem {
  id: string;
  icp_id?: string;
  country: string;
  region?: string;
  city?: string;
  postal_code?: string;
  radius_miles?: number;
  language?: string;
}

interface ICPItem {
  id: string;
  name: string;
}

export default function TargetMarketsPage() {
  const { t } = useI18n();
  const { activeOrg } = useAuth();
  const [markets, setMarkets] = useState<TargetMarketItem[]>([]);
  const [icps, setIcps] = useState<ICPItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingMarket, setEditingMarket] = useState<TargetMarketItem | null>(null);
  const [formData, setFormData] = useState({
    icp_id: '',
    country: 'US',
    region: '',
    city: '',
    postal_code: '',
    radius_miles: '',
    language: 'en',
  });
  const [formSubmitting, setFormSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const fetchMarkets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [resMarkets, resIcps] = await Promise.all([
        fetch('/api/proxy/api/v1/target-markets', { credentials: 'include' }),
        fetch('/api/proxy/api/v1/icps', { credentials: 'include' }),
      ]);

      if (resMarkets.ok) {
        const data = await resMarkets.json();
        setMarkets(data.items || []);
      } else {
        const err = await resMarkets.json().catch(() => ({}));
        setError(err.error?.message || `Failed to fetch target markets (${resMarkets.status})`);
        setMarkets([]);
      }

      if (resIcps.ok) {
        const data = await resIcps.json();
        setIcps(data.items || []);
      }
    } catch (e: any) {
      setError(e?.message || 'Network error fetching target markets');
      setMarkets([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMarkets();
  }, [activeOrg, fetchMarkets]);

  const openCreateModal = () => {
    setEditingMarket(null);
    setFormData({
      icp_id: icps.length > 0 ? icps[0].id : '',
      country: 'US',
      region: '',
      city: '',
      postal_code: '',
      radius_miles: '',
      language: 'en',
    });
    setFormError(null);
    setIsModalOpen(true);
  };

  const openEditModal = (market: TargetMarketItem) => {
    setEditingMarket(market);
    setFormData({
      icp_id: market.icp_id || '',
      country: market.country || 'US',
      region: market.region || '',
      city: market.city || '',
      postal_code: market.postal_code || '',
      radius_miles: market.radius_miles !== undefined ? String(market.radius_miles) : '',
      language: market.language || 'en',
    });
    setFormError(null);
    setIsModalOpen(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.country.trim()) {
      setFormError('Country code is required');
      return;
    }

    setFormSubmitting(true);
    setFormError(null);

    const payload: any = {
      country: formData.country.trim(),
      region: formData.region.trim() || undefined,
      city: formData.city.trim() || undefined,
      postal_code: formData.postal_code.trim() || undefined,
      radius_miles: formData.radius_miles ? parseFloat(formData.radius_miles) : undefined,
      language: formData.language.trim() || undefined,
      icp_id: formData.icp_id || undefined,
    };

    try {
      const url = editingMarket
        ? `/api/proxy/api/v1/target-markets/${editingMarket.id}`
        : '/api/proxy/api/v1/target-markets';
      const method = editingMarket ? 'PATCH' : 'POST';

      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        credentials: 'include',
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || `Failed to save target market (${res.status})`);
      }

      setIsModalOpen(false);
      fetchMarkets();
    } catch (err: any) {
      setFormError(err.message || 'Error saving target market');
    } finally {
      setFormSubmitting(false);
    }
  };

  const columns: Column<TargetMarketItem>[] = [
    {
      header: t('target_markets.columns.region'),
      accessorKey: 'country',
      cell: (row) => (
        <div className="font-semibold text-foreground flex items-center gap-2">
          <Globe2 className="w-4 h-4 text-brand-gold shrink-0" />
          <span>{row.country || 'Global'}</span>
        </div>
      ),
    },
    {
      header: 'Sub-Region / City',
      cell: (row) => {
        const loc = [row.city, row.region].filter(Boolean).join(', ');
        return <span className="text-xs text-foreground-muted">{loc || 'Territory-wide'}</span>;
      },
    },
    {
      header: 'Radius',
      cell: (row) => (
        <span className="text-xs text-foreground-muted">
          {row.radius_miles ? `${row.radius_miles} mi` : 'Exact boundary'}
        </span>
      ),
    },
    {
      header: 'Language',
      cell: (row) => (
        <Badge size="sm" variant="outline">
          {(row.language || 'en').toUpperCase()}
        </Badge>
      ),
    },
    {
      header: 'Linked ICP',
      cell: (row) => {
        const linkedIcp = icps.find((i) => i.id === row.icp_id);
        return (
          <span className="text-xs text-foreground-muted">
            {linkedIcp ? linkedIcp.name : row.icp_id ? `ICP-${row.icp_id.slice(0, 8)}` : '—'}
          </span>
        );
      },
    },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (row) => (
        <PermissionGate permission="target_market.manage">
          <Button
            size="sm"
            variant="ghost"
            onClick={(e) => {
              e.stopPropagation();
              openEditModal(row);
            }}
          >
            <Edit2 className="w-3.5 h-3.5 mr-1" />
            Edit
          </Button>
        </PermissionGate>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            {t('target_markets.title')}
          </h1>
          <p className="text-xs text-foreground-muted">
            {t('target_markets.subtitle')}
          </p>
        </div>

        <PermissionGate permission="target_market.manage">
          <Button size="sm" onClick={openCreateModal}>
            <Plus className="w-4 h-4 mr-1.5" />
            {t('target_markets.create_button')}
          </Button>
        </PermissionGate>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={fetchMarkets} />
      ) : markets.length === 0 && !loading ? (
        <EmptyState
          title={t('target_markets.empty')}
          description="Segment target accounts by geography, regional territories, and local language preferences."
          icon={<Globe2 className="w-6 h-6 text-brand-gold" />}
          actionLabel={t('target_markets.create_button')}
          onAction={openCreateModal}
        />
      ) : (
        <DataTable
          columns={columns}
          data={markets}
          isLoading={loading}
          emptyMessage={t('target_markets.empty')}
        />
      )}

      {/* Create / Edit Modal */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title={editingMarket ? t('target_markets.modal_edit_title') : t('target_markets.modal_create_title')}
      >
        <form onSubmit={handleSubmit} className="space-y-4">
          {formError && (
            <div className="p-3 bg-danger/10 border border-danger/30 rounded-md text-xs text-danger flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{formError}</span>
            </div>
          )}

          <div>
            <label className="block text-xs font-semibold text-foreground mb-1">
              {t('target_markets.form_icp')}
            </label>
            <select
              value={formData.icp_id}
              onChange={(e) => setFormData({ ...formData, icp_id: e.target.value })}
              className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-brand-dark"
            >
              <option value="">{t('target_markets.form_icp_placeholder')}</option>
              {icps.map((icp) => (
                <option key={icp.id} value={icp.id}>
                  {icp.name}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                {t('target_markets.form_country')} *
              </label>
              <input
                type="text"
                required
                value={formData.country}
                onChange={(e) => setFormData({ ...formData, country: e.target.value })}
                placeholder={t('target_markets.form_country_placeholder')}
                className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                {t('target_markets.form_region')}
              </label>
              <input
                type="text"
                value={formData.region}
                onChange={(e) => setFormData({ ...formData, region: e.target.value })}
                placeholder={t('target_markets.form_region_placeholder')}
                className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                {t('target_markets.form_city')}
              </label>
              <input
                type="text"
                value={formData.city}
                onChange={(e) => setFormData({ ...formData, city: e.target.value })}
                placeholder={t('target_markets.form_city_placeholder')}
                className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                {t('target_markets.form_postal_code')}
              </label>
              <input
                type="text"
                value={formData.postal_code}
                onChange={(e) => setFormData({ ...formData, postal_code: e.target.value })}
                placeholder={t('target_markets.form_postal_code_placeholder')}
                className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                {t('target_markets.form_radius')}
              </label>
              <input
                type="number"
                min="0"
                step="1"
                value={formData.radius_miles}
                onChange={(e) => setFormData({ ...formData, radius_miles: e.target.value })}
                placeholder="25"
                className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                {t('target_markets.form_language')}
              </label>
              <select
                value={formData.language}
                onChange={(e) => setFormData({ ...formData, language: e.target.value })}
                className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-brand-dark"
              >
                <option value="en">English (en)</option>
                <option value="es">Spanish (es)</option>
              </select>
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-border">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setIsModalOpen(false)}
              disabled={formSubmitting}
            >
              {t('common.cancel')}
            </Button>
            <Button type="submit" size="sm" disabled={formSubmitting}>
              {formSubmitting ? t('common.saving') : t('common.save')}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
