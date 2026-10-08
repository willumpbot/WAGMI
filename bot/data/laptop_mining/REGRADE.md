# Forward grade of the laptop signal corpus (mission 3)

> **SUPERSEDED in part by `VALIDATION.md` (2026-10-08).** After full price-series
> validation the graded set is 15,663 (not 15,476), the span starts 2026-02-11 (not
> 03-16), and n_eff is 208 (not 177). Headline conclusions are unchanged; the
> February and `agree>=3` results are new there.

_2026-10-08. Source: `signal_corpus.jsonl.gz` (16,458 proposals, 2026-02-11 → 06-05)
graded against Hyperliquid 1h candles. Output: `regrade.json`, `graded_signals.jsonl.gz`._

---

## Headline

**The laptop's signal stream has no directional edge, and that independently replicates the
server's central finding on a different period and a different data source.** 15,476 signals
graded over 2026-03-16 → 06-05 (56 days, 177 symbol-day clusters) come to **−9.8 bps at 4h**
net of 9 bps fees, against the server's **−14.0 bps** for the same claim. Confidence is
uninformative in both (rank corr +0.032 here, Spearman −0.045 there).

**The one robust slice finding is BTC**: significantly negative at all three horizons
(4h −15.9 bps, CI [−30.6, −3.7]; 12h −31.8 bps; n=4,442, n_eff=49, hit 30.7%).

**The one mechanical finding, and the more useful one:** SL is hit first 53.9% of the time
versus TP1 at 16.8%. At the corpus's designed R:R of 1.50, break-even needs TP-first near 40%.
Of resolved cases, 76.2% hit the stop first, giving roughly **−0.40R per setup from geometry
alone** — before any question of direction. The stops are too tight for the targets.

---

## Coverage and what could not be graded

| | n | note |
|---|---|---|
| corpus | 16,458 | |
| **graded** | **15,476** | 94.0% |
| ungradeable — before candle history | 773 | Hyperliquid's public 1h history starts **2026-03-14**; all February and early-March signals are unreachable from this source |
| ungradeable — no candles for symbol | 209 | PEPE (listed as a `k`-prefixed ticker on HL) and the thin tail |

A local OHLCV cache (`bot/data/cache/`, 397 files, 19 MB) does reach back to **2025-11-11** and
does cover February 2026. It is **not used here**: some files carry degenerate bars
(open=high=low=close) and column order is inconsistent between files, so it must first be
validated against Hyperliquid over the overlapping period. That is the obvious next step to
recover the 773.

## Method (deltas from the server's)

Follows `bot/data/agent_grades/SCORECARD.md` except where the data forces a change:

- `p0` = **close** of the last bar at or before the signal; rejected if the gap exceeds 2h. No lookahead.
- `p(t+h)` = **open** of the first bar starting at or after t+h, tolerance one bar (3600s).
  The server resolves to ≤30 min using 5m/15m candles; Hyperliquid only serves those for recent
  months (15m from Aug 16, 5m from Sep 20), so **this grade is coarser** — up to 1h of boundary
  drift at each horizon. Treat small cells accordingly.
- `e_h` = forward return in the proposed direction, minus 9 bps fees, in bps.
- SL/TP1-first from bar high/low strictly **after** t0, 24h window.
- CIs = cluster bootstrap over (symbol, UTC day), 3,000 iterations, seed fixed.
- Corpus was already de-duplicated on (symbol, side, strategy, entry, 1h bucket).
- n_eff = distinct (symbol, day) clusters. n<13 flagged.

---

## Results (bps, net of 9 bps; * = 95% CI excludes 0)

