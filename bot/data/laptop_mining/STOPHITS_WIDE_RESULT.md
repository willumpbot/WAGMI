# 🟢 `funding_hot → more stop hits` REPLICATES out-of-sample — and the LIVE configuration inherits it

**Second genuine out-of-sample replication tonight.** Prereg `PREREG_STOPHITS_WIDE`, sealed
**`81d016b7`**, commit `208a908e`, run **once**. Read in the prereg's order.

---

## 1. Is the test valid? — placebo size at δ=0

**Yes, and every arm is conservative or at nominal.** Sizes across all 12 arms: **0.015 – 0.035**, all
inside `SIZE_OK = (0.001, 0.09)` and all **at or below** the nominal 0.05. **Under-rejection means
every positive below was won against a stricter-than-nominal bar.**

## 2. MDE, before any effect

**+2.0 pp** on every `(c) NEW156` arm; **+2.57 pp** on the 17-coin arms. **I explicitly declined to
predict this** after missing it on the previous replication — recorded as the right call, since the
number is load-bearing in §4.

## 3. Counts

**145 week-clusters** on every arm. Matched cells: **4,087 – 4,664** on `(c)`, **1,907** on ORIG17.
Baseline stop-exceedance **17.72%** (fitted `em`) and **21.42%** (naive `em`).

## 4. 🎯 The canary — verified BEFORE sealing, and it matched at run time

| arm | required | observed |
|---|---|---|
| ORIG17, naive `em`, `ge`, unfiltered | +2.64 pp, t 3.31, 2,269 cells, 26.33% fired | **+2.64 pp, t 3.31, 2,269 cells, 26.33%** ✅ |
| ORIG17, naive `em`, `gt`, unfiltered | +2.68 pp, t 3.04, 18.92% fired | **+2.68 pp, t 3.04, 1,909 cells, 18.92%** ✅ |

**`PREREG_FUNDING_WIDE`'s canary was a hope and it failed, voiding that entire run. This one was
reproduced to the digit before the seal and matched again at run time.** That is the difference
between a check and a wish.

## 5. The two primaries — reported together, neither promoted

| | question | effect | t | 95% CI | vs MDE | verdict |
|---|---|---|---|---|---|---|
| **(A) CLAIM-REPLICATION**<br>naive `em`, `ge` | does the **published claim** hold on unseen coins? | **+2.37 pp** | **7.10** | [+1.72, +3.03] | above 2.0 | **🟢 replicates** |
| **(B) LIVE-CONFIG**<br>fitted `em`, `gt` | does the **condition the bot fires on**, judged against **the stop the bot sets**, hold on unseen coins? | **+2.40 pp** | **6.14** | [+1.63, +3.16] | above 2.0 | **🟢 replicates** |

**Both hold, and they agree to 0.03 pp.** The prereg's worst case — claim real but live configuration
not inheriting it — **did not happen.** The `em` and operator discrepancies I found while building
this are real, and they do **not** change the conclusion on held-out data.

**t rises from 3.31 in-sample to 7.10 out-of-sample** because the held-out panel carries ~2× the cells
at the same 145 week-clusters. **The clusters are what bound the inference, and they did not grow** —
so read the t as precision within weeks, not as more independent evidence.

## 6. The full 2×2 — and Amendment 1 earns its keep

| `em` | operator | fires | effect | t | verdict |
|---|---|---|---|---|---|
| naive | `ge` | 30.40% | +2.37 pp | 7.10 | replicates |
| naive | `gt` | 14.43% | **+3.48 pp** | **8.63** | replicates |
| fitted | `ge` | 30.40% | **+1.69 pp** | 5.13 | **positive but underpowered** |
| fitted | `gt` | 14.43% | +2.40 pp | 6.14 | replicates |

**Three of four cells replicate. The fourth is the case Amendment 1 was written for:** `+1.69 pp` sits
**below** its own 2.0 pp MDE while its CI still excludes zero at t 5.13. **Under the old rule that
would have been called "unmeasurable" — which would have been wrong, and under a naive reading it
would have been called a clean positive — which would also have been wrong.** "Positive but
underpowered" is the only honest label, and this result is the first live demonstration that the
amendment was necessary rather than pedantic.

**The operator matters more than the `em` here:** switching `ge → gt` *raises* the effect (+2.37 →
+3.48 naive, +1.69 → +2.40 fitted) while flagging **half as many coin-days** (30.4% → 14.4%). **The
stricter live flag is more concentrated, not weaker** — the tied block at the HL default funding rate
that `ge` sweeps in is apparently diluting the signal.

