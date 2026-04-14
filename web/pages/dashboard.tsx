import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { C, fmtUsd, fmtPct, timeAgo } from '../src/theme';
import { apiFetch } from '../src/api';
import type {
  TradeHistoryResponse,
  TradeRecord,
  EquityCurveResponse,
  EquityCurvePoint,
  LlmMarketView,
  Strategy,
} from '../src/types';

// ─── Types ────────────────────────────────────────────────────────────────────

type TimeRange = '7D' | '30D' | '90D' | 'ALL';

type DashStats = {
  equity: number | null;
  dailyPnl: number | null;
  winRate: number | null;
  openPositions: number;
  totalTrades: number;
  totalPnl: number | null;
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function filterByRange(points: EquityCurvePoint[], range: TimeRange): EquityCurvePoint[] {
  if (range === 'ALL' || !points.length) return points;
  const days = range === '7D' ? 7 : range === '30D' ? 30 : 90;
  const cutoff = Date.now() - days * 86400 * 1000;
  return points.filter((p) => new Date(p.ts).getTime() >= cutoff);
}

function calcSharpe(pts: EquityCurvePoint[]): number | null {
  if (pts.length < 5) return null;
  const returns = pts.slice(1).map((p, i) => (p.equity - pts[i].equity) / (pts[i].equity || 1));
  const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
  const variance = returns.reduce((a, b) => a + (b - mean) ** 2, 0) / returns.length;
  const std = Math.sqrt(variance);
  if (std === 0) return null;
  return (mean / std) * Math.sqrt(365);
}

function calcMaxDD(pts: EquityCurvePoint[]): number {
  let peak = pts[0]?.equity ?? 0;
  let maxDD = 0;
  for (const p of pts) {
    if (p.equity > peak) peak = p.equity;
    const dd = peak > 0 ? ((peak - p.equity) / peak) * 100 : 0;
    if (dd > maxDD) maxDD = dd;
  }
  return maxDD;
}

// ─── Metric Card ─────────────────────────────────────────────────────────────

function MetricCard({
  label,
  value,
  sub,
  color,
  icon,
}: {
  label: string;
  value: string;
  sub?: string;
  color?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div
      style={{
        flex: '1 1 160px',
        padding: '18px 20px',
        background: '#0d0d14',
        border: '1px solid rgba(255,255,255,0.06)',
        borderRadius: 12,
        minWidth: 140,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: C.muted, textTransform: 'uppercase', letterSpacing: 1 }}>
          {label}
        </div>
        {icon && <div style={{ color: C.muted }}>{icon}</div>}
      </div>
      <div
        style={{
          fontSize: 24,
          fontWeight: 800,
          color: color || C.text,
          fontFamily: 'JetBrains Mono, monospace',
          letterSpacing: -0.5,
          lineHeight: 1.15,
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 11, color: C.muted, marginTop: 4, fontWeight: 500 }}>{sub}</div>
      )}
    </div>
  );
}

// ─── Equity Chart SVG ─────────────────────────────────────────────────────────

function EquityChart({ points }: { points: EquityCurvePoint[] }) {
  if (points.length < 2) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: C.muted, fontSize: 13 }}>
      No equity data
    </div>
  );

  const values = points.map((p) => p.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const w = 1000;
  const h = 160;
  const padX = 0;
  const padY = 8;

  const pts = values.map((v, i) => {
    const x = padX + (i / (values.length - 1)) * (w - padX * 2);
    const y = padY + ((max - v) / range) * (h - padY * 2);
    return [x, y] as [number, number];
  });

  const pathD = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const fillD = pathD + ` L${pts[pts.length - 1][0].toFixed(1)},${h} L${pts[0][0].toFixed(1)},${h} Z`;
  const isPositive = values[values.length - 1] >= values[0];
  const lineColor = isPositive ? C.bull : C.bear;

  // Y axis labels
  const yLabels = [max, (max + min) / 2, min];

  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ width: '100%', height: '100%' }}>
      <defs>
        <linearGradient id="dashEcGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lineColor} stopOpacity="0.18" />
          <stop offset="100%" stopColor={lineColor} stopOpacity="0.01" />
        </linearGradient>
      </defs>
      <path d={fillD} fill="url(#dashEcGrad)" />
      <path d={pathD} fill="none" stroke={lineColor} strokeWidth="1.5" strokeLinejoin="round" />
      {/* Current value dot */}
      <circle
        cx={pts[pts.length - 1][0]}
        cy={pts[pts.length - 1][1]}
        r="3"
        fill={lineColor}
      />
    </svg>
  );
}

