import { useEffect, useState } from 'react';
import { BP } from '../src/theme';

/**
 * Returns true when the given CSS media query matches.
 * Updates reactively on window resize / orientation change.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const mql = window.matchMedia(query);
    setMatches(mql.matches);

    const handler = (e: MediaQueryListEvent) => setMatches(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, [query]);

  return matches;
}

/**
 * Convenience wrapper: returns true when the viewport is at least `bp` wide.
 * Uses the BP tokens from the design system.
 */
export function useBreakpoint(bp: 'sm' | 'md' | 'lg' | 'xl' | '2xl'): boolean {
  return useMediaQuery(`(min-width: ${BP[bp]}px)`);
}
