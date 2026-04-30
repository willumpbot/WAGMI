'use client';

import { useEffect, useState } from 'react';
import { resolveApiBase } from '../../src/api';

/**
 * useEdgeStats — fetches trade history and computes per-(symbol, side) and
 * per-hour-of-day aggregates. The "knowledge layer" of /trade.
 *
 * One fetch on mount + every 60s. Pulls /v1/trades/history?limit=500 so we
 * have enough sample for stable WR per pattern.
 */

export type SideStats = {
  trades: number;
  wins: number;
  pnl: number;
  winRate: number; // 0..1
  avgPnl: number;
};

export type EdgeStats = {
  bySymbolSide: Record<string, SideStats>; // key: "SYMBOL_SIDE" e.g. "SOL_LONG"
  byHourUtc: Record<number, SideStats>;    // 0..23
  totalTrades: number;
  loadedAt: number | null;
};

const empty: EdgeStats = {
  bySymbolSide: {},
  byHourUtc: {},
  totalTrades: 0,
  loadedAt: null,
};

type RawTrade = {
  symbol?: string;
  side?: string;
  pnl?: number;
  outcome?: string;
  timestamp?: string;
  entry_time?: string;
  close_time?: string;
};

export function useEdgeStats(): EdgeStats {
  const [stats, setStats] = useState<EdgeStats>(empty);

  useEffect(() => {
    let cancelled = false;
    const apiBase = resolveApiBase();

    const load = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/trades/history?limit=500`, { cache: 'no-store' });
        if (!res.ok) return;
        const j = await res.json();
        const trades: RawTrade[] = j.trades || [];
        const next = compute(trades);
        if (!cancelled) setStats(next);
      } catch {
        // silent
      }
    };
    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return stats;
}

function compute(trades: RawTrade[]): EdgeStats {
  const bySymbolSide: Record<string, SideStats> = {};
  const byHourUtc: Record<number, SideStats> = {};
  for (const t of trades) {
    const sym = (t.symbol || '').toUpperCase();
    const side = normalizeSide(t.side);
    if (!sym || !side) continue;
    const pnl = Number(t.pnl) || 0;
    const win = pnl > 0;

    const k = `${sym}_${side}`;
    const ss = (bySymbolSide[k] ||= { trades: 0, wins: 0, pnl: 0, winRate: 0, avgPnl: 0 });
    ss.trades += 1;
    if (win) ss.wins += 1;
    ss.pnl += pnl;

    const ts = t.close_time || t.entry_time || t.timestamp;
    if (ts) {
      const d = new Date(ts);
      if (!isNaN(d.getTime())) {
        const h = d.getUTCHours();
        const hs = (byHourUtc[h] ||= { trades: 0, wins: 0, pnl: 0, winRate: 0, avgPnl: 0 });
        hs.trades += 1;
        if (win) hs.wins += 1;
        hs.pnl += pnl;
      }
    }
  }
  for (const k in bySymbolSide) {
    const s = bySymbolSide[k];
    s.winRate = s.trades > 0 ? s.wins / s.trades : 0;
    s.avgPnl = s.trades > 0 ? s.pnl / s.trades : 0;
  }
  for (const h in byHourUtc) {
    const s = byHourUtc[Number(h)];
    s.winRate = s.trades > 0 ? s.wins / s.trades : 0;
    s.avgPnl = s.trades > 0 ? s.pnl / s.trades : 0;
  }
  return {
    bySymbolSide,
    byHourUtc,
    totalTrades: trades.length,
    loadedAt: Date.now(),
  };
}

function normalizeSide(s: string | undefined): 'LONG' | 'SHORT' | null {
  if (!s) return null;
  const u = s.toUpperCase();
  if (u === 'LONG' || u === 'BUY') return 'LONG';
  if (u === 'SHORT' || u === 'SELL') return 'SHORT';
  return null;
}
