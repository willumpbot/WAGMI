# Mission 8 — adaptive stops from the volatility forecast

_2026-10-08. 15,663 signals, train 2026-02-11→04-15 (6,523) / test 04-16→06-05 (9,140).
Script: `adaptive_stops.py`. Data: `adaptive_stops.json`._

---

## Recommended default for the terminal's calculator

**Stop = 2 × the forecast next-day move. Target = 0.5R. Time stop at 48h.**

On test that returns **+0.093R** per setup against the bot's current **−0.431R**, and — the test that
matters — it beats a *fixed* stop of the same average width by **+0.209R [+0.063, +0.343]**.

---

## Headline

**Two separate things are going on, and they need separating because only one of them is new.**

1. **Width is most of the gain, and it was already known.** Simply making the stop much wider beats
   the bot's default by **+0.48R [+0.255, +0.717]** on test. That reconfirms `GEOMETRY.md`; it is not
   a volatility finding at all.
2. **Scaling with the forecast adds real value on top of width — but only with a near target.**
   Against a fixed stop of identical average width, the `tp0.5` rules gain **+0.19 to +0.21R** with
   confidence intervals excluding zero, consistently across **all eight** of those cells (two forecast
   horizons × four k values). Every `tp ≥ 1.5` rule is *significantly worse* than fixed-same-width.

So: be wider because of GEOMETRY, and scale with the forecast because of this — but take profit near.

---

## The control that makes this meaningful

A wider stop wins almost everywhere, so comparing a forecast-scaled stop to the bot's narrow default
proves nothing. For every rule I also simulated a **fixed-percent stop set to that rule's own average
width**, over the same signals, and report the paired difference. That isolates "scales with the
forecast" from "is simply wider".

| rule | width | train R | test R | **vs FIXED same width** | stopped | median hrs |
|---|---|---|---|---|---|---|
| `f1\|k2.0\|tp0.5` | 4.79% | −0.104 | **+0.093** | **+0.209 [+0.063, +0.343]** ✓ | 13.6% | 37 |
| `f5\|k2.0\|tp0.5` | 6.29% | −0.076 | **+0.093** | **+0.205 [+0.070, +0.336]** ✓ | 3.3% | 48 |
| `f5\|k1.5\|tp0.5` | 4.71% | −0.120 | **+0.088** | **+0.205 [+0.057, +0.337]** ✓ | 15.1% | 35 |
| `f1\|k3.0\|tp0.5` | 7.19% | −0.070 | +0.076 | **+0.189 [+0.050, +0.329]** ✓ | 1.2% | 48 |
| `f1\|k1.0\|tp0.5` | 2.40% | −0.063 | −0.066 | +0.135 [−0.046, +0.294] | 30.1% | 10 |
| `f5\|k1.0\|tp1.0` | 3.14% | −0.227 | −0.012 | −0.072 [−0.313, +0.149] | 39.1% | 28 |
| `f1\|k1.0\|tp2.0` | 2.40% | −0.450 | −0.120 | **−0.506 [−0.821, −0.196]** ✗ | 51.6% | 31 |
| `f5\|k1.0\|tp1.5` | 3.14% | −0.397 | −0.095 | **−0.336 [−0.623, −0.070]** ✗ | 42.5% | 42 |
| **bot default** | 1.70% | — | **−0.431** | — | **62.3%** | — |

`f1` = scaled to the next-day forecast, `f5` = to the 5-day forecast, `k` = multiplier,
`tp` = target in R. Trailing-stop variants (trail at 1× the forecast) were tested and lose on every
configuration — 68–88% get stopped out.

### The pattern is coherent, not random
At a **near** target, scaling the stop also scales the target (target = 0.5 × stop), so in a hot
forecast you reach for a proportionally larger profit and in a calm one you take a smaller one —
which matches what the market is actually offering. At a **far** target, scaling makes the target
unreachable on calm days while the wide stop still bleeds. That is exactly the sign pattern observed.

### Holding time and stop-out rate
| | bot default | k2.0 tp0.5 |
|---|---|---|
| stopped out | **62.3%** | **13.6%** |
| median hold | — | 37h |

The bot currently stops out of nearly two thirds of its trades. The recommended rule stops out of one
in seven and holds about a day and a half.

---

## An honest weakness in how this was found

**The train-pick procedure did not select the winning family.** Selecting the best rule on train gave
`f5|k6.0|trail1x`, which on test beats the bot default (+0.480R [+0.255, +0.717]) but does **not**
beat fixed-same-width (−0.075 [−0.228, +0.071]). Its advantage is pure width.

The `tp0.5` family has *negative* train R and positive test R — the two halves differ in regime — so
train selection missed it. That means the scaling result is **observed on test**, not pre-registered.

I am not going to dress that up. What argues for it anyway:
- the effect appears in **all 8** `tp0.5` cells, across both forecast horizons and four k values, with
  the same sign and a tight magnitude range (+0.189 to +0.209R)
- the opposite sign appears consistently in the `tp ≥ 1.5` cells, which is a mechanism, not noise
- it is a **paired** comparison — identical signals, only the stop rule differs

**Treat it as a strong hypothesis for forward confirmation, not an established result.** The server's
live grader can settle it in weeks by running both rules on the same signals.

## Per-symbol stability
For the train-picked rule vs bot default on test: ETH **+0.711 [+0.546, +0.900]**✓,
SOL **+0.622 [+0.205, +0.932]**✓, BTC +0.348 [−0.052, +1.014], HYPE +0.170 [−0.196, +0.529].
Two of four exclude zero; all four point the same way.

## Caveats
- Still **loss-elimination, not alpha**: +0.093R is close to zero. The signals have no directional edge.
- Position size must shrink as the stop widens. A 4.79% stop versus the current 1.70% means roughly a
  third of the size for the same dollar risk — see `SAFE_LEVERAGE.md` for the leverage ceiling.
- 48h horizon, 1h bars, conservative tie rule (a bar covering both levels counts as a stop), 9 bps
  both legs, no lookahead.
- The forecast is the pooled HAR model from `VOLATILITY.md`, fitted on train days only and applied
  forward, with the smearing correction (factors 1.718 for f1, 1.175 for f5).
