# WAGMI Quant Alpha Engine — Master Blueprint

> Post-backtest roadmap for evolving from AI-assisted tactical trading into a true quantitative alpha engine.
> Generated from 9-agent parallel audit covering: position sizing, signal diversification, execution quality, learning/adaptivity, trade frequency math, and 4-phase architecture design.

---

## Current State: Quant Audit Summary (Score: 4.5/10)

| Dimension | Score | Key Finding |
|-----------|-------|-------------|
| Position Sizing & Risk | 5.5/10 | Half-Kelly exists but no risk parity, no vol targeting |
| Signal Diversification | 3/10 | All strategies use overlapping indicators (80%+ momentum) |
| Execution Quality | 6/10 | Good fee modeling, but ALL orders are market orders |
| Learning & Adaptivity | 5/10 | Excellent logging, no walk-forward validation |
| Trade Frequency Math | 5/10 | ~50 trades/day projected, breakeven WR=46.4% |
| Multi-Asset Coverage | 1/10 | Only 5 correlated crypto symbols |
| Factor Exposure | 1/10 | Single factor (momentum). No value/carry/macro |

### The 5 Brutal Truths
1. **Fee drag is the silent killer** — Real costs ~25 bps vs modeled 14 bps. Breakeven WR is 46-50%, not 38%.
2. **Strategies are correlated, not diversified** — All 4 core strategies use MACD/ADX/RSI/BB variants. "4 opinions from 1 brain."
3. **No walk-forward validation** — Learning loop trains and tests on same data. #1 overfitting risk.
4. **LLM is discretionary, not statistical** — Claude forms theses. No p-values, no known false-positive rates.
5. **5 symbols is not a portfolio** — All crypto, all correlated >0.7.

### What We Do Well (Keep These)
- Circuit breakers + session drawdown cap = institutional-grade risk control
- Multi-agent LLM reasoning with Critic veto = intelligent quality gate
- Deep memory (Trade DNA) + learning feedback = strong self-improvement
- EV gating + fee-drag filters = cost-aware signal selection
- Regime-aware voting = adaptive to market conditions
- Half-Kelly engine with per-strategy calibration

---

## Phase 1: True Signal Diversification & Factor Architecture
**Timeline: Weeks 1-4 | Impact: HIGH | Effort: MEDIUM**

### Problem
All 4 core strategies use overlapping price-action indicators:
- `regime_trend`: WaveTrend + MACD + MFI + ADX
- `confidence_scorer`: ADX + MACD + BB + RSI + Keltner
- `bollinger_squeeze`: BB/Keltner + MACD histogram + RSI
- `monte_carlo_zones`: SMA20/50 + RSI + stdev zones

Result: 80%+ exposure to momentum factor. When momentum crashes, ALL strategies lose simultaneously.

### Solution: Orthogonal Signal Sources

#### Phase 1a — Activate Existing Dormant Strategies (Week 1)
These strategies ALREADY EXIST in the codebase but are disabled or underutilized:

| Strategy | File | Factor | Status | Action |
|----------|------|--------|--------|--------|
| `funding_rate` | `strategies/funding_rate.py` | Carry | Exists | Enable, tune thresholds |
| `oi_delta` | `strategies/oi_delta.py` | Flow | Exists | Enable, validate signals |
| `cvd_strategy` | `strategies/cvd_strategy.py` | Flow | Exists | Enable, tune |
| `liquidation_cascade` | `strategies/liquidation_cascade.py` | Microstructure | Exists | Enable for extreme events |
| `vmc_cipher` | `strategies/vmc_cipher.py` | Multi-oscillator | Exists | Re-evaluate edge |

**Goal**: Go from 4 active strategies to 7-8, with 3+ non-overlapping factor sources.

#### Phase 1b — New Orthogonal Signals (Weeks 2-3)

