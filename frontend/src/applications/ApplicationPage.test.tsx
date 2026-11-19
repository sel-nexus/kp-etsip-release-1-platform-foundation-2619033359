import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import ApplicationPage from './ApplicationPage';
import type { User } from '../types';

const user: User = { id:'1', name:'Engineer', email:'engineer@ketsip.local', role:'Engineer', portfolioAccess:[], status:'Active', authSource:'local', managerName:null, vendorIndicator:false, lastLogin:null, mustChangePassword:false, defaultLandingPage:null };
const app = { id:'a', name:'Gateway', portfolioId:'p', description:'Payments', productArea:'Payments', businessOwner:'Business', technologyOwner:'Tech', etsOwner:'ETS', criticality:'High', tier:1, lifecycleStatus:'Active', technologyStack:'Python', repositoryLink:null, pipelineLink:null, applicationHealthScore:80, qualityScore:81, automationCoverage:70, unitTestCoverage:75, openDefects:4, openCriticalDefects:1, riskLevel:'Medium', createdAt:'now', updatedAt:'now' };
const page = {items:[app], total:1, limit:25, offset:0};
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
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

it('saves an edited application, retaining the form on conflict and reloading on success', async () => {
  let current = {...app};
  let fail = true;
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === 'PUT') {
      if (fail) { fail = false; return respond({detail:'Application changed; reload and try again'}, 409); }
      current = {...current, ...JSON.parse(String(init.body))};
      return respond(current);
    }
    if (url.includes('/capabilities')) return respond({create:true, edit:true, delete:true, export:true});
    if (url.includes('/portfolios')) return respond({items:[{id:'p', name:'Payments'}], total:1});
    if (url.includes('/applications/a')) return respond(current);
    return respond(page);
  });
  const interaction = userEvent.setup();
  mount();
  await interaction.click(await screen.findByRole('link', {name:'Gateway'}));
  await interaction.click(await screen.findByRole('button', {name:'Edit application'}));
  await interaction.clear(screen.getByLabelText('Name'));
  await interaction.type(screen.getByLabelText('Name'), 'Renamed gateway');
  await interaction.click(screen.getByRole('button', {name:'Save application'}));
  expect((await screen.findByRole('alert')).textContent).toContain('Application changed');
  expect(screen.getByLabelText('Name')).toHaveProperty('value', 'Renamed gateway');
  await interaction.click(screen.getByRole('button', {name:'Save application'}));
  expect(await screen.findByRole('heading', {name:'Renamed gateway'})).toBeTruthy();
  expect(screen.getByText('Application saved.')).toBeTruthy();
  const writes = fetcher.mock.calls.filter(([, init]) => init?.method === 'PUT');
  expect(writes).toHaveLength(2);
  expect(JSON.parse(String(writes[1][1]?.body))).toMatchObject({name:'Renamed gateway', portfolioId:'p'});
});

it('shows delete failure and navigates to updated inventory after successful confirmation', async () => {
  let exists = true;
  let fail = true;
  vi.spyOn(window, 'confirm').mockReturnValue(true);
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === 'DELETE') {
      if (fail) { fail = false; return respond({detail:'Delete denied'}, 403); }
      exists = false; return new Response(null, {status:204});
    }
    if (url.includes('/capabilities')) return respond({create:true, edit:true, delete:true, export:true});
    if (url.includes('/portfolios')) return respond({items:[{id:'p', name:'Payments'}], total:1});
    if (url.includes('/applications/a')) return respond(app);
    return respond(exists ? page : {...page, items:[], total:0});
  });
  const interaction = userEvent.setup();
  mount();
  await interaction.click(await screen.findByRole('link', {name:'Gateway'}));
  await interaction.click(await screen.findByRole('button', {name:'Delete application'}));
  expect((await screen.findByRole('alert')).textContent).toContain('Delete denied');
  expect(screen.getByRole('heading', {name:'Gateway'})).toBeTruthy();
  await interaction.click(screen.getByRole('button', {name:'Delete application'}));
  expect(await screen.findByText('No applications match these filters.')).toBeTruthy();
  expect(screen.getByText('Application deleted.')).toBeTruthy();
});

