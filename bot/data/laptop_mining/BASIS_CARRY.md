# Spot/perp basis carry — the mechanism works, the economics don't

_2026-10-08. HL spot screen across 330 spot pairs / 234 perps; 672 usable asset-days on HYPE,
2024-12-05 → 2026-10-07. Split at 2026-01-12 (train 403 / test 269).
Scripts: `fetch_spot.py`, `basis_carry2.py`. Data: `spot_meta.json`, `basis_carry.json`._

---

## Headline

**`FUNDING_CARRY.md` ended by saying a same-asset spot/perp hedge was probably the real edge this
project had been looking for. It isn't. The hedge works exactly as predicted — drift goes to
essentially zero — but the yield on the only Hyperliquid pair where it can be run nets out at
2.3% annualised on capital. That is below risk-free, on one asset, with no diversification.**

This is a definitive negative, and it is worth having: it stops anyone building the thing.

---

## 1. The hard constraint, found first

Of 330 HL spot pairs and 234 perps, exactly **8 assets have both a USDC spot market and a perp**:
AZTEC, BERA, HYPE, MON, PUMP, PURR, STABLE, TRUMP.

**BTC, ETH, SOL and XRP have no Hyperliquid spot market.** The basis trade cannot be run on any
major on HL.

After screening for usable data, **one asset survives**:

| asset | days | basis mean | basis sd | funding/day | verdict |
|---|---|---|---|---|---|
| **HYPE** | 672 | **+0.029%** | **0.101%** | +0.0561% | **USE** |
| PUMP | 455 | +2459.504% | 1137.100% | +0.0402% | **REJECT** — spot and perp quoted on different scales; that is an artefact, not a basis |
| AZTEC, BERA, MON, STABLE, TRUMP | — | — | — | — | no perp candles retrievable |

A genuine spot/perp basis is a fraction of a percent, so I filtered on |basis| < 5%. My first run
averaged PUMP in and produced nonsense (a −54% "net" with a ±213% interval); that run is superseded.

---

## 2. The hedge does work — this part is confirmed

| | cross-asset hedge (`FUNDING_CARRY.md`) | same-asset hedge (here) |
|---|---|---|
| hedge drift, mean | −0.104% / day | **−0.0001% / day** |
| hedge drift, sd | **5.82%** | **0.11%** |
| noise ÷ signal | **38×** | **≈2×** |

Long spot and short perp on the same asset is delta-flat by construction, and the data agrees:
basis change is indistinguishable from zero at every hold period (−0.0001% at 1 day, −0.0137% at 30
days). **The reason the cross-asset version failed is now positively identified** — it was the hedge,
not the funding.

---

## 3. The economics, by hold period

Net = funding over the hold − change in basis − 35 bps round trip (perp taker 4.5 bps + spot taker
7 bps, each in and out, plus 3 bps slippage per leg per side). Block bootstrap with block length =
hold period, because overlapping holds share days.

| hold | half | n | funding | Δ basis | NET | CI95 | on capital | annualised |
|---|---|---|---|---|---|---|---|---|
| 1d | train | 403 | 0.077% | −0.000% | **−0.273%** * | [−0.289, −0.255] | −0.136% | −49.8% |
| 1d | **test** | 268 | 0.025% | −0.001% | **−0.325%** * | [−0.332, −0.317] | −0.162% | −59.2% |
| 3d | train | 403 | 0.229% | −0.003% | −0.118% * | [−0.165, −0.071] | −0.059% | −7.2% |
| 3d | **test** | 266 | 0.075% | −0.000% | **−0.275%** * | [−0.288, −0.262] | −0.138% | −16.8% |
| 7d | train | 403 | 0.523% | −0.005% | **+0.178%** * | [+0.049, +0.323] | +0.089% | +4.6% |
| 7d | **test** | 262 | 0.174% | −0.000% | **−0.176%** * | [−0.206, −0.149] | −0.088% | −4.6% |
| 14d | train | 403 | 1.006% | −0.008% | **+0.664%** * | [+0.373, +1.042] | +0.332% | +8.7% |
| 14d | **test** | 255 | 0.346% | −0.001% | −0.003% | [−0.061, +0.055] | −0.002% | −0.0% |
| 30d | train | 403 | 1.976% | −0.014% | **+1.640%** * | [+1.018, +2.514] | +0.820% | +10.0% |
| **30d** | **test** | 239 | 0.730% | −0.001% | **+0.381%** * | **[+0.258, +0.510]** | **+0.190%** | **+2.3%** |

### Why short holds cannot work
HYPE funding averages **+0.0561%/day**, so **6.2 days of carry are needed just to cover 35 bps of
fees**. Testing a 1-day hold was testing whether 0.056% beats 0.35% — it cannot. My first run made
exactly that mistake; this table is the corrected version.

### Why the long hold still isn't enough
The 30-day hold is the only cell that is positive with a CI excluding zero **on test**. It earns
**+0.190% on capital per 30 days = 2.3% annualised**, because:
- capital is **2× notional** (spot bought outright plus perp margin), halving the headline return
- **funding decayed 63% between halves** — 1.976% per 30 days on train versus 0.730% on test. The
  train figure annualises to 10%; the test figure to 2.3%. The yield is not stable.
- it is **one asset**. No diversification, and HYPE is already the bot's largest concentration.

---

## 4. Verdict

| claim | status |
|---|---|
| funding is highly persistent (99.3%) | **confirmed** (`FUNDING_CARRY.md`) |
| a cross-asset hedge destroys the carry | **confirmed** — 38× noise/signal |
| a same-asset hedge removes the drift | **confirmed** — drift ≈ 0.000%, 2× noise/signal |
| the basis trade is a usable edge on HL | **NO** — 2.3% annualised on capital, one asset, decaying yield |

**Do not build it.** The honest summary is that funding persistence is real and the hedging theory is
correct, but Hyperliquid does not list spot against any major perp, and the one pair that does work
pays too little to clear a 35 bps round trip plus double capital.

### What would change the answer
1. **A venue with spot for BTC/ETH/SOL against an HL perp.** Holding spot elsewhere reintroduces
   transfer latency and counterparty risk, but the funding is 4–5× larger on majors in the top bucket
   (0.281%/day) than HYPE's average, which would clear fees in ~1.2 days instead of 6.2.
2. **Maker-only execution.** At maker rebates instead of 35 bps taker, break-even falls to ~2 days
   and the 7- and 14-day cells would likely flip positive. Worth re-running if fills can be made
   passively.
3. **Entering only in the top funding bucket** rather than all days. The table above pools all days;
   `FUNDING_CARRY.md` showed the top 5% pays 0.281%/day versus 0.056% on average. HYPE alone has too
   few such days to test honestly, but across several assets it would be testable.

Those are concrete and testable. None of them is in the current data, so they stay as hypotheses.

## Method notes
- Position: long 1 unit spot, short 1 unit perp. Price PnL reduces exactly to −Δbasis, since the legs
  cancel; verified empirically (Δbasis ≈ 0 at every horizon).
- Funding sign: positive funding means longs pay shorts, so the short perp leg collects it.
- `f_tr` uses `shift(1)` — strictly past. Outcomes use forward windows only.
- Train/test split at the 60th percentile of available days (2026-01-12), not a fixed date, because
  HYPE spot only begins 2024-12-05.
- The first run (`basis_carry.py`) is retained for provenance but its numbers are superseded: it
  included PUMP and tested only 1- and 3-day holds.
