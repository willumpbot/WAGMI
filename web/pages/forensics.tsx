'use client';

import React, { useEffect, useState, useMemo } from 'react';
import Link from 'next/link';
import { C, R, F, S, fmtUsd, fmtPct } from '../src/theme';
import type { TradeRecord, TradeHistoryResponse } from '../src/types';

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
  const [tooltip, setTooltip] = useState<{ x: number; y: number; trade: TradeRecord } | null>(null);

  const plotTrades = trades.filter(
    (t) => t.llm_confidence != null && t.rr_achieved != null && !isNaN(t.llm_confidence) && !isNaN(t.rr_achieved!)
  );

  if (plotTrades.length < 3) {
    return (
      <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.muted, fontSize: F.sm, background: C.surfaceHover, borderRadius: R.md }}>
        Need at least 3 trades with LLM confidence data to show scatter plot.
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

  // Linear regression
  const n = plotTrades.length;
  const sumX = confs.reduce((a, b) => a + b, 0);
  const sumY = rrs.reduce((a, b) => a + b, 0);
  const sumXY = confs.reduce((s, x, i) => s + x * rrs[i], 0);
  const sumX2 = confs.reduce((s, x) => s + x * x, 0);
  const denom = n * sumX2 - sumX * sumX;
  const slope = denom !== 0 ? (n * sumXY - sumX * sumY) / denom : 0;
  const intercept = (sumY - slope * sumX) / n;
  const regY1 = intercept + slope * minConf;
  const regY2 = intercept + slope * maxConf;

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
          <clipPath id="scatterClip">
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

        {/* Zero RR line */}
        <line x1={pad.left} y1={py(0)} x2={pad.left + plotW} y2={py(0)} stroke={C.border} strokeWidth={1.5} />

        {/* Regression line */}
        {slope !== 0 && (
          <line
            x1={px(minConf)} y1={py(regY1)}
            x2={px(maxConf)} y2={py(regY2)}
            stroke={C.brand} strokeWidth={1.5} strokeDasharray="5 4"
            clipPath="url(#scatterClip)"
          />
        )}
        {slope > 0 && (
          <text x={px(maxConf) - 5} y={py(regY2) - 6} fontSize={9} fill={C.brand} textAnchor="end" fontFamily="Inter, system-ui">
            +ve correlation
          </text>
        )}

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

        {/* Quadrant labels */}
        <text x={px(75)} y={py(maxRR) + 14} textAnchor="middle" fontSize={8} fill={C.bullMid} fontFamily="Inter, system-ui">High Conf · Good RR</text>
        <text x={px(25)} y={py(maxRR) + 14} textAnchor="middle" fontSize={8} fill={C.muted} fontFamily="Inter, system-ui">Low Conf · Good RR</text>
        <text x={px(75)} y={py(minRR) - 4} textAnchor="middle" fontSize={8} fill={C.bearMid} fontFamily="Inter, system-ui">High Conf · Bad RR</text>
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
          <div>P&L: {fmtUsd(tooltip.trade.pnl)}</div>
        </div>
      )}
    </div>
  );
}

// ─── Trade Waterfall ──────────────────────────────────────────────────────────

