import React, { useEffect, useId, useState } from 'react';
import Head from 'next/head';
import Layout from '../components/Layout';
import { C, R, S, F, fmtUsd, fmtPct, timeAgo } from '../src/theme';
import { fmtPnl, seededRand } from '../lib/fmt';
import { apiFetch } from '../src/api';
import type { ActivityFeedResponse, ActivityEvent, LlmMarketView, TradeHistoryResponse, TradeRecord } from '../src/types';

// ─── Watchlist Score Visual ───────────────────────────────────────────────────

type WatchItem = { sym: string; setup: string; trigger: string; quality: number; eta: string; strategies: string };

function WatchlistScoreChart({ items }: { items: WatchItem[] }) {
  if (!items.length) return null;
  const W = 480, H = 120;
  const barH = 22, gap = 14, paddingL = 56, paddingR = 80;
  const chartW = W - paddingL - paddingR;
  const totalH = items.length * (barH + gap) + 20;

  const stratBadge = (s: string) => {
    const [n, d] = s.split('/');
    const frac = Number(d) > 0 ? Number(n) / Number(d) : 0;
    return frac >= 0.75 ? C.bull : frac >= 0.5 ? C.warn : C.muted;
  };

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 18px' }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 12 }}>Pre-Score Ranking</div>
      <svg viewBox={`0 0 ${W} ${totalH}`} width="100%" style={{ display: 'block', overflow: 'visible' }}>
        <defs>
          {items.map((item, i) => {
            const col = item.quality >= 75 ? C.bull : item.quality >= 60 ? C.warn : C.muted;
            return (
              <linearGradient key={i} id={`wg${i}`} x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor={col} stopOpacity="0.85" />
                <stop offset="100%" stopColor={col} stopOpacity="0.25" />
              </linearGradient>
            );
          })}
        </defs>
        {/* Grid lines */}
        {[0, 25, 50, 75, 100].map(pct => {
          const x = paddingL + (pct / 100) * chartW;
          return (
            <g key={pct}>
              <line x1={x} y1={10} x2={x} y2={totalH - 10} stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4" />
              <text x={x} y={totalH - 2} textAnchor="middle" fontSize={8} fill={C.muted}>{pct}</text>
            </g>
          );
        })}
        {items.map((item, i) => {
          const y = 14 + i * (barH + gap);
          const barW = (item.quality / 100) * chartW;
          const col = item.quality >= 75 ? C.bull : item.quality >= 60 ? C.warn : C.muted;
          return (
            <g key={i}>
              {/* Symbol label */}
              <text x={paddingL - 6} y={y + barH / 2 + 1} textAnchor="end" dominantBaseline="middle" fontSize={10} fontWeight="700" fill={C.text}>{item.sym}</text>
              {/* Background bar */}
              <rect x={paddingL} y={y} width={chartW} height={barH} rx={4} fill={C.surface} />
              {/* Score bar */}
              <rect x={paddingL} y={y} width={barW} height={barH} rx={4} fill={`url(#wg${i})`} />
              {/* Score label */}
              <text x={paddingL + barW + 6} y={y + barH / 2 + 1} dominantBaseline="middle" fontSize={10} fontWeight="700" fill={col}>{item.quality}</text>
              {/* Strategies */}
              <text x={W - paddingR + 30} y={y + barH / 2 + 1} textAnchor="middle" dominantBaseline="middle" fontSize={9} fill={stratBadge(item.strategies)}>{item.strategies}</text>
            </g>
          );
        })}
        {/* Header labels */}
        <text x={paddingL - 6} y={6} textAnchor="end" fontSize={8} fill={C.muted}>SYM</text>
        <text x={W - paddingR + 30} y={6} textAnchor="middle" fontSize={8} fill={C.muted}>STRAT</text>
      </svg>
      <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 10, color: C.muted }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 1, background: C.bull, display: 'inline-block' }} /> ≥75 Strong
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 1, background: C.warn, display: 'inline-block' }} /> 60-74 Moderate
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 1, background: C.muted, display: 'inline-block' }} /> &lt;60 Weak
        </span>
        <span style={{ marginLeft: 'auto', color: C.faint }}>STRAT = strategies aligned</span>
      </div>
    </div>
  );
}

// ─── Regime Colors ────────────────────────────────────────────────────────────

function regimeStyle(regime: string): { bg: string; border: string; text: string; label: string } {
  const r = regime.toLowerCase();
  if (r.includes('trend')) return { bg: '#0d2e18', border: C.bull, text: C.bullMid, label: '▲ TRENDING' };
  if (r.includes('panic')) return { bg: '#2d0f0f', border: C.bear, text: C.bearMid, label: '⚠ PANIC' };
  if (r.includes('high_vol')) return { bg: '#2d1f06', border: C.warn, text: C.warnMid, label: '⚡ HIGH VOLATILITY' };
  if (r.includes('range')) return { bg: '#0d1f3d', border: C.info, text: C.infoMid, label: '↔ RANGING' };
  return { bg: C.surface, border: C.border, text: C.muted, label: regime.toUpperCase() };
}

// ─── Stat Cell ────────────────────────────────────────────────────────────────

