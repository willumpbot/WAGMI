# /live — The Manual Trader Co-Pilot — Design Spec

**Source:** user direction 2026-04-29 ("streamline a feature that shows live mechanical | live agentic | combined synthesis, helps the manual trader thoroughly, and lets them ask the agentic system questions")

This is the **single most differentiated feature** in WAGMI. It exposes both layers of the system (the deterministic ensemble pipeline and the LLM agent pipeline) side-by-side, plus a synthesized recommendation, plus an interactive Q&A — all aimed at helping a human trader make better decisions, not at replacing them.

## Core Positioning

WAGMI's bot is unique because it has *two parallel decision systems*:

- **Mechanical:** 23 strategies → ensemble vote → gate stack (rules, regime, calibration) → output
- **Agentic:** Regime → Trade → Risk → Critic → output

Most products expose only one. Showing both, with the points of agreement and disagreement made visible, gives a manual trader more information than either system alone.

The page is **not** "watch the bot trade." It's "two senior traders sitting next to me — one is a quant, one is a discretionary trader — and I can see their work and ask them questions."

## Layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Symbol pills: [BTC] [ETH] [SOL] [HYPE]   [+] All Symbols (scoreboard view)  │
│ Mode: ⚪ Live  ⚪ Replay [date/time]                                         │
├─────────────────────────────────────────────────────────────────────────────┤
│ ┌─ Mechanical ──────┐ ┌─ Agentic ─────────┐ ┌─ Synthesis ───────────────┐ │
│ │ Ensemble vote     │ │ Regime Agent      │ │ Final action              │ │
│ │ Strategy votes    │ │ Trade Agent       │ │ Sized conviction          │ │
│ │ Confluence score  │ │ Risk Agent        │ │ One-line summary          │ │
│ │ Active gates      │ │ Critic Agent      │ │ Disagreement flags ⚠      │ │
│ │ Regime cohort     │ │ Per-agent calib   │ │ Trust gauge               │ │
│ │ TOD cohort        │ │ Token cost        │ │ Manual-trader helpers:    │ │
│ │ Edge map          │ │                   │ │   suggested size          │ │
│ │ "No-LLM verdict"  │ │ "AI-only verdict" │ │   alt scenarios           │ │
│ │                   │ │                   │ │   key questions to ask    │ │
│ └───────────────────┘ └───────────────────┘ └───────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────────┤
│ ┌─ Ask the agents ──────────────────────────────────────────────────────┐ │
│ │ > Should I close my SOL long if BTC breaks below 60k?                 │ │
│ │ Trade Agent: ...  Critic: ...  Risk Agent: ...   [send / clear]       │ │
│ └───────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

When **All Symbols** mode is active, the three columns become three rows × N columns (one column per symbol), giving a scoreboard view.

## Column Contents

### Mechanical (left)

Pulled from `/v1/signals` + `/v1/forensics/analysis` + (eventually) `/v1/rules/active`.

- **Ensemble vote panel:** "3 LONG, 1 SHORT, 5 FLAT — weighted veto says LONG 72%"
- **Strategy table:** each of ~23 strategies as rows, side + confidence + ensemble weight + recent WR
- **Confluence score:** number of agreeing strategies × weighted by individual track records
- **Active gates:** confidence floor (current value), regime block status, hard-block rules in effect, time-of-day cohort filter, consecutive-loss circuit breaker state
- **Regime cohort:** current regime classification + historical WR in this regime for this symbol
- **TOD cohort:** current hour bucket + historical WR in this bucket
- **Edge map mini:** symbol × side WR/PnL grid, current cell highlighted
- **No-LLM verdict:** the action the deterministic pipeline alone would take, with sized confidence

### Agentic (middle)

Pulled from `/v1/llm/feed` (most recent decision for symbol) + `/v1/agents/team/calibration` + `/v1/reasoning/pipeline/{id}`.

- **Regime Agent:** classification, confidence, regime probabilities (trending 0.6 / range 0.3 / panic 0.1), one-line reasoning
- **Trade Agent:** thesis (action, side, conviction), reasoning, top 2 supporting facts
- **Risk Agent:** size recommendation (% equity), leverage cap suggestion, risks flagged
- **Critic Agent:** agree / veto / counter-thesis, why-this-might-fail bullets
- **Per-agent calibration:** last 10 calls' accuracy bar
- **Cost:** tokens, model tier (Haiku / Sonnet / Opus)
- **AI-only verdict:** the action the LLM pipeline alone would take

### Synthesis (right)

Computed client-side or via a new `/v1/synthesis/{symbol}` endpoint.

