# WAGMI Knowledge Map

_Compiled 2026-10-12 by a server Opus agent (read-only synthesis); saved by server Claude 2026-10-13. Shared spine for
both machines: when a question closes, amend its row (laptop: send the row in a reply and the server folds it in).
Sources: [mem:X] memory note, [L:X] laptop branch file bot/data/laptop_mining/X, [S:X] server file, [live:X] server
output in bot/data/hivemind/ read 2026-10-12 ~22:00Z. ⚠ = unverified or sources disagree._

## 1. Where we are

WAGMI is a **paper-trading bot** on Hyperliquid perps, LLM-first (Claude via the `claude -p` subscription), on the
server PC with six symbols (BTC, ETH, SOL, HYPE, XRP, NEAR). It is **almost flat on purpose**: 274 trades closed
Jun–Aug, only 19 in Sep–Oct, nearly all 0.1x probes [L:LONG_SIDE.md]. Corrected lifetime P&L is slightly negative,
almost all of it July (−$317) [L:REGISTER.md §6].

Around the bot, the **hivemind** runs a 15-minute cycle of collectors, graders and an Opus "chief", feeding the
**WAGMI Terminal** (HL-style page, 12 tabs) and a Telegram listener for meme-coin calls. A **research laptop** red-teams
everything under sealed pre-registrations and runs an hourly token-free crunch layer.

**What has shown an edge:** nothing directional. ~98 direction tests, none big enough to clear detection floors (mostly
> 90%/yr). "No LLM agent predicts price": across 8,340 forward-graded rounds, skip-everything beat every agent
[mem:project_mining_findings_2026-10-07].
**What survived:** how BIG moves will be, not which way - move size is forecastable; crowded funding means a bigger
day and more stop hits; tightening stops hurts.
**What is dead:** buying every meme call, trailing exits, wider-stop recipes, cross-sectional ranking, liquidation
magnets, confidence floors.

## 2. System map

### 2a. The bot (`run.py paper`, Task Scheduler "WAGMI-Bot" + supervisor; `auto_restart=False` on purpose)
| Stage / gate | What it does | Data | Consumed by |
|---|---|---|---|
| Strategy ensemble | Strategies vote each scan | trade_events.jsonl (SIGNAL_GENERATED) | IC gate |
| **IC gate** (silent mute) | Drops votes from 5 strategies whose record runs backwards; ~99.8% of votes dropped [live:decisions.json] | ic_dropped_resolved.jsonl | Laptop BLOCKED_PROPOSALS; card "ic-gate" |
| **LLM-first dispatcher** (LLM_FIRST_MODE=true) | Agents (Opus trade/critic) decide; risk veto | llm/decisions.jsonl, agent_performance.jsonl | Bot; laptop LLM_PIPELINE |
| Confidence floor | **INERT since June** (LLM-first returns before it) [mem:project_plans_scanner_2026-10-09_day] | floor_decisions_log | Logged only |
| **[ENTRY-GATE]** | Blocks solo_below_breakeven, long_drain_non_uptrend | entry_gate_log.jsonl.gz | Bot; drought diagnosis |
| **BLOCKED_GO probes** | 35% of blocked entries at 0.1x | trade ledger | Keeps the ledger learning [mem:project_drought_diagnosis] |
| Sizing | SIDE_LEVEL_EDGE (longs x0.25, shorts x1.5), LONG_REGIME_VETO, Kelly | ledger | Bot |
| Exits | PM: TP1/TP2, trail, breakeven, hold limit; LLM exit agent tighten_sl/close; credit saver EXIT_AGENT_LOCKED_COOLDOWN_S=3600 (ON) | exit_decisions.jsonl, exit_closes | Bot; E2/E2b |
| ADAPTIVE_STOPS | Stop from forecast move at equal $ risk. Merged, OFF | — | Waits on laptop |
| **Owner-plan exec** (OWNER_PLAN_EXEC=true) | Paper-opens the owner's plans; per-plan exit_mode (profits_only default) merged 10-13, held at bot_manages by OWNER_PLAN_EXIT_MODE_FORCE until laptop OK | owner_fills.jsonl | Plans / Trades tabs |
| Close handler → ledgers | trade_ledger.csv (stop_initial/tp1/tp2 since 10-10), trades.csv, position_journal.jsonl | exported hourly | Every study |
| Opus rules manager | Avoid/favor rules graded forward: 6 testing, 0 earned [live:decisions.json] | managers/rules | Decision card |

