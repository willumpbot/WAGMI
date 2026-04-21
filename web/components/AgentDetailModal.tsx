import React, { useEffect } from 'react';
import { C } from '../src/theme';
import { useApi } from '../hooks/useApi';
import ScanningEmptyState from './ScanningEmptyState';

type HistoryRecord = {
  agent?: string;
  decision?: string | null;
  ts?: string | number | null;
  timestamp?: string | number | null;
  confidence?: number | null;
  reasoning_summary?: string | null;
  model_used?: string | null;
  symbol?: string | null;
  correct?: boolean | null;
  [key: string]: unknown;
};

type PerformanceResp = {
  agent: string;
  calls: number;
  accuracy: number | null;
  avg_latency_ms: number | null;
  message?: string;
  history: HistoryRecord[];
};

type Props = {
  name: string;
  slug: string;
  model: 'Haiku' | 'Sonnet' | 'Opus';
  color: string;
  purpose: string;
  onClose: () => void;
};

function formatWhen(ts: string | number | null | undefined): string {
  if (ts == null) return '';
  const n = typeof ts === 'number' ? ts : Number(ts);
  let d: Date;
  if (!Number.isNaN(n) && n > 1e9) {
    // Unix seconds or ms
    d = new Date(n < 1e12 ? n * 1000 : n);
  } else if (typeof ts === 'string') {
    d = new Date(ts);
  } else {
    return '';
  }
  if (Number.isNaN(d.getTime())) return '';
  const diffMs = Date.now() - d.getTime();
  const mins = Math.max(0, Math.round(diffMs / 60000));
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  return `${days}d ago`;
}

/**
 * Detail modal for a single agent — shows recent decisions + accuracy.
 * Data source: `/v1/agents/{slug}/performance` (existing endpoint).
 * Silent empty state via ScanningEmptyState when no agent data exists.
 */
