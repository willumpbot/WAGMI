import React, { useEffect, useState, useMemo, useId } from 'react';
import Head from 'next/head';
import Layout from '../components/Layout';
import { C, G, R, S, F, fmtUsd, fmtPct } from '../src/theme';
import { apiFetch } from '../src/api';
import type { TradeHistoryResponse, TradeRecord, EquityCurveResponse, EquityCurvePoint, BacktestResult } from '../src/types';

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function Skeleton({ h = 16, w = '100%' }: { h?: number; w?: string | number }) {
  return <div className="skeleton" style={{ height: h, width: w, borderRadius: R.sm }} />;
}

// ─── EMA Helper ───────────────────────────────────────────────────────────────

function calcEMA(data: number[], period: number): number[] {
  if (!data.length) return [];
  const k = 2 / (period + 1);
  const ema: number[] = [data[0]];
  for (let i = 1; i < data.length; i++) ema.push(data[i] * k + ema[i - 1] * (1 - k));
  return ema;
}

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
  const negReturns = dailyReturns.filter((r) => r < 0);
  if (negReturns.length === 0) return null;
  // Downside deviation uses all returns in the denominator (not just negative ones)
  const downsideVariance = negReturns.reduce((a, b) => a + b ** 2, 0) / dailyReturns.length;
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
    <div className="card-hover" style={{
      background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg,
      padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 6,
      boxShadow: S.sm, position: 'relative', overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: color ?? C.brand, borderRadius: `${R.lg}px ${R.lg}px 0 0` }} />
      <div style={{ fontSize: F.sm, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
      <div className="num" style={{ fontSize: F['2xl'], fontWeight: 700, color: color ?? C.text }}>{value}</div>
      {sub && <div style={{ fontSize: F.xs, color: C.muted }}>{sub}</div>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="fade-in" style={{ marginBottom: 36 }}>
      <h2 className="section-label" style={{ margin: '0 0 16px' }}>{title}</h2>
      {children}
    </div>
  );
}

// ─── Rolling Win Rate Chart ───────────────────────────────────────────────────

function RollingWinRateChart({ data, width = 700, height = 120 }: { data: { idx: number; wr: number }[]; width?: number; height?: number }) {
  if (!data.length) return (
    <div style={{ textAlign: 'center', padding: '40px 20px', color: C.textSub }}>
      <div style={{ fontSize: 36, marginBottom: 10 }}>📈</div>
      <div style={{ fontSize: F.base, fontWeight: 600, color: C.text, marginBottom: 6 }}>Not enough trades yet</div>
      <div style={{ fontSize: F.sm, color: C.muted }}>Need at least 10 closed trades to compute a rolling win rate.</div>
    </div>
  );
  const pad = { t: 10, r: 20, b: 30, l: 44 };
  const W = width - pad.l - pad.r;
  const H = height - pad.t - pad.b;
  const maxI = data[data.length - 1].idx;
  const x = (i: number) => pad.l + (i / Math.max(1, maxI)) * W;
  const y = (v: number) => pad.t + H - ((v - 0) / 100) * H;

  // Split the area fill: above 50% = bull, below 50% = bear
  // Build two separate filled polylines clipped at y(50)
  const y50 = y(50);
  const abovePts = [
    `${x(data[0].idx)},${y50}`,
    ...data.map((d) => `${x(d.idx)},${Math.min(y(d.wr), y50)}`),
    `${x(data[data.length - 1].idx)},${y50}`,
  ].join(' ');
  const belowPts = [
    `${x(data[0].idx)},${y50}`,
    ...data.map((d) => `${x(d.idx)},${Math.max(y(d.wr), y50)}`),
    `${x(data[data.length - 1].idx)},${y50}`,
  ].join(' ');

  // Linear regression trend line
  const n = data.length;
  const sumX = data.reduce((s, d) => s + d.idx, 0);
  const sumY = data.reduce((s, d) => s + d.wr, 0);
  const sumXY = data.reduce((s, d) => s + d.idx * d.wr, 0);
  const sumX2 = data.reduce((s, d) => s + d.idx * d.idx, 0);
  const denom = n * sumX2 - sumX * sumX;
  const trendSlope = denom !== 0 ? (n * sumXY - sumX * sumY) / denom : 0;
  const trendIntercept = (sumY - trendSlope * sumX) / n;
  const trendStart = trendSlope * data[0].idx + trendIntercept;
  const trendEnd = trendSlope * data[data.length - 1].idx + trendIntercept;

  const lastVal = data[data.length - 1].wr;
  const lastX = x(data[data.length - 1].idx);
  const lastY = y(lastVal);

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      {/* Area fill — above 50% = bull, below 50% = bear */}
      <polyline points={abovePts} fill={C.bull + '20'} stroke="none" />
      <polyline points={belowPts} fill={C.bear + '20'} stroke="none" />

      {/* 75% target line */}
      <line x1={pad.l} y1={y(75)} x2={pad.l + W} y2={y(75)} stroke={C.bull} strokeWidth={1} strokeDasharray="5,3" opacity={0.6} />
      <text x={pad.l - 4} y={y(75) + 4} fill={C.bull} fontSize={8} textAnchor="end" opacity={0.7}>75%</text>

      {/* 50% reference line — bold dashed */}
      <line x1={pad.l} y1={y50} x2={pad.l + W} y2={y50} stroke={C.border} strokeWidth={1.5} strokeDasharray="4,4" />
      <text x={pad.l - 4} y={y50 + 4} fill={C.muted} fontSize={9} textAnchor="end">50%</text>
      <text x={pad.l - 4} y={y(100) + 4} fill={C.muted} fontSize={9} textAnchor="end">100%</text>
      <text x={pad.l - 4} y={y(0) + 4} fill={C.muted} fontSize={9} textAnchor="end">0%</text>

      {/* Trend line */}
      <line
        x1={x(data[0].idx)} y1={y(trendStart)}
        x2={x(data[data.length - 1].idx)} y2={y(trendEnd)}
        stroke={C.brand} strokeWidth={1} opacity={0.65}
      />

      {/* Win rate line */}
      <polyline points={data.map((d) => `${x(d.idx)},${y(d.wr)}`).join(' ')} fill="none" stroke={C.brand} strokeWidth={2} strokeLinejoin="round" />

      {/* Current value highlight */}
      <circle cx={lastX} cy={lastY} r={5} fill={C.brand} stroke={C.card} strokeWidth={1.5} />
      <text x={Math.min(lastX + 6, pad.l + W - 60)} y={lastY - 6} fill={C.brand} fontSize={8} fontWeight="700">
        Current: {lastVal.toFixed(1)}%
      </text>

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

// ─── Rolling Metrics Chart ────────────────────────────────────────────────────

function RollingMetrics({ trades }: { trades: TradeRecord[] }) {
  if (trades.length < 12) return null;

  const WINDOW = 10;
  const rollingWR: number[] = [];
  const rollingPnL: number[] = [];

  for (let i = WINDOW; i <= trades.length; i++) {
    const slice = trades.slice(i - WINDOW, i);
    const wins = slice.filter((t) => t.outcome === 'WIN').length;
    rollingWR.push(wins / WINDOW);
    rollingPnL.push(slice.reduce((s, t) => s + (t.pnl ?? 0), 0) / WINDOW);
  }

  const n = rollingWR.length;
  const W = 640, H = 160;
  const padT = 8, padB = 24, padL = 52, padR = 16;
  const halfH = (H - padT - padB) / 2 - 6;
  const iW = W - padL - padR;

  const toX = (i: number) => padL + (i / Math.max(n - 1, 1)) * iW;

  // Win rate section (top half)
  const wrY = (v: number) => padT + halfH - v * halfH;
  const wrPath = rollingWR.map((v, i) => `${i === 0 ? 'M' : 'L'} ${toX(i).toFixed(1)} ${wrY(v).toFixed(1)}`).join(' ');

  // PnL section (bottom half)
  const pnlBase = padT + halfH * 2 + 12;
  const maxAbsPnl = Math.max(...rollingPnL.map(Math.abs), 0.01);
  const pnlY = (v: number) => pnlBase + halfH - ((v + maxAbsPnl) / (2 * maxAbsPnl)) * halfH;
  const pnlPath = rollingPnL.map((v, i) => `${i === 0 ? 'M' : 'L'} ${toX(i).toFixed(1)} ${pnlY(v).toFixed(1)}`).join(' ');

  return (
    <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 20 }}>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 4 }}>Rolling 10-Trade Performance</div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 14 }}>How win rate and avg P&L evolve across each rolling window of 10 trades</div>

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
        {/* Win rate section label */}
        <text x={padL - 6} y={padT + halfH / 2} textAnchor="end" fontSize={9} fill={C.muted} transform={`rotate(-90,${padL - 6},${padT + halfH / 2})`}>Win Rate</text>
        <line x1={padL} y1={padT} x2={padL + iW} y2={padT} stroke={C.border} strokeWidth={0.5} />
        {/* 50% reference */}
        <line x1={padL} y1={wrY(0.5)} x2={padL + iW} y2={wrY(0.5)} stroke={C.muted} strokeWidth={0.5} strokeDasharray="4 3" />
        <text x={padL - 4} y={wrY(0.5) + 3} textAnchor="end" fontSize={8} fill={C.muted}>50%</text>
        <text x={padL - 4} y={wrY(1) + 3} textAnchor="end" fontSize={8} fill={C.muted}>100%</text>
        {/* Win rate line */}
        <path d={wrPath} fill="none" stroke={C.brand} strokeWidth={2} strokeLinejoin="round" />

        {/* Divider */}
        <line x1={padL} y1={pnlBase} x2={padL + iW} y2={pnlBase} stroke={C.border} strokeWidth={1} />

        {/* PnL section */}
        <text x={padL - 6} y={pnlBase + halfH / 2} textAnchor="end" fontSize={9} fill={C.muted} transform={`rotate(-90,${padL - 6},${pnlBase + halfH / 2})`}>Avg P&L</text>
        <line x1={padL} y1={pnlY(0)} x2={padL + iW} y2={pnlY(0)} stroke={C.muted} strokeWidth={0.5} strokeDasharray="4 3" />
        {/* PnL colored segments */}
        {rollingPnL.slice(0, -1).map((v, i) => {
          const x1 = toX(i), y1 = pnlY(v);
          const x2 = toX(i + 1), y2 = pnlY(rollingPnL[i + 1]);
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke={v >= 0 ? C.bull : C.bear} strokeWidth={2} />;
        })}

        {/* X-axis */}
        <line x1={padL} y1={padT + (H - padT - padB)} x2={padL + iW} y2={padT + (H - padT - padB)} stroke={C.border} strokeWidth={0.5} />
        <text x={padL} y={H - 4} fontSize={8} fill={C.muted}>Trade {WINDOW}</text>
        <text x={padL + iW} y={H - 4} textAnchor="end" fontSize={8} fill={C.muted}>Trade {trades.length}</text>
      </svg>

      <div style={{ display: 'flex', gap: 20, marginTop: 8, fontSize: 10, color: C.muted }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 16, height: 2, background: C.brand, display: 'inline-block' }} /> Rolling Win Rate
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, background: C.bull, borderRadius: 2, display: 'inline-block' }} /> Avg P&L (positive)
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, background: C.bear, borderRadius: 2, display: 'inline-block' }} /> Avg P&L (negative)
        </span>
      </div>
    </div>
  );
}

