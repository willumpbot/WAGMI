import React, { useEffect, useRef, useState } from 'react';

type Props = {
  value: number | null | undefined;
  format?: (n: number) => string;
  duration?: number;
  decimals?: number;
  className?: string;
  style?: React.CSSProperties;
};

/**
 * Number that animates to its target on change.
 * Uses requestAnimationFrame for 60fps ease-out interpolation — no Framer Motion dep.
 */
export default function AnimatedNumber({
  value,
  format,
  duration = 600,
  decimals = 2,
  className,
  style,
}: Props) {
  const [displayed, setDisplayed] = useState<number>(value ?? 0);
  const fromRef = useRef<number>(value ?? 0);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    if (value == null || isNaN(value)) return;
    const from = fromRef.current;
    const to = value;
    if (Math.abs(to - from) < 0.0001) {
      setDisplayed(to);
      return;
    }
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      const next = from + (to - from) * eased;
      setDisplayed(next);
      if (t < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = to;
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [value, duration]);

  if (value == null || isNaN(value)) {
    return <span className={className} style={style}>—</span>;
  }
  const text = format ? format(displayed) : displayed.toFixed(decimals);
  return <span className={className} style={style}>{text}</span>;
}
