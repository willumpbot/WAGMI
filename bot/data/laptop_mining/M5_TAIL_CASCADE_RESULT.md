# M5 — tail / cascade risk. **Two of five conditions survive. BTC shocks inflate the fat tail 1.60×, and the leverage ceiling should be cut to ~72% in those hours.**

_2026-10-13. `m5_tail_cascade.py`. **EXPLORATORY**, magnitude only, no card above HYPOTHESIS, no live
change. 178 coins of 1h bars, unconditional tail rate 4.16%._

**tail = `|next 1h move| > 3 × (live HAR daily forecast ÷ √24)`.** Condition read at bar *i*, outcome at
bar *i+1*.

---

## 1. The headline

| condition | coins | P(tail) flagged vs calm | lift | z | **placebo** | verdict |
|---|---|---|---|---|---|---|
| **btc_shock** | **174** | 0.1092 vs 0.0401 | **+0.0690** | **26.4** | **+0.0032** | **CUT LEVERAGE** |
| **funding_extreme** | **158** | 0.0785 vs 0.0400 | **+0.0385** | **10.3** | **−0.0013** | **CUT LEVERAGE** |
| liq_burst | **4** | 0.1041 vs 0.0334 | +0.0707 | 3.18 | **+0.0406** 🔴 | not actionable |
| depth_thin | 12 | 0.0431 vs 0.0352 | +0.0079 | 1.37 | **+0.0116** 🔴 | not actionable |
| oi_jump | 13 | 0.0313 vs 0.0362 | −0.0049 | −1.61 | +0.0126 | not actionable |

**When BTC moves more than 3× its own hourly expectation, every other coin's chance of a 3× hourly move
goes from 4.0% to 10.9% — a 2.7× jump.** That is the cascade the mission was asking about, and it is the
cleanest effect I have measured in this project: **pooled +0.0691 against equal-weighted +0.0690 —
agreement to four decimal places**, across 174 coins.

## 2. 🔴 The placebo earned its place, and it changes two conclusions

The placebo **circularly shifts** each coin's condition series by a random offset: the marginal rate and
the flag's own autocorrelation survive, only its alignment with the outcome is destroyed. **It is free to
come out positive, which is the whole point** — a placebo pinned to zero by construction tests nothing.

**It came out positive three times out of five, and killed two findings that would otherwise have led
the report:**

- **`liq_burst` has the largest lift in the table (+0.0707, 3.1× baseline, z 3.18) and its placebo is
  +0.0406 — 57% of the effect.** So most of what looks like "liquidation bursts predict tails" is just
  "liquidation bursts happen in volatile stretches". **Reported as not actionable despite the biggest
  raw number and a significant z.** It also rests on **4 coins**, not the 13 the table holds.
- **`depth_thin`'s placebo (+0.0116) is LARGER than its effect (+0.0079).** Nothing there.

**`btc_shock`'s placebo is +0.0032 against a +0.0690 effect, and `funding_extreme`'s is −0.0013.** Those
two are real.

## 3. One caveat on `funding_extreme` that I will not bury

**Equal-weighted +0.0385 against pooled +0.0164 — a 2.3× divergence.** The clustering standard says the
equal-weighted figure governs, and it is the one in the table. **But the divergence means the effect is
concentrated in coins with fewer hours, i.e. smaller and thinner ones** — so for the **majors**, which
is where leverage actually gets used, the pooled figure is the more relevant read and it is less than
half the size.

**`btc_shock` has no such problem** (+0.0690 vs +0.0691), which is a large part of why I am willing to
condition the leverage table on it and not on funding.

## 4. The deliverable: a fat-tail-aware, regime-conditional leverage table

The per-coin flagged column was **unestimable and says so** — a market-wide BTC shock supplies only ~90
hours inside 210 days, and the 0.999 quantile of 90 points *is* the maximum. So the tail inflation is
estimated **once, pooled across coins**, on the move **normalised by each coin's own expected hourly
move**, which makes coins comparable:

