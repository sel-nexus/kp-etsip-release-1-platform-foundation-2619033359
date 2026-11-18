import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api';
import type { User } from '../types';
import { downloadCsv } from './ReportsPage';

type Event = { id: string; timestamp: string; userId: string | null; userName: string; action: string; entityType: string; entityId: string | null; details: string };
type Page = { items: Event[]; total: number; limit: number; offset: number };

/** Present audit activity separately from user and role administration. */
export default function AuditPage({ user }: { user: User }) {
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState<Page | null>(null);
  const [canExport, setCanExport] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const query = params.toString();
  const allowed = user.role === 'Administrator' || user.role === 'Auditor';
  useEffect(() => {
    if (!allowed) { setLoading(false); return; }
    let active = true;
    setLoading(true); setError(''); setPage(null);
    Promise.all([api<Page>(`/audit-logs?${query}`), api<{ export: boolean }>('/applications/capabilities')])
      .then(([result, caps]) => { if (active) { setPage(result); setCanExport(caps.export); } })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Unable to load audit logs.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [allowed, query, revision]);
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== 'offset') next.delete('offset');
    setParams(next);
  }
  async function exportAudit() {
    const next = new URLSearchParams(params);
    next.delete('offset'); next.delete('limit'); next.set('format', 'csv');
    setSaving(true); setError('');
    try { await downloadCsv(`/audit-logs?${next}`, 'audit.csv'); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Export failed.'); }
    finally { setSaving(false); }
  }
  return <main className="content">
    <p className="eyebrow">GOVERNANCE</p>
    <h1>Audit log</h1>
    {!allowed && <p role="alert">Permission denied.</p>}
    {allowed && <>
      <section aria-label="Audit filters" className="mt-6 grid gap-4 md:grid-cols-3">
        <label>User ID<input value={params.get('userId') ?? ''} onChange={event => filter('userId', event.target.value)} /></label>
        <label>Action<input value={params.get('action') ?? ''} onChange={event => filter('action', event.target.value)} /></label>
        <label>From<input type="date" value={params.get('from') ?? ''} onChange={event => filter('from', event.target.value)} /></label>
        <label>To<input type="date" value={params.get('to') ?? ''} onChange={event => filter('to', event.target.value)} /></label>
      </section>
      {error && <p role="alert" className="error">{error}</p>}
      {loading && <p role="status">Loading audit log…</p>}
      {!loading && error && <button onClick={() => setRevision(value => value + 1)}>Retry</button>}
      {page && <section aria-label="Audit results" className="mt-8">
        {canExport && <button disabled={saving} onClick={exportAudit}>Export CSV</button>}
        <p>{page.total} events</p>
        {page.items.length === 0 ? <p>No events match these filters.</p> : <div className="overflow-x-auto"><table className="w-full text-left">
          <thead><tr>{['Timestamp', 'User', 'User ID', 'Action', 'Entity', 'Entity ID', 'Details'].map(label => <th scope="col" className="p-3 border-b border-outline-variant" key={label}>{label}</th>)}</tr></thead>
          <tbody>{page.items.map(item => <tr key={item.id}>{[item.timestamp, item.userName, item.userId, item.action, item.entityType, item.entityId, item.details].map((value, index) => <td className="p-3" key={index}>{value ?? '—'}</td>)}</tr>)}</tbody>
        </table></div>}
        <div className="flex gap-4 mt-6"><button disabled={page.offset === 0} onClick={() => filter('offset', String(Math.max(0, page.offset - page.limit)))}>Previous</button><button disabled={page.offset + page.limit >= page.total} onClick={() => filter('offset', String(page.offset + page.limit))}>Next</button></div>
      </section>}
    </>}
  </main>;
}
