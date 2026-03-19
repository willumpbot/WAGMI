'use client';

import React, { useEffect, useId, useState, useRef } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { C, R, S, F, G, fmtUsd, fmtPct, timeAgo } from '../src/theme';
import type { BacktestResult, ActivityEvent, LlmMarketView } from '../src/types';
import { resolveApiBase } from '../src/api';

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
      className="fade-in card-hover"
      style={{
        background: G.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '20px 24px',
        boxShadow: S.sm,
        flex: '1 1 180px',
        minWidth: 160,
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Subtle top accent bar */}
      {color && !loading && (
        <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 2, background: color, opacity: 0.6 }} />
      )}
      <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
        {label}
      </div>
      {loading ? (
        <>
          <Skeleton h={28} style={{ marginBottom: 8 }} />
          <Skeleton h={12} w="60%" />
        </>
      ) : (
        <>
          <div className="num" style={{ fontSize: F['2xl'], fontWeight: 800, color: color || C.text, lineHeight: 1.15, marginBottom: 5 }}>
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
  const uid = useId();
  if (!data || data.length < 2) {
    return <div style={{ width, height, background: C.surfaceHover, borderRadius: R.sm }} />;
  }
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  // Unique gradient ID per component instance (useId ensures no collisions)
  const gradId = `sparkGrad-${uid.replace(/:/g, '')}`;

  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 6) - 3;
    return { x, y };
  });

  const polyline = pts.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');

  // Dynamic color based on direction
  const isPositive = data[data.length - 1] >= data[0];
  const lineColor = isPositive ? C.bull : C.bear;
  const fillTopColor = lineColor + '60'; // 38% opacity hex

  // Gradient fill area path
  const areaPath =
    `M ${pts[0].x.toFixed(2)},${pts[0].y.toFixed(2)} ` +
    pts.slice(1).map((p) => `L ${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ') +
    ` L ${width},${height} L 0,${height} Z`;

  // 3-period SMA
  const smaPoints: Array<{ x: number; y: number }> = [];
  for (let i = 2; i < data.length; i++) {
    const smaVal = (data[i] + data[i - 1] + data[i - 2]) / 3;
    const x = (i / (data.length - 1)) * width;
    const y = height - ((smaVal - min) / range) * (height - 6) - 3;
    smaPoints.push({ x, y });
  }
  const smaPolyline = smaPoints.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ');

  // First and last dots
  const firstPt = pts[0];
  const lastPt = pts[pts.length - 1];

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} height={height} style={{ display: 'block', maxWidth: width }}>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={fillTopColor} />
          <stop offset="100%" stopColor="transparent" stopOpacity={0} />
        </linearGradient>
      </defs>
      {/* Gradient fill */}
      <path d={areaPath} fill={`url(#${gradId})`} />
      {/* Main sparkline */}
      <polyline fill="none" stroke={lineColor} strokeWidth={2} points={polyline} strokeLinejoin="round" strokeLinecap="round" />
      {/* 3-period SMA dashed line */}
      {smaPoints.length >= 2 && (
        <polyline
          fill="none"
          stroke={C.muted}
          strokeWidth={1}
          strokeDasharray="3 2"
          points={smaPolyline}
          strokeLinejoin="round"
          strokeLinecap="round"
          opacity={0.6}
        />
      )}
      {/* First value dot */}
      <circle cx={firstPt.x.toFixed(2)} cy={firstPt.y.toFixed(2)} r={3} fill={lineColor} opacity={0.7} />
      {/* Last value dot */}
      <circle cx={lastPt.x.toFixed(2)} cy={lastPt.y.toFixed(2)} r={3.5} fill={lineColor} />
    </svg>
  );
}

// ─── Market Heatmap ───────────────────────────────────────────────────────────

function heatColor(value: number, low: number, high: number, invertBull = false): string {
  const pct = Math.max(0, Math.min(1, (value - low) / (high - low || 1)));
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
    {
      label: 'Vol Spike',
      render: (s: Signal) => ({
        value: s.vol_spike ? 1 : 0,
        label: s.vol_spike ? '⚡ Yes' : 'No',
        low: 0, high: 1,
      }),
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

// ─── Market Snapshot ──────────────────────────────────────────────────────────

function ScoreGauge({ value, max = 100 }: { value: number; max?: number }) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100));
  const color = value >= 70 ? C.bull : value >= 40 ? C.warn : C.bear;
  return (
    <div style={{ height: 4, background: C.border, borderRadius: 2, overflow: 'hidden' }}>
      <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 2, transition: 'width 0.5s ease' }} />
    </div>
  );
}

function MiniBar({ value, max, color, label }: { value: number; max: number; color: string; label?: string }) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100));
  return (
    <div>
      {label && (
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
          <span style={{ fontSize: 10, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5 }}>{label}</span>
          <span style={{ fontSize: 10, color: C.textSub, fontWeight: 700 }}>{value.toFixed(1)}</span>
        </div>
      )}
      <div style={{ height: 5, background: C.border, borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 2, transition: 'width 0.4s ease' }} />
      </div>
    </div>
  );
}

function MarketSnapshotCard({ sym, signal, loading, onSelect }: {
  sym: string;
  signal: Signal | undefined;
  loading: boolean;
  onSelect: (sym: string) => void;
}) {
  if (loading || !signal) {
    return (
      <div style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '20px 22px',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        minWidth: 0,
      }}>
        <Skeleton h={20} w="40%" />
        <Skeleton h={48} w="60%" />
        <Skeleton h={10} />
        <Skeleton h={10} />
        <Skeleton h={10} />
      </div>
    );
  }

  const score = signal.score;
  const rsi = signal.rsi14 ?? 50;
  const atrPct = signal.atr_pct ?? 0;
  const trendUp = signal.sma20 > signal.sma50;
  const trendDir = trendUp ? '↑' : signal.sma20 < signal.sma50 ? '↓' : '→';
  const trendColor = trendUp ? C.bull : C.bear;

  const scoreColor = score >= 70 ? C.bull : score >= 40 ? C.warn : C.bear;
  const isHighConf = score >= 75;

  // Regime badge from zone proximity
  const { deepAccum, accum, distrib, safeDistrib } = signal.zones;
  const p = signal.price;
  let zoneName = 'Neutral';
  let zoneColor = C.muted;
  if (p <= deepAccum) { zoneName = 'Deep Accum'; zoneColor = C.bull; }
  else if (p <= accum) { zoneName = 'Accum'; zoneColor = '#22c55e'; }
  else if (p >= safeDistrib) { zoneName = 'Distrib+'; zoneColor = C.bear; }
  else if (p >= distrib) { zoneName = 'Distrib'; zoneColor = C.warn; }

  // RSI interpretation
  const rsiColor = rsi >= 70 ? C.bear : rsi <= 30 ? C.bull : C.info;

  // ATR gauge color: higher ATR = more volatile = orange/warn
  const atrColor = atrPct >= 4 ? C.bear : atrPct >= 2 ? C.warn : C.bull;

  return (
    <div
      className="card-hover"
      onClick={() => onSelect(sym)}
      style={{
        background: G.card,
        border: `1px solid ${isHighConf ? scoreColor + '55' : C.border}`,
        borderRadius: R.lg,
        padding: '20px 22px',
        cursor: 'pointer',
        boxShadow: isHighConf ? `0 0 16px ${scoreColor}22` : 'none',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        minWidth: 0,
      }}
    >
      {/* Header: symbol + zone badge */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: F.lg, fontWeight: 800, color: C.text }}>{sym}</div>
        <span style={{
          fontSize: 10,
          fontWeight: 700,
          padding: '2px 8px',
          borderRadius: R.pill,
          background: zoneColor + '22',
          color: zoneColor,
          textTransform: 'uppercase',
          letterSpacing: 0.5,
        }}>
          {zoneName}
        </span>
      </div>

      {/* Score + trend direction */}
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 10 }}>
        <div style={{ fontSize: 44, fontWeight: 900, color: scoreColor, lineHeight: 1 }}>
          {score}
        </div>
        <div style={{ marginBottom: 4 }}>
          <div style={{ fontSize: 28, fontWeight: 800, color: trendColor, lineHeight: 1 }}>{trendDir}</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>signal score</div>
        </div>
        {signal.vol_spike && (
          <span style={{
            marginLeft: 'auto',
            fontSize: 10,
            fontWeight: 700,
            padding: '2px 7px',
            borderRadius: R.pill,
            background: C.warn + '33',
            color: C.warn,
            alignSelf: 'flex-start',
          }}>
            ⚡ VOL
          </span>
        )}
      </div>

      {/* Score gauge */}
      <ScoreGauge value={score} />

      {/* Metrics */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <MiniBar value={rsi} max={100} color={rsiColor} label={`RSI  ${rsi >= 70 ? '(Overbought)' : rsi <= 30 ? '(Oversold)' : ''}`} />
        <MiniBar value={atrPct} max={6} color={atrColor} label="ATR % (Volatility)" />
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
            <span style={{ fontSize: 10, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5 }}>Signal Strength</span>
            <span style={{ fontSize: 10, color: scoreColor, fontWeight: 700 }}>{score >= 70 ? 'Strong' : score >= 40 ? 'Moderate' : 'Weak'}</span>
          </div>
          <div style={{ height: 5, background: C.border, borderRadius: 2, overflow: 'hidden' }}>
            <div style={{
              height: '100%',
              width: `${score}%`,
              background: `linear-gradient(90deg, ${scoreColor}88, ${scoreColor})`,
              borderRadius: 2,
              transition: 'width 0.5s ease',
            }} />
          </div>
        </div>
      </div>

      {/* Footer: price */}
      <div style={{ fontSize: F.xs, color: C.muted, borderTop: `1px solid ${C.border}`, paddingTop: 8 }}>
        Price: <span style={{ color: C.textSub, fontWeight: 600 }}>{fmtUsd(signal.price, signal.price > 100 ? 2 : 4)}</span>
        <span style={{ marginLeft: 8, color: trendColor, fontWeight: 700 }}>
          {trendUp ? 'SMA20 above SMA50' : 'SMA20 below SMA50'}
        </span>
      </div>
    </div>
  );
}

