/**
 * /agent-intelligence — The Agent Brain Dashboard
 *
 * Shows per-agent performance, beliefs, calibration curves,
 * debate outcomes, and team-level analytics.
 */
import React, { useEffect, useState, useMemo } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { C, R, S, F, G, timeAgo } from '../src/theme';
import { apiFetch } from '../src/api';

// ─── Types ───────────────────────────────────────────────────────────────────

interface AgentOverview {
  role: string;
  has_brain: boolean;
  total_decisions: number;
  correct_decisions: number;
  accuracy: number | null;
  belief_count: number;
  last_updated: string | null;
}

interface CalibrationBucket {
  predicted_avg: number;
  actual_accuracy: number;
  count: number;
}

interface AgentPerf {
  agent: string;
  has_data: boolean;
  total_decisions: number;
  correct_decisions: number;
  overall_accuracy: number | null;
  by_regime: Record<string, { correct: number; total: number; accuracy: number }>;
  avg_response_time_ms: number | null;
  recent_decisions: any[];
}

interface DebateEntry {
  consensus_direction: string;
  consensus_confidence: number;
  agreement_score: number;
  dissenting_agents: string[];
  key_arguments_for: string[];
  key_arguments_against: string[];
  risk_flags: string[];
  ts?: number;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function roleColor(role: string): string {
  const map: Record<string, string> = {
    regime: '#f59e0b',
    trade: C.brand,
    risk: C.bear,
    critic: C.purple,
    learning: C.bull,
    exit: '#ec4899',
    scout: C.info,
    quant: '#06b6d4',
    overseer: '#8b5cf6',
  };
  return map[role] || C.muted;
}

function roleIcon(role: string): string {
  const map: Record<string, string> = {
    regime: '🌊', trade: '🎯', risk: '🛡️', critic: '⚖️',
    learning: '🧠', exit: '🚪', scout: '🔭', quant: '📊', overseer: '👁️',
  };
  return map[role] || '🤖';
}

function pctBar(value: number, color: string, width = 80) {
  const pct = Math.round(value * 100);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width, height: 6, background: C.border, borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: F.xs, fontWeight: 700, color, minWidth: 32 }}>{pct}%</span>
    </div>
  );
}

function Card({ children, title, style }: { children: React.ReactNode; title?: string; style?: React.CSSProperties }) {
  return (
    <div style={{ background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: 16, ...style }}>
      {title && <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 12 }}>{title}</div>}
      {children}
    </div>
  );
}

function Pill({ label, color }: { label: string; color: string }) {
  return (
    <span style={{
      fontSize: F.xs, fontWeight: 700, color,
      background: `${color}20`, padding: '2px 8px', borderRadius: R.full,
      border: `1px solid ${color}40`,
    }}>
      {label}
    </span>
  );
}

// ─── Agent Card Component ────────────────────────────────────────────────────

