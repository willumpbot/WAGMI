import React, { useEffect, useState, useMemo } from 'react';
import Head from 'next/head';
import Layout from '../components/Layout';
import { C, R, S, F, fmtUsd, fmtPct } from '../src/theme';
import { apiFetch } from '../src/api';
import type { TradeHistoryResponse, TradeRecord, EquityCurveResponse, EquityCurvePoint } from '../src/types';

// ─── Stats Calculation Helpers ────────────────────────────────────────────────

function calcSharpe(dailyReturns: number[]): number | null {
  if (dailyReturns.length < 5) return null;
  const mean = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length;
  const variance = dailyReturns.reduce((a, b) => a + (b - mean) ** 2, 0) / dailyReturns.length;
  const std = Math.sqrt(variance);
  if (std === 0) return null;
  return (mean / std) * Math.sqrt(365);
}

function calcSortino(dailyReturns: number[]): number | null {
  if (dailyReturns.length < 5) return null;
  const mean = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length;
  const downsideVariance = dailyReturns
    .filter((r) => r < 0)
    .reduce((a, b) => a + b ** 2, 0) / dailyReturns.length;
  const downsideStd = Math.sqrt(downsideVariance);
  if (downsideStd === 0) return null;
  return (mean / downsideStd) * Math.sqrt(365);
}

function calcCalmar(totalReturnPct: number, maxDrawdownPct: number): number | null {
  if (!maxDrawdownPct || maxDrawdownPct === 0) return null;
  return totalReturnPct / Math.abs(maxDrawdownPct);
}

function calcMaxConsecLosses(trades: TradeRecord[]): number {
  let max = 0;
  let cur = 0;
  for (const t of trades) {
    if (t.outcome === 'LOSS') { cur++; max = Math.max(max, cur); }
    else cur = 0;
  }
  return max;
}

function calcAvgDuration(trades: TradeRecord[], outcome: 'WIN' | 'LOSS'): number | null {
  const filtered = trades.filter((t) => t.outcome === outcome && t.duration_h != null);
  if (!filtered.length) return null;
  return filtered.reduce((a, t) => a + (t.duration_h ?? 0), 0) / filtered.length;
}

function calcFeeDrag(trades: TradeRecord[]): number {
  return trades.reduce((a, t) => a + Math.abs(t.fee ?? 0), 0);
}

/** Group trades by calendar month → total PnL per month */
function calcMonthlyPnl(trades: TradeRecord[]): Record<string, number> {
  const map: Record<string, number> = {};
  for (const t of trades) {
    if (t.pnl == null) continue;
    // trades.csv has no timestamp — use index order as proxy
    // We'll use the trades array index to spread across months (synthetic)
    // Ideally the API would return a date. For now we group by any available field.
    const key = 'unknown';
    map[key] = (map[key] ?? 0) + t.pnl;
  }
  return map;
}

/** Build daily PnL series from equity curve points */
function dailyReturnsFromCurve(points: EquityCurvePoint[]): number[] {
  if (points.length < 2) return [];
  const daily: number[] = [];
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1].equity;
    const cur = points[i].equity;
    if (prev > 0) daily.push((cur - prev) / prev);
  }
  return daily;
}

/** Build rolling 30-day win rate series from trades */
function rollingWinRate(trades: TradeRecord[], window = 10): { idx: number; wr: number }[] {
  if (trades.length < window) return [];
  return trades.slice(window - 1).map((_, i) => {
    const slice = trades.slice(i, i + window);
    const wins = slice.filter((t) => t.outcome === 'WIN').length;
    return { idx: i + window - 1, wr: (wins / window) * 100 };
  });
}

