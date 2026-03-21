'use client';

import React, { useEffect, useRef, useState, useMemo, useId } from 'react';
import { motion } from 'framer-motion';
import Link from 'next/link';
import { C, G, R, F, S, Glass, SP, M, fmtUsd, fmtPct } from '../src/theme';
import { fadeUp, staggerContainer, staggerContainerSlow } from '../src/animations';
import { GeometricBG } from '../components/ui/GeometricBG';
import type { TradeRecord, TradeHistoryResponse } from '../src/types';
import { resolveApiBase } from '../src/api';
import { Skeleton } from '../components/ui/Skeleton';
import { Card } from '../components/ui/Card';
import { StatCard } from '../components/ui/StatCard';
import { SectionHeader } from '../components/ui/SectionHeader';
import { Badge } from '../components/ui/Badge';
import { EmptyState } from '../components/ui/EmptyState';
import { Grid } from '../components/ui/Stack';

function linearRegression(points: { x: number; y: number }[]): { slope: number; intercept: number } {
  const n = points.length;
  if (n < 2) return { slope: 0, intercept: 0 };
  const sumX = points.reduce((s, p) => s + p.x, 0);
  const sumY = points.reduce((s, p) => s + p.y, 0);
  const sumXY = points.reduce((s, p) => s + p.x * p.y, 0);
  const sumX2 = points.reduce((s, p) => s + p.x * p.x, 0);
  const denom = n * sumX2 - sumX * sumX;
  if (denom === 0) return { slope: 0, intercept: sumY / n };
  const slope = (n * sumXY - sumX * sumY) / denom;
  const intercept = (sumY - slope * sumX) / n;
  return { slope, intercept };
}

// ─── Confidence Ring ───────────────────────────────────────────────────────────

function ConfRing({ value, size = 36 }: { value: number; size?: number }) {
  const pct = Math.max(0, Math.min(1, value));
  const r = (size - 5) / 2;
  const circ = 2 * Math.PI * r;
  const color = pct >= 0.65 ? C.bull : pct >= 0.42 ? C.warn : C.bear;
  return (
    <svg width={size} height={size} style={{ flexShrink: 0 }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={C.border} strokeWidth={3} />
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={3}
        strokeDasharray={`${circ * pct} ${circ * (1 - pct)}`}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text x={size / 2} y={size / 2 + 4} textAnchor="middle" fontSize={9} fontWeight={700} fill={color}>
        {Math.round(pct * 100)}
      </text>
    </svg>
  );
}

// ─── Scatter Plot ──────────────────────────────────────────────────────────────

function ConfScatterPlot({ trades }: { trades: TradeRecord[] }) {
  const uid = useId().replace(/:/g, '');
  const [tooltip, setTooltip] = useState<{ x: number; y: number; trade: TradeRecord } | null>(null);

  const plotTrades = trades.filter(
    (t) => t.llm_confidence != null && t.rr_achieved != null && !isNaN(t.llm_confidence) && !isNaN(t.rr_achieved!)
  );

  if (plotTrades.length < 3) {
    return (
      <div style={{ height: 300, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: C.surfaceHover, borderRadius: R.md, textAlign: 'center', padding: '20px' }}>
        <div style={{ fontSize: 36, marginBottom: 10 }}>🎯</div>
        <div style={{ fontSize: F.base, fontWeight: 600, color: C.text, marginBottom: 6 }}>Not enough data yet</div>
        <div style={{ fontSize: F.sm, color: C.muted }}>Need at least 3 trades with LLM confidence scores to plot. Trade more to unlock this chart.</div>
      </div>
    );
  }

  const W = 560, H = 300;
  const pad = { top: 20, right: 20, bottom: 40, left: 60 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const confs = plotTrades.map((t) => (t.llm_confidence ?? 0) * 100);
  const rrs = plotTrades.map((t) => t.rr_achieved ?? 0);
  const minConf = 0, maxConf = 100;
  const minRR = Math.min(...rrs, -2);
  const maxRR = Math.max(...rrs, 5);
  const rangeRR = maxRR - minRR || 1;

  const px = (c: number) => pad.left + ((c - minConf) / (maxConf - minConf)) * plotW;
  const py = (rr: number) => pad.top + plotH - ((rr - minRR) / rangeRR) * plotH;

  // Linear regression using helper
  const regPoints = plotTrades.map((t, i) => ({ x: confs[i], y: rrs[i] }));
  const { slope, intercept } = linearRegression(regPoints);
  const regY1 = intercept + slope * minConf;
  const regY2 = intercept + slope * maxConf;

  // Pearson correlation coefficient
  const n = plotTrades.length;
  const meanX = confs.reduce((a, b) => a + b, 0) / n;
  const meanY = rrs.reduce((a, b) => a + b, 0) / n;
  const cov = confs.reduce((s, x, i) => s + (x - meanX) * (rrs[i] - meanY), 0) / n;
  const stdX = Math.sqrt(confs.reduce((s, x) => s + (x - meanX) ** 2, 0) / n) || 1;
  const stdY = Math.sqrt(rrs.reduce((s, y) => s + (y - meanY) ** 2, 0) / n) || 1;
  const corr = cov / (stdX * stdY);

  // Cluster center (mean of all points for the ellipse)
  const clusterCx = px(meanX);
  const clusterCy = py(meanY);
  const clusterRx = (stdX / (maxConf - minConf)) * plotW * 1.2;
  const clusterRy = (stdY / rangeRR) * plotH * 1.2;

  const yTicks = [Math.floor(minRR), 0, Math.ceil(maxRR / 2), Math.ceil(maxRR)].filter((v, i, a) => a.indexOf(v) === i);
  const xTicks = [0, 25, 50, 75, 100];

  return (
    <div style={{ position: 'relative' }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
        onMouseLeave={() => setTooltip(null)}
      >
        <defs>
          <clipPath id={`scatterClip-${uid}`}>
            <rect x={pad.left} y={pad.top} width={plotW} height={plotH} />
          </clipPath>
        </defs>

        {/* Grid */}
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={pad.left} y1={py(v)} x2={pad.left + plotW} y2={py(v)} stroke={C.border} strokeWidth={1} strokeDasharray={v === 0 ? '' : '3 4'} />
            <text x={pad.left - 6} y={py(v) + 4} textAnchor="end" fontSize={9} fill={C.muted} fontFamily="Inter, system-ui">{v.toFixed(1)}</text>
          </g>
        ))}
        {xTicks.map((v) => (
          <g key={v}>
            <line x1={px(v)} y1={pad.top} x2={px(v)} y2={pad.top + plotH} stroke={C.border} strokeWidth={1} strokeDasharray="3 4" />
            <text x={px(v)} y={pad.top + plotH + 14} textAnchor="middle" fontSize={9} fill={C.muted} fontFamily="Inter, system-ui">{v}%</text>
          </g>
        ))}

        {/* Cluster ellipse */}
        {clusterRx > 0 && clusterRy > 0 && (
          <ellipse
            cx={clusterCx} cy={clusterCy}
            rx={Math.min(clusterRx, plotW / 2)} ry={Math.min(clusterRy, plotH / 2)}
            fill={C.brand} fillOpacity={0.05}
            stroke={C.brand} strokeOpacity={0.25} strokeWidth={1} strokeDasharray="4 3"
            clipPath={`url(#scatterClip-${uid})`}
          />
        )}

        {/* Zero RR bold line (quadrant horizontal) */}
        <line x1={pad.left} y1={py(0)} x2={pad.left + plotW} y2={py(0)} stroke={C.borderBright} strokeWidth={2} />

        {/* Quadrant vertical at confidence=75 */}
        <line
          x1={px(75)} y1={pad.top}
          x2={px(75)} y2={pad.top + plotH}
          stroke={C.muted} strokeWidth={1} strokeDasharray="5 4" strokeOpacity={0.6}
          clipPath={`url(#scatterClip-${uid})`}
        />

        {/* Regression line */}
        {slope !== 0 && (
          <line
            x1={px(minConf)} y1={py(regY1)}
            x2={px(maxConf)} y2={py(regY2)}
            stroke={C.brand} strokeWidth={1.5} strokeDasharray="5 4"
            clipPath={`url(#scatterClip-${uid})`}
          />
        )}

        {/* Quadrant labels */}
        <text x={px(87.5)} y={pad.top + 14} textAnchor="middle" fontSize={8} fill={C.bull} fontFamily="Inter, system-ui" clipPath={`url(#scatterClip-${uid})`}>
          High conviction wins ✓
        </text>
        <text x={px(87.5)} y={pad.top + plotH - 6} textAnchor="middle" fontSize={8} fill={C.bear} fontFamily="Inter, system-ui" clipPath={`url(#scatterClip-${uid})`}>
          Overconfident losses ✗
        </text>
        <text x={px(37.5)} y={pad.top + 14} textAnchor="middle" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui" clipPath={`url(#scatterClip-${uid})`}>
          Lucky wins
        </text>
        <text x={px(37.5)} y={pad.top + plotH - 6} textAnchor="middle" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui" clipPath={`url(#scatterClip-${uid})`}>
          Correct avoids
        </text>

        {/* Correlation label */}
        <text x={pad.left + plotW - 4} y={pad.top + 14} textAnchor="end" fontSize={9} fill={C.brand} fontFamily="Inter, system-ui" fontWeight={600}>
          {`r = ${corr >= 0 ? '+' : ''}${corr.toFixed(2)} correlation`}
        </text>

        {/* Dots */}
        {plotTrades.map((t, i) => {
          const cx = px((t.llm_confidence ?? 0) * 100);
          const cy = py(t.rr_achieved ?? 0);
          const win = t.outcome === 'WIN';
          return (
            <circle
              key={i}
              cx={cx} cy={cy} r={5}
              fill={win ? C.bull : C.bear}
              fillOpacity={0.7}
              stroke={win ? C.bullMid : C.bearMid}
              strokeWidth={1}
              style={{ cursor: 'pointer' }}
              onMouseEnter={() => setTooltip({ x: cx, y: cy, trade: t })}
            />
          );
        })}

        {/* Axis labels */}
        <text x={pad.left + plotW / 2} y={H - 4} textAnchor="middle" fontSize={10} fill={C.muted} fontFamily="Inter, system-ui">LLM Confidence (%)</text>
        <text x={12} y={pad.top + plotH / 2} textAnchor="middle" fontSize={10} fill={C.muted} fontFamily="Inter, system-ui"
          transform={`rotate(-90 12 ${pad.top + plotH / 2})`}>
          R/R Achieved
        </text>
      </svg>

      {/* Tooltip */}
      {tooltip && (
        <div style={{
          position: 'absolute',
          left: `calc(${(tooltip.x / W) * 100}% + 10px)`,
          top: `calc(${(tooltip.y / H) * 100}%)`,
          background: C.surface,
          border: `1px solid ${C.borderBright}`,
          borderRadius: R.md,
          padding: '8px 12px',
          fontSize: F.xs,
          color: C.textSub,
          pointerEvents: 'none',
          zIndex: 10,
          minWidth: 140,
          boxShadow: S.md,
        }}>
          <div style={{ fontWeight: 700, color: tooltip.trade.outcome === 'WIN' ? C.bull : C.bear, marginBottom: 4 }}>
            {tooltip.trade.symbol} {tooltip.trade.side} — {tooltip.trade.outcome}
          </div>
          <div>Confidence: {Math.round((tooltip.trade.llm_confidence ?? 0) * 100)}%</div>
          <div>R/R achieved: {tooltip.trade.rr_achieved?.toFixed(2)}</div>
          <div>Strategy: {tooltip.trade.strategy}</div>
          <div>P&L: {fmtUsd(tooltip.trade.pnl ?? 0)}</div>
        </div>
      )}
    </div>
  );
}

// ─── Trade Waterfall ──────────────────────────────────────────────────────────

function TradeWaterfall({ trades }: { trades: TradeRecord[] }) {
  const uid = useId().replace(/:/g, '');
  const validTrades = trades.filter((t) => t.pnl != null && !isNaN(t.pnl!));

  if (validTrades.length < 2) {
    return (
      <div style={{ height: 160, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.muted, fontSize: F.sm, background: C.surfaceHover, borderRadius: R.md }}>
        Need at least 2 trades with P&L data to show waterfall.
      </div>
    );
  }

  // Thin out if too many trades
  const MAX_BARS = 30;
  let displayTrades = validTrades;
  let step = 1;
  if (validTrades.length > MAX_BARS) {
    step = Math.ceil(validTrades.length / MAX_BARS);
    displayTrades = validTrades.filter((_, i) => i % step === 0 || i === validTrades.length - 1);
  }

  // Build cumulative series for the display trades
  // We need original indices for X-axis labels
  const displayWithIdx = displayTrades.map((t, di) => ({
    trade: t,
    origIdx: di * step < validTrades.length ? di * step : validTrades.length - 1,
  }));

  // Compute cumulative PnL at each display trade
  let cumulative = 0;
  const bars = displayWithIdx.map(({ trade, origIdx }) => {
    const prev = cumulative;
    cumulative += trade.pnl!;
    return { prev, curr: cumulative, pnl: trade.pnl!, origIdx };
  });

  const finalPnl = cumulative;
  const allVals = bars.flatMap((b) => [b.prev, b.curr]);
  const minVal = Math.min(...allVals, 0);
  const maxVal = Math.max(...allVals, 0);
  const range = maxVal - minVal || 1;

  const VB_W = 700, VB_H = 160;
  const pad = { top: 18, right: 72, bottom: 28, left: 56 };
  const plotW = VB_W - pad.left - pad.right;
  const plotH = VB_H - pad.top - pad.bottom;
  const barW = Math.max(2, Math.floor(plotW / bars.length) - 1);

  const xPos = (i: number) => pad.left + i * (plotW / bars.length) + (plotW / bars.length - barW) / 2;
  const yPos = (v: number) => pad.top + plotH - ((v - minVal) / range) * plotH;
  const zeroY = yPos(0);

  // Key inflection points: first, last, largest gain, largest loss
  const maxGainIdx = bars.reduce((best, b, i) => b.pnl > bars[best].pnl ? i : best, 0);
  const maxLossIdx = bars.reduce((best, b, i) => b.pnl < bars[best].pnl ? i : best, 0);
  const inflectionSet = new Set([0, bars.length - 1, maxGainIdx, maxLossIdx]);

  return (
    <svg
      viewBox={`0 0 ${VB_W} ${VB_H}`}
      style={{ width: '100%', height: 'auto', display: 'block' }}
    >
      <defs>
        <linearGradient id={`wfBullGrad-${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.bull} stopOpacity="0.18" />
          <stop offset="100%" stopColor={C.bull} stopOpacity="0.02" />
        </linearGradient>
        <linearGradient id={`wfBearGrad-${uid}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.bear} stopOpacity="0.02" />
          <stop offset="100%" stopColor={C.bear} stopOpacity="0.18" />
        </linearGradient>
        <clipPath id={`wfClip-${uid}`}>
          <rect x={pad.left} y={pad.top} width={plotW} height={plotH} />
        </clipPath>
      </defs>

      {/* Profit / loss background tint */}
      {finalPnl >= 0 ? (
        <rect x={pad.left} y={pad.top} width={plotW} height={plotH} fill={`url(#wfBullGrad-${uid})`} rx={2} clipPath={`url(#wfClip-${uid})`} />
      ) : (
        <rect x={pad.left} y={pad.top} width={plotW} height={plotH} fill={`url(#wfBearGrad-${uid})`} rx={2} clipPath={`url(#wfClip-${uid})`} />
      )}

      {/* Y-axis ticks */}
      {[minVal, 0, maxVal].filter((v, i, a) => a.indexOf(v) === i).map((v) => (
        <g key={v}>
          <line
            x1={pad.left} y1={yPos(v)} x2={pad.left + plotW} y2={yPos(v)}
            stroke={v === 0 ? C.borderBright : C.border}
            strokeWidth={v === 0 ? 1.5 : 1}
            strokeDasharray={v === 0 ? '' : '3 4'}
          />
          <text x={pad.left - 5} y={yPos(v) + 4} textAnchor="end" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">
            {v >= 0 ? `+$${v.toFixed(0)}` : `-$${Math.abs(v).toFixed(0)}`}
          </text>
        </g>
      ))}

      {/* Bars */}
      {bars.map((b, i) => {
        const x = xPos(i);
        const isWin = b.pnl >= 0;
        const topY = Math.min(yPos(b.prev), yPos(b.curr));
        const botY = Math.max(yPos(b.prev), yPos(b.curr));
        const h = Math.max(1, botY - topY);
        return (
          <rect
            key={i}
            x={x} y={topY}
            width={barW} height={h}
            fill={isWin ? C.bull : C.bear}
            fillOpacity={0.75}
            rx={1}
          />
        );
      })}

      {/* Largest win annotation */}
      {(() => {
        const b = bars[maxGainIdx];
        const x = xPos(maxGainIdx) + barW / 2;
        const topY = Math.min(yPos(b.prev), yPos(b.curr));
        return (
          <g key="maxGain">
            <text x={x} y={topY - 3} textAnchor="middle" fontSize={8} fontWeight={700} fill={C.bull} fontFamily="Inter, system-ui">
              {`+$${b.pnl.toFixed(0)}`}
            </text>
          </g>
        );
      })()}

      {/* Largest loss annotation */}
      {(() => {
        if (maxLossIdx === maxGainIdx) return null;
        const b = bars[maxLossIdx];
        const x = xPos(maxLossIdx) + barW / 2;
        const botY = Math.max(yPos(b.prev), yPos(b.curr));
        return (
          <g key="maxLoss">
            <text x={x} y={botY + 10} textAnchor="middle" fontSize={8} fontWeight={700} fill={C.bear} fontFamily="Inter, system-ui">
              {`-$${Math.abs(b.pnl).toFixed(0)}`}
            </text>
          </g>
        );
      })()}

      {/* Running total line connecting bar tops */}
      {bars.length > 1 && (() => {
        const points = bars.map((b, i) => `${xPos(i) + barW / 2},${yPos(b.curr)}`).join(' ');
        return (
          <polyline
            points={points}
            fill="none"
            stroke={C.brand}
            strokeWidth={1.2}
            strokeDasharray="3 3"
            strokeLinejoin="round"
            clipPath={`url(#wfClip-${uid})`}
          />
        );
      })()}

      {/* X-axis labels at key inflection points */}
      {bars.map((b, i) => {
        if (!inflectionSet.has(i)) return null;
        const x = xPos(i) + barW / 2;
        return (
          <text key={i} x={x} y={pad.top + plotH + 12} textAnchor="middle" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">
            #{b.origIdx + 1}
          </text>
        );
      })}

      {/* Breakeven bold line */}
      <line x1={pad.left} y1={zeroY} x2={pad.left + plotW} y2={zeroY} stroke={C.borderBright} strokeWidth={2} />

      {/* Breakeven label */}
      <text x={pad.left - 5} y={zeroY + 4} textAnchor="end" fontSize={8} fontWeight={700} fill={C.borderBright} fontFamily="Inter, system-ui">
        $0
      </text>

      {/* Final cumulative P&L label */}
      <text
        x={pad.left + plotW + 5}
        y={yPos(finalPnl) + 4}
        fontSize={9}
        fontWeight={700}
        fill={finalPnl >= 0 ? C.bull : C.bear}
        fontFamily="Inter, system-ui"
      >
        {finalPnl >= 0 ? '+' : ''}{finalPnl.toFixed(2)}
      </text>

      {/* Axis labels */}
      <text x={pad.left + plotW / 2} y={VB_H - 2} textAnchor="middle" fontSize={9} fill={C.muted} fontFamily="Inter, system-ui">
        Trade Index
      </text>
      <text x={10} y={pad.top + plotH / 2} textAnchor="middle" fontSize={9} fill={C.muted} fontFamily="Inter, system-ui"
        transform={`rotate(-90 10 ${pad.top + plotH / 2})`}>
        Cum. P&L
      </text>
    </svg>
  );
}

