# Server audit: single points of failure in the data (2026-10-11)

This was a read-only audit. No code was changed and nothing was restarted. Sizes and timestamps come from `ls`, `du`, the first and last records of each file, `git ls-files`, `git check-ignore` and `git cat-file`.

## Bottom line

- **Disk space is not the risk.** C: has 298 GB free. `data/` is 1.8 GB (656 MB of that is `replay/` sandboxes) and `logs/` is 2.3 GB. Together they grow by roughly 5 MB/day of data plus about 100 MB/week of stdout archives.
- **The risk is that there is no off-box copy.** Almost every load-bearing dataset is git-ignored, and `laptop_sync.py` exports only about 25 small files.
- **No backup runs anywhere.** There is no backup scheduled task, and `C:\Users\vince\WAGMI` is not under OneDrive. If this disk dies, everything below marked "NO" for both tracked and exported is gone.
- **Datasets that are lost for good if the disk dies.** None of these is exported, and the source APIs keep no history:
  - Bybit liquidation stream
  - L2 depth history
  - HL whale positions
  - Hivemind voice log
  - Microcap point-in-time snapshots
  - Co-pilot forward-proof call ledger
  - The bot's own decision/rejection/counterfactual ledgers
- **`laptop_sync` has a bug that is bloating git history fast.** `gzip.open(...,"wt"/"wb")` stamps the current mtime into the gzip header. Every hourly run therefore writes new blobs even when the content has not changed. For example, `entry_gate_log.jsonl.gz` stayed at 192460 bytes but has a different blob id every commit (85e0621b, c4944fd8, 4704fca9, bb712a7c).
  - The 22 hourly commits since 2026-10-10 16:38 added **84 MB of unique blobs**. That rate is about 2.7 GB/month. The pack is already 548 MB.
  - Gzipped blobs do not delta-compress. When GitHub starts rejecting pushes, `run()` just returns "push failed" and the whole laptop pipeline stops without any alert.
- **Branch note.** The sync commits to the current branch and pushes `HEAD`, which is `desktop-overdrive-2026-05-30`, not `laptop-mining-2026-10`. The laptop branch does contain `server_exports/` (it merges them in), so this works today. It breaks if the server's checked-out branch changes.

## The 30-day ctx_snapshots export: is it trimming data the laptop hasn't archived?

**Not yet.** Only two day-files exist (2026-10-10 and 2026-10-11). Archiving started 10-10.

- The local writer (`scanner._log_ctx_snapshot`) only appends and never deletes, so the server keeps everything.
- The export keeps the newest 30 files and unlinks older ones from `server_exports/`. The first deletion will happen around **2026-11-09**.
- Every day-file is committed many times, so git history still holds it, and it is on GitHub once pushed. But the laptop's *working tree* loses it.
- **Action:** the laptop should copy `server_exports/ctx_snapshots/*.gz` into its own non-pruned archive on every pull, before 11-09.
- **Caveat:** the only copy of any day older than 30 days is then the server disk plus git history. If the 2.7 GB/month churn forces a history rewrite or squash, the git copy disappears.

## Inventory

Key to the columns:
- **Tracked:** T = in git, IGN = git-ignored (and so not in git).
- **Exported:** Y = `laptop_sync` sends it, N = it doesn't.
- **Growth:** estimated from the first and last records.