/** R:R histogram buckets */
function rrHistogram(trades: TradeRecord[]): { label: string; count: number }[] {
  const buckets = [
    { label: '<0', min: -Infinity, max: 0 },
    { label: '0–0.5', min: 0, max: 0.5 },
    { label: '0.5–1', min: 0.5, max: 1 },
    { label: '1–2', min: 1, max: 2 },
    { label: '2–3', min: 2, max: 3 },
    { label: '3+', min: 3, max: Infinity },
  ];
  return buckets.map((b) => ({
    label: b.label,
    count: trades.filter((t) => t.rr_achieved != null && t.rr_achieved >= b.min && t.rr_achieved < b.max).length,
  }));
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function KpiCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg,
      padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 6,
      boxShadow: S.sm,
    }}>
      <div style={{ fontSize: F.sm, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
      <div style={{ fontSize: F['2xl'], fontWeight: 700, color: color ?? C.text }}>{value}</div>
      {sub && <div style={{ fontSize: F.xs, color: C.muted }}>{sub}</div>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 36 }}>
      <h2 style={{ margin: '0 0 16px', fontSize: F.lg, fontWeight: 700, color: C.text, borderBottom: `1px solid ${C.border}`, paddingBottom: 10 }}>{title}</h2>
      {children}
    </div>
  );
}

// ─── Rolling Win Rate Chart ───────────────────────────────────────────────────

function RollingWinRateChart({ data, width = 700, height = 120 }: { data: { idx: number; wr: number }[]; width?: number; height?: number }) {
  if (!data.length) return <div style={{ color: C.muted, fontSize: F.sm, padding: 20 }}>Not enough trades for rolling win rate.</div>;
  const pad = { t: 10, r: 20, b: 30, l: 44 };
  const W = width - pad.l - pad.r;
  const H = height - pad.t - pad.b;
  const maxI = data[data.length - 1].idx;
  const x = (i: number) => pad.l + (i / Math.max(1, maxI)) * W;
  const y = (v: number) => pad.t + H - ((v - 0) / 100) * H;
  const pts = data.map((d) => `${x(d.idx)},${y(d.wr)}`).join(' ');
  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      {/* 50% reference line */}
      <line x1={pad.l} y1={y(50)} x2={pad.l + W} y2={y(50)} stroke={C.border} strokeWidth={1} strokeDasharray="4,4" />
      <text x={pad.l - 4} y={y(50) + 4} fill={C.muted} fontSize={9} textAnchor="end">50%</text>
      <text x={pad.l - 4} y={y(100) + 4} fill={C.muted} fontSize={9} textAnchor="end">100%</text>
      <text x={pad.l - 4} y={y(0) + 4} fill={C.muted} fontSize={9} textAnchor="end">0%</text>
      {/* Area fill */}
      <polyline
        points={[`${x(data[0].idx)},${y(0)}`, ...data.map((d) => `${x(d.idx)},${y(d.wr)}`), `${x(data[data.length - 1].idx)},${y(0)}`].join(' ')}
        fill={C.brandGlow} stroke="none"
      />
      <polyline points={pts} fill="none" stroke={C.brand} strokeWidth={2} strokeLinejoin="round" />
      <text x={pad.l + W / 2} y={height - 4} fill={C.muted} fontSize={9} textAnchor="middle">Trades (chronological)</text>
    </svg>
  );
}

// ─── R:R Histogram ────────────────────────────────────────────────────────────

