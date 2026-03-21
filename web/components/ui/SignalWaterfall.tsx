'use client';
import React, { useMemo } from 'react';
import { C, R, F, SP, Glass, alpha } from '../../src/theme';

interface Gate {
  label: string;
  note?: string;
  color: string;
  passRate?: number;
}

interface SignalWaterfallProps {
  gates?: Gate[];
  compact?: boolean;
}

const DEFAULT_GATES: Gate[] = [
  { label: 'Signals Generated', color: C.brand, passRate: 1.0 },
  { label: 'Validity Check', color: C.brand, passRate: 0.85 },
  { label: 'Circuit Breaker', color: C.info, passRate: 0.95 },
  { label: 'Position Limits', color: C.info, passRate: 0.90 },
  { label: 'Leverage Check', color: C.warn, passRate: 0.80 },
  { label: 'Liquidation Safety', color: C.warn, passRate: 0.90 },
  { label: 'Position Sizing', color: C.bull, passRate: 0.95 },
  { label: 'AI Critic Review', color: C.purple, passRate: 0.60 },
  { label: 'EXECUTE', color: C.bull, passRate: 1.0 },
];

export function SignalWaterfall({ gates = DEFAULT_GATES, compact = false }: SignalWaterfallProps) {
  const barHeight = compact ? 28 : 36;
  const gap = compact ? 4 : 8;
  const totalHeight = gates.length * (barHeight + gap);

  return (
    <div style={{ position: 'relative', width: '100%', height: totalHeight }}>
      {/* Vertical flow line */}
      <div style={{
        position: 'absolute',
        left: 16,
        top: barHeight / 2,
        bottom: barHeight / 2,
        width: 2,
        background: `linear-gradient(180deg, ${C.brand}, ${C.bull})`,
        opacity: 0.2,
        borderRadius: 1,
      }} />

      {gates.map((gate, i) => {
        const isLast = i === gates.length - 1;
        const widthPct = gate.passRate != null
          ? 40 + gate.passRate * 55
          : 70 + Math.random() * 25;

        return (
          <div
            key={i}
            className="fade-in"
            style={{
              position: 'relative',
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              marginBottom: gap,
              animationDelay: `${i * 0.06}s`,
            }}
          >
            {/* Node dot */}
            <div style={{
              flexShrink: 0,
              width: 10,
              height: 10,
              marginLeft: 12,
              borderRadius: '50%',
              background: gate.color,
              boxShadow: `0 0 8px ${alpha(gate.color.startsWith('#') ? gate.color : C.brand, 0.4)}`,
              zIndex: 1,
            }} />

            {/* Gate bar */}
            <div style={{
              flex: 1,
              position: 'relative',
              height: barHeight,
              borderRadius: R.sm,
              overflow: 'hidden',
            }}>
              {/* Background track */}
              <div style={{
                position: 'absolute',
                inset: 0,
                background: alpha(gate.color.startsWith('#') ? gate.color : C.brand, 0.06),
                border: `1px solid ${alpha(gate.color.startsWith('#') ? gate.color : C.brand, 0.12)}`,
                borderRadius: R.sm,
              }} />
              {/* Fill bar */}
              <div style={{
                position: 'absolute',
                top: 0,
                left: 0,
                bottom: 0,
                width: `${widthPct}%`,
                background: `linear-gradient(90deg, ${alpha(gate.color.startsWith('#') ? gate.color : C.brand, 0.2)}, ${alpha(gate.color.startsWith('#') ? gate.color : C.brand, 0.08)})`,
                borderRadius: R.sm,
                transition: 'width 0.6s ease',
              }} />
              {/* Label */}
              <div style={{
                position: 'relative',
                height: '100%',
                display: 'flex',
                alignItems: 'center',
                padding: `0 ${SP[3]}px`,
                zIndex: 1,
              }}>
                <span style={{
                  fontSize: compact ? F.xs : F.sm,
                  fontWeight: isLast ? 800 : 600,
                  color: isLast ? gate.color : C.textSub,
                  letterSpacing: isLast ? '0.04em' : undefined,
                }}>
                  {gate.label}
                </span>
                {gate.passRate != null && !isLast && (
                  <span style={{
                    marginLeft: 'auto',
                    fontSize: F.xs,
                    color: C.muted,
                    fontFamily: "'JetBrains Mono', monospace",
                  }}>
                    {(gate.passRate * 100).toFixed(0)}%
                  </span>
                )}
              </div>
            </div>
          </div>
        );
      })}

      {/* Animated pulse dots flowing down */}
      {[0, 1, 2].map(i => (
        <div
          key={`pulse-${i}`}
          style={{
            position: 'absolute',
            left: 14,
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: C.brand,
            opacity: 0.6,
            filter: 'blur(1px)',
            animation: `particleDrift ${3 + i}s linear infinite`,
            animationDelay: `${i * 1.2}s`,
            top: 0,
            zIndex: 2,
          }}
        />
      ))}
    </div>
  );
}

export default SignalWaterfall;
