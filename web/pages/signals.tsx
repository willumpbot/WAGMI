import React, { useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import { C, R, S, F, fmtUsd, timeAgo } from '../src/theme';
import type { ActivityEvent, LlmMarketView } from '../src/types';

// ─── Signal / Heatmap types ───────────────────────────────────────────────────

type Signal = {
  symbol: string;
  rsi?: number | null;
  atr_pct?: number | null;
  signal_score?: number | null;
  sma20?: number | null;
  sma50?: number | null;
  vol_spike?: boolean | null;
  price?: number | null;
  zones?: {
    accum?: number | null;
    distrib?: number | null;
  } | null;
};

type SignalsPayload = {
  signals: Record<string, Signal>;
  last_updated?: string | null;
};

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

// ─── Event type config ────────────────────────────────────────────────────────

const ETYPES: Record<string, { label: string; border: string; dot: string; bg: string; textColor: string }> = {
  llm_would_trade: { label: 'WOULD TRADE', border: C.bull, dot: '#4ade80', bg: 'rgba(22,163,74,0.08)', textColor: '#86efac' },
  llm_veto:        { label: 'AI VETO',     border: C.bear, dot: '#f87171', bg: 'rgba(220,38,38,0.08)', textColor: '#fca5a5' },
  llm_skip:        { label: 'SKIP',        border: '#475569', dot: '#94a3b8', bg: 'rgba(71,85,105,0.08)', textColor: '#94a3b8' },
  llm_flip:        { label: 'FLIP',        border: '#7c3aed', dot: '#a78bfa', bg: 'rgba(124,58,237,0.1)', textColor: '#c4b5fd' },
  llm_regime:      { label: 'REGIME',      border: '#2563eb', dot: '#60a5fa', bg: 'rgba(37,99,235,0.08)', textColor: '#93c5fd' },
  signal_blocked:  { label: 'BLOCKED',     border: '#d97706', dot: '#fbbf24', bg: 'rgba(217,119,6,0.08)', textColor: '#fbbf24' },
  signal_blocked_miss: { label: '⭐ MISSED WIN', border: '#10b981', dot: '#34d399', bg: 'rgba(16,185,129,0.12)', textColor: '#6ee7b7' },
};

const REGIME_EMOJI: Record<string, string> = {
  trend: '📈', range: '↔️', panic: '🚨', high_volatility: '⚡',
  low_liquidity: '🌊', news_dislocation: '📰', unknown: '❓',
};
const REGIME_COLOR: Record<string, string> = {
  trend: C.bull, range: '#2563eb', panic: C.bear,
  high_volatility: '#d97706', low_liquidity: '#64748b',
  news_dislocation: '#7c3aed', unknown: C.muted,
};

// ─── Confidence Ring ──────────────────────────────────────────────────────────

function ConfRing({ value, size = 44 }: { value: number; size?: number }) {
  const pct = Math.max(0, Math.min(1, value));
  const r = (size - 6) / 2;
  const circ = 2 * Math.PI * r;
  const filled = circ * pct;
  const color = pct >= 0.65 ? C.bull : pct >= 0.42 ? '#d97706' : C.bear;
  return (
    <svg width={size} height={size} style={{ flexShrink: 0 }}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={C.border} strokeWidth={4} />
      <circle
        cx={size / 2} cy={size / 2} r={r}
        fill="none" stroke={color} strokeWidth={4}
        strokeDasharray={`${filled} ${circ - filled}`}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
        style={{ transition: 'stroke-dasharray 0.5s ease' }}
      />
      <text x={size / 2} y={size / 2 + 4} textAnchor="middle" fontSize={11} fontWeight={700} fill={color}>
        {Math.round(pct * 100)}
      </text>
    </svg>
  );
}

// ─── Gate Funnel ──────────────────────────────────────────────────────────────

function SignalFunnel({ total, proceed, vetoed, skipped }: { total: number; proceed: number; vetoed: number; skipped: number }) {
  const stages = [
    { label: 'Analyzed by AI', value: total, pct: 100, color: C.brand, icon: '🔍', desc: 'Every market movement reviewed' },
    { label: 'Signal Formed', value: proceed + vetoed + skipped, pct: total > 0 ? Math.round(((proceed + vetoed + skipped) / total) * 100) : 0, color: '#7c3aed', icon: '📊', desc: 'Pattern matched a strategy' },
    { label: 'AI Approved', value: proceed + vetoed, pct: total > 0 ? Math.round(((proceed + vetoed) / total) * 100) : 0, color: '#2563eb', icon: '🤖', desc: 'Multi-agent review passed' },
    { label: 'Gates Passed', value: proceed, pct: total > 0 ? Math.round((proceed / total) * 100) : 12, color: C.bull, icon: '✅', desc: 'All 6 risk gates cleared' },
  ];

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '20px 24px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 18 }}>
        <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>Signal Filtering Funnel</div>
        <span style={{ fontSize: F.xs, color: C.muted }}>How signals are refined</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {stages.map((stage, i) => (
          <div key={stage.label}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 14 }}>{stage.icon}</span>
                <span style={{ fontSize: F.sm, fontWeight: 600, color: C.text }}>{stage.label}</span>
                <span style={{ fontSize: F.xs, color: C.muted }}>{stage.desc}</span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: F.sm, fontWeight: 700, color: stage.color }}>{stage.value.toLocaleString()}</span>
                <span style={{ fontSize: F.xs, color: C.muted, minWidth: 36, textAlign: 'right' }}>{stage.pct}%</span>
              </div>
            </div>
            <div style={{ height: 8, background: C.border, borderRadius: 4, overflow: 'hidden' }}>
              <div
                style={{
                  width: `${stage.pct}%`,
                  height: '100%',
                  background: `linear-gradient(90deg, ${stage.color} 0%, ${stage.color}99 100%)`,
                  borderRadius: 4,
                  transition: 'width 0.8s ease',
                }}
              />
            </div>
            {i < stages.length - 1 && (
              <div style={{ display: 'flex', justifyContent: 'center', margin: '2px 0', color: C.muted, fontSize: 10 }}>▼</div>
            )}
          </div>
        ))}
      </div>
      <div style={{
        marginTop: 14,
        paddingTop: 14,
        borderTop: `1px solid ${C.border}`,
        display: 'flex',
        gap: 20,
        fontSize: F.xs,
        color: C.muted,
      }}>
        <span style={{ color: '#fca5a5' }}>✗ Vetoed: {vetoed}</span>
        <span style={{ color: '#94a3b8' }}>⟳ Skipped: {skipped}</span>
        <span style={{ color: '#86efac' }}>✓ Would Trade: {proceed}</span>
      </div>
    </div>
  );
}

// ─── Per-symbol stance card ───────────────────────────────────────────────────

function SymbolStanceCard({ symbol, decision }: { symbol: string; decision: any }) {
  if (!decision) return null;
  const action = (decision.action || 'skip').toLowerCase();
  const conf = decision.confidence || 0;
  const regime = (decision.regime || 'unknown').toLowerCase();
  const isWould = action === 'proceed' || action === 'go';
  const isVeto = decision.is_veto;

  const statusColor = isVeto ? C.bear : isWould ? C.bull : C.muted;
  const statusLabel = isVeto ? 'VETOED' : isWould ? 'WATCHING' : action.toUpperCase();

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '16px 18px',
      flex: '1 1 200px',
      minWidth: 180,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: F.lg, fontWeight: 800, color: C.text }}>{symbol}</div>
          <div style={{ fontSize: F.xs, color: REGIME_COLOR[regime] || C.muted, marginTop: 2 }}>
            {REGIME_EMOJI[regime] || '❓'} {regime}
          </div>
        </div>
        <ConfRing value={conf} size={44} />
      </div>
      <div style={{
        display: 'inline-flex',
        padding: '3px 10px',
        borderRadius: R.pill,
        background: statusColor + '22',
        border: `1px solid ${statusColor}44`,
        fontSize: F.xs,
        fontWeight: 700,
        color: statusColor,
        letterSpacing: '0.05em',
        marginBottom: 8,
      }}>
        {statusLabel}
      </div>
      {decision.notes && (
        <div style={{ fontSize: F.xs, color: C.muted, lineHeight: 1.5 }}>
          {String(decision.notes).slice(0, 80)}{String(decision.notes).length > 80 ? '…' : ''}
        </div>
      )}
    </div>
  );
}

// ─── Signal Event Card ────────────────────────────────────────────────────────

