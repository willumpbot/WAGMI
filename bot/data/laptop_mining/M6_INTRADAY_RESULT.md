# M6 — the intraday shape is real, large, and replicates at **+0.939**. The funding-hour hypothesis is **null**. And it corrects M5's instrument without overturning M5's finding.

_2026-10-13. `m6_intraday.py`. **EXPLORATORY**, magnitude only, no card above HYPOTHESIS, no live
change. 176 coins with a complete 24-hour profile._

**Every number is `z = |1h move| ÷ (daily em ÷ √24)`, so the live daily forecast is divided out by
construction.** Flat z across hours would mean no intraday shape. It is not flat.

---

## 1. The hour-of-day shape

| | UTC hour | z |
|---|---|---|
| **peak** | **15:00** | **1.221** |
| | 14:00 | 1.190 |
| | 01:00 | 1.099 |
| | 13:00 | 1.097 |
| **trough** | **23:00** | **0.801** |
| | 19:00 | 0.849 |
| | 11:00 | 0.847 |

**Spread 0.420 against a placebo spread of 0.050 — 8.4× the placebo.** Held-out shape test:
**corr(ORIG17 profile, NEW profile) across all 24 hours = +0.939.**

**So the live daily forecast is systematically wrong by time of day: ~22% too low at 15:00 UTC and
~20% too high at 23:00 UTC.** The shape is the US session (13:00–15:00) plus an Asia bump at 01:00, with
the quiet running 06:00–11:00 and 19:00–23:00.

**The placebo had to be redesigned and that is why it works.** M5's circular shift would have been
**inert** here — a shift by a multiple of 24 preserves hour labels exactly. This one rotates each coin's
return series by an offset that is *not* a multiple of 24, keeping its autocorrelation and marginal
distribution and destroying only the clock alignment. **It returns 0.050 against a real 0.420.**

## 2. 🔴 The funding-hour hypothesis is null, and the mission asked for it specifically

| | mean z |
|---|---|
| funding hours (00 / 08 / 16 UTC) | **0.975** |
| every other hour | 0.962 |
| | **+1.3%** |

Individually: **00h 0.991, 08h 0.935, 16h 0.999** — one of the three is *below* average. **Against a
real hour-of-day spread of 42%, a 1.3% funding-hour effect is nothing.** Funding settlement does not
move magnitude on this panel, and that is a clean negative on a named hypothesis rather than a silence.

## 3. Does stop-hit probability depend on entry hour, holding `exp_move` fixed? **Yes — by 8%, not 42%**

| | UTC hour | P(stop hit in 24h) |
|---|---|---|
| **worst entry** | **20:00** | **0.2002** |
| **best entry** | **11:00** | **0.1848** |

**Spread 0.0154 = 8.0% relative.** Held-out shape test: **corr(ORIG17, NEW) = +0.627** — positive and
replicating, but materially weaker than the magnitude shape's +0.939.

**And the two profiles do not line up**: magnitude peaks at 15:00 while stop-hits peak at 20:00;
magnitude troughs at 23:00 where stop-hits are *high*. That is not a contradiction — **a 24-hour hold
spans all 24 hours whatever time you enter**, so total volatility is nearly constant and only the
*ordering* differs. What is left is a path effect, and it is small.

**This is the internally consistent story and it is the useful part of M6:** a 42% intraday shape
**mostly washes out** over a one-day hold, leaving 8%. **Which is precisely why the live daily model
works as well as it does** — the shape is real but the horizon integrates over it.

## 4. Weekday

`Mon 0.882 · Tue 1.004 · Wed 0.947 · Thu 1.055 · Fri 1.007 · Sat 1.012 · Sun 0.844` — spread 0.211,
**Sunday quietest, Thursday highest.**

**Weaker evidence than the hourly result and labelled so: I did not run the rotation placebo on the
weekday buckets**, and with only 7 buckets over ~210 days each coin contributes ~30 observations per
bucket. Treat as suggestive only.

## 5. 🔴 What this does to M5 — the instrument is wrong, the finding survives

M5's tail threshold was `3 × (daily em ÷ √24)`, which **this file shows is wrong by up to 44%
depending on the hour.** So:

- **M5's "3×" is effectively 2.46× at 15:00 and 3.75× at 23:00.** Its 4.16% unconditional tail rate is
  an **average over a real shape**, not a constant.
- **And there is a confound I have to name:** BTC shocks are detected with the *same* misspecified
  threshold, so they will be **over-detected in the volatile hours** — and the outcome is measured the
  same way. Both flag and outcome inflate in the same hours, which manufactures correlation.

**But M5's placebo already controls for this, by accident of design rather than by my intent.** M5
shifted the condition series by `rng.integers(100, len−100)` — a random offset, **overwhelmingly not a
multiple of 24**, so it scrambled the flag's hour alignment. **The effect survived at +0.0690 against a
placebo of +0.0032.** Had the hour confound been driving it, that placebo would have absorbed it.

**So: M5's `btc_shock` finding stands, and I am not claiming I planned the control that saved it.** What
should change is the **definition** going forward: any future use of an *hourly* expectation should use
an hour-aware scaling instead of `√24`. **Anything on a daily horizon should keep the daily `em`** — §3
shows the shape integrates away there.

## 6. What I would recommend

**Nothing live.** Consistent with M4 and M9: the geometry dials here are small. An 8% relative change in
stop-hit probability by entry hour is real and replicating, but it is 1.5 percentage points on a ~19%
base, and **M4 established that this family of adjustment is worth pennies per trade at this account
size.** I am not going to present a timing tweak as an edge after measuring that.

**The one thing worth carding as HYPOTHESIS: `intraday_vol_shape`** — not as a trading rule but as a
**forecast correction**, because it is the largest, best-replicated effect I have measured
(+0.939 held-out) and it makes an existing live model measurably more accurate. **Its natural consumer
is the hourly expectation M5 needs, not the stop.**

## Limits
- One venue, 2026-03-17 → 10-13 (~210 days), so each coin contributes ~8–9 observations per hour per
  month; the hourly profile is well sampled, the weekday one far less so.
- Magnitude only. Nothing here says which direction to trade, only when price travels further.
- `z` divides by the **live** daily forecast, so a systematic bias in that forecast would shift the
  whole profile up or down — **it cannot create a 42% hour-of-day shape**, but the absolute level of z
  is a statement about the forecast, not only about the market.
- Stop-hit uses random both-sided entries, a 1.65 × daily-em stop and a fixed 24h hold; a different
  hold length would redistribute the path effect in §3.
- The ORIG17 stop-hit level sits below NEW at every hour (~0.17 vs ~0.19). That is a **level**
  difference, not a shape one, which is why the held-out test is on correlation.
