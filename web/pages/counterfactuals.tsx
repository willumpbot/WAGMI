'use client';

/**
 * /counterfactuals — Ghost Trades Timeline
 *
 * WAGMI native differentiator: the bot doesn't just reject signals — it follows
 * every rejected signal to its outcome. This page shows what *would* have
 * happened if the bot had taken each skipped trade.
 *
 * Pulls /v1/counterfactuals/resolved (dedup + filtered).
 */
import React, { useMemo, useState } from 'react';
import Head from 'next/head';
import Layout from '../components/Layout';
import { C, F, R, fmtPct, timeAgo } from '../src/theme';
import { Skeleton } from '../components/ui/Skeleton';
import { Badge } from '../components/ui/Badge';
import { useApi } from '../hooks/useApi';

type CfSignal = {
  record_id: string;
  symbol: string;
  side: string;
  entry_price: number;
  sl: number;
  tp1: number;
  tp2: number;
  confidence: number;
  skip_reason: string;
  strategy: string;
  regime: string;
  created_at: string;
  resolved: boolean;
  would_hit_tp1: boolean;
  would_hit_tp2: boolean;
  would_hit_sl: boolean;
  hypothetical_pnl_pct: number;
  resolved_at: string;
  max_favorable_price?: number;
  max_adverse_price?: number;
};

type WorstGate = { reason: string; count: number; missed_win_pct: number };

type CfResponse = {
  signals: CfSignal[];
  count: number;
  total_resolved: number;
  wins: number;
  losses: number;
  would_have_won_pct: number;
  hypothetical_total_pnl_pct: number;
  avg_hypothetical_pnl_pct: number;
  worst_gate: WorstGate;
  top_reasons: { reason: string; count: number }[];
};

type OutcomeFilter = 'all' | 'win' | 'loss';

function sideColor(side: string): string {
  const s = side.toUpperCase();
  if (s === 'BUY' || s === 'LONG') return C.bull;
  if (s === 'SELL' || s === 'SHORT') return C.bear;
  return C.muted;
}

