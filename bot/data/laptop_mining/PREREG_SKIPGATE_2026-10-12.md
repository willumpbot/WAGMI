# PREREG — is the bot's confidence floor rejecting profitable signals? **Sealed before any reason × outcome statistic was computed.**

_`counterfactual_resolved`: **145,446 skipped signals, every one resolved**, 2026-05-30 → 10-08,
already on disk, zero API cost. This is the "which signals" question for the **bot**, following the
settled finding that the exit rule is not the lever. Owner asked for large task work on the local
data; this is it._

---

## 0. 🔴 What I have already looked at, declared so it cannot be laundered

**Marginal distributions and instrument checks only — no reason × outcome quantity:**

| seen | value |
|---|---|
| `resolved` | **True on all 145,446** — no resolution survivorship |
| `hypothetical_pnl_pct` coverage | 143,813 of 145,446 (98.9%) |
| its **aggregate** mean / median | **+0.252% / 0.00%**, p10 −1.96, p90 +2.80 |
| would-hit rates | SL 28.8%, TP1 13.9%, TP2 7.7% |
| `skip_reason` | **867 distinct**; `confidence_floor_*` dominates (43,902 at floor 71; 33,708 at 80), `graduated_rule_veto*` 17,062 |
| **distinct days** | **83** |

**The aggregate mean is used below only for power.** I have computed nothing per-reason, per-day,
or per-floor-value.

## 1. 🔴 Two facts that reframe the whole thing

**(a) `hypothetical_pnl_pct` is GROSS.** Verified: of 1,131 rows that would have stopped out,
**1,128 show P&L exactly equal to minus the stop distance.** No fees, no slippage, no funding. The
bot's round-trip cost is **9 bps**, so **every figure must be reported net of 9 bps as well as
gross**, and the gross number alone is not a finding.

**(b) 145,446 rows is NOT the sample size. 83 days is.** ~1,752 signals per day means the
clustering unit is overwhelmingly the day. **I described this to the owner as "495× the executed-trade
sample" and that was wrong on the measure that matters** — it is 83 clusters, the same order as the
83 call-days behind the fat-tail work. It is genuinely better only because each day-mean rests on
~1,752 observations instead of ~5, so between-day variance dominates rather than within-day noise.

## 2. The test

| | |
|---|---|
| **population** | skipped signals with `hypothetical_pnl_pct` present |
| **primary outcome** | `hypothetical_pnl_pct` **− 9 bps** (net), per signal |
| **primary contrast** | is the net day-mean of the **`confidence_floor_*`** family **> 0**? |
| **statistic** | **equal-weighted mean over the 83 days**, printed beside the pooled per-signal mean |
| **CI** | day-block bootstrap, 4,000 reps, resampling whole days |

**Exactly three families are tested — not 867 reasons:**

1. `confidence_floor_*` (~100k rows)
2. `graduated_rule_veto*` (~17k)
3. all remaining reasons pooled

**Bonferroni over 3, two-sided 0.05/3 → |z| > 2.39.** No fourth family may be introduced later, and
**no single `skip_reason` string may be promoted to headline** — with 867 of them, picking the best
is guaranteed to find one.

**Pre-approved secondary, descriptive only:** the net day-mean **by floor value** (58…80), because
the floor changed over time and that is a natural experiment. **It cannot become the primary** and
its multiplicity is not corrected, so it is read as a shape, never as a verdict.

## 3. 🔴 The confound that caps what any positive result can mean

**A per-signal counterfactual is not portfolio P&L.** Taking all ~100k floor-rejected signals was
never possible: risk budget, position limits, correlated symbols, and the bot already holding
positions. **So a positive result means "the floor is rejecting signals that were positive-EV in
isolation" — NOT "the bot would have earned this."**

**I will not translate any result into money, and a SUPPORT verdict is explicitly not a
recommendation to lower the floor.** The follow-up that could justify that is a portfolio
simulation with the bot's real constraints, which is a separate study and is out of scope here.

**Also inherited:** the counterfactual uses each signal's own `sl`/`tp` geometry, so it carries
whatever is wrong with that geometry. X2 measured the bot's live stop at **1.66% median**; these
counterfactuals share that construction and are not independent evidence about it.

## 4. Decision rule, fixed now

**SUPPORT** requires ALL of:

1. net equal-weighted day-mean **> 0** with CI excluding zero at **|z| > 2.39**;
2. **pooled and equal-weighted agree in sign**;
3. **sign-stable** across halves split at the median day;
4. effect **exceeds the MDE** of §5;
5. **survives the §6 placebos**.

**AGAINST**: significantly negative. **UNDERPOWERED**: everything else, including
positive-but-below-MDE.

## 5. Power

MDE by **simulation** on the accrued between-day dispersion, not a restated CI half-width.

**Pre-commitment: the effect to beat is the gross aggregate mean of +25.2 bps less the 9 bps cost,
i.e. ~16 bps. If the MDE exceeds 16 bps, the verdict is UNDERPOWERED regardless of the point
estimate.**

## 6. Placebos

1. **Day-label shuffle**, 2,000 draws — measured size must be ≈5%. **If not, "unmeasurable", not
   "nothing".**
2. **Taken-signal control.** Run the identical statistic on the signals the bot **did** take (the
   294 ledger trades). If skipped and taken signals look the same net of cost, the floor is not
   sorting anything and the result is about the market, not the gate.
3. **Shuffled-reason placebo.** Reassign `skip_reason` at random within days, preserving family
   sizes. Must be null; if it is not, the families differ by day composition rather than by reason.

## 7. Recorded expectation

**I expect a positive point estimate that does NOT clear the bar, and I expect the portfolio caveat
of §3 to matter more than the statistic.** Gross +25 bps against a 9 bps cost leaves a thin margin,
83 clusters is not many, and a confidence floor exists precisely because low-confidence signals are
worse — so a large positive would be surprising. **Writing that down so a positive cannot be
presented as vindication and a null cannot be presented as rigour.**

## 8. Out of scope

- **No bot change on SUPPORT**, and not without the owner's yes.
- **No money figure**, per §3.
- **No per-reason fishing** across the 867 strings.
- **Deviations** go in the results document with their effect on the number.
