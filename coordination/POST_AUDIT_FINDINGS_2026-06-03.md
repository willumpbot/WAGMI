# Post-Audit Findings — 2026-06-03 ~20:00 UTC

**From:** desktop-claude (after dispatching 3 parallel Explore agents)
**Context:** Nunu directive to "work effectively, leave no stone unturned." Agents found 4 concrete issues.

## Cross-check with laptop's 5c91984 + 097ef2d

Laptop already solved the Risk Agent sizing root cause MORE elegantly than my proposed cap:
- 5c91984: `portfolio_ctx` missing `symbol` key → Risk Agent saw 0 positions → sized blind
- Injects `sizing_constraint.max_risk_pct` as concrete number to Risk Agent
- Risk Agent self-constrains; my proposed cap is redundant safety net

I applied a defensive hard-cap on `desktop-overdrive-2026-05-30` at `coordinator.py:1488` (cap risk_pct at config.risk_per_trade=1.5%). It can stay or be reverted — does not conflict with laptop's design, but may be over-restrictive vs the architecture's intent of "10% when book empty + 2% stop." Recommend: keep as defense-in-depth or revert if you prefer laptop's design pure.

## Findings from the 3 parallel Explore agents

### 1. Quant Brain Kelly weights ARE fee-bug poisoned (CONFIRMS Nunu's hypothesis)

- Base WRs hardcoded in `quant_brain.py:185-195` (untouched since 2026-05-17, pre-fee-bug — likely OK as priors)
- BUT `kelly_engine.py:77-180` recomputes Kelly weights from `trade_ledger.csv` PnL column
- That PnL was computed under 45 bps fees (10x overstated)
- Result: Kelly weights are biased low → bot rejects setups with marginal "negative Kelly" that would be positive at real 4.5 bps
- **NO recompute script exists.** To fix: rebuild ledger PnL at 4.5 bps, regenerate Kelly.

**Recommended action for laptop:** write `scripts/recompute_ledger_at_corrected_fees.py` that rebuilds `trade_ledger.csv` net_pnl column with proper fees, backs up the original. Then trigger Kelly regen.

### 2. SOL SHORT toxic block — `bot/feedback/graduated_rules.json:841`

`SOL_SHORT_full_block` rule:
- Created 2026-04-28, A/B_ACTIVE at 100% gate, confidence 88%
- Evidence: WR=33%, n=30 live trades, PnL=-$154.35
- File itself documents at line 1037: "SOL_SHORT_full_block suspension may be stale ... needs human review to unsuspend"
- Conflicts with historical backtest: WR=63.7% on n=179 (+$5807)

**Already addressed by laptop in 097ef2d** ("SOL toxic threshold" mentioned in commit). Good.

### 3. Phantom-detection ledger gap (`auto_recovery.py:444`)

Phantom positions marked `state="CLOSED"` without `trade_ledger.record_trade()` write. Would orphan PnL in live mode.

**Caveat:** auto_recovery.py:420 SKIPS phantom detection in paper mode entirely. So this doesn't explain HYPE LONG #15's silent disappearance from our paper run.

**Real cause for HYPE #15 unknown — still mystery.** Either a normal close path failed silently (need to find which), or the position was managed by code I haven't traced. Worth a focused investigation.

**For live mode (when we go production):** fix the phantom path to write ledger row. Suggested signature change: pass `trade_ledger` to `startup_recovery()` and call `trade_ledger.record_trade()` on phantom close with `exit_type='reconciliation_phantom'`.

### 4. Pattern Nunu flagged — hardcoded vs learned

Nunu's pattern-recognition observation: bot has hardcoded values everywhere that aren't tracking live truth.

Concrete inventory of HARDCODED in the decision path:
- `quant_brain.py:185-195` — base WR priors (per-symbol-side, static since 2026-05-17)
- `prompts.py:1230-1236` — conditional multipliers (0.7x solo penalty, 0.85x dead hours, 1.15x prime hours)
- `coordinator.py:1480` — risk_pct fallback `0.10 * sz_mult` (10% baseline when Risk Agent omits)
- `bot/feedback/graduated_rules.json` — rule thresholds (some now over a month old)
- `kelly_engine.py:29` — KELLY_FLOOR = 0.15 (hard floor)

Each of these is a "tax" on the LLM's reasoning that may not reflect current market truth. The Kelly recompute (#1 above) is the highest-leverage fix; the conditional multipliers (0.7x, 0.85x) deserve their own re-derivation from fresh data.

## What I'm doing next

- Continue live monitoring of ETH SHORT #16 (still open, ~+$170 uPnL)
- NOT applying any more code changes without your visibility
- Will flag close events + new GO decisions

## Coordination question for laptop

Should we plan a coordinated restart that picks up your 4 fixes + my Risk Agent cap (or your design alone if you prefer)? The live bot is still running pre-fix code on `desktop-overdrive-2026-05-30`. State persistence proved out earlier (15:20 restart recovered ETH #16 cleanly).

-- desktop-claude
