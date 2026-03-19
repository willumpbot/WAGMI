import React, { useEffect, useState, useId } from 'react';
import { useRouter } from 'next/router';
import { C, R, S, F, G, fmtUsd, fmtPct, timeAgo } from '../../src/theme';
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

import { resolveApiBase } from '../../src/api';

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
  const uid = useId().replace(/:/g, '');
  const gradLeftId = `zoneGradLeft-${uid}`;
  const gradRightId = `zoneGradRight-${uid}`;
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
          <linearGradient id={gradLeftId} x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="#16a34a" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#22c55e" stopOpacity="0.35" />
          </linearGradient>
          <linearGradient id={gradRightId} x1="0%" y1="0%" x2="100%" y2="0%">
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
            fill={`url(#${gradLeftId})`}
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
            fill={`url(#${gradRightId})`}
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
      background: C.surface,
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

// ─── SignalScoreGauge ─────────────────────────────────────────────────────────

function SignalScoreGauge({ score }: { score: number }) {
  const VW = 200;
  const VH = 120;
  const CX = 100;
  const CY = 90; // Center slightly lower so arc fits in top portion
  const RADIUS = 70;
  const STROKE = 14;

  // Convert a 0-100 score to an angle on the semicircle (180° left → 0° right)
  // score=0 → angle=180°, score=100 → angle=0°
  const scoreToAngle = (s: number) => 180 - (s / 100) * 180;

  // SVG arc path helper: draws an arc segment on the gauge circle
  const arcPath = (startDeg: number, endDeg: number): string => {
    const toRad = (d: number) => (d * Math.PI) / 180;
    const x1 = CX + RADIUS * Math.cos(toRad(startDeg));
    const y1 = CY - RADIUS * Math.sin(toRad(startDeg));
    const x2 = CX + RADIUS * Math.cos(toRad(endDeg));
    const y2 = CY - RADIUS * Math.sin(toRad(endDeg));
    const largeArc = Math.abs(endDeg - startDeg) > 180 ? 1 : 0;
    // sweep=0 because we go from high angle to low angle (left to right = 180→0)
    return `M ${x1} ${y1} A ${RADIUS} ${RADIUS} 0 ${largeArc} 0 ${x2} ${y2}`;
  };

  // Zones (score range → start/end angles on the semicircle)
  // score 0→30 maps to angles 180→126; 30→60: 126→72; 60→80: 72→36; 80→100: 36→0
  const zones = [
    { start: 0, end: 30, color: '#ef4444', startAngle: 180, endAngle: 126 },
    { start: 30, end: 60, color: '#eab308', startAngle: 126, endAngle: 72 },
    { start: 60, end: 80, color: '#22c55e', startAngle: 72, endAngle: 36 },
    { start: 80, end: 100, color: '#4ade80', startAngle: 36, endAngle: 0 },
  ];

  // Needle angle (in SVG coordinate space: pointing from center)
  // Guard against NaN/Infinity before clamping
  const safeScore = Number.isFinite(score) ? score : 0;
  const needleAngleDeg = scoreToAngle(Math.max(0, Math.min(100, safeScore)));
  const needleRad = (needleAngleDeg * Math.PI) / 180;
  const needleLen = RADIUS - STROKE / 2 - 4;
  const needleX = CX + needleLen * Math.cos(needleRad);
  const needleY = CY - needleLen * Math.sin(needleRad);

  const scoreColor =
    safeScore >= 80 ? '#4ade80' :
    safeScore >= 60 ? '#22c55e' :
    safeScore >= 30 ? '#eab308' :
    '#ef4444';

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '20px 18px 14px',
    }}>
      <svg
        viewBox={`0 0 ${VW} ${VH}`}
        width={VW}
        height={VH}
        style={{ display: 'block', overflow: 'visible' }}
        aria-label={`Signal score gauge: ${safeScore}`}
      >
        {/* Background arc track */}
        <path
          d={arcPath(180, 0)}
          fill="none"
          stroke="#1e293b"
          strokeWidth={STROKE}
          strokeLinecap="round"
        />

        {/* Zone arcs */}
        {zones.map(z => (
          <path
            key={z.start}
            d={arcPath(z.startAngle, z.endAngle)}
            fill="none"
            stroke={z.color}
            strokeWidth={STROKE}
            strokeLinecap="butt"
            opacity={0.85}
          />
        ))}

        {/* Needle */}
        <line
          x1={CX}
          y1={CY}
          x2={needleX}
          y2={needleY}
          stroke={scoreColor}
          strokeWidth="3"
          strokeLinecap="round"
        />

        {/* Pivot circle */}
        <circle cx={CX} cy={CY} r="7" fill="#1e293b" stroke={scoreColor} strokeWidth="2.5" />

        {/* Score number */}
        <text
          x={CX}
          y={CY + 24}
          textAnchor="middle"
          fontSize="26"
          fontWeight="800"
          fill={scoreColor}
          fontFamily="Inter, sans-serif"
        >
          {safeScore}
        </text>

        {/* Label */}
        <text
          x={CX}
          y={CY + 40}
          textAnchor="middle"
          fontSize="10"
          fill={C.muted}
          fontFamily="Inter, sans-serif"
          letterSpacing="0.05em"
        >
          SIGNAL SCORE
        </text>

        {/* Min/Max labels */}
        <text x={CX - RADIUS - 2} y={CY + 6} textAnchor="middle" fontSize="8" fill={C.muted} fontFamily="monospace">0</text>
        <text x={CX + RADIUS + 2} y={CY + 6} textAnchor="middle" fontSize="8" fill={C.muted} fontFamily="monospace">100</text>
      </svg>
    </div>
  );
}

