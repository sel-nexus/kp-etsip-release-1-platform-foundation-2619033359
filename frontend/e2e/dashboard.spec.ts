import { test, expect } from '@playwright/test';

test('executive views and filters real dashboard measures', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/login');
  await page.getByLabel('Email').fill(process.env.E2E_EXECUTIVE_EMAIL ?? 'executive@ketsip.local');
  await page.getByLabel('Password').fill(process.env.E2E_DEMO_PASSWORD ?? 'LocalDemo123!');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('link', { name: 'Dashboard' })).toBeVisible();
  await page.getByRole('link', { name: 'Applications' }).click();
  const initialResponse = page.waitForResponse(response => response.url().includes('/api/dashboard/executive') && response.status() === 200);
  await page.getByRole('link', { name: 'Dashboard' }).click();
  const initial = await (await initialResponse).json();
  await expect(page.getByRole('heading', { name: 'Executive Dashboard' })).toBeVisible();
  const metrics = page.getByRole('region', { name: 'Executive metrics' });
  await expect(metrics.locator('div').filter({ hasText: 'Total Applications' })).toContainText(String(initial.totalApplications));
  await expect(metrics.locator('div').filter({ hasText: 'Total Portfolios' })).toContainText(String(initial.totalPortfolios));
  await expect(page.getByText(/manually maintained/)).toBeVisible();
  if (initial.portfolios.length) {
    await expect(page.getByRole('region', { name: 'Portfolio Quality Score' }).getByText(initial.portfolios[0].name, { exact: true })).toBeVisible();
    await expect(page.getByRole('region', { name: 'Applications at Risk by Portfolio' }).getByText(initial.portfolios[0].name, { exact: true })).toBeVisible();
  }
  const filteredResponse = page.waitForResponse(response => response.url().includes('/api/dashboard/executive?') && response.url().includes('riskLevel=High') && response.status() === 200);
  await page.getByLabel('Risk level').selectOption('High');
  const filtered = await (await filteredResponse).json();
  await expect(metrics.locator('div').filter({ hasText: 'Total Applications' })).toContainText(String(filtered.totalApplications));
  await expect(metrics.locator('div').filter({ hasText: 'Applications at Risk' })).toContainText(String(filtered.applicationsAtRisk));
  expect(filtered.applicationsAtRisk).toBe(filtered.totalApplications);
  expect(errors).toEqual([]);
});
