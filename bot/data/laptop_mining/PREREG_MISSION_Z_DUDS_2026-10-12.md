# PRE-REGISTRATION — Mission Z: can a Syndicate winner be told from a dud AT CALL TIME?

**SHA-256 of the sealed body — every byte after the LAST occurrence of the seal marker in this file
(the marker string occurs earlier in this header too, which is why the anchor is the last one):**
`b90c4b526cc5561199680209264da68233273d6ee2c6af8ea35af4fc2385d183`

Verify with:
`python -c "import hashlib,io;b=io.open('PREREG_MISSION_Z_DUDS_2026-10-12.md','rb').read();m=b'<!-- SEAL -->';i=b.rindex(m)+len(m)+1;print(hashlib.sha256(b[i:]).hexdigest())"`

<!-- SEAL -->
Sealed 2026-10-12, **before any feature has been joined to any outcome.** Mission Z, owner verbatim
via the server: *"i think the syndicate shows an immense amount of alpha, however there are a lot of
duds, bc its the memecoin market."*

The question this must answer and nothing else: **at call time, with only information that existed
at call time, can duds be separated from winners without throwing away the runners?**

---

## 0. Disclosure — exactly what was inspected before this seal

Full disclosure, so the seal means something. Before sealing I looked at:

* the **schema** of `syndicate_highs.jsonl`, `syndicate_paths.jsonl`,
  `server_exports/syndicate_calls_anon.jsonl`, and the two fetch scripts;
* **join keys and their failure rates** (counts only, section 2);
* **timestamps**: the call-date histogram, the data as-of time, maturity/censoring counts (section 3);
* the **already-published base rates** in `syndicate_highs_rates.json` / `syndicate_highs_grid.json`,
  which were measured and written before this mission existed.

I did **not** compute any outcome label, any joint outcome table, or any feature at all. No
feature-to-outcome relationship of any kind has been evaluated. The MDE in section 5 depends only on
sample sizes and the published base rate, so it is fixed here, in advance, where it belongs.

## 1. The decision this serves

The bot currently treats a Syndicate first-call as a signal with `p_15x` around 37.7% within 24h. A
dud filter would raise that number by **refusing to act on some calls**. The filter is only worth
having if the calls it refuses are disproportionately duds **and it keeps nearly all the 3x+
runners**, because the runners carry the whole expectancy of a memecoin book. Hence the gate in
section 8.

## 2. Data, and the join that is allowed

| file | role | rows |
|---|---|---|
| `syndicate_highs.jsonl` | **running max of the intrabar HIGH** as a multiple of entry: `peak_m` minute grid 0-24h (1441 pts), `peak_h` hourly grid 0-7d (169 pts) | 199 (181 with a path, 18 `skip: no_pool / no_path`) |
| `syndicate_paths.jsonl` | **forward-filled CLOSE** multiples, `m1` (1441) and `h1` (169) | 200 (182 with a path, 18 skips) |
| `server_exports/syndicate_calls_anon.jsonl` | `ca` + `call_ts`, and fields this mission must never read | 200 |

**The join key is `call_ts`, never `i`.** Measured before sealing: the highs file `i` agrees with the
current anon list ordering for only **18 of 199** rows — the server made that list append-only and
restored rows that had aged out of its 30-day window, and every index after an insertion is shifted.
`call_ts` is unique in all three files. Join rates on `call_ts`:

* highs to paths: **181 / 181** with-path rows join. This matters, because **the dud leg is not
  computable from the highs file at all** (a running maximum cannot fall), so `-80% at 7d` must come
  from the CLOSE path in `syndicate_paths.jsonl`.
* highs to anon (`ca` recovery, which the fetching agent needs): **197 / 199**. The 2 that fail have
  aged out of the current anon window. Those two rows are **SOURCE-MISSING for every call-time
  feature** and are never imputed.

**Forbidden fields, restated:** `caller_hash`, `starred`. Not read, not joined, not used as a
control, not used to stratify. No caller grading is built here, and *who called it* is not part of
the question being asked.

## 3. As-of time, and the censoring that follows from it

`T_asof = 1791764404` = **2026-10-12 00:20:04 UTC** (completion mtime of `syndicate_highs.jsonl`).
Calls span 2026-09-11 22:24 to 2026-10-11 17:00 UTC: **31 distinct UTC call-days**, 199 calls, mean
6.42 calls/day, median 6, max 18.

