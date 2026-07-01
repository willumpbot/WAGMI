# Trade / Signal / Thesis Audit — 2026-07-01
Source: bot/data/trades.csv (88 closed trades). Autonomous audit at owner request.

## Headline
Overall: **27% WR, +$750.82, expectancy +$8.53/trade** — profitable via asymmetry (avg win +87.6 vs avg loss -21.1, ~4:1). But that headline hides three real problems.

## 1. The edge is SHORTS; LONGS are a structural drain (BOTH eras)
| bucket | n | WR | PnL |
|---|---|---|---|
| ETH/BTC/SOL/HYPE **SHORT** (pooled) | 61 | ~32% | **+$1,441** |
| all **LONG** (pooled) | 27 | ~14% | **−$690** |
| worst: HYPE LONG | 8 | 12% | **−$585** |

Time-split: EARLIER 68 trades = +$780 (SHORT +1402 / LONG −622). RECENT 20 = −$29 (SHORT +39 / LONG −68). => the giant long losses (HYPE LONG −222 on 6/08, −264 on 6/17) are **legacy volume-era**, BUT the long-side stays net-negative even in the recent selective era (LONG −68 vs SHORT +39). **Long-side bleed is persistent, not just legacy.**

## 2. Confidence is mis-calibrated (anti-predictive in the 60–79 band)
| conf | n | WR | avgPnL |
|---|---|---|---|
| 60–69 | 45 | 18% | −$8.16 |
| 70–79 | 14 | **0%** | −$51.55 |
| 80–89 | 6 | 67% | +$11.77 |
| 90+ | 1 | 100% | +$17.07 |
The single biggest bucket (60–69, n=45) loses; 70–79 is 0% WR. Only **80+ is trustworthy.** The 70–79 disaster is skewed by legacy large-size losers (HYPE LONG −222/−264, BTC SHORT −141) but the pattern — mid-confidence = noise — is real. Any gate keyed to 60–70 admits garbage.

## 3. Measurement wiring leaks (can't learn from what you don't record)
- **Thesis captured on only 64%** of trades (34% blank, 2 "LLM pipeline failure").
- **Confidence missing (=0) on 22%.**
- primary_driver / regime / entry_type blank on 24% (same legacy trades); `strategy` column ~unwired (84/88 blank).
- Most gaps are legacy (pre rank-2 fix); confirm recent trades capture cleanly.

## 4. Veto self-measurement suspect
hype_long_veto was AUTO-RETIRED (53% "correct" on its blocks) — yet HYPE LONG's actual record is 12% WR / −$585. The retire logic may not weight PnL, so it can retire vetoes that are saving real money. Audit the veto accuracy accounting.

## Recommended wiring fixes (ranked by $ impact)
1. **Long-side policy** (owner call — touches "no hardcoded blocks"): short-bias sizing, OR a data-learned long veto (HYPE LONG first). n for HYPE LONG alone is 8 (<13 graduation bar) but pooled-long signal is strong + persistent.
2. **Confidence calibration**: recalibrate the LLM confidence, or down-size / add-confirmation for the 60–79 band; only 80+ earns full size. (Reversible; I can build + A/B on counterfactuals.)
3. **Plug capture leaks**: guarantee thesis + confidence + driver/regime recorded on EVERY close (finish the rank-2/rank-1 wiring). Pure measurement, no behavior change.
4. **Fix veto retire logic** to weight PnL, not just block-hit-rate.

## What needs a human (owner)
- Fix #1 is a directional-policy decision (short-bias vs long-veto vs leave-alone) — philosophically loaded vs the "no hardcoded blocks" rule, so it's the owner's call.
- Approve #2 (confidence recalibration changes trade selection — reversible).
- #3 and #4 are pure measurement/logic fixes — safe to do autonomously.
