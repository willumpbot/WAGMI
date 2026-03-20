import React, { useEffect, useState } from 'react';
import { resolveApiBase } from '../src/api';

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
  errors?: string[];
};

export default function Signals() {
  const [data, setData] = useState<SignalsPayload>({});
  const [loading, setLoading] = useState(true);
  const apiBase = resolveApiBase();

  // Friendly number/currency formatters
  const fmtUsd = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 4,
  });
  const fmtNum = (n: number, digits = 1) =>
    new Intl.NumberFormat('en-US', { maximumFractionDigits: digits }).format(n);

  function buildMicoPrompt(payload: any) {
    const s = payload?.signals || {};
    const lines: string[] = [
      'Market Signals',
      `Updated: ${payload?.last_updated || '-'}`,
      `Regime: ${payload?.regime || 'Neutral'}`,
      `Errors: ${payload?.errors?.length || 0}`,
      '',
    ];
    Object.values(s as Record<string, any>).forEach((x: any) => {
      lines.push(
        x.symbol,
        String(x.score ?? ''),
        x.label || '',
        `Price: $${x.price?.toFixed?.(4)}`,
        `SMA20 / SMA50: $${x.sma20?.toFixed?.(4)} / $${x.sma50?.toFixed?.(4)}`,
        `RSI14: ${x.rsi14?.toFixed?.(1) ?? '-'}`,
        `ATR14: $${x.atr14?.toFixed?.(4) ?? '-'} (${(x.atr_pct ?? 0).toFixed(2)}%)`,
        `Deep Accum: $${x.zones?.deepAccum?.toFixed?.(4)}`,
        `Accum: $${x.zones?.accum?.toFixed?.(4)}`,
        `Distrib: $${x.zones?.distrib?.toFixed?.(4)}`,
        `Safe Distrib: $${x.zones?.safeDistrib?.toFixed?.(4)}`,
        ''
      );
    });
    return [
      'You are Mico Copilot. Analyze the following Market Signals snapshot and give a concise, plain-English walkthrough:',
      '- Brief market regime take',
      '- Per-asset summary: label meaning, what drives score (0–100), risks',
      '- Explain ATR(14) and zones vs current price',
      '- Call out trend (SMA20/50), RSI extremes, volume spikes',
      '- Observational tone only, no directives',
      '',
      'Snapshot:',
      lines.join('\n'),
    ].join('\n');
  }

  useEffect(() => {
    const fetcher = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/signals`);
        if (res.ok) {
          const json = await res.json();
          setData(json);
          setLoading(false);
        }
      } catch (e) {
        console.error('Signals fetch error:', e);
      }
    };

    fetcher();
    const interval = setInterval(fetcher, 10000); // Poll every 10s
    return () => clearInterval(interval);
  }, [apiBase]);

  const signals = data.signals || {};
  const signalList = Object.values(signals);

  const getLabelColor = (label: string) => {
    if (label.includes('Aggressive Accumulation')) return '#4caf50';
    if (label.includes('Accumulation')) return '#8bc34a';
    if (label.includes('Aggressive Distribution')) return '#f44336';
    if (label.includes('Distribution')) return '#ff9800';
    return '#9e9e9e';
  };

  if (loading) {
    return <div style={{ padding: 20 }}>Loading signals...</div>;
  }

  return (
    <div style={{ padding: '0 20px' }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>Market Signals</h2>
        <div style={{ fontSize: 12, color: '#666' }}>
          <div>Updated: {data.last_updated ? new Date(data.last_updated).toLocaleTimeString() : '—'}</div>
          <div>Regime: {data.regime || 'Neutral'}</div>
          {data.errors && data.errors.length > 0 && (
            <div style={{ color: '#f44336' }}>Errors: {data.errors.length}</div>
          )}
        </div>
        <button
          onClick={() => navigator.clipboard?.writeText(buildMicoPrompt(data))}
          style={{ marginLeft: 'auto', padding: '6px 10px', border: '1px solid #444', borderRadius: 6, background: '#111', color: '#eee', cursor: 'pointer' }}
        >
          Copy for Mico
        </button>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
          gap: 16,
          marginBottom: 20,
        }}
      >
        {signalList.length === 0 && <p>No signals available yet. Wait ~60s for initial data.</p>}
        {signalList.map((s) => (
          <div
            key={s.symbol}
            style={{
              border: '1px solid #ddd',
              borderRadius: 8,
              padding: 16,
              backgroundColor: '#fafafa',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <strong style={{ fontSize: 18 }}>{s.symbol}</strong>
                {s.vol_spike && <span style={{ fontSize: 16 }}>🚀</span>}
              </div>
              <div
                style={{
                  fontSize: 12,
                  padding: '4px 8px',
                  borderRadius: 6,
                  backgroundColor: getLabelColor(s.label),
                  color: '#fff',
                  fontWeight: 600,
                }}
                title="Signal score (0–100): higher = stronger alignment across trend, volatility, RSI, and volume"
              >
                Score: {s.score}
              </div>
            </div>

            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: getLabelColor(s.label),
                marginBottom: 12,
              }}
            >
              {s.label}
            </div>

            <div style={{ fontSize: 13, marginBottom: 4 }}>
              <strong>Price:</strong> {fmtUsd.format(s.price)}
            </div>
            <div style={{ fontSize: 13, marginBottom: 4 }}>
              <strong>SMA20 / SMA50:</strong> {fmtUsd.format(s.sma20)} / {fmtUsd.format(s.sma50)}
            </div>
            <div style={{ fontSize: 13, marginBottom: 4 }}>
              <strong>RSI14:</strong> {s.rsi14 !== undefined ? s.rsi14.toFixed(1) : '—'}
            </div>
            <div style={{ fontSize: 13, marginBottom: 4 }}>
              <strong title="ATR(14) proxy: 14‑period volatility using rolling standard deviation of closes">ATR(14):</strong> {fmtUsd.format(s.atr14)}
              {typeof (s as any).atr_pct === 'number' && (
                <span style={{ color: '#666' }}> ({fmtNum((s as any).atr_pct, 2)}%)</span>
              )}
            </div>

            <div style={{ fontSize: 12, color: '#666', marginTop: 12, paddingTop: 8, borderTop: '1px solid #ddd' }}>
              <div style={{ marginBottom: 2 }}>
                <strong>Deep Accum:</strong> {fmtUsd.format(s.zones.deepAccum)}
              </div>
              <div style={{ marginBottom: 2 }}>
                <strong>Accum:</strong> {fmtUsd.format(s.zones.accum)}
              </div>
              <div style={{ marginBottom: 2 }}>
                <strong>Distrib:</strong> {fmtUsd.format(s.zones.distrib)}
              </div>
              <div>
                <strong>Safe Distrib:</strong> {fmtUsd.format(s.zones.safeDistrib)}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div style={{ fontSize: 11, color: '#777', padding: '12px 0', borderTop: '1px solid #eee' }}>
        <div style={{ marginBottom: 6 }}>
          <strong>How to read:</strong> Score ranges 0–100. Higher means stronger alignment of trend (SMA20/50), volatility (ATR), RSI, and volume.
        </div>
        <div style={{ marginBottom: 6 }}>
          <strong>Zones:</strong> Prices relative to SMA20 ± k·ATR define Accumulation/Distribution bands; k varies by asset risk.
        </div>
        <div>
          <strong>Disclaimer:</strong> Informational only. Verify on-chain. Never DM-first. $MICO is independent and unaffiliated with Microsoft.
        </div>
      </div>
    </div>
  );
}
