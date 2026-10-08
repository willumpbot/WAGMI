# Geometry v3 — FINAL VERDICT: HOLD. Nothing here is statistically actionable.

> ## 🔴 READ THIS BEFORE ANY OF THE BODY
>
> This document went through **two** red teams and was cut down twice. The body below is the working
> record of an evolving — and partly wrong — analysis. **The conclusion is at the top here.**
>
> | claim | status |
> |---|---|
> | v2's null was `(geometry) − (direction)` and could not detect geometry | **STANDS** — verified to 5.6e-17; v2's refutation was wrong |
> | the direction-free decomposition `(real+flip)/2` is the right estimator | **STANDS** |
> | tightening the stop to ×0.5 is harmful | **STANDS** (−0.13R to −0.20R) |
> | target-only changes at ×1 are null | **STANDS** |
> | **+0.1187R for `×2 \| 0.5R`** | **WITHDRAWN** — week-mean t = 1.41, CI [−0.0392, +0.1858] contains zero; pooled figure was 62% inflated by unequal week sizes |
> | **target `1.5R → 0.5R`** | **WITHDRAWN** — never tested at ×2; week-weighted it is **−0.0312R**, 6/14 weeks positive |
> | **the fee table (0.1272R at ×1)** | **WRONG BASE** — I used the *median* stop width. The simulation's **mean** `feeR` is **0.1483R at ×1, 0.0741R at ×2** |
> | **"71% fee / 46% something else"** | **WITHDRAWN** — fee share is 62% at ×2 and 82% at ×32; there is no unexplained 46% |
> | **"TIE_RULE means the remainder is understated"** | **WRONG THREE WAYS** — see below. It was my only argument for the non-fee half |
> | **"×4 never binds"** | **FALSE** — it binds on **44.3%** of trades. `BIND_FLOOR = 0.50` chose the answer |
> | **the synthetic control** | **COULD NOT FAIL** — `h0 = ds - ds.mean()` pins the mean to zero, then the CI is built around that same mean. 0/400 seeds reject |
> | **the +0.0741R fee saving** | **arithmetic, not evidence.** `feeR(m) = feeR(1)/m` by construction — positive on every trade on any data, including a random walk |
>
> **The TIE_RULE citation was wrong three ways, and it was load-bearing:**
> 1. **Zero exposure.** The sim applies the tie rule only to bars touching *both* levels — that is
>    **0 of 15,663 trades** at `2.0|0.5` and 2 of 15,663 at the default. It has *no effect* on the
>    comparison I used it to defend.
> 2. **Wrong sign.** `TIE_RULE.md` concludes correcting it would *shrink* the advantage. I cited it as
>    making the advantage *understated*. I wrote both documents.
> 3. **Wrong sample.** The 75–81% figures are synthetic brackets from 2026-09-21→10-08, a different
>    period that `TIE_RULE.md` itself flags as untested travel.
>
> **A driftless-GBM placebo reproduces ~95% of the whole surface** (+0.1131R at `2.0|0.5` vs +0.1187R
> measured). The effect is mechanical. There is no edge content in it.
>
> **What to do: nothing to the bot.** The one real thing is an *operational* question for the owner —
> fees per unit of risk halve if the stop doubles **and position size halves** to hold dollar risk
> constant. Hold notional constant and the dollar fee is unchanged while dollar risk doubles, so the
> "saving" is only a change of units. That is a sizing preference, not a result.

---

_2026-10-08. Red team `wj68xvlf8`, two independent reviewers + synthesiser, on `geometry_v2.py`.
Verdict: **NEGATIVE_TOO_STRONG**, high confidence. Then red team `wp73ppfxp` (5 agents) cut this
document down in turn. Body kept as the working record. Supersedes `GEOMETRY_V2.md` and §2 of
`RETRACTION.md`; superseded in its conclusions by the box above._

---

## Headline

**My side-flip null was mathematically incapable of detecting the thing it was built to test.** It
computed `flip(cell) − flip(default)`, which is algebraically `(geometry effect) − (directional
effect)`. So "flip ≈ 0.00R" did not mean "no geometry" — it meant **"geometry and direction are the
same size,"** which is exactly what the data says.

The honest decomposition of the original +0.3479R at `stop ×32 | tp 0.5R`:

| component | value | what it is |
|---|---|---|
| **direction-free geometry** | **+0.1745R** | real, mechanical, **71% explained by fee drag** |
| directional | +0.1734R | depends on signal quality — still unvalidated |
| original `real_adv` | +0.3479R | the sum |
| my null's `flip_adv` | **+0.0010R** | the *difference* — near-exact cancellation |

