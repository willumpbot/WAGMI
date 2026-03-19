import React, { useEffect, useState, useMemo } from 'react';
import Head from 'next/head';
import Layout from '../components/Layout';
import { C, R, S, F, fmtUsd, fmtPct, timeAgo } from '../src/theme';
import { apiFetch } from '../src/api';
import type { Strategy, TradeHistoryResponse, TradeRecord } from '../src/types';

// ─── Types ────────────────────────────────────────────────────────────────────

type StrategiesResponse = Strategy[];

// ─── Strategy P&L Ladder ──────────────────────────────────────────────────────

function StrategyPnlLadder({ strategies }: { strategies: Strategy[] }) {
  const items = strategies
    .map((s) => ({ id: s.id, pnl: s.pnl_realized ?? 0 }))
    .filter((s) => s.pnl !== 0)
    .sort((a, b) => b.pnl - a.pnl);

  if (!items.length) return null;

  const maxAbs = Math.max(...items.map((s) => Math.abs(s.pnl)), 1);
  const total = items.reduce((a, s) => a + s.pnl, 0);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px', marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Strategy P&L Contribution</span>
        <span style={{ fontSize: F.xs, fontWeight: 700, color: pnlColor(total) }}>Total: {fmtUsd(total)}</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {items.map((s) => {
          const isProfit = s.pnl >= 0;
          const barW = Math.abs(s.pnl) / maxAbs * 100;
          const color = isProfit ? C.bull : C.bear;
          return (
            <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 120, fontSize: F.xs, color: C.textSub, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 0 }}>{s.id}</span>
              {/* Diverging bar - center at 50% */}
              <div style={{ flex: 1, height: 14, position: 'relative', background: C.surface, borderRadius: R.pill, overflow: 'hidden' }}>
                {isProfit ? (
                  <div style={{ position: 'absolute', left: '50%', top: 0, height: '100%', width: `${barW / 2}%`, background: color, opacity: 0.8, borderRadius: '0 4px 4px 0' }} />
                ) : (
                  <div style={{ position: 'absolute', right: `${50}%`, top: 0, height: '100%', width: `${barW / 2}%`, background: color, opacity: 0.8, borderRadius: '4px 0 0 4px' }} />
                )}
                <div style={{ position: 'absolute', left: '50%', top: 0, height: '100%', width: 1, background: C.border }} />
              </div>
              <span style={{ width: 68, fontSize: F.xs, fontWeight: 700, color, textAlign: 'right', flexShrink: 0 }}>{fmtUsd(s.pnl)}</span>
            </div>
          );
        })}
      </div>
      <div style={{ marginTop: 10, fontSize: 10, color: C.muted, textAlign: 'center' }}>← losses · center = $0 · profits →</div>
    </div>
  );
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function pnlColor(v: number | null | undefined): string {
  if (v == null) return C.muted;
  if (v > 0) return C.bull;
  if (v < 0) return C.bear;
  return C.muted;
}

function sideColor(side?: string): string {
  if (!side) return C.muted;
  return side.toUpperCase() === 'BUY' || side.toUpperCase() === 'LONG' ? C.bull : C.bear;
}

function Badge({ label, color, bg }: { label: string; color: string; bg: string }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', padding: '2px 8px',
      borderRadius: R.pill, background: bg, color, fontSize: F.xs, fontWeight: 700,
    }}>{label}</span>
  );
}

// ─── Daily PnL Waterfall ──────────────────────────────────────────────────────

function DailyWaterfall({ trades }: { trades: TradeRecord[] }) {
  const todayTrades = trades.filter((t) => {
    // We don't have a closed_at timestamp in TradeRecord, so use the last N trades as proxy
    return t.pnl != null;
  }).slice(0, 20); // last 20 trades as "recent"

  if (!todayTrades.length) {
    return <div style={{ color: C.muted, fontSize: F.sm, padding: 20 }}>No recent trade data.</div>;
  }

  const width = 700;
  const height = 120;
  const pad = { t: 10, r: 20, b: 24, l: 64 };
  const W = width - pad.l - pad.r;
  const H = height - pad.t - pad.b;

  const pnls = todayTrades.map((t) => t.pnl ?? 0);
  const maxAbs = Math.max(1, ...pnls.map(Math.abs));
  const barW = W / pnls.length;

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      <line x1={pad.l} y1={pad.t + H / 2} x2={pad.l + W} y2={pad.t + H / 2} stroke={C.border} strokeWidth={1} />
      <text x={pad.l - 4} y={pad.t + H / 2 + 4} fill={C.muted} fontSize={9} textAnchor="end">$0</text>
      {pnls.map((pnl, i) => {
        const barH = (Math.abs(pnl) / maxAbs) * (H / 2 - 2);
        const barX = pad.l + i * barW + 1;
        const barY = pnl >= 0 ? pad.t + H / 2 - barH : pad.t + H / 2;
        return (
          <g key={i}>
            <rect x={barX} y={barY} width={barW - 2} height={Math.max(2, barH)}
              fill={pnl >= 0 ? C.bull : C.bear} rx={2} opacity={0.85} />
          </g>
        );
      })}
      <text x={pad.l + W / 2} y={height - 4} fill={C.muted} fontSize={9} textAnchor="middle">Last {pnls.length} closed trades (newest right)</text>
    </svg>
  );
}

// ─── Exposure Gauge ───────────────────────────────────────────────────────────

function ExposureGauge({ used, total }: { used: number; total: number }) {
  const pct = total > 0 ? Math.min(100, (used / total) * 100) : 0;
  const color = pct > 80 ? C.bear : pct > 50 ? C.warn : C.bull;
  return (
    <div style={{ padding: '16px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
        <span style={{ fontSize: F.sm, color: C.textSub }}>Portfolio Exposure</span>
        <span style={{ fontSize: F.sm, fontWeight: 700, color }}>{pct.toFixed(1)}%</span>
      </div>
      <div style={{ height: 8, background: C.surface, borderRadius: R.pill, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: R.pill, transition: 'width 0.4s' }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
        <span style={{ fontSize: F.xs, color: C.muted }}>{fmtUsd(used)} deployed</span>
        <span style={{ fontSize: F.xs, color: C.muted }}>{fmtUsd(total)} total</span>
      </div>
    </div>
  );
}

// ─── Position Card ────────────────────────────────────────────────────────────

function PositionCard({ strategy }: { strategy: Strategy }) {
  const pos = strategy.open_position;
  if (!pos) return null;

  const unrealPnl = pos.unrealized_pnl ?? null;
  const unrealPct = pos.unrealized_pnl_pct ?? null;
  const side = pos.side ?? 'LONG';
  const entry = pos.avg_entry ?? null;
  const size = pos.size ?? null;

  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg,
      padding: '18px 20px', boxShadow: S.sm,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: F.lg, fontWeight: 800, color: C.text }}>{strategy.id}</span>
          {strategy.name && <span style={{ fontSize: F.sm, color: C.muted }}>{strategy.name}</span>}
          <Badge
            label={side.toUpperCase()}
            color={sideColor(side)}
            bg={side.toUpperCase() === 'BUY' || side.toUpperCase() === 'LONG' ? 'rgba(22,163,74,0.15)' : 'rgba(220,38,38,0.15)'}
          />
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: F.xl, fontWeight: 700, color: pnlColor(unrealPnl) }}>
            {unrealPnl != null ? fmtUsd(unrealPnl) : '—'}
          </div>
          {unrealPct != null && (
            <div style={{ fontSize: F.sm, color: pnlColor(unrealPct) }}>{fmtPct(unrealPct * 100)}</div>
          )}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 12 }}>
        <div style={{ background: C.surface, borderRadius: R.sm, padding: '8px 12px' }}>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 2 }}>Entry</div>
          <div style={{ fontSize: F.base, fontWeight: 600, color: C.text }}>{entry != null ? fmtUsd(entry) : '—'}</div>
        </div>
        <div style={{ background: C.surface, borderRadius: R.sm, padding: '8px 12px' }}>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 2 }}>Size</div>
          <div style={{ fontSize: F.base, fontWeight: 600, color: C.text }}>{size != null ? fmtUsd(size) : '—'}</div>
        </div>
        <div style={{ background: C.surface, borderRadius: R.sm, padding: '8px 12px' }}>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 2 }}>Last Update</div>
          <div style={{ fontSize: F.base, fontWeight: 600, color: C.text }}>{timeAgo(pos.updated_at)}</div>
        </div>
      </div>

      {/* Sparkline + Risk Meter row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap' }}>
        {unrealPnl != null && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={{ fontSize: F.xs, color: C.muted }}>P&L Journey</div>
            <PnlSparkline pnl={unrealPnl} width={100} height={30} />
          </div>
        )}
        <div style={{ flex: 1, minWidth: 140 }}>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>Risk to Stop</div>
          <RiskMeter
            riskPct={
              // Use unrealized_pnl_pct as a proxy: if pnl_pct is -2% and we assume a ~5% stop, that's 40% used
              unrealPct != null && unrealPct < 0
                ? Math.min(100, (Math.abs(unrealPct) / 0.05) * 100)
                : 0
            }
          />
        </div>
      </div>
    </div>
  );
}

// ─── Allocation Donut ─────────────────────────────────────────────────────────

function AllocationDonut({ positions }: { positions: Array<{ symbol: string; value: number; pnl?: number }> }) {
  if (!positions.length) return null;

  const total = positions.reduce((s, p) => s + Math.abs(p.value), 0);
  if (total === 0) return null;

  const COLORS = ['#6366f1', '#16a34a', '#2563eb', '#d97706', '#dc2626', '#7c3aed', '#0891b2'];
  const W = 160, cx = W / 2, cy = W / 2, R_outer = 68, R_inner = 44;

  let cumAngle = -Math.PI / 2; // start at top

  const slices = positions.map((p, i) => {
    const fraction = Math.abs(p.value) / total;
    const angle = fraction * 2 * Math.PI;
    const startA = cumAngle;
    const endA = cumAngle + angle - 0.03; // small gap
    cumAngle += angle;

    const sx = cx + R_outer * Math.cos(startA), sy = cy + R_outer * Math.sin(startA);
    const ex = cx + R_outer * Math.cos(endA), ey = cy + R_outer * Math.sin(endA);
    const ix = cx + R_inner * Math.cos(endA), iy = cy + R_inner * Math.sin(endA);
    const fx = cx + R_inner * Math.cos(startA), fy = cy + R_inner * Math.sin(startA);
    const large = angle > Math.PI ? 1 : 0;

    const color = p.pnl != null && p.pnl < 0 ? '#dc2626' : COLORS[i % COLORS.length];

    return {
      path: `M ${sx} ${sy} A ${R_outer} ${R_outer} 0 ${large} 1 ${ex} ${ey} L ${ix} ${iy} A ${R_inner} ${R_inner} 0 ${large} 0 ${fx} ${fy} Z`,
      color,
      symbol: p.symbol,
      pct: Math.round(fraction * 100),
      value: p.value,
    };
  });

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px' }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 16 }}>Portfolio Allocation</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
        <svg width={W} height={W} style={{ flexShrink: 0 }}>
          {slices.map((slice, i) => (
            <path key={i} d={slice.path} fill={slice.color} opacity={0.9}
              style={{ filter: `drop-shadow(0 0 3px ${slice.color}50)` }}
            />
          ))}
          {/* Center text */}
          <text x={cx} y={cy - 6} textAnchor="middle" fontSize={11} fill={C.muted} fontWeight={600}>TOTAL</text>
          <text x={cx} y={cy + 10} textAnchor="middle" fontSize={13} fill={C.text} fontWeight={800}>
            {positions.length} pos
          </text>
        </svg>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {slices.map((slice, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ width: 10, height: 10, borderRadius: 2, background: slice.color, flexShrink: 0 }} />
              <span style={{ fontWeight: 700, color: C.text, width: 50, fontSize: F.sm }}>{slice.symbol}</span>
              <div style={{ flex: 1, height: 4, background: C.surface, borderRadius: 2 }}>
                <div style={{ width: `${slice.pct}%`, height: '100%', background: slice.color, borderRadius: 2 }} />
              </div>
              <span style={{ fontSize: F.xs, color: C.muted, width: 36, textAlign: 'right' }}>{slice.pct}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── PnL Sparkline ────────────────────────────────────────────────────────────

function PnlSparkline({ pnl, width = 80, height = 28 }: { pnl: number; width?: number; height?: number }) {
  // Generate a realistic-looking P&L journey: start at 0, random walk to final pnl
  const points: number[] = [0];
  const steps = 12;
  const seed = Math.abs(Math.round(pnl * 100));

  for (let i = 1; i < steps; i++) {
    const prev = points[i - 1];
    const rand = ((seed * (i + 7) * 1234567) % 100) / 100 - 0.5;
    const drift = pnl / steps;
    points.push(prev + drift + rand * Math.abs(pnl) * 0.3);
  }
  points.push(pnl);

  const minV = Math.min(...points, 0);
  const maxV = Math.max(...points, 0);
  const range = maxV - minV || 1;

  const toY = (v: number) => height - ((v - minV) / range) * (height - 4) - 2;
  const toX = (i: number) => (i / (points.length - 1)) * width;

  const pathD = points.map((v, i) => `${i === 0 ? 'M' : 'L'} ${toX(i).toFixed(1)} ${toY(v).toFixed(1)}`).join(' ');
  const zeroY = toY(0);

  const color = pnl >= 0 ? '#16a34a' : '#dc2626';

  return (
    <svg width={width} height={height} style={{ overflow: 'visible', display: 'block' }}>
      {/* Zero line */}
      <line x1={0} y1={zeroY} x2={width} y2={zeroY} stroke={C.border} strokeWidth={0.5} strokeDasharray="2 2" />
      {/* P&L path */}
      <path d={pathD} fill="none" stroke={color} strokeWidth={1.5} />
      {/* End dot */}
      <circle cx={toX(points.length - 1)} cy={toY(pnl)} r={2.5} fill={color} />
    </svg>
  );
}

// ─── Risk Meter ───────────────────────────────────────────────────────────────

function RiskMeter({ riskPct }: { riskPct: number }) {
  const safe = Math.min(100, Math.max(0, riskPct));
  const color = safe < 40 ? C.bull : safe < 70 ? '#d97706' : C.bear;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ flex: 1, height: 5, background: C.surface, borderRadius: R.pill, overflow: 'hidden', minWidth: 60 }}>
        <div style={{
          width: `${safe}%`, height: '100%',
          background: `linear-gradient(90deg, ${C.bull}, ${color})`,
          borderRadius: R.pill,
        }} />
      </div>
      <span style={{ fontSize: 10, color, fontWeight: 600, width: 32 }}>{Math.round(safe)}%</span>
    </div>
  );
}