### 2b. Hivemind cycle (`tools/hivemind/run_cycle.py`, 15 min; `--chief` every 4h)
| Job | Does | Output | Consumer |
|---|---|---|---|
| _uptime_ping | alive / llm_ok / can_trade; phone alert after 20+ min bad | uptime.jsonl, tg/outbox.jsonl | Owner phone; laptop j4 |
| voice_grader (4h) | Grades each voice (history since 2020 + live) | voice_grades.json | Voice trust |
| whales.snapshot | ~60 profitable non-MM HL accounts → net position per coin | whales_log.jsonl | Voice. **Never analysed** [L:LAPTOP_REPLY_106] |
| assemble | 19 voices per coin | state/<SYM>.json, voice_log.jsonl | Chief, desk, terminal |
| chief (4h) + resolve | Opus read per coin, graded | chief_calls.jsonl, chief_scorecard.json | Calls & chief tab |
| geometry_shadow | Every signal under 3 stop geometries | geometry_shadow*.json | "bot-stops" card |
| phone_link / journal | Tunnel URL to phone / grades owner's HL fills (disabled: no address) | journal.json | Journal tab |
| scanner (+scan_grader, expmove_grade) | Top-60 perps: exp_move, flags, safe lev; ctx snapshots for all 178 perps | scan.json, ctx_snapshots/, scan_grades.json, expmove_grades.json | Scanner/Screener, planner, ai_plans |
| plans.resolve | Grades owner plans on 5m (stop wins ties, 48h, 9 bps) | plans.json | Plans tab |
| tg_track / call_snapshot | 7-day tracker per Syndicate call / on-chain state at call time | tg/track.json, call_snapshots.jsonl | Calls tab; Mission Z |
| candle_archive / depth_all | 5m candles for 6 coins / L2 depth for all 178 perps | candles_5m/, depth_all.jsonl | Laptop j1 |
| entry_mom / stop_shadow | 24h momentum at each fill / 5m shadow stops 1.0/1.5/2.0x exp_move | entry_mom.jsonl, stop_shadow.json | Sealed preregs |
| ai_plans | Opus 0–2 swing ideas every 4h (was 11.5h) with OI/depth/crowding context + owner watchlist | ai_plans.json | Plans tab |
| history / decisions / desk | Milestones & curves / decision cards / page builds | history.json, decisions.json, terminal.html | Owner |
| laptop_sync | Hourly export + push of server_exports/ and bulk/ shards | laptop branch | Laptop |

### 2c. Terminal tabs
Brief ("Do this now"), Trades, Screener, Scanner, Plans, Positions, Journal (idle), Calls & chief, Levels, Voices,
History, Lab.

### 2d. Telegram listener (`tg_listener.py`)
Reads the owner's chats read-only as his account; memecard to Saved Messages per contract; logs tg/calls.jsonl (live
tracker only). History studies come from tg_history.py (full chat history), not the listener. Heartbeat every 10 min;
stall watchdog restarts it after 3h silence. Raw message text never leaves the server.

### 2e. Laptop crunch layer (WAGMI-LaptopCrunch, hourly, no tokens) [L:crunch/STATUS.md]
j1_panels (exports → panels.sqlite), j2_trackers (running n per prereg, no stats), j3_replications (live flags + chief
Brier on out-of-sample days; no verdicts before 2026-12-10), j4_integrity, j5_backfill (1h + funding for 178 perps,
5m for top 60), j6_archive (permanent copies of server streams), j7_bulk (bot-history shards). Also megacalls_fetch.py
pricing 2,477 Telegram calls (38% done, ~16h ETA as of 10-12) [L:LAPTOP_STATE.md].

