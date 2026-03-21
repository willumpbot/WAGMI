'use client';

import React from 'react';
import { C, R } from '../../src/theme';

export interface SkeletonProps {
  w?: string | number;
  h?: string | number;
  rounded?: number;
  variant?: 'text' | 'card' | 'chart';
}

const variantDefaults: Record<string, { width: string | number; height: string | number; borderRadius: number }> = {
  text: { width: '100%', height: 14, borderRadius: R.xs },
  card: { width: '100%', height: 120, borderRadius: R.lg },
  chart: { width: '100%', height: 200, borderRadius: R.lg },
};

export function Skeleton({ w, h, rounded, variant = 'text' }: SkeletonProps) {
  const defaults = variantDefaults[variant];

  const style: React.CSSProperties = {
    width: w ?? defaults.width,
    height: h ?? defaults.height,
    borderRadius: rounded ?? defaults.borderRadius,
    background: variant === 'chart'
      ? `repeating-linear-gradient(
          0deg,
          ${C.faint} 0px,
          ${C.faint} 1px,
          transparent 1px,
          transparent 40px
        ), linear-gradient(90deg, ${C.border} 0%, ${C.faint} 50%, ${C.border} 100%)`
      : undefined,
  };

  return <div className="skeleton" style={style} />;
}

export default Skeleton;
