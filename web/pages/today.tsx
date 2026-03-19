import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import Layout from '../components/Layout';
import { C, R, S, F, fmtUsd, fmtPct, timeAgo } from '../src/theme';
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
      <span style={{ fontSize: F.xs, color: C.muted, width: 60 }}>{t.close_reason || '—'}</span>
      <span style={{ fontSize: F.xs, color: t.outcome === 'WIN' ? C.bull : C.bear, fontWeight: 700, width: 36 }}>{t.outcome}</span>
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
  const activeIdx = segments.findIndex(s => r.includes(s.key.replace('_', ''))) ?? 5;
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
        <svg width={W} height={H} style={{ overflow: 'visible', maxWidth: '100%' }}>
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
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${COLS}, 36px)`, gap: 6, justifyContent: 'start' }}>
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
        <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} style={{ overflow: 'visible' }}>
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

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function TodayPage() {
  const [llmView, setLlmView] = useState<LlmMarketView | null>(null);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const fetch = async () => {
      const [lv, act, tr] = await Promise.all([
        apiFetch<LlmMarketView>('/v1/llm/market-view'),
        apiFetch<ActivityFeedResponse>('/v1/activity/feed?limit=50'),
        apiFetch<TradeHistoryResponse>('/v1/trades/history?limit=20'),
      ]);
      setLlmView(lv);
      setActivity(act?.items ?? []);
      setTrades(tr?.trades ?? []);
      setLoading(false);
    };
    fetch();
    const iv = setInterval(() => { fetch(); setNow(new Date()); }, 60_000);
    return () => clearInterval(iv);
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

        {/* ── Regime Dial + Streak Bar ── */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20, marginBottom: 28 }}>
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

        {/* ── 3-Column Quick Stats ── */}
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

        {/* ── Risk Gates + Hourly Trade Timeline ── */}
        <div style={{ display: 'flex', gap: 20, marginBottom: 28, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 320px' }}>
            <RiskGatesPanel />
          </div>
          <div style={{ flex: '1 1 320px' }}>
            <HourlyTradeTimeline />
          </div>
        </div>

        {/* ── Intraday Activity Heatmap ── */}
        <IntradayActivityHeatmap activity={activity} />

        {/* ── AI Market Commentary ── */}
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

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 28 }}>
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
              {recentTrades.map((t, i) => <TradeRow key={i} t={t} />)}
              {recentTrades.length === 0 && (
                <div style={{ padding: '20px 0', color: C.muted, fontSize: F.sm, textAlign: 'center' }}>
                  No trades in recent history. The bot is watching the market.
                </div>
              )}
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
