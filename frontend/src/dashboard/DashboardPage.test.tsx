import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import DashboardPage from './DashboardPage';

const filled = { enterpriseQualityScore: 0, applicationHealthScore: 75, automationMaturityScore: 60, openCriticalDefects: 3, applicationsAtRisk: 1, totalApplications: 2, totalPortfolios: 1, portfolios: [{ portfolioId: 'p1', name: 'Payments', applicationCount: 2, qualityScore: 0, applicationsAtRisk: 1 }] };
const empty = { enterpriseQualityScore: null, applicationHealthScore: null, automationMaturityScore: null, openCriticalDefects: 0, applicationsAtRisk: 0, totalApplications: 0, totalPortfolios: 0, portfolios: [] };
const choices = { items: [{ id: 'p1', name: 'Payments' }], total: 1 };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function mount() { render(<MemoryRouter><DashboardPage /></MemoryRouter>); }

it('shows loading, all metrics, both portfolio lists and zero values', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => json(String(input).includes('/portfolios?') ? choices : filled));
  mount();
  expect(screen.getByRole('status').textContent).toContain('Loading');
  const metrics = await screen.findByRole('region', { name: 'Executive metrics' });
  expect(within(metrics).getByText('Enterprise Quality Score').parentElement?.textContent).toContain('0');
  expect(within(metrics).getByText('Application Health Score').parentElement?.textContent).toContain('75');
  expect(within(metrics).getByText('Automation Maturity Score').parentElement?.textContent).toContain('60');
  expect(within(metrics).getByText('Open Critical Defects').parentElement?.textContent).toContain('3');
  expect(within(metrics).getByText('Applications at Risk').parentElement?.textContent).toContain('1');
  expect(within(metrics).getByText('Total Applications').parentElement?.textContent).toContain('2');
  expect(within(metrics).getByText('Total Portfolios').parentElement?.textContent).toContain('1');
  expect(within(screen.getByRole('region', { name: 'Portfolio Quality Score' })).getByText('Payments')).toBeTruthy();
  expect(within(screen.getByRole('region', { name: 'Applications at Risk by Portfolio' })).getByText('Payments')).toBeTruthy();
  expect(screen.getByText(/manually maintained/)).toBeTruthy();
});

it('passes filters and renders empty values as unavailable without treating zero as missing', async () => {
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async input => json(String(input).includes('/portfolios?') ? choices : String(input).includes('riskLevel=High') ? empty : filled));
  const user = userEvent.setup();
  mount();
  await screen.findByRole('region', { name: 'Executive metrics' });
  await user.selectOptions(screen.getByLabelText('Portfolio'), 'p1');
  await user.type(screen.getByLabelText('Product area'), 'A');
  await user.selectOptions(screen.getByLabelText('Risk level'), 'High');
  expect(await screen.findByText('No applications match these filters.')).toBeTruthy();
  expect(screen.getAllByText('Unavailable')).toHaveLength(3);
  expect(fetcher.mock.calls.some(([input]) => String(input).includes('portfolioId=p1') && String(input).includes('productArea=A') && String(input).includes('riskLevel=High'))).toBe(true);
});

it('exposes failure and retries successfully', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementationOnce(async () => json({ detail: 'Service unavailable' }, 503)).mockImplementation(async input => json(String(input).includes('/portfolios?') ? choices : empty));
  const user = userEvent.setup();
  mount();
  expect((await screen.findByRole('alert')).textContent).toContain('Service unavailable');
  await user.click(screen.getByRole('button', { name: 'Retry' }));
  expect(await screen.findByText('No applications match these filters.')).toBeTruthy();
});
