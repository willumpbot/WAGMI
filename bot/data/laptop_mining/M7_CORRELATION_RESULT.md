# M7 — **two same-side positions are never two independent bets: they stop together 64% more often than independence implies, in every regime.** The correlation-spike detector adds nothing you can rely on.

_2026-10-13. `m7_correlation.py`. **EXPLORATORY**, magnitude only, no card above HYPOTHESIS, no live
change._

**Source snapshot: `candles_1h` max_t `1791928800000`, rows `885,145`.** That stamp exists because of
§5 — the panel is live and moved five times during this analysis.

**The measured quantity is the clustering multiplier**, not the joint stop rate:

```
lambda = P(both stop) / (P(A stops) x P(B stops))      marginals estimated WITHIN the same regime
```

A raw joint probability rises whenever volatility rises, for both legs, **with no correlation
needed at all**. Estimating the marginals *inside* the regime is what stops a volatility effect from
being read as a correlation effect — which is the whole trap in this question.

---

## 1. The finding, and it is unconditional

| | value |
|---|---|
| **λ, all regimes, equal-weighted by day** | **1.637** |
| 95% CI | **[1.538, 1.737]** |
| P(both stop within 24h) | **0.0779** |
| independence benchmark P(A)×P(B) | 0.0366 |
| days / sampled pair-entries | 180 / 50,889 |

**Two same-side positions stop together 64% more often than their individual stop rates imply.** So
the "both legs lose today" scenario — a full 1% equity hit at 0.5% risk each — **arrives roughly twice
as often as an independence calculation says it should.**

**This λ came out at 1.637 in all five runs**, across five different snapshots of a moving panel. It is
the most stable number I have produced today.

## 2. The spike conditioning is BORDERLINE, and I am not carding it

| | λ (eq-day) | |
|---|---|---|
| spike (top 20% correlation) | **1.865** | CI [1.57, 2.21] |
| calm (bottom 80%) | 1.535 | CI [1.44, 1.62] |
| | **+21.5%** | |
| **placebo null (40 shifts)** | **mean 1.555, sd 0.148, range [1.263, 1.819]** | |
| **permutation p** | **0.024** | |

**p = 0.024 clears .05 on this snapshot. I am still not carding it, for a reason the snapshot itself
cannot show:** the five runs gave spike λ of **1.726 / 1.771 / 1.846 / 1.865 / 1.907**, and **the lower
two sit inside this null distribution.** The spike estimate rests on ~52 days; the unconditional one
rests on 180. **An effect that moves in and out of significance as the panel grows by 0.01% is at the
edge of detectability, not established.**

Held-out: `NEW`-pair spike λ **1.825 [1.576, 2.107]**, consistent with the pooled spike figure.
**The ORIG17-pair cell is unusable by construction** — with 17 of 176 coins, both legs land in ORIG17
in only `(17/176)² ≈ 0.93%` of pairs, giving 103 observations. That is a design limit, not a result.

## 3. 🔴 My own verdict logic was wrong, and it flipped the answer for no reason

The first version of the verdict asked *"does the spike CI contain the placebo **mean**?"*

- With a **single-draw** placebo, that mean was 1.654 → printed **"NOT established."**
- With the **40-draw** null, the mean fell to 1.555 → **the same data** printed **"survives."**

**Excluding a null's mean is not evidence.** The question is whether the observed value falls outside
the null *distribution*, which is a permutation p-value — and that is what the draws were collected
for. Replaced. **A verdict that moves because the null got better estimated, rather than because the
evidence changed, is a broken verdict**, and it is the same family as every other instrument bug today.

**And one draw is not a placebo.** Across runs a single shift gave 1.512 / 1.647 / 1.654 / 1.773 — a
spread as wide as the effect under test, so the verdict could have been decided by which offset was
drawn. The null now uses 40 draws and **its spread is reported, not hidden.**

## 4. The sizing rule: there isn't one needed yet, and that is the honest answer

**Concurrency is not the binding constraint.** M9 established that at 0.5% risk a $5,000 account can
already carry **~10 concurrent positions** on margin, while the bot runs **one or two**.

**So the output is the number, not a rule.** What λ = 1.64 says, precisely:

- **Correlation does not change expected P&L.** Expectation is linear — two positions have twice the
  expected return and twice the expected loss whatever the correlation.
- **It changes the drawdown clustering**, and only that. Two positions do not halve your bad days;
  they bunch them.

**That is the same shape as M9 (leverage cannot move P&L) and M4 (the drawdown flips with the
denominator, expectancy does not move): across four studies, the dials in this family move variance and
tail timing, never expectancy.** Worth saying once as a conclusion rather than four times as surprises.

**If concurrency ever does become binding**, the rule follows from λ directly: treat two same-side
positions as carrying **~1.6× the simultaneous-stop risk** of two independent ones, and size the pair
on that, not on 2 × 0.5%.

## 5. 🔴 `panels.sqlite` is LIVE, so "run once" was not a verifiable claim

**Discovered mid-analysis:** two runs of this file with the same fixed seed returned different samples.
Cause: the desktop exports into `panels.sqlite` **hourly**, so `candles_1h` grew **884,982 → 885,145**
rows across five runs. More rows move `n`, which moves the range the entry indices are drawn from, so
**the sample changes despite the seed.**

**A re-run of a live panel is not a replication.** Every result now carries a `source_snapshot`
(`MAX(t)` and row count) in its JSON. **This should be retrofitted to M4/M5/M6, whose numbers are tied
to snapshots none of them recorded** — their results stand, but they are not exactly reproducible, and
I would rather say that than imply otherwise.

**The silver lining is real**, though: the accidental re-runs became a **stability check I had not
designed**. λ = 1.637 five times out of five is far stronger evidence than one run could ever be, and it
is precisely what exposed the spike estimate as unstable.

## Limits
- Pairs sampled at random, **same side by construction** per the mission. Nothing here says whether to
  take either trade.
- Stop = 1.65 × daily `em`, 24h hold, both-sided, random entry times. A different hold would change λ.
- The correlation index is a 48h rolling mean pairwise correlation over the 30 most-complete coins,
  applied market-wide; a pair-specific correlation would be a different (and more favourable) test.
- λ is a ratio of small probabilities; the pooled value (2.13) runs well above the equal-weighted day
  mean (1.64), so **the day-clustered figure is the one quoted throughout** and the pooled one is
  reported beside it rather than used.
- 176 coins, one venue, ~210 days.
