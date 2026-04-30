'use client';

/**
 * /trade — HL-style 3-column trade page.
 * Phase 3 of the HL reshape (audits/2026-04-29/05_ui_reshape_hyperliquid_style.md).
 *
 * Layout:
 *   ┌─ Calibration strip (§7.3) ─────────────────────────────────┐
 *   ├─────────────┬──────────────────────────────┬──────────────┤
 *   │ Left rail   │ Chart + tabs                 │ Right rail   │
 *   │ Market list │ (Positions/Orders/Bot Signal)│ Order entry  │
 *   │ + search    │                              │ + Bot Op slot│
 *   │             │                              │   (§7.1)     │
 *   └─────────────┴──────────────────────────────┴──────────────┘
 *
 * Data sources (existing endpoints in bot/api_server.py):
 *   /v1/signals          — current bot opinions per symbol
 *   /v1/ohlcv?symbol=    — chart candles
 *   /v1/positions        — open positions
 *   /v1/llm/market-view  — current LLM regime call
 *   /v1/agents/team/calibration — calibration data for §7.3 strip
 *
 * This page is intentionally read-only for Phase 3. Order entry is a visual
 * placeholder until the bot/exchange wiring is decided. Existing /signals page
 * remains live; the Trade nav tab points to /signals until this page reaches
 * parity (then we flip the activeMatch routing).
 */

import React, { useState, useEffect, useMemo } from 'react';
import Head from 'next/head';
import { C, F, R } from '../src/theme';
import { resolveApiBase } from '../src/api';

const SYMBOLS = ['BTC', 'ETH', 'SOL', 'HYPE'];

type SignalSnap = {
  symbol: string;
  side?: string | null;
  price?: number | null;
  confidence?: number | null;
  action?: string | null;
  regime?: string | null;
  reasoning?: string | null;
};

type SignalsApi = {
  signals?: Record<string, SignalSnap | undefined>;
  last_updated?: string | null;
};

type Position = {
  symbol: string;
  side: string;
  entry: number;
  qty: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  state?: string;
};

