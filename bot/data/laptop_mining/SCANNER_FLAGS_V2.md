# Mission 1 v2 — still demote both, but for two *different* reasons. v1 had three fatal defects.

_2026-10-09. 19,574 coin-days, **17 clean perps**, 2023-01-01 → 2026-10-02. Script:
`scanner_flags_v2.py`. Data: `scanner_flags_v2.json`. **Supersedes `SCANNER_FLAGS.md`.**
Red team `wkqz8m3br` found the defects; all three verified by me before accepting._

---

## 🔴 Revised recommendation

| flag | v1 said | **v2 says** | on-screen label |
|---|---|---|---|
| `ma50_pullback` | null, demote | **null, demote — now with real evidence** | "no measured edge" |
| `on_20d_low` | null, demote | **UNMEASURABLE, demote** — my test cannot reject anything | **"untested"**, not "no edge" |

The action is the same; **the justification for `on_20d_low` was wrong and must not be quoted.**

---

## What was wrong with v1

### F1 — 7 of my "24 HL perps" were spot series, mostly stale

My filter was `not s.endswith("_wspot")`. That excluded the wrapped duplicates but let the
**identical** `*_spot` files through — `BERA_spot` and `BERA_wspot` are both 671 rows, 70.5% flat.

| series | stale bars (o=h=l=c) |
|---|---|
| BERA_spot | **70.5%** |
| TRUMP_spot | **68.0%** |
| MON_spot | **65.3%** |
| PUMP_spot | 40.0% |
| AZTEC_spot | 28.5% |
| every real perp | ≤0.3% |

**A stale run makes `px == min(low[-20:])` exactly, so `on_20d_low` fires every single day of it.**
Result: **63% of v1's `on_20d_low` firings came from those 7 series** (1,317 → 487 once removed). And
all 13 rows in v1's "top 1% carry 43.8% of absolute excess" were spot **denomination jumps**, not
meme explosions — `MON_spot` goes 0.000543 → 0.0069 → 0.000565 (×12.2 then ÷12.2). `TRUMP_spot` even
has 857 rows starting in 2024 at 0.000502, before the token existed.

So v1's most dramatic numbers (−8.402R at 5d, "+1008%, +1009%, +1173%") were measuring **data
corruption**. Fixed: exclude `_spot` and `_wspot`, and drop any series above 2% stale bars.

### F2 — my "power" table was an identity, in the script where I claimed to have fixed exactly that

v1 "injected" an effect by adding a scalar to every row. That shifts each week mean by `delta` and
leaves `mus.std(ddof=1)` **exactly unchanged**, so:

```
DETECTED  <=>  mean + delta - 1.96*se > 0  <=>  delta > -ci_low
```

Verified: `ma50_pullback` −ci_low = 0.0435 → "MDE 0.1"; `on_20d_low` −ci_low = 1.2700 → "MDE 2.0".
**The grid points were simply the first values above the CI bound.** Worse, the "zero-injection arm
(must NOT detect)" is the statement `ci_low < 0` — **logically identical to the null verdict it was
supposed to validate.** It could not fail. And v1's docstring claimed it "resamples genuinely"; it
touches no RNG at all.

This is the fourth instance of this project's recurring failure, and the most embarrassing: it is in
the script whose docstring boasts about avoiding `geometry_v3.py`'s version of the same error.

### F3 — the "−0.180% = exactly the fee" headline was a construction artifact

`net = x − 0.18`, and subtracting the per-date cross-sectional median forces `median(x) == 0`
identically (748 rows are exactly zero — the median coin on odd-count dates). It holds for the **full
panel** too, so it said nothing about the flags. v1 called it "the whole result in one line". It was
arithmetic.

---

## The honest result, on clean perps

### The power analysis that replaces v1's identity

Lag placebo: shift each coin's firing dates by a random offset within that coin, preserving firing
**count** and within-coin **clustering** while destroying any real timing. Then inject a known effect
and run the **full** decision criterion (null p < 0.05 **and** week CI low > 0).

