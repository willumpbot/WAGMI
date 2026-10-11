# PRE-REGISTRATION — does the small-cap breakout **fade** hold prospectively, and does funding eat it?

**Status: SEALED 2026-10-11, at n = 0 forward signals.** The in-sample result
(`SMALLCAP_CORRECTION.md` §4) was found by **exploration** — a red-team re-specified my own signals
by strength after seeing that day-weighting flipped the sign. The gradients are monotone in three
independent strength variables and clear a 113-cell Bonferroni bar, but it was still found by
looking, and this project has been wrong six times in one day about results found that way.

**So nothing in §4 is acted on. This is the test.**

## 1. The claim being tested

Small caps far above their 20-day high **underperform their same-hour peers**, and more so the
further above they sit. In sample, equal-weighted by day, 72h excess vs the full non-breakout
cross-section:

| close above 20d high | excess | z |
|---|---|---|
| 2–4% | −3.01% | −3.72 |
| 4–8% | −6.04% | −5.19 |
| ≥8% | **−14.85%** | **−6.14** |

## 2. Signal and benchmark, fixed now

- **Universe:** HL perps outside the **top 15** by *trailing* 20-day dollar volume at that hour
  (prior bars only), ≥25 eligible coins in the hour.
- **Signal:** `close / max(close over the prior 480h) − 1 ≥ 0.04`, strictly above.
- **Benchmark:** the **full** same-hour cross-section of eligible coins **not** above their 20-day
  high. No sampling — there is nothing to tune.
- **Statistic:** per hour, `mean(signal fwd) − mean(benchmark fwd)`; averaged within day;
  **equal-weighted across days.** The day is the unit of the estimate *and* of the variance — the
  error that produced this finding will not be repeated in testing it.
- **Horizons:** 1h, 4h, 24h, **72h (primary)**, 168h.

## 3. 🔴 The two things that decide whether it is real, both pre-stated

1. **FUNDING.** Unmeasured in sample and plausibly **~1%/day against a short in a blow-off**, i.e.
   **~3% of a 5.8% 72-hour edge.** From now the test subtracts **realised** `fundingHistory`
   (archived by `crunch/j5_backfill.py` from today) over the actual holding window, per coin. **A
   fade that does not survive realised funding is not a finding**, however large the excess.
2. **CAPACITY.** Median signal coin is **$572k/day**, 10th pct **$131k/day**. Reported at
   **$500 / $2k / $10k** per position against trailing volume. **A result that needs more size than
   the book holds is reported as unreachable, not as an edge.**

## 4. Bars, fixed now

- **Primary:** 72h excess, day-clustered bootstrap, **two-sided α = 0.05, one interim look at
  α = 0.005.** 80%-power constant for the gate is **3.80 × se** (Bonferroni 0.05/16 + 0.8416) —
  **not** the 2.8 I wrongly used in `smallcap_momentum.py`.
- **Unlock: 150 prospective signal events across ≥30 distinct days.** In sample the rate was 682
  events / 132 days ≈ 5/day, so this is roughly **4–6 weeks**. Written down now so the wait cannot
  be reframed as a result.
- **Until unlock, only the event and day counts are reported.**

## 5. What counts as what

| outcome | conclusion |
|---|---|
| excess clears 3.80×se **and** survives realised funding **and** is fillable at $2k | **SUPPORT** a fade/avoid rule; sizing proposed separately |
| clears, survives funding, **not** fillable | **REAL BUT UNREACHABLE** — recorded, not traded |
| clears but **funding eats it** | **NOT A FINDING.** The in-sample result was a funding illusion |
| does not clear | **NOT A FINDING.** §4 was exploration-driven after all, and `SMALLCAP_CORRECTION.md` gets a retraction line |

## 6. The AVOID rule is separate, and is NOT gated on this

`SMALLCAP_CORRECTION.md` §6 recommends **not buying** small caps far above their 20-day high. That
is a decision to *refrain*, it needs no capacity, pays no funding, and the in-sample evidence
against the long side is the part that was **pre-registered** (the original 16 cells, every
correction pushing further negative). **It does not wait on this prereg.** This prereg governs only
taking a **position** on the fade.

## 7. Constraints

- **No bot change on this prereg alone**; a SUPPORT verdict is an input to the owner's decision.
- **Short-side execution is not assumed to exist.** Shortability of a $131k/day perp is itself an
  open question and is reported, not presumed.
- **The in-sample window is spent.** It has been looked at, repeatedly, by six agents. Only
  post-seal data counts.
