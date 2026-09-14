'use client';

import React, { useEffect, useState } from 'react';
import { useI18n } from '@/lib/i18n/context';
import { useAuth } from '@/lib/auth/context';
import { DataTable, Column } from '@/components/ui/DataTable';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/states/EmptyState';
import { PermissionGate } from '@/components/navigation/PermissionGate';
import { Globe2, Plus } from 'lucide-react';

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

export default function TargetMarketsPage() {
  const { t } = useI18n();
  const { activeOrg } = useAuth();
  const [markets, setMarkets] = useState<TargetMarketItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchMarkets() {
      setLoading(true);
      try {
        const res = await fetch('/api/proxy/api/v1/target-markets', { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          setMarkets(data.items || []);
        } else {
          setMarkets([]);
        }
      } catch {
        setMarkets([]);
      } finally {
        setLoading(false);
      }
    }
    fetchMarkets();
  }, [activeOrg]);

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
      cell: (row) => (
        <span className="font-mono text-xs text-foreground-muted">
          {row.icp_id ? `ICP-${row.icp_id.slice(0, 8)}` : '—'}
        </span>
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

        <PermissionGate permission="target_market.create">
          <Button size="sm">
            <Plus className="w-4 h-4 mr-1.5" />
            Add Market
          </Button>
        </PermissionGate>
      </div>

      {markets.length === 0 && !loading ? (
        <EmptyState
          title={t('target_markets.empty')}
          description="Segment your audience into geographic and vertical target territories."
          icon={<Globe2 className="w-6 h-6 text-brand-gold" />}
        />
      ) : (
        <DataTable
          columns={columns}
          data={markets}
          isLoading={loading}
          emptyMessage={t('target_markets.empty')}
        />
      )}
    </div>
  );
}
