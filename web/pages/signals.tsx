import React, { useEffect, useState, useRef } from 'react';
import Link from 'next/link';
import { C, R, S, F, fmtUsd, timeAgo } from '../src/theme';
import type { ActivityEvent, LlmMarketView } from '../src/types';

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

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function SignalsPage() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [marketView, setMarketView] = useState<LlmMarketView | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>('all');
  const [pulseCount, setPulseCount] = useState(0);
  const apiBase = resolveApiBase();
  const mounted = useRef(true);

  const fetchData = async () => {
    const [feedRes, mvRes] = await Promise.allSettled([
      fetch(`${apiBase}/v1/activity/feed?limit=100`, { cache: 'no-store' }),
      fetch(`${apiBase}/v1/llm/market-view`, { cache: 'no-store' }),
    ]);

    if (!mounted.current) return;

    if (feedRes.status === 'fulfilled' && feedRes.value.ok) {
      const d = await feedRes.value.json();
      setEvents(Array.isArray(d.items) ? d.items : []);
    }
    if (mvRes.status === 'fulfilled' && mvRes.value.ok) {
      setMarketView(await mvRes.value.json());
    }
    setLoading(false);
  };

  useEffect(() => {
    mounted.current = true;
    fetchData();
    const iv = setInterval(() => {
      fetchData();
      setPulseCount(c => c + 1);
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

      {/* ── Two-column layout ────────────────────────────────────────────── */}
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
      <div>
        {/* Header + filter tabs */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
          <div>
            <div style={{ fontSize: F.lg, fontWeight: 800, color: C.text }}>Signal Timeline</div>
            <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>Click any row to expand full reasoning</div>
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