Both fetchers **pad their grid forward to the full horizon** whether or not data exists that far out.
So an immature call and a dead pool produce *the same shape* — a flat tail. That is the trap in this
dataset and it is fatal to any 7-day label applied naively.

| population | n | train (`call_ts < 2026-09-28 00:00 UTC`) | holdout (`>=`) |
|---|---|---|---|
| all calls | 199 | 126 (20 days) | 73 (11 days) |
| with a path | 181 | 114 | 67 |
| **24h-mature, with a path** (winner analysis set) | **179** | **107** | **72** |
| 7d-mature, all | 154 | 126 | 28 |
| **7d-mature, with a path** (dud analysis set) | **140** | **114** | **26** |

Consequences, fixed now:

* A call is **24h-mature** iff `call_ts + 86400 <= T_asof` (195 of 199).
* A call is **7d-mature** iff `call_ts + 604800 <= T_asof` (154 of 199).
* **45 calls are not 7d-mature.** They are labelled `OUTCOME-IMMATURE` and are **excluded from every
  dud figure**. They are *not* counted as non-duds. A missing source is not a zero.
* The 7d holdout is **26 calls over 4 days**. That is not a test; see section 5. The **single holdout
  verdict is therefore scored on the 24h WINNER leg plus the 3x-recall gate**, both of which are 24h
  quantities. Every 7d dud figure is train-side descriptive and is labelled as such.

## 4. Outcome definitions — fixed, and computable from these files

All on the full 199 unless stated. Dead pools count as misses, which is the convention the published
37.69% base rate already uses.

**WINNER** `:= max(peak_m[0..1440]) >= 1.5` — a 1.5x intrabar-high touch within 24h.
*Fallback, pre-committed:* the 2 with-path rows whose `peak_m` is null use
`max(peak_h[0..24]) >= 1.5`. *Skip rows (18): WINNER = 0.*

**WIN3X** `:= max(peak_m[0..1440]) >= 3.0` — the runner set that the gate in section 8 protects.
**WIN3X_7D** `:= max(peak_h[0..168]) >= 3.0`, reported on 7d-mature rows only.

**DUD** `:= dead_pool OR terminal_80`, defined **only on 7d-mature rows**:

* `dead_pool := the row is {skip: no_pool | no_path}` (structurally no tradable pool, or no price
  history at all) **OR** `silent := h1[121..168] are all exactly equal` — 48 consecutive
  forward-filled hourly closes, i.e. two days in which no trade moved the close, on a call that is
  7d-mature. Immature calls can never be labelled `silent`, because their flat tail is the padding,
  not the market.
* `terminal_80 := h1[168] <= 0.20` — the close at +7d is at or below 0.20x entry, i.e. -80%.
* *Robustness, pre-committed, reported alongside and never substituted for the primary:*
  `median(h1[161..168]) <= 0.20`.

**BOTH** `:= WINNER and DUD` — it spiked 1.5x, then died. **This is the cell where a dud filter does
its damage**, because these calls are tradable wins and terminal bag-holds at the same time.
**NEITHER** `:= not WINNER and not DUD`.

**Harness replication check, run first, abort on failure.** My labels must reproduce the already
published rates exactly: **WINNER = 75 / 199 = 37.69%**, `WIN3X = 26 / 199 = 13.07%`,
`WIN3X_7D = 53 / 199 = 26.63%` (`syndicate_highs_rates.json`, `syndicate_highs_grid.json`). If any
of the three does not reproduce, the harness is wrong and **nothing else in this prereg may be
reported.**

## 5. POWER — stated here, before any verdict, and binding

The clustered unit is the **UTC call-day**: 31 days, mean 6.42 calls/day. Design effect
`DE = 1 + (m - 1) * ICC`. Two-proportion MDE, alpha = 0.05 two-sided, power 0.80, baseline p = 0.377.

**The number that binds, because the single pre-specified test is one score on the holdout
(n = 72, 24h-mature with a path):**

| holdout n_eff | MDE, 50/50 bucket split | MDE, 30/70 split |
|---|---|---|
| 72 (ICC = 0) | **31.3 pp** | 34.7 pp |
| 56.6 (ICC = 0.05) | 34.7 pp | 38.3 pp |
| 46.7 (ICC = 0.10) | 37.5 pp | 41.4 pp |

