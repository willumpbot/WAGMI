import React, { useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { C, R, S, F, G, Glass, SP } from '../src/theme';
import { staggerContainer, fadeUp, hoverGlow } from '../src/animations';

// ─── Gate Funnel Diagram ──────────────────────────────────────────────────────

function GateFunnelChart() {
  const steps = [
    { label: 'Signals Generated', note: 'All candidate signals from 4 strategies', color: C.brand },
    { label: 'Gate 1: Validity', note: 'Valid SL/TP, R:R ≥ 1.0, stop width ≥ 0.3%', color: C.brand },
    { label: 'Gate 2: Circuit Breaker', note: 'No daily loss limit or loss streak active', color: C.info },
    { label: 'Gate 3: Position Limits', note: 'Position count within cap', color: C.info },
    { label: 'Gate 4: Leverage Check', note: 'Leverage within regime-appropriate limits', color: C.warn },
    { label: 'Gate 5: Liquidation Safety', note: 'SL clears liquidation price by safe margin', color: C.warn },
    { label: 'Gate 6: Position Sizing', note: '1.5% risk rule applied, size computed', color: C.bull },
    { label: 'AI Critic Review', note: 'Critic agent stress-tests thesis; can veto', color: C.purple },
    { label: 'EXECUTE', note: 'Order sent to exchange — only the strongest setups reach here', color: C.bull },
  ];

  return (
    <div className="glass-card card-hover glass-noise" style={{ ...Glass.card, borderRadius: R.lg, padding: '18px 20px', marginTop: 20 }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 4 }}>Signal Funnel — How Signals Become Trades</div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 16 }}>Every signal must pass all 6 gates plus an AI review before reaching the exchange. Only the strongest setups survive.</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {steps.map((step, i) => {
          const isLast = i === steps.length - 1;
          return (
            <div key={step.label}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                <div style={{
                  flexShrink: 0,
                  width: 8,
                  height: 8,
                  marginTop: 5,
                  borderRadius: '50%',
                  background: step.color,
                  opacity: isLast ? 1 : 0.75,
                }} />
                <div>
                  <div style={{ fontSize: F.xs, fontWeight: isLast ? 800 : 600, color: isLast ? step.color : C.textSub }}>{step.label}</div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>{step.note}</div>
                </div>
              </div>
              {!isLast && (
                <div style={{ marginLeft: 3, width: 2, height: 10, background: C.border, borderRadius: 1, marginTop: 2, marginBottom: 2 }} />
              )}
            </div>
          );
        })}
      </div>
      <div style={{ marginTop: 12, padding: '8px 12px', background: `${C.bull}10`, border: `1px solid ${C.bull}25`, borderRadius: R.sm, fontSize: F.xs, color: C.textSub }}>
        <strong style={{ color: C.bull }}>Stringent gates ensure only high-quality signals execute</strong> — only the strongest setups reach the exchange. Run the bot to see your actual execution rate.
      </div>
    </div>
  );
}

// ─── Accordion ────────────────────────────────────────────────────────────────

function FAQ({ q, a }: { q: string; a: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ border: `1px solid ${open ? C.borderBright : C.border}`, borderRadius: R.md, marginBottom: 8, overflow: 'hidden' }}>
      <button onClick={() => setOpen((v) => !v)} style={{
        width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '14px 18px', ...Glass.card, border: 'none', cursor: 'pointer', textAlign: 'left', gap: 12,
      }}>
        <span style={{ fontSize: F.sm, fontWeight: 600, color: C.text }}>{q}</span>
        <span style={{ color: C.muted, flexShrink: 0, fontSize: F.lg, transition: 'transform 0.15s', transform: open ? 'rotate(45deg)' : 'none' }}>+</span>
      </button>
      {open && (
        <div style={{ padding: '0 18px 16px', fontSize: F.sm, color: C.textSub, lineHeight: 1.7, ...Glass.card, borderTop: `1px solid ${C.border}` }}>
          {a}
        </div>
      )}
    </div>
  );
}

// ─── Section ──────────────────────────────────────────────────────────────────

function Section({ id, eyebrow, title, children }: { id?: string; eyebrow: string; title: string; children: React.ReactNode }) {
  return (
    <div id={id} style={{ marginBottom: 32, scrollMarginTop: 80 }}>
      <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>{eyebrow}</div>
      <h2 style={{ margin: '0 0 24px', fontSize: F['2xl'], fontWeight: 800, color: C.text }}>{title}</h2>
      {children}
    </div>
  );
}

// ─── Agent Card ───────────────────────────────────────────────────────────────

type AgentSpec = { name: string; model: string; cost: string; role: string; decides: string; color: string };
const AGENTS: AgentSpec[] = [
  { name: 'Regime Agent', model: 'Claude Haiku', cost: '~$0.0001/call', role: 'Classifies current market conditions', decides: 'Is this trending, ranging, volatile, or panic? What\'s the directional bias?', color: C.info },
  { name: 'Trade Agent', model: 'Claude Sonnet', cost: '~$0.003/call', role: 'Forms the directional thesis', decides: 'Should the bot go long, short, or skip? What\'s the entry rationale?', color: C.brand },
  { name: 'Risk Agent', model: 'Claude Haiku', cost: '~$0.0001/call', role: 'Sizes the position and flags risks', decides: 'How much capital to deploy? What leverage? Any portfolio concentration concerns?', color: C.warn },
  { name: 'Critic Agent', model: 'Claude Sonnet', cost: '~$0.003/call', role: 'Stress-tests the thesis with a counter-argument', decides: 'What could go wrong? Must provide a counter-thesis. Can VETO the trade.', color: C.purple },
  { name: 'Learning Agent', model: 'Claude Haiku', cost: '~$0.0001/call', role: 'Post-trade pattern extraction', decides: 'What did this trade teach us? Update hypothesis accuracy tracking.', color: C.bull },
  { name: 'Exit Agent', model: 'Claude Haiku', cost: '~$0.0001/call', role: 'Monitors open positions continuously', decides: 'Is the thesis still valid? Recommend hold, adjust stop, or close early.', color: C.warnMid },
  { name: 'Scout Agent', model: 'Claude Haiku', cost: '~$0.0001/call', role: 'Idle-time setup preparation', decides: 'What setups are forming? Pre-score upcoming opportunities before they trigger.', color: C.muted },
];

