# GM_GATE_ROC_56K — Gate ROC / confidence audit on the 56k signal-outcomes log

**Date:** 2026-07-02 · **Standard:** THE_STANDARD.md v1.3 (denominators, era-split, adversarial pass, week-1-artifact test)
**Dataset:** `bot/data/logs/signal_outcomes.jsonl` — 56,037 raw records, 2026-06-02 01:50 → 2026-07-02 02:50 UTC. Symbols BTC/ETH/SOL/HYPE/XRP, all `strat=ensemble`.
**Ground truth:** HL 15m candles (cache: `bot/tools/research/gate_roc_candles_15m.json`, extended to Jul 2 02:45 UTC). Outcome = directional forward close-to-close return at 1h/4h/24h, in bps (BUY=+ret, SELL=−ret). Gross of fees; HL round-trip taker ≈ 9–10 bps is the breakeven bar.
**Code:** `bot/tools/research/gm_gate_roc_56k.py` → `gm_gate_roc_results.json`.

---

## 0. Honesty first: the 56k is really ~7k

The log re-emits the same signal every ~30 s. Collapsing consecutive identical (sym, side, conf) within 45 min: **56,037 raw → 6,967 episodes** (6,894 scored at 4h; 6,539 at 24h). Passed: 10,778 raw → 1,566 episodes. All results below are episode-level. Anyone quoting this file as "n=56k" is inflating n by 8x.

**Era split** (bot dark Jun 10–16; confidence floor regime changed Jun 17):
- **E1** Jun 2–5 (crash-week tail): 833 episodes, **87.5% SELL** (729/833), floor=20 (never binds)
- **E2** Jun 6–10: 976 episodes, floor=20 (never binds)
- **E3** Jun 17–Jul 2: 5,138 episodes, adaptive floor 58→62→66→71

**Base rates (4h, mean dir bps):** E1|SELL **+74.1** (n=729, wr .671) — crash week, shorts of any quality won. E3|BUY **−38.0** (n=1,974, wr .345); E3|SELL −8.7 (n=3,111). At 24h, E1 base = **+270 bps** (wr .813) vs E3 base = **−81 bps** (wr .378). Any pooled claim is a composition claim.

---

## 1. Does confidence rank outcomes AT ALL? — Verdict: **NO in the live era; the pooled "yes" is a week-1 artifact**

### AUC (conf → win), Mann-Whitney

| Split | 1h | 4h | 24h |
|---|---|---|---|
| all (n≈6.9k) | 0.491 | **0.537** | **0.538** |
| E1 (n=833) | 0.465 | 0.451 | 0.568 |
| E2 (n=976) | 0.461 | 0.476 | **0.431** |
| E3 (n≈5.1k) | 0.481 | 0.505 | **0.439** |
| BUY (n≈2.5k) | 0.494 | 0.569 | 0.555 |
| SELL (n≈4.4k) | 0.483 | 0.502 | 0.511 |

The pooled 0.537/0.538 **dies under the week-1-artifact test**: high-conf signals cluster in E1 where 87.5%-SELL episodes rode a crash (+270 bps base). Within every individual era, AUC is 0.43–0.51 — coin flip or worse. In E3 at 24h, confidence is **anti-predictive (0.439)**.

### Confidence bins, E3 (current regime), mean dir bps

| conf bin | 4h n | 4h wr | 4h mean | 24h n | 24h wr | 24h mean |
|---|---|---|---|---|---|---|
| 0–49 | 999 | .381 | −32.1 | 941 | .447 | −37.0 |
| 50–59 | 1,369 | .425 | −9.0 | 1,292 | .405 | −56.8 |
| 60–69 | 1,791 | .468 | −8.6 | 1,664 | .346 | −93.2 |
| 70–79 | 775 | .394 | **−42.8** | 695 | .309 | **−150.1** |
| 80–89 | 137 | .285 | **−61.4** | 124 | .403 | −83.6 |
| 90–100 | 14 | .214 | −61.9 | 14 | .214 | −248.4 |