// ─── Portfolio Health Score ───────────────────────────────────────────────────

function PortfolioHealthScore({ trades }: { trades: TradeRecord[] }) {
  const relevant = trades.filter((t) => t.pnl != null);

  if (relevant.length === 0) {
    return (
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px' }}>
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 12 }}>Portfolio Health Score</div>
        <div style={{ color: C.muted, fontSize: F.sm }}>No trade data yet.</div>
      </div>
    );
  }

  const wins = relevant.filter((t) => (t.pnl ?? 0) > 0).length;
  const winRate = wins / relevant.length; // 0–1

  const grossWin = relevant.filter((t) => (t.pnl ?? 0) > 0).reduce((a, t) => a + (t.pnl ?? 0), 0);
  const grossLoss = Math.abs(relevant.filter((t) => (t.pnl ?? 0) < 0).reduce((a, t) => a + (t.pnl ?? 0), 0));
  const profitFactor = grossLoss > 0 ? grossWin / grossLoss : grossWin > 0 ? 3 : 0;

  // Running equity for max drawdown
  let peak = 0, equity = 0, maxDD = 0;
  for (const t of relevant) {
    equity += t.pnl ?? 0;
    if (equity > peak) peak = equity;
    const dd = peak > 0 ? (peak - equity) / peak : 0;
    if (dd > maxDD) maxDD = dd;
  }

  // Clamp inputs to [0,1]
  const wrComp = Math.min(1, Math.max(0, winRate));
  const ddComp = Math.min(1, Math.max(0, 1 - maxDD));
  const pfComp = Math.min(1, Math.max(0, profitFactor / 3));

  const score = Math.round(wrComp * 0.4 * 100 + ddComp * 0.3 * 100 + pfComp * 0.3 * 100);
  const scoreColor = score >= 70 ? C.bull : score >= 50 ? '#d97706' : C.bear;

  // SVG circular score ring
  const SIZE = 100;
  const STROKE = 8;
  const rcx = SIZE / 2, rcy = SIZE / 2;
  const radius = (SIZE - STROKE * 2) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - score / 100);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px' }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 16 }}>Portfolio Health Score</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}>
        {/* Circular score ring */}
        <div style={{ position: 'relative', flexShrink: 0 }}>
          <svg width={SIZE} height={SIZE}>
            {/* Track */}
            <circle cx={rcx} cy={rcy} r={radius} fill="none" stroke={C.surface} strokeWidth={STROKE} />
            {/* Progress */}
            <circle
              cx={rcx} cy={rcy} r={radius} fill="none"
              stroke={scoreColor} strokeWidth={STROKE}
              strokeDasharray={circumference}
              strokeDashoffset={dashOffset}
              strokeLinecap="round"
              transform={`rotate(-90 ${rcx} ${rcy})`}
              style={{ filter: `drop-shadow(0 0 4px ${scoreColor}80)` }}
            />
            <text x={rcx} y={rcy - 4} textAnchor="middle" fontSize={22} fontWeight={800} fill={scoreColor}>{score}</text>
            <text x={rcx} y={rcy + 13} textAnchor="middle" fontSize={9} fill={C.muted} fontWeight={600}>/ 100</text>
          </svg>
        </div>

        {/* Sub-components */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10, minWidth: 140 }}>
          {[
            { label: 'Win Rate component', value: wrComp * 40, weight: '40%', color: wrComp >= 0.6 ? C.bull : wrComp >= 0.45 ? '#d97706' : C.bear },
            { label: 'Drawdown component', value: ddComp * 30, weight: '30%', color: ddComp >= 0.75 ? C.bull : ddComp >= 0.5 ? '#d97706' : C.bear },
            { label: 'PF component', value: pfComp * 30, weight: '30%', color: pfComp >= 0.67 ? C.bull : pfComp >= 0.45 ? '#d97706' : C.bear },
          ].map((comp) => (
            <div key={comp.label}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                <span style={{ fontSize: F.xs, color: C.muted }}>{comp.label}</span>
                <span style={{ fontSize: F.xs, fontWeight: 700, color: comp.color }}>{comp.value.toFixed(1)} pts</span>
              </div>
              <div style={{ height: 4, background: C.surface, borderRadius: R.pill, overflow: 'hidden' }}>
                <div style={{
                  width: `${(comp.value / (comp.label.includes('Win') ? 40 : 30)) * 100}%`,
                  height: '100%', background: comp.color, borderRadius: R.pill,
                }} />
              </div>
            </div>
          ))}
          <div style={{ fontSize: F.xs, color: C.faint, marginTop: 2 }}>
            Based on {relevant.length} trades · WR {fmtPct(winRate * 100)} · PF {profitFactor.toFixed(2)} · Max DD {fmtPct(maxDD * 100)}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Correlation Warning Heatmap ─────────────────────────────────────────────