// ─── Tech Stack Grid ──────────────────────────────────────────────────────────

type TechItem = { abbr: string; name: string; desc: string; tag: string; tagColor: string; bg: string; abbrBg: string };

const TECH_ITEMS: TechItem[] = [
  // AI/LLM
  { abbr: 'CL', name: 'Claude API (Anthropic)', desc: 'Decision making brain', tag: 'AI/LLM', tagColor: C.brand, bg: `${C.brand}09`, abbrBg: C.brand },
  { abbr: 'MA', name: 'Multi-Agent Pipeline', desc: '7 specialist agents', tag: 'AI/LLM', tagColor: C.brand, bg: `${C.brand}09`, abbrBg: C.brand },
  { abbr: 'CC', name: 'Confidence Calibration', desc: 'Self-improving accuracy', tag: 'AI/LLM', tagColor: C.brand, bg: `${C.brand}09`, abbrBg: C.brand },
  // Trading
  { abbr: 'HL', name: 'Hyperliquid DEX', desc: 'Perpetuals trading', tag: 'Trading', tagColor: C.bull, bg: `${C.bull}09`, abbrBg: C.bull },
  { abbr: 'CX', name: 'CCXT', desc: 'Exchange connectivity', tag: 'Trading', tagColor: C.bull, bg: `${C.bull}09`, abbrBg: C.bull },
  { abbr: 'PT', name: 'Paper Trading Mode', desc: 'Risk-free testing', tag: 'Trading', tagColor: C.bull, bg: `${C.bull}09`, abbrBg: C.bull },
  // Data
  { abbr: 'OC', name: 'OHLCV Pipeline', desc: 'Multi-timeframe data', tag: 'Data', tagColor: '#2563eb', bg: 'rgba(37,99,235,0.06)', abbrBg: '#2563eb' },
  { abbr: 'MC', name: 'Monte Carlo Zones', desc: 'Support/resistance', tag: 'Data', tagColor: '#2563eb', bg: 'rgba(37,99,235,0.06)', abbrBg: '#2563eb' },
  { abbr: 'EV', name: 'Ensemble Voting', desc: '4-strategy consensus', tag: 'Data', tagColor: '#2563eb', bg: 'rgba(37,99,235,0.06)', abbrBg: '#2563eb' },
];

function TechStackGrid() {
  return (
    <div style={{ marginBottom: 32 }}>
      <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>
        Powered By
      </div>
      <h2 style={{ margin: '0 0 8px', fontSize: F['2xl'], fontWeight: 800, color: C.text }}>The technology stack.</h2>
      <p style={{ margin: '0 0 24px', fontSize: F.sm, color: C.muted, lineHeight: 1.6 }}>
        Every layer purpose-built: AI agents for decisions, a DEX for execution, and a data pipeline that never sleeps.
      </p>
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 12,
      }}>
        {TECH_ITEMS.map((item) => (
          <div key={item.name} style={{
            background: item.bg,
            border: `1px solid ${item.tagColor}25`,
            borderRadius: R.lg,
            padding: '16px 18px',
            display: 'flex',
            flexDirection: 'column',
            gap: 10,
          }}>
            {/* Icon + Name row */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{
                flexShrink: 0,
                width: 36,
                height: 36,
                borderRadius: R.md,
                background: item.abbrBg,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: F.xs,
                fontWeight: 800,
                color: '#fff',
                letterSpacing: 0.5,
              }}>
                {item.abbr}
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, lineHeight: 1.3 }}>{item.name}</div>
                <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2, lineHeight: 1.4 }}>{item.desc}</div>
              </div>
            </div>
            {/* Tag */}
            <div style={{ alignSelf: 'flex-start' }}>
              <span style={{
                fontSize: 10,
                fontWeight: 700,
                color: item.tagColor,
                background: `${item.tagColor}18`,
                padding: '2px 8px',
                borderRadius: R.pill,
                letterSpacing: 0.5,
                textTransform: 'uppercase',
              }}>
                {item.tag}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Safety Stats ─────────────────────────────────────────────────────────────

type SafetyStat = { value: string; label: string; desc: string; color: string };

const SAFETY_STATS: SafetyStat[] = [
  { value: '6', label: 'Safety Gates', desc: 'Every signal passes 6 validation checks before execution', color: C.brand },
  { value: '$0', label: 'Real $ at Risk', desc: 'Paper trading mode — no real money involved', color: C.bull },
  { value: 'SL', label: 'Automatic Stop Loss', desc: 'Every trade has a defined stop loss', color: C.warn },
  { value: '⏸', label: 'Circuit Breakers', desc: 'Auto-halt after consecutive losses or daily drawdown', color: C.bear },
];