Full-sample figures, descriptive and **not** the test, for reference: n = 179 gives **20.5 pp** at
ICC 0, 23.0 pp at ICC 0.05, 25.2 pp at ICC 0.10, 28.9 pp at ICC 0.20. A day-level two-sample test on
31 day-means with between-day SD 0.20 / 0.25 / 0.30 gives 20.1 / 25.2 / 30.2 pp.

**Read that honestly: on the holdout this study can only detect a filter that moves the winner rate
from 37.7% to roughly 69% or better.** A real but ordinary filter — say 37.7% to 50% — is invisible
here. Therefore, pre-committed:

* holdout lift **>= MDE** and the section 8 gate passed: **EDGE (provisional, one sample)**;
* holdout lift **< MDE**: **UNDERPOWERED**. Not "no edge", not "the filter fails". The word *null*
  may not be used for this outcome, because this design cannot produce a credible null at this n.
* The 7d dud leg on the holdout (n = 26) is **declared underpowered now** and will not be given a
  verdict at all.

## 6. Features — what is knowable AT CALL TIME, and what is poison

**The rule for the fetching agent: a call-time feature may read only (a) bars whose timestamp is
strictly `< call_ts`, (b) the immutable pool creation timestamp, (c) the call clock itself.
Everything a GeckoTerminal endpoint reports about *now* is post-hoc and is banned.**

### 6a. ALLOWED — the sealed list of 14. Nothing may be added later.

Request shape: minute OHLCV with `before_timestamp = call_ts`, hour OHLCV with
`before_timestamp = call_ts`, `pool_created_at` from the pool endpoint. 2.1 s throttle minimum, and
**only the one agent explicitly told to fetch may call the API.**

| # | feature | definition (every window ends strictly before `call_ts`) | hypothesised dud direction |
|---|---|---|---|
| F1 | `pool_age_min` | `(call_ts - pool_created_at) / 60`. A creation time is immutable, not current state. | very young = duddier |
| F2 | `n_premin_bars_60` | count of minute bars that exist in `[call_ts - 3600, call_ts)` (trade density, 0-60) | fewer = duddier |
| F3 | `pre_ret_60m` | `last_pre_close / close(call_ts - 3600) - 1` | none (both signs tried) |
| F4 | `pre_ret_15m` | the same over 15 minutes | none |
| F5 | `pre_ret_6h` | from hour bars before the call | none |
| F6 | `pre_rv_60m` | SD of 1-minute log close returns in the pre-hour | none |
| F7 | `pre_maxdd_60m` | min of `close / running-max close - 1` over the pre-hour | deeper = duddier |
| F8 | `pre_vol_usd_60m` | sum of bar volume (USD) over the pre-hour. Bar volume is point-in-time, unlike `volume_usd.h24`. | lower = duddier |
| F9 | `vol_accel` | `pre_vol_usd_15m / (pre_vol_usd_60m / 4)` | lower = duddier |
| F10 | `prox_to_pre_high` | `last_pre_close / max(high)` over the pre-6h | none |
| F11 | `pre_green_frac_60m` | share of pre-hour minute bars with `close > open` | none |
| F12 | `pre_hist_bars_total` | count of hour bars available before the call (price-history length; an age proxy that survives a missing `pool_created_at`) | fewer = duddier |
| F13 | `us_session` | **binary**: `13:00 <= hour_utc(call_ts) < 21:00`. From the clock alone, no fetch. | none |
| F14 | `mins_since_prev_call` | minutes since the previous Syndicate call in the list (strictly backward-looking) | none |

Features with no pre-committed sign are why both directions are counted in the threshold budget in
section 7.

**Missing pre-history is its own bucket, never a zero.** A token called minutes after launch may have
no pre-call bars at all. Such rows go to `no_prehistory` and are reported as a labelled bucket with
its own winner rate. They are not imputed to 0, not dropped silently, and `no_prehistory` itself is
**not** promoted to a feature — that would be F1 and F12 by the back door.

### 6b. BANNED — post-hoc. Using any of these invalidates the study.