`GEOMETRY_V2.md:107` said "~0.34R of that is leverage on being wrong." That is **wrong by a factor of
two.** About half is a genuine cost effect.

---

## The algebra, verified to machine precision

With `sym = (real+flip)/2` and `dir = (real−flip)/2`:

```
sym_adv + dir_adv == real_adv      max error 5.6e-17   (over 23 cells)
sym_adv − dir_adv == flip_adv      max error 3.5e-17
```

My null tested `sym − dir ≈ 0`, i.e. `sym ≈ dir`. It can only return "no geometry" when there is
**no geometry *or* geometry equals direction**. It never distinguished the two. `(real+flip)/2` — the
correct direction-free estimator — is computed nowhere in `geometry_v2.py`.

**20 of 23 cells have a positive direction-free advantage. Median +0.1606R.** And in every wide cell
the two components sit on top of each other, which is why the null read zero:

| cell | sym (geometry) | dir (directional) | dir/sym | my `flip_adv` |
|---|---|---|---|---|
| 8.0\|0.5 | +0.1832 | +0.1790 | 0.98 | +0.0042 |
| 12.0\|0.5 | +0.1771 | +0.1832 | 1.04 | −0.0062 |
| 20.0\|0.5 | +0.1721 | +0.1762 | 1.02 | −0.0041 |
| 32.0\|0.5 | +0.1745 | +0.1734 | 0.99 | +0.0010 |

### And the cancellation is forced, not coincidental
Fee drag in R is `2×9bps / (m × base)` and the directional term is `mu / (m × base)`. **Both scale as
1/m.** If they cancel at one stop width they cancel at all of them. So `GEOMETRY_V2.md:50`'s "~0.00R
at every stop width" is **one algebraic identity restated eight times** — the identical sin the
retraction correctly charged against v1's "4/4 folds." Measured dir/fee ratio across ×1→×32: 1.137,
1.388, 0.597, 1.116, 1.046, 1.044, 1.044.

### The reviewer's synthetic control settles it
A **known-real** direction-free geometry effect (+0.148R, fee saving ×1→×32) was injected and held
identical in every run; only the directional edge varied. My null's verdict:

