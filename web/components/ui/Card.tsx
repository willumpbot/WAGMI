'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { C, R, S, Glass } from '../../src/theme';
import { fadeUp, etherealFloat, magneticHover, luminousHover, hoverGlow } from '../../src/animations';

type GlassVariant = 'glass' | 'crystal' | 'liquid' | 'frosted' | 'diamond' | 'void';

export interface CardProps {
  accent?: string;
  /** Glass surface variant — controls blur, opacity, and inner reflections */
  variant?: GlassVariant;
  /** Legacy: if true uses Glass.card (same as variant='glass') */
  glass?: boolean;
  /** Hover effect style */
  hover?: boolean | 'magnetic' | 'luminous' | 'glow';
  /** Animated prismatic border (rainbow edge rotation) */
  prismatic?: boolean;
  /** Refraction edge effect (chromatic top edge highlight) */
  refraction?: boolean;
  /** Breathing glow animation */
  breathe?: boolean;
  delay?: number;
  style?: React.CSSProperties;
  className?: string;
  children: React.ReactNode;
}

const GLASS_MAP: Record<GlassVariant, React.CSSProperties> = {
  glass: Glass.card,
  crystal: Glass.crystal,
  liquid: Glass.liquid,
  frosted: Glass.frosted,
  diamond: Glass.diamond,
  void: Glass.void,
};

function getHoverProps(hover: CardProps['hover']) {
  if (!hover) return {};
  if (hover === 'magnetic') return magneticHover;
  if (hover === 'luminous') return luminousHover;
  return hoverGlow;
}

export function Card({
  accent,
  variant,
  glass = true,
  hover = false,
  prismatic = false,
  refraction = false,
  breathe = false,
  delay = 0,
  style,
  className,
  children,
}: CardProps) {
  // Determine glass surface
  const surfaceStyle = variant
    ? GLASS_MAP[variant]
    : glass
      ? Glass.card
      : { background: C.card, border: `1px solid ${C.border}` };

  // Build className list
  const classes = [
    className,
    prismatic && 'prismatic-border',
    refraction && 'refraction-edge',
    breathe && 'breathe-slow',
  ].filter(Boolean).join(' ') || undefined;

  const baseStyle: React.CSSProperties = {
    position: 'relative',
    borderRadius: R.lg,
    overflow: 'hidden',
    ...surfaceStyle,
    boxShadow: variant === 'diamond' || variant === 'crystal'
      ? (GLASS_MAP[variant!] as any).boxShadow
      : S.md,
    ...style,
  };

  return (
    <motion.div
      className={classes}
      style={baseStyle}
      variants={variant === 'diamond' || variant === 'crystal' ? etherealFloat : fadeUp}
      initial="hidden"
      animate="show"
      transition={{ delay }}
      {...getHoverProps(hover)}
    >
      {/* Accent stripe */}
      {accent && (
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: 2,
            background: accent,
            zIndex: 2,
          }}
        />
      )}
      {children}
    </motion.div>
  );
}

export default Card;
