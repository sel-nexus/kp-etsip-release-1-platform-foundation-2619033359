import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import LoginPage from './LoginPage';
import ProfilePage from './ProfilePage';
import type { User } from '../types';

const user: User = { id:'1', name:'Demo Engineer', email:'engineer@ketsip.local', role:'Engineer', portfolioAccess:[], status:'Active', authSource:'local', managerName:null, vendorIndicator:false, lastLogin:null, mustChangePassword:false, defaultLandingPage:null };
afterEach(() => { cleanup(); vi.restoreAllMocks(); sessionStorage.clear(); });
describe('local identity', () => {
  it('signs in and reports the returned account', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({token:'abc', user}), {status:200}));
    const onLogin = vi.fn(); const actor = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await actor.type(screen.getByLabelText('Email'), user.email);
    await actor.type(screen.getByLabelText('Password'), 'password1234');
    await actor.click(screen.getByRole('button', {name:'Sign in'}));
    expect(await screen.findByRole('button', {name:'Sign in'})).toBeTruthy();
    expect(onLogin).toHaveBeenCalledWith(user);
    expect(sessionStorage.getItem('kp-etsip-token')).toBe('abc');
  });
  it('displays invalid credentials without signing in', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({detail:'Invalid email or password'}), {status:401}));
    const onLogin = vi.fn(); const actor = userEvent.setup();
    render(<LoginPage onLogin={onLogin} />);
    await actor.type(screen.getByLabelText('Email'), user.email);
    await actor.type(screen.getByLabelText('Password'), 'wrong');
    await actor.click(screen.getByRole('button', {name:'Sign in'}));
    expect((await screen.findByRole('alert')).textContent).toContain('Invalid email or password');
    expect(onLogin).not.toHaveBeenCalled();
  });
  it('shows forced password change and hides preferences', () => {
    render(<ProfilePage user={{...user, mustChangePassword:true}} onUpdate={() => {}} />);
    expect(screen.getByRole('status').textContent).toContain('initial password');
    expect(screen.queryByLabelText('Default landing page')).toBeNull();
  });
  it('saves a preference and shows a server error', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({...user, defaultLandingPage:'dashboard'}), {status:200})).mockResolvedValueOnce(new Response(JSON.stringify({detail:'Current password is incorrect'}), {status:400}));
    const actor = userEvent.setup(); const update = vi.fn();
    render(<ProfilePage user={user} onUpdate={update} />);
    await actor.selectOptions(screen.getByLabelText('Default landing page'), 'dashboard');
    await actor.click(screen.getByRole('button', {name:'Save preference'}));
    expect((await screen.findByRole('status')).textContent).toContain('Preference saved');
    expect(update).toHaveBeenCalledWith(expect.objectContaining({defaultLandingPage:'dashboard'}));
    await actor.type(screen.getByLabelText('Current password'), 'wrong');
    await actor.type(screen.getByLabelText('New password'), 'new-password-123');
    await actor.click(screen.getByRole('button', {name:'Update password'}));
    expect((await screen.findByRole('alert')).textContent).toContain('incorrect');
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
