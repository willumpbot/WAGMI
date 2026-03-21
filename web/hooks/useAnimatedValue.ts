import { useSpring, useTransform, type MotionValue, useMotionValue } from 'framer-motion';
import { useEffect } from 'react';

/**
 * Returns a MotionValue that spring-animates smoothly toward `target`.
 * Useful for live-updating numbers (equity, PnL, etc.) that should
 * transition fluidly rather than jump.
 */
export function useAnimatedValue(
  target: number,
  config?: { stiffness?: number; damping?: number },
): MotionValue<number> {
  const motionValue = useMotionValue(target);

  const springValue = useSpring(motionValue, {
    stiffness: config?.stiffness ?? 120,
    damping: config?.damping ?? 20,
  });

  useEffect(() => {
    motionValue.set(target);
  }, [target, motionValue]);

  return springValue;
}
