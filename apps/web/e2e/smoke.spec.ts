import { test, expect } from '@playwright/test';

test.describe('BopClients Web Shell E2E Smoke Flow', () => {
  test('login, navigate to dashboard, switch to Spanish, and logout', async ({ page }) => {
    let isLoggedIn = false;

    // Controlled fixture for /api/auth/login
    await page.route('**/api/auth/login', async (route) => {
      isLoggedIn = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: {
          'Set-Cookie': 'bop_access_token=mock-jwt-token; Path=/; HttpOnly; SameSite=Lax',
        },
        body: JSON.stringify({
          success: true,
          user: {
            id: 'usr-smoke-1',
            email: 'admin@bopclients.io',
            full_name: 'Lead Architect',
            locale: 'en',
          },
          active_organization: {
            id: 'org-1',
            bop_organization_id: 'bop_org_enterprise_alpha',
            name: 'Enterprise Alpha',
            slug: 'enterprise-alpha',
            role: 'MEMBER',
          },
          organizations: [
            {
              id: 'org-1',
              bop_organization_id: 'bop_org_enterprise_alpha',
              name: 'Enterprise Alpha',
              slug: 'enterprise-alpha',
              role: 'MEMBER',
            },
            {
              id: 'org-2',
              bop_organization_id: 'bop_org_beta_holdings',
              name: 'Beta Holdings',
              slug: 'beta-holdings',
              role: 'VIEWER',
            },
          ],
        }),
      });
    });

    // Controlled fixture for /api/auth/session (401 initially, 200 when logged in)
    await page.route('**/api/auth/session', async (route) => {
      if (!isLoggedIn) {
        await route.fulfill({
          status: 401,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Unauthenticated' }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            user: {
              id: 'usr-smoke-1',
              email: 'admin@bopclients.io',
              full_name: 'Lead Architect',
              locale: 'en',
            },
            active_organization: {
              id: 'org-1',
              bop_organization_id: 'bop_org_enterprise_alpha',
              name: 'Enterprise Alpha',
              slug: 'enterprise-alpha',
              role: 'MEMBER',
            },
            active_role: 'MEMBER',
            organizations: [
              {
                id: 'org-1',
                bop_organization_id: 'bop_org_enterprise_alpha',
                name: 'Enterprise Alpha',
                slug: 'enterprise-alpha',
                role: 'MEMBER',
              },
              {
                id: 'org-2',
                bop_organization_id: 'bop_org_beta_holdings',
                name: 'Beta Holdings',
                slug: 'beta-holdings',
                role: 'VIEWER',
              },
            ],
          }),
        });
      }
    });

    // Controlled fixture for backend proxy list calls
    await page.route('**/api/proxy/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0 }),
      });
    });

    // Controlled fixture for /api/auth/logout
    await page.route('**/api/auth/logout', async (route) => {
      isLoggedIn = false;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });

    test.setTimeout(60000);

    // 1. Visit /en/login
    await page.goto('/en/login');
    await expect(page.locator('h1')).toContainText('Sign In to BopClients');

    // 2. Fill login credentials
    const emailInput = page.locator('input[type="email"]');
    await emailInput.fill('admin@bopclients.io');
    await page.locator('input[type="password"]').fill('CorrectPassword123!');
    await page.locator('button[type="submit"]').click();

    // 3. Reach /en/dashboard
    await expect(page).toHaveURL(/.*\/en\/dashboard/);
    await expect(page.locator('h1')).toContainText('Executive Overview');

    // 4. Switch locale -> /es/dashboard
    const esButton = page.locator('button[aria-label="Cambiar a Español"]');
    await esButton.click();

    // 5. Verify Spanish UI text
    await expect(page).toHaveURL(/.*\/es\/dashboard/);
    await expect(page.locator('h1')).toContainText('Resumen Ejecutivo');
    await expect(page.locator('nav')).toContainText('Panel Principal');
    await expect(page.locator('nav')).toContainText('Prospectos');

    // 6. User menu & Logout
    const userAvatar = page.locator('header button[aria-haspopup="menu"]');
    await userAvatar.click();
    const logoutBtn = page.locator('button:has-text("Cerrar Sesión")');
    await logoutBtn.click();

    // 7. Return to login
    await expect(page).toHaveURL(/.*\/es\/login/);
    await expect(page.locator('h1')).toContainText('Iniciar Sesión en BopClients');
  });

  test('multi-tenant organization switching updates active tenant context', async ({ page }) => {
    let activeOrgBopId = 'bop_org_enterprise_alpha';

    await page.route('**/api/auth/session', async (route) => {
      const isAlpha = activeOrgBopId === 'bop_org_enterprise_alpha';
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: {
            id: 'usr-smoke-1',
            email: 'admin@bopclients.io',
            full_name: 'Lead Architect',
            locale: 'en',
          },
          active_organization: isAlpha
            ? {
                id: 'org-1',
                bop_organization_id: 'bop_org_enterprise_alpha',
                name: 'Enterprise Alpha',
                slug: 'enterprise-alpha',
                role: 'MEMBER',
              }
            : {
                id: 'org-2',
                bop_organization_id: 'bop_org_beta_holdings',
                name: 'Beta Holdings',
                slug: 'beta-holdings',
                role: 'VIEWER',
              },
          active_role: isAlpha ? 'MEMBER' : 'VIEWER',
          organizations: [
            {
              id: 'org-1',
              bop_organization_id: 'bop_org_enterprise_alpha',
              name: 'Enterprise Alpha',
              slug: 'enterprise-alpha',
              role: 'MEMBER',
            },
            {
              id: 'org-2',
              bop_organization_id: 'bop_org_beta_holdings',
              name: 'Beta Holdings',
              slug: 'beta-holdings',
              role: 'VIEWER',
            },
          ],
        }),
      });
    });

    await page.route('**/api/auth/switch-org', async (route) => {
      const data = JSON.parse(route.request().postData() || '{}');
      activeOrgBopId = data.bop_organization_id;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          active_organization: {
            id: 'org-2',
            bop_organization_id: 'bop_org_beta_holdings',
            name: 'Beta Holdings',
            slug: 'beta-holdings',
            role: 'VIEWER',
          },
        }),
      });
    });

    await page.route('**/api/proxy/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0 }),
      });
    });

    // Visit dashboard directly with active session
    await page.goto('/en/dashboard');
    await expect(page.locator('header')).toContainText('Enterprise Alpha');

    // Open organization switcher
    const orgSwitcher = page.locator('aside button[aria-haspopup="listbox"]');
    await orgSwitcher.click();

    // Select Beta Holdings
    const betaOption = page.locator('button:has-text("Beta Holdings")');
    await betaOption.click();

    // Verify header updates to Beta Holdings
    await expect(page.locator('header')).toContainText('Beta Holdings');
    await expect(page.locator('header')).toContainText('VIEWER');
  });

  test('research page loads and prospect signals modal queries valid routes without 404', async ({ page }) => {
    let researchApiCalled = false;
    let signalsApiCalled = false;
    let any404Occurred = false;

    // Track responses to assert no 404s
    page.on('response', (response) => {
      if (response.status() === 404 && response.url().includes('/api/')) {
        any404Occurred = true;
      }
    });

    // Session fixture
    await page.route('**/api/auth/session', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: {
            id: 'usr-smoke-1',
            email: 'admin@bopclients.io',
            full_name: 'Lead Architect',
            locale: 'en',
          },
          active_organization: {
            id: 'org-1',
            bop_organization_id: 'bop_org_enterprise_alpha',
            name: 'Enterprise Alpha',
            slug: 'enterprise-alpha',
            role: 'MEMBER',
          },
          active_role: 'MEMBER',
          organizations: [
            {
              id: 'org-1',
              bop_organization_id: 'bop_org_enterprise_alpha',
              name: 'Enterprise Alpha',
              slug: 'enterprise-alpha',
              role: 'MEMBER',
            },
          ],
        }),
      });
    });

    // Proxy routes fixtures
    await page.route('**/api/proxy/**', async (route) => {
      const url = route.request().url();

      if (url.includes('/research-runs')) {
        researchApiCalled = true;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [
              {
                id: 'run-123-abc',
                organization_id: 'bop_org_enterprise_alpha',
                status: 'completed',
                display_key: 'research.status.completed',
                created_at: new Date().toISOString(),
              },
            ],
            total_items: 1,
            total_pages: 1,
            page: 1,
            page_size: 10,
          }),
        });
        return;
      }

      if (url.includes('/signals')) {
        signalsApiCalled = true;
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
            {
              id: 'sig-001',
              prospect_id: 'pros-999',
              category: 'NEED',
              display_key: 'signal.category.need',
              signal_type: 'HIRING_EXPANSION',
              confidence: 0.95,
              headline: 'Hiring VP of Sales',
              summary: 'Enterprise expansion identified in North America',
              detected_at: new Date().toISOString(),
              created_at: new Date().toISOString(),
            },
          ]),
        });
        return;
      }

      if (url.includes('/prospects')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [
              {
                id: 'pros-999',
                organization_id: 'bop_org_enterprise_alpha',
                name: 'Apex Innovations',
                email: 'contact@apex.example.com',
                industry: 'Cloud Security',
                city: 'Austin',
                state: 'TX',
                country: 'US',
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              },
            ],
            total_items: 1,
            total_pages: 1,
            page: 1,
            page_size: 15,
          }),
        });
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total_items: 0, total_pages: 0, page: 1, page_size: 10 }),
      });
    });

    // 1. Visit Research page
    await page.goto('/en/research');
    await expect(page.locator('h1')).toContainText('Autonomous Research & Discovery');
    await expect(page.locator('text=Run ID: run-123-')).toBeVisible();
    expect(researchApiCalled).toBe(true);

    // 2. Visit Prospects page
    await page.goto('/en/prospects');
    await expect(page.locator('h1')).toContainText('Prospect Directory');
    await expect(page.locator('text=Apex Innovations')).toBeVisible();

    // 3. Open prospect modal and check signals
    const viewButton = page.locator('button:has-text("View")').first();
    await viewButton.click();

    // Expect modal to show signals
    await expect(page.locator('#modal-title')).toContainText('Apex Innovations');
    await expect(page.locator('text=Hiring VP of Sales')).toBeVisible();
    await expect(page.locator('text=95%')).toBeVisible();
    expect(signalsApiCalled).toBe(true);

    // 4. Assert zero API 404s occurred
    expect(any404Occurred).toBe(false);
  });

  test('p21 primary product flow: full 25-step lifecycle from login to discovery, dossier and logout', async ({ page }) => {
    let isLoggedIn = false;
    const icps: any[] = [];
    const targetMarkets: any[] = [];
    const campaigns: any[] = [];

    // 1. Auth routes
    await page.route('**/api/auth/login', async (route) => {
      isLoggedIn = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: {
          'Set-Cookie': 'bop_access_token=mock-jwt-token; Path=/; HttpOnly; SameSite=Lax',
        },
        body: JSON.stringify({
          success: true,
          user: {
            id: 'usr-p21-admin',
            email: 'admin@bopclients.io',
            full_name: 'Lead Architect',
            locale: 'en',
          },
          active_organization: {
            id: 'org-1',
            bop_organization_id: 'bop_org_enterprise_alpha',
            name: 'Enterprise Alpha',
            slug: 'enterprise-alpha',
            role: 'MEMBER',
          },
          organizations: [
            {
              id: 'org-1',
              bop_organization_id: 'bop_org_enterprise_alpha',
              name: 'Enterprise Alpha',
              slug: 'enterprise-alpha',
              role: 'MEMBER',
            },
          ],
        }),
      });
    });

    await page.route('**/api/auth/session', async (route) => {
      if (!isLoggedIn) {
        await route.fulfill({
          status: 401,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Unauthenticated' }),
        });
      } else {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            user: {
              id: 'usr-p21-admin',
              email: 'admin@bopclients.io',
              full_name: 'Lead Architect',
              locale: 'en',
            },
            active_organization: {
              id: 'org-1',
              bop_organization_id: 'bop_org_enterprise_alpha',
              name: 'Enterprise Alpha',
              slug: 'enterprise-alpha',
              role: 'MEMBER',
            },
            active_role: 'MEMBER',
            organizations: [
              {
                id: 'org-1',
                bop_organization_id: 'bop_org_enterprise_alpha',
                name: 'Enterprise Alpha',
                slug: 'enterprise-alpha',
                role: 'MEMBER',
              },
            ],
          }),
        });
      }
    });

    await page.route('**/api/auth/logout', async (route) => {
      isLoggedIn = false;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true }),
      });
    });

    // 2. Proxy routes
    await page.route('**/api/proxy/**', async (route) => {
      const url = route.request().url();
      const method = route.request().method();

      // ICPs
      if (url.includes('/api/v1/icps')) {
        if (method === 'POST') {
          const body = JSON.parse(route.request().postData() || '{}');
          const newIcp = {
            id: 'icp-mock-1',
            organization_id: 'bop_org_enterprise_alpha',
            name: body.name,
            description: body.description,
            industries: body.industries || ['safety', 'distribution'],
            company_sizes: body.company_sizes || ['11-50'],
            countries: body.countries || ['US'],
            decision_maker_roles: body.decision_maker_roles || ['CEO'],
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          };
          icps.push(newIcp);
          await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(newIcp) });
          return;
        }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ items: icps, total_items: icps.length, total_pages: 1, page: 1, page_size: 25 }),
        });
        return;
      }

      // Target Markets
      if (url.includes('/api/v1/target-markets')) {
        if (method === 'POST') {
          const body = JSON.parse(route.request().postData() || '{}');
          const newTm = {
            id: 'tm-mock-1',
            icp_id: body.icp_id || 'icp-mock-1',
            country: body.country,
            region: body.region,
            city: body.city,
            postal_code: body.postal_code,
            radius_miles: body.radius_miles,
            language: body.language || 'en',
            created_at: new Date().toISOString(),
          };
          targetMarkets.push(newTm);
          await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(newTm) });
          return;
        }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ items: targetMarkets, total_items: targetMarkets.length, total_pages: 1, page: 1, page_size: 25 }),
        });
        return;
      }

      // Campaigns
      if (url.includes('/api/v1/campaigns')) {
        if (method === 'POST') {
          const body = JSON.parse(route.request().postData() || '{}');
          const newCamp = {
            id: 'camp-p21-alpha',
            organization_id: 'bop_org_enterprise_alpha',
            name: body.name,
            description: body.description,
            icp_id: body.icp_id,
            status: body.status || 'active',
            display_key: 'campaign.active',
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          };
          campaigns.push(newCamp);
          await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(newCamp) });
          return;
        }
        if (method === 'PATCH') {
          const body = JSON.parse(route.request().postData() || '{}');
          if (campaigns.length > 0) {
            Object.assign(campaigns[0], body);
          }
          await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(campaigns[0] || {}) });
          return;
        }
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ items: campaigns, total_items: campaigns.length, total_pages: 1, page: 1, page_size: 10 }),
        });
        return;
      }

      // Discovery Intents
      if (url.includes('/api/v1/discovery/intents')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            organization_id: 'bop_org_enterprise_alpha',
            campaign_id: 'camp-p21-alpha',
            raw_query: 'Texas industrial safety distributors',
            industries: ['Safety Equipment', 'Distribution'],
            business_categories: ['Industrial Supply'],
            countries: ['US'],
            regions: ['TX'],
            cities: ['Austin', 'Dallas'],
            languages: ['en'],
            company_size_min: 10,
            company_size_max: 200,
            keywords: ['safety', 'distribution', 'warehouse'],
            max_results: 50,
          }),
        });
        return;
      }

      // Discovery Plans
      if (url.includes('/api/v1/discovery/plans')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            organization_id: 'bop_org_enterprise_alpha',
            campaign_id: 'camp-p21-alpha',
            tasks: [
              {
                task_id: 'task-mock-1',
                provider: 'forge_discovery',
                query_params: {
                  query: 'Texas industrial safety distributors',
                  city: 'Austin',
                  region: 'TX',
                  country: 'US',
                  limit: 25,
                },
                priority: 1,
                status: 'pending',
                estimated_items: 25,
              },
            ],
            warnings: [],
            estimated_total_cost_credits: 0.0,
            generated_at: new Date().toISOString(),
          }),
        });
        return;
      }

      // Discovery Execute
      if (url.includes('/api/v1/discovery/execute')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'completed',
            campaign_id: 'camp-p21-alpha',
            tasks_executed: 1,
            tasks_succeeded: 1,
            tasks_failed: 0,
            discovered_businesses_count: 5,
            prospects_created: 4,
            prospects_reused: 1,
            total_imported_prospects: 5,
            imported_prospects: [
              {
                id: 'pros-texas-1',
                name: 'Lone Star Safety Supplies',
                website_url: 'https://lonestarsafety.example.com',
                city: 'Austin',
                state: 'TX',
                country: 'US',
                industry: 'Safety Equipment',
                source: 'forge_discovery',
              },
            ],
            errors: [],
          }),
        });
        return;
      }

      // Prospect Intelligence
      if (url.includes('/api/v1/prospects/pros-texas-1/intelligence')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            prospect_id: 'pros-texas-1',
            summary_text: 'Lone Star Safety Supplies is an established distributor of PPE and warehouse safety equipment across central Texas.',
            key_insights: [
              'Actively expanding regional warehouse operations',
              'Strong compliance alignment with industrial safety standards',
            ],
            recommended_angle: 'Offer bulk distribution automation and vendor catalog integration.',
            generated_at: new Date().toISOString(),
          }),
        });
        return;
      }

      // Prospect Signals
      if (url.includes('/api/v1/prospects/pros-texas-1/signals')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
            {
              id: 'sig-tx-1',
              prospect_id: 'pros-texas-1',
              category: 'hiring',
              display_key: 'signal.hiring',
              signal_type: 'job_posting',
              confidence: 0.92,
              headline: 'Expanding warehouse operations in Austin',
              summary: 'Seeking 5 new warehouse supervisors and safety compliance officers',
              detected_at: new Date().toISOString(),
              created_at: new Date().toISOString(),
            },
          ]),
        });
        return;
      }

      // Prospect Lead Score
      if (url.includes('/api/v1/prospects/pros-texas-1/score')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            prospect_id: 'pros-texas-1',
            organization_id: 'bop_org_enterprise_alpha',
            score: 88.0,
            explanation: 'Strong match for Texas industrial distribution ICP with active hiring triggers.',
            confidence: 0.95,
            calculated_at: new Date().toISOString(),
          }),
        });
        return;
      }

      // Prospect Priority
      if (url.includes('/api/v1/prospects/pros-texas-1/priority')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            prospect_id: 'pros-texas-1',
            organization_id: 'bop_org_enterprise_alpha',
            tier: 'urgent',
            score: 92.0,
            reasons: ['Recent expansion signal detected', 'High ICP commercial fit'],
            updated_at: new Date().toISOString(),
          }),
        });
        return;
      }

      // Prospect Research Trigger
      if (url.includes('/api/v1/prospects/pros-texas-1/research') && method === 'POST') {
        await route.fulfill({
          status: 202,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'run-mock-texas-1',
            organization_id: 'bop_org_enterprise_alpha',
            prospect_id: 'pros-texas-1',
            run_type: 'full_diligence',
            status: 'pending',
            display_key: 'research.status.pending',
            created_at: new Date().toISOString(),
          }),
        });
        return;
      }

      // Prospect Detail View
      if (url.includes('/api/v1/prospects/pros-texas-1')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            prospect: {
              id: 'pros-texas-1',
              organization_id: 'bop_org_enterprise_alpha',
              name: 'Lone Star Safety Supplies',
              website_url: 'https://lonestarsafety.example.com',
              phone: '+1 512 555 0199',
              email: 'sales@lonestarsafety.example.com',
              city: 'Austin',
              state: 'TX',
              country: 'US',
              industry: 'Safety Equipment',
              source: 'forge_discovery',
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            },
            campaign_associations: [
              {
                id: 'cp-mock-1',
                campaign_id: 'camp-p21-alpha',
                campaign_name: 'Texas Industrial Safety Q3',
                status: 'added',
                priority: 1,
                added_at: new Date().toISOString(),
              },
            ],
            lead_score: {
              score: 88.0,
              confidence: 0.95,
              calculated_at: new Date().toISOString(),
            },
            priority: {
              tier: 'urgent',
              score: 92.0,
              reasons: ['Recent expansion signal detected', 'High ICP commercial fit'],
              updated_at: new Date().toISOString(),
            },
            intelligence_summary: {
              summary_text: 'Lone Star Safety Supplies is an established distributor of PPE and warehouse safety equipment across central Texas.',
              key_insights: [
                'Actively expanding regional warehouse operations',
                'Strong compliance alignment with industrial safety standards',
              ],
              recommended_angle: 'Offer bulk distribution automation and vendor catalog integration.',
              generated_at: new Date().toISOString(),
            },
            recent_signals: [
              {
                id: 'sig-tx-1',
                category: 'hiring',
                display_key: 'signal.hiring',
                signal_type: 'job_posting',
                confidence: 0.92,
                headline: 'Expanding warehouse operations in Austin',
                detected_at: new Date().toISOString(),
              },
            ],
          }),
        });
        return;
      }

      // Default fallback
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total_items: 0, total_pages: 0, page: 1, page_size: 10 }),
      });
    });

    test.setTimeout(60000);

    // 1. Login
    await page.goto('/en/login');
    await expect(page.locator('h1')).toContainText('Sign In to BopClients');
    await page.locator('input[type="email"]').fill('admin@bopclients.io');
    await page.locator('input[type="password"]').fill('CorrectPassword123!');
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/.*\/en\/dashboard/);

    // 2. Navigate to ICPs
    await page.goto('/en/icps');
    await expect(page.locator('h1')).toContainText('Ideal Customer Profiles');

    // 3. Create a real test ICP via UI
    await page.locator('button:has-text("Create ICP")').first().click();
    await page.locator('input[placeholder*="Enterprise Safety"]').fill('Enterprise Safety ICP');
    await page.locator('textarea').fill('Regional industrial safety distributors');
    await page.locator('button[type="submit"]').click();

    // 4. Verify saved ICP appears
    await expect(page.locator('text=Enterprise Safety ICP')).toBeVisible();

    // 5. Navigate to Target Markets
    await page.goto('/en/target-markets');
    await expect(page.locator('h1')).toContainText('Target Markets');

    // 6. Create a Target Market via UI
    await page.locator('button:has-text("Create Target Market")').first().click();

    // 7. Associate it with the created ICP if actual model supports this
    const tmIcpSelect = page.locator('form select').first();
    if (await tmIcpSelect.isVisible()) {
      await tmIcpSelect.selectOption({ label: 'Enterprise Safety ICP' });
    }
    await page.locator('input[placeholder="Miami"]').fill('Miami');
    await page.locator('input[placeholder="FL"]').fill('FL');
    await page.locator('button[type="submit"]').click();

    // 8. Verify saved Target Market appears
    await expect(page.locator('text=Miami')).toBeVisible();

    // 9. Navigate to Campaigns
    await page.goto('/en/campaigns');
    await expect(page.locator('h1')).toContainText('Prospecting Campaigns');

    // 10. Create Campaign using actual valid relationships
    await page.locator('button:has-text("New Campaign")').first().click();
    await page.locator('input[placeholder*="Safety Distributors"]').fill('Texas Industrial Safety Q3');
    const campIcpSelect = page.locator('form select').first();
    if (await campIcpSelect.isVisible()) {
      await campIcpSelect.selectOption({ label: 'Enterprise Safety ICP' });
    }

    // 11. Put Campaign into the valid ACTIVE state needed for discovery
    await page.locator('form select').nth(1).selectOption('active');
    await page.locator('button[type="submit"]').click();
    await expect(page.locator('text=Texas Industrial Safety Q3')).toBeVisible();
    await expect(page.getByText('active', { exact: true })).toBeVisible();

    // 12. Navigate to Discovery
    await page.goto('/en/discovery');
    await expect(page.locator('h1')).toContainText('Prospect Discovery');

    // 13. Enter natural-language prospect request
    await page.locator('textarea').fill('Texas industrial safety distributors');

    // 14. Generate/preview SearchIntent/SearchPlan
    await page.locator('button:has-text("Parse Search Intent")').click();
    await expect(page.locator('text=1. Parsed Search Intent Preview')).toBeVisible();
    await expect(page.locator('text=Safety Equipment')).toBeVisible();
    await page.locator('button:has-text("Generate Search Plan")').click();
    await expect(page.locator('text=2. Search Plan Preview')).toBeVisible();
    await expect(page.locator('text=1 Discovery Tasks')).toBeVisible();

    // 15. Execute deterministic fixture discovery
    await page.locator('button:has-text("Run Discovery")').click();
    await expect(page.locator('text=3. Discovery & Import Results')).toBeVisible();

    // 16. Verify truthful imported/reused counts
    await expect(page.locator('text=New Prospects Created')).toBeVisible();
    await expect(page.locator('text=Existing Prospects Reused')).toBeVisible();
    await expect(page.locator('text=Total Prospects Imported')).toBeVisible();
    await expect(page.locator('text=Lone Star Safety Supplies')).toBeVisible();

    // 17. Open resulting Campaign Prospect
    const prospectRowLink = page.locator('a:has-text("Lone Star Safety Supplies")');
    await expect(prospectRowLink).toBeVisible();
    await prospectRowLink.click();

    // 18. Open Prospect Dossier
    await expect(page).toHaveURL(/.*\/en\/prospects\/pros-texas-1/);
    await expect(page.locator('h1')).toContainText('Lone Star Safety Supplies');

    // 19. Verify campaign context is dynamic, not hardcoded
    await expect(page.locator('text=Texas Industrial Safety Q3')).toBeVisible();

    // 20. Trigger controlled Research
    const researchBtn = page.locator('button:has-text("Research Prospect")');
    await expect(researchBtn).toBeVisible();
    await researchBtn.click();
    await expect(page.locator('text=Research run queued successfully')).toBeVisible();

    // 21. Verify Intelligence
    await expect(page.locator('text=Synthesized Intelligence')).toBeVisible();
    await expect(page.locator('text=Observed (Verified Direct Fact)')).toBeVisible();

    // 22. Verify Signals
    await expect(page.locator('text=Detected Opportunity Signals')).toBeVisible();
    await expect(page.locator('text=Expanding warehouse operations in Austin')).toBeVisible();

    // 23. Verify Lead Score
    await expect(page.locator('text=Lead Qualification Score')).toBeVisible();
    await expect(page.locator('text=88')).toBeVisible();

    // 24. Verify Priority
    await expect(page.locator('text=Outreach Priority')).toBeVisible();
    await expect(page.locator('text=URGENT')).toBeVisible();

    // 25. Logout
    const userAvatar = page.locator('header button[aria-haspopup="menu"]');
    await userAvatar.click();
    const logoutBtn = page.locator('button:has-text("Sign Out")');
    await logoutBtn.click();
    await expect(page).toHaveURL(/.*\/en\/login/);
    await expect(page.locator('h1')).toContainText('Sign In to BopClients');
  });

  test('p21 spanish product workflow: full discovery and dossier in spanish locale', async ({ page }) => {
    // Session setup in Spanish
    await page.route('**/api/auth/session', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: {
            id: 'usr-p21-es',
            email: 'es_user@bopclients.io',
            full_name: 'Operador en Español',
            locale: 'es',
          },
          active_organization: {
            id: 'org-1',
            bop_organization_id: 'bop_org_enterprise_alpha',
            name: 'Enterprise Alpha',
            slug: 'enterprise-alpha',
            role: 'MEMBER',
          },
          active_role: 'MEMBER',
          organizations: [
            {
              id: 'org-1',
              bop_organization_id: 'bop_org_enterprise_alpha',
              name: 'Enterprise Alpha',
              slug: 'enterprise-alpha',
              role: 'MEMBER',
            },
          ],
        }),
      });
    });

    // Mock API proxy routes for Spanish workflow
    await page.route('**/api/proxy/**', async (route) => {
      const url = route.request().url();
      const method = route.request().method();

      if (url.includes('/api/v1/campaigns')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [
              {
                id: 'camp-p21-es',
                organization_id: 'bop_org_enterprise_alpha',
                name: 'Campaña de Seguridad Industrial',
                description: 'Pipeline regional de distribuidores',
                status: 'active',
                display_key: 'campaign.active',
                created_at: new Date().toISOString(),
                updated_at: new Date().toISOString(),
              },
            ],
            total_items: 1,
            total_pages: 1,
            page: 1,
            page_size: 10,
          }),
        });
        return;
      }

      if (url.includes('/api/v1/discovery/intents')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            organization_id: 'bop_org_enterprise_alpha',
            campaign_id: 'camp-p21-es',
            raw_query: 'Distribuidores de seguridad industrial en Texas',
            industries: ['Equipos de Seguridad', 'Distribución'],
            business_categories: ['Suministros Industriales'],
            countries: ['US'],
            regions: ['TX'],
            cities: ['Austin', 'Dallas'],
            languages: ['es', 'en'],
            company_size_min: 10,
            company_size_max: 200,
            keywords: ['seguridad', 'distribución', 'almacén'],
            max_results: 50,
          }),
        });
        return;
      }

      if (url.includes('/api/v1/discovery/plans')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            organization_id: 'bop_org_enterprise_alpha',
            campaign_id: 'camp-p21-es',
            tasks: [
              {
                task_id: 'task-mock-es-1',
                provider: 'forge_discovery',
                query_params: {
                  query: 'Distribuidores de seguridad industrial en Texas',
                  city: 'Austin',
                  region: 'TX',
                  country: 'US',
                  limit: 25,
                },
                priority: 1,
                status: 'pending',
                estimated_items: 25,
              },
            ],
            warnings: [],
            estimated_total_cost_credits: 0.0,
            generated_at: new Date().toISOString(),
          }),
        });
        return;
      }

      if (url.includes('/api/v1/discovery/execute')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            status: 'completed',
            campaign_id: 'camp-p21-es',
            tasks_executed: 1,
            tasks_succeeded: 1,
            tasks_failed: 0,
            discovered_businesses_count: 5,
            prospects_created: 4,
            prospects_reused: 1,
            total_imported_prospects: 5,
            imported_prospects: [
              {
                id: 'pros-texas-1',
                name: 'Lone Star Safety Supplies',
                website_url: 'https://lonestarsafety.example.com',
                city: 'Austin',
                state: 'TX',
                country: 'US',
                industry: 'Equipos de Seguridad',
                source: 'forge_discovery',
              },
            ],
            errors: [],
          }),
        });
        return;
      }

      if (url.includes('/api/v1/prospects/pros-texas-1/signals')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([
            {
              id: 'sig-es-1',
              prospect_id: 'pros-texas-1',
              category: 'hiring',
              display_key: 'signal.hiring',
              signal_type: 'job_posting',
              confidence: 0.92,
              headline: 'Expansión de operaciones de almacén en Austin',
              summary: 'Contratando personal de seguridad y supervisores',
              detected_at: new Date().toISOString(),
              created_at: new Date().toISOString(),
            },
          ]),
        });
        return;
      }

      if (url.includes('/api/v1/prospects/pros-texas-1/score')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            prospect_id: 'pros-texas-1',
            organization_id: 'bop_org_enterprise_alpha',
            score: 88.0,
            explanation: 'Fuerte coincidencia con ICP de distribución.',
            confidence: 0.95,
            calculated_at: new Date().toISOString(),
          }),
        });
        return;
      }

      if (url.includes('/api/v1/prospects/pros-texas-1/priority')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            prospect_id: 'pros-texas-1',
            organization_id: 'bop_org_enterprise_alpha',
            tier: 'urgent',
            score: 92.0,
            reasons: ['Señal de expansión detectada'],
            updated_at: new Date().toISOString(),
          }),
        });
        return;
      }

      if (url.includes('/api/v1/prospects/pros-texas-1/research') && method === 'POST') {
        await route.fulfill({
          status: 202,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'run-mock-es-1',
            organization_id: 'bop_org_enterprise_alpha',
            prospect_id: 'pros-texas-1',
            run_type: 'full_diligence',
            status: 'pending',
            display_key: 'research.status.pending',
            created_at: new Date().toISOString(),
          }),
        });
        return;
      }

      if (url.includes('/api/v1/prospects/pros-texas-1')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            prospect: {
              id: 'pros-texas-1',
              organization_id: 'bop_org_enterprise_alpha',
              name: 'Lone Star Safety Supplies',
              website_url: 'https://lonestarsafety.example.com',
              phone: '+1 512 555 0199',
              email: 'ventas@lonestarsafety.example.com',
              city: 'Austin',
              state: 'TX',
              country: 'US',
              industry: 'Equipos de Seguridad',
              source: 'forge_discovery',
              created_at: new Date().toISOString(),
              updated_at: new Date().toISOString(),
            },
            campaign_associations: [
              {
                id: 'cp-mock-es-1',
                campaign_id: 'camp-p21-es',
                campaign_name: 'Campaña de Seguridad Industrial',
                status: 'added',
                priority: 1,
                added_at: new Date().toISOString(),
              },
            ],
            lead_score: {
              score: 88.0,
              confidence: 0.95,
              calculated_at: new Date().toISOString(),
            },
            priority: {
              tier: 'urgent',
              score: 92.0,
              reasons: ['Señal de expansión detectada'],
              updated_at: new Date().toISOString(),
            },
            intelligence_summary: {
              summary_text: 'Lone Star Safety Supplies es un distribuidor líder de equipos de seguridad en Texas.',
              key_insights: ['Expansión de almacenes activa en Austin'],
              recommended_angle: 'Ofrecer automatización de catálogo y abastecimiento.',
              generated_at: new Date().toISOString(),
            },
            recent_signals: [
              {
                id: 'sig-es-1',
                category: 'hiring',
                display_key: 'signal.hiring',
                signal_type: 'job_posting',
                confidence: 0.92,
                headline: 'Expansión de operaciones de almacén en Austin',
                detected_at: new Date().toISOString(),
              },
            ],
          }),
        });
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total_items: 0, total_pages: 0, page: 1, page_size: 10 }),
      });
    });

    test.setTimeout(60000);

    // 1. Visit Spanish Discovery page
    await page.goto('/es/discovery');
    await expect(page.locator('h1')).toContainText('Descubrimiento de Prospectos');

    // 2. Fill prompt in Spanish and parse intent
    await page.locator('textarea').fill('Distribuidores de seguridad industrial en Texas');
    await page.locator('button:has-text("Interpretar Intención de Búsqueda")').click();

    // 3. Verify Spanish Intent Preview
    await expect(page.locator('text=1. Vista Previa de la Intención de Búsqueda')).toBeVisible();
    await expect(page.locator('text=Equipos de Seguridad')).toBeVisible();

    // 4. Generate Plan
    await page.locator('button:has-text("Generar Plan de Búsqueda")').click();
    await expect(page.locator('text=2. Vista Previa del Plan de Búsqueda')).toBeVisible();
    await expect(page.locator('text=1 Tareas de Descubrimiento')).toBeVisible();

    // 5. Execute Discovery
    await page.locator('button:has-text("Ejecutar Descubrimiento")').click();
    await expect(page.locator('text=3. Resultados de Descubrimiento e Importación')).toBeVisible();
    await expect(page.locator('text=Nuevos Prospectos Creados')).toBeVisible();
    await expect(page.locator('text=Prospectos Existentes Reutilizados')).toBeVisible();
    await expect(page.locator('text=Lone Star Safety Supplies')).toBeVisible();

    // 6. Navigate to Prospect Dossier in Spanish
    await page.goto('/es/prospects/pros-texas-1');
    await expect(page.locator('h1')).toContainText('Lone Star Safety Supplies');
    await expect(page.locator('text=Calificación de Prospecto')).toBeVisible();
    await expect(page.locator('text=88')).toBeVisible();
    await expect(page.locator('text=URGENTE')).toBeVisible();
    await expect(page.locator('text=Señales de Oportunidad Detectadas')).toBeVisible();
    await expect(page.locator('text=Inteligencia Sintetizada')).toBeVisible();

    // 7. Trigger Research in Spanish
    const researchBtn = page.locator('button:has-text("Investigar Prospecto")');
    await expect(researchBtn).toBeVisible();
    await researchBtn.click();
    await expect(page.locator('text=Ejecución de investigación puesta en cola exitosamente.')).toBeVisible();

    // 8. Assert no untranslated translation keys leak onto the page
    const bodyText = await page.innerText('body');
    expect(bodyText).not.toContain('discovery.');
    expect(bodyText).not.toContain('prospect_detail.');
  });
});