function SafetyStats() {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(4, 1fr)',
      gap: 1,
      background: C.border,
      borderRadius: R.lg,
      overflow: 'hidden',
      marginBottom: 32,
      border: `1px solid ${C.border}`,
    }}>
      {SAFETY_STATS.map((stat, i) => (
        <div key={stat.label} style={{
          ...Glass.card,
          padding: '22px 18px',
          textAlign: 'center',
          borderRight: i < SAFETY_STATS.length - 1 ? `1px solid ${C.border}` : undefined,
        }}>
          <div style={{
            fontSize: F['3xl'],
            fontWeight: 900,
            color: stat.color,
            lineHeight: 1.1,
            marginBottom: 6,
            letterSpacing: -0.5,
          }}>
            {stat.value}
          </div>
          <div style={{
            fontSize: F.sm,
            fontWeight: 700,
            color: C.text,
            marginBottom: 6,
            lineHeight: 1.3,
          }}>
            {stat.label}
          </div>
          <div style={{
            fontSize: F.xs,
            color: C.muted,
            lineHeight: 1.5,
          }}>
            {stat.desc}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Strategy Card ────────────────────────────────────────────────────────────

function StrategyCard({ name, desc, data, why }: { name: string; desc: string; data: string; why: string }) {
  return (
    <div className="glass-card card-hover glass-noise" style={{ ...Glass.card, borderRadius: R.lg, padding: '20px 22px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
        <span style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>{name}</span>
        <span style={{ fontSize: F.xs, padding: '2px 8px', borderRadius: R.pill, background: 'rgba(22,163,74,0.12)', color: C.bull, fontWeight: 700 }}>● LIVE</span>
      </div>
      <p style={{ margin: '0 0 10px', fontSize: F.sm, color: C.textSub, lineHeight: 1.6 }}>{desc}</p>
      <div style={{ fontSize: F.xs, color: C.muted, borderTop: `1px solid ${C.border}`, paddingTop: 10, marginTop: 10 }}>
        <div><strong style={{ color: C.textSub }}>Data:</strong> {data}</div>
        <div style={{ marginTop: 4 }}><strong style={{ color: C.textSub }}>Why it works:</strong> {why}</div>
      </div>
    </div>
  );
}

// ─── Gate Step ────────────────────────────────────────────────────────────────

function GateStep({ n, title, desc }: { n: number; title: string; desc: string }) {
  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
      <div style={{ flexShrink: 0, width: 28, height: 28, borderRadius: '50%', background: C.brand, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: F.xs, fontWeight: 800, color: '#fff' }}>{n}</div>
      <div>
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 2 }}>{title}</div>
        <div style={{ fontSize: F.xs, color: C.muted, lineHeight: 1.5 }}>{desc}</div>
      </div>
    </div>
  );
}

// ─── Transparency Score Card ──────────────────────────────────────────────────

function TransparencyScoreCard() {
  const dimensions = [
    { name: 'Audit Trail', blackBox: 5, wagmi: 100 },
    { name: 'AI Reasoning', blackBox: 0, wagmi: 95 },
    { name: 'Risk Transparency', blackBox: 20, wagmi: 90 },
    { name: 'Backtests Public', blackBox: 10, wagmi: 100 },
    { name: 'Entry Logic', blackBox: 0, wagmi: 85 },
  ];

  const BAR_MAX_W = 220;
  const ROW_H = 44;
  const LABEL_W = 130;
  const GAP = 6;
  const svgW = LABEL_W + BAR_MAX_W + 64; // label + bars + value labels
  const svgH = dimensions.length * (ROW_H + GAP) + 40; // rows + legend space

  return (
    <div className="glass-card card-hover glass-noise" style={{ ...Glass.card, borderRadius: R.lg, padding: '20px 22px', marginTop: 24 }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 4 }}>Transparency Comparison</div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 16 }}>How open are trading bots about their inner workings? Scored 0–100.</div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 20, marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 12, height: 12, borderRadius: 3, background: C.bear, opacity: 0.7 }} />
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 600 }}>Typical Bot</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{ width: 12, height: 12, borderRadius: 3, background: C.brand }} />
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 600 }}>WAGMI</span>
        </div>
      </div>

      {/* SVG bar chart */}
      <svg width="100%" viewBox={`0 0 ${svgW} ${svgH}`} style={{ display: 'block', overflow: 'visible' }}>
        {dimensions.map((dim, i) => {
          const y = i * (ROW_H + GAP);
          const bbW = (dim.blackBox / 100) * BAR_MAX_W;
          const wagmiW = (dim.wagmi / 100) * BAR_MAX_W;
          const barBg = 14; // individual bar height
          const gap2 = 4;   // gap between the two bars in a group

          return (
            <g key={dim.name}>
              {/* Dimension label */}
              <text
                x={LABEL_W - 8}
                y={y + barBg + (barBg + gap2) / 2}
                textAnchor="end"
                fontSize={10}
                fontWeight={600}
                fill={C.textSub}
              >
                {dim.name}
              </text>

              {/* Background tracks */}
              <rect x={LABEL_W} y={y} width={BAR_MAX_W} height={barBg} rx={4} fill={C.surface} />
              <rect x={LABEL_W} y={y + barBg + gap2} width={BAR_MAX_W} height={barBg} rx={4} fill={C.surface} />

              {/* Black Box bar (top) */}
              <rect
                x={LABEL_W}
                y={y}
                width={Math.max(bbW, dim.blackBox > 0 ? 3 : 0)}
                height={barBg}
                rx={4}
                fill={C.bear}
                opacity={0.7}
              />

              {/* WAGMI bar (bottom) */}
              <rect
                x={LABEL_W}
                y={y + barBg + gap2}
                width={wagmiW}
                height={barBg}
                rx={4}
                fill={C.brand}
              />

              {/* Value labels */}
              <text
                x={LABEL_W + BAR_MAX_W + 6}
                y={y + barBg - 2}
                fontSize={9}
                fill={C.muted}
                fontWeight={600}
              >
                {dim.blackBox}
              </text>
              <text
                x={LABEL_W + BAR_MAX_W + 6}
                y={y + barBg + gap2 + barBg - 2}
                fontSize={9}
                fill={C.brand}
                fontWeight={700}
              >
                {dim.wagmi}
              </text>
            </g>
          );
        })}

        {/* X-axis tick labels */}
        {[0, 25, 50, 75, 100].map((tick) => (
          <g key={tick}>
            <line
              x1={LABEL_W + (tick / 100) * BAR_MAX_W}
              y1={0}
              x2={LABEL_W + (tick / 100) * BAR_MAX_W}
              y2={dimensions.length * (ROW_H + GAP) - GAP}
              stroke={C.faint}
              strokeWidth={0.5}
              strokeDasharray="3 3"
            />
            <text
              x={LABEL_W + (tick / 100) * BAR_MAX_W}
              y={dimensions.length * (ROW_H + GAP) + 12}
              textAnchor="middle"
              fontSize={9}
              fill={C.muted}
            >
              {tick}
            </text>
          </g>
        ))}
      </svg>

      <div style={{ marginTop: 14, padding: '8px 12px', background: `${C.brand}10`, border: `1px solid ${C.brand}25`, borderRadius: R.sm, fontSize: F.xs, color: C.textSub }}>
        <strong style={{ color: C.brand }}>Transparency is the product.</strong> Every score above reflects what's actually inspectable at the linked pages — not marketing claims.
      </div>
    </div>
  );
}

