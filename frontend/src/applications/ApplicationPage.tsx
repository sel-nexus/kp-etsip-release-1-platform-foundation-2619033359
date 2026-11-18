import { useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { api } from '../api';
import type { User } from '../types';

type Fields = {
  name: string; description: string; portfolioId: string; productArea: string;
  businessOwner: string; technologyOwner: string; etsOwner: string; criticality: string;
  tier: number; lifecycleStatus: string; technologyStack: string;
  repositoryLink: string | null; pipelineLink: string | null;
  applicationHealthScore: number; qualityScore: number; automationCoverage: number;
  unitTestCoverage: number; openDefects: number; openCriticalDefects: number; riskLevel: string;
};
type Application = Fields & { id: string; createdAt: string; updatedAt: string };
type Portfolio = { id: string; name: string };
type Page<T> = { items: T[]; total: number; limit: number; offset: number };
const empty: Fields = { name: '', description: '', portfolioId: '', productArea: '', businessOwner: '', technologyOwner: '', etsOwner: '', criticality: 'Medium', tier: 1, lifecycleStatus: 'Active', technologyStack: '', repositoryLink: null, pipelineLink: null, applicationHealthScore: 0, qualityScore: 0, automationCoverage: 0, unitTestCoverage: 0, openDefects: 0, openCriticalDefects: 0, riskLevel: 'Low' };
const textFields: [keyof Fields, string][] = [['name', 'Name'], ['description', 'Description'], ['productArea', 'Product area'], ['businessOwner', 'Business owner'], ['technologyOwner', 'Technology owner'], ['etsOwner', 'ETS owner'], ['technologyStack', 'Technology stack'], ['repositoryLink', 'Repository link'], ['pipelineLink', 'Pipeline link']];
const numberFields: [keyof Fields, string, number | undefined][] = [['tier', 'Tier', 4], ['applicationHealthScore', 'Health score', 100], ['qualityScore', 'Quality score', 100], ['automationCoverage', 'Automation coverage %', 100], ['unitTestCoverage', 'Unit-test coverage %', 100], ['openDefects', 'Open defects', undefined], ['openCriticalDefects', 'Open critical defects', undefined]];
const choices: [keyof Fields, string, string[]][] = [['criticality', 'Criticality', ['Low', 'Medium', 'High', 'Critical']], ['lifecycleStatus', 'Lifecycle status', ['Active', 'Deprecated', 'Retired']], ['riskLevel', 'Risk level', ['Low', 'Medium', 'High']]];
const message = (error: unknown) => error instanceof Error ? error.message : 'Request failed. Please try again.';

/** Manage and inspect application inventory through the authenticated API. */
export default function ApplicationPage({ user }: { user: User }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState<Page<Application> | null>(null);
  const [detail, setDetail] = useState<Application | null>(null);
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [fields, setFields] = useState<Fields>(empty);
  const [editing, setEditing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [revision, setRevision] = useState(0);
  const [permissions, setPermissions] = useState({ create: false, edit: false, delete: false, export: false });
  const query = params.toString();
  const canCreate = permissions.create;
  const canEdit = permissions.edit && !!detail && (user.role !== 'Portfolio Leader' || user.portfolioAccess.includes(detail.portfolioId));

  useEffect(() => {
    let active = true;
    async function load() {
      setLoading(true); setError(''); setPage(null); setDetail(null);
      try {
        const capabilities = await api<{create: boolean; edit: boolean; delete: boolean; export: boolean}>('/applications/capabilities');
        // Fetch all visible portfolios in bounded pages for the selector and labels.
        const all: Portfolio[] = [];
        let offset = 0;
        let total = 0;
        do {
          const result = await api<Page<Portfolio>>(`/portfolios?limit=100&offset=${offset}`);
          all.push(...result.items); total = result.total; offset += 100;
        } while (offset < total);
        const result = id ? await api<Application>(`/applications/${encodeURIComponent(id)}`) : await api<Page<Application>>(`/applications${query ? `?${query}` : ''}`);
        if (active) {
          setPermissions(capabilities);
          setPortfolios(all);
          if ('items' in result) setPage(result); else setDetail(result);
        }
      } catch (reason) { if (active) setError(message(reason)); }
      finally { if (active) setLoading(false); }
    }
    void load();
    return () => { active = false; };
  }, [id, query, revision]);

  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    if (key !== 'offset') next.delete('offset');
    setParams(next);
  }
  function startEdit(app?: Application) {
    if (app) {
      const { id: _id, createdAt: _created, updatedAt: _updated, ...editable } = app;
      setFields(editable);
    } else setFields({ ...empty, portfolioId: portfolios[0]?.id ?? '' });
    setError(''); setNotice(''); setEditing(true);
  }
  async function save(event: FormEvent) {
    event.preventDefault(); setSaving(true); setError('');
    try {
      const saved = await api<Application>(id ? `/applications/${encodeURIComponent(id)}` : '/applications', { method: id ? 'PUT' : 'POST', body: JSON.stringify(fields) });
      setEditing(false); setNotice('Application saved.');
      if (id === saved.id) setRevision(value => value + 1); else navigate(`/applications/${saved.id}`);
    } catch (reason) { setError(message(reason)); } finally { setSaving(false); }
  }
  async function remove() {
    if (!id || !window.confirm('Delete this application? This cannot be undone.')) return;
    setSaving(true); setError('');
    try { await api(`/applications/${encodeURIComponent(id)}`, { method: 'DELETE' }); setNotice('Application deleted.'); navigate('/applications'); }
    catch (reason) { setError(message(reason)); } finally { setSaving(false); }
  }
  async function exportCsv() {
    setSaving(true); setError('');
    try {
      const filters = new URLSearchParams(params);
      filters.delete('offset'); filters.delete('limit');
      const blob = await api<Blob>(`/applications/export?${filters.toString()}`, {}, 'blob');
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url; link.download = 'applications.csv'; link.click();
      URL.revokeObjectURL(url);
    } catch (reason) { setError(message(reason)); } finally { setSaving(false); }
  }
  const portfolioName = (identifier: string) => portfolios.find(item => item.id === identifier)?.name ?? identifier;
  return (
    <main className="content">
      <p className="eyebrow">INVENTORY</p>
      <h1>{id ? 'Application detail' : 'Application Repository'}</h1>
      {id && <p><Link to="/applications">Back to applications</Link></p>}
      {notice && <p role="status" className="success">{notice}</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {loading && <p role="status">Loading applications…</p>}
      {!loading && error && <button type="button" onClick={() => setRevision(value => value + 1)}>Retry</button>}
      {!id && !editing && !loading && canCreate && <button type="button" onClick={() => startEdit()}>Create application</button>}
      {!id && !editing && !loading && permissions.export && <button type="button" disabled={saving} onClick={exportCsv}>Export CSV</button>}
      {!id && !editing && (
        <section aria-label="Application filters" className="mt-6 grid gap-4 md:grid-cols-3">
          <label>Search<input value={params.get('search') ?? ''} onChange={event => filter('search', event.target.value)} /></label>
          <label>Portfolio<select value={params.get('portfolioId') ?? ''} onChange={event => filter('portfolioId', event.target.value)}><option value="">All portfolios</option>{portfolios.map(portfolio => <option key={portfolio.id} value={portfolio.id}>{portfolio.name}</option>)}</select></label>
          {choices.map(([key, label, options]) => <label key={key}>{label}<select value={params.get(key) ?? ''} onChange={event => filter(key, event.target.value)}><option value="">All {label.toLowerCase()} values</option>{options.map(option => <option key={option}>{option}</option>)}</select></label>)}
        </section>
      )}
      {editing && (
        <form onSubmit={save} className="card max-w-2xl">
          <h2>{id ? 'Edit application' : 'Create application'}</h2>
          {textFields.map(([key, label]) => <label key={key}>{label}<input type={key.endsWith('Link') ? 'url' : 'text'} required={key === 'name'} value={String(fields[key] ?? '')} onChange={event => setFields({ ...fields, [key]: event.target.value || (key.endsWith('Link') ? null : '') })} /></label>)}
          <label>Portfolio<select required value={fields.portfolioId} onChange={event => setFields({ ...fields, portfolioId: event.target.value })}><option value="">Select portfolio</option>{portfolios.map(portfolio => <option key={portfolio.id} value={portfolio.id}>{portfolio.name}</option>)}</select></label>
          {choices.map(([key, label, options]) => <label key={key}>{label}<select value={String(fields[key])} onChange={event => setFields({ ...fields, [key]: event.target.value })}>{options.map(option => <option key={option}>{option}</option>)}</select></label>)}
          {numberFields.map(([key, label, max]) => <label key={key}>{label}<input type="number" required min={key === 'tier' ? 1 : 0} max={max} step={1} value={String(fields[key])} onChange={event => setFields({ ...fields, [key]: event.target.value === '' ? '' : Number(event.target.value) })} /></label>)}
          <div className="flex gap-4"><button disabled={saving}>Save application</button><button type="button" className="text-button" onClick={() => setEditing(false)}>Cancel</button></div>
        </form>
      )}
      {!id && !editing && page && (
        <section className="mt-8" aria-label="Application results">
          <p>{page.total} applications</p>
          {page.items.length === 0 ? <p>No applications match these filters.</p> : <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr>{['Name', 'Portfolio', 'Criticality', 'Tier', 'Lifecycle status', 'Health score', 'Automation coverage %', 'Open critical defects', 'Risk level'].map(label => <th className="p-3 border-b border-outline-variant" scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{page.items.map(app => <tr key={app.id}><td className="p-3"><Link to={`/applications/${app.id}`}>{app.name}</Link></td><td className="p-3">{portfolioName(app.portfolioId)}</td><td className="p-3">{app.criticality}</td><td className="p-3">{app.tier}</td><td className="p-3">{app.lifecycleStatus}</td><td className="p-3">{app.applicationHealthScore}</td><td className="p-3">{app.automationCoverage}%</td><td className="p-3">{app.openCriticalDefects}</td><td className="p-3">{app.riskLevel}</td></tr>)}</tbody></table></div>}
          <div className="flex gap-4 mt-6"><button disabled={page.offset === 0} onClick={() => filter('offset', String(Math.max(0, page.offset - page.limit)))}>Previous</button><button disabled={page.offset + page.limit >= page.total} onClick={() => filter('offset', String(page.offset + page.limit))}>Next</button></div>
        </section>
      )}
      {id && detail && !editing && (
        <section className="mt-8">
          <h2>{detail.name}</h2>
          <dl><dt>Portfolio</dt><dd>{portfolioName(detail.portfolioId)}</dd>{textFields.filter(([key]) => key !== 'name').map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{key.endsWith('Link') && detail[key] ? <a href={String(detail[key])} target="_blank" rel="noreferrer">{String(detail[key])}</a> : String(detail[key] || 'Not specified')}</dd></div>)}{choices.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{String(detail[key])}</dd></div>)}{numberFields.map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{String(detail[key])}</dd></div>)}</dl>
          <div className="flex gap-4 mt-6">{canEdit && <button onClick={() => startEdit(detail)}>Edit application</button>}{permissions.delete && <button disabled={saving} onClick={remove}>Delete application</button>}</div>
        </section>
      )}
    </main>
  );
}
