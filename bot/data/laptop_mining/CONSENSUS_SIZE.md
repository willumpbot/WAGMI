# Mission 3 — remove the "~5% day / ~3.2% day" caption. The spread is real; consensus isn't why.

_2026-10-09. 29,402 coin-days, 24 coins, 2020-09-10 → 2026-10-07, train/test split at 2025-06-01.
Script: `consensus_size.py`. Data: `consensus_size.json`. Answering `SERVER_REPLY.md` mission 3._

---

## 🔴 Answer: remove it.

You asked: *"Does it survive controlling for the coin's own HAR forecast? If not, I remove it."*

**It does not. Once you control for the forecast *and* the date, the effect is +0.9% with
t = 0.17 and a CI of [−0.095, +0.112].** Show the coin's expected move instead — it already carries
the whole thing and it's already on screen.

---

## The claim does reproduce — that's the trap

| dissent bucket | n | mean \|next-day move\| | median | mean `em` (HAR) |
|---|---|---|---|---|
| **≤1 dissent** | 5,700 | **5.28%** | 3.08% | 4.32% |
| 2 dissent | 10,676 | 4.52% | 2.57% | 3.96% |
| **≥3 dissent** | 13,026 | **4.47%** | 2.41% | 3.93% |

**Raw spread +0.81 percentage points** — that is the terminal's "~5% vs ~3.2%". It is a real pattern
in the data. The question is only *why*.

## Four tests. Three of them control the wrong thing.

| what is controlled | dissent effect | reads as |
|---|---|---|
| nothing (raw) | **+0.81 pp** | big |
| the HAR forecast only (10 em deciles) | **+17.6%**, 10/10 deciles positive, **t = 6.46** | **very convincing** |
| the date only (within-date permutation) | +0.0283 of +0.1484 → **19%** of the spread | mostly date |
| **the date AND the forecast** | **+0.9%, t = 0.17, CI [−0.095, +0.112]** | **nothing** |

### The within-decile test is the one that nearly fooled me

Low dissent produced bigger moves in **10 of 10** expected-move deciles, mean +0.1623 in logs,
**t = 6.46**. That is as persuasive as a result gets — and it is wrong, because `em` is a *per-coin*
forecast and cannot absorb *market-wide* surprise. Low-dissent coin-days cluster on volatile market
days. Controlling for the coin's forecast does not control for the day.

| em decile | mean em | low dissent | high dissent | diff (log) |
|---|---|---|---|---|
| 0 | 1.58% | −0.1408 | −0.1633 | +0.0224 |
| 3 | 3.10% | −0.4303 | −0.5413 | +0.1110 |
| 7 | 4.62% | −0.3246 | −0.6319 | +0.3073 |
| 9 | 9.12% | −0.4260 | −0.6563 | +0.2302 |

### The decisive test: same date, same em quintile

1,699 matched (date × em-quintile) cells across 1,234 dates:

- mean diff **+0.0273** log, median +0.0928, **cells positive 53.4%** (a coin flip)
- **week-clustered +0.0088, t = 0.17, CI95 [−0.0947, +0.1124]**
- in level terms: **+0.9%**

**The placebo centres on +0.0017 with CI [−0.0680, +0.0750] — so it genuinely can fail** — and
p(null ≥ real) = **0.267**.

## Why the regression looked significant, and why I don't trust it

`log|move| ~ a + b·log(em) + c·disagree` gives a significant negative `disagree` coefficient in both
halves (−0.0521 train, −0.0885 test, week-clustered CIs excluding zero). But its **`log(em)`
coefficient is +0.8430 train and +0.2068 test** — a 4× swing. When the control variable's own
coefficient is that unstable, "controlling for it" isn't working, and the leftover loads onto
whatever else is in the model. The nonparametric date × quintile matching has no such problem.

---

## Trader rules — one number each

1. **Voice agreement tells you nothing about tomorrow's move size.** Same day, same forecast:
   **+0.9%** difference between full agreement and heavy dissent.
2. **The expected-move number already contains it.** The HAR forecast explains **48%** of the raw
   spread directly, and the market-wide day explains most of the rest.
3. **Low dissent is a volatility symptom, not a signal.** `disagree` is 70.6% determined by
   vote-activity and extremity (`SQUEEZE_V2.md`), with **corr(disagree, |RSI−50|/50) = −0.802**.
   "Everyone agrees" mostly means "RSI and Bollinger are stretched", which is already in `em`.

## What to put on screen instead
The coin's own expected move, which you already compute and display. Drop the dissent caption
entirely — or if you want to keep a consensus readout, label it **"agreement (no tested effect on
move size or direction)"**, consistent with `SQUEEZE_V2.md`'s finding that no definition of dissent
adds anything to squeeze probability either.

## Limits
- 24 coins including some with short history; the HAR coefficients were fitted on 11 majors, so `em`
  is slightly out-of-domain for the newer listings. The date × quintile matching is robust to that
  (it only compares coins within the same forecast bin on the same day), but the raw bucket means are
  not.
- One split at 2025-06-01, not walk-forward. The direction of the result — a variable adding
  *nothing* — is the kind least sensitive to split choice.
- Target is |next-day return|; this says nothing about multi-day move size.
- **Not red-teamed.** Provisional, and this document already changed its own answer twice.
