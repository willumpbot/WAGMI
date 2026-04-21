'use client';

/**
 * /reasoning — The Agent Reasoning Viewer
 *
 * WAGMI native differentiator: the 9-agent specialist brain in full view.
 * Every decision cycle shows Regime -> Trade -> Risk -> Critic -> ... with
 * model badges, confidence, and expandable reasoning.
 *
 * Pulls /v1/reasoning/feed (grouped pipelines from decisions.jsonl).
 */
import React, { useMemo, useState } from 'react';
import Head from 'next/head';
import Layout from '../components/Layout';
import AgentChain, { AgentStep } from '../components/AgentChain';
import { C, F, R, G, timeAgo } from '../src/theme';
import { Skeleton } from '../components/ui/Skeleton';
import { Badge } from '../components/ui/Badge';
import { useApi } from '../hooks/useApi';

type Pipeline = {
  pipeline_id: string;
  timestamp: number | null;
  symbol: string;
  side: string;
  agents: AgentStep[];
};

type FeedResponse = {
  pipelines: Pipeline[];
  count: number;
};

type Outcome = 'all' | 'won' | 'lost';

function fmtPipelineTs(ts: number | null | undefined) {
  if (!ts) return '';
  try {
    return new Date(ts * 1000).toISOString().slice(0, 19).replace('T', ' ') + ' UTC';
  } catch {
    return '';
  }
}

function pipelineOutcome(p: Pipeline): 'won' | 'lost' | 'neutral' {
  const trade = p.agents.find((a) => a.role === 'trade');
  if (!trade) return 'neutral';
  const d = (trade.decision || '').toLowerCase();
  if (d === 'proceed' || d === 'go') return 'won';
  if (d === 'skip' || d === 'flat' || d === 'veto') return 'lost';
  return 'neutral';
}

