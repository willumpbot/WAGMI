# Laptop -> server, 2026-10-13 — M5 closed. BTC shocks are the one condition worth carding, and the placebo killed two findings.

`M5_TAIL_CASCADE_RESULT.md`. **EXPLORATORY**, magnitude only, no live change. 178 coins of 1h bars.

## The one thing to card

**When BTC moves more than 3× its own hourly expectation, every other coin's chance of a 3× hourly move
goes from 4.0% to 10.9%.** Lift +0.0690, **z 26.4**, 174 coins — and **pooled +0.0691 against
equal-weighted +0.0690, agreeing to four decimals.** That is the cleanest effect I have measured here.

**Suggested card: `btc_shock_tail_regime` = HYPOTHESIS.** It is cheap and self-contained — it needs only
BTC's own 1h bars and its own forecast, **no OI, no depth, no liquidation feed.** And the natural first
use is **not** leverage: it is **holding off a new entry during the shock hour.**

`funding_extreme` also survives (+0.0385, z 10.3) **with a caveat I want on the card if it goes on at
all: equal-weighted +0.0385 vs pooled +0.0164, a 2.3× divergence.** The effect concentrates in coins
with fewer hours, so for the majors the pooled figure is the relevant one and it is less than half the
size. That is why the leverage table is conditioned on `btc_shock` instead.

## 🔴 The placebo came out positive three times in five, and killed the biggest number in the table

The placebo circularly shifts each coin's condition series — the marginal rate and the flag's own
autocorrelation survive, only the alignment with the outcome dies. **It is free to come out positive,
which is the point.**

- **`liq_burst` has the LARGEST lift in the study (+0.0707, 3.1× baseline, z 3.18) and its placebo is
  +0.0406 — 57% of the effect.** So most of "liquidations predict tails" is "liquidations happen in
  volatile stretches." **Not actionable, despite a significant z.** It also reached only **4 coins**.
- **`depth_thin`'s placebo (+0.0116) is bigger than its effect (+0.0079).**
- `oi_jump` came out **negative** (−0.0049).

**Please do not card any of those three**, including `liq_burst` — the raw number is tempting and the
placebo says it is mostly regime.

## Deliverable: the regime-conditional leverage table

Per-coin flagged quantiles were unestimable and the output says so (a market-wide shock gives ~90 hours
in 210 days; the 0.999 quantile of 90 points *is* the max). So inflation is pooled across coins on the
move **normalised by each coin's own em**: p99.9 of `|move|/em` goes **8.40 calm → 13.43 flagged,
inflation 1.60×** (n 742,430 / 15,703).

With HL's real tier-1 margin and HL's cap: **BTC 23.1→16.2×, ETH 17.0→12.2×, SOL 14.9→10.8×,
XRP 15.2→11.1×, HYPE 9.1→6.9×, NEAR 8.5→6.3× — a cut to ~72%, i.e. a divisor of ~1.4.**

## 🔴 And this is my third correction in the same direction. It is a pattern, not three slips.

| estimate | risk measure | margin | "table is too timid by" |
|---|---|---|---|
| M9 phase 1 | one expected daily move | flat 0.5% (wrong) | **4.6×–6.7×** |
| M9 phase 2 | one expected daily move | real | **2.6×–3.7×** |
| **M5** | **p99.9 of 1h moves, shock-conditioned** | real | **1.7×–2.2×** |

**Every correction moved the same way, and each came from using a less convenient risk measure. I kept
reaching for the one that made the cap look timid, and the number shrank threefold as I stopped.**

**It also reverses a phase 1 argument I gave the owner.** Phase 1 said the `/1.5` divisor "guards a
scenario the stop already handles." **The regime conditioning here calls for ~1.4 — almost exactly the
1.5 already in the terminal.** So the divisor is defensible as a tail buffer; what was wrong was the
*base* it applies to. **The terminal's rule was closer to right than I said, for a reason I had not
measured.** If the owner saw the 4.6–6.7× line, that is the third thing on my list that needs replacing.

## Queue

M1 ✅ M2(A) ✅ M3 ✅ M4 ✅ M5 ✅ M9 ✅+corrected — **M6 next** (intraday magnitude seasonality).
**M6 matters more than its priority suggests:** M5's 1h expectation is the daily forecast ÷ √24, which
assumes no intraday vol shape. **If M6 finds one, M5's tail rates need revisiting** — flagged in its
limits.

Still open from my side: the **live dissent series** for M3 stage 2. Nothing blocking.
