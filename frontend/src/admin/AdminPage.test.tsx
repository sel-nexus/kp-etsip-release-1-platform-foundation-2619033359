import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AdminPage from './AdminPage';
import type { User } from '../types';

const admin: User = { id: 'admin', name: 'Admin', email: 'admin@example.com', role: 'Administrator', portfolioAccess: [], status: 'Active', authSource: 'local', managerName: null, vendorIndicator: false, lastLogin: null, mustChangePassword: false, defaultLandingPage: null };
const account = { ...admin, id: 'one', name: 'Example User', email: 'person@example.com', role: 'Engineer' };
const role = { id: 'role', name: 'Engineer', description: 'Engineering', permissions: ['view', 'create'] };
const result = (items: unknown[]) => new Response(JSON.stringify({ items, total: items.length, limit: 25, offset: 0 }), { status: 200 });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('denies auditors without fetching administrative data', () => {
  const fetch = vi.spyOn(globalThis, 'fetch');
  render(<AdminPage user={{ ...admin, role: 'Auditor' }} />);
  expect(screen.getByRole('alert').textContent).toContain('Access denied');
  expect(fetch).not.toHaveBeenCalled();
});

it('creates a user with assigned portfolio and displays success', async () => {
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    if (init?.method === 'POST') return new Response(JSON.stringify(account), { status: 201 });
    if (String(input).includes('/portfolios')) return result([{ id: 'p1', name: 'Payments' }]);
    if (String(input).includes('/roles')) return result([role]);
    return result([account]);
  });
  render(<AdminPage user={admin} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Create user' }));
  await user.type(screen.getByLabelText('Name'), 'New Person');
  await user.type(screen.getByLabelText('Email'), 'new@example.com');
  await user.type(screen.getByLabelText('Password'), 'StrongPassword123!');
  await user.selectOptions(screen.getByLabelText('Role'), 'Portfolio Leader');
  await user.click(screen.getByLabelText('Payments'));
  await user.click(screen.getByRole('button', { name: 'Save user' }));
  expect(await screen.findByText('User saved.')).toBeTruthy();
  const request = fetch.mock.calls.find(([, init]) => init?.method === 'POST');
  expect(JSON.parse(String(request?.[1]?.body)).portfolioAccess).toEqual(['p1']);
});

it('edits bounded role permissions and shows server errors', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    if (init?.method === 'PUT') return new Response(JSON.stringify({ detail: 'Update rejected' }), { status: 409 });
    if (String(input).includes('/roles')) return result([role]);
    return result([]);
  });
  render(<AdminPage user={admin} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Roles' }));
  await user.click(await screen.findByRole('button', { name: 'Edit Engineer permissions' }));
  expect((screen.getByLabelText('administer') as HTMLInputElement).disabled).toBe(true);
  await user.click(screen.getByLabelText('create'));
  await user.click(screen.getByRole('button', { name: 'Save role' }));
  expect((await screen.findByRole('alert')).textContent).toContain('Update rejected');
});

it('offers retry after a loading failure', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Unavailable' }), { status: 503 })).mockImplementation(async () => result([]));
  render(<AdminPage user={admin} />);
  expect((await screen.findByRole('alert')).textContent).toContain('Unavailable');
  await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
  expect(await screen.findByText('No users found.')).toBeTruthy();
});
