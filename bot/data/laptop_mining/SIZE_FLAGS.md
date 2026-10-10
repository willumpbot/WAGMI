> # ⚠️ SPLIT VERDICT (red team `w8ieptgg3`, high confidence)
>
> **`funding_hot` SURVIVES — the first finding in this project to withstand a dedicated adversarial
> review. `volume_surge` must be PULLED from the terminal. Argument (c) is refuted and should be
> deleted.**
>
> ### `funding_hot`: keep it
> Clean on every control three reviewers threw at it — same-day |return|, signed return, both
> together, rv1 decile dummies, **all three HAR inputs explicitly** (+0.0548, t 2.76), coin-demeaning
> (+0.0682, t 3.06), funding-present rows only (+0.0692, t 2.98), and dropping the thin high-funding
> coins HYPE/PUMP/VVV (+0.0723, t 2.95). Placebo size **0.0235** against the correct nominal 0.025,
> empirical p **0.0005**, leave-one-week-out t never below **3.10**. It is not a momentum proxy, not a
> coin-identity proxy, not a repackaged rv1.
>
> ### `volume_surge`: pull it — it fails its own threshold
> My decision rule `(m - 1.96*se) > 0` is **one-sided at 2.5%**, and I benchmarked the placebo sizes
> against **0.05** — the wrong number. Re-run with 2,000 permutations instead of 200: measured size
> **0.0345**, empirical 97.5th-percentile t **2.10** against an observed **2.07**. One-sided
> p = **0.0265 > 0.025. It fails.** Three further strikes: leave-one-week-out t ranges 1.87–2.64 and
> dropping any one of 11 of its 160 weeks puts it under 1.96; it is insignificant in the first half of
> the sample (+7.1%, t 0.82) against the second (+19.3%, t 2.29); and **9.5% of its firings are
> zero-volume data artefacts.** It may well be directionally real (row-weighted t 3.17) — it is not
> established, and the terminal was relabelled "tested" on it.
>
> ### Argument (c) is refuted, and it was the thing that made this feel safe
> I claimed `vol_expanding` is null *because* `rv5`/`rv22` are HAR inputs, so controlling for the
> forecast "must" absorb it — and called that "the strongest internal check available, and it was not
> designed in." It is a coincidence. Flags built from the same inputs reach larger, more significant
> effects. On my own week-matched estimator:
>
> | flag | built from | fired | effect | week t |
> |---|---|---|---|---|
> | `vol_expanding` (`rv5 > 1.4·rv22`) | HAR inputs | 12.8% | +0.0114 | 0.24 |
> | `rv5 > 1.6·rv22` | **same two inputs** | 5.6% | −0.1100 | −1.77 |
> | **`rv22 > within-date median`** | **one pure HAR input** | 48.0% | **+0.1003** | **3.55** |
> | `funding_hot` (reference) | funding | 20.8% | +0.0740 | 3.28 |
>
> **A flag made of nothing but one of the forecast's own three inputs beats the finding.** The reason
> is arithmetic: `em` compresses three inputs into one scalar, so conditioning on date × em-quintile
> leaves ~34% of log(rv5/rv22) and ~40% of log(rv1) variance free to vary. **A forecast cannot absorb
> its own inputs when it compresses them.** And `vol_expanding` is not even null — under row-weighted
> within-cell regression it is **−8.1%, t −2.37**, significant on the *opposite* side to my +1.2%.
>
> ### What reproduced perfectly
> Every headline number, the size/power table, the whole tail-robustness table, to four decimals on an
> independently rebuilt panel. The universe filter is correct (all 24 drops name-based; in-window stale
> bars 2 of 19,853). No lookahead. The MDE table is a real simulation, not a restated CI bound. The
> placebo is a genuine within-cell permutation that can and did fail. **The arithmetic was sound; the
> inference on top of it was half wrong.**

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
