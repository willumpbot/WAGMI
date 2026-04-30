'use client';

/**
 * /live — The Manual Trader Co-Pilot.
 * See audits/2026-04-29/06_live_copilot_design.md for full spec.
 *
 * Shows in parallel:
 *   • Live mechanical analysis (ensemble + gates + cohorts)
 *   • Live agentic analysis (LLM agent ladder)
 *   • Synthesis (combined verdict with disagreement flags)
 *
 * Plus an Ask-the-Agents panel for interactive Q&A.
 *
 * Phase 4a: page skeleton + symbol pills + mode toggle. Columns are stubs.
 * Subsequent commits fill in each column then the Q&A panel.
 */

import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import { C, F, R } from '../src/theme';
import MechanicalColumn from '../components/live/MechanicalColumn';
import AgenticColumn from '../components/live/AgenticColumn';
import SynthesisColumn from '../components/live/SynthesisColumn';
import AskAgentsPanel from '../components/live/AskAgentsPanel';
import ScoreboardRow from '../components/live/ScoreboardRow';

const SYMBOLS = ['BTC', 'ETH', 'SOL', 'HYPE'];
type Mode = 'live' | 'replay';

export default function LivePage() {
  const [symbol, setSymbol] = useState<string>('BTC');
  const [allSymbolsMode, setAllSymbolsMode] = useState<boolean>(false);
  const [mode, setMode] = useState<Mode>('live');
  const [replayTimestamp, setReplayTimestamp] = useState<string>('');
  const [isMobile, setIsMobile] = useState<boolean>(false);

  // Triple-panel grid stacks on narrow screens to keep each column readable.
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth < 1024);
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // Read ?symbol=BTC from URL on mount (used by deep-links from /status etc.)
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const s = (params.get('symbol') || '').toUpperCase();
    if (s && SYMBOLS.includes(s)) {
      setSymbol(s);
      setAllSymbolsMode(false);
    }
  }, []);

  return (
    <>
      <Head>
        <title>Live Co-Pilot — WAGMI</title>
      </Head>

      <PageHeader
        symbol={symbol}
        setSymbol={setSymbol}
        allSymbolsMode={allSymbolsMode}
        setAllSymbolsMode={setAllSymbolsMode}
        mode={mode}
        setMode={setMode}
        replayTimestamp={replayTimestamp}
        setReplayTimestamp={setReplayTimestamp}
      />

      {mode === 'replay' && replayTimestamp && (
        <div
          style={{
            marginTop: 6,
            padding: '8px 12px',
            background: C.warn + '12',
            border: `1px solid ${C.warn}55`,
            borderRadius: R.sm,
            fontSize: F.xs,
            color: C.textSub,
            fontFamily: 'JetBrains Mono, monospace',
          }}
        >
          <span style={{ color: C.warn, fontWeight: 700 }}>⟲ REPLAY MODE</span>
          <span style={{ marginLeft: 8 }}>
            showing state as of {new Date(replayTimestamp).toLocaleString()} —
            historical positions and signal snapshots not yet rehydrated; only
            decision-time data is shown.
          </span>
        </div>
      )}

      {mode === 'replay' && !replayTimestamp && (
        <div
          style={{
            marginTop: 6,
            padding: '8px 12px',
            background: '#0a0a0f',
            border: `1px solid ${C.border}`,
            borderRadius: R.sm,
            fontSize: F.xs,
            color: C.textSub,
            fontFamily: 'JetBrains Mono, monospace',
          }}
        >
          Pick a date/time in the picker above to replay the bot&apos;s state.
        </div>
      )}

      {allSymbolsMode ? (
        <Scoreboard
          symbols={SYMBOLS}
          onFocus={(s) => {
            setAllSymbolsMode(false);
            setSymbol(s);
          }}
        />
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: isMobile ? '1fr' : '1fr 1fr 1fr',
            gap: 12,
            marginTop: 12,
            minHeight: 480,
          }}
        >
          <MechanicalColumn
            symbol={symbol}
            mode={mode}
            replayTimestamp={mode === 'replay' ? replayTimestamp : undefined}
          />
          <AgenticColumn
            symbol={symbol}
            mode={mode}
            replayTimestamp={mode === 'replay' ? replayTimestamp : undefined}
          />
          <SynthesisColumn
            symbol={symbol}
            mode={mode}
            replayTimestamp={mode === 'replay' ? replayTimestamp : undefined}
          />
        </div>
      )}

      {!allSymbolsMode && (
        <AskAgentsPanel symbol={symbol} mode={mode} replayTimestamp={replayTimestamp} />
      )}
    </>
  );
}

// ── Page header: symbol pills + mode toggle ─────────────────────────────────

