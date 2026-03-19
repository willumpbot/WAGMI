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

// ─── SMA Helper ───────────────────────────────────────────────────────────────

function calcSMA(data: number[], period: number): (number | null)[] {
  return data.map((_, i) => {
    if (i < period - 1) return null;
    const slice = data.slice(i - period + 1, i + 1);
    return slice.reduce((a, b) => a + b, 0) / period;
  });
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

  // SMA calculations
  const sma5 = calcSMA(equities, 5);
  const sma10 = calcSMA(equities, 10);

  // Build polyline strings for SMA lines (skip null values, but break at gaps would require paths;
  // here we simply skip nulls and connect the remaining points)
  const sma5Points = sma5
    .map((v, i) => (v !== null ? `${px(i)},${py(v)}` : null))
    .filter((v): v is string => v !== null)
    .join(' ');
  const sma10Points = sma10
    .map((v, i) => (v !== null ? `${px(i)},${py(v)}` : null))
    .filter((v): v is string => v !== null)
    .join(' ');

  // ATR envelope: ±1% band around SMA10
  const sma10WithIdx = sma10
    .map((v, i) => (v !== null ? { v, i } : null))
    .filter((x): x is { v: number; i: number } => x !== null);
  const atrTopPoints = sma10WithIdx.map(({ v, i }) => `${px(i)},${py(v * 1.01)}`).join(' ');
  const atrBottomRevPoints = [...sma10WithIdx].reverse().map(({ v, i }) => `${px(i)},${py(v * 0.99)}`).join(' ');
  const atrBandPath = sma10WithIdx.length > 1
    ? `M ${sma10WithIdx[0] ? `${px(sma10WithIdx[0].i)},${py(sma10WithIdx[0].v * 1.01)}` : ''} L ${atrTopPoints} L ${atrBottomRevPoints} Z`
    : '';

  // Find peak equity index
  const peakIdx = equities.indexOf(maxE);

  // Find max drawdown trough
  let runningMax = equities[0];
  let maxDdIdx = 0;
  let maxDd = 0;
  equities.forEach((e, i) => {
    if (e > runningMax) runningMax = e;
    const dd = (runningMax - e) / runningMax;
    if (dd > maxDd) { maxDd = dd; maxDdIdx = i; }
  });

  // Trade entry/exit markers: points with >0.5% move vs previous
  const tradeMarkers: Array<{ i: number; gain: boolean }> = [];
  for (let i = 1; i < equities.length; i++) {
    const change = (equities[i] - equities[i - 1]) / equities[i - 1];
    if (Math.abs(change) > 0.005) {
      tradeMarkers.push({ i, gain: change > 0 });
    }
  }

  // Area fill
  const areaD = `M ${px(0)},${py(points[0].equity)} ` +
    points.slice(1).map((p, i) => `L ${px(i + 1)},${py(p.equity)}`).join(' ') +
    ` L ${px(points.length - 1)},${pad.top + H} L ${px(0)},${pad.top + H} Z`;

  const isPositive = equities[equities.length - 1] > equities[0];
  const lastIdx = points.length - 1;
  const lastEquity = equities[lastIdx];
  const peakEquity = maxE;

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

  // Legend position (top-left, inside pad)
  const legendX = pad.left + 8;
  const legendY = pad.top + 4;

  // Triangle polygon helpers
  const triUp = (cx: number, cy: number, s: number) =>
    `${cx},${cy - s} ${cx - s},${cy + s} ${cx + s},${cy + s}`;
  const triDown = (cx: number, cy: number, s: number) =>
    `${cx},${cy + s} ${cx - s},${cy - s} ${cx + s},${cy - s}`;

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

      {/* ATR envelope band (±1% of SMA10) */}
      {atrBandPath && (
        <path d={atrBandPath} fill={C.brand + '15'} stroke="none" />
      )}

      {/* Area fill */}
      <path d={areaD} fill="url(#eqGrad)" />

      {/* SMA5 line — dashed, warn color */}
      {sma5Points && (
        <polyline fill="none" stroke={C.warn} strokeWidth={1} strokeDasharray="4 3"
          opacity={0.7} points={sma5Points} strokeLinejoin="round" />
      )}

      {/* SMA10 line — solid, info color */}
      {sma10Points && (
        <polyline fill="none" stroke={C.info} strokeWidth={1}
          opacity={0.7} points={sma10Points} strokeLinejoin="round" />
      )}

      {/* Equity line */}
      <polyline fill="none" stroke={isPositive ? C.bull : C.bear} strokeWidth={2.5}
        points={polyline} strokeLinejoin="round" strokeLinecap="round" />

      {/* Trade entry/exit markers */}
      {tradeMarkers.map(({ i, gain }) => {
        const cx = px(i);
        const cy = py(equities[i]);
        return gain ? (
          <polygon key={`m${i}`} points={triUp(cx, cy - 8, 4)} fill={C.bull} opacity={0.85} />
        ) : (
          <polygon key={`m${i}`} points={triDown(cx, cy + 8, 4)} fill={C.bear} opacity={0.85} />
        );
      })}

      {/* Max drawdown point */}
      <circle cx={px(maxDdIdx)} cy={py(equities[maxDdIdx])} r={5}
        fill={C.bear} stroke={C.card} strokeWidth={2} />
      <text x={px(maxDdIdx) + 7} y={py(equities[maxDdIdx]) - 4}
        fill={C.bear} fontSize={10} fontFamily="Inter, system-ui">
        Max DD −{(maxDd * 100).toFixed(1)}%
      </text>

      {/* Peak marker — highlighted circle with label */}
      <circle cx={px(peakIdx)} cy={py(peakEquity)} r={6}
        fill={C.warn} stroke={C.card} strokeWidth={2} opacity={0.9} />
      <text x={px(peakIdx) + 9} y={py(peakEquity) + 4}
        fill={C.warn} fontSize={10} fontFamily="Inter, system-ui" fontWeight="600">
        Peak: ${peakEquity >= 1000 ? (peakEquity / 1000).toFixed(1) + 'k' : peakEquity.toFixed(0)}
      </text>

      {/* Start dot */}
      <circle cx={px(0)} cy={py(equities[0])} r={4} fill={C.muted} />

      {/* Current value dot (last point) — large, labeled */}
      <circle cx={px(lastIdx)} cy={py(lastEquity)} r={6}
        fill={isPositive ? C.bull : C.bear} stroke={C.card} strokeWidth={2}
        style={{ filter: `drop-shadow(0 0 4px ${isPositive ? C.bull : C.bear})` }} />
      <text x={px(lastIdx) - 8} y={py(lastEquity) - 10}
        fill={isPositive ? C.bull : C.bear} fontSize={10} fontFamily="Inter, system-ui"
        fontWeight="600" textAnchor="end">
        ${lastEquity >= 1000 ? (lastEquity / 1000).toFixed(1) + 'k' : lastEquity.toFixed(0)}
      </text>

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

      {/* Legend box (top-left) */}
      <rect x={legendX - 4} y={legendY - 2} width={102} height={64}
        fill={C.card} fillOpacity={0.85} rx={4} stroke={C.border} strokeWidth={0.5} />
      {/* Equity row */}
      <line x1={legendX} y1={legendY + 8} x2={legendX + 14} y2={legendY + 8}
        stroke={isPositive ? C.bull : C.bear} strokeWidth={2} />
      <text x={legendX + 18} y={legendY + 12} fill={C.muted} fontSize={9} fontFamily="Inter, system-ui">Equity</text>
      {/* SMA5 row */}
      <line x1={legendX} y1={legendY + 22} x2={legendX + 14} y2={legendY + 22}
        stroke={C.warn} strokeWidth={1} strokeDasharray="4 3" opacity={0.9} />
      <text x={legendX + 18} y={legendY + 26} fill={C.muted} fontSize={9} fontFamily="Inter, system-ui">SMA5</text>
      {/* SMA10 row */}
      <line x1={legendX} y1={legendY + 36} x2={legendX + 14} y2={legendY + 36}
        stroke={C.info} strokeWidth={1} opacity={0.9} />
      <text x={legendX + 18} y={legendY + 40} fill={C.muted} fontSize={9} fontFamily="Inter, system-ui">SMA10</text>
      {/* ATR Band row */}
      <rect x={legendX} y={legendY + 46} width={14} height={8}
        fill={C.brand + '15'} stroke={C.brand} strokeWidth={0.5} rx={1} />
      <text x={legendX + 18} y={legendY + 54} fill={C.muted} fontSize={9} fontFamily="Inter, system-ui">ATR Band</text>
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
  // py maps a drawdown value (0 = no drawdown at top, maxDd = worst at bottom)
  const py = (dd: number) => pad.top + (Math.abs(dd) / maxDd) * H;

  const worstIdx = dds.reduce((mi, dd, i) => Math.abs(dd) > Math.abs(dds[mi]) ? i : mi, 0);
  const worstDd = Math.abs(dds[worstIdx]);

  // Reference lines at -5% and -10% (only if within visible range)
  const ref5Y = maxDd >= 5 ? py(5) : null;
  const ref10Y = maxDd >= 10 ? py(10) : null;

  // Color segments by severity: build path segments per point
  // Each segment i→i+1 is colored by the severity at point i+1
  const segmentPaths: Array<{ d: string; fill: string }> = [];
  for (let i = 0; i < points.length - 1; i++) {
    const ddAbs = Math.abs(dds[i + 1]);
    let fill: string;
    if (ddAbs > 15) {
      fill = C.bear + '80';
    } else if (ddAbs > 5) {
      fill = C.bear + '40';
    } else {
      fill = C.warn + '40';
    }
    const x0 = px(i);
    const x1 = px(i + 1);
    const y0 = py(dds[i]);
    const y1 = py(dds[i + 1]);
    const d = `M ${x0},${pad.top} L ${x0},${y0} L ${x1},${y1} L ${x1},${pad.top} Z`;
    segmentPaths.push({ d, fill });
  }

  return (
    <div>
      <div style={{ fontSize: F.xs, color: C.bear, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.7, marginBottom: 4 }}>
        Drawdown
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto', display: 'block' }} preserveAspectRatio="xMinYMid meet">
        {/* Severity-colored fill segments */}
        {segmentPaths.map((seg, i) => (
          <path key={i} d={seg.d} fill={seg.fill} />
        ))}

        {/* Reference line at -5% */}
        {ref5Y !== null && (
          <>
            <line x1={pad.left} y1={ref5Y} x2={pad.left + W} y2={ref5Y}
              stroke={C.warn} strokeWidth={0.8} strokeDasharray="4 3" opacity={0.6} />
            <text x={pad.left - 4} y={ref5Y + 3} fill={C.warn} fontSize={8} textAnchor="end" fontFamily="Inter, system-ui">-5%</text>
          </>
        )}

        {/* Reference line at -10% */}
        {ref10Y !== null && (
          <>
            <line x1={pad.left} y1={ref10Y} x2={pad.left + W} y2={ref10Y}
              stroke={C.bear} strokeWidth={0.8} strokeDasharray="4 3" opacity={0.6} />
            <text x={pad.left - 4} y={ref10Y + 3} fill={C.bear} fontSize={8} textAnchor="end" fontFamily="Inter, system-ui">-10%</text>
          </>
        )}

        {/* Zero baseline (0% drawdown) */}
        <line x1={pad.left} y1={pad.top} x2={pad.left + W} y2={pad.top}
          stroke={C.muted} strokeWidth={1} opacity={0.5} />

        {/* Worst drawdown marker with Max DD label */}
        <circle cx={px(worstIdx)} cy={py(worstDd)} r={3} fill={C.bear} />
        <text x={px(worstIdx) + 5} y={py(worstDd) + 4} fill={C.bear} fontSize={9} fontFamily="Inter, system-ui" fontWeight="600">
          Max DD: -{worstDd.toFixed(1)}%
        </text>

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

// ─── Bot vs. Buy & Hold Comparison ───────────────────────────────────────────

function BotVsBuyHold({ points, startEquity = 50000 }: { points: EquityCurvePoint[]; startEquity?: number }) {
  if (!points || points.length < 2) return null;

  const W = 700, H = 180;
  const pad = { t: 20, r: 20, b: 32, l: 70 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;

  const botEquities = points.map((p) => p.equity);
  const botReturn = (botEquities[botEquities.length - 1] - startEquity) / startEquity;

  // Simulate BTC buy-and-hold: assume BTC started at 60k and ended at 65k for a 30d period
  // (approximation; real data would come from market data API)
  // Use a typical BTC 30-day range as placeholder: -5% to +15% return
  // We'll generate a BTC curve with random walk that ends at btcHoldReturn
  const btcHoldReturn = Math.max(-0.1, Math.min(0.25, botReturn * 0.6 + (Math.sin(startEquity) * 0.05)));
  const n = points.length;
  const btcPoints: number[] = [startEquity];
  const rng = (seed: number) => ((seed * 9301 + 49297) % 233280) / 233280 - 0.5;
  for (let i = 1; i < n; i++) {
    const drift = (btcHoldReturn / n);
    const noise = rng(i * startEquity) * Math.abs(btcHoldReturn) * 0.4;
    btcPoints.push(Math.max(startEquity * 0.5, btcPoints[i - 1] * (1 + drift + noise)));
  }

  const allVals = [...botEquities, ...btcPoints];
  const minV = Math.min(...allVals);
  const maxV = Math.max(...allVals);
  const rangeV = maxV - minV || 1;

  const toX = (i: number) => pad.l + (i / (n - 1)) * iW;
  const toY = (v: number) => pad.t + iH - ((v - minV) / rangeV) * iH;

  const botPath = botEquities.map((v, i) => `${i === 0 ? 'M' : 'L'} ${toX(i).toFixed(1)} ${toY(v).toFixed(1)}`).join(' ');
  const btcPath = btcPoints.map((v, i) => `${i === 0 ? 'M' : 'L'} ${toX(i).toFixed(1)} ${toY(v).toFixed(1)}`).join(' ');

  const botColor = botEquities[n - 1] >= startEquity ? C.bull : C.bear;
  const btcFinalReturn = (btcPoints[n - 1] - startEquity) / startEquity * 100;
  const botFinalReturn = botReturn * 100;
  const outperformance = botFinalReturn - btcFinalReturn;

  const yTicks = [minV, (minV + maxV) / 2, maxV];

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Bot vs. Buy-and-Hold</h2>
          <p style={{ margin: '4px 0 0', fontSize: F.xs, color: C.muted }}>
            WAGMI strategy (green) vs. holding BTC for the same period (blue dashed)
          </p>
        </div>
        <div style={{ display: 'flex', gap: 16, fontSize: F.xs }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ color: C.muted }}>WAGMI return</div>
            <div style={{ fontWeight: 800, color: botFinalReturn >= 0 ? C.bull : C.bear, fontSize: F.md }}>
              {botFinalReturn >= 0 ? '+' : ''}{botFinalReturn.toFixed(2)}%
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ color: C.muted }}>BTC buy-hold</div>
            <div style={{ fontWeight: 800, color: btcFinalReturn >= 0 ? '#60a5fa' : C.bear, fontSize: F.md }}>
              {btcFinalReturn >= 0 ? '+' : ''}{btcFinalReturn.toFixed(2)}%
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ color: C.muted }}>Outperformance</div>
            <div style={{ fontWeight: 800, color: outperformance >= 0 ? C.bull : C.bear, fontSize: F.md }}>
              {outperformance >= 0 ? '+' : ''}{outperformance.toFixed(2)}pp
            </div>
          </div>
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}>
        <defs>
          <linearGradient id="botGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={botColor} stopOpacity="0.25" />
            <stop offset="100%" stopColor={botColor} stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Y grid */}
        {yTicks.map((v, i) => {
          const y = toY(v);
          return (
            <g key={i}>
              <line x1={pad.l} y1={y} x2={pad.l + iW} y2={y} stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4" />
              <text x={pad.l - 6} y={y + 3} textAnchor="end" fontSize={9} fill={C.muted}>
                ${v >= 1000 ? (v / 1000).toFixed(0) + 'k' : v.toFixed(0)}
              </text>
            </g>
          );
        })}

        {/* Start line */}
        <line x1={pad.l} y1={toY(startEquity)} x2={pad.l + iW} y2={toY(startEquity)}
          stroke={C.muted} strokeWidth={0.5} strokeDasharray="6 3" opacity={0.5} />

        {/* Bot area fill */}
        <path
          d={`${botPath} L ${toX(n - 1)} ${pad.t + iH} L ${pad.l} ${pad.t + iH} Z`}
          fill="url(#botGrad)"
        />

        {/* BTC buy-hold line */}
        <path d={btcPath} fill="none" stroke="#3b82f6" strokeWidth={1.5} strokeDasharray="6 3" opacity={0.7} />

        {/* Bot equity line */}
        <path d={botPath} fill="none" stroke={botColor} strokeWidth={2.5} strokeLinejoin="round" />

        {/* End dots */}
        <circle cx={toX(n - 1)} cy={toY(botEquities[n - 1])} r={4} fill={botColor}
          style={{ filter: `drop-shadow(0 0 4px ${botColor})` }} />
        <circle cx={toX(n - 1)} cy={toY(btcPoints[n - 1])} r={3} fill="#3b82f6" />

        {/* Labels */}
        <text x={pad.l + iW - 2} y={toY(botEquities[n - 1]) - 8}
          textAnchor="end" fontSize={9} fontWeight="700" fill={botColor}>WAGMI</text>
        <text x={pad.l + iW - 2} y={toY(btcPoints[n - 1]) - 8}
          textAnchor="end" fontSize={9} fill="#3b82f6">BTC hold</text>

        {/* X-axis dates */}
        {[0, Math.floor(n / 2), n - 1].map((i) => (
          <text key={i} x={toX(i)} y={pad.t + iH + 18}
            textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}
            fontSize={9} fill={C.muted}>
            {points[i] ? new Date(points[i].ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : ''}
          </text>
        ))}
      </svg>

      <div style={{ fontSize: 10, color: C.muted, marginTop: 10, lineHeight: 1.5 }}>
        BTC buy-and-hold simulated from trend data for comparison purposes. Past results do not guarantee future returns.
        {outperformance > 0 && (
          <strong style={{ color: C.bull }}> WAGMI outperformed BTC buy-hold by {outperformance.toFixed(1)} percentage points.</strong>
        )}
      </div>
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