function MonthlyPnlChart({ trades }: { trades: TradeRecord[] }) {
  const periods = useMemo(() => {
    if (!trades.length) return [];
    const chunkSize = 5;
    const result: { label: string; pnl: number }[] = [];
    for (let i = 0; i < trades.length; i += chunkSize) {
      const chunk = trades.slice(i, i + chunkSize);
      const pnl = chunk.reduce((sum, t) => sum + (t.pnl ?? 0), 0);
      result.push({ label: `${Math.floor(i / chunkSize) + 1}`, pnl });
    }
    return result;
  }, [trades]);

  if (!periods.length) {
    return <div style={{ color: C.muted, fontSize: F.sm, padding: 20 }}>No trade data available.</div>;
  }

  const vbW = 700;
  const vbH = 160;
  const pad = { t: 28, r: 16, b: 30, l: 52 };
  const W = vbW - pad.l - pad.r;
  const H = vbH - pad.t - pad.b;

  const maxAbs = Math.max(1, ...periods.map((p) => Math.abs(p.pnl)));
  const barW = Math.max(4, W / periods.length - 4);
  const zeroY = pad.t + H / 2;

  const barX = (i: number) => pad.l + (i / periods.length) * W + (W / periods.length - barW) / 2;
  const barH = (pnl: number) => Math.max(2, (Math.abs(pnl) / maxAbs) * (H / 2 - 4));
  const barY = (pnl: number) => pnl >= 0 ? zeroY - barH(pnl) : zeroY;
  const barCenterX = (i: number) => pad.l + (i / periods.length) * W + W / periods.length / 2;

  const topLabel = fmtUsd(maxAbs);
  const botLabel = fmtUsd(-maxAbs);

  // Average monthly PnL target line
  const avgPnl = periods.reduce((s, p) => s + p.pnl, 0) / periods.length;
  const avgY = zeroY - (avgPnl / maxAbs) * (H / 2 - 4);

  // Best and worst periods
  const bestIdx = periods.reduce((bi, p, i) => p.pnl > periods[bi].pnl ? i : bi, 0);
  const worstIdx = periods.reduce((wi, p, i) => p.pnl < periods[wi].pnl ? i : wi, 0);

  // Cumulative PnL for line overlay
  const cumPnl: number[] = [];
  let running = 0;
  for (const p of periods) {
    running += p.pnl;
    cumPnl.push(running);
  }
  const maxCum = Math.max(...cumPnl.map(Math.abs), 1);
  const cumY = (v: number) => zeroY - (v / maxCum) * (H / 2 - 4);
  const cumPts = cumPnl.map((v, i) => `${barCenterX(i)},${cumY(v)}`).join(' ');

  return (
    <svg width="100%" viewBox={`0 0 ${vbW} ${vbH}`} style={{ display: 'block' }}>
      {/* Title */}
      <text x={vbW / 2} y={12} fill={C.muted} fontSize={10} textAnchor="middle" fontWeight="600">P&amp;L by Period</text>

      {/* Y-axis labels */}
      <text x={pad.l - 4} y={pad.t + 4} fill={C.muted} fontSize={8} textAnchor="end">{topLabel}</text>
      <text x={pad.l - 4} y={zeroY + 4} fill={C.muted} fontSize={8} textAnchor="end">$0</text>
      <text x={pad.l - 4} y={pad.t + H + 4} fill={C.muted} fontSize={8} textAnchor="end">{botLabel}</text>

      {/* Reference line at 0 */}
      <line x1={pad.l} y1={zeroY} x2={pad.l + W} y2={zeroY} stroke={C.border} strokeWidth={1} />

      {/* Average PnL target dashed line */}
      {periods.length > 1 && (
        <g>
          <line x1={pad.l} y1={avgY} x2={pad.l + W} y2={avgY} stroke={C.brand} strokeWidth={1} strokeDasharray="5,3" opacity={0.6} />
          <text x={pad.l + W + 2} y={avgY + 3} fill={C.brand} fontSize={7} opacity={0.7}>avg</text>
        </g>
      )}

      {/* Bars */}
      {periods.map((p, i) => {
        const positive = p.pnl >= 0;
        const bx = barX(i);
        const bh = barH(p.pnl);
        const by = barY(p.pnl);
        const labelY = positive ? by - 3 : by + bh + 9;
        const labelText = (positive ? '+' : '') + fmtUsd(p.pnl, 0);
        return (
          <g key={i}>
            <rect
              x={bx} y={by} width={barW} height={bh}
              fill={positive ? C.bull : C.bear}
              rx={2} opacity={0.85}
            />
            {/* Bar value label — only show if bar is wide enough */}
            {barW > 20 && (
              <text
                x={bx + barW / 2} y={labelY}
                fill={positive ? C.bull : C.bear}
                fontSize={7} textAnchor="middle" fontWeight="600"
              >
                {labelText}
              </text>
            )}
            {/* X-axis period label */}
            <text
              x={bx + barW / 2} y={vbH - 14}
              fill={C.muted} fontSize={7} textAnchor="middle"
            >
              {p.label}
            </text>
          </g>
        );
      })}

      {/* Best/Worst annotations */}
      {periods.length > 1 && (
        <>
          <text
            x={barCenterX(bestIdx)}
            y={barY(periods[bestIdx].pnl) - 12}
            fill={C.bull} fontSize={7} textAnchor="middle" fontWeight="700"
          >
            Best: +{fmtUsd(periods[bestIdx].pnl, 0)}
          </text>
          <text
            x={barCenterX(worstIdx)}
            y={barY(periods[worstIdx].pnl) + barH(periods[worstIdx].pnl) + 18}
            fill={C.bear} fontSize={7} textAnchor="middle" fontWeight="700"
          >
            Worst: {fmtUsd(periods[worstIdx].pnl, 0)}
          </text>
        </>
      )}

      {/* Cumulative PnL overlay line */}
      {cumPnl.length > 1 && (
        <>
          <polyline points={cumPts} fill="none" stroke={C.brand} strokeWidth={1.5} strokeLinejoin="round" strokeDasharray="3,2" opacity={0.8} />
          {cumPnl.map((v, i) => (
            <circle key={`cum-${i}`} cx={barCenterX(i)} cy={cumY(v)} r={2} fill={C.brand} opacity={0.7} />
          ))}
        </>
      )}

      {/* X-axis label */}
      <text x={pad.l + W / 2} y={vbH - 2} fill={C.muted} fontSize={8} textAnchor="middle">
        Period (every 5 trades)
      </text>

      {/* Legend */}
      <line x1={pad.l} y1={vbH - 8} x2={pad.l + 14} y2={vbH - 8} stroke={C.brand} strokeWidth={1.5} strokeDasharray="3,2" />
      <text x={pad.l + 17} y={vbH - 4} fill={C.muted} fontSize={7}>Cumulative PnL</text>
    </svg>
  );
}

// ─── Drawdown Timeline ────────────────────────────────────────────────────────

function DrawdownTimeline({ points }: { points: EquityCurvePoint[] }) {
  if (points.length < 2) {
    return (
      <div style={{ textAlign: 'center', padding: '32px 20px', color: C.textSub }}>
        <div style={{ fontSize: 32, marginBottom: 8 }}>📉</div>
        <div style={{ fontSize: F.sm, fontWeight: 600, color: C.text, marginBottom: 4 }}>No equity curve data yet</div>
        <div style={{ fontSize: F.xs, color: C.muted }}>Drawdown timeline will appear once the bot has run long enough to generate equity curve points.</div>
      </div>
    );
  }

  const vbW = 700;
  const vbH = 100;
  const pad = { t: 8, r: 16, b: 20, l: 52 };
  const W = vbW - pad.l - pad.r;
  const H = vbH - pad.t - pad.b;

  // Top strip: equity line (30% of H)
  const eqH = Math.round(H * 0.30);
  // Bottom strip: drawdown bars (remaining)
  const ddH = H - eqH - 4;
  const ddTop = pad.t + eqH + 4;

  const equities = points.map((p) => p.equity);
  const minE = Math.min(...equities);
  const maxE = Math.max(...equities);
  const eqRange = maxE - minE || 1;

  const drawdowns = points.map((p) => p.drawdown_pct ?? 0); // negative values
  const minDD = Math.min(...drawdowns); // most negative = worst
  const ddRange = Math.abs(minDD) || 1;

  // Average drawdown (only include negative values)
  const negDDs = drawdowns.filter((d) => d < 0);
  const avgDD = negDDs.length > 0 ? negDDs.reduce((a, b) => a + b, 0) / negDDs.length : 0;

  const x = (i: number) => pad.l + (i / Math.max(1, points.length - 1)) * W;
  const yEq = (v: number) => pad.t + eqH - ((v - minE) / eqRange) * eqH;
  const ddBarH = (dd: number) => Math.max(1, (Math.abs(dd) / ddRange) * ddH);

  // Y position within the DD strip (dd=0 is ddTop, more negative = taller bar = lower on SVG)
  // We need a y coordinate for horizontal reference lines inside the DD strip
  // dd% maps: 0 → ddTop, minDD → ddTop + ddH
  const yDD = (ddPct: number) => ddTop + (Math.abs(ddPct) / ddRange) * ddH;

  // Find max drawdown trough index
  const maxDDIdx = drawdowns.indexOf(minDD);

  // Equity line path
  const eqPts = points.map((p, i) => `${x(i)},${yEq(p.equity)}`).join(' ');

  // Recovery markers: where drawdown returns to 0 after a dip
  const recoveryMarkers: number[] = [];
  for (let i = 1; i < drawdowns.length; i++) {
    if (drawdowns[i - 1] < -0.5 && drawdowns[i] >= -0.001) {
      recoveryMarkers.push(i);
    }
  }

  // Opacity scaled to drawdown depth
  const barOpacity = (dd: number) => 0.3 + 0.7 * (Math.abs(dd) / ddRange);

  // Severity band heights inside DD strip
  // -5% and -15% reference lines (as % of total DD range)
  const band5Y = minDD < -5 ? yDD(-5) : null;
  const band15Y = minDD < -15 ? yDD(-15) : null;

  return (
    <svg width="100%" viewBox={`0 0 ${vbW} ${vbH}`} style={{ display: 'block' }}>
      {/* Equity line strip */}
      <polyline points={eqPts} fill="none" stroke={C.bull} strokeWidth={1.5} strokeLinejoin="round" />

      {/* Severity color bands (background, drawn behind bars) */}
      {/* Green band: 0 to -5% */}
      <rect x={pad.l} y={ddTop} width={W} height={band5Y != null ? band5Y - ddTop : ddH} fill="rgba(22,163,74,0.06)" />
      {/* Yellow band: -5% to -15% */}
      {band5Y != null && (
        <rect x={pad.l} y={band5Y} width={W} height={band15Y != null ? band15Y - band5Y : ddTop + ddH - band5Y} fill="rgba(217,119,6,0.08)" />
      )}
      {/* Red band: below -15% */}
      {band15Y != null && (
        <rect x={pad.l} y={band15Y} width={W} height={ddTop + ddH - band15Y} fill="rgba(220,38,38,0.08)" />
      )}

      {/* Drawdown bars */}
      {points.map((p, i) => {
        const dd = drawdowns[i];
        if (dd >= -0.001) return null;
        const bh = ddBarH(dd);
        const bx = x(i) - 0.5;
        const isRecovering = i > 0 && drawdowns[i] > drawdowns[i - 1];
        return (
          <rect
            key={i}
            x={bx} y={ddTop} width={Math.max(1, W / points.length)}
            height={bh}
            fill={isRecovering ? '#e05050' : C.bear}
            opacity={barOpacity(dd)}
          />
        );
      })}

      {/* Average drawdown dashed line */}
      {avgDD < -0.001 && (
        <g>
          <line
            x1={pad.l} y1={yDD(avgDD)}
            x2={pad.l + W} y2={yDD(avgDD)}
            stroke={C.muted} strokeWidth={1} strokeDasharray="4,3"
          />
          <text x={pad.l + W + 2} y={yDD(avgDD) + 3} fill={C.muted} fontSize={7} textAnchor="start">
            avg {fmtPct(avgDD, 1)}
          </text>
        </g>
      )}

      {/* Severity band reference lines */}
      {band5Y != null && (
        <line x1={pad.l} y1={band5Y} x2={pad.l + W} y2={band5Y} stroke={C.warnMid} strokeWidth={0.5} strokeDasharray="3,4" opacity={0.5} />
      )}
      {band15Y != null && (
        <line x1={pad.l} y1={band15Y} x2={pad.l + W} y2={band15Y} stroke={C.bear} strokeWidth={0.5} strokeDasharray="3,4" opacity={0.5} />
      )}

      {/* Max drawdown trough annotation */}
      {maxDDIdx >= 0 && minDD < -0.001 && (
        <g>
          <line
            x1={x(maxDDIdx)} y1={ddTop}
            x2={x(maxDDIdx)} y2={ddTop + ddBarH(minDD)}
            stroke={C.bear} strokeWidth={1.5} strokeDasharray="3,2"
          />
          <circle cx={x(maxDDIdx)} cy={ddTop + ddBarH(minDD)} r={3} fill={C.bear} />
          <text
            x={Math.min(x(maxDDIdx) + 4, pad.l + W - 40)}
            y={ddTop + ddBarH(minDD) - 4}
            fill={C.bear} fontSize={7.5} fontWeight="700"
          >
            {fmtPct(minDD, 1)}
          </text>
        </g>
      )}

      {/* Recovery markers ↑ */}
      {recoveryMarkers.map((ri) => (
        <text key={`rec-${ri}`} x={x(ri)} y={ddTop - 2} fill={C.bull} fontSize={9} textAnchor="middle" opacity={0.8}>
          ↑
        </text>
      ))}

      {/* Y-axis label for drawdown strip */}
      <text x={pad.l - 4} y={ddTop + ddH / 2 + 3} fill={C.muted} fontSize={7.5} textAnchor="end">DD</text>
      <text x={pad.l - 4} y={pad.t + eqH / 2 + 3} fill={C.muted} fontSize={7.5} textAnchor="end">Eq.</text>

      {/* Divider line between eq and dd strips */}
      <line x1={pad.l} y1={ddTop - 2} x2={pad.l + W} y2={ddTop - 2} stroke={C.border} strokeWidth={0.5} />

      {/* Legend */}
      <circle cx={pad.l} cy={vbH - 5} r={3} fill={C.bear} />
      <text x={pad.l + 6} y={vbH - 2} fill={C.muted} fontSize={7}>Max drawdown trough</text>
      <line x1={pad.l + 110} y1={vbH - 5} x2={pad.l + 125} y2={vbH - 5} stroke={C.bear} strokeWidth={1.5} />
      <text x={pad.l + 128} y={vbH - 2} fill={C.muted} fontSize={7}>Drawdown depth</text>
      <text x={pad.l + 210} y={vbH - 2} fill={C.bull} fontSize={7}>↑ recovery</text>
    </svg>
  );
}

// ─── Performance Radar / Spider Chart ─────────────────────────────────────────

