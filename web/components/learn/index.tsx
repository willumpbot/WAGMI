'use client';

/**
 * Shared layout primitives for /learn and educational sub-pages.
 *
 * Goal: make /learn editable by adding small new files instead of scrolling
 * through the 4,086-line learn.tsx. Future pattern:
 *
 *   web/content/learn/<topic>.mdx       (MDX content; phone-editable via GitHub)
 *   web/components/learn/<Widget>.tsx   (interactive widgets)
 *   web/pages/learn.tsx                 (composes content + widgets)
 *
 * Phase 1 of the migration ships these primitives so new educational
 * content can be added in small files without touching learn.tsx.
 */

import React, { useState } from 'react';
import { C, F, R } from '../../src/theme';

export function LearnSection({
  title,
  badge,
  children,
}: {
  title: string;
  badge?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      style={{
        background: '#0a0a0f',
        border: `1px solid ${C.border}`,
        borderRadius: R.sm,
        padding: '20px 24px',
        marginBottom: 16,
      }}
    >
      <header
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 12,
          marginBottom: 12,
        }}
      >
        <h2
          style={{
            margin: 0,
            fontSize: F.xl,
            fontWeight: 700,
            color: C.text,
            letterSpacing: -0.3,
          }}
        >
          {title}
        </h2>
        {badge && (
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: '2px 8px',
              background: C.brand + '15',
              color: C.brand,
              border: `1px solid ${C.brand}55`,
              borderRadius: 3,
              fontFamily: 'JetBrains Mono, monospace',
              letterSpacing: 0.04,
            }}
          >
            {badge}
          </span>
        )}
      </header>
      <div
        style={{
          color: C.textSub,
          fontSize: F.md,
          lineHeight: 1.7,
        }}
      >
        {children}
      </div>
    </section>
  );
}

export function LearnAccordion({
  title,
  badge,
  defaultOpen = false,
  children,
}: {
  title: string;
  badge?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div
      style={{
        background: '#0a0a0f',
        border: `1px solid ${open ? C.borderBright : C.border}`,
        borderRadius: R.sm,
        marginBottom: 8,
        transition: 'border-color 120ms ease-out',
      }}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          width: '100%',
          padding: '14px 18px',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          textAlign: 'left',
          fontFamily: 'inherit',
        }}
      >
        <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {badge && (
            <span
              style={{
                fontSize: 10,
                fontWeight: 700,
                padding: '2px 8px',
                background: C.brand + '15',
                color: C.brand,
                border: `1px solid ${C.brand}55`,
                borderRadius: 3,
                fontFamily: 'JetBrains Mono, monospace',
              }}
            >
              {badge}
            </span>
          )}
          <span style={{ fontSize: F.md, fontWeight: 600, color: C.text }}>{title}</span>
        </span>
        <span
          style={{
            color: C.muted,
            fontSize: 12,
            transition: 'transform 120ms ease-out',
            transform: open ? 'rotate(180deg)' : 'rotate(0deg)',
          }}
        >
          ▾
        </span>
      </button>
      {open && (
        <div
          style={{
            padding: '4px 18px 18px',
            color: C.textSub,
            fontSize: F.sm,
            lineHeight: 1.7,
          }}
        >
          {children}
        </div>
      )}
    </div>
  );
}

export function LearnInfoBox({
  children,
  tone = 'info',
}: {
  children: React.ReactNode;
  tone?: 'info' | 'warn' | 'bull' | 'bear';
}) {
  const colors = {
    info: C.info,
    warn: C.warn,
    bull: C.bull,
    bear: C.bear,
  };
  const c = colors[tone];
  return (
    <div
      style={{
        margin: '12px 0',
        padding: '12px 14px',
        background: '#050508',
        border: `1px solid ${c}33`,
        borderLeft: `3px solid ${c}`,
        borderRadius: R.xs,
        color: C.textSub,
        fontSize: F.sm,
        lineHeight: 1.6,
      }}
    >
      {children}
    </div>
  );
}

export function LearnTerm({ term, def }: { term: string; def: string }) {
  return (
    <span
      title={def}
      style={{
        color: C.text,
        textDecoration: 'underline dotted',
        textUnderlineOffset: 3,
        textDecorationColor: C.muted,
        cursor: 'help',
      }}
    >
      {term}
    </span>
  );
}
