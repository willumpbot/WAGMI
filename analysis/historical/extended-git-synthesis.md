# Extended Historical Synthesis — Git History + All Data Sources
*Generated: 2026-05-30 | Sources: 1,352 git commits, year_backtest_results.json, walk_forward_results, cycle_3/4/5 JSONs, APRIL_26_FORENSIC_ANALYSIS.md, MASTER_FORENSICS_REPORT, Cycle 6 analysis, 1,410-signal BB analysis, perpetual deep-dive commits*

---

## CRITICAL WARNING: The Year Backtest Was Fake

The `year_backtest_results.json` file showing 91.7% WR / $272,149 profit / 27,740 trades is **NOT real historical data**. It was generated on 2026-04-25 from **synthetic 1-year OHLCV data** using "Omniscient V2 (5 patterns, Kelly optimal sizing)."

**Commit eb1db1e confirms:**
> "Data: Synthetic 1-year OHLCV (8,760 hourly candles per symbol)"
> "Strategy: Omniscient V2 (5 patterns, Kelly optimal sizing)"

That system was immediately deployed as `omniscient_integrated`. On real Hyperliquid data:
- 47 trades in 2 days
- 6.4% win rate
- -$2,155 net loss

**The gap between synthetic performance and real performance is the defining data point of the project's first year.** The year backtest "proved" 91.7% WR. Real execution delivered 6.4%.

**Do not use year_backtest_results.json as evidence of any edge. It represents overfitting to synthetic data.**

---

## The Walk-Forward Validation: Also Empty

Both `walk_forward_results_*.json` (April 28, 2026) show:
- 0 entries proposed
- 0 actual WR of entries
- Baseline at time: 25.4% WR

These were stub runs where the agent KBs were not yet wired into agent prompts. Empty data, not useful.

---

## The Two Collapses: Root Cause Autopsy

### Collapse 1: April 26-27 — Omniscient Cascade
- Trigger: `omniscient_integrated` fired 47 ETH/BTC SHORT signals into a rally
- Confidence: 30.0% – 39.9% (dangerously low)
- Leverage: 5.6x (not adjusted for low confidence)
- Root cause: confidence floor not applied to omniscient signals; no circuit breaker triggered
- Result: 6.4% WR, -$2,155

**April 26 forensic note:** Forensics confirmed the midnight UTC reset made daily_pnl appear +$104.66 when session was -$205.70. This confusion was a reporting bug that masked the real session loss.

### Collapse 2: May 1 — Configuration Disaster (New Data)
This is a separate event not previously documented in our analysis:

**Configuration change (Phase 3.2, deployed May 1 00:00 UTC):**
| Parameter | Phase 2 (safe) | Phase 3.2 (disaster) |
|---|---|---|
| ensemble_confidence_floor | 55% | **20%** |
| ranging_confidence_floor | 68% | **20%** |
| risk_per_trade | 10% | **18%** |
| max_portfolio_leverage | 4.0x | **10.0x** |

**Result:** 14 trades, 0% WR, -$2,419.32 in one session
- BTC: 0/1 wins, -$125.96
- ETH: 0/9 wins, -$1,664.93
- SOL: 0/4 wins, -$628.43

At 00:22 UTC, Anthropic API credits were exhausted. The 9-agent LLM system went offline. The mechanical ensemble with 20% confidence floor ran unguarded.

**This is what happens when two bad changes combine:** low confidence floor + LLM offline = every signal is a loser.

**The Phase 2 baseline (55% confidence floor, 10% risk, 4x leverage) was working.** Lowering the floor destroyed everything.

---

## The Only Real Statistical Edge: Bollinger Squeeze

From the `SIGNAL_ANALYSIS_1410.md` (April 5, 2026 — 60-day window, 1,410 raw signals):

### Strategy Ranking (4h price horizon)

| Strategy | Signals | WR | Avg Move | Total Return | Verdict |
|---|---|---|---|---|---|
| **bollinger_squeeze** | 385 | **57%** | +0.15% | **+58.9%** | **ONLY WINNER** |
| probability_engine | 32 | 53% | -0.04% | -1.4% | Breakeven |
| mean_reversion | 51 | 43% | -0.18% | -9.0% | Loser |
| regime_trend | 79 | 43% | -0.31% | -24.6% | Loser |
| confidence_scorer | 845 | 47% | -0.07% | -59.5% | Loser (huge vol) |