function TradeWaterfall({ trades }: { trades: TradeRecord[] }) {
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
        <linearGradient id="wfBullGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.bull} stopOpacity="0.18" />
          <stop offset="100%" stopColor={C.bull} stopOpacity="0.02" />
        </linearGradient>
        <linearGradient id="wfBearGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.bear} stopOpacity="0.02" />
          <stop offset="100%" stopColor={C.bear} stopOpacity="0.18" />
        </linearGradient>
        <clipPath id="wfClip">
          <rect x={pad.left} y={pad.top} width={plotW} height={plotH} />
        </clipPath>
      </defs>

      {/* Profit / loss background tint */}
      {finalPnl >= 0 ? (
        <rect x={pad.left} y={pad.top} width={plotW} height={plotH} fill="url(#wfBullGrad)" rx={2} clipPath="url(#wfClip)" />
      ) : (
        <rect x={pad.left} y={pad.top} width={plotW} height={plotH} fill="url(#wfBearGrad)" rx={2} clipPath="url(#wfClip)" />
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
    <div
      style={{
        background: C.card,
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
          <span style={{
            fontSize: F.xs, fontWeight: 700, padding: '1px 7px', borderRadius: R.pill,
            background: trade.side === 'BUY' ? C.bull + '18' : C.bear + '18',
            color: trade.side === 'BUY' ? C.bullMid : C.bearMid,
          }}>{trade.side}</span>
          <span style={{ fontSize: F.sm, fontWeight: 700, color: win ? C.bull : C.bear, fontVariantNumeric: 'tabular-nums', minWidth: 72 }}>
            {fmtUsd(trade.pnl)}
          </span>
          <span style={{
            fontSize: F.xs, fontWeight: 700, padding: '1px 7px', borderRadius: R.pill,
            background: win ? C.bull + '18' : C.bear + '18',
            color: win ? C.bullMid : C.bearMid,
          }}>{trade.outcome}</span>
          {trade.close_reason && (
            <span style={{
              fontSize: F.xs, fontWeight: 700, padding: '1px 7px', borderRadius: R.pill,
              background: (closeColor[trade.close_reason] || C.muted) + '18',
              color: closeColor[trade.close_reason] || C.muted,
            }}>{trade.close_reason}</span>
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
                  { label: 'R/R Target', value: trade.entry && trade.sl && trade.tp1 ? `${(Math.abs((trade.tp1 - trade.entry) / (trade.entry - trade.sl))).toFixed(2)}:1` : '—' },
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
    </div>
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
    const load = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/trades/history?limit=500`);
        if (res.ok) {
          const d: TradeHistoryResponse = await res.json();
          setTrades(d?.trades || []);
        }
      } catch {/* silent */}
      setLoading(false);
    };
    load();
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

    const avgRR = wins.length > 0
      ? wins.filter((t) => t.rr_achieved != null).reduce((s, t) => s + (t.rr_achieved ?? 0), 0) / wins.filter((t) => t.rr_achieved != null).length
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
    <div>
      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
          Deep Analysis
        </div>
        <h1 style={{ margin: 0, fontSize: 28, fontWeight: 800, color: C.text, letterSpacing: -0.5 }}>
          Trade Forensics
        </h1>
        <p style={{ margin: '6px 0 0', fontSize: F.sm, color: C.muted, maxWidth: 680 }}>
          Cross-tabulate every trade — filter by regime, strategy, LLM action, and outcome. See where the bot&apos;s edge actually comes from.
        </p>
      </div>

      {/* Stat Bar */}
      {loading ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 28 }}>
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} h={72} />)}
        </div>
      ) : stats ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 28 }}>
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
            <div key={label} style={{ padding: '14px 16px', background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, boxShadow: '0 1px 3px rgba(0,0,0,.2)' }}>
              <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.7, marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 22, fontWeight: 800, color, marginBottom: 2, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
              <div style={{ fontSize: 10, color: C.faint }}>{sub}</div>
            </div>
          ))}
        </div>
      ) : null}

      {/* Scatter Plot */}
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px', marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.text }}>Confidence vs R/R Achieved</h2>
            <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
              Does higher LLM confidence actually predict better outcomes? Green = WIN, Red = LOSS. Dashed line = regression.
            </div>
          </div>
          <div style={{ display: 'flex', gap: 12, fontSize: F.xs }}>
            <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: C.bull, marginRight: 4 }} />WIN</span>
            <span><span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: C.bear, marginRight: 4 }} />LOSS</span>
            <span><span style={{ display: 'inline-block', width: 16, height: 2, background: C.brand, marginRight: 4, verticalAlign: 'middle' }} />Trend</span>
          </div>
        </div>
        {loading ? (
          <Skeleton h={280} />
        ) : (
          <ConfScatterPlot trades={filtered} />
        )}
      </div>

      {/* Trade Waterfall */}
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px', marginBottom: 24 }}>
        <div style={{ marginBottom: 14 }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.text }}>Cumulative P&L Journey</h2>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
            Each bar shows one trade&apos;s impact on running P&L. Green = profit, Red = loss. Final value shown at right.
          </div>
        </div>
        {loading ? (
          <Skeleton h={160} />
        ) : (
          <TradeWaterfall trades={filtered} />
        )}
      </div>

      {/* Hourly Win Rate */}
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px', marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.text }}>Win Rate by Hour (UTC)</h2>
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
          <Skeleton h={54} />
        ) : (
          <HourlyWinRate trades={filtered} />
        )}
      </div>

      {/* Filters */}
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px', marginBottom: 20 }}>
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 14 }}>Filter Trades</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <PillFilter label="Outcome" options={['All', 'WIN', 'LOSS']} value={filterOutcome} onChange={setFilterOutcome} />
          <PillFilter label="Symbol" options={symbols} value={filterSymbol} onChange={setFilterSymbol} />
          <PillFilter label="Regime" options={regimes} value={filterRegime} onChange={setFilterRegime} />
          <PillFilter label="LLM Action" options={actions} value={filterAction} onChange={setFilterAction} />
          <PillFilter label="Strategy" options={strategies} value={filterStrategy} onChange={setFilterStrategy} />
        </div>
      </div>

      {/* Trade list */}
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: C.text }}>Trade Records</h2>
          <span style={{ fontSize: F.xs, color: C.muted }}>
            {filtered.length} of {trades.length} trades · click any card to expand
          </span>
        </div>

        {loading ? (
          Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} h={44} style={{ marginBottom: 8 }} />)
        ) : filtered.length === 0 ? (
          <div style={{ padding: '32px 24px', background: C.card, borderRadius: R.lg, border: `1px solid ${C.border}`, textAlign: 'center', color: C.muted, fontSize: F.sm }}>
            No trades match the current filters.
          </div>
        ) : (
          filtered.map((t, i) => <TradeCard key={i} trade={t} />)
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
    </div>
  );
}