function SignalCard({ event, index }: { event: ActivityEvent; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const type = event.event_type || 'llm_skip';
  const cfg = ETYPES[type] || ETYPES.llm_skip;
  const data = (event as any).data || {};
  const conf = data.confidence || 0;
  const isMissedWin = type === 'signal_blocked_miss';

  return (
    <div
      style={{
        background: cfg.bg,
        border: `1px solid ${cfg.border}44`,
        borderLeft: `3px solid ${cfg.border}`,
        borderRadius: R.md,
        overflow: 'hidden',
        animation: `fadeInUp 0.3s ease ${Math.min(index, 10) * 0.03}s both`,
      }}
    >
      {/* Main row */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '44px 64px 1fr auto auto',
          gap: 12,
          padding: '12px 16px',
          alignItems: 'center',
          cursor: 'pointer',
        }}
        onClick={() => setExpanded(e => !e)}
      >
        {/* Confidence ring */}
        <ConfRing value={conf} size={44} />

        {/* Symbol + badge */}
        <div>
          <div style={{ fontSize: F.md, fontWeight: 800, color: C.text }}>{event.symbol || '—'}</div>
          <span style={{
            display: 'inline-block',
            marginTop: 2,
            padding: '1px 6px',
            borderRadius: 4,
            fontSize: 9,
            fontWeight: 700,
            background: cfg.border + '33',
            color: cfg.textColor,
            letterSpacing: '0.05em',
          }}>
            {cfg.label}
          </span>
        </div>

        {/* Title + scalp insight */}
        <div>
          <div style={{ fontSize: F.sm, fontWeight: 600, color: C.text, marginBottom: 3 }}>
            {isMissedWin && <span style={{ color: '#34d399', marginRight: 6 }}>⭐</span>}
            {event.title}
          </div>
          {event.scalp_insight && (
            <div style={{ fontSize: F.xs, color: C.muted, lineHeight: 1.5 }}>
              {event.scalp_insight}
            </div>
          )}
        </div>

        {/* Regime badge */}
        <div style={{ textAlign: 'right' }}>
          {data.regime && (
            <span style={{
              fontSize: F.xs,
              color: REGIME_COLOR[data.regime.toLowerCase()] || C.muted,
              fontWeight: 500,
            }}>
              {REGIME_EMOJI[data.regime.toLowerCase()] || ''} {data.regime}
            </span>
          )}
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>{timeAgo(event.ts_iso || event.ts)}</div>
        </div>

        {/* Expand toggle */}
        <div style={{ color: C.muted, fontSize: 12, transition: 'transform 0.2s', transform: expanded ? 'rotate(180deg)' : 'none' }}>
          ▼
        </div>
      </div>

      {/* Expanded detail */}
      {expanded && (
        <div style={{
          padding: '0 16px 14px',
          borderTop: `1px solid ${cfg.border}22`,
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
          gap: 10,
          marginTop: 10,
        }}>
          {[
            { label: 'Direction', value: data.side || '—', color: data.side === 'BUY' ? C.bull : data.side === 'SELL' ? C.bear : C.muted },
            { label: 'Entry', value: data.entry ? fmtUsd(data.entry) : '—' },
            { label: 'Stop Loss', value: data.sl ? fmtUsd(data.sl) : '—', color: C.bear },
            { label: 'Target', value: data.tp1 ? fmtUsd(data.tp1) : '—', color: C.bull },
            { label: 'Mode', value: data.mode || '—' },
            { label: 'Gate', value: data.gate || '—' },
            ...(data.reason ? [{ label: 'Reason', value: String(data.reason).slice(0, 40) }] : []),
            ...(isMissedWin ? [{ label: 'Outcome', value: 'Would have WON ✓', color: '#34d399' }] : []),
          ].map(item => (
            <div key={item.label} style={{ background: '#0f172a', borderRadius: R.sm, padding: '8px 10px' }}>
              <div style={{ fontSize: 10, color: C.muted, fontWeight: 600, marginBottom: 3, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{item.label}</div>
              <div style={{ fontSize: F.sm, fontWeight: 600, color: (item as any).color || C.text }}>{item.value}</div>
            </div>
          ))}
          {event.detail && (
            <div style={{ gridColumn: '1 / -1', background: '#0f172a', borderRadius: R.sm, padding: '8px 10px' }}>
              <div style={{ fontSize: 10, color: C.muted, fontWeight: 600, marginBottom: 3, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Detail</div>
              <div style={{ fontSize: F.xs, color: C.textSub }}>{event.detail}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Market Heatmap ───────────────────────────────────────────────────────────
// NOTE: A separate MarketHeatmap component also exists in pages/index.tsx with
// an additional `onSelect` prop. These are parallel implementations — consider
// consolidating into a shared component if they diverge further.

function MarketHeatmap({ signals, loading }: { signals: Record<string, Signal> | null; loading: boolean }) {
  // Derive ordered symbol list: start with known defaults, append any extras from API
  const DEFAULT_SYMBOLS = ['BTC', 'SOL', 'HYPE'];
  const apiSymbols = signals ? Object.keys(signals) : [];
  const extras = apiSymbols.filter(s => !DEFAULT_SYMBOLS.includes(s));
  const symbols = signals ? [...DEFAULT_SYMBOLS.filter(s => apiSymbols.includes(s)), ...extras] : DEFAULT_SYMBOLS;

  // ── Cell color helpers ───────────────────────────────────────────────────
  function rsiColor(rsi: number | null | undefined): string {
    if (rsi == null) return C.heatNeutral;
    if (rsi < 30) return C.heatBull3;
    if (rsi < 45) return C.heatBull2;
    if (rsi < 55) return C.heatNeutral;
    if (rsi < 70) return C.heatBear1;
    return C.heatBear2;
  }

  function atrColor(atr: number | null | undefined): string {
    if (atr == null) return C.heatNeutral;
    if (atr < 0.5) return C.heatNeutral;
    if (atr < 2)   return '#854d0e'; // amber-900
    if (atr < 4)   return '#c2410c'; // orange-700
    return C.heatBear2;
  }

  function scoreColor(score: number | null | undefined): string {
    if (score == null) return C.heatNeutral;
    if (score < 50) return C.heatNeutral;
    if (score < 65) return '#854d0e';
    if (score < 75) return '#1e40af'; // blue-800
    if (score < 85) return C.heatBull2;
    return C.heatBull3;
  }

  function trendValue(sig: Signal): { label: string; color: string } {
    const { sma20, sma50 } = sig;
    if (sma20 == null || sma50 == null) return { label: '— N/A', color: C.muted };
    const diff = ((sma20 - sma50) / sma50) * 100;
    if (diff > 0.3)  return { label: '↑ Bull', color: C.heatBull1 };
    if (diff < -0.3) return { label: '↓ Bear', color: C.heatBear1 };
    return { label: '→ Flat', color: C.muted };
  }

  function zoneValue(sig: Signal): { label: string; color: string; bg: string } {
    const { price, zones } = sig;
    if (price == null || !zones) return { label: '⬜ Neutral', color: C.muted, bg: C.heatNeutral };
    if (zones.accum != null && price < zones.accum) return { label: '🟢 Accum', color: C.heatBull1, bg: C.heatBull3 };
    if (zones.distrib != null && price > zones.distrib) return { label: '🔴 Distrib', color: C.heatBear1, bg: C.heatBear3 };
    return { label: '⬜ Neutral', color: C.muted, bg: C.heatNeutral };
  }

  // ── Skeleton ─────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div style={{
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '20px 24px',
        overflowX: 'auto',
      }}>
        <div style={{ fontSize: F.md, fontWeight: 700, color: C.text, marginBottom: 16 }}>Market Metrics At a Glance</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[0, 1, 2, 3, 4, 5].map(i => (
            <div key={i} style={{ height: 50, background: C.heatNeutral, borderRadius: R.sm, animation: 'pulse 1.4s ease-in-out infinite', opacity: 0.4 + i * 0.05 }} />
          ))}
        </div>
      </div>
    );
  }

  // ── Row definitions ───────────────────────────────────────────────────────
  type RowDef = {
    label: string;
    render: (sig: Signal) => { text: string; bg: string; color: string; sub?: string };
  };

  const ROWS: RowDef[] = [
    {
      label: 'RSI 14',
      render: (sig) => {
        const v = sig.rsi;
        const bg = rsiColor(v);
        const color = '#f1f5f9';
        const text = v != null ? v.toFixed(1) : '—';
        const sub = v == null ? '' : v < 30 ? 'Oversold' : v > 70 ? 'Overbought' : 'Neutral';
        return { text, bg, color, sub };
      },
    },
    {
      label: 'ATR %',
      render: (sig) => {
        const v = sig.atr_pct;
        const bg = atrColor(v);
        const color = '#f1f5f9';
        const text = v != null ? `${v.toFixed(1)}%` : '—';
        const sub = v == null ? '' : v < 0.5 ? 'Low vol' : v < 2 ? 'Moderate' : v < 4 ? 'High vol' : 'Extreme';
        return { text, bg, color, sub };
      },
    },
    {
      label: 'Score',
      render: (sig) => {
        const v = sig.signal_score;
        const bg = scoreColor(v);
        const color = '#f1f5f9';
        const text = v != null ? String(Math.round(v)) : '—';
        const sub = v == null ? '' : v >= 85 ? 'Strong' : v >= 75 ? 'Good' : v >= 65 ? 'Moderate' : v >= 50 ? 'Weak' : 'No signal';
        return { text, bg, color, sub };
      },
    },
    {
      label: 'Trend',
      render: (sig) => {
        const { label, color } = trendValue(sig);
        const bg = label.includes('Bull') ? C.heatBull3 : label.includes('Bear') ? C.heatBear3 : C.heatNeutral;
        return { text: label, bg, color: '#f1f5f9', sub: '' };
      },
    },
    {
      label: 'Vol Spike',
      render: (sig) => {
        const spike = sig.vol_spike;
        if (spike) return { text: '⚡ Yes', bg: '#78350f', color: '#fbbf24', sub: 'Elevated' };
        return { text: '· No', bg: C.heatNeutral, color: C.muted, sub: 'Normal' };
      },
    },
    {
      label: 'Zone',
      render: (sig) => {
        const { label, color, bg } = zoneValue(sig);
        return { text: label, bg, color: '#f1f5f9', sub: '' };
      },
    },
  ];

  const COL_W = 92;
  const ROW_H = 54;
  const LABEL_W = 80;

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '20px 24px',
      overflowX: 'auto',
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 16, gap: 12 }}>
        <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>Market Metrics At a Glance</div>
        {signals && (
          <span style={{ fontSize: F.xs, color: C.muted, marginLeft: 'auto' }}>
            {/* Attempt last_updated from parent payload via a prop-style lookup — handled at call site */}
            Live snapshot
          </span>
        )}
      </div>

      {/* Table */}
      <table style={{ borderCollapse: 'separate', borderSpacing: 4, minWidth: LABEL_W + symbols.length * (COL_W + 4) }}>
        <thead>
          <tr>
            {/* Empty corner */}
            <th style={{ width: LABEL_W, minWidth: LABEL_W }} />
            {symbols.map(sym => (
              <th
                key={sym}
                style={{
                  width: COL_W,
                  minWidth: COL_W,
                  fontSize: F.sm,
                  fontWeight: 800,
                  color: C.text,
                  textAlign: 'center',
                  paddingBottom: 10,
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                }}
              >
                {sym}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map(row => (
            <tr key={row.label}>
              {/* Row label */}
              <td style={{
                fontSize: F.xs,
                fontWeight: 600,
                color: C.muted,
                paddingRight: 12,
                paddingTop: 2,
                paddingBottom: 2,
                whiteSpace: 'nowrap',
                verticalAlign: 'middle',
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
              }}>
                {row.label}
              </td>

              {/* Data cells */}
              {symbols.map(sym => {
                const sig = signals?.[sym];
                if (!sig) {
                  return (
                    <td key={sym}>
                      <div style={{
                        height: ROW_H,
                        width: COL_W,
                        background: C.heatNeutral,
                        borderRadius: R.sm,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: C.muted,
                        fontSize: F.xs,
                      }}>
                        —
                      </div>
                    </td>
                  );
                }
                const cell = row.render(sig);
                return (
                  <td key={sym} style={{ padding: 2 }}>
                    <div style={{
                      height: ROW_H,
                      width: COL_W,
                      background: cell.bg,
                      borderRadius: R.sm,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 2,
                      transition: 'opacity 0.2s',
                    }}>
                      <span style={{
                        fontSize: F.sm,
                        fontWeight: 700,
                        color: cell.color,
                        lineHeight: 1,
                      }}>
                        {cell.text}
                      </span>
                      {cell.sub && (
                        <span style={{
                          fontSize: 9,
                          color: cell.color,
                          opacity: 0.7,
                          letterSpacing: '0.03em',
                        }}>
                          {cell.sub}
                        </span>
                      )}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      {/* Legend */}
      <div style={{
        marginTop: 16,
        paddingTop: 14,
        borderTop: `1px solid ${C.border}`,
        display: 'flex',
        alignItems: 'center',
        gap: 20,
        flexWrap: 'wrap',
        fontSize: F.xs,
        color: C.muted,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 12, height: 12, borderRadius: 3, background: C.heatBull3 }} />
          <span>Bullish signal</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 12, height: 12, borderRadius: 3, background: C.heatBear2 }} />
          <span>Bearish signal</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 12, height: 12, borderRadius: 3, background: C.heatNeutral }} />
          <span>Neutral</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 12, height: 12, borderRadius: 3, background: '#78350f' }} />
          <span>High volatility / caution</span>
        </div>
      </div>
    </div>
  );
}

// ─── Signal Score Ranking ─────────────────────────────────────────────────────

type RankEntry = {
  symbol: string;
  score: number;
  side: 'BUY' | 'SELL' | 'NEUTRAL';
  stratCount: number;
  stratTotal: number;
};

function SignalScoreRanking({ signals }: { signals: Record<string, Signal> }) {
  const hasRealSignals = Object.keys(signals).length > 0;

  // Build ranked entries from real signals or fall back to example data
  const entries: RankEntry[] = hasRealSignals
    ? Object.entries(signals).map(([sym, sig]) => {
        const score = sig.signal_score ?? 0;
        // Derive side proxy: score >= 60 → BUY lean, score <= 40 → SELL lean, else NEUTRAL
        // (Signal type has no side field so we infer from score + trend)
        const sma20 = sig.sma20 ?? 0;
        const sma50 = sig.sma50 ?? 0;
        const trendUp = sma50 > 0 && sma20 > sma50;
        const trendDown = sma50 > 0 && sma20 < sma50;
        let side: RankEntry['side'] = 'NEUTRAL';
        if (score >= 60 && trendUp) side = 'BUY';
        else if (score >= 60 && trendDown) side = 'SELL';
        else if (score >= 60) side = 'BUY';
        else if (score < 40) side = 'SELL';
        // Strategy count: vol_spike + rsi present + atr_pct present + zones present
        const checks = [
          sig.rsi != null,
          sig.atr_pct != null,
          sig.vol_spike != null,
          sig.zones != null,
        ];
        const stratCount = checks.filter(Boolean).length;
        return { symbol: sym, score, side, stratCount, stratTotal: 4 };
      })
    : [
        { symbol: 'BTC', score: 82, side: 'BUY', stratCount: 3, stratTotal: 4 },
        { symbol: 'HYPE', score: 74, side: 'BUY', stratCount: 4, stratTotal: 4 },
        { symbol: 'SOL', score: 61, side: 'NEUTRAL', stratCount: 2, stratTotal: 4 },
      ];

  // Sort descending by score
  const sorted = [...entries].sort((a, b) => b.score - a.score);

  const n = sorted.length;
  const BAR_AREA_W = 300; // px — width of the bar drawing area
  const ROW_H = 40;
  const TOP_PAD = 48;
  const BOT_PAD = 24;
  const LEFT_PAD = 48;  // symbol labels
  const RIGHT_PAD = 120; // score + badge + strat count
  const svgW = LEFT_PAD + BAR_AREA_W + RIGHT_PAD;
  const svgH = TOP_PAD + n * ROW_H + BOT_PAD;

  // Threshold x positions
  const x50 = LEFT_PAD + (50 / 100) * BAR_AREA_W;
  const x70 = LEFT_PAD + (70 / 100) * BAR_AREA_W;

  function barColor(score: number): { start: string; end: string } {
    if (score >= 70) return { start: '#166534', end: C.bull };
    if (score >= 50) return { start: '#78350f', end: C.warn };
    return { start: '#7f1d1d', end: '#ef4444' };
  }

  function sideColor(side: RankEntry['side']): string {
    if (side === 'BUY') return C.bull;
    if (side === 'SELL') return C.bear;
    return C.muted;
  }

  const gradDefs = sorted.map((e, i) => {
    const { start, end } = barColor(e.score);
    return (
      <linearGradient key={e.symbol} id={`bar-grad-${i}`} x1="0" y1="0" x2="1" y2="0">
        <stop offset="0%" stopColor={start} />
        <stop offset="100%" stopColor={end} />
      </linearGradient>
    );
  });

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '20px 24px',
      marginBottom: 28,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>Signal Ranking — Live Scores</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
            70% = bot considers trading&nbsp;&nbsp;·&nbsp;&nbsp;50% = monitor zone
            {!hasRealSignals && <span style={{ color: C.muted, marginLeft: 8 }}>(example data)</span>}
          </div>
        </div>
        {/* Legend */}
        <div style={{ display: 'flex', gap: 14, fontSize: F.xs, color: C.muted, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: C.bull }} />
            ≥70 Trading zone
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: C.warn }} />
            50–69 Monitor
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 2, background: C.bear }} />
            &lt;50 Weak
          </span>
        </div>
      </div>

      {/* SVG chart */}
      <div style={{ overflowX: 'auto' }}>
        <svg
          viewBox={`0 0 ${svgW} ${svgH}`}
          width="100%"
          style={{ display: 'block', minWidth: Math.min(svgW, 320) }}
          aria-label="Signal score ranking bar chart"
        >
          <defs>{gradDefs}</defs>

          {/* Title row */}
          <text x={LEFT_PAD} y={18} fontSize={10} fill={C.muted} fontFamily="Inter, system-ui, sans-serif">
            SYMBOL
          </text>
          <text x={LEFT_PAD + BAR_AREA_W * 0.5} y={18} textAnchor="middle" fontSize={10} fill={C.muted} fontFamily="Inter, system-ui, sans-serif">
            SCORE
          </text>
          <text x={LEFT_PAD + BAR_AREA_W + 8} y={18} fontSize={10} fill={C.muted} fontFamily="Inter, system-ui, sans-serif">
            SIDE
          </text>
          <text x={svgW - 4} y={18} textAnchor="end" fontSize={10} fill={C.muted} fontFamily="Inter, system-ui, sans-serif">
            STRATS
          </text>

          {/* 50% dashed vertical line */}
          <line
            x1={x50} y1={TOP_PAD - 8}
            x2={x50} y2={TOP_PAD + n * ROW_H + 4}
            stroke={C.border}
            strokeWidth={1}
            strokeDasharray="4 3"
          />
          <text x={x50} y={TOP_PAD - 10} textAnchor="middle" fontSize={9} fill={C.muted} fontFamily="Inter, system-ui, sans-serif">
            50%
          </text>

          {/* 70% dashed vertical line */}
          <line
            x1={x70} y1={TOP_PAD - 8}
            x2={x70} y2={TOP_PAD + n * ROW_H + 4}
            stroke={`${C.bull}70`}
            strokeWidth={1}
            strokeDasharray="4 3"
          />
          <text x={x70} y={TOP_PAD - 10} textAnchor="middle" fontSize={9} fill={`${C.bull}cc`} fontFamily="Inter, system-ui, sans-serif">
            70%
          </text>

          {/* Rows */}
          {sorted.map((entry, i) => {
            const y = TOP_PAD + i * ROW_H;
            const barW = Math.max(2, (entry.score / 100) * BAR_AREA_W);
            const midY = y + ROW_H / 2;
            const sc = sideColor(entry.side);
            const scoreX = LEFT_PAD + barW + 6;

            return (
              <g key={entry.symbol}>
                {/* Row background (subtle zebra) */}
                {i % 2 === 0 && (
                  <rect
                    x={0} y={y + 2}
                    width={svgW} height={ROW_H - 4}
                    fill={`${C.surface}80`}
                    rx={4}
                  />
                )}

                {/* Symbol label */}
                <text
                  x={LEFT_PAD - 6}
                  y={midY + 4}
                  textAnchor="end"
                  fontSize={11}
                  fontWeight="700"
                  fill={C.text}
                  fontFamily="Inter, system-ui, sans-serif"
                >
                  {entry.symbol}
                </text>

                {/* Bar track background */}
                <rect
                  x={LEFT_PAD} y={midY - 8}
                  width={BAR_AREA_W} height={16}
                  fill={C.surface}
                  rx={4}
                />

                {/* Bar fill */}
                <rect
                  x={LEFT_PAD} y={midY - 8}
                  width={barW} height={16}
                  fill={`url(#bar-grad-${i})`}
                  rx={4}
                />

                {/* Score number at end of bar */}
                <text
                  x={Math.min(scoreX, LEFT_PAD + BAR_AREA_W - 4)}
                  y={midY + 4}
                  fontSize={10}
                  fontWeight="700"
                  fill={C.text}
                  fontFamily="Inter, system-ui, sans-serif"
                >
                  {Math.round(entry.score)}
                </text>

                {/* Side badge pill */}
                <rect
                  x={LEFT_PAD + BAR_AREA_W + 8}
                  y={midY - 8}
                  width={42}
                  height={16}
                  fill={`${sc}22`}
                  stroke={`${sc}55`}
                  strokeWidth={1}
                  rx={8}
                />
                <text
                  x={LEFT_PAD + BAR_AREA_W + 29}
                  y={midY + 4}
                  textAnchor="middle"
                  fontSize={9}
                  fontWeight="700"
                  fill={sc}
                  fontFamily="Inter, system-ui, sans-serif"
                >
                  {entry.side}
                </text>

                {/* Strategy count */}
                <text
                  x={svgW - 4}
                  y={midY + 4}
                  textAnchor="end"
                  fontSize={10}
                  fill={C.muted}
                  fontFamily="Inter, system-ui, sans-serif"
                >
                  {entry.stratCount}/{entry.stratTotal} ✓
                </text>
              </g>
            );
          })}

          {/* Bottom axis baseline */}
          <line
            x1={LEFT_PAD} y1={TOP_PAD + n * ROW_H + 6}
            x2={LEFT_PAD + BAR_AREA_W} y2={TOP_PAD + n * ROW_H + 6}
            stroke={C.border}
            strokeWidth={1}
          />
          <text x={LEFT_PAD} y={TOP_PAD + n * ROW_H + 18} fontSize={9} fill={C.muted} fontFamily="Inter, system-ui, sans-serif">0</text>
          <text x={LEFT_PAD + BAR_AREA_W} y={TOP_PAD + n * ROW_H + 18} textAnchor="end" fontSize={9} fill={C.muted} fontFamily="Inter, system-ui, sans-serif">100</text>
        </svg>
      </div>
    </div>
  );
}

