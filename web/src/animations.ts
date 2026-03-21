/**
 * WAGMI Animation System — shared Framer Motion variants & utilities.
 * Import these variants across all pages for consistent motion language.
 */
import type { Variants, Transition } from 'framer-motion';

// ── Entry Animations ──────────────────────────────────────────────────────────

/** Fade up from below (cards, sections) */
export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.25, 0.1, 0.25, 1] } },
};

/** Fade in without movement */
export const fadeIn: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: 0.3 } },
};

/** Scale up from slightly smaller (modals, overlays) */
export const scaleIn: Variants = {
  hidden: { opacity: 0, scale: 0.95 },
  show: { opacity: 1, scale: 1, transition: { duration: 0.25, ease: [0.25, 0.1, 0.25, 1] } },
};

/** Slide in from left (sidebar items) */
export const slideRight: Variants = {
  hidden: { opacity: 0, x: -20 },
  show: { opacity: 1, x: 0, transition: { duration: 0.3, ease: [0.25, 0.1, 0.25, 1] } },
};

/** Slide in from right */
export const slideLeft: Variants = {
  hidden: { opacity: 0, x: 20 },
  show: { opacity: 1, x: 0, transition: { duration: 0.3, ease: [0.25, 0.1, 0.25, 1] } },
};

/** Slide down (dropdowns, mobile menus) */
export const slideDown: Variants = {
  hidden: { opacity: 0, y: -8 },
  show: { opacity: 1, y: 0, transition: { duration: 0.2, ease: [0.25, 0.1, 0.25, 1] } },
};

// ── Stagger Containers ────────────────────────────────────────────────────────

/** Parent container that staggers children */
export const staggerContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06 } },
};

/** Slower stagger for larger groups */
export const staggerContainerSlow: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.04 } },
};

/** Fast stagger for small groups */
export const staggerContainerFast: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.03 } },
};

// ── Page Transitions ──────────────────────────────────────────────────────────

/** Page enter/exit animation props (spread onto motion.div) */
export const pageTransition = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -4 },
  transition: { duration: 0.2, ease: [0.25, 0.1, 0.25, 1] } as Transition,
};

// ── Micro-interactions ────────────────────────────────────────────────────────

/** Card hover lift effect */
export const hoverLift = {
  whileHover: { y: -3, boxShadow: '0 12px 40px rgba(0,0,0,0.4)', transition: { duration: 0.2 } },
};

/** Glass card hover — subtle glow intensify */
export const hoverGlow = {
  whileHover: {
    boxShadow: '0 12px 40px rgba(0,0,0,0.35), 0 0 20px rgba(99,102,241,0.12)',
    borderColor: 'rgba(255,255,255,0.1)',
    transition: { duration: 0.25 },
  },
};

/** Button tap shrink */
export const tapShrink = {
  whileTap: { scale: 0.97, transition: { duration: 0.1 } },
};

// ── Chart Animations ──────────────────────────────────────────────────────────

/** SVG path draw-in animation */
export const pathDraw: Variants = {
  hidden: { pathLength: 0, opacity: 0 },
  show: {
    pathLength: 1,
    opacity: 1,
    transition: { pathLength: { duration: 0.8, ease: 'easeInOut' }, opacity: { duration: 0.2 } },
  },
};

/** Bar chart bar grow-up */
export const barGrow: Variants = {
  hidden: { scaleY: 0, opacity: 0 },
  show: { scaleY: 1, opacity: 1, transition: { duration: 0.4, ease: [0.25, 0.1, 0.25, 1] } },
};

/** Heatmap cell fade-in */
export const cellFade: Variants = {
  hidden: { opacity: 0, scale: 0.8 },
  show: { opacity: 1, scale: 1, transition: { duration: 0.25 } },
};

// ── Cinematic Entry Animations ────────────────────────────────────────────────

/** Cinematic reveal — slides up with scale and blur (hero sections, page entrances) */
export const cinematicReveal: Variants = {
  hidden: { opacity: 0, y: 30, scale: 0.97, filter: 'blur(4px)' },
  show: {
    opacity: 1, y: 0, scale: 1, filter: 'blur(0px)',
    transition: { duration: 0.6, ease: [0.22, 1, 0.36, 1] },
  },
};

/** Ethereal float — gentle floating entrance with subtle 3D tilt */
export const etherealFloat: Variants = {
  hidden: { opacity: 0, y: 20, rotateX: 4 },
  show: {
    opacity: 1, y: 0, rotateX: 0,
    transition: { duration: 0.5, ease: [0.25, 0.1, 0.25, 1] },
  },
};

/** Crystallize — appears from center with scale + blur (modals, featured content) */
export const crystallize: Variants = {
  hidden: { opacity: 0, scale: 0.9, filter: 'blur(8px)' },
  show: {
    opacity: 1, scale: 1, filter: 'blur(0px)',
    transition: { duration: 0.4, ease: [0.22, 1, 0.36, 1] },
  },
};

// ── Orchestrated Choreography ────────────────────────────────────────────────

/** Orchestrated container — slower stagger with initial delay for drama */
export const orchestratedContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } },
};

/** Wave stagger — children enter in directional wave */
export const waveContainer: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.05, staggerDirection: 1 } },
};

// ── Advanced Hover Effects ───────────────────────────────────────────────────

/** Magnetic hover — premium card lift with spring physics */
export const magneticHover = {
  whileHover: {
    y: -4,
    scale: 1.01,
    boxShadow: '0 20px 60px rgba(0,0,0,0.4), 0 0 30px rgba(99,102,241,0.1)',
    borderColor: 'rgba(255,255,255,0.12)',
    transition: { type: 'spring' as const, stiffness: 300, damping: 20 },
  },
};

/** Luminous hover — inner glow intensifies */
export const luminousHover = {
  whileHover: {
    boxShadow: '0 0 40px rgba(99,102,241,0.15), 0 8px 32px rgba(0,0,0,0.3), inset 0 1px 0 rgba(255,255,255,0.1)',
    borderColor: 'rgba(99,102,241,0.2)',
    transition: { duration: 0.3 },
  },
};

// ── Number/Text Animations ───────────────────────────────────────────────────

/** Digit morphing spring config for AnimatedNumber */
export const digitMorph: Transition = {
  type: 'spring', stiffness: 200, damping: 30, mass: 0.8,
};

/** Tooltip spring entrance */
export const tooltipReveal: Variants = {
  hidden: { opacity: 0, y: 4, scale: 0.96 },
  show: {
    opacity: 1, y: 0, scale: 1,
    transition: { type: 'spring', stiffness: 500, damping: 30 },
  },
};

// ── Utility ───────────────────────────────────────────────────────────────────

/** Check if user prefers reduced motion */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** Returns empty animation props if user prefers reduced motion */
export function safeMotionProps<T extends Record<string, unknown>>(props: T): T | Record<string, never> {
  if (prefersReducedMotion()) return {};
  return props;
}
