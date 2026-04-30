'use client';

import React, { useEffect, useState, useMemo } from 'react';
import { C, F, R } from '../../src/theme';
import { resolveApiBase } from '../../src/api';
import ColumnShell, { Section, Stat, Empty } from './ColumnShell';

/**
 * SynthesisColumn — combines mechanical & agentic into a single verdict +
 * helpers for the manual trader.
 *
 * Computation is client-side: pull both raw sources, compute disagreement
 * level, sized conviction, and trader helpers.
 *
 * Phase 4d: full client-side synthesis based on /v1/signals + /v1/llm/feed.
 */

type Sig = {
  side?: string | null;
  confidence?: number | null;
  action?: string | null;
  regime?: string | null;
};

type LlmDecision = {
  symbol?: string;
  action?: string | null;
  side?: string | null;
  confidence?: number | null;
  is_veto?: boolean | null;
  allowed?: boolean | null;
};

type Pos = {
  symbol: string;
  side: string;
  entry: number;
  qty: number;
  unrealized_pnl?: number;
};

export default function SynthesisColumn({
  symbol,
  mode,
  replayTimestamp,
}: {
  symbol: string;
  mode: 'live' | 'replay';
  replayTimestamp?: string;
}) {
  const [sig, setSig] = useState<Sig | null>(null);
  const [llm, setLlm] = useState<LlmDecision | null>(null);
  const [position, setPosition] = useState<Pos | null>(null);
  const [bankroll, setBankroll] = useState<number>(5000); // operator-adjustable

  useEffect(() => {
    if (mode !== 'live') return;
    let cancelled = false;
    const apiBase = resolveApiBase();
    const load = async () => {
      try {
        const [sigRes, llmRes, posRes] = await Promise.all([
          fetch(`${apiBase}/v1/signals`, { cache: 'no-store' }),
          fetch(`${apiBase}/v1/llm/feed?limit=50`, { cache: 'no-store' }),
          fetch(`${apiBase}/v1/positions`, { cache: 'no-store' }),
        ]);
        if (cancelled) return;
        if (sigRes.ok) {
          const j = await sigRes.json();
          setSig(j.signals?.[symbol] ?? null);
        }
        if (llmRes.ok) {
          const j = await llmRes.json();
          setLlm((j.decisions || []).find((d: LlmDecision) => (d.symbol || '').toUpperCase() === symbol) || null);
        }
        if (posRes.ok) {
          const j = await posRes.json();
          setPosition((j.positions || []).find((p: Pos) => p.symbol === symbol) || null);
        }
      } catch {
        /* silent */
      }
    };
    load();
    const id = setInterval(load, 15_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [symbol, mode]);

  const synthesis = useMemo(() => synthesize(sig, llm), [sig, llm]);

  return (
    <ColumnShell
      tone="synthesis"
      verdict={{ label: synthesis.verdictLabel, color: synthesis.verdictColor }}
    >
      {/* Disagreement banner — shows loud when sources differ */}
      <DisagreementBanner level={synthesis.disagreement} />

      {/* Final action */}
      <Section title="Combined Verdict">
        <Stat label="action" value={synthesis.verdictLabel} tone={synthesis.verdictColor} />
        <Stat
          label="sized conviction"
          value={`${Math.round(synthesis.sizedConviction * 100)}%`}
          tone={synthesis.sizedConviction >= 0.6 ? C.bull : synthesis.sizedConviction >= 0.4 ? C.warn : C.muted}
        />
        <Stat
          label="agreement"
          value={synthesis.disagreement === 'aligned' ? 'aligned' : synthesis.disagreement === 'mixed' ? 'mixed' : 'opposed'}
          tone={
            synthesis.disagreement === 'aligned' ? C.bull : synthesis.disagreement === 'mixed' ? C.warn : C.bear
          }
        />
      </Section>

      {/* One-line summary */}
      <Section title="Summary">
        <p style={{ margin: 0, fontSize: F.sm, color: C.text, lineHeight: 1.5 }}>
          {synthesis.summary}
        </p>
      </Section>

      {/* Manual-trader helpers */}
      <Section title="If you trade this manually" hint="WAGMI suggests, you decide">
        <SizingHelper
          bankroll={bankroll}
          setBankroll={setBankroll}
          conviction={synthesis.sizedConviction}
          side={synthesis.directional}
        />
      </Section>

      {/* Position context */}
      {position && (
        <Section title={`Open ${symbol} position`}>
          <Stat label="side / size" value={`${position.side} ${position.qty}`} />
          <Stat label="entry" value={`$${position.entry.toFixed(2)}`} />
          <Stat
            label="uPnL"
            value={position.unrealized_pnl != null ? `${position.unrealized_pnl >= 0 ? '+' : ''}$${position.unrealized_pnl.toFixed(2)}` : '—'}
            tone={(position.unrealized_pnl ?? 0) >= 0 ? C.bull : C.bear}
          />
          <ExitGuidance
            position={position}
            mechanicalSide={synthesis.mechanicalDirectional}
            agenticSide={synthesis.agenticDirectional}
          />
        </Section>
      )}

      {/* Suggested questions to Ask Agents */}
      <Section title="Worth asking the agents" hint="click to copy">
        {synthesis.questions.map((q, i) => (
          <button
            key={i}
            onClick={() => {
              // Emit a custom event the AskAgentsPanel listens for.
              window.dispatchEvent(new CustomEvent('ask-agents:prefill', { detail: q }));
            }}
            style={{
              width: '100%',
              textAlign: 'left',
              padding: '6px 8px',
              fontSize: F.xs,
              color: C.textSub,
              background: 'transparent',
              border: `1px solid ${C.border}`,
              borderRadius: R.xs,
              marginBottom: 4,
              cursor: 'pointer',
              fontFamily: 'inherit',
              transition: 'all 120ms ease-out',
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.borderColor = C.borderBright;
              (e.currentTarget as HTMLButtonElement).style.color = C.text;
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.borderColor = C.border;
              (e.currentTarget as HTMLButtonElement).style.color = C.textSub;
            }}
          >
            → {q}
          </button>
        ))}
      </Section>

      {!sig && !llm && (
        <Section title="No data">
          <Empty note="Waiting for signals + agent decisions…" />
        </Section>
      )}
    </ColumnShell>
  );
}

// ── Synthesis logic ──────────────────────────────────────────────────────────

type Disagreement = 'aligned' | 'mixed' | 'opposed';

function synthesize(sig: Sig | null, llm: LlmDecision | null) {
  const mech = directional(sig?.side, sig?.action);
  const agent = directional(llm?.side, llm?.action);
  const mechConf = (sig?.confidence ?? 0) > 1 ? (sig?.confidence ?? 0) / 100 : sig?.confidence ?? 0;
  const agentConf =
    (llm?.confidence ?? 0) > 1 ? (llm?.confidence ?? 0) / 100 : llm?.confidence ?? 0;

  const mechActive = mech !== 'flat';
  const agentActive = agent !== 'flat' && llm?.allowed !== false && !llm?.is_veto;

  // Disagreement classification
  let disagreement: Disagreement;
  if (mech === agent && mechActive) {
    disagreement = 'aligned';
  } else if ((mechActive && !agentActive) || (!mechActive && agentActive)) {
    disagreement = 'mixed';
  } else if (mech !== agent && mechActive && agentActive) {
    disagreement = 'opposed';
  } else {
    disagreement = 'aligned'; // both flat
  }

  // Sized conviction: mean of two confidences × disagreement penalty.
  const meanConf = (mechConf + agentConf) / 2;
  const penalty = disagreement === 'aligned' ? 1.0 : disagreement === 'mixed' ? 0.7 : 0.3;
  const sizedConviction = Math.min(1.0, Math.max(0, meanConf * penalty));

  // Final verdict: pick the side both agree on; if mixed, pick whichever is active; if opposed, FLAT.
  const directionalSide: 'long' | 'short' | 'flat' =
    disagreement === 'opposed'
      ? 'flat'
      : mechActive && (mech === 'long' || mech === 'short')
      ? mech
      : agentActive && (agent === 'long' || agent === 'short')
      ? agent
      : 'flat';

  const verdictLabel = directionalSide.toUpperCase();
  const verdictColor =
    disagreement === 'opposed'
      ? C.bear
      : directionalSide === 'long'
      ? C.bull
      : directionalSide === 'short'
      ? C.bear
      : C.muted;

  // Plain-English summary
  let summary: string;
  if (directionalSide === 'flat') {
    if (disagreement === 'opposed') {
      summary = `Systems disagree (mechanical says ${mech}, agents say ${agent}). Stand down.`;
    } else {
      summary = 'Neither system has high-conviction signal. Wait.';
    }
  } else {
    const reliability =
      disagreement === 'aligned' ? 'both systems agree' : disagreement === 'mixed' ? 'one system active' : 'systems split';
    summary = `${verdictLabel} — ${Math.round(sizedConviction * 100)}% sized conviction (${reliability}).`;
  }

  // Pre-built questions to ask agents — drives engagement
  const questions = makeQuestions(directionalSide, disagreement, mech, agent);

  return {
    verdictLabel,
    verdictColor,
    sizedConviction,
    disagreement,
    summary,
    directional: directionalSide,
    mechanicalDirectional: mech,
    agenticDirectional: agent,
    questions,
  };
}

function directional(
  side: string | undefined | null,
  action: string | undefined | null,
): 'long' | 'short' | 'flat' {
  const a = (action || '').toLowerCase();
  if (a === 'flat' || a === 'skip' || !a) return 'flat';
  const s = (side || '').toUpperCase();
  if (s === 'BUY' || s === 'LONG') return 'long';
  if (s === 'SELL' || s === 'SHORT') return 'short';
  return 'flat';
}

function makeQuestions(
  side: 'long' | 'short' | 'flat',
  d: Disagreement,
  mech: string,
  agent: string,
): string[] {
  if (d === 'opposed') {
    return [
      `Why does the mechanical pipeline say ${mech} while agents say ${agent}?`,
      'Which side has been more accurate recently in this regime?',
      'What would resolve the disagreement — what data point would tip me?',
    ];
  }
  if (side === 'flat') {
    return [
      'What conditions would make either system fire a signal here?',
      'Is there a setup type I should be watching for?',
      'How does this regime usually break — direction and timing?',
    ];
  }
  return [
    `What's the strongest counter-thesis to going ${side}?`,
    'What are the key invalidation levels?',
    `If I take this ${side}, where should the stop be?`,
    `What's the best-case TP1/TP2 plan for this ${side}?`,
  ];
}

// ── Sub-components ───────────────────────────────────────────────────────────

function DisagreementBanner({ level }: { level: Disagreement }) {
  if (level === 'aligned') return null;
  const cfg = {
    mixed: { label: 'PARTIAL DISAGREEMENT', color: C.warn, note: 'one system has a signal, the other is flat' },
    opposed: { label: 'SYSTEMS OPPOSED', color: C.bear, note: 'mechanical and agents disagree on direction' },
  } as const;
  const c = cfg[level];
  return (
    <div
      style={{
        padding: '8px 10px',
        background: c.color + '12',
        border: `1px solid ${c.color}55`,
        borderRadius: R.xs,
        fontFamily: 'JetBrains Mono, monospace',
      }}
    >
      <div style={{ color: c.color, fontWeight: 700, fontSize: F.xs }}>⚠ {c.label}</div>
      <div style={{ color: C.textSub, fontSize: 10, marginTop: 2 }}>{c.note}</div>
    </div>
  );
}

function SizingHelper({
  bankroll,
  setBankroll,
  conviction,
  side,
}: {
  bankroll: number;
  setBankroll: (n: number) => void;
  conviction: number;
  side: 'long' | 'short' | 'flat';
}) {
  if (side === 'flat') {
    return <div style={{ color: C.muted, fontSize: F.xs }}>No sizing — no directional signal.</div>;
  }

  // Risk: 1% baseline × conviction
  const riskPct = 0.01 * Math.max(0.3, conviction);
  const riskUsd = bankroll * riskPct;
  // Conservative leverage suggestion: 2x at low conv, 5x at high
  const leverage = conviction >= 0.7 ? 5 : conviction >= 0.5 ? 3 : 2;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: F.xs, color: C.textSub }}>
        <span style={{ color: C.muted, minWidth: 60 }}>bankroll</span>
        <input
          type="number"
          value={bankroll}
          onChange={(e) => setBankroll(Number(e.target.value) || 0)}
          style={{
            flex: 1,
            background: '#050508',
            border: `1px solid ${C.border}`,
            color: C.text,
            padding: '4px 6px',
            fontSize: F.xs,
            fontFamily: 'JetBrains Mono, monospace',
            borderRadius: R.xs,
          }}
        />
      </label>
      <Stat label="risk %" value={`${(riskPct * 100).toFixed(2)}%`} />
      <Stat label="risk $" value={`$${riskUsd.toFixed(2)}`} tone={C.text} />
      <Stat label="suggested lev" value={`${leverage}x`} tone={C.text} />
      <div
        style={{
          fontSize: 10,
          color: C.faint,
          marginTop: 4,
          fontStyle: 'italic',
        }}
      >
        Position size = risk_$ ÷ stop_distance — set stop based on chart structure.
      </div>
    </div>
  );
}

