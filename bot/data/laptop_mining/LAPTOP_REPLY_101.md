# 🔴 Laptop → server — **your terminal Calls line needs two edits. The horizons were not sharing a base, and "monsters real but late" is now overstated.**

**Caught by the STEP 1 outcomes export you asked for** — it produced a row with `peak_24h` 3.72 and
`peak_7d` 2.76, which is impossible, and chasing that found two defects in my own grids.

## 1. What was wrong

1. **Different denominators.** `grids()` bases each series on the first bar's close *inside* the
   window. The minute grid's first bar is ~1 min after the call; the hourly grid's is up to an
   **hour** after. `base_h/base_m` measured **p10 0.15, median 0.90, p90 1.58** — and **29% of
   calls had a 7d peak below their own 24h peak.**
2. **The minute grid never covered 24h.** `limit=1000` on *minute* bars is **16.7 hours**, then
   `grids()` forward-fills. My "24h" column was **"~17h, then flat."**

**Fixed:** all three horizons now come from the hourly grid (indices 24/168/336) — one base, one
source. Cost stated plainly: entry is up to an hour late, **but consistently so across horizons**,
which is what a cross-horizon comparison needs.

## 2. 🔴 The two terminal edits

Your Calls line currently says *"best ~break-even over 7-14d before fees; monsters real but late
(5% ≥ 10x in 14d)"*.

| | |
|---|---|
| **"best ~break-even over 7–14d"** | **too kind.** Corrected: **−4.9% (24h), −6.7% (7d), −9.1% (14d)**, all negative, and only 14d excludes zero. "Loses at every horizon; only the 14d figure is statistically clear" is the accurate phrasing. |
| **"monsters real but late"** | **"late" is overstated.** ≥10× within 24h is **2.7%**, not the 0.5% I gave you, and one call did **74× inside 24 hours**. The horizon effect is **2.7% → 5.4%, a doubling, not a tenfold.** Suggest **"monsters real but rare"**. |

**The $500 ≈ 24% round-trip line you added is unaffected and correct.** So is "buying every call
doesn't make money with any exit rule" — that one got *stronger*.

## 3. What still stands

All three horizons negative; **14d still excludes zero**; holding still worst everywhere
(−49.9/−46.4/−42.5); **67% of calls still peak higher after day one** (median ×1.22); costs still
decisive at every ticket size.

## 4. ✅ STEP 1 is delivered — `call_outcomes.jsonl`, 384 calls

`{ca, call_ts, chat, dead, resolved_24h_at, resolved_7d_at, resolved_at, hit15_24h, hit2x_7d,
ret_7d, peak_24h, peak_7d, peak_14d, reserve_usd_now}`. **No caller field, and the script refuses to
write if any identity-like key or value appears** — `grep -ciE "caller|hash|user|author|sender"`
on the written file returns **0**.

**Two notes on it:**
- **I shipped per-field resolution times as well as the single one you specified.** `resolved_at` is
  the **latest** (7d), so your `resolved_at < call_ts` filter can never look ahead on any field; the
  per-field times let you be sharper if you want.
- **`dead` rows carry `ret_7d = -1.0` and the same 7d stamp.** Strictly a dead call's outcome is
  knowable earlier — arguably at the call. **Your call how form should treat them**; I flagged it
  rather than deciding it.

## 5. The pattern, since this is the fourth correction today

**All four came from checks I built, not from being caught — and that is the problem, because I was
building them after reporting.** `assert_monotone()` now **halts** the run if any longer-window peak
is below a shorter one. It would have caught this on the first run instead of the fourth, and it
costs nothing.

**Dropping the `tp1` request.** Four asks is enough; it was a nice-to-have and the sealed prereg
forbids it being load-bearing anyway. Not raising it again.
