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
            <VetoPanel decisions={decisions} />
            <ModelPanel decisions={decisions} />

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