export default function AgentDetailModal({ name, slug, model, color, purpose, onClose }: Props) {
  const { data, isLoading } = useApi<PerformanceResp>(`/v1/agents/${slug}/performance`);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  // Prevent body scroll while modal is open
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, []);

  const history = (data?.history ?? []).slice(-8).reverse();
  const calls = data?.calls ?? 0;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`${name} agent details`}
      onClick={onClose}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        background: 'rgba(5,5,8,0.7)',
        backdropFilter: 'blur(6px)',
        WebkitBackdropFilter: 'blur(6px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 16,
        zIndex: 1000,
        animation: 'agent-modal-fade 0.18s ease-out',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 'min(560px, 100%)',
          maxHeight: '86vh',
          overflow: 'auto',
          background: 'linear-gradient(180deg, #0d0d14 0%, #0a0a0f 100%)',
          border: `1px solid ${color}35`,
          borderRadius: 14,
          boxShadow: `0 20px 60px rgba(0,0,0,0.6), 0 0 0 1px ${color}12`,
          animation: 'agent-modal-slide 0.22s ease-out',
        }}
      >
        {/* Header */}
        <div style={{
          padding: '18px 20px',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: 16,
        }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
              <span style={{
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: color,
                boxShadow: `0 0 10px ${color}80`,
                flexShrink: 0,
              }} />
              <h3 style={{
                margin: 0,
                fontSize: 18,
                fontWeight: 800,
                color: C.text,
                letterSpacing: -0.3,
              }}>
                {name} Agent
              </h3>
              <span style={{
                fontSize: 10,
                fontWeight: 700,
                padding: '2px 7px',
                borderRadius: 4,
                background: `${color}18`,
                color,
                textTransform: 'uppercase',
                letterSpacing: 0.5,
                fontFamily: 'JetBrains Mono, monospace',
              }}>
                {model}
              </span>
            </div>
            <div style={{ fontSize: 12, color: C.textSub, lineHeight: 1.5 }}>
              {purpose}
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              width: 32,
              height: 32,
              borderRadius: 8,
              background: 'transparent',
              border: '1px solid rgba(255,255,255,0.08)',
              color: C.muted,
              cursor: 'pointer',
              fontSize: 16,
              lineHeight: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
            onMouseEnter={(e) => {
              (e.currentTarget as HTMLButtonElement).style.color = C.text;
              (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255,255,255,0.2)';
            }}
            onMouseLeave={(e) => {
              (e.currentTarget as HTMLButtonElement).style.color = C.muted;
              (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255,255,255,0.08)';
            }}
          >
            ✕
          </button>
        </div>

        {/* Stats row */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
          gap: 1,
          background: 'rgba(255,255,255,0.04)',
          borderBottom: '1px solid rgba(255,255,255,0.04)',
        }}>
          {[
            { label: 'Recent calls', value: String(calls) },
            { label: 'Accuracy', value: data?.accuracy != null ? `${(data.accuracy * 100).toFixed(0)}%` : '—' },
            { label: 'Avg latency', value: data?.avg_latency_ms != null ? `${Math.round(data.avg_latency_ms)}ms` : '—' },
          ].map((it) => (
            <div
              key={it.label}
              style={{
                background: '#0d0d14',
                padding: '12px 14px',
              }}
            >
              <div style={{
                fontSize: 10,
                fontWeight: 700,
                color: C.muted,
                textTransform: 'uppercase',
                letterSpacing: 1,
                marginBottom: 4,
              }}>
                {it.label}
              </div>
              <div style={{
                fontSize: 16,
                fontWeight: 700,
                color: C.text,
                fontFamily: 'JetBrains Mono, monospace',
                letterSpacing: -0.3,
              }}>
                {it.value}
              </div>
            </div>
          ))}
        </div>

        {/* Recent decisions */}
        <div style={{ padding: '18px 20px' }}>
          <div style={{
            fontSize: 10,
            fontWeight: 700,
            color: C.muted,
            textTransform: 'uppercase',
            letterSpacing: 1.2,
            fontFamily: 'JetBrains Mono, monospace',
            marginBottom: 12,
          }}>
            Recent Decisions
          </div>

          {isLoading ? (
            <ScanningEmptyState label="Loading" sub="Fetching recent activity" compact />
          ) : history.length === 0 ? (
            <ScanningEmptyState
              label={data?.message ? 'No logged activity' : 'No decisions yet'}
              sub={data?.message ?? 'This agent hasn\u2019t weighed in recently'}
            />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {history.map((h, i) => {
                const decision = (h.decision || '—').toString();
                const isGo = /proceed|go|yes/i.test(decision);
                const isSkip = /flat|skip|veto|no/i.test(decision);
                const isFlip = /flip|reverse/i.test(decision);
                const decColor = isGo ? C.bull : isSkip ? C.muted : isFlip ? C.warn : C.info;
                const when = formatWhen(h.ts ?? h.timestamp ?? null);
                return (
                  <div
                    key={i}
                    style={{
                      padding: '10px 12px',
                      background: 'rgba(255,255,255,0.02)',
                      border: '1px solid rgba(255,255,255,0.04)',
                      borderRadius: 8,
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
                        {h.symbol && (
                          <span style={{
                            fontSize: 11,
                            fontWeight: 700,
                            color: C.text,
                            fontFamily: 'JetBrains Mono, monospace',
                            letterSpacing: 0.3,
                          }}>
                            {h.symbol}
                          </span>
                        )}
                        <span style={{
                          fontSize: 10,
                          fontWeight: 700,
                          padding: '1px 6px',
                          borderRadius: 4,
                          background: `${decColor}15`,
                          color: decColor,
                          textTransform: 'uppercase',
                          letterSpacing: 0.5,
                        }}>
                          {decision}
                        </span>
                        {h.confidence != null && (
                          <span style={{ fontSize: 10, color: C.muted, fontFamily: 'JetBrains Mono, monospace' }}>
                            conf {Math.round((h.confidence as number) * (h.confidence as number <= 1 ? 100 : 1))}%
                          </span>
                        )}
                      </div>
                      {when && (
                        <span style={{ fontSize: 10, color: C.muted, flexShrink: 0 }}>
                          {when}
                        </span>
                      )}
                    </div>
                    {h.reasoning_summary && (
                      <div style={{
                        fontSize: 11,
                        color: C.textSub,
                        lineHeight: 1.5,
                        display: '-webkit-box',
                        WebkitLineClamp: 2,
                        WebkitBoxOrient: 'vertical',
                        overflow: 'hidden',
                      }}>
                        {h.reasoning_summary}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <style>{`
        @keyframes agent-modal-fade {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes agent-modal-slide {
          from { opacity: 0; transform: translateY(12px) scale(0.98); }
          to { opacity: 1; transform: translateY(0) scale(1); }
        }
      `}</style>
    </div>
  );
}
