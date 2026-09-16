'use client';

import React, { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useI18n } from '@/lib/i18n/context';
import { useAuth } from '@/lib/auth/context';
import { Card, CardHeader, CardTitle, CardContent, CardDescription, CardFooter } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import {
  getPublicInvitation,
  acceptInvitation,
  registerAndAcceptInvitation,
} from '@/lib/api/client';
import { InvitationPublicMetadata } from '@/lib/api/types';
import {
  Building2,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Mail,
  Shield,
  UserCheck,
  ArrowRight,
  LogOut,
} from 'lucide-react';

export default function InviteAcceptPage() {
  const { t, locale } = useI18n();
  const { user, isAuthenticated, logout } = useAuth();
  const router = useRouter();
  const params = useParams();
  const token = params?.token as string;

  const [invitation, setInvitation] = useState<InvitationPublicMetadata | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [errorType, setErrorType] = useState<string | null>(null);

  // Authenticated acceptance state
  const [isAccepting, setIsAccepting] = useState(false);
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [acceptSuccess, setAcceptSuccess] = useState(false);

  // Unauthenticated register-and-accept form state
  const [registerMode, setRegisterMode] = useState(false);
  const [regName, setRegName] = useState('');
  const [regPassword, setRegPassword] = useState('');
  const [isRegistering, setIsRegistering] = useState(false);
  const [regError, setRegError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    let isMounted = true;

    async function load() {
      setIsLoading(true);
      setLoadError(null);
      setErrorType(null);
      try {
        const data = await getPublicInvitation(token);
        if (isMounted) {
          setInvitation(data);
        }
      } catch (err: any) {
        if (isMounted) {
          const code = err?.code || '';
          setErrorType(code);
          if (code === 'INVITATION_EXPIRED') {
            setLoadError(t('invite.expired_desc'));
          } else if (code === 'INVITATION_REVOKED') {
            setLoadError(t('invite.revoked_desc'));
          } else if (code === 'INVITATION_ALREADY_ACCEPTED') {
            setLoadError(t('invite.already_accepted_desc'));
          } else {
            setLoadError(err?.message || t('invite.invalid_token_desc'));
          }
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    load();
    return () => {
      isMounted = false;
    };
  }, [token, t]);

  // Handle logged-in acceptance
  const handleAcceptLoggedIn = async () => {
    if (!token) return;
    setIsAccepting(true);
    setAcceptError(null);
    try {
      await acceptInvitation(token);
      setAcceptSuccess(true);
      setTimeout(() => {
        router.push(`/${locale}/settings`);
      }, 1500);
    } catch (err: any) {
      setAcceptError(err?.message || t('invite.accept_error'));
    } finally {
      setIsAccepting(false);
    }
  };

  // Handle new user register & accept
  const handleRegisterAndAccept = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !regName.trim() || !regPassword.trim()) return;
    setIsRegistering(true);
    setRegError(null);
    try {
      await registerAndAcceptInvitation({
        token,
        name: regName.trim(),
        password: regPassword,
        locale,
      });
      setAcceptSuccess(true);
      setTimeout(() => {
        router.push(`/${locale}/settings`);
      }, 1500);
    } catch (err: any) {
      setRegError(err?.message || t('invite.accept_error'));
    } finally {
      setIsRegistering(false);
    }
  };

  // Loading State
  if (isLoading) {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center p-4">
        <Loader2 className="w-8 h-8 animate-spin text-brand-gold mb-3" />
        <p className="text-xs text-foreground-muted">{t('settings.team.loading')}</p>
      </div>
    );
  }

  // Error State (Expired, Revoked, Not Found, etc.)
  if (loadError || !invitation) {
    return (
      <div className="min-h-[70vh] flex items-center justify-center p-4">
        <Card className="w-full max-w-md shadow-lg border-border">
          <CardHeader className="text-center pb-2">
            <div className="w-12 h-12 rounded-full bg-rose-100 dark:bg-rose-950/50 text-rose-600 flex items-center justify-center mx-auto mb-3">
              <AlertTriangle className="w-6 h-6" />
            </div>
            <CardTitle className="text-lg">
              {errorType === 'INVITATION_EXPIRED'
                ? t('invite.expired_title')
                : errorType === 'INVITATION_REVOKED'
                ? t('invite.revoked_title')
                : errorType === 'INVITATION_ALREADY_ACCEPTED'
                ? t('invite.already_accepted_title')
                : t('invite.invalid_token_title')}
            </CardTitle>
            <CardDescription className="text-xs text-foreground-muted leading-relaxed mt-1.5">
              {loadError || t('invite.invalid_token_desc')}
            </CardDescription>
          </CardHeader>
          <CardFooter className="flex justify-center pt-4">
            <Button
              variant="outline"
              size="sm"
              onClick={() => router.push(`/${locale}/login`)}
            >
              {t('invite.back_to_login')}
            </Button>
          </CardFooter>
        </Card>
      </div>
    );
  }

  const isEmailMatch =
    isAuthenticated && user?.email?.trim().toLowerCase() === invitation.email.trim().toLowerCase();

  return (
    <div className="min-h-[75vh] flex items-center justify-center p-4">
      <Card className="w-full max-w-lg shadow-xl border-border">
        {/* Card Header */}
        <CardHeader className="text-center pb-4 border-b border-border/50">
          <div className="w-12 h-12 rounded-2xl bg-brand-dark text-white flex items-center justify-center mx-auto mb-3 shadow-md">
            <Building2 className="w-6 h-6 text-brand-gold" />
          </div>
          <CardTitle className="text-xl font-bold text-foreground">
            {t('invite.title')}
          </CardTitle>
          <CardDescription className="text-xs text-foreground-muted mt-1">
            {t('invite.subtitle', { org: invitation.organization_name })}
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-5 pt-5">
          {/* Success Banner */}
          {acceptSuccess && (
            <div className="flex items-center gap-3 p-4 rounded-xl bg-emerald-50 text-emerald-800 border border-emerald-200 text-xs animate-in fade-in">
              <CheckCircle2 className="w-5 h-5 shrink-0 text-emerald-600" />
              <div>
                <p className="font-semibold">
                  {t('invite.accept_success', { org: invitation.organization_name })}
                </p>
                <p className="text-[11px] text-emerald-700 mt-0.5">Redirecting to organization dashboard...</p>
              </div>
            </div>
          )}

          {/* Invitation Details Summary */}
          <div className="p-4 rounded-xl bg-surface-subtle/50 border border-border/80 space-y-2.5 text-xs">
            <div className="flex justify-between items-center">
              <span className="text-foreground-muted">{t('settings.tabs.organization')}:</span>
              <span className="font-bold text-foreground">{invitation.organization_name}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-foreground-muted">{t('settings.team.role_label')}:</span>
              <Badge variant="gold" size="sm" className="uppercase font-bold tracking-wider">
                {invitation.role}
              </Badge>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-foreground-muted">{t('settings.invitations.col_email')}:</span>
              <span className="font-mono text-foreground font-semibold">{invitation.email}</span>
            </div>
          </div>

          {/* SCENARIO 1: Logged In & Matching Email */}
          {isAuthenticated && isEmailMatch && !acceptSuccess && (
            <div className="space-y-4 pt-2">
              {acceptError && (
                <div className="flex items-center gap-2 p-3 rounded-lg text-xs bg-rose-50 text-rose-800 border border-rose-200">
                  <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" />
                  <span>{acceptError}</span>
                </div>
              )}

              <Button
                size="lg"
                className="w-full gap-2 text-sm font-semibold"
                onClick={handleAcceptLoggedIn}
                disabled={isAccepting}
              >
                {isAccepting ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin mr-1" />
                    {t('invite.accepting')}
                  </>
                ) : (
                  <>
                    <UserCheck className="w-4 h-4" />
                    {t('invite.accept_button')}
                  </>
                )}
              </Button>
            </div>
          )}

          {/* SCENARIO 2: Logged In but EMAIL MISMATCH */}
          {isAuthenticated && !isEmailMatch && !acceptSuccess && (
            <div className="space-y-4 pt-2">
              <div className="p-4 rounded-xl bg-amber-50 text-amber-900 border border-amber-200 text-xs space-y-2">
                <p className="font-bold flex items-center gap-1.5 text-amber-800">
                  <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
                  {t('invite.email_mismatch_title')}
                </p>
                <p className="leading-relaxed">
                  {t('invite.email_mismatch_desc', {
                    currentEmail: user?.email || '',
                    invitedEmail: invitation.email,
                  })}
                </p>
              </div>

              <Button
                variant="outline"
                size="sm"
                className="w-full gap-2 text-xs"
                onClick={async () => {
                  await logout();
                  router.push(`/${locale}/login?email=${encodeURIComponent(invitation.email)}`);
                }}
              >
                <LogOut className="w-3.5 h-3.5" />
                {t('invite.login_different_account')}
              </Button>
            </div>
          )}

          {/* SCENARIO 3: Not Logged In */}
          {!isAuthenticated && !acceptSuccess && (
            <div className="space-y-4 pt-2">
              {!registerMode ? (
                <div className="space-y-3">
                  <p className="text-xs text-foreground-muted text-center">
                    {t('invite.login_prompt', { email: invitation.email })}
                  </p>
                  <Button
                    size="lg"
                    className="w-full gap-2 text-sm"
                    onClick={() =>
                      router.push(
                        `/${locale}/login?email=${encodeURIComponent(
                          invitation.email
                        )}&returnUrl=${encodeURIComponent(`/${locale}/invite/${token}`)}`
                      )
                    }
                  >
                    {t('invite.login_to_accept')}
                    <ArrowRight className="w-4 h-4" />
                  </Button>

                  <div className="relative my-4">
                    <div className="absolute inset-0 flex items-center">
                      <span className="w-full border-t border-border" />
                    </div>
                    <div className="relative flex justify-center text-[10px] uppercase">
                      <span className="bg-surface px-2 text-foreground-muted font-bold">Or</span>
                    </div>
                  </div>

                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full text-xs"
                    onClick={() => setRegisterMode(true)}
                  >
                    {t('invite.register_title')}
                  </Button>
                </div>
              ) : (
                <form onSubmit={handleRegisterAndAccept} className="space-y-3">
                  <div className="text-left space-y-1">
                    <h4 className="text-xs font-bold text-foreground">
                      {t('invite.register_title')}
                    </h4>
                    <p className="text-[11px] text-foreground-muted">
                      {t('invite.register_desc', { org: invitation.organization_name })}
                    </p>
                  </div>

                  {regError && (
                    <div className="flex items-center gap-2 p-3 rounded-lg text-xs bg-rose-50 text-rose-800 border border-rose-200">
                      <AlertTriangle className="w-4 h-4 shrink-0 text-rose-600" />
                      <span>{regError}</span>
                    </div>
                  )}

                  <div>
                    <label className="text-[11px] font-semibold text-foreground">
                      {t('invite.name_label')}
                    </label>
                    <Input
                      required
                      value={regName}
                      onChange={(e) => setRegName(e.target.value)}
                      placeholder={t('invite.name_placeholder')}
                      className="mt-1 text-xs"
                    />
                  </div>

                  <div>
                    <label className="text-[11px] font-semibold text-foreground">
                      {t('invite.password_label')}
                    </label>
                    <Input
                      type="password"
                      required
                      minLength={8}
                      value={regPassword}
                      onChange={(e) => setRegPassword(e.target.value)}
                      placeholder={t('invite.password_placeholder')}
                      className="mt-1 text-xs"
                    />
                  </div>

                  <div className="flex items-center gap-2 pt-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => setRegisterMode(false)}
                      disabled={isRegistering}
                    >
                      {t('settings.invitations.modal_cancel')}
                    </Button>
                    <Button
                      type="submit"
                      size="sm"
                      className="flex-1"
                      disabled={isRegistering || !regName.trim() || !regPassword.trim()}
                    >
                      {isRegistering ? (
                        <>
                          <Loader2 className="w-3.5 h-3.5 mr-1 animate-spin" />
                          {t('invite.registering')}
                        </>
                      ) : (
                        t('invite.register_button')
                      )}
                    </Button>
                  </div>
                </form>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