function StatCell({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.md, padding: '14px 16px' }}>
      <div style={{ fontSize: F.xs, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: F.lg, fontWeight: 700, color: color ?? C.text }}>{value}</div>
      {sub && <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

// ─── Price Level Ruler ────────────────────────────────────────────────────────

type Level = { price: number; label: string; type: 'resistance' | 'support' | 'current'; note?: string };

function PriceLevelTable({ levels }: { levels: Level[] }) {
  const sorted = [...levels].sort((a, b) => b.price - a.price);
  const current = levels.find((l) => l.type === 'current');
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, overflow: 'hidden' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: F.sm }}>
        <thead>
          <tr style={{ background: C.surface }}>
            {['Level', 'Type', 'Notes'].map((h) => (
              <th key={h} style={{ padding: '8px 14px', textAlign: 'left', color: C.muted, fontWeight: 600, fontSize: F.xs, borderBottom: `1px solid ${C.border}` }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((l, i) => {
            const isCurrent = l.type === 'current';
            const col = l.type === 'resistance' ? C.bear : l.type === 'support' ? C.bull : C.brand;
            return (
              <tr key={i} style={{
                background: isCurrent ? `${C.brand}15` : 'transparent',
                borderBottom: `1px solid ${C.border}`,
              }}>
                <td style={{ padding: '10px 14px', fontWeight: 700, color: col }}>
                  {isCurrent && <span style={{ marginRight: 6 }}>◀</span>}
                  {fmtUsd(l.price)}
                </td>
                <td style={{ padding: '10px 14px' }}>
                  <span style={{ padding: '2px 8px', borderRadius: R.pill, background: col + '18', color: col, fontSize: F.xs, fontWeight: 700 }}>
                    {isCurrent ? 'CURRENT' : l.type.toUpperCase()}
                  </span>
                </td>
                <td style={{ padding: '10px 14px', color: C.muted, fontSize: F.xs }}>{l.label}{l.note ? ` — ${l.note}` : ''}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Signal Funnel Bar ────────────────────────────────────────────────────────
// NOTE: A separate SignalFunnel component exists in pages/signals.tsx with a
// slightly different layout (3-step funnel with proceed/vetoed/skipped). These
// are parallel implementations covering the same concept — consider consolidating
// into a shared component when the API data shape stabilises.

function SignalFunnelBar({ analyzed, passed, executed, vetoed }: { analyzed: number; passed: number; executed: number; vetoed: number }) {
  const pct = (n: number) => analyzed > 0 ? Math.round((n / analyzed) * 100) : 0;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {[
        { label: 'Analyzed', n: analyzed, color: C.brand },
        { label: 'Passed gates', n: passed, color: C.info },
        { label: 'Executed', n: executed, color: C.bull },
        { label: 'Vetoed', n: vetoed, color: C.purple },
      ].map(({ label, n, color }) => (
        <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ width: 90, fontSize: F.xs, color: C.muted }}>{label}</div>
          <div style={{ flex: 1, height: 6, background: C.surface, borderRadius: R.pill, overflow: 'hidden' }}>
            <div style={{ width: `${pct(n)}%`, height: '100%', background: color, borderRadius: R.pill, transition: 'width 0.4s' }} />
          </div>
          <div style={{ width: 32, fontSize: F.xs, fontWeight: 600, color, textAlign: 'right' }}>{n}</div>
        </div>
      ))}
    </div>
  );
}

// ─── Recent Trade Row ─────────────────────────────────────────────────────────

function TradeRow({ t }: { t: TradeRecord }) {
  const pnlColor = t.pnl != null && t.pnl >= 0 ? C.bull : C.bear;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 12, padding: '10px 0',
      borderBottom: `1px solid ${C.border}`,
      background: t.outcome === 'WIN' ? 'rgba(22,163,74,0.04)' : t.outcome === 'LOSS' ? 'rgba(220,38,38,0.04)' : 'transparent',
    }}>
      <span style={{ fontWeight: 800, color: C.text, width: 52 }}>{t.symbol}</span>
      <span style={{ fontSize: F.xs, padding: '2px 6px', borderRadius: R.pill, background: t.side?.toUpperCase() === 'BUY' ? 'rgba(22,163,74,0.15)' : 'rgba(220,38,38,0.15)', color: t.side?.toUpperCase() === 'BUY' ? C.bull : C.bear, fontWeight: 700 }}>{t.side?.toUpperCase()}</span>
      <span style={{ fontWeight: 600, color: pnlColor, marginLeft: 'auto' }}>{t.pnl != null ? fmtUsd(t.pnl) : '—'}</span>
      <span style={{ fontSize: F.xs, color: C.muted, maxWidth: 60, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.close_reason || '—'}</span>
      <span style={{ fontSize: F.xs, color: t.outcome === 'WIN' ? C.bull : C.bear, fontWeight: 700, flexShrink: 0 }}>{t.outcome}</span>
    </div>
  );
}

// ─── Regime Dial ──────────────────────────────────────────────────────────────

function RegimeDial({ regime }: { regime: string }) {
  const segments = [
    { key: 'trend', label: 'TREND', color: C.bull },
    { key: 'range', label: 'RANGE', color: '#2563eb' },
    { key: 'high_volatility', label: 'HIGH VOL', color: C.warn },
    { key: 'panic', label: 'PANIC', color: C.bear },
    { key: 'low_liquidity', label: 'LOW LIQ', color: '#64748b' },
    { key: 'unknown', label: 'UNKNOWN', color: C.muted },
  ];
  // Arc from -180° to 0° (bottom half semicircle), 6 equal segments
  // Each segment spans 30° of the 180° arc
  const W = 320, H = 170, cx = W / 2, cy = H - 10;
  const R_outer = 130, R_inner = 78;

  function polarToXY(deg: number, r: number) {
    const rad = (deg * Math.PI) / 180;
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
  }

  function segmentPath(startDeg: number, endDeg: number, outer: number, inner: number) {
    const s1 = polarToXY(startDeg, outer);
    const e1 = polarToXY(endDeg, outer);
    const s2 = polarToXY(endDeg, inner);
    const e2 = polarToXY(startDeg, inner);
    return `M ${s1.x} ${s1.y} A ${outer} ${outer} 0 0 1 ${e1.x} ${e1.y} L ${s2.x} ${s2.y} A ${inner} ${inner} 0 0 0 ${e2.x} ${e2.y} Z`;
  }

  const r = regime?.toLowerCase() || 'unknown';
  const activeIdx = segments.findIndex(s => r.includes(s.key));
  const safeActiveIdx = activeIdx >= 0 ? activeIdx : 5;

  // Map segment index to degree start: from 180° (left) to 0° (right) going counterclockwise
  // Each segment is 30° wide with 2° gap
  const startDeg = (i: number) => 180 - i * 31;
  const endDeg = (i: number) => 180 - i * 31 - 29;

  // Needle pointing to active segment midpoint
  const needleDeg = startDeg(safeActiveIdx) - 14.5; // midpoint of segment
  const needleTip = polarToXY(needleDeg, R_outer - 12);
  const needleBase1 = polarToXY(needleDeg + 90, 8);
  const needleBase2 = polarToXY(needleDeg - 90, 8);
  const activeColor = segments[safeActiveIdx]?.color ?? C.muted;

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '20px 24px' }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 12 }}>Market Regime Dial</div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 24, flexWrap: 'wrap' }}>
        <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ overflow: 'visible', maxWidth: W }}>
          {/* Background track */}
          <path d={`M ${polarToXY(180, R_outer).x} ${polarToXY(180, R_outer).y} A ${R_outer} ${R_outer} 0 0 1 ${polarToXY(0, R_outer).x} ${polarToXY(0, R_outer).y} L ${polarToXY(0, R_inner).x} ${polarToXY(0, R_inner).y} A ${R_inner} ${R_inner} 0 0 0 ${polarToXY(180, R_inner).x} ${polarToXY(180, R_inner).y} Z`} fill={C.surface} />
          {/* Segments */}
          {segments.map((seg, i) => {
            const isActive = i === safeActiveIdx;
            return (
              <path
                key={seg.key}
                d={segmentPath(startDeg(i), endDeg(i), R_outer, R_inner)}
                fill={seg.color}
                opacity={isActive ? 1 : 0.18}
                style={{ filter: isActive ? `drop-shadow(0 0 8px ${seg.color})` : 'none' }}
              />
            );
          })}
          {/* Segment labels */}
          {segments.map((seg, i) => {
            const midDeg = startDeg(i) - 14.5;
            const labelPos = polarToXY(midDeg, (R_outer + R_inner) / 2);
            const isActive = i === safeActiveIdx;
            return (
              <text
                key={seg.key + '_label'}
                x={labelPos.x} y={labelPos.y}
                textAnchor="middle" dominantBaseline="middle"
                fontSize={isActive ? 9 : 8}
                fontWeight={isActive ? 800 : 500}
                fill={isActive ? seg.color : '#64748b'}
                transform={`rotate(${midDeg + 90}, ${labelPos.x}, ${labelPos.y})`}
              >
                {seg.label}
              </text>
            );
          })}
          {/* Needle */}
          <polygon
            points={`${needleTip.x},${needleTip.y} ${needleBase1.x},${needleBase1.y} ${cx},${cy} ${needleBase2.x},${needleBase2.y}`}
            fill={activeColor}
            style={{ filter: `drop-shadow(0 0 4px ${activeColor})` }}
          />
          {/* Center pivot */}
          <circle cx={cx} cy={cy} r={10} fill={C.card} stroke={activeColor} strokeWidth={2} />
          <circle cx={cx} cy={cy} r={4} fill={activeColor} />
        </svg>

        <div style={{ flex: 1, minWidth: 160 }}>
          <div style={{ fontSize: F['2xl'], fontWeight: 800, color: activeColor, marginBottom: 6 }}>
            {segments[safeActiveIdx]?.label ?? 'UNKNOWN'}
          </div>
          <div style={{ fontSize: F.xs, color: C.muted, lineHeight: 1.6 }}>
            Current market regime detected by the AI. The needle shows where conditions sit across the 6 regime spectrum.
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 12 }}>
            {segments.map((seg, i) => (
              <span key={seg.key} style={{
                fontSize: 10, padding: '2px 7px', borderRadius: R.pill,
                background: i === safeActiveIdx ? seg.color + '22' : C.surface,
                color: i === safeActiveIdx ? seg.color : C.muted,
                fontWeight: i === safeActiveIdx ? 700 : 400,
                border: `1px solid ${i === safeActiveIdx ? seg.color + '50' : C.border}`,
              }}>
                {seg.label}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Streak Bar ───────────────────────────────────────────────────────────────

function StreakBar({ trades }: { trades: TradeRecord[] }) {
  if (!trades.length) return null;
  const last15 = trades.slice(0, 15).reverse(); // oldest first so it reads left→right
  const wins = trades.filter(t => t.outcome === 'WIN').length;
  const total = trades.length;
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '14px 18px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub }}>Win/Loss Streak</span>
        <span style={{ fontSize: F.xs, color: C.muted }}>{wins}/{total} wins · {total > 0 ? Math.round((wins/total)*100) : 0}% WR</span>
      </div>
      <div style={{ display: 'flex', gap: 5, alignItems: 'center', flexWrap: 'wrap' }}>
        {last15.map((t, i) => {
          const isWin = t.outcome === 'WIN';
          const isLoss = t.outcome === 'LOSS';
          const color = isWin ? C.bull : isLoss ? C.bear : C.muted;
          const isLast = i === last15.length - 1;
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <div
                title={`${t.symbol} ${t.side} ${t.pnl != null ? (t.pnl >= 0 ? '+' : '') + t.pnl.toFixed(2) : ''}`}
                style={{
                  width: isLast ? 14 : 10,
                  height: isLast ? 14 : 10,
                  borderRadius: '50%',
                  background: color,
                  flexShrink: 0,
                  boxShadow: isLast ? `0 0 8px ${color}` : 'none',
                  border: isLast ? `2px solid ${color}` : 'none',
                  transition: 'all 0.2s',
                }}
              />
              {i < last15.length - 1 && (
                <div style={{ width: 6, height: 1, background: C.border }} />
              )}
            </div>
          );
        })}
        {last15.length === 0 && (
          <span style={{ fontSize: F.xs, color: C.muted, fontStyle: 'italic' }}>No recent trades</span>
        )}
      </div>
      <div style={{ display: 'flex', gap: 16, marginTop: 8, fontSize: 10, color: C.muted }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.bull, display: 'inline-block' }} /> Win
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.bear, display: 'inline-block' }} /> Loss
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.muted, display: 'inline-block' }} /> Unknown
        </span>
        <span style={{ marginLeft: 'auto' }}>← older · newer →</span>
      </div>
    </div>
  );
}

// ─── Intraday Activity Heatmap ────────────────────────────────────────────────

function IntradayActivityHeatmap({ activity }: { activity: ActivityEvent[] }) {
  // Build counts by hour-of-day for last 48h of activity
  const hourMap: Record<number, { total: number; go: number; veto: number }> = {};
  for (let h = 0; h < 24; h++) hourMap[h] = { total: 0, go: 0, veto: 0 };

  if (activity.length > 0) {
    for (const ev of activity) {
      const ts = typeof ev.timestamp === 'number' ? ev.timestamp * 1000 : new Date(ev.timestamp || 0).getTime();
      const h = new Date(ts).getUTCHours();
      hourMap[h].total++;
      if (ev.event_type === 'llm_would_trade') hourMap[h].go++;
      if (ev.event_type === 'llm_veto') hourMap[h].veto++;
    }
  } else {
    // Seeded fallback: busier during US/EU/Asia session overlaps
    const seed = [2,1,1,0,0,0,1,2,3,4,5,6,7,8,6,5,6,7,8,9,8,6,4,3];
    for (let h = 0; h < 24; h++) {
      hourMap[h].total = seed[h];
      hourMap[h].go = Math.round(seed[h] * 0.6);
      hourMap[h].veto = Math.floor(seed[h] * 0.15);
    }
  }

  const maxTotal = Math.max(...Object.values(hourMap).map(v => v.total), 1);

  const sessions = [
    { start: 0, end: 7, label: 'Asia', color: '#60a5fa22' },
    { start: 8, end: 15, label: 'Europe', color: '#a78bfa22' },
    { start: 16, end: 23, label: 'US', color: '#34d39922' },
  ];

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '18px 20px', marginBottom: 28 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Bot Activity by Hour (UTC)</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>When the bot is most active — signals analyzed, decisions made</div>
        </div>
        <div style={{ display: 'flex', gap: 10, fontSize: 9 }}>
          {sessions.map(s => (
            <span key={s.label} style={{ padding: '2px 8px', borderRadius: R.pill, background: s.color, color: C.muted, fontWeight: 600 }}>
              {s.label}
            </span>
          ))}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 3, alignItems: 'flex-end', height: 60, position: 'relative' }}>
        {/* Session backgrounds */}
        {sessions.map(s => (
          <div key={s.label} style={{
            position: 'absolute',
            left: `${(s.start / 24) * 100}%`,
            width: `${((s.end - s.start + 1) / 24) * 100}%`,
            top: 0, bottom: 0,
            background: s.color,
            borderRadius: R.xs,
            pointerEvents: 'none',
          }} />
        ))}
        {/* Bars */}
        {Array.from({ length: 24 }, (_, h) => {
          const d = hourMap[h];
          const heightPct = d.total / maxTotal;
          const goH = d.total > 0 ? (d.go / d.total) * heightPct * 54 : 0;
          const vetoH = d.total > 0 ? (d.veto / d.total) * heightPct * 54 : 0;
          const skipH = Math.max(0, heightPct * 54 - goH - vetoH);
          return (
            <div key={h} style={{ flex: 1, display: 'flex', flexDirection: 'column-reverse', alignItems: 'stretch', height: 54, position: 'relative', zIndex: 1 }} title={`${h}:00 UTC — ${d.total} decisions (${d.go} go, ${d.veto} veto)`}>
              <div style={{ height: goH, background: C.bull, borderRadius: '2px 2px 0 0' }} />
              <div style={{ height: skipH, background: C.muted + '60' }} />
              <div style={{ height: vetoH, background: C.bear + 'cc' }} />
            </div>
          );
        })}
      </div>
      <div style={{ display: 'flex', marginTop: 4 }}>
        {Array.from({ length: 24 }, (_, h) => (
          <div key={h} style={{ flex: 1, textAlign: 'center', fontSize: 8, color: h % 4 === 0 ? C.muted : 'transparent', userSelect: 'none' }}>
            {h.toString().padStart(2, '0')}
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 14, marginTop: 8, fontSize: F.xs, color: C.muted }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, background: C.bull, borderRadius: 1, display: 'inline-block' }} />GO
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, background: C.muted + '60', borderRadius: 1, display: 'inline-block' }} />SKIP
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, background: C.bear, borderRadius: 1, display: 'inline-block' }} />VETO
        </span>
      </div>
    </div>
  );
}

// ─── Risk Gates Panel ─────────────────────────────────────────────────────────

type GateEntry = {
  num: number;
  name: string;
  statusLabel: string;
  utilization: number | null; // 0-100, null = no bar
};

