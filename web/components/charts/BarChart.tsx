'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { C, R, F } from '../../src/theme';
import { barGrow, staggerContainer } from '../../src/animations';

// ── Types ────────────────────────────────────────────────────────────────────

export type BarDatum = {
  label: string;
  value: number;
  color?: string;
};

export type BarChartProps = {
  data: BarDatum[];
  height?: number;
  horizontal?: boolean;
};

// ── Component ────────────────────────────────────────────────────────────────

export function BarChart({ data, height = 200, horizontal = false }: BarChartProps) {
  if (!data.length) return null;

  const maxVal = Math.max(...data.map((d) => Math.abs(d.value)), 1);

  if (horizontal) {
    return (
      <motion.div
        style={{ display: 'flex', flexDirection: 'column', gap: 10, width: '100%' }}
        initial="hidden"
        animate="show"
        variants={staggerContainer}
      >
        {data.map((d, i) => {
          const pct = (Math.abs(d.value) / maxVal) * 100;
          const isPos = d.value >= 0;
          const barColor = d.color ?? (isPos ? C.bull : C.bear);

          return (
            <motion.div key={d.label + i} variants={barGrow} style={{ originX: 0 }}>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  marginBottom: 4,
                  fontSize: F.sm,
                }}
              >
                <span style={{ fontWeight: 600, color: C.text }}>{d.label}</span>
                <span style={{ fontWeight: 700, color: barColor }}>
                  {isPos ? '+' : ''}
                  {d.value.toFixed(2)}
                </span>
              </div>
              <div
                style={{
                  height: 16,
                  background: C.surfaceHover,
                  borderRadius: R.sm,
                  overflow: 'hidden',
                }}
              >
                <motion.div
                  initial={{ width: 0 }}
                  animate={{ width: `${pct}%` }}
                  transition={{ duration: 0.5, delay: i * 0.06, ease: [0.25, 0.1, 0.25, 1] }}
                  style={{
                    height: '100%',
                    background: barColor,
                    borderRadius: R.sm,
                    opacity: 0.8,
                  }}
                />
              </div>
            </motion.div>
          );
        })}
      </motion.div>
    );
  }

  // Vertical bars
  const pad = { top: 20, right: 10, bottom: 40, left: 10 };
  const chartW = 100; // percent-based
  const barAreaH = height - pad.top - pad.bottom;
  const barWidth = Math.max(12, Math.min(60, (chartW - data.length * 4) / data.length));

  return (
    <motion.div
      style={{ width: '100%', height }}
      initial="hidden"
      animate="show"
      variants={staggerContainer}
    >
      <svg
        viewBox={`0 0 ${data.length * (barWidth + 12) + pad.left + pad.right} ${height}`}
        style={{ width: '100%', height: '100%', display: 'block' }}
        preserveAspectRatio="xMidYMid meet"
      >
        {/* Baseline */}
        <line
          x1={pad.left}
          y1={pad.top + barAreaH}
          x2={data.length * (barWidth + 12) + pad.left}
          y2={pad.top + barAreaH}
          stroke={C.border}
          strokeWidth={1}
        />

        {data.map((d, i) => {
          const barH = (Math.abs(d.value) / maxVal) * barAreaH;
          const x = pad.left + i * (barWidth + 12) + 6;
          const y = pad.top + barAreaH - barH;
          const barColor = d.color ?? (d.value >= 0 ? C.bull : C.bear);

          return (
            <g key={d.label + i}>
              <motion.rect
                x={x}
                y={y}
                width={barWidth}
                rx={R.xs}
                fill={barColor}
                opacity={0.85}
                initial={{ height: 0, y: pad.top + barAreaH }}
                animate={{ height: barH, y }}
                transition={{ duration: 0.4, delay: i * 0.06, ease: [0.25, 0.1, 0.25, 1] }}
              />
              {/* Value label */}
              <text
                x={x + barWidth / 2}
                y={y - 5}
                textAnchor="middle"
                fill={barColor}
                fontSize={10}
                fontFamily="Inter, system-ui"
                fontWeight="600"
              >
                {d.value >= 0 ? '+' : ''}
                {d.value.toFixed(1)}
              </text>
              {/* Label */}
              <text
                x={x + barWidth / 2}
                y={pad.top + barAreaH + 14}
                textAnchor="middle"
                fill={C.muted}
                fontSize={9}
                fontFamily="Inter, system-ui"
              >
                {d.label}
              </text>
            </g>
          );
        })}
      </svg>
    </motion.div>
  );
}

export default BarChart;