## 3. Knowledge ledger

### Entries / direction
| Question | Verdict | Key number | Source | Changed |
|---|---|---|---|---|
| Any LLM agent predicts price? | REFUTED | skip-all beat every agent, 8,340 rounds | [mem:mining_findings_10-07] | Value moved to vetoes/exits |
| Price history predicts direction? | UNDERPOWERED | ~98 tests; MDE > 90%/yr | [L:REGISTER §6], [L:NULLS_AUDIT] | Terminal leaves direction to owner |
| Pipeline win_prob / EV rank its own trades? | REFUTED | ρ −0.096 / −0.044 | [L:LLM_PIPELINE] | Nothing yet |
| LLM confidence runs backwards? | OPEN (suggestive) | −21 / −24 pts win-rate above median, Jun & Jul | [L:LLM_PIPELINE], [L:TP1_SCREEN], [L:CONF_FLOOR] | "Don't size up on confidence" |
| Higher confidence floor helps? | REFUTED | shuffled confidence did as well; floor inert | [L:CONF_FLOOR] | None |
| Bot too picky (skipped signals)? | UNDERPOWERED / negative | pooled +21 bps, day-weighted −18 bps | [L:SKIPGATE] | Keep gates |
| Keep the IC gate? | KEEP | dropped signals −0.20% each (530) | [live:decisions.json] | Stays |
| Blocked proposals worth taking? | UNDERPOWERED | 0 of 22 groupings | [L:BLOCKED_PROPOSALS] | None |
| Counter-trend entries lose more? | RETRACTED | momentum measured at close | [L:LAPTOP_STATE §4] | Forward prereg ENTRY_TIMING |
| Long-side drain | PROVEN, historical | June/July only | [L:LONG_SIDE] | SIDE_LEVEL_EDGE |
| 50d pullback as a trade | REFUTED | 724 cases ≈ random | [live:milestones] | Context only |
| Tailwind gate | REFUTED | 70.6% → 50% entry-time-safe | [mem:edge_instruments] | Not built |
| Voice agreement as direction | REFUTED | 0/34 voice×regime survive | [mem:hivemind] | Size gauge |
| RSI mean reversion | REFUTED (backwards) | −236 bps/5d | [live:voice_grades] | Trust "backwards" |
| Chief direction skill | OPEN (10-16) | 122/122 NEUTRAL; Brier 0.2508 vs 0.1956 base-rate | [live:chief_scorecard], [L:CHIEF_GRADEABLE] | Prompt asks p_up |
| Cross-sectional 1d ranking | REFUTED | fees 0.36%/day = the null | [L:CROSS_SECTIONAL] | None |
| Intraday reversal | PROVEN, untradeable | 16/16 cells; max 5.2 vs 36 bps fees | [L:INTRADAY_DISP] | None |
| Basis / funding carry | REFUTED | 1–2.5%/yr | [L:BASIS_TRADE] | None |

### Exits / stops
| Question | Verdict | Key number | Source | Changed |
|---|---|---|---|---|
| Tighten the stop? | PROVEN harmful | −0.13 to −0.20R at ½x | [L:GEOMETRY_V3] | Planner never tightens |
| 2x stop / 0.5R / 48h | REFUTED | GBM reproduces 95% | [L:GEOMETRY_V3] | Withdrawn |
| Widen the bot's stop (real trades) | UNDERPOWERED | +0.19R vs MDE 0.81R | [L:X2_STOPWIDTH] | ADAPTIVE_STOPS OFF |
| Exit-engine tightening (E2/E2b) | NO FINDING | both absorbed by no-edge control | [L:E2_TIGHTEN], [L:E2B_ABSRET] | Owner-plan exit mode = preference |
| Exit-engine tightening, descriptive (server) | 76% to < 0.5x exp_move; 6/66 cost cases, 5 in < 0.5 bucket | | [S:SERVER_REPLY 23:10Z] | Owner chose "Profits only" |
| Trailing exit | REFUTED x5 | −0.02 to −0.04R | [L:TRAILING_EXIT], [L:MISSION_XZ] | None |
| "Exit agent is the leak" | REFUTED | its closes +0.037R | [L:EXIT_AGENT_REPLAY] | None |
| Never close before TP1 | REFUTED | 23/29 would hit stop | [L:EXIT_RULE_VERDICT] | None |
| Breakeven ratchet | REFUTED | −$126 to −$485 | [mem:capture_winners] | Shadow only |
| 16-cell exit grid (Mission X) | UNDERPOWERED | 0/16 positive; MDE 218–272 bps | [L:MISSION_XZ_SYNTHESIS] | stop_initial logging |
| Bot's actual stop width | OPEN | 0.43–0.47x exp_move (~1.66%) | [L:X2], [L:MISSION_XZ] | Never tested directly |