function StatBox({ label, value, color, sub }: { label: string; value: string; color?: string; sub?: string }) {
  return (
    <div
      style={{
        padding: '14px 18px',
        background: C.card,
        border: `1px solid ${C.border}`,
        borderRadius: R.md,
        flex: '1 1 160px',
        minWidth: 140,
      }}
    >
      <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {label}
      </div>
      <div
        className="num"
        style={{
          fontSize: F['2xl'],
          fontWeight: 800,
          color: color || C.text,
          fontFamily: "'JetBrains Mono', monospace",
          marginTop: 4,
        }}
      >
        {value}
      </div>
      {sub && <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

export default function CounterfactualsPage() {
  const [symbol, setSymbol] = useState('');
  const [reason, setReason] = useState('');
  const [outcome, setOutcome] = useState<OutcomeFilter>('all');

  const qs = useMemo(() => {
    const parts = ['limit=100'];
    if (symbol) parts.push(`symbol=${encodeURIComponent(symbol)}`);
    if (reason) parts.push(`reason=${encodeURIComponent(reason)}`);
    if (outcome !== 'all') parts.push(`outcome=${outcome}`);
    return parts.join('&');
  }, [symbol, reason, outcome]);

  const { data, isLoading, error } = useApi<CfResponse>(
    `/v1/counterfactuals/resolved?${qs}`,
    { refreshInterval: 60_000 },
  );

  const symbols = useMemo(() => {
    const set = new Set<string>();
    (data?.signals || []).forEach((s) => s.symbol && set.add(s.symbol));
    return Array.from(set).sort();
  }, [data]);

  return (
    <Layout>
      <Head>
        <title>Counterfactuals · WAGMI</title>
      </Head>

      <div style={{ marginBottom: 24 }}>
        <h1 style={{ margin: 0, fontSize: F['2xl'], fontWeight: 800, color: C.text, letterSpacing: -0.4 }}>
          Counterfactual Dashboard
        </h1>
        <p style={{ fontSize: F.sm, color: C.textSub, margin: '8px 0 0', maxWidth: 680, lineHeight: 1.5 }}>
          Signals the bot skipped — and what actually happened. WAGMI tracks every rejected trade to its
          hypothetical outcome so we can measure the cost of each filter, veto, and circuit breaker.
        </p>
      </div>

      {/* Stats header */}
      {data && !error && (
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 20 }}>
          <StatBox label="Total Skipped" value={data.total_resolved.toLocaleString()} />
          <StatBox
            label="Would-Have-Won %"
            value={`${data.would_have_won_pct.toFixed(1)}%`}
            color={data.would_have_won_pct > 50 ? C.bear : C.bull}
            sub={`${data.wins.toLocaleString()} of ${data.total_resolved.toLocaleString()} winners blocked`}
          />
          <StatBox
            label="Hypothetical PnL %"
            value={fmtPct(data.hypothetical_total_pnl_pct, 1)}
            color={data.hypothetical_total_pnl_pct >= 0 ? C.bull : C.bear}
            sub={`${fmtPct(data.avg_hypothetical_pnl_pct, 2)} avg`}
          />
          <StatBox
            label="Worst Gate"
            value={data.worst_gate.reason || '—'}
            color={C.warn}
            sub={
              data.worst_gate.count
                ? `${data.worst_gate.count} winners blocked · ${data.worst_gate.missed_win_pct.toFixed(0)}% WR`
                : 'insufficient data'
            }
          />
        </div>
      )}

      {/* Filters */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
          marginBottom: 20,
          padding: 12,
          background: C.card,
          border: `1px solid ${C.border}`,
          borderRadius: R.md,
        }}
      >
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: F.xs, fontWeight: 700, color: C.muted, textTransform: 'uppercase' }}>
            Symbol
          </span>
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            style={{
              padding: '4px 8px',
              background: C.surface,
              border: `1px solid ${C.border}`,
              borderRadius: R.sm,
              color: C.text,
              fontSize: F.sm,
              outline: 'none',
            }}
          >
            <option value="">All</option>
            {symbols.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <span style={{ fontSize: F.xs, fontWeight: 700, color: C.muted, textTransform: 'uppercase' }}>
            Reason
          </span>
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="filter…"
            style={{
              padding: '4px 8px',
              background: C.surface,
              border: `1px solid ${C.border}`,
              borderRadius: R.sm,
              color: C.text,
              fontSize: F.sm,
              outline: 'none',
              width: 140,
            }}
          />
        </div>

        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {(['all', 'win', 'loss'] as OutcomeFilter[]).map((o) => (
            <button
              key={o}
              onClick={() => setOutcome(o)}
              style={{
                padding: '4px 10px',
                background: outcome === o ? C.brandMuted : C.surface,
                border: `1px solid ${outcome === o ? C.brand : C.border}`,
                borderRadius: R.sm,
                color: outcome === o ? C.brand : C.textSub,
                fontSize: F.xs,
                fontWeight: 700,
                cursor: 'pointer',
                textTransform: 'capitalize',
              }}
            >
              {o === 'win' ? 'Would-win' : o === 'loss' ? 'Would-lose' : 'All'}
            </button>
          ))}
        </div>

        {data?.top_reasons && data.top_reasons.length > 0 && (
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {data.top_reasons.slice(0, 4).map((r) => (
              <button
                key={r.reason}
                onClick={() => setReason(r.reason)}
                title={`${r.count} signals blocked by ${r.reason}`}
                style={{
                  padding: '2px 8px',
                  background: 'rgba(255,255,255,0.03)',
                  border: `1px solid ${C.border}`,
                  borderRadius: R.pill,
                  color: C.textSub,
                  fontSize: F.xs,
                  cursor: 'pointer',
                  fontFamily: "'JetBrains Mono', monospace",
                }}
              >
                {r.reason} · {r.count}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Loading */}
      {isLoading && !data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[0, 1, 2, 3].map((k) => (
            <Skeleton key={k} h={72} />
          ))}
        </div>
      )}

      {error && !data && (
        <div
          style={{
            padding: 20,
            background: C.card,
            border: `1px solid ${C.border}`,
            borderRadius: R.md,
            color: C.muted,
            fontSize: F.sm,
            textAlign: 'center',
          }}
        >
          Could not load counterfactual feed.
        </div>
      )}

      {/* Timeline */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {(data?.signals || []).map((s) => {
          const sColor = sideColor(s.side);
          const win = s.hypothetical_pnl_pct > 0;
          return (
            <div
              key={s.record_id}
              style={{
                display: 'grid',
                gridTemplateColumns: 'auto 1fr auto',
                gap: 14,
                alignItems: 'center',
                padding: 14,
                background: C.card,
                border: `1px solid ${win ? 'rgba(255,68,102,0.15)' : C.border}`,
                borderLeft: `3px solid ${win ? C.bear : C.bull}`,
                borderRadius: R.md,
              }}
            >
              {/* Left: symbol + side */}
              <div style={{ minWidth: 96 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <span
                    style={{
                      fontSize: F.md,
                      fontWeight: 800,
                      color: C.text,
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  >
                    {s.symbol}
                  </span>
                  <span
                    style={{
                      fontSize: F.xs,
                      fontWeight: 700,
                      padding: '1px 6px',
                      borderRadius: R.sm,
                      background: `${sColor}22`,
                      color: sColor,
                    }}
                  >
                    {s.side}
                  </span>
                </div>
                <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
                  {timeAgo(s.created_at)}
                </div>
              </div>

              {/* Middle: reason + details */}
              <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 4 }}>
                  <span
                    style={{
                      fontSize: F.xs,
                      fontWeight: 700,
                      padding: '1px 8px',
                      borderRadius: R.pill,
                      background: C.warnMuted,
                      color: C.warn,
                      fontFamily: "'JetBrains Mono', monospace",
                    }}
                  >
                    {s.skip_reason || 'unknown'}
                  </span>
                  {s.regime && (
                    <span style={{ fontSize: F.xs, color: C.muted }}>
                      regime: <span style={{ color: C.textSub }}>{s.regime}</span>
                    </span>
                  )}
                  <span style={{ fontSize: F.xs, color: C.muted }}>
                    confidence: <span style={{ color: C.textSub }}>{s.confidence.toFixed(1)}</span>
                  </span>
                </div>
                <div
                  style={{
                    fontSize: F.xs,
                    color: C.muted,
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                >
                  entry {s.entry_price?.toFixed(4)} · sl {s.sl?.toFixed(4)} · tp1 {s.tp1?.toFixed(4)} · tp2 {s.tp2?.toFixed(4)}
                </div>
              </div>

              {/* Right: outcome */}
              <div style={{ textAlign: 'right', minWidth: 100 }}>
                <div
                  className="num"
                  style={{
                    fontSize: F.lg,
                    fontWeight: 800,
                    color: win ? C.bear : C.bull,
                    fontFamily: "'JetBrains Mono', monospace",
                  }}
                >
                  {fmtPct(s.hypothetical_pnl_pct, 2)}
                </div>
                <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>
                  {s.would_hit_tp2 ? 'TP2' : s.would_hit_tp1 ? 'TP1' : s.would_hit_sl ? 'SL' : '—'}
                  <span style={{ marginLeft: 6, opacity: 0.7 }}>
                    {win ? 'missed win' : 'avoided loss'}
                  </span>
                </div>
              </div>
            </div>
          );
        })}

        {data && data.signals.length === 0 && (
          <div
            style={{
              padding: 40,
              textAlign: 'center',
              color: C.muted,
              fontSize: F.sm,
              border: `1px dashed ${C.border}`,
              borderRadius: R.md,
            }}
          >
            No counterfactuals match these filters.
          </div>
        )}
      </div>
    </Layout>
  );
}
