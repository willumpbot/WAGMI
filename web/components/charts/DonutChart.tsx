'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { C, R, F } from '../../src/theme';
import { staggerContainer } from '../../src/animations';

// ── Types ────────────────────────────────────────────────────────────────────

export type DonutSegment = {
  label: string;
  value: number;
  color: string;
};

export type DonutChartProps = {
  segments: DonutSegment[];
  size?: number;
  thickness?: number;
  centerLabel?: string;
  centerValue?: string;
};

// ── Component ────────────────────────────────────────────────────────────────

export function DonutChart({
  segments,
  size = 200,
  thickness = 32,
  centerLabel,
  centerValue,
}: DonutChartProps) {
  const filtered = segments.filter((s) => s.value > 0);
  const total = filtered.reduce((s, seg) => s + seg.value, 0);
  if (!total || !filtered.length) return null;

  const radius = (size - thickness) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * radius;

  // Build arc segments
  let accumulatedOffset = 0;
  const arcs = filtered.map((seg) => {
    const fraction = seg.value / total;
    const dashLength = fraction * circumference;
    const gap = circumference - dashLength;
    const offset = -accumulatedOffset;
    accumulatedOffset += dashLength;
    return { ...seg, fraction, dashLength, gap, offset };
  });

  const displayCenter = centerValue ?? total.toString();
  const displayLabel = centerLabel ?? 'Total';

  return (
    <motion.div
      style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}
      initial="hidden"
      animate="show"
      variants={staggerContainer}
    >
      <div style={{ position: 'relative', width: size, height: size }}>
        <svg viewBox={`0 0 ${size} ${size}`} style={{ width: '100%', height: '100%', display: 'block' }}>
          {/* Background ring */}
          <circle cx={cx} cy={cy} r={radius} fill="none" stroke={C.surfaceHover} strokeWidth={thickness} />

          {/* Segments */}
          {arcs.map((arc, i) => (
            <motion.circle
              key={arc.label}
              cx={cx}
              cy={cy}
              r={radius}
              fill="none"
              stroke={arc.color}
              strokeWidth={thickness}
              strokeDasharray={`${arc.dashLength} ${arc.gap}`}
              strokeDashoffset={arc.offset}
              strokeLinecap="butt"
              transform={`rotate(-90 ${cx} ${cy})`}
              initial={{ strokeDashoffset: circumference }}
              animate={{ strokeDashoffset: arc.offset }}
              transition={{
                duration: 0.6,
                delay: i * 0.08,
                ease: [0.25, 0.1, 0.25, 1],
              }}
            />
          ))}
        </svg>

        {/* Center text */}
        <div
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <span style={{ fontSize: F['2xl'], fontWeight: 800, color: C.text, lineHeight: 1.1 }}>
            {displayCenter}
          </span>
          <span style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>{displayLabel}</span>
        </div>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, justifyContent: 'center' }}>
        {filtered.map((seg) => (
          <div
            key={seg.label}
            style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: F.xs }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: 2,
                background: seg.color,
                display: 'inline-block',
              }}
            />
            <span style={{ color: C.textSub, fontWeight: 600 }}>{seg.label}</span>
            <span style={{ color: C.muted }}>
              {seg.value} ({((seg.value / total) * 100).toFixed(0)}%)
            </span>
          </div>
        ))}
      </div>
    </motion.div>
  );
}

export default DonutChart;
