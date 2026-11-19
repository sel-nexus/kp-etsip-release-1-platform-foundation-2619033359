import { test, expect } from '@playwright/test';

test('auditor sees actual login activity, filters to no results and exports audit CSV', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/login');
  await page.getByLabel('Email').fill('auditor@ketsip.local');
  await page.getByLabel('Password').fill(process.env.E2E_DEMO_PASSWORD ?? 'LocalDemo123!');
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Sign in' }).click();
  expect((await login).status()).toBe(200);
  const auditResponse = page.waitForResponse(response => response.url().includes('/api/audit-logs') && response.status() === 200);
  await page.getByRole('link', { name: 'Audit log' }).click();
  const audit = await (await auditResponse).json();
  expect(audit.total).toBeGreaterThan(0);
  await expect(page.getByRole('region', { name: 'Audit results' })).toContainText(`${audit.total} events`);
  await expect(page.getByRole('region', { name: 'Audit results' })).toContainText(audit.items[0].userName);
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export CSV' }).click();
  expect((await download).suggestedFilename()).toBe('audit.csv');
  const noResults = page.waitForResponse(response => response.url().includes('/api/audit-logs') && response.url().includes('action=never-exists-e2e') && response.status() === 200);
  await page.getByLabel('Action').fill('never-exists-e2e');
  const filtered = await (await noResults).json();
  expect(filtered.total).toBe(0);
  await expect(page.getByText('No events match these filters.')).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('audit-empty.png'), fullPage: true });
  expect(errors).toEqual([]);
});