'use client';

import React, { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useI18n } from '@/lib/i18n/context';
import { useAuth } from '@/lib/auth/context';
import { DataTable, Column } from '@/components/ui/DataTable';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { EmptyState } from '@/components/states/EmptyState';
import { ErrorState } from '@/components/states/ErrorState';
import { PermissionGate } from '@/components/navigation/PermissionGate';
import { Megaphone, Plus, Edit2, Compass, ExternalLink, AlertCircle } from 'lucide-react';

interface CampaignItem {
  id: string;
  name: string;
  description?: string;
  status: string;
  icp_id?: string;
  created_at: string;
}

interface ICPItem {
  id: string;
  name: string;
}

export default function CampaignsPage() {
  const { t, locale } = useI18n();
  const { activeOrg } = useAuth();
  const router = useRouter();

  const [campaigns, setCampaigns] = useState<CampaignItem[]>([]);
  const [icps, setIcps] = useState<ICPItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingCampaign, setEditingCampaign] = useState<CampaignItem | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    icp_id: '',
    status: 'draft',
  });
  const [formSubmitting, setFormSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const fetchCampaigns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [resCampaigns, resIcps] = await Promise.all([
        fetch('/api/proxy/api/v1/campaigns', { credentials: 'include' }),
        fetch('/api/proxy/api/v1/icps', { credentials: 'include' }),
      ]);

      if (resCampaigns.ok) {
        const data = await resCampaigns.json();
        setCampaigns(data.items || []);
      } else {
        const err = await resCampaigns.json().catch(() => ({}));
        setError(err.error?.message || `Failed to fetch campaigns (${resCampaigns.status})`);
        setCampaigns([]);
      }

      if (resIcps.ok) {
        const data = await resIcps.json();
        setIcps(data.items || []);
      }
    } catch (e: any) {
      setError(e?.message || 'Network error fetching campaigns');
      setCampaigns([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchCampaigns();
  }, [activeOrg, fetchCampaigns]);

  const openCreateModal = () => {
    setEditingCampaign(null);
    setFormData({
      name: '',
      description: '',
      icp_id: '',
      status: 'draft',
    });
    setFormError(null);
    setIsModalOpen(true);
  };

  const openEditModal = (camp: CampaignItem) => {
    setEditingCampaign(camp);
    setFormData({
      name: camp.name,
      description: camp.description || '',
      icp_id: camp.icp_id || '',
      status: camp.status || 'draft',
    });
    setFormError(null);
    setIsModalOpen(true);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name.trim()) {
      setFormError('Campaign name is required');
      return;
    }

    setFormSubmitting(true);
    setFormError(null);

    const payload: any = {
      name: formData.name.trim(),
      description: formData.description.trim() || undefined,
      icp_id: formData.icp_id || undefined,
      status: formData.status,
    };

    try {
      const url = editingCampaign
        ? `/api/proxy/api/v1/campaigns/${editingCampaign.id}`
        : '/api/proxy/api/v1/campaigns';
      const method = editingCampaign ? 'PATCH' : 'POST';

      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        credentials: 'include',
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || `Failed to save campaign (${res.status})`);
      }

      setIsModalOpen(false);
      fetchCampaigns();
    } catch (err: any) {
      setFormError(err.message || 'Error saving campaign');
    } finally {
      setFormSubmitting(false);
    }
  };

  const columns: Column<CampaignItem>[] = [
    {
      header: t('campaigns.columns.name'),
      accessorKey: 'name',
      cell: (row) => (
        <div>
          <Link
            href={`/${locale}/campaigns/${row.id}`}
            className="font-semibold text-foreground hover:text-brand-gold flex items-center gap-1.5 transition-colors"
          >
            <Megaphone className="w-4 h-4 text-brand-gold shrink-0" />
            <span>{row.name}</span>
          </Link>
          {row.description && (
            <p className="text-xs text-foreground-muted truncate max-w-sm mt-0.5">{row.description}</p>
          )}
        </div>
      ),
    },
    {
      header: t('campaigns.columns.status'),
      accessorKey: 'status',
      cell: (row) => {
        const s = (row.status || '').toLowerCase();
        const variant =
          s === 'active'
            ? 'success'
            : s === 'paused'
            ? 'warning'
            : s === 'completed'
            ? 'info'
            : 'default';
        return <Badge size="sm" variant={variant}>{row.status}</Badge>;
      },
    },
    {
      header: 'Linked ICP',
      cell: (row) => {
        const linkedIcp = icps.find((i) => i.id === row.icp_id);
        return (
          <span className="text-xs text-foreground-muted font-mono">
            {linkedIcp ? linkedIcp.name : row.icp_id ? `ICP-${row.icp_id.slice(0, 8)}` : '—'}
          </span>
        );
      },
    },
    {
      header: t('campaigns.columns.created_at'),
      accessorKey: 'created_at',
      cell: (row) => (
        <span className="text-xs text-foreground-muted font-mono">
          {new Date(row.created_at).toLocaleDateString()}
        </span>
      ),
    },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (row) => (
        <div className="flex items-center justify-end gap-1.5">
          <Button
            size="sm"
            variant="ghost"
            onClick={(e) => {
              e.stopPropagation();
              router.push(`/${locale}/discovery?campaignId=${row.id}`);
            }}
            title={t('campaigns.run_discovery')}
          >
            <Compass className="w-3.5 h-3.5 text-brand-gold mr-1" />
            {t('campaigns.run_discovery')}
          </Button>
          <PermissionGate permission="campaign.update">
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
          <Link href={`/${locale}/campaigns/${row.id}`}>
            <Button size="sm" variant="ghost">
              <ExternalLink className="w-3.5 h-3.5" />
            </Button>
          </Link>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            {t('campaigns.title')}
          </h1>
          <p className="text-xs text-foreground-muted">
            {t('campaigns.subtitle')}
          </p>
        </div>

        <PermissionGate permission="campaign.create">
          <Button size="sm" onClick={openCreateModal}>
            <Plus className="w-4 h-4 mr-1.5" />
            {t('campaigns.create_button')}
          </Button>
        </PermissionGate>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={fetchCampaigns} />
      ) : campaigns.length === 0 && !loading ? (
        <EmptyState
          title={t('campaigns.empty')}
          description="Build structured outbound campaigns linked to Ideal Customer Profiles."
          icon={<Megaphone className="w-6 h-6 text-brand-gold" />}
          actionLabel={t('campaigns.create_button')}
          onAction={openCreateModal}
        />
      ) : (
        <DataTable
          columns={columns}
          data={campaigns}
          isLoading={loading}
          emptyMessage={t('campaigns.empty')}
          onRowClick={(row) => router.push(`/${locale}/campaigns/${row.id}`)}
        />
      )}

      {/* Create / Edit Modal */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title={editingCampaign ? t('campaigns.modal_edit_title') : t('campaigns.modal_create_title')}
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
              {t('campaigns.form_name')} *
            </label>
            <input
              type="text"
              required
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder={t('campaigns.form_name_placeholder')}
              className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-foreground mb-1">
              {t('campaigns.form_description')}
            </label>
            <textarea
              rows={2}
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder={t('campaigns.form_description_placeholder')}
              className="w-full p-2.5 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark resize-none"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                {t('campaigns.form_icp')}
              </label>
              <select
                value={formData.icp_id}
                onChange={(e) => setFormData({ ...formData, icp_id: e.target.value })}
                className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-brand-dark"
              >
                <option value="">{t('campaigns.form_icp_placeholder')}</option>
                {icps.map((icp) => (
                  <option key={icp.id} value={icp.id}>
                    {icp.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                {t('campaigns.form_status')}
              </label>
              <select
                value={formData.status}
                onChange={(e) => setFormData({ ...formData, status: e.target.value })}
                className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-brand-dark"
              >
                <option value="draft">Draft</option>
                <option value="active">Active</option>
                <option value="paused">Paused</option>
                <option value="completed">Completed</option>
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
