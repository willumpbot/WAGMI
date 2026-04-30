# Strategies Audit — 2026-04-29

**Question:** the project has 22 files in `bot/strategies/`. Which are wired into the ensemble vs. infrastructure vs. orphaned?

**Headline:** **3 alternate-implementation strategies are unwired and look promising as additional ensemble members.** Not "dead code" — they're different angles on the same alpha sources (funding, OI, liquidation) that could be activated to broaden the ensemble.

Plus 3 default-OFF strategies (Monte Carlo, VMC Cipher, Lead Lag) that are imported but not enabled by default — their `STRATEGY_*_ENABLED` env var defaults to false. Worth deciding whether to flip them on or remove them.

---

## Inventory

### ✅ Active in the ensemble (10, default ON)

| Strategy | env default | File |
|---|---|---|
| RegimeTrend | ON | `regime_trend.py` |
| ConfidenceScorer | ON | `confidence_scorer.py` |
| MultiTierQuality | ON | `multi_tier_quality.py` |
| FundingRate | ON | `funding_rate.py` |
| OIDelta | ON | `oi_delta.py` |
| BollingerSqueeze | ON | `bollinger_squeeze.py` |
| LiquidationCascade | ON | `liquidation_cascade.py` |
| ProbabilityEngine | ON | `probability_engine.py` |
| MeanReversion | ON | `mean_reversion.py` |
| (CVD) | OFF | `cvd_signal.py` (lazy-loaded when enabled) |

These are listed in `enabled_names` log line at startup and instantiated in `multi_strategy_main.py:431-472`. If `.env` enables them, they participate in ensemble voting.

### ⚠️ Imported but default OFF (3)

| Strategy | env default | File | Recommendation |
|---|---|---|---|
| MonteCarloZones | **OFF** | `monte_carlo_zones.py` | Decide: enable or remove |
| VMCCipher | **OFF** | `vmc_cipher.py` | Decide: enable or remove |
| LeadLag | **OFF** | `lead_lag.py` | Decide: enable or remove |

These are wired correctly — flipping the env var activates them. The question is whether they're being kept around for when the bot is healthier, or are dead weight to delete.

### 🔧 Infrastructure (5, used differently)

| File | Purpose | Used at |
|---|---|---|
| `base.py` | `Signal` + `BaseStrategy` classes | imported by every strategy |
| `ensemble.py` | The orchestrator | `multi_strategy_main.py:491` |
| `chop_detector.py` | Choppy-market filter (plugin to ensemble) | `multi_strategy_main.py:480` |
| `regime_detector.py` | Standalone regime classifier (not a strategy) | `multi_strategy_main.py:954` |
| `cross_symbol_patterns.py` | `CrossSymbolTracker` (lead-lag tracker) | `multi_strategy_main.py:209,968` |
| `alpha_gate.py` | Used internally by `ensemble.py:2553` | indirect |

These are correctly used as building blocks, not as voting strategies.

### 🟡 ORPHANED — Alternate implementations, no caller (3)

These are the interesting ones. Each takes a different angle on data the active strategies already use, but is not imported by `multi_strategy_main.py` or registered with the ensemble.

#### `funding_rate_signal.py` (171 lines)

```python
class FundingRateStrategy(BaseStrategy):
    """Funding rate mean-reversion strategy.
    
    Edge basis: Proven Sharpe > 1.5 on BTC in crypto quant literature.
    Uncorrelated with technical signals — adds independent alpha.
```

vs. the active `funding_rate.py` (241 lines):
```python
class FundingRateStrategy(BaseStrategy):
    """Counter-trade extreme funding rates.
```

**Same class name (collision risk if both imported).** The orphan takes a mean-reversion angle (gradient-based). The active takes an extreme-counter angle (threshold-based). These are conceptually different — could co-exist as `FundingRateMeanRev` + `FundingRateExtreme`.

#### `oi_divergence.py` (186 lines)

```python
"""Open Interest Divergence Signal — Directional signal from OI/price divergence.
The four OI scenarios:
  Price Rising  + OI Falling  = Short covering rally → FADE / short
  ...
```

vs. the active `oi_delta.py` (299 lines) which tracks OI rate of change.

