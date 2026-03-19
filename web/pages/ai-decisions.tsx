/**
 * /ai-decisions — The Decision Theater
 *
 * The flagship differentiator: real-time transparent AI reasoning stream.
 * Shows every LLM decision with the full agent chain, veto analysis,
 * and Critic accuracy grading. No competitor shows this.
 */
import React, { useEffect, useState, useMemo, useRef } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import Layout from '../components/Layout';
import { C, R, S, F, timeAgo } from '../src/theme';
import { apiFetch } from '../src/api';
import type { LlmDecision, LlmFeedResponse } from '../src/types';

// ─── Helpers ──────────────────────────────────────────────────────────────────

function actionColor(d: LlmDecision): string {
  if (d.is_veto) return C.purple;
  if (!d.allowed) return C.bear;
  const a = d.action?.toLowerCase();
  if (a === 'proceed' || a === 'go') return C.bull;
  if (a === 'flat' || a === 'skip') return C.muted;
  if (a === 'flip') return C.warn;
  return C.muted;
}

function actionLabel(d: LlmDecision): string {
  if (d.is_veto) return 'VETOED';
  if (!d.allowed) return 'BLOCKED';
  const a = d.action?.toLowerCase();
  if (a === 'proceed' || a === 'go') return 'GO';
  if (a === 'flat' || a === 'skip') return 'SKIP';
  if (a === 'flip') return 'FLIP';
  return d.action?.toUpperCase() || '?';
}

function modelBadge(model: string): { label: string; color: string } {
  const m = (model || '').toLowerCase();
  if (m.includes('opus')) return { label: 'Opus', color: '#a78bfa' };
  if (m.includes('sonnet')) return { label: 'Sonnet', color: C.brand };
  if (m.includes('haiku')) return { label: 'Haiku', color: C.info };
  return { label: model || '—', color: C.muted };
}

function confBar(conf: number, color: string) {
  const pct = Math.round(conf * 100);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width: 60, height: 4, background: C.border, borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontSize: F.xs, fontWeight: 700, color, minWidth: 30 }}>{pct}%</span>
    </div>
  );
}

// ─── Agent Pipeline Flow Visualization ───────────────────────────────────────

function AgentPipelineFlow({ decision }: { decision: LlmDecision | null }) {
  const notes = decision?.notes ?? '';
  const notesLower = notes.toLowerCase();

  const hasRegime = notesLower.includes('regime');
  const hasTrade = notesLower.includes('trade agent') || notesLower.includes('trade:');
  const hasRisk = notesLower.includes('risk agent') || notesLower.includes('risk:');
  const hasCritic = notesLower.includes('critic');
  const isVeto = decision?.is_veto ?? false;
  const hasDecision = decision != null;

  // Try to parse a confidence value for a given keyword prefix (e.g. "REGIME: ... confidence: 0.72")
  function parseScore(keyword: string): string | null {
    if (!notes) return null;
    const idx = notesLower.indexOf(keyword);
    if (idx === -1) return null;
    const slice = notes.slice(idx, idx + 200);
    const m = slice.match(/conf(?:idence)?[\s:=]+(\d+\.?\d*)/i);
    if (m) {
      const v = parseFloat(m[1]);
      return v <= 1 ? `${Math.round(v * 100)}%` : `${Math.round(v)}%`;
    }
    return null;
  }

  const regimeScore = parseScore('regime');
  const tradeScore = parseScore('trade agent') || parseScore('trade:');
  const riskScore = parseScore('risk agent') || parseScore('risk:');
  const criticScore = parseScore('critic');

  const NODES = [
    { key: 'regime', label: 'Regime', active: hasRegime, color: C.info, score: regimeScore },
    { key: 'trade', label: 'Trade', active: hasTrade, color: C.brand, score: tradeScore },
    { key: 'risk', label: 'Risk', active: hasRisk, color: C.warn, score: riskScore },
    { key: 'critic', label: 'Critic', active: hasCritic, color: '#7c3aed', score: criticScore },
    {
      key: 'decision',
      label: isVeto ? 'VETO' : 'GO',
      active: hasDecision,
      color: isVeto ? C.bear : C.bull,
      score: decision ? `${Math.round((decision.confidence ?? 0) * 100)}%` : null,
    },
  ];

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '18px 24px',
      marginBottom: 24,
    }}>
      <div style={{ fontSize: F.xs, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 16 }}>
        Live Agent Pipeline
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0, overflowX: 'auto', paddingBottom: 4 }}>
        {NODES.map((node, i) => (
          <React.Fragment key={node.key}>
            {/* Node */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6, flexShrink: 0 }}>
              <div style={{
                width: 52, height: 52, borderRadius: '50%',
                background: node.active ? node.color + '20' : C.surface,
                border: `2px solid ${node.active ? node.color : C.border}`,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                opacity: node.active ? 1 : 0.3,
                boxShadow: node.active ? `0 0 12px ${node.color}50` : 'none',
                transition: 'all 0.3s ease',
                position: 'relative',
              }}>
                <span style={{ fontSize: 9, fontWeight: 800, color: node.active ? node.color : C.muted, textAlign: 'center', lineHeight: 1.2, padding: '0 4px' }}>
                  {node.label}
                </span>
              </div>
              {/* Score / confidence below node */}
              <div style={{ fontSize: 9, fontWeight: 700, color: node.active && node.score ? node.color : C.faint, minHeight: 13 }}>
                {node.active && node.score ? node.score : node.active ? '✓' : '—'}
              </div>
            </div>

            {/* Connector arrow between nodes */}
            {i < NODES.length - 1 && (
              <div style={{ position: 'relative', width: 48, height: 4, flexShrink: 0, marginBottom: 13 }}>
                {/* Dashed track */}
                <div style={{
                  position: 'absolute', top: 0, left: 0, right: 0, height: '100%',
                  borderTop: `2px dashed ${C.border}`,
                }}/>
                {/* Filled portion when active */}
                {NODES[i].active && (
                  <div style={{
                    position: 'absolute', top: 0, left: 0, height: '100%',
                    width: NODES[i + 1].active ? '100%' : '50%',
                    borderTop: `2px solid ${NODES[i].color}`,
                    transition: 'width 0.4s ease',
                  }}/>
                )}
                {/* Traveling dot */}
                {NODES[i].active && !NODES[i + 1].active && (
                  <div style={{
                    position: 'absolute', top: -3, left: 0,
                    width: 8, height: 8, borderRadius: '50%',
                    background: NODES[i].color,
                    animation: 'pipelineDot 1.4s ease-in-out infinite',
                    boxShadow: `0 0 6px ${NODES[i].color}`,
                  }}/>
                )}
                {/* Arrow tip */}
                <div style={{
                  position: 'absolute', right: -1, top: -4,
                  borderTop: '5px solid transparent',
                  borderBottom: '5px solid transparent',
                  borderLeft: `5px solid ${NODES[i].active ? NODES[i].color : C.border}`,
                }}/>
              </div>
            )}
          </React.Fragment>
        ))}
      </div>

      {/* Status text */}
      {decision && (
        <div style={{ textAlign: 'center', marginTop: 8, fontSize: F.xs, color: C.muted }}>
          {decision.symbol && <span style={{ fontWeight: 700, color: C.textSub }}>{decision.symbol}</span>}
          {decision.regime && <span> · {decision.regime.replace('_', ' ')}</span>}
          {decision.trigger && <span> · {decision.trigger.replace('_', ' ')}</span>}
        </div>
      )}
      {!decision && (
        <div style={{ textAlign: 'center', marginTop: 8, fontSize: F.xs, color: C.faint }}>
          Waiting for first decision…
        </div>
      )}
    </div>
  );
}

