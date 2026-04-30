'use client';

import React, { useEffect, useMemo, useState } from 'react';
import { C, F, R } from '../../src/theme';
import { resolveApiBase } from '../../src/api';

/**
 * ScoreboardRow — compact triple-panel summary for a single symbol.
 * Used in All-Symbols mode on /live: render one row per symbol instead of
 * the full per-symbol triple-column. Click a row to focus that symbol.
 *
 * Each row shows in three cells (mechanical | agentic | synthesis):
 *  - directional verdict + confidence
 *  - one-line action guidance
 *  - color-coded by alignment level
 *
 * Polls /v1/signals + /v1/llm/feed once on mount + every 20s.
 */

type Sig = {
  side?: string | null;
  confidence?: number | null;
  action?: string | null;
  regime?: string | null;
  price?: number | null;
};

type LlmDecision = {
  symbol?: string;
  action?: string | null;
  side?: string | null;
  confidence?: number | null;
  is_veto?: boolean | null;
  allowed?: boolean | null;
};

export default function ScoreboardRow({
  symbol,
  onFocus,
}: {
  symbol: string;
  onFocus: (s: string) => void;
}) {
  const [sig, setSig] = useState<Sig | null>(null);
  const [llm, setLlm] = useState<LlmDecision | null>(null);

  useEffect(() => {
    let cancelled = false;
    const apiBase = resolveApiBase();
    const load = async () => {
      try {
        const [sigRes, llmRes] = await Promise.all([
          fetch(`${apiBase}/v1/signals`, { cache: 'no-store' }),
          fetch(`${apiBase}/v1/llm/feed?limit=50`, { cache: 'no-store' }),
        ]);
        if (cancelled) return;
        if (sigRes.ok) {
          const j = await sigRes.json();
          setSig(j.signals?.[symbol] ?? null);
        }
        if (llmRes.ok) {
          const j = await llmRes.json();
          setLlm(
            (j.decisions || []).find((d: LlmDecision) => (d.symbol || '').toUpperCase() === symbol) || null,
          );
        }
      } catch {
        /* silent */
      }
    };
    load();
    const id = setInterval(load, 20_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [symbol]);

  const summary = useMemo(() => summarize(sig, llm), [sig, llm]);

  return (
    <button
      onClick={() => onFocus(symbol)}
      style={{
        display: 'grid',
        gridTemplateColumns: '90px 1fr 1fr 1fr',
        gap: 0,
        background: '#0a0a0f',
        border: `1px solid ${C.border}`,
        borderLeft: `3px solid ${summary.borderTone}`,
        borderRadius: R.sm,
        padding: 0,
        cursor: 'pointer',
        textAlign: 'left',
        fontFamily: 'inherit',
        color: 'inherit',
        transition: 'border-color 120ms ease-out, background 120ms ease-out',
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLButtonElement).style.background = '#0d0d14';
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLButtonElement).style.background = '#0a0a0f';
      }}
    >
      <SymbolCell symbol={symbol} price={sig?.price} />
      <Cell
        tone={C.info}
        label="MECH"
        verdict={summary.mech.verdict}
        verdictColor={summary.mech.color}
        sub={summary.mech.sub}
      />
      <Cell
        tone={C.purple}
        label="AGNT"
        verdict={summary.agnt.verdict}
        verdictColor={summary.agnt.color}
        sub={summary.agnt.sub}
      />
      <Cell
        tone={C.brand}
        label="SYNTH"
        verdict={summary.syn.verdict}
        verdictColor={summary.syn.color}
        sub={summary.syn.sub}
      />
    </button>
  );
}

function SymbolCell({ symbol, price }: { symbol: string; price?: number | null }) {
  return (
    <div
      style={{
        padding: '12px 10px',
        borderRight: `1px solid ${C.border}`,
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        gap: 2,
        fontFamily: 'JetBrains Mono, monospace',
      }}
    >
      <span style={{ fontSize: F.md, fontWeight: 700, color: C.text, letterSpacing: -0.3 }}>
        {symbol}
      </span>
      <span style={{ fontSize: F.xs, color: C.muted }}>
        {price != null ? formatPrice(price) : '—'}
      </span>
    </div>
  );
}

