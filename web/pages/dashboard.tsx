import React, { useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { C, fmtUsd, fmtPct, timeAgo } from '../src/theme';
import { useApi } from '../hooks/useApi';
import { Skeleton } from '../components/ui/Skeleton';
import { StatusDot } from '../components/ui/StatusDot';
import PositionCard, { PositionItem as PositionCardItem } from '../components/PositionCard';
import SniperAlerts from '../components/SniperAlerts';
import SignalFunnel from '../components/SignalFunnel';
import DecisionTrail, { TradeBrief } from '../components/DecisionTrail';
import AgentHealthStrip from '../components/AgentHealthStrip';
import AnimatedNumber from '../components/AnimatedNumber';
import LiveActivityTape from '../components/LiveActivityTape';
import MarketPulse from '../components/MarketPulse';
import MetricSparkline from '../components/MetricSparkline';
import ScanningEmptyState from '../components/ScanningEmptyState';
import type {
  TradeRecord,
  EquityCurvePoint,
  LlmMarketView,
  Strategy,
} from '../src/types';

// Lightweight signal payload for live price ingestion
type SignalsApiLite = {
  signals?: Record<string, { price?: number | null }>;
  last_updated?: string | null;
};

// ─── Types ────────────────────────────────────────────────────────────────────

type TimeRange = '7D' | '30D' | '90D' | 'ALL';

/** Summary response from /v1/summary */
type SummaryResponse = {
  equity: number;
  peak_equity: number;
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  open_positions: number;
  today_pnl: number;
  today_trades: number;
};

/** Raw trade shape from /v1/trades/history (api_server.py) */
type RawTrade = {
  id?: string;
  timestamp?: string;
  symbol: string;
  side: string;
  entry?: number;
  exit?: number;
  pnl: number;
  outcome: string;
  confidence?: number;
  leverage?: number;
  strategy?: string;
  regime?: string;
  state_path?: string;
  entry_type?: string;
  fees?: number;
};

type TradeHistoryApiResponse = {
  trades: RawTrade[];
  total: number;
  wins?: number;
  losses?: number;
  win_rate?: number;
  total_pnl?: number;
};

type EquityCurveApiResponse = {
  points: Array<{ ts: string; equity: number; pnl?: number; symbol?: string; drawdown_pct?: number }>;
};

type PositionItem = {
  symbol: string;
  side: string;
  entry: number;
  sl: number;
  tp1: number;
  tp2: number;
  state: string;
  leverage: number;
  qty: number;
  realized_pnl: number;
  open_time: string;
};

type PositionsApiResponse = {
  positions: PositionItem[];
  count: number;
};

// ─── Normalizers ──────────────────────────────────────────────────────────────

function normalizeTrade(t: RawTrade): TradeRecord {
  const pnl = t.pnl ?? 0;
  return {
    symbol: t.symbol ?? '',
    side: t.side ?? '',
    strategy: t.strategy ?? 'ensemble',
    close_reason: t.state_path ?? '',
    entry: t.entry ?? null,
    exit: t.exit ?? null,
    sl: null,
    tp1: null,
    tp2: null,
    pnl,
    fee: t.fees ?? null,
    leverage: t.leverage ?? null,
    confidence: t.confidence ?? null,
    rr_achieved: null,
    duration_h: null,
    outcome: t.outcome || (pnl > 0 ? 'WIN' : 'LOSS'),
    llm_action: null,
    llm_regime: t.regime ?? null,
    llm_confidence: null,
  };
}

function normalizeEquityPoints(
  raw: EquityCurveApiResponse | undefined,
): EquityCurvePoint[] {
  if (!raw?.points || raw.points.length === 0) return [];
  // Compute rolling drawdown_pct if absent
  let peak = raw.points[0]?.equity ?? 0;
  return raw.points.map((p) => {
    if (p.equity > peak) peak = p.equity;
    const dd = peak > 0 ? ((peak - p.equity) / peak) * 100 : 0;
    return {
      ts: p.ts,
      equity: p.equity,
      drawdown_pct: p.drawdown_pct ?? dd,
    };
  });
}

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
  numericValue,
  formatter,
  sub,
  color,
  loading,
  icon,
  sparklineValues,
  sparklineColor,
}: {
  label: string;
  value?: string;
  numericValue?: number | null;
  formatter?: (n: number) => string;
  sub?: string;
  color?: string;
  loading?: boolean;
  icon?: React.ReactNode;
  sparklineValues?: number[];
  sparklineColor?: string;
}) {
  return (
    <div
      className="metric-card"
      style={{
        flex: '1 1 160px',
        padding: '18px 20px',
        background: '#0d0d14',
        border: '1px solid rgba(255,255,255,0.06)',
        borderRadius: 12,
        minWidth: 140,
        transition: 'transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: C.muted, textTransform: 'uppercase', letterSpacing: 1 }}>
          {label}
        </div>
        {icon && <div style={{ color: C.muted }}>{icon}</div>}
      </div>
      {loading ? (
        <Skeleton w={110} h={28} />
      ) : (
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
          {numericValue != null && formatter
            ? <AnimatedNumber value={numericValue} format={formatter} duration={700} />
            : (value ?? '—')}
        </div>
      )}
      {sub && !loading && (
        <div style={{ fontSize: 11, color: C.muted, marginTop: 4, fontWeight: 500 }}>{sub}</div>
      )}
      {sparklineValues && sparklineValues.length > 1 && !loading && (
        <div style={{ marginTop: 8, opacity: 0.85 }}>
          <MetricSparkline values={sparklineValues} color={sparklineColor} height={22} />
        </div>
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

// ─── Trade Row ────────────────────────────────────────────────────────────────

function TradeRow({ trade, onClick }: { trade: TradeRecord; onClick?: () => void }) {
  const isWin = trade.outcome === 'WIN' || (trade.pnl ?? 0) > 0;

  return (
    <div
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={(e) => {
        if (onClick && (e.key === 'Enter' || e.key === ' ')) onClick();
      }}
      title={onClick ? 'View decision trail' : undefined}
      style={{
        display: 'grid',
        gridTemplateColumns: '80px 56px 110px 80px 70px 60px',
        gap: 8,
        padding: '9px 16px',
        borderBottom: '1px solid rgba(255,255,255,0.03)',
        alignItems: 'center',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'background 0.12s ease',
      }}
      onMouseEnter={(e) => {
        if (onClick) (e.currentTarget as HTMLDivElement).style.background = 'rgba(0,204,136,0.04)';
      }}
      onMouseLeave={(e) => {
        if (onClick) (e.currentTarget as HTMLDivElement).style.background = 'transparent';
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
        {trade.leverage != null ? `${trade.leverage.toFixed(1)}x` : '—'}
      </div>
    </div>
  );
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [range, setRange] = useState<TimeRange>('30D');
  const [trailTrade, setTrailTrade] = useState<TradeBrief | null>(null);

  const openTrail = (t: TradeRecord) => {
    const raw = t as unknown as { id?: string; timestamp?: string };
    setTrailTrade({
      id: raw.id || raw.timestamp || '',
      timestamp: raw.timestamp || '',
      symbol: t.symbol,
      side: t.side,
      entry: t.entry ?? 0,
      exit: t.exit ?? 0,
      pnl: t.pnl ?? 0,
      leverage: t.leverage ?? undefined,
      strategy: t.strategy,
    });
  };

  // SWR-powered live data — positions 10s, summary 15s, trades 30s
  const { data: summary, error: summaryErr, isLoading: summaryLoading } =
    useApi<SummaryResponse>('/v1/summary', { refreshInterval: 15_000 });
  const { data: positionsData, error: positionsErr } =
    useApi<PositionsApiResponse>('/v1/positions', { refreshInterval: 10_000 });
  const { data: tradesData, error: tradesErr, isLoading: tradesLoading } =
    useApi<TradeHistoryApiResponse>('/v1/trades/history?limit=50', { refreshInterval: 30_000 });
  const { data: equityData, isLoading: equityLoading } =
    useApi<EquityCurveApiResponse>('/v1/trades/equity-curve', { refreshInterval: 30_000 });
  const { data: marketView } =
    useApi<LlmMarketView>('/v1/llm/market-view', { refreshInterval: 60_000 });
  const { data: strategiesData } =
    useApi<{ strategies: Strategy[] }>('/v1/strategies', { refreshInterval: 60_000 });
  // Live per-symbol prices (feeds into PositionCard)
  const { data: liveSignals } =
    useApi<SignalsApiLite>('/v1/signals', { refreshInterval: 20_000 });
  const priceUpdatedAt = liveSignals?.last_updated ? new Date(liveSignals.last_updated).getTime() : null;

  const apiDown = Boolean(summaryErr && positionsErr && tradesErr);

  const trades: TradeRecord[] = (tradesData?.trades ?? []).map(normalizeTrade);
  const allPoints = normalizeEquityPoints(equityData);
  const positions = positionsData?.positions ?? [];
  const strategies = strategiesData?.strategies ?? [];

  const visiblePoints = filterByRange(allPoints, range);
  const sharpe = calcSharpe(allPoints);
  const maxDD = allPoints.length > 1 ? calcMaxDD(allPoints) : null;

  // Prefer summary numbers when available
  const equity = summary?.equity ?? allPoints[allPoints.length - 1]?.equity ?? null;
  const todayPnl = summary?.today_pnl ?? null;
  const winRate = summary?.win_rate ?? null;
  const totalTrades = summary?.total_trades ?? trades.length;
  const openPositionsCount = summary?.open_positions ?? positions.length;

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
        <title>Dashboard — WAGMI</title>
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
              Live trading overview · positions 10s · summary 15s · trades 30s
            </p>
          </div>

          {/* Status pills */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            {apiDown ? (
              <StatusDot kind="error" label="API OFFLINE" />
            ) : summary ? (
              <StatusDot kind="live" label="LIVE" />
            ) : (
              <StatusDot kind="stale" label="CONNECTING" />
            )}
            {/* Regime */}
            {marketView?.regime && regimeStyle && (
              <div style={{ padding: '5px 10px', background: regimeStyle.bg, border: `1px solid ${regimeStyle.text}30`, borderRadius: 999 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: regimeStyle.text, textTransform: 'capitalize' }}>
                  {marketView.regime.replace(/_/g, ' ')}
                </span>
              </div>
            )}
            {/* Open positions */}
            {openPositionsCount > 0 && (
              <div style={{ padding: '5px 10px', background: 'rgba(68,136,255,0.08)', border: '1px solid rgba(68,136,255,0.2)', borderRadius: 999 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: C.info }}>
                  {openPositionsCount} OPEN
                </span>
              </div>
            )}
          </div>
        </div>

        {/* ── Live Activity Tape ───────────────────────────────── */}
        <div style={{ margin: '0 -24px 24px' }}>
          <LiveActivityTape />
        </div>

        {/* ── Market Pulse ─────────────────────────────────────── */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1.4, fontFamily: 'JetBrains Mono, monospace', marginBottom: 10 }}>
            Market Pulse
          </div>
          <MarketPulse />
        </div>

        {/* ── Metric Cards ───────────────────────────────────── */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 }} className="stagger-reveal">
          <MetricCard
            label="Portfolio Value"
            numericValue={equity}
            formatter={(n) => fmtUsd(n)}
            sub="Current equity"
            color={C.text}
            loading={summaryLoading && equity == null}
            sparklineValues={visiblePoints.slice(-30).map((p) => p.equity)}
          />
          <MetricCard
            label="Today's P&L"
            numericValue={todayPnl}
            formatter={(n) => fmtUsd(n)}
            sub={summary?.today_trades != null ? `${summary.today_trades} trades today` : 'vs open'}
            color={todayPnl == null ? C.text : todayPnl >= 0 ? C.bull : C.bear}
            loading={summaryLoading && todayPnl == null}
          />
          <MetricCard
            label="Total P&L"
            numericValue={summary?.total_pnl ?? null}
            formatter={(n) => fmtUsd(n)}
            sub={`${totalTrades} trades`}
            color={summary?.total_pnl == null ? C.text : summary.total_pnl >= 0 ? C.bull : C.bear}
            loading={summaryLoading}
            sparklineValues={visiblePoints.length > 1 ? visiblePoints.slice(-30).map((p) => p.equity - visiblePoints[0].equity) : []}
          />
          <MetricCard
            label="Win Rate"
            numericValue={winRate}
            formatter={(n) => fmtPct(n)}
            sub={`${totalTrades} trades`}
            color={winRate == null ? C.text : winRate >= 55 ? C.bull : winRate >= 45 ? C.warn : C.bear}
            loading={summaryLoading && winRate == null}
          />
          <MetricCard
            label="Open Positions"
            value={String(openPositionsCount)}
            sub="Live on exchange"
            color={openPositionsCount > 0 ? C.info : C.muted}
          />
          <MetricCard
            label="Sharpe"
            numericValue={sharpe}
            formatter={(n) => n.toFixed(2)}
            sub="Annualized"
            color={sharpe == null ? C.text : sharpe >= 1.5 ? C.bull : sharpe >= 0.5 ? C.warn : C.bear}
            loading={equityLoading && sharpe == null}
          />
          <MetricCard
            label="Max Drawdown"
            numericValue={maxDD}
            formatter={(n) => `-${n.toFixed(1)}%`}
            sub="From peak"
            color={maxDD == null ? C.text : maxDD <= 10 ? C.bull : maxDD <= 20 ? C.warn : C.bear}
            loading={equityLoading && maxDD == null}
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
            {equityLoading && visiblePoints.length === 0 ? (
              <Skeleton variant="chart" h={176} />
            ) : (
              <EquityChart points={visiblePoints} />
            )}
          </div>
        </div>

        {/* ── Open Positions ──────────────────────────────────── */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
            <h2 style={{ fontSize: 14, fontWeight: 700, color: C.text, margin: 0 }}>Open Positions</h2>
            <Link href="/portfolio" style={{ fontSize: 12, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>
              Full view →
            </Link>
          </div>

          {positions.length === 0 ? (
            <div
              style={{
                padding: '20px',
                background: 'rgba(13,13,20,0.7)',
                backdropFilter: 'blur(12px)',
                WebkitBackdropFilter: 'blur(12px)',
                border: '1px solid rgba(255,255,255,0.05)',
                borderRadius: 12,
              }}
            >
              <ScanningEmptyState
                label={positionsErr ? 'Unable to load positions' : 'No open positions'}
                sub={positionsErr ? 'Retrying in background' : 'Bot is scanning — new entries appear here when agents agree'}
              />
            </div>
          ) : (
            <div
              className="stagger-reveal"
              style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12 }}
            >
              {positions.map((p) => {
                const livePx = liveSignals?.signals?.[p.symbol]?.price ?? null;
                return (
                  <PositionCard
                    key={p.symbol}
                    position={p as PositionCardItem}
                    livePrice={livePx}
                    priceUpdatedAt={priceUpdatedAt}
                  />
                );
              })}
            </div>
          )}
        </div>

        {/* ── Sniper Alerts + AI Brain ───────────────────────── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16, marginBottom: 24 }}>
          <SniperAlerts limit={10} />

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
              {!marketView ? (
                <div style={{ color: C.muted, fontSize: 13 }}>Loading...</div>
              ) : !marketView.has_data ? (
                <div style={{ color: C.muted, fontSize: 13 }}>
                  {typeof marketView.summary === 'string' && marketView.summary
                    ? marketView.summary
                    : 'No brain data yet.'}
                </div>
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

        {/* ── Signal Funnel ──────────────────────────────────── */}
        <div style={{ marginBottom: 24 }}>
          <SignalFunnel hours={24} />
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

          {/* Inner scroll wrapper for narrow viewports — keeps the grid neat on mobile */}
          <div style={{ overflowX: 'auto', WebkitOverflowScrolling: 'touch' }}>
            <div style={{ minWidth: 504 }}>
              {/* Header */}
              <div style={{ display: 'grid', gridTemplateColumns: '80px 56px 110px 80px 70px 60px', gap: 8, padding: '8px 16px', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                {['Symbol', 'Side', 'Strategy', 'P&L', 'Result', 'Lev'].map((h) => (
                  <div key={h} style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.8 }}>{h}</div>
                ))}
              </div>

              {tradesLoading && trades.length === 0 ? (
                <div style={{ padding: '16px' }}>
                  <Skeleton h={14} />
                  <div style={{ height: 8 }} />
                  <Skeleton h={14} />
                  <div style={{ height: 8 }} />
                  <Skeleton h={14} />
                </div>
              ) : tradesErr ? (
                <div style={{ padding: '24px 16px', color: C.bear, fontSize: 13, textAlign: 'center' }}>
                  Unable to load trade history
                </div>
              ) : trades.length === 0 ? (
                <div style={{ padding: '20px 16px' }}>
                  <ScanningEmptyState label="No trade history yet" sub="Fills will appear as the bot executes" />
                </div>
              ) : (
                trades.slice(-10).reverse().map((t, i) => (
                  <TradeRow key={i} trade={t} onClick={() => openTrail(t)} />
                ))
              )}
            </div>
          </div>
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
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
              {strategies.map((s) => (
                <div
                  key={s.id}
                  style={{
                    padding: '14px 16px',
                    background: '#0d0d14',
                    border: '1px solid rgba(255,255,255,0.06)',
                    borderRadius: 10,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 6,
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 700, color: C.text }}>{s.name || s.id}</div>
                  {(s as unknown as { description?: string }).description && (
                    <div style={{ fontSize: 11, color: C.muted, lineHeight: 1.5 }}>
                      {(s as unknown as { description?: string }).description}
                    </div>
                  )}
                  {(s as unknown as { status?: string }).status && (
                    <div style={{ fontSize: 10, color: C.bull, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.8 }}>
                      {(s as unknown as { status?: string }).status}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Agent Health strip — shows which of the 9 specialist agents are live */}
        <div style={{ marginTop: 24 }}>
          <AgentHealthStrip />
        </div>

        {/* Keep timeAgo import used for type-compat even if unused visually */}
        <span style={{ display: 'none' }}>{timeAgo(null)}</span>
      </div>

      {/* Decision trail slide-over */}
      <DecisionTrail
        trade={trailTrade}
        open={trailTrade !== null}
        onClose={() => setTrailTrade(null)}
      />

      <style jsx>{`
        .metric-card:hover {
          transform: translateY(-2px);
          border-color: rgba(255, 255, 255, 0.12) !important;
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(0, 204, 136, 0.08);
        }
      `}</style>
    </>
  );
}
