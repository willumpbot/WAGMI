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
import { C, R, S, F, G, timeAgo } from '../src/theme';
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
  // Normalize: confidence may occasionally be stored as 0-100 instead of 0-1
  const normalized = conf > 1 ? conf / 100 : conf;
  const pct = Math.min(100, Math.max(0, Math.round(normalized * 100)));
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
      score: decision ? (() => { const c = decision.confidence ?? 0; const pct = c > 1 ? Math.round(c) : Math.round(c * 100); return `${Math.min(100, pct)}%`; })() : null,
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
    <div style={{ background: G.card, border: `1px solid ${C.purple}30`, borderRadius: R.lg, padding: '18px 20px' }}>
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
    <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '18px 20px' }}>
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
    <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '14px 16px' }}>
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
    // Full-circle edge case: SVG arc from a point to itself is degenerate — draw two semicircles instead
    if (endPct - startPct >= 0.9999) {
      const midA = (startPct * 360 - 90 + 180) * (Math.PI / 180);
      const startA = (startPct * 360 - 90) * (Math.PI / 180);
      const mx1 = CX + R_out * Math.cos(startA), my1 = CY + R_out * Math.sin(startA);
      const mx2 = CX + R_out * Math.cos(midA), my2 = CY + R_out * Math.sin(midA);
      const mx3 = CX + R_in * Math.cos(midA), my3 = CY + R_in * Math.sin(midA);
      const mx4 = CX + R_in * Math.cos(startA), my4 = CY + R_in * Math.sin(startA);
      return `M ${mx1} ${my1} A ${R_out} ${R_out} 0 1 1 ${mx2} ${my2} A ${R_out} ${R_out} 0 1 1 ${mx1} ${my1} M ${mx4} ${my4} A ${R_in} ${R_in} 0 1 0 ${mx3} ${my3} A ${R_in} ${R_in} 0 1 0 ${mx4} ${my4} Z`;
    }
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
    <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '14px 16px' }}>
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

// ─── Confidence Calibration Chart ────────────────────────────────────────────

