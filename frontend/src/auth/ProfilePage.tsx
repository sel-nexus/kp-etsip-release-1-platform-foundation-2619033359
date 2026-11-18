import { useState, type FormEvent } from 'react';
import { api, tokenKey } from '../api';
import type { Session, User } from '../types';

interface Props { user: User; onUpdate: (user: User) => void }
/** Display identity and manage password and landing preference. */
export default function ProfilePage({ user, onUpdate }: Props) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [landing, setLanding] = useState<'dashboard' | 'applications'>(user.defaultLandingPage ?? (['Administrator', 'Executive'].includes(user.role) ? 'dashboard' : 'applications'));
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage(''); setError('');
    try {
      const result = await api<Session>('/profile/password', { method: 'PUT', body: JSON.stringify({ currentPassword: current, newPassword: next }) });
      sessionStorage.setItem(tokenKey, result.token); onUpdate(result.user); setCurrent(''); setNext(''); setMessage('Password updated.');
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to update password.'); }
    finally { setBusy(false); }
  }
  async function savePreferences(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage(''); setError('');
    try { const result = await api<User>('/profile/preferences', { method: 'PUT', body: JSON.stringify({ defaultLandingPage: landing }) }); onUpdate(result); setMessage('Preference saved.'); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to save preference.'); }
    finally { setBusy(false); }
  }
  return (
    <main className="content">
      <p className="eyebrow">ACCOUNT SETTINGS</p>
      <h1>My profile</h1>
      <p>Manage your local account and preferred starting point.</p>
      {user.mustChangePassword && <p className="notice" role="status">Change your initial password before continuing.</p>}
      {error && <p className="error" role="alert" id="profile-error">{error}</p>}
      {message && <p role="status" className="success">{message}</p>}
      <div className="profile-grid">
        <section className="card" aria-labelledby="identity-heading">
          <h2 id="identity-heading">Identity &amp; access</h2>
          <dl>
            <dt>Name</dt><dd>{user.name}</dd>
            <dt>Email</dt><dd>{user.email}</dd>
            <dt>Role</dt><dd>{user.role}</dd>
            <dt>Portfolio access</dt><dd>{user.portfolioAccess.length ? user.portfolioAccess.join(', ') : user.role === 'Portfolio Leader' ? 'No assigned portfolios' : 'All portfolios'}</dd>
          </dl>
        </section>
        <section className="card" aria-labelledby="password-heading">
          <h2 id="password-heading">Change password</h2>
          <p>Use at least 12 characters, up to 72 UTF-8 bytes.</p>
          <form onSubmit={changePassword}>
            <label htmlFor="current-password">Current password</label>
            <input id="current-password" type="password" autoComplete="current-password" required aria-required="true" value={current} onChange={e => setCurrent(e.target.value)} aria-describedby={error ? 'profile-error' : undefined} />
            <label htmlFor="new-password">New password</label>
            <input id="new-password" type="password" autoComplete="new-password" required aria-required="true" minLength={12} maxLength={72} value={next} onChange={e => setNext(e.target.value)} />
            <button disabled={busy} type="submit">Update password</button>
          </form>
        </section>
        {!user.mustChangePassword && <section className="card" aria-labelledby="preference-heading">
          <h2 id="preference-heading">Landing preference</h2>
          <p>Choose where to start after signing in.</p>
          <form onSubmit={savePreferences}>
            <label htmlFor="landing">Default landing page</label>
            <select id="landing" value={landing} onChange={e => setLanding(e.target.value as 'dashboard' | 'applications')}>
              <option value="dashboard">Executive Dashboard</option>
              <option value="applications">Application Repository</option>
            </select>
            <button disabled={busy} type="submit">Save preference</button>
          </form>
        </section>}
      </div>
    </main>
  );
}
