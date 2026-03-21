'use client';

import React from 'react';
import { SP } from '../../src/theme';

/* ── Stack (vertical) ─────────────────────────────────────────────────────── */

export interface StackProps {
  gap?: number;
  align?: string;
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export function Stack({ gap = 4, align, children, style }: StackProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: SP[gap as keyof typeof SP] ?? gap,
        alignItems: align,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/* ── Row (horizontal) ─────────────────────────────────────────────────────── */

export interface RowProps {
  gap?: number;
  align?: string;
  justify?: string;
  wrap?: boolean;
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export function Row({ gap = 3, align = 'center', justify, wrap, children, style }: RowProps) {
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'row',
        gap: SP[gap as keyof typeof SP] ?? gap,
        alignItems: align,
        justifyContent: justify,
        flexWrap: wrap ? 'wrap' : undefined,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/* ── Grid ──────────────────────────────────────────────────────────────────── */

export interface GridProps {
  cols?: number;
  gap?: number;
  minChildWidth?: number;
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export function Grid({ cols, gap = 4, minChildWidth, children, style }: GridProps) {
  const gridTemplate = minChildWidth
    ? `repeat(auto-fit, minmax(${minChildWidth}px, 1fr))`
    : cols
      ? `repeat(${cols}, 1fr)`
      : undefined;

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: gridTemplate,
        gap: SP[gap as keyof typeof SP] ?? gap,
        ...style,
      }}
    >
      {children}
    </div>
  );
}

export default Stack;
