/**
 * /agent-intelligence — The Agent Brain Dashboard
 *
 * Shows per-agent performance across 9 specialist agents:
 * Regime, Trade, Risk, Critic, Learning, Exit, Scout, Overseer, Quant.
 *
 * Key metrics:
 * - Accuracy by regime: How well does each agent perform in different markets?
 * - Calibration curves: How well does the agent predict its own accuracy?
 * - Team calibration: Is the whole system well-calibrated?
 * - Recent debates: When agents strongly disagreed on decisions
 * - Recent decisions: Last 5 decisions per agent with outcomes
 *
 * Use this to:
 * - Find which agents are struggling (low accuracy)
 * - Identify regime-specific weaknesses
 * - Understand when agents disagree
 * - Track learning progress over time
 *
 * Full guide: docs/AI-PAGES-GUIDE.md#page-2-agent-intelligence
 * System architecture: docs/AI-SYSTEM-ARCHITECTURE.md
 */
import React, { useEffect, useState, useMemo } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { motion } from 'framer-motion';
import { C, R, S, F, G, SP, Glass, timeAgo } from '../src/theme';
import { fadeUp, staggerContainer, staggerContainerSlow, hoverGlow, cinematicReveal, orchestratedContainer, magneticHover } from '../src/animations';
import { apiFetch } from '../src/api';

import { ConfidenceRing } from '../components/ui/ConfidenceRing';

import { Card } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { SectionHeader } from '../components/ui/SectionHeader';
import { EmptyState } from '../components/ui/EmptyState';
import { Grid, Row, Stack } from '../components/ui/Stack';
import { Skeleton } from '../components/ui/Skeleton';
import AgentBrainGraphic from '../components/AgentBrainGraphic';

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
    regime: '\u{1F30A}', trade: '\u{1F3AF}', risk: '\u{1F6E1}\uFE0F', critic: '\u2696\uFE0F',
    learning: '\u{1F9E0}', exit: '\u{1F6AA}', scout: '\u{1F52D}', quant: '\u{1F4CA}', overseer: '\u{1F441}\uFE0F',
  };
  return map[role] || '\u{1F916}';
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

// ─── Agent Card Component ────────────────────────────────────────────────────