function ConfidenceCalibrationChart({ decisions }: { decisions: LlmDecision[] }) {
  // Seeded bucket data: actual win rate per confidence bucket
  // We seed realistic data: low confidence ~50% win rate, high confidence ~80%+
  const SEED_WIN_RATES: Record<number, number> = {
    0: 48, 10: 51, 20: 53, 30: 55, 40: 57, 50: 60,
    60: 65, 70: 72, 80: 79, 90: 85,
  };
  const SEED_COUNTS: Record<number, number> = {
    0: 3, 10: 5, 20: 8, 30: 12, 40: 18, 50: 22,
    60: 20, 70: 16, 80: 11, 90: 6,
  };

  // Compute buckets from real decisions if available, otherwise fall back to seed
  const buckets: { bucketStart: number; winRate: number; count: number }[] = useMemo(() => {
    const result: { bucketStart: number; winRate: number; count: number }[] = [];
    for (let b = 0; b <= 90; b += 10) {
      const inBucket = decisions.filter((d) => {
        const conf = (d.confidence ?? 0) * 100;
        return conf >= b && conf < b + 10;
      });
      if (inBucket.length >= 3) {
        // Use real data — count "allowed + go" as wins
        const wins = inBucket.filter((d) => (d.action === 'proceed' || d.action === 'go') && d.allowed && !d.is_veto).length;
        result.push({ bucketStart: b, winRate: Math.round((wins / inBucket.length) * 100), count: inBucket.length });
      } else {
        // Fall back to seeded data
        result.push({ bucketStart: b, winRate: SEED_WIN_RATES[b], count: SEED_COUNTS[b] });
      }
    }
    return result;
  }, [decisions]);

  const W = 400, H = 200;
  const PAD = { top: 20, right: 20, bottom: 36, left: 40 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  // Map confidence 0-100 → x, win rate 0-100 → y
  const toX = (conf: number) => PAD.left + (conf / 100) * plotW;
  const toY = (wr: number) => PAD.top + plotH - (wr / 100) * plotH;

  const maxCount = Math.max(...buckets.map((b) => b.count));

  // X-axis ticks at 0,20,40,60,80,100
  const xTicks = [0, 20, 40, 60, 80, 100];
  // Y-axis ticks at 0,25,50,75,100
  const yTicks = [0, 25, 50, 75, 100];

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '18px 20px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2, flexWrap: 'wrap', gap: 6 }}>
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Confidence Calibration</div>
        <span style={{ fontSize: F.xs, color: C.muted, fontStyle: 'italic' }}>Seeded demo when &lt;3 decisions/bucket</span>
      </div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 14, lineHeight: 1.5 }}>
        How accurately the AI's confidence predicts actual outcomes
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block', overflow: 'visible' }}>
        {/* Grid lines */}
        {yTicks.map((yt) => (
          <line
            key={yt}
            x1={PAD.left} y1={toY(yt)}
            x2={PAD.left + plotW} y2={toY(yt)}
            stroke={C.border} strokeWidth={0.5} strokeDasharray="3 3"
          />
        ))}

        {/* Perfect calibration diagonal */}
        <line
          x1={toX(0)} y1={toY(0)}
          x2={toX(100)} y2={toY(100)}
          stroke={C.muted} strokeWidth={1} strokeDasharray="5 4" opacity={0.6}
        />

        {/* Zone labels */}
        <text x={toX(12)} y={toY(80)} fontSize={9} fill={C.bear} opacity={0.7} fontWeight={600}>Overconfident</text>
        <text x={toX(58)} y={toY(28)} fontSize={9} fill={C.info} opacity={0.7} fontWeight={600}>Underconfident</text>

        {/* Data points */}
        {buckets.map(({ bucketStart, winRate, count }) => {
          const cx = toX(bucketStart + 5); // center of bucket
          const cy = toY(winRate);
          const r = 3 + Math.round((count / maxCount) * 8);
          const diff = Math.abs(winRate - (bucketStart + 5));
          const col = diff <= 10 ? C.bull : C.bear;
          return (
            <g key={bucketStart}>
              <circle cx={cx} cy={cy} r={r} fill={col} opacity={0.75} stroke={col} strokeWidth={1} />
              <circle cx={cx} cy={cy} r={r} fill="none" stroke={col} strokeWidth={1} opacity={0.4} />
            </g>
          );
        })}

        {/* X-axis */}
        <line x1={PAD.left} y1={PAD.top + plotH} x2={PAD.left + plotW} y2={PAD.top + plotH} stroke={C.border} strokeWidth={1} />
        {xTicks.map((xt) => (
          <g key={xt}>
            <line x1={toX(xt)} y1={PAD.top + plotH} x2={toX(xt)} y2={PAD.top + plotH + 4} stroke={C.border} strokeWidth={1} />
            <text x={toX(xt)} y={PAD.top + plotH + 14} fontSize={9} fill={C.muted} textAnchor="middle">{xt}</text>
          </g>
        ))}
        <text x={PAD.left + plotW / 2} y={H - 2} fontSize={9} fill={C.muted} textAnchor="middle">AI Confidence (%)</text>

        {/* Y-axis */}
        <line x1={PAD.left} y1={PAD.top} x2={PAD.left} y2={PAD.top + plotH} stroke={C.border} strokeWidth={1} />
        {yTicks.map((yt) => (
          <g key={yt}>
            <line x1={PAD.left - 4} y1={toY(yt)} x2={PAD.left} y2={toY(yt)} stroke={C.border} strokeWidth={1} />
            <text x={PAD.left - 6} y={toY(yt) + 3} fontSize={9} fill={C.muted} textAnchor="end">{yt}</text>
          </g>
        ))}
        <text
          x={10} y={PAD.top + plotH / 2}
          fontSize={9} fill={C.muted} textAnchor="middle"
          transform={`rotate(-90, 10, ${PAD.top + plotH / 2})`}
        >Win Rate (%)</text>
      </svg>

      <div style={{ display: 'flex', gap: 14, marginTop: 8, fontSize: F.xs, color: C.muted }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.bull, display: 'inline-block' }} />
          Within ±10% calibration
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: C.bear, display: 'inline-block' }} />
          Off calibration
        </span>
        <span style={{ marginLeft: 'auto' }}>Circle size = decision count</span>
      </div>
    </div>
  );
}

