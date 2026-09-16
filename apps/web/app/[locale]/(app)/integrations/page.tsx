'use client';

import React, { useEffect, useState } from 'react';
import { useI18n } from '@/lib/i18n/context';
import { useAuth } from '@/lib/auth/context';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/states/EmptyState';
import { PermissionGate } from '@/components/navigation/PermissionGate';
import { hasPermission } from '@/lib/permissions';
import { Boxes, Plus, Lock, Webhook, Share2 } from 'lucide-react';

interface DestinationItem {
  id: string;
  destination_name: string;
  target_app_id?: string;
  transport_type: string;
  endpoint_url?: string;
  secret_key_ref?: string;
  is_active: boolean;
}

export default function IntegrationsPage() {
  const { t } = useI18n();
  const { activeOrg, activeRole } = useAuth();
  const [destinations, setDestinations] = useState<DestinationItem[]>([]);
  const [loading, setLoading] = useState(true);

  const canManage = hasPermission(activeRole, 'integration.manage');

  useEffect(() => {
    async function loadDestinations() {
      setLoading(true);
      try {
        const res = await fetch('/api/proxy/api/v1/integrations/destinations', { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          setDestinations(data.items || []);
        } else {
          setDestinations([]);
        }
      } catch {
        setDestinations([]);
      } finally {
        setLoading(false);
      }
    }
    loadDestinations();
  }, [activeOrg]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground">
            {t('integrations.title')}
          </h1>
          <p className="text-xs text-foreground-muted">
            {t('integrations.subtitle')}
          </p>
        </div>

        <PermissionGate
          permission="integration.manage"
          fallback={
            <Button size="sm" variant="outline" disabled title={t('integrations.restricted_notice')}>
              <Lock className="w-3.5 h-3.5 mr-1.5 text-foreground-muted" />
              {t('integrations.add_destination')}
            </Button>
          }
        >
          <Button size="sm">
            <Plus className="w-4 h-4 mr-1.5" />
            {t('integrations.add_destination')}
          </Button>
        </PermissionGate>
      </div>

      {!canManage && (
        <div className="flex items-center gap-2 p-3 rounded-lg bg-surface-subtle border border-border text-xs text-foreground-muted">
          <Lock className="w-4 h-4 text-brand-gold shrink-0" />
          <span>{t('integrations.restricted_notice')}</span>
        </div>
      )}

      {/* Bop CRM Integration Status Card */}
      {(() => {
        const hasCrmConfigured = destinations.some(
          (d) => d.is_active && (d.target_app_id === 'bopcrm' || d.destination_name.toLowerCase().includes('crm'))
        );
        return (
          <div className="p-4 rounded-lg border border-border bg-surface flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-lg bg-brand-gold/10 flex items-center justify-center shrink-0 mt-0.5">
                <Share2 className="w-5 h-5 text-brand-gold" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-foreground">Bop CRM Integration (Cross-App Handoff)</h2>
                <p className="text-xs text-foreground-muted mt-0.5">
                  {hasCrmConfigured
                    ? 'Active destination configured for prospect.ready_for_crm. Sales reps can hand off dossiers directly from prospect detail pages.'
                    : 'No active destination configured for prospect.ready_for_crm. Configure an active destination below to enable dossier handoff.'}
                </p>
              </div>
            </div>
            <Badge size="sm" variant={hasCrmConfigured ? 'success' : 'default'} className="self-start sm:self-center">
              {hasCrmConfigured ? 'Configured' : 'Not Configured'}
            </Badge>
          </div>
        );
      })()}

      {/* Real Destination Grid (NO hardcoded fake destinations) */}
      {destinations.length === 0 && !loading ? (
        <EmptyState
          title={t('integrations.empty')}
          description="Configure external destinations to deliver qualified prospect events via webhook or cloud connectors."
          icon={<Boxes className="w-6 h-6 text-brand-gold" />}
        />
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {destinations.map((dest) => (
            <Card key={dest.id} className="hover:border-border transition-colors">
              <CardHeader className="flex flex-row items-start justify-between pb-2">
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-lg bg-brand-dark/5 flex items-center justify-center">
                    <Webhook className="w-4 h-4 text-brand-gold" />
                  </div>
                  <div>
                    <CardTitle className="text-sm">{dest.destination_name}</CardTitle>
                    <p className="text-[11px] text-foreground-muted font-mono">{dest.transport_type}</p>
                  </div>
                </div>
                <Badge size="sm" variant={dest.is_active ? 'success' : 'default'}>
                  {dest.is_active ? 'Active' : 'Inactive'}
                </Badge>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-foreground-muted truncate">
                  Endpoint: <span className="font-mono text-[11px] text-foreground">{dest.endpoint_url || '—'}</span>
                </p>
                {dest.secret_key_ref && (
                  <div className="mt-4 pt-3 border-t border-border/60 flex items-center justify-between text-xs">
                    <span className="text-foreground-muted">Credential Key Ref</span>
                    <span className="font-mono text-[10px] bg-surface-subtle px-1.5 py-0.5 rounded">
                      {dest.secret_key_ref}
                    </span>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
