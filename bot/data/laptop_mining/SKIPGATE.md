# Skip-gate: **no evidence the bot's confidence floor is costing money — and the tempting version of this result was the project's oldest error wearing a new hat.**

_2026-10-12. `skipgate.py`, running `PREREG_SKIPGATE_2026-10-12` (sealed `7f6ffc80`, sha
`3705561eb4265c1d`). **143,813 resolved skipped signals over 83 days**, local, zero API cost._

---

## 1. The answer

**VERDICT: UNDERPOWERED, and the point estimate is negative anyway.**

| `confidence_floor_*`, net of 9 bps round trip | |
|---|---|
| pooled per-signal mean | **+0.211%** |
| **equal-weighted day mean** | **−0.183%** |
| | **🔴 the signs DISAGREE** |
| CI95 (day-block, 45 days) | **[−0.435%, +0.085%]** — includes zero |
| z | **−1.37** against a bar of 2.39 |
| walk-forward halves | −0.268% / −0.101% — **sign-stable, both negative** |
| **MDE (simulated, 80% power)** | **44 bps** against a pre-committed floor of **16 bps** |

**All three families are null.** `graduated_rule_veto*`: eq-day **+0.009%**, z +0.02.
All other reasons pooled: eq-day **+0.091%**, CI [−0.262%, +0.472%].

## 2. 🔴 The trap, which is the actual finding here

**Pooled says the skipped signals were profitable. Day-weighted says they lost. The pooled figure is
the one I would have reported if the prereg had not fixed the statistic in advance.**

| | |
|---|---|
| what pooling says | **+21 bps per skipped signal** → *"the bot is too picky, loosen the floor"* |
| what the day mean says | **−18 bps** → *"the floor is not costing anything"* |

**The cause is the same one that has bitten this project repeatedly:** 115,065 floor-rejected signals
sit on only **45 days**, so a handful of very high-signal days dominate any per-signal average. Those
days happen to be the ones where rejected signals looked good. **On a typical day they lost.**

**This is the M2 error** — a pooled mean read +0.09% when the day-weighted truth was −3.93% — and it
is the fourth time the same shape has appeared. **The only reason it did not become a reported
finding is that the prereg named the equal-weighted day mean as governing before any number was
computed.**

## 3. 🟢 Both placebos passed, so the null is informative rather than empty

| placebo | result |
|---|---|
| **day-label shuffle**, 2,000 draws | rejection **2.6%** — size OK (slightly conservative) |
| **shuffled reason within day** | eq-day −0.212%, **z −1.62, null as required** — so the families differ by *reason*, not by which days each was active on |

**A null with a working placebo means "we looked and found nothing."** A null with a broken placebo
would mean "we could not have found anything," which is a different and far weaker statement.

## 4. Why this is UNDERPOWERED rather than AGAINST

The simulated floor is **44 bps**; the effect worth detecting was the gross aggregate (**+25 bps**)
less cost (**9 bps**), i.e. about **16 bps**. **The test cannot see an effect 2.75× smaller than its
own resolution**, so a null here is not evidence that the floor is harmless — only that this data
cannot show it either way.

**The binding constraint is 45 day-clusters, not 115,065 signals.** More signals per day do not
help; more *days* would.

## 5. What this does not say — stated in the prereg, repeated here

- **No money figure, and no recommendation to change the floor.** A per-signal counterfactual is not
  portfolio P&L: taking ~115k rejected signals was never possible given risk budget, position
  limits, correlated symbols, and positions already open. **A positive result would not have
  justified lowering the floor either.**
- **These counterfactuals use each signal's own `sl`/`tp` geometry**, so they inherit it and are not
  independent evidence about the bot's 1.66% stop.
- **No per-reason fishing.** 867 distinct `skip_reason` strings exist; exactly three pre-specified
  families were tested, and the floor-value breakdown is in the script as shape only.

## 6. What I would tell the owner — three rules, one number each

1. **No, the bot is not leaving money on the table by being too picky.** Day-weighted, its rejected
   signals lost **18 bps** each.
2. **The number that said otherwise was a weighting artefact.** Pooled it looked like **+21 bps**,
   and 115,065 signals sitting on just **45 days** is why.
3. **This question needs more days, not more signals.** The test can only resolve **44 bps**; the
   effect worth finding was **16**.

## Limits
- **45 day-clusters** for the primary family (83 across all reasons). That is the sample size.
- **Gross P&L verified gross**: 1,128 of 1,131 would-be stop-outs show exactly minus the stop
  distance, so 9 bps was subtracted manually. **No slippage, no funding, no priority fees** — so
  even the negative figure is optimistic.
- **The `confidence_floor_*` family appears on only 45 of 83 days**, because the floor value changed
  over the window. The floor-by-value table is descriptive and several of its rows rest on 3 days.
