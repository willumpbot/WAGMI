/**
 * Shared formatting and math utilities for the WAGMI trading dashboard.
 *
 * Extracted from repeated patterns across pages:
 *   - fmtPnl / fmtPct / fmtK  → sign-prefixed number formatting
 *   - clamp / normalise        → SVG coordinate helpers
 *   - seededRand               → deterministic PRNG (fake/fallback data)
 */

// ─── Number Formatting ────────────────────────────────────────────────────────

/**
 * Format a PnL value with sign prefix and dollar sign.
 * e.g. fmtPnl(1234)  → "+$1,234"
 *      fmtPnl(-456)  → "-$456"
 *      fmtPnl(null)  → "—"
 */
export function fmtPnl(v: number | null | undefined, decimals = 0): string {
  if (v == null || isNaN(v)) return '—';
  const sign = v >= 0 ? '+' : '-';
  const abs = Math.abs(v);
  const formatted = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(abs);
  return `${sign}$${formatted}`;
}

/**
 * Format a percentage with sign prefix.
 * e.g. fmtPct(12.3)  → "+12.3%"
 *      fmtPct(-4.5)  → "-4.5%"
 *      fmtPct(null)  → "—"
 *
 * Note: theme.ts also exports fmtPct (no sign for positive). This version
 * always includes the sign — prefer this one for PnL-style percentage display.
 */
export function fmtPct(v: number | null | undefined, decimals = 1): string {
  if (v == null || isNaN(v)) return '—';
  const sign = v >= 0 ? '+' : '';
  return `${sign}${v.toFixed(decimals)}%`;
}

/**
 * Format a dollar value compactly, abbreviating thousands with "K".
 * e.g. fmtK(1234)   → "$1.2K"
 *      fmtK(45)      → "$45"
 *      fmtK(-1234)   → "-$1.2K"
 *      fmtK(null)    → "—"
 *
 * Mirrors the pattern in strategies/index.tsx:
 *   (pnl >= 0 ? '+' : '') + (Math.abs(pnl) >= 1000 ? `$${(pnl/1000).toFixed(1)}k` : `$${pnl.toFixed(0)}`)
 * but without the sign prefix (use fmtPnl for signed version).
 */
export function fmtK(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return '—';
  const sign = v < 0 ? '-' : '';
  const abs = Math.abs(v);
  if (abs >= 1000) {
    return `${sign}$${(abs / 1000).toFixed(1)}K`;
  }
  return `${sign}$${abs.toFixed(0)}`;
}

/**
 * Signed compact formatter: combines fmtPnl sign logic with fmtK abbreviation.
 * e.g. fmtPnlK(1234)  → "+$1.2K"
 *      fmtPnlK(-456)  → "-$456"
 */
export function fmtPnlK(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return '—';
  const sign = v >= 0 ? '+' : '-';
  const abs = Math.abs(v);
  if (abs >= 1000) {
    return `${sign}$${(abs / 1000).toFixed(1)}K`;
  }
  return `${sign}$${abs.toFixed(0)}`;
}

// ─── Math Helpers ─────────────────────────────────────────────────────────────

/**
 * Clamp a value between min and max (inclusive).
 */
export function clamp(v: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, v));
}

/**
 * Normalise v to [0, 1] given a range [min, max].
 * Safe: returns 0 when max === min (avoids division by zero).
 * Used for SVG coordinate mapping, heatmap intensity, etc.
 *
 * e.g. normalise(50, 0, 100) → 0.5
 *      normalise(5,  5, 5)   → 0   (degenerate range)
 */
export function normalise(v: number, min: number, max: number): number {
  if (max === min) return 0;
  return (v - min) / (max - min);
}

// ─── Deterministic PRNG ───────────────────────────────────────────────────────

/**
 * Returns a seeded pseudo-random number generator (closure).
 * Uses a simple xorshift-style hash for good distribution and determinism.
 *
 * Unlike the scattered Math.sin(seed*N) patterns across pages, this gives
 * a stateful generator — call rand() repeatedly to advance the sequence.
 *
 * Usage:
 *   const rand = seededRand(42);
 *   rand(); // → 0.123...
 *   rand(); // → 0.456...  (deterministic sequence)
 *
 * If you need a single value at a specific index (stateless), use:
 *   seededRand(seed + index)()
 */
export function seededRand(seed: number): () => number {
  // mulberry32 algorithm — fast, good distribution, 32-bit state
  let s = (seed | 0) >>> 0;
  if (s === 0) s = 1; // avoid degenerate seed
  return (): number => {
    s += 0x6d2b79f5;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Single-shot seeded random value (stateless convenience wrapper).
 * Equivalent to: seededRand(seed)()
 *
 * Replaces the common Math.sin(seed + N) * 10000 frac pattern:
 *   const x = Math.sin(seed + 1) * 10000; return x - Math.floor(x);
 *
 * e.g. seedVal(42) → 0.789... (deterministic)
 */
export function seedVal(seed: number): number {
  return seededRand(seed)();
}