export default function TradePage() {
  const [selectedSymbol, setSelectedSymbol] = useState<string>('BTC');
  const [signals, setSignals] = useState<SignalsApi | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [marketView, setMarketView] = useState<{ regime?: string; confidence?: number } | null>(
    null,
  );
  const [activeTab, setActiveTab] = useState<'positions' | 'orders' | 'bot'>('bot');

  // Fetch on mount + every 15s.
  useEffect(() => {
    let cancelled = false;
    const apiBase = resolveApiBase();

    const load = async () => {
      try {
        const [sigRes, posRes, mvRes] = await Promise.all([
          fetch(`${apiBase}/v1/signals`, { cache: 'no-store' }),
          fetch(`${apiBase}/v1/positions`, { cache: 'no-store' }),
          fetch(`${apiBase}/v1/llm/market-view`, { cache: 'no-store' }),
        ]);
        if (cancelled) return;
        if (sigRes.ok) setSignals(await sigRes.json());
        if (posRes.ok) {
          const j = await posRes.json();
          setPositions(j.positions || []);
        }
        if (mvRes.ok) setMarketView(await mvRes.json());
      } catch {
        // silent — UI shows empty/stale state
      }
    };

    load();
    const id = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const currentSignal = useMemo(
    () => signals?.signals?.[selectedSymbol],
    [signals, selectedSymbol],
  );
  const currentPosition = useMemo(
    () => positions.find((p) => p.symbol === selectedSymbol),
    [positions, selectedSymbol],
  );

  return (
    <>
      <Head>
        <title>Trade — WAGMI</title>
      </Head>

      {/* ── §7.3 Calibration strip ──────────────────────────────────── */}
      <CalibrationStrip marketView={marketView} />

      {/* ── 3-column main grid ──────────────────────────────────────── */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '240px 1fr 320px',
          gap: 12,
          marginTop: 12,
          minHeight: 600,
        }}
      >
        <MarketRail
          signals={signals}
          selected={selectedSymbol}
          onSelect={setSelectedSymbol}
        />
        <ChartCenter
          symbol={selectedSymbol}
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          positions={positions}
          currentSignal={currentSignal}
        />
        <OrderRail
          symbol={selectedSymbol}
          currentSignal={currentSignal}
          currentPosition={currentPosition}
        />
      </div>
    </>
  );
}

// ── Calibration strip (§7.3) ────────────────────────────────────────────────

function CalibrationStrip({
  marketView,
}: {
  marketView: { regime?: string; confidence?: number } | null;
}) {
  const regime = marketView?.regime || 'unknown';
  const conf = marketView?.confidence;
  const confPct = conf != null ? Math.round((conf > 1 ? conf : conf * 100)) : null;
  const tone =
    regime === 'trending'
      ? C.bull
      : regime === 'ranging' || regime === 'illiquid'
      ? C.warn
      : regime === 'panic'
      ? C.bear
      : C.muted;

  return (
    <div
      style={{
        height: 28,
        background: '#0a0a0f',
        border: `1px solid ${C.border}`,
        borderRadius: R.sm,
        padding: '0 12px',
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        fontSize: F.xs,
        color: C.textSub,
        fontFamily: 'JetBrains Mono, monospace',
      }}
    >
      <span>
        regime:{' '}
        <span style={{ color: tone, fontWeight: 600 }}>{regime.toUpperCase()}</span>
        {confPct != null && <span style={{ marginLeft: 6, color: C.muted }}>({confPct}%)</span>}
      </span>
      <span style={{ color: C.faint }}>·</span>
      <span>
        <span style={{ color: C.muted }}>trade agent:</span>{' '}
        <span style={{ color: C.text }}>—</span>{' '}
        <span style={{ color: C.muted }}>regime agent:</span>{' '}
        <span style={{ color: C.text }}>—</span>
      </span>
      <span style={{ color: C.faint }}>·</span>
      <span style={{ color: C.muted }}>
        <em>(calibration history wires in Phase 5)</em>
      </span>
    </div>
  );
}

// ── Market rail (left column) ───────────────────────────────────────────────

function MarketRail({
  signals,
  selected,
  onSelect,
}: {
  signals: SignalsApi | null;
  selected: string;
  onSelect: (s: string) => void;
}) {
  return (
    <aside
      style={{
        background: '#0a0a0f',
        border: `1px solid ${C.border}`,
        borderRadius: R.sm,
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <div
        style={{
          padding: '8px 10px',
          borderBottom: `1px solid ${C.border}`,
          fontSize: F.xs,
          color: C.muted,
          textTransform: 'uppercase',
          letterSpacing: 0.05,
          fontWeight: 600,
        }}
      >
        Markets
      </div>
      {SYMBOLS.map((sym) => {
        const sig = signals?.signals?.[sym];
        const price = sig?.price;
        const isActive = sym === selected;
        const sideTone =
          sig?.side === 'BUY' || sig?.side === 'LONG'
            ? C.bull
            : sig?.side === 'SELL' || sig?.side === 'SHORT'
            ? C.bear
            : C.muted;
        return (
          <button
            key={sym}
            onClick={() => onSelect(sym)}
            style={{
              padding: '10px 12px',
              border: 'none',
              borderBottom: `1px solid ${C.border}`,
              borderLeft: `2px solid ${isActive ? C.brand : 'transparent'}`,
              background: isActive ? '#0d0d14' : 'transparent',
              color: C.text,
              cursor: 'pointer',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              fontSize: F.sm,
              fontFamily: 'JetBrains Mono, monospace',
              transition: 'background 120ms ease-out',
              textAlign: 'left',
            }}
          >
            <span style={{ fontWeight: 600, color: C.text }}>{sym}</span>
            <span style={{ color: sideTone, fontSize: F.xs }}>
              {price != null ? formatPrice(price) : '—'}
            </span>
          </button>
        );
      })}
    </aside>
  );
}

// ── Chart center column ─────────────────────────────────────────────────────

function ChartCenter({
  symbol,
  activeTab,
  setActiveTab,
  positions,
  currentSignal,
}: {
  symbol: string;
  activeTab: 'positions' | 'orders' | 'bot';
  setActiveTab: (t: 'positions' | 'orders' | 'bot') => void;
  positions: Position[];
  currentSignal: SignalSnap | undefined;
}) {
  return (
    <section
      style={{
        background: '#0a0a0f',
        border: `1px solid ${C.border}`,
        borderRadius: R.sm,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      {/* Symbol header */}
      <div
        style={{
          padding: '10px 14px',
          borderBottom: `1px solid ${C.border}`,
          display: 'flex',
          alignItems: 'baseline',
          gap: 12,
        }}
      >
        <h2
          style={{
            margin: 0,
            fontSize: F.lg,
            fontWeight: 700,
            color: C.text,
            fontFamily: 'JetBrains Mono, monospace',
          }}
        >
          {symbol}-PERP
        </h2>
        <span
          style={{
            fontSize: F.sm,
            color: C.text,
            fontFamily: 'JetBrains Mono, monospace',
          }}
        >
          {currentSignal?.price != null ? formatPrice(currentSignal.price) : '—'}
        </span>
      </div>

      {/* Chart placeholder — wires in Phase 3b with Lightweight Charts */}
      <div
        style={{
          flex: 1,
          minHeight: 360,
          background: '#050508',
          borderBottom: `1px solid ${C.border}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: C.muted,
          fontSize: F.sm,
        }}
      >
        Chart loads in Phase 3b
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', borderBottom: `1px solid ${C.border}` }}>
        {(['bot', 'positions', 'orders'] as const).map((t) => {
          const active = activeTab === t;
          return (
            <button
              key={t}
              onClick={() => setActiveTab(t)}
              style={{
                flex: '0 0 auto',
                padding: '10px 16px',
                background: 'transparent',
                border: 'none',
                borderBottom: `2px solid ${active ? C.brand : 'transparent'}`,
                color: active ? C.text : C.textSub,
                fontSize: F.sm,
                fontWeight: 500,
                textTransform: 'capitalize',
                cursor: 'pointer',
                fontFamily: 'inherit',
                marginBottom: -1,
              }}
            >
              {t === 'bot' ? 'Bot Signal' : t}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div style={{ padding: 14, minHeight: 120 }}>
        {activeTab === 'bot' && <BotSignalTab signal={currentSignal} symbol={symbol} />}
        {activeTab === 'positions' && (
          <PositionsTab positions={positions.filter((p) => p.symbol === symbol)} />
        )}
        {activeTab === 'orders' && (
          <div style={{ color: C.muted, fontSize: F.sm }}>No pending orders.</div>
        )}
      </div>
    </section>
  );
}

function BotSignalTab({ signal, symbol }: { signal: SignalSnap | undefined; symbol: string }) {
  if (!signal || !signal.action || signal.action.toLowerCase() === 'flat') {
    return (
      <div style={{ color: C.muted, fontSize: F.sm }}>
        WAGMI has no active signal on {symbol} right now.
      </div>
    );
  }
  const isLong = signal.side === 'BUY' || signal.side === 'LONG';
  const sideTone = isLong ? C.bull : C.bear;
  const conf = signal.confidence != null ? Math.round(signal.confidence * 100) : null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 10,
          fontFamily: 'JetBrains Mono, monospace',
        }}
      >
        <span style={{ fontSize: F.lg, fontWeight: 700, color: sideTone }}>
          {isLong ? 'LONG' : 'SHORT'}
        </span>
        {conf != null && (
          <span style={{ fontSize: F.sm, color: C.text }}>{conf}% conviction</span>
        )}
        {signal.regime && (
          <span style={{ fontSize: F.xs, color: C.muted }}>regime: {signal.regime}</span>
        )}
      </div>
      {signal.reasoning && (
        <p style={{ margin: 0, fontSize: F.sm, color: C.textSub, lineHeight: 1.5 }}>
          {signal.reasoning}
        </p>
      )}
    </div>
  );
}

function PositionsTab({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return <div style={{ color: C.muted, fontSize: F.sm }}>No open positions on this symbol.</div>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {positions.map((p, i) => (
        <div
          key={i}
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: F.sm,
            fontFamily: 'JetBrains Mono, monospace',
            padding: '6px 0',
          }}
        >
          <span>
            {p.symbol} {p.side}
          </span>
          <span style={{ color: C.text }}>
            {p.qty} @ {formatPrice(p.entry)}
          </span>
          <span
            style={{ color: (p.unrealized_pnl ?? 0) >= 0 ? C.bull : C.bear }}
          >
            {p.unrealized_pnl != null ? `${p.unrealized_pnl >= 0 ? '+' : ''}$${p.unrealized_pnl.toFixed(2)}` : '—'}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Order rail (right column, with §7.1 bot-opinion slot) ───────────────────

function OrderRail({
  symbol,
  currentSignal,
  currentPosition,
}: {
  symbol: string;
  currentSignal: SignalSnap | undefined;
  currentPosition: Position | undefined;
}) {
  const [orderType, setOrderType] = useState<'market' | 'limit' | 'trigger'>('market');
  const [side, setSide] = useState<'buy' | 'sell'>('buy');

  // §7.1 — Bot opinion alignment with the side currently selected
  const botSide =
    currentSignal?.side === 'BUY' || currentSignal?.side === 'LONG'
      ? 'buy'
      : currentSignal?.side === 'SELL' || currentSignal?.side === 'SHORT'
      ? 'sell'
      : null;
  const botAlignment = !currentSignal?.action
    ? 'no-signal'
    : botSide === side
    ? 'aligned'
    : botSide
    ? 'disagrees'
    : 'neutral';

  return (
    <aside
      style={{
        background: '#0a0a0f',
        border: `1px solid ${C.border}`,
        borderRadius: R.sm,
        padding: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
      }}
    >
      {/* Order type tabs */}
      <div style={{ display: 'flex', gap: 4 }}>
        {(['market', 'limit', 'trigger'] as const).map((t) => {
          const active = orderType === t;
          return (
            <button
              key={t}
              onClick={() => setOrderType(t)}
              style={{
                flex: 1,
                padding: '6px 0',
                fontSize: F.xs,
                background: active ? '#0d0d14' : 'transparent',
                color: active ? C.text : C.textSub,
                border: `1px solid ${active ? C.borderBright : C.border}`,
                borderRadius: R.xs,
                cursor: 'pointer',
                textTransform: 'capitalize',
                fontFamily: 'inherit',
              }}
            >
              {t}
            </button>
          );
        })}
      </div>

      {/* Buy/Sell switch */}
      <div style={{ display: 'flex', gap: 4 }}>
        <button
          onClick={() => setSide('buy')}
          style={{
            flex: 1,
            padding: '8px 0',
            background: side === 'buy' ? C.bullMuted : 'transparent',
            color: side === 'buy' ? C.bull : C.textSub,
            border: `1px solid ${side === 'buy' ? C.bull : C.border}`,
            borderRadius: R.xs,
            fontSize: F.sm,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Buy / Long
        </button>
        <button
          onClick={() => setSide('sell')}
          style={{
            flex: 1,
            padding: '8px 0',
            background: side === 'sell' ? C.bearMuted : 'transparent',
            color: side === 'sell' ? C.bear : C.textSub,
            border: `1px solid ${side === 'sell' ? C.bear : C.border}`,
            borderRadius: R.xs,
            fontSize: F.sm,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Sell / Short
        </button>
      </div>

      {/* Size + price inputs (visual placeholders — wiring to exchange is Phase 8+) */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <Field label="Size">
          <input
            type="number"
            placeholder="0.00"
            disabled
            style={inputStyle}
          />
        </Field>
        {orderType !== 'market' && (
          <Field label="Price">
            <input type="number" placeholder="0.00" disabled style={inputStyle} />
          </Field>
        )}
        <Field label="Leverage">
          <input type="number" placeholder="3" disabled style={inputStyle} />
        </Field>
      </div>

      {/* Submit (disabled — read-only Phase 3) */}
      <button
        disabled
        style={{
          padding: '10px 0',
          background: side === 'buy' ? C.bull : C.bear,
          color: '#000',
          border: 'none',
          borderRadius: R.xs,
          fontSize: F.sm,
          fontWeight: 700,
          cursor: 'not-allowed',
          opacity: 0.6,
        }}
      >
        {side === 'buy' ? 'Buy' : 'Sell'} {symbol} (read-only)
      </button>

      {/* §7.1 Bot opinion slot ─ inline below buy/sell */}
      <BotOpinionSlot alignment={botAlignment} signal={currentSignal} />

      {/* Open position summary, if any */}
      {currentPosition && (
        <div
          style={{
            marginTop: 8,
            paddingTop: 12,
            borderTop: `1px solid ${C.border}`,
            fontSize: F.xs,
            color: C.textSub,
            fontFamily: 'JetBrains Mono, monospace',
          }}
        >
          <div style={{ color: C.muted, marginBottom: 4 }}>POSITION</div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}>
            <span>{currentPosition.side}</span>
            <span>
              {currentPosition.qty} @ {formatPrice(currentPosition.entry)}
            </span>
          </div>
          {currentPosition.unrealized_pnl != null && (
            <div
              style={{
                color: currentPosition.unrealized_pnl >= 0 ? C.bull : C.bear,
                marginTop: 4,
              }}
            >
              uPnL: {currentPosition.unrealized_pnl >= 0 ? '+' : ''}${currentPosition.unrealized_pnl.toFixed(2)}
            </div>
          )}
        </div>
      )}
    </aside>
  );
}

function BotOpinionSlot({
  alignment,
  signal,
}: {
  alignment: 'aligned' | 'disagrees' | 'neutral' | 'no-signal';
  signal: SignalSnap | undefined;
}) {
  const cfg: Record<typeof alignment, { label: string; color: string; tone: string }> = {
    aligned: { label: 'ALIGNED', color: C.bull, tone: 'WAGMI agrees with this side' },
    disagrees: { label: 'DISAGREES', color: C.bear, tone: 'WAGMI suggests the opposite side' },
    neutral: { label: 'NEUTRAL', color: C.muted, tone: 'WAGMI is undecided on direction' },
    'no-signal': { label: 'NO SIGNAL', color: C.muted, tone: 'WAGMI has no active opinion' },
  };
  const c = cfg[alignment];
  const conf = signal?.confidence != null ? Math.round(signal.confidence * 100) : null;
  return (
    <div
      style={{
        marginTop: 8,
        padding: '8px 10px',
        background: '#050508',
        border: `1px solid ${C.border}`,
        borderLeft: `3px solid ${c.color}`,
        borderRadius: R.xs,
        fontSize: F.xs,
        color: C.textSub,
        fontFamily: 'JetBrains Mono, monospace',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ color: c.color, fontWeight: 700 }}>{c.label}</span>
        {conf != null && <span style={{ color: C.text }}>{conf}% conf</span>}
      </div>
      <div style={{ color: C.muted, marginTop: 2, fontSize: 10 }}>{c.tone}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      <span style={{ fontSize: 10, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.05 }}>
        {label}
      </span>
      {children}
    </label>
  );
}

const inputStyle: React.CSSProperties = {
  background: '#050508',
  border: `1px solid ${C.border}`,
  borderRadius: R.xs,
  color: C.text,
  padding: '6px 8px',
  fontSize: 13,
  fontFamily: 'JetBrains Mono, monospace',
  outline: 'none',
};

function formatPrice(p: number): string {
  if (p > 1000) return p.toLocaleString('en-US', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
  if (p > 1) return p.toFixed(2);
  return p.toPrecision(4);
}
