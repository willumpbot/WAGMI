'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { C, R, S, F } from '../src/theme';

// ─── Accordion Card ───────────────────────────────────────────────────────────

function AccordionCard({
  title,
  badge,
  badgeColor,
  defaultOpen = false,
  children,
}: {
  title: string;
  badge?: string;
  badgeColor?: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div
      style={{
        background: C.card,
        border: `1px solid ${open ? C.borderBright : C.border}`,
        borderRadius: R.lg,
        marginBottom: 12,
        overflow: 'hidden',
        transition: 'border-color 0.15s',
      }}
    >
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '16px 20px',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          textAlign: 'left',
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {badge && (
            <span
              style={{
                fontSize: F.xs,
                fontWeight: 700,
                padding: '2px 8px',
                borderRadius: R.pill,
                background: (badgeColor || C.brand) + '22',
                color: badgeColor || C.brand,
                flexShrink: 0,
              }}
            >
              {badge}
            </span>
          )}
          <span style={{ fontSize: F.md, fontWeight: 700, color: C.text }}>{title}</span>
        </div>
        <span style={{ color: C.muted, fontSize: 14, transition: 'transform 0.2s', transform: open ? 'rotate(180deg)' : 'rotate(0deg)', flexShrink: 0 }}>▼</span>
      </button>
      {open && (
        <div style={{ padding: '4px 20px 20px', fontSize: F.sm, color: C.textSub, lineHeight: 1.8 }}>
          {children}
        </div>
      )}
    </div>
  );
}

// ─── Info Box ─────────────────────────────────────────────────────────────────

function InfoBox({ children, color = C.info }: { children: React.ReactNode; color?: string }) {
  return (
    <div
      style={{
        padding: '12px 16px',
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
    </div>
  );
}

// ─── Agent Pipeline SVG ───────────────────────────────────────────────────────

function AgentPipelineDiagram() {
  const agents = [
    { name: 'Regime', model: 'Haiku', color: C.info, desc: 'Market regime classification' },
    { name: 'Trade', model: 'Sonnet', color: C.brand, desc: 'Go / Skip / Flip decision' },
    { name: 'Risk', model: 'Haiku', color: C.warn, desc: 'Position sizing + risk flags' },
    { name: 'Critic', model: 'Sonnet', color: C.bear, desc: 'Stress-tests thesis, veto power' },
    { name: 'Learning', model: 'Haiku', color: C.bull, desc: 'Post-trade lessons (offline)' },
  ];

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, overflowX: 'auto', padding: '8px 0' }}>
      {agents.map((agent, i) => (
        <React.Fragment key={agent.name}>
          <div
            style={{
              background: agent.color + '18',
              border: `1px solid ${agent.color}55`,
              borderRadius: R.md,
              padding: '10px 14px',
              textAlign: 'center',
              minWidth: 100,
              flexShrink: 0,
            }}
          >
            <div style={{ fontSize: F.sm, fontWeight: 700, color: agent.color, marginBottom: 2 }}>{agent.name}</div>
            <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>{agent.model}</div>
            <div style={{ fontSize: 10, color: C.textSub, lineHeight: 1.4 }}>{agent.desc}</div>
          </div>
          {i < agents.length - 1 && (
            <div style={{ flexShrink: 0, padding: '0 4px', color: C.muted, fontSize: 16 }}>→</div>
          )}
        </React.Fragment>
      ))}
    </div>
  );
}

// ─── Gate Flow SVG ────────────────────────────────────────────────────────────

function GateFlowDiagram() {
  const gates = [
    { n: 1, label: 'Validity', desc: 'SL width ≥ 0.3%, proper direction', color: C.info },
    { n: 2, label: 'Circuit Breaker', desc: 'No daily loss limit breach', color: C.brand },
    { n: 3, label: 'Position Limits', desc: 'Max open positions not exceeded', color: C.warn },
    { n: 4, label: 'Leverage', desc: 'Calculated leverage within safe range', color: C.purple },
    { n: 5, label: 'Liquidation', desc: 'Liquidation price buffer adequate', color: C.bear },
    { n: 6, label: 'Sizing', desc: 'Position size within risk limits', color: C.bull },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
      {/* Signal in */}
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 4 }}>
        <div style={{ padding: '6px 20px', background: C.surfaceHover, borderRadius: R.pill, fontSize: F.sm, fontWeight: 700, color: C.textSub }}>
          📡 Signal Generated
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 4, color: C.muted }}>↓</div>

      {gates.map((gate, i) => (
        <React.Fragment key={gate.n}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 28, height: 28, borderRadius: '50%', background: gate.color, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: F.xs, fontWeight: 800, color: '#fff', flexShrink: 0 }}>
              {gate.n}
            </div>
            <div style={{ flex: 1, padding: '8px 12px', background: gate.color + '12', border: `1px solid ${gate.color}33`, borderRadius: R.sm }}>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: gate.color }}>{gate.label}</div>
              <div style={{ fontSize: F.xs, color: C.muted }}>{gate.desc}</div>
            </div>
            <div style={{ fontSize: F.xs, padding: '3px 8px', background: C.bull + '18', color: C.bull, borderRadius: R.pill, fontWeight: 700 }}>✓ PASS</div>
          </div>
          {i < gates.length - 1 && (
            <div style={{ display: 'flex', justifyContent: 'center', margin: '2px 0', color: C.muted }}>↓</div>
          )}
        </React.Fragment>
      ))}

      {/* Trade out */}
      <div style={{ display: 'flex', justifyContent: 'center', marginTop: 4, marginBottom: 4, color: C.muted }}>↓</div>
      <div style={{ display: 'flex', justifyContent: 'center' }}>
        <div style={{ padding: '8px 24px', background: C.bull + '22', border: `1px solid ${C.bull}44`, borderRadius: R.pill, fontSize: F.sm, fontWeight: 700, color: C.bull }}>
          ✅ Trade Executed
        </div>
      </div>
    </div>
  );
}

// ─── Regime Table ─────────────────────────────────────────────────────────────

function RegimeTable() {
  const regimes = [
    { name: 'trend', emoji: '📈', desc: 'Price moving strongly in one direction', behaviour: 'Bot favours momentum trades. Buy dips in uptrend, sell rallies in downtrend.', risk: 'Low-Med' },
    { name: 'range', emoji: '↔️', desc: 'Price bouncing between support and resistance', behaviour: 'Bot waits for extreme zones. Mean-reversion setups only.', risk: 'Low' },
    { name: 'panic', emoji: '🔴', desc: 'Rapid, disorderly sell-off or flash crash', behaviour: 'Bot pauses or uses very tight sizing. High risk of slippage.', risk: 'Very High' },
    { name: 'high_volatility', emoji: '⚡', desc: 'Expanded ranges, fast candles, unpredictable', behaviour: 'Wider stops required. Bot reduces confidence thresholds.', risk: 'High' },
    { name: 'low_liquidity', emoji: '💧', desc: 'Thin order book, large spread', behaviour: 'Bot reduces position size to avoid slippage impact.', risk: 'Med-High' },
    { name: 'news_dislocation', emoji: '📰', desc: 'Price moved by news event, not technicals', behaviour: 'Bot waits for dust to settle before re-entering.', risk: 'Unpredictable' },
  ];

  return (
    <div style={{ overflowX: 'auto' }}>
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
    </div>
  );
}

