'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { C, F, R } from '../src/theme';
import { resolveApiBase } from '../src/api';

/**
 * BotStatusPill — at-a-glance "is the bot alive" indicator for the top nav.
 * Polls /health + the most recent decision timestamp every 15s. Shows:
 *   • green + "LIVE"        — API up, decision in last 15 min
 *   • amber + "STALE Xh"    — API up but no decision recently
 *   • red   + "OFFLINE"     — API not responding
 *
 * Hover for a tooltip with last decision timestamp.
 */

type Status = 'live' | 'stale' | 'offline' | 'loading';

export default function BotStatusPill({ compact = false }: { compact?: boolean }) {
  const [status, setStatus] = useState<Status>('loading');
  const [lastDecision, setLastDecision] = useState<Date | null>(null);
  const [staleHours, setStaleHours] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const apiBase = resolveApiBase();

    const load = async () => {
      try {
        const [healthRes, feedRes] = await Promise.all([
          fetch(`${apiBase}/health`, { cache: 'no-store' }),
          fetch(`${apiBase}/v1/llm/feed?limit=1`, { cache: 'no-store' }),
        ]);
        if (cancelled) return;

        if (!healthRes.ok) {
          setStatus('offline');
          setLastDecision(null);
          setStaleHours(null);
          return;
        }

        if (feedRes.ok) {
          const j = await feedRes.json();
          const d = (j.decisions || [])[0];
          const tsStr = d?.timestamp || d?.ts;
          if (tsStr) {
            const ts = new Date(tsStr);
            if (!isNaN(ts.getTime())) {
              const ageMs = Date.now() - ts.getTime();
              const ageH = ageMs / 3.6e6;
              setLastDecision(ts);
              if (ageMs < 15 * 60 * 1000) {
                setStatus('live');
                setStaleHours(null);
              } else {
                setStatus('stale');
                setStaleHours(ageH);
              }
              return;
            }
          }
          // API up but no decisions at all
          setStatus('stale');
          setLastDecision(null);
          setStaleHours(null);
        } else {
          setStatus('stale');
        }
      } catch {
        if (!cancelled) {
          setStatus('offline');
          setLastDecision(null);
        }
      }
    };
    load();
    const id = setInterval(load, 15_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const cfg: Record<Status, { dot: string; label: string }> = {
    live: { dot: C.bull, label: 'LIVE' },
    stale: {
      dot: C.warn,
      label: staleHours != null ? `STALE ${formatStale(staleHours)}` : 'STALE',
    },
    offline: { dot: C.bear, label: 'OFFLINE' },
    loading: { dot: C.muted, label: '…' },
  };
  const c = cfg[status];

  const tooltip = lastDecision
    ? `Last decision: ${lastDecision.toLocaleString()}`
    : status === 'offline'
    ? 'API not responding on /health'
    : 'No decisions logged yet';

  return (
    <Link
      href="/status"
      title={tooltip + ' — click for full status'}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: compact ? '2px 8px' : '4px 10px',
        background: '#050508',
        border: `1px solid ${C.border}`,
        borderRadius: R.pill,
        fontSize: 10,
        fontWeight: 700,
        color: c.dot,
        fontFamily: 'JetBrains Mono, monospace',
        letterSpacing: 0.04,
        textDecoration: 'none',
        cursor: 'pointer',
        transition: 'border-color 120ms ease-out',
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLAnchorElement).style.borderColor = c.dot + '88';
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLAnchorElement).style.borderColor = C.border;
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: c.dot,
          boxShadow: status === 'live' ? `0 0 6px ${c.dot}` : 'none',
        }}
      />
      {c.label}
    </Link>
  );
}

function formatStale(hours: number): string {
  if (hours < 1) return `${Math.round(hours * 60)}m`;
  if (hours < 24) return `${Math.round(hours)}h`;
  return `${Math.round(hours / 24)}d`;
}