**Different class names — no collision.** The divergence approach watches the price-vs-OI mismatch; delta watches the rate. Both legitimate, complementary signals.

#### `liquidation_signal.py` (402 lines)

```python
"""Liquidation Heatmap Proximity Signal — Estimates where leveraged liquidations 
cluster and generates signals when price approaches dense liquidation zones.

Edge basis: Retail traders cluster at predictable leverage levels (3x, 5x, 10x, 20x).
```

vs. the active `liquidation_cascade.py` (318 lines) which tracks actual liquidation events.

**Different class names.** The signal approach is *anticipatory* (where will liqs happen); the cascade approach is *reactive* (liqs just happened). Both legitimate.

---

## What This Tells Us

The strategies directory shows **a healthier pattern than the agents directory**. Where 13 of 23 agents are dormant, here only 3 of 22 strategies are unwired — and the 3 that are unwired look like deliberate alternative implementations, not the "wrote but forgot to wire" pattern from §09.

Plus 3 default-OFF imports (Monte Carlo, VMC Cipher, Lead Lag) that are wired but disabled. These look like cautious-default choices rather than dead code.

---

## Activation Plan

### Tier 1 — flip default-OFF imports (zero new code)

For each, verify in a backtest that adding it to the ensemble:
- (a) doesn't degrade overall WR
- (b) provides uncorrelated signal (low overlap with existing strategies)
- (c) survives the existing chop/regime gates

```bash
# Example: enable Lead Lag, run 60-day backtest, compare to baseline
STRATEGY_LEAD_LAG_ENABLED=true python run.py backtest --days 60
```

For `monte_carlo_zones`, `vmc_cipher`, `lead_lag` — that's 3 backtests. ~2 hours total.

### Tier 2 — wire the 3 orphan alternate-implementations

#### Funding Rate Mean-Rev (renaming required)

```python
# In funding_rate_signal.py
- class FundingRateStrategy(BaseStrategy):
+ class FundingRateMeanRevStrategy(BaseStrategy):
+     name = "funding_rate_mean_rev"
```

Then in `multi_strategy_main.py:447`:

```python
if os.getenv("STRATEGY_FUNDING_MEAN_REV_ENABLED", "false").lower() == "true":
    self.strategies.append(FundingRateMeanRevStrategy(sym_configs))
```

Default OFF until backtested. ~1h including backtest.

#### OI Divergence + Liquidation Proximity

Same pattern: import, register with new env var, default OFF, backtest before flipping.

These two don't have name collisions, so the code change is just adding the import + register block. ~30 min each + backtest.

### Tier 3 — decide on default-OFF imports

For each of monte_carlo / vmc_cipher / lead_lag: based on Tier 1 backtest results, either:
- enable as default ON (if positive WR contribution)
- delete (if no measurable contribution after fair test)
- keep default OFF as opt-in (if mixed — provides value in specific regimes only)

Don't leave them in limbo indefinitely. Either they earn their import or they're code rot.

---

## Comparison to Agent Audit (§09)

| Category | Agents (§09) | Strategies (§10) |
|---|---|---|
| Total | 23 roles | 22 files |
| Active | 9 (39%) | 13 (59%) |
| Built but unwired | 13 (57%) | 3 (14%) |
| Infrastructure | 1 (4%) | 5 (23%) |
| Orphan/decision-needed | — | 1 (5%) |

**Strategies are in better shape than agents.** The build-then-don't-wire failure mode hits the agent layer harder. Strategies seem to follow a cleaner "import + env-toggle" pattern that makes wiring explicit.

---

## Recommendation

Spend 1 evening on:

1. Backtest the 3 default-OFF imports (Monte Carlo / VMC Cipher / Lead Lag) — 60d each
2. Backtest the 3 orphan alternates (Funding mean-rev / OI divergence / Liquidation proximity) — 60d each + ensemble integration

Output: a comparison table for each strategy showing standalone WR, ensemble-additive WR (with vs without), and correlation with existing strategy outputs. Then pick winners.

Total: ~6 hours of backtests + ~1 hour analysis + ~2 hours wiring. Net: 3-6 new ensemble members validated and active. **Bigger short-term edge boost than activating any single dormant agent.**

This is what `/strategy-discover` skill in CLAUDE.md was built for — runnable any time without LLM cost.
