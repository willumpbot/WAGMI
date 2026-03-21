'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { C, R, F, Glass } from '../../src/theme';
import { fadeUp } from '../../src/animations';

export interface InfoBoxProps {
  children: React.ReactNode;
  color?: string;
}

export function InfoBox({ children, color = C.info }: InfoBoxProps) {
  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{
        padding: '12px 16px',
        ...Glass.card,
        background: color + '15',
        border: `1px solid ${color}33`,
        borderRadius: R.md,
        fontSize: F.sm,
        color: C.textSub,
        lineHeight: 1.7,
        marginBottom: 12,
      }}
    >
      {children}
    </motion.div>
  );
}

export default InfoBox;
