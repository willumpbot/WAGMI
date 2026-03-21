'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { C, R, F, Glass } from '../../src/theme';
import { fadeUp } from '../../src/animations';

// ─── RSI Scale ───────────────────────────────────────────────────────────────

export function RSIScale() {
  const W = 500, H = 80;
  const toX = (rsi: number) => (rsi / 100) * W;

  const zones = [
    { x1: toX(0),  x2: toX(30), fill: '#16a34a', label: 'OVERSOLD',  labelX: toX(15)  },
    { x1: toX(30), x2: toX(45), fill: '#4ade80', label: '',           labelX: toX(37)  },
    { x1: toX(45), x2: toX(55), fill: '#6b7280', label: 'NEUTRAL',   labelX: toX(50)  },
    { x1: toX(55), x2: toX(70), fill: '#f87171', label: '',           labelX: toX(62)  },
    { x1: toX(70), x2: toX(100),fill: '#dc2626', label: 'OVERBOUGHT',labelX: toX(85)  },
  ];

  const markers = [
    { rsi: 30, label: '30' },
    { rsi: 50, label: '50' },
    { rsi: 70, label: '70' },
  ];

  const dots = [
    { rsi: 62, color: '#f87171', note: '62' },
    { rsi: 48, color: '#9ca3af', note: '48' },
    { rsi: 71, color: '#dc2626', note: '71 \u25B2' },
  ];

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ marginTop: 20, marginBottom: 8 }}
    >
      <div style={{ fontSize: 11, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 8 }}>
        RSI Zone Map
      </div>
      <div style={{ overflowX: 'auto' }}>
        <svg width={W} height={H} style={{ display: 'block', minWidth: W }}>
          <defs>
            <linearGradient id="rsiGrad" x1="0" y1="0" x2="1" y2="0">
              <stop offset="0%"   stopColor="#16a34a" />
              <stop offset="30%"  stopColor="#4ade80" />
              <stop offset="50%"  stopColor="#6b7280" />
              <stop offset="70%"  stopColor="#f87171" />
              <stop offset="100%" stopColor="#dc2626" />
            </linearGradient>
          </defs>

          <rect x={0} y={12} width={W} height={18} rx={4} fill="url(#rsiGrad)" opacity={0.85} />

          {zones.filter(z => z.label).map(z => (
            <text key={z.label} x={z.labelX} y={9} textAnchor="middle" fontSize={9} fontWeight={700} fill={C.text as string} opacity={0.75}>
              {z.label}
            </text>
          ))}

          {markers.map(m => (
            <g key={m.rsi}>
              <line x1={toX(m.rsi)} y1={12} x2={toX(m.rsi)} y2={30} stroke={C.text as string} strokeWidth={1.5} opacity={0.6} />
              <text x={toX(m.rsi)} y={42} textAnchor="middle" fontSize={10} fontWeight={700} fill={C.text as string} opacity={0.8}>
                {m.label}
              </text>
            </g>
          ))}

          <text x={toX(15)}  y={58} textAnchor="middle" fontSize={9} fill="#4ade80">Potential Long</text>
          <text x={toX(50)}  y={58} textAnchor="middle" fontSize={9} fill={C.muted as string}>Neutral</text>
          <text x={toX(85)}  y={58} textAnchor="middle" fontSize={9} fill="#f87171">Potential Short</text>

          {dots.map(d => (
            <g key={d.rsi}>
              <circle cx={toX(d.rsi)} cy={21} r={5} fill={d.color} stroke="#0f172a" strokeWidth={1.5} />
              <text x={toX(d.rsi)} y={76} textAnchor="middle" fontSize={9} fill={d.color} fontWeight={700}>
                {d.note}
              </text>
            </g>
          ))}

          <text x={toX(71) + 8} y={18} fontSize={8} fill="#dc2626" fontWeight={700}>Current</text>
        </svg>
      </div>
      <div style={{ fontSize: 10, color: C.muted, marginTop: 4 }}>
        Dots show example RSI readings. Red dots are in overbought territory -- the bot reduces long conviction here.
      </div>
    </motion.div>
  );
}

