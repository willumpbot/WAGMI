'use client';

import React, { useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { C, R, S, F, fmtUsd, fmtPct, timeAgo } from '../src/theme';
import type { BacktestResult, ActivityEvent, LlmMarketView } from '../src/types';

// ─── API helper ───────────────────────────────────────────────────────────────

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

// ─── Types ────────────────────────────────────────────────────────────────────

type Signal = {
  symbol: string;
  label: string;
  score: number;
  price: number;
  sma20: number;
  sma50: number;
  atr14: number;
  atr_pct?: number;
  rsi14?: number;
  vol_spike?: boolean;
  zones: { deepAccum: number; accum: number; distrib: number; safeDistrib: number };
};
type SignalsPayload = {
  last_updated?: string;
  regime?: string;
  signals?: Record<string, Signal>;
};
type Strategy = {
  id: string;
  name?: string;
  status?: string;
  lastHeartbeat?: string;
  pnl_realized?: number | null;
  open_position?: { side?: string; size?: number; avg_entry?: number; unrealized_pnl?: number } | null;
};

const SYMBOLS = ['BTC', 'SOL', 'HYPE'];
const TV_SYMBOLS: Record<string, string> = {
  BTC: 'BINANCE:BTCUSDT',
  SOL: 'BINANCE:SOLUSDT',
  HYPE: 'BYBIT:HYPEUSDT',
};

// ─── Skeleton ─────────────────────────────────────────────────────────────────

function Skeleton({ w, h, style = {} }: { w?: string | number; h?: string | number; style?: React.CSSProperties }) {
  return (
    <div
      className="skeleton"
      style={{ width: w ?? '100%', height: h ?? 16, borderRadius: R.sm, ...style }}
    />
  );
}

// ─── KPI Card ─────────────────────────────────────────────────────────────────

function KpiCard({
  label,
  value,
  sub,
  color,
  loading,
}: {
  label: string;
  value: string;
  sub: string;
  color?: string;
  loading?: boolean;
}) {
  return (
    <div
      className="fade-in"
      style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '20px 24px',
        boxShadow: S.sm,
        flex: '1 1 180px',
        minWidth: 160,
      }}
    >
      <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 6 }}>
        {label}
      </div>
      {loading ? (
        <>
          <Skeleton h={28} style={{ marginBottom: 8 }} />
          <Skeleton h={12} w="60%" />
        </>
      ) : (
        <>
          <div style={{ fontSize: F['2xl'], fontWeight: 800, color: color || C.text, lineHeight: 1.2, marginBottom: 4 }}>
            {value}
          </div>
          <div style={{ fontSize: F.xs, color: C.muted }}>{sub}</div>
        </>
      )}
    </div>
  );
}

// ─── Sparkline Chart ──────────────────────────────────────────────────────────

function SparklineChart({ data, width = 220, height = 50 }: { data: number[]; width?: number; height?: number }) {
  if (!data || data.length < 2) {
    return <div style={{ width, height, background: C.surfaceHover, borderRadius: R.sm }} />;
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 4) - 2;
    return `${x},${y}`;
  });
  const polyline = pts.join(' ');
  const isPositive = data[data.length - 1] >= data[0];
  const lineColor = isPositive ? C.bull : C.bear;

  // Area fill path
  const areaPath = `M ${pts[0]} L ${polyline.split(' ').slice(1).join(' L ')} L ${width},${height} L 0,${height} Z`;

  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <defs>
        <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lineColor} stopOpacity={0.3} />
          <stop offset="100%" stopColor={lineColor} stopOpacity={0} />
        </linearGradient>
      </defs>
      <path d={areaPath} fill="url(#sparkGrad)" />
      <polyline fill="none" stroke={lineColor} strokeWidth={2} points={polyline} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// ─── Market Heatmap ───────────────────────────────────────────────────────────

function heatColor(value: number, low: number, high: number, invertBull = false): string {
  const pct = Math.max(0, Math.min(1, (value - low) / (high - low)));
  // 0 = most bearish/low, 1 = most bullish/high
  const bullish = invertBull ? 1 - pct : pct;
  if (bullish > 0.72) return C.heatBull2;
  if (bullish > 0.55) return C.heatBull1 + '55';
  if (bullish < 0.28) return C.heatBear2;
  if (bullish < 0.45) return C.heatBear1 + '55';
  return C.heatNeutral;
}

