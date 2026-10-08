# Mission 10 — funding carry on Hyperliquid

_2026-10-08. 14,344 coin-days, 16 perps, 2023-08-12 → 2026-10-07. Train < 2025-06-01 (6,604) /
test ≥ 2025-06-01 (7,740). Script: `funding_carry.py`. Data: `funding_carry.json`._

---

## Headline

**Funding is the single most predictable quantity found anywhere in this project — 99.3% persistent
— and the carry trade as I tested it still loses money. The funding is real; the hedge is what kills
it. Hedge drift has a standard deviation 25–38× larger than the funding being collected.**

**But read the caveat in §4 before writing this off.** I hedged with BTC because Hyperliquid spot
data was not in the dataset. A **same-asset spot/perp** hedge has almost no drift, and that version
is probably a real edge. This result rules out the cross-asset version, not funding carry itself.

---

## 1. Persistence — funding is nearly deterministic

| condition | n | P(next-day funding > 0) | P(next-3-day > 0) | mean next-1d | mean next-3d |
|---|---|---|---|---|---|
| **unconditional (the null)** | 14,344 | **83.2%** | — | — | — |
| trailing 1d > 0 | 11,938 | 92.7% | 92.0% | +0.046% | +0.132% |
| **trailing ≥ 80th pct** | 1,662 | **99.3%** | 99.2% | **+0.152%** | **+0.418%** |
| **trailing ≥ 95th pct** | 350 | **99.7%** | 99.4% | **+0.281%** | **+0.747%** |
| trailing < 0 | 2,406 | 36.2% | 41.0% | −0.041% | −0.097% |

Train thresholds: 80th percentile of trailing-1d funding = 0.0785%/day, 95th = 0.2286%/day.

**Put this next to everything else in the project.** Seven missions of directional work produced
nothing that beat a coin flip out of sample. Here, one condition gives a **99.3%** hit rate on the
sign of next-day funding, and 99.4% over three days. Funding is not a forecast of price — it is a
contractual cash flow with enormous autocorrelation. That is why it is predictable and direction is not.

At the 95th percentile the cash flow is **+0.281%/day**, which annualises to over 100% if it could be
harvested cleanly.

---

## 2. The carry PnL — and why it fails

Trade: short the high-funding perp, hedge with an equal-notional long in BTC, hold 1 day.
Net = funding collected − perp price move + hedge move − 26 bps.

Costs charged explicitly: taker 4.5 bps per side × 2 legs × in and out = 18 bps, plus 2 bps slippage
per side × 2 legs × in and out = 8 bps. **26 bps per round trip.**

| bucket / half | n | funding | hedge drift | **NET 1d** | CI95 |
|---|---|---|---|---|---|
| ≥80th pct / train | 1,321 | +0.165% | −0.104% | **−0.199%** | [−0.603, +0.197] |
| ≥80th pct / test | 341 | +0.098% | −0.021% | **−0.183%** | [−1.290, +0.967] |
| ≥95th pct / train | 331 | +0.289% | −0.564% | **−0.535%** | [−1.467, +0.352] |
| ≥95th pct / test | 19 | +0.157% | +0.607% | +0.504% | [−4.676, +5.001] |

Every interval spans zero. The ≥95th-pct test cell has **n=19** and a ±4.7% interval — it carries no
information at all and should not be quoted.

### The number that explains it

| bucket | funding collected | hedge drift sd | **noise / signal** |
|---|---|---|---|
| ≥80th pct | +0.152% | 5.82% | **38×** |
| ≥95th pct | +0.281% | 6.89% | **25×** |

You collect a fifth of a percent while carrying a position whose hedge error swings six percent. The
cash flow is completely buried. No amount of sample size fixes a 25× noise-to-signal ratio; the hedge
itself is the problem.

**Why BTC is a bad hedge for an alt perp:** alts have betas well above 1 to BTC and their own
idiosyncratic moves. An equal-*notional* hedge is not even beta-matched, so a large part of the alt's
own volatility passes straight through to PnL.

---