// ─── Confidence Gauge ────────────────────────────────────────────────────────

export function ConfidenceGauge({ value = 78 }: { value?: number }) {
  const cx = 100, cy = 100, r = 72;
  const arcStart = 215;
  const arcSweep = 250;

  const toRad = (deg: number) => (deg * Math.PI) / 180;

  const segments = [
    { from: 0,  to: 50,  color: '#dc2626' },
    { from: 50, to: 65,  color: '#f97316' },
    { from: 65, to: 75,  color: '#eab308' },
    { from: 75, to: 85,  color: '#22c55e' },
    { from: 85, to: 100, color: '#16a34a' },
  ];

  const valueAngle = arcStart + (value / 100) * arcSweep;

  const describeArc = (fromVal: number, toVal: number) => {
    const a1 = toRad(arcStart + (fromVal / 100) * arcSweep);
    const a2 = toRad(arcStart + (toVal / 100) * arcSweep);
    const p1 = { x: cx + r * Math.cos(a1), y: cy + r * Math.sin(a1) };
    const p2 = { x: cx + r * Math.cos(a2), y: cy + r * Math.sin(a2) };
    const large = (toVal - fromVal) / 100 * arcSweep > 180 ? 1 : 0;
    return `M ${p1.x} ${p1.y} A ${r} ${r} 0 ${large} 1 ${p2.x} ${p2.y}`;
  };

  const needleAngle = toRad(valueAngle);
  const needleTip = { x: cx + (r - 8) * Math.cos(needleAngle), y: cy + (r - 8) * Math.sin(needleAngle) };
  const needleBase1 = { x: cx + 8 * Math.cos(needleAngle + Math.PI / 2), y: cy + 8 * Math.sin(needleAngle + Math.PI / 2) };
  const needleBase2 = { x: cx + 8 * Math.cos(needleAngle - Math.PI / 2), y: cy + 8 * Math.sin(needleAngle - Math.PI / 2) };

  const thresholds = [
    { val: 0,   label: '0'  },
    { val: 50,  label: '50' },
    { val: 65,  label: '65' },
    { val: 75,  label: '75' },
    { val: 85,  label: '85' },
    { val: 100, label: '100'},
  ];

  const labelColor = value >= 85 ? '#16a34a' : value >= 75 ? '#22c55e' : value >= 65 ? '#eab308' : value >= 50 ? '#f97316' : '#dc2626';

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap', marginTop: 20 }}
    >
      <div>
        <div style={{ fontSize: 11, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 8 }}>
          Confidence Gauge — Example: {value}
        </div>
        <svg width={200} height={130} style={{ display: 'block', overflow: 'visible' }}>
          <path d={describeArc(0, 100)} fill="none" stroke={C.border as string} strokeWidth={14} strokeLinecap="round" />

          {segments.map(seg => (
            <path key={seg.from} d={describeArc(seg.from, seg.to)} fill="none" stroke={seg.color} strokeWidth={14} strokeLinecap="butt" opacity={0.9} />
          ))}

          {thresholds.map(t => {
            const angle = toRad(arcStart + (t.val / 100) * arcSweep);
            const inner = { x: cx + (r - 20) * Math.cos(angle), y: cy + (r - 20) * Math.sin(angle) };
            const outer = { x: cx + (r - 8)  * Math.cos(angle), y: cy + (r - 8)  * Math.sin(angle) };
            const lx    = cx + (r - 28) * Math.cos(angle);
            const ly    = cy + (r - 28) * Math.sin(angle);
            return (
              <g key={t.val}>
                <line x1={inner.x} y1={inner.y} x2={outer.x} y2={outer.y} stroke={C.text as string} strokeWidth={1.5} opacity={0.5} />
                <text x={lx} y={ly + 3} textAnchor="middle" fontSize={8} fill={C.muted as string}>{t.label}</text>
              </g>
            );
          })}

          <polygon
            points={`${needleTip.x},${needleTip.y} ${needleBase1.x},${needleBase1.y} ${needleBase2.x},${needleBase2.y}`}
            fill={labelColor}
            opacity={0.9}
          />
          <circle cx={cx} cy={cy} r={6} fill={C.card as string} stroke={labelColor} strokeWidth={2} />

          <text x={cx} y={cy + 26} textAnchor="middle" fontSize={22} fontWeight={800} fill={labelColor}>{value}</text>
          <text x={cx} y={cy + 38} textAnchor="middle" fontSize={9} fill={C.muted as string}>Confidence</text>
        </svg>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {[
          { range: '85\u2013100', label: 'Strong Setup',    color: '#16a34a' },
          { range: '75\u201384',  label: 'Good Setup',      color: '#22c55e' },
          { range: '65\u201374',  label: 'Moderate',        color: '#eab308' },
          { range: '50\u201364',  label: 'Below Threshold', color: '#f97316' },
          { range: '0\u201349',   label: 'Weak / No Trade', color: '#dc2626' },
        ].map(row => (
          <div key={row.range} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 10, height: 10, borderRadius: 2, background: row.color, flexShrink: 0 }} />
            <span style={{ fontSize: 11, fontWeight: 700, color: row.color, minWidth: 48 }}>{row.range}</span>
            <span style={{ fontSize: 11, color: C.muted }}>{row.label}</span>
          </div>
        ))}
      </div>
    </motion.div>
  );
}