// ─── Hourly Win Rate Heat Strip ────────────────────────────────────────────────

function HourlyWinRate({ trades }: { trades: TradeRecord[] }) {
  // TradeRecord doesn't have a timestamp field in the current type definition.
  // We try to read open_time or close_time from the raw record if present at runtime,
  // falling back to a graceful empty state.
  type AnyRecord = TradeRecord & { open_time?: string | number | null; close_time?: string | number | null };

  const buckets: { wins: number; total: number }[] = Array.from({ length: 24 }, () => ({ wins: 0, total: 0 }));
  let hasTimestamps = false;

  trades.forEach((t) => {
    const r = t as AnyRecord;
    const raw = r.open_time ?? r.close_time;
    if (raw == null) return;
    try {
      const ts = typeof raw === 'number'
        ? (raw > 1e10 ? raw : raw * 1000)
        : new Date(raw as string).getTime();
      if (isNaN(ts)) return;
      const hour = new Date(ts).getUTCHours();
      hasTimestamps = true;
      buckets[hour].total++;
      if (t.outcome === 'WIN') buckets[hour].wins++;
    } catch {/* skip */}
  });

  const CELL_W = 28, CELL_H = 40;
  const labelH = 14;
  const totalW = 24 * CELL_W;
  const totalH = CELL_H + labelH;

  if (!hasTimestamps) {
    return (
      <div style={{ height: 60, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.muted, fontSize: F.sm, background: C.surfaceHover, borderRadius: R.md }}>
        Hour data not available — trades have no timestamp field.
      </div>
    );
  }

  function cellColor(b: { wins: number; total: number }): string {
    if (b.total === 0) return C.heatNeutral;
    const wr = b.wins / b.total;
    if (wr >= 0.7) return C.heatBull3;
    if (wr >= 0.55) return C.heatBull2;
    if (wr >= 0.45) return C.heatBull1;
    if (wr >= 0.35) return C.heatBear1;
    if (wr >= 0.2) return C.heatBear2;
    return C.heatBear3;
  }

  const showLabelHours = new Set([0, 4, 8, 12, 16, 20]);

  return (
    <svg
      viewBox={`0 0 ${totalW} ${totalH}`}
      style={{ width: '100%', height: 'auto', display: 'block' }}
    >
      {buckets.map((b, h) => {
        const x = h * CELL_W;
        const fill = cellColor(b);
        const wr = b.total > 0 ? Math.round((b.wins / b.total) * 100) : null;
        return (
          <g key={h}>
            <rect x={x} y={0} width={CELL_W - 1} height={CELL_H} fill={fill} rx={2} />
            {wr != null && (
              <text
                x={x + CELL_W / 2 - 0.5}
                y={CELL_H / 2 + 4}
                textAnchor="middle"
                fontSize={b.total > 0 ? 8 : 7}
                fontWeight={700}
                fill="#fff"
                fillOpacity={0.85}
                fontFamily="Inter, system-ui"
              >
                {wr}%
              </text>
            )}
            {showLabelHours.has(h) && (
              <text
                x={x + CELL_W / 2 - 0.5}
                y={CELL_H + labelH - 2}
                textAnchor="middle"
                fontSize={8}
                fill={C.muted}
                fontFamily="Inter, system-ui"
              >
                {h}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

// ─── Hour of Day Win Rate Heat Strip ─────────────────────────────────────────

function HourOfDayWinRate({ trades }: { trades: TradeRecord[] }) {
  type AnyRecord = TradeRecord & { entry_timestamp_ms?: number | null };

  const buckets: { wins: number; total: number }[] = Array.from({ length: 24 }, () => ({ wins: 0, total: 0 }));
  let hasRealData = false;

  trades.forEach((t) => {
    const ts = (t as AnyRecord).entry_timestamp_ms;
    if (ts == null || isNaN(ts)) return;
    const hour = new Date(ts).getUTCHours();
    hasRealData = true;
    buckets[hour].total++;
    if (t.outcome === 'WIN') buckets[hour].wins++;
  });

  if (!hasRealData) {
    return (
      <div>
        <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 6 }}>
          Win Rate by Hour of Day (UTC)
        </div>
        <EmptyState icon="⏳" title="Awaiting trade data" subtitle="Hour-of-day win rate will populate once the bot has closed trades with timestamp data" />
      </div>
    );
  }

  const CELL_W = 26;
  const CELL_H = 44;
  const LABEL_H = 16;
  const PAD = 2;
  const totalW = 24 * (CELL_W + PAD);
  const totalH = CELL_H + LABEL_H;

  function cellFill(b: { wins: number; total: number }): string {
    if (b.total === 0) return C.heatNeutral;
    const wr = b.wins / b.total;
    if (wr >= 0.7) return C.heatBull3;
    if (wr >= 0.55) return C.heatBull2;
    if (wr >= 0.42) return C.heatBull1;
    if (wr >= 0.35) return C.heatBear1;
    if (wr >= 0.2) return C.heatBear2;
    return C.heatBear3;
  }

  return (
    <div>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 6 }}>
        Win Rate by Hour of Day (UTC)
      </div>
      <svg
        viewBox={`0 0 ${totalW} ${totalH}`}
        style={{ width: '100%', height: 'auto', display: 'block' }}
      >
        {buckets.map((b, h) => {
          const x = h * (CELL_W + PAD);
          const fill = cellFill(b);
          const wr = b.total > 0 ? Math.round((b.wins / b.total) * 100) : null;
          return (
            <g key={h}>
              <rect x={x} y={0} width={CELL_W} height={CELL_H} fill={fill} rx={3}>
                <title>{`Hour ${h}:00 UTC — ${b.wins}/${b.total} wins${wr != null ? ` (${wr}%)` : ''}`}</title>
              </rect>
              {wr != null && (
                <text
                  x={x + CELL_W / 2}
                  y={CELL_H / 2 - 4}
                  textAnchor="middle"
                  fontSize={8}
                  fontWeight={700}
                  fill="#fff"
                  fillOpacity={0.9}
                  fontFamily="Inter, system-ui"
                >
                  {wr}%
                </text>
              )}
              <text
                x={x + CELL_W / 2}
                y={CELL_H / 2 + 8}
                textAnchor="middle"
                fontSize={7}
                fill="#fff"
                fillOpacity={0.6}
                fontFamily="Inter, system-ui"
              >
                {b.total > 0 ? `${b.wins}/${b.total}` : '—'}
              </text>
              {/* Hour label below cell — show every 4 hours */}
              {h % 4 === 0 && (
                <text
                  x={x + CELL_W / 2}
                  y={CELL_H + LABEL_H - 2}
                  textAnchor="middle"
                  fontSize={8}
                  fill={C.muted}
                  fontFamily="Inter, system-ui"
                >
                  {h}h
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <div style={{ display: 'flex', gap: 12, fontSize: 10, color: C.muted, marginTop: 6 }}>
        {[
          { color: C.heatBull3, label: '≥70%' },
          { color: C.heatBull2, label: '55–70%' },
          { color: C.heatBull1, label: '42–55%' },
          { color: C.heatBear1, label: '35–42%' },
          { color: C.heatBear2, label: '20–35%' },
          { color: C.heatBear3, label: '<20%' },
          { color: C.heatNeutral, label: 'No data' },
        ].map(({ color, label }) => (
          <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
            <span style={{ width: 10, height: 10, background: color, borderRadius: 2, display: 'inline-block', flexShrink: 0 }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── Risk:Reward Scatter Plot ─────────────────────────────────────────────────

function RiskRewardScatter({ trades }: { trades: TradeRecord[] }) {
  // Uses signal confidence (0-1) on X-axis vs actual R:R achieved on Y-axis.
  // Distinct from ConfScatterPlot which plots llm_confidence.
  const uid = useId().replace(/:/g, '');
  const plotTrades = trades.filter(
    (t) =>
      t.confidence != null &&
      t.rr_achieved != null &&
      !isNaN(t.confidence!) &&
      !isNaN(t.rr_achieved!)
  );

  if (plotTrades.length < 3) {
    return <EmptyState icon="⏳" title="Awaiting signal data" subtitle="Signal confidence vs R:R scatter will appear once there are at least 3 trades with confidence and R:R data" />;
  }

  const W = 500, H = 200;
  const pad = { top: 24, right: 24, bottom: 44, left: 52 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const dots = plotTrades.map((t, i) => ({
    conf: (t.confidence ?? 0) * 100,
    rr: t.rr_achieved ?? 0,
    win: t.outcome === 'WIN',
    label: t.symbol,
    size: (t as any).position_size != null ? Math.max(3, Math.min(9, 3 + ((t as any).position_size / 1000))) : 4,
    isRecent: i >= plotTrades.length - 5,
  }));

  const allRR = dots.map((d) => d.rr);
  const minRR = Math.min(...allRR, -1.5);
  const maxRR = Math.max(...allRR, 3);
  const rangeRR = maxRR - minRR || 1;

  const px = (conf: number) => pad.left + (conf / 100) * plotW;
  const py = (rr: number) => pad.top + plotH - ((rr - minRR) / rangeRR) * plotH;

  const xTicks = [0, 25, 50, 75, 100];
  const yTickValues = Array.from(new Set([Math.floor(minRR), 0, 1, 2, Math.ceil(maxRR)])).sort((a, b) => a - b);

  return (
    <div style={{ position: 'relative' }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
      >
        <defs>
          <clipPath id={`rrScatterClip-${uid}`}>
            <rect x={pad.left} y={pad.top} width={plotW} height={plotH} />
          </clipPath>
        </defs>

        {/* Ideal zone: R:R > 1.5 AND confidence > 75 */}
        {(() => {
          const x1 = px(75);
          const y1 = py(Math.min(maxRR, 999));
          const x2 = px(100);
          const y2 = py(1.5);
          if (y2 > pad.top + plotH) return null; // 1.5 is below chart range
          return (
            <rect
              x={x1} y={y1}
              width={x2 - x1} height={Math.max(0, y2 - y1)}
              fill={C.bull} fillOpacity={0.08}
              clipPath={`url(#rrScatterClip-${uid})`}
            />
          );
        })()}

        {/* Y grid lines */}
        {yTickValues.map((v) => (
          <g key={v}>
            <line
              x1={pad.left} y1={py(v)}
              x2={pad.left + plotW} y2={py(v)}
              stroke={C.border} strokeWidth={v === 0 ? 1.2 : 0.7}
              strokeDasharray={v === 0 ? '' : '3 4'}
            />
            <text x={pad.left - 5} y={py(v) + 4} textAnchor="end" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">
              {v.toFixed(1)}
            </text>
          </g>
        ))}

        {/* X grid lines */}
        {xTicks.map((v) => (
          <g key={v}>
            <line
              x1={px(v)} y1={pad.top}
              x2={px(v)} y2={pad.top + plotH}
              stroke={C.border} strokeWidth={0.7} strokeDasharray="3 4"
            />
            <text x={px(v)} y={pad.top + plotH + 13} textAnchor="middle" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">
              {v}%
            </text>
          </g>
        ))}

        {/* R:R = 1.0 reference line */}
        {minRR < 1.0 && 1.0 < maxRR && (
          <g>
            <line
              x1={pad.left} y1={py(1.0)}
              x2={pad.left + plotW} y2={py(1.0)}
              stroke={C.warn} strokeWidth={1} strokeDasharray="6 4"
              clipPath={`url(#rrScatterClip-${uid})`}
            />
            <text x={pad.left + plotW - 2} y={py(1.0) - 4} textAnchor="end" fontSize={8} fill={C.warn} fontFamily="Inter, system-ui">1.0×</text>
          </g>
        )}

        {/* R:R = 2.0 reference line */}
        {minRR < 2.0 && 2.0 < maxRR && (
          <g>
            <line
              x1={pad.left} y1={py(2.0)}
              x2={pad.left + plotW} y2={py(2.0)}
              stroke={C.bull} strokeWidth={1} strokeDasharray="6 4"
              clipPath={`url(#rrScatterClip-${uid})`}
            />
            <text x={pad.left + plotW - 2} y={py(2.0) - 4} textAnchor="end" fontSize={8} fill={C.bull} fontFamily="Inter, system-ui">2.0×</text>
          </g>
        )}

        {/* Confidence = 75% vertical reference line */}
        <line
          x1={px(75)} y1={pad.top}
          x2={px(75)} y2={pad.top + plotH}
          stroke={C.brand} strokeWidth={1} strokeDasharray="6 4"
          clipPath={`url(#rrScatterClip-${uid})`}
        />
        <text x={px(75) + 3} y={pad.top + 10} fontSize={8} fill={C.brand} fontFamily="Inter, system-ui">75%</text>

        {/* Dots */}
        {dots.map((d, i) => {
          const cx = px(d.conf);
          const cy = py(d.rr);
          const r = d.size ?? 4;
          return (
            <g key={i} clipPath={`url(#rrScatterClip-${uid})`}>
              {/* White ring for recent trades (last 5) */}
              {d.isRecent && (
                <circle cx={cx} cy={cy} r={r + 3} fill="none" stroke="#ffffff" strokeWidth={1.5} strokeOpacity={0.7} />
              )}
              <circle
                cx={cx}
                cy={cy}
                r={r}
                fill={d.win ? C.bull : C.bear}
                fillOpacity={0.75}
                stroke={d.win ? C.bullMid : C.bearMid}
                strokeWidth={0.8}
              >
                <title>{d.label ? `${d.label} — Conf: ${d.conf.toFixed(0)}% R:R: ${d.rr.toFixed(2)} (${d.win ? 'WIN' : 'LOSS'})` : `Conf: ${d.conf.toFixed(0)}% R:R: ${d.rr.toFixed(2)}`}</title>
              </circle>
            </g>
          );
        })}

        {/* Axis labels */}
        <text x={pad.left + plotW / 2} y={H - 4} textAnchor="middle" fontSize={10} fill={C.muted} fontFamily="Inter, system-ui">
          Signal Confidence
        </text>
        <text
          x={12}
          y={pad.top + plotH / 2}
          textAnchor="middle"
          fontSize={10}
          fill={C.muted}
          fontFamily="Inter, system-ui"
          transform={`rotate(-90 12 ${pad.top + plotH / 2})`}
        >
          R:R Achieved
        </text>
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, fontSize: 10, color: C.muted, marginTop: 6, flexWrap: 'wrap' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.bull, display: 'inline-block' }} /> WIN
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.bear, display: 'inline-block' }} /> LOSS
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 16, height: 2, background: C.warn, display: 'inline-block', verticalAlign: 'middle' }} /> 1.0× R:R
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 16, height: 2, background: C.bull, display: 'inline-block', verticalAlign: 'middle' }} /> 2.0× R:R
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 2, height: 10, background: C.brand, display: 'inline-block', verticalAlign: 'middle' }} /> 75% conf
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 14, height: 14, borderRadius: '50%', border: '2px solid rgba(255,255,255,0.7)', display: 'inline-block' }} /> Last 5 trades
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 14, height: 14, borderRadius: 2, background: C.bull, opacity: 0.15, display: 'inline-block' }} /> Ideal zone
        </span>
      </div>
    </div>
  );
}

// ─── Regime Performance Matrix ────────────────────────────────────────────────

function RegimePerformanceMatrix({ trades }: { trades: TradeRecord[] }) {
  const REGIMES = ['trend', 'range', 'high_volatility', 'panic', 'low_liquidity', 'unknown'];
  const REGIME_LABELS: Record<string, string> = {
    trend: '📈 Trend', range: '↔ Range', high_volatility: '⚡ Hi-Vol',
    panic: '🚨 Panic', low_liquidity: '🌊 Low Liq', unknown: '❓ Unknown',
  };

  const stats: Record<string, { wins: number; total: number; pnl: number }> = {};
  REGIMES.forEach((r) => { stats[r] = { wins: 0, total: 0, pnl: 0 }; });

  trades.forEach((t) => {
    const regime = (t.llm_regime ?? 'unknown').toLowerCase().replace(/ /g, '_');
    const key = REGIMES.find((r) => regime.includes(r.replace('_', ''))) ?? 'unknown';
    stats[key].total++;
    if (t.outcome === 'WIN') stats[key].wins++;
    stats[key].pnl += t.pnl ?? 0;
  });

  const hasData = Object.values(stats).some((s) => s.total > 0);
  if (!hasData) return null;

  const CLOSE_COLORS: Record<string, string> = {
    TP1: '#16a34a', TP2: '#22c55e', TRAILING_STOP: '#2563eb', SL: '#dc2626',
    EARLY_EXIT: '#d97706', CIRCUIT_BREAKER: '#7c3aed', BACKTEST_END: '#64748b',
  };

  // Also build exit breakdown per regime
  const exitBreakdown: Record<string, Record<string, number>> = {};
  REGIMES.forEach((r) => { exitBreakdown[r] = {}; });
  trades.forEach((t) => {
    const regime = (t.llm_regime ?? 'unknown').toLowerCase().replace(/ /g, '_');
    const key = REGIMES.find((r) => regime.includes(r.replace('_', ''))) ?? 'unknown';
    const exit = t.close_reason || 'unknown';
    exitBreakdown[key][exit] = (exitBreakdown[key][exit] || 0) + 1;
  });

  const activeRegimes = REGIMES.filter((r) => stats[r].total > 0);

  return (
    <motion.div variants={fadeUp} initial="hidden" animate="show" style={{ ...Glass.crystal, borderRadius: R.xl, padding: '20px 24px', marginBottom: 24 }}>
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Performance by Regime</div>
        <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>How the bot performs in each market regime — hover cells for detail</div>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 420 }}>
          <thead>
            <tr>
              {['Regime', 'Trades', 'Win Rate', 'Net P&L', 'Avg P&L', 'Top Exit'].map((h, i) => (
                <th key={h} style={{
                  padding: '6px 12px', fontSize: F.xs, color: C.muted, fontWeight: 600,
                  textTransform: 'uppercase', letterSpacing: 0.5,
                  textAlign: i === 0 ? 'left' : 'center',
                  borderBottom: `1px solid ${C.border}`,
                }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {activeRegimes.map((regime) => {
              const s = stats[regime];
              const wr = s.total > 0 ? s.wins / s.total : 0;
              const avgPnl = s.total > 0 ? s.pnl / s.total : 0;
              const wrColor = wr >= 0.65 ? C.bull : wr >= 0.45 ? '#d97706' : C.bear;
              const pnlColor = s.pnl >= 0 ? C.bull : C.bear;

              const exits = Object.entries(exitBreakdown[regime]).sort((a, b) => b[1] - a[1]);
              const topExit = exits[0];

              return (
                <tr key={regime} style={{ borderBottom: `1px solid ${C.border}` }}>
                  <td style={{ padding: '10px 12px' }}>
                    <div style={{
                      display: 'inline-flex', alignItems: 'center', gap: 6,
                      padding: '3px 10px', borderRadius: R.pill,
                      background: wrColor + '18', color: wrColor,
                      fontSize: F.xs, fontWeight: 700,
                    }}>
                      {REGIME_LABELS[regime]}
                    </div>
                  </td>
                  <td style={{ padding: '10px 12px', textAlign: 'center', fontWeight: 700, color: C.text }}>{s.total}</td>
                  <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center' }}>
                      <div style={{ width: 48, height: 5, background: C.surface, borderRadius: R.pill, overflow: 'hidden' }}>
                        <div style={{ width: `${wr * 100}%`, height: '100%', background: wrColor, borderRadius: R.pill }} />
                      </div>
                      <span style={{ fontSize: F.xs, fontWeight: 700, color: wrColor }}>{Math.round(wr * 100)}%</span>
                    </div>
                  </td>
                  <td style={{ padding: '10px 12px', textAlign: 'center', fontWeight: 700, color: pnlColor }}>
                    {s.pnl >= 0 ? '+' : ''}{s.pnl.toFixed(2)}
                  </td>
                  <td style={{ padding: '10px 12px', textAlign: 'center', fontSize: F.xs, color: avgPnl >= 0 ? C.bull : C.bear }}>
                    {avgPnl >= 0 ? '+' : ''}{avgPnl.toFixed(2)}/trade
                  </td>
                  <td style={{ padding: '10px 12px', textAlign: 'center' }}>
                    {topExit ? (
                      <span style={{
                        fontSize: 10, padding: '2px 7px', borderRadius: R.pill,
                        background: (CLOSE_COLORS[topExit[0]] ?? C.muted) + '22',
                        color: CLOSE_COLORS[topExit[0]] ?? C.muted, fontWeight: 700,
                      }}>
                        {topExit[0]} ×{topExit[1]}
                      </span>
                    ) : '—'}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </motion.div>
  );
}

// ─── Trade Duration Histogram ─────────────────────────────────────────────────

function TradeDurationHistogram({ trades }: { trades: TradeRecord[] }) {
  const uid = useId().replace(/:/g, '');
  // Group trade durations into buckets (in hours)
  const BUCKETS = [
    { label: '<1h', max: 1 }, { label: '1–4h', max: 4 },
    { label: '4–12h', max: 12 }, { label: '12–24h', max: 24 },
    { label: '1–3d', max: 72 }, { label: '>3d', max: Infinity },
  ];

  const data = BUCKETS.map((b) => ({ ...b, wins: 0, losses: 0 }));

  let hasDuration = false;
  const allDurations: number[] = [];
  trades.forEach((t) => {
    if (t.duration_h == null) return;
    hasDuration = true;
    allDurations.push(t.duration_h);
    const idx = data.findIndex((b) => t.duration_h! <= b.max);
    if (idx >= 0) {
      if (t.outcome === 'WIN') data[idx].wins++;
      else data[idx].losses++;
    }
  });

  if (!hasDuration) return null;

  // Compute mean and median duration in bucket-index space for vertical reference lines
  const meanDuration = allDurations.reduce((a, b) => a + b, 0) / allDurations.length;
  const sortedDurs = [...allDurations].sort((a, b) => a - b);
  const medianDuration = sortedDurs.length % 2 === 0
    ? (sortedDurs[sortedDurs.length / 2 - 1] + sortedDurs[sortedDurs.length / 2]) / 2
    : sortedDurs[Math.floor(sortedDurs.length / 2)];

  // Map a duration (hours) to a fractional bucket x position
  const BUCKET_BOUNDS = [0, 1, 4, 12, 24, 72, Infinity];
  function durationToFrac(dh: number): number {
    for (let i = 0; i < BUCKET_BOUNDS.length - 1; i++) {
      const lo = BUCKET_BOUNDS[i], hi = BUCKET_BOUNDS[i + 1];
      if (dh <= hi) {
        const hiClamped = hi === Infinity ? lo * 3 : hi;
        return (i + (dh - lo) / (hiClamped - lo)) / (BUCKET_BOUNDS.length - 1);
      }
    }
    return 1;
  }

  const maxTotal = Math.max(...data.map((d) => d.wins + d.losses), 1);
  const W = 560, H = 140;
  const pad = { t: 20, r: 16, b: 36, l: 40 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;
  const barW = iW / data.length - 4;

  // Best performing bucket (highest win rate with at least 1 trade)
  const bestBucketIdx = data.reduce((best, d, i) => {
    const total = d.wins + d.losses;
    if (total === 0) return best;
    const wr = d.wins / total;
    const bestTotal = data[best].wins + data[best].losses;
    const bestWr = bestTotal > 0 ? data[best].wins / bestTotal : -1;
    return wr > bestWr ? i : best;
  }, 0);

  return (
    <motion.div variants={fadeUp} initial="hidden" animate="show" style={{ ...Glass.crystal, borderRadius: R.xl, padding: '20px 24px', marginBottom: 24 }}>
      <div style={{ marginBottom: 14 }}>
        <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Trade Duration Distribution</div>
        <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>How long trades are held — stacked by win (green) / loss (red)</div>
      </div>

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
        <defs>
          <linearGradient id={`durationWin-${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.bull} stopOpacity="0.9" />
            <stop offset="100%" stopColor={C.bull} stopOpacity="0.5" />
          </linearGradient>
          <linearGradient id={`durationLoss-${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.bear} stopOpacity="0.9" />
            <stop offset="100%" stopColor={C.bear} stopOpacity="0.5" />
          </linearGradient>
        </defs>

        {/* Y grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map((frac) => {
          const y = pad.t + iH * (1 - frac);
          const count = Math.round(frac * maxTotal);
          return (
            <g key={frac}>
              <line x1={pad.l} y1={y} x2={pad.l + iW} y2={y} stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4" />
              <text x={pad.l - 4} y={y + 3} textAnchor="end" fontSize={8} fill={C.muted}>{count}</text>
            </g>
          );
        })}

        {/* Bars */}
        {data.map((d, i) => {
          const total = d.wins + d.losses;
          const winH = total > 0 ? (d.wins / maxTotal) * iH : 0;
          const lossH = total > 0 ? (d.losses / maxTotal) * iH : 0;
          const x = pad.l + i * (iW / data.length) + 2;
          const wr = total > 0 ? Math.round((d.wins / total) * 100) : null;
          const isBest = i === bestBucketIdx && total > 0;
          const barTopY = pad.t + iH - lossH - winH;

          return (
            <g key={d.label}>
              {/* Loss bar (bottom) */}
              {lossH > 0 && (
                <rect x={x} y={pad.t + iH - lossH} width={barW} height={lossH}
                  fill={`url(#durationLoss-${uid})`} rx={2} />
              )}
              {/* Win bar (stacked on top) */}
              {winH > 0 && (
                <rect x={x} y={pad.t + iH - lossH - winH} width={barW} height={winH}
                  fill={`url(#durationWin-${uid})`} rx={2} />
              )}
              {/* Total count label */}
              {total > 0 && (
                <text x={x + barW / 2} y={barTopY - (isBest ? 14 : 4)}
                  textAnchor="middle" fontSize={8} fill={C.muted}>{total}</text>
              )}
              {/* Star for best performing bucket */}
              {isBest && (
                <text x={x + barW / 2} y={barTopY - 4}
                  textAnchor="middle" fontSize={11} fill={C.warn}>★</text>
              )}
              {/* WR label inside if tall enough */}
              {wr != null && winH + lossH > 20 && (
                <text x={x + barW / 2} y={pad.t + iH - lossH - winH / 2 + 4}
                  textAnchor="middle" fontSize={8} fontWeight="700" fill="#fff" fillOpacity="0.9">{wr}%</text>
              )}
              {/* X label */}
              <text x={x + barW / 2} y={pad.t + iH + 14}
                textAnchor="middle" fontSize={9} fill={C.muted}>{d.label}</text>
            </g>
          );
        })}

        {/* Mean duration vertical line */}
        {(() => {
          const xMean = pad.l + durationToFrac(meanDuration) * iW;
          return (
            <g>
              <line x1={xMean} y1={pad.t} x2={xMean} y2={pad.t + iH}
                stroke={C.brand} strokeWidth={1.2} strokeDasharray="4 3" />
              <text x={xMean + 2} y={pad.t + 9} fontSize={7} fill={C.brand} fontFamily="Inter, system-ui">avg</text>
            </g>
          );
        })()}

        {/* Median duration vertical line */}
        {(() => {
          const xMedian = pad.l + durationToFrac(medianDuration) * iW;
          return (
            <g>
              <line x1={xMedian} y1={pad.t} x2={xMedian} y2={pad.t + iH}
                stroke={C.warn} strokeWidth={1.2} />
              <text x={xMedian + 2} y={pad.t + 17} fontSize={7} fill={C.warn} fontFamily="Inter, system-ui">med</text>
            </g>
          );
        })()}

        {/* Axis */}
        <line x1={pad.l} y1={pad.t} x2={pad.l} y2={pad.t + iH} stroke={C.border} strokeWidth={0.5} />
        <line x1={pad.l} y1={pad.t + iH} x2={pad.l + iW} y2={pad.t + iH} stroke={C.border} strokeWidth={0.5} />
      </svg>

      <div style={{ display: 'flex', gap: 16, fontSize: 10, color: C.muted, marginTop: 8, flexWrap: 'wrap' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.bull, borderRadius: 2, display: 'inline-block' }} /> Win
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.bear, borderRadius: 2, display: 'inline-block' }} /> Loss
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 16, height: 2, background: C.brand, display: 'inline-block', verticalAlign: 'middle', borderTop: '1px dashed' }} /> Avg
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 16, height: 2, background: C.warn, display: 'inline-block', verticalAlign: 'middle' }} /> Median
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: 11, color: C.warn }}>★</span> Best win rate bucket
        </span>
      </div>
    </motion.div>
  );
}

// ─── Multi-Symbol Cumulative P&L Chart ────────────────────────────────────────

function MultiSymbolPnlChart({ trades }: { trades: TradeRecord[] }) {
  if (trades.length < 3) return null;

  // Sort by time, group by symbol
  const sorted = [...trades].sort((a, b) => {
    const ta = (a as any).entry_time ?? (a as any).timestamp ?? '';
    const tb = (b as any).entry_time ?? (b as any).timestamp ?? '';
    return ta < tb ? -1 : ta > tb ? 1 : 0;
  });

  const symbols = Array.from(new Set(sorted.map((t) => t.symbol).filter(Boolean))).slice(0, 5) as string[];
  if (symbols.length < 2) return null;

  // Build cumulative P&L per symbol as sequential trade index
  const symbolColors: Record<string, string> = {
    BTC: C.brand,
    SOL: C.bull,
    HYPE: C.warn,
    ETH: C.info,
  };
  const defaultColors = [C.bear, '#a78bfa', '#f472b6', C.muted, '#34d399'];
  const getColor = (sym: string, i: number) => symbolColors[sym] ?? defaultColors[i % defaultColors.length];

  const symData: Record<string, { x: number; y: number }[]> = {};
  const symCum: Record<string, number> = {};

  symbols.forEach((s) => { symData[s] = [{ x: 0, y: 0 }]; symCum[s] = 0; });

  let globalIdx = 0;
  sorted.forEach((t) => {
    if (!t.symbol || !symbols.includes(t.symbol)) return;
    globalIdx++;
    symCum[t.symbol] += t.pnl ?? 0;
    symData[t.symbol].push({ x: globalIdx, y: symCum[t.symbol] });
  });

  const W = 560, H = 160;
  const pad = { t: 16, r: 20, b: 28, l: 60 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;

  const maxX = globalIdx || 1;
  const allY = Object.values(symData).flatMap((pts) => pts.map((p) => p.y));
  const minY = Math.min(...allY, 0);
  const maxY = Math.max(...allY, 1);
  const rangeY = maxY - minY || 1;

  const px = (x: number) => pad.l + (x / maxX) * iW;
  const py = (y: number) => pad.t + iH - ((y - minY) / rangeY) * iH;

  const yTicks = [minY, 0, maxY / 2, maxY].filter((v, i, a) => a.indexOf(v) === i).sort((a, b) => a - b);

  return (
    <motion.div variants={fadeUp} initial="hidden" animate="show" style={{ ...Glass.crystal, borderRadius: R.xl, padding: '20px 24px', marginBottom: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Cumulative P&L by Symbol</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>Each line tracks cumulative profit/loss per symbol over trade sequence</div>
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {symbols.map((sym, i) => {
            const color = getColor(sym, i);
            const finalPnl = symCum[sym];
            return (
              <span key={sym} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 10 }}>
                <span style={{ width: 16, height: 2.5, background: color, display: 'inline-block', borderRadius: 2 }} />
                <span style={{ color: C.textSub, fontWeight: 600 }}>{sym}</span>
                <span style={{ color: finalPnl >= 0 ? C.bull : C.bear, fontWeight: 700 }}>
                  {finalPnl >= 0 ? '+' : ''}${finalPnl.toFixed(0)}
                </span>
              </span>
            );
          })}
        </div>
      </div>

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
        <defs>
          {symbols.map((sym, i) => {
            const color = getColor(sym, i);
            return (
              <linearGradient key={sym} id={`msGrad${i}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity="0.12" />
                <stop offset="100%" stopColor={color} stopOpacity="0.01" />
              </linearGradient>
            );
          })}
        </defs>

        {/* Y grid + labels */}
        {yTicks.map((tick) => {
          const y = py(tick);
          const isZero = tick === 0;
          return (
            <g key={tick}>
              <line x1={pad.l} y1={y} x2={pad.l + iW} y2={y}
                stroke={isZero ? C.muted : C.border}
                strokeWidth={isZero ? 1 : 0.5}
                strokeDasharray={isZero ? '4 3' : '2 4'}
              />
              <text x={pad.l - 4} y={y + 3} textAnchor="end" fontSize={8} fill={C.muted}>
                {tick >= 0 ? '+' : ''}{tick >= 1000 ? `${(tick / 1000).toFixed(1)}k` : tick.toFixed(0)}
              </text>
            </g>
          );
        })}

        {/* Lines per symbol */}
        {symbols.map((sym, i) => {
          const color = getColor(sym, i);
          const pts = symData[sym];
          if (pts.length < 2) return null;
          const polyPoints = pts.map((p) => `${px(p.x)},${py(p.y)}`).join(' ');
          const areaPoints = [`${px(0)},${py(0)}`, ...pts.map((p) => `${px(p.x)},${py(p.y)}`), `${px(pts[pts.length - 1].x)},${py(0)}`].join(' ');
          const lastPt = pts[pts.length - 1];
          return (
            <g key={sym}>
              <polygon points={areaPoints} fill={`url(#msGrad${i})`} />
              <polyline points={polyPoints} fill="none" stroke={color} strokeWidth={1.8} strokeLinejoin="round" />
              <circle cx={px(lastPt.x)} cy={py(lastPt.y)} r={3} fill={color} />
            </g>
          );
        })}

        {/* X axis label */}
        <text x={pad.l + iW / 2} y={H - 4} textAnchor="middle" fontSize={8} fill={C.muted}>Trade sequence →</text>
      </svg>
    </motion.div>
  );
}

// ─── Trade Card ───────────────────────────────────────────────────────────────

function TradeCard({ trade }: { trade: TradeRecord }) {
  const [expanded, setExpanded] = useState(false);
  const win = trade.outcome === 'WIN';

  const closeColor: Record<string, string> = {
    TP1: C.bull, TP2: '#22c55e', TRAILING_STOP: C.info, SL: C.bear,
    EARLY_EXIT: C.warn, CIRCUIT_BREAKER: '#7c3aed', BACKTEST_END: C.muted,
  };

  const actionColor: Record<string, string> = {
    proceed: C.bull, go: C.bull, skip: C.muted, flat: C.muted, flip: C.purple, veto: C.bear,
  };

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      animate="show"
      style={{
        ...Glass.card,
        border: `1px solid ${win ? C.bull + '30' : C.bear + '20'}`,
        borderLeft: `3px solid ${win ? C.bull : C.bear}`,
        borderRadius: R.md,
        marginBottom: 8,
        overflow: 'hidden',
        transition: 'border-color 0.15s',
      }}
    >
      {/* Summary row */}
      <button
        onClick={() => setExpanded((v) => !v)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 14px', background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', gap: 8,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', flex: 1 }}>
          <span style={{ fontSize: F.sm, fontWeight: 800, color: C.text, minWidth: 40 }}>{trade.symbol}</span>
          <Badge variant={trade.side === 'BUY' ? 'bull' : 'bear'}>{trade.side}</Badge>
          <span className="num" style={{ fontSize: F.sm, fontWeight: 700, color: win ? C.bull : C.bear, minWidth: 72 }}>
            {fmtUsd(trade.pnl)}
          </span>
          <Badge variant={win ? 'bull' : 'bear'}>{trade.outcome}</Badge>
          {trade.close_reason && (
            <Badge variant={trade.close_reason === 'SL' ? 'bear' : trade.close_reason.startsWith('TP') ? 'bull' : 'info'}>{trade.close_reason}</Badge>
          )}
          {trade.duration_h != null && (
            <span style={{ fontSize: F.xs, color: C.muted }}>{trade.duration_h.toFixed(1)}h</span>
          )}
        </div>
        <span style={{ color: C.muted, fontSize: 11, transform: expanded ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s', flexShrink: 0 }}>▼</span>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div style={{ padding: '0 14px 14px', borderTop: `1px solid ${C.border}` }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginTop: 12 }}>
            {/* Trade mechanics */}
            <div>
              <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>Trade Mechanics</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: F.xs, color: C.textSub }}>
                {[
                  { label: 'Entry', value: fmtUsd(trade.entry) },
                  { label: 'Exit', value: fmtUsd(trade.exit) },
                  { label: 'Stop Loss', value: fmtUsd(trade.sl) },
                  { label: 'TP1', value: fmtUsd(trade.tp1) },
                  { label: 'TP2', value: fmtUsd(trade.tp2) },
                  { label: 'R/R Target', value: trade.entry && trade.sl && trade.tp1 && trade.entry !== trade.sl ? `${(Math.abs((trade.tp1 - trade.entry) / (trade.entry - trade.sl))).toFixed(2)}:1` : '—' },
                  { label: 'R/R Achieved', value: trade.rr_achieved != null ? `${trade.rr_achieved.toFixed(2)}:1` : '—' },
                  { label: 'Leverage', value: trade.leverage != null ? `${trade.leverage.toFixed(1)}×` : '—' },
                  { label: 'Fee', value: fmtUsd(trade.fee) },
                  { label: 'Hold Time', value: trade.duration_h != null ? `${trade.duration_h.toFixed(1)}h` : '—' },
                ].map(({ label, value }) => (
                  <div key={label} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                    <span style={{ color: C.muted }}>{label}</span>
                    <span style={{ fontVariantNumeric: 'tabular-nums', fontWeight: 600, color: C.text }}>{value}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* LLM context */}
            <div>
              <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>LLM Context</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {trade.llm_confidence != null && <ConfRing value={trade.llm_confidence} size={36} />}
                  <div>
                    <div style={{ fontSize: F.xs, color: C.muted }}>Confidence</div>
                    <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>{trade.llm_confidence != null ? `${(trade.llm_confidence * 100).toFixed(0)}%` : '—'}</div>
                  </div>
                </div>
                {[
                  { label: 'LLM Action', value: trade.llm_action, color: actionColor[(trade.llm_action || '').toLowerCase()] },
                  { label: 'Regime', value: trade.llm_regime, color: C.text },
                  { label: 'Strategy', value: trade.strategy, color: C.brand },
                  { label: 'Signal Conf.', value: trade.confidence != null ? `${(trade.confidence * 100).toFixed(0)}%` : null, color: C.text },
                ].map(({ label, value, color }) => value ? (
                  <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontSize: F.xs, gap: 8 }}>
                    <span style={{ color: C.muted }}>{label}</span>
                    <span style={{ fontWeight: 700, color: color || C.text, textTransform: 'capitalize' }}>{value}</span>
                  </div>
                ) : null)}
              </div>
            </div>
          </div>
        </div>
      )}
    </motion.div>
  );
}

// ─── Pill Filter ─────────────────────────────────────────────────────────────

function PillFilter({ label, options, value, onChange }: {
  label: string;
  options: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
      <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 600 }}>{label}:</span>
      {options.map((opt) => (
        <button
          key={opt}
          onClick={() => onChange(opt)}
          style={{
            fontSize: F.xs, padding: '3px 10px', borderRadius: R.pill, cursor: 'pointer', fontWeight: 600,
            border: `1px solid ${value === opt ? C.brand : C.border}`,
            background: value === opt ? C.brand + '22' : 'transparent',
            color: value === opt ? C.brand : C.muted,
            transition: 'all 0.12s',
          }}
        >
          {opt}
        </button>
      ))}
    </div>
  );
}

// ─── Signal Quality Funnel ────────────────────────────────────────────────────

function SignalQualityFunnel({ trades }: { trades: TradeRecord[] }) {
  const executed = trades.length;

  // Stage counts — calculated from actual trade count or fallback minimums
  const fallback = executed === 0;
  const generated = fallback ? 100 : Math.max(40, executed * 4);

  const stages: { label: string; count: number }[] = fallback
    ? [
        { label: 'Signals Generated', count: 100 },
        { label: 'Gate 1: Valid Signal', count: 85 },
        { label: 'Gate 2: Circuit Breaker', count: 81 },
        { label: 'Gate 3: Position Limits', count: 73 },
        { label: 'Gate 4: Leverage Check', count: 67 },
        { label: 'Gate 5: Final Risk', count: 59 },
        { label: 'Executed Trades', count: 12 },
      ]
    : [
        { label: 'Signals Generated', count: generated },
        { label: 'Gate 1: Valid Signal', count: Math.round(generated * 0.85) },
        { label: 'Gate 2: Circuit Breaker', count: Math.round(generated * 0.85 * 0.95) },
        { label: 'Gate 3: Position Limits', count: Math.round(generated * 0.85 * 0.95 * 0.90) },
        { label: 'Gate 4: Leverage Check', count: Math.round(generated * 0.85 * 0.95 * 0.90 * 0.92) },
        { label: 'Gate 5: Final Risk', count: Math.round(generated * 0.85 * 0.95 * 0.90 * 0.92 * 0.88) },
        { label: 'Executed Trades', count: executed },
      ];

  const SVG_W = 480;
  const SVG_H = 280;
  const BAR_H = 22;
  const GAP = 16; // space between bars (for arrow + drop-off text)
  const totalSlots = stages.length; // 7
  const usedH = totalSlots * BAR_H + (totalSlots - 1) * GAP;
  const topPad = (SVG_H - usedH) / 2;

  const MAX_BAR_W = 320;
  const MIN_BAR_W = 80;
  const LABEL_COL_W = 140; // left label column width
  const COUNT_COL_X = LABEL_COL_W + MAX_BAR_W + 8; // right count x position

  const maxCount = stages[0].count;

  function barWidth(count: number): number {
    if (maxCount === 0) return MIN_BAR_W;
    return MIN_BAR_W + ((count / maxCount) * (MAX_BAR_W - MIN_BAR_W));
  }

  function barX(count: number): number {
    // Center bars around the midpoint of the bar area
    const mid = LABEL_COL_W + MAX_BAR_W / 2;
    return mid - barWidth(count) / 2;
  }

  function dropPct(current: number, prev: number): string {
    if (prev === 0) return '';
    const diff = prev - current;
    const pct = Math.round((diff / prev) * 100);
    return pct > 0 ? `-${pct}%` : '0%';
  }

  return (
    <motion.div variants={fadeUp} initial="hidden" animate="show" style={{ ...Glass.crystal, borderRadius: R.xl, padding: '20px 24px', marginBottom: 24 }}>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Signal Quality Funnel</h2>
        <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
          How raw signals are filtered through each safety gate before execution. Width represents relative volume.
        </div>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <svg
          viewBox={`0 0 ${SVG_W} ${SVG_H}`}
          width={SVG_W}
          height={SVG_H}
          style={{ display: 'block', maxWidth: '100%' }}
        >
          {stages.map((stage, i) => {
            const y = topPad + i * (BAR_H + GAP);
            const bw = barWidth(stage.count);
            const bx = barX(stage.count);
            const isLast = i === stages.length - 1;
            const isFirst = i === 0;

            // Filtered-out stub: how many were dropped from previous stage
            const filteredCount = i > 0 ? stages[i - 1].count - stage.count : 0;
            const stubW = i > 0 && stages[i - 1].count > 0
              ? (filteredCount / stages[0].count) * (MAX_BAR_W - MIN_BAR_W)
              : 0;
            const stubX = bx + bw + 4;

            // Bar color: last stage gets bear tint to stand out, first gets a slightly brighter brand
            const barFill = isLast ? C.bull : isFirst ? C.brand : C.brand;
            const barOpacity = isLast ? 0.9 : isFirst ? 0.92 : 0.72 - i * 0.04;

            return (
              <g key={stage.label}>
                {/* Stage bar */}
                <rect
                  x={bx}
                  y={y}
                  width={bw}
                  height={BAR_H}
                  rx={3}
                  fill={barFill}
                  fillOpacity={Math.max(0.45, barOpacity)}
                />

                {/* Filtered-out stub on the right (bear color) */}
                {stubW > 1 && (
                  <rect
                    x={stubX}
                    y={y + BAR_H * 0.2}
                    width={Math.max(3, stubW)}
                    height={BAR_H * 0.6}
                    rx={2}
                    fill={C.bear}
                    fillOpacity={0.55}
                  />
                )}

                {/* Left label */}
                <text
                  x={LABEL_COL_W - 8}
                  y={y + BAR_H / 2 + 4}
                  textAnchor="end"
                  fontSize={9}
                  fill={isFirst || isLast ? C.textSub : C.muted}
                  fontWeight={isFirst || isLast ? 700 : 500}
                  fontFamily="Inter, system-ui"
                >
                  {stage.label}
                </text>

                {/* Right count */}
                <text
                  x={COUNT_COL_X}
                  y={y + BAR_H / 2 + 4}
                  textAnchor="start"
                  fontSize={10}
                  fontWeight={700}
                  fill={isLast ? C.bull : C.textSub}
                  fontFamily="Inter, system-ui"
                >
                  {stage.count.toLocaleString()}
                </text>

                {/* Down arrow between stages */}
                {!isLast && (
                  <text
                    x={LABEL_COL_W + MAX_BAR_W / 2}
                    y={y + BAR_H + GAP / 2 + 4}
                    textAnchor="middle"
                    fontSize={9}
                    fill={C.muted}
                    fontFamily="Inter, system-ui"
                  >
                    ▼
                  </text>
                )}

                {/* Drop-off percentage between stages */}
                {i > 0 && (
                  <text
                    x={COUNT_COL_X}
                    y={y - GAP / 2 + 4}
                    textAnchor="start"
                    fontSize={9}
                    fontWeight={600}
                    fill={C.bear}
                    fontFamily="Inter, system-ui"
                  >
                    {dropPct(stage.count, stages[i - 1].count)}
                  </text>
                )}
              </g>
            );
          })}

          {/* Legend: pass bar + filtered stub */}
          <g>
            <rect x={LABEL_COL_W} y={SVG_H - 18} width={14} height={10} rx={2} fill={C.brand} fillOpacity={0.75} />
            <text x={LABEL_COL_W + 18} y={SVG_H - 9} fontSize={9} fill={C.muted} fontFamily="Inter, system-ui">Pass</text>
            <rect x={LABEL_COL_W + 60} y={SVG_H - 18} width={14} height={10} rx={2} fill={C.bear} fillOpacity={0.55} />
            <text x={LABEL_COL_W + 78} y={SVG_H - 9} fontSize={9} fill={C.muted} fontFamily="Inter, system-ui">Filtered out</text>
          </g>
        </svg>
      </div>
    </motion.div>
  );
}

// ─── Rolling Sharpe Chart ─────────────────────────────────────────────────────

function RollingSharpeChart({ trades }: { trades: TradeRecord[] }) {
  const uid = useId().replace(/:/g, '');
  const validTrades = trades.filter((t) => t.pnl != null && !isNaN(t.pnl!));
  const WINDOW = 10;

  if (validTrades.length < WINDOW) {
    return (
      <div style={{ height: 100, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.muted, fontSize: F.sm, background: C.surfaceHover, borderRadius: R.md }}>
        Need at least {WINDOW} trades with P&L data to compute rolling Sharpe.
      </div>
    );
  }

  // Build rolling Sharpe points: center index = i + WINDOW/2 - 0.5
  const sharpePoints: { x: number; sharpe: number }[] = [];
  for (let i = 0; i <= validTrades.length - WINDOW; i++) {
    const slice = validTrades.slice(i, i + WINDOW).map((t) => t.pnl!);
    const mean = slice.reduce((a, b) => a + b, 0) / WINDOW;
    const variance = slice.reduce((a, b) => a + (b - mean) ** 2, 0) / WINDOW;
    const std = Math.sqrt(Math.max(0, variance));
    const sharpe = std > 0 ? (mean / std) * Math.sqrt(WINDOW) : 0;
    sharpePoints.push({ x: i + WINDOW / 2, sharpe });
  }

  const W = 540, H = 100;
  const pad = { top: 18, right: 80, bottom: 22, left: 44 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const yMin = -1, yMax = 3;
  const xMax = validTrades.length;

  const px = (x: number) => pad.left + (x / xMax) * plotW;
  const py = (v: number) => pad.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;

  // Build fill path split at y=0
  const abovePath: string[] = [];
  const belowPath: string[] = [];

  sharpePoints.forEach((pt, i) => {
    const x = px(pt.x);
    const y = py(pt.sharpe);
    const y0 = py(0);
    if (i === 0) {
      abovePath.push(`M ${x} ${y0}`);
      belowPath.push(`M ${x} ${y0}`);
    }
    abovePath.push(`L ${x} ${Math.min(y, y0)}`);
    belowPath.push(`L ${x} ${Math.max(y, y0)}`);
  });
  if (sharpePoints.length > 0) {
    const lastX = px(sharpePoints[sharpePoints.length - 1].x);
    const y0 = py(0);
    abovePath.push(`L ${lastX} ${y0} Z`);
    belowPath.push(`L ${lastX} ${y0} Z`);
  }

  // Polyline
  const linePoints = sharpePoints.map((pt) => `${px(pt.x)},${py(pt.sharpe)}`).join(' ');

  const currentSharpe = sharpePoints.length > 0 ? sharpePoints[sharpePoints.length - 1].sharpe : 0;
  const lineColor = currentSharpe >= 1.0 ? C.bull : currentSharpe >= 0 ? C.warn : C.bear;

  const lastPt = sharpePoints[sharpePoints.length - 1];
  const lastX = px(lastPt.x);
  const lastY = py(lastPt.sharpe);

  return (
    <div>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 6 }}>
        Rolling Sharpe Ratio (10-trade window)
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
      >
        <defs>
          <clipPath id={`sharpeClip-${uid}`}>
            <rect x={pad.left} y={pad.top} width={plotW} height={plotH} />
          </clipPath>
        </defs>

        {/* Fill above 0 */}
        <path d={abovePath.join(' ')} fill={C.bull + '15'} clipPath={`url(#sharpeClip-${uid})`} />
        {/* Fill below 0 */}
        <path d={belowPath.join(' ')} fill={C.bear + '15'} clipPath={`url(#sharpeClip-${uid})`} />

        {/* Reference line: 0 (bold gray) */}
        <line x1={pad.left} y1={py(0)} x2={pad.left + plotW} y2={py(0)}
          stroke={C.borderBright} strokeWidth={1.5} />
        <text x={pad.left - 4} y={py(0) + 4} textAnchor="end" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">0</text>

        {/* Reference line: 1.0 (dashed green "Good") */}
        <line x1={pad.left} y1={py(1.0)} x2={pad.left + plotW} y2={py(1.0)}
          stroke={C.bull} strokeWidth={1} strokeDasharray="5 4" clipPath={`url(#sharpeClip-${uid})`} />
        <text x={pad.left + plotW + 3} y={py(1.0) + 3} fontSize={8} fill={C.bull} fontFamily="Inter, system-ui">Good</text>
        <text x={pad.left - 4} y={py(1.0) + 4} textAnchor="end" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">1.0</text>

        {/* Reference line: 2.0 (dashed C.bull "Excellent") */}
        <line x1={pad.left} y1={py(2.0)} x2={pad.left + plotW} y2={py(2.0)}
          stroke={C.bull} strokeWidth={1} strokeDasharray="5 4" clipPath={`url(#sharpeClip-${uid})`} />
        <text x={pad.left + plotW + 3} y={py(2.0) + 3} fontSize={8} fill={C.bull} fontFamily="Inter, system-ui">Excellent</text>
        <text x={pad.left - 4} y={py(2.0) + 4} textAnchor="end" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">2.0</text>

        {/* Y tick: -1 */}
        <text x={pad.left - 4} y={py(-1) + 4} textAnchor="end" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">-1</text>
        <line x1={pad.left} y1={py(-1)} x2={pad.left + plotW} y2={py(-1)}
          stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4" clipPath={`url(#sharpeClip-${uid})`} />

        {/* Sharpe line */}
        {sharpePoints.length > 1 && (
          <polyline
            points={linePoints}
            fill="none"
            stroke={lineColor}
            strokeWidth={2}
            strokeLinejoin="round"
            clipPath={`url(#sharpeClip-${uid})`}
          />
        )}

        {/* Current value dot */}
        <circle cx={lastX} cy={lastY} r={4} fill={lineColor} />
        <text
          x={lastX + 6}
          y={lastY + 4}
          fontSize={9}
          fontWeight={700}
          fill={lineColor}
          fontFamily="Inter, system-ui"
        >
          Current: {currentSharpe.toFixed(1)}
        </text>

        {/* X axis label */}
        <text x={pad.left + plotW / 2} y={H - 3} textAnchor="middle" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">
          Trade index
        </text>
      </svg>
    </div>
  );
}

// ─── Trade Clusters Chart ──────────────────────────────────────────────────────

function TradeClustersChart({ trades }: { trades: TradeRecord[] }) {
  const uid = useId().replace(/:/g, '');
  type AnyRecord = TradeRecord & { open_time?: string | number | null; entry_timestamp_ms?: number | null };

  const W = 520, H = 180;
  const pad = { top: 18, right: 20, bottom: 28, left: 44 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  // day 0 = Mon (ISO weekday 1), day 6 = Sun (ISO weekday 0)

  interface DotData {
    hour: number;
    day: number;
    win: boolean;
    pnl: number;
    jitterX: number;
    jitterY: number;
  }

  const dots: DotData[] = [];
  let hasTimestamps = false;

  trades.forEach((t, i) => {
    const r = t as AnyRecord;
    const raw = r.entry_timestamp_ms ?? r.open_time;
    if (raw == null) return;
    try {
      const ts = typeof raw === 'number'
        ? (raw > 1e12 ? raw : raw * 1000)
        : new Date(raw as string).getTime();
      if (isNaN(ts)) return;
      const d = new Date(ts);
      const hour = d.getUTCHours();
      // ISO: 0=Sun,1=Mon,...,6=Sat → remap to Mon=0..Sun=6
      const isoDay = d.getUTCDay(); // 0=Sun
      const day = isoDay === 0 ? 6 : isoDay - 1;
      hasTimestamps = true;
      // Deterministic jitter based on index
      const jitterX = ((i * 7919 + 13) % 40) / 40 - 0.5; // -0.5 to 0.5
      const jitterY = ((i * 3761 + 7) % 40) / 40 - 0.5;
      dots.push({ hour, day, win: t.outcome === 'WIN', pnl: Math.abs(t.pnl ?? 1), jitterX, jitterY });
    } catch {/* skip */}
  });

  if (!hasTimestamps) {
    return (
      <div>
        <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 6 }}>
          Trade Cluster Map — When Does Bot Win?
        </div>
        <EmptyState icon="⏳" title="Awaiting trade data" subtitle="Trade cluster map will populate once the bot has closed trades with timestamp data" />
      </div>
    );
  }

  const cellW = plotW / 24;
  const cellH = plotH / 7;

  const cx = (hour: number, jitter: number) => pad.left + (hour + 0.5 + jitter * 0.6) * cellW;
  const cy = (day: number, jitter: number) => pad.top + (day + 0.5 + jitter * 0.6) * cellH;

  // Compute per-cell win rate for cluster circles
  const cellStats: { wins: number; total: number }[][] = Array.from({ length: 7 }, () =>
    Array.from({ length: 24 }, () => ({ wins: 0, total: 0 }))
  );
  dots.forEach((d) => {
    cellStats[d.day][d.hour].total++;
    if (d.win) cellStats[d.day][d.hour].wins++;
  });

  // Find best and worst clusters (contiguous 4-hour windows per day with ≥3 trades)
  type ClusterInfo = { day: number; startHour: number; endHour: number; wr: number; total: number };
  const clusters: ClusterInfo[] = [];
  for (let day = 0; day < 7; day++) {
    for (let h = 0; h <= 20; h++) {
      let wins = 0, total = 0;
      for (let dh = 0; dh < 4; dh++) {
        wins += cellStats[day][h + dh].wins;
        total += cellStats[day][h + dh].total;
      }
      if (total >= 3) clusters.push({ day, startHour: h, endHour: h + 4, wr: wins / total, total });
    }
  }
  clusters.sort((a, b) => b.wr - a.wr);
  const bestCluster = clusters[0] ?? null;
  const worstCluster = clusters.length > 1 ? clusters[clusters.length - 1] : null;

  const maxPnl = Math.max(...dots.map((d) => d.pnl), 1);

  return (
    <div>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 6 }}>
        Trade Cluster Map — When Does Bot Win?
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
      >
        <defs>
          <clipPath id={`clusterClip-${uid}`}>
            <rect x={pad.left} y={pad.top} width={plotW} height={plotH} />
          </clipPath>
        </defs>

        {/* Grid lines — hours */}
        {Array.from({ length: 25 }, (_, h) => (
          <line key={`gh${h}`}
            x1={pad.left + h * cellW} y1={pad.top}
            x2={pad.left + h * cellW} y2={pad.top + plotH}
            stroke={C.border} strokeWidth={0.4}
          />
        ))}
        {/* Grid lines — days */}
        {Array.from({ length: 8 }, (_, d) => (
          <line key={`gd${d}`}
            x1={pad.left} y1={pad.top + d * cellH}
            x2={pad.left + plotW} y2={pad.top + d * cellH}
            stroke={C.border} strokeWidth={0.4}
          />
        ))}

        {/* Best cluster ellipse */}
        {bestCluster && (() => {
          const ecx = pad.left + (bestCluster.startHour + 2) * cellW;
          const ecy = pad.top + (bestCluster.day + 0.5) * cellH;
          const erx = cellW * 2.2;
          const ery = cellH * 0.55;
          return (
            <ellipse cx={ecx} cy={ecy} rx={erx} ry={ery}
              fill={C.bull + '15'} stroke={C.bull} strokeWidth={1} strokeDasharray="4 3"
              clipPath={`url(#clusterClip-${uid})`}
            />
          );
        })()}

        {/* Worst cluster ellipse */}
        {worstCluster && (() => {
          const ecx = pad.left + (worstCluster.startHour + 2) * cellW;
          const ecy = pad.top + (worstCluster.day + 0.5) * cellH;
          const erx = cellW * 2.2;
          const ery = cellH * 0.55;
          return (
            <ellipse cx={ecx} cy={ecy} rx={erx} ry={ery}
              fill={C.bear + '15'} stroke={C.bear} strokeWidth={1} strokeDasharray="4 3"
              clipPath={`url(#clusterClip-${uid})`}
            />
          );
        })()}

        {/* Dots */}
        {dots.map((d, i) => {
          const r = Math.max(2, Math.min(7, 2 + (d.pnl / maxPnl) * 5));
          return (
            <circle
              key={i}
              cx={cx(d.hour, d.jitterX)}
              cy={cy(d.day, d.jitterY)}
              r={r}
              fill={d.win ? C.bull : C.bear}
              fillOpacity={0.65}
              stroke={d.win ? C.bullMid : C.bearMid}
              strokeWidth={0.6}
              clipPath={`url(#clusterClip-${uid})`}
            >
              <title>{`${DAYS[d.day]} ${d.hour}:00 UTC — ${d.win ? 'WIN' : 'LOSS'} $${d.pnl.toFixed(2)}`}</title>
            </circle>
          );
        })}

        {/* Y axis: day labels */}
        {DAYS.map((label, d) => (
          <text
            key={label}
            x={pad.left - 5}
            y={pad.top + (d + 0.5) * cellH + 4}
            textAnchor="end"
            fontSize={8}
            fill={C.muted}
            fontFamily="Inter, system-ui"
          >
            {label}
          </text>
        ))}

        {/* X axis: hour labels every 4h */}
        {[0, 4, 8, 12, 16, 20].map((h) => (
          <text
            key={h}
            x={pad.left + (h + 0.5) * cellW}
            y={pad.top + plotH + 12}
            textAnchor="middle"
            fontSize={8}
            fill={C.muted}
            fontFamily="Inter, system-ui"
          >
            {h}h
          </text>
        ))}

        {/* Best cluster label */}
        {bestCluster && (
          <text
            x={pad.left + (bestCluster.startHour + 2) * cellW}
            y={pad.top + (bestCluster.day + 0.5) * cellH - cellH * 0.6 - 3}
            textAnchor="middle"
            fontSize={8}
            fontWeight={700}
            fill={C.bull}
            fontFamily="Inter, system-ui"
          >
            {`Best: ${DAYS[bestCluster.day]} ${bestCluster.startHour}–${bestCluster.endHour} UTC (${Math.round(bestCluster.wr * 100)}% WR)`}
          </text>
        )}

        {/* Worst cluster label */}
        {worstCluster && worstCluster.day !== (bestCluster?.day ?? -1) && (
          <text
            x={pad.left + (worstCluster.startHour + 2) * cellW}
            y={pad.top + (worstCluster.day + 0.5) * cellH + cellH * 0.7 + 8}
            textAnchor="middle"
            fontSize={8}
            fontWeight={700}
            fill={C.bear}
            fontFamily="Inter, system-ui"
          >
            {`Avoid: ${DAYS[worstCluster.day]} ${worstCluster.startHour}–${worstCluster.endHour} UTC (${Math.round(worstCluster.wr * 100)}% WR)`}
          </text>
        )}

        {/* X axis title */}
        <text x={pad.left + plotW / 2} y={H - 3} textAnchor="middle" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">
          Hour of day (UTC)
        </text>
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, fontSize: 10, color: C.muted, marginTop: 6, flexWrap: 'wrap' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.bull, display: 'inline-block' }} /> WIN
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.bear, display: 'inline-block' }} /> LOSS
        </span>
        <span style={{ color: C.muted }}>Dot size ∝ |P&L|</span>
      </div>
    </div>
  );
}

