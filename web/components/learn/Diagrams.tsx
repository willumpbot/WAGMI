'use client';

import React from 'react';
import { motion } from 'framer-motion';
import { C, R, F, Glass, SP } from '../../src/theme';
import { fadeUp, staggerContainer } from '../../src/animations';

// ─── Agent Pipeline Diagram ──────────────────────────────────────────────────

export function AgentPipelineDiagram() {
  const agents = [
    { name: 'Regime', model: 'Haiku', color: C.info, desc: 'Market regime classification' },
    { name: 'Trade', model: 'Sonnet', color: C.brand, desc: 'Go / Skip / Flip decision' },
    { name: 'Risk', model: 'Haiku', color: C.warn, desc: 'Position sizing + risk flags' },
    { name: 'Critic', model: 'Sonnet', color: C.bear, desc: 'Stress-tests thesis, veto power' },
    { name: 'Learning', model: 'Haiku', color: C.bull, desc: 'Post-trade lessons (offline)' },
  ];

  return (
    <motion.div
      variants={staggerContainer}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ display: 'flex', alignItems: 'center', gap: 0, overflowX: 'auto', padding: '8px 0' }}
    >
      {agents.map((agent, i) => (
        <React.Fragment key={agent.name}>
          <motion.div
            variants={fadeUp}
            style={{
              ...Glass.card,
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
          </motion.div>
          {i < agents.length - 1 && (
            <div style={{ flexShrink: 0, padding: '0 4px', color: C.muted, fontSize: 16 }}>&rarr;</div>
          )}
        </React.Fragment>
      ))}
    </motion.div>
  );
}

// ─── Gate Flow Diagram ───────────────────────────────────────────────────────

export function GateFlowDiagram() {
  const gates = [
    { n: 1, label: 'Validity', desc: 'SL width >= 0.3%, proper direction', color: C.info },
    { n: 2, label: 'Circuit Breaker', desc: 'No daily loss limit breach', color: C.brand },
    { n: 3, label: 'Position Limits', desc: 'Max open positions not exceeded', color: C.warn },
    { n: 4, label: 'Leverage', desc: 'Calculated leverage within safe range', color: C.purple },
    { n: 5, label: 'Liquidation', desc: 'Liquidation price buffer adequate', color: C.bear },
    { n: 6, label: 'Sizing', desc: 'Position size within risk limits', color: C.bull },
  ];

  return (
    <motion.div
      variants={staggerContainer}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ display: 'flex', flexDirection: 'column', gap: 0 }}
    >
      {/* Signal in */}
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 4 }}>
        <div style={{ padding: '6px 20px', ...Glass.card, borderRadius: R.pill, fontSize: F.sm, fontWeight: 700, color: C.textSub }}>
          Signal Generated
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 4, color: C.muted }}>&darr;</div>

      {gates.map((gate, i) => (
        <React.Fragment key={gate.n}>
          <motion.div variants={fadeUp} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ width: 28, height: 28, borderRadius: '50%', background: gate.color, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: F.xs, fontWeight: 800, color: '#fff', flexShrink: 0 }}>
              {gate.n}
            </div>
            <div style={{ flex: 1, padding: '8px 12px', ...Glass.card, background: gate.color + '12', border: `1px solid ${gate.color}33`, borderRadius: R.sm }}>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: gate.color }}>{gate.label}</div>
              <div style={{ fontSize: F.xs, color: C.muted }}>{gate.desc}</div>
            </div>
            <div style={{ fontSize: F.xs, padding: '3px 8px', background: C.bull + '18', color: C.bull, borderRadius: R.pill, fontWeight: 700 }}>PASS</div>
          </motion.div>
          {i < gates.length - 1 && (
            <div style={{ display: 'flex', justifyContent: 'center', margin: '2px 0', color: C.muted }}>&darr;</div>
          )}
        </React.Fragment>
      ))}

      {/* Trade out */}
      <div style={{ display: 'flex', justifyContent: 'center', marginTop: 4, marginBottom: 4, color: C.muted }}>&darr;</div>
      <div style={{ display: 'flex', justifyContent: 'center' }}>
        <div style={{ padding: '8px 24px', background: C.bull + '22', border: `1px solid ${C.bull}44`, borderRadius: R.pill, fontSize: F.sm, fontWeight: 700, color: C.bull }}>
          Trade Executed
        </div>
      </div>
    </motion.div>
  );
}

