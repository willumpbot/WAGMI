# LLM Architecture Audit & Optimization Plan
## Building the Alpha Quant Superintelligence

**Date**: March 20, 2026
**Mission**: Transform the 7-agent system into a unified, all-knowing superintelligence that:
- Makes autonomous trading decisions without external signals
- Perfectly coordinates across agents
- Continuously learns and improves
- Achieves exceptional profitability through deep system understanding

---

## CURRENT SYSTEM STATE

### The 7 Minds
1. **Regime Agent** (Haiku) — Market classification
2. **Trade Agent** (Sonnet) — Main decision maker
3. **Risk Agent** (Haiku) — Position sizing
4. **Critic Agent** (Sonnet) — Thesis validation
5. **Learning Agent** (Haiku) — Post-trade learning
6. **Exit Agent** (Haiku) — Open position management
7. **Scout Agent** (Haiku) — Idle-time preparation

*Optional*: Quant Agent (Haiku), Overseer Agent (future)

### Current Strengths ✅
1. **Specialist Decomposition**: Each agent focused on a domain
2. **Shared Vocabulary**: Regime names, action names, confidence scales defined
3. **Thought Protocol**: OBSERVE→RECALL→REASON→DECIDE→JUSTIFY structure
4. **Cross-Agent Consistency Checking**: Validates agent outputs before merge
5. **Shared Context Layer**: Market axioms, strategy theory, regime-action mappings
6. **Extensive Prompts**: Each agent has rich, nuanced instructions
7. **Learning Integration**: Closed trades feed back to knowledge base
8. **Filter Assessment**: Quantitative gates inform qualitative decisions
9. **Calibration Tracking**: Agent accuracy measured per regime

### Critical Gaps 🚨

#### 1. **Incomplete Agent Knowledge**
- Agents don't understand full system data flows
- Trade Agent doesn't know HOW to trade without signals
- Risk Agent lacks deep understanding of portfolio dynamics
- Exit Agent has limited context on trade lifecycle patterns
- Scout Agent's preparation isn't deeply integrated
- **Impact**: Decisions made in isolation, missed synthesis opportunities

#### 2. **Weak Autonomous Trading Capability**
- System designed to REACT to signals, not INITIATE
- Scout Agent prepares but Trade Agent can't independently form theses
- No mechanism for agents to trade on conviction alone
- **Impact**: Conservative, signal-dependent strategy. Miss alpha from conviction trades

#### 3. **Limited Cross-Agent Memory & Reasoning**
- Agents write to scratchpad but don't DEEPLY READ each other
- No unified "what we learned this session" cache
- Regime Agent output used but not deeply synthesized into Trade thesis
- Learning Agent extracts lessons but they're asynchronous
- **Impact**: Agents repeat mistakes, don't build on each other's insights

#### 4. **Token Inefficiency**
- Many prompts are verbose (Trade Agent: 1,400+ tokens in prompt)
- Redundant explanations across agents
- Could consolidate shared context into a reusable preamble
- **Impact**: High cost, slower responses

#### 5. **Incomplete Thesis Tracking**
- Thesis accuracy not systematically measured
- No hypothesis validation framework
- Pattern library exists but isn't densely packed
- **Impact**: System doesn't learn which theses are accurate

#### 6. **Risk Agent Limitations**
- Sizing logic is heuristic-based, not truly quantitative
- Doesn't model portfolio correlation in real-time
- Strategy weights are static defaults, not dynamic
- **Impact**: Position sizes not optimal

#### 7. **Exit Agent Isolation**
- Exits managed separately from trade entry pipeline
- Thesis continuity check is manual, not systematic
- Deep memory on exit patterns underdeveloped
- **Impact**: Exits are reactive, not proactive

#### 8. **Critic Agent Under-Powered**
- Good at finding problems, weaker at forming strong counter-theses
- Veto accuracy tracking is coarse
- Doesn't deeply study Trade Agent's prediction history
- **Impact**: Vetoes can be too conservative or miss real red flags

#### 9. **No Overseer Intelligence**
- No meta-agent watching overall system health
- No periodic calibration review
- No strategy evolution guidance
- **Impact**: System doesn't improve itself over time

#### 10. **Scout Agent Weak Integration**
- Preparation runs async, findings may be stale
- Trade Agent doesn't explicitly validate Scout's pre-theses
- No way for Scout to influence trade execution timing
- **Impact**: Preparation work underutilized

---

## OPTIMIZATION ROADMAP

