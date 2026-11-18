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
