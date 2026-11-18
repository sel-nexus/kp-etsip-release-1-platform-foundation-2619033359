import { test, expect } from '@playwright/test';

test('administrator creates, edits and deactivates an account using the live API', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const name = `E2E User ${Date.now()}`;
  await page.goto('/login');
  await page.getByLabel('Email').fill(process.env.E2E_ADMIN_EMAIL ?? 'admin@ketsip.local');
  await page.getByLabel('Password').fill(process.env.E2E_ADMIN_PASSWORD ?? 'LocalAdmin123!');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.getByRole('link', { name: 'Administration' }).click();
  await page.getByRole('button', { name: 'Create user' }).click();
  await page.getByLabel('Name', { exact: true }).fill(name);
  await page.getByLabel('Email', { exact: true }).fill(`e2e-${Date.now()}@example.com`);
  await page.getByLabel('Password', { exact: true }).fill('E2eTemporaryPassword123!');
  const created = page.waitForResponse(response => response.url().endsWith('/api/users') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Save user' }).click();
  const response = await created;
  expect(response.status()).toBe(201);
  const record = await response.json();
  expect(record.name).toBe(name);
  expect(record.passwordHash).toBeUndefined();
  await expect(page.getByText('User saved.')).toBeVisible();
  const authToken = await page.evaluate(() => sessionStorage.getItem('kp-etsip-token'));
  const stored = await page.request.get(`/api/users/${record.id}`, { headers: { Authorization: `Bearer ${authToken}` } });
  expect((await stored.json()).name).toBe(name);
  const edit = page.getByRole('button', { name: `Edit ${name}` });
  while (!(await edit.count()) && await page.getByRole('button', { name: 'Next', exact: true }).isEnabled()) {
    const nextPage = page.waitForResponse(response => response.url().includes('/api/users?') && response.request().method() === 'GET');
    await page.getByRole('button', { name: 'Next', exact: true }).click();
    await nextPage;
    await expect(page.getByText('Loading administration…')).toBeHidden();
  }
  await edit.click();
  await page.getByLabel('Manager name').fill('E2E manager');
  await page.getByRole('button', { name: 'Save user' }).click();
  await expect(page.getByText('User saved.')).toBeVisible();
  const updated = await page.request.get(`/api/users/${record.id}`, { headers: { Authorization: `Bearer ${authToken}` } });
  expect((await updated.json()).managerName).toBe('E2E manager');
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: `Deactivate ${name}` }).click();
  await expect(page.getByText('User deactivated.')).toBeVisible();
  const after = await page.request.get(`/api/users/${record.id}`, { headers: { Authorization: `Bearer ${authToken}` } });
  expect((await after.json()).status).toBe('Inactive');
  expect(errors).toEqual([]);
});
