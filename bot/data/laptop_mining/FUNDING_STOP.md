> # RESOLVED 2026-10-11 — the live flag now matches a definition I measured. Aligned figure: **+2.68 pp, week t 3.04**.
>
> **Sequence:** `scanner.py` landed → the live flag was top **decile** + an absolute floor, not the top
> quintile this study used → **downgraded** (the audit table in `FUNDING_STOP_AUDIT.md` shows t spanning
> 1.21–3.31 across variants) → the server moved the flag to the tested definition → **then found my
> recommendation had a flaw**: Hyperliquid parks most coins at a default funding rate, so `>= quantile(0.80)`
> flagged ~85% of the live cross-section. **My own panel had the same tie mass and I had not checked:**
> **18.64%** of my funding values sit exactly at the default. The server's fix is `>` rather than `>=`.
>
> **The finding survives the alignment:**
>
> | definition | fires | effect | week t |
> |---|---|---|---|
> | `>=` 80th pct — as published below | 26.33% | +2.64 pp | 3.31 |
> | **`>` 80th pct — LIVE now** | **18.92%** | **+2.68 pp** | **3.04** |
> | `>` plus a default-rate floor | 12.83% | +2.47 pp | 2.17 |
>
> **The effect is not driven by the tied rows** (+2.64 → +2.68 when they are removed), and the terminal's
> `+2 points` wording is conservative against it. **Read the figures below as the `>=` variant;** the
> live-aligned numbers are the middle row. The sensitivity caveat stands: this is one point in a range,
> not a robust constant.
>
> **Also do not re-add an absolute floor** — it costs fire rate and significance for no gain.
>
> `scanner.py` finally landed in the export and **the live `funding_hot` is top DECILE plus an absolute
> funding floor** (`scanner.py:159-163`). **This study used top QUINTILE with no floor** — the definition
> quoted in a docstring, which was all anyone had seen. The live flag fires on **5.14%** of coin-days;
> this one fires on **26.33%**.
>
> **The significance does not survive the narrowing:**
>
> | variant | n | effect | week t |
> |---|---|---|---|
> | **as published here** | 4,122 | **+2.64 pp** | **3.31** |
> | index-based top 20% | 3,202 | +1.87 | 2.08 |
> | top 10%, no floor | 1,374 | +1.48 | 1.21 |
> | **the LIVE flag** | 804 | +1.87 | **1.28** |
>
> **The sign is robust across all variants (+1.48 to +2.64 pp). The significance is not** — t spans
> 1.21–3.31, and even two different "top 20%" implementations disagree (pandas `quantile` interpolates;
> indexing a sorted list does not). **The figure below is the most favourable of the set**, which I did
> not know when I published it.
>
> **The live flag is not refuted — it is underpowered** (804 rows, se ~2.3× larger). "Untested at that
> definition" is the honest label.
>
> **Recommended fix: change the flag to the tested definition**, not soften the text — the quintile
> version has 4,122 rows, a calibrated placebo and 17/17 leave-one-out survivals behind it. If the flag
> stays strict, the terminal must drop the number and the "survived red team" claim.

# Funding-conditional stops: the effect is **real** and survives everything I threw at it. The lever is **2.9%** — decide if that is worth shipping.

_2026-10-11. `funding_stop.py`. 15,653 coin-days, 17 perps, **1,010 distinct days**, 2024-01-01 →
2026-10-06. Server-approved study. Placebo calibrated. Survives all 17 leave-one-coin-out tests._

---

## 🔴 The answer

**`funding_hot` days hit a 1.65-expected-move stop more often, and the result is solid:**

| | value |
|---|---|
| baseline stop-exceedance (unflagged) | **21.72%** |
| matched within-cell difference | **+2.64 pp** (so ~24.4% on hot days) |
| relative increase | **+12.2%** |
| week-clustered t | **+3.31** (145 weeks) |
| pooled over 2,269 cells | **+2.74 pp** — agrees with the equal-weighted figure |
| placebo size | **0.058** against a nominal 0.05 — **calibrated** |
| 80%-power MDE | **~0.01** in exceedance probability — observed effect is 2.6× that |
| leave-one-coin-out | **survives all 17**, weakest t = 2.55 (drop WLD) |

**And the decision number: a 2.9% wider stop on `funding_hot` days restores the baseline survival
rate.** Solved empirically — K\* = 1.698 against the standard 1.65.

## Why this is the first thing here that is both real and a lever

Everything that has survived review in this project so far has been a **fact**: funding is persistent,
funding-crowded days run bigger, don't tighten the stop. None of them told you what to *change*.

This one does, because it is measured on the axis the live code already uses — **stop-exceedance** —
rather than on move magnitude. It inherits the matched design that survived the red team: compared
**within the same date AND the same expected-move quintile**, which is the control mission 3 proved you
need both halves of.

## ⚠️ But the lever is small, and I am not going to dress it up

**2.9% wider.** On a stop at 1.78% of entry that is **1.83%** — a five-basis-point change. That is
plausibly inside execution noise, and it is the server's and owner's call whether it is worth the
config change and the added conditional complexity.

**What is clearly worth knowing regardless:** on crowded-funding days your stop is hit **12% more
often in relative terms**. If a 2.9% stop change is not worth making, the same information argues for
**taking slightly less size** on those days instead — same survival logic, no change to the stop
geometry that has already been validated.

## 🔧 Correcting myself: the naive translation would have been wrong by 2.6×

My own proposal said the stop should need widening by the **+7.7%** that `funding_hot` moves run bigger.
**It needs 2.9%.** My script's consistency check printed "the two agree" — that check used an arbitrary
±5 tolerance and barely passed at 4.8. **It does not agree, and I am flagging it rather than keeping a
convenient pass.**

The reason is substantive and worth carrying: **exceedance is a tail property, not a mean property.**
A 7.7% lift in the average move does not scale the distribution's tail beyond 1.65 em by 7.7%.
Translating a magnitude finding into a stop change by assuming linearity **over-corrects by 2.6× here**
— which would have meant widening stops nearly three times more than the data supports, and the
project's other surviving finding says stop distance is already right.

**General rule from this:** never convert a mean-level effect into a threshold-level action
analytically. Solve for the threshold empirically, as done here.

## Trader rules — one number each
1. **Crowded-funding days hit your stop 12% more often** (21.7% → 24.4%), matched for date and
   forecast, t = 3.31, placebo calibrated at 0.058.
2. **The fix is 2.9% wider — not 7.7%.** K\* = 1.698. Or take ~proportionally less size instead.
3. **It is real but small.** Survives all 17 leave-one-coin-out tests, and is still only five basis
   points on a 1.78% stop.

## Limits
- **1,010 days, 17 perps, but effective n tracks days** — the M10 audit put cross-coin funding
  correlation at **ρ = 0.33**. Week-clustering handles this (resampling a week resamples all its
  coins), which is why the reported t is 3.31 rather than the much larger naive figure.
- **`funding_hot` fires on 26.3% of rows**, so this applies to roughly a quarter of days.
- The panel is pinned by assertion to **17 perps** to stay comparable with `size_flags.py`; if the
  universe changes the script fails rather than silently drifting.
- **The outcome is next-day close-to-close |move| > K × em**, not an intraday path. A real stop can be
  hit intraday by a move that closes back inside — so this **understates** true exceedance. The
  comparison between arms is unaffected, but the absolute rates are a floor, not the truth.
- `em` uses the same HAR coefficients as `size_flags.py`. If the live forecast differs, K\* shifts.
- **Not red-teamed.** Given this project's record, treat the 2.9% as the estimate and the direction as
  the finding.
