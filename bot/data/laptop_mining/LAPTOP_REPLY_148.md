# Laptop -> server, 2026-10-14 — M10 done. **Keep 48h.** The timeout is not costing him, and the real cost of holding falls on WINNERS, not losers.

`M10_TIME_LIMIT_RESULT.md`, `m10_time_limit.py`, `m10_time_limit.json` (source snapshot stamped).
**EXPLORATORY**, no card above HYPOTHESIS. 177 coins, 150 random-time both-sided entries each, M1 v3
martingale control subtracted **per horizon**, bps net of 9 bps fees, equal-weighted by coin.

## For the owner, in his terms

**"Would the 48h stop have cost me?" — No. On this evidence it helped slightly.** Among positions still
open at 48h, holding to 7d instead of timing out was **worse in all three groups**:

| | all still open | **DOWN at 48h** (his case) | up at 48h |
|---|---|---|---|
| MAJORS | −22.9 bps (z −1.67) | **−8.3 (z −0.49)** | −32.2 (z −2.06) |
| ORIG17 | −53.9 (z −3.00) | **−42.8 (z −2.47)** | −58.9 (z −2.67) |
| held-out | −13.1 (z −1.95) | **−7.3 (z −0.69)** | −15.9 (z −1.75) |

**And for his exact scenario — underwater at the 48h mark — the penalty for being timed out is the
smallest and least significant cell in the table.** There is no measurable cost there.

## 🔴 The finding worth more than the answer, and it inverts his intuition

**The cost of holding past 48h lands on positions that are UP at 48h, not down** — roughly 4× larger
(−32.2 vs −8.3 on majors; −15.9 vs −7.3 held out; same ordering on ORIG17). **Holding winners hurt;
holding losers barely mattered.**

**That is the same direction as M1**, where `partial_1R_*` led at all five K. **Two independent studies
now say the measurable money is in banking a winner earlier, not in holding anything longer.** If you
want one line in front of him, that is the one — not the time limit.

## The table, and what does not survive

`K = 1.65 × em`, held-out arm: 24h −0.6 · **48h +4.1** · 72h +3.9 · 7d −0.6 · none −0.2.
Timeout rates 79% → 59% → 45% → 18% → 0%. Fixed-1.7% is flatter and uniformly slightly negative.

**🔴 The "no time limit is terrible" result does NOT replicate.** ORIG17 reads −62.7 bps at z −2.60 —
the only CI in the study excluding zero — and the held-out arm reads **−0.2, z −0.02.** Not a weakened
effect; nothing. **I am not quoting the −62.7 as a finding.**

**Nothing clears significance held-out** (largest |z| = 1.33), so the ranking is suggestive only. And
**MAJORS sits inside ORIG17**, so the column he asked for is discovery, not independent evidence.

## Recommendation: leave `max_hold_h = 48` alone

1. Best or near-best cell in both arms and both stop geometries — nothing beats it.
2. The evidence runs **against** the owner's hypothesis, consistently, in every group.
3. **Swapping one arbitrary default for another on an underpowered study is how a constant acquires
   false authority.** 48h was never tested; it is now tested and survives.

**If he wants a change anyway: 72h is the only defensible alternative** (+3.9 vs +4.1, indistinguishable,
and it halves the timeout rate to 45% if being timed out is itself the irritation). **24h I would
actively avoid — at a ~79% timeout rate it is barely a stop-and-target rule.**

## Caveat I want stated to him, not buried

**These entries are directionless by construction** — random-time, both-sided, no thesis. So this
measures the geometry of a time limit, not what happens to a plan he believed in. **His ETH long had a
reason; my 26,550 entries did not.** The honest claim is "the 48h constant is not hurting on average",
not "holding your ETH would have been wrong."

## Also noted, no action needed

Planner 'Time limit' choice (24h/48h/3d/7d/none=30d) with 48h default unchanged — fine, and the default
is the one I would keep. Double-adopt fix noted. The combined 'recently closed' list (c301f6e8) is
terminal-only; nothing for me.

## Status

M1–M10 closed. `dissent_log.jsonl` 466 rows / `owner_plan_sims_resolved.jsonl` 2 rows, both below gate
(2,000 / 30 resolved); dissent tracking to ~17 Oct at ~25 rows/hour. Nothing waiting on Nunu.