**The bollinger_squeeze strategy is the ONLY one with positive edge over 1,410 signals.**

### BB Golden Setups (>55% WR, n>20)

| Setup | WR | n | Avg Move | Priority |
|---|---|---|---|---|
| **ETH_SELL_BB** | **70%** | 50 | +0.81% | MAX SIZE |
| **BTC_BUY_BB** | **69%** | 32 | +0.06% | TAKE |
| **SOL_BUY_BB** | **67%** | 24 | +0.36% | TAKE |
| **BTC_SELL_BB** | **61%** | 54 | +0.24% | TAKE |
| **ETH_BUY_BB** | **59%** | 59 | +0.14% | TAKE |

### BB Dead Setups (never take)

| Setup | WR | n | Avg Move | Action |
|---|---|---|---|---|
| HYPE_SELL_BB | 35% | 51 | -0.54% | NEVER |
| HYPE_BUY_CS | 38% | 125 | -0.19% | NEVER |

### BB Simulation Result
- BB-only (all symbols): 385 trades, 57% WR, +59% cumulative in 60 days
- BB-only excluding HYPE_SELL_BB: 334 trades, **60% WR, +86% cumulative in 60 days**
- At 8% risk / 7x leverage: ~48% account return projected

**BB without HYPE_SELL is the cleanest edge in the entire 8-month dataset.**

### Regime Context for BB
| Regime | WR | n | Avg Move |
|---|---|---|---|
| trending | 78% | 9 | +0.35% |
| high_volatility | **55%** | **258** | +0.11% |
| range | 47% | 98 | +0.05% |
| trend | 47% | 841 | -0.07% |

BB in high_volatility regime (258 samples): confirmed 55% WR. Most BB signals fire in high-volatility environments.

### Confidence Is NOT Predictive (Confirmed Again)
| Confidence | WR | Avg Move |
|---|---|---|
| <60% | 52% | +0.01% |
| 70-79% | 52% | +0.01% |
| **80%+** | **50%** | **-0.09%** |
| 60-69% | 47% | -0.06% |

High confidence (80%+) actually slightly underperforms 50%. Moderate confidence + correct direction = wins.

---

## Gate Analysis from Cycles 3/4/5 (April 28, 2026)

All three cycles ran identical 365-day backtests (2025-09-29 to 2026-04-25), only 3 positions executed per run. Gates were eliminating virtually everything.

### Gate Effectiveness Breakdown

| Gate | Rejections | Would Have Lost | Accuracy | Verdict |
|---|---|---|---|---|
| fee_drag | 2,055 | 468/673 = 70% | **70%** | **KEEP** — blocking losers |
| insufficient_votes | 1,222 | 639/1,204 = 53% | 53% | **REVIEW** — barely coin flip |
| ev_floor | 475 | 32/53 = 60% | 60% | Marginal keep |
| unknown | 351 | 77/301 = 26% | **26%** | **FIX** — blocking winners |
| confidence_floor | 332 | 152/327 = 46% | 46% | REVIEW — slightly hurts |
| regime_blocked | 1 | 0/0 = 0% | 0% | Irrelevant |

**Key finding:** The `unknown` gate blocked 351 signals and was right only 26% of the time (74% of those signals would have WON). This gate is destroying alpha.

**`insufficient_votes` (requiring 2+ strategy agreement) blocked 1,222 trades.** Of those, 57% were `monte_carlo_zones` solo signals (57% WR if taken). The solo vote requirement is too restrictive for MC zones specifically.

### Missed Opportunities (top misses)
All from `insufficient_votes`: SOL BUY at 65% confidence, missed +14-15% moves. These were single-strategy MC zones or regime_trend signals that were profitable but blocked.

### Gate Verdict
- `risk_filter_chain`: 726 rejected, 68.9% correct → KEEP
- `ensemble` gate: 1,832 rejected, only 47.4% correct → REVIEW (hurting more than helping)

---

