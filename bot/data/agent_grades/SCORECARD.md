# LLM Agent Scorecard — forward-graded, 2026-05-30 → 2026-10-05

**Headline: no LLM agent shows skill at predicting price.** The trade agent's GOs did *worse* than its SKIPs
(-22 vs -12.5 bps at 4h, after fees; at 12h the gap is -31 bps, p=0.002). The regime agent is no better than
shuffled labels, and its "trending_bear" label was followed by price going *up* 62% of the time. The exit agent's
hold-vs-close calls are a coin flip (0.0 bps difference). The quant agent's long/short calls do worse than
"always long" at the same moments. **The one exception is the risk agent's veto:** among trade-agent GOs, the
setups risk blocked were 18.6 bps worse at 4h (CI +3.5…+34.7, positive at 1h, 4h and 12h). Even so, what risk
let through still lost money (-17 bps). That is the best candidate for the first graded "manager". It acts as a
filter, not a source of profit.

Skips saved money only because the whole signal stream loses money after fees. Taking every signal = -14 bps per
4h setup. Always-skip = 0, and that beats every agent.

## Method (short)
- Source: `data/llm/agent_performance.jsonl`, 56,475 records. **636 pipelines (~7%) were pytest fixtures written
  into the live file** (latency 150/0 ms, canned text such as "3-strategy consensus in trending regime with
  positive EV"). They were dropped; they would have added ~600 fake GOs. Root cause is likely
  `performance_tracker._DEFAULT_DATA_DIR = "data/llm"` (relative), so tests that use the default tracker write into
  the live file when run from `bot/`. `trade_events.jsonl` has the same problem: ~7.5k TRADE_OPENED rows (vs ~290
  real trades) and ~15k SIGNAL_GENERATED rows that fail a price sanity check (e.g. entry=100.0).
- Graded: 8,340 real pipelines (one round = regime + quant + trade + risk + critic), all sharing one timestamp,
  plus 7,684 exit-agent evaluations across 218 position clusters.
- Proposed side: no pipeline role logs `side` (it is empty). It was recovered from the latest real
  SIGNAL_GENERATED for that symbol up to 15 min before the round (6,038 rows), falling back to side words parsed
  from the reasoning text (1,735 rows; these agree with the signal side 92% of the time). Results hold when only
  signal-joined sides are used (`robustness.json`).
- Prices: Hyperliquid 1h candles (full span), 15m (from Aug 16), 5m (from Sep 20), plus the bot's own
  funding_oi price, depth mids and validated signal entries. Each was checked against the 1h candle range to drop
  fixture prices.
- No lookahead: p0 is the last price at or before the decision. p(t+h) is the first price at or after t+h
  (stale by at most 30 min). Path and SL/TP checks only use bars that start after t0.
- e_h is the forward return in the proposed (or taken) direction minus 9 bps fees. Duplicates were removed per
  (symbol, side, decision, 1h bucket). CIs use a cluster bootstrap over (symbol, UTC day). n_eff counts distinct
  (symbol, horizon-bucket) cells. Cells with n_eff<30 are flagged.

## Per-agent table (4h horizon, net of 9 bps)
| Agent | Gradeable claim | n (n_eff) | Result | vs baseline | Verdict |
|---|---|---|---|---|---|
| Signal stream | take every signal | 2456 (987) | -14.0 bps [-23,-6], hit 44.6% | random side -12.6 | negative edge after fees |
| **Trade** (sonnet-4-6 mostly) | GO | 895 (507) | -22.4 bps [-34,-12], hit 43% | worse than take-all | **no skill / anti** |
| Trade | SKIP (proposed side) | 2085 (895) | -12.5 bps [-22,-3] | | skips "saved" money |
| Trade | GO − SKIP | | 1h -4.1 (p.23), 4h -9.8 (p.08), **12h -30.5 [-55,-10] p.002** | 0 = no skill | GOs picked the worse setups |
| Trade | confidence → outcome | 2980 | Spearman -0.045, AUC 0.486 | 0.5 | **uninformative** |
| Trade | SL-vs-TP1 first (24h) | 580 / 1734 | GO TP-first 21.7% vs SKIP 28.6% | | worse |
| Critic | implied take − no-take | 402 / 2734 | +0.4 bps [-13,+14] | 0 | noise; haiku-critic **-21 bps p.03** |
| Critic | challenged GO − approved GO | 655 / 389 | -10.8 [-26,+4.5] | 0 | weak right direction, n.s. |
| **Risk** | take − block, within trade GO | 611 / 332 | **+18.6 bps [3.5, 34.7], p.015**; 1h +9.6, 12h +25.9 | 0 | **only positive discriminator** |
| Risk | size multiplier → outcome | 611 | no monotone relation | | size is not informative |
| Quant | ev=long/short direction (gross) | 1199 (648) | -8.6 bps, hit 47.1% | always-long +0.7 | **no skill** |
| Quant | quality clean/marginal/noise | 54/493/2151 | -20.9 / -18.4 / -16.6 | | "clean" not better (clean n_eff=45) |
| Quant | confidence | 1199 | Spearman -0.05, AUC 0.47 | 0.5 | uninformative |
| **Regime** (haiku) | label vs realized next 12h | 2837 (~930 @12h) | accuracy 48.3% | shuffled labels 49.1% (p=0.88) | **no skill** |
| Regime | trend-labels vs range-labels → realized efficiency ratio | | AUC 0.491 | 0.5 | can't tell trend from range |
| Regime | trending_bull − trending_bear, 12h return | 285 / 307 | **-42 bps** [-114,+22] | >0 expected | wrong sign (labels look backward / mean-revert) |
| Regime | confidence → correct | 2837 | AUC 0.484; 0.8+ bucket 44% vs <0.6 bucket 54% | | slightly *inverted* |
| **Exit** (haiku) | hold − full_close, position-side fwd return | 787 / 1058 | 1h +0.05, 4h +1.6 [-12.5,+14.8], 12h -14 | 0 | **coin flip** (close "correct" 49.9%) |
| Scout / Overseer / Learning | | | not gradeable (no directional or verifiable claim; text truncated to 200 chars) | | |

Risk and exit confidence is a constant 0.5. Critic confidence is 0.5 on 94% of records. Confidence for these three
is uninformative by construction.

## Answers
**(a) Did SKIPs leave money on the table or save it?** They saved it, but only because nearly everything loses
after fees. The 2,085 de-duplicated skipped setups averaged -12.5 bps at 4h. Taking each one at $1,000 notional
would have lost about $2,615, and only 44.6% would have cleared fees. The GOs were worse still (-22.4 bps). So
the selection carried no value: skipping everything would have done best. By side, both LONG and SHORT GOs
underperform their skips. By symbol, NEAR GOs (-82 bps) and HYPE GOs (-41 bps) are the worst.

**(b) Is any agent's confidence informative?** No. Trade (AUC 0.486), quant (0.47) and regime (0.484) are all at
or slightly below chance. Regime's highest-confidence bucket is its *least* accurate. Risk, exit and critic emit
constant confidence. Confidence should not size anything.

**(c) Did model upgrades change accuracy?** Nothing measurable, and the comparisons are period-confounded.
- Trade: haiku and sonnet were live in the same months. July GO−SKIP was -3.5 (haiku, n=58/186) vs -9.6 (sonnet,
  n=194/501), both n.s. No month shows sonnet with positive discrimination.
- Critic: haiku had negative discrimination (-21 bps, p=.03). Sonnet was +8 (n.s.). Sonnet is not worse; neither
  is proven.
- Regime: opus scored 60% (n=58, only May 30 – early June) vs haiku 47.7%. That sample is too small and from one
  regime. Interestingly, the non-LLM `technical_fallback` scored 65.9% (n=44, flagged small).
- Quant: opus -13 vs haiku -5 bps gross, both n.s.

**(d) Which agent should be the first graded manager, and which is noise?** Make the **Risk agent's
take/block veto** the first graded manager. It is the only cell positive at all three horizons, and it held up
under critic=challenge, SHORT side and haiku-model slices. Caveats: it is concentrated in June (+54 bps) and in
HYPE/NEAR, it is negative on SOL/XRP, and about 60 comparisons were run, so roughly 3 false positives at p<.05
are expected. It needs forward confirmation before anyone leans on it. **Noise:** regime label, exit hold/close,
quant direction and quality, critic, and all confidences. **The trade agent's GO is noise or worse:** its GOs
under-performed its own skips. Note: "full desk yes" (trade go + risk take + critic approve) averaged -15.5 bps,
n_eff 252.

## Caveats
- Forward returns are counterfactual market-entry outcomes, not the bot's actual fills, trailing stops or exits.
  The 4h horizon is a proxy for the real hold.
- Proposed side is inferred: 21% of rows use text parsing. Results hold on signal-joined rows only.
- Rounds repeat every 5–15 min on the same setup. De-duplication plus cluster bootstrap handle most of this, but
  CIs may still be a bit narrow. n_eff at 12h is about half of n.
- Many comparisons were run. Treat any single p≈0.02–0.05 cell as a hypothesis, not a finding.
- All regime "truth" thresholds (efficiency-ratio median, rv p75) are per-symbol and in-sample. They are neutral
  across labels but arbitrary.
- 2026-08-10 → 09-07 is an outage gap. October is thin (n_eff<30 in most cells).

## Going forward: incremental real-time scorecard (design)
1. **Hook:** `llm/agents/performance_tracker.py::record_pipeline_run()` already sees every round. Make it
   (a) persist the proposed `side`, `entry`, `sl` and `tp1` from the signal context (today `side` is empty for
   every pipeline role, which is why this study had to join by time), and (b) set an `is_test` flag. Better still,
   make `_DEFAULT_DATA_DIR` absolute and refuse writes when running under pytest (`PYTEST_CURRENT_TEST`). That
   stops the fixture pollution at the source.
2. **Resolver:** a light task every 15 min (or folded into the existing hourly site/publish task). It tails new
   lines from a byte offset stored in `agent_grades/state.json` and appends each new decision to
   `pending.jsonl` as {record_id, ts, sym, side, role, decision, conf, model, p0}. p0 comes from the bot's own last
   depth mid at write time.
3. **Resolution:** once now ≥ ts + 12h, fetch one HL 5m candleSnapshot per symbol per run (cache the last 2 days in
   memory, never the history). Compute r1h/r4h/r12h, SL/TP-first and er/rv. Append to `resolved.jsonl` and
   drop the row from pending. Pending is small (12h × ~6 rounds/h × 6 symbols ≈ 500 rows).
4. **Aggregates:** keep running sums per (role, decision, model, symbol, month): n, Σe, Σe², hits, and a
   36-bucket confidence histogram, in `agent_grades/live_scorecard.json` (<100 KB). Rebuild bootstrap CIs nightly
   from `resolved.jsonl` (~5k rows/month, a few MB). Peak RAM is under 50 MB with no pandas.
5. **Gating:** a role "earns" authority only when its discrimination (take − block, or GO − SKIP) has a
   cluster-bootstrap lower bound > 0 at n_eff ≥ 100 forward from the start date. That fits the existing n≥30 and
   n≥13 living-value rules. Surface one line per role on the dashboard, e.g. "Risk veto: +18 bps, n_eff 332,
   provisional".

## Files
- `fetch_candles.py`: HL candle cache → `candles/` (1h full span, 15m and 5m recent).
- `build_dataset.py`: streams raw logs, filters fixtures, joins sides, computes forward outcomes →
  `graded_decisions.jsonl`.
- `grade.py`: scorecard → `scorecard.json` (full tables: by model, month, symbol, regime, side, calibration
  buckets) and `grade_output.txt`.
- `robustness.py`: risk-veto slices and the trade signal-side-only check → `robustness.json`.
- `profile.py`: raw file profile (roles, vocabularies, models by month).