## 3. Tail risk — squeezes are worse exactly when funding is high

Upside excursion against the short, measured from the entry close:

| bucket | n | median | p95 | **p99 (1d)** | p99 (3d) | worst |
|---|---|---|---|---|---|---|
| all days | 14,328 | 2.52% | 12.26% | **21.55%** | 39.77% | 74.28% |
| trailing ≥ 80th pct | 1,662 | 3.29% | 15.65% | **27.59%** | 53.09% | 70.24% |
| trailing ≥ 95th pct | 350 | 4.25% | 20.43% | **28.96%** | 50.83% | 39.68% |

High funding means a crowded long book, and a crowded long book squeezes harder. The 99th-percentile
one-day move against the short rises from 21.6% to **29.0%**, and over three days to **50.8%**.

Cross-reference `SAFE_LEVERAGE.md`: a 29% adverse move liquidates anything above roughly **3.3x**.
So the carry trade must be run at very low leverage precisely when its yield looks most attractive —
which cuts the annualised return by the same factor that makes it survivable.

---

## 4. The caveat that matters, and the follow-up

**This tested a cross-asset hedge, which is the wrong hedge.** The standard way to harvest funding is
a **basis trade**: long the asset spot, short the same asset's perp. Delta is then structurally flat,
hedge drift is near zero by construction rather than by correlation, and the only residual risks are
funding reversal and liquidation on the perp leg.

Rough arithmetic for the same-asset version, using this data's own numbers:

| | ≥80th pct | ≥95th pct |
|---|---|---|
| funding over a 3-day hold | +0.418% | +0.747% |
| round-trip cost | −0.260% | −0.260% |
| **net, with no hedge drift** | **+0.158%** | **+0.487%** |
| probability funding stays positive | 99.2% | 99.4% |

**+0.49% per three-day cycle at a 99.4% hit rate would be a genuine, direction-free edge** — and the
first one this project has found. It is also exactly the kind of thing that *should* exist, because it
is a structural cash flow rather than a prediction.

**What is needed to confirm it, and what I could not do here:**
1. **Hyperliquid spot availability and spot fees per asset** — only some assets have an HL spot
   market. Without that list this cannot be simulated honestly.
2. **Actual basis** (spot vs perp price) through time, because entering a basis trade at a wide basis
   can cost more than the funding earns.
3. **Borrow or capital cost** on the spot leg, plus the fact that capital is tied up in two legs, so
   the return is on roughly double the notional.
4. **Funding-reversal risk**: 0.6–0.8% of the time funding flips, and that is likely correlated with
   the squeezes in §3.

That is a well-defined mission and it is the one place in this project where a direction-free edge
looks plausible on the evidence.

---

## Blunt verdict, as asked

- **Funding persistence: a real and very strong regularity.** 99.3% / 99.7% next-day sign accuracy
  versus an 83.2% null. Use it.
- **Cross-asset hedged carry (short alt perp / long BTC): not an edge.** Negative point estimates in
  three of four cells, every CI spanning zero, and hedge noise 25–38× the signal. **Do not trade it.**
- **Same-asset spot/perp basis carry: untested here and plausibly real.** ~+0.49% per 3-day cycle at
  a 99.4% hit rate before spot-side frictions. Needs HL spot data to settle.
- **Whatever version is run, size it for the squeeze, not the yield.** p99 adverse move of 29% in one
  day caps leverage near 3x in exactly the regime that looks most profitable.

## Method notes
- Funding rates are hourly and summed to a daily percentage. Positive funding = longs pay shorts, so
  a short collects it.
- Trailing funding uses `shift(1)` — strictly yesterday and earlier, no lookahead.
- Cluster bootstrap on calendar day, 2,000 draws, so that the many coins moving together on one day
  are not counted as independent observations.
- 16 of the top-40 perps by volume had both funding and price history at the time of the run; the
  fetch for the remainder was still in progress. Re-running `funding_carry.py` after it completes will
  widen the panel, though the hedge-drift conclusion is driven by the 25–38× ratio and will not change.