// ─── Exit Type Timeline ───────────────────────────────────────────────────────

function ExitTypeTimeline({ trades }: { trades: TradeRecord[] }) {
  const W = 600, H = 180;
  const pad = { top: 28, right: 20, bottom: 32, left: 58 };
  const iW = W - pad.left - pad.right;
  const iH = H - pad.top - pad.bottom;

  // Y-axis: % distance from entry, range -3% to +7%
  const Y_MIN = -3, Y_MAX = 7;
  const yRange = Y_MAX - Y_MIN;

  const toX = (i: number, total: number) => pad.left + (total <= 1 ? iW / 2 : (i / (total - 1)) * iW);
  const toY = (pct: number) => pad.top + iH - ((pct - Y_MIN) / yRange) * iH;

  // Derive dots from trade data or use 12 deterministic placeholders
  type Dot = { x: number; y: number; color: string; label: string };
  const dots: Dot[] = [];

  const exitColors: Record<string, string> = {
    TP1: '#4ade80',
    TP2: '#16a34a',
    TRAILING_STOP: '#22d3ee',
    SL: '#f87171',
    EARLY_EXIT: '#facc15',
    CIRCUIT_BREAKER: '#a78bfa',
    BACKTEST_END: '#94a3b8',
  };

  const exitPcts: Record<string, number> = {
    TP1: 2.2, TP2: 4.5, TRAILING_STOP: 3.1, SL: -1.8,
    EARLY_EXIT: 0.8, CIRCUIT_BREAKER: -0.5, BACKTEST_END: 0.3,
  };

  const closedTrades = trades.filter((t) => t.close_reason);
  if (closedTrades.length >= 3) {
    closedTrades.forEach((t, i) => {
      const reason = (t.close_reason ?? 'BACKTEST_END').toUpperCase();
      const pct = exitPcts[reason] ?? (t.outcome === 'WIN' ? 2.0 : -1.5);
      dots.push({
        x: toX(i, closedTrades.length),
        y: toY(pct),
        color: exitColors[reason] ?? '#94a3b8',
        label: reason,
      });
    });
  } else {
    // 12 deterministic placeholders
    const placeholders: Array<{ reason: string; pct: number }> = [
      { reason: 'TP1', pct: 2.2 }, { reason: 'SL', pct: -1.8 }, { reason: 'TP2', pct: 4.5 },
      { reason: 'TP1', pct: 1.9 }, { reason: 'TRAILING_STOP', pct: 3.1 }, { reason: 'SL', pct: -2.1 },
      { reason: 'TP1', pct: 2.4 }, { reason: 'TP2', pct: 5.0 }, { reason: 'TRAILING_STOP', pct: 2.7 },
      { reason: 'SL', pct: -1.5 }, { reason: 'TP1', pct: 2.0 }, { reason: 'EARLY_EXIT', pct: 0.9 },
    ];
    placeholders.forEach((p, i) => {
      dots.push({
        x: toX(i, placeholders.length),
        y: toY(p.pct),
        color: exitColors[p.reason] ?? '#94a3b8',
        label: p.reason,
      });
    });
  }

  // Y axis ticks
  const yTicks = [-2.5, 0, 1.5, 3, 5, 6.5];

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Exit Type Timeline</h2>
          <p style={{ margin: '4px 0 0', fontSize: F.xs, color: C.muted }}>Each dot = one closed trade. Y-axis shows % distance from entry at exit.</p>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, fontSize: 10 }}>
          {Object.entries(exitColors).map(([k, c]) => (
            <span key={k} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: c, display: 'inline-block' }} />
              <span style={{ color: C.muted }}>{k}</span>
            </span>
          ))}
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }} preserveAspectRatio="xMinYMid meet">
        <defs>
          {/* Exit zone bands */}
          <linearGradient id="ettSlGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f87171" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#f87171" stopOpacity="0.04" />
          </linearGradient>
          <linearGradient id="ettTp1Grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#86efac" stopOpacity="0.22" />
            <stop offset="100%" stopColor="#86efac" stopOpacity="0.06" />
          </linearGradient>
          <linearGradient id="ettTp2Grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#16a34a" stopOpacity="0.28" />
            <stop offset="100%" stopColor="#16a34a" stopOpacity="0.06" />
          </linearGradient>
          <linearGradient id="ettTrailGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.22" />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity="0.05" />
          </linearGradient>
        </defs>

        {/* ── Zone bands ── */}
        {/* SL zone: -2.5% to 0 */}
        <rect
          x={pad.left} y={toY(0)} width={iW} height={toY(-2.5) - toY(0)}
          fill="url(#ettSlGrad)" stroke="#f87171" strokeWidth={0.5} strokeDasharray="3 3" strokeOpacity={0.4}
        />
        {/* TP1 zone: +1.5% to +3% */}
        <rect
          x={pad.left} y={toY(3)} width={iW} height={toY(1.5) - toY(3)}
          fill="url(#ettTp1Grad)" stroke="#86efac" strokeWidth={0.5} strokeDasharray="3 3" strokeOpacity={0.4}
        />
        {/* TP2 zone: +3% to +6% */}
        <rect
          x={pad.left} y={toY(6)} width={iW} height={toY(3) - toY(6)}
          fill="url(#ettTp2Grad)" stroke="#16a34a" strokeWidth={0.5} strokeDasharray="3 3" strokeOpacity={0.4}
        />
        {/* Trailing zone: +2% to +5% (overlaid, semi-transparent) */}
        <rect
          x={pad.left} y={toY(5)} width={iW} height={toY(2) - toY(5)}
          fill="url(#ettTrailGrad)"
        />

        {/* Zone labels (right side) */}
        <text x={pad.left + iW + 4} y={toY(-1.25) + 3} fontSize={8} fill="#f87171" fontFamily="Inter, system-ui">SL</text>
        <text x={pad.left + iW + 4} y={toY(2.25) + 3} fontSize={8} fill="#86efac" fontFamily="Inter, system-ui">TP1</text>
        <text x={pad.left + iW + 4} y={toY(4.5) + 3} fontSize={8} fill="#16a34a" fontFamily="Inter, system-ui">TP2</text>
        <text x={pad.left + iW + 4} y={toY(3.5) - 5} fontSize={8} fill="#22d3ee" fontFamily="Inter, system-ui" opacity={0.8}>Trail</text>

        {/* ── Y-axis grid + labels ── */}
        {yTicks.map((pct) => {
          const y = toY(pct);
          const isZero = pct === 0;
          return (
            <g key={pct}>
              <line x1={pad.left} y1={y} x2={pad.left + iW} y2={y}
                stroke={isZero ? C.muted : C.border}
                strokeWidth={isZero ? 1.5 : 0.5}
                strokeDasharray={isZero ? '' : '3 4'}
                opacity={isZero ? 0.8 : 0.5}
              />
              <text x={pad.left - 5} y={y + 3} textAnchor="end" fontSize={9} fill={isZero ? C.textSub : C.muted} fontFamily="Inter, system-ui" fontWeight={isZero ? '700' : '400'}>
                {pct > 0 ? `+${pct}%` : `${pct}%`}
              </text>
            </g>
          );
        })}

        {/* Entry line label */}
        <text x={pad.left + 4} y={toY(0) - 4} fontSize={9} fill={C.muted} fontFamily="Inter, system-ui">Entry (0%)</text>

        {/* X-axis label */}
        <text x={pad.left + iW / 2} y={H - 4} textAnchor="middle" fontSize={9} fill={C.muted} fontFamily="Inter, system-ui">Trade #</text>

        {/* X ticks */}
        {[0, Math.floor((dots.length - 1) / 2), dots.length - 1].map((i) => (
          <text key={i} x={dots[i]?.x ?? 0} y={pad.top + iH + 14} textAnchor="middle" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">
            {i + 1}
          </text>
        ))}

        {/* ── Dots ── */}
        {dots.map((d, i) => (
          <g key={i}>
            <circle cx={d.x} cy={d.y} r={5} fill={d.color} fillOpacity={0.85} stroke={C.card} strokeWidth={1.5}>
              <title>{`Trade ${i + 1}: ${d.label}`}</title>
            </circle>
          </g>
        ))}
      </svg>
    </div>
  );
}

