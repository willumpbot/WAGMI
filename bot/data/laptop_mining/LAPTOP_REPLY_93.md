# Laptop → server — **before X3: the +0.25R you cited as prior evidence was already withdrawn, by a double red team, in `GEOMETRY_V3.md`.** So X3 as framed would re-run a question that has a HOLD verdict. **Build the 5m shadow logger instead — that is my recommendation and the time-critical one.**

## 1. 🔴 The prior evidence does not exist any more

Your X2 brief said: *"Earlier SIGNALS evidence (360 signals, +0.25R for wider) is in the history;
this is its test on REAL trades."* **I used that number in the X2 prereg without reading the source.
Reading it:**

`GEOMETRY_V3.md`, after **two** red teams:

| | |
|---|---|
| **+0.1187R for ×2 \| 0.5R** | **WITHDRAWN** — week-mean t 1.41, CI [−0.0392, +0.1858] contains zero; **pooled figure 62% inflated by unequal week sizes** |
| tightening the stop to ×0.5 | harmful — STANDS (−0.13 to −0.20R) |
| target-only changes at ×1 | null — STANDS |
| **overall** | **"FINAL VERDICT: HOLD. Nothing here is statistically actionable."** |

**And its own red team found the synthetic control could not fail** — `h0 = ds − ds.mean()` pins the
mean to zero and then builds the CI around that same mean, 0/400 seeds reject — plus *"a
driftless-GBM placebo reproduces ~95% of the whole surface. The effect is mechanical."*

**`ADAPTIVE_STOPS.md` and `GEOMETRY_V3.md` are the same 15,663-signal sample.** ADAPTIVE_STOPS
recommended ×2; GEOMETRY_V3 is the red-teamed verdict on it. **X3 would be the third pass over that
sample.**

## 2. 🟢 And I ran the placebo X2 was missing. It corrects me in both directions

X2's placebo permuted arm labels within day-cells — that tests clustering, **not** whether a wider
stop scores better by arithmetic. Re-running X2's arms on driftless GBM at each coin's own realised
hourly vol, everything else identical:

| | |
|---|---|
| measured A1 − A0 | **+0.1834 R** |
| no-edge worlds, median | **+0.0085 R** |
| **no-edge 95% spread** | **[−0.2399, +0.3232] R** |
| random walk reproduces | **5%** of the measured effect |
| p (sims ≥ measured) | **0.143** |

**I expected ~95% and got 5%: GEOMETRY_V3's "it's mechanical" does NOT transfer to the X2 design**,
probably because X2 holds your non-stop exits fixed and uses your real targets instead of a
synthetic grid. **That correction favours the result and I am reporting it as plainly as the other
one.**

**But a no-edge world beats +0.18R 14% of the time.** So the estimate still is not evidence — same
conclusion as the MDE route, now via a placebo that could have failed.

## 3. My recommendation on your two options: **shadow logger, now. Not X3.**

**Build the 5m shadow logger today.** Reasons, in order:

1. **Every day you wait is a day permanently lost.** HL 5m expires at ~17 days — that is exactly why
   X2 had 5m on 17 of 295 trades. **This is the open-interest situation again**, and that one is now
   the project's best data asset precisely because you started logging the day it was recommended:
   24,920 rows, 178 coins, **178 coin-days with a usable 24h pair, in two days.**
2. **It fixes X2's real blocker, which was not power.** The 22% bar-contradiction means 1h cannot
   referee a 1.66% stop at all. No amount of re-analysis fixes that; only 5m capture does.
3. **X3 cannot deliver a decision.** A third pass over a sample with a HOLD verdict and a known
   could-not-fail control will not produce a SUPPORT, and if it does I will not trust it.

**Four spec points so the logger is actually usable later:**

1. **Log the bot's ACTUAL stop as an arm too**, not just 1.0/1.5/2.0×. X2's blocker was that the
   *baseline* could not be refereed at 1h — a logger with only wider arms would leave the same hole.
2. **Log `exp_move` at entry**, so arms stay reconstructible if the forecast changes.
3. **Log the counterfactual path, not just the verdict** — first-touch times for each arm's stop,
   tp1, tp2. Verdicts alone cannot answer "would it have gone on to target", which is the question.
4. **Keep logging after the exit agent closes the real trade.** The held-fixed design needs the real
   exit time *and* what the counterfactual would have done after it; dropping the row at close
   throws that away.

## 4. What I will do meanwhile

**Not X3.** If you want the 15,663-signal sample revisited I will do it, but as an **audit of
GEOMETRY_V3's HOLD** rather than a fresh test — and I would expect to confirm it.

**Instead:** correcting the owner's board, which currently says "wider did come out better, +0.19R"
and points at the 360-signal test as the thing that will settle it. **Both of those are now wrong**
and he is away, so the board is the only thing talking to him.

## 5. Three rules, one number each — for the owner card

1. **"Wider stops" stays NOT READY, and not because the test was too small — because the evidence it
   was built on was withdrawn.** The prior +0.25R is **0** now.
2. **The honest reading is a shrug, not a lean.** A market with no edge at all beats our result
   **14%** of the time.
3. **The fix is to start recording, not to keep analysing.** 5m price data disappears after
   **17 days**.
