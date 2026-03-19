import React, { useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import Layout from '../components/Layout';
import { C, R, S, F, G, fmtUsd } from '../src/theme';

// ─── Tier Config ──────────────────────────────────────────────────────────────

type Tier = {
  name: string;
  monthly: number | null;
  annual: number | null;
  tagline: string;
  features: { label: string; included: boolean; note?: string }[];
  cta: string;
  ctaHref: string;
  highlighted: boolean;
  badge?: string;
};

const TIERS: Tier[] = [
  {
    name: 'Observer',
    monthly: 0,
    annual: 0,
    tagline: 'See how the bot thinks. No commitment.',
    features: [
      { label: 'Live signals (delayed 15 min)', included: true },
      { label: 'Public AI audit trail', included: true, note: 'Every decision, logged' },
      { label: 'Analytics dashboard', included: true },
      { label: 'Performance track record', included: true },
      { label: 'Learning course (Sections 1–3)', included: true },
      { label: 'Real-time signals', included: false },
      { label: 'Telegram alerts', included: false },
      { label: 'Morning brief', included: false },
      { label: 'Full course access', included: false },
      { label: 'Auto-execution', included: false },
    ],
    cta: 'Get Started Free',
    ctaHref: '/',
    highlighted: false,
  },
  {
    name: 'Pro',
    monthly: 29,
    annual: 232,
    tagline: 'Everything you need to follow the bot profitably.',
    badge: 'Most Popular',
    features: [
      { label: 'Real-time signals (no delay)', included: true },
      { label: 'Full AI audit trail', included: true },
      { label: 'Analytics dashboard', included: true },
      { label: 'Telegram alerts — instant', included: true, note: 'Signal, TP hit, close' },
      { label: 'Daily morning brief', included: true },
      { label: 'Full course (all 8 sections)', included: true },
      { label: 'Risk calculator + tools', included: true },
      { label: 'Discord community access', included: true },
      { label: 'Copy-trade setup guide', included: true },
      { label: 'Auto-execution', included: false },
    ],
    cta: 'Start 7-Day Free Trial',
    ctaHref: '/copy-trade',
    highlighted: true,
  },
  {
    name: 'Elite',
    monthly: 97,
    annual: 776,
    tagline: 'Automated execution with custom risk parameters.',
    features: [
      { label: 'Everything in Pro', included: true },
      { label: 'Auto-execution on Hyperliquid', included: true, note: 'API key required' },
      { label: 'Custom risk parameters', included: true, note: 'Your sizing, your limits' },
      { label: 'Multi-symbol expansion', included: true, note: 'Beyond BTC/SOL/HYPE' },
      { label: 'API access', included: true },
      { label: 'Priority support', included: true },
      { label: 'Dedicated onboarding call', included: true },
      { label: 'Custom alert thresholds', included: true },
      { label: 'Performance reporting', included: true },
      { label: 'Early access to new agents', included: true },
    ],
    cta: 'Talk to Us',
    ctaHref: '/copy-trade',
    highlighted: false,
  },
];

// ─── RoiTimelineChart ─────────────────────────────────────────────────────────

function RoiTimelineChart() {
  const W = 600;
  const H = 160;
  const padL = 52;
  const padR = 12;
  const padT = 12;
  const padB = 30;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;

  // 12 data points: months 0–11
  const months = Array.from({ length: 12 }, (_, i) => i);

  const observerRate = 0;
  const proRate = 0.015;
  const eliteRate = 0.022;
  const start = 10000;

  const observerData = months.map((m) => start * Math.pow(1 + observerRate, m));
  const proData = months.map((m) => start * Math.pow(1 + proRate, m));
  const eliteData = months.map((m) => start * Math.pow(1 + eliteRate, m));

  const yMin = 9800;
  const yMax = 13200;

  const xScale = (m: number) => padL + (m / 11) * chartW;
  const yScale = (v: number) => padT + chartH - ((v - yMin) / (yMax - yMin)) * chartH;

  const pointsToPath = (data: number[]) =>
    data.map((v, i) => `${i === 0 ? 'M' : 'L'}${xScale(i).toFixed(1)},${yScale(v).toFixed(1)}`).join(' ');

  const pointsToArea = (data: number[]) => {
    const line = pointsToPath(data);
    const bottomRight = `L${xScale(11).toFixed(1)},${(padT + chartH).toFixed(1)}`;
    const bottomLeft = `L${xScale(0).toFixed(1)},${(padT + chartH).toFixed(1)}`;
    return `${line} ${bottomRight} ${bottomLeft} Z`;
  };

  // Y-axis ticks: 10k, 11k, 12k, 13k
  const yTicks = [10000, 11000, 12000, 13000];

  const fmtK = (v: number) => `$${(v / 1000).toFixed(0)}k`;

  const observerFinal = observerData[11].toFixed(0);
  const proFinal = proData[11].toFixed(0);
  const eliteFinal = eliteData[11].toFixed(0);

  return (
    <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '24px 24px 16px', marginBottom: 0 }}>
      <div style={{ marginBottom: 14, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 2 }}>Projected equity growth</div>
          <div style={{ fontSize: F.xs, color: C.muted }}>Starting capital $10,000 · 12 months</div>
        </div>
        {/* Legend */}
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          {[
            { label: 'Observer', color: C.muted, dash: true, final: `$${Number(observerFinal).toLocaleString()}` },
            { label: 'Pro', color: C.brand, dash: false, final: `$${Number(proFinal).toLocaleString()}` },
            { label: 'Elite', color: C.bull, dash: false, final: `$${Number(eliteFinal).toLocaleString()}` },
          ].map((item) => (
            <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <svg width={20} height={10}>
                <line
                  x1={0} y1={5} x2={20} y2={5}
                  stroke={item.color} strokeWidth={2}
                  strokeDasharray={item.dash ? '4 3' : undefined}
                />
              </svg>
              <span style={{ fontSize: F.xs, color: C.textSub, fontWeight: 600 }}>{item.label}</span>
              <span style={{ fontSize: F.xs, color: item.color, fontWeight: 700 }}>{item.final}</span>
            </div>
          ))}
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto', display: 'block' }}>
        <defs>
          <linearGradient id="gradObs" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.muted} stopOpacity={0.08} />
            <stop offset="100%" stopColor={C.muted} stopOpacity={0} />
          </linearGradient>
          <linearGradient id="gradPro" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.brand} stopOpacity={0.08} />
            <stop offset="100%" stopColor={C.brand} stopOpacity={0} />
          </linearGradient>
          <linearGradient id="gradElite" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.bull} stopOpacity={0.08} />
            <stop offset="100%" stopColor={C.bull} stopOpacity={0} />
          </linearGradient>
        </defs>

        {/* Y-axis grid lines and labels */}
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              x1={padL} y1={yScale(tick)}
              x2={W - padR} y2={yScale(tick)}
              stroke={C.border} strokeWidth={1}
            />
            <text
              x={padL - 6} y={yScale(tick) + 4}
              textAnchor="end"
              fontSize={9}
              fill={C.muted}
            >{fmtK(tick)}</text>
          </g>
        ))}

        {/* Area fills */}
        <path d={pointsToArea(observerData)} fill="url(#gradObs)" />
        <path d={pointsToArea(proData)} fill="url(#gradPro)" />
        <path d={pointsToArea(eliteData)} fill="url(#gradElite)" />

        {/* Lines */}
        <path d={pointsToPath(observerData)} fill="none" stroke={C.muted} strokeWidth={1.5} strokeDasharray="5 4" />
        <path d={pointsToPath(proData)} fill="none" stroke={C.brand} strokeWidth={2} />
        <path d={pointsToPath(eliteData)} fill="none" stroke={C.bull} strokeWidth={2} />

        {/* X-axis labels */}
        {months.map((m) => (
          <text
            key={m}
            x={xScale(m)}
            y={padT + chartH + 18}
            textAnchor="middle"
            fontSize={9}
            fill={C.muted}
          >{`M${m + 1}`}</text>
        ))}
      </svg>

      <div style={{ fontSize: 10, color: C.faint, marginTop: 8, textAlign: 'center', lineHeight: 1.5 }}>
        Illustrative only. Based on 30-day backtest rate of 11.34% projected forward. Past performance ≠ future results.
      </div>
    </div>
  );
}

