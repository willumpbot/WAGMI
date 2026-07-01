# BT_VETO_RESCORE — Dollar re-score of every graduated rule vs the counterfactual corpus

Lane: backtest / veto re-score. Date: 2026-07-01.
Script: `bot/tools/backtests/veto_rescore_2026-07-01.py` (+ `veto_rescore_detail.py`); full per-rule JSON: `bot/tools/backtests/veto_rescore_results.json`.

## Method (and honest denominators)

- **Rule population** = union of the live `bot/data/llm/graduated_rules.json` (26 rules, all regenerated TODAY 17:10 with zeroed counters) and `graduated_rules.json.bak.20260619T161520Z` (33 rules incl. the named legacy vetoes). 59 unique rules scored, active AND retired.
- **Corpus**: 39,119 resolved counterfactual records, 2026-05-30 → 2026-07-01 (33 days). Each rule's `matches()` semantics were reimplemented faithfully (regime canonicalization trending_bull→trend / consolidation→range, side BUY/LONG=SELL/SHORT canon, confidence bounds, UTC-hour bounds).
- **Episode dedup (the honest denominator)**: the raw corpus is scan-cycle spam — the same skipped setup is re-recorded every ~5–12 min. Consecutive records for the same (symbol, side) within 4h and entry within 1.5% collapse to ONE episode (median pnl). Raw counts overstate by ~20–50x; all verdicts below use episodes.
- **Scoring**: veto/penalize → `pnl_saved` = Σ|pnl| of blocked would-be losers, `pnl_missed` = Σ pnl of blocked would-be winners, net = saved − missed. Boost → inverted (winners promoted are good). Vetoes additionally get: (a) credit/debit for the ACTUAL trades in trades.csv matching their condition (LLM_FIRST overrides let them through; an enforced veto would have blocked them), (b) ~0.10% notional round-trip fee credit per blocked episode (measured live fee: median 0.073%, mean 0.086% of notional).
- **Dollars**: `hypothetical_pnl_pct` is an unlevered, fee-free price-move %. Converted at the **median live notional $714/trade** (mean $2,774 — early trades were much larger; dollars scale linearly if sizing changes).
- **Fortnights**: 3 buckets — F1 = May 30–Jun 12, F2 = Jun 13–26 (mid-June selloff; bot partly dark), F3 = Jun 27–Jul 1 (partial, current selective posture).

## Headline verdicts (the four named rules)

### hype_long_veto_v1 (just restored) — RESTORE JUSTIFIED IN DOLLARS. KEEP.
- 189 blocked episodes: saved 412.1 pct-pts vs missed 258.0 → **cf net +154.1 pct-pts = +$1,101**.
- Would also have blocked the 9 actual HYPE BUY trades taken: they lost **−$591.90** (further credit).
- Fee credit ~$132. **Combined ≈ +$1,825 over 33 days.**
- Fortnights: F1 +$63 (13L/14W), F2 **+$1,170** (100L/48W), F3 −$132 (7L/7W).
- Caveat: value is concentrated in the mid-June selloff fortnight; last week it was mildly negative. Keep, but this is a bear-regime rule — re-score if HYPE enters a sustained uptrend.
- **COORDINATION FLAG**: the live graduated_rules.json (rewritten today 17:10) does NOT contain hype_long_veto_v1. If the restore was supposed to land in that file, it has been clobbered by today's regeneration. ensemble.py Gate 1g comments still reference it. Whoever owns the rules file: re-check.

### sol_long_veto_v1 (the "14/14 hit-rate" rule) — DOLLARS SAY: REAL BUT SMALL. KEEP (minor rule, not a crown jewel).
- 57 episodes: saved 61.9 vs missed 36.3 → cf net +25.6 pct-pts = **+$183**; blocked-actual credit +$36 (4 trades, −$35.51); fee ~$40. **Combined ≈ +$258.**
- Sign-stable: positive all three fortnights (+$10 / +$155 / +$17) — the most consistent veto in the book.
- But the population hit rate is 38 losers / 19 winners = 67%, not 100%. The 14/14 live counter was a biased sample (small n, one regime). Dollar edge ≈ $8/blocked-episode. Keep; don't build strategy around it.

### night_session_block_v1 — DOLLAR-NEGATIVE COMBINED. DO NOT RESTORE.
- 190 episodes: cf net +23.0 pct-pts = +$164 — looks positive in isolation.
- BUT the 21 actual trades taken in the 00:00–06:00 UTC window made **+$375.46**. Enforcing the block would have forfeited that. Combined = +$164 − $375 + $133 fees ≈ **−$78**.
- Fortnights flip sign: F1 −$451, F2 +$466, F3 +$150. No stable time-of-day edge; the original "19% WR at night" was regime, not clock. Leave retired.

