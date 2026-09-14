'use client';

import React, { useState, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/lib/auth/context';
import { useI18n } from '@/lib/i18n/context';
import { BrandLogo } from '@/components/brand/BrandLogo';
import { LocaleSwitcher } from '@/components/navigation/LocaleSwitcher';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { ShieldCheck, Lock, Mail } from 'lucide-react';

export default function LoginPage() {
  const { login, isAuthenticated } = useAuth();
  const { locale, t } = useI18n();
  const router = useRouter();
  const searchParams = useSearchParams();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (isAuthenticated) {
      router.push(`/${locale}/dashboard`);
    }
  }, [isAuthenticated, locale, router]);

  useEffect(() => {
    if (searchParams.get('expired')) {
      setErrorMessage(t('auth.session_expired'));
    }
  }, [searchParams, t]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setErrorMessage(null);

    try {
      await login({ email, password });
      router.push(`/${locale}/dashboard`);
    } catch (err: any) {
      setErrorMessage(err.message || t('auth.auth_failed'));
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

      {/* Main Login Card */}
      <div className="w-full max-w-md mx-auto my-auto py-8">
        <div className="bg-surface border border-border rounded-xl shadow-lg p-6 sm:p-8 space-y-6">
          <div className="space-y-1 text-center">
            <h1 className="text-xl font-bold tracking-tight text-foreground">
              {t('auth.title')}
            </h1>
            <p className="text-xs text-foreground-muted">
              {t('auth.subtitle')}
            </p>
          </div>

          {errorMessage && (
            <div className="p-3 rounded-md bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium animate-in fade-in">
              {errorMessage}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <Input
                label={t('auth.email_label')}
                type="email"
                placeholder={t('auth.email_placeholder')}
                value={email}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEmail(e.target.value)}
                required
                autoComplete="email"
                disabled={isLoading}
              />
            </div>

            <div>
              <Input
                label={t('auth.password_label')}
                type="password"
                placeholder={t('auth.password_placeholder')}
                value={password}
                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                disabled={isLoading}
              />
            </div>

            <Button
              type="submit"
              className="w-full"
              isLoading={isLoading}
            >
              {isLoading ? t('auth.signing_in') : t('auth.signin_button')}
            </Button>
          </form>

          {/* Security architecture notice */}
          <div className="pt-2 border-t border-border/70 flex items-center justify-center gap-1.5 text-[11px] text-foreground-muted">
            <ShieldCheck className="w-3.5 h-3.5 text-brand-gold shrink-0" />
            <span>{t('auth.secure_badge')}</span>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className="w-full max-w-5xl mx-auto py-4 text-center text-xs text-foreground-muted">
        <p>© 2026 BOP | CLIENTS — {t('brand.tagline')}</p>
      </div>
    </div>
  );
}
