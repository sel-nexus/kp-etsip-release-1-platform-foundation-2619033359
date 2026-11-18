import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import ApplicationPage from './ApplicationPage';
import type { User } from '../types';

const user: User = { id:'1', name:'Engineer', email:'engineer@ketsip.local', role:'Engineer', portfolioAccess:[], status:'Active', authSource:'local', managerName:null, vendorIndicator:false, lastLogin:null, mustChangePassword:false, defaultLandingPage:null };
const app = { id:'a', name:'Gateway', portfolioId:'p', description:'Payments', productArea:'Payments', businessOwner:'Business', technologyOwner:'Tech', etsOwner:'ETS', criticality:'High', tier:1, lifecycleStatus:'Active', technologyStack:'Python', repositoryLink:null, pipelineLink:null, applicationHealthScore:80, qualityScore:81, automationCoverage:70, unitTestCoverage:75, openDefects:4, openCriticalDefects:1, riskLevel:'Medium', createdAt:'now', updatedAt:'now' };
const page = {items:[app], total:1, limit:25, offset:0};
afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function mount(account: User = user) {
  render(<MemoryRouter initialEntries={['/applications']}><Routes><Route path="/applications/:id?" element={<ApplicationPage user={account} />} /></Routes></MemoryRouter>);
}
function respond(body: unknown, status = 200) { return new Response(JSON.stringify(body), {status}); }
it('shows filtered inventory and opens full detail with role-appropriate controls', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input);
    if (url.includes('/capabilities')) return respond({create:true, edit:true, delete:false});
    if (url.includes('/portfolios')) return respond({items:[{id:'p', name:'Payments'}], total:1});
    if (url.includes('/applications/a')) return respond(app);
    return respond(page);
  });
  mount();
  expect(await screen.findByRole('button', {name:'Create application'})).toBeTruthy();
  await userEvent.selectOptions(screen.getByLabelText('Risk level'), 'High');
  await userEvent.click(await screen.findByRole('link', {name:'Gateway'}));
  expect(await screen.findByRole('heading', {name:'Gateway'})).toBeTruthy();
  expect(screen.getByText('Tech')).toBeTruthy();
  expect(screen.getByRole('button', {name:'Edit application'})).toBeTruthy();
  expect(screen.queryByRole('button', {name:'Delete application'})).toBeNull();
  await userEvent.click(screen.getByRole('button', {name:'Edit application'}));
  expect(screen.getByLabelText('Quality score')).toHaveProperty('value', '81');
  expect(screen.getByLabelText('Repository link')).toBeTruthy();
});
it('hides mutation controls when effective permissions deny them', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input);
    if (url.includes('/capabilities')) return respond({create:false, edit:false, delete:false});
    if (url.includes('/portfolios')) return respond({items:[{id:'p', name:'Payments'}], total:1});
    if (url.includes('/applications/a')) return respond(app);
    return respond(page);
  });
  mount({...user, role:'Read Only'});
  await userEvent.click(await screen.findByRole('link', {name:'Gateway'}));
  await screen.findByRole('heading', {name:'Gateway'});
  expect(screen.queryByRole('button', {name:'Edit application'})).toBeNull();
  expect(screen.queryByRole('button', {name:'Delete application'})).toBeNull();
});
it('reports a backend error and retries', async () => {
  let failed = false;
  vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input);
    if (url.includes('/capabilities')) {
      if (!failed) { failed = true; return respond({detail:'Unavailable'}, 503); }
      return respond({create:false, edit:false, delete:false});
    }
    if (url.includes('/portfolios')) return respond({items:[], total:0});
    return respond({items:[], total:0, limit:25, offset:0});
  });
  mount();
  expect((await screen.findByRole('alert')).textContent).toContain('Unavailable');
  await userEvent.click(screen.getByRole('button', {name:'Retry'}));
  expect(await screen.findByText('No applications match these filters.')).toBeTruthy();
});