// ─── Position Size Calculator ─────────────────────────────────────────────────

function PositionSizeCalc() {
  const [accountSize, setAccountSize] = useState(10000);
  const [riskPct, setRiskPct] = useState(1.5);
  const [entry, setEntry] = useState(95000);
  const [stopLoss, setStopLoss] = useState(94200);

  const riskDollars = (accountSize * riskPct) / 100;
  const stopDist = Math.abs(entry - stopLoss);
  const stopDistPct = entry > 0 ? (stopDist / entry) * 100 : 0;
  const positionSize = stopDist > 0 ? riskDollars / stopDist : 0;
  const notionalValue = positionSize * entry;
  const leverage = accountSize > 0 ? notionalValue / accountSize : 0;

  const inputStyle: React.CSSProperties = {
    padding: '8px 12px', background: C.surfaceHover, border: `1px solid ${C.border}`,
    borderRadius: R.sm, color: C.text, fontSize: F.sm, width: '100%', outline: 'none',
    fontVariantNumeric: 'tabular-nums',
  };
  const labelStyle: React.CSSProperties = { fontSize: F.xs, color: C.muted, fontWeight: 600, marginBottom: 4 };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
      <div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
          <div>
            <div style={labelStyle}>Account Size ($)</div>
            <input type="number" style={inputStyle} value={accountSize} onChange={e => setAccountSize(+e.target.value)} min={100} />
          </div>
          <div>
            <div style={labelStyle}>Risk Per Trade (%)</div>
            <input type="number" style={inputStyle} value={riskPct} step={0.1} onChange={e => setRiskPct(+e.target.value)} min={0.1} max={10} />
          </div>
          <div>
            <div style={labelStyle}>Entry Price ($)</div>
            <input type="number" style={inputStyle} value={entry} onChange={e => setEntry(+e.target.value)} min={0.01} />
          </div>
          <div>
            <div style={labelStyle}>Stop Loss Price ($)</div>
            <input type="number" style={inputStyle} value={stopLoss} onChange={e => setStopLoss(+e.target.value)} min={0.01} />
          </div>
        </div>
        <div style={{ padding: '10px 14px', background: C.warn + '12', border: `1px solid ${C.warn}30`, borderRadius: R.sm, fontSize: F.xs, color: C.textSub }}>
          Stop distance: <strong style={{ color: C.warn }}>{stopDistPct.toFixed(2)}%</strong> = ${stopDist.toLocaleString(undefined, { maximumFractionDigits: 2 })} per unit
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {[
          { label: 'Max Dollar Risk', value: `$${riskDollars.toLocaleString(undefined, { maximumFractionDigits: 2 })}`, color: C.warn, desc: `${riskPct}% of account` },
          { label: 'Position Size', value: positionSize > 0 ? positionSize.toLocaleString(undefined, { maximumFractionDigits: 4 }) + ' units' : '—', color: C.text, desc: 'BTC / SOL / HYPE etc.' },
          { label: 'Notional Value', value: notionalValue > 0 ? `$${notionalValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}` : '—', color: C.info, desc: 'Total position exposure' },
          { label: 'Effective Leverage', value: leverage > 0 ? `${leverage.toFixed(1)}×` : '—', color: leverage > 10 ? C.bear : leverage > 5 ? C.warn : C.bull, desc: 'Notional ÷ account size' },
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
            ⚠ Leverage &gt;10× is high risk. Consider widening your stop or reducing position size.
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Risk/Reward Calculator ────────────────────────────────────────────────────

function RRCalc() {
  const [entry, setEntry] = useState(95000);
  const [sl, setSl] = useState(94200);
  const [tp1, setTp1] = useState(96400);
  const [tp2, setTp2] = useState(97800);

  const risk = Math.abs(entry - sl);
  const reward1 = Math.abs(tp1 - entry);
  const reward2 = Math.abs(tp2 - entry);
  const rr1 = risk > 0 ? reward1 / risk : 0;
  const rr2 = risk > 0 ? reward2 / risk : 0;
  const slPct = entry > 0 ? (risk / entry) * 100 : 0;
  const tp1Pct = entry > 0 ? (reward1 / entry) * 100 : 0;
  const tp2Pct = entry > 0 ? (reward2 / entry) * 100 : 0;

  const barMax = Math.max(reward2, risk) || 1;

  const inputStyle: React.CSSProperties = {
    padding: '8px 12px', background: C.surfaceHover, border: `1px solid ${C.border}`,
    borderRadius: R.sm, color: C.text, fontSize: F.sm, width: '100%', outline: 'none',
  };
  const labelStyle: React.CSSProperties = { fontSize: F.xs, color: C.muted, fontWeight: 600, marginBottom: 4 };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div style={{ gridColumn: '1/-1' }}>
          <div style={labelStyle}>Entry Price ($)</div>
          <input type="number" style={inputStyle} value={entry} onChange={e => setEntry(+e.target.value)} />
        </div>
        <div>
          <div style={labelStyle}>Stop Loss ($)</div>
          <input type="number" style={inputStyle} value={sl} onChange={e => setSl(+e.target.value)} />
        </div>
        <div>
          <div style={labelStyle}>TP1 ($)</div>
          <input type="number" style={inputStyle} value={tp1} onChange={e => setTp1(+e.target.value)} />
        </div>
        <div style={{ gridColumn: '1/-1' }}>
          <div style={labelStyle}>TP2 (Final Target) ($)</div>
          <input type="number" style={inputStyle} value={tp2} onChange={e => setTp2(+e.target.value)} />
        </div>
      </div>

      <div>
        {/* Visual bar */}
        <div style={{ marginBottom: 16 }}>
          {[
            { label: 'Risk (SL)', dist: risk, pct: slPct, color: C.bear, side: 'down' },
            { label: 'TP1 Reward', dist: reward1, pct: tp1Pct, color: C.bullMid, side: 'up' },
            { label: 'TP2 Reward', dist: reward2, pct: tp2Pct, color: C.bull, side: 'up' },
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
              <div style={{ fontSize: F.xs, color: ok ? C.bullMid : C.bearMid }}>{ok ? '✓ Good' : '✗ Too tight'}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── Compound Growth Calculator ────────────────────────────────────────────────

function CompoundCalc() {
  const [capital, setCapital] = useState(10000);
  const [monthlyPct, setMonthlyPct] = useState(5);
  const [months, setMonths] = useState(12);

  const rows: { month: number; equity: number; gain: number }[] = [];
  let equity = capital;
  for (let m = 1; m <= Math.min(months, 60); m++) {
    const gain = equity * (monthlyPct / 100);
    equity += gain;
    rows.push({ month: m, equity, gain });
  }
  const finalEquity = rows[rows.length - 1]?.equity ?? capital;
  const totalReturn = ((finalEquity - capital) / capital) * 100;
  const maxEquity = finalEquity;

  const inputStyle: React.CSSProperties = {
    padding: '8px 12px', background: C.surfaceHover, border: `1px solid ${C.border}`,
    borderRadius: R.sm, color: C.text, fontSize: F.sm, width: '100%', outline: 'none',
  };
  const labelStyle: React.CSSProperties = { fontSize: F.xs, color: C.muted, fontWeight: 600, marginBottom: 4 };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr', gap: 24 }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div>
          <div style={labelStyle}>Starting Capital ($)</div>
          <input type="number" style={inputStyle} value={capital} onChange={e => setCapital(+e.target.value)} min={100} />
        </div>
        <div>
          <div style={labelStyle}>Monthly Return (%)</div>
          <input type="number" style={inputStyle} value={monthlyPct} step={0.5} onChange={e => setMonthlyPct(+e.target.value)} min={0.1} max={100} />
        </div>
        <div>
          <div style={labelStyle}>Number of Months</div>
          <input type="number" style={inputStyle} value={months} onChange={e => setMonths(Math.min(60, Math.max(1, +e.target.value)))} min={1} max={60} />
        </div>
        <div style={{ padding: '14px 16px', background: C.bull + '12', border: `1px solid ${C.bull}30`, borderRadius: R.md }}>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 4 }}>Final Equity</div>
          <div style={{ fontSize: F['2xl'], fontWeight: 800, color: C.bull }}>${finalEquity.toLocaleString(undefined, { maximumFractionDigits: 0 })}</div>
          <div style={{ fontSize: F.xs, color: C.bullMid }}>+{totalReturn.toFixed(1)}% total</div>
        </div>
      </div>

      {/* Mini chart */}
      <div>
        <svg width="100%" viewBox={`0 0 400 160`} style={{ display: 'block', overflow: 'visible' }}>
          <defs>
            <linearGradient id="compGrad" x1="0" y1="0" x2="0" y2="1">
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
                <path d={area} fill="url(#compGrad)" />
                <polyline fill="none" stroke={C.bull} strokeWidth={2} points={line} strokeLinejoin="round" />
                {/* Start + end labels */}
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
  );
}

// ─── Glossary ─────────────────────────────────────────────────────────────────

const GLOSSARY = [
  { term: 'ATR (Average True Range)', def: 'Measures how much an asset typically moves in a single candle. High ATR = high volatility. The bot uses ATR to size stop losses so they are proportional to actual market movement.' },
  { term: 'SMA (Simple Moving Average)', def: 'Average of the last N closing prices. SMA20 (fast) crosses above SMA50 (slow) = uptrend signal. SMA20 crosses below SMA50 = downtrend signal.' },
  { term: 'RSI (Relative Strength Index)', def: 'Momentum oscillator on a 0-100 scale. Above 70 = potentially overbought (caution on longs). Below 30 = potentially oversold (caution on shorts). The bot uses RSI as one confluence factor among many.' },
  { term: 'Confidence Score', def: 'The bot\'s internal 0-100 rating for how strong a setup is. Based on how many strategies agree and how strongly. Score ≥ 70 is considered a strong signal. The LLM adds its own confidence layer on top.' },
  { term: 'Regime', def: 'Market state classification (trend/range/panic/high_volatility/low_liquidity). Different regimes call for different strategies. The Regime Agent classifies this each evaluation cycle.' },
  { term: 'Ensemble', def: 'The process of combining votes from multiple strategies. The bot uses "weighted_veto" mode: strategies vote, but any strategy can veto a trade if conditions are too risky.' },
  { term: 'Veto', def: 'When the Critic agent (or a strategy) overrides a trade signal. Usually triggered by conflicting signals, high risk conditions, or poor risk/reward ratio.' },
  { term: 'Circuit Breaker', def: 'An automatic stop-trading mechanism that activates when losses exceed a daily threshold or a certain number of consecutive losses occur. Prevents catastrophic drawdowns.' },
  { term: 'Drawdown', def: 'The peak-to-trough decline in account equity. Max drawdown is the worst historical decline. Lower is better. The bot aims to keep max drawdown below 15%.' },
  { term: 'Profit Factor', def: 'Gross profit divided by gross loss. A ratio above 1.0 means the strategy makes more than it loses. 1.5× is good; 2.0× is excellent.' },
  { term: 'R:R (Risk/Reward Ratio)', def: 'How much profit you aim for vs how much you risk. The bot requires R:R ≥ 1.0 before entering. A 2:1 setup means potential gain is twice the potential loss.' },
  { term: 'Accumulation Zone', def: 'Price level below current price where the bot considers the asset "cheap" relative to its volatility bands. Good levels to consider longs.' },
  { term: 'Distribution Zone', def: 'Price level above current price where the bot considers the asset "expensive". Good levels to consider profit-taking or shorts.' },
  { term: 'Funding Rate', def: 'The cost of holding a perpetual futures position. Positive funding = longs pay shorts. Extreme funding rates signal crowded trades the bot may fade.' },
  { term: 'Liquidation Price', def: 'The price at which your leveraged position gets automatically closed by the exchange. The bot always checks that the stop loss is hit long before the liquidation price.' },
  { term: 'Trailing Stop', def: 'A stop loss that moves up with a winning trade (for longs). Locks in profit as price rises, closes only if price falls back by a set amount. The bot uses progressive trailing after TP1 is hit.' },
  { term: 'Sharpe Ratio', def: 'Return per unit of risk taken. Higher = better. Adjusts for volatility so a steady 10% return is rated better than an erratic 15% return.' },
  { term: 'Open Interest (OI)', def: 'Total number of outstanding futures contracts. Rising OI + rising price = strong trend. Rising OI + falling price = distribution. The bot monitors OI divergence as a signal.' },
  { term: 'Advisory Mode', def: 'The LLM operates in advisory mode by default: it analyses and logs what it would trade, but does NOT execute trades. Useful for monitoring AI judgement before giving it execution power.' },
  { term: 'Slippage', def: 'The difference between the price you expected to trade at and the price you actually got. Higher volatility and lower liquidity = more slippage. The bot accounts for 0.05-0.1% slippage in its cost model.' },
  { term: 'VWAP (Volume-Weighted Average Price)', def: 'The average price weighted by volume, resetting each day. Institutional traders use VWAP as a benchmark. Price above VWAP = bullish bias; below = bearish. The Multi-Tier Quality strategy anchors its entries to VWAP.' },
  { term: 'MACD (Moving Average Convergence Divergence)', def: 'A momentum indicator that shows the relationship between two EMAs. When the MACD line crosses above the signal line = bullish momentum. Used by the bot\'s Regime Trend strategy for trend confirmation.' },
  { term: 'Bollinger Bands', def: 'Volatility bands placed 2 standard deviations above and below a moving average. Price near upper band = overbought. Near lower band = oversold. When bands squeeze (narrow), a big move is typically coming.' },
  { term: 'Keltner Channel', def: 'Volatility envelope based on ATR. When Bollinger Bands are inside Keltner Channels, the market is in a "squeeze" — coiling energy before a breakout. The Confidence Scorer uses squeeze detection.' },
  { term: 'EMA (Exponential Moving Average)', def: 'Like SMA but gives more weight to recent prices, making it more responsive to current conditions. The bot uses EMA crossovers (short EMA crossing long EMA) as trend signals.' },
  { term: 'ADX (Average Directional Index)', def: 'Measures the strength of a trend, regardless of direction. ADX above 25 = strong trend; below 20 = range/choppy market. The bot uses ADX to avoid trading range-bound markets with trend strategies.' },
  { term: 'WaveTrend', def: 'A custom momentum oscillator that combines channel-based smoothing with momentum. The Regime Trend strategy uses WaveTrend to detect oversold/overbought conditions within the context of the current regime.' },
  { term: 'Paper Trading', def: 'Simulated trading with real market data but no real money. The bot runs in paper mode by default. All signals, decisions, and "trades" are executed in a virtual account to test performance before going live.' },
  { term: 'Live Trading', def: 'Trading with real capital on the exchange. Requires the bot to be configured with exchange API keys and LLM_MODE ≥ 1. Only activate after extended paper trading validation.' },
  { term: 'Entry Price', def: 'The price at which a trade position is opened. The bot calculates entry based on current market price at the time the signal is confirmed. For limit orders, the entry may differ slightly from the trigger price.' },
  { term: 'Take Profit (TP)', def: 'Pre-set price target where a portion of a position is closed to realize profit. The bot uses two targets: TP1 closes ~50% of the position and moves the stop to breakeven; TP2 is the final target for the remainder.' },
  { term: 'Breakeven Stop', def: 'Moving the stop loss to the entry price after TP1 is hit. This guarantees the trade cannot lose money on the remaining position. The bot does this automatically after TP1.' },
  { term: 'Confluence', def: 'When multiple independent signals all point in the same direction. High confluence = higher confidence trade. The bot requires at least 2 strategies to agree, plus regime alignment, before considering a trade.' },
  { term: 'Perpetual Futures (Perps)', def: 'Futures contracts with no expiry date. Unlike regular futures, they track the spot price via a funding rate mechanism. Hyperliquid trades are all perpetual futures, allowing both long and short positions with leverage.' },
  { term: 'Long / Short', def: 'Long = betting price goes up. Short = betting price goes down. Perpetual futures allow you to profit in both directions. The bot can take either direction depending on signal and regime.' },
  { term: 'Mark Price', def: 'The "fair" price of a futures contract, calculated using a weighted average of spot prices across exchanges. Used by Hyperliquid to calculate unrealized PnL and trigger liquidations — not the last traded price.' },
  { term: 'Margin', def: 'The collateral deposited to open and maintain a leveraged position. Cross margin shares your full account balance across positions. Isolated margin limits risk to a fixed amount per position. The bot uses isolated margin.' },
  { term: 'Unrealized PnL', def: 'The profit or loss on an open position if it were closed at the current price. Shown in the dashboard as "open position PnL." Not banked until the position closes.' },
  { term: 'Realized PnL', def: 'Profit or loss that has been locked in by closing a position. This is what counts for your account equity.' },
  { term: 'Basis Points (bps)', def: '1 basis point = 0.01%. Used to express small percentage changes. A 50bps stop loss = 0.5% below entry. Fees are often quoted in basis points (e.g. 3.5bps maker fee = 0.035%).' },
  { term: 'Thesis', def: 'The reason for taking a trade. The Trade agent constructs a thesis: "BTC is in an accumulation zone, regime is trend, RSI is 58, 3/4 strategies agree. Thesis: continuation long." The Critic then stress-tests it.' },
  { term: 'Counter-Thesis', def: 'The opposite argument to the trade thesis. The Critic agent is required to provide a counter-thesis before it can veto a trade — it cannot just say "bad trade" without explaining why.' },
  { term: 'Backtest', def: 'Running the bot\'s strategies on historical price data to see how they would have performed. Results include total return, win rate, drawdown, and per-trade breakdown. Used to validate strategy changes before going live.' },
  { term: 'Walk-Forward Testing', def: 'A more rigorous form of backtesting where the strategy is optimized on one period and tested on the next, then the window moves forward. Helps detect overfitting — strategies that work on past data but fail on new data.' },
  { term: 'Overfitting', def: 'When a strategy is tuned so precisely to historical data that it fails on future data. The bot avoids overfitting by using robust, logic-based indicators rather than curve-fitted parameters.' },
  { term: 'Monte Carlo Simulation', def: 'Running thousands of random simulations of possible future price paths based on historical volatility. The bot uses this to find statistical support/resistance zones that hold across many possible scenarios.' },
  { term: 'Hyperliquid', def: 'The decentralized perpetuals exchange the bot trades on. Key advantages: fully onchain, sub-second execution, deep liquidity, low fees (0.035% maker / 0.05% taker), and a wide range of tradeable assets.' },
  { term: 'API Key', def: 'A credential pair (API key + secret) that allows software to interact with an exchange on your behalf. Required for live trading. Never share your API key — store it encrypted in your .env file only.' },
  { term: 'Hot Wallet', def: 'A wallet connected to the internet, used for exchange trading. Contrasted with cold storage (hardware wallets). Only fund your trading wallet with what you are willing to risk.' },
  { term: 'Equity Curve', def: 'A chart showing account equity over time. A smooth upward-sloping curve with small drawdowns is the goal. The bot\'s backtest results page shows the equity curve for all tested periods.' },
  { term: 'Max Drawdown', def: 'The largest peak-to-trough decline in equity during a trading period. A strategy with a 30% max drawdown would have caused an account to fall 30% from its peak before recovering. Lower is better.' },
  { term: 'Calmar Ratio', def: 'Annual return divided by maximum drawdown. A ratio above 1.0 means the strategy earns more annually than its worst drawdown. Higher is better.' },
  { term: 'Win Rate', def: 'The percentage of trades that are profitable. A strategy can be profitable with a win rate below 50% if the average win is much larger than the average loss. The bot currently targets win rates above 60%.' },
  { term: 'Expectancy', def: 'The average profit per trade, accounting for both win rate and average win/loss size. Formula: (WinRate × AvgWin) − (LossRate × AvgLoss). Positive expectancy means the system is profitable over many trades.' },
];

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function Learn() {
  const [glossarySearch, setGlossarySearch] = useState('');
  const filteredGlossary = GLOSSARY.filter(
    (g) =>
      g.term.toLowerCase().includes(glossarySearch.toLowerCase()) ||
      g.def.toLowerCase().includes(glossarySearch.toLowerCase())
  );

  return (
    <div>
      {/* ── Header ───────────────────────────────────── */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>
          Knowledge Base
        </div>
        <h1 style={{ margin: 0, fontSize: F['3xl'], fontWeight: 800, color: C.text, letterSpacing: -0.5 }}>
          Learn
        </h1>
        <p style={{ margin: '6px 0 0', fontSize: F.sm, color: C.muted, maxWidth: 600 }}>
          Everything you need to understand what the bot is doing, why it trades when it does, and how to make better decisions yourself.
        </p>
      </div>

      {/* ── Quick nav ─────────────────────────────────── */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 32 }}>
        {['What is this bot?', 'Signals', 'AI Brain', 'Risk Management', 'Trade Flow', 'Calculators', 'Copy Trading', 'Glossary'].map((label) => (
          <a
            key={label}
            href={`#${label.toLowerCase().replace(/\?/g, '').replace(/ /g, '-')}`}
            style={{
              fontSize: F.sm,
              padding: '6px 14px',
              borderRadius: R.pill,
              border: `1px solid ${C.border}`,
              color: C.textSub,
              textDecoration: 'none',
              transition: 'all 0.15s',
            }}
          >
            {label}
          </a>
        ))}
      </div>

      {/* ─────────────────────────────────── */}
      <div id="what-is-this-bot" />
      <div style={{ marginBottom: 8, paddingTop: 8 }}>
        <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>01 — Foundation</div>
        <h2 style={{ margin: '0 0 16px', fontSize: F.xl, fontWeight: 700, color: C.text }}>What Is This Bot?</h2>
      </div>

      <AccordionCard title="The 4 Core Strategies" badge="How it works" defaultOpen>
        <p>The bot runs 4 independent strategies simultaneously. Each one looks at different aspects of the market:</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12, marginTop: 12 }}>
          {[
            { name: 'Regime Trend', tf: '1h + 6h', desc: 'Identifies the direction of the trend using WaveTrend and MACD. Only trades in the direction of the dominant regime.' },
            { name: 'Monte Carlo Zones', tf: 'Daily', desc: 'Simulates 1,000 possible future price paths to find statistical support/resistance levels. Trades near high-probability reversal zones.' },
            { name: 'Confidence Scorer', tf: '1h', desc: 'Scores each setup based on 5+ confluence factors: ADX trend strength, MACD, Bollinger/Keltner squeeze, RSI divergence. Higher score = stronger setup.' },
            { name: 'Multi-Tier Quality', tf: '1h + 6h', desc: 'Uses EMA crossovers, VWAP anchoring, and multi-timeframe regime alignment. Only trades when the 1h signal and 6h regime agree.' },
          ].map((s) => (
            <div key={s.name} style={{ padding: '12px 14px', background: C.surfaceHover, borderRadius: R.md }}>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: C.brand, marginBottom: 2 }}>{s.name}</div>
              <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 6 }}>Timeframe: {s.tf}</div>
              <div style={{ fontSize: F.xs, color: C.textSub, lineHeight: 1.6 }}>{s.desc}</div>
            </div>
          ))}
        </div>
      </AccordionCard>

      <AccordionCard title="How Ensemble Voting Works" badge="Weighted-Veto">
        <p>The 4 strategies each cast a vote (BUY, SELL, or abstain). The ensemble uses "weighted-veto" mode:</p>
        <ol style={{ paddingLeft: 20, marginTop: 8 }}>
          <li style={{ marginBottom: 8 }}><strong>Weighted votes:</strong> Each strategy has a performance-based weight. A strategy that has been winning recently gets more influence.</li>
          <li style={{ marginBottom: 8 }}><strong>Minimum votes:</strong> At least 2 strategies must agree on direction before any trade is considered.</li>
          <li style={{ marginBottom: 8 }}><strong>Veto rule:</strong> If any strategy sees a strong counter-signal (e.g., the trend strategy says SHORT while others say LONG), it can veto the trade entirely.</li>
          <li><strong>Confidence floor:</strong> The combined signal must score ≥ 75 confidence before advancing to LLM review.</li>
        </ol>
        <InfoBox color={C.bull}>
          This system is designed to only trade when multiple independent analyses agree. A single strategy firing alone is not enough.
        </InfoBox>
      </AccordionCard>

      <AccordionCard title="Why Hyperliquid?">
        <p>Hyperliquid is a high-performance perpetuals exchange with several features that make it ideal for algo trading:</p>
        <ul style={{ paddingLeft: 20 }}>
          <li style={{ marginBottom: 6 }}>Sub-second order execution — critical for tight stop losses</li>
          <li style={{ marginBottom: 6 }}>Low fees (≈0.035% maker, 0.05% taker) — important for frequent trading</li>
          <li style={{ marginBottom: 6 }}>Onchain settlement — transparent, auditable</li>
          <li style={{ marginBottom: 6 }}>Deep liquidity on BTC, ETH, SOL, HYPE and 50+ other perps</li>
          <li>Up to 50× leverage available (bot uses 2-10× depending on confidence)</li>
        </ul>
      </AccordionCard>

      {/* ─────────────────────────────────── */}
      <div style={{ height: 24 }} />
      <div id="signals" />
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>02 — Signals</div>
        <h2 style={{ margin: '0 0 16px', fontSize: F.xl, fontWeight: 700, color: C.text }}>Understanding Signals</h2>
      </div>

      <AccordionCard title="Signal Score: What 0-100 Means" badge="Confidence">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 12 }}>
          {[
            { range: '0–49', label: 'Weak / No Trade', color: C.bear, desc: 'Bot ignores. Not enough agreement between strategies.' },
            { range: '50–64', label: 'Below Threshold', color: C.warn, desc: 'Some agreement but not enough for the confidence floor. Bot waits.' },
            { range: '65–74', label: 'Moderate', color: C.warnMid, desc: 'Enters consideration queue. LLM reviews and often skips.' },
            { range: '75–84', label: 'Good Setup', color: C.bull, desc: 'Typically trades with standard sizing.' },
            { range: '85–100', label: 'Strong Setup', color: '#22c55e', desc: 'High confidence. Bot may use larger position size.' },
          ].map(({ range, label, color, desc }) => (
            <div key={range} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{ width: 48, flexShrink: 0, fontWeight: 700, fontSize: F.sm, color }}>{range}</div>
              <div style={{ flex: 1, height: 6, background: C.surfaceHover, borderRadius: R.pill, overflow: 'hidden' }}>
                <div style={{ width: `${parseInt(range.split('–')[1])}%`, height: '100%', background: color, borderRadius: R.pill }} />
              </div>
              <div style={{ minWidth: 120, fontSize: F.xs, fontWeight: 700, color }}>{label}</div>
              <div style={{ flex: 2, fontSize: F.xs, color: C.muted }}>{desc}</div>
            </div>
          ))}
        </div>
      </AccordionCard>

      <AccordionCard title="Accumulation & Distribution Zones" badge="Price Zones">
        <p>The Monte Carlo strategy generates four key price levels relative to current price:</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, margin: '12px 0' }}>
          {[
            { label: 'Safe Distribution', color: '#7f1d1d', desc: 'Very expensive. Strong sell zone. Price rarely sustains here.' },
            { label: 'Distribution', color: C.bear, desc: 'Above fair value. Consider taking profit on longs.' },
            { label: '── Current Price ──', color: C.info, desc: '' },
            { label: 'Accumulation', color: C.bull, desc: 'Below fair value. Consider building long positions.' },
            { label: 'Deep Accumulation', color: '#166534', desc: 'Very cheap. High-probability long entry. Strong support.' },
          ].map(({ label, color, desc }) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ width: 12, height: 12, borderRadius: 3, background: color, flexShrink: 0 }} />
              <div style={{ fontSize: F.sm, fontWeight: 600, color, minWidth: 160 }}>{label}</div>
              {desc && <div style={{ fontSize: F.xs, color: C.muted }}>{desc}</div>}
            </div>
          ))}
        </div>
        <InfoBox color={C.info}>
          These zones shift every day as the bot recalculates based on recent volatility. A zone that was "Deep Accumulation" yesterday may be "Accumulation" today if price has moved.
        </InfoBox>
      </AccordionCard>

      <AccordionCard title="Regime Types Explained" badge="Market States" defaultOpen={false}>
        <p>The Regime Agent classifies the market every evaluation cycle. This classification affects which strategies run and how aggressively the bot sizes up:</p>
        <RegimeTable />
      </AccordionCard>

      {/* ─────────────────────────────────── */}
      <div style={{ height: 24 }} />
      <div id="ai-brain" />
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>03 — AI Brain</div>
        <h2 style={{ margin: '0 0 16px', fontSize: F.xl, fontWeight: 700, color: C.text }}>The LLM Multi-Agent System</h2>
      </div>

      <AccordionCard title="Agent Pipeline Overview" badge="5 Agents" badgeColor={C.brand} defaultOpen>
        <p>When multi-agent mode is enabled, every trade goes through 5 specialist Claude AI agents in sequence:</p>
        <div style={{ overflowX: 'auto', marginBottom: 16 }}>
          <AgentPipelineDiagram />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10, marginTop: 12 }}>
          {[
            { agent: 'Regime', model: 'Claude Haiku', role: 'Classifies market regime + directional outlook. Sets the context for all downstream agents.' },
            { agent: 'Trade', model: 'Claude Sonnet', role: 'Forms a directional thesis. Decides Go / Skip / Flip based on all available signals.' },
            { agent: 'Risk', model: 'Claude Haiku', role: 'Sizes the position. Flags portfolio risk overlaps. Sets leverage tier.' },
            { agent: 'Critic', model: 'Claude Sonnet', role: 'Stress-tests the Trade agent\'s thesis. Must provide a counter-thesis if it wants to veto.' },
            { agent: 'Learning', model: 'Claude Haiku', role: 'Post-close only. Extracts lessons and tracks thesis accuracy per setup type.' },
          ].map(({ agent, model, role }) => (
            <div key={agent} style={{ padding: '10px 12px', background: C.surfaceHover, borderRadius: R.md }}>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 2 }}>{agent}</div>
              <div style={{ fontSize: F.xs, color: C.brand, marginBottom: 6 }}>{model}</div>
              <div style={{ fontSize: F.xs, color: C.muted, lineHeight: 1.5 }}>{role}</div>
            </div>
          ))}
        </div>
      </AccordionCard>

      <AccordionCard title="Advisory Mode vs Full Autonomy" badge="Mode Levels">
        <p>The bot supports 6 levels of LLM autonomy (<code>LLM_MODE</code> 0-5):</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
          {[
            { level: '0 — OFF', desc: 'LLM disabled. Pure strategy signals only.', color: C.muted },
            { level: '1 — ADVISORY', desc: 'LLM analyses every setup and logs what it would do. Does NOT execute. This is the default safe mode shown on the dashboard.', color: C.info },
            { level: '2 — VETO_ONLY', desc: 'LLM can veto (block) bad trades, but cannot initiate trades on its own.', color: C.warn },
            { level: '3 — SIZING', desc: 'LLM controls position sizing in addition to veto power.', color: C.warn },
            { level: '4 — DIRECTION', desc: 'LLM can change trade direction (long → short flip).', color: C.bear + 'cc' },
            { level: '5 — FULL', desc: 'LLM has full control: can initiate, veto, resize, and flip trades autonomously.', color: C.bear },
          ].map(({ level, desc, color }) => (
            <div key={level} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
              <div style={{ fontSize: F.xs, fontWeight: 800, color, minWidth: 90, paddingTop: 2 }}>{level}</div>
              <div style={{ fontSize: F.xs, color: C.textSub, lineHeight: 1.6 }}>{desc}</div>
            </div>
          ))}
        </div>
      </AccordionCard>

      <AccordionCard title="What 'AI VETO' Means" badge="VETO" badgeColor={C.bear}>
        <p>A veto happens when the Critic agent (or the LLM in VETO_ONLY+ mode) decides the proposed trade should not be taken.</p>
        <p>The Critic agent is designed to:</p>
        <ul style={{ paddingLeft: 20 }}>
          <li style={{ marginBottom: 6 }}>Challenge the Trade agent's thesis by finding counter-arguments</li>
          <li style={{ marginBottom: 6 }}>Detect conflicting signals the strategies may have missed</li>
          <li style={{ marginBottom: 6 }}>Flag when confidence is high but risk is disproportionate</li>
        </ul>
        <InfoBox color={C.warn}>
          A veto is NOT a guarantee the trade would have lost — it means the AI decided the risk wasn't worth taking given current conditions. In the activity feed, you can see every veto with the reasoning.
        </InfoBox>
      </AccordionCard>

      {/* ─────────────────────────────────── */}
      <div style={{ height: 24 }} />
      <div id="risk-management" />
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: F.xs, color: C.warn, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>04 — Safety</div>
        <h2 style={{ margin: '0 0 16px', fontSize: F.xl, fontWeight: 700, color: C.text }}>Risk Management</h2>
      </div>

      <AccordionCard title="Circuit Breakers" badge="Auto-Stop" badgeColor={C.bear} defaultOpen>
        <p>Circuit breakers are automatic kill switches that prevent catastrophic losses:</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10, marginTop: 8 }}>
          {[
            { name: 'Daily Loss Limit', desc: 'If the bot loses more than X% of current equity in a single day, it stops trading until the next day.' },
            { name: 'Consecutive Losses', desc: 'After N losses in a row, the bot pauses and waits for conditions to improve before re-entering.' },
            { name: 'Position Limits', desc: 'Maximum number of open positions at once. Prevents over-exposure to correlated assets.' },
            { name: 'Drawdown Guard', desc: 'If equity drops below a rolling 30-day peak by more than X%, the bot enters a cautious mode with reduced sizing.' },
          ].map(({ name, desc }) => (
            <div key={name} style={{ padding: '12px 14px', background: C.bear + '10', border: `1px solid ${C.bear}22`, borderRadius: R.md }}>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: C.bear, marginBottom: 4 }}>{name}</div>
              <div style={{ fontSize: F.xs, color: C.textSub, lineHeight: 1.5 }}>{desc}</div>
            </div>
          ))}
        </div>
      </AccordionCard>

      <AccordionCard title="Position Sizing & Leverage">
        <p>The bot uses a fixed fractional position sizing model:</p>
        <InfoBox color={C.brand}>
          <strong>Risk per trade = 1.5% of current equity.</strong> If your account is $10,000, no single trade risks more than $150.
        </InfoBox>
        <p>Leverage is calculated dynamically based on:</p>
        <ul style={{ paddingLeft: 20 }}>
          <li style={{ marginBottom: 6 }}>Signal confidence (higher confidence = higher allowed leverage)</li>
          <li style={{ marginBottom: 6 }}>Number of strategies agreeing (3/4 agreement allows more than 2/4)</li>
          <li style={{ marginBottom: 6 }}>Distance to stop loss (wider stop = lower leverage to keep $ risk constant)</li>
          <li>Market regime (panic or high_volatility = leverage cap reduced)</li>
        </ul>
        <p>The result: leverage typically ranges 2-7× for normal setups and rarely exceeds 10×.</p>
      </AccordionCard>

      <AccordionCard title="Stop Loss Philosophy">
        <p>Stop losses are placed at the <strong>Deep Accumulation zone</strong> for longs (or Safe Distribution zone for shorts) — not at arbitrary percentage levels.</p>
        <p>Why this works better than percentage-based stops:</p>
        <ul style={{ paddingLeft: 20 }}>
          <li style={{ marginBottom: 6 }}>Zones are based on actual volatility (ATR), not arbitrary numbers</li>
          <li style={{ marginBottom: 6 }}>They represent price levels where the trade thesis is genuinely invalid</li>
          <li>They adapt to each asset's current volatility regime</li>
        </ul>
        <p>After TP1 is hit, the stop loss moves to breakeven and a trailing stop activates — locking in profit progressively.</p>
      </AccordionCard>

      {/* ─────────────────────────────────── */}
      <div style={{ height: 24 }} />
      <div id="trade-flow" />
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: F.xs, color: C.bull, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>05 — Process</div>
        <h2 style={{ margin: '0 0 16px', fontSize: F.xl, fontWeight: 700, color: C.text }}>How a Trade Flows</h2>
      </div>

      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px', marginBottom: 12 }}>
        <p style={{ margin: '0 0 20px', fontSize: F.sm, color: C.textSub }}>
          A signal must pass through 6 sequential gates before becoming a trade. If it fails any gate, it&apos;s rejected and logged.
        </p>
        <GateFlowDiagram />
      </div>

      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 24px', marginBottom: 24 }}>
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 12 }}>After the Trade Opens</div>
        <div style={{ display: 'flex', gap: 0, overflowX: 'auto' }}>
          {[
            { state: 'IDLE', desc: 'No position', color: C.muted },
            { state: 'OPEN', desc: 'Position active, stop loss set', color: C.info },
            { state: 'TP1_HIT', desc: 'First profit target reached, size reduced', color: C.bull },
            { state: 'TRAILING', desc: 'Stop moved to BE+, trailing up', color: C.brand },
            { state: 'CLOSED', desc: 'Trade complete, results logged', color: C.bull },
          ].map((s, i) => (
            <React.Fragment key={s.state}>
              <div style={{ textAlign: 'center', flexShrink: 0, minWidth: 90 }}>
                <div style={{ padding: '6px 10px', background: s.color + '20', border: `1px solid ${s.color}44`, borderRadius: R.sm, marginBottom: 6 }}>
                  <div style={{ fontSize: F.xs, fontWeight: 700, color: s.color }}>{s.state}</div>
                </div>
                <div style={{ fontSize: 10, color: C.muted, lineHeight: 1.4 }}>{s.desc}</div>
              </div>
              {i < 4 && <div style={{ color: C.muted, fontSize: 12, padding: '8px 2px', flexShrink: 0, alignSelf: 'flex-start' }}>→</div>}
            </React.Fragment>
          ))}
        </div>
      </div>

      {/* ─────────────────────────────────── */}
      <div style={{ height: 24 }} />
      <div id="calculators" />
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>06 — Tools</div>
        <h2 style={{ margin: '0 0 16px', fontSize: F.xl, fontWeight: 700, color: C.text }}>Trading Calculators</h2>
      </div>

      <AccordionCard title="Position Size Calculator" badge="Risk Per Trade" badgeColor={C.warn} defaultOpen>
        <p style={{ marginBottom: 16 }}>Enter your account size, risk tolerance, and stop distance. The calculator shows exactly how many units to buy and what leverage that implies.</p>
        <PositionSizeCalc />
        <div style={{ marginTop: 16, padding: '10px 14px', background: C.info + '10', border: `1px solid ${C.info}25`, borderRadius: R.sm, fontSize: F.xs, color: C.textSub, lineHeight: 1.7 }}>
          <strong>Pro tip:</strong> The bot uses 1.5% risk per trade by default. At $10K account, that&apos;s $150 max risk per trade. Effective leverage of 3-7× is healthy for most setups.
        </div>
      </AccordionCard>

      <AccordionCard title="Risk/Reward Calculator" badge="R:R Ratio">
        <p style={{ marginBottom: 16 }}>Visualize your setup&apos;s risk-to-reward ratio before taking a trade. The bot requires R:R ≥ 1.0 to pass Gate 1.</p>
        <RRCalc />
        <div style={{ marginTop: 16, padding: '10px 14px', background: C.bull + '10', border: `1px solid ${C.bull}25`, borderRadius: R.sm, fontSize: F.xs, color: C.textSub, lineHeight: 1.7 }}>
          <strong>Target:</strong> R:R ≥ 1.5:1 to TP1 and ≥ 2.5:1 to TP2. Higher R:R means you can be wrong more often and still be profitable overall.
        </div>
      </AccordionCard>

      <AccordionCard title="Compound Growth Calculator" badge="Monthly Returns">
        <p style={{ marginBottom: 16 }}>See how consistent monthly returns compound over time. The bot&apos;s 30-day backtest averaged ~11.3% — see what that looks like extended over a year.</p>
        <CompoundCalc />
        <div style={{ marginTop: 16, padding: '10px 14px', background: C.brand + '10', border: `1px solid ${C.brand}25`, borderRadius: R.sm, fontSize: F.xs, color: C.textSub, lineHeight: 1.7 }}>
          <strong>Reality check:</strong> Past backtest results don&apos;t guarantee future performance. Use conservative estimates (3-5% monthly) for realistic projections.
        </div>
      </AccordionCard>

      {/* ─────────────────────────────────── */}
      <div style={{ height: 24 }} />
      <div id="copy-trade-guide" />
      <div style={{ marginBottom: 8 }}>
        <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>07 — Copy Trading</div>
        <h2 style={{ margin: '0 0 16px', fontSize: F.xl, fontWeight: 700, color: C.text }}>How to Copy-Trade This Bot</h2>
      </div>

      <AccordionCard title="Step-by-Step: Copy a Signal" badge="Beginner" badgeColor={C.bull} defaultOpen>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[
            { n: 1, title: 'Watch the Signals page', desc: 'Go to Signals → watch for a signal card to appear with a score ≥ 75. The higher the score, the stronger the bot\'s conviction.' },
            { n: 2, title: 'Check the regime', desc: 'Look at the current regime badge in the top nav. "TREND" or "RANGE" regimes are typically safer. Avoid copying trades in "PANIC" or "HIGH_VOLATILITY" regimes unless you understand the risk.' },
            { n: 3, title: 'Calculate your position size', desc: 'Use the Position Size Calculator above. Risk 1-2% of your capital max. Enter the signal\'s entry, SL, and TP levels into the calculator.' },
            { n: 4, title: 'Set your order on Hyperliquid', desc: 'Open Hyperliquid → select the symbol → set a limit order at the entry price, or market order if price is currently at the entry zone. Set your stop loss immediately.' },
            { n: 5, title: 'Set your take profits', desc: 'Place a TP1 order at the first target (typically 50% of your position), and TP2 for the remainder. Consider setting a trailing stop after TP1 is hit.' },
            { n: 6, title: 'Follow the bot\'s exit signal', desc: 'Check the Activity Feed for exit signals. If the bot shows a regime change or veto on the same symbol, consider closing early.' },
          ].map(({ n, title, desc }) => (
            <div key={n} style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
              <div style={{ width: 28, height: 28, borderRadius: '50%', background: C.brand, color: '#fff', fontSize: F.sm, fontWeight: 800, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>{n}</div>
              <div>
                <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 3 }}>{title}</div>
                <div style={{ fontSize: F.xs, color: C.textSub, lineHeight: 1.6 }}>{desc}</div>
              </div>
            </div>
          ))}
        </div>
      </AccordionCard>

      <AccordionCard title="Common Copy-Trading Mistakes" badge="Avoid These" badgeColor={C.bear}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {[
            { mistake: 'Chasing signals after they\'re old', fix: 'Only enter a signal if price is still within 0.5% of the stated entry. If price has moved significantly, the setup has changed.' },
            { mistake: 'Skipping the stop loss', fix: 'ALWAYS set your stop loss before entering. The stop is the only thing protecting you from a large loss. Never trade without one.' },
            { mistake: 'Oversizing positions', fix: 'The signal score says nothing about position size. Use the calculator. 1-2% risk per trade. 10× leverage on a 1% stop = 10% account at risk per trade.' },
            { mistake: 'Copying in PANIC regime', fix: 'During panic regimes, signals have much lower reliability. The bot reduces its own sizing in this mode. You should too — or sit on the sidelines.' },
            { mistake: 'Ignoring the LLM veto', fix: 'If the Activity Feed shows "AI VETO" on the same symbol you\'re about to copy, that\'s a warning. The Critic agent found a reason not to trade this setup.' },
            { mistake: 'Holding through TP2 hoping for more', fix: 'Respect the take-profit levels. They\'re calculated zones where the statistical edge weakens. Greed is how winning trades become losers.' },
          ].map(({ mistake, fix }) => (
            <div key={mistake} style={{ padding: '10px 14px', background: C.bear + '08', border: `1px solid ${C.bear}20`, borderRadius: R.md }}>
              <div style={{ fontSize: F.xs, fontWeight: 700, color: C.bear, marginBottom: 4 }}>✗ {mistake}</div>
              <div style={{ fontSize: F.xs, color: C.textSub, lineHeight: 1.5 }}>→ {fix}</div>
            </div>
          ))}
        </div>
      </AccordionCard>

      <AccordionCard title="Market Psychology: Why Most Traders Lose" badge="Mindset">
        <p>Even with a profitable system, traders lose because of psychology. Here&apos;s what to watch for:</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10, marginTop: 12 }}>
          {[
            { bias: 'FOMO', desc: 'Fear of Missing Out. Causes traders to enter too late, past the entry zone. Solution: set alerts, not market orders. If you missed it, the next signal is coming.' },
            { bias: 'Loss Aversion', desc: 'Holding losers too long hoping they\'ll recover, while cutting winners short. Solution: set TP and SL levels before entry and don\'t move them based on emotion.' },
            { bias: 'Overconfidence', desc: 'After 3 winning trades, traders increase size dramatically. The 4th trade then blows up the gains. Solution: fixed risk % per trade, always.' },
            { bias: 'Revenge Trading', desc: 'After a loss, jumping into the next trade immediately to "get it back." Usually results in a second, bigger loss. Solution: if you\'ve had 2 consecutive losses, take a break.' },
            { bias: 'Recency Bias', desc: 'Assuming recent market conditions will continue forever. "BTC has been going up all month" leads to oversized longs at tops. Solution: trust the regime classification, not your gut.' },
            { bias: 'Analysis Paralysis', desc: 'Waiting for the "perfect" signal while good setups pass. Solution: if a signal meets all criteria (score ≥ 75, regime confirmed, R:R ≥ 1.5), that\'s enough. Act.' },
          ].map(({ bias, desc }) => (
            <div key={bias} style={{ padding: '12px 14px', background: C.purple + '10', border: `1px solid ${C.purple}25`, borderRadius: R.md }}>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: C.purple, marginBottom: 4 }}>{bias}</div>
              <div style={{ fontSize: F.xs, color: C.textSub, lineHeight: 1.5 }}>{desc}</div>
            </div>
          ))}
        </div>
      </AccordionCard>

      {/* ─────────────────────────────────── */}
      <div style={{ height: 24 }} />
      <div id="glossary" />
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 12 }}>08 — Reference</div>
        <h2 style={{ margin: '0 0 8px', fontSize: F.xl, fontWeight: 700, color: C.text }}>Glossary</h2>
        <input
          type="text"
          placeholder="Search terms…"
          value={glossarySearch}
          onChange={(e) => setGlossarySearch(e.target.value)}
          style={{
            width: '100%',
            maxWidth: 400,
            padding: '8px 14px',
            background: C.card,
            border: `1px solid ${C.border}`,
            borderRadius: R.md,
            color: C.text,
            fontSize: F.sm,
            outline: 'none',
          }}
        />
      </div>

      <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, overflow: 'hidden' }}>
        {filteredGlossary.length === 0 ? (
          <div style={{ padding: 24, textAlign: 'center', color: C.muted, fontSize: F.sm }}>No terms matching "{glossarySearch}"</div>
        ) : (
          filteredGlossary.map((item, i) => (
            <div
              key={item.term}
              style={{
                padding: '14px 20px',
                borderBottom: i < filteredGlossary.length - 1 ? `1px solid ${C.border}` : 'none',
                display: 'flex',
                gap: 20,
                alignItems: 'flex-start',
              }}
            >
              <div style={{ fontSize: F.sm, fontWeight: 700, color: C.brand, minWidth: 200, flexShrink: 0 }}>{item.term}</div>
              <div style={{ fontSize: F.sm, color: C.textSub, lineHeight: 1.7 }}>{item.def}</div>
            </div>
          ))
        )}
      </div>

      {/* ── CTA ──────────────────────────────────────── */}
      <div
        style={{
          marginTop: 40,
          padding: '28px 32px',
          background: `linear-gradient(135deg, ${C.brand}18, ${C.card})`,
          border: `1px solid ${C.brand}40`,
          borderRadius: R.xl,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 20,
        }}
      >
        <div>
          <div style={{ fontSize: F.lg, fontWeight: 700, color: C.text, marginBottom: 4 }}>Ready to see it in action?</div>
          <div style={{ fontSize: F.sm, color: C.muted }}>View live signals, copy trades, or explore backtest results.</div>
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <Link href="/copy-trade" style={{ padding: '10px 20px', background: C.brand, color: '#fff', borderRadius: R.md, fontSize: F.sm, fontWeight: 700, textDecoration: 'none' }}>
            Copy Trade
          </Link>
          <Link href="/results" style={{ padding: '10px 20px', border: `1px solid ${C.brand}`, color: C.brand, borderRadius: R.md, fontSize: F.sm, fontWeight: 700, textDecoration: 'none' }}>
            See Results
          </Link>
        </div>
      </div>
    </div>
  );
}