### conf_floor rules
- **conf_floor_70_v1** (penalize conf 60–70): 433 episodes, cf net **−16.1 pct-pts = −$115** (missed 631.2 vs saved 615.1 — the band is a coin flip in counterfactuals). Actual 60–70-conf trades: 49, **−$381.72** → blocking those is credit. Combined incl. fees ≈ +$570, **but** this is almost entirely non-marginal: the live confidence floors (floor_66/floor_71 = 22,265 of 39k skip records) already block this band. Verdict: **REDUNDANT — keep retired; the live floor already does this job.** Restoring it would just double-penalize.
- **btc_short_conf70_80_penalize_v1**: 15 episodes, cf net +1.3 pct = +$9; the 3 actual matching trades lost $159.70. Weak positive, tiny n. Verdict: **unmeasurable-to-mildly-positive; leave as is (retired).**
- **btc_short_90plus_boost_v1** (active): only 2 episodes ever reached conf≥90 — both would have LOST (−5.4 pct). **UNMEASURABLE (n=2), and the only evidence is against it.** The "67% WR, +$102.92/trade" founding claim is from the pre-metadata era and cannot be reproduced. Candidate to deactivate on burden-of-proof grounds.

## Active rules that are DOLLAR-NEGATIVE (retire candidates under the new criterion)

| rule | cond | eps | cf net | actual trades | combined | note |
|---|---|---|---|---|---|---|
| rule_1781080478_16 (pen) | trend+SELL | 174 | **−$826** | 10, −$124 | ~−$700 | worst active rule; blocks 304 pct-pts of winners |
| rule_1782943853_1 (pen, NEW today) | HYPE trend SELL | 70 | **−$643** | 0 | −$643 | born dollar-negative |
| rule_1782943853_2 / rule_1781693230_22 (boost) | HYPE trend BUY | 80 | **−$1,120 boost-value** | 3, −$337 | — | promotes 63 losers vs 17 winners; DIRECTLY contradicts hype_long_veto_v1. Retire both copies. |
| rule_1781878466_32 (veto) | BTC trend SELL | 37 | −$197 | 8, −$119 | ~−$52 | negative; also blocks the documented BTC-short edge |
| rule_1781025758_12 (veto) | BTC consolidation SELL | 41 | −$126 | 8, +$65 | ~−$162 | blocked trades were winning live |
| rule_1781700110_26 (veto) | SOL trend SELL | 33 | −$135 | 1, −$4 | ~−$107 | see contradiction cluster below |
| rule_1781767546_28 (pen) | SOL trend SELL | 33 | −$135 | 1, −$4 | ~−$107 | duplicate condition of _26 |
| rule_1781720035_27 (veto) | ETH range SELL | 38 | −$246 | 12, −$202 | ~−$17 | flat once blocked live losses credited; weak — retire on cf sign |
| rule_1781637145_18 (pen) | SOL consolidation SELL | 44 | −$35 | 7, −$36 | ~flat | marginal |
| rule_1780756282_10 (pen, retired) | BTC SELL | 59 | −$305 | 22, +$332 | ~−$600 | stay retired — BTC shorts were the profit engine |
| eth_trending_regime_boost_v1 (boost) | ETH trend | 39 | −$133 boost-value | 1, −$1 | — | founding 71%-WR claim not reproduced |
| rule_1781693230_21 (boost) | ETH trend SELL | 25 | −$82 boost-value | 1, −$1 | — | contradicts 3 penalize rules on same condition |
| hype_short_veto_v1 (retired) | HYPE SELL | 190 | −$488 | 11, +$17 | ~−$372 | correctly retired, stay retired |

## Active rules that are DOLLAR-POSITIVE (keep)

| rule | cond | eps | cf net | fortnight signs | note |
|---|---|---|---|---|---|
| rule_1781693230_24 (pen) | trend (any) | 323 | **+$445** | −/+/+ | broad regime tax; positive 2 of 3 |
| rule_1781827393_29 (pen) | BTC BUY | 44 | +$192 | — | 34L/10W; BTC longs genuinely bad in this window |
| rule_1781042973_15 (pen) | BTC range BUY | 40 | +$144 | — | 29L/11W |
| rule_1782943855_23/_25, rule_1781029979_14 (pen/veto) | SOL consolidation BUY | 37 | +$122 | — | consistent |
| rule_1781700110_25 (veto), rule_1781637145_19, rule_1782943854_12/_22 (pen) | SOL consolidation/range | 81 | +$87 | — | modest |
| rule_1780907413_11 / rule_1781029979_13 / rule_1781654767_20 (pen, 3 duplicates) | ETH trend SELL | 25 | +$82 | — | keep ONE, retire the duplicate copies |
| rule_1782943854_13 (veto) | SOL trend BUY | 29 | +$21 | — | marginal keep |
| rule_1782943854_11 (pen) | BTC consolidation | 81 | +$18 | — | ~flat, harmless |
| rule_1782943388_0 / rule_1777922205_0 (boost) | BTC trend | 57 | +$159 boost-value | — | cf-positive but actual BTC-trend trades lost $125 — keep with caution |
| rule_1781693230_23 (boost) | trend SELL | 174 | +$826 boost-value | — | mirror-image of retire-candidate _16; see contradictions |
| rule_1781637145_17 (boost) | SOL trend SELL | 33 | +$135 boost-value | — | contradicted by active veto _26 |

