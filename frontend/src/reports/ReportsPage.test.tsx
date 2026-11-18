import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import ReportsPage from './ReportsPage';
import AuditPage from './AuditPage';
import type { User } from '../types';

const auditor: User = { id: 'u1', name: 'Auditor', email: 'auditor@example.com', role: 'Auditor', portfolioAccess: [], status: 'Active', authSource: 'local', managerName: null, vendorIndicator: false, lastLogin: null, mustChangePassword: false, defaultLandingPage: null };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it('renders filtered reports, switches tables and hides export without permission', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const path = String(input);
    if (path.includes('capabilities')) return json({ export: false });
    if (path.includes('/portfolios')) return json({ items: [{ id: 'p1', name: 'Payments', applicationCount: 2, qualityScore: 50 }], total: 1, limit: 25, offset: 0 });
    return json({ items: [{ id: 'a1', name: 'Ledger', portfolioId: 'p1', criticality: 'High', riskLevel: 'High' }], total: 1, limit: 25, offset: 0 });
  });
  const user = userEvent.setup();
  render(<MemoryRouter><ReportsPage /></MemoryRouter>);
  expect(screen.getByRole('status').textContent).toContain('Loading');
  expect(await screen.findByRole('link', { name: 'Ledger' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Export CSV' })).toBeNull();
  await user.selectOptions(screen.getByLabelText('Risk level'), 'High');
  expect(fetcher.mock.calls.some(([input]) => String(input).includes('riskLevel=High'))).toBe(true);
  await user.selectOptions(screen.getByLabelText('Report'), 'portfolios');
  expect(await screen.findByRole('link', { name: 'Payments' })).toBeTruthy();
});

it('shows an error and retries the report', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementationOnce(async () => json({ detail: 'Unavailable' }, 503)).mockImplementation(async input => String(input).includes('capabilities') ? json({ export: true }) : json({ items: [], total: 0, limit: 25, offset: 0 }));
  const user = userEvent.setup();
  render(<MemoryRouter><ReportsPage /></MemoryRouter>);
  expect((await screen.findByRole('alert')).textContent).toContain('Unavailable');
  await user.click(screen.getByRole('button', { name: 'Retry' }));
  expect(await screen.findByText('No records match these filters.')).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Export CSV' })).toBeTruthy();
});

it('renders auditor events and sends audit filters without admin access', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async input => String(input).includes('capabilities') ? json({ export: true }) : json({ items: [{ id: 'e1', timestamp: '2024-04-03', userId: 'u1', userName: 'Auditor', action: 'login', entityType: 'user', entityId: 'u1', details: 'Login succeeded' }], total: 1, limit: 25, offset: 0 }));
  const user = userEvent.setup();
  render(<MemoryRouter><AuditPage user={auditor} /></MemoryRouter>);
  expect(await screen.findByText('Login succeeded')).toBeTruthy();
  await user.type(screen.getByLabelText('User ID'), 'u1');
  expect(fetcher.mock.calls.some(([input]) => String(input).includes('userId=u1'))).toBe(true);
  expect(screen.getByRole('button', { name: 'Export CSV' })).toBeTruthy();
});

it('denies other roles locally without requesting audit data', () => {
  const fetcher = vi.spyOn(globalThis, 'fetch');
  render(<MemoryRouter><AuditPage user={{ ...auditor, role: 'Engineer' }} /></MemoryRouter>);
  expect(screen.getByRole('alert').textContent).toContain('Permission denied');
  expect(fetcher).not.toHaveBeenCalled();
});
