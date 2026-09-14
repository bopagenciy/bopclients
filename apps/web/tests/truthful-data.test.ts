import { describe, it, expect } from 'vitest';
import fs from 'fs';
import path from 'path';

describe('Truthful Data & Integrity Verification', () => {
  const appPagesDir = path.resolve(__dirname, '../app/[locale]/(app)');

  function readAllTsxFiles(dir: string): string[] {
    let contents: string[] = [];
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        contents = contents.concat(readAllTsxFiles(fullPath));
      } else if (entry.name.endsWith('.tsx')) {
        contents.push(fs.readFileSync(fullPath, 'utf8'));
      }
    }
    return contents;
  }

  it('contains NO hardcoded fake company entities in foundation views', () => {
    const allCode = readAllTsxFiles(appPagesDir).join('\n');

    // Assert that invented sample companies are not hardcoded as real data
    expect(allCode).not.toContain('Stripe, Inc.');
    expect(allCode).not.toContain('Datadog Solutions');
    expect(allCode).not.toContain('Corporate Outbound Webhook');
    expect(allCode).not.toContain('BopCRM Sync Endpoint');
  });

  it('contains NO hardcoded fake metrics or invented percentages', () => {
    const allCode = readAllTsxFiles(appPagesDir).join('\n');

    // Assert that fabricated metrics are eliminated
    expect(allCode).not.toContain('+12.5%');
    expect(allCode).not.toContain('99.9%');
    expect(allCode).not.toContain('4 Nodes');
    expect(allCode).not.toContain('1,240');
  });

  it('contains NO fabricated brand mark or SVG artwork in public assets', () => {
    const svgPath = path.resolve(__dirname, '../public/brand/bop-clients-logo.svg');
    expect(fs.existsSync(svgPath)).toBe(false);
  });

  it('campaign card uses truthful Total Campaigns label matching total_items data', () => {
    const en = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../messages/en.json'), 'utf8'));
    const es = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../messages/es.json'), 'utf8'));

    expect(en.dashboard.metrics.total_campaigns).toBe('Total Campaigns');
    expect(es.dashboard.metrics.total_campaigns).toBe('Campañas Totales');
  });

  it('ICP section uses neutral non-ranking label without Top ICPs language', () => {
    const en = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../messages/en.json'), 'utf8'));
    const es = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../messages/es.json'), 'utf8'));

    expect(en.dashboard.top_icps).toBe('Ideal Customer Profiles');
    expect(en.dashboard.top_icps).not.toContain('Top');
    expect(en.dashboard.top_icps).not.toContain('Performing');

    expect(es.dashboard.top_icps).toBe('Perfiles de Cliente Ideal');
    expect(es.dashboard.top_icps).not.toContain('Mayor');
    expect(es.dashboard.top_icps).not.toContain('Rendimiento');
  });
});
