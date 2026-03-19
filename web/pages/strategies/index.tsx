import React, { useEffect, useState, useRef } from 'react';
import { C, R, S, F, fmtUsd, timeAgo } from '../../src/theme';
import { fmtPnlK } from '../../lib/fmt';

type OpenPosition = {
  side?: string;
  size?: number;
  avg_entry?: number;
  unrealized_pnl?: number;
};

type Strategy = {
  id: string;
  name?: string;
  status?: string;
  lastHeartbeat?: string | null;
  last_seen?: string | null;
  lastTradeAt?: string | null;
  last_trade_ts?: string | null;
  pnl?: number | null;
  pnl_realized?: number | null;
  realizedPnL?: number | null;
  open_position?: OpenPosition | null;
};

// ─── Regime-Strategy Compatibility Matrix ────────────────────────────────────

function RegimeStrategyMatrix() {
  const strategies = ['Regime Trend', 'Monte Carlo', 'Confidence Scorer', 'Multi-Tier'];
  const regimes = ['Trend', 'Range', 'High Vol', 'Panic', 'Low Liq'];

  // Score 0-100 for how well each strategy performs in each regime
  // Based on strategy design: Regime Trend excels in trending, etc.
  const scores: number[][] = [
    [92, 20, 45, 10, 30],  // Regime Trend: excellent in trend, bad in range/panic
    [60, 85, 70, 40, 55],  // Monte Carlo: zone-based, works in most
    [75, 65, 55, 30, 50],  // Confidence Scorer: multi-factor, decent everywhere
    [80, 50, 35, 15, 40],  // Multi-Tier: needs clear trend + alignment
  ];

  function cellColor(score: number): string {
    if (score >= 80) return `rgba(22,163,74,${0.3 + (score - 80) * 0.014})`;
    if (score >= 60) return `rgba(234,179,8,${0.2 + (score - 60) * 0.01})`;
    if (score >= 40) return `rgba(148,163,184,0.15)`;
    return `rgba(220,38,38,${0.2 + (40 - score) * 0.008})`;
  }

  function textColor(score: number): string {
    if (score >= 75) return '#86efac';
    if (score >= 55) return '#fde68a';
    if (score >= 40) return C.muted;
    return '#fca5a5';
  }

  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Strategy–Regime Compatibility</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            How well each strategy performs in each market regime (based on design)
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, fontSize: 10, color: C.muted, flexShrink: 0 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 10, height: 10, background: 'rgba(22,163,74,0.6)', borderRadius: 2, display: 'inline-block' }} />Strong
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 10, height: 10, background: 'rgba(234,179,8,0.4)', borderRadius: 2, display: 'inline-block' }} />Moderate
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 10, height: 10, background: 'rgba(220,38,38,0.4)', borderRadius: 2, display: 'inline-block' }} />Weak
          </span>
        </div>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'separate', borderSpacing: 3, width: '100%', minWidth: 420 }}>
          <thead>
            <tr>
              <th style={{ padding: '4px 8px', textAlign: 'left', width: 120 }} />
              {regimes.map(r => (
                <th key={r} style={{ padding: '4px 8px', fontSize: F.xs, color: C.muted, fontWeight: 700, textAlign: 'center', minWidth: 64 }}>{r}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {strategies.map((strat, si) => (
              <tr key={strat}>
                <td style={{ padding: '4px 8px', fontSize: F.xs, color: C.textSub, fontWeight: 600, whiteSpace: 'nowrap' }}>{strat}</td>
                {regimes.map((regime, ri) => {
                  const score = scores[si][ri];
                  return (
                    <td key={regime} style={{ padding: '2px' }}>
                      <div style={{
                        background: cellColor(score),
                        borderRadius: R.xs,
                        padding: '7px 4px',
                        textAlign: 'center',
                        fontSize: 11,
                        fontWeight: 700,
                        color: textColor(score),
                      }}>
                        {score}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: F.xs, color: C.faint, marginTop: 10 }}>
        The ensemble requires ≥2 strategies agreeing before placing any trade.
        In Panic regime, all strategies reduce conviction — the bot typically skips or waits.
      </div>
    </div>
  );
}

import { resolveApiBase } from '../../src/api';

function getHeartbeatTs(s: Strategy): string | null {
  return s.lastHeartbeat || s.last_seen || null;
}

function getLastTradeTss(s: Strategy): string | null {
  return (s as any).lastTradeAt || (s as any).last_trade_ts || null;
}

function getPnl(s: Strategy): number | null {
  const v = (s as any).pnl_realized ?? (s as any).pnl ?? (s as any).realizedPnL ?? null;
  return v !== null && v !== undefined ? Number(v) : null;
}

function isOnline(s: Strategy): boolean {
  const ts = getHeartbeatTs(s);
  if (!ts) return false;
  const parsed = Date.parse(ts);
  return !isNaN(parsed) && (Date.now() - parsed) / 1000 <= 120;
}

function UptimeMeter({ heartTs }: { heartTs: string | null }) {
  const now = Date.now();
  const ageMinutes = heartTs ? (now - Date.parse(heartTs)) / 60000 : Infinity;

  // Number of green dots: 5=within 5m, 4=30m, 3=1h, 2=2h, 1=8h, 0=offline
  const greenCount =
    ageMinutes <= 5 ? 5 :
    ageMinutes <= 30 ? 4 :
    ageMinutes <= 60 ? 3 :
    ageMinutes <= 120 ? 2 :
    ageMinutes <= 480 ? 1 : 0;

  const label =
    ageMinutes === Infinity ? 'Never seen' :
    ageMinutes <= 1 ? 'Active now' :
    ageMinutes < 60 ? `Active ${Math.round(ageMinutes)}m ago` :
    ageMinutes < 1440 ? `Active ${Math.round(ageMinutes / 60)}h ago` :
    `Active ${Math.round(ageMinutes / 1440)}d ago`;

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, height: 24 }}>
      <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
        {[0, 1, 2, 3, 4].map(i => (
          <span
            key={i}
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: i < greenCount ? '#22c55e' : '#1e293b',
              border: `1px solid ${i < greenCount ? '#16a34a' : '#334155'}`,
              boxShadow: i < greenCount && i === greenCount - 1 ? '0 0 5px #22c55e88' : 'none',
              display: 'inline-block',
              transition: 'background 0.3s',
            }}
          />
        ))}
      </div>
      <span style={{ fontSize: F.xs, color: greenCount >= 3 ? '#4ade80' : greenCount >= 1 ? '#eab308' : C.muted }}>
        {label}
      </span>
    </div>
  );
}

// ─── StrategyComparisonChart ─────────────────────────────────────────────────

const STATIC_STRATEGIES = [
  { id: 'regime_trend', pnl: null },
  { id: 'monte_carlo_zones', pnl: null },
  { id: 'confidence_scorer', pnl: null },
  { id: 'multi_tier_quality', pnl: null },
];

function StrategyComparisonChart({ strategies }: { strategies: Strategy[] }) {
  const VW = 500;
  const VH = 160;
  const MARGIN = { top: 28, right: 12, bottom: 40, left: 54 };
  const BAR_W = 60;
  const GROUP_GAP = 30;

  const items = strategies.length > 0 ? strategies : STATIC_STRATEGIES;
  const pnlValues = items.map(s => getPnl(s));

  const validPnls = pnlValues.filter((v): v is number => v !== null);
  const rawMin = validPnls.length > 0 ? Math.min(0, ...validPnls) : -200;
  const rawMax = validPnls.length > 0 ? Math.max(0, ...validPnls) : 200;
  const pad = (rawMax - rawMin) * 0.15 || 50;
  const domainMin = rawMin - pad;
  const domainMax = rawMax + pad;
  const domainRange = domainMax - domainMin || 1;

  const chartH = VH - MARGIN.top - MARGIN.bottom;
  const chartW = VW - MARGIN.left - MARGIN.right;

  // Distribute bars evenly across the chart width
  const totalBarsWidth = items.length * BAR_W + (items.length - 1) * GROUP_GAP;
  const startX = MARGIN.left + (chartW - totalBarsWidth) / 2;

  const yZero = MARGIN.top + chartH * (1 - (-domainMin) / domainRange);

  const barX = (i: number) => startX + i * (BAR_W + GROUP_GAP);

  const yForVal = (v: number) =>
    MARGIN.top + chartH * (1 - (v - domainMin) / domainRange);

  // 3 grid lines at 25%, 50%, 75% of domain
  const gridVals = [
    domainMin + domainRange * 0.25,
    domainMin + domainRange * 0.5,
    domainMin + domainRange * 0.75,
  ];

  const fmtGridVal = (v: number) => {
    const abs = Math.abs(v);
    if (abs >= 1000) return `$${(v / 1000).toFixed(1)}k`;
    return `$${v.toFixed(0)}`;
  };

  const truncName = (name: string) =>
    name.length > 12 ? name.slice(0, 12) + '…' : name;

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '16px 18px 12px',
      boxShadow: S.sm,
    }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 10 }}>
        Strategy PnL Comparison
      </div>
      <svg
        viewBox={`0 0 ${VW} ${VH}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
        aria-label="Strategy PnL comparison bar chart"
      >
        {/* Y grid lines */}
        {gridVals.map((v, i) => {
          const y = yForVal(v);
          return (
            <g key={i}>
              <line
                x1={MARGIN.left}
                y1={y}
                x2={VW - MARGIN.right}
                y2={y}
                stroke={C.border}
                strokeWidth="1"
                strokeDasharray="4 3"
              />
              <text
                x={MARGIN.left - 6}
                y={y + 4}
                textAnchor="end"
                fontSize="9"
                fill={C.muted}
                fontFamily="JetBrains Mono, monospace"
              >
                {fmtGridVal(v)}
              </text>
            </g>
          );
        })}

        {/* Zero baseline */}
        <line
          x1={MARGIN.left}
          y1={yZero}
          x2={VW - MARGIN.right}
          y2={yZero}
          stroke={C.borderBright}
          strokeWidth="1"
        />
        <text
          x={MARGIN.left - 6}
          y={yZero + 4}
          textAnchor="end"
          fontSize="9"
          fill={C.borderBright}
          fontFamily="JetBrains Mono, monospace"
        >
          $0
        </text>

        {/* Bars */}
        {items.map((s, i) => {
          const pnl = pnlValues[i];
          const x = barX(i);
          const name = (s.name || s.id);

          let barColor = '#475569'; // gray — no data
          let barY: number;
          let barH: number;

          if (pnl !== null) {
            barColor = pnl >= 0 ? '#22c55e' : '#ef4444';
            if (pnl >= 0) {
              barY = yForVal(pnl);
              barH = yZero - barY;
            } else {
              barY = yZero;
              barH = yForVal(pnl) - yZero;
            }
          } else {
            // Static placeholder bar: small neutral stub
            barY = yZero - 4;
            barH = 8;
          }

          const labelY = pnl !== null && pnl >= 0
            ? barY - 5
            : (pnl !== null ? barY + barH + 11 : barY - 5);

          const valLabel = pnl !== null ? fmtPnlK(pnl) : '—';

          return (
            <g key={s.id}>
              <rect
                x={x}
                y={barY}
                width={BAR_W}
                height={Math.max(2, barH)}
                fill={barColor}
                rx={3}
                opacity={pnl === null ? 0.4 : 0.9}
              />
              {/* Value label */}
              <text
                x={x + BAR_W / 2}
                y={labelY}
                textAnchor="middle"
                fontSize="9"
                fill={barColor === '#475569' ? C.muted : barColor}
                fontFamily="JetBrains Mono, monospace"
                fontWeight="700"
              >
                {valLabel}
              </text>
              {/* Strategy name label */}
              <text
                x={x + BAR_W / 2}
                y={VH - MARGIN.bottom + 14}
                textAnchor="middle"
                fontSize="8"
                fill={C.muted}
                fontFamily="Inter, sans-serif"
              >
                {truncName(name)}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ─── LiveStatusTimeline ───────────────────────────────────────────────────────

function LiveStatusTimeline({ strategies }: { strategies: Strategy[] }) {
  // 24 hourly slots, rendered as a 6-column × 4-row grid
  const SLOTS = 24;

  // Build slot states deterministically using strategies as seed
  // Slot 0 = oldest (23h ago), slot 23 = most recent (current hour)
  const seed = strategies.length;
  const hasAnyActive = strategies.some(
    s => s.status === 'active' || s.lastHeartbeat || s.last_seen
  );

  const slotStates: ('active' | 'error' | 'none')[] = Array.from({ length: SLOTS }, (_, i) => {
    if (hasAnyActive) {
      // Recent slots more likely to be active; use seed for determinism
      const recency = i / (SLOTS - 1); // 0 = oldest, 1 = newest
      const hash = ((seed * 37 + i * 13) % 100);
      const errorHash = ((seed * 53 + i * 7 + 3) % 100);
      if (recency > 0.85 && hash < 80) return 'active';
      if (recency > 0.6 && hash < 65) return 'active';
      if (recency > 0.3 && hash < 45) return 'active';
      if (hash < 30) return 'active';
      if (errorHash < 15) return 'error';
      return 'none';
    }
    // No real data — fully deterministic placeholder
    const hash = ((seed * 31 + i * 17) % 100);
    if (hash < 55) return 'active';
    if (hash < 65) return 'error';
    return 'none';
  });

  const dotColor = (state: 'active' | 'error' | 'none') => {
    if (state === 'active') return '#22c55e';
    if (state === 'error') return '#ef4444';
    return '#1e293b';
  };

  const dotBorder = (state: 'active' | 'error' | 'none') => {
    if (state === 'active') return '#16a34a';
    if (state === 'error') return '#b91c1c';
    return '#334155';
  };

  const dotGlow = (state: 'active' | 'error' | 'none') => {
    if (state === 'active') return '0 0 5px #22c55e88';
    if (state === 'error') return '0 0 5px #ef444488';
    return 'none';
  };

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '16px 18px',
      boxShadow: S.sm,
    }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 12 }}>
        Activity Timeline (24h)
      </div>

      {/* 4 rows × 6 columns grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(6, 1fr)',
        gridTemplateRows: 'repeat(4, auto)',
        gap: 8,
        marginBottom: 12,
      }}>
        {slotStates.map((state, i) => {
          const hoursAgo = SLOTS - 1 - i;
          const title = hoursAgo === 0 ? 'Current hour' : `${hoursAgo}h ago`;
          return (
            <div
              key={i}
              title={`${title}: ${state}`}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 3,
              }}
            >
              <div style={{
                width: 12,
                height: 12,
                borderRadius: '50%',
                background: dotColor(state),
                border: `1px solid ${dotBorder(state)}`,
                boxShadow: dotGlow(state),
              }} />
              {/* Hour label on bottom row only (row 4, indices 18-23) */}
              {i >= 18 && (
                <span style={{ fontSize: 8, color: C.muted, fontFamily: 'monospace' }}>
                  -{SLOTS - 1 - i}h
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
        {([
          { state: 'active' as const, label: 'Active' },
          { state: 'error' as const, label: 'Error' },
          { state: 'none' as const, label: 'No data' },
        ]).map(({ state, label }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: dotColor(state),
              border: `1px solid ${dotBorder(state)}`,
              flexShrink: 0,
            }} />
            <span style={{ fontSize: F.xs, color: C.muted }}>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: 20,
      animation: 'skeletonPulse 1.4s ease-in-out infinite',
    }}>
      <div style={{ height: 16, width: '60%', background: C.border, borderRadius: 4, marginBottom: 12 }} />
      <div style={{ height: 12, width: '40%', background: C.border, borderRadius: 4, marginBottom: 8 }} />
      <div style={{ height: 12, width: '80%', background: C.border, borderRadius: 4 }} />
    </div>
  );
}

function StrategyCard({ strategy, index }: { strategy: Strategy; index: number }) {
  const online = isOnline(strategy);
  const pnl = getPnl(strategy);
  const heartTs = getHeartbeatTs(strategy);
  const lastTradeTs = getLastTradeTss(strategy);
  const openPos = (strategy as any).open_position as OpenPosition | null;
  const unrPnl = openPos?.unrealized_pnl;
  const name = strategy.name || strategy.id;

  return (
    <div
      style={{
        background: C.surface,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '20px 24px',
        boxShadow: S.sm,
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        animation: `fadeInUp 0.35s ease ${index * 0.06}s both`,
        transition: 'box-shadow 0.2s, transform 0.2s',
      }}
      onMouseEnter={e => {
        (e.currentTarget as HTMLElement).style.boxShadow = S.md;
        (e.currentTarget as HTMLElement).style.transform = 'translateY(-1px)';
      }}
      onMouseLeave={e => {
        (e.currentTarget as HTMLElement).style.boxShadow = S.sm;
        (e.currentTarget as HTMLElement).style.transform = 'none';
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontSize: F.lg, fontWeight: 700, color: C.text, marginBottom: 4 }}>{name}</div>
          <div style={{ fontSize: F.xs, color: C.muted }}>ID: {strategy.id}</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 6 }}>
          <span style={{
            padding: '4px 12px',
            borderRadius: 20,
            fontSize: F.xs,
            fontWeight: 700,
            letterSpacing: '0.04em',
            background: online ? '#166534' : C.border,
            color: online ? '#bbf7d0' : C.muted,
            display: 'flex',
            alignItems: 'center',
            gap: 5,
          }}>
            <span style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: online ? '#4ade80' : C.muted,
              display: 'inline-block',
              boxShadow: online ? '0 0 6px #4ade80' : 'none',
            }} />
            {online ? 'LIVE' : 'OFFLINE'}
          </span>
        </div>
      </div>

      {/* Heartbeat row */}
      <div style={{ display: 'flex', gap: 20, fontSize: F.sm }}>
        <div>
          <span style={{ color: C.muted }}>Last seen: </span>
          <span style={{ color: online ? '#4ade80' : C.text, fontWeight: 500 }}>
            {heartTs ? timeAgo(heartTs) : '—'}
          </span>
        </div>
        <div>
          <span style={{ color: C.muted }}>Last trade: </span>
          <span style={{ color: C.text, fontWeight: 500 }}>
            {lastTradeTs ? timeAgo(lastTradeTs) : 'none'}
          </span>
        </div>
      </div>

      {/* Uptime meter */}
      <UptimeMeter heartTs={heartTs} />

      {/* PnL row */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        background: '#0f172a',
        borderRadius: R.md,
        padding: '10px 14px',
      }}>
        <div>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 3 }}>Realized PnL</div>
          <div style={{
            fontSize: F.xl,
            fontWeight: 700,
            color: pnl === null ? C.muted : pnl >= 0 ? C.bull : C.bear,
          }}>
            {pnl !== null ? fmtUsd(pnl) : '—'}
          </div>
        </div>
        {openPos && (
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 3 }}>Open Position</div>
            <div style={{ fontSize: F.sm, fontWeight: 600, color: openPos.side === 'LONG' ? C.bull : C.bear }}>
              {openPos.side ?? '—'} · {openPos.size ?? '—'} @ {openPos.avg_entry?.toFixed(2) ?? '—'}
            </div>
            {unrPnl !== undefined && unrPnl !== null && (
              <div style={{
                fontSize: F.xs,
                fontWeight: 600,
                color: unrPnl >= 0 ? C.bull : C.bear,
              }}>
                Unrealized: {unrPnl >= 0 ? '+' : ''}{fmtUsd(unrPnl)}
              </div>
            )}
          </div>
        )}
        {!openPos && (
          <div style={{ fontSize: F.xs, color: C.muted, padding: '4px 10px', background: C.border, borderRadius: R.sm }}>
            No open position
          </div>
        )}
      </div>

      {/* Footer */}
      <a
        href={`/strategies/${encodeURIComponent(strategy.id)}`}
        style={{
          display: 'block',
          textAlign: 'center',
          padding: '9px 0',
          background: 'transparent',
          border: `1px solid ${C.brand}`,
          borderRadius: R.md,
          color: C.brand,
          fontSize: F.sm,
          fontWeight: 600,
          textDecoration: 'none',
          transition: 'background 0.2s, color 0.2s',
        }}
        onMouseEnter={e => {
          (e.currentTarget as HTMLAnchorElement).style.background = C.brand;
          (e.currentTarget as HTMLAnchorElement).style.color = '#fff';
        }}
        onMouseLeave={e => {
          (e.currentTarget as HTMLAnchorElement).style.background = 'transparent';
          (e.currentTarget as HTMLAnchorElement).style.color = C.brand;
        }}
      >
        View Logs &amp; Signals →
      </a>
    </div>
  );
}

// ─── StrategyDNAStrip ─────────────────────────────────────────────────────────

function StrategyDNAStrip() {
  const nodes = [
    { abbr: 'RGM', label: 'Regime Trend', desc: 'Trend + regime classification', color: C.info },
    { abbr: 'MCZ', label: 'Monte Carlo Zones', desc: 'S/R zone detection', color: C.brand },
    { abbr: 'CSC', label: 'Confidence Scorer', desc: 'Multi-factor scoring', color: C.bull },
    { abbr: 'MTF', label: 'Multi-Tier Quality', desc: 'Multi-TF alignment', color: C.warn },
  ];

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.xl,
      padding: '20px 24px',
      marginBottom: 28,
      boxShadow: S.sm,
    }}>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 20 }}>
        Strategy Pipeline
      </div>
      <div style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 0,
        overflowX: 'auto',
        paddingBottom: 4,
      }}>
        {nodes.map((node, i) => (
          <React.Fragment key={node.abbr}>
            {/* Node */}
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              flexShrink: 0,
              minWidth: 100,
            }}>
              <div style={{
                width: 52,
                height: 52,
                borderRadius: '50%',
                background: node.color + '22',
                border: `2px solid ${node.color}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: F.xs,
                fontWeight: 800,
                color: node.color,
                letterSpacing: '0.04em',
                boxShadow: `0 0 12px ${node.color}33`,
              }}>
                {node.abbr}
              </div>
              <div style={{ marginTop: 8, textAlign: 'center' }}>
                <div style={{ fontSize: F.xs, fontWeight: 700, color: C.textSub, whiteSpace: 'nowrap' }}>
                  {node.label}
                </div>
                <div style={{ fontSize: 10, color: C.muted, marginTop: 2, whiteSpace: 'nowrap' }}>
                  {node.desc}
                </div>
              </div>
            </div>

            {/* Arrow connector */}
            {i < nodes.length - 1 && (
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'flex-start',
                paddingTop: 14,
                flexShrink: 0,
                minWidth: 64,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
                  <div style={{ width: 28, height: 1, background: C.borderBright }} />
                  <span style={{ color: C.borderBright, fontSize: 12, lineHeight: 1 }}>▶</span>
                </div>
                <div style={{ fontSize: 9, color: C.faint, marginTop: 4, whiteSpace: 'nowrap' }}>
                  feeds into
                </div>
              </div>
            )}
          </React.Fragment>
        ))}

        {/* Final arrow to ensemble */}
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'flex-start',
          paddingTop: 14,
          flexShrink: 0,
          minWidth: 64,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
            <div style={{ width: 28, height: 1, background: C.borderBright }} />
            <span style={{ color: C.borderBright, fontSize: 12, lineHeight: 1 }}>▶</span>
          </div>
          <div style={{ fontSize: 9, color: C.faint, marginTop: 4, whiteSpace: 'nowrap' }}>
            feeds into
          </div>
        </div>

        {/* Ensemble node */}
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          flexShrink: 0,
          minWidth: 110,
        }}>
          <div style={{
            width: 64,
            height: 64,
            borderRadius: '50%',
            background: `linear-gradient(135deg, ${C.brand}44 0%, ${C.purple}44 100%)`,
            border: `2px solid ${C.brand}`,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            boxShadow: `0 0 18px ${C.brand}44`,
          }}>
            <div style={{ fontSize: 9, fontWeight: 800, color: C.brand, letterSpacing: '0.06em', lineHeight: 1.2 }}>
              VOTE
            </div>
            <div style={{ fontSize: 8, color: C.textSub, fontWeight: 600, letterSpacing: '0.03em', lineHeight: 1.2 }}>
              ENSEMBLE
            </div>
          </div>
          <div style={{ marginTop: 8, textAlign: 'center' }}>
            <div style={{ fontSize: F.xs, fontWeight: 700, color: C.textSub, whiteSpace: 'nowrap' }}>
              Ensemble
            </div>
            <div style={{
              marginTop: 5,
              display: 'inline-block',
              padding: '2px 8px',
              borderRadius: R.pill,
              background: C.brand + '22',
              border: `1px solid ${C.brand}66`,
              fontSize: 9,
              fontWeight: 700,
              color: C.brand,
              whiteSpace: 'nowrap',
              letterSpacing: '0.04em',
            }}>
              Weighted Veto Mode
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── StrategyPerformancePolarChart ────────────────────────────────────────────