| | n | p99.9 of \|move\| ÷ em |
|---|---|---|
| calm hours | 742,430 | **8.40** |
| BTC-shock hours | 15,703 | **13.43** |
| | | **inflation 1.60×** |

**Using HL's real tier-1 maintenance margin and capped by HL's own max leverage:**

| coin | em 1h | ceiling, calm | **ceiling, BTC shock** | cut to |
|---|---|---|---|---|
| BTC | 0.367% | 23.1× | **16.2×** | 70% |
| ETH | 0.463% | 17.0× | **12.2×** | 72% |
| SOL | 0.500% | 14.9× | **10.8×** | 73% |
| XRP | 0.486% | 15.2× | **11.1×** | 73% |
| HYPE | 0.711% | 9.1× | **6.9×** | 75% |
| NEAR | 0.808% | 8.5× | **6.3×** | 74% |

**So the answer to "which conditions should cut leverage" is: BTC shocks, and the cut is to about 72% of
the calm ceiling — a divisor of roughly 1.4.**

## 5. 🔴 Third correction in the same direction: I have overstated the cap's timidity three times

Putting the three estimates of "how conservative is the terminal's safe-leverage table" side by side:

| estimate | risk measure | maintenance margin | verdict on the table |
|---|---|---|---|
| M9 phase 1 | one expected daily move | **flat 0.5% (wrong)** | **4.6×–6.7× too timid** |
| M9 phase 2 | one expected daily move | real, 1.25–5.0% | **2.6×–3.7× too timid** |
| **M5 (here)** | **p99.9 of 1h moves, shock-conditioned** | real | **1.7×–2.2× too timid** |

**Every correction moved the same way, and each one came from using a less convenient risk measure.**
The pattern is not three unrelated slips: **I kept reaching for the measure that made the cap look
timid, and the number shrank by a factor of three as I stopped.**

**And it reverses one of phase 1's arguments.** Phase 1 said the `/1.5` divisor "guards a scenario the
stop already handles." **Measured here, the regime conditioning calls for a divisor of ~1.4 — almost
exactly the 1.5 the terminal already uses.** So the divisor is defensible as a tail buffer; what was
wrong was the *base* it is applied to, not its existence. **The terminal's rule was closer to right
than I gave it credit for, for a reason I had not measured.**

## 6. What I would recommend, and what I would not

**Would not:** change the leverage table. The two surviving conditions are magnitude findings on random
entries, `ADAPTIVE_STOPS` is off, and §5 says my own estimates here have moved by 3× in a day.

**Would, as the one idea worth carding:** **a BTC-shock regime flag is cheap, market-wide, and the
best-supported signal in this study.** It needs only BTC's own 1h bars and its own forecast — no OI, no
depth, no liquidation feed — and it more than doubles every coin's tail probability. **If any single
condition ever gates risk, it should be that one**, and the natural first use is not leverage at all
but **holding off on a new entry during the shock hour.**

## Limits
- **Coverage is wildly uneven by condition and that is reported per row, never intersected.** Pooling
  all five would have collapsed the panel to 13 coins over 73 days.
- `liq_burst` reached only **4 coins** and `depth_thin` 12 — both below anything I would act on even
  without the placebo problem.
- **Absence reported as absence:** `panels.ctx` carries ~3 days of OI, so OI came from the 31-coin
  128-day export instead; nothing was treated as zero.
- BTC shock is **contemporaneous**, not a forecast: it says the next hour is dangerous *given* BTC just
  moved, not that BTC's move can be predicted.
- One venue, 2026-03-17 → 10-13. Magnitude only — nothing here says which way to trade.
- The 1h expectation is the daily HAR forecast ÷ √24, which assumes no intraday vol shape. **M6 is
  exactly the test of that assumption**, so this number may need revisiting after it.
