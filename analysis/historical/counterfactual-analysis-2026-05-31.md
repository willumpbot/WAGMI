# Counterfactual Analysis — 2026-05-31

*Analyzed by laptop-claude from `bot/data/counterfactuals/scenarios.json`*
*Coverage: March 25 – April 23, 2026 (pre-LLM-first era, historical import)*

---

## Summary

352 counterfactual scenarios tracked — all resolved. Two types:

| Type | Count | Key Finding |
|---|---|---|
| exit_timing | 134 | 81% of the time TP1 was better than what the bot did |
| veto_override | 218 | 100% correct — but see caveat below |

---

## Exit Timing (134 scenarios)

The system tracked what would have happened if exits had been taken at TP1 vs. the actual exit (SL, trailing stop, or waiting for TP2).

**Result:** 81% of actual exits (109/134) would have banked MORE by taking TP1 instead.

| Metric | Value |
|---|---|
| Cases where actual exit was better | 25 (19%) |
| Cases where TP1 would have been better | 109 (81%) |
| Cumulative delta (actual vs TP1) | +477.22% |
| Average gain left on table per trade | +3.56% |

**Interpretation:** The bot was consistently too greedy — it let winners reverse into SL or trail into a smaller gain rather than banking at TP1. Over 134 trades, this represents roughly 477% of compounded edge that was surrendered to reversal risk.

**Action:** Exit Agent should bias toward TP1 capture in high-volatility regimes. A good rule: if ATR% is elevated AND we're at TP1, take it rather than holding for TP2.

---

## Veto Override (218 scenarios)

The system tracked what would have happened if vetoed entries had been taken.

**Result:** 100% of vetoes were correct (all vetoed entries would have lost).

| Metric | Value |
|---|---|
| Total vetoes tracked | 218 |
| Correct vetoes (saved loss) | 218 (100%) |
| Wrong vetoes (missed winner) | 0 (0%) |
| Total saved from correct vetoes | +980.47% |
| Total missed from wrong vetoes | 0% |

**By symbol:**

| Symbol | Vetoes | Accuracy | Saved |
|---|---|---|---|
| BTC | 33 | 100% | +139.7% |
| ETH | 53 | 100% | +256.5% |
| HYPE | 53 | 100% | +436.1% |
| SOL | 79 | 100% | +148.1% |

### Caveat: These are NOT LLM veto decisions

Virtually all 218 vetoes have `reason = "LLM_FIRST: LLM pipeline failure"`. This means the pipeline was broken at the time (pre-fix era), and the veto happened because the LLM failed to respond — not because the LLM made a good judgment call.

The "100% correct" rate reflects two compounding facts:
1. The pipeline was failing on nearly all signals during March-April (the gates we fixed)
2. The market was crashing April 23-28 — most BUY signals during that period would have lost

**This data cannot be used to validate LLM veto quality.** Real LLM veto quality measurement starts with the overnight session (May 31, 2026) on the desktop machine. Desktop confirmed their first counterfactual resolution at 16:12 UTC: HYPE BUY veto was correct (-6.23% if entered).

---

## Model Routing Audit (historical `agent_performance.jsonl`)

The laptop's agent_performance.jsonl covers the old bot era (March-May 2026) plus today's backtest runs. The live bot's overnight session data is on the desktop machine.

**Old bot era model breakdown (15,143 entries):**

| Model | Count | % |
|---|---|---|
| claude-haiku-4-5-20251001 | 8,768 | 57.9% |
| claude-sonnet-4-5-20250929 | 4,825 | 31.9% |
| claude-haiku-4-5 | 948 | 6.3% |
| claude-sonnet-4-6 | 602 | 4.0% |

Haiku-dominant as expected for the old bot (Haiku for Regime/Risk/Quant, Sonnet for Trade/Critic). The 602 Sonnet-4.6 entries are from today's backtest runs (v2 + v3).

**Per-role breakdown (all history):**
- regime: ~87% Haiku ✅
- risk: ~86% Haiku ✅
- quant: ~86% Haiku ✅
- trade: ~64% Sonnet-4-5 + 20% Haiku (older) ✅ (Sonnet is correct for Trade)
- critic: ~85% Sonnet-4-5 ✅ (Sonnet correct for Critic — NOT Opus as overnight briefing suggested)
- exit: 100% Haiku ✅
- learning: mixed

**Desktop's 77% Opus finding** applies to the OVERNIGHT live bot session (data on desktop machine only, not in this file). Per desktop's briefing, Opus is over-routing during live operation. This needs investigation on desktop side — the per-agent model overrides (`AGENT_CRITIC_MODEL`, etc.) are not set in `.env`, so the usage tier system is defaulting everything to Opus for some trigger types.

---

## Key Recommendations

1. **Exit at TP1 more often** — 81% WR on TP1 capture vs. trailing/holding is a strong signal. Consider an Exit Agent rule: in high_volatility regime, always take TP1.

2. **Veto quality baseline established** — but it's not LLM quality yet. Need 30+ LLM veto resolutions before drawing calibration conclusions.

3. **Desktop model routing** — Critic and Regime calling Opus is ~5x cost overkill. Per CLAUDE.md spec: Regime=Haiku, Critic=Sonnet. Set `AGENT_REGIME_MODEL=claude-haiku-4-5-20251001` and `AGENT_CRITIC_MODEL=claude-sonnet-4-6` in `.env` on desktop.