**The old small-n claim "conf 60–79 is anti-predictive" is CONFIRMED at scale and sharpened: in E3 it's conf ≥70 that's toxic** (4h: −45.9 bps, n=926, wr .375 vs −8.8 for 50–69, n=3,160). Adversarial checks: fragility — removing the single worst episode moves −45.9 → −45.0 (nothing); composition — 8 of 10 (sym,side) cells in conf≥70 are negative (ETH SELL −69.6, HYPE BUY −151.8, HYPE SELL −76.2), so it's not one symbol; time — within the fixed Jun 24–30 window, conf<66 = −97.1 vs conf≥66 = **−121.9** (n=2,126/889), so it's not floor-change confounding. The gate's own adjusted value (`annotation.value`) does no better: AUC 0.510.

In E1 the sign flips (24h f≥90: +418 bps, wr .956, n=68) — i.e., "confidence works" was learned in one crash week and has been inverted ever since.

---

## 2. Threshold analysis — what floor maximizes EV? **None. The data wants a ceiling.**

Floor sweep, E3, mean dir bps of kept signals (episodes):

| floor ≥ | 4h n | 4h mean | 24h n | 24h mean |
|---|---|---|---|---|
| 0 | 5,085 | −20.1 | 4,730 | **−80.7 (best)** |
| 50 | 4,086 | **−17.2 (best 4h)** | 3,789 | −91.5 |
| 60 | 2,717 | −21.3 | 2,497 | −109.5 |
| 66 (live) | ~1,846 | −33.0 | 1,687 | −121.5 |
| 71 (live) | 926 | −45.9 | 833 | **−141.8** |
| 80 | 151 | −61.5 | 138 | −100.3 |

- **EV is monotonically DECREASING in the floor above ~50–55, at both horizons, in the live era.** The floors actually deployed (66, 71) select close to the worst slice of the stream: floor=71 keeps a set losing −141.8 bps/24h while the blocked set loses −67.6.
- The EV-maximizing rule on this data is inverted: a **ceiling**. E3 conf<65: −12.8 bps/4h, −58.1/24h vs unfiltered −20.1/−80.7 — a cap at 65 outperforms every floor tested.
- Both-directions check: in E1 the floor direction was correct (f≥90 → +418). Regime-dependent sign = not a rankable feature, per §2 "never hardcode directional opinion."
- **The bigger verdict: no confidence threshold in either direction makes this stream EV-positive in E3.** Best achievable slice ≈ −9 bps/4h gross, below the ~10 bps fee bar. The generator, not the gate, is the problem.

---

## 3. Gate-by-gate ROC (classifier of "loser", 24h, E3 unless noted)

Base loser rate E3: 57.8% (4h), 62.2% (24h). Precision = P(loser | rejected); lift = precision − base.

| Gate | rejected (ep) | precision 4h | lift 4h | precision 24h | lift 24h | unique-reject EV (24h) |
|---|---|---|---|---|---|---|
| confidence_floor | 3,506 | .562 | −.016 | .647 | +.025 | −124.1 bps (n=1,200) — saves |
| volume_chop | 2,897 (E3) / 3,909 all | .563 | −.015 | .593 | **−.029** | **+36.6 bps (n=1,620) — COSTS** |
| llm_skip | 483 | .634 | +.056 | .574 | −.048 | +17.9 bps (n=888) — costs |
| trend_alignment | **0 of 52,954** | — | — | — | — | dead gate |
| rr/fee/ev/lev floors | 1–2 total | — | — | — | — | effectively unwired |