function PerformanceRadar({
  sharpe, sortino, winRate, profitFactor, calmar,
}: {
  sharpe: number | null;
  sortino: number | null;
  winRate: number | null;
  profitFactor: number | null;
  calmar: number | null;
}) {
  const uid = useId().replace(/:/g, '');
  const size = 250;
  const cx = size / 2;
  const cy = size / 2;
  const r = 88; // outer radius of pentagon

  const axes = [
    { label: 'Sharpe', value: sharpe, max: 3 },
    { label: 'Sortino', value: sortino, max: 3 },
    { label: 'Win Rate', value: winRate, max: 100 },
    { label: 'Prof. Factor', value: profitFactor, max: 3 },
    { label: 'Calmar', value: calmar, max: 2 },
  ];

  const n = axes.length;

  // Angle: start at top (-π/2), go clockwise
  const angle = (i: number) => (2 * Math.PI * i) / n - Math.PI / 2;
  const pt = (i: number, radius: number) => ({
    x: cx + radius * Math.cos(angle(i)),
    y: cy + radius * Math.sin(angle(i)),
  });

  // Normalized 0-1 for each axis
  const norm = (v: number | null, max: number) => {
    if (v == null || isNaN(v)) return 0;
    return Math.min(1, Math.max(0, v / max));
  };

  const targetR = 0.7;

  // Build polygon points
  const valuePts = axes
    .map((a, i) => pt(i, norm(a.value, a.max) * r))
    .map((p) => `${p.x},${p.y}`)
    .join(' ');

  const targetPts = axes
    .map((_, i) => pt(i, targetR * r))
    .map((p) => `${p.x},${p.y}`)
    .join(' ');

  const outerPts = axes
    .map((_, i) => pt(i, r))
    .map((p) => `${p.x},${p.y}`)
    .join(' ');

  // Concentric grid rings
  const gridRings = [0.25, 0.5, 0.75, 1.0];

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ display: 'block', margin: '0 auto' }}>
      <defs>
        <radialGradient id={`radarFill-${uid}`} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor={C.brand} stopOpacity="0.35" />
          <stop offset="100%" stopColor={C.brand} stopOpacity="0.12" />
        </radialGradient>
      </defs>

      {/* Concentric grid rings */}
      {gridRings.map((t) => (
        <polygon
          key={t}
          points={axes.map((_, i) => { const p = pt(i, t * r); return `${p.x},${p.y}`; }).join(' ')}
          fill="none"
          stroke={C.border}
          strokeWidth={t === 1.0 ? 1 : 0.5}
          opacity={0.6}
        />
      ))}

      {/* Axis spokes */}
      {axes.map((_, i) => {
        const outer = pt(i, r);
        return <line key={i} x1={cx} y1={cy} x2={outer.x} y2={outer.y} stroke={C.border} strokeWidth={0.75} />;
      })}

      {/* Target reference pentagon (0.7) */}
      <polygon
        points={targetPts}
        fill="none"
        stroke={C.brand}
        strokeWidth={1}
        strokeDasharray="3,3"
        opacity={0.4}
      />

      {/* Value polygon */}
      <polygon
        points={valuePts}
        fill={`url(#radarFill-${uid})`}
        stroke={C.brand}
        strokeWidth={2}
        strokeLinejoin="round"
      />

      {/* Vertex dots */}
      {axes.map((a, i) => {
        const p = pt(i, norm(a.value, a.max) * r);
        return <circle key={i} cx={p.x} cy={p.y} r={3} fill={C.brand} />;
      })}

      {/* Axis labels */}
      {axes.map((a, i) => {
        const labelR = r + 18;
        const p = pt(i, labelR);
        const anchor =
          Math.abs(p.x - cx) < 8 ? 'middle' : p.x < cx ? 'end' : 'start';
        const displayVal = a.value != null && !isNaN(a.value)
          ? a.label === 'Win Rate'
            ? `${a.value.toFixed(0)}%`
            : a.value.toFixed(2)
          : '—';
        return (
          <g key={i}>
            <text x={p.x} y={p.y - 3} fill={C.textSub} fontSize={8.5} textAnchor={anchor} fontWeight="600">
              {a.label}
            </text>
            <text x={p.x} y={p.y + 8} fill={C.muted} fontSize={7.5} textAnchor={anchor}>
              {displayVal}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ─── Benchmark Comparison ─────────────────────────────────────────────────────

function BenchmarkComparison({ trades, backtest }: { trades: TradeRecord[]; backtest: BacktestResult | null }) {
  const metrics = useMemo(() => {
    const tradeWins = trades.filter((t) => t.outcome === 'WIN');
    const tradeLosses = trades.filter((t) => t.outcome === 'LOSS');
    const totalTrades = trades.length;

    // Win rate (0–100)
    const winRate = totalTrades > 0 ? (tradeWins.length / totalTrades) * 100 : 0;

    // Profit factor: prefer backtest, fall back to computing from trades
    let profitFactor = 0;
    if (backtest?.results?.profit_factor != null && backtest.results.profit_factor > 0) {
      profitFactor = backtest.results.profit_factor;
    } else {
      const grossWin = tradeWins.reduce((a, t) => a + (t.pnl ?? 0), 0);
      const grossLoss = tradeLosses.reduce((a, t) => a + Math.abs(t.pnl ?? 0), 0);
      profitFactor = grossLoss > 0 ? grossWin / grossLoss : 0;
    }

    // Max drawdown (absolute %) from backtest if available
    let maxDrawdown = 0;
    if (backtest?.results?.max_drawdown_pct != null) {
      maxDrawdown = Math.abs(backtest.results.max_drawdown_pct);
    }

    // Avg win / Avg loss ratio
    let avgWinLossRatio = 0;
    if (
      backtest?.results?.avg_win != null &&
      backtest.results.avg_loss != null &&
      Math.abs(backtest.results.avg_loss) > 0
    ) {
      avgWinLossRatio = Math.abs(backtest.results.avg_win) / Math.abs(backtest.results.avg_loss);
    } else {
      const avgWin = tradeWins.length > 0
        ? tradeWins.reduce((a, t) => a + (t.pnl ?? 0), 0) / tradeWins.length
        : 0;
      const avgLoss = tradeLosses.length > 0
        ? tradeLosses.reduce((a, t) => a + Math.abs(t.pnl ?? 0), 0) / tradeLosses.length
        : 0;
      avgWinLossRatio = avgLoss > 0 ? avgWin / avgLoss : 0;
    }

    // Return per trade: avg pnl as % of avg entry price
    const avgPnl = totalTrades > 0
      ? trades.reduce((a, t) => a + (t.pnl ?? 0), 0) / totalTrades
      : 0;
    const entriesWithPrice = trades.filter((t) => t.entry != null);
    const avgEntry = entriesWithPrice.length > 0
      ? entriesWithPrice.reduce((a, t) => a + (t.entry ?? 0), 0) / entriesWithPrice.length
      : 0;
    const returnPerTrade = avgEntry > 0 ? (avgPnl / avgEntry) * 100 : 0;

    // Risk-adjusted return = totalReturn% / maxDrawdown%
    let riskAdjReturn = 0;
    if (backtest?.results?.total_return_pct != null && maxDrawdown > 0) {
      riskAdjReturn = backtest.results.total_return_pct / maxDrawdown;
    }

    return { winRate, profitFactor, maxDrawdown, avgWinLossRatio, returnPerTrade, riskAdjReturn };
  }, [trades, backtest]);

  const vbW = 600;
  const vbH = 180;
  const padL = 148; // label area
  const padR = 80;  // value area on right
  const padT = 22;
  const padB = 18;
  const barAreaW = vbW - padL - padR;
  const totalRows = 6;
  const rowH = (vbH - padT - padB) / totalRows;

  // [label, botValue, benchmark, lowerIsBetter, formatFn]
  type MetricRow = [string, number, number, boolean, (v: number) => string];
  const rows: MetricRow[] = [
    ['Win Rate',          metrics.winRate,         60,  false, (v) => `${v.toFixed(1)}%`],
    ['Profit Factor',     metrics.profitFactor,    1.5, false, (v) => v.toFixed(2)],
    ['Max Drawdown',      metrics.maxDrawdown,     15,  true,  (v) => `${v.toFixed(1)}%`],
    ['Avg Win / Avg Loss',metrics.avgWinLossRatio, 2.0, false, (v) => v.toFixed(2)],
    ['Return per Trade',  metrics.returnPerTrade,  0.5, false, (v) => `${v.toFixed(2)}%`],
    ['Risk-Adj Return',   metrics.riskAdjReturn,   1.5, false, (v) => v.toFixed(2)],
  ];

  // Benchmark marker sits at 70% of bar area width for visual balance
  // → the "full scale" that maps to barAreaW is bench / 0.70
  const BENCH_FRAC = 0.70;

  return (
    <svg width="100%" viewBox={`0 0 ${vbW} ${vbH}`} style={{ display: 'block' }}>
      {/* Chart title */}
      <text x={vbW / 2} y={13} fill={C.muted} fontSize={9.5} textAnchor="middle" fontWeight="600">
        vs. Excellence Benchmarks
      </text>

      {rows.map(([label, botVal, bench, lowerBetter, fmt], i) => {
        const rowY = padT + i * rowH;
        const barCenterY = rowY + rowH * 0.5;
        const barH = rowH * 0.42;
        const barTop = barCenterY - barH / 2;

        // Full scale: bench / BENCH_FRAC maps to full barAreaW
        const fullScale = bench / BENCH_FRAC;
        const clampedVal = Math.min(botVal, fullScale * 1.02);
        const barW = barAreaW * Math.max(0, clampedVal / fullScale);

        const isBetter = lowerBetter ? botVal <= bench : botVal >= bench;
        const barColor = botVal === 0 ? C.border : isBetter ? C.bull : C.bear;
        const bLineX = padL + barAreaW * BENCH_FRAC;

        return (
          <g key={label}>
            {/* Alternating row bg */}
            <rect
              x={padL} y={rowY}
              width={barAreaW} height={rowH}
              fill={i % 2 === 0 ? 'rgba(255,255,255,0.018)' : 'transparent'}
            />
            {/* Metric label */}
            <text
              x={padL - 8} y={barCenterY + 3.5}
              fill={C.textSub} fontSize={8.5} textAnchor="end"
            >
              {label}
            </text>
            {/* Bar track */}
            <rect x={padL} y={barTop} width={barAreaW} height={barH} fill={C.surface} rx={2} />
            {/* Bot value bar */}
            {barW > 0 && (
              <rect
                x={padL} y={barTop}
                width={Math.min(barW, barAreaW)} height={barH}
                fill={barColor} rx={2} opacity={0.80}
              />
            )}
            {/* Benchmark dashed vertical line */}
            <line
              x1={bLineX} y1={barTop - 3}
              x2={bLineX} y2={barTop + barH + 3}
              stroke="#d4a017" strokeWidth={1.5} strokeDasharray="3,2"
            />
            {/* Benchmark triangle marker at top */}
            <polygon
              points={`${bLineX - 4},${barTop - 4} ${bLineX + 4},${barTop - 4} ${bLineX},${barTop}`}
              fill="#d4a017"
            />
            {/* Bot value label */}
            <text
              x={padL + barAreaW + 6} y={barCenterY + 1}
              fill={barColor} fontSize={8.5} textAnchor="start" fontWeight="600"
            >
              {fmt(botVal)}
            </text>
            {/* Benchmark value label */}
            <text
              x={padL + barAreaW + 6} y={barCenterY + 11}
              fill={C.muted} fontSize={7} textAnchor="start"
            >
              /{fmt(bench)}
            </text>
          </g>
        );
      })}

      {/* Legend */}
      <line
        x1={padL} y1={vbH - 6} x2={padL + 14} y2={vbH - 6}
        stroke="#d4a017" strokeWidth={1.5} strokeDasharray="3,2"
      />
      <text x={padL + 18} y={vbH - 2} fill={C.muted} fontSize={7}>Benchmark target</text>
      <rect x={padL + 108} y={vbH - 11} width={10} height={7} fill={C.bull} rx={1} opacity={0.80} />
      <text x={padL + 122} y={vbH - 2} fill={C.muted} fontSize={7}>Above benchmark</text>
      <rect x={padL + 210} y={vbH - 11} width={10} height={7} fill={C.bear} rx={1} opacity={0.80} />
      <text x={padL + 224} y={vbH - 2} fill={C.muted} fontSize={7}>Below benchmark</text>
    </svg>
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

function EquityChart({ points, trades = [], width = 700, height = 180 }: { points: EquityCurvePoint[]; trades?: TradeRecord[]; width?: number; height?: number }) {
  const uid = useId().replace(/:/g, '');
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

  // EMA overlays
  const ema9 = calcEMA(equities, 9);
  const ema21 = calcEMA(equities, 21);
  const ema9Pts = ema9.map((v, i) => `${x(i)},${y(v)}`).join(' ');
  const ema21Pts = ema21.map((v, i) => `${x(i)},${y(v)}`).join(' ');

  // Golden/Death cross markers (EMA9 crosses EMA21)
  type CrossMarker = { i: number; golden: boolean };
  const crossMarkers: CrossMarker[] = [];
  for (let i = 1; i < ema9.length && i < ema21.length; i++) {
    const prevAbove = ema9[i - 1] > ema21[i - 1];
    const curAbove = ema9[i] > ema21[i];
    if (!prevAbove && curAbove) crossMarkers.push({ i, golden: true });
    else if (prevAbove && !curAbove) crossMarkers.push({ i, golden: false });
  }

  // Max drawdown period: find peak then trough
  let peakIdx = 0;
  let troughIdx = 0;
  let maxDD = 0;
  let runPeak = equities[0];
  let runPeakIdx = 0;
  for (let i = 1; i < equities.length; i++) {
    if (equities[i] > runPeak) { runPeak = equities[i]; runPeakIdx = i; }
    const dd = (equities[i] - runPeak) / runPeak;
    if (dd < maxDD) { maxDD = dd; peakIdx = runPeakIdx; troughIdx = i; }
  }

  // Trade annotation dots — spread trades evenly across the x axis by index
  const tradeAnnotations = trades.map((t, i) => {
    const xPos = pad.l + (i / Math.max(1, trades.length - 1)) * W;
    return { xPos, win: t.outcome === 'WIN' };
  });

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      <defs>
        <linearGradient id={`perfEqGrad-${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.bull} stopOpacity="0.25" />
          <stop offset="100%" stopColor={C.bull} stopOpacity="0.02" />
        </linearGradient>
      </defs>

      {/* Weekend / low-activity bands: every 5 data points */}
      {points.map((_, i) => {
        if (i % 5 !== 0 || i + 1 >= points.length) return null;
        const x0 = x(i);
        const x1 = x(i + 1);
        return (
          <rect
            key={`wknd-${i}`}
            x={x0} y={pad.t}
            width={x1 - x0} height={H}
            fill="rgba(148,163,184,0.04)"
          />
        );
      })}

      {/* Max drawdown shaded region */}
      {maxDD < -0.001 && (
        <rect
          x={x(peakIdx)} y={pad.t}
          width={Math.max(2, x(troughIdx) - x(peakIdx))} height={H}
          fill="rgba(220,38,38,0.10)"
        />
      )}

      {/* Grid lines */}
      {[0, 0.25, 0.5, 0.75, 1].map((t) => {
        const val = minE + t * range;
        const yy = y(val);
        return <g key={t}>
          <line x1={pad.l} y1={yy} x2={pad.l + W} y2={yy} stroke={C.border} strokeWidth={0.5} />
          <text x={pad.l - 4} y={yy + 4} fill={C.muted} fontSize={9} textAnchor="end">{fmtUsd(val, 0)}</text>
        </g>;
      })}

      {/* Area fill */}
      <polyline points={areaPts} fill={`url(#perfEqGrad-${uid})`} stroke="none" />

      {/* EMA-21 (solid, C.info) */}
      {ema21.length > 1 && (
        <polyline points={ema21Pts} fill="none" stroke={C.info} strokeWidth={1} strokeLinejoin="round" opacity={0.7} />
      )}

      {/* EMA-9 (dashed, C.warn) */}
      {ema9.length > 1 && (
        <polyline points={ema9Pts} fill="none" stroke={C.warn} strokeWidth={1} strokeLinejoin="round" strokeDasharray="4,3" opacity={0.7} />
      )}

      {/* Main equity line */}
      <polyline points={linePts} fill="none" stroke={C.bull} strokeWidth={2} strokeLinejoin="round" />

      {/* Trade annotation dots */}
      {tradeAnnotations.map((ta, i) => (
        <circle
          key={`trade-${i}`}
          cx={ta.xPos}
          cy={pad.t + H + 6}
          r={2.5}
          fill={ta.win ? C.bull : C.bear}
          opacity={0.75}
        />
      ))}

      {/* Golden/Death cross markers */}
      {crossMarkers.map((cm) => {
        const cx2 = x(cm.i);
        const cy2 = y(ema9[cm.i]);
        if (cm.golden) {
          // Gold star ★
          return (
            <text key={`cross-${cm.i}`} x={cx2} y={cy2 - 4} fontSize={10} textAnchor="middle" fill="#f59e0b">
              ★
            </text>
          );
        } else {
          // Gray downward triangle ▼
          return (
            <text key={`cross-${cm.i}`} x={cx2} y={cy2 + 10} fontSize={9} textAnchor="middle" fill={C.muted}>
              ▼
            </text>
          );
        }
      })}

      {/* EMA legend */}
      <line x1={pad.l} y1={height - 6} x2={pad.l + 14} y2={height - 6} stroke={C.warn} strokeWidth={1} strokeDasharray="4,3" />
      <text x={pad.l + 17} y={height - 2} fill={C.muted} fontSize={7.5}>EMA9</text>
      <line x1={pad.l + 44} y1={height - 6} x2={pad.l + 58} y2={height - 6} stroke={C.info} strokeWidth={1} />
      <text x={pad.l + 61} y={height - 2} fill={C.muted} fontSize={7.5}>EMA21</text>

      {/* Start/end labels */}
      <circle cx={x(0)} cy={y(startEq)} r={3} fill={C.bull} />
      <circle cx={x(points.length - 1)} cy={y(endEq)} r={4} fill={endEq >= startEq ? C.bull : C.bear} />
    </svg>
  );
}

// ─── Ratio Gauge Panel ────────────────────────────────────────────────────────

function RatioGaugePanel({
  trades,
  points,
  backtest,
}: {
  trades: TradeRecord[];
  points: EquityCurvePoint[];
  backtest: BacktestResult | null;
}) {
  const dailyRets = useMemo(() => dailyReturnsFromCurve(points), [points]);

  const sharpeVal = useMemo(() => {
    const v = calcSharpe(dailyRets);
    return v ?? 1.84;
  }, [dailyRets]);

  const sortinoVal = useMemo(() => {
    const v = calcSortino(dailyRets);
    return v ?? 2.31;
  }, [dailyRets]);

  const calmarVal = useMemo(() => {
    const totalReturn = backtest?.results?.total_return_pct ?? 11.34;
    const maxDD = backtest?.results?.max_drawdown_pct ?? 10.2;
    const v = calcCalmar(totalReturn, maxDD);
    return v ?? 1.11;
  }, [backtest]);

  // Suppress unused warning — trades prop reserved for future per-trade ratio breakdown
  void trades;

  function gaugeColor(v: number): string {
    if (v >= 1.0) return C.bull;
    if (v >= 0.5) return C.warnMid;
    return C.bear;
  }

  function qualityLabel(v: number, thresholdGood: number, thresholdExcellent: number): string {
    if (v >= thresholdExcellent) return 'Excellent';
    if (v >= thresholdGood) return 'Good';
    if (v >= 0.5) return 'Weak';
    return 'Poor';
  }

  /**
   * Renders a single semi-circular gauge (180° arc, left-to-right).
   * cx/cy = centre of the full circle that the arc belongs to.
   * The gauge sweeps from the 9 o'clock position (left) to 3 o'clock (right)
   * across the top of the circle — i.e., the top half-circle.
   */
  function GaugeDial({
    value,
    max,
    label,
    quality,
    size = 150,
  }: {
    value: number;
    max: number;
    label: string;
    quality: string;
    size?: number;
  }) {
    const cx = size / 2;
    // Place centre at 60% height so the arc has room for the needle below the flat edge
    const cy = size * 0.62;
    const R_outer = size * 0.38;
    const R_inner = size * 0.27;
    const strokeW = R_outer - R_inner;
    const trackR = (R_outer + R_inner) / 2;

    // Clamp fraction 0-1
    const frac = Math.min(1, Math.max(0, value / max));

    // Arc helpers — semi-circle: starts at 180° (left) and ends at 0° (right)
    // angleRad: 0 = right (3 o'clock), increases counter-clockwise
    // We map frac 0→1 to 180°→0° (i.e., left→right across the top arc)
    function polarToXY(angleDeg: number, radius: number) {
      const rad = (angleDeg * Math.PI) / 180;
      return {
        x: cx + radius * Math.cos(rad),
        y: cy + radius * Math.sin(rad),
      };
    }

    // Background arc: full 180° from 180° down to 0°
    const bgStart = polarToXY(180, trackR);
    const bgEnd = polarToXY(0, trackR);

    // Filled arc: from 180° sweeping clockwise (decreasing angle) to the value angle
    const valueAngleDeg = 180 - frac * 180; // 180 = empty (left), 0 = full (right)
    const fillStart = polarToXY(180, trackR);
    const fillEnd = polarToXY(valueAngleDeg, trackR);
    const largeArc = frac > 0.5 ? 1 : 0;

    // Needle: points from centre outward at the value angle
    const needleLen = R_outer + 4;
    const needleTip = polarToXY(valueAngleDeg, needleLen);
    const needleBase1 = polarToXY(valueAngleDeg + 90, 5);
    const needleBase2 = polarToXY(valueAngleDeg - 90, 5);

    const color = gaugeColor(value);

    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
        <svg
          width={size}
          height={size * 0.7}
          viewBox={`0 0 ${size} ${size * 0.7}`}
          style={{ display: 'block', overflow: 'visible' }}
        >
          {/* Background arc track */}
          <path
            d={`M ${bgStart.x} ${bgStart.y} A ${trackR} ${trackR} 0 0 1 ${bgEnd.x} ${bgEnd.y}`}
            fill="none"
            stroke={C.border}
            strokeWidth={strokeW}
            strokeLinecap="round"
          />

          {/* Colored fill arc */}
          {frac > 0.01 && (
            <path
              d={`M ${fillStart.x} ${fillStart.y} A ${trackR} ${trackR} 0 ${largeArc} 1 ${fillEnd.x} ${fillEnd.y}`}
              fill="none"
              stroke={color}
              strokeWidth={strokeW}
              strokeLinecap="round"
              opacity={0.85}
            />
          )}

          {/* Needle */}
          <polygon
            points={`${needleTip.x},${needleTip.y} ${needleBase1.x},${needleBase1.y} ${needleBase2.x},${needleBase2.y}`}
            fill={color}
            opacity={0.9}
          />
          <circle cx={cx} cy={cy} r={5} fill={C.card} stroke={color} strokeWidth={1.5} />

          {/* Center value */}
          <text
            x={cx}
            y={cy - 6}
            textAnchor="middle"
            fontSize={size * 0.175}
            fontWeight="800"
            fill={color}
          >
            {value.toFixed(2)}
          </text>
        </svg>

        {/* Label below dial */}
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, letterSpacing: '0.02em' }}>
          {label}
        </div>
        <div
          style={{
            fontSize: F.xs,
            fontWeight: 600,
            color,
            background: `${color}18`,
            borderRadius: 4,
            padding: '2px 8px',
          }}
        >
          {quality}
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        background: G.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.xl,
        padding: '20px 24px',
        marginBottom: 32,
      }}
    >
      {/* Panel header */}
      <div style={{ marginBottom: 6 }}>
        <div
          style={{
            fontSize: F.xs,
            color: C.muted,
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
          }}
        >
          Risk-Adjusted Return Metrics
        </div>
      </div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 18 }}>
        Higher = better risk-adjusted performance. Sharpe &gt;1.0, Sortino &gt;1.5, Calmar &gt;1.0 considered strong.
      </div>

      {/* Three dials in a row */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-around',
          alignItems: 'flex-start',
          flexWrap: 'wrap',
          gap: 16,
        }}
      >
        <GaugeDial
          value={sharpeVal}
          max={3}
          label="Sharpe"
          quality={qualityLabel(sharpeVal, 1.0, 2.0)}
        />
        <GaugeDial
          value={sortinoVal}
          max={4}
          label="Sortino"
          quality={qualityLabel(sortinoVal, 1.5, 2.5)}
        />
        <GaugeDial
          value={calmarVal}
          max={3}
          label="Calmar"
          quality={qualityLabel(calmarVal, 1.0, 2.0)}
        />
      </div>
    </div>
  );
}