## UNMEASURABLE (say so, loudly)

**All 17 strategy-conditioned rules** (every rule with `strategy: confidence_scorer` / `regime_trend`, incl. current-file rules _3–_10, _14–_21, _24, _30–_31 and backup rule_1781827393_30, rule_1781878466_31): **zero counterfactual matches**, because every cf record has `strategy="ensemble"` and `metadata={}` — the per-strategy agreement list is never stamped into counterfactual records. These rules are unfalsifiable with current instrumentation. **Instrumentation fix needed: stamp `strategies_agree` into counterfactual records at skip time.** Until then they silently no-op against ensemble signals (condition can never match `strategy="ensemble"`), i.e. they are dead weight, not risk.

Also unmeasurable: illiquid_regime_penalize_v1 (0 cf matches — regime "illiquid" never recorded in corpus), btc_short_90plus_boost_v1 (n=2).

## Contradiction clusters (both sides active simultaneously)

1. **SOL trend SELL**: boost +8 (rule_1781637145_17) + veto (rule_1781700110_26) + penalize −10 (rule_1781767546_28) all ACTIVE on the identical condition. The veto wins at runtime and it is dollar-negative (−$107). Retire the veto and the penalize; the data weakly favors letting these through.
2. **trend SELL (any symbol)**: penalize −10 (rule_1781080478_16, −$826) vs boost +8 (rule_1781693230_23, +$826) — same condition, opposite actions, both active; they nearly cancel to −2 conf. Retire BOTH (net effect ~0 but they burn rule-budget and confuse prompt injection).
3. **HYPE trend BUY**: boost +8 (two copies) vs hype_long_veto_v1. The dollars are unambiguous: veto +$1,825, boost −$1,120. Retire the boosts, keep the veto.
4. **ETH trend SELL**: 3 duplicate penalize + 1 boost. Keep one penalize (+$82), retire the rest.

## Reproduction-fidelity caveats — plainly

1. `hypothetical_pnl_pct` is unlevered and fee-free, resolved on a TP1/SL price path over ≤48 bars. Actual trades run 2x+ leverage and pay ~0.07–0.09% fees. Dollar figures are at median live notional $714; mean notional was $2,774, so peak-sizing-era dollar impact could be ~4x larger.
2. The corpus contains only SKIPPED signals (dominated by confidence-floor skips: 22k of 39k). A rule's score here = its value among signals already rejected by something else. Marginal value on top of the live filter stack is lower for redundant rules (this is why conf_floor_70_v1 reads "positive" but is redundant).
3. Live rule counters (`times_applied`/`times_correct`) were unusable — the rules file was regenerated today with all counters zeroed. This analysis is pure condition-replay, not live-fire accounting.
4. F2 (Jun 13–26) contributes most of the dollars and was a one-directional selloff; several "edges" (HYPE long veto especially) may be regime artifacts. F3 under the new selective posture is small-n everywhere.
5. Episode clustering (4h / 1.5% entry drift) is a judgment call; raw-count numbers are in the JSON for anyone who wants to re-cut. Directionally, verdicts are identical raw vs episode except magnitudes.
6. The funding/OI 536h hole does not affect this lane (cf resolution carried its own price tracking); no external price reconstruction was needed.

## Recommended actions (for the rule-owner agent)

1. Re-confirm hype_long_veto_v1 is actually IN the live graduated_rules.json — it is not, as of 17:10 today. Restore it (dollars: +$1,825/33d).
2. Retire: rule_1781080478_16, rule_1782943853_1, rule_1782943853_2, rule_1781693230_22, rule_1781878466_32, rule_1781025758_12, rule_1781700110_26, rule_1781767546_28, rule_1781720035_27, eth_trending_regime_boost_v1, rule_1781693230_21, rule_1781693230_23 (cancel-pair), + duplicate ETH/SOL copies.
3. Do NOT restore: night_session_block_v1, hype_short_veto_v1, conf_floor_70_v1 (redundant with live floors).
4. Keep: sol_long_veto_v1 (small, stable), rule_1781693230_24, rule_1781827393_29, rule_1781042973_15, SOL-consolidation family, one ETH-trend-SELL penalize.
5. Instrumentation: stamp `strategies_agree` + `num_agree` into counterfactual records so the 17 strategy-conditioned rules become measurable.
