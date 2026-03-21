'use client';
import React, { useMemo } from 'react';

interface ParticleFieldProps {
  count?: number;
  color?: string;
  colors?: string[];
  maxDuration?: number;
  minDuration?: number;
}

export function ParticleField({
  count = 30,
  color,
  colors = ['rgba(99,102,241,0.4)', 'rgba(168,85,247,0.3)', 'rgba(6,182,212,0.3)'],
  maxDuration = 18,
  minDuration = 10,
}: ParticleFieldProps) {
  const particles = useMemo(() => {
    return Array.from({ length: count }, (_, i) => {
      const c = color || colors[i % colors.length];
      const dur = minDuration + Math.random() * (maxDuration - minDuration);
      const delay = Math.random() * dur;
      const left = Math.random() * 100;
      const bottom = -(Math.random() * 20);
      const size = 1.5 + Math.random() * 2;
      return { key: i, c, dur, delay, left, bottom, size };
    });
  }, [count, color, colors, maxDuration, minDuration]);

  return (
    <div className="particle-field" aria-hidden="true">
      {particles.map((p) => (
        <div
          key={p.key}
          className="particle"
          style={{
            left: `${p.left}%`,
            bottom: `${p.bottom}%`,
            width: p.size,
            height: p.size,
            background: p.c,
            '--duration': `${p.dur}s`,
            '--delay': `${p.delay}s`,
          } as React.CSSProperties}
        />
      ))}
    </div>
  );
}

export default ParticleField;
