'use client';

import React, { useEffect, useState, useRef } from 'react';
import { C, R, S, F, fmtUsd, fmtPct } from '../src/theme';
import type { BacktestResult, BacktestRunMeta, BacktestJob } from '../src/types';

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

// ─── Equity Sparkline ─────────────────────────────────────────────────────────

function Sparkline({ returnPct, width = 80, height = 32 }: { returnPct: number; width?: number; height?: number }) {
  // Generate synthetic equity curve from return %
  const points = Array.from({ length: 10 }, (_, i) => {
    const progress = i / 9;
    // Rough curve: starts at 1, ends at 1 + return/100, with slight noise
    const noise = (Math.sin(i * 1.5) * 0.3 * Math.abs(returnPct / 100));
    return 1 + (returnPct / 100) * progress + noise * (i / 9);
  });
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 0.01;
  const pts = points.map((v, i) => {
    const x = (i / 9) * width;
    const y = height - ((v - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  });
  const isPos = returnPct >= 0;
  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <polyline fill="none" stroke={isPos ? C.bull : C.bear} strokeWidth={2} points={pts.join(' ')} strokeLinejoin="round" />
    </svg>
  );
}

// ─── Run Card ─────────────────────────────────────────────────────────────────

function RunCard({ run, selected, onClick }: { run: BacktestRunMeta; selected: boolean; onClick: () => void }) {
  const date = new Date(run.created_at).toLocaleDateString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
  });
  const isPos = (run.total_return_pct ?? 0) >= 0;

  return (
    <div
      onClick={onClick}
      style={{
        background: selected ? C.surfaceHover : C.card,
        border: `1px solid ${selected ? C.brand : C.border}`,
        borderRadius: R.md,
        padding: '12px 16px',
        cursor: 'pointer',
        transition: 'all 0.15s',
        boxShadow: selected ? S.glow : 'none',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
      }}
    >
      {/* Sparkline */}
      <Sparkline returnPct={run.total_return_pct ?? 0} />

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {run.symbols?.join(', ') || '—'} · {run.days ?? '?'}d
        </div>
        <div style={{ fontSize: F.xs, color: C.muted }}>{date}</div>
      </div>

      <div style={{ textAlign: 'right', flexShrink: 0 }}>
        {run.total_return_pct != null ? (
          <div style={{ fontSize: F.md, fontWeight: 800, color: isPos ? C.bull : C.bear }}>
            {fmtPct(run.total_return_pct)}
          </div>
        ) : (
          <div style={{ fontSize: F.xs, color: C.muted }}>—</div>
        )}
        {run.win_rate != null && (
          <div style={{ fontSize: F.xs, color: C.muted }}>{(run.win_rate * 100).toFixed(0)}% WR</div>
        )}
      </div>
    </div>
  );
}

// ─── Equity Curve Chart ───────────────────────────────────────────────────────