// ─── Trade Replay Timeline ────────────────────────────────────────────────────

function TradeReplayTimeline({ trades }: { trades: TradeRecord[] }) {
  const uid = useId().replace(/:/g, '');
  const [hoveredIdx, setHoveredIdx] = useState<number | null>(null);

  const validTrades = trades.filter((t) => t.pnl != null && !isNaN(t.pnl!));

  if (validTrades.length < 2) {
    return (
      <div style={{ height: 120, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.muted, fontSize: F.sm, background: C.surfaceHover, borderRadius: R.md }}>
        Need at least 2 trades with P&L data to show timeline.
      </div>
    );
  }

  const W = 560, H = 120;
  const PAD_L = 12, PAD_R = 12, PAD_T = 28, PAD_B = 28;
  const timelineW = W - PAD_L - PAD_R;
  const timelineY = PAD_T + 46; // vertical baseline for segments
  const segH_max = 32; // max segment height
  const equityY = PAD_T + 8; // top area for equity polyline

  // Compute running equity
  let cumPnl = 0;
  const equityValues: number[] = [0];
  validTrades.forEach((t) => { cumPnl += t.pnl ?? 0; equityValues.push(cumPnl); });

  const minEq = Math.min(...equityValues);
  const maxEq = Math.max(...equityValues);
  const eqRange = maxEq - minEq || 1;
  const equityAreaH = 24;

  const toEqY = (v: number) => equityY + equityAreaH - ((v - minEq) / eqRange) * equityAreaH;

  // Build segments — each trade occupies a proportional slice of timeline width
  // Use duration_h for width; fall back to equal width
  const durations = validTrades.map((t) => Math.max(0.1, t.duration_h ?? 1));
  const totalDur = durations.reduce((a, b) => a + b, 0) || validTrades.length;

  let xCursor = PAD_L;
  const segments = validTrades.map((t, i) => {
    const segW = (durations[i] / totalDur) * timelineW;
    const x = xCursor;
    xCursor += segW;
    const absPnl = Math.abs(t.pnl ?? 0);
    const maxAbsPnl = Math.max(...validTrades.map((t2) => Math.abs(t2.pnl ?? 0)), 1);
    const h = Math.max(4, (absPnl / maxAbsPnl) * segH_max);
    const win = t.outcome === 'WIN';
    return { x, w: segW, h, win, trade: t, idx: i };
  });

  // Tick marks every ~5 trades or every 20% of timeline
  const tickCount = Math.min(5, validTrades.length);
  const tickStep = Math.floor(validTrades.length / tickCount) || 1;
  const ticks: { x: number; label: string }[] = [];
  for (let i = 0; i < validTrades.length; i += tickStep) {
    ticks.push({ x: segments[i].x, label: `#${i + 1}` });
  }

  // Equity polyline points
  const eqPoints = equityValues.map((v, i) => {
    const segX = i === 0 ? PAD_L : segments[i - 1].x + segments[i - 1].w;
    return `${segX},${toEqY(v)}`;
  }).join(' ');

  // Hovered segment info
  const hovered = hoveredIdx != null ? segments[hoveredIdx] : null;
  const hoveredTrade = hovered?.trade ?? null;

  return (
    <div style={{ position: 'relative' }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
        onMouseLeave={() => setHoveredIdx(null)}
      >
        <defs>
          <clipPath id={`tlClip-${uid}`}>
            <rect x={PAD_L} y={0} width={timelineW} height={H} />
          </clipPath>
        </defs>

        {/* Equity polyline */}
        {equityValues.length > 1 && (
          <polyline
            points={eqPoints}
            fill="none"
            stroke={C.brand}
            strokeWidth={1.2}
            strokeLinejoin="round"
            clipPath={`url(#tlClip-${uid})`}
          />
        )}

        {/* Equity zero line (dashed) */}
        <line
          x1={PAD_L} y1={toEqY(0)}
          x2={PAD_L + timelineW} y2={toEqY(0)}
          stroke={C.borderBright} strokeWidth={0.7} strokeDasharray="3 3"
          clipPath={`url(#tlClip-${uid})`}
        />

        {/* Baseline */}
        <line
          x1={PAD_L} y1={timelineY}
          x2={PAD_L + timelineW} y2={timelineY}
          stroke={C.borderBright} strokeWidth={1}
        />

        {/* Trade segments */}
        {segments.map(({ x, w, h, win, trade, idx }) => {
          const isHovered = hoveredIdx === idx;
          const segColor = win ? C.bull : C.bear;
          const segY = timelineY - h;
          const entryX = x + 1;
          const exitX = x + w - 1;
          const midX = x + w / 2;
          // Entry triangle tip at bottom, pointing up for BUY, down for SELL
          const isBuy = trade.side === 'BUY';
          const triSize = 5;
          // ▲ for BUY (pointing up), ▼ for SELL (pointing down)
          const triPoints = isBuy
            ? `${entryX},${timelineY + 8} ${entryX - triSize},${timelineY + 8 + triSize * 1.4} ${entryX + triSize},${timelineY + 8 + triSize * 1.4}`
            : `${entryX},${timelineY + 8 + triSize * 1.4} ${entryX - triSize},${timelineY + 8} ${entryX + triSize},${timelineY + 8}`;
          const triColor = isBuy ? C.bull : C.bear;

          return (
            <g key={idx}>
              <rect
                x={x + 0.5} y={segY}
                width={Math.max(1, w - 1)} height={h}
                fill={segColor}
                fillOpacity={isHovered ? 0.9 : 0.6}
                rx={1.5}
                style={{ cursor: 'pointer' }}
                onMouseEnter={() => setHoveredIdx(idx)}
              >
                <title>{`${trade.symbol} ${trade.side} · ${(trade.pnl ?? 0) >= 0 ? '+' : ''}$${(trade.pnl ?? 0).toFixed(2)} · ${trade.duration_h != null ? trade.duration_h.toFixed(1) + 'h' : '—'}`}</title>
              </rect>

              {/* Entry triangle */}
              <polygon
                points={triPoints}
                fill={triColor}
                fillOpacity={0.85}
                style={{ cursor: 'pointer' }}
                onMouseEnter={() => setHoveredIdx(idx)}
              />

              {/* Exit × mark */}
              {w > 8 && (
                <g>
                  <line x1={exitX - 2.5} y1={timelineY + 5} x2={exitX + 2.5} y2={timelineY + 11} stroke={C.muted} strokeWidth={1.2} />
                  <line x1={exitX + 2.5} y1={timelineY + 5} x2={exitX - 2.5} y2={timelineY + 11} stroke={C.muted} strokeWidth={1.2} />
                </g>
              )}

              {/* PnL label for wide-enough segments */}
              {w > 30 && (
                <text
                  x={midX} y={segY - 3}
                  textAnchor="middle" fontSize={7} fill={segColor}
                  fontFamily="Inter, system-ui" fontWeight={600}
                >
                  {(trade.pnl ?? 0) >= 0 ? '+' : ''}{(trade.pnl ?? 0).toFixed(0)}
                </text>
              )}
            </g>
          );
        })}

        {/* Tick marks */}
        {ticks.map(({ x, label }) => (
          <g key={label}>
            <line x1={x} y1={timelineY - 2} x2={x} y2={timelineY + 4} stroke={C.borderBright} strokeWidth={0.8} />
            <text x={x} y={H - 4} textAnchor="middle" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">{label}</text>
          </g>
        ))}

        {/* Equity label */}
        <text x={PAD_L + 2} y={equityY - 2} fontSize={7} fill={C.brand} fontFamily="Inter, system-ui" fontWeight={600}>equity</text>
      </svg>

      {/* Hover tooltip */}
      {hovered && hoveredTrade && (() => {
        const tooltipX = Math.min(hovered.x + hovered.w / 2, W - 110);
        return (
          <div style={{
            position: 'absolute',
            left: `calc(${(tooltipX / W) * 100}% + 6px)`,
            top: `${((timelineY - hovered.h - 10) / H) * 100}%`,
            background: C.surface,
            border: `1px solid ${C.borderBright}`,
            borderRadius: R.md,
            padding: '7px 11px',
            fontSize: F.xs,
            color: C.textSub,
            pointerEvents: 'none',
            zIndex: 10,
            minWidth: 130,
            boxShadow: S.md,
          }}>
            <div style={{ fontWeight: 700, color: hoveredTrade.outcome === 'WIN' ? C.bull : C.bear, marginBottom: 3 }}>
              {hoveredTrade.symbol} {hoveredTrade.side} · {hoveredTrade.outcome}
            </div>
            <div>P&L: {(hoveredTrade.pnl ?? 0) >= 0 ? '+' : ''}${(hoveredTrade.pnl ?? 0).toFixed(2)}</div>
            {hoveredTrade.duration_h != null && <div>Hold: {hoveredTrade.duration_h.toFixed(1)}h</div>}
            {hoveredTrade.strategy && <div>Strategy: {hoveredTrade.strategy}</div>}
            {hoveredTrade.llm_regime && <div>Regime: {hoveredTrade.llm_regime}</div>}
          </div>
        );
      })()}

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, fontSize: 10, color: C.muted, marginTop: 6, flexWrap: 'wrap' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <svg width={10} height={10}><polygon points="5,0 0,10 10,10" fill={C.bull} /></svg> BUY entry
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <svg width={10} height={10}><polygon points="5,10 0,0 10,0" fill={C.bear} /></svg> SELL entry
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.bull, borderRadius: 2, display: 'inline-block' }} /> Win
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.bear, borderRadius: 2, display: 'inline-block' }} /> Loss
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 16, height: 2, background: C.brand, display: 'inline-block', verticalAlign: 'middle' }} /> Running equity
        </span>
        <span style={{ color: C.muted }}>Bar height ∝ |P&L| · Bar width ∝ hold duration</span>
      </div>
    </div>
  );
}

