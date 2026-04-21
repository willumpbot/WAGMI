import React from 'react';

type Props = {
  width?: number | string;
  height?: number | string;
  radius?: number;
  style?: React.CSSProperties;
};

/**
 * Elegant loading shimmer. Drop-in replacement for static Skeleton.
 * Uses a subtle diagonal gradient sweep — matches dark theme without glare.
 */
export default function Shimmer({ width = '100%', height = 16, radius = 6, style }: Props) {
  return (
    <div
      style={{
        width,
        height,
        borderRadius: radius,
        background: 'linear-gradient(90deg, rgba(255,255,255,0.03) 0%, rgba(255,255,255,0.08) 50%, rgba(255,255,255,0.03) 100%)',
        backgroundSize: '200% 100%',
        animation: 'shimmer-sweep 1.4s ease-in-out infinite',
        ...style,
      }}
    >
      <style>{`
        @keyframes shimmer-sweep {
          0%   { background-position: 100% 0; }
          100% { background-position: -100% 0; }
        }
      `}</style>
    </div>
  );
}

/** A stack of shimmer lines — useful for text blocks or list loading states. */
export function ShimmerLines({ count = 3, lineHeight = 12, gap = 8 }: { count?: number; lineHeight?: number; gap?: number }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap }}>
      {Array.from({ length: count }).map((_, i) => (
        <Shimmer
          key={i}
          height={lineHeight}
          width={i === count - 1 ? '60%' : '100%'}
          radius={3}
        />
      ))}
    </div>
  );
}
