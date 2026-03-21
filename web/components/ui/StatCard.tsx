'use client';

import React from 'react';
import { C, F, SP, S, alpha } from '../../src/theme';
import { Card } from './Card';
import { Skeleton } from './Skeleton';

export interface StatCardProps {
  label: string;
  value: string;
  sub?: string;
  color?: string;
  loading?: boolean;
  big?: boolean;
  trend?: 'up' | 'down' | 'flat';
  /** Use premium crystal glass variant */
  crystal?: boolean;
  /** Add breathing glow animation */
  breathe?: boolean;
}

const trendArrows: Record<string, string> = {
  up: '\u25B2',
  down: '\u25BC',
  flat: '\u25C6',
};

const trendColors: Record<string, string> = {
  up: C.bull,
  down: C.bear,
  flat: C.muted,
};

function pnlGlow(color?: string): string | undefined {
  if (color === C.bull) return S.bullGlow;
  if (color === C.bear) return S.bearGlow;
  return undefined;
}

export function StatCard({
  label,
  value,
  sub,
  color,
  loading = false,
  big = false,
  trend,
  crystal = false,
  breathe = false,
}: StatCardProps) {
  const glow = pnlGlow(color);

  // Contextual halo glow behind the value
  const haloColor = color === C.bull
    ? alpha('#16a34a', 0.06)
    : color === C.bear
      ? alpha('#dc2626', 0.06)
      : undefined;

  return (
    <Card
      variant={crystal ? 'crystal' : 'glass'}
      accent={color}
      hover="magnetic"
      breathe={breathe}
      refraction={crystal}
      style={{
        padding: `${SP[4]}px ${SP[5]}px`,
        ...(glow ? { boxShadow: glow } : {}),
      }}
    >
      {/* Contextual halo glow */}
      {haloColor && (
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            width: '80%',
            height: '80%',
            transform: 'translate(-50%, -50%)',
            background: `radial-gradient(circle, ${haloColor} 0%, transparent 70%)`,
            pointerEvents: 'none',
            zIndex: 0,
          }}
        />
      )}

      {loading ? (
        <div style={{ position: 'relative', zIndex: 1 }}>
          <Skeleton w="60%" h={12} />
          <div style={{ height: SP[2] }} />
          <Skeleton w="80%" h={big ? 28 : 22} />
          {sub !== undefined && (
            <>
              <div style={{ height: SP[1] }} />
              <Skeleton w="50%" h={11} />
            </>
          )}
        </div>
      ) : (
        <div style={{ position: 'relative', zIndex: 1 }}>
          <div
            style={{
              fontSize: F.xs,
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              color: C.muted,
              marginBottom: SP[1],
            }}
          >
            {label}
          </div>
          <div
            style={{
              display: 'flex',
              alignItems: 'baseline',
              gap: SP[2],
            }}
          >
            <span
              style={{
                fontSize: big ? F['3xl'] : F['2xl'],
                fontWeight: 700,
                color: color ?? C.text,
                fontFamily: "'JetBrains Mono', monospace",
                fontVariantNumeric: 'tabular-nums',
                lineHeight: 1.1,
                textShadow: color
                  ? `0 0 20px ${alpha(color.startsWith('#') ? color : C.brand, 0.15)}`
                  : undefined,
              }}
            >
              {value}
            </span>
            {trend && (
              <span
                style={{
                  fontSize: F.xs,
                  color: trendColors[trend],
                  lineHeight: 1,
                }}
              >
                {trendArrows[trend]}
              </span>
            )}
          </div>
          {sub && (
            <div
              style={{
                fontSize: F.xs,
                color: C.muted,
                marginTop: SP[1],
                fontFamily: "'JetBrains Mono', monospace",
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {sub}
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

export default StatCard;
