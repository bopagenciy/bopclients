'use client';

import React, { useEffect, useState } from 'react';
import { useI18n } from '@/lib/i18n/context';
import { useAuth } from '@/lib/auth/context';
import { DataTable, Column } from '@/components/ui/DataTable';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/states/EmptyState';
import { PermissionGate } from '@/components/navigation/PermissionGate';
import { Megaphone, Plus } from 'lucide-react';

interface CampaignItem {
  id: string;
  name: string;
  description?: string;
  status: string;
  icp_id?: string;
  created_at: string;
}

export default function CampaignsPage() {
  const { t } = useI18n();
  const { activeOrg } = useAuth();
  const [campaigns, setCampaigns] = useState<CampaignItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchCampaigns() {
      setLoading(true);
      try {
        const res = await fetch('/api/proxy/api/v1/campaigns', { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          setCampaigns(data.items || []);
        } else {
          setCampaigns([]);
        }
      } catch {
        setCampaigns([]);
      } finally {
        setLoading(false);
      }
    }
    fetchCampaigns();
  }, [activeOrg]);

  const columns: Column<CampaignItem>[] = [
    {
      header: t('campaigns.columns.name'),
      accessorKey: 'name',
      cell: (row) => (
        <div>
          <p className="font-semibold text-foreground">{row.name}</p>
          {row.description && (
            <p className="text-xs text-foreground-muted truncate max-w-sm">{row.description}</p>
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
      cell: (row) => (
        <span className="text-xs text-foreground-muted font-mono">
          {row.icp_id ? `ICP-${row.icp_id.slice(0, 8)}` : '—'}
        </span>
      ),
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

        {/* Member allowed, Viewer denied */}
        <PermissionGate permission="campaign.create">
          <Button size="sm">
            <Plus className="w-4 h-4 mr-1.5" />
            {t('campaigns.create_button')}
          </Button>
        </PermissionGate>
      </div>

      {campaigns.length === 0 && !loading ? (
        <EmptyState
          title={t('campaigns.empty')}
          description="Create your first outbound prospecting campaign linked to an Ideal Customer Profile."
          icon={<Megaphone className="w-6 h-6 text-brand-gold" />}
        />
      ) : (
        <DataTable
          columns={columns}
          data={campaigns}
          isLoading={loading}
          emptyMessage={t('campaigns.empty')}
        />
      )}
    </div>
  );
}
