# ⚠️ WITHDRAWN — I refuted the original against a baseline I invented

_Red team `wp73ppfxp`, 2026-10-08. Verified by me before accepting._

**Do NOT swap HAR for EWMA. Keep `volforecast.py` as it is.**

> ### Precision note added 2026-10-09 — the degenerate baseline is real, but it lives elsewhere
>
> I wrote below that I "invented" the degenerate baseline. That is too strong and, more importantly,
> inaccurate. It exists in the project — in a **different artifact** than the one I attributed it to:
>
> | artifact | baseline | QLIKE | honest? |
> |---|---|---|---|
> | `volatility_forecast.json` → `y1_naive` | **"naive persistence"** | **4.1202** vs HAR 0.5126 | **no — degenerate**, and this is the y1 calibration work |
> | `walkforward_vol.json` → `naive5` | `ret.rolling(5).std()` | **0.2781** vs HAR 0.1565 | **yes** — and HAR wins 1.78× |
>
> So the correct statement is: **the "beats naive by a huge margin" problem is real for the y1
> calibration numbers, and false for the y5 walk-forward.** I found the degenerate baseline in the
> first artifact, then attributed it to the second and generalised the refutation to both. The y5
> walk-forward result stands as the original reported it.
>
> This does not revive the EWMA recommendation — that still fails for the loss-specification and
> unfair-window reasons below. **Keep HAR.** But the charge against the original is narrower than I
> stated: *y1 was never walk-forwarded, and its in-sample comparison used a degenerate baseline.*

The rest of this document overstates the case:

| my claim | the truth |
|---|---|
| "the original beat a degenerate `naive \|yesterday\|` proxy, QLIKE 4.79" | `walkforward_vol.py:50` defines **`"naive5": ret.rolling(5).std()`** and `:117` scores against it. `walkforward_vol.json` stores **HAR 0.1565 vs naive 0.2781 — a 1.78× gap, not 36×.** |
| evidence: "`grep -o y1 walkforward_vol.json` returns 0" | true, but **`grep -o y5` also returns 0** — the JSON stores no horizon label at all, so the grep proves nothing either way |
| "HAR earns nothing over EWMA" | holds **only** under QLIKE-on-level, and I capped HAR at 22 days while `ewma_pred` recursed over 120 returns. Under **MSE-on-variance at y5, HAR beats EWMA 19/22 (p = 0.0008)**; QLIKE-on-variance favours HAR at both horizons |
| — | **HAR is better on the axis the live code uses:** stop-exceedance at a nominal 5% stop is **6.30% (HAR) vs 7.25% (EWMA)**, and the swap moves over half of all coin-days into a different leverage decile |

My verdict gate also could not fire: `beats = (w == n and tmean < -1.96)` averages 22 per-fold
t-statistics, which is not a test statistic. A wild cluster bootstrap puts the true 5% critical value
at −0.34 to −0.73 — my −1.96 was **2.7–5.7× too strict.**

**What survives:** the 1-day horizon genuinely was never walk-forwarded — but the evidence is the
three `fit(tr,"y5")` call sites at lines 114/159/168, not the void grep. Everything below is kept as
the working record of a wrong analysis.

---

# Volatility, corrected — forecastable, but HAR earns nothing over an EWMA

_2026-10-08. 20,444 coin-days, 11 coins, 2020-09-19 → 2026-10-01, 22 walk-forward folds.
Supersedes `VOLATILITY.md` and `walkforward_vol.py`. Script: `volatility_v2.py`.
Data: `volatility_v2.json`. Context: `RETRACTION.md`._

---

## Headline

**Volatility really is forecastable — QLIKE 0.52 against the naive baseline's 4.79 is a nine-fold
improvement, and that is not noise. But our HAR model earns nothing over a one-parameter EWMA: it
wins 7 of 22 folds at one day and 11 of 22 at five days. The "22/22 folds" I reported was true only
against a degenerate baseline, and the one-day walk-forward had never been run at all.**

**Recommendation: replace HAR with EWMA in `volforecast.py`.** Same accuracy, one parameter instead
of four plus a smearing factor, and no stage-2 correction to maintain. This makes the live system
simpler and no worse.

---

## The full comparison

