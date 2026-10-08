# Mission 14 — is same-asset funding harvesting real on Hyperliquid?

_2026-10-08. 21 spot/perp pairs screened, 5 usable, 2,562 coin-days, 57 cycles.
Train/test split 2026-01-12. Scripts: `fetch_basis_data.py`, `basis_trade.py`.
Data: `basis_pairs.json`, `basis_trade.json`._

---

## One line, as asked

**No. The hedge works perfectly and the trade still does not pay: out of sample it earns 1–2.5%
annualised at $1–5k clips and is significantly *negative* at $25k. Do not add a Carry panel.**

---

## First, a correction to my own previous answer

`BASIS_CARRY.md` said BTC/ETH/SOL have no Hyperliquid spot market. **That was wrong.** I matched spot
*base* names against the perp universe, and HL lists the majors as **wrapped** tokens — `UBTC` (@142),
`UETH` (@151), `USOL` (@156) — so the names never matched. Mission 14 flagged exactly this.

With the mapping fixed there are **21 spot/perp pairs**, not 8, and the majors have genuine depth.
A second self-inflicted error: I rejected BTC on a basis standard deviation of 13.1%, which turned out
to be **11 bad prints out of 613** (Feb 2025 rows quoting UBTC spot at 6,969,696 and 7,979,573 —
placeholder quotes from before the market had liquidity). Filtering rows instead of coins gives BTC a
basis sd of **0.063%**, the tightest in the whole set. Rejecting the best asset over 11 rows was the
worse of the two mistakes.

---

## 1. Availability, depth and basis

| coin | spot token | days | basis mean | basis sd | funding/day | depth ±0.5% | slip $5k | verdict |
|---|---|---|---|---|---|---|---|---|
| **BTC** | UBTC | 601 | −0.007% | **0.063%** | +0.0213% | **$419k** | 0.6 bps | **USE** |
| **ETH** | UETH | 560 | −0.010% | 0.067% | +0.0204% | **$357k** | 0.7 bps | **USE** |
| **SOL** | USOL | 516 | −0.013% | 0.081% | +0.0091% | **$292k** | 1.4 bps | **USE** |
| **ZEC** | UZEC | 213 | −0.001% | 0.212% | +0.0212% | $116k | 3.2 bps | **USE** |
| **HYPE** | HYPE | 672 | +0.029% | 0.101% | **+0.0561%** | $83k | 3.0 bps | **USE** |
| ENA | UENA | 298 | +0.103% | 0.549% | +0.0153% | $6k | 45 bps | reject — thin book |
| AVAX | UAVAX | 133 | +0.084% | 0.821% | +0.0138% | ~$0k | 1253 bps | reject — thin book |
| PUMP | UPUMP/PUMP | 0 | — | — | +0.0402% | $29k | 9.6 bps | reject — every row a scale mismatch |
| AZTEC, BERA, MON, PURR, STABLE, TRUMP, FARTCOIN, VIRTUAL, XPL, WLD | — | — | — | — | — | — | — | no retrievable perp or spot history |

**A capacity oddity worth stating:** the major books are deep but `spotMetaAndAssetCtxs` reports ~$0
of 24h volume on UBTC/UETH/USOL (only PURR $2.42M, STABLE $0.41M, UZEC $0.09M show any). Deep resting
liquidity with almost no trading means **entry is probably fillable once, but repeated round trips are
not demonstrated**. Treat the depth figures as one-shot capacity, not recurring throughput.

---

## 2. The cycle backtest

Rule exactly as specified: enter when trailing-24h funding ≥ the train 80th percentile
(**0.0505%/day**), exit when trailing funding falls below its train median (**0.0300%/day**) or after
30 days. Long wrapped spot, short perp, delta flat. Costs: 23 bps per cycle in fees (perp taker 4.5 +
spot taker 7, in and out) plus slippage modelled from the **measured** book depth for each clip.

57 cycles, median hold 5 days.

| clip | half | n | funding | Δ basis | cost | **net/cycle** | CI95 | annualised on 2× capital | worst |
|---|---|---|---|---|---|---|---|---|---|
| $1k | train | 42 | 0.767% | −0.039% | 0.239% | **+0.567%** * | [+0.214, +1.067] | 12.0% | −0.40% |
| $1k | **test** | 15 | 0.242% | −0.075% | 0.251% | **+0.066%** | [−0.061, +0.227] | **2.5%** | −0.26% |
| $5k | train | 42 | 0.767% | −0.039% | 0.269% | **+0.538%** * | [+0.193, +1.016] | 11.4% | −0.41% |
| $5k | **test** | 15 | 0.242% | −0.075% | 0.290% | **+0.027%** | [−0.096, +0.180] | **1.0%** | −0.31% |
| $25k | train | 42 | 0.767% | −0.039% | 0.418% | **+0.389%** * | [+0.039, +0.845] | 8.2% | −0.47% |
| $25k | **test** | 15 | 0.242% | −0.075% | 0.483% | **−0.167%** * | **[−0.294, −0.001]** | **−6.3%** | −0.55% |