| slice | n | n_eff | 1h | 4h | 12h | hit 4h | CI95 (4h) |
|---|---|---|---|---|---|---|---|
| **ALL (null)** | 15,476 | 177 | −10.8* | −9.8 | −10.2 | 37.3% | [−21.0, +3.6] |
| LONG | 9,815 | 139 | −10.6* | −7.2 | −21.3 | 38.7% | [−17.9, +4.0] |
| SHORT | 5,661 | 93 | −11.3* | −14.2 | +9.0 | 34.8% | [−38.0, +17.0] |
| **BTC** | 4,442 | 49 | −12.8* | **−15.9*** | **−31.8*** | 30.7% | **[−30.6, −3.7]** |
| ETH | 4,032 | 38 | −10.4* | +2.8 | +16.0 | 42.0% | [−27.9, +45.5] |
| HYPE | 3,810 | 44 | −11.8* | −12.6 | −3.5 | 39.9% | [−36.3, +10.5] |
| SOL | 3,192 | 46 | −7.4 | −13.8 | −21.5 | 37.5% | [−31.5, +9.4] |
| agree=1 | 11,051 | 138 | −11.0* | −10.3 | −4.6 | 36.3% | [−24.3, +6.2] |
| agree=2 | 4,155 | 125 | −10.3* | −7.6 | −21.1 | 40.5% | [−21.4, +7.8] |
| agree≥3 | 270 | 20 | −12.6 | −22.3 | **−72.6*** | 27.0% | [−56.5, +11.5] |
| conf <50 | 2,883 | 84 | −9.3* | −2.5 | −1.1 | 32.6% | [−34.4, +42.5] |
| conf 50–59 | 2,149 | 78 | −2.6 | **−21.7*** | −44.1 | 35.8% | **[−41.1, −4.5]** |
| conf 60–69 | 4,335 | 120 | −11.6* | −7.7 | +9.2 | 38.2% | [−22.9, +8.1] |
| conf 70–79 | 3,780 | 135 | −14.0* | −8.0 | −9.5 | 41.7% | [−25.4, +9.0] |
| conf ≥80 | 2,329 | 85 | −13.6* | −14.3 | −27.6 | 35.4% | [−29.0, +1.3] |
| 2026-03 | 2,374 | 45 | −3.9 | −8.4 | −9.3 | 47.6% | [−31.4, +13.1] |
| 2026-04 | 9,200 | 109 | −12.6* | −10.1 | −18.7 | 36.0% | [−27.1, +12.1] |
| 2026-05 | 3,852 | 20 | −10.1* | **−10.5*** | +8.3 | 33.5% | [−21.2, −1.0] |
| 2026-06 | 50 | 3 | −65.1* | +32.1 | +75.0 | 70.0% | — (n_eff 3) |

### SL / TP1 first, 24h
| outcome | n | share |
|---|---|---|
| SL first | 8,335 | 53.9% |
| unresolved in 24h | 4,535 | 29.3% |
| TP1 first | 2,606 | 16.8% |

---

## Does a bigger, earlier sample change any of the server's verdicts?

| server verdict | this sample | effect |
|---|---|---|
| take every signal is negative after fees (−14.0 bps) | −9.8 bps, 1h −10.8* | **confirmed**, independently |
| agent confidence is uninformative (AUC 0.486) | rank corr +0.032 on 15,476 | **confirmed** |
| confidence should not size anything | no monotone pattern; conf 50–59 is the *worst* cell, conf <50 the least bad | **confirmed and strengthened** |
| **risk-veto edge (+18.6 bps, provisional)** | **cannot test** | the laptop corpus has no agent roles or veto decisions — only proposals. This sample neither supports nor weakens it. |
| trade agent GO vs SKIP | **cannot test** | same reason |
| trend-adjusted floor is the one valuable block (−0.30%) | **not replicated** (mission 1: −0.010, CI [−0.315, +0.300]) | treat as unconfirmed |

**New, not in the server's scorecard:**
1. **BTC-specific negative edge**, significant at 1h/4h/12h — the strongest slice signal in this
   dataset and a direct candidate for the rules manager.
2. **Agreement is anti-predictive at 12h** (agree≥3 → −72.6*). Counterintuitive; n_eff=20, so a
   hypothesis, not a finding. Worth watching forward, as it contradicts the design assumption
   that consensus improves signal quality.
3. **Geometry dominates direction.** A −0.40R structural drag from stop/target placement is
   larger than any directional effect measured here. This also matches the archive: on 2026-04-05
   a session found `sl_atr` set to 0.55x while strategies specified 2.0x, i.e. "stops at noise
   level" — median stop width in this corpus is still only 1.458%.

## Caveats
- Coarser horizon resolution than the server's (1h bars, up to 1h boundary drift).
- Forward returns are counterfactual market outcomes, not the bot's fills, trailing stops or exits.
- 2026-05 has n_eff=20 and 2026-06 n_eff=3; month cells are weak despite large n.
- Many cells were examined (~25). Treat any single p≈0.05 cell as a hypothesis. BTC is the only
  slice significant at **all three** horizons, which is why it is the one promoted to mission 4.
- Every February signal is ungraded, so the corpus's earliest regime is unrepresented.
