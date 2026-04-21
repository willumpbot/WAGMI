'use client';

import React, { useMemo } from 'react';
import { C, fmtPct } from '../../src/theme';

type Trade = {
  symbol?: string;
  timestamp?: string;
  pnl?: number | null;
  outcome?: string;
};

export interface PerformanceHeatmapProps {
  trades: Trade[];
  /** Minimum trades per cell before it's colored (below this it's gray). */
  minTradesPerCell?: number;
}

/**
 * Win-rate heatmap grid: rows = symbol, columns = hour-of-day (UTC).
 * Computed entirely client-side from the trade history list.
 * Gray cell = insufficient samples.
 */
export default function PerformanceHeatmap({ trades, minTradesPerCell = 2 }: PerformanceHeatmapProps) {
  const { symbols, matrix } = useMemo(() => {
    const bySymHour: Record<string, Record<number, { wins: number; total: number }>> = {};
    const symSet = new Set<string>();

    for (const t of trades || []) {
      const sym = t.symbol?.trim();
      const ts = t.timestamp;
      if (!sym || !ts) continue;
      let hour: number;
      try {
        const d = new Date(ts);
        if (isNaN(d.getTime())) continue;
        hour = d.getUTCHours();
      } catch {
        continue;
      }
      symSet.add(sym);
      if (!bySymHour[sym]) bySymHour[sym] = {};
      if (!bySymHour[sym][hour]) bySymHour[sym][hour] = { wins: 0, total: 0 };
      bySymHour[sym][hour].total += 1;
      const isWin = t.outcome === 'WIN' || ((t.pnl ?? 0) > 0);
      if (isWin) bySymHour[sym][hour].wins += 1;
    }

    const symbols = Array.from(symSet).sort();
    const matrix = symbols.map((sym) =>
      Array.from({ length: 24 }, (_, h) => {
        const cell = bySymHour[sym]?.[h];
        if (!cell || cell.total === 0) return { wr: null as number | null, total: 0 };
        return { wr: (cell.wins / cell.total) * 100, total: cell.total };
      }),
    );

    return { symbols, matrix };
  }, [trades]);

  if (symbols.length === 0) {
    return (
      <div
        style={{
          padding: 24,
          background: 'rgba(13,13,20,0.7)',
          border: '1px solid rgba(255,255,255,0.05)',
          borderRadius: 12,
          color: C.muted,
          fontSize: 13,
          textAlign: 'center',
        }}
      >
        Not enough trade history yet to build a WR heatmap.
      </div>
    );
  }

  function cellColor(wr: number | null, total: number): { bg: string; border: string } {
    if (wr == null || total < minTradesPerCell) {
      return { bg: 'rgba(255,255,255,0.025)', border: 'rgba(255,255,255,0.04)' };
    }
    // Center around 50% WR. Above = green intensity, below = red intensity.
    const delta = Math.max(-50, Math.min(50, wr - 50));
    const intensity = Math.abs(delta) / 50;
    if (delta >= 0) {
      return {
        bg: `rgba(0,204,136,${0.08 + intensity * 0.55})`,
        border: `rgba(0,204,136,${0.15 + intensity * 0.4})`,
      };
    }
    return {
      bg: `rgba(255,68,102,${0.08 + intensity * 0.55})`,
      border: `rgba(255,68,102,${0.15 + intensity * 0.4})`,
    };
  }

  return (
    <div
      style={{
        padding: 18,
        background: 'rgba(13,13,20,0.7)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        border: '1px solid rgba(255,255,255,0.05)',
        borderRadius: 12,
        overflowX: 'auto',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 14,
          flexWrap: 'wrap',
          gap: 8,
        }}
      >
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, letterSpacing: -0.2 }}>
            WR Heatmap · Symbol × Hour (UTC)
          </div>
          <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>
            {trades.length} trades · min {minTradesPerCell} per cell to color
          </div>
        </div>

        {/* Legend */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 10, color: C.muted, fontWeight: 700 }}>WR</span>
          <div style={{ width: 10, height: 10, borderRadius: 2, background: 'rgba(255,68,102,0.55)' }} />
          <span style={{ fontSize: 10, color: C.muted }}>0%</span>
          <div style={{ width: 10, height: 10, borderRadius: 2, background: 'rgba(255,255,255,0.08)' }} />
          <span style={{ fontSize: 10, color: C.muted }}>50%</span>
          <div style={{ width: 10, height: 10, borderRadius: 2, background: 'rgba(0,204,136,0.6)' }} />
          <span style={{ fontSize: 10, color: C.muted }}>100%</span>
        </div>
      </div>

      {/* Grid */}
      <div style={{ minWidth: 540 }}>
        {/* Column header — hours */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: `44px repeat(24, minmax(18px, 1fr))`,
            gap: 2,
            marginBottom: 4,
          }}
        >
          <div />
          {Array.from({ length: 24 }, (_, h) => (
            <div
              key={h}
              style={{
                fontSize: 9,
                textAlign: 'center',
                color: h % 6 === 0 ? C.textSub : C.muted,
                fontWeight: h % 6 === 0 ? 700 : 500,
                fontFamily: 'JetBrains Mono, monospace',
              }}
            >
              {String(h).padStart(2, '0')}
            </div>
          ))}
        </div>

        {/* Rows */}
        {symbols.map((sym, i) => (
          <div
            key={sym}
            style={{
              display: 'grid',
              gridTemplateColumns: `44px repeat(24, minmax(18px, 1fr))`,
              gap: 2,
              marginBottom: 2,
            }}
          >
            <div
              className="num"
              style={{
                fontSize: 11,
                fontWeight: 700,
                color: C.textSub,
                fontFamily: 'JetBrains Mono, monospace',
                display: 'flex',
                alignItems: 'center',
              }}
            >
              {sym}
            </div>
            {matrix[i].map((cell, h) => {
              const palette = cellColor(cell.wr, cell.total);
              const tooltip =
                cell.total === 0
                  ? `${sym} @ ${h}:00 UTC · no trades`
                  : `${sym} @ ${h}:00 UTC · WR ${fmtPct(cell.wr ?? 0, 0)} · n=${cell.total}`;
              return (
                <div
                  key={h}
                  title={tooltip}
                  style={{
                    height: 22,
                    background: palette.bg,
                    border: `1px solid ${palette.border}`,
                    borderRadius: 3,
                    cursor: 'help',
                    transition: 'transform 0.12s ease',
                  }}
                  onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.transform = 'scale(1.25)'; }}
                  onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.transform = 'scale(1)'; }}
                />
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