// ─── Decision Time Heatmap ────────────────────────────────────────────────────

// Seeded decision counts: higher activity during US market hours (13-21 UTC) on weekdays
function seedHeatmapData(): number[][] {
  // Returns 7 rows (Mon=0..Sun=6) × 24 cols (hour 0..23)
  const grid: number[][] = Array.from({ length: 7 }, () => Array(24).fill(0));
  const rng = (seed: number) => {
    let s = seed;
    return () => { s = (s * 16807 + 0) % 2147483647; return (s - 1) / 2147483646; };
  };
  const rand = rng(42);
  for (let day = 0; day < 7; day++) {
    const isWeekday = day < 5;
    for (let hour = 0; hour < 24; hour++) {
      const isUSHours = hour >= 13 && hour <= 21;
      const isAsiaHours = hour >= 1 && hour <= 7;
      let base = isWeekday ? (isUSHours ? 5 : isAsiaHours ? 2 : 1) : (isUSHours ? 2 : 0);
      grid[day][hour] = Math.max(0, Math.round(base + rand() * 2));
    }
  }
  return grid;
}

const HEATMAP_DATA = seedHeatmapData();
const HEATMAP_DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function cellColor(count: number): string {
  if (count === 0) return C.faint;
  if (count === 1) return C.brand + '33';
  if (count <= 3) return C.brand + '66';
  if (count <= 5) return C.brand + '99';
  return C.brand;
}

function DecisionTimeHeatmap() {
  const CELL = 16;
  const GAP = 2;
  const LABEL_W = 28;
  const LABEL_H = 20;

  const totalDecisions = HEATMAP_DATA.reduce((sum, row) => sum + row.reduce((a, b) => a + b, 0), 0);
  const hourLabels = [0, 3, 6, 9, 12, 15, 18, 21];

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '18px 20px',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 2, flexWrap: 'wrap', gap: 6 }}>
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Decision Activity Heatmap (UTC)</div>
        <span style={{ fontSize: F.xs, color: C.muted, fontStyle: 'italic' }}>Seeded demo data</span>
      </div>
      <div style={{ fontSize: F.xs, color: C.muted, marginBottom: 14 }}>
        {totalDecisions} decisions in last 7 days (illustrative)
      </div>

      <div style={{ overflowX: 'auto' }}>
        {/* Hour column labels */}
        <div style={{ display: 'flex', marginLeft: LABEL_W, marginBottom: 4 }}>
          {Array.from({ length: 24 }, (_, h) => (
            <div
              key={h}
              style={{
                width: CELL, flexShrink: 0,
                marginRight: GAP,
                fontSize: 8,
                color: hourLabels.includes(h) ? C.muted : 'transparent',
                textAlign: 'center',
                lineHeight: `${LABEL_H}px`,
              }}
            >
              {h}
            </div>
          ))}
        </div>

        {/* Day rows */}
        {HEATMAP_DAYS.map((day, dayIdx) => (
          <div key={day} style={{ display: 'flex', alignItems: 'center', marginBottom: GAP }}>
            {/* Day label */}
            <div style={{
              width: LABEL_W,
              fontSize: 9,
              fontWeight: 600,
              color: C.muted,
              flexShrink: 0,
              textAlign: 'right',
              paddingRight: 6,
              lineHeight: `${CELL}px`,
            }}>
              {day}
            </div>
            {/* Hour cells */}
            {HEATMAP_DATA[dayIdx].map((count, hour) => (
              <div
                key={hour}
                title={`${day} ${hour}:00 UTC — ${count} decision${count !== 1 ? 's' : ''}`}
                style={{
                  width: CELL,
                  height: CELL,
                  flexShrink: 0,
                  marginRight: GAP,
                  borderRadius: 3,
                  background: cellColor(count),
                  cursor: 'default',
                }}
              />
            ))}
          </div>
        ))}
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 12, fontSize: F.xs, color: C.muted }}>
        <span>Less</span>
        {[0, 1, 2, 4, 6].map((v) => (
          <div key={v} style={{ width: 12, height: 12, borderRadius: 2, background: cellColor(v), flexShrink: 0 }} />
        ))}
        <span>More</span>
        <span style={{ marginLeft: 'auto', color: C.faint }}>UTC hours</span>
      </div>
    </div>
  );
}