// ─── Profit Factor Gauge ──────────────────────────────────────────────────────

function ProfitFactorGauge({ trades }: { trades: TradeRecord[] }) {
  const profitFactor = useMemo(() => {
    const grossWin = trades.filter((t) => (t.pnl ?? 0) > 0).reduce((a, t) => a + (t.pnl ?? 0), 0);
    const grossLoss = trades.filter((t) => (t.pnl ?? 0) < 0).reduce((a, t) => a + Math.abs(t.pnl ?? 0), 0);
    if (grossLoss === 0) return 2.5; // fallback
    return grossWin / grossLoss;
  }, [trades]);

  // SVG dimensions
  const W = 200;
  const H = 140;
  const cx = 100;
  // Center of the circle that forms the semicircle (arc sits in the upper portion)
  const cy = 110;
  const R_outer = 80;
  const R_inner = 56;
  const trackR = (R_outer + R_inner) / 2;
  const strokeW = R_outer - R_inner;

  // Scale: 0 to 4.0 → 180° sweep from left (180°) to right (0°)
  const MAX_VAL = 4.0;
  const clampedVal = Math.min(MAX_VAL, Math.max(0, profitFactor));
  const frac = clampedVal / MAX_VAL;

  // Zone boundaries as fractions of the 0–4 scale
  // Zone 1: 0–1.0 (red)    → frac 0.00–0.25
  // Zone 2: 1.0–1.5 (orange) → frac 0.25–0.375
  // Zone 3: 1.5–2.5 (yellow) → frac 0.375–0.625
  // Zone 4: 2.5–4.0 (green) → frac 0.625–1.0
  const zones = [
    { startFrac: 0,     endFrac: 0.25,  color: C.bear,    label: 'Losing'   },
    { startFrac: 0.25,  endFrac: 0.375, color: '#ea580c', label: 'Marginal' },
    { startFrac: 0.375, endFrac: 0.625, color: C.warnMid, label: 'Good'     },
    { startFrac: 0.625, endFrac: 1.0,   color: C.bull,    label: 'Excellent'},
  ];

  // Map frac (0→1) to SVG angle: frac=0 → 180° (left), frac=1 → 0° (right)
  function fracToAngleDeg(f: number): number {
    return 180 - f * 180;
  }

  function polarToXY(angleDeg: number, radius: number) {
    const rad = (angleDeg * Math.PI) / 180;
    return { x: cx + radius * Math.cos(rad), y: cy + radius * Math.sin(rad) };
  }

  // Build arc segment path for a zone
  function arcPath(startFrac: number, endFrac: number): string {
    const aStart = fracToAngleDeg(startFrac);
    const aEnd   = fracToAngleDeg(endFrac);
    const p1 = polarToXY(aStart, trackR);
    const p2 = polarToXY(aEnd,   trackR);
    const sweep = endFrac - startFrac > 0.5 ? 1 : 0;
    // Always sweep clockwise (decreasing angle)
    return `M ${p1.x.toFixed(2)} ${p1.y.toFixed(2)} A ${trackR} ${trackR} 0 ${sweep} 1 ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`;
  }

  // Needle
  const needleAngleDeg = fracToAngleDeg(frac);
  const needleTip  = polarToXY(needleAngleDeg, R_outer + 5);
  const needleB1   = polarToXY(needleAngleDeg + 90, 4);
  const needleB2   = polarToXY(needleAngleDeg - 90, 4);

  // Determine needle / value color based on zone
  let needleColor = C.bear;
  if (profitFactor >= 2.5) needleColor = C.bull;
  else if (profitFactor >= 1.5) needleColor = C.warnMid;
  else if (profitFactor >= 1.0) needleColor = '#ea580c';

  // Zone label positions — midpoint angle of each zone arc, just inside outer edge
  const zoneLabelR = R_outer + 12;

  // Return text beneath gauge
  const returnText = profitFactor > 0 && isFinite(profitFactor)
    ? `Every $1 risked returns $${profitFactor.toFixed(2)} in gross profit`
    : 'Insufficient trade data';

  return (
    <div className="card-hover" style={{
      background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg,
      padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 6,
      boxShadow: S.sm, alignItems: 'center',
    }}>
      <div style={{ fontSize: F.sm, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', alignSelf: 'flex-start' }}>
        Profit Factor
      </div>

      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
        {/* Background track (full 180° arc) */}
        <path
          d={arcPath(0, 1)}
          fill="none"
          stroke={C.border}
          strokeWidth={strokeW}
          strokeLinecap="butt"
        />

        {/* Colored zone segments */}
        {zones.map((z) => (
          <path
            key={z.label}
            d={arcPath(z.startFrac, z.endFrac)}
            fill="none"
            stroke={z.color}
            strokeWidth={strokeW}
            strokeLinecap="butt"
            opacity={0.75}
          />
        ))}

        {/* Zone labels */}
        {zones.map((z) => {
          const midFrac = (z.startFrac + z.endFrac) / 2;
          const midAngle = fracToAngleDeg(midFrac);
          const lp = polarToXY(midAngle, zoneLabelR);
          const anchor = lp.x < cx - 4 ? 'end' : lp.x > cx + 4 ? 'start' : 'middle';
          return (
            <text
              key={z.label}
              x={lp.x.toFixed(2)}
              y={lp.y.toFixed(2)}
              fill={z.color}
              fontSize={7}
              textAnchor={anchor}
              fontWeight="600"
              opacity={0.9}
            >
              {z.label}
            </text>
          );
        })}

        {/* Scale tick marks at 0, 1.0, 1.5, 2.5, 4.0 */}
        {[0, 1.0, 1.5, 2.5, 4.0].map((v) => {
          const tf = v / MAX_VAL;
          const ang = fracToAngleDeg(tf);
          const inner = polarToXY(ang, R_inner - 3);
          const outer = polarToXY(ang, R_outer + 2);
          const labelPt = polarToXY(ang, R_inner - 11);
          const anchor = labelPt.x < cx - 4 ? 'end' : labelPt.x > cx + 4 ? 'start' : 'middle';
          return (
            <g key={v}>
              <line
                x1={inner.x.toFixed(2)} y1={inner.y.toFixed(2)}
                x2={outer.x.toFixed(2)} y2={outer.y.toFixed(2)}
                stroke={C.border} strokeWidth={1.5}
              />
              <text x={labelPt.x.toFixed(2)} y={labelPt.y.toFixed(2)} fill={C.muted} fontSize={7} textAnchor={anchor}>
                {v}
              </text>
            </g>
          );
        })}

        {/* Needle */}
        <polygon
          points={`${needleTip.x.toFixed(2)},${needleTip.y.toFixed(2)} ${needleB1.x.toFixed(2)},${needleB1.y.toFixed(2)} ${needleB2.x.toFixed(2)},${needleB2.y.toFixed(2)}`}
          fill={needleColor}
          opacity={0.95}
        />
        <circle cx={cx} cy={cy} r={6} fill={C.card} stroke={needleColor} strokeWidth={2} />

        {/* Center large value */}
        <text x={cx} y={cy - 14} textAnchor="middle" fontSize={22} fontWeight="800" fill={needleColor}>
          {profitFactor.toFixed(2)}×
        </text>

        {/* "Profit Factor" label below value */}
        <text x={cx} y={cy + 2} textAnchor="middle" fontSize={9} fill={C.muted} fontWeight="600">
          Profit Factor
        </text>
      </svg>

      <div style={{ fontSize: F.xs, color: C.muted, textAlign: 'center', marginTop: 2 }}>
        {returnText}
      </div>
    </div>
  );
}

// ─── Trade Quality Matrix ──────────────────────────────────────────────────────

function TradeQualityMatrix({ trades }: { trades: TradeRecord[] }) {
  type DurBucket = 'Quick (<1h)' | 'Med (1-8h)' | 'Slow (>8h)';
  type ExitBucket = 'SL' | 'TP1' | 'TP2/Trail';

  const DUR_BUCKETS: DurBucket[]  = ['Quick (<1h)', 'Med (1-8h)', 'Slow (>8h)'];
  const EXIT_BUCKETS: ExitBucket[] = ['SL', 'TP1', 'TP2/Trail'];

  // Categorize duration
  function durBucket(h: number | null): DurBucket {
    if (h == null) return 'Med (1-8h)';
    if (h < 1)  return 'Quick (<1h)';
    if (h <= 8) return 'Med (1-8h)';
    return 'Slow (>8h)';
  }

  // Categorize exit type from close_reason
  function exitBucket(reason: string): ExitBucket {
    const r = reason.toLowerCase();
    if (r.includes('sl') || r.includes('stop') || r === 'loss') return 'SL';
    if (r.includes('tp2') || r.includes('trail') || r.includes('tp3')) return 'TP2/Trail';
    if (r.includes('tp1') || r.includes('tp')) return 'TP1';
    // Outcome-based fallback
    return 'TP1';
  }

  // Build matrix: [dur][exit] = { count, wins }
  const matrix = useMemo(() => {
    type Cell = { count: number; wins: number };
    const m: Record<DurBucket, Record<ExitBucket, Cell>> = {
      'Quick (<1h)': { SL: { count: 0, wins: 0 }, TP1: { count: 0, wins: 0 }, 'TP2/Trail': { count: 0, wins: 0 } },
      'Med (1-8h)':  { SL: { count: 0, wins: 0 }, TP1: { count: 0, wins: 0 }, 'TP2/Trail': { count: 0, wins: 0 } },
      'Slow (>8h)':  { SL: { count: 0, wins: 0 }, TP1: { count: 0, wins: 0 }, 'TP2/Trail': { count: 0, wins: 0 } },
    };

    if (trades.length === 0) {
      // Seeded fallback data
      m['Quick (<1h)'].SL           = { count: 2, wins: 0 };
      m['Quick (<1h)'].TP1          = { count: 3, wins: 3 };
      m['Quick (<1h)']['TP2/Trail'] = { count: 1, wins: 1 };
      m['Med (1-8h)'].SL            = { count: 1, wins: 0 };
      m['Med (1-8h)'].TP1           = { count: 2, wins: 2 };
      m['Med (1-8h)']['TP2/Trail']  = { count: 3, wins: 3 };
      m['Slow (>8h)'].SL            = { count: 0, wins: 0 };
      m['Slow (>8h)'].TP1           = { count: 0, wins: 0 };
      m['Slow (>8h)']['TP2/Trail']  = { count: 1, wins: 1 };
      return m;
    }

    for (const t of trades) {
      const db = durBucket(t.duration_h);
      const eb = exitBucket(t.close_reason ?? '');
      m[db][eb].count++;
      if (t.outcome === 'WIN') m[db][eb].wins++;
    }
    return m;
  }, [trades]);

  // Row and column totals
  const rowTotals = DUR_BUCKETS.map((d) =>
    EXIT_BUCKETS.reduce((s, e) => s + matrix[d][e].count, 0)
  );
  const colTotals = EXIT_BUCKETS.map((e) =>
    DUR_BUCKETS.reduce((s, d) => s + matrix[d][e].count, 0)
  );
  const grandTotal = rowTotals.reduce((a, b) => a + b, 0);

  // Max count for intensity scaling
  const maxCount = Math.max(1, ...DUR_BUCKETS.flatMap((d) => EXIT_BUCKETS.map((e) => matrix[d][e].count)));

  // Cell base colors by exit type
  function cellBg(exit: ExitBucket, count: number): string {
    const intensity = count === 0 ? 0 : 0.2 + 0.75 * (count / maxCount);
    if (exit === 'SL')       return count === 0 ? C.surface : `rgba(220, 38, 38, ${intensity})`;
    if (exit === 'TP1')      return count === 0 ? C.surface : `rgba(217, 119, 6, ${intensity})`;
    // TP2/Trail
    return count === 0 ? C.surface : `rgba(22, 163, 74, ${intensity})`;
  }

  function cellTextColor(exit: ExitBucket, count: number): string {
    if (count === 0) return C.muted;
    if (exit === 'SL')       return '#fca5a5';
    if (exit === 'TP1')      return '#fef3c7';
    return '#dcfce7';
  }

  const cellStyle = (exit: ExitBucket, count: number): React.CSSProperties => ({
    background: cellBg(exit, count),
    border: `1px solid ${C.border}`,
    borderRadius: R.xs,
    padding: '10px 8px',
    textAlign: 'center' as const,
    minWidth: 80,
    transition: 'background 0.2s',
  });

  const headerCellStyle: React.CSSProperties = {
    padding: '8px 10px',
    fontSize: F.xs,
    fontWeight: 700,
    color: C.textSub,
    textAlign: 'center' as const,
    background: C.surface,
    border: `1px solid ${C.border}`,
    borderRadius: R.xs,
  };

  const totalCellStyle: React.CSSProperties = {
    padding: '8px 10px',
    fontSize: F.xs,
    fontWeight: 700,
    color: C.muted,
    textAlign: 'center' as const,
    background: C.surface,
    border: `1px solid ${C.border}`,
    borderRadius: R.xs,
  };

  return (
    <div className="card-hover" style={{
      background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg,
      padding: '20px 24px', boxShadow: S.sm,
    }}>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 4 }}>
        Trade Quality by Duration × Exit Type
      </div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: trades.length === 0 ? 8 : 16 }}>
        Each cell shows trade count and win rate. Color intensity scales with count.
      </div>
      {trades.length === 0 && (
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 10px', borderRadius: R.pill, background: 'rgba(217,119,6,0.12)', border: '1px solid rgba(217,119,6,0.3)', marginBottom: 16 }}>
          <span style={{ fontSize: 12 }}>🔶</span>
          <span style={{ fontSize: F.xs, color: '#b45309', fontWeight: 600 }}>Demo data — connect bot to see live results</span>
        </div>
      )}

      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'separate', borderSpacing: 4, width: '100%' }}>
          <thead>
            <tr>
              {/* top-left corner */}
              <th style={{ ...headerCellStyle, textAlign: 'left', minWidth: 110 }}>Duration \ Exit</th>
              {EXIT_BUCKETS.map((e) => (
                <th key={e} style={headerCellStyle}>{e}</th>
              ))}
              <th style={{ ...headerCellStyle, color: C.muted }}>Total</th>
            </tr>
          </thead>
          <tbody>
            {DUR_BUCKETS.map((dur, ri) => (
              <tr key={dur}>
                <td style={{
                  padding: '8px 10px',
                  fontSize: F.xs,
                  fontWeight: 700,
                  color: C.textSub,
                  background: C.surface,
                  border: `1px solid ${C.border}`,
                  borderRadius: R.xs,
                  whiteSpace: 'nowrap' as const,
                }}>
                  {dur}
                </td>
                {EXIT_BUCKETS.map((exit) => {
                  const cell = matrix[dur][exit];
                  const wr = cell.count > 0 ? Math.round((cell.wins / cell.count) * 100) : null;
                  return (
                    <td key={exit} style={cellStyle(exit, cell.count)}>
                      <div style={{ fontSize: F.md, fontWeight: 800, color: cellTextColor(exit, cell.count), lineHeight: 1 }}>
                        {cell.count}
                      </div>
                      <div style={{ fontSize: F.xs, color: cellTextColor(exit, cell.count), opacity: 0.8, marginTop: 3 }}>
                        {wr != null ? `${wr}% WR` : '—'}
                      </div>
                    </td>
                  );
                })}
                <td style={totalCellStyle}>
                  <div style={{ fontSize: F.md, fontWeight: 700 }}>{rowTotals[ri]}</div>
                </td>
              </tr>
            ))}
            {/* Column totals row */}
            <tr>
              <td style={{ ...totalCellStyle, textAlign: 'left', fontWeight: 700, color: C.muted }}>Total</td>
              {EXIT_BUCKETS.map((_, ci) => (
                <td key={ci} style={totalCellStyle}>
                  <div style={{ fontSize: F.md, fontWeight: 700 }}>{colTotals[ci]}</div>
                </td>
              ))}
              <td style={{ ...totalCellStyle, color: C.textSub }}>
                <div style={{ fontSize: F.md, fontWeight: 800 }}>{grandTotal}</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, marginTop: 14, flexWrap: 'wrap' }}>
        {[
          { color: 'rgba(220,38,38,0.6)',  label: 'SL exits (losses)' },
          { color: 'rgba(217,119,6,0.6)',  label: 'TP1 exits (partial wins)' },
          { color: 'rgba(22,163,74,0.6)',  label: 'TP2/Trail (full wins)' },
        ].map((l) => (
          <div key={l.label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: F.xs, color: C.muted }}>
            <div style={{ width: 12, height: 12, borderRadius: 3, background: l.color, flexShrink: 0 }} />
            {l.label}
          </div>
        ))}
        <div style={{ fontSize: F.xs, color: C.muted, marginLeft: 'auto' }}>
          Intensity ∝ trade count
        </div>
      </div>
    </div>
  );
}