function Cell({
  tone,
  label,
  verdict,
  verdictColor,
  sub,
}: {
  tone: string;
  label: string;
  verdict: string;
  verdictColor: string;
  sub: string;
}) {
  return (
    <div
      style={{
        padding: '10px 12px',
        borderRight: `1px solid ${C.border}`,
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        fontFamily: 'JetBrains Mono, monospace',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
        <span style={{ fontSize: 9, fontWeight: 700, color: tone, letterSpacing: 0.06 }}>
          {label}
        </span>
        <span style={{ fontSize: F.sm, fontWeight: 700, color: verdictColor }}>{verdict}</span>
      </div>
      <span style={{ fontSize: 10, color: C.textSub, lineHeight: 1.4 }}>{sub}</span>
    </div>
  );
}

// ── Summary computation ──────────────────────────────────────────────────────

type CellSummary = { verdict: string; color: string; sub: string };

function summarize(sig: Sig | null, llm: LlmDecision | null): {
  mech: CellSummary;
  agnt: CellSummary;
  syn: CellSummary;
  borderTone: string;
} {
  // Mechanical
  const mechSide = directional(sig?.side, sig?.action);
  const mechConf = pctOrNull(sig?.confidence);
  const mech: CellSummary = mechSide === 'flat'
    ? { verdict: 'FLAT', color: C.muted, sub: 'no signal' }
    : {
        verdict: mechSide.toUpperCase(),
        color: mechSide === 'long' ? C.bull : C.bear,
        sub: mechConf != null ? `${mechConf}% confluence` : 'active',
      };

  // Agentic
  const agentSide = directional(llm?.side, llm?.action);
  const agentConf = pctOrNull(llm?.confidence);
  const agentActive = agentSide !== 'flat' && llm?.allowed !== false && !llm?.is_veto;
  const agnt: CellSummary = llm?.is_veto
    ? { verdict: 'VETOED', color: C.purple, sub: 'critic stopped trade' }
    : !llm?.allowed
    ? { verdict: 'BLOCKED', color: C.bear, sub: 'gate denied' }
    : !agentActive
    ? { verdict: 'FLAT', color: C.muted, sub: 'no thesis' }
    : {
        verdict: agentSide.toUpperCase(),
        color: agentSide === 'long' ? C.bull : C.bear,
        sub: agentConf != null ? `${agentConf}% conviction` : 'active',
      };

  // Synthesis
  const mechActive = mechSide !== 'flat';
  let dis: 'aligned' | 'mixed' | 'opposed';
  if (mechSide === agentSide && mechActive) dis = 'aligned';
  else if ((mechActive && !agentActive) || (!mechActive && agentActive)) dis = 'mixed';
  else if (mechSide !== agentSide && mechActive && agentActive) dis = 'opposed';
  else dis = 'aligned';

  const sizingPenalty = dis === 'aligned' ? 1.0 : dis === 'mixed' ? 0.7 : 0.3;
  const meanConf = ((mechConf ?? 0) + (agentConf ?? 0)) / 2;
  const sized = Math.round(meanConf * sizingPenalty);

  const synSide: 'long' | 'short' | 'flat' =
    dis === 'opposed'
      ? 'flat'
      : mechActive
      ? mechSide
      : agentActive
      ? agentSide
      : 'flat';

  const syn: CellSummary =
    dis === 'opposed'
      ? { verdict: 'OPPOSED', color: C.bear, sub: 'systems disagree — stand down' }
      : synSide === 'flat'
      ? { verdict: 'FLAT', color: C.muted, sub: 'wait' }
      : {
          verdict: synSide.toUpperCase(),
          color: synSide === 'long' ? C.bull : C.bear,
          sub: `${dis} · sized ${sized}%`,
        };

  const borderTone =
    dis === 'opposed'
      ? C.bear
      : dis === 'aligned' && synSide !== 'flat'
      ? C.bull
      : dis === 'mixed'
      ? C.warn
      : C.border;

  return { mech, agnt, syn, borderTone };
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

function pctOrNull(c: number | null | undefined): number | null {
  if (c == null) return null;
  return Math.round(c > 1 ? c : c * 100);
}

function formatPrice(p: number): string {
  if (p > 1000) return p.toLocaleString('en-US', { maximumFractionDigits: 2 });
  if (p > 1) return p.toFixed(2);
  return p.toPrecision(4);
}
