'use client';
import React, { useRef, useState, useCallback } from 'react';
import { C, R, Glass } from '../../src/theme';

interface DepthStackProps {
  layers?: number;
  children: React.ReactNode;
  style?: React.CSSProperties;
}

export function DepthStack({ layers = 3, children, style }: DepthStackProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [offset, setOffset] = useState({ x: 0, y: 0 });

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
    const y = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
    setOffset({ x, y });
  }, []);

  const handleMouseLeave = useCallback(() => {
    setOffset({ x: 0, y: 0 });
  }, []);

  const layerElements = Array.from({ length: layers - 1 }, (_, i) => {
    const depth = (i + 1) * 2;
    const blur = (i + 1) * 2;
    const opacityVal = 0.04 - i * 0.01;
    const shift = depth * 0.8;

    return (
      <div
        key={i}
        style={{
          position: 'absolute',
          inset: 0,
          borderRadius: R.lg,
          background: `rgba(26,34,54,${opacityVal})`,
          border: '1px solid rgba(255,255,255,0.03)',
          transform: `translate(${offset.x * shift}px, ${offset.y * shift}px)`,
          filter: `blur(${blur}px)`,
          transition: 'transform 0.3s ease-out',
          zIndex: -1 - i,
        }}
      />
    );
  });

  return (
    <div
      ref={containerRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      style={{
        position: 'relative',
        ...style,
      }}
    >
      {layerElements}
      <div style={{ position: 'relative', zIndex: 1 }}>
        {children}
      </div>
    </div>
  );
}

export default DepthStack;