function PageHeader({
  symbol,
  setSymbol,
  allSymbolsMode,
  setAllSymbolsMode,
  mode,
  setMode,
  replayTimestamp,
  setReplayTimestamp,
}: {
  symbol: string;
  setSymbol: (s: string) => void;
  allSymbolsMode: boolean;
  setAllSymbolsMode: (v: boolean) => void;
  mode: Mode;
  setMode: (m: Mode) => void;
  replayTimestamp: string;
  setReplayTimestamp: (t: string) => void;
}) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
        background: '#0a0a0f',
        border: `1px solid ${C.border}`,
        borderRadius: R.sm,
        padding: '12px 14px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span
          style={{
            fontSize: F.lg,
            fontWeight: 700,
            color: C.text,
            letterSpacing: -0.3,
          }}
        >
          Live Co-Pilot
        </span>
        <span style={{ fontSize: F.xs, color: C.muted, fontFamily: 'JetBrains Mono, monospace' }}>
          mechanical · agentic · synthesis
        </span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        {/* Symbol pills */}
        <div style={{ display: 'flex', gap: 4 }}>
          {SYMBOLS.map((s) => {
            const active = !allSymbolsMode && s === symbol;
            return (
              <button
                key={s}
                onClick={() => {
                  setAllSymbolsMode(false);
                  setSymbol(s);
                }}
                style={{
                  padding: '6px 12px',
                  fontSize: F.sm,
                  fontWeight: 600,
                  fontFamily: 'JetBrains Mono, monospace',
                  background: active ? '#0d0d14' : 'transparent',
                  color: active ? C.text : C.textSub,
                  border: `1px solid ${active ? C.borderBright : C.border}`,
                  borderRadius: R.xs,
                  cursor: 'pointer',
                  transition: 'all 120ms ease-out',
                }}
              >
                {s}
              </button>
            );
          })}
          <button
            onClick={() => setAllSymbolsMode(true)}
            style={{
              padding: '6px 12px',
              fontSize: F.sm,
              fontWeight: 600,
              fontFamily: 'JetBrains Mono, monospace',
              background: allSymbolsMode ? '#0d0d14' : 'transparent',
              color: allSymbolsMode ? C.text : C.textSub,
              border: `1px solid ${allSymbolsMode ? C.borderBright : C.border}`,
              borderRadius: R.xs,
              cursor: 'pointer',
            }}
          >
            All
          </button>
        </div>

        <span style={{ color: C.faint, fontSize: F.xs }}>·</span>

        {/* Mode toggle */}
        <div style={{ display: 'flex', gap: 4 }}>
          <button
            onClick={() => setMode('live')}
            style={modeBtnStyle(mode === 'live', C.brand)}
          >
            ● Live
          </button>
          <button
            onClick={() => setMode('replay')}
            style={modeBtnStyle(mode === 'replay', C.warn)}
          >
            ⟲ Replay
          </button>
        </div>

        {mode === 'replay' && (
          <input
            type="datetime-local"
            value={replayTimestamp}
            onChange={(e) => setReplayTimestamp(e.target.value)}
            style={{
              fontSize: F.xs,
              padding: '4px 6px',
              background: '#050508',
              border: `1px solid ${C.border}`,
              borderRadius: R.xs,
              color: C.text,
              fontFamily: 'JetBrains Mono, monospace',
            }}
          />
        )}

        {allSymbolsMode && (
          <span
            style={{
              marginLeft: 'auto',
              fontSize: F.xs,
              color: C.muted,
              fontFamily: 'JetBrains Mono, monospace',
            }}
          >
            scoreboard — click row to focus
          </span>
        )}
      </div>
    </div>
  );
}

function modeBtnStyle(active: boolean, accent: string): React.CSSProperties {
  return {
    padding: '6px 12px',
    fontSize: F.sm,
    fontWeight: 600,
    fontFamily: 'JetBrains Mono, monospace',
    background: active ? accent + '15' : 'transparent',
    color: active ? accent : C.textSub,
    border: `1px solid ${active ? accent : C.border}`,
    borderRadius: R.xs,
    cursor: 'pointer',
    transition: 'all 120ms ease-out',
  };
}

// ── Scoreboard view (all symbols) ───────────────────────────────────────────

function Scoreboard({
  symbols,
  onFocus,
}: {
  symbols: string[];
  onFocus: (s: string) => void;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
      {/* Column legend */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '90px 1fr 1fr 1fr',
          gap: 0,
          padding: '0 14px',
          fontSize: 9,
          color: C.muted,
          textTransform: 'uppercase',
          letterSpacing: 0.06,
          fontWeight: 600,
        }}
      >
        <span>symbol</span>
        <span style={{ paddingLeft: 12, color: C.info }}>mechanical</span>
        <span style={{ paddingLeft: 12, color: C.purple }}>agentic</span>
        <span style={{ paddingLeft: 12, color: C.brand }}>synthesis</span>
      </div>
      {symbols.map((s) => (
        <ScoreboardRow key={s} symbol={s} onFocus={onFocus} />
      ))}
      <div
        style={{
          padding: '8px 14px',
          fontSize: F.xs,
          color: C.muted,
          fontStyle: 'italic',
          textAlign: 'center',
        }}
      >
        Click any row to focus that symbol and open the full triple-panel +
        Q&amp;A.
      </div>
    </div>
  );
}
