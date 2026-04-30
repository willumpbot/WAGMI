'use client';

import React from 'react';
import { C, F, R } from '../../src/theme';
import type { EdgeStats } from './useEdgeStats';

/**
 * CohortStrip — surfaces the time-of-day cohort behavior for the current hour.
 * Sits below the regime calibration strip on /trade.
 *
 * Why this exists: meta_learning insights show 56-pt WR spread between morning
 * (06-12 UTC, 67-71% WR) and night (00-06 UTC, 9-15% WR). The trade page
 * should surface this *as the operator is about to trade*, not bury it in
 * an analytics page.
 */

export default function CohortStrip({ stats }: { stats: EdgeStats }) {
  const nowUtc = new Date().getUTCHours();
  const hourStat = stats.byHourUtc[nowUtc];
  const cohort = labelCohort(nowUtc);
  const cohortBucket = aggregateCohort(stats, cohort);

  if (!hourStat && !cohortBucket) {
    // Don't render until we have data
    return null;
  }

  const wr = cohortBucket?.winRate ?? hourStat?.winRate;
  const n = cohortBucket?.trades ?? hourStat?.trades ?? 0;
  const tone =
    wr == null ? C.muted : wr >= 0.55 ? C.bull : wr >= 0.42 ? C.warn : C.bear;

  return (
    <div
      style={{
        height: 28,
        marginTop: 6,
        background: '#0a0a0f',
        border: `1px solid ${C.border}`,
        borderRadius: R.sm,
        padding: '0 12px',
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        fontSize: F.xs,
        color: C.textSub,
        fontFamily: 'JetBrains Mono, monospace',
      }}
    >
      <span style={{ color: C.muted }}>now {pad2(nowUtc)}:00 UTC</span>
      <span style={{ color: C.faint }}>·</span>
      <span>
        cohort:{' '}
        <span style={{ color: C.text, fontWeight: 600 }}>{cohort}</span>{' '}
        <span style={{ color: C.muted }}>({nowUtc}-{(nowUtc + 6) % 24}h)</span>
      </span>
      <span style={{ color: C.faint }}>·</span>
      <span>
        historical WR:{' '}
        <span style={{ color: tone, fontWeight: 600 }}>
          {wr != null ? `${(wr * 100).toFixed(0)}%` : '—'}
        </span>
        <span style={{ color: C.muted, marginLeft: 4 }}>(n={n})</span>
      </span>
      {wr != null && wr < 0.35 && n >= 10 && (
        <>
          <span style={{ color: C.faint }}>·</span>
          <span style={{ color: C.bear, fontWeight: 600 }}>caution: weak hour</span>
        </>
      )}
      {wr != null && wr >= 0.6 && n >= 10 && (
        <>
          <span style={{ color: C.faint }}>·</span>
          <span style={{ color: C.bull, fontWeight: 600 }}>strong hour</span>
        </>
      )}
    </div>
  );
}

function pad2(n: number): string {
  return n.toString().padStart(2, '0');
}

function labelCohort(hourUtc: number): string {
  if (hourUtc >= 6 && hourUtc < 12) return 'MORNING';
  if (hourUtc >= 12 && hourUtc < 18) return 'AFTERNOON';
  if (hourUtc >= 18 || hourUtc < 0) return 'EVENING';
  return 'NIGHT';
}

function aggregateCohort(stats: EdgeStats, cohort: string) {
  const ranges: Record<string, [number, number]> = {
    MORNING: [6, 12],
    AFTERNOON: [12, 18],
    EVENING: [18, 24],
    NIGHT: [0, 6],
  };
  const [start, end] = ranges[cohort] || [0, 24];
  let trades = 0;
  let wins = 0;
  let pnl = 0;
  for (let h = start; h < end; h++) {
    const s = stats.byHourUtc[h];
    if (!s) continue;
    trades += s.trades;
    wins += s.wins;
    pnl += s.pnl;
  }
  if (trades === 0) return null;
  return {
    trades,
    wins,
    pnl,
    winRate: wins / trades,
    avgPnl: pnl / trades,
  };
}
