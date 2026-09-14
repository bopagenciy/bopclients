'use client';

import React, { useEffect, useState } from 'react';
import { useI18n } from '@/lib/i18n/context';
import { useAuth } from '@/lib/auth/context';
import { DataTable, Column } from '@/components/ui/DataTable';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/states/EmptyState';
import { PermissionGate } from '@/components/navigation/PermissionGate';
import { Target, Plus } from 'lucide-react';

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

  useEffect(() => {
    async function fetchIcps() {
      setLoading(true);
      try {
        const res = await fetch('/api/proxy/api/v1/icps', { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          setIcps(data.items || []);
        } else {
          setIcps([]);
        }
      } catch {
        setIcps([]);
      } finally {
        setLoading(false);
      }
    }
    fetchIcps();
  }, [activeOrg]);

  const columns: Column<ICPItem>[] = [
    {
      header: t('icps.columns.name'),
      accessorKey: 'name',
      cell: (row) => (
        <div className="font-semibold text-foreground flex items-center gap-2">
          <Target className="w-4 h-4 text-brand-gold shrink-0" />
          <span>{row.name}</span>
        </div>
      ),
    },
    {
      header: t('icps.columns.industry'),
      cell: (row) => {
        const ind = row.industries && row.industries.length > 0 ? row.industries[0] : null;
        return (
          <Badge size="sm" variant="default">
            {ind || 'General'}
          </Badge>
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
        <div className="flex items-center gap-1">
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
          <Button size="sm">
            <Plus className="w-4 h-4 mr-1.5" />
            {t('icps.create_button')}
          </Button>
        </PermissionGate>
      </div>

      {icps.length === 0 && !loading ? (
        <EmptyState
          title={t('icps.empty')}
          description="Define firmographic scoring criteria to evaluate prospects against your ideal customer criteria."
          icon={<Target className="w-6 h-6 text-brand-gold" />}
        />
      ) : (
        <DataTable
          columns={columns}
          data={icps}
          isLoading={loading}
          emptyMessage={t('icps.empty')}
        />
      )}
    </div>
  );
}
