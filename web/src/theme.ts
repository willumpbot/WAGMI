import React from 'react';

/**
 * WAGMI Design System — shared tokens for all pages.
 * Import C (colours), R (radii), S (shadows), F (font sizes),
 * SP (spacing), Z (z-index), M (motion), Glass (glass surfaces),
 * BP (breakpoints), G (gradients).
 */

export const C = {
  // Brand
  brand: '#6366f1',
  brandDark: '#4f46e5',
  brandGlow: 'rgba(99,102,241,0.15)',

  // Semantic
  bull: '#16a34a',
  bullLight: '#dcfce7',
  bullMid: '#86efac',
  bear: '#dc2626',
  bearLight: '#fee2e2',
  bearMid: '#fca5a5',
  warn: '#d97706',
  warnLight: '#fef3c7',
  warnMid: '#fbbf24',
  info: '#2563eb',
  infoLight: '#dbeafe',
  infoMid: '#93c5fd',
  purple: '#7c3aed',
  purpleLight: '#ede9fe',

  // Dark surface scale (primary palette)
  bg: '#0a0f1e',
  surface: '#111827',
  surfaceHover: '#1e293b',
  card: '#1a2236',
  border: '#2d3748',
  borderBright: '#4a5568',

  // Text on dark
  text: '#f1f5f9',
  textSub: '#cbd5e1',
  muted: '#64748b',
  faint: '#334155',

  // Light surface scale (for cards / signal sections that need light bg)
  bgLight: '#f8fafc',
  surfaceLight: '#ffffff',
  cardLight: '#f1f5f9',
  borderLight: '#e2e8f0',
  textLight: '#0f172a',
  textSubLight: '#374151',
  mutedLight: '#6b7280',

  // Heatmap cells
  heatBull3: '#166534',
  heatBull2: '#15803d',
  heatBull1: '#22c55e',
  heatNeutral: '#374151',
  heatBear1: '#ef4444',
  heatBear2: '#b91c1c',
  heatBear3: '#7f1d1d',

  // Semantic muted background tints (12% alpha)
  bearMuted: 'rgba(220,38,38,.12)',
  bullMuted: 'rgba(22,163,74,.12)',
  brandMuted: 'rgba(99,102,241,.12)',
  warnMuted: 'rgba(234,179,8,.12)',
  infoMuted: 'rgba(37,99,235,.12)',

  // Extended palette — chromatic accents for prismatic effects
  cyan: '#06b6d4',
  cyanGlow: 'rgba(6,182,212,0.15)',
  rose: '#ec4899',
  roseGlow: 'rgba(236,72,153,0.15)',
  amber: '#f59e0b',
  emerald: '#10b981',
};

export const R = {
  xs: 4,
  sm: 6,
  md: 10,
  lg: 16,
  xl: 20,
  pill: 999,
} as const;

export const S = {
  sm: '0 1px 3px rgba(0,0,0,.25)',
  md: '0 4px 12px rgba(0,0,0,.3)',
  lg: '0 8px 28px rgba(0,0,0,.4)',
  glow: '0 0 20px rgba(99,102,241,.25)',
  bullGlow: '0 0 20px rgba(22,163,74,0.15), 0 4px 12px rgba(0,0,0,0.2)',
  bearGlow: '0 0 20px rgba(220,38,38,0.15), 0 4px 12px rgba(0,0,0,0.2)',
  brandGlow: '0 0 24px rgba(99,102,241,0.2), 0 4px 12px rgba(0,0,0,0.2)',
  glass: '0 8px 32px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.04)',
  // Layered depth shadows — architectural ambient occlusion
  depth1: '0 1px 2px rgba(0,0,0,0.3), 0 2px 6px rgba(0,0,0,0.2)',
  depth2: '0 2px 4px rgba(0,0,0,0.3), 0 4px 12px rgba(0,0,0,0.25), 0 8px 24px rgba(0,0,0,0.2)',
  depth3: '0 4px 8px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.25), 0 16px 48px rgba(0,0,0,0.2), 0 24px 64px rgba(0,0,0,0.15)',
  ambient: '0 0 0 1px rgba(255,255,255,0.03), 0 4px 16px rgba(0,0,0,0.3), 0 12px 40px rgba(0,0,0,0.2)',
  innerLight: 'inset 0 1px 0 rgba(255,255,255,0.08), inset 0 0 20px rgba(99,102,241,0.03)',
} as const;

