# PREREG — does a caller's prior hit rate predict their NEXT call? **Sealed before any form × outcome statistic was computed.**

_STEP 3 of the identity-free handoff. The server's `call_caller_form_anon.jsonl` (384 rows) is on
disk and has been inspected for **structure and predictor reliability only**. No form × outcome
quantity of any kind has been calculated. Every number below describes the predictor or the sample,
never the relationship being tested._

---

## 0. The handoff, and why it is built this way

| step | where | what |
|---|---|---|
| 1 | laptop | `call_outcomes.jsonl` — public price facts per call, **no caller field**, write refused if any identity-like key appears |
| 2 | **server** | join to identity **locally**, compute rolling form from outcomes with `resolved_at < call_ts`, ship back form columns with no identity |
| 3 | laptop | **this test** |

**`caller_hash` is never read by this machine.** My own identity audit flagged `caller_is_bot` on a
substring match; **that is a false positive and the field is admissible** — a single boolean cannot
identify a person or group calls by caller. It is kept as a covariate (§5), not as an identifier.

## 1. The predictor, measured before the test

| field | coverage |
|---|---|
| `form_n_prior_calls` | 327 rows, median **4**, max 71 |
| **`form_n_known_7d`** (prior calls whose 7d outcome had resolved) | 327 rows, **median 1** |
| `form_hit2x_7d` (the 7d form rate) | **166 rows** |
| `form_decile_2x7d` | 126 rows |
| `caller_is_bot` | 57 of 384 true |

## 2. 🔴 The reliability threshold, fixed now at **`form_n_known_7d ≥ 3`**

**A hit rate computed from one prior outcome is 0 or 1 by construction** — at `min n = 1` the
predictor is largely a coin flip relabelled as form. Measured trade-off, predictor-side only:

| min prior outcomes | calls surviving | share of 384 |
|---|---|---|
| 1 | 166 | 43% |
| 2 | 147 | 38% |
| **3** | **126** | **33%** |
| 5 | 79 | 21% |
| 8 | 73 | 19% |

**`≥ 3` is the choice: it removes the 0-or-1 degenerate cases while keeping 126 calls.** Declared
now so it cannot be tuned afterwards. **`≥ 5` is the single pre-approved sensitivity cut** and is
reported alongside; no other threshold may be introduced later.

**`form_decile_2x7d` is NOT the primary predictor.** Its distribution is badly lumpy —
`{0:23, 1:3, 2:21, 3:37, 6:5, 7:17, 8:19, 9:1}`, with deciles 4 and 5 empty — because few prior
outcomes admit few distinct rates. **Primary is the continuous `form_hit2x_7d`.** The decile is
descriptive only.

## 3. Primary test

| | |
|---|---|
| **predictor** | `form_hit2x_7d`, continuous, on calls with `form_n_known_7d ≥ 3` |
| **outcome** | `hit2x_7d` from `call_outcomes.jsonl` — same horizon as the form, so like predicts like |
| **statistic** | difference in outcome rate between **above-median** and **below-median** form, **equal-weighted over call-days**, printed beside the pooled difference |
| **CI** | day-block bootstrap, 4,000 reps, resampling whole call-days |
| **dead** | `dead` rows are outcome **false**, never dropped |

**The equal-weighted call-day figure governs on disagreement with pooled.** Non-negotiable: it is
the M2 error, and I committed it again in `fattail2` twelve hours ago.

**Secondary, reported but not headline:** the same test on `form_hit15_24h` → `hit15_24h` (24h
form → 24h outcome, n larger), and `ret_7d` as a continuous outcome.

## 4. Decision rule, fixed now

**SUPPORT** for "caller form predicts the next call" requires ALL of:

1. equal-weighted day-mean difference **> 0**, CI excluding zero at **|z| > 2.24** (Bonferroni over
   the 2 horizons, two-sided 0.05/2);
2. **pooled and equal-weighted agree in sign**;
3. **sign-stable** across halves split at the median call-day;
4. effect **exceeds the MDE** of §6;
5. **survives the §7 placebos**;
6. **survives the bot/human split of §5** — not reversing sign between them.

**AGAINST**: significantly negative. **UNDERPOWERED**: anything else, explicitly including
positive-but-below-MDE.

## 5. The covariate that could fake this

**57 of 384 calls are bot-posted.** If bot callers both call more often (higher `form_n_prior_calls`)
and have systematically different outcomes, form would proxy for bot-ness rather than skill.

**So the primary test is run on human-posted calls only, and the bot subset is reported separately.**
Declared now, because discovering this split afterwards and choosing the flattering side is exactly
how the Z filter became a denominator artefact.

## 6. Power

MDE by **simulation** on the accrued dispersion at n=126, not a restated CI half-width.

**Pre-commitment: if the MDE exceeds 15 percentage points of hit rate, the verdict is UNDERPOWERED
regardless of the point estimate.** 126 calls over ~60 call-days with a binary outcome is thin, and
I would rather say so in advance than discover it after seeing a direction I like.

## 7. Placebos

1. **Form-shuffle within call-day cells**, 2,000 draws — measured size must be ≈5%. **If not,
   "unmeasurable", not "nothing".**
2. **Time-reversal placebo.** Recompute each call's form from *subsequent* outcomes instead of prior
   ones and re-run. **It should be at least as strong**; if the real-direction result is stronger
   than the reversed one by a wide margin that is reassuring, and if the reversed one is stronger,
   the no-lookahead construction has failed and the result is void.
3. **Chat-only placebo.** Replace form with the caller's *chat* identity. If chat alone reproduces
   the effect, this is a chat-quality finding mislabelled as caller skill.

## 8. Recorded expectation

