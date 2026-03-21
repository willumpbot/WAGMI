'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { C, R, F, SP, G, Glass } from '../../src/theme';
import { fadeUp } from '../../src/animations';

export interface EmptyStateProps {
  icon?: string;
  title: string;
  subtitle?: string;
  action?: { label: string; onClick: () => void };
}

export function EmptyState({ icon, title, subtitle, action }: EmptyStateProps) {
  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      animate="show"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: SP[12],
        borderRadius: R.lg,
        ...Glass.card,
        textAlign: 'center',
      }}
    >
      {icon && (
        <div style={{ fontSize: 48, opacity: 0.3, marginBottom: SP[4] }}>
          {icon}
        </div>
      )}
      <div
        style={{
          fontSize: F.lg,
          fontWeight: 600,
          color: C.textSub,
          marginBottom: subtitle ? SP[2] : action ? SP[4] : 0,
        }}
      >
        {title}
      </div>
      {subtitle && (
        <div
          style={{
            fontSize: F.sm,
            color: C.muted,
            marginBottom: action ? SP[4] : 0,
            maxWidth: 320,
          }}
        >
          {subtitle}
        </div>
      )}
      {action && (
        <button
          onClick={action.onClick}
          style={{
            padding: `${SP[2]}px ${SP[5]}px`,
            borderRadius: R.md,
            border: 'none',
            background: G.brand,
            color: '#fff',
            fontSize: F.sm,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          {action.label}
        </button>
      )}
    </motion.div>
  );
}

export default EmptyState;