function AgentCard({ agent, onClick }: { agent: AgentOverview; onClick: () => void }) {
  const color = roleColor(agent.role);
  const icon = roleIcon(agent.role);

  return (
    <div
      onClick={onClick}
      style={{
        background: G.card, border: `1px solid ${C.border}`, borderRadius: R.lg,
        padding: 16, cursor: 'pointer', transition: 'all 0.15s',
        borderLeft: `3px solid ${color}`,
      }}
      onMouseEnter={(e) => { (e.target as HTMLElement).style.borderColor = color; }}
      onMouseLeave={(e) => { (e.target as HTMLElement).style.borderColor = C.border; }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 18 }}>{icon}</span>
          <span style={{ fontSize: F.sm, fontWeight: 700, color, textTransform: 'capitalize' }}>
            {agent.role} Agent
          </span>
        </div>
        {agent.has_brain ? (
          <Pill label="ACTIVE" color={C.bull} />
        ) : (
          <Pill label="NO BRAIN" color={C.muted} />
        )}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <div>
          <div style={{ fontSize: F.xs, color: C.muted }}>Decisions</div>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>{agent.total_decisions}</div>
        </div>
        <div>
          <div style={{ fontSize: F.xs, color: C.muted }}>Accuracy</div>
          {agent.accuracy !== null ? (
            pctBar(agent.accuracy, agent.accuracy >= 0.6 ? C.bull : agent.accuracy >= 0.5 ? C.warn : C.bear)
          ) : (
            <div style={{ fontSize: F.sm, color: C.muted }}>---</div>
          )}
        </div>
        <div>
          <div style={{ fontSize: F.xs, color: C.muted }}>Beliefs</div>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>{agent.belief_count}</div>
        </div>
        <div>
          <div style={{ fontSize: F.xs, color: C.muted }}>Status</div>
          <div style={{ fontSize: F.sm, color: agent.has_brain ? C.bull : C.muted }}>
            {agent.has_brain ? 'Learning' : 'Awaiting Data'}
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Calibration Chart (text-based) ──────────────────────────────────────────

function CalibrationChart({ data }: { data: Record<string, CalibrationBucket> }) {
  const buckets = Object.entries(data);
  if (buckets.length === 0) return <div style={{ color: C.muted, fontSize: F.sm }}>No calibration data yet.</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: F.xs, color: C.muted, marginBottom: 4 }}>
        <span>Predicted</span>
        <span>Actual</span>
        <span>n</span>
      </div>
      {buckets.map(([label, bucket]) => {
        const diff = bucket.actual_accuracy - bucket.predicted_avg;
        const diffColor = Math.abs(diff) < 0.1 ? C.bull : Math.abs(diff) < 0.2 ? C.warn : C.bear;
        return (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: F.xs }}>
            <span style={{ color: C.textSub, minWidth: 60 }}>{label}</span>
            <div style={{ flex: 1, margin: '0 8px' }}>
              {pctBar(bucket.actual_accuracy, diffColor, 60)}
            </div>
            <span style={{ color: C.muted, minWidth: 24, textAlign: 'right' }}>{bucket.count}</span>
          </div>
        );
      })}
      <div style={{ fontSize: F.xs, color: C.muted, marginTop: 4 }}>
        Perfect calibration = predicted matches actual. Green = well-calibrated.
      </div>
    </div>
  );
}

// ─── Debate Card ─────────────────────────────────────────────────────────────

