'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { C, R, F, Glass, SP } from '../../src/theme';
import { fadeUp } from '../../src/animations';

// ─── Regime Table ────────────────────────────────────────────────────────────

export function RegimeTable() {
  const regimes = [
    { name: 'trend', emoji: '\uD83D\uDCC8', desc: 'Price moving strongly in one direction', behaviour: 'Bot favours momentum trades. Buy dips in uptrend, sell rallies in downtrend.', risk: 'Low-Med' },
    { name: 'range', emoji: '\u2194\uFE0F', desc: 'Price bouncing between support and resistance', behaviour: 'Bot waits for extreme zones. Mean-reversion setups only.', risk: 'Low' },
    { name: 'panic', emoji: '\uD83D\uDD34', desc: 'Rapid, disorderly sell-off or flash crash', behaviour: 'Bot pauses or uses very tight sizing. High risk of slippage.', risk: 'Very High' },
    { name: 'high_volatility', emoji: '\u26A1', desc: 'Expanded ranges, fast candles, unpredictable', behaviour: 'Wider stops required. Bot reduces confidence thresholds.', risk: 'High' },
    { name: 'low_liquidity', emoji: '\uD83D\uDCA7', desc: 'Thin order book, large spread', behaviour: 'Bot reduces position size to avoid slippage impact.', risk: 'Med-High' },
    { name: 'news_dislocation', emoji: '\uD83D\uDCF0', desc: 'Price moved by news event, not technicals', behaviour: 'Bot waits for dust to settle before re-entering.', risk: 'Unpredictable' },
  ];

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ overflowX: 'auto' }}
    >
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: F.sm }}>
        <thead>
          <tr style={{ background: C.surface }}>
            {['Regime', 'What it means', 'Bot behaviour', 'Risk'].map((h) => (
              <th key={h} style={{ padding: '10px 12px', textAlign: 'left', fontSize: F.xs, color: C.muted, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5, borderBottom: `1px solid ${C.border}` }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {regimes.map((r, i) => (
            <tr key={r.name} style={{ borderBottom: `1px solid ${C.border}`, background: i % 2 ? C.surfaceHover + '40' : 'transparent' }}>
              <td style={{ padding: '10px 12px', fontWeight: 700, color: C.text, whiteSpace: 'nowrap' }}>
                {r.emoji} {r.name}
              </td>
              <td style={{ padding: '10px 12px', color: C.textSub }}>{r.desc}</td>
              <td style={{ padding: '10px 12px', color: C.muted }}>{r.behaviour}</td>
              <td style={{ padding: '10px 12px', fontWeight: 700, color: r.risk === 'Very High' || r.risk === 'Unpredictable' ? C.bear : r.risk.includes('High') ? C.warn : C.bull }}>
                {r.risk}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </motion.div>
  );
}

// ─── Exchange Comparison Chart ───────────────────────────────────────────────

export function ExchangeComparisonChart() {
  const metrics = [
    { label: 'Taker Fee', unit: '%', HL: 0.05, Binance: 0.10, Bybit: 0.10, dYdX: 0.05, higherIsBetter: false, fmt: (v: number) => v.toFixed(3) },
    { label: 'Maker Fee', unit: '%', HL: 0.035, Binance: 0.02, Bybit: 0.01, dYdX: 0.02, higherIsBetter: false, fmt: (v: number) => v.toFixed(3) },
    { label: 'Exec Speed', unit: 'ms', HL: 50, Binance: 80, Bybit: 90, dYdX: 150, higherIsBetter: false, fmt: (v: number) => String(v) },
    { label: 'Max Leverage', unit: '\u00D7', HL: 50, Binance: 125, Bybit: 100, dYdX: 20, higherIsBetter: true, fmt: (v: number) => String(v) },
    { label: 'Onchain Settlement', unit: '', HL: 1, Binance: 0, Bybit: 0, dYdX: 0.5, higherIsBetter: true, fmt: (v: number) => v === 1 ? '\u2713' : v === 0.5 ? '~' : '\u2717' },
    { label: 'API Rate Limit', unit: '', HL: 5, Binance: 3, Bybit: 2, dYdX: 3, higherIsBetter: true, fmt: (v: number) => ['Low','Med','High','High+','Max'][v-1] || '?' },
  ];
  const exchanges = ['HL', 'Binance', 'Bybit', 'dYdX'] as const;
  const colors: Record<string, string> = { HL: C.brand, Binance: C.warn, Bybit: C.info, dYdX: C.bull };

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ marginTop: 16 }}
    >
      <div style={{ fontSize: F.xs, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>
        Exchange Feature Comparison
      </div>
      {/* Legend */}
      <div style={{ display: 'flex', gap: 16, marginBottom: 14, flexWrap: 'wrap' }}>
        {exchanges.map(ex => (
          <div key={ex} style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <div style={{ width: 10, height: 10, borderRadius: '50%', background: colors[ex] }} />
            <span style={{ fontSize: F.xs, color: ex === 'HL' ? C.brand : C.muted, fontWeight: ex === 'HL' ? 700 : 400 }}>
              {ex === 'HL' ? 'Hyperliquid \u2605' : ex}
            </span>
          </div>
        ))}
      </div>
      {/* Chart rows */}
      {metrics.map(m => {
        const vals: Record<string, number> = { HL: m.HL, Binance: m.Binance, Bybit: m.Bybit, dYdX: m.dYdX };
        const max = Math.max(...exchanges.map(ex => vals[ex]));
        return (
          <div key={m.label} style={{ marginBottom: 14 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span style={{ fontSize: F.xs, color: C.textSub, fontWeight: 600 }}>{m.label}</span>
              {m.higherIsBetter
                ? <span style={{ fontSize: F.xs, color: C.bull }}>higher = better &uarr;</span>
                : <span style={{ fontSize: F.xs, color: C.warn }}>lower = better &darr;</span>}
            </div>
            {exchanges.map(ex => {
              const v = vals[ex];
              const pct = max > 0 ? (v / max) * 100 : 100;
              const isBest = m.higherIsBetter
                ? v === Math.max(...exchanges.map(e => vals[e]))
                : v === Math.min(...exchanges.map(e => vals[e]));
              return (
                <div key={ex} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <div style={{ width: 60, fontSize: F.xs, color: ex === 'HL' ? C.brand : C.muted, fontWeight: ex === 'HL' ? 700 : 400, flexShrink: 0 }}>{ex}</div>
                  <div style={{ flex: 1, height: 18, background: C.surfaceHover, borderRadius: R.sm, overflow: 'hidden', position: 'relative' }}>
                    <div style={{
                      width: `${pct}%`, height: '100%',
                      background: isBest ? colors[ex] : colors[ex] + '55',
                      borderRadius: R.sm,
                      transition: 'width 0.3s',
                    }} />
                  </div>
                  <div style={{
                    width: 52, fontSize: F.xs, textAlign: 'right', flexShrink: 0,
                    color: isBest ? colors[ex] : C.muted,
                    fontWeight: isBest ? 700 : 400,
                  }}>
                    {m.fmt(v)}{m.unit && m.unit !== '' && m.label !== 'Exec Speed' ? m.unit : m.label === 'Exec Speed' ? 'ms' : ''}
                  </div>
                  {isBest && (
                    <div style={{ width: 14, fontSize: 10, color: isBest ? colors[ex] : 'transparent' }}>\u2605</div>
                  )}
                </div>
              );
            })}
          </div>
        );
      })}
      <div style={{
        marginTop: 8, padding: '8px 12px', ...Glass.card,
        background: C.brand + '11',
        borderRadius: R.sm, border: `1px solid ${C.brand}33`,
        fontSize: F.xs, color: C.textSub, lineHeight: 1.6,
      }}>
        Best-in-class for algo trading: Hyperliquid leads on execution speed, fees, and onchain transparency.
        The bot caps leverage at 10x regardless of what the exchange allows.
      </div>
    </motion.div>
  );
}

// ─── Leverage Matrix ─────────────────────────────────────────────────────────

export function LeverageMatrix() {
  const confLabels = ['60\u201369%', '70\u201379%', '80\u201389%', '\u226590%'];
  const agrLabels = ['2/4', '3/4', '4/4'];
  const matrix = [
    [2, 3, 4],
    [3, 5, 6],
    [4, 6, 8],
    [5, 7, 10],
  ];
  const maxLev = 10;

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ marginTop: 16 }}
    >
      <div style={{ fontSize: F.xs, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>
        Max Leverage by Confidence x Agreement
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 280 }}>
          <thead>
            <tr>
              <th style={{ padding: '6px 10px', fontSize: F.xs, color: C.muted, textAlign: 'left', fontWeight: 600, borderBottom: `1px solid ${C.border}` }}>Confidence</th>
              {agrLabels.map(a => (
                <th key={a} style={{ padding: '6px 10px', fontSize: F.xs, color: C.textSub, textAlign: 'center', fontWeight: 600, borderBottom: `1px solid ${C.border}` }}>
                  {a} agree
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, ri) => (
              <tr key={ri}>
                <td style={{ padding: '6px 10px', fontSize: F.xs, color: C.textSub, fontWeight: 600, borderBottom: `1px solid ${C.border}22` }}>{confLabels[ri]}</td>
                {row.map((lev, ci) => {
                  const intensity = lev / maxLev;
                  const bg = `rgba(99, 102, 241, ${intensity * 0.5})`;
                  return (
                    <td key={ci} style={{
                      padding: '8px 10px', textAlign: 'center',
                      background: bg, borderBottom: `1px solid ${C.border}22`,
                      fontSize: F.sm, fontWeight: 700,
                      color: intensity > 0.5 ? C.brand : C.textSub,
                    }}>
                      {lev}x
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ marginTop: 8, fontSize: F.xs, color: C.muted, lineHeight: 1.6 }}>
        Final leverage is also reduced in <span style={{ color: C.bear, fontWeight: 700 }}>PANIC</span> and <span style={{ color: C.warn, fontWeight: 700 }}>HIGH_VOLATILITY</span> regimes.
        Stop width overrides: wider SL = lower leverage to keep dollar risk constant at 1.5% equity.
      </div>
    </motion.div>
  );
}

export default { RegimeTable, ExchangeComparisonChart, LeverageMatrix };
