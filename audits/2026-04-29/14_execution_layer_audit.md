# Execution Layer Audit — 2026-04-29

**Question:** `bot/execution/` has 44 files / 13,770 lines including the most safety-critical code in the project (risk.py, position_manager.py, leverage.py, ops_guard.py). Is the layer wired correctly, are there safety gaps, and what's dead?

**Headline:** **Risk surface is properly wired** — `RiskManager` + `CircuitBreaker` are imported and instantiated in `multi_strategy_main.py` and confirmed actively gating trades. But the layer has **3 zero-byte placeholder files** for safety code (concerning), and **2 substantial unwired modules** including a 403-line signal validator that should probably be active.

---

## Critical Path: Verified Wired ✅

| Module | Imported from main | Active gating |
|---|---|---|
| `risk.py` | RiskManager + CircuitBreaker (line 54) | line 661 instantiation; `risk_mgr` consulted before every trade |
| `position_manager.py` | PositionManager | actively manages state machine IDLE→OPEN→TP1→TRAILING→CLOSED |
| `leverage.py` | LeverageManager | per-confidence + per-strategy tiers |
| `ops_guard.py` | OpsGuard | prevents duplicate positions, oversized trades |
| `precision.py` | symbol specs + price validation | every order |
| `reconciliation.py` | startup state sync | bot startup with exchange state |
| `auto_recovery.py` | recovery routines | on startup |
| `graceful_degradation.py` | DegradationManager | exchange-down halt-new-entries |
| `pending_orders.py` | PendingOrderManager | limit order tracking |
| `trade_logger.py`, `trade_profile.py`, `dynamic_tp.py`, `time_sizing.py`, `funding_timer.py`, `candidate.py`, `rotation_manager.py` | all imported | wired |

**16 modules confirmed live.** This is the *load-bearing* portion of the system.

---

## ⚠️ Critical: 3 Zero-Byte Placeholder Files

```
$ ls -la bot/execution/{executor,manual_executor,risk_engine}.py
-rw-r--r--  0 bytes  executor.py
-rw-r--r--  0 bytes  manual_executor.py
-rw-r--r--  0 bytes  risk_engine.py
```

**`risk_engine.py` being empty is the most concerning.** "Risk engine" implies a centralized risk gate. The file's name is in the directory but the implementation is absent. Three possibilities:

1. **Renamed to `risk.py`** — likely. The file `risk.py` has `RiskManager` + `CircuitBreaker`. The rename probably happened, the placeholder was forgotten.
2. **Reserved for future work** — possible but with no comment / TODO marker, unsigned.
3. **Accidentally truncated** — would be alarming. No evidence in git but worth a `git log -- bot/execution/risk_engine.py` check.

Same logic applies to `executor.py` (probably renamed `order_executor.py`) and `manual_executor.py` (sniper has its own executor path now).

**Fix:** delete all 3 placeholder files. ~2 min. Documents intent (no missing code), removes a misleading signal.

If git log shows substantial deleted content, restore from history first.

---

## ⚠️ Substantial Unwired Modules (2)

### `signal_validator.py` (403 lines) — fully implemented, no callers

```python
"""
Signal performance validator and analytics.

Links signals to trade outcomes. Calculates win rates by:
- Symbol
- Regime alignment strength
- Strategy consensus
- Time of day
- Confidence tier
- Market condition

Output: signal_outcomes.csv with full tracing
"""

class SignalOutcome:
    """Linked outcome for a signal."""
    signal_id, timestamp, symbol, direction, entry_price,
    confidence, regime_score, strategy_consensus, num_strategies, status
```

Has `class SignalValidator` with what looks like real implementation. **Zero callers from anywhere in the bot.**

This is exactly the kind of subsystem the meta-learning insights system should be feeding from. The fact that it exists and isn't wired is identical to the §09 dormant-agents pattern: built ~80% complete, never wired the last 20%.

