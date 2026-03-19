import React, { useEffect, useState } from 'react';
import { useRouter } from 'next/router';
import { C, R, S, F, fmtUsd, fmtPct, timeAgo } from '../../src/theme';
import type { TradeRecord } from '../../src/types';

// ─── Types ───────────────────────────────────────────────────────────────────

type LogEntry = {
  ts: string;
  event: string;
  details?: Record<string, any>;
};

type LatestSignal = {
  label: string;
  score: number;
  market: string;
  price: number;
  trend: { sma20: 'Up' | 'Down'; sma50: 'Up' | 'Down'; rsi14: number };
  zones: { deepAccum: number; accum: number; distrib: number; safeDistrib: number };
};

type StrategyCard = {
  id: string;
  name: string;
  status: string;
  lastEvaluated: string;
  latestSignal: LatestSignal | null;
  lastHeartbeat?: string;
  last_seen?: string;
  pnl_realized?: number;
  pnl?: number;
  open_position?: {
    side?: string;
    size?: number;
    avg_entry?: number;
    unrealized_pnl?: number;
  } | null;
};

type Tab = 'signals' | 'trades' | 'performance' | 'logs';

// ─── Helpers ─────────────────────────────────────────────────────────────────

function resolveApiBase(): string {
  const envVal =
    (process.env.NEXT_PUBLIC_API_URL as string | undefined) ||
    (process.env.NEXT_PUBLIC_API_BASE_URL as string | undefined);
  if (envVal && envVal.trim().length > 0) return envVal;
  if (typeof window !== 'undefined') {
    const host = window.location.hostname;
    if (host && host !== 'localhost' && host !== '127.0.0.1') {
      return 'https://nunuirl-platform.onrender.com';
    }
  }
  return 'http://localhost:8000';
}

const fmt = (v: any, digits = 2) => {
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n.toFixed(digits) : '—';
};