// ─── Trading Flow Diagram ────────────────────────────────────────────────────

export function TradingFlowDiagram() {
  const W = 750, H = 180;
  const nodeW = 80, nodeH = 36;
  const arrowW = 24;
  const nodeCount = 8;

  const nodes: { label: string; sub?: string; color: string; bg: string }[] = [
    { label: 'Signal', sub: 'Detected', color: C.info, bg: C.info + '22' },
    { label: 'Gate 1', sub: 'Valid?', color: C.brand, bg: C.brand + '18' },
    { label: 'Gate 2', sub: 'Circuit?', color: C.brand, bg: C.brand + '18' },
    { label: 'Gate 3', sub: 'Pos. Limits?', color: C.brand, bg: C.brand + '18' },
    { label: 'Gate 4', sub: 'Leverage?', color: C.brand, bg: C.brand + '18' },
    { label: 'Gate 5', sub: 'Liq. Price?', color: C.brand, bg: C.brand + '18' },
    { label: 'Gate 6', sub: 'Sizing?', color: C.brand, bg: C.brand + '18' },
    { label: 'EXECUTE', sub: '\u2713', color: '#fff', bg: C.bull },
  ];

  const totalUsed = nodeCount * nodeW + 7 * arrowW;
  const padH = (W - totalUsed) / 2;
  const nodeY = 32;

  const xs: number[] = [];
  let cx = padH;
  for (let i = 0; i < nodeCount; i++) {
    xs.push(cx);
    cx += nodeW + arrowW;
  }

  const midY = nodeY + nodeH / 2;
  const rejectX = xs[1];
  const rejectY = nodeY + nodeH + 44;
  const rejectW = 72, rejectH = 32;

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ overflowX: 'auto', marginTop: 16, marginBottom: 8 }}
    >
      <svg width={W} height={H} style={{ display: 'block', minWidth: W }}>
        <defs>
          <marker id="arrowHead" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill={C.muted as string} />
          </marker>
          <marker id="arrowHeadRej" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
            <path d="M0,0 L6,3 L0,6 Z" fill={C.bear as string} />
          </marker>
        </defs>

        {/* Horizontal arrows between nodes */}
        {xs.slice(0, -1).map((x, i) => (
          <line
            key={i}
            x1={x + nodeW}
            y1={midY}
            x2={x + nodeW + arrowW}
            y2={midY}
            stroke={C.muted as string}
            strokeWidth={1.5}
            markerEnd="url(#arrowHead)"
          />
        ))}

        {/* REJECT branch */}
        <line
          x1={xs[1] + nodeW / 2}
          y1={nodeY + nodeH}
          x2={rejectX + rejectW / 2}
          y2={rejectY}
          stroke={C.bear as string}
          strokeWidth={1.5}
          strokeDasharray="4 3"
          markerEnd="url(#arrowHeadRej)"
        />

        {/* Node boxes */}
        {nodes.map((node, i) => (
          <g key={i}>
            <rect
              x={xs[i]}
              y={nodeY}
              width={nodeW}
              height={nodeH}
              rx={6}
              fill={node.bg}
              stroke={i === nodes.length - 1 ? C.bull : C.brand}
              strokeWidth={i === nodes.length - 1 ? 2 : 1}
            />
            <text
              x={xs[i] + nodeW / 2}
              y={nodeY + 14}
              textAnchor="middle"
              fontSize={9}
              fontWeight={700}
              fill={node.color}
            >
              {node.label}
            </text>
            {node.sub && (
              <text
                x={xs[i] + nodeW / 2}
                y={nodeY + 26}
                textAnchor="middle"
                fontSize={8}
                fill={i === nodes.length - 1 ? 'rgba(255,255,255,0.85)' : (C.muted as string)}
              >
                {node.sub}
              </text>
            )}
          </g>
        ))}

        {/* REJECT box */}
        <rect
          x={rejectX + (nodeW - rejectW) / 2}
          y={rejectY}
          width={rejectW}
          height={rejectH}
          rx={6}
          fill={C.bear + '22'}
          stroke={C.bear}
          strokeWidth={1.5}
        />
        <text
          x={rejectX + nodeW / 2}
          y={rejectY + 13}
          textAnchor="middle"
          fontSize={9}
          fontWeight={700}
          fill={C.bear as string}
        >
          REJECT
        </text>
        <text
          x={rejectX + nodeW / 2}
          y={rejectY + 24}
          textAnchor="middle"
          fontSize={8}
          fill={C.muted as string}
        >
          Logged + skipped
        </text>

        {/* "Any gate fails" label */}
        <text
          x={rejectX + nodeW / 2 + 44}
          y={nodeY + nodeH + 20}
          fontSize={8}
          fill={C.muted as string}
          fontStyle="italic"
        >
          any gate fails &rarr;
        </text>
      </svg>
      <div style={{ fontSize: 10, color: C.muted, marginTop: 4 }}>
        A signal must pass all 6 gates sequentially. Failure at any gate triggers rejection — the trade is logged but never executed.
      </div>
    </motion.div>
  );
}

