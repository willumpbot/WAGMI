'use client';

import React, { useEffect, useState, useRef } from 'react';
import { useRouter } from 'next/router';

type MostRecentTrade = {
  strategyId: string;
  name: string;
  market: string;
  action: string;
  price: number;
  ts: string;
};

type Summary = {
  updatedAt?: string;
  regime?: string;
  status?: string;
  errors?: number;
  mostRecentTrade?: MostRecentTrade | null;
};

type LatestSignal = {
  label: string;
  score: number;
  market: string;
  ts: string;
};

type Strategy = {
  id: string;
  name: string;
  markets: string[];
  status: string;
  lastEvaluated?: string;
  latestSignal?: LatestSignal | null;
};

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
  zones: {
    deepAccum: number;
    accum: number;
    distrib: number;
    safeDistrib: number;
  };
};

type SignalsPayload = {
  last_updated?: string;
  regime?: string;
  signals?: Record<string, Signal>;
};

// Map our symbol names to TradingView symbol IDs
const TV_SYMBOLS: Record<string, string> = {
  BTC: 'BINANCE:BTCUSDT',
  SOL: 'BINANCE:SOLUSDT',
  HYPE: 'BYBIT:HYPEUSDT',
};

const SYMBOLS = ['BTC', 'SOL', 'HYPE'];

function resolveApiBase(): string {
  const envVal = (process.env.NEXT_PUBLIC_API_URL as string | undefined) || (process.env.NEXT_PUBLIC_API_BASE_URL as string | undefined);
  if (envVal && envVal.trim().length > 0) return envVal;
  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (host && host !== 'localhost' && host !== '127.0.0.1') {
      return 'https://nunuirl-platform.onrender.com';
    }
  }
  return 'http://localhost:8000';
}

const fmtUsd = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 2,
});

// ─── TradingView Chart ───────────────────────────────────────────────────────