// ─── Veto Reason Word Cloud ───────────────────────────────────────────────────

const STOP_WORDS = new Set(['the', 'a', 'and', 'is', 'to', 'of', 'in', 'for', 'with', 'at', 'on', 'not', 'has', 'this', 'that', 'be', 'are', 'was', 'it']);
const RISK_KEYWORDS = new Set(['risk', 'loss', 'stop', 'drawdown', 'position', 'exposure', 'volatile', 'spike', 'circuit']);
const REGIME_KEYWORDS = new Set(['regime', 'trend', 'panic', 'range', 'volatility', 'shift', 'market', 'bearish', 'bullish']);

function VetoReasonWordCloud({ decisions }: { decisions: LlmDecision[] }) {
  const tags = useMemo(() => {
    const freq: Record<string, number> = {};
    for (const d of decisions) {
      const text = ((d.notes || '') + ' ' + (d.gate_reason || '')).toLowerCase();
      const words = text.split(/\W+/).filter((w) => w.length > 3 && !STOP_WORDS.has(w));
      for (const w of words) {
        freq[w] = (freq[w] || 0) + 1;
      }
    }
    return Object.entries(freq)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20);
  }, [decisions]);

  if (tags.length === 0) return null;

  const maxCount = tags[0][1];
  const minCount = tags[tags.length - 1][1];
  const range = Math.max(1, maxCount - minCount);

  function tagColor(word: string): string {
    if (RISK_KEYWORDS.has(word)) return C.bear;
    if (REGIME_KEYWORDS.has(word)) return C.warn;
    return C.muted;
  }

  function tagSize(count: number): number {
    return 11 + Math.round(((count - minCount) / range) * 7);
  }

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.purple}30`,
      borderRadius: R.lg,
      padding: '16px 18px',
      marginTop: 16,
    }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 14 }}>☁</span> Veto Reason Keywords
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {tags.map(([word, count]) => {
          const col = tagColor(word);
          const size = tagSize(count);
          return (
            <span key={word} style={{
              fontSize: size,
              fontWeight: count === maxCount ? 700 : 500,
              color: col,
              background: col + '14',
              border: `1px solid ${col}25`,
              borderRadius: R.pill,
              padding: '2px 8px',
              lineHeight: 1.4,
              cursor: 'default',
            }} title={`${count} occurrence${count !== 1 ? 's' : ''}`}>
              {word}
            </span>
          );
        })}
      </div>
      <div style={{ marginTop: 10, fontSize: F.xs, color: C.muted }}>
        Extracted from {decisions.length} veto decision{decisions.length !== 1 ? 's' : ''}. Size = frequency.{' '}
        <span style={{ color: C.bear }}>Red</span> = risk-related, <span style={{ color: C.warn }}>amber</span> = regime-related.
      </div>
    </div>
  );
}

// ─── Agent Pipeline "thinking" steps parsed from notes ───────────────────────

/**
 * Try to extract structured agent steps from the notes field.
 * The notes contain Claude's raw reasoning — we display it cleanly.
 */
function parseAgentSteps(notes: string): { agent: string; text: string; color: string }[] {
  if (!notes) return [];
  // Detect common thought protocol markers
  const lines = notes.split('\n').filter(Boolean);
  const steps: { agent: string; text: string; color: string }[] = [];
  let current: { agent: string; lines: string[]; color: string } | null = null;

  const MARKERS: [string, string, string][] = [
    ['OBSERVE', 'Observe', C.info],
    ['RECALL', 'Recall', C.brand],
    ['REASON', 'Reason', C.warn],
    ['DECIDE', 'Decide', C.bull],
    ['JUSTIFY', 'Justify', C.muted],
    ['REGIME', 'Regime', C.info],
    ['TRADE', 'Trade Agent', C.brand],
    ['RISK', 'Risk Agent', C.warn],
    ['CRITIC', 'Critic', C.purple],
    ['VETO', 'Veto', C.bear],
    ['APPROVE', 'Approved', C.bull],
  ];

  for (const line of lines) {
    const up = line.toUpperCase();
    let matched = false;
    for (const [key, label, color] of MARKERS) {
      if (up.startsWith(key) || up.includes(`: ${key}`) || up.includes(`[${key}]`)) {
        if (current) steps.push({ agent: current.agent, text: current.lines.join(' '), color: current.color });
        current = { agent: label, lines: [line.replace(/^[A-Z\s:\[\]]+:/i, '').trim()], color };
        matched = true;
        break;
      }
    }
    if (!matched && current) current.lines.push(line);
  }
  if (current) steps.push({ agent: current.agent, text: current.lines.join(' '), color: current.color });

  // If no markers found, return the whole text as a single "Reasoning" block
  if (!steps.length && notes.trim()) {
    return [{ agent: 'AI Reasoning', text: notes.slice(0, 600) + (notes.length > 600 ? '…' : ''), color: C.brand }];
  }
  return steps.slice(0, 8); // cap for display
}

// ─── Decision Card ────────────────────────────────────────────────────────────

function DecisionCard({ d, isNew }: { d: LlmDecision; isNew?: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const aCol = actionColor(d);
  const aLabel = actionLabel(d);
  const mb = modelBadge(d.model);
  const conf = d.confidence ?? 0;
  const steps = useMemo(() => parseAgentSteps(d.notes), [d.notes]);

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${d.is_veto ? C.purple + '50' : !d.allowed ? C.bear + '40' : C.border}`,
      borderLeft: `3px solid ${aCol}`,
      borderRadius: R.lg,
      marginBottom: 10,
      overflow: 'hidden',
      animation: isNew ? 'fadeInDown 0.3s ease' : 'none',
      boxShadow: d.is_veto ? `0 0 12px ${C.purple}20` : 'none',
    }}>
      {/* ── Header row ── */}
      <div
        onClick={() => setExpanded((v) => !v)}
        style={{
          padding: '12px 16px', cursor: 'pointer',
          display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
        }}
      >
        {/* Action badge */}
        <span style={{
          padding: '2px 9px', borderRadius: R.pill,
          background: aCol + '18', color: aCol,
          fontSize: 10, fontWeight: 800, letterSpacing: '0.06em', flexShrink: 0,
        }}>{aLabel}</span>

        {/* Symbol */}
        <span style={{ fontWeight: 800, color: C.text, fontSize: F.sm }}>{d.symbol || '—'}</span>

        {/* Confidence */}
        {confBar(conf, aCol)}

        {/* Model */}
        <span style={{
          fontSize: F.xs, padding: '1px 7px', borderRadius: R.pill,
          background: mb.color + '18', color: mb.color, fontWeight: 600, flexShrink: 0,
        }}>{mb.label}</span>

        {/* Regime */}
        {d.regime && (
          <span style={{ fontSize: F.xs, color: C.muted, flexShrink: 0 }}>
            {d.regime.replace('_', ' ')}
          </span>
        )}

        {/* Trigger */}
        {d.trigger && (
          <span style={{ fontSize: F.xs, color: C.faint, flexShrink: 0 }}>
            {d.trigger.replace('_', ' ')}
          </span>
        )}

        {/* Time */}
        <span style={{ marginLeft: 'auto', fontSize: F.xs, color: C.muted, flexShrink: 0 }}>
          {timeAgo(d.ts_iso || d.ts)}
        </span>

        {/* Expand chevron */}
        <span style={{ color: C.muted, fontSize: F.sm, transition: 'transform 0.15s', display: 'inline-block', transform: expanded ? 'rotate(180deg)' : 'none', flexShrink: 0 }}>▾</span>
      </div>

      {/* ── Expanded reasoning ── */}
      {expanded && (
        <div style={{ borderTop: `1px solid ${C.border}`, padding: '14px 16px', background: C.surface }}>
          {/* Veto / gate reason */}
          {(d.is_veto || !d.allowed) && d.gate_reason && (
            <div style={{
              marginBottom: 14, padding: '10px 14px',
              background: (!d.allowed ? C.bear : C.purple) + '10',
              border: `1px solid ${(!d.allowed ? C.bear : C.purple)}30`,
              borderRadius: R.sm,
              fontSize: F.sm, color: !d.allowed ? C.bearMid : '#c084fc',
            }}>
              <strong>{d.is_veto ? '🚫 Veto reason' : '⛔ Blocked by gate'}:</strong> {d.gate_reason}
            </div>
          )}

          {/* Agent reasoning steps */}
          {steps.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {steps.map((s, i) => (
                <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                  <div style={{
                    flexShrink: 0, width: 80, fontSize: F.xs, fontWeight: 700,
                    color: s.color, padding: '2px 0', textAlign: 'right',
                  }}>{s.agent}</div>
                  <div style={{ width: 1, background: s.color + '40', flexShrink: 0, alignSelf: 'stretch', minHeight: 20 }} />
                  <div style={{ flex: 1, fontSize: F.xs, color: C.textSub, lineHeight: 1.6 }}>{s.text}</div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: F.xs, color: C.textSub, lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>
              {d.notes || 'No reasoning logged.'}
            </div>
          )}

          {/* Metadata footer */}
          <div style={{ marginTop: 12, paddingTop: 10, borderTop: `1px solid ${C.border}`, display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: F.xs, color: C.muted }}>
            {d.ts_iso && <span>Logged: {new Date(d.ts_iso).toLocaleString()}</span>}
            {d.mode && <span>Mode: {d.mode}</span>}
            {d.size_multiplier != null && <span>Size multiplier: {d.size_multiplier}×</span>}
            {d.trigger_context && <span>Context: {d.trigger_context.slice(0, 80)}</span>}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Veto Analysis Panel ──────────────────────────────────────────────────────

function VetoPanel({ decisions }: { decisions: LlmDecision[] }) {
  const vetoed = decisions.filter((d) => d.is_veto);
  const total = decisions.length;
  const vetoRate = total > 0 ? (vetoed.length / total) * 100 : 0;

  // Group by gate_reason
  const byReason: Record<string, number> = {};
  for (const d of vetoed) {
    const r = d.gate_reason || 'unspecified';
    byReason[r] = (byReason[r] || 0) + 1;
  }
  const reasonEntries = Object.entries(byReason).sort((a, b) => b[1] - a[1]);
  const maxReasonCount = Math.max(1, ...reasonEntries.map((e) => e[1]));

  return (
    <div style={{ background: C.card, border: `1px solid ${C.purple}30`, borderRadius: R.lg, padding: '18px 20px' }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 14, display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ fontSize: 16 }}>🚫</span> Critic Veto Analysis
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 14 }}>
        <div style={{ background: C.surface, borderRadius: R.sm, padding: '10px 12px' }}>
          <div style={{ fontSize: F.xs, color: C.muted }}>Total vetoed</div>
          <div style={{ fontSize: F.xl, fontWeight: 700, color: C.purple }}>{vetoed.length}</div>
        </div>
        <div style={{ background: C.surface, borderRadius: R.sm, padding: '10px 12px' }}>
          <div style={{ fontSize: F.xs, color: C.muted }}>Veto rate</div>
          <div style={{ fontSize: F.xl, fontWeight: 700, color: C.purple }}>{vetoRate.toFixed(1)}%</div>
        </div>
      </div>
      {reasonEntries.length > 0 && (
        <div>
          <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 8 }}>Top veto reasons</div>
          {reasonEntries.slice(0, 5).map(([reason, count]) => (
            <div key={reason} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <div style={{ flex: 1, fontSize: F.xs, color: C.textSub, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{reason}</div>
              <div style={{ width: 80, height: 4, background: C.surface, borderRadius: 2, overflow: 'hidden' }}>
                <div style={{ width: `${(count / maxReasonCount) * 100}%`, height: '100%', background: C.purple, borderRadius: 2 }} />
              </div>
              <div style={{ width: 20, fontSize: F.xs, color: C.purple, textAlign: 'right' }}>{count}</div>
            </div>
          ))}
        </div>
      )}
      <div style={{ marginTop: 12, fontSize: F.xs, color: C.muted, lineHeight: 1.5 }}>
        The Critic Agent must provide a counter-thesis to exercise a veto — vague objections are rejected. This prevents over-conservative filtering.
      </div>
    </div>
  );
}

// ─── Model Routing Panel ──────────────────────────────────────────────────────

function ModelPanel({ decisions }: { decisions: LlmDecision[] }) {
  const counts: Record<string, number> = {};
  for (const d of decisions) {
    const mb = modelBadge(d.model);
    counts[mb.label] = (counts[mb.label] || 0) + 1;
  }
  const total = decisions.length || 1;
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);

  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '18px 20px' }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 14 }}>Model Routing</div>
      {entries.map(([model, count]) => {
        const mb = modelBadge(model);
        return (
          <div key={model} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <span style={{ width: 52, fontSize: F.xs, fontWeight: 700, color: mb.color }}>{model}</span>
            <div style={{ flex: 1, height: 6, background: C.surface, borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ width: `${(count / total) * 100}%`, height: '100%', background: mb.color, borderRadius: 3 }} />
            </div>
            <span style={{ width: 26, fontSize: F.xs, color: C.muted, textAlign: 'right' }}>{count}</span>
          </div>
        );
      })}
      <div style={{ marginTop: 10, fontSize: F.xs, color: C.muted, lineHeight: 1.5 }}>
        Haiku handles regime + risk (fast, cheap). Sonnet handles trade thesis + critique (high-accuracy). Total cost: ~$0.007/decision.
      </div>
    </div>
  );
}