| injected drift mu/h | my null says |
|---|---|
| 0.0000 | 5/5 "GEOMETRY SURVIVES" |
| −0.00008 | 5/5 survives |
| −0.00014 | 2/5 |
| **−0.00022** (this data's regime) | **1/5** |
| −0.00080 | 1/5 |

The verdict tracks the *directional* edge, not the geometry. **It destroys a known-real effect by
construction.**

---

## The mechanism: this is fee drag, and it is the bot's biggest controllable cost

Fees in R scale as `1/m`, so a tight stop pays enormously in R terms:

| stop | fee drag per trade | recovered vs ×1 |
|---|---|---|
| **×1 (bot default)** | **0.1272 R** | — |
| ×4 | 0.0318 R | +0.0954 R |
| ×8 | 0.0159 R | +0.1113 R |
| ×32 | 0.0040 R | +0.1232 R |

An 18bps round trip against a 1.4% stop **is 12.7% of R**. The predicted saving (+0.1232R) explains
**71%** of the measured +0.1745R; the remainder is tie-rule and terminal-mark geometry — and
`TIE_RULE.md` shows that part is *understated*, since targets are actually hit first 45.5% of the
time where the sim assumed 0%.

**This is a cost claim, not an edge claim. That is why it survives** — it needs nothing to be
predicted correctly. It does require re-sizing to hold dollar risk constant when the stop widens;
otherwise the R-unit saving is just a change of units.

---

## But "wide stop" is the wrong name for it — beyond ×20 there is no bracket

If a bracket binds, the target must matter. It stops mattering:

| stop | real_R at tp 0.5 / 1.0 / 1.5 | spread |
|---|---|---|
| **×1** | −0.2178 / −0.2808 / −0.3477 | **0.1299** |
| ×4 | −0.0463 / −0.0396 / −0.0432 | 0.0067 |
| ×20 | +0.0005 / +0.0003 / +0.0003 | 0.0002 |
| ×32 | +0.0002 / +0.0002 / +0.0002 | **0.0000** |

At ×20+ every trade exits by marking to the 48h horizon and `real_R → +0.0002 ≈ 0`. **The finding is
not "wide stops win." It is "the bot's bracket is tight enough that fees eat it, and removing the
bracket entirely stops the bleeding."** The surface saturates where the bracket stops binding — so
reading an optimum off ×20 or ×32 is reading noise about a stop that never fires.

---

## Three more defects the red team found, which I accept

1. **"Zero of 24 cells survive the null" is false — the null ran on 5 cells.**
   `geometry_v2.json` carries `geometry_survives_null` on exactly `8.0|0.5, 12.0|0.5, 12.0|1.0,
   20.0|0.5, 32.0|0.5`. The other 19 were never tested. `GEOMETRY_V2.md:20` overstates its own
   coverage — the same failure mode as v1.
2. **The null had no power against the effects it dismissed.** On `8.0|0.5` the flip CI half-width is
   0.3103R. Injecting the true direction-free effect (0.1745R) is killed; it needs ≥0.35R to fire. On
   the tp-1.0R residual, injecting the *full real effect* is still killed. "Fails the null" meant
   "the null had no power."
3. **The load-bearing fact fails the clustering standard the retraction itself mandates.** The
   reviewer recomputes the 48h drift as week-clustered t = **−1.02** (day −0.89, symbol −1.56; only
   4 symbols, heavily overlapping windows), week-block CI95 [−1.0610%, +0.4292%] — **includes zero**.
   `RETRACTION.md:147` demands week-level blocks for every cell CI but never applied them here.
   Separately the quoted "−0.2174%, t = −10.0, Robust" is **unreproducible from `geometry_v2.py`**,
   which computes no raw return at all; note `real_R` at `1.0|0.5` is −0.2178, so this looks like an
   R-value reprinted as a percentage. Needs re-deriving from scratch, not re-quoting.

---

## Where this leaves the stop decision

| claim | status |
|---|---|
| "wider stops beat the bot default by +0.35R" | **half right** — +0.17R geometry is real, +0.17R directional is unvalidated |
| "it is all leverage on being wrong" (`GEOMETRY_V2.md`) | **withdrawn** — my null could not have shown that |
| "the bot's bracket costs ~0.127R/trade in fees" | **real, mechanical, direction-free** |
| "×20 or ×32 is the optimum" | **withdrawn** — the bracket never binds there; it is not a stop |
| the 48h drift, "t = −10.0, robust" | **not significant** week-clustered (t = −1.02), and unreproducible |

**So the stop change is defensible on cost grounds at ~+0.12R, not on edge grounds at +0.35R.** That
is a smaller, duller, and much more trustworthy reason, and it does not need any prediction to hold.

---

# ⚠️ THE RECOMMENDATION BELOW WAS CUT DOWN BY A RED TEAM — read this first

_Red team `wp73ppfxp`, verdict PARTLY_CONFIRMED / high confidence. Both fatal findings verified by me
in `verify_v3.py` / `verify_v3.json` before acceptance._

**What survived:** the mechanism, the v2 reversal, the decomposition, the synthetic control, "tighter
is harmful", and "target-only at ×1 is null". All reproduce.

**What did not:** the headline number and half the decision card.

| claim | published | equal-weighted week mean | week t | CI95 | weeks + |
|---|---|---|---|---|---|
| ×2/0.5R vs default | **+0.1187R** | **+0.0733R** | +1.41 | **[−0.0392, +0.1858]** | 9/14 |
| target 1.5R→0.5R at ×2 (sym) | +0.0367R | **−0.0312R** | −0.79 | [−0.1168, +0.0544] | 6/14 |
| target 1.5R→0.5R at ×2 (real) | +0.0429R | **−0.0103R** | −0.18 | [−0.1328, +0.1122] | 7/14 |

1. **The recommended cell fails week-level clustering — the exact standard this document enforces
   against the 48h drift claim.** I killed that claim for being week-clustered t = −1.02 with a CI
   containing zero, then recommended a live change off a cell that is week-clustered t = +1.41 with a
   CI containing zero. The pooled mean was **62% larger** than the equal-weighted week mean; with only
   14 blocks the percentile bootstrap used in `geometry_v3.py` is anti-conservative.
2. **The target half was never tested at the recommended stop width.** Finding 2 below tests
   target-only changes at ×1 and finds them null — but the card recommends the target change at ×2,
   where it is **negative** week-weighted. And the fee saving is *identical* across tp 0.5/1.0/1.5 at
   a given stop (0.0636R in all three), so the target half **cannot inherit any of the fee argument.**

## FINAL: HOLD. Nothing here is statistically actionable.

The full 5-agent review went further than the two fatal items above. Three more, all verified:

1. **The fee saving is an algebraic identity, not a measurement.** `feeR = 2×9bps×entry/(m×base)`
   gives `feeR(m) = feeR(1)/m` exactly, per trade. It is positive on **every** trade on **any** data,
   including a driftless random walk — so "positive in all 14 weeks, t = +8.84" is a property of
   arithmetic, not evidence. And my figures were off base: the simulation's **mean** `feeR` is
   **0.1483R at ×1 and 0.0741R at ×2** (I used the median stop width, 1.4151%, giving 0.1272/0.0636).
   The saving is therefore **+0.0741R**, mean-exact — and the fee share of the headline is 62%, not
   54%, which **destroys my "46% comes from somewhere else" argument.**
2. **The non-fee remainder is not significant anywhere that matters.** At `2.0|0.5` it is +0.0445R,
   week-block CI **[−0.0308, +0.0935]**. Across all 24 cells it is significantly positive in exactly
   **one** cell — `8.0|0.5` — which I reject for not binding.
3. **`BIND_FLOOR = 0.50` chose the answer, and my reason for rejecting ×4 was false.**
   `sym_adv` is monotone in stop width until saturation, so the floor *is* the recommendation:
   ≤0.143 → `8.0|0.5`; 0.143–0.443 → `4.0|0.5`; 0.443–0.791 → `2.0|0.5`; >0.791 → **nothing
   qualifies.** I wrote that ×4 "never binds" — **it binds on 44.3% of trades.** `saturated_cells` is
   just the floor relabelled. Requiring a bracket to resolve most trades leaves nothing actionable,
   and that is the finding the floor concealed.
4. **My synthetic control's zero arm could not fail.** `h0 = ds - ds.mean()` pins the sample mean to
   exactly zero and `boot_ci` then builds a percentile CI around that same mean; 0 of 400 seeds
   reject. "No false positive at zero" was guaranteed by construction. The power curve also ran only
   at `8.0|0.5` — a cell this document says must not be read — and the recommended effect sits
   **below** the 0.08R detection floor it reported.
5. **A driftless-GBM placebo reproduces ~95% of the surface** (+0.1131R at `2.0|0.5` vs +0.1187R
   measured). That confirms the effect is mechanical, and confirms there is no edge content in it.

### So the only thing left is an operational choice, not a finding

Fees per unit of risk halve if the stop doubles **and position size halves** to hold dollar risk
constant. Hold notional constant instead and the dollar fee is unchanged while dollar risk doubles —
the "saving" is then just a change of units. That is a question for the owner about how he wants to
size, not a result this analysis established.

**Withdrawn:** the +0.1187R headline, the `target 1.5R → 0.5R` change, the TIE_RULE support argument
(see below), and the ×2 recommendation itself.

<details>
<summary>Superseded intermediate position (kept for the record)</summary>

**Stop ×1 → ×2, worth +0.0636R per trade, on deterministic fee arithmetic.**

```
fee_R = 2 × 9bps / (m × base)
  stop ×1 : 0.1272 R per trade
  stop ×2 : 0.0636 R per trade
  saving  : +0.0636 R      <- arithmetic; no significance test applies
```

This is not a statistical claim, so clustering does not bite it. It requires position size to halve
so dollar risk is unchanged — at a fixed \$100 risk per trade, \$12.72 of fees becomes \$6.36.

</details>

**Withdrawn:** the +0.1187R headline, and the `target 1.5R → 0.5R` change. **Everything below this
line is the original write-up, kept for the working — read its "Recommendation" section as superseded
by this block.**

---

# RESULT — `geometry_v3.py`, all 24 cells, synthetic control passed

_Run 2026-10-08. 15,663 signals, 14 ISO weeks, 71 days. Data: `geometry_v3.json`._

## The synthetic control passes — the step v2 skipped

Built an exact-zero-effect dataset by removing the measured effect, then injected known deltas:

| injected | detected? | CI95 |
|---|---|---|
| **0.0000** | **no** | [−0.0730, +0.0480] |
| 0.0200 | no | [−0.0520, +0.0690] |
| 0.0500 | no | [−0.0212, +0.0985] |
| **0.0800** | **YES** | [+0.0078, +0.1276] |
| **0.1232** (fee prediction) | **YES** | [+0.0529, +0.1715] |
| 0.1745 | YES | [+0.1037, +0.2230] |

**No false positive at zero effect; smallest detectable effect 0.08R.** The estimator can see the
0.1232R fee prediction. v2's null could not have passed this — it killed a known-real 0.148R effect.

## All 24 cells, with the binding rate

| cell | bound | sym (geometry) | sym CI95 (week blocks) | dir | real adv | verdict |
|---|---|---|---|---|---|---|
| 0.5\|0.5 | 100.0% | **−0.1953** | [−0.2530, −0.1502] | +0.0996 | −0.0957 | **significantly WORSE** |
| 0.5\|1.0 | 99.7% | **−0.1372** | [−0.1987, −0.0852] | +0.0301 | −0.1071 | **significantly WORSE** |
| 0.5\|1.5 | 99.4% | **−0.1316** | [−0.1765, −0.0941] | +0.0208 | −0.1108 | **significantly WORSE** |
| 1.0\|0.5 | 98.3% | +0.0429 | [−0.0431, +0.1087] | +0.0870 | +0.1299 | not significant |
| 1.0\|1.0 | 93.5% | +0.0307 | [−0.0130, +0.0577] | +0.0362 | +0.0669 | not significant |
| **1.0\|1.5** | 86.0% | 0 | — | 0 | 0 | **← the bot today** |
| **2.0\|0.5** | **79.1%** | **+0.1187** | **[+0.0395, +0.1661]** | +0.0719 | +0.1906 | **real & binds** |
| 2.0\|1.0 | 60.6% | +0.1050 | [+0.0506, +0.1357] | +0.0437 | +0.1487 | real & binds |
| 2.0\|1.5 | 51.5% | +0.0820 | [+0.0174, +0.1414] | +0.0657 | +0.1477 | real & binds |
| 4.0\|0.5 | 44.3% | +0.1731 | [+0.0972, +0.2182] | +0.1282 | +0.3014 | real, barely binds |
| 8.0\|0.5 | 14.3% | +0.1832 | [+0.1137, +0.2312] | +0.1791 | +0.3623 | real but NO BRACKET |
| 32.0\|0.5 | **0.0%** | +0.1745 | [+0.1105, +0.2165] | +0.1735 | +0.3479 | real but NO BRACKET |

(All 24 in `geometry_v3.json`. **15 of 24 cells are saturated** — the bracket never binds.)

## Three findings

1. **Tightening the stop is significantly harmful.** At ×0.5 the direction-free cost is −0.13R to
   −0.20R, CIs well clear of zero. This is the sturdiest result in the whole geometry thread, and it
   is a *cost* result — it needs nothing predicted. (v3 also fixes a labelling bug that printed these
   as "not significant" because the verdict only tested the upper bound.)
2. **Changing only the target does nothing.** `1.0|0.5` and `1.0|1.0` both have CIs containing zero.
   v2's "cheap alternative — keep the stop, change the target" is **null**.
3. **The actionable setting is stop ×2, target 0.5R.** +0.1187R direction-free,
   CI [+0.0395, +0.1661], bracket still binding on **79.1%** of trades.

## Recommendation: ×2 / 0.5R — not ×8, not ×32

Bigger `sym` values exist at ×4–×32, but the binding rate collapses 79.1% → 44.3% → 14.3% → 0.0%.
Those cells measure *"no bracket"*, not *"a wider bracket"*, so reading an optimum off them is reading
noise about a stop that never fires. `×2 | 0.5R` is where a real bracket still exists and the fee
saving is already captured: fees predict +0.0636R of the +0.1187R (54%), and per `TIE_RULE.md` the
remainder is **understated** — at tp 0.5R the target is really touched first 75–81% of the time where
the sim assumed 0%.

**So the decision card becomes: stop ×1 → ×2, target 1.5R → 0.5R, worth +0.1187R per trade on
fee/geometry grounds alone.** Ignore the +0.0719R directional half. Far smaller and duller than the
×8–×32 the refuted v1 pointed at — and it does not depend on any prediction being right.

### Caveat on the binding floor
`BIND_FLOOR = 0.50` is my judgment call and it is load-bearing: it excludes `4.0|0.5`, which has a
larger `sym` (+0.1731R) but binds only 44.3%. If a bracket resolving fewer than half of trades is
acceptable, ×4 is the aggressive read. ×2 is the conservative one and the one I recommend.

## Still owed
- Re-derive the 48h drift from the corrected entry with week clustering, or drop the claim. The
  `−0.2174%, t = −10.0, "robust"` figure remains unreproducible and must not be quoted.
- Apply the *measured* tie rule rather than the conservative one, which should widen the ×2 advantage.

## Lesson
The retraction fixed a real problem — validating on data that had informed the choice — and then I
swung too far: I accepted a null that returned the answer I now expected, without checking what it
could detect. **A null that cannot fail is as useless as a test that cannot fail.** The synthetic
control the reviewer ran (inject a known-real effect, confirm the test finds it) is the step I
skipped, and it is cheap. It becomes standard before any null is used to kill a finding.
