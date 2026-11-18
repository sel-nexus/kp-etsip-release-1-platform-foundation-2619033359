import { useEffect, useState } from 'react';
import { BrowserRouter, Link, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { tokenKey } from './api';
import type { User } from './types';
import LoginPage from './auth/LoginPage';
import ProfilePage from './auth/ProfilePage';
import { currentUser, landingPath, signOut } from './auth/auth';
import PortfolioPage from './portfolios/PortfolioPage';
import ApplicationPage from './applications/ApplicationPage';

/** Route identity screens and restore an existing browser session. */
function Shell() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(!!sessionStorage.getItem(tokenKey));
  const [error, setError] = useState('');
  const navigate = useNavigate();
  useEffect(() => {
    let active = true;
    const expired = () => { if (active) { setUser(null); setError('Your session has expired. Please sign in again.'); navigate('/login'); } };
    window.addEventListener('session-expired', expired);
    if (sessionStorage.getItem(tokenKey)) currentUser().then(u => { if (active) setUser(u); }).catch(() => { if (active) setError('Unable to restore your session. Please sign in again.'); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; window.removeEventListener('session-expired', expired); };
  }, [navigate]);
  async function logout() {
    try { await signOut(); } catch { setError('Session cleared locally; the server could not be reached.'); }
    finally { setUser(null); navigate('/login'); }
  }
  if (loading) return <main className="content" role="status">Restoring session…</main>;
  const login = <LoginPage onLogin={u => { setError(''); setUser(u); navigate(landingPath(u)); }} />;
  return (
    <>
      <header className="site-header">
        <div className="header-inner">
          <Link className="brand" to="/">KP <span>ETSIP</span></Link>
          {user && <nav aria-label="Account">{!user.mustChangePassword && <><Link to="/portfolios">Portfolios</Link><Link to="/applications">Applications</Link></>}<Link to="/profile">My profile</Link><button className="text-button" onClick={logout}>Sign out</button></nav>}
        </div>
      </header>
      {error && <p className="global-message" role="alert">{error}</p>}
      <Routes>
        <Route path="/login" element={user ? <Navigate to={landingPath(user)} replace /> : login} />
        <Route path="/profile" element={user ? <ProfilePage user={user} onUpdate={setUser} /> : <Navigate to="/login" replace />} />
        <Route path="/portfolios/:id?" element={user ? user.mustChangePassword ? <Navigate to="/profile" replace /> : <PortfolioPage user={user} /> : <Navigate to="/login" replace />} />
        <Route path="/" element={<Navigate to={user ? landingPath(user) : '/login'} replace />} />
        <Route path="/dashboard" element={user ? user.mustChangePassword ? <Navigate to="/profile" replace /> : <Destination title="Executive Dashboard" /> : <Navigate to="/login" replace />} />
        <Route path="/applications/:id?" element={user ? user.mustChangePassword ? <Navigate to="/profile" replace /> : <ApplicationPage user={user} /> : <Navigate to="/login" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  );
}
/** Explain availability of the selected future destination without simulating it. */
function Destination({ title }: { title: string }) {
  return <main className="content"><p className="eyebrow">YOUR STARTING POINT</p><h1>{title}</h1><p>This destination is not available in the identity foundation yet.</p><Link to="/profile">Manage your profile</Link></main>;
}
/** Supply the application's single browser router. */
export default function App() { return <BrowserRouter><Shell /></BrowserRouter>; }
