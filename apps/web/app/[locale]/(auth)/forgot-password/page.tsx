'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useI18n } from '@/lib/i18n/context';
import { BrandLogo } from '@/components/brand/BrandLogo';
import { LocaleSwitcher } from '@/components/navigation/LocaleSwitcher';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { requestPasswordReset } from '@/lib/api/client';
import { CheckCircle2, ArrowLeft, Mail } from 'lucide-react';

export default function ForgotPasswordPage() {
  const { locale, t } = useI18n();

  const [email, setEmail] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setErrorMessage(null);

    try {
      await requestPasswordReset({ email, locale });
      setIsSubmitted(true);
    } catch (err: any) {
      // Even in case of errors, avoid leaking user existence
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

      {/* Main Card */}
      <div className="w-full max-w-md mx-auto my-auto py-8">
        <div className="bg-surface border border-border rounded-xl shadow-lg p-6 sm:p-8 space-y-6">
          <div className="space-y-1 text-center">
            <h1 className="text-xl font-bold tracking-tight text-foreground">
              {t('auth.forgot_password_title')}
            </h1>
            <p className="text-xs text-foreground-muted">
              {t('auth.forgot_password_subtitle')}
            </p>
          </div>

          {isSubmitted ? (
            <div className="space-y-5 animate-in fade-in">
              <div className="p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-700 dark:text-emerald-400 space-y-2 text-center">
                <CheckCircle2 className="w-8 h-8 mx-auto text-emerald-600 dark:text-emerald-400" />
                <p className="text-sm font-medium">
                  {t('auth.reset_link_sent')}
                </p>
              </div>

              <div className="pt-2 text-center">
                <Link
                  href={`/${locale}/login`}
                  className="inline-flex items-center gap-1.5 text-xs text-brand-gold hover:underline font-medium"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  {t('auth.back_to_login')}
                </Link>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {errorMessage && (
                <div className="p-3 rounded-md bg-rose-50 border border-rose-200 text-rose-700 text-xs font-medium animate-in fade-in">
                  {errorMessage}
                </div>
              )}

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

              <Button
                type="submit"
                className="w-full"
                isLoading={isLoading}
              >
                {isLoading ? t('auth.sending_reset_link') : t('auth.send_reset_link')}
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
