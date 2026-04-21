'use client';

import React from 'react';
import { C } from '../../src/theme';

export type StatusKind = 'live' | 'stale' | 'error' | 'idle';

export interface StatusDotProps {
  kind: StatusKind;
  size?: number;
  label?: string;
  title?: string;
}

/**
 * Pulsing status dot. green=live+fresh, amber=stale, red=error, gray=idle.
 * Use as a universal freshness indicator on any live data source.
 */
export function StatusDot({ kind, size = 7, label, title }: StatusDotProps) {
  const palette: Record<StatusKind, { color: string; bg: string; label: string }> = {
    live:  { color: C.bull,  bg: 'rgba(0,204,136,0.12)', label: 'LIVE' },
    stale: { color: C.warn,  bg: 'rgba(255,170,0,0.12)', label: 'STALE' },
    error: { color: C.bear,  bg: 'rgba(255,68,102,0.12)', label: 'ERROR' },
    idle:  { color: C.muted, bg: 'rgba(107,107,123,0.10)', label: 'IDLE' },
  };
  const tone = palette[kind];

  if (label === undefined) {
    // Bare dot (for inline use next to a card title)
    return (
      <div
        title={title || tone.label}
        className={kind === 'live' ? 'live-dot' : undefined}
        style={{
          width: size,
          height: size,
          borderRadius: '50%',
          background: tone.color,
          flexShrink: 0,
          display: 'inline-block',
        }}
      />
    );
  }

  return (
    <div
      title={title || tone.label}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 10px',
        background: tone.bg,
        border: `1px solid ${tone.color}25`,
        borderRadius: 999,
      }}
    >
      <div
        className={kind === 'live' ? 'live-dot' : undefined}
        style={{ width: size, height: size, borderRadius: '50%', background: tone.color }}
      />
      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          color: tone.color,
          letterSpacing: 0.6,
          textTransform: 'uppercase',
          whiteSpace: 'nowrap',
        }}
      >
        {label || tone.label}
      </span>
    </div>
  );
}

export default StatusDot;
