'use client';

import React, { useState, useId } from 'react';
import { motion } from 'framer-motion';
import { C, R, F, Glass, SP } from '../../src/theme';
import { fadeUp } from '../../src/animations';

// ─── Position Size Calculator ────────────────────────────────────────────────

export function PositionSizeCalc() {
  const [accountSize, setAccountSize] = useState(10000);
  const [riskPct, setRiskPct] = useState(1.5);
  const [entry, setEntry] = useState(95000);
  const [stopLoss, setStopLoss] = useState(94200);

  const safeAccountSize = isNaN(accountSize) || accountSize <= 0 ? 0 : accountSize;
  const safeEntry = isNaN(entry) || entry <= 0 ? 0 : entry;
  const safeStopLoss = isNaN(stopLoss) || stopLoss <= 0 ? 0 : stopLoss;
  const riskDollars = (safeAccountSize * riskPct) / 100;
  const stopDist = Math.abs(safeEntry - safeStopLoss);
  const stopDistPct = safeEntry > 0 ? (stopDist / safeEntry) * 100 : 0;
  const positionSize = stopDist > 0 ? riskDollars / stopDist : 0;
  const notionalValue = positionSize * safeEntry;
  const leverage = safeAccountSize > 0 ? notionalValue / safeAccountSize : 0;

  const inputStyle: React.CSSProperties = {
    padding: '8px 12px', background: C.surfaceHover, border: `1px solid ${C.border}`,
    borderRadius: R.sm, color: C.text, fontSize: F.sm, width: '100%', outline: 'none',
    fontVariantNumeric: 'tabular-nums',
  };
  const labelStyle: React.CSSProperties = { fontSize: F.xs, color: C.muted, fontWeight: 600, marginBottom: 4 };

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ ...Glass.card, borderRadius: R.lg, padding: SP[5] }}
    >
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
        <div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
            <div>
              <div style={labelStyle}>Account Size ($)</div>
              <input type="number" aria-label="Account size in dollars" style={inputStyle} value={accountSize} onChange={e => { const v = parseFloat(e.target.value); setAccountSize(isNaN(v) ? 0 : Math.max(0, v)); }} min={100} />
            </div>
            <div>
              <div style={labelStyle}>Risk Per Trade (%)</div>
              <input type="number" aria-label="Risk per trade percentage" style={inputStyle} value={riskPct} step={0.1} onChange={e => { const v = parseFloat(e.target.value); setRiskPct(isNaN(v) ? 0 : Math.max(0, Math.min(100, v))); }} min={0.1} max={10} />
            </div>
            <div>
              <div style={labelStyle}>Entry Price ($)</div>
              <input type="number" aria-label="Entry price in dollars" style={inputStyle} value={entry} onChange={e => { const v = parseFloat(e.target.value); setEntry(isNaN(v) ? 0 : Math.max(0, v)); }} min={0.01} />
            </div>
            <div>
              <div style={labelStyle}>Stop Loss Price ($)</div>
              <input type="number" aria-label="Stop loss price in dollars" style={inputStyle} value={stopLoss} onChange={e => { const v = parseFloat(e.target.value); setStopLoss(isNaN(v) ? 0 : Math.max(0, v)); }} min={0.01} />
            </div>
          </div>
          <div style={{ padding: '10px 14px', background: C.warn + '12', border: `1px solid ${C.warn}30`, borderRadius: R.sm, fontSize: F.xs, color: C.textSub }}>
            Stop distance: <strong style={{ color: C.warn }}>{stopDistPct.toFixed(2)}%</strong> = ${stopDist.toLocaleString(undefined, { maximumFractionDigits: 2 })} per unit
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[
            { label: 'Max Dollar Risk', value: `$${riskDollars.toLocaleString(undefined, { maximumFractionDigits: 2 })}`, color: C.warn, desc: `${riskPct}% of account` },
            { label: 'Position Size', value: positionSize > 0 ? positionSize.toLocaleString(undefined, { maximumFractionDigits: 4 }) + ' units' : '\u2014', color: C.text, desc: 'BTC / SOL / HYPE etc.' },
            { label: 'Notional Value', value: notionalValue > 0 ? `$${notionalValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '\u2014', color: C.info, desc: 'Total position exposure' },
            { label: 'Effective Leverage', value: leverage > 0 ? `${leverage.toFixed(1)}x` : '\u2014', color: leverage > 10 ? C.bear : leverage > 5 ? C.warn : C.bull, desc: 'Notional / account size' },
          ].map(({ label, value, color, desc }) => (
            <div key={label} style={{ padding: '12px 16px', background: C.surfaceHover, border: `1px solid ${C.border}`, borderRadius: R.md, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 2 }}>{label}</div>
                <div style={{ fontSize: F.xs, color: C.faint }}>{desc}</div>
              </div>
              <div style={{ fontSize: F.lg, fontWeight: 800, color }}>{value}</div>
            </div>
          ))}
          {leverage > 10 && (
            <div style={{ padding: '8px 12px', background: C.bear + '12', border: `1px solid ${C.bear}30`, borderRadius: R.sm, fontSize: F.xs, color: C.bearMid }}>
              Leverage &gt;10x is high risk. Consider widening your stop or reducing position size.
            </div>
          )}
        </div>
      </div>
    </motion.div>
  );
}

// ─── Risk/Reward Calculator ──────────────────────────────────────────────────

export function RRCalc() {
  const [entry, setEntry] = useState(95000);
  const [sl, setSl] = useState(94200);
  const [tp1, setTp1] = useState(96400);
  const [tp2, setTp2] = useState(97800);

  const safeEntry = isNaN(entry) || entry <= 0 ? 0 : entry;
  const safeSl = isNaN(sl) || sl <= 0 ? 0 : sl;
  const safeTp1 = isNaN(tp1) || tp1 <= 0 ? 0 : tp1;
  const safeTp2 = isNaN(tp2) || tp2 <= 0 ? 0 : tp2;
  const risk = Math.abs(safeEntry - safeSl);
  const reward1 = Math.abs(safeTp1 - safeEntry);
  const reward2 = Math.abs(safeTp2 - safeEntry);
  const rr1 = risk > 0 ? reward1 / risk : 0;
  const rr2 = risk > 0 ? reward2 / risk : 0;
  const slPct = safeEntry > 0 ? (risk / safeEntry) * 100 : 0;
  const tp1Pct = safeEntry > 0 ? (reward1 / safeEntry) * 100 : 0;
  const tp2Pct = safeEntry > 0 ? (reward2 / safeEntry) * 100 : 0;

  const barMax = Math.max(reward2, risk) || 1;

  const inputStyle: React.CSSProperties = {
    padding: '8px 12px', background: C.surfaceHover, border: `1px solid ${C.border}`,
    borderRadius: R.sm, color: C.text, fontSize: F.sm, width: '100%', outline: 'none',
  };
  const labelStyle: React.CSSProperties = { fontSize: F.xs, color: C.muted, fontWeight: 600, marginBottom: 4 };

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ ...Glass.card, borderRadius: R.lg, padding: SP[5] }}
    >
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
          <div style={{ gridColumn: '1/-1' }}>
            <div style={labelStyle}>Entry Price ($)</div>
            <input type="number" aria-label="Entry price" style={inputStyle} value={entry} onChange={e => { const v = parseFloat(e.target.value); setEntry(isNaN(v) ? 0 : Math.max(0, v)); }} />
          </div>
          <div>
            <div style={labelStyle}>Stop Loss ($)</div>
            <input type="number" aria-label="Stop loss price" style={inputStyle} value={sl} onChange={e => { const v = parseFloat(e.target.value); setSl(isNaN(v) ? 0 : Math.max(0, v)); }} />
          </div>
          <div>
            <div style={labelStyle}>TP1 ($)</div>
            <input type="number" aria-label="Take profit 1 price" style={inputStyle} value={tp1} onChange={e => { const v = parseFloat(e.target.value); setTp1(isNaN(v) ? 0 : Math.max(0, v)); }} />
          </div>
          <div style={{ gridColumn: '1/-1' }}>
            <div style={labelStyle}>TP2 (Final Target) ($)</div>
            <input type="number" aria-label="Take profit 2 final target price" style={inputStyle} value={tp2} onChange={e => { const v = parseFloat(e.target.value); setTp2(isNaN(v) ? 0 : Math.max(0, v)); }} />
          </div>
        </div>

        <div>
          {/* Visual bar */}
          <div style={{ marginBottom: 16 }}>
            {[
              { label: 'Risk (SL)', dist: risk, pct: slPct, color: C.bear },
              { label: 'TP1 Reward', dist: reward1, pct: tp1Pct, color: C.bullMid },
              { label: 'TP2 Reward', dist: reward2, pct: tp2Pct, color: C.bull },
            ].map(({ label, dist, pct, color }) => (
              <div key={label} style={{ marginBottom: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                  <span style={{ fontSize: F.xs, color: C.muted }}>{label}</span>
                  <span style={{ fontSize: F.xs, fontWeight: 700, color }}>{pct.toFixed(2)}%</span>
                </div>
                <div style={{ height: 8, background: C.border, borderRadius: R.pill, overflow: 'hidden' }}>
                  <div style={{ width: `${Math.min(100, (dist / barMax) * 100)}%`, height: '100%', background: color, borderRadius: R.pill }} />
                </div>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            {[
              { label: 'R:R to TP1', value: `${rr1.toFixed(2)}:1`, ok: rr1 >= 1 },
              { label: 'R:R to TP2', value: `${rr2.toFixed(2)}:1`, ok: rr2 >= 2 },
            ].map(({ label, value, ok }) => (
              <div key={label} style={{ flex: 1, padding: '10px 14px', background: (ok ? C.bull : C.bear) + '12', border: `1px solid ${(ok ? C.bull : C.bear)}30`, borderRadius: R.md, textAlign: 'center' }}>
                <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 2 }}>{label}</div>
                <div style={{ fontSize: F.xl, fontWeight: 800, color: ok ? C.bull : C.bear }}>{value}</div>
                <div style={{ fontSize: F.xs, color: ok ? C.bullMid : C.bearMid }}>{ok ? 'Good' : 'Too tight'}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// ─── Compound Growth Calculator ──────────────────────────────────────────────

export function CompoundCalc() {
  const uid = useId().replace(/:/g, '');
  const gradId = `compGrad-${uid}`;
  const [capital, setCapital] = useState(10000);
  const [monthlyPct, setMonthlyPct] = useState(5);
  const [months, setMonths] = useState(12);

  const rows: { month: number; equity: number; gain: number }[] = [];
  let equity = capital > 0 ? capital : 1;
  for (let m = 1; m <= Math.min(months, 60); m++) {
    const gain = equity * (monthlyPct / 100);
    equity = Math.max(0, equity + gain);
    rows.push({ month: m, equity, gain });
  }
  const finalEquity = rows[rows.length - 1]?.equity ?? capital;
  const safeCapital = capital > 0 ? capital : 1;
  const totalReturn = ((finalEquity - safeCapital) / safeCapital) * 100;
  const maxEquity = finalEquity;

  const inputStyle: React.CSSProperties = {
    padding: '8px 12px', background: C.surfaceHover, border: `1px solid ${C.border}`,
    borderRadius: R.sm, color: C.text, fontSize: F.sm, width: '100%', outline: 'none',
  };
  const labelStyle: React.CSSProperties = { fontSize: F.xs, color: C.muted, fontWeight: 600, marginBottom: 4 };

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ ...Glass.card, borderRadius: R.lg, padding: SP[5] }}
    >
      <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', gap: 24 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div>
            <div style={labelStyle}>Starting Capital ($)</div>
            <input type="number" aria-label="Starting capital in dollars" style={inputStyle} value={capital} onChange={e => { const v = parseFloat(e.target.value); setCapital(isNaN(v) ? 0 : Math.max(0, v)); }} min={100} />
          </div>
          <div>
            <div style={labelStyle}>Monthly Return (%)</div>
            <input type="number" aria-label="Monthly return percentage" style={inputStyle} value={monthlyPct} step={0.5} onChange={e => { const v = parseFloat(e.target.value); setMonthlyPct(isNaN(v) ? 0 : Math.max(0, Math.min(100, v))); }} min={0.1} max={100} />
          </div>
          <div>
            <div style={labelStyle}>Number of Months</div>
            <input type="number" aria-label="Number of months" style={inputStyle} value={months} onChange={e => setMonths(Math.min(60, Math.max(1, +e.target.value)))} min={1} max={60} />
          </div>
          <div style={{ padding: '14px 16px', background: C.bull + '12', border: `1px solid ${C.bull}30`, borderRadius: R.md }}>
            <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>Final Equity</div>
            <div style={{ fontSize: F['2xl'], fontWeight: 800, color: C.bull }}>{isFinite(finalEquity) ? `$${finalEquity.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '\u2014'}</div>
            <div style={{ fontSize: F.xs, color: C.bullMid }}>{isFinite(totalReturn) ? `${totalReturn >= 0 ? '+' : ''}${totalReturn.toFixed(1)}%` : '\u2014'} total</div>
          </div>
        </div>

        {/* Mini chart */}
        <div>
          <svg width="100%" viewBox="0 0 400 160" style={{ display: 'block', overflow: 'visible' }}>
            <defs>
              <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={C.bull} stopOpacity={0.3} />
                <stop offset="100%" stopColor={C.bull} stopOpacity={0} />
              </linearGradient>
            </defs>
            {rows.length >= 2 && (() => {
              const minE = capital;
              const rangeE = maxEquity - minE || 1;
              const W = 380, H = 130, padL = 0, padT = 10;
              const px = (i: number) => padL + (i / (rows.length - 1)) * W;
              const py = (e: number) => padT + H - ((e - minE) / rangeE) * H;
              const pts = rows.map((r, i) => `${px(i)},${py(r.equity)}`);
              const area = `M ${pts[0]} L ${pts.slice(1).join(' L ')} L ${px(rows.length - 1)},${padT + H} L ${padL},${padT + H} Z`;
              const line = pts.join(' ');
              return (
                <>
                  <path d={area} fill={`url(#${gradId})`} />
                  <polyline fill="none" stroke={C.bull} strokeWidth={2} points={line} strokeLinejoin="round" />
                  <text x={padL} y={padT + H + 16} fontSize={10} fill={C.muted}>${capital.toLocaleString()}</text>
                  <text x={W} y={padT + 8} fontSize={10} fill={C.bullMid} textAnchor="end">${finalEquity.toLocaleString(undefined, { maximumFractionDigits: 0 })}</text>
                </>
              );
            })()}
          </svg>
          <div style={{ fontSize: F.xs, color: C.muted, textAlign: 'center', marginTop: 4 }}>
            Month-by-month equity growth over {months} months
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// ─── Expected Value Calculator ───────────────────────────────────────────────

export function ExpectedValueCalc() {
  const [winRate, setWinRate] = useState(0.60);
  const [avgWin, setAvgWin] = useState(300);
  const [avgLoss, setAvgLoss] = useState(150);

  const ev = winRate * avgWin - (1 - winRate) * avgLoss;
  const isPositive = ev >= 0;
  const tradesPerMonth = 20;
  const monthlyEV = ev * tradesPerMonth;

  const breakevenWR = avgLoss > 0 && avgWin > 0 ? avgLoss / (avgWin + avgLoss) : 0;

  const totalBar = winRate * avgWin + (1 - winRate) * avgLoss;
  const gainPct = totalBar > 0 ? (winRate * avgWin / totalBar) * 100 : 50;
  const lossPct = 100 - gainPct;

  const inputStyle: React.CSSProperties = {
    padding: '7px 10px',
    background: C.surfaceHover,
    border: `1px solid ${C.border}`,
    borderRadius: R.sm,
    color: C.text,
    fontSize: F.sm,
    width: '100%',
    outline: 'none',
    fontVariantNumeric: 'tabular-nums',
  };
  const labelStyle: React.CSSProperties = { fontSize: F.xs, color: C.muted, fontWeight: 600, marginBottom: 4 };

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ ...Glass.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 22px' }}
    >
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 16 }}>
        Expected Value Calculator
      </div>

      {/* EV Result */}
      <div style={{ marginBottom: 20, padding: '16px 20px', background: (isPositive ? C.bull : C.bear) + '14', border: `1px solid ${(isPositive ? C.bull : C.bear)}33`, borderRadius: R.md, textAlign: 'center' }}>
        <div style={{ fontSize: 28, fontWeight: 900, color: isPositive ? C.bull : C.bear, letterSpacing: -0.5 }}>
          {isPositive ? '+' : ''}{ev >= 0 ? '$' : '-$'}{Math.abs(ev).toFixed(2)} per trade
        </div>
        <div style={{ fontSize: F.xs, color: C.muted, marginTop: 4 }}>
          Win Rate: {(winRate * 100).toFixed(0)}% | Avg Win: ${avgWin} | Avg Loss: ${avgLoss}
        </div>
      </div>

      {/* Inputs */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 16 }}>
        <div>
          <div style={labelStyle}>Win Rate (%)</div>
          <input
            type="range"
            min={0} max={100} step={1}
            value={Math.round(winRate * 100)}
            onChange={e => setWinRate(+e.target.value / 100)}
            style={{ width: '100%', accentColor: C.brand as string, cursor: 'pointer' }}
            aria-label="Win rate percentage slider"
          />
          <div style={{ ...inputStyle, textAlign: 'center', marginTop: 4 }}>
            <input
              type="number" min={0} max={100} step={1}
              value={Math.round(winRate * 100)}
              onChange={e => setWinRate(Math.min(100, Math.max(0, +e.target.value)) / 100)}
              style={{ background: 'none', border: 'none', color: C.text, fontSize: F.sm, width: '100%', textAlign: 'center', outline: 'none' }}
              aria-label="Win rate percentage"
            />
          </div>
        </div>
        <div>
          <div style={labelStyle}>Avg Win ($)</div>
          <input
            type="range"
            min={10} max={2000} step={10}
            value={avgWin}
            onChange={e => setAvgWin(+e.target.value)}
            style={{ width: '100%', accentColor: C.bull as string, cursor: 'pointer' }}
            aria-label="Average win amount slider"
          />
          <div style={{ ...inputStyle, textAlign: 'center', marginTop: 4 }}>
            <input
              type="number" min={1} max={10000} step={10}
              value={avgWin}
              onChange={e => setAvgWin(Math.max(1, +e.target.value))}
              style={{ background: 'none', border: 'none', color: C.text, fontSize: F.sm, width: '100%', textAlign: 'center', outline: 'none' }}
              aria-label="Average win amount"
            />
          </div>
        </div>
        <div>
          <div style={labelStyle}>Avg Loss ($)</div>
          <input
            type="range"
            min={10} max={2000} step={10}
            value={avgLoss}
            onChange={e => setAvgLoss(+e.target.value)}
            style={{ width: '100%', accentColor: C.bear as string, cursor: 'pointer' }}
            aria-label="Average loss amount slider"
          />
          <div style={{ ...inputStyle, textAlign: 'center', marginTop: 4 }}>
            <input
              type="number" min={1} max={10000} step={10}
              value={avgLoss}
              onChange={e => setAvgLoss(Math.max(1, +e.target.value))}
              style={{ background: 'none', border: 'none', color: C.text, fontSize: F.sm, width: '100%', textAlign: 'center', outline: 'none' }}
              aria-label="Average loss amount"
            />
          </div>
        </div>
      </div>

      {/* Visual breakdown bar */}
      <div style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: F.xs, color: C.muted, marginBottom: 4 }}>
          <span style={{ color: C.bull }}>Expected Gain ({(winRate * 100).toFixed(0)}% x ${avgWin})</span>
          <span style={{ color: C.bear }}>Expected Loss ({((1 - winRate) * 100).toFixed(0)}% x ${avgLoss})</span>
        </div>
        <div style={{ height: 14, borderRadius: R.pill, overflow: 'hidden', display: 'flex' }}>
          <div style={{ width: `${gainPct}%`, background: C.bull, transition: 'width 0.2s' }} />
          <div style={{ width: `${lossPct}%`, background: C.bear, transition: 'width 0.2s' }} />
        </div>
      </div>

      {/* Monthly projection + breakeven */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        <div style={{ padding: '10px 14px', background: C.surfaceHover, border: `1px solid ${C.border}`, borderRadius: R.md }}>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 2 }}>Monthly Projection</div>
          <div style={{ fontSize: F.md, fontWeight: 800, color: isPositive ? C.bull : C.bear }}>
            {isPositive ? '+' : ''}${monthlyEV.toFixed(0)}
          </div>
          <div style={{ fontSize: F.xs, color: C.muted }}>If {tradesPerMonth} trades/month</div>
        </div>
        <div style={{ padding: '10px 14px', background: C.surfaceHover, border: `1px solid ${C.border}`, borderRadius: R.md }}>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 2 }}>Breakeven Win Rate</div>
          <div style={{ fontSize: F.md, fontWeight: 800, color: winRate >= breakevenWR ? C.bull : C.bear }}>
            {(breakevenWR * 100).toFixed(1)}%
          </div>
          <div style={{ fontSize: F.xs, color: C.muted }}>
            Need &ge;{(breakevenWR * 100).toFixed(1)}% to be profitable
          </div>
        </div>
      </div>
    </motion.div>
  );
}

