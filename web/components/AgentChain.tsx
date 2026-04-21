'use client';

import React, { useState } from 'react';
import { C, F, R } from '../src/theme';
import { Badge } from './ui/Badge';

export type AgentStep = {
  role: string;
  decision?: string | null;
  confidence?: number | null;
  reasoning_summary?: string | null;
  model_used?: string | null;
  model_class?: 'haiku' | 'sonnet' | 'opus' | 'unknown' | string;
  latency_ms?: number | null;
  record_id?: string | null;
};

const AGENT_LABEL: Record<string, string> = {
  regime: 'Regime',
  trade: 'Trade',
  risk: 'Risk',
  critic: 'Critic',
  learning: 'Learning',
  exit: 'Exit',
  scout: 'Scout',
  overseer: 'Overseer',
  quant: 'Quant',
};

const AGENT_SUBTITLE: Record<string, string> = {
  regime: 'Market classification',
  trade: 'Directional thesis',
  risk: 'Position sizing',
  critic: 'Stress test + veto',
  learning: 'Post-trade lessons',
  exit: 'Open position review',
  scout: 'Idle watchlists',
  overseer: 'System health',
  quant: 'Statistical edge',
};

function modelBadgeVariant(cls?: string) {
  if (cls === 'opus') return 'brand';
  if (cls === 'sonnet') return 'info';
  if (cls === 'haiku') return 'muted';
  return 'muted';
}

function decisionColor(decision?: string | null): { bg: string; color: string } {
  const d = (decision || '').toLowerCase();
  if (['proceed', 'go', 'enter'].includes(d)) return { bg: C.bullMuted, color: C.bull };
  if (['skip', 'flat', 'veto', 'hold'].includes(d)) return { bg: C.warnMuted, color: C.warn };
  if (['flip', 'reverse', 'close'].includes(d)) return { bg: C.bearMuted, color: C.bear };
  return { bg: 'rgba(255,255,255,0.04)', color: C.muted };
}

function formatConfidence(c?: number | null): string {
  if (c == null) return '—';
  // Handle both 0-1 and 0-100 scales
  const pct = c > 1 ? c : c * 100;
  return `${pct.toFixed(0)}%`;
}

export default function AgentChain({
  agents,
  symbol,
  compact = false,
}: {
  agents: AgentStep[];
  symbol?: string;
  compact?: boolean;
}) {
  const [expanded, setExpanded] = useState<number | null>(null);

  if (!agents || agents.length === 0) {
    return (
      <div
        style={{
          padding: 16,
          fontSize: F.sm,
          color: C.muted,
          textAlign: 'center',
          border: `1px dashed ${C.border}`,
          borderRadius: R.md,
        }}
      >
        No agent records for this pipeline.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: compact ? 6 : 10 }}>
      {agents.map((a, i) => {
        const label = AGENT_LABEL[a.role] || a.role.toUpperCase();
        const sub = AGENT_SUBTITLE[a.role] || '';
        const isOpen = expanded === i;
        const decColor = decisionColor(a.decision);
        const modelClass = a.model_class || 'unknown';

        return (
          <div key={`${a.record_id || i}`} style={{ position: 'relative' }}>
            {/* Connector line */}
            {i < agents.length - 1 && (
              <div
                aria-hidden
                style={{
                  position: 'absolute',
                  left: 19,
                  top: compact ? 30 : 38,
                  bottom: -10,
                  width: 2,
                  background: `linear-gradient(180deg, ${C.border} 0%, rgba(0,204,136,0.2) 100%)`,
                  zIndex: 0,
                }}
              />
            )}

            <div
              onClick={() => setExpanded(isOpen ? null : i)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') setExpanded(isOpen ? null : i);
              }}
              style={{
                display: 'flex',
                gap: 12,
                alignItems: 'flex-start',
                padding: compact ? '8px 10px' : '12px 14px',
                background: isOpen ? 'rgba(0,204,136,0.04)' : 'rgba(13,13,20,0.7)',
                border: `1px solid ${isOpen ? 'rgba(0,204,136,0.2)' : C.border}`,
                borderRadius: R.md,
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                position: 'relative',
                zIndex: 1,
                backdropFilter: 'blur(6px)',
                WebkitBackdropFilter: 'blur(6px)',
              }}
            >
              {/* Left: agent index bubble */}
              <div
                style={{
                  flexShrink: 0,
                  width: 24,
                  height: 24,
                  borderRadius: '50%',
                  background: decColor.bg,
                  color: decColor.color,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 10,
                  fontWeight: 800,
                  fontFamily: "'JetBrains Mono', monospace",
                  border: `1px solid ${decColor.color}40`,
                }}
              >
                {i + 1}
              </div>

              {/* Middle: content */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    flexWrap: 'wrap',
                    marginBottom: compact ? 2 : 4,
                  }}
                >
                  <span style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>{label}</span>
                  <Badge variant={modelBadgeVariant(modelClass) as any}>{modelClass}</Badge>
                  {a.decision && (
                    <span
                      style={{
                        fontSize: F.xs,
                        fontWeight: 700,
                        padding: '1px 8px',
                        borderRadius: R.pill,
                        background: decColor.bg,
                        color: decColor.color,
                        textTransform: 'uppercase',
                        letterSpacing: 0.5,
                      }}
                    >
                      {a.decision}
                    </span>
                  )}
                  <span
                    className="num"
                    style={{
                      fontSize: F.xs,
                      color: C.muted,
                      fontFamily: "'JetBrains Mono', monospace",
                      marginLeft: 'auto',
                    }}
                  >
                    {formatConfidence(a.confidence)}
                  </span>
                </div>
                {!compact && sub && (
                  <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>{sub}</div>
                )}
                {a.reasoning_summary && (
                  <div
                    style={{
                      fontSize: F.sm,
                      color: C.textSub,
                      lineHeight: 1.5,
                      overflow: 'hidden',
                      display: isOpen ? 'block' : '-webkit-box',
                      WebkitLineClamp: isOpen ? undefined : 1,
                      WebkitBoxOrient: 'vertical' as const,
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {a.reasoning_summary}
                  </div>
                )}

                {isOpen && (
                  <div
                    style={{
                      marginTop: 10,
                      paddingTop: 10,
                      borderTop: `1px solid ${C.border}`,
                      display: 'flex',
                      gap: 16,
                      fontSize: F.xs,
                      color: C.muted,
                      flexWrap: 'wrap',
                    }}
                  >
                    {a.model_used && (
                      <span>
                        Model <span style={{ color: C.textSub }}>{a.model_used}</span>
                      </span>
                    )}
                    {a.latency_ms != null && a.latency_ms > 0 && (
                      <span>
                        Latency <span style={{ color: C.textSub }}>{Math.round(a.latency_ms)}ms</span>
                      </span>
                    )}
                    {a.record_id && (
                      <span>
                        ID <span style={{ color: C.textSub, fontFamily: "'JetBrains Mono', monospace" }}>{a.record_id}</span>
                      </span>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
