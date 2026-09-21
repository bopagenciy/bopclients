'use client';

import React, { useEffect, useState, useCallback, useRef } from 'react';
import Link from 'next/link';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { useI18n } from '@/lib/i18n/context';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { ErrorState } from '@/components/states/ErrorState';
import { EmptyState } from '@/components/states/EmptyState';
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
  Sparkles,
  Shield,
  Clock,
  AlertTriangle,
  Info,
} from 'lucide-react';
import {
  ProspectDetail,
  Signal,
  LeadScoreDetail,
  PriorityDetail,
  CrmHandoffStatusResponse,
  ResearchRun,
  ProspectIntelligenceData,
  ProspectIntelligenceResponse,
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

  // P30 Research States
  const [intelligence, setIntelligence] = useState<ProspectIntelligenceData | null>(null);
  const [intelMeta, setIntelMeta] = useState<{
    confidence?: number | null;
    research_version?: string | null;
  } | null>(null);
  const [activeRun, setActiveRun] = useState<ResearchRun | null>(null);
  const [researchRuns, setResearchRuns] = useState<ResearchRun[]>([]);
  const [pollingTimeoutNotice, setPollingTimeoutNotice] = useState(false);
  const [researchError, setResearchError] = useState<string | null>(null);
  const pollCountRef = useRef(0);

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

  const fetchIntelligence = useCallback(async () => {
    if (!prospectId) return;
    try {
      const res = await fetch(`/api/proxy/api/v1/prospects/${prospectId}/intelligence`, {
        credentials: 'include',
      });
      if (res.ok) {
        const data: ProspectIntelligenceResponse = await res.json();
        setIntelligence(data.intelligence || null);
        setIntelMeta({
          confidence: data.confidence,
          research_version: data.research_version,
        });
      }
    } catch {
      // Handled silently
    }
  }, [prospectId]);

  const fetchResearchRuns = useCallback(async () => {
    if (!prospectId) return;
    try {
      const res = await fetch(`/api/proxy/api/v1/research-runs?prospect_id=${prospectId}&page=1&page_size=5`, {
        credentials: 'include',
      });
      if (res.ok) {
        const data = await res.json();
        const items: ResearchRun[] = data.items || [];
        setResearchRuns(items);
        if (items.length > 0) {
          const latest = items[0];
          if (latest.status === 'pending' || latest.status === 'running') {
            setActiveRun((prev) => {
              if (prev && (prev.status === 'completed' || prev.status === 'failed')) {
                return prev;
              }
              return latest;
            });
          }
        }
      }
    } catch {
      // Handled silently
    }
  }, [prospectId]);

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

      // 2. Parallel fetch of signals, score, priority, CRM status, intelligence, and runs
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

      await Promise.all([fetchIntelligence(), fetchResearchRuns()]);
    } catch (err: any) {
      setError(err.message || 'Error loading prospect dossier');
    } finally {
      setLoading(false);
    }
  }, [prospectId, fetchIntelligence, fetchResearchRuns]);

  useEffect(() => {
    fetchProspectData();
  }, [fetchProspectData]);

  const activeRunId = activeRun?.id;
  const activeRunStatus = activeRun?.status;

  // Polling Effect for In-Flight Research Runs
  useEffect(() => {
    if (!activeRunId || (activeRunStatus !== 'pending' && activeRunStatus !== 'running')) {
      return;
    }

    let isMounted = true;
    pollCountRef.current = 0;

    const intervalId = setInterval(async () => {
      pollCountRef.current += 1;
      if (pollCountRef.current > 60) {
        clearInterval(intervalId);
        if (isMounted) {
          setPollingTimeoutNotice(true);
          setResearching(false);
        }
        return;
      }

      try {
        const res = await fetch(`/api/proxy/api/v1/research-runs/${activeRunId}`, {
          credentials: 'include',
        });
        if (!res.ok) return;
        const updatedRun: ResearchRun = await res.json();

        if (!isMounted) return;

        if (updatedRun.status !== activeRunStatus) {
          setActiveRun(updatedRun);
        }

        if (updatedRun.status === 'completed') {
          clearInterval(intervalId);
          setResearching(false);
          setActionSuccess(t('prospect_detail.research_completed'));
          await fetchIntelligence();
          await fetchResearchRuns();
          await fetchProspectData();
        } else if (updatedRun.status === 'failed') {
          clearInterval(intervalId);
          setResearching(false);
          setResearchError(updatedRun.error_message || t('prospect_detail.research_failed_msg'));
          await fetchResearchRuns();
        }
      } catch {
        // Tolerates temporary network errors, continuing until max iterations
      }
    }, 2000);

    return () => {
      isMounted = false;
      clearInterval(intervalId);
    };
  }, [activeRunId, activeRunStatus, fetchIntelligence, fetchResearchRuns, fetchProspectData, t]);

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
    setResearchError(null);
    setPollingTimeoutNotice(false);

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
        const runData: ResearchRun = await res.json();
        // Retain run_id and initialize tracking
        setActiveRun(runData);
        setActionSuccess(t('prospect_detail.research_triggered'));

        if (runData.status === 'completed') {
          setResearching(false);
          await fetchIntelligence();
          await fetchResearchRuns();
        }
      } else {
        const errData = await res.json().catch(() => ({}));
        setResearchError(errData?.error?.message || t('prospect_detail.research_failed_msg'));
        setResearching(false);
      }
    } catch (err: any) {
      setResearchError(err.message || t('prospect_detail.research_failed_msg'));
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
  const isRunActive = activeRun?.status === 'pending' || activeRun?.status === 'running' || researching;
  const providerName = intelligence?.ai_provider || 'deterministic';
  const isDeterministic = providerName.toLowerCase().includes('deterministic');

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

        <div className="flex items-center gap-2 flex-wrap sm:flex-nowrap">
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
              disabled={isRunActive}
            >
              {isRunActive ? (
                <RefreshCw className="w-3.5 h-3.5 mr-1.5 animate-spin text-brand-gold" />
              ) : (
                <Compass className="w-3.5 h-3.5 mr-1.5 text-brand-gold" />
              )}
              {isRunActive ? t('prospect_detail.researching') : t('prospect_detail.research_button')}
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
                  <Send className={`w-3.5 h-3.5 mr-1.5 ${sendingToCrm ? 'animate-spin' : ''}`} />
                  {sendingToCrm ? t('prospect_detail.sending_to_crm') : t('prospect_detail.send_to_crm')}
                </Button>
              )}
            </PermissionGate>
          </div>
        </div>
      </div>

      {/* Action Banners & In-Flight Status */}
      {actionSuccess && (
        <div className="p-3 bg-success/10 border border-success/30 rounded-md text-xs text-success flex items-center justify-between">
          <span>{actionSuccess}</span>
          <button onClick={() => setActionSuccess(null)} className="text-success hover:underline">
            ✕
          </button>
        </div>
      )}

      {crmError && (
        <div className="p-3 bg-danger/10 border border-danger/30 rounded-md text-xs text-danger flex items-center justify-between">
          <span>{crmError}</span>
          <button onClick={() => setCrmError(null)} className="text-danger hover:underline">
            ✕
          </button>
        </div>
      )}

      {researchError && (
        <div className="p-3 bg-danger/10 border border-danger/30 rounded-md text-xs text-danger flex items-center justify-between">
          <div className="flex items-center gap-2">
            <AlertCircle className="w-4 h-4 text-danger shrink-0" />
            <span>{researchError}</span>
          </div>
          <button onClick={() => setResearchError(null)} className="text-danger hover:underline">
            ✕
          </button>
        </div>
      )}

      {/* Active Run Feedback Banners */}
      {activeRun?.status === 'pending' && (
        <div className="p-4 bg-brand-gold/10 border border-brand-gold/40 rounded-lg flex items-center gap-3 text-xs text-foreground">
          <Clock className="w-4 h-4 text-brand-gold animate-pulse shrink-0" />
          <div className="flex-1">
            <p className="font-semibold">{t('prospect_detail.research_requested')}</p>
            <p className="text-foreground-muted text-[11px]">
              Run ID: <span className="font-mono">{activeRun.id}</span> • Status: <Badge size="sm" variant="info">pending</Badge>
            </p>
          </div>
        </div>
      )}

      {activeRun?.status === 'running' && (
        <div className="p-4 bg-brand-gold/10 border border-brand-gold/40 rounded-lg flex items-center gap-3 text-xs text-foreground">
          <RefreshCw className="w-4 h-4 text-brand-gold animate-spin shrink-0" />
          <div className="flex-1">
            <p className="font-semibold">{t('prospect_detail.research_in_progress')}</p>
            <p className="text-foreground-muted text-[11px]">
              Run ID: <span className="font-mono">{activeRun.id}</span> • Status: <Badge size="sm" variant="warning">running</Badge>
            </p>
          </div>
        </div>
      )}

      {pollingTimeoutNotice && (
        <div className="p-4 bg-surface-subtle border border-border rounded-lg flex items-center gap-3 text-xs text-foreground">
          <Info className="w-4 h-4 text-brand-gold shrink-0" />
          <p className="text-foreground-muted">
            {t('prospect_detail.research_still_processing')}
          </p>
        </div>
      )}

      {/* Main Grid: Left Column (Overview, Intelligence, Signals, History) | Right Column (Scores) */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="space-y-6 lg:col-span-2">
          {/* Company Information & Provenance */}
          <div className="p-5 rounded-lg border border-border bg-surface space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold text-foreground flex items-center gap-2">
                <Building className="w-4 h-4 text-brand-gold" />
                {t('prospect_detail.company_info')}
              </h2>
              {locationStr && (
                <span className="text-xs text-foreground-muted">{locationStr}</span>
              )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
              <div className="p-3 bg-surface-subtle rounded-md space-y-1">
                <p className="text-foreground-muted font-medium flex items-center gap-1.5">
                  <Globe className="w-3.5 h-3.5" />
                  {t('prospect_detail.website')}
                </p>
                {prospect?.website_url ? (
                  <a
                    href={prospect.website_url.startsWith('http') ? prospect.website_url : `https://${prospect.website_url}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-brand-gold hover:underline flex items-center gap-1 font-mono truncate"
                  >
                    {prospect.website_url}
                    <ExternalLink className="w-3 h-3 shrink-0" />
                  </a>
                ) : (
                  <span className="text-foreground-muted font-mono">—</span>
                )}
              </div>

              <div className="p-3 bg-surface-subtle rounded-md space-y-1">
                <p className="text-foreground-muted font-medium flex items-center gap-1.5">
                  <Mail className="w-3.5 h-3.5" />
                  {t('prospect_detail.email')}
                </p>
                <span className="font-mono text-foreground">
                  {prospect?.email || '—'}
                </span>
              </div>

              <div className="p-3 bg-surface-subtle rounded-md space-y-1">
                <p className="text-foreground-muted font-medium flex items-center gap-1.5">
                  <Phone className="w-3.5 h-3.5" />
                  {t('prospect_detail.phone')}
                </p>
                <span className="font-mono text-foreground">
                  {prospect?.phone || '—'}
                </span>
              </div>

              <div className="p-3 bg-surface-subtle rounded-md space-y-1">
                <p className="text-foreground-muted font-medium flex items-center gap-1.5">
                  <Users className="w-3.5 h-3.5" />
                  {t('prospect_detail.campaign_memberships')}
                </p>
                <span className="font-semibold text-foreground">
                  {dossier?.campaign_associations?.length || 0} associated campaigns
                </span>
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

          {/* Research Intelligence Section */}
          <div className="p-5 rounded-lg border border-border bg-surface space-y-5">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-border">
              <div>
                <h2 className="text-sm font-bold text-foreground flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-brand-gold" />
                  {t('prospect_detail.research_intelligence_title')}
                </h2>
                <p className="text-xs text-foreground-muted mt-0.5">
                  {t('prospect_detail.research_intelligence_desc')}
                </p>
              </div>

              {intelligence && (
                <div className="flex items-center gap-2">
                  <Badge size="sm" variant={isDeterministic ? 'outline' : 'default'}>
                    {isDeterministic
                      ? t('prospect_detail.research_provider_deterministic')
                      : t('prospect_detail.research_provider_gemini')}
                  </Badge>
                  {intelMeta?.confidence !== undefined && intelMeta.confidence !== null && (
                    <span className="text-xs font-mono text-brand-gold">
                      {Math.round(intelMeta.confidence * 100)}% {t('prospect_detail.research_confidence_label')}
                    </span>
                  )}
                </div>
              )}
            </div>

            {/* Provider Transparency Explanation */}
            {intelligence && (
              <div className="p-3 rounded-md bg-surface-subtle border border-border/70 text-xs text-foreground-muted flex items-start gap-2.5">
                <Info className="w-4 h-4 text-brand-gold shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold text-foreground mr-1">
                    {t('prospect_detail.research_provider_label')}: {providerName}
                  </span>
                  <span>
                    {isDeterministic
                      ? t('prospect_detail.research_provider_deterministic_desc')
                      : t('prospect_detail.research_provider_gemini_desc')}
                  </span>
                </div>
              </div>
            )}

            {!intelligence && !isRunActive ? (
              <div className="py-6">
                <EmptyState
                  title={t('prospect_detail.research_empty_state')}
                  description="Run evidence-backed research to extract verified claims, commercial opportunities, and executive synthesis."
                  icon={<Compass className="w-8 h-8 text-brand-gold" />}
                />
              </div>
            ) : null}

            {intelligence && (
              <div className="space-y-5">
                {/* Executive Summary */}
                {intelligence.executive_summary && (
                  <div className="p-4 rounded-lg bg-surface-subtle border border-brand-gold/30 space-y-2">
                    <h3 className="text-xs font-bold text-brand-gold uppercase tracking-wider flex items-center gap-1.5">
                      <FileText className="w-3.5 h-3.5" />
                      {t('prospect_detail.executive_summary_title')}
                    </h3>
                    <p className="text-xs text-foreground leading-relaxed">
                      {intelligence.executive_summary}
                    </p>
                  </div>
                )}

                {/* Evidence & Verified Claims */}
                <div className="space-y-3">
                  <h3 className="text-xs font-bold text-foreground uppercase tracking-wider flex items-center gap-1.5">
                    <Shield className="w-3.5 h-3.5 text-brand-gold" />
                    {t('prospect_detail.verified_claims_title')} ({intelligence.claims?.length || 0})
                  </h3>

                  {!intelligence.claims || intelligence.claims.length === 0 ? (
                    <p className="text-xs text-foreground-muted py-2">
                      {t('prospect_detail.research_empty_claims')}
                    </p>
                  ) : (
                    <div className="space-y-2.5">
                      {intelligence.claims.map((claim) => {
                        const classificationLower = (claim.classification || 'observed').toLowerCase();
                        const isObserved = classificationLower.includes('observed');
                        const isDerived = classificationLower.includes('derived');

                        return (
                          <div
                            key={claim.id}
                            className="p-3 bg-surface-subtle rounded-md border border-border/70 space-y-1.5 text-xs"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <div className="flex items-center gap-2 flex-wrap">
                                <Badge
                                  size="sm"
                                  variant={isObserved ? 'success' : isDerived ? 'info' : 'warning'}
                                >
                                  {isObserved
                                    ? t('prospect_detail.evidence_observed')
                                    : isDerived
                                    ? t('prospect_detail.evidence_derived')
                                    : t('prospect_detail.evidence_inferred')}
                                </Badge>
                                {claim.claim_type && (
                                  <span className="text-[11px] text-foreground-muted font-mono">
                                    [{claim.claim_type}]
                                  </span>
                                )}
                              </div>
                              <span className="text-[11px] font-mono text-brand-gold shrink-0">
                                {Math.round((claim.confidence || 0) * 100)}% {t('prospect_detail.confidence')}
                              </span>
                            </div>

                            <p className="text-foreground font-medium text-xs leading-normal">
                              {claim.statement}
                            </p>

                            {((claim.evidence_refs && claim.evidence_refs.length > 0) ||
                              (claim.source_refs && claim.source_refs.length > 0)) && (
                              <div className="pt-1 text-[11px] text-foreground-muted flex items-center gap-2 flex-wrap">
                                <span className="font-semibold text-foreground">
                                  {t('prospect_detail.evidence_sources')}:
                                </span>
                                {claim.evidence_refs?.map((ref, idx) => (
                                  <span key={`ev-${idx}`} className="bg-surface px-1.5 py-0.5 rounded border border-border font-mono">
                                    {ref}
                                  </span>
                                ))}
                                {claim.source_refs?.map((ref, idx) => (
                                  <span key={`src-${idx}`} className="bg-surface px-1.5 py-0.5 rounded border border-border font-mono">
                                    {ref}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* Commercial Opportunities */}
                <div className="space-y-3">
                  <h3 className="text-xs font-bold text-foreground uppercase tracking-wider flex items-center gap-1.5">
                    <Flame className="w-3.5 h-3.5 text-brand-gold" />
                    {t('prospect_detail.commercial_opportunities_title')} ({intelligence.commercial_opportunities?.length || 0})
                  </h3>

                  {!intelligence.commercial_opportunities || intelligence.commercial_opportunities.length === 0 ? (
                    <p className="text-xs text-foreground-muted py-2">
                      {t('prospect_detail.research_empty_opportunities')}
                    </p>
                  ) : (
                    <div className="space-y-2.5">
                      {intelligence.commercial_opportunities.map((opp, idx) => (
                        <div
                          key={idx}
                          className="p-3 bg-surface-subtle rounded-md border border-border/70 space-y-1.5 text-xs"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2">
                              <Badge
                                size="sm"
                                variant={
                                  opp.priority === 'urgent'
                                    ? 'danger'
                                    : opp.priority === 'high'
                                    ? 'warning'
                                    : opp.priority === 'medium'
                                    ? 'info'
                                    : 'default'
                                }
                              >
                                {(opp.priority || 'NORMAL').toUpperCase()}
                              </Badge>
                              <span className="font-bold text-foreground">{opp.title}</span>
                            </div>
                            <span className="text-[11px] font-mono text-brand-gold shrink-0">
                              {Math.round((opp.confidence || 0) * 100)}% {t('prospect_detail.confidence')}
                            </span>
                          </div>

                          <p className="text-foreground-muted text-xs leading-normal">
                            {opp.description}
                          </p>

                          {opp.matched_services && opp.matched_services.length > 0 && (
                            <div className="pt-1 text-[11px] text-foreground-muted flex items-center gap-1.5 flex-wrap">
                              <span className="font-semibold text-foreground">
                                {t('prospect_detail.matched_services')}:
                              </span>
                              {opp.matched_services.map((svc, sIdx) => (
                                <span key={sIdx} className="bg-brand-gold/10 text-foreground px-1.5 py-0.5 rounded text-[10px]">
                                  {svc}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Risks & Unknowns */}
                {((intelligence.risks && intelligence.risks.length > 0) ||
                  (intelligence.unknowns && intelligence.unknowns.length > 0)) && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
                    {intelligence.risks && intelligence.risks.length > 0 && (
                      <div className="p-3 bg-danger/5 border border-danger/20 rounded-md text-xs space-y-1.5">
                        <h4 className="font-bold text-danger flex items-center gap-1.5">
                          <AlertTriangle className="w-3.5 h-3.5" />
                          {t('prospect_detail.risks_and_limitations_title')}
                        </h4>
                        <ul className="list-disc list-inside text-foreground-muted text-[11px] space-y-0.5">
                          {intelligence.risks.map((risk, rIdx) => (
                            <li key={rIdx}>{risk}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {intelligence.unknowns && intelligence.unknowns.length > 0 && (
                      <div className="p-3 bg-surface-subtle border border-border/80 rounded-md text-xs space-y-1.5">
                        <h4 className="font-bold text-foreground flex items-center gap-1.5">
                          <HelpCircle className="w-3.5 h-3.5 text-foreground-muted" />
                          {t('prospect_detail.unknowns_title')}
                        </h4>
                        <ul className="list-disc list-inside text-foreground-muted text-[11px] space-y-0.5">
                          {intelligence.unknowns.map((unk, uIdx) => (
                            <li key={uIdx}>{unk}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
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

          {/* Research Run History Card */}
          <div className="p-5 rounded-lg border border-border bg-surface space-y-3">
            <h3 className="text-sm font-bold text-foreground flex items-center gap-2">
              <Clock className="w-4 h-4 text-brand-gold" />
              {t('prospect_detail.research_history_title')} ({researchRuns.length})
            </h3>

            {researchRuns.length === 0 ? (
              <p className="text-xs text-foreground-muted py-2">
                {t('prospect_detail.research_history_empty')}
              </p>
            ) : (
              <div className="space-y-2">
                {researchRuns.map((run) => (
                  <div
                    key={run.id}
                    className="p-3 rounded-md bg-surface-subtle border border-border flex items-center justify-between text-xs"
                  >
                    <div>
                      <span className="font-mono text-foreground font-semibold">
                        {run.id.slice(0, 10)}...
                      </span>
                      <p className="text-[11px] text-foreground-muted">
                        {run.run_type || 'full_diligence'} • {new Date(run.created_at).toLocaleString()}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge
                        size="sm"
                        variant={
                          run.status === 'completed'
                            ? 'success'
                            : run.status === 'failed'
                            ? 'danger'
                            : run.status === 'running'
                            ? 'warning'
                            : 'info'
                        }
                      >
                        {t(`research.status.${(run.status || 'pending').toLowerCase()}`)}
                      </Badge>
                      {run.completed_at && (
                        <span className="text-[10px] text-foreground-muted font-mono hidden sm:inline">
                          {new Date(run.completed_at).toLocaleTimeString()}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Scoring, Urgency & Quick Intelligence */}
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

          {/* Quick Intelligence Summary Card */}
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