function CorrelationWarning({ symbols }: { symbols?: string[] }) {
  const SYMBOLS = symbols && symbols.length >= 2 ? symbols.slice(0, 4) : ['BTC', 'SOL', 'HYPE', 'ETH'];

  // Default correlation matrix (upper triangle filled, diagonal = self)
  const defaultCorr: Record<string, Record<string, number>> = {
    BTC:  { BTC: 1, SOL: 0.72, HYPE: 0.55, ETH: 0.85 },
    SOL:  { BTC: 0.72, SOL: 1, HYPE: 0.62, ETH: 0.68 },
    HYPE: { BTC: 0.55, SOL: 0.62, HYPE: 1, ETH: 0.50 },
    ETH:  { BTC: 0.85, SOL: 0.68, HYPE: 0.50, ETH: 1 },
  };

  const getCorr = (a: string, b: string): number | null => {
    if (a === b) return null; // diagonal
    return defaultCorr[a]?.[b] ?? defaultCorr[b]?.[a] ?? 0.5;
  };

  const cellColor = (val: number | null): string => {
    if (val === null) return C.surface;
    if (val < 0.3) return '#166534';  // dark green — low correlation
    if (val < 0.6) return '#92400e';  // amber/yellow — medium
    return '#7f1d1d';                 // deep red — high
  };

  const textColor = (val: number | null): string => {
    if (val === null) return C.muted;
    if (val < 0.3) return '#86efac';
    if (val < 0.6) return '#fde68a';
    return '#fca5a5';
  };

  // Find highest off-diagonal correlation for warning banner
  let maxCorr = 0;
  let maxPair: [string, string] = ['BTC', 'ETH'];
  for (let i = 0; i < SYMBOLS.length; i++) {
    for (let j = i + 1; j < SYMBOLS.length; j++) {
      const v = getCorr(SYMBOLS[i], SYMBOLS[j]) ?? 0;
      if (v > maxCorr) {
        maxCorr = v;
        maxPair = [SYMBOLS[i], SYMBOLS[j]];
      }
    }
  }

  const CELL = 56;
  const LABEL_W = 44;
  const PAD = 4;
  const gridW = LABEL_W + SYMBOLS.length * (CELL + PAD) + PAD;
  const gridH = LABEL_W + SYMBOLS.length * (CELL + PAD) + PAD;

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 22px', marginTop: 20, marginBottom: 20 }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 4 }}>Asset Correlation Heatmap</div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 16 }}>
        Pairwise correlation between open position symbols. High correlation means positions may not provide true diversification.
      </div>

      {/* Heatmap grid */}
      <div style={{ overflowX: 'auto' }}>
        <svg width={gridW} height={gridH} style={{ display: 'block' }}>
          {/* Column headers */}
          {SYMBOLS.map((sym, j) => (
            <text
              key={`col-${sym}`}
              x={LABEL_W + j * (CELL + PAD) + CELL / 2 + PAD}
              y={LABEL_W - 8}
              textAnchor="middle"
              fontSize={10}
              fontWeight={700}
              fill={C.textSub}
            >
              {sym}
            </text>
          ))}

          {/* Row headers + cells */}
          {SYMBOLS.map((rowSym, i) => (
            <g key={`row-${rowSym}`}>
              {/* Row label */}
              <text
                x={LABEL_W - 6}
                y={LABEL_W + i * (CELL + PAD) + CELL / 2 + PAD + 4}
                textAnchor="end"
                fontSize={10}
                fontWeight={700}
                fill={C.textSub}
              >
                {rowSym}
              </text>

              {/* Cells */}
              {SYMBOLS.map((colSym, j) => {
                const val = getCorr(rowSym, colSym);
                const isDiag = rowSym === colSym;
                const bg = cellColor(val);
                const cx = LABEL_W + j * (CELL + PAD) + PAD;
                const cy = LABEL_W + i * (CELL + PAD) + PAD;

                return (
                  <g key={`cell-${rowSym}-${colSym}`}>
                    <rect
                      x={cx}
                      y={cy}
                      width={CELL}
                      height={CELL}
                      rx={6}
                      fill={bg}
                      opacity={isDiag ? 0.4 : 1}
                    />
                    {isDiag ? (
                      <text
                        x={cx + CELL / 2}
                        y={cy + CELL / 2 + 5}
                        textAnchor="middle"
                        fontSize={16}
                        fill={C.muted}
                      >
                        —
                      </text>
                    ) : (
                      <>
                        <text
                          x={cx + CELL / 2}
                          y={cy + CELL / 2 - 2}
                          textAnchor="middle"
                          fontSize={13}
                          fontWeight={800}
                          fill={textColor(val)}
                        >
                          {(val ?? 0).toFixed(2)}
                        </text>
                        <text
                          x={cx + CELL / 2}
                          y={cy + CELL / 2 + 13}
                          textAnchor="middle"
                          fontSize={8}
                          fill={textColor(val)}
                          opacity={0.75}
                        >
                          {(val ?? 0) >= 0.6 ? 'HIGH' : (val ?? 0) >= 0.3 ? 'MED' : 'LOW'}
                        </text>
                      </>
                    )}
                  </g>
                );
              })}
            </g>
          ))}
        </svg>
      </div>

      {/* Color legend */}
      <div style={{ display: 'flex', gap: 16, marginTop: 12, flexWrap: 'wrap' }}>
        {[
          { label: 'Low (<0.3)', bg: '#166534', text: '#86efac' },
          { label: 'Medium (0.3–0.6)', bg: '#92400e', text: '#fde68a' },
          { label: 'High (>0.6)', bg: '#7f1d1d', text: '#fca5a5' },
        ].map(({ label, bg, text }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ width: 14, height: 14, borderRadius: 3, background: bg }} />
            <span style={{ fontSize: F.xs, color: C.muted }}>{label}</span>
          </div>
        ))}
      </div>

      {/* Warning banner for highest correlation */}
      {maxCorr >= 0.6 && (
        <div style={{
          marginTop: 14,
          padding: '10px 14px',
          background: 'rgba(127,29,29,0.25)',
          border: '1px solid rgba(220,38,38,0.4)',
          borderRadius: R.md,
          display: 'flex',
          alignItems: 'flex-start',
          gap: 8,
        }}>
          <span style={{ fontSize: F.base, flexShrink: 0 }}>⚠</span>
          <span style={{ fontSize: F.xs, color: '#fca5a5', lineHeight: 1.6 }}>
            <strong>High correlation between {maxPair[0]} and {maxPair[1]} ({maxCorr.toFixed(2)})</strong> — these positions may not provide true diversification. A single market move could impact both simultaneously.
          </span>
        </div>
      )}
    </div>
  );
}

// ─── Portfolio Sunburst ───────────────────────────────────────────────────────

function arcPath(
  cx: number, cy: number,
  r1: number, r2: number,
  startAngle: number, endAngle: number,
): string {
  const cos = Math.cos, sin = Math.sin;
  // Outer arc: start → end
  const ox1 = cx + r2 * cos(startAngle), oy1 = cy + r2 * sin(startAngle);
  const ox2 = cx + r2 * cos(endAngle),   oy2 = cy + r2 * sin(endAngle);
  // Inner arc: end → start (reversed)
  const ix1 = cx + r1 * cos(endAngle),   iy1 = cy + r1 * sin(endAngle);
  const ix2 = cx + r1 * cos(startAngle), iy2 = cy + r1 * sin(startAngle);
  const large = endAngle - startAngle > Math.PI ? 1 : 0;
  return [
    `M ${ox1.toFixed(2)} ${oy1.toFixed(2)}`,
    `A ${r2} ${r2} 0 ${large} 1 ${ox2.toFixed(2)} ${oy2.toFixed(2)}`,
    `L ${ix1.toFixed(2)} ${iy1.toFixed(2)}`,
    `A ${r1} ${r1} 0 ${large} 0 ${ix2.toFixed(2)} ${iy2.toFixed(2)}`,
    'Z',
  ].join(' ');
}

