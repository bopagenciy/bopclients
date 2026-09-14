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
});
