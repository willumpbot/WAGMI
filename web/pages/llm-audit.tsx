/**
 * /llm-audit — LLM Cost & Model Routing Audit
 *
 * Tracks LLM spending and optimizes model routing (Haiku/Sonnet/Opus).
 * Shows cost per decision type, trigger×model matrix, and historical trends.
 * Use this to understand where money is spent and find savings.
 *
 * Dashboard pages: /ai-decisions, /agent-intelligence, /llm-audit
 * Full guide: docs/AI-PAGES-GUIDE.md
 */
'use client';

import React, { useEffect, useState, useMemo } from 'react';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { C, R, F, S, G, Glass, SP, fmtPct } from '../src/theme';
import { staggerContainer, fadeUp, hoverGlow } from '../src/animations';
import type { LlmDecision, LlmFeedResponse } from '../src/types';
import { resolveApiBase } from '../src/api';

function Skeleton({ h = 16, w = '100%' }: { h?: number; w?: string | number }) {
  return <div className="skeleton" style={{ height: h, width: w, borderRadius: R.sm }} />;
}

function timeAgo(isoOrTs: string | number | null | undefined): string {
  if (!isoOrTs) return '';
  try {
    const ts = typeof isoOrTs === 'number' ? isoOrTs * 1000 : new Date(isoOrTs).getTime();
    const diff = Math.floor((Date.now() - ts) / 1000);
    if (diff < 60) return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  } catch { return ''; }
}

/** Format a cost value — show "<$0.01" for sub-cent amounts to avoid "$0.0000" */
function fmtCost(cost: number): string {
  if (cost <= 0) return '$0.00';
  if (cost < 0.01) return '<$0.01';
  if (cost < 1) return `$${cost.toFixed(3)}`;
  return `$${cost.toFixed(2)}`;
}

// ─── Model Routing Chart ──────────────────────────────────────────────────────