function eventColor(event: string): string {
  const e = event.toLowerCase();
  if (e.includes('trade') || e.includes('fill') || e.includes('open') || e.includes('close')) return '#6366f1';
  if (e.includes('signal') || e.includes('buy') || e.includes('long')) return '#16a34a';
  if (e.includes('sell') || e.includes('short') || e.includes('exit')) return '#dc2626';
  if (e.includes('error') || e.includes('fail')) return '#dc2626';
  if (e.includes('warn')) return '#eab308';
  return '#64748b';
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function ZoneRuler({ sig }: { sig: LatestSignal }) {
  const { deepAccum, accum, distrib, safeDistrib } = sig.zones;
  const current = sig.price;

  // Build a safe price range with fallback padding
  const allPrices = [deepAccum, accum, current, distrib, safeDistrib].filter(Number.isFinite);
  if (allPrices.length < 2) return null;
  const rawMin = Math.min(...allPrices);
  const rawMax = Math.max(...allPrices);
  const pad = (rawMax - rawMin) * 0.08 || rawMin * 0.02;
  const domainMin = rawMin - pad;
  const domainMax = rawMax + pad;
  const domainRange = domainMax - domainMin || 1;

  const W = 600; // SVG viewBox width
  const H = 90;
  const BAR_Y = 34;
  const BAR_H = 18;

  const px = (price: number) => ((price - domainMin) / domainRange) * W;

  const xDeepAccum = px(deepAccum);
  const xAccum = px(accum);
  const xCurrent = px(current);
  const xDistrib = px(distrib);
  const xSafeDistrib = px(safeDistrib);

  const pctLabel = (price: number) => {
    const diff = ((price - current) / current) * 100;
    return (diff >= 0 ? '+' : '') + diff.toFixed(1) + '%';
  };

  // Format price compactly
  const fmtP = (v: number) => {
    if (v >= 10000) return '$' + Math.round(v).toLocaleString();
    if (v >= 100) return '$' + v.toFixed(0);
    return '$' + v.toFixed(2);
  };

  const ticks = [
    { x: xDeepAccum, color: '#16a34a', label: 'Deep Accum', pct: pctLabel(deepAccum), fmtVal: fmtP(deepAccum) },
    { x: xAccum, color: '#22c55e', label: 'Accum', pct: pctLabel(accum), fmtVal: fmtP(accum) },
    { x: xDistrib, color: '#f97316', label: 'Distrib', pct: pctLabel(distrib), fmtVal: fmtP(distrib) },
    { x: xSafeDistrib, color: '#dc2626', label: 'Safe Distrib', pct: pctLabel(safeDistrib), fmtVal: fmtP(safeDistrib) },
  ];

  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '14px 18px 10px' }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 10 }}>Price Zone Ruler</div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
        aria-label="Price zone ruler"
      >
        <defs>
          <linearGradient id="zoneGradLeft" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#16a34a" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#22c55e" stopOpacity="0.35" />
          </linearGradient>
          <linearGradient id="zoneGradRight" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#f97316" stopOpacity="0.35" />
            <stop offset="100%" stopColor="#dc2626" stopOpacity="0.55" />
          </linearGradient>
        </defs>

        {/* Base track */}
        <rect x={xDeepAccum} y={BAR_Y} width={xSafeDistrib - xDeepAccum} height={BAR_H} rx={BAR_H / 2} fill="#1e293b" />

        {/* Green half: deepAccum → current */}
        {xCurrent > xDeepAccum && (
          <rect
            x={xDeepAccum}
            y={BAR_Y}
            width={Math.max(0, xCurrent - xDeepAccum)}
            height={BAR_H}
            rx={BAR_H / 2}
            fill="url(#zoneGradLeft)"
          />
        )}

        {/* Red half: current → safeDistrib */}
        {xSafeDistrib > xCurrent && (
          <rect
            x={xCurrent}
            y={BAR_Y}
            width={Math.max(0, xSafeDistrib - xCurrent)}
            height={BAR_H}
            rx={BAR_H / 2}
            fill="url(#zoneGradRight)"
          />
        )}

        {/* Non-current tick marks */}
        {ticks.map(tick => (
          <g key={tick.label}>
            <line x1={tick.x} y1={BAR_Y - 6} x2={tick.x} y2={BAR_Y + BAR_H + 6} stroke={tick.color} strokeWidth="2" />
            {/* pct label below bar */}
            <text x={tick.x} y={BAR_Y + BAR_H + 20} textAnchor="middle" fontSize="9" fill={tick.color} fontFamily="JetBrains Mono, monospace">
              {tick.pct}
            </text>
            {/* zone name further below */}
            <text x={tick.x} y={BAR_Y + BAR_H + 32} textAnchor="middle" fontSize="8" fill="#64748b" fontFamily="Inter, sans-serif">
              {tick.label}
            </text>
          </g>
        ))}

        {/* Current price — blue circle */}
        <circle cx={xCurrent} cy={BAR_Y + BAR_H / 2} r={BAR_H / 2 + 3} fill="#1d4ed8" stroke="#60a5fa" strokeWidth="2" />
        <text x={xCurrent} y={BAR_Y + BAR_H / 2 + 4} textAnchor="middle" fontSize="8" fill="#e0f2fe" fontWeight="700" fontFamily="Inter, sans-serif">NOW</text>

        {/* Current price label above bar */}
        <text x={xCurrent} y={BAR_Y - 12} textAnchor="middle" fontSize="10" fill="#60a5fa" fontWeight="700" fontFamily="JetBrains Mono, monospace">
          ◀ {fmtP(current)}
        </text>
      </svg>
    </div>
  );
}

