# Postmortem: shorting into 4h high-volatility (the NEAR −$8.70 case)

**2026-09-27.** Triggered by the owner's read of the recent NEAR SHORT loss:
"it should've been a long and our setup knew that." Checked against
`data/trade_ledger.csv` (287 closes). Small-file, read-only.

## The owner's instinct, tested

**CORRECTION (added after the join-gap investigation).** My first pass claimed the
NEAR decision was "internally conflicted (confidence_scorer SELL vs
multi_tier_quality LONG)." That was wrong — I read a `decisions.jsonl` record that
was a portfolio-wide *trigger* log, not this trade's entry decision. The actual
NEAR entry decision lives in `agent_performance.jsonl` (pipeline `915b5357-057`,
21s before open) and shows the pipeline **agreed** to short: trade=go,
risk=size0.3/override=reduce, critic=approve. So at the per-trade level the setup
did **not** "know it should be a long" — every agent signed off on the short.

The owner's instinct is therefore supported by the **aggregate regime pattern
below, not by this specific decision.** That distinction matters: the fix is a
regime-level guard, not "the bot ignored a signal it had."

## What the ledger says

Overall by side (the general picture — "should've been a long" is NOT a blanket rule):

| side | n | net | WR |
|---|---|---|---|
| LONG | 114 | **−$795.59** | 36% |
| SHORT | 174 | **+$539.43** | 36% |

Shorts are historically the bot's profitable side; longs are the drain (consistent
with the long-drain finding in memory). So in general, shorting is *not* the error.

**The exception — a losing pocket inside the winning side:**

SHORT trades by 4h regime:

| regime_4h | n | net | WR |
|---|---|---|---|
| (blank) | 154 | +$644.84 | 38% |
| **high_volatility** | **11** | **−$103.26** | **9%** |
| consolidation | 8 | −$1.19 | 38% |
| trend | 1 | −$0.96 | 0% |

The `consolidation-1h + high_volatility-4h SHORT` setup specifically: **n=11,
−$103.26, 9% WR**, composed of NEAR (7), SOL (2), HYPE (2). NEAR is the worst
offender but it is **not** NEAR-alone — it's a regime×side pocket. Shorting into
4h high-volatility gets squeezed.

NEAR alone: SHORT n=7 −$89.66 (14% WR) vs LONG n=2 +$1.13 (50% WR).

## Honest verdict

- **The owner is right for THIS regime, not in general.** Shorts win overall;
  shorts *into 4h high-volatility* lose hard (9% WR). The NEAR short was in exactly
  that pocket, and the pipeline had a LONG signal it discarded.
- **This is a candidate forward-veto**: "don't short when regime_4h ==
  high_volatility" (or size it down). Mechanism is plausible (shorting into a
  vol spike = squeeze risk), and it spans 3 symbols, not one.

## Caveats (do not overclaim)

1. **n=11 is below the owner's n≥13 graduation gate.** Per standing policy
   (no hardcoded directional blocks; data-learned vetoes at n≥13), this is NOT
   yet actionable as a live block — it needs ~2 more instances. Log it, watch it.
2. **`regime_4h` is mostly BLANK** (154 of 174 shorts have no 4h label — the
   known measurement gap). So this pocket is n=11 out of only ~20 labeled shorts;
   the true size is unknown until regime_4h logging is fixed. **Fixing regime_4h
   population is the prerequisite** to trusting this at scale.
3. NEAR LONG n=2 is far too thin to call longs "good" on NEAR.

## Why this matters for the lineage work

This is the exact shape the decision-lineage tracer should surface automatically:
a trade taken into a regime where that side loses — *even with all agents in
agreement* (which is what makes it dangerous; nothing internal objected). If the
tracer had flagged "you are shorting into 4h high-vol, where this side is 9% WR"
at decision time, it's a legible, actionable warning — not hindsight.
