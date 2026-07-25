/**
 * Auth fixture for E2E tests.
 *
 * The Next.js middleware is bypassed via KORA_E2E_BYPASS_AUTH=true (set in
 * playwright.config.ts webServer env), so protected routes are reachable
 * without a real Supabase instance. The `authedPage` fixture is a plain page
 * that tests can use to add their own API route mocks on top.
 */
import { test as base, type Page } from '@playwright/test';

export const test = base.extend<{ authedPage: Page }>({
  authedPage: async ({ page }, use) => {
    await use(page);
  },
});

export { expect } from '@playwright/test';