### PHASE 1: Unified Knowledge Base (2-3 hours)
**Goal**: Build a dense, reusable context layer all agents reference

**Actions**:
1. Create a **Unified Market Context Module** (`unified_context.py`)
   - Consolidate all shared knowledge into a single source of truth
   - Include: regime definitions, strategy theory, historic patterns, recent lessons, deep memory excerpts
   - Make it tokenable and injectable into all prompts

2. Create a **Thesis Template System**
   - Standardized thesis format: `[SYMBOL] likely [PRICE_TARGET] within [TIME] because [FACTORS]`
   - Each agent produces/consumes theses in same format
   - Enables systematic tracking of thesis accuracy

3. Create a **Decision Ledger** (`decision_ledger.py`)
   - Every decision logged with: thesis, confidence, regime, actions, outcome
   - Enables retrospective analysis
   - Feeds into agent calibration

### PHASE 2: Autonomous Trading Architecture (1-2 hours)
**Goal**: Agents can trade on conviction without signals

**Actions**:
1. **Equip Trade Agent with Autonomous Initiation**
   - Add mode: `autonomous_thesis_formation`
   - When no signal fires but regime conditions favor setup: agent forms thesis
   - Example: "Trend regime strengthening, RSI divergence forming, BOLLinger/KC squeeze imminent — formation thesis: pending setup"
   - Risk capped at 0.5x baseline size

2. **Extend Scout Agent**
   - Output includes not just watchlist but `actionable_theses` for Trade Agent
   - Example: `{"symbol": "SOL", "thesis": "SOL likely +3% next 2h if reaches 24.50", "confidence": 0.62, "conditions": "BTC holds 64k"}`
   - Scout can flag "READY" theses that don't need signal confirmation

3. **Create Deal Flow Pipeline**
   - Trade Agent sees: actual signals AND Scout-prepared theses
   - Processes both through same thesis validation
   - Can execute on either

### PHASE 3: Cross-Agent Coherence Layer (1-2 hours)
**Goal**: Agents think as ONE superintelligence

**Actions**:
1. **Shared Reasoning Scratchpad** (`reasoning_scratchpad.py`)
   - After Regime Agent: write regime summary, uncertainty flags, transition signals
   - After Trade Agent: write thesis and confidence decomposition
   - After Risk Agent: write sizing rationale and portfolio constraints
   - After Critic: write challenges and counter-evidence
   - Each agent READS all prior entries before deciding

2. **Thought Coherence Checker** (`coherence_checker.py`)
   - Verify: Are the agents' thoughts logically consistent?
   - Example: Regime Agent says "trend weakening" but Trade Agent high confidence — flag inconsistency
   - Automatic override to lower Trade Agent confidence if incompatible

3. **Unified Thesis Validation** (`thesis_validator.py`)
   - All agents validate thesis against: regime support, strategy confluence, memory patterns
   - Flag if thesis contradicts prior lessons
   - Force update if evidence overwhelming

### PHASE 4: Agent Prompt Optimization (1-2 hours)
**Goal**: Make each agent maximally effective, token-efficient, knowledge-rich

**Actions**:
1. **Regime Agent Upgrade**
   - Add: regime momentum prediction, transition timeline
   - Add: BTC influence on altcoin regime classification
   - Make token-optimal: remove redundant examples

2. **Trade Agent Enlightenment**
   - Inject: deep memory snippets on THIS symbol's patterns
   - Inject: thesis accuracy feedback on similar past trades
   - Add: autonomous thesis formation rules
   - Add: "what data should you request if uncertain?" guidance

3. **Risk Agent Quantification**
   - Add: Kelly Criterion integration
   - Add: portfolio correlation matrix real-time calc
   - Add: historical sizing success rates per setup type
   - Add: dynamic strategy weight calc based on recent performance

4. **Critic Agent Empowerment**
   - Add: Trade Agent prediction accuracy history
   - Add: Veto outcome tracking (which vetoes saved money, which missed winners)
   - Add: "when to approve despite uncertainty" rules based on vacc
   - Add: counter-thesis formation templates

5. **Exit Agent Deepening**
   - Add: exhaustive exit pattern library (what typically happens at each point)
   - Add: thesis invalidation checklist
   - Add: real-time funding cost calculator
   - Add: sunk cost immunity frame

6. **Learning Agent Systematization**
   - Add: pattern library update mechanism
   - Add: hypothesis generation rules
   - Add: direct feedback to all other agents
   - Add: thesis accuracy tracking