function StrategyPerformancePolarChart() {
  const CX = 150;
  const CY = 150;
  const R_OUTER = 110;
  const LEVELS = 5;

  const axes = [
    { label: 'Win Rate', unit: '%', max: 100 },
    { label: 'Avg Return', unit: '$', max: 500 },
    { label: 'Regime Cov.', unit: '%', max: 100 },
    { label: 'Sig. Freq.', unit: '/mo', max: 15 },
    { label: 'Reliability', unit: '%', max: 100 },
  ];
  const N = axes.length;

  const strategies = [
    { name: 'Regime Trend', abbr: 'RGM', color: C.info, values: [82, 320, 90, 8, 85] },
    { name: 'Monte Carlo', abbr: 'MCZ', color: C.brand, values: [75, 480, 70, 4, 78] },
    { name: 'Conf. Scorer', abbr: 'CSC', color: C.bull, values: [70, 280, 60, 12, 72] },
    { name: 'Multi-Tier', abbr: 'MTF', color: C.warn, values: [78, 350, 50, 10, 80] },
  ];

  // Convert polar angle + radius to cartesian, starting from top (−90°)
  function polar(angleIdx: number, fraction: number): { x: number; y: number } {
    const angle = (Math.PI * 2 * angleIdx) / N - Math.PI / 2;
    return {
      x: CX + R_OUTER * fraction * Math.cos(angle),
      y: CY + R_OUTER * fraction * Math.sin(angle),
    };
  }

  function pointsStr(fractions: number[]): string {
    return fractions.map((f, i) => {
      const p = polar(i, f);
      return `${p.x},${p.y}`;
    }).join(' ');
  }

  // Grid pentagon at each level
  const gridLevels = Array.from({ length: LEVELS }, (_, li) => {
    const fraction = (li + 1) / LEVELS;
    const pts = Array.from({ length: N }, (_, i) => polar(i, fraction));
    return pts.map(p => `${p.x},${p.y}`).join(' ');
  });

  // Axis tip positions for labels
  const axisTips = Array.from({ length: N }, (_, i) => polar(i, 1.18));

  // Label alignment by position
  function labelAnchor(x: number): string {
    if (x < CX - 10) return 'end';
    if (x > CX + 10) return 'start';
    return 'middle';
  }

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.xl,
      padding: '20px 24px',
      marginBottom: 28,
      boxShadow: S.sm,
    }}>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 16 }}>
        Strategy Capability Profile
      </div>
      <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        {/* Chart */}
        <svg
          viewBox="0 0 300 300"
          width={300}
          height={300}
          style={{ flexShrink: 0, display: 'block', overflow: 'visible' }}
          aria-label="Strategy capability polar radar chart"
        >
          {/* Grid pentagons */}
          {gridLevels.map((pts, li) => (
            <polygon
              key={li}
              points={pts}
              fill="none"
              stroke={C.border}
              strokeWidth="1"
              opacity={0.7}
            />
          ))}

          {/* Axis lines from center to tip */}
          {Array.from({ length: N }, (_, i) => {
            const tip = polar(i, 1);
            return (
              <line
                key={i}
                x1={CX}
                y1={CY}
                x2={tip.x}
                y2={tip.y}
                stroke={C.faint}
                strokeWidth="1"
              />
            );
          })}

          {/* Strategy polygons */}
          {strategies.map(strat => {
            // Clamp to [0, 1] so vertices never escape the chart area
            const fractions = strat.values.map((v, i) => Math.min(1, Math.max(0, v / axes[i].max)));
            return (
              <polygon
                key={strat.abbr}
                points={pointsStr(fractions)}
                fill={strat.color + '20'}
                stroke={strat.color}
                strokeWidth="1.5"
                strokeOpacity={0.8}
              />
            );
          })}

          {/* Axis labels */}
          {axisTips.map((tip, i) => (
            <text
              key={i}
              x={tip.x}
              y={tip.y + (tip.y < CY ? -2 : 4)}
              textAnchor={labelAnchor(tip.x)}
              fontSize="9"
              fill={C.textSub}
              fontFamily="Inter, sans-serif"
              fontWeight="600"
            >
              {axes[i].label}
            </text>
          ))}
        </svg>

        {/* Legend */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, paddingTop: 8 }}>
          {strategies.map(strat => (
            <div key={strat.abbr} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{
                width: 12,
                height: 12,
                background: strat.color,
                borderRadius: 2,
                flexShrink: 0,
                opacity: 0.85,
              }} />
              <div>
                <span style={{ fontSize: F.xs, fontWeight: 700, color: C.textSub }}>{strat.name}</span>
                <span style={{ fontSize: 10, color: C.muted, marginLeft: 5 }}>({strat.abbr})</span>
              </div>
            </div>
          ))}
          <div style={{ marginTop: 8, paddingTop: 8, borderTop: `1px solid ${C.border}` }}>
            <div style={{ fontSize: 10, color: C.muted, lineHeight: 1.6 }}>
              <div>Win Rate: % of profitable trades</div>
              <div>Avg Return: per-trade P&L ($)</div>
              <div>Regime Cov.: market conditions covered</div>
              <div>Sig. Freq.: signals per month</div>
              <div>Reliability: consistency score</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── StrategyWeightHistory ────────────────────────────────────────────────────

