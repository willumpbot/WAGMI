'use client';

import React, { useEffect } from 'react';
import { motion, useSpring, useTransform } from 'framer-motion';

export interface AnimatedNumberProps {
  value: number;
  format?: (n: number) => string;
  duration?: number;
  className?: string;
  style?: React.CSSProperties;
}

const defaultFormat = (n: number) =>
  n.toLocaleString('en-US', { maximumFractionDigits: 2 });

export function AnimatedNumber({
  value,
  format = defaultFormat,
  duration = 0.6,
  className,
  style,
}: AnimatedNumberProps) {
  const spring = useSpring(0, { duration: duration * 1000 });
  const display = useTransform(spring, (v) => format(v));

  useEffect(() => {
    spring.set(value);
  }, [spring, value]);

  return <motion.span className={className} style={style}>{display}</motion.span>;
}

export default AnimatedNumber;
