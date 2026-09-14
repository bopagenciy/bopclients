import { describe, it, expect } from 'vitest';
import openApiSchema from '../openapi_p19.json';

describe('BopClients Frontend <-> P19 OpenAPI Contract Fidelity', () => {
  const openApiPaths = Object.keys(openApiSchema.paths);

  // List of all backend endpoints invoked across apps/web
  const frontendApiRoutes: { path: string; method: 'get' | 'post' | 'patch' | 'delete'; component: string }[] = [
    { path: '/api/v1/auth/login', method: 'post', component: 'app/api/auth/login/route.ts' },
    { path: '/api/v1/auth/logout', method: 'post', component: 'app/api/auth/logout/route.ts' },
    { path: '/api/v1/auth/refresh', method: 'post', component: 'app/api/auth/refresh/route.ts & proxy auto-refresh' },
    { path: '/api/v1/me', method: 'get', component: 'app/api/auth/session & switch-org' },
    { path: '/api/v1/me/organizations', method: 'get', component: 'app/api/auth/login/route.ts' },
    { path: '/api/v1/me/preferences', method: 'patch', component: 'components/navigation/LocaleSwitcher.tsx' },
    { path: '/api/v1/campaigns', method: 'get', component: 'app/[locale]/(app)/campaigns/page.tsx' },
    { path: '/api/v1/campaigns', method: 'post', component: 'app/[locale]/(app)/campaigns/page.tsx' },
    { path: '/api/v1/icps', method: 'get', component: 'app/[locale]/(app)/icps/page.tsx & dashboard' },
    { path: '/api/v1/target-markets', method: 'get', component: 'app/[locale]/(app)/target-markets/page.tsx & dashboard' },
    { path: '/api/v1/prospects', method: 'get', component: 'app/[locale]/(app)/prospects/page.tsx & dashboard' },
    { path: '/api/v1/prospects/{prospect_id}/signals', method: 'get', component: 'app/[locale]/(app)/prospects/page.tsx modal' },
    { path: '/api/v1/research-runs', method: 'get', component: 'app/[locale]/(app)/research/page.tsx' },
    { path: '/api/v1/monitoring/overview', method: 'get', component: 'app/[locale]/(app)/monitoring/page.tsx' },
    { path: '/api/v1/monitoring/health', method: 'get', component: 'app/[locale]/(app)/monitoring/page.tsx' },
    { path: '/api/v1/integrations/destinations', method: 'get', component: 'app/[locale]/(app)/integrations/page.tsx' },
  ];

  it('all frontend API route templates must exist in P19 OpenAPI specification', () => {
    for (const route of frontendApiRoutes) {
      const exists = openApiPaths.includes(route.path);
      expect(exists, `Route ${route.method.toUpperCase()} ${route.path} used in ${route.component} does not exist in OpenAPI schema`).toBe(true);

      const pathSpec = (openApiSchema.paths as any)[route.path];
      expect(pathSpec, `Missing path spec for ${route.path}`).toBeDefined();
      expect(pathSpec[route.method], `Method ${route.method.toUpperCase()} not allowed on ${route.path} in OpenAPI`).toBeDefined();
    }
  });

  it('prospect signals endpoint uses canonical path in P19 OpenAPI', () => {
    expect(openApiPaths).toContain('/api/v1/prospects/{prospect_id}/signals');
    const signalsPath = (openApiSchema.paths as any)['/api/v1/prospects/{prospect_id}/signals'];
    expect(signalsPath.get).toBeDefined();
    expect(signalsPath.get.summary).toBe('List signals for a specific prospect');
  });

  it('research runs endpoint uses canonical path in P19 OpenAPI', () => {
    expect(openApiPaths).toContain('/api/v1/research-runs');
    const researchPath = (openApiSchema.paths as any)['/api/v1/research-runs'];
    expect(researchPath.get).toBeDefined();
    expect(researchPath.get.summary).toBe('List tenant research runs');
  });

  it('monitoring endpoints exist and match overview and health paths', () => {
    expect(openApiPaths).toContain('/api/v1/monitoring/overview');
    expect(openApiPaths).toContain('/api/v1/monitoring/health');
  });

  it('zero calls to non-existent P19 routes', () => {
    const nonexistent = frontendApiRoutes.filter((r) => !openApiPaths.includes(r.path));
    expect(nonexistent.length).toBe(0);
  });
});
