import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../api';

interface PortfolioMetric { portfolioId: string; name: string; applicationCount: number; qualityScore: number | null; applicationsAtRisk: number }
interface Dashboard { enterpriseQualityScore: number | null; applicationHealthScore: number | null; automationMaturityScore: number | null; openCriticalDefects: number; applicationsAtRisk: number; totalApplications: number; totalPortfolios: number; portfolios: PortfolioMetric[] }
interface PortfolioPage { items: { id: string; name: string }[]; total: number }

/** Display scoped, manually maintained inventory measures and filters. */
export default function DashboardPage() {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<Dashboard | null>(null);
  const [portfolios, setPortfolios] = useState<PortfolioPage['items']>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const query = params.toString();

  useEffect(() => {
    let active = true;
    setLoading(true); setData(null); setError('');
    async function load() {
      try {
        const dashboard = await api<Dashboard>(`/dashboard/executive${query ? `?${query}` : ''}`);
        const choices: PortfolioPage['items'] = [];
        let total = 0;
        do {
          const page = await api<PortfolioPage>(`/portfolios?limit=100&offset=${choices.length}`);
          choices.push(...page.items);
          total = page.total;
          if (!page.items.length) break;
        } while (choices.length < total);
        if (active) { setData(dashboard); setPortfolios(choices); }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : 'Unable to load dashboard.');
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => { active = false; };
  }, [query, revision]);

  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next);
  }
  const metrics = data && [
    ['Enterprise Quality Score', data.enterpriseQualityScore],
    ['Application Health Score', data.applicationHealthScore],
    ['Automation Maturity Score', data.automationMaturityScore],
    ['Open Critical Defects', data.openCriticalDefects],
    ['Applications at Risk', data.applicationsAtRisk],
    ['Total Applications', data.totalApplications],
    ['Total Portfolios', data.totalPortfolios],
  ] as const;
  const maxRisk = Math.max(1, ...(data?.portfolios.map(item => item.applicationsAtRisk) ?? []));

  return (
    <main className="content">
      <p className="eyebrow">QUALITY INVENTORY</p>
      <h1>Executive Dashboard</h1>
      <p className="notice">Scores, coverage, defects and risk are manually maintained inventory values, not live measurements.</p>
      <section aria-label="Dashboard filters" className="mt-6 grid gap-4 md:grid-cols-3">
        <label htmlFor="dashboard-portfolio">Portfolio
          <select id="dashboard-portfolio" value={params.get('portfolioId') ?? ''} onChange={event => filter('portfolioId', event.target.value)}>
            <option value="">All portfolios</option>
            {portfolios.map(portfolio => <option key={portfolio.id} value={portfolio.id}>{portfolio.name}</option>)}
          </select>
        </label>
        <label htmlFor="dashboard-area">Product area
          <input id="dashboard-area" value={params.get('productArea') ?? ''} onChange={event => filter('productArea', event.target.value)} />
        </label>
        <label htmlFor="dashboard-risk">Risk level
          <select id="dashboard-risk" value={params.get('riskLevel') ?? ''} onChange={event => filter('riskLevel', event.target.value)}>
            <option value="">All risk levels</option>
            <option>Low</option>
            <option>Medium</option>
            <option>High</option>
          </select>
        </label>
      </section>
      {loading && <p role="status">Loading dashboard…</p>}
      {error && <div role="alert">
        <p className="error">{error}</p>
        <button type="button" onClick={() => setRevision(value => value + 1)}>Retry</button>
      </div>}
      {data && (
        <>
          {data.totalApplications === 0 && <p role="status" className="mt-6">No applications match these filters.</p>}
          <section aria-label="Executive metrics" className="grid gap-4 mt-8 sm:grid-cols-2 lg:grid-cols-4">
            {metrics && metrics.map(([label, value]) => (
              <div className="card" key={label}>
                <p>{label}</p>
                <strong className="text-3xl tabular-nums">{value ?? 'Unavailable'}</strong>
              </div>
            ))}
          </section>
          {data.portfolios.length > 0 && (
            <div className="grid gap-6 mt-8 lg:grid-cols-2">
              <section className="card" aria-labelledby="quality-heading">
                <h2 id="quality-heading">Portfolio Quality Score</h2>
                <ul>
                  {data.portfolios.map(item => (
                    <li key={item.portfolioId} className="py-3">
                      <div className="flex justify-between gap-4">
                        <span>{item.name}</span>
                        <strong>{item.qualityScore ?? 'Unavailable'}</strong>
                      </div>
                      {item.qualityScore !== null && <div className="h-2 bg-surface-container mt-2" aria-hidden="true">
                        <div className="h-full bg-primary" style={{ width: `${item.qualityScore}%` }} />
                      </div>}
                    </li>
                  ))}
                </ul>
              </section>
              <section className="card" aria-labelledby="risk-heading">
                <h2 id="risk-heading">Applications at Risk by Portfolio</h2>
                <ul>
                  {data.portfolios.map(item => (
                    <li key={item.portfolioId} className="py-3">
                      <div className="flex justify-between gap-4">
                        <span>{item.name}</span>
                        <strong>{item.applicationsAtRisk}</strong>
                      </div>
                      <div className="h-2 bg-surface-container mt-2" aria-hidden="true">
                        <div className="h-full bg-primary" style={{ width: `${item.applicationsAtRisk / maxRisk * 100}%` }} />
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          )}
        </>
      )}
    </main>
  );
}