function WinLossRing({ wins, losses }: { wins: number; losses: number }) {
  const total = wins + losses;
  const winRate = total > 0 ? (wins / total) * 100 : 0;

  const R_OUTER = 40;
  const STROKE = 10;
  const CX = 50;
  const CY = 50;
  const circumference = 2 * Math.PI * R_OUTER;
  const winDash = total > 0 ? (wins / total) * circumference : 0;
  const lossDash = circumference - winDash;
  // strokeDashoffset of circumference*0.25 rotates start to top (12-o'clock)

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      gap: 8,
    }}>
      <svg viewBox="0 0 100 100" width="120" height="120" aria-label="Win/loss ring">
        {/* Background ring */}
        <circle
          cx={CX} cy={CY} r={R_OUTER}
          fill="none"
          stroke="#1e293b"
          strokeWidth={STROKE}
        />
        {/* Win arc */}
        {winDash > 0 && (
          <circle
            cx={CX} cy={CY} r={R_OUTER}
            fill="none"
            stroke="#22c55e"
            strokeWidth={STROKE}
            strokeDasharray={`${winDash} ${circumference - winDash}`}
            strokeDashoffset={circumference * 0.25}
            strokeLinecap="round"
          />
        )}
        {/* Loss arc */}
        {lossDash > 0 && winDash > 0 && (
          <circle
            cx={CX} cy={CY} r={R_OUTER}
            fill="none"
            stroke="#dc2626"
            strokeWidth={STROKE}
            strokeDasharray={`${lossDash} ${circumference - lossDash}`}
            strokeDashoffset={circumference * 0.25 - winDash}
            strokeLinecap="round"
            style={{ opacity: 0.75 }}
          />
        )}
        {/* All-loss ring */}
        {winDash === 0 && (
          <circle
            cx={CX} cy={CY} r={R_OUTER}
            fill="none"
            stroke="#dc2626"
            strokeWidth={STROKE}
            strokeDasharray={`${circumference} 0`}
            strokeDashoffset={circumference * 0.25}
          />
        )}
        {/* Center label */}
        <text x={CX} y={CY - 4} textAnchor="middle" fontSize="16" fontWeight="800" fill={winRate >= 60 ? '#22c55e' : winRate >= 45 ? '#eab308' : '#dc2626'} fontFamily="Inter, sans-serif">
          {winRate.toFixed(0)}%
        </text>
        <text x={CX} y={CY + 12} textAnchor="middle" fontSize="8" fill="#64748b" fontFamily="Inter, sans-serif">
          WIN RATE
        </text>
      </svg>
      <div style={{ display: 'flex', gap: 12, fontSize: F.xs, color: C.muted }}>
        <span style={{ color: '#22c55e', fontWeight: 600 }}>Wins: {wins}</span>
        <span style={{ color: '#dc2626', fontWeight: 600 }}>Losses: {losses}</span>
      </div>
    </div>
  );
}

