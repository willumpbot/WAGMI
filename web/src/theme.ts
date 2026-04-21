import React from 'react';

/**
 * WAGMI Design System — shared tokens.
 * True black base, green accent (#00cc88), clean card surfaces.
 */

export const C: Record<string, string> = {
  // Brand — green accent
  brand: '#00cc88',
  brandDark: '#00a86b',
  brandGlow: 'rgba(0,204,136,0.15)',
  brandMid: '#00e699',

  // Semantic
  bull: '#00cc88',
  bullLight: 'rgba(0,204,136,0.12)',
  bullMid: '#00e699',
  bear: '#ff4466',
  bearLight: 'rgba(255,68,102,0.12)',
  bearMid: '#ff6680',
  warn: '#ffaa00',
  warnLight: 'rgba(255,170,0,0.12)',
  warnMid: '#ffc133',
  info: '#4488ff',
  infoLight: 'rgba(68,136,255,0.12)',
  infoMid: '#66aaff',
  purple: '#aa66ff',
  purpleLight: 'rgba(170,102,255,0.12)',

  // Dark surface scale — true black
  bg: '#050508',
  surface: '#0a0a0f',
  surfaceHover: '#0f0f18',
  card: '#0d0d14',
  cardHover: '#121220',
  border: 'rgba(255,255,255,0.06)',
  borderBright: 'rgba(255,255,255,0.12)',

  // Text on dark
  text: '#f0f0f5',
  textSub: '#a0a0b8',
  muted: '#6b6b7b',
  faint: '#333344',

  // Semantic muted tints
  bearMuted: 'rgba(255,68,102,0.10)',
  bullMuted: 'rgba(0,204,136,0.10)',
  brandMuted: 'rgba(0,204,136,0.10)',
  warnMuted: 'rgba(255,170,0,0.10)',
  infoMuted: 'rgba(68,136,255,0.10)',
  purpleMuted: 'rgba(170,102,255,0.10)',

  // Heatmap cells
  heatBull3: '#006644',
  heatBull2: '#008855',
  heatBull1: '#00cc88',
  heatNeutral: '#1a1a26',
  heatBear1: '#ff4466',
  heatBear2: '#cc2244',
  heatBear3: '#881133',

  // Legacy light surface scale — kept for backwards compat (not used in new design)
  bgLight: '#f8fafc',
  surfaceLight: '#ffffff',
  cardLight: '#f1f5f9',
  borderLight: '#e2e8f0',
  textLight: '#0f172a',
  textSubLight: '#374151',
  mutedLight: '#6b7280',

  // Extended palette
  cyan: '#00ddcc',
  cyanGlow: 'rgba(0,221,204,0.15)',
  rose: '#ff4488',
  roseGlow: 'rgba(255,68,136,0.15)',
  amber: '#ffaa00',
  emerald: '#00cc88',
};

export const R = {
  xs: 4,
  sm: 6,
  md: 10,
  lg: 12,
  xl: 16,
  pill: 999,
} as const;

export const S = {
  sm: '0 1px 3px rgba(0,0,0,0.4)',
  md: '0 4px 12px rgba(0,0,0,0.5)',
  lg: '0 8px 28px rgba(0,0,0,0.6)',
  card: '0 1px 0 rgba(255,255,255,0.04), 0 4px 16px rgba(0,0,0,0.4)',
  glow: '0 0 20px rgba(0,204,136,0.2)',
  bullGlow: '0 0 20px rgba(0,204,136,0.15), 0 4px 12px rgba(0,0,0,0.3)',
  bearGlow: '0 0 20px rgba(255,68,102,0.15), 0 4px 12px rgba(0,0,0,0.3)',
  brandGlow: '0 0 24px rgba(0,204,136,0.18), 0 4px 12px rgba(0,0,0,0.3)',
  depth1: '0 1px 2px rgba(0,0,0,0.5), 0 2px 6px rgba(0,0,0,0.3)',
  depth2: '0 2px 4px rgba(0,0,0,0.5), 0 4px 12px rgba(0,0,0,0.4)',
  depth3: '0 4px 8px rgba(0,0,0,0.5), 0 8px 24px rgba(0,0,0,0.4), 0 16px 48px rgba(0,0,0,0.3)',
  ambient: '0 0 0 1px rgba(255,255,255,0.04), 0 4px 16px rgba(0,0,0,0.4)',
  innerLight: 'inset 0 1px 0 rgba(255,255,255,0.06)',
} as const;

