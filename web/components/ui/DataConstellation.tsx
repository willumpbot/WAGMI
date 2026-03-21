'use client';
import React, { useMemo } from 'react';
import { C } from '../../src/theme';

interface DataConstellationProps {
  pointCount?: number;
  connectionDistance?: number;
  color?: string;
  width?: number | string;
  height?: number | string;
  opacity?: number;
}

export function DataConstellation({
  pointCount = 25,
  connectionDistance = 25,
  color,
  width = '100%',
  height = '100%',
  opacity = 0.08,
}: DataConstellationProps) {
  const c = color || C.brand;

  const { points, lines } = useMemo(() => {
    const seed = (n: number) => {
      let s = n * 9301 + 49297;
      return ((s % 233280) / 233280);
    };
    const pts = Array.from({ length: pointCount }, (_, i) => ({
      x: seed(i * 2) * 100,
      y: seed(i * 2 + 1) * 100,
      size: 1 + seed(i * 3) * 2,
      delay: seed(i * 5) * 8,
      dur: 6 + seed(i * 7) * 10,
    }));

    const lns: { x1: number; y1: number; x2: number; y2: number; dist: number }[] = [];
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const dx = pts[i].x - pts[j].x;
        const dy = pts[i].y - pts[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < connectionDistance) {
          lns.push({ x1: pts[i].x, y1: pts[i].y, x2: pts[j].x, y2: pts[j].y, dist });
        }
      }
    }
    return { points: pts, lines: lns };
  }, [pointCount, connectionDistance]);

  return (
    <div
      aria-hidden="true"
      style={{
        position: 'absolute',
        inset: 0,
        width,
        height,
        opacity,
        pointerEvents: 'none',
        zIndex: 0,
        overflow: 'hidden',
      }}
    >
      <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{ width: '100%', height: '100%' }}>
        {lines.map((l, i) => (
          <line
            key={`l-${i}`}
            x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2}
            stroke={c}
            strokeWidth="0.15"
            opacity={1 - l.dist / connectionDistance}
          />
        ))}
        {points.map((p, i) => (
          <circle key={`p-${i}`} cx={p.x} cy={p.y} r={p.size * 0.3} fill={c} opacity="0.6">
            <animateTransform
              attributeName="transform"
              type="translate"
              values={`0 0; ${(i % 2 === 0 ? 1 : -1) * 0.5} ${(i % 3 === 0 ? -1 : 1) * 0.3}; 0 0`}
              dur={`${p.dur}s`}
              begin={`${p.delay}s`}
              repeatCount="indefinite"
            />
          </circle>
        ))}
      </svg>
    </div>
  );
}

export default DataConstellation;
