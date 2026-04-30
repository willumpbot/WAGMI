'use client';

import React, { useEffect, useState } from 'react';
import { C, F } from '../../src/theme';
import { resolveApiBase } from '../../src/api';
import ColumnShell, { Section, Stat, Empty } from './ColumnShell';
import { useEdgeStats } from '../trade/useEdgeStats';

/**
 * MechanicalColumn — the deterministic pipeline's view.
 * Pulls from /v1/signals (live) or /v1/decisions/{id} (replay).
 * Phase 4b: wired against /v1/signals + edge stats. Strategy table & gates are
 * placeholders pending /v1/signals/funnel and a future /v1/rules/active endpoint.
 */

type Sig = {
  symbol?: string;
  side?: string | null;
  price?: number | null;
  confidence?: number | null;
  action?: string | null;
  regime?: string | null;
};

export default function MechanicalColumn({
  symbol,
  mode,
  replayTimestamp,
}: {
  symbol: string;
  mode: 'live' | 'replay';
  replayTimestamp?: string;
}) {
  const [sig, setSig] = useState<Sig | null>(null);
  const edge = useEdgeStats();

  useEffect(() => {
    if (mode !== 'live') return; // replay wires later
    let cancelled = false;
    const apiBase = resolveApiBase();
    const load = async () => {
      try {
        const r = await fetch(`${apiBase}/v1/signals`, { cache: 'no-store' });
        if (!r.ok) return;
        const j = await r.json();
        if (!cancelled) setSig(j.signals?.[symbol] ?? null);
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

  // Compute "no-LLM" verdict from confluence signals.
  const isLong = sig?.side === 'LONG' || sig?.side === 'BUY';
  const isShort = sig?.side === 'SHORT' || sig?.side === 'SELL';
  const conf = sig?.confidence != null ? Math.round(sig.confidence > 1 ? sig.confidence : sig.confidence * 100) : null;
  const verdictLabel = !sig?.action || sig.action === 'flat' ? 'FLAT' : isLong ? 'LONG' : isShort ? 'SHORT' : 'FLAT';
  const verdictColor = isLong ? C.bull : isShort ? C.bear : C.muted;

  const longEdge = edge.bySymbolSide[`${symbol}_LONG`];
  const shortEdge = edge.bySymbolSide[`${symbol}_SHORT`];
  const nowH = new Date().getUTCHours();
  const todStat = edge.byHourUtc[nowH];

  return (
    <ColumnShell
      tone="mechanical"
      verdict={{ label: verdictLabel, color: verdictColor }}
    >
      {/* Ensemble vote summary */}
      <Section title="Ensemble Vote" hint="weighted veto mode">
        <Stat
          label="action"
          value={sig?.action ? sig.action.toUpperCase() : 'flat'}
          tone={verdictColor}
        />
        <Stat
          label="confidence"
          value={conf != null ? `${conf}%` : '—'}
          tone={conf != null && conf >= 75 ? C.bull : conf != null && conf >= 60 ? C.warn : C.muted}
        />
        <Stat
          label="regime"
          value={sig?.regime?.toUpperCase() || '—'}
          tone={
            sig?.regime === 'trending' ? C.bull : sig?.regime === 'ranging' || sig?.regime === 'illiquid' ? C.warn : C.text
          }
        />
      </Section>

      {/* Strategy table — placeholder; real per-strategy votes via /v1/signals/funnel */}
      <Section title="Strategies (top 5)" hint="placeholder — wires next">
        <Empty note="Per-strategy votes load from /v1/signals/funnel in next commit." />
      </Section>

      {/* Active gates */}
      <Section title="Active Gates">
        <Stat label="confidence floor" value="dynamic" />
        <Stat label="regime block" value={sig?.regime === 'illiquid' || sig?.regime === 'ranging' ? 'ACTIVE' : 'inactive'} tone={sig?.regime === 'illiquid' ? C.warn : C.muted} />
        <Stat label="hard-block rules" value="—" />
        <Stat label="circuit breaker" value="—" />
      </Section>

      {/* Symbol edge map */}
      <Section title={`Edge map — ${symbol}`}>
        <Stat
          label="LONG"
          value={longEdge ? `n=${longEdge.trades} · WR ${(longEdge.winRate * 100).toFixed(0)}% · ${longEdge.pnl >= 0 ? '+' : ''}$${longEdge.pnl.toFixed(0)}` : '—'}
          tone={longEdge ? (longEdge.pnl >= 0 ? C.bull : C.bear) : C.muted}
        />
        <Stat
          label="SHORT"
          value={shortEdge ? `n=${shortEdge.trades} · WR ${(shortEdge.winRate * 100).toFixed(0)}% · ${shortEdge.pnl >= 0 ? '+' : ''}$${shortEdge.pnl.toFixed(0)}` : '—'}
          tone={shortEdge ? (shortEdge.pnl >= 0 ? C.bull : C.bear) : C.muted}
        />
      </Section>

      {/* TOD cohort */}
      <Section title={`Time cohort — now ${pad2(nowH)}:00 UTC`}>
        <Stat
          label="historical WR"
          value={todStat ? `${(todStat.winRate * 100).toFixed(0)}% (n=${todStat.trades})` : '—'}
          tone={todStat ? (todStat.winRate >= 0.5 ? C.bull : todStat.winRate >= 0.4 ? C.warn : C.bear) : C.muted}
        />
      </Section>

      {/* No-LLM verdict footer */}
      <Section title="No-LLM Verdict" hint="if agents off">
        <div
          style={{
            padding: 10,
            background: '#050508',
            border: `1px solid ${C.border}`,
            borderLeft: `3px solid ${verdictColor}`,
            borderRadius: 4,
            fontSize: F.xs,
            color: C.textSub,
            fontFamily: 'JetBrains Mono, monospace',
          }}
        >
          <span style={{ color: verdictColor, fontWeight: 700 }}>{verdictLabel}</span>
          {conf != null && <span style={{ marginLeft: 8, color: C.text }}>{conf}% conf</span>}
          <span style={{ display: 'block', color: C.muted, marginTop: 4, fontSize: 10 }}>
            from ensemble + gates only — no LLM input
          </span>
        </div>
      </Section>
    </ColumnShell>
  );
}

function pad2(n: number) {
  return n.toString().padStart(2, '0');
}