// ─── Confidence Trend Sparkline ───────────────────────────────────────────────

function ConfidenceTrendSparkline({ decisions }: { decisions: LlmDecision[] }) {
  if (decisions.length < 5) return null;
  const last30 = [...decisions].sort((a, b) => a.ts - b.ts).slice(-30);
  const W = 240, H = 60;
  const vals = last30.map((d) => (d.confidence ?? 0) * 100);
  const min = Math.min(...vals);
  const max = Math.max(...vals) || 1;
  const range = max - min || 1;
  const x = (i: number) => (i / (vals.length - 1)) * W;
  const y = (v: number) => H - 4 - ((v - min) / range) * (H - 8);
  const pts = vals.map((v, i) => `${x(i)},${y(v)}`).join(' ');
  const areaPath = [`0,${H}`, ...vals.map((v, i) => `${x(i)},${y(v)}`), `${W},${H}`].join(' ');
  const avgConf = vals.reduce((a, b) => a + b, 0) / vals.length;
  const avgY = y(avgConf);
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '14px 16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Confidence Trend</span>
        <span style={{ fontSize: F.xs, fontWeight: 700, color: avgConf >= 65 ? C.bull : avgConf >= 45 ? C.warn : C.bear }}>
          avg {Math.round(avgConf)}%
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block', overflow: 'visible' }}>
        <defs>
          <linearGradient id="confGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.brand} stopOpacity="0.3" />
            <stop offset="100%" stopColor={C.brand} stopOpacity="0.02" />
          </linearGradient>
        </defs>
        {/* 65% threshold line */}
        {(() => {
          const threshY = y(65);
          return (
            <line x1={0} y1={threshY} x2={W} y2={threshY} stroke={C.bull} strokeWidth={0.8} strokeDasharray="3 4" opacity={0.5} />
          );
        })()}
        {/* Area fill */}
        <polygon points={areaPath} fill="url(#confGrad)" />
        {/* Line */}
        <polyline points={pts} fill="none" stroke={C.brand} strokeWidth={1.5} strokeLinejoin="round" />
        {/* End dot */}
        <circle cx={x(vals.length - 1)} cy={y(vals[vals.length - 1])} r={3} fill={C.brand} />
        {/* Labels */}
        <text x={2} y={H - 2} fontSize={8} fill={C.muted}>older</text>
        <text x={W - 2} y={H - 2} fontSize={8} fill={C.muted} textAnchor="end">now</text>
        <text x={W + 2} y={avgY + 3} fontSize={8} fill={C.bull} textAnchor="start">65%</text>
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 10, color: C.muted }}>
        <span>min: {Math.round(min)}%</span>
        <span>{last30.length} decisions</span>
        <span>max: {Math.round(max)}%</span>
      </div>
    </div>
  );
}

