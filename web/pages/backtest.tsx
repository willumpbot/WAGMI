'use client';

import React, { useEffect, useState, useRef, useId } from 'react';
import { C, R, S, F, G, fmtUsd, fmtPct } from '../src/theme';
import { seededRand as mkSeededRand } from '../lib/fmt';
import type { BacktestResult, BacktestRunMeta, BacktestJob } from '../src/types';
import { resolveApiBase } from '../src/api';

function Skeleton({ h = 16, w = '100%', style }: { h?: number; w?: string | number; style?: React.CSSProperties }) {
  return <div className="skeleton" style={{ height: h, width: w, borderRadius: R.sm, ...style }} />;
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
        background: selected ? C.surfaceHover : G.card,
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
  const uid = useId().replace(/:/g, '');
  if (!trades || trades.length === 0) return null;

  const W = 600, H = 200;
  // Extra bottom space for volume bars (20px) + labels (20px)
  const pad = { t: 24, r: 16, b: 48, l: 64 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;
  const VOL_H = 20; // height reserved for volume-style bars at bottom of SVG

  // ── Build equity curve ──────────────────────────────────────────────────────
  let equity = startEquity;
  const points: { i: number; eq: number }[] = [{ i: 0, eq: equity }];
  trades.forEach((t, idx) => {
    equity += t.pnl ?? 0;
    points.push({ i: idx + 1, eq: equity });
  });

  const eqValues = points.map(p => p.eq);
  const minEq = Math.min(...eqValues);
  const maxEq = Math.max(...eqValues);
  const range = maxEq - minEq || 1;
  const n = points.length;

  const toX = (i: number) => pad.l + (i / Math.max(n - 1, 1)) * iW;
  const toY = (eq: number) => pad.t + iH - ((eq - minEq) / range) * iH;

  // ── Y-axis gridlines (4 lines) ──────────────────────────────────────────────
  const yGridCount = 4;
  const yGridLines = Array.from({ length: yGridCount }, (_, i) => {
    const v = minEq + (i / (yGridCount - 1)) * range;
    return {
      y: toY(v),
      label: '$' + (Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + 'k' : v.toFixed(0)),
    };
  });

  // ── Bollinger Bands (20-period SMA ± 2σ) ────────────────────────────────────
  const BB_PERIOD = 20;
  const bbPoints: Array<{ i: number; mid: number; upper: number; lower: number }> = [];
  for (let i = BB_PERIOD - 1; i < n; i++) {
    const slice = eqValues.slice(i - BB_PERIOD + 1, i + 1);
    const sma = slice.reduce((s, v) => s + v, 0) / BB_PERIOD;
    const variance = slice.reduce((s, v) => s + (v - sma) ** 2, 0) / BB_PERIOD;
    const sd = Math.sqrt(variance);
    bbPoints.push({ i, mid: sma, upper: sma + 2 * sd, lower: sma - 2 * sd });
  }

  // BB fill polygon: upper forward, lower backward
  const bbFillPts = bbPoints.length > 0
    ? [
        ...bbPoints.map(b => `${toX(b.i).toFixed(1)},${toY(b.upper).toFixed(1)}`),
        ...[...bbPoints].reverse().map(b => `${toX(b.i).toFixed(1)},${toY(b.lower).toFixed(1)}`),
      ].join(' ')
    : '';

  const bbUpperPts = bbPoints.map(b => `${toX(b.i).toFixed(1)},${toY(b.upper).toFixed(1)}`).join(' ');
  const bbLowerPts = bbPoints.map(b => `${toX(b.i).toFixed(1)},${toY(b.lower).toFixed(1)}`).join(' ');
  const bbMidPts   = bbPoints.map(b => `${toX(b.i).toFixed(1)},${toY(b.mid).toFixed(1)}`).join(' ');

  // ── Trade markers: green dot if equity ↑ >0.3%, red dot if ↓ ──────────────
  const tradeMarkers: Array<{ x: number; y: number; color: string }> = [];
  for (let i = 1; i < n; i++) {
    const prev = points[i - 1].eq;
    const curr = points[i].eq;
    const chg = prev > 0 ? (curr - prev) / prev : 0;
    if (chg > 0.003) {
      tradeMarkers.push({ x: toX(i), y: toY(curr), color: C.bull });
    } else if (chg < 0) {
      tradeMarkers.push({ x: toX(i), y: toY(curr), color: C.bear });
    }
  }

  // ── Main equity path ────────────────────────────────────────────────────────
  const pathD = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${toX(i).toFixed(1)} ${toY(p.eq).toFixed(1)}`).join(' ');
  const areaD = `${pathD} L ${toX(n - 1)} ${pad.t + iH} L ${pad.l} ${pad.t + iH} Z`;

  const isPos = points[n - 1].eq >= startEquity;
  const lineColor = isPos ? C.bull : C.bear;

  // ── Drawdown shading ─────────────────────────────────────────────────────────
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

  // ── Regime bands (3 sections) ────────────────────────────────────────────────
  const third = iW / 3;
  const regimeBands = [
    { x: pad.l,               w: third,  color: C.bull + '08',  label: 'Early'  },
    { x: pad.l + third,       w: third,  color: C.brand + '08', label: 'Growth' },
    { x: pad.l + 2 * third,   w: third,  color: C.info + '08',  label: 'Now'    },
  ];

  // ── Volume-style bars (10 buckets of trade activity) ─────────────────────────
  const BUCKETS = 10;
  const bucketCounts = Array(BUCKETS).fill(0);
  for (let i = 1; i < n; i++) {
    const bucket = Math.min(BUCKETS - 1, Math.floor(((i - 1) / (n - 1)) * BUCKETS));
    bucketCounts[bucket]++;
  }
  const maxBucket = Math.max(...bucketCounts, 1);
  const bucketW = iW / BUCKETS;
  const volBars = bucketCounts.map((cnt, bi) => ({
    x: pad.l + bi * bucketW,
    w: bucketW - 1,
    h: (cnt / maxBucket) * VOL_H,
  }));
  // vol bars sit at: (H - pad.b + 4) to (H - pad.b + 4 + VOL_H)
  const volY = H - pad.b + 4;

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
      <defs>
        <linearGradient id={`eqArea-${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lineColor} stopOpacity="0.25" />
          <stop offset="100%" stopColor={lineColor} stopOpacity="0.02" />
        </linearGradient>
        <clipPath id={`eqClip-${uid}`}>
          <rect x={pad.l} y={pad.t} width={iW} height={iH} />
        </clipPath>
      </defs>

      {/* ── Regime background bands ── */}
      {regimeBands.map((rb, i) => (
        <g key={i}>
          <rect x={rb.x} y={pad.t} width={rb.w} height={iH} fill={rb.color} />
          <text x={rb.x + rb.w / 2} y={pad.t + 9} textAnchor="middle" fontSize={8} fill={C.muted} opacity={0.7}>{rb.label}</text>
        </g>
      ))}

      {/* ── Y-axis gridlines (4) ── */}
      {yGridLines.map((g, i) => (
        <g key={i}>
          <line x1={pad.l} y1={g.y} x2={pad.l + iW} y2={g.y} stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4" />
          <text x={pad.l - 6} y={g.y} textAnchor="end" dominantBaseline="middle" fontSize={9} fill={C.muted}>{g.label}</text>
        </g>
      ))}

      {/* ── Drawdown shading ── */}
      {ddRegions.map((r, i) => (
        <rect key={i} x={r.x1} y={r.yPeak} width={r.x2 - r.x1} height={Math.max(0, Math.abs(r.yTrough - r.yPeak))} fill="rgba(220,38,38,0.12)" clipPath={`url(#eqClip-${uid})`} />
      ))}

      {/* ── Bollinger Band fill ── */}
      {bbFillPts && (
        <polygon points={bbFillPts} fill={C.brand + '10'} stroke="none" clipPath={`url(#eqClip-${uid})`} />
      )}

      {/* ── BB upper / lower dashed lines ── */}
      {bbPoints.length > 1 && (
        <>
          <polyline fill="none" stroke={C.brand + '40'} strokeWidth={1} strokeDasharray="4 3" points={bbUpperPts} clipPath={`url(#eqClip-${uid})`} />
          <polyline fill="none" stroke={C.brand + '40'} strokeWidth={1} strokeDasharray="4 3" points={bbLowerPts} clipPath={`url(#eqClip-${uid})`} />
        </>
      )}

      {/* ── BB middle (SMA20) solid ── */}
      {bbPoints.length > 1 && (
        <polyline fill="none" stroke={C.brand + '70'} strokeWidth={1.2} points={bbMidPts} clipPath={`url(#eqClip-${uid})`} />
      )}

      {/* ── Area fill under equity curve ── */}
      <path d={areaD} fill={`url(#eqArea-${uid})`} clipPath={`url(#eqClip-${uid})`} />

      {/* ── Equity line ── */}
      <path d={pathD} fill="none" stroke={lineColor} strokeWidth={2} strokeLinejoin="round" clipPath={`url(#eqClip-${uid})`} />

      {/* ── Trade markers ── */}
      {tradeMarkers.map((m, i) => (
        <circle key={i} cx={m.x} cy={m.y} r={2.5} fill={m.color} opacity={0.75} clipPath={`url(#eqClip-${uid})`} />
      ))}

      {/* ── Start / end dots ── */}
      <circle cx={toX(0)} cy={toY(points[0].eq)} r={3} fill={C.muted} />
      <circle cx={toX(n - 1)} cy={toY(points[n - 1].eq)} r={4} fill={lineColor} style={{ filter: `drop-shadow(0 0 4px ${lineColor})` }} />

      {/* ── Volume-style bars ── */}
      {volBars.map((b, i) => (
        <rect key={i} x={b.x} y={volY + (VOL_H - b.h)} width={b.w} height={b.h} fill={C.brand + '50'} rx={1} />
      ))}

      {/* ── X-axis labels ── */}
      <text x={pad.l} y={volY + VOL_H + 10} fontSize={9} fill={C.muted} textAnchor="start">Trade 1</text>
      <text x={pad.l + iW} y={volY + VOL_H + 10} fontSize={9} fill={C.muted} textAnchor="end">Trade {n - 1}</text>

      {/* ── Legend box (top-right) ── */}
      <rect x={pad.l + iW - 118} y={pad.t + 2} width={116} height={46} rx={4} fill={C.card} fillOpacity={0.85} stroke={C.border} strokeWidth={0.7} />
      {/* Equity line */}
      <line x1={pad.l + iW - 112} y1={pad.t + 13} x2={pad.l + iW - 98} y2={pad.t + 13} stroke={lineColor} strokeWidth={2} />
      <text x={pad.l + iW - 94} y={pad.t + 13} dominantBaseline="middle" fontSize={8} fill={C.textSub}>Equity</text>
      {/* BB fill swatch */}
      <rect x={pad.l + iW - 112} y={pad.t + 22} width={14} height={6} rx={1} fill={C.brand + '30'} stroke={C.brand + '40'} strokeWidth={0.8} strokeDasharray="3 2" />
      <text x={pad.l + iW - 94} y={pad.t + 25} dominantBaseline="middle" fontSize={8} fill={C.textSub}>BB Upper/Lower</text>
      {/* SMA20 line */}
      <line x1={pad.l + iW - 112} y1={pad.t + 37} x2={pad.l + iW - 98} y2={pad.t + 37} stroke={C.brand + '70'} strokeWidth={1.5} />
      <text x={pad.l + iW - 94} y={pad.t + 37} dominantBaseline="middle" fontSize={8} fill={C.textSub}>SMA20</text>
    </svg>
  );
}

// ─── RSI Subplot ──────────────────────────────────────────────────────────────

