import React, { useEffect, useState, useRef } from 'react';
import type { LlmDecision, LlmMarketView, ActivityEvent, BacktestResult } from '../src/types';
import { C, R, F, fmtUsd as themeFmtUsd } from '../src/theme';

// ─── Types ───────────────────────────────────────────────────────────────────

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

// ─── Helpers ─────────────────────────────────────────────────────────────────

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

const fmt = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 4,
});

// Map our symbol names to TradingView symbol IDs
const TV_SYMBOLS: Record<string, string> = {
  BTC: 'BINANCE:BTCUSDT',
  SOL: 'BINANCE:SOLUSDT',
  HYPE: 'BYBIT:HYPEUSDT',
};

// ─── LLM Helpers ─────────────────────────────────────────────────────────────

function getActionStyle(action: string): { label: string; color: string; bgColor: string } {
  const a = (action || '').toLowerCase();
  if (a === 'proceed' || a === 'go')
    return { label: 'TRADE', color: '#16a34a', bgColor: '#dcfce7' };
  if (a === 'flip' || a === 'reverse')
    return { label: 'FLIP', color: '#7c3aed', bgColor: '#ede9fe' };
  return { label: 'SKIP', color: '#6b7280', bgColor: '#f3f4f6' };
}

function getBiasStyle(bias: string): { color: string; bgColor: string } {
  if (bias === 'bullish') return { color: '#16a34a', bgColor: '#dcfce7' };
  if (bias === 'volatile') return { color: '#7c3aed', bgColor: '#ede9fe' };
  if (bias === 'mixed') return { color: '#ea580c', bgColor: '#fff7ed' };
  return { color: '#6b7280', bgColor: '#f3f4f6' };
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? '#16a34a' : pct >= 45 ? '#eab308' : '#dc2626';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ flex: 1, height: 6, background: '#e5e7eb', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3, transition: 'width 0.3s' }} />
      </div>
      <span style={{ fontSize: 12, fontWeight: 600, color, minWidth: 34 }}>{pct}%</span>
    </div>
  );
}

