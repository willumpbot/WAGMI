/**
 * WAGMI Design System — shared tokens for all pages.
 * Import C (colours), R (radii), S (shadows), F (font sizes),
 * A (animations), DARK (dark mode palette), COMPONENTS (component styles).
 */

// ─── COLOR SYSTEM ─────────────────────────────────────────────────────────

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

  // Agent role colors
  agentRegime: '#f59e0b',
  agentTrade: '#3b82f6',
  agentRisk: '#ef4444',
  agentCritic: '#a78bfa',
  agentLearning: '#10b981',
  agentExit: '#ec4899',
  agentScout: '#06b6d4',
  agentQuant: '#06b6d4',
  agentOverseer: '#8b5cf6',
};

// ─── DARK MODE PALETTE ────────────────────────────────────────────────────

export const DARK = {
  bg: '#0f0f1e',
  surface: '#1a1a2e',
  card: '#252541',
  border: '#3a3a52',
  text: '#e8e8f0',
  textSub: '#a8a8b8',
  muted: '#707080',
};

// ─── BORDER RADIUS ────────────────────────────────────────────────────────

export const R = {
  xs: 4,
  sm: 6,
  md: 10,
  lg: 16,
  xl: 20,
  pill: 999,
} as const;

// ─── SHADOWS ──────────────────────────────────────────────────────────────

export const S = {
  sm: '0 1px 3px rgba(0,0,0,.25)',
  md: '0 4px 12px rgba(0,0,0,.3)',
  lg: '0 8px 28px rgba(0,0,0,.4)',
  glow: '0 0 20px rgba(99,102,241,.25)',
  glowSuccess: '0 0 20px rgba(16,179,81,.2)',
  glowDanger: '0 0 20px rgba(220,38,38,.2)',
  lift: '0 12px 24px rgba(0,0,0,.35)',
} as const;

// ─── FONT SIZES ───────────────────────────────────────────────────────────

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

// ─── ANIMATIONS ───────────────────────────────────────────────────────────

export const A = {
  // Fade animations
  fadeIn: 'all 0.4s ease-in',
  fadeOut: 'all 0.3s ease-out',

  // Movement animations
  slideInUp: 'transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1)',
  slideInDown: 'transform 0.5s cubic-bezier(0.34, 1.56, 0.64, 1)',
  slideInLeft: 'transform 0.4s ease-out',
  slideInRight: 'transform 0.4s ease-out',

  // Scale & lift
  scaleIn: 'transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)',
  lift: 'transform 0.3s ease, box-shadow 0.3s ease',

  // Pulse & glow
  pulse: 'opacity 0.6s infinite',
  glow: 'box-shadow 0.3s ease',
  shimmer: 'background-position 2s infinite',

  // Interactions
  hover: 'all 0.2s ease',
  active: 'transform 0.1s ease',

  // Count animation (duration for JS)
  countUp: 'duration 0.8s ease-out',
} as const;

// ─── TRANSITION SHORTHAND ─────────────────────────────────────────────────

export const T = 'transition: all 0.18s ease;';

// ─── GRADIENTS ────────────────────────────────────────────────────────────

export const G = {
  brand: 'linear-gradient(135deg, #6366f1 0%, #a855f7 100%)',
  brandSubtle: 'linear-gradient(135deg, rgba(99,102,241,.12) 0%, rgba(168,85,247,.08) 100%)',
  bull: 'linear-gradient(135deg, #16a34a 0%, #22c55e 100%)',
  bear: 'linear-gradient(135deg, #dc2626 0%, #ef4444 100%)',
  surface: 'linear-gradient(180deg, #1a2236 0%, #111827 100%)',
  hero: 'linear-gradient(135deg, #0a0f1e 0%, #0d1529 50%, #0f172a 100%)',
  card: 'linear-gradient(145deg, #1a2236 0%, #151e30 100%)',
} as const;

// ─── COMPONENT STYLES ─────────────────────────────────────────────────────

export const COMPONENTS = {
  // Card hover state
  cardHover: {
    background: C.surfaceHover,
    boxShadow: S.lift,
    transform: 'translateY(-2px)',
    transition: A.lift,
  },

  // Button base
  buttonBase: {
    padding: '10px 16px',
    fontSize: F.sm,
    fontWeight: 600,
    borderRadius: R.md,
    border: 'none',
    cursor: 'pointer',
    transition: A.hover,
  },

  // Button primary
  buttonPrimary: {
    background: C.brand,
    color: '#fff',
    boxShadow: S.md,
  },

  // Button secondary
  buttonSecondary: {
    background: C.surface,
    color: C.text,
    border: `1px solid ${C.border}`,
  },

  // Badge
  badge: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '4px 10px',
    borderRadius: R.pill,
    fontSize: F.xs,
    fontWeight: 600,
    transition: A.hover,
  },

  // Progress bar
  progressBar: {
    height: 6,
    borderRadius: R.pill,
    background: C.border,
    overflow: 'hidden',
  },

  // Stat block
  statBlock: {
    padding: '20px 24px',
    background: C.card,
    border: `1px solid ${C.border}`,
    borderRadius: R.lg,
    transition: A.lift,
  },
} as const;

// ─── UTILITY FUNCTIONS ────────────────────────────────────────────────────

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

/** Get agent role color by name */
export function agentColor(role: string): string {
  const roleMap: Record<string, string> = {
    regime: C.agentRegime,
    trade: C.agentTrade,
    risk: C.agentRisk,
    critic: C.agentCritic,
    learning: C.agentLearning,
    exit: C.agentExit,
    scout: C.agentScout,
    quant: C.agentQuant,
    overseer: C.agentOverseer,
  };
  return roleMap[role.toLowerCase()] || C.muted;
}

/** Get decision color (proceed/skip/flip/veto) */
export function decisionColor(action: string): string {
  const actionMap: Record<string, string> = {
    proceed: C.bull,
    go: C.bull,
    skip: C.muted,
    flat: C.muted,
    flip: C.warn,
    reverse: C.warn,
    veto: C.purple,
    blocked: C.bear,
  };
  return actionMap[action.toLowerCase()] || C.muted;
}

