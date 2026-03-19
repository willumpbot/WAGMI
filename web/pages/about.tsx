import React, { useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import Layout from '../components/Layout';
import { C, R, S, F } from '../src/theme';

// ─── Accordion ────────────────────────────────────────────────────────────────

function FAQ({ q, a }: { q: string; a: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ border: `1px solid ${open ? C.borderBright : C.border}`, borderRadius: R.md, marginBottom: 8, overflow: 'hidden' }}>
      <button onClick={() => setOpen((v) => !v)} style={{
        width: '100%', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '14px 18px', background: C.card, border: 'none', cursor: 'pointer', textAlign: 'left', gap: 12,
      }}>
        <span style={{ fontSize: F.sm, fontWeight: 600, color: C.text }}>{q}</span>
        <span style={{ color: C.muted, flexShrink: 0, fontSize: F.lg, transition: 'transform 0.15s', transform: open ? 'rotate(45deg)' : 'none' }}>+</span>
      </button>
      {open && (
        <div style={{ padding: '0 18px 16px', fontSize: F.sm, color: C.textSub, lineHeight: 1.7, background: C.card, borderTop: `1px solid ${C.border}` }}>
          {a}
        </div>
      )}
    </div>
  );
}

// ─── Section ──────────────────────────────────────────────────────────────────

