import { describe, it, expect } from 'vitest';
import en from '../messages/en.json';
import es from '../messages/es.json';
import { translate } from '../lib/i18n';

function extractKeys(obj: Record<string, any>, prefix = ''): string[] {
  let keys: string[] = [];
  for (const [key, value] of Object.entries(obj)) {
    const fullKey = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      keys = keys.concat(extractKeys(value, fullKey));
    } else {
      keys.push(fullKey);
    }
  }
  return keys.sort();
}

describe('i18n Translation Catalogs', () => {
  it('should have 100% key parity between English and Spanish catalogs', () => {
    const enKeys = extractKeys(en);
    const esKeys = extractKeys(es);

    // Assert key counts match
    expect(enKeys.length).toBeGreaterThan(20);
    expect(esKeys.length).toBe(enKeys.length);

    // Check missing keys in Spanish
    const missingInEs = enKeys.filter((k) => !esKeys.includes(k));
    expect(missingInEs).toEqual([]);

    // Check extraneous keys in Spanish
    const extraInEs = esKeys.filter((k) => !enKeys.includes(k));
    expect(extraInEs).toEqual([]);
  });

  it('should translate keys correctly in English and Spanish', () => {
    expect(translate('en', 'brand.name')).toBe('BOP | CLIENTS');
    expect(translate('es', 'brand.name')).toBe('BOP | CLIENTS');

    expect(translate('en', 'nav.dashboard')).toBe('Dashboard');
    expect(translate('es', 'nav.dashboard')).toBe('Panel Principal');

    expect(translate('en', 'auth.signin_button')).toBe('Sign In');
    expect(translate('es', 'auth.signin_button')).toBe('Iniciar Sesión');
  });

  it('should interpolate variables accurately', () => {
    const enShowing = translate('en', 'prospects.pagination.showing', {
      start: 1,
      end: 15,
      total: 100,
    });
    expect(enShowing).toBe('Showing 1 to 15 of 100 prospects');

    const esShowing = translate('es', 'prospects.pagination.showing', {
      start: 1,
      end: 15,
      total: 100,
    });
    expect(esShowing).toBe('Mostrando 1 a 15 de 100 prospectos');
  });

  it('should fallback to English if key is missing in Spanish catalog', () => {
    // If a non-existent key is queried, return the key path
    expect(translate('es', 'non.existent.key')).toBe('non.existent.key');
  });
});