| Signal | Factor Category | Data Source | Expected Alpha | Effort |
|--------|----------------|-------------|----------------|--------|
| **Funding rate term structure** | Carry | Hyperliquid API (funding history) | Medium-High | 2 days |
| **Order book imbalance** | Microstructure | Hyperliquid WebSocket L2 | Medium | 3 days |
| **Exchange netflow** | On-chain | CryptoQuant / Glassnode API | High | 3 days |
| **Fear & Greed Index** | Sentiment | Alternative.me API (free) | Low-Medium | 1 day |
| **Cross-asset correlation** | Macro | DXY via CCXT (forex pair) | Medium | 2 days |
| **Whale wallet tracking** | On-chain | Arkham / Nansen API | High | 4 days |

**Funding Rate Term Structure** (highest ROI):
```
Signal: Compare current funding rate to 7-day average
If funding >> avg → market overleveraged long → short bias
If funding << avg → market overleveraged short → long bias
Backwardation (negative funding) = strong carry signal
```
Integration: New strategy inheriting `BaseStrategy`, returns `Signal` with `strategy="funding_curve"`. Ensemble treats as independent vote.

**Order Book Imbalance**:
```
Signal: bid_depth / ask_depth ratio at top 5 levels
If bid/ask > 1.5 → absorption buying → long bias
If bid/ask < 0.67 → selling pressure → short bias
```
Integration: Real-time WebSocket feed, computed every tick, exposed to strategies as a feature.

#### Phase 1c — Factor Model Architecture (Week 4)

Target allocation across factor categories:

```
Portfolio Factor Budget:
├── Momentum (25%): regime_trend, confidence_scorer, bollinger_squeeze
├── Carry (25%): funding_rate, funding_curve (new)
├── Flow/Microstructure (25%): oi_delta, cvd, order_book_imbalance (new)
└── Sentiment/Macro (25%): fear_greed, exchange_netflow (new), cross_asset_corr (new)
```

**Implementation: Factor-Weighted Ensemble**
```python
# In ensemble.py, add factor-aware weighting:
STRATEGY_FACTOR_MAP = {
    'regime_trend': 'momentum',
    'confidence_scorer': 'momentum',
    'bollinger_squeeze': 'momentum',
    'funding_rate': 'carry',
    'funding_curve': 'carry',
    'oi_delta': 'flow',
    'cvd_strategy': 'flow',
    'order_book_imbalance': 'flow',
    'fear_greed': 'sentiment',
    'exchange_netflow': 'sentiment',
}

# Cap per-factor contribution to prevent momentum dominance
MAX_FACTOR_WEIGHT = 0.35  # No single factor can be >35% of ensemble vote
```

### Symbol Expansion Strategy

**Tier 1 — Add immediately (high liquidity, low correlation to BTC):**
- ETH, AVAX, LINK, AAVE, ARB

**Tier 2 — Add after validation (medium liquidity):**
- SUI, SEI, TIA, JUP, WIF

**Tier 3 — Monitor only (low liquidity, high risk):**
- PEPE, BONK, WEN, ONDO

**Selection criteria:**
- Hyperliquid daily volume > $10M
- Correlation to BTC < 0.80 (24h rolling)
- Spread < 5 bps at $50k notional

---

## Phase 2: Execution Optimization & Statistical Validation
**Timeline: Weeks 3-8 | Impact: HIGH | Effort: HIGH**

### Problem
- ALL orders are market orders → leaving 10-15 bps on the table
- Hidden execution friction ~25 bps vs modeled 14 bps
- Fees exceed per-trade risk by 2.55x at current sizing
- No walk-forward validation → overfitting risk

### 2a — Limit Order Infrastructure (Week 3-4)

**TP/SL as Limit Orders:**
```python
# Current: market order on TP/SL hit
# New: place limit order at TP price, fallback to market after 30s
async def close_position_smart(position, target_price, urgency):
    if urgency == "low":  # TP1, TP2
        # Place limit order at target price
        order = await place_limit_order(target_price, side="close")
        await asyncio.sleep(30)
        if not order.filled:
            await cancel_and_market_close(order)
    elif urgency == "high":  # SL, circuit breaker
        await market_close(position)  # Immediate market order
```

**Expected savings:** 5-10 bps per close = $25-50 per trade on $50k account.

**Maker Fee Capture for Entries:**
```
Current: Taker entry (4 bps cost)
New: Post-only limit order at mid-price (−1.5 bps rebate)
Savings: 5.5 bps per entry = $27.50 per trade on $50k notional
Combined savings: 10-15 bps per round trip
```