function Section({ id, eyebrow, title, children }: { id?: string; eyebrow: string; title: string; children: React.ReactNode }) {
  return (
    <div id={id} style={{ marginBottom: 60, scrollMarginTop: 80 }}>
      <div style={{ fontSize: F.xs, color: C.brand, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>{eyebrow}</div>
      <h2 style={{ margin: '0 0 24px', fontSize: F['2xl'], fontWeight: 800, color: C.text }}>{title}</h2>
      {children}
    </div>
  );
}

// ─── Agent Card ───────────────────────────────────────────────────────────────

type AgentSpec = { name: string; model: string; cost: string; role: string; decides: string; color: string };
const AGENTS: AgentSpec[] = [
  { name: 'Regime Agent', model: 'Claude Haiku', cost: '~$0.0001/call', role: 'Classifies current market conditions', decides: 'Is this trending, ranging, volatile, or panic? What\'s the directional bias?', color: C.info },
  { name: 'Trade Agent', model: 'Claude Sonnet', cost: '~$0.003/call', role: 'Forms the directional thesis', decides: 'Should the bot go long, short, or skip? What\'s the entry rationale?', color: C.brand },
  { name: 'Risk Agent', model: 'Claude Haiku', cost: '~$0.0001/call', role: 'Sizes the position and flags risks', decides: 'How much capital to deploy? What leverage? Any portfolio concentration concerns?', color: C.warn },
  { name: 'Critic Agent', model: 'Claude Sonnet', cost: '~$0.003/call', role: 'Stress-tests the thesis with a counter-argument', decides: 'What could go wrong? Must provide a counter-thesis. Can VETO the trade.', color: C.purple },
  { name: 'Learning Agent', model: 'Claude Haiku', cost: '~$0.0001/call', role: 'Post-trade pattern extraction', decides: 'What did this trade teach us? Update hypothesis accuracy tracking.', color: C.bull },
  { name: 'Exit Agent', model: 'Claude Haiku', cost: '~$0.0001/call', role: 'Monitors open positions continuously', decides: 'Is the thesis still valid? Recommend hold, adjust stop, or close early.', color: C.warnMid },
  { name: 'Scout Agent', model: 'Claude Haiku', cost: '~$0.0001/call', role: 'Idle-time setup preparation', decides: 'What setups are forming? Pre-score upcoming opportunities before they trigger.', color: C.muted },
];

// ─── Strategy Card ────────────────────────────────────────────────────────────

function StrategyCard({ name, desc, data, why }: { name: string; desc: string; data: string; why: string }) {
  return (
    <div style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: R.lg, padding: '20px 22px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
        <span style={{ fontSize: F.base, fontWeight: 700, color: C.text }}>{name}</span>
        <span style={{ fontSize: F.xs, padding: '2px 8px', borderRadius: R.pill, background: 'rgba(22,163,74,0.12)', color: C.bull, fontWeight: 700 }}>● LIVE</span>
      </div>
      <p style={{ margin: '0 0 10px', fontSize: F.sm, color: C.textSub, lineHeight: 1.6 }}>{desc}</p>
      <div style={{ fontSize: F.xs, color: C.muted, borderTop: `1px solid ${C.border}`, paddingTop: 10, marginTop: 10 }}>
        <div><strong style={{ color: C.textSub }}>Data:</strong> {data}</div>
        <div style={{ marginTop: 4 }}><strong style={{ color: C.textSub }}>Why it works:</strong> {why}</div>
      </div>
    </div>
  );
}

// ─── Gate Step ────────────────────────────────────────────────────────────────

function GateStep({ n, title, desc }: { n: number; title: string; desc: string }) {
  return (
    <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
      <div style={{ flexShrink: 0, width: 28, height: 28, borderRadius: '50%', background: C.brand, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: F.xs, fontWeight: 800, color: '#fff' }}>{n}</div>
      <div>
        <div style={{ fontSize: F.sm, fontWeight: 700, color: C.text, marginBottom: 2 }}>{title}</div>
        <div style={{ fontSize: F.xs, color: C.muted, lineHeight: 1.5 }}>{desc}</div>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function AboutPage() {
  return (
    <Layout>
      <Head>
        <title>About WAGMI — How It Works</title>
        <meta name="description" content="WAGMI doesn't have a black box. It has an audit trail. Learn about the 4 strategies, 7 AI agents, and the risk management system that protects your capital." />
      </Head>

      <div style={{ maxWidth: 860, margin: '0 auto', padding: '32px 20px' }}>

        {/* ── Hero ── */}
        <div style={{ textAlign: 'center', marginBottom: 60 }}>
          <h1 style={{ margin: '0 0 14px', fontSize: F['3xl'], fontWeight: 900, color: C.text, letterSpacing: -0.5, lineHeight: 1.15 }}>
            Built in public.<br />Every trade logged.<br />Every decision explained.
          </h1>
          <p style={{ margin: 0, fontSize: F.lg, color: C.muted, maxWidth: 520, marginLeft: 'auto', marginRight: 'auto', lineHeight: 1.6 }}>
            WAGMI doesn't have a black box. It has an audit trail.
          </p>
        </div>

        {/* ── Stats Hero Bar ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14, marginBottom: 60 }}>
          {[
            { value: '$0.0067', label: 'per decision', color: C.brand },
            { value: '23%', label: 'veto rate', color: C.bear },
            { value: '7', label: 'AI agents', color: C.brand },
            { value: '6', label: 'risk gates', color: C.bull },
          ].map(({ value, label, color }) => (
            <div key={label} style={{
              background: C.card,
              border: `1px solid ${color}30`,
              borderRadius: R.lg,
              padding: '20px 16px',
              textAlign: 'center',
              boxShadow: `0 0 0 0 transparent`,
            }}>
              <div style={{ fontSize: F['3xl'], fontWeight: 900, color, lineHeight: 1.1, marginBottom: 6 }}>{value}</div>
              <div style={{ fontSize: F.xs, color: C.muted, textTransform: 'uppercase', letterSpacing: 1, fontWeight: 600 }}>{label}</div>
            </div>
          ))}
        </div>

        {/* ── Problem ── */}
        <Section eyebrow="Why We Built This" title="Most trading bots are black boxes.">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
            <div style={{ background: 'rgba(220,38,38,0.06)', border: `1px solid ${C.bear}30`, borderRadius: R.lg, padding: '20px 22px' }}>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: C.bear, marginBottom: 12 }}>✗ How most bots work</div>
              {['Signal appears. No explanation.', 'Algorithm fires. You don\'t know why.', 'Trade loses. Zero insight.', 'Risk management? A black-box number.', 'You trust blindly — or you don\'t.'].map((t) => (
                <div key={t} style={{ fontSize: F.sm, color: C.muted, marginBottom: 6, display: 'flex', gap: 8 }}>
                  <span style={{ color: C.bear }}>×</span> {t}
                </div>
              ))}
            </div>
            <div style={{ background: 'rgba(22,163,74,0.06)', border: `1px solid ${C.bull}30`, borderRadius: R.lg, padding: '20px 22px' }}>
              <div style={{ fontSize: F.sm, fontWeight: 700, color: C.bull, marginBottom: 12 }}>✓ How WAGMI works</div>
              {['Every signal logged with full reasoning.', 'Every AI decision auditable at /ai-decisions.', 'Every loss analysed and explained.', 'Risk gates are documented and inspectable.', 'Transparency is the product.'].map((t) => (
                <div key={t} style={{ fontSize: F.sm, color: C.textSub, marginBottom: 6, display: 'flex', gap: 8 }}>
                  <span style={{ color: C.bull }}>✓</span> {t}
                </div>
              ))}
            </div>
          </div>
        </Section>

        {/* ── Strategies ── */}
        <Section id="strategies" eyebrow="The Signal Engine" title="4 strategies vote on every trade.">
          <p style={{ margin: '0 0 20px', color: C.muted, fontSize: F.sm, lineHeight: 1.7 }}>
            No single strategy trades alone. All four must vote, and a confidence threshold must be reached before any order is placed. Disagreement = skip.
          </p>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: 14 }}>
            <StrategyCard name="Regime Trend" desc="Follows established trends on 1h and 6h timeframes, using multiple moving averages and momentum indicators." data="1h, 6h candles via Hyperliquid" why="Trend continuation is the highest-probability setup when regime is confirmed." />
            <StrategyCard name="Monte Carlo Zones" desc="Uses Monte Carlo simulation to build support and resistance zones from daily price action. Defines accumulation and distribution regions." data="Daily candles" why="Probabilistic zones outperform static % levels because they adapt to each asset's actual volatility." />
            <StrategyCard name="Confidence Scorer" desc="Multi-factor scoring system: RSI, VWAP, ATR, trend alignment, volume confirmation. Outputs a 0–100 score." data="Multiple timeframes" why="Aggregating weak signals into a composite score reduces false positives vs any single indicator." />
            <StrategyCard name="Multi-Tier Quality" desc="Checks signal quality across short (5m) and medium (1h) timeframes. Filters out setups that lack multi-timeframe alignment." data="5m, 1h candles" why="A signal that looks good on 1h but bad on 5m is often entering at a local peak. MTF filters this." />
          </div>
        </Section>

        {/* ── Agents ── */}
        <Section id="agents" eyebrow="The AI Brain" title="7 agents debate every trade.">
          <p style={{ margin: '0 0 24px', color: C.muted, fontSize: F.sm, lineHeight: 1.7 }}>
            Each agent has a specific role and is prevented from stepping outside it. The Critic must provide a counter-thesis before vetoing — vague objections are not allowed.
          </p>
          {/* ── Pipeline Diagram ── */}
          <div style={{ overflowX: 'auto', marginBottom: 28 }}>
            {/* Pre-Trade Pipeline */}
            <div style={{ marginBottom: 6 }}>
              <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>Pre-Trade Pipeline</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 0, minWidth: 720 }}>
                {/* Signal source */}
                <div style={{
                  flexShrink: 0,
                  background: C.surface,
                  border: `1px solid ${C.border}`,
                  borderRadius: R.md,
                  padding: '10px 14px',
                  textAlign: 'center',
                  minWidth: 72,
                }}>
                  <div style={{ fontSize: 16, marginBottom: 2 }}>📊</div>
                  <div style={{ fontSize: F.xs, fontWeight: 700, color: C.textSub }}>Signal</div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>4 strategies</div>
                </div>

                {/* Arrow */}
                <div style={{ flex: '0 0 20px', textAlign: 'center', color: C.muted, fontSize: F.base }}>→</div>

                {/* Regime */}
                <div style={{
                  flexShrink: 0,
                  background: `linear-gradient(135deg, ${C.info}22, ${C.info}10)`,
                  border: `1px solid ${C.info}40`,
                  borderRadius: R.md,
                  padding: '10px 14px',
                  textAlign: 'center',
                  minWidth: 84,
                }}>
                  <div style={{ fontSize: 16, marginBottom: 2 }}>🌐</div>
                  <div style={{ fontSize: F.xs, fontWeight: 700, color: C.info }}>Regime</div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>Haiku</div>
                </div>

                {/* Arrow */}
                <div style={{ flex: '0 0 20px', textAlign: 'center', color: C.muted, fontSize: F.base }}>→</div>

                {/* Trade */}
                <div style={{
                  flexShrink: 0,
                  background: `linear-gradient(135deg, ${C.brand}22, ${C.brand}10)`,
                  border: `1px solid ${C.brand}40`,
                  borderRadius: R.md,
                  padding: '10px 14px',
                  textAlign: 'center',
                  minWidth: 84,
                }}>
                  <div style={{ fontSize: 16, marginBottom: 2 }}>🧠</div>
                  <div style={{ fontSize: F.xs, fontWeight: 700, color: C.brand }}>Trade</div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>Sonnet</div>
                </div>

                {/* Arrow */}
                <div style={{ flex: '0 0 20px', textAlign: 'center', color: C.muted, fontSize: F.base }}>→</div>

                {/* Risk */}
                <div style={{
                  flexShrink: 0,
                  background: `linear-gradient(135deg, ${C.warn}22, ${C.warn}10)`,
                  border: `1px solid ${C.warn}40`,
                  borderRadius: R.md,
                  padding: '10px 14px',
                  textAlign: 'center',
                  minWidth: 84,
                }}>
                  <div style={{ fontSize: 16, marginBottom: 2 }}>🛡️</div>
                  <div style={{ fontSize: F.xs, fontWeight: 700, color: C.warn }}>Risk</div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>Haiku</div>
                </div>

                {/* Arrow */}
                <div style={{ flex: '0 0 20px', textAlign: 'center', color: C.muted, fontSize: F.base }}>→</div>

                {/* Critic */}
                <div style={{
                  flexShrink: 0,
                  background: `linear-gradient(135deg, ${C.purple}22, ${C.purple}10)`,
                  border: `1px solid ${C.purple}40`,
                  borderRadius: R.md,
                  padding: '10px 14px',
                  textAlign: 'center',
                  minWidth: 84,
                }}>
                  <div style={{ fontSize: 16, marginBottom: 2 }}>⚖️</div>
                  <div style={{ fontSize: F.xs, fontWeight: 700, color: C.purple }}>Critic</div>
                  <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>Sonnet</div>
                </div>

                {/* Arrow */}
                <div style={{ flex: '0 0 20px', textAlign: 'center', color: C.muted, fontSize: F.base }}>→</div>

                {/* Fork: Execute or Veto */}
                <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div style={{
                    background: `linear-gradient(135deg, ${C.bull}25, ${C.bull}10)`,
                    border: `1px solid ${C.bull}50`,
                    borderRadius: R.md,
                    padding: '8px 12px',
                    textAlign: 'center',
                    minWidth: 90,
                  }}>
                    <div style={{ fontSize: F.xs, fontWeight: 800, color: C.bull }}>✓ EXECUTE</div>
                  </div>
                  <div style={{
                    background: `linear-gradient(135deg, ${C.bear}22, ${C.bear}10)`,
                    border: `1px solid ${C.bear}50`,
                    borderRadius: R.md,
                    padding: '8px 12px',
                    textAlign: 'center',
                    minWidth: 90,
                  }}>
                    <div style={{ fontSize: F.xs, fontWeight: 800, color: C.bear }}>✗ VETO</div>
                  </div>
                </div>
              </div>
            </div>

            {/* Ongoing Agents */}
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: F.xs, color: C.muted, fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 10 }}>Ongoing Agents</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 720 }}>
                {[
                  { emoji: '📚', name: 'Learning', sub: 'post-trade', color: C.bull },
                  { emoji: '👁️', name: 'Exit', sub: 'monitors positions', color: C.warnMid },
                  { emoji: '🔭', name: 'Scout', sub: 'idle preparation', color: C.muted },
                ].map(({ emoji, name, sub, color }) => (
                  <div key={name} style={{
                    background: `linear-gradient(135deg, ${color}15, ${color}08)`,
                    border: `1px dashed ${color}50`,
                    borderRadius: R.md,
                    padding: '10px 16px',
                    textAlign: 'center',
                    minWidth: 110,
                  }}>
                    <div style={{ fontSize: 16, marginBottom: 2 }}>{emoji}</div>
                    <div style={{ fontSize: F.xs, fontWeight: 700, color }}>{name}</div>
                    <div style={{ fontSize: 10, color: C.muted, marginTop: 1 }}>{sub}</div>
                  </div>
                ))}
                <div style={{ fontSize: F.xs, color: C.faint, fontStyle: 'italic', paddingLeft: 4 }}>run async — not on critical path</div>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {AGENTS.map((a) => (
              <div key={a.name} style={{ background: C.card, border: `1px solid ${a.color}30`, borderRadius: R.lg, padding: '16px 20px', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
                <div style={{ flexShrink: 0, minWidth: 160 }}>
                  <div style={{ fontSize: F.sm, fontWeight: 800, color: a.color }}>{a.name}</div>
                  <div style={{ fontSize: F.xs, color: C.muted, marginTop: 2 }}>Model: {a.model}</div>
                  <div style={{ fontSize: F.xs, color: C.faint, marginTop: 1 }}>{a.cost}</div>
                </div>
                <div style={{ flex: 1, minWidth: 200 }}>
                  <div style={{ fontSize: F.sm, color: C.textSub, marginBottom: 4 }}>{a.role}</div>
                  <div style={{ fontSize: F.xs, color: C.muted, lineHeight: 1.5 }}><strong style={{ color: C.textSub }}>Decides:</strong> {a.decides}</div>
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 16, padding: '12px 16px', background: `${C.purple}10`, border: `1px solid ${C.purple}30`, borderRadius: R.md, fontSize: F.sm, color: C.textSub }}>
            Total cost per entry decision: ~$0.0067. The Critic vetoed 23% of signals last month — those would have been marginal setups, not the high-conviction trades. That's the system working.
          </div>
          <div style={{ marginTop: 12 }}>
            <Link href="/llm-audit" style={{ fontSize: F.sm, color: C.brand, fontWeight: 600, textDecoration: 'none' }}>See every AI decision logged →</Link>
          </div>
        </Section>

        {/* ── Risk Management ── */}
        <Section id="risk" eyebrow="Risk Management" title="The bot can stop itself.">
          <p style={{ margin: '0 0 20px', color: C.muted, fontSize: F.sm, lineHeight: 1.7 }}>
            Every trade passes through 6 sequential gates. A signal must pass all 6 to become an order. The gates are hard-coded — they cannot be disabled from the UI.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16, marginBottom: 24 }}>
            <GateStep n={1} title="Signal Validity" desc="Is the signal well-formed? Valid SL/TP, stop width ≥ 0.3% of entry, R:R ≥ 1.0. Nonsensical trades rejected here." />
            <GateStep n={2} title="Circuit Breaker" desc="Has the bot lost more than X% today, or had N consecutive losses? If yes, trading pauses until the next session." />
            <GateStep n={3} title="Position Limits" desc="Maximum simultaneous positions enforced. Prevents over-exposure to correlated assets." />
            <GateStep n={4} title="Leverage Check" desc="Leverage is capped based on confidence score, strategy agreement, and market regime. High volatility = lower cap." />
            <GateStep n={5} title="Liquidation Safety" desc="The liquidation price must be below the stop loss level (for longs) by a safe margin. Near-liquidation trades are rejected." />
            <GateStep n={6} title="Position Sizing" desc="Final size = 1.5% of current equity ÷ stop distance. Never more than 1.5% of capital at risk on any single trade." />
          </div>
          <div style={{ background: `${C.bull}08`, border: `1px solid ${C.bull}25`, borderRadius: R.lg, padding: '14px 18px', fontSize: F.sm, color: C.textSub }}>
            <strong style={{ color: C.bull }}>The result:</strong> Even in the worst realistic scenario — all open positions hit their stops simultaneously — you lose at most 4.5% of capital in one session. The daily loss circuit breaker triggers long before that.
          </div>
        </Section>

        {/* ── Transparency Commitments ── */}
        <Section eyebrow="Our Commitments" title="What we promise.">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {[
              { n: '1', text: 'Every closed trade is logged and public at /forensics — including losses.', href: '/forensics' },
              { n: '2', text: 'Every AI decision is auditable at /llm-audit — model, reasoning, veto history.', href: '/llm-audit' },
              { n: '3', text: 'Drawdown is reported in real-time at /performance — no cherry-picking periods.', href: '/performance' },
              { n: '4', text: 'No cherry-picked results — all trades included. All losses shown. One ledger.', href: null },
              { n: '5', text: 'Model costs are disclosed — we\'re not hiding that we use Claude to think.', href: null },
            ].map(({ n, text, href }) => (
              <div key={n} style={{ display: 'flex', gap: 14, padding: '12px 16px', background: C.card, borderRadius: R.md, border: `1px solid ${C.border}`, alignItems: 'flex-start' }}>
                <span style={{ flexShrink: 0, width: 24, height: 24, borderRadius: '50%', background: C.bull + '20', color: C.bull, fontWeight: 800, fontSize: F.xs, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>{n}</span>
                <span style={{ fontSize: F.sm, color: C.textSub, lineHeight: 1.5 }}>
                  {text} {href && <Link href={href} style={{ color: C.brand, fontWeight: 600, textDecoration: 'none' }}>View →</Link>}
                </span>
              </div>
            ))}
          </div>
        </Section>

        {/* ── FAQ ── */}
        <Section eyebrow="FAQ" title="Honest answers.">
          <FAQ q="Is this financial advice?" a="No. WAGMI is a market analysis tool. Every signal is for informational purposes only. You are responsible for all trading decisions." />
          <FAQ q="What happens if the bot loses money?" a={<>Circuit breakers activate automatically. A daily loss cap stops trading for the session. After N consecutive losses, the bot pauses until conditions improve. These limits are hard-coded and visible in <Link href="/learn" style={{ color: C.brand }}>the course</Link>.</>} />
          <FAQ q="Can I lose more than I put in?" a="On Hyperliquid, your loss is capped at your margin. The bot's liquidation gate (Gate 5) ensures the stop loss is always triggered before liquidation, so you exit at your stop, not at liquidation price." />
          <FAQ q="How do I know the results are real?" a={<>Every trade is timestamped and logged at <Link href="/forensics" style={{ color: C.brand }}>/forensics</Link>. Entry, exit, time, P&L — all there. We include the losers.</>} />
          <FAQ q="What's the difference between paper and live trading?" a="Paper trading executes at market prices on Hyperliquid testnet infrastructure — the signals are identical to live. Real money has not been deployed yet. When we go live, you'll see it." />
          <FAQ q="Which exchange does this run on?" a="Hyperliquid. We chose it for its deep liquidity on perps, zero maker fees, and on-chain settlement. The API is fast enough for scalp-level execution." />
          <FAQ q="Why Claude (Anthropic) and not GPT-4?" a="Claude's longer context window and lower hallucination rate on structured tasks made it the right fit. We tested both extensively. Claude also has strong JSON mode compliance which matters for the agent pipeline." />
          <FAQ q="How much does it cost to run this per month?" a="LLM costs run approximately $0.007 per full trade decision cycle. For a bot analyzing 50 signals per day, that's ~$10/month in AI costs. This is disclosed at /llm-audit." />
          <FAQ q="How do I start?" a={<>Start at <Link href="/copy-trade" style={{ color: C.brand }}>Trade This</Link> to see live signals, or <Link href="/learn" style={{ color: C.brand }}>Understand the Edge</Link> to learn the system first.</>} />
        </Section>

        {/* ── CTA ── */}
        <div style={{ textAlign: 'center', padding: '24px 0 8px' }}>
          <h2 style={{ margin: '0 0 12px', fontSize: F['2xl'], fontWeight: 800, color: C.text }}>Ready to see it in action?</h2>
          <p style={{ margin: '0 0 24px', color: C.muted, fontSize: F.sm }}>Every claim on this page is auditable. Start with the track record.</p>
          <div style={{ display: 'flex', gap: 12, justifyContent: 'center', flexWrap: 'wrap' }}>
            <Link href="/forensics" style={{ padding: '10px 22px', background: C.brand, color: '#fff', borderRadius: R.md, fontSize: F.sm, fontWeight: 700, textDecoration: 'none' }}>
              See Every Trade →
            </Link>
            <Link href="/llm-audit" style={{ padding: '10px 22px', border: `1px solid ${C.border}`, color: C.textSub, borderRadius: R.md, fontSize: F.sm, fontWeight: 600, textDecoration: 'none' }}>
              Audit the AI →
            </Link>
          </div>
        </div>
      </div>
    </Layout>
  );
}