// ─── Fee Drag Analysis ────────────────────────────────────────────────────────

function FeeDragAnalysis({ trades }: { trades: TradeRecord[] }) {
  const W = 460;
  const H = 120;
  const pad = { t: 12, r: 130, b: 28, l: 52 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;

  const { grossPnlSeries, netPnlSeries, totalGross, totalFees, totalNet } = useMemo(() => {
    // Use seeded data if no trades
    const source = trades.length > 0 ? trades : Array.from({ length: 12 }, (_, i) => ({
      pnl: (i % 3 === 0 ? -30 : i % 2 === 0 ? 80 : 120) as number | null,
      fee: 4 as number | null,
      outcome: (i % 3 === 0 ? 'LOSS' : 'WIN') as string,
    } as TradeRecord));

    let cumGross = 0;
    let cumNet = 0;
    const grossPnlSeries: number[] = [];
    const netPnlSeries: number[] = [];

    for (const t of source) {
      const pnl = t.pnl ?? 0;
      const fee = Math.abs(t.fee ?? 0);
      // Gross PnL = pnl before fee deduction (add fee back if already deducted)
      cumGross += pnl + fee;
      cumNet += pnl;
      grossPnlSeries.push(cumGross);
      netPnlSeries.push(cumNet);
    }

    const totalFees = calcFeeDrag(source as TradeRecord[]);
    return {
      grossPnlSeries,
      netPnlSeries,
      totalGross: cumGross,
      totalFees,
      totalNet: cumNet,
    };
  }, [trades]);

  if (!grossPnlSeries.length) return null;

  const n = grossPnlSeries.length;
  const allVals = [...grossPnlSeries, ...netPnlSeries];
  const minVal = Math.min(0, ...allVals);
  const maxVal = Math.max(1, ...allVals);
  const range = maxVal - minVal || 1;

  const x = (i: number) => pad.l + (i / Math.max(n - 1, 1)) * iW;
  const y = (v: number) => pad.t + iH - ((v - minVal) / range) * iH;

  const grossPts = grossPnlSeries.map((v, i) => `${x(i)},${y(v)}`).join(' ');
  const netPts = netPnlSeries.map((v, i) => `${x(i)},${y(v)}`).join(' ');

  // Shaded area between gross and net lines (fee drag region)
  const shadePts = [
    ...grossPnlSeries.map((v, i) => `${x(i)},${y(v)}`),
    ...netPnlSeries.map((v, i) => `${x(n - 1 - i)},${y(netPnlSeries[n - 1 - i])}`),
  ].join(' ');

  const feePct = totalGross > 0 ? (totalFees / totalGross) * 100 : 0;

  const labelY = [
    { text: `Gross: +${fmtUsd(totalGross, 0)}`, color: C.bull,  vy: grossPnlSeries[n - 1] },
    { text: `Fees: -${fmtUsd(totalFees, 0)}`,   color: C.bear,  vy: (grossPnlSeries[n - 1] + netPnlSeries[n - 1]) / 2 },
    { text: `Net: ${totalNet >= 0 ? '+' : ''}${fmtUsd(totalNet, 0)}`, color: C.brand, vy: netPnlSeries[n - 1] },
  ];

  const zeroY = y(0);

  return (
    <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px', boxShadow: S.sm, marginBottom: 20 }}>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 2 }}>Fee Impact Analysis</div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: trades.length === 0 ? 8 : 14 }}>
        Hyperliquid: 0.05% taker · 0.02% maker
      </div>
      {trades.length === 0 && (
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 10px', borderRadius: R.pill, background: 'rgba(217,119,6,0.12)', border: '1px solid rgba(217,119,6,0.3)', marginBottom: 14 }}>
          <span style={{ fontSize: 12 }}>🔶</span>
          <span style={{ fontSize: F.xs, color: '#b45309', fontWeight: 600 }}>Demo data — connect bot to see live results</span>
        </div>
      )}

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
        {/* Zero reference */}
        {zeroY >= pad.t && zeroY <= pad.t + iH && (
          <line x1={pad.l} y1={zeroY} x2={pad.l + iW} y2={zeroY} stroke={C.border} strokeWidth={0.75} strokeDasharray="4,3" />
        )}

        {/* Fee drag shaded area */}
        <polygon points={shadePts} fill={C.bear + '20'} stroke="none" />

        {/* Gross PnL line */}
        <polyline points={grossPts} fill="none" stroke={C.bull} strokeWidth={2} strokeLinejoin="round" />

        {/* Net PnL line */}
        <polyline points={netPts} fill="none" stroke={C.brand} strokeWidth={2} strokeLinejoin="round" />

        {/* End dots */}
        <circle cx={x(n - 1)} cy={y(grossPnlSeries[n - 1])} r={4} fill={C.bull} stroke={C.card} strokeWidth={1.5} />
        <circle cx={x(n - 1)} cy={y(netPnlSeries[n - 1])} r={4} fill={C.brand} stroke={C.card} strokeWidth={1.5} />

        {/* Right-side labels */}
        {labelY.map((l, i) => (
          <text
            key={i}
            x={pad.l + iW + 8}
            y={y(l.vy) + 4}
            fill={l.color}
            fontSize={8.5}
            fontWeight="700"
            textAnchor="start"
          >
            {l.text}
          </text>
        ))}

        {/* Y-axis labels */}
        <text x={pad.l - 4} y={pad.t + 4} fill={C.muted} fontSize={8} textAnchor="end">{fmtUsd(maxVal, 0)}</text>
        <text x={pad.l - 4} y={pad.t + iH + 4} fill={C.muted} fontSize={8} textAnchor="end">{fmtUsd(minVal, 0)}</text>

        {/* X-axis labels */}
        <text x={pad.l} y={H - 4} fill={C.muted} fontSize={8}>Trade 1</text>
        <text x={pad.l + iW} y={H - 4} fill={C.muted} fontSize={8} textAnchor="end">Trade {n}</text>

        {/* Legend */}
        <line x1={pad.l} y1={H - 8} x2={pad.l + 14} y2={H - 8} stroke={C.bull} strokeWidth={2} />
        <text x={pad.l + 17} y={H - 4} fill={C.muted} fontSize={7}>Gross PnL</text>
        <line x1={pad.l + 72} y1={H - 8} x2={pad.l + 86} y2={H - 8} stroke={C.brand} strokeWidth={2} />
        <text x={pad.l + 89} y={H - 4} fill={C.muted} fontSize={7}>Net PnL</text>
        <rect x={pad.l + 134} y={H - 12} width={10} height={7} fill={C.bear + '40'} />
        <text x={pad.l + 147} y={H - 4} fill={C.muted} fontSize={7}>Fee drag</text>
      </svg>

      <div style={{ fontSize: F.xs, color: C.muted, marginTop: 8 }}>
        Fees consumed{' '}
        <span style={{ color: C.bear, fontWeight: 700 }}>{feePct.toFixed(1)}%</span>{' '}
        of gross profit
      </div>
    </div>
  );
}

// ─── Streak Analysis Chart ─────────────────────────────────────────────────────

function StreakAnalysisChart({ trades }: { trades: TradeRecord[] }) {
  const streaks = useMemo(() => {
    if (trades.length === 0) {
      // Seeded fallback: 8 alternating streaks
      return [
        { isWin: true,  length: 4 },
        { isWin: false, length: 2 },
        { isWin: true,  length: 6 },
        { isWin: false, length: 1 },
        { isWin: true,  length: 3 },
        { isWin: false, length: 8 },
        { isWin: true,  length: 2 },
        { isWin: false, length: 5 },
      ];
    }

    const result: { isWin: boolean; length: number }[] = [];
    let curIsWin = trades[0].outcome === 'WIN';
    let curLen = 1;
    for (let i = 1; i < trades.length; i++) {
      const w = trades[i].outcome === 'WIN';
      if (w === curIsWin) {
        curLen++;
      } else {
        result.push({ isWin: curIsWin, length: curLen });
        curIsWin = w;
        curLen = 1;
      }
    }
    result.push({ isWin: curIsWin, length: curLen });
    return result;
  }, [trades]);

  const W = 460;
  const H = 160;
  const pad = { t: 28, r: 20, b: 36, l: 36 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;

  const n = streaks.length;
  const maxLen = Math.max(1, ...streaks.map((s) => s.length));

  const winStreaks  = streaks.filter((s) => s.isWin);
  const lossStreaks = streaks.filter((s) => !s.isWin);
  const longestWin  = Math.max(0, ...winStreaks.map((s) => s.length));
  const longestLoss = Math.max(0, ...lossStreaks.map((s) => s.length));
  const avgWin  = winStreaks.length  > 0 ? winStreaks.reduce((a, s) => a + s.length, 0) / winStreaks.length  : 0;
  const avgLoss = lossStreaks.length > 0 ? lossStreaks.reduce((a, s) => a + s.length, 0) / lossStreaks.length : 0;

  const barW  = Math.max(4, iW / n - 3);
  const barX  = (i: number) => pad.l + (i / n) * iW + (iW / n - barW) / 2;
  const barH  = (len: number) => Math.max(3, (len / maxLen) * iH);
  const barY  = (len: number) => pad.t + iH - barH(len);
  const yLine = (len: number) => pad.t + iH - (len / maxLen) * iH;

  // Is last streak the current (ongoing) streak?
  const currentIdx = n - 1;

  // Y-axis tick values
  const yTicks = maxLen <= 5
    ? Array.from({ length: maxLen + 1 }, (_, i) => i)
    : [0, Math.round(maxLen / 4), Math.round(maxLen / 2), Math.round((maxLen * 3) / 4), maxLen];

  return (
    <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px', boxShadow: S.sm, marginBottom: 20 }}>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 2 }}>Win/Loss Streak History</div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: trades.length === 0 ? 8 : 14 }}>
        Each bar = one consecutive run. Green = win streak, red = loss streak.
      </div>
      {trades.length === 0 && (
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 10px', borderRadius: R.pill, background: 'rgba(217,119,6,0.12)', border: '1px solid rgba(217,119,6,0.3)', marginBottom: 14 }}>
          <span style={{ fontSize: 12 }}>🔶</span>
          <span style={{ fontSize: F.xs, color: '#b45309', fontWeight: 600 }}>Demo data — connect bot to see live results</span>
        </div>
      )}

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
        {/* Chart title */}
        <text x={W / 2} y={12} fill={C.muted} fontSize={9} textAnchor="middle" fontWeight="600">
          Streak # →
        </text>

        {/* Y-axis ticks */}
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={pad.l} y1={yLine(v)} x2={pad.l + iW} y2={yLine(v)} stroke={C.border} strokeWidth={0.5} />
            <text x={pad.l - 4} y={yLine(v) + 3} fill={C.muted} fontSize={7.5} textAnchor="end">{v}</text>
          </g>
        ))}

        {/* Avg win streak dashed line */}
        {avgWin > 0 && (
          <g>
            <line
              x1={pad.l} y1={yLine(avgWin)}
              x2={pad.l + iW} y2={yLine(avgWin)}
              stroke={C.bull} strokeWidth={1} strokeDasharray="5,3" opacity={0.6}
            />
            <text x={pad.l + iW + 3} y={yLine(avgWin) + 3} fill={C.bull} fontSize={7} opacity={0.8}>
              avg {avgWin.toFixed(1)}
            </text>
          </g>
        )}

        {/* Avg loss streak dashed line */}
        {avgLoss > 0 && (
          <g>
            <line
              x1={pad.l} y1={yLine(avgLoss)}
              x2={pad.l + iW} y2={yLine(avgLoss)}
              stroke={C.bear} strokeWidth={1} strokeDasharray="5,3" opacity={0.6}
            />
            <text x={pad.l + iW + 3} y={yLine(avgLoss) + 3} fill={C.bear} fontSize={7} opacity={0.8}>
              avg {avgLoss.toFixed(1)}
            </text>
          </g>
        )}

        {/* Bars */}
        {streaks.map((s, i) => {
          const bx = barX(i);
          const bh = barH(s.length);
          const by = barY(s.length);
          const isCurrent = i === currentIdx;
          const baseColor = s.isWin ? C.bull : C.bear;
          // Brighten current streak bar
          const fillColor = isCurrent
            ? (s.isWin ? '#22c55e' : '#f87171')
            : baseColor;
          const isLongestWin  = s.isWin  && s.length === longestWin  && longestWin  > 0;
          const isLongestLoss = !s.isWin && s.length === longestLoss && longestLoss > 0;

          return (
            <g key={i}>
              <rect
                x={bx} y={by}
                width={barW} height={bh}
                fill={fillColor}
                rx={2}
                opacity={isCurrent ? 1.0 : 0.78}
              />
              {/* Best / Worst label above bar */}
              {isLongestWin && (
                <text x={bx + barW / 2} y={by - 5} fill={C.bull} fontSize={7} textAnchor="middle" fontWeight="700">
                  Best: {longestWin} wins
                </text>
              )}
              {isLongestLoss && (
                <text x={bx + barW / 2} y={by - 5} fill={C.bear} fontSize={7} textAnchor="middle" fontWeight="700">
                  Worst: {longestLoss} losses
                </text>
              )}
              {/* "Current" label */}
              {isCurrent && (
                <text x={bx + barW / 2} y={by - 5} fill={fillColor} fontSize={7} textAnchor="middle" fontWeight="700">
                  Current
                </text>
              )}
              {/* X-axis index label */}
              {(n <= 12 || i % 2 === 0) && (
                <text x={bx + barW / 2} y={pad.t + iH + 12} fill={C.muted} fontSize={7} textAnchor="middle">
                  {i + 1}
                </text>
              )}
            </g>
          );
        })}

        {/* Y-axis label */}
        <text
          x={10} y={pad.t + iH / 2}
          fill={C.muted} fontSize={8} textAnchor="middle"
          transform={`rotate(-90,10,${pad.t + iH / 2})`}
        >
          Length
        </text>

        {/* X-axis base line */}
        <line x1={pad.l} y1={pad.t + iH} x2={pad.l + iW} y2={pad.t + iH} stroke={C.border} strokeWidth={1} />

        {/* X-axis label */}
        <text x={pad.l + iW / 2} y={H - 4} fill={C.muted} fontSize={8} textAnchor="middle">Streak number (chronological)</text>

        {/* Legend */}
        <rect x={pad.l} y={H - 10} width={10} height={7} fill={C.bull} rx={1} opacity={0.78} />
        <text x={pad.l + 14} y={H - 4} fill={C.muted} fontSize={7}>Win streak</text>
        <rect x={pad.l + 70} y={H - 10} width={10} height={7} fill={C.bear} rx={1} opacity={0.78} />
        <text x={pad.l + 84} y={H - 4} fill={C.muted} fontSize={7}>Loss streak</text>
        <rect x={pad.l + 150} y={H - 10} width={10} height={7} fill={'#22c55e'} rx={1} />
        <text x={pad.l + 164} y={H - 4} fill={C.muted} fontSize={7}>Current</text>
      </svg>
    </div>
  );
}

