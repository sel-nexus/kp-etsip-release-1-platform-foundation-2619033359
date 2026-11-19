import { test, expect } from '@playwright/test';

test('profile shows backend identity and persists a landing preference', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/login');
  await page.getByLabel('Email').fill('readonly@ketsip.local');
  await page.getByLabel('Password').fill(process.env.E2E_DEMO_PASSWORD ?? 'LocalDemo123!');
  const login = page.waitForResponse(response => response.url().endsWith('/api/auth/login') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Sign in' }).click();
  const response = await login;
  expect(response.status()).toBe(200);
  const { user } = await response.json();
  await page.getByRole('link', { name: 'My profile' }).click();
  await expect(page.getByText(user.name, { exact: true })).toBeVisible();
  await expect(page.getByText(user.email, { exact: true })).toBeVisible();
  await page.getByLabel('Default landing page').selectOption('dashboard');
  const save = page.waitForResponse(response => response.url().endsWith('/api/profile/preferences') && response.request().method() === 'PUT');
  await page.getByRole('button', { name: 'Save preference' }).click();
  expect((await save).status()).toBe(200);
  await expect(page.getByText('Preference saved.')).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('Default landing page')).toHaveValue('dashboard');
  await page.screenshot({ path: testInfo.outputPath('profile.png'), fullPage: true });
  expect(errors).toEqual([]);
});

test('unauthenticated access redirects to sign in and invalid input is explained on mobile', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/profile');
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible();
  await page.getByLabel('Email').fill('not-an-email');
  await page.getByLabel('Password').fill('invalid-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  const email = page.getByLabel('Email');
  expect(await email.evaluate((input: HTMLInputElement) => input.validity.typeMismatch)).toBe(true);
  expect(await email.evaluate((input: HTMLInputElement) => input.validationMessage)).not.toBe('');
  await page.screenshot({ path: testInfo.outputPath('mobile-invalid-login.png'), fullPage: true });
  expect(errors).toEqual([]);
});