function ExitGuidance({
  position,
  mechanicalSide,
  agenticSide,
}: {
  position: Pos;
  mechanicalSide: 'long' | 'short' | 'flat';
  agenticSide: 'long' | 'short' | 'flat';
}) {
  const positionSide: 'long' | 'short' = position.side.toUpperCase() === 'LONG' ? 'long' : 'short';
  const mechAgrees = mechanicalSide === 'flat' || mechanicalSide === positionSide;
  const agentAgrees = agenticSide === 'flat' || agenticSide === positionSide;

  let advice: { label: string; tone: string; text: string };
  if (mechAgrees && agentAgrees) {
    advice = { label: 'HOLD', tone: C.bull, text: 'Both systems agree with your direction.' };
  } else if (!mechAgrees && !agentAgrees) {
    advice = { label: 'CONSIDER CLOSE', tone: C.bear, text: 'Both systems now favor the opposite side.' };
  } else {
    advice = { label: 'WATCH', tone: C.warn, text: 'One system has flipped against you.' };
  }

  return (
    <div
      style={{
        marginTop: 6,
        padding: 8,
        background: '#050508',
        border: `1px solid ${C.border}`,
        borderLeft: `3px solid ${advice.tone}`,
        borderRadius: R.xs,
        fontSize: F.xs,
        fontFamily: 'JetBrains Mono, monospace',
      }}
    >
      <div style={{ color: advice.tone, fontWeight: 700 }}>{advice.label}</div>
      <div style={{ color: C.textSub, marginTop: 2, lineHeight: 1.4 }}>{advice.text}</div>
    </div>
  );
}