function DebateCard({ debate }: { debate: DebateEntry }) {
  const dirColor = debate.consensus_direction === 'bullish' ? C.bull
    : debate.consensus_direction === 'bearish' ? C.bear : C.muted;
  const agreementColor = debate.agreement_score >= 0.7 ? C.bull
    : debate.agreement_score >= 0.5 ? C.warn : C.bear;

  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Pill label={debate.consensus_direction.toUpperCase()} color={dirColor} />
          <span style={{ fontSize: F.xs, color: C.muted }}>
            Conf: {Math.round(debate.consensus_confidence * 100)}%
          </span>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: F.xs, color: C.muted }}>Agreement:</span>
          {pctBar(debate.agreement_score, agreementColor, 50)}
        </div>
      </div>

      {debate.dissenting_agents.length > 0 && (
        <div style={{ fontSize: F.xs, color: C.warn, marginBottom: 8 }}>
          Dissent: {debate.dissenting_agents.map(a => `${roleIcon(a)} ${a}`).join(', ')}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
        <div>
          <div style={{ fontSize: F.xs, color: C.bull, fontWeight: 700, marginBottom: 4 }}>Arguments For</div>
          {debate.key_arguments_for.slice(0, 3).map((arg, i) => (
            <div key={i} style={{ fontSize: F.xs, color: C.textSub, marginBottom: 2 }}>+ {arg}</div>
          ))}
        </div>
        <div>
          <div style={{ fontSize: F.xs, color: C.bear, fontWeight: 700, marginBottom: 4 }}>Arguments Against</div>
          {debate.key_arguments_against.slice(0, 3).map((arg, i) => (
            <div key={i} style={{ fontSize: F.xs, color: C.textSub, marginBottom: 2 }}>- {arg}</div>
          ))}
        </div>
      </div>

      {debate.risk_flags.length > 0 && (
        <div style={{ marginTop: 8, padding: '4px 8px', background: `${C.bear}10`, borderRadius: R.md }}>
          {debate.risk_flags.map((flag, i) => (
            <div key={i} style={{ fontSize: F.xs, color: C.bear }}>Risk: {flag}</div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function AgentIntelligence() {
  const [agents, setAgents] = useState<AgentOverview[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [agentPerf, setAgentPerf] = useState<AgentPerf | null>(null);
  const [calibration, setCalibration] = useState<Record<string, CalibrationBucket> | null>(null);
  const [debates, setDebates] = useState<DebateEntry[]>([]);
  const [teamCal, setTeamCal] = useState<Record<string, { calibration_error: number; decisions: number; overall_accuracy: number | null }> | null>(null);
  const [loading, setLoading] = useState(true);

  // Load overview
  useEffect(() => {
    Promise.all([
      apiFetch('/v1/agents/overview').then(r => r.json()).catch(() => ({ agents: [] })),
      apiFetch('/v1/agents/debate/history?limit=10').then(r => r.json()).catch(() => ({ items: [] })),
      apiFetch('/v1/agents/team/calibration').then(r => r.json()).catch(() => ({ agents: {} })),
    ]).then(([overview, debateHistory, team]) => {
      setAgents(overview.agents || []);
      setDebates(debateHistory.items || []);
      setTeamCal(team.agents || null);
      setLoading(false);
    });
  }, []);

  // Load detail when agent selected
  useEffect(() => {
    if (!selectedAgent) return;
    Promise.all([
      apiFetch(`/v1/agents/${selectedAgent}/performance`).then(r => r.json()).catch(() => null),
      apiFetch(`/v1/agents/${selectedAgent}/calibration`).then(r => r.json()).catch(() => null),
    ]).then(([perf, cal]) => {
      setAgentPerf(perf);
      setCalibration(cal?.curve || null);
    });
  }, [selectedAgent]);

  return (
    <>
      <Head><title>Agent Intelligence | WAGMI</title></Head>
      <div style={{ background: C.bg, minHeight: '100vh', padding: '24px 16px', maxWidth: 1200, margin: '0 auto' }}>

        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
          <div>
            <h1 style={{ fontSize: F.xl, fontWeight: 800, color: C.text, margin: 0 }}>
              Agent Intelligence
            </h1>
            <p style={{ fontSize: F.sm, color: C.muted, margin: '4px 0 0' }}>
              Per-agent brains, calibration, debate outcomes, team performance
            </p>
          </div>
          <Link href="/ai-decisions" style={{ fontSize: F.sm, color: C.brand, textDecoration: 'none' }}>
            Decision Feed →
          </Link>
        </div>

        {/* Team Calibration Summary */}
        {teamCal && Object.keys(teamCal).length > 0 && (
          <Card title="Team Calibration Overview" style={{ marginBottom: 16 }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
              {Object.entries(teamCal).map(([role, data]) => (
                <div key={role} style={{ padding: 8, background: C.surface, borderRadius: R.md }}>
                  <div style={{ fontSize: F.xs, color: roleColor(role), fontWeight: 700, textTransform: 'capitalize' }}>
                    {roleIcon(role)} {role}
                  </div>
                  <div style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>
                    {data.overall_accuracy !== null ? `${Math.round(data.overall_accuracy * 100)}%` : '---'}
                  </div>
                  <div style={{ fontSize: 10, color: C.muted }}>
                    Cal err: {(data.calibration_error * 100).toFixed(1)}% | n={data.decisions}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Agent Grid */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
          gap: 12, marginBottom: 24,
        }}>
          {loading ? (
            <Card><div style={{ color: C.muted, fontSize: F.sm }}>Loading agent data...</div></Card>
          ) : agents.length === 0 ? (
            <Card>
              <div style={{ color: C.muted, fontSize: F.sm, textAlign: 'center', padding: 24 }}>
                No agent data yet. Enable LLM_MULTI_AGENT=true and run trades.
              </div>
            </Card>
          ) : (
            agents.map(agent => (
              <AgentCard
                key={agent.role}
                agent={agent}
                onClick={() => setSelectedAgent(agent.role === selectedAgent ? null : agent.role)}
              />
            ))
          )}
        </div>

        {/* Agent Detail Panel */}
        {selectedAgent && agentPerf && (
          <Card title={`${roleIcon(selectedAgent)} ${selectedAgent.toUpperCase()} Agent — Detailed Performance`} style={{ marginBottom: 24 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>

              {/* Regime Breakdown */}
              <div>
                <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 8 }}>
                  Accuracy by Regime
                </div>
                {agentPerf.by_regime && Object.keys(agentPerf.by_regime).length > 0 ? (
                  Object.entries(agentPerf.by_regime).map(([regime, data]) => (
                    <div key={regime} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                      <span style={{ fontSize: F.xs, color: C.textSub, textTransform: 'capitalize' }}>{regime}</span>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        {pctBar(data.accuracy, data.accuracy >= 0.6 ? C.bull : C.warn, 50)}
                        <span style={{ fontSize: 10, color: C.muted }}>n={data.total}</span>
                      </div>
                    </div>
                  ))
                ) : (
                  <div style={{ fontSize: F.xs, color: C.muted }}>No regime-specific data yet.</div>
                )}
              </div>

              {/* Calibration Curve */}
              <div>
                <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 8 }}>
                  Calibration Curve
                </div>
                {calibration ? (
                  <CalibrationChart data={calibration} />
                ) : (
                  <div style={{ fontSize: F.xs, color: C.muted }}>Need 5+ decisions for calibration.</div>
                )}
              </div>
            </div>

            {/* Recent Decisions */}
            {agentPerf.recent_decisions && agentPerf.recent_decisions.length > 0 && (
              <div style={{ marginTop: 16 }}>
                <div style={{ fontSize: F.sm, fontWeight: 700, color: C.textSub, marginBottom: 8 }}>
                  Recent Decisions
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {agentPerf.recent_decisions.slice(0, 5).map((d: any, i: number) => (
                    <div key={i} style={{
                      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      padding: '4px 8px', background: C.surface, borderRadius: R.sm, fontSize: F.xs,
                    }}>
                      <span style={{ color: C.textSub }}>{d.regime || '—'}</span>
                      <span style={{ color: d.was_correct ? C.bull : C.bear }}>
                        {d.was_correct ? 'CORRECT' : 'WRONG'}
                      </span>
                      <span style={{ color: C.muted }}>{d.confidence ? `${Math.round(d.confidence * 100)}%` : '—'}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Card>
        )}

        {/* Debate History */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontSize: F.base, fontWeight: 700, color: C.text, marginBottom: 12 }}>
            Recent Debates
          </div>
          {debates.length === 0 ? (
            <Card>
              <div style={{ color: C.muted, fontSize: F.sm, textAlign: 'center', padding: 16 }}>
                No debates yet. Debates trigger when agents disagree on direction.
              </div>
            </Card>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {debates.map((debate, i) => <DebateCard key={i} debate={debate} />)}
            </div>
          )}
        </div>

        {/* Footer nav */}
        <div style={{ display: 'flex', gap: 12, justifyContent: 'center', padding: '16px 0' }}>
          <Link href="/" style={{ fontSize: F.sm, color: C.muted, textDecoration: 'none' }}>Home</Link>
          <Link href="/ai-decisions" style={{ fontSize: F.sm, color: C.muted, textDecoration: 'none' }}>Decisions</Link>
          <Link href="/forensics" style={{ fontSize: F.sm, color: C.muted, textDecoration: 'none' }}>Forensics</Link>
          <Link href="/performance" style={{ fontSize: F.sm, color: C.muted, textDecoration: 'none' }}>Performance</Link>
        </div>
      </div>
    </>
  );
}
