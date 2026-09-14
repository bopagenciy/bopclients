import React from 'react';
import { describe, it, expect } from 'vitest';
import { renderToString } from 'react-dom/server';
import { BrandLogo } from '../components/brand/BrandLogo';
import { I18nProvider } from '../lib/i18n/context';

describe('BrandLogo Component', () => {
  it('renders strictly typographic fallback without any fabricated iconography', () => {
    const html = renderToString(
      <I18nProvider locale="en">
        <BrandLogo locale="en" />
      </I18nProvider>
    );

    // Verify purely typographic text
    expect(html).toContain('BOP');
    expect(html).toContain('CLIENTS');
    expect(html).toContain('aria-label="BopClients Home"');

    // Confirm NO fabricated SVG icons, geometric nodes, or symbols
    expect(html).not.toContain('<svg');
    expect(html).not.toContain('<path');
    expect(html).not.toContain('<circle');
  });

  it('renders Spanish aria-label when locale is es', () => {
    const html = renderToString(
      <I18nProvider locale="es">
        <BrandLogo locale="es" />
      </I18nProvider>
    );

    expect(html).toContain('aria-label="Inicio de BopClients"');
  });

  it('renders collapsed typographic fallback omitting secondary wordmark', () => {
    const html = renderToString(
      <I18nProvider locale="en">
        <BrandLogo locale="en" collapsed={true} />
      </I18nProvider>
    );

    expect(html).toContain('BOP');
    expect(html).not.toContain('CLIENTS');
  });
});