// ─── Autonomy Level Meter ────────────────────────────────────────────────────

export function AutonomyLevelMeter() {
  const levels = [
    { n: 0, name: 'OFF', desc: 'Pure strategy', color: C.muted },
    { n: 1, name: 'ADVISORY', desc: 'Log only', color: C.info },
    { n: 2, name: 'VETO_ONLY', desc: 'Can block', color: C.warn },
    { n: 3, name: 'SIZING', desc: '+ size control', color: '#f97316' },
    { n: 4, name: 'DIRECTION', desc: '+ flip trades', color: C.bear + 'cc' },
    { n: 5, name: 'FULL', desc: 'Full control', color: C.bear },
  ];
  const currentMode = 1;

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ marginTop: 16 }}
    >
      <div style={{ fontSize: F.xs, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>
        Autonomy Scale (default: Level 1 — Advisory)
      </div>
      <div style={{ display: 'flex', gap: 4, marginBottom: 8 }}>
        {levels.map(({ n, name, desc, color }) => (
          <div key={n} style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              padding: '10px 6px',
              borderRadius: R.sm,
              ...Glass.card,
              background: n === currentMode ? color + '22' : C.surfaceHover,
              border: `2px solid ${n === currentMode ? color : C.border}`,
              textAlign: 'center',
              transition: 'all 0.2s',
            }}>
              <div style={{ fontSize: 11, fontWeight: 900, color: n === currentMode ? color : C.muted }}>{n}</div>
              <div style={{ fontSize: 9, fontWeight: 700, color: n === currentMode ? color : C.muted, textTransform: 'uppercase', letterSpacing: 0.3, marginTop: 2 }}>{name}</div>
              <div style={{ fontSize: 9, color: C.muted, marginTop: 3, lineHeight: 1.3 }}>{desc}</div>
            </div>
          </div>
        ))}
      </div>
      {/* Gradient risk bar */}
      <div style={{ height: 6, borderRadius: R.pill, background: `linear-gradient(to right, ${C.muted}, ${C.info}, ${C.warn}, #f97316, ${C.bear + 'cc'}, ${C.bear})`, marginBottom: 4 }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: C.muted }}>
        <span>Safe</span>
        <span>&larr; Increasing LLM Autonomy &rarr;</span>
        <span>Full AI Control</span>
      </div>
    </motion.div>
  );
}

export default { RSIScale, ConfidenceGauge, AutonomyLevelMeter };