function timeAgo(isoOrTs: string | number | null): string {
  if (!isoOrTs) return '';
  try {
    const ts = typeof isoOrTs === 'number' ? isoOrTs * 1000 : new Date(isoOrTs).getTime();
    const diff = Math.floor((Date.now() - ts) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  } catch {
    return '';
  }
}

// ─── LLM Brain Banner ────────────────────────────────────────────────────────

function LlmBrainBanner({ view }: { view: LlmMarketView | null }) {
  if (!view) {
    return (
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 10, padding: '14px 20px', marginBottom: 24, fontSize: 13, color: C.muted }}>
        LLM Brain View loading...
      </div>
    );
  }

  if (!view.has_data) {
    return (
      <div style={{ background: C.warn + '12', border: `1px solid ${C.warn}33`, borderRadius: 10, padding: '14px 20px', marginBottom: 24 }}>
        <div style={{ fontWeight: 600, fontSize: 14, color: C.warn, marginBottom: 4 }}>LLM not running yet</div>
        <div style={{ fontSize: 13, color: C.textSub }}>
          Start the bot with <code style={{ background: C.surfaceHover, padding: '1px 4px', borderRadius: 3, color: C.brand }}>LLM_MODE=1 LLM_MULTI_AGENT=true</code> to see AI market analysis here.
        </div>
      </div>
    );
  }

  const biasStyle = getBiasStyle(view.overall_bias);
  const symbols = Object.keys(view.per_symbol);

  return (
    <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: '16px 20px', marginBottom: 24, color: '#e2e8f0' }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 15, fontWeight: 700, letterSpacing: 0.3 }}>LLM Brain</span>
          <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, background: '#1e293b', color: '#94a3b8' }}>
            ADVISORY MODE
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, color: '#64748b' }}>
          <span>Regime: <strong style={{ color: '#cbd5e1' }}>{view.regime}</strong></span>
          <span
            style={{
              padding: '2px 10px', borderRadius: 10,
              background: biasStyle.bgColor, color: biasStyle.color,
              fontWeight: 700, fontSize: 11,
            }}
          >
            {(view.overall_bias || 'neutral').toUpperCase()}
          </span>
          {view.last_updated && (
            <span style={{ color: '#475569' }}>{timeAgo(view.last_updated)}</span>
          )}
        </div>
      </div>

      {/* Per-symbol stance */}
      {symbols.length > 0 && (
        <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
          {symbols.map((sym) => {
            const d = view.per_symbol[sym];
            const style = getActionStyle(d.action);
            return (
              <div key={sym} style={{ display: 'flex', alignItems: 'center', gap: 6, background: '#1e293b', borderRadius: 8, padding: '6px 12px' }}>
                <span style={{ fontWeight: 700, fontSize: 13 }}>{sym}</span>
                <span style={{ fontSize: 11, fontWeight: 700, padding: '1px 7px', borderRadius: 6, background: style.bgColor, color: style.color }}>
                  {style.label}
                </span>
                <span style={{ fontSize: 11, color: '#64748b' }}>{Math.round(d.confidence * 100)}%</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Summary text */}
      {view.summary && (
        <div style={{ fontSize: 13, color: '#94a3b8', lineHeight: 1.6, borderTop: '1px solid #1e293b', paddingTop: 10 }}>
          {view.summary}
        </div>
      )}

      {/* Decision counts */}
      {view.decision_counts && (
        <div style={{ display: 'flex', gap: 16, marginTop: 10, fontSize: 11, color: '#475569' }}>
          <span>Last 10: <strong style={{ color: '#16a34a' }}>{view.decision_counts.proceed} trade</strong></span>
          <span><strong style={{ color: '#6b7280' }}>{view.decision_counts.flat} skip</strong></span>
          <span><strong style={{ color: '#7c3aed' }}>{view.decision_counts.flip} flip</strong></span>
          {view.avg_confidence !== null && (
            <span>avg confidence <strong style={{ color: '#e2e8f0' }}>{Math.round((view.avg_confidence || 0) * 100)}%</strong></span>
          )}
        </div>
      )}
    </div>
  );
}

// ─── LLM Decision Card (per-symbol) ──────────────────────────────────────────

function LlmDecisionPanel({ decision }: { decision: LlmDecision | null }) {
  if (!decision) {
    return (
      <div style={{ padding: '12px 16px', background: '#f8fafc', borderRadius: 8, fontSize: 13, color: '#94a3b8' }}>
        No LLM analysis for this symbol yet.
      </div>
    );
  }

  const actionStyle = getActionStyle(decision.action);

  return (
    <div style={{ padding: '14px 16px', background: '#0f172a', borderRadius: 8, color: '#e2e8f0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10, gap: 8, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>LLM Decision</div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span
              style={{
                fontSize: 16, fontWeight: 800, padding: '3px 12px', borderRadius: 6,
                background: actionStyle.bgColor, color: actionStyle.color,
              }}
            >
              {actionStyle.label}
            </span>
            {decision.is_veto && (
              <span style={{ fontSize: 11, padding: '2px 8px', background: '#fef2f2', color: '#dc2626', borderRadius: 5, fontWeight: 600 }}>
                VETOED
              </span>
            )}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>Regime</div>
          <div style={{ fontSize: 13, fontWeight: 600, color: '#cbd5e1' }}>{decision.regime || '—'}</div>
        </div>
      </div>

      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>Confidence</div>
        <ConfidenceBar value={decision.confidence} />
      </div>

      {decision.notes && (
        <div style={{ fontSize: 12, color: '#94a3b8', lineHeight: 1.6, borderTop: '1px solid #1e293b', paddingTop: 8, marginTop: 4 }}>
          {decision.notes}
        </div>
      )}

      {decision.gate_reason && !decision.allowed && (
        <div style={{ fontSize: 11, marginTop: 8, padding: '6px 10px', background: '#1e293b', borderRadius: 5, color: '#94a3b8' }}>
          Blocked: {decision.gate_reason}
        </div>
      )}

      <div style={{ display: 'flex', gap: 12, marginTop: 10, fontSize: 11, color: '#475569' }}>
        <span>{decision.mode}</span>
        {decision.model && <span>{decision.model}</span>}
        <span>{timeAgo(decision.ts_iso || decision.ts)}</span>
      </div>
    </div>
  );
}

// ─── Signal Strength ─────────────────────────────────────────────────────────

function getSignalStrength(signal: Signal): {
  direction: string;
  color: string;
  bgColor: string;
  strength: string;
  emoji: string;
} {
  const label = signal.label || '';

  if (label.includes('Aggressive Accumulation')) {
    return { direction: 'BULLISH', color: '#16a34a', bgColor: '#dcfce7', strength: 'Strong', emoji: '' };
  }
  if (label.includes('Accumulation')) {
    return { direction: 'LEANING BULLISH', color: '#65a30d', bgColor: '#ecfccb', strength: 'Moderate', emoji: '' };
  }
  if (label.includes('Aggressive Distribution')) {
    return { direction: 'BEARISH', color: '#dc2626', bgColor: '#fee2e2', strength: 'Strong', emoji: '' };
  }
  if (label.includes('Distribution')) {
    return { direction: 'LEANING BEARISH', color: '#ea580c', bgColor: '#fff7ed', strength: 'Moderate', emoji: '' };
  }
  return { direction: 'NEUTRAL', color: '#6b7280', bgColor: '#f3f4f6', strength: 'Weak', emoji: '' };
}

// ─── TradingView Chart ───────────────────────────────────────────────────────

function TradingViewChart({ symbol }: { symbol: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const tvSymbol = TV_SYMBOLS[symbol] || `BINANCE:${symbol}USDT`;

  useEffect(() => {
    if (!containerRef.current) return;
    containerRef.current.innerHTML = '';

    // Required: inner widget div (TradingView embed structure)
    const widgetDiv = document.createElement('div');
    widgetDiv.className = 'tradingview-widget-container__widget';
    widgetDiv.style.cssText = 'height:100%;width:100%';
    containerRef.current.appendChild(widgetDiv);

    // Config script: type + textContent (not innerHTML) is the correct pattern
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

  return (
    <div className="tradingview-widget-container" ref={containerRef} style={{ height: 400, width: '100%' }} />
  );
}

// ─── Activity Feed ────────────────────────────────────────────────────────────

function ActivityFeed({ events }: { events: ActivityEvent[] }) {
  if (events.length === 0) {
    return (
      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.md, padding: '16px 20px', marginBottom: 24 }}>
        <div style={{ fontSize: F.sm, fontWeight: 600, color: C.text, marginBottom: 6 }}>Bot Activity</div>
        <div style={{ fontSize: F.sm, color: C.muted }}>
          No activity yet. Start the bot with <code style={{ background: C.surfaceHover, padding: '1px 4px', borderRadius: R.xs, color: C.brand }}>LLM_MODE=1</code> to see live decisions here.
        </div>
      </div>
    );
  }

  return (
    <div style={{ marginBottom: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
        <div style={{ fontSize: F.sm, fontWeight: 600, color: C.text }}>
          Bot Activity
          <span style={{ marginLeft: 8, display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: '#16a34a', fontWeight: 400 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#16a34a', display: 'inline-block' }} />
            live
          </span>
        </div>
        <span style={{ fontSize: F.xs, color: C.muted }}>last {events.length} events</span>
      </div>

      <div style={{ border: `1px solid ${C.border}`, borderRadius: R.md, overflow: 'hidden', maxHeight: 340, overflowY: 'auto' }}>
        {events.map((event, i) => (
          <div
            key={`${event.ts}-${i}`}
            style={{
              padding: '12px 16px',
              borderBottom: i < events.length - 1 ? `1px solid ${C.border}` : 'none',
              background: C.card,
            }}
          >
            {/* Header row */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    padding: '2px 7px',
                    borderRadius: 4,
                    background: event.badge_color + '18',
                    color: event.badge_color,
                    letterSpacing: 0.3,
                  }}
                >
                  {event.badge}
                </span>
                {event.symbol && (
                  <span style={{ fontSize: 13, fontWeight: 700, color: '#111' }}>{event.symbol}</span>
                )}
              </div>
              <span style={{ fontSize: F.xs, color: C.muted }}>{timeAgo(event.ts_iso || event.ts)}</span>
            </div>

            {/* Detail line */}
            <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 5 }}>{event.detail}</div>

            {/* Scalp insight */}
            {event.scalp_insight && (
              <div
                style={{
                  fontSize: F.xs,
                  color: C.textSub,
                  background: C.surfaceHover,
                  borderLeft: `3px solid ${event.badge_color}`,
                  padding: '4px 8px',
                  borderRadius: '0 4px 4px 0',
                  lineHeight: 1.5,
                }}
              >
                {event.scalp_insight}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Mode Banner ─────────────────────────────────────────────────────────────

function ModeBanner({ mode }: { mode: string | null }) {
  if (!mode) return null;
  const isAdvisory = mode === 'ADVISORY' || mode === 'advisory';
  return (
    <div
      style={{
        padding: '10px 16px',
        marginBottom: 20,
        borderRadius: R.md,
        background: isAdvisory ? C.info + '12' : C.bull + '12',
        border: `1px solid ${isAdvisory ? C.info : C.bull}33`,
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        fontSize: F.sm,
      }}
    >
      <span style={{ fontSize: 16 }}>{isAdvisory ? 'ℹ️' : '✅'}</span>
      <span style={{ color: isAdvisory ? '#93c5fd' : '#86efac' }}>
        Bot is in <strong>{mode}</strong> mode —{' '}
        {isAdvisory
          ? 'it analyses and logs decisions but does NOT execute trades. All signals here are advisory only.'
          : 'the LLM has execution access. Signals shown reflect live AI decisions.'}
      </span>
    </div>
  );
}

// ─── Risk Calculator ─────────────────────────────────────────────────────────

function RiskCalculator({ entry, sl, symbol }: { entry: number; sl: number; symbol: string }) {
  const [accountSize, setAccountSize] = useState('10000');
  const [riskPct, setRiskPct] = useState('1');

  const acct = parseFloat(accountSize) || 0;
  const risk = parseFloat(riskPct) || 0;
  const dollarRisk = (acct * risk) / 100;
  const slDist = Math.abs(entry - sl);
  const slDistPct = slDist / entry;
  const positionSizeUsd = slDistPct > 0 ? dollarRisk / slDistPct : 0;
  const qty = entry > 0 ? positionSizeUsd / entry : 0;
  const lev = positionSizeUsd > acct ? positionSizeUsd / acct : 1;

  const fmt2 = (n: number) => n.toFixed(2);

  return (
    <div
      style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '16px 20px',
        marginBottom: 16,
      }}
    >
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 12 }}>
        Risk Calculator
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 12 }}>
        <div>
          <label style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, display: 'block', marginBottom: 4 }}>Account Size ($)</label>
          <input
            type="number"
            value={accountSize}
            onChange={(e) => setAccountSize(e.target.value)}
            style={{ width: '100%', padding: '7px 10px', background: C.surfaceHover, border: `1px solid ${C.border}`, borderRadius: R.sm, color: C.text, fontSize: F.sm, fontFamily: 'inherit' }}
          />
        </div>
        <div>
          <label style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, display: 'block', marginBottom: 4 }}>Risk per Trade (%)</label>
          <div style={{ display: 'flex', gap: 4 }}>
            {[0.5, 1, 2].map((v) => (
              <button
                key={v}
                onClick={() => setRiskPct(String(v))}
                style={{
                  flex: 1,
                  padding: '7px 4px',
                  borderRadius: R.sm,
                  border: `1px solid ${parseFloat(riskPct) === v ? C.brand : C.border}`,
                  background: parseFloat(riskPct) === v ? C.brand : C.surfaceHover,
                  color: parseFloat(riskPct) === v ? '#fff' : C.muted,
                  fontSize: F.xs,
                  fontWeight: 700,
                  cursor: 'pointer',
                }}
              >
                {v}%
              </button>
            ))}
            <input
              type="number"
              value={riskPct}
              onChange={(e) => setRiskPct(e.target.value)}
              style={{ flex: 1, padding: '7px 8px', background: C.surfaceHover, border: `1px solid ${C.border}`, borderRadius: R.sm, color: C.text, fontSize: F.sm, textAlign: 'center', fontFamily: 'inherit' }}
            />
          </div>
        </div>
      </div>

      {acct > 0 && slDistPct > 0 && (
        <div
          style={{
            padding: '12px 14px',
            background: C.surfaceHover,
            borderRadius: R.md,
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
            gap: 10,
          }}
        >
          {[
            { label: 'Max $ risk', value: `$${fmt2(dollarRisk)}`, color: C.bear, note: `${risk}% of $${acct.toLocaleString()}` },
            { label: 'SL distance', value: `${(slDistPct * 100).toFixed(2)}%`, color: C.warn, note: `$${fmt2(slDist)}` },
            { label: 'Position size', value: `$${Math.round(positionSizeUsd).toLocaleString()}`, color: C.text, note: `${qty < 1 ? qty.toFixed(4) : qty.toFixed(2)} ${symbol}` },
            { label: 'Implied leverage', value: `${fmt2(lev)}×`, color: lev > 10 ? C.bear : lev > 5 ? C.warn : C.bull, note: lev > 10 ? '⚠ Very high' : lev > 5 ? 'Moderate' : 'Conservative' },
          ].map(({ label, value, color, note }) => (
            <div key={label}>
              <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, marginBottom: 2 }}>{label}</div>
              <div style={{ fontSize: F.md, fontWeight: 800, color }}>{value}</div>
              <div style={{ fontSize: F.xs, color: C.muted }}>{note}</div>
            </div>
          ))}
        </div>
      )}

      <div style={{ marginTop: 10, fontSize: F.xs, color: C.muted, lineHeight: 1.5 }}>
        Based on entry <strong style={{ color: C.text }}>{themeFmtUsd(entry, 4)}</strong> and SL <strong style={{ color: C.text }}>{themeFmtUsd(sl, 4)}</strong>.
        If {symbol} drops to the SL, you lose <strong style={{ color: C.bear }}>${fmt2(dollarRisk)}</strong>.
      </div>
    </div>
  );
}

// ─── Agent Chain Strip ───────────────────────────────────────────────────────

function AgentChainStrip({ decision }: { decision: LlmDecision | null }) {
  if (!decision) return null;

  const action = (decision.action || 'skip').toLowerCase();
  const isGo = action === 'proceed' || action === 'go';
  const isFlip = action === 'flip' || action === 'reverse';
  const isVeto = decision.is_veto;
  const conf = decision.confidence || 0;
  const confPct = Math.round(conf * 100);
  const regime = (decision.regime || 'unknown').toLowerCase();
  const allowed = decision.allowed !== false;

  const regimeColors: Record<string, string> = {
    trend: '#16a34a', range: '#2563eb', panic: '#dc2626',
    high_volatility: '#d97706', low_liquidity: '#64748b', unknown: '#64748b',
  };
  const regimeColor = regimeColors[regime] || '#64748b';

  const actionColor = isVeto ? '#dc2626' : isGo ? '#16a34a' : isFlip ? '#7c3aed' : '#64748b';
  const actionLabel = isVeto ? 'VETOED' : isGo ? `GO ${confPct}%` : isFlip ? `FLIP ${confPct}%` : `SKIP ${confPct}%`;

  const gateColor = allowed ? '#16a34a' : '#dc2626';
  const gateLabel = allowed ? 'Passed' : 'Blocked';

  const finalLabel = isVeto ? 'BLOCKED' : isGo && allowed ? 'WATCHING' : isFlip && allowed ? 'FLIP WATCH' : 'SKIP';
  const finalColor = isVeto ? '#dc2626' : isGo && allowed ? '#6366f1' : '#64748b';

  const Step = ({ label, value, color }: { label: string; value: string; color: string }) => (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 3,
    }}>
      <span style={{ fontSize: 9, color: '#94a3b8', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</span>
      <span style={{
        fontSize: 11,
        fontWeight: 700,
        color,
        padding: '3px 8px',
        borderRadius: 6,
        background: color + '18',
        border: `1px solid ${color}44`,
        whiteSpace: 'nowrap',
      }}>
        {value}
      </span>
    </div>
  );

  return (
    <div style={{
      padding: '10px 20px',
      borderBottom: `1px solid ${C.border}`,
      background: C.surfaceHover,
    }}>
      <div style={{ fontSize: 10, fontWeight: 600, color: '#94a3b8', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        AI Reasoning Chain
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <Step label="Regime" value={regime.toUpperCase()} color={regimeColor} />
        <span style={{ color: '#cbd5e1', fontSize: 14, fontWeight: 300 }}>→</span>
        <Step label="AI Decision" value={actionLabel} color={actionColor} />
        <span style={{ color: '#cbd5e1', fontSize: 14, fontWeight: 300 }}>→</span>
        <Step label="Gate Status" value={gateLabel} color={gateColor} />
        <span style={{ color: '#cbd5e1', fontSize: 14, fontWeight: 300 }}>→</span>
        <Step label="Result" value={finalLabel} color={finalColor} />
        {decision.gate_reason && (
          <>
            <span style={{ color: '#cbd5e1', fontSize: 14, fontWeight: 300, marginLeft: 4 }}>·</span>
            <span style={{ fontSize: 10, color: '#94a3b8', marginLeft: 4, fontStyle: 'italic' }}>
              {String(decision.gate_reason).slice(0, 60)}
            </span>
          </>
        )}
      </div>
    </div>
  );
}

// ─── Copy Trade Card ─────────────────────────────────────────────────────────

function CopyTradeCard({
  signal,
  llmDecision,
  backtestBySymbol,
}: {
  signal: Signal;
  llmDecision: LlmDecision | null;
  backtestBySymbol?: { trades: number; wins: number; pnl: number; win_rate: number } | null;
}) {
  const info = getSignalStrength(signal);
  const trendUp = signal.sma20 > signal.sma50;
  const rsiVal = signal.rsi14 ?? 50;
  const isOverbought = rsiVal > 70;
  const isOversold = rsiVal < 30;

  return (
    <div
      style={{
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        background: C.card,
        marginBottom: 32,
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          padding: '16px 20px',
          borderBottom: `1px solid ${C.border}`,
          background: C.surfaceHover,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <span style={{ fontSize: 24, fontWeight: 700, color: C.text }}>{signal.symbol}</span>
          <span style={{ fontSize: 18, color: C.textSub }}>{fmt.format(signal.price)}</span>
        </div>
        <div
          style={{
            padding: '6px 16px',
            borderRadius: 20,
            background: info.bgColor,
            color: info.color,
            fontWeight: 700,
            fontSize: 14,
          }}
        >
          {info.emoji} {info.direction}
        </div>
      </div>

      {/* LLM Brain Section */}
      <div style={{ padding: '16px 20px', borderBottom: `1px solid ${C.border}`, background: C.surface }}>
        <div style={{ fontSize: F.xs, fontWeight: 700, marginBottom: 10, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          LLM Brain — What the AI Would Do
        </div>
        <LlmDecisionPanel decision={llmDecision} />
      </div>

      {/* Agent Chain Strip */}
      <AgentChainStrip decision={llmDecision} />

      {/* Signal Summary */}
      <div style={{ padding: '16px 20px', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ fontSize: F.xs, fontWeight: 700, marginBottom: 12, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          What the Bot Sees
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
          {/* Signal Score */}
          <div style={{ padding: 12, background: C.surfaceHover, borderRadius: R.md }}>
            <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>Signal Score</div>
            <div style={{ fontSize: 24, fontWeight: 700, color: signal.score >= 60 ? C.bull : signal.score >= 40 ? C.warn : C.bear }}>
              {signal.score}/100
            </div>
            <div style={{ fontSize: F.xs, color: C.faint }}>
              {signal.score >= 70 ? 'Strong signal' : signal.score >= 50 ? 'Moderate signal' : 'Weak signal'}
            </div>
            {backtestBySymbol && (
              <div style={{ marginTop: 6, paddingTop: 6, borderTop: `1px solid ${C.border}`, fontSize: 10, color: C.muted }}>
                Backtest accuracy:{' '}
                <strong style={{ color: backtestBySymbol.win_rate >= 0.65 ? C.bull : C.warn }}>
                  {(backtestBySymbol.win_rate * 100).toFixed(0)}%
                </strong>{' '}
                ({backtestBySymbol.wins}W/{backtestBySymbol.trades - backtestBySymbol.wins}L)
              </div>
            )}
          </div>

          {/* Trend */}
          <div style={{ padding: 12, background: C.surfaceHover, borderRadius: R.md }}>
            <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>Trend (SMA 20/50)</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: trendUp ? C.bull : C.bear }}>
              {trendUp ? 'Uptrend' : 'Downtrend'}
            </div>
            <div style={{ fontSize: F.xs, color: C.faint }}>
              20: {fmt.format(signal.sma20)} / 50: {fmt.format(signal.sma50)}
            </div>
          </div>

          {/* RSI */}
          <div style={{ padding: 12, background: C.surfaceHover, borderRadius: R.md }}>
            <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>RSI (14)</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: isOverbought ? C.bear : isOversold ? C.bull : C.text }}>
              {rsiVal.toFixed(1)}
            </div>
            <div style={{ fontSize: F.xs, color: C.faint }}>
              {isOverbought ? 'Overbought - caution' : isOversold ? 'Oversold - potential bounce' : 'Normal range'}
            </div>
          </div>

          {/* Volatility */}
          <div style={{ padding: 12, background: C.surfaceHover, borderRadius: R.md }}>
            <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>Volatility (ATR)</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: C.text }}>
              {typeof signal.atr_pct === 'number' ? signal.atr_pct.toFixed(2) + '%' : fmt.format(signal.atr14)}
            </div>
            <div style={{ fontSize: F.xs, color: C.faint }}>
              {signal.vol_spike ? 'Volume spike detected!' : 'Normal volume'}
            </div>
          </div>
        </div>
      </div>

      {/* Ensemble Vote Strip */}
      <EnsembleVoteStrip signal={signal} />

      {/* Key Price Levels */}
      <div style={{ padding: '16px 20px', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ fontSize: F.xs, fontWeight: 700, marginBottom: 12, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          Key Price Levels
        </div>
        <div style={{ fontSize: F.sm, color: C.textSub, marginBottom: 8 }}>
          These zones show where the bot considers price to be cheap (accumulation) or expensive (distribution) based on volatility analysis.
        </div>

        {/* SVG Price Ruler */}
        <VisualPriceRuler price={signal.price} zones={signal.zones} />

        {/* Supplementary price level details */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 500 }}>
          <PriceLevel label="Safe Distribution (very expensive)" price={signal.zones.safeDistrib} color={C.bear} currentPrice={signal.price} />
          <PriceLevel label="Distribution (expensive)" price={signal.zones.distrib} color="#ea580c" currentPrice={signal.price} />
          <div style={{ padding: '8px 12px', background: C.info + '20', border: `1px solid ${C.info}40`, borderRadius: R.sm, fontWeight: 700, fontSize: F.sm, color: C.info }}>
            Current Price: {fmt.format(signal.price)}
          </div>
          <PriceLevel label="Accumulation (cheap)" price={signal.zones.accum} color="#65a30d" currentPrice={signal.price} />
          <PriceLevel label="Deep Accumulation (very cheap)" price={signal.zones.deepAccum} color={C.bull} currentPrice={signal.price} />
        </div>
      </div>

      {/* Chart */}
      <div style={{ padding: '16px 20px', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ fontSize: F.xs, fontWeight: 700, marginBottom: 12, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          1H Chart
        </div>
        <TradingViewChart symbol={signal.symbol} />
      </div>

      {/* Risk Calculator */}
      <div style={{ padding: '16px 20px', borderBottom: `1px solid ${C.border}` }}>
        <div style={{ fontSize: F.xs, fontWeight: 700, marginBottom: 12, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          Position Sizing Calculator
        </div>
        <RiskCalculator entry={signal.price} sl={info.direction.includes('BULLISH') ? signal.zones.deepAccum : signal.zones.safeDistrib} symbol={signal.symbol} />
      </div>

      {/* How to Trade This */}
      <div style={{ padding: '16px 20px' }}>
        <div style={{ fontSize: F.xs, fontWeight: 700, marginBottom: 12, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          How to Trade This (Manual)
        </div>
        <HowToTrade signal={signal} info={info} llmDecision={llmDecision} />
      </div>
    </div>
  );
}

// ─── Visual Price Ruler ───────────────────────────────────────────────────────

function VisualPriceRuler({
  price,
  zones,
}: {
  price: number;
  zones: { deepAccum: number; accum: number; distrib: number; safeDistrib: number };
}) {
  const W = 600;
  const H = 80;
  const BAR_Y = 44;
  const BAR_H = 14;
  const TICK_H = 10;

  const { deepAccum, accum, distrib, safeDistrib } = zones;
  const rangeMin = deepAccum;
  const rangeMax = safeDistrib;
  const range = rangeMax - rangeMin;

  if (range <= 0) return null;

  const toX = (p: number) => ((p - rangeMin) / range) * W;

  const currentX = toX(price);
  const deepAccumX = toX(deepAccum);
  const accumX = toX(accum);
  const distribX = toX(distrib);
  const safeDistribX = toX(safeDistrib);

  const pctFrom = (p: number) => {
    const d = ((p - price) / price) * 100;
    return (d >= 0 ? '+' : '') + d.toFixed(1) + '%';
  };

  type MarkerDef = {
    x: number;
    label: string;
    subLabel: string;
    color: string;
    isCurrent?: boolean;
  };

  const markers: MarkerDef[] = [
    { x: deepAccumX, label: fmt.format(deepAccum), subLabel: pctFrom(deepAccum), color: '#16a34a' },
    { x: accumX,     label: fmt.format(accum),     subLabel: pctFrom(accum),     color: '#65a30d' },
    { x: currentX,   label: 'NOW',                 subLabel: fmt.format(price),  color: '#3b82f6', isCurrent: true },
    { x: distribX,   label: fmt.format(distrib),   subLabel: pctFrom(distrib),   color: '#ea580c' },
    { x: safeDistribX, label: fmt.format(safeDistrib), subLabel: pctFrom(safeDistrib), color: '#dc2626' },
  ];

  return (
    <div style={{ width: '100%', overflowX: 'auto', marginBottom: 12 }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: H, display: 'block', minWidth: 320 }}
        aria-label="Price range ruler"
      >
        {/* Green bar: deepAccum → currentX */}
        <defs>
          <linearGradient id="greenGrad" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor="#16a34a" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#86efac" stopOpacity="0.75" />
          </linearGradient>
          <linearGradient id="redGrad" x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor="#fca5a5" stopOpacity="0.75" />
            <stop offset="100%" stopColor="#dc2626" stopOpacity="0.55" />
          </linearGradient>
        </defs>

        {/* Cheap zone (green) */}
        <rect
          x={deepAccumX}
          y={BAR_Y}
          width={Math.max(0, currentX - deepAccumX)}
          height={BAR_H}
          rx={4}
          fill="url(#greenGrad)"
        />
        {/* Expensive zone (red) */}
        <rect
          x={currentX}
          y={BAR_Y}
          width={Math.max(0, safeDistribX - currentX)}
          height={BAR_H}
          rx={4}
          fill="url(#redGrad)"
        />

        {/* Tick marks + labels */}
        {markers.map((m, i) => {
          const isLeft = m.x < W * 0.15;
          const isRight = m.x > W * 0.85;
          const anchor: React.SVGAttributes<SVGTextElement>['textAnchor'] =
            isLeft ? 'start' : isRight ? 'end' : 'middle';

          if (m.isCurrent) {
            return (
              <g key={i}>
                {/* Vertical line through bar */}
                <line
                  x1={m.x} y1={BAR_Y - 2}
                  x2={m.x} y2={BAR_Y + BAR_H + 2}
                  stroke={m.color}
                  strokeWidth={2}
                />
                {/* Circle above bar */}
                <circle cx={m.x} cy={BAR_Y - 8} r={6} fill={m.color} />
                {/* NOW label above circle */}
                <text
                  x={m.x} y={BAR_Y - 18}
                  textAnchor={anchor}
                  fontSize={9}
                  fontWeight="700"
                  fill={m.color}
                  fontFamily="inherit"
                >
                  {m.label}
                </text>
                {/* Price below bar */}
                <text
                  x={m.x} y={BAR_Y + BAR_H + TICK_H + 4}
                  textAnchor={anchor}
                  fontSize={8}
                  fill={m.color}
                  fontFamily="inherit"
                >
                  {m.subLabel}
                </text>
              </g>
            );
          }

          return (
            <g key={i}>
              {/* Tick line above bar */}
              <line
                x1={m.x} y1={BAR_Y - TICK_H}
                x2={m.x} y2={BAR_Y}
                stroke={m.color}
                strokeWidth={1.5}
              />
              {/* Tick line below bar */}
              <line
                x1={m.x} y1={BAR_Y + BAR_H}
                x2={m.x} y2={BAR_Y + BAR_H + TICK_H}
                stroke={m.color}
                strokeWidth={1.5}
              />
              {/* Price label above tick */}
              <text
                x={m.x} y={BAR_Y - TICK_H - 3}
                textAnchor={anchor}
                fontSize={8}
                fontWeight="600"
                fill={m.color}
                fontFamily="inherit"
              >
                {m.label}
              </text>
              {/* % label below tick */}
              <text
                x={m.x} y={BAR_Y + BAR_H + TICK_H + 9}
                textAnchor={anchor}
                fontSize={8}
                fill={m.color}
                fontFamily="inherit"
              >
                {m.subLabel}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ─── Ensemble Vote Strip ──────────────────────────────────────────────────────

function EnsembleVoteStrip({ signal }: { signal: Signal }) {
  const agreementCount = Math.min(4, Math.max(0, Math.round(signal.score / 25)));

  const strategies = [
    { name: 'Regime', short: 'RGM' },
    { name: 'MonteCarlo', short: 'MCZ' },
    { name: 'ConfScore', short: 'CSC' },
    { name: 'MTF Quality', short: 'MTF' },
  ];

  const label = signal.label || '';
  const isBull = label.includes('Accumulation');
  const isBear = label.includes('Distribution');
  const voteColor = isBull ? '#16a34a' : isBear ? '#dc2626' : '#6b7280';
  const voteBg   = isBull ? '#dcfce7' : isBear ? '#fee2e2' : '#f3f4f6';
  const voteDir  = isBull ? 'BUY' : isBear ? 'SELL' : 'FLAT';

  return (
    <div
      style={{
        padding: '12px 20px',
        borderBottom: `1px solid ${C.border}`,
        background: C.surface,
      }}
    >
      <div
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: C.muted,
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          marginBottom: 8,
        }}
      >
        Strategy Agreement
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {strategies.map((s, i) => {
          const voting = i < agreementCount;
          return (
            <div
              key={s.name}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 3,
                padding: '6px 10px',
                borderRadius: 8,
                background: voting ? voteBg : C.surfaceHover,
                border: `1px solid ${voting ? voteColor + '55' : C.border}`,
                minWidth: 64,
                transition: 'background 0.2s',
              }}
            >
              <span
                style={{
                  fontSize: 9,
                  fontWeight: 700,
                  color: voting ? voteColor : C.faint,
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                }}
              >
                {s.short}
              </span>
              <span
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  color: voting ? voteColor : C.muted,
                }}
              >
                {voting ? voteDir : '—'}
              </span>
            </div>
          );
        })}

        {/* Summary badge */}
        <div
          style={{
            marginLeft: 'auto',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'flex-end',
            gap: 2,
          }}
        >
          <span style={{ fontSize: 10, color: C.muted, fontWeight: 600 }}>
            Agreement
          </span>
          <span
            style={{
              fontSize: 15,
              fontWeight: 800,
              color: agreementCount >= 3 ? '#16a34a' : agreementCount >= 2 ? '#eab308' : '#dc2626',
            }}
          >
            {agreementCount}/4
          </span>
          <div style={{ display: 'flex', gap: 3 }}>
            {strategies.map((_, i) => (
              <span
                key={i}
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: i < agreementCount ? voteColor : C.border,
                  display: 'inline-block',
                  transition: 'background 0.2s',
                }}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Price Level Row ─────────────────────────────────────────────────────────

function PriceLevel({ label, price, color, currentPrice }: { label: string; price: number; color: string; currentPrice: number }) {
  const diff = ((price - currentPrice) / currentPrice) * 100;
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 12px', background: C.surfaceHover, borderRadius: R.sm, borderLeft: `3px solid ${color}` }}>
      <span style={{ fontSize: F.xs, color: C.muted }}>{label}</span>
      <div style={{ textAlign: 'right' }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>{fmt.format(price)}</span>
        <span style={{ fontSize: 11, color: diff > 0 ? '#16a34a' : '#dc2626', marginLeft: 6 }}>
          ({diff > 0 ? '+' : ''}{diff.toFixed(1)}%)
        </span>
      </div>
    </div>
  );
}

// ─── How to Trade Instructions ───────────────────────────────────────────────

function HowToTrade({
  signal,
  info,
  llmDecision,
}: {
  signal: Signal;
  info: ReturnType<typeof getSignalStrength>;
  llmDecision: LlmDecision | null;
}) {
  const isBullish = info.direction.includes('BULLISH');
  const isBearish = info.direction.includes('BEARISH');
  const isNeutral = info.direction === 'NEUTRAL';

  // LLM alignment check
  const llmSaysSkip = llmDecision && llmDecision.action === 'flat';
  const llmSaysTrade = llmDecision && llmDecision.would_have_traded;

  if (isNeutral) {
    return (
      <div style={{ padding: 16, background: '#f3f4f6', borderRadius: 8, fontSize: 14, color: '#6b7280' }}>
        <strong>No clear signal right now.</strong> The bot sees mixed indicators. Best to wait for a stronger setup.
        Check back in a few minutes — signals update every 60 seconds.
      </div>
    );
  }

  const direction = isBullish ? 'Long (Buy)' : 'Short (Sell)';
  const slZone = isBullish ? signal.zones.deepAccum : signal.zones.safeDistrib;
  const tpZone = isBullish ? signal.zones.distrib : signal.zones.accum;

  return (
    <div>
      {/* LLM alignment banner */}
      {llmDecision && (
        <div
          style={{
            padding: '10px 14px',
            borderRadius: 8,
            marginBottom: 12,
            background: llmSaysSkip ? C.bear + '10' : llmSaysTrade ? C.bull + '10' : C.surfaceHover,
            border: `1px solid ${llmSaysSkip ? C.bear + '40' : llmSaysTrade ? C.bull + '40' : C.border}`,
            fontSize: 13,
          }}
        >
          {llmSaysSkip ? (
            <span style={{ color: '#dc2626', fontWeight: 600 }}>
              LLM says SKIP — the AI would not trade this setup right now. ({llmDecision.notes?.slice(0, 80) || 'No details'})
            </span>
          ) : llmSaysTrade ? (
            <span style={{ color: '#16a34a', fontWeight: 600 }}>
              LLM agrees — the AI would also trade this setup ({Math.round(llmDecision.confidence * 100)}% confidence).
            </span>
          ) : (
            <span style={{ color: '#6b7280' }}>LLM stance: {llmDecision.action} — use your judgment.</span>
          )}
        </div>
      )}

      <div
        style={{
          padding: 16,
          background: info.bgColor,
          borderRadius: 8,
          marginBottom: 12,
          border: `1px solid ${info.color}20`,
        }}
      >
        <div style={{ fontSize: 16, fontWeight: 700, color: info.color, marginBottom: 4 }}>
          Signal: {direction}
        </div>
        <div style={{ fontSize: F.sm, color: C.textSub }}>
          Strength: {info.strength} ({signal.score}/100)
        </div>
      </div>

      <div style={{ fontSize: 14, lineHeight: 1.8 }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>Steps on Hyperliquid:</div>
        <ol style={{ paddingLeft: 20, margin: 0 }}>
          <li style={{ marginBottom: 8 }}>
            Go to <strong>app.hyperliquid.xyz</strong> and open <strong>{signal.symbol}-USD</strong>
          </li>
          <li style={{ marginBottom: 8 }}>
            Select <strong>{isBullish ? 'Long' : 'Short'}</strong> and choose your leverage
            <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
              Recommended: 2-5x for beginners, never more than 10x
            </div>
          </li>
          <li style={{ marginBottom: 8 }}>
            Set your entry near <strong>{fmt.format(signal.price)}</strong> (current price)
          </li>
          <li style={{ marginBottom: 8 }}>
            Set a <strong>Stop Loss</strong> near <strong>{fmt.format(slZone)}</strong>
            <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
              This is the {isBullish ? 'Deep Accumulation' : 'Safe Distribution'} zone — if price reaches here, the trade idea is invalid
            </div>
          </li>
          <li style={{ marginBottom: 8 }}>
            Set a <strong>Take Profit</strong> near <strong>{fmt.format(tpZone)}</strong>
            <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
              This is the {isBullish ? 'Distribution' : 'Accumulation'} zone — where the bot expects price resistance/support
            </div>
          </li>
          <li>
            <strong>Only risk what you can afford to lose.</strong> Start small.
          </li>
        </ol>
      </div>

      {/* Risk warning */}
      <div
        style={{
          marginTop: 16,
          padding: 12,
          background: C.warn + '12',
          borderRadius: R.sm,
          border: `1px solid ${C.warn}40`,
          fontSize: F.xs,
          color: C.textSub,
        }}
      >
        <strong>Risk Warning:</strong> This is not financial advice. The bot is showing what it sees in the data —
        you make your own decision. Always use a stop loss. Never risk more than 1-2% of your account on a single trade.
        Past signals do not guarantee future results.
      </div>
    </div>
  );
}

// ─── Risk Calculator ─────────────────────────────────────────────────────────

function StandaloneRiskCalc({ defaultEntry, defaultSl }: { defaultEntry?: number; defaultSl?: number }) {
  const [show, setShow] = useState(false);
  const [accountSize, setAccountSize] = useState(10000);
  const [riskPct, setRiskPct] = useState(1.5);
  const [entry, setEntry] = useState(defaultEntry || 95000);
  const [stopLoss, setStopLoss] = useState(defaultSl || 94200);

  React.useEffect(() => {
    if (defaultEntry) setEntry(defaultEntry);
    if (defaultSl) setStopLoss(defaultSl);
  }, [defaultEntry, defaultSl]);

  const riskDollars = (accountSize * riskPct) / 100;
  const stopDist = Math.abs(entry - stopLoss);
  const stopDistPct = entry > 0 ? (stopDist / entry) * 100 : 0;
  const positionSize = stopDist > 0 ? riskDollars / stopDist : 0;
  const notionalValue = positionSize * entry;
  const leverage = accountSize > 0 ? notionalValue / accountSize : 0;

  const inp: React.CSSProperties = {
    padding: '7px 10px', background: C.surfaceHover, border: `1px solid ${C.border}`,
    borderRadius: R.sm, color: C.text, fontSize: F.sm, width: '100%', outline: 'none',
    fontVariantNumeric: 'tabular-nums',
  };

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, marginBottom: 24, overflow: 'hidden' }}>
      <button
        onClick={() => setShow(v => !v)}
        style={{
          width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '14px 20px', background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>Risk Calculator</span>
          <span style={{ fontSize: F.xs, padding: '2px 8px', borderRadius: R.pill, background: C.warn + '22', color: C.warn, fontWeight: 700 }}>Position Sizing</span>
        </div>
        <span style={{ color: C.muted, fontSize: 12, transform: show ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>▼</span>
      </button>
      {show && (
        <div style={{ padding: '0 20px 20px', borderTop: `1px solid ${C.border}` }}>
          <p style={{ fontSize: F.xs, color: C.muted, margin: '12px 0' }}>
            Enter your account size and risk tolerance to get exact position sizing for any signal.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12, marginBottom: 16 }}>
            {[
              { label: 'Account Size ($)', val: accountSize, set: setAccountSize, min: 100 },
              { label: 'Risk Per Trade (%)', val: riskPct, set: setRiskPct, step: 0.1, min: 0.1, max: 10 },
              { label: 'Entry Price ($)', val: entry, set: setEntry, min: 0.01 },
              { label: 'Stop Loss Price ($)', val: stopLoss, set: setStopLoss, min: 0.01 },
            ].map(({ label, val, set, ...rest }) => (
              <div key={label}>
                <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, marginBottom: 4 }}>{label}</div>
                <input type="number" style={inp} value={val} onChange={e => set(+e.target.value)} {...rest} />
              </div>
            ))}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 10 }}>
            {[
              { label: 'Dollar Risk', value: `$${riskDollars.toFixed(2)}`, sub: `${riskPct}% of account`, color: C.warn },
              { label: 'Stop Distance', value: `${stopDistPct.toFixed(2)}%`, sub: `$${stopDist.toFixed(2)} per unit`, color: C.text },
              { label: 'Position Size', value: positionSize > 0 ? positionSize.toFixed(4) + ' units' : '—', sub: 'coins / contracts', color: C.info },
              { label: 'Notional Value', value: notionalValue > 0 ? `$${notionalValue.toFixed(0)}` : '—', sub: 'total exposure', color: C.text },
              { label: 'Effective Leverage', value: leverage > 0 ? `${leverage.toFixed(1)}×` : '—', sub: leverage > 10 ? 'WARNING: very high' : leverage > 5 ? 'moderate-high' : 'healthy', color: leverage > 10 ? C.bear : leverage > 5 ? C.warn : C.bull },
            ].map(({ label, value, sub, color }) => (
              <div key={label} style={{ padding: '10px 14px', background: C.surfaceHover, border: `1px solid ${C.border}`, borderRadius: R.md }}>
                <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 3 }}>{label}</div>
                <div style={{ fontSize: F.lg, fontWeight: 800, color, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
                <div style={{ fontSize: F.xs, color: C.faint }}>{sub}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function CopyTrade() {
  const [data, setData] = useState<SignalsPayload>({});
  const [llmView, setLlmView] = useState<LlmMarketView | null>(null);
  const [activityEvents, setActivityEvents] = useState<ActivityEvent[]>([]);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(true);
  const apiBase = resolveApiBase();

  useEffect(() => {
    const fetcher = async () => {
      try {
        const [signalsRes, llmRes, activityRes, btRes] = await Promise.allSettled([
          fetch(`${apiBase}/v1/signals`),
          fetch(`${apiBase}/v1/llm/market-view`),
          fetch(`${apiBase}/v1/activity/feed?limit=25`),
          fetch(`${apiBase}/v1/backtest/results/latest`),
        ]);

        if (signalsRes.status === 'fulfilled' && signalsRes.value.ok) {
          setData(await signalsRes.value.json());
        }
        if (llmRes.status === 'fulfilled' && llmRes.value.ok) {
          setLlmView(await llmRes.value.json());
        }
        if (activityRes.status === 'fulfilled' && activityRes.value.ok) {
          const actData = await activityRes.value.json();
          setActivityEvents(actData?.items || []);
        }
        if (btRes.status === 'fulfilled' && btRes.value.ok) {
          setBacktest(await btRes.value.json());
        }
      } catch (e) {
        console.error('Fetch error:', e);
      }
      setLoading(false);
    };

    fetcher();
    const interval = setInterval(fetcher, 30000);
    return () => clearInterval(interval);
  }, [apiBase]);

  const signals = data.signals || {};
  const symbolOrder = ['BTC', 'SOL', 'HYPE'];
  const orderedSignals = symbolOrder.map((sym) => signals[sym]).filter(Boolean);
  const llmMode = llmView?.per_symbol
    ? Object.values(llmView.per_symbol)[0]?.mode || null
    : null;

  return (
    <div>
      {/* Page Header */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, marginBottom: 8 }}>Copy Trade</h1>
        <p style={{ fontSize: 15, color: '#6b7280', margin: 0, maxWidth: 700 }}>
          See what the bot sees — including the AI brain — then decide for yourself. Each card shows signals,
          key price levels, the LLM&apos;s reasoning, and step-by-step trade instructions for Hyperliquid.
        </p>
        {data.last_updated && (
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 8 }}>
            Signals updated: {new Date(data.last_updated).toLocaleString()} | Regime: {data.regime || 'Neutral'}
          </div>
        )}
      </div>

      {/* Mode Banner */}
      <ModeBanner mode={llmMode} />

      {/* LLM Brain Banner */}
      <LlmBrainBanner view={llmView} />

      {/* Activity Feed */}
      <ActivityFeed events={activityEvents} />

      {/* Risk Calculator */}
      <StandaloneRiskCalc />

      {/* Quick Guide */}
      <div
        style={{
          background: C.info + '10',
          border: `1px solid ${C.info}30`,
          borderRadius: R.md,
          padding: 20,
          marginBottom: 28,
        }}
      >
        <div style={{ fontSize: F.md, fontWeight: 600, marginBottom: 10, color: C.info }}>
          How This Works
        </div>
        <div style={{ fontSize: F.sm, color: C.textSub, lineHeight: 1.7 }}>
          <div style={{ marginBottom: 6 }}>
            <strong>1.</strong> The bot scans BTC, SOL, and HYPE every 60 seconds using 9 different strategies.
          </div>
          <div style={{ marginBottom: 6 }}>
            <strong>2.</strong> The <strong>LLM Brain</strong> (Claude AI) evaluates each setup in advisory mode — it logs what it would trade but does NOT execute.
          </div>
          <div style={{ marginBottom: 6 }}>
            <strong>3.</strong> Each card shows both the technical signal and the AI&apos;s reasoning. Use both to form your own view.
          </div>
          <div>
            <strong>4.</strong> Always use a stop loss. Start with small size. This is a tool, not a guarantee.
          </div>
        </div>
      </div>

      {/* Signal Cards */}
      {loading ? (
        <div style={{ padding: 40, textAlign: 'center', color: '#6b7280' }}>Loading signals...</div>
      ) : orderedSignals.length === 0 ? (
        <div style={{ padding: 40, textAlign: 'center', color: '#6b7280' }}>
          No signals available yet. The bot needs ~60 seconds to generate the first scan.
        </div>
      ) : (
        orderedSignals.map((signal) => (
          <CopyTradeCard
            key={signal.symbol}
            signal={signal}
            llmDecision={llmView?.per_symbol?.[signal.symbol] ?? null}
            backtestBySymbol={backtest?.by_symbol?.[signal.symbol] ?? null}
          />
        ))
      )}

      {/* Placeholder cards for missing symbols */}
      {!loading &&
        symbolOrder
          .filter((sym) => !signals[sym])
          .map((sym) => (
            <div
              key={sym}
              style={{
                border: `1px solid ${C.border}`,
                borderRadius: R.lg,
                background: C.card,
                padding: 32,
                marginBottom: 32,
                textAlign: 'center',
              }}
            >
              <div style={{ fontSize: 24, fontWeight: 700, marginBottom: 8, color: C.text }}>{sym}</div>
              <div style={{ color: C.muted, marginBottom: 16 }}>Waiting for signal data...</div>
              <TradingViewChart symbol={sym} />
            </div>
          ))}

      {/* Footer */}
      <div
        style={{
          fontSize: F.xs,
          color: C.muted,
          padding: '20px 0',
          borderTop: `1px solid ${C.border}`,
          textAlign: 'center',
          lineHeight: 1.6,
        }}
      >
        <strong>Disclaimer:</strong> This is not financial advice. All trading involves risk.
        The signals and AI analysis shown are generated by an automated bot and are for informational purposes only.
        You are solely responsible for your own trading decisions. Never invest more than you can afford to lose.
      </div>
    </div>
  );
}
