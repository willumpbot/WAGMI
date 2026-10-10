# Mission 10 — two of the four size flags are real. Keep `volume_surge` and `funding_hot`; merge `vol_expanding` into the expected move.

_2026-10-10. 19,853 coin-days, 17 clean perps, 2023-01-01 → 2026-10-06, funding on 77% of rows.
Script: `size_flags.py`. Data: `size_flags.json`. Answering `SERVER_REPLY.md` mission 10._

**This is the project's first clean positive finding. It has not been red-teamed, and my positives
have a poor record — treat it as provisional until it has been.**

---

## 🔴 The answer

| flag | fired on | bigger next-day move | week t | placebo size | verdict |
|---|---|---|---|---|---|
| **`volume_surge`** | 5.5% | **+12.5%** | **2.07** | 0.045 ✓ | **real sizing input — keep** |
| **`funding_hot`** | 20.8% | **+7.7%** | **3.28** | 0.030 ✓ | **real sizing input — keep** |
| `vol_expanding` | 12.8% | +1.2% | 0.24 | 0.030 ✓ | **redundant — merge into the expected move** |
| `funding_cold` | 13.4% | −5.5% | −1.16 | 0.030 ✓ | no measurable effect |

"Bigger move" means **beyond what the HAR forecast already predicts**, comparing flagged against
unflagged coins **in the same date and the same expected-move quintile** — both controls at once,
which is the lesson Mission 3 cost.

---

## Why I believe this one

### The placebo is calibrated, so a null would have shown

Permuting each flag within its date × quintile cell and injecting known effects:

| flag | size (δ=0) | power at +0.05 | at +0.10 | at +0.20 |
|---|---|---|---|---|
| vol_expanding | **0.030** | 0.155 | 0.630 | 0.990 |
| volume_surge | **0.045** | 0.170 | 0.380 | 0.925 |
| funding_hot | **0.030** | 0.620 | 0.980 | 1.000 |
| funding_cold | **0.030** | 0.225 | 0.720 | 1.000 |

All four sizes land near the nominal 0.05. **This test can fail, and for two flags it did.** That is
the first time in this project a placebo has come back properly calibrated on the first attempt.

### Neither positive is tail-driven

| flag | mean | median | weeks positive | drop best week | drop worst week | biggest week's share of \|total\| |
|---|---|---|---|---|---|---|
| volume_surge | +0.1182 | **+0.1128** | 58% of 160 | +0.1039 | +0.1402 | **4.1%** |
| funding_hot | +0.0740 | **+0.0607** | 59% of 145 | +0.0679 | +0.0785 | **3.1%** |
| vol_expanding | +0.0114 | **−0.0178** | 49% of 164 | — | — | 3.5% |
| funding_cold | −0.0562 | −0.0133 | 48% of 143 | — | — | 5.7% |

Mean ≈ median, no single week carries more than 4%, and leave-one-week-out moves nothing. Contrast
`vol_expanding`, whose mean is positive while its **median is negative** and weeks are a 49% coin
flip — correctly called null.

### There is a mechanism, and it predicts which flags fail

**`vol_expanding` is `rv5 > 1.4 × rv22` — and `rv5` and `rv22` are two of the three HAR inputs.**
It is built from the forecast's own ingredients, so once you control for the forecast it *must* add
nothing. It adds +1.2%.

**Volume and funding appear nowhere in the HAR features** — `rv1`, `rv5`, `rv22` are all
return-based. They are positioning and turnover, information the forecast structurally cannot have.
They add +12.5% and +7.7%.

That the redundant flag fails and the outside-information flags succeed is the strongest internal
check available, and it was not designed in.

---

## Trader rules — one number each

1. **A volume surge means a bigger day than the forecast says — by about an eighth.** `volume_surge`
   days move **+12.5%** more than same-forecast coins on the same day. Size down.
2. **Crowded longs mean a bigger day too, by about a thirteenth.** `funding_hot` adds **+7.7%**.
3. **"Moves getting bigger" tells you nothing the expected-move number doesn't already say** — +1.2%,
   because it is built out of the forecast's own inputs.

## What to change on screen
- **`volume_surge` and `funding_hot`: promote from `context` to a sizing input** with the figures
  above. These are the first two flags in the project with a defensible number attached.
- **`vol_expanding`: demote or fold into the expected-move column.** It is not wrong, it is
  redundant — it re-displays the forecast. Its current caption cites the volatility walk-forward,
  which is sound, but that supports the *forecast*, not the flag.
- **`funding_cold`: leave as context.** The point estimate is *negative* (−5.5%, smaller moves) and
  not significant; do not invert it on that basis.

## Limits
- **17 clean perps, not top-60.** `_spot`/`_wspot` and any series above 2% stale bars were dropped —
  the filter bug that invalidated Mission 1. Coins outside my `history/` set are unmeasured.
- **Funding on 77% of rows.** `funding_hot` is a cross-sectional top-quintile flag computed only on
  dates with ≥5 funding observations, so its sample is the thinnest of the four.
- Daily closes; `|next-day return|` only. Says nothing about multi-day move size or about direction —
  these are unsigned flags and this is an unsigned test.
- The two surviving effects are **modest**: 58–59% of weeks positive. Real, but not large.
- **Not red-teamed.** Given this project's record with positive findings, that is the next step and
  this document should not drive a screen change until it is done.