* **Everything the GeckoTerminal pool or token endpoint reports as current state**, read today, after
  the outcome: `reserve_in_usd` (current liquidity), `fdv_usd`, `market_cap_usd`,
  `base_token_price_usd`, `price_change_percentage.*`, `volume_usd.h1/h6/h24`, `transactions.h1/h24`
  (buys, sells, buyers, sellers), holder counts, any holder-distribution or token-security score.
  **A dead pool reads near-zero liquidity and near-zero 24h volume *because* it died.** Using these
  would produce a filter with a spectacular in-sample AUC and no real-world meaning whatsoever. It is
  first on this list because it is the single most likely way this mission gets silently ruined.
* Any OHLCV bar with `ts >= call_ts`, including the entry bar high.
* `peak_m`, `peak_h`, `m1`, `h1` — outcome by construction.
* `caller_hash`, `starred` — rule-forbidden.
* `first_seen_via_bot_alert`: genuinely call-time, but **deliberately excluded** from the sealed 14 as
  a possible caller proxy. It may not be added to this mission without a new prereg.

### 6c. A bias I cannot remove, so I declare it instead

`best_pool()` picks the **deepest pool as it exists today**. Pool choice is therefore conditioned on
survival, for every row equally. Fixing it would need the pool list as of `call_ts`, which is not
retrievable. Declared here, carried into the verdict as a caveat, and not described as negligible.

## 7. ONE rule form. One.

`KEEP the call iff s * x >= s * t`, for a single feature `x` from the sealed 14, a direction
`s` in `{+1, -1}`, and a threshold `t` taken from the **train** distribution. One feature, one
threshold. No two-feature rules, no scores, no trees, no interactions, no "and also".

**Selection, on TRAIN only (n = 107):** maximise `winner_rate(KEEP) - winner_rate(all train)`,
subject to `3x-recall(KEEP) >= 0.85` **and** `keep_fraction >= 0.40`. Ties go to the larger keep
fraction.

**Threshold budget, counted in advance:** 13 continuous features x 9 train deciles (10th to 90th) x 2
directions = 234, plus F13 binary x 2 directions = 2. **236 candidate rules.** The realised count
(grids collapse when a feature has ties or is missing) **will be reported as a number in the
results**, next to the Sidak-adjusted alpha it implies. Train-side lift is a *selection statistic, not
evidence*: with 236 tries the best-of-noise lift runs about 2.5 to 3 SE, and section 10 measures that
directly instead of assuming it.

**The holdout is scored exactly once, with the winning rule, and the result is reported whatever it
is.** If the holdout contradicts the train, the holdout stands.

## 8. THE KILLER METRIC — a verdict GATE, not a footnote

> **What share of 3x-or-better winners does the filter throw away?**

`runner_recall := |KEEP and WIN3X| / |WIN3X|`, on the holdout, with a Wilson 95% interval.

**Gate, pre-committed: the rule FAILS — verdict WORTHLESS, no matter how good the winner-rate lift
looks — if holdout `runner_recall < 0.85`, or if its Wilson lower bound < 0.65.**

A filter that lifts the 1.5x rate by killing the 10x is a loss dressed as a win. The 1.5x touches are
the common case; the 3x+ tail is where the money is.

**And the gate has its own power problem, stated now:** `WIN3X` is about 13.07% of calls, so the
holdout contains only **9 or 10 three-baggers**, the full sample about 26. At n = 24 a recall of 0.85
carries SE 0.073 and a Wilson interval of [0.66, 0.94]; at n = 48 (3x within 7d) it is [0.72, 0.92].
So:

* the gate is deliberately **asymmetric** — it can *fail* a rule credibly (dropping 3 of 10 runners is
  visible) but it can never *certify* one as runner-safe;
* `runner_recall` is also reported on the **full sample** and against **`WIN3X_7D`** (larger n) as
  descriptive context, with the holdout number the only one that gates.

## 9. Clustering discipline — it applies to the number being acted on

Learned the expensive way: clustering the variance by day while averaging by event produced a
published false null in this project. So for **every** rate reported — base rates, bucket winner
rates, train lift, holdout lift, runner recall:

1. the **pooled** (per-call) figure;
2. **beside it, the equal-weighted-by-day mean** — each UTC day rate computed, then days averaged
   with equal weight — reported for the acted-on number itself, not only for its CI;
