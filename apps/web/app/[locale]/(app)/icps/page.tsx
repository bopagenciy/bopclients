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
import { Target, Plus, Edit2, AlertCircle } from 'lucide-react';

interface ICPItem {
  id: string;
  organization_id: string;
  name: string;
  description?: string | null;
  industries: string[];
  company_sizes: string[];
  decision_maker_roles: string[];
  pain_points: string[];
  desired_signals: string[];
  excluded_signals: string[];
  countries: string[];
  languages: string[];
  created_at: string;
}

export default function ICPsPage() {
  const { t } = useI18n();
  const { activeOrg } = useAuth();
  const [icps, setIcps] = useState<ICPItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingIcp, setEditingIcp] = useState<ICPItem | null>(null);
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    industries: '',
    company_sizes: '',
    countries: '',
    decision_maker_roles: '',
  });
  const [formSubmitting, setFormSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const fetchIcps = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/proxy/api/v1/icps', { credentials: 'include' });
      if (res.ok) {
        const data = await res.json();
        setIcps(data.items || []);
      } else {
        const err = await res.json().catch(() => ({}));
        setError(err.error?.message || `Failed to fetch ICPs (Status ${res.status})`);
        setIcps([]);
      }
    } catch (e: any) {
      setError(e?.message || 'Network error fetching ICPs');
      setIcps([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchIcps();
  }, [activeOrg, fetchIcps]);

  const openCreateModal = () => {
    setEditingIcp(null);
    setFormData({
      name: '',
      description: '',
      industries: '',
      company_sizes: '',
      countries: '',
      decision_maker_roles: '',
    });
    setFormError(null);
    setIsModalOpen(true);
  };

  const openEditModal = (icp: ICPItem) => {
    setEditingIcp(icp);
    setFormData({
      name: icp.name,
      description: icp.description || '',
      industries: (icp.industries || []).join(', '),
      company_sizes: (icp.company_sizes || []).join(', '),
      countries: (icp.countries || []).join(', '),
      decision_maker_roles: (icp.decision_maker_roles || []).join(', '),
    });
    setFormError(null);
    setIsModalOpen(true);
  };

  const closeModal = useCallback(() => {
    setIsModalOpen(false);
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name.trim()) {
      setFormError('Name is required');
      return;
    }

    setFormSubmitting(true);
    setFormError(null);

    const payload = {
      name: formData.name.trim(),
      description: formData.description.trim() || undefined,
      industries: formData.industries
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      company_sizes: formData.company_sizes
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      countries: formData.countries
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      decision_maker_roles: formData.decision_maker_roles
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
    };

    try {
      const url = editingIcp
        ? `/api/proxy/api/v1/icps/${editingIcp.id}`
        : '/api/proxy/api/v1/icps';
      const method = editingIcp ? 'PATCH' : 'POST';

      const res = await fetch(url, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        credentials: 'include',
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error?.message || `Failed to save ICP (${res.status})`);
      }

      setIsModalOpen(false);
      fetchIcps();
    } catch (err: any) {
      setFormError(err.message || 'Error saving ICP');
    } finally {
      setFormSubmitting(false);
    }
  };

  const columns: Column<ICPItem>[] = [
    {
      header: t('icps.columns.name'),
      accessorKey: 'name',
      cell: (row) => (
        <div>
          <div className="font-semibold text-foreground flex items-center gap-2">
            <Target className="w-4 h-4 text-brand-gold shrink-0" />
            <span>{row.name}</span>
          </div>
          {row.description && (
            <p className="text-xs text-foreground-muted mt-0.5 line-clamp-1">{row.description}</p>
          )}
        </div>
      ),
    },
    {
      header: t('icps.columns.industry'),
      cell: (row) => {
        const ind = row.industries && row.industries.length > 0 ? row.industries : [];
        if (ind.length === 0) return <span className="text-xs text-foreground-muted">—</span>;
        return (
          <div className="flex flex-wrap gap-1">
            {ind.slice(0, 2).map((item) => (
              <Badge key={item} size="sm" variant="default">
                {item}
              </Badge>
            ))}
            {ind.length > 2 && (
              <Badge size="sm" variant="outline">
                +{ind.length - 2}
              </Badge>
            )}
          </div>
        );
      },
    },
    {
      header: t('icps.columns.target_headcount'),
      cell: (row) => {
        const size = row.company_sizes && row.company_sizes.length > 0 ? row.company_sizes.join(', ') : '—';
        return <span className="text-xs text-foreground-muted">{size}</span>;
      },
    },
    {
      header: t('icps.columns.geo_markets'),
      cell: (row) => (
        <div className="flex items-center gap-1 flex-wrap">
          {row.countries && row.countries.length > 0 ? (
            row.countries.map((c) => (
              <Badge key={c} size="sm" variant="outline">{c}</Badge>
            ))
          ) : (
            <span className="text-xs text-foreground-muted">—</span>
          )}
        </div>
      ),
    },
    {
      header: 'Created',
      accessorKey: 'created_at',
      cell: (row) => (
        <span className="text-xs text-foreground-muted font-mono">
          {row.created_at ? new Date(row.created_at).toLocaleDateString() : '—'}
        </span>
      ),
    },
    {
      header: 'Actions',
      className: 'text-right',
      cell: (row) => (
        <PermissionGate permission="icp.manage">
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
            {t('icps.title')}
          </h1>
          <p className="text-xs text-foreground-muted">
            {t('icps.subtitle')}
          </p>
        </div>

        {/* Member allowed, Viewer denied */}
        <PermissionGate permission="icp.manage">
          <Button size="sm" onClick={openCreateModal}>
            <Plus className="w-4 h-4 mr-1.5" />
            {t('icps.create_button')}
          </Button>
        </PermissionGate>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={fetchIcps} />
      ) : icps.length === 0 && !loading ? (
        <EmptyState
          title={t('icps.empty')}
          description="Define firmographic scoring criteria to evaluate prospects against your ideal customer criteria."
          icon={<Target className="w-6 h-6 text-brand-gold" />}
          actionLabel={t('icps.create_button')}
          onAction={openCreateModal}
        />
      ) : (
        <DataTable
          columns={columns}
          data={icps}
          isLoading={loading}
          emptyMessage={t('icps.empty')}
        />
      )}

      {/* Create / Edit ICP Modal */}
      <Modal
        isOpen={isModalOpen}
        onClose={closeModal}
        title={editingIcp ? t('icps.modal_edit_title') : t('icps.modal_create_title')}
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
              {t('icps.form_name')} *
            </label>
            <input
              type="text"
              required
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder={t('icps.form_name_placeholder')}
              className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-foreground mb-1">
              {t('icps.form_description')}
            </label>
            <textarea
              rows={2}
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder={t('icps.form_description_placeholder')}
              className="w-full p-2.5 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark resize-none"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-foreground mb-1">
              {t('icps.form_industries')}
            </label>
            <input
              type="text"
              value={formData.industries}
              onChange={(e) => setFormData({ ...formData, industries: e.target.value })}
              placeholder={t('icps.form_industries_placeholder')}
              className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                {t('icps.form_company_sizes')}
              </label>
              <input
                type="text"
                value={formData.company_sizes}
                onChange={(e) => setFormData({ ...formData, company_sizes: e.target.value })}
                placeholder={t('icps.form_company_sizes_placeholder')}
                className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark"
              />
            </div>
            <div>
              <label className="block text-xs font-semibold text-foreground mb-1">
                {t('icps.form_countries')}
              </label>
              <input
                type="text"
                value={formData.countries}
                onChange={(e) => setFormData({ ...formData, countries: e.target.value })}
                placeholder={t('icps.form_countries_placeholder')}
                className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-foreground mb-1">
              {t('icps.form_roles')}
            </label>
            <input
              type="text"
              value={formData.decision_maker_roles}
              onChange={(e) => setFormData({ ...formData, decision_maker_roles: e.target.value })}
              placeholder={t('icps.form_roles_placeholder')}
              className="w-full h-9 px-3 rounded-md border border-border bg-surface text-xs text-foreground placeholder:text-foreground-muted focus:outline-none focus:ring-2 focus:ring-brand-dark"
            />
          </div>

          <div className="flex justify-end gap-2 pt-3 border-t border-border">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={closeModal}
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
