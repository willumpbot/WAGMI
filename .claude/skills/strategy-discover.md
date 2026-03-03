# /strategy-discover — Activate and Run Strategy Discovery Agent

## Description
Activate the built-but-dormant strategy discovery system to find NEW profitable trading strategies. Uses the research agent to propose ideas, sandbox to backtest them, and proposal tracker to evaluate them.

## Arguments
- `$ARGUMENTS` — Optional: "scan" (look for opportunities), "propose" (generate ideas), "test" (backtest proposals), "status" (check existing proposals)

## Workflow

### 1. System Status
Read `bot/llm/strategy_discovery/`:
- `research_agent.py` — LLM-powered strategy idea generator
- `sandbox.py` — Safe backtesting environment for proposals
- `proposals.py` — Proposal lifecycle tracking
- `corpus.py` — Strategy knowledge corpus

Check: Is the discovery system activated? Are there existing proposals?

### 2. Market Scan (if "scan")
Analyze current market data for unexploited opportunities:

**Data Sources:**
- Funding rate extremes → funding rate arbitrage opportunity?
- Cross-exchange price dislocations → arb signals?
- Order book depth (if available) → order flow signals?
- Regime transition patterns → regime timing strategy?
- Time-of-day patterns → session-specific strategy?

**Current Strategy Gaps:**
Read existing strategies and identify what they DON'T cover:
- `regime_trend.py` — covers trending markets, misses range entries
- `monte_carlo_zones.py` — covers S/R zones, misses momentum
- `confidence_scorer.py` — meta-scoring, not a direct signal source
- `multi_tier_quality.py` — multi-TF confirmation, slow to react

What market conditions have NO strategy coverage?

### 3. Propose New Strategies (if "propose")
Using the research agent or manual analysis:

**Priority Ideas from ROADMAP:**
1. **Funding Rate Reversal**: When funding is extreme (>0.05%), counter-trade with tight stops. Funding reversals are predictable and high-WR. Data already in pipeline.

2. **Order Flow Imbalance**: Detect aggressive market orders and order book imbalance for directional bias. Needs Hyperliquid order book data.

3. **Cross-Exchange Divergence**: Use Kraken/Bybit as leading indicators for Hyperliquid. Price dislocations → momentum signals. Data already fetched via CCXT.

4. **Session Open Breakout**: Trade breakouts at London/NY session opens when ATR is expanding and volume confirms.

5. **Correlation Regime**: When BTC-alt correlation breaks down, trade the divergence back to mean.

For each proposal:
- Name and description
- Entry/exit logic (specific, not vague)
- Expected edge (why this should work)
- Data requirements (what data do we already have?)
- Implementation difficulty (config change / new code / new data source)
- Risk (how can this lose money?)

### 4. Sandbox Test (if "test")
For each promising proposal:

1. **Build minimal implementation** — just the signal generation logic
2. **Backtest against historical data**:
   ```bash
   cd bot && python run.py backtest --strategy <new_strategy> --days 30
   ```
3. **Evaluate results**:
   - Win rate (must be >55% to be interesting)
   - Average R-multiple (must be >1.0)
   - Sharpe ratio (must be >0.5)
   - Max drawdown (must be tolerable)
   - Trade frequency (enough trades to be statistically significant?)
4. **Compare vs existing system**:
   - Does adding this strategy improve ensemble PnL?
   - Or does it just add noise?

### 5. Integration Assessment
For strategies that pass sandbox testing:

**Does it fit the ensemble?**
- Signal dataclass compatible? (returns proper Signal with entry/SL/TP)
- Timeframe requirements available?
- Does it agree or disagree with existing strategies?
- Does it add a NEW dimension (not just duplicate existing signals)?

**Ensemble impact simulation:**
- Add as 5th strategy with weight 1.0
- Backtest ensemble with and without
- Does win rate improve? Does PnL improve?
- Does it reduce max drawdown?

### 6. Proposal Tracking
Update `bot/llm/strategy_discovery/proposals.py`:
```
STRATEGY PROPOSALS
━━━━━━━━━━━━━━━━━━
#  Name                    Status       WR    Sharpe  Decision
1  Funding Rate Reversal   TESTING      62%   1.2     Promising
2  Session Open Breakout   PROPOSED     —     —       Needs backtest
3  Cross-Exchange Div      REJECTED     48%   0.3     No edge
```

### 7. Report
```
STRATEGY DISCOVERY — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CURRENT STRATEGIES: 4 (ensemble weighted veto)
COVERAGE GAPS: [list uncovered market conditions]

PROPOSALS:
  Active:   N
  Testing:  N
  Accepted: N
  Rejected: N

TOP PROPOSAL: [Name]
  Expected Edge: XX% WR, X.XX Sharpe
  Data Ready: [YES/NEEDS WORK]
  Implementation: [N hours estimated]
  PnL Impact: +$XXX/month estimated

RECOMMENDED NEXT STEP:
  [Specific action — backtest X, implement Y, gather data for Z]
```