function TradingViewChart({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const tvSymbol = TV_SYMBOLS[symbol] || `BINANCE:${symbol}USDT`;

  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = '';

    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol: tvSymbol,
      interval: '60',
      timezone: 'Etc/UTC',
      theme: 'light',
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

  return (
    <div className="tradingview-widget-container" ref={containerRef} style={{ height: 400, width: '100%' }} />
  );
}

// ─── Signal Label Color ──────────────────────────────────────────────────────

function getLabelColor(label: string) {
  if (label.includes('Aggressive Accumulation')) return '#16a34a';
  if (label.includes('Accumulation')) return '#65a30d';
  if (label.includes('Aggressive Distribution')) return '#dc2626';
  if (label.includes('Distribution')) return '#ea580c';
  return '#6b7280';
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function Home() {
  const [summary, setSummary] = useState<Summary>({});
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [signalsData, setSignalsData] = useState<SignalsPayload>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeChart, setActiveChart] = useState<string>('BTC');
  const router = useRouter();
  const apiBase = resolveApiBase();

  useEffect(() => {
    const fetchData = async () => {
      try {
        setError(null);
        const [summaryRes, strategiesRes, signalsRes] = await Promise.all([
          fetch(`${apiBase}/v1/summary`, { cache: 'no-store' }).catch(() => null),
          fetch(`${apiBase}/v1/strategies`, { cache: 'no-store' }).catch(() => null),
          fetch(`${apiBase}/v1/signals`, { cache: 'no-store' }).catch(() => null),
        ]);

        if (summaryRes?.ok) {
          setSummary((await summaryRes.json()) || {});
        }
        if (strategiesRes?.ok) {
          const data = await strategiesRes.json();
          setStrategies(Array.isArray(data) ? data : data?.items || []);
        }
        if (signalsRes?.ok) {
          setSignalsData((await signalsRes.json()) || {});
        }

        setLoading(false);
      } catch (e: any) {
        setError(e?.message || 'Failed to load data');
        setLoading(false);
      }
    };

    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [apiBase]);

  const formatTime = (isoString?: string) => {
    if (!isoString) return '—';
    try { return new Date(isoString).toLocaleTimeString(); } catch { return '—'; }
  };

  const signals = signalsData.signals || {};

  if (loading) {
    return <div style={{ padding: 20 }}>Loading...</div>;
  }

  const status = summary?.status || (error ? 'degraded' : 'ok');
  const regime = signalsData?.regime || summary?.regime || 'Neutral';

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, marginBottom: 8, fontSize: 24 }}>Dashboard</h1>
        <div style={{ display: 'flex', gap: 16, fontSize: 14, color: '#666', alignItems: 'center', flexWrap: 'wrap' }}>
          <span>Updated: {signalsData.last_updated ? new Date(signalsData.last_updated).toLocaleTimeString() : formatTime(summary?.updatedAt)}</span>
          <span>Regime: <strong>{regime}</strong></span>
          {status === 'degraded' && (
            <span style={{ padding: '2px 8px', borderRadius: 4, background: '#ff9800', color: '#fff', fontSize: 12, fontWeight: 600 }}>
              Degraded
            </span>
          )}
          {error && <span style={{ fontSize: 12, color: '#f44336' }}>Error: {error}</span>}
        </div>
      </div>

      {/* Charts Section */}
      <div style={{ marginBottom: 32 }}>
        <h2 style={{ fontSize: 18, marginBottom: 12 }}>Charts (1H)</h2>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          {SYMBOLS.map((sym) => (
            <button
              key={sym}
              onClick={() => setActiveChart(sym)}
              style={{
                padding: '8px 20px',
                border: activeChart === sym ? '2px solid #111' : '1px solid #ddd',
                borderRadius: 8,
                background: activeChart === sym ? '#111' : '#fff',
                color: activeChart === sym ? '#fff' : '#333',
                cursor: 'pointer',
                fontSize: 14,
                fontWeight: 600,
              }}
            >
              {sym}
            </button>
          ))}
        </div>
        <div style={{ border: '1px solid #e5e7eb', borderRadius: 10, overflow: 'hidden', background: '#fff' }}>
          <TradingViewChart symbol={activeChart} />
        </div>
      </div>

      {/* Signal Cards for all 3 symbols */}
      <div style={{ marginBottom: 32 }}>
        <h2 style={{ fontSize: 18, marginBottom: 12 }}>Market Signals</h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 }}>
          {SYMBOLS.map((sym) => {
            const s = signals[sym];
            if (!s) {
              return (
                <div key={sym} style={{ border: '1px solid #ddd', borderRadius: 10, padding: 20, background: '#fff' }}>
                  <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>{sym}</div>
                  <div style={{ color: '#9ca3af', fontSize: 13 }}>Waiting for signal data...</div>
                </div>
              );
            }
            const labelColor = getLabelColor(s.label);
            const trendUp = s.sma20 > s.sma50;
            return (
              <div key={sym} style={{ border: '1px solid #ddd', borderRadius: 10, padding: 20, background: '#fff' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 18, fontWeight: 700 }}>{s.symbol}</span>
                    {s.vol_spike && <span title="Volume spike">*</span>}
                  </div>
                  <div style={{ padding: '4px 10px', borderRadius: 12, background: labelColor, color: '#fff', fontSize: 11, fontWeight: 600 }}>
                    Score: {s.score}
                  </div>
                </div>

                <div style={{ fontSize: 14, fontWeight: 600, color: labelColor, marginBottom: 12 }}>
                  {s.label}
                </div>

                <div style={{ fontSize: 13, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                  <div><strong>Price:</strong> {fmtUsd.format(s.price)}</div>
                  <div><strong>RSI:</strong> {s.rsi14 !== undefined ? s.rsi14.toFixed(1) : '—'}</div>
                  <div><strong>Trend:</strong> <span style={{ color: trendUp ? '#16a34a' : '#dc2626' }}>{trendUp ? 'Up' : 'Down'}</span></div>
                  <div><strong>ATR:</strong> {typeof s.atr_pct === 'number' ? s.atr_pct.toFixed(2) + '%' : fmtUsd.format(s.atr14)}</div>
                </div>

                <div style={{ fontSize: 12, color: '#6b7280', marginTop: 12, paddingTop: 8, borderTop: '1px solid #f0f0f0' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                    <div><strong>Deep Accum:</strong> {fmtUsd.format(s.zones.deepAccum)}</div>
                    <div><strong>Distrib:</strong> {fmtUsd.format(s.zones.distrib)}</div>
                    <div><strong>Accum:</strong> {fmtUsd.format(s.zones.accum)}</div>
                    <div><strong>Safe Distrib:</strong> {fmtUsd.format(s.zones.safeDistrib)}</div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Most Recent Trade */}
      {summary?.mostRecentTrade && (
        <div style={{ marginBottom: 32 }}>
          <h2 style={{ fontSize: 18, marginBottom: 12 }}>Most Recent Trade</h2>
          <div style={{ border: '1px solid #ddd', borderRadius: 10, padding: 16, background: '#fff' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>
                  {summary.mostRecentTrade.name} - {summary.mostRecentTrade.market}
                </div>
                <div style={{ fontSize: 14, color: '#666' }}>
                  {summary.mostRecentTrade.action} @ ${summary.mostRecentTrade.price?.toFixed(2) || '—'}
                </div>
                <div style={{ fontSize: 12, color: '#999' }}>{formatTime(summary.mostRecentTrade.ts)}</div>
              </div>
              <button
                onClick={() => router.push(`/strategies/${summary.mostRecentTrade!.strategyId}`)}
                style={{ padding: '8px 16px', border: '1px solid #444', borderRadius: 6, background: '#111', color: '#eee', cursor: 'pointer', fontSize: 13 }}
              >
                View logs
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Strategies */}
      <div style={{ marginBottom: 32 }}>
        <h2 style={{ fontSize: 18, marginBottom: 12 }}>Strategies</h2>
        {strategies.length === 0 && <p style={{ color: '#666' }}>No strategy data yet.</p>}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 }}>
          {strategies.map((strat) => (
            <div key={strat.id} style={{ border: '1px solid #ddd', borderRadius: 10, padding: 16, background: '#fff' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <div style={{ fontSize: 16, fontWeight: 600 }}>{strat.name}</div>
                <div style={{ padding: '4px 8px', borderRadius: 4, background: strat.status === 'Active' || strat.status === 'live' ? '#4caf50' : '#9e9e9e', color: '#fff', fontSize: 11, fontWeight: 600 }}>
                  {strat.status}
                </div>
              </div>
              <div style={{ fontSize: 13, color: '#666', marginBottom: 8 }}>Markets: {strat.markets.join(', ')}</div>
              <div style={{ fontSize: 13, color: '#666', marginBottom: 12 }}>Last evaluated: {formatTime(strat.lastEvaluated)}</div>
              {strat.latestSignal && (
                <div style={{ fontSize: 13, padding: 8, background: '#f9fafb', border: '1px solid #eee', borderRadius: 6, marginBottom: 12 }}>
                  <strong>Signal:</strong> {strat.latestSignal.label} - {strat.latestSignal.score}/100 ({strat.latestSignal.market})
                </div>
              )}
              <button
                onClick={() => router.push(`/strategies/${strat.id}`)}
                style={{ width: '100%', padding: '8px 16px', border: '1px solid #444', borderRadius: 6, background: '#111', color: '#eee', cursor: 'pointer', fontSize: 13 }}
              >
                View logs
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div style={{ fontSize: 11, color: '#999', padding: '16px 0', borderTop: '1px solid #eee', textAlign: 'center' }}>
        <strong>Disclaimer:</strong> Informational only. Not financial advice. Always do your own research.
      </div>
    </div>
  );
}