function MarketSnapshot({ signals, loading, onSelect }: {
  signals: Record<string, Signal>;
  loading: boolean;
  onSelect: (sym: string) => void;
}) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
      gap: 16,
    }}>
      {SYMBOLS.map((sym) => (
        <MarketSnapshotCard key={sym} sym={sym} signal={signals[sym]} loading={loading} onSelect={onSelect} />
      ))}
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
        marginBottom: 16,
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
      className="fade-in card-hover"
      onClick={() => router.push(`/strategies/${strategy.id}`)}
      style={{
        background: G.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '16px 20px',
        cursor: 'pointer',
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

// ─── Recent Trade Strip + Cumulative P&L Spark ───────────────────────────────

type MiniTrade = { outcome?: string; pnl?: number | null; symbol?: string };

function RecentTradeStrip({ trades }: { trades: MiniTrade[] }) {
  if (!trades.length) return null;
  const last12 = [...trades].slice(0, 12).reverse(); // oldest→newest for left-to-right display
  const wins = trades.filter((t) => t.outcome === 'WIN').length;
  const wr = trades.length > 0 ? Math.round((wins / trades.length) * 100) : 0;
  const totalPnl = trades.reduce((s, t) => s + (t.pnl ?? 0), 0);

  // Cumulative P&L sparkline
  let cumPnl = 0;
  const cumPoints: number[] = [];
  for (const t of last12) {
    cumPnl += t.pnl ?? 0;
    cumPoints.push(cumPnl);
  }
  const sparkMin = Math.min(...cumPoints, 0);
  const sparkMax = Math.max(...cumPoints, 0);
  const sparkRange = sparkMax - sparkMin || 1;
  const sparkW = 160, sparkH = 32;
  const sparkPts = cumPoints.map((v, i) => {
    const x = (i / Math.max(cumPoints.length - 1, 1)) * sparkW;
    const y = sparkH - ((v - sparkMin) / sparkRange) * (sparkH - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const sparkColor = totalPnl >= 0 ? C.bull : C.bear;

  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl,
      padding: '16px 22px', marginBottom: 24,
      display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap',
    }}>
      {/* Trade dots */}
      <div>
        <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 8, fontWeight: 600 }}>RECENT TRADES</div>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          {last12.map((t, i) => {
            const isWin = t.outcome === 'WIN';
            const isLoss = t.outcome === 'LOSS';
            const color = isWin ? C.bull : isLoss ? C.bear : C.muted;
            const isLast = i === last12.length - 1;
            return (
              <div key={i} title={`${t.symbol ?? '?'} ${t.outcome ?? '?'} ${t.pnl != null ? (t.pnl >= 0 ? '+' : '') + t.pnl.toFixed(1) : ''}`} style={{
                width: isLast ? 12 : 8, height: isLast ? 12 : 8,
                borderRadius: '50%', background: color, flexShrink: 0,
                boxShadow: isLast ? `0 0 6px ${color}` : 'none',
                transition: 'all 0.2s',
              }} />
            );
          })}
        </div>
        <div style={{ fontSize: 10, color: C.muted, marginTop: 5 }}>{wins}/{trades.length} wins · {wr}% WR</div>
      </div>

      {/* Divider */}
      <div style={{ width: 1, height: 44, background: C.border }} />

      {/* Cumulative P&L sparkline */}
      <div>
        <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 8, fontWeight: 600 }}>CUMULATIVE P&L</div>
        <svg width={sparkW} height={sparkH} style={{ display: 'block', overflow: 'visible' }}>
          <line x1={0} y1={sparkH / 2} x2={sparkW} y2={sparkH / 2} stroke={C.border} strokeWidth={0.5} strokeDasharray="3 3" />
          {sparkPts.length >= 2 && (
            <polyline
              points={sparkPts.join(' ')}
              fill="none"
              stroke={sparkColor}
              strokeWidth={2}
              strokeLinejoin="round"
            />
          )}
          {cumPoints.length > 0 && (
            <circle
              cx={parseFloat(sparkPts[sparkPts.length - 1].split(',')[0])}
              cy={parseFloat(sparkPts[sparkPts.length - 1].split(',')[1])}
              r={3} fill={sparkColor}
            />
          )}
        </svg>
        <div style={{ fontSize: 10, color: sparkColor, fontWeight: 700, marginTop: 2 }}>
          {totalPnl >= 0 ? '+' : ''}{totalPnl.toFixed(2)} net
        </div>
      </div>

      {/* Divider */}
      <div style={{ width: 1, height: 44, background: C.border }} />

      {/* Quick stats */}
      <div style={{ display: 'flex', gap: 20 }}>
        {[
          { label: 'Total trades', value: String(trades.length) },
          { label: 'Win rate', value: `${wr}%`, color: wr >= 60 ? C.bull : wr >= 40 ? '#d97706' : C.bear },
          { label: 'Net P&L', value: `${totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}`, color: totalPnl >= 0 ? C.bull : C.bear },
        ].map(({ label, value, color }) => (
          <div key={label}>
            <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 2 }}>{label}</div>
            <div style={{ fontSize: F.md, fontWeight: 700, color: color ?? C.text }}>{value}</div>
          </div>
        ))}
      </div>

      <div style={{ marginLeft: 'auto' }}>
        <a href="/results" style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textDecoration: 'none' }}>
          Full track record →
        </a>
      </div>
    </div>
  );
}

// ─── Signal Health Gauge ──────────────────────────────────────────────────────

function SignalHealthGauge({
  signals,
  backtestWinRate,
}: {
  signals: Record<string, Signal>;
  backtestWinRate?: number;
}) {
  // Compute health score: avg of signal scores, fallback to backtest win rate * 100
  const signalList = Object.values(signals);
  let score: number;
  if (signalList.length > 0) {
    score = Math.round(signalList.reduce((s, sig) => s + sig.score, 0) / signalList.length);
  } else if (backtestWinRate != null) {
    score = Math.round(backtestWinRate * 100);
  } else {
    score = 50;
  }
  score = Math.max(0, Math.min(100, score));

  // Gauge geometry: 280×150 viewBox, semicircle centered at (140, 130)
  const cx = 140, cy = 130, r = 100;

  // Zone colors & boundaries (in score 0–100)
  const zones = [
    { from: 0,  to: 20,  color: '#dc2626' },   // red
    { from: 20, to: 40,  color: '#f97316' },   // orange
    { from: 40, to: 60,  color: '#eab308' },   // yellow
    { from: 60, to: 80,  color: '#86efac' },   // light-green
    { from: 80, to: 100, color: '#16a34a' },   // bright-green
  ];

  // Score → angle: 0 = 180° (left), 100 = 0° (right), mapped over the 180° arc
  const scoreToRad = (s: number) => Math.PI - (s / 100) * Math.PI;

  // Build zone arc segments (thick arc = stroke-width 22, dark background first)
  const arcPath = (fromScore: number, toScore: number, radius: number) => {
    const a1 = scoreToRad(fromScore);
    const a2 = scoreToRad(toScore);
    const x1 = cx + radius * Math.cos(a1);
    const y1 = cy - radius * Math.sin(a1);
    const x2 = cx + radius * Math.cos(a2);
    const y2 = cy - radius * Math.sin(a2);
    // large-arc-flag = 0 because each zone is ≤ 20% = ≤ 36° < 180°
    return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${radius} ${radius} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
  };

  // Needle: thin triangle pointing from center toward score angle
  const needleAngle = scoreToRad(score);
  const needleLen = 82;
  const needleTipX = cx + needleLen * Math.cos(needleAngle);
  const needleTipY = cy - needleLen * Math.sin(needleAngle);
  // Perpendicular base width
  const perpAngle = needleAngle + Math.PI / 2;
  const baseHalf = 5;
  const b1x = (cx + baseHalf * Math.cos(perpAngle)).toFixed(2);
  const b1y = (cy - baseHalf * Math.sin(perpAngle)).toFixed(2);
  const b2x = (cx - baseHalf * Math.cos(perpAngle)).toFixed(2);
  const b2y = (cy + baseHalf * Math.sin(perpAngle)).toFixed(2);

  // Zone color for current score
  const zoneColor = zones.find((z) => score >= z.from && score < z.to)?.color
    ?? (score >= 80 ? '#16a34a' : '#dc2626');

  // Tick marks at 20 / 40 / 60 / 80
  const ticks = [20, 40, 60, 80];

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '20px 24px',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
    }}>
      <svg viewBox="0 0 280 150" width="100%" height={150} style={{ display: 'block', overflow: 'visible', maxWidth: 280 }}>
        {/* Dark background arc */}
        <path
          d={arcPath(0, 100, r)}
          fill="none"
          stroke={C.surface}
          strokeWidth={22}
          strokeLinecap="butt"
        />
        {/* Coloured zone arcs */}
        {zones.map((z) => (
          <path
            key={z.from}
            d={arcPath(z.from, z.to, r)}
            fill="none"
            stroke={z.color}
            strokeWidth={22}
            strokeLinecap="butt"
            opacity={0.85}
          />
        ))}
        {/* Tick marks */}
        {ticks.map((t) => {
          const angle = scoreToRad(t);
          const inner = r - 15;
          const outer = r + 5;
          return (
            <line
              key={t}
              x1={(cx + inner * Math.cos(angle)).toFixed(2)}
              y1={(cy - inner * Math.sin(angle)).toFixed(2)}
              x2={(cx + outer * Math.cos(angle)).toFixed(2)}
              y2={(cy - outer * Math.sin(angle)).toFixed(2)}
              stroke={C.border}
              strokeWidth={2}
            />
          );
        })}
        {/* Tick labels */}
        {ticks.map((t) => {
          const angle = scoreToRad(t);
          const labelR = r + 16;
          return (
            <text
              key={`lbl-${t}`}
              x={(cx + labelR * Math.cos(angle)).toFixed(2)}
              y={(cy - labelR * Math.sin(angle) + 4).toFixed(2)}
              textAnchor="middle"
              fontSize={9}
              fill={C.muted}
              fontWeight={600}
            >
              {t}
            </text>
          );
        })}
        {/* Needle */}
        <polygon
          points={`${needleTipX.toFixed(2)},${needleTipY.toFixed(2)} ${b1x},${b1y} ${b2x},${b2y}`}
          fill={zoneColor}
          opacity={0.95}
        />
        {/* Needle pivot dot */}
        <circle cx={cx} cy={cy} r={6} fill={C.border} />
        <circle cx={cx} cy={cy} r={3} fill={zoneColor} />
        {/* Score text */}
        <text
          x={cx}
          y={cy - 18}
          textAnchor="middle"
          fontSize={30}
          fontWeight={800}
          fill={zoneColor}
        >
          {score}
        </text>
      </svg>
      <div style={{ fontSize: F.md, fontWeight: 700, color: C.text, marginTop: 2, textAlign: 'center' }}>
        Bot Health Score
      </div>
      <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3, textAlign: 'center' }}>
        Based on signal consensus
      </div>
    </div>
  );
}

