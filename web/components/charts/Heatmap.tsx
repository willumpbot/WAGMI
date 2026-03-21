'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { C, R, F } from '../../src/theme';
import { cellFade, staggerContainer } from '../../src/animations';

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

                return (
                  <td key={col} style={{ padding: 1 }}>
                    <motion.div
                      variants={cellFade}
                      transition={{ delay: (ri * cols.length + ci) * 0.02 }}
                      title={`${row} / ${col}: ${hasValue ? val.toFixed(2) : 'N/A'}`}
                      style={{
                        width: cellSize,
                        height: 30,
                        borderRadius: 4,
                        background: hasValue ? colorScale(val) : C.surface,
                        border: `1px solid ${C.border}`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        fontSize: 9,
                        fontWeight: 700,
                        color: hasValue ? '#fff' : C.muted,
                      }}
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