// ─── TierValueBars ─────────────────────────────────────────────────────────────

const TIER_VALUE_DIMS = [
  { label: 'Signal Speed',  observer: 40,  pro: 100, elite: 100 },
  { label: 'Alerts',        observer: 0,   pro: 80,  elite: 100 },
  { label: 'Learning',      observer: 30,  pro: 100, elite: 100 },
  { label: 'Automation',    observer: 0,   pro: 0,   elite: 100 },
  { label: 'Support',       observer: 10,  pro: 60,  elite: 100 },
];

function TierValueBars() {
  const tiers = [
    { key: 'observer', label: 'Observer', color: C.muted },
    { key: 'pro',      label: 'Pro',      color: C.brand },
    { key: 'elite',    label: 'Elite',    color: C.bull  },
  ] as const;

  return (
    <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '24px 24px 20px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 8 }}>
        <div>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 2 }}>What you get at each tier</div>
          <div style={{ fontSize: F.xs, color: C.muted }}>Coverage across key dimensions</div>
        </div>
        {/* Tier legend */}
        <div style={{ display: 'flex', gap: 14 }}>
          {tiers.map((t) => (
            <div key={t.key} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <div style={{ width: 10, height: 10, borderRadius: 3, background: t.color }} />
              <span style={{ fontSize: F.xs, color: C.textSub, fontWeight: 600 }}>{t.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {TIER_VALUE_DIMS.map((dim) => (
          <div key={dim.label}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 5 }}>
              <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, width: 100, flexShrink: 0 }}>{dim.label}</span>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
                {tiers.map((t) => {
                  const pct: number = dim[t.key as keyof typeof dim] as number;
                  return (
                    <div key={t.key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div style={{ flex: 1, background: `${t.color}18`, borderRadius: 99, height: 8, overflow: 'hidden' }}>
                        <div style={{
                          width: `${pct}%`,
                          height: '100%',
                          background: t.color,
                          borderRadius: 99,
                          transition: 'width 0.4s ease',
                          minWidth: pct > 0 ? 4 : 0,
                        }} />
                      </div>
                      <span style={{ fontSize: 10, color: pct === 0 ? C.faint : t.color, fontWeight: 600, width: 30, textAlign: 'right', flexShrink: 0 }}>
                        {pct === 0 ? '—' : `${pct}%`}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Returns Calculator ───────────────────────────────────────────────────────

function ReturnsCalc({ returnPct }: { returnPct: number }) {
  const [capital, setCapital] = useState(3000);
  const projected = capital * (returnPct / 100);
  return (
    <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '24px 28px', maxWidth: 480, marginLeft: 'auto', marginRight: 'auto' }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 16 }}>What could this mean for you?</div>
      <div style={{ marginBottom: 14 }}>
        <label style={{ fontSize: F.xs, color: C.muted, display: 'block', marginBottom: 6 }}>Your trading capital</label>
        <input
          type="range" min={1000} max={100000} step={1000} value={capital}
          onChange={(e) => setCapital(Number(e.target.value))}
          aria-label="Trading capital amount"
          style={{ width: '100%', accentColor: C.brand }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4 }}>
          <span style={{ fontSize: F.xs, color: C.muted }}>$1,000</span>
          <span style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>{fmtUsd(capital, 0)}</span>
          <span style={{ fontSize: F.xs, color: C.muted }}>$100,000</span>
        </div>
      </div>
      <div style={{ background: C.surface, borderRadius: R.md, padding: '14px 16px', textAlign: 'center' }}>
        <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>Projected return at {returnPct.toFixed(1)}% (30-day backtest rate)</div>
        <div style={{ fontSize: F['2xl'], fontWeight: 800, color: C.bull }}>{fmtUsd(projected)}</div>
        <div style={{ fontSize: F.xs, color: C.muted, marginTop: 4 }}>Past performance does not predict future results</div>
      </div>
    </div>
  );
}

// ─── Feature Comparison ───────────────────────────────────────────────────────

const ALL_FEATURES = [
  { category: 'Signals', rows: [
    { feature: 'Live signals', observer: 'Delayed 15m', pro: 'Real-time', elite: 'Real-time' },
    { feature: 'Signal reasoning', observer: '✓', pro: '✓', elite: '✓' },
    { feature: 'AI confidence score', observer: '✓', pro: '✓', elite: '✓' },
    { feature: 'Symbols covered', observer: 'BTC, SOL, HYPE', pro: 'BTC, SOL, HYPE', elite: 'Unlimited' },
  ]},
  { category: 'Alerts', rows: [
    { feature: 'Telegram signal alerts', observer: '—', pro: '✓', elite: '✓' },
    { feature: 'Telegram TP/close alerts', observer: '—', pro: '✓', elite: '✓' },
    { feature: 'Morning brief (06:00 UTC)', observer: '—', pro: '✓', elite: '✓' },
    { feature: 'Custom thresholds', observer: '—', pro: '—', elite: '✓' },
  ]},
  { category: 'Analytics', rows: [
    { feature: 'Track record & forensics', observer: '✓', pro: '✓', elite: '✓' },
    { feature: 'AI audit trail', observer: '✓', pro: '✓', elite: '✓' },
    { feature: 'Performance metrics (Sharpe etc.)', observer: '✓', pro: '✓', elite: '✓' },
    { feature: 'Portfolio page', observer: '✓', pro: '✓', elite: '✓' },
  ]},
  { category: 'Execution', rows: [
    { feature: 'Manual copy trade guide', observer: '✓', pro: '✓', elite: '✓' },
    { feature: 'Auto-execution (API)', observer: '—', pro: '—', elite: '✓' },
    { feature: 'Custom risk parameters', observer: '—', pro: '—', elite: '✓' },
    { feature: 'API access', observer: '—', pro: '—', elite: '✓' },
  ]},
  { category: 'Learning', rows: [
    { feature: 'Course (Sections 1–3)', observer: '✓', pro: '✓', elite: '✓' },
    { feature: 'Full course (8 sections)', observer: '—', pro: '✓', elite: '✓' },
    { feature: 'Interactive calculators', observer: 'Basic', pro: '✓', elite: '✓' },
  ]},
  { category: 'Support', rows: [
    { feature: 'Discord community', observer: 'Read-only', pro: '✓', elite: '✓' },
    { feature: 'Priority support', observer: '—', pro: '—', elite: '✓' },
    { feature: 'Onboarding call', observer: '—', pro: '—', elite: '✓' },
  ]},
];

function FeatureTable({ annual }: { annual: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const showCategories = expanded ? ALL_FEATURES : ALL_FEATURES.slice(0, 3);
  return (
    <div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: F.sm, minWidth: 560 }}>
          <thead>
            <tr style={{ background: C.surface }}>
              <th style={{ padding: '10px 16px', textAlign: 'left', color: C.muted, fontWeight: 600, fontSize: F.xs, borderBottom: `1px solid ${C.border}` }}>Feature</th>
              {['Observer', 'Pro', 'Elite'].map((t) => (
                <th key={t} style={{ padding: '10px 16px', textAlign: 'center', color: t === 'Pro' ? C.brand : C.muted, fontWeight: 700, fontSize: F.xs, borderBottom: `1px solid ${C.border}` }}>{t}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {showCategories.map((cat) => (
              <React.Fragment key={cat.category}>
                <tr>
                  <td colSpan={4} style={{ padding: '10px 16px 4px', fontSize: F.xs, fontWeight: 700, color: C.brand, textTransform: 'uppercase', letterSpacing: '0.05em', background: `${C.brand}08` }}>{cat.category}</td>
                </tr>
                {cat.rows.map((row) => (
                  <tr key={row.feature} style={{ borderBottom: `1px solid ${C.border}` }}>
                    <td style={{ padding: '9px 16px', color: C.textSub }}>{row.feature}</td>
                    {([['observer', row.observer], ['pro', row.pro], ['elite', row.elite]] as [string, string][]).map(([tier, v]) => (
                      <td key={tier} style={{ padding: '9px 16px', textAlign: 'center', color: v === '✓' ? C.bull : v === '—' ? C.faint : C.muted, fontWeight: v === '✓' ? 700 : 400 }}>{v}</td>
                    ))}
                  </tr>
                ))}
              </React.Fragment>
            ))}
          </tbody>
        </table>
      </div>
      {!expanded && (
        <button onClick={() => setExpanded(true)} style={{ width: '100%', padding: '12px', background: G.card, border: `1px solid ${C.border}`, borderTop: 'none', borderRadius: `0 0 ${R.lg}px ${R.lg}px`, cursor: 'pointer', color: C.brand, fontSize: F.sm, fontWeight: 600 }}>
          Show all features ↓
        </button>
      )}
    </div>
  );
}

// ─── MonthlyReturnHeatmap ─────────────────────────────────────────────────────

function MonthlyReturnHeatmap() {
  const MONTH_LABELS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const ROWS = [
    { label: 'Observer', rate: 0.00, color: C.muted },
    { label: 'Pro',      rate: 0.015, color: C.bull },
    { label: 'Elite',    rate: 0.022, color: C.bull },
  ];

  // Build cumulative returns: month index 0 = after month 1
  // cumReturn[m] = (1 + rate)^(m+1) - 1
  const getCumReturn = (rate: number, monthIdx: number) =>
    Math.pow(1 + rate, monthIdx + 1) - 1;

  // Max possible cumulative return for color scaling (Elite, month 11)
  const maxReturn = getCumReturn(0.022, 11); // ~29.7%

  // Green intensity: 0 → transparent, 1 → C.bull
  // Observer row stays gray
  const cellBg = (tierIdx: number, monthIdx: number): string => {
    const rate = ROWS[tierIdx].rate;
    if (rate === 0) return C.faint; // Observer: flat gray
    const cum = getCumReturn(rate, monthIdx);
    // Map 0..maxReturn to 0..1 intensity
    const intensity = Math.min(cum / maxReturn, 1);
    // Interpolate: low → heatBull1 (#22c55e), high → heatBull3 (#166534)
    // Use opacity on a dark green to keep text readable
    const alpha = Math.round(30 + intensity * 180); // 30–210 hex
    const alphaHex = alpha.toString(16).padStart(2, '0');
    return `${C.bull}${alphaHex}`;
  };

  const cellTextColor = (tierIdx: number, monthIdx: number): string => {
    const rate = ROWS[tierIdx].rate;
    if (rate === 0) return C.muted;
    const cum = getCumReturn(rate, monthIdx);
    const intensity = Math.min(cum / maxReturn, 1);
    // Light text at high intensity, muted-green at low
    return intensity > 0.5 ? '#dcfce7' : C.bullLight;
  };

  const fmtCum = (rate: number, monthIdx: number): string => {
    if (rate === 0) return '—';
    const cum = getCumReturn(rate, monthIdx);
    return `+${(cum * 100).toFixed(1)}%`;
  };

  // SVG layout
  const COL_COUNT = 12;
  const ROW_COUNT = 3;
  const LABEL_W = 64;
  const CELL_W = 56;
  const CELL_H = 40;
  const HEADER_H = 24;
  const GAP = 3;
  const PAD = 16;

  const totalW = PAD + LABEL_W + GAP + COL_COUNT * (CELL_W + GAP) + PAD;
  const totalH = PAD + HEADER_H + GAP + ROW_COUNT * (CELL_H + GAP) + PAD;

  const colX = (colIdx: number) => PAD + LABEL_W + GAP + colIdx * (CELL_W + GAP);
  const rowY = (rowIdx: number) => PAD + HEADER_H + GAP + rowIdx * (CELL_H + GAP);

  return (
    <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.xl, padding: '24px 24px 16px' }}>
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 2 }}>
          Projected Cumulative Returns (monthly compounding)
        </div>
        <div style={{ fontSize: F.xs, color: C.muted }}>
          Each cell shows expected cumulative gain at end of that month · Observer has no alpha edge
        </div>
      </div>

      <svg
        viewBox={`0 0 ${totalW} ${totalH}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
      >
        {/* Column header: month labels */}
        {MONTH_LABELS.map((mo, ci) => (
          <text
            key={mo}
            x={colX(ci) + CELL_W / 2}
            y={PAD + HEADER_H - 6}
            textAnchor="middle"
            fontSize={9}
            fill={C.muted}
            fontWeight={600}
          >{mo}</text>
        ))}

        {/* Rows */}
        {ROWS.map((row, ri) => (
          <g key={row.label}>
            {/* Row label */}
            <text
              x={PAD + LABEL_W - 8}
              y={rowY(ri) + CELL_H / 2 + 4}
              textAnchor="end"
              fontSize={10}
              fill={row.color}
              fontWeight={700}
            >{row.label}</text>

            {/* Cells */}
            {MONTH_LABELS.map((_mo, ci) => {
              const isLast = ci === 11;
              const bg = cellBg(ri, ci);
              const textCol = cellTextColor(ri, ci);
              const label = fmtCum(row.rate, ci);
              return (
                <g key={ci}>
                  <rect
                    x={colX(ci)}
                    y={rowY(ri)}
                    width={CELL_W}
                    height={CELL_H}
                    rx={R.xs}
                    fill={bg}
                    stroke={isLast && row.rate > 0 ? row.color : 'none'}
                    strokeWidth={isLast && row.rate > 0 ? 1.5 : 0}
                  />
                  <text
                    x={colX(ci) + CELL_W / 2}
                    y={rowY(ri) + CELL_H / 2 + 4}
                    textAnchor="middle"
                    fontSize={row.rate === 0 ? 9 : 9}
                    fill={row.rate === 0 ? C.faint : textCol}
                    fontWeight={isLast && row.rate > 0 ? 700 : 500}
                  >{label}</text>
                </g>
              );
            })}
          </g>
        ))}

        {/* Final column "Year-end" callout labels */}
        {ROWS.filter((r) => r.rate > 0).map((row, idx) => {
          const ri = idx + 1; // Observer is ri=0, skip
          const cum = getCumReturn(row.rate, 11);
          const yr = `+${(cum * 100).toFixed(1)}%`;
          return (
            <text
              key={row.label}
              x={colX(11) + CELL_W + 6}
              y={rowY(ri) + CELL_H / 2 + 4}
              fontSize={9}
              fill={row.color}
              fontWeight={700}
            >{yr}</text>
          );
        })}
      </svg>

      <div style={{ fontSize: 10, color: C.faint, marginTop: 8, textAlign: 'center', lineHeight: 1.5 }}>
        Illustrative only. Assumes constant monthly rate. Past performance does not guarantee future results.
      </div>
    </div>
  );
}

// ─── BreakEvenCalculator ──────────────────────────────────────────────────────

const TIER_COSTS = [0, 29, 97] as const;
const TIER_NAMES = ['Observer', 'Pro', 'Elite'] as const;
const TIER_COLORS: [string, string, string] = [C.muted, C.brand, C.bull];

function BreakEvenCalculator() {
  const [accountSize, setAccountSize] = useState(5000);
  const [tier, setTier] = useState<0 | 1 | 2>(1);

  const monthlyCost = TIER_COSTS[tier];
  const safeAccountSize = accountSize > 0 ? accountSize : 1;
  const breakEvenReturnPct = monthlyCost > 0 ? (monthlyCost / safeAccountSize) * 100 : 0;
  // break-even trade count: assume 1.5% profit per winning trade, 77% win rate
  // expected profit per trade = 1.5% * 0.77 - (1 - 0.77) * something
  // Simplified: each trade nets 0.015 * accountSize on average (gross).
  // We need: n * 0.015 * 0.77 * accountSize >= monthlyCost
  const breakEvenTrades =
    monthlyCost > 0
      ? Math.ceil(monthlyCost / (safeAccountSize * 0.015 * 0.77))
      : 0;
  const monthlyReturnGross = safeAccountSize * 0.11;
  const netProfit = monthlyReturnGross - monthlyCost;
  const accentColor = TIER_COLORS[tier];

  return (
    <div
      style={{
        background: G.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.xl,
        padding: '24px 28px',
      }}
    >
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 2 }}>
          Break-Even Calculator
        </div>
        <div style={{ fontSize: F.xs, color: C.muted }}>
          How much do you need to earn to cover the subscription cost?
        </div>
      </div>

      {/* Input row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18, flexWrap: 'wrap' }}>
        <label style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, flexShrink: 0 }}>Account:</label>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ fontSize: F.sm, color: C.muted, fontWeight: 700 }}>$</span>
          <input
            type="number"
            min={1000}
            max={100000}
            step={1000}
            value={accountSize}
            onChange={(e) => {
              const raw = Number(e.target.value);
              if (isNaN(raw)) return;
              const v = Math.max(1000, Math.min(100000, raw));
              setAccountSize(v);
            }}
            style={{
              background: C.surface,
              border: `1px solid ${C.border}`,
              borderRadius: R.md,
              color: C.text,
              fontSize: F.base,
              fontWeight: 700,
              padding: '6px 10px',
              width: 110,
              outline: 'none',
            }}
          />
        </div>

        {/* Tier buttons */}
        <div style={{ display: 'flex', gap: 6, marginLeft: 8, flexWrap: 'wrap' }}>
          {([0, 1, 2] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTier(t)}
              style={{
                padding: '5px 14px',
                borderRadius: R.pill,
                border: `1px solid ${tier === t ? TIER_COLORS[t] : C.border}`,
                background: tier === t ? `${TIER_COLORS[t]}20` : C.surface,
                color: tier === t ? TIER_COLORS[t] : C.muted,
                fontSize: F.xs,
                fontWeight: 700,
                cursor: 'pointer',
              }}
            >
              {TIER_NAMES[t]}
              {TIER_COSTS[t] > 0 ? `/$${TIER_COSTS[t]}` : '/Free'}
            </button>
          ))}
        </div>
      </div>

      {/* Output box */}
      <div
        style={{
          background: C.surface,
          border: `1px solid ${accentColor}30`,
          borderRadius: R.lg,
          padding: '16px 20px',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
          gap: 16,
        }}
      >
        <div>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>Monthly cost</div>
          <div style={{ fontSize: F['2xl'], fontWeight: 800, color: accentColor }}>
            ${monthlyCost}
          </div>
        </div>
        <div>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>Break-even return</div>
          <div style={{ fontSize: F['2xl'], fontWeight: 800, color: accentColor }}>
            {monthlyCost > 0 ? `${breakEvenReturnPct.toFixed(2)}%` : '0.00%'}
          </div>
        </div>
        <div>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>Break-even trades</div>
          <div style={{ fontSize: F['2xl'], fontWeight: 800, color: accentColor }}>
            {monthlyCost > 0 ? `~${breakEvenTrades}` : '—'}
          </div>
          {monthlyCost > 0 && (
            <div style={{ fontSize: 10, color: C.muted, marginTop: 2 }}>
              at 1.5% avg · 77% win rate
            </div>
          )}
        </div>
        <div>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>
            At 11% monthly return
          </div>
          <div
            style={{
              fontSize: F['2xl'],
              fontWeight: 800,
              color: netProfit >= 0 ? C.bull : C.bear,
            }}
          >
            {netProfit >= 0 ? '+' : ''}${netProfit.toFixed(0)}
          </div>
          <div style={{ fontSize: 10, color: C.muted, marginTop: 2 }}>net profit</div>
        </div>
      </div>
    </div>
  );
}

// ─── CostVsReturnChart ─────────────────────────────────────────────────────────

function CostVsReturnChart() {
  const W = 480;
  const H = 180;
  const padL = 56;
  const padR = 90; // room for end labels
  const padT = 36; // room for title
  const padB = 28;
  const chartW = W - padL - padR;
  const chartH = H - padT - padB;

  const START = 5000;
  const MONTHLY_RETURN = 0.11;
  const MONTHS = 12;

  // Performance multipliers per tier
  const perfBonus = [1.0, 1.08, 1.15] as const;
  const costs = [0, 29, 97] as const;

  const buildEquity = (tierIdx: number): number[] =>
    Array.from({ length: MONTHS + 1 }, (_, m) => {
      if (m === 0) return START;
      // compound return adjusted by performance bonus, minus monthly cost
      let equity = START;
      for (let i = 1; i <= m; i++) {
        equity = equity * (1 + MONTHLY_RETURN * perfBonus[tierIdx]) - costs[tierIdx];
      }
      return equity;
    });

  const observerEquity = buildEquity(0);
  const proEquity = buildEquity(1);
  const eliteEquity = buildEquity(2);

  const yMin = 5000;
  const yMax = 20000;

  const xScale = (m: number) => padL + (m / MONTHS) * chartW;
  const yScale = (v: number) =>
    padT + chartH - Math.max(0, Math.min(1, (v - yMin) / (yMax - yMin))) * chartH;

  const pointsToPath = (data: number[]) =>
    data
      .map((v, i) => `${i === 0 ? 'M' : 'L'}${xScale(i).toFixed(1)},${yScale(v).toFixed(1)}`)
      .join(' ');

  const yTicks = [5000, 10000, 15000, 20000];
  const fmtK = (v: number) => `$${(v / 1000).toFixed(0)}k`;

  const obsFinal = observerEquity[MONTHS];
  const proFinal = proEquity[MONTHS];
  const eliteFinal = eliteEquity[MONTHS];

  const lineColors: [string, string, string] = [C.muted, C.brand, C.bull];

  const titleY = padT - 12;

  return (
    <div
      style={{
        background: G.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.xl,
        padding: '20px 24px 16px',
      }}
    >
      <svg
        viewBox={`0 0 ${W} ${H}`}
        style={{ width: '100%', height: 'auto', display: 'block', overflow: 'visible' }}
      >
        {/* Title */}
        <text
          x={W / 2}
          y={titleY}
          textAnchor="middle"
          fontSize={10}
          fill={C.textSub}
          fontWeight={700}
        >
          12-Month Growth Projection ($5,000 start, ~11% avg monthly)
        </text>

        {/* Y-axis grid + labels */}
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              x1={padL}
              y1={yScale(tick)}
              x2={W - padR}
              y2={yScale(tick)}
              stroke={tick === 5000 ? C.muted : C.border}
              strokeWidth={tick === 5000 ? 1 : 0.8}
              strokeDasharray={tick === 5000 ? '4 3' : undefined}
            />
            <text
              x={padL - 6}
              y={yScale(tick) + 4}
              textAnchor="end"
              fontSize={9}
              fill={C.muted}
            >
              {fmtK(tick)}
            </text>
          </g>
        ))}

        {/* X-axis labels */}
        {Array.from({ length: MONTHS }, (_, i) => i + 1).map((m) => (
          <text
            key={m}
            x={xScale(m)}
            y={padT + chartH + 16}
            textAnchor="middle"
            fontSize={9}
            fill={C.muted}
          >
            {m}
          </text>
        ))}
        {/* X-axis title */}
        <text
          x={padL + chartW / 2}
          y={padT + chartH + 26}
          textAnchor="middle"
          fontSize={8}
          fill={C.faint}
        >
          Month
        </text>

        {/* Lines */}
        <path
          d={pointsToPath(observerEquity)}
          fill="none"
          stroke={lineColors[0]}
          strokeWidth={1.5}
          strokeDasharray="5 4"
        />
        <path d={pointsToPath(proEquity)} fill="none" stroke={lineColors[1]} strokeWidth={2} />
        <path d={pointsToPath(eliteEquity)} fill="none" stroke={lineColors[2]} strokeWidth={2} />

        {/* End labels */}
        {(
          [
            { equity: obsFinal, color: lineColors[0], label: 'Observer' },
            { equity: proFinal, color: lineColors[1], label: 'Pro' },
            { equity: eliteFinal, color: lineColors[2], label: 'Elite' },
          ] as { equity: number; color: string; label: string }[]
        ).map((item) => (
          <g key={item.label}>
            <text
              x={W - padR + 6}
              y={yScale(item.equity) + 4}
              fontSize={9}
              fill={item.color}
              fontWeight={700}
            >
              {item.label}: ${Math.round(item.equity).toLocaleString()}
            </text>
          </g>
        ))}
      </svg>

      <div
        style={{
          fontSize: 10,
          color: C.faint,
          marginTop: 6,
          textAlign: 'center',
          lineHeight: 1.5,
        }}
      >
        Projected based on historical backtest performance. Not a guarantee.
      </div>
    </div>
  );
}

// ─── FAQ ──────────────────────────────────────────────────────────────────────

function PFAQ({ q, a }: { q: string; a: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ border: `1px solid ${C.border}`, borderRadius: R.md, marginBottom: 8 }}>
      <button onClick={() => setOpen((v) => !v)} style={{ width: '100%', display: 'flex', justifyContent: 'space-between', padding: '13px 16px', background: C.card, border: 'none', cursor: 'pointer', textAlign: 'left', gap: 8 }}>
        <span style={{ fontSize: F.sm, fontWeight: 600, color: C.text }}>{q}</span>
        <span style={{ color: C.muted, flexShrink: 0, transition: 'transform 0.15s', transform: open ? 'rotate(45deg)' : 'none', display: 'inline-block' }}>+</span>
      </button>
      {open && <div style={{ padding: '0 16px 14px', fontSize: F.sm, color: C.textSub, lineHeight: 1.7, background: C.card, borderTop: `1px solid ${C.border}` }}>{a}</div>}
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function PricingPage() {
  const [annual, setAnnual] = useState(false);
  const returnPct = 11.34; // from backtest results

  return (
    <Layout>
      <Head>
        <title>Pricing — WAGMI</title>
        <meta name="description" content="Start free. Upgrade when you're ready to automate. Three clear tiers with honest feature differentiation." />
      </Head>

      <div style={{ maxWidth: 1000, margin: '0 auto', padding: '40px 20px' }}>

        {/* ── Header ── */}
        <div style={{ textAlign: 'center', marginBottom: 40 }}>
          <h1 style={{ margin: '0 0 12px', fontSize: F['3xl'], fontWeight: 900, color: C.text, letterSpacing: -0.5 }}>Pick your edge.</h1>
          <p style={{ margin: '0 0 24px', fontSize: F.base, color: C.muted }}>Start free. Upgrade when you're ready to automate.</p>

          {/* Annual toggle */}
          <div style={{ display: 'inline-flex', alignItems: 'center', gap: 10, background: G.card, border: `1px solid ${C.border}`, borderRadius: R.pill, padding: '4px 8px' }}>
            <button onClick={() => setAnnual(false)} style={{ padding: '5px 16px', borderRadius: R.pill, border: 'none', cursor: 'pointer', background: !annual ? C.brand : 'transparent', color: !annual ? '#fff' : C.muted, fontSize: F.sm, fontWeight: 600 }}>Monthly</button>
            <button onClick={() => setAnnual(true)} style={{ padding: '5px 16px', borderRadius: R.pill, border: 'none', cursor: 'pointer', background: annual ? C.brand : 'transparent', color: annual ? '#fff' : C.muted, fontSize: F.sm, fontWeight: 600 }}>
              Annual <span style={{ fontSize: F.xs, color: annual ? '#c7d2fe' : C.bull, marginLeft: 4 }}>Save 33%</span>
            </button>
          </div>
        </div>

        {/* ── Tier Cards ── */}
        <style>{`@media (max-width: 720px) { .tier-grid { grid-template-columns: 1fr !important; } }`}</style>
        <div className="tier-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 48, alignItems: 'start' }}>
          {TIERS.map((tier) => {
            const price = annual && tier.annual != null ? tier.annual / 12 : tier.monthly;
            return (
              <div key={tier.name} style={{
                background: G.card, border: `1px solid ${tier.highlighted ? C.brand : C.border}`,
                borderRadius: R.xl, padding: '28px 24px', position: 'relative',
                boxShadow: tier.highlighted ? S.glow : S.sm,
                transform: tier.highlighted ? 'translateY(-6px)' : 'none',
              }}>
                {tier.badge && (
                  <div style={{ position: 'absolute', top: -12, left: '50%', transform: 'translateX(-50%)', padding: '3px 14px', borderRadius: R.pill, background: C.brand, color: '#fff', fontSize: F.xs, fontWeight: 700, whiteSpace: 'nowrap' }}>{tier.badge}</div>
                )}
                <div style={{ fontSize: F.lg, fontWeight: 800, color: C.text, marginBottom: 4 }}>{tier.name}</div>
                <div style={{ fontSize: F.sm, color: C.muted, marginBottom: 16, lineHeight: 1.4 }}>{tier.tagline}</div>
                <div style={{ marginBottom: 20 }}>
                  <span style={{ fontSize: 36, fontWeight: 900, color: tier.highlighted ? C.brand : C.text }}>
                    {price === 0 ? 'Free' : `$${price?.toFixed(0)}`}
                  </span>
                  {price !== null && price > 0 && (
                    <span style={{ fontSize: F.sm, color: C.muted }}>/month{annual ? ' · billed annually' : ''}</span>
                  )}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 24 }}>
                  {tier.features.map((f) => (
                    <div key={f.label} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                      <span style={{ color: f.included ? C.bull : C.faint, flexShrink: 0, fontWeight: 700, marginTop: 1 }}>{f.included ? '✓' : '—'}</span>
                      <span style={{ fontSize: F.xs, color: f.included ? C.textSub : C.faint, lineHeight: 1.4 }}>
                        {f.label}{f.note && <span style={{ color: C.muted }}> ({f.note})</span>}
                      </span>
                    </div>
                  ))}
                </div>
                <Link href={tier.ctaHref} style={{
                  display: 'block', textAlign: 'center', padding: '11px 0',
                  background: tier.highlighted ? C.brand : C.surface,
                  color: tier.highlighted ? '#fff' : C.textSub,
                  border: `1px solid ${tier.highlighted ? C.brand : C.border}`,
                  borderRadius: R.md, fontSize: F.sm, fontWeight: 700, textDecoration: 'none',
                }}>{tier.cta}</Link>
              </div>
            );
          })}
        </div>

        {/* ── Tier Value Bars ── */}
        <div style={{ marginBottom: 40 }}>
          <h2 style={{ margin: '0 0 16px', fontSize: F.xl, fontWeight: 700, color: C.text, textAlign: 'center' }}>What each tier unlocks</h2>
          <TierValueBars />
        </div>

        {/* ── Returns Calculator ── */}
        <div style={{ marginBottom: 52 }}>
          <ReturnsCalc returnPct={returnPct} />
        </div>

        {/* ── ROI Timeline Chart ── */}
        <div style={{ marginBottom: 52 }}>
          <RoiTimelineChart />
        </div>

        {/* ── Feature Table ── */}
        <div style={{ marginBottom: 52 }}>
          <h2 style={{ margin: '0 0 20px', fontSize: F.xl, fontWeight: 700, color: C.text, textAlign: 'center' }}>Full feature comparison</h2>
          <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, overflow: 'hidden' }}>
            <FeatureTable annual={annual} />
          </div>
        </div>

        {/* ── Social Proof ── */}
        <div style={{ background: `${C.brand}10`, border: `1px solid ${C.brand}30`, borderRadius: R.xl, padding: '24px 28px', marginBottom: 48, textAlign: 'center' }}>
          <div style={{ fontSize: F.xl, fontWeight: 700, color: C.text, marginBottom: 8 }}>7-day money back guarantee</div>
          <div style={{ fontSize: F.sm, color: C.muted }}>Try Pro or Elite for 7 days. If it's not for you, we'll refund without questions.</div>
        </div>

        {/* ── Break-Even Calculator + Growth Projection ── */}
        <div style={{ marginBottom: 52 }}>
          <h2 style={{ margin: '0 0 16px', fontSize: F.xl, fontWeight: 700, color: C.text, textAlign: 'center' }}>Is it worth it for your account?</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 20 }}>
            <BreakEvenCalculator />
            <CostVsReturnChart />
          </div>
        </div>

        {/* ── Monthly Return Heatmap ── */}
        <div style={{ marginBottom: 52 }}>
          <MonthlyReturnHeatmap />
        </div>

        {/* ── FAQ ── */}
        <div style={{ marginBottom: 40 }}>
          <h2 style={{ margin: '0 0 20px', fontSize: F.xl, fontWeight: 700, color: C.text, textAlign: 'center' }}>Pricing FAQ</h2>
          <PFAQ q="Is there a free trial?" a="Yes — Pro has a 7-day free trial, no credit card required. Observer is free forever with no time limit." />
          <PFAQ q="Can I cancel anytime?" a="Yes. Monthly plans cancel immediately. Annual plans get a prorated refund in the first 30 days." />
          <PFAQ q="What is auto-execution?" a="Elite tier connects to your Hyperliquid API key and places trades automatically when the bot fires a signal. You set the capital allocation and risk parameters; the bot handles execution." />
          <PFAQ q="Do I need my own Hyperliquid account?" a="Yes for Pro and Elite. For Observer and learning purposes, you can follow signals manually on any exchange that lists BTC/SOL/HYPE perps." />
          <PFAQ q="What if I want to scale up my position size?" a="The bot sizes positions at 1.5% risk per trade based on the capital amount you set in Settings. You can adjust this under Elite's custom risk parameters." />
          <PFAQ q="Is there a difference between the AI signals on Pro vs Elite?" a="No — the AI analysis is identical across all tiers. The difference is delivery speed (delayed vs real-time) and execution mode (manual vs auto)." />
        </div>

        {/* ── Final CTA ── */}
        <div style={{ textAlign: 'center', paddingBottom: 20 }}>
          <div style={{ fontSize: F.sm, color: C.muted, marginBottom: 20 }}>
            Still evaluating? Start with the free track record. No account required.
          </div>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
            <Link href="/results" style={{ padding: '10px 22px', border: `1px solid ${C.border}`, color: C.textSub, borderRadius: R.md, fontSize: F.sm, fontWeight: 600, textDecoration: 'none' }}>
              See the Track Record →
            </Link>
            <Link href="/copy-trade" style={{ padding: '10px 22px', background: C.brand, color: '#fff', borderRadius: R.md, fontSize: F.sm, fontWeight: 700, textDecoration: 'none', boxShadow: S.glow }}>
              Start Free →
            </Link>
          </div>
        </div>
      </div>
    </Layout>
  );
}
