'use client';

import React, { useState, useRef, useId } from 'react';
import { C, F, R } from '../src/theme';

/**
 * Tooltip — hover-to-learn pattern (§7.5 of the HL reshape doc).
 * Wrap any term to surface a 1-2 sentence definition on hover.
 *
 * Usage:
 *   <Tooltip term="Funding rate" def="Periodic payment between longs and shorts...">
 *     <span>funding</span>
 *   </Tooltip>
 *
 * Or use the dictionary form for known terms:
 *   <Tooltip dict="funding">funding</Tooltip>
 */

const DICT: Record<string, string> = {
  funding:
    'Funding rate — small periodic payment between longs and shorts to keep perp price near spot. Positive = longs pay shorts.',
  conviction:
    'Conviction — the bot\'s confidence in the signal, 0–100%. Trades above 80% conviction historically win 60% of the time.',
  regime:
    'Regime — market state classification: trending, ranging, illiquid, panic. Different strategies work in different regimes.',
  leverage:
    'Leverage — multiplier on position size. WAGMI caps leverage at 5x. Higher = bigger gains and bigger losses.',
  rr: 'R:R (Risk:Reward) — ratio of potential profit to risk on a trade. WAGMI requires R:R ≥ 1.0 for any signal to be valid.',
  tp1: 'TP1 (Take Profit 1) — first take-profit target. Bot closes a portion here and trails the remainder.',
  tp2: 'TP2 (Take Profit 2) — second target, takes more off if reached. Final remainder rides a trailing stop.',
  sl: 'SL (Stop Loss) — automatic exit if price moves against the trade beyond a fixed distance.',
  trailing: 'Trailing stop — SL that follows price as it moves favorably, locking in gains.',
  drawdown:
    'Drawdown — peak-to-trough equity decline. WAGMI pauses trading when daily drawdown exceeds risk limits.',
  calibration:
    'Calibration — how often the agent\'s stated confidence matches actual outcomes. 0.9 = well-calibrated.',
  veto: 'Veto — when the Critic agent overrides the Trade agent\'s decision. Vetoed trades historically were correct to skip.',
};

export default function Tooltip({
  children,
  term,
  def,
  dict,
}: {
  children: React.ReactNode;
  term?: string;
  def?: string;
  dict?: keyof typeof DICT | string;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);
  const id = useId();

  const definition = def || (dict ? DICT[dict] : undefined);
  if (!definition) {
    return <>{children}</>; // No definition → render plainly
  }

  return (
    <span
      ref={ref}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
      style={{
        position: 'relative',
        display: 'inline-block',
        textDecoration: 'underline dotted',
        textUnderlineOffset: 3,
        textDecorationColor: C.muted,
        cursor: 'help',
      }}
      tabIndex={0}
      aria-describedby={open ? id : undefined}
    >
      {children}
      {open && (
        <span
          id={id}
          role="tooltip"
          style={{
            position: 'absolute',
            bottom: '100%',
            left: 0,
            marginBottom: 6,
            background: '#0d0d14',
            border: `1px solid ${C.borderBright}`,
            borderRadius: R.sm,
            padding: '8px 10px',
            fontSize: F.xs,
            color: C.textSub,
            lineHeight: 1.5,
            width: 260,
            zIndex: 1000,
            boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
            pointerEvents: 'none',
          }}
        >
          {term && (
            <div style={{ color: C.text, fontWeight: 600, marginBottom: 3 }}>{term}</div>
          )}
          {definition}
        </span>
      )}
    </span>
  );
}
