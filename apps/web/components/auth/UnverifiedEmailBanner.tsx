'use client';

import React, { useState } from 'react';
import { useAuth } from '@/lib/auth/context';
import { useI18n } from '@/lib/i18n/context';
import { resendEmailVerification } from '@/lib/api/client';
import { AlertTriangle, Mail, CheckCircle2, Loader2, X } from 'lucide-react';

export function UnverifiedEmailBanner() {
  const { user } = useAuth();
  const { locale, t } = useI18n();

  const [isDismissed, setIsDismissed] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [sentSuccess, setSentSuccess] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // If user is verified or banner dismissed, don't show anything
  if (!user || user.is_verified !== false || isDismissed) {
    return null;
  }

  const handleResend = async () => {
    setIsSending(true);
    setErrorMessage(null);

    try {
      await resendEmailVerification({ locale });
      setSentSuccess(true);
    } catch (err: any) {
      setErrorMessage(err.message || 'Failed to resend verification email.');
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div
      role="region"
      aria-label="Email verification notice"
      className="bg-amber-500/10 border-b border-amber-500/20 text-amber-900 dark:text-amber-200 px-4 py-2.5 text-xs transition-all"
    >
      <div className="max-w-7xl mx-auto flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <AlertTriangle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
          <span className="font-medium truncate">
            {t('auth.unverified_email_banner')}
          </span>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          {sentSuccess ? (
            <span className="inline-flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400 font-medium">
              <CheckCircle2 className="w-3.5 h-3.5" />
              {t('auth.verification_email_sent')}
            </span>
          ) : (
            <button
              onClick={handleResend}
              disabled={isSending}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded bg-amber-600/20 hover:bg-amber-600/30 text-amber-900 dark:text-amber-100 font-medium transition-colors disabled:opacity-50"
            >
              {isSending ? (
                <>
                  <Loader2 className="w-3 h-3 animate-spin" />
                  <span>{t('auth.resending_verification')}</span>
                </>
              ) : (
                <>
                  <Mail className="w-3 h-3" />
                  <span>{t('auth.resend_verification')}</span>
                </>
              )}
            </button>
          )}

          {errorMessage && (
            <span className="text-rose-600 text-[11px]">{errorMessage}</span>
          )}

          <button
            onClick={() => setIsDismissed(true)}
            aria-label="Dismiss verification banner"
            className="text-amber-700 dark:text-amber-400 hover:opacity-75 transition-opacity p-0.5"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}
