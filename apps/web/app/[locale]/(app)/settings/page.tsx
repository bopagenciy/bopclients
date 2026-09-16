'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { useI18n } from '@/lib/i18n/context';
import { useAuth } from '@/lib/auth/context';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Modal } from '@/components/ui/Modal';
import { hasPermission } from '@/lib/permissions';
import {
  getOrganizationMembers,
  updateMemberRole,
  removeOrganizationMember,
  updateOrganizationProfile,
} from '@/lib/api/client';
import { OrganizationMember, Role } from '@/lib/api/types';
import {
  Building2,
  Users,
  Shield,
  KeyRound,
  UserCheck,
  Trash2,
  Edit2,
  AlertTriangle,
  CheckCircle2,
  Loader2,
  Info,
} from 'lucide-react';

export default function SettingsPage() {
  const { t } = useI18n();
  const { user, activeOrg, activeRole } = useAuth();
  const [activeTab, setActiveTab] = useState<'organization' | 'members' | 'security'>('organization');

  // Organization settings state
  const [orgName, setOrgName] = useState(activeOrg?.name || '');
  const [isSavingOrg, setIsSavingOrg] = useState(false);
  const [orgMessage, setOrgMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Team members state
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [isLoadingMembers, setIsLoadingMembers] = useState(false);
  const [memberActionError, setMemberActionError] = useState<string | null>(null);
  const [memberActionSuccess, setMemberActionSuccess] = useState<string | null>(null);

  // Role Edit Modal state
  const [roleModalTarget, setRoleModalTarget] = useState<OrganizationMember | null>(null);
  const [selectedNewRole, setSelectedNewRole] = useState<string>('MEMBER');
  const [isUpdatingRole, setIsUpdatingRole] = useState(false);

  // Remove Member Modal state
  const [removeModalTarget, setRemoveModalTarget] = useState<OrganizationMember | null>(null);
  const [isRemovingMember, setIsRemovingMember] = useState(false);

  const canManageOrg = hasPermission(activeRole, 'organization.manage');
  const canManageMembers = hasPermission(activeRole, 'members.manage');

  // Synchronize initial org name
  useEffect(() => {
    if (activeOrg?.name) {
      setOrgName(activeOrg.name);
    }
  }, [activeOrg?.name]);

  // Load team members
  const fetchMembers = useCallback(async () => {
    setIsLoadingMembers(true);
    setMemberActionError(null);
    try {
      const data = await getOrganizationMembers();
      setMembers(data);
    } catch (err: any) {
      setMemberActionError(err?.message || t('settings.team.empty'));
    } finally {
      setIsLoadingMembers(false);
    }
  }, [t]);

  useEffect(() => {
    if (activeTab === 'members') {
      fetchMembers();
    }
  }, [activeTab, fetchMembers]);

  // Save Organization Name
  const handleSaveOrganization = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!canManageOrg) return;
    if (!orgName.trim()) {
      setOrgMessage({ type: 'error', text: t('settings.organization.name_placeholder') });
      return;
    }

    setIsSavingOrg(true);
    setOrgMessage(null);
    try {
      await updateOrganizationProfile({ name: orgName.trim() });
      setOrgMessage({ type: 'success', text: t('settings.organization.save_success') });
      if (activeOrg) {
        activeOrg.name = orgName.trim();
      }
    } catch (err: any) {
      setOrgMessage({ type: 'error', text: err?.message || t('settings.organization.save_error') });
    } finally {
      setIsSavingOrg(false);
    }
  };

  // Check role update eligibility
  const canEditMemberRole = (target: OrganizationMember): boolean => {
    if (!canManageMembers) return false;
    const normalizedTargetRole = (target.role || '').toUpperCase();
    const normalizedActorRole = (activeRole || '').toUpperCase();

    if (normalizedActorRole === 'OWNER') {
      return true;
    }
    if (normalizedActorRole === 'ADMIN') {
      return normalizedTargetRole === 'MEMBER' || normalizedTargetRole === 'VIEWER';
    }
    return false;
  };

  // Check member removal eligibility
  const canRemoveMember = (target: OrganizationMember): boolean => {
    if (!canManageMembers) return false;
    const normalizedTargetRole = (target.role || '').toUpperCase();
    const normalizedActorRole = (activeRole || '').toUpperCase();

    if (normalizedActorRole === 'OWNER') {
      // Sole owner protection check on client side
      const owners = members.filter((m) => (m.role || '').toUpperCase() === 'OWNER');
      if (normalizedTargetRole === 'OWNER' && owners.length <= 1) {
        return false;
      }
      return true;
    }
    if (normalizedActorRole === 'ADMIN') {
      if (normalizedTargetRole === 'OWNER') return false;
      if (normalizedTargetRole === 'ADMIN' && target.user_id !== user?.id) return false;
      return true;
    }
    return false;
  };

  // Available roles for selector based on actor's permission
  const getEligibleRolesForActor = (): Role[] => {
    const normalizedActorRole = (activeRole || '').toUpperCase();
    if (normalizedActorRole === 'OWNER') {
      return ['OWNER', 'ADMIN', 'MEMBER', 'VIEWER'];
    }
    if (normalizedActorRole === 'ADMIN') {
      return ['MEMBER', 'VIEWER'];
    }
    return [];
  };

  // Open role modal
  const openRoleModal = (member: OrganizationMember) => {
    setRoleModalTarget(member);
    setSelectedNewRole((member.role || 'MEMBER').toUpperCase());
    setMemberActionError(null);
    setMemberActionSuccess(null);
  };

  // Submit role update
  const handleUpdateRole = async () => {
    if (!roleModalTarget) return;
    setIsUpdatingRole(true);
    setMemberActionError(null);
    try {
      await updateMemberRole(roleModalTarget.user_id, selectedNewRole);
      setMemberActionSuccess(t('settings.team.role_updated_success'));
      setRoleModalTarget(null);
      await fetchMembers();
    } catch (err: any) {
      setMemberActionError(err?.message || t('settings.team.role_update_error'));
    } finally {
      setIsUpdatingRole(false);
    }
  };

  // Open remove modal
  const openRemoveModal = (member: OrganizationMember) => {
    setRemoveModalTarget(member);
    setMemberActionError(null);
    setMemberActionSuccess(null);
  };

  // Submit member removal
  const handleRemoveMember = async () => {
    if (!removeModalTarget) return;
    setIsRemovingMember(true);
    setMemberActionError(null);
    try {
      await removeOrganizationMember(removeModalTarget.user_id);
      setMemberActionSuccess(t('settings.team.remove_success'));
      setRemoveModalTarget(null);
      await fetchMembers();
    } catch (err: any) {
      setMemberActionError(err?.message || t('settings.team.remove_error'));
    } finally {
      setIsRemovingMember(false);
    }
  };

  // Role Badge Formatter
  const renderRoleBadge = (roleStr: string) => {
    const r = (roleStr || '').toUpperCase();
    switch (r) {
      case 'OWNER':
        return <Badge variant="gold">{t('roles.owner')}</Badge>;
      case 'ADMIN':
        return <Badge variant="success">{t('roles.admin')}</Badge>;
      case 'MEMBER':
        return <Badge variant="info">{t('roles.member')}</Badge>;
      case 'VIEWER':
      default:
        return <Badge variant="outline">{t('roles.viewer')}</Badge>;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          {t('settings.title')}
        </h1>
        <p className="text-xs text-foreground-muted">
          {t('settings.subtitle')}
        </p>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-2 border-b border-border text-xs font-semibold">
        <button
          onClick={() => setActiveTab('organization')}
          className={`flex items-center gap-2 px-4 py-2.5 border-b-2 transition-colors ${
            activeTab === 'organization'
              ? 'border-brand-dark text-foreground'
              : 'border-transparent text-foreground-muted hover:text-foreground'
          }`}
        >
          <Building2 className="w-3.5 h-3.5" />
          {t('settings.tabs.organization')}
        </button>
        <button
          onClick={() => setActiveTab('members')}
          className={`flex items-center gap-2 px-4 py-2.5 border-b-2 transition-colors ${
            activeTab === 'members'
              ? 'border-brand-dark text-foreground'
              : 'border-transparent text-foreground-muted hover:text-foreground'
          }`}
        >
          <Users className="w-3.5 h-3.5" />
          {t('settings.tabs.members')}
        </button>
        <button
          onClick={() => setActiveTab('security')}
          className={`flex items-center gap-2 px-4 py-2.5 border-b-2 transition-colors ${
            activeTab === 'security'
              ? 'border-brand-dark text-foreground'
              : 'border-transparent text-foreground-muted hover:text-foreground'
          }`}
        >
          <Shield className="w-3.5 h-3.5" />
          {t('settings.tabs.security')}
        </button>
      </div>

      {/* Tab 1: Organization Profile */}
      {activeTab === 'organization' && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle>{t('settings.organization.title')}</CardTitle>
              <CardDescription>{t('settings.organization.description')}</CardDescription>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSaveOrganization} className="space-y-4">
                {orgMessage && (
                  <div
                    className={`flex items-center gap-2 p-3 rounded-lg text-xs border ${
                      orgMessage.type === 'success'
                        ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
                        : 'bg-rose-50 text-rose-800 border-rose-200'
                    }`}
                  >
                    {orgMessage.type === 'success' ? (
                      <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" />
                    ) : (
                      <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" />
                    )}
                    <span>{orgMessage.text}</span>
                  </div>
                )}

                <div>
                  <label htmlFor="org-name" className="text-xs font-semibold text-foreground">
                    {t('settings.organization.name_label')}
                  </label>
                  <Input
                    id="org-name"
                    value={orgName}
                    onChange={(e) => setOrgName(e.target.value)}
                    readOnly={!canManageOrg}
                    placeholder={t('settings.organization.name_placeholder')}
                    className={`mt-1 ${!canManageOrg ? 'bg-surface-subtle cursor-not-allowed' : ''}`}
                  />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="text-xs font-semibold text-foreground">
                      {t('settings.organization.slug_label')}
                    </label>
                    <Input
                      value={activeOrg?.slug || ''}
                      readOnly
                      className="mt-1 bg-surface-subtle cursor-not-allowed font-mono text-xs"
                    />
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-foreground">
                      {t('settings.organization.bop_id_label')}
                    </label>
                    <Input
                      value={activeOrg?.bop_organization_id || ''}
                      readOnly
                      className="mt-1 bg-surface-subtle cursor-not-allowed font-mono text-xs"
                    />
                    <span className="text-[10px] text-foreground-muted flex items-center gap-1 mt-1">
                      <Info className="w-3 h-3 text-brand-gold shrink-0" />
                      {t('settings.organization.bop_id_help')}
                    </span>
                  </div>
                </div>

                {canManageOrg && (
                  <div className="pt-2 flex justify-end">
                    <Button type="submit" disabled={isSavingOrg || !orgName.trim()}>
                      {isSavingOrg ? (
                        <>
                          <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                          {t('settings.organization.saving_button')}
                        </>
                      ) : (
                        t('settings.organization.save_button')
                      )}
                    </Button>
                  </div>
                )}
              </form>
            </CardContent>
          </Card>

          {/* Metadata Card */}
          <Card>
            <CardHeader>
              <CardTitle>{t('settings.organization.my_role_label')}</CardTitle>
              <CardDescription>{user?.email}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-[11px] text-foreground-muted font-medium">
                  {t('settings.organization.my_role_label')}
                </p>
                <div className="mt-1.5">{renderRoleBadge(activeRole || 'VIEWER')}</div>
              </div>

              <div className="pt-3 border-t border-border/60">
                <p className="text-[11px] text-foreground-muted font-medium">
                  {t('settings.organization.member_count_label')}
                </p>
                <p className="text-xl font-bold text-foreground mt-0.5">
                  {members.length > 0 ? members.length : '—'}
                </p>
              </div>

              <div className="pt-3 border-t border-border/60 space-y-2">
                <div className="flex justify-between text-xs">
                  <span className="text-foreground-muted">{t('settings.organization.country_label')}:</span>
                  <span className="font-semibold text-foreground font-mono">US</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-foreground-muted">{t('settings.organization.language_label')}:</span>
                  <span className="font-semibold text-foreground font-mono">en</span>
                </div>
                <div className="flex justify-between text-xs">
                  <span className="text-foreground-muted">{t('settings.organization.timezone_label')}:</span>
                  <span className="font-semibold text-foreground font-mono">UTC</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Tab 2: Team Members */}
      {activeTab === 'members' && (
        <Card>
          <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <div>
              <CardTitle>{t('settings.team.title')}</CardTitle>
              <CardDescription>
                {t('settings.team.subtitle')}
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline" size="sm">
                {t('settings.team.total_count', { count: members.length })}
              </Badge>
              {!canManageMembers && (
                <Badge variant="default" size="sm">
                  {t('settings.team.read_only_badge')}
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Feedback Alerts */}
            {memberActionSuccess && (
              <div className="flex items-center gap-2 p-3 rounded-lg text-xs bg-emerald-50 text-emerald-800 border border-emerald-200">
                <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" />
                <span>{memberActionSuccess}</span>
              </div>
            )}
            {memberActionError && (
              <div className="flex items-center gap-2 p-3 rounded-lg text-xs bg-rose-50 text-rose-800 border border-rose-200">
                <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" />
                <span>{memberActionError}</span>
              </div>
            )}

            {/* Loading State */}
            {isLoadingMembers && (
              <div className="py-12 flex flex-col items-center justify-center text-foreground-muted gap-2 text-xs">
                <Loader2 className="w-5 h-5 animate-spin text-brand-gold" />
                <span>{t('settings.team.loading')}</span>
              </div>
            )}

            {/* Empty State */}
            {!isLoadingMembers && members.length === 0 && (
              <div className="py-12 text-center text-xs text-foreground-muted">
                {t('settings.team.empty')}
              </div>
            )}

            {/* Members Table (Desktop & Tablet) */}
            {!isLoadingMembers && members.length > 0 && (
              <div className="hidden md:block overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="border-b border-border text-foreground-muted uppercase text-[10px] tracking-wider">
                    <tr>
                      <th className="py-3 px-4">{t('settings.team.col_member')}</th>
                      <th className="py-3 px-4">{t('settings.team.col_email')}</th>
                      <th className="py-3 px-4">{t('settings.team.col_role')}</th>
                      <th className="py-3 px-4">{t('settings.team.col_joined')}</th>
                      <th className="py-3 px-4 text-right">{t('settings.team.col_actions')}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/60">
                    {members.map((member) => {
                      const canEditRole = canEditMemberRole(member);
                      const canRemove = canRemoveMember(member);
                      const isCurrentUser = member.user_id === user?.id;

                      return (
                        <tr key={member.id} className="hover:bg-surface-subtle/50 transition-colors">
                          <td className="py-3 px-4">
                            <div className="flex items-center gap-3">
                              <div className="w-8 h-8 rounded-full bg-brand-dark text-white flex items-center justify-center text-xs font-bold shrink-0">
                                {(member.full_name || member.email || 'U')[0].toUpperCase()}
                              </div>
                              <div>
                                <span className="font-semibold text-foreground">
                                  {member.full_name || member.email?.split('@')[0]}
                                </span>
                                {isCurrentUser && (
                                  <span className="ml-1.5 text-[10px] font-medium text-brand-gold">
                                    (You)
                                  </span>
                                )}
                              </div>
                            </div>
                          </td>
                          <td className="py-3 px-4 font-mono text-foreground-muted">
                            {member.email || '—'}
                          </td>
                          <td className="py-3 px-4">
                            {renderRoleBadge(member.role as string)}
                          </td>
                          <td className="py-3 px-4 text-foreground-muted">
                            {member.created_at ? new Date(member.created_at).toLocaleDateString() : '—'}
                          </td>
                          <td className="py-3 px-4 text-right">
                            <div className="flex items-center justify-end gap-1.5">
                              {canEditRole && (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => openRoleModal(member)}
                                  aria-label={`${t('settings.team.edit_role')} ${member.full_name || member.email}`}
                                >
                                  <Edit2 className="w-3 h-3 mr-1" />
                                  {t('settings.team.edit_role')}
                                </Button>
                              )}
                              {canRemove && (
                                <Button
                                  variant="outline"
                                  size="sm"
                                  onClick={() => openRemoveModal(member)}
                                  aria-label={`${t('settings.team.remove_member')} ${member.full_name || member.email}`}
                                  className="text-rose-600 hover:text-rose-700 hover:bg-rose-50 border-rose-200"
                                >
                                  <Trash2 className="w-3 h-3 mr-1" />
                                  {t('settings.team.remove_member')}
                                </Button>
                              )}
                              {!canEditRole && !canRemove && (
                                <span className="text-[11px] text-foreground-muted italic">
                                  {t('settings.team.cannot_modify')}
                                </span>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {/* Responsive Cards (Mobile <768px) */}
            {!isLoadingMembers && members.length > 0 && (
              <div className="md:hidden space-y-3">
                {members.map((member) => {
                  const canEditRole = canEditMemberRole(member);
                  const canRemove = canRemoveMember(member);
                  const isCurrentUser = member.user_id === user?.id;

                  return (
                    <div
                      key={member.id}
                      className="p-4 rounded-xl border border-border bg-surface-subtle/30 space-y-3"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex items-center gap-3">
                          <div className="w-9 h-9 rounded-full bg-brand-dark text-white flex items-center justify-center text-xs font-bold shrink-0">
                            {(member.full_name || member.email || 'U')[0].toUpperCase()}
                          </div>
                          <div>
                            <p className="text-xs font-semibold text-foreground">
                              {member.full_name || member.email?.split('@')[0]}
                              {isCurrentUser && (
                                <span className="ml-1.5 text-[10px] font-medium text-brand-gold">
                                  (You)
                                </span>
                              )}
                            </p>
                            <p className="text-[11px] text-foreground-muted font-mono">{member.email}</p>
                          </div>
                        </div>
                        <div>{renderRoleBadge(member.role as string)}</div>
                      </div>

                      <div className="text-[11px] text-foreground-muted flex justify-between border-t border-border/40 pt-2">
                        <span>{t('settings.team.col_joined')}:</span>
                        <span>{member.created_at ? new Date(member.created_at).toLocaleDateString() : '—'}</span>
                      </div>

                      {(canEditRole || canRemove) && (
                        <div className="flex items-center gap-2 pt-2 border-t border-border/40">
                          {canEditRole && (
                            <Button
                              variant="outline"
                              size="sm"
                              className="flex-1"
                              onClick={() => openRoleModal(member)}
                            >
                              <Edit2 className="w-3 h-3 mr-1" />
                              {t('settings.team.edit_role')}
                            </Button>
                          )}
                          {canRemove && (
                            <Button
                              variant="outline"
                              size="sm"
                              className="flex-1 text-rose-600 hover:text-rose-700 hover:bg-rose-50 border-rose-200"
                              onClick={() => openRemoveModal(member)}
                            >
                              <Trash2 className="w-3 h-3 mr-1" />
                              {t('settings.team.remove_member')}
                            </Button>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Tab 3: Security */}
      {activeTab === 'security' && (
        <Card>
          <CardHeader>
            <CardTitle>{t('settings.security.title')}</CardTitle>
            <CardDescription>{t('settings.security.subtitle')}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-xs">
            <div className="p-4 rounded-xl bg-surface-subtle/50 border border-border space-y-1.5">
              <p className="font-semibold text-foreground flex items-center gap-2">
                <Shield className="w-4 h-4 text-brand-gold" />
                {t('settings.security.cookie_title')}
              </p>
              <p className="text-foreground-muted leading-relaxed">
                {t('settings.security.cookie_desc')}
              </p>
            </div>

            <div className="p-4 rounded-xl bg-surface-subtle/50 border border-border space-y-1.5">
              <p className="font-semibold text-foreground flex items-center gap-2">
                <KeyRound className="w-4 h-4 text-emerald-600" />
                {t('settings.security.hashing_title')}
              </p>
              <p className="text-foreground-muted leading-relaxed">
                {t('settings.security.hashing_desc')}
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Role Update Modal */}
      <Modal
        isOpen={!!roleModalTarget}
        onClose={() => setRoleModalTarget(null)}
        title={t('settings.team.role_modal_title')}
        description={t('settings.team.role_modal_desc', {
          name: roleModalTarget?.full_name || roleModalTarget?.email || '',
        })}
      >
        <div className="space-y-4">
          <div>
            <label htmlFor="role-select" className="text-xs font-semibold text-foreground">
              {t('settings.team.role_label')}
            </label>
            <select
              id="role-select"
              value={selectedNewRole}
              onChange={(e) => setSelectedNewRole(e.target.value)}
              className="mt-1 block w-full rounded-md border border-border bg-surface px-3 py-2 text-xs text-foreground shadow-sm focus:border-brand-gold focus:outline-none focus:ring-1 focus:ring-brand-gold"
            >
              {getEligibleRolesForActor().map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center justify-end gap-2 pt-3 border-t border-border">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setRoleModalTarget(null)}
              disabled={isUpdatingRole}
            >
              {t('settings.team.role_modal_cancel')}
            </Button>
            <Button
              size="sm"
              onClick={handleUpdateRole}
              disabled={isUpdatingRole || selectedNewRole === roleModalTarget?.role?.toUpperCase()}
            >
              {isUpdatingRole ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                  {t('common.loading')}
                </>
              ) : (
                t('settings.team.role_modal_save')
              )}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Remove Member Confirmation Modal */}
      <Modal
        isOpen={!!removeModalTarget}
        onClose={() => setRemoveModalTarget(null)}
        title={t('settings.team.remove_modal_title')}
      >
        <div className="space-y-4">
          <p className="text-xs text-foreground-muted leading-relaxed">
            {t('settings.team.remove_modal_desc', {
              name: removeModalTarget?.full_name || removeModalTarget?.email?.split('@')[0] || '',
              email: removeModalTarget?.email || '',
            })}
          </p>

          <div className="flex items-center justify-end gap-2 pt-3 border-t border-border">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setRemoveModalTarget(null)}
              disabled={isRemovingMember}
            >
              {t('settings.team.remove_modal_cancel')}
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={handleRemoveMember}
              disabled={isRemovingMember}
              className="bg-rose-600 hover:bg-rose-700 text-white"
            >
              {isRemovingMember ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                  {t('settings.team.remove_modal_in_progress')}
                </>
              ) : (
                t('settings.team.remove_modal_confirm')
              )}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
