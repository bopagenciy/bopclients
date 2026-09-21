import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { renderToString } from 'react-dom/server';
import fs from 'fs';
import path from 'path';
import { BrandLogo } from '../components/brand/BrandLogo';
import { AppSidebar } from '../components/navigation/AppSidebar';
import { I18nProvider } from '../lib/i18n/context';
import { AuthProvider } from '../lib/auth/context';

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: () => '/en/dashboard',
  useSearchParams: () => new URLSearchParams(),
}));

const dummySession = {
  user: {
    id: 'usr-1',
    email: 'test@bopagencia.local',
    full_name: 'Test User',
    locale: 'en',
    is_active: true,
    is_superuser: false,
    created_at: '2026-09-01T00:00:00Z',
  },
  active_organization: {
    id: 'org-1',
    bop_organization_id: 'bop-org-1',
    name: 'Bop Agencia',
    slug: 'bop-agencia',
    role: 'ADMIN',
  },
  active_role: 'ADMIN',
  organizations: [
    {
      id: 'org-1',
      bop_organization_id: 'bop-org-1',
      name: 'Bop Agencia',
      slug: 'bop-agencia',
      role: 'ADMIN',
    },
  ],
};

describe('P30.3 Official Product Branding Foundation', () => {
  it('official asset exists in public assets structure and original is preserved', () => {
    const originalAsset = path.resolve(__dirname, '../../../bopclients/logo/BopClients.png');
    const publicAsset = path.resolve(__dirname, '../public/brand/BopClients.png');
    const wordmarkAsset = path.resolve(__dirname, '../public/brand/bop-clients-wordmark.png');
    const markAsset = path.resolve(__dirname, '../public/brand/bop-clients-mark.png');
    const iconAsset = path.resolve(__dirname, '../public/brand/bop-clients-icon.png');
    const faviconAsset = path.resolve(__dirname, '../public/favicon.ico');

    expect(fs.existsSync(originalAsset)).toBe(true);
    expect(fs.existsSync(publicAsset)).toBe(true);
    expect(fs.existsSync(wordmarkAsset)).toBe(true);
    expect(fs.existsSync(markAsset)).toBe(true);
    expect(fs.existsSync(iconAsset)).toBe(true);
    expect(fs.existsSync(faviconAsset)).toBe(true);

    // Verify byte size matches between original and copied public asset
    const origSize = fs.statSync(originalAsset).size;
    const pubSize = fs.statSync(publicAsset).size;
    expect(pubSize).toBe(origSize);
  });

  it('BrandLogo renders official wordmark with correct public asset path and alt', () => {
    const html = renderToString(
      <I18nProvider locale="en">
        <BrandLogo locale="en" />
      </I18nProvider>
    );

    expect(html).toContain('src="/brand/bop-clients-wordmark.png"');
    expect(html).toContain('alt="BopClients"');
    expect(html).toContain('aria-label="BopClients Home"');
  });

  it('BrandLogo renders collapsed mark for compact navigation', () => {
    const html = renderToString(
      <I18nProvider locale="en">
        <BrandLogo locale="en" collapsed={true} />
      </I18nProvider>
    );

    expect(html).toContain('src="/brand/bop-clients-mark.png"');
    expect(html).toContain('alt="BopClients"');
  });

  it('sidebar renders brand logo and preserves tenant organization switcher', () => {
    const html = renderToString(
      <I18nProvider locale="en">
        <AuthProvider initialSession={dummySession as any}>
          <AppSidebar />
        </AuthProvider>
      </I18nProvider>
    );

    // Brand logo identity in sidebar header
    expect(html).toContain('src="/brand/bop-clients-wordmark.png"');
    expect(html).toContain('alt="BopClients"');

    // Tenant Organization Switcher preserved independently
    expect(html).toContain('Bop Agencia');
  });

  it('browser metadata in layout defines BopClients identity and favicon', () => {
    const rootLayout = fs.readFileSync(path.resolve(__dirname, '../app/layout.tsx'), 'utf8');
    const localeLayout = fs.readFileSync(path.resolve(__dirname, '../app/[locale]/layout.tsx'), 'utf8');

    expect(rootLayout).toContain('BopClients — Autonomous Prospecting Platform');
    expect(rootLayout).toContain('/brand/bop-clients-icon.png');
    expect(rootLayout).toContain('/favicon.ico');

    expect(localeLayout).toContain('BopClients — Autonomous Prospecting Platform');
    expect(localeLayout).toContain('/brand/bop-clients-icon.png');
    expect(localeLayout).toContain('/favicon.ico');
  });

  it('login page integrates BrandLogo with clean layout and no FORGE mentions', () => {
    const loginPage = fs.readFileSync(
      path.resolve(__dirname, '../app/[locale]/(auth)/login/page.tsx'),
      'utf8'
    );

    expect(loginPage).toContain('<BrandLogo locale={locale} />');
    expect(loginPage).not.toContain('FORGE');
    expect(loginPage).not.toContain('DataForge');
  });

  it('localized routes and translation keys are maintained without FORGE strings', () => {
    const en = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../messages/en.json'), 'utf8'));
    const es = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../messages/es.json'), 'utf8'));

    expect(en.brand.home_label).toBe('BopClients Home');
    expect(es.brand.home_label).toBe('Inicio de BopClients');
    expect(en.auth.title).toContain('BopClients');
    expect(es.auth.title).toContain('BopClients');
  });
});
