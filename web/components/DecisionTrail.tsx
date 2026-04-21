'use client';

/**
 * DecisionTrail — slide-over panel showing the full 9-agent reasoning chain
 * for a single trade, plus "what the bot learned" from the Learning agent.
 *
 * Pulls /v1/trade/{id}/trail which matches the trade to the nearest decision pipeline.
 */
import React, { useEffect } from 'react';
import { C, F, R, Z, fmtUsd, fmtPct, timeAgo } from '../src/theme';
import AgentChain, { AgentStep } from './AgentChain';
import { Skeleton } from './ui/Skeleton';
import { useApi } from '../hooks/useApi';

export type TradeBrief = {
  id: string;
  timestamp: string;
  symbol: string;
  side: string;
  entry: number;
  exit: number;
  pnl: number;
  leverage?: number;
  strategy?: string;
};

type TrailResponse = {
  trade: Record<string, any>;
  pipeline_id: string | null;
  time_delta_sec: number | null;
  agents: AgentStep[];
  lesson: string | null;
  error?: string;
};

export default function DecisionTrail({
  trade,
  open,
  onClose,
}: {
  trade: TradeBrief | null;
  open: boolean;
  onClose: () => void;
}) {
  const tradeId = trade?.id || trade?.timestamp || '';
  // Only fetch when the panel is open and we have an id. useApi always needs
  // a string — guard with an unreachable path so SWR stays idle.
  const path = open && tradeId ? `/v1/trade/${encodeURIComponent(tradeId)}/trail` : '';
  const { data, isLoading } = useApi<TrailResponse>(path, { refreshInterval: 0 });

  // Esc to close
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  // Lock body scroll while open
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  if (!open || !trade) return null;

  const win = trade.pnl > 0;
  const sideCol = (trade.side || '').toUpperCase() === 'BUY' ? C.bull : C.bear;

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: 'fixed',
          inset: 0,
          background: 'rgba(5,5,8,0.75)',
          backdropFilter: 'blur(4px)',
          WebkitBackdropFilter: 'blur(4px)',
          zIndex: Z.modal - 1,
          animation: 'fadeIn 0.15s ease',
        }}
      />

      {/* Panel */}
      <div
        role="dialog"
        aria-modal="true"
        style={{
          position: 'fixed',
          top: 0,
          right: 0,
          bottom: 0,
          width: 'min(560px, 100%)',
          background: C.surface,
          borderLeft: `1px solid ${C.border}`,
          zIndex: Z.modal,
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '-8px 0 32px rgba(0,0,0,0.7)',
          animation: 'slideIn 0.2s ease',
        }}
      >
        <style>{`
          @keyframes slideIn { from { transform: translateX(24px); opacity: 0; } to { transform: translateX(0); opacity: 1; } }
          @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
        `}</style>

        {/* Header */}
        <div
          style={{
            padding: '16px 20px',
            borderBottom: `1px solid ${C.border}`,
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            flexShrink: 0,
          }}
        >
          <div>
            <div
              style={{
                fontSize: F.xs,
                color: C.muted,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: 0.5,
              }}
            >
              Decision trail
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
              <span
                style={{
                  fontSize: F.lg,
                  fontWeight: 800,
                  color: C.text,
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                {trade.symbol}
              </span>
              <span
                style={{
                  fontSize: F.xs,
                  fontWeight: 700,
                  padding: '1px 8px',
                  borderRadius: R.pill,
                  background: `${sideCol}22`,
                  color: sideCol,
                }}
              >
                {trade.side}
              </span>
              <span
                className="num"
                style={{
                  fontSize: F.md,
                  fontWeight: 800,
                  color: win ? C.bull : C.bear,
                  fontFamily: "'JetBrains Mono', monospace",
                  marginLeft: 8,
                }}
              >
                {fmtUsd(trade.pnl)}
              </span>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              marginLeft: 'auto',
              background: 'none',
              border: `1px solid ${C.border}`,
              color: C.textSub,
              borderRadius: R.sm,
              padding: '4px 10px',
              fontSize: F.sm,
              cursor: 'pointer',
            }}
            aria-label="Close"
          >
            Esc
          </button>
        </div>

        {/* Scroll body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 20 }}>
          {/* Trade summary */}
          <div
            style={{
              padding: 12,
              background: C.card,
              border: `1px solid ${C.border}`,
              borderRadius: R.md,
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))',
              gap: 10,
              marginBottom: 20,
            }}
          >
            <SumCell label="Entry" value={fmtUsd(trade.entry, trade.entry < 10 ? 4 : 2)} />
            <SumCell label="Exit" value={fmtUsd(trade.exit, trade.exit < 10 ? 4 : 2)} />
            <SumCell
              label="PnL"
              value={fmtUsd(trade.pnl)}
              color={win ? C.bull : C.bear}
            />
            {trade.leverage != null && (
              <SumCell label="Leverage" value={`${trade.leverage.toFixed(1)}x`} />
            )}
            {trade.strategy && <SumCell label="Strategy" value={trade.strategy} />}
            <SumCell label="Time" value={timeAgo(trade.timestamp)} />
          </div>

          {/* Agent chain */}
          <div style={{ marginBottom: 20 }}>
            <h3
              style={{
                margin: '0 0 10px',
                fontSize: F.sm,
                fontWeight: 800,
                color: C.text,
                textTransform: 'uppercase',
                letterSpacing: 0.6,
              }}
            >
              Agent reasoning chain
            </h3>
            {isLoading && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <Skeleton h={52} />
                <Skeleton h={52} />
                <Skeleton h={52} />
              </div>
            )}
            {!isLoading && data && data.agents.length > 0 && (
              <AgentChain agents={data.agents} symbol={trade.symbol} compact />
            )}
            {!isLoading && (!data || data.agents.length === 0) && (
              <div
                style={{
                  padding: 14,
                  border: `1px dashed ${C.border}`,
                  borderRadius: R.md,
                  fontSize: F.sm,
                  color: C.muted,
                  textAlign: 'center',
                }}
              >
                No agent records within 4h of this trade. LLM may have been dormant at entry time.
              </div>
            )}
          </div>

          {/* Lesson */}
          <div>
            <h3
              style={{
                margin: '0 0 10px',
                fontSize: F.sm,
                fontWeight: 800,
                color: C.text,
                textTransform: 'uppercase',
                letterSpacing: 0.6,
              }}
            >
              What the bot learned
            </h3>
            <div
              style={{
                padding: 14,
                background: C.card,
                border: `1px solid ${C.border}`,
                borderRadius: R.md,
                fontSize: F.sm,
                color: data?.lesson ? C.textSub : C.muted,
                lineHeight: 1.6,
                fontStyle: data?.lesson ? 'normal' : 'italic',
              }}
            >
              {isLoading
                ? <Skeleton h={60} />
                : data?.lesson || 'No Learning agent note captured for this trade yet.'}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

function SumCell({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div
        style={{
          fontSize: F.xs,
          color: C.muted,
          fontWeight: 700,
          textTransform: 'uppercase',
          letterSpacing: 0.5,
        }}
      >
        {label}
      </div>
      <div
        className="num"
        style={{
          fontSize: F.sm,
          fontWeight: 700,
          color: color || C.text,
          fontFamily: "'JetBrains Mono', monospace",
          marginTop: 2,
        }}
      >
        {value}
      </div>
    </div>
  );
}