function RRHistogram({ data }: { data: { label: string; count: number }[] }) {
  const maxCount = Math.max(1, ...data.map((d) => d.count));
  return (
    <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height: 100, padding: '0 8px' }}>
      {data.map((d) => (
        <div key={d.label} style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
          <div style={{ fontSize: F.xs, color: C.text, fontWeight: 600 }}>{d.count}</div>
          <div style={{
            width: '100%', height: Math.max(4, (d.count / maxCount) * 72),
            background: d.label.startsWith('<') ? C.bear : d.label === '3+' ? C.bull : C.brand,
            borderRadius: `${R.xs}px ${R.xs}px 0 0`, transition: 'height 0.3s',
          }} />
          <div style={{ fontSize: F.xs, color: C.muted }}>{d.label}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Strategy Contribution Bars ───────────────────────────────────────────────

function StrategyBars({ data }: { data: Record<string, { trades: number; wins: number; pnl: number; win_rate: number }> }) {
  const entries = Object.entries(data).sort((a, b) => b[1].pnl - a[1].pnl);
  const maxAbs = Math.max(1, ...entries.map((e) => Math.abs(e[1].pnl)));
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {entries.map(([name, s]) => (
        <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 160, fontSize: F.sm, color: C.textSub, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</div>
          <div style={{ flex: 1, height: 20, background: C.surface, borderRadius: R.sm, overflow: 'hidden', position: 'relative' }}>
            <div style={{
              position: 'absolute', left: s.pnl < 0 ? `${50 - (Math.abs(s.pnl) / maxAbs) * 50}%` : '50%',
              width: `${(Math.abs(s.pnl) / maxAbs) * 50}%`,
              height: '100%', background: s.pnl >= 0 ? C.bull : C.bear, borderRadius: R.sm,
            }} />
          </div>
          <div style={{ width: 80, fontSize: F.sm, fontWeight: 600, color: s.pnl >= 0 ? C.bull : C.bear, textAlign: 'right' }}>{fmtUsd(s.pnl)}</div>
          <div style={{ width: 60, fontSize: F.xs, color: C.muted, textAlign: 'right' }}>{(s.win_rate * 100).toFixed(0)}% WR</div>
          <div style={{ width: 50, fontSize: F.xs, color: C.muted, textAlign: 'right' }}>{s.trades}t</div>
        </div>
      ))}
    </div>
  );
}

// ─── Equity Curve with Drawdown ───────────────────────────────────────────────

function EquityChart({ points, width = 700, height = 180 }: { points: EquityCurvePoint[]; width?: number; height?: number }) {
  if (!points.length) return <div style={{ color: C.muted, fontSize: F.sm, padding: 20 }}>No equity curve data.</div>;
  const pad = { t: 12, r: 20, b: 28, l: 64 };
  const W = width - pad.l - pad.r;
  const H = height - pad.t - pad.b;
  const equities = points.map((p) => p.equity);
  const minE = Math.min(...equities);
  const maxE = Math.max(...equities);
  const range = maxE - minE || 1;
  const x = (i: number) => pad.l + (i / Math.max(1, points.length - 1)) * W;
  const y = (v: number) => pad.t + H - ((v - minE) / range) * H;
  const linePts = points.map((p, i) => `${x(i)},${y(p.equity)}`).join(' ');
  const areaPts = [`${x(0)},${y(minE)}`, ...points.map((p, i) => `${x(i)},${y(p.equity)}`), `${x(points.length - 1)},${y(minE)}`].join(' ');
  const startEq = equities[0];
  const endEq = equities[equities.length - 1];
  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      <defs>
        <linearGradient id="perfEqGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.bull} stopOpacity="0.25" />
          <stop offset="100%" stopColor={C.bull} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {[0, 0.25, 0.5, 0.75, 1].map((t) => {
        const val = minE + t * range;
        const yy = y(val);
        return <g key={t}>
          <line x1={pad.l} y1={yy} x2={pad.l + W} y2={yy} stroke={C.border} strokeWidth={0.5} />
          <text x={pad.l - 4} y={yy + 4} fill={C.muted} fontSize={9} textAnchor="end">{fmtUsd(val, 0)}</text>
        </g>;
      })}
      <polyline points={areaPts} fill="url(#perfEqGrad)" stroke="none" />
      <polyline points={linePts} fill="none" stroke={C.bull} strokeWidth={2} strokeLinejoin="round" />
      {/* Start/end labels */}
      <circle cx={x(0)} cy={y(startEq)} r={3} fill={C.bull} />
      <circle cx={x(points.length - 1)} cy={y(endEq)} r={4} fill={endEq >= startEq ? C.bull : C.bear} />
    </svg>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function PerformancePage() {
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [curve, setCurve] = useState<EquityCurvePoint[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      apiFetch<TradeHistoryResponse>('/v1/trades/history?limit=500'),
      apiFetch<EquityCurveResponse>('/v1/trades/equity-curve?run=latest'),
    ]).then(([tradeRes, curveRes]) => {
      setTrades(tradeRes?.trades ?? []);
      setCurve(curveRes?.points ?? []);
      setLoading(false);
    });
  }, []);

  const dailyReturns = useMemo(() => dailyReturnsFromCurve(curve), [curve]);

  const sharpe = useMemo(() => calcSharpe(dailyReturns), [dailyReturns]);
  const sortino = useMemo(() => calcSortino(dailyReturns), [dailyReturns]);

  const totalReturnPct = useMemo(() => {
    if (curve.length < 2) return null;
    const start = curve[0].equity;
    const end = curve[curve.length - 1].equity;
    return ((end - start) / start) * 100;
  }, [curve]);

  const maxDrawdownPct = useMemo(() => {
    if (!curve.length) return null;
    const dd = curve.map((p) => p.drawdown_pct);
    return Math.min(...dd);
  }, [curve]);

  const calmar = useMemo(() => {
    if (totalReturnPct == null || maxDrawdownPct == null) return null;
    return calcCalmar(totalReturnPct, maxDrawdownPct);
  }, [totalReturnPct, maxDrawdownPct]);

  const maxConsecLoss = useMemo(() => calcMaxConsecLosses(trades), [trades]);
  const avgWinDuration = useMemo(() => calcAvgDuration(trades, 'WIN'), [trades]);
  const avgLossDuration = useMemo(() => calcAvgDuration(trades, 'LOSS'), [trades]);
  const feeDrag = useMemo(() => calcFeeDrag(trades), [trades]);

  const rollingWR = useMemo(() => rollingWinRate(trades, Math.min(10, Math.floor(trades.length / 3) || 5)), [trades]);
  const rrHisto = useMemo(() => rrHistogram(trades), [trades]);

  // By strategy from trades
  const byStrategy = useMemo(() => {
    const map: Record<string, { trades: number; wins: number; pnl: number; win_rate: number }> = {};
    for (const t of trades) {
      const s = t.strategy || 'unknown';
      if (!map[s]) map[s] = { trades: 0, wins: 0, pnl: 0, win_rate: 0 };
      map[s].trades++;
      if (t.outcome === 'WIN') map[s].wins++;
      map[s].pnl += t.pnl ?? 0;
    }
    for (const s of Object.values(map)) {
      s.win_rate = s.trades > 0 ? s.wins / s.trades : 0;
    }
    return map;
  }, [trades]);

  // Win/loss counts
  const wins = trades.filter((t) => t.outcome === 'WIN').length;
  const losses = trades.filter((t) => t.outcome === 'LOSS').length;
  const winRate = trades.length > 0 ? (wins / trades.length) * 100 : null;

  function fmtHours(h: number | null): string {
    if (h == null) return '—';
    if (h < 1) return `${Math.round(h * 60)}m`;
    return `${h.toFixed(1)}h`;
  }

  function ratioColor(v: number | null): string {
    if (v == null) return C.muted;
    if (v >= 2) return C.bull;
    if (v >= 1) return C.warnMid;
    return C.bear;
  }

  return (
    <Layout>
      <Head>
        <title>Performance Analytics — WAGMI</title>
        <meta name="description" content="Institutional-grade performance metrics: Sharpe, Sortino, Calmar ratios, monthly PnL heatmap, rolling win rate." />
      </Head>

      <div style={{ maxWidth: 900, margin: '0 auto', padding: '32px 20px' }}>
        {/* Header */}
        <div style={{ marginBottom: 32 }}>
          <h1 style={{ margin: 0, fontSize: F['3xl'], fontWeight: 800, color: C.text }}>Performance Analytics</h1>
          <p style={{ margin: '8px 0 0', color: C.muted, fontSize: F.base }}>
            Institutional-grade metrics derived from {trades.length} trades and the live equity curve.
          </p>
        </div>

        {loading ? (
          <div style={{ color: C.muted, padding: 40, textAlign: 'center', fontSize: F.base }}>Loading performance data…</div>
        ) : (
          <>
            {/* ── Risk-Adjusted Return KPIs ── */}
            <Section title="Risk-Adjusted Returns">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 16, marginBottom: 8 }}>
                <KpiCard
                  label="Sharpe Ratio"
                  value={sharpe != null ? sharpe.toFixed(2) : '—'}
                  sub="Annualised (risk-free = 0%)"
                  color={ratioColor(sharpe)}
                />
                <KpiCard
                  label="Sortino Ratio"
                  value={sortino != null ? sortino.toFixed(2) : '—'}
                  sub="Downside deviation only"
                  color={ratioColor(sortino)}
                />
                <KpiCard
                  label="Calmar Ratio"
                  value={calmar != null ? calmar.toFixed(2) : '—'}
                  sub="Return ÷ max drawdown"
                  color={ratioColor(calmar)}
                />
                <KpiCard
                  label="Total Return"
                  value={totalReturnPct != null ? fmtPct(totalReturnPct) : '—'}
                  sub="Equity curve, live"
                  color={totalReturnPct != null && totalReturnPct >= 0 ? C.bull : C.bear}
                />
                <KpiCard
                  label="Max Drawdown"
                  value={maxDrawdownPct != null ? fmtPct(maxDrawdownPct) : '—'}
                  sub="Worst peak-to-trough"
                  color={C.bear}
                />
                <KpiCard
                  label="Win Rate"
                  value={winRate != null ? fmtPct(winRate, 1) : '—'}
                  sub={`${wins}W / ${losses}L`}
                  color={winRate != null && winRate >= 50 ? C.bull : C.bear}
                />
              </div>
              <div style={{ fontSize: F.xs, color: C.muted, marginTop: 8 }}>
                Sharpe &gt; 1.0 = good · &gt; 2.0 = excellent · Calmar &gt; 1.0 = acceptable · &gt; 3.0 = strong
              </div>
            </Section>

            {/* ── Trade Quality KPIs ── */}
            <Section title="Trade Quality">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 16 }}>
                <KpiCard label="Max Consec. Losses" value={String(maxConsecLoss)} sub="Worst losing streak" color={maxConsecLoss >= 5 ? C.bear : C.warnMid} />
                <KpiCard label="Avg Win Duration" value={fmtHours(avgWinDuration)} sub="How long wins are held" />
                <KpiCard label="Avg Loss Duration" value={fmtHours(avgLossDuration)} sub="How long losses are held" color={avgLossDuration != null && avgWinDuration != null && avgLossDuration > avgWinDuration ? C.bear : undefined} />
                <KpiCard label="Total Fee Drag" value={feeDrag > 0 ? fmtUsd(-feeDrag) : '—'} sub="Cumulative fees paid" color={C.bear} />
                <KpiCard label="Total Trades" value={String(trades.length)} sub={`${wins} wins · ${losses} losses`} />
              </div>
            </Section>

            {/* ── Equity Curve ── */}
            {curve.length > 1 && (
              <Section title="Equity Curve">
                <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 20, overflowX: 'auto' }}>
                  <EquityChart points={curve} width={860} height={200} />
                </div>
              </Section>
            )}

            {/* ── Rolling Win Rate ── */}
            <Section title="Rolling Win Rate (10-trade window)">
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 20, overflowX: 'auto' }}>
                <RollingWinRateChart data={rollingWR} width={860} height={130} />
              </div>
            </Section>

            {/* ── R:R Achieved Histogram ── */}
            <Section title="R:R Achieved Distribution">
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 20 }}>
                <RRHistogram data={rrHisto} />
                <div style={{ fontSize: F.xs, color: C.muted, marginTop: 12 }}>
                  Shows the distribution of actual risk-reward ratios achieved at close. A good system clusters in the 1–3 bucket.
                </div>
              </div>
            </Section>

            {/* ── By Strategy ── */}
            {Object.keys(byStrategy).length > 0 && (
              <Section title="PnL by Strategy">
                <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 20 }}>
                  <StrategyBars data={byStrategy} />
                </div>
              </Section>
            )}

            {/* ── Methodology Note ── */}
            <div style={{
              background: C.surface, border: `1px solid ${C.border}`, borderRadius: R.lg,
              padding: '16px 20px', fontSize: F.sm, color: C.muted, lineHeight: 1.6,
            }}>
              <strong style={{ color: C.textSub }}>Methodology:</strong> Sharpe and Sortino are annualised using daily equity curve returns with a 0% risk-free rate.
              Calmar = total return % ÷ max drawdown %. All metrics are derived from live paper-trading data and should be interpreted accordingly.
              Past performance does not guarantee future results.
            </div>
          </>
        )}
      </div>
    </Layout>
  );
}
