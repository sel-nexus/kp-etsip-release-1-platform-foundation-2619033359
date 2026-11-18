import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import type { User } from '../types';

interface Fields { name: string; owner: string; description: string; productArea: string; status: 'Active' | 'Archived' }
interface Portfolio extends Fields { id: string; applicationCount: number; qualityScore: number | null }
interface Application { id: string; name: string }
interface Page<T> { items: T[]; total: number; limit: number; offset: number }
const empty: Fields = { name: '', owner: '', description: '', productArea: '', status: 'Active' };
const message = (error: unknown) => error instanceof Error ? error.message : 'Request failed. Please try again.';

/** Manage the portfolio inventory using the authenticated API. */
export default function PortfolioPage({ user }: { user: User }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState<Page<Portfolio> | null>(null);
  const [detail, setDetail] = useState<Portfolio | null>(null);
  const [apps, setApps] = useState<Page<Application> | null>(null);
  const [fields, setFields] = useState<Fields>(empty);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const leaderCanEdit = user.role === 'Portfolio Leader' && !!id && user.portfolioAccess.includes(id);
  const canEdit = user.role === 'Administrator' || leaderCanEdit;
  const query = params.toString();
  const appOffset = Math.max(0, Number.parseInt(params.get('appOffset') ?? '0', 10) || 0);

  useEffect(() => {
    let active = true;
    setLoading(true); setError(''); setPage(null); setDetail(null); setApps(null);
    const request = id
      ? Promise.all([api<Portfolio>(`/portfolios/${encodeURIComponent(id)}`), api<Page<Application>>(`/portfolios/${encodeURIComponent(id)}/applications?limit=25&offset=${appOffset}`)]).then(([portfolio, applications]) => { if (active) { setDetail(portfolio); setApps(applications); } })
      : api<Page<Portfolio>>(`/portfolios${query ? `?${query}` : ''}`).then(result => { if (active) setPage(result); });
    request.catch(reason => { if (active) setError(message(reason)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, query, revision, appOffset]);

  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== 'offset') next.delete('offset');
    setParams(next);
  }
  function startEdit(portfolio?: Portfolio) {
    setFields(portfolio ? { name: portfolio.name, owner: portfolio.owner, description: portfolio.description, productArea: portfolio.productArea, status: portfolio.status } : empty);
    setError(''); setNotice(''); setEditing(true);
  }
  async function save(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError('');
    try {
      const saved = await api<Portfolio>(id ? `/portfolios/${encodeURIComponent(id)}` : '/portfolios', { method: id ? 'PUT' : 'POST', body: JSON.stringify(fields) });
      setEditing(false); setNotice('Portfolio saved.');
      if (id === saved.id) setRevision(value => value + 1); else navigate(`/portfolios/${saved.id}`);
    } catch (reason) { setError(message(reason)); } finally { setSaving(false); }
  }
  async function remove() {
    if (!id || !window.confirm('Delete this portfolio? This cannot be undone.')) return;
    setSaving(true); setError('');
    try { await api(`/portfolios/${encodeURIComponent(id)}`, { method: 'DELETE' }); setNotice('Portfolio deleted.'); navigate('/portfolios'); }
    catch (reason) { setError(message(reason)); } finally { setSaving(false); }
  }
  return (
    <main className="content">
      <p className="eyebrow">INVENTORY</p>
      <h1>{id ? 'Portfolio detail' : 'Portfolios'}</h1>
      {id && <p><Link to="/portfolios">Back to portfolios</Link></p>}
      {notice && <p role="status" className="success">{notice}</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {loading && <p role="status">Loading portfolios…</p>}
      {!loading && error && <button type="button" onClick={() => setRevision(value => value + 1)}>Retry</button>}
      {!id && !editing && user.role === 'Administrator' && <button type="button" onClick={() => startEdit()}>Create portfolio</button>}
      {!id && !editing && (
        <section aria-label="Portfolio filters" className="mt-6 grid gap-4 md:grid-cols-3">
          <label>Search<input value={params.get('search') ?? ''} onChange={event => filter('search', event.target.value)} /></label>
          <label>Status<select value={params.get('status') ?? ''} onChange={event => filter('status', event.target.value)}><option value="">All statuses</option><option>Active</option><option>Archived</option></select></label>
          <label>Product area<input value={params.get('productArea') ?? ''} onChange={event => filter('productArea', event.target.value)} /></label>
        </section>
      )}
      {editing && (
        <form onSubmit={save} className="card max-w-2xl">
          <h2>{id ? 'Edit portfolio' : 'Create portfolio'}</h2>
          <label htmlFor="portfolio-name">Name</label><input id="portfolio-name" required maxLength={200} value={fields.name} onChange={event => setFields({ ...fields, name: event.target.value })} />
          <label htmlFor="portfolio-owner">Owner</label><input id="portfolio-owner" maxLength={200} value={fields.owner} onChange={event => setFields({ ...fields, owner: event.target.value })} />
          <label htmlFor="portfolio-area">Product area</label><input id="portfolio-area" maxLength={200} value={fields.productArea} onChange={event => setFields({ ...fields, productArea: event.target.value })} />
          <label htmlFor="portfolio-description">Description</label><textarea id="portfolio-description" className="border border-outline rounded p-3" maxLength={4000} value={fields.description} onChange={event => setFields({ ...fields, description: event.target.value })} />
          <label htmlFor="portfolio-status">Status</label><select id="portfolio-status" value={fields.status} onChange={event => setFields({ ...fields, status: event.target.value as Fields['status'] })}><option>Active</option><option>Archived</option></select>
          <div className="flex gap-4"><button disabled={saving}>Save portfolio</button><button type="button" className="text-button" onClick={() => setEditing(false)}>Cancel</button></div>
        </form>
      )}
      {!id && !editing && page && (
        <section className="mt-8" aria-label="Portfolio results">
          <p>{page.total} portfolios</p>
          {page.items.length === 0 ? <p>No portfolios match these filters.</p> : <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr>{['Name', 'Owner', 'Product Area', 'Applications', 'Quality Score', 'Status'].map(label => <th className="p-3 border-b border-outline-variant" scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{page.items.map(portfolio => <tr key={portfolio.id}><td className="p-3 border-b border-outline-variant"><Link to={`/portfolios/${portfolio.id}`}>{portfolio.name}</Link></td><td className="p-3">{portfolio.owner}</td><td className="p-3">{portfolio.productArea}</td><td className="p-3">{portfolio.applicationCount}</td><td className="p-3">{portfolio.qualityScore ?? 'Unavailable'}</td><td className="p-3">{portfolio.status}</td></tr>)}</tbody></table></div>}
          <div className="flex gap-4 mt-6"><button disabled={page.offset === 0} onClick={() => filter('offset', String(Math.max(0, page.offset - page.limit)))}>Previous</button><button disabled={page.offset + page.limit >= page.total} onClick={() => filter('offset', String(page.offset + page.limit))}>Next</button></div>
        </section>
      )}
      {id && detail && !editing && (
        <section className="mt-8">
          <h2>{detail.name}</h2>
          <p>{detail.description || 'No description provided.'}</p>
          <dl><dt>Owner</dt><dd>{detail.owner || 'Not specified'}</dd><dt>Product area</dt><dd>{detail.productArea || 'Not specified'}</dd><dt>Status</dt><dd>{detail.status}</dd><dt>Applications</dt><dd>{detail.applicationCount}</dd><dt>Quality score</dt><dd>{detail.qualityScore ?? 'Unavailable'}</dd></dl>
          <div className="flex gap-4 mt-6">{canEdit && <button onClick={() => startEdit(detail)}>Edit portfolio</button>}{user.role === 'Administrator' && <button disabled={saving} onClick={remove}>Delete portfolio</button>}</div>
          <h2 className="mt-8">Applications</h2>
          {apps && (apps.items.length ? <ul>{apps.items.map(app => <li className="py-2" key={app.id}><Link to={`/applications/${app.id}`}>{app.name}</Link></li>)}</ul> : <p>No applications in this portfolio.</p>)}
          {apps && apps.total > 0 && <p>Showing {apps.offset + 1}–{apps.offset + apps.items.length} of {apps.total} applications.</p>}
          {apps && <div className="flex gap-4"><button disabled={apps.offset === 0} onClick={() => filter('appOffset', String(Math.max(0, apps.offset - apps.limit)))}>Previous applications</button><button disabled={apps.offset + apps.limit >= apps.total} onClick={() => filter('appOffset', String(apps.offset + apps.limit))}>Next applications</button></div>}
        </section>
      )}
    </main>
  );
}