// ─── Memory System Diagram ───────────────────────────────────────────────────

export function MemorySystemDiagram() {
  const W = 600, H = 170;
  const boxW = 190, boxH = 130;
  const leftX = 10, rightX = W - boxW - 10;
  const boxY = 20;
  const brainX = W / 2, brainY = boxY + boxH / 2;
  const leftEdge = leftX + boxW;
  const rightEdge = rightX;
  const arrowGap = 18;

  const shortNotes = [
    '\u2022 RSI was 71 at 14:30',
    '\u2022 BTC rejected $65k twice',
    '\u2022 Regime shifted to range',
    '\u2022 Trade skipped: low ATR',
  ];
  const longPatterns = [
    '\u2022 BTC breakout \u2192 +4.2% avg',
    '\u2022 High-vol: skip \u2192 +EV',
    '\u2022 Range + RSI<35 = long edge',
    '\u2022 After panic: wait 2h',
  ];

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ marginTop: 20, marginBottom: 8 }}
    >
      <div style={{ fontSize: 11, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 10 }}>
        Memory Architecture — How the Bot Remembers
      </div>
      <div style={{ overflowX: 'auto' }}>
        <svg width={W} height={H} style={{ display: 'block', minWidth: W }}>
          {/* Short-term box */}
          <rect x={leftX} y={boxY} width={boxW} height={boxH} rx={8} fill={C.info + '12'} stroke={C.info + '55'} strokeWidth={1.5} />
          <text x={leftX + boxW / 2} y={boxY + 18} textAnchor="middle" fontSize={11} fontWeight={800} fill={C.info as string}>
            Short-Term Memory
          </text>
          <text x={leftX + boxW / 2} y={boxY + 30} textAnchor="middle" fontSize={9} fill={C.infoMid as string}>
            7-day TTL &middot; 100 notes max
          </text>
          {shortNotes.map((note, i) => (
            <text key={i} x={leftX + 10} y={boxY + 50 + i * 17} fontSize={9} fill={C.textSub as string}>
              {note}
            </text>
          ))}

          {/* Long-term box */}
          <rect x={rightX} y={boxY} width={boxW} height={boxH} rx={8} fill={C.purple + '12'} stroke={C.purple + '55'} strokeWidth={1.5} />
          <text x={rightX + boxW / 2} y={boxY + 18} textAnchor="middle" fontSize={11} fontWeight={800} fill={C.purple as string}>
            Long-Term Memory
          </text>
          <text x={rightX + boxW / 2} y={boxY + 30} textAnchor="middle" fontSize={9} fill={C.purpleLight as string + '99'}>
            Trade DNA &middot; Patterns &middot; Rules
          </text>
          {longPatterns.map((note, i) => (
            <text key={i} x={rightX + 10} y={boxY + 50 + i * 17} fontSize={9} fill={C.textSub as string}>
              {note}
            </text>
          ))}

          {/* Brain icon (center) */}
          <circle cx={brainX} cy={brainY} r={26} fill={C.brand + '22'} stroke={C.brand + '66'} strokeWidth={2} />
          <text x={brainX} y={brainY + 16} textAnchor="middle" fontSize={8} fontWeight={700} fill={C.brand as string}>AI Brain</text>

          {/* Arrows */}
          <line x1={leftEdge} y1={brainY - arrowGap / 2} x2={brainX - 28} y2={brainY - arrowGap / 2} stroke={C.info as string} strokeWidth={1.5} markerEnd="url(#arrowInfo)" />
          <line x1={brainX - 28} y1={brainY + arrowGap / 2} x2={leftEdge} y2={brainY + arrowGap / 2} stroke={C.info as string} strokeWidth={1.5} markerEnd="url(#arrowInfoBack)" />
          <line x1={brainX + 28} y1={brainY - arrowGap / 2} x2={rightEdge} y2={brainY - arrowGap / 2} stroke={C.purple as string} strokeWidth={1.5} markerEnd="url(#arrowPurple)" />
          <line x1={rightEdge} y1={brainY + arrowGap / 2} x2={brainX + 28} y2={brainY + arrowGap / 2} stroke={C.purple as string} strokeWidth={1.5} markerEnd="url(#arrowPurpleBack)" />

          <defs>
            <marker id="arrowInfo" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill={C.info as string} />
            </marker>
            <marker id="arrowInfoBack" markerWidth="6" markerHeight="6" refX="1" refY="3" orient="auto">
              <path d="M6,0 L0,3 L6,6 Z" fill={C.info as string} />
            </marker>
            <marker id="arrowPurple" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
              <path d="M0,0 L6,3 L0,6 Z" fill={C.purple as string} />
            </marker>
            <marker id="arrowPurpleBack" markerWidth="6" markerHeight="6" refX="1" refY="3" orient="auto">
              <path d="M6,0 L0,3 L6,6 Z" fill={C.purple as string} />
            </marker>
          </defs>
        </svg>
      </div>
      <div style={{ fontSize: 10, color: C.muted, marginTop: 4 }}>
        The AI brain reads from both memory stores each cycle and writes new observations after each decision. Long-term patterns graduate from short-term notes via the Learning Agent.
      </div>
    </motion.div>
  );
}