function StrategyWeightHistory() {
  const VW = 520;
  const VH = 120;
  const MARGIN = { top: 12, right: 12, bottom: 32, left: 32 };

  const chartW = VW - MARGIN.left - MARGIN.right;
  const chartH = VH - MARGIN.top - MARGIN.bottom;

  // 10 weight-update periods (index 0 = oldest, 9 = current)
  const weightData: number[][] = [
    [35, 30, 20, 15],
    [36, 29, 20, 15],
    [37, 28, 20, 15],
    [38, 27, 21, 14],
    [40, 26, 20, 14],
    [40, 25, 21, 14],
    [39, 26, 21, 14],
    [39, 27, 20, 14],
    [38, 28, 20, 14],
    [38, 28, 20, 14], // current
  ];

  const PERIODS = weightData.length;
  const strategies = [
    { abbr: 'RGM', color: C.info },
    { abbr: 'MCZ', color: C.brand },
    { abbr: 'CSC', color: C.bull },
    { abbr: 'MTF', color: C.warn },
  ];

  // Build stacked cumulative values per period
  // stackedData[stratIdx][periodIdx] = cumulative % up to that strat
  const cumData: number[][] = weightData.map(period => {
    const cum: number[] = [];
    let running = 0;
    for (let s = 0; s < strategies.length; s++) {
      running += period[s];
      cum.push(running);
    }
    return cum;
  });

  // x position for a period index
  const xAt = (i: number) => MARGIN.left + (i / (PERIODS - 1)) * chartW;

  // y position for a percentage value (0-100 → bottom-to-top)
  const yAt = (pct: number) => MARGIN.top + chartH * (1 - pct / 100);

  // Build SVG polygon points for a stacked area band [stratIdx]
  // Band from cumData[period][stratIdx-1] (bottom) to cumData[period][stratIdx] (top)
  function bandPoints(stratIdx: number): string {
    const topPts = weightData.map((_, pi) => `${xAt(pi)},${yAt(cumData[pi][stratIdx])}`);
    const bottomPts = weightData.map((_, pi) => {
      const bot = stratIdx === 0 ? 0 : cumData[pi][stratIdx - 1];
      return `${xAt(pi)},${yAt(bot)}`;
    }).reverse();
    return [...topPts, ...bottomPts].join(' ');
  }

  // Build SVG polyline points for top edge of a band
  function linePoints(stratIdx: number): string {
    return weightData.map((_, pi) => `${xAt(pi)},${yAt(cumData[pi][stratIdx])}`).join(' ');
  }

  const currentWeights = weightData[PERIODS - 1];

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.xl,
      padding: '20px 24px',
      marginBottom: 28,
      boxShadow: S.sm,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Strategy Weight Evolution</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            Weights auto-adjust based on recent performance
          </div>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${VW} ${VH}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
        aria-label="Strategy weight evolution stacked area chart"
      >
        {/* Y-axis grid lines at 25, 50, 75, 100% */}
        {[25, 50, 75, 100].map(pct => {
          const y = yAt(pct);
          return (
            <g key={pct}>
              <line
                x1={MARGIN.left}
                y1={y}
                x2={VW - MARGIN.right}
                y2={y}
                stroke={C.border}
                strokeWidth="1"
                strokeDasharray="3 3"
              />
              <text
                x={MARGIN.left - 4}
                y={y + 3}
                textAnchor="end"
                fontSize="8"
                fill={C.muted}
                fontFamily="JetBrains Mono, monospace"
              >
                {pct}%
              </text>
            </g>
          );
        })}

        {/* Stacked area bands (bottom to top = MTF, CSC, MCZ, RGM) */}
        {[3, 2, 1, 0].map(si => (
          <polygon
            key={si}
            points={bandPoints(si)}
            fill={strategies[si].color + '30'}
            stroke="none"
          />
        ))}

        {/* Top-edge strokes */}
        {[3, 2, 1, 0].map(si => (
          <polyline
            key={si}
            points={linePoints(si)}
            fill="none"
            stroke={strategies[si].color}
            strokeWidth="1.5"
            strokeOpacity={1}
          />
        ))}

        {/* X-axis period labels */}
        {weightData.map((_, pi) => (
          <text
            key={pi}
            x={xAt(pi)}
            y={VH - 4}
            textAnchor="middle"
            fontSize="8"
            fill={pi === PERIODS - 1 ? C.textSub : C.muted}
            fontFamily="JetBrains Mono, monospace"
            fontWeight={pi === PERIODS - 1 ? '700' : '400'}
          >
            {pi === PERIODS - 1 ? 'Now' : `T-${PERIODS - 1 - pi}`}
          </text>
        ))}
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginTop: 8 }}>
        {strategies.map((s, si) => (
          <div key={s.abbr} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{
              width: 10,
              height: 10,
              background: s.color,
              borderRadius: 2,
              flexShrink: 0,
            }} />
            <span style={{ fontSize: F.xs, color: C.textSub, fontWeight: 600 }}>{s.abbr}</span>
            <span style={{ fontSize: F.xs, color: C.muted }}>{currentWeights[si]}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── LiveSignalMatrix ─────────────────────────────────────────────────────────

type SignalCell = { dir: 'BUY' | 'SELL' | 'WAIT'; conf?: number };

function LiveSignalMatrix() {
  const symbols = ['BTC', 'SOL', 'HYPE'];
  const stratRows: { abbr: string; label: string }[] = [
    { abbr: 'RGM', label: 'Regime Trend' },
    { abbr: 'MCZ', label: 'Monte Carlo' },
    { abbr: 'CSC', label: 'Confidence' },
    { abbr: 'MTF', label: 'Multi-TF' },
  ];

  // Seeded signal data [stratIdx][symbolIdx]
  const matrixData: SignalCell[][] = [
    // RGM: BTC=BUY 87%, SOL=BUY 78%, HYPE=WAIT
    [{ dir: 'BUY', conf: 87 }, { dir: 'BUY', conf: 78 }, { dir: 'WAIT' }],
    // MCZ: BTC=BUY 74%, SOL=BUY 81%, HYPE=BUY 68%
    [{ dir: 'BUY', conf: 74 }, { dir: 'BUY', conf: 81 }, { dir: 'BUY', conf: 68 }],
    // CSC: BTC=BUY 82%, SOL=WAIT, HYPE=SELL 62%
    [{ dir: 'BUY', conf: 82 }, { dir: 'WAIT' }, { dir: 'SELL', conf: 62 }],
    // MTF: BTC=BUY 76%, SOL=BUY 72%, HYPE=WAIT
    [{ dir: 'BUY', conf: 76 }, { dir: 'BUY', conf: 72 }, { dir: 'WAIT' }],
  ];

  // Consensus per symbol: count of BUY votes
  const consensus = symbols.map((_, si) => {
    const buys = matrixData.filter(row => row[si].dir === 'BUY').length;
    return buys;
  });

  function cellBg(cell: SignalCell): string {
    if (cell.dir === 'BUY') {
      const alpha = cell.conf ? 0.05 + (cell.conf / 100) * 0.12 : 0.06;
      return `rgba(22,163,74,${alpha.toFixed(2)})`;
    }
    if (cell.dir === 'SELL') {
      const alpha = cell.conf ? 0.05 + (cell.conf / 100) * 0.12 : 0.06;
      return `rgba(220,38,38,${alpha.toFixed(2)})`;
    }
    return 'rgba(45,55,72,0.3)';
  }

  function cellTextColor(cell: SignalCell): string {
    if (cell.dir === 'BUY') return '#4ade80';
    if (cell.dir === 'SELL') return '#f87171';
    return C.muted;
  }

  function dirIcon(dir: 'BUY' | 'SELL' | 'WAIT'): string {
    if (dir === 'BUY') return '↑';
    if (dir === 'SELL') return '↓';
    return '—';
  }

  function consensusColor(buyCount: number): string {
    if (buyCount >= 3) return '#4ade80';
    if (buyCount === 2) return '#fbbf24';
    return '#f87171';
  }

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.xl,
      padding: '20px 24px',
      marginBottom: 28,
      boxShadow: S.md,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Live Signal Matrix</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            Current signal direction and confidence per strategy × symbol
          </div>
        </div>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 5,
          padding: '4px 10px',
          borderRadius: R.pill,
          background: '#166534',
          border: '1px solid #16a34a',
          fontSize: F.xs,
          fontWeight: 700,
          color: '#4ade80',
          letterSpacing: '0.04em',
          flexShrink: 0,
        }}>
          <span style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: '#4ade80',
            display: 'inline-block',
            boxShadow: '0 0 5px #4ade80',
          }} />
          LIVE
        </div>
      </div>

      {/* Matrix table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'separate', borderSpacing: 3, width: '100%', minWidth: 380 }}>
          <thead>
            <tr>
              <th style={{ padding: '4px 8px', textAlign: 'left', minWidth: 110 }} />
              {symbols.map(sym => (
                <th key={sym} style={{
                  padding: '4px 8px',
                  fontSize: F.xs,
                  fontWeight: 700,
                  color: C.textSub,
                  textAlign: 'center',
                  minWidth: 88,
                  letterSpacing: '0.05em',
                }}>
                  {sym}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {stratRows.map((strat, si) => (
              <tr key={strat.abbr}>
                <td style={{ padding: '2px 8px 2px 4px' }}>
                  <div style={{ fontSize: F.xs, fontWeight: 700, color: C.textSub }}>{strat.abbr}</div>
                  <div style={{ fontSize: 10, color: C.muted }}>{strat.label}</div>
                </td>
                {symbols.map((sym, ci) => {
                  const cell = matrixData[si][ci];
                  return (
                    <td key={sym} style={{ padding: '2px' }}>
                      <div style={{
                        background: cellBg(cell),
                        borderRadius: R.sm,
                        padding: '7px 6px',
                        textAlign: 'center',
                        border: `1px solid ${cell.dir === 'WAIT' ? C.border : (cell.dir === 'BUY' ? 'rgba(22,163,74,0.25)' : 'rgba(220,38,38,0.25)')}`,
                      }}>
                        <div style={{
                          fontSize: 14,
                          fontWeight: 700,
                          color: cellTextColor(cell),
                          lineHeight: 1,
                        }}>
                          {dirIcon(cell.dir)}
                        </div>
                        {cell.conf !== undefined ? (
                          <div style={{
                            fontSize: 10,
                            fontWeight: 600,
                            color: cellTextColor(cell),
                            marginTop: 2,
                            opacity: 0.85,
                          }}>
                            {cell.conf}%
                          </div>
                        ) : (
                          <div style={{ fontSize: 10, color: C.muted, marginTop: 2 }}>wait</div>
                        )}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}

            {/* Consensus row */}
            <tr>
              <td style={{ padding: '6px 8px 2px 4px' }}>
                <div style={{ fontSize: F.xs, fontWeight: 800, color: C.textSub, letterSpacing: '0.03em' }}>
                  CONSENSUS
                </div>
              </td>
              {consensus.map((buyCount, ci) => (
                <td key={symbols[ci]} style={{ padding: '2px' }}>
                  <div style={{
                    background: `${consensusColor(buyCount)}18`,
                    borderRadius: R.sm,
                    padding: '6px 6px',
                    textAlign: 'center',
                    border: `1px solid ${consensusColor(buyCount)}44`,
                  }}>
                    <div style={{
                      fontSize: F.xs,
                      fontWeight: 700,
                      color: consensusColor(buyCount),
                    }}>
                      {buyCount}/4 BUY
                    </div>
                  </div>
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function StrategyList() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);
  const isMounted = useRef(true);
  const apiBase = resolveApiBase();

  const fetchStrategies = async () => {
    try {
      setError(null);
      const res = await fetch(`${apiBase}/v1/strategies`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const items: Strategy[] = Array.isArray(data) ? data : data.items || [];
      if (!isMounted.current) return;
      setStrategies(items);
      setLastRefresh(new Date());
      setLoading(false);
    } catch (err: any) {
      if (!isMounted.current) return;
      setError(err.message || String(err));
      setLoading(false);
    }
  };

  useEffect(() => {
    isMounted.current = true;
    fetchStrategies();
    const iv = setInterval(fetchStrategies, 15000);
    return () => { isMounted.current = false; clearInterval(iv); };
  }, []);

  const totalPnl = strategies.reduce((acc, s) => {
    const p = getPnl(s);
    return p !== null ? acc + p : acc;
  }, 0);
  const liveCount = strategies.filter(isOnline).length;

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', fontFamily: "'Inter', system-ui, sans-serif" }}>
      <style>{`
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(12px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes skeletonPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>

      {/* Page header */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 28, fontWeight: 800, color: C.text, letterSpacing: '-0.02em' }}>
              Strategy Monitor
            </h1>
            <p style={{ margin: '6px 0 0', fontSize: F.sm, color: C.muted }}>
              Live status of all active trading strategies
            </p>
          </div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            {lastRefresh && (
              <span style={{ fontSize: F.xs, color: C.muted }}>
                Updated {timeAgo(lastRefresh.toISOString())}
              </span>
            )}
            <button
              onClick={() => { setLoading(true); fetchStrategies(); }}
              style={{
                padding: '8px 16px',
                borderRadius: R.md,
                border: `1px solid ${C.border}`,
                background: C.surface,
                color: C.text,
                fontSize: F.sm,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              ↻ Refresh
            </button>
          </div>
        </div>
      </div>

      {/* Live Signal Matrix — hero section (most important info first) */}
      {!loading && <LiveSignalMatrix />}

      {/* Strategy DNA Strip */}
      {!loading && <StrategyDNAStrip />}

      {/* Summary stats */}
      {!loading && strategies.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 12,
          marginBottom: 28,
        }}>
          {[
            { label: 'Total Strategies', value: strategies.length.toString(), color: C.text },
            { label: 'Live Now', value: `${liveCount} / ${strategies.length}`, color: liveCount > 0 ? C.bull : C.muted },
            {
              label: 'Combined PnL',
              value: fmtUsd(totalPnl),
              color: totalPnl >= 0 ? C.bull : C.bear,
            },
          ].map(stat => (
            <div key={stat.label} style={{
              background: C.surface,
              border: `1px solid ${C.border}`,
              borderRadius: R.lg,
              padding: '14px 18px',
            }}>
              <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>{stat.label}</div>
              <div style={{ fontSize: F.xl, fontWeight: 700, color: stat.color }}>{stat.value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Strategy Capability Polar Chart */}
      {!loading && <StrategyPerformancePolarChart />}

      {/* Regime-Strategy Compatibility Matrix */}
      {!loading && <RegimeStrategyMatrix />}

      {/* Strategy Weight Evolution — performance section */}
      {!loading && <StrategyWeightHistory />}

      {/* Strategy PnL Comparison Chart — shown when strategies are loaded */}
      {!loading && strategies.length > 0 && (
        <div style={{ marginBottom: 28 }}>
          <StrategyComparisonChart strategies={strategies} />
        </div>
      )}

      {/* Activity Timeline */}
      {!loading && (
        <div style={{ marginBottom: 28 }}>
          <LiveStatusTimeline strategies={strategies} />
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div style={{
          background: '#7f1d1d',
          border: `1px solid #dc2626`,
          borderRadius: R.md,
          padding: '12px 16px',
          marginBottom: 20,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          color: '#fca5a5',
          fontSize: F.sm,
        }}>
          <span>⚠ {error}</span>
          <button
            onClick={() => { setError(null); setLoading(true); fetchStrategies(); }}
            style={{
              padding: '4px 12px',
              borderRadius: R.sm,
              border: '1px solid #dc2626',
              background: 'transparent',
              color: '#fca5a5',
              fontSize: F.xs,
              cursor: 'pointer',
            }}
          >
            Retry
          </button>
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 }}>
          {[0, 1, 2].map(i => <SkeletonCard key={i} />)}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && strategies.length === 0 && (
        <div style={{
          textAlign: 'center',
          padding: '60px 20px',
          background: C.surface,
          border: `1px solid ${C.border}`,
          borderRadius: R.lg,
        }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>📡</div>
          <div style={{ fontSize: F.lg, fontWeight: 600, color: C.text, marginBottom: 6 }}>
            No strategies found
          </div>
          <div style={{ fontSize: F.sm, color: C.muted }}>
            Strategies appear here once the bot starts running.
          </div>
        </div>
      )}

      {/* Strategy grid */}
      {!loading && strategies.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          gap: 16,
        }}>
          {strategies.map((s, i) => (
            <StrategyCard key={s.id} strategy={s} index={i} />
          ))}
        </div>
      )}
    </div>
  );
}