function EquityCurveChart({ trades, startEquity = 50000 }: { trades?: Array<{ pnl?: number | null }>; startEquity?: number }) {
  if (!trades || trades.length === 0) {
    // Generate synthetic curve from return %
    return null;
  }
  const W = 600, H = 160;
  const pad = { t: 16, r: 16, b: 28, l: 64 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;

  // Build equity curve
  let equity = startEquity;
  const points: { i: number; eq: number }[] = [{ i: 0, eq: equity }];
  trades.forEach((t, idx) => {
    equity += t.pnl ?? 0;
    points.push({ i: idx + 1, eq: equity });
  });

  const minEq = Math.min(...points.map(p => p.eq));
  const maxEq = Math.max(...points.map(p => p.eq));
  const range = maxEq - minEq || 1;
  const n = points.length;

  const toX = (i: number) => pad.l + (i / (n - 1)) * iW;
  const toY = (eq: number) => pad.t + iH - ((eq - minEq) / range) * iH;

  // Peak tracking for drawdown shading
  let peak = startEquity;
  const ddRegions: Array<{ x1: number; x2: number; yPeak: number; yTrough: number }> = [];
  let ddStart: number | null = null;

  points.forEach((p, i) => {
    if (p.eq > peak) {
      if (ddStart !== null) {
        ddRegions.push({ x1: toX(ddStart), x2: toX(i), yPeak: toY(peak), yTrough: toY(Math.min(...points.slice(ddStart, i + 1).map(q => q.eq))) });
        ddStart = null;
      }
      peak = p.eq;
    } else if (p.eq < peak && ddStart === null) {
      ddStart = i - 1;
    }
  });
  if (ddStart !== null) {
    ddRegions.push({ x1: toX(ddStart), x2: toX(n - 1), yPeak: toY(peak), yTrough: toY(Math.min(...points.slice(ddStart).map(q => q.eq))) });
  }

  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${toX(i).toFixed(1)} ${toY(p.eq).toFixed(1)}`).join(' ');
  const areaD = `${pathD} L ${toX(n - 1)} ${pad.t + iH} L ${pad.l} ${pad.t + iH} Z`;

  const isPos = points[points.length - 1].eq >= startEquity;
  const lineColor = isPos ? C.bull : C.bear;

  // Y-axis labels
  const yTicks = [minEq, (minEq + maxEq) / 2, maxEq].map(v => ({
    y: toY(v),
    label: '$' + (v >= 1000 ? (v / 1000).toFixed(1) + 'k' : v.toFixed(0)),
  }));

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
      <defs>
        <linearGradient id="eqArea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lineColor} stopOpacity="0.3" />
          <stop offset="100%" stopColor={lineColor} stopOpacity="0.02" />
        </linearGradient>
        <clipPath id="eqClip">
          <rect x={pad.l} y={pad.t} width={iW} height={iH} />
        </clipPath>
      </defs>

      {/* Y grid lines */}
      {yTicks.map((t, i) => (
        <g key={i}>
          <line x1={pad.l} y1={t.y} x2={pad.l + iW} y2={t.y} stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4" />
          <text x={pad.l - 6} y={t.y} textAnchor="end" dominantBaseline="middle" fontSize={9} fill={C.muted}>{t.label}</text>
        </g>
      ))}

      {/* Drawdown shading */}
      {ddRegions.map((r, i) => (
        <rect key={i} x={r.x1} y={r.yPeak} width={r.x2 - r.x1} height={Math.abs(r.yTrough - r.yPeak)} fill="rgba(220,38,38,0.12)" clipPath="url(#eqClip)" />
      ))}

      {/* Area fill */}
      <path d={areaD} fill="url(#eqArea)" clipPath="url(#eqClip)" />

      {/* Line */}
      <path d={pathD} fill="none" stroke={lineColor} strokeWidth={2} strokeLinejoin="round" clipPath="url(#eqClip)" />

      {/* Start dot */}
      <circle cx={toX(0)} cy={toY(points[0].eq)} r={3} fill={C.muted} />
      {/* End dot */}
      <circle cx={toX(n - 1)} cy={toY(points[n - 1].eq)} r={4} fill={lineColor} style={{ filter: `drop-shadow(0 0 4px ${lineColor})` }} />

      {/* Start/end labels */}
      <text x={pad.l} y={pad.t + iH + 16} fontSize={9} fill={C.muted} textAnchor="start">Trade 1</text>
      <text x={pad.l + iW} y={pad.t + iH + 16} fontSize={9} fill={C.muted} textAnchor="end">Trade {n - 1}</text>
    </svg>
  );
}

// ─── Exit Type Donut ──────────────────────────────────────────────────────────

function ExitTypeDonut({ byAction }: { byAction: Record<string, number> }) {
  const entries = Object.entries(byAction).filter(([, v]) => v > 0);
  if (!entries.length) return null;

  const EXIT_COLORS: Record<string, string> = {
    TP1: '#16a34a', TP2: '#22c55e',
    TRAILING_STOP: '#2563eb', SL: '#dc2626',
  };
  const total = entries.reduce((s, [, v]) => s + v, 0);
  const W = 120, cx = W / 2, cy = W / 2, R_outer = 50, R_inner = 32;

  let cumAngle = -Math.PI / 2;
  const slices = entries.map(([key, val]) => {
    const frac = val / total;
    const angle = frac * 2 * Math.PI;
    const startA = cumAngle;
    const endA = cumAngle + angle - 0.03;
    cumAngle += angle;
    const sx = cx + R_outer * Math.cos(startA);
    const sy = cy + R_outer * Math.sin(startA);
    const ex = cx + R_outer * Math.cos(endA);
    const ey = cy + R_outer * Math.sin(endA);
    const ix = cx + R_inner * Math.cos(endA);
    const iy = cy + R_inner * Math.sin(endA);
    const fx = cx + R_inner * Math.cos(startA);
    const fy = cy + R_inner * Math.sin(startA);
    const large = angle > Math.PI ? 1 : 0;
    const color = EXIT_COLORS[key] || C.muted;
    return { key, val, frac, color, path: `M ${sx} ${sy} A ${R_outer} ${R_outer} 0 ${large} 1 ${ex} ${ey} L ${ix} ${iy} A ${R_inner} ${R_inner} 0 ${large} 0 ${fx} ${fy} Z` };
  });

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
      <svg width={W} height={W} style={{ flexShrink: 0 }}>
        {slices.map((s, i) => (
          <path key={i} d={s.path} fill={s.color} opacity={0.9} />
        ))}
        <text x={cx} y={cy - 5} textAnchor="middle" fontSize={10} fill={C.muted}>EXITS</text>
        <text x={cx} y={cy + 10} textAnchor="middle" fontSize={13} fontWeight="800" fill={C.text}>{total}</text>
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {slices.map((s) => (
          <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 10, height: 10, borderRadius: 2, background: s.color, flexShrink: 0 }} />
            <span style={{ fontSize: F.xs, color: C.text, fontWeight: 600, width: 96 }}>{s.key}</span>
            <span style={{ fontSize: F.xs, color: C.muted }}>{s.val} ({Math.round(s.frac * 100)}%)</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Run Detail Panel ─────────────────────────────────────────────────────────

function BySymbolBars({ bySymbol }: { bySymbol: Record<string, { trades: number; wins: number; pnl: number; win_rate: number }> }) {
  const entries = Object.entries(bySymbol).sort((a, b) => b[1].pnl - a[1].pnl);
  const maxAbs = Math.max(...entries.map(([, v]) => Math.abs(v.pnl)), 1);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {entries.map(([sym, data]) => {
        const pct = (Math.abs(data.pnl) / maxAbs) * 100;
        const isPos = data.pnl >= 0;
        return (
          <div key={sym}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3, fontSize: F.sm }}>
              <span style={{ fontWeight: 700, color: C.text }}>
                {sym} <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 400 }}>{data.trades}t · {(data.win_rate * 100).toFixed(0)}%WR</span>
              </span>
              <span style={{ fontWeight: 700, color: isPos ? C.bull : C.bear }}>{fmtUsd(data.pnl)}</span>
            </div>
            <div style={{ height: 14, background: C.surfaceHover, borderRadius: R.sm, overflow: 'hidden' }}>
              <div style={{ height: '100%', width: `${pct}%`, background: isPos ? C.bull : C.bear, borderRadius: R.sm }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Comparison Delta Table ────────────────────────────────────────────────────

function ComparisonDelta({ a, b, labelA, labelB }: { a: BacktestResult; b: BacktestResult; labelA: string; labelB: string }) {
  const ra = a.results;
  const rb = b.results;

  const metrics = [
    {
      label: 'Total Return',
      va: ra.total_return_pct, vb: rb.total_return_pct,
      fmt: (v: number) => fmtPct(v),
      delta: (d: number) => `${d > 0 ? '+' : ''}${d.toFixed(2)}pp`,
      higherBetter: true,
    },
    {
      label: 'Win Rate',
      va: ra.win_rate * 100, vb: rb.win_rate * 100,
      fmt: (v: number) => `${v.toFixed(1)}%`,
      delta: (d: number) => `${d > 0 ? '+' : ''}${d.toFixed(1)}pp`,
      higherBetter: true,
    },
    {
      label: 'Profit Factor',
      va: ra.profit_factor ?? 0, vb: rb.profit_factor ?? 0,
      fmt: (v: number) => `${v.toFixed(2)}×`,
      delta: (d: number) => `${d > 0 ? '+' : ''}${d.toFixed(2)}×`,
      higherBetter: true,
    },
    {
      label: 'Max Drawdown',
      va: -Math.abs(ra.max_drawdown_pct), vb: -Math.abs(rb.max_drawdown_pct),
      fmt: (v: number) => fmtPct(v),
      delta: (d: number) => `${d > 0 ? '+' : ''}${d.toFixed(2)}pp`,
      higherBetter: false,
    },
    {
      label: 'Net P&L',
      va: ra.net_pnl, vb: rb.net_pnl,
      fmt: (v: number) => fmtUsd(v),
      delta: (d: number) => fmtUsd(d),
      higherBetter: true,
    },
    {
      label: 'Total Fees',
      va: ra.total_fees, vb: rb.total_fees,
      fmt: (v: number) => fmtUsd(v),
      delta: (d: number) => fmtUsd(d),
      higherBetter: false,
    },
    {
      label: 'Avg Win',
      va: ra.avg_win, vb: rb.avg_win,
      fmt: (v: number) => fmtUsd(v),
      delta: (d: number) => fmtUsd(d),
      higherBetter: true,
    },
    {
      label: 'Total Trades',
      va: ra.total_trades, vb: rb.total_trades,
      fmt: (v: number) => `${v}`,
      delta: (d: number) => `${d > 0 ? '+' : ''}${d}`,
      higherBetter: null,
    },
  ];

  let aWins = 0; let bWins = 0;
  metrics.forEach(({ va, vb, higherBetter }) => {
    if (higherBetter === null) return;
    if (higherBetter ? vb > va : vb < va) bWins++; else if (higherBetter ? va > vb : va < vb) aWins++;
  });

  const winner = aWins > bWins ? labelA : bWins > aWins ? labelB : 'Tie';

  return (
    <div style={{ background: C.surfaceHover, border: `1px solid ${C.brand}40`, borderRadius: R.lg, padding: '16px 20px', marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Head-to-Head Comparison</div>
        <div style={{ fontSize: F.xs, padding: '3px 10px', borderRadius: R.pill, background: C.brand + '22', color: C.brand, fontWeight: 700 }}>
          {winner === 'Tie' ? '🤝 Tie' : `${winner} wins ${Math.max(aWins, bWins)}/${aWins + bWins}`}
        </div>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: F.sm }}>
          <thead>
            <tr>
              {['Metric', labelA, labelB, 'Delta', ''].map((h, i) => (
                <th key={i} style={{ padding: '6px 10px', fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, textAlign: i === 0 ? 'left' : 'right', borderBottom: `1px solid ${C.border}` }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metrics.map(({ label, va, vb, fmt, delta, higherBetter }) => {
              const d = vb - va;
              const bBetter = higherBetter !== null ? (higherBetter ? vb > va : vb < va) : null;
              const aBetter = higherBetter !== null ? (higherBetter ? va > vb : va < vb) : null;
              return (
                <tr key={label} style={{ borderBottom: `1px solid ${C.border}` }}>
                  <td style={{ padding: '8px 10px', color: C.textSub, fontWeight: 600 }}>{label}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', color: aBetter ? C.bull : aBetter === false ? C.muted : C.text, fontWeight: aBetter ? 700 : 400, fontVariantNumeric: 'tabular-nums' }}>{fmt(va)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', color: bBetter ? C.bull : bBetter === false ? C.muted : C.text, fontWeight: bBetter ? 700 : 400, fontVariantNumeric: 'tabular-nums' }}>{fmt(vb)}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right', color: d === 0 ? C.muted : d > 0 ? C.bull : C.bear, fontSize: F.xs, fontVariantNumeric: 'tabular-nums' }}>{d !== 0 ? delta(d) : '='}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                    {bBetter && <span style={{ fontSize: F.xs, color: C.bull }}>B ✓</span>}
                    {aBetter && <span style={{ fontSize: F.xs, color: C.warn }}>A ✓</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RunDetail({ result }: { result: BacktestResult }) {
  const r = result.results;
  const cfg = result.config;

  const kpis = [
    { label: 'Total Return', value: fmtPct(r.total_return_pct), color: r.total_return_pct >= 0 ? C.bull : C.bear },
    { label: 'Net P&L', value: fmtUsd(r.net_pnl), color: r.net_pnl >= 0 ? C.bull : C.bear },
    { label: 'Win Rate', value: `${(r.win_rate * 100).toFixed(1)}%`, color: r.win_rate > 0.6 ? C.bull : C.warn },
    { label: 'Profit Factor', value: `${(r.profit_factor ?? 0).toFixed(2)}×`, color: r.profit_factor > 1.5 ? C.bull : C.warn },
    { label: 'Max Drawdown', value: fmtPct(-Math.abs(r.max_drawdown_pct)), color: C.warn },
    { label: 'Total Trades', value: `${r.total_trades}`, color: C.text },
    { label: 'Avg Win', value: fmtUsd(r.avg_win), color: C.bull },
    { label: 'Avg Loss', value: fmtUsd(r.avg_loss), color: C.bear },
  ];

  return (
    <div>
      {/* Config badge */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {cfg.symbols.map((s) => (
          <span key={s} style={{ fontSize: F.xs, padding: '2px 8px', borderRadius: R.pill, background: C.brand + '22', color: C.brand, fontWeight: 700 }}>{s}</span>
        ))}
        <span style={{ fontSize: F.xs, padding: '2px 8px', borderRadius: R.pill, background: C.surfaceHover, color: C.muted }}>{cfg.days}d</span>
        <span style={{ fontSize: F.xs, padding: '2px 8px', borderRadius: R.pill, background: C.surfaceHover, color: C.muted }}>Capital {fmtUsd(cfg.starting_equity, 0)}</span>
        <span style={{ fontSize: F.xs, padding: '2px 8px', borderRadius: R.pill, background: C.surfaceHover, color: C.muted }}>{cfg.ensemble_mode}</span>
      </div>

      {/* KPI grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10, marginBottom: 20 }}>
        {kpis.map(({ label, value, color }) => (
          <div key={label} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.md, padding: '12px 14px' }}>
            <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 4 }}>{label}</div>
            <div style={{ fontSize: F.lg, fontWeight: 800, color }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Equity Curve Chart */}
      {result.trades && result.trades.length > 1 && (
        <div style={{ marginBottom: 20 }}>
          <h3 style={{ margin: '0 0 12px', fontSize: F.md, fontWeight: 700, color: C.text }}>Equity Curve</h3>
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px', overflowX: 'auto' }}>
            <EquityCurveChart trades={result.trades} startEquity={cfg.starting_equity ?? 50000} />
          </div>
          <div style={{ fontSize: 10, color: C.muted, marginTop: 6 }}>
            Red shading = drawdown zones · End dot = final equity · Dashed lines = reference levels
          </div>
        </div>
      )}

      {/* By symbol + Exit types side-by-side */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 24, marginBottom: 20, alignItems: 'start' }}>
        {result.by_symbol && Object.keys(result.by_symbol).length > 0 && (
          <div>
            <h3 style={{ margin: '0 0 12px', fontSize: F.md, fontWeight: 700, color: C.text }}>By Symbol</h3>
            <BySymbolBars bySymbol={result.by_symbol} />
          </div>
        )}

        {r.by_action && Object.values(r.by_action).some(v => v > 0) && (
          <div style={{ minWidth: 220 }}>
            <h3 style={{ margin: '0 0 12px', fontSize: F.md, fontWeight: 700, color: C.text }}>Exit Types</h3>
            <ExitTypeDonut byAction={r.by_action} />
          </div>
        )}
      </div>
    </div>
  );
}

// ─── New Backtest Form ────────────────────────────────────────────────────────

const ALL_SYMBOLS = ['BTC', 'ETH', 'SOL', 'HYPE', 'LINK', 'AVAX', 'DOGE', 'ARB'];
const DAY_OPTIONS = [7, 14, 30, 60, 90];

function NewBacktestForm({ onJobStarted, apiBase }: { onJobStarted: (jobId: string) => void; apiBase: string }) {
  const [open, setOpen] = useState(false);
  const [selectedSymbols, setSelectedSymbols] = useState(['BTC', 'SOL', 'HYPE']);
  const [days, setDays] = useState(30);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleSymbol = (sym: string) => {
    setSelectedSymbols((prev) =>
      prev.includes(sym) ? prev.filter((s) => s !== sym) : [...prev, sym]
    );
  };

  const handleSubmit = async () => {
    if (!selectedSymbols.length) { setError('Select at least one symbol.'); return; }
    setSubmitting(true);
    setError(null);
    try {
      const params = new URLSearchParams({ symbols: selectedSymbols.join(','), days: String(days) });
      const res = await fetch(`${apiBase}/v1/backtest/run?${params}`, { method: 'POST' });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        setError(d.detail || `Error ${res.status}`);
        setSubmitting(false);
        return;
      }
      const data = await res.json();
      onJobStarted(data.job_id);
      setOpen(false);
    } catch (e: any) {
      setError(e.message || 'Failed to start backtest');
    }
    setSubmitting(false);
  };

  return (
    <div style={{ marginBottom: 20 }}>
      {!open ? (
        <button
          onClick={() => setOpen(true)}
          style={{
            width: '100%',
            padding: '12px',
            borderRadius: R.md,
            border: `1px dashed ${C.brand}`,
            background: C.brand + '08',
            color: C.brand,
            fontSize: F.sm,
            fontWeight: 700,
            cursor: 'pointer',
            transition: 'all 0.15s',
          }}
        >
          + Run New Backtest
        </button>
      ) : (
        <div
          style={{
            background: C.card,
            border: `1px solid ${C.brand}40`,
            borderRadius: R.lg,
            padding: '20px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
            <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>New Backtest</div>
            <button onClick={() => setOpen(false)} style={{ background: 'none', border: 'none', color: C.muted, cursor: 'pointer', fontSize: 16 }}>✕</button>
          </div>

          <div
            style={{
              padding: '8px 12px',
              background: C.warnLight,
              border: `1px solid ${C.warnMid}`,
              borderRadius: R.sm,
              fontSize: F.xs,
              color: '#78350f',
              marginBottom: 14,
              lineHeight: 1.6,
            }}
          >
            ⚠ Runs WITHOUT <code>--learn</code> and WITHOUT <code>--llm</code> — your profitable results are safe.
            New results save to a timestamped file and never overwrite existing data.
          </div>

          {/* Symbols */}
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.7, marginBottom: 8 }}>Symbols</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {ALL_SYMBOLS.map((sym) => {
                const active = selectedSymbols.includes(sym);
                return (
                  <button
                    key={sym}
                    onClick={() => toggleSymbol(sym)}
                    style={{
                      padding: '5px 12px',
                      borderRadius: R.pill,
                      border: `1px solid ${active ? C.brand : C.border}`,
                      background: active ? C.brand : 'transparent',
                      color: active ? '#fff' : C.muted,
                      fontSize: F.xs,
                      fontWeight: 700,
                      cursor: 'pointer',
                      transition: 'all 0.15s',
                    }}
                  >
                    {sym}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Days */}
          <div style={{ marginBottom: 14 }}>
            <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.7, marginBottom: 8 }}>Lookback Days</div>
            <div style={{ display: 'flex', gap: 6 }}>
              {DAY_OPTIONS.map((d) => (
                <button
                  key={d}
                  onClick={() => setDays(d)}
                  style={{
                    padding: '5px 14px',
                    borderRadius: R.pill,
                    border: `1px solid ${days === d ? C.brand : C.border}`,
                    background: days === d ? C.brand : 'transparent',
                    color: days === d ? '#fff' : C.muted,
                    fontSize: F.xs,
                    fontWeight: 700,
                    cursor: 'pointer',
                    transition: 'all 0.15s',
                  }}
                >
                  {d}d
                </button>
              ))}
            </div>
          </div>

          {error && (
            <div style={{ padding: '8px 12px', background: C.bearLight + '33', border: `1px solid ${C.bear}44`, borderRadius: R.sm, fontSize: F.xs, color: C.bear, marginBottom: 12 }}>
              {error}
            </div>
          )}

          <button
            onClick={handleSubmit}
            disabled={submitting}
            style={{
              width: '100%',
              padding: '10px',
              borderRadius: R.md,
              border: 'none',
              background: submitting ? C.muted : C.brand,
              color: '#fff',
              fontSize: F.sm,
              fontWeight: 700,
              cursor: submitting ? 'not-allowed' : 'pointer',
              opacity: submitting ? 0.7 : 1,
            }}
          >
            {submitting ? 'Starting…' : `Run Backtest (${selectedSymbols.join(', ')} · ${days}d)`}
          </button>
        </div>
      )}
    </div>
  );
}

// ─── Job Progress ─────────────────────────────────────────────────────────────

function JobProgress({ jobId, apiBase, onDone }: { jobId: string; apiBase: string; onDone: (resultId: string) => void }) {
  const [job, setJob] = useState<BacktestJob | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/backtest/status/${jobId}`);
        if (res.ok) {
          const data: BacktestJob = await res.json();
          setJob(data);
          if (data.status === 'done' || data.status === 'error') {
            if (pollRef.current) clearInterval(pollRef.current);
            if (data.status === 'done') onDone(data.result_id);
          }
        }
      } catch { /* silent */ }
    };
    poll();
    pollRef.current = setInterval(poll, 2500);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [jobId, apiBase]);

  if (!job) return <div style={{ padding: 16, color: C.muted, fontSize: F.sm }}>Starting backtest…</div>;

  const statusColors: Record<string, string> = {
    pending: C.warn,
    running: C.brand,
    done: C.bull,
    error: C.bear,
  };

  const steps = ['pending', 'running', 'done'];
  const currentStep = steps.indexOf(job.status);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px', marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>
          Backtest Running — {job.symbols}
        </div>
        <span style={{ fontSize: F.xs, fontWeight: 700, padding: '2px 8px', borderRadius: R.pill, background: (statusColors[job.status] || C.muted) + '22', color: statusColors[job.status] || C.muted }}>
          {job.status.toUpperCase()}
        </span>
      </div>

      {/* Progress bar */}
      <div style={{ height: 6, background: C.surfaceHover, borderRadius: R.pill, marginBottom: 12, overflow: 'hidden' }}>
        <div
          style={{
            height: '100%',
            width: job.status === 'done' ? '100%' : job.status === 'running' ? '60%' : '15%',
            background: statusColors[job.status] || C.brand,
            borderRadius: R.pill,
            transition: 'width 0.5s ease',
            animation: job.status === 'running' ? 'none' : 'none',
          }}
        />
      </div>

      {/* Steps */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 10 }}>
        {['Queued', 'Running strategies', 'Complete'].map((step, i) => {
          const done = i < currentStep || job.status === 'done';
          const active = i === currentStep && job.status !== 'done' && job.status !== 'error';
          return (
            <div key={step} style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 16, height: 16, borderRadius: '50%', background: done || active ? C.brand : C.border, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 9, color: '#fff', flexShrink: 0, fontWeight: 700 }}>
                {done ? '✓' : i + 1}
              </span>
              <span style={{ fontSize: F.xs, color: done || active ? C.textSub : C.muted }}>{step}</span>
              {i < 2 && <span style={{ flex: 1, height: 1, background: done ? C.brand : C.border, marginLeft: 4 }} />}
            </div>
          );
        })}
      </div>

      {/* Last log line */}
      {job.log_tail?.length > 0 && (
        <div style={{ fontSize: F.xs, color: C.muted, fontFamily: 'JetBrains Mono, monospace', padding: '6px 8px', background: C.bg, borderRadius: R.xs, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {job.log_tail[job.log_tail.length - 1]}
        </div>
      )}

      {job.status === 'error' && (
        <div style={{ marginTop: 8, padding: '8px 10px', background: C.bearLight + '22', borderRadius: R.sm, fontSize: F.xs, color: C.bear }}>
          Error: {job.error || 'Unknown error'}
        </div>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Backtest() {
  const [runs, setRuns] = useState<BacktestRunMeta[]>([]);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedResult, setSelectedResult] = useState<BacktestResult | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [compareId, setCompareId] = useState<string | null>(null);
  const [compareResult, setCompareResult] = useState<BacktestResult | null>(null);
  const apiBase = resolveApiBase();

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/backtest/results`);
        if (res.ok) {
          const d = await res.json();
          setRuns(d.results || []);
          // Auto-select latest
          if (d.results?.length > 0) {
            setSelectedId(d.results[0].id);
          }
        }
      } catch { /* silent */ }
      setLoadingRuns(false);
    };
    load();
  }, [apiBase]);

  useEffect(() => {
    if (!selectedId) { setSelectedResult(null); return; }
    setLoadingDetail(true);
    fetch(`${apiBase}/v1/backtest/results/${selectedId}`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { setSelectedResult(d); setLoadingDetail(false); })
      .catch(() => setLoadingDetail(false));
  }, [selectedId, apiBase]);

  useEffect(() => {
    if (!compareId) { setCompareResult(null); return; }
    fetch(`${apiBase}/v1/backtest/results/${compareId}`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => setCompareResult(d));
  }, [compareId, apiBase]);

  const handleJobDone = async (resultId: string) => {
    setActiveJobId(null);
    // Reload runs list
    const res = await fetch(`${apiBase}/v1/backtest/results`);
    if (res.ok) {
      const d = await res.json();
      setRuns(d.results || []);
    }
    setSelectedId(resultId);
  };

  return (
    <div>
      {/* ── Header ───────────────────────────────────── */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
          Strategy Testing
        </div>
        <h1 style={{ margin: 0, fontSize: F['3xl'], fontWeight: 800, color: C.text, letterSpacing: -0.5 }}>
          Backtest Explorer
        </h1>
        <p style={{ margin: '6px 0 0', fontSize: F.sm, color: C.muted }}>
          Browse all backtest runs or test new symbol/timeframe combinations. Existing results are never modified.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 20, alignItems: 'start' }}>
        {/* ── Left: run list ─────────────────────── */}
        <div>
          {/* Active job progress */}
          {activeJobId && (
            <JobProgress jobId={activeJobId} apiBase={apiBase} onDone={handleJobDone} />
          )}

          {/* New backtest form */}
          <NewBacktestForm apiBase={apiBase} onJobStarted={setActiveJobId} />

          {/* Run list */}
          <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.7, marginBottom: 10 }}>
            Saved Runs ({runs.length})
          </div>
          {loadingRuns ? (
            Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} h={72} style={{ marginBottom: 8 }} />)
          ) : runs.length === 0 ? (
            <div style={{ padding: 16, background: C.card, borderRadius: R.md, border: `1px solid ${C.border}`, textAlign: 'center', color: C.muted, fontSize: F.sm }}>
              No runs yet. Run your first backtest above.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {runs.map((run) => (
                <RunCard
                  key={run.id}
                  run={run}
                  selected={selectedId === run.id}
                  onClick={() => setSelectedId(run.id)}
                />
              ))}
            </div>
          )}
        </div>

        {/* ── Right: detail view ─────────────────── */}
        <div>
          {/* Compare dropdown */}
          {runs.length >= 2 && selectedResult && (
            <div style={{ marginBottom: 16, display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: F.sm, color: C.muted }}>Compare with:</span>
              <select
                value={compareId || ''}
                onChange={(e) => setCompareId(e.target.value || null)}
                style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.sm, color: C.text, padding: '4px 10px', fontSize: F.sm, cursor: 'pointer' }}
              >
                <option value="">— none —</option>
                {runs.filter((r) => r.id !== selectedId).map((r) => (
                  <option key={r.id} value={r.id}>{r.symbols?.join(', ')} · {r.days}d · {fmtPct(r.total_return_pct ?? 0)}</option>
                ))}
              </select>
              {compareId && (
                <button onClick={() => setCompareId(null)} style={{ background: 'none', border: 'none', color: C.muted, cursor: 'pointer', fontSize: F.sm }}>✕ Clear</button>
              )}
            </div>
          )}

          {/* Comparison delta table */}
          {compareResult && selectedResult && (
            <ComparisonDelta
              a={selectedResult}
              b={compareResult}
              labelA="Run A"
              labelB="Run B"
            />
          )}

          {/* Detail panels (side by side if comparing) */}
          <div style={{ display: 'grid', gridTemplateColumns: compareResult ? '1fr 1fr' : '1fr', gap: 16 }}>
            {/* Selected run */}
            <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px' }}>
              {loadingDetail ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  <Skeleton h={24} w="60%" />
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                    {Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} h={60} />)}
                  </div>
                </div>
              ) : selectedResult ? (
                <RunDetail result={selectedResult} />
              ) : (
                <div style={{ padding: 32, textAlign: 'center', color: C.muted, fontSize: F.sm }}>
                  Select a run from the left to view details.
                </div>
              )}
            </div>

            {/* Compare run */}
            {compareResult && (
              <div style={{ background: C.card, border: `1px solid ${C.brand}40`, borderRadius: R.lg, padding: '20px 24px' }}>
                <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.7, marginBottom: 12 }}>Comparison</div>
                <RunDetail result={compareResult} />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Responsive fix ─── */}
      <style>{`
        @media (max-width: 900px) {
          div[style*="300px 1fr"] { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}