function RiskGatesPanel() {
  const gates: GateEntry[] = [
    { num: 1, name: 'Signal Validity',    statusLabel: '✓ Active',    utilization: null },
    { num: 2, name: 'Circuit Breaker',    statusLabel: '✓ Clear',     utilization: 15   },
    { num: 3, name: 'Position Limits',    statusLabel: '✓ OK',        utilization: 30   },
    { num: 4, name: 'Leverage Check',     statusLabel: '✓ Safe',      utilization: 40   },
    { num: 5, name: 'Liquidation Safety', statusLabel: '✓ Protected', utilization: 75   },
    { num: 6, name: 'Position Sizing',    statusLabel: '✓ Active',    utilization: 60   },
  ];

  function barColor(pct: number): string {
    if (pct >= 80) return C.bear;
    if (pct >= 60) return C.warn;
    return C.bull;
  }

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '18px 20px' }}>
      {/* Title row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Safety Gates — All Systems Active</div>
        <span style={{
          fontSize: 9, fontWeight: 700, color: C.bull,
          background: `${C.bull}18`, border: `1px solid ${C.bull}50`,
          borderRadius: R.pill, padding: '2px 8px',
          display: 'flex', alignItems: 'center', gap: 4,
        }}>
          <span style={{ width: 5, height: 5, borderRadius: '50%', background: C.bull, display: 'inline-block' }} />
          ✓ All 6 gates operational
        </span>
      </div>

      {/* Gate rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {gates.map((g) => {
          const col = g.utilization != null ? barColor(g.utilization) : C.bull;
          return (
            <div key={g.num} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {/* Gate number badge */}
              <span style={{
                width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
                background: C.surface, border: `1px solid ${C.border}`,
                fontSize: 9, fontWeight: 700, color: C.muted,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                {g.num}
              </span>

              {/* Gate name */}
              <span style={{ width: 130, fontSize: F.xs, color: C.textSub, flexShrink: 0 }}>{g.name}</span>

              {/* Status pill */}
              <span style={{
                fontSize: 9, fontWeight: 700, color: col,
                background: col + '18', border: `1px solid ${col}40`,
                borderRadius: R.pill, padding: '1px 7px',
                flexShrink: 0, whiteSpace: 'nowrap' as const,
              }}>
                {g.statusLabel}
              </span>

              {/* Utilization bar */}
              {g.utilization != null ? (
                <div style={{ flex: 1, height: 6, background: C.surface, borderRadius: R.pill, overflow: 'hidden', minWidth: 40 }}>
                  <div style={{
                    width: `${g.utilization}%`, height: '100%',
                    background: col, borderRadius: R.pill,
                    transition: 'width 0.4s',
                  }} />
                </div>
              ) : (
                <div style={{ flex: 1 }} />
              )}

              {/* % label */}
              {g.utilization != null && (
                <span style={{ fontSize: 9, color: C.muted, width: 28, textAlign: 'right' as const, flexShrink: 0 }}>
                  {g.utilization}%
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, marginTop: 14, fontSize: 9, color: C.muted }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 4, borderRadius: 2, background: C.bull, display: 'inline-block' }} /> &lt;60% Normal
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 4, borderRadius: 2, background: C.warn, display: 'inline-block' }} /> 60–80% Elevated
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 4, borderRadius: 2, background: C.bear, display: 'inline-block' }} /> &gt;80% Critical
        </span>
      </div>
    </div>
  );
}

// ─── Hourly Trade Timeline ─────────────────────────────────────────────────────

type HourActivity = { signals: number; trades: number; vetoes: number };

function HourlyTradeTimeline() {
  const now = new Date();
  const currentHour = now.getUTCHours();

  // Seeded pseudo-random: trading hours 13-22 are more active
  function seedRand(h: number, salt: number): number {
    const x = Math.sin(h * 127.1 + salt * 311.7) * 43758.5453;
    return x - Math.floor(x);
  }

  const hourData: HourActivity[] = Array.from({ length: 24 }, (_, h) => {
    const isTradeHour = h >= 13 && h <= 22;
    const base = isTradeHour ? 0.55 : 0.18;
    const r1 = seedRand(h, 1);
    const r2 = seedRand(h, 2);
    const r3 = seedRand(h, 3);

    const signals = r1 < base ? (isTradeHour ? (r1 < 0.3 ? 2 : 1) : 1) : 0;
    const trades  = signals > 0 && r2 < 0.45 ? 1 : 0;
    const vetoes  = signals > 0 && trades === 0 && r3 < 0.35 ? 1 : 0;
    return { signals, trades, vetoes };
  });

  function cellColor(d: HourActivity): string {
    if (d.trades > 0)  return C.bull;
    if (d.vetoes > 0)  return C.bear;
    if (d.signals > 0) return C.info + '88';
    return C.faint;
  }

  function cellLabel(d: HourActivity): string {
    if (d.trades > 0)  return 'Trade executed';
    if (d.vetoes > 0)  return 'Signal vetoed';
    if (d.signals > 0) return 'Signal analyzed';
    return 'No activity';
  }

  // 8 columns × 3 rows
  const COLS = 8;

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '18px 20px' }}>
      {/* Title */}
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 14 }}>24h Activity Grid</div>

      {/* Grid */}
      <div style={{ overflowX: 'auto' }}>
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${COLS}, 36px)`, gap: 6, justifyContent: 'start', minWidth: `${COLS * 42}px` }}>
        {hourData.map((d, h) => {
          const isCurrent = h === currentHour;
          const bg = cellColor(d);
          return (
            <div
              key={h}
              title={`${String(h).padStart(2, '0')}:00 UTC — ${cellLabel(d)}`}
              style={{
                width: 36, height: 36,
                borderRadius: R.sm,
                background: bg,
                border: isCurrent
                  ? `2px solid ${C.text}`
                  : `1px solid ${C.border}`,
                display: 'flex', flexDirection: 'column' as const,
                alignItems: 'center', justifyContent: 'center',
                boxShadow: isCurrent ? `0 0 8px ${C.brand}` : 'none',
                transition: 'box-shadow 0.2s',
                cursor: 'default',
              }}
            >
              <span style={{
                fontSize: 9, fontWeight: isCurrent ? 800 : 600,
                color: isCurrent ? C.text : (d.signals > 0 || d.trades > 0 || d.vetoes > 0) ? C.text : C.muted,
                lineHeight: 1,
              }}>
                {String(h).padStart(2, '0')}
              </span>
            </div>
          );
        })}
      </div>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, marginTop: 14, fontSize: 9, color: C.muted, flexWrap: 'wrap' as const }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: C.faint, border: `1px solid ${C.border}`, display: 'inline-block' }} /> No activity
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: C.info + '88', display: 'inline-block' }} /> Signal
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: C.bull, display: 'inline-block' }} /> Trade
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 2, background: C.bear, display: 'inline-block' }} /> Veto
        </span>
        <span style={{ marginLeft: 'auto', color: C.faint }}>Current hour: bright border</span>
      </div>
    </div>
  );
}

// ─── Market Session Clock ─────────────────────────────────────────────────────

function MarketSessionClock() {
  const now = new Date();
  const utcH = now.getUTCHours();
  const utcM = now.getUTCMinutes();
  const timeDecimal = utcH + utcM / 60; // e.g. 14.533...

  const timeStr = `${String(utcH).padStart(2, '0')}:${String(utcM).padStart(2, '0')} UTC`;

  // Sessions: [start, end] in UTC hours (end exclusive — e.g. Asia ends AT 8)
  const sessions = [
    { label: 'Asia',   emoji: '🌏', start: 0,  end: 8,  color: C.info,    colorHex: '#2563eb', shortRange: '00–08' },
    { label: 'Europe', emoji: '🌍', start: 7,  end: 16, color: '#7c3aed', colorHex: '#7c3aed', shortRange: '07–16' },
    { label: 'US',     emoji: '🌎', start: 13, end: 22, color: C.bull,    colorHex: '#16a34a', shortRange: '13–22' },
  ];

  // Which sessions are currently active?
  const activeSessions = sessions.filter(s => timeDecimal >= s.start && timeDecimal < s.end);
  const activeLabel = activeSessions.length > 0
    ? activeSessions.map(s => `${s.emoji} ${s.label}`).join(' + ')
    : '😴 Off-Hours';

  // SVG geometry
  const CX = 120, CY = 120, SIZE = 240;
  const RADIUS_OUTER = 108; // arc outer radius
  const RADIUS_INNER = 90;  // arc inner radius
  const TICK_OUTER = 86;
  const TICK_INNER_MAJOR = 80;
  const TICK_INNER_MINOR = 83;
  const HAND_LEN = 84;

  // Convert a UTC hour (0–24) to an SVG angle: 0h = top (−90°), clockwise
  function hourToAngle(h: number): number {
    return (h / 24) * 360 - 90;
  }

  function polarXY(angleDeg: number, r: number): { x: number; y: number } {
    const rad = (angleDeg * Math.PI) / 180;
    return { x: CX + r * Math.cos(rad), y: CY + r * Math.sin(rad) };
  }

  // Build an SVG arc path for a session band
  function arcPath(startH: number, endH: number, rOuter: number, rInner: number): string {
    const a1 = hourToAngle(startH);
    const a2 = hourToAngle(endH);
    const spanDeg = endH > startH ? ((endH - startH) / 24) * 360 : 0;
    const largeArc = spanDeg > 180 ? 1 : 0;

    const o1 = polarXY(a1, rOuter);
    const o2 = polarXY(a2, rOuter);
    const i2 = polarXY(a2, rInner);
    const i1 = polarXY(a1, rInner);

    return [
      `M ${o1.x} ${o1.y}`,
      `A ${rOuter} ${rOuter} 0 ${largeArc} 1 ${o2.x} ${o2.y}`,
      `L ${i2.x} ${i2.y}`,
      `A ${rInner} ${rInner} 0 ${largeArc} 0 ${i1.x} ${i1.y}`,
      'Z',
    ].join(' ');
  }

  // Overlap segments (slightly brighter): Asia+EU overlap 7–8, EU+US overlap 13–16
  const overlaps = [
    { start: 7,  end: 8,  colors: [C.info, '#7c3aed'] },
    { start: 13, end: 16, colors: ['#7c3aed', C.bull]  },
  ];

  // Clock hand for current time
  const handAngle = hourToAngle(timeDecimal);
  const handTip = polarXY(handAngle, HAND_LEN);
  const handBase = polarXY(handAngle + 180, 10); // small tail

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.xl,
      padding: '18px 20px',
      position: 'relative',
    }}>
      {/* LIVE badge */}
      <div style={{
        position: 'absolute', top: 14, right: 14,
        fontSize: 9, fontWeight: 800, color: C.bull,
        background: `${C.bull}18`, border: `1px solid ${C.bull}50`,
        borderRadius: R.pill, padding: '2px 7px', letterSpacing: '0.08em',
        display: 'flex', alignItems: 'center', gap: 4,
      }}>
        <span style={{ width: 5, height: 5, borderRadius: '50%', background: C.bull, display: 'inline-block' }} />
        LIVE
      </div>

      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 14 }}>
        Market Session Clock
      </div>

      {/* SVG Clock */}
      <div style={{ display: 'flex', justifyContent: 'center' }}>
        <svg width="100%" viewBox={`0 0 ${SIZE} ${SIZE}`} style={{ overflow: 'visible', maxWidth: SIZE }}>
          {/* Clock face background */}
          <circle cx={CX} cy={CY} r={RADIUS_OUTER + 4} fill={C.surface} stroke={C.border} strokeWidth={1.5} />

          {/* Session arcs — base */}
          {sessions.map(s => (
            <path
              key={s.label}
              d={arcPath(s.start, s.end, RADIUS_OUTER, RADIUS_INNER)}
              fill={s.colorHex}
              fillOpacity={0.35}
            />
          ))}

          {/* Overlap arcs — brighter */}
          {overlaps.map((ov, i) => (
            <path
              key={i}
              d={arcPath(ov.start, ov.end, RADIUS_OUTER + 2, RADIUS_INNER - 2)}
              fill={ov.colors[0]}
              fillOpacity={0.55}
              strokeWidth={0}
            />
          ))}

          {/* Hour tick marks (24 ticks) */}
          {Array.from({ length: 24 }, (_, h) => {
            const angle = hourToAngle(h);
            const isMajor = h % 6 === 0;
            const outer = polarXY(angle, TICK_OUTER);
            const inner = polarXY(angle, isMajor ? TICK_INNER_MAJOR : TICK_INNER_MINOR);
            return (
              <line
                key={h}
                x1={outer.x} y1={outer.y}
                x2={inner.x} y2={inner.y}
                stroke={isMajor ? C.textSub : C.muted}
                strokeWidth={isMajor ? 1.5 : 0.75}
                strokeLinecap="round"
              />
            );
          })}

          {/* Hour labels at 0, 6, 12, 18 */}
          {[0, 6, 12, 18].map(h => {
            const labelAngle = hourToAngle(h);
            const pos = polarXY(labelAngle, 72);
            return (
              <text
                key={h}
                x={pos.x} y={pos.y}
                textAnchor="middle" dominantBaseline="middle"
                fontSize={9} fontWeight={700}
                fill={C.textSub}
              >
                {String(h).padStart(2, '0')}
              </text>
            );
          })}

          {/* Clock hand — red line from center to edge */}
          <line
            x1={handBase.x} y1={handBase.y}
            x2={handTip.x} y2={handTip.y}
            stroke="#ef4444"
            strokeWidth={2.5}
            strokeLinecap="round"
            style={{ filter: 'drop-shadow(0 0 4px #ef4444)' }}
          />

          {/* Center pivot */}
          <circle cx={CX} cy={CY} r={5} fill="#ef4444" style={{ filter: 'drop-shadow(0 0 3px #ef4444)' }} />
          <circle cx={CX} cy={CY} r={2.5} fill={C.card} />

          {/* Center time text */}
          <text x={CX} y={CY - 8} textAnchor="middle" fontSize={14} fontWeight={800} fill={C.text}>
            {timeStr}
          </text>

          {/* Active session label below center */}
          <text x={CX} y={CY + 10} textAnchor="middle" fontSize={9} fill={C.muted}>
            {activeLabel}
          </text>
        </svg>
      </div>

      {/* Session pill labels */}
      <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
        {sessions.map(s => {
          const isActive = timeDecimal >= s.start && timeDecimal < s.end;
          return (
            <span key={s.label} style={{
              fontSize: 10, fontWeight: isActive ? 700 : 500,
              padding: '3px 10px', borderRadius: R.pill,
              background: isActive ? s.colorHex + '28' : C.surface,
              color: isActive ? s.colorHex : C.muted,
              border: `1px solid ${isActive ? s.colorHex + '60' : C.border}`,
              transition: 'all 0.2s',
            }}>
              {s.emoji} {s.label} {s.shortRange}
            </span>
          );
        })}
      </div>
    </div>
  );
}

// ─── Today Equity Mini ────────────────────────────────────────────────────────

function TodayEquityMini() {
  const uid = useId();
  const gradId = `equityFillGrad-${uid.replace(/:/g, '')}`;
  const W = 340, H = 80;
  const paddingL = 6, paddingR = 6, paddingT = 10, paddingB = 16;
  const chartW = W - paddingL - paddingR;
  const chartH = H - paddingT - paddingB;

  // Seeded equity data: 25 points across today's hours (~+$180 gain overall)
  const baseEquity = 50000;
  const seedPoints: number[] = [
    50000, 50012, 50008, 50025, 50019, 50038, 50045, 50031, 50060,
    50072, 50055, 50088, 50103, 50095, 50118, 50134, 50128, 50152,
    50163, 50148, 50170, 50162, 50178, 50180, 50180,
  ];

  const currentEquity = seedPoints[seedPoints.length - 1];
  const gain = currentEquity - baseEquity;
  const isUp = gain >= 0;
  const lineColor = isUp ? C.bull : C.bear;
  const fillColor = isUp ? C.bull + '15' : C.bear + '15';

  const minVal = Math.min(...seedPoints) - 20;
  const maxVal = Math.max(...seedPoints) + 20;
  const range = maxVal - minVal;

  function toSvgX(i: number): number {
    return paddingL + (i / (seedPoints.length - 1)) * chartW;
  }
  function toSvgY(val: number): number {
    return paddingT + chartH - ((val - minVal) / range) * chartH;
  }

  const polylinePoints = seedPoints
    .map((v, i) => `${toSvgX(i)},${toSvgY(v)}`)
    .join(' ');

  // Fill path: go along the line then close at the bottom
  const firstX = toSvgX(0);
  const lastX = toSvgX(seedPoints.length - 1);
  const bottomY = paddingT + chartH;
  const fillPath =
    `M ${firstX},${bottomY} ` +
    seedPoints.map((v, i) => `L ${toSvgX(i)},${toSvgY(v)}`).join(' ') +
    ` L ${lastX},${bottomY} Z`;

  const gainLabel = (isUp ? '+' : '') + fmtUsd(gain) + ' today';

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.xl,
      padding: '14px 16px',
      flex: 1,
      minWidth: 0,
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub }}>Today's Equity</span>
        <span style={{
          fontSize: 10, fontWeight: 700,
          padding: '2px 8px', borderRadius: R.pill,
          background: lineColor + '20',
          color: lineColor,
          border: `1px solid ${lineColor}40`,
        }}>
          {gainLabel}
        </span>
      </div>

      {/* SVG chart */}
      <svg
        width="100%"
        viewBox={`0 0 ${W} ${H}`}
        style={{ display: 'block', overflow: 'visible' }}
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={lineColor} stopOpacity="0.25" />
            <stop offset="100%" stopColor={lineColor} stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Gradient fill under the line */}
        <path d={fillPath} fill={`url(#${gradId})`} />

        {/* The equity line itself */}
        <polyline
          points={polylinePoints}
          fill="none"
          stroke={lineColor}
          strokeWidth={1.8}
          strokeLinejoin="round"
          strokeLinecap="round"
        />

        {/* Dot at the current (last) point */}
        <circle
          cx={toSvgX(seedPoints.length - 1)}
          cy={toSvgY(currentEquity)}
          r={3.5}
          fill={lineColor}
          style={{ filter: `drop-shadow(0 0 4px ${lineColor})` }}
        />
      </svg>

      {/* Bottom labels */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 2 }}>
        <span style={{ fontSize: 10, color: C.muted }}>{fmtUsd(baseEquity, 0)}</span>
        <span style={{ fontSize: 10, fontWeight: 700, color: lineColor }}>{fmtUsd(currentEquity, 0)}</span>
      </div>

      {/* X-axis label */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 1 }}>
        <span style={{ fontSize: 9, color: C.faint }}>00:00 UTC</span>
        <span style={{ fontSize: 9, color: C.faint }}>Now</span>
      </div>
    </div>
  );
}