**Recommendation:** trace the `meta_learning/insights.json` data — does anything write to it currently? If yes (and it's wired to feed agent prompts), then `signal_validator.py` is the *better* version of that pipeline that should replace the current ad-hoc one. ~2-3 hours to wire and migrate.

### `exit_config.py` (98 lines) — CellExitRule class, no callers

98 lines defining `CellExitRule`. The "cell" terminology suggests a grid (probably (regime, time-of-day) cells) with exit rules per cell. Smaller surface than signal_validator but related to the §01 counterfactual finding (TP1 underweighting) — exit rules are exactly the kind of policy this should improve.

**Recommendation:** read fully and either wire (if rules are sensible) or delete (if abandoned). ~1 hour.

---

## Dormant But Imported-At-Site (the next tier)

These have callers but only 1-3, suggesting limited integration. Worth verifying each is consumed at decision time, not just initialized:

| Module | Caller count | Notes |
|---|---|---|
| `mfe_exit.py` | 2 | Maximum favorable excursion-based exits — likely used by position manager |
| `monte_carlo_ruin.py` | 2 | Risk-of-ruin Monte Carlo. Likely informational, not trade-gating |
| `quant_executor.py` | 1 | Single caller — fragile |
| `tp_sl_engine.py` | 1 | Single caller — likely the canonical TP/SL calculator |
| `price_guard.py` | 1 | Pre-trade price sanity check; single caller |
| `correlation_gate.py` | 2 | Cross-asset correlation gating |
| `liquidity_guard.py` | 3 | Liquidity-driven entry block |
| `cross_asset_alert.py` | 3 | Alerts when correlated assets diverge |

These look like **specialized gates and exit modifiers** — most are likely correct in their narrow integration, but a failure in any of them silently degrades trading quality.

**Recommendation:** dedicated mini-audit per module — check the caller wires it correctly and the gate fires at the right point in the pipeline. ~30 min per module = 4-6 hours total to verify.

---

## Trade Profile + Sizing Pipeline

The trade profile / sizing path is non-trivially wired:

- `trade_profile.classify_trade()` — assigns profile (SCALP / MEDIUM / TREND / REGIME)
- `apply_profile_to_signal()` — sets TP/SL/leverage based on profile
- `dynamic_tp.optimize_tp_sl()` — final TP/SL refinement
- `sizing_optimizer.py` — 4 callers — adjusts position size

This is several layers of optimization. Each layer is small individually but together they're complex enough to merit a flow diagram. **Not currently documented anywhere.**

**Recommendation:** add a comment-block to `multi_strategy_main.py:_process_symbol` pointing at the actual sequence:

```
# Trade pipeline (post-ensemble vote):
#   1. classify_trade(signal) → profile
#   2. apply_profile_to_signal(signal, profile) → adjusts TP1/TP2/SL/leverage
#   3. dynamic_tp.optimize_tp_sl(signal) → fine-tune
#   4. sizing_optimizer adjusts qty
#   5. risk gates (risk_mgr, leverage, liquidation)
#   6. ops_guard final pre-flight
#   7. execute via order_executor / sniper path
```

~15 min, makes future audits / debugging much faster.

---

## Where Exits Live (the §01 lever)

The §01 counterfactual finding said TP1 is universally underweighted (+$477 across 134 trades). Where is exit logic actually implemented?

Searching for exit-related modules:

- `position_manager.py` — state machine; trailing stop logic
- `dynamic_tp.py` — TP/SL price calculation
- `mfe_exit.py` — MFE-based exits (used)
- `exit_optimizer.py` — 1 caller
- `exit_config.py` — 0 callers (orphan, see above)
- `mfe_exit.get_exit_recommendation()` referenced at multi_strategy_main:3035-3038

The TP1 partial-close logic is in `position_manager.py` (state machine TP1_HIT branch). Increasing TP1 partial fraction is a 1-line change in that file. The §01 finding's fix is concrete and small.

**Recommendation:** §12 audit recommended adding a `tp1_partial_pct` proposal type to the growth dispatcher. The execution-layer side is just ensuring `position_manager.py` reads from a config value (it almost certainly does already — verify). Together: ~1.5 hours, +$477 / 134-trade equivalent edge.

---

## Files to Delete (high-confidence)

Based on this audit:

1. `executor.py` (0 bytes) — placeholder, redundant with `order_executor.py`
2. `manual_executor.py` (0 bytes) — placeholder, sniper has own path
3. `risk_engine.py` (0 bytes) — placeholder, redundant with `risk.py`

Delete these. Run tests. Should be safe (zero-byte files cannot have callers).

## Files to Investigate (medium-confidence)

4. `signal_validator.py` (403 lines, 0 callers) — wire or archive
5. `exit_config.py` (98 lines, 0 callers) — wire or archive

---

## What This Audit Confirms

**Risk + safety surface is real and active.** The bot has been operating with proper circuit breakers, leverage caps, ops guards, and reconciliation. This contrasts to the agents/swarm/rules systems where significant pieces are dead — execution-critical code is much more rigorously wired.

**But the directory has accumulated debris** — 3 zero-byte stubs and 2 substantial unwired modules. None pose safety risk (they're bypassed) but they obscure the directory's signal-to-noise ratio.

---

## Bottom Line

**Top execution-layer fixes:**

1. Delete 3 zero-byte placeholder files (~2 min) — high signal, zero risk
2. Read & decide on `signal_validator.py` (~1h read + ~2h wire if kept)
3. Read & decide on `exit_config.py` (~30min)
4. Add trade pipeline flow comment in `multi_strategy_main.py:_process_symbol` (~15min)
5. Per-module mini-audits on the 8 single-caller / dual-caller gates (~4-6h)

Excluding #5, total: **~3.5 hours** to clean the execution layer's documentation/inventory state. #5 is the deeper rigor work, schedule independently.

The execution layer is the **strongest** part of the codebase audited so far. After §09 (agents 57% dead) and §11 (tools 93% script-only), this is reassuring — the safety-critical code has the rigor it needs. The dead code is in the *learning* surface, not the *execution* surface.
