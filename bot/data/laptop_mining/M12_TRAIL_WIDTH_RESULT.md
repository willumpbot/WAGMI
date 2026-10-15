# M12 — 🔴 **CORRECTED: the 1-exp-move trail was never live.** The geometry finding stands, but it VALIDATES the bot's existing ATR trail rather than indicting it — and my grid stopped below the live setting.

> ## Correction, 2026-10-15 00:10Z — I called the 1-em trail "the incumbent" and "what the bot does now". It is neither.
>
> **The live trail is `execution/position_manager.py:906-920`:**
> `trailing_distance = atr × trailing_atr_mult (1.5) × style_mult`, where `style_mult` is
> `{tight 0.8, medium 1.0, loose 1.5}` — so **1.2× to 2.25× ATR**, with a 0.6–1.5%-of-entry fallback
> when ATR is 0. **Owner plans under `profits_only` have no trail at all** (the stop never moves).
>
> **The 1-em trail existed only in the server's replay tool and in my own sealed prereg's
> `partial_1R_har` arm.** I asserted "incumbent" from a label instead of reading
> `position_manager.py`, which was available the whole time. **Third instance of that exact class this
> week** — after the `.env` that did not exist (M8 §4) and "his live positions" (reply 136).
>
> **What changes:** the recommendation "change the trail" is void — there is nothing to change, and the
> bot already scales to ATR, which is what this study concluded it should do. **The measurements below
> are unaffected.**
>
> **And a gap I have to own: my grid ran 0.25 → 1.00 ATR, and the live setting is 1.2–2.25 ATR. My
> best-tested arm is BELOW the live floor.** The trend was monotonically improving up to 1.00, so the
> live width is plausibly better still — but **I did not test it and cannot say.** Extending the grid to
> 1.25 / 1.5 / 2.0 / 2.5 ATR is the run that would speak to the live configuration.

**Original title, kept for the record:** *"The current 1-exp-move trail is the worst arm tested and the
only one whose CI excludes zero. Their premise holds: scaling to the coin's own ATR helps ~3× more on
high-vol coins."* — the second sentence survives; the first describes a setting that was never live.

_2026-10-15. `m12_trail_width.py`. **EXPLORATORY**, no card above HYPOTHESIS. Source snapshot stamped.
176 coins, 250 random-time both-sided entries each, stop fixed at 1.65 × em in every arm so only the
trail varies, trail arms at +1R, 72h horizon, M1 v3 martingale control subtracted, bps net of 9 bps
fees, coin-clustered._

---

## 1. Their premise, measured before the study was designed

| | ATR60 ÷ HAR em |
|---|---|
| median (176 coins) | **2.31** (p10 1.84, p90 2.96) |
| low-vol third → high-vol third | **2.09 → 2.85** |
| correlation(ATR, ratio) | **+0.766** |
| **CASHCAT** | **29.3% / 8.5% = 3.44** |

**Correct, and the magnitude matters.** A 1-em trail is ~0.43 ATR at the median — and on CASHCAT it is
**0.29 ATR**, i.e. inside a routine intraday range. **That is not "taking profit", it is being stopped
out by noise.**

## 2. The result: the incumbent loses, and wider is monotonically better

**bps net of fees, control subtracted, equal-weighted by coin (ALL, 176 coins):**

| trail | bps | 95% CI | vs incumbent |
|---|---|---|---|
| **1.00 × em** (replay tool + my prereg only — NOT live) | **−16.14** | **[−25.52, −6.90]** | — |
| 0.25 × ATR | −15.69 | [−24.74, −6.41] | +0.44 |
| 0.50 × ATR | −9.59 | [−20.31, +0.26] | +6.55 |
| 0.75 × ATR | −2.27 | [−11.82, +7.39] | +13.87 |
| **1.00 × ATR** | **+4.89** | [−5.47, +14.85] | **+21.02** |

**🔴 The incumbent is the only arm whose CI excludes zero — and it is negative.** The finding here is
not "1 ATR is proven good" (its CI contains zero); it is **"1 em is measurably bad."**

**And the tight arm is if anything flattered by my implementation**: every arm exits *at* the trail
level, which is optimistic, and a tighter trail triggers far more often — so it collects that optimism
most. It still loses.

## 3. The interaction test — which is what actually vindicates their premise

A gain from "wider" alone would appear equally in every tercile. It does not:

| volatility tercile | mean ATR | 1.00 ATR vs incumbent |
|---|---|---|
| low third | 5.9%/day | **+13.14** |
| mid third | 7.7%/day | +11.27 |
| **high third** | **11.8%/day** | **+38.07** |

**~3× larger in the high-vol third.** Their hypothesis was specifically about high-vol coins and the
data agrees with that specificity, not just with "wider is better".

Both sides of the split agree in shape: ORIG17 **+40.73**, non-ORIG17 **+18.92** for 1 ATR vs incumbent.

## 4. 🔴 This does NOT contradict M10 — and the reconciliation is the useful part

M10 found positions **up at 48h lost money by being held** (−32 bps majors). That argues for cutting
winners *earlier*. M12 finds a tight trail *costs* money. Those look opposed. They are not:

- **M10's exit is clock-based.** It leaves at a fixed time regardless of where price is.
- **M12's trail is noise-based.** A 0.43-ATR trail is hit by ordinary intraday range, so it exits on
  noise rather than on a genuine reversal.

**So the synthesis is: cut winners on the clock, not on noise.** Keep `max_hold_h = 48` (M10) *and*
widen the trail so it survives a normal day's range (M12). The two findings are complementary, and
together they explain their CASHCAT replay: the 1-em trail cut the runner at ~31h — **before** the 48h
clock would have — because 0.29 ATR is inside CASHCAT's noise.

**Their CASHCAT observation was right, for the right reason, and now has cross-sectional support
instead of resting on one outcome-selected trade.**

## 5. Recommendation — REWRITTEN after the correction above

**Nothing to change live. The bot already scales its trail to ATR, which is what this study concludes a
trail should do.** The original "change the trail" recommendation was void the moment I read
`position_manager.py`.

What the study actually supports:

1. **The bot's ATR-scaling design is validated, not indicted.** Trails priced in exp_move units get
   tighter in ATR terms exactly where volatility is highest (corr +0.766), and that is the regime where
   the measured penalty is worst. Scaling to ATR removes that coupling by construction.
2. **I cannot speak to the live multiplier.** Live is 1.2–2.25 ATR; my grid stopped at 1.00. The trend
   was still improving at my ceiling, so the live width is plausibly fine or better — **but that is an
   extrapolation, not a measurement.**
3. **The one place the 1-em trail still matters is MINE:** `PREREG_PARTIAL_EXIT` arm B is sealed to test
   `partial_1R_har` with a 1-em trail. Amended — see that document.
4. **Do not read any of this as a proven edge.** No wide arm is significantly positive. The durable
   content is the *geometry*: a trail at ~0.4 ATR is inside the noise, and width matters far more than
   M1's "trail flavour is worth <0.7 bps" suggested — M1 varied the flavour at roughly fixed width,
   this varied the width.

## Limits
- Random-time both-sided entries; direction is null by construction. Trail **geometry** only.
- Every arm exits at the trail level (optimistic). This flatters tight trails most, so the incumbent's
  loss is if anything understated.
- ATR60 is computed on the **latest** 60 daily bars and applied across the whole sample, so the trail
  width is not point-in-time. A walk-forward ATR would be the next refinement and could shrink the
  effect.
- 72h horizon, one venue. Stop fixed at 1.65 × em in all arms by design.
- Control subtracted per arm; two trail widths do not price equally under no edge.
