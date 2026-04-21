import React from 'react';
import { C } from '../src/theme';

type Props = {
  values: number[];
  color?: string;
  width?: number;
  height?: number;
  stroke?: number;
  fill?: boolean;
  baseline?: 'first' | 'min';
};

/**
 * Tiny inline sparkline for metric cards. SVG-based, no deps.
 * Auto-colors green/red by direction unless `color` is overridden.
 * `baseline='first'` anchors to start (relative trajectory);
 * `baseline='min'` anchors to min (absolute shape).
 */
export default function MetricSparkline({
  values,
  color,
  width = 120,
  height = 28,
  stroke = 1.5,
  fill = true,
  baseline = 'first',
}: Props) {
  if (!values || values.length < 2) {
    return <div style={{ width, height, opacity: 0 }} />;
  }

  const padding = 2;
  const w = width;
  const h = height;

  const vMax = Math.max(...values);
  const vMin = Math.min(...values);
  const range = vMax - vMin || Math.abs(vMax) * 0.01 || 1;

  const anchor = baseline === 'min' ? vMin : values[0];
  const isUp = values[values.length - 1] >= anchor;
  const lineColor = color || (isUp ? C.bull : C.bear);

  const pts = values.map((v, i) => {
    const x = padding + (i / (values.length - 1)) * (w - padding * 2);
    const y = padding + ((vMax - v) / range) * (h - padding * 2);
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  const pathD = 'M' + pts.join(' L');
  const fillD = pathD + ` L${w - padding},${h - padding} L${padding},${h - padding} Z`;
  const gradId = `spark-${lineColor.replace(/[^a-z0-9]/gi, '')}`;

  return (
    <svg
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      style={{ width: '100%', height, display: 'block' }}
      aria-hidden
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lineColor} stopOpacity="0.28" />
          <stop offset="100%" stopColor={lineColor} stopOpacity="0" />
        </linearGradient>
      </defs>
      {fill && <path d={fillD} fill={`url(#${gradId})`} />}
      <path d={pathD} fill="none" stroke={lineColor} strokeWidth={stroke} strokeLinejoin="round" strokeLinecap="round" />
      {/* End-dot to mark current value */}
      <circle
        cx={pts[pts.length - 1].split(',')[0]}
        cy={pts[pts.length - 1].split(',')[1]}
        r="2.2"
        fill={lineColor}
      />
    </svg>
  );
}
