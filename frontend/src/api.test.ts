import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, tokenKey } from './api';

afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

describe('API client', () => {
  it('sends JSON and bearer credentials and returns parsed data', async () => {
    sessionStorage.setItem(tokenKey, 'session-token');
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"name":"saved"}', { status: 200 }));
    await expect(api('/items', { method: 'POST', body: '{"name":"saved"}' })).resolves.toEqual({ name: 'saved' });
    const [url, options] = fetcher.mock.calls[0];
    expect(url).toBe('/api/items');
    expect(new Headers(options?.headers).get('Authorization')).toBe('Bearer session-token');
    expect(new Headers(options?.headers).get('Content-Type')).toBe('application/json');
  });
  it('returns undefined for no content', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api('/items/1', { method: 'DELETE' })).resolves.toBeUndefined();
  });
  it('returns blob responses', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('csv data', { status: 200 }));
    const result = await api<Blob>('/export', {}, 'blob');
    // Node's fetch Response returns a Node Blob, not jsdom's FileReader Blob.
    // Read through the Blob interface so the byte content remains verified.
    expect(result.size).toBe(8);
    expect(await result.text()).toBe('csv data');
  });
  it('clears an expired session and emits session-expired on protected 401', async () => {
    sessionStorage.setItem(tokenKey, 'expired');
    const expired = vi.fn();
    window.addEventListener('session-expired', expired);
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"detail":"Session expired"}', { status: 401 }));
    try {
      await expect(api('/items')).rejects.toThrow('Session expired');
      expect(sessionStorage.getItem(tokenKey)).toBeNull();
      expect(expired).toHaveBeenCalledOnce();
    } finally { window.removeEventListener('session-expired', expired); }
  });
  it('does not send a stored bearer or clear it on login rejection', async () => {
    sessionStorage.setItem(tokenKey, 'existing');
    const expired = vi.fn();
    window.addEventListener('session-expired', expired);
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"detail":"Invalid email or password"}', { status: 401 }));
    try {
      await expect(api('/auth/login', { method: 'POST', body: '{}' })).rejects.toThrow('Invalid email or password');
      expect(new Headers(fetcher.mock.calls[0][1]?.headers).has('Authorization')).toBe(false);
      expect(sessionStorage.getItem(tokenKey)).toBe('existing');
      expect(expired).not.toHaveBeenCalled();
    } finally { window.removeEventListener('session-expired', expired); }
  });
  it.each(['not JSON', '{"detail":[{"msg":"invalid"}]}'])('uses a generic error for non-string detail: %s', async body => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(body, { status: 422 }));
    await expect(api('/items')).rejects.toThrow('Request failed. Please try again.');
  });
  it('propagates a network failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Network unavailable'));
    await expect(api('/items')).rejects.toThrow('Network unavailable');
  });
});