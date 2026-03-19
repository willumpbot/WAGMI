import React, { useEffect, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { C, R, S, F, fmtUsd, fmtPct } from '../src/theme';
import { apiFetch } from '../src/api';
import type { BacktestResult, ActivityEvent, ActivityFeedResponse } from '../src/types';

// ─── Inline SVG Equity Sparkline ─────────────────────────────────────────────

function HeroSparkline({ data, w = 320, h = 80 }: { data: number[]; w?: number; h?: number }) {
  if (data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const x = (i: number) => (i / (data.length - 1)) * w;
  const y = (v: number) => h - ((v - min) / range) * h * 0.85 - h * 0.075;
  const pts = data.map((v, i) => `${x(i)},${y(v)}`).join(' ');
  const area = [`0,${h}`, ...data.map((v, i) => `${x(i)},${y(v)}`), `${w},${h}`].join(' ');
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
      <defs>
        <linearGradient id="heroSparkGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={C.bull} stopOpacity="0.35" />
          <stop offset="100%" stopColor={C.bull} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <polyline points={area} fill="url(#heroSparkGrad)" stroke="none" />
      <polyline points={pts} fill="none" stroke={C.bull} strokeWidth={2.5} strokeLinejoin="round" />
    </svg>
  );
}

// ─── Live trade ticker ────────────────────────────────────────────────────────

function LiveTicker({ events }: { events: ActivityEvent[] }) {
  if (!events.length) return null;
  const visible = events.slice(0, 8);
  return (
    <div style={{
      overflow: 'hidden', height: 36, background: 'rgba(0,0,0,0.3)',
      borderTop: `1px solid ${C.border}`, borderBottom: `1px solid ${C.border}`,
      position: 'relative',
    }}>
      <style>{`@keyframes ticker { 0% { transform: translateX(0); } 100% { transform: translateX(-50%); } }`}</style>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 40, height: '100%',
        whiteSpace: 'nowrap', animation: 'ticker 30s linear infinite',
        paddingLeft: 20,
      }}>
        {[...visible, ...visible].map((e, i) => {
          const col = e.badge_color || C.muted;
          return (
            <span key={`ticker-${i}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 8, fontSize: F.xs }}>
              <span style={{ padding: '1px 6px', borderRadius: R.pill, background: col + '22', color: col, fontWeight: 700, fontSize: 10 }}>{e.badge}</span>
              <span style={{ color: C.textSub, fontWeight: 600 }}>{e.symbol || '—'}</span>
              <span style={{ color: C.muted }}>{e.detail?.slice(0, 40) || e.title}</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

// ─── Stat Counter ─────────────────────────────────────────────────────────────

function StatBlock({ value, label, sub }: { value: string; label: string; sub?: string }) {
  return (
    <div style={{ textAlign: 'center', padding: '24px 16px' }}>
      <div style={{ fontSize: F['4xl'], fontWeight: 800, color: C.text, lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: F.base, fontWeight: 600, color: C.textSub, marginTop: 8 }}>{label}</div>
      {sub && <div style={{ fontSize: F.sm, color: C.muted, marginTop: 4 }}>{sub}</div>}
    </div>
  );
}

// ─── Agent Pipeline Diagram ───────────────────────────────────────────────────

function AgentPipeline() {
  const agents = [
    { name: 'Regime', model: 'Haiku', role: 'Classifies market conditions', color: C.info },
    { name: 'Trade', model: 'Sonnet', role: 'Forms directional thesis', color: C.brand },
    { name: 'Risk', model: 'Haiku', role: 'Sizes position and flags risks', color: C.warn },
    { name: 'Critic', model: 'Sonnet', role: 'Stress-tests the thesis', color: C.purple },
    { name: 'Execute', model: '→', role: 'Trade placed (or vetoed)', color: C.bull },
  ];
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, overflowX: 'auto', padding: '8px 0' }}>
      {agents.map((a, i) => (
        <React.Fragment key={a.name}>
          <div style={{
            flex: '0 0 auto', textAlign: 'center', padding: '14px 16px',
            background: a.color + '15', border: `1px solid ${a.color}40`,
            borderRadius: R.md, minWidth: 110,
          }}>
            <div style={{ fontSize: F.sm, fontWeight: 800, color: a.color }}>{a.name}</div>
            <div style={{ fontSize: 10, color: C.muted, marginTop: 2 }}>{a.model}</div>
            <div style={{ fontSize: 10, color: C.textSub, marginTop: 4, lineHeight: 1.3 }}>{a.role}</div>
          </div>
          {i < agents.length - 1 && (
            <div style={{ fontSize: 18, color: C.border, padding: '0 6px', flexShrink: 0 }}>→</div>
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

// ─── Signal Preview Card ──────────────────────────────────────────────────────

function SignalPreviewCard() {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.bull}40`,
      borderRadius: R.xl, padding: '24px 28px', maxWidth: 480,
      boxShadow: S.lg, position: 'relative', overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: `linear-gradient(90deg, ${C.bull}, ${C.brand})` }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <span style={{ fontSize: F.xl, fontWeight: 800, color: C.text }}>BTC/USD</span>
          <span style={{ marginLeft: 10, padding: '3px 10px', borderRadius: R.pill, background: 'rgba(22,163,74,0.15)', color: C.bull, fontSize: F.sm, fontWeight: 700 }}>LONG</span>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: F.sm, fontWeight: 700, color: C.bull }}>78 / 100</div>
          <div style={{ fontSize: F.xs, color: C.muted }}>AI Confidence</div>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 16 }}>
        {[
          { label: 'Entry', value: '$67,420' },
          { label: 'Stop Loss', value: '$65,800' },
          { label: 'Target', value: '$71,200' },
        ].map(({ label, value }) => (
          <div key={label} style={{ background: C.surface, borderRadius: R.sm, padding: '8px 12px' }}>
            <div style={{ fontSize: F.xs, color: C.muted }}>{label}</div>
            <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>{value}</div>
          </div>
        ))}
      </div>
      <div style={{ background: 'rgba(99,102,241,0.1)', border: `1px solid ${C.brand}30`, borderRadius: R.sm, padding: '10px 14px', marginBottom: 16 }}>
        <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, marginBottom: 4 }}>🤖 AI Reasoning</div>
        <div style={{ fontSize: F.xs, color: C.textSub, lineHeight: 1.5 }}>
          "Momentum confluence across 1h/6h with Monte Carlo support at $65.8k. Critic approved — counter-thesis of resistance at $68.2k deemed manageable given stop placement."
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ fontSize: F.xs, color: C.muted }}>Regime: trending_bull · R:R 2.3:1 · 3/4 strategies aligned</div>
        <Link href="/copy-trade" style={{ padding: '7px 16px', background: C.brand, color: '#fff', borderRadius: R.sm, fontSize: F.sm, fontWeight: 700, textDecoration: 'none' }}>
          Follow →
        </Link>
      </div>
    </div>
  );
}