// ─── Decision Mix Donut ───────────────────────────────────────────────────────

function DecisionMixDonut({ decisions }: { decisions: LlmDecision[] }) {
  if (!decisions.length) return null;
  const goes = decisions.filter((d) => (d.action === 'proceed' || d.action === 'go') && d.allowed && !d.is_veto).length;
  const vetoes = decisions.filter((d) => d.is_veto).length;
  const blocked = decisions.filter((d) => !d.allowed && !d.is_veto).length;
  const flips = decisions.filter((d) => d.action === 'flip').length;
  const skips = decisions.length - goes - vetoes - blocked - flips;

  const segments = [
    { label: 'GO', count: goes, color: C.bull },
    { label: 'SKIP', count: Math.max(skips, 0), color: C.muted },
    { label: 'VETO', count: vetoes, color: C.purple },
    { label: 'BLOCKED', count: blocked, color: C.bear },
    { label: 'FLIP', count: flips, color: C.warn },
  ].filter((s) => s.count > 0);

  const total = segments.reduce((a, s) => a + s.count, 0) || 1;
  const CX = 60, CY = 60, R_out = 52, R_in = 34;

  const arcPath = (startPct: number, endPct: number) => {
    const a1 = (startPct * 360 - 90) * (Math.PI / 180);
    const a2 = (endPct * 360 - 90) * (Math.PI / 180);
    const large = (endPct - startPct) * 360 > 180 ? 1 : 0;
    const x1 = CX + R_out * Math.cos(a1), y1 = CY + R_out * Math.sin(a1);
    const x2 = CX + R_out * Math.cos(a2), y2 = CY + R_out * Math.sin(a2);
    const x3 = CX + R_in * Math.cos(a2), y3 = CY + R_in * Math.sin(a2);
    const x4 = CX + R_in * Math.cos(a1), y4 = CY + R_in * Math.sin(a1);
    return `M ${x1} ${y1} A ${R_out} ${R_out} 0 ${large} 1 ${x2} ${y2} L ${x3} ${y3} A ${R_in} ${R_in} 0 ${large} 0 ${x4} ${y4} Z`;
  };

  let cumulative = 0;
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '14px 16px' }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 10 }}>Decision Mix</div>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <svg width={120} height={120} viewBox="0 0 120 120" style={{ flexShrink: 0 }}>
          {segments.map((seg) => {
            const startPct = cumulative / total;
            const endPct = (cumulative + seg.count) / total;
            cumulative += seg.count;
            const d = arcPath(startPct, endPct);
            return <path key={seg.label} d={d} fill={seg.color} opacity={0.85} stroke={C.bg} strokeWidth={1} />;
          })}
          <text x={CX} y={CY - 5} textAnchor="middle" fontSize={14} fontWeight="800" fill={C.text}>{total}</text>
          <text x={CX} y={CY + 10} textAnchor="middle" fontSize={8} fill={C.muted}>total</text>
        </svg>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 5 }}>
          {segments.map((seg) => (
            <div key={seg.label} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 8, height: 8, borderRadius: 2, background: seg.color, flexShrink: 0 }} />
              <span style={{ fontSize: 10, color: C.textSub, flex: 1 }}>{seg.label}</span>
              <span style={{ fontSize: 10, fontWeight: 700, color: seg.color }}>{Math.round((seg.count / total) * 100)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── AI Thinking Speed ────────────────────────────────────────────────────────

const SPEED_MODELS = [
  { name: 'Haiku',  ms: 200,  color: C.warn,   desc: 'Regime · Risk · Exit',   note: 'Fast'     },
  { name: 'Sonnet', ms: 800,  color: C.info,   desc: 'Trade · Critic agents',  note: 'Balanced' },
  { name: 'Opus',   ms: 2000, color: C.brand,  desc: 'High-stakes decisions',  note: 'Thorough' },
];
const MAX_MS = 2000;

function AIThinkingSpeed() {
  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '18px 20px',
    }}>
      <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 4 }}>AI Thinking Speed</div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 14, lineHeight: 1.5 }}>
        Speed vs thoroughness — the bot selects the right model for each decision type
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {SPEED_MODELS.map(({ name, ms, color, desc, note }) => {
          const pct = Math.round((ms / MAX_MS) * 100);
          return (
            <div key={name}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 5 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <span style={{
                    fontSize: F.xs, fontWeight: 800, color,
                    width: 48, flexShrink: 0,
                  }}>{name}</span>
                  <span style={{
                    fontSize: 10,
                    padding: '1px 6px',
                    borderRadius: R.pill,
                    background: color + '18',
                    color,
                    fontWeight: 600,
                    flexShrink: 0,
                  }}>{note}</span>
                </div>
                <span style={{ fontSize: F.xs, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>
                  ~{ms >= 1000 ? `${ms / 1000}s` : `${ms}ms`} avg
                </span>
              </div>

              {/* Speed bar */}
              <div style={{ height: 8, background: C.surface, borderRadius: R.pill, overflow: 'hidden' }}>
                <div style={{
                  width: `${pct}%`,
                  height: '100%',
                  background: `linear-gradient(90deg, ${color}80, ${color})`,
                  borderRadius: R.pill,
                  transition: 'width 0.5s ease',
                }} />
              </div>

              <div style={{ fontSize: 10, color: C.muted, marginTop: 3 }}>{desc}</div>
            </div>
          );
        })}
      </div>

      <div style={{
        marginTop: 14,
        paddingTop: 12,
        borderTop: `1px solid ${C.border}`,
        fontSize: 10,
        color: C.muted,
        lineHeight: 1.5,
      }}>
        Typical latency values. Actual response time varies with API load and prompt length.
      </div>
    </div>
  );
}