function ModelRoutingChart({ decisions }: { decisions: LlmDecision[] }) {
  const counts: Record<string, number> = {};
  decisions.forEach((d) => {
    const model = d.model || 'unknown';
    const key = model.includes('haiku') ? 'Haiku' : model.includes('sonnet') ? 'Sonnet' : model.includes('opus') ? 'Opus' : 'Other';
    counts[key] = (counts[key] || 0) + 1;
  });
  const total = decisions.length || 1;

  const modelColors: Record<string, string> = {
    Haiku: C.warn,
    Sonnet: C.info,
    Opus: C.purple,
    Other: C.muted,
  };

  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);

  // Trigger × Model matrix
  const triggerModel: Record<string, Record<string, number>> = {};
  decisions.forEach((d) => {
    const trigger = d.trigger || 'unknown';
    const model = d.model?.includes('haiku') ? 'Haiku' : d.model?.includes('sonnet') ? 'Sonnet' : d.model?.includes('opus') ? 'Opus' : 'Other';
    if (!triggerModel[trigger]) triggerModel[trigger] = {};
    triggerModel[trigger][model] = (triggerModel[trigger][model] || 0) + 1;
  });
  const triggers = Object.keys(triggerModel).filter((t) => t !== 'unknown');
  const models = ['Haiku', 'Sonnet', 'Opus', 'Other'];

  return (
    <div>
      {/* Stacked bar */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ height: 20, borderRadius: R.pill, overflow: 'hidden', display: 'flex', marginBottom: 8 }}>
          {entries.map(([model, count]) => (
            <div
              key={model}
              title={`${model}: ${count} (${((count / total) * 100).toFixed(0)}%)`}
              style={{ flex: count, background: modelColors[model] || C.muted, transition: 'flex 0.4s' }}
            />
          ))}
        </div>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          {entries.map(([model, count]) => (
            <div key={model} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: modelColors[model] || C.muted, display: 'inline-block' }} />
              <span style={{ fontSize: F.xs, fontWeight: 600, color: modelColors[model] || C.muted }}>{model}</span>
              <span style={{ fontSize: F.xs, color: C.muted }}>{count} ({((count / total) * 100).toFixed(0)}%)</span>
            </div>
          ))}
        </div>
      </div>

      {/* Trigger × Model matrix */}
      {triggers.length > 0 && (
        <div style={{ overflowX: 'auto', marginTop: 16 }}>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 8, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5 }}>
            Trigger → Model Routing Matrix
          </div>
          <table style={{ borderCollapse: 'collapse', fontSize: F.xs, minWidth: 400 }}>
            <thead>
              <tr>
                <th style={{ padding: '6px 10px', textAlign: 'left', color: C.muted, fontWeight: 600, borderBottom: `1px solid ${C.border}` }}>Trigger</th>
                {models.map((m) => (
                  <th key={m} style={{ padding: '6px 10px', textAlign: 'right', color: modelColors[m] || C.muted, fontWeight: 700, borderBottom: `1px solid ${C.border}` }}>{m}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {triggers.map((trigger) => (
                <tr key={trigger} style={{ borderBottom: `1px solid ${C.border}` }}>
                  <td style={{ padding: '6px 10px', color: C.textSub, fontWeight: 600 }}>{trigger}</td>
                  {models.map((m) => {
                    const count = triggerModel[trigger]?.[m] || 0;
                    return (
                      <td key={m} style={{ padding: '6px 10px', textAlign: 'right', color: count > 0 ? modelColors[m] : C.faint, fontWeight: count > 0 ? 700 : 400, fontVariantNumeric: 'tabular-nums' }}>
                        {count || '—'}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Confidence Calibration Chart ─────────────────────────────────────────────

function ConfCalibration({ decisions }: { decisions: LlmDecision[] }) {
  const buckets = [
    { label: '0–20%', min: 0, max: 0.20 },
    { label: '20–40%', min: 0.20, max: 0.40 },
    { label: '40–60%', min: 0.40, max: 0.60 },
    { label: '60–80%', min: 0.60, max: 0.80 },
    { label: '80–100%', min: 0.80, max: 1.01 },
  ];

  type BucketStats = { total: number; proceed: number; veto: number; skip: number };

  const stats: BucketStats[] = buckets.map(({ min, max }) => {
    const members = decisions.filter((d) => {
      const c = Number.isFinite(d.confidence) ? d.confidence : 0;
      return c >= min && c < max;
    });
    const total = members.length;
    const proceed = members.filter((d) => ['proceed', 'go'].includes((d.action || '').toLowerCase())).length;
    const veto = members.filter((d) => d.is_veto || (d.action || '').toLowerCase() === 'veto').length;
    const skip = total - proceed - veto;
    return { total, proceed, veto, skip };
  });

  const hasData = stats.some((s) => s.total > 0);

  // SVG layout
  const W = 700;
  const H = 140;
  const padL = 36;
  const padR = 12;
  const padTop = 16;
  const padBot = 36;
  const chartW = W - padL - padR;
  const chartH = H - padTop - padBot;
  const barGroupW = chartW / buckets.length;
  const barW = Math.min(28, barGroupW * 0.28);
  const gap = 2;

  const yTicks = [0, 25, 50, 75, 100];

  return (
    <div>
      <div style={{ fontWeight: 700, fontSize: F.sm, color: C.text, marginBottom: 2 }}>Is the AI Well-Calibrated?</div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 14 }}>
        Ideally, higher confidence → more GO decisions, fewer vetoes
      </div>

      {!hasData ? (
        <div style={{ color: C.faint, fontSize: F.xs, padding: '12px 0' }}>Not enough data yet to show calibration.</div>
      ) : (
        <>
          <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: W, display: 'block' }}>
            {/* Y grid lines & labels */}
            {yTicks.map((tick) => {
              const y = padTop + chartH - (tick / 100) * chartH;
              return (
                <g key={tick}>
                  <line x1={padL} y1={y} x2={W - padR} y2={y} stroke={C.border} strokeWidth={1} strokeDasharray={tick === 0 ? '0' : '3 3'} />
                  <text x={padL - 4} y={y + 4} textAnchor="end" fontSize={9} fill={C.faint}>{tick}</text>
                </g>
              );
            })}

            {/* Bars per bucket */}
            {stats.map((s, i) => {
              const cx = padL + i * barGroupW + barGroupW / 2;
              const proceedPct = s.total > 0 ? (s.proceed / s.total) * 100 : 0;
              const vetoPct = s.total > 0 ? (s.veto / s.total) * 100 : 0;
              const skipPct = s.total > 0 ? (s.skip / s.total) * 100 : 0;

              const bars = [
                { pct: proceedPct, color: C.bull, label: 'GO' },
                { pct: vetoPct, color: C.bear, label: 'VETO' },
                { pct: skipPct, color: C.muted, label: 'SKIP' },
              ];

              return (
                <g key={i}>
                  {bars.map((bar, bi) => {
                    const x = cx - (3 * barW + 2 * gap) / 2 + bi * (barW + gap);
                    const barH = (bar.pct / 100) * chartH;
                    const y = padTop + chartH - barH;
                    return (
                      <g key={bi}>
                        <rect
                          x={x}
                          y={barH > 0 ? y : padTop + chartH}
                          width={barW}
                          height={Math.max(barH, 0)}
                          fill={bar.color}
                          opacity={s.total === 0 ? 0.2 : 0.85}
                          rx={2}
                        >
                          <title>{`${buckets[i].label} · ${bar.label}: ${bar.pct.toFixed(0)}% (${s.total} decisions)`}</title>
                        </rect>
                        {barH > 10 && (
                          <text x={x + barW / 2} y={y + 10} textAnchor="middle" fontSize={8} fill="#fff" fontWeight={700}>
                            {bar.pct.toFixed(0)}
                          </text>
                        )}
                      </g>
                    );
                  })}
                  {/* X label */}
                  <text x={cx} y={H - padBot + 14} textAnchor="middle" fontSize={9} fill={C.muted}>
                    {buckets[i].label}
                  </text>
                  {/* n= label */}
                  <text x={cx} y={H - padBot + 26} textAnchor="middle" fontSize={8} fill={C.faint}>
                    n={s.total}
                  </text>
                </g>
              );
            })}
          </svg>

          {/* Legend */}
          <div style={{ display: 'flex', gap: 16, marginTop: 8 }}>
            {[{ label: 'GO / Proceed', color: C.bull }, { label: 'Veto', color: C.bear }, { label: 'Skip', color: C.muted }].map(({ label, color }) => (
              <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 10, height: 10, borderRadius: 2, background: color, display: 'inline-block', opacity: 0.85 }} />
                <span style={{ fontSize: F.xs, color: C.textSub }}>{label}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

// ─── Decision Activity Heatmap ─────────────────────────────────────────────────

function DecisionActivityMap({ decisions }: { decisions: LlmDecision[] }) {
  // Build a density map: day (0–6, last 7 days) × hour-block (0–5, each 4 hours)
  const DAYS = 7;
  const HOUR_BLOCKS = 6; // 0-3, 4-7, 8-11, 12-15, 16-19, 20-23
  const BLOCK_SIZE = 4;

  const density: number[][] = Array.from({ length: DAYS }, () => Array(HOUR_BLOCKS).fill(0));

  const now = Date.now();
  const windowMs = DAYS * 24 * 3600 * 1000;
  let mostActiveHour = -1;
  let mostActiveCount = 0;
  const hourTotal: number[] = Array(24).fill(0);

  let hasTimestamps = false;

  decisions.forEach((d) => {
    const raw = d.ts_iso || d.ts;
    if (!raw) return;
    try {
      const ts = typeof raw === 'number' ? raw * 1000 : new Date(raw).getTime();
      if (isNaN(ts)) return;
      const age = now - ts;
      if (age < 0 || age > windowMs) return;
      hasTimestamps = true;
      const dayIdx = DAYS - 1 - Math.floor(age / (24 * 3600 * 1000));
      const date = new Date(ts);
      const hour = date.getHours();
      const blockIdx = Math.floor(hour / BLOCK_SIZE);
      if (dayIdx >= 0 && dayIdx < DAYS && blockIdx >= 0 && blockIdx < HOUR_BLOCKS) {
        density[dayIdx][blockIdx]++;
      }
      hourTotal[hour]++;
    } catch { /* skip */ }
  });

  // Find most active hour
  hourTotal.forEach((count, h) => {
    if (count > mostActiveCount) { mostActiveCount = count; mostActiveHour = h; }
  });

  const maxDensity = Math.max(1, ...density.flat());

  const CELL_W = 18;
  const CELL_H = 12;
  const GAP = 2;
  const PAD_L = 46;
  const PAD_T = 18;
  const totalW = PAD_L + DAYS * (CELL_W + GAP);
  const totalH = PAD_T + HOUR_BLOCKS * (CELL_H + GAP) + 20;

  // Day labels: last 7 days as Mon/Tue etc.
  const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  const BLOCK_LABELS = ['0h', '4h', '8h', '12h', '16h', '20h'];

  const dayLabels = Array.from({ length: DAYS }, (_, i) => {
    const d = new Date(now - (DAYS - 1 - i) * 24 * 3600 * 1000);
    return DAY_LABELS[d.getDay()];
  });

  const fmtHour = (h: number) => {
    if (h < 0) return '—';
    const ampm = h < 12 ? 'am' : 'pm';
    const disp = h % 12 === 0 ? 12 : h % 12;
    return `${disp}${ampm}`;
  };

  // Brand color hex — extract base for opacity trick via SVG fill-opacity
  const brandBase = C.brand;

  if (!hasTimestamps) {
    return (
      <div style={{ color: C.faint, fontSize: F.xs, padding: '8px 0' }}>
        No timestamp data available to build activity map.
      </div>
    );
  }

  return (
    <div style={{ marginTop: 20 }}>
      <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10 }}>
        Decision Activity (Last 7 Days)
      </div>
      <svg viewBox={`0 0 ${totalW} ${totalH}`} style={{ width: totalW, maxWidth: '100%', display: 'block' }}>
        {/* Day column headers */}
        {dayLabels.map((label, di) => (
          <text
            key={di}
            x={PAD_L + di * (CELL_W + GAP) + CELL_W / 2}
            y={PAD_T - 4}
            textAnchor="middle"
            fontSize={8}
            fill={C.faint}
          >
            {label}
          </text>
        ))}

        {/* Hour-block row labels */}
        {BLOCK_LABELS.map((label, bi) => (
          <text
            key={bi}
            x={PAD_L - 4}
            y={PAD_T + bi * (CELL_H + GAP) + CELL_H / 2 + 3}
            textAnchor="end"
            fontSize={8}
            fill={C.faint}
          >
            {label}
          </text>
        ))}

        {/* Cells */}
        {Array.from({ length: DAYS }, (_, di) =>
          Array.from({ length: HOUR_BLOCKS }, (_, bi) => {
            const count = density[di][bi];
            const intensity = count / maxDensity;
            const x = PAD_L + di * (CELL_W + GAP);
            const y = PAD_T + bi * (CELL_H + GAP);
            return (
              <rect
                key={`${di}-${bi}`}
                x={x}
                y={y}
                width={CELL_W}
                height={CELL_H}
                rx={2}
                fill={brandBase}
                fillOpacity={count === 0 ? 0.06 : 0.12 + intensity * 0.78}
                stroke={C.border}
                strokeWidth={0.5}
              >
                <title>{`${dayLabels[di]} ${BLOCK_LABELS[bi]}–${BLOCK_LABELS[bi + 1] ?? '24h'}: ${count} decision${count !== 1 ? 's' : ''}`}</title>
              </rect>
            );
          })
        )}
      </svg>

      {mostActiveHour >= 0 && mostActiveCount > 0 && (
        <div style={{ fontSize: F.xs, color: C.muted, marginTop: 6 }}>
          Most active: <span style={{ color: C.brand, fontWeight: 700 }}>{fmtHour(mostActiveHour)}</span>
          <span style={{ color: C.faint }}> ({mostActiveCount} decisions)</span>
        </div>
      )}
    </div>
  );
}

// ─── Veto Analysis ────────────────────────────────────────────────────────────

function VetoAnalysis({ decisions }: { decisions: LlmDecision[] }) {
  const vetoes = decisions.filter((d) => d.is_veto);
  if (!vetoes.length) {
    return <div style={{ color: C.muted, fontSize: F.sm, padding: '16px 0' }}>No veto decisions recorded yet.</div>;
  }

  const bySymbol: Record<string, number> = {};
  const byRegime: Record<string, number> = {};
  const byReason: Record<string, number> = {};

  vetoes.forEach((v) => {
    if (v.symbol) bySymbol[v.symbol] = (bySymbol[v.symbol] || 0) + 1;
    if (v.regime) byRegime[v.regime] = (byRegime[v.regime] || 0) + 1;
    if (v.gate_reason) {
      const key = v.gate_reason.length > 40 ? v.gate_reason.substring(0, 40) + '…' : v.gate_reason;
      byReason[key] = (byReason[key] || 0) + 1;
    }
  });

  const sortedEntries = (obj: Record<string, number>) => Object.entries(obj).sort((a, b) => b[1] - a[1]);

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 16 }}>
      {[
        { title: 'By Symbol', entries: sortedEntries(bySymbol), color: C.info },
        { title: 'By Regime', entries: sortedEntries(byRegime), color: C.bear },
        { title: 'By Reason (truncated)', entries: sortedEntries(byReason).slice(0, 5), color: C.warn },
      ].map(({ title, entries, color }) => (
        <div key={title}>
          <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>{title}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {entries.slice(0, 6).map(([key, count]) => (
              <div key={key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: F.xs, color: C.textSub, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{key}</span>
                <span style={{ fontSize: F.xs, fontWeight: 700, color, flexShrink: 0, minWidth: 28, textAlign: 'right' }}>{count}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Symbol Decision Grid ─────────────────────────────────────────────────────

function SymbolDecisionGrid({ decisions }: { decisions: LlmDecision[] }) {
  if (!decisions.length) return null;

  // Build per-symbol stats
  const bySymbol: Record<string, { proceed: number; skip: number; veto: number; total: number; avgConf: number; confSum: number }> = {};
  decisions.forEach((d) => {
    const sym = d.symbol || 'UNKNOWN';
    if (!bySymbol[sym]) bySymbol[sym] = { proceed: 0, skip: 0, veto: 0, total: 0, avgConf: 0, confSum: 0 };
    bySymbol[sym].total++;
    bySymbol[sym].confSum += d.confidence ?? 0;
    if (d.is_veto) bySymbol[sym].veto++;
    else if (['proceed', 'go'].includes((d.action || '').toLowerCase())) bySymbol[sym].proceed++;
    else bySymbol[sym].skip++;
  });
  Object.values(bySymbol).forEach((v) => { v.avgConf = v.total > 0 ? v.confSum / v.total : 0; });

  const symbols = Object.entries(bySymbol).sort((a, b) => b[1].total - a[1].total).slice(0, 8);
  if (symbols.length === 0) return null;

  return (
    <div className="card-hover glass-noise" style={{ ...Glass.crystal, borderRadius: R.xl, padding: '20px 24px', marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Per-Symbol Decision Breakdown</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>GO / SKIP / VETO count per symbol with avg confidence</div>
        </div>
        <div style={{ display: 'flex', gap: 12, fontSize: 10 }}>
          {[['GO', C.bull], ['SKIP', C.muted], ['VETO', C.bear]].map(([label, color]) => (
            <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 4, color: color as string }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: color as string, display: 'inline-block' }} />
              {label}
            </span>
          ))}
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {symbols.map(([sym, s]) => {
          const goW = s.total > 0 ? (s.proceed / s.total) * 100 : 0;
          const skipW = s.total > 0 ? (s.skip / s.total) * 100 : 0;
          const vetoW = s.total > 0 ? (s.veto / s.total) * 100 : 0;
          const confPct = Math.round(s.avgConf * 100);
          const confColor = confPct >= 65 ? C.bull : confPct >= 42 ? C.warn : C.bear;
          return (
            <div key={sym} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 48, fontSize: F.xs, fontWeight: 800, color: C.text, flexShrink: 0, textAlign: 'right' }}>{sym}</span>
              {/* Stacked bar */}
              <div style={{ flex: 1, height: 16, borderRadius: R.pill, overflow: 'hidden', display: 'flex', background: C.surface, minWidth: 100 }}>
                {goW > 0 && (
                  <div
                    title={`GO: ${s.proceed}`}
                    style={{ width: `${goW}%`, background: C.bull, opacity: 0.85, transition: 'width 0.3s' }}
                  />
                )}
                {skipW > 0 && (
                  <div
                    title={`SKIP: ${s.skip}`}
                    style={{ width: `${skipW}%`, background: C.muted, opacity: 0.5, transition: 'width 0.3s' }}
                  />
                )}
                {vetoW > 0 && (
                  <div
                    title={`VETO: ${s.veto}`}
                    style={{ width: `${vetoW}%`, background: C.bear, opacity: 0.85, transition: 'width 0.3s' }}
                  />
                )}
              </div>
              {/* Counts */}
              <span style={{ fontSize: 10, color: C.muted, width: 80, flexShrink: 0, fontVariantNumeric: 'tabular-nums' }}>
                {s.proceed}G·{s.skip}S·{s.veto}V
              </span>
              {/* Avg confidence */}
              <span style={{ fontSize: 10, fontWeight: 700, color: confColor, width: 36, flexShrink: 0, textAlign: 'right' }}>{confPct}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Action Rate Timeline ─────────────────────────────────────────────────────

function ActionRateTimeline({ decisions }: { decisions: LlmDecision[] }) {
  if (decisions.length < 6) return null;

  // Group decisions into N time buckets and show GO/VETO/SKIP rate per bucket
  const BUCKETS = 10;
  const sorted = [...decisions].sort((a, b) => a.ts - b.ts);
  const bucketSize = Math.ceil(sorted.length / BUCKETS);
  const buckets: Array<{ go: number; veto: number; skip: number; total: number }> = [];

  for (let i = 0; i < sorted.length; i += bucketSize) {
    const slice = sorted.slice(i, i + bucketSize);
    buckets.push({
      go: slice.filter((d) => d.action === 'proceed' || d.action === 'go').length,
      veto: slice.filter((d) => d.is_veto).length,
      skip: slice.filter((d) => d.action === 'flat' || d.action === 'skip').length,
      total: slice.length,
    });
  }

  const W = 600, H = 120;
  const pad = { t: 12, r: 12, b: 24, l: 32 };
  const iW = W - pad.l - pad.r;
  const iH = H - pad.t - pad.b;
  const bW = (iW / buckets.length) - 2;

  const maxH = Math.max(...buckets.map((b) => b.total), 1);

  return (
    <div className="card-hover glass-noise" style={{ ...Glass.crystal, borderRadius: R.xl, padding: '20px 24px', marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Decision Action Rate Over Time</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>GO / VETO / SKIP distribution across chronological decision windows</div>
        </div>
        <div style={{ display: 'flex', gap: 12, fontSize: 10 }}>
          {[['GO', C.bull], ['VETO', C.bear], ['SKIP', C.muted]].map(([label, color]) => (
            <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 4, color: color as string }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: color as string, display: 'inline-block' }} />
              {label}
            </span>
          ))}
        </div>
      </div>

      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', overflow: 'visible' }}>
        {/* Y grid */}
        {[0, 0.5, 1].map((frac) => {
          const y = pad.t + iH * (1 - frac);
          const count = Math.round(frac * maxH);
          return (
            <g key={frac}>
              <line x1={pad.l} y1={y} x2={pad.l + iW} y2={y} stroke={C.border} strokeWidth={0.5} strokeDasharray="3 4" />
              <text x={pad.l - 4} y={y + 3} textAnchor="end" fontSize={8} fill={C.muted}>{count}</text>
            </g>
          );
        })}

        {/* Stacked bars */}
        {buckets.map((b, i) => {
          const x = pad.l + i * (iW / buckets.length) + 1;
          const goH = (b.go / maxH) * iH;
          const vetoH = (b.veto / maxH) * iH;
          const skipH = (b.skip / maxH) * iH;
          const baseY = pad.t + iH;

          return (
            <g key={i}>
              {/* Skip (bottom) */}
              {skipH > 0 && <rect x={x} y={baseY - skipH} width={bW} height={skipH} fill={C.muted} opacity={0.4} rx={1} />}
              {/* Veto (middle) */}
              {vetoH > 0 && <rect x={x} y={baseY - skipH - vetoH} width={bW} height={vetoH} fill={C.bear} opacity={0.8} rx={1} />}
              {/* Go (top) */}
              {goH > 0 && <rect x={x} y={baseY - skipH - vetoH - goH} width={bW} height={goH} fill={C.bull} opacity={0.85} rx={1} />}
            </g>
          );
        })}

        {/* X axis labels: first and last */}
        {sorted.length > 0 && (
          <>
            <text x={pad.l} y={pad.t + iH + 14} fontSize={8} fill={C.muted} textAnchor="start">
              {new Date(sorted[0].ts * 1000).toLocaleDateString()}
            </text>
            <text x={pad.l + iW} y={pad.t + iH + 14} fontSize={8} fill={C.muted} textAnchor="end">
              {new Date(sorted[sorted.length - 1].ts * 1000).toLocaleDateString()}
            </text>
          </>
        )}
      </svg>
    </div>
  );
}

// ─── Trigger Breakdown Chart ──────────────────────────────────────────────────

function TriggerBreakdownChart({ decisions }: { decisions: LlmDecision[] }) {
  if (!decisions.length) return null;

  // Build trigger stats
  const byTrigger: Record<string, { total: number; proceed: number; veto: number; skip: number; avgConf: number; confSum: number }> = {};
  for (const d of decisions) {
    const t = d.trigger || 'unknown';
    if (!byTrigger[t]) byTrigger[t] = { total: 0, proceed: 0, veto: 0, skip: 0, avgConf: 0, confSum: 0 };
    byTrigger[t].total++;
    byTrigger[t].confSum += d.confidence ?? 0;
    const action = (d.action || '').toLowerCase();
    if (d.is_veto) byTrigger[t].veto++;
    else if (['proceed', 'go'].includes(action)) byTrigger[t].proceed++;
    else byTrigger[t].skip++;
  }
  for (const v of Object.values(byTrigger)) v.avgConf = v.total ? v.confSum / v.total : 0;

  const sorted = Object.entries(byTrigger).sort((a, b) => b[1].total - a[1].total).slice(0, 8);
  const maxTotal = sorted[0]?.[1].total || 1;

  const triggerShort: Record<string, string> = {
    PRE_TRADE: 'Pre-Trade',
    REGIME_SHIFT: 'Regime',
    PERIODIC: 'Periodic',
    POSITION_CLOSED: 'Pos.Closed',
    HIGH_CONFIDENCE: 'Hi-Conf',
    MEMORY_EVENT: 'Memory',
    STARTUP: 'Startup',
    unknown: 'Unknown',
  };

  return (
    <div className="card-hover glass-noise" style={{ ...Glass.crystal, borderRadius: R.lg, padding: '20px 24px', marginBottom: 24 }}>
      <h2 style={{ margin: '0 0 4px', fontSize: 16, fontWeight: 700, color: C.text }}>Trigger Breakdown</h2>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 16 }}>
        Which triggers fire most often — and what the AI decides for each
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {sorted.map(([trigger, s]) => {
          const proceedW = s.total ? (s.proceed / s.total) * 100 : 0;
          const skipW = s.total ? (s.skip / s.total) * 100 : 0;
          const vetoW = s.total ? (s.veto / s.total) * 100 : 0;
          const barW = (s.total / maxTotal) * 100;
          const avgConfPct = Math.round(s.avgConf * 100);
          return (
            <div key={trigger}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                <div style={{ width: 90, flexShrink: 0, fontSize: F.xs, color: C.textSub, fontWeight: 600 }}>
                  {triggerShort[trigger] || trigger.replace('_', ' ').slice(0, 10)}
                </div>
                {/* Stacked bar */}
                <div style={{ flex: 1, height: 20, background: C.surfaceHover, borderRadius: R.sm, overflow: 'hidden', position: 'relative' }}>
                  <div style={{ display: 'flex', height: '100%', width: `${barW}%` }}>
                    <div style={{ width: `${proceedW}%`, background: C.bull, opacity: 0.85 }} />
                    <div style={{ width: `${skipW}%`, background: C.muted, opacity: 0.5 }} />
                    <div style={{ width: `${vetoW}%`, background: C.bear, opacity: 0.85 }} />
                  </div>
                </div>
                {/* Count + conf */}
                <div style={{ minWidth: 70, display: 'flex', gap: 8, fontSize: F.xs, color: C.muted, flexShrink: 0 }}>
                  <span style={{ fontWeight: 700, color: C.text }}>{s.total}</span>
                  <span style={{ color: avgConfPct >= 65 ? C.bull : avgConfPct >= 42 ? C.warn : C.bear }}>
                    {avgConfPct}%
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, marginTop: 12, fontSize: F.xs, color: C.muted }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.bull, borderRadius: 2, display: 'inline-block' }} />GO
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.muted, opacity: 0.6, borderRadius: 2, display: 'inline-block' }} />SKIP
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 10, height: 10, background: C.bear, borderRadius: 2, display: 'inline-block' }} />VETO
        </span>
        <span style={{ marginLeft: 'auto' }}>Bar width = relative frequency · % = avg confidence</span>
      </div>
    </div>
  );
}

// ─── Decision Row ─────────────────────────────────────────────────────────────

function DecisionRow({ d }: { d: LlmDecision }) {
  const [expanded, setExpanded] = useState(false);

  const actionColors: Record<string, { bg: string; text: string }> = {
    proceed: { bg: C.bull + '18', text: C.bullMid },
    go: { bg: C.bull + '18', text: C.bullMid },
    skip: { bg: C.surfaceHover, text: C.muted },
    flat: { bg: C.surfaceHover, text: C.muted },
    flip: { bg: C.purple + '18', text: '#c4b5fd' },
    veto: { bg: C.bear + '18', text: C.bearMid },
    unknown: { bg: C.surfaceHover, text: C.faint },
  };

  const actionStyle = actionColors[(d.action || '').toLowerCase()] || actionColors.unknown;
  const modelTag = d.model?.includes('haiku') ? 'Haiku' : d.model?.includes('sonnet') ? 'Sonnet' : d.model?.includes('opus') ? 'Opus' : d.model || '';
  const modelColor = modelTag === 'Haiku' ? C.warn : modelTag === 'Sonnet' ? C.info : C.purple;
  const confPct = Math.round(Math.min(100, Math.max(0, (Number.isFinite(d.confidence) ? d.confidence : 0) * 100)));
  const confColor = confPct >= 65 ? C.bull : confPct >= 42 ? C.warn : C.bear;

  return (
    <div style={{ borderBottom: `1px solid ${C.border}` }}>
      <button
        onClick={() => setExpanded((v) => !v)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 8, padding: '10px 16px',
          background: 'none', border: 'none', cursor: 'pointer', textAlign: 'left', flexWrap: 'wrap',
        }}
      >
        {/* Timestamp */}
        <span style={{ fontSize: F.xs, color: C.faint, minWidth: 60, flexShrink: 0 }}>
          {timeAgo(d.ts_iso || d.ts)}
        </span>

        {/* Symbol */}
        {d.symbol && (
          <span style={{ fontSize: F.sm, fontWeight: 800, color: C.text, minWidth: 36 }}>{d.symbol}</span>
        )}

        {/* Action badge */}
        <span style={{
          fontSize: F.xs, fontWeight: 700, padding: '2px 8px', borderRadius: R.pill,
          background: actionStyle.bg, color: actionStyle.text,
        }}>
          {(d.action || 'UNKNOWN').toUpperCase()}
          {d.is_veto && ' — VETOED'}
        </span>

        {/* Confidence */}
        <span style={{ fontSize: F.xs, fontWeight: 700, color: confColor, minWidth: 36 }}>{confPct}%</span>

        {/* Regime */}
        {d.regime && (
          <span style={{ fontSize: F.xs, padding: '2px 6px', borderRadius: R.pill, background: C.surfaceHover, color: C.muted, textTransform: 'capitalize' }}>
            {d.regime}
          </span>
        )}

        {/* Model */}
        {modelTag && (
          <span style={{ fontSize: F.xs, fontWeight: 600, color: modelColor }}>{modelTag}</span>
        )}

        {/* Trigger */}
        {d.trigger && (
          <span style={{ fontSize: F.xs, color: C.faint }}>{d.trigger}</span>
        )}

        {/* Gate blocked badge */}
        {!d.allowed && d.gate_reason && (
          <span style={{ fontSize: F.xs, padding: '2px 6px', borderRadius: R.pill, background: C.warn + '18', color: C.warn, fontWeight: 600 }}>
            BLOCKED
          </span>
        )}

        <span style={{ marginLeft: 'auto', color: C.faint, fontSize: 11, transform: expanded ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}>▼</span>
      </button>

      {expanded && d.notes && (
        <div style={{ padding: '0 16px 12px', borderTop: `1px solid ${C.border}` }}>
          <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 6, marginTop: 10 }}>
            LLM Reasoning
          </div>
          <div style={{ fontSize: F.xs, color: C.textSub, lineHeight: 1.7, fontStyle: 'italic' }}>
            {d.notes}
          </div>
          {d.gate_reason && (
            <div style={{ marginTop: 8, fontSize: F.xs, color: C.warn }}>
              <strong>Gate reason:</strong> {d.gate_reason}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Confidence Histogram ─────────────────────────────────────────────────────

function ConfidenceHistogram({ decisions }: { decisions: LlmDecision[] }) {
  const BUCKET_COUNT = 10;
  const counts = Array(BUCKET_COUNT).fill(0);

  let confSum = 0;
  let confCount = 0;

  decisions.forEach((d) => {
    const c = Math.min(100, Math.max(0, (Number.isFinite(d.confidence) ? d.confidence : 0) * 100));
    const idx = Math.min(Math.floor(c / 10), BUCKET_COUNT - 1);
    counts[idx]++;
    confSum += c;
    confCount++;
  });

  const total = decisions.length;
  const mean = confCount > 0 ? confSum / confCount : 0;
  const maxCount = Math.max(1, ...counts);

  // SVG dimensions
  const W = 360;
  const H = 120;
  const padL = 28;
  const padR = 10;
  const padTop = 20;
  const padBot = 28;
  const chartW = W - padL - padR;
  const chartH = H - padTop - padBot;
  const barW = (chartW / BUCKET_COUNT) - 3;

  // Threshold line at 75% (bucket index 7.5 → pixel)
  const thresholdPx = padL + (75 / 100) * chartW;

  const getBucketColor = (bucketIndex: number): string => {
    const lo = bucketIndex * 10;
    if (lo < 50) return C.bear + 'bb';
    if (lo < 75) return C.warn + 'cc';
    if (lo < 90) return C.brand + 'dd';
    return C.bull + 'ee';
  };

  return (
    <div>
      <div style={{ fontWeight: 700, fontSize: F.sm, color: C.text, marginBottom: 2 }}>
        Confidence Score Distribution
      </div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 10 }}>
        {total} decisions · mean {mean.toFixed(0)}%
      </div>

      {total === 0 ? (
        <div style={{ color: C.faint, fontSize: F.xs, padding: '12px 0' }}>No decision data to display.</div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', maxWidth: W, display: 'block', overflow: 'visible' }}>
          {/* Y-axis baseline */}
          <line x1={padL} y1={padTop + chartH} x2={W - padR} y2={padTop + chartH} stroke={C.border} strokeWidth={1} />

          {/* Bars */}
          {counts.map((count, i) => {
            const barH = (count / maxCount) * chartH;
            const x = padL + i * (chartW / BUCKET_COUNT) + 1.5;
            const y = padTop + chartH - barH;
            const isAboveThreshold = i * 10 >= 75;
            return (
              <g key={i}>
                <rect
                  x={x}
                  y={barH > 0 ? y : padTop + chartH}
                  width={barW}
                  height={Math.max(barH, 0)}
                  fill={getBucketColor(i)}
                  rx={2}
                >
                  <title>{`${i * 10}–${i * 10 + 9}%: ${count} decision${count !== 1 ? 's' : ''}`}</title>
                </rect>
                {/* Count label at top of bar */}
                {count === maxCount && count > 0 && (
                  <text
                    x={x + barW / 2}
                    y={y - 4}
                    textAnchor="middle"
                    fontSize={8}
                    fill={C.textSub}
                    fontWeight={700}
                  >
                    {count}
                  </text>
                )}
                {/* X-axis label */}
                <text
                  x={x + barW / 2}
                  y={H - padBot + 12}
                  textAnchor="middle"
                  fontSize={8}
                  fill={isAboveThreshold ? C.brand : C.faint}
                >
                  {i * 10}
                </text>
              </g>
            );
          })}

          {/* Final x-axis label: 100 */}
          <text
            x={padL + chartW}
            y={H - padBot + 12}
            textAnchor="middle"
            fontSize={8}
            fill={C.faint}
          >
            100
          </text>

          {/* Threshold line at 75% */}
          <line
            x1={thresholdPx}
            y1={padTop - 4}
            x2={thresholdPx}
            y2={padTop + chartH}
            stroke={C.brand}
            strokeWidth={1.5}
            strokeDasharray="4 3"
          />
          {/* Threshold label */}
          <text
            x={thresholdPx + 4}
            y={padTop + 7}
            fontSize={8}
            fill={C.brand}
            fontWeight={700}
          >
            Bot threshold (75%)
          </text>
        </svg>
      )}
    </div>
  );
}

// ─── Token Usage Bar ──────────────────────────────────────────────────────────

function TokenUsageBar({ decisions }: { decisions: LlmDecision[] }) {
  if (!decisions.length) return null;

  const TOKENS: Record<string, number> = { haiku: 800, sonnet: 2000, opus: 4000 };
  const COST_PER_M: Record<string, number> = { haiku: 0.25, sonnet: 3.0, opus: 15.0 };

  const usage = { haiku: 0, sonnet: 0, opus: 0 };

  decisions.forEach((d) => {
    const m = (d.model || '').toLowerCase();
    if (m.includes('haiku')) usage.haiku += TOKENS.haiku;
    else if (m.includes('sonnet')) usage.sonnet += TOKENS.sonnet;
    else if (m.includes('opus')) usage.opus += TOKENS.opus;
    else usage.haiku += TOKENS.haiku; // default to haiku estimate
  });

  const totalTokens = usage.haiku + usage.sonnet + usage.opus;
  const totalCost =
    (usage.haiku / 1_000_000) * COST_PER_M.haiku +
    (usage.sonnet / 1_000_000) * COST_PER_M.sonnet +
    (usage.opus / 1_000_000) * COST_PER_M.opus;

  const avgTokens = decisions.length > 0 ? totalTokens / decisions.length : 0;

  const segments: Array<{ key: keyof typeof usage; label: string; color: string }> = [
    { key: 'haiku', label: 'Haiku', color: C.warn },
    { key: 'sonnet', label: 'Sonnet', color: C.info },
    { key: 'opus', label: 'Opus', color: C.purple },
  ];

  return (
    <div>
      <div style={{ fontWeight: 700, fontSize: F.sm, color: C.text, marginBottom: 2 }}>
        Estimated Token Usage
      </div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 10 }}>
        {decisions.length} decisions · ~{Math.round(avgTokens).toLocaleString()} tokens/decision
      </div>

      {/* Stacked bar */}
      <div style={{ height: 18, borderRadius: R.pill, overflow: 'hidden', display: 'flex', marginBottom: 8 }}>
        {segments.map(({ key, label, color }) => {
          const pct = totalTokens > 0 ? (usage[key] / totalTokens) * 100 : 0;
          return pct > 0 ? (
            <div
              key={key}
              title={`${label}: ~${(usage[key] / 1000).toFixed(0)}K tokens ($${((usage[key] / 1_000_000) * COST_PER_M[key]).toFixed(4)})`}
              style={{ width: `${pct}%`, background: color, opacity: 0.85, transition: 'width 0.4s' }}
            />
          ) : null;
        })}
      </div>

      {/* Legend + cost */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        {segments.map(({ key, label, color }) => {
          const pct = totalTokens > 0 ? (usage[key] / totalTokens) * 100 : 0;
          const cost = (usage[key] / 1_000_000) * COST_PER_M[key];
          return (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: color, display: 'inline-block', opacity: 0.85 }} />
              <span style={{ fontSize: F.xs, fontWeight: 600, color }}>{label}</span>
              <span style={{ fontSize: F.xs, color: C.muted }}>{pct.toFixed(0)}%</span>
              <span style={{ fontSize: F.xs, color: C.faint }}>{fmtCost(cost)}</span>
            </div>
          );
        })}
        <span style={{ marginLeft: 'auto', fontSize: F.xs, fontWeight: 700, color: C.textSub }}>
          ~{fmtCost(totalCost)} total
        </span>
      </div>
    </div>
  );
}

// ─── Agent Accuracy Matrix ────────────────────────────────────────────────────

function AgentAccuracyMatrix({ decisions }: { decisions: LlmDecision[] }) {
  const agentNames = ['Regime', 'Trade', 'Risk', 'Critic', 'Learning'];
  const agentColors: Record<string, string> = {
    Regime: C.info, Trade: C.brand, Risk: C.warn, Critic: C.bear, Learning: C.bull,
  };

  const agentCounts: Record<string, number> = {};
  decisions.forEach((d) => {
    const notes = (d.notes || '').toLowerCase();
    agentNames.forEach((name) => {
      if (notes.includes(name.toLowerCase())) {
        agentCounts[name] = (agentCounts[name] || 0) + 1;
      }
    });
  });

  return (
    <div className="card-hover glass-noise" style={{ ...Glass.crystal, borderRadius: R.xl, padding: '16px 18px', marginBottom: 20 }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 12 }}>Agent Activity</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {agentNames.map((name) => {
          const count = agentCounts[name] || 0;
          const color = agentColors[name];
          return (
            <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, flexShrink: 0, display: 'inline-block' }} />
              <span style={{ fontSize: F.xs, fontWeight: 700, color: C.textSub, width: 65 }}>{name}</span>
              <span style={{ fontSize: F.xs, color: C.muted }}>{count > 0 ? `${count} decisions` : 'No data yet'}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── Veto Frequency Bars ──────────────────────────────────────────────────────

function VetoFrequencyBars({ decisions }: { decisions: LlmDecision[] }) {
  const KEYWORDS = [
    { kw: 'overbought', group: 'confidence' },
    { kw: 'leverage', group: 'risk' },
    { kw: 'regime', group: 'regime' },
    { kw: 'confidence', group: 'confidence' },
    { kw: 'drawdown', group: 'risk' },
    { kw: 'volatility', group: 'regime' },
    { kw: 'position', group: 'risk' },
    { kw: 'liquidity', group: 'risk' },
  ] as const;

  type KwGroup = 'risk' | 'regime' | 'confidence';

  const kwColors: Record<KwGroup, string> = {
    risk: C.bear,
    regime: C.warn,
    confidence: C.brand,
  };

  const vetoes = decisions.filter((d) => d.is_veto);
  const totalVetoes = vetoes.length;

  // Count keyword occurrences in veto decisions
  const counts: Record<string, number> = {};
  KEYWORDS.forEach(({ kw }) => { counts[kw] = 0; });

  vetoes.forEach((d) => {
    const haystack = ((d.gate_reason || '') + ' ' + (d.notes || '')).toLowerCase();
    KEYWORDS.forEach(({ kw }) => {
      if (haystack.includes(kw)) counts[kw]++;
    });
  });

  const hasRealData = Object.values(counts).some((v) => v > 0);
  const displayCounts = counts;
  const displayTotal = totalVetoes;

  const sorted = KEYWORDS
    .map(({ kw, group }) => ({ kw, group, count: displayCounts[kw] ?? 0 }))
    .filter(({ count }) => count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);

  const maxCount = Math.max(1, ...sorted.map((r) => r.count));

  return (
    <div className="card-hover glass-noise" style={{ ...Glass.crystal, borderRadius: R.xl, padding: '20px 24px', marginBottom: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>Top Veto Reasons</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 3 }}>
            Keyword frequency in veto decisions
          </div>
        </div>
        <span style={{
          fontSize: F.xs, fontWeight: 700,
          padding: '3px 10px', borderRadius: R.pill,
          background: C.bear + '18', color: C.bear,
          flexShrink: 0,
        }}>
          {displayTotal} veto{displayTotal !== 1 ? 'es' : ''} in dataset
        </span>
      </div>

      {sorted.length === 0 ? (
        <div style={{ fontSize: F.xs, color: C.faint, padding: '12px 0' }}>No veto keyword data available.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {sorted.map(({ kw, group, count }) => {
            const barPct = (count / maxCount) * 100;
            const barColor = kwColors[group as KwGroup] || C.muted;
            return (
              <div key={kw} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                {/* Keyword label */}
                <div style={{ width: 72, flexShrink: 0, fontSize: F.xs, fontWeight: 600, color: C.textSub, textTransform: 'capitalize', textAlign: 'right' }}>
                  {kw}
                </div>
                {/* Bar */}
                <div style={{ flex: 1, height: 14, background: C.surfaceHover, borderRadius: R.pill, overflow: 'hidden', position: 'relative' }}>
                  <div
                    style={{
                      width: `${barPct}%`,
                      height: '100%',
                      background: barColor,
                      opacity: 0.82,
                      borderRadius: R.pill,
                      transition: 'width 0.35s ease',
                    }}
                  />
                </div>
                {/* Count */}
                <div style={{ width: 24, flexShrink: 0, fontSize: F.xs, fontWeight: 700, color: barColor, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                  {count}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, marginTop: 14, fontSize: F.xs, color: C.muted, flexWrap: 'wrap' }}>
        {([['risk', C.bear], ['regime', C.warn], ['confidence', C.brand]] as [KwGroup, string][]).map(([label, color]) => (
          <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: color, display: 'inline-block' }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  );
}


// ─── Model Cost Breakdown ─────────────────────────────────────────────────────

function ModelCostBreakdown({ decisions }: { decisions: LlmDecision[] }) {
  if (!decisions.length) return null;

  const TOKENS: Record<string, number> = { haiku: 800, sonnet: 2000, opus: 4000 };
  const COST_PER_M: Record<string, number> = { haiku: 0.25, sonnet: 3.0, opus: 15.0 };

  const counts = { haiku: 0, sonnet: 0, opus: 0 };

  decisions.forEach((d) => {
    const m = (d.model || '').toLowerCase();
    if (m.includes('haiku')) counts.haiku++;
    else if (m.includes('sonnet')) counts.sonnet++;
    else if (m.includes('opus')) counts.opus++;
    else counts.haiku++; // default
  });

  const totalDecisions = decisions.length;

  const costs = {
    haiku: (counts.haiku * TOKENS.haiku / 1_000_000) * COST_PER_M.haiku,
    sonnet: (counts.sonnet * TOKENS.sonnet / 1_000_000) * COST_PER_M.sonnet,
    opus: (counts.opus * TOKENS.opus / 1_000_000) * COST_PER_M.opus,
  };
  const totalCost = costs.haiku + costs.sonnet + costs.opus;
  const maxCost = Math.max(costs.haiku, costs.sonnet, costs.opus, 0.001);

  const models: Array<{ key: keyof typeof counts; label: string; color: string }> = [
    { key: 'haiku', label: 'Haiku', color: C.warn },
    { key: 'sonnet', label: 'Sonnet', color: C.brand },
    { key: 'opus', label: 'Opus', color: C.bull },
  ];

  // Donut chart dimensions
  const DONUT_R = 42;
  const DONUT_INNER_R = 26;
  const DONUT_CX = 58;
  const DONUT_CY = 58;
  const totalCount = totalDecisions || 1;

  // Build donut slices
  type DonutSlice = { startDeg: number; endDeg: number; color: string; label: string; pct: number };
  const donutSlices: DonutSlice[] = [];
  let cumDeg = -90; // start from top
  models.forEach(({ key, label, color }) => {
    const pct = counts[key] / totalCount;
    const span = pct * 360;
    donutSlices.push({ startDeg: cumDeg, endDeg: cumDeg + span, color, label, pct });
    cumDeg += span;
  });

  const donutArcPath = (startDeg: number, endDeg: number, outerR: number, innerR: number): string => {
    const toR = (deg: number) => (deg * Math.PI) / 180;
    const span = endDeg - startDeg;
    // Clamp tiny slivers
    if (span < 0.5) return '';
    // Full-circle edge case: arc from a point to itself is degenerate — draw two semicircles
    if (span >= 359.5) {
      const s = toR(startDeg);
      const mid = toR(startDeg + 180);
      const ox1 = DONUT_CX + outerR * Math.cos(s), oy1 = DONUT_CY + outerR * Math.sin(s);
      const ox2 = DONUT_CX + outerR * Math.cos(mid), oy2 = DONUT_CY + outerR * Math.sin(mid);
      const ix1 = DONUT_CX + innerR * Math.cos(s), iy1 = DONUT_CY + innerR * Math.sin(s);
      const ix2 = DONUT_CX + innerR * Math.cos(mid), iy2 = DONUT_CY + innerR * Math.sin(mid);
      return `M ${ox1} ${oy1} A ${outerR} ${outerR} 0 1 1 ${ox2} ${oy2} A ${outerR} ${outerR} 0 1 1 ${ox1} ${oy1} M ${ix1} ${iy1} A ${innerR} ${innerR} 0 1 0 ${ix2} ${iy2} A ${innerR} ${innerR} 0 1 0 ${ix1} ${iy1} Z`;
    }
    const s = toR(startDeg);
    const e = toR(endDeg);
    const large = span > 180 ? 1 : 0;
    const ox1 = DONUT_CX + outerR * Math.cos(s);
    const oy1 = DONUT_CY + outerR * Math.sin(s);
    const ox2 = DONUT_CX + outerR * Math.cos(e);
    const oy2 = DONUT_CY + outerR * Math.sin(e);
    const ix1 = DONUT_CX + innerR * Math.cos(e);
    const iy1 = DONUT_CY + innerR * Math.sin(e);
    const ix2 = DONUT_CX + innerR * Math.cos(s);
    const iy2 = DONUT_CY + innerR * Math.sin(s);
    return `M ${ox1} ${oy1} A ${outerR} ${outerR} 0 ${large} 1 ${ox2} ${oy2} L ${ix1} ${iy1} A ${innerR} ${innerR} 0 ${large} 0 ${ix2} ${iy2} Z`;
  };

  return (
    <div className="card-hover glass-noise" style={{ ...Glass.crystal, borderRadius: R.xl, padding: '20px 24px', marginBottom: 24 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>LLM Cost Breakdown</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>Estimated spend by model tier</div>
        </div>
        <span style={{ fontSize: F.xs, fontWeight: 700, color: C.textSub, background: C.surfaceHover, padding: '3px 9px', borderRadius: R.pill }}>
          {totalDecisions} calls
        </span>
      </div>

      <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        {/* Left: donut of call count */}
        <div style={{ flexShrink: 0 }}>
          <svg viewBox={`0 0 116 116`} width={116} height={116}>
            {donutSlices.map((slice, i) => {
              const path = donutArcPath(slice.startDeg, slice.endDeg, DONUT_R, DONUT_INNER_R);
              return path ? (
                <path key={i} d={path} fill={slice.color} opacity={0.85}>
                  <title>{`${slice.label}: ${counts[models[i].key]} calls (${(slice.pct * 100).toFixed(0)}%)`}</title>
                </path>
              ) : null;
            })}
            {/* Center text */}
            <text x={DONUT_CX} y={DONUT_CY - 5} textAnchor="middle" fontSize={10} fontWeight={700} fill={C.textSub}>
              {totalDecisions}
            </text>
            <text x={DONUT_CX} y={DONUT_CY + 8} textAnchor="middle" fontSize={8} fill={C.muted}>
              calls
            </text>
          </svg>
          {/* Mini legend */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 4 }}>
            {models.map(({ key, label, color }) => (
              <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <span style={{ width: 7, height: 7, borderRadius: 2, background: color, display: 'inline-block', opacity: 0.85, flexShrink: 0 }} />
                <span style={{ fontSize: F.xs, color: C.textSub, fontWeight: 600 }}>{label}</span>
                <span style={{ fontSize: F.xs, color: C.muted, marginLeft: 'auto' }}>{counts[key]}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: horizontal cost bars */}
        <div style={{ flex: 1, minWidth: 140 }}>
          <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 10 }}>
            $ Cost Contribution
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {models.map(({ key, label, color }) => {
              const barPct = (costs[key] / maxCost) * 100;
              return (
                <div key={key}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                    <span style={{ fontSize: F.xs, color, fontWeight: 700 }}>{label}</span>
                    <span style={{ fontSize: F.xs, color: C.textSub, fontVariantNumeric: 'tabular-nums' }}>
                      {fmtCost(costs[key])}
                    </span>
                  </div>
                  <div style={{ height: 10, background: C.surfaceHover, borderRadius: R.pill, overflow: 'hidden' }}>
                    <div
                      style={{
                        width: `${barPct}%`,
                        height: '100%',
                        background: color,
                        opacity: 0.85,
                        borderRadius: R.pill,
                        transition: 'width 0.4s ease',
                      }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Bottom summary */}
      <div style={{ marginTop: 16, paddingTop: 14, borderTop: `1px solid ${C.border}` }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8, marginBottom: 6 }}>
          <span style={{ fontSize: F.sm, color: C.muted }}>Total estimated cost:</span>
          <span style={{ fontSize: F.md, fontWeight: 800, color: C.text, fontVariantNumeric: 'tabular-nums' }}>
            {fmtCost(totalCost)} for {totalDecisions} decisions
          </span>
        </div>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          <div style={{ fontSize: F.xs, color: C.muted }}>
            Cost per trade signal:{' '}
            <span style={{ color: C.brand, fontWeight: 700 }}>~$0.007</span>
          </div>
          <div style={{ fontSize: F.xs, color: C.muted }}>
            Monthly projection (20 trades/day):{' '}
            <span style={{ color: C.warn, fontWeight: 700 }}>~$4.20/month</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function LlmAudit() {
  const [decisions, setDecisions] = useState<LlmDecision[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterAction, setFilterAction] = useState('All');
  const [filterTrigger, setFilterTrigger] = useState('All');
  const [filterSymbol, setFilterSymbol] = useState('All');
  const apiBase = resolveApiBase();

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(`${apiBase}/v1/llm/feed?limit=200`);
        if (res.ok) {
          const d: LlmFeedResponse = await res.json();
          setDecisions(d?.items || []);
        }
      } catch {/* silent */}
      setLoading(false);
    };
    load();
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
  }, [apiBase]);

  const triggers = useMemo(() => ['All', ...Array.from(new Set(decisions.map((d) => d.trigger).filter(Boolean)))], [decisions]);
  const symbols = useMemo(() => ['All', ...Array.from(new Set(decisions.map((d) => d.symbol).filter(Boolean) as string[]))], [decisions]);

  const filtered = useMemo(() => {
    return decisions.filter((d) => {
      if (filterAction !== 'All') {
        if (filterAction === 'VETO' && !d.is_veto) return false;
        if (filterAction === 'PROCEED' && !['proceed', 'go'].includes((d.action || '').toLowerCase())) return false;
        if (filterAction === 'SKIP' && !['skip', 'flat'].includes((d.action || '').toLowerCase())) return false;
        if (filterAction === 'FLIP' && (d.action || '').toLowerCase() !== 'flip') return false;
        if (filterAction === 'BLOCKED' && d.allowed) return false;
      }
      if (filterTrigger !== 'All' && d.trigger !== filterTrigger) return false;
      if (filterSymbol !== 'All' && d.symbol !== filterSymbol) return false;
      return true;
    });
  }, [decisions, filterAction, filterTrigger, filterSymbol]);

  // Stats
  const stats = useMemo(() => {
    const total = decisions.length;
    if (!total) return null;
    const proceed = decisions.filter((d) => ['proceed', 'go'].includes((d.action || '').toLowerCase())).length;
    const vetoes = decisions.filter((d) => d.is_veto).length;
    const blocked = decisions.filter((d) => !d.allowed).length;
    const avgConf = decisions.reduce((s, d) => s + (d.confidence ?? 0), 0) / total;
    const models: Record<string, number> = {};
    decisions.forEach((d) => {
      const m = d.model?.includes('haiku') ? 'Haiku' : d.model?.includes('sonnet') ? 'Sonnet' : d.model?.includes('opus') ? 'Opus' : 'Other';
      models[m] = (models[m] || 0) + 1;
    });
    return { total, proceed, vetoes, blocked, avgConf, models };
  }, [decisions]);

  const PillBtn = ({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) => (
    <button
      onClick={onClick}
      style={{
        fontSize: F.xs, padding: '3px 10px', borderRadius: R.pill, cursor: 'pointer', fontWeight: 600,
        border: `1px solid ${active ? C.brand : C.border}`,
        background: active ? C.brand + '22' : 'transparent',
        color: active ? C.brand : C.muted,
        transition: 'all 0.12s',
      }}
    >
      {label}
    </button>
  );

  return (
    <div className="bg-aurora" style={{ position: 'relative' }}>
      <div className="floating-orb orb-purple" style={{ position: 'fixed', top: '20%', left: '5%' }} />
      {/* Header */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
          AI Transparency
        </div>
        <h1 style={{ margin: 0, fontSize: F['3xl'], fontWeight: 900, color: C.text, letterSpacing: -0.5 }}>
          LLM <span className="gradient-text">Decision Audit</span>
        </h1>
        <p style={{ margin: '6px 0 0', fontSize: F.sm, color: C.muted, maxWidth: 680 }}>
          Every AI decision, in full. What model was used, what trigger fired, the full reasoning, and whether the trade was blocked. Radical transparency.
        </p>
      </div>

      {/* Stat Row */}
      {loading ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 28 }}>
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} h={64} />)}
        </div>
      ) : !stats ? (
        <div style={{ padding: '24px 20px', ...Glass.card, borderRadius: R.lg, border: `1px solid ${C.border}`, textAlign: 'center', color: C.muted, fontSize: F.sm, marginBottom: 28 }}>
          No LLM decisions recorded yet. Start the bot with <code style={{ background: C.surfaceHover, padding: '1px 4px', borderRadius: R.xs, color: C.brand }}>LLM_MODE=1</code> to see AI decisions here.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 28 }}>
          {[
            { label: 'Total Decisions', value: `${stats.total}`, color: C.text },
            { label: 'Proceed Rate', value: `${stats.total > 0 ? ((stats.proceed / stats.total) * 100).toFixed(0) : 0}%`, color: C.bull },
            { label: 'Veto Rate', value: `${stats.total > 0 ? ((stats.vetoes / stats.total) * 100).toFixed(0) : 0}%`, color: C.bear },
            { label: 'Gate Block Rate', value: `${stats.total > 0 ? ((stats.blocked / stats.total) * 100).toFixed(0) : 0}%`, color: C.warn },
            { label: 'Avg Confidence', value: `${(stats.avgConf * 100).toFixed(0)}%`, color: stats.avgConf >= 0.55 ? C.bull : C.warn },
            {
              label: 'Models Used',
              value: Object.entries(stats.models).map(([m, c]) => `${m[0]}:${c}`).join(' '),
              color: C.text,
            },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ padding: '12px 14px', ...Glass.crystal, borderRadius: R.lg }}>
              <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.6, marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 18, fontWeight: 800, color, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* Main content + Right sidebar layout */}
      <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
        {/* Main column */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Model Routing */}
          {decisions.length > 0 && (
            <div className="card-hover glass-noise" style={{ ...Glass.crystal, borderRadius: R.lg, padding: '20px 24px', marginBottom: 24 }}>
              <h2 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 700, color: C.text }}>Model Routing</h2>
              <ModelRoutingChart decisions={decisions} />
              <div style={{ marginTop: 20, paddingTop: 18, borderTop: `1px solid ${C.border}` }}>
                <TokenUsageBar decisions={decisions} />
              </div>
              <DecisionActivityMap decisions={decisions} />
            </div>
          )}

          {/* Model Cost Breakdown */}
          {decisions.length > 0 && <ModelCostBreakdown decisions={decisions} />}

          {/* Confidence Calibration */}
          {decisions.length > 0 && (
            <div style={{ ...Glass.card, borderRadius: R.lg, padding: '20px 24px', marginBottom: 24 }}>
              <h2 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 700, color: C.text }}>Confidence Calibration</h2>
              <ConfCalibration decisions={decisions} />
              <div style={{ marginTop: 24, paddingTop: 20, borderTop: `1px solid ${C.border}` }}>
                <ConfidenceHistogram decisions={decisions} />
              </div>
            </div>
          )}

          {/* Action Rate Timeline */}
          {decisions.length >= 6 && <ActionRateTimeline decisions={decisions} />}

          {/* Per-Symbol Decision Grid */}
          {decisions.length > 0 && <SymbolDecisionGrid decisions={decisions} />}

          {/* Trigger Breakdown */}
          {decisions.length > 0 && <TriggerBreakdownChart decisions={decisions} />}

          {/* Veto Analysis */}
          {decisions.some((d) => d.is_veto) && (
            <div style={{ ...Glass.card, borderRadius: R.lg, padding: '20px 24px', marginBottom: 24 }}>
              <h2 style={{ margin: '0 0 4px', fontSize: 16, fontWeight: 700, color: C.text }}>Veto Analysis</h2>
              <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 16 }}>
                {decisions.filter((d) => d.is_veto).length} vetoes out of {decisions.length} decisions
              </div>
              <VetoAnalysis decisions={decisions} />
            </div>
          )}

          {/* Veto Frequency Bars */}
          {decisions.length > 0 && <VetoFrequencyBars decisions={decisions} />}
        </div>

        {/* Right sidebar */}
        <div style={{ width: 280, flexShrink: 0 }}>
          {/* Agent Activity */}
          {decisions.length > 0 && <AgentAccuracyMatrix decisions={decisions} />}
        </div>
      </div>

      {/* Filters */}
      <div className="card-hover glass-noise" style={{ ...Glass.crystal, borderRadius: R.lg, padding: '14px 20px', marginBottom: 16 }}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 600 }}>Filter:</span>
          {['All', 'PROCEED', 'SKIP', 'VETO', 'FLIP', 'BLOCKED'].map((a) => (
            <PillBtn key={a} label={a} active={filterAction === a} onClick={() => setFilterAction(a)} />
          ))}
          <span style={{ color: C.faint }}>|</span>
          {symbols.slice(0, 8).map((s) => (
            <PillBtn key={s} label={s} active={filterSymbol === s} onClick={() => setFilterSymbol(s)} />
          ))}
          {triggers.length > 2 && (
            <>
              <span style={{ color: C.faint }}>|</span>
              <select
                value={filterTrigger}
                onChange={(e) => setFilterTrigger(e.target.value)}
                style={{ ...Glass.card, borderRadius: R.sm, color: C.text, padding: '3px 8px', fontSize: F.xs, cursor: 'pointer' }}
              >
                {triggers.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </>
          )}
          {(filterAction !== 'All' || filterSymbol !== 'All' || filterTrigger !== 'All') && (
            <button
              onClick={() => { setFilterAction('All'); setFilterSymbol('All'); setFilterTrigger('All'); }}
              style={{ marginLeft: 'auto', fontSize: F.xs, padding: '3px 10px', borderRadius: R.pill, cursor: 'pointer', fontWeight: 600, border: `1px solid ${C.border}`, background: 'transparent', color: C.muted }}
            >
              Clear filters
            </button>
          )}
        </div>
      </div>

      {/* Decision Timeline */}
      <div className="card-hover glass-noise" style={{ ...Glass.crystal, borderRadius: R.lg, overflow: 'hidden' }}>
        <div style={{ padding: '14px 20px', background: C.surfaceHover, borderBottom: `1px solid ${C.border}`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Decision Timeline</span>
          <span style={{ fontSize: F.xs, color: C.muted }}>{filtered.length} decisions · click to expand reasoning</span>
        </div>
        {loading ? (
          <div style={{ padding: '16px 20px' }}>
            {Array.from({ length: 5 }).map((_, i) => <div key={i} style={{ marginBottom: 8 }}><Skeleton h={40} /></div>)}
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ padding: '32px 24px', textAlign: 'center', color: C.muted, fontSize: F.sm }}>
            No decisions match the current filters.
          </div>
        ) : (
          filtered.map((d, i) => <DecisionRow key={i} d={d} />)
        )}
      </div>

      {/* Links */}
      <div style={{ display: 'flex', gap: 12, marginTop: 28, paddingTop: 20, borderTop: `1px solid ${C.border}` }}>
        <Link href="/signals" style={{ fontSize: F.sm, padding: '8px 16px', borderRadius: R.md, background: C.brand, color: '#fff', fontWeight: 700, textDecoration: 'none' }}>
          ← Live Signals
        </Link>
        <Link href="/forensics" style={{ fontSize: F.sm, padding: '8px 16px', borderRadius: R.md, border: `1px solid ${C.border}`, color: C.muted, fontWeight: 600, textDecoration: 'none' }}>
          Trade Forensics →
        </Link>
      </div>
    </div>
  );
}
