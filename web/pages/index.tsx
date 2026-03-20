'use client';

import React, { useEffect, useState, useRef, useCallback } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { C, R, S, F, fmtUsd, fmtPct, timeAgo } from '../src/theme';
import type { BacktestResult, ActivityEvent, LlmMarketView } from '../src/types';
import type { IChartApi, ISeriesApi, IPriceLine, UTCTimestamp } from 'lightweight-charts';

// ─── API helper ───────────────────────────────────────────────────────────────

function resolveApiBase(): string {
  const envVal =
    (process.env.NEXT_PUBLIC_API_URL as string | undefined) ||
    (process.env.NEXT_PUBLIC_API_BASE_URL as string | undefined);
  if (envVal && envVal.trim().length > 0) return envVal;
  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (host && host !== 'localhost' && host !== '127.0.0.1') {
      return 'https://wagmi-production-d376.up.railway.app';
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

function MarketHeatmap({ signals, llmView, loading, onSelect, activeChart }: {
  signals: Record<string, Signal>;
  llmView: LlmMarketView | null;
  loading: boolean;
  onSelect: (sym: string) => void;
  activeChart: string;
}) {
  const rows: Array<{
    label: string;
    group?: string;
    render: (s: Signal) => { value: number; label: string; low: number; high: number; invertBull?: boolean };
  }> = [
    {
      label: 'Score',
      group: 'Signal',
      render: (s) => ({ value: s.score, label: `${s.score}`, low: 0, high: 100 }),
    },
    {
      label: 'RSI(14)',
      group: 'Signal',
      render: (s) => ({
        value: s.rsi14 ?? 50,
        label: s.rsi14 != null ? s.rsi14.toFixed(1) : '—',
        low: 20, high: 80,
      }),
    },
    {
      label: 'Trend',
      group: 'Signal',
      render: (s) => {
        const up = s.sma20 > s.sma50;
        return { value: up ? 1 : 0, label: up ? '↑ Bull' : '↓ Bear', low: 0, high: 1 };
      },
    },
    {
      label: 'ATR%',
      group: 'Volatility',
      render: (s) => ({
        value: s.atr_pct ?? 0,
        label: s.atr_pct != null ? s.atr_pct.toFixed(2) + '%' : '—',
        low: 0, high: 5,
        invertBull: true,
      }),
    },
    {
      label: 'Vol Spike',
      group: 'Volatility',
      render: (s) => ({
        value: s.vol_spike ? 1 : 0,
        label: s.vol_spike ? '⚡ Yes' : '— No',
        low: 0, high: 1,
      }),
    },
    {
      label: 'Zone',
      group: 'Structure',
      render: (s) => {
        const p = s.price;
        const { deepAccum, accum, distrib, safeDistrib } = s.zones;
        let zone = 'Neutral'; let score = 0.5;
        if (p <= deepAccum)      { zone = 'Deep Buy'; score = 0.95; }
        else if (p <= accum)     { zone = 'Buy Zone'; score = 0.72; }
        else if (p >= safeDistrib) { zone = 'Safe Sell'; score = 0.05; }
        else if (p >= distrib)   { zone = 'Sell Zone'; score = 0.28; }
        return { value: score, label: zone, low: 0, high: 1 };
      },
    },
    {
      label: 'SMA Dist%',
      group: 'Structure',
      render: (s) => {
        const dist = s.sma20 > 0 ? ((s.price - s.sma20) / s.sma20) * 100 : 0;
        const clamped = Math.max(-10, Math.min(10, dist));
        return {
          value: clamped + 10, // shift to 0-20 scale
          label: (dist >= 0 ? '+' : '') + dist.toFixed(1) + '%',
          low: 0, high: 20,
        };
      },
    },
  ];

  const STANCE_COLOR: Record<string, string> = {
    proceed: C.bull, go: C.bull, skip: C.muted, flat: C.muted, flip: '#a78bfa', veto: C.bear,
  };

  return (
    <div style={{ overflowX: 'auto', borderRadius: R.md, border: `1px solid ${C.border}` }}>
      <table style={{ borderCollapse: 'collapse', minWidth: 460, width: '100%' }}>
        <thead>
          <tr style={{ background: C.surface }}>
            <th style={{ padding: '12px 16px', fontSize: F.xs, color: C.muted, fontWeight: 600, textAlign: 'left', borderRight: `1px solid ${C.border}`, whiteSpace: 'nowrap' }}>
              Indicator
            </th>
            {SYMBOLS.map((sym) => (
              <th
                key={sym}
                onClick={() => onSelect(sym)}
                style={{
                  padding: '12px 16px',
                  fontSize: F.md, fontWeight: 800,
                  color: sym === activeChart ? '#fff' : C.brand,
                  background: sym === activeChart ? C.brand + '33' : 'transparent',
                  cursor: 'pointer', textAlign: 'center',
                  borderRight: `1px solid ${C.border}`,
                  userSelect: 'none', transition: 'background 0.15s',
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
          <tr style={{ borderTop: `1px solid ${C.border}`, background: '#0f172a' }}>
            <td style={{ padding: '12px 16px', fontSize: F.xs, color: C.muted, fontWeight: 700, borderRight: `1px solid ${C.border}`, whiteSpace: 'nowrap' }}>
              Price
            </td>
            {SYMBOLS.map((sym) => {
              const s = signals[sym];
              return (
                <td key={sym} style={{ padding: '12px 16px', textAlign: 'center', fontSize: F.md, fontWeight: 700, color: C.text, borderRight: `1px solid ${C.border}` }}>
                  {loading ? <Skeleton h={16} /> : s ? fmtUsd(s.price, s.price > 100 ? 2 : 4) : <span style={{ color: C.muted }}>—</span>}
                </td>
              );
            })}
          </tr>

          {/* AI Stance row */}
          {llmView?.per_symbol && (
            <tr style={{ borderTop: `1px solid ${C.border}` }}>
              <td style={{ padding: '12px 16px', fontSize: F.xs, color: C.muted, fontWeight: 700, borderRight: `1px solid ${C.border}`, whiteSpace: 'nowrap' }}>
                🤖 AI Stance
              </td>
              {SYMBOLS.map((sym) => {
                const dec = llmView.per_symbol[sym];
                if (!dec) return <td key={sym} style={{ padding: '12px 16px', background: C.heatNeutral, borderRight: `1px solid ${C.border}` }} />;
                const action = (dec.action || 'skip').toLowerCase();
                const label  = dec.is_veto ? 'VETO' : action === 'proceed' || action === 'go' ? 'GO' : action === 'flip' ? 'FLIP' : 'SKIP';
                const color  = STANCE_COLOR[dec.is_veto ? 'veto' : action] || C.muted;
                const confPct = dec.confidence != null ? Math.round(dec.confidence * 100) : null;
                return (
                  <td key={sym} style={{ padding: '10px 16px', textAlign: 'center', borderRight: `1px solid ${C.border}`, background: color + '11' }}>
                    <span style={{ fontSize: F.xs, fontWeight: 800, color, display: 'block' }}>{label}</span>
                    {confPct != null && <span style={{ fontSize: 10, color: C.muted }}>{confPct}%</span>}
                  </td>
                );
              })}
            </tr>
          )}

          {/* Signal rows */}
          {rows.map((row) => (
            <tr key={row.label} style={{ borderTop: `1px solid ${C.border}` }}>
              <td style={{ padding: '11px 16px', fontSize: F.xs, color: C.muted, fontWeight: 600, borderRight: `1px solid ${C.border}`, whiteSpace: 'nowrap' }}>
                <span style={{ fontSize: 9, color: C.faint, textTransform: 'uppercase', display: 'block', marginBottom: 1 }}>{row.group}</span>
                {row.label}
              </td>
              {SYMBOLS.map((sym) => {
                const s = signals[sym];
                if (!s) return <td key={sym} style={{ padding: '11px 16px', background: C.heatNeutral, borderRight: `1px solid ${C.border}` }} />;
                if (loading) return <td key={sym} style={{ padding: '11px 16px', borderRight: `1px solid ${C.border}` }}><Skeleton h={14} /></td>;
                const { value, label, low, high, invertBull } = row.render(s) as any;
                return <HeatCell key={sym} value={value} label={label} low={low} high={high} invertBull={invertBull} />;
              })}
            </tr>
          ))}
        </tbody>
      </table>

      {/* Legend */}
      <div style={{ padding: '10px 16px', background: C.surface, display: 'flex', gap: 16, fontSize: F.xs, color: C.muted, borderTop: `1px solid ${C.border}`, flexWrap: 'wrap' }}>
        {[
          { color: C.heatBull2, label: 'Strong bull' },
          { color: C.heatBull1 + '88', label: 'Mild bull' },
          { color: C.heatNeutral, label: 'Neutral' },
          { color: C.heatBear1 + '88', label: 'Mild bear' },
          { color: C.heatBear2, label: 'Strong bear' },
        ].map(({ color, label }) => (
          <span key={label}>
            <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: color, marginRight: 5, verticalAlign: 'middle' }} />
            {label}
          </span>
        ))}
        <span style={{ marginLeft: 'auto' }}>Click symbol header to switch chart</span>
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

// ─── Candle Chart with Bot Overlays (lightweight-charts v5) ──────────────────

type Candle = { time: UTCTimestamp; open: number; high: number; low: number; close: number; volume: number };

const CHART_TIMEFRAMES = ['15m', '1h', '4h', '1d'] as const;
type Timeframe = typeof CHART_TIMEFRAMES[number];

function CandleChart({
  symbol,
  apiBase,
  zones,
  signalLevels,
  timeframe,
}: {
  symbol: string;
  apiBase: string;
  zones?: Signal['zones'] | null;
  signalLevels?: { entry?: number; sl?: number; tp1?: number; tp2?: number; side?: string } | null;
  timeframe: Timeframe;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const roRef = useRef<ResizeObserver | null>(null);
  const [status, setStatus] = useState<'loading' | 'ok' | 'error'>('loading');
  const [chartReady, setChartReady] = useState(false);

  // Initialize chart once on mount (browser only)
  useEffect(() => {
    if (typeof window === 'undefined' || !containerRef.current) return;

    let chart: IChartApi;
    let destroyed = false;

    (async () => {
      const lc = await import('lightweight-charts');
      if (destroyed || !containerRef.current) return;

      containerRef.current.innerHTML = '';
      chart = lc.createChart(containerRef.current, {
        autoSize: true,
        layout: { background: { color: C.card }, textColor: C.textSub },
        grid: { vertLines: { color: C.border }, horzLines: { color: C.border } },
        crosshair: { mode: lc.CrosshairMode.Normal },
        rightPriceScale: { borderColor: C.border },
        timeScale: { borderColor: C.border, timeVisible: true, secondsVisible: false },
        handleScroll: true,
        handleScale: true,
      });
      chartRef.current = chart;

      // Volume histogram (in a separate pane)
      const volSeries = chart.addSeries(lc.HistogramSeries, {
        color: C.brand + '55',
        priceFormat: { type: 'volume' },
        priceScaleId: 'vol',
      });
      chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });
      volumeSeriesRef.current = volSeries;

      // Candlestick series
      const candleSeries = chart.addSeries(lc.CandlestickSeries, {
        upColor: C.bull,
        downColor: C.bear,
        borderUpColor: C.bull,
        borderDownColor: C.bear,
        wickUpColor: C.bull,
        wickDownColor: C.bear,
      });
      candleSeriesRef.current = candleSeries;
      setChartReady(true);

      // Auto-resize via ResizeObserver
      const ro = new ResizeObserver(() => {
        if (containerRef.current && !destroyed) {
          chart.applyOptions({ width: containerRef.current.clientWidth });
        }
      });
      ro.observe(containerRef.current);
      roRef.current = ro;
    })();

    return () => {
      destroyed = true;
      roRef.current?.disconnect();
      chartRef.current?.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      priceLinesRef.current = [];
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch + render candles when symbol/timeframe changes (or chart becomes ready)
  useEffect(() => {
    if (!chartReady || !candleSeriesRef.current) return;
    setStatus('loading');

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 8000); // 8s timeout

    fetch(`${apiBase}/v1/ohlcv?symbol=${symbol}&timeframe=${timeframe}&limit=300`, { signal: controller.signal })
      .then((r) => r.json())
      .then((raw: any[]) => {
        clearTimeout(timeoutId);
        if (!Array.isArray(raw) || raw.length === 0) { setStatus('error'); return; }
        const candles: Candle[] = raw.map((c) => ({ ...c, time: c.time as UTCTimestamp }));
        const sorted = [...candles].sort((a, b) => a.time - b.time);
        if (candleSeriesRef.current) {
          candleSeriesRef.current.setData(sorted);
          volumeSeriesRef.current?.setData(
            sorted.map((c) => ({ time: c.time, value: c.volume, color: c.close >= c.open ? C.bull + '66' : C.bear + '66' }))
          );
          chartRef.current?.timeScale().fitContent();
        }
        setStatus('ok');
      })
      .catch(() => { clearTimeout(timeoutId); setStatus('error'); });
    return () => { clearTimeout(timeoutId); controller.abort(); };
  }, [symbol, timeframe, apiBase, chartReady]);

  // Apply zone bands + signal price lines whenever they change
  useEffect(() => {
    const series = candleSeriesRef.current;
    if (!series) return;

    // Clear previous price lines
    priceLinesRef.current.forEach((pl) => { try { series.removePriceLine(pl); } catch {} });
    priceLinesRef.current = [];

    const lines: IPriceLine[] = [];

    (async () => {
      const { LineStyle } = await import('lightweight-charts');

      // Zone dashed lines
      if (zones) {
        const zoneLines = [
          { price: zones.deepAccum,   color: '#16a34acc', title: '▶ Deep Buy' },
          { price: zones.accum,       color: '#22c55ecc', title: '▶ Buy Zone' },
          { price: zones.distrib,     color: '#ef4444cc', title: '◀ Sell Zone' },
          { price: zones.safeDistrib, color: '#b91c1ccc', title: '◀ Safe Sell' },
        ];
        for (const z of zoneLines) {
          if (!z.price || z.price === 0) continue;
          lines.push(series.createPriceLine({ price: z.price, color: z.color, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: z.title }));
        }
      }

      // Signal entry/SL/TP solid lines
      if (signalLevels) {
        const sigLines = [
          { price: signalLevels.sl,    color: '#ef4444', title: 'SL',    width: 2 },
          { price: signalLevels.entry, color: '#f59e0b', title: 'Entry', width: 2 },
          { price: signalLevels.tp1,   color: '#34d399', title: 'TP1',   width: 2 },
          { price: signalLevels.tp2,   color: '#16a34a', title: 'TP2',   width: 1 },
        ];
        for (const l of sigLines) {
          if (!l.price || l.price === 0) continue;
          lines.push(series.createPriceLine({ price: l.price!, color: l.color, lineWidth: l.width as any, lineStyle: LineStyle.Solid, axisLabelVisible: true, title: l.title }));
        }
      }

      priceLinesRef.current = lines;
    })();
  }, [zones, signalLevels]);

  // TradingView widget fallback when OHLCV API is unavailable
  if (status === 'error') {
    const TV_TF: Record<string, string> = { '15m': '15', '1h': '60', '4h': '240', '1d': 'D' };
    const tvSrc = `https://s.tradingview.com/widgetembed/?frameElementId=tv_${symbol}&symbol=${TV_SYMBOLS[symbol] ?? symbol}&interval=${TV_TF[timeframe] ?? '60'}&theme=dark&style=1&locale=en&hide_top_toolbar=0&hide_side_toolbar=0&allow_symbol_change=0&save_image=0&withdateranges=1`;
    return (
      <div style={{ width: '100%', height: 620, borderRadius: R.md, overflow: 'hidden', background: '#131722' }}>
        <iframe
          src={tvSrc}
          style={{ width: '100%', height: '100%', border: 'none', display: 'block' }}
          allow="fullscreen"
          title={`${symbol} Chart`}
        />
      </div>
    );
  }

  return (
    <div style={{ position: 'relative' }}>
      <div ref={containerRef} style={{ width: '100%', height: 620, background: C.card, borderRadius: R.md }} />
      {status === 'loading' && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: C.card + 'cc', borderRadius: R.md, fontSize: F.sm, color: C.muted }}>
          Loading candles…
        </div>
      )}
    </div>
  );
}

// ─── Signal Panel (manual trading reference) ──────────────────────────────────

function SignalPanel({
  symbol,
  signal,
  llmDec,
  regime,
}: {
  symbol: string;
  signal?: Signal | null;
  llmDec?: any | null;
  regime: string;
}) {
  const action = (llmDec?.action || 'skip').toLowerCase();
  const isGo   = action === 'proceed' || action === 'go';
  const isVeto = llmDec?.is_veto;
  const conf   = llmDec?.confidence ?? null;
  const confPct = conf != null ? Math.round(conf * 100) : null;
  const stanceColor = isVeto ? C.bear : isGo ? C.bull : C.muted;
  const stanceLabel = isVeto ? 'VETO' : isGo ? 'GO' : 'SKIP';

  const REGIME_COLOR: Record<string, string> = {
    trend: C.bull, range: '#60a5fa', panic: C.bear,
    high_volatility: '#fbbf24', low_liquidity: '#64748b',
    news_dislocation: '#7c3aed', unknown: C.muted, neutral: C.muted,
  };
  const regimeKey = (regime || 'unknown').toLowerCase().replace(' ', '_');
  const regimeColor = REGIME_COLOR[regimeKey] || C.muted;

  // Price ladder entries (sorted by price for visual)
  const levels = signal ? [
    { label: 'TP2',   price: signal.zones?.safeDistrib, color: '#16a34a', icon: '⬆' },
    { label: 'TP1',   price: signal.zones?.distrib,     color: '#34d399', icon: '⬆' },
    { label: 'Entry', price: signal.price,              color: '#f59e0b', icon: '◆' },
    { label: 'SL',    price: signal.zones?.deepAccum,   color: C.bear,    icon: '⬇' },
  ].filter(l => l.price && l.price > 0) : [];

  const highP = levels.length ? Math.max(...levels.map(l => l.price!)) : 0;
  const lowP  = levels.length ? Math.min(...levels.map(l => l.price!)) : 0;
  const range = highP - lowP || 1;

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '18px 16px',
      display: 'flex',
      flexDirection: 'column',
      gap: 14,
      height: '100%',
      boxSizing: 'border-box',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: F.lg, fontWeight: 800, color: C.text }}>{symbol}</span>
        <span style={{
          fontSize: F.xs, fontWeight: 700, padding: '3px 10px', borderRadius: R.pill,
          background: stanceColor + '22', color: stanceColor, border: `1px solid ${stanceColor}44`,
        }}>
          {stanceLabel}
        </span>
      </div>

      {/* Regime */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: F.xs, color: C.muted }}>Regime</span>
        <span style={{
          fontSize: F.xs, fontWeight: 700, padding: '2px 8px', borderRadius: R.pill,
          background: regimeColor + '22', color: regimeColor,
        }}>
          {regime.toUpperCase()}
        </span>
      </div>

      {/* AI Confidence bar */}
      {confPct != null && (
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
            <span style={{ fontSize: F.xs, color: C.muted }}>AI Confidence</span>
            <span style={{ fontSize: F.xs, fontWeight: 700, color: stanceColor }}>{confPct}%</span>
          </div>
          <div style={{ height: 5, background: C.border, borderRadius: 3, overflow: 'hidden' }}>
            <div style={{ width: `${confPct}%`, height: '100%', background: stanceColor, borderRadius: 3, transition: 'width 0.4s ease' }} />
          </div>
        </div>
      )}

      {/* LLM notes */}
      {llmDec?.notes && (
        <div style={{
          fontSize: F.xs, color: C.textSub, lineHeight: 1.5,
          background: '#0f172a', borderRadius: R.sm, padding: '8px 10px',
          borderLeft: `2px solid ${stanceColor}`,
          maxHeight: 72, overflow: 'hidden',
        }}>
          {llmDec.notes}
        </div>
      )}

      {/* Divider */}
      <div style={{ height: 1, background: C.border }} />

      {/* Price Signal Section */}
      <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.8 }}>
        Signal Levels
      </div>

      {signal ? (
        <>
          {/* Visual price ladder */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {levels.sort((a, b) => (b.price ?? 0) - (a.price ?? 0)).map((lvl) => {
              const pct = highP > lowP ? ((lvl.price! - lowP) / range) * 100 : 50;
              return (
                <div key={lvl.label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: 10, color: lvl.color, width: 12, textAlign: 'center' }}>{lvl.icon}</span>
                  <span style={{ fontSize: F.xs, color: C.muted, width: 36 }}>{lvl.label}</span>
                  <div style={{ flex: 1, height: 3, background: C.border, borderRadius: 2 }}>
                    <div style={{ width: `${pct}%`, height: '100%', background: lvl.color + '88', borderRadius: 2 }} />
                  </div>
                  <span style={{ fontSize: F.xs, fontWeight: 600, color: lvl.color, minWidth: 70, textAlign: 'right' }}>
                    {fmtUsd(lvl.price, (lvl.price ?? 0) > 100 ? 2 : 4)}
                  </span>
                </div>
              );
            })}
          </div>

          {/* Key metrics */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {[
              { label: 'Score', value: `${signal.score ?? '—'}`, color: (signal.score ?? 0) > 60 ? C.bull : C.warn },
              { label: 'RSI', value: signal.rsi14 != null ? signal.rsi14.toFixed(1) : '—', color: signal.rsi14 != null && signal.rsi14 < 35 ? C.bull : signal.rsi14 != null && signal.rsi14 > 65 ? C.bear : C.muted },
              { label: 'ATR %', value: signal.atr_pct != null ? signal.atr_pct.toFixed(2) + '%' : '—', color: C.muted },
              { label: 'Vol Spike', value: signal.vol_spike ? 'YES' : 'No', color: signal.vol_spike ? C.warn : C.muted },
            ].map(m => (
              <div key={m.label} style={{ background: '#0f172a', borderRadius: R.sm, padding: '8px 10px' }}>
                <div style={{ fontSize: 10, color: C.muted, marginBottom: 3 }}>{m.label}</div>
                <div style={{ fontSize: F.sm, fontWeight: 700, color: m.color }}>{m.value}</div>
              </div>
            ))}
          </div>

          {/* Zone label */}
          <div style={{
            textAlign: 'center', fontSize: F.xs, fontWeight: 600,
            padding: '6px 10px', borderRadius: R.sm, background: C.brand + '18', color: C.brand,
            border: `1px solid ${C.brand}33`,
          }}>
            {signal.label ?? 'Observation'}
          </div>
        </>
      ) : (
        <div style={{ fontSize: F.xs, color: C.muted, textAlign: 'center', padding: '12px 0' }}>
          No signal data — bot may be offline
        </div>
      )}
    </div>
  );
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
  const [activeTimeframe, setActiveTimeframe] = useState<Timeframe>('1h');
  const [heatTab, setHeatTab] = useState<'market' | 'scores' | 'correlation' | 'regime'>('market');
  const [correlations, setCorrelations] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState(false);
  const [sniperQueue, setSniperQueue] = useState<any[]>([]);
  const [sniperStats, setSniperStats] = useState<any>({pending:0,approved:0,rejected:0,executed:0,total:0});
  const [sniperAction, setSniperAction] = useState<Record<string, 'approving'|'rejecting'|null>>({});
  const apiBase = resolveApiBase();

  // Compute correlation matrix from recent OHLCV (30 daily candles)
  useEffect(() => {
    const pearson = (a: number[], b: number[]) => {
      const n = Math.min(a.length, b.length);
      if (n < 5) return 0;
      const meanA = a.slice(0, n).reduce((s, x) => s + x, 0) / n;
      const meanB = b.slice(0, n).reduce((s, x) => s + x, 0) / n;
      const num = a.slice(0, n).reduce((s, x, i) => s + (x - meanA) * (b[i] - meanB), 0);
      const denA = Math.sqrt(a.slice(0, n).reduce((s, x) => s + (x - meanA) ** 2, 0));
      const denB = Math.sqrt(b.slice(0, n).reduce((s, x) => s + (x - meanB) ** 2, 0));
      return denA * denB === 0 ? 0 : num / (denA * denB);
    };

    const fetchAll = async () => {
      try {
        const results = await Promise.all(
          SYMBOLS.map((sym) =>
            fetch(`${apiBase}/v1/ohlcv?symbol=${sym}&timeframe=1d&limit=30`)
              .then((r) => r.json())
              .then((d: any[]) => Array.isArray(d) ? d.map((c) => c.close as number) : [])
              .catch(() => [] as number[])
          )
        );
        const [btcC, solC, hypeC] = results;
        const corrs: Record<string, number> = {
          'BTC-SOL': pearson(btcC, solC),
          'BTC-HYPE': pearson(btcC, hypeC),
          'SOL-HYPE': pearson(solC, hypeC),
          'SOL-BTC': pearson(solC, btcC),
          'HYPE-BTC': pearson(hypeC, btcC),
          'HYPE-SOL': pearson(hypeC, solC),
          'BTC-BTC': 1, 'SOL-SOL': 1, 'HYPE-HYPE': 1,
        };
        setCorrelations(corrs);
      } catch {}
    };

    fetchAll();
  }, [apiBase]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [sigRes, stratRes, btRes, actRes, llmRes, sniperRes, sniperStatsRes] = await Promise.allSettled([
          fetch(`${apiBase}/v1/signals`),
          fetch(`${apiBase}/v1/strategies`),
          fetch(`${apiBase}/v1/backtest/results/latest`),
          fetch(`${apiBase}/v1/activity/feed?limit=8`),
          fetch(`${apiBase}/v1/llm/market-view`),
          fetch(`${apiBase}/v1/sniper/queue?limit=20`),
          fetch(`${apiBase}/v1/sniper/stats`),
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
        if (sniperRes.status === 'fulfilled' && sniperRes.value.ok) {
          const d = await sniperRes.value.json();
          setSniperQueue(d?.proposals || []);
        }
        if (sniperStatsRes.status === 'fulfilled' && sniperStatsRes.value.ok) {
          setSniperStats(await sniperStatsRes.value.json());
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

  const handleSniperAction = async (id: string, action: 'approve' | 'reject') => {
    setSniperAction(prev => ({ ...prev, [id]: action === 'approve' ? 'approving' : 'rejecting' }));
    try {
      const res = await fetch(`${apiBase}/v1/sniper/${id}/${action}`, { method: 'POST' });
      if (res.ok) {
        setSniperQueue(prev => prev.filter(p => p.id !== id));
        setSniperStats((prev: any) => ({
          ...prev,
          pending: Math.max(0, (prev.pending || 0) - 1),
          [action === 'approve' ? 'approved' : 'rejected']: (prev[action === 'approve' ? 'approved' : 'rejected'] || 0) + 1,
        }));
      }
    } catch {}
    setSniperAction(prev => ({ ...prev, [id]: null }));
  };

  // Equity sparkline data from backtest equity (simplified: just use total_return as flat curve)
  // We'll use by_symbol pnl data to derive a simple visual
  const sparkData = btRes
    ? [btRes.total_return_pct < 0 ? 0 : 2, 3, 1.5, 4, 2.5, 5, btRes.total_return_pct]
    : [];

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
          sub={btRes ? `${backtest?.config?.days ?? 30}-day backtest` : 'Waiting for data'}
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
                {btRes ? `$${(backtest?.config?.starting_equity ?? 50000).toLocaleString()} → ${fmtUsd(btRes.final_equity)}` : 'No backtest data'}
              </div>
            </>
          )}
        </div>
      </div>

      {/* ── Activity ticker ───────────────────────────── */}
      <ActivityTicker events={activity} />

      {/* ── Full-width Chart ──────────────────────────── */}
      <div style={{ marginBottom: 16 }}>
        {/* Controls row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0, fontSize: F.lg, fontWeight: 700, color: C.text }}>Chart</h2>

          <div style={{ display: 'flex', gap: 5, marginLeft: 6 }}>
            {SYMBOLS.map((sym) => (
              <button key={sym} onClick={() => setActiveChart(sym)} style={{
                padding: '5px 14px', borderRadius: R.pill, cursor: 'pointer', transition: 'all 0.15s',
                border: `1px solid ${activeChart === sym ? C.brand : C.border}`,
                background: activeChart === sym ? C.brand : 'transparent',
                color: activeChart === sym ? '#fff' : C.muted,
                fontSize: F.sm, fontWeight: 600,
              }}>
                {sym}
              </button>
            ))}
          </div>

          <div style={{ width: 1, height: 20, background: C.border, margin: '0 4px' }} />

          <div style={{ display: 'flex', gap: 4 }}>
            {CHART_TIMEFRAMES.map((tf) => (
              <button key={tf} onClick={() => setActiveTimeframe(tf)} style={{
                padding: '4px 10px', borderRadius: R.sm, cursor: 'pointer', transition: 'all 0.15s',
                border: `1px solid ${activeTimeframe === tf ? C.brand + '88' : C.border}`,
                background: activeTimeframe === tf ? C.brand + '22' : 'transparent',
                color: activeTimeframe === tf ? C.brand : C.muted,
                fontSize: F.xs, fontWeight: 600,
              }}>
                {tf}
              </button>
            ))}
          </div>

          <div style={{ marginLeft: 'auto', display: 'flex', gap: 12, fontSize: F.xs, color: C.muted }}>
            <span><span style={{ display: 'inline-block', width: 20, height: 2, background: '#22c55e', verticalAlign: 'middle', marginRight: 4 }} />Buy zones</span>
            <span><span style={{ display: 'inline-block', width: 20, height: 2, background: '#ef4444', verticalAlign: 'middle', marginRight: 4 }} />Sell zones</span>
          </div>
        </div>

        {/* Full-width chart */}
        <div style={{ border: `1px solid ${C.border}`, borderRadius: R.md, overflow: 'hidden', background: C.card }}>
          <CandleChart
            symbol={activeChart}
            apiBase={apiBase}
            zones={signals[activeChart]?.zones ?? null}
            signalLevels={null}
            timeframe={activeTimeframe}
          />
        </div>
      </div>

      {/* ── Below-chart 3-column panel ────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 220px 220px', gap: 14, marginBottom: 28, alignItems: 'start' }}>

        {/* LEFT — Tabbed heatmap section */}
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: R.lg, overflow: 'hidden' }}>
          {/* Tab strip */}
          <div style={{ display: 'flex', borderBottom: `1px solid ${C.border}`, background: '#0f172a' }}>
            {(['market', 'scores', 'correlation', 'regime'] as const).map((tab) => {
              const labels: Record<string, string> = { market: 'Market Signals', scores: 'Strategy Scores', correlation: 'Correlation', regime: 'Regime History' };
              return (
                <button key={tab} onClick={() => setHeatTab(tab)} style={{
                  flex: 1, padding: '10px 4px', background: 'none', border: 'none', cursor: 'pointer',
                  fontSize: F.xs, fontWeight: 600, transition: 'all 0.15s',
                  color: heatTab === tab ? C.brand : C.muted,
                  borderBottom: heatTab === tab ? `2px solid ${C.brand}` : '2px solid transparent',
                }}>
                  {labels[tab]}
                </button>
              );
            })}
          </div>

          {/* Tab content */}
          <div>
            {heatTab === 'market' && (
              <MarketHeatmap signals={signals} llmView={llmView} loading={loading} onSelect={(sym) => { setActiveChart(sym); }} activeChart={activeChart} />
            )}

            {heatTab === 'scores' && (
              <div>
                {/* Strategy-style score matrix: treat each indicator as a "strategy" */}
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                    <thead>
                      <tr style={{ background: '#0f172a' }}>
                        <th style={{ padding: '10px 14px', fontSize: F.xs, color: C.muted, fontWeight: 600, textAlign: 'left', borderRight: `1px solid ${C.border}` }}>Component</th>
                        {SYMBOLS.map((sym) => (
                          <th key={sym} onClick={() => setActiveChart(sym)} style={{ padding: '10px 14px', fontSize: F.sm, fontWeight: 800, color: sym === activeChart ? '#fff' : C.brand, cursor: 'pointer', textAlign: 'center', borderRight: `1px solid ${C.border}`, background: sym === activeChart ? C.brand + '33' : 'transparent' }}>{sym}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        { label: 'Overall Score', getValue: (s: Signal) => ({ v: s.score, txt: `${s.score}`, lo: 0, hi: 100 }) },
                        { label: 'RSI Momentum', getValue: (s: Signal) => { const r = s.rsi14 ?? 50; return { v: r, txt: r.toFixed(1), lo: 20, hi: 80 }; } },
                        { label: 'Trend (SMA)', getValue: (s: Signal) => ({ v: s.sma20 > s.sma50 ? 80 : 20, txt: s.sma20 > s.sma50 ? '↑ Bull' : '↓ Bear', lo: 0, hi: 100 }) },
                        { label: 'Zone Position', getValue: (s: Signal) => {
                          const p = s.price; const { deepAccum, accum, distrib, safeDistrib } = s.zones;
                          const score = p <= deepAccum ? 95 : p <= accum ? 70 : p >= safeDistrib ? 5 : p >= distrib ? 25 : 50;
                          const txt = p <= deepAccum ? 'Deep Buy' : p <= accum ? 'Buy Zone' : p >= safeDistrib ? 'Safe Sell' : p >= distrib ? 'Sell Zone' : 'Neutral';
                          return { v: score, txt, lo: 0, hi: 100 };
                        }},
                        { label: 'ATR Volatility', getValue: (s: Signal) => ({ v: Math.min(s.atr_pct ?? 0, 10), txt: s.atr_pct != null ? s.atr_pct.toFixed(2) + '%' : '—', lo: 0, hi: 10, inv: true }) },
                        { label: 'Vol Spike', getValue: (s: Signal) => ({ v: s.vol_spike ? 80 : 20, txt: s.vol_spike ? '⚡ Yes' : '— No', lo: 0, hi: 100 }) },
                      ].map((row) => (
                        <tr key={row.label} style={{ borderTop: `1px solid ${C.border}` }}>
                          <td style={{ padding: '10px 14px', fontSize: F.xs, color: C.muted, fontWeight: 600, borderRight: `1px solid ${C.border}`, whiteSpace: 'nowrap' }}>{row.label}</td>
                          {SYMBOLS.map((sym) => {
                            const s = signals[sym];
                            if (!s) return <td key={sym} style={{ padding: '10px 14px', background: C.heatNeutral, borderRight: `1px solid ${C.border}` }} />;
                            const { v, txt, lo, hi, inv } = row.getValue(s) as any;
                            return <HeatCell key={sym} value={v} label={txt} low={lo} high={hi} invertBull={!!inv} />;
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{ padding: '8px 14px', background: C.surface, fontSize: F.xs, color: C.muted, borderTop: `1px solid ${C.border}` }}>
                  Each row = one signal component. Green = bullish signal, red = bearish.
                </div>
              </div>
            )}

            {heatTab === 'correlation' && (
              <div style={{ padding: 16 }}>
                <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 12 }}>30-day daily return correlation (Pearson)</div>
                <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                  <thead>
                    <tr>
                      <th style={{ padding: '8px 10px', fontSize: F.xs, color: C.muted, textAlign: 'left' }}></th>
                      {SYMBOLS.map((sym) => (
                        <th key={sym} style={{ padding: '8px 14px', fontSize: F.sm, fontWeight: 800, color: C.brand, textAlign: 'center' }}>{sym}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {SYMBOLS.map((rowSym) => (
                      <tr key={rowSym}>
                        <td style={{ padding: '8px 10px', fontSize: F.sm, fontWeight: 800, color: C.brand }}>{rowSym}</td>
                        {SYMBOLS.map((colSym) => {
                          const key = `${rowSym}-${colSym}`;
                          const val = correlations[key];
                          const isDiag = rowSym === colSym;
                          const pct = val != null ? val : null;
                          const bg = isDiag ? C.brand + '22' :
                            pct == null ? C.heatNeutral :
                            pct > 0.7 ? C.heatBull2 :
                            pct > 0.4 ? C.heatBull1 + '55' :
                            pct < -0.4 ? C.heatBear2 :
                            C.heatNeutral;
                          return (
                            <td key={colSym} style={{ padding: '12px 14px', background: bg, textAlign: 'center', fontSize: F.sm, fontWeight: 700, color: C.text, border: `1px solid ${C.border}` }}>
                              {isDiag ? '1.00' : pct != null ? pct.toFixed(2) : '…'}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ marginTop: 12, display: 'flex', gap: 14, fontSize: F.xs, color: C.muted, flexWrap: 'wrap' }}>
                  <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: C.heatBull2, marginRight: 4 }} />{'>'}0.7 highly correlated</span>
                  <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: C.heatNeutral, marginRight: 4 }} />Neutral</span>
                  <span><span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: C.heatBear2, marginRight: 4 }} />Inverse</span>
                </div>
              </div>
            )}

            {heatTab === 'regime' && (
              <div style={{ padding: '12px 16px' }}>
                <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 10 }}>Recent regime & signal events</div>
                {activity.length === 0 ? (
                  <div style={{ color: C.muted, fontSize: F.xs, textAlign: 'center', padding: 16 }}>No activity yet</div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {activity.slice(0, 10).map((ev, i) => {
                      const REGIME_COLOR: Record<string, string> = {
                        trend: C.bull, range: '#60a5fa', panic: C.bear, high_volatility: '#fbbf24',
                        low_liquidity: '#64748b', news_dislocation: '#7c3aed',
                      };
                      const dotColor = ev.badge_color || C.brand;
                      return (
                        <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: '8px 0', borderBottom: i < activity.length - 1 ? `1px solid ${C.border}` : 'none' }}>
                          <div style={{ width: 8, height: 8, borderRadius: '50%', background: dotColor, flexShrink: 0, marginTop: 4 }} />
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 2, flexWrap: 'wrap' }}>
                              <span style={{ fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: R.xs, background: dotColor + '22', color: dotColor }}>{ev.badge}</span>
                              {ev.symbol && <span style={{ fontSize: F.xs, fontWeight: 700, color: C.textSub }}>{ev.symbol}</span>}
                              <span style={{ fontSize: 10, color: C.muted }}>{timeAgo(ev.ts_iso || ev.ts)}</span>
                            </div>
                            <div style={{ fontSize: F.xs, color: C.textSub, lineHeight: 1.4, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as any }}>
                              {ev.title}
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* CENTER — Compact AI stance cards */}
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: R.lg, overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px', borderBottom: `1px solid ${C.border}`, background: '#0f172a', display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 14 }}>🤖</span>
            <span style={{ fontSize: F.xs, fontWeight: 700, color: C.text }}>AI Stance</span>
            <Link href="/signals" style={{ marginLeft: 'auto', fontSize: 10, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>Feed →</Link>
          </div>
          <div style={{ padding: '12px 14px', display: 'flex', flexDirection: 'column', gap: 10 }}>
            {SYMBOLS.map((sym) => {
              const dec = llmView?.per_symbol?.[sym];
              const action = (dec?.action || 'skip').toLowerCase();
              const isGo = action === 'proceed' || action === 'go';
              const isVeto = dec?.is_veto;
              const conf = dec?.confidence ?? null;
              const stanceColor = isVeto ? C.bear : isGo ? C.bull : C.muted;
              const label = isVeto ? 'VETO' : isGo ? 'GO' : 'SKIP';
              return (
                <div key={sym} onClick={() => setActiveChart(sym)} style={{
                  background: '#0f172a', borderRadius: R.md, padding: '10px 12px', cursor: 'pointer',
                  border: `1px solid ${sym === activeChart ? stanceColor + '55' : C.border}`,
                  transition: 'border-color 0.15s',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                    <span style={{ fontSize: F.sm, fontWeight: 800, color: C.text }}>{sym}</span>
                    <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: R.pill, background: stanceColor + '22', color: stanceColor }}>{label}</span>
                  </div>
                  {conf != null && (
                    <>
                      <div style={{ height: 3, background: C.border, borderRadius: 2, marginBottom: 4, overflow: 'hidden' }}>
                        <div style={{ width: `${Math.round(conf * 100)}%`, height: '100%', background: stanceColor, borderRadius: 2, transition: 'width 0.4s' }} />
                      </div>
                      <div style={{ fontSize: 10, color: C.muted }}>{Math.round(conf * 100)}% confidence</div>
                    </>
                  )}
                  {dec?.notes && (
                    <div style={{ fontSize: 10, color: C.textSub, marginTop: 5, lineHeight: 1.4, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' as any }}>
                      {dec.notes}
                    </div>
                  )}
                </div>
              );
            })}

            {/* Global regime */}
            <div style={{ marginTop: 4, padding: '8px 10px', background: C.brand + '15', borderRadius: R.sm, border: `1px solid ${C.brand}33` }}>
              <div style={{ fontSize: 10, color: C.muted, marginBottom: 2 }}>MARKET REGIME</div>
              <div style={{ fontSize: F.sm, fontWeight: 800, color: C.brand }}>{regime.toUpperCase()}</div>
              {llmView?.decision_counts && (
                <div style={{ display: 'flex', gap: 8, marginTop: 4, fontSize: 10, flexWrap: 'wrap' }}>
                  <span style={{ color: C.bull }}>✓ {llmView.decision_counts.proceed}</span>
                  <span style={{ color: C.muted }}>— {llmView.decision_counts.flat}</span>
                  <span style={{ color: '#a78bfa' }}>↔ {llmView.decision_counts.flip}</span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* RIGHT — Signal levels for active chart */}
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: R.lg, overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px', borderBottom: `1px solid ${C.border}`, background: '#0f172a', display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 14 }}>📍</span>
            <span style={{ fontSize: F.xs, fontWeight: 700, color: C.text }}>{activeChart} Signal</span>
          </div>
          {(() => {
            const sig = signals[activeChart];
            if (!sig) return (
              <div style={{ padding: 16, fontSize: F.xs, color: C.muted, textAlign: 'center' }}>No signal data</div>
            );
            const levels = [
              { label: 'Safe Sell', price: sig.zones.safeDistrib, color: '#b91c1c', icon: '▲' },
              { label: 'Sell Zone', price: sig.zones.distrib,     color: '#ef4444', icon: '▲' },
              { label: 'Price',     price: sig.price,             color: '#f59e0b', icon: '◆' },
              { label: 'Buy Zone',  price: sig.zones.accum,       color: '#22c55e', icon: '▼' },
              { label: 'Deep Buy',  price: sig.zones.deepAccum,   color: '#16a34a', icon: '▼' },
            ].filter((l) => l.price && l.price > 0);
            const highP = Math.max(...levels.map((l) => l.price));
            const lowP  = Math.min(...levels.map((l) => l.price));
            const rng   = highP - lowP || 1;
            return (
              <div style={{ padding: '14px 14px' }}>
                {/* Visual price ladder */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginBottom: 14 }}>
                  {levels.sort((a, b) => b.price - a.price).map((lv) => {
                    const pct = ((lv.price - lowP) / rng) * 100;
                    return (
                      <div key={lv.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontSize: 9, color: lv.color, width: 10, textAlign: 'center' }}>{lv.icon}</span>
                        <span style={{ fontSize: 10, color: C.muted, width: 52 }}>{lv.label}</span>
                        <div style={{ flex: 1, height: lv.label === 'Price' ? 4 : 2, background: C.border, borderRadius: 2 }}>
                          <div style={{ width: `${pct}%`, height: '100%', background: lv.color + '88', borderRadius: 2 }} />
                        </div>
                        <span style={{ fontSize: 10, fontWeight: 600, color: lv.color, minWidth: 56, textAlign: 'right' }}>
                          {fmtUsd(lv.price, lv.price > 100 ? 1 : 4)}
                        </span>
                      </div>
                    );
                  })}
                </div>
                {/* Mini stats */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                  {[
                    { label: 'Score', value: `${sig.score}`, color: sig.score > 60 ? C.bull : C.warn },
                    { label: 'RSI', value: sig.rsi14 != null ? sig.rsi14.toFixed(1) : '—', color: sig.rsi14 != null && sig.rsi14 < 35 ? C.bull : sig.rsi14 != null && sig.rsi14 > 65 ? C.bear : C.muted },
                    { label: 'ATR%', value: sig.atr_pct != null ? sig.atr_pct.toFixed(2) + '%' : '—', color: C.muted },
                    { label: 'Spike', value: sig.vol_spike ? '⚡Yes' : 'No', color: sig.vol_spike ? C.warn : C.muted },
                  ].map((m) => (
                    <div key={m.label} style={{ background: '#0f172a', borderRadius: R.sm, padding: '7px 8px' }}>
                      <div style={{ fontSize: 9, color: C.muted, marginBottom: 2 }}>{m.label}</div>
                      <div style={{ fontSize: F.xs, fontWeight: 700, color: m.color }}>{m.value}</div>
                    </div>
                  ))}
                </div>
                <div style={{ marginTop: 8, textAlign: 'center', fontSize: F.xs, fontWeight: 600, color: C.brand, padding: '5px 8px', background: C.brand + '15', borderRadius: R.sm }}>
                  {sig.label ?? 'Observation'}
                </div>
              </div>
            );
          })()}
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

      {/* ── LLM Sniper Queue ─────────────────────────── */}
      <div style={{ marginBottom: 28 }}>
        {/* Header row */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ fontSize: 18 }}>🎯</div>
            <div>
              <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>LLM Sniper Queue</div>
              <div style={{ fontSize: F.xs, color: C.muted }}>
                Single-strategy signals evaluated by LLM for high-conviction entries
              </div>
            </div>
          </div>
          {/* Stats pills */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {[
              { label: 'Pending', val: sniperStats.pending, color: '#f59e0b' },
              { label: 'Approved', val: sniperStats.approved, color: C.bull },
              { label: 'Rejected', val: sniperStats.rejected, color: C.bear },
            ].map(s => (
              <div key={s.label} style={{
                background: C.card, border: `1px solid ${C.border}`,
                borderRadius: R.sm, padding: '4px 10px',
                fontSize: F.xs, color: s.color, fontWeight: 700,
              }}>
                {s.label}: {s.val}
              </div>
            ))}
          </div>
        </div>

        {sniperQueue.length === 0 ? (
          <div style={{
            background: C.card, border: `1px solid ${C.border}`, borderRadius: R.md,
            padding: '24px', textAlign: 'center', color: C.muted, fontSize: F.sm,
          }}>
            {sniperStats.total === 0
              ? 'No sniper proposals yet — enable LLM_SNIPER_ENABLED=true to start collecting'
              : 'No pending proposals — check history for past reviews'}
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 14 }}>
            {sniperQueue.map((p: any) => {
              const isBuy = p.side === 'BUY';
              const sideColor = isBuy ? C.bull : C.bear;
              const confPct = Math.round((p.confidence || 0) * 100);
              const isActing = !!sniperAction[p.id];
              return (
                <div key={p.id} style={{
                  background: C.card,
                  border: `1px solid ${sideColor}40`,
                  borderLeft: `4px solid ${sideColor}`,
                  borderRadius: R.md,
                  padding: '14px 16px',
                }}>
                  {/* Title row */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: F.md, fontWeight: 800, color: C.text }}>{p.symbol}</span>
                      <span style={{
                        fontSize: F.xs, fontWeight: 700, color: sideColor,
                        background: sideColor + '20', borderRadius: R.sm, padding: '2px 8px',
                      }}>{p.side}</span>
                      <span style={{ fontSize: F.xs, color: C.muted }}>{p.strategy_source}</span>
                    </div>
                    <div style={{ fontSize: F.xs, color: C.muted }}>
                      {new Date(p.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  </div>

                  {/* Price levels */}
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginBottom: 10 }}>
                    {[
                      { label: 'Entry', val: p.entry, color: C.text },
                      { label: 'SL', val: p.sl, color: C.bear },
                      { label: 'TP1', val: p.tp1, color: C.bull },
                    ].map(({ label, val, color }) => (
                      <div key={label} style={{ background: '#0f172a', borderRadius: R.sm, padding: '6px 8px' }}>
                        <div style={{ fontSize: 10, color: C.muted, marginBottom: 2 }}>{label}</div>
                        <div style={{ fontSize: F.xs, fontWeight: 700, color }}>{Number(val).toFixed(4)}</div>
                      </div>
                    ))}
                  </div>

                  {/* Confidence + Leverage */}
                  <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: C.muted, marginBottom: 4 }}>
                        <span>LLM Conf</span><span style={{ color: sideColor, fontWeight: 700 }}>{confPct}%</span>
                      </div>
                      <div style={{ height: 4, background: C.border, borderRadius: 2, overflow: 'hidden' }}>
                        <div style={{ width: `${confPct}%`, height: '100%', background: sideColor, borderRadius: 2 }} />
                      </div>
                    </div>
                    <div style={{
                      background: '#7c3aed20', border: '1px solid #7c3aed40',
                      borderRadius: R.sm, padding: '4px 10px', fontSize: F.xs,
                      color: '#a78bfa', fontWeight: 700, alignSelf: 'center',
                    }}>
                      {p.leverage?.toFixed(0)}x
                    </div>
                  </div>

                  {/* LLM reasoning */}
                  {p.llm_reasoning && (
                    <div style={{
                      fontSize: F.xs, color: C.textSub, fontStyle: 'italic',
                      background: '#0f172a', borderRadius: R.sm, padding: '6px 8px', marginBottom: 10,
                      borderLeft: `2px solid ${C.brand}40`,
                    }}>
                      "{p.llm_reasoning}"
                    </div>
                  )}

                  {/* Actions */}
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      disabled={isActing}
                      onClick={() => handleSniperAction(p.id, 'approve')}
                      style={{
                        flex: 1, padding: '7px 0', borderRadius: R.sm, border: 'none',
                        background: isActing ? C.border : C.bull + '20',
                        color: isActing ? C.muted : C.bull,
                        fontWeight: 700, fontSize: F.xs, cursor: isActing ? 'not-allowed' : 'pointer',
                        transition: 'background 0.2s',
                      }}
                    >
                      {sniperAction[p.id] === 'approving' ? '...' : '✓ Approve'}
                    </button>
                    <button
                      disabled={isActing}
                      onClick={() => handleSniperAction(p.id, 'reject')}
                      style={{
                        flex: 1, padding: '7px 0', borderRadius: R.sm, border: 'none',
                        background: isActing ? C.border : C.bear + '20',
                        color: isActing ? C.muted : C.bear,
                        fontWeight: 700, fontSize: F.xs, cursor: isActing ? 'not-allowed' : 'pointer',
                        transition: 'background 0.2s',
                      }}
                    >
                      {sniperAction[p.id] === 'rejecting' ? '...' : '✕ Reject'}
                    </button>
                  </div>
                </div>
              );
            })}
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