// Keep Glass for backwards compat — but we discourage use; prefer solid cards
export const Glass = {
  card: {
    background: '#0d0d14',
    border: '1px solid rgba(255,255,255,0.06)',
  } as React.CSSProperties,
  nav: {
    background: '#0a0a0f',
    border: '1px solid rgba(255,255,255,0.06)',
  } as React.CSSProperties,
  elevated: {
    background: '#0f0f18',
    border: '1px solid rgba(255,255,255,0.08)',
    boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
  } as React.CSSProperties,
  crystal: {
    background: '#0d0d14',
    border: '1px solid rgba(255,255,255,0.06)',
    boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
  } as React.CSSProperties,
  liquid: {
    background: '#0d0d14',
    border: '1px solid rgba(255,255,255,0.06)',
    boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
  } as React.CSSProperties,
  frosted: {
    background: '#0a0a0f',
    border: '1px solid rgba(255,255,255,0.04)',
    boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
  } as React.CSSProperties,
  diamond: {
    background: '#0d0d14',
    border: '1px solid rgba(255,255,255,0.08)',
    boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
  } as React.CSSProperties,
  void: {
    background: '#050508',
    border: '1px solid rgba(255,255,255,0.03)',
    boxShadow: '0 16px 48px rgba(0,0,0,0.6)',
  } as React.CSSProperties,
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
export const T = 'transition: all 0.15s ease;';

/** Spacing scale (4px base) */
export const SP = { 0: 0, 1: 4, 2: 8, 3: 12, 4: 16, 5: 20, 6: 24, 8: 32, 10: 40, 12: 48, 16: 64, 20: 80 } as const;

/** Z-index layers */
export const Z = { base: 1, dropdown: 300, sidebar: 350, modal: 400, toast: 500, tooltip: 600 } as const;

/** Responsive breakpoints (px) */
export const BP = { sm: 640, md: 768, lg: 1024, xl: 1280, '2xl': 1536 } as const;

/** Motion tokens */
export const M = {
  fast: { duration: 0.12, ease: [0.25, 0.1, 0.25, 1] as number[] },
  normal: { duration: 0.2, ease: [0.25, 0.1, 0.25, 1] as number[] },
  slow: { duration: 0.35, ease: [0.25, 0.1, 0.25, 1] as number[] },
  spring: { type: 'spring' as const, stiffness: 320, damping: 26 },
  bouncy: { type: 'spring' as const, stiffness: 400, damping: 18 },
} as const;

/** Gradient tokens */
export const G = {
  brand: 'linear-gradient(135deg, #00cc88 0%, #00e699 100%)',
  brandSubtle: 'linear-gradient(135deg, rgba(0,204,136,0.12) 0%, rgba(0,230,153,0.08) 100%)',
  bull: 'linear-gradient(135deg, #00cc88 0%, #00e699 100%)',
  bear: 'linear-gradient(135deg, #ff4466 0%, #ff6680 100%)',
  surface: 'linear-gradient(180deg, #0d0d14 0%, #0a0a0f 100%)',
  hero: 'linear-gradient(135deg, #050508 0%, #080810 50%, #050508 100%)',
  card: 'linear-gradient(145deg, #0d0d14 0%, #0a0a0f 100%)',
  mesh: `radial-gradient(ellipse at 20% 50%, rgba(0,204,136,0.05) 0%, transparent 50%),
         radial-gradient(ellipse at 80% 20%, rgba(68,136,255,0.03) 0%, transparent 50%),
         radial-gradient(ellipse at 50% 80%, rgba(170,102,255,0.03) 0%, transparent 50%),
         #050508`,
  prismatic: 'linear-gradient(135deg, rgba(0,204,136,0.3) 0%, rgba(68,136,255,0.2) 50%, rgba(170,102,255,0.25) 100%)',
  iridescent: 'linear-gradient(135deg, rgba(0,204,136,0.1) 0%, rgba(68,136,255,0.08) 50%, rgba(170,102,255,0.1) 100%)',
  aurora: 'linear-gradient(180deg, rgba(0,204,136,0.04) 0%, rgba(68,136,255,0.03) 50%, rgba(170,102,255,0.03) 100%)',
  celestial: `radial-gradient(ellipse at 30% 20%, rgba(0,204,136,0.08) 0%, transparent 50%),
              radial-gradient(ellipse at 70% 80%, rgba(68,136,255,0.05) 0%, transparent 50%),
              radial-gradient(ellipse at 50% 50%, rgba(170,102,255,0.04) 0%, transparent 60%)`,
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
  const r = parseInt(h.substring(0, 2), 16);
  const g = parseInt(h.substring(2, 4), 16);
  const b = parseInt(h.substring(4, 6), 16);
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
