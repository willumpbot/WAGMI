import React, { useMemo } from 'react';
import { C } from '../src/theme';
import { useApi } from '../hooks/useApi';

type Trade = {
  timestamp?: string;
  symbol: string;
  side: string;
  pnl?: number;
  outcome?: string;
};

type TradeHistory = { trades: Trade[]; total?: number };

/**
 * Horizontal ticker of recent trades. Continuously scrolls via CSS animation.
 * Gives any page immediate "this is alive" energy.
 *
 * Shows: SYMBOL · SIDE · PnL · outcome.
 * Refresh every 30s. If no data, renders nothing (graceful degradation).
 */
export default function LiveActivityTape() {
  const { data } = useApi<TradeHistory>('/v1/trades/history?limit=30', { refreshInterval: 30_000 });
  const trades: Trade[] = data?.trades ?? [];

  const items = useMemo(() => trades.slice(-20).reverse(), [trades]);

  if (items.length === 0) return null;

  // Duplicate the list so the scroll wraps seamlessly.
  const doubled = [...items, ...items];

  return (
    <div
      style={{
        width: '100%',
        overflow: 'hidden',
        background: 'rgba(13,13,20,0.6)',
        borderTop: `1px solid ${C.border}`,
        borderBottom: `1px solid ${C.border}`,
        position: 'relative',
        height: 36,
      }}
      aria-label="Recent trading activity"
    >
      {/* Edge fades */}
      <div style={{
        position: 'absolute', top: 0, left: 0, bottom: 0, width: 60,
        background: 'linear-gradient(to right, #050508, transparent)',
        pointerEvents: 'none', zIndex: 2,
      }} />
      <div style={{
        position: 'absolute', top: 0, right: 0, bottom: 0, width: 60,
        background: 'linear-gradient(to left, #050508, transparent)',
        pointerEvents: 'none', zIndex: 2,
      }} />

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 28,
          padding: '0 16px',
          height: '100%',
          whiteSpace: 'nowrap',
          animation: 'tape-scroll 55s linear infinite',
          willChange: 'transform',
        }}
      >
        {doubled.map((t, i) => {
          const pnl = t.pnl ?? 0;
          const isWin = pnl > 0;
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 12 }}>
              <span style={{
                fontFamily: 'JetBrains Mono, monospace',
                fontWeight: 700,
                color: C.text,
                letterSpacing: 0.5,
              }}>
                {t.symbol}
              </span>
              <span style={{
                fontSize: 10,
                padding: '2px 6px',
                borderRadius: 4,
                background: t.side === 'BUY' ? C.bullLight : C.bearLight,
                color: t.side === 'BUY' ? C.bull : C.bear,
                fontWeight: 700,
                letterSpacing: 0.5,
              }}>
                {t.side}
              </span>
              <span style={{
                fontFamily: 'JetBrains Mono, monospace',
                fontWeight: 700,
                color: isWin ? C.bull : C.bear,
                fontSize: 12,
              }}>
                {isWin ? '+' : ''}${pnl.toFixed(2)}
              </span>
              <span style={{ fontSize: 11, color: C.muted, fontWeight: 500 }}>
                {t.outcome || (isWin ? 'WIN' : 'LOSS')}
              </span>
              <span style={{ color: C.faint, fontSize: 10, userSelect: 'none' }}>·</span>
            </div>
          );
        })}
      </div>

      <style>{`
        @keyframes tape-scroll {
          from { transform: translateX(0); }
          to { transform: translateX(-50%); }
        }
      `}</style>
    </div>
  );
}