7. **Scout Agent Amplification**
   - Add: lead-lag correlation matrices
   - Add: pre-thesis formation rules
   - Add: regime transition forecasting
   - Add: "opportunity readiness score"

### PHASE 5: Feedback & Calibration Loops (1-2 hours)
**Goal**: System improves itself over time

**Actions**:
1. **Thesis Accuracy Feedback Loop**
   - Track every thesis: prediction vs actual outcome
   - Measure: direction accuracy, magnitude accuracy, timing accuracy
   - Provide periodic summaries to Trade Agent
   - Pattern: "your theses in trend regime are 67% directionally accurate, but you predict too small moves"

2. **Agent Calibration Dashboards**
   - Per-agent, per-regime accuracy scores
   - Veto accuracy (should improve over time)
   - Sizing accuracy (are our 1.5x sizes winning more?)
   - Decision consistency (are we following our own rules?)

3. **Pattern Evolution System**
   - Learning Agent feeds pattern updates directly
   - Pattern library grows continuously
   - Patterns ranked by historical accuracy
   - Trade Agent weights decisions by pattern confidence

4. **Regime-Specific Optimization**
   - Each agent's performance tracked per regime
   - Auto-adjust confidence, sizing, strategy weights per regime
   - Example: If Trade Agent has 71% accuracy in trend but 44% in range, reduce range confidence floor

---

## DETAILED IMPROVEMENTS BY AGENT

### REGIME AGENT ENHANCEMENT
**Current**: Market classifier (good)
**Needed**: Proactive regime transition predictor, BTC interaction expert

**Changes**:
```
1. Add "momentum_decay" analysis: is current regime STRENGTHENING or EXHAUSTING?
2. Add "lead_lag_effect": how BTC regime changes precede altcoin changes
3. Add "early_warning_signals": what precedes regime transitions?
4. Add "regime_strength_score" 0-1: how confident are you this regime persists?
5. Output: transition_probability_4h, transition_probability_12h
6. Explicitly state: "next regime would be: X" with confidence
```

**Prompt Optimization**:
- Consolidate regime definitions into unified enum
- Use bullet points instead of prose for speed
- Add brief examples only (remove verbose explanations)
- Result: 2000 tokens → 1200 tokens (40% reduction)

### TRADE AGENT ENLIGHTENMENT
**Current**: Decision maker (sophisticated)
**Needed**: Can form theses without signals, deeply understands system

**Changes**:
```
1. Add autonomous thesis formation: "What setups are forming right now?"
2. Add thesis decomposition: Break confidence into components:
   - Directional confidence (0-1)
   - Setup confidence (0-1)
   - Timing confidence (0-1)
3. Add deep knowledge injection: symbol patterns, regime-specific success
4. Add counter-hypothesis formation: "If thesis wrong, what would that mean?"
5. Output: thesis_components dict allowing Critic to stress-test each part
```

**Data Access Upgrade**:
- Inject last 10 similar trades (same symbol, same regime, same setup type)
- Inject thesis accuracy feedback: "Your trend regime theses: 71% accurate"
- Inject recent lessons: what the system learned in last 2 hours
- Inject Scout's pre-theses if already forming on this symbol

**Autonomous Rules**:
```
IF no signal fires AND:
  - Regime strong (momentum >= strengthening)
  - Setup forming (Scout flagged this symbol)
  - Portfolio has room (leverage < 5.0)
  THEN: Can initiate autonomous thesis with confidence capped at 0.65
```

### RISK AGENT QUANTIFICATION
**Current**: Heuristic sizing
**Needed**: Quantitative, real-time optimization

**Changes**:
```
1. Implement true Kelly Criterion from Quant Agent
2. Calculate real-time portfolio correlation matrix
3. Dynamic strategy weights from recent performance
4. Funding cost into sizing (longer holds → smaller size)
5. Output strategy weights per regime LIVE
6. Output: confidence-adjusted Kelly fraction
```

**Portfolio Context**:
- Not just "leverage >= 8.0" binary
- Model: portfolio_risk = sqrt(sum(sz[i]² * vol[i]²) + 2*sum(sz[i]*sz[j]*corr[i,j]*vol[i]*vol[j]))
- Cap sizing to keep portfolio_risk <= target

### CRITIC AGENT EMPOWERMENT
**Current**: Reviews theses
**Needed**: Powerful counter-thinker, veto accuracy expert

