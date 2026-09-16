'use client';

import React, { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { useI18n } from '@/lib/i18n/context';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { ErrorState } from '@/components/states/ErrorState';
import { PermissionGate } from '@/components/navigation/PermissionGate';
import {
  Users,
  ArrowLeft,
  Building,
  Globe,
  Mail,
  Phone,
  Compass,
  FileText,
  Activity,
  Award,
  Flame,
  CheckCircle2,
  ExternalLink,
  HelpCircle,
  RefreshCw,
  Send,
  AlertCircle,
} from 'lucide-react';
import {
  ProspectDetail,
  Signal,
  LeadScoreDetail,
  PriorityDetail,
  CrmHandoffStatusResponse,
} from '@/lib/api/types';

export default function ProspectDetailPage() {
  const { t, locale } = useI18n();
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const prospectId = params?.prospectId as string;
  const returnTo = searchParams.get('return_to');

  const [dossier, setDossier] = useState<ProspectDetail | null>(null);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [leadScore, setLeadScore] = useState<LeadScoreDetail | null>(null);
  const [priority, setPriority] = useState<PriorityDetail | null>(null);
  const [crmStatus, setCrmStatus] = useState<CrmHandoffStatusResponse | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Action loading states
  const [scoring, setScoring] = useState(false);
  const [prioritizing, setPrioritizing] = useState(false);
  const [researching, setResearching] = useState(false);
  const [sendingToCrm, setSendingToCrm] = useState(false);
  const [crmError, setCrmError] = useState<string | null>(null);
  const [actionSuccess, setActionSuccess] = useState<string | null>(null);
  const [selectedCampaignId, setSelectedCampaignId] = useState<string>('');

  const fetchProspectData = useCallback(async () => {
    if (!prospectId) return;
    setLoading(true);
    setError(null);

    try {
      // 1. Fetch Prospect core record
      const res = await fetch(`/api/proxy/api/v1/prospects/${prospectId}`, {
        credentials: 'include',
      });
      if (!res.ok) {
        throw new Error(`Prospect not found (Status ${res.status})`);
      }
      const data: ProspectDetail = await res.json();
      setDossier(data);

      // 2. Parallel fetch of signals, score, priority, and CRM handoff status
      const [resSignals, resScore, resPriority, resCrm] = await Promise.all([
        fetch(`/api/proxy/api/v1/prospects/${prospectId}/signals`, { credentials: 'include' }),
        fetch(`/api/proxy/api/v1/prospects/${prospectId}/score`, { credentials: 'include' }),
        fetch(`/api/proxy/api/v1/prospects/${prospectId}/priority`, { credentials: 'include' }),
        fetch(`/api/proxy/api/v1/prospects/${prospectId}/crm-handoff`, { credentials: 'include' }),
      ]);

      if (resSignals.ok) {
        const sigData = await resSignals.json();
        setSignals(Array.isArray(sigData) ? sigData : sigData.items || []);
      }
      if (resScore.ok) {
        const scData = await resScore.json();
        setLeadScore(scData);
      }
      if (resPriority.ok) {
        const priData = await resPriority.json();
        setPriority(priData);
      }
      if (resCrm.ok) {
        const crmData = await resCrm.json();
        setCrmStatus(crmData);
      }
    } catch (err: any) {
      setError(err.message || 'Error loading prospect dossier');
    } finally {
      setLoading(false);
    }
  }, [prospectId]);

  useEffect(() => {
    fetchProspectData();
  }, [fetchProspectData]);

  // Recalculate Score
  const handleRecalculateScore = async () => {
    setScoring(true);
    setActionSuccess(null);
    try {
      const res = await fetch(`/api/proxy/api/v1/prospects/${prospectId}/score/recalculate`, {
        method: 'POST',
        credentials: 'include',
      });
      if (res.ok) {
        const data = await res.json();
        setLeadScore(data);
        setActionSuccess(t('prospect_detail.score_recalculated'));
      }
    } catch {
      // Handled silently
    } finally {
      setScoring(false);
    }
  };

  // Recalculate Priority
  const handleRecalculatePriority = async () => {
    setPrioritizing(true);
    setActionSuccess(null);
    try {
      const res = await fetch(`/api/proxy/api/v1/prospects/${prospectId}/priority/recalculate`, {
        method: 'POST',
        credentials: 'include',
      });
      if (res.ok) {
        const data = await res.json();
        setPriority(data);
        setActionSuccess(t('prospect_detail.priority_recalculated'));
      }
    } catch {
      // Handled silently
    } finally {
      setPrioritizing(false);
    }
  };

  // Trigger Research
  const handleTriggerResearch = async () => {
    setResearching(true);
    setActionSuccess(null);
    try {
      const activeCampaignId =
        selectedCampaignId ||
        (dossier?.campaign_associations?.length === 1
          ? dossier.campaign_associations[0].campaign_id
          : undefined);

      const payload: { campaign_id?: string; run_type: string } = {
        run_type: 'full_diligence',
      };
      if (activeCampaignId) {
        payload.campaign_id = activeCampaignId;
      }

      const res = await fetch(`/api/proxy/api/v1/prospects/${prospectId}/research`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        credentials: 'include',
      });
      if (res.ok) {
        setActionSuccess(t('prospect_detail.research_triggered'));
      }
    } catch {
      // Handled silently
    } finally {
      setResearching(false);
    }
  };

  // Send to Bop CRM
  const handleSendToCrm = async () => {
    if (!prospectId) return;
    setSendingToCrm(true);
    setCrmError(null);
    try {
      const res = await fetch(`/api/proxy/api/v1/prospects/${prospectId}/crm-handoff`, {
        method: 'POST',
        credentials: 'include',
      });
      if (res.ok) {
        const data = await res.json();
        setActionSuccess(data.is_idempotent_replay ? t('prospect_detail.crm_already_sent') : t('prospect_detail.crm_handoff_success'));
        const sRes = await fetch(`/api/proxy/api/v1/prospects/${prospectId}/crm-handoff`, { credentials: 'include' });
        if (sRes.ok) {
          setCrmStatus(await sRes.json());
        }
      } else {
        const errData = await res.json().catch(() => ({}));
        const msg = errData?.error?.message || (res.status === 409 ? t('prospect_detail.crm_destination_not_configured') : t('prospect_detail.crm_handoff_failed'));
        setCrmError(msg);
      }
    } catch (err: any) {
      setCrmError(err.message || t('prospect_detail.crm_handoff_failed'));
    } finally {
      setSendingToCrm(false);
    }
  };

  if (loading && !dossier) {
    return (
      <div className="flex items-center justify-center p-12">
        <div className="animate-spin h-8 w-8 border-2 border-brand-gold border-t-transparent rounded-full" />
      </div>
    );
  }

  if (error || !dossier) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" onClick={() => router.push(`/${locale}/prospects`)}>
          <ArrowLeft className="w-4 h-4 mr-1.5" />
          {t('prospect_detail.back_to_prospects')}
        </Button>
        <ErrorState message={error || 'Prospect not found'} onRetry={fetchProspectData} />
      </div>
    );
  }

  const prospect = dossier.prospect;
  const locationStr = [prospect?.city, prospect?.state, prospect?.country].filter(Boolean).join(', ');

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Top Breadcrumb & Action Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              if (returnTo) {
                router.push(returnTo);
              } else {
                router.push(`/${locale}/prospects`);
              }
            }}
            className="-ml-2 text-foreground-muted hover:text-foreground mb-1"
          >
            <ArrowLeft className="w-4 h-4 mr-1.5" />
            {t('prospect_detail.back_to_prospects')}
          </Button>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">
              {prospect?.name}
            </h1>
            {prospect?.industry && (
              <Badge size="sm" variant="default">
                {prospect.industry}
              </Badge>
            )}
          </div>
          <p className="text-xs text-foreground-muted mt-0.5">
            {t('prospect_detail.subtitle')}
          </p>
        </div>

        <div className="flex items-center gap-2">
          {dossier?.campaign_associations && dossier.campaign_associations.length > 1 && (
            <div className="flex items-center gap-1.5 text-xs">
              <label htmlFor="campaign-context-select" className="text-foreground-muted hidden sm:inline">
                {t('prospect_detail.research_campaign_select')}
              </label>
              <select
                id="campaign-context-select"
                value={selectedCampaignId}
                onChange={(e) => setSelectedCampaignId(e.target.value)}
                className="bg-surface border border-border text-foreground text-xs rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-brand-gold"
              >
                <option value="">{t('prospect_detail.research_campaign_none')}</option>
                {dossier.campaign_associations.map((ca) => (
                  <option key={ca.campaign_id} value={ca.campaign_id}>
                    {ca.campaign_name || ca.campaign_id.slice(0, 12)}
                  </option>
                ))}
              </select>
            </div>
          )}
          {dossier?.campaign_associations && dossier.campaign_associations.length === 1 && (
            <div className="flex items-center gap-1 text-xs text-foreground-muted bg-surface-subtle border border-border px-2.5 py-1 rounded">
              <span className="text-foreground-muted">Campaign:</span>
              <span className="font-semibold text-foreground">
                {dossier.campaign_associations[0].campaign_name || dossier.campaign_associations[0].campaign_id.slice(0, 12)}
              </span>
            </div>
          )}
          <PermissionGate permission="research.run">
            <Button
              size="sm"
              variant="outline"
              onClick={handleTriggerResearch}
              disabled={researching}
            >
              <Compass className="w-3.5 h-3.5 mr-1.5 text-brand-gold" />
              {researching ? t('prospect_detail.researching') : t('prospect_detail.research_button')}
            </Button>
          </PermissionGate>

          {/* BOP CRM Handoff Action & Status */}
          <div className="flex items-center gap-2">
            {crmStatus && crmStatus.status !== 'NOT_SENT' && (
              <Badge
                size="sm"
                variant={
                  crmStatus.status === 'DELIVERED'
                    ? 'success'
                    : crmStatus.status === 'FAILED'
                    ? 'danger'
                    : 'warning'
                }
                className="flex items-center gap-1.5 py-1 px-2.5"
              >
                {crmStatus.status === 'DELIVERED' && <CheckCircle2 className="w-3 h-3 text-success" />}
                {crmStatus.status === 'QUEUED' && <RefreshCw className="w-3 h-3 animate-spin text-warning" />}
                {crmStatus.status === 'DELIVERING' && <RefreshCw className="w-3 h-3 animate-spin text-warning" />}
                {crmStatus.status === 'FAILED' && <AlertCircle className="w-3 h-3 text-danger" />}
                <span>
                  {crmStatus.status === 'DELIVERED' && t('prospect_detail.crm_status_delivered')}
                  {crmStatus.status === 'QUEUED' && t('prospect_detail.crm_status_queued')}
                  {crmStatus.status === 'DELIVERING' && t('prospect_detail.crm_status_delivering')}
                  {crmStatus.status === 'FAILED' && t('prospect_detail.crm_status_failed')}
                </span>
              </Badge>
            )}

            <PermissionGate permission="prospect.update">
              {(!crmStatus || crmStatus.status === 'NOT_SENT' || crmStatus.status === 'FAILED') && (
                <Button
                  size="sm"
                  variant="primary"
                  onClick={handleSendToCrm}
                  disabled={sendingToCrm}
                >
                  <Send className="w-3.5 h-3.5 mr-1.5" />
                  {sendingToCrm
                    ? t('prospect_detail.sending_to_crm')
                    : crmStatus?.status === 'FAILED'
                    ? t('prospect_detail.crm_retry_button')
                    : t('prospect_detail.send_to_crm')}
                </Button>
              )}
            </PermissionGate>
          </div>
        </div>
      </div>

      {actionSuccess && (
        <div className="p-3 bg-success/10 border border-success/30 rounded-md text-xs text-success flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 shrink-0" />
          <span>{actionSuccess}</span>
        </div>
      )}

      {crmError && (
        <div className="p-3 bg-danger/10 border border-danger/30 rounded-md text-xs text-danger flex items-start gap-2">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="font-semibold">{crmError}</p>
            {crmError.toLowerCase().includes('destination') && (
              <Link
                href={`/${locale}/integrations`}
                className="underline font-medium hover:text-danger-hover mt-1 inline-block"
              >
                Go to Integrations settings &rarr;
              </Link>
            )}
          </div>
        </div>
      )}

      {/* Two-Column Grid: Left (Dossier & Signals), Right (Scores & Intelligence) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column (2 cols wide) */}
        <div className="lg:col-span-2 space-y-6">
          {/* Overview Card */}
          <div className="p-5 rounded-lg border border-border bg-surface space-y-4">
            <h2 className="text-sm font-bold text-foreground flex items-center gap-2">
              <Building className="w-4 h-4 text-brand-gold" />
              {t('prospect_detail.company_info')}
            </h2>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              <div>
                <p className="text-foreground-muted font-medium mb-0.5">{t('prospect_detail.website')}</p>
                {prospect?.website_url ? (
                  <a
                    href={prospect.website_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-brand-gold hover:underline flex items-center gap-1 font-mono"
                  >
                    <span>{prospect.website_url}</span>
                    <ExternalLink className="w-3 h-3" />
                  </a>
                ) : (
                  <span className="text-foreground-muted">—</span>
                )}
              </div>

              <div>
                <p className="text-foreground-muted font-medium mb-0.5">{t('prospect_detail.address')}</p>
                <span className="text-foreground">{locationStr || '—'}</span>
              </div>

              <div>
                <p className="text-foreground-muted font-medium mb-0.5">{t('prospect_detail.phone')}</p>
                <span className="text-foreground font-mono">{prospect?.phone || '—'}</span>
              </div>

              <div>
                <p className="text-foreground-muted font-medium mb-0.5">{t('prospect_detail.email')}</p>
                <span className="text-foreground font-mono">{prospect?.email || '—'}</span>
              </div>
            </div>
          </div>

          {/* Provenance Card */}
          <div className="p-5 rounded-lg border border-border bg-surface space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-bold text-foreground flex items-center gap-2">
                  <FileText className="w-4 h-4 text-brand-gold" />
                  {t('prospect_detail.provenance_title')}
                </h2>
                <p className="text-xs text-foreground-muted mt-0.5">
                  {t('prospect_detail.provenance_desc')}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs pt-1">
              <div className="p-3 bg-surface-subtle rounded-md">
                <p className="text-foreground-muted font-medium mb-1">{t('prospect_detail.source_type')}</p>
                <Badge size="sm" variant="outline">
                  {prospect?.source || 'forge'}
                </Badge>
              </div>

              <div className="p-3 bg-surface-subtle rounded-md">
                <p className="text-foreground-muted font-medium mb-1">{t('prospect_detail.created_at')}</p>
                <span className="font-mono text-foreground">
                  {prospect?.created_at ? new Date(prospect.created_at).toLocaleDateString() : '—'}
                </span>
              </div>

              <div className="p-3 bg-surface-subtle rounded-md">
                <p className="text-foreground-muted font-medium mb-1">{t('prospect_detail.external_id')}</p>
                <span className="font-mono text-foreground truncate block" title={prospect?.id}>
                  {prospect?.id ? `${prospect.id.slice(0, 13)}...` : '—'}
                </span>
              </div>
            </div>
          </div>

          {/* Signals Card */}
          <div className="p-5 rounded-lg border border-border bg-surface space-y-3">
            <div>
              <h2 className="text-sm font-bold text-foreground flex items-center gap-2">
                <Activity className="w-4 h-4 text-brand-gold" />
                {t('prospect_detail.signals_title')} ({signals.length})
              </h2>
              <p className="text-xs text-foreground-muted mt-0.5">
                {t('prospect_detail.signals_desc')}
              </p>
            </div>

            {signals.length === 0 ? (
              <p className="text-xs text-foreground-muted py-3">
                {t('prospects.detail.no_signals')}
              </p>
            ) : (
              <div className="space-y-2.5 pt-1">
                {signals.map((sig) => (
                  <div
                    key={sig.id}
                    className="p-3 bg-surface-subtle rounded-md border border-border/60 space-y-1 text-xs"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <Badge size="sm" variant="default">
                          {sig.category}
                        </Badge>
                        <span className="font-semibold text-foreground">{sig.headline}</span>
                      </div>
                      <span className="text-[11px] font-mono text-brand-gold shrink-0">
                        {Math.round((sig.confidence || 0) * 100)}% {t('prospect_detail.confidence')}
                      </span>
                    </div>

                    {sig.summary && (
                      <p className="text-foreground-muted text-[11px]">{sig.summary}</p>
                    )}

                    <div className="flex items-center justify-between text-[11px] text-foreground-muted pt-1">
                      <span>
                        {t('prospect_detail.detected')}: {new Date(sig.detected_at).toLocaleDateString()}
                      </span>
                      {sig.source_url && (
                        <a
                          href={sig.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:text-brand-gold flex items-center gap-1"
                        >
                          Source <ExternalLink className="w-2.5 h-2.5" />
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Scoring, Urgency & Intelligence */}
        <div className="space-y-6">
          {/* Lead Qualification Score Card */}
          <div className="p-5 rounded-lg border border-border bg-surface space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <Award className="w-4 h-4 text-brand-gold" />
                <h3 className="text-sm font-bold text-foreground">
                  {t('prospect_detail.lead_score_title')}
                </h3>
              </div>
              <div
                className="group relative cursor-help text-foreground-muted hover:text-foreground"
                title={t('prospect_detail.lead_score_tooltip')}
              >
                <HelpCircle className="w-3.5 h-3.5" />
              </div>
            </div>

            <p className="text-xs text-foreground-muted">
              {t('prospect_detail.lead_score_desc')}
            </p>

            <div className="flex items-baseline gap-2 py-2">
              <span className="text-4xl font-extrabold text-foreground">
                {leadScore?.score !== null && leadScore?.score !== undefined
                  ? Math.round(leadScore.score)
                  : '—'}
              </span>
              <span className="text-xs text-foreground-muted font-medium">/ 100</span>
            </div>

            {leadScore?.explanation && (
              <p className="text-xs text-foreground-muted p-2.5 bg-surface-subtle rounded-md border border-border/60">
                {leadScore.explanation}
              </p>
            )}

            <PermissionGate permission="prospect.update">
              <Button
                size="sm"
                variant="outline"
                className="w-full"
                onClick={handleRecalculateScore}
                disabled={scoring}
              >
                <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${scoring ? 'animate-spin' : ''}`} />
                {scoring ? t('prospect_detail.recalculating') : t('prospect_detail.recalculate_score')}
              </Button>
            </PermissionGate>
          </div>

          {/* Outreach Priority Card */}
          <div className="p-5 rounded-lg border border-border bg-surface space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <Flame className="w-4 h-4 text-brand-gold" />
                <h3 className="text-sm font-bold text-foreground">
                  {t('prospect_detail.priority_title')}
                </h3>
              </div>
              <div
                className="group relative cursor-help text-foreground-muted hover:text-foreground"
                title={t('prospect_detail.priority_tooltip')}
              >
                <HelpCircle className="w-3.5 h-3.5" />
              </div>
            </div>

            <p className="text-xs text-foreground-muted">
              {t('prospect_detail.priority_desc')}
            </p>

            <div className="flex items-center gap-3 py-1">
              <Badge
                size="sm"
                variant={
                  priority?.tier === 'urgent'
                    ? 'danger'
                    : priority?.tier === 'high'
                    ? 'warning'
                    : priority?.tier === 'medium'
                    ? 'info'
                    : 'default'
                }
              >
                {(priority?.tier ? t(`priority.${priority.tier.toLowerCase()}`) : 'NORMAL').toUpperCase()}
              </Badge>
              {priority?.score !== undefined && priority?.score !== null && (
                <span className="text-xs font-mono text-foreground-muted">
                  Score: {Math.round(priority.score)}
                </span>
              )}
            </div>

            {priority?.reasons && priority.reasons.length > 0 && (
              <div className="space-y-1">
                <p className="text-[11px] font-semibold text-foreground-muted">Scoring Factors:</p>
                <ul className="list-disc list-inside text-xs text-foreground space-y-0.5">
                  {priority.reasons.map((r, idx) => (
                    <li key={idx}>{r}</li>
                  ))}
                </ul>
              </div>
            )}

            <PermissionGate permission="prospect.update">
              <Button
                size="sm"
                variant="outline"
                className="w-full"
                onClick={handleRecalculatePriority}
                disabled={prioritizing}
              >
                <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${prioritizing ? 'animate-spin' : ''}`} />
                {prioritizing ? t('prospect_detail.recalculating') : t('prospect_detail.recalculate_priority')}
              </Button>
            </PermissionGate>
          </div>

          {/* Intelligence Classification Card (Observed / Derived / Inferred) */}
          <div className="p-5 rounded-lg border border-border bg-surface space-y-3">
            <h3 className="text-sm font-bold text-foreground flex items-center gap-2">
              <Activity className="w-4 h-4 text-brand-gold" />
              {t('prospect_detail.intelligence_title')}
            </h3>
            <p className="text-xs text-foreground-muted">
              {t('prospect_detail.intelligence_desc')}
            </p>

            <div className="space-y-2 pt-1 text-xs">
              <div className="p-2.5 bg-surface-subtle rounded-md">
                <span className="font-semibold text-foreground block mb-0.5">
                  {t('prospect_detail.evidence_observed')}
                </span>
                <p className="text-foreground-muted text-[11px]">
                  Direct entity registrations, verified addresses, and operational domains.
                </p>
              </div>

              <div className="p-2.5 bg-surface-subtle rounded-md">
                <span className="font-semibold text-foreground block mb-0.5">
                  {t('prospect_detail.evidence_derived')}
                </span>
                <p className="text-foreground-muted text-[11px]">
                  Estimated employee headcount, geographic radius alignment, and ICP match index.
                </p>
              </div>

              <div className="p-2.5 bg-surface-subtle rounded-md">
                <span className="font-semibold text-foreground block mb-0.5">
                  {t('prospect_detail.evidence_inferred')}
                </span>
                <p className="text-foreground-muted text-[11px]">
                  Buying trigger likelihood and operational urgency based on signal frequency.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