| Dataset | Size | Growth | Tracked | Exported | Refetchable? | Loss if disk dies | Action |
|---|---|---|---|---|---|---|---|
| `copilot/liquidations/liq_events.jsonl` (Bybit liquidations, since 08-01) | 18 MB | ~0.26 MB/d | IGN | **N** | **NO.** It comes from a websocket stream and Bybit has no liquidation history API. | The substrate of the **only forward-validated finding (H3)** and the liq-magnet recheck. 71 days, unrecoverable. | **#1:** export as daily gz shards |
| `market_depth_history.jsonl` (L2 depth, imbalance, OKX taker/basis, since 07-01) | 57 MB | ~0.56 MB/d | IGN | **N** | **NO.** Order-book snapshots have no history endpoint. | 102 days of depth/imbalance (DATA_WAVES, lane B IC, `agent_grades/build_dataset`). | **#1:** shard and export |
| `hivemind/whales_log.jsonl` (HL whale net positions per coin) | 0.7 MB | ~0.23 MB/d | IGN | **N** | **NO.** HL only serves current positions. | Whale-voice grading history. | **#1** |
| `hivemind/voice_log.jsonl` (every voice's reading every 15 min) | 3.9 MB | ~1.3 MB/d | IGN | **N** | **NO.** These are point-in-time readings, and the derivable parts depend on archived ctx/candles. | All voice report cards and grades: the hivemind's "earned voices" premise. | **#1** |
| `ctx_snapshots/*.jsonl.gz` (OI/premium/impact/funding for all perps) | 0.76 MB (2 days) | ~0.7–1 MB/d | IGN | Y (newest 30) | **NO.** HL has no ctx history (422s). | Recoverable from git history, but see the trim note above. | Laptop archives on pull; stop the churn |
| `candles_5m/*.jsonl` (6 coins, bars since 09-22) | 2.9 MB | ~0.16 MB/d | IGN | Y | Only the last ~17 days (HL's 5000-bar window). | Bars older than 17 days. | OK. Shard by month later. |
| `funding_oi_history.jsonl` (31 coins, since 06-06) | 10.6 MB | ~0.08 MB/d | IGN | Y (full re-gzip hourly) | Funding only (HL fundingHistory). OI and premium cannot be refetched. | Covered by the export. | Daily shards, `mtime=0` |
| `copilot/call_ledger.jsonl` + `_resolved` (forward-proof ledger, n≥20 gate) | 0.48 MB | small | IGN | **N** | **NO.** Call timestamps are the evidence. | The entire co-pilot forward-evidence record. | **#2:** add to FILES (tiny) |
| `llm/decisions.jsonl` (lineage substrate) | 56 MB | ~0.42 MB/d | IGN | **N** | NO | Every LLM decision since 05-30 (lineage tracer, mining findings). | **#3:** weekly gz offsite |
| `llm/counterfactual_resolved.jsonl` (145k rows) | 97 MB | ~0.7 MB/d | IGN | **N** (one-off laptop copy earlier) | Labels can be re-derived from candles; the skip context cannot. | Gate-kill counterfactual EV corpus. | **#3** |
| `llm/agent_performance.jsonl` | 33 MB | ~0.24 MB/d | IGN | N | NO | Per-agent decision rows (8,340-round grading). | **#3** |
| `llm/thesis_history.jsonl` | 1.1 MB | small | IGN | N | NO | Thesis archive. | **#3** |
| `trade_events.jsonl` | 55 MB | ~0.41 MB/d | IGN | N | NO | Full signal→filter→trade event stream since 05-30. | **#3** |
| `manual/sniper_rejections.jsonl` | 68 MB | ~0.51 MB/d | IGN | N | NO | 79k+ gate rejections (rej79k studies). | **#3** |
| `manual/trade_scorecards`, `sniper_signals`, `trade_lessons`, `sim_trades`, `signal_value_tracker` | ~11 MB | small | IGN | N | NO | Scorecard and lesson history. | **#3** |
| `missed_trades.jsonl` + `_resolved` | 22 MB | moderate | IGN | N | Partly (outcomes can be re-derived from candles) | Missed-trade audit corpus. | **#3** |
| `data/logs/` (`exit_closes`, `signal_outcomes`, `state_transitions.csv`, `exit_regret_scores`, `safety_events`) | 3.0 MB | small | IGN | Only `exit_decisions` | NO | Exit-regret and state history (exit-engine evidence). | **#2:** add to FILES |
| `trade_ledger.csv`, `trades.csv`, `position_journal.jsonl`, `execution_analytics.csv` | ~1 MB | small | IGN | Y | NO | Covered by the export. | OK |
| `shadow/`, `shadow_ledger.csv` | 1.6 MB | small | IGN | N | NO | Shadow-phase ledgers. | **#3** |
| `agent_grades/live/resolved.jsonl`, `live_scorecard` | 0.7 MB | ~0.2 MB/d | IGN | Y | Labels yes, inputs no | Covered. `pending.json` and `progress.json` are not exported (in-flight grades). | Add `pending.json` |
| `agent_grades/graded_decisions.jsonl` | 11 MB | static (10-07) | IGN | N | Rebuildable *only* from `llm/` + depth on this disk | Grading dataset (scripts are tracked). | Goes with #3 |
| Learned bot state (`feedback/{confidence,signal_quality,regime_feedback}`, `llm/{agent_calibration,neuroplasticity,network_learning,active_learning,agent_performance.json}`, `ic_history`, `epoch_start`, `position_state`) | <1 MB | rewritten | IGN (only kelly, graduated_rules, llm_memory, hold_time, risk_equity, `managers/rules` are T) | Only `confidence_state` | NO | All the bot's learning loops cold-start, and the epoch baseline is lost. | **#4:** add to FILES |
| Hivemind owner/AI records (`owner_exit_decisions`, `owner_plan_reviews`, `ai_plans.jsonl`, `owner_orders_state`, `voice_grades`, `geometry_shadow_state`, `journal`, `hivemind/state/`) | ~0.7 MB | small | IGN | N (`owner_plans`, `fills`, `plans`, `ai_plans.json` are Y) | NO | Owner decision history, i.e. the plan→grade loop. | **#2:** add to FILES |
| `microcap/{wash_signal,flow_signal,liquidity_snapshots,discovery_log,early_life_watchlist}` (since 08-06) | 105 MB | ~1.4 MB/d | IGN | N | **NO.** These are Jupiter/DexScreener point-in-time readings, and dead pump pools vanish. | 66 days of microcap forward data (organic-score wash flag). | **#5:** weekly gz offsite |
| `microcap/ohlcv/` (1,441 hourly CSVs) | 88 MB | static-ish | IGN | N | Partly. GeckoTerminal lookback is limited and pools for dead tokens disappear. | Microcap price history. | **#5** |
| `logs/bot_*.log` (74 files since 05-30) + `python_stdout.archive_*` (12) | 1.1 GB + 1.2 GB | ~80–200 MB/wk | IGN | Only grep-extracted gate/floor lines | NO | Raw source for any future log-mined question. The exports cover only today's grep patterns. | **#5:** weekly gz offsite (~10:1) |
| `hivemind/tg/*` (history_calls 22 MB, caller_calls_graded 4 MB, calls, track.json, price_cache 50 MB, paths) | ~80 MB | small | IGN | Anonymized aggregates only (correct) | Messages can be re-pulled from Telegram while the chats exist. **`track.json` holds the owner's star/watch curation and cannot be refetched.** | Caller grades are recomputable. Stars are lost. | **Keep local.** Copy to an encrypted local second drive or USB. Never git, never laptop. |
| `hivemind/tg/owner.session`, `hivemind/owner_token.txt` | tiny | — | IGN | N | Re-login / re-issue | Telegram auth and owner token. A credential, not data. | **Never export.** Re-login if lost. |
| `replay/` (C2t/C5p sandboxes) | 656 MB | static | IGN | N | Rebuildable | Low. The copies sit on the same disk, so they give no redundancy. | Ignore |
| `reports/majors_fullhist.json`, `cache/`, `longtail/` | ~35 MB | static | IGN | N | Yes (public candles) | Low | Ignore |

## Growth, RAM and rotation findings

- **Unrotated append-only files.** These all grow by 0.2–1.4 MB/day with no rotation:
  - `trade_events.jsonl`
  - `market_depth_history.jsonl`
  - `sniper_rejections.jsonl`
  - `llm/decisions.jsonl`
  - `llm/counterfactual_resolved.jsonl`
  - `llm/agent_performance.jsonl`
  - `missed_trades.jsonl`
  - `liq_events.jsonl`
  - `microcap/*.jsonl`
  - `hivemind/voice_log.jsonl`

  On disk this is harmless: about 5 MB/day in total against 298 GB free.
- **RAM risk.** `api_server.py`'s `/v1/counterfactuals/resolved` (around line 1483) and `/v1/signals/funnel/cost` (around line 1651) call `_read_jsonl(path, limit=0)` on the 97 MB, 145k-row `counterfactual_resolved.jsonl`. That materializes every row as a dict, likely several hundred MB of Python objects. With about 0.5 GB free, one request could OOM the box. Nothing scheduled calls these endpoints (`publish_site.py` does not), so the risk is latent.
- **Microcap watchlist rewrite.** `microcap/early_life_watchlist.json` is a single 15 MB JSON rewritten as a whole. Each load costs roughly 10× its size in RAM.
- **Unrotated stdout logs:**

  | File | Size |
  |---|---|
  | `copilot/liquidations/python_stdout.log` | 42 MB |
  | `microcap/python_stdout.log` | 23 MB |
  | `logs/api_stdout.log` | 22 MB |

  By contrast, the collector logs rotate at 5 MB × 3, and `WAGMI-LogRotate` rotates the bot's `python_stdout` weekly but never deletes the archives.
- **`laptop_sync` re-reads every log every hour.** Each run reads all 1.1 GB of `logs/bot_2026*.log`, line by line, to rebuild two gz files that are nearly identical each time. That is streaming I/O, not RAM, but it is wasted disk I/O every hour that is never needed. It should process only logs modified since the last sync and append the results.
- **`ctx_snapshots` and `candle_archive` are healthy.** Both append without trimming locally. `candle_archive` backfills at most 17 days after an outage, which is the HL limit, so any gap longer than 17 days is permanent.

## Top 5 actions (ranked)

1. **Export the unrecoverable market streams as daily gz shards.** This covers `liq_events`, `market_depth_history`, `whales_log` and `voice_log`.
   - Write `<name>/YYYY-MM-DD.jsonl.gz` with `gzip.GzipFile(mtime=0)`, and commit only *closed* days plus the current day.
   - That adds about 0.5 MB/day of gz and no rewrite churn.
   - These are the datasets whose loss would erase H3 and the hivemind voice record. Nothing else is both this valuable and this impossible to recover.
2. **Fix the export churn before it breaks the pipeline.**
   - Use `mtime=0` on every gzip the sync writes (floor, entry_gate, funding, syndicate).
   - Skip writing a file whose content hash is unchanged.
   - Move `funding_oi_history` to daily shards.
   - Make an incremental log scan (only logs with mtime newer than the last sync).
   - In the same change, add the tiny irreplaceable files:
     - `copilot/call_ledger*.jsonl`
     - `data/logs/{exit_closes,signal_outcomes,state_transitions.csv,exit_regret_scores}`
     - Hivemind `owner_exit_decisions`, `owner_plan_reviews`, `ai_plans.jsonl`, `voice_grades`
     - `agent_grades/live/pending.json`

   Without this fix the repo grows about 2.7 GB/month, and pushes will eventually fail with no alert.
3. **Ship a weekly offsite snapshot of the bot's own decision ledgers, outside the hourly git path.** This covers `llm/{decisions,counterfactual_resolved,agent_performance,thesis_history}`, `trade_events`, `sniper_rejections`, `manual/*`, `missed_trades*`, `shadow/` and `agent_grades/graded_decisions`.
   - That is about 350 MB raw, roughly 40–60 MB as gz.
   - Possible targets are a GitHub release asset, the laptop via a weekly pull, or a USB/second drive.
   - These are four-plus months of history that no API can reproduce.
4. **Add the learned-state files to the hourly FILES list.** They total under 1 MB:
   - `feedback/{signal_quality,regime_feedback}`
   - `llm/{agent_calibration,neuroplasticity_state,network_learning,active_learning,agent_performance.json}`
   - `ic_history.json`, `epoch_start.json`, `position_state.json`

   Today a dead disk means every learning loop restarts cold and the epoch baseline is gone, even with a fresh clone.
5. **Make a weekly compressed offsite copy of the microcap collector data and the raw bot logs.** Also cap the three unrotated stdout logs.
   - The microcap data is 105 MB of point-in-time snapshots plus 88 MB of OHLCV. The raw bot logs are 2.3 GB, about 230 MB as gz.
   - **Separately, keep Telegram data local.** `track.json` (the owner's stars) and the TG corpus belong on an encrypted second local drive or USB, never in git or on the laptop. Anonymized aggregates stay as they are.
   - Laptop side: archive `server_exports/ctx_snapshots` on every pull before the first 30-day trim on about 2026-11-09.