3. **`corr(calls_per_day, day_winner_rate)`** with its n. **If that correlation is non-zero the
   pooled figure is WRONG, not merely noisy**, and the equal-weighted figure is the one quoted in the
   verdict;
4. day-clustered CIs: block bootstrap over the 31 days, 2000 resamples.

Days with a single call contribute a 0/1 day-rate, which inflates equal-weighted variance, so the
count of singleton days is reported too — the day histogram already shows several days with 1 to 3
calls.

## 10. A placebo that can FAIL

**Not** a mean pinned to zero. The null is generated by resampling *new* data:

For each of **500 iterations**: permute the 14 feature *vectors* across calls **by whole day blocks**
— shuffle the day labels, carry each day of feature rows to another day — so within-day feature
correlation survives but every feature-to-outcome link is destroyed. Then run the **entire** pipeline
unchanged: all 236 candidates, train-side selection under the same constraints, one holdout score.
Record the holdout lift.

* The real holdout lift must exceed the **95th percentile** of those 500 null lifts. That is the
  p-value for this study, and it is a number that can come out against me.
* **Harness-leak abort condition:** the null distribution median holdout lift must sit **near 0
  (within +/- 3 pp)**. If permuted features still yield a positive median lift there is look-ahead or
  a shared-path leak in the harness, and **no real result may be reported until it is found.**

Could this come out the other way? Yes, and that is the point. A day-block permutation under the null
has no reason to beat the real features, and a real signal has no reason to land inside the bulk of
the null.

## 11. Walk-forward sign stability — a gate, because 5 of 6 rules flipped last time

In Mission M3, **5 of 6 rules flipped sign between halves.** So: split TRAIN itself at its own time
median into T1 and T2 and evaluate the selected rule winner-rate lift in each.

**Gate: if `sign(lift_T1) != sign(lift_T2)` the verdict is NO EDGE regardless of the holdout score.**
Both half-lifts are reported with their n, pooled and equal-weighted-by-day.

## 12. The verdict table — the exact shape the answer must take

One row, for the single selected rule. Columns in this order, filled with numbers and uncertainty, no
prose:

| field | content |
|---|---|
| rule | `KEEP iff s * x >= t`: feature name, threshold value, direction |
| candidates tried | realised count (budget 236) and the Sidak alpha it implies |
| train lift | pooled pp **and** equal-weight-by-day pp, `n_keep / n_train`, day-clustered CI |
| `corr(day size, day rate)` | value and n days; if non-zero, the equal-weighted figure is the one quoted |
| T1 / T2 half lifts | two numbers with signs, then **sign-stability gate PASS/FAIL** |
| **holdout lift (one score)** | pooled pp **and** equal-weight-by-day pp, with day-clustered CI |
| **MDE** | 31.3 pp (ICC 0) / 34.7 pp (ICC 0.05), restated from section 5 inside the table |
| **runner recall (holdout)** | value and Wilson 95%, then **killer-metric gate PASS/FAIL** |
| placebo | real lift vs the null 95th percentile; null median, as the leak check |
| 7d dud leg | train-side descriptive only, with `OUTCOME-IMMATURE` counts shown |
| **verdict** | one of **EDGE (provisional)**, **NO EDGE (sign flip)**, **WORTHLESS (kills runners)**, **UNDERPOWERED**, **SOURCE-MISSING** |

**Verdict logic, fixed now, evaluated in this order:**

1. harness replication fails (section 4), or the placebo median is non-zero (section 10): **nothing
   is reported**;
2. the runner-recall gate fails (section 8): **WORTHLESS**;
3. sign stability fails (section 11): **NO EDGE**;
4. holdout lift < MDE (section 5): **UNDERPOWERED**;
5. holdout lift >= MDE and lift > the placebo 95th percentile: **EDGE (provisional, single sample,
   carrying the section 6c pool-selection caveat)**.

## 13. What this study cannot answer, written down in advance

* Whether a *multi-feature* dud model works. Not asked here, and n = 179 cannot support it.
* Whether duds are separable at a horizon longer than 7 days.
* Anything about *which caller* is better. Forbidden, and not asked.
* Whether the -80%-at-7d leg generalises past 2026-10-04, since nothing after that date is 7d-mature
  as of `T_asof`.
* Any statement of the form "duds are unpredictable at call time." The holdout MDE is 31 pp; this
  design is not entitled to that sentence, and it will not be written.
