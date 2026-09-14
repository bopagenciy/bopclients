import en from '../../messages/en.json';
import es from '../../messages/es.json';
import { Locale, DEFAULT_LOCALE, SUPPORTED_LOCALES } from './types';

const catalogs: Record<Locale, Record<string, any>> = {
  en,
  es,
};

export function isValidLocale(locale: string): locale is Locale {
  return SUPPORTED_LOCALES.includes(locale as Locale);
}

export function getDictionary(locale: Locale) {
  return catalogs[locale] || catalogs[DEFAULT_LOCALE];
}

export function translate(
  locale: Locale,
  path: string,
  params?: Record<string, string | number>
): string {
  const dict = getDictionary(locale);
  const segments = path.split('.');

  let current: any = dict;
  for (const seg of segments) {
    if (current && typeof current === 'object' && seg in current) {
      current = current[seg];
    } else {
      // Fallback to English dictionary if not found in current locale
      let fallback: any = catalogs[DEFAULT_LOCALE];
      for (const fSeg of segments) {
        if (fallback && typeof fallback === 'object' && fSeg in fallback) {
          fallback = fallback[fSeg];
        } else {
          return path;
        }
      }
      current = fallback;
      break;
    }
  }

  if (typeof current !== 'string') {
    return path;
  }

  let result = current;
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      result = result.replace(new RegExp(`\\{${key}\\}`, 'g'), String(value));
    }
  }

  return result;
}

export * from './types';
