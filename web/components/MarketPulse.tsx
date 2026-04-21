import React from 'react';
import { C } from '../src/theme';
import { useApi } from '../hooks/useApi';
import ScanningEmptyState from './ScanningEmptyState';

type Signal = {
  symbol: string;
  price: number;
  sma20?: number;
  sma50?: number;
  rsi14?: number;
  atr_pct?: number;
  score?: number;
  label?: string;
};

type SignalsResponse = {
  signals?: Record<string, Signal>;
  last_updated?: string;
};

const SYMBOLS = ['BTC', 'ETH', 'SOL', 'HYPE'] as const;

function scoreColor(score: number | undefined): string {
  if (score == null) return C.muted;
  if (score >= 70) return C.bull;
  if (score >= 55) return C.brandMid;
  if (score <= 30) return C.bear;
  if (score <= 45) return C.warn;
  return C.info;
}

function priceDigits(symbol: string, price: number): number {
  if (!price) return 2;
  if (symbol === 'BTC' || symbol === 'ETH') return 0;
  if (symbol === 'SOL') return 2;
  if (symbol === 'HYPE') return 3;
  return 2;
}

/**
 * Per-symbol market state strip. BTC / ETH / SOL / HYPE each as its own card
 * with price, momentum score, label (Accumulation/Distribution/Neutral), and RSI.
 *
 * Derived from `/v1/signals` (lightweight TA snapshot). Refreshes every 20s.
 * Graceful degradation when an API is offline or a symbol has no data.
 */
export default function MarketPulse() {
  const { data, error } = useApi<SignalsResponse>('/v1/signals', { refreshInterval: 20_000 });

  const sigs = data?.signals ?? {};
  const hasAny = Object.keys(sigs).length > 0;

  if (!hasAny) {
    // Show a subtle scanning state instead of empty/hidden space
    return (
      <div
        style={{
          padding: '14px 16px',
          background: 'rgba(13,13,20,0.6)',
          border: '1px solid rgba(255,255,255,0.05)',
          borderRadius: 10,
        }}
      >
        <ScanningEmptyState
          label={error ? 'Market data offline' : 'Warming up market feed'}
          sub={error ? 'Retrying in the background' : 'Pulling live BTC / ETH / SOL / HYPE ticks'}
          compact
        />
      </div>
    );
  }

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
        gap: 10,
      }}
    >
      {SYMBOLS.map((sym) => {
        const s = sigs[sym];
        const score = s?.score;
        const label = s?.label ?? '—';
        const price = s?.price ?? 0;
        const rsi = s?.rsi14;
        const sma20 = s?.sma20;
        const trendUp = sma20 != null && price > sma20;
        const color = scoreColor(score);
        const digits = priceDigits(sym, price);

        return (
          <div
            key={sym}
            className="pulse-card"
            style={{
              padding: '14px 16px',
              background: 'rgba(13,13,20,0.8)',
              border: `1px solid ${color}25`,
              borderRadius: 10,
              transition: 'transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease',
              position: 'relative',
              overflow: 'hidden',
            }}
          >
            {/* Accent stripe */}
            <div
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                bottom: 0,
                width: 3,
                background: color,
                opacity: 0.6,
              }}
            />
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <div style={{ fontSize: 13, fontWeight: 800, color: C.text, fontFamily: 'JetBrains Mono, monospace', letterSpacing: 0.5 }}>
                {sym}
              </div>
              {trendUp != null && (
                <div style={{
                  fontSize: 9,
                  fontWeight: 700,
                  padding: '1px 6px',
                  borderRadius: 4,
                  background: trendUp ? C.bullLight : C.bearLight,
                  color: trendUp ? C.bull : C.bear,
                  letterSpacing: 0.5,
                }}>
                  {trendUp ? '↑ ABOVE 20' : '↓ BELOW 20'}
                </div>
              )}
            </div>
            <div style={{
              fontSize: 18,
              fontWeight: 700,
              color: C.text,
              fontFamily: 'JetBrains Mono, monospace',
              letterSpacing: -0.3,
              lineHeight: 1.1,
              marginBottom: 6,
            }}>
              {price > 0 ? `$${price.toLocaleString(undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits })}` : '—'}
            </div>
            <div style={{
              fontSize: 10,
              fontWeight: 700,
              color,
              textTransform: 'uppercase',
              letterSpacing: 1,
              marginBottom: 4,
            }}>
              {label}
            </div>
            <div style={{ display: 'flex', gap: 10, fontSize: 10, color: C.muted, fontFamily: 'JetBrains Mono, monospace' }}>
              {score != null && <span>score {score}</span>}
              {rsi != null && <span>rsi {rsi.toFixed(0)}</span>}
            </div>
          </div>
        );
      })}
      <style jsx>{`
        .pulse-card:hover {
          transform: translateY(-2px);
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
        }
      `}</style>
    </div>
  );
}
