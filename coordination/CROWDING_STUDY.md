# Funding-Crowding → Direction: does it fade or continue?
**Run:** 2026-07-01 (autonomous). **Data:** bot/data/funding_oi_history.jsonl, 2026-06-06 → 07-01 (~25 days, ~300 samples/symbol, XRP ~160). **Trigger:** the market-prediction scorecard scored 1/5 and suggested "funding-crowding = squeeze/continuation, not a fade — flip the sign." This study tests that against our own history BEFORE changing anything (validate-before-build).

## Method
For each sample, funding[t] vs forward return fwd_ret = (price[t+h]-price[t])/price[t], horizons h=6/12/24h (nearest sample within +/-1.5h). Pearson corr(funding, fwd_ret) per symbol + pooled on z-scored funding. corr>0 = CONTINUATION (crowd is right), corr<0 = FADE (crowd underperforms).

## Result
| horizon | pooled corr | read |
|---|---|---|
| 6h  | -0.06 | ~noise |
| 12h | -0.18 | weak FADE |
| 24h | -0.18 | weak FADE |

Per-symbol (12h): SOL -0.41, ETH -0.15, XRP -0.26 (24h: -0.89) show the fade tilt; BTC ~-0.09 and HYPE ~-0.05 show nothing. Tercile means (12h): low-funding (crowded shorts) forward-returns consistently BEAT high-funding (crowded longs) — e.g. SOL +3.31% vs +1.47%.

## Verdict — do NOT flip the sign
The data **weakly supports the EXISTING fade lean** (crowded longs underperform, corr ~-0.18), the OPPOSITE of the scorecard's n=1 "continuation" takeaway. Flipping the crowding->direction mapping based on one melt-up window would have been textbook overfitting to noise (the exact failure mode we guard against).

**Reconciliation (the real insight):** the fade edge is real but weak, and it gets *destroyed when it fights a trend*. The 1/5 scorecard failed not because fade is backwards, but because it faded crowded LONGS straight into a +1-3% melt-up. Direction wasn't the bug; **regime was.**

## Recommendation (validated, low-risk)
1. Do NOT invert crowding. Keep the fade sign.
2. Treat funding-crowding as a **mild fade CONTEXT tilt, gated by regime** — suppress the fade when multi-TF trend is strongly with the crowd (don't fade crowded longs in a confirmed uptrend). This is a gate, not a new directional trigger.
3. Do NOT graduate this into a hard rule yet — n and regime coverage are thin (see caveats).

## Caveats (why this is a lean, not a law)
- **Overlapping windows:** ~16-min sampling vs 12-24h horizons => heavy autocorrelation; effective N << shown; significance overstated. Treat |corr| ~0.18 as suggestive only.
- **Single regime:** ~25 days, largely trending up. Cannot cleanly separate funding signal from regime — which is itself the point (regime dominates).
- **Low funding variance** for BTC/SOL/HYPE (often pinned near the cap) => little signal there; XRP/ETH carry most of the fade tilt.
- Next step to firm this up: rerun across a longer, multi-regime span and split by trend-state (fade-in-range vs fade-in-trend) to confirm the regime-gate hypothesis before any code change.