## 7. Supporting arms

| arm | effect | t | verdict |
|---|---|---|---|
| (b) ORIG17 filtered, fitted `em`, `gt` | +2.67 pp | 3.27 | replicates |
| **(c_raw) NEW156 UNFILTERED** | **+2.67 pp** | 7.25 | replicates → **filter-robust** |
| **(c) NEW156 FROZEN cutoff** | **+2.58 pp** | 6.34 | replicates → **not rank-dependent** |
| (a) ALL173 — **CONTAMINATED** | +2.24 pp | 6.13 | *never quotable as a replication* |

**Both pre-specified robustness checks pass**, same as the funding replication: removing the
backfilled rows changes nothing, and freezing the quintile cutoff to the original 17 coins changes
nothing.

## 8. K-curve on (B) — shape only; the verdict rests on K = 1.65

| K | baseline exceedance | effect | t |
|---|---|---|---|
| 1.00 | 37.77% | +3.44 pp | 6.36 |
| 1.50 | 21.14% | +2.67 pp | 5.88 |
| **1.65** | **17.72%** | **+2.40 pp** | **6.14** |
| 2.00 | 11.95% | +1.80 pp | 5.04 |

**Monotone and sensible: a wider stop is hit less often, and the `funding_hot` excess shrinks with
it.** Nothing here is cherry-picked — K = 1.65 was fixed by the prereg and sits mid-curve.

## 9. Scoring my recorded predictions

| predicted in advance | outcome |
|---|---|
| canary reproduces both operators | ✅ exact |
| **P(A) ≈ 60%** — published claim replicates | ✅ it did |
| **P(B) ≈ 55%** — live config replicates | ✅ it did |
| attenuation to **+1.2 to +2.2 pp** | ❌ **MISSED HIGH** — observed +2.37 and +2.40. I over-predicted decay. Only the fitted/`ge` cell (+1.69) fell in my band |
| declined to predict the MDE | ✅ right call — it came in at 2.0 pp and is load-bearing in §6 |

**Four of five, and the miss is the same direction as last time: I expect more attenuation than
happens.** Two replications in one night, both landing above my predicted decay. **That is now a
calibration bias worth correcting, not a one-off.**

## 10. What this means, and what it does not

**It means:** `funding_hot` days hit a 1.65-expected-move stop **about 2.4 percentage points more
often** — ~20% relative on a 17.7% baseline — and this holds on **156 coins the claim was never tested
on**, under the exact flag the bot fires and the exact forecast the bot sizes from. **This is a sizing
and stop-width input, and it is now the best-evidenced thing in the project.**

**It does not mean the `em` problem is harmless.** The claim's own `em` is **not** the bot's `em`
(`funding_stop.py` hardcodes an unfitted HAR — see §11), and the fitted-`em` effect is consistently
**smaller** (+1.69/+2.40 vs +2.37/+3.48). **Any decision number derived from the published figure —
including the K\* = 1.698 "2.9% wider stop" recommendation — was calibrated on the wrong forecast and
should be recomputed on the fitted `em` before it is acted on.**

## 11. 🔴 A fourth `exp_move` variant, found while building this

`funding_stop.py:41-42` hardcodes `Y1B = (0.0, 0.35, 0.35, 0.30)`, `Y1S = 1.0` — **no intercept, no
smearing correction.** `size_flags.py` loads the fitted `[-0.3921, 0.0521, 0.2143, 0.5201]` with
smearing **1.7389** from `volatility_forecast.json`.

**Confirmed by reproduction, not assumed:** with the naive coefficients both published figures come
back to the digit (+2.64/t 3.31/2,269 cells and +2.68/t 3.04); with the fitted ones they do not. **This
belongs in the server's D3 ledger as a fourth variant**, and it is the one sitting inside the evidence
for a card that feeds the terminal.

## Limits

- **145 week-clusters** — unchanged from in-sample. The cross-section grew; the independent time
  dimension did not.
- **`START = "2024-01-01"`**, Hyperliquid only, one era.
- **Unsigned.** Exceedance probability, not direction.
- **`(a) ALL173` contains the discovery sample** and is reported for completeness only.
- Run once, 12 arms, `stophits_wide.json`. Canary matched; no amendment was needed.