// ─── Regime Transition Diagram ────────────────────────────────────────────────

function RegimeTransitionDiagram() {
  const W = 500;
  const H = 280;

  // Node positions (cx, cy)
  const nodes: Record<string, { cx: number; cy: number; label: string; color: string }> = {
    trend:   { cx: 250, cy: 44,  label: 'Trend',    color: C.bull  },
    range:   { cx: 250, cy: 150, label: 'Range',    color: C.info  },
    highvol: { cx: 400, cy: 100, label: 'High Vol', color: C.warn  },
    panic:   { cx: 390, cy: 220, label: 'Panic',    color: C.bear  },
    lowliq:  { cx: 90,  cy: 185, label: 'Low Liq',  color: C.muted },
  };

  const R_NODE = 32;

  // Arrow thickness: 2px at 15%, 5px at 60% — linear interpolation
  function strokeW(pct: number): number {
    return 2 + ((pct - 15) / (60 - 15)) * 3;
  }

  // Given two circles, compute the point on the circumference of the source
  // facing the target, and vice versa (so arrows don't overlap the circles).
  function edgePoints(
    ax: number, ay: number,
    bx: number, by: number,
  ): { x1: number; y1: number; x2: number; y2: number } {
    const dx = bx - ax;
    const dy = by - ay;
    const len = Math.sqrt(dx * dx + dy * dy);
    const ux = dx / len;
    const uy = dy / len;
    return {
      x1: ax + ux * R_NODE,
      y1: ay + uy * R_NODE,
      x2: bx - ux * (R_NODE + 6), // 6px gap for arrowhead
      y2: by - uy * (R_NODE + 6),
    };
  }

  // Midpoint for label placement, optionally offset perpendicular
  function midpoint(
    x1: number, y1: number,
    x2: number, y2: number,
    perpOffset = 0,
  ): { x: number; y: number } {
    const mx = (x1 + x2) / 2;
    const my = (y1 + y2) / 2;
    if (perpOffset === 0) return { x: mx, y: my };
    const dx = x2 - x1;
    const dy = y2 - y1;
    const len = Math.sqrt(dx * dx + dy * dy);
    return { x: mx + (-dy / len) * perpOffset, y: my + (dx / len) * perpOffset };
  }

  // Edges: [from, to, pct, perpLabelOffset]
  const edges: [string, string, number, number][] = [
    ['trend',   'range',   45,  10],
    ['trend',   'highvol', 30,  -8],
    ['range',   'trend',   35,  -10],
    ['range',   'highvol', 25,  8],
    ['range',   'lowliq',  15,  8],
    ['highvol', 'panic',   40,  8],
    ['highvol', 'range',   35,  -8],
    ['panic',   'lowliq',  50,  -8],
    ['panic',   'range',   30,  8],
    ['lowliq',  'range',   60,  8],
  ];

  // Unique marker id per source color (to color arrowheads per source)
  const markerColors: Record<string, string> = {
    trend:   C.bull,
    range:   C.info,
    highvol: C.warn,
    panic:   C.bear,
    lowliq:  C.muted,
  };

  return (
    <div className="glass-card card-hover glass-noise" style={{ ...Glass.card, borderRadius: R.lg, padding: '20px 22px', marginTop: 24 }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 4 }}>
        Regime Transition Map — How Markets Evolve
      </div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 16 }}>
        Arrow thickness proportional to transition probability. Range is the most common steady-state regime.
      </div>

      {/* SVG diagram */}
      <div style={{ overflowX: 'auto' }}>
        <svg
          width={W}
          height={H}
          viewBox={`0 0 ${W} ${H}`}
          style={{ display: 'block', maxWidth: '100%' }}
        >
          <defs>
            {/* One arrowhead marker per source node color */}
            {Object.entries(markerColors).map(([key, color]) => (
              <marker
                key={key}
                id={`arrow-${key}`}
                markerWidth="7"
                markerHeight="7"
                refX="6"
                refY="3.5"
                orient="auto"
              >
                <polygon points="0 0, 7 3.5, 0 7" fill={color} opacity="0.85" />
              </marker>
            ))}
          </defs>

          {/* ── Edges ── */}
          {edges.map(([from, to, pct, perpOffset]) => {
            const a = nodes[from];
            const b = nodes[to];
            const { x1, y1, x2, y2 } = edgePoints(a.cx, a.cy, b.cx, b.cy);
            const mid = midpoint(x1, y1, x2, y2, perpOffset);
            const sw = strokeW(pct);
            const srcColor = markerColors[from];
            return (
              <g key={`${from}-${to}`}>
                <line
                  x1={x1} y1={y1}
                  x2={x2} y2={y2}
                  stroke={srcColor}
                  strokeWidth={sw}
                  strokeOpacity={0.75}
                  markerEnd={`url(#arrow-${from})`}
                />
                <text
                  x={mid.x}
                  y={mid.y}
                  textAnchor="middle"
                  dominantBaseline="middle"
                  fontSize={9}
                  fontWeight={700}
                  fill={srcColor}
                  opacity={0.9}
                  style={{ pointerEvents: 'none' }}
                >
                  {pct}%
                </text>
              </g>
            );
          })}

          {/* ── Self-loop on Range (most common steady state) ── */}
          {(() => {
            const { cx, cy } = nodes.range;
            const loopR = 18;
            // Small arc loop above-left of the Range node
            const lx = cx - R_NODE - 4;
            const ly = cy - R_NODE - 4;
            return (
              <g>
                <circle
                  cx={lx}
                  cy={ly}
                  r={loopR}
                  fill="none"
                  stroke={C.info}
                  strokeWidth={1.5}
                  strokeOpacity={0.6}
                  strokeDasharray="4 2"
                  markerEnd="url(#arrow-range)"
                />
                <text
                  x={lx - loopR - 2}
                  y={ly - loopR + 2}
                  fontSize={8}
                  fill={C.info}
                  fontWeight={700}
                  opacity={0.8}
                  textAnchor="end"
                >
                  steady
                </text>
              </g>
            );
          })()}

          {/* ── Nodes ── */}
          {Object.entries(nodes).map(([key, { cx, cy, label, color }]) => (
            <g key={key}>
              {/* Shadow ring */}
              <circle cx={cx} cy={cy} r={R_NODE + 3} fill={color} opacity={0.12} />
              {/* Main circle */}
              <circle cx={cx} cy={cy} r={R_NODE} fill={color} opacity={0.18} stroke={color} strokeWidth={2} />
              {/* Label */}
              <text
                x={cx}
                y={cy}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize={10}
                fontWeight={800}
                fill={color}
                style={{ pointerEvents: 'none' }}
              >
                {label}
              </text>
            </g>
          ))}
        </svg>
      </div>

      {/* ── Legend ── */}
      <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginTop: 16, paddingTop: 14, borderTop: `1px solid ${C.border}` }}>
        {Object.entries(nodes).map(([key, { label, color }]) => (
          <div key={key} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5 }}>
            <div style={{
              width: 20,
              height: 20,
              borderRadius: '50%',
              background: color,
              opacity: 0.85,
            }} />
            <span style={{ fontSize: 9, color: C.muted, fontWeight: 600 }}>{label}</span>
          </div>
        ))}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <div style={{ width: 28, height: 2, background: C.muted, borderRadius: 1 }} />
            <div style={{ width: 28, height: 5, background: C.muted, borderRadius: 1 }} />
          </div>
          <span style={{ fontSize: 9, color: C.muted, fontWeight: 600 }}>Arrow width = probability</span>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function AboutPage() {
  return (
    <>
      <Head>
        <title>About WAGMI — How It Works</title>
        <meta name="description" content="WAGMI doesn't have a black box. It has an audit trail. Learn about the 4 strategies, 7 AI agents, and the risk management system that protects your capital." />
      </Head>

      <div className="bg-aurora" style={{ maxWidth: 860, margin: '0 auto', padding: '32px 20px', position: 'relative' }}>
        <div className="floating-orb orb-brand" style={{ position: 'fixed', top: '10%', right: '15%' }} />
        <div className="floating-orb orb-purple" style={{ position: 'fixed', bottom: '20%', left: '10%' }} />

        {/* ── Hero ── */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <h1 style={{ margin: '0 0 14px', fontSize: F['3xl'], fontWeight: 900, color: C.text, letterSpacing: -0.5, lineHeight: 1.15 }}>
            Built in public.<br /><span className="gradient-text">Every trade logged.</span><br />Every decision explained.
          </h1>
          <p style={{ margin: 0, fontSize: F.lg, color: C.muted, maxWidth: 520, marginLeft: 'auto', marginRight: 'auto', lineHeight: 1.6 }}>
            WAGMI doesn't have a black box. It has an audit trail.
          </p>
        </div>

        {/* ── Stats Hero Bar ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 32 }}>
          {[
            { value: '$0.0067', label: 'per decision', color: C.brand },
            { value: '⚖️', label: 'AI veto power', color: C.bear },
            { value: '7', label: 'AI agents', color: C.brand },
            { value: '6', label: 'risk gates', color: C.bull },
          ].map(({ value, label, color }) => (
            <div key={label} className="glass-card card-hover glass-noise" style={{
              ...Glass.card,
              border: `1px solid ${color}30`,
              borderRadius: R.lg,
              padding: '20px 16px',
              textAlign: 'center',
              boxShadow: `0 0 0 0 transparent`,
            }}>
              <div style={{ fontSize: F['3xl'], fontWeight: 900, color, lineHeight: 1.1, marginBottom: 6 }}>{value}</div>
              <div style={{ fontSize: F.xs, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, fontWeight: 600 }}>{label}</div>
            </div>
          ))}
        </div>

        {/* ── In-page nav ── */}
        <nav style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap', marginBottom: 32 }}>
          {[
            { href: '#strategies', label: 'Strategies' },
            { href: '#agents',     label: 'AI Agents' },
            { href: '#risk',       label: 'Risk Management' },
            { href: '#contact',    label: 'Get Started' },
          ].map(({ href, label }) => (
            <a key={href} href={href} style={{ padding: '6px 16px', borderRadius: R.pill, border: `1px solid ${C.border}`, fontSize: F.xs, fontWeight: 600, color: C.textSub, textDecoration: 'none', background: G.card }}>
              {label}
            </a>
          ))}
        </nav>

        {/* ── Tech Stack Grid ── */}
        <TechStackGrid />

        {/* ── Problem ── */}
        <Section eyebrow="Why We Built This" title="Most trading bots are black boxes.">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            <div style={{ background: 'rgba(220,38,38,0.06)', border: `1px solid ${C.bear}30`, borderRadius: R.lg, padding: '20px 22px' }}>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: C.bear, marginBottom: 12 }}>✗ How most bots work</div>
              {['Signal appears. No explanation.', 'Algorithm fires. You don\'t know why.', 'Trade loses. Zero insight.', 'Risk management? A black-box number.', 'You trust blindly — or you don\'t.'].map((t) => (
                <div key={t} style={{ fontSize: F.sm, color: C.muted, marginBottom: 6, display: 'flex', gap: 8 }}>
                  <span style={{ color: C.bear }}>×</span> {t}
                </div>
              ))}
            </div>
            <div style={{ background: 'rgba(22,163,74,0.06)', border: `1px solid ${C.bull}30`, borderRadius: R.lg, padding: '20px 22px' }}>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: C.bull, marginBottom: 12 }}>✓ How WAGMI works</div>
              {['Every signal logged with full reasoning.', 'Every AI decision auditable at /ai-decisions.', 'Every loss analysed and explained.', 'Risk gates are documented and inspectable.', 'Transparency is the product.'].map((t) => (
                <div key={t} style={{ fontSize: F.sm, color: C.textSub, marginBottom: 6, display: 'flex', gap: 8 }}>
                  <span style={{ color: C.bull }}>✓</span> {t}
                </div>
              ))}
            </div>
          </div>
          <TransparencyScoreCard />
        </Section>

        {/* ── Strategies ── */}
        <Section id="strategies" eyebrow="The Signal Engine" title="4 strategies vote on every trade.">
          <p style={{ margin: '0 0 20px', color: C.muted, fontSize: F.sm, lineHeight: 1.7 }}>
            No single strategy trades alone. All four must vote, and a confidence threshold must be reached before any order is placed. Disagreement = skip.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: 14 }}>
            <StrategyCard name="Regime Trend" desc="Follows established trends on 1h and 6h timeframes, using multiple moving averages and momentum indicators." data="1h, 6h candles via Hyperliquid" why="Trend continuation is the highest-probability setup when regime is confirmed." />
            <StrategyCard name="Monte Carlo Zones" desc="Uses Monte Carlo simulation to build support and resistance zones from daily price action. Defines accumulation and distribution regions." data="Daily candles" why="Probabilistic zones outperform static % levels because they adapt to each asset's actual volatility." />
            <StrategyCard name="Confidence Scorer" desc="Multi-factor scoring system: RSI, VWAP, ATR, trend alignment, volume confirmation. Outputs a 0–100 score." data="Multiple timeframes" why="Aggregating weak signals into a composite score reduces false positives vs any single indicator." />
            <StrategyCard name="Multi-Tier Quality" desc="Checks signal quality across short (5m) and medium (1h) timeframes. Filters out setups that lack multi-timeframe alignment." data="5m, 1h candles" why="A signal that looks good on 1h but bad on 5m is often entering at a local peak. MTF filters this." />
          </div>
          <RegimeTransitionDiagram />
        </Section>

        {/* ── Agents ── */}
        <Section id="agents" eyebrow="The AI Brain" title="7 agents debate every trade.">
          <p style={{ margin: '0 0 24px', color: C.muted, fontSize: F.sm, lineHeight: 1.7 }}>
            Each agent has a specific role and is prevented from stepping outside it. The Critic must provide a counter-thesis before vetoing — vague objections are not allowed.
          </p>
          {/* ── Pipeline Diagram ── */}
          <div style={{ overflowX: 'auto', marginBottom: 28 }}>
            {/* Pre-Trade Pipeline */}
            <div style={{ marginBottom: 6 }}>
              <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>Pre-Trade Pipeline</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 0, minWidth: 720 }}>
                {/* Signal source */}
                <div style={{
                  flexShrink: 0,
                  background: C.surface,
                  border: `1px solid ${C.border}`,
                  borderRadius: R.md,
                  padding: '10px 14px',
                  textAlign: 'center',
                  minWidth: 72,
                }}>
                  <div style={{ fontSize: 16, marginBottom: 2 }}>📊</div>
                  <div style={{ fontSize: F.xs, fontWeight: 700, color: C.textSub }}>Signal</div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>4 strategies</div>
                </div>

                {/* Arrow */}
                <div style={{ flex: '0 0 20px', textAlign: 'center', color: C.muted, fontSize: F.base }}>→</div>

                {/* Regime */}
                <div style={{
                  flexShrink: 0,
                  background: `linear-gradient(135deg, ${C.info}22, ${C.info}10)`,
                  border: `1px solid ${C.info}40`,
                  borderRadius: R.md,
                  padding: '10px 14px',
                  textAlign: 'center',
                  minWidth: 84,
                }}>
                  <div style={{ fontSize: 16, marginBottom: 2 }}>🌐</div>
                  <div style={{ fontSize: F.xs, fontWeight: 700, color: C.info }}>Regime</div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>Haiku</div>
                </div>

                {/* Arrow */}
                <div style={{ flex: '0 0 20px', textAlign: 'center', color: C.muted, fontSize: F.base }}>→</div>

                {/* Trade */}
                <div style={{
                  flexShrink: 0,
                  background: `linear-gradient(135deg, ${C.brand}22, ${C.brand}10)`,
                  border: `1px solid ${C.brand}40`,
                  borderRadius: R.md,
                  padding: '10px 14px',
                  textAlign: 'center',
                  minWidth: 84,
                }}>
                  <div style={{ fontSize: 16, marginBottom: 2 }}>🧠</div>
                  <div style={{ fontSize: F.xs, fontWeight: 700, color: C.brand }}>Trade</div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>Sonnet</div>
                </div>

                {/* Arrow */}
                <div style={{ flex: '0 0 20px', textAlign: 'center', color: C.muted, fontSize: F.base }}>→</div>

                {/* Risk */}
                <div style={{
                  flexShrink: 0,
                  background: `linear-gradient(135deg, ${C.warn}22, ${C.warn}10)`,
                  border: `1px solid ${C.warn}40`,
                  borderRadius: R.md,
                  padding: '10px 14px',
                  textAlign: 'center',
                  minWidth: 84,
                }}>
                  <div style={{ fontSize: 16, marginBottom: 2 }}>🛡️</div>
                  <div style={{ fontSize: F.xs, fontWeight: 700, color: C.warn }}>Risk</div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>Haiku</div>
                </div>

                {/* Arrow */}
                <div style={{ flex: '0 0 20px', textAlign: 'center', color: C.muted, fontSize: F.base }}>→</div>

                {/* Critic */}
                <div style={{
                  flexShrink: 0,
                  background: `linear-gradient(135deg, ${C.purple}22, ${C.purple}10)`,
                  border: `1px solid ${C.purple}40`,
                  borderRadius: R.md,
                  padding: '10px 14px',
                  textAlign: 'center',
                  minWidth: 84,
                }}>
                  <div style={{ fontSize: 16, marginBottom: 2 }}>⚖️</div>
                  <div style={{ fontSize: F.xs, fontWeight: 700, color: C.purple }}>Critic</div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>Sonnet</div>
                </div>

                {/* Arrow */}
                <div style={{ flex: '0 0 20px', textAlign: 'center', color: C.muted, fontSize: F.base }}>→</div>

                {/* Fork: Execute or Veto */}
                <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{
                    background: `linear-gradient(135deg, ${C.bull}25, ${C.bull}10)`,
                    border: `1px solid ${C.bull}50`,
                    borderRadius: R.md,
                    padding: '8px 12px',
                    textAlign: 'center',
                    minWidth: 90,
                  }}>
                    <div style={{ fontSize: F.xs, fontWeight: 800, color: C.bull }}>✓ EXECUTE</div>
                  </div>
                  <div style={{
                    background: `linear-gradient(135deg, ${C.bear}22, ${C.bear}10)`,
                    border: `1px solid ${C.bear}50`,
                    borderRadius: R.md,
                    padding: '8px 12px',
                    textAlign: 'center',
                    minWidth: 90,
                  }}>
                    <div style={{ fontSize: F.xs, fontWeight: 800, color: C.bear }}>✗ VETO</div>
                  </div>
                </div>
              </div>
            </div>

            {/* Ongoing Agents */}
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>Ongoing Agents</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 720 }}>
                {[
                  { emoji: '📚', name: 'Learning', sub: 'post-trade', color: C.bull },
                  { emoji: '👁️', name: 'Exit', sub: 'monitors positions', color: C.warnMid },
                  { emoji: '🔭', name: 'Scout', sub: 'idle preparation', color: C.muted },
                ].map(({ emoji, name, sub, color }) => (
                  <div key={name} style={{
                    background: `linear-gradient(135deg, ${color}15, ${color}08)`,
                    border: `1px dashed ${color}50`,
                    borderRadius: R.md,
                    padding: '10px 16px',
                    textAlign: 'center',
                    minWidth: 110,
                  }}>
                    <div style={{ fontSize: 16, marginBottom: 2 }}>{emoji}</div>
                    <div style={{ fontSize: F.xs, fontWeight: 700, color }}>{name}</div>
                    <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>{sub}</div>
                  </div>
                ))}
                <div style={{ fontSize: F.xs, color: C.faint, fontStyle: 'italic', paddingLeft: 4 }}>run async — not on critical path</div>
              </div>
            </div>
          </div>

          {/* ── Safety Stats Strip ── */}
          <SafetyStats />

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {AGENTS.map((a) => (
              <div key={a.name} className="glass-card card-hover glass-noise" style={{ ...Glass.card, border: `1px solid ${a.color}30`, borderRadius: R.lg, padding: '16px 20px', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                <div style={{ flexShrink: 0, minWidth: 160 }}>
                  <div style={{ fontSize: F.sm, fontWeight: 800, color: a.color }}>{a.name}</div>
                  <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>Model: {a.model}</div>
                  <div style={{ fontSize: F.xs, color: C.faint, marginTop: 1 }}>{a.cost}</div>
                </div>
                <div style={{ flex: 1, minWidth: 200 }}>
                  <div style={{ fontSize: F.sm, color: C.textSub, marginBottom: 4 }}>{a.role}</div>
                  <div style={{ fontSize: F.xs, color: C.muted, lineHeight: 1.5 }}><strong style={{ color: C.textSub }}>Decides:</strong> {a.decides}</div>
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 16, padding: '12px 16px', background: `${C.purple}10`, border: `1px solid ${C.purple}30`, borderRadius: R.md, fontSize: F.sm, color: C.textSub }}>
            Total cost per entry decision: ~$0.0067. The Critic agent actively vetoes marginal setups — those that lack a strong, defensible thesis don't reach the exchange. That's the system working.
          </div>
          <div style={{ marginTop: 12 }}>
            <Link href="/llm-audit" style={{ fontSize: F.sm, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>See every AI decision logged →</Link>
          </div>
        </Section>

        {/* ── Risk Management ── */}
        <Section id="risk" eyebrow="Risk Management" title="The bot can stop itself.">
          <p style={{ margin: '0 0 20px', color: C.muted, fontSize: F.sm, lineHeight: 1.7 }}>
            Every trade passes through 6 sequential gates. A signal must pass all 6 to become an order. The gates are hard-coded — they cannot be disabled from the UI.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginBottom: 24 }}>
            <GateStep n={1} title="Signal Validity" desc="Is the signal well-formed? Valid SL/TP, stop width ≥ 0.3% of entry, R:R ≥ 1.0. Nonsensical trades rejected here." />
            <GateStep n={2} title="Circuit Breaker" desc="Has the bot lost more than X% today, or had N consecutive losses? If yes, trading pauses until the next session." />
            <GateStep n={3} title="Position Limits" desc="Maximum simultaneous positions enforced. Prevents over-exposure to correlated assets." />
            <GateStep n={4} title="Leverage Check" desc="Leverage is capped based on confidence score, strategy agreement, and market regime. High volatility = lower cap." />
            <GateStep n={5} title="Liquidation Safety" desc="The liquidation price must be below the stop loss level (for longs) by a safe margin. Near-liquidation trades are rejected." />
            <GateStep n={6} title="Position Sizing" desc="Final size = 1.5% of current equity ÷ stop distance. Never more than 1.5% of capital at risk on any single trade." />
          </div>
          <GateFunnelChart />
          <div style={{ background: `${C.bull}08`, border: `1px solid ${C.bull}25`, borderRadius: R.lg, padding: '14px 18px', fontSize: F.sm, color: C.textSub, marginTop: 20 }}>
            <strong style={{ color: C.bull }}>The result:</strong> Even in the worst realistic scenario — all open positions hit their stops simultaneously — you lose at most 4.5% of capital in one session. The daily loss circuit breaker triggers long before that.
          </div>
        </Section>

        {/* ── Transparency Commitments ── */}
        <Section eyebrow="Our Commitments" title="What we promise.">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[
              { n: '1', text: 'Every closed trade is logged and public at /forensics — including losses.', href: '/forensics' },
              { n: '2', text: 'Every AI decision is auditable at /llm-audit — model, reasoning, veto history.', href: '/llm-audit' },
              { n: '3', text: 'Drawdown is reported in real-time at /performance — no cherry-picking periods.', href: '/performance' },
              { n: '4', text: 'No cherry-picked results — all trades included. All losses shown. One ledger.', href: null },
              { n: '5', text: 'Model costs are disclosed — we\'re not hiding that we use Claude to think.', href: null },
            ].map(({ n, text, href }) => (
              <div key={n} className="glass-card card-hover glass-noise" style={{ display: 'flex', gap: 14, padding: '12px 16px', ...Glass.card, borderRadius: R.md, border: `1px solid ${C.border}`, alignItems: 'flex-start' }}>
                <span style={{ flexShrink: 0, width: 24, height: 24, borderRadius: '50%', background: C.bull + '20', color: C.bull, fontWeight: 800, fontSize: F.xs, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{n}</span>
                <span style={{ fontSize: F.sm, color: C.textSub, lineHeight: 1.5 }}>
                  {text} {href && <Link href={href} style={{ color: C.brand, fontWeight: 600, textDecoration: 'none' }}>View →</Link>}
                </span>
              </div>
            ))}
          </div>
        </Section>

        {/* ── FAQ ── */}
        <Section eyebrow="FAQ" title="Honest answers.">
          <FAQ q="Is this financial advice?" a="No. WAGMI is a market analysis tool. Every signal is for informational purposes only. You are responsible for all trading decisions." />
          <FAQ q="What happens if the bot loses money?" a={<>Circuit breakers activate automatically. A daily loss cap stops trading for the session. After N consecutive losses, the bot pauses until conditions improve. These limits are hard-coded and visible in <Link href="/learn" style={{ color: C.brand }}>the course</Link>.</>} />
          <FAQ q="Can I lose more than I put in?" a="On Hyperliquid, your loss is capped at your margin. The bot's liquidation gate (Gate 5) ensures the stop loss is always triggered before liquidation, so you exit at your stop, not at liquidation price." />
          <FAQ q="How do I know the results are real?" a={<>Every trade is timestamped and logged at <Link href="/forensics" style={{ color: C.brand }}>/forensics</Link>. Entry, exit, time, P&L — all there. We include the losers.</>} />
          <FAQ q="What's the difference between paper and live trading?" a="Paper trading executes at market prices on Hyperliquid testnet infrastructure — the signals are identical to live. Real money has not been deployed yet. When we go live, you'll see it." />
          <FAQ q="Which exchange does this run on?" a="Hyperliquid. We chose it for its deep liquidity on perps, zero maker fees, and on-chain settlement. The API is fast enough for scalp-level execution." />
          <FAQ q="Why Claude (Anthropic) and not GPT-4?" a="Claude's longer context window and lower hallucination rate on structured tasks made it the right fit. We tested both extensively. Claude also has strong JSON mode compliance which matters for the agent pipeline." />
          <FAQ q="How much does it cost to run this per month?" a="LLM costs run approximately $0.007 per full trade decision cycle. For a bot analyzing 50 signals per day, that's ~$10/month in AI costs. This is disclosed at /llm-audit." />
          <FAQ q="How do I start?" a={<>Start at <Link href="/copy-trade" style={{ color: C.brand }}>Trade This</Link> to see live signals, or <Link href="/learn" style={{ color: C.brand }}>Understand the Edge</Link> to learn the system first.</>} />
        </Section>

        {/* ── CTA ── */}
        <div style={{ textAlign: 'center', padding: '24px 0 8px' }}>
          <h2 style={{ margin: '0 0 12px', fontSize: F['2xl'], fontWeight: 800, color: C.text }}>Ready to see it in action?</h2>
          <p style={{ margin: '0 0 24px', color: C.muted, fontSize: F.sm }}>Every claim on this page is auditable. Start with the track record.</p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
            <Link href="/forensics" style={{ padding: '10px 22px', background: C.brand, color: '#fff', borderRadius: R.md, fontSize: F.sm, fontWeight: 700, textDecoration: 'none' }}>
              See Every Trade →
            </Link>
            <Link href="/llm-audit" style={{ padding: '10px 22px', border: `1px solid ${C.border}`, color: C.textSub, borderRadius: R.md, fontSize: F.sm, fontWeight: 600, textDecoration: 'none' }}>
              Audit the AI →
            </Link>
          </div>
        </div>

        {/* ── Contact / Get Started ── */}
        <div id="contact" style={{ marginTop: 32, padding: '32px 28px', background: `linear-gradient(135deg, ${C.brand}12, ${C.surface})`, border: `1px solid ${C.brand}30`, borderRadius: R.xl, textAlign: 'center', scrollMarginTop: 80 }}>
          <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>Get Started</div>
          <h2 style={{ margin: '0 0 12px', fontSize: F['2xl'], fontWeight: 800, color: C.text }}>Start free. No credit card required.</h2>
          <p style={{ margin: '0 0 24px', fontSize: F.sm, color: C.muted, maxWidth: 440, marginLeft: 'auto', marginRight: 'auto', lineHeight: 1.6 }}>
            Observer tier is free forever. Copy-trade access is open to all. Questions? Reach us in the Discord community.
          </p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
            <Link href="/copy-trade" style={{ padding: '11px 26px', background: C.brand, color: '#fff', borderRadius: R.md, fontSize: F.sm, fontWeight: 700, textDecoration: 'none', boxShadow: S.glow }}>
              Start Copy Trading →
            </Link>
            <Link href="/pricing" style={{ padding: '11px 26px', border: `1px solid ${C.border}`, color: C.textSub, borderRadius: R.md, fontSize: F.sm, fontWeight: 600, textDecoration: 'none' }}>
              View Pricing →
            </Link>
          </div>
        </div>
      </div>
    </>
  );
}
