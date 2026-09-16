'use client';

import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { useParams, useSearchParams, useRouter } from 'next/navigation';
import { useI18n } from '@/lib/i18n/context';
import { useAuth } from '@/lib/auth/context';
import { BrandLogo } from '@/components/brand/BrandLogo';
import { LocaleSwitcher } from '@/components/navigation/LocaleSwitcher';
import { Button } from '@/components/ui/Button';
import { confirmEmailVerification } from '@/lib/api/client';
import { CheckCircle2, AlertCircle, Loader2, ArrowRight } from 'lucide-react';

export default function VerifyEmailPage() {
  const { locale, t } = useI18n();
  const { isAuthenticated } = useAuth();
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();

  const token = (params?.token as string) || searchParams.get('token') || '';

  const [isLoading, setIsLoading] = useState(true);
  const [isSuccess, setIsSuccess] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setIsLoading(false);
      setErrorMessage(t('auth.email_verification_failed'));
      return;
    }

    let isMounted = true;

    async function verify() {
      try {
        await confirmEmailVerification({ token });
        if (isMounted) {
          setIsSuccess(true);
        }
      } catch (err: any) {
        if (isMounted) {
          setErrorMessage(err.message || t('auth.email_verification_failed'));
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    verify();

    return () => {
      isMounted = false;
    };
  }, [token, t]);

  return (
    <div className="min-h-screen flex flex-col justify-between bg-background p-4 sm:p-6 lg:p-8">
      {/* Top Header */}
      <div className="flex items-center justify-between w-full max-w-5xl mx-auto py-2">
        <BrandLogo locale={locale} />
        <LocaleSwitcher />
      </div>

      {/* Main Card */}
      <div className="w-full max-w-md mx-auto my-auto py-8">
        <div className="bg-surface border border-border rounded-xl shadow-lg p-6 sm:p-8 space-y-6 text-center">
          <div className="space-y-1">
            <h1 className="text-xl font-bold tracking-tight text-foreground">
              {t('auth.verify_email_title')}
            </h1>
          </div>

          {isLoading && (
            <div className="py-8 space-y-3">
              <Loader2 className="w-8 h-8 mx-auto animate-spin text-brand-gold" />
              <p className="text-xs text-foreground-muted">
                {t('auth.verifying_email')}
              </p>
            </div>
          )}

          {!isLoading && isSuccess && (
            <div className="space-y-5 animate-in fade-in">
              <div className="p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-emerald-700 dark:text-emerald-400 space-y-2">
                <CheckCircle2 className="w-8 h-8 mx-auto text-emerald-600 dark:text-emerald-400" />
                <p className="text-sm font-medium">
                  {t('auth.email_verified_success')}
                </p>
              </div>

              <div className="pt-2">
                <Link
                  href={isAuthenticated ? `/${locale}/dashboard` : `/${locale}/login`}
                  className="inline-flex items-center justify-center gap-2 w-full py-2.5 px-4 rounded-md bg-brand-gold text-brand-dark hover:bg-brand-gold/90 font-medium text-sm transition-colors"
                >
                  <span>{isAuthenticated ? t('nav.dashboard') : t('auth.signin_button')}</span>
                  <ArrowRight className="w-4 h-4" />
                </Link>
              </div>
            </div>
          )}

          {!isLoading && !isSuccess && (
            <div className="space-y-5 animate-in fade-in">
              <div className="p-4 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 space-y-2">
                <AlertCircle className="w-8 h-8 mx-auto text-rose-600" />
                <p className="text-sm font-medium">
                  {errorMessage || t('auth.email_verification_failed')}
                </p>
              </div>

              <div className="pt-2">
                <Link
                  href={`/${locale}/login`}
                  className="inline-flex items-center justify-center w-full py-2.5 px-4 rounded-md bg-secondary text-foreground hover:bg-secondary/80 font-medium text-sm transition-colors border border-border"
                >
                  {t('auth.back_to_login')}
                </Link>
              </div>
            </div>
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