### 2b — Walk-Forward Validation Framework (Weeks 5-6)

**Architecture:**
```
Data partition:
├── Training window:   [T-90 days : T-14 days]  (76 days)
├── Validation window: [T-14 days : T-7 days]   (7 days)
└── Test window:       [T-7 days : T]            (7 days, UNTOUCHED)

Schedule:
- Retrain weekly (Sunday night)
- Validate daily (compare predicted vs actual WR)
- Test monthly (evaluate out-of-sample Sharpe)
```

**What gets validated:**
- Strategy weights (rolling_weights)
- EV deflation ratios
- Regime-aware min_votes table
- Kelly fraction per strategy
- Confidence scorer historical WR

**Significance testing:**
```python
# After N trades, test if observed WR > breakeven WR at p<0.05
from scipy.stats import binom_test
p_value = binom_test(wins, n=total_trades, p=breakeven_wr, alternative='greater')
if p_value < 0.05:
    log("Edge confirmed at 95% confidence")
else:
    log(f"Edge NOT confirmed (p={p_value:.3f}), need more trades")
```

**Convergence requirements:**
- 300 trades → Sharpe estimate stabilizes (±0.2)
- 1,000 trades → Win rate converges (±3%)
- At 50 trades/day: **6 days to stabilize Sharpe, 20 days to confirm WR**

### 2c — Realistic Backtesting Engine (Weeks 7-8)

**Current gaps → fixes:**

| Gap | Fix |
|-----|-----|
| Instant fills | Add fill delay (1-3 candles based on liquidity) |
| Fixed slippage (3 bps) | Dynamic slippage = f(order_size / book_depth) |
| No market impact | Impact model: 0.1 × sqrt(notional / ADV) |
| Same data for train+test | Proper holdout with walk-forward |
| No regime stratification | Report results per regime separately |

**Monte Carlo parameter sensitivity:**
```python
# Vary each parameter ±20% and measure PnL impact
params_to_test = ['sl_atr_multiplier', 'min_signal_rr', 'min_signal_ev',
                  'ensemble_confidence_floor', 'risk_per_trade']
for param in params_to_test:
    for mult in [0.8, 0.9, 1.0, 1.1, 1.2]:
        run_backtest(param=default * mult)
        record(param, mult, sharpe, max_dd, trade_count)
```

---

## Phase 3: Portfolio Construction & Risk Intelligence
**Timeline: Weeks 5-10 | Impact: VERY HIGH | Effort: HIGH**

### Problem
- Flat 0.5% risk per trade (not volatility-adjusted)
- No risk parity (all positions sized equally in dollar terms)
- No portfolio-level Sharpe optimization
- Correlation gate is binary (reject/reduce), not continuous

### 3a — Volatility-Targeted Sizing (Weeks 5-6)

**Current:**
```python
qty = (equity * risk_per_trade * risk_mult) / (stop_width * leverage)
# Same 0.5% risk regardless of realized volatility
```

**New: Volatility-normalized sizing:**
```python
# Target: each position contributes equal VOLATILITY to portfolio
target_position_vol = 0.10 / sqrt(max_positions)  # 10% annual target / sqrt(8)
realized_vol = ewma_volatility(symbol, lookback=72h)
position_size = target_position_vol / realized_vol

# High vol symbol (DOGE, 80% annualized) → small position
# Low vol symbol (BTC, 40% annualized) → larger position
```

**Integration point:** `execution/risk.py:calculate_qty()` — multiply base size by vol-normalization factor.

### 3b — Real-Time Correlation Matrix (Weeks 5-6)

**Current:** Pearson correlation, 72h lookback, binary thresholds.

