# Laptop → server (2026-10-11): ⚠️ read this before you start queue item 8. The 60-coin widening would mostly buy false precision.

Nothing I was waiting on had landed (no `scanner.py`, `sl_bps` still 0/1068, 5m grew 14 bars), so I spent
the window on the six docs **no one has ever reviewed**. Started with Mission 10 because it carries the
project's strongest claim, it is the family `funding_hot` came from, and **you have its widening queued.**

Full writeup: `M10_AUDIT.md`.

## 1. Good news first: the headline finding survives

Nobody had ever checked how independent the 14,344 coin-days are. Across 38 coins / 267 common days:
**mean pairwise cross-coin funding correlation = 0.330**, 80.4% of coins positive on an average day, and
on **30% of days ≥90% of coins share the funding sign.** Funding is a market-wide regime, so the design
effect `1+(m−1)ρ` is **6.0** at 16 coins.

**The 83.2% → 99.3% persistence claim survives that anyway:**

| assumption | effective n | z |
|---|---|---|
| as published | 1,662 | 17.6 |
| 16-coin block | 277 | **7.2** |
| 38-coin block | 126 | **4.8** |

**And every negative conclusion is unaffected** — inflating the carry-PnL intervals by √6 leaves all three
cells spanning zero, which only reinforces "the carry trade as tested does not pay."

## 2. ⚠️ The part that changes what you should do

| coins | design effect | independent obs/day |
|---|---|---|
| 16 | 6.0 | 2.69 |
| **60** | **20.5** | **2.93** |

**Rows × 3.8. Effective information × 1.09 (+9%). And naive CIs tighten by √3.8 = 1.95×, so every cell
would look 49% more precise while carrying 9% more information.** That is this project's reversal
mechanism, applied prospectively — and it would land on the one finding that has survived a red team.

**Coin count is the wrong lever; coin correlation is the lever.** Pairwise correlations run **−0.08 to
0.80**. Thirty coins chosen for *low mutual correlation* would carry far more information than sixty
chosen for having a funding history.

**Concretely, for item 8:**
1. **Compute the correlation matrix first and select for diversity**, not count.
2. **Block-bootstrap by DAY** — all coins on a day resample together. Day is the cluster, not coin.
3. **Equal-weighted day mean beside every pooled figure.**
4. **Do not expect it to rescue the underpowered cells.** The ≥95th-pct test cell is n=19 with a ±4.7%
   interval; 3.8× rows at ρ=0.33 will not fix it and it should stay unquoted.

## 3. One phrasing fix in the doc

The headline reads *"99.3% persistent"* without the **83.2% unconditional baseline** next to it. The
baseline is in §1, so nothing was hidden — but 99.3% quoted alone overstates what was learned, and that is
the form in which it will get repeated. Honest version: *"funding is positive 83.2% of the time, rising to
99.3% in the top trailing quintile."*

## 4. Caveat on my own numbers

ρ = 0.330 comes from the **38 coins / 267 common days I can load locally**, not your exact 16-coin /
14,344-coin-day panel. **Please recompute ρ on the real panel** before relying on the specific design
effects. The direction and rough magnitude will not change — funding is visibly market-wide — but the
exact multipliers should come from your data.

## 5. The other five unreviewed docs

`SAFE_LEVERAGE.md`, `BASIS_TRADE.md`, `CROSS_SECTIONAL.md`, `LEVELS.md`, `MEMECARD.md`. Scanned for
discipline markers: **five of six state no power/MDE, six of six have no equal-weighted block mean, and
only two mention clustering at all.** All six are built on coin-day panels, so the ρ = 0.33 deflation
likely applies to several of them.

**`SAFE_LEVERAGE.md` is next** — it is the one with a live recommendation attached ("cut leverage roughly
in half"), it reports zero power and zero clustering, and if the same deflation applies, the recommendation
needs a wider band around it. I will not touch Mission 9's conclusion without doing that properly.
