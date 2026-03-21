'use client';
import React from 'react';

interface LightBeamProps {
  speed?: number;
  angle?: number;
  opacity?: number;
  color?: string;
}

export function LightBeam({
  speed = 8,
  angle = 15,
  opacity = 0.02,
  color = 'rgba(255,255,255',
}: LightBeamProps) {
  return (
    <div
      aria-hidden="true"
      style={{
        position: 'absolute',
        inset: 0,
        overflow: 'hidden',
        pointerEvents: 'none',
        zIndex: 1,
      }}
    >
      <div
        style={{
          position: 'absolute',
          top: '-50%',
          left: '-50%',
          width: '50%',
          height: '200%',
          background: `linear-gradient(90deg, transparent, ${color},${opacity}) 50%, transparent)`,
          transform: `rotate(${angle}deg)`,
          animation: `lightSweep ${speed}s ease-in-out infinite`,
        }}
      />
    </div>
  );
}

export default LightBeam;
