# Geometry v3 — I over-retracted. Half the original finding is real, and it is a fee effect.

_2026-10-08. Red team `wj68xvlf8`, two independent reviewers + synthesiser, on `geometry_v2.py`.
Verdict: **NEGATIVE_TOO_STRONG**, high confidence. Every number below re-derived by me from
`geometry_v2.json` before accepting it. Supersedes `GEOMETRY_V2.md` and §2 of `RETRACTION.md`._

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

## What I owe next
- `(real+flip)/2` with week-block CIs **on all 24 cells**, not 5 — the direction-free estimate done right.
- Re-derive the 48h drift from the corrected entry with week clustering, or drop the claim.
- Find the stop width that minimises *total* cost where the bracket still binds (×4–×8), rather than
  reading a saturated surface.

## Lesson
The retraction fixed a real problem — validating on data that had informed the choice — and then I
swung too far: I accepted a null that returned the answer I now expected, without checking what it
could detect. **A null that cannot fail is as useless as a test that cannot fail.** The synthetic
control the reviewer ran (inject a known-real effect, confirm the test finds it) is the step I
skipped, and it is cheap. It becomes standard before any null is used to kill a finding.