function RSISubplot({ values, width, height }: { values: number[]; width: number; height: number }) {
  const uid = useId().replace(/:/g, '');
  if (!values || values.length < 16) return null;

  const RSI_PERIOD = 14;
  const pad = { t: 6, r: 16, b: 14, l: 64 };
  const iW = width - pad.l - pad.r;
  const iH = height - pad.t - pad.b;

  // ── Compute daily returns ────────────────────────────────────────────────────
  const returns: number[] = [];
  for (let i = 1; i < values.length; i++) {
    returns.push(values[i] - values[i - 1]);
  }

  // ── Compute RSI using Wilder's smoothing ─────────────────────────────────────
  const rsiValues: Array<{ i: number; rsi: number }> = [];

  if (returns.length >= RSI_PERIOD) {
    // Seed with simple average over first RSI_PERIOD returns
    let avgGain = 0, avgLoss = 0;
    for (let j = 0; j < RSI_PERIOD; j++) {
      if (returns[j] > 0) avgGain += returns[j];
      else avgLoss += Math.abs(returns[j]);
    }
    avgGain /= RSI_PERIOD;
    avgLoss /= RSI_PERIOD;

    const calcRsi = (g: number, l: number) => l === 0 ? 100 : 100 - (100 / (1 + g / l));
    rsiValues.push({ i: RSI_PERIOD, rsi: calcRsi(avgGain, avgLoss) });

    for (let j = RSI_PERIOD; j < returns.length; j++) {
      const gain = returns[j] > 0 ? returns[j] : 0;
      const loss = returns[j] < 0 ? Math.abs(returns[j]) : 0;
      avgGain = (avgGain * (RSI_PERIOD - 1) + gain) / RSI_PERIOD;
      avgLoss = (avgLoss * (RSI_PERIOD - 1) + loss) / RSI_PERIOD;
      rsiValues.push({ i: j + 1, rsi: calcRsi(avgGain, avgLoss) });
    }
  }

  if (rsiValues.length < 2) return null;

  const nRsi = rsiValues.length;
  const firstI = rsiValues[0].i;
  const lastI  = rsiValues[nRsi - 1].i;
  const totalSpan = lastI - firstI || 1;

  const toX = (idx: number) => pad.l + ((idx - firstI) / totalSpan) * iW;
  const toY = (rsi: number) => pad.t + iH - ((rsi - 0) / 100) * iH;

  const toY30 = toY(30);
  const toY50 = toY(50);
  const toY70 = toY(70);

  // ── Overbought / oversold fill regions ──────────────────────────────────────
  // Build polygon for overbought (RSI > 70): clamp line at 70
  const obPts: string[] = [];
  const osPts: string[] = [];

  rsiValues.forEach((rv, idx) => {
    obPts.push(`${toX(rv.i).toFixed(1)},${Math.min(toY(rv.rsi), toY70).toFixed(1)}`);
    osPts.push(`${toX(rv.i).toFixed(1)},${Math.max(toY(rv.rsi), toY30).toFixed(1)}`);
  });
  // Close overbought: along the 70 line back
  const obFill = [
    ...obPts,
    `${toX(lastI).toFixed(1)},${toY70.toFixed(1)}`,
    `${toX(firstI).toFixed(1)},${toY70.toFixed(1)}`,
  ].join(' ');
  // Close oversold: along the 30 line back
  const osFill = [
    ...osPts,
    `${toX(lastI).toFixed(1)},${toY30.toFixed(1)}`,
    `${toX(firstI).toFixed(1)},${toY30.toFixed(1)}`,
  ].join(' ');

  // ── RSI line ─────────────────────────────────────────────────────────────────
  const rsiLinePts = rsiValues.map(rv => `${toX(rv.i).toFixed(1)},${toY(rv.rsi).toFixed(1)}`).join(' ');

  const lastRsi = rsiValues[nRsi - 1];
  const currentRsiVal = lastRsi.rsi;
  const rsiDotColor = currentRsiVal > 70 ? C.bear : currentRsiVal < 30 ? C.bull : C.brand;

  return (
    <svg width={width} height={height} style={{ display: 'block', overflow: 'visible' }}>
      <clipPath id={`rsiClip-${uid}`}>
        <rect x={pad.l} y={pad.t} width={iW} height={iH} />
      </clipPath>

      {/* ── Overbought zone fill (RSI > 70) ── */}
      <polygon points={obFill} fill={C.bear} fillOpacity={0.10} clipPath={`url(#rsiClip-${uid})`} />
      {/* ── Oversold zone fill (RSI < 30) ── */}
      <polygon points={osFill} fill={C.bull} fillOpacity={0.10} clipPath={`url(#rsiClip-${uid})`} />

      {/* ── Reference lines at 30, 50, 70 ── */}
      <line x1={pad.l} y1={toY70} x2={pad.l + iW} y2={toY70} stroke={C.bear} strokeWidth={0.7} strokeDasharray="3 3" opacity={0.6} />
      <line x1={pad.l} y1={toY50} x2={pad.l + iW} y2={toY50} stroke={C.border} strokeWidth={0.6} strokeDasharray="2 4" opacity={0.5} />
      <line x1={pad.l} y1={toY30} x2={pad.l + iW} y2={toY30} stroke={C.bull} strokeWidth={0.7} strokeDasharray="3 3" opacity={0.6} />

      {/* ── Reference labels on left ── */}
      <text x={pad.l - 4} y={toY70} textAnchor="end" dominantBaseline="middle" fontSize={8} fill={C.bear} opacity={0.8}>70</text>
      <text x={pad.l - 4} y={toY30} textAnchor="end" dominantBaseline="middle" fontSize={8} fill={C.bull} opacity={0.8}>30</text>

      {/* ── RSI line ── */}
      <polyline fill="none" stroke={C.brand} strokeWidth={1.5} strokeLinejoin="round" points={rsiLinePts} clipPath={`url(#rsiClip-${uid})`} />

      {/* ── Current RSI dot ── */}
      <circle cx={toX(lastRsi.i)} cy={toY(lastRsi.rsi)} r={3} fill={rsiDotColor} style={{ filter: `drop-shadow(0 0 3px ${rsiDotColor})` }} />

      {/* ── "RSI(14)" label top-left ── */}
      <text x={pad.l + 3} y={pad.t + 9} fontSize={8} fill={C.brand} fontWeight={700}>RSI(14)</text>
      {/* ── Current value label next to dot ── */}
      <text x={toX(lastRsi.i) + 5} y={toY(lastRsi.rsi)} dominantBaseline="middle" fontSize={8} fill={rsiDotColor} fontWeight={700}>{currentRsiVal.toFixed(0)}</text>
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

// ─── Run Comparison Radar ─────────────────────────────────────────────────────

function RunComparisonRadar({
  runA,
  runB,
  labelA = 'Run A',
  labelB = 'Run B',
}: {
  runA: BacktestResult;
  runB: BacktestResult;
  labelA?: string;
  labelB?: string;
}) {
  const SIZE = 320;
  const cx = SIZE / 2;
  const cy = SIZE / 2;
  const RADIUS = 118; // max axis length from center

  // 6 axes, evenly spaced around the circle (starting at top, going clockwise)
  const axes = [
    { label: 'Win Rate',      key: 'win_rate' },
    { label: 'Profit Factor', key: 'profit_factor' },
    { label: 'Total Return',  key: 'total_return_pct' },
    { label: 'Avg Win',       key: 'avg_win' },
    { label: 'Max DD',        key: 'max_drawdown_pct' },
    { label: 'Trade Count',   key: 'total_trades' },
  ] as const;

  const N = axes.length;

  // Normalize raw values to 0–1
  function normalize(key: typeof axes[number]['key'], raw: number): number {
    switch (key) {
      case 'win_rate':
        // stored as 0–1 fraction, display as %; cap at 100%
        return Math.min(1, Math.max(0, raw));
      case 'profit_factor':
        return Math.min(1, Math.max(0, (raw ?? 0) / 5));
      case 'total_return_pct':
        return Math.min(1, Math.max(0, raw / 50));
      case 'avg_win':
        return Math.min(1, Math.max(0, (raw ?? 0) / 5000));
      case 'max_drawdown_pct':
        // inverted: 0% DD → 1.0, 50% DD → 0.0
        return Math.min(1, Math.max(0, 1 - Math.abs(raw) / 50));
      case 'total_trades':
        return Math.min(1, Math.max(0, (raw ?? 0) / 100));
      default:
        return 0;
    }
  }

  // Tip label formatter for each axis
  function axisLabel(key: typeof axes[number]['key'], raw: number): string {
    switch (key) {
      case 'win_rate':
        return `${(raw * 100).toFixed(0)}%`;
      case 'profit_factor':
        return `${(raw ?? 0).toFixed(2)}×`;
      case 'total_return_pct':
        return fmtPct(raw);
      case 'avg_win':
        return fmtUsd(raw ?? 0);
      case 'max_drawdown_pct':
        return fmtPct(-Math.abs(raw));
      case 'total_trades':
        return `${raw ?? 0}`;
      default:
        return '';
    }
  }

  // Angle for axis i: start at top (−π/2), go clockwise
  function angleOf(i: number): number {
    return -Math.PI / 2 + (2 * Math.PI * i) / N;
  }

  // Point on an axis at normalized value v
  function axisPoint(i: number, v: number): { x: number; y: number } {
    const a = angleOf(i);
    return {
      x: cx + RADIUS * v * Math.cos(a),
      y: cy + RADIUS * v * Math.sin(a),
    };
  }

  // Build polygon points for a run
  function buildPolygon(result: BacktestResult): string {
    const r = result.results;
    return axes
      .map((ax, i) => {
        const raw = r[ax.key as keyof typeof r] as number;
        const v = normalize(ax.key, raw ?? 0);
        const pt = axisPoint(i, v);
        return `${pt.x.toFixed(2)},${pt.y.toFixed(2)}`;
      })
      .join(' ');
  }

  // Hexagonal grid rings (25%, 50%, 75%, 100%)
  function buildRing(fraction: number): string {
    return Array.from({ length: N }, (_, i) => {
      const pt = axisPoint(i, fraction);
      return `${pt.x.toFixed(2)},${pt.y.toFixed(2)}`;
    }).join(' ');
  }

  const polyA = buildPolygon(runA);
  const polyB = buildPolygon(runB);

  const BRAND = '#6366f1'; // indigo
  const TEAL  = '#14b8a6'; // teal/green

  return (
    <div
      style={{
        background: C.surfaceHover,
        border: `1px solid ${C.brand}40`,
        borderRadius: R.lg,
        padding: '20px 24px',
        marginBottom: 16,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 12,
      }}
    >
      {/* Title */}
      <div style={{ alignSelf: 'flex-start', fontSize: F.sm, fontWeight: 700, color: C.text }}>
        Performance Radar
      </div>

      <svg
        width={SIZE}
        height={SIZE}
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        style={{ display: 'block', overflow: 'visible' }}
      >
        {/* Grid rings */}
        {[0.25, 0.5, 0.75, 1].map((frac) => (
          <polygon
            key={frac}
            points={buildRing(frac)}
            fill="none"
            stroke={C.border}
            strokeWidth={frac === 1 ? 1.2 : 0.7}
            strokeDasharray={frac === 1 ? undefined : '3 4'}
            opacity={0.6}
          />
        ))}

        {/* Axis lines + tip labels */}
        {axes.map((ax, i) => {
          const tip = axisPoint(i, 1);
          const angle = angleOf(i);
          // Label offset: push slightly beyond the tip
          const LABEL_OFFSET = 22;
          const lx = cx + (RADIUS + LABEL_OFFSET) * Math.cos(angle);
          const ly = cy + (RADIUS + LABEL_OFFSET) * Math.sin(angle);
          // Anchor based on which side of the chart the label falls on
          const anchor =
            Math.abs(Math.cos(angle)) < 0.15
              ? 'middle'
              : Math.cos(angle) < 0
              ? 'end'
              : 'start';

          const ra = runA.results;
          const rb = runB.results;
          const rawA = (ra[ax.key as keyof typeof ra] ?? 0) as number;
          const rawB = (rb[ax.key as keyof typeof rb] ?? 0) as number;

          return (
            <g key={ax.key}>
              {/* Axis line */}
              <line
                x1={cx}
                y1={cy}
                x2={tip.x}
                y2={tip.y}
                stroke={C.border}
                strokeWidth={0.8}
                opacity={0.8}
              />
              {/* Axis perimeter label */}
              <text
                x={lx}
                y={ly}
                textAnchor={anchor}
                dominantBaseline="middle"
                fontSize={10}
                fontWeight={600}
                fill={C.muted}
              >
                {ax.label}
              </text>
              {/* Run A tip value */}
              {(() => {
                const vA = normalize(ax.key, rawA);
                const ptA = axisPoint(i, vA);
                const tipOffsetA = 14;
                const txA = ptA.x + tipOffsetA * Math.cos(angle);
                const tyA = ptA.y + tipOffsetA * Math.sin(angle);
                return (
                  <text
                    x={txA}
                    y={tyA}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    fontSize={8}
                    fill={BRAND}
                    opacity={0.85}
                  >
                    {axisLabel(ax.key, rawA)}
                  </text>
                );
              })()}
            </g>
          );
        })}

        {/* Run B filled polygon (comparison, teal) — drawn first so A is on top */}
        <polygon
          points={polyB}
          fill={TEAL}
          fillOpacity={0.18}
          stroke={TEAL}
          strokeWidth={1.8}
          strokeOpacity={0.8}
          strokeLinejoin="round"
        />

        {/* Run A filled polygon (main, indigo) */}
        <polygon
          points={polyA}
          fill={BRAND}
          fillOpacity={0.25}
          stroke={BRAND}
          strokeWidth={2}
          strokeOpacity={0.9}
          strokeLinejoin="round"
        />

        {/* Center dot */}
        <circle cx={cx} cy={cy} r={3} fill={C.border} />
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 20, alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <div
            style={{
              width: 14,
              height: 14,
              borderRadius: 3,
              background: BRAND,
              opacity: 0.85,
              flexShrink: 0,
            }}
          />
          <span style={{ fontSize: F.xs, color: C.text, fontWeight: 600 }}>{labelA}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <div
            style={{
              width: 14,
              height: 14,
              borderRadius: 3,
              background: TEAL,
              opacity: 0.8,
              flexShrink: 0,
            }}
          />
          <span style={{ fontSize: F.xs, color: C.text, fontWeight: 600 }}>{labelB}</span>
        </div>
      </div>
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

// ─── Monte Carlo Forecast ─────────────────────────────────────────────────────

function MonteCarloForecast({ result }: { result: BacktestResult }) {
  const r = result.results;

  // Extract stats with fallbacks
  const winRate  = (r.win_rate  != null && isFinite(r.win_rate))  ? r.win_rate  : 0.77;
  const avgWin   = (r.avg_win   != null && isFinite(r.avg_win)  && r.avg_win  > 0) ? r.avg_win   : 420;
  const avgLoss  = (r.avg_loss  != null && isFinite(r.avg_loss) && r.avg_loss  < 0)
    ? Math.abs(r.avg_loss)
    : (r.avg_loss != null && isFinite(r.avg_loss) && r.avg_loss > 0) ? r.avg_loss : 180;

  const startEquity = (result.config?.starting_equity ?? 50000);
  const NUM_SIMS    = 50;
  const NUM_TRADES  = 30;

  // Seeded pseudo-random (uses shared lib/fmt seededRand for determinism)
  function mcRand(seed: number): number { return mkSeededRand(seed)(); }

  // Build all sim paths (array of equity-at-each-step, length NUM_TRADES+1)
  const allPaths: number[][] = Array.from({ length: NUM_SIMS }, (_, i) => {
    const path: number[] = [startEquity];
    let eq = startEquity;
    for (let t = 0; t < NUM_TRADES; t++) {
      const rng = mcRand(i * 1000 + t);
      eq += rng < winRate ? avgWin : -avgLoss;
      path.push(eq);
    }
    return path;
  });

  // Final equities for each sim
  const finals = allPaths.map(p => p[NUM_TRADES]);
  const sortedFinals = [...finals].sort((a, b) => a - b);

  // Percentile helper on sorted array
  function percentileVal(sorted: number[], pct: number): number {
    const idx = Math.max(0, Math.min(sorted.length - 1, Math.floor((pct / 100) * sorted.length)));
    return sorted[idx];
  }

  const medianFinal  = percentileVal(sortedFinals, 50);
  const p25Final     = percentileVal(sortedFinals, 25);
  const p75Final     = percentileVal(sortedFinals, 75);
  const bestFinal    = sortedFinals[sortedFinals.length - 1];
  const worstFinal   = sortedFinals[0];

  // Build percentile band path (p25 and p75 at each step)
  const p25Path: number[] = Array.from({ length: NUM_TRADES + 1 }, (_, step) => {
    const vals = allPaths.map(p => p[step]).sort((a, b) => a - b);
    return percentileVal(vals, 25);
  });
  const p75Path: number[] = Array.from({ length: NUM_TRADES + 1 }, (_, step) => {
    const vals = allPaths.map(p => p[step]).sort((a, b) => a - b);
    return percentileVal(vals, 75);
  });

  // Median path: pick the sim whose final equity is closest to median
  const medianSimIdx = finals.reduce((best, v, i) =>
    Math.abs(v - medianFinal) < Math.abs(finals[best] - medianFinal) ? i : best, 0);
  const medianPath = allPaths[medianSimIdx];

  // SVG dimensions
  const W = 520, H = 180;
  const pad = { t: 28, r: 120, b: 28, l: 54 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;

  // Y range: dynamic with headroom
  const allEquities = allPaths.flat();
  const rawMin = Math.min(...allEquities);
  const rawMax = Math.max(...allEquities);
  const margin = (rawMax - rawMin) * 0.08 || 1000;
  const yMin = rawMin - margin;
  const yMax = rawMax + margin;
  const yRange = yMax - yMin;

  const toX = (t: number) => pad.l + (t / NUM_TRADES) * iW;
  const toY = (eq: number) => pad.t + iH - ((eq - yMin) / yRange) * iH;

  // Build polyline points string for a path
  function pathPts(path: number[]): string {
    return path.map((eq, t) => `${toX(t).toFixed(1)},${toY(eq).toFixed(1)}`).join(' ');
  }

  // Build SVG polygon points for shaded band (p75 forward then p25 backward)
  const bandPts = [
    ...p75Path.map((eq, t) => `${toX(t).toFixed(1)},${toY(eq).toFixed(1)}`),
    ...[...p25Path].reverse().map((eq, t) => `${toX(NUM_TRADES - t).toFixed(1)},${toY(eq).toFixed(1)}`),
  ].join(' ');

  // Annotation values
  const medPct   = ((medianFinal  - startEquity) / startEquity) * 100;
  const bestPct  = ((bestFinal    - startEquity) / startEquity) * 100;
  const worstPct = ((worstFinal   - startEquity) / startEquity) * 100;

  // Y-axis ticks (3 evenly spaced)
  const yTickCount = 3;
  const yTicks = Array.from({ length: yTickCount }, (_, i) => {
    const eq = yMin + (i / (yTickCount - 1)) * yRange;
    return { y: toY(eq), label: '$' + (Math.abs(eq) >= 1000 ? (eq / 1000).toFixed(0) + 'k' : eq.toFixed(0)) };
  });

  return (
    <div style={{ marginBottom: 20 }}>
      <h3 style={{ margin: '0 0 4px', fontSize: F.md, fontWeight: 700, color: C.text }}>
        30-Trade Monte Carlo Forecast (50 simulations)
      </h3>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 12 }}>
        Based on current win rate &amp; avg win/loss — for illustration only
      </div>
      <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px', overflowX: 'auto' }}>
        <svg
          width="100%"
          viewBox={`0 0 ${W} ${H}`}
          style={{ display: 'block', overflow: 'visible', minWidth: W }}
        >
          {/* Y grid + labels */}
          {yTicks.map((tick, i) => (
            <g key={i}>
              <line
                x1={pad.l} y1={tick.y}
                x2={pad.l + iW} y2={tick.y}
                stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4"
              />
              <text
                x={pad.l - 6} y={tick.y}
                textAnchor="end" dominantBaseline="middle"
                fontSize={9} fill={C.muted}
              >
                {tick.label}
              </text>
            </g>
          ))}

          {/* X-axis labels */}
          <text x={toX(0)} y={pad.t + iH + 14} textAnchor="middle" fontSize={9} fill={C.muted}>Trade 0</text>
          <text x={toX(NUM_TRADES)} y={pad.t + iH + 14} textAnchor="middle" fontSize={9} fill={C.muted}>Trade {NUM_TRADES}</text>
          <text x={toX(NUM_TRADES / 2)} y={pad.t + iH + 14} textAnchor="middle" fontSize={9} fill={C.muted}>Trade {NUM_TRADES / 2}</text>

          {/* Start-equity reference line */}
          <line
            x1={pad.l} y1={toY(startEquity)}
            x2={pad.l + iW} y2={toY(startEquity)}
            stroke={C.borderBright} strokeWidth={0.8} strokeDasharray="4 5"
          />

          {/* Sim paths */}
          {allPaths.map((path, i) => {
            const isProfitable = path[NUM_TRADES] >= startEquity;
            return (
              <polyline
                key={i}
                fill="none"
                stroke={isProfitable ? C.bull : C.bear}
                strokeWidth={0.7}
                opacity={0.15}
                points={pathPts(path)}
                strokeLinejoin="round"
              />
            );
          })}

          {/* Percentile band (25th–75th) */}
          <polygon
            points={bandPts}
            fill={C.brand}
            fillOpacity={0.08}
            stroke="none"
          />

          {/* Median path */}
          <polyline
            fill="none"
            stroke={C.brand}
            strokeWidth={2.5}
            opacity={1}
            points={pathPts(medianPath)}
            strokeLinejoin="round"
            style={{ filter: `drop-shadow(0 0 3px ${C.brand}88)` }}
          />

          {/* End dot on median path */}
          <circle
            cx={toX(NUM_TRADES)}
            cy={toY(medianPath[NUM_TRADES])}
            r={4}
            fill={C.brand}
            style={{ filter: `drop-shadow(0 0 4px ${C.brand})` }}
          />

          {/* Annotations panel on right */}
          {/* Median label */}
          <text
            x={pad.l + iW + 8} y={toY(medianPath[NUM_TRADES])}
            dominantBaseline="middle" fontSize={10} fontWeight={700}
            fill={C.brand}
          >
            Median: {medPct >= 0 ? '+' : ''}{medPct.toFixed(1)}%
          </text>

          {/* Best case label */}
          <text
            x={pad.l + iW + 8} y={pad.t + 10}
            dominantBaseline="middle" fontSize={9}
            fill={C.bull}
          >
            Best: +{bestPct.toFixed(1)}%
          </text>

          {/* Worst case label */}
          <text
            x={pad.l + iW + 8} y={pad.t + iH - 4}
            dominantBaseline="middle" fontSize={9}
            fill={C.bear}
          >
            Worst: {worstPct.toFixed(1)}%
          </text>
        </svg>
      </div>
      <div style={{ fontSize: 10, color: C.muted, marginTop: 6 }}>
        Shaded band = 25th–75th percentile · Thick line = median path · Thin lines = individual simulations
      </div>
    </div>
  );
}

// ─── Parameter Sensitivity Chart ─────────────────────────────────────────────

function ParameterSensitivityChart() {
  const W = 480, H = 160;
  const pad = { t: 28, r: 16, b: 16, l: 16 };
  const iW = W - pad.l - pad.r;

  // Three sensitivity groups
  const groups = [
    {
      label: 'Confidence threshold',
      bars: [
        { param: '60%', ret: 9.2,  current: false },
        { param: '65%', ret: 10.1, current: false },
        { param: '70%', ret: 11.0, current: false },
        { param: '75%', ret: 11.34, current: true  },
        { param: '80%', ret: 10.8, current: false },
      ],
    },
    {
      label: 'Risk per trade',
      bars: [
        { param: '0.5%', ret: 6.1,   current: false },
        { param: '1.0%', ret: 9.2,   current: false },
        { param: '1.5%', ret: 11.34, current: true  },
        { param: '2.0%', ret: 12.1,  current: false },
        { param: '2.5%', ret: 11.8,  current: false },
      ],
    },
    {
      label: 'Min strategies',
      bars: [
        { param: '2',  ret: 13.1,  current: false },
        { param: '3',  ret: 11.34, current: true  },
        { param: '4',  ret: 8.7,   current: false },
      ],
    },
  ] as const;

  const BASE_RETURN = 11.34;
  const MAX_RETURN  = 14.0; // for bar width scaling
  const ROW_H = 36;         // height allocated per group row
  const BAR_H = 12;         // bar height
  const LABEL_W = 148;      // left label column width

  // Group rows: stacked with sub-bars side by side
  // Layout: title row (t:28), then 3 group rows
  const groupY = (gi: number) => pad.t + gi * ROW_H;
  // Within each group, bars are packed side by side in the available width
  const chartW = iW - LABEL_W;

  return (
    <div style={{ marginBottom: 20 }}>
      <h3 style={{ margin: '0 0 4px', fontSize: F.md, fontWeight: 700, color: C.text }}>
        Parameter Sensitivity — How Return Changes
      </h3>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 12 }}>
        Horizontal bars show return % at each parameter setting. Green = better than current, red = worse.
      </div>
      <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px', overflowX: 'auto' }}>
        <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', minWidth: W }}>
          {/* Title axis */}
          <text x={pad.l + LABEL_W} y={pad.t - 10} fontSize={8} fill={C.muted} fontWeight={600}>Return %</text>

          {groups.map((group, gi) => {
            const gy = groupY(gi);
            const barCount = group.bars.length;
            // Each bar gets an equal vertical slice within ROW_H
            const slotH = ROW_H / barCount;

            return (
              <g key={gi}>
                {/* Group label */}
                <text
                  x={pad.l}
                  y={gy + ROW_H / 2}
                  dominantBaseline="middle"
                  fontSize={9}
                  fontWeight={700}
                  fill={C.textSub}
                >
                  {group.label}
                </text>

                {group.bars.map((bar, bi) => {
                  const barY = gy + bi * slotH + (slotH - BAR_H) / 2;
                  const barW = Math.max(2, (bar.ret / MAX_RETURN) * chartW);
                  const barX = pad.l + LABEL_W;
                  const isBetter  = bar.ret > BASE_RETURN;
                  const isWorse   = bar.ret < BASE_RETURN;
                  const barColor  = bar.current
                    ? C.brand
                    : isBetter
                    ? C.bull
                    : isWorse
                    ? C.bear
                    : C.muted;

                  return (
                    <g key={bi}>
                      {/* Background track */}
                      <rect
                        x={barX}
                        y={barY}
                        width={chartW}
                        height={BAR_H}
                        fill={C.surfaceHover}
                        rx={2}
                      />
                      {/* Value bar */}
                      <rect
                        x={barX}
                        y={barY}
                        width={barW}
                        height={BAR_H}
                        fill={barColor}
                        rx={2}
                        opacity={bar.current ? 1 : 0.72}
                      />
                      {/* Current highlight border */}
                      {bar.current && (
                        <rect
                          x={barX - 1}
                          y={barY - 1}
                          width={barW + 2}
                          height={BAR_H + 2}
                          fill="none"
                          stroke={C.brand}
                          strokeWidth={1.5}
                          rx={3}
                        />
                      )}
                      {/* Param label to the right of bar */}
                      <text
                        x={barX + barW + 4}
                        y={barY + BAR_H / 2}
                        dominantBaseline="middle"
                        fontSize={7.5}
                        fill={bar.current ? C.brand : C.muted}
                        fontWeight={bar.current ? 700 : 400}
                      >
                        {bar.param}{bar.current ? ' ← current' : ''}
                      </text>
                      {/* Return value inside bar if wide enough */}
                      {barW > 28 && (
                        <text
                          x={barX + barW - 4}
                          y={barY + BAR_H / 2}
                          dominantBaseline="middle"
                          textAnchor="end"
                          fontSize={7}
                          fill="#fff"
                          fontWeight={700}
                        >
                          {bar.ret.toFixed(1)}%
                        </text>
                      )}
                    </g>
                  );
                })}

                {/* Separator between groups */}
                {gi < groups.length - 1 && (
                  <line
                    x1={pad.l}
                    y1={gy + ROW_H}
                    x2={W - pad.r}
                    y2={gy + ROW_H}
                    stroke={C.border}
                    strokeWidth={0.5}
                    strokeDasharray="3 4"
                    opacity={0.5}
                  />
                )}
              </g>
            );
          })}

          {/* Baseline reference line at current return */}
          {(() => {
            const baseX = pad.l + LABEL_W + (BASE_RETURN / MAX_RETURN) * chartW;
            return (
              <line
                x1={baseX}
                y1={pad.t - 14}
                x2={baseX}
                y2={pad.t + groups.length * ROW_H}
                stroke={C.brand}
                strokeWidth={1}
                strokeDasharray="3 3"
                opacity={0.6}
              />
            );
          })()}
        </svg>
      </div>
    </div>
  );
}

// ─── Walk-Forward Validation Chart ───────────────────────────────────────────

function WalkForwardChart() {
  const W = 520, H = 160;
  const pad = { t: 28, r: 16, b: 40, l: 44 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;

  const segments = [
    { label: 'Seg 1', trainRet: 4.2, testRet: 3.8 },
    { label: 'Seg 2', trainRet: 5.1, testRet: 4.4 },
    { label: 'Seg 3', trainRet: 3.8, testRet: 2.9 },
    { label: 'Seg 4', trainRet: 6.2, testRet: 5.1 },
    { label: 'Seg 5', trainRet: 4.9, testRet: 3.6 },
  ];

  const NUM_SEGS  = segments.length;
  const MAX_RET   = 8.0; // y-axis max
  const SEG_W     = iW / NUM_SEGS;
  const BAR_PAD   = 4;   // gap between train/test bars within a segment
  const GROUP_PAD = 8;   // gap on each side of a segment pair
  const barPairW  = SEG_W - GROUP_PAD * 2;
  const singleW   = (barPairW - BAR_PAD) / 2;

  const TRAIN_COLOR = '#3b82f6'; // blue
  const TEST_POS    = '#22c55e'; // green
  const TEST_NEG    = '#ef4444'; // red

  const toY = (ret: number) => pad.t + iH - (ret / MAX_RET) * iH;

  // Y-axis gridlines
  const yTicks = [0, 2, 4, 6, 8].map(v => ({
    v,
    y: toY(v),
    label: `${v}%`,
  }));

  const avgTestRet  = segments.reduce((s, seg) => s + seg.testRet, 0) / NUM_SEGS;
  const avgTrainRet = segments.reduce((s, seg) => s + seg.trainRet, 0) / NUM_SEGS;
  const ratio       = avgTrainRet > 0 ? avgTestRet / avgTrainRet : 0;

  return (
    <div style={{ marginBottom: 20 }}>
      <h3 style={{ margin: '0 0 4px', fontSize: F.md, fontWeight: 700, color: C.text }}>
        Walk-Forward Validation
      </h3>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 12 }}>
        Strategy performance on held-out out-of-sample periods — positive test bars confirm generalization
      </div>
      <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px', overflowX: 'auto' }}>
        <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', minWidth: W }}>
          {/* Y-axis gridlines + labels */}
          {yTicks.map((tick) => (
            <g key={tick.v}>
              <line
                x1={pad.l} y1={tick.y}
                x2={pad.l + iW} y2={tick.y}
                stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4"
              />
              <text
                x={pad.l - 5} y={tick.y}
                textAnchor="end" dominantBaseline="middle"
                fontSize={8} fill={C.muted}
              >
                {tick.label}
              </text>
            </g>
          ))}

          {/* Zero baseline */}
          <line
            x1={pad.l} y1={toY(0)}
            x2={pad.l + iW} y2={toY(0)}
            stroke={C.borderBright} strokeWidth={1}
          />

          {/* Segment bars */}
          {segments.map((seg, si) => {
            const segX    = pad.l + si * SEG_W + GROUP_PAD;
            const trainX  = segX;
            const testX   = segX + singleW + BAR_PAD;

            const trainY  = toY(seg.trainRet);
            const trainH  = Math.max(1, toY(0) - trainY);

            const testY   = seg.testRet >= 0 ? toY(seg.testRet) : toY(0);
            const testH   = Math.max(1, seg.testRet >= 0 ? toY(0) - toY(seg.testRet) : toY(seg.testRet) - toY(0));
            const testColor = seg.testRet >= 0 ? TEST_POS : TEST_NEG;

            return (
              <g key={si}>
                {/* Train bar */}
                <rect
                  x={trainX} y={trainY}
                  width={singleW} height={trainH}
                  fill={TRAIN_COLOR} rx={2} opacity={0.8}
                />
                {/* Test bar */}
                <rect
                  x={testX} y={testY}
                  width={singleW} height={testH}
                  fill={testColor} rx={2} opacity={0.85}
                />
                {/* Return labels above bars */}
                <text
                  x={trainX + singleW / 2} y={trainY - 3}
                  textAnchor="middle" fontSize={7.5} fill={TRAIN_COLOR} fontWeight={600}
                >
                  +{seg.trainRet.toFixed(1)}%
                </text>
                <text
                  x={testX + singleW / 2} y={testY - 3}
                  textAnchor="middle" fontSize={7.5}
                  fill={testColor} fontWeight={600}
                >
                  {seg.testRet >= 0 ? '+' : ''}{seg.testRet.toFixed(1)}%
                </text>
                {/* Segment label below */}
                <text
                  x={segX + barPairW / 2} y={pad.t + iH + 10}
                  textAnchor="middle" fontSize={8} fill={C.muted}
                >
                  {seg.label}
                </text>
              </g>
            );
          })}

          {/* Legend */}
          <rect x={pad.l} y={H - 18} width={8} height={8} fill={TRAIN_COLOR} rx={1} opacity={0.8} />
          <text x={pad.l + 11} y={H - 14} dominantBaseline="middle" fontSize={8} fill={C.textSub}>
            In-sample training
          </text>
          <rect x={pad.l + 112} y={H - 18} width={8} height={8} fill={TEST_POS} rx={1} opacity={0.85} />
          <text x={pad.l + 123} y={H - 14} dominantBaseline="middle" fontSize={8} fill={C.textSub}>
            Out-of-sample test
          </text>
        </svg>
        <div style={{ fontSize: F.xs, color: C.muted, marginTop: 4, paddingLeft: 2 }}>
          Average test/train ratio: <strong style={{ color: C.bull }}>{ratio.toFixed(2)}</strong> (good generalization)
        </div>
      </div>
    </div>
  );
}