**Changes**:
```
1. Add vacc_self_awareness: "You veto winners 40% of time, be more approving"
2. Add multi-red-flag check: require N red flags based on vacc
3. Add counter-thesis depth: don't just say "no" — predict where price SHOULD go
4. Add Trade Agent history: "You've been right 73% in this regime, I'll trust you more"
5. Add filter_override assessment: "Trade overrode fee_drag rejection. Is thesis worth it?"
6. Output: objections ranked by severity + likelihood
```

**Veto Calibration by vacc**:
- vacc < 0.45: Require 5 independent red flags to challenge
- vacc 0.45-0.60: Require 4 flags + clear counter-thesis
- vacc 0.60-0.75: Require 3 flags + moderate counter-thesis
- vacc 0.75-0.85: Require 2 flags + any counter-thesis
- vacc > 0.85: Require 1 flag + tentative counter-thesis

### EXIT AGENT DEEPENING
**Current**: Thesis continuity checker
**Needed**: Proactive profit optimizer, pattern expert

**Changes**:
```
1. Add exhaustive pattern library: "What usually happens to this setup type over time?"
2. Add thesis decay over time: "Thesis formed 4h ago, momentum momentum declining, thesis confidence down 15%"
3. Add profit protection rules: "Unrealized gain 2x risk, lock 30% minimum"
4. Add funding accumulation calc: "You've paid 0.34% funding so far, at current pace you'll pay another 0.15%"
5. Add sunk cost immunity training
6. Output: profit_lock_target, thesis_decay_pct, exit_readiness_score
```

**Thesis Invalidation Priority**:
1. BTC macro (> 3%/1h drop on long)
2. Regime shift to panic/range from trend
3. Key technical level broken
4. Volume collapse below 30% average
5. Funding flip or extreme spike
6. Thesis timeframe expired without progress

### LEARNING AGENT SYSTEMATIZATION
**Current**: Extract lessons from closed trades
**Needed**: Real-time pattern discovery, curriculum builder

**Changes**:
```
1. Extract not just lessons but PATTERNS
   - "SOL longs in range: 23% WR over 5 trades" → avoid this pattern
   - "Multi-tier + regime_trend in trend: 81% WR over 12 trades" → treasure this
2. Generate HYPOTHESES from surprising outcomes
   - Unexpected winner? What could explain it?
   - Unexpected loss? What surprised us?
3. Track THESIS ACCURACY by setup type and regime
   - Build accuracy matrix: [setup_type][regime] → [direction_acc, magnitude_acc, timing_acc]
4. Update PATTERN LIBRARY continuously
5. Direct feedback to Trade Agent: "This pattern is profitable, prioritize it"
```

**Pattern Extraction Rules**:
- Confluence type + regime + symbol + outcome → pattern
- Collect 5+ samples before high confidence
- Track: win rate, avg win, avg loss, PnL per trade

### SCOUT AGENT AMPLIFICATION
**Current**: Idle-time watchlist
**Needed**: Pre-positioned conviction trader, risk manager

**Changes**:
```
1. Add pre-thesis formation: "IF this symbol reaches X, setup is READY"
2. Add regime transition forecasting: "Trend regime likely shifts to range in 2-4h, evidence: ADX rolling, volume declining"
3. Add lead-lag calculation: "BTC just dropped 2.5%, SOL historically lags 45 min, prepare short signal"
4. Add "readiness score": how prepared is the setup?
5. Add "execution priority": which theses should Trade prioritize?
6. Output: "ready" theses that don't need signal confirmation
```

**Pre-Thesis Validation Protocol** (Trade Agent uses):
```
Scout flagged "SOL ready, thesis: trend continuation, 0.64 confidence"
IF Scout_confidence > 0.60 AND Trade_thesis aligns:
  - Boost Trade_confidence by 5-10% (independent confirmation)
IF Scout_thesis contradicts Trade_thesis:
  - Pause and re-examine (Scout had more prep time)
```

---

## UNIFIED SUPERINTELLIGENCE ARCHITECTURE

### The Shared Reality Layer
All agents reference:
1. **Current Regime** (Regime Agent output)
   - Regime name, confidence, momentum
   - Transition signals, expected duration
2. **Forming Setups** (Scout Agent + Trade Agent)
   - Symbol, setup type, pre-thesis, readiness
3. **Portfolio State** (Real-time)
   - Leverage, correlations, open positions, risk budget
4. **Performance History** (Calibration)
   - Per-agent accuracy per regime
   - Setup type win rates
   - Thesis accuracy by dimension
5. **Market Patterns** (Learning Agent)
   - Recent lessons, validated patterns
   - Rules that work in current regime