// ─── Agent Sequence Timeline ──────────────────────────────────────────────────

const TIMELINE_AGENTS = [
  {
    key: 'regime',
    label: 'Regime',
    initial: 'R',
    model: 'Haiku',
    color: C.info,
    latencyMs: 120,
    outputs: ['market regime', 'directional bias', 'volatility class'],
  },
  {
    key: 'trade',
    label: 'Trade',
    initial: 'T',
    model: 'Sonnet',
    color: C.brand,
    latencyMs: 800,
    outputs: ['go/skip/flip', 'entry thesis', 'confluence score'],
  },
  {
    key: 'risk',
    label: 'Risk',
    initial: 'Rk',
    model: 'Haiku',
    color: C.warn,
    latencyMs: 150,
    outputs: ['position size', 'leverage tier', 'portfolio risk'],
  },
  {
    key: 'critic',
    label: 'Critic',
    initial: 'C',
    model: 'Sonnet',
    color: C.bear,
    latencyMs: 900,
    outputs: ['veto/approve', 'counter-thesis', 'stress test'],
  },
  {
    key: 'learning',
    label: 'Learning',
    initial: 'L',
    model: 'Haiku',
    color: C.bull,
    latencyMs: 100,
    outputs: ['lesson stored', 'hypothesis', 'calibration note'],
  },
] as const;

