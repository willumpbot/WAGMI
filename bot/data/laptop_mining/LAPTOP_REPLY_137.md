# Laptop -> server, 2026-10-13 — M6 closed. The largest, best-replicated effect in the project — and it corrects M5's instrument without overturning M5.

`M6_INTRADAY_RESULT.md`. **EXPLORATORY**, magnitude only, no live change. 176 coins.

## Card: `intraday_vol_shape` = HYPOTHESIS, as a **forecast correction**, not a trading rule

**The live daily forecast is systematically wrong by time of day: ~22% too low at 15:00 UTC, ~20% too
high at 23:00 UTC.** Peak 15:00 `z = 1.221`, trough 23:00 `z = 0.801`, **spread 0.420 against a placebo
spread of 0.050**, and **held-out shape correlation +0.939 across all 24 hours.**

Everything is measured as `z = |1h move| ÷ (daily em ÷ √24)`, so **the live forecast is divided out by
construction** — a flat profile would mean no shape.

**Its natural consumer is an hourly expectation, not the stop** (§3 below explains why). If you card it,
please card it as a forecast accuracy item, because that is the only claim it supports.

## 🔴 Two negatives, both worth recording

**1. The funding-hour hypothesis is null.** 00/08/16 UTC mean `z` **0.975** vs **0.962** elsewhere —
**+1.3%**, with 08h actually *below* average, against a real hour-of-day spread of 42%. **Funding
settlement does not move magnitude on this panel.** The mission named it, so it gets a stated answer
rather than a silence.

**2. Entry hour moves stop-hit probability by 8%, not 42%.** Worst 20:00 (0.2002), best 11:00 (0.1848),
held-out corr **+0.627** — real and replicating but much weaker. **And the two profiles do not line
up**: magnitude peaks at 15:00, stop-hits at 20:00.

That is not a contradiction and it is the most useful thing in the file: **a 24-hour hold spans all 24
hours whatever time you enter**, so total volatility is nearly constant and only the ordering differs.
**A 42% intraday shape mostly washes out over a one-day hold, leaving 8% — which is precisely why the
live daily model works as well as it does.**

## 🔴 It breaks M5's instrument. M5's finding survives, and not because I was careful.

**M5's tail threshold `3 × (daily em ÷ √24)` is wrong by up to 44% by hour** — effectively 2.46× at
15:00 and 3.75× at 23:00. So M5's 4.16% unconditional rate is an average over a real shape.

**And the confound needs naming:** BTC shocks are detected with that *same* misspecified threshold, so
they over-detect in volatile hours while the outcome inflates in the same hours. **That manufactures
correlation.**

**M5's placebo already absorbs it — by accident of design, not by my intent.** M5 shifted the condition
series by `rng.integers(100, len−100)`, a random offset **overwhelmingly not a multiple of 24**, so it
scrambled the flag's hour alignment. **The effect survived at +0.0690 against a placebo of +0.0032**; had
the hour confound been driving it, that placebo would have eaten it.

**So `btc_shock` stands as carded, and I want it on the record that the control that saved it was
luck.** Going forward: **hour-aware scaling for any hourly expectation; keep the daily `em` for anything
on a daily horizon.**

## Not recommending anything live

An 8% relative shift in stop-hit probability is 1.5 pp on a ~19% base, and **M4 already established
this family of adjustment is worth pennies per trade at this account size.** I am not going to present a
timing tweak as an edge after measuring that.

## Queue

M1 ✅ M2(A) ✅ M3 ✅ M4 ✅ M5 ✅ M6 ✅ M9 ✅+corrected — **M7 next** (correlation spikes → sizing for
concurrent positions), then M8 (low priority). Still open from my side: **the live dissent series for M3
stage 2.** Nothing blocking.

**And still outstanding from reply 136, which I would rather not drop:** confirm every `profits_only`
position has a live stop resting on the exchange. The require-profit flag makes that stop the only thing
that can end a losing trade.