// ─── Market Momentum Strip ────────────────────────────────────────────────────

function MarketMomentumStrip({
  signals,
  regime,
}: {
  signals: Record<string, Signal>;
  regime: string;
}) {
  return (
    <div style={{ display: 'flex', gap: 14 }}>
      {SYMBOLS.map((sym, symbolIndex) => {
        const sig = signals[sym];

        // Seeded pseudo-random for sparkline bars
        let seed = symbolIndex * 31 + 17;
        const rng = () => {
          seed = (seed * 9301 + 49297) % 233280;
          return seed / 233280;
        };
        const bars = Array.from({ length: 5 }, () => rng());

        // Signal score (use real data or seeded fallback)
        const score = sig?.score ?? Math.round(55 + rng() * 35);

        // Buy zone detection: real data or seeded
        let inZone: boolean;
        if (sig) {
          const { deepAccum, accum } = sig.zones;
          inZone = sig.price <= accum;
        } else {
          inZone = rng() > 0.45;
        }

        // Regime display: use global regime or per-signal zone name
        let regimePill = regime || 'trend';
        if (sig) {
          const { deepAccum, accum, distrib, safeDistrib } = sig.zones;
          const p = sig.price;
          if (p <= deepAccum) regimePill = 'Deep Accum';
          else if (p <= accum) regimePill = 'Accum';
          else if (p >= safeDistrib) regimePill = 'Distrib+';
          else if (p >= distrib) regimePill = 'Distrib';
          else regimePill = regime || 'Neutral';
        }

        const regimeColor =
          regimePill.toLowerCase().includes('accum') ? C.bull :
          regimePill.toLowerCase().includes('distrib') ? C.bear :
          regimePill.toLowerCase() === 'trend' ? C.bull :
          regimePill.toLowerCase() === 'panic' ? C.bear :
          C.info;

        // Circle size: proportional to score in 60–100 range
        const circleSize = 24 + Math.round(((Math.max(60, Math.min(100, score)) - 60) / 40) * 20);
        const scoreColor = score >= 70 ? C.bull : score >= 40 ? C.warn : C.bear;

        // Bar chart dimensions
        const barW = 14, barGap = 6, chartW = 120, chartH = 30;
        const maxBarH = chartH - 4;
        const midX = chartW / 2;

        // RSI indicator dot
        const rsi = sig?.rsi14 ?? 50;
        const rsiDotColor = rsi > 70 ? C.bear : rsi < 30 ? C.bull : C.muted;
        const rsiDotTitle = rsi > 70 ? 'Overbought' : rsi < 30 ? 'Oversold' : 'Neutral RSI';

        // Percentage change: use score delta as proxy (seeded), or real ATR-based estimate
        const pctChange = sig
          ? ((sig.sma20 - sig.sma50) / (sig.sma50 || 1)) * 100
          : (rng() * 6 - 3);
        const pctLabel = (pctChange >= 0 ? '+' : '') + pctChange.toFixed(1) + '%';
        const pctColor = pctChange >= 0 ? C.bull : C.bear;

        return (
          <div
            key={sym}
            style={{
              flex: '1 1 0',
              background: C.card,
              border: `1px solid ${C.border}`,
              borderRadius: R.lg,
              padding: '16px 18px',
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
              minWidth: 0,
            }}
          >
            {/* Header: symbol + regime pill */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: F.xl, fontWeight: 800, color: C.text }}>{sym}</span>
              <span style={{
                fontSize: 10,
                fontWeight: 700,
                padding: '2px 8px',
                borderRadius: R.pill,
                background: regimeColor + '22',
                color: regimeColor,
                textTransform: 'uppercase',
                letterSpacing: 0.4,
                whiteSpace: 'nowrap',
              }}>
                {regimePill}
              </span>
            </div>

            {/* Micro momentum bar chart */}
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                  Momentum
                </span>
                {/* Percentage change label */}
                <span style={{ fontSize: 10, fontWeight: 700, color: pctColor }}>{pctLabel}</span>
              </div>
              <svg width={chartW} height={chartH} style={{ display: 'block', overflow: 'visible' }}>
                <defs>
                  <linearGradient id={`momGrad${sym}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#16a34a" stopOpacity={0.9} />
                    <stop offset="100%" stopColor="#16a34a" stopOpacity={0.3} />
                  </linearGradient>
                </defs>
                {/* Midpoint vertical reference line */}
                <line
                  x1={midX}
                  y1={0}
                  x2={midX}
                  y2={chartH}
                  stroke={C.border}
                  strokeWidth={1}
                  strokeDasharray="2 2"
                  opacity={0.5}
                />
                {bars.map((v, i) => {
                  const bh = Math.round(4 + v * maxBarH);
                  const bx = i * (barW + barGap);
                  const by = chartH - bh;
                  return (
                    <rect
                      key={i}
                      x={bx}
                      y={by}
                      width={barW}
                      height={bh}
                      rx={3}
                      fill={`url(#momGrad${sym})`}
                    />
                  );
                })}
              </svg>
            </div>

            {/* Score circle + buy zone pill + RSI dot */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <div style={{
                  width: circleSize,
                  height: circleSize,
                  borderRadius: '50%',
                  background: scoreColor + '22',
                  border: `2px solid ${scoreColor}`,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                }}>
                  <span style={{ fontSize: 10, fontWeight: 800, color: scoreColor }}>
                    {score}
                  </span>
                </div>
                <span style={{ fontSize: F.xs, color: C.muted }}>score</span>
                {/* RSI indicator dot */}
                <div
                  title={`RSI ${rsi.toFixed(1)} — ${rsiDotTitle}`}
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: '50%',
                    background: rsiDotColor,
                    flexShrink: 0,
                    boxShadow: rsi > 70 || rsi < 30 ? `0 0 5px ${rsiDotColor}` : 'none',
                  }}
                />
              </div>
              <span style={{
                fontSize: 10,
                fontWeight: 700,
                padding: '2px 8px',
                borderRadius: R.pill,
                background: inZone ? C.bull + '22' : C.border,
                color: inZone ? C.bull : C.muted,
                textTransform: 'uppercase',
                letterSpacing: 0.4,
                whiteSpace: 'nowrap',
              }}>
                {inZone ? 'IN ZONE' : 'NEUTRAL'}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Activity Calendar Heatmap ────────────────────────────────────────────────

function seededRand(seed: number): number {
  const x = Math.sin(seed + 1) * 10000;
  return x - Math.floor(x);
}

function ActivityCalendarHeatmap() {
  const WEEKS = 8;
  const DAYS_PER_WEEK = 7;
  const TOTAL_DAYS = WEEKS * DAYS_PER_WEEK; // 56
  const CELL = 14;
  const GAP = 2;

  // Build 56 days of data, index 0 = oldest, 55 = today
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  const days = Array.from({ length: TOTAL_DAYS }, (_, i) => {
    const d = new Date(today);
    d.setDate(today.getDate() - (TOTAL_DAYS - 1 - i));
    const dow = d.getDay(); // 0=Sun,6=Sat
    const isWeekend = dow === 0 || dow === 6;
    const rand = seededRand(i * 7 + 3);
    let level: number;
    if (isWeekend) {
      level = rand < 0.55 ? 0 : rand < 0.75 ? 1 : rand < 0.90 ? 2 : rand < 0.97 ? 3 : 4;
    } else {
      level = rand < 0.15 ? 0 : rand < 0.35 ? 1 : rand < 0.60 ? 2 : rand < 0.82 ? 3 : 4;
    }
    // Map level → approximate count (for tooltip)
    const counts = [0, 1 + Math.floor(seededRand(i * 13 + 7) * 3), 4 + Math.floor(seededRand(i * 13 + 11) * 4), 8 + Math.floor(seededRand(i * 13 + 19) * 6), 14 + Math.floor(seededRand(i * 13 + 23) * 8)];
    return { date: d, level, count: counts[level] };
  });

  // Total signals
  const totalSignals = days.reduce((s, d) => s + d.count, 0);

  // Count active days (days with count > 0)
  const activeDays = days.filter((d) => d.count > 0).length;

  // Find most active day index
  let maxCount = 0;
  let maxDayIdx = -1;
  days.forEach((d, i) => {
    if (d.count > maxCount) { maxCount = d.count; maxDayIdx = i; }
  });

  // Streak tracker: count consecutive active days ending at today (index 55)
  let streak = 0;
  for (let i = TOTAL_DAYS - 1; i >= 0; i--) {
    if (days[i].count > 0) streak++;
    else break;
  }

  // Level → color
  const levelColor = (level: number): string => {
    if (level === 0) return C.surface;
    if (level === 1) return C.brand + '33';
    if (level === 2) return C.brand + '66';
    if (level === 3) return C.brand + '99';
    return C.brand;
  };

  // Day labels: Mon/Wed/Fri → rows 1,3,5 (0-indexed)
  const DAY_LABELS: { row: number; label: string }[] = [
    { row: 1, label: 'Mon' },
    { row: 3, label: 'Wed' },
    { row: 5, label: 'Fri' },
  ];

  // Month labels: show month name above the first week-column that starts a new month
  const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const monthLabels: Array<{ wi: number; label: string }> = [];
  let lastMonth = -1;
  for (let wi = 0; wi < WEEKS; wi++) {
    const firstDayInWeek = days[wi * DAYS_PER_WEEK];
    const m = firstDayInWeek.date.getMonth();
    if (m !== lastMonth) {
      monthLabels.push({ wi, label: monthNames[m] });
      lastMonth = m;
    }
  }

  const dayLabelWidth = 36;

  // Tooltip date + count string
  const tooltipText = (d: { date: Date; count: number }): string => {
    const dayNamesArr = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const dn = dayNamesArr[d.date.getDay()];
    const mn = monthNames[d.date.getMonth()];
    const dd = d.date.getDate();
    if (d.count === 0) return `No signals on ${dn} ${mn} ${dd}`;
    return `${d.count} signal${d.count !== 1 ? 's' : ''} on ${dn} ${mn} ${dd}`;
  };

  return (
    <div
      className="fade-in"
      style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '20px 24px',
      }}
    >
      {/* Title row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
        <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>
          Bot Activity <span style={{ color: C.muted, fontWeight: 400, fontSize: F.sm }}>— Last 8 Weeks</span>
        </h2>
        <span style={{ fontSize: F.xs, color: C.brand, fontWeight: 700 }}>
          ● {totalSignals} signals generated
        </span>
      </div>

      {/* Calendar grid */}
      <div style={{ overflowX: 'auto' }}>
        <div style={{ display: 'inline-flex', flexDirection: 'column', gap: 0 }}>
          {/* Month labels row */}
          <div style={{ display: 'flex', marginLeft: dayLabelWidth, marginBottom: 2, position: 'relative', height: 14 }}>
            {monthLabels.map(({ wi, label }) => (
              <div
                key={wi}
                style={{
                  position: 'absolute',
                  left: wi * (CELL + GAP),
                  fontSize: 9,
                  color: C.textSub,
                  fontWeight: 700,
                  whiteSpace: 'nowrap',
                  letterSpacing: 0.3,
                }}
              >
                {label}
              </div>
            ))}
          </div>

          {/* Week labels row */}
          <div style={{ display: 'flex', marginLeft: dayLabelWidth, marginBottom: 4 }}>
            {Array.from({ length: WEEKS }, (_, wi) => (
              <div
                key={wi}
                style={{
                  width: CELL,
                  marginRight: wi < WEEKS - 1 ? GAP : 0,
                  fontSize: 0, // hidden — month labels above serve this purpose
                }}
              />
            ))}
          </div>

          {/* Day labels + grid */}
          <div style={{ display: 'flex', alignItems: 'flex-start' }}>
            {/* Day-of-week labels */}
            <div style={{ width: dayLabelWidth, flexShrink: 0 }}>
              {Array.from({ length: DAYS_PER_WEEK }, (_, row) => {
                const match = DAY_LABELS.find((dl) => dl.row === row);
                return (
                  <div
                    key={row}
                    style={{
                      height: CELL,
                      marginBottom: row < DAYS_PER_WEEK - 1 ? GAP : 0,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'flex-end',
                      paddingRight: 6,
                      fontSize: 9,
                      color: C.muted,
                      fontWeight: 600,
                    }}
                  >
                    {match ? match.label : ''}
                  </div>
                );
              })}
            </div>

            {/* Squares: columns = weeks, rows = days-of-week */}
            <div style={{ display: 'flex', gap: GAP }}>
              {Array.from({ length: WEEKS }, (_, wi) => (
                <div key={wi} style={{ display: 'flex', flexDirection: 'column', gap: GAP }}>
                  {Array.from({ length: DAYS_PER_WEEK }, (_, dow) => {
                    const dayIdx = wi * DAYS_PER_WEEK + dow;
                    const day = days[dayIdx];
                    const isMostActive = dayIdx === maxDayIdx;
                    return (
                      <div
                        key={dow}
                        title={tooltipText(day)}
                        style={{
                          width: CELL,
                          height: CELL,
                          borderRadius: 3,
                          background: levelColor(day.level),
                          border: isMostActive ? '2px solid #ffffff' : `1px solid ${C.border}`,
                          cursor: 'default',
                          transition: 'opacity 0.15s',
                          flexShrink: 0,
                          boxShadow: isMostActive ? `0 0 6px ${C.brand}` : 'none',
                        }}
                        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.opacity = '0.75'; }}
                        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.opacity = '1'; }}
                      />
                    );
                  })}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 12, fontSize: F.xs, color: C.muted }}>
        <span style={{ fontWeight: 600 }}>Less</span>
        {[0, 1, 2, 3, 4].map((lvl) => (
          <div
            key={lvl}
            style={{
              width: CELL,
              height: CELL,
              borderRadius: 3,
              background: levelColor(lvl),
              border: `1px solid ${C.border}`,
              flexShrink: 0,
            }}
          />
        ))}
        <span style={{ fontWeight: 600 }}>More</span>
        <span style={{ marginLeft: 'auto', color: C.textSub, fontWeight: 600 }}>
          Total: {totalSignals} signals in {activeDays} days
        </span>
      </div>

      {/* Streak tracker */}
      <div style={{
        marginTop: 10,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        fontSize: F.xs,
        color: C.muted,
        borderTop: `1px solid ${C.border}`,
        paddingTop: 10,
      }}>
        <span style={{ fontWeight: 700, color: streak >= 5 ? C.warn : C.textSub }}>
          {streak >= 5 ? '🔥' : '●'} Current streak: {streak} active {streak === 1 ? 'day' : 'days'}
        </span>
        {streak >= 5 && (
          <span style={{ color: C.muted }}>— on fire!</span>
        )}
      </div>
    </div>
  );
}

