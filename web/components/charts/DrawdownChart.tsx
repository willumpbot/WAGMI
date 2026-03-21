'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { C, R, F, G } from '../../src/theme';
import { pathDraw, staggerContainer } from '../../src/animations';

// ── Types ────────────────────────────────────────────────────────────────────

export type DrawdownPoint = {
  equity: number;
};

export type DrawdownChartProps = {
  points: DrawdownPoint[];
  width?: number;
  height?: number;
};

// ── Component ────────────────────────────────────────────────────────────────

export function DrawdownChart({ points, width = 700, height = 80 }: DrawdownChartProps) {
  if (!points || points.length < 2) return null;

  // Calculate drawdown from equity values
  const equities = points.map((p) => p.equity);
  let peak = equities[0];
  const dds = equities.map((e) => {
    if (e > peak) peak = e;
    return peak > 0 ? -((peak - e) / peak) * 100 : 0;
  });

  const maxDd = Math.max(...dds.map(Math.abs), 0.001);
  const pad = { top: 8, right: 20, bottom: 20, left: 70 };
  const W = width - pad.left - pad.right;
  const H = height - pad.top - pad.bottom;

  const px = (i: number) => pad.left + (i / (points.length - 1)) * W;
  const py = (dd: number) => pad.top + (Math.abs(dd) / maxDd) * H;

  const worstIdx = dds.reduce((mi, dd, i) => (Math.abs(dd) > Math.abs(dds[mi]) ? i : mi), 0);
  const worstDd = Math.abs(dds[worstIdx]);

  // Reference lines
  const ref5Y = maxDd >= 5 ? py(5) : null;
  const ref10Y = maxDd >= 10 ? py(10) : null;

  // Build area path
  const areaD =
    `M ${px(0).toFixed(1)},${pad.top} ` +
    dds.map((dd, i) => `L ${px(i).toFixed(1)},${py(dd).toFixed(1)}`).join(' ') +
    ` L ${px(points.length - 1).toFixed(1)},${pad.top} Z`;

  // Severity-colored segment paths
  const segmentPaths: Array<{ d: string; fill: string }> = [];
  for (let i = 0; i < points.length - 1; i++) {
    const ddAbs = Math.abs(dds[i + 1]);
    let fill: string;
    if (ddAbs > 15) fill = C.bear + '80';
    else if (ddAbs > 5) fill = C.bear + '40';
    else fill = C.warn + '40';

    const x0 = px(i);
    const x1 = px(i + 1);
    const y0 = py(dds[i]);
    const y1 = py(dds[i + 1]);
    segmentPaths.push({
      d: `M ${x0.toFixed(1)},${pad.top} L ${x0.toFixed(1)},${y0.toFixed(1)} L ${x1.toFixed(1)},${y1.toFixed(1)} L ${x1.toFixed(1)},${pad.top} Z`,
      fill,
    });
  }

  const gradId = `ddGrad-${Math.random().toString(36).slice(2, 8)}`;

  return (
    <div>
      <div
        style={{
          fontSize: F.xs,
          color: C.bear,
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: 0.7,
          marginBottom: 4,
        }}
      >
        Drawdown
      </div>
      <motion.svg
        viewBox={`0 0 ${width} ${height}`}
        style={{ width: '100%', height: 'auto', display: 'block' }}
        preserveAspectRatio="xMinYMid meet"
        initial="hidden"
        animate="show"
        variants={staggerContainer}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.bear} stopOpacity={0.2} />
            <stop offset="100%" stopColor={C.bear} stopOpacity={0} />
          </linearGradient>
        </defs>

        {/* Severity-colored fill segments */}
        {segmentPaths.map((seg, i) => (
          <motion.path
            key={i}
            d={seg.d}
            fill={seg.fill}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.3, delay: i * 0.002 }}
          />
        ))}

        {/* Reference line at -5% */}
        {ref5Y !== null && (
          <>
            <line
              x1={pad.left}
              y1={ref5Y}
              x2={pad.left + W}
              y2={ref5Y}
              stroke={C.warn}
              strokeWidth={0.8}
              strokeDasharray="4 3"
              opacity={0.6}
            />
            <text x={pad.left - 4} y={ref5Y + 3} fill={C.warn} fontSize={8} textAnchor="end" fontFamily="Inter, system-ui">
              -5%
            </text>
          </>
        )}

        {/* Reference line at -10% */}
        {ref10Y !== null && (
          <>
            <line
              x1={pad.left}
              y1={ref10Y}
              x2={pad.left + W}
              y2={ref10Y}
              stroke={C.bear}
              strokeWidth={0.8}
              strokeDasharray="4 3"
              opacity={0.6}
            />
            <text x={pad.left - 4} y={ref10Y + 3} fill={C.bear} fontSize={8} textAnchor="end" fontFamily="Inter, system-ui">
              -10%
            </text>
          </>
        )}

        {/* Zero baseline */}
        <line
          x1={pad.left}
          y1={pad.top}
          x2={pad.left + W}
          y2={pad.top}
          stroke={C.muted}
          strokeWidth={1}
          opacity={0.5}
        />

        {/* Worst drawdown marker */}
        <circle cx={px(worstIdx)} cy={py(worstDd)} r={3} fill={C.bear} />
        <text
          x={px(worstIdx) + 5}
          y={py(worstDd) + 4}
          fill={C.bear}
          fontSize={9}
          fontFamily="Inter, system-ui"
          fontWeight="600"
        >
          Max DD: -{worstDd.toFixed(1)}%
        </text>

        {/* Y label */}
        <text
          x={pad.left - 4}
          y={pad.top + H / 2}
          fill={C.muted}
          fontSize={9}
          textAnchor="end"
          fontFamily="Inter, system-ui"
        >
          -{maxDd.toFixed(1)}%
        </text>
      </motion.svg>
    </div>
  );
}

export default DrawdownChart;