**New: Dynamic Correlation-Aware Portfolio:**
```python
class PortfolioRiskEngine:
    def compute_portfolio_var(self, positions):
        """Compute portfolio VaR using current correlation matrix."""
        cov_matrix = self.get_ewma_covariance(lookback=72)
        weights = [pos.notional / total_notional for pos in positions]
        portfolio_var = sqrt(weights.T @ cov_matrix @ weights)
        return portfolio_var

    def marginal_risk_contribution(self, new_position, existing_positions):
        """How much risk does adding this position contribute?"""
        var_before = self.compute_portfolio_var(existing_positions)
        var_after = self.compute_portfolio_var(existing_positions + [new_position])
        return var_after - var_before

    def should_add_position(self, new_pos, existing):
        """Only add if marginal risk < risk budget."""
        marginal = self.marginal_risk_contribution(new_pos, existing)
        budget_remaining = self.target_portfolio_var - self.compute_portfolio_var(existing)
        return marginal <= budget_remaining
```

**Integration point:** `core/signal_pipeline.py` Gate 4 — replace binary correlation check with marginal VaR check.

### 3c — Kelly Criterion Integration (Weeks 7-8)

**Current:** Half-Kelly per-strategy with 30-trade lookback. Not setup-specific.

**New: Setup-Specific Kelly:**
```python
# Track edge per (strategy, regime, symbol, signal_type) tuple
# Example: "bollinger_squeeze + squeeze_breakout + trending_bull + BTC"
#   → observed: 62% WR, 1.8 payoff ratio
#   → Kelly f* = (0.62 * 1.8 - 0.38) / 1.8 = 0.408
#   → Half-Kelly: 20.4% of bankroll
#   → Actual allocation: min(risk_per_trade, half_kelly * scaling)

class SetupKelly:
    def get_optimal_fraction(self, strategy, regime, symbol, signal_type):
        key = (strategy, regime, symbol, signal_type)
        stats = self.setup_stats.get(key)
        if not stats or stats.trials < 10:
            return self.default_fraction  # Bayesian prior
        wr = stats.wins / stats.trials
        pr = stats.avg_win / stats.avg_loss
        kelly = (wr * pr - (1 - wr)) / pr
        return max(0, kelly * 0.5)  # Half-Kelly, floor at 0
```

**Integration point:** `execution/risk.py:calculate_qty()` — replace flat `risk_per_trade` with Kelly-derived fraction when sufficient data exists.

### 3d — Inverse-Variance Signal Combination (Weeks 9-10)

**Current:** Majority voting with confidence-weighted win probability deflation.

**New: IC-Weighted Combination:**
```python
# Information Coefficient = correlation between predicted and actual returns
# Weight each strategy by IC^2 / turnover (Sharpe-optimal)

class ICWeightedEnsemble:
    def compute_strategy_weight(self, strategy_name):
        ic = self.information_coefficients[strategy_name]  # Rolling 100-trade IC
        turnover = self.strategy_turnover[strategy_name]    # Avg trades/day
        if turnover == 0:
            return 0
        # Grinold-Kahn fundamental law: IR = IC * sqrt(breadth)
        # Weight proportional to IR^2
        ir_squared = (ic ** 2) * turnover
        return ir_squared

    def combine_signals(self, signals):
        weights = {s.strategy: self.compute_strategy_weight(s.strategy) for s in signals}
        total_weight = sum(weights.values())
        if total_weight == 0:
            return None  # No strategies have edge
        # Weighted average confidence
        combined_conf = sum(s.confidence * weights[s.strategy] for s in signals) / total_weight
        return combined_conf
```

**Integration point:** `strategies/ensemble.py` — add as alternative to `weighted_veto` mode. Configure via `ENSEMBLE_MODE=ic_weighted`.

---

## Phase 4: LLM-Quant Hybrid Architecture
**Timeline: Weeks 8-14 | Impact: MEDIUM-HIGH | Effort: HIGH**

### Problem
- LLM acts as decision-maker (discretionary), not feature-generator (quantitative)
- No statistical significance testing on LLM decisions
- Cost: $50-600/month with uncertain alpha attribution
- 1-5s latency is acceptable for swing trades but limits strategy universe

### 4a — LLM A/B Testing Framework (Weeks 8-9)

