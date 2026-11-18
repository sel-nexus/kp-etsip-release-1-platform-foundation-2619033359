/** Fetch JSON using the stored bearer session, surfacing server errors. */
const base = import.meta.env.VITE_API_BASE ?? '/api';
export const tokenKey = 'kp-etsip-token';

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set('Content-Type', 'application/json');
  const token = sessionStorage.getItem(tokenKey);
  if (token && path !== '/auth/login') headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`${base}${path}`, { ...options, headers });
  if (!response.ok) {
    if (response.status === 401 && path !== '/auth/login') {
      sessionStorage.removeItem(tokenKey);
      window.dispatchEvent(new Event('session-expired'));
    }
    let detail = 'Request failed. Please try again.';
    try {
      const body: { detail?: unknown } = await response.json();
      if (typeof body.detail === 'string') detail = body.detail;
    } catch { /* A non-JSON error still gets a useful generic message. */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}