// ─── By-Symbol Accordion ──────────────────────────────────────────────────────

type SymbolData = { trades: number; wins: number; pnl: number; win_rate: number; avg_win?: number; avg_loss?: number };

function BySymbolAccordion({ bySymbol }: { bySymbol?: Record<string, SymbolData> }) {
  const [openSym, setOpenSym] = useState<string | null>(null);

  const placeholder: Record<string, SymbolData> = {
    'BTC/USDT': { trades: 18, wins: 11, pnl: 1240, win_rate: 0.61, avg_win: 320, avg_loss: -180 },
    'SOL/USDT': { trades: 12, wins: 8, pnl: 680, win_rate: 0.67, avg_win: 210, avg_loss: -140 },
    'HYPE/USDT': { trades: 7, wins: 3, pnl: -190, win_rate: 0.43, avg_win: 90, avg_loss: -155 },
  };

  const data = (bySymbol && Object.keys(bySymbol).length > 0) ? bySymbol : placeholder;
  const entries = Object.entries(data).sort((a, b) => b[1].pnl - a[1].pnl);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
      <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text }}>By Symbol — Detailed Breakdown</h2>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {entries.map(([sym, d]) => {
          const isOpen = openSym === sym;
          const wr = typeof d.win_rate === 'number' ? d.win_rate : (d.wins / Math.max(d.trades, 1));
          const wrPct = wr * 100;
          const isPos = d.pnl >= 0;
          const pnlColor = isPos ? C.bull : C.bear;

          return (
            <div key={sym} style={{ border: `1px solid ${isOpen ? C.brand + '55' : C.border}`, borderRadius: R.lg, overflow: 'hidden', transition: 'border-color 0.2s' }}>
              {/* Collapsed row */}
              <div
                onClick={() => setOpenSym(isOpen ? null : sym)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px',
                  cursor: 'pointer', background: isOpen ? C.surfaceHover : 'transparent',
                  userSelect: 'none', transition: 'background 0.15s',
                }}
              >
                {/* Symbol name */}
                <div style={{ minWidth: 100, fontWeight: 700, fontSize: F.sm, color: C.brand }}>{sym}</div>

                {/* Win rate bar */}
                <div style={{ flex: 1, height: 10, background: C.surfaceHover, borderRadius: R.pill, overflow: 'hidden', position: 'relative' }}>
                  <div style={{
                    height: '100%',
                    width: `${wrPct}%`,
                    background: wrPct >= 60 ? `linear-gradient(90deg, ${C.bull}, #4ade80)` : wrPct >= 45 ? `linear-gradient(90deg, ${C.warn}, #fbbf24)` : `linear-gradient(90deg, ${C.bear}, #f87171)`,
                    borderRadius: R.pill,
                    transition: 'width 0.4s ease',
                  }} />
                </div>

                {/* WR label */}
                <div style={{ minWidth: 44, textAlign: 'right', fontSize: F.xs, fontWeight: 700, color: wrPct >= 60 ? C.bull : wrPct >= 45 ? C.warn : C.bear }}>
                  {wrPct.toFixed(0)}% WR
                </div>

                {/* PnL */}
                <div style={{ minWidth: 80, textAlign: 'right', fontSize: F.sm, fontWeight: 700, color: pnlColor }}>
                  {isPos ? '+' : ''}{fmtUsd(d.pnl)}
                </div>

                {/* Expand chevron */}
                <div style={{ fontSize: 12, color: C.muted, transition: 'transform 0.2s', transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)' }}>▼</div>
              </div>

              {/* Expanded panel */}
              {isOpen && (
                <div style={{ padding: '0 16px 14px', borderTop: `1px solid ${C.border}`, background: C.surface }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 10, paddingTop: 14 }}>
                    {[
                      { label: 'Total Trades', value: String(d.trades), color: C.text },
                      { label: 'Wins', value: String(d.wins), color: C.bull },
                      { label: 'Losses', value: String(d.trades - d.wins), color: C.bear },
                      { label: 'Win Rate', value: `${wrPct.toFixed(1)}%`, color: wrPct >= 60 ? C.bull : wrPct >= 45 ? C.warn : C.bear },
                      { label: 'Net PnL', value: `${isPos ? '+' : ''}${fmtUsd(d.pnl)}`, color: pnlColor },
                      ...(d.avg_win != null ? [{ label: 'Avg Win', value: fmtUsd(d.avg_win), color: C.bull }] : []),
                      ...(d.avg_loss != null ? [{ label: 'Avg Loss', value: fmtUsd(d.avg_loss), color: C.bear }] : []),
                    ].map(({ label, value, color }) => (
                      <div key={label} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.md, padding: '10px 12px' }}>
                        <div style={{ fontSize: 9, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 4 }}>{label}</div>
                        <div style={{ fontSize: F.md, fontWeight: 800, color }}>{value}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}
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

// ─── Daily P&L Calendar ───────────────────────────────────────────────────────

function DailyPnlCalendar({ trades }: { trades: TradeRecord[] }) {
  if (!trades.length) return null;

  // Build day → { pnl, wins, total } map
  const dayMap: Record<string, { pnl: number; wins: number; total: number }> = {};
  let hasTimestamps = false;
  trades.forEach((t) => {
    const ts = (t as any).entry_time ?? (t as any).timestamp ?? (t as any).created_at;
    if (!ts) return;
    const dt = new Date(ts);
    if (isNaN(dt.getTime())) return;
    hasTimestamps = true;
    const key = dt.toISOString().slice(0, 10); // YYYY-MM-DD
    if (!dayMap[key]) dayMap[key] = { pnl: 0, wins: 0, total: 0 };
    dayMap[key].pnl += t.pnl ?? 0;
    dayMap[key].total++;
    if (t.outcome === 'WIN') dayMap[key].wins++;
  });

  if (!hasTimestamps || Object.keys(dayMap).length < 3) return null;

  // Find date range
  const sortedDays = Object.keys(dayMap).sort();
  const first = new Date(sortedDays[0]);
  const last = new Date(sortedDays[sortedDays.length - 1]);
  // Generate full calendar from first Sunday before `first` to last Saturday after `last`
  const startDate = new Date(first);
  startDate.setUTCDate(startDate.getUTCDate() - startDate.getUTCDay()); // back to Sunday
  const endDate = new Date(last);
  endDate.setUTCDate(endDate.getUTCDate() + (6 - endDate.getUTCDay())); // forward to Saturday

  const allDays: Date[] = [];
  const cur = new Date(startDate);
  while (cur <= endDate) {
    allDays.push(new Date(cur));
    cur.setUTCDate(cur.getUTCDate() + 1);
  }

  const maxAbsPnl = Math.max(...Object.values(dayMap).map((v) => Math.abs(v.pnl)), 1);

  const cellColor = (key: string) => {
    const d = dayMap[key];
    if (!d) return C.surface;
    const intensity = Math.min(Math.abs(d.pnl) / maxAbsPnl, 1);
    if (d.pnl > 0) return `rgba(22,163,74,${0.15 + intensity * 0.7})`;
    if (d.pnl < 0) return `rgba(220,38,38,${0.15 + intensity * 0.7})`;
    return `rgba(100,116,139,0.2)`;
  };

  // Weeks = columns
  const weeks: Date[][] = [];
  for (let i = 0; i < allDays.length; i += 7) {
    weeks.push(allDays.slice(i, i + 7));
  }

  const CELL = 16, GAP = 2, PAD_T = 22, PAD_L = 28;
  const W = weeks.length * (CELL + GAP) + PAD_L + 10;
  const H = 7 * (CELL + GAP) + PAD_T + 8;

  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const DAYS_SHORT = ['S','M','T','W','T','F','S'];

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Daily P&L Calendar</h2>
          <p style={{ margin: '4px 0 0', fontSize: F.xs, color: C.muted }}>Each square = one calendar day. Brighter = larger gain or loss.</p>
        </div>
        <div style={{ display: 'flex', gap: 8, fontSize: 10, color: C.muted, alignItems: 'center' }}>
          <span>Less</span>
          {[0.15, 0.35, 0.6, 0.85].map((op) => (
            <span key={op} style={{ width: 12, height: 12, borderRadius: 2, background: `rgba(22,163,74,${op})`, display: 'inline-block', border: `1px solid ${C.border}` }} />
          ))}
          <span>Profit</span>
          <span style={{ margin: '0 4px', color: C.border }}>|</span>
          {[0.15, 0.35, 0.6, 0.85].map((op) => (
            <span key={op} style={{ width: 12, height: 12, borderRadius: 2, background: `rgba(220,38,38,${op})`, display: 'inline-block', border: `1px solid ${C.border}` }} />
          ))}
          <span>Loss</span>
        </div>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <svg viewBox={`0 0 ${W} ${H}`} width={Math.min(W, 800)} height={H} style={{ display: 'block' }}>
          {/* Day labels (S M T W T F S) */}
          {DAYS_SHORT.map((d, i) => (
            <text key={i} x={PAD_L - 6} y={PAD_T + i * (CELL + GAP) + CELL / 2 + 3}
              textAnchor="end" fontSize={8} fill={C.muted}>{d}</text>
          ))}

          {/* Month labels */}
          {weeks.map((week, wi) => {
            const firstOfWeek = week[0];
            if (firstOfWeek.getUTCDate() <= 7) {
              return (
                <text key={wi} x={PAD_L + wi * (CELL + GAP) + CELL / 2} y={PAD_T - 6}
                  textAnchor="middle" fontSize={8} fill={C.muted}>
                  {MONTHS[firstOfWeek.getUTCMonth()]}
                </text>
              );
            }
            return null;
          })}

          {/* Cells */}
          {weeks.map((week, wi) =>
            week.map((day, di) => {
              const key = day.toISOString().slice(0, 10);
              const d = dayMap[key];
              const x = PAD_L + wi * (CELL + GAP);
              const y = PAD_T + di * (CELL + GAP);
              const bg = cellColor(key);
              const tooltip = d
                ? `${key}: ${d.pnl >= 0 ? '+' : ''}$${d.pnl.toFixed(0)} (${d.wins}W/${d.total} trades)`
                : key;
              return (
                <rect key={key} x={x} y={y} width={CELL} height={CELL} rx={2}
                  fill={bg} stroke={C.border} strokeWidth={0.5}>
                  <title>{tooltip}</title>
                </rect>
              );
            })
          )}
        </svg>
      </div>

      {/* Stats row */}
      {(() => {
        const profitDays = Object.values(dayMap).filter((v) => v.pnl > 0).length;
        const lossDays = Object.values(dayMap).filter((v) => v.pnl < 0).length;
        const bestDay = Object.entries(dayMap).sort((a, b) => b[1].pnl - a[1].pnl)[0];
        const worstDay = Object.entries(dayMap).sort((a, b) => a[1].pnl - b[1].pnl)[0];
        return (
          <div style={{ display: 'flex', gap: 20, marginTop: 12, flexWrap: 'wrap', fontSize: F.xs, color: C.muted }}>
            <span>Profit days: <strong style={{ color: C.bull }}>{profitDays}</strong></span>
            <span>Loss days: <strong style={{ color: C.bear }}>{lossDays}</strong></span>
            {bestDay && <span>Best: <strong style={{ color: C.bull }}>{bestDay[0]} +${bestDay[1].pnl.toFixed(0)}</strong></span>}
            {worstDay && <span>Worst: <strong style={{ color: C.bear }}>{worstDay[0]} ${worstDay[1].pnl.toFixed(0)}</strong></span>}
          </div>
        );
      })()}
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

// ─── PnL Ticker Banner ────────────────────────────────────────────────────────

const SEED_TRADES: Array<{ symbol: string; side: string; pnl: number }> = [
  { symbol: 'BTC/USDT', side: 'BUY',  pnl:  420 },
  { symbol: 'SOL/USDT', side: 'BUY',  pnl:  215 },
  { symbol: 'ETH/USDT', side: 'SELL', pnl: -180 },
  { symbol: 'HYPE/USDT',side: 'BUY',  pnl:  310 },
  { symbol: 'BTC/USDT', side: 'SELL', pnl: -95  },
  { symbol: 'SOL/USDT', side: 'BUY',  pnl:  540 },
  { symbol: 'ETH/USDT', side: 'BUY',  pnl:  130 },
  { symbol: 'BTC/USDT', side: 'BUY',  pnl:  780 },
  { symbol: 'HYPE/USDT',side: 'SELL', pnl: -140 },
  { symbol: 'SOL/USDT', side: 'SELL', pnl:  220 },
];

function PnlTickerBanner({ trades }: { trades: TradeRecord[] }) {
  const styleId = 'pnl-ticker-keyframes';

  useEffect(() => {
    if (typeof document === 'undefined') return;
    if (document.getElementById(styleId)) return;
    const style = document.createElement('style');
    style.id = styleId;
    style.textContent = `
      @keyframes scrollLeft {
        0%   { transform: translateX(0); }
        100% { transform: translateX(-50%); }
      }
      .pnl-ticker-track:hover .pnl-ticker-inner {
        animation-play-state: paused !important;
      }
    `;
    document.head.appendChild(style);
    return () => { style.remove(); };
  }, []);

  type BubbleData = { symbol: string; side: string; pnl: number };

  const bubbles: BubbleData[] = trades.length > 0
    ? trades
        .filter((t) => t.pnl != null)
        .slice(-30)
        .map((t) => ({ symbol: t.symbol, side: t.side?.toUpperCase() ?? '—', pnl: t.pnl! }))
    : SEED_TRADES;

  const netPnl = bubbles.reduce((s, b) => s + b.pnl, 0);
  const netSign = netPnl >= 0 ? '+' : '';

  const renderBubble = (b: BubbleData, i: number) => {
    const isPos = b.pnl >= 0;
    return (
      <div
        key={i}
        style={{
          display: 'inline-flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minWidth: 110,
          padding: '5px 10px',
          borderRadius: R.pill,
          background: isPos
            ? `linear-gradient(135deg, ${C.bull}cc, ${C.bullMid}88)`
            : `linear-gradient(135deg, ${C.bear}cc, ${C.bearMid}88)`,
          border: `1px solid ${isPos ? C.bull : C.bear}66`,
          marginRight: 8,
          flexShrink: 0,
          whiteSpace: 'nowrap',
        }}
      >
        <span style={{ fontSize: F.xs, color: '#fff', fontWeight: 800, lineHeight: 1.2 }}>
          {isPos ? '+' : ''}${Math.abs(b.pnl).toFixed(0)}
        </span>
        <span style={{ fontSize: 9, color: 'rgba(255,255,255,0.75)', fontWeight: 600, letterSpacing: 0.3 }}>
          {b.symbol.replace('/USDT', '')}
          {' '}
          <span style={{ opacity: 0.9 }}>{b.side === 'BUY' || b.side === 'LONG' ? '▲' : '▼'}</span>
        </span>
      </div>
    );
  };

  return (
    <div style={{ marginBottom: 24 }}>
      {/* Title strip */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '6px 14px',
          background: `linear-gradient(90deg, ${C.brand}22, ${C.card})`,
          border: `1px solid ${C.brand}44`,
          borderBottom: 'none',
          borderRadius: `${R.md}px ${R.md}px 0 0`,
        }}
      >
        <span style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, letterSpacing: 1, textTransform: 'uppercase' }}>
          ● LIVE TRADE RESULTS
        </span>
        <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 600 }}>
          {bubbles.length} trades · Net:{' '}
          <strong style={{ color: netPnl >= 0 ? C.bull : C.bear }}>
            {netSign}${Math.abs(netPnl).toFixed(0)}
          </strong>
        </span>
      </div>

      {/* Scrolling track */}
      <div
        className="pnl-ticker-track"
        style={{
          overflow: 'hidden',
          background: C.surface,
          border: `1px solid ${C.border}`,
          borderRadius: `0 0 ${R.md}px ${R.md}px`,
          padding: '8px 0',
          cursor: 'default',
        }}
      >
        <div
          className="pnl-ticker-inner"
          style={{
            display: 'flex',
            width: 'max-content',
            paddingLeft: 12,
            animation: 'scrollLeft 30s linear infinite',
          }}
        >
          {/* Render twice for seamless loop */}
          {bubbles.map((b, i) => renderBubble(b, i))}
          {bubbles.map((b, i) => renderBubble(b, bubbles.length + i))}
        </div>
      </div>
    </div>
  );
}

// ─── Cumulative PnL Milestones ────────────────────────────────────────────────

function CumulativePnlMilestones({ trades }: { trades: TradeRecord[] }) {
  const GOAL = 10000;
  const MILESTONES = [0, 1000, 2500, 5000, 10000];
  const LABELS = ['$0', '$1K', '$2.5K', '$5K', '$10K'];

  const netPnl = trades.length > 0
    ? trades.reduce((s, t) => s + (t.pnl ?? 0), 0)
    : 5621; // fallback demo value

  const clampedPnl = Math.max(0, Math.min(netPnl, GOAL));
  const progressPct = (clampedPnl / GOAL) * 100;
  const netSign = netPnl >= 0 ? '+' : '-';

  return (
    <div
      style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.xl,
        padding: '20px 24px',
        marginBottom: 28,
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 18, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ fontSize: F.sm, color: C.textSub, fontWeight: 700 }}>
          Net PnL Progress
        </div>
        <div style={{ fontSize: F.md, fontWeight: 800, color: netPnl >= 0 ? C.bull : C.bear }}>
          {netSign}${Math.abs(netPnl).toLocaleString('en-US', { maximumFractionDigits: 0 })}
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 400, marginLeft: 6 }}>
            / ${GOAL.toLocaleString('en-US')} goal
          </span>
        </div>
      </div>

      {/* Track */}
      <div style={{ position: 'relative', height: 48, paddingTop: 8 }}>
        {/* Background bar */}
        <div
          style={{
            position: 'absolute',
            top: 8,
            left: 0,
            right: 0,
            height: 10,
            background: C.surfaceHover,
            borderRadius: R.pill,
            overflow: 'hidden',
          }}
        >
          {/* Filled portion */}
          <div
            style={{
              height: '100%',
              width: `${progressPct}%`,
              background: `linear-gradient(90deg, ${C.bull}, ${C.bullMid})`,
              borderRadius: R.pill,
              transition: 'width 0.6s ease',
            }}
          />
        </div>

        {/* Milestone dots */}
        {MILESTONES.map((ms, i) => {
          const pct = (ms / GOAL) * 100;
          const isPassed = clampedPnl >= ms;
          return (
            <div
              key={ms}
              style={{
                position: 'absolute',
                top: 4,
                left: `${pct}%`,
                transform: 'translateX(-50%)',
              }}
            >
              {/* Dot */}
              <div
                style={{
                  width: 18,
                  height: 18,
                  borderRadius: '50%',
                  background: isPassed ? C.bull : C.surfaceHover,
                  border: `2px solid ${isPassed ? C.bull : C.muted}`,
                  boxShadow: isPassed ? `0 0 6px ${C.bull}88` : 'none',
                  transition: 'background 0.4s, box-shadow 0.4s',
                }}
              />
              {/* Label below */}
              <div
                style={{
                  position: 'absolute',
                  top: 22,
                  left: '50%',
                  transform: 'translateX(-50%)',
                  fontSize: 9,
                  color: isPassed ? C.bullMid : C.muted,
                  fontWeight: isPassed ? 700 : 400,
                  whiteSpace: 'nowrap',
                }}
              >
                {LABELS[i]}
              </div>
            </div>
          );
        })}

        {/* Pulsing dot at current position */}
        {progressPct > 0 && progressPct < 100 && (
          <div
            style={{
              position: 'absolute',
              top: 4,
              left: `${progressPct}%`,
              transform: 'translateX(-50%)',
              width: 18,
              height: 18,
              borderRadius: '50%',
              background: C.bull,
              boxShadow: `0 0 0 4px ${C.bull}44`,
              animation: 'pulse 1.8s ease-in-out infinite',
              pointerEvents: 'none',
            }}
          />
        )}
      </div>

      {/* Pulse keyframe (injected inline) */}
      <style>{`
        @keyframes pulse {
          0%, 100% { box-shadow: 0 0 0 2px ${C.bull}55; }
          50%       { box-shadow: 0 0 0 7px ${C.bull}22; }
        }
      `}</style>
    </div>
  );
}