function AgentCard({ agent, onClick, delay }: { agent: AgentOverview; onClick: () => void; delay: number }) {
  const color = roleColor(agent.role);
  const icon = roleIcon(agent.role);

  return (
    <Card variant="crystal" hover="magnetic" refraction delay={delay} accent={color} style={{ padding: SP[4], cursor: 'pointer' }}>
      <div onClick={onClick}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 18 }}>{icon}</span>
            <span style={{ fontSize: F.sm, fontWeight: 700, color, textTransform: 'capitalize' }}>
              {agent.role} Agent
            </span>
          </div>
          {agent.has_brain ? (
            <Badge variant="bull" pulse>ACTIVE</Badge>
          ) : (
            <Badge variant="muted">NO BRAIN</Badge>
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
              <ConfidenceRing value={Math.round(agent.accuracy * 100)} size={64} label="accuracy" />
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
    </Card>
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

function DebateCardComponent({ debate, delay }: { debate: DebateEntry; delay: number }) {
  const dirColor = debate.consensus_direction === 'bullish' ? C.bull
    : debate.consensus_direction === 'bearish' ? C.bear : C.muted;
  const agreementColor = debate.agreement_score >= 0.7 ? C.bull
    : debate.agreement_score >= 0.5 ? C.warn : C.bear;
  const dirVariant = debate.consensus_direction === 'bullish' ? 'bull' as const
    : debate.consensus_direction === 'bearish' ? 'bear' as const : 'muted' as const;

  return (
    <Card glass delay={delay} style={{ padding: SP[4] }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Badge variant={dirVariant}>{debate.consensus_direction.toUpperCase()}</Badge>
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
      apiFetch<any>('/v1/agents/overview'),
      apiFetch<any>('/v1/agents/debate/history?limit=10'),
      apiFetch<any>('/v1/agents/team/calibration'),
    ]).then(([overview, debateHistory, team]) => {
      setAgents(overview?.agents || []);
      setDebates(debateHistory?.items || []);
      setTeamCal(team?.agents || null);
      setLoading(false);
    });
  }, []);

  // Load detail when agent selected
  useEffect(() => {
    if (!selectedAgent) return;
    Promise.all([
      apiFetch<any>(`/v1/agents/${selectedAgent}/performance`),
      apiFetch<any>(`/v1/agents/${selectedAgent}/calibration`),
    ]).then(([perf, cal]) => {
      setAgentPerf(perf);
      setCalibration(cal?.curve || null);
    });
  }, [selectedAgent]);

  return (
    <>
      <Head><title>Agent Intelligence | WAGMI</title></Head>
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25 }}
        style={{ background: C.bg, minHeight: '100vh', padding: '24px 16px', maxWidth: 1200, margin: '0 auto', position: 'relative', overflow: 'hidden' }}
      >


        {/* Header */}
        <motion.div
          variants={fadeUp}
          initial="hidden"
          animate="show"
          style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}
        >
          <div>
            <h1 style={{ fontSize: F.xl, fontWeight: 800, color: C.text, margin: 0 }}>
              Agent Intelligence
            </h1>
            <p style={{ fontSize: F.sm, color: C.muted, margin: '4px 0 0' }}>
              Per-agent brains, calibration, debate outcomes, team performance
            </p>
          </div>
          <Link href="/ai-decisions" style={{ fontSize: F.sm, color: C.brand, textDecoration: 'none' }}>
            Decision Feed &rarr;
          </Link>
        </motion.div>

        {/* Brain topology — visual anchor */}
        <Card glass delay={0.05} style={{ padding: SP[4], marginBottom: SP[4] }}>
          <SectionHeader label="Brain Topology" />
          <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0' }}>
            <AgentBrainGraphic width={700} height={280} />
          </div>
          <div style={{
            fontSize: 11,
            color: C.muted,
            textAlign: 'center',
            marginTop: 8,
            fontFamily: 'JetBrains Mono, monospace',
            letterSpacing: 0.5,
          }}>
            CLASSIFY → DECIDE → LEARN & MONITOR
          </div>
        </Card>


        {/* Team Calibration Summary */}
        {teamCal && Object.keys(teamCal).length > 0 && (
          <Card glass delay={0.1} style={{ padding: SP[4], marginBottom: SP[4] }}>
            <SectionHeader label="Team Calibration Overview" />
            <Grid minChildWidth={140} gap={2}>
              {Object.entries(teamCal).map(([role, data]) => (
                <div key={role} style={{ padding: 8, ...Glass.card, borderRadius: R.md }}>
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
            </Grid>
          </Card>
        )}

        {/* Agent Grid */}
        <SectionHeader label="Agent Overview" />
        <motion.div
          variants={orchestratedContainer}
          initial="hidden"
          animate="show"
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
            gap: 12, marginBottom: 24,
          }}
        >
          {loading ? (
            <Card glass style={{ padding: SP[4] }}>
              <Stack gap={2}>
                <Skeleton w="60%" h={14} />
                <Skeleton w="100%" h={60} />
              </Stack>
            </Card>
          ) : agents.length === 0 ? (
            <div style={{ gridColumn: '1 / -1' }}>
              <EmptyState
                icon="\u{1F916}"
                title="No agent data yet"
                subtitle="Enable LLM_MULTI_AGENT=true and run trades."
              />
            </div>
          ) : (
            agents.map((agent, i) => (
              <motion.div key={agent.role} variants={fadeUp}>
                <AgentCard
                  agent={agent}
                  delay={i * 0.06}
                  onClick={() => setSelectedAgent(agent.role === selectedAgent ? null : agent.role)}
                />
              </motion.div>
            ))
          )}
        </motion.div>

        {/* Agent Detail Panel */}
        {selectedAgent && agentPerf && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
          >
            <Card glass accent={roleColor(selectedAgent)} style={{ padding: SP[5], marginBottom: 24 }}>
              <SectionHeader label={`${roleIcon(selectedAgent)} ${selectedAgent.toUpperCase()} Agent — Detailed Performance`} />
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
                      <motion.div
                        key={i}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: i * 0.05 }}
                        style={{
                          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                          padding: '4px 8px', ...Glass.card, borderRadius: R.sm, fontSize: F.xs,
                        }}
                      >
                        <span style={{ color: C.textSub }}>{d.regime || '\u2014'}</span>
                        <Badge variant={d.was_correct ? 'bull' : 'bear'}>
                          {d.was_correct ? 'CORRECT' : 'WRONG'}
                        </Badge>
                        <span style={{ color: C.muted }}>{d.confidence ? `${Math.round(d.confidence * 100)}%` : '\u2014'}</span>
                      </motion.div>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          </motion.div>
        )}

        {/* Debate History */}
        <div style={{ marginBottom: 24 }}>
          <SectionHeader label="Recent Debates" />
          {debates.length === 0 ? (
            <EmptyState
              icon="\u2696\uFE0F"
              title="No debates yet"
              subtitle="Debates trigger when agents disagree on direction."
            />
          ) : (
            <motion.div
              variants={orchestratedContainer}
              initial="hidden"
              animate="show"
              style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
            >
              {debates.map((debate, i) => (
                <motion.div key={i} variants={fadeUp}>
                  <DebateCardComponent debate={debate} delay={i * 0.04} />
                </motion.div>
              ))}
            </motion.div>
          )}
        </div>

        {/* Footer nav */}
        <motion.div
          variants={fadeUp}
          initial="hidden"
          animate="show"
          transition={{ delay: 0.4 }}
          style={{ display: 'flex', gap: 12, justifyContent: 'center', padding: '16px 0' }}
        >
          {[
            { href: '/', label: 'Home' },
            { href: '/ai-decisions', label: 'Decisions' },
            { href: '/forensics', label: 'Forensics' },
            { href: '/performance', label: 'Performance' },
          ].map(({ href, label }) => (
            <Link key={href} href={href} style={{ fontSize: F.sm, color: C.muted, textDecoration: 'none' }}>{label}</Link>
          ))}
        </motion.div>
      </motion.div>
    </>
  );
}