// ─── Open Position Row ────────────────────────────────────────────────────────

function PositionRow({ strategy }: { strategy: Strategy }) {
  const pos = strategy.open_position;
  if (!pos) return null;
  const upnl = pos.unrealized_pnl ?? 0;
  const isLong = pos.side?.toUpperCase() === 'BUY' || pos.side?.toUpperCase() === 'LONG';

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '100px 60px 80px 90px 90px 80px',
        gap: 8,
        padding: '10px 16px',
        borderBottom: '1px solid rgba(255,255,255,0.03)',
        alignItems: 'center',
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 700, color: C.text, fontFamily: 'JetBrains Mono, monospace' }}>
        {strategy.id}
      </div>
      <div>
        <span
          style={{
            fontSize: 11,
            fontWeight: 700,
            padding: '2px 7px',
            borderRadius: 999,
            background: isLong ? C.bullLight : C.bearLight,
            color: isLong ? C.bull : C.bear,
          }}
        >
          {pos.side?.toUpperCase()}
        </span>
      </div>
      <div style={{ fontSize: 12, color: C.textSub, fontFamily: 'JetBrains Mono, monospace' }}>
        {pos.size != null ? pos.size.toFixed(4) : '—'}
      </div>
      <div style={{ fontSize: 12, color: C.textSub, fontFamily: 'JetBrains Mono, monospace' }}>
        {pos.avg_entry != null ? fmtUsd(pos.avg_entry) : '—'}
      </div>
      <div
        style={{
          fontSize: 13,
          fontWeight: 700,
          color: upnl >= 0 ? C.bull : C.bear,
          fontFamily: 'JetBrains Mono, monospace',
        }}
      >
        {fmtUsd(upnl)}
      </div>
      <div
        style={{
          fontSize: 12,
          color: C.muted,
          fontFamily: 'JetBrains Mono, monospace',
        }}
      >
        {pos.unrealized_pnl_pct != null ? fmtPct(pos.unrealized_pnl_pct) : '—'}
      </div>
    </div>
  );
}

// ─── Trade Row ────────────────────────────────────────────────────────────────

function TradeRow({ trade }: { trade: TradeRecord }) {
  const isWin = trade.outcome === 'WIN' || (trade.pnl ?? 0) > 0;

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '80px 56px 110px 80px 70px 60px',
        gap: 8,
        padding: '9px 16px',
        borderBottom: '1px solid rgba(255,255,255,0.03)',
        alignItems: 'center',
      }}
    >
      <div style={{ fontSize: 13, fontWeight: 600, color: C.text, fontFamily: 'JetBrains Mono, monospace' }}>
        {trade.symbol}
      </div>
      <div>
        <span style={{ fontSize: 11, fontWeight: 700, padding: '2px 7px', borderRadius: 999, background: trade.side === 'BUY' ? C.bullLight : C.bearLight, color: trade.side === 'BUY' ? C.bull : C.bear }}>
          {trade.side}
        </span>
      </div>
      <div style={{ fontSize: 12, color: C.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {trade.strategy}
      </div>
      <div style={{ fontSize: 13, fontWeight: 700, color: isWin ? C.bull : C.bear, textAlign: 'right', fontFamily: 'JetBrains Mono, monospace' }}>
        {fmtUsd(trade.pnl ?? 0)}
      </div>
      <div style={{ fontSize: 11, fontWeight: 700, padding: '2px 7px', borderRadius: 999, background: isWin ? C.bullLight : C.bearLight, color: isWin ? C.bull : C.bear, textAlign: 'center' }}>
        {trade.outcome}
      </div>
      <div style={{ fontSize: 11, color: C.muted, textAlign: 'right', fontFamily: 'JetBrains Mono, monospace' }}>
        {trade.duration_h != null ? `${trade.duration_h.toFixed(1)}h` : '—'}
      </div>
    </div>
  );
}