- **Final action:** the combined output (mechanical + agentic with disagreement penalty)
- **Sized conviction:** scaled by agent agreement multiplier (full conviction × 1.0 if both agree, × 0.7 if mixed, × 0.4 if disagree)
- **One-line summary:** plain-English ("Long BTC, 60% of full size, both systems agree but Critic flags drawdown risk")
- **Disagreement flags:** loud red banner if columns disagree on direction, amber if they disagree on size, green if aligned
- **Trust gauge:** % agreement over last 30 decisions on this symbol
- **Manual-trader helpers** (the bottom of synthesis):
  - Suggested size at $X bankroll → "0.05 BTC at 3x = $150 risk"
  - Alternative scenarios → "if you want lower risk: 0.025 BTC at 2x"
  - Key questions to ask → 3-5 prompts pre-filled for the Q&A panel ("What if BTC breaks below the day's low?", "How does this trade do in a 1-hour reversal?")
  - Stop / target levels (mechanical's SL/TP1/TP2 + agent's adjusted variants)

## Ask-the-Agents Panel

A persistent chat interface at the bottom. Multi-turn.

- Operator types a question → server forwards to LLM (Sonnet by default) with current context (symbol, signal, position, market state) injected
- Each agent can be asked individually or all at once
- Three response styles:
  - **Trade Agent:** action-oriented, "I'd …", focused on entry/exit
  - **Critic Agent:** counter-thesis, "but consider …", focused on risk
  - **Risk Agent:** sizing-focused, "with current bankroll, no more than …"
- Pre-filled question buttons populate from synthesis's "key questions to ask"
- Conversation history persisted client-side (localStorage) per symbol

Backend: needs new `/v1/agents/ask` endpoint. Spec:

```
POST /v1/agents/ask
{
  "agent": "trade" | "risk" | "critic" | "regime" | "all",
  "question": "Should I close my SOL long if BTC breaks below 60k?",
  "context": {
    "symbol": "SOL",
    "side": "LONG",
    "entry": 145.32,
    "current_price": 142.10,
    "regime": "trending",
    "decision_id": "<optional, for replay context>"
  }
}

→ {
  "responses": [
    { "agent": "trade", "text": "...", "model": "sonnet", "cost_usd": 0.0023 }
  ],
  "elapsed_ms": 1840
}
```

Cost concern: this is an open token sink if not gated. Solutions:
- Rate limit per-symbol-per-minute (default 3 questions/min)
- Cap response length (300 tokens max)
- Cache identical-context-identical-question for 60s
- For paid users: lift rate limits, enable Opus

## Historical Replay Mode

Toggle: `Live` / `Replay`.

In Replay mode:
- Date/time picker at top
- All three columns render the state *as it existed at that point* — pulling from persisted decisions in `decisions.jsonl` and any time-stamped strategy/regime snapshots
- The Ask-Agents panel still works — the LLM gets the historical context as its "current state"
- Useful for: post-mortem analysis, learning from past trades, understanding regime transitions

Implementation note: this is "free" if we ensure the synthesis is computed from raw inputs (signals + agent outputs) at render time, not pre-computed and stored. Always recompute from the source data.

## Manual-Trader Mode (default UX)

The page assumes the operator is *trading by hand* — not just watching the bot. Implications:

- No buy/sell buttons (we don't execute for them)
- Size suggestions are *informational*, with explicit "this is what the bot would do; you decide"
- Help with sizing math: "you said you have $5,000 bankroll, 1% risk = $50, current SL distance is 1.8% → max position $2,778 at 1x or $556 at 5x"
- Help with timing: "current regime is trending, current hour is morning UTC — both favor entries. If both flip ranging/night, consider exiting."
- Help with exit decisions: explicit "if you're already in this trade, here's what each system would do now"
- Built-in "panic button" — clicking it asks all 3 agents "I want to close this trade; talk me through whether that's wise" — surfaces the full reasoning before the user clicks anything

## Premium Gating

The full feature lives behind paid gating eventually. Free tier sees:
- Mechanical column (real-time, full data)
- Synthesis column (real-time, with sized conviction)
- One question per hour to the agents
- 7-day replay history

Paid tier sees:
- Agentic column (full agent breakdown)
- Unlimited questions
- Multi-symbol scoreboard view
- Full replay history (months back)
- Opus-tier responses

Implementation: gate via the `auth` middleware in Phase 8. For now, build the UI assuming full access.

## Build Order

1. **Page skeleton** — `/live` route, three empty columns, symbol pills, mode toggle. Routes work, layout right.
2. **Mechanical column** — wire to `/v1/signals` + edge stats. Show ensemble vote, gates, cohorts. Lots of data already available.
3. **Agentic column** — wire to `/v1/llm/feed` + `/v1/reasoning/pipeline`. Show agent ladder.
4. **Synthesis column** — compute client-side from the two columns. Show disagreement flag, sized conviction, manual-trader helpers.
5. **Ask-Agents panel** — UI shell, localStorage persistence, mocked responses (just template strings) until backend exists.
6. **Backend `/v1/agents/ask`** — adds the endpoint to `bot/api_server.py`. Calls the existing agent pipeline with question + context.
7. **All Symbols mode** — scoreboard layout with smaller per-symbol cards.
8. **Replay mode** — date picker + state-rehydration logic.

Estimated scope: ~30 hours from skeleton to fully-working with backend. The UI shell (1-5) is ~12 hours and gives 80% of the visible value. Backend wiring (6) is the gating risk for the Q&A feature.