### Per coin ($5k clips, all cycles)
| coin | cycles | net/cycle | mean hold | worst cycle | capacity |
|---|---|---|---|---|---|
| **HYPE** | 27 | **+0.735%** | 9.9d | −0.31% | **$83k** (smallest) |
| ETH | 6 | +0.238% | 7.0d | −0.21% | $490k |
| SOL | 7 | +0.079% | 5.4d | −0.24% | $340k |
| ZEC | 8 | +0.076% | 4.9d | −0.22% | $116k |
| BTC | 9 | +0.061% | 5.6d | −0.41% | $419k |

**The result is structurally awkward:** HYPE produces +0.735%/cycle and 27 of the 57 cycles, but has
the *smallest* capacity. The coins with real capacity — BTC, ETH, SOL — net +0.06% to +0.24% per
cycle, barely above their own costs.

### How often a cycle fails
- **Basis moves wiped the cycle's funding in 5.3%** of cycles — so the hedge is doing its job.
- But **40–42% of cycles were net negative** at $1–5k, rising to **63% at $25k**, because fees and
  slippage, not basis risk, are what kill it.

### Why test is so much worse than train
Funding collapsed between halves: **0.767% per cycle on train versus 0.242% on test, a 68% decay.**
The same decay showed up in `BASIS_CARRY.md` (1.976% → 0.730% per 30 days on HYPE). Funding yield on
HL has been compressing, and the strategy's entire return is that yield.

---

## 3. Risks, stated plainly

| risk | assessment |
|---|---|
| **perp-leg liquidation on a squeeze** | real and quantified. `FUNDING_CARRY.md`: p99 one-day adverse move rises to **29%** in high-funding regimes, which per `SAFE_LEVERAGE.md` liquidates anything above ~3.3x. The perp leg must be funded conservatively, which raises the capital and lowers the return further. |
| **wrapped-asset custody / depeg** | UBTC/UETH/USOL are bridged representations. A depeg breaks the hedge precisely when it matters. Not quantifiable from price history; it is a tail I cannot price. |
| **funding flipping negative** | 0.6–0.8% of days per `FUNDING_CARRY.md`, and correlated with squeezes. The exit rule (funding below median) handles drift but not a gap. |
| **capacity** | the binding constraint. Deep books with ~zero traded volume; $25k is already significantly negative. Realistic size is ~$5k per coin, so ~$25k deployed across five coins for ~1–2.5% annualised. |

---

## 4. Trader rules, one number each

Even though the verdict is negative, these are the thresholds the data supports if it is ever run:

1. **Never exceed $5k per clip.** At $25k the trade is significantly negative (−0.167%/cycle, CI
   excludes zero).
2. **Only harvest on coins with ≥ $80k spot depth within 0.5%.** Below that, slippage alone exceeds
   the funding — ENA costs 45 bps and AVAX 1,253 bps per side.
3. **Require trailing funding ≥ 0.05%/day to enter.** Below that, a 5-day hold cannot recover the
   23 bps cycle cost.

---

## 5. What would actually change the answer

1. **Maker-only execution.** Tested on HYPE in `basis_fees.json`: break-even fee is 17 bps at a 7-day
   hold and 35 bps at 14 days. Maker fills would move the $5k test cell from +0.027% toward the
   +0.10–0.15% range — still only ~4–5% annualised. **Checked, and it does not rescue it.**
2. **Funding returning to 2025 levels.** Train-half yields annualised at 11–12%. If funding reverts,
   the trade becomes interesting at small size. It is worth re-running this script quarterly rather
   than concluding permanently.
3. **More cycles.** 15 test cycles is thin. The conclusion "not significant" is partly a sample-size
   statement — but the $25k cell *is* significantly negative, which is not a power problem.

## Method notes
- Funding is hourly on HL, summed to daily percentages; positive funding means longs pay shorts, so
  the short perp leg collects.
- `f_tr` uses `shift(1)`, strictly past. Entry and exit thresholds come from the **train** half only.
- Slippage model: `spread/2 + 50 bps × (clip ÷ depth within 0.5%)`, applied to both legs on entry and
  exit. A clip equal to the measured 0.5% depth therefore costs ~50 bps.
- Price PnL reduces exactly to −Δbasis because the legs cancel; confirmed empirically (mean Δbasis
  −0.039%).
- Bad-print filter: rows with |basis| > 2% are dropped as quote artefacts, not the coin.
- Capital is 2× notional (spot outright + perp margin), so annualised figures are on the doubled base.
