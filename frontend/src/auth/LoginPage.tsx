import { useState, type FormEvent } from 'react';
import type { User } from '../types';
import { signIn } from './auth';

interface Props { onLogin: (user: User) => void }
/** Present the local account sign-in form. */
export default function LoginPage({ onLogin }: Props) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    try { const session = await signIn(email, password); onLogin(session.user); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to sign in.'); }
    finally { setBusy(false); }
  }
  return (
    <main className="auth-layout">
      <section className="intro">
        <p className="eyebrow">KP ETSIP · PLATFORM FOUNDATION</p>
        <h1>Quality, in clear view.</h1>
        <p>A shared foundation for quality inventory and responsible access.</p>
      </section>
      <section className="card login-card" aria-labelledby="login-title">
        <p className="eyebrow">WELCOME BACK</p>
        <h2 id="login-title">Sign in</h2>
        <p>Use your local account to continue.</p>
        <form onSubmit={submit}>
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            autoComplete="username"
            required
            aria-required="true"
            value={email}
            onChange={e => setEmail(e.target.value)}
          />
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            required
            aria-required="true"
            value={password}
            onChange={e => setPassword(e.target.value)}
            aria-invalid={!!error}
            aria-describedby={error ? 'login-error' : undefined}
          />
          {error && <p id="login-error" role="alert" className="error">{error}</p>}
          <button type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        </form>
        <p className="hint">Local demo credentials are documented in the README. Deployment credentials are configured by your administrator.</p>
      </section>
    </main>
  );
}