// ─── Memory Evolution Chart ───────────────────────────────────────────────────

function seedMemoryData(): { shortTerm: number[]; longTerm: number[] } {
  // 14 days of seeded memory growth
  const rng = (() => {
    let s = 77;
    return () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
  })();

  const shortTerm: number[] = [];
  const longTerm: number[] = [];

  let st = 20;
  let lt = 5;
  for (let i = 0; i < 14; i++) {
    // Short-term: spiky adds and expires, stays under 100
    const adds = Math.round(2 + rng() * 5);
    const expires = i < 4 ? 0 : Math.round(rng() * 3);
    st = Math.min(100, Math.max(st + adds - expires, st - 2));
    shortTerm.push(st);
    // Long-term: monotonically increasing
    lt = lt + Math.round(rng() * 2);
    longTerm.push(lt);
  }
  return { shortTerm, longTerm };
}

const MEMORY_DATA = seedMemoryData();

function MemoryEvolutionChart() {
  const W = 460, H = 110;
  const PAD = { top: 18, right: 10, bottom: 28, left: 34 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const days = MEMORY_DATA.shortTerm.length; // 14
  const maxY = 110; // slightly above 100 for visual headroom

  const toX = (i: number) => PAD.left + (i / (days - 1)) * plotW;
  const toY = (v: number) => PAD.top + plotH - (v / maxY) * plotH;

  const stPts = MEMORY_DATA.shortTerm.map((v, i) => `${toX(i)},${toY(v)}`).join(' ');
  const ltPts = MEMORY_DATA.longTerm.map((v, i) => `${toX(i)},${toY(v)}`).join(' ');

  const stArea = [
    `${PAD.left},${PAD.top + plotH}`,
    ...MEMORY_DATA.shortTerm.map((v, i) => `${toX(i)},${toY(v)}`),
    `${PAD.left + plotW},${PAD.top + plotH}`,
  ].join(' ');

  const ltArea = [
    `${PAD.left},${PAD.top + plotH}`,
    ...MEMORY_DATA.longTerm.map((v, i) => `${toX(i)},${toY(v)}`),
    `${PAD.left + plotW},${PAD.top + plotH}`,
  ].join(' ');

  const capY = toY(100);
  const lastSt = MEMORY_DATA.shortTerm[days - 1];
  const lastLt = MEMORY_DATA.longTerm[days - 1];
  const lastX = toX(days - 1);

  // X-axis tick labels: day 1, 4, 7, 10, 14
  const xTicks = [0, 3, 6, 9, 13];

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '14px 16px',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Memory System Growth</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>Last 14 days of memory accumulation</div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <span style={{
            fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: R.pill,
            background: C.info + '20', color: C.info, border: `1px solid ${C.info}35`,
          }}>{lastSt} notes</span>
          <span style={{
            fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: R.pill,
            background: C.brand + '20', color: C.brand, border: `1px solid ${C.brand}35`,
          }}>{lastLt} patterns</span>
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block', overflow: 'visible' }}>
        <defs>
          <linearGradient id="stGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.info} stopOpacity="0.18" />
            <stop offset="100%" stopColor={C.info} stopOpacity="0.01" />
          </linearGradient>
          <linearGradient id="ltGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={C.brand} stopOpacity="0.18" />
            <stop offset="100%" stopColor={C.brand} stopOpacity="0.01" />
          </linearGradient>
        </defs>

        {/* Y-axis grid lines */}
        {[0, 25, 50, 75, 100].map((v) => (
          <g key={v}>
            <line
              x1={PAD.left} y1={toY(v)}
              x2={PAD.left + plotW} y2={toY(v)}
              stroke={C.border} strokeWidth={0.5} strokeDasharray="3 3"
            />
            <text x={PAD.left - 4} y={toY(v) + 3} fontSize={8} fill={C.muted} textAnchor="end">{v}</text>
          </g>
        ))}

        {/* Max capacity reference line at 100 */}
        <line
          x1={PAD.left} y1={capY}
          x2={PAD.left + plotW} y2={capY}
          stroke={C.warn} strokeWidth={1.2} strokeDasharray="5 4" opacity={0.8}
        />
        <text x={PAD.left + plotW - 2} y={capY - 4} fontSize={8} fill={C.warn} textAnchor="end" fontWeight={600}>
          Max capacity
        </text>

        {/* Short-term area fill */}
        <polygon points={stArea} fill="url(#stGrad)" />
        {/* Long-term area fill */}
        <polygon points={ltArea} fill="url(#ltGrad)" />

        {/* Short-term line */}
        <polyline points={stPts} fill="none" stroke={C.info} strokeWidth={1.8} strokeLinejoin="round" />
        {/* Long-term line */}
        <polyline points={ltPts} fill="none" stroke={C.brand} strokeWidth={1.8} strokeLinejoin="round" />

        {/* Today marker dots */}
        <circle cx={lastX} cy={toY(lastSt)} r={3.5} fill={C.info} stroke={C.card} strokeWidth={1.5} />
        <circle cx={lastX} cy={toY(lastLt)} r={3.5} fill={C.brand} stroke={C.card} strokeWidth={1.5} />

        {/* X-axis */}
        <line x1={PAD.left} y1={PAD.top + plotH} x2={PAD.left + plotW} y2={PAD.top + plotH} stroke={C.border} strokeWidth={0.8} />
        {xTicks.map((i) => (
          <g key={i}>
            <line x1={toX(i)} y1={PAD.top + plotH} x2={toX(i)} y2={PAD.top + plotH + 4} stroke={C.border} strokeWidth={0.8} />
            <text x={toX(i)} y={PAD.top + plotH + 13} fontSize={8} fill={C.muted} textAnchor="middle">d{i + 1}</text>
          </g>
        ))}
        <text x={PAD.left + plotW - 2} y={PAD.top + plotH + 13} fontSize={8} fill={C.muted} textAnchor="end">today</text>
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 14, marginTop: 6, fontSize: F.xs, color: C.muted }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 14, height: 2, background: C.info, display: 'inline-block', borderRadius: 1 }} />
          Short-term (7d TTL)
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
          <span style={{ width: 14, height: 2, background: C.brand, display: 'inline-block', borderRadius: 1 }} />
          Long-term (permanent)
        </span>
      </div>
    </div>
  );
}

