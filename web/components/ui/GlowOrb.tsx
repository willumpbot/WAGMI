'use client';
import React from 'react';

interface GlowOrbProps {
  color?: string;
  size?: number;
  top?: string;
  left?: string;
  right?: string;
  bottom?: string;
  duration?: number;
  delay?: number;
  blur?: number;
  opacity?: number;
}

export function GlowOrb({
  color = 'rgba(99,102,241,0.15)',
  size = 300,
  top,
  left,
  right,
  bottom,
  duration = 15,
  delay = 0,
  blur = 80,
  opacity = 1,
}: GlowOrbProps) {
  return (
    <div
      className="morphing-blob"
      style={{
        background: color,
        width: size,
        height: size,
        top, left, right, bottom,
        filter: `blur(${blur}px)`,
        opacity,
        animationDuration: `${duration}s`,
        animationDelay: `${delay}s`,
        zIndex: 0,
      }}
    />
  );
}

export default GlowOrb;
