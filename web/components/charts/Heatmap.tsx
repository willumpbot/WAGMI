'use client';

import React, { useId } from 'react';
import { motion } from 'framer-motion';
import { C, R, F } from '../../src/theme';
import { cellFade, staggerContainer } from '../../src/animations';

/** Enhanced cell animation: scale up with a brief intensity burst, then settle */
const cellPulse: import('framer-motion').Variants = {
  hidden: { opacity: 0, scale: 0.7 },
  show: {
    opacity: 1,
    scale: 1,
    transition: {
      duration: 0.4,
      ease: [0.22, 1, 0.36, 1] as [number, number, number, number],
    },
  },
};

// ── Types ────────────────────────────────────────────────────────────────────

export type HeatmapDatum = {
  row: string;
  col: string;
  value: number;
};

export type HeatmapProps = {
  data: HeatmapDatum[];
  rows: string[];
  cols: string[];
  colorScale?: (v: number) => string;
  cellSize?: number;
};

// ── Default color scale ──────────────────────────────────────────────────────

function defaultColorScale(v: number): string {
  // Expects v in range roughly -1..1 (or any range; we clamp to [-1,1])
  const clamped = Math.max(-1, Math.min(1, v));
  if (clamped >= 0.8) return C.heatBull3;
  if (clamped >= 0.5) return C.heatBull2;
  if (clamped >= 0.2) return C.heatBull1;
  if (clamped > -0.2) return C.heatNeutral;
  if (clamped > -0.5) return C.heatBear1;
  if (clamped > -0.8) return C.heatBear2;
  return C.heatBear3;
}

// ── Component ────────────────────────────────────────────────────────────────

export function Heatmap({
  data,
  rows,
  cols,
  colorScale = defaultColorScale,
  cellSize = 46,
}: HeatmapProps) {
  if (!data.length) return null;

  // Build lookup map
  const lookup = new Map<string, number>();
  data.forEach((d) => lookup.set(`${d.row}__${d.col}`, d.value));

  const cellGap = 3;
  const labelW = 48;
  const labelH = 20;

  return (
    <motion.div
      style={{ overflowX: 'auto', width: '100%' }}
      initial="hidden"
      animate="show"
      variants={staggerContainer}
    >
      <table style={{ borderCollapse: 'separate', borderSpacing: cellGap }}>
        <thead>
          <tr>
            <th style={{ width: labelW, padding: '4px 6px', fontSize: 10, color: C.muted, textAlign: 'right' }} />
            {cols.map((col) => (
              <th
                key={col}
                style={{
                  padding: '4px 2px',
                  fontSize: 9,
                  color: C.muted,
                  fontWeight: 600,
                  textAlign: 'center',
                  minWidth: cellSize,
                }}
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={row}>
              <td
                style={{
                  padding: '2px 8px 2px 0',
                  fontSize: 10,
                  color: C.muted,
                  fontWeight: 600,
                  textAlign: 'right',
                  whiteSpace: 'nowrap',
                }}
              >
                {row}
              </td>
              {cols.map((col, ci) => {
                const val = lookup.get(`${row}__${col}`);
                const hasValue = val !== undefined;
                const intensity = hasValue ? Math.abs(val) : 0;
                // Hot cells (|value| > 0.5) get a subtle breathing glow
                const isHot = intensity > 0.5;
                const cellColor = hasValue ? colorScale(val) : C.surface;

                return (
                  <td key={col} style={{ padding: 1 }}>
                    <motion.div
                      variants={cellPulse}
                      transition={{ delay: (ri * cols.length + ci) * 0.025 }}
                      title={`${row} / ${col}: ${hasValue ? val.toFixed(2) : 'N/A'}`}
                      style={{
                        width: cellSize,
                        height: 30,
                        borderRadius: 4,
                        background: cellColor,
                        border: `1px solid ${hasValue ? 'rgba(255,255,255,0.08)' : C.border}`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: 9,
                        fontWeight: 700,
                        color: hasValue ? '#fff' : C.muted,
                        boxShadow: isHot
                          ? `0 0 ${8 + intensity * 10}px ${cellColor}40, inset 0 1px 0 rgba(255,255,255,0.1)`
                          : 'none',
                        transition: 'box-shadow 0.3s ease, background 0.3s ease',
                      }}
                      whileHover={hasValue ? {
                        scale: 1.15,
                        boxShadow: `0 0 20px ${cellColor}60, inset 0 1px 0 rgba(255,255,255,0.15)`,
                        zIndex: 10,
                        transition: { duration: 0.2 },
                      } : undefined}
                    >
                      {hasValue ? val.toFixed(1) : '\u2014'}
                    </motion.div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </motion.div>
  );
}

export default Heatmap;
