import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import PortfolioPage from './PortfolioPage';
import type { User } from '../types';

const user: User = { id:'1', name:'Admin', email:'admin@ketsip.local', role:'Administrator', portfolioAccess:[], status:'Active', authSource:'local', managerName:null, vendorIndicator:false, lastLogin:null, mustChangePassword:false, defaultLandingPage:null };
const portfolio = { id:'abc', name:'Payments', owner:'Owner', description:'Summary', productArea:'Payments', status:'Active', applicationCount:1, qualityScore:80 };
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function mount() {
  render(<MemoryRouter initialEntries={['/portfolios']}><Routes><Route path="/portfolios/:id?" element={<PortfolioPage user={user} />} /></Routes></MemoryRouter>);
}
it('renders inventory and opens a detail with linked applications', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input);
    const body = url.includes('/applications') ? {items:[{id:'a', name:'Gateway'}], total:1, offset:0, limit:100} : url.endsWith('/abc') ? portfolio : {items:[portfolio], total:1, offset:0, limit:25};
    return new Response(JSON.stringify(body), {status:200});
  });
  mount();
  await userEvent.click(await screen.findByRole('link', {name:'Payments'}));
  expect(await screen.findByRole('heading', {name:'Payments'})).toBeTruthy();
  expect(await screen.findByRole('link', {name:'Gateway'})).toBeTruthy();
});
it('shows a server error and permits retry', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({detail:'Unavailable'}), {status:503})).mockResolvedValueOnce(new Response(JSON.stringify({items:[], total:0, offset:0, limit:25}), {status:200}));
  mount();
  expect((await screen.findByRole('alert')).textContent).toContain('Unavailable');
  await userEvent.click(screen.getByRole('button', {name:'Retry'}));
  expect(await screen.findByText('No portfolios match these filters.')).toBeTruthy();
});

it('retains a failed create and opens the saved portfolio after retry', async () => {
  let current = {...portfolio};
  let fail = true;
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === 'POST') {
      if (fail) { fail = false; return new Response(JSON.stringify({detail:'Name already exists'}), {status:409}); }
      current = {...current, ...JSON.parse(String(init.body))};
      return new Response(JSON.stringify(current), {status:201});
    }
    if (url.includes('/applications')) return new Response(JSON.stringify({items:[], total:0, offset:0, limit:25}), {status:200});
    return new Response(JSON.stringify(url.endsWith('/abc') ? current : {items:[portfolio], total:1, offset:0, limit:25}), {status:200});
  });
  const interaction = userEvent.setup();
  mount();
  await interaction.click(await screen.findByRole('button', {name:'Create portfolio'}));
  await interaction.type(screen.getByLabelText('Name'), 'New portfolio');
  await interaction.type(screen.getByLabelText('Owner'), 'New owner');
  await interaction.click(screen.getByRole('button', {name:'Save portfolio'}));
  expect((await screen.findByRole('alert')).textContent).toContain('Name already exists');
  expect(screen.getByLabelText('Name')).toHaveProperty('value', 'New portfolio');
  expect(screen.getByLabelText('Owner')).toHaveProperty('value', 'New owner');
  await interaction.click(screen.getByRole('button', {name:'Save portfolio'}));
  expect(await screen.findByRole('heading', {name:'New portfolio'})).toBeTruthy();
  expect(screen.getByText('New owner')).toBeTruthy();
  expect(screen.getByText('Portfolio saved.')).toBeTruthy();
  const writes = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST');
  expect(writes).toHaveLength(2);
  expect(JSON.parse(String(writes[1][1]?.body))).toMatchObject({name:'New portfolio', owner:'New owner'});
});

it('retains failed edits and reloads the updated portfolio on success', async () => {
  let current = {...portfolio};
  let fail = true;
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === 'PUT') {
      if (fail) { fail = false; return new Response(JSON.stringify({detail:'Edit rejected'}), {status:409}); }
      current = {...current, ...JSON.parse(String(init.body))};
      return new Response(JSON.stringify(current), {status:200});
    }
    if (url.includes('/applications')) return new Response(JSON.stringify({items:[], total:0, offset:0, limit:25}), {status:200});
    return new Response(JSON.stringify(url.endsWith('/abc') ? current : {items:[portfolio], total:1, offset:0, limit:25}), {status:200});
  });
  const interaction = userEvent.setup();
  mount();
  await interaction.click(await screen.findByRole('link', {name:'Payments'}));
  await interaction.click(await screen.findByRole('button', {name:'Edit portfolio'}));
  await interaction.clear(screen.getByLabelText('Owner'));
  await interaction.type(screen.getByLabelText('Owner'), 'Updated owner');
  await interaction.click(screen.getByRole('button', {name:'Save portfolio'}));
  expect((await screen.findByRole('alert')).textContent).toContain('Edit rejected');
  expect(screen.getByLabelText('Owner')).toHaveProperty('value', 'Updated owner');
  await interaction.click(screen.getByRole('button', {name:'Save portfolio'}));
  expect(await screen.findByText('Updated owner')).toBeTruthy();
  expect(screen.getByText('Portfolio saved.')).toBeTruthy();
  const writes = fetcher.mock.calls.filter(([, init]) => init?.method === 'PUT');
  expect(writes).toHaveLength(2);
  expect(JSON.parse(String(writes[1][1]?.body))).toMatchObject({name:'Payments', owner:'Updated owner'});
});

it('does not delete on cancellation, displays failure, and returns to inventory on confirmation', async () => {
  let exists = true;
  let fail = true;
  const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true);
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === 'DELETE') {
      if (fail) { fail = false; return new Response(JSON.stringify({detail:'Portfolio is referenced'}), {status:409}); }
      exists = false; return new Response(null, {status:204});
    }
    if (url.includes('/applications')) return new Response(JSON.stringify({items:[], total:0, offset:0, limit:25}), {status:200});
    return new Response(JSON.stringify(url.endsWith('/abc') ? portfolio : {items:exists ? [portfolio] : [], total:exists ? 1 : 0, offset:0, limit:25}), {status:200});
  });
  const interaction = userEvent.setup();
  mount();
  await interaction.click(await screen.findByRole('link', {name:'Payments'}));
  await interaction.click(await screen.findByRole('button', {name:'Delete portfolio'}));
  expect(confirm).toHaveBeenCalled();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'DELETE')).toHaveLength(0);
  expect(screen.getByRole('heading', {name:'Payments'})).toBeTruthy();
  await interaction.click(screen.getByRole('button', {name:'Delete portfolio'}));
  expect((await screen.findByRole('alert')).textContent).toContain('Portfolio is referenced');
  expect(screen.getByRole('heading', {name:'Payments'})).toBeTruthy();
  await interaction.click(screen.getByRole('button', {name:'Delete portfolio'}));
  expect(await screen.findByText('No portfolios match these filters.')).toBeTruthy();
  expect(screen.getByText('Portfolio deleted.')).toBeTruthy();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'DELETE')).toHaveLength(2);
});
