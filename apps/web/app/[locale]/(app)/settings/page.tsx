'use client';

import React, { useState } from 'react';
import { useI18n } from '@/lib/i18n/context';
import { useAuth } from '@/lib/auth/context';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { PermissionGate } from '@/components/navigation/PermissionGate';
import { hasPermission } from '@/lib/permissions';
import { Settings, Users, Shield, KeyRound, Lock, UserPlus } from 'lucide-react';

export default function SettingsPage() {
  const { t } = useI18n();
  const { user, activeOrg, activeRole } = useAuth();
  const [activeTab, setActiveTab] = useState<'general' | 'members' | 'security'>('general');

  const canManageMembers = hasPermission(activeRole, 'members.manage');

  return (
    <div className="space-y-6">
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
          onClick={() => setActiveTab('general')}
          className={`px-4 py-2.5 border-b-2 transition-colors ${
            activeTab === 'general'
              ? 'border-brand-dark text-foreground'
              : 'border-transparent text-foreground-muted hover:text-foreground'
          }`}
        >
          {t('settings.tabs.general')}
        </button>
        <button
          onClick={() => setActiveTab('members')}
          className={`px-4 py-2.5 border-b-2 transition-colors ${
            activeTab === 'members'
              ? 'border-brand-dark text-foreground'
              : 'border-transparent text-foreground-muted hover:text-foreground'
          }`}
        >
          {t('settings.tabs.members')}
        </button>
        <button
          onClick={() => setActiveTab('security')}
          className={`px-4 py-2.5 border-b-2 transition-colors ${
            activeTab === 'security'
              ? 'border-brand-dark text-foreground'
              : 'border-transparent text-foreground-muted hover:text-foreground'
          }`}
        >
          {t('settings.tabs.security')}
        </button>
      </div>

      {/* General Tab */}
      {activeTab === 'general' && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Card>
            <CardHeader>
              <CardTitle>Tenant Identity</CardTitle>
              <CardDescription>Global organization configuration and metadata.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-foreground">Organization Name</label>
                <Input value={activeOrg?.name || ''} readOnly className="mt-1 bg-surface-subtle" />
              </div>
              <div>
                <label className="text-xs font-semibold text-foreground">Slug</label>
                <Input value={activeOrg?.slug || ''} readOnly className="mt-1 bg-surface-subtle" />
              </div>
              <div>
                <label className="text-xs font-semibold text-foreground">Canonical Bop Org ID</label>
                <Input
                  value={activeOrg?.bop_organization_id || ''}
                  readOnly
                  className="mt-1 bg-surface-subtle font-mono text-xs"
                />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>My Account Profile</CardTitle>
              <CardDescription>Personal user profile and active membership role.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-foreground">Full Name</label>
                <Input value={user?.full_name || ''} readOnly className="mt-1 bg-surface-subtle" />
              </div>
              <div>
                <label className="text-xs font-semibold text-foreground">Email Address</label>
                <Input value={user?.email || ''} readOnly className="mt-1 bg-surface-subtle font-mono" />
              </div>
              <div>
                <label className="text-xs font-semibold text-foreground">Assigned Role</label>
                <div className="mt-1">
                  <Badge variant="gold">{activeRole || 'VIEWER'}</Badge>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Members Tab */}
      {activeTab === 'members' && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <div>
              <CardTitle>{t('settings.tabs.members')}</CardTitle>
              <CardDescription>
                Collaborators with active memberships in {activeOrg?.name}.
              </CardDescription>
            </div>
            <PermissionGate permission="members.manage">
              <Button size="sm">
                <UserPlus className="w-4 h-4 mr-1.5" />
                {t('settings.invite_button')}
              </Button>
            </PermissionGate>
          </CardHeader>
          <CardContent>
            {!canManageMembers && (
              <div className="mb-4 flex items-center gap-2 p-3 rounded-lg bg-surface-subtle border border-border text-xs text-foreground-muted">
                <Lock className="w-4 h-4 text-brand-gold shrink-0" />
                <span>{t('settings.role_restriction')}</span>
              </div>
            )}

            <div className="divide-y divide-border/60">
              <div className="py-3 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-brand-dark text-white flex items-center justify-center text-xs font-bold">
                    {(user?.full_name || user?.email || 'U')[0].toUpperCase()}
                  </div>
                  <div>
                    <p className="text-xs font-semibold text-foreground">{user?.full_name || 'Current User'}</p>
                    <p className="text-[11px] text-foreground-muted font-mono">{user?.email}</p>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <Badge size="sm" variant="gold">{activeRole || 'OWNER'}</Badge>
                  <span className="text-[11px] text-emerald-600 font-medium">Active</span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Security Tab */}
      {activeTab === 'security' && (
        <Card>
          <CardHeader>
            <CardTitle>{t('settings.tabs.security')}</CardTitle>
            <CardDescription>Enterprise security architecture & BFF token lifecycle.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4 text-xs">
            <div className="p-3 rounded-lg bg-surface-subtle/50 border border-border space-y-1">
              <p className="font-semibold text-foreground flex items-center gap-1.5">
                <Shield className="w-3.5 h-3.5 text-brand-gold" />
                Zero Client Token Storage Guarantee
              </p>
              <p className="text-foreground-muted">
                JWT access tokens and opaque refresh session tokens are stored strictly inside HttpOnly, SameSite=Lax browser cookies. They are never written to localStorage or sessionStorage.
              </p>
            </div>

            <div className="p-3 rounded-lg bg-surface-subtle/50 border border-border space-y-1">
              <p className="font-semibold text-foreground flex items-center gap-1.5">
                <KeyRound className="w-3.5 h-3.5 text-emerald-600" />
                Cryptographic Password Hashing
              </p>
              <p className="text-foreground-muted">
                Argon2id primary hashing with cryptographically unique salts. Server-side session revocation ensures instant session termination upon logout.
              </p>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
