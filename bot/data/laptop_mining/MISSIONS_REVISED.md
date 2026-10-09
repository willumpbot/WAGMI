# Missions 1–4, revised after red team `wkqz8m3br`. Three of four recommendations change.

_2026-10-09. 8 reviewers + synthesiser, 1.01M tokens. Every claim below re-derived by me before
acceptance. **This supersedes `SCANNER_FLAGS.md`, `SOL_50D_SHORT.md`, `CONSENSUS_SIZE.md` and the Q1
half of `PLANS_AUDIT.md`.**_

---

## The revised table

| mission | what I told you | **what to actually do** |
|---|---|---|
| **1** scanner flags | demote both, both null | **demote both — but `on_20d_low` is UNMEASURABLE, not null.** Label it "untested" |
| **2** 50d / SMA-vs-EMA | *"a bug — switch the scanner to the simple average"* | **RETRACTED. Don't change the code.** The two levels are not statistically distinguishable (z = −1.90) and the SMA's own effect decayed from −9.4 to −2.1 points |
| **3** consensus caption | remove it, the effect is +0.9% | **Don't remove it on my evidence — my test had no power.** The effect is **+4.0%, t = 0.97**: small, not establishable, not zero |
| **4** plan grader | don't build 1m; fix the fill candle | **Fix the fill candle — confirmed and go further.** But *"don't build 1m"* is **withdrawn**: I measured it on the wrong geometry |

**One recommendation survives intact: fix the fill candle.** Everything else needs softening.

---

## Mission 1 — see `SCANNER_FLAGS_V2.md`

Three fatal defects, all mine: **7 of my "24 perps" were spot series with up to 70.5% stale bars**
(63% of `on_20d_low` firings came from them); my **power table was an identity** (`DETECTED ⟺ delta >
−ci_low`, in the very script that boasted of avoiding `geometry_v3`'s version); and the
**"−0.180% = exactly the fee" headline was forced by construction**.

Rebuilt on 17 clean perps. `ma50_pullback` is a **genuine** null — random dates beat it (p = 0.815),
size correctly calibrated at 0.058, **98% power at 0.5%/trade**. `on_20d_low` has only 487 clean
firings and my test's **size is 0.000** — it cannot reject anything, so "no edge" is unsupported.

---

## Mission 2 — I retract the bug claim

`levels.py:78` really does use `c.rolling(50).mean()` (simple) while `scanner.py` uses `_ema(c,50)`.
That part is a fact. **But "the EMA is broken and the SMA works" does not survive testing:**

| era | SMA vs null | EMA vs null | difference | se | **z** |
|---|---|---|---|---|---|
| 2020–2026 | −5.3 | −0.5 | −4.8 pts | 2.5 | **−1.90** |
| pre-2024 | **−9.4** | −2.8 | −6.6 pts | 3.7 | −1.81 |
| **2024 onward** | **−2.1** | +1.4 | −3.5 pts | 3.4 | −1.03 |

**Two things kill the recommendation:**
1. **The SMA/EMA gap never reaches significance in any era** — closest is z = −1.90, just under 1.96.
   I presented a difference-of-differences as established without ever testing the difference.
2. **The SMA's own support effect has decayed**: −9.4 points pre-2024, **−2.1 points since** (CI
   [30.9, 40.2] against a 37.7 null — covers it). So switching the scanner to the SMA would install
   a level whose effect is mostly gone.

**What stands:** the *documentation* mismatch is real and worth fixing for accuracy — `LEVELS.md`'s
"the 50-day average holds from above more than chance" was measured on the **simple** average, so the
on-screen citation should say which, or stop citing it. **What falls:** any code change.

**On the owner's setup:** "no edge" at n=134 was also a no-power claim. The honest statement is
*the setup is untested at the sample size available*, plus the structural point that still holds —
he is shorting a level that historically held, while conditioning on an uptrend that makes support
*more* likely to hold. And **"price does neither 37% of the time"** survives everything; it remains
the most useful number in that mission.

---

## Mission 3 — my null had no power. The caption overstates, but not by as much as I said.

The reviewers caught this exactly, and my own power curve confirms their number:

| injected effect | matched-cell week t | result |
|---|---|---|
| 0% | 0.17 | missed *(reproduces my published +0.0088 / t 0.17)* |
| **+5%** | **1.09** | **missed** ← the reviewers' figure, reproduced |
| +10% | 1.97 | detected |
| +20% | 3.62 | detected |

**My "decisive test" had an MDE of ~+10% against a true effect of ~+4%.** It could never have found
it. I threw away 94% of the data — 1,699 matched cells out of 29,402 rows — to get a clean control,
and bought a test that couldn't fail.

The powered version (date × em-quintile **fixed effects** on all 15,961 usable rows, week-clustered):

```
effect  +0.0393 log  =  +4.0%     se 0.0403   t 0.97   CI95 [-0.0460, +0.1134]
```

**Not significant — but the point estimate is +4.0%, not +0.9%.** The reviewers reported +4.7% with
t = 2.29; the point estimate agrees, the t does not survive week clustering, which is the standard
I've enforced all day.

**So the revised recommendation:** don't remove the caption on the grounds that the effect is zero —
**I can't establish that.** But the caption's implied effect is **+18% relative** (+0.81pp on a 4.47%
base) and what survives controls is **+4.0%**, so it **overstates by roughly 4.5×**. Either restate
the numbers, or keep the readout and drop the causal claim. Do not cite my +0.9%.

---

## Mission 4 — the fill-candle fix is confirmed. "Don't build 1m" is withdrawn.

**Confirmed and strengthened:** the fill candle really is tested on its own pre-fill range. The
reviewers add a refinement I missed — **the fix should be adverse-side-only, not a blanket skip.**
Of the 10,748 contaminated fill candles, **99.7% have the candle open on the far side of the limit**
(price descended into a long's entry). In that geometry the candle **low** can only be reached at or
after the first touch of the limit, so **stop hits are genuine post-fill events**, while the **high**
is reached on the approach, so **target hits are spurious**. A blanket skip discards real stop
information. Suppress only the favourable side on the fill candle.

**Withdrawn:** my 0.115% tie-rule figure was measured on **market fills at random bar closes**, which
never examines a limit fill candle at all. On the script's own limit geometry the tie rule fires on
**0.65%** of plans and **4.73%** at 0.5% stops. Still small, but an order of magnitude more than I
reported, and concentrated exactly where the fill-candle bug also lives. **1m resolution is a
judgement call, not a settled "no".**

**Also honest:** the 9.62% headline rests on an unanchored assumption — a limit entry 0.5
stop-distances from price. Contamination swings **4.9%–28.2%** across 0.1×–2.0× offsets.
`owner_plans.jsonl` does not exist on this machine, so **zero real plans were examined by anyone.**
Send me the real plans and I'll anchor it.

---

## One dispute resolved in my favour
Three reviewers concluded `tools/hivemind/scanner.py` "does not exist" and that my quoted definitions
were unauditable. It exists on `origin/desktop-overdrive-2026-05-30` — they searched only the
filesystem and HEAD. The synthesiser confirmed `_ema` at :48, `e50` at :79, `d50` at :85 and the flag
conditions at :102–105, exactly as I cited. **My citation was accurate.** Their arithmetic criticisms
stand regardless.

Still genuinely unverifiable from here: **whether the live scanner passes stage-2 arguments to
`volforecast.forecast()`**, which would change `em` far more than anything discussed above. Please
confirm it calls `forecast(c)` with one argument.

---

## The pattern, for the fifth time

| mission | the test that could not fail |
|---|---|
| 1 | a "power" table that was the CI bound restated; a zero-arm identical to the null verdict |
| 2 | a difference-of-differences asserted without testing the difference |
| 3 | a control so aggressive it discarded 94% of the data and all of the power |
| 4 | a rate measured on a geometry the question doesn't apply to |

**Three of these are a new variant of the same error: I kept making controls stricter to be rigorous,
and strictness destroyed power.** A null is only evidence of absence if you state what it could have
detected — and that figure has to come from a placebo that resamples, not from arithmetic on the
confidence interval.

Adding to the standing rules: **report size and power for every null, from a placebo that can fail —
and if size is not near 5%, the design is void and the result is "unmeasurable", not "nothing".**
