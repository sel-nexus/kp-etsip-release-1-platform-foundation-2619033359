import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api';

type Row = { id: string; name: string; portfolioId?: string; owner?: string; productArea?: string; status?: string; applicationCount?: number; qualityScore?: number | null; criticality?: string; riskLevel?: string; lifecycleStatus?: string; applicationHealthScore?: number; automationCoverage?: number; openCriticalDefects?: number };
type Page = { items: Row[]; total: number; limit: number; offset: number };

/** Download an authenticated CSV and surface errors to the caller. */
export async function downloadCsv(path: string, filename: string) {
  const blob = await api<Blob>(path, {}, 'blob');
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** Show filtered inventory reports using bounded API pages. */
export default function ReportsPage() {
  const [params, setParams] = useSearchParams();
  const kind = params.get('report') === 'portfolios' ? 'portfolios' : 'applications';
  const [page, setPage] = useState<Page | null>(null);
  const [canExport, setCanExport] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const query = new URLSearchParams(params);
  query.delete('report');
  const queryString = query.toString();

  useEffect(() => {
    let active = true;
    setLoading(true); setError(''); setPage(null);
    Promise.all([api<Page>(`/reports/${kind}?${queryString}`), api<{ export: boolean }>('/applications/capabilities')])
      .then(([result, capabilities]) => { if (active) { setPage(result); setCanExport(capabilities.export); } })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : 'Unable to load reports.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [kind, queryString, revision]);

  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (key === 'report') { setParams(value === 'portfolios' ? { report: value } : {}); return; }
    if (value) next.set(key, value); else next.delete(key);
    if (key !== 'offset') next.delete('offset');
    setParams(next);
  }
  async function exportReport() {
    setSaving(true); setError('');
    const filters = new URLSearchParams(queryString);
    filters.delete('offset'); filters.delete('limit'); filters.set('format', 'csv');
    try { await downloadCsv(`/reports/${kind}?${filters}`, `${kind}-report.csv`); }
    catch (reason) { setError(reason instanceof Error ? reason.message : 'Export failed.'); }
    finally { setSaving(false); }
  }
  return (
    <main className="content">
      <p className="eyebrow">INSIGHT</p>
      <h1>Reports</h1>
      <p>Reports use manually maintained inventory values.</p>
      <label>Report
        <select value={kind} onChange={event => filter('report', event.target.value)}>
          <option value="applications">Application Report</option>
          <option value="portfolios">Portfolio Report</option>
        </select>
      </label>
      <section aria-label="Report filters" className="mt-6 grid gap-4 md:grid-cols-3">
        <label>Search<input value={params.get('search') ?? ''} onChange={event => filter('search', event.target.value)} /></label>
        {kind === 'applications' ? <>
          <label>Portfolio ID<input value={params.get('portfolioId') ?? ''} onChange={event => filter('portfolioId', event.target.value)} /></label>
          {[['criticality', 'Criticality', ['Low', 'Medium', 'High', 'Critical']], ['riskLevel', 'Risk level', ['Low', 'Medium', 'High']], ['lifecycleStatus', 'Lifecycle status', ['Active', 'Deprecated', 'Retired']]].map(([key, label, options]) => <label key={key as string}>{label as string}<select value={params.get(key as string) ?? ''} onChange={event => filter(key as string, event.target.value)}><option value="">All</option>{(options as string[]).map(option => <option key={option}>{option}</option>)}</select></label>)}
        </> : <>
          <label>Product area<input value={params.get('productArea') ?? ''} onChange={event => filter('productArea', event.target.value)} /></label>
          <label>Status<select value={params.get('status') ?? ''} onChange={event => filter('status', event.target.value)}><option value="">All</option><option>Active</option><option>Archived</option></select></label>
        </>}
      </section>
      {error && <p role="alert" className="error">{error}</p>}
      {loading && <p role="status">Loading reports…</p>}
      {!loading && error && <button onClick={() => setRevision(value => value + 1)}>Retry</button>}
      {!loading && page && <section aria-label="Report results" className="mt-8">
        {canExport && <button type="button" disabled={saving} onClick={exportReport}>Export CSV</button>}
        <p>{page.total} results</p>
        {page.items.length === 0 ? <p>No records match these filters.</p> : <div className="overflow-x-auto"><table className="w-full text-left">
          <thead><tr>{(kind === 'applications' ? ['Name', 'Portfolio ID', 'Criticality', 'Lifecycle', 'Health', 'Quality', 'Automation %', 'Critical defects', 'Risk'] : ['Name', 'Owner', 'Product area', 'Status', 'Applications', 'Quality']).map(label => <th key={label} scope="col" className="p-3 border-b border-outline-variant">{label}</th>)}</tr></thead>
          <tbody>{page.items.map(row => <tr key={row.id}>
            <td className="p-3"><Link to={`/${kind}/${row.id}`}>{row.name}</Link></td>
            {(kind === 'applications' ? [row.portfolioId, row.criticality, row.lifecycleStatus, row.applicationHealthScore, row.qualityScore, row.automationCoverage, row.openCriticalDefects, row.riskLevel] : [row.owner, row.productArea, row.status, row.applicationCount, row.qualityScore]).map((value, index) => <td key={index} className="p-3">{value ?? 'Unavailable'}</td>)}
          </tr>)}</tbody>
        </table></div>}
        <div className="flex gap-4 mt-6"><button disabled={page.offset === 0} onClick={() => filter('offset', String(Math.max(0, page.offset - page.limit)))}>Previous</button><button disabled={page.offset + page.limit >= page.total} onClick={() => filter('offset', String(page.offset + page.limit))}>Next</button></div>
      </section>}
    </main>
  );
}