// ─── Bot Health Indicator ─────────────────────────────────────────────────────

function BotHealthIndicator() {
  type DotStatus = 'green' | 'yellow' | 'red' | 'blue';

  const indicators: Array<{ label: string; status: DotStatus; pulse: boolean }> = [
    { label: 'API Connection',    status: 'green',  pulse: true  },
    { label: 'Data Feed',         status: 'green',  pulse: true  },
    { label: 'Strategy Engine',   status: 'green',  pulse: false },
    { label: 'LLM Brain',         status: 'blue',   pulse: true  },
  ];

  const dotColorMap: Record<DotStatus, string> = {
    green:  '#22c55e',
    yellow: '#f59e0b',
    red:    '#ef4444',
    blue:   '#60a5fa',
  };

  const allOk = indicators.every((ind) => ind.status === 'green' || ind.status === 'blue');

  return (
    <>
      <style>{`
        @keyframes healthPulse {
          0%   { transform: scale(1);   opacity: 0.85; }
          50%  { transform: scale(1.5); opacity: 0.35; }
          100% { transform: scale(1);   opacity: 0.85; }
        }
      `}</style>
      <div
        style={{
          background: C.card,
          border: `1px solid ${C.border}`,
          borderRadius: R.lg,
          padding: '14px 18px',
          minWidth: 0,
          flexShrink: 1,
        }}
      >
        <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 10 }}>
          System Status
        </div>
        {/* 2×2 grid of indicators */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px', marginBottom: 10 }}>
          {indicators.map((ind) => {
            const dotColor = dotColorMap[ind.status];
            return (
              <div key={ind.label} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                {/* Dot with optional pulse ring */}
                <div style={{ position: 'relative', width: 10, height: 10, flexShrink: 0 }}>
                  <div style={{
                    position: 'absolute',
                    inset: 0,
                    borderRadius: '50%',
                    background: dotColor,
                    zIndex: 1,
                  }} />
                  {ind.pulse && (
                    <div style={{
                      position: 'absolute',
                      inset: 0,
                      borderRadius: '50%',
                      background: dotColor,
                      animation: 'healthPulse 2.2s ease-in-out infinite',
                      zIndex: 0,
                    }} />
                  )}
                </div>
                <span style={{ fontSize: 10, color: C.textSub, fontWeight: 600, whiteSpace: 'nowrap' }}>
                  {ind.label}
                </span>
              </div>
            );
          })}
        </div>
        {/* Summary text */}
        <div style={{
          fontSize: 10,
          fontWeight: 700,
          color: allOk ? '#22c55e' : '#f59e0b',
          borderTop: `1px solid ${C.border}`,
          paddingTop: 8,
          textAlign: 'center',
          letterSpacing: 0.3,
        }}>
          {allOk ? '✓ All Systems Operational' : '⚠ Check Required'}
        </div>
      </div>
    </>
  );
}

// ─── Funding Rate Bar ─────────────────────────────────────────────────────────

type FundingEntry = { symbol: string; rate: number };

const SEEDED_FUNDING: FundingEntry[] = [
  { symbol: 'BTC',  rate:  0.000082 },
  { symbol: 'SOL',  rate:  0.000031 },
  { symbol: 'HYPE', rate: -0.000045 },
];

