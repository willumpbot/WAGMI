import React from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { useApi } from '../hooks/useApi';
import { resolveApiBase } from '../src/api';

// ─── Types ────────────────────────────────────────────────────────────────────

type ThesisListRow = {
  symbol: string;
  price?: number;
  updated_at?: string;
  regime_label?: string;
  action?: string;
  confidence?: number;
  vote?: string;
  charts?: string[];
  error?: string;
};

type ThesisListResponse = {
  symbols: ThesisListRow[];
  ts?: number;
};

type CommitteeAgent = {
  ok?: boolean;
  narrative?: string;
  regime_label?: string;
  confidence?: number;
  bias?: string;
  vol_band?: string;
  action?: string;
  entry_low?: number;
  entry_high?: number;
  stop?: number;
  target1?: number;
  target2?: number;
  rr_t1?: number;
  rr_t2?: number;
  invalidation?: number;
  vote?: string;
  risk_flags?: string[];
  daily_slope_pct?: number;
  daily_rsi?: number;
  h1_rsi?: number;
  vol_ratio_1h?: number;
};

type ThesisFull = {
  symbol: string;
  updated_at?: string;
  price?: number;
  levels?: Record<string, unknown>;
  committee?: {
    regime?: CommitteeAgent;
    trade?: CommitteeAgent;
    critic?: CommitteeAgent;
    mode?: string;
  };
  charts?: string[];
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtUsd(n?: number): string {
  if (n == null || isNaN(n)) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD', maximumFractionDigits: 2,
  }).format(n);
}