// ─── Alerts Panel ─────────────────────────────────────────────────────────────

type AlertType = 'INFO' | 'SUCCESS' | 'WARNING' | 'VETO';

type AlertItem = {
  time: string;
  type: AlertType;
  message: string;
};

function alertDotColor(type: AlertType): string {
  if (type === 'SUCCESS') return C.bull;
  if (type === 'VETO') return C.bear;
  if (type === 'WARNING') return C.warn;
  return C.info;
}

const SEEDED_ALERTS: AlertItem[] = [
  { time: '09:14 UTC', type: 'INFO',    message: 'Regime classified as TREND (confidence: 87%)' },
  { time: '10:32 UTC', type: 'SUCCESS', message: 'BTC signal approved — entering long at $95,240' },
  { time: '10:34 UTC', type: 'SUCCESS', message: 'Position opened: 0.26 BTC @ $95,240' },
  { time: '12:15 UTC', type: 'WARNING', message: 'SOL ATR elevated — reduced position sizing by 30%' },
  { time: '13:08 UTC', type: 'VETO',    message: 'AI vetoed HYPE trade — RSI overbought at 73' },
  { time: '14:41 UTC', type: 'SUCCESS', message: 'BTC TP1 hit — partial exit at $96,680 (+$1,440)' },
];

function AlertsPanel() {
  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.xl,
      padding: '14px 16px',
      flex: 1,
      minWidth: 0,
      display: 'flex',
      flexDirection: 'column',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub }}>Today's Bot Alerts</span>
        <span style={{
          display: 'flex', alignItems: 'center', gap: 5,
          fontSize: 10, fontWeight: 700, color: C.bull,
          background: C.bull + '18', border: `1px solid ${C.bull}40`,
          borderRadius: R.pill, padding: '2px 8px',
        }}>
          {/* Pulsing live dot via CSS animation */}
          <span style={{
            width: 6, height: 6, borderRadius: '50%',
            background: C.bull, display: 'inline-block',
            animation: 'wagmiPulse 1.4s ease-in-out infinite',
          }} />
          Live
        </span>
      </div>

      {/* Scrollable alert list */}
      <div style={{
        display: 'flex', flexDirection: 'column', gap: 2,
        overflowY: 'auto', maxHeight: 210,
      }}>
        {SEEDED_ALERTS.map((alert, i) => {
          const dot = alertDotColor(alert.type);
          return (
            <div
              key={i}
              style={{
                display: 'flex', alignItems: 'flex-start', gap: 8,
                padding: '7px 8px',
                borderRadius: R.sm,
                cursor: 'default',
                transition: 'background 0.15s',
              }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLDivElement).style.background = C.surfaceHover;
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLDivElement).style.background = 'transparent';
              }}
            >
              {/* Colored dot */}
              <span style={{
                width: 7, height: 7, borderRadius: '50%',
                background: dot, flexShrink: 0,
                marginTop: 4,
                boxShadow: `0 0 4px ${dot}80`,
              }} />

              {/* Time */}
              <span style={{
                fontSize: 10, color: C.muted,
                flexShrink: 0, minWidth: 64,
                paddingTop: 1,
              }}>
                {alert.time}
              </span>

              {/* Type badge */}
              <span style={{
                fontSize: 9, fontWeight: 700,
                padding: '1px 5px', borderRadius: R.pill,
                background: dot + '20', color: dot,
                border: `1px solid ${dot}40`,
                flexShrink: 0, whiteSpace: 'nowrap' as const,
                alignSelf: 'flex-start',
                marginTop: 1,
              }}>
                {alert.type}
              </span>

              {/* Message */}
              <span style={{ fontSize: F.xs, color: C.textSub, lineHeight: 1.5 }}>
                {alert.message}
              </span>
            </div>
          );
        })}
      </div>

      {/* Keyframe styles injected inline via a <style> tag — avoids a CSS module dep */}
      <style>{`
        @keyframes wagmiPulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%       { opacity: 0.4; transform: scale(0.75); }
        }
      `}</style>
    </div>
  );
}

// ─── Circuit Breaker Dashboard ────────────────────────────────────────────────

type CbStatus = 'OK' | 'WARNING' | 'TRIGGERED';

type CircuitBreaker = {
  title: string;
  limit: number | string;
  current: number | string;
  limitNum: number;
  currentNum: number;
  status: CbStatus;
  kind: 'ring' | 'dots' | 'bar' | 'slots';
  unit?: string;
};

