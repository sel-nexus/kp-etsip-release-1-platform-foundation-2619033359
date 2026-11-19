import { test, expect } from '@playwright/test';

test('administrator changes a role permission and the change persists', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/login');
  await page.getByLabel('Email').fill(process.env.E2E_ADMIN_EMAIL ?? 'admin@ketsip.local');
  await page.getByLabel('Password').fill(process.env.E2E_ADMIN_PASSWORD ?? 'LocalAdmin123!');
  await page.getByRole('button', { name: 'Sign in' }).click();
  const rolesResponse = page.waitForResponse(response => response.url().includes('/api/roles?') && response.status() === 200);
  await page.getByRole('link', { name: 'Administration' }).click();
  const roles = await (await rolesResponse).json();
  const role = roles.items.find((item: { name: string }) => item.name === 'Executive');
  expect(role).toBeDefined();
  expect(role.permissions).toContain('export');
  const token = await page.evaluate(() => sessionStorage.getItem('kp-etsip-token'));
  try {
    await page.getByRole('button', { name: 'Roles', exact: true }).click();
    await page.getByRole('button', { name: 'Edit Executive permissions' }).click();
    await page.getByRole('checkbox', { name: 'export' }).uncheck();
    const saved = page.waitForResponse(response => response.url().endsWith(`/api/roles/${role.id}`) && response.request().method() === 'PUT');
    await page.getByRole('button', { name: 'Save role' }).click();
    const response = await saved;
    expect(response.status()).toBe(200);
    expect((await response.json()).permissions).not.toContain('export');
    await expect(page.getByText('Role saved.')).toBeVisible();
    await page.reload();
    await page.getByRole('button', { name: 'Roles', exact: true }).click();
    await page.getByRole('button', { name: 'Edit Executive permissions' }).click();
    await expect(page.getByRole('checkbox', { name: 'export' })).not.toBeChecked();
    await page.screenshot({ path: testInfo.outputPath('role-permissions.png'), fullPage: true });
  } finally {
    const restored = await page.request.put(`/api/roles/${role.id}`, { headers: { Authorization: `Bearer ${token}` }, data: { name: role.name, description: role.description, permissions: role.permissions } });
    expect(restored.status()).toBe(200);
  }
  expect(errors).toEqual([]);
});

test('administrator receives a visible validation error for a whitespace-only user name', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/login');
  await page.getByLabel('Email').fill(process.env.E2E_ADMIN_EMAIL ?? 'admin@ketsip.local');
  await page.getByLabel('Password').fill(process.env.E2E_ADMIN_PASSWORD ?? 'LocalAdmin123!');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.getByRole('link', { name: 'Administration' }).click();
  await page.getByRole('button', { name: 'Create user' }).click();
  await page.getByLabel('Name', { exact: true }).fill('   ');
  await page.getByLabel('Email', { exact: true }).fill('invalid-name@example.com');
  await page.getByLabel('Password', { exact: true }).fill('TemporaryPassword123!');
  await page.getByRole('button', { name: 'Save user' }).click();
  await expect(page.getByRole('alert')).toContainText('Enter a name and a password');
  expect(errors).toEqual([]);
});

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