function HeatCell({ value, label, low, high, invertBull = false }: {
  value: string | number;
  label?: string;
  low: number;
  high: number;
  invertBull?: boolean;
}) {
  const num = typeof value === 'number' ? value : parseFloat(String(value));
  const bg = isNaN(num) ? C.heatNeutral : heatColor(num, low, high, invertBull);
  return (
    <td
      style={{
        padding: '10px 14px',
        background: bg,
        textAlign: 'center',
        fontSize: F.sm,
        fontWeight: 600,
        color: C.text,
        borderRight: `1px solid ${C.border}`,
        transition: 'background 0.3s',
      }}
    >
      {label ?? value}
    </td>
  );
}

function MarketHeatmap({ signals, loading, onSelect }: {
  signals: Record<string, Signal>;
  loading: boolean;
  onSelect: (sym: string) => void;
}) {
  const rows = [
    {
      label: 'Score',
      render: (s: Signal) => ({
        value: s.score,
        label: `${s.score}`,
        low: 0, high: 100,
      }),
    },
    {
      label: 'RSI',
      render: (s: Signal) => ({
        value: s.rsi14 ?? 50,
        label: s.rsi14 != null ? s.rsi14.toFixed(1) : '—',
        low: 20, high: 80,
      }),
    },
    {
      label: 'ATR %',
      render: (s: Signal) => ({
        value: s.atr_pct ?? 0,
        label: s.atr_pct != null ? s.atr_pct.toFixed(2) + '%' : '—',
        low: 0, high: 5,
        invertBull: true,
      }),
    },
    {
      label: 'Trend',
      render: (s: Signal) => {
        const up = s.sma20 > s.sma50;
        return { value: up ? 1 : 0, label: up ? '↑ Up' : '↓ Down', low: 0, high: 1 };
      },
    },
    {
      label: 'Zone',
      render: (s: Signal) => {
        const p = s.price;
        const { deepAccum, accum, distrib, safeDistrib } = s.zones;
        let zone = 'Neutral';
        let score = 0.5;
        if (p <= deepAccum) { zone = 'Deep Accum'; score = 0.95; }
        else if (p <= accum) { zone = 'Accum'; score = 0.7; }
        else if (p >= safeDistrib) { zone = 'Safe Distrib'; score = 0.05; }
        else if (p >= distrib) { zone = 'Distrib'; score = 0.25; }
        return { value: score, label: zone, low: 0, high: 1 };
      },
    },
  ];

  return (
    <div style={{ overflowX: 'auto', borderRadius: R.md, border: `1px solid ${C.border}` }}>
      <table style={{ borderCollapse: 'collapse', minWidth: 420, width: '100%' }}>
        <thead>
          <tr style={{ background: C.surface }}>
            <th style={{ padding: '10px 14px', fontSize: F.xs, color: C.muted, fontWeight: 600, textAlign: 'left', borderRight: `1px solid ${C.border}` }}>
              Indicator
            </th>
            {SYMBOLS.map((sym) => (
              <th
                key={sym}
                onClick={() => onSelect(sym)}
                style={{
                  padding: '10px 14px',
                  fontSize: F.sm,
                  fontWeight: 700,
                  color: C.brand,
                  cursor: 'pointer',
                  textAlign: 'center',
                  borderRight: `1px solid ${C.border}`,
                  userSelect: 'none',
                }}
                title={`Click to view ${sym} chart`}
              >
                {sym}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {/* Price row */}
          <tr style={{ borderTop: `1px solid ${C.border}` }}>
            <td style={{ padding: '10px 14px', fontSize: F.xs, color: C.muted, fontWeight: 600, borderRight: `1px solid ${C.border}` }}>
              Price
            </td>
            {SYMBOLS.map((sym) => {
              const s = signals[sym];
              return (
                <td key={sym} style={{ padding: '10px 14px', textAlign: 'center', fontSize: F.sm, fontWeight: 600, color: C.text, borderRight: `1px solid ${C.border}` }}>
                  {loading ? <Skeleton h={14} /> : s ? fmtUsd(s.price, s.price > 100 ? 2 : 4) : <span style={{ color: C.muted }}>—</span>}
                </td>
              );
            })}
          </tr>

          {rows.map((row) => (
            <tr key={row.label} style={{ borderTop: `1px solid ${C.border}` }}>
              <td style={{ padding: '10px 14px', fontSize: F.xs, color: C.muted, fontWeight: 600, borderRight: `1px solid ${C.border}` }}>
                {row.label}
              </td>
              {SYMBOLS.map((sym) => {
                const s = signals[sym];
                if (!s) return <td key={sym} style={{ padding: '10px 14px', background: C.heatNeutral, borderRight: `1px solid ${C.border}` }} />;
                if (loading) return <td key={sym} style={{ padding: '10px 14px', borderRight: `1px solid ${C.border}` }}><Skeleton h={14} /></td>;
                const { value, label, low, high, invertBull } = row.render(s) as any;
                return <HeatCell key={sym} value={value} label={label} low={low} high={high} invertBull={invertBull} />;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {/* Legend */}
      <div style={{ padding: '8px 14px', background: C.surface, display: 'flex', gap: 16, fontSize: F.xs, color: C.muted, borderTop: `1px solid ${C.border}` }}>
        <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: C.heatBull2, marginRight: 4 }} />Strong bull</span>
        <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: C.heatNeutral, marginRight: 4 }} />Neutral</span>
        <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: C.heatBear2, marginRight: 4 }} />Strong bear</span>
        <span style={{ marginLeft: 'auto' }}>Click symbol header to view chart</span>
      </div>
    </div>
  );
}

// ─── Activity Ticker ──────────────────────────────────────────────────────────

function ActivityTicker({ events }: { events: ActivityEvent[] }) {
  if (!events.length) return null;

  const items = [...events, ...events]; // duplicate for seamless loop
  return (
    <div
      style={{
        overflow: 'hidden',
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.md,
        padding: '8px 0',
        marginTop: 16,
      }}
    >
      <div
        style={{
          display: 'flex',
          gap: 32,
          animation: 'tickerScroll 40s linear infinite',
          whiteSpace: 'nowrap',
          width: 'max-content',
          paddingLeft: 16,
        }}
        onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.animationPlayState = 'paused')}
        onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.animationPlayState = 'running')}
      >
        {items.map((ev, i) => (
          <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: R.xs, background: ev.badge_color + '22', color: ev.badge_color }}>
              {ev.badge}
            </span>
            {ev.symbol && <span style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub }}>{ev.symbol}</span>}
            <span style={{ fontSize: F.xs, color: C.muted }}>{timeAgo(ev.ts_iso || ev.ts)}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── TradingView Chart ────────────────────────────────────────────────────────