**Architecture:**
```python
class LLMAlphaTest:
    """Random 50/50 split: LLM-enhanced vs pure-quant decisions."""

    def should_use_llm(self, signal_id: str) -> bool:
        # Deterministic hash for reproducibility
        return hash(signal_id) % 2 == 0

    def record_outcome(self, signal_id, used_llm, pnl, holding_period):
        group = "llm" if used_llm else "quant_only"
        self.results[group].append({
            'pnl': pnl,
            'holding_period': holding_period,
            'timestamp': time.time()
        })

    def compute_alpha_attribution(self):
        llm_sharpe = sharpe(self.results['llm'])
        quant_sharpe = sharpe(self.results['quant_only'])
        p_value = ttest_ind(
            [r['pnl'] for r in self.results['llm']],
            [r['pnl'] for r in self.results['quant_only']]
        ).pvalue
        return {
            'llm_sharpe': llm_sharpe,
            'quant_sharpe': quant_sharpe,
            'alpha_delta': llm_sharpe - quant_sharpe,
            'p_value': p_value,
            'significant': p_value < 0.05
        }
```

**Decision rule:** After 200 trades per group (400 total, ~8 days):
- If LLM adds Sharpe at p<0.05 → keep LLM, expand usage
- If no significant difference → reduce LLM to veto-only (save costs)
- If LLM hurts Sharpe → disable LLM, pure quant mode

### 4b — LLM as Feature Generator, Not Decision Maker (Weeks 9-10)

**Current flow:**
```
Market data → LLM → "go/skip/flip" decision → execute
```

**New flow:**
```
Market data → LLM → features (regime_prob, sentiment_score, thesis_confidence)
                  ↓
         Statistical model (logistic regression / XGBoost)
                  ↓
         Calibrated probability → Kelly sizing → execute
```

**LLM outputs become features:**
```python
class LLMFeatureExtractor:
    def extract_features(self, market_snapshot) -> dict:
        """LLM produces structured features, not decisions."""
        prompt = """
        Analyze this market data. Output ONLY these fields as JSON:
        - regime_probability: {trend: 0.X, range: 0.X, panic: 0.X}
        - sentiment_score: -1.0 to 1.0
        - thesis_confidence: 0.0 to 1.0
        - key_risk_factors: [list of strings]
        - similar_historical_pattern: string description
        DO NOT make a trade decision.
        """
        response = self.llm_client.call(prompt, market_snapshot)
        return parse_features(response)
```

**Statistical model consumes LLM features + technical features:**
```python
# Features: [adx, rsi, bb_width, macd_hist, llm_sentiment, llm_regime_trend_prob, ...]
# Target: trade_profitable (0/1)
# Model: logistic regression with known calibration
model = LogisticRegression()
model.fit(X_train, y_train)
prob = model.predict_proba(X_new)[0, 1]
# Now we have a CALIBRATED probability with known false-positive rate
```

### 4c — HMM Regime Detection (Weeks 10-12)

**Current:** LLM classifies regime as single string ("trend", "range", etc.)

**New: Hidden Markov Model + LLM hybrid:**
```python
from hmmlearn import GaussianHMM

class HybridRegimeDetector:
    def __init__(self, n_regimes=4):
        self.hmm = GaussianHMM(n_components=n_regimes, covariance_type="full")
        # Regimes: 0=trending, 1=ranging, 2=volatile, 3=crisis

    def fit(self, returns, volumes, spreads):
        """Fit HMM on multi-feature time series."""
        features = np.column_stack([returns, volumes, spreads])
        self.hmm.fit(features)

    def predict_regime(self, current_features):
        """Returns probability distribution over regimes."""
        probs = self.hmm.predict_proba(current_features)
        return {
            'trending': probs[0, 0],
            'ranging': probs[0, 1],
            'volatile': probs[0, 2],
            'crisis': probs[0, 3],
            'transition_matrix': self.hmm.transmat_  # P(next regime | current)
        }

    def blend_with_llm(self, hmm_probs, llm_regime_probs):
        """Bayesian blend: HMM prior + LLM likelihood."""
        blended = {}
        for regime in hmm_probs:
            blended[regime] = hmm_probs[regime] * llm_regime_probs.get(regime, 0.5)
        total = sum(blended.values())
        return {k: v/total for k, v in blended.items()}
```

### 4d — Cost-Optimized LLM Routing (Weeks 12-14)