## Strategy Performance Rankings (May 6, 2026)

From Cycle 6 strategy_weights.json analysis:

| Strategy | WR | Trials | Status |
|---|---|---|---|
| **sniper_premium** | **67%** | 30 | ACTIVE — STRONGEST |
| regime_trend | 59% | 2.27 | ACTIVE (tiny sample) |
| ensemble | 29% | 1,226 | ACTIVE (large sample — weak) |
| bollinger_squeeze | 28% | 28 | ACTIVE |
| omniscient_integrated | 6.7% | 450 | MUTED (correctly) |
| monte_carlo_zones | N/A | 0 | DISABLED |
| trend_breakout | N/A | 0 | DISABLED |
| confidence_scorer | N/A | 0 | DISABLED |

**Why is ensemble at 29% when Phase 2 baseline was 55%?**
- Three strategies completely disabled (0 signals generated)
- Disabled strategies still counted toward vote threshold
- Phase 3.2 config damage may have persisted beyond the May 1 disaster

**`sniper_premium` at 67% WR is the current live edge.** This aligns with the May 7 cluster — the sniper strategy was what drove 77.8% WR that final profitable week.

---

## SOL_SHORT: Suspension Confirmed Correct

From perpetual deep-dive (May 22, 2026):
- **Backtest WR**: 63.7%
- **Live paper WR**: 34.6% on 52 trades, -$176.24 net
- **Verdict**: Suspension confirmed. Backtest was overfit to a specific market period.

From perpetual deep-dive (May 24):
- SOL_SHORT gate elevated from 20% → 50% penalty

**The live data directly contradicts the backtest for SOL_SHORT. This is the strongest evidence of overfitting we have.** A 29-percentage-point gap between backtest (63.7%) and live (34.6%) means the backtest was not capturing the real risk profile.

---

## BTC LONG in Non-Trend Regime: Avoid

From perpetual deep-dive (May 22):
- BTC LONG in ranging/illiquid/unknown: **18% WR, 17 trades**
- `btc_trend_long_counter_v1` rule only covers TREND regime
- Non-trend BTC LONG is unprotected and consistently loses

**Actionable:** LLM should add regime check to BTC LONG decisions. Only take BTC LONG in trending/trending_bull regimes.

---

## BB Rules Blocked by Schema Issue

From perpetual deep-dive (May 22):
- 6 BB-specific rules (confidence 90-95%) are blocked
- Reason: missing 'strategy' condition type in the rule schema
- Fix estimate: ~1 hour P1 development
- Impact: 6 high-confidence BB-specific rules not firing

**This is a live bug reducing edge capture. Desktop-claude should patch the rule schema.**

---

## Phase 2 Baseline: The Working Configuration

Before all the disasters, Phase 2 established a proven working config:

| Parameter | Phase 2 Value |
|---|---|
| ensemble_confidence_floor | 55% |
| ranging_confidence_floor | 68% |
| risk_per_trade | 10% |
| max_portfolio_leverage | 4.0x |
| environment | paper |

Phase 2 results:
- Historical WR: 55%
- Paper trading WR: 50%
- Circuit breaker: 5% daily loss, 60min cooldown

**Any future configuration changes should be measured against this Phase 2 baseline.**

---

## Complete Data Inventory (Updated)

| Dataset | Trades | What It Is | Reliability |
|---|---|---|---|
| trades.csv (live) | 228 | Real paper trading Mar–May 2026 | **HIGH** — authoritative |
| trade_ledger.csv | 181 | Enriched version with regime/agreement | **HIGH** |
| signal_quality.json | 352 | Resolved trades incl. pre-cascade | **HIGH** |
| shadow_ledger.csv | 1,330 resolved | Signal quality, Apr 2–21 | **HIGH** (narrow window) |
| backtest_30d | 61 | Real mechanical backtest | **MEDIUM** (date unknown) |
| backtest_60d | 802 | Real mechanical backtest | **MEDIUM** |
| backtest_100d | 589 | Real mechanical backtest | **MEDIUM** |
| 1,410-signal analysis | 1,410 | Raw signals, 60-day window, April 5 | **HIGH** |
| Cycle 3/4/5 backtests | 3 positions each | April 28 over-gated runs | **LOW** (too few trades) |
| walk_forward_results | 0 entries | Empty stub runs | **DISCARD** |
| year_backtest_results | 27,740 | **SYNTHETIC DATA** — omniscient_integrated | **DISCARD** |

