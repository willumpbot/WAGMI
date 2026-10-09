> # ⚠️ SUPERSEDED by `MISSIONS_REVISED.md` (red team `wkqz8m3br`)
>
> **Mission 2 v1.** The "SMA vs EMA is a bug" claim is RETRACTED -- the two levels are not statistically distinguishable in any era (best z = -1.90) and the SMA's own effect decayed from -9.4 to -2.1 points. Do not change the scanner code.
>
> Kept as the working record. **Read `MISSIONS_REVISED.md` instead.**

# Mission 2 — your SOL short into the 50-day average: the setup has no edge, and I found a bug

_2026-10-09. 418 touches, 17 HL perps, 2024-07-14 → 2026-09-17. Script: `sol_50d_short.py`.
Data: `sol_50d_short.json`. Answering `SERVER_REPLY.md` mission 2._

---

## 🔴 First, the bug — it matters more than the setup

**`levels.py:78` validated the 50-day SIMPLE average. `scanner.py` flags the 50-day EMA. They are
different levels, and only one of them works.**

```python
levels.py:78    ma50 = c.rolling(50).mean().shift(1)     # SIMPLE
scanner.py      e50  = _ema(c, 50)                       # EXPONENTIAL
```

Same 11 coins, same window, same touch definition, LEVELS.md's own null:

| level definition | n | break% | CI95 | null% | vs null |
|---|---|---|---|---|---|
| **SMA — what `levels.py` tested** | 696 | **32.3** | [28.9, 35.8] | 37.4 | **−5.1** ✓ |
| **EMA — what `scanner.py` flags** | 749 | 37.0 | [33.5, 40.4] | 37.5 | **−0.5** ✗ |

LEVELS.md reports n=701, 32.1% [28.8, 35.8], −4.4. **I reproduce it almost exactly on the SMA, so
LEVELS.md is right.** The scanner then cites it as evidence for a level it doesn't compute.

**Fix:** either switch `ma50_pullback` to the simple 50-day average, or drop the LEVELS.md citation.
This is a second, independent reason to demote the flag — and unlike Mission 1's finding, it's
repairable.

---

## Your setup: no edge, in any variant

Break = closes ≥0.5 expected moves below the level within 2 days (**the short wins**).
Reject = moves ≥1.0 em back up (**the short loses**). Null = random-date pseudo-levels, LEVELS.md's.

| condition | n | break% | CI95 | null% | vs null | reject% | **neither%** |
|---|---|---|---|---|---|---|---|
| all ma50-from-above | 418 | 36.4 | [31.8, 41.0] | 38.8 | −2.4 | 26.3 | 38.8 |
| + daily trend UP | 172 | 42.4 | [35.1, 49.8] | 39.0 | +3.4 | 22.7 | 36.6 |
| **+ trend UP & 4h down ← yours** | **134** | **41.0** | **[32.7, 49.4]** | **39.1** | **+2.0** | 23.9 | **37.3** |
| + trend UP & 4h last-6 down | 101 | 39.6 | [30.1, 49.1] | 39.3 | +0.4 | 24.8 | 36.6 |
| _(contrast)_ trend DOWN & 4h down | 69 | 43.5 | [31.8, 55.2] | 38.7 | +4.8 | 33.3 | 26.1 |

**Every confidence interval covers its null.** The 4h filter moves the break rate from +3.4 to +2.0 —
it makes the setup slightly *worse*, not better.

### What the short actually pays

| condition | n | 1d mean | 1d week mean | week t | 5d mean | 5d week mean | week t |
|---|---|---|---|---|---|---|---|
| all touches | 418 | −0.208 | −0.055 | −0.16 | −1.210 | −1.661 | −1.42 |
| + trend UP | 172 | +0.279 | +0.204 | 0.42 | −0.059 | −1.175 | −0.72 |
| **+ trend UP & 4h down** | 134 | **+0.201** | +0.114 | 0.22 | **−1.206** | −2.215 | −1.18 |
| _(contrast)_ trend DOWN & 4h down | 69 | +0.500 | −0.073 | −0.11 | −2.821 | −2.308 | −1.30 |

Net of 9 bps, signed for a short. Not one week-t clears 1.96. **The short is a coin flip at 1 day and
loses at 5 days in every variant.**

---

## Three plain answers, one number each

1. **How often does the 50-day average break when you short into it from above?**
   **41%** in your exact setup — against a random-line rate of **39%**. You are paying fees for a
   2-point edge that the confidence interval cannot distinguish from zero.
2. **What does the short return?**
   **+0.20% at 1 day, −1.21% at 5 days.** Holding it longer makes it worse, not better.
3. **The number I'd actually keep: price does neither 37% of the time.**
   It doesn't break and it doesn't reject — it just sits on the level. **Any plan phrased "it breaks
   or it bounces" is wrong more than a third of the time**, and that's the most reliable fact here.

## The structural problem with the plan

You're shorting into **the one level in the whole table that holds better than chance** (−5.1 points
on the SMA over 2020–2026), while conditioning on **daily trend up** — which is the condition that
makes support *more* likely to hold. The two halves of the plan work against each other. The contrast
row shows the sense you probably want: trend DOWN gives the highest break rate (43.5%), though its
CI is [31.8, 55.2] and n=69, so I can't call it real either.

## Limits — read these before acting
- **4h history binds the sample to 2024-07 onward.** That matters: the SMA support effect is
  concentrated *before* 2024 (pre-2024 −2.7 points, 2024-onward **+1.6**). So in the window where I
  can test your 4h condition, the underlying support effect is itself absent.
- **Pooled across 17 coins, not SOL alone.** 418 touches ÷ 17 coins ≈ 25 each, and your condition
  cuts that to roughly 8 per coin. SOL-only is far too thin to report. If the setup is SOL-specific
  rather than general, this does not test it.
- LEVELS.md:68 already flagged `ma50 from above, uptrend` as the **one unstable cell** in its
  structure table (train 29.9% / test 43.4%, "stable: no") — your condition sits exactly there.
- Daily closes for the break test, next-day open for entry. No stops, so this measures the setup, not
  a managed trade.
- **Not red-teamed.** Provisional.