### Sizing / volatility
| Question | Verdict | Key number | Source | Changed |
|---|---|---|---|---|
| Move size forecastable (HAR)? | PROVEN (historical) | 22/22 walk-forward | [L:VOLATILITY_V2] | exp_move everywhere |
| funding_hot → bigger day | PROVEN | +7.7%, t 3.28 | [L:SIZE_FLAGS] | Scanner/planner warning |
| funding_hot → more stop hits | PROVEN, definition-sensitive | +2.68 pp, t 3.04 | [L:FUNDING_STOP_AUDIT] | Planner warning; NOT in bot sizing |
| Crowded shorts | UNDERPOWERED | +2.56 pp, t 1.59 | [L:CROWDED_SHORT] | None |
| Funding persistence | PROVEN | 99.3% top quintile | [L:M10_AUDIT] | Context |
| volume_surge as size signal | REFUTED | p 0.0265 vs 0.025 | [L:SIZE_FLAGS] | Pulled from Scanner-now; ⚠ check other displays |
| vol_expanding | REFUTED / maybe opposite | OOS day diffs −10.5, −1.8, −1.0% | [L:crunch/REPLICATIONS] | Tooltip reworded |
| Safe leverage p99 | FIXED | sample max at n=68 | [L:M9_AUDIT] | ÷1.15 / p95 |
| Liquidation clustering (H3) | PROVEN, narrow | BTC/SOL/FARTCOIN ~¼ of headline | [mem:h3_verified] | Context |
| Liquidation clusters as magnets | REFUTED | pooled +3.4 pts, CI spans 0 | [L:LIQ_MAGNET_REVIEW] | None |
| ADX gate tuning | UNDERPOWERED | 92.5% of flow discarded at 60 | [L:ADX_GATE] | Left at 10 |

### Scanner flags
| Flag | Verdict | Source |
|---|---|---|
| ma50_pullback | Null as a trade; forward n=43, MDE 0.92% | [L:LEVELS], [live:scan_grades] |
| on_20d_low | UNTESTED; forward MDE 6.9% | [S:SERVER_AUDIT_CLAIMS] |
| squeeze | Measures stretch, not agreement; never fired in 3 OOS days | [L:SQUEEZE_V2], [L:REPLICATIONS] |
| momentum_small | Strong in-sample REVERSAL (−14.85%/72h vs peers at ≥8% above 20d high, z −6.1); forward prereg sealed; ⚠ live flag population differs from tested | [L:SMALLCAP_CORRECTION] |
| scan_grader gate | n≥30 can't detect; needs ~300 | [L:SCAN_GRADER_POWER] |

### Meme calls (Syndicate / DTN)
| Question | Verdict | Key number | Source | Changed |
|---|---|---|---|---|
| Buy every call, any target | REFUTED | −9.8 to −10.8%/call at 24h/7d/14d; hold −45% | [L:LAPTOP_STATE §3] | Calls line |
| Costs | PROVEN prohibitive | ~4% at $100 up to 78% at $2k RT | [L:LAPTOP_STATE §3] | Terminal |
| Pick winners at call time | REFUTED | 17 stats, 300 calls | [L:MISSION_XZ], [live:milestones] | None |
| Moonbag vs sell-all | UNDERPOWERED | 20 missing calls flip sign | [L:SYNDICATE_MOONBAG] | Re-check at ~3x calls |
| Re-called coins | UNDERPOWERED | re-call entry worse (n=25) | [S:SERVER_REPLY 05:00Z] | Prereg RECALL |
| Star callers (DUBI 17/18 @1.5x) | OPEN | thin after multiplicity | [live:milestones] | ★ on cards |
| Sonnet call verdicts | OPEN | 10 logged | [mem:session_10-11] | v3 calibrated |