// ─── Strategy Voting Visual ──────────────────────────────────────────────────

export function StrategyVotingVisual() {
  const strategies = [
    { abbr: 'RGM', name: 'Regime Trend', vote: 'BUY' as const },
    { abbr: 'MCZ', name: 'Monte Carlo Zones', vote: 'BUY' as const },
    { abbr: 'CSC', name: 'Confidence Scorer', vote: 'BUY' as const },
    { abbr: 'MTF', name: 'Multi-TF Quality', vote: 'SKIP' as const },
  ];

  const voteColor: Record<string, string> = {
    BUY: C.bull,
    SKIP: C.muted,
    SELL: C.bear,
  };
  const voteBg: Record<string, string> = {
    BUY: C.bull + '22',
    SKIP: C.surfaceHover,
    SELL: C.bear + '22',
  };

  const cols = ['BUY', 'SKIP', 'SELL'];

  return (
    <motion.div
      variants={fadeUp}
      initial="hidden"
      whileInView="show"
      viewport={{ once: true }}
      style={{ marginTop: 20, marginBottom: 8 }}
    >
      <div style={{ fontSize: 11, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 10 }}>
        Weighted-Veto Ensemble — Sample Vote
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', fontSize: 12, minWidth: 360 }}>
          <thead>
            <tr>
              <th style={{ padding: '6px 12px', textAlign: 'left', fontSize: 11, color: C.muted, fontWeight: 600, borderBottom: `1px solid ${C.border}` }}>
                Strategy
              </th>
              {cols.map(col => (
                <th key={col} style={{ padding: '6px 16px', textAlign: 'center', fontSize: 11, color: col === 'BUY' ? C.bull : col === 'SELL' ? C.bear : C.muted, fontWeight: 700, borderBottom: `1px solid ${C.border}` }}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {strategies.map((s, si) => (
              <tr key={s.abbr} style={{ background: si % 2 ? C.surfaceHover + '40' : 'transparent' }}>
                <td style={{ padding: '8px 12px', borderBottom: `1px solid ${C.border}` }}>
                  <span style={{ fontSize: 11, fontWeight: 800, color: C.text }}>{s.abbr}</span>
                  <span style={{ fontSize: 10, color: C.muted, marginLeft: 6 }}>{s.name}</span>
                </td>
                {cols.map(col => (
                  <td key={col} style={{ padding: '8px 16px', textAlign: 'center', borderBottom: `1px solid ${C.border}` }}>
                    {(s.vote as string) === col ? (
                      <span style={{
                        display: 'inline-block',
                        padding: '2px 10px',
                        borderRadius: R.pill,
                        background: voteBg[col],
                        color: voteColor[col],
                        fontSize: 11,
                        fontWeight: 800,
                        border: `1px solid ${voteColor[col]}44`,
                      }}>
                        {col === 'BUY' ? '\u25B2' : col === 'SELL' ? '\u25BC' : '\u2014'} {col}
                      </span>
                    ) : (
                      <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: C.faint }} />
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Tally + result */}
      <div style={{ marginTop: 12, display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 6 }}>
          {[
            { label: '3 BUY', color: C.bull },
            { label: '0 SELL', color: C.bear },
            { label: '1 SKIP', color: C.muted },
          ].map(({ label, color }) => (
            <span key={label} style={{ fontSize: 11, fontWeight: 700, padding: '3px 10px', borderRadius: R.pill, background: color + '18', color, border: `1px solid ${color}33` }}>
              {label}
            </span>
          ))}
        </div>
        <span style={{ color: C.muted, fontSize: 12 }}>&rarr;</span>
        <span style={{ fontSize: 11, fontWeight: 700, padding: '3px 12px', borderRadius: R.pill, background: C.brand + '18', color: C.brand, border: `1px solid ${C.brand}44` }}>
          Signal PASSES minimum votes
        </span>
        <span style={{ color: C.muted, fontSize: 12 }}>&rarr;</span>
        <span style={{ fontSize: 11, fontWeight: 700, padding: '3px 12px', borderRadius: R.pill, background: C.info + '18', color: C.info, border: `1px solid ${C.info}44` }}>
          AI review
        </span>
        <span style={{ color: C.muted, fontSize: 12 }}>&rarr;</span>
        <span style={{ fontSize: 11, fontWeight: 800, padding: '3px 12px', borderRadius: R.pill, background: C.bull + '22', color: C.bull, border: `1px solid ${C.bull}55` }}>
          EXECUTE
        </span>
      </div>
      <div style={{ marginTop: 8, fontSize: 10, color: C.muted, lineHeight: 1.6 }}>
        Weighted-Veto mode: each strategy votes independently. Minimum 2 agreements required. No SELL votes = no veto triggered. Signal advances to the LLM pipeline for final review.
      </div>
    </motion.div>
  );
}

export default {
  AgentPipelineDiagram,
  GateFlowDiagram,
  TradingFlowDiagram,
  MemorySystemDiagram,
  StrategyVotingVisual,
};