**Verdicts:**
- **trend_alignment is decorative.** 52,954 evaluations, zero rejections, value and threshold both logged as 0.0 always. It gates nothing.
- **volume_chop is the biggest rejector (59% of all raw rejections) and the only gate that reliably rejects at BELOW base-rate precision — it uniquely blocked signals worth +36.6 bps/24h (n=1,620, wr .538).** Worse: its logged deciding value is **0.0 on all 33,246 rejections** against threshold 0.5, and `meta.chop_score_smoothed` is 0.0 on 100% of records. The gate fires on a value the log says is zero — broken telemetry (§3b provenance failure). This gate cannot be audited from its own log and costs money where it can be measured. Prime de-hardcode candidate.
- **confidence_floor** is the only gate with positive 24h lift (+.025), but that lift is **time-confounded**: the floor was raised (58→71) into the worst market week (wk26 base −95.8 bps, 2,168 of its 3,258 rejections). In the fixed Jun 24–30 window the kept side was WORSE than the rejected side (−121.9 vs −97.1). Its "saving" is coincidental timing, not ranking skill (AUC ≤ 0.51). Note the floor only started rejecting anything on Jun 17 — floor=20 (E1/E2) never bound once (1st-pctile conf = 31.9).
- **llm_skip/llm_execute** (llm_first pipeline, 3,082 raw / ~1,050 episodes): LLM approved 174 raw (5.6%). Executed n=102 @4h: −5.3 bps vs skipped −11.0; at 24h executed −20.2 vs skipped +17.8. **Underpowered; no detectable positive selection, mildly negative at 24h.** Does not clear small-n humility (§1) in either direction — verdict: unproven, not indicted.
- Bonus instruments: the bot's own `meta.ev_per_dollar` estimate has **AUC 0.470 (4h) / 0.444 (24h) — anti-predictive** (n=5,861/5,564). Quant-Brain-suspect confirmed on this dataset. `n_agree` is incoherent (3-agree best at 4h −1.3, worst at 24h −161.3).

---

## 4. Redundancy matrix (6,163 rejected episodes)

| | conf_floor | volume_chop | llm_skip | solo rejections |
|---|---|---|---|---|
| conf_floor (3,570) | — | **2,257** | 8 | 1,309 |
| volume_chop (3,909) | 2,257 | — | 5 | 1,651 |
| llm_skip (949) | 8 | 5 | — | 938 |

- conf_floor ∩ volume_chop Jaccard = 2,257/5,222 = **0.43** — 63% of confidence_floor's rejections are already rejected by volume_chop. Heavily redundant pair.
- llm_skip is nearly disjoint (operates on a different pipeline stage).
- **Who uniquely saves money (24h):** conf_floor-only rejects would have lost −124.1 bps (n=1,200) — unique save, though see time-confound above. **Who uniquely costs:** volume_chop-only rejects would have MADE +36.6 bps (n=1,620); llm_skip-only +17.9 (n=888).
- Full stack, E3: passed −47.9 bps/24h (n=618) vs rejected −85.6 (n=4,112) — the stack picks less-bad, but at 4h it inverts (passed −43.8 vs rejected −16.5), and everything is negative.

## 5. Killed / confirmed hypotheses (for RESEARCH_AGENDA ANSWERED)

1. **KILLED:** "confidence ranks outcomes at scale" — era-split AUC 0.43–0.51 everywhere; pooled 0.537 is a week-1 crash-week composition artifact (E1 = 87.5% SELL, +270 bps base).
2. **CONFIRMED (small-n claim, now n=926):** conf ≥70 is anti-predictive in the live era (−45.9 bps/4h, −150 bps/24h at 70–79). Raising floors to 66/71 selected toward the worst slice.
3. **KILLED:** "volume_chop protects EV" — below-base precision, uniquely blocked +36.6 bps/24h signals, and fires on a logged value of 0.0 (broken instrument, 59% of all rejections).
4. **KILLED:** "trend_alignment is a gate" — 0 rejections in 52,954 evaluations.
5. **CONFIRMED:** `ev_per_dollar` prompt stat is anti-predictive (AUC .44–.47) — supports the Quant-Brain-suspect memory.
6. **The load-bearing fact: the ensemble signal stream is EV-negative in the live era at every confidence level (best slice ≈ −9 bps/4h gross, fees ≈ 10).** Gate optimization is rearranging losses; the alpha problem is upstream in signal generation.

*Limits: outcomes are close-to-close hypotheticals (no TP/SL path, no fees/funding/slippage); episode collapse is heuristic (45 min); E2 is thin (n=976); Jun 10–16 has no data (bot dark).*
