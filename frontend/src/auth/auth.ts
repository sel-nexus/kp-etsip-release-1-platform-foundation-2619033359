/** Manage bearer session operations against the identity API. */
import { api, tokenKey } from '../api';
import type { Session, User } from '../types';

export async function signIn(email: string, password: string): Promise<Session> {
  const session = await api<Session>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) });
  sessionStorage.setItem(tokenKey, session.token);
  return session;
}
export async function signOut(): Promise<void> {
  try { await api('/auth/logout', { method: 'POST' }); }
  finally { sessionStorage.removeItem(tokenKey); }
}
export async function currentUser(): Promise<User> { return api<User>('/auth/me'); }
export function landingPath(user: User): string {
  if (user.mustChangePassword) return '/profile';
  return `/${user.defaultLandingPage ?? (['Administrator', 'Executive'].includes(user.role) ? 'dashboard' : 'applications')}`;
}