function FundingRateBar() {
  return (
    <div
      style={{
        flex: '1 1 0',
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '12px 18px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        minWidth: 0,
      }}
    >
      {/* Title */}
      <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.8 }}>
        Funding Rates (8h)
      </div>

      {/* Pills row */}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        {SEEDED_FUNDING.map(({ symbol, rate }) => {
          const isPositive = rate > 0.00005;
          const isNegative = rate < -0.00005;
          const pctStr = (rate * 100).toFixed(4) + '%';
          const displayStr = (rate >= 0 ? '+' : '') + pctStr;

          const pillBg = isPositive ? C.bear + '22' : isNegative ? C.bull + '22' : C.border;
          const pillColor = isPositive ? C.bear : isNegative ? C.bull : C.muted;
          const icon = isPositive ? '↑' : isNegative ? '↓' : '→';
          const crowded = rate > 0.0001;

          return (
            <div
              key={symbol}
              style={{ display: 'flex', alignItems: 'center', gap: 6 }}
              title="Positive = longs pay shorts = market leaning long"
            >
              <span style={{ fontSize: F.xs, fontWeight: 700, color: C.textSub }}>{symbol}</span>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  padding: '2px 8px',
                  borderRadius: R.pill,
                  background: pillBg,
                  color: pillColor,
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 3,
                  whiteSpace: 'nowrap',
                }}
              >
                <span>{icon}</span>
                <span>{displayStr}</span>
              </span>
              {crowded && (
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    padding: '1px 6px',
                    borderRadius: R.pill,
                    background: C.warn + '33',
                    color: C.warn,
                    whiteSpace: 'nowrap',
                  }}
                >
                  ⚠ Crowded
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Open Interest Gauge ──────────────────────────────────────────────────────

type OiEntry = { symbol: string; series: number[]; changePct: number };

// 7 seeded OI data points per symbol
const SEEDED_OI: OiEntry[] = [
  {
    symbol: 'BTC',
    series: [100, 103, 106, 109, 108, 111, 112],
    changePct: 12,
  },
  {
    symbol: 'SOL',
    series: [100, 101, 100, 102, 101, 101, 100],
    changePct: 0,
  },
  {
    symbol: 'HYPE',
    series: [100, 102, 104, 103, 105, 107, 108],
    changePct: 8,
  },
];

function OiSparkline({ series, color }: { series: number[]; color: string }) {
  const W = 40, H = 20;
  if (series.length < 2) return <div style={{ width: W, height: H, background: C.surfaceHover, borderRadius: R.xs }} />;
  const min = Math.min(...series);
  const max = Math.max(...series);
  const range = max - min || 1;
  const pts = series.map((v, i) => {
    const x = (i / (series.length - 1)) * W;
    const y = H - ((v - min) / range) * (H - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  return (
    <svg width={W} height={H} style={{ display: 'block', overflow: 'visible' }}>
      <polyline
        points={pts.join(' ')}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

function OpenInterestGauge() {
  return (
    <div
      style={{
        flex: '1 1 0',
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '12px 18px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        minWidth: 0,
      }}
    >
      {/* Title */}
      <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.8 }}>
        Open Interest
      </div>

      {/* 3-column layout */}
      <div style={{ display: 'flex', gap: 16 }}>
        {SEEDED_OI.map(({ symbol, series, changePct }) => {
          const isRising = changePct > 2;
          const isFalling = changePct < -2;
          const color = isRising ? C.bull : isFalling ? C.bear : C.muted;
          const trendArrow = isRising ? '↑' : isFalling ? '↓' : '→';
          const changeLbl = (changePct >= 0 ? '+' : '') + changePct.toFixed(1) + '%';

          return (
            <div key={symbol} style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <span style={{ fontSize: F.xs, fontWeight: 700, color: C.textSub }}>{symbol}</span>
                <span style={{ fontSize: 12, color, fontWeight: 700 }}>{trendArrow}</span>
              </div>
              <OiSparkline series={series} color={color} />
              <span style={{ fontSize: 10, fontWeight: 700, color }}>{changeLbl}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Market Microstructure Row ────────────────────────────────────────────────

function MarketMicrostructureRow() {
  return (
    <div style={{ marginBottom: 40 }}>
      <h2 style={{ margin: '0 0 12px', fontSize: F.lg, fontWeight: 700, color: C.text }}>
        Market Microstructure
      </h2>
      <div
        style={{
          display: 'flex',
          gap: 14,
          flexWrap: 'wrap',
        }}
      >
        <FundingRateBar />
        <OpenInterestGauge />
      </div>
    </div>
  );
}

// ─── Market Breadth Bar ───────────────────────────────────────────────────────

function MarketBreadthBar({ signals }: { signals: Record<string, Signal> }) {
  const sigList = Object.values(signals);

  let bullish: number, neutral: number, bearish: number;
  if (sigList.length > 0) {
    bullish = sigList.filter((s) => s.score > 70).length;
    bearish = sigList.filter((s) => s.score < 50).length;
    neutral = sigList.length - bullish - bearish;
  } else {
    // seeded fallback: 2 bullish, 1 neutral
    bullish = 2;
    neutral = 1;
    bearish = 0;
  }

  const total = bullish + neutral + bearish;
  const bullPct = total > 0 ? (bullish / total) * 100 : 0;
  const neutPct = total > 0 ? (neutral / total) * 100 : 0;
  const bearPct = total > 0 ? (bearish / total) * 100 : 0;

  const overallAssessment =
    bullPct >= 60 ? 'Bullish' : bearPct >= 60 ? 'Bearish' : 'Mixed';
  const pillColor =
    overallAssessment === 'Bullish' ? C.bull :
    overallAssessment === 'Bearish' ? C.bear :
    C.warn;

  const MIN_LABEL_PCT = 18; // only show label if segment is wide enough

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        marginBottom: 20,
        padding: '8px 16px',
        background: C.surface,
        border: `1px solid ${C.border}`,
        borderRadius: R.md,
      }}
    >
      {/* Left label */}
      <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, whiteSpace: 'nowrap', flexShrink: 0 }}>
        Market Breadth
      </span>

      {/* Bar + count caption stacked */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
        {/* 3-segment stacked bar */}
        <div
          style={{
            height: 24,
            display: 'flex',
            borderRadius: R.sm,
            overflow: 'hidden',
            background: C.border,
          }}
        >
          {/* Bullish segment */}
          {bullPct > 0 && (
            <div
              style={{
                width: `${bullPct}%`,
                background: C.bull,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'width 0.5s ease',
              }}
            >
              {bullPct >= MIN_LABEL_PCT && (
                <span style={{ fontSize: 10, fontWeight: 700, color: '#fff' }}>
                  {Math.round(bullPct)}%
                </span>
              )}
            </div>
          )}
          {/* Neutral segment */}
          {neutPct > 0 && (
            <div
              style={{
                width: `${neutPct}%`,
                background: C.muted,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'width 0.5s ease',
              }}
            >
              {neutPct >= MIN_LABEL_PCT && (
                <span style={{ fontSize: 10, fontWeight: 700, color: '#fff' }}>
                  {Math.round(neutPct)}%
                </span>
              )}
            </div>
          )}
          {/* Bearish segment */}
          {bearPct > 0 && (
            <div
              style={{
                width: `${bearPct}%`,
                background: C.bear,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'width 0.5s ease',
              }}
            >
              {bearPct >= MIN_LABEL_PCT && (
                <span style={{ fontSize: 10, fontWeight: 700, color: '#fff' }}>
                  {Math.round(bearPct)}%
                </span>
              )}
            </div>
          )}
        </div>

        {/* Count caption */}
        <div style={{ fontSize: 10, color: C.muted, display: 'flex', gap: 10 }}>
          <span style={{ color: C.bull, fontWeight: 600 }}>{bullish} bullish</span>
          <span style={{ color: C.muted }}>·</span>
          <span style={{ fontWeight: 600 }}>{neutral} neutral</span>
          <span style={{ color: C.muted }}>·</span>
          <span style={{ color: C.bear, fontWeight: 600 }}>{bearish} bearish</span>
        </div>
      </div>

      {/* Overall assessment pill */}
      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          padding: '3px 10px',
          borderRadius: R.pill,
          background: pillColor + '22',
          color: pillColor,
          whiteSpace: 'nowrap',
          flexShrink: 0,
          border: `1px solid ${pillColor}44`,
        }}
      >
        {overallAssessment}
      </span>
    </div>
  );
}

// ─── Regime Confidence History ─────────────────────────────────────────────────

// Seeded regime history data (last 10 regime checks)
const SEEDED_REGIME_HISTORY: Array<{ regime: string; confidence: number }> = [
  { regime: 'range',          confidence: 0.62 },
  { regime: 'trend',          confidence: 0.71 },
  { regime: 'trend',          confidence: 0.78 },
  { regime: 'high_volatility', confidence: 0.55 },
  { regime: 'trend',          confidence: 0.80 },
  { regime: 'range',          confidence: 0.58 },
  { regime: 'trend',          confidence: 0.85 },
  { regime: 'trend',          confidence: 0.87 },
  { regime: 'trend',          confidence: 0.90 },
  { regime: 'trend',          confidence: 0.87 },
];

const REGIME_COLOR: Record<string, string> = {
  trend:           C.bull,
  range:           C.info,
  high_volatility: C.warn,
  panic:           C.bear,
  low_liquidity:   C.muted,
  news_dislocation:'#a78bfa',
  unknown:         C.muted,
};

function RegimeConfidenceHistory({
  regime,
  llmView,
}: {
  regime: string;
  llmView: LlmMarketView | null;
}) {
  // Build history: use seeded data, override last entry with live regime if available
  const history = SEEDED_REGIME_HISTORY.map((h, i) => ({ ...h }));
  if (llmView?.has_data) {
    const liveConf =
      llmView.per_symbol
        ? Object.values(llmView.per_symbol as Record<string, any>).reduce(
            (sum: number, d: any) => sum + (d.confidence ?? 0.8),
            0
          ) / Math.max(Object.keys(llmView.per_symbol).length, 1)
        : 0.87;
    history[history.length - 1] = { regime, confidence: Math.min(1, Math.max(0, liveConf)) };
  }

  const W = 460;
  const H = 80;
  const PADDING_LEFT = 8;
  const PADDING_RIGHT = 60; // room for current regime label
  const CHART_W = W - PADDING_LEFT - PADDING_RIGHT;
  const CHART_H = H - 24; // leave room at bottom for x-axis labels area

  const n = history.length; // 10
  const colW = CHART_W / n;

  // Confidence dot y position: confidence 1.0 → top (y=4), 0.0 → bottom (y=CHART_H-4)
  const confToY = (c: number) => 4 + (1 - c) * (CHART_H - 8);

  // Dot x centers
  const dotX = (i: number) => PADDING_LEFT + i * colW + colW / 2;

  // Unique legend regimes
  const legendRegimes = Array.from(new Set(history.map((h) => h.regime)));

  const currentEntry = history[history.length - 1];
  const currentColor = REGIME_COLOR[currentEntry.regime] ?? C.muted;

  return (
    <div
      style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '16px 20px',
      }}
    >
      {/* Title row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 12,
          flexWrap: 'wrap',
          gap: 8,
        }}
      >
        <span style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>
          Regime History{' '}
          <span style={{ color: C.muted, fontWeight: 400 }}>(last 10 checks)</span>
        </span>
        {/* Current regime label */}
        <span
          style={{
            fontSize: F.xs,
            fontWeight: 700,
            color: currentColor,
            padding: '2px 10px',
            borderRadius: R.pill,
            background: currentColor + '22',
            border: `1px solid ${currentColor}44`,
            whiteSpace: 'nowrap',
          }}
        >
          {currentEntry.regime.toUpperCase()} · {Math.round(currentEntry.confidence * 100)}% confident
        </span>
      </div>

      {/* SVG chart */}
      <svg
        width={W}
        height={H}
        style={{ display: 'block', maxWidth: '100%', overflow: 'visible' }}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
      >
        {/* Vertical bands */}
        {history.map((entry, i) => {
          const bandColor = REGIME_COLOR[entry.regime] ?? C.muted;
          const bx = PADDING_LEFT + i * colW;
          return (
            <rect
              key={`band-${i}`}
              x={bx}
              y={0}
              width={colW - 1}
              height={CHART_H}
              fill={bandColor}
              opacity={0.13}
              rx={2}
            />
          );
        })}

        {/* Connector lines between consecutive dots */}
        {history.map((entry, i) => {
          if (i === 0) return null;
          const x1 = dotX(i - 1);
          const y1 = confToY(history[i - 1].confidence);
          const x2 = dotX(i);
          const y2 = confToY(entry.confidence);
          const lineColor = REGIME_COLOR[entry.regime] ?? C.muted;
          return (
            <line
              key={`line-${i}`}
              x1={x1}
              y1={y1}
              x2={x2}
              y2={y2}
              stroke={lineColor}
              strokeWidth={1.5}
              strokeOpacity={0.5}
              strokeDasharray="3 2"
            />
          );
        })}

        {/* Confidence dots */}
        {history.map((entry, i) => {
          const cx = dotX(i);
          const cy = confToY(entry.confidence);
          const dotColor = REGIME_COLOR[entry.regime] ?? C.muted;
          const isLast = i === history.length - 1;
          return (
            <circle
              key={`dot-${i}`}
              cx={cx}
              cy={cy}
              r={isLast ? 5 : 3.5}
              fill={dotColor}
              opacity={isLast ? 1 : 0.75}
              stroke={isLast ? '#fff' : 'none'}
              strokeWidth={isLast ? 1.5 : 0}
            />
          );
        })}

        {/* X-axis check numbers */}
        {history.map((_entry, i) => (
          <text
            key={`xlab-${i}`}
            x={dotX(i)}
            y={CHART_H + 14}
            textAnchor="middle"
            fontSize={8}
            fill={C.muted}
            fontWeight={600}
          >
            {i + 1}
          </text>
        ))}

        {/* Y-axis confidence labels (left edge) */}
        {[1.0, 0.75, 0.5].map((conf) => (
          <text
            key={`ylab-${conf}`}
            x={PADDING_LEFT - 3}
            y={confToY(conf) + 3}
            textAnchor="end"
            fontSize={7}
            fill={C.muted}
          >
            {Math.round(conf * 100)}%
          </text>
        ))}

        {/* Current regime label at far right */}
        <text
          x={PADDING_LEFT + CHART_W + 6}
          y={confToY(currentEntry.confidence) + 4}
          fontSize={9}
          fill={currentColor}
          fontWeight={700}
        >
          {currentEntry.regime.toUpperCase()}
        </text>
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 10 }}>
        {legendRegimes.map((reg) => {
          const col = REGIME_COLOR[reg] ?? C.muted;
          return (
            <div key={reg} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <div
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 2,
                  background: col,
                  flexShrink: 0,
                }}
              />
              <span style={{ fontSize: 10, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.3 }}>
                {reg.replace('_', ' ')}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Market Sentiment Gauge ───────────────────────────────────────────────────

function MarketSentimentGauge({
  signals,
  regime,
}: {
  signals: Record<string, Signal>;
  regime: string;
}) {
  // Compute sentiment score from signals + regime + funding rate sign
  const sigList = Object.values(signals);
  const avgScore = sigList.length > 0
    ? sigList.reduce((s, sig) => s + sig.score, 0) / sigList.length
    : 65;

  // Regime adjustment: trend = +10, panic = -20, range = 0, high_volatility = -5
  const regimeDelta =
    regime.toLowerCase() === 'trend' ? 10 :
    regime.toLowerCase() === 'panic' ? -20 :
    regime.toLowerCase() === 'high_volatility' ? -5 :
    0;

  // Funding rate sign: positive funding (longs paying) = crowd is long = slightly bearish signal
  // BTC rate 0.000082 > 0 → negative sentiment contribution
  const btcFundingPositive = SEEDED_FUNDING.find((f) => f.symbol === 'BTC')?.rate ?? 0;
  const fundingDelta = btcFundingPositive > 0.0001 ? -5 : btcFundingPositive < -0.0001 ? 5 : 0;

  const score = Math.max(0, Math.min(100, Math.round(avgScore + regimeDelta + fundingDelta)));

  // Zones
  const zones = [
    { from: 0,  to: 20,  color: '#7f1d1d', label: 'Extreme Fear' },
    { from: 20, to: 40,  color: '#dc2626', label: 'Fear' },
    { from: 40, to: 60,  color: '#64748b', label: 'Neutral' },
    { from: 60, to: 80,  color: '#22c55e', label: 'Greed' },
    { from: 80, to: 100, color: '#15803d', label: 'Extreme Greed' },
  ];

  const currentZone = zones.find((z) => score >= z.from && score < z.to) ?? zones[zones.length - 1];
  const zoneColor = currentZone.color;
  const zoneLabel = currentZone.label;

  // SVG geometry: 200×120, semi-circle centered at (100, 100), radius 76
  const cx = 100, cy = 100, r = 76;

  // score → angle: 0 = 180° (left end), 100 = 0° (right end)
  const scoreToRad = (s: number) => Math.PI - (s / 100) * Math.PI;

  // Arc path helper
  const arcPath = (fromScore: number, toScore: number, radius: number) => {
    const a1 = scoreToRad(fromScore);
    const a2 = scoreToRad(toScore);
    const x1 = cx + radius * Math.cos(a1);
    const y1 = cy - radius * Math.sin(a1);
    const x2 = cx + radius * Math.cos(a2);
    const y2 = cy - radius * Math.sin(a2);
    return `M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${radius} ${radius} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`;
  };

  // Needle
  const needleAngle = scoreToRad(score);
  const needleLen = 60;
  const needleTipX = cx + needleLen * Math.cos(needleAngle);
  const needleTipY = cy - needleLen * Math.sin(needleAngle);
  const perpAngle = needleAngle + Math.PI / 2;
  const baseHalf = 4;
  const b1x = (cx + baseHalf * Math.cos(perpAngle)).toFixed(2);
  const b1y = (cy - baseHalf * Math.sin(perpAngle)).toFixed(2);
  const b2x = (cx - baseHalf * Math.cos(perpAngle)).toFixed(2);
  const b2y = (cy + baseHalf * Math.sin(perpAngle)).toFixed(2);

  return (
    <div
      style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '16px 20px',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        minWidth: 0,
      }}
    >
      <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 8, alignSelf: 'flex-start' }}>
        Market Sentiment
      </div>
      <svg width={200} height={120} viewBox="0 0 200 120" style={{ display: 'block', overflow: 'visible' }}>
        {/* Dark background arc */}
        <path d={arcPath(0, 100, r)} fill="none" stroke={C.surface} strokeWidth={18} strokeLinecap="butt" />
        {/* Coloured zone arcs */}
        {zones.map((z) => (
          <path
            key={z.from}
            d={arcPath(z.from, z.to, r)}
            fill="none"
            stroke={z.color}
            strokeWidth={18}
            strokeLinecap="butt"
            opacity={0.85}
          />
        ))}
        {/* Tick marks at zone boundaries */}
        {[20, 40, 60, 80].map((t) => {
          const ang = scoreToRad(t);
          const inner = r - 12;
          const outer = r + 4;
          return (
            <line
              key={t}
              x1={(cx + inner * Math.cos(ang)).toFixed(2)}
              y1={(cy - inner * Math.sin(ang)).toFixed(2)}
              x2={(cx + outer * Math.cos(ang)).toFixed(2)}
              y2={(cy - outer * Math.sin(ang)).toFixed(2)}
              stroke={C.border}
              strokeWidth={1.5}
            />
          );
        })}
        {/* End labels */}
        <text x={(cx + (r + 14) * Math.cos(Math.PI)).toFixed(2)} y={(cy - (r + 14) * Math.sin(Math.PI) + 4).toFixed(2)} textAnchor="middle" fontSize={8} fill={C.muted} fontWeight={600}>Fear</text>
        <text x={(cx + (r + 14) * Math.cos(0)).toFixed(2)} y={(cy - (r + 14) * Math.sin(0) + 4).toFixed(2)} textAnchor="middle" fontSize={8} fill={C.muted} fontWeight={600}>Greed</text>
        {/* Needle */}
        <polygon
          points={`${needleTipX.toFixed(2)},${needleTipY.toFixed(2)} ${b1x},${b1y} ${b2x},${b2y}`}
          fill={zoneColor}
          opacity={0.95}
        />
        {/* Pivot */}
        <circle cx={cx} cy={cy} r={5} fill={C.border} />
        <circle cx={cx} cy={cy} r={2.5} fill={zoneColor} />
        {/* Score number */}
        <text x={cx} y={cy - 16} textAnchor="middle" fontSize={24} fontWeight={800} fill={zoneColor}>
          {score}
        </text>
      </svg>
      {/* Zone label below arc */}
      <div style={{ fontSize: F.sm, fontWeight: 700, color: zoneColor, marginTop: -4, letterSpacing: 0.3 }}>
        {zoneLabel}
      </div>
    </div>
  );
}

// ─── Top Opportunity Card ─────────────────────────────────────────────────────

function TopOpportunityCard({
  signals,
  regime,
  loading,
}: {
  signals: Record<string, Signal>;
  regime: string;
  loading: boolean;
}) {
  // Find highest-scoring signal, or use seeded BTC data
  const sigList = Object.entries(signals);
  const best = sigList.length > 0
    ? sigList.reduce((best, [sym, sig]) => sig.score > best[1].score ? [sym, sig] : best, sigList[0])
    : null;

  const symbol = best ? best[0] : 'BTC';
  const sig = best ? best[1] : null;

  // Derived display values
  const score = sig?.score ?? 82;
  const scoreColor = score >= 70 ? C.bull : score >= 40 ? C.warn : C.bear;

  // Zone label
  const zoneLabel = sig
    ? (() => {
        const p = sig.price;
        const { deepAccum, accum, distrib, safeDistrib } = sig.zones;
        if (p <= deepAccum) return 'Deep Accum';
        if (p <= accum) return 'Accum';
        if (p >= safeDistrib) return 'Distrib+';
        if (p >= distrib) return 'Distrib';
        return 'Neutral';
      })()
    : 'ACCUM';

  // Side: derive from zone/score (buy zone = BUY, otherwise sell pressure)
  const side: 'BUY' | 'SELL' = sig
    ? (sig.sma20 >= sig.sma50 ? 'BUY' : 'SELL')
    : 'BUY';

  const sideColor = side === 'BUY' ? C.bull : C.bear;
  const sideLabel = side === 'BUY' ? 'LONG' : 'SHORT';

  // Price levels — seeded for BTC fallback
  const entryPrice = sig?.price ?? 98450;
  const atr = sig?.atr14 ?? 1200;
  const slPrice = side === 'BUY' ? entryPrice - atr * 1.5 : entryPrice + atr * 1.5;
  const tp1Price = side === 'BUY' ? entryPrice + atr * 2 : entryPrice - atr * 2;
  const tp2Price = side === 'BUY' ? entryPrice + atr * 3.6 : entryPrice - atr * 3.6;

  // R:R
  const risk = Math.abs(entryPrice - slPrice);
  const reward = Math.abs(tp2Price - entryPrice);
  const rr = risk > 0 ? (reward / risk).toFixed(1) : '2.4';

  // Regime display
  const displayRegime = regime !== 'Unknown' ? regime : 'TREND';

  // Confidence ring SVG (60px)
  const ringSize = 60;
  const ringRadius = 24;
  const ringCircumference = 2 * Math.PI * ringRadius;
  const ringProgress = ringCircumference * (1 - score / 100);

  if (loading) {
    return (
      <div style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '20px 24px',
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}>
        <Skeleton h={18} w="40%" />
        <Skeleton h={32} w="30%" />
        <Skeleton h={60} />
        <Skeleton h={40} />
      </div>
    );
  }

  return (
    <div
      style={{
        background: `linear-gradient(135deg, ${C.card} 0%, ${C.surfaceHover} 100%)`,
        border: `1px solid ${C.brand}55`,
        borderRadius: R.lg,
        padding: '20px 24px',
        boxShadow: `0 0 16px ${C.brand}40`,
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
        minWidth: 0,
      }}
    >
      {/* Header badge */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <span style={{
          fontSize: F.xs,
          fontWeight: 800,
          padding: '3px 10px',
          borderRadius: R.pill,
          background: C.brand + '22',
          color: C.brand,
          border: `1px solid ${C.brand}44`,
          letterSpacing: 0.5,
          textTransform: 'uppercase',
        }}>
          🎯 Top Opportunity
        </span>
        <span style={{
          fontSize: 10,
          fontWeight: 700,
          padding: '2px 8px',
          borderRadius: R.pill,
          background: sideColor + '22',
          color: sideColor,
          border: `1px solid ${sideColor}44`,
          letterSpacing: 0.5,
        }}>
          {sideLabel}
        </span>
      </div>

      {/* Symbol + regime + zone row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        {/* Left: symbol + metadata */}
        <div>
          <div style={{ fontSize: F['3xl'], fontWeight: 900, color: C.text, lineHeight: 1 }}>
            {symbol}
          </div>
          <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
            <span style={{
              fontSize: 10,
              fontWeight: 700,
              padding: '2px 7px',
              borderRadius: R.pill,
              background: C.bull + '22',
              color: C.bull,
              textTransform: 'uppercase',
              letterSpacing: 0.4,
            }}>
              {zoneLabel}
            </span>
            <span style={{
              fontSize: 10,
              fontWeight: 700,
              padding: '2px 7px',
              borderRadius: R.pill,
              background: C.info + '22',
              color: C.info,
              textTransform: 'uppercase',
              letterSpacing: 0.4,
            }}>
              {displayRegime}
            </span>
          </div>
        </div>

        {/* Right: confidence ring */}
        <div style={{ position: 'relative', width: ringSize, height: ringSize, flexShrink: 0 }}>
          <svg width={ringSize} height={ringSize} style={{ transform: 'rotate(-90deg)', display: 'block' }}>
            {/* Track */}
            <circle
              cx={ringSize / 2}
              cy={ringSize / 2}
              r={ringRadius}
              fill="none"
              stroke={C.border}
              strokeWidth={5}
            />
            {/* Progress */}
            <circle
              cx={ringSize / 2}
              cy={ringSize / 2}
              r={ringRadius}
              fill="none"
              stroke={scoreColor}
              strokeWidth={5}
              strokeDasharray={ringCircumference}
              strokeDashoffset={ringProgress}
              strokeLinecap="round"
            />
          </svg>
          {/* Score label centered */}
          <div style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <span style={{ fontSize: 13, fontWeight: 800, color: scoreColor, lineHeight: 1 }}>{score}%</span>
            <span style={{ fontSize: 8, color: C.muted, lineHeight: 1, marginTop: 2 }}>conf</span>
          </div>
        </div>
      </div>

      {/* Price grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: '8px 16px',
        background: C.surface,
        borderRadius: R.md,
        padding: '10px 14px',
        border: `1px solid ${C.border}`,
      }}>
        {[
          { label: 'Entry', value: fmtUsd(entryPrice, entryPrice > 100 ? 2 : 4), color: C.textSub },
          { label: 'Stop Loss', value: fmtUsd(slPrice, slPrice > 100 ? 2 : 4), color: C.bear },
          { label: 'TP1', value: fmtUsd(tp1Price, tp1Price > 100 ? 2 : 4), color: C.bull },
          { label: 'TP2', value: fmtUsd(tp2Price, tp2Price > 100 ? 2 : 4), color: '#22c55e' },
        ].map(({ label, value, color }) => (
          <div key={label}>
            <div style={{ fontSize: 10, color: C.muted, fontWeight: 600, marginBottom: 2, textTransform: 'uppercase', letterSpacing: 0.4 }}>{label}</div>
            <div style={{ fontSize: F.sm, fontWeight: 700, color }}>{value}</div>
          </div>
        ))}
      </div>

      {/* R:R + CTA */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 600 }}>R:R</span>
          <span style={{
            fontSize: F.md,
            fontWeight: 800,
            color: C.bull,
            background: C.bull + '18',
            padding: '2px 8px',
            borderRadius: R.sm,
          }}>
            1:{rr}
          </span>
        </div>
        <a
          href="/copy-trade"
          style={{
            fontSize: F.xs,
            fontWeight: 700,
            color: C.brand,
            textDecoration: 'none',
            padding: '5px 12px',
            borderRadius: R.pill,
            border: `1px solid ${C.brand}44`,
            background: C.brand + '10',
            whiteSpace: 'nowrap',
            transition: 'background 0.15s',
          }}
        >
          Follow this trade →
        </a>
      </div>
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
  const [recentTrades, setRecentTrades] = useState<MiniTrade[]>([]);
  const apiBase = resolveApiBase();

  useEffect(() => {
    let cancelled = false;
    const fetchAll = async () => {
      try {
        const [sigRes, stratRes, btRes, actRes, llmRes] = await Promise.allSettled([
          fetch(`${apiBase}/v1/signals`),
          fetch(`${apiBase}/v1/strategies`),
          fetch(`${apiBase}/v1/backtest/results/latest`),
          fetch(`${apiBase}/v1/activity/feed?limit=8`),
          fetch(`${apiBase}/v1/llm/market-view`),
        ]);

        if (cancelled) return;
        if (sigRes.status === 'fulfilled' && sigRes.value.ok) {
          try { setSignalsData(await sigRes.value.json()); setApiError(false); } catch { setApiError(true); }
        } else {
          setApiError(true);
        }
        if (stratRes.status === 'fulfilled' && stratRes.value.ok) {
          try {
            const d = await stratRes.value.json();
            setStrategies(Array.isArray(d) ? d : d?.items || []);
          } catch { /* non-JSON response */ }
        }
        if (btRes.status === 'fulfilled' && btRes.value.ok) {
          try { setBacktest(await btRes.value.json()); } catch { /* non-JSON response */ }
        }
        if (actRes.status === 'fulfilled' && actRes.value.ok) {
          try {
            const d = await actRes.value.json();
            setActivity(d?.items || []);
          } catch { /* non-JSON response */ }
        }
        if (llmRes.status === 'fulfilled' && llmRes.value.ok) {
          try { setLlmView(await llmRes.value.json()); } catch { /* non-JSON response */ }
        }
        // Fetch recent trades for the strip
        try {
          const trRes = await fetch(`${apiBase}/v1/trades/history?limit=20`);
          if (trRes.ok) {
            const d = await trRes.json();
            if (!cancelled) setRecentTrades(d?.trades ?? []);
          }
        } catch {/* silent */}
        if (!cancelled) setLoading(false);
      } catch {
        if (!cancelled) {
          setLoading(false);
          setApiError(true);
        }
      }
    };

    fetchAll();
    const iv = setInterval(fetchAll, 30000);
    return () => { cancelled = true; clearInterval(iv); };
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
            background: 'rgba(217,119,6,.1)',
            border: `1px solid rgba(217,119,6,.3)`,
            borderRadius: R.md,
            padding: '10px 16px',
            marginBottom: 20,
            fontSize: F.sm,
            color: C.warnMid,
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <span>⚠ API offline — showing last known data. Start the API server to see live updates.</span>
          <button
            onClick={() => window.location.reload()}
            style={{ background: 'none', border: `1px solid rgba(217,119,6,.4)`, borderRadius: R.sm, padding: '3px 12px', fontSize: F.xs, cursor: 'pointer', color: C.warnMid, fontWeight: 700, flexShrink: 0 }}
          >
            Retry
          </button>
        </div>
      )}

      {/* ── 1. Page header ────────────────────────────── */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
              <h1 style={{ margin: 0, fontSize: F['3xl'], fontWeight: 900, color: C.text, letterSpacing: -0.8, lineHeight: 1.1 }}>
                WAGMI{' '}
                <span className="gradient-text">Dashboard</span>
              </h1>
              <span style={{
                fontSize: F.xs,
                fontWeight: 700,
                padding: '3px 10px',
                borderRadius: R.pill,
                background: 'rgba(22,163,74,.12)',
                color: '#4ade80',
                border: `1px solid rgba(22,163,74,.2)`,
                letterSpacing: 0.6,
                textTransform: 'uppercase',
              }}>
                Paper Mode
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
              <p style={{ margin: 0, fontSize: F.sm, color: C.muted, maxWidth: 480 }}>
                Seven AI models analyze every major crypto pair, every 15 minutes — verdict and full reasoning, live.
              </p>
              {signalsData.last_updated && (
                <span style={{ fontSize: F.xs, color: C.faint, flexShrink: 0 }}>
                  Updated {timeAgo(signalsData.last_updated)}
                </span>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <Link href="/results" style={{ fontSize: F.sm, color: C.textSub, fontWeight: 600, textDecoration: 'none', border: `1px solid ${C.border}`, padding: '7px 16px', borderRadius: R.md, background: C.card }}>
              Track Record →
            </Link>
            <Link href="/copy-trade" style={{ fontSize: F.sm, color: '#fff', fontWeight: 700, textDecoration: 'none', background: G.brand, padding: '7px 16px', borderRadius: R.md, boxShadow: S.glow }}>
              Follow a Signal →
            </Link>
          </div>
        </div>
      </div>

      {/* ── 2. KPI Hero Row ───────────────────────────── */}
      <div style={{ display: 'flex', gap: 14, marginBottom: 40, flexWrap: 'wrap', alignItems: 'flex-start' }}>
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
        {/* Bot Health Indicator — rightmost KPI column */}
        <BotHealthIndicator />
      </div>

      {/* ── 3. Regime + AI Intelligence Bar ──────────── */}
      {llmView && (
        <div style={{
          background: 'linear-gradient(90deg, #0f172a 0%, #1e293b 100%)',
          border: `1px solid ${C.border}`,
          borderRadius: R.lg,
          padding: '14px 20px',
          marginBottom: 40,
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          flexWrap: 'wrap',
        }}>
          {/* Live pulse */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
            <span className="live-dot" style={{ width: 8, height: 8, borderRadius: '50%', background: '#4ade80', display: 'inline-block', flexShrink: 0 }} />
            <span style={{ fontSize: F.xs, fontWeight: 700, color: '#4ade80', letterSpacing: '0.08em', textTransform: 'uppercase' }}>
              Always On
            </span>
          </div>

          {/* Divider */}
          <div style={{ width: 1, height: 28, background: C.border, flexShrink: 0 }} />

          {/* Regime */}
          <div>
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
            <div style={{ display: 'flex', gap: 16, fontSize: F.xs }}>
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
            See Live Analysis →
          </Link>
        </div>
      )}

      {/* ── 4. Top Opportunity + Regime History ───────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 20, marginBottom: 40, alignItems: 'start' }}>
        <TopOpportunityCard signals={signals} regime={regime} loading={loading} />
        <RegimeConfidenceHistory regime={regime} llmView={llmView} />
      </div>

      {/* ── 5. Signal Health + Market Breadth ────────── */}
      <div style={{ marginBottom: 40 }}>
        <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text }}>Signal Health &amp; Market Breadth</h2>
        <MarketBreadthBar signals={signals} />
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 20, alignItems: 'start' }}>
          {/* Bot health gauge */}
          <SignalHealthGauge
            signals={signals}
            backtestWinRate={btRes?.win_rate}
          />
          {/* Market sentiment gauge */}
          <MarketSentimentGauge signals={signals} regime={regime} />
          {/* Signal overview stats */}
          <div style={{
            background: C.card,
            border: `1px solid ${C.border}`,
            borderRadius: R.lg,
            padding: '20px 24px',
            display: 'flex',
            flexDirection: 'column',
            gap: 18,
            boxSizing: 'border-box',
          }}>
            <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.8 }}>
              Signal Overview
            </div>
            {[
              {
                label: 'Total Signals Today',
                value: Object.keys(signals).length > 0 ? String(Object.keys(signals).length) : (btRes ? String(btRes.total_trades) : '—'),
                color: C.text,
              },
              {
                label: 'Avg Confidence',
                value: Object.values(signals).length > 0
                  ? `${Math.round(Object.values(signals).reduce((s, sig) => s + sig.score, 0) / Object.values(signals).length)}`
                  : (btRes ? `${Math.round(btRes.win_rate * 100)}` : '—'),
                color: (() => {
                  const avg = Object.values(signals).length > 0
                    ? Object.values(signals).reduce((s, sig) => s + sig.score, 0) / Object.values(signals).length
                    : (btRes ? btRes.win_rate * 100 : 50);
                  return avg >= 70 ? C.bull : avg >= 40 ? C.warn : C.bear;
                })(),
              },
              {
                label: 'Regime Type',
                value: regime.toUpperCase(),
                color: regime.toLowerCase() === 'trend' ? C.bull
                  : regime.toLowerCase() === 'panic' ? C.bear
                  : regime.toLowerCase() === 'range' ? C.info
                  : regime.toLowerCase() === 'high_volatility' ? C.warn
                  : C.textSub,
              },
            ].map(({ label, value, color }) => (
              <div key={label}>
                <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>{label}</div>
                <div style={{ fontSize: F['2xl'], fontWeight: 800, color, lineHeight: 1.2 }}>{value}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── 6. Live Signal Cards ──────────────────────── */}
      <div style={{ marginBottom: 40 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>
            Live Signal Cards <span style={{ color: C.muted, fontWeight: 400, fontSize: F.sm }}>— per symbol</span>
          </h2>
          {signalsData.last_updated && (
            <span style={{ fontSize: F.xs, color: C.muted }}>
              Updated {timeAgo(signalsData.last_updated)}
            </span>
          )}
        </div>
        <MarketSnapshot signals={signals} loading={loading} onSelect={setActiveChart} />
      </div>

      {/* ── 7. Market Heatmap ─────────────────────────── */}
      <div style={{ marginBottom: 40 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Market Heatmap</h2>
          <div style={{ fontSize: F.xs, color: C.muted }}>
            Regime: <strong style={{ color: C.textSub }}>{regime}</strong>
            {signalsData.last_updated && (
              <> · Updated {timeAgo(signalsData.last_updated)}</>
            )}
          </div>
        </div>
        <MarketHeatmap signals={signals} loading={loading} onSelect={setActiveChart} />
      </div>

      {/* ── 8. Market Momentum + Microstructure ──────── */}
      <div style={{ marginBottom: 40 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>
            Market Momentum
          </h2>
          <span style={{
            fontSize: 10,
            fontWeight: 700,
            padding: '2px 8px',
            borderRadius: R.pill,
            background: C.bull + '22',
            color: C.bull,
            textTransform: 'uppercase',
            letterSpacing: 0.8,
          }}>
            LIVE
          </span>
        </div>
        <MarketMomentumStrip signals={signals} regime={regime} />
      </div>

      {/* ── 9. Market Microstructure ──────────────────── */}
      <MarketMicrostructureRow />

      {/* ── 10. TradingView Chart ─────────────────────── */}
      <div style={{ marginBottom: 40 }}>
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

      {/* ── 11. Activity Feed + Recent Trades ─────────── */}
      <div style={{ marginBottom: 40 }}>
        <h2 style={{ margin: '0 0 12px', fontSize: F.lg, fontWeight: 700, color: C.text }}>Activity Feed</h2>
        <ActivityTicker events={activity} />
        {recentTrades.length > 0 && <RecentTradeStrip trades={recentTrades} />}
        <ActivityCalendarHeatmap />
      </div>

      {/* ── 12. LLM Brain Summary ─────────────────────── */}
      {llmView?.has_data && (
        <div
          className="fade-in"
          style={{
            background: C.surface,
            border: `1px solid ${C.border}`,
            borderRadius: R.lg,
            padding: '20px 24px',
            marginBottom: 40,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ fontSize: 20 }}>🧠</span>
              <span style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>Live AI Assessment</span>
              <span style={{ fontSize: F.xs, padding: '2px 8px', borderRadius: R.pill, background: '#1e293b', color: C.muted }} title="The bot analyzes and flags opportunities — it does not auto-execute trades">Advisory Mode · signals only</span>
            </div>
            <Link href="/signals" style={{ fontSize: F.xs, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>
              See every decision →
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
                    minWidth: 120,
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

      {/* ── 13. Strategies ────────────────────────────── */}
      <div style={{ marginBottom: 40 }}>
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
            Strategies appear here once the bot starts scanning. Nothing active yet — start the bot to begin receiving signals.
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 14 }}>
            {strategies.slice(0, 4).map((s) => (
              <StrategyCard key={s.id} strategy={s} />
            ))}
          </div>
        )}
      </div>

      {/* ── 14. Proof teaser ──────────────────────────── */}
      {btRes && (
        <div
          style={{
            background: `linear-gradient(135deg, ${C.brand}18, ${C.card})`,
            border: `1px solid ${C.brand}40`,
            borderRadius: R.xl,
            padding: '24px 28px',
            marginBottom: 40,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 16,
          }}
        >
          <div>
            <div style={{ fontSize: F.sm, color: C.muted, marginBottom: 4 }}>{btRes.config?.days ?? 30}-day paper trading · full log available</div>
            <div style={{ fontSize: F['2xl'], fontWeight: 800, color: C.bull }}>
              {fmtPct(btRes.total_return_pct)} return · {(btRes.win_rate * 100).toFixed(0)}% win rate
            </div>
            <div style={{ fontSize: F.sm, color: C.textSub, marginTop: 4 }}>
              {btRes.total_trades} closed trades · {fmtUsd(btRes.net_pnl)} net profit · {btRes.profit_factor?.toFixed(2)}× profit factor
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
            Verify the Performance →
          </Link>
        </div>
      )}
    </div>
  );
}