| injected | `ma50_pullback` 1d | `on_20d_low` 1d |
|---|---|---|
| **0.00% (size)** | **0.058** ✓ calibrated | **0.000** ✗ **void** |
| 0.25% | 0.608 | 0.000 |
| 0.50% | **0.983** | 0.008 |
| 1.00% | 1.000 | 0.525 |
| 2.00% | 1.000 | 1.000 |

**This placebo can fail, and for `on_20d_low` it did.** A size of 0.000 means the criterion never
fires even when it should 5% of the time — so a "null" verdict from it is worth nothing.

### ma50_pullback — a genuine null

| hz | mean excess | week mean | week t | week CI95 | null mean | **null p** | win% | panel win% |
|---|---|---|---|---|---|---|---|---|
| 1d | +0.0723 | +0.1743 | +1.17 | [−0.1189, +0.4675] | +0.1838 | **0.815** | 42.5% | 43.0% |
| 5d | +0.4045 | +0.7166 | +1.92 | [−0.0158, +1.4490] | +0.9403 | **0.975** | 43.9% | 45.7% |

**Random dates in the same coin do BETTER than the flag** at both horizons (p = 0.815, 0.975). The
test has correctly calibrated size (0.058) and **98% power to detect 0.5% per trade.** It found
nothing. **This is evidence of absence.** Demote with confidence.

### on_20d_low — unmeasurable, not null

| hz | mean excess | week mean | week t | week CI95 | null mean | null p | win% | panel win% |
|---|---|---|---|---|---|---|---|---|
| 1d | −0.4190 | −0.6800 | −3.15 | [−1.1034, −0.2566] | −0.5676 | 0.201 | 42.7% | 43.1% |
| 5d | −0.7514 | −1.4500 | −2.29 | [−2.6907, −0.2093] | −1.4051 | 0.059 | 45.4% | 45.8% |

Shorting it **loses** significantly (week t = −3.15), but **random dates in the same coin lose about
as much** (−0.5676 vs −0.4190, p = 0.201) — so the loss is a property of these coins in this period,
not of the flag. And with only 487 firings over 17 coins, **my test's size is 0.000: it cannot reject
anything.**

**The honest on-screen label is "untested", not "no edge".** An edge below ~2% per trade would be
invisible here, and I cannot rule one out in either direction.

---

## Trader rules — one number each

1. **A pullback to the 50-day average is not a buy signal.** Random days in the same coin beat it
   **81%** of the time at 1 day. Win rate 42.5% vs a 43.0% base rate.
2. **The 20-day low is not measurable with the data I have.** 487 clean firings; the test detects
   nothing below **2% per trade.** Do not claim it works *or* that it doesn't.
3. **Both flags still cost 0.18% a round trip.** That part was never in question.

## What else changed from v1
- `vol_expanding` — unchanged advice: an excess-return test is the wrong test for a move-*size*
  flag. Relabel "tested (move size, not direction)".
- The `LEVELS.md` citation point stands and is sharpened by Mission 2: that document validated the
  **simple** 50-day average, while `scanner.py` flags the **EMA**.

## Limits
- **17 perps, not 24.** Dropping the spot series cost real coverage; the live scanner covers top-60,
  so most of its universe is still unmeasured here.
- `scanner.py` is not in my working tree — I read it from
  `origin/desktop-overdrive-2026-05-30:bot/tools/hivemind/scanner.py`. A reviewer without git access
  cannot audit the definitions, and I could not verify whether the live scanner passes stage-2
  arguments to `volforecast.forecast()`, which would change `em` materially. **Please confirm it
  calls `forecast(c)` with one argument.**
- Daily closes only; entry next open, exit a close. No stops.
- **v2 is itself not red-teamed.** v1 reproduced perfectly under review and was still wrong three
  ways, so reproduction is not validation.