| horizon | baseline | HAR wins | HAR QLIKE | baseline QLIKE | DM t | verdict |
|---|---|---|---|---|---|---|
| y1 | naive \|yesterday\| | **22/22** | 0.5202 | **4.7945** | −3.33 | HAR clearly better |
| y1 | rolling 22d stdev | 18/22 | 0.5202 | 0.5333 | −1.80 | better, not significant |
| **y1** | **EWMA (λ fitted on train)** | **7/22** | 0.5202 | **0.5169** | +0.62 | **no better — EWMA edges it** |
| y5 | naive \|yesterday\| | **22/22** | 0.1548 | **5.6335** | −3.90 | HAR clearly better |
| y5 | rolling 22d stdev | 18/22 | 0.1548 | 0.1699 | **−2.60** | **significantly better** |
| **y5** | **EWMA** | **11/22** | 0.1548 | 0.1549 | +0.08 | **a coin flip** |

Diebold-Mariano t-statistics on the QLIKE differential, Newey-West corrected for the 5-day overlap at
y5. Negative t means HAR has the lower loss.

### Reading it
1. **The naive baseline was broken, exactly as the reviewer said.** `|yesterday's return|` is a
   single-draw proxy that is often near zero, and QLIKE diverges as the forecast approaches zero. Its
   loss of 4.79 (y1) and 5.63 (y5) is dominated by its own tail. Beating it 22/22 was unavoidable and
   meaningless.
2. **HAR does beat a plain rolling window at five days** — 18/22 folds, t = −2.60, which clears the
   5% threshold. That is a real if modest result, and it is the only one in this document.
3. **Against EWMA there is nothing.** 7/22 at y1 with EWMA's QLIKE *lower* (0.5169 vs 0.5202); 11/22
   at y5 with the two identical to four decimals. A single exponential decay parameter captures
   everything the three-term HAR specification does.

---

## The three faults, each confirmed

| fault | status |
|---|---|
| **The 1-day walk-forward never ran.** `walkforward_vol.py` lines 114/159/168 all call `fit(tr,"y5")`; the output JSON contains zero `y1`. | **Confirmed.** y1 is walk-forwarded here for the first time, and it is the horizon where HAR does *worst* against EWMA (7/22). |
| **"Beats naive" beat a degenerate baseline.** | **Confirmed.** Naive's QLIKE is 9–36× HAR's, which is a statement about naive, not about HAR. |
| **No significance test anywhere.** | **Confirmed.** Added: Diebold-Mariano with Newey-West lags. It is what turns "18/22 folds" into "t = −2.60, real" and "11/22 folds" into "t = +0.08, nothing". |

---

## What this means for the live system

`volforecast.py` currently runs HAR plus a stage-2 error correction (itself retracted in
`RETRACTION.md` for test-set leakage). The honest replacement is smaller:

```
# EWMA variance recursion on daily returns, lambda fitted on train only
v = lam * v + (1 - lam) * r_prev**2
sigma = sqrt(v)
next_day_move  = sigma * sqrt(2/pi)     # |return| has mean sigma*sqrt(2/pi)
next_5day_vol  = sigma
```

One parameter, no smearing factor, no stage-2, no coefficient file to keep in sync — and it matched
or beat HAR in 15 of 22 folds at one day. λ is selected on train by QLIKE over
{0.88, 0.90, 0.92, 0.94, 0.96, 0.97}.

**What does NOT change:** the expected-move column, the levels-in-expected-moves display, the
position calculator's use of a forecast, and `SAFE_LEVERAGE.md`'s volatility buckets. All of those
need *a* volatility forecast and will work as well or better on EWMA. The claim being retracted is
"our model is good", not "volatility is forecastable".

---

## Trader rules

1. **Expect roughly the last month's volatility, decayed toward the last week** — that is what an
   EWMA is, and nothing more elaborate beat it over six years and 22 folds.
2. **Yesterday's move alone is a terrible forecast** — its loss is **9×** worse than an EWMA's. One
   quiet day does not mean a quiet tomorrow.
3. **At five days, a 22-day window is measurably worse than a decayed one** (t = −2.60), so weight
   recent days more; at one day the two are indistinguishable.

## Limits
- QLIKE only. MSE on variance would weight the tail differently and was not run.
- λ is refitted per fold on train, so the EWMA baseline is honestly out-of-sample; HAR is too.
- 22 folds of 90 days with expanding training windows, so folds are nested and not independent. The
  DM test handles serial correlation within a fold, not dependence between them.
- This does not test the *calibration* claims from `VOLATILITY.md`, several of which the reviewer
  also found contradicted by the project's own JSON (stored top-decile ratios as low as 0.602).
  Calibration needs its own pass once the model choice is settled.