const MAX_LATENCY_MS = Math.max(...TIMELINE_AGENTS.map((a) => a.latencyMs));

function AgentSequenceTimeline() {
  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '18px 16px 14px',
    }}>
      {/* Header */}
      <div style={{ fontSize: F.xs, fontWeight: 700, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 16 }}>
        Agent Pipeline Sequence
      </div>

      {/* Horizontal node row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', overflowX: 'auto', paddingBottom: 4 }}>
        {TIMELINE_AGENTS.map((agent, i) => (
          <React.Fragment key={agent.key}>
            {/* Node column */}
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5, flexShrink: 0, minWidth: 52 }}>
              {/* Colored circle with initial */}
              <div style={{
                width: 44,
                height: 44,
                borderRadius: '50%',
                background: agent.color + '20',
                border: `2px solid ${agent.color}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: `0 0 10px ${agent.color}35`,
              }}>
                <span style={{ fontSize: 11, fontWeight: 800, color: agent.color }}>{agent.initial}</span>
              </div>

              {/* Agent name */}
              <span style={{ fontSize: 10, fontWeight: 700, color: C.text, textAlign: 'center', lineHeight: 1.2 }}>
                {agent.label}
              </span>

              {/* Model badge */}
              <span style={{
                fontSize: 9,
                fontWeight: 600,
                padding: '1px 5px',
                borderRadius: R.pill,
                background: agent.color + '18',
                color: agent.color,
                lineHeight: 1.4,
              }}>
                {agent.model}
              </span>

              {/* Latency bar */}
              <div style={{ width: 44, marginTop: 4 }}>
                <div style={{ width: '100%', height: 5, background: C.surface, borderRadius: R.pill, overflow: 'hidden' }}>
                  <div style={{
                    width: `${Math.round((agent.latencyMs / MAX_LATENCY_MS) * 100)}%`,
                    height: '100%',
                    background: `linear-gradient(90deg, ${agent.color}70, ${agent.color})`,
                    borderRadius: R.pill,
                  }} />
                </div>
                <div style={{ fontSize: 9, color: C.muted, textAlign: 'center', marginTop: 2, fontVariantNumeric: 'tabular-nums' }}>
                  ~{agent.latencyMs}ms
                </div>
              </div>
            </div>

            {/* Arrow connector between nodes */}
            {i < TIMELINE_AGENTS.length - 1 && (
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                paddingTop: 14,
                flexShrink: 0,
                width: 20,
                gap: 2,
              }}>
                {/* Arrow line + head */}
                <div style={{ display: 'flex', alignItems: 'center' }}>
                  <div style={{ width: 10, height: 1, background: C.border }} />
                  <div style={{
                    borderTop: '4px solid transparent',
                    borderBottom: '4px solid transparent',
                    borderLeft: `5px solid ${C.border}`,
                  }} />
                </div>
                <span style={{ fontSize: 8, color: C.faint, whiteSpace: 'nowrap' }}>feeds</span>
              </div>
            )}
          </React.Fragment>
        ))}
      </div>

      {/* Output tag pills — two rows per agent laid out column by column */}
      <div style={{
        marginTop: 14,
        paddingTop: 12,
        borderTop: `1px solid ${C.border}`,
        display: 'flex',
        justifyContent: 'space-between',
        gap: 4,
        overflowX: 'auto',
      }}>
        {TIMELINE_AGENTS.map((agent) => (
          <div key={agent.key} style={{ display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'center', flexShrink: 0, minWidth: 52 }}>
            {agent.outputs.map((tag) => (
              <span key={tag} style={{
                fontSize: 8,
                fontWeight: 600,
                padding: '2px 5px',
                borderRadius: R.xs,
                background: agent.color + '14',
                border: `1px solid ${agent.color}28`,
                color: agent.color,
                lineHeight: 1.4,
                textAlign: 'center',
                whiteSpace: 'nowrap',
              }}>
                {tag}
              </span>
            ))}
          </div>
        ))}
      </div>

      <div style={{ marginTop: 10, fontSize: 9, color: C.faint, lineHeight: 1.5 }}>
        Latency bars are proportional to max agent time (~900ms Critic). Total pipeline: ~2.1s typical.
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

const ACTION_TABS = ['ALL', 'GO', 'SKIP', 'VETOED', 'BLOCKED', 'FLIP'];

export default function AiDecisionsPage() {
  const [decisions, setDecisions] = useState<LlmDecision[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('ALL');
  const [symbolFilter, setSymbolFilter] = useState('ALL');
  const [newIds, setNewIds] = useState<Set<number>>(new Set());
  const prevCount = useRef(0);
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  const fetchDecisions = async () => {
    const r = await apiFetch<LlmFeedResponse>('/v1/llm/feed?limit=200');
    if (r?.items) {
      const items = r.items;
      if (items.length > prevCount.current) {
        const fresh = new Set(items.slice(0, items.length - prevCount.current).map((d) => d.ts));
        setNewIds(fresh);
        setTimeout(() => setNewIds(new Set()), 3000);
      }
      prevCount.current = items.length;
      setDecisions(items);
      setLastUpdate(new Date());
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchDecisions();
    const iv = setInterval(fetchDecisions, 30_000);
    return () => clearInterval(iv);
  }, []);

  // Available symbols
  const symbols = useMemo(() => {
    const s = new Set(decisions.map((d) => d.symbol).filter(Boolean) as string[]);
    return ['ALL', ...Array.from(s).sort()];
  }, [decisions]);

  // Filtered decisions
  const filtered = useMemo(() => {
    return decisions.filter((d) => {
      if (symbolFilter !== 'ALL' && d.symbol !== symbolFilter) return false;
      if (activeTab === 'ALL') return true;
      if (activeTab === 'GO') return (d.action === 'proceed' || d.action === 'go') && d.allowed && !d.is_veto;
      if (activeTab === 'SKIP') return (d.action === 'flat' || d.action === 'skip') && !d.is_veto;
      if (activeTab === 'VETOED') return d.is_veto;
      if (activeTab === 'BLOCKED') return !d.allowed && !d.is_veto;
      if (activeTab === 'FLIP') return d.action === 'flip';
      return true;
    });
  }, [decisions, activeTab, symbolFilter]);

  // Stats
  const stats = useMemo(() => {
    const total = decisions.length;
    const goes = decisions.filter((d) => (d.action === 'proceed' || d.action === 'go') && d.allowed && !d.is_veto).length;
    const vetoes = decisions.filter((d) => d.is_veto).length;
    const blocked = decisions.filter((d) => !d.allowed && !d.is_veto).length;
    const avgConf = total > 0 ? decisions.reduce((a, d) => a + (d.confidence ?? 0), 0) / total : 0;
    const models = new Set(decisions.map((d) => d.model).filter(Boolean)).size;
    return { total, goes, vetoes, blocked, avgConf, models };
  }, [decisions]);

  return (
    <Layout>
      <Head>
        <title>Decision Theater — WAGMI AI Reasoning</title>
        <meta name="description" content="Every AI trading decision, fully explained. See the agent chain, the Critic's veto reasoning, and the full thought process behind each trade." />
      </Head>

      <style>{`
        @keyframes fadeInDown { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes glow { 0%,100% { box-shadow: 0 0 6px ${C.brand}40; } 50% { box-shadow: 0 0 16px ${C.brand}70; } }
        @keyframes pipelineDot { 0% { left: 0; opacity: 1; } 80% { left: 36px; opacity: 1; } 100% { left: 40px; opacity: 0; } }
      `}</style>

      <div style={{ maxWidth: 1100, margin: '0 auto' }}>

        {/* ── Header ── */}
        <div style={{ marginBottom: 24, display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>
              The Decision Theater
            </div>
            <h1 style={{ margin: '0 0 4px', fontSize: F['3xl'], fontWeight: 800, color: C.text }}>
              AI Thinks Out Loud
            </h1>
            <p style={{ margin: 0, color: C.muted, fontSize: F.base }}>
              Every trade decision, every agent's reasoning, every veto — fully transparent. No black box.
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {lastUpdate && <span style={{ fontSize: F.xs, color: C.muted }}>Updated {timeAgo(lastUpdate.toISOString())}</span>}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 5,
              padding: '4px 10px', borderRadius: R.pill,
              background: `${C.bull}12`, border: `1px solid ${C.bull}30`,
            }}>
              <span style={{ width: 6, height: 6, borderRadius: '50%', background: C.bull, display: 'inline-block', animation: 'glow 2s infinite' }} />
              <span style={{ fontSize: F.xs, color: C.bull, fontWeight: 700 }}>LIVE</span>
            </div>
          </div>
        </div>

        {/* ── Agent Pipeline Flow ── */}
        <AgentPipelineFlow decision={decisions[0] ?? null} />

        {/* ── KPI Strip ── */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
          {[
            { label: 'Total Decisions', value: String(stats.total), color: C.text },
            { label: 'GO Signals', value: String(stats.goes), color: C.bull },
            { label: 'Vetoed', value: String(stats.vetoes), color: C.purple },
            { label: 'Gate Blocked', value: String(stats.blocked), color: C.bear },
            { label: 'Avg Confidence', value: `${Math.round(stats.avgConf * 100)}%`, color: C.brand },
            { label: 'Models Used', value: String(stats.models), color: C.info },
          ].map(({ label, value, color }) => (
            <div key={label} style={{
              flex: '1 1 130px', background: C.card, border: `1px solid ${C.border}`,
              borderRadius: R.md, padding: '12px 16px', boxShadow: S.sm,
            }}>
              <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 3 }}>{label}</div>
              <div style={{ fontSize: F.xl, fontWeight: 700, color }}>{value}</div>
            </div>
          ))}
        </div>

        {/* ── Main Layout: feed + sidebar ── */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 280px', gap: 20, alignItems: 'start' }}>

          {/* ── Left: Decision Feed ── */}
          <div>
            {/* Filters */}
            <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center' }}>
              {/* Action tabs */}
              <div style={{ display: 'flex', gap: 4, background: C.surface, borderRadius: R.sm, padding: 4, flexWrap: 'wrap' }}>
                {ACTION_TABS.map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    style={{
                      padding: '4px 12px', borderRadius: R.xs, border: 'none', cursor: 'pointer',
                      background: activeTab === tab ? C.card : 'transparent',
                      color: activeTab === tab ? C.text : C.muted,
                      fontSize: F.xs, fontWeight: activeTab === tab ? 700 : 400,
                      boxShadow: activeTab === tab ? S.sm : 'none',
                    }}
                  >{tab}</button>
                ))}
              </div>

              {/* Symbol filter */}
              <select
                value={symbolFilter}
                onChange={(e) => setSymbolFilter(e.target.value)}
                style={{
                  padding: '6px 12px', borderRadius: R.sm, border: `1px solid ${C.border}`,
                  background: C.card, color: C.text, fontSize: F.xs, cursor: 'pointer',
                }}
              >
                {symbols.map((s) => <option key={s} value={s}>{s === 'ALL' ? 'All symbols' : s}</option>)}
              </select>

              <span style={{ fontSize: F.xs, color: C.muted, marginLeft: 'auto' }}>
                {filtered.length} decisions shown
              </span>
            </div>

            {/* Intro callout */}
            <div style={{
              background: `${C.brand}10`, border: `1px solid ${C.brand}25`,
              borderRadius: R.md, padding: '10px 14px', marginBottom: 14,
              fontSize: F.xs, color: C.textSub, lineHeight: 1.5,
            }}>
              <strong style={{ color: C.brand }}>How to read this:</strong> Click any decision to expand the full AI reasoning chain.
              Green left border = GO signal. Purple = Critic veto. Red = gate-blocked.
              The <strong style={{ color: C.purple }}>veto</strong> panel shows the Critic's counter-argument.{' '}
              <Link href="/learn#ai-brain" style={{ color: C.brand, fontWeight: 600, textDecoration: 'none' }}>Learn how agents work →</Link>
            </div>

            {/* Decision list */}
            {loading ? (
              <div style={{ color: C.muted, padding: 32, textAlign: 'center', fontSize: F.base }}>Loading decisions…</div>
            ) : filtered.length === 0 ? (
              <div style={{
                background: C.card, border: `1px solid ${C.border}`, borderRadius: R.xl,
                padding: 40, textAlign: 'center',
              }}>
                <div style={{ fontSize: 32, marginBottom: 10 }}>🤖</div>
                <div style={{ fontSize: F.base, color: C.muted }}>No decisions match this filter.</div>
                <div style={{ fontSize: F.sm, color: C.faint, marginTop: 6 }}>
                  The bot logs decisions when LLM_MODE is set to ADVISORY or higher. Check the bot configuration.
                </div>
              </div>
            ) : (
              filtered.map((d) => (
                <DecisionCard key={`${d.ts}-${d.symbol}`} d={d} isNew={newIds.has(d.ts)} />
              ))
            )}
          </div>

          {/* ── Right: Stats panels ── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16, position: 'sticky', top: 80 }}>
            <DecisionMixDonut decisions={decisions} />
            <ConfidenceTrendSparkline decisions={decisions} />
            <VetoPanel decisions={decisions} />
            <VetoReasonWordCloud decisions={decisions.filter((d) => d.is_veto).slice(0, 100)} />
            <ModelPanel decisions={decisions} />
            <AgentSequenceTimeline />
            <AIThinkingSpeed />

            {/* "What makes this unique" callout */}
            <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 18px' }}>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 10 }}>Why this matters</div>
              {[
                { icon: '🔍', text: 'Every decision has a reason — no black box' },
                { icon: '⚔️', text: 'Critic must argue against the trade before vetoing' },
                { icon: '🧠', text: 'Each loss becomes a memory note for future decisions' },
                { icon: '📚', text: 'Connect any decision to the course curriculum' },
              ].map(({ icon, text }) => (
                <div key={text} style={{ display: 'flex', gap: 8, marginBottom: 8, fontSize: F.xs, color: C.muted }}>
                  <span style={{ flexShrink: 0 }}>{icon}</span> {text}
                </div>
              ))}
              <div style={{ marginTop: 12, paddingTop: 10, borderTop: `1px solid ${C.border}` }}>
                <Link href="/about#agents" style={{ fontSize: F.xs, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>About the agent architecture →</Link>
              </div>
            </div>

            {/* Deep dive links */}
            <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 18px' }}>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 10 }}>Explore further</div>
              {[
                { href: '/forensics', label: 'Trade Forensics', desc: 'Pair decisions with trade outcomes' },
                { href: '/llm-audit', label: 'LLM Audit', desc: 'Model routing and cost breakdown' },
                { href: '/results', label: 'Track Record', desc: 'See if the AI\'s calls were right' },
                { href: '/learn', label: 'Understand the Edge', desc: 'Learn what each agent decides' },
              ].map(({ href, label, desc }) => (
                <Link key={href} href={href} style={{ display: 'flex', flexDirection: 'column', padding: '8px 0', borderBottom: `1px solid ${C.border}`, textDecoration: 'none' }}>
                  <span style={{ fontSize: F.sm, fontWeight: 600, color: C.brand }}>{label}</span>
                  <span style={{ fontSize: F.xs, color: C.muted }}>{desc}</span>
                </Link>
              ))}
            </div>
          </div>
        </div>
      </div>
    </Layout>
  );
}
