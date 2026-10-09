# ADX_MIN_TRENDING — unmeasurable with 14 weeks of signals. Leave it at 10 and close the item.

_2026-10-09. 15,663 signals with ADX + outcome, 14 ISO weeks, 2026-02-11 → 06-05.
Script: `adx_gate.py`. Data: `adx_gate.json`. The last live, never-examined knob from
`CONFIG_AUDIT.md`._

---

## 🔴 Answer: no recommendation is possible, and that closes the item.

The test **declared its own design void before producing a verdict** — placebo size 0.000 against a
nominal 0.05, and the 80%-power MDE is not reached even at **0.40R**. Fourteen weeks of signals
cannot resolve an ADX gate effect of any plausible size.

**So: leave `ADX_MIN_TRENDING` at 10.0, and stop carrying the July swarm's ">60" as a pending
action.** Not because raising it is wrong — because nothing here can tell you either way, and
**gating at 60 would discard 92.5% of signal flow on an unmeasurable hypothesis.**

This is the first finding today where the power check caught the problem *before* publication
instead of after.

---

## Why the item existed

| source | says | direction |
|---|---|---|
| `trading_config.py:263` comment | lowered 15 → 10 because *"crypto ranges with ADX 10–15 very frequently"* and *"ADX 15 was blocking too many"* | **lower it** |
| July swarm | gate >60 | **raise it 6×** |

Two rationales pointing opposite ways, never reconciled. Unlike `ENSEMBLE_CONFIDENCE_FLOOR`, this one
really is live — `bot/strategies/regime_trend.py:271`, `confidence_scorer.py:556`,
`multi_tier_quality.py:226`.

ADX replicated from the bot's own `bot/core/quant_regime.py:62`, which uses **EMA** smoothing of
+DM/−DM/TR (not Wilder's), period 14, on **1h** candles. Matching the bot matters more than matching
the textbook.

## What each gate would cost you

| gate | signals kept |
|---|---|
| ADX ≥ 10 *(current)* | ~100% |
| ADX ≥ 20 | 87.6% |
| ADX ≥ 25 | 77.7% |
| ADX ≥ 40 | 38.3% |
| **ADX ≥ 60** *(swarm)* | **7.5%** |

## The power check — run first, and it failed

Lag placebo: shift each coin's signal times within that coin, preserving count and clustering, so
any real ADX↔outcome relationship is destroyed while the data structure survives.

| injected effect | detection rate |
|---|---|
| **0.00R** | **0.000** ← size, wanted ~0.05 |
| 0.05R | 0.007 |
| 0.10R | 0.007 |
| 0.20R | 0.113 |
| 0.40R | 0.440 |

**Size 0.000 means the criterion never fires, even when it should 5% of the time.** And at 0.40R —
larger than the entire geometry surface spanned from tightest to widest stop — detection is still
only 44%. With 14 weekly blocks and buckets as small as 190 signals, there is no inference to be had.

## The numbers, as description only

Reported because they're informative about the *bot*, not about the gate:

| ADX bucket | n | raw mean R | **week mean** | week se | week t |
|---|---|---|---|---|---|
| 10–15 | 190 | −0.4201 | **−0.6196** | 0.2987 | −2.07 |
| 15–20 | 1,752 | −0.6880 | **+0.1506** | 0.2973 | 0.51 |
| 20–25 | 1,556 | −0.3816 | −0.1143 | 0.2225 | −0.51 |
| 25–40 | 6,162 | −0.3321 | −0.1995 | 0.1573 | −1.27 |
| 40+ | 6,003 | −0.2604 | **−0.3153** | 0.1373 | −2.30 |

Two things to notice, and neither supports a gate:

1. **No monotone relationship.** Week means go −0.62, +0.15, −0.11, −0.20, −0.32. The sign flips
   twice. If higher ADX meant better outcomes this column would trend.
2. **Raw and week-weighted means disagree violently.** The 15–20 bucket is **−0.6880 raw but +0.1506
   week-weighted** — a swing of 0.84R from re-weighting alone. That is the same unequal-block problem
   that inflated my geometry headline by 62%, and it is why none of these numbers can be acted on.

Every gate comparison came back `unmeasurable`: differences of +0.32R to −0.44R with standard errors
of 0.19–0.32, i.e. noise of the same magnitude as the estimates.

## The thing that *is* worth saying

**Every ADX bucket has negative mean R.** The bot's signals lose at the bot's own bracket over 48h in
this corpus regardless of trend strength — consistent with `GEOMETRY_V3`'s −0.3477R for the default
bracket. **An ADX gate rearranges which losses you take; it does not create a winner.** If the
signals are negative-expectancy, filtering them by trend strength is not the lever.

## Trader rules — one number each

1. **Leave the ADX gate at 10.** Raising it to 60 would discard **92.5%** of signals to buy an effect
   this data cannot measure at any size.
2. **Signals lose at every trend strength.** Mean R is negative in all five ADX buckets, from
   −0.26R to −0.69R.
3. **Fourteen weeks is not enough to tune a gate.** The smallest effect detectable here is above
   **0.40R** — bigger than any realistic gate effect.

## What would make this answerable
More weeks of signals, not more cleverness. At the observed per-week dispersion, resolving a 0.10R
gate effect at 80% power needs roughly **16× the weekly blocks** — about 4–5 years of signal logging
at the current rate. Alternatively, test the gate on the *bot's realised fills* once
`trade_ledger.csv` exists, where the outcome is actual P&L rather than a simulated bracket.

## Limits
- One corpus, one bracket definition (the bot's own entry/sl, tp1 where valid, else 1R), 48h horizon.
- ADX is computed on the bar **before** entry, so there is no lookahead, but the bot's live ADX may
  come from a different candle source or a partially-formed bar.
- `regime_trend` is flagged in-code as a losing strategy (−$200, 18% WR, PF 0.15) and it is one of the
  consumers of this knob. A gate study pooled across strategies may be the wrong unit entirely.
- **The design is void by its own test.** Nothing here is a finding; it is a statement that the
  question is out of reach with this sample.