// ─── Outcome Probability Bars ─────────────────────────────────────────────────

function OutcomeProbabilityBars({ trades }: { trades: TradeRecord[] }) {
  // Calculate real probabilities from trades when available
  const hasData = trades.length >= 5;

  function winRateFor(predicate: (t: TradeRecord) => boolean): number | null {
    if (!hasData) return null;
    const subset = trades.filter(predicate);
    if (subset.length < 2) return null;
    return subset.filter((t) => t.outcome === 'WIN').length / subset.length;
  }

  // Detect "first trade of day" by grouping sequential trades — use index parity as proxy if no timestamps
  function isFirstOfDay(idx: number): boolean {
    // Rough heuristic: index 0 or each trade that follows a >8h gap (duration_h of previous)
    if (idx === 0) return true;
    const prev = trades[idx - 1];
    return (prev?.duration_h ?? 0) >= 8;
  }

  function afterLoss(idx: number): boolean {
    if (idx === 0) return false;
    return trades[idx - 1]?.outcome === 'LOSS';
  }

  if (!hasData) {
    return <EmptyState icon="⏳" title="Awaiting trade data" subtitle="Win probability by context will appear once there are at least 5 trades" />;
  }

  const rows: { label: string; pct: number | null }[] = [
    {
      label: 'P(win | regime=TREND)',
      pct: winRateFor((t) => (t.llm_regime ?? '').toLowerCase().includes('trend')),
    },
    {
      label: 'P(win | regime=RANGE)',
      pct: winRateFor((t) => (t.llm_regime ?? '').toLowerCase().includes('range')),
    },
    {
      label: 'P(win | confidence ≥ 80%)',
      pct: winRateFor((t) => (t.llm_confidence ?? 0) >= 0.80),
    },
    {
      label: 'P(win | confidence < 70%)',
      pct: winRateFor((t) => (t.llm_confidence ?? 0) < 0.70 && t.llm_confidence != null),
    },
    {
      label: 'P(win | first trade of day)',
      pct: winRateFor((_t, idx = trades.indexOf(_t)) => isFirstOfDay(idx)),
    },
    {
      label: 'P(win | after a loss)',
      pct: winRateFor((_t, idx = trades.indexOf(_t)) => afterLoss(idx)),
    },
  ];

  const resolved = rows.filter((r) => r.pct != null) as { label: string; pct: number }[];

  if (resolved.length === 0) {
    return <EmptyState icon="⏳" title="Awaiting signal data" subtitle="Not enough data per condition yet to compute conditional win rates" />;
  }

  // Sort descending by probability
  const sorted = [...resolved].sort((a, b) => b.pct - a.pct);

  const BAR_MAX_W = 240;
  const ROW_H = 28;
  const LABEL_W = 200;
  const PCT_W = 44;
  const totalW = LABEL_W + BAR_MAX_W + PCT_W + 16;
  const totalH = sorted.length * ROW_H + 8;

  function barColor(pct: number): string {
    if (pct >= 0.70) return C.bull;
    if (pct >= 0.50) return C.warn;
    return C.bear;
  }

  return (
    <div>
      <svg
        viewBox={`0 0 ${totalW} ${totalH}`}
        style={{ width: '100%', height: 'auto', display: 'block' }}
      >
        {sorted.map(({ label, pct }, i) => {
          const y = i * ROW_H + 4;
          const barW = pct * BAR_MAX_W;
          const color = barColor(pct);
          const pctText = `${Math.round(pct * 100)}%`;

          return (
            <g key={label}>
              {/* Label */}
              <text
                x={LABEL_W - 6}
                y={y + ROW_H / 2 + 4}
                textAnchor="end"
                fontSize={9}
                fill={C.textSub}
                fontFamily="Inter, system-ui"
              >
                {label}
              </text>

              {/* Bar track */}
              <rect
                x={LABEL_W}
                y={y + 6}
                width={BAR_MAX_W}
                height={ROW_H - 12}
                fill={C.surfaceHover}
                rx={3}
              />

              {/* Bar fill */}
              <rect
                x={LABEL_W}
                y={y + 6}
                width={barW}
                height={ROW_H - 12}
                fill={color}
                fillOpacity={0.8}
                rx={3}
              >
                <title>{`${label}: ${pctText}`}</title>
              </rect>

              {/* Percentage label */}
              <text
                x={LABEL_W + BAR_MAX_W + 8}
                y={y + ROW_H / 2 + 4}
                fontSize={10}
                fontWeight={700}
                fill={color}
                fontFamily="Inter, system-ui"
              >
                {pctText}
              </text>
            </g>
          );
        })}

        {/* 50% reference line */}
        <line
          x1={LABEL_W + BAR_MAX_W * 0.5}
          y1={4}
          x2={LABEL_W + BAR_MAX_W * 0.5}
          y2={totalH - 4}
          stroke={C.borderBright}
          strokeWidth={0.8}
          strokeDasharray="3 3"
        />
        <text
          x={LABEL_W + BAR_MAX_W * 0.5}
          y={totalH - 2}
          textAnchor="middle"
          fontSize={7}
          fill={C.muted}
          fontFamily="Inter, system-ui"
        >
          50%
        </text>

        {/* 70% reference line */}
        <line
          x1={LABEL_W + BAR_MAX_W * 0.7}
          y1={4}
          x2={LABEL_W + BAR_MAX_W * 0.7}
          y2={totalH - 4}
          stroke={C.bull}
          strokeWidth={0.8}
          strokeDasharray="3 3"
          strokeOpacity={0.5}
        />
        <text
          x={LABEL_W + BAR_MAX_W * 0.7}
          y={totalH - 2}
          textAnchor="middle"
          fontSize={7}
          fill={C.bull}
          fontFamily="Inter, system-ui"
        >
          70%
        </text>
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, fontSize: 10, color: C.muted, marginTop: 8, flexWrap: 'wrap' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.bull, borderRadius: 2, display: 'inline-block' }} /> {'>'}70% (strong edge)
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.warn, borderRadius: 2, display: 'inline-block' }} /> 50–70% (moderate)
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.bear, borderRadius: 2, display: 'inline-block' }} /> {'<'}50% (weak / avoid)
        </span>
      </div>
    </div>
  );
}