// ─── StrategySignalHistory ────────────────────────────────────────────────────

type SignalHistoryEntry = {
  side: 'BUY' | 'SELL' | 'NEUTRAL';
  score: number;
  market: string;
  ts: string;
};

function StrategySignalHistory({ logs, card }: { logs: LogEntry[]; card: StrategyCard | null }) {
  // Try to derive signal history from logs
  const fromLogs: SignalHistoryEntry[] = logs
    .filter(l => {
      const ev = l.event.toLowerCase();
      return ev.includes('signal') || ev.includes('buy') || ev.includes('sell') || ev.includes('long') || ev.includes('short');
    })
    .slice(-10)
    .reverse()
    .map(l => {
      const ev = l.event.toLowerCase();
      const side: SignalHistoryEntry['side'] =
        ev.includes('buy') || ev.includes('long') ? 'BUY' :
        ev.includes('sell') || ev.includes('short') ? 'SELL' :
        'NEUTRAL';
      const score = l.details?.score ?? l.details?.confidence ?? l.details?.signal_score ?? 0;
      const market = l.details?.market ?? l.details?.symbol ?? card?.latestSignal?.market ?? '—';
      return { side, score: Number(score), market: String(market), ts: l.ts };
    });

  // Deterministic placeholders if no real log-derived history
  const placeholders: SignalHistoryEntry[] = (() => {
    const base = Date.now();
    const seed = (card?.id?.length ?? 5) * 7;
    const entries: SignalHistoryEntry[] = [
      { side: 'BUY', score: 72 + (seed % 15), market: card?.latestSignal?.market ?? 'BTC-USD', ts: new Date(base - 3600000).toISOString() },
      { side: 'NEUTRAL', score: 48 + (seed % 10), market: card?.latestSignal?.market ?? 'BTC-USD', ts: new Date(base - 7200000).toISOString() },
      { side: 'SELL', score: 61 + (seed % 12), market: card?.latestSignal?.market ?? 'BTC-USD', ts: new Date(base - 10800000).toISOString() },
      { side: 'BUY', score: 55 + (seed % 20), market: card?.latestSignal?.market ?? 'BTC-USD', ts: new Date(base - 18000000).toISOString() },
      { side: 'NEUTRAL', score: 42 + (seed % 8), market: card?.latestSignal?.market ?? 'BTC-USD', ts: new Date(base - 28800000).toISOString() },
    ];
    return entries;
  })();

  const entries = fromLogs.length > 0 ? fromLogs : placeholders;

  const dotColor = (side: SignalHistoryEntry['side']) => {
    if (side === 'BUY') return '#22c55e';
    if (side === 'SELL') return '#ef4444';
    return '#64748b';
  };

  const scoreColor = (score: number) =>
    score >= 70 ? '#22c55e' : score >= 45 ? '#eab308' : '#ef4444';

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '16px 18px',
    }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 14 }}>
        Signal History
        {fromLogs.length === 0 && (
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 400, marginLeft: 8 }}>(example)</span>
        )}
      </div>

      {/* Vertical timeline */}
      <div style={{ position: 'relative', paddingLeft: 20 }}>
        {/* Vertical line */}
        <div style={{
          position: 'absolute',
          left: 5,
          top: 6,
          bottom: 6,
          width: 2,
          background: C.border,
          borderRadius: 1,
        }} />

        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {entries.map((entry, i) => (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 12, position: 'relative' }}>
              {/* Timeline dot */}
              <div style={{
                position: 'absolute',
                left: -15,
                width: 10,
                height: 10,
                borderRadius: '50%',
                background: dotColor(entry.side),
                border: `1.5px solid ${dotColor(entry.side)}`,
                boxShadow: `0 0 4px ${dotColor(entry.side)}88`,
                flexShrink: 0,
              }} />

              {/* Content */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', flex: 1 }}>
                {/* Side badge */}
                <span style={{
                  padding: '2px 8px',
                  borderRadius: R.sm,
                  fontSize: F.xs,
                  fontWeight: 700,
                  background: entry.side === 'BUY' ? '#166534' : entry.side === 'SELL' ? '#7f1d1d' : C.faint,
                  color: entry.side === 'BUY' ? '#bbf7d0' : entry.side === 'SELL' ? '#fca5a5' : C.muted,
                  letterSpacing: '0.04em',
                }}>
                  {entry.side}
                </span>

                {/* Score */}
                <span style={{
                  fontSize: F.xs,
                  fontWeight: 700,
                  color: scoreColor(entry.score),
                  fontFamily: 'JetBrains Mono, monospace',
                }}>
                  {entry.score > 0 ? entry.score.toFixed(0) : '—'}
                </span>

                {/* Market */}
                <span style={{ fontSize: F.xs, color: C.textSub, fontFamily: 'monospace' }}>
                  {entry.market}
                </span>

                {/* Timestamp */}
                <span style={{ fontSize: F.xs, color: C.muted, marginLeft: 'auto' }}>
                  {timeAgo(entry.ts)}
                </span>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SignalsTab({ card, logs }: { card: StrategyCard | null; logs: LogEntry[] }) {
  if (!card?.latestSignal) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        {/* Gauge still visible even without a live signal (shows default 65) */}
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <SignalScoreGauge score={65} />
        </div>
        <StrategySignalHistory logs={logs} card={card} />
        <div style={{ textAlign: 'center', padding: '48px 0', color: C.muted }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>📊</div>
          <div style={{ fontSize: F.lg, fontWeight: 600, color: C.text, marginBottom: 4 }}>Awaiting first signal</div>
          <div style={{ fontSize: F.sm }}>Signals appear once the strategy has run at least one evaluation cycle.</div>
        </div>
      </div>
    );
  }

  const sig = card.latestSignal;
  const score = Number.isFinite(sig.score) ? sig.score : 0;
  const scoreColor = score >= 70 ? C.bull : score >= 45 ? '#eab308' : C.bear;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Signal Score Gauge — above score hero */}
      <div style={{ display: 'flex', justifyContent: 'center' }}>
        <SignalScoreGauge score={score} />
      </div>

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

      {/* Signal History — below zone ruler */}
      <StrategySignalHistory logs={logs} card={card} />
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

// ─── TradeStreakVisual ────────────────────────────────────────────────────────

function TradeStreakVisual({ trades }: { trades: TradeRecord[] }) {
  // Seeded fallback: [W,W,L,W,W,W,W,L,W,W,W,L,W,W,W,W,L,W,W,W]
  const FALLBACK: boolean[] = [
    true, true, false, true, true, true, true, false,
    true, true, true, false, true, true, true, true,
    false, true, true, true,
  ];

  // Derive win/loss booleans from real trades (newest last → oldest first after slice)
  const isWin = (t: TradeRecord): boolean =>
    t.outcome === 'WIN' || (t.pnl != null && t.pnl > 0);

  const useFallback = trades.length === 0;
  const last20: boolean[] = useFallback
    ? FALLBACK
    : trades.slice(-20).map(isWin);

  // Pad to 20 if fewer than 20 real trades (pad from front with nulls represented as false)
  const grid: (boolean | null)[] = useFallback
    ? last20
    : Array.from({ length: 20 }, (_, i) => {
        const offset = 20 - last20.length;
        return i < offset ? null : last20[i - offset];
      });

  // Current streak (from the most-recent trade going backwards)
  let streakCount = 0;
  let streakType: 'WIN' | 'LOSS' | null = null;
  for (let i = last20.length - 1; i >= 0; i--) {
    if (streakType === null) {
      streakType = last20[i] ? 'WIN' : 'LOSS';
      streakCount = 1;
    } else if (last20[i] === (streakType === 'WIN')) {
      streakCount++;
    } else {
      break;
    }
  }

  // Win rate of the last 20 displayed trades
  const realCells = grid.filter(v => v !== null) as boolean[];
  const winCount = realCells.filter(Boolean).length;
  const lossCount = realCells.length - winCount;
  const winRate = realCells.length > 0 ? (winCount / realCells.length) * 100 : 0;

  const SQUARE = 22;
  const GAP = 3;
  const COLS = 4; // 4 columns × 5 rows = 20 squares
  // Total grid width: 4 squares + 3 gaps
  const gridWidth = COLS * SQUARE + (COLS - 1) * GAP;

  const winColor = '#22c55e';
  const lossColor = '#dc2626';
  const emptyColor = C.faint;

  const winRateColor =
    winRate >= 60 ? winColor :
    winRate >= 45 ? '#eab308' :
    lossColor;

  // Momentum bar proportions (use realCells.length, not hardcoded 20)
  const lossPct = realCells.length > 0 ? (lossCount / realCells.length) * 100 : 0;
  const winPct = realCells.length > 0 ? (winCount / realCells.length) * 100 : 0;

  return (
    <div style={{
      background: C.surface,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '18px 20px',
      display: 'flex',
      flexDirection: 'column',
      gap: 14,
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>
          Trade Streak
          {useFallback && (
            <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 400, marginLeft: 8 }}>(example)</span>
          )}
        </div>
        {/* Win-rate pill */}
        <span style={{
          padding: '3px 10px',
          borderRadius: R.pill,
          fontSize: F.xs,
          fontWeight: 700,
          background: winRateColor === winColor ? '#166534' : winRateColor === '#eab308' ? '#713f12' : '#7f1d1d',
          color: winRateColor === winColor ? '#bbf7d0' : winRateColor === '#eab308' ? '#fef08a' : '#fca5a5',
          letterSpacing: '0.04em',
        }}>
          {winRate.toFixed(0)}% WIN RATE ({realCells.length} trades)
        </span>
      </div>

      {/* Body: streak badge + grid side by side */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 20, flexWrap: 'wrap' }}>
        {/* Current streak badge */}
        {streakType && (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            minWidth: 100,
            padding: '12px 16px',
            background: streakType === 'WIN' ? 'rgba(22,163,74,0.12)' : 'rgba(220,38,38,0.12)',
            border: `1.5px solid ${streakType === 'WIN' ? winColor : lossColor}`,
            borderRadius: R.md,
            gap: 4,
          }}>
            <div style={{ fontSize: 22, lineHeight: 1 }}>
              {streakType === 'WIN' ? '🔥' : '⚠'}
            </div>
            <div style={{
              fontSize: F['2xl'],
              fontWeight: 800,
              color: streakType === 'WIN' ? winColor : lossColor,
              lineHeight: 1.1,
              fontFamily: 'JetBrains Mono, monospace',
            }}>
              {streakCount}
            </div>
            <div style={{
              fontSize: F.xs,
              fontWeight: 700,
              color: streakType === 'WIN' ? winColor : lossColor,
              letterSpacing: '0.06em',
            }}>
              {streakType === 'WIN' ? 'WIN' : 'LOSS'} STREAK
            </div>
          </div>
        )}

        {/* 4×5 grid of squares */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: `repeat(${COLS}, ${SQUARE}px)`,
          gap: GAP,
        }}>
          {grid.map((isWinCell, idx) => (
            <div
              key={idx}
              title={isWinCell === null ? 'No trade' : isWinCell ? 'Win' : 'Loss'}
              style={{
                width: SQUARE,
                height: SQUARE,
                borderRadius: 4,
                background: isWinCell === null ? emptyColor : isWinCell ? winColor : lossColor,
                opacity: isWinCell === null ? 0.3 : 1,
                cursor: 'pointer',
                transition: 'opacity 0.15s',
              }}
              onMouseEnter={e => { (e.currentTarget as HTMLDivElement).style.opacity = '0.7'; }}
              onMouseLeave={e => { (e.currentTarget as HTMLDivElement).style.opacity = isWinCell === null ? '0.3' : '1'; }}
            />
          ))}
        </div>

        {/* Legend */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignSelf: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: F.xs, color: C.muted }}>
            <div style={{ width: 12, height: 12, borderRadius: 2, background: winColor, flexShrink: 0 }} />
            Win ({winCount})
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: F.xs, color: C.muted }}>
            <div style={{ width: 12, height: 12, borderRadius: 2, background: lossColor, flexShrink: 0 }} />
            Loss ({lossCount})
          </div>
        </div>
      </div>

      {/* Momentum bar */}
      <div>
        <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 5, fontWeight: 600, letterSpacing: '0.04em' }}>
          MOMENTUM — last {realCells.length} trades
        </div>
        <div style={{
          position: 'relative',
          height: 12,
          borderRadius: R.pill,
          background: C.faint,
          overflow: 'hidden',
          width: '100%',
        }}>
          {/* Left half: red (losses), right half: green (wins) — each fills from center outward */}
          {/* Full bar: red on left, green on right, split at center */}
          <div style={{
            position: 'absolute',
            left: 0,
            top: 0,
            bottom: 0,
            width: `${lossPct / 2}%`,
            background: lossColor,
            borderRadius: `${R.pill}px 0 0 ${R.pill}px`,
            opacity: 0.85,
            transition: 'width 0.5s',
          }} />
          <div style={{
            position: 'absolute',
            right: 0,
            top: 0,
            bottom: 0,
            width: `${winPct / 2}%`,
            background: winColor,
            borderRadius: `0 ${R.pill}px ${R.pill}px 0`,
            opacity: 0.85,
            transition: 'width 0.5s',
          }} />
          {/* Center marker */}
          <div style={{
            position: 'absolute',
            left: '50%',
            top: 0,
            bottom: 0,
            width: 2,
            background: C.border,
            transform: 'translateX(-50%)',
          }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
          <span style={{ fontSize: F.xs, color: lossColor, fontWeight: 600 }}>{lossCount}L</span>
          <span style={{ fontSize: F.xs, color: C.muted }}>center</span>
          <span style={{ fontSize: F.xs, color: winColor, fontWeight: 600 }}>{winCount}W</span>
        </div>
      </div>
    </div>
  );
}

