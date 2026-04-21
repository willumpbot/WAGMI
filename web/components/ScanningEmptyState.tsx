import React from 'react';
import { C } from '../src/theme';

type Props = {
  label?: string;
  sub?: string;
  height?: number | string;
  compact?: boolean;
};

/**
 * Subtle empty-state placeholder used when an endpoint returns no data yet.
 * Shows a pulsing dot + short message — professional, not noisy, and reassures
 * the user that the bot is alive and scanning (vs blank space which reads as broken).
 */
export default function EmptyState({
  label = 'No data yet',
  sub = 'Bot is scanning — check back shortly',
  height,
  compact = false,
}: Props) {
  return (
    <div
      className="empty-state"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: compact ? 8 : 12,
        minHeight: height ?? (compact ? 48 : 96),
        padding: compact ? '10px 14px' : '20px 16px',
        width: '100%',
        textAlign: 'center',
        color: C.muted,
      }}
      aria-label={label}
    >
      <div
        className="empty-dot"
        style={{
          width: compact ? 6 : 8,
          height: compact ? 6 : 8,
          borderRadius: '50%',
          background: C.brand,
          opacity: 0.7,
          flexShrink: 0,
        }}
      />
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', textAlign: 'left' }}>
        <div style={{ fontSize: compact ? 11 : 12, fontWeight: 600, color: C.textSub, letterSpacing: 0.2 }}>
          {label}
        </div>
        {sub && (
          <div style={{ fontSize: compact ? 10 : 11, color: C.muted, marginTop: 2 }}>
            {sub}
          </div>
        )}
      </div>
      <style jsx>{`
        .empty-state .empty-dot {
          animation: empty-pulse 1.8s ease-in-out infinite;
        }
        @keyframes empty-pulse {
          0%, 100% { opacity: 0.35; transform: scale(0.85); }
          50% { opacity: 0.9; transform: scale(1.15); }
        }
      `}</style>
    </div>
  );
}
