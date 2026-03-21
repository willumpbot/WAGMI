'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { C } from '../../src/theme';
import { pathDraw } from '../../src/animations';

// ── Types ────────────────────────────────────────────────────────────────────

export type SparklineProps = {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
  strokeWidth?: number;
  fill?: boolean;
};

// ── Component ────────────────────────────────────────────────────────────────

export function Sparkline({
  data,
  color = C.brand,
  width = 120,
  height = 32,
  strokeWidth = 1.5,
  fill = false,
}: SparklineProps) {
  if (!data || data.length < 2) return null;

  const pad = 2;
  const W = width - pad * 2;
  const H = height - pad * 2;

  const minV = Math.min(...data);
  const maxV = Math.max(...data);
  const rangeV = maxV - minV || 1;

  const px = (i: number) => pad + (i / (data.length - 1)) * W;
  const py = (v: number) => pad + H - ((v - minV) / rangeV) * H;

  const lineD = data
    .map((v, i) => `${i === 0 ? 'M' : 'L'} ${px(i).toFixed(1)},${py(v).toFixed(1)}`)
    .join(' ');

  const areaD = fill
    ? lineD +
      ` L ${px(data.length - 1).toFixed(1)},${(pad + H).toFixed(1)}` +
      ` L ${px(0).toFixed(1)},${(pad + H).toFixed(1)} Z`
    : '';

  const gradId = `spark-${Math.random().toString(36).slice(2, 8)}`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      style={{ width, height, display: 'block', flexShrink: 0 }}
      preserveAspectRatio="none"
    >
      {fill && (
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.25} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
      )}

      {fill && areaD && <path d={areaD} fill={`url(#${gradId})`} />}

      <motion.path
        d={lineD}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
        initial={{ pathLength: 0, opacity: 0 }}
        animate={{ pathLength: 1, opacity: 1 }}
        transition={{ pathLength: { duration: 0.3, ease: 'easeInOut' }, opacity: { duration: 0.15 } }}
      />
    </svg>
  );
}

export default Sparkline;