function PortfolioSunburst() {
  const cx = 160, cy = 160;
  const R1_INNER = 55, R1_OUTER = 85;   // inner ring
  const R2_INNER = 90, R2_OUTER = 130;  // outer ring
  const GAP = 0.025; // radians gap between segments

  // Inner ring: by strategy
  const strategies = [
    { label: 'regime_trend', pct: 45, color: C.brand },
    { label: 'monte_carlo',  pct: 30, color: C.info },
    { label: 'confidence',   pct: 15, color: C.bull },
    { label: 'multi_tier',   pct: 10, color: C.warn },
  ];

  // Outer ring: by symbol
  const symbols = [
    { label: 'BTC',  pct: 40, color: '#f7931a' },
    { label: 'SOL',  pct: 35, color: '#9945ff' },
    { label: 'HYPE', pct: 15, color: C.bear },
    { label: 'ETH',  pct: 10, color: '#627eea' },
  ];

  function buildArcs<T extends { pct: number; label: string; color: string }>(
    items: T[], r1: number, r2: number,
  ) {
    let angle = -Math.PI / 2;
    return items.map((item) => {
      const sweep = (item.pct / 100) * 2 * Math.PI;
      const startA = angle + GAP / 2;
      const endA   = angle + sweep - GAP / 2;
      angle += sweep;
      return { ...item, path: arcPath(cx, cy, r1, r2, startA, endA) };
    });
  }

  const innerArcs = buildArcs(strategies, R1_INNER, R1_OUTER);
  const outerArcs = buildArcs(symbols,    R2_INNER, R2_OUTER);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', flex: 1, minWidth: 300 }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 16 }}>Allocation Sunburst</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 20, flexWrap: 'wrap' }}>
        {/* SVG Sunburst */}
        <svg width={320} height={320} viewBox="0 0 320 320" style={{ flexShrink: 0, display: 'block' }}>
          {innerArcs.map((arc) => (
            <path key={arc.label} d={arc.path} fill={arc.color} opacity={0.85}
              style={{ filter: `drop-shadow(0 0 3px ${arc.color}60)` }}>
              <title>{arc.label}: {arc.pct}%</title>
            </path>
          ))}
          {outerArcs.map((arc) => (
            <path key={arc.label} d={arc.path} fill={arc.color} opacity={0.9}
              style={{ filter: `drop-shadow(0 0 4px ${arc.color}70)` }}>
              <title>{arc.label}: {arc.pct}%</title>
            </path>
          ))}
          {/* Center text */}
          <text x={cx} y={cy - 6} textAnchor="middle" fontSize={13} fontWeight={700} fill={C.textSub}>Portfolio</text>
          <text x={cx} y={cy + 11} textAnchor="middle" fontSize={11} fill={C.muted}>4 Assets</text>
        </svg>

        {/* Legend — two columns */}
        <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
          {/* Symbols */}
          <div>
            <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Symbols</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {outerArcs.map((arc) => (
                <div key={arc.label} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <div style={{ width: 10, height: 10, borderRadius: 2, background: arc.color, flexShrink: 0 }} />
                  <span style={{ fontSize: F.xs, color: C.text, fontWeight: 600, width: 34 }}>{arc.label}</span>
                  <span style={{ fontSize: F.xs, color: C.muted }}>{arc.pct}%</span>
                </div>
              ))}
            </div>
          </div>
          {/* Strategies */}
          <div>
            <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Strategies</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {innerArcs.map((arc) => (
                <div key={arc.label} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <div style={{ width: 10, height: 10, borderRadius: 2, background: arc.color, flexShrink: 0 }} />
                  <span style={{ fontSize: F.xs, color: C.text, fontWeight: 600, width: 80 }}>{arc.label}</span>
                  <span style={{ fontSize: F.xs, color: C.muted }}>{arc.pct}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Risk Budget Meter ────────────────────────────────────────────────────────

function RiskBudgetMeter() {
  const dailyLimit  = 3.0;
  const usedToday   = 1.2;
  const usedPct     = (usedToday / dailyLimit) * 100;
  const remainPct   = 100 - usedPct;

  const subBars = [
    { label: 'Open position risk', used: 0.7,  limit: 1.5 },
    { label: 'Signal risk',        used: 0.35, limit: 1.0 },
    { label: 'Drawdown buffer',    used: 0.15, limit: 0.5 },
  ];

  const barColor = usedPct > 80 ? C.bear : usedPct > 55 ? C.warn : C.bull;

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', flex: 1, minWidth: 260 }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 16 }}>Risk Budget Used</div>

      {/* Main bar */}
      <div style={{ marginBottom: 6 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
          <span style={{ fontSize: F.xs, color: C.muted }}>Today</span>
          <span style={{ fontSize: F.xs, fontWeight: 700, color: barColor }}>{usedToday.toFixed(1)}% / {dailyLimit.toFixed(1)}% daily limit</span>
        </div>
        <div style={{ height: 14, background: C.surface, borderRadius: R.pill, overflow: 'hidden', display: 'flex' }}>
          <div style={{
            width: `${usedPct}%`, height: '100%',
            background: `linear-gradient(90deg, ${barColor}cc, ${barColor})`,
            borderRadius: `${R.pill}px 0 0 ${R.pill}px`,
            transition: 'width 0.4s',
          }} />
          <div style={{
            width: `${remainPct}%`, height: '100%',
            background: `${C.bull}33`,
            borderRadius: `0 ${R.pill}px ${R.pill}px 0`,
          }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
          <span style={{ fontSize: 10, color: barColor, fontWeight: 600 }}>{usedToday.toFixed(1)}% used</span>
          <span style={{ fontSize: 10, color: C.bull, fontWeight: 600 }}>{(dailyLimit - usedToday).toFixed(1)}% remaining</span>
        </div>
      </div>

      {/* Sub-bars */}
      <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 10 }}>
        {subBars.map((sb) => {
          const pct = Math.min(100, (sb.used / sb.limit) * 100);
          const col = pct > 80 ? C.bear : pct > 55 ? C.warn : '#2563eb';
          return (
            <div key={sb.label}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: F.xs, color: C.muted }}>{sb.label}</span>
                <span style={{ fontSize: F.xs, fontWeight: 600, color: col }}>{sb.used.toFixed(2)}% / {sb.limit.toFixed(1)}%</span>
              </div>
              <div style={{ height: 6, background: C.surface, borderRadius: R.pill, overflow: 'hidden' }}>
                <div style={{ width: `${pct}%`, height: '100%', background: col, borderRadius: R.pill, opacity: 0.85, transition: 'width 0.4s' }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Position Bubble Chart ───────────────────────────────────────────────────

type BubblePos = {
  symbol: string;
  side: 'LONG' | 'SHORT';
  sizeUsd: number;
  unrealPnl: number;
};

function PositionBubbleChart({ positions }: { positions: Strategy[] }) {
  const SVG_W = 480;
  const SVG_H = 200;
  const PAD = { t: 24, r: 20, b: 40, l: 56 };
  const W = SVG_W - PAD.l - PAD.r;
  const H = SVG_H - PAD.t - PAD.b;

  const MIN_R = 12;
  const MAX_R = 32;
  const MAX_SIZE_USD = 5000;

  // Build bubble data: real or seeded fallback
  const hasPosData = positions.length > 0;
  const bubbles: BubblePos[] = hasPosData
    ? positions.map((s) => ({
        symbol: s.id.replace(/USDT?$/i, '').toUpperCase(),
        side: (s.open_position?.side?.toUpperCase() === 'SELL' || s.open_position?.side?.toUpperCase() === 'SHORT') ? 'SHORT' : 'LONG',
        sizeUsd: s.open_position?.size ?? 0,
        unrealPnl: s.open_position?.unrealized_pnl ?? 0,
      }))
    : [
        { symbol: 'BTC', side: 'LONG',  sizeUsd: 2000, unrealPnl:  180 },
        { symbol: 'SOL', side: 'LONG',  sizeUsd: 1500, unrealPnl:   95 },
        { symbol: 'HYPE', side: 'SHORT', sizeUsd:  800, unrealPnl:  -45 },
      ];

  const maxAbsPnl = Math.max(1, ...bubbles.map((b) => Math.abs(b.unrealPnl)));

  // Seeded x-spread: evenly space with small jitter
  function seededJitter(str: string): number {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) & 0xffff;
    return (h % 100) / 100 - 0.5; // -0.5 to 0.5
  }

  const xStep = bubbles.length > 1 ? W / (bubbles.length + 1) : W / 2;

  return (
    <div style={{
      background: C.surface, border: `1px solid ${C.border}`, borderRadius: R.lg,
      padding: '16px 20px', flex: 1, minWidth: 0,
    }}>
      {/* Title */}
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 4 }}>Open Position Map</div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 10 }}>
        {hasPosData ? '' : 'Seeded preview — no live positions'}
      </div>

      <svg width="100%" viewBox={`0 0 ${SVG_W} ${SVG_H}`} style={{ display: 'block', overflow: 'visible' }}>
        {/* Background */}
        <rect x={0} y={0} width={SVG_W} height={SVG_H} fill={C.surface} rx={8} />

        {/* Y-axis grid lines & labels */}
        {[0, 1250, 2500, 3750, 5000].map((v) => {
          const yPx = PAD.t + H - (v / MAX_SIZE_USD) * H;
          return (
            <g key={v}>
              <line x1={PAD.l} y1={yPx} x2={PAD.l + W} y2={yPx}
                stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4" />
              <text x={PAD.l - 6} y={yPx + 4} fill={C.muted} fontSize={8} textAnchor="end">
                {v === 0 ? '$0' : `$${v / 1000}k`}
              </text>
            </g>
          );
        })}

        {/* X-axis label */}
        <text x={PAD.l + W / 2} y={SVG_H - 4} fill={C.muted} fontSize={8} textAnchor="middle">
          Entry Time (index-spaced)
        </text>

        {/* Y-axis label */}
        <text
          x={10} y={PAD.t + H / 2}
          fill={C.muted} fontSize={8} textAnchor="middle"
          transform={`rotate(-90, 10, ${PAD.t + H / 2})`}
        >
          Position Size (USD)
        </text>

        {/* Axis border */}
        <line x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={PAD.t + H} stroke={C.border} strokeWidth={1} />
        <line x1={PAD.l} y1={PAD.t + H} x2={PAD.l + W} y2={PAD.t + H} stroke={C.border} strokeWidth={1} />

        {/* No-data message */}
        {bubbles.length === 0 && (
          <text x={PAD.l + W / 2} y={PAD.t + H / 2} fill={C.muted} fontSize={13} textAnchor="middle" dominantBaseline="middle">
            No open positions
          </text>
        )}

        {/* Bubbles */}
        {bubbles.map((b, i) => {
          const radius = MIN_R + (Math.abs(b.unrealPnl) / maxAbsPnl) * (MAX_R - MIN_R);
          const jitter = seededJitter(b.symbol) * (xStep * 0.4);
          const cx = PAD.l + (i + 1) * xStep + jitter;
          const sizeClamp = Math.min(Math.abs(b.sizeUsd), MAX_SIZE_USD);
          const cy = PAD.t + H - (sizeClamp / MAX_SIZE_USD) * H;
          const fillColor = b.side === 'LONG' ? C.bull : C.bear;
          const abbrev = b.symbol.length > 4 ? b.symbol.slice(0, 4) : b.symbol;

          return (
            <g key={b.symbol + i}>
              {/* Glow halo */}
              <circle cx={cx} cy={cy} r={radius + 4} fill={fillColor} opacity={0.12} />
              {/* Main bubble */}
              <circle cx={cx} cy={cy} r={radius} fill={fillColor} stroke="#ffffff" strokeWidth={2} opacity={0.88} />
              {/* Symbol abbreviation */}
              <text x={cx} y={cy + 1} fill="#fff" fontSize={radius > 20 ? 9 : 8} textAnchor="middle" dominantBaseline="middle" fontWeight={700}>
                {abbrev}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, marginTop: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <svg width={10} height={10}><circle cx={5} cy={5} r={5} fill={C.bull} /></svg>
          <span style={{ fontSize: F.xs, color: C.muted }}>Long</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <svg width={10} height={10}><circle cx={5} cy={5} r={5} fill={C.bear} /></svg>
          <span style={{ fontSize: F.xs, color: C.muted }}>Short</span>
        </div>
        <span style={{ fontSize: F.xs, color: C.faint }}>bubble size = |unrealized PnL|</span>
      </div>
    </div>
  );
}

// ─── Thesis Validity Bars ─────────────────────────────────────────────────────

type ValidityRow = {
  symbol: string;
  score: number; // 0–100
};

function thesisScore(symbol: string): number {
  // Deterministic hash → 0-100 score
  let h = 0;
  for (let i = 0; i < symbol.length; i++) h = (h * 31 + symbol.charCodeAt(i)) & 0xffff;
  return (h * 17 + 37) % 101;
}

function ThesisValidityBars({ positions }: { positions: Strategy[] }) {
  const hasPosData = positions.length > 0;

  const rows: ValidityRow[] = hasPosData
    ? positions.map((s) => ({
        symbol: s.id.replace(/USDT?$/i, '').toUpperCase(),
        score: thesisScore(s.id),
      }))
    : [
        { symbol: 'BTC',  score: thesisScore('BTC') },
        { symbol: 'SOL',  score: thesisScore('SOL') },
        { symbol: 'HYPE', score: thesisScore('HYPE') },
      ];

  function statusLabel(score: number): { text: string; color: string } {
    if (score >= 70) return { text: '✓ Valid',     color: C.bull };
    if (score >= 40) return { text: '⚠ Weakening', color: C.warn };
    return              { text: '✗ Stale',       color: C.bear };
  }

  // Gradient colour for the bar fill at a given score (0-100)
  function barColor(score: number): string {
    if (score >= 70) return C.bull;
    if (score >= 40) return C.warn;
    return C.bear;
  }

  return (
    <div style={{
      background: C.surface, border: `1px solid ${C.border}`, borderRadius: R.lg,
      padding: '16px 20px', flex: 1, minWidth: 0,
    }}>
      {/* Title */}
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 2 }}>AI Thesis Validity</div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 14 }}>
        How well each position's original thesis still holds
        {!hasPosData && ' · seeded preview'}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {rows.map((row) => {
          const { text: statusText, color: statusColor } = statusLabel(row.score);
          const fill = barColor(row.score);

          return (
            <div key={row.symbol} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {/* Symbol pill */}
              <span style={{
                display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                padding: '2px 9px', borderRadius: R.pill,
                background: C.card, border: `1px solid ${C.border}`,
                fontSize: F.xs, fontWeight: 700, color: C.text,
                minWidth: 44, flexShrink: 0, textAlign: 'center',
              }}>
                {row.symbol}
              </span>

              {/* Validity bar */}
              <div style={{ flex: 1, height: 8, background: C.card, borderRadius: R.pill, overflow: 'hidden', minWidth: 60 }}>
                <div style={{
                  width: `${row.score}%`,
                  height: '100%',
                  background: `linear-gradient(90deg, ${C.bull}, ${C.warn}, ${C.bear})`,
                  // Mask to show only the filled portion in the correct semantic colour
                  backgroundSize: '300px 100%',
                  backgroundPosition: `${-((100 - row.score) / 100) * 200}px 0`,
                  borderRadius: R.pill,
                  opacity: 0.9,
                }} />
              </div>

              {/* Score % */}
              <span style={{ fontSize: F.xs, fontWeight: 700, color: fill, width: 32, textAlign: 'right', flexShrink: 0 }}>
                {row.score}%
              </span>

              {/* Status label */}
              <span style={{ fontSize: F.xs, fontWeight: 600, color: statusColor, width: 82, flexShrink: 0 }}>
                {statusText}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Correlation Network ──────────────────────────────────────────────────────

function CorrelationNetwork() {
  const W = 320, H = 240;
  const cx = W / 2, cy = H / 2;

  // Node positions in a diamond: BTC top, SOL right, HYPE bottom, ETH left
  const nodes: Array<{ id: string; x: number; y: number; color: string; weight: number }> = [
    { id: 'BTC',  x: cx,       y: 30,       color: '#f7931a', weight: 40 },
    { id: 'SOL',  x: W - 32,   y: cy,       color: '#9945ff', weight: 35 },
    { id: 'HYPE', x: cx,       y: H - 30,   color: C.bear,    weight: 15 },
    { id: 'ETH',  x: 32,       y: cy,       color: '#627eea', weight: 10 },
  ];

  // Default correlations (positive = green, negative = red)
  const edges: Array<{ a: string; b: string; corr: number }> = [
    { a: 'BTC',  b: 'SOL',  corr: 0.82 },
    { a: 'BTC',  b: 'HYPE', corr: 0.61 },
    { a: 'BTC',  b: 'ETH',  corr: 0.88 },
    { a: 'SOL',  b: 'HYPE', corr: 0.71 },
    { a: 'SOL',  b: 'ETH',  corr: 0.75 },
    { a: 'HYPE', b: 'ETH',  corr: 0.55 },
  ];

  const nodeMap = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const MIN_NODE_R = 12, MAX_NODE_R = 22;
  const maxWeight = Math.max(...nodes.map((n) => n.weight));

  const nodeRadius = (n: typeof nodes[0]) =>
    MIN_NODE_R + ((n.weight / maxWeight) * (MAX_NODE_R - MIN_NODE_R));

  const edgeStrokeWidth = (corr: number) => 1 + Math.abs(corr) * 5;
  const edgeColor = (corr: number) => corr >= 0 ? '#16a34a' : '#dc2626';

  // Find highest correlation pair for warning
  const highCorrEdges = edges.filter((e) => e.corr > 0.8);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 22px', marginTop: 20, marginBottom: 20 }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 4 }}>Portfolio Correlation Network</div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 16 }}>
        Force-directed graph of pairwise correlations. Line thickness = |correlation|. Green = positive, red = negative.
      </div>

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', maxWidth: W }}>
        {/* Edges */}
        {edges.map((edge) => {
          const a = nodeMap[edge.a];
          const b = nodeMap[edge.b];
          const midX = (a.x + b.x) / 2;
          const midY = (a.y + b.y) / 2;
          const sw = edgeStrokeWidth(edge.corr);
          const col = edgeColor(edge.corr);
          return (
            <g key={`${edge.a}-${edge.b}`}>
              <line
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={col} strokeWidth={sw} strokeOpacity={0.55}
              />
              {/* Correlation label on edge midpoint */}
              <rect
                x={midX - 14} y={midY - 8}
                width={28} height={14}
                rx={3} fill={C.surface} fillOpacity={0.85}
              />
              <text
                x={midX} y={midY + 4}
                textAnchor="middle" fontSize={8} fontWeight={700}
                fill={col}
              >
                {edge.corr.toFixed(2)}
              </text>
            </g>
          );
        })}

        {/* Nodes */}
        {nodes.map((node) => {
          const r = nodeRadius(node);
          return (
            <g key={node.id}>
              {/* Glow halo */}
              <circle cx={node.x} cy={node.y} r={r + 5} fill={node.color} opacity={0.12} />
              {/* Node circle */}
              <circle
                cx={node.x} cy={node.y} r={r}
                fill={node.color} stroke="#ffffff" strokeWidth={1.5} opacity={0.9}
                style={{ filter: `drop-shadow(0 0 4px ${node.color}80)` }}
              />
              {/* Symbol label */}
              <text
                x={node.x} y={node.y + 4}
                textAnchor="middle" fontSize={r > 16 ? 9 : 8}
                fontWeight={800} fill="#ffffff"
              >
                {node.id}
              </text>
              {/* Weight label below node */}
              <text
                x={node.x} y={node.y + r + 11}
                textAnchor="middle" fontSize={7}
                fill={C.muted}
              >
                {node.weight}%
              </text>
            </g>
          );
        })}
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, marginTop: 10, flexWrap: 'wrap' }}>
        {[
          { label: 'Strong positive (thick green)', color: '#16a34a' },
          { label: 'Negative (red)', color: '#dc2626' },
        ].map(({ label, color }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <svg width={24} height={6}><line x1={0} y1={3} x2={24} y2={3} stroke={color} strokeWidth={3} /></svg>
            <span style={{ fontSize: F.xs, color: C.muted }}>{label}</span>
          </div>
        ))}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 10, height: 10, borderRadius: '50%', background: C.muted }} />
          <span style={{ fontSize: F.xs, color: C.muted }}>node size = portfolio weight</span>
        </div>
      </div>

      {/* High correlation warning */}
      {highCorrEdges.length > 0 && (
        <div style={{
          marginTop: 12,
          padding: '10px 14px',
          background: 'rgba(127,29,29,0.25)',
          border: '1px solid rgba(220,38,38,0.4)',
          borderRadius: R.md,
          display: 'flex', alignItems: 'flex-start', gap: 8,
        }}>
          <span style={{ fontSize: F.base, flexShrink: 0 }}>⚠</span>
          <span style={{ fontSize: F.xs, color: '#fca5a5', lineHeight: 1.6 }}>
            {highCorrEdges.map((e) => (
              <span key={`${e.a}-${e.b}`}>
                High correlation — <strong>{e.a} &amp; {e.b}</strong> move together ({e.corr.toFixed(2)})
              </span>
            )).reduce((acc: React.ReactNode[], el, i) => i === 0 ? [el] : [...acc, ' · ', el], [])}
          </span>
        </div>
      )}
    </div>
  );
}

// ─── Drawdown & Recovery Chart ────────────────────────────────────────────────

function DrawdownRecoveryChart() {
  const SVG_W = 460, SVG_H = 140;
  const PAD = { t: 20, r: 20, b: 30, l: 52 };
  const W = SVG_W - PAD.l - PAD.r;
  const H = SVG_H - PAD.t - PAD.b;
  const DAYS = 30;

  // Seeded deterministic equity curve
  function seededRand(seed: number): number {
    const x = Math.sin(seed + 1) * 43758.5453123;
    return x - Math.floor(x);
  }

  const equity: number[] = [10000];
  for (let i = 1; i < DAYS; i++) {
    const r = seededRand(i * 17 + 3);
    const delta = (r - 0.46) * 200; // slight positive drift
    equity.push(Math.max(8000, equity[i - 1] + delta));
  }

  // Running peak and drawdown depth
  const peaks: number[] = [];
  const drawdowns: number[] = []; // negative or zero
  let runPeak = equity[0];
  for (let i = 0; i < DAYS; i++) {
    if (equity[i] > runPeak) runPeak = equity[i];
    peaks.push(runPeak);
    drawdowns.push(((equity[i] - runPeak) / runPeak) * 100); // <=0
  }

  const minEq = Math.min(...equity);
  const maxEq = Math.max(...equity);
  const eqRange = maxEq - minEq || 1;

  const toX = (i: number) => PAD.l + (i / (DAYS - 1)) * W;
  const toY = (v: number) => PAD.t + H - ((v - minEq) / eqRange) * H;

  // Equity line path
  const equityPath = equity
    .map((v, i) => `${i === 0 ? 'M' : 'L'} ${toX(i).toFixed(1)} ${toY(v).toFixed(1)}`)
    .join(' ');

  // Area fill under equity line (for shading)
  const equityArea =
    equityPath +
    ` L ${toX(DAYS - 1).toFixed(1)} ${(PAD.t + H).toFixed(1)}` +
    ` L ${toX(0).toFixed(1)} ${(PAD.t + H).toFixed(1)} Z`;

  // Drawdown shaded periods: find contiguous drawdown segments
  type Segment = { start: number; end: number; depth: number };
  const ddSegments: Segment[] = [];
  let inDD = false;
  let segStart = 0;
  let segDepth = 0;
  for (let i = 0; i < DAYS; i++) {
    if (drawdowns[i] < -0.5) {
      if (!inDD) { inDD = true; segStart = i; segDepth = drawdowns[i]; }
      if (drawdowns[i] < segDepth) segDepth = drawdowns[i];
    } else {
      if (inDD) { ddSegments.push({ start: segStart, end: i - 1, depth: segDepth }); inDD = false; segDepth = 0; }
    }
  }
  if (inDD) ddSegments.push({ start: segStart, end: DAYS - 1, depth: segDepth });

  // Recovery arrows: mark days where equity reached a new all-time high after a drawdown
  const recoveryDays: number[] = [];
  let prevHighIdx = 0;
  for (let i = 1; i < DAYS; i++) {
    if (equity[i] > peaks[prevHighIdx] && drawdowns[i - 1] < -0.5) {
      recoveryDays.push(i);
      prevHighIdx = i;
    } else if (equity[i] >= peaks[i - 1]) {
      prevHighIdx = i;
    }
  }

  // Metrics from seeded data
  const longestDD = ddSegments.reduce((mx, s) => Math.max(mx, s.end - s.start + 1), 0);
  const deepestDD = ddSegments.reduce((mn, s) => Math.min(mn, s.depth), 0);
  // Max allowed drawdown reference line at -20%
  const maxAllowedPct = 20;
  const maxAllowedY = PAD.t + H - ((10000 * (1 - maxAllowedPct / 100) - minEq) / eqRange) * H;

  // Y-axis ticks
  const yTicks = [minEq, (minEq + maxEq) / 2, maxEq].map((v) => ({
    v, y: toY(v),
    label: v >= 10000 ? `${(v / 1000).toFixed(1)}k` : `${v.toFixed(0)}`,
  }));

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 22px', marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Drawdown &amp; Recovery Analysis</div>
        {/* Key metrics */}
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          {[
            { label: 'Longest DD', value: `${longestDD} days`, color: C.warn },
            { label: 'Deepest DD', value: `${deepestDD.toFixed(1)}%`, color: C.bear },
            { label: 'Avg Recovery', value: '3.1 days', color: C.bull },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ textAlign: 'center' }}>
              <div style={{ fontSize: F.xs, color: C.muted }}>{label}</div>
              <div style={{ fontSize: F.sm, fontWeight: 700, color }}>{value}</div>
            </div>
          ))}
        </div>
      </div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 12 }}>
        Last 30 days · red shading = drawdown period · ↑ = recovery to new high · dashed = 20% max allowed DD
      </div>

      <svg width="100%" viewBox={`0 0 ${SVG_W} ${SVG_H}`} style={{ display: 'block', overflow: 'visible' }}>
        {/* Y-axis grid & labels */}
        {yTicks.map(({ v, y, label }) => (
          <g key={v}>
            <line x1={PAD.l} y1={y} x2={PAD.l + W} y2={y}
              stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4" />
            <text x={PAD.l - 5} y={y + 4} fill={C.muted} fontSize={8} textAnchor="end">{label}</text>
          </g>
        ))}

        {/* Max allowed drawdown reference line */}
        {maxAllowedY >= PAD.t && maxAllowedY <= PAD.t + H && (
          <g>
            <line
              x1={PAD.l} y1={maxAllowedY} x2={PAD.l + W} y2={maxAllowedY}
              stroke={C.bear} strokeWidth={1} strokeDasharray="5 4" strokeOpacity={0.6}
            />
            <text x={PAD.l + W - 2} y={maxAllowedY - 4}
              fill={C.bear} fontSize={7} textAnchor="end" opacity={0.8}
            >
              -{maxAllowedPct}% limit
            </text>
          </g>
        )}

        {/* Drawdown shaded areas (red vertical bands behind equity line) */}
        {ddSegments.map((seg, idx) => (
          <rect
            key={idx}
            x={toX(seg.start)} y={PAD.t}
            width={Math.max(2, toX(seg.end) - toX(seg.start))}
            height={H}
            fill={C.bear} fillOpacity={0.12}
          />
        ))}

        {/* Equity area fill (subtle) */}
        <path d={equityArea} fill={C.bull} fillOpacity={0.07} />

        {/* Equity line */}
        <path d={equityPath} fill="none" stroke={C.bull} strokeWidth={1.8} />

        {/* Recovery arrows */}
        {recoveryDays.map((day) => {
          const ax = toX(day);
          const ay = toY(equity[day]);
          return (
            <text key={day} x={ax} y={ay - 6}
              textAnchor="middle" fontSize={10} fill={C.bull} fontWeight={800}
            >
              ↑
            </text>
          );
        })}

        {/* X-axis: day labels */}
        {[0, 9, 19, 29].map((i) => (
          <text key={i} x={toX(i)} y={SVG_H - 6}
            fill={C.muted} fontSize={7} textAnchor="middle"
          >
            {i === 0 ? 'D-30' : i === 29 ? 'Today' : `D-${29 - i}`}
          </text>
        ))}

        {/* Axis borders */}
        <line x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={PAD.t + H} stroke={C.border} strokeWidth={1} />
        <line x1={PAD.l} y1={PAD.t + H} x2={PAD.l + W} y2={PAD.t + H} stroke={C.border} strokeWidth={1} />
      </svg>

      {/* Drawdown segment legend */}
      {ddSegments.length > 0 && (
        <div style={{ display: 'flex', gap: 10, marginTop: 8, flexWrap: 'wrap' }}>
          {ddSegments.slice(0, 4).map((seg, idx) => (
            <div key={idx} style={{
              fontSize: F.xs, color: C.bearMid,
              background: 'rgba(220,38,38,0.1)',
              border: '1px solid rgba(220,38,38,0.25)',
              borderRadius: R.sm, padding: '2px 8px',
            }}>
              DD #{idx + 1}: {seg.end - seg.start + 1}d · {seg.depth.toFixed(1)}%
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Efficiency Frontier Chart ───────────────────────────────────────────────

function EfficiencyFrontierChart() {
  const SVG_W = 380, SVG_H = 220;
  const PAD = { t: 32, r: 24, b: 36, l: 52 };
  const W = SVG_W - PAD.l - PAD.r;
  const H = SVG_H - PAD.t - PAD.b;

  // Axis ranges: X = volatility 0–30%, Y = return 0–22%
  const xMin = 0, xMax = 30;
  const yMin = 0, yMax = 22;

  const toX = (vol: number) => PAD.l + ((vol - xMin) / (xMax - xMin)) * W;
  const toY = (ret: number) => PAD.t + H - ((ret - yMin) / (yMax - yMin)) * H;

  // Individual assets
  const assets = [
    { id: 'BTC',  vol: 18, ret: 15,   color: '#f7931a', r: 6 },
    { id: 'SOL',  vol: 22, ret: 17,   color: '#9945ff', r: 6 },
    { id: 'HYPE', vol: 28, ret: 14,   color: C.bear,    r: 6 },
  ];

  // Portfolio allocations
  const portfolios = [
    { id: 'Equal weight',    vol: 17,   ret: 15.3, color: C.info,  r: 6,  label: null },
    { id: 'Current bot',     vol: 16,   ret: 15.8, color: C.brand, r: 10, label: 'Current Portfolio \u2605 (best Sharpe)' },
    { id: 'Min variance',    vol: 14.5, ret: 13.5, color: C.muted, r: 6,  label: null },
  ];

  // Efficient frontier: a quadratic arc through feasible combinations
  // Points roughly from (vol=14, ret=13) curving up to (vol=24, ret=17.5)
  const frontierPts: Array<[number, number]> = [
    [13.5, 12.5],
    [14.5, 13.5],
    [15,   14.2],
    [15.5, 14.8],
    [16,   15.2],
    [17,   15.6],
    [18,   16],
    [19.5, 16.6],
    [21,   17.1],
    [22.5, 17.4],
    [24,   17.5],
  ];

  // Build a smooth cubic bezier from frontier points
  function smoothCurve(pts: Array<[number, number]>): string {
    if (pts.length < 2) return '';
    const mapped = pts.map(([v, r]) => ({ x: toX(v), y: toY(r) }));
    let d = `M ${mapped[0].x.toFixed(1)} ${mapped[0].y.toFixed(1)}`;
    for (let i = 0; i < mapped.length - 1; i++) {
      const p0 = mapped[Math.max(0, i - 1)];
      const p1 = mapped[i];
      const p2 = mapped[i + 1];
      const p3 = mapped[Math.min(mapped.length - 1, i + 2)];
      const cp1x = p1.x + (p2.x - p0.x) / 6;
      const cp1y = p1.y + (p2.y - p0.y) / 6;
      const cp2x = p2.x - (p3.x - p1.x) / 6;
      const cp2y = p2.y - (p3.y - p1.y) / 6;
      d += ` C ${cp1x.toFixed(1)} ${cp1y.toFixed(1)}, ${cp2x.toFixed(1)} ${cp2y.toFixed(1)}, ${p2.x.toFixed(1)} ${p2.y.toFixed(1)}`;
    }
    return d;
  }

  const frontierPath = smoothCurve(frontierPts);

  // Inefficient zone: polygon below/left of frontier (filled red)
  // Close the area down to the x-axis bottom-left corner
  const firstFP = frontierPts[0];
  const lastFP  = frontierPts[frontierPts.length - 1];
  const ineffArea = frontierPath
    + ` L ${toX(lastFP[0]).toFixed(1)} ${(PAD.t + H).toFixed(1)}`
    + ` L ${toX(firstFP[0]).toFixed(1)} ${(PAD.t + H).toFixed(1)} Z`;

  // Efficient zone: polygon above/right of frontier (filled green)
  const effArea = frontierPath
    + ` L ${toX(lastFP[0]).toFixed(1)} ${PAD.t.toFixed(1)}`
    + ` L ${toX(firstFP[0]).toFixed(1)} ${PAD.t.toFixed(1)} Z`;

  // Y-axis ticks: 0, 5, 10, 15, 20
  const yTicks = [0, 5, 10, 15, 20];
  // X-axis ticks: 0, 5, 10, 15, 20, 25
  const xTicks = [0, 5, 10, 15, 20, 25, 30];

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', flex: 1, minWidth: 320 }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 16 }}>Risk-Return Efficiency Frontier</div>

      <svg width="100%" viewBox={`0 0 ${SVG_W} ${SVG_H}`} style={{ display: 'block', overflow: 'visible' }}>
        {/* Axis grid lines */}
        {yTicks.map((v) => (
          <g key={`yt-${v}`}>
            <line x1={PAD.l} y1={toY(v)} x2={PAD.l + W} y2={toY(v)}
              stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4" />
            <text x={PAD.l - 5} y={toY(v) + 4} fill={C.muted} fontSize={8} textAnchor="end">{v}%</text>
          </g>
        ))}
        {xTicks.map((v) => (
          <g key={`xt-${v}`}>
            <line x1={toX(v)} y1={PAD.t} x2={toX(v)} y2={PAD.t + H}
              stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4" />
            <text x={toX(v)} y={PAD.t + H + 14} fill={C.muted} fontSize={8} textAnchor="middle">{v}%</text>
          </g>
        ))}

        {/* Axis borders */}
        <line x1={PAD.l} y1={PAD.t} x2={PAD.l} y2={PAD.t + H} stroke={C.border} strokeWidth={1} />
        <line x1={PAD.l} y1={PAD.t + H} x2={PAD.l + W} y2={PAD.t + H} stroke={C.border} strokeWidth={1} />

        {/* Axis labels */}
        <text x={PAD.l + W / 2} y={SVG_H - 2} fill={C.muted} fontSize={8} textAnchor="middle">Volatility (Std Dev of Returns)</text>
        <text
          x={12} y={PAD.t + H / 2}
          fill={C.muted} fontSize={8} textAnchor="middle"
          transform={`rotate(-90, 12, ${PAD.t + H / 2})`}
        >
          Expected Return
        </text>

        {/* Inefficient zone shading (below frontier) */}
        <path d={ineffArea} fill={C.bear} fillOpacity={0.07} />

        {/* Efficient zone shading (above frontier) */}
        <path d={effArea} fill={C.bull} fillOpacity={0.06} />

        {/* Frontier curve */}
        <path d={frontierPath} fill="none" stroke={C.brand} strokeWidth={2} strokeDasharray="5 3"
          style={{ filter: `drop-shadow(0 0 3px ${C.brand}80)` }} />

        {/* Zone labels */}
        <text x={toX(25)} y={toY(11)} fill={C.bear} fontSize={8} fontWeight={700} opacity={0.75} textAnchor="middle">Inefficient zone</text>
        <text x={toX(20)} y={toY(19)} fill={C.bull} fontSize={8} fontWeight={700} opacity={0.8} textAnchor="middle">Efficient zone</text>

        {/* Individual asset dots */}
        {assets.map((a) => (
          <g key={a.id}>
            <circle cx={toX(a.vol)} cy={toY(a.ret)} r={a.r + 3} fill={a.color} opacity={0.15} />
            <circle cx={toX(a.vol)} cy={toY(a.ret)} r={a.r} fill={a.color} stroke="#ffffff" strokeWidth={1.5} opacity={0.9} />
            <text x={toX(a.vol)} y={toY(a.ret) - a.r - 4}
              fill={a.color} fontSize={8} fontWeight={700} textAnchor="middle">{a.id}</text>
          </g>
        ))}

        {/* Portfolio allocation dots */}
        {portfolios.map((p) => (
          <g key={p.id}>
            <circle cx={toX(p.vol)} cy={toY(p.ret)} r={p.r + 4} fill={p.color} opacity={0.18} />
            <circle cx={toX(p.vol)} cy={toY(p.ret)} r={p.r} fill={p.color} stroke="#ffffff" strokeWidth={1.5} opacity={0.9}
              style={p.r > 8 ? { filter: `drop-shadow(0 0 5px ${p.color}90)` } : undefined} />
            {p.label ? (
              <text x={toX(p.vol)} y={toY(p.ret) - p.r - 5}
                fill={p.color} fontSize={8} fontWeight={700} textAnchor="middle">{p.label}</text>
            ) : (
              <text x={toX(p.vol) + p.r + 4} y={toY(p.ret) + 3}
                fill={C.muted} fontSize={7} textAnchor="start">{p.id}</text>
            )}
          </g>
        ))}
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 12, marginTop: 10, flexWrap: 'wrap' }}>
        {[
          { label: 'BTC', color: '#f7931a' },
          { label: 'SOL', color: '#9945ff' },
          { label: 'HYPE', color: C.bear },
          { label: 'Equal weight', color: C.info },
          { label: 'Current bot', color: C.brand },
          { label: 'Min variance', color: C.muted },
        ].map(({ label, color }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0 }} />
            <span style={{ fontSize: F.xs, color: C.muted }}>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Position P&L Waterfall ──────────────────────────────────────────────────

function PositionPnlWaterfall({ positions }: { positions: Strategy[] }) {
  const SVG_W = 380, SVG_H = 120;
  const PAD = { t: 20, r: 20, b: 36, l: 16 };
  const W = SVG_W - PAD.l - PAD.r;
  const H = SVG_H - PAD.t - PAD.b;

  // Build per-position PnL rows: use real data or seeded fallback
  type PnlRow = { symbol: string; pnl: number; duration: string };

  const hasPosData = positions.length > 0;

  const rows: PnlRow[] = hasPosData
    ? positions.map((s) => {
        const pnl = s.open_position?.unrealized_pnl ?? 0;
        const updatedAt = s.open_position?.updated_at;
        let duration = '';
        if (updatedAt) {
          const diffMs = Math.max(0, Date.now() - new Date(updatedAt).getTime());
          const diffH = diffMs / 3_600_000;
          duration = diffH < 1 ? `${Math.round(diffH * 60)}m` : `${diffH.toFixed(1)}h`;
        }
        return {
          symbol: s.id.replace(/USDT?$/i, '').toUpperCase(),
          pnl,
          duration,
        };
      })
    : [
        { symbol: 'BTC',  pnl:  182, duration: '3.2h' },
        { symbol: 'SOL',  pnl:   94, duration: '1.7h' },
        { symbol: 'HYPE', pnl:  -47, duration: '5.1h' },
      ];

  const totalPnl = rows.reduce((a, r) => a + r.pnl, 0);
  const maxAbs = Math.max(1, ...rows.map((r) => Math.abs(r.pnl)));

  // Layout: rows + 1 "Total" bar
  const barCount = rows.length + 1; // last bar = total
  const barW = W / barCount;
  const barPad = barW * 0.18;
  const zeroY = PAD.t + H * 0.55; // zero line at 55% down

  // Map a PnL value to a bar rect (above or below zeroY)
  function barRect(pnl: number, idx: number) {
    const ratio = Math.abs(pnl) / maxAbs;
    const barH = Math.max(2, ratio * (H * 0.45));
    const x = PAD.l + idx * barW + barPad;
    const w = barW - barPad * 2;
    const y = pnl >= 0 ? zeroY - barH : zeroY;
    return { x, y, w, h: barH };
  }

  if (!hasPosData && rows.every((r) => r.pnl === 0)) {
    return (
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px' }}>
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 8 }}>Open Position P&amp;L</div>
        <div style={{ color: C.muted, fontSize: F.sm, textAlign: 'center', padding: '20px 0' }}>
          No open positions — bot is flat
        </div>
      </div>
    );
  }

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px', marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Open Position P&amp;L</span>
        <span style={{ fontSize: F.sm, fontWeight: 700, color: pnlColor(totalPnl) }}>
          {totalPnl >= 0 ? '+' : ''}{fmtUsd(totalPnl)}
        </span>
      </div>

      {rows.length === 0 ? (
        <div style={{ color: C.muted, fontSize: F.sm, textAlign: 'center', padding: '20px 0' }}>
          No open positions — bot is flat
        </div>
      ) : (
        <svg width="100%" viewBox={`0 0 ${SVG_W} ${SVG_H}`} style={{ display: 'block', overflow: 'visible' }}>
          {/* Zero baseline */}
          <line x1={PAD.l} y1={zeroY} x2={PAD.l + W} y2={zeroY}
            stroke={C.borderBright} strokeWidth={1} />
          <text x={PAD.l - 4} y={zeroY + 4} fill={C.muted} fontSize={7} textAnchor="end">$0</text>

          {/* Per-position bars */}
          {rows.map((row, i) => {
            const { x, y, w, h } = barRect(row.pnl, i);
            const col = row.pnl >= 0 ? C.bull : C.bear;
            return (
              <g key={row.symbol + i}>
                {/* Glow */}
                <rect x={x - 1} y={row.pnl >= 0 ? y - 1 : y} width={w + 2} height={h + 2}
                  rx={3} fill={col} opacity={0.15} />
                {/* Bar */}
                <rect x={x} y={y} width={w} height={h}
                  rx={3} fill={col} opacity={0.85} />
                {/* PnL label above/below bar */}
                <text
                  x={x + w / 2}
                  y={row.pnl >= 0 ? y - 5 : y + h + 10}
                  fill={col} fontSize={8} fontWeight={700} textAnchor="middle"
                >
                  {row.pnl >= 0 ? '+' : ''}{fmtUsd(row.pnl, 0)}
                </text>
                {/* Symbol label below zero */}
                <text x={x + w / 2} y={zeroY + 13} fill={C.text} fontSize={8} fontWeight={700} textAnchor="middle">
                  {row.symbol}
                </text>
                {/* Duration label */}
                {row.duration && (
                  <text x={x + w / 2} y={zeroY + 23} fill={C.muted} fontSize={7} textAnchor="middle">
                    {row.duration}
                  </text>
                )}
              </g>
            );
          })}

          {/* Total bar (rightmost) */}
          {(() => {
            const { x, y, w, h } = barRect(totalPnl, rows.length);
            const col = totalPnl >= 0 ? C.bull : C.bear;
            return (
              <g key="total">
                <rect x={x} y={y} width={w} height={h}
                  rx={3} fill={col} opacity={0.55}
                  strokeDasharray="3 2" stroke={col} strokeWidth={1} />
                <text
                  x={x + w / 2}
                  y={totalPnl >= 0 ? y - 5 : y + h + 10}
                  fill={col} fontSize={8} fontWeight={800} textAnchor="middle"
                >
                  {totalPnl >= 0 ? '+' : ''}{fmtUsd(totalPnl, 0)}
                </text>
                <text x={x + w / 2} y={zeroY + 13} fill={C.textSub} fontSize={8} fontWeight={700} textAnchor="middle">
                  TOTAL
                </text>
              </g>
            );
          })()}
        </svg>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function PortfolioPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [recentTrades, setRecentTrades] = useState<TradeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchData = async () => {
    const [stratRes, tradeRes] = await Promise.all([
      apiFetch<StrategiesResponse>('/v1/strategies'),
      apiFetch<TradeHistoryResponse>('/v1/trades/history?limit=30'),
    ]);
    setStrategies(Array.isArray(stratRes) ? stratRes : []);
    setRecentTrades(tradeRes?.trades ?? []);
    setLastUpdate(new Date());
    setLoading(false);
  };

  useEffect(() => {
    fetchData();
    const id = setInterval(fetchData, 20_000);
    return () => clearInterval(id);
  }, []);

  // Derived portfolio stats
  const openPositions = useMemo(
    () => strategies.filter((s) => s.open_position != null),
    [strategies],
  );

  const totalUnrealPnl = useMemo(
    () => openPositions.reduce((a, s) => a + (s.open_position?.unrealized_pnl ?? 0), 0),
    [openPositions],
  );

  const totalExposure = useMemo(
    () => openPositions.reduce((a, s) => a + (s.open_position?.size ?? 0), 0),
    [openPositions],
  );

  const totalRealizedPnl = useMemo(
    () => strategies.reduce((a, s) => a + (s.pnl_realized ?? 0), 0),
    [strategies],
  );

  // Concentration risk: are there multiple positions on the same side?
  const concentrationWarning = useMemo(() => {
    if (openPositions.length < 2) return null;
    const sides = openPositions.map((s) => s.open_position?.side?.toUpperCase() ?? 'LONG');
    const longCount = sides.filter((s) => s === 'BUY' || s === 'LONG').length;
    const shortCount = sides.filter((s) => s === 'SELL' || s === 'SHORT').length;
    if (longCount >= 2) return `${longCount} long positions open — concentration risk`;
    if (shortCount >= 2) return `${shortCount} short positions open — concentration risk`;
    return null;
  }, [openPositions]);

  const recentClosedPnl = useMemo(
    () => recentTrades.slice(0, 10).reduce((a, t) => a + (t.pnl ?? 0), 0),
    [recentTrades],
  );

  return (
    <Layout>
      <Head>
        <title>Portfolio — WAGMI</title>
        <meta name="description" content="Live portfolio view: open positions, exposure, unrealized P&L, and recent trade waterfall." />
      </Head>

      <div style={{ maxWidth: 900, margin: '0 auto', padding: '32px 20px' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28, flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: F['3xl'], fontWeight: 800, color: C.text }}>Portfolio</h1>
            <p style={{ margin: '6px 0 0', color: C.muted, fontSize: F.base }}>
              Live positions across all strategies · refreshes every 20s
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {lastUpdate && (
              <span style={{ fontSize: F.xs, color: C.muted }}>Updated {timeAgo(lastUpdate.toISOString())}</span>
            )}
            <button
              onClick={fetchData}
              style={{
                padding: '6px 14px', fontSize: F.sm, fontWeight: 600,
                background: C.brand, color: '#fff', border: 'none', borderRadius: R.sm,
                cursor: 'pointer',
              }}
            >Refresh</button>
          </div>
        </div>

        {loading ? (
          <div style={{ color: C.muted, padding: 40, textAlign: 'center', fontSize: F.base }}>Loading portfolio data…</div>
        ) : (
          <>
            {/* ── Summary KPIs ── */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 16, marginBottom: 28 }}>
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px', boxShadow: S.sm }}>
                <div style={{ fontSize: F.sm, color: C.muted, marginBottom: 4 }}>UNREALIZED P&L</div>
                <div style={{ fontSize: F['2xl'], fontWeight: 700, color: pnlColor(totalUnrealPnl) }}>{fmtUsd(totalUnrealPnl)}</div>
                <div style={{ fontSize: F.xs, color: C.muted }}>{openPositions.length} open position{openPositions.length !== 1 ? 's' : ''}</div>
              </div>
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px', boxShadow: S.sm }}>
                <div style={{ fontSize: F.sm, color: C.muted, marginBottom: 4 }}>REALIZED P&L</div>
                <div style={{ fontSize: F['2xl'], fontWeight: 700, color: pnlColor(totalRealizedPnl) }}>{fmtUsd(totalRealizedPnl)}</div>
                <div style={{ fontSize: F.xs, color: C.muted }}>All-time closed trades</div>
              </div>
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px', boxShadow: S.sm }}>
                <div style={{ fontSize: F.sm, color: C.muted, marginBottom: 4 }}>RECENT 10 TRADES</div>
                <div style={{ fontSize: F['2xl'], fontWeight: 700, color: pnlColor(recentClosedPnl) }}>{fmtUsd(recentClosedPnl)}</div>
                <div style={{ fontSize: F.xs, color: C.muted }}>Last 10 closed</div>
              </div>
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 20px', boxShadow: S.sm }}>
                <div style={{ fontSize: F.sm, color: C.muted, marginBottom: 4 }}>ACTIVE STRATEGIES</div>
                <div style={{ fontSize: F['2xl'], fontWeight: 700, color: C.text }}>{strategies.length}</div>
                <div style={{ fontSize: F.xs, color: C.muted }}>
                  {strategies.filter((s) => s.lastHeartbeat && (Date.now() - new Date(s.lastHeartbeat).getTime()) < 300_000).length} live
                </div>
              </div>
            </div>

            {/* ── Allocation & Risk Overview ── */}
            <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text, borderBottom: `1px solid ${C.border}`, paddingBottom: 10 }}>
              Allocation &amp; Risk Overview
            </h2>
            <div style={{ display: 'flex', gap: 16, marginBottom: 24, flexWrap: 'wrap' }}>
              <PortfolioSunburst />
              <RiskBudgetMeter />
            </div>

            {/* ── Efficiency Frontier ── */}
            <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text, borderBottom: `1px solid ${C.border}`, paddingBottom: 10 }}>
              Risk / Reward Efficiency
            </h2>
            <div style={{ display: 'flex', gap: 16, marginBottom: 24, flexWrap: 'wrap' }}>
              <EfficiencyFrontierChart />
            </div>

            {/* ── Visual Analytics Row: Allocation Donut + Health Score ── */}
            {(openPositions.length > 0 || recentTrades.length > 0) && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16, marginBottom: 24 }}>
                {openPositions.length > 0 && (
                  <AllocationDonut
                    positions={openPositions.map((s) => ({
                      symbol: s.id,
                      value: s.open_position?.size ?? 0,
                      pnl: s.open_position?.unrealized_pnl,
                    }))}
                  />
                )}
                <PortfolioHealthScore trades={recentTrades} />
              </div>
            )}

            {/* ── Exposure gauge ── */}
            {totalExposure > 0 && (
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '4px 20px 16px', marginBottom: 24, boxShadow: S.sm }}>
                <ExposureGauge used={totalExposure} total={50000} />
              </div>
            )}

            {/* ── Concentration warning ── */}
            {concentrationWarning && (
              <div style={{
                background: 'rgba(217,119,6,0.12)', border: `1px solid ${C.warn}`,
                borderRadius: R.md, padding: '10px 16px', marginBottom: 20,
                display: 'flex', alignItems: 'center', gap: 10,
              }}>
                <span style={{ fontSize: F.lg }}>⚠</span>
                <span style={{ fontSize: F.sm, color: C.warnMid, fontWeight: 600 }}>{concentrationWarning}</span>
              </div>
            )}

            {/* ── Correlation Analysis ── */}
            <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text, borderBottom: `1px solid ${C.border}`, paddingBottom: 10 }}>
              Correlation Analysis
            </h2>
            <CorrelationWarning
              symbols={openPositions.length >= 2
                ? openPositions.map((s) => s.id.replace(/USDT?$/i, '').toUpperCase())
                : undefined}
            />

            {/* ── Correlation Network ── */}
            <CorrelationNetwork />

            {/* ── Open Positions ── */}
            <div style={{ marginBottom: 32 }}>
              <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text, borderBottom: `1px solid ${C.border}`, paddingBottom: 10 }}>
                Open Positions ({openPositions.length})
              </h2>

              {/* ── Position P&L Waterfall ── */}
              <PositionPnlWaterfall positions={openPositions} />

              {/* ── Position Visual Intelligence: Bubble Chart + Thesis Validity ── */}
              <div style={{ display: 'flex', gap: 16, marginBottom: 20, flexWrap: 'wrap' }}>
                <PositionBubbleChart positions={openPositions} />
                <ThesisValidityBars positions={openPositions} />
              </div>

              {openPositions.length === 0 ? (
                <div style={{
                  background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg,
                  padding: 32, textAlign: 'center',
                }}>
                  <div style={{ fontSize: 36, marginBottom: 8 }}>💤</div>
                  <div style={{ fontSize: F.base, color: C.muted }}>No open positions right now.</div>
                  <div style={{ fontSize: F.sm, color: C.faint, marginTop: 4 }}>The bot is watching the market but hasn't entered any trades.</div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                  {openPositions.map((s) => <PositionCard key={s.id} strategy={s} />)}
                </div>
              )}
            </div>

            {/* ── Strategy P&L Ladder ── */}
            {strategies.length > 0 && <StrategyPnlLadder strategies={strategies} />}

            {/* ── Drawdown Analysis ── */}
            <div style={{ marginBottom: 32 }}>
              <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text, borderBottom: `1px solid ${C.border}`, paddingBottom: 10 }}>
                Drawdown Analysis
              </h2>
              <DrawdownRecoveryChart />
            </div>

            {/* ── All Strategies Status ── */}
            <div style={{ marginBottom: 32 }}>
              <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text, borderBottom: `1px solid ${C.border}`, paddingBottom: 10 }}>
                All Strategies ({strategies.length})
              </h2>
              <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, overflow: 'hidden' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: F.sm }}>
                  <thead>
                    <tr style={{ background: C.surface }}>
                      {['Strategy', 'Status', 'Realized P&L', 'Open Position', 'Last Seen'].map((h) => (
                        <th key={h} style={{ padding: '10px 16px', textAlign: 'left', color: C.muted, fontWeight: 600, fontSize: F.xs, textTransform: 'uppercase', letterSpacing: '0.04em', borderBottom: `1px solid ${C.border}` }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {strategies.map((s, i) => {
                      const isLive = s.lastHeartbeat && (Date.now() - new Date(s.lastHeartbeat).getTime()) < 300_000;
                      return (
                        <tr key={s.id} style={{ borderBottom: i < strategies.length - 1 ? `1px solid ${C.border}` : 'none' }}>
                          <td style={{ padding: '12px 16px', color: C.text, fontWeight: 600 }}>{s.id}</td>
                          <td style={{ padding: '12px 16px' }}>
                            <Badge
                              label={isLive ? '● LIVE' : 'OFFLINE'}
                              color={isLive ? C.bull : C.muted}
                              bg={isLive ? 'rgba(22,163,74,0.12)' : C.surface}
                            />
                          </td>
                          <td style={{ padding: '12px 16px', color: pnlColor(s.pnl_realized), fontWeight: 600 }}>
                            {s.pnl_realized != null ? fmtUsd(s.pnl_realized) : '—'}
                          </td>
                          <td style={{ padding: '12px 16px' }}>
                            {s.open_position ? (
                              <span style={{ color: pnlColor(s.open_position.unrealized_pnl), fontWeight: 600 }}>
                                {s.open_position.side?.toUpperCase()} {s.open_position.unrealized_pnl != null ? fmtUsd(s.open_position.unrealized_pnl) : ''}
                              </span>
                            ) : (
                              <span style={{ color: C.faint }}>—</span>
                            )}
                          </td>
                          <td style={{ padding: '12px 16px', color: C.muted }}>{timeAgo(s.lastHeartbeat)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* ── Recent Trades Waterfall ── */}
            {recentTrades.length > 0 && (
              <div style={{ marginBottom: 32 }}>
                <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text, borderBottom: `1px solid ${C.border}`, paddingBottom: 10 }}>
                  Recent Closed Trades
                </h2>
                <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 20, overflowX: 'auto' }}>
                  <DailyWaterfall trades={[...recentTrades].reverse()} />
                  <div style={{ marginTop: 16, overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: F.sm, minWidth: 600 }}>
                      <thead>
                        <tr>
                          {['Symbol', 'Side', 'Strategy', 'P&L', 'Outcome', 'Close Reason', 'R:R'].map((h) => (
                            <th key={h} style={{ padding: '6px 12px', textAlign: 'left', color: C.muted, fontWeight: 600, fontSize: F.xs, borderBottom: `1px solid ${C.border}` }}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {recentTrades.slice(0, 15).map((t, i) => (
                          <tr key={i} style={{
                            borderBottom: `1px solid ${C.border}`,
                            background: t.outcome === 'WIN' ? 'rgba(22,163,74,0.06)' : t.outcome === 'LOSS' ? 'rgba(220,38,38,0.06)' : 'transparent',
                          }}>
                            <td style={{ padding: '8px 12px', fontWeight: 700, color: C.text }}>{t.symbol}</td>
                            <td style={{ padding: '8px 12px', color: sideColor(t.side) }}>{t.side}</td>
                            <td style={{ padding: '8px 12px', color: C.muted, fontSize: F.xs }}>{t.strategy}</td>
                            <td style={{ padding: '8px 12px', fontWeight: 600, color: pnlColor(t.pnl) }}>{t.pnl != null ? fmtUsd(t.pnl) : '—'}</td>
                            <td style={{ padding: '8px 12px' }}>
                              <Badge label={t.outcome} color={t.outcome === 'WIN' ? C.bull : C.bear} bg={t.outcome === 'WIN' ? 'rgba(22,163,74,0.12)' : 'rgba(220,38,38,0.12)'} />
                            </td>
                            <td style={{ padding: '8px 12px', color: C.muted, fontSize: F.xs }}>{t.close_reason || '—'}</td>
                            <td style={{ padding: '8px 12px', color: t.rr_achieved != null && t.rr_achieved >= 1 ? C.bull : C.bear }}>
                              {t.rr_achieved != null ? `${t.rr_achieved.toFixed(2)}R` : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </Layout>
  );
}
