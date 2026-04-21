'use client';

import React, { useEffect, useState } from 'react';
import { C, fmtUsd } from '../src/theme';
import { StatusDot } from './ui/StatusDot';

export type PositionItem = {
  symbol: string;
  side: string;
  entry: number;
  sl: number;
  tp1: number;
  tp2: number;
  state: string;
  leverage: number;
  qty: number;
  realized_pnl: number;
  open_time: string;
};

export interface PositionCardProps {
  position: PositionItem;
  livePrice?: number | null; // current mark price (may be null)
  priceUpdatedAt?: number | null; // epoch ms of last price update
}

// ─── Helpers ───────────────────────────────────────────────────────────────

function fmtDuration(isoOrTs: string | undefined | null): string {
  if (!isoOrTs) return '—';
  try {
    const ts = typeof isoOrTs === 'string' ? new Date(isoOrTs).getTime() : Number(isoOrTs) * 1000;
    const diff = Math.max(0, Date.now() - ts);
    const s = Math.floor(diff / 1000);
    if (s < 60) return `${s}s`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m`;
    const h = Math.floor(m / 60);
    const mm = m % 60;
    if (h < 24) return `${h}h ${mm}m`;
    const d = Math.floor(h / 24);
    const hh = h % 24;
    return `${d}d ${hh}h`;
  } catch {
    return '—';
  }
}

function pctChange(from: number, to: number): number {
  if (!from) return 0;
  return ((to - from) / from) * 100;
}

// ─── Mini distance bar ─────────────────────────────────────────────────────

function DistanceBar({
  label,
  distancePct,
  color,
}: {
  label: string;
  distancePct: number | null;
  color: string;
}) {
  // Cap displayed fill at 100% of bar
  const fill = distancePct == null ? 0 : Math.max(0, Math.min(1, Math.abs(distancePct) / 5));
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          marginBottom: 3,
          fontSize: 10,
          fontWeight: 700,
          color: C.muted,
          letterSpacing: 0.5,
          textTransform: 'uppercase',
        }}
      >
        <span>{label}</span>
        <span
          className="num"
          style={{
            color,
            fontFamily: 'JetBrains Mono, monospace',
            fontWeight: 700,
          }}
        >
          {distancePct == null ? '—' : `${distancePct >= 0 ? '+' : ''}${distancePct.toFixed(2)}%`}
        </span>
      </div>
      <div
        style={{
          height: 3,
          background: 'rgba(255,255,255,0.05)',
          borderRadius: 999,
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${fill * 100}%`,
            height: '100%',
            background: color,
            borderRadius: 999,
            transition: 'width 0.4s ease',
          }}
        />
      </div>
    </div>
  );
}

// ─── PnL horizontal bar (red ← 0 → green) ──────────────────────────────────