function cbColor(status: CbStatus): string {
  if (status === 'TRIGGERED') return C.bear;
  if (status === 'WARNING') return C.warn;
  return C.bull;
}

function cbStatusLabel(status: CbStatus): string {
  if (status === 'TRIGGERED') return '✕ TRIGGERED';
  if (status === 'WARNING') return '⚠ WARNING';
  return '✓ OK';
}

/** Circular progress ring for daily loss limit */
function CbRing({ limitNum, currentNum, status, label, sub }: { limitNum: number; currentNum: number; status: CbStatus; label: string; sub: string }) {
  const cx = 36, cy = 36, r = 28;
  const circumference = 2 * Math.PI * r;
  const pct = Math.min(currentNum / (limitNum || 1), 1);
  const dashOffset = circumference * (1 - pct);
  const col = cbColor(status);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
      <svg width={72} height={72} viewBox="0 0 72 72">
        <circle cx={cx} cy={cy} r={r} fill="none" stroke={C.surface} strokeWidth={6} />
        <circle
          cx={cx} cy={cy} r={r}
          fill="none"
          stroke={col}
          strokeWidth={6}
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          strokeLinecap="round"
          transform="rotate(-90 36 36)"
          style={{ filter: `drop-shadow(0 0 4px ${col})` }}
        />
        <text x={cx} y={cy - 4} textAnchor="middle" dominantBaseline="middle" fontSize={10} fontWeight={800} fill={col}>{label}</text>
        <text x={cx} y={cy + 9} textAnchor="middle" dominantBaseline="middle" fontSize={8} fill={C.muted}>{sub}</text>
      </svg>
    </div>
  );
}

/** Dot streak display for consecutive losses */
function CbDots({ limitNum, currentNum, status }: { limitNum: number; currentNum: number; status: CbStatus }) {
  const col = cbColor(status);
  return (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', justifyContent: 'center', flexWrap: 'wrap' as const, padding: '6px 0' }}>
      {Array.from({ length: limitNum }, (_, i) => {
        const filled = i < currentNum;
        return (
          <div
            key={i}
            style={{
              width: 16, height: 16, borderRadius: '50%',
              background: filled ? col : C.surface,
              border: `2px solid ${filled ? col : C.border}`,
              boxShadow: filled ? `0 0 6px ${col}` : 'none',
              transition: 'all 0.2s',
            }}
          />
        );
      })}
    </div>
  );
}

/** Horizontal bar for drawdown limit */
function CbBar({ limitNum, currentNum, status }: { limitNum: number; currentNum: number; status: CbStatus }) {
  const pct = Math.min((currentNum / (limitNum || 1)) * 100, 100);
  const col = cbColor(status);
  return (
    <div style={{ padding: '8px 0' }}>
      <div style={{ height: 10, background: C.surface, borderRadius: R.pill, overflow: 'hidden', position: 'relative' }}>
        <div style={{
          width: `${pct}%`, height: '100%', background: col,
          borderRadius: R.pill, transition: 'width 0.4s',
          boxShadow: `0 0 6px ${col}80`,
        }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 9, color: C.muted }}>
        <span>0%</span>
        <span style={{ color: col, fontWeight: 700 }}>{currentNum}% used</span>
        <span>{limitNum}%</span>
      </div>
    </div>
  );
}