function KpiCard({ label, value, sub, valueColor }: { label: string; value: string; sub?: string; valueColor?: string }) {
  return (
    <div style={{
      background: '#0f172a',
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '16px 18px',
    }}>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: F.xl, fontWeight: 700, color: valueColor || C.text }}>{value}</div>
      {sub && <div style={{ fontSize: F.xs, color: C.muted, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

function SignalsTab({ card }: { card: StrategyCard | null }) {
  if (!card?.latestSignal) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 0', color: C.muted }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>📊</div>
        <div style={{ fontSize: F.lg, fontWeight: 600, color: C.text, marginBottom: 4 }}>Awaiting first signal</div>
        <div style={{ fontSize: F.sm }}>Signals appear once the strategy has run at least one evaluation cycle.</div>
      </div>
    );
  }

  const sig = card.latestSignal;
  const score = sig.score || 0;
  const scoreColor = score >= 70 ? C.bull : score >= 45 ? '#eab308' : C.bear;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Score hero */}
      <div style={{
        background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)',
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '24px',
        display: 'flex',
        alignItems: 'center',
        gap: 24,
      }}>
        <div style={{
          width: 80,
          height: 80,
          borderRadius: '50%',
          border: `4px solid ${scoreColor}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}>
          <div style={{ fontSize: 24, fontWeight: 800, color: scoreColor }}>{score}</div>
        </div>
        <div>
          <div style={{ fontSize: F.xl, fontWeight: 700, color: C.text, marginBottom: 4 }}>{sig.label}</div>
          <div style={{ fontSize: F.sm, color: C.muted }}>
            {sig.market} · ${fmt(sig.price, 2)} · Last evaluated {card.lastEvaluated ? timeAgo(card.lastEvaluated) : '—'}
          </div>
        </div>
      </div>

      {/* Metrics grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        <KpiCard label="SMA 20" value={sig.trend.sma20} sub="20-period trend" valueColor={sig.trend.sma20 === 'Up' ? C.bull : C.bear} />
        <KpiCard label="SMA 50" value={sig.trend.sma50} sub="50-period trend" valueColor={sig.trend.sma50 === 'Up' ? C.bull : C.bear} />
        <KpiCard label="RSI 14" value={fmt(sig.trend.rsi14, 1)} sub={sig.trend.rsi14 > 70 ? 'Overbought' : sig.trend.rsi14 < 30 ? 'Oversold' : 'Neutral'} valueColor={sig.trend.rsi14 > 70 ? C.bear : sig.trend.rsi14 < 30 ? C.bull : C.text} />
      </div>

      {/* Zones */}
      {sig.zones && (
        <>
        <ZoneRuler sig={sig} />
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 18 }}>
          <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 14 }}>Price Zones</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[
              { label: 'Safe Distribution', value: sig.zones.safeDistrib, color: '#dc2626', note: 'Strong resistance — short bias' },
              { label: 'Distribution', value: sig.zones.distrib, color: '#f97316', note: 'Minor resistance' },
              { label: '▶ Current Price', value: sig.price, color: C.brand, note: 'Now', bold: true },
              { label: 'Accumulation', value: sig.zones.accum, color: '#22c55e', note: 'Support zone' },
              { label: 'Deep Accumulation', value: sig.zones.deepAccum, color: '#16a34a', note: 'Strong support — long bias' },
            ].map(zone => (
              <div key={zone.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: `1px solid ${C.border}` }}>
                <div>
                  <span style={{ fontSize: F.sm, fontWeight: zone.bold ? 700 : 400, color: zone.color }}>{zone.label}</span>
                  <span style={{ fontSize: F.xs, color: C.muted, marginLeft: 8 }}>{zone.note}</span>
                </div>
                <span style={{ fontSize: F.sm, fontWeight: 700, color: zone.color, fontFamily: 'JetBrains Mono, monospace' }}>
                  ${fmt(zone.value, 2)}
                </span>
              </div>
            ))}
          </div>
        </div>
        </>
      )}
    </div>
  );
}

function TradesTab({ trades, loading }: { trades: TradeRecord[]; loading: boolean }) {
  if (loading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {[0, 1, 2, 3].map(i => (
          <div key={i} style={{ height: 44, background: C.surface, borderRadius: R.md, animation: 'skeletonPulse 1.4s ease-in-out infinite' }} />
        ))}
      </div>
    );
  }

  if (!trades.length) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 0', color: C.muted }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>📋</div>
        <div style={{ fontSize: F.lg, fontWeight: 600, color: C.text, marginBottom: 4 }}>No trades yet</div>
        <div style={{ fontSize: F.sm }}>Trade history appears once the strategy has executed at least one trade.</div>
      </div>
    );
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: F.sm }}>
        <thead>
          <tr style={{ background: '#0f172a' }}>
            {['Symbol', 'Side', 'Entry', 'Exit', 'PnL', 'Result', 'Confidence', 'Duration', 'Close Reason'].map(h => (
              <th key={h} style={{ padding: '10px 14px', textAlign: 'left', color: C.muted, fontWeight: 600, borderBottom: `1px solid ${C.border}`, whiteSpace: 'nowrap' }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => {
            const isWin = (t as any).outcome === 'WIN' || (t as any).pnl > 0;
            const rowBg = isWin ? 'rgba(22,163,74,0.07)' : i % 2 === 0 ? C.surface : '#0f172a';
            return (
              <tr key={i} style={{ background: rowBg }}>
                <td style={{ padding: '10px 14px', borderBottom: `1px solid ${C.border}`, fontWeight: 600, color: C.text }}>
                  {(t as any).symbol || '—'}
                </td>
                <td style={{ padding: '10px 14px', borderBottom: `1px solid ${C.border}` }}>
                  <span style={{
                    padding: '2px 8px',
                    borderRadius: 4,
                    fontSize: F.xs,
                    fontWeight: 700,
                    background: (t as any).side === 'BUY' ? '#166534' : '#7f1d1d',
                    color: (t as any).side === 'BUY' ? '#bbf7d0' : '#fca5a5',
                  }}>
                    {(t as any).side || '—'}
                  </span>
                </td>
                <td style={{ padding: '10px 14px', borderBottom: `1px solid ${C.border}`, color: C.text, fontFamily: 'monospace' }}>
                  ${fmt((t as any).entry, 2)}
                </td>
                <td style={{ padding: '10px 14px', borderBottom: `1px solid ${C.border}`, color: C.text, fontFamily: 'monospace' }}>
                  {(t as any).exit ? `$${fmt((t as any).exit, 2)}` : '—'}
                </td>
                <td style={{ padding: '10px 14px', borderBottom: `1px solid ${C.border}`, fontWeight: 700, color: (t as any).pnl >= 0 ? C.bull : C.bear }}>
                  {(t as any).pnl !== undefined ? `${(t as any).pnl >= 0 ? '+' : ''}${fmtUsd((t as any).pnl)}` : '—'}
                </td>
                <td style={{ padding: '10px 14px', borderBottom: `1px solid ${C.border}` }}>
                  <span style={{
                    padding: '2px 8px',
                    borderRadius: 4,
                    fontSize: F.xs,
                    fontWeight: 700,
                    background: isWin ? '#166534' : '#7f1d1d',
                    color: isWin ? '#bbf7d0' : '#fca5a5',
                  }}>
                    {isWin ? 'WIN' : 'LOSS'}
                  </span>
                </td>
                <td style={{ padding: '10px 14px', borderBottom: `1px solid ${C.border}`, color: C.muted }}>
                  {(t as any).confidence ? `${Math.round((t as any).confidence)}%` : '—'}
                </td>
                <td style={{ padding: '10px 14px', borderBottom: `1px solid ${C.border}`, color: C.muted, whiteSpace: 'nowrap' }}>
                  {(t as any).duration_h ? `${fmt((t as any).duration_h, 1)}h` : '—'}
                </td>
                <td style={{ padding: '10px 14px', borderBottom: `1px solid ${C.border}`, color: C.muted, fontSize: F.xs }}>
                  {(t as any).close_reason || '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PerformanceTab({ trades }: { trades: TradeRecord[] }) {
  if (!trades.length) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 0', color: C.muted }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>📈</div>
        <div style={{ fontSize: F.lg, fontWeight: 600, color: C.text, marginBottom: 4 }}>No data yet</div>
        <div style={{ fontSize: F.sm }}>Performance stats will appear once trades are recorded.</div>
      </div>
    );
  }

  const wins = trades.filter(t => (t as any).outcome === 'WIN' || (t as any).pnl > 0);
  const losses = trades.filter(t => (t as any).outcome !== 'WIN' && (t as any).pnl <= 0);
  const winRate = trades.length > 0 ? (wins.length / trades.length) * 100 : 0;
  const totalPnl = trades.reduce((a, t) => a + ((t as any).pnl || 0), 0);
  const avgWin = wins.length > 0 ? wins.reduce((a, t) => a + (t as any).pnl, 0) / wins.length : 0;
  const avgLoss = losses.length > 0 ? Math.abs(losses.reduce((a, t) => a + (t as any).pnl, 0) / losses.length) : 0;
  const profitFactor = avgLoss > 0 ? (wins.reduce((a, t) => a + (t as any).pnl, 0)) / Math.abs(losses.reduce((a, t) => a + (t as any).pnl, 0)) : null;

  // Exit type counts
  const exitTypes: Record<string, number> = {};
  trades.forEach(t => {
    const cr = (t as any).close_reason || 'UNKNOWN';
    exitTypes[cr] = (exitTypes[cr] || 0) + 1;
  });
  const exitEntries = Object.entries(exitTypes).sort((a, b) => b[1] - a[1]);
  const exitColors: Record<string, string> = { SL: C.bear, TP1: C.bull, TP2: '#16a34a', TRAILING_STOP: '#6366f1', UNKNOWN: C.muted };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* KPI grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
        <KpiCard label="Total Trades" value={trades.length.toString()} sub={`${wins.length}W / ${losses.length}L`} />
        <KpiCard label="Win Rate" value={`${winRate.toFixed(1)}%`} valueColor={winRate >= 60 ? C.bull : winRate >= 45 ? '#eab308' : C.bear} />
        <KpiCard label="Net PnL" value={fmtUsd(totalPnl)} valueColor={totalPnl >= 0 ? C.bull : C.bear} />
        <KpiCard label="Avg Win" value={avgWin > 0 ? `+${fmtUsd(avgWin)}` : '—'} valueColor={C.bull} />
        <KpiCard label="Avg Loss" value={avgLoss > 0 ? `-${fmtUsd(avgLoss)}` : '—'} valueColor={C.bear} />
        <KpiCard label="Profit Factor" value={profitFactor !== null ? profitFactor.toFixed(2) + '×' : '—'} valueColor={profitFactor !== null && profitFactor >= 1.5 ? C.bull : C.muted} />
      </div>

      {/* Win/loss visual + exit breakdown — 2-column grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 16, alignItems: 'start' }}>
        {/* Win/Loss donut ring */}
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '18px 20px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 12, alignSelf: 'flex-start' }}>Outcome</div>
          <WinLossRing wins={wins.length} losses={losses.length} />
        </div>

        {/* Exit type breakdown */}
        {exitEntries.length > 0 && (
          <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 18 }}>
            <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 14 }}>Exit Type Breakdown</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {exitEntries.map(([type, count]) => {
                const pct = (count / trades.length) * 100;
                const color = exitColors[type] || C.muted;
                return (
                  <div key={type}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{ fontSize: F.sm, color: C.text }}>{type}</span>
                      <span style={{ fontSize: F.sm, color: C.muted }}>{count} ({pct.toFixed(0)}%)</span>
                    </div>
                    <div style={{ height: 8, background: C.border, borderRadius: 4, overflow: 'hidden' }}>
                      <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4, transition: 'width 0.5s' }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function LogsTab({ logs, loading, error }: { logs: LogEntry[]; loading: boolean; error: string | null }) {
  if (loading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {[0, 1, 2, 3, 4].map(i => (
          <div key={i} style={{ height: 36, background: C.surface, borderRadius: 4, animation: 'skeletonPulse 1.4s ease-in-out infinite' }} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: '24px', color: '#fca5a5', background: '#7f1d1d', borderRadius: R.md, fontSize: F.sm }}>
        ⚠ {error}
      </div>
    );
  }

  if (!logs.length) {
    return (
      <div style={{ textAlign: 'center', padding: '48px 0', color: C.muted }}>
        <div style={{ fontSize: 40, marginBottom: 12 }}>📄</div>
        <div style={{ fontSize: F.lg, fontWeight: 600, color: C.text, marginBottom: 4 }}>No logs yet</div>
        <div style={{ fontSize: F.sm }}>Log entries appear once the strategy begins executing.</div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, fontFamily: 'JetBrains Mono, Consolas, monospace', fontSize: 12 }}>
      {logs.map((log, idx) => {
        const color = eventColor(log.event);
        return (
          <div
            key={idx}
            style={{
              display: 'grid',
              gridTemplateColumns: '160px 180px 1fr',
              gap: 8,
              padding: '6px 12px',
              background: idx % 2 === 0 ? '#0f172a' : C.surface,
              borderRadius: 3,
              alignItems: 'flex-start',
            }}
          >
            <span style={{ color: C.muted, whiteSpace: 'nowrap' }}>
              {new Date(log.ts).toLocaleTimeString()}
            </span>
            <span style={{ color, fontWeight: 600 }}>{log.event}</span>
            <span style={{ color: C.text, opacity: 0.8, wordBreak: 'break-all' }}>
              {log.details ? JSON.stringify(log.details) : ''}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function StrategyDetail() {
  const router = useRouter();
  const { id } = router.query;
  const [activeTab, setActiveTab] = useState<Tab>('signals');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logsLoading, setLogsLoading] = useState(true);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [card, setCard] = useState<StrategyCard | null>(null);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [tradesLoading, setTradesLoading] = useState(false);
  const apiBase = resolveApiBase();

  const online = (() => {
    const ts = card?.lastHeartbeat || card?.last_seen;
    if (!ts) return false;
    return (Date.now() - Date.parse(ts)) / 1000 <= 120;
  })();

  const pnl = (card as any)?.pnl_realized ?? (card as any)?.pnl ?? null;

  useEffect(() => {
    if (!id) return;

    const fetchAll = async () => {
      // Fetch card
      try {
        const r = await fetch(`${apiBase}/v1/strategies/${id}`, { cache: 'no-store' });
        if (r.ok) setCard(await r.json());
      } catch (_) {}

      // Fetch logs
      try {
        setLogsError(null);
        const r = await fetch(`${apiBase}/v1/strategies/${id}/logs`, { cache: 'no-store' });
        if (r.ok) {
          const data = await r.json();
          setLogs(Array.isArray(data) ? data : data?.value || []);
        } else {
          setLogsError(`HTTP ${r.status}`);
        }
      } catch (e: any) {
        setLogsError(e?.message || 'Failed to load logs');
      } finally {
        setLogsLoading(false);
      }
    };

    fetchAll();
    const iv = setInterval(fetchAll, 30000);
    return () => clearInterval(iv);
  }, [id, apiBase]);

  // Load trades when that tab is selected
  useEffect(() => {
    if (activeTab !== 'trades' && activeTab !== 'performance') return;
    if (trades.length > 0) return;
    setTradesLoading(true);
    fetch(`${apiBase}/v1/trades/history?limit=200`, { cache: 'no-store' })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data?.trades) {
          // filter to this strategy's symbol if possible
          const sym = card?.latestSignal?.market;
          const filtered = sym
            ? data.trades.filter((t: any) => t.symbol === sym)
            : data.trades;
          setTrades(filtered);
        }
      })
      .catch(() => {})
      .finally(() => setTradesLoading(false));
  }, [activeTab, apiBase, card]);

  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: 'signals', label: 'Signals' },
    { key: 'trades', label: 'Trades', count: trades.length || undefined },
    { key: 'performance', label: 'Performance' },
    { key: 'logs', label: 'Logs', count: logs.length || undefined },
  ];

  return (
    <main style={{ padding: '32px 24px', maxWidth: 1100, margin: '0 auto', fontFamily: "'Inter', system-ui, sans-serif" }}>
      <style>{`
        @keyframes skeletonPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      {/* Back button */}
      <button
        onClick={() => router.push('/strategies')}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '7px 14px',
          border: `1px solid ${C.border}`,
          borderRadius: R.md,
          background: 'transparent',
          color: C.muted,
          fontSize: F.sm,
          cursor: 'pointer',
          marginBottom: 24,
          transition: 'color 0.15s',
        }}
        onMouseEnter={e => (e.currentTarget.style.color = C.text)}
        onMouseLeave={e => (e.currentTarget.style.color = C.muted)}
      >
        ← Back to Strategies
      </button>

      {/* Page header */}
      <div style={{
        background: C.surface,
        border: `1px solid ${C.border}`,
        borderRadius: R.lg,
        padding: '24px',
        marginBottom: 24,
        animation: 'fadeInUp 0.3s ease',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 16 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800, color: C.text, letterSpacing: '-0.02em' }}>
              {card?.name || `Strategy ${id}`}
            </h1>
            <div style={{ marginTop: 6, fontSize: F.sm, color: C.muted }}>
              ID: {id} · Last evaluated: {card?.lastEvaluated ? timeAgo(card.lastEvaluated) : '—'}
            </div>
          </div>
          <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <span style={{
              padding: '5px 14px',
              borderRadius: 20,
              fontSize: F.xs,
              fontWeight: 700,
              background: online ? '#166534' : C.border,
              color: online ? '#bbf7d0' : C.muted,
              display: 'flex',
              alignItems: 'center',
              gap: 5,
            }}>
              <span style={{
                width: 7,
                height: 7,
                borderRadius: '50%',
                background: online ? '#4ade80' : C.muted,
                display: 'inline-block',
                boxShadow: online ? '0 0 6px #4ade80' : 'none',
              }} />
              {online ? 'LIVE' : 'OFFLINE'}
            </span>
            {pnl !== null && (
              <div style={{
                padding: '5px 14px',
                borderRadius: 20,
                fontSize: F.sm,
                fontWeight: 700,
                background: '#0f172a',
                border: `1px solid ${C.border}`,
                color: pnl >= 0 ? C.bull : C.bear,
              }}>
                {pnl >= 0 ? '+' : ''}{fmtUsd(pnl)} PnL
              </div>
            )}
          </div>
        </div>

        {/* Open position */}
        {card?.open_position && (
          <div style={{
            marginTop: 16,
            paddingTop: 16,
            borderTop: `1px solid ${C.border}`,
            display: 'flex',
            gap: 24,
            fontSize: F.sm,
          }}>
            <span style={{ color: C.muted }}>Open Position:</span>
            <span style={{ fontWeight: 600, color: card.open_position.side === 'LONG' ? C.bull : C.bear }}>
              {card.open_position.side}
            </span>
            <span style={{ color: C.text }}>{card.open_position.size} @ ${fmt(card.open_position.avg_entry, 2)}</span>
            {card.open_position.unrealized_pnl !== undefined && (
              <span style={{ fontWeight: 600, color: (card.open_position.unrealized_pnl || 0) >= 0 ? C.bull : C.bear }}>
                Unrealized: {(card.open_position.unrealized_pnl || 0) >= 0 ? '+' : ''}{fmtUsd(card.open_position.unrealized_pnl || 0)}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Tab bar */}
      <div style={{
        display: 'flex',
        gap: 0,
        borderBottom: `1px solid ${C.border}`,
        marginBottom: 24,
      }}>
        {tabs.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            style={{
              padding: '10px 20px',
              border: 'none',
              borderBottom: activeTab === tab.key ? `2px solid ${C.brand}` : '2px solid transparent',
              background: 'transparent',
              color: activeTab === tab.key ? C.brand : C.muted,
              fontSize: F.sm,
              fontWeight: activeTab === tab.key ? 700 : 400,
              cursor: 'pointer',
              marginBottom: -1,
              transition: 'color 0.15s, border-color 0.15s',
              display: 'flex',
              alignItems: 'center',
              gap: 6,
            }}
          >
            {tab.label}
            {tab.count !== undefined && tab.count > 0 && (
              <span style={{
                padding: '1px 7px',
                borderRadius: 10,
                fontSize: 11,
                background: activeTab === tab.key ? C.brand : C.border,
                color: activeTab === tab.key ? '#fff' : C.muted,
              }}>
                {tab.count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ animation: 'fadeInUp 0.25s ease' }}>
        {activeTab === 'signals' && <SignalsTab card={card} />}
        {activeTab === 'trades' && <TradesTab trades={trades} loading={tradesLoading} />}
        {activeTab === 'performance' && <PerformanceTab trades={trades} />}
        {activeTab === 'logs' && <LogsTab logs={logs} loading={logsLoading} error={logsError} />}
      </div>
    </main>
  );
}