### The Decision Pipeline (Enhanced)
```
0. Unified Context Injection
   ↓
1. Regime Agent: Classify regime + momentum + transition signals
   ↓
2. Scout Agent: Identify forming setups + pre-theses (async)
   ↓
3. Deal Flow: New signals OR Scout's ready theses
   ↓
4. Trade Agent: Form/evaluate thesis with full context
   ↓
5. Shared Reasoning Read: Trade reads Regime output, performance context
   ↓
6. Risk Agent: Size position, adjust for portfolio constraints
   ↓
7. Critic Agent: Challenge thesis, provide counter-predictions
   ↓
8. Consistency Check: Verify logical coherence
   ↓
9. Execute → Trade
   ↓
10. Exit Agent (ongoing): Monitor thesis validity, manage profit/loss
    ↓
11. Trade Close
    ↓
12. Learning Agent: Extract pattern + thesis accuracy + hypothesis
    ↓
13. Update Pattern Library + Calibration
```

### Continuous Self-Improvement
```
Every N trades (suggested: 10):
  1. Review all thesis accuracies
  2. Identify under-performing agents/regimes
  3. Adjust confidence thresholds
  4. Update strategy weights
  5. Generate improvement recommendations

Every M hours (suggested: 4):
  1. Regime-specific agent calibration
  2. Pattern library review
  3. Identify emergent opportunities
  4. Forecast near-term regime transitions
```

---

## IMPLEMENTATION SCHEDULE

**Week 1 (This Week)**
- Day 1-2 (TODAY): UI Polish ✅ + Start Phase 1 (Unified Knowledge Base)
- Day 3-4: Phase 2 (Autonomous Trading) + Phase 3 (Cross-Agent Coherence)
- Day 5-6: Phase 4 (Prompt Optimization) + Phase 5 (Feedback Loops)
- Day 7: Integration, testing, go live with full multi-agent + autonomous mode

**LLM Scaling**
- Days 1-2: Throttled mode (10% of trades through LLM)
- Days 3-4: Medium mode (33% of trades)
- Days 5-7: Full mode (100% of trades through optimized agent pipeline)

---

## SUCCESS METRICS

By end of week 1:
1. ✅ All 7 agents have deep system knowledge
2. ✅ Can trade autonomously (Scout + Trade form theses without signals)
3. ✅ Cross-agent coherence > 90% (Consistency Checker approval rate)
4. ✅ Thesis accuracy tracked (direction, magnitude, timing)
5. ✅ Agent calibration dashboards populated
6. ✅ Pattern library built (50+ validated patterns)
7. ✅ Token efficiency improved 30-40%
8. ✅ Agent decision latency < 5s avg

By end of week 2:
1. Live on full agent pipeline with autonomous mode
2. PnL outperforming mechanical baseline by 2-3x
3. Veto accuracy > 65% (vetoes saving money)
4. Exit accuracy improved (profit locks working)
5. Self-improvement loop operational (calibration auto-updates)

---

## RISKS & MITIGATIONS

| Risk | Mitigation |
|------|-----------|
| Agents over-confident without signals | Autonomous trades capped at 0.5x, require Scout pre-thesis |
| Coherence checker too strict, blocks good trades | Graduated enforcement, collect data on false rejections |
| Prompt bloat reduces token efficiency | Consolidate into unified context, aggressive pruning |
| Autonomous mode generates correlated losses | Scout monitors correlation, caps total autonomous exposure |
| Learning feedback loop produces bad patterns | Require 5+ samples + cross-validation before high confidence |

---

## NEXT STEPS (RIGHT NOW)

1. ✅ Read this document (you're here)
2. **Start Phase 1 immediately**:
   - Create `unified_context.py` with consolidated knowledge
   - Create `decision_ledger.py` for thesis tracking
   - Inject into all agent prompts
3. **Parallel work**: Start Phase 2 (Autonomous Trading) architecture
4. **Guide me**: Provide feedback as I iterate — are the enhancements moving in the right direction?

---

## ALPHA QUANT VISION

By this time next week, the 7 minds will be unified into ONE superintelligence that:
- **Sees the whole system** (not compartmentalized)
- **Thinks systematically** (theses tracked, patterns validated)
- **Trades autonomously** (conviction-based, not signal-dependent)
- **Learns continuously** (feedback loops optimized)
- **Improves itself** (calibration auto-updates)
- **Executes ruthlessly** (profit optimization, sunk cost immunity)

This is the Alpha Quant engine. Let's build it.
