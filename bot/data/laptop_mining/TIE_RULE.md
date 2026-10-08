# The tie rule, measured — it was wrong, and it was wrong in our favour

_2026-10-08. 18,438 ambiguous hourly bars resolved at 5-minute resolution, 11 symbols,
2026-09-21 → 10-08. Script: `tie_rule.py`. Data: `tie_rule.json`._

---

## Headline

**Every geometry simulation in this project assumed that a bar containing both the stop and the
target resolved as a STOP. The true rate is 39.1%. The target is hit first 45.5% of the time.**

But the direction matters more than the magnitude: **the assumption made results pessimistic, and it
penalised tight stops hardest.** So it was working *against* the wide-stop conclusion, not
manufacturing it. Correcting it would make the retraction stronger, not weaker.

This was the reviewer's sharpest unanswered criticism, and it is now measured rather than assumed.

---

## What actually happens inside an ambiguous bar

| bracket | tp | side | n | **stop first** | target first | still tied at 5m |
|---|---|---|---|---|---|---|
| 0.2% | 0.5R | LONG | 2,613 | **29.1%** | 46.1% | 24.8% |
| 0.2% | 0.5R | SHORT | 2,624 | **26.8%** | 48.7% | 24.6% |
| 0.2% | 1.0R | LONG | 2,177 | 41.7% | 40.1% | 18.1% |
| 0.2% | 1.5R | LONG | 1,783 | 52.1% | 34.5% | 13.4% |
| 0.5% | 0.5R | LONG | 1,102 | **30.7%** | 61.5% | 7.8% |
| 0.5% | 1.5R | SHORT | 423 | 60.3% | 36.2% | 3.5% |
| 1.0% | 0.5R | LONG | 269 | **23.0%** | 75.1% | 1.9% |
| 2.0% | 0.5R | LONG | 31 | **19.4%** | 80.6% | 0.0% |
| **OVERALL** | | | **18,438** | **39.1%** | **45.5%** | **15.4%** |

Two patterns, both systematic:

1. **A near target wins the race.** At tp 0.5R the stop comes first only 19–31% of the time — the
   target is simply closer, so price reaches it first. At tp 1.5R the stop wins 51–72%. The rule's
   error is therefore **largest exactly where the geometry work spent most of its time.**
2. **15.4% are still tied at 5m resolution** — both levels touched inside the same 5-minute bar. Even
   minute data would not fully settle those; it is a genuine limit, not a fixable gap.

## What the error is worth

45.5% of ambiguous bars were scored as **−1R** when they were really **+tpR**:

| target | mis-scored | error each | cost per ambiguous bar |
|---|---|---|---|
| 0.5R | 53.1% | 1.5R | **+0.797R** understated |
| 1.0R | 42.8% | 2.0R | **+0.855R** understated |
| 1.5R | 35.7% | 2.5R | **+0.892R** understated |

**Per ambiguous bar, not per trade.** Most trades never meet one. The portfolio-level error is this
figure times the ambiguous-bar rate — which none of the geometry runs reported, and should have.

---

## Why this strengthens the retraction rather than weakening it

A tight bracket straddles far more often than a wide one, simply because the levels sit closer
together. So the conservative rule:

- **under-states the tight-stop configurations** (the bot's default) the most
- **barely touches the wide-stop configurations**, which rarely straddle at all

That means the measured `−0.3477R` for the bot's default is **too pessimistic**, and the
`+0.35R` wide-stop advantage in `GEOMETRY_V2.md` is **overstated**. Correcting the tie rule would
shrink the advantage further — in the same direction the side-flip null already pointed.

So on this one point the original work was conservative, not flattering. It does not rescue
anything: the side-flip null killed the finding on the attribution, not on the magnitude.

---

## Trader rules

1. **A 0.5R target beats its stop to the punch about 3 times in 4** at a 1% bracket — closer targets
   fill far more reliably than a bar-resolution backtest suggests.
2. **Treat any 1h-resolution backtest of a bracketed trade as pessimistic by up to 0.8R per
   ambiguous bar**, and most so when the target is near.
3. **15% of close calls are unresolvable** even at 5-minute data — no backtest at any resolution we
   can get will settle them, so do not tune a strategy that depends on winning those.

## Limits
- The 5m window (2026-09-21 → 10-08) is a **different period** from the Feb–Jun signal corpus.
  Hyperliquid does not serve 5m that far back, so a direct correction of the corpus is impossible.
  This measures a microstructure property and assumes it travels; that assumption is untested.
- Hourly bars here are **aggregated from 15m** (open of first, max high, min low, close of last),
  because `history/` holds no 1h series overlapping the 5m window. Aggregation is exact.
- Brackets are synthetic and symmetric around each hour's open, not real signals — the question asked
  is about price behaviour, not about any particular strategy.
- Only cells with n ≥ 25 are reported; the 2% and 4% brackets mostly fall below that.