**I expect UNDERPOWERED, with a small positive point estimate.** Prior work in this project found
caller grading did carry signal on the server's own data (the 61.7% / DUBI figures), so a positive
direction would not surprise me — **but 126 calls and a 15-point floor almost certainly cannot
resolve it.** Writing both halves down so neither outcome can be presented as a vindication.

## 9. Out of scope

- **No trading recommendation on SUPPORT.** Costs already put a $500 ticket above 24% round trip on
  the median pool; a form edge would have to be enormous to survive execution.
- **No caller identity, ever.** If the test appears to need it, it stops and goes back to the server.
- **Deviations** are declared in the results document with their effect on the number.

---

## AMENDMENT 1, made before any form × outcome statistic was computed

**The prereg above omitted a stopping rule.** §6 mentions n=126 without saying whether the test runs
there, and the corpus is **384 of 2,479 fetched** — it will grow roughly six-fold. Without a rule I
would be free to run at 126, dislike the answer, and re-run at 800, which is the peeking this
document exists to prevent.

**Fixed, now: the test runs ONCE, when the fetch completes (or on 2026-10-20, whichever is first).
No run at n=126.**

**Declaring it at this moment is the only legitimate time** — I have computed nothing about form
versus outcome, so I cannot be choosing a stopping point that suits a result. **If I run it earlier
for any reason, that run is the one that counts and the fact is recorded here.**

**The reliability threshold (§2, `form_n_known_7d ≥ 3`) and everything else stay as sealed.** The
expected n at completion is roughly 33% of ~2,000 priceable calls with a resolved form, so about
650 — which may clear the 15-point MDE floor that n=126 almost certainly could not.

---

## AMENDMENT 2 — made 2026-10-13 BEFORE any form × outcome statistic was computed

**Reason: the server flagged caller concentration when shipping step 2, and it invalidates this
prereg's clustering unit. The flag came before I read anything, and I have computed nothing.**

### A. What the refreshed corpus actually looks like

| | at seal (384 rows) | now (2,442 rows) |
|---|---|---|
| eligible at `form_n_known_7d ≥ 3` | 126 | **1,528** |
| `form_n_prior_calls` median | 22 | **82** |
| `form_n_prior_calls` p90 | 59 | **388** |
| **`form_n_prior_calls` max** | **71** | **540** |

**Server's count, which I verified: 126 human callers, the top caller has 541 calls, the top 10 hold
~1,477 of the 1,528 eligible rows — about 97%.** My own proxy agrees: **46% of eligible rows come
from callers with >100 prior calls, 16% from >300.**

### B. 🔴 Why this breaks §3 as sealed

§3 clusters on the **call-day** and bootstraps whole call-days. **That does nothing about caller
concentration, because the same caller recurs across many days.** With ~10 effective callers:

- **the day-block CI is too NARROW**, so **z is inflated** — the test over-rejects;
- **and the error runs in the dangerous direction.** The funding replication's placebo was
  conservative, so a positive there was trustworthy. **Here a positive could be manufactured by the
  clustering choice alone.**

**Worse, the hypothesis itself is caller-level.** "A caller's prior hit rate predicts their next
call" is a statement about callers. **With one caller supplying 541 calls, a day-clustered positive
could mean "this one caller is good", which is n=1 for the thing being claimed.**

**At 384 rows this was invisible — max prior calls was 71.** The concentration only became legible at
the full corpus, which is exactly when the prereg said to run. **So this is a defect discovered at the
gate, not a preference discovered after a result.**

### C. The amendment

**1. The CALLER becomes the primary clustering unit.** Caller-block bootstrap, 4,000 reps, resampling
whole callers. **The day-clustered figure is still reported, beside it, as the secondary.**

**2. On disagreement the CALLER-clustered CI governs.** The hypothesis is caller-level and the
concentration makes day-clustering anti-conservative. **Fixed now, before any number exists.**

**3. Report the effective sample size**, not just 1,528: number of distinct callers, and Kish
effective n from the call-count distribution. **Any claim quoting 1,528 as the sample is prohibited.**

**4. NEW pre-specified robustness check — leave-the-top-caller-out.** Re-run excluding the single
largest caller, and separately excluding the top 3. **If the effect does not survive, the finding is
one caller's track record and must be reported as such.** With 97% of rows in 10 callers this is the
single most informative check available, and it is specified before any read.

**5. This requires a clustering key, which this machine must not have as an identity.** The server
offered **an opaque per-run random `caller_cluster` id that cannot be linked across runs.** That is
accepted: it groups rows without naming anyone, is useless outside the run, and **`caller_hash` is
still never read here.**

**6. THE TEST DOES NOT RUN UNTIL THAT KEY ARRIVES.** Running now would mean knowingly using a
clustering unit I have just established is wrong in the anti-conservative direction.

### D. Deferral, recorded so it cannot be misread later

**The sealed trigger — fetch completion — fired on 2026-10-13 ~06:40 and the gate is OPEN.** The run
is deferred twice now: first because the server's step-2 join had not been rebuilt, now because the
clustering key does not exist.

**Neither deferral is mine to choose, and in neither case have I seen a form × outcome quantity.**
**When the key lands it runs ONCE, immediately, and this amendment is part of what runs.** If I ever
run it before then, that run is the one that counts — the original seal's rule, unchanged.

### E. Expectation, restated under the amendment

**§8 said UNDERPOWERED with a small positive. I now expect that MORE strongly, not less.** 1,528 rows
looked like power; **~126 callers with 97% of the mass in 10 of them is thin**, and the leave-one-out
check in C4 is likely to be the result rather than the robustness note. **Writing that down before
seeing anything.**
