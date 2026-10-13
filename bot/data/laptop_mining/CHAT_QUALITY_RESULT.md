# Chat quality — **UNDERPOWERED, as predicted.** The primary misses at **z 1.87** against a 2.24 bar.

**`PREREG_CHAT_QUALITY_2026-10-12`, run ONCE at the gate (megacall fetch complete).** Read in the
prereg's order: placebo → MDE → shared-day count → only then the effect.

**Recorded expectation was "I expect UNDERPOWERED." That is what happened — and it is not a
vindication, because a near-miss at z 1.87 is the least informative outcome available.**

---

## 1. Is the test valid? — placebo

**Chat-label shuffle WITHIN shared days, 2,000 draws:** size **0.067** (primary), **0.078**
(secondary). **Both inside [0.02, 0.09], so both tests are correctly sized** and the results below
mean what they say.

## 2. MDE, before the effect

| pair | simulated MDE (80% power) | pre-committed floor |
|---|---|---|
| primary | **8.0 pp** | 15 pp |
| secondary | **10.0 pp** | 15 pp |

**Both clear the floor**, so unlike the prereg's own pessimism ("the floor is stated now because it is
probably fatal") the test was *not* doomed by power alone. **The 6.4× corpus growth did its job:**
32 shared days instead of the 14 available at seal.

## 3. Counts

| pair | shared days | calls |
|---|---|---|
| **dtn_hitters vs syndicate** | **32** | 96 vs 215 |
| dtn vs dtn_hitters | 23 | 743 vs 41 |

**The prereg predicted "~32 at full corpus" and the run produced exactly 32.** That match is what
confirmed the implementation after the void run below.

## 4. The result

| | eq-weighted (GOVERNS) | pooled | 95% CI | z | sign-stable | verdict |
|---|---|---|---|---|---|---|
| **PRIMARY** `dtn_hitters` − `syndicate` | **+14.5 pp** | +8.9 pp | **[−0.7, +29.6]** | **1.87** | yes (+11.9 / +17.0) | **UNDERPOWERED** |
| SECONDARY `dtn` − `dtn_hitters` | +12.7 pp | +19.5 pp | [−5.5, +28.9] | 1.45 | **NO** (−4.1 / +28.0) | **UNDERPOWERED** |

**Why the primary is UNDERPOWERED despite a large estimate:** it satisfies four of the five SUPPORT
criteria — sign-stable across halves, pooled and equal-weighted agree in sign, effect (14.5 pp) well
above its MDE (8.0 pp), placebo valid — **and fails the first one. The CI's lower bound is −0.7 pp and
z is 1.87 against the Bonferroni-corrected bar of 2.24.**

**That is the whole finding: the gap is probably real and we cannot say so.** A lower bound of −0.7
on a +14.5 estimate is a test that nearly resolved and didn't.

**I am not going to call this "suggestive evidence that `dtn_hitters` beats `syndicate`."** The bar
was fixed in advance at 2.24 precisely so a 1.87 could not be talked across it, and this project's
history is that every result talked across a line later died.

**The secondary is weaker than its numbers look.** +12.7 pp equal-weighted, but **the halves are −4.1
and +28.0** — the sign flips. The prereg required sign stability for exactly this case. Treat it as
noise.

**`ret_7d` adds nothing:** primary eq +1.4% against pooled −5.1% (signs disagree, z 0.08). No claim
either way.

## 5. 🔴 Death rates — the prereg said this "may be the whole story", and it partly is

| chat | n | dead | death rate | hit2x_7d |
|---|---|---|---|---|
| `dtn` | 1,861 | 98 | **5.3%** | **40.6%** |
| `dtn_hitters` | 174 | 53 | **30.5%** | 33.3% |
| `syndicate` | 323 | 111 | **34.4%** | 31.0% |

**`dtn`'s death rate is six times lower than the other two, and its hit rate is the highest.** That
looks like a decisive quality difference and **it is not usable**, because `dtn` ends 2026-06-21 and
`syndicate` begins 2026-08-24 — **they never coexist.** The entire gap is confounded with era.

**This is exactly why the prereg permanently excluded `dtn` × `syndicate` before any number was
computed**, and seeing these three rows side by side is the best argument for that exclusion. **A
6× death-rate difference across non-overlapping eras is a market-regime fact wearing a
call-quality label.**

**The one comparison that IS era-matched** — `dtn_hitters` 30.5% vs `syndicate` 34.4% on shared days —
**is a 4-point death-rate gap, in the same direction as the 14.5 pp hit-rate gap.** So the primary
effect may be substantially a survival effect rather than a target-reaching one. **Not resolvable at
32 days, and flagged rather than claimed.**

## 6. 🔴 VOID RUN 1, disclosed — and it contaminated nothing

**The first execution reported "shared days: 1" for both pairs and could compute no effect at all.**

**Cause:** `day_of()` divided `call_ts` by 1000, but `call_outcomes.jsonl` stores it in **seconds**
(10 digits). Every call collapsed into ~20 days of **January 1970**, so almost no two calls shared a
day.

**What caught it: the prereg's own recorded number.** It states 14 shared days at 384 rows and
predicts ~32 at full corpus. **More data cannot reduce shared days, so "1" was impossible** — a
contradiction with a fact written down before the run.

**Unlike `PREREG_FUNDING_WIDE`'s void run, this one revealed nothing.** Both pairs returned
`CANNOT TEST` and no effect, placebo, or MDE was produced. **So the re-run is genuinely blind, and
the only cost was my time.**

**Fixed with a check that halts:** units are now detected (`>1e12` → ms) *and* the resulting year is
range-checked to 2024–2030, so a future units error stops the run instead of silently producing one
shared day.

## 7. Scoring the recorded expectation

| predicted in advance | outcome |
|---|---|
| **"I expect UNDERPOWERED"** | ✅ **correct** |
| MDE "probably fatal", floor near 14 pp | ❌ **too pessimistic** — actual MDE 8.0 pp. The corpus growth from 384 to 2,442 rows mattered more than I expected |
| ~32 shared days at full corpus | ✅ **exactly 32** |

**Second time tonight my power pessimism was wrong in the same direction** — I under-estimated what
the data would support, having over-estimated attenuation on both replications. **Three instances now:
I am systematically too gloomy about power and too gloomy about effect persistence.**

## 8. What would settle it

**Not more analysis — more shared days.** At 32 days a 14.5 pp gap sits just inside the noise. The
corpus is complete, so **the only route is forward: `dtn_hitters` and `syndicate` both continuing to
post.** At ~60 shared days the same effect would clear 2.24 comfortably.

**Do not re-run this prereg when that happens.** It ran once, as sealed. A new question at a larger n
needs a new document.

## Limits
- 32 shared days; the clustering unit is the day, never the call.
- The era confound makes `dtn` uncomparable to `syndicate` permanently, by construction.
- `dead` rows count as outcome FALSE and were never dropped.
- The primary's hit-rate gap and death-rate gap run the same way and cannot be separated here.
