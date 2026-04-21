import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { C } from '../src/theme';
import { useApi } from '../hooks/useApi';

type Health = { ok?: boolean; ts?: number };

type Summary = {
  equity?: number;
  total_trades?: number;
  today_trades?: number;
};

function formatClock(d: Date): string {
  const hh = d.getHours().toString().padStart(2, '0');
  const mm = d.getMinutes().toString().padStart(2, '0');
  const ss = d.getSeconds().toString().padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

/**
 * Compact system-status badge for page footers. Shows:
 *   - live dot (green = API up, amber = polling, red = offline)
 *   - "API up" / "API offline" label
 *   - last-checked timestamp
 *   - link to docs
 *
 * Uses /health (lightweight) + /v1/summary (proxy for bot activity) — both existing.
 */
export default function SystemStatus() {
  const { data: health, error: healthErr } = useApi<Health>('/health', { refreshInterval: 30_000 });
  const { data: summary } = useApi<Summary>('/v1/summary', { refreshInterval: 60_000 });

  const [now, setNow] = useState<Date>(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);

  const apiUp = !!(health?.ok && !healthErr);
  const botActive = apiUp && (summary?.total_trades ?? 0) > 0;

  const dotColor = apiUp ? (botActive ? C.bull : C.warn) : C.bear;
  const label = apiUp ? (botActive ? 'All systems online' : 'API up · no trades yet') : 'API offline';

  return (
    <div
      className="system-status"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 14,
        flexWrap: 'wrap',
        padding: '8px 12px',
        background: 'rgba(13,13,20,0.6)',
        border: '1px solid rgba(255,255,255,0.05)',
        borderRadius: 8,
        fontSize: 11,
        color: C.muted,
        fontFamily: 'JetBrains Mono, monospace',
        letterSpacing: 0.3,
      }}
    >
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
        <span
          className="status-dot"
          style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            background: dotColor,
            boxShadow: `0 0 8px ${dotColor}80`,
            flexShrink: 0,
          }}
        />
        <span style={{ color: C.textSub, fontWeight: 600 }}>{label}</span>
      </span>
      <span style={{ color: C.faint }}>·</span>
      <span>Updated {formatClock(now)}</span>
      <span style={{ color: C.faint }}>·</span>
      <Link
        href="/agent-intelligence"
        style={{
          color: C.brand,
          textDecoration: 'none',
          fontWeight: 600,
        }}
        onMouseEnter={(e) => ((e.currentTarget as HTMLAnchorElement).style.opacity = '0.8')}
        onMouseLeave={(e) => ((e.currentTarget as HTMLAnchorElement).style.opacity = '1')}
      >
        Architecture →
      </Link>
      <style jsx>{`
        .system-status .status-dot {
          animation: status-pulse 2.2s ease-in-out infinite;
        }
        @keyframes status-pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  );
}
