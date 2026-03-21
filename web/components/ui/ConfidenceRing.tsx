'use client';
import React, { useEffect, useState } from 'react';
import { C, F, alpha } from '../../src/theme';

interface ConfidenceRingProps {
  value: number;          // 0-100 or 0-1 (auto-detected)
  label?: string;
  size?: number;
  strokeWidth?: number;
  color?: string;
  showTicks?: boolean;
  animated?: boolean;
}

function getColor(pct: number, customColor?: string): string {
  if (customColor) return customColor;
  if (pct >= 70) return C.bull;
  if (pct >= 40) return C.warn;
  return C.bear;
}

export function ConfidenceRing({
  value,
  label,
  size = 120,
  strokeWidth = 6,
  color,
  showTicks = true,
  animated = true,
}: ConfidenceRingProps) {
  // Normalize: if value <= 1, treat as fraction
  const pct = value > 1 ? value : value * 100;
  const displayVal = Math.round(pct);
  const ringColor = getColor(pct, color);

  const [animatedPct, setAnimatedPct] = useState(animated ? 0 : pct);

  useEffect(() => {
    if (!animated) { setAnimatedPct(pct); return; }
    const timeout = setTimeout(() => setAnimatedPct(pct), 100);
    return () => clearTimeout(timeout);
  }, [pct, animated]);

  const radius = (size - strokeWidth * 2) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (animatedPct / 100) * circumference;
  const center = size / 2;

  const tickCount = 10;
  const ticks = Array.from({ length: tickCount }, (_, i) => {
    const angle = (i / tickCount) * 360 - 90;
    const rad = (angle * Math.PI) / 180;
    const inner = radius - strokeWidth / 2 - 3;
    const outer = radius - strokeWidth / 2 - 1;
    return {
      x1: center + Math.cos(rad) * inner,
      y1: center + Math.sin(rad) * inner,
      x2: center + Math.cos(rad) * outer,
      y2: center + Math.sin(rad) * outer,
    };
  });

  return (
    <div style={{
      width: size,
      height: size,
      position: 'relative',
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
    }}>
      {/* Glow halo */}
      <div style={{
        position: 'absolute',
        inset: -8,
        borderRadius: '50%',
        background: `radial-gradient(circle, ${alpha(ringColor.startsWith('#') ? ringColor : C.brand, 0.08 + (pct / 100) * 0.1)} 0%, transparent 70%)`,
      }} />

      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        {/* Background track */}
        <circle
          cx={center} cy={center} r={radius}
          fill="none"
          stroke={C.faint}
          strokeWidth={strokeWidth}
          opacity={0.3}
        />
        {/* Progress arc */}
        <circle
          cx={center} cy={center} r={radius}
          fill="none"
          stroke={ringColor}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{
            transition: animated ? 'stroke-dashoffset 1s cubic-bezier(0.22, 1, 0.36, 1), stroke 0.3s' : undefined,
            filter: `drop-shadow(0 0 4px ${alpha(ringColor.startsWith('#') ? ringColor : C.brand, 0.3)})`,
          }}
        />
        {/* Tick marks */}
        {showTicks && ticks.map((t, i) => (
          <line
            key={i}
            x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2}
            stroke={C.muted}
            strokeWidth="0.5"
            opacity="0.4"
          />
        ))}
      </svg>

      {/* Center text */}
      <div style={{
        position: 'absolute',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
      }}>
        <span style={{
          fontSize: size > 100 ? F['2xl'] : F.lg,
          fontWeight: 800,
          color: ringColor,
          fontFamily: "'JetBrains Mono', monospace",
          fontVariantNumeric: 'tabular-nums',
          lineHeight: 1,
        }}>
          {displayVal}
        </span>
        <span style={{
          fontSize: size > 100 ? F.xs : 9,
          color: C.muted,
          fontWeight: 600,
          marginTop: 2,
        }}>
          {label || '%'}
        </span>
      </div>
    </div>
  );
}

export default ConfidenceRing;
