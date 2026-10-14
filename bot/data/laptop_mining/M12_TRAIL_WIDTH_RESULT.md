# M12 — **The current 1-exp-move trail is the worst arm tested and the only one whose CI excludes zero.** Their premise holds: scaling to the coin's own ATR helps ~3× more on high-vol coins.

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
| **1.00 × em (incumbent)** | **−16.14** | **[−25.52, −6.90]** | — |
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

## 5. Recommendation

**Change the trail; it is the one thing in this family with a significantly negative cell.**

1. **Scale the trail to the coin's own ATR, not to exp_move.** `1.00 × ATR60` is the best arm and the
   only non-negative one; **`0.75 × ATR` is the conservative choice** (+13.87 overall, +28.37 in the
   high-vol third) if a tighter give-back is wanted.
2. **The gain is concentrated where they predicted** — if only one change is made, apply it to high-vol
   coins first.
3. **Do not read this as a proven edge.** No wide arm is significantly positive. The honest claim is
   *stop doing something measurably bad*, which is a lower bar and a sufficient one.

## Limits
- Random-time both-sided entries; direction is null by construction. Trail **geometry** only.
- Every arm exits at the trail level (optimistic). This flatters tight trails most, so the incumbent's
  loss is if anything understated.
- ATR60 is computed on the **latest** 60 daily bars and applied across the whole sample, so the trail
  width is not point-in-time. A walk-forward ATR would be the next refinement and could shrink the
  effect.
- 72h horizon, one venue. Stop fixed at 1.65 × em in all arms by design.
- Control subtracted per arm; two trail widths do not price equally under no edge.