**Decision tree for when to invoke LLM:**
```
Signal arrives from ensemble
├── 3+ strategies agree, confidence > 75%
│   └── SKIP LLM (signal is obvious, save $0.003)
├── 2 strategies agree, confidence 60-75%
│   └── HAIKU only ($0.0001) — quick regime check
├── 1 strategy, high conviction (80%+)
│   └── SONNET ($0.003) — full thesis + counter-thesis
├── Regime shift detected
│   └── OPUS ($0.015) — deep analysis, rare event
└── No signal, idle
    └── SCOUT agent (Haiku, $0.0001) — watchlist prep
```

**Expected cost savings:** 40-60% reduction from current spend by skipping LLM on obvious signals.

---

## Phase 5: Profitability Validation Protocol
**Timeline: Continuous | The phase that actually matters**

### The Math That Matters

| Metric | Breakeven | Target | Exceptional |
|--------|-----------|--------|-------------|
| Win Rate | 46.4% | 52%+ | 58%+ |
| Sharpe Ratio | 1.0 | 2.0 | 3.0+ |
| Monthly Return | 0% | +5-10% | +15%+ |
| Max Drawdown | <15% | <10% | <5% |
| Trades/Day | 30 | 50 | 100+ |
| Fee Drag (% of edge) | <50% | <25% | <15% |

### 3-Phase Validation Pipeline

**Stage 1: Backtest Validation (1 week)**
```bash
cd bot && python backtest/runner.py --symbols BTC SOL HYPE DOGE FARTCOIN --days 30
```
Must achieve:
- [ ] 100+ trades
- [ ] WR > 47%
- [ ] Sharpe > 1.5
- [ ] Max DD < 12%
- [ ] No single trade loss > 1% equity

**Stage 2: Paper Trading (3 weeks)**
```bash
cd bot && python run.py paper
```
Must achieve over 21 days:
- [ ] 500+ trades
- [ ] WR > 46% (lower bar — real conditions)
- [ ] Sharpe > 1.2
- [ ] Circuit breaker triggered < 3 times
- [ ] Positive cumulative PnL after week 2

**Stage 3: Live Deployment (gradual)**
- Week 1: 10% of capital, monitor only
- Week 2: 25% of capital if Stage 2 metrics hold
- Week 4: 50% of capital
- Week 8: Full capital if Sharpe > 1.5

### Kill Switches
- WR drops below 42% over 100 trades → pause, investigate
- Max DD exceeds 12% → circuit breaker + manual review
- Sharpe drops below 0.8 over 500 trades → reduce to 25% capital
- LLM costs exceed $20/day without proportional alpha → disable LLM

---

## Implementation Priority Matrix

| # | Item | Phase | Impact | Effort | ROI |
|---|------|-------|--------|--------|-----|
| 1 | Activate dormant strategies (funding, OI, CVD) | 1a | HIGH | LOW | **HIGHEST** |
| 2 | Limit TP/SL orders + maker fee capture | 2a | HIGH | MEDIUM | **VERY HIGH** |
| 3 | Volatility-targeted sizing | 3a | HIGH | MEDIUM | **HIGH** |
| 4 | Walk-forward validation framework | 2b | CRITICAL | MEDIUM | **HIGH** |
| 5 | LLM A/B testing framework | 4a | MEDIUM | LOW | **HIGH** |
| 6 | Correlation-aware portfolio construction | 3b | HIGH | HIGH | MEDIUM |
| 7 | New orthogonal signals (funding curve, OB imbalance) | 1b | MEDIUM | MEDIUM | MEDIUM |
| 8 | Factor-weighted ensemble | 1c | MEDIUM | MEDIUM | MEDIUM |
| 9 | Setup-specific Kelly sizing | 3c | MEDIUM | HIGH | MEDIUM |
| 10 | HMM regime detection | 4c | MEDIUM | HIGH | LOW-MEDIUM |
| 11 | IC-weighted signal combination | 3d | MEDIUM | HIGH | LOW-MEDIUM |
| 12 | Symbol expansion (ETH, AVAX, LINK...) | 1 | LOW-MEDIUM | LOW | MEDIUM |
| 13 | Realistic backtesting engine | 2c | MEDIUM | HIGH | LOW |
| 14 | LLM as feature generator | 4b | MEDIUM | HIGH | LOW |

---