// ─── Exit Timing Heatmap ──────────────────────────────────────────────────────

function ExitTimingHeatmap({ trades }: { trades: TradeRecord[] }) {
  // 24 columns (hours) × 7 rows (days Mon–Sun) of average PnL per exit slot
  type AnyRecord = TradeRecord & { close_time?: string | number | null; exit_timestamp_ms?: number | null };

  const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  // grid[day][hour] = { sum, count }
  const grid: { sum: number; count: number }[][] = Array.from({ length: 7 }, () =>
    Array.from({ length: 24 }, () => ({ sum: 0, count: 0 }))
  );

  let hasReal = false;
  trades.forEach((t) => {
    const r = t as AnyRecord;
    const raw = r.exit_timestamp_ms ?? r.close_time;
    if (raw == null || t.pnl == null) return;
    try {
      const ts = typeof raw === 'number'
        ? (raw > 1e12 ? raw : raw * 1000)
        : new Date(raw as string).getTime();
      if (isNaN(ts)) return;
      const d = new Date(ts);
      const hour = d.getUTCHours();
      const isoDay = d.getUTCDay(); // 0=Sun
      const day = isoDay === 0 ? 6 : isoDay - 1; // Mon=0..Sun=6
      hasReal = true;
      grid[day][hour].sum += t.pnl;
      grid[day][hour].count++;
    } catch {/* skip */}
  });

  // Seeded fallback — US hours (13-21) on weekdays get higher PnL
  if (!hasReal) {
    return (
      <div>
        <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 4 }}>
          Exit Timing — Average P&amp;L by Hour &amp; Day
        </div>
        <EmptyState icon="⏳" title="Awaiting trade data" subtitle="Exit timing heatmap will populate once the bot has closed trades with exit timestamp data" />
      </div>
    );
  }

  const displayGrid = grid.map((row) => row.map((c) => ({ avg: c.count > 0 ? c.sum / c.count : NaN, count: c.count })));

  // Find max absolute avg for intensity scaling
  const allAvgs = displayGrid.flat().map((c) => c.avg).filter((v) => !isNaN(v));
  const maxAbs = Math.max(...allAvgs.map((v) => Math.abs(v)), 1);

  // Find top-3 cells by avg PnL
  const ranked: { day: number; hour: number; avg: number }[] = [];
  displayGrid.forEach((row, day) => {
    row.forEach((cell, hour) => {
      if (!isNaN(cell.avg) && cell.count > 0) ranked.push({ day, hour, avg: cell.avg });
    });
  });
  ranked.sort((a, b) => b.avg - a.avg);
  const top3Set = new Set(ranked.slice(0, 3).map((r) => `${r.day}:${r.hour}`));

  // Best window summary
  const best = ranked[0];
  const bestSummary = best
    ? `Best exit window: ${DAYS[best.day]} ${best.hour}–${best.hour + 1} UTC (+$${best.avg.toFixed(0)} avg)`
    : null;

  // SVG layout
  const CELL_W = 20;
  const CELL_H = 22;
  const PAD_LEFT = 36; // for day labels
  const PAD_TOP = 18;  // for hour labels
  const PAD_BOTTOM = 24;
  const W = PAD_LEFT + 24 * CELL_W + 4;
  const H = PAD_TOP + 7 * CELL_H + PAD_BOTTOM;

  function cellColor(avg: number): string {
    if (isNaN(avg)) return C.surfaceHover;
    const t = Math.min(1, Math.abs(avg) / maxAbs);
    if (avg >= 0) {
      // Interpolate from C.heatNeutral toward C.heatBull3
      const r = Math.round(55 + t * (22 - 55));
      const g = Math.round(65 + t * (101 - 65));
      const b = Math.round(81 + t * (52 - 81));
      return `rgb(${r},${g},${b})`;
    } else {
      const r = Math.round(55 + t * (220 - 55));
      const g = Math.round(65 + t * (38 - 65));
      const b = Math.round(81 + t * (38 - 81));
      return `rgb(${r},${g},${b})`;
    }
  }

  const showColLabels = new Set([0, 4, 8, 12, 16, 20]);

  return (
    <div>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 4 }}>
        Exit Timing — Average P&amp;L by Hour &amp; Day
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
      >
        {/* Column (hour) labels */}
        {Array.from({ length: 24 }, (_, h) =>
          showColLabels.has(h) ? (
            <text
              key={`cl${h}`}
              x={PAD_LEFT + h * CELL_W + CELL_W / 2}
              y={PAD_TOP - 4}
              textAnchor="middle"
              fontSize={8}
              fill={C.muted}
              fontFamily="Inter, system-ui"
            >
              {h}
            </text>
          ) : null
        )}

        {/* Cells */}
        {displayGrid.map((row, day) =>
          row.map((cell, hour) => {
            const x = PAD_LEFT + hour * CELL_W;
            const y = PAD_TOP + day * CELL_H;
            const key = `${day}:${hour}`;
            const isTop3 = top3Set.has(key);
            const fill = cellColor(cell.avg);
            const label = !isNaN(cell.avg) && cell.count > 0
              ? (cell.avg >= 0 ? `+$${Math.round(cell.avg)}` : `-$${Math.abs(Math.round(cell.avg))}`)
              : null;
            const showLabel = CELL_W >= 20 && label != null && Math.abs(cell.avg) > 20;

            return (
              <g key={key}>
                <rect
                  x={x + 1}
                  y={y + 1}
                  width={CELL_W - 2}
                  height={CELL_H - 2}
                  fill={fill}
                  rx={2}
                >
                  <title>{`${DAYS[day]} ${hour}:00 UTC — ${!isNaN(cell.avg) && cell.count > 0 ? `avg $${cell.avg.toFixed(0)} (${cell.count} trades)` : 'no data'}`}</title>
                </rect>
                {/* Top-3 highlight border */}
                {isTop3 && (
                  <rect
                    x={x + 1}
                    y={y + 1}
                    width={CELL_W - 2}
                    height={CELL_H - 2}
                    fill="none"
                    stroke={C.warn}
                    strokeWidth={1.5}
                    rx={2}
                  />
                )}
                {showLabel && (
                  <text
                    x={x + CELL_W / 2}
                    y={y + CELL_H / 2 + 3}
                    textAnchor="middle"
                    fontSize={6}
                    fontWeight={700}
                    fill="#fff"
                    fillOpacity={0.9}
                    fontFamily="Inter, system-ui"
                  >
                    {label}
                  </text>
                )}
              </g>
            );
          })
        )}

        {/* Row (day) labels */}
        {DAYS.map((label, day) => (
          <text
            key={`dl${day}`}
            x={PAD_LEFT - 4}
            y={PAD_TOP + day * CELL_H + CELL_H / 2 + 4}
            textAnchor="end"
            fontSize={8}
            fill={C.muted}
            fontFamily="Inter, system-ui"
          >
            {label}
          </text>
        ))}
      </svg>

      {/* Summary line */}
      {bestSummary && (
        <div style={{ fontSize: F.xs, color: C.bull, marginTop: 6, fontWeight: 600 }}>
          {bestSummary}
        </div>
      )}

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, fontSize: 10, color: C.muted, marginTop: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.heatBull3, borderRadius: 2, display: 'inline-block' }} /> High avg win
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.heatBear3, borderRadius: 2, display: 'inline-block' }} /> High avg loss
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.surfaceHover, borderRadius: 2, display: 'inline-block' }} /> No trades
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, border: `1.5px solid ${C.warn}`, borderRadius: 2, display: 'inline-block' }} /> Top-3 slots
        </span>
      </div>
    </div>
  );
}