// ─── WinRateByRegimeHeatmap ───────────────────────────────────────────────────

function WinRateByRegimeHeatmap({ trades }: { trades: TradeRecord[] }) {
  const REGIMES = [
    { key: 'trend',           label: 'Trend',    color: '#22c55e' },
    { key: 'range',           label: 'Range',    color: '#6366f1' },
    { key: 'high_volatility', label: 'High Vol', color: '#eab308' },
    { key: 'panic',           label: 'Panic',    color: '#dc2626' },
    { key: 'low_liquidity',   label: 'Low Liq',  color: '#64748b' },
  ] as const;

  const SYMBOLS = ['BTC', 'SOL', 'HYPE'] as const;

  // Seeded fallback matrix (rows = regimes, cols = symbols)
  const FALLBACK: Record<string, Record<string, number>> = {
    trend:           { BTC: 82, SOL: 78, HYPE: 71 },
    range:           { BTC: 55, SOL: 61, HYPE: 48 },
    high_volatility: { BTC: 43, SOL: 52, HYPE: 38 },
    panic:           { BTC: 30, SOL: 25, HYPE: 33 },
    low_liquidity:   { BTC: 60, SOL: 55, HYPE: 58 },
  };

  const useFallback = trades.length === 0;

  // Build matrix from real trades
  type Cell = { wins: number; total: number };
  const matrix: Record<string, Record<string, Cell>> = {};
  for (const r of REGIMES) {
    matrix[r.key] = {};
    for (const sym of SYMBOLS) {
      matrix[r.key][sym] = { wins: 0, total: 0 };
    }
  }

  if (!useFallback) {
    for (const t of trades) {
      const regime = ((t as any).regime || t.llm_regime || '').toLowerCase();
      const sym = (t.symbol || '').toUpperCase().replace(/-.*$/, ''); // strip -USD etc.
      if (!REGIMES.find(r => r.key === regime)) continue;
      if (!SYMBOLS.includes(sym as typeof SYMBOLS[number])) continue;
      const cell = matrix[regime][sym];
      cell.total++;
      if (t.outcome === 'WIN' || (t.pnl != null && t.pnl > 0)) cell.wins++;
    }
  }

  const cellBg = (pct: number): string => {
    if (pct < 40)  return `rgba(220,38,38,${0.15 + (40 - pct) / 40 * 0.35})`;
    if (pct <= 60) return `rgba(217,119,6,${0.15 + Math.abs(pct - 50) / 10 * 0.2})`;
    return `rgba(22,163,74,${0.15 + (pct - 60) / 40 * 0.45})`;
  };

  const cellFg = (pct: number): string =>
    pct < 40 ? '#fca5a5' : pct <= 60 ? '#fde68a' : '#86efac';

  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '18px 20px' }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 14 }}>
        Win Rate by Regime × Symbol
        {useFallback && (
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 400, marginLeft: 8 }}>(example)</span>
        )}
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', minWidth: 320 }}>
          <thead>
            <tr>
              {/* Empty corner cell */}
              <th style={{ padding: '6px 12px', width: 90 }} />
              {SYMBOLS.map(sym => (
                <th key={sym} style={{
                  padding: '6px 14px',
                  fontSize: F.xs,
                  fontWeight: 700,
                  color: C.textSub,
                  textAlign: 'center',
                  letterSpacing: '0.06em',
                }}>
                  {sym}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {REGIMES.map(regime => (
              <tr key={regime.key}>
                {/* Row header */}
                <td style={{ padding: '6px 12px', whiteSpace: 'nowrap' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                    <div style={{
                      width: 8,
                      height: 8,
                      borderRadius: '50%',
                      background: regime.color,
                      flexShrink: 0,
                      boxShadow: `0 0 5px ${regime.color}88`,
                    }} />
                    <span style={{ fontSize: F.xs, fontWeight: 600, color: C.textSub }}>{regime.label}</span>
                  </div>
                </td>

                {SYMBOLS.map(sym => {
                  let pct: number | null = null;
                  if (useFallback) {
                    pct = FALLBACK[regime.key][sym];
                  } else {
                    const cell = matrix[regime.key][sym];
                    pct = cell.total > 0 ? (cell.wins / cell.total) * 100 : null;
                  }

                  const bg = pct !== null ? cellBg(pct) : C.faint;
                  const fg = pct !== null ? cellFg(pct) : C.muted;

                  return (
                    <td key={sym} style={{ padding: '5px 8px', textAlign: 'center' }}>
                      <div style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        minWidth: 52,
                        height: 34,
                        borderRadius: R.md,
                        background: bg,
                        border: `1px solid ${pct !== null ? fg + '44' : C.border}`,
                        fontSize: F.sm,
                        fontWeight: 700,
                        color: fg,
                        fontFamily: 'JetBrains Mono, monospace',
                      }}>
                        {pct !== null ? `${Math.round(pct)}%` : '—'}
                      </div>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, marginTop: 14, flexWrap: 'wrap' }}>
        {[
          { label: '< 40%', color: '#fca5a5', bg: 'rgba(220,38,38,0.3)' },
          { label: '40–60%', color: '#fde68a', bg: 'rgba(217,119,6,0.3)' },
          { label: '> 60%', color: '#86efac', bg: 'rgba(22,163,74,0.35)' },
        ].map(item => (
          <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ width: 16, height: 12, borderRadius: 3, background: item.bg, border: `1px solid ${item.color}44` }} />
            <span style={{ fontSize: F.xs, color: C.muted }}>{item.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── SignalEntryDistribution ──────────────────────────────────────────────────

function SignalEntryDistribution({ trades }: { trades: TradeRecord[] }) {
  const SVG_W = 460;
  const SVG_H = 140;
  const PAD_L = 36;
  const PAD_R = 16;
  const PAD_T = 16;
  const PAD_B = 36;
  const CHART_W = SVG_W - PAD_L - PAD_R;
  const CHART_H = SVG_H - PAD_T - PAD_B;

  const BUCKETS = 10; // 0-9, 10-19, ..., 90-100

  const CONFIDENCE_THRESHOLD = 65;

  // Seeded fallback: normal distribution centered ~77
  const FALLBACK_COUNTS = [0, 1, 2, 5, 9, 14, 20, 24, 16, 9];
  const FALLBACK_WINS   = [0, 0, 1, 2, 4,  7, 13, 19, 14, 8];

  const useFallback = trades.length === 0;

  const counts: number[] = Array(BUCKETS).fill(0);
  const winCounts: number[] = Array(BUCKETS).fill(0);

  if (!useFallback) {
    for (const t of trades) {
      const score = t.confidence != null ? t.confidence : null;
      if (score == null) continue;
      // confidence is 0–100 (already a percentage in TradeRecord, but could be 0–1)
      const normalized = score > 1 ? score : score * 100;
      const bucket = Math.min(BUCKETS - 1, Math.floor(normalized / 10));
      counts[bucket]++;
      if (t.outcome === 'WIN' || (t.pnl != null && t.pnl > 0)) winCounts[bucket]++;
    }
  }

  const displayCounts = useFallback ? FALLBACK_COUNTS : counts;
  const displayWins   = useFallback ? FALLBACK_WINS   : winCounts;

  const maxCount = Math.max(...displayCounts, 1);

  const barColor = (bucketIdx: number): string => {
    const midScore = bucketIdx * 10 + 5;
    if (midScore < 65)  return `rgba(220,38,38,0.65)`;
    if (midScore < 75)  return `rgba(217,119,6,0.75)`;
    if (midScore < 85)  return `rgba(99,102,241,0.8)`;
    return `rgba(22,163,74,0.85)`;
  };

  // Bar geometry
  const barW = CHART_W / BUCKETS;
  const barGap = 3;
  const barInnerW = barW - barGap;

  // x for bar center (bucket index)
  const bx = (i: number) => PAD_L + i * barW + barW / 2;

  // y for a count value on the primary Y axis (count → SVG y)
  const cy = (count: number) => PAD_T + CHART_H - (count / maxCount) * CHART_H;

  // Win rate line points
  const linePoints = displayCounts.map((cnt, i) => {
    const wr = cnt > 0 ? (displayWins[i] / cnt) * 100 : null;
    return wr;
  });

  // x tick position for bucket i
  const tx = (i: number) => PAD_L + i * barW;

  // Confidence threshold x coordinate
  const threshX = PAD_L + (CONFIDENCE_THRESHOLD / 100) * CHART_W;

  // Y axis labels (count)
  const yLabels = [0, Math.round(maxCount / 2), maxCount];

  // Build SVG polyline points for win-rate overlay (only for buckets with data)
  const wrLineSegments: { x1: number; y1: number; x2: number; y2: number }[] = [];
  let prevWr: { x: number; y: number } | null = null;
  for (let i = 0; i < BUCKETS; i++) {
    const wr = linePoints[i];
    if (wr === null) { prevWr = null; continue; }
    // win rate y: map 0-100 onto chart height (top = 100%, bottom = 0%)
    const wrY = PAD_T + CHART_H - (wr / 100) * CHART_H;
    const cx_ = bx(i);
    if (prevWr !== null) {
      wrLineSegments.push({ x1: prevWr.x, y1: prevWr.y, x2: cx_, y2: wrY });
    }
    prevWr = { x: cx_, y: wrY };
  }

  return (
    <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '18px 20px' }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 14 }}>
        Entry Signal Score Distribution
        {useFallback && (
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 400, marginLeft: 8 }}>(example)</span>
        )}
      </div>

      <svg
        viewBox={`0 0 ${SVG_W} ${SVG_H}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
        aria-label="Entry signal score distribution histogram"
      >
        {/* Y-axis gridlines + labels */}
        {yLabels.map((val, li) => {
          const yPos = PAD_T + CHART_H - (val / maxCount) * CHART_H;
          return (
            <g key={li}>
              <line
                x1={PAD_L} y1={yPos} x2={PAD_L + CHART_W} y2={yPos}
                stroke={C.border} strokeWidth="1" strokeDasharray="3 4"
              />
              <text x={PAD_L - 4} y={yPos + 4} textAnchor="end" fontSize="8" fill={C.muted} fontFamily="monospace">
                {val}
              </text>
            </g>
          );
        })}

        {/* Histogram bars */}
        {displayCounts.map((count, i) => {
          const barH = (count / maxCount) * CHART_H;
          const bx_ = PAD_L + i * barW + barGap / 2;
          const by_ = PAD_T + CHART_H - barH;
          return (
            <rect
              key={i}
              x={bx_}
              y={by_}
              width={barInnerW}
              height={barH}
              rx={3}
              fill={barColor(i)}
            />
          );
        })}

        {/* Win-rate overlay line */}
        {wrLineSegments.map((seg, i) => (
          <line
            key={i}
            x1={seg.x1} y1={seg.y1}
            x2={seg.x2} y2={seg.y2}
            stroke="#f0abfc"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        ))}

        {/* Win-rate dots */}
        {displayCounts.map((cnt, i) => {
          const wr = cnt > 0 ? (displayWins[i] / cnt) * 100 : null;
          if (wr === null) return null;
          const wrY = PAD_T + CHART_H - (wr / 100) * CHART_H;
          return (
            <circle key={i} cx={bx(i)} cy={wrY} r={2.5} fill="#f0abfc" stroke={C.surface} strokeWidth="1" />
          );
        })}

        {/* Confidence threshold vertical dashed line */}
        <line
          x1={threshX} y1={PAD_T - 4}
          x2={threshX} y2={PAD_T + CHART_H}
          stroke={C.warn}
          strokeWidth="1.5"
          strokeDasharray="4 3"
        />
        <text x={threshX + 3} y={PAD_T + 4} fontSize="8" fill={C.warn} fontFamily="monospace">65%</text>

        {/* X-axis tick labels */}
        {Array.from({ length: BUCKETS }, (_, i) => (
          <text
            key={i}
            x={tx(i) + barW / 2}
            y={PAD_T + CHART_H + 14}
            textAnchor="middle"
            fontSize="8"
            fill={C.muted}
            fontFamily="monospace"
          >
            {i * 10}
          </text>
        ))}

        {/* X-axis label */}
        <text
          x={PAD_L + CHART_W / 2}
          y={SVG_H - 2}
          textAnchor="middle"
          fontSize="8"
          fill={C.muted}
          fontFamily="Inter, sans-serif"
        >
          Signal Score (0–100)
        </text>

        {/* Y-axis label */}
        <text
          x={8}
          y={PAD_T + CHART_H / 2}
          textAnchor="middle"
          fontSize="8"
          fill={C.muted}
          fontFamily="Inter, sans-serif"
          transform={`rotate(-90, 8, ${PAD_T + CHART_H / 2})`}
        >
          Trades
        </text>
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        {[
          { label: '< 65', color: 'rgba(220,38,38,0.65)' },
          { label: '65–75', color: 'rgba(217,119,6,0.75)' },
          { label: '75–85', color: 'rgba(99,102,241,0.8)' },
          { label: '85+', color: 'rgba(22,163,74,0.85)' },
        ].map(item => (
          <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{ width: 12, height: 10, borderRadius: 2, background: item.color }} />
            <span style={{ fontSize: F.xs, color: C.muted }}>{item.label}</span>
          </div>
        ))}
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <svg width="20" height="8"><line x1="0" y1="4" x2="20" y2="4" stroke="#f0abfc" strokeWidth="1.5" /><circle cx="10" cy="4" r="2.5" fill="#f0abfc" /></svg>
          <span style={{ fontSize: F.xs, color: C.muted }}>Win rate</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <svg width="16" height="8"><line x1="0" y1="4" x2="16" y2="4" stroke={C.warn} strokeWidth="1.5" strokeDasharray="3 2" /></svg>
          <span style={{ fontSize: F.xs, color: C.muted }}>65% threshold</span>
        </div>
      </div>
    </div>
  );
}

// ─── PerformanceTab ───────────────────────────────────────────────────────────

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

  const wins = trades.filter(t => t.outcome === 'WIN' || (t.pnl != null && t.pnl > 0));
  const losses = trades.filter(t => t.outcome !== 'WIN' && (t.pnl != null && t.pnl <= 0));
  const winRate = trades.length > 0 ? (wins.length / trades.length) * 100 : 0;
  const totalPnl = trades.reduce((a, t) => a + (t.pnl ?? 0), 0);
  const avgWin = wins.length > 0 ? wins.reduce((a, t) => a + (t.pnl ?? 0), 0) / wins.length : 0;
  const avgLoss = losses.length > 0 ? Math.abs(losses.reduce((a, t) => a + (t.pnl ?? 0), 0) / losses.length) : 0;
  const profitFactor = avgLoss > 0 ? wins.reduce((a, t) => a + (t.pnl ?? 0), 0) / Math.abs(losses.reduce((a, t) => a + (t.pnl ?? 0), 0)) : null;

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
      {/* Streak tracker */}
      <TradeStreakVisual trades={trades} />

      {/* Win rate heatmap by regime × symbol */}
      <WinRateByRegimeHeatmap trades={trades} />

      {/* Signal score distribution histogram */}
      <SignalEntryDistribution trades={trades} />

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
  const { id: rawId } = router.query;
  // id can be string | string[] | undefined — normalise to string | undefined
  const id: string | undefined = !router.isReady
    ? undefined
    : Array.isArray(rawId) ? rawId[0] : rawId;

  const [activeTab, setActiveTab] = useState<Tab>('signals');
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logsLoading, setLogsLoading] = useState(true);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [card, setCard] = useState<StrategyCard | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [trades, setTrades] = useState<TradeRecord[]>([]);
  const [tradesLoading, setTradesLoading] = useState(false);
  const apiBase = resolveApiBase();

  // Reset per-route state whenever the strategy id changes
  useEffect(() => {
    setActiveTab('signals');
    setCard(null);
    setNotFound(false);
    setLogs([]);
    setLogsLoading(true);
    setLogsError(null);
    setTrades([]);
  }, [id]);

  const online = (() => {
    const ts = card?.lastHeartbeat || card?.last_seen;
    if (!ts) return false;
    return (Date.now() - Date.parse(ts)) / 1000 <= 120;
  })();

  const pnl = (card as any)?.pnl_realized ?? (card as any)?.pnl ?? null;

  useEffect(() => {
    if (!id) return;

    // AbortController prevents stale responses from overwriting newer state
    const controller = new AbortController();
    const signal = controller.signal;

    const fetchAll = async () => {
      // Fetch card
      try {
        const r = await fetch(`${apiBase}/v1/strategies/${encodeURIComponent(id)}`, { cache: 'no-store', signal });
        if (r.ok) { setCard(await r.json()); setNotFound(false); }
        else if (r.status === 404) { setCard(null); setNotFound(true); }
      } catch (_) {}

      // Fetch logs
      try {
        setLogsError(null);
        const r = await fetch(`${apiBase}/v1/strategies/${encodeURIComponent(id)}/logs`, { cache: 'no-store', signal });
        if (r.ok) {
          const data = await r.json();
          setLogs(Array.isArray(data) ? data : data?.value || []);
        } else {
          setLogsError(`HTTP ${r.status}`);
        }
      } catch (e: any) {
        if (e?.name !== 'AbortError') setLogsError(e?.message || 'Failed to load logs');
      } finally {
        if (!signal.aborted) setLogsLoading(false);
      }
    };

    fetchAll();
    const iv = setInterval(fetchAll, 30000);
    return () => { controller.abort(); clearInterval(iv); };
  }, [id, apiBase]);

  // Load trades when that tab is selected; reset when id changes (handled above)
  useEffect(() => {
    if (!id) return;
    if (activeTab !== 'trades' && activeTab !== 'performance') return;
    if (trades.length > 0) return;
    const ctrl = new AbortController();
    setTradesLoading(true);
    fetch(`${apiBase}/v1/trades/history?limit=200`, { cache: 'no-store', signal: ctrl.signal })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (ctrl.signal.aborted) return;
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
      .finally(() => { if (!ctrl.signal.aborted) setTradesLoading(false); });
    return () => ctrl.abort();
  }, [activeTab, apiBase, card, id, trades.length]);

  const tabs: { key: Tab; label: string; count?: number }[] = [
    { key: 'signals', label: 'Signals' },
    { key: 'trades', label: 'Trades', count: trades.length || undefined },
    { key: 'performance', label: 'Performance' },
    { key: 'logs', label: 'Logs', count: logs.length || undefined },
  ];

  return (
    <div style={{ maxWidth: 1100, margin: '0 auto', fontFamily: "'Inter', system-ui, sans-serif" }}>
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

      {/* 404 not-found state */}
      {notFound && (
        <div style={{
          textAlign: 'center',
          padding: '60px 20px',
          background: C.surface,
          border: `1px solid ${C.border}`,
          borderRadius: R.lg,
        }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>🔍</div>
          <div style={{ fontSize: F.lg, fontWeight: 600, color: C.text, marginBottom: 6 }}>Strategy not found</div>
          <div style={{ fontSize: F.sm, color: C.muted }}>No strategy with ID &ldquo;{id}&rdquo; exists.</div>
        </div>
      )}

      {/* Page header + tabs — only shown when strategy exists */}
      {!notFound && (
        <>
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
                  {card?.name || (id ? `Strategy ${id}` : 'Loading…')}
                </h1>
                <div style={{ marginTop: 6, fontSize: F.sm, color: C.muted }}>
                  ID: {id ?? '—'} · Last evaluated: {card?.lastEvaluated ? timeAgo(card.lastEvaluated) : '—'}
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
                  {card.open_position.side ?? '—'}
                </span>
                <span style={{ color: C.text }}>{card.open_position.size ?? '—'} @ ${fmt(card.open_position.avg_entry, 2)}</span>
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
            {activeTab === 'signals' && <SignalsTab card={card} logs={logs} />}
            {activeTab === 'trades' && <TradesTab trades={trades} loading={tradesLoading} />}
            {activeTab === 'performance' && <PerformanceTab trades={trades} />}
            {activeTab === 'logs' && <LogsTab logs={logs} loading={logsLoading} error={logsError} />}
          </div>
        </>
      )}
    </div>
  );
}