export const F = {
  xs: 11,
  sm: 12,
  base: 13,
  md: 14,
  lg: 16,
  xl: 18,
  '2xl': 22,
  '3xl': 28,
  '4xl': 36,
} as const;

/** Transition shorthand */
export const T = 'transition: all 0.18s ease;';

/** Spacing scale (4px base) */
export const SP = { 0:0, 1:4, 2:8, 3:12, 4:16, 5:20, 6:24, 8:32, 10:40, 12:48, 16:64, 20:80 } as const;

/** Z-index layers */
export const Z = { base:1, dropdown:300, sidebar:350, modal:400, toast:500, tooltip:600 } as const;

/** Responsive breakpoints (px) */
export const BP = { sm:640, md:768, lg:1024, xl:1280, '2xl':1536 } as const;

/** Motion tokens for Framer Motion */
export const M = {
  fast: { duration: 0.15, ease: [0.25, 0.1, 0.25, 1] as number[] },
  normal: { duration: 0.25, ease: [0.25, 0.1, 0.25, 1] as number[] },
  slow: { duration: 0.4, ease: [0.25, 0.1, 0.25, 1] as number[] },
  spring: { type: 'spring' as const, stiffness: 300, damping: 24 },
  bouncy: { type: 'spring' as const, stiffness: 400, damping: 17 },
} as const;

/** Glass surface styles for glassmorphism — architectural depth hierarchy */
export const Glass = {
  /** Standard card — everyday content container */
  card: {
    background: 'rgba(26,34,54,0.55)',
    backdropFilter: 'blur(16px) saturate(1.4)',
    WebkitBackdropFilter: 'blur(16px) saturate(1.4)',
    border: '1px solid rgba(255,255,255,0.06)',
  } as React.CSSProperties,
  /** Navigation — slightly more opaque for readability */
  nav: {
    background: 'rgba(17,24,39,0.72)',
    backdropFilter: 'blur(20px) saturate(1.5)',
    WebkitBackdropFilter: 'blur(20px) saturate(1.5)',
    border: '1px solid rgba(255,255,255,0.04)',
  } as React.CSSProperties,
  /** Elevated — modals, popovers, overlays */
  elevated: {
    background: 'rgba(26,34,54,0.7)',
    backdropFilter: 'blur(24px) saturate(1.6)',
    WebkitBackdropFilter: 'blur(24px) saturate(1.6)',
    border: '1px solid rgba(255,255,255,0.08)',
    boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
  } as React.CSSProperties,
  /** Crystal — premium translucent surface with edge reflections */
  crystal: {
    background: 'rgba(26,34,54,0.35)',
    backdropFilter: 'blur(40px) saturate(1.8)',
    WebkitBackdropFilter: 'blur(40px) saturate(1.8)',
    border: '1px solid rgba(255,255,255,0.1)',
    boxShadow: '0 8px 32px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.08), inset 0 -1px 0 rgba(255,255,255,0.02)',
  } as React.CSSProperties,
  /** Liquid — flowing gradient glass with brightness lift */
  liquid: {
    background: 'linear-gradient(135deg, rgba(26,34,54,0.5) 0%, rgba(30,41,59,0.4) 100%)',
    backdropFilter: 'blur(32px) saturate(1.6) brightness(1.05)',
    WebkitBackdropFilter: 'blur(32px) saturate(1.6) brightness(1.05)',
    border: '1px solid rgba(255,255,255,0.08)',
    boxShadow: '0 12px 40px rgba(0,0,0,0.35), inset 0 2px 0 rgba(255,255,255,0.06)',
  } as React.CSSProperties,
  /** Frosted — deep matte glass, heavy blur */
  frosted: {
    background: 'rgba(17,24,39,0.45)',
    backdropFilter: 'blur(60px) saturate(2)',
    WebkitBackdropFilter: 'blur(60px) saturate(2)',
    border: '1px solid rgba(255,255,255,0.04)',
    boxShadow: '0 16px 48px rgba(0,0,0,0.4)',
  } as React.CSSProperties,
  /** Diamond — ultra-premium: maximum clarity + multi-layer reflections */
  diamond: {
    background: 'rgba(26,34,54,0.25)',
    backdropFilter: 'blur(48px) saturate(2) brightness(1.02)',
    WebkitBackdropFilter: 'blur(48px) saturate(2) brightness(1.02)',
    border: '1px solid rgba(255,255,255,0.12)',
    boxShadow: '0 12px 48px rgba(0,0,0,0.35), inset 0 2px 0 rgba(255,255,255,0.1), inset 0 -1px 0 rgba(255,255,255,0.04), 0 0 0 1px rgba(255,255,255,0.03)',
  } as React.CSSProperties,
  /** Void — deepest layer, heavy atmospheric blur */
  void: {
    background: 'rgba(10,15,30,0.6)',
    backdropFilter: 'blur(80px) saturate(2.2)',
    WebkitBackdropFilter: 'blur(80px) saturate(2.2)',
    border: '1px solid rgba(255,255,255,0.03)',
    boxShadow: '0 24px 80px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.04)',
  } as React.CSSProperties,
} as const;