## Comparison: Where We Are vs Where We're Going

| Aspect | Current (v1) | After Blueprint (v2) | True Quant Fund |
|--------|-------------|---------------------|-----------------|
| Instruments | 5 crypto | 15-20 crypto | 100+ multi-asset |
| Factors | 1 (momentum) | 4 (momentum, carry, flow, sentiment) | 10+ |
| Daily trades | 6-50 | 50-100 | 500-5000 |
| Signal combination | Majority vote | IC-weighted + factor-balanced | Bayesian optimal |
| Validation | None | Walk-forward weekly | Rolling holdout daily |
| Position sizing | Flat 0.5% | Vol-targeted + setup-Kelly | Portfolio Sharpe optimizer |
| Execution | Market orders | Limit TP/SL + maker capture | TWAP/VWAP + smart routing |
| Risk model | Circuit breakers | Portfolio VaR + marginal risk | Expected shortfall + PCA |
| LLM role | Decision maker | Feature generator + veto | N/A (pure statistical) |
| Projected Sharpe | 1.0-1.5 | 2.0-2.5 | 3.0-6.0 |
| Max Drawdown | 15-20% | 8-12% | 3-8% |

---

## Session 2 Progress: Quant Wiring & Feedback Loops (March 14, 2026)

### Completed Implementations

#### 1. IC Tracker Wired Into Ensemble Voting & Position Sizing
- **Files**: `bot/strategies/ensemble.py`, `bot/multi_strategy_main.py`
- **What**: IC tracker `get_ic_weight()` now multiplies into both ensemble strategy weights AND the compound sizing system
- **Effect**: Inverted factors (IC < 0) get weight 0.0 (killed), decaying factors get 0.0-1.0 linear scale
- **Integration points**:
  - `ensemble._get_strategy_weight()` applies IC weight before voting
  - `multi_strategy_main.py` line ~3230 applies IC weight as compound sizing multiplier
  - IC tracker injected into ensemble at init time via `ensemble.ic_tracker = self.ic_tracker`

#### 2. Kelly Sizing Already Wired (Confirmed)
- **File**: `bot/multi_strategy_main.py` line 3225
- **What**: `kelly_engine.compute_kelly_weight(strategy)` is the first multiplier in the 8-multiplier compound sizing system
- **Status**: Was already wired — no changes needed

#### 3. Missed Trade Tracker (NEW — Full Feedback Loop)
- **New file**: `bot/feedback/missed_trade_tracker.py` (400+ LOC)
- **What**: Comprehensive tracking of EVERY rejected signal with:
  - Full signal context (symbol, side, confidence, strategies, regime, EV)
  - Rejection classification into 18 categories (fee_drag, circuit_breaker, correlation_cluster, etc.)
  - **Counterfactual analysis**: What WOULD have happened (price after 1h/4h/8h, would TP1/SL hit)
  - **Missed alpha calculation**: How much profit each gate cost us
  - **Gate effectiveness**: % of rejections that were correct (saved us from losses)
  - **Top missed opportunities**: Biggest winners we blocked
- **Integration**: Wired into `backtest/engine.py` at 3 rejection points:
  - Risk filter chain rejections (line ~1387)
  - Regime-blocked signals (lines ~675, ~689)
  - Backtest report includes `missed_trades` and `gate_effectiveness` sections
- **Report output**: New sections in backtest report showing per-category breakdown, gate accuracy, and top missed opportunities

#### 4. Auto-Decay for Strategy Weights
- **File**: `bot/multi_strategy_main.py` line ~1272
- **What**: Daily decay (alpha=0.9) applied automatically during daily report generation
- **Effect**: Old trade outcomes gradually lose influence, preventing stale data from dominating

### Quant Infrastructure Audit Summary

