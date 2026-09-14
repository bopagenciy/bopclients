'use client';

import React, { useEffect, useState } from 'react';
import { useI18n } from '@/lib/i18n/context';
import { useAuth } from '@/lib/auth/context';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { EmptyState } from '@/components/states/EmptyState';
import { PermissionGate } from '@/components/navigation/PermissionGate';
import { Compass, Info, Sparkles } from 'lucide-react';

interface ResearchRunItem {
  id: string;
  prospect_id?: string;
  campaign_id?: string;
  run_type?: string;
  status: string;
  started_at?: string;
  created_at: string;
}

export default function ResearchPage() {
  const { t } = useI18n();
  const { activeOrg } = useAuth();
  const [query, setQuery] = useState('');
  const [runs, setRuns] = useState<ResearchRunItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadResearchRuns() {
      setLoading(true);
      try {
        const res = await fetch('/api/proxy/api/v1/research-runs?page=1&page_size=10', {
          credentials: 'include',
        });
        if (res.ok) {
          const data = await res.json();
          setRuns(data.items || []);
        } else {
          setRuns([]);
        }
      } catch {
        setRuns([]);
      } finally {
        setLoading(false);
      }
    }

    loadResearchRuns();
  }, [activeOrg]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          {t('research.title')}
        </h1>
        <p className="text-xs text-foreground-muted">
          {t('research.subtitle')}
        </p>
      </div>

      {/* Strict Semantic Boundary Notice (Fully Translated via i18n Catalogs) */}
      <div className="flex items-start gap-3 p-4 rounded-lg bg-brand-gold/10 border border-brand-gold/40 text-xs">
        <Info className="w-4 h-4 text-brand-gold shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="font-semibold text-foreground">
            {t('research.notice')}
          </p>
          <p className="text-foreground-muted">
            {t('research.boundary_info')}
          </p>
        </div>
      </div>

      {/* Research Query Console */}
      <Card>
        <CardHeader>
          <CardTitle>Autonomous Entity Discovery</CardTitle>
          <CardDescription>
            Input an enterprise domain or business entity name to trigger deep-web signal harvesting.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col sm:flex-row gap-3">
            <Input
              placeholder="e.g. domain.com or Corporate Entity Name"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="flex-1"
            />
            <PermissionGate permission="research.run">
              <Button size="md" className="sm:w-auto">
                <Sparkles className="w-4 h-4 mr-1.5 text-brand-gold" />
                Launch Pipeline
              </Button>
            </PermissionGate>
          </div>
        </CardContent>
      </Card>

      {/* Real Intelligence Operations (NO hardcoded fake companies) */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold text-foreground">Recent Discovery Executions</h3>
        {runs.length === 0 && !loading ? (
          <EmptyState
            title={t('research.empty')}
            description="Discovery runs triggered against target prospects will appear here."
            icon={<Compass className="w-6 h-6 text-brand-gold" />}
          />
        ) : (
          <div className="space-y-2">
            {runs.map((run) => (
              <div
                key={run.id}
                className="flex items-center justify-between p-3.5 rounded-lg border border-border bg-surface shadow-xs"
              >
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-md bg-brand-dark/5 flex items-center justify-center">
                    <Compass className="w-4 h-4 text-brand-gold" />
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-foreground font-mono">
                      Run ID: {run.id.slice(0, 8)}...
                    </p>
                    <p className="text-[11px] text-foreground-muted">
                      Type: {run.run_type || 'standard_discovery'}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Badge size="sm" variant={run.status === 'completed' ? 'success' : 'info'}>
                    {run.status}
                  </Badge>
                  <span className="text-[11px] text-foreground-muted font-mono">
                    {new Date(run.created_at).toLocaleTimeString()}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