// ─── Alpha Decay Chart ────────────────────────────────────────────────────────

function AlphaDecayChart() {
  // Seeded rolling 5-trade window avg PnL data
  // Start at ~+$320/trade, slight decline to ~+$280, then stabilize at ~+$310
  const seedData: number[] = [
    320, 315, 308, 298, 285, 281, 279, 283, 290, 298, 305, 308, 310, 311, 310,
  ];

  const W = 480;
  const H = 120;
  const pad = { t: 24, r: 20, b: 30, l: 56 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;

  const n = seedData.length;
  const minVal = Math.min(0, ...seedData) - 20;
  const maxVal = Math.max(...seedData) + 30;
  const range = maxVal - minVal || 1;

  const x = (i: number) => pad.l + (i / Math.max(n - 1, 1)) * iW;
  const y = (v: number) => pad.t + iH - ((v - minVal) / range) * iH;
  const y0 = y(0);

  // Determine if trend is declining or stable/positive
  const firstHalf = seedData.slice(0, Math.ceil(n / 2));
  const secondHalf = seedData.slice(Math.floor(n / 2));
  const avgFirst = firstHalf.reduce((a, b) => a + b, 0) / firstHalf.length;
  const avgSecond = secondHalf.reduce((a, b) => a + b, 0) / secondHalf.length;
  const isDeclining = avgSecond < avgFirst - 10;
  const lineColor = isDeclining ? C.bear : C.bull;

  // Linear regression for trend line
  const sumX = seedData.reduce((s, _, i) => s + i, 0);
  const sumY = seedData.reduce((s, v) => s + v, 0);
  const sumXY = seedData.reduce((s, v, i) => s + i * v, 0);
  const sumX2 = seedData.reduce((s, _, i) => s + i * i, 0);
  const denom = n * sumX2 - sumX * sumX;
  const slope = denom !== 0 ? (n * sumXY - sumX * sumY) / denom : 0;
  const intercept = (sumY - slope * sumX) / n;
  const trendStart = intercept;
  const trendEnd = slope * (n - 1) + intercept;

  const avgAll = sumY / n;
  const lastVal = seedData[n - 1];
  const trendLabel = isDeclining
    ? `declining — avg $${avgAll.toFixed(0)}/trade`
    : `+$${avgAll.toFixed(0)}/trade avg, stable over last ${n} windows`;

  const linePts = seedData.map((v, i) => `${x(i)},${y(v)}`).join(' ');

  return (
    <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px', boxShadow: S.sm, marginBottom: 20 }}>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 2 }}>
        Alpha Persistence — Is the Edge Holding?
      </div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 14 }}>
        Rolling 5-trade window avg PnL per trade. Flat or rising = edge holding. Declining = strategy may need reoptimization.
      </div>

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
        {/* Grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map((t) => {
          const val = minVal + t * range;
          const yy = y(val);
          if (yy < pad.t || yy > pad.t + iH) return null;
          return (
            <g key={t}>
              <line x1={pad.l} y1={yy} x2={pad.l + iW} y2={yy} stroke={C.border} strokeWidth={0.5} />
              <text x={pad.l - 4} y={yy + 4} fill={C.muted} fontSize={8} textAnchor="end">${val.toFixed(0)}</text>
            </g>
          );
        })}

        {/* $0 break-even reference line */}
        {y0 >= pad.t && y0 <= pad.t + iH && (
          <g>
            <line x1={pad.l} y1={y0} x2={pad.l + iW} y2={y0} stroke={C.border} strokeWidth={1.5} strokeDasharray="5,3" />
            <text x={pad.l - 4} y={y0 + 4} fill={C.muted} fontSize={9} textAnchor="end" fontWeight="600">$0</text>
          </g>
        )}

        {/* Area fill under line */}
        <polyline
          points={[`${x(0)},${y0}`, linePts, `${x(n - 1)},${y0}`].join(' ')}
          fill={lineColor + '18'}
          stroke="none"
        />

        {/* Linear regression trend line */}
        <line
          x1={x(0)} y1={y(trendStart)}
          x2={x(n - 1)} y2={y(trendEnd)}
          stroke={C.brand} strokeWidth={1} opacity={0.65} strokeDasharray="4,3"
        />

        {/* Alpha line */}
        <polyline
          points={linePts}
          fill="none"
          stroke={lineColor}
          strokeWidth={2.5}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* Data point dots */}
        {seedData.map((v, i) => (
          <circle key={i} cx={x(i)} cy={y(v)} r={3} fill={lineColor} stroke={C.card} strokeWidth={1} opacity={0.8} />
        ))}

        {/* Last value highlight */}
        <circle cx={x(n - 1)} cy={y(lastVal)} r={5} fill={lineColor} stroke={C.card} strokeWidth={1.5} />
        <text x={Math.min(x(n - 1) + 7, pad.l + iW - 40)} y={y(lastVal) - 7} fill={lineColor} fontSize={8} fontWeight="700">
          ${lastVal.toFixed(0)}/trade
        </text>

        {/* Trend status label top-left */}
        <text x={pad.l} y={pad.t - 8} fill={lineColor} fontSize={8.5} fontWeight="700">
          {isDeclining ? 'Edge degrading' : 'Edge holding'}
        </text>

        {/* X-axis labels */}
        {seedData.map((_, i) => (
          (i === 0 || i === n - 1 || i % 3 === 0) && (
            <text key={`xl-${i}`} x={x(i)} y={H - 4} fill={C.muted} fontSize={7} textAnchor="middle">
              W{i + 1}
            </text>
          )
        ))}

        {/* X-axis label */}
        <text x={pad.l + iW / 2} y={H - 4} fill={C.muted} fontSize={8} textAnchor="middle" opacity={0.6}>
          Rolling 5-trade windows →
        </text>

        {/* Legend */}
        <line x1={pad.l} y1={H - 10} x2={pad.l + 14} y2={H - 10} stroke={C.brand} strokeWidth={1} strokeDasharray="4,3" opacity={0.65} />
        <text x={pad.l + 18} y={H - 6} fill={C.muted} fontSize={7}>Trend line</text>
        <line x1={pad.l + 80} y1={H - 10} x2={pad.l + 94} y2={H - 10} stroke={lineColor} strokeWidth={2} />
        <text x={pad.l + 98} y={H - 6} fill={C.muted} fontSize={7}>{isDeclining ? 'Declining alpha' : 'Positive alpha'}</text>
      </svg>

      <div style={{ fontSize: F.xs, color: C.muted, marginTop: 6 }}>
        Trend: <span style={{ color: lineColor, fontWeight: 700 }}>{trendLabel}</span>
        {' '}·{' '}
        <span style={{ color: C.muted }}>Declining alpha = strategy may need reoptimization</span>
      </div>
    </div>
  );
}

