'use client';

import React from 'react';
import { C, fmtUsd, timeAgo } from '../src/theme';
import { useApi } from '../hooks/useApi';
import { Skeleton } from './ui/Skeleton';
import { StatusDot } from './ui/StatusDot';

type SniperSignal = {
  symbol: string;
  side: string;
  tier?: string;
  entry?: number;
  sl?: number;
  tp_scalp?: number;
  tp_swing?: number;
  confidence?: number;
  num_agree?: number;
  quality_grade?: string;
  leverage?: number;
  timestamp?: string;
  ts?: string;
  regime?: string;
  strategies?: string[];
};

type ApiResp = {
  signals: SniperSignal[];
  count: number;
};

const TIER_STYLES: Record<string, { color: string; bg: string; border: string; label: string }> = {
  MICRO_SNIPER: { color: C.bear,   bg: 'rgba(255,68,102,0.12)', border: 'rgba(255,68,102,0.25)', label: 'MICRO' },
  SNIPER:       { color: C.warn,   bg: 'rgba(255,170,0,0.12)',  border: 'rgba(255,170,0,0.25)',  label: 'SNIPER' },
  PREMIUM:      { color: C.info,   bg: 'rgba(68,136,255,0.12)', border: 'rgba(68,136,255,0.25)', label: 'PREMIUM' },
  ELITE:        { color: C.purple, bg: 'rgba(170,102,255,0.12)', border: 'rgba(170,102,255,0.25)', label: 'ELITE' },
  STANDARD:     { color: C.bull,   bg: 'rgba(0,204,136,0.10)',  border: 'rgba(0,204,136,0.25)',  label: 'STD' },
};

function tierStyle(t?: string) {
  if (!t) return TIER_STYLES.STANDARD;
  const key = t.toUpperCase();
  return TIER_STYLES[key] || TIER_STYLES.STANDARD;
}

/**
 * Sniper alerts panel — recent high-conviction signals from /v1/sniper/recent.
 * Refreshes every 20s.
 */
export default function SniperAlerts({ limit = 10 }: { limit?: number }) {
  const { data, error, isLoading } = useApi<ApiResp>(`/v1/sniper/recent?limit=${limit}`, {
    refreshInterval: 20_000,
  });

  const signals = data?.signals ?? [];
  // newest first
  const ordered = [...signals].reverse();

  return (
    <div
      style={{
        background: 'rgba(13,13,20,0.7)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        border: '1px solid rgba(255,255,255,0.05)',
        borderRadius: 12,
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '14px 18px',
          borderBottom: '1px solid rgba(255,255,255,0.04)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: C.text, letterSpacing: -0.2 }}>Sniper Alerts</div>
          <span style={{ fontSize: 11, color: C.muted, fontWeight: 600 }}>last {limit}</span>
        </div>
        <StatusDot kind={error ? 'error' : 'live'} size={6} title={error ? 'Feed offline' : '20s refresh'} />
      </div>

      {/* Body */}
      {isLoading && signals.length === 0 ? (
        <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} h={38} />
          ))}
        </div>
      ) : error ? (
        <div style={{ padding: '24px 18px', color: C.muted, fontSize: 13, textAlign: 'center' }}>
          Unable to load sniper feed.
        </div>
      ) : ordered.length === 0 ? (
        <div style={{ padding: '24px 18px', color: C.muted, fontSize: 13, textAlign: 'center' }}>
          No sniper alerts yet.
        </div>
      ) : (
        <div>
          {ordered.map((s, i) => {
            const tier = tierStyle(s.tier);
            const isLong = s.side?.toUpperCase() === 'BUY' || s.side?.toUpperCase() === 'LONG';
            const sideColor = isLong ? C.bull : C.bear;
            const ts = s.timestamp || s.ts;
            const wr = s.confidence; // user blueprint says "WR badge" — we use confidence as proxy
            return (
              <div
                key={`${s.symbol}-${ts}-${i}`}
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'minmax(72px,auto) minmax(54px,auto) 46px minmax(110px,1fr) minmax(60px,auto) minmax(68px,auto)',
                  gap: 10,
                  alignItems: 'center',
                  padding: '10px 18px',
                  borderBottom: '1px solid rgba(255,255,255,0.03)',
                }}
              >
                {/* Tier badge */}
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 800,
                    padding: '3px 8px',
                    borderRadius: 999,
                    background: tier.bg,
                    color: tier.color,
                    border: `1px solid ${tier.border}`,
                    letterSpacing: 0.6,
                    textAlign: 'center',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {tier.label}
                </span>

                {/* Symbol */}
                <span
                  className="num"
                  style={{
                    fontSize: 13,
                    fontWeight: 700,
                    color: C.text,
                    fontFamily: 'JetBrains Mono, monospace',
                  }}
                >
                  {s.symbol}
                </span>

                {/* Side */}
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 800,
                    padding: '2px 6px',
                    borderRadius: 4,
                    background: isLong ? 'rgba(0,204,136,0.12)' : 'rgba(255,68,102,0.12)',
                    color: sideColor,
                    textAlign: 'center',
                    letterSpacing: 0.5,
                  }}
                >
                  {isLong ? 'LONG' : 'SHORT'}
                </span>

                {/* Entry / SL */}
                <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                  <span
                    className="num"
                    style={{
                      fontSize: 11,
                      color: C.textSub,
                      fontFamily: 'JetBrains Mono, monospace',
                      fontWeight: 600,
                    }}
                  >
                    E {s.entry != null ? fmtUsd(s.entry, s.entry > 1000 ? 2 : 4) : '—'}
                  </span>
                  <span
                    className="num"
                    style={{
                      fontSize: 10,
                      color: C.bear,
                      fontFamily: 'JetBrains Mono, monospace',
                      fontWeight: 600,
                    }}
                  >
                    SL {s.sl != null ? fmtUsd(s.sl, s.sl > 1000 ? 2 : 4) : '—'}
                  </span>
                </div>

                {/* WR/Confidence */}
                <span
                  className="num"
                  style={{
                    fontSize: 11,
                    fontWeight: 700,
                    color: wr == null ? C.muted : wr >= 85 ? C.bull : wr >= 70 ? C.warn : C.bear,
                    fontFamily: 'JetBrains Mono, monospace',
                    padding: '2px 6px',
                    background: 'rgba(255,255,255,0.03)',
                    borderRadius: 4,
                    textAlign: 'center',
                  }}
                  title="Confidence / WR"
                >
                  {wr != null ? `${Math.round(wr)}%` : '—'}
                </span>

                {/* Time */}
                <span
                  style={{
                    fontSize: 10,
                    color: C.muted,
                    fontWeight: 600,
                    textAlign: 'right',
                    whiteSpace: 'nowrap',
                  }}
                  title={ts}
                >
                  {timeAgo(ts)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
