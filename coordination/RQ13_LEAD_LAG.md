# RQ13: BTC -> Alt Lead-Lag (1-6h) — VERDICT: KILLED (continuation); fade-signal residue is era-unstable, also killed

**Date:** 2026-07-01 · **Agent:** research subagent · **Script:** `bot/tools/research/rq13_lead_lag.py` · **Raw output:** `bot/tools/research/rq13_results.json`

## Claim under test
Scout claim: BTC leads alts — after BTC moves, ETH/SOL/XRP/HYPE follow over the next 1-6h, tradeably.

## Data (denominators first)
- **Source:** Hyperliquid 1h candles for all 5 symbols (our execution venue). Binance.com is geo-blocked (HTTP 451); Binance.US rejected — 0.28 BTC/hr volume, 63 trades/hr → stale closes would *fabricate* lead-lag.
- **Sample:** 2025-12-05 13:00 UTC → 2026-07-01 00:00 UTC = **4,980 hourly bars** (HL history depth caps at ~5,000 candles; a longer window is not available from this venue).
- **Events:** BTC |1h return| > 1%: **n=258** (5.2% of hours). > 2%: n=42.
- funding_oi_history.jsonl was not usable for conditioning: 1,569 rows total across symbols with the known 536h Jun 7-29 hole — too sparse.

## Result 1 — Cross-correlation: no lead at any horizon
corr(BTC ret[t], alt ret[t+k]), full sample (4,980 hrs):

| | k=0 (same hr) | k=1 | k=2 | k=3 | k=4 | k=5 | k=6 | alt→BTC k=1 |
|---|---|---|---|---|---|---|---|---|
| ETH | **0.899** | 0.026 | -0.016 | 0.015 | -0.010 | -0.013 | -0.004 | -0.015 |
| SOL | **0.859** | 0.012 | -0.015 | 0.019 | -0.007 | 0.007 | -0.027 | -0.018 |
| XRP | **0.808** | 0.005 | -0.036 | 0.006 | -0.003 | -0.014 | -0.000 | 0.005 |
| HYPE | **0.550** | -0.032 | -0.057 | 0.006 | -0.007 | -0.020 | -0.033 | 0.001 |

Every lagged correlation is |r| ≤ 0.057 ≈ noise. The entire relationship is contemporaneous. Era splits (E1 Dec-Feb, E2 Mar-Apr, E3 May-Jun) show the same: lag-1..6 correlations bounce around zero with no stable sign (see JSON).

## Result 2 — Event study: alts have already moved by the time the BTC bar closes
After a signed BTC ±1% hour, the alt's **same-hour** signed move: ETH +184bps, SOL +190bps, XRP +161bps, HYPE +150bps (vs BTC's own +152bps). Alts don't follow BTC — they *overshoot it simultaneously* (contemporaneous beta > 1). At 1h resolution there is nothing left to chase. BTC itself doesn't continue either (self-continuation: -1bps @1h t=-0.2, -14bps @6h t=-1.3).

Signed forward returns t+1..t+k after BTC ±1% (n=258, full sample), mean bps / t-stat:

| | 1h | 2h | 3h | 6h |
|---|---|---|---|---|
| ETH | +5.6 / 0.8 | -0.9 / -0.1 | +7.3 / 0.6 | -7.0 / -0.5 |
| SOL | +4.4 / 0.6 | -5.6 / -0.5 | +2.8 / 0.2 | -17.7 / -1.2 |
| XRP | +2.4 / 0.4 | -13.1 / -1.4 | -7.8 / -0.7 | -25.5 / -1.7 |
| HYPE | -13.3 / -1.4 | **-35.4 / -2.5** | -30.6 / -2.0 | **-63.0 / -3.0** |

No positive continuation anywhere. Hit rates 43-51%. The 2% threshold (n=42) is the same or worse (HYPE -112bps @3h t=-2.1; all others n.s.). **Continuation claim: dead in every cut.**

## Result 3 — The one residue (HYPE *fade*) fails the era test
HYPE moving *against* BTC's direction after a BTC shock looked significant full-sample (-63bps @6h, t=-3.0, survives drop-best-observation: -67bps). Adversarial check with BTC-hedged residual (alt fwd − β·BTC fwd) and era split:

| HYPE resid @3h | E1 Dec-Feb (n=136) | E2 Mar-Apr (n=64) | E3 May-Jun (n=61) |
|---|---|---|---|
| mean / t | **-69bps / -3.2** | -9bps / -0.5 | **+46bps / +2.0** |

**Sign flips across eras.** The full-sample "signal" is one era (E1) doing all the work; in the most recent era it inverts. Regime split says the same thing: fade exists in hivol (-45bps @2h t=-2.9) and downtrend (-90bps @6h t=-2.9), *flips positive* in lovol (+30bps @1h). This is E1's HYPE-specific downtrend bleeding through a conditional lens, not a stable BTC-shock response. Under THE_STANDARD an era-sign-flip is a kill regardless of full-sample t-stat. E3's +46bps t=2.0 on n=61 is likewise not graduatable on its own (single era, drop-best untested at that slice size, and it contradicts the prior two eras).

## Fees / tradeable residue
HL taker 4.5bps/side → ~9bps round trip + ~3bps slippage = **~12bps hurdle**. Best era-stable candidate: ETH residual +8bps @3h (t=1.6 full, same sign all 3 eras but never t>1.6 in any era) — **below the fee hurdle before slippage**. Nothing clears.

## Adversarial self-checks done
- Reverse direction tested (alts leading BTC): also zero.
- BTC-momentum confound removed via β-hedged residual: HYPE fade shrank and era-flipped.
- Fragility: drop-best-observation applied to all event cells (reported in JSON; full-sample HYPE fade survived it — era split is what killed it).
- Venue/staleness artifact avoided by rejecting thin Binance.US closes.
- Limitation honestly noted: 208 days, one venue, close-to-close returns (real fills at next open would only *worsen* any residue).

## Week-1 artifact test
If BTC→alt lead-lag were real at 1-6h, one week of data (~168 hrs, ~9 events) would show alts visibly lagging BTC on a chart and positive lag-1 correlation. It shows neither — lag-1 r ≈ 0.02 and alts complete their move inside the same hourly bar. Fails.

## Verdict
**KILL.** BTC→alt lead-lag at 1h+ horizons does not exist in this sample: information transmits within the same hourly bar (contemporaneous r = 0.55-0.90, all lagged r ≈ 0). No continuation edge; the apparent HYPE fade is era-unstable (sign flip E1 vs E3) and dies under THE_STANDARD. Tradeable residue after fees: **zero**. If lead-lag exists at all it lives at sub-minute horizons we cannot trade from this stack. Scout claim rejected; this kill is the deliverable. Do not build a follower strategy.