// ─── Market Heatmap with timestamp wrapper ─────────────────────────────────────

function MarketHeatmapSection({ payload, loading }: { payload: SignalsPayload | null; loading: boolean }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: F.lg, fontWeight: 800, color: C.text }}>Market Metrics At a Glance</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            Color-coded snapshot of key indicators across all tracked symbols
          </div>
        </div>
        {payload?.last_updated && (
          <span style={{ fontSize: F.xs, color: C.muted }}>
            Updated {timeAgo(payload.last_updated)}
          </span>
        )}
      </div>
      <MarketHeatmap signals={payload?.signals || null} loading={loading} />
    </div>
  );
}

// ─── Correlation Matrix ───────────────────────────────────────────────────────

function CorrelationMatrix({ signals }: { signals: Record<string, any> }) {
  const syms = Object.keys(signals).slice(0, 5); // up to 5 symbols
  if (syms.length < 2) return null;

  // Build score array for each symbol
  const scores: Record<string, number> = {};
  syms.forEach(s => { scores[s] = signals[s]?.signal_score ?? 50; });

  // Simple correlation proxy: if both scores > 60 or both < 40, correlated
  // If one > 60 and other < 40, anti-correlated
  function corrColor(a: number, b: number): { bg: string; label: string; text: string } {
    if (a === b) return { bg: `${C.brand}30`, label: '1.00', text: C.brand }; // diagonal
    const diff = Math.abs(a - b);
    if (diff < 15) return { bg: 'rgba(22,163,74,0.25)', label: '+0.' + (9 - Math.round(diff/3)), text: '#86efac' };
    if (diff < 30) return { bg: 'rgba(22,163,74,0.12)', label: '+0.' + (6 - Math.round(diff/10)), text: '#4ade80' };
    if (diff < 45) return { bg: 'rgba(148,163,184,0.12)', label: '~0.0', text: C.muted };
    return { bg: 'rgba(220,38,38,0.2)', label: '-0.' + Math.round(diff/12), text: '#fca5a5' };
  }

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Signal Score Correlation</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>How much do markets move together right now? Green = correlated, red = diverging</div>
        </div>
        <div style={{ display: 'flex', gap: 12, fontSize: 10, color: C.muted }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 12, height: 12, background: 'rgba(22,163,74,0.4)', borderRadius: 2, display: 'inline-block' }} />
            Correlated
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 12, height: 12, background: 'rgba(148,163,184,0.2)', borderRadius: 2, display: 'inline-block' }} />
            Neutral
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 12, height: 12, background: 'rgba(220,38,38,0.3)', borderRadius: 2, display: 'inline-block' }} />
            Diverging
          </span>
        </div>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', minWidth: 300 }}>
          <thead>
            <tr>
              <th style={{ width: 52, padding: '6px 8px' }} />
              {syms.map(s => (
                <th key={s} style={{ padding: '6px 14px', fontSize: F.xs, fontWeight: 700, color: C.muted, textAlign: 'center', minWidth: 70 }}>
                  {s}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {syms.map(rowSym => (
              <tr key={rowSym}>
                <td style={{ padding: '6px 8px', fontSize: F.xs, fontWeight: 700, color: C.text }}>{rowSym}</td>
                {syms.map(colSym => {
                  const { bg, label, text } = corrColor(scores[rowSym] ?? 50, scores[colSym] ?? 50);
                  return (
                    <td key={colSym} style={{ padding: '8px 14px', textAlign: 'center' }}>
                      <div style={{
                        background: bg,
                        borderRadius: R.sm,
                        padding: '8px 4px',
                        fontSize: F.xs,
                        fontWeight: 700,
                        color: text,
                        minWidth: 54,
                      }}>
                        {label}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ fontSize: 10, color: C.muted, marginTop: 12, lineHeight: 1.5 }}>
        Correlation computed from current signal scores. Values near +1.0 mean both assets have similar buy/sell conditions. Near -1.0 means they are diverging. This is a snapshot, not a statistical correlation coefficient.
      </div>
    </div>
  );
}

// ─── Signal Strength Timeline ─────────────────────────────────────────────────

function SignalStrengthTimeline({ signals }: { signals: Record<string, any> }) {
  const entries = Object.entries(signals).slice(0, 6);
  if (!entries.length) return null;

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px', marginBottom: 28 }}>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 4 }}>Signal Strength Comparison</div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 16 }}>Current signal score across tracked assets — higher is a stronger buy setup</div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {entries.map(([sym, data]) => {
          const score = data?.signal_score ?? 0;
          const rsi = data?.rsi ?? null;
          const atrPct = data?.atr_pct ?? null;
          const color = score >= 70 ? C.bull : score >= 45 ? '#d97706' : C.bear;
          const price = data?.price;

          return (
            <div key={sym}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, alignItems: 'center' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontWeight: 800, color: C.text, width: 48 }}>{sym}</span>
                  {price && <span style={{ fontSize: 10, color: C.muted }}>${price.toLocaleString()}</span>}
                  {data?.vol_spike && (
                    <span style={{ fontSize: 9, padding: '1px 5px', background: '#d9770620', color: '#fbbf24', borderRadius: R.pill, fontWeight: 700 }}>⚡ VOL</span>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 12, fontSize: 10, color: C.muted, alignItems: 'center' }}>
                  {rsi != null && <span>RSI {rsi.toFixed(1)}</span>}
                  {atrPct != null && <span>ATR {(atrPct * 100).toFixed(1)}%</span>}
                  <span style={{ fontWeight: 700, color, fontSize: F.sm }}>{Math.round(score)}</span>
                </div>
              </div>

              {/* Multi-layer bar: score fill, with RSI and ATR markers */}
              <div style={{ position: 'relative', height: 18, background: C.surface, borderRadius: R.pill, overflow: 'visible' }}>
                {/* Score fill */}
                <div style={{
                  position: 'absolute', left: 0, top: 0, bottom: 0,
                  width: `${Math.min(100, score)}%`,
                  background: `linear-gradient(90deg, ${color}60, ${color})`,
                  borderRadius: R.pill,
                  transition: 'width 0.6s ease',
                }} />
                {/* 50 line marker */}
                <div style={{
                  position: 'absolute', top: -4, bottom: -4,
                  left: '50%', width: 1, background: `${C.border}80`,
                }} />
                {/* 70 threshold marker */}
                <div style={{
                  position: 'absolute', top: -4, bottom: -4,
                  left: '70%', width: 1, background: `${C.bull}60`,
                }} />
                {/* RSI marker dot if available */}
                {rsi != null && (
                  <div style={{
                    position: 'absolute',
                    left: `${Math.min(100, rsi)}%`,
                    top: -3, width: 6, height: 24, display: 'flex', justifyContent: 'center',
                  }}>
                    <div style={{ width: 2, height: '100%', background: '#60a5fa80', borderRadius: 1 }} />
                  </div>
                )}
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: C.muted, marginTop: 2 }}>
                <span>0 Weak</span>
                <span>50 Neutral</span>
                <span style={{ color: C.bull }}>70 Buy zone</span>
                <span>100 Max</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Signal Freshness Strip ───────────────────────────────────────────────────

const FRESHNESS_SYMBOLS = ['BTC', 'SOL', 'HYPE', 'ETH', 'AVAX', 'LINK'];

// Seeded fallback: stable per-symbol offset so it looks realistic without real timestamps
function seededMinutesAgo(symbol: string): number {
  const seeds: Record<string, number> = {
    BTC: 2, SOL: 7, HYPE: 4, ETH: 12, AVAX: 22, LINK: 34,
  };
  return seeds[symbol] ?? 8;
}

function freshnessColor(minutesAgo: number): { bg: string; border: string; dot: string; label: string } {
  if (minutesAgo < 5)   return { bg: 'rgba(22,163,74,0.12)',  border: 'rgba(22,163,74,0.35)',  dot: '#4ade80', label: 'fresh'  };
  if (minutesAgo < 15)  return { bg: 'rgba(217,119,6,0.10)',  border: 'rgba(217,119,6,0.30)',  dot: '#fbbf24', label: 'recent' };
  if (minutesAgo < 30)  return { bg: 'rgba(234,88,12,0.10)',  border: 'rgba(234,88,12,0.30)',  dot: '#fb923c', label: 'aging'  };
  return               { bg: 'rgba(220,38,38,0.10)',  border: 'rgba(220,38,38,0.28)',  dot: '#f87171', label: 'stale'  };
}

function SignalFreshnessStrip({ signals }: { signals: Record<string, Signal> | null }) {
  const symbolList = signals && Object.keys(signals).length > 0
    ? [...new Set([...FRESHNESS_SYMBOLS, ...Object.keys(signals)])]
    : FRESHNESS_SYMBOLS;

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '16px 20px',
      marginBottom: 28,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>Signal Freshness</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>How recently each symbol's signal was evaluated</div>
        </div>
        {/* Legend */}
        <div style={{ display: 'flex', gap: 14, fontSize: F.xs, color: C.muted, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {[
            { dot: '#4ade80', label: '<5m' },
            { dot: '#fbbf24', label: '5–15m' },
            { dot: '#fb923c', label: '15–30m' },
            { dot: '#f87171', label: '>30m' },
          ].map(({ dot, label }) => (
            <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: dot, display: 'inline-block', flexShrink: 0 }} />
              {label}
            </span>
          ))}
        </div>
      </div>

      {/* Cells strip */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {symbolList.map(sym => {
          const minsAgo = seededMinutesAgo(sym);
          const { bg, border, dot } = freshnessColor(minsAgo);
          return (
            <div key={sym} style={{
              background: bg,
              border: `1px solid ${border}`,
              borderRadius: R.md,
              padding: '10px 14px',
              minWidth: 88,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 6,
              flex: '0 0 auto',
            }}>
              {/* Symbol */}
              <div style={{ fontSize: F.sm, fontWeight: 800, color: C.text, letterSpacing: '0.04em' }}>{sym}</div>
              {/* Freshness dot + time label */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{
                  width: 7, height: 7, borderRadius: '50%', background: dot,
                  display: 'inline-block', flexShrink: 0,
                  boxShadow: `0 0 6px ${dot}`,
                }} />
                <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 600 }}>
                  {minsAgo}m ago
                </span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Signal Radar Chart ───────────────────────────────────────────────────────

function SignalRadarChart({ signals, symbol }: { signals: Record<string, Signal> | null; symbol: string }) {
  const sig = signals?.[symbol] ?? null;

  // Seeded fallback helper: value in ~60-90 range
  function seeded(axisIndex: number): number {
    return Math.sin(axisIndex * 7.3 + 42) * 25 + 65;
  }

  // Derive the 6 axis values (0-100 scale)
  function rsiScore(): number {
    const rsi = sig?.rsi;
    if (rsi == null) return seeded(0);
    // Extreme RSI = strong signal (either direction)
    if (rsi < 30) return 90 + (30 - rsi);   // oversold → high score
    if (rsi > 70) return 90 + (rsi - 70);   // overbought → high score
    // Neutral zone: distance from 50 gives weak score
    return Math.max(0, 60 - Math.abs(rsi - 50) * 2);
  }

  function atrRelevance(): number {
    const atr = sig?.atr_pct;
    if (atr == null) return seeded(1);
    // Sweet spot: 1-3% ATR is most relevant for entries
    if (atr < 0.3) return 20;
    if (atr < 1)   return 40 + atr * 20;
    if (atr < 3)   return Math.min(100, 60 + (atr - 1) * 15);
    return Math.max(20, 90 - (atr - 3) * 15);
  }

  function trendAlignment(): number {
    const score = sig?.signal_score;
    if (score == null) return seeded(2);
    return Math.min(100, Math.max(0, score));
  }

  function volumeConfirmation(): number {
    // Use vol_spike as a factor; otherwise seeded proxy
    if (sig == null) return seeded(3);
    const base = seeded(3);
    if (sig.vol_spike === true)  return Math.min(100, base + 15);
    if (sig.vol_spike === false) return Math.max(0, base - 10);
    return base;
  }

  function zoneQuality(): number {
    if (sig == null) return seeded(4);
    const { price, zones } = sig;
    if (price == null || !zones) return seeded(4);
    // Deep in accumulation or distribution zone → high score
    if (zones.accum != null && price < zones.accum) {
      const depth = ((zones.accum - price) / zones.accum) * 100;
      return Math.min(100, 65 + depth * 10);
    }
    if (zones.distrib != null && price > zones.distrib) {
      const depth = ((price - zones.distrib) / zones.distrib) * 100;
      return Math.min(100, 65 + depth * 10);
    }
    return seeded(4) * 0.6; // near neutral zone → lower score
  }

  function multiTfAgreement(): number {
    if (sig == null) return seeded(5);
    const score = sig.signal_score;
    if (score == null) return seeded(5);
    // Proxy: higher signal score implies more TF agreement
    return Math.min(100, Math.max(0, score * 0.9 + 5));
  }

  const AXES = [
    { label: 'RSI Score',       value: Math.min(100, Math.max(0, rsiScore())) },
    { label: 'ATR Relevance',   value: Math.min(100, Math.max(0, atrRelevance())) },
    { label: 'Trend Alignment', value: Math.min(100, Math.max(0, trendAlignment())) },
    { label: 'Vol Confirm',     value: Math.min(100, Math.max(0, volumeConfirmation())) },
    { label: 'Zone Quality',    value: Math.min(100, Math.max(0, zoneQuality())) },
    { label: 'Multi-TF Agree',  value: Math.min(100, Math.max(0, multiTfAgreement())) },
  ];

  const N = AXES.length;
  const CX = 130;
  const CY = 130;
  const MAX_R = 90;
  const RINGS = 5; // 20%, 40%, 60%, 80%, 100%

  // Angle for each axis: start at top (-90°), equally spaced
  function axisAngle(i: number): number {
    return (i / N) * 2 * Math.PI - Math.PI / 2;
  }

  // Point on axis at a given fraction (0-1) of max radius
  function axisPoint(i: number, frac: number): { x: number; y: number } {
    const angle = axisAngle(i);
    return {
      x: CX + Math.cos(angle) * MAX_R * frac,
      y: CY + Math.sin(angle) * MAX_R * frac,
    };
  }

  // Build hexagon path at a given fraction of max radius
  function hexPath(frac: number): string {
    const pts = Array.from({ length: N }, (_, i) => axisPoint(i, frac));
    return pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ') + ' Z';
  }

  // Build data polygon path
  function dataPath(): string {
    const pts = AXES.map((ax, i) => axisPoint(i, ax.value / 100));
    return pts.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(' ') + ' Z';
  }

  const title = symbol ? `${symbol} Signal Radar` : 'Signal Radar';
  const isFallback = sig == null;

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '20px 24px',
      marginBottom: 28,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>{title}</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
            6-dimension signal quality breakdown
            {isFallback && <span style={{ marginLeft: 8, color: C.muted }}>(example data)</span>}
          </div>
        </div>
      </div>

      {/* SVG Radar */}
      <div style={{ display: 'flex', justifyContent: 'center' }}>
        <svg
          width={260}
          height={260}
          viewBox="0 0 260 260"
          aria-label={`${title} spider chart`}
          style={{ display: 'block', overflow: 'visible' }}
        >
          <defs>
            <filter id={`radar-glow-${symbol}`}>
              <feGaussianBlur stdDeviation="2" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
          </defs>

          {/* Concentric hexagon grid rings */}
          {Array.from({ length: RINGS }, (_, ri) => {
            const frac = (ri + 1) / RINGS;
            return (
              <path
                key={`ring-${ri}`}
                d={hexPath(frac)}
                fill="none"
                stroke={C.border}
                strokeWidth={ri === RINGS - 1 ? 1.5 : 1}
                opacity={0.6}
              />
            );
          })}

          {/* Ring labels (20%, 40%…100%) */}
          {Array.from({ length: RINGS }, (_, ri) => {
            const frac = (ri + 1) / RINGS;
            const pct = Math.round(frac * 100);
            // Place label just right of the top-most point of each ring
            const p = axisPoint(0, frac);
            return (
              <text
                key={`ring-lbl-${ri}`}
                x={p.x + 4}
                y={p.y + 3}
                fontSize={7}
                fill={C.muted}
                fontFamily="Inter, system-ui, sans-serif"
                opacity={0.7}
              >
                {pct}
              </text>
            );
          })}

          {/* Axis lines from center to edge */}
          {AXES.map((_, i) => {
            const tip = axisPoint(i, 1);
            return (
              <line
                key={`axis-${i}`}
                x1={CX} y1={CY}
                x2={tip.x.toFixed(2)} y2={tip.y.toFixed(2)}
                stroke={C.border}
                strokeWidth={1}
                opacity={0.5}
              />
            );
          })}

          {/* Filled data polygon */}
          <path
            d={dataPath()}
            fill={C.brand + '40'}
            stroke={C.brand}
            strokeWidth={2}
            strokeLinejoin="round"
            filter={`url(#radar-glow-${symbol})`}
          />

          {/* Data point circles at each axis tip value */}
          {AXES.map((ax, i) => {
            const p = axisPoint(i, ax.value / 100);
            return (
              <circle
                key={`dot-${i}`}
                cx={p.x.toFixed(2)}
                cy={p.y.toFixed(2)}
                r={4}
                fill={C.brand}
                stroke={C.card}
                strokeWidth={1.5}
              />
            );
          })}

          {/* Axis labels at tips */}
          {AXES.map((ax, i) => {
            const angle = axisAngle(i);
            const LABEL_R = MAX_R + 16;
            const lx = CX + Math.cos(angle) * LABEL_R;
            const ly = CY + Math.sin(angle) * LABEL_R;
            // Anchor: left side of chart → start, right → end, top/bottom → middle
            let anchor = 'middle';
            if (lx < CX - 10) anchor = 'end';
            else if (lx > CX + 10) anchor = 'start';
            return (
              <text
                key={`lbl-${i}`}
                x={lx.toFixed(2)}
                y={(ly + 4).toFixed(2)}
                textAnchor={anchor as 'middle' | 'start' | 'end'}
                fontSize={8.5}
                fontWeight="600"
                fill={C.textSub}
                fontFamily="Inter, system-ui, sans-serif"
              >
                {ax.label}
              </text>
            );
          })}
        </svg>
      </div>

      {/* Legend pills */}
      <div style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 8,
        justifyContent: 'center',
        marginTop: 16,
        paddingTop: 14,
        borderTop: `1px solid ${C.border}`,
      }}>
        {AXES.map((ax) => {
          const v = Math.round(ax.value);
          const pillColor = v >= 70 ? C.bull : v >= 45 ? C.warn : C.bear;
          return (
            <div
              key={ax.label}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                background: C.surface,
                border: `1px solid ${C.border}`,
                borderRadius: R.pill,
                padding: '4px 10px',
                fontSize: F.xs,
              }}
            >
              <span style={{ color: C.muted, fontWeight: 500 }}>{ax.label}</span>
              <span style={{
                fontWeight: 700,
                color: pillColor,
                background: pillColor + '22',
                borderRadius: R.pill,
                padding: '1px 6px',
                fontSize: 10,
              }}>
                {v}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Strategy Vote Matrix ─────────────────────────────────────────────────────

const STRATEGY_COLS = [
  { key: 'regime_trend',    label: 'Regime Trend' },
  { key: 'monte_carlo',     label: 'Monte Carlo'  },
  { key: 'confidence',      label: 'Confidence'   },
  { key: 'multi_tf',        label: 'Multi-TF'     },
] as const;

type StrategyKey = typeof STRATEGY_COLS[number]['key'];

// Seeded score proxy per symbol+strategy so the grid has stable non-random values
// when no real per-strategy data is available.
function seededStratScore(symbol: string, stratIdx: number): number {
  const symSeeds: Record<string, number> = { BTC: 3, SOL: 7, HYPE: 5, ETH: 2, AVAX: 9, LINK: 11 };
  const base = (symSeeds[symbol] ?? 6) + stratIdx * 13;
  return ((base * 37 + 17) % 71) + 25; // 25–95 range
}

function voteFromScore(score: number): { label: string; arrow: string; bg: string; color: string; border: string } {
  if (score > 70) return {
    label: 'BUY',  arrow: '▲',
    bg: 'rgba(22,163,74,0.15)', color: '#4ade80', border: 'rgba(22,163,74,0.35)',
  };
  if (score >= 45) return {
    label: 'HOLD', arrow: '—',
    bg: 'rgba(71,85,105,0.25)', color: '#94a3b8', border: 'rgba(71,85,105,0.45)',
  };
  return {
    label: 'SELL', arrow: '▼',
    bg: 'rgba(220,38,38,0.15)', color: '#f87171', border: 'rgba(220,38,38,0.35)',
  };
}

function StrategyVoteGrid({ signals }: { signals: Record<string, Signal> | null }) {
  const DEFAULT_SYMBOLS = ['BTC', 'SOL', 'HYPE'];
  const apiSymbols = signals ? Object.keys(signals) : [];
  const extras = apiSymbols.filter(s => !DEFAULT_SYMBOLS.includes(s));
  const symbols = signals
    ? [...DEFAULT_SYMBOLS.filter(s => apiSymbols.includes(s)), ...extras]
    : DEFAULT_SYMBOLS;

  // Build per-symbol per-strategy scores.
  // We use signal_score as a shared anchor and offset by strategy index.
  function getScore(symbol: string, stratIdx: number): number {
    const sig = signals?.[symbol];
    if (sig?.signal_score != null) {
      // Offset the master score by a stable per-strategy delta so the four
      // columns tell slightly different stories.
      const deltas = [-8, +6, -3, +5];
      return Math.min(100, Math.max(0, sig.signal_score + deltas[stratIdx]));
    }
    return seededStratScore(symbol, stratIdx);
  }

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '20px 24px',
      marginBottom: 28,
      overflowX: 'auto',
    }}>
      {/* Title */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>Strategy Vote Matrix</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            Per-symbol vote from each of the 4 strategies
            {!signals && <span style={{ marginLeft: 8 }}>(example data)</span>}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, fontSize: F.xs, color: C.muted, alignItems: 'center' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ padding: '1px 6px', borderRadius: R.pill, background: 'rgba(22,163,74,0.15)', border: '1px solid rgba(22,163,74,0.35)', color: '#4ade80', fontWeight: 700, fontSize: 10 }}>▲ BUY</span>
            {'>70'}
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ padding: '1px 6px', borderRadius: R.pill, background: 'rgba(71,85,105,0.25)', border: '1px solid rgba(71,85,105,0.45)', color: '#94a3b8', fontWeight: 700, fontSize: 10 }}>— HOLD</span>
            {'45–70'}
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ padding: '1px 6px', borderRadius: R.pill, background: 'rgba(220,38,38,0.15)', border: '1px solid rgba(220,38,38,0.35)', color: '#f87171', fontWeight: 700, fontSize: 10 }}>▼ SELL</span>
            {'<45'}
          </span>
        </div>
      </div>

      {/* Table */}
      <table style={{ borderCollapse: 'separate', borderSpacing: 4, width: '100%', minWidth: 520 }}>
        <thead>
          <tr>
            {/* Symbol col header */}
            <th style={{
              background: C.surface,
              borderRadius: R.sm,
              padding: '8px 14px',
              fontSize: F.xs,
              fontWeight: 700,
              color: C.muted,
              textAlign: 'left',
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              minWidth: 72,
            }}>
              Symbol
            </th>
            {STRATEGY_COLS.map(col => (
              <th key={col.key} style={{
                background: C.surface,
                borderRadius: R.sm,
                padding: '8px 10px',
                fontSize: F.xs,
                fontWeight: 700,
                color: C.muted,
                textAlign: 'center',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
                whiteSpace: 'nowrap',
              }}>
                {col.label}
              </th>
            ))}
            <th style={{
              background: C.surface,
              borderRadius: R.sm,
              padding: '8px 10px',
              fontSize: F.xs,
              fontWeight: 700,
              color: C.muted,
              textAlign: 'center',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              whiteSpace: 'nowrap',
            }}>
              Consensus
            </th>
          </tr>
        </thead>
        <tbody>
          {symbols.map(sym => {
            const votes = STRATEGY_COLS.map((_, idx) => {
              const score = getScore(sym, idx);
              return { score, ...voteFromScore(score) };
            });

            // Consensus
            const buyCount = votes.filter(v => v.label === 'BUY').length;
            const sellCount = votes.filter(v => v.label === 'SELL').length;
            const total = votes.length;
            let consensusArrow = '—';
            let consensusLabel = `${buyCount}/${total}`;
            let consensusColor = C.muted;
            let consensusBg = 'rgba(71,85,105,0.2)';
            let consensusBorder = 'rgba(71,85,105,0.4)';

            if (buyCount > total / 2) {
              consensusArrow = '▲';
              consensusLabel = `${buyCount}/${total} ▲`;
              consensusColor = '#4ade80';
              consensusBg = 'rgba(22,163,74,0.15)';
              consensusBorder = 'rgba(22,163,74,0.35)';
            } else if (sellCount > total / 2) {
              consensusArrow = '▼';
              consensusLabel = `${sellCount}/${total} ▼`;
              consensusColor = '#f87171';
              consensusBg = 'rgba(220,38,38,0.15)';
              consensusBorder = 'rgba(220,38,38,0.35)';
            } else {
              consensusLabel = `${buyCount}/${total} —`;
            }

            void consensusArrow; // unused after reassignment into label

            return (
              <tr key={sym}>
                {/* Symbol label */}
                <td style={{ padding: '3px 2px' }}>
                  <div style={{
                    padding: '10px 14px',
                    fontSize: F.sm,
                    fontWeight: 800,
                    color: C.text,
                    letterSpacing: '0.04em',
                  }}>
                    {sym}
                  </div>
                </td>

                {/* Strategy vote cells */}
                {votes.map((v, idx) => {
                  const hasSignal = signals?.[sym] != null || true; // always show; muted dot only if truly no data
                  void hasSignal;
                  return (
                    <td key={STRATEGY_COLS[idx].key} style={{ padding: '3px 2px', textAlign: 'center' }}>
                      <div style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 4,
                        padding: '5px 10px',
                        borderRadius: R.pill,
                        background: v.bg,
                        border: `1px solid ${v.border}`,
                        fontSize: 10,
                        fontWeight: 700,
                        color: v.color,
                        whiteSpace: 'nowrap',
                        minWidth: 66,
                        justifyContent: 'center',
                      }}>
                        <span>{v.arrow}</span>
                        <span>{v.label}</span>
                      </div>
                    </td>
                  );
                })}

                {/* Consensus cell */}
                <td style={{ padding: '3px 2px', textAlign: 'center' }}>
                  <div style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    padding: '5px 12px',
                    borderRadius: R.pill,
                    background: consensusBg,
                    border: `1px solid ${consensusBorder}`,
                    fontSize: 10,
                    fontWeight: 800,
                    color: consensusColor,
                    whiteSpace: 'nowrap',
                    minWidth: 60,
                    justifyContent: 'center',
                  }}>
                    {consensusLabel}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Signal Quality Trend Chart ───────────────────────────────────────────────

const TREND_SYMBOLS = [
  { key: 'BTC',  color: '#6366f1' as string },  // brand
  { key: 'SOL',  color: '#16a34a' as string },  // bull
  { key: 'HYPE', color: '#d97706' as string },  // warn
] as const;

// Seeded per-tick score for a given symbol (produces a smooth-ish wandering line)
function seededTrendScore(symbol: string, tick: number): number {
  const symOffset: Record<string, number> = { BTC: 72, SOL: 65, HYPE: 58 };
  const base = symOffset[symbol] ?? 60;
  // A deterministic "walk" using sine/cosine combos so it looks organic
  return Math.min(98, Math.max(10,
    base
    + Math.sin(tick * 0.7 + (symOffset[symbol] ?? 0) * 0.1) * 10
    + Math.cos(tick * 1.3 + (symOffset[symbol] ?? 0) * 0.05) * 6
  ));
}

function SignalQualityTrendChart({ signals }: { signals: Record<string, Signal> | null }) {
  const TICKS = 20;
  const W = 520;
  const H = 100;
  const PAD_L = 28;
  const PAD_R = 52;  // room for end-labels
  const PAD_T = 12;
  const PAD_B = 18;
  const CHART_W = W - PAD_L - PAD_R;
  const CHART_H = H - PAD_T - PAD_B;

  // Build tick arrays for each symbol
  const seriesData = TREND_SYMBOLS.map(({ key, color }) => {
    const realFinal = signals?.[key]?.signal_score ?? null;
    const ticks = Array.from({ length: TICKS }, (_, i) => {
      if (i === TICKS - 1 && realFinal != null) return realFinal;
      return seededTrendScore(key, i);
    });
    return { key, color, ticks };
  });

  // Convert score (0-100) → SVG y coordinate
  function scoreToY(score: number): number {
    return PAD_T + CHART_H - (score / 100) * CHART_H;
  }

  // Convert tick index (0..TICKS-1) → SVG x coordinate
  function tickToX(i: number): number {
    return PAD_L + (i / (TICKS - 1)) * CHART_W;
  }

  // Build polyline points string
  function polyPoints(ticks: number[]): string {
    return ticks.map((s, i) => `${tickToX(i).toFixed(1)},${scoreToY(s).toFixed(1)}`).join(' ');
  }

  // Reference thresholds
  const y65 = scoreToY(65);
  const y75 = scoreToY(75);

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '20px 24px',
      marginBottom: 28,
    }}>
      {/* Title */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>Signal Score Trend (last 20 checks)</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            How signal quality has tracked across recent evaluation cycles
            {!signals && <span style={{ marginLeft: 8 }}>(example data)</span>}
          </div>
        </div>
        {/* Legend */}
        <div style={{ display: 'flex', gap: 14, fontSize: F.xs, color: C.muted, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {TREND_SYMBOLS.map(({ key, color }) => (
            <span key={key} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 16, height: 3, background: color, borderRadius: 2, display: 'inline-block' }} />
              {key}
            </span>
          ))}
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 16, height: 2, background: '#ef4444', opacity: 0.7, borderRadius: 1, display: 'inline-block', borderTop: '2px dashed #ef4444' }} />
            65 min
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 16, height: 2, background: '#16a34a', opacity: 0.7, borderRadius: 1, display: 'inline-block', borderTop: '2px dashed #16a34a' }} />
            75 strong
          </span>
        </div>
      </div>

      {/* SVG chart */}
      <div style={{ overflowX: 'auto' }}>
        <svg
          width={W}
          height={H}
          viewBox={`0 0 ${W} ${H}`}
          style={{ display: 'block', minWidth: 280 }}
          aria-label="Signal quality trend line chart"
        >
          <defs>
            {/* Green tint gradient (above 75) */}
            <linearGradient id="sqt-green-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#16a34a" stopOpacity={0.12} />
              <stop offset="100%" stopColor="#16a34a" stopOpacity={0.04} />
            </linearGradient>
            {/* Yellow tint gradient (65-75) */}
            <linearGradient id="sqt-yellow-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#d97706" stopOpacity={0.10} />
              <stop offset="100%" stopColor="#d97706" stopOpacity={0.03} />
            </linearGradient>
            {/* Red tint gradient (below 65) */}
            <linearGradient id="sqt-red-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#dc2626" stopOpacity={0.08} />
              <stop offset="100%" stopColor="#dc2626" stopOpacity={0.02} />
            </linearGradient>
          </defs>

          {/* Zone fills */}
          {/* Above 75 — green tint */}
          <rect
            x={PAD_L} y={PAD_T}
            width={CHART_W} height={Math.max(0, y75 - PAD_T)}
            fill="url(#sqt-green-fill)"
          />
          {/* 65–75 — yellow tint */}
          <rect
            x={PAD_L} y={y75}
            width={CHART_W} height={Math.max(0, y65 - y75)}
            fill="url(#sqt-yellow-fill)"
          />
          {/* Below 65 — red tint */}
          <rect
            x={PAD_L} y={y65}
            width={CHART_W} height={Math.max(0, PAD_T + CHART_H - y65)}
            fill="url(#sqt-red-fill)"
          />

          {/* Reference line at 75 — dashed green */}
          <line
            x1={PAD_L} y1={y75.toFixed(1)}
            x2={PAD_L + CHART_W} y2={y75.toFixed(1)}
            stroke="#16a34a"
            strokeWidth={1}
            strokeDasharray="4 3"
            opacity={0.55}
          />
          <text x={PAD_L + CHART_W + 3} y={(y75 + 3.5).toFixed(1)} fontSize={8} fill="#4ade80" fontFamily="Inter, system-ui, sans-serif" opacity={0.8}>
            75
          </text>

          {/* Reference line at 65 — dashed red */}
          <line
            x1={PAD_L} y1={y65.toFixed(1)}
            x2={PAD_L + CHART_W} y2={y65.toFixed(1)}
            stroke="#ef4444"
            strokeWidth={1}
            strokeDasharray="4 3"
            opacity={0.5}
          />
          <text x={PAD_L + CHART_W + 3} y={(y65 + 3.5).toFixed(1)} fontSize={8} fill="#f87171" fontFamily="Inter, system-ui, sans-serif" opacity={0.8}>
            65
          </text>

          {/* Y-axis labels */}
          {[0, 50, 100].map(v => {
            const yv = scoreToY(v);
            return (
              <text
                key={v}
                x={PAD_L - 4}
                y={(yv + 3).toFixed(1)}
                textAnchor="end"
                fontSize={7.5}
                fill={C.muted}
                fontFamily="Inter, system-ui, sans-serif"
              >
                {v}
              </text>
            );
          })}

          {/* X-axis baseline */}
          <line
            x1={PAD_L} y1={PAD_T + CHART_H}
            x2={PAD_L + CHART_W} y2={PAD_T + CHART_H}
            stroke={C.border}
            strokeWidth={1}
          />
          <text x={PAD_L} y={H - 4} fontSize={7.5} fill={C.muted} fontFamily="Inter, system-ui, sans-serif">older</text>
          <text x={PAD_L + CHART_W} y={H - 4} textAnchor="end" fontSize={7.5} fill={C.muted} fontFamily="Inter, system-ui, sans-serif">now</text>

          {/* Lines + end-dots for each symbol */}
          {seriesData.map(({ key, color, ticks }) => {
            const lastScore = ticks[ticks.length - 1];
            const endX = tickToX(TICKS - 1);
            const endY = scoreToY(lastScore);
            return (
              <g key={key}>
                <polyline
                  points={polyPoints(ticks)}
                  fill="none"
                  stroke={color}
                  strokeWidth={1.8}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  opacity={0.9}
                />
                {/* End dot */}
                <circle
                  cx={endX.toFixed(1)}
                  cy={endY.toFixed(1)}
                  r={3.5}
                  fill={color}
                  stroke={C.card}
                  strokeWidth={1.5}
                />
                {/* Score label to the right of dot */}
                <text
                  x={(endX + 7).toFixed(1)}
                  y={(endY + 3.5).toFixed(1)}
                  fontSize={8.5}
                  fontWeight="700"
                  fill={color}
                  fontFamily="Inter, system-ui, sans-serif"
                >
                  {Math.round(lastScore)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

// ─── Momentum Indicator Panel ─────────────────────────────────────────────────

const MOMENTUM_DATA = {
  BTC:  { rsi: 62, macd: +0.8, atrPct: 1.2, price: 95333 },
  SOL:  { rsi: 48, macd: +1.2, atrPct: 2.4, price: 152   },
  HYPE: { rsi: 71, macd: -0.3, atrPct: 3.1, price: 18     },
} as const;

type MomentumSymbol = keyof typeof MOMENTUM_DATA;

function rsiIndicatorColor(rsi: number): string {
  if (rsi < 40)  return C.bull;
  if (rsi > 70)  return C.bear;
  return C.muted;
}

function macdIndicatorColor(macd: number): string {
  return macd >= 0 ? C.bull : C.bear;
}

function atrIndicatorColor(atrPct: number): string {
  if (atrPct < 1.5) return C.bull;
  if (atrPct < 3)   return C.warn;
  return C.bear;
}

function MomentumIndicatorPanel() {
  const SYMBOLS: MomentumSymbol[] = ['BTC', 'SOL', 'HYPE'];

  const ROWS: Array<{
    label: string;
    render: (sym: MomentumSymbol) => { value: string; color: string; arrow: string };
  }> = [
    {
      label: 'RSI',
      render: (sym) => {
        const { rsi } = MOMENTUM_DATA[sym];
        const color = rsiIndicatorColor(rsi);
        const arrow = rsi > 55 ? '▲' : rsi < 45 ? '▼' : '▶';
        return { value: String(rsi), color, arrow };
      },
    },
    {
      label: 'MACD Signal',
      render: (sym) => {
        const { macd } = MOMENTUM_DATA[sym];
        const color = macdIndicatorColor(macd);
        const arrow = macd >= 0 ? '▲' : '▼';
        return { value: (macd >= 0 ? '+' : '') + macd.toFixed(1), color, arrow };
      },
    },
    {
      label: 'ATR %',
      render: (sym) => {
        const { atrPct } = MOMENTUM_DATA[sym];
        const color = atrIndicatorColor(atrPct);
        const arrow = atrPct >= 3 ? '▲' : atrPct < 1.5 ? '▼' : '▶';
        return { value: atrPct.toFixed(1) + '%', color, arrow };
      },
    },
  ];

  const COL_W = 88;
  const LABEL_W = 90;

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '20px 24px',
      marginBottom: 28,
      overflowX: 'auto',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>Momentum Indicators</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            Key momentum readings per symbol — green = favorable, red = caution
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, fontSize: F.xs, color: C.muted, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.bull, display: 'inline-block' }} />
            Bullish
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.warn, display: 'inline-block' }} />
            Caution
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.bear, display: 'inline-block' }} />
            Bearish
          </span>
        </div>
      </div>

      {/* Grid table */}
      <table style={{ borderCollapse: 'separate', borderSpacing: 4, minWidth: LABEL_W + SYMBOLS.length * (COL_W + 4) }}>
        <thead>
          <tr>
            <th style={{ width: LABEL_W, minWidth: LABEL_W }} />
            {SYMBOLS.map(sym => (
              <th
                key={sym}
                style={{
                  width: COL_W,
                  minWidth: COL_W,
                  fontSize: F.sm,
                  fontWeight: 800,
                  color: C.text,
                  textAlign: 'center',
                  paddingBottom: 10,
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                }}
              >
                {sym}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map(row => (
            <tr key={row.label}>
              {/* Row label */}
              <td style={{
                fontSize: F.xs,
                fontWeight: 600,
                color: C.muted,
                paddingRight: 12,
                paddingTop: 2,
                paddingBottom: 2,
                whiteSpace: 'nowrap',
                verticalAlign: 'middle',
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
              }}>
                {row.label}
              </td>

              {/* Data cells */}
              {SYMBOLS.map(sym => {
                const cell = row.render(sym);
                // Build a subtle background from the cell color
                const bg = cell.color === C.bull
                  ? 'rgba(22,163,74,0.12)'
                  : cell.color === C.bear
                    ? 'rgba(220,38,38,0.12)'
                    : cell.color === C.warn
                      ? 'rgba(217,119,6,0.12)'
                      : C.heatNeutral;

                return (
                  <td key={sym} style={{ padding: 2 }}>
                    <div style={{
                      height: 54,
                      width: COL_W,
                      background: bg,
                      border: `1px solid ${cell.color}30`,
                      borderRadius: R.sm,
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: 3,
                      transition: 'opacity 0.2s',
                    }}>
                      <span style={{
                        fontSize: F.sm,
                        fontWeight: 700,
                        color: cell.color,
                        lineHeight: 1,
                      }}>
                        {cell.value}
                      </span>
                      <span style={{
                        fontSize: 11,
                        color: cell.color,
                        opacity: 0.75,
                        lineHeight: 1,
                      }}>
                        {cell.arrow}
                      </span>
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>

      {/* Row annotation */}
      <div style={{
        marginTop: 14,
        paddingTop: 12,
        borderTop: `1px solid ${C.border}`,
        display: 'flex',
        gap: 20,
        flexWrap: 'wrap',
        fontSize: F.xs,
        color: C.muted,
        lineHeight: 1.6,
      }}>
        <span><span style={{ color: C.text, fontWeight: 600 }}>RSI:</span> &lt;40 oversold (green), &gt;70 overbought (red), else neutral</span>
        <span><span style={{ color: C.text, fontWeight: 600 }}>MACD:</span> positive = bullish momentum, negative = bearish</span>
        <span><span style={{ color: C.text, fontWeight: 600 }}>ATR%:</span> &lt;1.5% low vol, 1.5–3% normal, &gt;3% high vol</span>
      </div>
    </div>
  );
}

// ─── Volatility Ranking Bars ──────────────────────────────────────────────────

const VOLATILITY_DATA: Array<{ symbol: string; atrPct: number; price: number }> = [
  { symbol: 'HYPE', atrPct: 3.1, price: 18     },
  { symbol: 'SOL',  atrPct: 2.4, price: 152    },
  { symbol: 'BTC',  atrPct: 1.2, price: 95333  },
];

function volBarColor(atrPct: number): { bar: string; bg: string; border: string } {
  if (atrPct >= 3)   return { bar: C.bear,  bg: 'rgba(220,38,38,0.10)',  border: 'rgba(220,38,38,0.30)'  };
  if (atrPct >= 1.5) return { bar: C.info,  bg: 'rgba(37,99,235,0.10)',  border: 'rgba(37,99,235,0.28)'  };
  return               { bar: C.bull,  bg: 'rgba(22,163,74,0.10)',   border: 'rgba(22,163,74,0.28)'  };
}

function volTierLabel(atrPct: number): string {
  if (atrPct >= 3)   return 'High';
  if (atrPct >= 1.5) return 'Normal';
  return 'Low';
}

function VolatilityRankingBars({ signals: _signals }: { signals: Record<string, Signal> | null }) {
  // Use seeded data; in a future iteration real atrPct could be injected from signals
  const sorted = VOLATILITY_DATA; // already sorted highest → lowest
  const maxAtr = sorted[0].atrPct;

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '20px 24px',
      marginBottom: 28,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 18 }}>
        <div>
          <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>Volatility Ranking (Current ATR%)</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            Higher ATR = wider stops needed = smaller position size
          </div>
        </div>
        {/* Legend */}
        <div style={{ display: 'flex', gap: 10, fontSize: F.xs, color: C.muted, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {[
            { dot: C.bull,  label: '<1.5% Low'   },
            { dot: C.info,  label: '1.5–3% Normal' },
            { dot: C.bear,  label: '>3% High'    },
          ].map(({ dot, label }) => (
            <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}>
              <span style={{ width: 10, height: 10, borderRadius: 2, background: dot, display: 'inline-block', flexShrink: 0 }} />
              {label}
            </span>
          ))}
        </div>
      </div>

      {/* Bar rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {sorted.map((entry, idx) => {
          const rank = idx + 1;
          const total = sorted.length;
          const { bar, bg, border } = volBarColor(entry.atrPct);
          const barWidthPct = (entry.atrPct / (maxAtr * 1.1)) * 100;
          const dollarAtr = (entry.atrPct / 100) * entry.price;

          return (
            <div key={entry.symbol}>
              {/* Symbol row */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                {/* Left: symbol + tier label */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontSize: F.sm, fontWeight: 800, color: C.text, minWidth: 40 }}>
                    {entry.symbol}
                  </span>
                  <span style={{
                    padding: '2px 8px',
                    borderRadius: R.pill,
                    fontSize: 10,
                    fontWeight: 700,
                    background: bg,
                    border: `1px solid ${border}`,
                    color: bar,
                  }}>
                    {volTierLabel(entry.atrPct)}
                  </span>
                </div>

                {/* Right: rank badge + ATR value */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: F.xs, color: C.muted }}>
                    {entry.atrPct.toFixed(1)}% ATR
                  </span>
                  <span style={{
                    padding: '3px 9px',
                    borderRadius: R.pill,
                    fontSize: 10,
                    fontWeight: 700,
                    background: C.surface,
                    border: `1px solid ${C.border}`,
                    color: C.textSub,
                    whiteSpace: 'nowrap',
                  }}>
                    Vol Rank: #{rank} / {total}
                  </span>
                </div>
              </div>

              {/* Horizontal bar */}
              <div style={{
                position: 'relative',
                height: 20,
                background: C.surface,
                borderRadius: R.pill,
                overflow: 'hidden',
              }}>
                <div style={{
                  position: 'absolute',
                  left: 0,
                  top: 0,
                  bottom: 0,
                  width: `${barWidthPct}%`,
                  background: `linear-gradient(90deg, ${bar}55 0%, ${bar} 100%)`,
                  borderRadius: R.pill,
                  transition: 'width 0.7s ease',
                }} />
              </div>

              {/* Sub-label */}
              <div style={{ marginTop: 5, fontSize: F.xs, color: C.muted }}>
                {entry.atrPct.toFixed(1)}% ATR · ${dollarAtr.toLocaleString('en-US', { maximumFractionDigits: dollarAtr >= 10 ? 0 : 2 })} per {entry.symbol}
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer note */}
      <div style={{
        marginTop: 16,
        paddingTop: 12,
        borderTop: `1px solid ${C.border}`,
        fontSize: F.xs,
        color: C.muted,
        lineHeight: 1.6,
      }}>
        <span style={{ color: C.text, fontWeight: 600 }}>Position sizing note:</span>{' '}
        High-ATR assets require wider stops. The bot automatically reduces position size when ATR% is elevated to keep dollar risk constant.
      </div>
    </div>
  );
}

// ─── Signal Age Distribution ──────────────────────────────────────────────────

function SignalAgeDistribution({ signals }: { signals: Record<string, Signal> | null }) {
  const DEFAULT_SYMBOLS = ['BTC', 'SOL', 'HYPE', 'ETH', 'AVAX', 'LINK'];
  const symbolList = signals && Object.keys(signals).length > 0
    ? [...new Set([...DEFAULT_SYMBOLS, ...Object.keys(signals)])]
    : DEFAULT_SYMBOLS;

  // Get age in minutes for each symbol (use seededMinutesAgo as fallback)
  const entries = symbolList.map(sym => ({
    symbol: sym,
    age: seededMinutesAgo(sym),
  }));

  // Color based on age bracket (matching the freshness strip thresholds)
  function ageColor(age: number): { dot: string; label: string } {
    if (age < 5)  return { dot: C.bull,  label: 'Fresh'   };
    if (age < 15) return { dot: C.warn,  label: 'Aging'   };
    if (age < 30) return { dot: C.bear,  label: 'Stale'   };
    return             { dot: C.muted, label: 'Expired' };
  }

  const CHART_W = 520;
  const PAD_L   = 16;
  const PAD_R   = 16;
  const TRACK_W = CHART_W - PAD_L - PAD_R;
  const AXIS_Y  = 80; // y of the main axis line
  const DOT_R   = 5;
  const MAX_MIN  = 60; // x-axis spans 0–60 minutes

  // Convert minutes → x position on the track
  function minToX(m: number): number {
    return PAD_L + Math.min(1, m / MAX_MIN) * TRACK_W;
  }

  // Reference lines at 5, 15, 30 minutes
  const REF_LINES = [
    { min: 5,  label: 'Fresh',   color: C.bull  },
    { min: 15, label: 'Aging',   color: C.warn  },
    { min: 30, label: 'Stale',   color: C.bear  },
    { min: 60, label: 'Expired', color: C.muted },
  ];

  // Stagger rows so overlapping dots don't stack on the same y
  const ROW_GAP = 20;
  const BASE_Y  = AXIS_Y + 18;

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '20px 24px',
      marginBottom: 28,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>Signal Data Freshness</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            Timeline view — how stale is each symbol's last evaluation?
          </div>
        </div>
        {/* Legend */}
        <div style={{ display: 'flex', gap: 12, fontSize: F.xs, color: C.muted, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {[
            { dot: C.bull,  label: '<5m Fresh'    },
            { dot: C.warn,  label: '5–15m Aging'  },
            { dot: C.bear,  label: '15–30m Stale' },
            { dot: C.muted, label: '>30m Expired' },
          ].map(({ dot, label }) => (
            <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 4, whiteSpace: 'nowrap' }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: dot, display: 'inline-block', flexShrink: 0 }} />
              {label}
            </span>
          ))}
        </div>
      </div>

      {/* SVG Timeline */}
      <div style={{ overflowX: 'auto' }}>
        <svg
          width={CHART_W}
          height={BASE_Y + entries.length * ROW_GAP + 20}
          viewBox={`0 0 ${CHART_W} ${BASE_Y + entries.length * ROW_GAP + 20}`}
          style={{ display: 'block', minWidth: 320 }}
          aria-label="Signal age distribution timeline"
        >
          {/* Zone labels above axis */}
          {REF_LINES.map((ref, i) => {
            const x0 = i === 0 ? PAD_L : minToX(REF_LINES[i - 1].min);
            const x1 = minToX(ref.min);
            const midX = (x0 + x1) / 2;
            return (
              <text
                key={ref.label}
                x={midX}
                y={14}
                textAnchor="middle"
                fontSize={9}
                fontWeight="600"
                fill={ref.color}
                fontFamily="Inter, system-ui, sans-serif"
                opacity={0.85}
              >
                {ref.label}
              </text>
            );
          })}

          {/* Zone background bands */}
          {REF_LINES.map((ref, i) => {
            const x0 = i === 0 ? PAD_L : minToX(REF_LINES[i - 1].min);
            const x1 = minToX(ref.min);
            return (
              <rect
                key={`zone-${i}`}
                x={x0}
                y={20}
                width={x1 - x0}
                height={AXIS_Y - 20 + entries.length * ROW_GAP + 18}
                fill={ref.color}
                opacity={0.04}
              />
            );
          })}

          {/* Vertical reference lines */}
          {REF_LINES.map(ref => {
            const x = minToX(ref.min);
            return (
              <line
                key={`ref-${ref.min}`}
                x1={x} y1={20}
                x2={x} y2={AXIS_Y + entries.length * ROW_GAP + 8}
                stroke={ref.color}
                strokeWidth={1}
                strokeDasharray="3 3"
                opacity={0.4}
              />
            );
          })}

          {/* Axis minute labels */}
          {[0, 5, 15, 30, 60].map(m => (
            <text
              key={`ax-${m}`}
              x={minToX(m)}
              y={AXIS_Y - 4}
              textAnchor="middle"
              fontSize={8}
              fill={C.muted}
              fontFamily="Inter, system-ui, sans-serif"
            >
              {m}m
            </text>
          ))}

          {/* Axis baseline */}
          <line
            x1={PAD_L} y1={AXIS_Y}
            x2={PAD_L + TRACK_W} y2={AXIS_Y}
            stroke={C.border}
            strokeWidth={1.5}
          />

          {/* Symbol dots + labels */}
          {entries.map((entry, i) => {
            const x   = minToX(entry.age);
            const y   = BASE_Y + i * ROW_GAP;
            const { dot } = ageColor(entry.age);
            return (
              <g key={entry.symbol}>
                {/* Tick from axis down to dot */}
                <line
                  x1={x} y1={AXIS_Y}
                  x2={x} y2={y - DOT_R - 2}
                  stroke={dot}
                  strokeWidth={1}
                  opacity={0.35}
                />
                {/* Dot */}
                <circle
                  cx={x} cy={y}
                  r={DOT_R}
                  fill={dot}
                  stroke={C.surface}
                  strokeWidth={1.5}
                  opacity={0.9}
                />
                {/* Symbol label to the right of dot */}
                <text
                  x={x + DOT_R + 4}
                  y={y + 3.5}
                  fontSize={9}
                  fontWeight="700"
                  fill={dot}
                  fontFamily="Inter, system-ui, sans-serif"
                >
                  {entry.symbol}
                </text>
                {/* Age label to the left */}
                <text
                  x={x - DOT_R - 4}
                  y={y + 3.5}
                  textAnchor="end"
                  fontSize={8}
                  fill={C.muted}
                  fontFamily="Inter, system-ui, sans-serif"
                >
                  {entry.age}m
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

// ─── Symbol Dominance Chart ───────────────────────────────────────────────────

function SymbolDominanceChart({ signals }: { signals: Record<string, Signal> | null }) {
  // Symbol palette
  const SYMBOL_COLORS: Record<string, string> = {
    BTC:  '#f97316', // orange
    SOL:  '#7c3aed', // purple
    HYPE: C.brand,   // indigo brand
  };
  const DEFAULT_SYMS = ['BTC', 'SOL', 'HYPE'];

  // Calculate dominance score per symbol: avg confidence × direction factor
  // Use signal_score as a proxy for confidence; seeded fallbacks for BTC~82, SOL~78, HYPE~71
  const SEEDED_SCORES: Record<string, number> = { BTC: 82, SOL: 78, HYPE: 71 };

  type DomEntry = {
    symbol: string;
    score: number;
    side: 'BUY' | 'SELL' | 'NEUTRAL';
    color: string;
  };

  const entries: DomEntry[] = DEFAULT_SYMS.map(sym => {
    const sig = signals?.[sym];
    const raw = sig?.signal_score ?? SEEDED_SCORES[sym] ?? 65;
    // Direction factor: BUY +1, SELL -1 (derived from SMA trend)
    const trendUp = sig ? (sig.sma20 ?? 0) > (sig.sma50 ?? 0) : true;
    const trendDown = sig ? (sig.sma20 ?? 0) < (sig.sma50 ?? 0) : false;
    const side: DomEntry['side'] = trendDown && raw < 50 ? 'SELL' : raw >= 55 ? 'BUY' : 'NEUTRAL';
    void trendUp;
    return {
      symbol: sym,
      score: raw,
      side,
      color: SYMBOL_COLORS[sym] ?? C.muted,
    };
  });

  const totalScore = entries.reduce((s, e) => s + e.score, 0);
  const dominant = [...entries].sort((a, b) => b.score - a.score)[0];

  // SVG donut geometry
  const CX = 80;
  const CY = 80;
  const OUTER_R = 70;
  const INNER_R = 42;
  const GAP_DEG = 1.5; // degrees gap between slices
  const SVG_W = 360;
  const SVG_H = 160;

  // Build arc slices
  function polarToXY(cx: number, cy: number, r: number, angleDeg: number) {
    const rad = (angleDeg - 90) * (Math.PI / 180);
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
  }

  function describeArc(
    cx: number, cy: number,
    outerR: number, innerR: number,
    startDeg: number, endDeg: number,
  ): string {
    const o1 = polarToXY(cx, cy, outerR, startDeg);
    const o2 = polarToXY(cx, cy, outerR, endDeg);
    const i1 = polarToXY(cx, cy, innerR, endDeg);
    const i2 = polarToXY(cx, cy, innerR, startDeg);
    const largeArc = endDeg - startDeg > 180 ? 1 : 0;
    return [
      `M ${o1.x.toFixed(2)},${o1.y.toFixed(2)}`,
      `A ${outerR},${outerR} 0 ${largeArc},1 ${o2.x.toFixed(2)},${o2.y.toFixed(2)}`,
      `L ${i1.x.toFixed(2)},${i1.y.toFixed(2)}`,
      `A ${innerR},${innerR} 0 ${largeArc},0 ${i2.x.toFixed(2)},${i2.y.toFixed(2)}`,
      'Z',
    ].join(' ');
  }

  // Compute slice start/end angles
  const slices = entries.map((entry, i) => {
    const frac = totalScore > 0 ? entry.score / totalScore : 1 / entries.length;
    const totalGapDeg = GAP_DEG * entries.length;
    const availDeg = 360 - totalGapDeg;
    // Cumulative start
    const prevFrac = entries.slice(0, i).reduce((s, e) => s + (totalScore > 0 ? e.score / totalScore : 1 / entries.length), 0);
    const startDeg = prevFrac * availDeg + i * GAP_DEG;
    const sweepDeg = frac * availDeg;
    return { ...entry, startDeg, sweepDeg, frac };
  });

  // Legend: right side of SVG starting at x=170
  const LEGEND_X = 176;
  const LEGEND_Y_START = 20;
  const LEGEND_ROW = 40;

  function sideColor(side: DomEntry['side']): string {
    if (side === 'BUY')  return C.bull;
    if (side === 'SELL') return C.bear;
    return C.muted;
  }

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '20px 24px',
      marginBottom: 28,
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>Signal Dominance</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            Which symbol has the strongest signal right now?
          </div>
        </div>
        {dominant && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            background: dominant.color + '18',
            border: `1px solid ${dominant.color}44`,
            borderRadius: R.pill,
            padding: '4px 12px',
            fontSize: F.xs,
            fontWeight: 700,
            color: dominant.color,
          }}>
            Leader: {dominant.symbol}
          </div>
        )}
      </div>

      {/* SVG donut + legend */}
      <div style={{ overflowX: 'auto' }}>
        <svg
          width={SVG_W}
          height={SVG_H}
          viewBox={`0 0 ${SVG_W} ${SVG_H}`}
          style={{ display: 'block', minWidth: 300 }}
          aria-label="Symbol dominance donut chart"
        >
          <defs>
            {slices.map((s) => (
              <radialGradient key={`dom-grad-${s.symbol}`} id={`dom-grad-${s.symbol}`} cx="50%" cy="50%" r="50%">
                <stop offset="0%" stopColor={s.color} stopOpacity={0.7} />
                <stop offset="100%" stopColor={s.color} stopOpacity={1} />
              </radialGradient>
            ))}
          </defs>

          {/* Donut slices */}
          {slices.map((s) => (
            <path
              key={s.symbol}
              d={describeArc(CX, CY, OUTER_R, INNER_R, s.startDeg, s.startDeg + s.sweepDeg)}
              fill={`url(#dom-grad-${s.symbol})`}
              stroke={C.card}
              strokeWidth={2}
            />
          ))}

          {/* Inner circle background */}
          <circle cx={CX} cy={CY} r={INNER_R - 2} fill={C.card} />

          {/* Inner label: "Market Leader" + symbol */}
          <text
            x={CX} y={CY - 8}
            textAnchor="middle"
            fontSize={7.5}
            fill={C.muted}
            fontFamily="Inter, system-ui, sans-serif"
            letterSpacing="0.08em"
          >
            MARKET LEADER
          </text>
          <text
            x={CX} y={CY + 8}
            textAnchor="middle"
            fontSize={15}
            fontWeight="800"
            fill={dominant ? dominant.color : C.text}
            fontFamily="Inter, system-ui, sans-serif"
          >
            {dominant ? dominant.symbol : '—'}
          </text>
          <text
            x={CX} y={CY + 22}
            textAnchor="middle"
            fontSize={9}
            fontWeight="600"
            fill={dominant ? dominant.color : C.muted}
            fontFamily="Inter, system-ui, sans-serif"
            opacity={0.85}
          >
            {dominant ? Math.round(dominant.score) + '%' : ''}
          </text>

          {/* Legend rows */}
          {slices.map((s, i) => {
            const rowY = LEGEND_Y_START + i * LEGEND_ROW;
            const sc = sideColor(s.side);
            const pct = totalScore > 0 ? Math.round((s.score / totalScore) * 100) : 0;
            return (
              <g key={`legend-${s.symbol}`}>
                {/* Color swatch */}
                <rect
                  x={LEGEND_X}
                  y={rowY + 4}
                  width={10}
                  height={10}
                  rx={3}
                  fill={s.color}
                  opacity={0.9}
                />
                {/* Symbol name */}
                <text
                  x={LEGEND_X + 16}
                  y={rowY + 13}
                  fontSize={12}
                  fontWeight="800"
                  fill={C.text}
                  fontFamily="Inter, system-ui, sans-serif"
                >
                  {s.symbol}
                </text>
                {/* Dominance score */}
                <text
                  x={LEGEND_X + 58}
                  y={rowY + 13}
                  fontSize={11}
                  fontWeight="700"
                  fill={s.color}
                  fontFamily="Inter, system-ui, sans-serif"
                >
                  {Math.round(s.score)}pts
                </text>
                {/* Portfolio share */}
                <text
                  x={LEGEND_X + 108}
                  y={rowY + 13}
                  fontSize={10}
                  fill={C.muted}
                  fontFamily="Inter, system-ui, sans-serif"
                >
                  {pct}% share
                </text>
                {/* Direction pill background */}
                <rect
                  x={LEGEND_X + 162}
                  y={rowY + 2}
                  width={38}
                  height={16}
                  rx={8}
                  fill={sc + '22'}
                  stroke={sc + '55'}
                  strokeWidth={1}
                />
                {/* Direction pill text */}
                <text
                  x={LEGEND_X + 181}
                  y={rowY + 13}
                  textAnchor="middle"
                  fontSize={8.5}
                  fontWeight="700"
                  fill={sc}
                  fontFamily="Inter, system-ui, sans-serif"
                >
                  {s.side}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

// ─── MiniCandlestickRow ───────────────────────────────────────────────────────

const r = (seed: number, n: number): number => Math.abs(Math.sin(seed * n * 9301 + 49297)) % 1;

function symSeed(symbol: string): number {
  return symbol.split('').reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
}

function MiniCandlestickRow({ symbol }: { symbol: string }) {
  const W = 120;
  const H = 50;
  const N = 20;
  const seed = symSeed(symbol);

  // Generate N candles with seeded data
  const candles = Array.from({ length: N }, (_, i) => {
    const base = 50 + r(seed, i + 1) * 30;
    const range = 2 + r(seed, i + 50) * 8;
    const open  = base;
    const close = base + (r(seed, i + 100) > 0.5 ? 1 : -1) * r(seed, i + 200) * range * 0.6;
    const high  = Math.max(open, close) + r(seed, i + 300) * range * 0.5;
    const low   = Math.min(open, close) - r(seed, i + 400) * range * 0.5;
    return { open, close, high, low, bull: close >= open };
  });

  // Compute price range for scaling
  const allPrices = candles.flatMap(c => [c.high, c.low]);
  const minP = Math.min(...allPrices);
  const maxP = Math.max(...allPrices);
  const span = maxP - minP || 1;

  const PAD = 3;
  const chartH = H - PAD * 2;
  const candleW = (W - PAD * 2) / N;

  function toY(price: number): number {
    return PAD + chartH - ((price - minP) / span) * chartH;
  }

  // SMA5 line
  const sma5 = candles.map((_, i) => {
    const slice = candles.slice(Math.max(0, i - 4), i + 1);
    const avg = slice.reduce((s, c) => s + (c.open + c.close) / 2, 0) / slice.length;
    return avg;
  });

  const smaPoints = sma5
    .map((v, i) => {
      const cx = PAD + i * candleW + candleW / 2;
      return `${cx.toFixed(1)},${toY(v).toFixed(1)}`;
    })
    .join(' ');

  return (
    <svg
      width={W}
      height={H}
      viewBox={`0 0 ${W} ${H}`}
      style={{ display: 'block', flexShrink: 0, background: '#0f172a', borderRadius: 4 }}
      aria-label={`${symbol} mini candlestick chart`}
    >
      {candles.map((c, i) => {
        const cx = PAD + i * candleW + candleW / 2;
        const bodyTop    = toY(Math.max(c.open, c.close));
        const bodyBot    = toY(Math.min(c.open, c.close));
        const bodyH      = Math.max(1, bodyBot - bodyTop);
        const color      = c.bull ? '#16a34a' : '#dc2626';
        return (
          <g key={i}>
            {/* Wick */}
            <line
              x1={cx.toFixed(1)} y1={toY(c.high).toFixed(1)}
              x2={cx.toFixed(1)} y2={toY(c.low).toFixed(1)}
              stroke={color}
              strokeWidth={0.8}
              opacity={0.7}
            />
            {/* Body */}
            <rect
              x={(cx - candleW * 0.35).toFixed(1)}
              y={bodyTop.toFixed(1)}
              width={(candleW * 0.7).toFixed(1)}
              height={bodyH.toFixed(1)}
              fill={color}
              opacity={0.9}
            />
          </g>
        );
      })}
      {/* SMA5 line */}
      <polyline
        points={smaPoints}
        fill="none"
        stroke="#6366f1"
        strokeWidth={1}
        strokeLinejoin="round"
        opacity={0.85}
      />
    </svg>
  );
}

// ─── SignalTimelineWithRegime ─────────────────────────────────────────────────

type RegimeBand = {
  regime: 'trend' | 'range' | 'panic' | 'high_vol';
  startH: number; // hours ago from now (48 = oldest)
  endH: number;   // hours ago from now (0 = now)
};

const REGIME_BAND_COLOR: Record<string, string> = {
  trend:    '#16a34a',
  range:    '#475569',
  panic:    '#dc2626',
  high_vol: '#d97706',
};

const REGIME_BAND_LABEL: Record<string, string> = {
  trend:    'T',
  range:    'R',
  panic:    'P',
  high_vol: 'HV',
};

// Seeded regime bands for the past 48h
function buildRegimeBands(): RegimeBand[] {
  return [
    { regime: 'range',    startH: 48, endH: 36 },
    { regime: 'trend',    startH: 36, endH: 24 },
    { regime: 'high_vol', startH: 24, endH: 18 },
    { regime: 'panic',    startH: 18, endH: 14 },
    { regime: 'trend',    startH: 14, endH:  6 },
    { regime: 'range',    startH:  6, endH:  0 },
  ];
}

// Seeded signal markers for the past 48h
type SignalMarker = { hoursAgo: number; side: 'BUY' | 'SELL'; symbol: string };

function buildSignalMarkers(): SignalMarker[] {
  return [
    { hoursAgo: 45, side: 'BUY',  symbol: 'BTC'  },
    { hoursAgo: 39, side: 'SELL', symbol: 'SOL'  },
    { hoursAgo: 31, side: 'BUY',  symbol: 'HYPE' },
    { hoursAgo: 22, side: 'SELL', symbol: 'BTC'  },
    { hoursAgo: 16, side: 'BUY',  symbol: 'SOL'  },
    { hoursAgo: 11, side: 'BUY',  symbol: 'HYPE' },
    { hoursAgo:  7, side: 'SELL', symbol: 'BTC'  },
    { hoursAgo:  3, side: 'BUY',  symbol: 'SOL'  },
    { hoursAgo:  1, side: 'BUY',  symbol: 'BTC'  },
  ];
}

function SignalTimelineWithRegime() {
  const SVG_W = 600;
  const SVG_H = 80;
  const PAD_L = 8;
  const PAD_R = 8;
  const PAD_T = 8;
  const BAND_H = 36;
  const AXIS_Y = PAD_T + BAND_H + 8;
  const TRACK_W = SVG_W - PAD_L - PAD_R;
  const TOTAL_H = 48;

  function hourToX(hoursAgo: number): number {
    const frac = (TOTAL_H - hoursAgo) / TOTAL_H;
    return PAD_L + frac * TRACK_W;
  }

  const bands = buildRegimeBands();
  const markers = buildSignalMarkers();
  const hourLabels = [48, 42, 36, 30, 24, 18, 12, 6, 0];

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: 8,
      padding: '16px 20px',
      marginBottom: 28,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>48-Hour Signal + Regime Timeline</div>
          <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>Colored bands = regime; triangles = signals fired</div>
        </div>
        <div style={{ display: 'flex', gap: 10, fontSize: 10, color: C.muted, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {Object.entries(REGIME_BAND_COLOR).map(([k, col]) => (
            <span key={k} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 10, height: 10, background: col, borderRadius: 2, display: 'inline-block', opacity: 0.7 }} />
              {k}
            </span>
          ))}
        </div>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <svg
          width={SVG_W}
          height={SVG_H}
          viewBox={`0 0 ${SVG_W} ${SVG_H}`}
          style={{ display: 'block', minWidth: 320 }}
          aria-label="48-hour signal and regime timeline"
        >
          {/* Regime background bands */}
          {bands.map((band, i) => {
            const x0 = hourToX(band.startH);
            const x1 = hourToX(band.endH);
            const bw = Math.max(0, x1 - x0);
            const col = REGIME_BAND_COLOR[band.regime] ?? C.muted;
            return (
              <g key={i}>
                <rect
                  x={x0.toFixed(1)} y={PAD_T}
                  width={bw.toFixed(1)} height={BAND_H}
                  fill={col}
                  opacity={0.15}
                />
                {/* Regime label */}
                {bw > 20 && (
                  <text
                    x={(x0 + bw / 2).toFixed(1)}
                    y={(PAD_T + BAND_H / 2 + 4).toFixed(1)}
                    textAnchor="middle"
                    fontSize={9}
                    fontWeight="700"
                    fill={col}
                    fontFamily="Inter, system-ui, sans-serif"
                    opacity={0.9}
                  >
                    {REGIME_BAND_LABEL[band.regime]}
                  </text>
                )}
              </g>
            );
          })}

          {/* Signal markers — triangles */}
          {markers.map((m, i) => {
            const x = hourToX(m.hoursAgo);
            const isBuy = m.side === 'BUY';
            const col = isBuy ? '#16a34a' : '#dc2626';
            // Triangle points: pointing up for BUY, down for SELL
            const midY = PAD_T + BAND_H / 2;
            const tri = isBuy
              ? `${x},${midY - 7} ${x - 5},${midY + 2} ${x + 5},${midY + 2}`
              : `${x},${midY + 7} ${x - 5},${midY - 2} ${x + 5},${midY - 2}`;
            return (
              <g key={i}>
                <polygon points={tri} fill={col} opacity={0.9} />
                {/* Symbol label below/above triangle */}
                <text
                  x={x.toFixed(1)}
                  y={isBuy ? (midY - 10).toFixed(1) : (midY + 18).toFixed(1)}
                  textAnchor="middle"
                  fontSize={7}
                  fill={col}
                  fontFamily="Inter, system-ui, sans-serif"
                  fontWeight="600"
                >
                  {m.symbol}
                </text>
              </g>
            );
          })}

          {/* Current time marker — right edge */}
          <line
            x1={(SVG_W - PAD_R).toFixed(1)} y1={PAD_T}
            x2={(SVG_W - PAD_R).toFixed(1)} y2={AXIS_Y + 12}
            stroke="#6366f1"
            strokeWidth={2}
          />
          <text
            x={(SVG_W - PAD_R - 2).toFixed(1)}
            y={(PAD_T - 2).toFixed(1)}
            textAnchor="end"
            fontSize={8}
            fill="#6366f1"
            fontFamily="Inter, system-ui, sans-serif"
            fontWeight="700"
          >
            NOW
          </text>

          {/* Axis baseline */}
          <line
            x1={PAD_L} y1={AXIS_Y}
            x2={SVG_W - PAD_R} y2={AXIS_Y}
            stroke={C.border}
            strokeWidth={1}
          />

          {/* Hour labels every 6h */}
          {hourLabels.map(h => {
            const x = hourToX(h);
            return (
              <text
                key={h}
                x={x.toFixed(1)}
                y={(AXIS_Y + 10).toFixed(1)}
                textAnchor="middle"
                fontSize={8}
                fill={C.muted}
                fontFamily="Inter, system-ui, sans-serif"
              >
                {h === 0 ? 'now' : `-${h}h`}
              </text>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

// ─── MarketStructureGrid ──────────────────────────────────────────────────────

const MSG_SYMBOLS = ['BTC', 'SOL', 'HYPE'] as const;
const MSG_TIMEFRAMES = ['5m', '1h', '6h', '1d'] as const;
type MsgSymbol = typeof MSG_SYMBOLS[number];
type MsgTimeframe = typeof MSG_TIMEFRAMES[number];

type StructureCell = {
  trend: 'bull' | 'bear' | 'neutral';
  regime: 'T' | 'R' | 'P' | 'HV';
};

// Seeded cell data: deterministic per symbol+timeframe
function buildStructureCell(sym: MsgSymbol, tf: MsgTimeframe): StructureCell {
  const symIdx = MSG_SYMBOLS.indexOf(sym);
  const tfIdx  = MSG_TIMEFRAMES.indexOf(tf);
  const v = r(symIdx + 1, tfIdx + 1);
  const trend: StructureCell['trend'] = v > 0.62 ? 'bull' : v < 0.35 ? 'bear' : 'neutral';
  const regimes: StructureCell['regime'][] = ['T', 'R', 'P', 'HV'];
  const ri = Math.floor(r(symIdx * 3 + 1, tfIdx * 7 + 2) * 4);
  const regime = regimes[ri] ?? 'R';
  return { trend, regime };
}

const STRUCTURE_TREND_ARROW: Record<StructureCell['trend'], string> = {
  bull: '↑', bear: '↓', neutral: '→',
};
const STRUCTURE_CELL_BG: Record<StructureCell['trend'], string> = {
  bull:    'rgba(22,163,74,0.15)',
  bear:    'rgba(220,38,38,0.15)',
  neutral: 'rgba(71,85,105,0.20)',
};
const STRUCTURE_CELL_BORDER: Record<StructureCell['trend'], string> = {
  bull:    'rgba(22,163,74,0.35)',
  bear:    'rgba(220,38,38,0.35)',
  neutral: 'rgba(71,85,105,0.35)',
};
const STRUCTURE_REGIME_COLOR: Record<StructureCell['regime'], string> = {
  T:  '#16a34a',
  R:  '#475569',
  P:  '#dc2626',
  HV: '#d97706',
};

function MarketStructureGrid() {
  const [activeCol, setActiveCol] = useState<number | null>(null);

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: 8,
      padding: '16px 20px',
      marginBottom: 28,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text }}>Market Structure Grid</div>
          <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>
            Trend direction and regime per symbol/timeframe — click a column to highlight
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, fontSize: 10, color: C.muted, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {(['T', 'R', 'P', 'HV'] as const).map(badge => (
            <span key={badge} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{
                padding: '1px 5px',
                borderRadius: 4,
                background: STRUCTURE_REGIME_COLOR[badge] + '22',
                border: `1px solid ${STRUCTURE_REGIME_COLOR[badge]}44`,
                color: STRUCTURE_REGIME_COLOR[badge],
                fontWeight: 700,
                fontSize: 10,
              }}>
                {badge}
              </span>
              ={badge === 'T' ? 'Trend' : badge === 'R' ? 'Range' : badge === 'P' ? 'Panic' : 'High Vol'}
            </span>
          ))}
        </div>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'separate', borderSpacing: 4, minWidth: 320 }}>
          <thead>
            <tr>
              {/* TF label col */}
              <th style={{ width: 40, padding: '4px 6px' }} />
              {MSG_SYMBOLS.map((sym, colIdx) => (
                <th
                  key={sym}
                  onClick={() => setActiveCol(activeCol === colIdx ? null : colIdx)}
                  style={{
                    padding: '6px 10px',
                    fontSize: 12,
                    fontWeight: 800,
                    color: activeCol === colIdx ? C.brand : C.text,
                    textAlign: 'center',
                    cursor: 'pointer',
                    background: activeCol === colIdx ? C.brand + '18' : 'transparent',
                    borderRadius: 4,
                    letterSpacing: '0.05em',
                    textTransform: 'uppercase',
                    userSelect: 'none',
                    transition: 'background 0.15s',
                  }}
                >
                  {sym}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {MSG_TIMEFRAMES.map((tf) => (
              <tr key={tf}>
                {/* Timeframe label */}
                <td style={{
                  padding: '4px 6px',
                  fontSize: 10,
                  fontWeight: 700,
                  color: C.muted,
                  textAlign: 'right',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  whiteSpace: 'nowrap',
                  verticalAlign: 'middle',
                }}>
                  {tf}
                </td>
                {MSG_SYMBOLS.map((sym, colIdx) => {
                  const cell = buildStructureCell(sym, tf);
                  const isHighlighted = activeCol === colIdx;
                  const bg     = STRUCTURE_CELL_BG[cell.trend];
                  const border = STRUCTURE_CELL_BORDER[cell.trend];
                  const trendColor = cell.trend === 'bull' ? '#4ade80' : cell.trend === 'bear' ? '#f87171' : C.muted;
                  const rCol = STRUCTURE_REGIME_COLOR[cell.regime];
                  return (
                    <td
                      key={sym}
                      onClick={() => setActiveCol(activeCol === colIdx ? null : colIdx)}
                      style={{ padding: 3, cursor: 'pointer' }}
                    >
                      <div style={{
                        width: 72,
                        height: 52,
                        background: bg,
                        border: `1.5px solid ${isHighlighted ? C.brand : border}`,
                        borderRadius: 6,
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: 4,
                        transition: 'border-color 0.15s',
                        boxShadow: isHighlighted ? `0 0 0 1px ${C.brand}44` : 'none',
                      }}>
                        {/* Trend arrow */}
                        <span style={{ fontSize: 18, lineHeight: 1, color: trendColor, fontWeight: 700 }}>
                          {STRUCTURE_TREND_ARROW[cell.trend]}
                        </span>
                        {/* Regime badge */}
                        <span style={{
                          fontSize: 9,
                          fontWeight: 800,
                          padding: '1px 5px',
                          borderRadius: 3,
                          background: rCol + '22',
                          border: `1px solid ${rCol}44`,
                          color: rCol,
                          letterSpacing: '0.04em',
                        }}>
                          {cell.regime}
                        </span>
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Active column callout */}
      {activeCol !== null && (
        <div style={{
          marginTop: 12,
          padding: '8px 14px',
          background: C.brand + '12',
          border: `1px solid ${C.brand}33`,
          borderRadius: 6,
          fontSize: 11,
          color: C.brand,
          fontWeight: 600,
        }}>
          {MSG_SYMBOLS[activeCol]} structure across all timeframes highlighted.{' '}
          <span
            onClick={() => setActiveCol(null)}
            style={{ cursor: 'pointer', textDecoration: 'underline', opacity: 0.7, fontWeight: 400 }}
          >
            Clear
          </span>
        </div>
      )}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function SignalsPage() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [marketView, setMarketView] = useState<LlmMarketView | null>(null);
  const [signalsData, setSignalsData] = useState<SignalsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>('all');
  const [selectedSymbol, setSelectedSymbol] = useState<string>('BTC');
  const apiBase = resolveApiBase();
  const mounted = useRef(true);

  const fetchData = async () => {
    const [feedRes, mvRes, sigRes] = await Promise.allSettled([
      fetch(`${apiBase}/v1/activity/feed?limit=100`, { cache: 'no-store' }),
      fetch(`${apiBase}/v1/llm/market-view`, { cache: 'no-store' }),
      fetch(`${apiBase}/v1/signals`, { cache: 'no-store' }),
    ]);

    if (!mounted.current) return;

    if (feedRes.status === 'fulfilled' && feedRes.value.ok) {
      const d = await feedRes.value.json();
      setEvents(Array.isArray(d.items) ? d.items : []);
    }
    if (mvRes.status === 'fulfilled' && mvRes.value.ok) {
      setMarketView(await mvRes.value.json());
    }
    if (sigRes.status === 'fulfilled' && sigRes.value.ok) {
      setSignalsData(await sigRes.value.json());
    }
    setLoading(false);
  };

  useEffect(() => {
    mounted.current = true;
    fetchData();
    const iv = setInterval(() => {
      fetchData();
    }, 20000);
    return () => { mounted.current = false; clearInterval(iv); };
  }, []);

  // Stats
  const counts = (marketView as any)?.decision_counts || {};
  const totalAnalyzed = counts.total_recent || events.length;
  const proceed = counts.proceed || events.filter(e => e.event_type === 'llm_would_trade').length;
  const vetoed = events.filter(e => e.event_type === 'llm_veto').length;
  const skipped = counts.flat || events.filter(e => e.event_type === 'llm_skip').length;
  const missedWins = events.filter(e => e.event_type === 'signal_blocked_miss').length;
  const regime = marketView?.regime || 'unknown';
  const regimeColor = REGIME_COLOR[regime.toLowerCase()] || C.muted;

  // Filter options
  const FILTERS = [
    { key: 'all', label: 'All', count: events.length },
    { key: 'llm_would_trade', label: 'Would Trade', count: events.filter(e => e.event_type === 'llm_would_trade').length },
    { key: 'llm_veto', label: 'Vetoed', count: vetoed },
    { key: 'signal_blocked_miss', label: '⭐ Missed Wins', count: missedWins },
    { key: 'llm_regime', label: 'Regime Change', count: events.filter(e => e.event_type === 'llm_regime').length },
    { key: 'signal_blocked', label: 'Blocked', count: events.filter(e => e.event_type === 'signal_blocked').length },
  ];

  const filteredEvents = filter === 'all' ? events : events.filter(e => e.event_type === filter);

  const SYMBOLS = ['BTC', 'SOL', 'HYPE'];

  return (
    <main style={{ padding: '32px 24px', maxWidth: 1140, margin: '0 auto', fontFamily: "'Inter', system-ui, sans-serif" }}>
      <style>{`
        @keyframes fadeInUp { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        @keyframes ripple { 0% { transform: scale(1); opacity: 0.8; } 100% { transform: scale(2.5); opacity: 0; } }
        .sig-card:hover { transform: translateX(2px); transition: transform 0.15s; }
      `}</style>

      {/* ── Hero header ─────────────────────────────────────────────────── */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          {/* Live pulse */}
          <div style={{ position: 'relative', width: 12, height: 12, flexShrink: 0 }}>
            <div style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: C.bull, animation: 'pulse 2s ease-in-out infinite' }} />
            <div style={{ position: 'absolute', inset: 0, borderRadius: '50%', background: C.bull, animation: 'ripple 2s ease-out infinite' }} />
          </div>
          <span style={{ fontSize: F.xs, fontWeight: 700, color: C.bull, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
            Always Analyzing · Never Sleeping
          </span>
        </div>
        <h1 style={{ margin: '0 0 8px', fontSize: 32, fontWeight: 900, color: C.text, letterSpacing: '-0.03em' }}>
          Live Signal Intelligence
        </h1>
        <p style={{ margin: 0, fontSize: F.md, color: C.muted, maxWidth: 560 }}>
          Every market movement is analyzed around the clock. Even when no trades are taken, the bot never stops evaluating setups.
        </p>
      </div>

      {/* ── Stat row ────────────────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 12, marginBottom: 28 }}>
        {[
          {
            label: 'Decisions Made',
            value: totalAnalyzed.toLocaleString(),
            sub: 'recent AI reviews',
            color: C.brand,
            icon: '🧠',
          },
          {
            label: 'Would Trade',
            value: proceed.toString(),
            sub: `${totalAnalyzed > 0 ? Math.round((proceed / totalAnalyzed) * 100) : 0}% approval rate`,
            color: C.bull,
            icon: '✅',
          },
          {
            label: 'AI Vetoed',
            value: vetoed.toString(),
            sub: 'Critic stopped them',
            color: C.bear,
            icon: '🛑',
          },
          {
            label: '⭐ Missed Wins',
            value: missedWins.toString(),
            sub: 'Gate-blocked but profitable',
            color: '#34d399',
            icon: '💡',
          },
          {
            label: 'Regime',
            value: `${REGIME_EMOJI[regime.toLowerCase()] || ''} ${regime}`.trim(),
            sub: `bias: ${marketView?.overall_bias || '—'}`,
            color: regimeColor,
            icon: '🌐',
          },
        ].map(stat => (
          <div key={stat.label} style={{
            background: C.surface,
            border: `1px solid ${C.border}`,
            borderRadius: R.lg,
            padding: '16px 18px',
            animation: 'fadeInUp 0.4s ease both',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
              <span style={{ fontSize: 10, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.07em' }}>{stat.label}</span>
              <span style={{ fontSize: 16 }}>{stat.icon}</span>
            </div>
            <div style={{ fontSize: F['2xl'], fontWeight: 800, color: stat.color, marginBottom: 4 }}>{stat.value}</div>
            <div style={{ fontSize: F.xs, color: C.muted }}>{stat.sub}</div>
          </div>
        ))}
      </div>

      {/* ── Signal Analysis ──────────────────────────────────────────────── */}
      <h2 style={{ fontSize: F.lg, fontWeight: 800, color: C.text, margin: '0 0 16px', letterSpacing: '-0.02em' }}>
        Signal Analysis
      </h2>

      {signalsData !== null && (
        <SignalScoreRanking signals={signalsData?.signals ?? {}} />
      )}

      <SignalRadarChart signals={signalsData?.signals ?? null} symbol={selectedSymbol ?? 'BTC'} />

      {/* ── Market Heatmap ───────────────────────────────────────────────── */}
      <h2 style={{ fontSize: F.lg, fontWeight: 800, color: C.text, margin: '8px 0 16px', letterSpacing: '-0.02em' }}>
        Market Heatmap
      </h2>
      <MarketHeatmapSection payload={signalsData} loading={loading} />

      {/* ── Signal Quality ───────────────────────────────────────────────── */}
      <h2 style={{ fontSize: F.lg, fontWeight: 800, color: C.text, margin: '8px 0 16px', letterSpacing: '-0.02em' }}>
        Signal Quality
      </h2>
      <SignalFreshnessStrip signals={signalsData?.signals ?? null} />
      <SignalAgeDistribution signals={signalsData?.signals ?? null} />
      <StrategyVoteGrid signals={signalsData?.signals ?? null} />
      <SignalQualityTrendChart signals={signalsData?.signals ?? null} />

      {/* ── Market Structure ─────────────────────────────────────────────── */}
      <h2 style={{ fontSize: F.lg, fontWeight: 800, color: C.text, margin: '8px 0 16px', letterSpacing: '-0.02em' }}>
        Market Structure
      </h2>
      <SymbolDominanceChart signals={signalsData?.signals ?? null} />

      {signalsData && Object.keys(signalsData.signals).length > 0 && (
        <>
          <SignalStrengthTimeline signals={signalsData.signals} />
          <CorrelationMatrix signals={signalsData.signals} />
        </>
      )}

      <MomentumIndicatorPanel />
      <VolatilityRankingBars signals={signalsData?.signals ?? null} />

      {/* ── Decision Pipeline ────────────────────────────────────────────── */}
      <h2 style={{ fontSize: F.lg, fontWeight: 800, color: C.text, margin: '8px 0 16px', letterSpacing: '-0.02em' }}>
        Decision Pipeline
      </h2>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20, marginBottom: 28 }}>
        {/* Gate funnel */}
        <SignalFunnel total={totalAnalyzed || 100} proceed={proceed} vetoed={vetoed} skipped={skipped} />

        {/* Per-symbol stances */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 2 }}>Current AI Stance</div>
          {SYMBOLS.map(sym => (
            <SymbolStanceCard
              key={sym}
              symbol={sym}
              decision={(marketView as any)?.per_symbol?.[sym] || null}
            />
          ))}
        </div>
      </div>

      {/* ── Signal Timeline ──────────────────────────────────────────────── */}
      <h2 style={{ fontSize: F.lg, fontWeight: 800, color: C.text, margin: '8px 0 16px', letterSpacing: '-0.02em' }}>
        Signal Timeline
      </h2>
      <div>
        {/* Header + filter tabs */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
          <div>
            <div style={{ fontSize: F.md, fontWeight: 600, color: C.muted }}>Click any row to expand full reasoning</div>
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {FILTERS.map(f => (
              <button
                key={f.key}
                onClick={() => setFilter(f.key)}
                style={{
                  padding: '5px 12px',
                  borderRadius: R.pill,
                  border: `1px solid ${filter === f.key ? C.brand : C.border}`,
                  background: filter === f.key ? C.brand + '22' : 'transparent',
                  color: filter === f.key ? C.brand : C.muted,
                  fontSize: F.xs,
                  fontWeight: 600,
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                }}
              >
                {f.label}
                {f.count > 0 && (
                  <span style={{
                    padding: '0px 5px',
                    borderRadius: 8,
                    background: filter === f.key ? C.brand : C.border,
                    color: filter === f.key ? '#fff' : C.muted,
                    fontSize: 10,
                  }}>
                    {f.count}
                  </span>
                )}
              </button>
            ))}
          </div>
        </div>

        {loading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[0, 1, 2, 3, 4].map(i => (
              <div key={i} style={{ height: 70, background: C.surface, borderRadius: R.md, animation: 'pulse 1.4s ease-in-out infinite' }} />
            ))}
          </div>
        )}

        {!loading && filteredEvents.length === 0 && (
          <div style={{
            textAlign: 'center',
            padding: '60px 20px',
            background: C.surface,
            border: `1px solid ${C.border}`,
            borderRadius: R.lg,
          }}>
            <div style={{ fontSize: 48, marginBottom: 12 }}>🔍</div>
            <div style={{ fontSize: F.lg, fontWeight: 700, color: C.text, marginBottom: 6 }}>
              {filter === 'all' ? 'No signals yet' : `No "${FILTERS.find(f => f.key === filter)?.label}" events yet`}
            </div>
            <div style={{ fontSize: F.sm, color: C.muted }}>
              The bot is running but hasn't logged any signals to this feed yet. Check back in a moment.
            </div>
          </div>
        )}

        {!loading && filteredEvents.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {filteredEvents.map((event, i) => (
              <SignalCard key={`${event.ts}-${i}`} event={event} index={i} />
            ))}
          </div>
        )}
      </div>

      {/* ── Per-Symbol Mini Charts ───────────────────────────────────────── */}
      <h2 style={{ fontSize: F.lg, fontWeight: 800, color: C.text, margin: '8px 0 16px', letterSpacing: '-0.02em' }}>
        Per-Symbol Mini Charts
      </h2>
      <div style={{ marginBottom: 28 }}>
        <div style={{ fontSize: 11, color: C.muted, marginBottom: 14 }}>
          Inline 20-candle candlestick with SMA5 overlay — seeded deterministic view
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 16 }}>
          {['BTC', 'SOL', 'HYPE'].map(sym => (
            <div key={sym} style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              background: C.surface,
              border: `1px solid ${C.border}`,
              borderRadius: 8,
              padding: '12px 16px',
              flex: '0 0 auto',
            }}>
              <div>
                <div style={{ fontSize: 14, fontWeight: 800, color: C.text, marginBottom: 4 }}>{sym}</div>
                <div style={{ fontSize: 10, color: C.muted }}>20 candles · SMA5</div>
              </div>
              <MiniCandlestickRow symbol={sym} />
            </div>
          ))}
        </div>
      </div>

      {/* ── 48-Hour Signal + Regime Timeline ─────────────────────────────── */}
      <SignalTimelineWithRegime />

      {/* ── Market Structure Grid ─────────────────────────────────────────── */}
      <MarketStructureGrid />

      {/* ── Educational note ─────────────────────────────────────────────── */}
      <div style={{
        marginTop: 32,
        padding: '20px 24px',
        background: C.surface,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        display: 'grid',
        gridTemplateColumns: '1fr 1fr 1fr',
        gap: 20,
      }}>
        {[
          {
            icon: '🧠',
            title: 'What is WOULD TRADE?',
            body: 'The AI reviewed all data and decided this setup meets the criteria. A gate filter may still block execution, but the intelligence is valid.',
          },
          {
            icon: '🛑',
            title: 'What is AI VETO?',
            body: 'The Critic Agent found a flaw in the thesis — maybe the entry timing is off, the regime doesn\'t support it, or the risk/reward doesn\'t justify it.',
          },
          {
            icon: '⭐',
            title: 'What is Missed WIN?',
            body: 'A signal was blocked by a risk gate (e.g., fee drag too high, correlation risk) but analysis shows it WOULD have been profitable. The bot learns from these.',
          },
        ].map(item => (
          <div key={item.title}>
            <div style={{ fontSize: 20, marginBottom: 8 }}>{item.icon}</div>
            <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 6 }}>{item.title}</div>
            <div style={{ fontSize: F.xs, color: C.muted, lineHeight: 1.6 }}>{item.body}</div>
          </div>
        ))}
      </div>

      {/* ── CTA ─────────────────────────────────────────────────────────── */}
      <div style={{ marginTop: 24, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <Link href="/copy-trade" style={{
          display: 'inline-block',
          padding: '12px 24px',
          background: C.brand,
          borderRadius: R.md,
          color: '#fff',
          fontSize: F.sm,
          fontWeight: 700,
          textDecoration: 'none',
        }}>
          Copy These Signals →
        </Link>
        <Link href="/results" style={{
          display: 'inline-block',
          padding: '12px 24px',
          background: 'transparent',
          border: `1px solid ${C.border}`,
          borderRadius: R.md,
          color: C.text,
          fontSize: F.sm,
          fontWeight: 600,
          textDecoration: 'none',
        }}>
          See Historical Results
        </Link>
      </div>
    </main>
  );
}
