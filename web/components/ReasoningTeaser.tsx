import React from 'react';
import Link from 'next/link';
import { C, timeAgo } from '../src/theme';
import { useApi } from '../hooks/useApi';
import ScanningEmptyState from './ScanningEmptyState';

type AgentRecord = {
  role: string;
  decision?: string | null;
  confidence?: number | null;
  reasoning_summary?: string | null;
  model_used?: string | null;
  model_class?: string | null;
  latency_ms?: number | null;
};

type Pipeline = {
  pipeline_id: string;
  timestamp?: string | number | null;
  symbol: string;
  side: string;
  agents: AgentRecord[];
};

type FeedResponse = { pipelines: Pipeline[]; count: number };

const AGENT_ORDER = ['regime', 'trade', 'risk', 'critic', 'learning', 'exit', 'scout', 'quant', 'overseer'];

const MODEL_COLOR: Record<string, string> = {
  haiku: C.info,
  sonnet: C.brand,
  opus: C.purple,
};

function bestSummary(agents: AgentRecord[]): { role: string; text: string } | null {
  // Prefer Trade (the thesis), then Critic (the counter-thesis), then Regime, then first.
  const priority = ['trade', 'critic', 'regime'];
  for (const want of priority) {
    const a = agents.find((x) => x.role === want && x.reasoning_summary);
    if (a && a.reasoning_summary) return { role: a.role, text: a.reasoning_summary };
  }
  const first = agents.find((x) => x.reasoning_summary);
  if (first && first.reasoning_summary) return { role: first.role, text: first.reasoning_summary };
  return null;
}

/**
 * Compact preview of recent 9-agent deliberations on the public landing page.
 * Shows what the bot is actually thinking — not just trade outcomes.
 * This is the WAGMI moat: JUICE can't show agent reasoning.
 *
 * Click-through goes to `/reasoning` for the full chain viewer.
 * Silent render if no data.
 */
export default function ReasoningTeaser() {
  const { data } = useApi<FeedResponse>('/v1/reasoning/feed?limit=6', { refreshInterval: 45_000 });
  const pipelines: Pipeline[] = (data?.pipelines ?? []).slice(0, 3);

  if (pipelines.length === 0) {
    return (
      <div
        style={{
          padding: '14px 16px',
          background: '#0d0d14',
          border: '1px solid rgba(255,255,255,0.06)',
          borderRadius: 10,
        }}
      >
        <ScanningEmptyState
          label="Waiting for the brain to deliberate"
          sub="9-agent reasoning will stream here as signals arrive"
        />
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
      {pipelines.map((p) => {
        const summary = bestSummary(p.agents);
        const orderedAgents = [...p.agents].sort(
          (a, b) => AGENT_ORDER.indexOf(a.role) - AGENT_ORDER.indexOf(b.role)
        );

        // Decide final pipeline action from Trade agent, fallback Critic, fallback last
        const finalAgent =
          p.agents.find((a) => a.role === 'trade' && a.decision) ||
          p.agents.find((a) => a.role === 'critic' && a.decision) ||
          p.agents[p.agents.length - 1];
        const action = finalAgent?.decision ?? '';
        const actionColor =
          /proceed|go/i.test(action) ? C.bull :
          /flat|skip|veto/i.test(action) ? C.muted :
          /flip|reverse/i.test(action) ? C.warn :
          C.info;

        return (
          <Link
            key={p.pipeline_id}
            href="/reasoning"
            style={{ textDecoration: 'none' }}
          >
            <div
              className="reasoning-card"
              style={{
                padding: 16,
                background: '#0d0d14',
                border: '1px solid rgba(255,255,255,0.06)',
                borderRadius: 10,
                cursor: 'pointer',
                transition: 'transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease',
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              {/* Top: symbol + time + action */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span style={{
                    fontSize: 12,
                    fontWeight: 800,
                    color: C.text,
                    fontFamily: 'JetBrains Mono, monospace',
                    letterSpacing: 0.5,
                  }}>
                    {p.symbol || '—'}
                  </span>
                  {p.side && (
                    <span style={{
                      fontSize: 9,
                      fontWeight: 700,
                      padding: '1px 6px',
                      borderRadius: 4,
                      background: p.side === 'BUY' ? C.bullLight : C.bearLight,
                      color: p.side === 'BUY' ? C.bull : C.bear,
                      letterSpacing: 0.5,
                    }}>
                      {p.side}
                    </span>
                  )}
                </div>
                {action && (
                  <span style={{
                    fontSize: 9,
                    fontWeight: 700,
                    color: actionColor,
                    textTransform: 'uppercase',
                    letterSpacing: 1,
                  }}>
                    {action}
                  </span>
                )}
              </div>

              {/* Agent chain dots */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 12, flexWrap: 'wrap' }}>
                {orderedAgents.map((a, i) => {
                  const mc = (a.model_class || '').toLowerCase();
                  const color = MODEL_COLOR[mc] || C.muted;
                  return (
                    <div
                      key={`${p.pipeline_id}-${a.role}-${i}`}
                      title={`${a.role}: ${a.decision || '?'} (${a.model_used || '?'})`}
                      style={{ display: 'flex', alignItems: 'center', gap: 3 }}
                    >
                      <div style={{
                        width: 7,
                        height: 7,
                        borderRadius: '50%',
                        background: color,
                        opacity: 0.8,
                        flexShrink: 0,
                      }} />
                      <span style={{
                        fontSize: 9,
                        color: C.muted,
                        textTransform: 'uppercase',
                        letterSpacing: 0.5,
                        fontFamily: 'JetBrains Mono, monospace',
                      }}>
                        {a.role.slice(0, 3)}
                      </span>
                      {i < orderedAgents.length - 1 && (
                        <span style={{ color: C.faint, fontSize: 8, marginLeft: 1 }}>→</span>
                      )}
                    </div>
                  );
                })}
              </div>

              {/* Reasoning excerpt */}
              {summary ? (
                <div style={{ flex: 1 }}>
                  <div style={{
                    fontSize: 9,
                    fontWeight: 700,
                    color: C.muted,
                    textTransform: 'uppercase',
                    letterSpacing: 0.8,
                    marginBottom: 4,
                  }}>
                    {summary.role} agent
                  </div>
                  <div style={{
                    fontSize: 12,
                    color: C.textSub,
                    lineHeight: 1.5,
                    display: '-webkit-box',
                    WebkitLineClamp: 3,
                    WebkitBoxOrient: 'vertical',
                    overflow: 'hidden',
                  }}>
                    {summary.text}
                  </div>
                </div>
              ) : (
                <div style={{ flex: 1, fontSize: 11, color: C.muted, fontStyle: 'italic' }}>
                  No reasoning summary available.
                </div>
              )}

              {/* Bottom row: timestamp + see more */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 10, paddingTop: 8, borderTop: '1px solid rgba(255,255,255,0.04)' }}>
                <span style={{ fontSize: 10, color: C.muted }}>
                  {timeAgo(p.timestamp) || 'recent'}
                </span>
                <span style={{ fontSize: 10, color: C.brand, fontWeight: 600 }}>
                  Full chain →
                </span>
              </div>
            </div>
          </Link>
        );
      })}
      <style jsx>{`
        .reasoning-card:hover {
          transform: translateY(-2px);
          border-color: rgba(255, 255, 255, 0.14) !important;
          box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(0, 204, 136, 0.1);
        }
      `}</style>
    </div>
  );
}
