# M9 phase 2 — 🔴 **I have to correct phase 1's headline number.** The real maintenance margin is 2.5×–10× what I assumed, and for 4 of 6 majors Hyperliquid's own cap is the answer.

_2026-10-13. `m9_tiered.py`, `hl_margin_tiers.json` (234 assets, fetched from `meta`/`marginTables`).
**EXPLORATORY.** No live change — and phase 1's recommendation (do not raise the cap) survives._

**Phase 1 is owner-facing: the server carded it as a milestone and the owner read it. So this is
published as a correction, not folded quietly into a phase-2 appendix.**

---

## 1. What I got wrong, and why it was avoidable

Phase 1 modelled maintenance margin **flat at 0.5%** and declared in its own §5.1 that the ceilings
were therefore optimistic. **They were — by more than I implied.** HL's rule is
`mm = 1 / (2 × maxLeverage)`:

| | BTC | ETH | SOL | XRP | HYPE | NEAR |
|---|---|---|---|---|---|---|
| **real mm** | 1.25% | 2.00% | 2.50% | 2.50% | 5.00% | 5.00% |
| phase 1 assumed | 0.50% | 0.50% | 0.50% | 0.50% | 0.50% | 0.50% |
| **understated by** | 2.5× | 4× | 5× | 5× | **10×** | **10×** |

**This was one unauthenticated API call, and the server had already told me where it lived.** That makes
it the same shape as the M3 error, where I took the 0.8 haircut from inside a JSON file instead of
re-measuring it: **I flagged the weakness correctly, then shipped the number anyway rather than closing
it.** Declaring a limitation is not the same as not having the error.

## 2. The corrected table

| coin | em% | p99% | mm% | HL cap | ceiling phase 1 | **ceiling corrected** | shrink | P(liq<stop) @120% |
|---|---|---|---|---|---|---|---|---|
| BTC | 1.80 | 6.69 | 1.25 | 40× | 43.5× | **32.8×** | 1.33× | 0.003 |
| ETH | 2.27 | 8.17 | 2.00 | 25× | 36.2× | **23.4×** | 1.54× | 0.002 |
| SOL | 2.45 | 8.63 | 2.50 | 20× | 33.9× | **20.0×** 🔒 | 1.69× | 0.000 |
| XRP | 2.38 | 10.41 | 2.50 | 20× | 34.7× | **20.0×** 🔒 | 1.73× | 0.000 |
| HYPE | 3.49 | 13.69 | 5.00 | 10× | 25.1× | **10.0×** 🔒 | 2.51× | 0.002 |
| NEAR | 3.96 | 19.35 | 5.00 | 10× | 22.4× | **10.0×** 🔒 | 2.24× | 0.002 |

🔒 = **Hyperliquid's own max leverage is the binding ceiling, not my stop geometry.**

**Phase 1 said "the ceiling that matters is 22× to 43×". The corrected range is 10× to 33×.**

## 3. The genuinely better answer phase 1 could not see

**For 4 of the 6 majors, the question "how much leverage is safe?" is answered by the exchange.** SOL,
XRP, HYPE and NEAR all hit HL's cap before they hit the stop-based ceiling. **That is a much more useful
answer than a simulated number**, because it needs no model, cannot drift, and is not mine to be wrong
about. Phase 1 had no visibility into per-asset caps at all.

**So the honest form of the owner's question is: "should I sit at Hyperliquid's max on the majors?"**
And on these numbers, for SOL/XRP/HYPE/NEAR, max leverage is *inside* the region where a wick cannot
reach liquidation before the stop fills — P(liq before stop) at 120% of the terminal's "safe" level is
**0.000 to 0.003**, unchanged from phase 1.

## 4. What the correction does NOT change

1. **Leverage still cannot move P&L.** `size = risk ÷ stop`, so with dollar risk fixed the position is
   identical at 3× and at 20×. **That was algebra, not simulation — no margin number touches it.** The
   central conclusion the owner acted on is intact.
2. **The terminal's table is still timid**, just less so: **2.6×–3.7× conservative, not 4.6×–6.7×.**
3. **Still do not raise the cap.** It buys idle margin and spends real tail risk, and §5 below is
   still unmeasured.

## 5. 🔴 Tiering turned out to be a red herring — and that is worth saying plainly

I queued "model HL's tiered schedule" as phase 2's main task. **It is irrelevant at this account size.**
Tier 2 begins at **$20,000,000 to $150,000,000** of notional; a $5,000 account at 0.5% risk holds about
**$1,000**. Tier 1 is the only tier Nunu will ever touch.

**So "tiered margin" reduces to "the tier-1 level" — and my error was never about tiering, it was about
the level.** I had named the right file and the wrong reason.

## 6. Still unmeasured, and still the reason not to push leverage

Phase 1's §5.2 stands untouched: **this measures wick risk, not gap risk.** A stop that does not fill —
an outage, a liquidity hole, a gap through the level — is exactly the scenario the p99/1.5 rule exists
for, and 1h bars structurally cannot see inside the hour. The 5m check on the 72 coins that have 5m
bars is still queued and is the next thing that would move this.

## Limits
- `safe_L` here is the terminal's **formula** recomputed with the real mm, not necessarily the number
  the terminal currently prints — it uses its own mm assumption, which I have not read.
- `mm = 1/(2 × maxLeverage)` is HL's documented rule, applied to the fetched tier-1 `maxLeverage`; I
  have not verified it against a live account's margin readout.
- 1h bars, one venue, 2026-03-17 → 10-13, random-time both-sided entries. Magnitude only; nothing here
  says whether to take a trade.
