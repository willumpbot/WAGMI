'use client';

import React from 'react';
import { C, F } from '../../src/theme';

/**
 * EdgeBadge — compact verdict tag for a (symbol, side) pair.
 * Encodes WAGMI's accumulated knowledge from historical trades:
 *   ✅ Edge — winning pattern, take it
 *   🟢 Viable — break-even-ish, OK to trade
 *   ⚠ Weak — losing more than winning, be careful
 *   🛑 Avoid — statistically destroyed equity, WAGMI blocks these
 *
 * Tone is kept neutral (no emojis); just colored text + label.
 * Color/label derived from win rate × sample size × net P&L.
 */

export type EdgeVerdict = 'edge' | 'viable' | 'weak' | 'avoid' | 'unknown';

export function classifyEdge(
  winRate: number | null,
  sampleSize: number,
  netPnl: number | null,
): EdgeVerdict {
  if (sampleSize < 5 || winRate == null || netPnl == null) return 'unknown';
  if (winRate >= 0.55 && netPnl > 0) return 'edge';
  if (winRate >= 0.42 && netPnl > -1) return 'viable';
  if (sampleSize >= 30 && winRate < 0.35 && netPnl < -10) return 'avoid';
  if (winRate < 0.40 || netPnl < -1) return 'weak';
  return 'viable';
}

export default function EdgeBadge({
  verdict,
  size = 'sm',
}: {
  verdict: EdgeVerdict;
  size?: 'xs' | 'sm';
}) {
  const cfg: Record<EdgeVerdict, { label: string; color: string }> = {
    edge: { label: 'EDGE', color: C.bull },
    viable: { label: 'OK', color: C.textSub },
    weak: { label: 'WEAK', color: C.warn },
    avoid: { label: 'AVOID', color: C.bear },
    unknown: { label: '—', color: C.muted },
  };
  const c = cfg[verdict];
  const fontSize = size === 'xs' ? 9 : F.xs;
  return (
    <span
      style={{
        display: 'inline-block',
        padding: size === 'xs' ? '1px 4px' : '2px 6px',
        fontSize,
        fontWeight: 700,
        color: c.color,
        border: `1px solid ${c.color}55`,
        borderRadius: 3,
        letterSpacing: 0.04,
        fontFamily: 'JetBrains Mono, monospace',
        lineHeight: 1.2,
      }}
    >
      {c.label}
    </span>
  );
}
