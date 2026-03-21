'use client';

import React, { useId } from 'react';
import { motion } from 'framer-motion';
import { C, R, F, G, fmtUsd } from '../../src/theme';
import { pathDraw, staggerContainer, fadeUp } from '../../src/animations';

// ── Types ────────────────────────────────────────────────────────────────────

export type EquityCurvePoint = {
  equity: number;
  ts?: string;
};

export type EquityCurveProps = {
  points: EquityCurvePoint[];
  width?: number;
  height?: number;
  showSMA?: boolean;
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function calcSMA(data: number[], period: number): (number | null)[] {
  return data.map((_, i) => {
    if (i < period - 1) return null;
    const slice = data.slice(i - period + 1, i + 1);
    return slice.reduce((a, b) => a + b, 0) / period;
  });
}

// ── Component ────────────────────────────────────────────────────────────────

export function EquityCurve({ points, width = 700, height = 200, showSMA = true }: EquityCurveProps) {
  if (!points || points.length < 2) {
    return (
      <div
        style={{
          width: '100%',
          height,
          background: G.card,
          borderRadius: R.md,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: C.muted,
          fontSize: F.sm,
        }}
      >
        No equity curve data available
      </div>
    );
  }

  const equities = points.map((p) => p.equity);
  const minE = Math.min(...equities);
  const maxE = Math.max(...equities);
  const rangeE = maxE - minE || 1;
  const pad = { top: 20, right: 20, bottom: 30, left: 70 };
  const W = width - pad.left - pad.right;
  const H = height - pad.top - pad.bottom;

  const px = (i: number) => pad.left + (i / (points.length - 1)) * W;
  const py = (e: number) => pad.top + H - ((e - minE) / rangeE) * H;

  // Main equity path (as SVG path d string for motion.path)
  const equityD = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${px(i).toFixed(1)},${py(p.equity).toFixed(1)}`)
    .join(' ');

  // SMA calculations
  const sma5 = calcSMA(equities, 5);
  const sma10 = calcSMA(equities, 10);

  const buildSMAPath = (sma: (number | null)[]) => {
    const segments: string[] = [];
    let started = false;
    sma.forEach((v, i) => {
      if (v === null) { started = false; return; }
      segments.push(`${started ? 'L' : 'M'} ${px(i).toFixed(1)},${py(v).toFixed(1)}`);
      started = true;
    });
    return segments.join(' ');
  };

  const sma5Path = showSMA ? buildSMAPath(sma5) : '';
  const sma10Path = showSMA ? buildSMAPath(sma10) : '';

  // ATR envelope: +/-1% band around SMA10
  const sma10WithIdx = sma10
    .map((v, i) => (v !== null ? { v, i } : null))
    .filter((x): x is { v: number; i: number } => x !== null);
  const atrBandPath =
    showSMA && sma10WithIdx.length > 1
      ? `M ${px(sma10WithIdx[0].i).toFixed(1)},${py(sma10WithIdx[0].v * 1.01).toFixed(1)} ` +
        sma10WithIdx.map(({ v, i }) => `L ${px(i).toFixed(1)},${py(v * 1.01).toFixed(1)}`).join(' ') +
        ' ' +
        [...sma10WithIdx].reverse().map(({ v, i }) => `L ${px(i).toFixed(1)},${py(v * 0.99).toFixed(1)}`).join(' ') +
        ' Z'
      : '';

  // Area fill
  const areaD =
    equityD +
    ` L ${px(points.length - 1).toFixed(1)},${(pad.top + H).toFixed(1)}` +
    ` L ${px(0).toFixed(1)},${(pad.top + H).toFixed(1)} Z`;

  const isPositive = equities[equities.length - 1] > equities[0];

  // Peak / trough markers
  const peakIdx = equities.indexOf(maxE);
  let runningMax = equities[0];
  let maxDdIdx = 0;
  let maxDd = 0;
  equities.forEach((e, i) => {
    if (e > runningMax) runningMax = e;
    if (!runningMax || runningMax === 0) return;
    const dd = (runningMax - e) / runningMax;
    if (dd > maxDd) { maxDd = dd; maxDdIdx = i; }
  });

  // Trade markers: >0.5% equity move vs previous
  const tradeMarkers: Array<{ i: number; gain: boolean }> = [];
  for (let i = 1; i < equities.length; i++) {
    const prev = equities[i - 1];
    const change = prev !== 0 ? (equities[i] - prev) / prev : 0;
    if (Math.abs(change) > 0.005) tradeMarkers.push({ i, gain: change > 0 });
  }

  // Y-axis labels
  const yTicks = 4;
  const yLabels = Array.from({ length: yTicks + 1 }, (_, i) => {
    const val = minE + (rangeE / yTicks) * i;
    return { val, y: py(val) };
  });

  // X-axis labels
  const xIndices = [0, Math.floor(points.length / 2), points.length - 1];
  const xLabels = xIndices.map((i) => ({
    i,
    label: points[i].ts
      ? new Date(points[i].ts!).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      : `#${i}`,
  }));

  const lastIdx = points.length - 1;
  const lastEquity = equities[lastIdx];
  const peakEquity = maxE;

  const triUp = (cx: number, cy: number, s: number) =>
    `${cx},${cy - s} ${cx - s},${cy + s} ${cx + s},${cy + s}`;
  const triDown = (cx: number, cy: number, s: number) =>
    `${cx},${cy + s} ${cx - s},${cy - s} ${cx + s},${cy - s}`;

  const legendX = pad.left + 8;
  const legendY = pad.top + 4;
  const uniqueId = useId();
  const gradId = `eqGrad-${uniqueId}`;
  const glowId = `eqGlow-${uniqueId}`;
  const trailGradId = `eqTrail-${uniqueId}`;
  const mainColor = isPositive ? C.bull : C.bear;

  return (
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
          <stop offset="0%" stopColor={mainColor} stopOpacity={0.25} />
          <stop offset="100%" stopColor={mainColor} stopOpacity={0} />
        </linearGradient>
        {/* Glow filter for the trailing particle */}
        <filter id={glowId} x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        {/* Animated glow trail gradient along the line */}
        <linearGradient id={trailGradId} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor={mainColor} stopOpacity={0} />
          <stop offset="85%" stopColor={mainColor} stopOpacity={0} />
          <stop offset="95%" stopColor={mainColor} stopOpacity={0.8} />
          <stop offset="100%" stopColor="#fff" stopOpacity={1} />
        </linearGradient>
      </defs>

      {/* Ambient glow line underneath the main line */}
      <motion.path
        d={equityD}
        fill="none"
        stroke={mainColor}
        strokeWidth={8}
        strokeLinejoin="round"
        strokeLinecap="round"
        opacity={0.12}
        style={{ filter: `blur(6px)` }}
        variants={pathDraw}
      />

      {/* Grid lines */}
      {yLabels.map(({ y }, i) => (
        <line
          key={i}
          x1={pad.left}
          y1={y}
          x2={pad.left + W}
          y2={y}
          stroke={C.border}
          strokeWidth={1}
          strokeDasharray={i === 0 ? '' : '3 4'}
        />
      ))}

      {/* ATR envelope band */}
      {atrBandPath && <path d={atrBandPath} fill={C.brand + '15'} stroke="none" />}

      {/* Area fill */}
      <motion.path d={areaD} fill={`url(#${gradId})`} variants={pathDraw} />

      {/* SMA5 line */}
      {sma5Path && (
        <motion.path
          d={sma5Path}
          fill="none"
          stroke={C.warn}
          strokeWidth={1}
          strokeDasharray="4 3"
          opacity={0.7}
          strokeLinejoin="round"
          variants={pathDraw}
        />
      )}

      {/* SMA10 line */}
      {sma10Path && (
        <motion.path
          d={sma10Path}
          fill="none"
          stroke={C.info}
          strokeWidth={1}
          opacity={0.7}
          strokeLinejoin="round"
          variants={pathDraw}
        />
      )}

      {/* Equity line — glow trail version */}
      <motion.path
        d={equityD}
        fill="none"
        stroke={`url(#${trailGradId})`}
        strokeWidth={3}
        strokeLinejoin="round"
        strokeLinecap="round"
        variants={pathDraw}
      />
      {/* Equity line — main solid */}
      <motion.path
        d={equityD}
        fill="none"
        stroke={mainColor}
        strokeWidth={2.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        variants={pathDraw}
      />

      {/* Trade entry/exit markers */}
      {tradeMarkers.map(({ i, gain }) => {
        const cx = px(i);
        const cy = py(equities[i]);
        return gain ? (
          <polygon key={`m${i}`} points={triUp(cx, cy - 8, 4)} fill={C.bull} opacity={0.85} />
        ) : (
          <polygon key={`m${i}`} points={triDown(cx, cy + 8, 4)} fill={C.bear} opacity={0.85} />
        );
      })}

      {/* Max drawdown point */}
      <circle cx={px(maxDdIdx)} cy={py(equities[maxDdIdx])} r={5} fill={C.bear} stroke={C.card} strokeWidth={2} />
      <text x={px(maxDdIdx) + 7} y={py(equities[maxDdIdx]) - 4} fill={C.bear} fontSize={10} fontFamily="Inter, system-ui">
        Max DD -{(maxDd * 100).toFixed(1)}%
      </text>

      {/* Peak marker */}
      <circle cx={px(peakIdx)} cy={py(peakEquity)} r={6} fill={C.warn} stroke={C.card} strokeWidth={2} opacity={0.9} />
      <text x={px(peakIdx) + 9} y={py(peakEquity) + 4} fill={C.warn} fontSize={10} fontFamily="Inter, system-ui" fontWeight="600">
        Peak: ${peakEquity >= 1000 ? (peakEquity / 1000).toFixed(1) + 'k' : peakEquity.toFixed(0)}
      </text>

      {/* Start dot */}
      <circle cx={px(0)} cy={py(equities[0])} r={4} fill={C.muted} />

      {/* Current value dot — outer pulse ring */}
      <motion.circle
        cx={px(lastIdx)}
        cy={py(lastEquity)}
        r={10}
        fill="none"
        stroke={mainColor}
        strokeWidth={1.5}
        initial={{ opacity: 0.6, r: 6 }}
        animate={{ opacity: [0.6, 0, 0.6], r: [6, 16, 6] }}
        transition={{ duration: 2.5, repeat: Infinity, ease: 'easeInOut' }}
      />
      {/* Current value dot — glow halo */}
      <circle
        cx={px(lastIdx)}
        cy={py(lastEquity)}
        r={12}
        fill={mainColor}
        opacity={0.15}
        style={{ filter: 'blur(6px)' }}
      />
      {/* Current value dot */}
      <circle
        cx={px(lastIdx)}
        cy={py(lastEquity)}
        r={6}
        fill={mainColor}
        stroke={C.card}
        strokeWidth={2}
        filter={`url(#${glowId})`}
      />
      <text
        x={px(lastIdx) - 8}
        y={py(lastEquity) - 10}
        fill={isPositive ? C.bull : C.bear}
        fontSize={10}
        fontFamily="Inter, system-ui"
        fontWeight="600"
        textAnchor="end"
      >
        ${lastEquity >= 1000 ? (lastEquity / 1000).toFixed(1) + 'k' : lastEquity.toFixed(0)}
      </text>

      {/* Y labels */}
      {yLabels.map(({ val, y }, i) => (
        <text key={i} x={pad.left - 6} y={y + 4} textAnchor="end" fill={C.muted} fontSize={10} fontFamily="Inter, system-ui">
          ${(val / 1000).toFixed(1)}k
        </text>
      ))}

      {/* X labels */}
      {xLabels.map(({ i, label }) => (
        <text key={i} x={px(i)} y={height - 4} textAnchor="middle" fill={C.muted} fontSize={10} fontFamily="Inter, system-ui">
          {label}
        </text>
      ))}

      {/* Legend box */}
      {showSMA && (
        <>
          <rect x={legendX - 4} y={legendY - 2} width={102} height={64} fill={C.card} fillOpacity={0.85} rx={4} stroke={C.border} strokeWidth={0.5} />
          <line x1={legendX} y1={legendY + 8} x2={legendX + 14} y2={legendY + 8} stroke={isPositive ? C.bull : C.bear} strokeWidth={2} />
          <text x={legendX + 18} y={legendY + 12} fill={C.muted} fontSize={9} fontFamily="Inter, system-ui">Equity</text>
          <line x1={legendX} y1={legendY + 22} x2={legendX + 14} y2={legendY + 22} stroke={C.warn} strokeWidth={1} strokeDasharray="4 3" opacity={0.9} />
          <text x={legendX + 18} y={legendY + 26} fill={C.muted} fontSize={9} fontFamily="Inter, system-ui">SMA5</text>
          <line x1={legendX} y1={legendY + 36} x2={legendX + 14} y2={legendY + 36} stroke={C.info} strokeWidth={1} opacity={0.9} />
          <text x={legendX + 18} y={legendY + 40} fill={C.muted} fontSize={9} fontFamily="Inter, system-ui">SMA10</text>
          <rect x={legendX} y={legendY + 46} width={14} height={8} fill={C.brand + '15'} stroke={C.brand} strokeWidth={0.5} rx={1} />
          <text x={legendX + 18} y={legendY + 54} fill={C.muted} fontSize={9} fontFamily="Inter, system-ui">ATR Band</text>
        </>
      )}
    </motion.svg>
  );
}

export default EquityCurve;