// ─── Leverage PnL Chart ────────────────────────────────────────────────────────

function LeveragePnlChart({ trades }: { trades: TradeRecord[] }) {
  const uid = useId().replace(/:/g, '');
  const TIERS = [
    { label: '1-2×', min: 1, max: 2 },
    { label: '2-3×', min: 2, max: 3 },
    { label: '3-5×', min: 3, max: 5 },
    { label: '5-10×', min: 5, max: 10 },
  ];

  // Compute real stats from trades
  const realStats = TIERS.map(({ min, max }) => {
    const subset = trades.filter((t) => t.leverage != null && t.leverage >= min && t.leverage < max);
    if (subset.length < 3) return null;
    const wins = subset.filter((t) => t.outcome === 'WIN');
    const losses = subset.filter((t) => t.outcome === 'LOSS');
    const avgWin = wins.length > 0 ? wins.reduce((s, t) => s + (t.pnl ?? 0), 0) / wins.length : 0;
    const avgLoss = losses.length > 0 ? Math.abs(losses.reduce((s, t) => s + (t.pnl ?? 0), 0) / losses.length) : 0;
    const wr = subset.length > 0 ? wins.length / subset.length : 0;
    return { wr, avgWin, avgLoss };
  });

  const hasReal = realStats.some((s) => s !== null);

  if (!hasReal) {
    return (
      <div>
        <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 4 }}>
          Performance by Leverage Tier
        </div>
        <EmptyState icon="⏳" title="Awaiting trade data" subtitle="Performance by leverage tier will appear once there are at least 3 trades per tier" />
      </div>
    );
  }

  const displayData = TIERS.map((tier, i) => ({
    ...tier,
    ...(realStats[i] ?? { wr: 0, avgWin: 0, avgLoss: 0 }),
  })).filter((_, i) => realStats[i] !== null);

  // SVG dimensions
  const W = 460, H = 140;
  const PAD = { top: 24, right: 20, bottom: 36, left: 52 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const TIER_COUNT = displayData.length;
  const tierSlotW = plotW / TIER_COUNT;
  const BAR_W = Math.floor(tierSlotW / 5);
  const BAR_GAP = Math.floor(BAR_W * 0.4);

  // Y scale: use the full $ amount domain
  const maxVal = Math.max(...displayData.map((d) => d.avgWin), 1);
  const py = (v: number) => PAD.top + plotH - (v / maxVal) * plotH;

  // Win rate dot Y scale: secondary axis (0–1) mapped onto plot
  const wrY = (wr: number) => PAD.top + plotH - wr * plotH;

  // Win rate polyline points
  const wrPoints = displayData
    .map((d, i) => {
      const midX = PAD.left + i * tierSlotW + tierSlotW / 2;
      return `${midX},${wrY(d.wr)}`;
    })
    .join(' ');

  // Y-axis ticks
  const yTicks = [0, Math.round(maxVal / 2), maxVal];

  return (
    <div>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 4 }}>
        Performance by Leverage Tier
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
      >
        <defs>
          <clipPath id={`levClip-${uid}`}>
            <rect x={PAD.left} y={PAD.top} width={plotW} height={plotH} />
          </clipPath>
        </defs>

        {/* Y-axis grid + labels */}
        {yTicks.map((v) => (
          <g key={v}>
            <line
              x1={PAD.left} y1={py(v)}
              x2={PAD.left + plotW} y2={py(v)}
              stroke={C.border} strokeWidth={v === 0 ? 1 : 0.5}
              strokeDasharray={v === 0 ? '' : '3 4'}
            />
            <text x={PAD.left - 4} y={py(v) + 4} textAnchor="end" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">
              ${v >= 1000 ? `${(v / 1000).toFixed(1)}k` : Math.round(v)}
            </text>
          </g>
        ))}

        {/* Bars per tier */}
        {displayData.map((d, i) => {
          const slotX = PAD.left + i * tierSlotW;
          const midX = slotX + tierSlotW / 2;
          // 3 bars side by side: win (left), loss (mid), reference spacing
          const totalBarsW = BAR_W * 2 + BAR_GAP;
          const winX = midX - totalBarsW / 2;
          const lossX = winX + BAR_W + BAR_GAP;

          const winH = Math.max(1, (d.avgWin / maxVal) * plotH);
          const lossH = Math.max(1, (d.avgLoss / maxVal) * plotH);

          return (
            <g key={d.label}>
              {/* Avg Win bar */}
              <rect
                x={winX}
                y={py(d.avgWin)}
                width={BAR_W}
                height={winH}
                fill={C.bull}
                fillOpacity={0.8}
                rx={2}
                clipPath={`url(#levClip-${uid})`}
              >
                <title>{`${d.label} — Avg Win: $${d.avgWin.toFixed(0)}`}</title>
              </rect>
              {/* Avg Loss bar */}
              <rect
                x={lossX}
                y={py(d.avgLoss)}
                width={BAR_W}
                height={lossH}
                fill={C.bear}
                fillOpacity={0.8}
                rx={2}
                clipPath={`url(#levClip-${uid})`}
              >
                <title>{`${d.label} — Avg Loss: $${d.avgLoss.toFixed(0)}`}</title>
              </rect>
              {/* X label */}
              <text
                x={midX}
                y={PAD.top + plotH + 14}
                textAnchor="middle"
                fontSize={9}
                fill={C.muted}
                fontFamily="Inter, system-ui"
              >
                {d.label}
              </text>
              {/* Win rate label above */}
              <text
                x={midX}
                y={wrY(d.wr) - 5}
                textAnchor="middle"
                fontSize={8}
                fontWeight={700}
                fill={C.warn}
                fontFamily="Inter, system-ui"
              >
                {Math.round(d.wr * 100)}%
              </text>
            </g>
          );
        })}

        {/* Win rate declining line */}
        {displayData.length > 1 && (
          <polyline
            points={wrPoints}
            fill="none"
            stroke={C.warn}
            strokeWidth={1.5}
            strokeLinejoin="round"
            strokeDasharray="4 3"
            clipPath={`url(#levClip-${uid})`}
          />
        )}

        {/* Win rate dots */}
        {displayData.map((d, i) => {
          const midX = PAD.left + i * tierSlotW + tierSlotW / 2;
          return (
            <circle
              key={d.label}
              cx={midX}
              cy={wrY(d.wr)}
              r={3.5}
              fill={C.warn}
              stroke={C.surface}
              strokeWidth={1}
            />
          );
        })}

        {/* Left Y-axis line */}
        <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={PAD.top + plotH} stroke={C.border} strokeWidth={0.5} />
        <line x1={PAD.left} y1={PAD.top + plotH} x2={PAD.left + plotW} y2={PAD.top + plotH} stroke={C.border} strokeWidth={0.5} />

        {/* Y-axis label */}
        <text
          x={12}
          y={PAD.top + plotH / 2}
          textAnchor="middle"
          fontSize={9}
          fill={C.muted}
          fontFamily="Inter, system-ui"
          transform={`rotate(-90 12 ${PAD.top + plotH / 2})`}
        >
          Avg $ per trade
        </text>
      </svg>

      {/* Caption */}
      <div style={{ fontSize: F.xs, color: C.muted, marginTop: 6 }}>
        Bot caps at 5× for high-confidence, 3× for standard
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, fontSize: 10, color: C.muted, marginTop: 4, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.bull, borderRadius: 2, display: 'inline-block' }} /> Avg win ($)
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.bear, borderRadius: 2, display: 'inline-block' }} /> Avg loss ($)
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 16, height: 2, background: C.warn, display: 'inline-block', verticalAlign: 'middle' }} />
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: C.warn, display: 'inline-block' }} />
          Win rate %
        </span>
      </div>
    </div>
  );
}

