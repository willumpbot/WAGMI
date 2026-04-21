import React from 'react';
import { C, fmtUsd } from '../src/theme';
import { useApi } from '../hooks/useApi';
import AnimatedNumber from './AnimatedNumber';

type Summary = {
  total_trades?: number;
  total_pnl?: number;
};

type Funnel = {
  total?: number;
};

type CounterfactualsResp = {
  resolved?: unknown[];
  count?: number;
};

type ReasoningFeed = {
  pipelines?: unknown[];
  count?: number;
};

type Props = {
  /** Optional heading shown above the strip */
  heading?: string;
};

/**
 * Proof strip — real lifetime metrics that demonstrate WAGMI is not vaporware.
 * Every number pulls from the live API. Uses AnimatedNumber for a live feel.
 *
 * Placement: above the "How It Works" section on the landing page.
 * Message: "This bot has already done this much — it's real, it's running."
 */
export default function ProofStrip({ heading }: Props) {
  const { data: summary } = useApi<Summary>('/v1/summary', { refreshInterval: 30_000 });
  // Funnel over 720h (~30d) as a proxy for "signals evaluated recently"
  const { data: funnel } = useApi<Funnel>('/v1/signals/funnel?hours=720', { refreshInterval: 60_000 });
  const { data: counterfactuals } = useApi<CounterfactualsResp>(
    '/v1/counterfactuals/resolved?limit=1000',
    { refreshInterval: 120_000 }
  );
  const { data: feed } = useApi<ReasoningFeed>('/v1/reasoning/feed?limit=1000', { refreshInterval: 120_000 });

  const trades = summary?.total_trades ?? null;
  const pnl = summary?.total_pnl ?? null;
  const signals = funnel?.total ?? null;
  const resolved = counterfactuals?.count ?? counterfactuals?.resolved?.length ?? null;
  const deliberations = feed?.count ?? feed?.pipelines?.length ?? null;

  const items: Array<{ label: string; value: number | null; color: string; formatter: (n: number) => string }> = [
    { label: 'Trades executed',       value: trades,         color: C.text,  formatter: (n) => Math.round(n).toLocaleString() },
    { label: 'Cumulative PnL',        value: pnl,            color: (pnl ?? 0) >= 0 ? C.bull : C.bear, formatter: (n) => fmtUsd(n) },
    { label: 'Signals evaluated',     value: signals,        color: C.info,  formatter: (n) => Math.round(n).toLocaleString() },
    { label: 'Counterfactuals tracked', value: resolved,     color: C.warn,  formatter: (n) => Math.round(n).toLocaleString() },
    { label: 'Agent deliberations',   value: deliberations,  color: C.purple, formatter: (n) => Math.round(n).toLocaleString() },
  ];

  // If every single value is null, silently hide (API offline / no data at all)
  const anyData = items.some((i) => i.value != null);
  if (!anyData) return null;

  return (
    <div>
      {heading && (
        <div style={{
          fontSize: 11,
          fontWeight: 700,
          color: C.muted,
          textTransform: 'uppercase',
          letterSpacing: 1.4,
          marginBottom: 14,
          fontFamily: 'JetBrains Mono, monospace',
        }}>
          {heading}
        </div>
      )}
      <div
        className="proof-strip"
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: 1,
          background: 'rgba(255,255,255,0.06)',
          border: '1px solid rgba(255,255,255,0.06)',
          borderRadius: 12,
          overflow: 'hidden',
        }}
      >
        {items.map((it) => (
          <div
            key={it.label}
            style={{
              background: '#0d0d14',
              padding: '18px 16px',
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
              minWidth: 0,
            }}
          >
            <div style={{
              fontSize: 10,
              fontWeight: 700,
              color: C.muted,
              textTransform: 'uppercase',
              letterSpacing: 1,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}>
              {it.label}
            </div>
            <div style={{
              fontSize: 22,
              fontWeight: 800,
              color: it.color,
              fontFamily: 'JetBrains Mono, monospace',
              letterSpacing: -0.5,
              lineHeight: 1.1,
              minWidth: 0,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}>
              {it.value != null
                ? <AnimatedNumber value={it.value} format={it.formatter} duration={1000} />
                : '—'}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
