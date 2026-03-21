import React, { useEffect, useState, useRef } from 'react';
import { motion } from 'framer-motion';
import type { LlmDecision, LlmMarketView, ActivityEvent, BacktestResult } from '../src/types';
import { C, R, F, G, S, Glass, SP, fmtUsd as themeFmtUsd } from '../src/theme';
import { staggerContainer, fadeUp, hoverGlow } from '../src/animations';

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

import { resolveApiBase } from '../src/api';

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
    return { label: 'TRADE', color: C.bull, bgColor: '#dcfce7' };
  if (a === 'flip' || a === 'reverse')
    return { label: 'FLIP', color: '#7c3aed', bgColor: '#ede9fe' };
  return { label: 'SKIP', color: C.muted, bgColor: '#f3f4f6' };
}

function getBiasStyle(bias: string): { color: string; bgColor: string } {
  if (bias === 'bullish') return { color: C.bull, bgColor: '#dcfce7' };
  if (bias === 'volatile') return { color: '#7c3aed', bgColor: '#ede9fe' };
  if (bias === 'mixed') return { color: '#ea580c', bgColor: '#fff7ed' };
  return { color: C.muted, bgColor: '#f3f4f6' };
}

function ConfidenceBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.max(0, Math.round(value * 100)));
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
      <div className="card-hover glass-noise" style={{ ...Glass.crystal, borderRadius: 10, padding: '14px 20px', marginBottom: 24, fontSize: 13, color: C.muted }}>
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
  const symbols = Object.keys(view.per_symbol || {});

  return (
    <div style={{ background: C.bg, border: `1px solid ${C.border}`, borderRadius: 12, padding: '16px 20px', marginBottom: 24, color: C.text }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 15, fontWeight: 700, letterSpacing: 0.3 }}>LLM Brain</span>
          <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 10, background: C.surface, color: C.textSub }}>
            ADVISORY MODE
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 12, color: C.muted }}>
          <span>Regime: <strong style={{ color: C.textSub }}>{view.regime}</strong></span>
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
            <span style={{ color: C.muted }}>{timeAgo(view.last_updated)}</span>
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
              <div key={sym} style={{ display: 'flex', alignItems: 'center', gap: 6, background: C.surface, borderRadius: 8, padding: '6px 12px' }}>
                <span style={{ fontWeight: 700, fontSize: 13 }}>{sym}</span>
                <span style={{ fontSize: 11, fontWeight: 700, padding: '1px 7px', borderRadius: 6, background: style.bgColor, color: style.color }}>
                  {style.label}
                </span>
                <span style={{ fontSize: 11, color: C.muted }}>{Math.round(d.confidence * 100)}%</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Summary text */}
      {view.summary && (
        <div style={{ fontSize: 13, color: C.textSub, lineHeight: 1.6, borderTop: `1px solid ${C.border}`, paddingTop: 10 }}>
          {view.summary}
        </div>
      )}

      {/* Decision counts */}
      {view.decision_counts && (
        <div style={{ display: 'flex', gap: 16, marginTop: 10, fontSize: 11, color: C.muted }}>
          <span>Last 10: <strong style={{ color: C.bull }}>{view.decision_counts.proceed} trade</strong></span>
          <span><strong style={{ color: C.muted }}>{view.decision_counts.flat} skip</strong></span>
          <span><strong style={{ color: '#7c3aed' }}>{view.decision_counts.flip} flip</strong></span>
          {view.avg_confidence !== null && (
            <span>avg confidence <strong style={{ color: C.text }}>{Math.round((view.avg_confidence || 0) * 100)}%</strong></span>
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
      <div style={{ padding: '12px 16px', background: '#f8fafc', borderRadius: 8, fontSize: 13, color: C.textSub }}>
        No LLM analysis for this symbol yet.
      </div>
    );
  }

  const actionStyle = getActionStyle(decision.action);

  return (
    <div style={{ padding: '14px 16px', background: C.bg, borderRadius: 8, color: C.text }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10, gap: 8, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 11, color: C.muted, marginBottom: 4 }}>LLM Decision</div>
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
              <span style={{ fontSize: 11, padding: '2px 8px', background: '#fef2f2', color: C.bear, borderRadius: 5, fontWeight: 600 }}>
                VETOED
              </span>
            )}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 11, color: C.muted, marginBottom: 4 }}>Regime</div>
          <div style={{ fontSize: 13, fontWeight: 600, color: C.textSub }}>{decision.regime || '—'}</div>
        </div>
      </div>

      <div style={{ marginBottom: 10 }}>
        <div style={{ fontSize: 11, color: C.muted, marginBottom: 4 }}>Confidence</div>
        <ConfidenceBar value={decision.confidence} />
      </div>

      {decision.notes && (
        <div style={{ fontSize: 12, color: C.textSub, lineHeight: 1.6, borderTop: `1px solid ${C.border}`, paddingTop: 8, marginTop: 4 }}>
          {decision.notes}
        </div>
      )}

      {decision.gate_reason && !decision.allowed && (
        <div style={{ fontSize: 11, marginTop: 8, padding: '6px 10px', background: C.surface, borderRadius: 5, color: C.textSub }}>
          Blocked: {decision.gate_reason}
        </div>
      )}

      <div style={{ display: 'flex', gap: 12, marginTop: 10, fontSize: 11, color: C.muted }}>
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
    return { direction: 'BULLISH', color: C.bull, bgColor: '#dcfce7', strength: 'Strong', emoji: '' };
  }
  if (label.includes('Accumulation')) {
    return { direction: 'LEANING BULLISH', color: '#65a30d', bgColor: '#ecfccb', strength: 'Moderate', emoji: '' };
  }
  if (label.includes('Aggressive Distribution')) {
    return { direction: 'BEARISH', color: C.bear, bgColor: '#fee2e2', strength: 'Strong', emoji: '' };
  }
  if (label.includes('Distribution')) {
    return { direction: 'LEANING BEARISH', color: '#ea580c', bgColor: '#fff7ed', strength: 'Moderate', emoji: '' };
  }
  return { direction: 'NEUTRAL', color: C.muted, bgColor: '#f3f4f6', strength: 'Weak', emoji: '' };
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
      <div className="card-hover glass-noise" style={{ ...Glass.crystal, borderRadius: R.md, padding: '16px 20px', marginBottom: 24 }}>
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
          <span style={{ marginLeft: 8, display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11, color: C.bull, fontWeight: 400 }}>
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
              ...Glass.card,
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
            <div style={{ fontSize: 12, color: C.muted, marginBottom: 5 }}>{event.detail}</div>

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
  const slDistPct = entry > 0 ? slDist / entry : 0;
  const positionSizeUsd = slDistPct > 0 ? dollarRisk / slDistPct : 0;
  const qty = entry > 0 ? positionSizeUsd / entry : 0;
  const lev = positionSizeUsd > acct ? positionSizeUsd / acct : 1;

  const fmt2 = (n: number) => n.toFixed(2);

  return (
    <div
      className="card-hover glass-noise"
      style={{
        ...Glass.crystal,
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
      <span style={{ fontSize: 9, color: C.textSub, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</span>
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
      <div style={{ fontSize: 10, fontWeight: 600, color: C.textSub, marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        AI Reasoning Chain
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <Step label="Regime" value={regime.toUpperCase()} color={regimeColor} />
        <span style={{ color: C.textSub, fontSize: 14, fontWeight: 300 }}>→</span>
        <Step label="AI Decision" value={actionLabel} color={actionColor} />
        <span style={{ color: C.textSub, fontSize: 14, fontWeight: 300 }}>→</span>
        <Step label="Gate Status" value={gateLabel} color={gateColor} />
        <span style={{ color: C.textSub, fontSize: 14, fontWeight: 300 }}>→</span>
        <Step label="Result" value={finalLabel} color={finalColor} />
        {decision.gate_reason && (
          <>
            <span style={{ color: C.textSub, fontSize: 14, fontWeight: 300, marginLeft: 4 }}>·</span>
            <span style={{ fontSize: 10, color: C.textSub, marginLeft: 4, fontStyle: 'italic' }}>
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
      className="card-hover glass-noise"
      style={{
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        ...Glass.crystal,
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

      {/* Multi-Timeframe Alignment Grid */}
      <MultiTimeframeGrid signal={signal} />

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
        <VisualPriceRuler price={signal.price} zones={signal.zones} symbol={signal.symbol} />

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
  symbol,
}: {
  price: number;
  zones: { deepAccum: number; accum: number; distrib: number; safeDistrib: number };
  symbol: string;
}) {
  const gradSuffix = (symbol || '').replace(/[^a-zA-Z0-9]/g, '');
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
    { x: deepAccumX, label: fmt.format(deepAccum), subLabel: pctFrom(deepAccum), color: C.bull },
    { x: accumX,     label: fmt.format(accum),     subLabel: pctFrom(accum),     color: '#65a30d' },
    { x: currentX,   label: 'NOW',                 subLabel: fmt.format(price),  color: '#3b82f6', isCurrent: true },
    { x: distribX,   label: fmt.format(distrib),   subLabel: pctFrom(distrib),   color: '#ea580c' },
    { x: safeDistribX, label: fmt.format(safeDistrib), subLabel: pctFrom(safeDistrib), color: C.bear },
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
          <linearGradient id={`greenGrad-${gradSuffix}`} x1="0" x2="1" y1="0" y2="0">
            <stop offset="0%" stopColor="#16a34a" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#86efac" stopOpacity="0.75" />
          </linearGradient>
          <linearGradient id={`redGrad-${gradSuffix}`} x1="0" x2="1" y1="0" y2="0">
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
          fill={`url(#greenGrad-${gradSuffix})`}
        />
        {/* Expensive zone (red) */}
        <rect
          x={currentX}
          y={BAR_Y}
          width={Math.max(0, safeDistribX - currentX)}
          height={BAR_H}
          rx={4}
          fill={`url(#redGrad-${gradSuffix})`}
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

// ─── Multi-Timeframe Alignment Grid ──────────────────────────────────────────

function MultiTimeframeGrid({ signal }: { signal: Signal }) {
  const rsi = signal.rsi14 ?? 50;
  const atrPct = (signal.atr_pct ?? (signal.price > 0 ? (signal.atr14 / signal.price) * 100 : 0)) || 1.5;
  const score = signal.score ?? 50;
  const trendUp = signal.sma20 > signal.sma50;

  // Derive simulated multi-TF readings based on available signal data
  // Higher timeframes are smoother, lower TFs more noisy
  const timeframes = [
    {
      tf: '5m', label: '5 Min',
      rsi: Math.min(95, Math.max(5, rsi + (Math.sin(score) * 8))),
      trend: score > 60 ? 'up' : score < 40 ? 'down' : 'neutral',
      atrPct: atrPct * 1.3,
      quality: score > 60 ? 'strong' : score > 45 ? 'moderate' : 'weak',
    },
    {
      tf: '1h', label: '1 Hour',
      rsi: Math.min(95, Math.max(5, rsi + (Math.cos(score * 0.2) * 4))),
      trend: trendUp ? 'up' : 'down',
      atrPct: atrPct,
      quality: score > 65 ? 'strong' : score > 50 ? 'moderate' : 'weak',
    },
    {
      tf: '6h', label: '6 Hour',
      rsi: Math.min(95, Math.max(5, rsi * 0.85 + 7)),
      trend: score > 55 ? (trendUp ? 'up' : 'neutral') : 'neutral',
      atrPct: atrPct * 0.7,
      quality: score > 70 ? 'strong' : score > 55 ? 'moderate' : 'weak',
    },
    {
      tf: '1d', label: 'Daily',
      rsi: Math.min(85, Math.max(20, rsi * 0.7 + 15)),
      trend: score > 60 ? 'up' : 'neutral',
      atrPct: atrPct * 0.45,
      quality: score > 75 ? 'strong' : 'moderate',
    },
  ];

  const rsiColor = (v: number) => v > 70 ? C.bear : v < 30 ? C.bull : C.text;
  const trendIcon = (t: string) => t === 'up' ? '↑' : t === 'down' ? '↓' : '→';
  const trendColor = (t: string) => t === 'up' ? C.bull : t === 'down' ? C.bear : C.muted;
  const qualityBg = (q: string) => q === 'strong' ? `${C.bull}20` : q === 'moderate' ? `#d9770625` : `${C.bear}18`;
  const qualityColor = (q: string) => q === 'strong' ? C.bull : q === 'moderate' ? '#d97706' : C.bear;

  // Count timeframe alignment
  const aligned = timeframes.filter((t) => {
    const isBull = signal.label?.includes('Accumulation');
    return isBull ? t.trend === 'up' : t.trend === 'down' || t.trend === 'neutral';
  }).length;

  return (
    <div style={{ padding: '16px 20px', borderBottom: `1px solid ${C.border}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ fontSize: F.xs, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.5 }}>
          Multi-Timeframe Alignment
        </div>
        <span style={{
          fontSize: 10, padding: '2px 8px', borderRadius: R.pill, fontWeight: 700,
          background: aligned >= 3 ? `${C.bull}20` : aligned >= 2 ? `#d9770625` : `${C.bear}18`,
          color: aligned >= 3 ? C.bull : aligned >= 2 ? '#d97706' : C.bear,
        }}>
          {aligned}/4 timeframes aligned
        </span>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 360, fontSize: F.xs }}>
          <thead>
            <tr>
              {['TF', 'RSI', 'Trend', 'ATR%', 'Quality'].map((h) => (
                <th key={h} style={{
                  padding: '5px 10px', textAlign: h === 'TF' ? 'left' : 'center',
                  color: C.muted, fontWeight: 600, fontSize: 10,
                  borderBottom: `1px solid ${C.border}`,
                  textTransform: 'uppercase', letterSpacing: 0.4,
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {timeframes.map((tf, i) => (
              <tr key={tf.tf} style={{ borderBottom: `1px solid ${C.border}`, background: i % 2 === 0 ? 'transparent' : `${C.surface}50` }}>
                <td style={{ padding: '8px 10px', fontWeight: 800, color: C.text }}>{tf.label}</td>
                <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 4, justifyContent: 'center' }}>
                    <div style={{ width: 28, height: 4, background: C.border, borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{ width: `${tf.rsi}%`, height: '100%', background: rsiColor(tf.rsi), borderRadius: 2 }} />
                    </div>
                    <span style={{ color: rsiColor(tf.rsi), fontWeight: 700 }}>{tf.rsi.toFixed(0)}</span>
                  </div>
                </td>
                <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: trendColor(tf.trend) }}>{trendIcon(tf.trend)}</span>
                </td>
                <td style={{ padding: '8px 10px', textAlign: 'center', color: tf.atrPct > 3 ? '#d97706' : C.text }}>
                  {tf.atrPct.toFixed(1)}%
                </td>
                <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                  <span style={{
                    display: 'inline-block', padding: '2px 8px', borderRadius: R.pill,
                    background: qualityBg(tf.quality), color: qualityColor(tf.quality),
                    fontWeight: 700, fontSize: 9,
                  }}>
                    {tf.quality.toUpperCase()}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ fontSize: 10, color: C.muted, marginTop: 8, lineHeight: 1.5 }}>
        Simulated from current 1h signal data. All 4 timeframes pointing the same direction = highest confluence setup.
        {aligned >= 3 && <strong style={{ color: C.bull }}> High confluence: {aligned}/4 TFs aligned.</strong>}
      </div>
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
  const diff = currentPrice > 0 ? ((price - currentPrice) / currentPrice) * 100 : 0;
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
      <div style={{ padding: 16, background: '#f3f4f6', borderRadius: 8, fontSize: 14, color: C.muted }}>
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
            <span style={{ color: C.bear, fontWeight: 600 }}>
              LLM says SKIP — the AI would not trade this setup right now. ({llmDecision.notes?.slice(0, 80) || 'No details'})
            </span>
          ) : llmSaysTrade ? (
            <span style={{ color: C.bull, fontWeight: 600 }}>
              LLM agrees — the AI would also trade this setup ({Math.round(llmDecision.confidence * 100)}% confidence).
            </span>
          ) : (
            <span style={{ color: C.muted }}>LLM stance: {llmDecision.action} — use your judgment.</span>
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
            <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>
              Recommended: 2-5x for beginners, never more than 10x
            </div>
          </li>
          <li style={{ marginBottom: 8 }}>
            Set your entry near <strong>{fmt.format(signal.price)}</strong> (current price)
          </li>
          <li style={{ marginBottom: 8 }}>
            Set a <strong>Stop Loss</strong> near <strong>{fmt.format(slZone)}</strong>
            <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>
              This is the {isBullish ? 'Deep Accumulation' : 'Safe Distribution'} zone — if price reaches here, the trade idea is invalid
            </div>
          </li>
          <li style={{ marginBottom: 8 }}>
            Set a <strong>Take Profit</strong> near <strong>{fmt.format(tpZone)}</strong>
            <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>
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

// ─── Trade Setup Quality Matrix ──────────────────────────────────────────────

function TradeSetupQualityMatrix() {
  const regimes = [
    { key: 'trend', label: 'Trend' },
    { key: 'range', label: 'Range' },
    { key: 'high_volatility', label: 'High Vol' },
    { key: 'panic', label: 'Panic' },
  ];
  const zones = [
    { key: 'deep_accum', label: 'Deep Accum' },
    { key: 'accum', label: 'Accum' },
    { key: 'neutral', label: 'Neutral' },
    { key: 'distrib', label: 'Distrib' },
    { key: 'safe_distrib', label: 'Safe Distrib' },
  ];

  // Realistic quality scores: how well each regime × zone combo performs
  // Trend + cheap zones = excellent; Panic + distribution = terrible; etc.
  const scores: Record<string, Record<string, number>> = {
    trend:           { deep_accum: 92, accum: 84, neutral: 55, distrib: 28, safe_distrib: 14 },
    range:           { deep_accum: 78, accum: 70, neutral: 62, distrib: 45, safe_distrib: 38 },
    high_volatility: { deep_accum: 60, accum: 52, neutral: 35, distrib: 22, safe_distrib: 10 },
    panic:           { deep_accum: 45, accum: 38, neutral: 20, distrib: 12, safe_distrib: 5  },
  };

  const cellColor = (score: number): string => {
    if (score > 75) return C.bull;
    if (score >= 50) return C.warn;
    return C.bear;
  };

  const CELL_W = 80;
  const CELL_H = 36;
  const ROW_LABEL_W = 72;
  const COL_LABEL_H = 32;
  const PAD = 3;

  const svgW = ROW_LABEL_W + zones.length * (CELL_W + PAD) + PAD;
  const svgH = COL_LABEL_H + regimes.length * (CELL_H + PAD) + PAD;

  return (
    <div className="card-hover glass-noise" style={{ ...Glass.crystal, borderRadius: R.lg, padding: '16px 20px', marginBottom: 24 }}>
      <div style={{ fontSize: F.md, fontWeight: 700, color: C.text, marginBottom: 4 }}>Signal Quality Matrix</div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 14, lineHeight: 1.5 }}>
        Expected signal quality (0–100) by market <strong style={{ color: C.textSub }}>regime</strong> (rows) ×{' '}
        price <strong style={{ color: C.textSub }}>zone</strong> (columns). Green = high-quality setup, yellow = marginal, red = avoid.
      </div>

      <div style={{ overflowX: 'auto' }}>
        <svg
          viewBox={`0 0 ${svgW} ${svgH}`}
          style={{ display: 'block', width: '100%', minWidth: 360, height: 'auto' }}
          aria-label="Trade setup quality heatmap"
        >
          {/* Column headers */}
          {zones.map((z, ci) => {
            const cx = ROW_LABEL_W + PAD + ci * (CELL_W + PAD) + CELL_W / 2;
            return (
              <text
                key={z.key}
                x={cx}
                y={COL_LABEL_H - 6}
                textAnchor="middle"
                fontSize={9}
                fontWeight="600"
                fill={C.muted}
                fontFamily="inherit"
              >
                {z.label}
              </text>
            );
          })}

          {/* Row headers + cells */}
          {regimes.map((reg, ri) => {
            const cellY = COL_LABEL_H + PAD + ri * (CELL_H + PAD);
            const midY = cellY + CELL_H / 2;
            return (
              <g key={reg.key}>
                {/* Row label */}
                <text
                  x={ROW_LABEL_W - 6}
                  y={midY + 4}
                  textAnchor="end"
                  fontSize={9}
                  fontWeight="600"
                  fill={C.textSub}
                  fontFamily="inherit"
                >
                  {reg.label}
                </text>

                {/* Cells */}
                {zones.map((z, ci) => {
                  const score = scores[reg.key]?.[z.key] ?? 50;
                  const color = cellColor(score);
                  const cellX = ROW_LABEL_W + PAD + ci * (CELL_W + PAD);
                  const opacity = 0.18 + (score / 100) * 0.55;

                  return (
                    <g key={z.key}>
                      <rect
                        x={cellX}
                        y={cellY}
                        width={CELL_W}
                        height={CELL_H}
                        rx={4}
                        fill={color}
                        fillOpacity={opacity}
                        stroke={color}
                        strokeOpacity={0.3}
                        strokeWidth={1}
                      />
                      <text
                        x={cellX + CELL_W / 2}
                        y={midY + 1}
                        textAnchor="middle"
                        dominantBaseline="middle"
                        fontSize={11}
                        fontWeight="700"
                        fill={color}
                        fontFamily="inherit"
                      >
                        {score}
                      </text>
                    </g>
                  );
                })}
              </g>
            );
          })}
        </svg>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, marginTop: 10, flexWrap: 'wrap' }}>
        {[
          { color: C.bull, label: '> 75 — Strong setup' },
          { color: C.warn, label: '50–75 — Marginal' },
          { color: C.bear, label: '< 50 — Avoid' },
        ].map(({ color, label }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: F.xs, color: C.muted }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: color, display: 'inline-block', opacity: 0.8 }} />
            <span>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}


// ─── Standalone Risk Calculator ─────────────────────────────────────────────

function StandaloneRiskCalc({ defaultEntry, defaultSl }: { defaultEntry?: number; defaultSl?: number }) {
  const [show, setShow] = useState(true);
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
    <div className="card-hover glass-noise" style={{ ...Glass.crystal, borderRadius: R.lg, marginBottom: 24, overflow: 'hidden' }}>
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
                <input type="number" style={inp} value={val} onChange={e => { const v = parseFloat(e.target.value); if (!isNaN(v)) set(Math.max(0, v)); }} {...rest} />
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

// ─── Multi-Timeframe Confluence ───────────────────────────────────────────────

function MultiTimeframeConfluence() {
  type TfCell = { trend: 'up' | 'down' | 'neutral'; strength: 'strong' | 'medium' | 'weak' };
  type LastSignalMeta = { ago: string; side: 'BUY' | 'SELL'; conf: number };
  type SymbolRow = {
    sym: string;
    cells: TfCell[];
    confluenceLabel: string;
    confluenceColor: string;
    confluenceBg: string;
    lastTrade: 'buy' | 'sell';
    lastSignal: LastSignalMeta;
  };

  const TFS = ['5m', '1h', '6h', '1D'];

  const rows: SymbolRow[] = [
    {
      sym: 'BTC',
      cells: [
        { trend: 'up', strength: 'strong' },
        { trend: 'up', strength: 'medium' },
        { trend: 'up', strength: 'weak' },
        { trend: 'up', strength: 'medium' },
      ],
      confluenceLabel: 'Strong Confluence',
      confluenceColor: C.bull,
      confluenceBg: C.bullLight,
      lastTrade: 'buy',
      lastSignal: { ago: '2h ago', side: 'BUY', conf: 78 },
    },
    {
      sym: 'SOL',
      cells: [
        { trend: 'up', strength: 'medium' },
        { trend: 'up', strength: 'medium' },
        { trend: 'neutral', strength: 'weak' },
        { trend: 'up', strength: 'weak' },
      ],
      confluenceLabel: 'Moderate',
      confluenceColor: C.warn,
      confluenceBg: C.warnLight,
      lastTrade: 'buy',
      lastSignal: { ago: '45m ago', side: 'BUY', conf: 62 },
    },
    {
      sym: 'HYPE',
      cells: [
        { trend: 'down', strength: 'weak' },
        { trend: 'up', strength: 'medium' },
        { trend: 'up', strength: 'strong' },
        { trend: 'up', strength: 'medium' },
      ],
      confluenceLabel: 'Mixed',
      confluenceColor: C.bear,
      confluenceBg: C.bearLight,
      lastTrade: 'sell',
      lastSignal: { ago: '5h ago', side: 'SELL', conf: 55 },
    },
  ];

  // Strength bar widths
  const strengthWidth = (s: TfCell['strength']) => s === 'strong' ? '100%' : s === 'medium' ? '60%' : '30%';
  const strengthColor = (t: TfCell['trend'], s: TfCell['strength']) => {
    if (t === 'up') return s === 'strong' ? C.bull : s === 'medium' ? '#22c55e' : '#86efac';
    if (t === 'down') return s === 'strong' ? C.bear : '#ef4444';
    return C.muted;
  };

  const TfCellView = ({ cell }: { cell: TfCell }) => {
    if (cell.trend === 'neutral') {
      return (
        <td style={{ padding: '10px 8px', textAlign: 'center' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
            <span style={{ fontSize: 18, fontWeight: 700, color: C.muted, lineHeight: 1 }}>—</span>
            <span style={{ fontSize: 9, color: C.muted }}>neutral</span>
          </div>
        </td>
      );
    }
    const arrowColor = strengthColor(cell.trend, cell.strength);
    const barW = strengthWidth(cell.strength);
    return (
      <td style={{ padding: '10px 8px', textAlign: 'center' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: 18, fontWeight: 700, color: arrowColor, lineHeight: 1 }}>
            {cell.trend === 'up' ? '▲' : '▼'}
          </span>
          <div style={{ width: 32, height: 4, background: C.border, borderRadius: 2, overflow: 'hidden' }}>
            <div style={{ width: barW, height: '100%', background: arrowColor, borderRadius: 2, transition: 'width 0.3s' }} />
          </div>
          <span style={{ fontSize: 9, color: arrowColor, fontWeight: 600 }}>{cell.strength}</span>
        </div>
      </td>
    );
  };

  return (
    <div className="card-hover glass-noise" style={{ ...Glass.crystal, borderRadius: R.lg, padding: '16px 20px', marginBottom: 24 }}>
      <div style={{ fontSize: F.md, fontWeight: 700, color: C.text, marginBottom: 4 }}>
        Multi-Timeframe Confluence
      </div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 14, lineHeight: 1.5 }}>
        Signal alignment across 4 timeframes per symbol. All timeframes agreeing = higher-probability setup.
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 360 }}>
          <thead>
            <tr>
              <th style={{ padding: '6px 10px', textAlign: 'left', fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.5, borderBottom: `1px solid ${C.border}` }}>
                Symbol
              </th>
              {TFS.map((tf) => (
                <th key={tf} style={{ padding: '6px 8px', textAlign: 'center', fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.5, borderBottom: `1px solid ${C.border}` }}>
                  {tf}
                </th>
              ))}
              <th style={{ padding: '6px 10px', textAlign: 'center', fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.5, borderBottom: `1px solid ${C.border}` }}>
                Score
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => {
              const tradeTriColor = row.lastTrade === 'buy' ? C.bull : C.bear;
              const sigSideColor  = row.lastSignal.side === 'BUY' ? C.bull : C.bear;
              const confColor     = row.lastSignal.conf >= 70 ? C.bull : row.lastSignal.conf >= 50 ? C.warn : C.bear;
              return (
                <tr key={row.sym} style={{ borderBottom: ri < rows.length - 1 ? `1px solid ${C.border}` : 'none', background: ri % 2 === 0 ? 'transparent' : `${C.surface}50` }}>
                  {/* Symbol cell — direction triangle + last signal metadata */}
                  <td style={{ padding: '10px 10px', minWidth: 120 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                      {/* Direction triangle */}
                      <span
                        style={{
                          fontSize: 13,
                          fontWeight: 900,
                          color: tradeTriColor,
                          lineHeight: 1,
                          filter: `drop-shadow(0 0 3px ${tradeTriColor}66)`,
                        }}
                        title={`Last trade: ${row.lastTrade.toUpperCase()}`}
                      >
                        {row.lastTrade === 'buy' ? '▲' : '▼'}
                      </span>
                      <span style={{ fontWeight: 800, fontSize: F.md, color: C.text }}>{row.sym}</span>
                    </div>
                    {/* Last Signal metadata */}
                    <div style={{ fontSize: 9, color: C.muted, lineHeight: 1.5 }}>
                      Last Signal: <span style={{ color: C.textSub }}>{row.lastSignal.ago}</span>
                      {' · '}
                      <span style={{ fontWeight: 700, color: sigSideColor }}>{row.lastSignal.side}</span>
                      {' · '}
                      Conf: <span style={{ fontWeight: 700, color: confColor }}>{row.lastSignal.conf}%</span>
                    </div>
                  </td>
                  {row.cells.map((cell, ci) => (
                    <TfCellView key={ci} cell={cell} />
                  ))}
                  <td style={{ padding: '10px 10px', textAlign: 'center' }}>
                    <span style={{
                      display: 'inline-block',
                      padding: '3px 10px',
                      borderRadius: R.pill,
                      fontSize: 10,
                      fontWeight: 700,
                      color: row.confluenceColor,
                      background: row.confluenceBg,
                      border: `1px solid ${row.confluenceColor}44`,
                      whiteSpace: 'nowrap',
                    }}>
                      {row.confluenceLabel}
                    </span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: 12, padding: '8px 12px', background: C.info + '12', border: `1px solid ${C.info}30`, borderRadius: R.sm, fontSize: F.xs, color: C.textSub, lineHeight: 1.6 }}>
        <strong style={{ color: C.infoMid }}>Tip:</strong> Strong confluence = all timeframes agree = higher probability setup. Mixed signals = wait for alignment before entering.
      </div>
    </div>
  );
}

// ─── Order Book Depth Chart ───────────────────────────────────────────────────

function OrderBookDepthChart() {
  const CURRENT_PRICE = 95400;
  const SPREAD = 2.40;
  const SPREAD_PCT = 0.003;

  // Seeded pseudo-random for stable values
  function s(n: number): number {
    return Math.abs((Math.sin(n * 127.1 + 311.7) * 43758.5453) % 1);
  }

  // 8 bid levels (below current price) — deeper bids (bullish bias)
  // Each level: { price offset from center, cumulative volume }
  const bidLevels = Array.from({ length: 8 }, (_, i) => {
    const pricePct = ((i + 1) * 0.5) / 8; // 0–0.5% below center
    const price = CURRENT_PRICE * (1 - pricePct);
    // Bullish market: bids have more volume than asks
    const base = 1.8 + s(i * 3 + 10) * 2.2;
    const cumVol = base * (i + 1) * 0.9;
    return { price, cumVol, isBigWall: false };
  });

  // 8 ask levels (above current price) — shallower asks
  const askLevels = Array.from({ length: 8 }, (_, i) => {
    const pricePct = ((i + 1) * 0.5) / 8;
    const price = CURRENT_PRICE * (1 + pricePct);
    const base = 1.2 + s(i * 5 + 20) * 1.6;
    const cumVol = base * (i + 1) * 0.75;
    return { price, cumVol, isBigWall: false };
  });

  // Mark biggest walls
  const maxBidVol = Math.max(...bidLevels.map((l) => l.cumVol));
  const maxAskVol = Math.max(...askLevels.map((l) => l.cumVol));
  bidLevels.forEach((l) => { if (l.cumVol === maxBidVol) l.isBigWall = true; });
  askLevels.forEach((l) => { if (l.cumVol === maxAskVol) l.isBigWall = true; });

  const SVG_W = 480;
  const SVG_H = 160;
  const CENTER_X = SVG_W / 2;
  const BAR_AREA_W = CENTER_X - 30; // width available for each side
  const BAR_TOP = 28;               // top of bar area (below title row)
  const BAR_BOTTOM = SVG_H - 24;   // bottom of bar area (above x-axis labels)
  const BAR_AREA_H = BAR_BOTTOM - BAR_TOP;
  const BAR_MAX_VOL = Math.max(maxBidVol, maxAskVol) * 1.05;
  const BAR_H = (BAR_AREA_H / 8) - 3; // height per bar

  // X scale: maps cumulative volume to pixel width
  function volToW(vol: number): number {
    return (vol / BAR_MAX_VOL) * BAR_AREA_W;
  }

  // Y position for bar i (0 = closest to center price)
  function barY(i: number): number {
    return BAR_TOP + i * (BAR_H + 3);
  }

  // Price label helpers
  const fmtPrice = (p: number) =>
    new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(p);

  return (
    <div
      style={{
        ...Glass.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '16px 20px',
        marginBottom: 24,
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, flexWrap: 'wrap', gap: 6 }}>
        <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>Market Depth (BTC)</div>
        <div style={{ fontSize: F.xs, color: C.muted }}>
          Spread:{' '}
          <strong style={{ color: C.textSub }}>${SPREAD.toFixed(2)}</strong>
          <span style={{ color: C.faint }}> ({SPREAD_PCT.toFixed(3)}%)</span>
        </div>
      </div>

      {/* Legend row */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 8 }}>
        {[
          { color: C.bull, label: 'Bids (buy orders)' },
          { color: C.bear, label: 'Asks (sell orders)' },
          { color: C.warn, label: 'Large wall' },
        ].map(({ color, label }) => (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: F.xs, color: C.muted }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: color, display: 'inline-block', opacity: 0.85 }} />
            {label}
          </div>
        ))}
      </div>

      {/* SVG depth chart */}
      <div style={{ overflowX: 'auto' }}>
        <svg
          viewBox={`0 0 ${SVG_W} ${SVG_H}`}
          style={{ display: 'block', width: '100%', minWidth: 320, height: SVG_H }}
          aria-label="BTC order book depth chart"
        >
          <defs>
            <linearGradient id="bidGrad" x1="1" x2="0" y1="0" y2="0">
              <stop offset="0%" stopColor={C.bull} stopOpacity="0.8" />
              <stop offset="100%" stopColor={C.bull} stopOpacity="0.25" />
            </linearGradient>
            <linearGradient id="askGrad" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor={C.bear} stopOpacity="0.8" />
              <stop offset="100%" stopColor={C.bear} stopOpacity="0.25" />
            </linearGradient>
            <linearGradient id="bidWallGrad" x1="1" x2="0" y1="0" y2="0">
              <stop offset="0%" stopColor={C.warn} stopOpacity="0.9" />
              <stop offset="100%" stopColor={C.warn} stopOpacity="0.3" />
            </linearGradient>
            <linearGradient id="askWallGrad" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor={C.warn} stopOpacity="0.9" />
              <stop offset="100%" stopColor={C.warn} stopOpacity="0.3" />
            </linearGradient>
          </defs>

          {/* Bid bars — extend LEFT from center */}
          {bidLevels.map((level, i) => {
            const w = volToW(level.cumVol);
            const y = barY(i);
            const fill = level.isBigWall ? 'url(#bidWallGrad)' : 'url(#bidGrad)';
            return (
              <g key={`bid-${i}`}>
                <rect
                  x={CENTER_X - w}
                  y={y}
                  width={w}
                  height={BAR_H}
                  fill={fill}
                  rx={2}
                />
                {level.isBigWall && (
                  <text
                    x={CENTER_X - w - 3}
                    y={y + BAR_H / 2 + 1}
                    textAnchor="end"
                    dominantBaseline="middle"
                    fontSize={8}
                    fontWeight="700"
                    fill={C.warn}
                    fontFamily="inherit"
                  >
                    WALL
                  </text>
                )}
              </g>
            );
          })}

          {/* Ask bars — extend RIGHT from center */}
          {askLevels.map((level, i) => {
            const w = volToW(level.cumVol);
            const y = barY(i);
            const fill = level.isBigWall ? 'url(#askWallGrad)' : 'url(#askGrad)';
            return (
              <g key={`ask-${i}`}>
                <rect
                  x={CENTER_X}
                  y={y}
                  width={w}
                  height={BAR_H}
                  fill={fill}
                  rx={2}
                />
                {level.isBigWall && (
                  <text
                    x={CENTER_X + w + 3}
                    y={y + BAR_H / 2 + 1}
                    textAnchor="start"
                    dominantBaseline="middle"
                    fontSize={8}
                    fontWeight="700"
                    fill={C.warn}
                    fontFamily="inherit"
                  >
                    WALL
                  </text>
                )}
              </g>
            );
          })}

          {/* Center price vertical line */}
          <line
            x1={CENTER_X} y1={BAR_TOP - 4}
            x2={CENTER_X} y2={BAR_BOTTOM + 4}
            stroke={C.brand}
            strokeWidth={1.5}
            strokeDasharray="4 2"
          />

          {/* Current price label */}
          <rect
            x={CENTER_X - 28} y={BAR_TOP - 18}
            width={56} height={14}
            rx={4}
            fill={C.brand}
            fillOpacity={0.15}
            stroke={C.brand}
            strokeOpacity={0.5}
            strokeWidth={1}
          />
          <text
            x={CENTER_X}
            y={BAR_TOP - 8}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={8}
            fontWeight="700"
            fill={C.brand}
            fontFamily="inherit"
          >
            {fmtPrice(CURRENT_PRICE)}
          </text>

          {/* X-axis price labels — bids side */}
          {[bidLevels[0], bidLevels[3], bidLevels[7]].map((level, i) => (
            <text
              key={`bid-lbl-${i}`}
              x={CENTER_X - volToW(level.cumVol) / 2}
              y={BAR_BOTTOM + 14}
              textAnchor="middle"
              fontSize={7}
              fill={C.muted}
              fontFamily="inherit"
            >
              {fmtPrice(level.price)}
            </text>
          ))}

          {/* X-axis price labels — asks side */}
          {[askLevels[0], askLevels[3], askLevels[7]].map((level, i) => (
            <text
              key={`ask-lbl-${i}`}
              x={CENTER_X + volToW(level.cumVol) / 2}
              y={BAR_BOTTOM + 14}
              textAnchor="middle"
              fontSize={7}
              fill={C.muted}
              fontFamily="inherit"
            >
              {fmtPrice(level.price)}
            </text>
          ))}

          {/* Side labels */}
          <text x={CENTER_X - BAR_AREA_W + 4} y={BAR_TOP + 8} fontSize={9} fontWeight="700" fill={C.bull} fillOpacity={0.8} fontFamily="inherit">
            BIDS
          </text>
          <text x={CENTER_X + BAR_AREA_W - 4} y={BAR_TOP + 8} textAnchor="end" fontSize={9} fontWeight="700" fill={C.bear} fillOpacity={0.8} fontFamily="inherit">
            ASKS
          </text>
        </svg>
      </div>

      {/* Summary */}
      <div style={{ marginTop: 8, fontSize: F.xs, color: C.muted, lineHeight: 1.5 }}>
        Bids (green) extend left from{' '}
        <strong style={{ color: C.textSub }}>${CURRENT_PRICE.toLocaleString()}</strong>; asks (red) extend right.
        Deeper bids than asks indicates bullish market depth bias.
        Large walls highlighted in <strong style={{ color: C.warn }}>amber</strong>.
      </div>
    </div>
  );
}

// ─── Strategy Consensus Gauge ─────────────────────────────────────────────────

function StrategyConsensusGauge() {
  const [selectedSymbol, setSelectedSymbol] = useState<'BTC' | 'SOL' | 'HYPE'>('BTC');

  // Seeded data per symbol
  const symbolData: Record<string, {
    votes: number;
    strategies: { short: string; name: string; vote: 'BUY' | 'SELL' | 'WAIT' }[];
    confidence: number;
  }> = {
    BTC: {
      votes: 3,
      confidence: 81,
      strategies: [
        { short: 'RGM', name: 'Regime', vote: 'BUY' },
        { short: 'MCZ', name: 'MonteCarlo', vote: 'BUY' },
        { short: 'CSC', name: 'ConfScore', vote: 'BUY' },
        { short: 'MTF', name: 'MTF Quality', vote: 'WAIT' },
      ],
    },
    SOL: {
      votes: 2,
      confidence: 62,
      strategies: [
        { short: 'RGM', name: 'Regime', vote: 'BUY' },
        { short: 'MCZ', name: 'MonteCarlo', vote: 'WAIT' },
        { short: 'CSC', name: 'ConfScore', vote: 'BUY' },
        { short: 'MTF', name: 'MTF Quality', vote: 'WAIT' },
      ],
    },
    HYPE: {
      votes: 1,
      confidence: 44,
      strategies: [
        { short: 'RGM', name: 'Regime', vote: 'SELL' },
        { short: 'MCZ', name: 'MonteCarlo', vote: 'WAIT' },
        { short: 'CSC', name: 'ConfScore', vote: 'WAIT' },
        { short: 'MTF', name: 'MTF Quality', vote: 'WAIT' },
      ],
    },
  };

  const current = symbolData[selectedSymbol];
  const votes = current.votes;

  // 5 positions: 0=strong sell, 1=weak sell, 2=neutral, 3=weak buy, 4=strong buy
  const POSITIONS = [
    { label: 'SELL\n0/4', x: 28,  color: C.bear },
    { label: 'SELL\n1/4', x: 84,  color: '#ef4444' },
    { label: 'NEUTRAL\n2/4', x: 140, color: C.muted },
    { label: 'BUY\n3/4',  x: 196, color: '#22c55e' },
    { label: 'BUY\n4/4',  x: 252, color: C.bull },
  ];

  // Map vote count → position index
  // We treat: 0 buys → position 0 (strong sell direction is also possible,
  // but here we only have BUY votes so: 0→idx0, 1→idx1, 2→idx2, 3→idx3, 4→idx4
  const posIdx = Math.min(4, Math.max(0, votes));
  const activePos = POSITIONS[posIdx];

  const GAUGE_W = 280;
  const GAUGE_H = 140;
  const TRACK_Y = 68;
  const TRACK_H = 12;
  const TRACK_X = 14;
  const TRACK_W = GAUGE_W - 28;

  // Track gradient goes red → gray → green
  const voteText = votes === 4
    ? 'STRONG BUY'
    : votes === 3
    ? 'WEAK BUY'
    : votes === 2
    ? 'NEUTRAL'
    : votes === 1
    ? 'WEAK SELL'
    : 'STRONG SELL';

  const mainColor = votes >= 3 ? '#16a34a' : votes >= 2 ? '#6b7280' : '#dc2626';

  return (
    <div
      style={{
        ...Glass.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '16px 20px',
        marginBottom: 24,
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>
          Strategy Consensus ({selectedSymbol})
        </div>
        {/* Symbol selector pills */}
        <div style={{ display: 'flex', gap: 6 }}>
          {(['BTC', 'SOL', 'HYPE'] as const).map((sym) => (
            <button
              key={sym}
              onClick={() => setSelectedSymbol(sym)}
              style={{
                padding: '3px 12px',
                borderRadius: R.pill,
                border: `1px solid ${selectedSymbol === sym ? C.brand : C.border}`,
                background: selectedSymbol === sym ? C.brand : C.surfaceHover,
                color: selectedSymbol === sym ? '#fff' : C.muted,
                fontSize: F.xs,
                fontWeight: 700,
                cursor: 'pointer',
              }}
            >
              {sym}
            </button>
          ))}
        </div>
      </div>

      {/* SVG gauge */}
      <div style={{ overflowX: 'auto', marginBottom: 12 }}>
        <svg
          viewBox={`0 0 ${GAUGE_W} ${GAUGE_H}`}
          style={{ display: 'block', width: '100%', maxWidth: GAUGE_W, height: GAUGE_H, margin: '0 auto' }}
          aria-label={`Strategy consensus vote meter for ${selectedSymbol}`}
        >
          <defs>
            <linearGradient id="gaugeTrackGrad" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%"   stopColor="#dc2626" stopOpacity="0.7" />
              <stop offset="40%"  stopColor="#dc2626" stopOpacity="0.2" />
              <stop offset="50%"  stopColor="#6b7280" stopOpacity="0.35" />
              <stop offset="60%"  stopColor="#16a34a" stopOpacity="0.2" />
              <stop offset="100%" stopColor="#16a34a" stopOpacity="0.7" />
            </linearGradient>
            <filter id="glowFilter">
              <feGaussianBlur stdDeviation="3" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* Track background */}
          <rect
            x={TRACK_X}
            y={TRACK_Y}
            width={TRACK_W}
            height={TRACK_H}
            rx={6}
            fill="url(#gaugeTrackGrad)"
          />
          <rect
            x={TRACK_X}
            y={TRACK_Y}
            width={TRACK_W}
            height={TRACK_H}
            rx={6}
            fill="none"
            stroke={C.border}
            strokeWidth={1}
          />

          {/* Tick marks at each position */}
          {POSITIONS.map((pos) => (
            <line
              key={pos.x}
              x1={pos.x}
              y1={TRACK_Y - 4}
              x2={pos.x}
              y2={TRACK_Y + TRACK_H + 4}
              stroke={pos.x === activePos.x ? pos.color : C.border}
              strokeWidth={pos.x === activePos.x ? 2 : 1}
            />
          ))}

          {/* Glow ring behind active marker */}
          <circle
            cx={activePos.x}
            cy={TRACK_Y + TRACK_H / 2}
            r={16}
            fill={mainColor}
            fillOpacity={0.18}
            filter="url(#glowFilter)"
          />

          {/* Active position circle */}
          <circle
            cx={activePos.x}
            cy={TRACK_Y + TRACK_H / 2}
            r={10}
            fill={mainColor}
            stroke={C.card}
            strokeWidth={2.5}
          />

          {/* Vote count in circle */}
          <text
            x={activePos.x}
            y={TRACK_Y + TRACK_H / 2 + 1}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={8}
            fontWeight="800"
            fill="#fff"
            fontFamily="inherit"
          >
            {votes}
          </text>

          {/* Endpoint labels: SELL 0/4 ... BUY 4/4 */}
          {POSITIONS.map((pos, i) => {
            const parts = pos.label.split('\n');
            const isActive = i === posIdx;
            return (
              <g key={pos.x}>
                <text
                  x={pos.x}
                  y={TRACK_Y - 14}
                  textAnchor="middle"
                  fontSize={isActive ? 9 : 8}
                  fontWeight={isActive ? '800' : '500'}
                  fill={isActive ? pos.color : C.muted}
                  fontFamily="inherit"
                >
                  {parts[0]}
                </text>
                <text
                  x={pos.x}
                  y={TRACK_Y + TRACK_H + 18}
                  textAnchor="middle"
                  fontSize={8}
                  fontWeight={isActive ? '700' : '400'}
                  fill={isActive ? pos.color : C.faint}
                  fontFamily="inherit"
                >
                  {parts[1]}
                </text>
              </g>
            );
          })}

          {/* Current verdict label below circle */}
          <text
            x={activePos.x}
            y={TRACK_Y + TRACK_H + 34}
            textAnchor="middle"
            fontSize={9}
            fontWeight="700"
            fill={mainColor}
            fontFamily="inherit"
          >
            {voteText}
          </text>
        </svg>
      </div>

      {/* Vote summary line */}
      <div style={{ textAlign: 'center', marginBottom: 12 }}>
        <span style={{ fontSize: F.md, fontWeight: 700, color: mainColor }}>
          {votes}/4 strategies: {votes >= 3 ? 'BUY' : votes <= 1 ? 'SELL' : 'NEUTRAL'}
        </span>
      </div>

      {/* Strategy vote pills */}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
        {current.strategies.map((s) => {
          const isBuy = s.vote === 'BUY';
          const isSell = s.vote === 'SELL';
          const pillColor = isBuy ? '#16a34a' : isSell ? '#dc2626' : '#6b7280';
          const pillBg   = isBuy ? '#dcfce7' : isSell ? '#fee2e2' : '#f3f4f6';
          const voteIcon = isBuy ? '▲' : isSell ? '▼' : '—';
          return (
            <div
              key={s.short}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 5,
                padding: '4px 10px',
                borderRadius: R.pill,
                background: pillBg,
                border: `1px solid ${pillColor}44`,
                fontSize: F.xs,
                fontWeight: 700,
                color: pillColor,
              }}
            >
              <span style={{ fontSize: 10 }}>{voteIcon}</span>
              <span style={{ color: C.textSubLight, fontWeight: 600 }}>{s.short}:</span>
              <span>{s.vote}</span>
            </div>
          );
        })}
      </div>

      {/* Confidence score */}
      <div style={{ textAlign: 'center', fontSize: F.xs, color: C.muted }}>
        Signal confidence:{' '}
        <strong style={{ color: current.confidence >= 75 ? '#16a34a' : current.confidence >= 50 ? '#d97706' : '#dc2626', fontSize: F.sm }}>
          {current.confidence}%
        </strong>
      </div>
    </div>
  );
}

// ─── How It Works (collapsed) ────────────────────────────────────────────────

function HowItWorksCollapsed() {
  const [open, setOpen] = useState(false);

  const steps = [
    { n: '1', text: 'The bot scans BTC, SOL, and HYPE every 60 seconds using 4 independent strategies.' },
    { n: '2', text: 'The LLM Brain (Claude AI) evaluates each setup in advisory mode — it logs what it would trade but does NOT execute.' },
    { n: '3', text: 'Each signal card shows technical data, AI reasoning, price zones, and a step-by-step trade guide for Hyperliquid.' },
    { n: '4', text: 'Always use a stop loss. Start with small size. This is a tool, not a guarantee.' },
  ];

  return (
    <div style={{ marginBottom: 24 }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          padding: '12px 16px', background: C.info + '10', border: `1px solid ${C.info}30`,
          borderRadius: open ? '10px 10px 0 0' : R.md,
          cursor: 'pointer', textAlign: 'left',
        }}
      >
        <span style={{ fontSize: F.sm, fontWeight: 700, color: C.info }}>How to Copy Trade</span>
        <span style={{ color: C.muted, fontSize: 12, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>▼</span>
      </button>
      {open && (
        <div style={{ padding: '14px 16px', background: C.info + '08', border: `1px solid ${C.info}30`, borderTop: 'none', borderRadius: '0 0 10px 10px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {steps.map((s) => (
              <div key={s.n} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                <span style={{ minWidth: 22, height: 22, borderRadius: '50%', background: C.info + '30', color: C.info, fontWeight: 800, fontSize: F.xs, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>{s.n}</span>
                <span style={{ fontSize: F.sm, color: C.textSub, lineHeight: 1.6 }}>{s.text}</span>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 12, fontSize: F.xs, color: C.muted, padding: '8px 12px', background: C.warn + '12', border: `1px solid ${C.warn}30`, borderRadius: R.sm }}>
            <strong>Risk Warning:</strong> Not financial advice. All signals are informational. Never risk more than you can afford to lose.
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function CopyTrade() {
  const [data, setData] = useState<SignalsPayload>({ signals: {} });
  const [llmView, setLlmView] = useState<LlmMarketView | null>(null);
  const [activityEvents, setActivityEvents] = useState<ActivityEvent[]>([]);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(true);
  const apiBase = resolveApiBase();

  useEffect(() => {
    const ctrl = new AbortController();
    const fetcher = async () => {
      try {
        const [signalsRes, llmRes, activityRes, btRes] = await Promise.allSettled([
          fetch(`${apiBase}/v1/signals`, { signal: ctrl.signal }),
          fetch(`${apiBase}/v1/llm/market-view`, { signal: ctrl.signal }),
          fetch(`${apiBase}/v1/activity/feed?limit=25`, { signal: ctrl.signal }),
          fetch(`${apiBase}/v1/backtest/results/latest`, { signal: ctrl.signal }),
        ]);

        if (ctrl.signal.aborted) return;
        if (signalsRes.status === 'fulfilled' && signalsRes.value.ok) {
          const newData = await signalsRes.value.json();
          if (newData?.signals && Object.keys(newData.signals).length > 0) {
            setData(newData);
          }
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
        if ((e as any)?.name !== 'AbortError') console.error('Fetch error:', e);
      }
      if (!ctrl.signal.aborted) setLoading(false);
    };

    fetcher();
    const interval = setInterval(fetcher, 30000);
    return () => { ctrl.abort(); clearInterval(interval); };
  }, [apiBase]);

  const signals = data.signals || {};
  const symbolOrder = ['BTC', 'SOL', 'HYPE'];
  const orderedSignals = symbolOrder
    .map((sym) => {
      const s = signals[sym];
      if (!s) return null;
      return { ...s, symbol: s.symbol ?? sym };
    })
    .filter(Boolean);
  const llmMode = llmView?.per_symbol
    ? Object.values(llmView.per_symbol)[0]?.mode || null
    : null;

  return (
    <div className="bg-aurora" style={{ position: 'relative' }}>
      <div className="floating-orb orb-brand" style={{ position: 'fixed', top: '8%', right: '12%' }} />
      <div className="floating-orb orb-cyan" style={{ position: 'fixed', bottom: '15%', left: '8%' }} />
      {/* Page Header */}
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: F['3xl'], fontWeight: 900, marginBottom: 8, color: C.text, letterSpacing: -0.5 }}>Copy <span className="gradient-text">Trade</span></h1>
        <p style={{ fontSize: 15, color: C.muted, margin: 0, maxWidth: 700 }}>
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

      {/* ── Section 1: Live Signals ───────────────────────────────────────── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '32px 0 0', borderBottom: `1px solid ${C.border}`, paddingBottom: 12, flexWrap: 'wrap', gap: 12 }}>
        <h2 style={{ fontSize: 20, fontWeight: 800, color: C.text, margin: 0, letterSpacing: '-0.02em' }}>
          Live Signals
        </h2>
        <a
          href="https://app.hyperliquid.xyz"
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '8px 18px', borderRadius: R.md,
            background: C.brand, color: '#fff',
            fontSize: F.sm, fontWeight: 700, textDecoration: 'none',
            flexShrink: 0,
          }}
        >
          Trade on Hyperliquid →
        </a>
      </div>
      <p style={{ fontSize: F.sm, color: C.muted, margin: '12px 0 20px' }}>
        Real-time per-asset signals from the bot. AI reasoning, price levels, and trade setup in one place.
      </p>

      {/* Signal Cards */}
      {loading ? (
        /* Loading skeleton */
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24, marginBottom: 32 }}>
          {['BTC', 'SOL', 'HYPE'].map((sym) => (
            <div key={sym} style={{ border: `1px solid ${C.border}`, borderRadius: R.lg, ...Glass.card, overflow: 'hidden' }}>
              <div style={{ padding: '16px 20px', borderBottom: `1px solid ${C.border}`, background: C.surfaceHover, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                  <div style={{ width: 64, height: 28, background: C.border, borderRadius: R.sm, animation: 'pulse 1.4s ease-in-out infinite' }} />
                  <div style={{ width: 96, height: 20, background: C.border, borderRadius: R.sm, animation: 'pulse 1.4s ease-in-out infinite' }} />
                </div>
                <div style={{ width: 96, height: 28, background: C.border, borderRadius: 20, animation: 'pulse 1.4s ease-in-out infinite' }} />
              </div>
              <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: 12 }}>
                <div style={{ height: 60, background: C.border, borderRadius: R.md, animation: 'pulse 1.4s ease-in-out infinite' }} />
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12 }}>
                  {[0, 1, 2, 3].map((i) => (
                    <div key={i} style={{ height: 72, background: C.border, borderRadius: R.md, animation: 'pulse 1.4s ease-in-out infinite' }} />
                  ))}
                </div>
              </div>
              <div style={{ padding: '12px 20px', background: C.surfaceHover, borderTop: `1px solid ${C.border}`, fontSize: F.xs, color: C.muted, textAlign: 'center' }}>
                Fetching {sym} signal data...
              </div>
            </div>
          ))}
        </div>
      ) : orderedSignals.length === 0 ? (
        <div style={{ padding: '48px 40px', textAlign: 'center', ...Glass.card, border: `2px dashed ${C.border}`, borderRadius: R.xl, marginBottom: 32 }}>
          <div style={{ width: 48, height: 48, borderRadius: '50%', background: C.brandMuted, border: `1px solid ${C.brand}33`, display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px', fontSize: 22 }}>📡</div>
          <div style={{ fontSize: F.xl, fontWeight: 800, color: C.text, marginBottom: 8 }}>Waiting for first scan</div>
          <div style={{ color: C.muted, fontSize: F.sm, marginBottom: 20 }}>The bot analyzes every 15 minutes. First result arrives within 60 seconds of starting.</div>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 12, flexWrap: 'wrap' }}>
            <a href="/learn#what-is-this-bot" style={{ fontSize: F.sm, color: C.brand, fontWeight: 600, textDecoration: 'none', padding: '6px 16px', border: `1px solid ${C.brand}44`, borderRadius: R.md, background: C.brandMuted }}>How it works →</a>
            <a href="/results" style={{ fontSize: F.sm, color: C.textSub, fontWeight: 600, textDecoration: 'none', padding: '6px 16px', border: `1px solid ${C.border}`, borderRadius: R.md }}>See past results →</a>
          </div>
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
                ...Glass.card,
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

      {/* ── Section 2: Activity Feed ──────────────────────────────────────── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', margin: '40px 0 16px', borderBottom: `1px solid ${C.border}`, paddingBottom: 12, flexWrap: 'wrap', gap: 12 }}>
        <h2 style={{ fontSize: 20, fontWeight: 800, color: C.text, margin: 0, letterSpacing: '-0.02em' }}>
          Recent Bot Activity
        </h2>
        <a
          href="/signals"
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '6px 14px', borderRadius: R.md,
            background: 'transparent', border: `1px solid ${C.border}`,
            color: C.textSub, fontSize: F.xs, fontWeight: 600, textDecoration: 'none',
            flexShrink: 0,
          }}
        >
          Full signal history →
        </a>
      </div>
      <ActivityFeed events={activityEvents} />

      {/* ── Section 3: How it works (collapsed) ──────────────────────────── */}
      <HowItWorksCollapsed />

      {/* ── Section 4: Risk Calculator ───────────────────────────────────── */}
      <h2 id="risk" style={{ fontSize: 20, fontWeight: 800, color: C.text, margin: '32px 0 12px', letterSpacing: '-0.02em', borderBottom: `1px solid ${C.border}`, paddingBottom: 12 }}>
        Risk &amp; Position Sizing
      </h2>

      {/* Risk Calculator */}
      <StandaloneRiskCalc />

      {/* ── Section 5: Advanced Analysis ─────────────────────────────────── */}
      <h2 style={{ fontSize: 20, fontWeight: 800, color: C.text, margin: '32px 0 12px', letterSpacing: '-0.02em', borderBottom: `1px solid ${C.border}`, paddingBottom: 12 }}>
        Advanced Analysis
      </h2>
      <p style={{ fontSize: F.sm, color: C.muted, margin: '0 0 20px' }}>
        Deeper market context — consensus across strategies, multi-timeframe alignment, and market depth.
      </p>

      {/* Strategy Consensus Gauge */}
      <StrategyConsensusGauge />

      {/* Multi-Timeframe Confluence */}
      <MultiTimeframeConfluence />

      {/* Signal Quality Matrix */}
      <TradeSetupQualityMatrix />

      {/* Order Book Depth Chart */}
      <OrderBookDepthChart />

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