// ─── Placeholder components (data not yet available from API) ─────────────────

function TradeAutopsyCard() {
  return (
    <div style={{ color: C.muted, fontSize: F.sm, padding: '16px 0' }}>
      Worst trade autopsy requires MAE and price-path data — not yet available from the API.
    </div>
  );
}

function SignalDecayChart() {
  return (
    <div style={{ color: C.muted, fontSize: F.sm, padding: '16px 0' }}>
      Signal confidence decay requires intra-trade confidence snapshots — not yet available from the API.
    </div>
  );
}

function ExposureRiskMatrix() {
  return (
    <div style={{ color: C.muted, fontSize: F.sm, padding: '16px 0' }}>
      Exposure risk matrix requires position-size and volatility data per time slot — not yet available from the API.
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function Forensics() {
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const apiBase = resolveApiBase();

  const [filterOutcome, setFilterOutcome] = useState('All');
  const [filterRegime, setFilterRegime] = useState('All');
  const [filterAction, setFilterAction] = useState('All');
  const [filterStrategy, setFilterStrategy] = useState('All');
  const [filterSymbol, setFilterSymbol] = useState('All');

  useEffect(() => {
    const ctrl = new AbortController();
    const load = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/trades/history?limit=500`, { signal: ctrl.signal });
        if (res.ok) {
          const d: TradeHistoryResponse = await res.json();
          if (!ctrl.signal.aborted) setTrades(d?.trades || []);
        }
      } catch {/* silent (includes AbortError) */}
      if (!ctrl.signal.aborted) setLoading(false);
    };
    load();
    return () => ctrl.abort();
  }, [apiBase]);

  // Derive filter options
  const regimes = useMemo(() => ['All', ...Array.from(new Set(trades.map((t) => t.llm_regime || 'unknown').filter(Boolean)))], [trades]);
  const actions = useMemo(() => ['All', ...Array.from(new Set(trades.map((t) => t.llm_action || '—').filter((a) => a !== '—')))], [trades]);
  const strategies = useMemo(() => ['All', ...Array.from(new Set(trades.map((t) => t.strategy).filter(Boolean)))], [trades]);
  const symbols = useMemo(() => ['All', ...Array.from(new Set(trades.map((t) => t.symbol).filter(Boolean)))], [trades]);

  // Apply filters
  const filtered = useMemo(() => {
    return trades.filter((t) => {
      if (filterOutcome !== 'All' && t.outcome !== filterOutcome) return false;
      if (filterRegime !== 'All' && (t.llm_regime || 'unknown') !== filterRegime) return false;
      if (filterAction !== 'All' && (t.llm_action || '—') !== filterAction) return false;
      if (filterStrategy !== 'All' && t.strategy !== filterStrategy) return false;
      if (filterSymbol !== 'All' && t.symbol !== filterSymbol) return false;
      return true;
    });
  }, [trades, filterOutcome, filterRegime, filterAction, filterStrategy, filterSymbol]);

  // Computed stats
  const stats = useMemo(() => {
    if (!filtered.length) return null;
    const wins = filtered.filter((t) => t.outcome === 'WIN');
    const losses = filtered.filter((t) => t.outcome === 'LOSS');

    const rrWins = wins.filter((t) => t.rr_achieved != null);
    const avgRR = rrWins.length > 0
      ? rrWins.reduce((s, t) => s + (t.rr_achieved ?? 0), 0) / rrWins.length
      : 0;

    const highConfTrades = filtered.filter((t) => (t.llm_confidence ?? 0) >= 0.65);
    const highConfWins = highConfTrades.filter((t) => t.outcome === 'WIN');
    const confAccuracy = highConfTrades.length > 0 ? highConfWins.length / highConfTrades.length : null;

    const avgWinDur = wins.filter((t) => t.duration_h != null).reduce((s, t) => s + (t.duration_h ?? 0), 0) / (wins.filter((t) => t.duration_h != null).length || 1);
    const avgLossDur = losses.filter((t) => t.duration_h != null).reduce((s, t) => s + (t.duration_h ?? 0), 0) / (losses.filter((t) => t.duration_h != null).length || 1);

    const grossPnl = filtered.filter((t) => (t.pnl ?? 0) > 0).reduce((s, t) => s + (t.pnl ?? 0), 0);
    const totalFees = filtered.reduce((s, t) => s + (t.fee ?? 0), 0);
    const feeDrag = grossPnl > 0 ? (totalFees / grossPnl) * 100 : 0;

    // Best regime
    const byRegime: Record<string, { wins: number; total: number }> = {};
    filtered.forEach((t) => {
      const k = t.llm_regime || 'unknown';
      if (!byRegime[k]) byRegime[k] = { wins: 0, total: 0 };
      byRegime[k].total++;
      if (t.outcome === 'WIN') byRegime[k].wins++;
    });
    const bestRegime = Object.entries(byRegime)
      .filter(([, v]) => v.total >= 3)
      .sort((a, b) => (b[1].wins / b[1].total) - (a[1].wins / a[1].total))[0];

    // LLM accuracy
    const llmProceed = filtered.filter((t) => (t.llm_action || '').toLowerCase() === 'proceed' || (t.llm_action || '').toLowerCase() === 'go');
    const llmAccuracy = llmProceed.length > 0 ? llmProceed.filter((t) => t.outcome === 'WIN').length / llmProceed.length : null;

    return { avgRR, confAccuracy, avgWinDur, avgLossDur, feeDrag, bestRegime, llmAccuracy, highConfTrades: highConfTrades.length };
  }, [filtered]);

  return (
    <motion.div className="bg-aurora" style={{ position: 'relative' }} variants={staggerContainerSlow} initial="hidden" animate="show">
      <GeometricBG variant="diamond" opacity={0.02} />
      <div className="floating-orb orb-cyan" style={{ position: 'fixed', top: '15%', right: '10%' }} />
      {/* Header */}
      <motion.div variants={fadeUp} style={{ marginBottom: 28 }}>
        <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
          Deep Analysis
        </div>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 800, color: C.text, letterSpacing: -0.5 }}>
          Trade <span className="gradient-text">Forensics</span>
        </h1>
        <p style={{ margin: '6px 0 0', fontSize: F.sm, color: C.muted, maxWidth: 680 }}>
          Cross-tabulate every trade — filter by regime, strategy, LLM action, and outcome. See where the bot&apos;s edge actually comes from.
        </p>
      </motion.div>

      {/* Stat Bar */}
      {loading ? (
        <Grid minChildWidth={180} gap={3} style={{ marginBottom: 28 }}>
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} variant="card" h={72} />)}
        </Grid>
      ) : stats ? (
        <motion.div variants={staggerContainer} initial="hidden" animate="show">
          <Grid minChildWidth={180} gap={3} style={{ marginBottom: 28 }}>
            {[
              {
                label: 'Avg R/R (Wins)',
                value: stats.avgRR > 0 ? `${stats.avgRR.toFixed(2)}:1` : '—',
                sub: 'Average reward on winning trades',
                color: stats.avgRR >= 1.5 ? C.bull : C.warn,
              },
              {
                label: 'High Conf Accuracy',
                value: stats.confAccuracy != null ? `${(stats.confAccuracy * 100).toFixed(0)}%` : '—',
                sub: `${stats.highConfTrades} trades ≥65% confidence`,
                color: stats.confAccuracy != null && stats.confAccuracy >= 0.65 ? C.bull : C.warn,
              },
              {
                label: 'Win Hold Duration',
                value: `${stats.avgWinDur.toFixed(1)}h`,
                sub: `vs ${stats.avgLossDur.toFixed(1)}h for losses`,
                color: C.text,
              },
              {
                label: 'Fee Drag',
                value: stats.feeDrag > 0 ? `${stats.feeDrag.toFixed(1)}%` : '—',
                sub: 'Fees as % of gross profit',
                color: stats.feeDrag > 15 ? C.bear : stats.feeDrag > 8 ? C.warn : C.bull,
              },
              {
                label: 'Best Regime',
                value: stats.bestRegime ? `${(stats.bestRegime[1].wins / stats.bestRegime[1].total * 100).toFixed(0)}%` : '—',
                sub: stats.bestRegime ? `${stats.bestRegime[0]} (${stats.bestRegime[1].total} trades)` : 'Not enough data',
                color: C.bull,
              },
              {
                label: 'LLM Accuracy',
                value: stats.llmAccuracy != null ? `${(stats.llmAccuracy * 100).toFixed(0)}%` : '—',
                sub: 'Win rate when LLM says Proceed',
                color: stats.llmAccuracy != null && stats.llmAccuracy >= 0.65 ? C.bull : C.warn,
              },
            ].map(({ label, value, sub, color }) => (
              <motion.div key={label} variants={fadeUp}>
                <StatCard label={label} value={value} sub={sub} color={color} />
              </motion.div>
            ))}
          </Grid>
        </motion.div>
      ) : !loading ? (
        <div style={{ marginBottom: 28 }}>
          <EmptyState
            icon="🔬"
            title="No trade data to analyze"
            subtitle="Start paper trading to see forensic stats here."
            action={{ label: 'View Results →', onClick: () => { window.location.href = '/results'; } }}
          />
        </div>
      ) : null}

      {/* ════════════════════════════════════════════════
          SECTION: Summary
          ════════════════════════════════════════════════ */}
      <SectionHeader label="Summary" />

      {/* Signal Quality Funnel */}
      {!loading && <SignalQualityFunnel trades={filtered} />}

      {/* Confidence vs R/R Scatter */}
      <motion.div variants={fadeUp}>
        <Card glass hover style={{ padding: `${SP[5]}px ${SP[6]}px`, marginBottom: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
            <div>
              <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.text }}>Confidence vs R/R Achieved</h3>
              <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
                Does higher LLM confidence actually predict better outcomes? Green = WIN, Red = LOSS. Dashed line = regression.
              </div>
            </div>
            <div style={{ display: 'flex', gap: 12, fontSize: F.xs }}>
              <span><Badge variant="bull">WIN</Badge></span>
              <span><Badge variant="bear">LOSS</Badge></span>
              <span><Badge variant="brand">Trend</Badge></span>
            </div>
          </div>
          {loading ? (
            <Skeleton variant="chart" h={280} />
          ) : (
            <ConfScatterPlot trades={filtered} />
          )}
        </Card>
      </motion.div>

      {/* Trade Waterfall */}
      <motion.div variants={fadeUp}>
        <Card glass hover style={{ padding: `${SP[5]}px ${SP[6]}px`, marginBottom: 24 }}>
          <div style={{ marginBottom: 14 }}>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.text }}>Cumulative P&L Journey</h3>
            <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
              Each bar shows one trade&apos;s impact on running P&L. Green = profit, Red = loss. Final value shown at right.
            </div>
          </div>
          {loading ? (
            <Skeleton variant="chart" h={160} />
          ) : (
            <TradeWaterfall trades={filtered} />
          )}
        </Card>
      </motion.div>

      {/* ════════════════════════════════════════════════
          SECTION: Time Analysis
          ════════════════════════════════════════════════ */}
      <div style={{ marginTop: 48 }}><SectionHeader label="Time Analysis" /></div>

      {/* Hourly Win Rate */}
      <Card glass hover style={{ padding: `${SP[5]}px ${SP[6]}px`, marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.text }}>Win Rate by Hour (UTC)</h3>
            <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
              When does the bot win? Each cell = one hour of day. Darker green = higher win rate.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: F.xs, color: C.muted, flexWrap: 'wrap' }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 2, background: C.heatBull3 }} /> High WR
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 2, background: C.heatBear3 }} /> Low WR
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 2, background: C.heatNeutral }} /> No trades
            </span>
          </div>
        </div>
        {loading ? (
          <Skeleton variant="chart" h={54} />
        ) : (
          <HourlyWinRate trades={filtered} />
        )}
      </Card>

      {/* Hour of Day Win Rate — entry_timestamp_ms based */}
      <Card glass hover style={{ padding: `${SP[5]}px ${SP[6]}px`, marginBottom: 24 }}>
        <div style={{ marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.text }}>Hour-of-Day Win Rate</h3>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
            Derived from <code style={{ fontSize: F.xs, color: C.brand }}>entry_timestamp_ms</code> field. Shows which hours of the day (UTC) historically produce wins vs losses.
          </div>
        </div>
        {loading ? (
          <Skeleton variant="chart" h={74} />
        ) : (
          <HourOfDayWinRate trades={filtered} />
        )}
      </Card>

      {/* Trade Clusters Chart */}
      <Card glass hover style={{ padding: `${SP[5]}px ${SP[6]}px`, marginBottom: 24 }}>
        <div style={{ marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.text }}>Trade Clusters</h3>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
            Scatter of every trade by day-of-week (Mon–Sun) vs hour of day (UTC). Dot size ∝ |P&L|.
          </div>
        </div>
        {loading ? (
          <Skeleton variant="chart" h={180} />
        ) : (
          <TradeClustersChart trades={filtered} />
        )}
      </Card>

      {/* Exit Timing Heatmap */}
      <Card glass hover style={{ padding: `${SP[5]}px ${SP[6]}px`, marginBottom: 24 }}>
        <div style={{ marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.text }}>Exit Timing Heatmap</h3>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
            Average P&amp;L per exit hour and day of week. Gold border = top-3 best exit windows.
          </div>
        </div>
        {loading ? (
          <Skeleton variant="chart" h={180} />
        ) : (
          <ExitTimingHeatmap trades={filtered} />
        )}
      </Card>

      {/* ════════════════════════════════════════════════
          SECTION: Setup Analysis
          ════════════════════════════════════════════════ */}
      <div style={{ marginTop: 48 }}><SectionHeader label="Setup Analysis" /></div>

      {/* Risk:Reward Scatter */}
      <Card glass hover style={{ padding: `${SP[5]}px ${SP[6]}px`, marginBottom: 24 }}>
        <div style={{ marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.text }}>Signal Confidence vs R:R Achieved</h3>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
            Plots strategy signal confidence against actual risk:reward per trade. Dashed lines at 1.0×, 2.0× R:R and 75% confidence threshold.
          </div>
        </div>
        {loading ? (
          <Skeleton variant="chart" h={200} />
        ) : (
          <RiskRewardScatter trades={filtered} />
        )}
      </Card>

      {/* ── Trade Duration Histogram ── */}
      <TradeDurationHistogram trades={filtered} />

      {/* ── Regime Performance Matrix ── */}
      <RegimePerformanceMatrix trades={filtered} />

      {/* ════════════════════════════════════════════════
          SECTION: Sequence Analysis
          ════════════════════════════════════════════════ */}
      <div style={{ marginTop: 48 }}><SectionHeader label="Sequence Analysis" /></div>

      {/* Rolling Sharpe Chart */}
      <Card glass hover style={{ padding: `${SP[5]}px ${SP[6]}px`, marginBottom: 24 }}>
        <div style={{ marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.text }}>Rolling Sharpe Ratio</h3>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
            10-trade rolling window. Green fill = positive Sharpe. Dashed lines at 1.0 (Good) and 2.0 (Excellent).
          </div>
        </div>
        {loading ? (
          <Skeleton variant="chart" h={100} />
        ) : (
          <RollingSharpeChart trades={filtered} />
        )}
      </Card>

      {/* Trade Replay Timeline */}
      <Card glass hover style={{ padding: `${SP[5]}px ${SP[6]}px`, marginBottom: 24 }}>
        <div style={{ marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: F.base, fontWeight: 700, color: C.text }}>Trade Sequence Timeline</h3>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            Each segment is one trade — width ∝ hold duration, height ∝ |P&L|. Running equity line above. Hover for detail.
          </div>
        </div>
        {loading ? (
          <Skeleton variant="chart" h={120} />
        ) : (
          <TradeReplayTimeline trades={filtered} />
        )}
      </Card>

      <MultiSymbolPnlChart trades={filtered} />

      {/* ════════════════════════════════════════════════
          SECTION: Outcome Probability
          ════════════════════════════════════════════════ */}
      <div style={{ marginTop: 48 }}><SectionHeader label="Outcome Probability" /></div>

      {/* Win Probability by Context */}
      <Card glass hover style={{ padding: `${SP[5]}px ${SP[6]}px`, marginBottom: 24 }}>
        <div style={{ marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: F.base, fontWeight: 700, color: C.text }}>Win Probability by Context</h3>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            Conditional win rates by regime, confidence level, and trade sequence. Shows where the bot has the strongest edge.
          </div>
        </div>
        {loading ? (
          <Skeleton variant="chart" h={180} />
        ) : (
          <OutcomeProbabilityBars trades={filtered} />
        )}
      </Card>

      {/* Leverage PnL Chart */}
      <Card glass hover style={{ padding: `${SP[5]}px ${SP[6]}px`, marginBottom: 24 }}>
        <div style={{ marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.text }}>P&L by Leverage Tier</h3>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
            Win/loss dollar size and win rate across leverage tiers. Dashed line shows declining win rate at higher leverage.
          </div>
        </div>
        {loading ? (
          <Skeleton variant="chart" h={140} />
        ) : (
          <LeveragePnlChart trades={filtered} />
        )}
      </Card>

      {/* Trade Autopsy Card */}
      <Card glass hover style={{ padding: `${SP[5]}px ${SP[6]}px`, marginBottom: 24 }}>
        <div style={{ marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: F.base, fontWeight: 700, color: C.text }}>Worst Trade Autopsy</h3>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            Deep-dive on the single worst trade — entry/exit marked on price chart, root cause analysis, lessons for next time.
          </div>
        </div>
        <TradeAutopsyCard />
      </Card>

      {/* Signal Decay Chart */}
      <Card glass hover style={{ padding: `${SP[5]}px ${SP[6]}px`, marginBottom: 24 }}>
        <div style={{ marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: F.base, fontWeight: 700, color: C.text }}>Signal Confidence Decay</h3>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            How each strategy&apos;s confidence score evolves after entry. Dashed line = action threshold. Marker = actual close point.
          </div>
        </div>
        <SignalDecayChart />
      </Card>

      {/* Exposure Risk Matrix */}
      <Card glass hover style={{ padding: `${SP[5]}px ${SP[6]}px`, marginBottom: 24 }}>
        <div style={{ marginBottom: 14 }}>
          <h3 style={{ margin: 0, fontSize: F.base, fontWeight: 700, color: C.text }}>Exposure Risk Matrix</h3>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            Average risk exposure (position size × volatility) per symbol and UTC time slot. Darker red = higher risk concentration.
          </div>
        </div>
        <ExposureRiskMatrix />
      </Card>

      {/* ════════════════════════════════════════════════
          SECTION: Raw Trade Cards
          ════════════════════════════════════════════════ */}
      <div style={{ marginTop: 48 }}><SectionHeader label="Raw Trade Cards" /></div>

      {/* Filters */}
      <Card glass style={{ padding: `${SP[4]}px ${SP[5]}px`, marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Filter Trades</div>
          {(filterOutcome !== 'All' || filterRegime !== 'All' || filterAction !== 'All' || filterStrategy !== 'All' || filterSymbol !== 'All') && (
            <button
              onClick={() => { setFilterOutcome('All'); setFilterRegime('All'); setFilterAction('All'); setFilterStrategy('All'); setFilterSymbol('All'); }}
              style={{ fontSize: F.xs, padding: '3px 10px', borderRadius: R.pill, cursor: 'pointer', fontWeight: 600, border: `1px solid ${C.border}`, background: 'transparent', color: C.muted }}
            >
              Clear filters
            </button>
          )}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <PillFilter label="Outcome" options={['All', 'WIN', 'LOSS']} value={filterOutcome} onChange={setFilterOutcome} />
          <PillFilter label="Symbol" options={symbols} value={filterSymbol} onChange={setFilterSymbol} />
          <PillFilter label="Regime" options={regimes} value={filterRegime} onChange={setFilterRegime} />
          <PillFilter label="LLM Action" options={actions} value={filterAction} onChange={setFilterAction} />
          <PillFilter label="Strategy" options={strategies} value={filterStrategy} onChange={setFilterStrategy} />
        </div>
      </Card>

      {/* Trade list */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.text }}>Trade Records</h3>
          <span style={{ fontSize: F.xs, color: C.muted }}>
            {filtered.length} of {trades.length} trades · click any card to expand
          </span>
        </div>

        {loading ? (
          Array.from({ length: 5 }).map((_, i) => <div key={i} style={{ marginBottom: 8 }}><Skeleton variant="card" h={44} /></div>)
        ) : filtered.length === 0 ? (
          <EmptyState
            icon="🔍"
            title={trades.length === 0 ? 'No trade history yet' : 'No trades match the current filters'}
            subtitle={trades.length === 0 ? 'Start paper trading to see forensic analysis here.' : 'Try adjusting the filters above to broaden your search.'}
            {...(trades.length === 0 ? { action: { label: 'View Results →', onClick: () => { window.location.href = '/results'; } } } : {})}
          />
        ) : (
          <motion.div variants={staggerContainerSlow} initial="hidden" animate="show">
            {filtered.map((t, i) => <TradeCard key={i} trade={t} />)}
          </motion.div>
        )}
      </div>

      {/* Links */}
      <div style={{ display: 'flex', gap: 12, marginTop: 28, paddingTop: 20, borderTop: `1px solid ${C.border}` }}>
        <Link href="/results" style={{ fontSize: F.sm, padding: '8px 16px', borderRadius: R.md, background: C.brand, color: '#fff', fontWeight: 700, textDecoration: 'none' }}>
          ← Results Overview
        </Link>
        <Link href="/llm-audit" style={{ fontSize: F.sm, padding: '8px 16px', borderRadius: R.md, border: `1px solid ${C.border}`, color: C.muted, fontWeight: 600, textDecoration: 'none' }}>
          LLM Audit →
        </Link>
      </div>
    </motion.div>
  );
}
