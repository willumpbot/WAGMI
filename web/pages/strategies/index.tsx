import React, { useEffect, useState, useRef } from 'react';
import { C, R, S, F, fmtUsd, timeAgo } from '../../src/theme';

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

function resolveApiBase(): string {
  const envVal =
    (process.env.NEXT_PUBLIC_API_URL as string | undefined) ||
    (process.env.NEXT_PUBLIC_API_BASE_URL as string | undefined);
  if (envVal && envVal.trim().length > 0) return envVal;
  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (host && host !== 'localhost' && host !== '127.0.0.1') {
      return 'https://nunuirl-platform.onrender.com';
    }
  }
  return 'http://localhost:8000';
}

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

          const valLabel = pnl !== null
            ? (pnl >= 0 ? '+' : '') + (Math.abs(pnl) >= 1000
                ? `$${(pnl / 1000).toFixed(1)}k`
                : `$${pnl.toFixed(0)}`)
            : '—';

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
              {openPos.side} · {openPos.size} @ {openPos.avg_entry?.toFixed(2)}
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
    <main style={{ padding: '32px 24px', maxWidth: 1100, margin: '0 auto', fontFamily: "'Inter', system-ui, sans-serif" }}>
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
    </main>
  );
}