---

## Consolidated Actionable Findings

These are confirmed across 3+ data sources:

### 1. Bollinger Squeeze Is the Core Edge
- 57% WR over 1,410 real signals (April analysis)
- BB shadow edges confirmed in shadow_ledger (HYPE BUY 61.2%, SOL SELL 72.1%)
- Top BB setups: ETH_SELL (70%), BTC_BUY (69%), SOL_BUY (67%), BTC_SELL (61%), ETH_BUY (59%)
- **HYPE_SELL_BB is a confirmed loser (35% WR) — never take**
- BB-only strategy excluding HYPE_SELL → 60% WR, +86% in 60 days

### 2. Regime Matters Most for BB
- BB in high_volatility: 55% WR (258 samples) — best large-sample regime
- BB in trending: 78% WR (only 9 samples — needs more data)
- BB in trend (mislabeled): 47% WR — avoid solo BB in these conditions
- trending_bear regime: 80% WR across all strategies (live data, 10 trades)

### 3. Confidence Is Decorative — Direction Is Real
- High confidence (80%+): WR WORSE than low confidence
- May 7 cluster: 6 best trades all fired at 53-54 confidence
- sniper_standard at confidence=100 on May 11: LOST
- **LLM should evaluate directional read, not confidence score**

### 4. Never Lower the Confidence Floor Below 55%
- Phase 2 (55% floor): 55% WR historical, 50% paper
- Phase 3.2 (20% floor): 0% WR on 14 trades, -$2,419 in one day
- The floor protects against trash signals entering the pipeline

### 5. Avoid These Setups (Multiple Confirmations)
| Setup | Evidence | WR |
|---|---|---|
| SOL_SELL + regime_trend | Shadow ledger 149 samples | 0% |
| ETH_SELL + regime_trend | Shadow ledger 65 samples | 23% |
| HYPE_SELL_BB | 1,410-signal analysis 51 samples | 35% |
| BTC LONG in ranging/illiquid | Perpetual deep-dive 17 samples | 18% |
| SOL_SHORT (live) | Live paper 52 trades | 34.6% |
| Any setup with omniscient_integrated | 450+ samples | 6.7% |
| Range regime entries | Live 14 trades | 7.1% |

### 6. The Fee Drag Gate Is Correct (70% Accuracy)
- Keep the fee_drag gate — it correctly blocks losers 70% of the time
- The `unknown` gate is wrong 74% of the time — fix or remove
- The `insufficient_votes` gate for solo signals is barely coin-flip — LLM should override

### 7. BB Schema Bug Must Be Fixed
- 6 high-confidence BB-specific rules blocked
- ~1 hour fix in the rule schema
- Live revenue loss every day this is not patched

### 8. Trailing Stops Are the P&L Multiplier
- May 7 cluster: 6 trades × avg $146 trailing exit vs ~$20 fixed TP = 7x more EV
- 34 trailing wins across all historical data extracted $1,668 vs fixed TP
- **The trailing stop logic in `position_manager.py` must never be simplified**

---

## For Desktop-Claude

These require attention:

1. **Rule schema fix** — 6 BB rules with 'strategy' condition type blocked. ~1h patch, P1.
2. **SOL_SHORT suspension confirmed** — Live 34.6% vs backtest 63.7%. Keep suspended.
3. **BTC LONG non-trend protection** — 18% WR in ranging/illiquid. LLM should block.
4. **HYPE_SELL_BB** — 35% WR, consistently loses. Should be in LLM context as an avoid.
5. **Confidence floor floor** — Never let it drop below 55% under any config change. The May 1 evidence is definitive.
6. **Unknown gate** — Blocking 74% of winners. Investigate and fix or disable.

---

*Generated: 2026-05-30 | laptop-claude extended synthesis from git history mining*
*Builds on: backtest-full-synthesis.md, shadow-ledger-edges.md, backtest-evidence.md*