### Data integrity (fixed unless noted)
Leverage double-count in P&L; tests writing into live data (~4,000 writes); 694 test-suite rows in position_journal;
grader 4h-not-12h window; R denominator x leverage; GeckoTerminal token-side bug; HL default-funding ties; ENTRY_TIMING
look-ahead; silent outages (now alarmed); Telegram listener decorator bug (10-11, ~10h lost). **Not fixed:** 2
wrong-signed pre-July ledger rows - pre-07-24 P&L fields untrusted.

## 4. Open threads
| Thread | Reads out | Now | Source |
|---|---|---|---|
| Chief re-test (Brier) | 2026-10-16 | Brier 0.2508 > base-rate 0.1956 | [L:CHIEF_GRADEABLE] |
| CALLER_FORM + CHAT_QUALITY | once, at fetch completion or 2026-10-20 | fetch 38% | [L:LAPTOP_STATE] |
| RECALL_CROSSCHAT | n ≥ 250 | 35 | same |
| STOP_SHADOW (GBM amendment) | n=150 or 2027-04-12 | ~2 entries/day | same |
| PREREG_OI | interim n_days ≥ 106 (~2027-01-24 ⚠ REGISTER says ~2027-03); full ~2027-05-11 | 1 day | [L:crunch/TRACKERS] |
| PREREG_IDEAS | interim n=87; full n=196 | 4 ⚠ server stats say 1 | [L:TRACKERS] |
| PREREG_ADOPT | both arms ≥ 44 | adopt=1 | same |
| PREREG_ENTRY_TIMING | 60 counter-trend trades | counting | [L:PREREG_ENTRY_TIMING] |
| PREREG_SMALLCAP_FADE | 150 events / ≥30 days | counting | [L:PREREG_SMALLCAP_FADE] |
| j3 replications | not before 2026-12-10 | 3 OOS day-blocks | [L:REPLICATIONS] |
| Mission A (wider stops, real exits) | ~30 rows with stop_initial (~60 days) | 1 | [L:REGISTER §3] |
| TP1 question (8.5% reach it) | ~50 logged closes (~100 days) | — | same |
| expmove_grade | ~16 day-clusters | 1 | [live:expmove_grades] |
| Owner-plan "Profits only" | laptop red-team → remove FORCE line in .env | code merged 10-13 | [S:SERVER_REPLY] |
| OI/premium as size predictor | laptop prereg | proposed | [L:LAPTOP_REPLY_106] |
| Owner HL address → journal | owner pastes it | disabled | [live:journal.json] |
| Decision cards | ⚠ credit-saver card stale (already ON in .env); ⚠ geometry_shadow "confirmed live" has no GBM control | | [live:decisions.json] |

## 5. Untapped potential (ranked by expected value)
1. **The only proven edge never reaches the bot.** funding_hot (+2.7 pp stop hits, +7.7% move) and HAR exp_move live
   only in terminal tooltips; core/ and execution/ never use them (only the OFF ADAPTIVE_STOPS path touches the
   forecast). Registered action "size down on crowded-funding days" [L:REGISTER §1] was never built as a flag-gated
   multiplier. Highest EV: red-teamed and risk-reducing.
2. **Every new collector measures positioning/liquidity, and every survivor is a magnitude result.** OI/premium/impact,
   depth_all, whales, Bybit liquidations (71,816 rows), H3. Re-use SIZE_FLAGS' winning shape (178-coin daily panel,
   outcome |move|/exp_move) for each as a size predictor; one prereg across all five with Bonferroni → a
   "risk-of-big-day" score feeding (1). liq_events and whales never analysed beyond H3 / magnets.