function fmtTime(iso?: string): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return `${Math.floor(diff)}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return d.toISOString().slice(0, 16) + 'Z';
  } catch {
    return iso;
  }
}

function regimeColor(label?: string): string {
  if (!label) return '#8b949e';
  if (label.includes('bull')) return '#26a69a';
  if (label.includes('bear')) return '#ef5350';
  if (label === 'range') return '#ffc107';
  if (label.includes('volatility')) return '#ab47bc';
  return '#42a5f5';
}

function actionColor(action?: string): string {
  if (action === 'go_long') return '#26a69a';
  if (action === 'go_short') return '#ef5350';
  if (action === 'wait') return '#ffc107';
  return '#8b949e';
}

function voteColor(vote?: string): string {
  if (vote === 'pass') return '#26a69a';
  if (vote === 'veto') return '#ef5350';
  if (vote === 'reduce') return '#ffc107';
  return '#8b949e';
}

// ─── Tile ─────────────────────────────────────────────────────────────────────

function SymbolTile({ row }: { row: ThesisListRow }) {
  return (
    <Link
      href={`/thesis?sym=${row.symbol}`}
      style={{
        display: 'block', textDecoration: 'none', color: 'inherit',
        background: '#161b22', border: '1px solid #30363d', borderRadius: 12,
        padding: 18, transition: 'all 0.2s',
      }}
      onMouseEnter={e => (e.currentTarget.style.borderColor = '#58a6ff')}
      onMouseLeave={e => (e.currentTarget.style.borderColor = '#30363d')}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontSize: 22, fontWeight: 700, color: '#e6edf3' }}>{row.symbol}</div>
        <div style={{ fontSize: 18, color: '#e6edf3' }}>{fmtUsd(row.price)}</div>
      </div>
      <div style={{ fontSize: 11, color: '#8b949e', marginTop: 4 }}>
        Updated {fmtTime(row.updated_at)}
      </div>
      <div style={{ display: 'flex', gap: 10, marginTop: 12, flexWrap: 'wrap' }}>
        <span style={{
          padding: '3px 8px', borderRadius: 6, fontSize: 11, fontWeight: 600,
          background: regimeColor(row.regime_label) + '22',
          color: regimeColor(row.regime_label),
        }}>
          {row.regime_label || 'unknown'}
        </span>
        <span style={{
          padding: '3px 8px', borderRadius: 6, fontSize: 11, fontWeight: 600,
          background: actionColor(row.action) + '22',
          color: actionColor(row.action),
        }}>
          {row.action || '?'} · {row.confidence ?? '—'}%
        </span>
        <span style={{
          padding: '3px 8px', borderRadius: 6, fontSize: 11, fontWeight: 600,
          background: voteColor(row.vote) + '22',
          color: voteColor(row.vote),
        }}>
          critic: {row.vote || '?'}
        </span>
      </div>
    </Link>
  );
}

// ─── Full symbol view ─────────────────────────────────────────────────────────

function SymbolDetail({ symbol }: { symbol: string }) {
  const { data, error, isLoading } = useApi<ThesisFull>(
    `/v1/thesis/${symbol}`,
    { refreshInterval: 30000 },
  );
  const apiBase = resolveApiBase();

  if (error) return <div style={{ color: '#ef5350' }}>Error loading thesis: {String(error)}</div>;
  if (isLoading || !data) return <div style={{ color: '#8b949e' }}>Loading…</div>;
  if ((data as any).error) return <div style={{ color: '#ef5350' }}>{(data as any).error}</div>;

  const { committee, price, updated_at, charts } = data;
  const regime = committee?.regime;
  const trade = committee?.trade;
  const critic = committee?.critic;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 24 }}>
        <div>
          <div style={{ fontSize: 32, fontWeight: 700 }}>{data.symbol}</div>
          <div style={{ fontSize: 13, color: '#8b949e' }}>
            {fmtUsd(price)} · updated {fmtTime(updated_at)} · mode {committee?.mode || 'heuristic'}
          </div>
        </div>
        <Link href="/thesis" style={{ color: '#58a6ff', textDecoration: 'none' }}>
          ← all symbols
        </Link>
      </div>

      {/* Committee tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16, marginBottom: 24 }}>
        <AgentCard title="🌡 Regime" color={regimeColor(regime?.regime_label)} a={regime} fields={[
          ['Regime', regime?.regime_label],
          ['Bias', regime?.bias],
          ['Vol band', regime?.vol_band],
          ['Daily slope', regime?.daily_slope_pct != null ? `${regime.daily_slope_pct > 0 ? '+' : ''}${regime.daily_slope_pct}%` : undefined],
          ['Daily RSI', regime?.daily_rsi],
          ['1h RSI', regime?.h1_rsi],
          ['1h vol ratio', regime?.vol_ratio_1h],
        ]} />
        <AgentCard title="🎯 Trade" color={actionColor(trade?.action)} a={trade} fields={[
          ['Action', trade?.action],
          ['Confidence', trade?.confidence != null ? `${trade.confidence}%` : undefined],
          ['Entry', trade?.entry_low != null ? `${fmtUsd(trade.entry_low)} – ${fmtUsd(trade?.entry_high)}` : undefined],
          ['Stop', fmtUsd(trade?.stop)],
          ['Target 1', fmtUsd(trade?.target1)],
          ['Target 2', fmtUsd(trade?.target2)],
          ['R:R T1', trade?.rr_t1],
          ['R:R T2', trade?.rr_t2],
          ['Invalidation', fmtUsd(trade?.invalidation)],
        ]} />
        <AgentCard title="👮 Critic" color={voteColor(critic?.vote)} a={critic} fields={[
          ['Vote', critic?.vote],
          ['Risk flags', (critic?.risk_flags || []).join(', ') || 'none'],
        ]} />
      </div>

      {/* Charts */}
      <div>
        <h2 style={{ fontSize: 18, margin: '0 0 12px 0' }}>Charts</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(500px, 1fr))', gap: 14 }}>
          {(charts || []).map(c => (
            // charts is ["/thesis/btc/01.png", ...] — served by Next.js from web/public/
            <img key={c} src={c}
                 alt={c} style={{ width: '100%', borderRadius: 8, border: '1px solid #30363d' }} />
          ))}
        </div>
      </div>
    </div>
  );
}

function AgentCard({ title, color, a, fields }: {
  title: string;
  color: string;
  a?: CommitteeAgent;
  fields: Array<[string, unknown]>;
}) {
  return (
    <div style={{
      background: '#161b22', border: `1px solid ${color}55`, borderRadius: 12,
      padding: 16,
    }}>
      <div style={{ fontSize: 14, fontWeight: 700, color, marginBottom: 10 }}>{title}</div>
      <p style={{ fontSize: 13, lineHeight: 1.5, color: '#e6edf3', margin: '0 0 12px 0' }}>
        {a?.narrative || 'No analysis available.'}
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px', fontSize: 12 }}>
        {fields.filter(([_, v]) => v != null && v !== '').map(([k, v]) => (
          <React.Fragment key={k}>
            <div style={{ color: '#8b949e' }}>{k}</div>
            <div style={{ color: '#e6edf3', fontFamily: 'monospace', textAlign: 'right' }}>
              {String(v)}
            </div>
          </React.Fragment>
        ))}
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function ThesisPage() {
  const [sym, setSym] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    setSym(url.searchParams.get('sym'));
    const onPop = () => {
      const u = new URL(window.location.href);
      setSym(u.searchParams.get('sym'));
    };
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, []);

  const { data: listData, error, isLoading } = useApi<ThesisListResponse>(
    '/v1/thesis/list',
    { refreshInterval: 15000 },
  );

  return (
    <div style={{
      minHeight: '100vh', background: '#0d1117', color: '#e6edf3',
      padding: '28px 32px', fontFamily: 'Inter, -apple-system, sans-serif',
    }}>
      <Head><title>WAGMI · Live Thesis</title></Head>

      <header style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 30, fontWeight: 700 }}>
              <span style={{ color: '#ffc107' }}>WAGMI</span> · Live Quant Analyst
            </h1>
            <div style={{ fontSize: 13, color: '#8b949e', marginTop: 4 }}>
              Real-time multi-timeframe thesis · 9-agent committee · auto-refresh every 30s
            </div>
          </div>
          <nav style={{ display: 'flex', gap: 18 }}>
            <Link href="/" style={{ color: '#8b949e', textDecoration: 'none', fontSize: 13 }}>Dashboard</Link>
            <Link href="/agent-intelligence" style={{ color: '#8b949e', textDecoration: 'none', fontSize: 13 }}>Agents</Link>
            <Link href="/performance" style={{ color: '#8b949e', textDecoration: 'none', fontSize: 13 }}>Performance</Link>
          </nav>
        </div>
      </header>

      {sym ? (
        <SymbolDetail symbol={sym} />
      ) : (
        <>
          {error && <div style={{ color: '#ef5350' }}>Error: {String(error)}</div>}
          {isLoading && <div style={{ color: '#8b949e' }}>Loading symbols…</div>}
          {listData && (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 14 }}>
                {listData.symbols.map(row => (
                  <SymbolTile key={row.symbol} row={row} />
                ))}
              </div>
              {listData.symbols.length === 0 && (
                <div style={{ padding: 40, textAlign: 'center', color: '#8b949e' }}>
                  No theses yet. Run: <code style={{ color: '#58a6ff' }}>python bot/tools/live_analyst.py --loop</code>
                </div>
              )}
            </>
          )}
        </>
      )}

      <footer style={{ marginTop: 40, paddingTop: 16, borderTop: '1px solid #21262d',
                       fontSize: 11, color: '#8b949e' }}>
        Not financial advice. Structural analysis only. Live Quant Analyst by WAGMI.
      </footer>
    </div>
  );
}