/** Gradient tokens */
export const G = {
  brand: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
  brandSubtle: 'linear-gradient(135deg, rgba(99,102,241,.12) 0%, rgba(168,85,247,.08) 100%)',
  bull: 'linear-gradient(135deg, #16a34a 0%, #22c55e 100%)',
  bear: 'linear-gradient(135deg, #dc2626 0%, #ef4444 100%)',
  surface: 'linear-gradient(180deg, #1a2236 0%, #111827 100%)',
  hero: 'linear-gradient(135deg, #0a0f1e 0%, #0d1529 50%, #0f172a 100%)',
  card: 'linear-gradient(145deg, #1a2236 0%, #151e30 100%)',
  mesh: `radial-gradient(ellipse at 20% 50%, rgba(99,102,241,0.08) 0%, transparent 50%),
         radial-gradient(ellipse at 80% 20%, rgba(168,85,247,0.05) 0%, transparent 50%),
         radial-gradient(ellipse at 50% 80%, rgba(6,182,212,0.04) 0%, transparent 50%),
         #0a0f1e`,
  // Prismatic — full spectrum refraction (indigo→purple→cyan→rose)
  prismatic: 'linear-gradient(135deg, rgba(99,102,241,0.4) 0%, rgba(168,85,247,0.3) 25%, rgba(6,182,212,0.3) 50%, rgba(99,102,241,0.4) 75%, rgba(236,72,153,0.3) 100%)',
  // Iridescent — subtle rainbow shimmer
  iridescent: 'linear-gradient(135deg, rgba(99,102,241,0.15) 0%, rgba(6,182,212,0.1) 20%, rgba(168,85,247,0.12) 40%, rgba(236,72,153,0.1) 60%, rgba(99,102,241,0.15) 80%, rgba(6,182,212,0.1) 100%)',
  // Aurora — vertical atmospheric glow
  aurora: 'linear-gradient(180deg, rgba(99,102,241,0.06) 0%, rgba(6,182,212,0.04) 30%, rgba(168,85,247,0.05) 60%, rgba(99,102,241,0.03) 100%)',
  // Celestial — radial multi-source light
  celestial: `radial-gradient(ellipse at 30% 20%, rgba(99,102,241,0.12) 0%, transparent 50%),
              radial-gradient(ellipse at 70% 80%, rgba(168,85,247,0.08) 0%, transparent 50%),
              radial-gradient(ellipse at 50% 50%, rgba(6,182,212,0.06) 0%, transparent 60%)`,
} as const;

/** Format a number as USD */
export function fmtUsd(n: number | null | undefined, decimals = 2): string {
  if (n == null || isNaN(n)) return '—';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: decimals,
    minimumFractionDigits: decimals,
  }).format(n);
}

/** Format a percentage */
export function fmtPct(n: number | null | undefined, decimals = 1): string {
  if (n == null || isNaN(n)) return '—';
  const sign = n > 0 ? '+' : '';
  return `${sign}${n.toFixed(decimals)}%`;
}

/** Return a CSS rgba string for any hex color at the given opacity (0-1) */
export function alpha(hex: string, opacity: number): string {
  const h = hex.replace('#', '');
  const r = parseInt(h.substring(0,2), 16);
  const g = parseInt(h.substring(2,4), 16);
  const b = parseInt(h.substring(4,6), 16);
  return `rgba(${r},${g},${b},${opacity})`;
}

/** Format a relative timestamp */
export function timeAgo(isoOrTs: string | number | null | undefined): string {
  if (!isoOrTs) return '';
  try {
    const ts = typeof isoOrTs === 'number' ? isoOrTs * 1000 : new Date(isoOrTs).getTime();
    const diff = Math.floor((Date.now() - ts) / 1000);
    if (diff < 5) return 'just now';
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  } catch {
    return '';
  }
}