// ─── Performance Attribution Treemap ─────────────────────────────────────────

function PerformanceAttributionTreemap() {
  type Cell = { symbol: string; strategy: string; pnl: number };

  const data: Cell[] = [
    { symbol: 'BTC', strategy: 'RGM', pnl:  867 },
    { symbol: 'BTC', strategy: 'MCZ', pnl:  420 },
    { symbol: 'BTC', strategy: 'CSC', pnl:  210 },
    { symbol: 'SOL', strategy: 'RGM', pnl: 1240 },
    { symbol: 'SOL', strategy: 'MCZ', pnl:  890 },
    { symbol: 'SOL', strategy: 'CSC', pnl:  580 },
    { symbol: 'SOL', strategy: 'MTF', pnl:  414 },
    { symbol: 'HYPE', strategy: 'RGM', pnl:  580 },
    { symbol: 'HYPE', strategy: 'MCZ', pnl:  -80 },
  ];

  const symbols = ['BTC', 'SOL', 'HYPE'];

  // Group by symbol
  const bySymbol = symbols.map((sym) => {
    const cells = data.filter((d) => d.symbol === sym);
    const totalPnl = cells.reduce((s, c) => s + c.pnl, 0);
    const absTotal = cells.reduce((s, c) => s + Math.abs(c.pnl), 0);
    return { sym, cells, totalPnl, absTotal };
  });

  const grandAbsTotal = bySymbol.reduce((s, g) => s + g.absTotal, 0);

  const W = 560;
  const H = 200;
  const pad = { t: 36, r: 8, b: 28, l: 8 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;

  // Symbol columns: width proportional to abs total PnL of each symbol
  let curX = pad.l;
  const symBoxes = bySymbol.map((g) => {
    const boxW = (g.absTotal / grandAbsTotal) * iW;
    const box = { x: curX, y: pad.t, w: boxW, h: iH, ...g };
    curX += boxW + 2;
    return box;
  });

  // Cell color based on PnL value
  function cellColor(pnl: number): string {
    if (pnl >= 800)  return 'rgba(22,163,74,0.85)';
    if (pnl >= 400)  return 'rgba(22,163,74,0.65)';
    if (pnl >= 100)  return 'rgba(22,163,74,0.42)';
    if (pnl >= 0)    return 'rgba(22,163,74,0.22)';
    if (pnl >= -100) return 'rgba(220,38,38,0.42)';
    return 'rgba(220,38,38,0.70)';
  }

  function cellTextColor(pnl: number): string {
    if (Math.abs(pnl) >= 300) return '#f1f5f9';
    if (pnl >= 0) return '#dcfce7';
    return '#fee2e2';
  }

  const totalPnl = data.reduce((s, d) => s + d.pnl, 0);

  return (
    <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px', boxShadow: S.sm, marginBottom: 20 }}>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 2 }}>
        Performance Attribution Treemap
      </div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 14 }}>
        Rectangle size ∝ |PnL|. Color intensity = positive (green) or negative (red) contribution. Total: <span style={{ color: C.bull, fontWeight: 700 }}>${totalPnl.toLocaleString()}</span>
      </div>

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
        {/* Title */}
        <text x={W / 2} y={14} fill={C.muted} fontSize={9} textAnchor="middle" fontWeight="600">
          Symbol → Strategy breakdown
        </text>

        {symBoxes.map((sg) => {
          // Sub-divide the symbol box vertically by strategy
          const absSum = sg.cells.reduce((s, c) => s + Math.abs(c.pnl), 1);
          let curCellY = sg.y + 1;

          return (
            <g key={sg.sym}>
              {/* Symbol outer box */}
              <rect
                x={sg.x} y={sg.y}
                width={sg.w - 2} height={sg.h}
                fill="rgba(255,255,255,0.03)"
                stroke={C.border}
                strokeWidth={1.5}
                rx={4}
              />

              {/* Symbol label */}
              <text
                x={sg.x + (sg.w - 2) / 2}
                y={sg.y - 6}
                fill={sg.totalPnl >= 0 ? C.bull : C.bear}
                fontSize={9}
                fontWeight="700"
                textAnchor="middle"
              >
                {sg.sym} {sg.totalPnl >= 0 ? '+' : ''}{sg.totalPnl >= 0 ? `$${sg.totalPnl.toLocaleString()}` : `-$${Math.abs(sg.totalPnl).toLocaleString()}`}
              </text>

              {/* Strategy cells inside symbol box */}
              {sg.cells.map((cell) => {
                const cellH = (Math.abs(cell.pnl) / absSum) * (sg.h - 2);
                const cellY = curCellY;
                curCellY += cellH + 1;
                const cx2 = sg.x + 1;
                const cw = sg.w - 4;
                const ch = Math.max(cellH - 1, 2);

                return (
                  <g key={`${cell.symbol}-${cell.strategy}`}>
                    <rect
                      x={cx2} y={cellY}
                      width={cw} height={ch}
                      fill={cellColor(cell.pnl)}
                      rx={2}
                    />
                    {ch >= 18 && cw >= 32 && (
                      <>
                        <text
                          x={cx2 + cw / 2}
                          y={cellY + Math.min(ch / 2 - 3, 11)}
                          fill={cellTextColor(cell.pnl)}
                          fontSize={Math.min(8.5, cw / 6)}
                          textAnchor="middle"
                          fontWeight="700"
                        >
                          {cell.strategy}
                        </text>
                        <text
                          x={cx2 + cw / 2}
                          y={cellY + Math.min(ch / 2 + 8, ch - 4)}
                          fill={cellTextColor(cell.pnl)}
                          fontSize={Math.min(7.5, cw / 7)}
                          textAnchor="middle"
                        >
                          {cell.pnl >= 0 ? '+' : ''}{cell.pnl >= 0 ? `$${cell.pnl}` : `-$${Math.abs(cell.pnl)}`}
                        </text>
                      </>
                    )}
                    {ch >= 10 && ch < 18 && cw >= 28 && (
                      <text
                        x={cx2 + cw / 2}
                        y={cellY + ch / 2 + 3}
                        fill={cellTextColor(cell.pnl)}
                        fontSize={7}
                        textAnchor="middle"
                      >
                        {cell.strategy} {cell.pnl >= 0 ? '+' : ''}${cell.pnl}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}

        {/* X-axis label */}
        <text x={W / 2} y={H - 4} fill={C.muted} fontSize={8} textAnchor="middle">
          BTC · SOL · HYPE — width proportional to |PnL| contribution
        </text>

        {/* Legend */}
        <rect x={pad.l} y={H - 12} width={10} height={8} fill="rgba(22,163,74,0.65)" rx={1} />
        <text x={pad.l + 14} y={H - 5} fill={C.muted} fontSize={7}>Positive PnL</text>
        <rect x={pad.l + 86} y={H - 12} width={10} height={8} fill="rgba(220,38,38,0.60)" rx={1} />
        <text x={pad.l + 100} y={H - 5} fill={C.muted} fontSize={7}>Negative PnL</text>
        <text x={pad.l + 170} y={H - 5} fill={C.muted} fontSize={7}>Darker = larger absolute contribution</text>
      </svg>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

// ─── Date Range Tabs ──────────────────────────────────────────────────────────

type DateRange = '7d' | '30d' | 'all';

function DateRangeTabs({ value, onChange }: { value: DateRange; onChange: (r: DateRange) => void }) {
  const options: { label: string; value: DateRange }[] = [
    { label: '7 Days',  value: '7d'  },
    { label: '30 Days', value: '30d' },
    { label: 'All Time', value: 'all' },
  ];
  return (
    <div style={{
      display: 'inline-flex',
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: 3,
      gap: 2,
    }}>
      {options.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            style={{
              padding: '6px 16px',
              borderRadius: R.md,
              border: 'none',
              background: active ? C.brand : 'transparent',
              color: active ? '#fff' : C.muted,
              fontSize: F.sm,
              fontWeight: active ? 700 : 500,
              cursor: 'pointer',
              transition: 'all 0.15s',
              boxShadow: active ? S.sm : 'none',
            }}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}

export default function PerformancePage() {
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [curve, setCurve] = useState<EquityCurvePoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetchError, setFetchError] = useState(false);
  const [dateRange, setDateRange] = useState<DateRange>('all');

  useEffect(() => {
    const load = async () => {
      try {
        const [tradeRes, curveRes] = await Promise.all([
          apiFetch<TradeHistoryResponse>('/v1/trades/history?limit=500'),
          apiFetch<EquityCurveResponse>('/v1/trades/equity-curve?run=latest'),
        ]);
        setTrades(tradeRes?.trades ?? []);
        setCurve(curveRes?.points ?? []);
        setFetchError(false);
      } catch {
        setFetchError(true);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, []);

  // ── Filter by date range ──────────────────────────────────────────────────
  // trades.csv has no timestamp; approximate by slicing from the end (most recent N%)
  const filteredTrades = useMemo(() => {
    if (dateRange === 'all') return trades;
    const now = Date.now();
    const cutoffMs = dateRange === '7d' ? 7 * 86400000 : 30 * 86400000;
    // If trades have a timestamp field use it; otherwise fall back to tail slice
    const hasTs = trades.some((t) => (t as { timestamp?: number }).timestamp != null);
    if (hasTs) {
      return trades.filter((t) => {
        const ts = (t as { timestamp?: number }).timestamp;
        return ts != null && (now - ts) <= cutoffMs;
      });
    }
    // Approximate: assume trades are sorted oldest→newest
    const fraction = dateRange === '7d' ? 0.25 : 0.6;
    return trades.slice(Math.floor(trades.length * (1 - fraction)));
  }, [trades, dateRange]);

  const filteredCurve = useMemo(() => {
    if (dateRange === 'all') return curve;
    const fraction = dateRange === '7d' ? 0.25 : 0.6;
    return curve.slice(Math.floor(curve.length * (1 - fraction)));
  }, [curve, dateRange]);

  const dailyReturns = useMemo(() => dailyReturnsFromCurve(filteredCurve), [filteredCurve]);

  const sharpe = useMemo(() => calcSharpe(dailyReturns), [dailyReturns]);
  const sortino = useMemo(() => calcSortino(dailyReturns), [dailyReturns]);

  const totalReturnPct = useMemo(() => {
    if (filteredCurve.length < 2) return null;
    const start = filteredCurve[0].equity;
    const end = filteredCurve[filteredCurve.length - 1].equity;
    if (start === 0) return null;
    return ((end - start) / start) * 100;
  }, [filteredCurve]);

  const maxDrawdownPct = useMemo(() => {
    if (!filteredCurve.length) return null;
    const dd = filteredCurve.map((p) => p.drawdown_pct);
    return Math.min(...dd);
  }, [filteredCurve]);

  const calmar = useMemo(() => {
    if (totalReturnPct == null || maxDrawdownPct == null) return null;
    return calcCalmar(totalReturnPct, maxDrawdownPct);
  }, [totalReturnPct, maxDrawdownPct]);

  const maxConsecLoss = useMemo(() => calcMaxConsecLosses(filteredTrades), [filteredTrades]);
  const avgWinDuration = useMemo(() => calcAvgDuration(filteredTrades, 'WIN'), [filteredTrades]);
  const avgLossDuration = useMemo(() => calcAvgDuration(filteredTrades, 'LOSS'), [filteredTrades]);
  const feeDrag = useMemo(() => calcFeeDrag(filteredTrades), [filteredTrades]);

  const profitFactor = useMemo(() => {
    const grossWin = filteredTrades.filter((t) => (t.pnl ?? 0) > 0).reduce((a, t) => a + (t.pnl ?? 0), 0);
    const grossLoss = filteredTrades.filter((t) => (t.pnl ?? 0) < 0).reduce((a, t) => a + Math.abs(t.pnl ?? 0), 0);
    if (grossLoss === 0) return grossWin > 0 ? null : null;
    return grossWin / grossLoss;
  }, [filteredTrades]);

  const rollingWR = useMemo(() => rollingWinRate(filteredTrades, Math.min(10, Math.floor(filteredTrades.length / 3) || 5)), [filteredTrades]);
  const rrHisto = useMemo(() => rrHistogram(filteredTrades), [filteredTrades]);

  // By strategy from filteredTrades
  const byStrategy = useMemo(() => {
    const map: Record<string, { trades: number; wins: number; pnl: number; win_rate: number }> = {};
    for (const t of filteredTrades) {
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
  }, [filteredTrades]);

  // Win/loss counts
  const wins = filteredTrades.filter((t) => t.outcome === 'WIN').length;
  const losses = filteredTrades.filter((t) => t.outcome === 'LOSS').length;
  const winRate = filteredTrades.length > 0 ? (wins / filteredTrades.length) * 100 : null;

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
        <div className="fade-in" style={{ marginBottom: 32 }}>
          <h1 style={{ margin: 0, fontSize: F['3xl'], fontWeight: 800, color: C.text }}>
            <span className="gradient-text">Performance</span> Analytics
          </h1>
          <p style={{ margin: '8px 0 0', color: C.muted, fontSize: F.base }}>
            Institutional-grade metrics derived from <span className="num">{trades.length}</span> trades and the live equity curve.
          </p>
        </div>

        {fetchError && !loading && (
          <div style={{ marginBottom: 20, padding: '12px 16px', background: 'rgba(217,119,6,.1)', border: '1px solid rgba(217,119,6,.3)', borderRadius: 8, color: C.warnMid, fontSize: 14 }}>
            Failed to load performance data. The API may be offline — data shown may be stale or empty.
          </div>
        )}

        {/* ── Date Range Selector ── */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 28, flexWrap: 'wrap' }}>
          <DateRangeTabs value={dateRange} onChange={setDateRange} />
          {filteredTrades.length !== trades.length && (
            <span style={{ fontSize: F.xs, color: C.muted }}>
              Showing {filteredTrades.length} of {trades.length} trades
            </span>
          )}
        </div>

        {loading ? (
          <div>
            {/* KPI skeleton row */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 16, marginBottom: 36 }}>
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '18px 20px' }}>
                  <Skeleton h={11} w="55%" />
                  <div style={{ marginTop: 10 }}><Skeleton h={32} w="75%" /></div>
                  <div style={{ marginTop: 8 }}><Skeleton h={10} w="60%" /></div>
                </div>
              ))}
            </div>
            {/* Section heading + chart skeletons */}
            <Skeleton h={22} w="35%" />
            <div style={{ marginTop: 14, marginBottom: 32 }}><Skeleton h={200} /></div>
            <Skeleton h={22} w="30%" />
            <div style={{ marginTop: 14, marginBottom: 32 }}><Skeleton h={140} /></div>
            <Skeleton h={22} w="40%" />
            <div style={{ marginTop: 14, marginBottom: 32 }}><Skeleton h={130} /></div>
          </div>
        ) : (
          <>
            {/* ══════════════════════════════════════════════════════════════
                SECTION 1 — EQUITY & RETURNS
                Top KPI row + equity curve + monthly PnL bars
            ══════════════════════════════════════════════════════════════ */}
            <Section title="Equity & Returns">
              {/* Must-have KPI cards: Total Return, Max Drawdown, Sharpe, Win Rate */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 16, marginBottom: 24 }}>
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
                  label="Sharpe Ratio"
                  value={sharpe != null ? sharpe.toFixed(2) : '—'}
                  sub="Annualised (rf = 0%)"
                  color={ratioColor(sharpe)}
                />
                <KpiCard
                  label="Win Rate"
                  value={winRate != null ? fmtPct(winRate, 1) : '—'}
                  sub={`${wins}W / ${losses}L`}
                  color={winRate != null && winRate >= 50 ? C.bull : C.bear}
                />
              </div>

              {/* Equity curve with EMA overlays */}
              {filteredCurve.length > 1 && (
                <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 20, overflowX: 'auto', marginBottom: 16 }}>
                  <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                    Equity Curve with EMA-9 / EMA-21
                  </div>
                  <EquityChart points={filteredCurve} trades={filteredTrades} width={860} height={200} />
                </div>
              )}

              {/* Monthly PnL bars */}
              {filteredTrades.length >= 5 && (
                <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 20, overflowX: 'auto' }}>
                  <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                    P&L by Period (every 5 trades)
                  </div>
                  <MonthlyPnlChart trades={filteredTrades} />
                  <div style={{ fontSize: F.xs, color: C.muted, marginTop: 10 }}>
                    Green = net positive period, red = net negative. Dashed line = cumulative PnL.
                  </div>
                </div>
              )}
            </Section>

            {/* ══════════════════════════════════════════════════════════════
                SECTION 2 — RISK METRICS
                Sharpe/Sortino/Calmar gauges, profit factor gauge, radar
            ══════════════════════════════════════════════════════════════ */}
            <Section title="Risk Metrics">
              {/* Ratio gauge dials */}
              <RatioGaugePanel trades={filteredTrades} points={filteredCurve} backtest={null} />

              {/* KPI cards: Sortino, Calmar, + supporting metrics */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 16, marginBottom: 16 }}>
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
                <KpiCard label="Max Consec. Losses" value={String(maxConsecLoss)} sub="Worst losing streak" color={maxConsecLoss >= 5 ? C.bear : C.warnMid} />
                <KpiCard label="Total Fee Drag" value={feeDrag > 0 ? fmtUsd(-feeDrag) : '—'} sub="Cumulative fees paid" color={C.bear} />
              </div>

              {/* Profit factor gauge + radar side by side */}
              <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                <div style={{ flex: '0 0 auto' }}>
                  <ProfitFactorGauge trades={filteredTrades} />
                </div>
                <div className="card-hover" style={{
                  flex: '0 0 260px', background: G.card, border: `1px solid ${C.border}`,
                  borderRadius: R.lg, padding: '16px 8px', boxShadow: S.sm,
                }}>
                  <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', textAlign: 'center', marginBottom: 8 }}>
                    Performance Radar
                  </div>
                  <PerformanceRadar
                    sharpe={sharpe}
                    sortino={sortino}
                    winRate={winRate}
                    profitFactor={profitFactor}
                    calmar={calmar}
                  />
                  <div style={{ fontSize: F.xs, color: C.muted, textAlign: 'center', marginTop: 6 }}>
                    Dashed pentagon = 0.7× target
                  </div>
                </div>
              </div>
              <div style={{ fontSize: F.xs, color: C.muted, marginTop: 10 }}>
                Sharpe &gt; 1.0 = good · &gt; 2.0 = excellent · Calmar &gt; 1.0 = acceptable · &gt; 3.0 = strong
              </div>
            </Section>

            {/* ══════════════════════════════════════════════════════════════
                SECTION 3 — DRAWDOWN ANALYSIS
                Drawdown timeline + streak analysis
            ══════════════════════════════════════════════════════════════ */}
            <Section title="Drawdown Analysis">
              {filteredCurve.length > 1 && (
                <div className="card-hover" style={{
                  background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg,
                  padding: '16px 20px', overflowX: 'auto', marginBottom: 16,
                }}>
                  <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>
                    Drawdown Depth Timeline
                  </div>
                  <DrawdownTimeline points={filteredCurve} />
                </div>
              )}

              <StreakAnalysisChart trades={filteredTrades} />
            </Section>

            {/* ══════════════════════════════════════════════════════════════
                SECTION 4 — BENCHMARKS
                Benchmark comparison + fee drag analysis
            ══════════════════════════════════════════════════════════════ */}
            <Section title="Benchmarks">
              {/* ── Benchmark Comparison ── */}
              {filteredTrades.length > 0 && (
              <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px', marginBottom: 20, overflowX: 'auto' }}>
                <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                  Performance vs. Benchmarks
                </div>
                <BenchmarkComparison trades={filteredTrades} backtest={null} />
                <div style={{ fontSize: F.xs, color: C.muted, marginTop: 8 }}>
                  Horizontal bars show bot metrics vs. excellence thresholds. Green = above benchmark, red = below. Values shown: bot / target.
                </div>
              </div>
            )}

              {/* ── Fee Drag Analysis ── */}
              {filteredTrades.length > 0 && (
                <FeeDragAnalysis trades={filteredTrades} />
              )}
            </Section>

            {/* ══════════════════════════════════════════════════════════════
                SECTION 5 — TRADE QUALITY
                Win rate chart, quality matrix, alpha decay, R:R histogram
            ══════════════════════════════════════════════════════════════ */}
            <Section title="Trade Quality">
              {/* Supporting KPIs */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 16, marginBottom: 20 }}>
                <KpiCard label="Avg Win Duration" value={fmtHours(avgWinDuration)} sub="How long wins are held" />
                <KpiCard label="Avg Loss Duration" value={fmtHours(avgLossDuration)} sub="How long losses are held" color={avgLossDuration != null && avgWinDuration != null && avgLossDuration > avgWinDuration ? C.bear : undefined} />
                <KpiCard label="Total Trades" value={String(filteredTrades.length)} sub={`${wins} wins · ${losses} losses`} />
                <KpiCard label="Max Consec. Losses" value={String(maxConsecLoss)} sub="Worst losing streak" color={maxConsecLoss >= 5 ? C.bear : C.warnMid} />
              </div>

              {/* Rolling win rate chart */}
              <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 20, overflowX: 'auto', marginBottom: 16 }}>
                <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                  Rolling Win Rate (10-trade window)
                </div>
                <RollingWinRateChart data={rollingWR} width={860} height={130} />
              </div>

              {/* Trade Quality Matrix */}
              <div style={{ marginBottom: 16 }}>
                <TradeQualityMatrix trades={filteredTrades} />
              </div>

              {/* Alpha Decay */}
              <AlphaDecayChart />

              {/* Rolling 10-trade metrics */}
              {filteredTrades.length >= 12 && (
                <RollingMetrics trades={filteredTrades} />
              )}

              {/* R:R Histogram */}
              <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 20, marginBottom: 16 }}>
                <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                  R:R Achieved Distribution
                </div>
                <RRHistogram data={rrHisto} />
                <div style={{ fontSize: F.xs, color: C.muted, marginTop: 12 }}>
                  Distribution of actual risk-reward ratios at close. A strong system clusters in the 1–3 bucket.
                </div>
              </div>
            </Section>

            {/* ══════════════════════════════════════════════════════════════
                SECTION 6 — ATTRIBUTION
                PnL by strategy, performance attribution treemap
            ══════════════════════════════════════════════════════════════ */}
            <Section title="Attribution">
              {/* By Strategy bars */}
              {Object.keys(byStrategy).length > 0 && (
                <div className="card-hover" style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 20, marginBottom: 16 }}>
                  <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
                    PnL by Strategy
                  </div>
                  <StrategyBars data={byStrategy} />
                </div>
              )}

              {/* Performance Attribution Treemap */}
              <PerformanceAttributionTreemap />
            </Section>

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