function PnlBar({ pnlUsd, marginUsd }: { pnlUsd: number; marginUsd: number }) {
  // Normalize to a -100% / +100% visual range. Cap fill at 1.0.
  const pct = marginUsd > 0 ? pnlUsd / marginUsd : 0;
  const fill = Math.max(-1, Math.min(1, pct));
  const isPos = fill > 0;
  const width = Math.abs(fill) * 50; // each side is 50% of bar

  return (
    <div style={{ position: 'relative', height: 8, background: 'rgba(255,255,255,0.04)', borderRadius: 999, overflow: 'hidden' }}>
      {/* Center line */}
      <div style={{ position: 'absolute', top: 0, bottom: 0, left: '50%', width: 1, background: 'rgba(255,255,255,0.12)' }} />
      {/* Fill (either left or right of center) */}
      <div
        style={{
          position: 'absolute',
          top: 0,
          bottom: 0,
          left: isPos ? '50%' : `${50 - width}%`,
          width: `${width}%`,
          background: isPos ? C.bull : C.bear,
          boxShadow: isPos ? '0 0 10px rgba(0,204,136,0.45)' : '0 0 10px rgba(255,68,102,0.45)',
          transition: 'all 0.4s ease',
          borderRadius: 999,
        }}
      />
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────

export default function PositionCard({ position, livePrice, priceUpdatedAt }: PositionCardProps) {
  const pos = position;
  const isLong = pos.side?.toUpperCase() === 'BUY' || pos.side?.toUpperCase() === 'LONG';
  const current = livePrice != null && livePrice > 0 ? livePrice : pos.entry;
  const priceAgeS = priceUpdatedAt ? Math.floor((Date.now() - priceUpdatedAt) / 1000) : null;
  const freshness: 'live' | 'stale' | 'idle' = priceAgeS == null
    ? 'idle'
    : priceAgeS > 60
    ? 'stale'
    : 'live';

  // Distance metrics — signed so we can color directional progress.
  const slDist = pos.sl ? pctChange(current, pos.sl) : null;       // negative for long
  const tp1Dist = pos.tp1 ? pctChange(current, pos.tp1) : null;
  const tp2Dist = pos.tp2 ? pctChange(current, pos.tp2) : null;

  // Unrealized PnL (position sign × price move × qty)
  const qty = pos.qty ?? 0;
  const priceDelta = current - pos.entry;
  const directionalDelta = isLong ? priceDelta : -priceDelta;
  const unrealizedPnl = directionalDelta * Math.abs(qty);
  const realized = pos.realized_pnl ?? 0;
  const totalPnl = realized + unrealizedPnl;

  // Rough margin to normalize PnL bar. Fallback = notional / leverage.
  const notional = Math.abs(qty) * pos.entry;
  const margin = notional / Math.max(1, pos.leverage || 1);

  const sideColor = isLong ? C.bull : C.bear;
  const sideBg = isLong ? 'rgba(0,204,136,0.12)' : 'rgba(255,68,102,0.12)';

  const pnlColor = totalPnl > 0 ? C.bull : totalPnl < 0 ? C.bear : C.textSub;

  return (
    <div
      style={{
        padding: '14px 16px',
        background: 'rgba(13,13,20,0.7)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        border: '1px solid rgba(255,255,255,0.05)',
        borderRadius: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        minWidth: 0,
        boxShadow:
          totalPnl > 0
            ? '0 0 20px rgba(0,204,136,0.08), 0 4px 14px rgba(0,0,0,0.35)'
            : totalPnl < 0
            ? '0 0 20px rgba(255,68,102,0.08), 0 4px 14px rgba(0,0,0,0.35)'
            : '0 4px 14px rgba(0,0,0,0.35)',
        transition: 'box-shadow 0.3s ease',
      }}
    >
      {/* Header: symbol + side + leverage + live dot */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div
          className="num"
          style={{
            fontSize: 15,
            fontWeight: 800,
            color: C.text,
            fontFamily: 'JetBrains Mono, monospace',
            letterSpacing: -0.4,
          }}
        >
          {pos.symbol}
        </div>
        <span
          style={{
            fontSize: 10,
            fontWeight: 800,
            padding: '2px 8px',
            borderRadius: 999,
            background: sideBg,
            color: sideColor,
            letterSpacing: 0.6,
          }}
        >
          {isLong ? 'LONG' : 'SHORT'}
        </span>
        {pos.leverage > 0 && (
          <span
            className="num"
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: '2px 8px',
              borderRadius: 999,
              background: 'rgba(255,255,255,0.05)',
              color: C.textSub,
              fontFamily: 'JetBrains Mono, monospace',
              border: '1px solid rgba(255,255,255,0.06)',
            }}
          >
            {pos.leverage}x
          </span>
        )}
        <div style={{ flex: 1 }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }} title={`Price ${priceAgeS != null ? priceAgeS + 's' : 'n/a'} old`}>
          <StatusDot kind={freshness} size={6} />
          <span style={{ fontSize: 10, fontWeight: 700, color: C.muted, letterSpacing: 0.5, textTransform: 'uppercase' }}>
            {fmtDuration(pos.open_time)}
          </span>
        </div>
      </div>

      {/* Entry + Current row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <div>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, letterSpacing: 0.6, textTransform: 'uppercase', marginBottom: 2 }}>Entry</div>
          <div
            className="num"
            style={{ fontSize: 13, fontWeight: 700, color: C.textSub, fontFamily: 'JetBrains Mono, monospace' }}
          >
            {pos.entry ? fmtUsd(pos.entry, pos.entry > 1000 ? 2 : 4) : '—'}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 10, fontWeight: 700, color: C.muted, letterSpacing: 0.6, textTransform: 'uppercase', marginBottom: 2 }}>Current</div>
          <div
            className="num"
            style={{
              fontSize: 13,
              fontWeight: 800,
              color: livePrice != null ? C.text : C.muted,
              fontFamily: 'JetBrains Mono, monospace',
            }}
          >
            {current ? fmtUsd(current, current > 1000 ? 2 : 4) : '—'}
          </div>
        </div>
      </div>

      {/* Distance bars */}
      <div style={{ display: 'flex', gap: 10 }}>
        <DistanceBar label="SL" distancePct={slDist} color={C.bear} />
        <DistanceBar label="TP1" distancePct={tp1Dist} color={C.warn} />
        <DistanceBar label="TP2" distancePct={tp2Dist} color={C.bull} />
      </div>

      {/* PnL bar + value */}
      <div>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 4,
          }}
        >
          <span
            style={{ fontSize: 10, fontWeight: 700, color: C.muted, letterSpacing: 0.6, textTransform: 'uppercase' }}
          >
            {livePrice != null ? 'Unrealized P&L' : 'Realized P&L'}
          </span>
          <span
            className="num"
            style={{
              fontSize: 13,
              fontWeight: 800,
              color: pnlColor,
              fontFamily: 'JetBrains Mono, monospace',
              letterSpacing: -0.2,
            }}
          >
            {fmtUsd(totalPnl)}
          </span>
        </div>
        <PnlBar pnlUsd={totalPnl} marginUsd={margin} />
      </div>
    </div>
  );
}