3. **The bot's stop is a third of a normal day's move, and nobody has tied the stop findings together.** Bot stop
   0.43–0.47x exp_move; 76% of tightenings < 0.5x; 1h bars contradict 22% of stop-outs; funding_hot raises stop hits;
   "don't tighten" proven. One "stop-in-noise" prereg on the 5m shadow with GBM control would unify four studies that
   each fail for power.
4. **Point-in-time microcap data could unblock Mission Z now.** microcap/{wash,flow,liquidity,discovery} since 08-06,
   un-backfillable, reaches no decision; Syndicate calls start 08-24 - any contract the microcap pipeline saw before
   its call already has look-ahead-free call-time features. Plus 15,539 tg_card_snapshots. ⚠ Overlap unchecked.
5. **Redirect the chief's Opus tokens:** grade its expected_move_pct against HAR (expmove_grade machinery) - a contest
   it could win, gradeable in weeks; if it can't beat HAR, cut the 4-hourly Opus spend.
6. **"Attention fades" appears in three datasets** (small caps −15%/72h after ≥8% breakouts; meme calls −10%/call;
   intraday 16/16 reversal) but was never stated as one thesis. Meme coins can't be shorted; HL perps can. Align the
   live scanner flag with the tested population so it feeds the SMALLCAP_FADE prereg for free.
7. **Confidence inversion is free to test forward** - seal a prereg on llm_confidence vs outcome now.
8. **Forgotten 10-07 leads:** risk-veto +18.6 bps (provisional), Overseer SLICE avoid-rules 8/11 right, never applied
   [mem:mining_findings]. ⚠ Status unknown; could seed the Opus rules manager.
9. **The owner's own fills** - one public-address paste turns his real trading into graded data.
10. **Off-box resilience** - the laptop is the only off-PC copy of un-backfillable streams and the 208-day 1h panel.

## 6. How it ties together
1. "No direction edge" is why the terminal leaves direction to the owner and sells SIZE (exp_move stops, safe lev,
   funding_hot). If a direction test survives, revisit the Brief/playbook.
2. The confidence floor is inert, so the real gates are IC gate → LLM skip → ENTRY-GATE → probes; if LLM_FIRST_MODE is
   ever turned off, the floor goes live and CONF_FLOOR/SKIPGATE must be re-read.
3. ENTRY-GATE is right on evidence but froze learning → 0.1x probes → Sep–Oct P&L carries no information → every
   forward study waits 2–3 months at ~0.5 closes/day.
4. The low trade rate is why the project manufactures forward data (stop_shadow, geometry_shadow, scan_grader,
   entry_mom, ai_plans, owner plans). Raising the probe rate would speed every prereg - an owner strategy call.
5. HL default-funding ties are why funding_hot is strictly above the 80th pct; change the definition and FUNDING_STOP
   no longer applies.
6. GEOMETRY_V3's GBM placebo is why wider stops stay OFF. ⚠ geometry_shadow.json still prints "confirmed live"
   (+0.268R) with NO GBM control and the decision card quotes it - re-check before acting.
7. exp_move has three definitions; production is volforecast.py. Every stop study, safe lev, stop_shadow arm and
   coin advice scale with it.
8. Meme-call results are why the Calls tab says "don't buy every call" and why "which calls" moved to caller form /
   chat quality / re-calls (10-20 readout), via the identity-free handoff.
9. megacalls_paths.jsonl is append-only and caused two corrections - consumers must dedupe by contract address.
10. The corroboration rule is why ADAPTIVE_STOPS, the exit mode and any funding_hot sizing need laptop SUPPORT;
    display and grading changes don't.
11. Un-backfillable streams are why collectors run before questions exist; if one dies its prereg loses data forever -
    j4_integrity flags must be read.
12. SIDE_LEVEL_EDGE / LONG_REGIME_VETO came from the June/July long drain (one era) - cut by month before revisiting.
