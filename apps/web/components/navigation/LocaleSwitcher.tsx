'use client';

import React from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useI18n } from '../../lib/i18n/context';
import { Locale, SUPPORTED_LOCALES } from '../../lib/i18n/types';
import { Globe } from 'lucide-react';

export function LocaleSwitcher() {
  const { locale } = useI18n();
  const pathname = usePathname();
  const router = useRouter();

  const handleLocaleChange = async (targetLocale: Locale) => {
    if (targetLocale === locale) return;

    // Replace the locale segment in the path: /[locale]/...
    const segments = pathname.split('/');
    if (SUPPORTED_LOCALES.includes(segments[1] as Locale)) {
      segments[1] = targetLocale;
    } else {
      segments.splice(1, 0, targetLocale);
    }
    const newPath = segments.join('/') || `/${targetLocale}`;

    // Best-effort update user preference in backend
    try {
      await fetch('/api/proxy/api/v1/me/preferences', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ locale: targetLocale }),
        credentials: 'include',
      });
    } catch {
      // Non-blocking preference sync
    }

    router.push(newPath);
  };

  return (
    <div className="flex items-center gap-1 text-xs border border-border rounded-md p-1 bg-surface shadow-xs">
      <Globe className="w-3.5 h-3.5 text-foreground-muted ml-1" />
      <button
        type="button"
        onClick={() => handleLocaleChange('en')}
        className={`px-2 py-0.5 rounded text-xs font-semibold transition-colors ${
          locale === 'en'
            ? 'bg-brand-dark text-white shadow-xs'
            : 'text-foreground-muted hover:text-foreground'
        }`}
        aria-label="Switch to English"
      >
        EN
      </button>
      <span className="text-border">|</span>
      <button
        type="button"
        onClick={() => handleLocaleChange('es')}
        className={`px-2 py-0.5 rounded text-xs font-semibold transition-colors ${
          locale === 'es'
            ? 'bg-brand-dark text-white shadow-xs'
            : 'text-foreground-muted hover:text-foreground'
        }`}
        aria-label="Cambiar a Español"
      >
        ES
      </button>
    </div>
  );
}
