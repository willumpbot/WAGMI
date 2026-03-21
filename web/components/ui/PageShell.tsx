'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { C, F, SP } from '../../src/theme';
import { pageTransition } from '../../src/animations';

export interface PageShellProps {
  title?: string;
  subtitle?: string;
  children: React.ReactNode;
}

export function PageShell({ title, subtitle, children }: PageShellProps) {
  return (
    <motion.div
      {...pageTransition}
      style={{ paddingTop: SP[8], paddingBottom: SP[8] }}
    >
      {(title || subtitle) && (
        <div style={{ marginBottom: SP[6] }}>
          {title && (
            <h1
              style={{
                fontSize: F['3xl'],
                fontWeight: 700,
                color: C.text,
                margin: 0,
                lineHeight: 1.2,
              }}
            >
              {title}
            </h1>
          )}
          {subtitle && (
            <p
              style={{
                fontSize: F.md,
                color: C.muted,
                margin: `${SP[2]}px 0 0`,
              }}
            >
              {subtitle}
            </p>
          )}
        </div>
      )}
      {children}
    </motion.div>
  );
}

export default PageShell;