function TradingViewChart({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const tvSymbol = TV_SYMBOLS[symbol] || `BINANCE:${symbol}USDT`;

  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = '';
    const widgetDiv = document.createElement('div');
    widgetDiv.className = 'tradingview-widget-container__widget';
    widgetDiv.style.cssText = 'height:100%;width:100%';
    containerRef.current.appendChild(widgetDiv);
    const script = document.createElement('script');
    script.type = 'text/javascript';
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.async = true;
    script.textContent = JSON.stringify({
      autosize: true,
      symbol: tvSymbol,
      interval: '60',
      timezone: 'Etc/UTC',
      theme: 'dark',
      style: '1',
      locale: 'en',
      hide_top_toolbar: false,
      hide_legend: false,
      allow_symbol_change: false,
      save_image: false,
      hide_volume: false,
      support_host: 'https://www.tradingview.com',
    });
    containerRef.current.appendChild(script);
  }, [tvSymbol]);

  return <div className="tradingview-widget-container" ref={containerRef} style={{ height: 400, width: '100%' }} />;
}

// ─── Strategy Card ────────────────────────────────────────────────────────────

function StrategyCard({ strategy }: { strategy: Strategy }) {
  const router = useRouter();
  const lastSeen = strategy.lastHeartbeat || (strategy as any).last_seen_ts;
  const pnl = strategy.pnl_realized ?? (strategy as any).pnl_realized ?? null;
  const pos = strategy.open_position || (strategy as any).open_position;

  const ageSeconds = lastSeen
    ? (Date.now() - new Date(lastSeen).getTime()) / 1000
    : Infinity;
  const isLive = ageSeconds < 120;

  return (
    <div
      className="fade-in"
      onClick={() => router.push(`/strategies/${strategy.id}`)}
      style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '16px 20px',
        cursor: 'pointer',
        transition: 'border-color 0.15s, box-shadow 0.15s',
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLElement).style.borderColor = C.brand;
        (e.currentTarget as HTMLElement).style.boxShadow = S.glow;
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLElement).style.borderColor = C.border;
        (e.currentTarget as HTMLElement).style.boxShadow = 'none';
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>
          {strategy.name || strategy.id}
        </div>
        <span
          style={{
            fontSize: F.xs,
            fontWeight: 700,
            padding: '2px 8px',
            borderRadius: R.pill,
            background: isLive ? C.bullLight + '22' : C.border,
            color: isLive ? C.bull : C.muted,
          }}
        >
          {isLive ? '● LIVE' : 'OFFLINE'}
        </span>
      </div>

      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 8 }}>
        Last seen: {lastSeen ? timeAgo(lastSeen) : 'never'}
      </div>

      {pnl != null && (
        <div style={{ fontSize: F.md, fontWeight: 700, color: pnl >= 0 ? C.bull : C.bear, marginBottom: 8 }}>
          {fmtUsd(pnl)} realized PnL
        </div>
      )}

      {pos && (
        <div
          style={{
            padding: '8px 10px',
            background: C.surfaceHover,
            borderRadius: R.sm,
            fontSize: F.xs,
          }}
        >
          <span style={{ color: pos.side === 'long' || pos.side === 'LONG' ? C.bull : C.bear, fontWeight: 700 }}>
            {pos.side?.toUpperCase()}
          </span>
          {' · '}
          <span style={{ color: C.textSub }}>avg entry {fmtUsd(pos.avg_entry ?? null)}</span>
          {pos.unrealized_pnl != null && (
            <span style={{ marginLeft: 8, color: pos.unrealized_pnl >= 0 ? C.bull : C.bear, fontWeight: 600 }}>
              {pos.unrealized_pnl >= 0 ? '+' : ''}{fmtUsd(pos.unrealized_pnl)}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Home() {
  const [signalsData, setSignalsData] = useState<SignalsPayload>({});
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [llmView, setLlmView] = useState<LlmMarketView | null>(null);
  const [activeChart, setActiveChart] = useState('BTC');
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState(false);
  const apiBase = resolveApiBase();

  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [sigRes, stratRes, btRes, actRes, llmRes] = await Promise.allSettled([
          fetch(`${apiBase}/v1/signals`),
          fetch(`${apiBase}/v1/strategies`),
          fetch(`${apiBase}/v1/backtest/results/latest`),
          fetch(`${apiBase}/v1/activity/feed?limit=8`),
          fetch(`${apiBase}/v1/llm/market-view`),
        ]);

        if (sigRes.status === 'fulfilled' && sigRes.value.ok) {
          setSignalsData(await sigRes.value.json());
          setApiError(false);
        } else {
          setApiError(true);
        }
        if (stratRes.status === 'fulfilled' && stratRes.value.ok) {
          const d = await stratRes.value.json();
          setStrategies(Array.isArray(d) ? d : d?.items || []);
        }
        if (btRes.status === 'fulfilled' && btRes.value.ok) {
          setBacktest(await btRes.value.json());
        }
        if (actRes.status === 'fulfilled' && actRes.value.ok) {
          const d = await actRes.value.json();
          setActivity(d?.items || []);
        }
        if (llmRes.status === 'fulfilled' && llmRes.value.ok) {
          setLlmView(await llmRes.value.json());
        }
        setLoading(false);
      } catch {
        setLoading(false);
        setApiError(true);
      }
    };

    fetchAll();
    const iv = setInterval(fetchAll, 30000);
    return () => clearInterval(iv);
  }, [apiBase]);

  const signals = signalsData.signals || {};
  const btRes = backtest?.results;
  const regime = llmView?.regime || signalsData.regime || 'Unknown';

  // Equity sparkline: derive running cumulative PnL from individual trades (real data)
  const sparkData = (() => {
    if (!btRes) return [];
    const trades = (btRes as any).trades as Array<{ pnl?: number; pnl_pct?: number }> | undefined;
    if (trades && trades.length >= 2) {
      let cum = 0;
      return trades.map((t) => { cum += t.pnl_pct ?? t.pnl ?? 0; return cum; });
    }
    // Fallback: use by_symbol cumulative values as rough curve points
    const bySymbol = (btRes as any).by_symbol as Record<string, { pnl?: number }> | undefined;
    if (bySymbol) {
      let cum = 0;
      return Object.values(bySymbol).map((s) => { cum += s.pnl ?? 0; return cum; });
    }
    return [];
  })();

  return (
    <div>
      {/* ── API offline banner ─────────────────────────── */}
      {apiError && !loading && (
        <div
          style={{
            background: C.warnLight,
            border: `1px solid ${C.warnMid}`,
            borderRadius: R.md,
            padding: '10px 16px',
            marginBottom: 20,
            fontSize: F.sm,
            color: '#92400e',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
          }}
        >
          <span>⚠ API not responding — data may be stale. Check that the API server is running.</span>
          <button
            onClick={() => window.location.reload()}
            style={{ background: 'none', border: `1px solid #d97706`, borderRadius: R.sm, padding: '2px 10px', fontSize: F.xs, cursor: 'pointer', color: '#92400e' }}
          >
            Retry
          </button>
        </div>
      )}

      {/* ── Page header ───────────────────────────────── */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: F['3xl'], fontWeight: 800, color: C.text, letterSpacing: -0.5 }}>
              Dashboard
            </h1>
            <p style={{ margin: '4px 0 0', fontSize: F.sm, color: C.muted }}>
              Live signals · AI analysis · Real-time market intelligence
            </p>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <Link href="/results" style={{ fontSize: F.sm, color: C.brand, fontWeight: 600, textDecoration: 'none', border: `1px solid ${C.brand}40`, padding: '6px 14px', borderRadius: R.md }}>
              View Results →
            </Link>
            <Link href="/copy-trade" style={{ fontSize: F.sm, color: '#fff', fontWeight: 600, textDecoration: 'none', background: C.brand, padding: '6px 14px', borderRadius: R.md }}>
              Copy Trade →
            </Link>
          </div>
        </div>
      </div>

      {/* ── Always Watching Intelligence Bar ──────────── */}
      {llmView && (
        <div style={{
          background: 'linear-gradient(90deg, #0f172a 0%, #1e293b 100%)',
          border: `1px solid ${C.border}`,
          borderRadius: R.lg,
          padding: '14px 20px',
          marginBottom: 24,
          display: 'flex',
          alignItems: 'center',
          gap: 0,
          flexWrap: 'wrap',
        }}>
          {/* Live pulse */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginRight: 20, flexShrink: 0 }}>
            <div style={{ position: 'relative', width: 10, height: 10 }}>
              <div style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: C.bull, opacity: 0.8 }} />
              <div style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: C.bull, animation: 'ripplePulse 2s ease-out infinite' }} />
            </div>
            <span style={{ fontSize: F.xs, fontWeight: 700, color: C.bull, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              Always On
            </span>
          </div>

          {/* Divider */}
          <div style={{ width: 1, height: 28, background: C.border, marginRight: 20 }} />

          {/* Regime */}
          <div style={{ marginRight: 24 }}>
            <span style={{ fontSize: F.xs, color: C.muted }}>Regime </span>
            <span style={{
              fontSize: F.sm,
              fontWeight: 700,
              color: regime.toLowerCase() === 'trend' ? C.bull :
                     regime.toLowerCase() === 'panic' ? C.bear :
                     regime.toLowerCase() === 'range' ? '#60a5fa' :
                     regime.toLowerCase() === 'high_volatility' ? '#fbbf24' : C.text,
            }}>
              {regime.toUpperCase()}
            </span>
          </div>

          {/* Decision counts */}
          {llmView.decision_counts && (
            <div style={{ display: 'flex', gap: 16, marginRight: 24, fontSize: F.xs }}>
              <span style={{ color: C.bull, fontWeight: 700 }}>✓ {llmView.decision_counts.proceed} trade</span>
              <span style={{ color: C.muted }}>— {llmView.decision_counts.flat} skip</span>
              <span style={{ color: '#a78bfa' }}>↔ {llmView.decision_counts.flip} flip</span>
            </div>
          )}

          {/* Spacer */}
          <div style={{ flex: 1 }} />

          {/* CTA */}
          <Link href="/signals" style={{
            fontSize: F.xs,
            fontWeight: 700,
            color: C.brand,
            textDecoration: 'none',
            padding: '5px 12px',
            border: `1px solid ${C.brand}44`,
            borderRadius: R.pill,
            flexShrink: 0,
          }}>
            View Signal Feed →
          </Link>
        </div>
      )}
      <style>{`@keyframes ripplePulse { 0% { transform: scale(1); opacity: 0.7; } 100% { transform: scale(2.8); opacity: 0; } }`}</style>

      {/* ── KPI Hero Row ──────────────────────────────── */}
      <div style={{ display: 'flex', gap: 14, marginBottom: 28, flexWrap: 'wrap' }}>
        <KpiCard
          label="Total Return"
          value={btRes ? fmtPct(btRes.total_return_pct) : '—'}
          sub={btRes ? `${btRes.config?.days ?? 30}-day backtest` : 'Waiting for data'}
          color={btRes && btRes.total_return_pct > 0 ? C.bull : C.bear}
          loading={loading}
        />
        <KpiCard
          label="Win Rate"
          value={btRes ? `${(btRes.win_rate * 100).toFixed(1)}%` : '—'}
          sub={btRes ? `${btRes.wins}W / ${btRes.losses}L` : ''}
          color={btRes && btRes.win_rate > 0.6 ? C.bull : C.warn}
          loading={loading}
        />
        <KpiCard
          label="Profit Factor"
          value={btRes ? `${(btRes.profit_factor ?? 0).toFixed(2)}×` : '—'}
          sub="gross profit ÷ gross loss"
          color={btRes && btRes.profit_factor > 1.5 ? C.bull : C.warn}
          loading={loading}
        />
        <KpiCard
          label="Max Drawdown"
          value={btRes ? fmtPct(-Math.abs(btRes.max_drawdown_pct)) : '—'}
          sub="worst peak-to-trough"
          color={btRes && btRes.max_drawdown_pct < 15 ? C.warn : C.bear}
          loading={loading}
        />
        <div
          className="fade-in"
          style={{
            background: C.card,
            border: `1px solid ${C.border}`,
            borderRadius: R.lg,
            padding: '20px 24px',
            flex: '1 1 200px',
            minWidth: 180,
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 6 }}>
            Equity Trend
          </div>
          {loading ? (
            <Skeleton h={50} />
          ) : (
            <>
              <SparklineChart data={sparkData} width={180} height={48} />
              <div style={{ fontSize: F.xs, color: C.muted, marginTop: 4 }}>
                {btRes ? `$${(btRes.config?.starting_equity ?? 50000).toLocaleString()} → ${fmtUsd(btRes.final_equity)}` : 'No backtest data'}
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Activity ticker ───────────────────────────── */}
      <ActivityTicker events={activity} />

      {/* ── Market Heatmap ────────────────────────────── */}
      <div style={{ marginBottom: 28, marginTop: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Market Signals</h2>
          <div style={{ fontSize: F.xs, color: C.muted }}>
            Regime: <strong style={{ color: C.textSub }}>{regime}</strong>
            {signalsData.last_updated && (
              <> · Updated {timeAgo(signalsData.last_updated)}</>
            )}
          </div>
        </div>
        <MarketHeatmap signals={signals} loading={loading} onSelect={setActiveChart} />
      </div>

      {/* ── Chart ────────────────────────────────────── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Chart (1H)</h2>
          <div style={{ display: 'flex', gap: 6, marginLeft: 8 }}>
            {SYMBOLS.map((sym) => (
              <button
                key={sym}
                onClick={() => setActiveChart(sym)}
                style={{
                  padding: '5px 14px',
                  borderRadius: R.pill,
                  border: `1px solid ${activeChart === sym ? C.brand : C.border}`,
                  background: activeChart === sym ? C.brand : 'transparent',
                  color: activeChart === sym ? '#fff' : C.muted,
                  fontSize: F.sm,
                  fontWeight: 600,
                  cursor: 'pointer',
                  transition: 'all 0.15s',
                }}
              >
                {sym}
              </button>
            ))}
          </div>
        </div>
        <div style={{ border: `1px solid ${C.border}`, borderRadius: R.md, overflow: 'hidden', background: C.card }}>
          <TradingViewChart symbol={activeChart} />
        </div>
      </div>

      {/* ── LLM Brain Summary ─────────────────────────── */}
      {llmView?.has_data && (
        <div
          className="fade-in"
          style={{
            background: C.surface,
            border: `1px solid ${C.border}`,
            borderRadius: R.lg,
            padding: '20px 24px',
            marginBottom: 28,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 20 }}>🧠</span>
              <span style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>AI Brain Summary</span>
              <span style={{ fontSize: F.xs, padding: '2px 8px', borderRadius: R.pill, background: '#1e293b', color: C.muted }}>Advisory Mode</span>
            </div>
            <Link href="/signals" style={{ fontSize: F.xs, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>
              Full signal feed →
            </Link>
          </div>

          {/* Per-symbol stance row */}
          {llmView.per_symbol && (
            <div style={{ display: 'flex', gap: 10, marginBottom: 14, flexWrap: 'wrap' }}>
              {Object.entries(llmView.per_symbol).map(([sym, dec]: [string, any]) => {
                const action = (dec.action || 'skip').toLowerCase();
                const isGo = action === 'proceed' || action === 'go';
                const isVeto = dec.is_veto;
                const conf = dec.confidence || 0;
                const confPct = Math.round(conf * 100);
                const stanceColor = isVeto ? C.bear : isGo ? C.bull : C.muted;
                return (
                  <div key={sym} style={{
                    flex: '1 1 120px',
                    background: '#0f172a',
                    border: `1px solid ${stanceColor}33`,
                    borderRadius: R.md,
                    padding: '10px 14px',
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                      <span style={{ fontSize: F.sm, fontWeight: 800, color: C.text }}>{sym}</span>
                      <span style={{
                        fontSize: 10,
                        fontWeight: 700,
                        padding: '1px 6px',
                        borderRadius: R.pill,
                        background: stanceColor + '22',
                        color: stanceColor,
                      }}>
                        {isVeto ? 'VETO' : isGo ? 'GO' : 'SKIP'}
                      </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <div style={{ flex: 1, height: 4, background: C.border, borderRadius: 2, overflow: 'hidden' }}>
                        <div style={{ width: `${confPct}%`, height: '100%', background: stanceColor, borderRadius: 2 }} />
                      </div>
                      <span style={{ fontSize: F.xs, color: stanceColor, fontWeight: 700, minWidth: 28 }}>{confPct}%</span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Summary text */}
          {llmView.summary && (
            <div style={{ fontSize: F.sm, color: C.textSub, lineHeight: 1.6, borderTop: `1px solid ${C.border}`, paddingTop: 12 }}>
              {llmView.summary}
            </div>
          )}
        </div>
      )}

      {/* ── Strategies ───────────────────────────────── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Strategies</h2>
          <Link href="/strategies" style={{ fontSize: F.sm, color: C.brand, textDecoration: 'none', fontWeight: 600 }}>
            View all →
          </Link>
        </div>
        {loading ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 }}>
            {[1, 2].map((i) => <Skeleton key={i} h={100} />)}
          </div>
        ) : strategies.length === 0 ? (
          <div style={{ padding: '24px', background: C.card, borderRadius: R.lg, border: `1px solid ${C.border}`, textAlign: 'center', color: C.muted, fontSize: F.sm }}>
            No strategies registered yet. Start the bot to populate strategy data.
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 }}>
            {strategies.slice(0, 4).map((s) => (
              <StrategyCard key={s.id} strategy={s} />
            ))}
          </div>
        )}
      </div>

      {/* ── Proof teaser ─────────────────────────────── */}
      {btRes && (
        <div
          style={{
            background: `linear-gradient(135deg, ${C.brand}18, ${C.card})`,
            border: `1px solid ${C.brand}40`,
            borderRadius: R.xl,
            padding: '24px 28px',
            marginBottom: 28,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 16,
          }}
        >
          <div>
            <div style={{ fontSize: F.sm, color: C.muted, marginBottom: 4 }}>Latest backtest results</div>
            <div style={{ fontSize: F['2xl'], fontWeight: 800, color: C.bull }}>
              {fmtPct(btRes.total_return_pct)} return · {(btRes.win_rate * 100).toFixed(0)}% win rate
            </div>
            <div style={{ fontSize: F.sm, color: C.textSub, marginTop: 4 }}>
              {btRes.total_trades} trades · {fmtUsd(btRes.net_pnl)} net profit · {btRes.profit_factor?.toFixed(2)}× profit factor
            </div>
          </div>
          <Link
            href="/results"
            style={{
              padding: '10px 22px',
              background: C.brand,
              color: '#fff',
              borderRadius: R.md,
              fontSize: F.sm,
              fontWeight: 700,
              textDecoration: 'none',
              flexShrink: 0,
              boxShadow: S.glow,
            }}
          >
            See Full Results →
          </Link>
        </div>
      )}
    </div>
  );
}
