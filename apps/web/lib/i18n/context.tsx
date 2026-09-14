'use client';

import React, { createContext, useContext, useMemo } from 'react';
import { Locale, DEFAULT_LOCALE } from './types';
import { translate, getDictionary } from './index';

interface I18nContextType {
  locale: Locale;
  t: (key: string, params?: Record<string, string | number>) => string;
  dictionary: Record<string, any>;
}

const I18nContext = createContext<I18nContextType>({
  locale: DEFAULT_LOCALE,
  t: (key: string, params?: Record<string, string | number>) => translate(DEFAULT_LOCALE, key, params),
  dictionary: getDictionary(DEFAULT_LOCALE),
});

export function I18nProvider({
  locale,
  children,
}: {
  locale: Locale;
  children: React.ReactNode;
}) {
  const dictionary = useMemo(() => getDictionary(locale), [locale]);

  const value = useMemo(
    () => ({
      locale,
      t: (key: string, params?: Record<string, string | number>) => translate(locale, key, params),
      dictionary,
    }),
    [locale, dictionary]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextType {
  const context = useContext(I18nContext);
  if (!context) {
    throw new Error('useI18n must be used within an I18nProvider');
  }
  return context;
}