// ─── Strategy Card ────────────────────────────────────────────────────────────

function StrategyCard({ s }: { s: Strategy }) {
  const pnl = s.pnl_realized ?? 0;
  const hasPos = !!s.open_position;

  return (
    <div
      style={{
        padding: '16px',
        background: '#0d0d14',
        border: '1px solid rgba(255,255,255,0.06)',
        borderRadius: 10,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: C.text }}>{s.name || s.id}</span>
        {hasPos && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: '2px 7px',
              borderRadius: 999,
              background: C.bullLight,
              color: C.bull,
            }}
          >
            OPEN
          </span>
        )}
      </div>
      <div style={{ fontSize: 20, fontWeight: 800, color: pnl >= 0 ? C.bull : C.bear, fontFamily: 'JetBrains Mono, monospace', letterSpacing: -0.5 }}>
        {fmtUsd(pnl)}
      </div>
      {s.lastHeartbeat && (
        <div style={{ fontSize: 11, color: C.muted }}>
          Last active: {timeAgo(s.lastHeartbeat)}
        </div>
      )}
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [range, setRange] = useState<TimeRange>('30D');
  const [allPoints, setAllPoints] = useState<EquityCurvePoint[]>([]);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [marketView, setMarketView] = useState<LlmMarketView | null>(null);
  const [stats, setStats] = useState<DashStats>({
    equity: null, dailyPnl: null, winRate: null, openPositions: 0, totalTrades: 0, totalPnl: null,
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      const [tradeRes, equityRes, stratRes, marketRes] = await Promise.all([
        apiFetch<TradeHistoryResponse>('/v1/trades/history?limit=20'),
        apiFetch<EquityCurveResponse>('/v1/trades/equity-curve?run=latest'),
        apiFetch<Strategy[]>('/v1/strategies'),
        apiFetch<LlmMarketView>('/v1/llm/market-view'),
      ]);

      if (equityRes?.points) setAllPoints(equityRes.points);
      if (tradeRes?.trades) setTrades(tradeRes.trades);
      if (marketRes) setMarketView(marketRes);

      const strats = Array.isArray(stratRes) ? stratRes : [];
      setStrategies(strats);

      // Compute stats
      const pts = equityRes?.points ?? [];
      const ts = tradeRes?.trades ?? [];
      const openPos = strats.filter((s) => s.open_position).length;

      let dailyPnl: number | null = null;
      if (pts.length > 1) {
        const now = pts[pts.length - 1].equity;
        const cutoff = Date.now() - 86400 * 1000;
        const yesterdayPt = [...pts].reverse().find((p) => new Date(p.ts).getTime() <= cutoff);
        if (yesterdayPt) dailyPnl = now - yesterdayPt.equity;
      }

      const wins = ts.filter((t) => t.outcome === 'WIN' || (t.pnl ?? 0) > 0);
      const totalPnl = ts.reduce((a, b) => a + (b.pnl ?? 0), 0);
      const winRate = ts.length > 0 ? (wins.length / ts.length) * 100 : null;

      setStats({
        equity: pts[pts.length - 1]?.equity ?? null,
        dailyPnl,
        winRate,
        openPositions: openPos,
        totalTrades: ts.length,
        totalPnl,
      });
      setLoading(false);
    }

    load();
    const iv = setInterval(load, 30_000);
    return () => clearInterval(iv);
  }, []);

  const visiblePoints = filterByRange(allPoints, range);
  const openPositionStrategies = strategies.filter((s) => s.open_position);
  const sharpe = calcSharpe(allPoints);
  const maxDD = allPoints.length > 1 ? calcMaxDD(allPoints) : null;

  const regimeLookup: Record<string, { bg: string; text: string }> = {
    trend: { bg: 'rgba(0,204,136,0.12)', text: '#00cc88' },
    range: { bg: 'rgba(68,136,255,0.12)', text: '#4488ff' },
    panic: { bg: 'rgba(255,68,102,0.12)', text: '#ff4466' },
    high_volatility: { bg: 'rgba(255,170,0,0.12)', text: '#ffaa00' },
    low_liquidity: { bg: 'rgba(107,107,123,0.12)', text: '#a0a0b8' },
  };
  const regimeStyle = marketView?.regime ? regimeLookup[marketView.regime] : null;

  return (
    <>
      <Head>
        <title>Dashboard — CrazyOnSol</title>
      </Head>

      <div style={{ paddingBottom: 60 }}>
        {/* ── Top bar ────────────────────────────────────────── */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: 24,
            flexWrap: 'wrap',
            gap: 12,
          }}
        >
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 800, color: C.text, margin: 0, letterSpacing: -0.5 }}>
              Dashboard
            </h1>
            <p style={{ fontSize: 13, color: C.muted, margin: '4px 0 0' }}>
              Live trading overview · updates every 30s
            </p>
          </div>

          {/* Status pills */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            {/* Live dot */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 10px', background: 'rgba(0,204,136,0.08)', border: '1px solid rgba(0,204,136,0.15)', borderRadius: 999 }}>
              <div className="live-dot" style={{ width: 6, height: 6, borderRadius: '50%', background: C.bull }} />
              <span style={{ fontSize: 11, fontWeight: 700, color: C.bull }}>LIVE</span>
            </div>
            {/* Regime */}
            {marketView?.regime && regimeStyle && (
              <div style={{ padding: '5px 10px', background: regimeStyle.bg, border: `1px solid ${regimeStyle.text}30`, borderRadius: 999 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: regimeStyle.text, textTransform: 'capitalize' }}>
                  {marketView.regime.replace(/_/g, ' ')}
                </span>
              </div>
            )}
            {/* Open positions */}
            {stats.openPositions > 0 && (
              <div style={{ padding: '5px 10px', background: 'rgba(68,136,255,0.08)', border: '1px solid rgba(68,136,255,0.2)', borderRadius: 999 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: C.info }}>
                  {stats.openPositions} OPEN
                </span>
              </div>
            )}
          </div>
        </div>

        {/* ── Metric Cards ───────────────────────────────────── */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 }} className="stagger-reveal">
          <MetricCard
            label="Portfolio Value"
            value={loading ? '—' : fmtUsd(stats.equity)}
            sub="Current equity"
            color={C.text}
          />
          <MetricCard
            label="24h P&L"
            value={loading || stats.dailyPnl == null ? '—' : fmtUsd(stats.dailyPnl)}
            sub="vs yesterday"
            color={stats.dailyPnl == null ? C.text : stats.dailyPnl >= 0 ? C.bull : C.bear}
          />
          <MetricCard
            label="Win Rate"
            value={loading || stats.winRate == null ? '—' : fmtPct(stats.winRate)}
            sub={`${stats.totalTrades} trades`}
            color={stats.winRate == null ? C.text : stats.winRate >= 55 ? C.bull : stats.winRate >= 45 ? C.warn : C.bear}
          />
          <MetricCard
            label="Open Positions"
            value={loading ? '—' : String(stats.openPositions)}
            sub="Active strategies"
            color={stats.openPositions > 0 ? C.info : C.muted}
          />
          <MetricCard
            label="Sharpe"
            value={loading || sharpe == null ? '—' : sharpe.toFixed(2)}
            sub="Annualized"
            color={sharpe == null ? C.text : sharpe >= 1.5 ? C.bull : sharpe >= 0.5 ? C.warn : C.bear}
          />
          <MetricCard
            label="Max Drawdown"
            value={loading || maxDD == null ? '—' : `-${maxDD.toFixed(1)}%`}
            sub="From peak"
            color={maxDD == null ? C.text : maxDD <= 10 ? C.bull : maxDD <= 20 ? C.warn : C.bear}
          />
        </div>

        {/* ── Equity Curve ───────────────────────────────────── */}
        <div
          style={{
            background: '#0d0d14',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: 12,
            marginBottom: 24,
            overflow: 'hidden',
          }}
        >
          <div style={{ padding: '14px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>Equity Curve</div>
              {visiblePoints.length > 0 && (
                <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>
                  {fmtUsd(visiblePoints[0]?.equity)} → {fmtUsd(visiblePoints[visiblePoints.length - 1]?.equity)}
                  {' '}
                  <span style={{ color: (visiblePoints[visiblePoints.length - 1]?.equity ?? 0) >= (visiblePoints[0]?.equity ?? 0) ? C.bull : C.bear }}>
                    ({fmtPct(visiblePoints.length > 1 ? ((visiblePoints[visiblePoints.length - 1].equity - visiblePoints[0].equity) / visiblePoints[0].equity) * 100 : 0)})
                  </span>
                </div>
              )}
            </div>

            {/* Time range toggles */}
            <div style={{ display: 'flex', gap: 4 }}>
              {(['7D', '30D', '90D', 'ALL'] as TimeRange[]).map((r) => (
                <button
                  key={r}
                  onClick={() => setRange(r)}
                  style={{
                    padding: '4px 10px',
                    borderRadius: 6,
                    border: '1px solid',
                    borderColor: range === r ? C.brand : 'rgba(255,255,255,0.08)',
                    background: range === r ? C.brandMuted : 'transparent',
                    color: range === r ? C.brand : C.muted,
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>

          <div style={{ height: 200, padding: '12px 16px 8px' }}>
            {loading ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: C.muted, fontSize: 13 }}>Loading...</div>
            ) : (
              <EquityChart points={visiblePoints} />
            )}
          </div>
        </div>

        {/* ── Open Positions + AI Brain ──────────────────────── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0,1.6fr) minmax(0,1fr)', gap: 16, marginBottom: 24 }}>

          {/* Open Positions */}
          <div
            style={{
              background: '#0d0d14',
              border: '1px solid rgba(255,255,255,0.06)',
              borderRadius: 12,
              overflow: 'hidden',
            }}
          >
            <div style={{ padding: '14px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>Open Positions</div>
              <Link href="/portfolio" style={{ fontSize: 12, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>
                Full view →
              </Link>
            </div>

            {openPositionStrategies.length === 0 ? (
              <div style={{ padding: '24px 20px', color: C.muted, fontSize: 13, textAlign: 'center' }}>
                No open positions
              </div>
            ) : (
              <>
                {/* Table header */}
                <div style={{ display: 'grid', gridTemplateColumns: '100px 60px 80px 90px 90px 80px', gap: 8, padding: '8px 16px' }}>
                  {['Symbol', 'Side', 'Size', 'Entry', 'Unr. P&L', 'P&L %'].map((h) => (
                    <div key={h} style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.8 }}>{h}</div>
                  ))}
                </div>
                {openPositionStrategies.map((s) => (
                  <PositionRow key={s.id} strategy={s} />
                ))}
              </>
            )}
          </div>

          {/* AI Brain */}
          <div
            style={{
              background: '#0d0d14',
              border: '1px solid rgba(255,255,255,0.06)',
              borderRadius: 12,
              overflow: 'hidden',
            }}
          >
            <div style={{ padding: '14px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>AI Brain</div>
              <Link href="/agent-intelligence" style={{ fontSize: 12, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>
                Details →
              </Link>
            </div>

            <div style={{ padding: '16px 20px' }}>
              {loading || !marketView ? (
                <div style={{ color: C.muted, fontSize: 13 }}>Loading...</div>
              ) : !marketView.has_data ? (
                <div style={{ color: C.muted, fontSize: 13 }}>No brain data yet.</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  {/* Regime + Bias row */}
                  <div style={{ display: 'flex', gap: 8 }}>
                    <div style={{ flex: 1, padding: '10px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 8 }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>Regime</div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: regimeStyle?.text || C.text, textTransform: 'capitalize' }}>
                        {marketView.regime?.replace(/_/g, ' ') || '—'}
                      </div>
                    </div>
                    <div style={{ flex: 1, padding: '10px 12px', background: 'rgba(255,255,255,0.03)', borderRadius: 8 }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>Bias</div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: marketView.overall_bias === 'bullish' ? C.bull : marketView.overall_bias === 'bearish' ? C.bear : C.warn, textTransform: 'capitalize' }}>
                        {marketView.overall_bias || '—'}
                      </div>
                    </div>
                  </div>

                  {/* Decision counts */}
                  <div>
                    <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Decision Split</div>
                    <div style={{ display: 'flex', gap: 6 }}>
                      {[
                        { label: 'Proceed', value: marketView.decision_counts?.proceed ?? 0, color: C.bull },
                        { label: 'Skip', value: marketView.decision_counts?.flat ?? 0, color: C.muted },
                        { label: 'Flip', value: marketView.decision_counts?.flip ?? 0, color: C.warn },
                      ].map((d) => (
                        <div key={d.label} style={{ flex: 1, textAlign: 'center', padding: '8px 4px', background: 'rgba(255,255,255,0.03)', borderRadius: 8 }}>
                          <div style={{ fontSize: 18, fontWeight: 800, color: d.color, fontFamily: 'JetBrains Mono, monospace' }}>{d.value}</div>
                          <div style={{ fontSize: 10, color: C.muted, marginTop: 2, fontWeight: 600 }}>{d.label}</div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Confidence */}
                  {marketView.avg_confidence != null && (
                    <div>
                      <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Avg Confidence</div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <div style={{ flex: 1, height: 4, background: 'rgba(255,255,255,0.06)', borderRadius: 999, overflow: 'hidden' }}>
                          <div style={{ height: '100%', width: `${(marketView.avg_confidence * 100).toFixed(0)}%`, background: C.brand, borderRadius: 999, transition: 'width 0.5s ease' }} />
                        </div>
                        <span style={{ fontSize: 12, fontWeight: 700, color: C.text, fontFamily: 'JetBrains Mono, monospace', flexShrink: 0 }}>
                          {(marketView.avg_confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Summary */}
                  {marketView.summary && (
                    <div style={{ padding: '10px 12px', background: 'rgba(255,255,255,0.02)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.04)' }}>
                      <div style={{ fontSize: 12, color: C.textSub, lineHeight: 1.6 }}>
                        {marketView.summary}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ── Recent Trades ──────────────────────────────────── */}
        <div
          style={{
            background: '#0d0d14',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: 12,
            overflow: 'hidden',
            marginBottom: 24,
          }}
        >
          <div style={{ padding: '14px 20px', borderBottom: '1px solid rgba(255,255,255,0.04)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>Recent Trades</div>
            <Link href="/results" style={{ fontSize: 12, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>
              Full history →
            </Link>
          </div>

          {/* Header */}
          <div style={{ display: 'grid', gridTemplateColumns: '80px 56px 110px 80px 70px 60px', gap: 8, padding: '8px 16px', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
            {['Symbol', 'Side', 'Strategy', 'P&L', 'Result', 'Hold'].map((h) => (
              <div key={h} style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.8 }}>{h}</div>
            ))}
          </div>

          {loading ? (
            <div style={{ padding: '20px 16px', color: C.muted, fontSize: 13 }}>Loading trades...</div>
          ) : trades.length === 0 ? (
            <div style={{ padding: '24px 16px', color: C.muted, fontSize: 13, textAlign: 'center' }}>No trade history yet</div>
          ) : (
            trades.slice(0, 10).map((t, i) => <TradeRow key={i} trade={t} />)
          )}
        </div>

        {/* ── Strategy Cards ─────────────────────────────────── */}
        {strategies.length > 0 && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
              <h2 style={{ fontSize: 14, fontWeight: 700, color: C.text, margin: 0 }}>Strategies</h2>
              <Link href="/strategies" style={{ fontSize: 12, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>
                View all →
              </Link>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12 }}>
              {strategies.map((s) => (
                <StrategyCard key={s.id} s={s} />
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
