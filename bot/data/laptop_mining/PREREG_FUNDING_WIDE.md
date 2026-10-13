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

---

# AMENDMENT 1 — made 2026-10-12 BEFORE any read, with funding at 60/178 files

**Reason: the verdict rule in §4 is defective, and I found it by applying it to the discovery sample
instead of trusting my description of it.** Two separate corrections, plus two factual fixes.

## A. The verdict rule conflated two different questions

`size_flags.json` records, for `funding_hot`:

| | |
|---|---|
| week-mean log effect | **+0.0740** → level **+7.68%** |
| week clusters | **145** (not the 160 I kept quoting) |
| matched cells | **2,283** |
| size at δ=0 | **0.030** ✓ inside [0.02, 0.09] |
| power | δ=0.05 → **0.62**, δ=0.10 → **0.98** |
| **mde80** | **0.10 log ≈ +10.5% level** |
| t | **3.28** |

**So the original effect (+7.68%) sits BELOW its own 80%-power MDE (+10.5%), while still being
significant at t 3.28.** §4 as written says "if `|level_pct| < MDE`, the verdict is unmeasurable" —
**which would declare `SIZE_FLAGS` itself unmeasurable.** A rule that rejects the very result it was
written to re-test is wrong.

**The error is conflating "could we have detected an effect of size X" with "did we detect one."** An
effect can be real and significant while sitting under the 80%-power point; 80% power is a design
target, not a detection threshold. Both facts matter and they are now reported separately.

**Replacement verdict matrix — fixed here, before any read:**

| | effect ≥ MDE80 | effect < MDE80 |
|---|---|---|
| **CI excludes zero** | **replicates** | **positive but underpowered** |
| **CI includes zero** | **does not replicate** (we could have seen it and did not) | **unmeasurable** |

**"positive but underpowered" is the honest label for the original finding**, and it is a real outcome
for the replication too — not a fudge. **"does not replicate" now requires that the design actually
had the power to see the effect**, which is the only condition under which a null is informative.

## B. MDE was resolved on too coarse a grid

`DELTAS` of {0, 0.03, 0.05, 0.10, 0.20} can only ever return an MDE from that set, which is how a
true effect of 0.074 gets compared against a reported MDE of 0.10. **MDE is now interpolated linearly
between the two bracketing grid points at 80% power**, and the grid is finer:
**{0, 0.02, 0.03, 0.04, 0.05, 0.06, 0.075, 0.10, 0.15, 0.20}**.

**δ=0 remains the placebo and remains able to fail.** The TEST BROKEN rule at [0.02, 0.09] is
unchanged. Interpolation affects only where the MDE line is drawn, never whether the test is valid.

## C. Two factual corrections to my own recorded expectations

1. **§5.1 said "(b) reproduces near +7.4%". Wrong** — +0.0740 is the week-mean **log** coefficient;
   the level is **+7.68%**. The canary passes if **(b) reproduces near log +0.074 / level +7.7%**.
   The PC's knowledge registry had this right and I had it wrong.
2. **The cluster baseline is 145 weeks, not 160.** So the wide panel's ceiling of **199 available
   weeks is a +37% gain on funding_hot's actual 145**, not the +24% I recorded. **The cell count is
   the bigger move: 2,283 matched cells, against a wide panel that should yield an order of magnitude
   more.** The claim still gets made only from the injected-effect table, not from this arithmetic.

## D. What this amendment does NOT change

Populations, arms, the gate at ≥170/173, `START = "2023-01-01"`, the prohibited list, and the report
order are all untouched. **No held-out data has been read.** The amendment is made because a rule
failed a sanity check against the discovery sample, which is the only moment such a fix is legitimate.

---

# AMENDMENT 2 — made 2026-10-12 BEFORE any read, with funding at ~100/178 files

**Reason: the PC answered the provenance question and the answer invalidates part of the panel.**
Reply to 116: *"pre-2023 HL daily bars are HL's own backfill (n=0, v=0); real trading from
2023-02-26."* **Verified independently on the laptop's own files, and it is worse than the headline.**

## A. What the data shows

| coin | bars | zero-volume | last v=0 | first v>0 | flat OHLC |
|---|---|---|---|---|---|
| BTC | 2,242 | 921 | 2023-02-25 | **2023-02-26** | **0** |
| ETH | 2,242 | 921 | 2023-02-25 | 2023-02-26 | 0 |
| ATOM | 2,246 | 921 | 2023-02-25 | 2023-02-26 | 0 |
| **DOGE** | 2,242 | **957** | 2023-04-02 | **2023-04-03** | 0 |

