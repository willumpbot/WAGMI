'use client';

import React, { useEffect, useState } from 'react';
import { C, F } from '../../src/theme';
import { resolveApiBase } from '../../src/api';
import ColumnShell, { Section, Stat, Empty } from './ColumnShell';

/**
 * AgenticColumn — the LLM agent pipeline's view.
 * Pulls from /v1/llm/feed (latest decision for symbol).
 *
 * Renders the agent ladder: Regime → Trade → Risk → Critic, each with
 * action, confidence, one-line reasoning, and per-agent calibration.
 */

type LlmDecision = {
  id?: string;
  symbol?: string;
  action?: string | null;
  side?: string | null;
  confidence?: number | null;
  regime?: string | null;
  notes?: string | null;
  thesis?: string | null;
  is_veto?: boolean | null;
  allowed?: boolean | null;
  model?: string | null;
  cost_usd?: number | null;
  agents?: Array<{
    role: string;
    action?: string;
    confidence?: number;
    reasoning?: string;
    model?: string;
  }>;
  timestamp?: string;
};

type LlmFeedResponse = {
  decisions?: LlmDecision[];
};

const AGENT_ORDER = ['regime', 'trade', 'risk', 'critic'] as const;
type AgentRole = typeof AGENT_ORDER[number];

const AGENT_LABEL: Record<AgentRole, string> = {
  regime: 'Regime Agent',
  trade: 'Trade Agent',
  risk: 'Risk Agent',
  critic: 'Critic Agent',
};

export default function AgenticColumn({
  symbol,
  mode,
  replayTimestamp,
}: {
  symbol: string;
  mode: 'live' | 'replay';
  replayTimestamp?: string;
}) {
  const [decision, setDecision] = useState<LlmDecision | null>(null);

  useEffect(() => {
    if (mode !== 'live') return;
    let cancelled = false;
    const apiBase = resolveApiBase();
    const load = async () => {
      try {
        const r = await fetch(`${apiBase}/v1/llm/feed?limit=50`, { cache: 'no-store' });
        if (!r.ok) return;
        const j: LlmFeedResponse = await r.json();
        const latest = (j.decisions || []).find((d) => (d.symbol || '').toUpperCase() === symbol);
        if (!cancelled) setDecision(latest || null);
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
  }, [symbol, mode]);

  // Derive verdict
  const verdictLabel = decision?.is_veto
    ? 'VETOED'
    : !decision?.allowed
    ? 'BLOCKED'
    : !decision?.action
    ? '—'
    : decision.action.toUpperCase() === 'PROCEED' || decision.action.toUpperCase() === 'GO'
    ? decision.side === 'SHORT' || decision.side === 'SELL'
      ? 'SHORT'
      : 'LONG'
    : decision.action.toUpperCase();

  const verdictColor = decision?.is_veto
    ? C.purple
    : !decision?.allowed
    ? C.bear
    : verdictLabel === 'LONG'
    ? C.bull
    : verdictLabel === 'SHORT'
    ? C.bear
    : C.muted;

  const conf =
    decision?.confidence != null
      ? Math.round(decision.confidence > 1 ? decision.confidence : decision.confidence * 100)
      : null;

  const agentsByRole: Record<string, LlmDecision['agents'] extends (infer T)[] | undefined ? T : never> = {};
  for (const a of decision?.agents || []) {
    agentsByRole[a.role.toLowerCase()] = a;
  }

  return (
    <ColumnShell
      tone="agentic"
      verdict={{ label: verdictLabel, color: verdictColor }}
    >
      {/* Top-level pipeline summary */}
      <Section title="Pipeline" hint={decision?.timestamp ? new Date(decision.timestamp).toLocaleTimeString() : 'no recent decision'}>
        <Stat
          label="action"
          value={decision?.action ? decision.action.toUpperCase() : '—'}
          tone={verdictColor}
        />
        <Stat
          label="confidence"
          value={conf != null ? `${conf}%` : '—'}
          tone={conf != null && conf >= 75 ? C.bull : conf != null && conf >= 60 ? C.warn : C.muted}
        />
        <Stat
          label="regime call"
          value={decision?.regime?.toUpperCase() || '—'}
        />
        <Stat
          label="cost"
          value={decision?.cost_usd != null ? `$${decision.cost_usd.toFixed(4)}` : '—'}
          tone={C.faint}
        />
      </Section>

      {/* Agent ladder */}
      <Section title="Agent Ladder">
        {AGENT_ORDER.map((role) => {
          const a = agentsByRole[role];
          return <AgentRow key={role} role={role} agent={a} />;
        })}
      </Section>

      {/* Thesis */}
      {decision?.thesis && (
        <Section title="Thesis">
          <p
            style={{
              margin: 0,
              fontSize: F.xs,
              color: C.textSub,
              lineHeight: 1.5,
            }}
          >
            {decision.thesis}
          </p>
        </Section>
      )}

      {/* Notes — surfaces vetoes & overrides */}
      {decision?.notes && (
        <Section title="Notes">
          <p
            style={{
              margin: 0,
              fontSize: F.xs,
              color: C.textSub,
              lineHeight: 1.5,
              fontFamily: 'JetBrains Mono, monospace',
            }}
          >
            {decision.notes}
          </p>
        </Section>
      )}

      {!decision && (
        <Section title="Status">
          <Empty note={`No recent agent decisions on ${symbol}.`} />
        </Section>
      )}

      {/* AI-only verdict footer */}
      <Section title="AI-only Verdict" hint="if mechanical off">
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
            from agent pipeline only — no rule gates applied
          </span>
        </div>
      </Section>
    </ColumnShell>
  );
}

function AgentRow({
  role,
  agent,
}: {
  role: AgentRole;
  agent: { role: string; action?: string; confidence?: number; reasoning?: string; model?: string } | undefined;
}) {
  const conf =
    agent?.confidence != null
      ? Math.round(agent.confidence > 1 ? agent.confidence : agent.confidence * 100)
      : null;
  return (
    <div
      style={{
        padding: '6px 0',
        borderBottom: `1px dashed ${C.border}`,
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontSize: F.xs,
          fontFamily: 'JetBrains Mono, monospace',
        }}
      >
        <span style={{ color: C.text, fontWeight: 600 }}>{AGENT_LABEL[role]}</span>
        <span style={{ color: agent?.action ? C.text : C.muted }}>
          {agent?.action ? agent.action.toUpperCase() : '—'}
          {conf != null && <span style={{ marginLeft: 6, color: C.muted }}>{conf}%</span>}
        </span>
      </div>
      {agent?.reasoning && (
        <span
          style={{
            fontSize: 10,
            color: C.textSub,
            lineHeight: 1.4,
            marginTop: 2,
          }}
        >
          {truncate(agent.reasoning, 140)}
        </span>
      )}
      {agent?.model && (
        <span style={{ fontSize: 9, color: C.faint, fontFamily: 'JetBrains Mono, monospace' }}>
          {modelLabel(agent.model)}
        </span>
      )}
    </div>
  );
}

function truncate(s: string, max: number): string {
  if (s.length <= max) return s;
  return s.slice(0, max).trimEnd() + '…';
}

function modelLabel(model: string): string {
  const m = model.toLowerCase();
  if (m.includes('opus')) return 'Opus';
  if (m.includes('sonnet')) return 'Sonnet';
  if (m.includes('haiku')) return 'Haiku';
  return model;
}
