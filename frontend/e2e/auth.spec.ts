import { test, expect } from '@playwright/test';

test('live sign-in, preference persistence and sign-out', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/login');
  await page.getByLabel('Email').fill(process.env.E2E_EMAIL ?? 'engineer@ketsip.local');
  await page.getByLabel('Password').fill(process.env.E2E_PASSWORD ?? 'LocalDemo123!');
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Sign in' }).click();
  expect((await login).status()).toBe(200);
  await page.getByRole('link', {name: 'My profile'}).click();
  await expect(page.getByText('Demo Engineer')).toBeVisible();
  await page.getByLabel('Default landing page').selectOption('dashboard');
  await page.getByRole('button', {name: 'Save preference'}).click();
  await expect(page.getByRole('status')).toContainText('Preference saved');
  await page.reload();
  await expect(page.getByLabel('Default landing page')).toHaveValue('dashboard');
  await page.getByRole('button', {name: 'Sign out'}).click();
  await expect(page.getByRole('heading', {name:'Sign in'})).toBeVisible();
  expect(errors).toEqual([]);
});
