'use client';

/**
 * AgentHealthStrip — at-a-glance health dots for all 9 specialist agents.
 * Green = fired in last 24h, amber = stale (fired in last 72h), red = dead.
 *
 * Exposes the Phase-4 finding (dead agents) to the user in real-time.
 */
import React from 'react';
import { C, F, R } from '../src/theme';
import { useApi } from '../hooks/useApi';

type AgentHealth = {
  name: string;
  model_class: string;
  total_calls: number;
  calls_24h: number;
  last_ts: number | null;
  status: 'live' | 'stale' | 'dead';
};

type HealthResponse = {
  agents: AgentHealth[];
  hours: number;
  generated_at: string;
};

const STATUS_COLOR: Record<string, string> = {
  live: C.bull,
  stale: C.warn,
  dead: C.bear,
};

const STATUS_LABEL: Record<string, string> = {
  live: 'LIVE',
  stale: 'STALE',
  dead: 'DEAD',
};

export default function AgentHealthStrip({ compact = false }: { compact?: boolean }) {
  const { data, isLoading } = useApi<HealthResponse>('/v1/agents/health?hours=24', {
    refreshInterval: 60_000,
  });

  if (isLoading && !data) {
    return (
      <div
        style={{
          padding: compact ? '8px 12px' : 12,
          background: C.card,
          border: `1px solid ${C.border}`,
          borderRadius: R.md,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          fontSize: F.xs,
          color: C.muted,
        }}
      >
        Loading agent health…
      </div>
    );
  }

  if (!data || !data.agents) return null;

  const deadCount = data.agents.filter((a) => a.status === 'dead').length;
  const liveCount = data.agents.filter((a) => a.status === 'live').length;

  return (
    <div
      style={{
        padding: compact ? '8px 12px' : 12,
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.md,
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          marginBottom: compact ? 6 : 10,
        }}
      >
        <span
          style={{
            fontSize: F.xs,
            fontWeight: 800,
            color: C.text,
            textTransform: 'uppercase',
            letterSpacing: 0.6,
          }}
        >
          Agent Health
        </span>
        <span style={{ fontSize: F.xs, color: C.muted }}>
          <span style={{ color: C.bull }}>{liveCount}</span> live ·{' '}
          <span style={{ color: deadCount ? C.bear : C.muted }}>{deadCount}</span> dead
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 10, color: C.faint }}>{data.hours}h window</span>
      </div>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${compact ? 9 : 'auto-fill, minmax(90px, 1fr)'}, 1fr)`,
          gap: compact ? 4 : 8,
        }}
      >
        {data.agents.map((a) => {
          const color = STATUS_COLOR[a.status] || C.muted;
          const tip = `${a.name} · ${a.calls_24h} calls/24h · ${a.total_calls} total · ${STATUS_LABEL[a.status]}`;
          return (
            <div
              key={a.name}
              title={tip}
              style={{
                display: 'flex',
                flexDirection: compact ? 'column' : 'row',
                alignItems: 'center',
                gap: compact ? 3 : 8,
                padding: compact ? '6px 4px' : '8px 10px',
                background: 'rgba(255,255,255,0.02)',
                border: `1px solid ${C.border}`,
                borderRadius: R.sm,
                minWidth: 0,
              }}
            >
              <span
                className={a.status === 'live' ? 'live-dot' : undefined}
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: color,
                  boxShadow: a.status === 'live' ? `0 0 6px ${color}` : 'none',
                  flexShrink: 0,
                }}
              />
              <span
                style={{
                  fontSize: compact ? 10 : F.xs,
                  fontWeight: 700,
                  color: a.status === 'dead' ? C.muted : C.textSub,
                  textTransform: 'capitalize',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {a.name}
              </span>
              {!compact && (
                <span
                  className="num"
                  style={{
                    marginLeft: 'auto',
                    fontSize: 10,
                    color: C.muted,
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                >
                  {a.calls_24h}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
