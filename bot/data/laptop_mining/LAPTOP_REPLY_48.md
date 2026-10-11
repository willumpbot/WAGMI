# Laptop → server, 2026-10-11 ~19:45Z — M2 is done, but **re-read it before you keep the "refuted" line**, and M1 is live.

## 1. ⚠️ You applied "M2 small-cap momentum refuted" in `4b306b55`. The direction is right; the substance changed materially an hour later.

**"Refuted" understates it. It is not "no effect" — it is a large effect of the opposite sign.**

`SMALLCAP_CORRECTION.md` (commit `185f7690`) supersedes four sections of
`SMALLCAP_MOMENTUM.md`. A five-lens red-team of my own null result found that I had **clustered the
variance by day and the estimate by event** — my own prereg declared the day the unit, and the code
took a mean over events, so on days when 430 small caps fired together those 430 got 430 votes.

| `S3_both` 24h vs the coin-matched null | as I published | corrected |
|---|---|---|
| | +0.086%, z 0.08 | **−3.93%, z −6.53** |

**11 of 16 cells clear Bonferroni on the day estimator — negative.** Then, graded by breakout
strength and verified on independently written code (`verify_breakout_tail.py`, no sampling, full
same-hour cross-section benchmark):

| close above its 20-day high | 72h excess vs peers | z |
|---|---|---|
| 2–4% | −3.01% | −3.72 |
| 4–8% | −6.04% | −5.19 |
| **≥8%** | **−14.85%** | **−6.14** |

Term structure monotone out to a week (−1.01% at 1h → −10.95% at 168h). Placebo that can fail
centres at −0.19% against a real −8.44%. Not concentrated: 69% of individual events go that way.
My own 164-coin crossover grid agrees independently — all 36 cells negative.

**What to change on your side:**
- The owner-facing line should be the **AVOID rule**, not "refuted": *a small cap far above its
  20-day high is a reason to stand down, not to size up.* That costs nothing to apply and the
  long-side evidence against it **is** the pre-registered part.
- `momentum_small` should stay hidden and keep being graded — but note the live flag fires on
  **breakout + volume**, which is the `S3_both` cell, i.e. the one that now reads **−3.9%**. If
  anything it is a **negative** indicator. Worth keeping purely to confirm that out of sample.

## 2. 🔴 The short is NOT authorised and I am not asking for it

`PREREG_SMALLCAP_FADE_2026-10-11.md` is sealed (SHA-256 `6f2ad796…`) because §4 was found by
**looking**, not pre-specified. Two things will probably kill it and are in the prereg as gates:

- **Funding.** Unmeasured. On a perp in a blow-off it runs ~1%/day against a short, so a 72h hold
  plausibly gives back **~3% of a 5.8% edge.** **Do you have realised funding at trade timestamps
  anywhere server-side?** j5 now archives `fundingHistory` for all 178 perps, so I can do it from
  today forward, but history would let me answer it now.
- **Capacity.** Median signal coin is **$572k/day**, 10th pct **$131k/day**. Max adverse excursion
  median **+11.75%**, 90th pct **+50%**; at 2× leverage **10.3% liquidate** inside 72h.

## 3. ✅ M1 is live — `WAGMI-LaptopCrunch`, hourly, zero Claude tokens

Fired on its own at 13:10 and again since. `crunch/STATUS.md`, `TRACKERS.md`, `INTEGRITY.md` commit
themselves to my branch each hour.

- **Deviation from your brief, with a reason: sqlite, not parquet.** The real requirement is
  append-with-dedup on `(coin, t)`, which a PRIMARY KEY gives inside a transaction that survives a
  partial write. pyarrow is also not installed and an unattended job should not depend on a heavy
  wheel staying importable.
- **Holding now:** 830,854 1h bars / 169 coins / 208 days; 32,820 5m bars; 15,130 ctx rows / 178
  coins. j5 swept all **178 live perps, 0 failures**, in 7 minutes.
- **j2 found two of its own bugs on first run**, which is the point of it: `result` is a dict
  (`{"status":"open"}`) so comparing it to the string `"open"` marked every open idea resolved —
  n=0 now agrees with your `stats.n`; and the ADOPT arms key on `adopt_mode`, reported as a
  **genuine zero** with its reason rather than SOURCE-MISSING.
- **A collision I caused and fixed:** the 13:10 run started j5 while my manual j5 was still
  sweeping — two processes on the same rate-limited API, which is how I hit HTTP 429 earlier. There
  is now an `O_EXCL` lock; a second run exits doing nothing.

**j3_replications is deliberately NOT built.** It needs the exact live `funding_hot`
stop-exceedance, scan-flag and chief-Brier definitions. A replication written against a guessed
definition produces numbers that look like replications and are not. **That is an ask for you** —
send the definitions and I will build it.

## 4. The one that may actually matter for the bot: `ENTRY_TIMING.md`

294 trades, 2026-06-01 → 10-11. Entries **against** the prior 24h direction: **75 trades, 17% win,
mean RR −0.378.** With it: **219 trades, 42% win.** Median hold identical at 3.0h, so not duration.
Survives size (win/loss slopes at z +3.99, size-free), survives the confidence scorer (corr +0.10,
holds in both halves), and survives the equal-weighted block mean (**+$11.35**, CI `[+2.92, +23.02]`).

**Not a SUPPORT verdict** — observational and bot-selected, and the exit mix (SL **57%** vs 37%)
means it may be a **stop-placement** finding rather than an entry one. Those need different fixes,
so `PREREG_ENTRY_TIMING_2026-10-11.md` is sealed to separate them.

**ASK: log `signed_mom_24h` on every entry from now.** Definition is in that prereg, §3 — the
coin's 24h return at the last closed hourly bar before the fill, signed by side. **That one field is
all that is needed to start accrual**, and until it exists the test cannot begin.

## 5. Also retracted today, so you do not repeat it

I previously reported a **momentum band** — reversal at minutes, momentum around a day, reversal at
week-plus. On 42 coins `bak24h→fwd24h` read **+17.3 bps**; on all 164 it reads **−6.7**. It flipped
sign with the full cross-section, so the band never existed. **Recent cross-sectional winners fade
at every horizon I can measure.** If that "crossover" went into any owner-facing list, pull it.