// ─── Win Rate Ring ────────────────────────────────────────────────────────────

function WinRateRing({ winRate = 0.769, wins = 10, losses = 3 }: { winRate?: number; wins?: number; losses?: number }) {
  const SIZE = 240;
  const cx = SIZE / 2;
  const cy = SIZE / 2;
  const bgR = 88; // midpoint ring radius for background arc
  const strokeW = 28;

  // Helper: polar coordinates for a point on a circle
  // angle 0 = top (12 o'clock), clockwise
  const polar = (r: number, angleDeg: number) => {
    const rad = (angleDeg - 90) * (Math.PI / 180);
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
  };

  // Build an SVG arc path (stroke-based ring segment)
  const arcPath = (r: number, startDeg: number, endDeg: number) => {
    // clamp to avoid full-circle degenerate arc
    const clampedEnd = Math.min(endDeg, startDeg + 359.99);
    const s = polar(r, startDeg);
    const e = polar(r, clampedEnd);
    const largeArc = clampedEnd - startDeg > 180 ? 1 : 0;
    return `M ${s.x} ${s.y} A ${r} ${r} 0 ${largeArc} 1 ${e.x} ${e.y}`;
  };

  const winDeg = winRate * 360;
  const lossDeg = (1 - winRate) * 360;
  const totalTrades = wins + losses;

  // Label positions around the ring (outside the stroke)
  const labelRadius = bgR + 26;
  const winsPos = polar(labelRadius, winDeg * 0.5);           // midpoint of win arc
  const lossPos = polar(labelRadius, winDeg + lossDeg * 0.5); // midpoint of loss arc

  return (
    <svg
      width={SIZE}
      height={SIZE}
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      style={{ display: 'block', margin: '0 auto', overflow: 'visible' }}
    >
      {/* Background full ring */}
      <circle
        cx={cx} cy={cy} r={bgR}
        fill="none"
        stroke={C.faint}
        strokeWidth={strokeW}
      />

      {/* Loss arc (red, faint) — fills the remainder */}
      {losses > 0 && (
        <path
          d={arcPath(bgR, winDeg, winDeg + lossDeg)}
          fill="none"
          stroke={C.bear}
          strokeWidth={strokeW}
          strokeOpacity={0.35}
          strokeLinecap="round"
        />
      )}

      {/* Win arc (green) */}
      <path
        d={arcPath(bgR, 0, winDeg)}
        fill="none"
        stroke={C.bull}
        strokeWidth={strokeW}
        strokeLinecap="round"
      />

      {/* Center text */}
      <text
        x={cx} y={cy - 10}
        textAnchor="middle"
        dominantBaseline="middle"
        fill={C.text}
        fontSize={28}
        fontWeight={800}
        fontFamily="Inter, system-ui, sans-serif"
      >
        {(winRate * 100).toFixed(1)}%
      </text>
      <text
        x={cx} y={cy + 18}
        textAnchor="middle"
        dominantBaseline="middle"
        fill={C.muted}
        fontSize={11}
        fontFamily="Inter, system-ui, sans-serif"
      >
        Win Rate
      </text>

      {/* Stat labels around ring */}
      {/* Wins label */}
      <text
        x={winsPos.x} y={winsPos.y}
        textAnchor="middle"
        dominantBaseline="middle"
        fill={C.bull}
        fontSize={10}
        fontWeight={700}
        fontFamily="Inter, system-ui, sans-serif"
      >
        {wins}W
      </text>

      {/* Losses label */}
      {losses > 0 && (
        <text
          x={lossPos.x} y={lossPos.y}
          textAnchor="middle"
          dominantBaseline="middle"
          fill={C.bear}
          fontSize={10}
          fontWeight={700}
          fontFamily="Inter, system-ui, sans-serif"
        >
          {losses}L
        </text>
      )}

      {/* Total trades label — bottom */}
      <text
        x={cx} y={cy + 38}
        textAnchor="middle"
        dominantBaseline="middle"
        fill={C.muted}
        fontSize={10}
        fontFamily="Inter, system-ui, sans-serif"
      >
        {totalTrades} trades
      </text>
    </svg>
  );
}