**Three things follow, none of which I had allowed for:**

1. **The real-trading start is PER COIN, not a global 2023-02-26.** DOGE's is 2023-04-03.
2. **`START = "2023-01-01"` is INSIDE the backfill.** Freezing `START` protected against reaching
   further back, but the window already began before real trading existed.
3. **The `MAX_STALE` filter catches none of it.** Backfill bars have **moving OHLC with zero volume**,
   so `o == h == l == c` is false and all 2% of the stale filter's budget goes unused. **I had
   recorded "0 dropped as stale" as evidence the new series were clean. It was evidence the filter
   does not look at volume.**

**In the analysis window: 20,022 of 168,129 rows are zero-volume — 11.9% of the panel.** Those rows
**cannot be flagged** (no funding exists before a coin trades), so they sit entirely in the
**unflagged comparison arm** as fabricated price paths. **That biases the exact difference this test
measures.**

## B. 🔴 And it contaminates `SIZE_FLAGS` itself

`SIZE_FLAGS` ran without any volume filter. **Its own 17-coin window is 10.7% synthetic** — 2,159 of
20,156 rows — and the distribution is severe, not diffuse:

| coin | synthetic rows | share |
|---|---|---|
| **ZEC** | **999 of 1,371** | **73%** |
| NEAR | 304 of 1,377 | 22% |
| UNI | 222 of 1,377 | 16% |
| XRP | 167 of 1,377 | 12% |
| LINK | 137 of 1,377 | 10% |

**11 of the 17 coins carry synthetic rows, and ZEC is almost entirely backfill.** This is an
independent second reason the `funding_hot_bigger_day` card must not read PROVEN, separate from the
power argument in reply 116.

## C. The fix, pre-specified

**`VOL_FILTER`, applied to every population in the primary result:**

1. **Truncate each coin's series to its first `v > 0` bar.** Zero-volume runs are a clean **prefix**
   for **93 of 178** coins (83 have none at all), so truncation removes every synthetic bar *and*
   preserves a contiguous daily grid for `rv1/rv5/rv22`.
2. **Then drop any coin-day whose own bar or whose next-day outcome bar has `v == 0`.** Only **2**
   coins have interior zeros — **BANANA (8 bars)** and **VVV (1 bar)** — but VVV is one of the
   original 17, so the rule is stated rather than waved off.
3. **Report rows removed** beside the panel size.

## D. The canary has to split, or it stops being a canary

`SIZE_FLAGS` ran on the contaminated panel, so **a volume-filtered ORIG17 will NOT reproduce
+0.0740 log**, and a mismatch would no longer mean the pipeline is broken. Both arms are therefore
reported:

| arm | purpose |
|---|---|
| **(b_raw) ORIG17, NO volume filter** | **the true pipeline canary.** Must reproduce ≈ **+0.0740 log / +7.7% level**, or the reimplementation is wrong and nothing else in the run is trustworthy |
| **(b) ORIG17, volume filtered** | what the discovery sample says once fabricated rows are removed |
| **(c) NEW156, volume filtered** | **unchanged: still the replication and the only number to act on** |

## E. Recorded expectation — with its mechanism, so it can be wrong

**I will not claim a direction I cannot argue.** The mechanism I can argue: **synthetic rows are
removable only from the unflagged arm**, because they can never be flagged. **If backfilled bars are
smoother relative to `em` than real ones** — plausible, since a reconstructed series has no genuine
microstructure — **then removing them RAISES the unflagged arm's mean |move| and SHRINKS the
flagged-minus-unflagged difference.**

**So the prediction is: (b) filtered comes in BELOW (b_raw) unfiltered.** If it comes in higher, that
mechanism is wrong and I say so. **I am deliberately not measuring |move| by volume status before the
run**, which would be a read; it gets reported afterwards as part of the result.

**Panel size falls ~12%**, so every MDE should widen slightly. That is the cost of removing fabricated
data and it is worth paying.

## F. Unchanged

Populations, arms, the gate at ≥170/173, the Amendment 1 verdict matrix, the prohibited list, and the
report order. **`START` stays `2023-01-01`** — the volume filter now does the work that moving `START`
would have done, and does it per coin instead of globally. **No held-out data has been read.**