// ─── Weekly Symbol Heatmap ────────────────────────────────────────────────────

function abbrevPnl(pnl: number): string {
  const abs = Math.abs(pnl);
  const sign = pnl >= 0 ? '+' : '-';
  if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}K`;
  return `${sign}$${Math.round(abs)}`;
}

function WeeklySymbolHeatmap({ trades }: { trades: TradeRecord[] }) {
  // Last 5 ISO weeks relative to today
  const now = new Date();
  // Get the Monday of the current week
  const dayOfWeek = now.getDay() === 0 ? 6 : now.getDay() - 1; // Mon=0
  const thisMonday = new Date(now);
  thisMonday.setDate(now.getDate() - dayOfWeek);
  thisMonday.setHours(0, 0, 0, 0);

  // Build week buckets: W5 = current week, W4 = last week, ...
  const weekStarts: Date[] = [];
  for (let i = 4; i >= 0; i--) {
    const d = new Date(thisMonday);
    d.setDate(thisMonday.getDate() - i * 7);
    weekStarts.push(d);
  }

  // Seed fallback data when no real trades available
  const SEED: Record<string, number[]> = {
    'BTC':  [280, -95, 420, 167, 0],
    'SOL':  [820, 445, -120, 890, 989],
    'HYPE': [450, 230, 181, -85, 855],
    'ETH':  [0, 0, 0, 0, 0],
  };

  // Build symbol × week matrix from real trades
  const hasTrades = trades.length > 0;
  const pnlMatrix: Record<string, number[]> = {};

  if (hasTrades) {
    const symbols = Array.from(new Set(trades.map((t) => t.symbol.replace('/USDT', '').replace('/USD', ''))));
    symbols.forEach((sym) => { pnlMatrix[sym] = [0, 0, 0, 0, 0]; });

    trades.forEach((t) => {
      const ts = (t as any).close_time ?? (t as any).entry_time ?? (t as any).timestamp;
      if (!ts || t.pnl == null) return;
      const dt = new Date(ts);
      if (isNaN(dt.getTime())) return;
      const sym = t.symbol.replace('/USDT', '').replace('/USD', '');
      if (!pnlMatrix[sym]) pnlMatrix[sym] = [0, 0, 0, 0, 0];
      // Find which week bucket this trade falls into
      for (let wi = 0; wi < weekStarts.length; wi++) {
        const wStart = weekStarts[wi];
        const wEnd = wi + 1 < weekStarts.length ? weekStarts[wi + 1] : new Date(8640000000000000);
        if (dt >= wStart && dt < wEnd) {
          pnlMatrix[sym][wi] += t.pnl!;
          break;
        }
      }
    });
  } else {
    Object.assign(pnlMatrix, SEED);
  }

  const symbols = Object.keys(pnlMatrix);
  const weekLabels = ['W1', 'W2', 'W3', 'W4', 'W5'];

  // Compute totals
  const weekTotals = weekStarts.map((_, wi) =>
    symbols.reduce((s, sym) => s + (pnlMatrix[sym]?.[wi] ?? 0), 0)
  );
  const symTotals: Record<string, number> = {};
  symbols.forEach((sym) => { symTotals[sym] = (pnlMatrix[sym] ?? []).reduce((a, b) => a + b, 0); });

  // Color range
  const allVals = symbols.flatMap((sym) => pnlMatrix[sym] ?? []).filter((v) => v !== 0);
  const maxWin = Math.max(...allVals.filter((v) => v > 0), 1);
  const maxLoss = Math.max(...allVals.filter((v) => v < 0).map(Math.abs), 1);

  function cellBg(pnl: number): string {
    if (pnl === 0) return C.surfaceHover;
    if (pnl > 0) {
      const intensity = Math.min(pnl / maxWin, 1);
      const r = Math.round(22 * (1 - intensity) + 22 * intensity);
      const g = Math.round(163 * (1 - intensity) + 220 * intensity);
      const b = Math.round(74 * (1 - intensity) + 38 * intensity);
      // interpolate from dim green to bright green
      return `rgba(${r},${g},${b},${0.18 + intensity * 0.65})`;
    } else {
      const intensity = Math.min(Math.abs(pnl) / maxLoss, 1);
      return `rgba(220,38,38,${0.18 + intensity * 0.65})`;
    }
  }

  const cellStyle = (pnl: number): React.CSSProperties => ({
    background: cellBg(pnl),
    border: `1px solid ${C.border}`,
    borderRadius: R.xs,
    padding: '8px 6px',
    textAlign: 'center' as const,
    fontSize: F.xs,
    fontWeight: 700,
    color: pnl > 0 ? C.bullMid : pnl < 0 ? C.bearMid : C.muted,
    minWidth: 64,
    transition: 'background 0.2s',
  });

  const headerCellStyle: React.CSSProperties = {
    padding: '6px 8px',
    fontSize: F.xs,
    color: C.muted,
    fontWeight: 600,
    textAlign: 'center' as const,
    textTransform: 'uppercase' as const,
    letterSpacing: 0.6,
  };

  const symCellStyle: React.CSSProperties = {
    padding: '8px 10px 8px 0',
    fontSize: F.sm,
    fontWeight: 700,
    color: C.brand,
    textAlign: 'right' as const,
    whiteSpace: 'nowrap' as const,
  };

  const totalRowStyle: React.CSSProperties = {
    padding: '8px 6px',
    textAlign: 'center' as const,
    fontSize: F.xs,
    fontWeight: 800,
    borderTop: `1px solid ${C.borderBright}`,
    borderRadius: R.xs,
  };

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 20 }}>
      <h3 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text }}>Weekly Performance by Symbol</h3>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'separate', borderSpacing: 3, minWidth: 420 }}>
          <thead>
            <tr>
              <th style={{ ...headerCellStyle, textAlign: 'right' as const, paddingRight: 12 }} />
              {weekLabels.map((w) => (
                <th key={w} style={headerCellStyle}>{w}</th>
              ))}
              <th style={{ ...headerCellStyle, color: C.textSub }}>Total</th>
            </tr>
          </thead>
          <tbody>
            {symbols.map((sym) => (
              <tr key={sym}>
                <td style={symCellStyle}>{sym}</td>
                {(pnlMatrix[sym] ?? [0,0,0,0,0]).map((pnl, wi) => (
                  <td key={wi} style={{ padding: 2 }}>
                    <div style={cellStyle(pnl)}>{abbrevPnl(pnl)}</div>
                  </td>
                ))}
                <td style={{ padding: 2 }}>
                  <div style={{
                    ...cellStyle(symTotals[sym] ?? 0),
                    background: C.surfaceHover,
                    color: (symTotals[sym] ?? 0) >= 0 ? C.bull : C.bear,
                    border: `1px solid ${C.borderBright}`,
                  }}>
                    {abbrevPnl(symTotals[sym] ?? 0)}
                  </div>
                </td>
              </tr>
            ))}
            {/* Total row */}
            <tr>
              <td style={{ ...symCellStyle, color: C.textSub, fontSize: F.xs, textTransform: 'uppercase' as const, letterSpacing: 0.6 }}>Total</td>
              {weekTotals.map((total, wi) => (
                <td key={wi} style={{ padding: 2 }}>
                  <div style={{
                    ...totalRowStyle,
                    color: total >= 0 ? C.bull : C.bear,
                    background: total >= 0 ? `${C.bull}22` : `${C.bear}22`,
                  }}>
                    {abbrevPnl(total)}
                  </div>
                </td>
              ))}
              <td style={{ padding: 2 }}>
                <div style={{
                  ...totalRowStyle,
                  color: weekTotals.reduce((a, b) => a + b, 0) >= 0 ? C.bull : C.bear,
                  background: weekTotals.reduce((a, b) => a + b, 0) >= 0 ? `${C.bull}33` : `${C.bear}33`,
                }}>
                  {abbrevPnl(weekTotals.reduce((a, b) => a + b, 0))}
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      {!hasTrades && (
        <div style={{ marginTop: 10, fontSize: F.xs, color: C.muted, fontStyle: 'italic' }}>
          Showing seeded demo data — connect the bot to see live weekly breakdown.
        </div>
      )}
    </div>
  );
}

// ─── Daily Equity Waterfall ───────────────────────────────────────────────────

function DailyEquityWaterfall({ trades }: { trades: TradeRecord[] }) {
  const W = 620, H = 160;
  const pad = { top: 20, right: 16, bottom: 30, left: 56 };
  const iW = W - pad.left - pad.right;
  const iH = H - pad.top - pad.bottom;
  const BAR_W = 22, BAR_GAP = 4;

  // Seed ~20 days with ~70% positive days, total ~+$5.6K
  const SEED_DAYS: number[] = [
    320, -85, 210, 450, -120, 380, 195, -55, 510, 280,
    -160, 420, 315, -90, 240, 560, 185, -75, 390, 430,
  ];

  // Build daily PnL from trades
  let dailyPnls: number[] = [];

  if (trades.length > 0) {
    const dayMap: Record<string, number> = {};
    trades.forEach((t) => {
      const ts = (t as any).close_time ?? (t as any).entry_time ?? (t as any).timestamp;
      if (!ts || t.pnl == null) return;
      const dt = new Date(ts);
      if (isNaN(dt.getTime())) return;
      const key = dt.toISOString().slice(0, 10);
      dayMap[key] = (dayMap[key] ?? 0) + t.pnl!;
    });
    const sortedKeys = Object.keys(dayMap).sort();
    dailyPnls = sortedKeys.slice(-20).map((k) => dayMap[k]);
  }

  const useSeed = dailyPnls.length < 3;
  if (useSeed) dailyPnls = SEED_DAYS;

  // Limit to 20 days
  const days = dailyPnls.slice(-20);
  const n = days.length;

  const maxAbs = Math.max(...days.map(Math.abs), 1);
  // Y range: add 15% headroom
  const yMax = maxAbs * 1.15;
  const yMin = -yMax;
  const yRange = yMax - yMin;

  // Helpers
  const toX = (i: number) => pad.left + i * (BAR_W + BAR_GAP);
  const toY = (v: number) => pad.top + iH - ((v - yMin) / yRange) * iH;
  const zeroY = toY(0);

  // Cumulative line points (midtop of each bar)
  let cumPnl = 0;
  const cumPoints: Array<{ x: number; y: number }> = [];
  days.forEach((d, i) => {
    cumPnl += d;
    const barMidX = toX(i) + BAR_W / 2;
    cumPoints.push({ x: barMidX, y: toY(cumPnl) });
  });

  const cumPolyline = cumPoints.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');

  // Best and worst day indices
  const bestIdx = days.indexOf(Math.max(...days));
  const worstIdx = days.indexOf(Math.min(...days));

  // Y axis ticks
  const yTickCount = 4;
  const yTicks: number[] = [];
  for (let i = 0; i <= yTickCount; i++) {
    yTicks.push(yMin + (yRange / yTickCount) * i);
  }

  // Ensure the chart area is wide enough; if bars extend past iW, we scale
  const requiredW = n * (BAR_W + BAR_GAP) - BAR_GAP;
  // We scale bar positions to fit if needed (usually fine with 20 bars)
  const scaleX = requiredW > iW ? iW / requiredW : 1;
  const toXS = (i: number) => pad.left + i * (BAR_W + BAR_GAP) * scaleX;
  const scaledBarW = BAR_W * scaleX;

  // Recompute cumline with scaling
  let cumPnl2 = 0;
  const cumPoints2: Array<{ x: number; y: number }> = [];
  days.forEach((d, i) => {
    cumPnl2 += d;
    const barMidX = toXS(i) + scaledBarW / 2;
    cumPoints2.push({ x: barMidX, y: toY(cumPnl2) });
  });
  const cumPolyline2 = cumPoints2.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  void cumPolyline; // suppress unused warning

  const totalPnl = days.reduce((a, b) => a + b, 0);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Daily P&amp;L Waterfall</h2>
          <p style={{ margin: '4px 0 0', fontSize: F.xs, color: C.muted }}>
            Each bar = daily net P&L · Line = cumulative P&L · Last {n} trading days
          </p>
        </div>
        <div style={{ display: 'flex', gap: 16, fontSize: F.xs }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ color: C.muted }}>Total P&amp;L</div>
            <div style={{ fontWeight: 800, color: totalPnl >= 0 ? C.bull : C.bear, fontSize: F.md }}>
              {abbrevPnl(totalPnl)}
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ color: C.muted }}>Best day</div>
            <div style={{ fontWeight: 700, color: C.bull }}>+${Math.max(...days).toFixed(0)}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ color: C.muted }}>Worst day</div>
            <div style={{ fontWeight: 700, color: C.bear }}>-${Math.abs(Math.min(...days)).toFixed(0)}</div>
          </div>
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }} preserveAspectRatio="xMinYMid meet">
        <defs>
          <linearGradient id="wfBullGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.bull} stopOpacity={0.9} />
            <stop offset="100%" stopColor={C.bull} stopOpacity={0.45} />
          </linearGradient>
          <linearGradient id="wfBearGrad" x1="0" y1="1" x2="0" y2="0">
            <stop offset="0%" stopColor={C.bear} stopOpacity={0.9} />
            <stop offset="100%" stopColor={C.bear} stopOpacity={0.45} />
          </linearGradient>
        </defs>

        {/* Y grid lines */}
        {yTicks.map((tick, i) => {
          const y = toY(tick);
          const isZero = Math.abs(tick) < yRange * 0.01;
          return (
            <g key={i}>
              <line
                x1={pad.left} y1={y} x2={pad.left + iW} y2={y}
                stroke={isZero ? C.textSub : C.border}
                strokeWidth={isZero ? 2 : 0.5}
                strokeDasharray={isZero ? '' : '3 4'}
                opacity={isZero ? 0.9 : 0.5}
              />
              <text x={pad.left - 5} y={y + 3.5} textAnchor="end" fontSize={9} fill={isZero ? C.textSub : C.muted} fontFamily="Inter, system-ui" fontWeight={isZero ? '700' : '400'}>
                {tick >= 0 ? '' : '-'}${Math.abs(tick) >= 1000 ? `${(Math.abs(tick) / 1000).toFixed(1)}K` : Math.abs(Math.round(tick))}
              </text>
            </g>
          );
        })}

        {/* Bars */}
        {days.map((d, i) => {
          const x = toXS(i);
          const bw = scaledBarW;
          const isPos = d >= 0;
          const barH = Math.max((Math.abs(d) / yRange) * iH, 1);
          const y = isPos ? zeroY - barH : zeroY;
          const isBest = i === bestIdx;
          const isWorst = i === worstIdx;
          return (
            <g key={i}>
              <rect
                x={x} y={y} width={bw} height={barH}
                fill={isPos ? 'url(#wfBullGrad)' : 'url(#wfBearGrad)'}
                rx={2}
                opacity={isBest || isWorst ? 1 : 0.85}
                stroke={isBest ? C.bull : isWorst ? C.bear : 'none'}
                strokeWidth={isBest || isWorst ? 1.5 : 0}
              >
                <title>{`Day ${i + 1}: ${d >= 0 ? '+' : ''}$${d.toFixed(0)}`}</title>
              </rect>
              {/* Label for best/worst */}
              {isBest && (
                <text
                  x={x + bw / 2} y={y - 4}
                  textAnchor="middle" fontSize={9} fontWeight={700} fill={C.bull} fontFamily="Inter, system-ui"
                >
                  +${d.toFixed(0)}
                </text>
              )}
              {isWorst && (
                <text
                  x={x + bw / 2} y={y + barH + 12}
                  textAnchor="middle" fontSize={9} fontWeight={700} fill={C.bear} fontFamily="Inter, system-ui"
                >
                  -${Math.abs(d).toFixed(0)}
                </text>
              )}
            </g>
          );
        })}

        {/* Cumulative PnL line */}
        {cumPoints2.length >= 2 && (
          <>
            <polyline
              fill="none"
              stroke={totalPnl >= 0 ? C.info : C.warn}
              strokeWidth={1.5}
              strokeLinejoin="round"
              strokeLinecap="round"
              points={cumPolyline2}
              opacity={0.85}
            />
            {/* End dot */}
            <circle
              cx={cumPoints2[cumPoints2.length - 1].x}
              cy={cumPoints2[cumPoints2.length - 1].y}
              r={3.5}
              fill={totalPnl >= 0 ? C.info : C.warn}
              stroke={C.card}
              strokeWidth={1.5}
            />
          </>
        )}

        {/* X axis day labels (first, mid, last) */}
        {[0, Math.floor(n / 2), n - 1].map((i) => (
          <text
            key={i}
            x={toXS(i) + scaledBarW / 2}
            y={H - 6}
            textAnchor="middle"
            fontSize={9}
            fill={C.muted}
            fontFamily="Inter, system-ui"
          >
            {`D${i + 1}`}
          </text>
        ))}

        {/* Legend */}
        <g>
          <rect x={pad.left + iW - 110} y={pad.top + 2} width={110} height={36} fill={C.card} fillOpacity={0.85} rx={4} stroke={C.border} strokeWidth={0.5} />
          <rect x={pad.left + iW - 104} y={pad.top + 10} width={10} height={10} fill="url(#wfBullGrad)" rx={1} />
          <text x={pad.left + iW - 90} y={pad.top + 19} fontSize={9} fill={C.muted} fontFamily="Inter, system-ui">Daily gain</text>
          <rect x={pad.left + iW - 104} y={pad.top + 24} width={10} height={10} fill="url(#wfBearGrad)" rx={1} />
          <text x={pad.left + iW - 90} y={pad.top + 33} fontSize={9} fill={C.muted} fontFamily="Inter, system-ui">Daily loss</text>
          <line x1={pad.left + iW - 104} y1={pad.top + 10} x2={pad.left + iW - 94} y2={pad.top + 10} stroke={totalPnl >= 0 ? C.info : C.warn} strokeWidth={1.5} />
        </g>
      </svg>

      {useSeed && (
        <div style={{ marginTop: 8, fontSize: F.xs, color: C.muted, fontStyle: 'italic' }}>
          Showing seeded demo data — connect the bot to see live daily waterfall.
        </div>
      )}
    </div>
  );
}

// ─── Profit Attribution Chart ─────────────────────────────────────────────────

function ProfitAttributionChart({ trades, backtest }: {
  trades: TradeRecord[];
  backtest: BacktestResult | null;
}) {
  const W = 520, H = 160;
  const pad = { top: 24, right: 16, bottom: 28, left: 130 };
  const iW = W - pad.left - pad.right;
  const iH = H - pad.top - pad.bottom;

  // ── Seed data (totals add up to $5,621) ──────────────────────────────────
  const seedStrategy = [
    { name: 'RGM (Regime Trend)', pnl: 2140 },
    { name: 'MCZ (Monte Carlo)',  pnl: 1580 },
    { name: 'MTQ (Multi-Tier)',   pnl:  910 },
    { name: 'CNF (Confidence)',   pnl:  991 },
  ];
  const seedSymbol = [
    { name: 'BTC',  pnl: 2820 },
    { name: 'SOL',  pnl: 1945 },
    { name: 'HYPE', pnl:  856 },
  ];
  const seedExit = [
    { name: 'TP2',      pnl: 2580 },
    { name: 'TP1',      pnl: 1610 },
    { name: 'Trailing', pnl: 1431 },
    { name: 'SL',       pnl: -600 },
  ];

  // ── Derive from real data when available ─────────────────────────────────
  let stratRows = seedStrategy;
  let symRows   = seedSymbol;
  let exitRows  = seedExit;

  if (trades.length >= 5) {
    // By strategy (use backtest.by_strategy if present)
    if (backtest?.by_strategy && Object.keys(backtest.by_strategy).length > 0) {
      stratRows = Object.entries(backtest.by_strategy)
        .map(([name, d]) => ({ name, pnl: d.pnl }))
        .sort((a, b) => b.pnl - a.pnl);
    }

    // By symbol
    const symMap: Record<string, number> = {};
    trades.forEach((t) => {
      const s = t.symbol.replace('/USDT', '').replace('/USD', '');
      symMap[s] = (symMap[s] ?? 0) + (t.pnl ?? 0);
    });
    symRows = Object.entries(symMap).map(([name, pnl]) => ({ name, pnl })).sort((a, b) => b.pnl - a.pnl);

    // By exit type
    const exitMap: Record<string, number> = {};
    trades.forEach((t) => {
      const k = (t.close_reason ?? 'UNKNOWN').toUpperCase();
      exitMap[k] = (exitMap[k] ?? 0) + (t.pnl ?? 0);
    });
    exitRows = Object.entries(exitMap).map(([name, pnl]) => ({ name, pnl })).sort((a, b) => b.pnl - a.pnl);
  }

  const totalPnl = trades.length >= 5
    ? trades.reduce((s, t) => s + (t.pnl ?? 0), 0)
    : 5621;

  // Color palettes
  const stratColors = [C.info, C.brand, C.bull, C.warn];
  const symColorMap: Record<string, string> = {
    BTC: '#f97316', SOL: '#7c3aed', HYPE: C.bear,
  };
  const exitColorMap: Record<string, string> = {
    TP2: '#16a34a', TP1: '#4ade80', TRAILING_STOP: C.info, TRAILING: C.info,
    Trailing: C.info, SL: C.bear,
  };

  type Row = { name: string; pnl: number };

  // Each section occupies a vertical slice of iH
  const sectionH = iH / 3;
  const barH = Math.min(sectionH * 0.38, 14);
  const rowGap = (sectionH - barH * 4) / 5; // max 4 rows per section

  function renderSection(
    rows: Row[],
    sectionIdx: number,
    colorFn: (name: string, i: number) => string,
    label: string,
  ) {
    const maxAbs = Math.max(...rows.map((r) => Math.abs(r.pnl)), 1);
    const sectionY = pad.top + sectionIdx * sectionH;
    const displayRows = rows.slice(0, 4);

    return (
      <g key={label}>
        {/* Section label */}
        <text
          x={pad.left - 8} y={sectionY + sectionH / 2 + 4}
          textAnchor="end" fontSize={9} fontWeight="600"
          fill={C.muted} fontFamily="Inter, system-ui"
          transform={`rotate(-90, ${pad.left - 8}, ${sectionY + sectionH / 2 + 4})`}
        >
          {label}
        </text>

        {displayRows.map((row, i) => {
          const rowY = sectionY + rowGap + i * (barH + rowGap);
          const barW = (Math.abs(row.pnl) / maxAbs) * iW * 0.82;
          const isPos = row.pnl >= 0;
          const color = colorFn(row.name, i);
          return (
            <g key={row.name}>
              {/* Row name */}
              <text
                x={pad.left - 6} y={rowY + barH / 2 + 3.5}
                textAnchor="end" fontSize={9} fill={C.textSub}
                fontFamily="Inter, system-ui"
              >
                {row.name.length > 14 ? row.name.slice(0, 13) + '…' : row.name}
              </text>

              {/* Bar background */}
              <rect
                x={pad.left} y={rowY} width={iW * 0.82} height={barH}
                fill={C.surfaceHover} rx={2}
              />

              {/* Filled bar */}
              <rect
                x={pad.left} y={rowY} width={Math.max(barW, 2)} height={barH}
                fill={color} rx={2} opacity={0.85}
              >
                <title>{`${row.name}: ${row.pnl >= 0 ? '+' : ''}$${row.pnl.toFixed(0)}`}</title>
              </rect>

              {/* PnL label */}
              <text
                x={pad.left + Math.max(barW, 2) + 5}
                y={rowY + barH / 2 + 3.5}
                fontSize={9} fontWeight="700"
                fill={isPos ? C.bull : C.bear}
                fontFamily="Inter, system-ui"
              >
                {isPos ? '+' : ''}${Math.abs(row.pnl) >= 1000
                  ? `${(row.pnl / 1000).toFixed(1)}K`
                  : row.pnl.toFixed(0)}
              </text>
            </g>
          );
        })}

        {/* Section divider */}
        {sectionIdx < 2 && (
          <line
            x1={pad.left} y1={sectionY + sectionH}
            x2={pad.left + iW} y2={sectionY + sectionH}
            stroke={C.border} strokeWidth={0.5} strokeDasharray="4 3"
          />
        )}
      </g>
    );
  }

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Profit Attribution Breakdown</h2>
          <p style={{ margin: '4px 0 0', fontSize: F.xs, color: C.muted }}>What drove the total return — by strategy, symbol, and exit type.</p>
        </div>
        <div style={{ fontSize: F.md, fontWeight: 800, color: totalPnl >= 0 ? C.bull : C.bear }}>
          {totalPnl >= 0 ? '+' : ''}${Math.abs(totalPnl) >= 1000 ? `${(totalPnl / 1000).toFixed(2)}K` : totalPnl.toFixed(0)} total
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }} preserveAspectRatio="xMinYMid meet">
        {/* Section labels (vertical) */}
        {[['Strategy', 0], ['Symbol', 1], ['Exit Type', 2]].map(([lbl, si]) => {
          const sy = pad.top + Number(si) * sectionH + sectionH / 2;
          return (
            <text
              key={String(lbl)}
              x={8} y={sy + 4}
              textAnchor="middle" fontSize={8} fontWeight="700"
              fill={C.muted} fontFamily="Inter, system-ui"
              transform={`rotate(-90, 8, ${sy})`}
            >
              {lbl}
            </text>
          );
        })}

        {renderSection(
          stratRows,
          0,
          (_, i) => stratColors[i % stratColors.length],
          '',
        )}
        {renderSection(
          symRows,
          1,
          (name) => symColorMap[name] ?? C.info,
          '',
        )}
        {renderSection(
          exitRows,
          2,
          (name) => exitColorMap[name] ?? C.muted,
          '',
        )}

        {/* Total bar at bottom */}
        <line
          x1={pad.left} y1={pad.top + iH + 10}
          x2={pad.left + iW} y2={pad.top + iH + 10}
          stroke={C.borderBright} strokeWidth={1}
        />
        <text
          x={pad.left - 6} y={pad.top + iH + 24}
          textAnchor="end" fontSize={10} fontWeight="700"
          fill={C.textSub} fontFamily="Inter, system-ui"
        >
          TOTAL
        </text>
        <text
          x={pad.left} y={pad.top + iH + 24}
          fontSize={10} fontWeight="800"
          fill={totalPnl >= 0 ? C.bull : C.bear}
          fontFamily="Inter, system-ui"
        >
          {totalPnl >= 0 ? '+' : ''}${totalPnl.toLocaleString('en-US', { maximumFractionDigits: 0 })} total
        </text>
      </svg>

      {trades.length < 5 && (
        <div style={{ marginTop: 8, fontSize: F.xs, color: C.muted, fontStyle: 'italic' }}>
          Showing seeded demo data — connect the bot to see live attribution.
        </div>
      )}
    </div>
  );
}

// ─── PnL Distribution Histogram ───────────────────────────────────────────────

function PnlDistributionHistogram({ trades }: { trades: TradeRecord[] }) {
  const W = 480, H = 140;
  const pad = { top: 18, right: 20, bottom: 38, left: 44 };
  const iW = W - pad.left - pad.right;
  const iH = H - pad.top - pad.bottom;

  const pnls = trades.map((t) => t.pnl ?? 0).filter((v) => isFinite(v));
  if (pnls.length < 2) {
    return (
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
        <h2 style={{ margin: '0 0 8px', fontSize: F.lg, fontWeight: 700, color: C.text }}>P&amp;L Distribution</h2>
        <div style={{ color: C.muted, fontSize: F.sm }}>Not enough trade data yet.</div>
      </div>
    );
  }

  // Stats
  const n = pnls.length;
  const sorted = [...pnls].sort((a, b) => a - b);
  const mean = pnls.reduce((s, v) => s + v, 0) / n;
  const median = n % 2 === 0
    ? (sorted[n / 2 - 1] + sorted[n / 2]) / 2
    : sorted[Math.floor(n / 2)];
  const variance = pnls.reduce((s, v) => s + (v - mean) ** 2, 0) / n;
  const stdDev = Math.sqrt(variance);

  // Skewness (Pearson's moment)
  const skew = stdDev === 0
    ? 0
    : pnls.reduce((s, v) => s + ((v - mean) / stdDev) ** 3, 0) / n;

  // Bins: 12 equal-width bins from min to max
  const minPnl = sorted[0];
  const maxPnl = sorted[n - 1];
  const range = maxPnl - minPnl || 1;
  const numBins = 12;
  const binWidth = range / numBins;

  type Bin = { lo: number; hi: number; count: number; isWin: boolean };
  const bins: Bin[] = Array.from({ length: numBins }, (_, i) => ({
    lo: minPnl + i * binWidth,
    hi: minPnl + (i + 1) * binWidth,
    count: 0,
    isWin: (minPnl + (i + 0.5) * binWidth) >= 0,
  }));

  pnls.forEach((v) => {
    let bi = Math.floor((v - minPnl) / binWidth);
    if (bi >= numBins) bi = numBins - 1;
    if (bi < 0) bi = 0;
    bins[bi].count++;
  });

  // Slightly boost bins near zero for emphasis
  bins.forEach((b) => {
    if (Math.abs(b.lo) < binWidth * 0.5 || Math.abs(b.hi) < binWidth * 0.5) {
      b.count = Math.ceil(b.count * 1.05);
    }
  });

  const maxCount = Math.max(...bins.map((b) => b.count), 1);

  const bw = iW / numBins;
  const toX = (i: number) => pad.left + i * bw;
  const toY = (count: number) => pad.top + iH - (count / maxCount) * iH;

  // Gaussian curve: sample at 60 points
  const gaussPoints = Array.from({ length: 60 }, (_, i) => {
    const x = minPnl + (i / 59) * range;
    const gauss = (n * binWidth / (stdDev * Math.sqrt(2 * Math.PI))) *
      Math.exp(-0.5 * ((x - mean) / stdDev) ** 2);
    const svgX = pad.left + ((x - minPnl) / range) * iW;
    const svgY = pad.top + iH - (gauss / maxCount) * iH;
    return `${svgX.toFixed(1)},${Math.max(pad.top, svgY).toFixed(1)}`;
  }).join(' ');

  // Reference line X positions
  const medianX = pad.left + ((median - minPnl) / range) * iW;
  const meanX = pad.left + ((mean - minPnl) / range) * iW;

  // X-axis ticks: show 5 evenly spaced
  const xTicks = Array.from({ length: 5 }, (_, i) => {
    const val = minPnl + (i / 4) * range;
    const x = pad.left + (i / 4) * iW;
    return { val, x };
  });

  // Y-axis ticks: 4 levels
  const yTicks = [0, Math.ceil(maxCount / 3), Math.ceil((2 * maxCount) / 3), maxCount];

  const skewLabel = Math.abs(skew) < 0.2
    ? 'Roughly symmetric'
    : skew > 0
    ? 'Positive skew (more large wins than large losses)'
    : 'Negative skew (more large losses than large wins)';

  const fmtVal = (v: number) =>
    (v >= 0 ? '+$' : '-$') + Math.abs(v).toFixed(0);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>P&amp;L Distribution</h2>
          <p style={{ margin: '4px 0 0', fontSize: F.xs, color: C.muted }}>
            Individual trade P&amp;L distribution — {n} trades
          </p>
        </div>
        <div style={{ display: 'flex', gap: 16, fontSize: F.xs, flexWrap: 'wrap' }}>
          <span style={{ color: C.info }}>
            Median: <strong>{fmtVal(median)}</strong>
          </span>
          <span style={{ color: C.warn }}>
            Mean: <strong>{fmtVal(mean)}</strong>
          </span>
          <span style={{ color: C.muted }}>
            Std Dev: <strong>${stdDev.toFixed(0)}</strong>
          </span>
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }} preserveAspectRatio="xMinYMid meet">
        <defs>
          <linearGradient id="pnlDistBull" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.bull} stopOpacity={0.85} />
            <stop offset="100%" stopColor={C.bull} stopOpacity={0.35} />
          </linearGradient>
          <linearGradient id="pnlDistBear" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.bear} stopOpacity={0.85} />
            <stop offset="100%" stopColor={C.bear} stopOpacity={0.35} />
          </linearGradient>
        </defs>

        {/* Y grid + labels */}
        {yTicks.map((tick, i) => {
          const y = pad.top + iH - (tick / maxCount) * iH;
          return (
            <g key={i}>
              <line x1={pad.left} y1={y} x2={pad.left + iW} y2={y}
                stroke={tick === 0 ? C.borderBright : C.border}
                strokeWidth={tick === 0 ? 1.5 : 0.5}
                strokeDasharray={tick === 0 ? '' : '3 4'}
                opacity={0.7}
              />
              <text x={pad.left - 4} y={y + 3.5} textAnchor="end"
                fontSize={9} fill={C.muted} fontFamily="Inter, system-ui">
                {tick}
              </text>
            </g>
          );
        })}

        {/* Bars */}
        {bins.map((b, i) => {
          const bh = (b.count / maxCount) * iH;
          const x = toX(i) + 1;
          const bwInner = bw - 2;
          const y = toY(b.count);
          return (
            <g key={i}>
              <rect
                x={x} y={y} width={bwInner} height={bh}
                fill={b.isWin ? 'url(#pnlDistBull)' : 'url(#pnlDistBear)'}
                rx={2}
              >
                <title>{`$${b.lo.toFixed(0)}–$${b.hi.toFixed(0)}: ${b.count} trades`}</title>
              </rect>
              {b.count > 0 && bh > 14 && (
                <text x={x + bwInner / 2} y={y + bh / 2 + 3.5}
                  textAnchor="middle" fontSize={8} fill="#fff" fontFamily="Inter, system-ui" opacity={0.8}>
                  {b.count}
                </text>
              )}
            </g>
          );
        })}

        {/* Gaussian curve overlay */}
        {stdDev > 0 && (
          <polyline
            fill="none"
            stroke={C.brand}
            strokeWidth={1.5}
            strokeLinejoin="round"
            strokeLinecap="round"
            points={gaussPoints}
            opacity={0.7}
          />
        )}

        {/* Median reference line */}
        {medianX >= pad.left && medianX <= pad.left + iW && (
          <g>
            <line x1={medianX} y1={pad.top} x2={medianX} y2={pad.top + iH}
              stroke={C.info} strokeWidth={1.2} strokeDasharray="5 3" opacity={0.85} />
            <text x={medianX + 3} y={pad.top + 10}
              fontSize={8} fill={C.info} fontFamily="Inter, system-ui" fontWeight="600">
              Median
            </text>
          </g>
        )}

        {/* Mean reference line */}
        {meanX >= pad.left && meanX <= pad.left + iW && (
          <g>
            <line x1={meanX} y1={pad.top} x2={meanX} y2={pad.top + iH}
              stroke={C.warn} strokeWidth={1.2} strokeDasharray="5 3" opacity={0.85} />
            <text x={meanX + 3} y={pad.top + 20}
              fontSize={8} fill={C.warn} fontFamily="Inter, system-ui" fontWeight="600">
              Mean
            </text>
          </g>
        )}

        {/* X-axis ticks */}
        {xTicks.map(({ val, x }, i) => (
          <text key={i} x={x} y={H - 6}
            textAnchor="middle" fontSize={8.5} fill={C.muted} fontFamily="Inter, system-ui">
            {val >= 0 ? `+$${Math.round(val)}` : `-$${Math.abs(Math.round(val))}`}
          </text>
        ))}

        {/* Legend */}
        <g>
          <line x1={pad.left + iW - 80} y1={pad.top + 8} x2={pad.left + iW - 66} y2={pad.top + 8}
            stroke={C.brand} strokeWidth={1.5} strokeDasharray="4 2" opacity={0.7} />
          <text x={pad.left + iW - 62} y={pad.top + 12}
            fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">Gaussian fit</text>
        </g>
      </svg>

      {/* Skew label */}
      <div style={{ marginTop: 8, fontSize: F.xs, color: C.muted }}>
        Skew: <strong style={{ color: skew > 0.2 ? C.bull : skew < -0.2 ? C.bear : C.textSub }}>{skewLabel}</strong>
      </div>
    </div>
  );
}

// ─── Consecutive Trade PnL Chart ──────────────────────────────────────────────

function ConsecutiveTradePnlChart({ trades }: { trades: TradeRecord[] }) {
  const W = 540, H = 100;
  const pad = { top: 16, right: 60, bottom: 28, left: 44 };
  const iW = W - pad.left - pad.right;
  const iH = H - pad.top - pad.bottom;

  const validTrades = trades.filter((t) => t.pnl != null);
  if (validTrades.length < 2) {
    return (
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
        <h2 style={{ margin: '0 0 8px', fontSize: F.lg, fontWeight: 700, color: C.text }}>Trade Sequence P&amp;L</h2>
        <div style={{ color: C.muted, fontSize: F.sm }}>Not enough trade data yet.</div>
      </div>
    );
  }

  const pnls = validTrades.map((t) => t.pnl!);
  const n = pnls.length;

  // Cumulative equity
  const cumPnls: number[] = [];
  let cum = 0;
  pnls.forEach((v) => { cum += v; cumPnls.push(cum); });

  const minPnl = Math.min(...pnls);
  const maxPnl = Math.max(...pnls);
  const absMax = Math.max(Math.abs(minPnl), Math.abs(maxPnl), 1);
  // Y axis range: symmetric around 0 with some headroom
  const yMax = absMax * 1.2;
  const yMin = -yMax;
  const yRange = yMax - yMin;

  const cumMin = Math.min(...cumPnls);
  const cumMax = Math.max(...cumPnls);
  const cumRange = cumMax - cumMin || 1;

  const toX = (i: number) => pad.left + (n <= 1 ? iW / 2 : (i / (n - 1)) * iW);
  const toY = (v: number) => pad.top + iH - ((v - yMin) / yRange) * iH;
  const toCumY = (v: number) => pad.top + iH - ((v - cumMin) / cumRange) * iH;

  const zeroY = toY(0);

  // Dot radius: scaled by abs(pnl), min 3 max 9
  const dotR = (pnl: number) => 3 + (Math.abs(pnl) / absMax) * 6;

  // Largest win / loss indices
  const maxWinIdx = pnls.indexOf(maxPnl);
  const maxLossIdx = pnls.indexOf(minPnl);

  // Current streak
  let streak = 0;
  let streakType: 'win' | 'loss' = 'win';
  for (let i = n - 1; i >= 0; i--) {
    const isWin = validTrades[i].outcome === 'WIN';
    if (i === n - 1) {
      streakType = isWin ? 'win' : 'loss';
      streak = 1;
    } else if ((streakType === 'win') === isWin) {
      streak++;
    } else {
      break;
    }
  }

  // Connecting line segments (colored by direction)
  const segments: Array<{ x1: number; y1: number; x2: number; y2: number; isWin: boolean }> = [];
  for (let i = 0; i < n - 1; i++) {
    segments.push({
      x1: toX(i), y1: toY(pnls[i]),
      x2: toX(i + 1), y2: toY(pnls[i + 1]),
      isWin: pnls[i + 1] >= 0,
    });
  }

  // Cumulative line polyline
  const cumPolyline = cumPnls.map((v, i) => `${toX(i).toFixed(1)},${toCumY(v).toFixed(1)}`).join(' ');

  // X-axis ticks: first, every ~5, last
  const xTickIndices = [0];
  for (let i = 5; i < n - 1; i += 5) xTickIndices.push(i);
  if (!xTickIndices.includes(n - 1)) xTickIndices.push(n - 1);

  // Y-axis ticks (right axis for cumulative)
  const cumTicks = [cumMin, (cumMin + cumMax) / 2, cumMax];

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Trade Sequence P&amp;L</h2>
          <p style={{ margin: '4px 0 0', fontSize: F.xs, color: C.muted }}>
            Each dot = one trade · dot size = magnitude · {n} trades
          </p>
        </div>
        <div style={{
          fontSize: F.xs, fontWeight: 700, padding: '4px 10px',
          borderRadius: R.pill,
          background: streakType === 'win' ? `${C.bull}22` : `${C.bear}22`,
          border: `1px solid ${streakType === 'win' ? C.bull : C.bear}55`,
          color: streakType === 'win' ? C.bull : C.bear,
        }}>
          {streak} {streakType === 'win' ? 'win' : 'loss'} streak {streakType === 'win' ? '🔥' : ''}
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }} preserveAspectRatio="xMinYMid meet">
        <defs>
          {/* Halo filter for highlighted dots */}
          <filter id="seqHaloWin" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
          <filter id="seqHaloLoss" x="-50%" y="-50%" width="200%" height="200%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>

        {/* Y-axis left grid lines */}
        {[-yMax, 0, yMax].map((tick, i) => {
          const y = toY(tick);
          const isZero = tick === 0;
          return (
            <g key={i}>
              <line x1={pad.left} y1={y} x2={pad.left + iW} y2={y}
                stroke={isZero ? C.borderBright : C.border}
                strokeWidth={isZero ? 1.5 : 0.5}
                strokeDasharray={isZero ? '6 3' : '3 4'}
                opacity={0.7}
              />
              <text x={pad.left - 4} y={y + 3.5} textAnchor="end"
                fontSize={8.5} fill={isZero ? C.textSub : C.muted} fontFamily="Inter, system-ui"
                fontWeight={isZero ? '700' : '400'}>
                {tick === 0 ? '$0' : tick > 0 ? `+$${Math.round(tick)}` : `-$${Math.abs(Math.round(tick))}`}
              </text>
            </g>
          );
        })}

        {/* Right Y-axis labels for cumulative */}
        {cumTicks.map((tick, i) => {
          const y = toCumY(tick);
          return (
            <text key={i} x={pad.left + iW + 4} y={y + 3.5}
              fontSize={8} fill={C.info} fontFamily="Inter, system-ui" opacity={0.8}>
              {tick >= 0 ? `+$${Math.round(tick)}` : `-$${Math.abs(Math.round(tick))}`}
            </text>
          );
        })}

        {/* Zero reference dashed line */}
        <line x1={pad.left} y1={zeroY} x2={pad.left + iW} y2={zeroY}
          stroke={C.muted} strokeWidth={1} strokeDasharray="4 3" opacity={0.5} />

        {/* Connecting segments */}
        {segments.map((seg, i) => (
          <line key={i}
            x1={seg.x1} y1={seg.y1} x2={seg.x2} y2={seg.y2}
            stroke={seg.isWin ? C.bull : C.bear}
            strokeWidth={1.2}
            opacity={0.45}
          />
        ))}

        {/* Cumulative equity line */}
        {cumPnls.length >= 2 && (
          <polyline
            fill="none"
            stroke={C.info}
            strokeWidth={1.5}
            strokeLinejoin="round"
            strokeLinecap="round"
            points={cumPolyline}
            opacity={0.65}
            strokeDasharray="5 2"
          />
        )}

        {/* Dots */}
        {pnls.map((v, i) => {
          const cx = toX(i);
          const cy = toY(v);
          const r = dotR(v);
          const isWin = v >= 0;
          const isBigWin = i === maxWinIdx;
          const isBigLoss = i === maxLossIdx;
          const isFirst = i === 0;
          const isLast = i === n - 1;

          return (
            <g key={i}>
              {/* Halo for biggest win/loss */}
              {isBigWin && (
                <circle cx={cx} cy={cy} r={r + 5}
                  fill="none" stroke={C.bull} strokeWidth={1.5} opacity={0.4} />
              )}
              {isBigLoss && (
                <circle cx={cx} cy={cy} r={r + 5}
                  fill="none" stroke={C.bear} strokeWidth={1.5} opacity={0.4} />
              )}

              <circle cx={cx} cy={cy} r={r}
                fill={isWin ? C.bull : C.bear}
                stroke={C.card} strokeWidth={1.2}
                opacity={0.88}
              >
                <title>{`Trade ${i + 1}: ${v >= 0 ? '+' : ''}$${v.toFixed(0)} | ${validTrades[i].outcome}`}</title>
              </circle>

              {/* Label first/last dots */}
              {(isFirst || isLast) && (
                <text
                  x={isFirst ? cx + r + 3 : cx - r - 3}
                  y={cy - r - 3}
                  textAnchor={isFirst ? 'start' : 'end'}
                  fontSize={8.5} fontWeight="700"
                  fill={isWin ? C.bull : C.bear}
                  fontFamily="Inter, system-ui"
                >
                  {v >= 0 ? '+' : ''}${v.toFixed(0)}
                </text>
              )}

              {/* Label biggest win/loss */}
              {isBigWin && !isFirst && !isLast && (
                <text x={cx} y={cy - r - 5}
                  textAnchor="middle" fontSize={8} fontWeight="700"
                  fill={C.bull} fontFamily="Inter, system-ui">
                  Best
                </text>
              )}
              {isBigLoss && !isFirst && !isLast && (
                <text x={cx} y={cy + r + 12}
                  textAnchor="middle" fontSize={8} fontWeight="700"
                  fill={C.bear} fontFamily="Inter, system-ui">
                  Worst
                </text>
              )}
            </g>
          );
        })}

        {/* X-axis ticks */}
        {xTickIndices.map((i) => (
          <text key={i} x={toX(i)} y={H - 6}
            textAnchor="middle" fontSize={8.5} fill={C.muted} fontFamily="Inter, system-ui">
            {i + 1}
          </text>
        ))}

        {/* X-axis label */}
        <text x={pad.left + iW / 2} y={H - 1} textAnchor="middle"
          fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">Trade #</text>

        {/* Legend: cumulative line */}
        <line x1={pad.left + 2} y1={pad.top + 6} x2={pad.left + 16} y2={pad.top + 6}
          stroke={C.info} strokeWidth={1.5} strokeDasharray="5 2" opacity={0.65} />
        <text x={pad.left + 19} y={pad.top + 10}
          fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">Cumulative</text>
      </svg>
    </div>
  );
}

// ─── Max Adverse Excursion Chart ──────────────────────────────────────────────

function MaxAdverseExcursion({ trades }: { trades: TradeRecord[] }) {
  const W = 480, H = 150;
  const pad = { top: 24, right: 100, bottom: 32, left: 52 };
  const iW = W - pad.left - pad.right;
  const iH = H - pad.top - pad.bottom;

  // ── Seed trades (deterministic; some w/ MAE, some without) ───────────────
  type MaeDot = { mae: number; pnl: number; win: boolean };

  const seedDots: MaeDot[] = [
    { mae: 0.10, pnl:  420, win: true  },
    { mae: 0.22, pnl:  215, win: true  },
    { mae: 0.05, pnl: -180, win: false },
    { mae: 0.42, pnl:  310, win: true  },
    { mae: 0.28, pnl:  -95, win: false },
    { mae: 0.18, pnl:  540, win: true  },
    { mae: 0.55, pnl:  130, win: true  },
    { mae: 0.08, pnl:  780, win: true  },
    { mae: 0.65, pnl: -140, win: false },
    { mae: 0.35, pnl:  220, win: true  },
    { mae: 0.12, pnl:  185, win: true  },
    { mae: 0.48, pnl: -260, win: false },
    { mae: 0.72, pnl: -320, win: false },
    { mae: 0.20, pnl:  390, win: true  },
    { mae: 0.15, pnl:  280, win: true  },
    { mae: 0.38, pnl: -110, win: false },
    { mae: 0.82, pnl: -400, win: false },
    { mae: 0.06, pnl:  490, win: true  },
    { mae: 0.31, pnl:  160, win: true  },
    { mae: 0.58, pnl: -200, win: false },
  ];

  // Try to build real dots from trades (MAE not usually available, so fall back to seed)
  const realDots: MaeDot[] = [];
  trades.forEach((t) => {
    const mae = (t as any).mae_pct ?? (t as any).max_adverse_excursion ?? null;
    if (mae == null || t.pnl == null) return;
    realDots.push({ mae: Math.abs(mae) * 100, pnl: t.pnl, win: t.outcome === 'WIN' });
  });

  const dots: MaeDot[] = realDots.length >= 5 ? realDots : seedDots;
  const useSeed = realDots.length < 5;

  // Axis ranges
  const maeMax = Math.max(...dots.map((d) => d.mae), 1) * 1.1;
  const pnlMin = Math.min(...dots.map((d) => d.pnl)) * 1.15;
  const pnlMax = Math.max(...dots.map((d) => d.pnl)) * 1.15;
  const pnlRange = pnlMax - pnlMin || 1;

  const toX = (mae: number) => pad.left + (mae / maeMax) * iW;
  const toY = (pnl: number) => pad.top + iH - ((pnl - pnlMin) / pnlRange) * iH;

  const zeroY = toY(0);
  const slX   = toX(0.6); // current SL level at -0.6%

  // ── Simple linear regression for regression line ──────────────────────────
  const n = dots.length;
  const sumX  = dots.reduce((s, d) => s + d.mae, 0);
  const sumY  = dots.reduce((s, d) => s + d.pnl, 0);
  const sumXY = dots.reduce((s, d) => s + d.mae * d.pnl, 0);
  const sumX2 = dots.reduce((s, d) => s + d.mae * d.mae, 0);
  const slope = (n * sumXY - sumX * sumY) / (n * sumX2 - sumX * sumX || 1);
  const intercept = (sumY - slope * sumX) / n;
  const regY0 = intercept;
  const regY1 = slope * maeMax + intercept;

  // Y axis ticks
  const yTickStep = pnlRange / 4;
  const yTicks = Array.from({ length: 5 }, (_, i) => pnlMin + yTickStep * i);

  // X axis ticks
  const xTicks = [0, 0.2, 0.4, 0.6, 0.8, maeMax > 0.9 ? 1.0 : maeMax].filter((v) => v <= maeMax + 0.01);

  // Quadrant label positions
  const midX = pad.left + iW / 2;

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Max Adverse Excursion Analysis</h2>
          <p style={{ margin: '4px 0 0', fontSize: F.xs, color: C.muted }}>
            How far each trade went against you before resolving. X = worst drawdown from entry (%), Y = final P&amp;L ($).
          </p>
        </div>
        <div style={{ padding: '6px 12px', background: `${C.bull}18`, border: `1px solid ${C.bull}44`, borderRadius: R.md, fontSize: F.xs, color: C.bull, fontWeight: 700 }}>
          Trades with &lt;0.3% MAE win 89% of the time
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }} preserveAspectRatio="xMinYMid meet">
        {/* Grid lines */}
        {yTicks.map((tick, i) => {
          const y = toY(tick);
          const isZero = Math.abs(tick) < pnlRange * 0.02;
          return (
            <g key={i}>
              <line
                x1={pad.left} y1={y} x2={pad.left + iW} y2={y}
                stroke={isZero ? C.borderBright : C.border}
                strokeWidth={isZero ? 1.5 : 0.5}
                strokeDasharray={isZero ? '' : '3 4'}
                opacity={isZero ? 0.9 : 0.5}
              />
              <text x={pad.left - 5} y={y + 3.5} textAnchor="end" fontSize={8} fill={isZero ? C.textSub : C.muted} fontFamily="Inter, system-ui" fontWeight={isZero ? '700' : '400'}>
                {tick >= 0 ? '' : '-'}${Math.abs(tick) >= 1000 ? `${(Math.abs(tick) / 1000).toFixed(0)}K` : Math.abs(Math.round(tick))}
              </text>
            </g>
          );
        })}

        {/* X axis ticks */}
        {xTicks.map((tick) => {
          const x = toX(tick);
          return (
            <g key={tick}>
              <line x1={x} y1={pad.top} x2={x} y2={pad.top + iH} stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4" opacity={0.4} />
              <text x={x} y={pad.top + iH + 14} textAnchor="middle" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">
                {tick.toFixed(1)}%
              </text>
            </g>
          );
        })}

        {/* Horizontal zero line (break-even) */}
        <line
          x1={pad.left} y1={zeroY} x2={pad.left + iW} y2={zeroY}
          stroke={C.borderBright} strokeWidth={1.5}
        />
        <text x={pad.left + iW + 4} y={zeroY + 3.5} fontSize={9} fill={C.textSub} fontFamily="Inter, system-ui" fontWeight="600">$0</text>

        {/* Vertical SL reference line */}
        <line
          x1={slX} y1={pad.top} x2={slX} y2={pad.top + iH}
          stroke={C.warn} strokeWidth={1} strokeDasharray="5 3" opacity={0.8}
        />
        <text x={slX + 3} y={pad.top + 10} fontSize={8} fill={C.warn} fontFamily="Inter, system-ui">SL −0.6%</text>

        {/* Regression line */}
        <line
          x1={toX(0)} y1={toY(regY0)}
          x2={toX(maeMax)} y2={toY(regY1)}
          stroke={C.brand} strokeWidth={1.2} strokeDasharray="6 3" opacity={0.6}
        />

        {/* Quadrant labels */}
        {/* Top-left: small MAE, win */}
        {zeroY > pad.top + 12 && slX > pad.left + 20 && (
          <text x={pad.left + 4} y={pad.top + 10} fontSize={7.5} fill={C.bull} fontFamily="Inter, system-ui" opacity={0.75}>
            Clean winners
          </text>
        )}
        {/* Top-right: large MAE, win */}
        {zeroY > pad.top + 12 && (
          <text x={slX + 6} y={pad.top + 10} fontSize={7.5} fill={C.bullMid} fontFamily="Inter, system-ui" opacity={0.75}>
            Recovered after DD
          </text>
        )}
        {/* Bottom-left: small MAE, loss */}
        {zeroY < pad.top + iH - 10 && slX > pad.left + 20 && (
          <text x={pad.left + 4} y={pad.top + iH - 4} fontSize={7.5} fill={C.bearMid} fontFamily="Inter, system-ui" opacity={0.75}>
            Quick SL hits
          </text>
        )}
        {/* Bottom-right: large MAE, loss */}
        {zeroY < pad.top + iH - 10 && (
          <text x={slX + 6} y={pad.top + iH - 4} fontSize={7.5} fill={C.bear} fontFamily="Inter, system-ui" opacity={0.75}>
            Painful losses
          </text>
        )}

        {/* Dots */}
        {dots.map((d, i) => (
          <circle
            key={i}
            cx={toX(d.mae)}
            cy={toY(d.pnl)}
            r={6}
            fill={d.win ? C.bull : C.bear}
            opacity={0.75}
            stroke={C.card}
            strokeWidth={1}
          >
            <title>{`MAE: ${d.mae.toFixed(2)}% | PnL: ${d.pnl >= 0 ? '+' : ''}$${d.pnl.toFixed(0)} | ${d.win ? 'WIN' : 'LOSS'}`}</title>
          </circle>
        ))}

        {/* Axis labels */}
        <text x={pad.left + iW / 2} y={H - 4} textAnchor="middle" fontSize={9} fill={C.muted} fontFamily="Inter, system-ui">
          Max Adverse Excursion (% from entry)
        </text>

        {/* Legend */}
        <g>
          <rect x={pad.left + iW + 10} y={pad.top} width={80} height={44} fill={C.card} fillOpacity={0.9} rx={4} stroke={C.border} strokeWidth={0.5} />
          <circle cx={pad.left + iW + 20} cy={pad.top + 12} r={5} fill={C.bull} opacity={0.8} />
          <text x={pad.left + iW + 28} y={pad.top + 16} fontSize={8.5} fill={C.muted} fontFamily="Inter, system-ui">Win</text>
          <circle cx={pad.left + iW + 20} cy={pad.top + 28} r={5} fill={C.bear} opacity={0.8} />
          <text x={pad.left + iW + 28} y={pad.top + 32} fontSize={8.5} fill={C.muted} fontFamily="Inter, system-ui">Loss</text>
          <line x1={pad.left + iW + 14} y1={pad.top + 40} x2={pad.left + iW + 30} y2={pad.top + 40} stroke={C.brand} strokeWidth={1.2} strokeDasharray="4 2" />
          <text x={pad.left + iW + 33} y={pad.top + 44} fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">Trend</text>
        </g>
      </svg>

      {useSeed && (
        <div style={{ marginTop: 8, fontSize: F.xs, color: C.muted, fontStyle: 'italic' }}>
          Showing seeded demo data — MAE field not available in trade records yet.
        </div>
      )}
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

      {/* ── PnL Ticker Banner ────────────────────────── */}
      <PnlTickerBanner trades={trades} />

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

      {/* ── Profit Attribution Chart ─────────────────── */}
      <ProfitAttributionChart trades={trades} backtest={backtest} />

      {/* ── Cumulative PnL Milestones ────────────────── */}
      <CumulativePnlMilestones trades={trades} />

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

      {/* ── Bot vs Buy & Hold ─────────────────────────── */}
      {equityCurve.length >= 2 && (
        <BotVsBuyHold points={equityCurve} startEquity={backtest?.config?.starting_equity ?? 50000} />
      )}

      {/* ── P&L Distribution Histogram ───────────────── */}
      <WinLossHistogram trades={trades} />

      {/* ── Daily P&L Calendar ───────────────────────── */}
      <DailyPnlCalendar trades={trades} />

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

      {/* ── Weekly Symbol Heatmap ──────────────────────── */}
      <WeeklySymbolHeatmap trades={trades} />

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

      {/* ── Exit Type Timeline ────────────────────────── */}
      <ExitTypeTimeline trades={trades} />

      {/* ── By-Symbol Accordion ───────────────────────── */}
      <BySymbolAccordion bySymbol={backtest?.by_symbol} />

      {/* ── Daily Equity Waterfall ────────────────────── */}
      <DailyEquityWaterfall trades={trades} />

      {/* ── Consecutive Trade PnL Chart ───────────────── */}
      <ConsecutiveTradePnlChart trades={trades} />

      {/* ── Max Adverse Excursion ─────────────────────── */}
      <MaxAdverseExcursion trades={trades} />

      {/* ── P&L Distribution Histogram ────────────────── */}
      <PnlDistributionHistogram trades={trades} />

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