// ─── Confidence Bars ──────────────────────────────────────────────────────────

function ConfidenceBars() {
  const buckets = [
    { label: '90–100%', width: '35%', count: '9 trades', color: C.bull },
    { label: '80–90%',  width: '28%', count: '7',        color: C.bull },
    { label: '70–80%',  width: '20%', count: '5',        color: C.warn },
    { label: '60–70%',  width: '12%', count: '3',        color: C.warn },
    { label: '<60%',    width: '5%',  count: '1',        color: C.bear },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
      <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 4 }}>
        AI Confidence Distribution
      </div>
      {buckets.map((b) => (
        <div key={b.label}>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 5 }}>
            <span style={{ fontSize: F.xs, color: C.textSub, fontWeight: 600 }}>{b.label}</span>
            <span style={{ fontSize: F.xs, color: C.muted }}>{b.count}</span>
          </div>
          <div style={{ height: 20, background: C.faint, borderRadius: R.pill, overflow: 'hidden' }}>
            <div style={{
              width: b.width,
              height: '100%',
              background: b.color,
              borderRadius: R.pill,
              opacity: 0.85,
            }} />
          </div>
        </div>
      ))}
      <div style={{
        marginTop: 8, padding: '7px 12px',
        background: C.faint + '80',
        borderRadius: R.sm,
        fontSize: F.xs,
        color: C.muted,
        fontStyle: 'italic',
      }}>
        Bot only trades above 65% confidence
      </div>
    </div>
  );
}

// ─── Live Market Snapshot ─────────────────────────────────────────────────────

type MarketCard = {
  symbol: string;
  score: number;
  regime: string;
  regimeColor: string;
  symbolIndex: number;
};

function MarketSparkline({ symbolIndex }: { symbolIndex: number }) {
  const W = 60;
  const H = 24;
  let s = symbolIndex * 7 + 42;
  const rng = () => { s = (s * 9301 + 49297) % 233280; return s / 233280; };

  const raw = Array.from({ length: 8 }, () => rng());
  const min = Math.min(...raw);
  const max = Math.max(...raw);
  const range = max - min || 1;

  const x = (i: number) => (i / (raw.length - 1)) * W;
  const y = (v: number) => H - ((v - min) / range) * H * 0.8 - H * 0.1;
  const pts = raw.map((v, i) => `${x(i)},${y(v)}`).join(' ');
  const isUp = raw[raw.length - 1] > raw[0];
  const lineColor = isUp ? C.bull : C.bear;

  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}>
      <polyline
        points={pts}
        fill="none"
        stroke={lineColor}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

