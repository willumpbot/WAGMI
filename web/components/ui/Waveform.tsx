'use client';
import React, { useMemo } from 'react';
import { C } from '../../src/theme';

interface WaveformProps {
  points?: number;
  amplitude?: number;
  width?: number | string;
  height?: number;
  color?: string;
  speed?: number;
  opacity?: number;
}

export function Waveform({
  points = 8,
  amplitude = 20,
  width = '100%',
  height = 80,
  color,
  speed = 4,
  opacity = 0.15,
}: WaveformProps) {
  const gradientId = useMemo(() => `wf-grad-${Math.random().toString(36).slice(2, 8)}`, []);
  const filterId = useMemo(() => `wf-glow-${Math.random().toString(36).slice(2, 8)}`, []);

  const pathD = useMemo(() => {
    const step = 100 / (points - 1);
    const pts: string[] = [];
    for (let i = 0; i < points; i++) {
      const x = i * step;
      const y = 50 + Math.sin(i * 0.8) * amplitude;
      if (i === 0) {
        pts.push(`M ${x} ${y}`);
      } else {
        const prevX = (i - 1) * step;
        const cpx = prevX + step / 2;
        const prevY = 50 + Math.sin((i - 1) * 0.8) * amplitude;
        pts.push(`C ${cpx} ${prevY}, ${cpx} ${y}, ${x} ${y}`);
      }
    }
    return pts.join(' ');
  }, [points, amplitude]);

  return (
    <div
      aria-hidden="true"
      style={{
        position: 'absolute',
        bottom: 0,
        left: 0,
        width,
        height,
        opacity,
        pointerEvents: 'none',
        zIndex: 0,
      }}
    >
      <svg
        viewBox={`0 0 100 100`}
        preserveAspectRatio="none"
        style={{ width: '100%', height: '100%' }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor={color || C.brand} />
            <stop offset="50%" stopColor={C.cyan || '#06b6d4'} />
            <stop offset="100%" stopColor={C.purple} />
          </linearGradient>
          <filter id={filterId}>
            <feGaussianBlur stdDeviation="1.5" />
          </filter>
        </defs>
        <path
          d={pathD}
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth="0.8"
          filter={`url(#${filterId})`}
        >
          <animateTransform
            attributeName="transform"
            type="translate"
            values="0 0; 2 -3; -1 2; 0 0"
            dur={`${speed}s`}
            repeatCount="indefinite"
          />
        </path>
        <path
          d={pathD}
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth="0.3"
        >
          <animateTransform
            attributeName="transform"
            type="translate"
            values="0 0; -2 2; 1 -3; 0 0"
            dur={`${speed * 1.3}s`}
            repeatCount="indefinite"
          />
        </path>
      </svg>
    </div>
  );
}

export default Waveform;
