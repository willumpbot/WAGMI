'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { C, R, S, F, fmtUsd, fmtPct, timeAgo } from '../src/theme';
import type { BacktestResult, TradeRecord, TradeHistoryResponse, EquityCurvePoint } from '../src/types';

function resolveApiBase(): string {
  const envVal =
    (process.env.NEXT_PUBLIC_API_URL as string | undefined) ||
    (process.env.NEXT_PUBLIC_API_BASE_URL as string | undefined);
  if (envVal && envVal.trim().length > 0) return envVal;
  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (host && host !== 'localhost' && host !== '127.0.0.1') return 'https://nunuirl-platform.onrender.com';
  }
  return 'http://localhost:8000';
}

function Skeleton({ h = 16, w = '100%' }: { h?: number; w?: string | number }) {
  return <div className="skeleton" style={{ height: h, width: w, borderRadius: R.sm }} />;
}

// ─── KPI Grid ─────────────────────────────────────────────────────────────────

function KpiBlock({ label, value, sub, color, big }: {
  label: string; value: string; sub?: string; color?: string; big?: boolean;
}) {
  return (
    <div style={{ padding: big ? '24px 28px' : '18px 20px', background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg }}>
      <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: big ? F['3xl'] : F['2xl'], fontWeight: 800, color: color || C.text, lineHeight: 1.1, marginBottom: sub ? 4 : 0 }}>{value}</div>
      {sub && <div style={{ fontSize: F.xs, color: C.muted }}>{sub}</div>}
    </div>
  );
}

// ─── Equity Curve SVG ─────────────────────────────────────────────────────────

function EquityCurveChart({ points, width = 700, height = 200 }: { points: EquityCurvePoint[]; width?: number; height?: number }) {
  if (!points || points.length < 2) {
    return (
      <div style={{ width: '100%', height, background: C.card, borderRadius: R.md, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.muted, fontSize: F.sm }}>
        No equity curve data available
      </div>
    );
  }

  const equities = points.map((p) => p.equity);
  const minE = Math.min(...equities);
  const maxE = Math.max(...equities);
  const rangeE = maxE - minE || 1;
  const pad = { top: 20, right: 20, bottom: 30, left: 70 };
  const W = width - pad.left - pad.right;
  const H = height - pad.top - pad.bottom;

  const px = (i: number) => pad.left + (i / (points.length - 1)) * W;
  const py = (e: number) => pad.top + H - ((e - minE) / rangeE) * H;

  const polyline = points.map((p, i) => `${px(i)},${py(p.equity)}`).join(' ');

  // Find max drawdown trough
  let runningMax = equities[0];
  let maxDdIdx = 0;
  let maxDd = 0;
  equities.forEach((e, i) => {
    if (e > runningMax) runningMax = e;
    const dd = (runningMax - e) / runningMax;
    if (dd > maxDd) { maxDd = dd; maxDdIdx = i; }
  });

  // Area fill
  const areaD = `M ${px(0)},${py(points[0].equity)} ` +
    points.slice(1).map((p, i) => `L ${px(i + 1)},${py(p.equity)}`).join(' ') +
    ` L ${px(points.length - 1)},${pad.top + H} L ${px(0)},${pad.top + H} Z`;

  const isPositive = equities[equities.length - 1] > equities[0];

  // Y-axis labels
  const yTicks = 4;
  const yLabels = Array.from({ length: yTicks + 1 }, (_, i) => {
    const val = minE + (rangeE / yTicks) * i;
    const y = py(val);
    return { val, y };
  });

  // X-axis: show first, mid, last date labels
  const xLabels = [0, Math.floor(points.length / 2), points.length - 1].map((i) => ({
    i,
    label: new Date(points[i].ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
  }));

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      style={{ width: '100%', height: 'auto', display: 'block' }}
      preserveAspectRatio="xMinYMid meet"
    >
      <defs>
        <linearGradient id="eqGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={isPositive ? C.bull : C.bear} stopOpacity={0.25} />
          <stop offset="100%" stopColor={isPositive ? C.bull : C.bear} stopOpacity={0} />
        </linearGradient>
        <linearGradient id="ddGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.bear} stopOpacity={0.2} />
          <stop offset="100%" stopColor={C.bear} stopOpacity={0} />
        </linearGradient>
      </defs>

      {/* Grid lines */}
      {yLabels.map(({ y }, i) => (
        <line key={i} x1={pad.left} y1={y} x2={pad.left + W} y2={y}
          stroke={C.border} strokeWidth={1} strokeDasharray={i === 0 ? '' : '3 4'} />
      ))}

      {/* Area fill */}
      <path d={areaD} fill="url(#eqGrad)" />

      {/* Equity line */}
      <polyline fill="none" stroke={isPositive ? C.bull : C.bear} strokeWidth={2.5}
        points={polyline} strokeLinejoin="round" strokeLinecap="round" />

      {/* Max drawdown point */}
      <circle cx={px(maxDdIdx)} cy={py(equities[maxDdIdx])} r={5}
        fill={C.bear} stroke={C.card} strokeWidth={2} />
      <text x={px(maxDdIdx) + 7} y={py(equities[maxDdIdx]) - 4}
        fill={C.bear} fontSize={10} fontFamily="Inter, system-ui">
        Max DD −{(maxDd * 100).toFixed(1)}%
      </text>

      {/* Start & end dots */}
      <circle cx={px(0)} cy={py(equities[0])} r={4} fill={C.muted} />
      <circle cx={px(points.length - 1)} cy={py(equities[points.length - 1])} r={4}
        fill={isPositive ? C.bull : C.bear} />

      {/* Y labels */}
      {yLabels.map(({ val, y }, i) => (
        <text key={i} x={pad.left - 6} y={y + 4} textAnchor="end"
          fill={C.muted} fontSize={10} fontFamily="Inter, system-ui">
          ${(val / 1000).toFixed(1)}k
        </text>
      ))}

      {/* X labels */}
      {xLabels.map(({ i, label }) => (
        <text key={i} x={px(i)} y={height - 4} textAnchor="middle"
          fill={C.muted} fontSize={10} fontFamily="Inter, system-ui">
          {label}
        </text>
      ))}
    </svg>
  );
}