// ─── Position Size Demo ──────────────────────────────────────────────────────

export function PositionSizeDemo() {
  const examples = [
    { confidence: 65, label: 'Low Confidence', notional: 500, leverage: '2x', barColor: C.warn, riskDollars: 150 },
    { confidence: 75, label: 'Medium Confidence', notional: 1500, leverage: '5x', barColor: C.brand, riskDollars: 150 },
    { confidence: 90, label: 'High Confidence', notional: 3000, leverage: '10x', barColor: C.bull, riskDollars: 150 },
  ];

  const maxNotional = 3000;

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
    >
      <div style={{ fontSize: F.sm, fontWeight: 800, color: C.text, marginBottom: 6 }}>
        How Confidence Affects Position Size
      </div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 20, lineHeight: 1.6 }}>
        Higher confidence = bot sizes up, but max risk per trade stays fixed at 1.5%
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16 }}>
        {examples.map((ex) => {
          const barPct = (ex.notional / maxNotional) * 100;
          return (
            <div
              key={ex.label}
              style={{
                ...Glass.card,
                background: ex.barColor + '0e',
                border: `1px solid ${ex.barColor}30`,
                borderRadius: R.md,
                padding: '16px 14px',
              }}
            >
              {/* Confidence badge */}
              <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: F.xs, color: C.muted, fontWeight: 600 }}>{ex.label}</span>
                <span style={{
                  fontSize: F.xs,
                  fontWeight: 800,
                  padding: '2px 8px',
                  borderRadius: R.pill,
                  background: ex.barColor + '22',
                  color: ex.barColor,
                  border: `1px solid ${ex.barColor}44`,
                }}>
                  {ex.confidence}%
                </span>
              </div>

              {/* Horizontal position bar */}
              <div style={{ marginBottom: 10 }}>
                <div style={{ fontSize: 10, color: C.muted, marginBottom: 4 }}>Notional Size</div>
                <div style={{ height: 18, background: C.border + '60', borderRadius: R.sm, overflow: 'hidden', position: 'relative' }}>
                  <div style={{
                    width: `${barPct}%`,
                    height: '100%',
                    background: ex.barColor,
                    borderRadius: R.sm,
                    transition: 'width 0.3s',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'flex-end',
                    paddingRight: 4,
                  }}>
                    {barPct > 20 && (
                      <span style={{ fontSize: 9, fontWeight: 700, color: '#fff', whiteSpace: 'nowrap' }}>
                        ${ex.notional.toLocaleString()}
                      </span>
                    )}
                  </div>
                  {barPct <= 20 && (
                    <span style={{ position: 'absolute', left: `${barPct + 2}%`, top: 2, fontSize: 9, fontWeight: 700, color: ex.barColor, whiteSpace: 'nowrap' }}>
                      ${ex.notional.toLocaleString()}
                    </span>
                  )}
                </div>
              </div>

              {/* Leverage pill */}
              <div style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 10, color: C.muted }}>Leverage:</span>
                <span style={{
                  fontSize: F.xs,
                  fontWeight: 700,
                  padding: '1px 7px',
                  borderRadius: R.pill,
                  background: C.surfaceHover,
                  color: ex.barColor,
                  border: `1px solid ${ex.barColor}33`,
                }}>
                  {ex.leverage}
                </span>
              </div>

              {/* Risk line */}
              <div style={{
                fontSize: F.xs,
                color: C.muted,
                padding: '6px 8px',
                background: C.warn + '0e',
                border: `1px solid ${C.warn}22`,
                borderRadius: R.sm,
                lineHeight: 1.5,
              }}>
                Risk: <strong style={{ color: C.warn }}>${ex.riskDollars}</strong>{' '}
                <span style={{ color: C.faint }}>(1.5% of $10K)</span>
              </div>
            </div>
          );
        })}
      </div>

      <div style={{
        marginTop: 14,
        padding: '10px 14px',
        ...Glass.card,
        background: C.brand + '10',
        border: `1px solid ${C.brand}30`,
        borderRadius: R.md,
        fontSize: F.xs,
        color: C.textSub,
        lineHeight: 1.7,
      }}>
        The dollar risk ($150) stays constant across all confidence levels -- only the position notional and leverage change. This is achieved by adjusting quantity, not the stop width.
      </div>
    </motion.div>
  );
}

export default { PositionSizeCalc, RRCalc, CompoundCalc, ExpectedValueCalc, PositionSizeDemo };