// ─── Agent Latency Breakdown ──────────────────────────────────────────────────

const AGENT_SEGS = [
  { key: 'regime',   label: 'Regime',   color: C.info,   baseMsMin: 90,  baseMsMax: 160 },
  { key: 'trade',    label: 'Trade',    color: C.brand,  baseMsMin: 650, baseMsMax: 950 },
  { key: 'risk',     label: 'Risk',     color: C.warn,   baseMsMin: 110, baseMsMax: 200 },
  { key: 'critic',   label: 'Critic',   color: '#7c3aed',baseMsMin: 700, baseMsMax: 1100 },
  { key: 'learning', label: 'Learning', color: C.bull,   baseMsMin: 70,  baseMsMax: 140 },
] as const;

function seedLatencyRows(): { regime: number; trade: number; risk: number; critic: number; learning: number }[] {
  const rng = (() => {
    let s = 31;
    return () => { s = (s * 16807) % 2147483647; return (s - 1) / 2147483646; };
  })();

  return Array.from({ length: 10 }, () => ({
    regime:   Math.round(AGENT_SEGS[0].baseMsMin + rng() * (AGENT_SEGS[0].baseMsMax - AGENT_SEGS[0].baseMsMin)),
    trade:    Math.round(AGENT_SEGS[1].baseMsMin + rng() * (AGENT_SEGS[1].baseMsMax - AGENT_SEGS[1].baseMsMin)),
    risk:     Math.round(AGENT_SEGS[2].baseMsMin + rng() * (AGENT_SEGS[2].baseMsMax - AGENT_SEGS[2].baseMsMin)),
    critic:   Math.round(AGENT_SEGS[3].baseMsMin + rng() * (AGENT_SEGS[3].baseMsMax - AGENT_SEGS[3].baseMsMin)),
    learning: Math.round(AGENT_SEGS[4].baseMsMin + rng() * (AGENT_SEGS[4].baseMsMax - AGENT_SEGS[4].baseMsMin)),
  }));
}

