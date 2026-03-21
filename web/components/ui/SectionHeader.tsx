'use client';

import React from 'react';
import { C, F, SP } from '../../src/theme';

export interface SectionHeaderProps {
  label: string;
  action?: React.ReactNode;
}

export function SectionHeader({ label, action }: SectionHeaderProps) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: SP[3],
        marginBottom: SP[4],
      }}
    >
      <span
        style={{
          fontSize: F.xs,
          fontWeight: 600,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: C.muted,
          whiteSpace: 'nowrap',
        }}
      >
        {label}
      </span>
      <div
        style={{
          flex: 1,
          height: 1,
          background: `linear-gradient(90deg, ${C.border} 0%, rgba(99,102,241,0.08) 40%, transparent 100%)`,
        }}
      />
      {action && <div style={{ flexShrink: 0 }}>{action}</div>}
    </div>
  );
}

export default SectionHeader;