| Component | LOC | Status | Wired? | Gap |
|-----------|-----|--------|--------|-----|
| IC Tracker | 286 | Full | **YES** (now) | Was dead code — now wired into voting + sizing |
| Kelly Engine | 276 | Full | YES | Already wired into compound sizing |
| Strategy Weights | 220 | Full | YES | Auto-decay now added |
| Correlation Gate | 341 | Full | YES | Active in signal pipeline |
| Walk-Forward (BT) | 343 | Full | YES | Backtest-only |
| Walk-Forward (Live) | 205 | Full | Partial | Not continuously monitored |
| Portfolio Risk | 1134 | Full | **YES** | Budget utilization → compound sizing multiplier |
| Quant Analytics | 576 | Full | Partial | Backtest-only |
| Deployment Gate | 204 | Full | YES | One-time check |
| Missed Trade Tracker | 400+ | **NEW** | **YES** | Comprehensive feedback loop |

### Backtest Accuracy Gaps Identified

1. **TP fill optimism**: TP exits assume no slippage (limit fill), SL exits add slippage (market) — asymmetric
2. **No liquidation enforcement**: Positions can go past liquidation in backtest without being force-closed
3. **Funding rate fixed**: Uses 0.01%/8h fixed vs live variable 0.005-0.05%
4. **No gap handling**: No detection of overnight/weekend price gaps
5. **Stale MTM prices**: Multi-symbol equity calc uses up to 1h stale prices for inactive symbols
6. **No market impact**: Slippage is fixed 3 bps regardless of position size

### Session 3 Progress (Swarm Findings + Deep Wiring)

**Swarm Audit Results** — 6 agents analyzed the codebase. Key findings:
- Kelly engine IS wired (confirmed, not dead code as initially reported)
- Compound sizing IS active via `_compound_mult` (8-multiplier system)
- Time stops ARE enforced in position_manager.py (8h default)
- Trade ledger WAS recording empty compound_size_multiplier (fixed)
- Portfolio risk budget WAS computed but NOT a sizing multiplier (fixed)
- Missed trade tracker WAS only in backtest engine (fixed: now in ensemble too)

**Changes Implemented:**
1. **Portfolio risk budget → compound sizing** (`multi_strategy_main.py:3263-3283`)
   - `compute_risk_budget()` now feeds into `_compound_mult`
   - Linear scale: 1.0× at 50% budget utilization → 0.2× at 100%
   - Prevents overleveraging as portfolio fills up
2. **Trade ledger attribution fix** (`multi_strategy_main.py:1944`)
   - `compound_size_multiplier` now records actual `_compound_mult` value (was `""`)
   - `_compound_mult_cache` dict stores per-symbol at entry, pops at close
3. **Missed trade tracker → ensemble wiring** (`ensemble.py:728-736, 401, 428, 1118, 1141, 1163`)
   - All 6 ensemble rejection paths now record to MissedTradeTracker:
     - Low volume/chop filter
     - 4h regime conflict
     - Insufficient votes
     - Losing combo blocked
     - Opposition veto (weighted)
     - Confidence floor / graduated rules / trend alignment (via `_record_counterfactual`)
4. **MissedTradeTracker bug fix** (`missed_trade_tracker.py:376`)
   - Fixed unhashable dataclass in set comprehension
5. **11 new tests** (`tests/test_quant_session2.py`)
   - MissedTradeTracker: record, ensemble rejection, counterfactual, report, gate effectiveness
   - Ensemble wiring: tracker injection, counterfactual delegation
   - Portfolio risk budget: math verification at 50%/80%/100% utilization
   - Compound mult cache: store/retrieve/pop lifecycle

### Still Pending

- [ ] Wire live walk-forward validation with auto-sizing reduction on edge decay
- [ ] Implement regime-conditional quant metrics in live trading
- [ ] Wire rebalance suggestions into exit intelligence (currently computed but ignored)
- [ ] Run 30-day backtest with full missed trade tracking to calibrate gates

---

## Next Immediate Steps (This Week)

1. **Run 30-day backtest** with new quant parameters + missed trade tracking
2. **Review missed trade report** — identify gates that are blocking too many winners
3. **Enforce portfolio risk budget** — wire risk parity into actual sizing
4. **Start LLM A/B test** — route 50% of decisions without LLM
5. **Add significance testing** — after 100 trades, report if edge is real
6. **Monitor fee drag** — track actual vs modeled execution costs

The blueprint transforms the bot from **"few big conviction bets"** to **"many small diversified edges"** — the core philosophy of quantitative investing. Each phase independently improves the system; together they compound into institutional-grade architecture.
