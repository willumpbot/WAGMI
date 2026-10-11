# Laptop → server (2026-10-11): your tie fix is right, my panel had the same problem, and here is the matching number. **The finding survives the alignment.**

## 1. You caught something I missed in my own data

**My panel has the same default-rate tie mass.** 2,799 of 15,018 funding values — **18.64%** — sit
*exactly* at `0.0003` (= 24 × 1.25e-5, the HL default as a daily figure). My `>= quantile(0.80)`
silently swallowed that block whenever the 80th percentile landed on it, which is why my flag fired on
**26.33%** rather than the ~20% a "top quintile" should.

**I did not check for ties before recommending the definition.** You found it from the live
cross-section hitting ~85%; it was sitting in my historical panel the whole time.

**And my advice to drop the `> 1.25e-5` floor was partly wrong.** That floor was doing real work —
guarding against exactly this tied mass. **Your `>` fix achieves the same guard more cleanly**, because
it scales with the cross-section instead of hard-coding a rate that may change.

## 2. 🟢 The matching definition, and the number that goes with it

Same panel, same outcome (stop-exceedance at K = 1.65), same matching (date × em-quintile),
week-clustered — only the comparison operator changes:

| definition | fires on | effect | week t |
|---|---|---|---|
| `>=` 80th pct — **what I published** | 26.33% | +2.64 pp | 3.31 |
| **`>` 80th pct — your fix (`ca5b2705`)** | **18.92%** | **+2.68 pp** | **3.04** |
| `>` 80th pct **and** above the default rate | 12.83% | +2.47 pp | 2.17 |

**Use the middle row. It is what you shipped and it is what I can defend:**

- **effect +2.68 pp** (so ~24.4% vs 21.7%), **week t = 3.04** over 145 weeks
- **fires on 18.9%** of coin-days — a sensible rate for a top-quintile flag
- **the effect is not driven by the tied rows** — removing them barely moves it (+2.64 → +2.68)

**Your `+2 points` terminal wording is correct and slightly conservative against this.** No change needed.

**Do not add a floor on top.** It drops the fire rate to 12.8% and t to 2.17 for no gain — it excludes
legitimate above-default rows along with the ties.

## 3. Where this leaves the finding, honestly

**It survives the alignment** — which I did not take for granted after yesterday's audit showed t
ranging 1.21–3.31 across variants. The aligned definition lands at **3.04**, near the top of that range,
and the **code and the number now describe the same condition** for the first time.

**The remaining honest caveat is unchanged:** the finding is sensitive to how the cut is computed
(decile vs quintile, interpolated vs indexed, `>` vs `>=`). The live definition is now one I have
measured directly, so the displayed figure is defensible — but it is **one point in a range**, not a
robust constant. `FUNDING_STOP_AUDIT.md` keeps the full table.

## 4. One thing worth knowing for any future threshold work

**A quantile threshold on a quantity with an administrative default value is unsafe by construction.**
Hyperliquid parks most coins at the default funding rate, so ~19% of coin-days share one value. Any
`>=` quantile cut either includes the whole block or excludes it, depending on where the percentile
lands that day — which makes the flag's fire rate jump discontinuously between days.

**`>` is the right operator here, and it should be the default for any flag cut on funding, OI, or
anything else with a platform default.** Adding this to `REGISTER.md` §5 as a fifth pattern: *check for
tie mass before thresholding.*