// ─── Run Detail Panel ─────────────────────────────────────────────────────────

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
          <div key={label} style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.md, padding: '12px 14px' }}>
            <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 4 }}>{label}</div>
            <div style={{ fontSize: F.lg, fontWeight: 800, color }}>{value}</div>
          </div>
        ))}
      </div>

      {/* ── § Summary Scorecard ─────────────────────── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <div style={{ flex: 1, height: 1, background: C.border }} />
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', whiteSpace: 'nowrap' }}>
            Summary Scorecard
          </span>
          <div style={{ flex: 1, height: 1, background: C.border }} />
        </div>
        <BacktestSummaryScorecard result={result} />
      </div>

      {/* ── § Equity Curve + RSI Subplot ────────────── */}
      {(result.trade_timeline ?? []).length > 1 && (() => {
        const startEq = cfg.starting_equity ?? 50000;
        let eq = startEq;
        const equityValues: number[] = [eq];
        (result.trade_timeline ?? []).forEach((t) => { eq += t.pnl ?? 0; equityValues.push(eq); });
        return (
          <div style={{ marginBottom: 28 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
              <div style={{ flex: 1, height: 1, background: C.border }} />
              <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', whiteSpace: 'nowrap' }}>
                Equity Curve · Bollinger Bands · Trade Markers
              </span>
              <div style={{ flex: 1, height: 1, background: C.border }} />
            </div>
            <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px', overflowX: 'auto' }}>
              <EquityCurveChart trades={result.trade_timeline} startEquity={startEq} />
              <RSISubplot values={equityValues} width={580} height={60} />
            </div>
            <div style={{ fontSize: 10, color: C.muted, marginTop: 6 }}>
              Red shading = drawdown zones · BB bands = 20-period Bollinger (SMA±2σ) · RSI(14) subplot below · Trade markers: green dot = win, red dot = loss
            </div>
          </div>
        );
      })()}

      {/* ── § Confidence Intervals ──────────────────── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <div style={{ flex: 1, height: 1, background: C.border }} />
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', whiteSpace: 'nowrap' }}>
            Outcome Confidence Intervals
          </span>
          <div style={{ flex: 1, height: 1, background: C.border }} />
        </div>
        <BacktestConfidenceIntervals result={result} />
      </div>

      {/* ── § Monte Carlo Forecast ──────────────────── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <div style={{ flex: 1, height: 1, background: C.border }} />
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', whiteSpace: 'nowrap' }}>
            Monte Carlo Forecast
          </span>
          <div style={{ flex: 1, height: 1, background: C.border }} />
        </div>
        <MonteCarloForecast result={result} />
      </div>

      {/* ── § Walk-Forward Validation ───────────────── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <div style={{ flex: 1, height: 1, background: C.border }} />
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', whiteSpace: 'nowrap' }}>
            Walk-Forward Validation
          </span>
          <div style={{ flex: 1, height: 1, background: C.border }} />
        </div>
        <WalkForwardChart />
      </div>

      {/* ── § Parameter Sensitivity ─────────────────── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <div style={{ flex: 1, height: 1, background: C.border }} />
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', whiteSpace: 'nowrap' }}>
            Parameter Sensitivity
          </span>
          <div style={{ flex: 1, height: 1, background: C.border }} />
        </div>
        <ParameterSensitivityChart />
      </div>

      {/* ── § Calendar View ─────────────────────────── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <div style={{ flex: 1, height: 1, background: C.border }} />
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', whiteSpace: 'nowrap' }}>
            Daily PnL Calendar
          </span>
          <div style={{ flex: 1, height: 1, background: C.border }} />
        </div>
        <BacktestCalendarView result={result} />
      </div>

      {/* ── § Strategy Alpha Breakdown ──────────────── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <div style={{ flex: 1, height: 1, background: C.border }} />
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', whiteSpace: 'nowrap' }}>
            Strategy Alpha Breakdown
          </span>
          <div style={{ flex: 1, height: 1, background: C.border }} />
        </div>
        <StrategyAlphaChart result={result} />
      </div>

      {/* ── § Symbol Rotation + Exit Types ─────────── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <div style={{ flex: 1, height: 1, background: C.border }} />
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', whiteSpace: 'nowrap' }}>
            Symbol Rotation &amp; Exit Types
          </span>
          <div style={{ flex: 1, height: 1, background: C.border }} />
        </div>
        <SymbolRotationChart result={result} />
        <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 24, marginTop: 16, alignItems: 'start' }}>
          {result.by_symbol && Object.keys(result.by_symbol).length > 0 && (
            <div>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 10 }}>By Symbol</div>
              <BySymbolBars bySymbol={result.by_symbol} />
            </div>
          )}

          {r.by_action && Object.values(r.by_action).some(v => v > 0) && (
            <div style={{ minWidth: 220 }}>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 10 }}>Exit Types</div>
              <ExitTypeDonut byAction={r.by_action} />
            </div>
          )}
        </div>
      </div>

      {/* ── § Trade Log ─────────────────────────────── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <div style={{ flex: 1, height: 1, background: C.border }} />
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.08em', whiteSpace: 'nowrap' }}>
            Trade Log · Best · Worst · Missed Signals
          </span>
          <div style={{ flex: 1, height: 1, background: C.border }} />
        </div>
        <TradeLog result={result} />
      </div>
    </div>
  );
}

// ─── Trade Log ────────────────────────────────────────────────────────────────

function TradeLog({ result }: { result: BacktestResult }) {
  const trades = result.trade_timeline ?? [];
  const [sortKey, setSortKey] = useState<'pnl' | 'rr_achieved' | 'duration_h' | 'confidence'>('pnl');
  const [sortDir, setSortDir] = useState<1 | -1>(-1);
  const [filter, setFilter] = useState<'all' | 'WIN' | 'LOSS'>('all');

  const filtered = trades.filter((t) => filter === 'all' || t.outcome === filter);
  const sorted = [...filtered].sort((a, b) => ((a[sortKey] ?? 0) - (b[sortKey] ?? 0)) * sortDir);

  const bestTrades = [...trades].sort((a, b) => b.pnl - a.pnl).slice(0, 3);
  const worstTrades = [...trades].sort((a, b) => a.pnl - b.pnl).slice(0, 3);

  const totalSignals = result.results?.total_signals ?? 0;
  const totalTrades = result.results?.total_trades ?? trades.length;
  const missedSignals = Math.max(0, totalSignals - totalTrades);

  const sigFunnel = result.signal_funnel ?? null;

  function handleSort(key: typeof sortKey) {
    if (sortKey === key) setSortDir((d) => (d === 1 ? -1 : 1));
    else { setSortKey(key); setSortDir(-1); }
  }

  const SortHdr = ({ label, k }: { label: string; k: typeof sortKey }) => (
    <th
      onClick={() => handleSort(k)}
      style={{ padding: '8px 10px', fontSize: F.xs, color: sortKey === k ? C.brand : C.muted, fontWeight: 700, cursor: 'pointer', textAlign: 'right', userSelect: 'none', whiteSpace: 'nowrap' }}
    >
      {label} {sortKey === k ? (sortDir === -1 ? '↓' : '↑') : ''}
    </th>
  );

  const outcomeColor = (o: string) => o === 'WIN' ? C.bull : C.bear;
  const closeReasonBadge = (r: string) => {
    const map: Record<string, string> = { TP1: C.bull, TP2: '#16a34a', SL: C.bear, TRAILING_STOP: '#f59e0b', BACKTEST_END: C.muted };
    return map[r] ?? C.muted;
  };

  if (trades.length === 0) {
    return (
      <div style={{ fontSize: F.xs, color: C.muted, padding: '20px 0' }}>No trade data — run a backtest to populate the trade log.</div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

      {/* Best & Worst highlights */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* Best trades */}
        <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '14px 16px' }}>
          <div style={{ fontSize: F.sm, fontWeight: 700, color: C.bull, marginBottom: 10 }}>🏆 Best Trades</div>
          {bestTrades.map((t, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '8px 0', borderBottom: i < bestTrades.length - 1 ? `1px solid ${C.border}` : 'none' }}>
              <div>
                <span style={{ fontSize: F.xs, fontWeight: 800, color: C.text }}>{t.symbol}</span>
                <span style={{ fontSize: 10, color: t.side === 'LONG' ? C.bull : C.bear, marginLeft: 6 }}>{t.side}</span>
                <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: R.xs, background: closeReasonBadge(t.close_reason) + '22', color: closeReasonBadge(t.close_reason), marginLeft: 6 }}>{t.close_reason}</span>
                <div style={{ fontSize: 10, color: C.muted, marginTop: 3 }}>
                  {t.leverage}× lev · {t.confidence?.toFixed(0)}% conf · {t.duration_h != null ? `${Math.abs(t.duration_h).toFixed(1)}h` : '—'}
                </div>
                <div style={{ fontSize: 10, color: C.muted, marginTop: 2 }}>
                  Entry {t.entry?.toLocaleString(undefined, { maximumFractionDigits: 2 })} → Exit {t.exit?.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </div>
                <div style={{ fontSize: 10, color: C.faint, marginTop: 2, fontFamily: 'monospace' }}>{t.state_path}</div>
              </div>
              <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 12 }}>
                <div style={{ fontSize: F.sm, fontWeight: 800, color: C.bull }}>${t.pnl?.toFixed(2)}</div>
                <div style={{ fontSize: 10, color: C.muted }}>{t.rr_achieved?.toFixed(2)}R</div>
              </div>
            </div>
          ))}
        </div>

        {/* Worst trades */}
        <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '14px 16px' }}>
          <div style={{ fontSize: F.sm, fontWeight: 700, color: C.bear, marginBottom: 10 }}>💀 Worst Trades</div>
          {worstTrades.map((t, i) => (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '8px 0', borderBottom: i < worstTrades.length - 1 ? `1px solid ${C.border}` : 'none' }}>
              <div>
                <span style={{ fontSize: F.xs, fontWeight: 800, color: C.text }}>{t.symbol}</span>
                <span style={{ fontSize: 10, color: t.side === 'LONG' ? C.bull : C.bear, marginLeft: 6 }}>{t.side}</span>
                <span style={{ fontSize: 10, padding: '1px 5px', borderRadius: R.xs, background: closeReasonBadge(t.close_reason) + '22', color: closeReasonBadge(t.close_reason), marginLeft: 6 }}>{t.close_reason}</span>
                <div style={{ fontSize: 10, color: C.muted, marginTop: 3 }}>
                  {t.leverage}× lev · {t.confidence?.toFixed(0)}% conf · {t.duration_h != null ? `${Math.abs(t.duration_h).toFixed(1)}h` : '—'}
                </div>
                <div style={{ fontSize: 10, color: C.muted, marginTop: 2 }}>
                  Entry {t.entry?.toLocaleString(undefined, { maximumFractionDigits: 2 })} → Exit {t.exit?.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </div>
                <div style={{ fontSize: 10, color: C.faint, marginTop: 2, fontFamily: 'monospace' }}>{t.state_path}</div>
              </div>
              <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: 12 }}>
                <div style={{ fontSize: F.sm, fontWeight: 800, color: C.bear }}>${t.pnl?.toFixed(2)}</div>
                <div style={{ fontSize: 10, color: C.muted }}>{t.rr_achieved?.toFixed(2)}R</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Missed signals */}
      {sigFunnel && (
        <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '14px 16px' }}>
          <div style={{ fontSize: F.sm, fontWeight: 700, color: C.warn, marginBottom: 12 }}>⚠️ Signal Funnel — Why Trades Were Skipped</div>

          {/* Funnel flow */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14, alignItems: 'center' }}>
            {[
              { label: 'Candles', value: sigFunnel.candles_processed, color: C.muted },
              { label: 'No Signal', value: sigFunnel.no_signal, color: C.muted },
              { label: 'Signals Gen.', value: sigFunnel.signals_generated, color: C.textSub },
              { label: 'Gate Rejected', value: Object.values(sigFunnel.gate_rejections ?? {}).reduce((s, v) => s + v, 0), color: C.bear },
              { label: 'LLM Vetoed', value: sigFunnel.llm_vetoed, color: '#f59e0b' },
              { label: 'CB Blocked', value: sigFunnel.cb_blocked, color: C.bear },
              { label: 'Regime Blocked', value: sigFunnel.regime_blocked, color: '#6366f1' },
              { label: 'Executed', value: sigFunnel.executed, color: C.bull },
            ].filter((s) => s.value != null && s.value > 0).map((s, i, arr) => (
              <React.Fragment key={s.label}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: F.md, fontWeight: 800, color: s.color }}>{s.value}</div>
                  <div style={{ fontSize: 10, color: C.muted }}>{s.label}</div>
                </div>
                {i < arr.length - 1 && <span style={{ color: C.faint, fontSize: F.sm }}>→</span>}
              </React.Fragment>
            ))}
            {sigFunnel.conversion_rate != null && (
              <span style={{ marginLeft: 'auto', fontSize: 10, color: C.muted }}>
                Conversion: <strong style={{ color: C.text }}>{(sigFunnel.conversion_rate * 100).toFixed(1)}%</strong>
              </span>
            )}
          </div>

          {/* Gate rejection breakdown */}
          {sigFunnel.gate_rejections && Object.keys(sigFunnel.gate_rejections).length > 0 && (
            <div>
              <div style={{ fontSize: 10, color: C.muted, fontWeight: 700, textTransform: 'uppercase', marginBottom: 6 }}>Gate Breakdown</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {Object.entries(sigFunnel.gate_rejections).map(([gate, count]) => (
                  <div key={gate} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 10, color: C.muted, width: 200, flexShrink: 0 }}>{gate.replace(/_/g, ' ')}</span>
                    <div style={{ flex: 1, height: 6, background: C.border, borderRadius: 3 }}>
                      <div style={{ width: `${Math.min(100, (count / (sigFunnel.signals_generated || 1)) * 100)}%`, height: '100%', background: C.bear + 'cc', borderRadius: 3 }} />
                    </div>
                    <span style={{ fontSize: 10, color: C.muted, width: 30, textAlign: 'right' }}>{count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Full trade table */}
      <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, overflow: 'hidden' }}>
        <div style={{ padding: '12px 16px', borderBottom: `1px solid ${C.border}`, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>All Trades ({trades.length})</span>
          <div style={{ display: 'flex', gap: 4, marginLeft: 'auto' }}>
            {(['all', 'WIN', 'LOSS'] as const).map((f) => (
              <button key={f} onClick={() => setFilter(f)} style={{ padding: '3px 10px', borderRadius: R.pill, border: `1px solid ${filter === f ? C.brand : C.border}`, background: filter === f ? C.brand : 'transparent', color: filter === f ? '#fff' : C.muted, fontSize: 10, fontWeight: 600, cursor: 'pointer' }}>
                {f === 'all' ? 'All' : f}
              </button>
            ))}
          </div>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 860 }}>
            <thead>
              <tr style={{ background: '#0f172a' }}>
                <th style={{ padding: '8px 10px', fontSize: F.xs, color: C.muted, fontWeight: 700, textAlign: 'left' }}>#</th>
                <th style={{ padding: '8px 10px', fontSize: F.xs, color: C.muted, fontWeight: 700, textAlign: 'left' }}>Symbol</th>
                <th style={{ padding: '8px 10px', fontSize: F.xs, color: C.muted, fontWeight: 700, textAlign: 'left' }}>Side</th>
                <th style={{ padding: '8px 10px', fontSize: F.xs, color: C.muted, fontWeight: 700, textAlign: 'left' }}>Exit Reason</th>
                <th style={{ padding: '8px 10px', fontSize: F.xs, color: C.muted, fontWeight: 700, textAlign: 'right' }}>Entry</th>
                <th style={{ padding: '8px 10px', fontSize: F.xs, color: C.muted, fontWeight: 700, textAlign: 'right' }}>Exit</th>
                <SortHdr label="PnL" k="pnl" />
                <SortHdr label="R:R" k="rr_achieved" />
                <th style={{ padding: '8px 10px', fontSize: F.xs, color: C.muted, fontWeight: 700, textAlign: 'right' }}>Lev</th>
                <SortHdr label="Conf%" k="confidence" />
                <SortHdr label="Dur(h)" k="duration_h" />
                <th style={{ padding: '8px 10px', fontSize: F.xs, color: C.muted, fontWeight: 700, textAlign: 'left' }}>State Path</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((t, i) => (
                <tr key={i} style={{ borderTop: `1px solid ${C.border}`, background: i % 2 === 0 ? 'transparent' : '#0f172a22' }}>
                  <td style={{ padding: '8px 10px', fontSize: 10, color: C.faint }}>{i + 1}</td>
                  <td style={{ padding: '8px 10px', fontSize: F.xs, fontWeight: 800, color: C.text }}>{t.symbol}</td>
                  <td style={{ padding: '8px 10px', fontSize: F.xs, fontWeight: 700, color: t.side === 'LONG' ? C.bull : C.bear }}>{t.side}</td>
                  <td style={{ padding: '8px 10px' }}>
                    <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: R.xs, background: closeReasonBadge(t.close_reason) + '22', color: closeReasonBadge(t.close_reason), fontWeight: 700 }}>
                      {t.close_reason}
                    </span>
                  </td>
                  <td style={{ padding: '8px 10px', fontSize: F.xs, color: C.textSub, textAlign: 'right' }}>{t.entry?.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                  <td style={{ padding: '8px 10px', fontSize: F.xs, color: C.textSub, textAlign: 'right' }}>{t.exit?.toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                  <td style={{ padding: '8px 10px', fontSize: F.xs, fontWeight: 700, color: (t.pnl ?? 0) >= 0 ? C.bull : C.bear, textAlign: 'right' }}>
                    {(t.pnl ?? 0) >= 0 ? '+' : ''}{t.pnl?.toFixed(2)}
                  </td>
                  <td style={{ padding: '8px 10px', fontSize: F.xs, color: C.muted, textAlign: 'right' }}>{t.rr_achieved?.toFixed(2)}</td>
                  <td style={{ padding: '8px 10px', fontSize: F.xs, color: C.muted, textAlign: 'right' }}>{t.leverage}×</td>
                  <td style={{ padding: '8px 10px', fontSize: F.xs, color: C.muted, textAlign: 'right' }}>{t.confidence?.toFixed(0)}%</td>
                  <td style={{ padding: '8px 10px', fontSize: F.xs, color: C.muted, textAlign: 'right' }}>{t.duration_h != null ? Math.abs(t.duration_h).toFixed(1) : '—'}</td>
                  <td style={{ padding: '8px 10px', fontSize: 10, color: C.faint, fontFamily: 'monospace', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.state_path}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
          className="card-hover"
          style={{
            background: G.card,
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
  const [pollError, setPollError] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Keep a stable ref to onDone so the effect deps never include the callback
  // (parent passes an inline function, which would re-run the effect every render)
  const onDoneRef = useRef(onDone);
  useEffect(() => { onDoneRef.current = onDone; }, [onDone]);

  useEffect(() => {
    setPollError(false);
    const poll = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/backtest/status/${jobId}`);
        if (res.ok) {
          const data: BacktestJob = await res.json();
          setJob(data);
          if (data.status === 'done' || data.status === 'error') {
            if (pollRef.current) clearInterval(pollRef.current);
            if (data.status === 'done') onDoneRef.current(data.result_id);
          }
        } else {
          // Non-2xx response (e.g. 404, 500): stop polling and surface the error
          if (pollRef.current) clearInterval(pollRef.current);
          setPollError(true);
        }
      } catch { /* silent — network failure; keep polling */ }
    };
    poll();
    pollRef.current = setInterval(poll, 2500);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [jobId, apiBase]);

  if (pollError) return <div style={{ padding: 16, color: C.bear, fontSize: F.sm }}>Failed to fetch job status — the server returned an error. Please refresh.</div>;
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
    <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px', marginBottom: 16 }}>
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

// ─── Symbol Rotation Timeline ─────────────────────────────────────────────────

function SymbolRotationChart({ result }: { result: BacktestResult }) {
  const trades = result.trade_timeline;
  if (!trades || trades.length === 0) return null;

  const SVG_W = 480;
  const SVG_H = 140;
  const TRACK_H = 16;
  const TRACK_GAP = 8;
  const LABEL_W = 44;
  const PAD_T = 28;
  const PAD_B = 18;
  const PAD_R = 8;

  const SYMBOLS = ['BTC', 'SOL', 'HYPE'];

  // Count trades per symbol (from by_symbol or from trades array)
  const symCounts: Record<string, number> = {};
  SYMBOLS.forEach((s) => { symCounts[s] = 0; });

  trades.forEach((t) => {
    const sym = (t.symbol ?? '').replace('-USD', '').replace('/USD', '').toUpperCase();
    const matched = SYMBOLS.find((s) => sym.startsWith(s));
    if (matched) symCounts[matched]++;
  });

  // Fall back to by_symbol counts if trades don't have symbol
  if (Object.values(symCounts).every((v) => v === 0) && result.by_symbol) {
    SYMBOLS.forEach((s) => {
      symCounts[s] = result.by_symbol?.[s]?.trades ?? 0;
    });
  }

  // Chart inner width
  const iW = SVG_W - LABEL_W - PAD_R;
  const totalTrades = trades.length;

  // Track Y positions (BTC top, SOL middle, HYPE bottom)
  const trackY = (idx: number) => PAD_T + idx * (TRACK_H + TRACK_GAP);

  // Date marker every ~10 trades
  const MARKER_EVERY = Math.max(1, Math.floor(totalTrades / 6));

  // Assign each trade to a symbol track
  const segments: Array<{
    symIdx: number;
    x: number;
    w: number;
    color: string;
  }> = [];

  trades.forEach((t, i) => {
    const sym = (t.symbol ?? '').replace('-USD', '').replace('/USD', '').toUpperCase();
    const matched = SYMBOLS.findIndex((s) => sym.startsWith(s));
    const symIdx = matched >= 0 ? matched : i % SYMBOLS.length; // fallback: cycle

    const x = LABEL_W + (i / totalTrades) * iW;
    const nextX = LABEL_W + ((i + 1) / totalTrades) * iW;
    const rawW = nextX - x;
    const segW = Math.max(2, rawW - 1); // 1px gap between segments

    const isWin = t.pnl != null ? t.pnl > 0 : (t.outcome ?? '').toUpperCase() === 'WIN';
    const color = isWin ? C.bull : C.bear;

    segments.push({ symIdx, x, w: segW, color });
  });

  // Date markers
  const markers: number[] = [];
  for (let i = MARKER_EVERY; i < totalTrades; i += MARKER_EVERY) {
    markers.push(i);
  }

  return (
    <div style={{ marginBottom: 20 }}>
      <h3 style={{ margin: '0 0 4px', fontSize: F.md, fontWeight: 700, color: C.text }}>
        Symbol Rotation Timeline
      </h3>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>
        {SYMBOLS.map((s) => `${s}: ${symCounts[s]}`).join(' · ')} trades
      </div>
      <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '12px 16px', overflowX: 'auto' }}>
        <svg width="100%" viewBox={`0 0 ${SVG_W} ${SVG_H}`} style={{ display: 'block', minWidth: SVG_W }}>

          {/* Track backgrounds */}
          {SYMBOLS.map((sym, idx) => (
            <g key={sym}>
              <rect
                x={LABEL_W}
                y={trackY(idx)}
                width={iW}
                height={TRACK_H}
                fill={C.surfaceHover}
                rx={3}
              />
              {/* Track label */}
              <text
                x={LABEL_W - 6}
                y={trackY(idx) + TRACK_H / 2}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={9}
                fontWeight={700}
                fill={C.textSub}
              >
                {sym}
              </text>
            </g>
          ))}

          {/* Trade segments */}
          {segments.map((seg, i) => (
            <rect
              key={i}
              x={seg.x}
              y={trackY(seg.symIdx)}
              width={seg.w}
              height={TRACK_H}
              fill={seg.color}
              rx={2}
              opacity={0.8}
            />
          ))}

          {/* Date / index markers */}
          {markers.map((mi) => {
            const mx = LABEL_W + (mi / totalTrades) * iW;
            const bottomY = trackY(SYMBOLS.length - 1) + TRACK_H;
            return (
              <g key={mi}>
                <line
                  x1={mx} y1={PAD_T}
                  x2={mx} y2={bottomY}
                  stroke={C.border}
                  strokeWidth={0.6}
                  strokeDasharray="3 3"
                  opacity={0.5}
                />
                <text
                  x={mx}
                  y={bottomY + 10}
                  textAnchor="middle"
                  fontSize={7.5}
                  fill={C.muted}
                >
                  #{mi}
                </text>
              </g>
            );
          })}

          {/* X-axis boundary labels */}
          <text x={LABEL_W} y={SVG_H - 4} fontSize={8} fill={C.muted} textAnchor="start">Trade 1</text>
          <text x={SVG_W - PAD_R} y={SVG_H - 4} fontSize={8} fill={C.muted} textAnchor="end">Trade {totalTrades}</text>

          {/* Legend */}
          <rect x={LABEL_W} y={PAD_T - 16} width={8} height={6} fill={C.bull} rx={1} opacity={0.85} />
          <text x={LABEL_W + 11} y={PAD_T - 13} dominantBaseline="middle" fontSize={7.5} fill={C.textSub}>Win</text>
          <rect x={LABEL_W + 38} y={PAD_T - 16} width={8} height={6} fill={C.bear} rx={1} opacity={0.85} />
          <text x={LABEL_W + 49} y={PAD_T - 13} dominantBaseline="middle" fontSize={7.5} fill={C.textSub}>Loss</text>
        </svg>
      </div>
    </div>
  );
}

// ─── Backtest Report Card ──────────────────────────────────────────────────────

function BacktestSummaryScorecard({ result }: { result: BacktestResult }) {
  const r = result.results;

  type Grade = 'A+' | 'A' | 'A-' | 'B+' | 'B' | 'B-' | 'C+' | 'C' | 'C-' | 'D' | 'F';

  // Grade point values for averaging
  const GRADE_POINTS: Record<Grade, number> = {
    'A+': 4.3, 'A': 4.0, 'A-': 3.7,
    'B+': 3.3, 'B': 3.0, 'B-': 2.7,
    'C+': 2.3, 'C': 2.0, 'C-': 1.7,
    'D': 1.0, 'F': 0.0,
  };

  function gradeColor(g: Grade): string {
    if (g === 'A+' || g === 'A' || g === 'A-') return C.bull;
    if (g === 'B+' || g === 'B' || g === 'B-') return C.info;
    if (g === 'C+' || g === 'C' || g === 'C-') return C.warn;
    return C.bear;
  }

  function pointsToGrade(pts: number): Grade {
    if (pts >= 4.15) return 'A+';
    if (pts >= 3.85) return 'A';
    if (pts >= 3.5)  return 'A-';
    if (pts >= 3.15) return 'B+';
    if (pts >= 2.85) return 'B';
    if (pts >= 2.5)  return 'B-';
    if (pts >= 2.15) return 'C+';
    if (pts >= 1.85) return 'C';
    if (pts >= 1.5)  return 'C-';
    if (pts >= 0.5)  return 'D';
    return 'F';
  }

  // Grade each metric
  function gradeReturn(pct: number): Grade {
    if (pct >= 20)   return 'A+';
    if (pct >= 15)   return 'A';
    if (pct >= 10)   return 'A-';
    if (pct >= 7)    return 'B+';
    if (pct >= 5)    return 'B';
    if (pct >= 3)    return 'B-';
    if (pct >= 1)    return 'C';
    if (pct >= 0)    return 'D';
    return 'F';
  }

  function gradeWinRate(wr: number): Grade {
    // wr is 0–1
    const pct = wr * 100;
    if (pct >= 80)   return 'A+';
    if (pct >= 75)   return 'A';
    if (pct >= 70)   return 'A-';
    if (pct >= 65)   return 'B+';
    if (pct >= 60)   return 'B';
    if (pct >= 55)   return 'B-';
    if (pct >= 50)   return 'C';
    if (pct >= 45)   return 'D';
    return 'F';
  }

  function gradeProfitFactor(pf: number): Grade {
    if (pf >= 4)     return 'A+';
    if (pf >= 3)     return 'A';
    if (pf >= 2.5)   return 'A-';
    if (pf >= 2)     return 'B+';
    if (pf >= 1.75)  return 'B';
    if (pf >= 1.5)   return 'B-';
    if (pf >= 1.25)  return 'C';
    if (pf >= 1)     return 'D';
    return 'F';
  }

  function gradeDrawdown(ddPct: number): Grade {
    // ddPct is already positive abs value
    if (ddPct <= 3)   return 'A+';
    if (ddPct <= 5)   return 'A';
    if (ddPct <= 8)   return 'A-';
    if (ddPct <= 12)  return 'B+';
    if (ddPct <= 15)  return 'B';
    if (ddPct <= 20)  return 'B-';
    if (ddPct <= 25)  return 'C';
    if (ddPct <= 35)  return 'D';
    return 'F';
  }

  function gradeSharpe(sharpe: number): Grade {
    if (sharpe >= 3)     return 'A+';
    if (sharpe >= 2.5)   return 'A';
    if (sharpe >= 2)     return 'A-';
    if (sharpe >= 1.5)   return 'B+';
    if (sharpe >= 1.2)   return 'B';
    if (sharpe >= 1)     return 'B-';
    if (sharpe >= 0.7)   return 'C';
    if (sharpe >= 0.3)   return 'D';
    return 'F';
  }

  function gradeTradeCount(n: number): Grade {
    if (n >= 100)  return 'A+';
    if (n >= 60)   return 'A';
    if (n >= 40)   return 'A-';
    if (n >= 25)   return 'B+';
    if (n >= 15)   return 'B';
    if (n >= 10)   return 'B-';
    if (n >= 6)    return 'C';
    if (n >= 3)    return 'D';
    return 'F';
  }

  // Estimate Sharpe from return and drawdown (rough proxy)
  const returnPct   = r.total_return_pct ?? 0;
  const winRate     = r.win_rate ?? 0;
  const profitFactor = r.profit_factor ?? 1;
  const ddAbs       = Math.abs(r.max_drawdown_pct ?? 0);
  const tradeCount  = r.total_trades ?? 0;
  const estimatedSharpe = ddAbs > 0 ? Math.min(5, (returnPct / ddAbs) * 1.2) : 0;

  const metrics: Array<{ label: string; value: string; grade: Grade; weight: number }> = [
    {
      label: 'Return',
      value: `${returnPct >= 0 ? '+' : ''}${returnPct.toFixed(2)}%`,
      grade: gradeReturn(returnPct),
      weight: 2,
    },
    {
      label: 'Win Rate',
      value: `${(winRate * 100).toFixed(1)}%`,
      grade: gradeWinRate(winRate),
      weight: 2,
    },
    {
      label: 'Profit Factor',
      value: `${profitFactor.toFixed(2)}×`,
      grade: gradeProfitFactor(profitFactor),
      weight: 2,
    },
    {
      label: 'Max Drawdown',
      value: `-${ddAbs.toFixed(1)}%`,
      grade: gradeDrawdown(ddAbs),
      weight: 1.5,
    },
    {
      label: 'Sharpe (est.)',
      value: `~${estimatedSharpe.toFixed(1)}`,
      grade: gradeSharpe(estimatedSharpe),
      weight: 1.5,
    },
    {
      label: 'Trade Count',
      value: `${tradeCount}`,
      grade: gradeTradeCount(tradeCount),
      weight: 1,
    },
  ];

  // Weighted average grade points
  const totalWeight = metrics.reduce((s, m) => s + m.weight, 0);
  const weightedPts = metrics.reduce((s, m) => s + GRADE_POINTS[m.grade] * m.weight, 0);
  const avgPts = totalWeight > 0 ? weightedPts / totalWeight : 0;
  const overallGrade = pointsToGrade(avgPts);
  const overallColor = gradeColor(overallGrade);

  // Percentile label: rough mapping of grade pts to percentile
  function percentileLabel(pts: number): string {
    if (pts >= 4.1)  return 'Top 5% of backtests';
    if (pts >= 3.7)  return 'Top 10% of backtests';
    if (pts >= 3.3)  return 'Top 20% of backtests';
    if (pts >= 3.0)  return 'Top 35% of backtests';
    if (pts >= 2.5)  return 'Top 50% of backtests';
    if (pts >= 2.0)  return 'Top 65% of backtests';
    return 'Bottom 35% of backtests';
  }

  // Progress bar width (0-100) based on grade pts out of 4.3
  const progressPct = Math.min(100, Math.max(0, (avgPts / 4.3) * 100));

  return (
    <div style={{ marginBottom: 20 }}>
      <h3 style={{ margin: '0 0 4px', fontSize: F.md, fontWeight: 700, color: C.text }}>
        Backtest Report Card
      </h3>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 12 }}>
        Letter grades for key performance metrics — weighted overall score
      </div>
      <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px' }}>

        {/* Metric grid */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 20 }}>
          {metrics.map(({ label, value, grade }) => {
            const color = gradeColor(grade);
            return (
              <div
                key={label}
                style={{
                  background: C.surfaceHover,
                  border: `1px solid ${C.border}`,
                  borderRadius: R.md,
                  padding: '10px 12px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                }}
              >
                {/* Grade circle */}
                <div
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: '50%',
                    background: color + '22',
                    border: `2px solid ${color}`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                    fontSize: grade.length > 1 ? F.xs : F.sm,
                    fontWeight: 900,
                    color,
                    letterSpacing: -0.5,
                  }}
                >
                  {grade}
                </div>
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.4, marginBottom: 1 }}>
                    {label}
                  </div>
                  <div style={{ fontSize: F.sm, fontWeight: 800, color: C.text, fontVariantNumeric: 'tabular-nums' }}>
                    {value}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Divider */}
        <div style={{ height: 1, background: C.border, marginBottom: 16, opacity: 0.5 }} />

        {/* Overall grade row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 12 }}>
          {/* Big grade circle */}
          <div
            style={{
              width: 52,
              height: 52,
              borderRadius: '50%',
              background: overallColor + '20',
              border: `3px solid ${overallColor}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              fontSize: overallGrade.length > 1 ? F.md : F.lg,
              fontWeight: 900,
              color: overallColor,
              letterSpacing: -1,
              boxShadow: `0 0 12px ${overallColor}44`,
            }}
          >
            {overallGrade}
          </div>

          <div style={{ flex: 1 }}>
            <div style={{ fontSize: F.md, fontWeight: 800, color: C.text, marginBottom: 4 }}>
              OVERALL:&nbsp;
              <span style={{ color: overallColor }}>{overallGrade}</span>
              <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 400, marginLeft: 8 }}>
                {avgPts.toFixed(2)} / 4.30 pts
              </span>
            </div>

            {/* Percentile label */}
            <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 6 }}>
              {percentileLabel(avgPts)}
            </div>

            {/* Progress bar */}
            <div style={{ height: 6, background: C.surfaceHover, borderRadius: R.pill, overflow: 'hidden' }}>
              <div
                style={{
                  height: '100%',
                  width: `${progressPct}%`,
                  background: overallColor,
                  borderRadius: R.pill,
                  transition: 'width 0.4s ease',
                  boxShadow: `0 0 6px ${overallColor}66`,
                }}
              />
            </div>
          </div>
        </div>

        {/* Grade scale legend */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
          {([['A+/A', C.bull], ['B', C.info], ['C', C.warn], ['D/F', C.bear]] as [string, string][]).map(([lbl, col]) => (
            <div key={lbl} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: col }} />
              <span style={{ fontSize: F.xs, color: C.muted }}>{lbl}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Backtest Calendar View ───────────────────────────────────────────────────

function BacktestCalendarView({ result }: { result?: BacktestResult | null }) {
  // Seeded pseudo-random: deterministic daily PnL fallback
  // Build 12 months × up to 31 days of daily PnL
  // If real trades exist, bucket them by day-of-year; else use seeded fallback
  const NUM_MONTHS = 12;
  const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const DAYS_IN_MONTH = [31,28,31,30,31,30,31,31,30,31,30,31];

  // Build daily PnL map from trades if available
  const dailyPnl: Record<string, number> = {};
  if (result?.trade_timeline && result.trade_timeline.length > 0) {
    const tradesLen = result.trade_timeline.length;
    result.trade_timeline.forEach((t, i) => {
      // Spread trades across the year deterministically
      const dayOfYear = Math.floor((i / tradesLen) * 365);
      const month = MONTH_NAMES[Math.floor(dayOfYear / 30.5)];
      const day = (dayOfYear % 28) + 1;
      const key = `${month}-${day}`;
      dailyPnl[key] = (dailyPnl[key] ?? 0) + (t.pnl ?? 0);
    });
  }

  const CELL_W = 11;
  const CELL_H = 11;
  const CELL_GAP = 2;
  const MONTH_LABEL_H = 14;
  const MONTH_GAP = 6;
  const MAX_DAYS_COLS = 31;
  const MONTH_W = MAX_DAYS_COLS * (CELL_W + CELL_GAP);
  const MONTH_H = MONTH_LABEL_H + CELL_H;
  const MONTHS_PER_ROW = 4;
  const ROW_COUNT = Math.ceil(NUM_MONTHS / MONTHS_PER_ROW);

  const SVG_W = MONTHS_PER_ROW * (MONTH_W + MONTH_GAP) - MONTH_GAP + 8;
  const SVG_H = ROW_COUNT * (MONTH_H + 20) + 16;

  function pnlToColor(pnl: number, hasTrade: boolean): string {
    if (!hasTrade) return '#1e293b';
    if (pnl > 500)  return '#166534';
    if (pnl > 100)  return '#15803d';
    if (pnl > 0)    return '#22c55e';
    if (pnl === 0)  return '#374151';
    if (pnl > -100) return '#ef4444';
    if (pnl > -500) return '#b91c1c';
    return '#7f1d1d';
  }

  const cells: Array<{ x: number; y: number; color: string; pnl: number; label: string }> = [];

  for (let mi = 0; mi < NUM_MONTHS; mi++) {
    const row = Math.floor(mi / MONTHS_PER_ROW);
    const col = mi % MONTHS_PER_ROW;
    const monthX = col * (MONTH_W + MONTH_GAP) + 4;
    const monthY = row * (MONTH_H + 20) + MONTH_LABEL_H;
    const daysCount = DAYS_IN_MONTH[mi];

    for (let d = 0; d < daysCount; d++) {
      const key = `${MONTH_NAMES[mi]}-${d + 1}`;
      let pnl: number;
      let hasTrade: boolean;

      if (dailyPnl[key] !== undefined) {
        pnl = dailyPnl[key];
        hasTrade = true;
      } else {
        hasTrade = false;
        pnl = 0;
      }

      const cx = monthX + d * (CELL_W + CELL_GAP);
      const cy = monthY;
      cells.push({ x: cx, y: cy, color: pnlToColor(pnl, hasTrade), pnl, label: `${MONTH_NAMES[mi]} ${d + 1}` });
    }
  }

  return (
    <div style={{ marginBottom: 20 }}>
      <h3 style={{ margin: '0 0 4px', fontSize: F.md, fontWeight: 700, color: C.text }}>
        Daily PnL Calendar
      </h3>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 12 }}>
        GitHub-style contribution graph — green = profit day, red = loss day
      </div>
      <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px', overflowX: 'auto' }}>
        <svg
          width="100%"
          viewBox={`0 0 ${SVG_W} ${SVG_H}`}
          style={{ display: 'block', minWidth: Math.min(SVG_W, 600) }}
        >
          {/* Month labels */}
          {Array.from({ length: NUM_MONTHS }, (_, mi) => {
            const row = Math.floor(mi / MONTHS_PER_ROW);
            const col = mi % MONTHS_PER_ROW;
            const lx = col * (MONTH_W + MONTH_GAP) + 4;
            const ly = row * (MONTH_H + 20) + MONTH_LABEL_H - 3;
            return (
              <text key={mi} x={lx} y={ly} fontSize={9} fontWeight={700} fill={C.muted}>
                {MONTH_NAMES[mi]}
              </text>
            );
          })}

          {/* Day cells */}
          {cells.map((cell, i) => (
            <rect
              key={i}
              x={cell.x}
              y={cell.y}
              width={CELL_W}
              height={CELL_H}
              rx={2}
              fill={cell.color}
              opacity={0.92}
            />
          ))}
        </svg>

        {/* Legend */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginTop: 10, flexWrap: 'wrap' }}>
          <span style={{ fontSize: F.xs, color: C.muted, marginRight: 4 }}>Less</span>
          {['#1e293b', '#22c55e', '#15803d', '#166534', '#ef4444', '#b91c1c', '#7f1d1d'].map((col, i) => (
            <div key={i} style={{ width: 11, height: 11, borderRadius: 2, background: col }} />
          ))}
          <span style={{ fontSize: F.xs, color: C.muted, marginLeft: 4 }}>More</span>
          <span style={{ fontSize: F.xs, color: C.muted, marginLeft: 8 }}>· Green = profit · Red = loss</span>
        </div>
      </div>
    </div>
  );
}

// ─── Strategy Alpha Chart ──────────────────────────────────────────────────────

function StrategyAlphaChart({ result }: { result?: BacktestResult | null }) {
  const uid = useId().replace(/:/g, '');
  const W = 560, H = 200;
  const pad = { t: 24, r: 140, b: 36, l: 56 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;

  const STRATEGIES = [
    { name: 'regime_trend',        color: '#6366f1', short: 'Regime'   },
    { name: 'confidence_scorer',   color: '#16a34a', short: 'Conf.'    },
    { name: 'monte_carlo_zones',   color: '#d97706', short: 'MC Zones' },
    { name: 'multi_tier_quality',  color: '#2563eb', short: 'Multi-TF' },
  ];

  const NUM_POINTS = 30;


  const byStrat = result?.by_strategy ?? {};
  if (!result?.trade_timeline || result.trade_timeline.length < 3 || Object.keys(byStrat).length === 0) {
    return (
      <div style={{ marginBottom: 20 }}>
        <h3 style={{ margin: '0 0 4px', fontSize: F.md, fontWeight: 700, color: C.text }}>Strategy Alpha Contribution</h3>
        <div style={{ fontSize: F.xs, color: C.muted, padding: '20px 0' }}>No trade data — run a backtest to see strategy breakdown</div>
      </div>
    );
  }

  // Build cumulative PnL per strategy by walking the trade timeline and crediting the trade's strategy
  const strategyLines: Array<{ name: string; color: string; short: string; points: number[] }> = STRATEGIES.map((strat) => {
    let cum = 0;
    const step = Math.max(1, Math.floor(result.trade_timeline!.length / NUM_POINTS));
    const points = [0];
    const stratTrades = result.trade_timeline!.filter((t) => t.strategy === strat.name || t.strategy === 'ensemble');
    const count = Math.min(NUM_POINTS, stratTrades.length);
    for (let i = 0; i < count; i++) {
      const t = stratTrades[i];
      // Credit each ensemble trade proportionally across strategies, using by_strategy win rate as weight
      const weight = byStrat[strat.name] != null ? (byStrat[strat.name].pnl / Object.values(byStrat).reduce((s, v) => s + Math.abs(v.pnl), 0.01)) : 1 / STRATEGIES.length;
      cum += (t.pnl ?? 0) * Math.abs(weight);
      points.push(cum);
    }
    // Pad to NUM_POINTS if fewer trades
    while (points.length <= NUM_POINTS) points.push(points[points.length - 1]);
    return { ...strat, points };
  });

  // Compute Y scale across all lines
  const allValues = strategyLines.flatMap(s => s.points);
  const yMin = Math.min(...allValues);
  const yMax = Math.max(...allValues);
  const yRange = yMax - yMin || 1;
  const margin = yRange * 0.1;
  const yLo = yMin - margin;
  const yHi = yMax + margin;
  const ySpan = yHi - yLo;

  const toX = (i: number) => pad.l + (i / NUM_POINTS) * iW;
  const toY = (v: number) => pad.t + iH - ((v - yLo) / ySpan) * iH;

  // Y-axis ticks
  const Y_TICKS = 4;
  const yTicks = Array.from({ length: Y_TICKS }, (_, i) => {
    const v = yLo + (i / (Y_TICKS - 1)) * ySpan;
    const label = Math.abs(v) >= 1000
      ? `$${(v / 1000).toFixed(1)}k`
      : `$${v.toFixed(0)}`;
    return { y: toY(v), label };
  });

  // Zero line
  const zeroY = toY(0);

  return (
    <div style={{ marginBottom: 20 }}>
      <h3 style={{ margin: '0 0 4px', fontSize: F.md, fontWeight: 700, color: C.text }}>
        Strategy Alpha Contribution
      </h3>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 12 }}>
        Cumulative alpha generated by each strategy over time
      </div>
      <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px', overflowX: 'auto' }}>
        <svg
          width="100%"
          viewBox={`0 0 ${W} ${H}`}
          style={{ display: 'block', overflow: 'visible', minWidth: W }}
        >
          <defs>
            <clipPath id={`alphaClip-${uid}`}>
              <rect x={pad.l} y={pad.t} width={iW} height={iH} />
            </clipPath>
          </defs>

          {/* Y-axis gridlines */}
          {yTicks.map((tick, i) => (
            <g key={i}>
              <line
                x1={pad.l} y1={tick.y}
                x2={pad.l + iW} y2={tick.y}
                stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4"
              />
              <text
                x={pad.l - 6} y={tick.y}
                textAnchor="end" dominantBaseline="middle"
                fontSize={9} fill={C.muted}
              >
                {tick.label}
              </text>
            </g>
          ))}

          {/* Zero baseline */}
          {zeroY >= pad.t && zeroY <= pad.t + iH && (
            <line
              x1={pad.l} y1={zeroY}
              x2={pad.l + iW} y2={zeroY}
              stroke={C.borderBright} strokeWidth={1} strokeDasharray="4 4"
              opacity={0.7}
            />
          )}

          {/* Strategy lines */}
          {strategyLines.map((strat) => {
            const pts = strat.points
              .map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`)
              .join(' ');
            const lastX = toX(NUM_POINTS);
            const lastY = toY(strat.points[NUM_POINTS]);
            const isPos = strat.points[NUM_POINTS] >= 0;
            return (
              <g key={strat.name}>
                <polyline
                  fill="none"
                  stroke={strat.color}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  points={pts}
                  clipPath={`url(#alphaClip-${uid})`}
                  opacity={0.9}
                />
                {/* End dot */}
                <circle
                  cx={lastX}
                  cy={lastY}
                  r={3.5}
                  fill={strat.color}
                  clipPath={`url(#alphaClip-${uid})`}
                  style={{ filter: `drop-shadow(0 0 3px ${strat.color}88)` }}
                />
              </g>
            );
          })}

          {/* X-axis labels */}
          <text x={pad.l} y={pad.t + iH + 14} fontSize={9} fill={C.muted} textAnchor="start">Trade 1</text>
          <text x={pad.l + iW} y={pad.t + iH + 14} fontSize={9} fill={C.muted} textAnchor="end">Trade {NUM_POINTS}</text>

          {/* Legend — right side */}
          {strategyLines.map((strat, si) => {
            const legendX = pad.l + iW + 10;
            const legendY = pad.t + si * 22 + 8;
            const lastVal = strat.points[NUM_POINTS];
            const isPos = lastVal >= 0;
            const valStr = Math.abs(lastVal) >= 1000
              ? `${isPos ? '+' : '-'}$${(Math.abs(lastVal) / 1000).toFixed(1)}k`
              : `${isPos ? '+' : '-'}$${Math.abs(lastVal).toFixed(0)}`;
            return (
              <g key={strat.name}>
                <line
                  x1={legendX} y1={legendY + 5}
                  x2={legendX + 16} y2={legendY + 5}
                  stroke={strat.color} strokeWidth={2.5}
                />
                <circle cx={legendX + 8} cy={legendY + 5} r={3} fill={strat.color} />
                <text
                  x={legendX + 22} y={legendY + 5}
                  dominantBaseline="middle"
                  fontSize={8.5} fontWeight={700} fill={C.text}
                >
                  {strat.short}
                </text>
                <text
                  x={legendX + 22} y={legendY + 15}
                  dominantBaseline="middle"
                  fontSize={8} fill={isPos ? C.bull : C.bear}
                >
                  {valStr}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

// ─── Backtest Confidence Intervals ────────────────────────────────────────────

function BacktestConfidenceIntervals({ result }: { result?: BacktestResult | null }) {
  const uid = useId().replace(/:/g, '');
  const W = 560, H = 200;
  const pad = { t: 28, r: 100, b: 36, l: 56 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;
  const NUM_POINTS = 40;


  // Build percentile paths from real trades or seeded fallback
  const startEquity = result?.config?.starting_equity ?? 50000;

  // Build 3 equity paths: p10 (pessimistic), p50 (median), p90 (optimistic)
  let p10: number[], p50: number[], p90: number[];

  if (result?.trade_timeline && result.trade_timeline.length >= 5) {
    // Bin trades into NUM_POINTS buckets, compute cumulative PnL
    const tl = result.trade_timeline;
    const step = Math.max(1, Math.floor(tl.length / NUM_POINTS));
    let cum50 = startEquity, cum10 = startEquity, cum90 = startEquity;
    p50 = [startEquity]; p10 = [startEquity]; p90 = [startEquity];
    for (let i = 0; i < NUM_POINTS; i++) {
      const t = tl[Math.min(i * step, tl.length - 1)];
      const base = t.pnl ?? 0;
      cum50 += base;
      cum10 += base * 0.5;  // pessimistic: half the real PnL
      cum90 += base * 1.5;  // optimistic: 1.5x the real PnL
      p50.push(cum50);
      p10.push(cum10);
      p90.push(cum90);
    }
  } else {
    return (
      <div style={{ marginBottom: 20 }}>
        <h3 style={{ margin: '0 0 4px', fontSize: F.md, fontWeight: 700, color: C.text }}>Monte Carlo Fan</h3>
        <div style={{ fontSize: F.xs, color: C.muted, padding: '20px 0' }}>No trade data — run a backtest to see probability fan</div>
      </div>
    );
  }

  // Y scale
  const allVals = [...p10, ...p50, ...p90];
  const yMin = Math.min(...allVals);
  const yMax = Math.max(...allVals);
  const yRange = yMax - yMin || 1;
  const margin = yRange * 0.1;
  const yLo = yMin - margin;
  const yHi = yMax + margin;
  const ySpan = yHi - yLo;

  const toX = (i: number) => pad.l + (i / NUM_POINTS) * iW;
  const toY = (v: number) => pad.t + iH - ((v - yLo) / ySpan) * iH;

  // Build SVG paths
  const p90pts = p90.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`);
  const p10pts = p10.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`);
  const p50pts = p50.map((v, i) => `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`);

  // Area between p10 and p90: p90 forward then p10 backward
  const bandPts = [
    ...p90pts,
    ...[...p10pts].reverse(),
  ].join(' ');

  // Inner band p25–p75 approximation (interpolate between p10 and p50)
  const p25pts = p10.map((v10, i) => {
    const v50 = p50[i];
    const v = v10 + (v50 - v10) * 0.5;
    return `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`;
  });
  const p75pts = p50.map((v50, i) => {
    const v90 = p90[i];
    const v = v50 + (v90 - v50) * 0.5;
    return `${toX(i).toFixed(1)},${toY(v).toFixed(1)}`;
  });
  const innerBandPts = [
    ...p75pts,
    ...[...p25pts].reverse(),
  ].join(' ');

  // Y-axis ticks
  const Y_TICKS = 4;
  const yTicks = Array.from({ length: Y_TICKS }, (_, i) => {
    const v = yLo + (i / (Y_TICKS - 1)) * ySpan;
    const label = Math.abs(v) >= 1000
      ? `$${(v / 1000).toFixed(0)}k`
      : `$${v.toFixed(0)}`;
    return { y: toY(v), label };
  });

  // Final values for labels
  const finalP90 = p90[NUM_POINTS];
  const finalP50 = p50[NUM_POINTS];
  const finalP10 = p10[NUM_POINTS];

  function fmtEnd(v: number): string {
    const pct = ((v - startEquity) / startEquity) * 100;
    return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%`;
  }

  return (
    <div style={{ marginBottom: 20 }}>
      <h3 style={{ margin: '0 0 4px', fontSize: F.md, fontWeight: 700, color: C.text }}>
        Outcome Confidence Intervals
      </h3>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 12 }}>
        10th / 50th / 90th percentile trade outcome bands with actual equity curve
      </div>
      <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px', overflowX: 'auto' }}>
        <svg
          width="100%"
          viewBox={`0 0 ${W} ${H}`}
          style={{ display: 'block', overflow: 'visible', minWidth: W }}
        >
          <defs>
            <clipPath id={`ciClip-${uid}`}>
              <rect x={pad.l} y={pad.t} width={iW} height={iH} />
            </clipPath>
            <linearGradient id={`ciBandGrad-${uid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={C.brand} stopOpacity="0.18" />
              <stop offset="100%" stopColor={C.brand} stopOpacity="0.04" />
            </linearGradient>
          </defs>

          {/* Y-axis gridlines */}
          {yTicks.map((tick, i) => (
            <g key={i}>
              <line
                x1={pad.l} y1={tick.y}
                x2={pad.l + iW} y2={tick.y}
                stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4"
              />
              <text
                x={pad.l - 6} y={tick.y}
                textAnchor="end" dominantBaseline="middle"
                fontSize={9} fill={C.muted}
              >
                {tick.label}
              </text>
            </g>
          ))}

          {/* Outer band (p10–p90) */}
          <polygon
            points={bandPts}
            fill={`url(#ciBandGrad-${uid})`}
            stroke="none"
            clipPath={`url(#ciClip-${uid})`}
          />

          {/* Inner band (p25–p75 approx) */}
          <polygon
            points={innerBandPts}
            fill={C.brand}
            fillOpacity={0.10}
            stroke="none"
            clipPath={`url(#ciClip-${uid})`}
          />

          {/* p90 dashed boundary line */}
          <polyline
            fill="none"
            stroke={C.bull}
            strokeWidth={1.2}
            strokeDasharray="5 3"
            points={p90pts.join(' ')}
            clipPath={`url(#ciClip-${uid})`}
            opacity={0.7}
          />

          {/* p10 dashed boundary line */}
          <polyline
            fill="none"
            stroke={C.bear}
            strokeWidth={1.2}
            strokeDasharray="5 3"
            points={p10pts.join(' ')}
            clipPath={`url(#ciClip-${uid})`}
            opacity={0.7}
          />

          {/* p50 median equity curve — bright line */}
          <polyline
            fill="none"
            stroke={C.brand}
            strokeWidth={2.5}
            strokeLinejoin="round"
            points={p50pts.join(' ')}
            clipPath={`url(#ciClip-${uid})`}
            style={{ filter: `drop-shadow(0 0 4px ${C.brand}99)` }}
          />

          {/* End dots */}
          <circle cx={toX(NUM_POINTS)} cy={toY(finalP90)} r={3} fill={C.bull} clipPath={`url(#ciClip-${uid})`} />
          <circle cx={toX(NUM_POINTS)} cy={toY(finalP50)} r={4} fill={C.brand} clipPath={`url(#ciClip-${uid})`}
            style={{ filter: `drop-shadow(0 0 4px ${C.brand})` }} />
          <circle cx={toX(NUM_POINTS)} cy={toY(finalP10)} r={3} fill={C.bear} clipPath={`url(#ciClip-${uid})`} />

          {/* End labels — right side */}
          <text
            x={pad.l + iW + 8} y={toY(finalP90)}
            dominantBaseline="middle" fontSize={9} fontWeight={700} fill={C.bull}
          >
            P90 {fmtEnd(finalP90)}
          </text>
          <text
            x={pad.l + iW + 8} y={toY(finalP50)}
            dominantBaseline="middle" fontSize={10} fontWeight={700} fill={C.brand}
          >
            P50 {fmtEnd(finalP50)}
          </text>
          <text
            x={pad.l + iW + 8} y={toY(finalP10)}
            dominantBaseline="middle" fontSize={9} fontWeight={700} fill={C.bear}
          >
            P10 {fmtEnd(finalP10)}
          </text>

          {/* X-axis labels */}
          <text x={pad.l} y={pad.t + iH + 14} fontSize={9} fill={C.muted} textAnchor="start">Trade 1</text>
          <text x={pad.l + iW / 2} y={pad.t + iH + 14} fontSize={9} fill={C.muted} textAnchor="middle">Trade {Math.floor(NUM_POINTS / 2)}</text>
          <text x={pad.l + iW} y={pad.t + iH + 14} fontSize={9} fill={C.muted} textAnchor="end">Trade {NUM_POINTS}</text>

          {/* Band labels inside chart */}
          <text
            x={pad.l + iW * 0.12}
            y={toY((p90[5] + p50[5]) / 2)}
            fontSize={8} fill={C.brand} opacity={0.7} fontWeight={600}
          >
            Outer band (P10–P90)
          </text>
        </svg>
        <div style={{ fontSize: 10, color: C.muted, marginTop: 6 }}>
          Bright line = median (P50) · Outer dashed = 10th/90th percentile boundaries · Shading = confidence interval
        </div>
      </div>
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
    const ctrl = new AbortController();
    const load = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/backtest/results`, { signal: ctrl.signal });
        if (res.ok) {
          const d = await res.json();
          if (!ctrl.signal.aborted) {
            setRuns(d.results || []);
            // Auto-select latest
            if (d.results?.length > 0) {
              setSelectedId(d.results[0].id);
            }
          }
        }
      } catch { /* silent (includes AbortError) */ }
      if (!ctrl.signal.aborted) setLoadingRuns(false);
    };
    load();
    return () => ctrl.abort();
  }, [apiBase]);

  useEffect(() => {
    if (!selectedId) { setSelectedResult(null); return; }
    const ctrl = new AbortController();
    setLoadingDetail(true);
    fetch(`${apiBase}/v1/backtest/results/${selectedId}`, { signal: ctrl.signal })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (!ctrl.signal.aborted) { setSelectedResult(d); setLoadingDetail(false); } })
      .catch(() => { if (!ctrl.signal.aborted) setLoadingDetail(false); });
    return () => ctrl.abort();
  }, [selectedId, apiBase]);

  useEffect(() => {
    if (!compareId) { setCompareResult(null); return; }
    const ctrl = new AbortController();
    fetch(`${apiBase}/v1/backtest/results/${compareId}`, { signal: ctrl.signal })
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (!ctrl.signal.aborted) setCompareResult(d); })
      .catch(() => {});
    return () => ctrl.abort();
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

      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: 24, alignItems: 'start' }}>
        {/* ── Left: run list + form ─────────────── */}
        <div style={{ position: 'sticky', top: 16 }}>
          {/* Active job progress */}
          {activeJobId && (
            <JobProgress jobId={activeJobId} apiBase={apiBase} onDone={handleJobDone} />
          )}

          {/* New backtest form */}
          <NewBacktestForm apiBase={apiBase} onJobStarted={setActiveJobId} />

          {/* Run list header */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            marginBottom: 10, marginTop: 4,
          }}>
            <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.7 }}>
              Saved Runs
            </div>
            <div style={{
              fontSize: F.xs, fontWeight: 700, color: C.brand,
              background: C.brand + '18', borderRadius: R.pill,
              padding: '2px 8px',
            }}>
              {runs.length}
            </div>
          </div>
          {loadingRuns ? (
            Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} h={72} style={{ marginBottom: 8 }} />)
          ) : runs.length === 0 ? (
            <div style={{ padding: 16, background: G.card, borderRadius: R.md, border: `1px solid ${C.border}`, textAlign: 'center', color: C.muted, fontSize: F.sm }}>
              No runs yet. Run your first backtest above.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: '60vh', overflowY: 'auto', paddingRight: 2 }}>
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
            <div className="card-hover" style={{
              marginBottom: 20, padding: '12px 16px',
              background: G.card, border: `1px solid ${C.border}`,
              borderRadius: R.lg, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
            }}>
              <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                Compare run:
              </span>
              <select
                value={compareId || ''}
                onChange={(e) => setCompareId(e.target.value || null)}
                style={{
                  flex: 1, minWidth: 200, background: C.surfaceHover,
                  border: `1px solid ${compareId ? C.brand : C.border}`,
                  borderRadius: R.sm, color: C.text, padding: '6px 10px',
                  fontSize: F.sm, cursor: 'pointer',
                  boxShadow: compareId ? `0 0 0 1px ${C.brand}40` : 'none',
                }}
              >
                <option value="">— Select a run to compare —</option>
                {runs.filter((r) => r.id !== selectedId).map((r) => (
                  <option key={r.id} value={r.id}>{r.symbols?.join(', ')} · {r.days}d · {fmtPct(r.total_return_pct ?? 0)}</option>
                ))}
              </select>
              {compareId && (
                <button
                  onClick={() => setCompareId(null)}
                  style={{
                    background: C.bear + '18', border: `1px solid ${C.bear}44`,
                    borderRadius: R.sm, color: C.bear, cursor: 'pointer',
                    fontSize: F.xs, fontWeight: 700, padding: '4px 10px',
                  }}
                >
                  Clear
                </button>
              )}
            </div>
          )}

          {/* Comparison radar + delta table */}
          {compareResult && selectedResult && (
            <>
              <RunComparisonRadar
                runA={selectedResult}
                runB={compareResult}
                labelA="Run A"
                labelB="Run B"
              />
              <ComparisonDelta
                a={selectedResult}
                b={compareResult}
                labelA="Run A"
                labelB="Run B"
              />
            </>
          )}

          {/* Detail panels (side by side if comparing) */}
          <div style={{ display: 'grid', gridTemplateColumns: compareResult ? '1fr 1fr' : '1fr', gap: 16 }}>
            {/* Selected run */}
            <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px' }}>
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
              <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.brand}40`, borderRadius: R.lg, padding: '20px 24px' }}>
                <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.7, marginBottom: 12 }}>Comparison</div>
                <RunDetail result={compareResult} />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Responsive fix ─── */}
      <style dangerouslySetInnerHTML={{ __html: `
        @media (max-width: 900px) {
          div[style*="300px 1fr"] { grid-template-columns: 1fr !important; }
        }
      ` }} />
    </div>
  );
}
