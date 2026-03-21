'use client';

import React from 'react';
import { C, R, F } from '../../src/theme';

export type BadgeVariant = 'bull' | 'bear' | 'warn' | 'info' | 'muted' | 'brand';

export interface BadgeProps {
  variant: BadgeVariant;
  pulse?: boolean;
  children: React.ReactNode;
}

const variantColors: Record<BadgeVariant, { bg: string; text: string }> = {
  bull: { bg: C.bullMuted, text: C.bull },
  bear: { bg: C.bearMuted, text: C.bear },
  warn: { bg: C.warnMuted, text: C.warn },
  info: { bg: C.infoMuted, text: C.info },
  muted: { bg: C.faint, text: C.muted },
  brand: { bg: C.brandMuted, text: C.brand },
};

export function Badge({ variant, pulse = false, children }: BadgeProps) {
  const colors = variantColors[variant];

  const style: React.CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    padding: '2px 10px',
    borderRadius: R.pill,
    background: colors.bg,
    color: colors.text,
    fontSize: F.xs,
    fontWeight: 600,
    lineHeight: '20px',
    whiteSpace: 'nowrap',
    animation: pulse ? 'badgePulse 2s ease-in-out infinite' : undefined,
  };

  return (
    <>
      {pulse && (
        <style>{`
          @keyframes badgePulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
          }
        `}</style>
      )}
      <span style={style}>{children}</span>
    </>
  );
}

export default Badge;
