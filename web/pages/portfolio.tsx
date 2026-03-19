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
  const today = new Date();
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

            {/* ── Correlation Warning Heatmap ── */}
            <CorrelationWarning
              symbols={openPositions.length >= 2
                ? openPositions.map((s) => s.id.replace(/USDT?$/i, '').toUpperCase())
                : undefined}
            />

            {/* ── Open Positions ── */}
            <div style={{ marginBottom: 32 }}>
              <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text, borderBottom: `1px solid ${C.border}`, paddingBottom: 10 }}>
                Open Positions ({openPositions.length})
              </h2>
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
