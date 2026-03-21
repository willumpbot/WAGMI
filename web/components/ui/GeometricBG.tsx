'use client';
import React, { useMemo } from 'react';
import { C } from '../../src/theme';

type GeoVariant = 'hexagon' | 'diamond' | 'wave' | 'circuit';

interface GeometricBGProps {
  variant?: GeoVariant;
  opacity?: number;
  color?: string;
  animated?: boolean;
}

function HexagonPattern({ color, opacity }: { color: string; opacity: number }) {
  const hexSize = 60;
  const h = hexSize * Math.sqrt(3) / 2;
  return (
    <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, opacity }}>
      <defs>
        <pattern id="hex-pattern" width={hexSize * 1.5} height={h * 2} patternUnits="userSpaceOnUse">
          <polygon
            points={`${hexSize},0 ${hexSize * 1.5},${h * 0.5} ${hexSize * 1.5},${h * 1.5} ${hexSize},${h * 2} ${hexSize * 0.5},${h * 1.5} ${hexSize * 0.5},${h * 0.5}`}
            fill="none"
            stroke={color}
            strokeWidth="0.5"
          />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#hex-pattern)" />
    </svg>
  );
}

function DiamondPattern({ color, opacity }: { color: string; opacity: number }) {
  return (
    <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, opacity }}>
      <defs>
        <pattern id="diamond-pattern" width="40" height="40" patternUnits="userSpaceOnUse">
          <polygon points="20,0 40,20 20,40 0,20" fill="none" stroke={color} strokeWidth="0.5" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#diamond-pattern)" />
    </svg>
  );
}

function WavePattern({ color, opacity }: { color: string; opacity: number }) {
  return (
    <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, opacity }} preserveAspectRatio="none">
      <defs>
        <pattern id="wave-pattern" width="120" height="30" patternUnits="userSpaceOnUse">
          <path
            d="M0 15 Q30 0 60 15 Q90 30 120 15"
            fill="none"
            stroke={color}
            strokeWidth="0.5"
          />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#wave-pattern)" />
    </svg>
  );
}

function CircuitPattern({ color, opacity }: { color: string; opacity: number }) {
  return (
    <svg width="100%" height="100%" style={{ position: 'absolute', inset: 0, opacity }}>
      <defs>
        <pattern id="circuit-pattern" width="80" height="80" patternUnits="userSpaceOnUse">
          <path d="M0 40 H30 M50 40 H80 M40 0 V30 M40 50 V80" fill="none" stroke={color} strokeWidth="0.5" />
          <circle cx="40" cy="40" r="3" fill="none" stroke={color} strokeWidth="0.5" />
          <circle cx="40" cy="40" r="1" fill={color} />
          <circle cx="0" cy="40" r="1" fill={color} opacity="0.5" />
          <circle cx="80" cy="40" r="1" fill={color} opacity="0.5" />
          <circle cx="40" cy="0" r="1" fill={color} opacity="0.5" />
          <circle cx="40" cy="80" r="1" fill={color} opacity="0.5" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#circuit-pattern)" />
    </svg>
  );
}

export function GeometricBG({
  variant = 'hexagon',
  opacity = 0.04,
  color,
  animated = false,
}: GeometricBGProps) {
  const c = color || C.brand;
  const wrapStyle: React.CSSProperties = {
    position: 'absolute',
    inset: 0,
    pointerEvents: 'none',
    zIndex: 0,
    overflow: 'hidden',
    ...(animated ? { animation: 'tickerScroll 60s linear infinite' } : {}),
  };

  return (
    <div style={wrapStyle} aria-hidden="true">
      {variant === 'hexagon' && <HexagonPattern color={c} opacity={opacity} />}
      {variant === 'diamond' && <DiamondPattern color={c} opacity={opacity} />}
      {variant === 'wave' && <WavePattern color={c} opacity={opacity} />}
      {variant === 'circuit' && <CircuitPattern color={c} opacity={opacity} />}
    </div>
  );
}

export default GeometricBG;
