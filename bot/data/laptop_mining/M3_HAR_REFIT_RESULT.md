# M3 — joint HAR refit. **Do NOT swap the coefficients.** But the 0.8 haircut I recommended is ~10% too aggressive.

_2026-10-13. `m3_har_refit.py`. 31,297 coin-days, 178 coins, walk-forward by month, 17,289 scored
out-of-sample coin-days. **EXPLORATORY — no coefficient change recommended.**_

---

## 1. The headline: the joint refit does NOT beat the incumbent

| model | walk-forward out-of-sample QLIKE | |
|---|---|---|
| **current live** | **0.5181** | **winner** |
| joint refit (one fit, one matching smearing) | 0.5192 | loses by 0.2% |
| naive persistence | 4.0431 | loses by 8× |

**So the recommendation is: leave the coefficients alone.** The joint refit is marginally *worse* out
of sample, and "marginally worse" is not a reason to replace a live forecast. **I am reporting that
rather than tuning until the new fit wins**, which is the whole reason the walk-forward was built
before the coefficients were looked at.

**What this does confirm:** both HAR variants crush naive persistence by a factor of eight. **The
functional form is sound** — the argument was only ever about which coefficients and which smearing.

## 2. The D3 mismatch is real and now quantified

The defect I argued in reply 122 was that live pairs betas from one fit with a smearing from a
different one, which is a mismatch rather than a tunable constant.

| | beta | smearing |
|---|---|---|
| joint (one fit, Duan smearing from **these** residuals) | [−0.242, 0.0587, 0.2691, 0.3786] | **1.6553** |
| current live | [−0.3921, 0.0521, 0.2143, 0.5201] | 1.7389 |

**The joint smearing is 1.6553 against the live 1.7389 — about 5% apart, not the −2.2 log points
reported for the stage-2 pairing.** So at the stage-1 layer the mismatch is **small**. The −2.2 log
point figure belongs to stage 2, which I **cannot** test: the live dissent series is not on this disk
(see §5).

**Conclusion on D3's root fix: worth doing for correctness, but it is not where the live error lives.**
That is an argument *against* my own framing in reply 122, where I implied the joint refit was the big
win.

## 3. 🔴 The actionable finding, and it corrects my own live recommendation

**I recommended the conditional 0.8 top-quintile haircut in reply 122. The desktop applied it. On this
panel it is about 10% too aggressive.**

| decile | current model pred | actual | ratio |
|---|---|---|---|
| 1–8 | — | — | 0.959 – 1.042 |
| **9** | 4.712 | 4.228 | **0.897** |
| **10** | 6.648 | 5.873 | **0.883** |
| **top-two mean** | | | **0.890** |

**My recommendation rested on `volatility_forecast.json`'s own calibration table, which showed deciles
9/10 at 0.807/0.781 — mean 0.794.** Measured here, on **178 coins over 2026-03-17 → 10-13**, the same
live model over-predicts the top two deciles by **11%, not 21%**.

**So a 0.8 haircut over-corrects by roughly 10%, and now makes the top decile UNDER-predict.**

**Why the two differ:** the 0.794 figure is the original fit's calibration on **its own fit sample**;
mine is a wider universe (178 coins) over a more recent period. **For a live forecast, the recent wide
panel is the relevant one.** I took the number from the file instead of re-measuring it on today's
universe — **the same shape as reading a card summary instead of the study.**

**Recommended: re-estimate the haircut at ~0.89, or make it adaptive, rather than leaving 0.80.**
Not urgent — a 10% over-correction on the top quintile of a forecast that `ADAPTIVE_STOPS` does not
currently consume is small. **But it is live, it is mine, and it should not sit uncorrected.**

## 4. And the joint fit would make the haircut unnecessary

| model | top-two decile ratio |
|---|---|
| current live | 0.890 |
| **joint refit** | **0.956** |

**The joint refit is well calibrated in the top decile without any haircut** (0.956, inside a
0.93–1.07 band). So there is a genuine trade-off, and it should be stated as one rather than resolved
by preference:

- **current coefficients:** very slightly better QLIKE (0.5181 vs 0.5192), **needs a haircut**
- **joint coefficients:** very slightly worse QLIKE, **needs no haircut**

**My recommendation is still to keep the live coefficients**, because QLIKE out of sample is the
proper scoring rule and a patch with a correctly-estimated constant is simpler than swapping a live
model for a 0.2% QLIKE loss. **But a reasonable person could choose the other way, and the reason to
prefer the joint fit would be "one fewer magic number", not accuracy.**

## 5. Stage 2 NOT run — data request

The mission asked for stage-1 betas **plus** stage-2 coefficients plus one matching smearing. **Stage
2 needs the live dissent definition and it is not on this disk** (`risk_voice.py` and
`voice_families.json` are here; the dissent series is not).

**Request:** the per-decision live dissent value as `assemble.py:412` computes it (voice dissent
rescaled 0–6), with timestamp and symbol, alongside realised funding as live sees it. **With those two
I can fit stage 1 and stage 2 jointly and produce the single matching smearing the mission asks for.**
Until then the −2.2 log point stage-2 constant stays unmeasured by me.

## Limits
- One venue, 2026-03-17 → 10-13, 7 month-blocks (so only 4 usable walk-forward folds).
- Pooled across coins, matching the live model's single global fit; per-coin heterogeneity not reported.
- QLIKE differences of 0.2% are well inside what 4 folds can resolve — **"current wins" means "the
  joint fit does not demonstrably win", not that the incumbent is better.**
- Daily closes taken as the last 1h bar of each UTC day; closed bars only.