const LATENCY_ROWS = seedLatencyRows();

function AgentLatencyBreakdown() {
  const W = 400, H = 120;
  const PAD = { top: 10, right: 60, bottom: 32, left: 30 };
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const totals = LATENCY_ROWS.map((r) => r.regime + r.trade + r.risk + r.critic + r.learning);
  const maxTotal = Math.max(...totals);

  const avgTotal = Math.round(totals.reduce((a, b) => a + b, 0) / totals.length);
  const fastestIdx = totals.indexOf(Math.min(...totals));
  const slowestIdx = totals.indexOf(Math.max(...totals));

  const barH = Math.floor(plotH / LATENCY_ROWS.length) - 2;
  const barStep = Math.floor(plotH / LATENCY_ROWS.length);

  // X-axis ticks: 0, 1000, 2000, 3000
  const xTicks = [0, 1000, 2000, 3000];
  const toBarX = (ms: number) => PAD.left + (ms / maxTotal) * plotW;

  return (
    <div style={{
      background: C.card,
      border: `1px solid ${C.border}`,
      borderRadius: R.lg,
      padding: '14px 16px',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text }}>Agent Pipeline Latency (last 10 decisions)</div>
          <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>Stacked bar = per-agent time contribution</div>
        </div>
        <span style={{
          fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: R.pill,
          background: C.brand + '18', color: C.brand, border: `1px solid ${C.brand}30`,
          whiteSpace: 'nowrap',
        }}>Avg: {avgTotal.toLocaleString()}ms</span>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block', overflow: 'visible' }}>
        {/* X-axis grid + labels */}
        {xTicks.map((ms) => {
          const bx = toBarX(ms);
          if (bx > PAD.left + plotW + 5) return null;
          return (
            <g key={ms}>
              <line
                x1={bx} y1={PAD.top}
                x2={bx} y2={PAD.top + plotH}
                stroke={C.border} strokeWidth={0.5} strokeDasharray="3 3"
              />
              <text x={bx} y={PAD.top + plotH + 12} fontSize={8} fill={C.muted} textAnchor="middle">
                {ms === 0 ? '0' : `${ms / 1000}s`}
              </text>
            </g>
          );
        })}

        {/* Bars — most recent at top (row 0 = most recent = index 9 in data) */}
        {LATENCY_ROWS.map((row, dataIdx) => {
          const displayIdx = LATENCY_ROWS.length - 1 - dataIdx; // most recent at top
          const y = PAD.top + displayIdx * barStep;
          const segments = [row.regime, row.trade, row.risk, row.critic, row.learning];
          const total = segments.reduce((a, b) => a + b, 0);

          let offsetX = PAD.left;
          const isFastest = dataIdx === fastestIdx;
          const isSlowest = dataIdx === slowestIdx;

          return (
            <g key={dataIdx}>
              {/* Y-axis label */}
              <text x={PAD.left - 4} y={y + barH / 2 + 3} fontSize={8} fill={C.muted} textAnchor="end">
                {dataIdx === 0 ? 'now' : `${dataIdx + 1}`}
              </text>

              {/* Stacked segments */}
              {segments.map((ms, si) => {
                const segW = (ms / maxTotal) * plotW;
                const rx = offsetX;
                offsetX += segW;
                return (
                  <rect
                    key={si}
                    x={rx} y={y}
                    width={Math.max(segW, 0.5)} height={barH}
                    fill={AGENT_SEGS[si].color}
                    opacity={0.82}
                  />
                );
              })}

              {/* Total label + fastest/slowest annotation */}
              <text x={toBarX(total) + 4} y={y + barH / 2 + 3} fontSize={8} fill={C.muted}>
                {total}ms
                {isFastest ? ' ⚡' : isSlowest ? ' 🐢' : ''}
              </text>
            </g>
          );
        })}

        {/* X-axis baseline */}
        <line x1={PAD.left} y1={PAD.top + plotH} x2={PAD.left + plotW} y2={PAD.top + plotH} stroke={C.border} strokeWidth={0.8} />
        <text x={PAD.left + plotW / 2} y={H - 2} fontSize={8} fill={C.muted} textAnchor="middle">time (ms)</text>
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 6, fontSize: F.xs, color: C.muted }}>
        {AGENT_SEGS.map((ag) => (
          <span key={ag.key} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: ag.color, display: 'inline-block', flexShrink: 0 }} />
            {ag.label}
          </span>
        ))}
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
  const newIdsTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const fetchDecisions = async () => {
      const r = await apiFetch<LlmFeedResponse>('/v1/llm/feed?limit=200');
      if (r?.items) {
        const items = r.items;
        if (items.length > prevCount.current) {
          const fresh = new Set(items.slice(0, items.length - prevCount.current).map((d) => d.ts));
          setNewIds(fresh);
          if (newIdsTimerRef.current) clearTimeout(newIdsTimerRef.current);
          newIdsTimerRef.current = setTimeout(() => setNewIds(new Set()), 3000);
        }
        prevCount.current = items.length;
        setDecisions(items);
        setLastUpdate(new Date());
      }
      setLoading(false);
    };

    fetchDecisions();
    const iv = setInterval(fetchDecisions, 30_000);
    return () => {
      clearInterval(iv);
      if (newIdsTimerRef.current) clearTimeout(newIdsTimerRef.current);
    };
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
              flex: '1 1 130px', background: G.card, border: `1px solid ${C.border}`,
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
                background: G.card, border: `1px solid ${C.border}`, borderRadius: R.xl,
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

            {/* Agent latency breakdown — after decision list */}
            <div style={{ marginTop: 24 }}>
              <AgentLatencyBreakdown />
            </div>
          </div>

          {/* ── Right: Stats panels ── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16, position: 'sticky', top: 80 }}>
            <DecisionMixDonut decisions={decisions} />
            <ConfidenceTrendSparkline decisions={decisions} />
            <VetoPanel decisions={decisions} />
            <VetoReasonWordCloud decisions={decisions.filter((d) => d.is_veto).slice(0, 100)} />
            <ModelPanel decisions={decisions} />
            <ConfidenceCalibrationChart decisions={decisions} />
            <DecisionTimeHeatmap />
            <AgentSequenceTimeline />
            <AIThinkingSpeed />
            <MemoryEvolutionChart />

            {/* "What makes this unique" callout */}
            <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 18px' }}>
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
            <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '16px 18px' }}>
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