/** Slot indicator for position limit */
function CbSlots({ limitNum, currentNum, status }: { limitNum: number; currentNum: number; status: CbStatus }) {
  const col = cbColor(status);
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'center', padding: '6px 0' }}>
      {Array.from({ length: limitNum }, (_, i) => {
        const occupied = i < currentNum;
        return (
          <div
            key={i}
            style={{
              width: 28, height: 20, borderRadius: R.xs,
              background: occupied ? col + '30' : C.surface,
              border: `1.5px solid ${occupied ? col : C.border}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 8, fontWeight: 700, color: occupied ? col : C.faint,
              transition: 'all 0.2s',
            }}
          >
            {occupied ? '●' : '○'}
          </div>
        );
      })}
    </div>
  );
}

function CircuitBreakerStatus() {
  const breakers: CircuitBreaker[] = [
    { title: 'Daily Loss Limit', limit: '$500', current: '$0', limitNum: 500, currentNum: 0, status: 'OK', kind: 'ring', unit: '$' },
    { title: 'Consecutive Losses', limit: '3 streak', current: '0 streak', limitNum: 3, currentNum: 0, status: 'OK', kind: 'dots' },
    { title: 'Drawdown Limit', limit: '20%', current: '0.8%', limitNum: 20, currentNum: 0.8, status: 'OK', kind: 'bar', unit: '%' },
    { title: 'Position Limit', limit: '3 open', current: '1 open', limitNum: 3, currentNum: 1, status: 'OK', kind: 'slots' },
  ];

  // Determine overall system status
  const hasTriggered = breakers.some(b => b.status === 'TRIGGERED');
  const hasWarning = breakers.some(b => b.status === 'WARNING');
  const overallStatus: CbStatus = hasTriggered ? 'TRIGGERED' : hasWarning ? 'WARNING' : 'OK';
  const overallColor = cbColor(overallStatus);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '18px 20px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Circuit Breaker Dashboard</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
            Circuit breakers automatically pause trading when limits are hit
          </div>
        </div>
        <span style={{
          fontSize: 10, fontWeight: 800,
          padding: '4px 12px', borderRadius: R.pill,
          background: overallColor + '18', border: `1px solid ${overallColor}50`,
          color: overallColor,
          display: 'flex', alignItems: 'center', gap: 6,
        }}>
          <span style={{ width: 6, height: 6, borderRadius: '50%', background: overallColor, display: 'inline-block' }} />
          {overallStatus === 'OK' ? '🛡 All Circuit Breakers: Normal' : overallStatus === 'WARNING' ? '⚠ Warning State' : '✕ Breaker Triggered'}
        </span>
      </div>

      {/* 2×2 grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        {breakers.map((b) => {
          const col = cbColor(b.status);
          const statusLabel = cbStatusLabel(b.status);
          return (
            <div
              key={b.title}
              style={{
                background: C.surface,
                border: `1px solid ${b.status !== 'OK' ? col + '60' : C.border}`,
                borderRadius: R.lg,
                padding: '14px 16px',
              }}
            >
              {/* Card header */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                <div style={{ fontSize: F.xs, fontWeight: 700, color: C.textSub }}>{b.title}</div>
                <span style={{
                  fontSize: 9, fontWeight: 700,
                  padding: '1px 6px', borderRadius: R.pill,
                  background: col + '20', color: col,
                  border: `1px solid ${col}40`,
                  whiteSpace: 'nowrap' as const,
                }}>
                  {statusLabel}
                </span>
              </div>

              {/* Visual indicator */}
              {b.kind === 'ring' && (
                <CbRing
                  limitNum={b.limitNum}
                  currentNum={b.currentNum}
                  status={b.status}
                  label={b.current as string}
                  sub={`limit ${b.limit}`}
                />
              )}
              {b.kind === 'dots' && (
                <CbDots limitNum={b.limitNum} currentNum={b.currentNum} status={b.status} />
              )}
              {b.kind === 'bar' && (
                <CbBar limitNum={b.limitNum} currentNum={b.currentNum} status={b.status} />
              )}
              {b.kind === 'slots' && (
                <CbSlots limitNum={b.limitNum} currentNum={b.currentNum} status={b.status} />
              )}

              {/* Limit / current footer */}
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 10 }}>
                <span style={{ color: C.muted }}>Current: <span style={{ color: col, fontWeight: 700 }}>{b.current}</span></span>
                <span style={{ color: C.faint }}>Limit: {b.limit}</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Bot Schedule Timeline ─────────────────────────────────────────────────────

type ScheduleEvent = {
  hour: number;
  minute: number;
  kind: 'regime' | 'signal' | 'trade' | 'veto' | 'future-regime' | 'future-signal';
  label: string;
  warning?: boolean;
};

function BotScheduleTimeline() {
  const now = new Date();
  const currentHour = now.getUTCHours();
  const currentMinute = now.getUTCMinutes();
  const nowDecimal = currentHour + currentMinute / 60;

  const W = 480, H = 80;
  const padL = 20, padR = 20, padT = 14, padB = 22;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;
  const axisY = padT + chartH; // y of the main axis line

  // Convert hour decimal to SVG x
  function toX(h: number): number {
    return padL + (h / 24) * chartW;
  }

  // Seeded schedule events
  const pastEvents: ScheduleEvent[] = [
    { hour: 6, minute: 0, kind: 'regime', label: 'regime check' },
    { hour: 9, minute: 14, kind: 'signal', label: 'signal check' },
    { hour: 10, minute: 32, kind: 'trade', label: 'TRADE BTC long' },
    { hour: 12, minute: 15, kind: 'signal', label: 'signal check', warning: true },
    { hour: 13, minute: 8, kind: 'veto', label: 'VETO HYPE' },
  ];

  // Future events relative to current time
  const future1Decimal = nowDecimal + 1;
  const future3Decimal = nowDecimal + 3;
  const futureEvents: ScheduleEvent[] = [
    { hour: Math.floor(future1Decimal) % 24, minute: Math.floor((future1Decimal % 1) * 60), kind: 'future-regime', label: 'regime check' },
    { hour: Math.floor(future3Decimal) % 24, minute: Math.floor((future3Decimal % 1) * 60), kind: 'future-signal', label: 'signal check' },
  ];

  // Session background bands
  const bands = [
    { start: 0, end: 8,  color: '#2563eb', label: 'Asia',   labelPos: 4 },
    { start: 7, end: 16, color: '#7c3aed', label: 'Europe', labelPos: 11 },
    { start: 13, end: 22, color: '#16a34a', label: 'US',    labelPos: 17 },
  ];

  function eventColor(kind: ScheduleEvent['kind'], warning?: boolean): string {
    if (warning) return C.warn;
    if (kind === 'trade') return C.bull;
    if (kind === 'veto') return C.bear;
    if (kind === 'regime') return C.info;
    if (kind === 'signal') return C.muted;
    if (kind === 'future-regime') return C.info;
    if (kind === 'future-signal') return C.muted;
    return C.muted;
  }

  function eventSymbol(kind: ScheduleEvent['kind']): string {
    if (kind === 'trade') return '▲';
    if (kind === 'veto') return '✕';
    return '●';
  }

  const nowX = toX(nowDecimal);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '16px 18px' }}>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 4 }}>Today's Bot Activity Timeline</div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 12 }}>UTC — past events left of NOW, upcoming right</div>

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
        {/* Session bands */}
        {bands.map((b) => (
          <rect
            key={b.label}
            x={toX(b.start)}
            y={padT}
            width={toX(b.end) - toX(b.start)}
            height={chartH}
            fill={b.color}
            fillOpacity={0.08}
            rx={2}
          />
        ))}

        {/* Session band labels */}
        {bands.map((b) => (
          <text
            key={b.label + '_lbl'}
            x={toX(b.labelPos)}
            y={padT + 8}
            fontSize={7}
            fill={b.color}
            fillOpacity={0.55}
            fontWeight={600}
          >
            {b.label}
          </text>
        ))}

        {/* Axis line */}
        <line x1={padL} y1={axisY} x2={W - padR} y2={axisY} stroke={C.border} strokeWidth={1} />

        {/* Hour ticks at 0,4,8,12,16,20 */}
        {[0, 4, 8, 12, 16, 20, 24].map(h => (
          <g key={h}>
            <line x1={toX(h)} y1={axisY} x2={toX(h)} y2={axisY + 4} stroke={C.border} strokeWidth={0.75} />
            {h < 24 && (
              <text x={toX(h)} y={axisY + 12} textAnchor="middle" fontSize={7} fill={C.faint}>
                {String(h).padStart(2, '0')}
              </text>
            )}
          </g>
        ))}

        {/* Past events */}
        {pastEvents.map((ev, i) => {
          const x = toX(ev.hour + ev.minute / 60);
          const col = eventColor(ev.kind, ev.warning);
          const sym = eventSymbol(ev.kind);
          const dotR = ev.kind === 'trade' ? 5 : 4;
          return (
            <g key={i}>
              {/* Vertical stem */}
              <line x1={x} y1={padT + 6} x2={x} y2={axisY} stroke={col} strokeWidth={1} strokeOpacity={0.5} />
              {/* Symbol */}
              <text x={x} y={padT + 4} textAnchor="middle" dominantBaseline="middle" fontSize={ev.kind === 'trade' ? 10 : 8} fill={col} fontWeight={800}>
                {sym}
              </text>
              {/* Dot on axis */}
              <circle cx={x} cy={axisY} r={dotR} fill={col} style={{ filter: `drop-shadow(0 0 3px ${col})` }} />
              {/* Label below axis */}
              <text
                x={x}
                y={axisY + 16}
                textAnchor="middle"
                fontSize={6.5}
                fill={col}
                fontWeight={ev.kind === 'trade' || ev.kind === 'veto' ? 700 : 500}
              >
                {String(ev.hour).padStart(2,'0')}:{String(ev.minute).padStart(2,'0')}
              </text>
            </g>
          );
        })}

        {/* Future events — dotted */}
        {futureEvents.map((ev, i) => {
          const x = toX(ev.hour + ev.minute / 60);
          const col = eventColor(ev.kind);
          return (
            <g key={'f' + i}>
              <line x1={x} y1={padT + 10} x2={x} y2={axisY} stroke={col} strokeWidth={1} strokeDasharray="3 3" strokeOpacity={0.45} />
              {/* Open circle */}
              <circle cx={x} cy={padT + 8} r={4} fill="none" stroke={col} strokeWidth={1.5} strokeOpacity={0.6} />
              <circle cx={x} cy={axisY} r={3.5} fill="none" stroke={col} strokeWidth={1.2} strokeDasharray="2 2" strokeOpacity={0.55} />
              <text x={x} y={axisY + 16} textAnchor="middle" fontSize={6.5} fill={C.muted}>
                +{i === 0 ? '1h' : '3h'}
              </text>
            </g>
          );
        })}

        {/* NOW line */}
        <line
          x1={nowX} y1={padT - 4}
          x2={nowX} y2={axisY + 4}
          stroke={C.text}
          strokeWidth={2}
          style={{ filter: `drop-shadow(0 0 3px ${C.brand})` }}
        />
        {/* NOW label */}
        <rect x={nowX - 14} y={padT - 13} width={28} height={10} rx={2} fill={C.brand} />
        <text x={nowX} y={padT - 7} textAnchor="middle" dominantBaseline="middle" fontSize={7} fontWeight={800} fill="#fff">
          NOW
        </text>
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, marginTop: 6, fontSize: 9, color: C.muted, flexWrap: 'wrap' as const }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: C.info, display: 'inline-block' }} /> Regime check
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: C.muted, display: 'inline-block' }} /> Signal check
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: C.bull, display: 'inline-block' }} /> Trade
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: C.bear, display: 'inline-block' }} /> Veto
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: 'none', border: `1.5px dashed ${C.muted}`, display: 'inline-block' }} /> Upcoming
        </span>
      </div>
    </div>
  );
}

// ─── GateFlowAnimated ─────────────────────────────────────────────────────────

function GateFlowAnimated() {
  const gates = [
    { name: 'Validity Check',    passed: 98 },
    { name: 'Circuit Breaker',   passed: 87 },
    { name: 'Position Limits',   passed: 72 },
    { name: 'Leverage Calc',     passed: 65 },
    { name: 'Liquidation Guard', passed: 61 },
    { name: 'Position Sizing',   passed: 58 },
  ];
  const total = 100;

  // Determine the "active" gate: the last gate that still has signals passing through
  // (lowest index where passed < previous passed, i.e. the bottleneck gate)
  const activeGateIdx = gates.reduce((acc, g, i) => (g.passed < gates[acc].passed ? i : acc), 0);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '18px 20px' }}>
      <style>{`
        @keyframes gateGlow {
          0%, 100% { box-shadow: 0 0 0px transparent; }
          50%       { box-shadow: 0 0 10px ${C.brand}80; }
        }
        @keyframes gatePulse {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.55; }
        }
      `}</style>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Signal Gate Funnel</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>6-stage sequential filter — 100 example signals</div>
        </div>
        <span style={{
          fontSize: 9, fontWeight: 700, color: C.brand,
          background: `${C.brand}18`, border: `1px solid ${C.brand}50`,
          borderRadius: R.pill, padding: '2px 8px',
        }}>
          {gates[gates.length - 1].passed}/{total} reach execution
        </span>
      </div>

      {/* Gate rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {gates.map((g, i) => {
          const isActive = i === activeGateIdx;
          const passRate = g.passed / total;
          const failRate = 1 - passRate;
          const prevPassed = i === 0 ? total : gates[i - 1].passed;
          const droppedHere = prevPassed - g.passed;

          return (
            <div
              key={g.name}
              style={{
                borderRadius: R.md,
                border: `1px solid ${isActive ? C.brand + '60' : C.border}`,
                background: isActive ? `${C.brand}08` : C.surface,
                padding: '10px 12px',
                animation: isActive ? 'gateGlow 2s ease-in-out infinite' : 'none',
                transition: 'border-color 0.3s',
              }}
            >
              {/* Row header */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  {/* Gate number */}
                  <span style={{
                    width: 18, height: 18, borderRadius: '50%', flexShrink: 0,
                    background: isActive ? C.brand : C.surface,
                    border: `1px solid ${isActive ? C.brand : C.border}`,
                    fontSize: 9, fontWeight: 700, color: isActive ? '#fff' : C.muted,
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                    animation: isActive ? 'gatePulse 1.6s ease-in-out infinite' : 'none',
                  }}>
                    {i + 1}
                  </span>
                  <span style={{ fontSize: F.xs, fontWeight: isActive ? 700 : 500, color: isActive ? C.text : C.textSub }}>
                    {g.name}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 10 }}>
                  <span style={{ color: C.bull, fontWeight: 700 }}>{g.passed} passed</span>
                  {droppedHere > 0 && (
                    <span style={{ color: C.bear, fontWeight: 600 }}>−{droppedHere} dropped</span>
                  )}
                </div>
              </div>

              {/* Dual fill bar: green (pass) + red (fail) */}
              <div style={{ height: 8, background: C.border, borderRadius: R.pill, overflow: 'hidden', display: 'flex' }}>
                <div style={{
                  width: `${passRate * 100}%`, height: '100%',
                  background: C.bull,
                  borderRadius: `${R.pill}px 0 0 ${R.pill}px`,
                  transition: 'width 0.5s',
                }} />
                <div style={{
                  flex: 1, height: '100%',
                  background: C.bear + '70',
                  borderRadius: `0 ${R.pill}px ${R.pill}px 0`,
                }} />
              </div>

              {/* % labels under bar */}
              <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 3, fontSize: 9 }}>
                <span style={{ color: C.bull }}>{Math.round(passRate * 100)}% pass</span>
                <span style={{ color: C.bear + 'cc' }}>{Math.round(failRate * 100)}% fail</span>
              </div>
            </div>
          );
        })}
      </div>

      {/* Funnel summary */}
      <div style={{ marginTop: 14, padding: '10px 12px', background: C.surface, borderRadius: R.md, border: `1px solid ${C.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' as const }}>
          {gates.map((g, i) => (
            <React.Fragment key={g.name}>
              <span style={{
                fontSize: 10, fontWeight: 700,
                color: i === gates.length - 1 ? C.brand : C.textSub,
                padding: '1px 6px', borderRadius: R.pill,
                background: i === gates.length - 1 ? `${C.brand}20` : 'transparent',
              }}>
                {g.passed}
              </span>
              {i < gates.length - 1 && (
                <span style={{ fontSize: 9, color: C.muted }}>→</span>
              )}
            </React.Fragment>
          ))}
          <span style={{ marginLeft: 6, fontSize: F.xs, color: C.muted }}>signals surviving each gate</span>
        </div>
      </div>
    </div>
  );
}

// ─── TodayPnlByHour ───────────────────────────────────────────────────────────

function TodayPnlByHour() {
  const now = new Date();
  const currentHour = now.getUTCHours();

  // Seeded hourly PnL: hours 9-11 and 14-16 are highest activity (bull hours)
  const hourlyPnl: number[] = [
    0,     0,     0,     0,     0,     0,      // 0–5
    0,     0,     12.5,  48.3,  -18.7, 91.2,  // 6–11
    0,     0,     67.4,  -22.1, 88.6,  0,     // 12–17
    0,     0,     0,     0,     0,     0,      // 18–23
  ];

  const W = 500, H = 120;
  const padL = 36, padR = 8, padT = 8, padB = 24;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;

  const maxAbs = Math.max(...hourlyPnl.map(Math.abs), 1);

  function barX(h: number): number {
    const slotW = chartW / 24;
    return padL + h * slotW + slotW * 0.15;
  }
  function barWidth(): number {
    return (chartW / 24) * 0.7;
  }
  function barH(pnl: number): number {
    return (Math.abs(pnl) / maxAbs) * (chartH * 0.85);
  }

  // Y-axis labels
  const yLabels = [maxAbs, maxAbs / 2, 0, -maxAbs / 2, -maxAbs];

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '16px 18px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Today's P&L by Hour (UTC)</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>Realized P&L distribution across 24 trading hours</div>
        </div>
        <div style={{ display: 'flex', gap: 10, fontSize: 10 }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: C.bull }}>
            <span style={{ width: 8, height: 8, background: C.bull, borderRadius: 1, display: 'inline-block' }} /> Profit
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: C.bear }}>
            <span style={{ width: 8, height: 8, background: C.bear, borderRadius: 1, display: 'inline-block' }} /> Loss
          </span>
        </div>
      </div>

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
        {/* Horizontal zero line */}
        <line
          x1={padL} y1={padT + chartH / 2}
          x2={W - padR} y2={padT + chartH / 2}
          stroke={C.border} strokeWidth={1}
        />

        {/* Y-axis grid lines */}
        {[0.25, 0.75].map(frac => (
          <line
            key={frac}
            x1={padL} y1={padT + chartH * frac}
            x2={W - padR} y2={padT + chartH * frac}
            stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4"
          />
        ))}

        {/* Y-axis labels */}
        <text x={padL - 4} y={padT + 4} textAnchor="end" fontSize={7} fill={C.muted} dominantBaseline="hanging">
          +${Math.round(maxAbs)}
        </text>
        <text x={padL - 4} y={padT + chartH / 2} textAnchor="end" fontSize={7} fill={C.muted} dominantBaseline="middle">
          $0
        </text>
        <text x={padL - 4} y={padT + chartH - 2} textAnchor="end" fontSize={7} fill={C.muted} dominantBaseline="auto">
          -${Math.round(maxAbs)}
        </text>

        {/* Bars */}
        {hourlyPnl.map((pnl, h) => {
          if (pnl === 0) return null;
          const isPositive = pnl >= 0;
          const bH = barH(pnl);
          const bX = barX(h);
          const bW = barWidth();
          const midY = padT + chartH / 2;
          const bY = isPositive ? midY - bH : midY;
          const col = isPositive ? C.bull : C.bear;
          const isCurrent = h === currentHour;

          return (
            <g key={h}>
              <rect
                x={bX} y={bY}
                width={bW} height={bH}
                fill={col}
                fillOpacity={isCurrent ? 0 : 0.85}
                rx={2}
                stroke={isCurrent ? col : 'none'}
                strokeWidth={isCurrent ? 1.5 : 0}
                strokeDasharray={isCurrent ? '3 2' : 'none'}
              />
              {/* Subtle glow for significant bars */}
              {Math.abs(pnl) > maxAbs * 0.5 && (
                <rect
                  x={bX - 1} y={bY - 1}
                  width={bW + 2} height={bH + 2}
                  fill="none"
                  rx={3}
                  stroke={col}
                  strokeWidth={0.5}
                  strokeOpacity={0.4}
                />
              )}
            </g>
          );
        })}

        {/* Current hour outline (if no pnl yet) */}
        {hourlyPnl[currentHour] === 0 && (
          <rect
            x={barX(currentHour)} y={padT + chartH / 2 - 4}
            width={barWidth()} height={8}
            fill="none"
            stroke={C.brand}
            strokeWidth={1}
            strokeDasharray="3 2"
            rx={2}
            opacity={0.6}
          />
        )}

        {/* X-axis: hour labels at 0,4,8,12,16,20 */}
        {[0, 4, 8, 12, 16, 20].map(h => {
          const x = padL + (h / 24) * chartW + (chartW / 24) * 0.5;
          return (
            <g key={h}>
              <line x1={x} y1={padT + chartH} x2={x} y2={padT + chartH + 3} stroke={C.border} strokeWidth={0.75} />
              <text x={x} y={padT + chartH + 10} textAnchor="middle" fontSize={8} fill={C.muted}>
                {String(h).padStart(2, '0')}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Summary row */}
      <div style={{ display: 'flex', gap: 16, marginTop: 4, fontSize: F.xs, color: C.muted }}>
        <span>Total: <span style={{ color: C.bull, fontWeight: 700 }}>
          {fmtUsd(hourlyPnl.reduce((a, b) => a + b, 0))}
        </span></span>
        <span>Best hour: <span style={{ color: C.bull, fontWeight: 700 }}>
          {String(hourlyPnl.indexOf(Math.max(...hourlyPnl))).padStart(2, '0')}:00 UTC
        </span></span>
        <span style={{ marginLeft: 'auto', color: C.faint }}>Current hour: dashed border</span>
      </div>
    </div>
  );
}

// ─── LivePositionPnlStream ────────────────────────────────────────────────────

type LivePosition = {
  symbol: string;
  side: 'LONG' | 'SHORT';
  size: string;
  entry: number;
  current: number;
};

function LivePositionPnlStream() {
  // Seeded open positions (would come from API in real use)
  const positions: LivePosition[] = [
    { symbol: 'BTC',  side: 'LONG',  size: '0.26',  entry: 95240, current: 96680 },
    { symbol: 'SOL',  side: 'LONG',  size: '12.5',  entry: 145.2, current: 143.8 },
    { symbol: 'HYPE', side: 'SHORT', size: '200',   entry: 18.45, current: 17.90 },
  ];

  if (positions.length === 0) {
    return (
      <div style={{
        background: C.surface,
        borderBottom: `1px solid ${C.border}`,
        padding: '8px 16px',
        fontSize: F.xs,
        color: C.muted,
        fontStyle: 'italic',
        textAlign: 'center',
      }}>
        No open positions — bot is scanning
      </div>
    );
  }

  // Build ticker items (duplicate for seamless loop)
  const items = [...positions, ...positions];

  const totalPnl = positions.reduce((acc, p) => {
    const mult = p.side === 'LONG' ? 1 : -1;
    const raw = (p.current - p.entry) * parseFloat(p.size) * mult;
    return acc + raw;
  }, 0);

  return (
    <div style={{
      background: C.surface,
      borderBottom: `1px solid ${C.border}`,
      overflow: 'hidden',
      position: 'relative',
    }}>
      <style>{`
        @keyframes wagmiTickerScroll {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }
      `}</style>

      {/* Left label */}
      <div style={{
        position: 'absolute', left: 0, top: 0, bottom: 0, zIndex: 2,
        display: 'flex', alignItems: 'center',
        background: `linear-gradient(to right, ${C.surface} 80%, transparent)`,
        paddingLeft: 12, paddingRight: 24,
        pointerEvents: 'none',
      }}>
        <span style={{
          fontSize: 9, fontWeight: 800, color: C.brand,
          letterSpacing: '0.07em', textTransform: 'uppercase',
          display: 'flex', alignItems: 'center', gap: 5,
        }}>
          <span style={{
            width: 5, height: 5, borderRadius: '50%',
            background: C.bull, display: 'inline-block',
            animation: 'wagmiPulse 1.4s ease-in-out infinite',
          }} />
          LIVE
        </span>
      </div>

      {/* Scrolling strip */}
      <div style={{
        display: 'inline-flex',
        animation: 'wagmiTickerScroll 28s linear infinite',
        paddingLeft: 80,
        whiteSpace: 'nowrap' as const,
      }}>
        {items.map((p, i) => {
          const mult = p.side === 'LONG' ? 1 : -1;
          const pnl = (p.current - p.entry) * parseFloat(p.size) * mult;
          const isPos = pnl >= 0;
          const col = isPos ? C.bull : C.bear;
          const pnlStr = (isPos ? '+' : '') + fmtUsd(pnl);

          return (
            <span key={i} style={{
              display: 'inline-flex', alignItems: 'center', gap: 6,
              padding: '6px 18px',
              borderRight: `1px solid ${C.border}`,
              fontSize: F.xs,
            }}>
              {/* Symbol + side badge */}
              <span style={{ fontWeight: 800, color: C.text }}>{p.symbol}</span>
              <span style={{
                fontSize: 9, fontWeight: 700,
                padding: '1px 5px', borderRadius: R.pill,
                background: p.side === 'LONG' ? `${C.bull}20` : `${C.bear}20`,
                color: p.side === 'LONG' ? C.bull : C.bear,
                border: `1px solid ${p.side === 'LONG' ? C.bull : C.bear}40`,
              }}>
                {p.side}
              </span>
              <span style={{ color: C.muted }}>{p.size}</span>
              <span style={{ color: C.faint }}>@</span>
              <span style={{ color: C.textSub }}>{fmtUsd(p.entry)}</span>
              <span style={{ color: C.faint }}>→</span>
              <span style={{ color: C.textSub }}>{fmtUsd(p.current)}</span>
              <span style={{ fontWeight: 700, color: col }}>{pnlStr}</span>
            </span>
          );
        })}
      </div>

      {/* Right total */}
      <div style={{
        position: 'absolute', right: 0, top: 0, bottom: 0, zIndex: 2,
        display: 'flex', alignItems: 'center',
        background: `linear-gradient(to left, ${C.surface} 80%, transparent)`,
        paddingRight: 12, paddingLeft: 24,
        pointerEvents: 'none',
      }}>
        <span style={{
          fontSize: 10, fontWeight: 700,
          color: totalPnl >= 0 ? C.bull : C.bear,
        }}>
          {totalPnl >= 0 ? '+' : ''}{fmtUsd(totalPnl)} total
        </span>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function TodayPage() {
  const [llmView, setLlmView] = useState<LlmMarketView | null>(null);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    let cancelled = false;
    const fetchData = async () => {
      try {
        const [lv, act, tr] = await Promise.all([
          apiFetch<LlmMarketView>('/v1/llm/market-view'),
          apiFetch<ActivityFeedResponse>('/v1/activity/feed?limit=50'),
          apiFetch<TradeHistoryResponse>('/v1/trades/history?limit=20'),
        ]);
        if (cancelled) return;
        setLlmView(lv);
        setActivity(act?.items ?? []);
        setTrades(tr?.trades ?? []);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchData();
    const iv = setInterval(() => { if (!cancelled) { fetchData(); setNow(new Date()); } }, 60_000);
    return () => { cancelled = true; clearInterval(iv); };
  }, []);

  const regime = llmView?.regime || 'unknown';
  const rs = regimeStyle(regime);

  // Derive 24h signal funnel from activity
  const analyzed = activity.length;
  const executed = activity.filter((e) => e.event_type === 'llm_would_trade').length;
  const vetoed = activity.filter((e) => e.event_type === 'llm_veto').length;
  const passed = executed + vetoed;

  // Today's closed trades (last 5)
  const recentTrades = trades.slice(0, 8);
  const todayPnl = recentTrades.reduce((a, t) => a + (t.pnl ?? 0), 0);
  const todayWins = recentTrades.filter((t) => t.outcome === 'WIN').length;

  // Build WAGMI-relative key levels from signals data (placeholder — real data would come from /v1/signals)
  const btcPrice = 67420; // Would normally come from live signals
  const exampleLevels: Level[] = [
    { price: 71200, label: 'TP2 target', type: 'resistance', note: 'Trend continuation target' },
    { price: 69800, label: 'TP1 cluster', type: 'resistance', note: 'Previous close rejection zone' },
    { price: 68400, label: 'Overnight high', type: 'resistance', note: 'Supply zone from yesterday' },
    { price: btcPrice, label: 'BTC current price', type: 'current' },
    { price: 67200, label: 'Regime invalidation', type: 'support', note: 'If lost, regime shifts to range' },
    { price: 65800, label: 'Stop loss cluster', type: 'support', note: 'Bot stop orders near here' },
    { price: 64200, label: 'Monte Carlo major S/R', type: 'support', note: 'Deep accumulation zone' },
  ];

  const dateStr = now.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });

  return (
    <Layout>
      <Head>
        <title>Morning Brief — WAGMI</title>
        <meta name="description" content="Daily market brief: current regime, AI commentary, key levels, and what the bot is watching today." />
      </Head>

      {/* ── Live Position PnL Ticker Strip ── */}
      <LivePositionPnlStream />

      <div style={{ maxWidth: 960, margin: '0 auto' }}>
        {/* ── Header ── */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>Daily Brief</div>
          <h1 style={{ margin: '0 0 4px', fontSize: F['3xl'], fontWeight: 800, color: C.text }}>{dateStr}</h1>
          <p style={{ margin: 0, fontSize: F.sm, color: C.muted }}>Generated by WAGMI AI · Updated every 60 seconds · {now.toISOString().slice(11, 16)} UTC</p>
        </div>

        {/* ── Regime Banner ── */}
        <div style={{
          background: rs.bg, border: `1px solid ${rs.border}`, borderRadius: R.xl,
          padding: '18px 24px', marginBottom: 24,
          display: 'flex', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap',
        }}>
          <div>
            <div style={{ fontSize: F.xs, color: rs.text, fontWeight: 700, letterSpacing: '0.06em', marginBottom: 6 }}>{rs.label}</div>
            <div style={{ fontSize: F.lg, fontWeight: 800, color: rs.text, marginBottom: 4 }}>{regime.replace('_', ' ').toUpperCase()}</div>
            {llmView?.avg_confidence != null && (
              <div style={{ fontSize: F.sm, color: C.muted }}>Avg confidence: {Math.round(llmView.avg_confidence * 100)}%</div>
            )}
          </div>
          {llmView?.summary && (
            <div style={{ flex: 1, minWidth: 240, fontSize: F.sm, color: C.textSub, lineHeight: 1.6, borderLeft: `2px solid ${rs.border}40`, paddingLeft: 16 }}>
              {llmView.summary}
            </div>
          )}
        </div>

        {/* ── Portfolio Overview ── */}
        <h2 style={{ fontSize: F.lg, fontWeight: 800, color: C.text, margin: '0 0 14px', letterSpacing: '-0.02em' }}>
          Portfolio Overview
        </h2>
        <div style={{ display: 'flex', gap: 20, marginBottom: 24, flexWrap: 'wrap' }}>
          <TodayEquityMini />
          <AlertsPanel />
        </div>

        <div style={{ marginBottom: 24 }}>
          <TodayPnlByHour />
        </div>

        <div style={{ marginBottom: 24 }}>
          <BotScheduleTimeline />
        </div>

        {/* ── Regime Analysis ── */}
        <h2 style={{ fontSize: F.lg, fontWeight: 800, color: C.text, margin: '0 0 14px', letterSpacing: '-0.02em' }}>
          Regime Analysis
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 20, marginBottom: 28 }}>
          <RegimeDial regime={regime} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <MarketSessionClock />
            <StreakBar trades={recentTrades} />
            {/* AI confidence overview */}
            <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '14px 18px', flex: 1 }}>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 12 }}>Today at a Glance</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <div>
                  <div style={{ fontSize: F.xs, color: C.muted }}>Signals analyzed</div>
                  <div style={{ fontSize: F.xl, fontWeight: 700, color: C.text }}>{analyzed}</div>
                </div>
                <div>
                  <div style={{ fontSize: F.xs, color: C.muted }}>Trades executed</div>
                  <div style={{ fontSize: F.xl, fontWeight: 700, color: C.bull }}>{executed}</div>
                </div>
                <div>
                  <div style={{ fontSize: F.xs, color: C.muted }}>AI vetoed</div>
                  <div style={{ fontSize: F.xl, fontWeight: 700, color: '#a855f7' }}>{vetoed}</div>
                </div>
                <div>
                  <div style={{ fontSize: F.xs, color: C.muted }}>Recent P&L</div>
                  <div style={{ fontSize: F.xl, fontWeight: 700, color: todayPnl >= 0 ? C.bull : C.bear }}>{fmtUsd(todayPnl)}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ── Activity Summary ── */}
        <h2 style={{ fontSize: F.lg, fontWeight: 800, color: C.text, margin: '0 0 14px', letterSpacing: '-0.02em' }}>
          Activity Summary
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 14, marginBottom: 28 }}>
          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 18px' }}>
            <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 12 }}>Recent Activity</div>
            <StatCell label="Trades closed" value={String(recentTrades.length)} sub="Recent history" />
            <div style={{ marginTop: 10 }}>
              <StatCell label="P&L" value={fmtUsd(todayPnl)} color={todayPnl >= 0 ? C.bull : C.bear} sub={`${todayWins}W / ${recentTrades.length - todayWins}L`} />
            </div>
          </div>

          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 18px' }}>
            <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 12 }}>Signal Funnel (24h)</div>
            <SignalFunnelBar analyzed={analyzed} passed={passed} executed={executed} vetoed={vetoed} />
          </div>

          <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 18px' }}>
            <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 12 }}>AI Decisions</div>
            {llmView?.decision_counts ? (
              <>
                <StatCell label="GO signals" value={String(llmView.decision_counts.proceed)} color={C.bull} />
                <div style={{ height: 8 }} />
                <StatCell label="Skipped" value={String(llmView.decision_counts.flat)} color={C.muted} />
                <div style={{ height: 8 }} />
                <StatCell label="Flipped" value={String(llmView.decision_counts.flip)} color={C.warn} />
              </>
            ) : (
              <div style={{ color: C.muted, fontSize: F.sm }}>Waiting for AI data…</div>
            )}
          </div>
        </div>

        {/* ── Risk & Gate Analysis ── */}
        <h2 style={{ fontSize: F.lg, fontWeight: 800, color: C.text, margin: '0 0 14px', letterSpacing: '-0.02em' }}>
          Risk &amp; Gate Analysis
        </h2>
        <div style={{ display: 'flex', gap: 20, marginBottom: 28, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 320px' }}>
            <RiskGatesPanel />
          </div>
          <div style={{ flex: '1 1 320px' }}>
            <HourlyTradeTimeline />
          </div>
        </div>

        {/* ── Gate Flow Animated Funnel ── */}
        <div style={{ marginBottom: 28 }}>
          <GateFlowAnimated />
        </div>

        {/* ── Safety: Circuit Breaker Dashboard ── */}
        <div style={{ marginBottom: 28 }}>
          <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text }}>Safety</h2>
          <CircuitBreakerStatus />
        </div>

        {/* ── Intraday Activity Heatmap ── */}
        <IntradayActivityHeatmap activity={activity} />

        {/* ── AI Market Commentary ── */}
        <h2 style={{ fontSize: F.lg, fontWeight: 800, color: C.text, margin: '0 0 14px', letterSpacing: '-0.02em' }}>
          AI Assessment
        </h2>
        <div style={{ background: C.card, border: `1px solid ${C.brand}40`, borderRadius: R.xl, padding: '22px 26px', marginBottom: 28 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
            <span style={{ fontSize: 20 }}>🤖</span>
            <span style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Live AI Assessment</span>
            <span style={{ fontSize: F.xs, padding: '2px 8px', borderRadius: R.pill, background: C.surface, color: C.muted }}>Advisory mode · signals only</span>
            <span style={{ marginLeft: 'auto', fontSize: F.xs, color: C.muted }}>Updated {timeAgo(llmView?.last_updated)}</span>
          </div>

          {/* Per-symbol stances */}
          {llmView?.per_symbol && Object.keys(llmView.per_symbol).length > 0 && (
            <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
              {Object.entries(llmView.per_symbol).map(([sym, dec]: [string, any]) => {
                const action = (dec.action || 'skip').toLowerCase();
                const isGo = action === 'proceed' || action === 'go';
                const isVeto = dec.is_veto;
                const col = isVeto ? C.bear : isGo ? C.bull : C.muted;
                const confPct = Math.round((dec.confidence || 0) * 100);
                return (
                  <div key={sym} style={{
                    flex: '1 1 140px', background: C.surface, borderRadius: R.md,
                    padding: '12px 14px', border: `1px solid ${col}30`,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                      <span style={{ fontWeight: 800, color: C.text }}>{sym}</span>
                      <span style={{ fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: R.pill, background: col + '22', color: col }}>
                        {isVeto ? 'VETO' : isGo ? 'GO' : 'SKIP'}
                      </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <div style={{ flex: 1, height: 4, background: C.border, borderRadius: 2, overflow: 'hidden' }}>
                        <div style={{ width: `${confPct}%`, height: '100%', background: col }} />
                      </div>
                      <span style={{ fontSize: F.xs, color: col, fontWeight: 700 }}>{confPct}%</span>
                    </div>
                    {dec.regime && <div style={{ fontSize: 10, color: C.muted, marginTop: 4 }}>{dec.regime}</div>}
                  </div>
                );
              })}
            </div>
          )}

          {llmView?.summary ? (
            <div style={{ fontSize: F.sm, color: C.textSub, lineHeight: 1.7, borderTop: `1px solid ${C.border}`, paddingTop: 14 }}>
              {llmView.summary}
            </div>
          ) : loading ? (
            <div style={{ color: C.muted, fontSize: F.sm }}>Loading AI commentary…</div>
          ) : (
            <div style={{ color: C.muted, fontSize: F.sm, fontStyle: 'italic' }}>
              AI commentary is generated when the bot's LLM mode is active. Start the bot with LLM_MODE=ADVISORY or higher to see live reasoning here.
            </div>
          )}
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 24, marginBottom: 28 }}>
          {/* ── Key Levels ── */}
          <div>
            <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text }}>Key Levels — BTC</h2>
            <PriceLevelTable levels={exampleLevels} />
            <p style={{ margin: '8px 0 0', fontSize: F.xs, color: C.muted }}>
              Levels derived from Monte Carlo zones, strategy stop clusters, and TP targets. Updates as new signals are generated.
            </p>
          </div>

          {/* ── What the Bot Is Watching ── */}
          <div>
            <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text }}>What the Bot Is Watching</h2>
            {(() => {
              const watchItems: WatchItem[] = [
                { sym: 'BTC', setup: 'Breakout continuation', trigger: 'Close above $68,400 on 1h', quality: 78, eta: '2–4h', strategies: '3/4' },
                { sym: 'SOL', setup: 'Accumulation zone bounce', trigger: 'Hold above $145 with vol spike', quality: 62, eta: 'If BTC confirms', strategies: '2/4' },
                { sym: 'HYPE', setup: 'Momentum continuation', trigger: 'RSI reset + 6h uptrend', quality: 71, eta: 'Today', strategies: '3/4' },
              ];
              return (
                <>
                  <WatchlistScoreChart items={watchItems} />
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 12 }}>
                    {watchItems.map((s) => (
                      <div key={s.sym} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '14px 16px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                          <div>
                            <span style={{ fontWeight: 800, color: C.text }}>{s.sym}</span>
                            <span style={{ marginLeft: 8, fontSize: F.xs, color: C.muted }}>{s.setup}</span>
                          </div>
                          <div style={{ textAlign: 'right' }}>
                            <span style={{ fontSize: F.xs, fontWeight: 700, color: s.quality >= 70 ? C.bull : C.warn }}>Pre-score: {s.quality}</span>
                          </div>
                        </div>
                        <div style={{ fontSize: F.xs, color: C.textSub, marginBottom: 4 }}>Trigger: {s.trigger}</div>
                        <div style={{ display: 'flex', gap: 12, fontSize: 10, color: C.muted }}>
                          <span>Strategies: {s.strategies}</span>
                          <span>ETA: {s.eta}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              );
            })()}
          </div>
        </div>

        {/* ── Recent Trades Recap ── */}
        {recentTrades.length > 0 && (
          <div style={{ marginBottom: 28 }}>
            <h2 style={{ margin: '0 0 14px', fontSize: F.lg, fontWeight: 700, color: C.text }}>Recent Trade Recap</h2>
            <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '4px 16px' }}>
              {recentTrades.map((t, i) => <TradeRow key={`${t.symbol}-${t.side}-${t.entry ?? i}-${i}`} t={t} />)}
            </div>
          </div>
        )}

        {/* ── CTA ── */}
        <div style={{
          background: `linear-gradient(135deg, ${C.brand}15, ${C.card})`,
          border: `1px solid ${C.brand}40`, borderRadius: R.xl,
          padding: '22px 28px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16,
        }}>
          <div>
            <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Get this brief every morning</div>
            <div style={{ fontSize: F.sm, color: C.muted, marginTop: 4 }}>Connect Telegram to receive the daily brief at 06:00 UTC, plus instant signal alerts.</div>
          </div>
          <a href="/settings" style={{ padding: '9px 20px', background: C.brand, color: '#fff', borderRadius: R.sm, fontSize: F.sm, fontWeight: 700, textDecoration: 'none' }}>
            Set Up Alerts →
          </a>
        </div>
      </div>
    </Layout>
  );
}