// ─── Drawdown Sub-Chart ───────────────────────────────────────────────────────

function DrawdownSubChart({ points, width = 700, height = 80 }: { points: EquityCurvePoint[]; width?: number; height?: number }) {
  if (!points || points.length < 2) return null;
  const dds = points.map((p) => p.drawdown_pct ?? 0);
  const maxDd = Math.max(...dds.map(Math.abs), 0.001);
  const pad = { top: 8, right: 20, bottom: 20, left: 70 };
  const W = width - pad.left - pad.right;
  const H = height - pad.top - pad.bottom;
  const px = (i: number) => pad.left + (i / (points.length - 1)) * W;
  const py = (dd: number) => pad.top + (Math.abs(dd) / maxDd) * H;

  const areaPath = `M ${px(0)},${pad.top} ` +
    points.slice(1).map((p, i) => `L ${px(i + 1)},${py(p.drawdown_pct ?? 0)}`).join(' ') +
    ` L ${px(points.length - 1)},${pad.top} Z`;

  const worstIdx = dds.reduce((mi, dd, i) => Math.abs(dd) > Math.abs(dds[mi]) ? i : mi, 0);

  return (
    <div>
      <div style={{ fontSize: F.xs, color: C.bear, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.7, marginBottom: 4 }}>
        Drawdown
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto', display: 'block' }} preserveAspectRatio="xMinYMid meet">
        <defs>
          <linearGradient id="ddSubGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.bear} stopOpacity={0.5} />
            <stop offset="100%" stopColor={C.bear} stopOpacity={0.05} />
          </linearGradient>
        </defs>
        {/* Zero line */}
        <line x1={pad.left} y1={pad.top} x2={pad.left + W} y2={pad.top} stroke={C.border} strokeWidth={1} />
        {/* Drawdown area */}
        <path d={areaPath} fill="url(#ddSubGrad)" />
        {/* Worst drawdown marker */}
        {worstIdx > 0 && (
          <>
            <circle cx={px(worstIdx)} cy={py(dds[worstIdx])} r={3} fill={C.bear} />
            <text x={px(worstIdx) + 5} y={py(dds[worstIdx]) + 4} fill={C.bear} fontSize={9} fontFamily="Inter, system-ui">
              {dds[worstIdx].toFixed(1)}%
            </text>
          </>
        )}
        {/* Y label */}
        <text x={pad.left - 4} y={pad.top + H / 2} fill={C.muted} fontSize={9} textAnchor="end" fontFamily="Inter, system-ui">
          -{maxDd.toFixed(1)}%
        </text>
        {/* X label: dates */}
        {[0, points.length - 1].map((i) => (
          <text key={i} x={px(i)} y={pad.top + H + 14} fill={C.muted} fontSize={9} textAnchor={i === 0 ? 'start' : 'end'} fontFamily="Inter, system-ui">
            {new Date(points[i].ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
          </text>
        ))}
      </svg>
    </div>
  );
}

// ─── Strategy Bars ────────────────────────────────────────────────────────────

function ByStrategyBars({ byStrategy }: { byStrategy: Record<string, { trades: number; wins: number; pnl: number; win_rate: number }> }) {
  const entries = Object.entries(byStrategy).sort((a, b) => b[1].pnl - a[1].pnl);
  if (!entries.length) return null;
  const maxAbsPnl = Math.max(...entries.map(([, v]) => Math.abs(v.pnl)), 1);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {entries.map(([name, data]) => {
        const pct = (Math.abs(data.pnl) / maxAbsPnl) * 100;
        const isPos = data.pnl >= 0;
        const wr = (data.win_rate * 100).toFixed(0);
        return (
          <div key={name}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: F.sm }}>
              <div style={{ fontWeight: 600, color: C.text }}>
                {name}
                <span style={{ marginLeft: 8, fontSize: F.xs, color: C.muted, fontWeight: 400 }}>
                  {data.trades} trades · {wr}% WR
                </span>
              </div>
              <span style={{ fontWeight: 700, color: isPos ? C.bull : C.bear }}>{fmtUsd(data.pnl)}</span>
            </div>
            <div style={{ height: 16, background: C.surfaceHover, borderRadius: R.sm, overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${pct}%`, background: isPos ? C.bull : C.bear, borderRadius: R.sm, transition: 'width 0.5s ease', opacity: 0.8 }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Regime Win Rate ──────────────────────────────────────────────────────────

function RegimeWinRate({ trades }: { trades: TradeRecord[] }) {
  const byRegime: Record<string, { wins: number; total: number; pnl: number }> = {};
  trades.forEach((t) => {
    const regime = t.llm_regime || 'unknown';
    if (!byRegime[regime]) byRegime[regime] = { wins: 0, total: 0, pnl: 0 };
    byRegime[regime].total++;
    if (t.outcome === 'WIN') byRegime[regime].wins++;
    byRegime[regime].pnl += t.pnl ?? 0;
  });
  const entries = Object.entries(byRegime).filter(([, v]) => v.total >= 2).sort((a, b) => (b[1].wins / b[1].total) - (a[1].wins / a[1].total));
  if (!entries.length) return <div style={{ color: C.muted, fontSize: F.sm }}>Not enough data yet.</div>;

  const regimeColors: Record<string, string> = {
    trend: C.bull, range: C.info, panic: C.bear, high_volatility: C.warn, low_liquidity: C.muted, unknown: C.muted,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {entries.map(([regime, data]) => {
        const wr = data.wins / data.total;
        const color = regimeColors[regime.toLowerCase()] || C.muted;
        return (
          <div key={regime}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontSize: F.sm, fontWeight: 700, color, textTransform: 'capitalize' }}>{regime}</span>
              <div style={{ display: 'flex', gap: 12, fontSize: F.xs, color: C.muted }}>
                <span>{data.total} trades</span>
                <span style={{ fontWeight: 700, color: wr >= 0.6 ? C.bull : wr >= 0.45 ? C.warn : C.bear }}>{(wr * 100).toFixed(0)}% WR</span>
                <span style={{ color: data.pnl >= 0 ? C.bull : C.bear }}>{fmtUsd(data.pnl)}</span>
              </div>
            </div>
            <div style={{ height: 10, background: C.surfaceHover, borderRadius: R.pill, overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${wr * 100}%`, background: wr >= 0.6 ? C.bull : wr >= 0.45 ? C.warn : C.bear, borderRadius: R.pill, transition: 'width 0.5s ease' }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── By-Symbol Bars ───────────────────────────────────────────────────────────

function BySymbolBars({ bySymbol }: { bySymbol: Record<string, { trades: number; wins: number; pnl: number; win_rate: number }> }) {
  const entries = Object.entries(bySymbol).sort((a, b) => b[1].pnl - a[1].pnl);
  if (!entries.length) return null;
  const maxAbsPnl = Math.max(...entries.map(([, v]) => Math.abs(v.pnl)), 1);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {entries.map(([sym, data]) => {
        const pct = (Math.abs(data.pnl) / maxAbsPnl) * 100;
        const isPos = data.pnl >= 0;
        return (
          <div key={sym}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: F.sm }}>
              <div style={{ fontWeight: 700, color: C.text }}>
                {sym}
                <span style={{ marginLeft: 8, fontSize: F.xs, color: C.muted, fontWeight: 400 }}>
                  {data.trades} trades · {(data.win_rate * 100).toFixed(0)}% WR
                </span>
              </div>
              <span style={{ fontWeight: 700, color: isPos ? C.bull : C.bear }}>{fmtUsd(data.pnl)}</span>
            </div>
            <div style={{ height: 20, background: C.surfaceHover, borderRadius: R.sm, overflow: 'hidden' }}>
              <div
                style={{
                  height: '100%',
                  width: `${pct}%`,
                  background: isPos
                    ? `linear-gradient(90deg, ${C.bull}, ${C.bullMid})`
                    : `linear-gradient(90deg, ${C.bear}, ${C.bearMid})`,
                  borderRadius: R.sm,
                  transition: 'width 0.5s ease',
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Exit Type Donut ──────────────────────────────────────────────────────────

function ExitDonut({ byAction }: { byAction: Record<string, number> }) {
  const colors: Record<string, string> = {
    TP1: C.bull,
    TP2: '#22c55e',
    TRAILING_STOP: C.info,
    SL: C.bear,
    EARLY_EXIT: C.warn,
    CIRCUIT_BREAKER: '#7c3aed',
    BACKTEST_END: C.muted,
  };
  const entries = Object.entries(byAction).filter(([, v]) => v > 0);
  const total = entries.reduce((s, [, v]) => s + v, 0);
  if (!total) return null;

  // Simple horizontal bar breakdown
  return (
    <div>
      <div style={{ display: 'flex', height: 16, borderRadius: R.pill, overflow: 'hidden', marginBottom: 12 }}>
        {entries.map(([key, val]) => (
          <div
            key={key}
            title={`${key}: ${val} (${((val / total) * 100).toFixed(0)}%)`}
            style={{ flex: val, background: colors[key] || C.muted, transition: 'flex 0.4s' }}
          />
        ))}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
        {entries.map(([key, val]) => (
          <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: F.xs }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: colors[key] || C.muted, display: 'inline-block' }} />
            <span style={{ color: C.textSub, fontWeight: 600 }}>{key}</span>
            <span style={{ color: C.muted }}>{val} ({((val / total) * 100).toFixed(0)}%)</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Trade Table ──────────────────────────────────────────────────────────────

function TradeTable({ trades, loading }: { trades: TradeRecord[]; loading: boolean }) {
  const [sortCol, setSortCol] = useState<keyof TradeRecord>('pnl');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const sorted = [...trades].sort((a, b) => {
    const av = a[sortCol] as number | null;
    const bv = b[sortCol] as number | null;
    if (av == null) return 1;
    if (bv == null) return -1;
    return sortDir === 'asc' ? (av as number) - (bv as number) : (bv as number) - (av as number);
  });

  const cols: Array<{ key: keyof TradeRecord; label: string; render?: (t: TradeRecord) => React.ReactNode }> = [
    { key: 'symbol', label: 'Symbol', render: (t) => <span style={{ fontWeight: 700, color: C.brand }}>{t.symbol}</span> },
    {
      key: 'side', label: 'Side', render: (t) => (
        <span style={{ fontWeight: 700, color: t.side === 'LONG' || t.side === 'long' ? C.bull : C.bear }}>
          {t.side?.toUpperCase()}
        </span>
      )
    },
    { key: 'entry', label: 'Entry', render: (t) => fmtUsd(t.entry, 4) },
    { key: 'exit', label: 'Exit', render: (t) => fmtUsd(t.exit, 4) },
    {
      key: 'pnl', label: 'P&L', render: (t) => (
        <span style={{ fontWeight: 700, color: (t.pnl ?? 0) >= 0 ? C.bull : C.bear }}>
          {t.pnl != null ? (t.pnl >= 0 ? '+' : '') + fmtUsd(t.pnl) : '—'}
        </span>
      )
    },
    { key: 'leverage', label: 'Lev', render: (t) => t.leverage != null ? `${t.leverage.toFixed(1)}×` : '—' },
    { key: 'confidence', label: 'Conf', render: (t) => t.confidence != null ? `${t.confidence.toFixed(0)}%` : '—' },
    { key: 'duration_h', label: 'Duration', render: (t) => t.duration_h != null ? `${t.duration_h.toFixed(1)}h` : '—' },
    { key: 'close_reason', label: 'Exit' },
    {
      key: 'outcome', label: 'Result', render: (t) => (
        <span style={{ fontWeight: 700, padding: '2px 8px', borderRadius: R.pill, fontSize: F.xs, background: t.outcome === 'WIN' ? C.bullLight + '33' : C.bearLight + '33', color: t.outcome === 'WIN' ? C.bull : C.bear }}>
          {t.outcome}
        </span>
      )
    },
  ];

  const thStyle: React.CSSProperties = {
    padding: '10px 12px',
    fontSize: F.xs,
    color: C.muted,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    cursor: 'pointer',
    userSelect: 'none',
    whiteSpace: 'nowrap',
    background: C.surface,
  };

  return (
    <div style={{ overflowX: 'auto', borderRadius: R.md, border: `1px solid ${C.border}` }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 700 }}>
        <thead>
          <tr>
            {cols.map((col) => (
              <th
                key={col.key}
                style={{ ...thStyle, color: sortCol === col.key ? C.brand : C.muted }}
                onClick={() => {
                  if (sortCol === col.key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
                  else { setSortCol(col.key); setSortDir('desc'); }
                }}
              >
                {col.label} {sortCol === col.key ? (sortDir === 'asc' ? '↑' : '↓') : ''}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <tr key={i}>
                {cols.map((col) => (
                  <td key={col.key} style={{ padding: '10px 12px' }}><Skeleton h={12} /></td>
                ))}
              </tr>
            ))
          ) : sorted.length === 0 ? (
            <tr>
              <td colSpan={cols.length} style={{ padding: '32px', textAlign: 'center', color: C.muted, fontSize: F.sm }}>
                No trade history yet. Start the bot to see results here.
              </td>
            </tr>
          ) : (
            sorted.map((trade, i) => (
              <tr
                key={i}
                style={{
                  background: trade.outcome === 'WIN'
                    ? C.bull + '08'
                    : trade.outcome === 'LOSS' ? C.bear + '08' : 'transparent',
                  borderTop: `1px solid ${C.border}`,
                  transition: 'background 0.15s',
                }}
              >
                {cols.map((col) => (
                  <td key={col.key} style={{ padding: '10px 12px', fontSize: F.sm, color: C.textSub, whiteSpace: 'nowrap' }}>
                    {col.render ? col.render(trade) : (trade[col.key] as string | number | null) ?? '—'}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

// ─── Win/Loss Histogram ───────────────────────────────────────────────────────

type PnlBucket = { label: string; min: number; max: number; count: number; isWin: boolean };

function WinLossHistogram({ trades }: { trades: TradeRecord[] }) {
  const buckets: PnlBucket[] = [
    { label: '< −5%',    min: -Infinity, max: -5,   count: 0, isWin: false },
    { label: '−5 to −2%', min: -5,       max: -2,   count: 0, isWin: false },
    { label: '−2 to 0%', min: -2,        max: 0,    count: 0, isWin: false },
    { label: '0 to 2%',  min: 0,         max: 2,    count: 0, isWin: true  },
    { label: '2 to 5%',  min: 2,         max: 5,    count: 0, isWin: true  },
    { label: '> 5%',     min: 5,         max: Infinity, count: 0, isWin: true },
  ];

  // Fill buckets using pnl_pct if available, else rough estimate via outcome
  trades.forEach((t) => {
    const pnlPct = (t as any).pnl_pct ?? null;
    if (pnlPct == null) return;
    const val = pnlPct * 100; // convert decimal to %
    for (const b of buckets) {
      if (val > b.min && val <= b.max) { b.count++; break; }
    }
  });

  // Fallback: if no pnl_pct, try outcome-based approach
  const hasData = buckets.some((b) => b.count > 0);
  if (!hasData) {
    // Distribute by outcome as a rough fallback
    trades.forEach((t) => {
      if (t.outcome === 'WIN') buckets[3].count++;
      else if (t.outcome === 'LOSS') buckets[1].count++;
    });
  }

  const maxCount = Math.max(...buckets.map((b) => b.count), 1);
  const totalWins = buckets.filter((b) => b.isWin).reduce((s, b) => s + b.count, 0);
  const totalLosses = buckets.filter((b) => !b.isWin).reduce((s, b) => s + b.count, 0);
  const total = totalWins + totalLosses;

  // SVG dimensions
  const svgW = 700;
  const svgH = 160;
  const padL = 36;
  const padR = 16;
  const padT = 16;
  const padB = 36;
  const chartW = svgW - padL - padR;
  const chartH = svgH - padT - padB;
  const barW = chartW / buckets.length;
  const barGap = barW * 0.18;
  const zeroBucketIdx = 3; // "0 to 2%" is the first win bucket; zero line is between idx 2 and 3
  const zeroX = padL + zeroBucketIdx * barW;

  // Y gridlines
  const yTicks = [0, Math.ceil(maxCount / 4), Math.ceil(maxCount / 2), Math.ceil((3 * maxCount) / 4), maxCount];

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px', marginBottom: 28 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
        <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Trade P&amp;L Distribution</h2>
        <div style={{ display: 'flex', gap: 16, fontSize: F.sm }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: C.bull, display: 'inline-block' }} />
            <span style={{ color: C.bull, fontWeight: 700 }}>{totalWins} wins</span>
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: C.bear, display: 'inline-block' }} />
            <span style={{ color: C.bear, fontWeight: 700 }}>{totalLosses} losses</span>
          </span>
          {total > 0 && (
            <span style={{ color: C.muted }}>
              Win rate: <strong style={{ color: totalWins / total >= 0.6 ? C.bull : C.warn }}>{((totalWins / total) * 100).toFixed(0)}%</strong>
            </span>
          )}
        </div>
      </div>

      {total === 0 ? (
        <div style={{ height: svgH, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.muted, fontSize: F.sm }}>
          No trade history available yet.
        </div>
      ) : (
        <svg viewBox={`0 0 ${svgW} ${svgH}`} style={{ width: '100%', height: 'auto', display: 'block' }} preserveAspectRatio="xMinYMid meet">
          <defs>
            <linearGradient id="histBull" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={C.bull} stopOpacity={0.9} />
              <stop offset="100%" stopColor={C.bull} stopOpacity={0.5} />
            </linearGradient>
            <linearGradient id="histBear" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={C.bear} stopOpacity={0.9} />
              <stop offset="100%" stopColor={C.bear} stopOpacity={0.5} />
            </linearGradient>
          </defs>

          {/* Horizontal grid lines + Y labels */}
          {yTicks.map((tick) => {
            const y = padT + chartH - (tick / maxCount) * chartH;
            return (
              <g key={tick}>
                <line x1={padL} y1={y} x2={padL + chartW} y2={y}
                  stroke={C.border} strokeWidth={tick === 0 ? 1.5 : 1} strokeDasharray={tick === 0 ? '' : '3 4'} />
                <text x={padL - 4} y={y + 4} textAnchor="end"
                  fill={C.muted} fontSize={9} fontFamily="Inter, system-ui">{tick}</text>
              </g>
            );
          })}

          {/* Bars */}
          {buckets.map((b, i) => {
            const barH = (b.count / maxCount) * chartH;
            const x = padL + i * barW + barGap / 2;
            const w = barW - barGap;
            const y = padT + chartH - barH;
            const fill = b.isWin ? 'url(#histBull)' : 'url(#histBear)';
            return (
              <g key={b.label}>
                {b.count > 0 && (
                  <>
                    <rect x={x} y={y} width={w} height={barH} fill={fill} rx={3} />
                    <text x={x + w / 2} y={y - 4} textAnchor="middle"
                      fill={b.isWin ? C.bull : C.bear} fontSize={10} fontWeight={700} fontFamily="Inter, system-ui">
                      {b.count}
                    </text>
                  </>
                )}
                {/* X axis label */}
                <text x={x + w / 2} y={padT + chartH + 14} textAnchor="middle"
                  fill={C.muted} fontSize={9} fontFamily="Inter, system-ui">
                  {b.label}
                </text>
              </g>
            );
          })}

          {/* Zero line */}
          <line x1={zeroX} y1={padT} x2={zeroX} y2={padT + chartH}
            stroke={C.muted} strokeWidth={1.5} strokeDasharray="4 3" />
          <text x={zeroX + 3} y={padT + 10} fill={C.muted} fontSize={9} fontFamily="Inter, system-ui">0%</text>
        </svg>
      )}
    </div>
  );
}

// ─── Time-of-Day Win Rate Heatmap ─────────────────────────────────────────────

function TimeOfDayHeatmap({ trades }: { trades: TradeRecord[] }) {
  const HOURS = [0, 4, 8, 12, 16, 20]; // 4-hour UTC blocks
  const HOUR_LABELS = ['00–04', '04–08', '08–12', '12–16', '16–20', '20–24'];
  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  // Build a 7×6 grid of { wins, total }
  const grid: Record<string, { wins: number; total: number }> = {};
  DAYS.forEach((d) => HOURS.forEach((h) => { grid[`${d}_${h}`] = { wins: 0, total: 0 }; }));

  let hasTimestamps = false;
  trades.forEach((t) => {
    const ts = (t as any).entry_time ?? (t as any).timestamp ?? (t as any).created_at;
    if (!ts) return;
    const dt = new Date(ts);
    if (isNaN(dt.getTime())) return;
    hasTimestamps = true;
    const dayIdx = (dt.getUTCDay() + 6) % 7; // Mon=0
    const dayKey = DAYS[dayIdx];
    const hourBlock = HOURS.filter((h) => dt.getUTCHours() >= h).pop() ?? 0;
    const key = `${dayKey}_${hourBlock}`;
    if (!grid[key]) grid[key] = { wins: 0, total: 0 };
    grid[key].total++;
    if (t.outcome === 'WIN') grid[key].wins++;
  });

  if (!hasTimestamps) return null;

  function cellColor(wins: number, total: number): string {
    if (total === 0) return C.surface;
    const wr = wins / total;
    if (wr >= 0.8) return 'rgba(22,163,74,0.75)';
    if (wr >= 0.65) return 'rgba(22,163,74,0.5)';
    if (wr >= 0.5) return 'rgba(22,163,74,0.28)';
    if (wr >= 0.35) return 'rgba(234,179,8,0.3)';
    if (wr >= 0.2) return 'rgba(220,38,38,0.3)';
    return 'rgba(220,38,38,0.55)';
  }

  function cellText(wins: number, total: number): string {
    if (total === 0) return '—';
    return `${Math.round((wins / total) * 100)}%`;
  }

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Win Rate by Day & Time (UTC)</h2>
          <p style={{ margin: '4px 0 0', fontSize: F.xs, color: C.muted }}>When does the bot win most? Green = high win rate, red = avoid these windows.</p>
        </div>
        <div style={{ display: 'flex', gap: 10, fontSize: 10, color: C.muted, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {[['≥80%', 'rgba(22,163,74,0.75)'], ['65–80%', 'rgba(22,163,74,0.5)'], ['50–65%', 'rgba(22,163,74,0.28)'], ['35–50%', 'rgba(234,179,8,0.3)'], ['<35%', 'rgba(220,38,38,0.55)'], ['No data', C.surface]].map(([label, bg]) => (
            <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 12, height: 12, borderRadius: 2, background: bg, border: `1px solid ${C.border}`, display: 'inline-block' }} />
              {label}
            </span>
          ))}
        </div>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'separate', borderSpacing: 3, minWidth: 420 }}>
          <thead>
            <tr>
              <th style={{ width: 38, padding: '4px 6px', fontSize: 10, color: C.muted, textAlign: 'right', paddingRight: 8 }} />
              {HOUR_LABELS.map((h) => (
                <th key={h} style={{ padding: '4px 2px', fontSize: 9, color: C.muted, fontWeight: 600, textAlign: 'center', minWidth: 54 }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DAYS.map((day) => (
              <tr key={day}>
                <td style={{ padding: '2px 8px 2px 0', fontSize: 10, color: C.muted, fontWeight: 600, textAlign: 'right', whiteSpace: 'nowrap' }}>{day}</td>
                {HOURS.map((h) => {
                  const { wins, total } = grid[`${day}_${h}`] ?? { wins: 0, total: 0 };
                  return (
                    <td key={h} style={{ padding: 1 }}>
                      <div
                        title={`${day} ${h}:00–${h + 4}:00 UTC — ${wins}W / ${total} total`}
                        style={{
                          width: 54, height: 30, borderRadius: 4,
                          background: cellColor(wins, total),
                          border: `1px solid ${C.border}`,
                          display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: 9, fontWeight: 700,
                          color: total > 0 ? '#fff' : C.muted,
                        }}
                      >
                        {cellText(wins, total)}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Summary: best trading window */}
      {(() => {
        let bestWr = 0; let bestLabel = '';
        DAYS.forEach((d) => HOURS.forEach((h) => {
          const { wins, total } = grid[`${d}_${h}`] ?? { wins: 0, total: 0 };
          if (total >= 2 && wins / total > bestWr) {
            bestWr = wins / total;
            bestLabel = `${d} ${h}:00–${h + 4}:00 UTC`;
          }
        }));
        if (!bestLabel) return null;
        return (
          <div style={{ marginTop: 14, padding: '10px 14px', background: `${C.bull}15`, borderRadius: R.sm, fontSize: F.xs, color: C.textSub }}>
            <strong style={{ color: C.bull }}>Best window:</strong> {bestLabel} ({Math.round(bestWr * 100)}% win rate) — when data shows this is prime trading territory.
          </div>
        );
      })()}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Results() {
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [equityCurve, setEquityCurve] = useState<EquityCurvePoint[]>([]);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [loadingBt, setLoadingBt] = useState(true);
  const [loadingTrades, setLoadingTrades] = useState(true);
  const [copied, setCopied] = useState(false);
  const apiBase = resolveApiBase();

  useEffect(() => {
    const load = async () => {
      const [btRes, eqRes, tradesRes] = await Promise.allSettled([
        fetch(`${apiBase}/v1/backtest/results/latest`),
        fetch(`${apiBase}/v1/trades/equity-curve?run=latest`),
        fetch(`${apiBase}/v1/trades/history?limit=200`),
      ]);
      if (btRes.status === 'fulfilled' && btRes.value.ok) {
        setBacktest(await btRes.value.json());
      }
      setLoadingBt(false);
      if (eqRes.status === 'fulfilled' && eqRes.value.ok) {
        const d = await eqRes.value.json();
        setEquityCurve(d?.points || []);
      }
      if (tradesRes.status === 'fulfilled' && tradesRes.value.ok) {
        const d: TradeHistoryResponse = await tradesRes.value.json();
        setTrades(d?.trades || []);
      }
      setLoadingTrades(false);
    };
    load();
  }, [apiBase]);

  const r = backtest?.results;
  const cfg = backtest?.config;

  const handleCopy = () => {
    if (typeof window !== 'undefined') {
      navigator.clipboard.writeText(window.location.href).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
    }
  };

  return (
    <div>
      {/* ── Header ───────────────────────────────────── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
              Verified Performance
            </div>
            <h1 style={{ margin: 0, fontSize: F['3xl'], fontWeight: 800, color: C.text, letterSpacing: -0.5 }}>
              Results &amp; Proof
            </h1>
            <p style={{ margin: '6px 0 0', fontSize: F.sm, color: C.muted, maxWidth: 600 }}>
              Real backtest results from the live strategy ensemble. Every trade logged, every decision traceable.
              {cfg && ` Starting capital: ${fmtUsd(cfg.starting_equity)} · ${cfg.days}-day run.`}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <button
              onClick={handleCopy}
              style={{ fontSize: F.sm, padding: '8px 16px', borderRadius: R.md, border: `1px solid ${C.border}`, background: copied ? C.bull + '22' : 'transparent', color: copied ? C.bull : C.muted, cursor: 'pointer', fontWeight: 600 }}
            >
              {copied ? '✓ Copied' : '⎘ Share'}
            </button>
            <Link href="/backtest" style={{ fontSize: F.sm, padding: '8px 16px', borderRadius: R.md, background: C.brand, color: '#fff', fontWeight: 700, textDecoration: 'none' }}>
              Explore Backtests →
            </Link>
          </div>
        </div>
      </div>

      {/* ── Hero banner ──────────────────────────────── */}
      {loadingBt ? (
        <div style={{ marginBottom: 24 }}><Skeleton h={100} /></div>
      ) : r ? (
        <div
          style={{
            background: `linear-gradient(135deg, ${C.bull}1a, ${C.card})`,
            border: `1px solid ${C.bull}40`,
            borderRadius: R.xl,
            padding: '28px 32px',
            marginBottom: 28,
            display: 'flex',
            gap: 40,
            flexWrap: 'wrap',
            alignItems: 'center',
          }}
        >
          <div>
            <div style={{ fontSize: F.xs, color: C.bull, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
              LIVE PAPER TRADING · {cfg?.days ?? 30} Days
            </div>
            <div style={{ fontSize: 42, fontWeight: 800, color: C.bull, lineHeight: 1, marginBottom: 6 }}>
              {fmtPct(r.total_return_pct)}
            </div>
            <div style={{ fontSize: F.md, color: C.textSub }}>
              {fmtUsd(r.net_pnl)} net profit on {fmtUsd(cfg?.starting_equity ?? 50000)} starting capital
            </div>
          </div>
          <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap' }}>
            {[
              { label: 'Win Rate', value: `${(r.win_rate * 100).toFixed(1)}%`, color: C.bull },
              { label: 'Profit Factor', value: `${(r.profit_factor ?? 0).toFixed(2)}×`, color: C.info },
              { label: 'Total Trades', value: `${r.total_trades}`, color: C.text },
              { label: 'Max Drawdown', value: fmtPct(-Math.abs(r.max_drawdown_pct)), color: C.warn },
            ].map(({ label, value, color }) => (
              <div key={label}>
                <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.7, marginBottom: 4 }}>{label}</div>
                <div style={{ fontSize: F['2xl'], fontWeight: 800, color }}>{value}</div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div style={{ marginBottom: 24, padding: 24, background: C.card, borderRadius: R.lg, border: `1px solid ${C.border}`, textAlign: 'center', color: C.muted }}>
          No backtest results found. Run a backtest first via the{' '}
          <Link href="/backtest" style={{ color: C.brand }}>Backtest Explorer</Link>.
        </div>
      )}

      {/* ── Full KPI grid ─────────────────────────────── */}
      {r && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14, marginBottom: 28 }}>
          <KpiBlock label="Net Profit" value={fmtUsd(r.net_pnl)} color={r.net_pnl >= 0 ? C.bull : C.bear} />
          <KpiBlock label="Gross Profit" value={fmtUsd(r.gross_pnl || r.total_pnl)} color={C.bull} />
          <KpiBlock label="Total Fees" value={fmtUsd(r.total_fees)} color={C.warn} />
          <KpiBlock label="Avg Win" value={fmtUsd(r.avg_win)} color={C.bull} />
          <KpiBlock label="Avg Loss" value={fmtUsd(r.avg_loss)} color={C.bear} />
          <KpiBlock label="Signals → Trades" value={`${r.positions_opened}/${r.total_signals}`} sub="signal conversion rate" />
        </div>
      )}

      {/* ── Equity Curve + Drawdown ──────────────────── */}
      <div
        style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px', marginBottom: 28 }}
      >
        <h2 style={{ margin: '0 0 16px', fontSize: F.lg, fontWeight: 700, color: C.text }}>Equity Curve</h2>
        <EquityCurveChart points={equityCurve} height={200} />
        {equityCurve.length >= 2 && (
          <div style={{ marginTop: 8, borderTop: `1px solid ${C.border}`, paddingTop: 12 }}>
            <DrawdownSubChart points={equityCurve} height={80} />
          </div>
        )}
      </div>

      {/* ── P&L Distribution Histogram ───────────────── */}
      <WinLossHistogram trades={trades} />

      {/* ── Time-of-Day Heatmap ───────────────────────── */}
      <TimeOfDayHeatmap trades={trades} />

      {/* ── By-Strategy + Regime Win Rate ──────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 28 }}>
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px' }}>
          <h2 style={{ margin: '0 0 16px', fontSize: F.lg, fontWeight: 700, color: C.text }}>By Strategy</h2>
          {backtest?.by_strategy && Object.keys(backtest.by_strategy).length > 0 ? (
            <ByStrategyBars byStrategy={backtest.by_strategy} />
          ) : (
            <div style={{ color: C.muted, fontSize: F.sm }}>No per-strategy breakdown in this backtest.</div>
          )}
        </div>
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px' }}>
          <h2 style={{ margin: '0 0 4px', fontSize: F.lg, fontWeight: 700, color: C.text }}>Win Rate by Regime</h2>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 14 }}>Computed from live trade history</div>
          <RegimeWinRate trades={trades} />
        </div>
      </div>

      {/* ── By-Symbol + Exit Type ──────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 28 }}>
        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px' }}>
          <h2 style={{ margin: '0 0 16px', fontSize: F.lg, fontWeight: 700, color: C.text }}>By Symbol</h2>
          {backtest?.by_symbol ? (
            <BySymbolBars bySymbol={backtest.by_symbol} />
          ) : (
            <div style={{ color: C.muted, fontSize: F.sm }}>No per-symbol data.</div>
          )}
        </div>

        <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px' }}>
          <h2 style={{ margin: '0 0 16px', fontSize: F.lg, fontWeight: 700, color: C.text }}>Exit Types</h2>
          {r?.by_action ? (
            <ExitDonut byAction={r.by_action} />
          ) : (
            <div style={{ color: C.muted, fontSize: F.sm }}>No exit breakdown data.</div>
          )}
          {r && (
            <div style={{ marginTop: 16, paddingTop: 16, borderTop: `1px solid ${C.border}`, fontSize: F.xs, color: C.muted, lineHeight: 1.7 }}>
              <strong style={{ color: C.textSub }}>What this means:</strong><br />
              TP1/TP2 = bot hit its profit targets.<br />
              TRAILING_STOP = position trailed up and locked in profit before reversal.<br />
              SL = stop loss hit (trade failed the thesis).
            </div>
          )}
        </div>
      </div>

      {/* ── Trade history table ───────────────────────── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Trade History</h2>
          <span style={{ fontSize: F.xs, color: C.muted }}>{trades.length} trades · click column headers to sort</span>
        </div>
        <TradeTable trades={trades} loading={loadingTrades} />
      </div>

      {/* ── Disclaimer ───────────────────────────────── */}
      <div
        style={{
          padding: '16px 20px',
          background: C.warnLight,
          border: `1px solid ${C.warnMid}`,
          borderRadius: R.md,
          fontSize: F.xs,
          color: '#78350f',
          lineHeight: 1.7,
        }}
      >
        <strong>Disclaimer:</strong> These results are from paper trading (simulated, no real money).
        Past performance does not guarantee future results. All trading involves risk.
        The signals and analysis shown are generated by an automated system and are for informational purposes only.
        Never trade with money you cannot afford to lose. Always use a stop loss.
      </div>
    </div>
  );
}