it('creates an application after a rejected save and retains its fields', async () => {
  let current = {...app};
  let fail = true;
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === 'POST') {
      if (fail) { fail = false; return respond({detail:'Name already exists'}, 409); }
      current = {...current, ...JSON.parse(String(init.body))};
      return respond(current, 201);
    }
    if (url.includes('/capabilities')) return respond({create:true, edit:true, delete:true, export:true});
    if (url.includes('/portfolios')) return respond({items:[{id:'p', name:'Payments'}], total:1});
    if (url.includes('/applications/a')) return respond(current);
    return respond(page);
  });
  const interaction = userEvent.setup();
  mount();
  await interaction.click(await screen.findByRole('button', {name:'Create application'}));
  await interaction.type(screen.getByLabelText('Name'), 'New application');
  expect(screen.getByLabelText('Portfolio')).toHaveProperty('value', 'p');
  await interaction.click(screen.getByRole('button', {name:'Save application'}));
  expect((await screen.findByRole('alert')).textContent).toContain('Name already exists');
  expect(screen.getByLabelText('Name')).toHaveProperty('value', 'New application');
  await interaction.click(screen.getByRole('button', {name:'Save application'}));
  expect(await screen.findByRole('heading', {name:'New application'})).toBeTruthy();
  expect(screen.getByText('Application saved.')).toBeTruthy();
  const writes = fetcher.mock.calls.filter(([, init]) => init?.method === 'POST');
  expect(writes).toHaveLength(2);
  expect(JSON.parse(String(writes[1][1]?.body))).toMatchObject({name:'New application', portfolioId:'p'});
});

it('leaves an application in place when deletion is cancelled', async () => {
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input);
    if (url.includes('/capabilities')) return respond({create:true, edit:true, delete:true, export:true});
    if (url.includes('/portfolios')) return respond({items:[{id:'p', name:'Payments'}], total:1});
    if (url.includes('/applications/a')) return respond(app);
    return respond(page);
  });
  const interaction = userEvent.setup();
  mount();
  await interaction.click(await screen.findByRole('link', {name:'Gateway'}));
  await interaction.click(await screen.findByRole('button', {name:'Delete application'}));
  expect(confirm).toHaveBeenCalled();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === 'DELETE')).toHaveLength(0);
  expect(screen.getByRole('heading', {name:'Gateway'})).toBeTruthy();
  expect(screen.queryByText('Application deleted.')).toBeNull();
});

it('exports filtered CSV and surfaces export errors', async () => {
  let fail = true;
  const create = vi.fn(() => 'blob:test');
  const revoke = vi.fn();
  vi.stubGlobal('URL', Object.assign(URL, {createObjectURL: create, revokeObjectURL: revoke}));
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  const fetcher = vi.spyOn(globalThis, 'fetch').mockImplementation(async input => {
    const url = String(input);
    if (url.includes('/applications/export')) {
      if (fail) { fail = false; return respond({detail:'Export unavailable'}, 503); }
      return new Response('name\nGateway\n', {status:200, headers:{'Content-Type':'text/csv'}});
    }
    if (url.includes('/capabilities')) return respond({create:true, edit:true, delete:false, export:true});
    if (url.includes('/portfolios')) return respond({items:[{id:'p', name:'Payments'}], total:1});
    return respond(page);
  });
  const interaction = userEvent.setup();
  mount();
  await interaction.selectOptions(await screen.findByLabelText('Risk level'), 'High');
  await interaction.click(await screen.findByRole('button', {name:'Export CSV'}));
  expect((await screen.findByRole('alert')).textContent).toContain('Export unavailable');
  await interaction.click(screen.getByRole('button', {name:'Export CSV'}));
  expect(create).toHaveBeenCalledTimes(1);
  expect(revoke).toHaveBeenCalledWith('blob:test');
  expect(click).toHaveBeenCalledTimes(1);
  const exports = fetcher.mock.calls.filter(([url]) => String(url).includes('/applications/export'));
  expect(exports).toHaveLength(2);
  expect(String(exports[1][0])).toContain('riskLevel=High');
});
