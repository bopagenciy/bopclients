import React from 'react';
import { describe, it, expect } from 'vitest';
import { renderToString } from 'react-dom/server';
import { BrandLogo } from '../components/brand/BrandLogo';
import { I18nProvider } from '../lib/i18n/context';

describe('BrandLogo Component', () => {
  it('renders official BopClients logo image with correct public asset path', () => {
    const html = renderToString(
      <I18nProvider locale="en">
        <BrandLogo locale="en" />
      </I18nProvider>
    );

    // Verify official image asset is rendered with correct alt and source
    expect(html).toContain('src="/brand/bop-clients-wordmark.png"');
    expect(html).toContain('alt="BopClients"');
    expect(html).toContain('aria-label="BopClients Home"');
    expect(html).toContain('href="/en/dashboard"');

    // Confirm NO fabricated SVG icons, geometric nodes, or symbols
    expect(html).not.toContain('<svg');
    expect(html).not.toContain('<path');
    expect(html).not.toContain('<circle');

    // Confirm no FORGE branding
    expect(html).not.toContain('FORGE');
    expect(html).not.toContain('DataForge');
  });

  it('renders collapsed official BopClients mark when collapsed is true', () => {
    const html = renderToString(
      <I18nProvider locale="en">
        <BrandLogo locale="en" collapsed={true} />
      </I18nProvider>
    );

    expect(html).toContain('src="/brand/bop-clients-mark.png"');
    expect(html).toContain('alt="BopClients"');
    expect(html).toContain('aria-label="BopClients Home"');
  });

  it('renders Spanish aria-label and localized link when locale is es', () => {
    const html = renderToString(
      <I18nProvider locale="es">
        <BrandLogo locale="es" />
      </I18nProvider>
    );

    expect(html).toContain('aria-label="Inicio de BopClients"');
    expect(html).toContain('href="/es/dashboard"');
  });

  it('renders strictly typographic fallback when fallbackOnly is requested', () => {
    const html = renderToString(
      <I18nProvider locale="en">
        <BrandLogo locale="en" fallbackOnly={true} />
      </I18nProvider>
    );

    expect(html).toContain('BOP');
    expect(html).toContain('CLIENTS');
    expect(html).toContain('aria-label="BopClients Home"');
    expect(html).not.toContain('<img');
  });

  it('renders collapsed typographic fallback omitting secondary wordmark when fallbackOnly is true', () => {
    const html = renderToString(
      <I18nProvider locale="en">
        <BrandLogo locale="en" collapsed={true} fallbackOnly={true} />
      </I18nProvider>
    );

    expect(html).toContain('BOP');
    expect(html).not.toContain('CLIENTS');
    expect(html).not.toContain('<img');
  });
});
