# PREREG — does `funding_hot` replicate OUT-OF-SAMPLE on the 156 coins it was never tested on?

**Sealed 2026-10-12, BEFORE the funding walk completed and before any predictor-outcome quantity was
computed on the wide panel.** The data for the held-out coins did not exist on this machine when this
was written — `fetch_funding_wide.py` was still running, 50 of 178 files present. That is the
strongest sealing condition any prereg in this project has had, and it is the reason to write it now
rather than after.

---

## 1. Why this one matters more than the other eight preregs

`SIZE_FLAGS` is **the only finding that has ever survived a red team here**: `funding_hot` predicted a
**+7.4% bigger next-day |move|** than the HAR forecast alone. Everything else this project has
produced — M2, skipgate, E2, E2b, X2, fat-tail, profits-only — died.

**It was discovered on 17 perps, because 17 was all that was cached.** The universe is 173.
**So 156 coins are a true held-out sample: never looked at, never used to choose this design, and
physically unavailable when this document was sealed.**

**This project has never run a genuine out-of-sample replication.** Every previous "confirmation" was
a re-cut of the discovery sample — which is exactly how M2 survived six readings before the
equal-weighted block mean killed it.

## 2. The question, and the ONE number that decides it

> On the **156 coins that were not in `SIZE_FLAGS`**, does `funding_hot` predict a bigger next-day
> |move| than coins with the same HAR forecast on the same date?

**The governing statistic is the equal-weighted WEEK-cluster mean of the within-cell difference**,
where a cell is **date × em-quintile**, exactly as `matched()` already computes it. Reported as
`level_pct = 100 * (exp(week_mean_log) - 1)`.

**Three populations, reported together, and they are NOT interchangeable:**

| population | coins | status | what it can establish |
|---|---|---|---|
| **(c) NEW coins only** | **156** | **held out — the number to act on** | **replication** |
| (b) original 17 | 17 | discovery sample | **nothing new.** A consistency check, not evidence |
| (a) all 173 pooled | 173 | mixture | completeness only; **contaminated by (b)**, never quoted as the replication |

**If (b) is strong and (c) is null, the honest conclusion is that `SIZE_FLAGS` was a cross-sectional
fluke of 17 coins and the project's only surviving finding does not generalise.** I am writing that
sentence before seeing the number, so it cannot be renegotiated afterwards.

## 3. The treatment is redefined by widening — pre-specified now, not later

`funding_hot` is a **cross-sectional top quintile per date** (`f.quantile(0.80)`, needs ≥5 coins with
funding that date). **Top 20% of 17 coins ≠ top 20% of 173 coins.** Widening the universe silently
changes the thing under test, so the arms are fixed here:

- **PRIMARY — rank arm.** Quintile computed **within the population being tested**. Replicates the
  *rule*, and matches what the live scanner does: it ranks across the coins it scans.
- **SECONDARY — threshold arm.** The quintile cutoff is **frozen per date from the original 17 coins**
  and applied to the new 156. Replicates the *threshold*.
- **Both are reported.** If they disagree, the finding is **rank-dependent** — and that is itself the
  result, reported as such, with neither arm promoted to the answer.

## 4. Power, stated BEFORE any verdict — the standing rule

`size_flags.py`'s injected-effect block runs first and governs interpretation. It permutes the flag
**within cells** and injects δ ∈ {0.00, 0.05, 0.10, 0.20}.

- **δ=0.00 is the test's SIZE (false-positive rate). This is the placebo, and it CAN FAIL** — it runs
  on permuted labels, so a broken test shows it. **If size falls outside [0.02, 0.09] the result is
  reported "TEST BROKEN" and no verdict is issued**, regardless of how the effect looks. E2, E2b and
  X2 would all have been caught by this.
- **MDE is read off the power table and written down before the effect is read.** If
  `|level_pct| < MDE`, the verdict is **"unmeasurable"**, never "no effect".
- **Expected improvement, as a falsifiable prediction:** cells go from ~3.4 coins (0 or 1 flagged,
  usually discarded by the `f.all() or not f.any()` guard) to ~24 coins (~5 flagged, usually kept), so
  more weeks should clear the ≥8-cell bar and each week's mean should be far less noisy. Week clusters
  should rise from 160 toward the ceiling of **199** — **a +24% gain at most, which is NOT where the
  power comes from.** It comes from within-week precision. **If the power table does not show a lower
  MDE than `SIZE_FLAGS`, this prediction was wrong and I say so.**

## 5. Recorded expectations — so the result can contradict me

1. **The original 17 (b) reproduce near +7.4%.** If they do not, something broke in the pipeline and
   nothing else in the run is trustworthy. **This is the pipeline's own canary.**
2. **The new 156 (c) show a SMALLER effect, roughly +2% to +5%.** Reason: the new coins are smaller
   and newer, where funding is noisier and goes extreme for mechanical low-OI reasons rather than
   because of crowded positioning.
3. **Probability I assign to (c) being a clean positive above its MDE: ~45%.** Explicitly below a coin
   flip. The base rate in this project is one survivor in nine.
4. **MDE on (c) will land near +2–3%** — better than `SIZE_FLAGS`, but possibly not better than the
   true attenuated effect, in which case the honest answer is **"unmeasurable", which is a real
   outcome and not a failure to be worked around.**

## 6. Stopping rule — ONE run, no re-cuts

- **Runs ONCE**, when `fetch_funding_wide.py` has funding for **≥170 of the 173** qualifying perps.
  Below that it does not run at all: `load_funding` returns `{}` for a missing file, which makes a coin
  **silently and permanently unflagged** and biases the comparison. **A missing source is never a
  zero.**
- **No second run after seeing the result.** No added controls, no dropped coins, no moved `START`, no
  swapped flag, no changed quintile, no re-weighting.
- **`START` stays `2023-01-01`.** The ~123 extra weeks available pre-2023 are **excluded on purpose**:
  48 coins carry bars starting on exactly 2020-08-19 with exactly 865 pre-2023 rows, and
  **Hyperliquid did not exist in 2020.** That is unexplained backfill, and buying weeks with
  unexplained provenance is how mission 1 was invalidated.
- **Amendments only before a read**, appended here with a reason, exactly as `PREREG_STOP_SHADOW`
  Amendment 1 was handled.

## 7. Prohibited, explicitly

- Quoting **(a) pooled 173** as the replication. It contains the discovery sample.
- Quoting **coin-days (167,680 / 8.4x)** as the power gain. Alts co-move; coin-days are not
  independent units; **the clustering standard applies to the number being acted on.**
- Reporting a **signed** direction. The outcome is unsigned |move| by construction, and every signed
  claim this project has made has died.
- Any use of `caller_hash` or `starred`. Not relevant here, and barred regardless.
- Re-deriving the HAR baseline from prose. `Y1B`/`Y1S` come from `volatility_forecast.json`
  **unchanged and unrefitted** — applying them to 156 new coins is deliberately out-of-sample.

## 8. What gets written afterwards

A result file with, in this order: **size at δ=0 → MDE → week-cluster counts → then** the three
populations × two arms, each as `level_pct` with its week-clustered CI, and the verdict words
**"replicates" / "does not replicate" / "unmeasurable" / "TEST BROKEN"**. The equal-weighted week mean
sits beside any pooled figure. **No number is read before the one above it.**