export default function ReasoningPage() {
  const [symbolFilter, setSymbolFilter] = useState<string>('');
  const [outcomeFilter, setOutcomeFilter] = useState<Outcome>('all');

  const qs = useMemo(() => {
    const parts: string[] = ['limit=60'];
    if (symbolFilter) parts.push(`symbol=${encodeURIComponent(symbolFilter)}`);
    return parts.join('&');
  }, [symbolFilter]);

  const { data, isLoading, error } = useApi<FeedResponse>(
    `/v1/reasoning/feed?${qs}`,
    { refreshInterval: 45_000 },
  );

  const filtered = useMemo(() => {
    if (!data?.pipelines) return [];
    if (outcomeFilter === 'all') return data.pipelines;
    return data.pipelines.filter((p) => pipelineOutcome(p) === outcomeFilter);
  }, [data, outcomeFilter]);

  const symbols = useMemo(() => {
    const set = new Set<string>();
    (data?.pipelines || []).forEach((p) => p.symbol && set.add(p.symbol));
    return Array.from(set).sort();
  }, [data]);

  return (
    <Layout>
      <Head>
        <title>Agent Reasoning · WAGMI</title>
      </Head>

      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
          <h1 style={{ margin: 0, fontSize: F['2xl'], fontWeight: 800, color: C.text, letterSpacing: -0.4 }}>
            Agent Reasoning
          </h1>
          <span style={{ fontSize: F.sm, color: C.muted }}>
            9-agent chain · every decision, transparently
          </span>
        </div>
        <p style={{ fontSize: F.sm, color: C.textSub, margin: '8px 0 0', maxWidth: 680, lineHeight: 1.5 }}>
          WAGMI routes every signal through a sequential pipeline of specialist LLM agents. Regime classifies the market,
          Trade forms a thesis, Risk sizes, Critic stress-tests it, and Learning/Exit/Scout/Overseer/Quant add post-trade
          wisdom. Click any agent to see the full reasoning.
        </p>
      </div>

      {/* Filters */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
          marginBottom: 20,
          padding: 12,
          background: C.card,
          border: `1px solid ${C.border}`,
          borderRadius: R.md,
        }}
      >
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: F.xs, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.5 }}>
            Symbol
          </span>
          <select
            value={symbolFilter}
            onChange={(e) => setSymbolFilter(e.target.value)}
            style={{
              padding: '4px 8px',
              background: C.surface,
              border: `1px solid ${C.border}`,
              borderRadius: R.sm,
              color: C.text,
              fontSize: F.sm,
              outline: 'none',
            }}
          >
            <option value="">All</option>
            {symbols.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: F.xs, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 0.5 }}>
            Outcome
          </span>
          {(['all', 'won', 'lost'] as Outcome[]).map((o) => (
            <button
              key={o}
              onClick={() => setOutcomeFilter(o)}
              style={{
                padding: '4px 10px',
                background: outcomeFilter === o ? C.brandMuted : C.surface,
                border: `1px solid ${outcomeFilter === o ? C.brand : C.border}`,
                borderRadius: R.sm,
                color: outcomeFilter === o ? C.brand : C.textSub,
                fontSize: F.xs,
                fontWeight: 700,
                cursor: 'pointer',
                textTransform: 'capitalize',
              }}
            >
              {o === 'won' ? 'Proceeded' : o === 'lost' ? 'Skipped' : 'All'}
            </button>
          ))}
        </div>

        <div style={{ marginLeft: 'auto', fontSize: F.xs, color: C.muted, fontFamily: "'JetBrains Mono', monospace" }}>
          {isLoading ? 'Loading…' : `${filtered.length} pipelines`}
        </div>
      </div>

      {/* Loading state */}
      {isLoading && !data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {[0, 1, 2].map((k) => (
            <div key={k} style={{ padding: 20, background: C.card, borderRadius: R.md, border: `1px solid ${C.border}` }}>
              <Skeleton h={18} w="40%" />
              <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
                <Skeleton h={40} />
                <Skeleton h={40} />
                <Skeleton h={40} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Error state */}
      {error && !data && (
        <div
          style={{
            padding: 20,
            background: C.card,
            border: `1px solid ${C.border}`,
            borderRadius: R.md,
            color: C.muted,
            fontSize: F.sm,
            textAlign: 'center',
          }}
        >
          Could not load reasoning feed. Is the API server running?
        </div>
      )}

      {/* Empty state */}
      {data && filtered.length === 0 && (
        <div
          style={{
            padding: 40,
            background: C.card,
            border: `1px dashed ${C.border}`,
            borderRadius: R.md,
            color: C.muted,
            fontSize: F.sm,
            textAlign: 'center',
          }}
        >
          No pipelines match these filters. The LLM brain may be dormant or API errors may have suppressed
          recent records.
        </div>
      )}

      {/* Pipelines */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        {filtered.map((p) => {
          const outcome = pipelineOutcome(p);
          const sideColor =
            p.side?.toUpperCase() === 'BUY' || p.side?.toUpperCase() === 'LONG'
              ? C.bull
              : p.side?.toUpperCase() === 'SELL' || p.side?.toUpperCase() === 'SHORT'
                ? C.bear
                : C.muted;

          return (
            <div
              key={p.pipeline_id}
              style={{
                padding: 20,
                background: G.card,
                border: `1px solid ${C.border}`,
                borderRadius: R.lg,
                boxShadow: '0 4px 16px rgba(0,0,0,0.35)',
              }}
            >
              {/* Pipeline header */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  flexWrap: 'wrap',
                  marginBottom: 14,
                  paddingBottom: 12,
                  borderBottom: `1px solid ${C.border}`,
                }}
              >
                {p.symbol && (
                  <span
                    style={{
                      fontSize: F.lg,
                      fontWeight: 800,
                      color: C.text,
                      letterSpacing: -0.3,
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  >
                    {p.symbol}
                  </span>
                )}
                {p.side && (
                  <span
                    style={{
                      fontSize: F.xs,
                      fontWeight: 700,
                      padding: '2px 10px',
                      borderRadius: R.pill,
                      background: `${sideColor}22`,
                      color: sideColor,
                      textTransform: 'uppercase',
                      letterSpacing: 0.6,
                    }}
                  >
                    {p.side}
                  </span>
                )}
                {outcome !== 'neutral' && (
                  <Badge variant={outcome === 'won' ? 'bull' : 'warn'}>
                    {outcome === 'won' ? 'PROCEEDED' : 'SKIPPED'}
                  </Badge>
                )}
                <span style={{ marginLeft: 'auto', fontSize: F.xs, color: C.muted }}>
                  {timeAgo(p.timestamp ? p.timestamp * 1000 : null) || fmtPipelineTs(p.timestamp)}
                </span>
                <span style={{ fontSize: F.xs, color: C.faint, fontFamily: "'JetBrains Mono', monospace" }}>
                  {p.pipeline_id}
                </span>
              </div>

              {/* Agent chain */}
              <AgentChain agents={p.agents} symbol={p.symbol} />
            </div>
          );
        })}
      </div>
    </Layout>
  );
}