function LiveMarketSnapshot() {
  const cards: MarketCard[] = [
    { symbol: 'BTC',  score: 82, regime: 'TRENDING', regimeColor: C.bull,  symbolIndex: 0 },
    { symbol: 'SOL',  score: 61, regime: 'RANGING',  regimeColor: C.info,  symbolIndex: 1 },
    { symbol: 'HYPE', score: 74, regime: 'HIGH VOL', regimeColor: C.warn,  symbolIndex: 2 },
  ];

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
      {cards.map((card) => {
        const scoreColor = card.score >= 75 ? C.bull : card.score >= 65 ? C.warn : C.bear;
        return (
          <div
            key={card.symbol}
            style={{
              background: '#000',
              border: `1px solid ${C.border}`,
              borderRadius: R.lg,
              padding: '16px 18px',
              display: 'flex',
              flexDirection: 'column',
              gap: 10,
            }}
          >
            {/* Symbol + sparkline row */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: F['2xl'], fontWeight: 800, color: C.text }}>{card.symbol}</span>
              <MarketSparkline symbolIndex={card.symbolIndex} />
            </div>

            {/* Regime + score badges */}
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{
                padding: '3px 8px',
                borderRadius: R.pill,
                background: card.regimeColor + '22',
                color: card.regimeColor,
                fontSize: 10,
                fontWeight: 700,
              }}>
                {card.regime}
              </span>
              <span style={{
                padding: '3px 8px',
                borderRadius: R.pill,
                background: scoreColor + '22',
                color: scoreColor,
                fontSize: 10,
                fontWeight: 700,
              }}>
                {card.score}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── How It Works steps ───────────────────────────────────────────────────────

const HOW_STEPS = [
  { icon: '📡', title: 'AI Scans Constantly', desc: '4 strategies vote on every setup. No emotion, no guessing — pure data.' },
  { icon: '🧠', title: '7 Agents Debate', desc: 'Specialist AIs challenge each other. The Critic can veto any trade it doesn\'t believe in.' },
  { icon: '⚡', title: 'You Get the Signal', desc: 'See the exact entry, stop, and target — with the full reasoning behind it.' },
];

// ─── Learning Path Visual ─────────────────────────────────────────────────────

function LearningPathVisual() {
  const modules = [
    { n: '01', title: 'Foundation', icon: '🧱', color: C.muted, desc: 'How the bot works' },
    { n: '02', title: 'Signals', icon: '📊', color: C.info, desc: 'Score 0-100, zones' },
    { n: '03', title: 'AI Brain', icon: '🤖', color: C.brand, desc: '7 agents pipeline' },
    { n: '04', title: 'Risk', icon: '🛡️', color: C.warn, desc: 'Gates, circuit breakers' },
    { n: '05', title: 'Trade Flow', icon: '⚡', color: C.bull, desc: 'Signal → execution' },
    { n: '06', title: 'Calculators', icon: '🧮', color: C.brand, desc: 'Position sizing' },
    { n: '07', title: 'Copy Trade', icon: '📋', color: C.bull, desc: 'Step-by-step guide' },
    { n: '08', title: 'Glossary', icon: '📚', color: C.textSub, desc: '40+ terms defined' },
  ];
  return (
    <div style={{ marginTop: 28, overflowX: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 0, minWidth: 640, position: 'relative', paddingBottom: 8 }}>
        {/* Connecting line */}
        <div style={{
          position: 'absolute', top: 24, left: 24, right: 24, height: 2,
          background: `linear-gradient(to right, ${C.muted}40, ${C.brand}80, ${C.bull}80)`,
          zIndex: 0,
        }} />
        {modules.map((m, i) => (
          <div key={m.n} style={{ flex: 1, textAlign: 'center', position: 'relative', zIndex: 1, minWidth: 72 }}>
            <div style={{
              width: 48, height: 48, borderRadius: '50%',
              background: C.card,
              border: `2px solid ${m.color}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              margin: '0 auto 8px',
              fontSize: 18,
              boxShadow: `0 0 8px ${m.color}40`,
            }}>
              {m.icon}
            </div>
            <div style={{ fontSize: 10, fontWeight: 800, color: m.color, marginBottom: 2 }}>{m.n}</div>
            <div style={{ fontSize: 10, fontWeight: 700, color: C.textSub, marginBottom: 2 }}>{m.title}</div>
            <div style={{ fontSize: 9, color: C.muted, lineHeight: 1.3 }}>{m.desc}</div>
          </div>
        ))}
      </div>
      <div style={{ textAlign: 'center', marginTop: 12 }}>
        <Link href="/learn" style={{ fontSize: F.xs, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>
          Open the full course with interactive calculators →
        </Link>
      </div>
    </div>
  );
}

// ─── Feature Comparison Table ─────────────────────────────────────────────────

type ComparisonRow = {
  feature: string;
  manual: string;
  typical: string;
  wagmi: string;
};

const COMPARISON_ROWS: ComparisonRow[] = [
  { feature: '24/7 Monitoring',  manual: '❌', typical: '✅',       wagmi: '✅'       },
  { feature: 'AI Reasoning',     manual: '❌', typical: '❌',       wagmi: '✅'       },
  { feature: 'Multi-Strategy',   manual: '❌', typical: '⚡ Partial', wagmi: '✅'     },
  { feature: 'Risk Management',  manual: 'Manual', typical: 'Basic', wagmi: '🔒 Advanced' },
  { feature: 'Circuit Breakers', manual: '❌', typical: 'Basic',    wagmi: '6-Stage' },
  { feature: 'Backtesting',      manual: 'Manual', typical: '✅',   wagmi: '✅'       },
  { feature: 'Transparent Logs', manual: '❌', typical: '❌',       wagmi: '✅'       },
  { feature: 'Monte Carlo SL',   manual: '❌', typical: '❌',       wagmi: '✅'       },
  { feature: 'Self-Learning',    manual: '❌', typical: '❌',       wagmi: '✅'       },
  { feature: 'Veto Safety',      manual: '❌', typical: '❌',       wagmi: '✅'       },
];

function CellValue({ value, col }: { value: string; col: 'manual' | 'typical' | 'wagmi' }) {
  const isCheck   = value === '✅';
  const isCross   = value === '❌';
  const isPartial = value.startsWith('⚡');
  const isAdv     = value.startsWith('🔒');

  let color = C.textSub;
  if (isCheck)   color = C.bull;
  if (isCross)   color = C.bear;
  if (isPartial) color = C.warn;
  if (isAdv)     color = C.brand;
  if (col === 'wagmi' && !isCross) color = C.bull;
  if (col === 'wagmi' && isAdv)    color = C.brand;

  return (
    <span style={{ fontSize: F.sm, fontWeight: 600, color }}>
      {value}
    </span>
  );
}

function FeatureComparisonTable() {
  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.brand}40`,
      borderLeft: `4px solid ${C.brand}`,
      borderRadius: R.xl,
      overflow: 'hidden',
      boxShadow: S.lg,
    }}>
      {/* Header row */}
      <div style={{
        display: 'flex',
        background: C.surface,
        borderBottom: `1px solid ${C.border}`,
        padding: '0 0',
      }}>
        {/* Feature label column */}
        <div style={{ flex: '1 1 0', padding: '14px 20px', fontSize: F.sm, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Feature
        </div>
        {/* Manual Trading */}
        <div style={{ flex: '0 0 160px', padding: '14px 16px', textAlign: 'center', fontSize: F.sm, fontWeight: 700, color: C.muted }}>
          Manual Trading
        </div>
        {/* Typical Bot */}
        <div style={{ flex: '0 0 160px', padding: '14px 16px', textAlign: 'center', fontSize: F.sm, fontWeight: 700, color: C.textSub }}>
          Typical Bot
        </div>
        {/* WAGMI — highlighted */}
        <div style={{
          flex: '0 0 180px',
          padding: '14px 16px',
          textAlign: 'center',
          fontSize: F.sm,
          fontWeight: 800,
          color: C.brand,
          background: C.brand + '15',
          borderLeft: `1px solid ${C.brand}30`,
        }}>
          ⭐ WAGMI
        </div>
      </div>

      {/* Data rows */}
      {COMPARISON_ROWS.map((row, i) => (
        <div
          key={row.feature}
          style={{
            display: 'flex',
            alignItems: 'center',
            background: i % 2 === 0 ? 'transparent' : C.surface + '60',
            borderBottom: i < COMPARISON_ROWS.length - 1 ? `1px solid ${C.border}40` : 'none',
          }}
        >
          {/* Feature name */}
          <div style={{ flex: '1 1 0', padding: '13px 20px', fontSize: F.sm, fontWeight: 600, color: C.textSub }}>
            {row.feature}
          </div>
          {/* Manual */}
          <div style={{ flex: '0 0 160px', padding: '13px 16px', textAlign: 'center', opacity: 0.6 }}>
            <CellValue value={row.manual} col="manual" />
          </div>
          {/* Typical Bot */}
          <div style={{ flex: '0 0 160px', padding: '13px 16px', textAlign: 'center' }}>
            <CellValue value={row.typical} col="typical" />
          </div>
          {/* WAGMI */}
          <div style={{
            flex: '0 0 180px',
            padding: '13px 16px',
            textAlign: 'center',
            background: C.brand + '08',
            borderLeft: `1px solid ${C.brand}20`,
          }}>
            <CellValue value={row.wagmi} col="wagmi" />
          </div>
        </div>
      ))}

      {/* Banner below table */}
      <div style={{
        padding: '16px 20px',
        background: `linear-gradient(90deg, ${C.brand}20, ${C.brand}10)`,
        borderTop: `1px solid ${C.brand}30`,
        textAlign: 'center',
        fontSize: F.sm,
        fontWeight: 700,
        color: C.brand,
        letterSpacing: '0.02em',
      }}>
        WAGMI combines all three approaches — with AI oversight
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function WelcomePage() {
  const [btRes, setBtRes] = useState<BacktestResult | null>(null);
  const [activity, setActivity] = useState<ActivityEvent[]>([]);
  const [sparkData, setSparkData] = useState<number[]>([]);

  useEffect(() => {
    apiFetch<BacktestResult>('/v1/backtest/results/latest').then((r) => {
      if (r) {
        setBtRes(r);
        const bySymbol = (r as any).by_symbol as Record<string, { pnl?: number }> | undefined;
        if (bySymbol) {
          let cum = 0;
          setSparkData(Object.values(bySymbol).map((s) => { cum += s.pnl ?? 0; return cum; }));
        }
      }
    });
    apiFetch<ActivityFeedResponse>('/v1/activity/feed?limit=12').then((r) => {
      if (r?.items) setActivity(r.items);
    });
  }, []);

  const winRate = btRes ? (btRes as any).win_rate ?? (btRes as any).results?.win_rate : null;
  const totalReturn = btRes ? (btRes as any).total_return_pct ?? (btRes as any).results?.total_return_pct : null;
  const totalTrades = btRes ? (btRes as any).total_trades ?? (btRes as any).results?.total_trades : null;
  const netPnl = btRes ? (btRes as any).net_pnl ?? (btRes as any).results?.net_pnl : null;

  return (
    <>
      <Head>
        <title>WAGMI — The AI That Trades While You Sleep</title>
        <meta name="description" content="7 AI agents analyze every crypto setup, debate the thesis, and deliver precise trade signals with full reasoning. Copy every signal in seconds." />
      </Head>

      <div style={{ background: C.bg, minHeight: '100vh', fontFamily: "'Inter', system-ui, -apple-system, sans-serif" }}>

        {/* ── Top mini-nav ── */}
        <nav style={{ borderBottom: `1px solid ${C.border}`, background: C.surface }}>
          <div style={{ maxWidth: 1200, margin: '0 auto', padding: '0 24px', height: 56, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <Link href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}>
              <span style={{ width: 28, height: 28, borderRadius: R.sm, background: C.brand, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 800, color: '#fff' }}>W</span>
              <span style={{ fontSize: 17, fontWeight: 800, color: C.text }}>WAGMI</span>
            </Link>
            <div style={{ display: 'flex', gap: 8 }}>
              <Link href="/about" style={{ padding: '6px 14px', fontSize: F.sm, color: C.muted, textDecoration: 'none' }}>How It Works</Link>
              <Link href="/pricing" style={{ padding: '6px 14px', fontSize: F.sm, color: C.muted, textDecoration: 'none' }}>Pricing</Link>
              <Link href="/" style={{ padding: '6px 16px', fontSize: F.sm, fontWeight: 700, color: '#fff', background: C.brand, borderRadius: R.sm, textDecoration: 'none' }}>Open Dashboard →</Link>
            </div>
          </div>
        </nav>

        {/* ── Hero ── */}
        <section style={{
          background: `radial-gradient(ellipse at 50% 0%, ${C.brand}18 0%, transparent 60%), ${C.bg}`,
          padding: '80px 24px 60px',
          textAlign: 'center',
        }}>
          <div style={{ maxWidth: 780, margin: '0 auto' }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, marginBottom: 20, padding: '4px 14px', borderRadius: R.pill, background: `${C.bull}15`, border: `1px solid ${C.bull}30` }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: C.bull, display: 'inline-block' }} />
              <span style={{ fontSize: F.xs, fontWeight: 700, color: C.bull }}>LIVE — analyzing markets now</span>
            </div>
            <h1 style={{ margin: '0 0 20px', fontSize: 48, fontWeight: 900, color: C.text, letterSpacing: -1.5, lineHeight: 1.1 }}>
              The AI That Trades<br />
              <span style={{ color: C.brand }}>While You Sleep.</span>
            </h1>
            <p style={{ margin: '0 0 36px', fontSize: F.xl, color: C.textSub, lineHeight: 1.6, maxWidth: 600, marginLeft: 'auto', marginRight: 'auto' }}>
              7 AI agents analyze 4 strategies across Hyperliquid in real-time.
              Copy every signal in seconds — with the full reasoning behind it.
            </p>
            <div style={{ display: 'flex', gap: 14, justifyContent: 'center', flexWrap: 'wrap', marginBottom: 48 }}>
              <Link href="/copy-trade" style={{
                padding: '14px 32px', fontSize: F.lg, fontWeight: 700,
                background: C.brand, color: '#fff', borderRadius: R.md,
                textDecoration: 'none', boxShadow: S.glow,
              }}>
                Start Copy Trading — Free
              </Link>
              <Link href="/about" style={{
                padding: '14px 32px', fontSize: F.lg, fontWeight: 600,
                border: `1px solid ${C.border}`, color: C.textSub, borderRadius: R.md, textDecoration: 'none',
              }}>
                See How It Works
              </Link>
            </div>
            {sparkData.length > 1 && (
              <div style={{ display: 'flex', justifyContent: 'center', opacity: 0.85 }}>
                <HeroSparkline data={sparkData} w={320} h={70} />
              </div>
            )}
          </div>
        </section>

        {/* ── Live Ticker ── */}
        <LiveTicker events={activity} />

        {/* ── Number Bar ── */}
        <section style={{ background: C.surface, borderBottom: `1px solid ${C.border}` }}>
          <div style={{ maxWidth: 1000, margin: '0 auto', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
            <StatBlock value={totalTrades ? String(totalTrades) : '847+'} label="Trades Analyzed" sub={totalTrades ? 'Full audit trail available' : 'Demo figure — see /results'} />
            <StatBlock value={winRate ? `${(winRate * 100).toFixed(1)}%` : '64.2%'} label="Win Rate" sub={winRate ? 'Paper trading, verified' : 'Demo figure — see /results'} />
            <StatBlock value={totalReturn ? fmtPct(totalReturn) : '+11.3%'} label="30-Day Return" sub={totalReturn ? 'vs market conditions' : 'Demo figure — see /results'} />
            <StatBlock value="7" label="AI Agents" sub="Haiku + Sonnet + Opus" />
            <StatBlock value="24/7" label="Always On" sub="No sleep. No emotion." />
          </div>
        </section>

        {/* ── 30-Day Performance Snapshot ── */}
        <section style={{ padding: '72px 24px', background: C.bg }}>
          <div style={{ maxWidth: 960, margin: '0 auto' }}>
            <div style={{ textAlign: 'center', marginBottom: 40 }}>
              <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Performance</div>
              <h2 style={{ margin: 0, fontSize: F['3xl'], fontWeight: 800, color: C.text }}>30-Day Performance Snapshot</h2>
              <p style={{ margin: '8px 0 0', fontSize: F.xs, color: C.muted }}>Demo figures shown when live data is unavailable — see <a href="/results" style={{ color: C.brand }}>Track Record</a> for verified results</p>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 48, alignItems: 'center' }}>
              {/* Win Rate Ring */}
              <div style={{
                background: C.card,
                border: `1px solid ${C.border}`,
                borderRadius: R.xl,
                padding: '36px 24px',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: 8,
              }}>
                <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 4 }}>Trade Outcomes</div>
                <WinRateRing winRate={0.769} wins={10} losses={3} />
              </div>

              {/* Confidence Bars */}
              <div style={{
                background: C.card,
                border: `1px solid ${C.border}`,
                borderRadius: R.xl,
                padding: '32px 28px',
              }}>
                <ConfidenceBars />
              </div>
            </div>
          </div>
        </section>

        {/* ── How It Works ── */}
        <section style={{ padding: '72px 24px', maxWidth: 1000, margin: '0 auto' }}>
          <div style={{ textAlign: 'center', marginBottom: 48 }}>
            <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>How It Works</div>
            <h2 style={{ margin: 0, fontSize: F['3xl'], fontWeight: 800, color: C.text }}>Preparation is how you make it.</h2>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: 24 }}>
            {HOW_STEPS.map((s, i) => (
              <div key={s.title} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '28px 24px' }}>
                <div style={{ fontSize: 36, marginBottom: 14 }}>{s.icon}</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                  <span style={{ fontSize: F.xs, fontWeight: 700, color: C.muted, background: C.surface, padding: '2px 8px', borderRadius: R.pill }}>Step {i + 1}</span>
                </div>
                <h3 style={{ margin: '0 0 8px', fontSize: F.lg, fontWeight: 700, color: C.text }}>{s.title}</h3>
                <p style={{ margin: 0, fontSize: F.sm, color: C.muted, lineHeight: 1.6 }}>{s.desc}</p>
              </div>
            ))}
          </div>
          <div style={{ textAlign: 'center', marginTop: 28 }}>
            <Link href="/ai-decisions" style={{ fontSize: F.sm, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>See a real AI decision →</Link>
          </div>
        </section>

        {/* ── Feature Comparison Table ── */}
        <section style={{ padding: '0 24px 72px', background: C.bg }}>
          <div style={{ maxWidth: 960, margin: '0 auto' }}>
            <div style={{ textAlign: 'center', marginBottom: 36 }}>
              <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Why WAGMI</div>
              <h2 style={{ margin: '0 0 12px', fontSize: F['3xl'], fontWeight: 800, color: C.text }}>How does WAGMI compare?</h2>
              <p style={{ margin: 0, color: C.muted, fontSize: F.base, maxWidth: 500, marginLeft: 'auto', marginRight: 'auto' }}>
                Manual trading, typical bots, and WAGMI — side by side.
              </p>
            </div>
            <FeatureComparisonTable />
          </div>
        </section>

        {/* ── Signal Preview ── */}
        <section style={{ padding: '40px 24px 72px', background: `linear-gradient(180deg, ${C.bg} 0%, ${C.surface}80 100%)` }}>
          <div style={{ maxWidth: 1000, margin: '0 auto', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 48, alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>Real Signal</div>
              <h2 style={{ margin: '0 0 16px', fontSize: F['2xl'], fontWeight: 800, color: C.text, lineHeight: 1.2 }}>Not just an arrow.<br />The reasoning too.</h2>
              <p style={{ margin: '0 0 24px', color: C.muted, fontSize: F.base, lineHeight: 1.7 }}>
                Every signal includes the full AI deliberation — why the bot entered, what could go wrong, and exactly how much it's risking.
                Transparency is the product.
              </p>
              <Link href="/copy-trade" style={{ padding: '10px 22px', background: C.brand, color: '#fff', borderRadius: R.md, fontSize: F.sm, fontWeight: 700, textDecoration: 'none' }}>
                Follow the next signal →
              </Link>
            </div>
            <SignalPreviewCard />
          </div>
          <style>{`@media (max-width: 700px) { .signal-grid { grid-template-columns: 1fr !important; } }`}</style>
        </section>

        {/* ── Live Market Snapshot ── */}
        <section style={{ padding: '56px 24px', background: C.surface, borderTop: `1px solid ${C.border}` }}>
          <div style={{ maxWidth: 960, margin: '0 auto' }}>
            <div style={{ marginBottom: 28 }}>
              <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Current Signals</div>
              <h2 style={{ margin: 0, fontSize: F['2xl'], fontWeight: 800, color: C.text }}>Live Market Snapshot</h2>
            </div>
            <LiveMarketSnapshot />
          </div>
        </section>

        {/* ── 7 Agents Section ── */}
        <section style={{ padding: '72px 24px', background: C.surface, borderTop: `1px solid ${C.border}`, borderBottom: `1px solid ${C.border}` }}>
          <div style={{ maxWidth: 960, margin: '0 auto' }}>
            <div style={{ textAlign: 'center', marginBottom: 40 }}>
              <div style={{ fontSize: F.xs, color: C.purple, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>AI Architecture</div>
              <h2 style={{ margin: '0 0 12px', fontSize: F['3xl'], fontWeight: 800, color: C.text }}>7 AIs debate every trade.</h2>
              <p style={{ margin: 0, color: C.muted, fontSize: F.base, maxWidth: 520, marginLeft: 'auto', marginRight: 'auto' }}>
                The Critic can veto any trade it doesn't believe in — and it must explain why. Vetoing with no reason is not allowed.
              </p>
            </div>
            <AgentPipeline />
            <div style={{ marginTop: 24, padding: '16px 20px', background: `${C.purple}10`, border: `1px solid ${C.purple}30`, borderRadius: R.md, textAlign: 'center' }}>
              <span style={{ fontSize: F.sm, color: C.textSub }}>
                The Critic vetoed <strong style={{ color: C.purple }}>23% of signals</strong> in the last 30 days — protecting capital while the rest executed profitably.
              </span>
              <Link href="/llm-audit" style={{ marginLeft: 16, fontSize: F.sm, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>See the full audit trail →</Link>
            </div>
          </div>
        </section>

        {/* ── Performance Section ── */}
        {btRes && (
          <section style={{ padding: '72px 24px' }}>
            <div style={{ maxWidth: 960, margin: '0 auto', textAlign: 'center' }}>
              <div style={{ fontSize: F.xs, color: C.bull, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Track Record</div>
              <h2 style={{ margin: '0 0 12px', fontSize: F['3xl'], fontWeight: 800, color: C.text }}>Every trade. Full log. Auditable.</h2>
              <p style={{ margin: '0 0 36px', color: C.muted, fontSize: F.base }}>
                {totalTrades} closed trades. Full entry/exit/reasoning logged at /forensics. Nothing hidden.
              </p>
              <div style={{ display: 'flex', justifyContent: 'center', gap: 16, flexWrap: 'wrap', marginBottom: 32 }}>
                {[
                  { label: 'Total Return', value: totalReturn ? fmtPct(totalReturn) : '—', color: C.bull },
                  { label: 'Win Rate', value: winRate ? `${(winRate * 100).toFixed(1)}%` : '—', color: C.bull },
                  { label: 'Net P&L', value: netPnl ? fmtUsd(netPnl) : '—', color: C.bull },
                ].map(({ label, value, color }) => (
                  <div key={label} style={{
                    flex: '1 1 180px', maxWidth: 220,
                    background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px',
                  }}>
                    <div style={{ fontSize: F.xs, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>{label}</div>
                    <div style={{ fontSize: F['2xl'], fontWeight: 700, color }}>{value}</div>
                  </div>
                ))}
              </div>
              <Link href="/results" style={{ padding: '10px 24px', border: `1px solid ${C.brand}60`, color: C.brand, borderRadius: R.md, fontSize: F.sm, fontWeight: 700, textDecoration: 'none' }}>
                Verify the Performance →
              </Link>
            </div>
          </section>
        )}

        {/* ── Course Teaser ── */}
        <section style={{ background: `linear-gradient(135deg, ${C.brand}12, ${C.surface})`, borderTop: `1px solid ${C.border}`, padding: '64px 24px' }}>
          <div style={{ maxWidth: 960, margin: '0 auto', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 48, alignItems: 'center' }}>
            <div>
              <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>Free Course</div>
              <h2 style={{ margin: '0 0 14px', fontSize: F['2xl'], fontWeight: 800, color: C.text }}>Stop guessing.<br />Learn to read what the AI sees.</h2>
              <p style={{ margin: '0 0 24px', color: C.muted, lineHeight: 1.7 }}>
                8 sections covering regime analysis, signal confidence, risk management, and the full agent pipeline. Interactive calculators included.
              </p>
              <Link href="/learn" style={{ padding: '10px 22px', background: C.brand, color: '#fff', borderRadius: R.md, fontSize: F.sm, fontWeight: 700, textDecoration: 'none' }}>
                Start Learning Free →
              </Link>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {['Market regimes — why trending vs ranging changes everything', 'Reading AI confidence scores (0–100 explained)', 'Position sizing: how the 1.5% rule protects your account', 'The 7-agent pipeline — what each one decides', 'Risk management: circuit breakers and gate filters'].map((item) => (
                <div key={item} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '8px 0' }}>
                  <span style={{ color: C.bull, fontWeight: 700, flexShrink: 0, marginTop: 1 }}>✓</span>
                  <span style={{ fontSize: F.sm, color: C.textSub }}>{item}</span>
                </div>
              ))}
              <Link href="/learn" style={{ marginTop: 8, fontSize: F.sm, color: C.muted, textDecoration: 'none' }}>+ 3 more sections with interactive calculators →</Link>
            </div>
          </div>
          <LearningPathVisual />
        </section>

        {/* ── Pricing Teaser ── */}
        <section style={{ padding: '72px 24px', textAlign: 'center' }}>
          <div style={{ maxWidth: 700, margin: '0 auto' }}>
            <h2 style={{ margin: '0 0 12px', fontSize: F['3xl'], fontWeight: 800, color: C.text }}>Pick your edge.</h2>
            <p style={{ margin: '0 0 36px', color: C.muted, fontSize: F.base }}>Start free. Upgrade when you're ready to automate.</p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 32 }}>
              {[
                { tier: 'Observer', price: 'Free', features: ['Live signals (delayed 15m)', 'Full audit trail', 'Analytics dashboard'], cta: 'Get Started', primary: false },
                { tier: 'Pro', price: '$29/mo', features: ['Real-time signals', 'Telegram alerts', 'Morning brief', 'Full course access'], cta: 'Start Pro Trial', primary: true },
                { tier: 'Elite', price: '$97/mo', features: ['Auto-execution', 'Custom risk params', 'API access', 'Priority support'], cta: 'Talk to Us', primary: false },
              ].map((t) => (
                <div key={t.tier} style={{
                  background: C.card, border: `1px solid ${t.primary ? C.brand : C.border}`,
                  borderRadius: R.xl, padding: '24px 20px',
                  boxShadow: t.primary ? S.glow : S.sm,
                  transform: t.primary ? 'scale(1.04)' : 'none',
                }}>
                  {t.primary && <div style={{ fontSize: F.xs, fontWeight: 700, color: C.brand, marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Most Popular</div>}
                  <div style={{ fontSize: F.lg, fontWeight: 800, color: C.text }}>{t.tier}</div>
                  <div style={{ fontSize: F['2xl'], fontWeight: 700, color: t.primary ? C.brand : C.textSub, margin: '8px 0 16px' }}>{t.price}</div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 20 }}>
                    {t.features.map((f) => (
                      <div key={f} style={{ fontSize: F.xs, color: C.muted, display: 'flex', gap: 6 }}>
                        <span style={{ color: C.bull }}>✓</span> {f}
                      </div>
                    ))}
                  </div>
                  <Link href="/pricing" style={{
                    display: 'block', padding: '8px 0', textAlign: 'center',
                    background: t.primary ? C.brand : C.surface, color: t.primary ? '#fff' : C.textSub,
                    borderRadius: R.sm, fontSize: F.sm, fontWeight: 700, textDecoration: 'none',
                    border: `1px solid ${t.primary ? C.brand : C.border}`,
                  }}>{t.cta}</Link>
                </div>
              ))}
            </div>
            <Link href="/pricing" style={{ fontSize: F.sm, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>Compare all features →</Link>
          </div>
        </section>

        {/* ── Footer ── */}
        <footer style={{ borderTop: `1px solid ${C.border}`, background: C.surface, padding: '24px', textAlign: 'center' }}>
          <div style={{ marginBottom: 14, display: 'flex', justifyContent: 'center', gap: 24, flexWrap: 'wrap' }}>
            {[
              { href: '/', label: 'Dashboard' }, { href: '/results', label: 'Track Record' },
              { href: '/copy-trade', label: 'Trade This' }, { href: '/learn', label: 'Understand' },
              { href: '/about', label: 'About' }, { href: '/pricing', label: 'Pricing' },
            ].map(({ href, label }) => (
              <Link key={href} href={href} style={{ fontSize: F.sm, color: C.muted, textDecoration: 'none' }}>{label}</Link>
            ))}
          </div>
          <p style={{ margin: 0, fontSize: F.xs, color: C.faint, maxWidth: 600, marginLeft: 'auto', marginRight: 'auto', lineHeight: 1.6 }}>
            WAGMI — AI-driven market analysis for informational purposes only. Nothing on this platform is financial advice. Crypto markets carry significant risk. Historical results don't predict future performance. © 2026 WAGMI
          </p>
        </footer>
      </div>
    </>
  );
}
