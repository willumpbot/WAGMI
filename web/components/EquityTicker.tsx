'use client';

import React, { useEffect, useRef, useState } from 'react';
import { C, fmtUsd } from '../src/theme';
import { useApi } from '../hooks/useApi';
import { StatusDot } from './ui/StatusDot';

type SummaryResponse = {
  equity: number;
  peak_equity?: number;
  total_trades?: number;
  win_rate?: number;
  total_pnl?: number;
  open_positions?: number;
  today_pnl?: number;
  today_trades?: number;
};

/**
 * Persistent equity ticker rendered at the top of every page.
 * Shows: equity, today's PnL (color-coded + arrow), open positions count.
 * Pulls /v1/summary every 10s. Glass morphism card with a subtle glow on PnL change.
 * Mobile-first: collapses to equity + PnL only at narrow widths.
 */
export default function EquityTicker({ compact = false }: { compact?: boolean }) {
  const { data, error } = useApi<SummaryResponse>('/v1/summary', { refreshInterval: 10_000 });
  const [glow, setGlow] = useState<'bull' | 'bear' | null>(null);
  const lastPnlRef = useRef<number | null>(null);

  // Trigger a brief glow when today's PnL changes.
  useEffect(() => {
    const pnl = data?.today_pnl;
    if (pnl == null) return;
    const last = lastPnlRef.current;
    if (last != null && last !== pnl) {
      setGlow(pnl >= last ? 'bull' : 'bear');
      const t = setTimeout(() => setGlow(null), 1200);
      return () => clearTimeout(t);
    }
    lastPnlRef.current = pnl;
  }, [data?.today_pnl]);

  const kind: 'live' | 'stale' | 'error' = error ? 'error' : data ? 'live' : 'stale';

  const equity = data?.equity;
  const todayPnl = data?.today_pnl;
  const openCount = data?.open_positions ?? 0;

  const pnlColor =
    todayPnl == null ? C.muted : todayPnl > 0 ? C.bull : todayPnl < 0 ? C.bear : C.textSub;

  const glowShadow =
    glow === 'bull'
      ? '0 0 20px rgba(0,204,136,0.22)'
      : glow === 'bear'
      ? '0 0 20px rgba(255,68,102,0.22)'
      : 'none';

  const arrow = todayPnl == null ? '' : todayPnl > 0 ? '▲' : todayPnl < 0 ? '▼' : '—';

  return (
    <div
      role="status"
      aria-label="Live portfolio status"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: compact ? '6px 10px' : '8px 14px',
        background: 'rgba(13,13,20,0.7)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        border: '1px solid rgba(255,255,255,0.05)',
        borderRadius: 999,
        boxShadow: glowShadow,
        transition: 'box-shadow 0.4s ease',
        flexWrap: 'nowrap',
        minWidth: 0,
      }}
    >
      <StatusDot kind={kind} size={6} title={kind === 'live' ? 'API live' : kind === 'error' ? 'API offline' : 'Connecting…'} />

      {/* Equity */}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, minWidth: 0 }}>
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: C.muted,
            letterSpacing: 0.8,
            textTransform: 'uppercase',
          }}
        >
          Equity
        </span>
        <span
          className="num"
          style={{
            fontSize: 14,
            fontWeight: 700,
            color: C.text,
            fontFamily: 'JetBrains Mono, monospace',
            letterSpacing: -0.3,
            whiteSpace: 'nowrap',
          }}
        >
          {equity != null ? fmtUsd(equity) : '—'}
        </span>
      </div>

      {/* PnL */}
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 4,
          paddingLeft: 10,
          marginLeft: 2,
          borderLeft: '1px solid rgba(255,255,255,0.06)',
          minWidth: 0,
        }}
      >
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: C.muted,
            letterSpacing: 0.8,
            textTransform: 'uppercase',
          }}
        >
          Today
        </span>
        <span
          className="num"
          style={{
            fontSize: 13,
            fontWeight: 700,
            color: pnlColor,
            fontFamily: 'JetBrains Mono, monospace',
            letterSpacing: -0.2,
            whiteSpace: 'nowrap',
          }}
        >
          {arrow} {todayPnl != null ? fmtUsd(todayPnl) : '—'}
        </span>
      </div>

      {/* Open positions */}
      {!compact && (
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 5,
            paddingLeft: 10,
            marginLeft: 2,
            borderLeft: '1px solid rgba(255,255,255,0.06)',
          }}
        >
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              color: C.muted,
              letterSpacing: 0.8,
              textTransform: 'uppercase',
            }}
          >
            Open
          </span>
          <span
            className="num"
            style={{
              fontSize: 13,
              fontWeight: 700,
              color: openCount > 0 ? C.info : C.textSub,
              fontFamily: 'JetBrains Mono, monospace',
            }}
          >
            {openCount}
          </span>
        </div>
      )}
    </div>
  );
}
