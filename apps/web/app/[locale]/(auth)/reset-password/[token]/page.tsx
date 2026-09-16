'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useParams, useSearchParams, useRouter } from 'next/navigation';
import { useI18n } from '@/lib/i18n/context';
import { BrandLogo } from '@/components/brand/BrandLogo';
import { LocaleSwitcher } from '@/components/navigation/LocaleSwitcher';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { confirmPasswordReset } from '@/lib/api/client';
import { CheckCircle2, AlertCircle, ArrowLeft } from 'lucide-react';

export default function ResetPasswordPage() {
  const { locale, t } = useI18n();
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();

  const token = (params?.token as string) || searchParams.get('token') || '';

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);

    if (!token) {
      setErrorMessage(t('auth.invalid_or_expired_token'));
      return;
    }

    if (password.length < 8) {
      setErrorMessage(t('auth.password_min_length'));
      return;
    }

    if (password !== confirmPassword) {
      setErrorMessage(t('auth.passwords_do_not_match'));
      return;
    }

    setIsLoading(true);

    try {
      await confirmPasswordReset({ token, new_password: password });
      setIsSuccess(true);
    } catch (err: any) {
      const code = err?.code;
      if (code === 'INVALID_TOKEN' || err?.status === 400) {
        setErrorMessage(t('auth.invalid_or_expired_token'));
      } else {
        setErrorMessage(err.message || t('auth.auth_failed'));
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-between bg-background p-4 sm:p-6 lg:p-8">
      {/* Top Header */}
      <div className="flex items-center justify-between w-full max-w-5xl mx-auto py-2">
        <BrandLogo locale={locale} />
        <LocaleSwitcher />
      </div>

      {/* Main Card */}
      <div className="w-full max-w-md mx-auto my-auto py-8">
        <div className="bg-surface border border-border rounded-xl shadow-lg p-6 sm:p-8 space-y-6">
          <div className="space-y-1 text-center">
            <h1 className="text-xl font-bold tracking-tight text-foreground">
              {t('auth.reset_password_title')}
            </h1>
            <p className="text-xs text-foreground-muted">
              {t('auth.reset_password_subtitle')}
            </p>
          </div>

          {isSuccess ? (
            <div className="space-y-5 animate-in fade-in">
              <div className="p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-700 dark:text-emerald-400 space-y-2 text-center">
                <CheckCircle2 className="w-8 h-8 mx-auto text-emerald-600 dark:text-emerald-400" />
                <p className="text-sm font-medium">
                  {t('auth.password_reset_success')}
                </p>
              </div>

              <div className="pt-2 text-center">
                <Link
                  href={`/${locale}/login`}
                  className="inline-flex items-center justify-center w-full py-2.5 px-4 rounded-md bg-brand-gold text-brand-dark hover:bg-brand-gold/90 font-medium text-sm transition-colors"
                >
                  {t('auth.signin_button')}
                </Link>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {errorMessage && (
                <div className="p-3 rounded-md bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium space-y-1 animate-in fade-in">
                  <div className="flex items-center gap-1.5">
                    <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" />
                    <span>{errorMessage}</span>
                  </div>
                  {errorMessage === t('auth.invalid_or_expired_token') && (
                    <div className="pt-1">
                      <Link
                        href={`/${locale}/forgot-password`}
                        className="underline text-rose-800 font-semibold hover:text-rose-900"
                      >
                        {t('auth.send_reset_link')}
                      </Link>
                    </div>
                  )}
                </div>
              )}

              <div>
                <Input
                  label={t('auth.new_password_label')}
                  type="password"
                  placeholder="••••••••••••"
                  value={password}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => setPassword(e.target.value)}
                  required
                  autoComplete="new-password"
                  disabled={isLoading}
                />
              </div>

              <div>
                <Input
                  label={t('auth.confirm_password_label')}
                  type="password"
                  placeholder="••••••••••••"
                  value={confirmPassword}
                  onChange={(e: React.ChangeEvent<HTMLInputElement>) => setConfirmPassword(e.target.value)}
                  required
                  autoComplete="new-password"
                  disabled={isLoading}
                />
              </div>

              <Button
                type="submit"
                className="w-full"
                isLoading={isLoading}
              >
                {isLoading ? t('auth.resetting_password') : t('auth.reset_password_button')}
              </Button>

              <div className="pt-2 text-center">
                <Link
                  href={`/${locale}/login`}
                  className="inline-flex items-center gap-1.5 text-xs text-foreground-muted hover:text-foreground transition-colors font-medium"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  {t('auth.back_to_login')}
                </Link>
              </div>
            </form>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="w-full max-w-5xl mx-auto py-4 text-center text-xs text-foreground-muted">
        <p>© 2026 BOP | CLIENTS — {t('brand.tagline')}</p>
      </div>
    </div>
  );
}
