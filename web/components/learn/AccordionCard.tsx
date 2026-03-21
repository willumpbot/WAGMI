'use client';

import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { C, R, F, Glass, SP } from '../../src/theme';
import { fadeUp } from '../../src/animations';

export interface AccordionCardProps {
  title: string;
  badge?: string;
  badgeColor?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}

export function AccordionCard({
  title,
  badge,
  badgeColor,
  defaultOpen = false,
  children,
}: AccordionCardProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <motion.div
      className="card-hover"
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true, margin: '-40px' }}
      style={{
        ...Glass.card,
        borderRadius: R.lg,
        marginBottom: SP[3],
        overflow: 'hidden',
        borderColor: open ? 'rgba(255,255,255,0.1)' : undefined,
        transition: 'border-color 0.15s',
      }}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '16px 20px',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          textAlign: 'left',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {badge && (
            <span
              style={{
                fontSize: F.xs,
                fontWeight: 700,
                padding: '2px 8px',
                borderRadius: R.pill,
                background: (badgeColor || C.brand) + '22',
                color: badgeColor || C.brand,
                flexShrink: 0,
              }}
            >
              {badge}
            </span>
          )}
          <span style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>{title}</span>
        </div>
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: 0.2 }}
          style={{ color: C.muted, fontSize: 14, flexShrink: 0 }}
        >
          &#9660;
        </motion.span>
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
            style={{ overflow: 'hidden' }}
          >
            <div style={{ padding: '4px 20px 20px', fontSize: F.sm, color: C.textSub, lineHeight: 1.8 }}>
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

export default AccordionCard;
