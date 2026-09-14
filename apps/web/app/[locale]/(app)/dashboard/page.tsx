'use client';

import React, { useEffect, useState } from 'react';
import { useI18n } from '@/lib/i18n/context';
import { useAuth } from '@/lib/auth/context';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/states/EmptyState';
import { PermissionGate } from '@/components/navigation/PermissionGate';
import {
  Users,
  Megaphone,
  Target,
  Globe2,
  ArrowUpRight,
  ShieldCheck,
  Inbox,
  Sparkles,
} from 'lucide-react';
import Link from 'next/link';

interface DashboardTotals {
  totalProspects: number | null;
  totalCampaigns: number | null;
  totalICPs: number | null;
  totalTargetMarkets: number | null;
  loading: boolean;
}

interface ICPItem {
  id: string;
  name: string;
  industries?: string[];
}

export default function DashboardPage() {
  const { t, locale } = useI18n();
  const { activeOrg } = useAuth();
  const [stats, setStats] = useState<DashboardTotals>({
    totalProspects: null,
    totalCampaigns: null,
    totalICPs: null,
    totalTargetMarkets: null,
    loading: true,
  });
  const [recentICPs, setRecentICPs] = useState<ICPItem[]>([]);

  useEffect(() => {
    async function loadTruthfulDashboardData() {
      setStats((prev) => ({ ...prev, loading: true }));
      try {
        // Query only actual P19 pagination endpoints for real totals
        const [prospectsRes, campaignsRes, icpsRes, marketsRes] = await Promise.allSettled([
          fetch('/api/proxy/api/v1/prospects?page=1&page_size=1', { credentials: 'include' }),
          fetch('/api/proxy/api/v1/campaigns?page=1&page_size=1', { credentials: 'include' }),
          fetch('/api/proxy/api/v1/icps?page=1&page_size=5', { credentials: 'include' }),
          fetch('/api/proxy/api/v1/target-markets?page=1&page_size=1', { credentials: 'include' }),
        ]);

        let totalProspects = 0;
        let totalCampaigns = 0;
        let totalICPs = 0;
        let totalTargetMarkets = 0;

        if (prospectsRes.status === 'fulfilled' && prospectsRes.value.ok) {
          const pData = await prospectsRes.value.json();
          totalProspects = pData.total_items ?? 0;
        }

        if (campaignsRes.status === 'fulfilled' && campaignsRes.value.ok) {
          const cData = await campaignsRes.value.json();
          totalCampaigns = cData.total_items ?? 0;
        }

        if (icpsRes.status === 'fulfilled' && icpsRes.value.ok) {
          const iData = await icpsRes.value.json();
          totalICPs = iData.total_items ?? 0;
          setRecentICPs(iData.items || []);
        }

        if (marketsRes.status === 'fulfilled' && marketsRes.value.ok) {
          const mData = await marketsRes.value.json();
          totalTargetMarkets = mData.total_items ?? 0;
        }

        setStats({
          totalProspects,
          totalCampaigns,
          totalICPs,
          totalTargetMarkets,
          loading: false,
        });
      } catch {
        setStats({
          totalProspects: 0,
          totalCampaigns: 0,
          totalICPs: 0,
          totalTargetMarkets: 0,
          loading: false,
        });
      }
    }

    loadTruthfulDashboardData();
  }, [activeOrg]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            {t('dashboard.title')}
          </h1>
          <p className="text-xs text-foreground-muted">
            {t('dashboard.subtitle')} • <span className="font-semibold text-foreground">{activeOrg?.name}</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href={`/${locale}/prospects`}>
            <Button size="sm" variant="secondary">
              <Users className="w-3.5 h-3.5 mr-1.5 text-foreground-muted" />
              {t('nav.prospects')}
            </Button>
          </Link>
          <PermissionGate permission="campaign.create">
            <Link href={`/${locale}/campaigns`}>
              <Button size="sm">
                <Megaphone className="w-3.5 h-3.5 mr-1.5 text-brand-gold" />
                {t('campaigns.create_button')}
              </Button>
            </Link>
          </PermissionGate>
        </div>
      </div>

      {/* Truthful Metrics Grid (Backed 100% by P19 endpoints) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-foreground-muted">
              {t('dashboard.metrics.total_prospects')}
            </CardTitle>
            <div className="w-7 h-7 rounded-md bg-brand-dark/5 flex items-center justify-center">
              <Users className="w-4 h-4 text-brand-dark" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-extrabold text-foreground">
              {stats.loading ? '—' : stats.totalProspects?.toLocaleString()}
            </div>
            <p className="text-[11px] text-foreground-muted mt-1">
              Live tenant prospect directory
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-foreground-muted">
              {t('dashboard.metrics.total_campaigns')}
            </CardTitle>
            <div className="w-7 h-7 rounded-md bg-brand-gold/10 flex items-center justify-center">
              <Megaphone className="w-4 h-4 text-brand-gold" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-extrabold text-foreground">
              {stats.loading ? '—' : stats.totalCampaigns}
            </div>
            <p className="text-[11px] text-foreground-muted mt-1">
              Configured outbound cadences
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-foreground-muted">
              {t('nav.icps')}
            </CardTitle>
            <div className="w-7 h-7 rounded-md bg-brand-dark/5 flex items-center justify-center">
              <Target className="w-4 h-4 text-brand-dark" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-extrabold text-foreground">
              {stats.loading ? '—' : stats.totalICPs}
            </div>
            <p className="text-[11px] text-foreground-muted mt-1">
              Defined scoring profiles
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-2">
            <CardTitle className="text-xs font-semibold text-foreground-muted">
              {t('nav.target_markets')}
            </CardTitle>
            <div className="w-7 h-7 rounded-md bg-brand-dark/5 flex items-center justify-center">
              <Globe2 className="w-4 h-4 text-brand-dark" />
            </div>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-extrabold text-foreground">
              {stats.loading ? '—' : stats.totalTargetMarkets}
            </div>
            <p className="text-[11px] text-foreground-muted mt-1">
              Mapped target territories
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Activity & System Status */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>{t('dashboard.recent_activity')}</CardTitle>
            <CardDescription>
              Real-time events emitted by the continuous execution engine
            </CardDescription>
          </CardHeader>
          <CardContent>
            {/* Truthful state: No fake events rendered */}
            <EmptyState
              title="No recent activity recorded"
              description="Real-time activity logs will stream here as outbound cadences and discovery runs are executed."
              icon={<Inbox className="w-6 h-6 text-foreground-muted" />}
              className="my-2"
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t('dashboard.top_icps')}</CardTitle>
            <CardDescription>Configured ICP profiles</CardDescription>
          </CardHeader>
          <CardContent>
            {recentICPs.length === 0 && !stats.loading ? (
              <EmptyState
                title={t('icps.empty')}
                description="No ICP profiles configured for this organization yet."
                className="my-1 py-4"
              />
            ) : (
              <div className="space-y-2">
                {recentICPs.map((icp) => (
                  <div key={icp.id} className="p-3 rounded-lg border border-border bg-surface-subtle/40 space-y-1">
                    <p className="font-semibold text-foreground text-xs">{icp.name}</p>
                    <p className="text-[11px] text-foreground-muted">
                      {icp.industries && icp.industries.length > 0 ? icp.industries.join(', ') : 'General Industry'}
                    </p>
                  </div>
                ))}
                <div className="pt-2">
                  <Link href={`/${locale}/icps`} className="text-xs font-semibold text-brand-gold hover:text-brand-gold-hover flex items-center gap-1">
                    <span>View all ICP profiles</span>
                    <ArrowUpRight className="w-3.5 h-3.5" />
                  </Link>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
