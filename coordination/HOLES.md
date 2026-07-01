# HOLES.md — Master Hole Registry (2026-07-01/02)

Single ranked backlog of every distinct open hole, deduplicated across: WIRING_AUDIT_2026-07-01 (WA#n = that audit's own finding numbers), MORNING_BRIEF_2026-07-02 (MB), THESIS_GRADES_2026-07-01 (TG), MISSED_EV_LOCKDOWN_2026-07-01 (MEV), THESIS_AUDIT_2026-07-01 (TA), TRADE_AUDIT_2026-07-01 (TR), WIRING_INVARIANTS (WI).

**Status legend:** OPEN | FIXED-tonight (commit ref) | PARTIAL-tonight (part shipped, remainder open) | OWNER-DECISION-# (packaged as MB decision 1-6) | VERIFY-pending (should already be fixed/live; confirm on next closes).
**Lane:** AUTONOMOUS = pure measurement/logging, learning engine may fix now. OWNER-GATED = changes trading behavior; backtest + adversarial review first.

Tonight's shipped commits: fix1 partial-close accounting `27e7797` (+tests `c91c24c`), fix2 liq-avoid `7c78216`, fix3 ledger completeness `f601c72`, fix4 honest labeling `b7b8f60`, fix5 thesis side+grading `8d5cc4c` (+retro-grade `1f22f53`), fix6 dollar-aware veto retirement `664912a`, Quant Brain mute `27e7797`.

## Registry

| ID | Title | Severity | Source | Status | Lane |
|---|---|---|---|---|---|
| H1 | LLM-first entries never submit exchange orders (phantom positions; one env-flip from live catastrophe) | CRITICAL | WA#1 | OWNER-DECISION-5 | OWNER-GATED |
| H2 | Partial-close PnL black hole (qty reduced, profit leg never recorded; labels inverted) | CRITICAL | WA#2 | FIXED-tonight (27e7797, tests c91c24c) | — |
| H3 | LIQUIDATION_AVOID force-close event discarded (largest losses erased from equity/ledger/learning) | CRITICAL | WA#3 | FIXED-tonight (7c78216) | — |
| H4 | Parallel symbol scans deleted each other's closing positions mid-pipeline (11 closes → 2 ledger rows) | CRITICAL | MB fix3 / TA §2.4 | FIXED-tonight (f601c72) | — |
| H5 | Restart wipes the book — recovery loads 0 open positions; every restart orphans the book | CRITICAL | MB anomaly 1 / WI inv-8 | OWNER-DECISION-6 | AUTONOMOUS (pure correctness per MB) |
| H6 | Two equity trackers diverge ~$368 ($2318.91 persisted vs $1951.01 heartbeat); no single source of truth | HIGH | MB anomaly 2 / WI inv-5 | OWNER-DECISION-6 | AUTONOMOUS (pure correctness per MB) |
| H7 | Exit asymmetry A: no profit protection in the 0R→TP1 band (crumb wins vs full losses) | HIGH | WA#4 | OWNER-DECISION-3 | OWNER-GATED (backtest-first approved lean) |
| H8 | Exit asymmetry B: post-TP1 floor locks 57.5% of peak instantly, kills the runner (cushion-BE dead code) | HIGH | WA#5 | OWNER-DECISION-3 | OWNER-GATED |
| H9 | Exploration sizing inverse-to-stop-width, bypasses all sizing guards (the $628 XRP LONG class) | HIGH | WA#6 | OWNER-DECISION-4 | OWNER-GATED |
| H10 | Pipeline-failure skips logged as LLM vetoes / exploration entries labeled "LLM approved" (labeling half) | HIGH | WA#7 (labeling) | FIXED-tonight (b7b8f60) | — |
| H11 | Pipeline-failure skips (conf=0.0) still convertible into live exploration trades | HIGH | WA#7 (conversion) | OPEN | OWNER-GATED |
| H12 | Sizing formula divides by leverage — every leverage CAP increases notional; paths size ~7x apart | HIGH | WA#8 | OPEN | OWNER-GATED (ship with risk re-tune + backtest) |
| H13 | LLM Risk Agent risk_pct unclamped; omitted-field fallback hardcodes 10% risk | HIGH | WA#9 | OPEN | OWNER-GATED |
| H14 | All merged size modulation (Kelly, drawdown, Risk 'reduce') computed then dropped — never reaches qty | HIGH | WA#10 | OPEN | OWNER-GATED |
| H15 | risk_mult_override dropped by _merge_signals — solo/soft-veto trades execute at FULL size | HIGH | WA#11 | OPEN | OWNER-GATED |
| H16 | Time-of-day sizing applied twice; second pass inverts LONG direction (LONG/SHORT vs BUY/SELL clash) | HIGH | WA#12 | OPEN | OWNER-GATED |
| H17 | RiskFilterChain Gate 1f (win-prob floor) dead; Gate 1g runs with empty regime/num_agree/strategies | HIGH | WA#13 | OPEN | OWNER-GATED |
| H18 | LLM 'flip' silently converted to 'go' — bot would trade the direction the LLM said to reverse | HIGH | WA#14 | OPEN | OWNER-GATED |
| H19 | HOLD_LIMIT force-closes bypass exchange submission + post-trade pipeline | HIGH | WA#15 | PARTIAL-tonight (bookkeeping via f601c72; exchange submission still open) | OWNER-GATED |
| H20 | Veto auto-retire on biased hit-rate estimator; one-way door (killed vindicated hype_long_veto) | HIGH | WA#16 / TR#4 | PARTIAL-tonight (664912a dollar gate; sign-only scoring, forming-candle feed, reactivation path still open) | OWNER-GATED |
| H21 | exit_price never in metadata → Learning Agent price_move always −100%; regime calibration ledger 100% fabricated | HIGH | WA#17 | OPEN | AUTONOMOUS |
| H22 | Graduated record_outcome never passes strategy/setup_type — strategy-conditioned rules fire forever, unmeasured, unkillable | HIGH | WA#18 | OPEN | AUTONOMOUS |
| H23 | Regime recorded 'unknown'/'' on every exploration/pipeline-failure trade — regime-keyed learning collapses to one bucket | HIGH | WA#19 / TR#3 | OPEN | AUTONOMOUS |
| H24 | get_win_rate_by("strategy") pools ALL trades under 'unknown'; setup edge map injects empty-string key | HIGH | WA#20 | OPEN | OWNER-GATED |
| H25 | Thesis outcomes never graded (209/209 "pending"; loop never closed once) | HIGH | TA §2.1 / TG bug2 | FIXED-tonight (8d5cc4c auto-grade on close; 1f22f53 retro-graded 230) | — |
| H26 | Thesis recording stopped 2026-06-30 06:48 — Jul-1 trades have no thesis rows | HIGH | TA §2.1.4 | VERIFY-pending (confirm new rows post-8d5cc4c) | AUTONOMOUS |
| H27 | Confidence anti-predictive: 60–79 band 0–18% WR loses money; only 80+ trustworthy; thesis conf inverted (30–44 beats 60–74) | HIGH | TR#2 / TG conf-bands | OPEN | OWNER-GATED (recalibration changes selection) |
| H28 | Long-side structural drain: LONG n=27 15% WR −$690 both eras; HYPE LONG 12% WR −$585 | HIGH | TR#1 / TA §2.5-2 | OPEN | OWNER-GATED (directional policy = owner call) |
| H29 | Exploration epsilon, not the LLM, sets trade count (all 5 Jul-1 opens were skip→go overrides; ~7/day vs ~2/day posture) | HIGH | TA D1 / MB decision 1 | OWNER-DECISION-1 | OWNER-GATED |
| H30 | Quant Brain = hardcoded pre-filter vetoing signals before Claude, self-trained on broken ledger, anti-signal (17% WR when cited) | HIGH | MB fix7 / TA §2.5-3 / TG EV-citing | FIXED-tonight (muted, QUANT_BRAIN_ENABLED=false, 27e7797) | — |
| H31 | Quant Brain "live calibrations" silent no-op — gates on frozen 2026-06-03 table (dormant while muted) | MEDIUM | WA#21 | OPEN (dormant) | OWNER-GATED |
| H32 | Quant Brain calibrations refresh exactly once per process; refresh_calibrations() has zero callers (dormant while muted) | MEDIUM | WA#22 | OPEN (dormant) | OWNER-GATED |
| H33 | Exit Agent winner-close structurally unreachable (0.85 conf vs 0.90 gate); EXIT_AGENT_FULL_CLOSE flag a no-op for winners | MEDIUM | WA#23 | OWNER-DECISION-3 (exit geometry batch) | OWNER-GATED |
| H34 | Dead-capital carve-out = fragile keyword match on truncated text; fee-blind is_profitable exempts marginally-green stuck positions | MEDIUM | WA#24 | OWNER-DECISION-3 (exit geometry batch) | OWNER-GATED |
| H35 | Circuit-breaker size_multiplier applied twice (0.25x not 0.5x) | MEDIUM | WA#25 | OPEN | OWNER-GATED |
| H36 | Per-symbol risk_per_trade override clobbered; vol-target ATR units mismatch degenerates to constant 2x | MEDIUM | WA#26 | OPEN | OWNER-GATED |
| H37 | 0.50 risk-mult floor swallows learned long penalties; MAX_RISK_MULTIPLIER env knob never wired | MEDIUM | WA#27 | OPEN | OWNER-GATED |
| H38 | Win/loss streaks counted 3x via three parallel multipliers | MEDIUM | WA#28 | OPEN | OWNER-GATED |
| H39 | LLM-first trades a different signal than the one that passed gating (evaluate_raw re-run diverges) | MEDIUM | WA#29 | OPEN | OWNER-GATED |
| H40 | Quality multiplier applied twice via two SignalQualityScorer instances over the same state file | MEDIUM | WA#30 | OPEN | OWNER-GATED |
| H41 | Side-vocab clash in quality scoring (LONG/SHORT recorded, BUY/SELL scored) — directional learning dimension neutral | MEDIUM | WA#31 | OPEN | OWNER-GATED |
| H42 | REGIME_MIN_VOTES table dead config; min_votes always flat 2 | MEDIUM | WA#32 | OPEN | OWNER-GATED |
| H43 | LLM-first open_position omits strategy/setup_type/tp1_close_pct/mode — attribution empty for 100% of active-path trades | MEDIUM | WA#33 / TR#3 | OPEN | AUTONOMOUS |
| H44 | Exploration skip→go mutation poisons coordinator entry-decision cache (mutated GO replays up to 3 min) | MEDIUM | WA#34 | OPEN | OWNER-GATED |
| H45 | Structured-debate Critic R1 schema mismatch — 'challenge' verdicts can't veto or reduce confidence | MEDIUM | WA#35 | OPEN | OWNER-GATED |
| H46 | Structured debate bypasses CLI routing (raw call_llm) — has never run under the subscription setup | MEDIUM | WA#36 | OPEN | OWNER-GATED |
| H47 | Quant-noise 50% size reduction written to a key nobody reads (trade_out.data['sm']) | MEDIUM | WA#37 | OPEN | OWNER-GATED |
| H48 | Invalid LLMDecision constructors — Tier-1 routing skip and budget-exceeded return crash with TypeError | MEDIUM | WA#38 | OPEN | AUTONOMOUS |
| H49 | CLI adapter forces every agent timeout to >=300s, nullifying per-agent timeouts + 90s Sonnet→Haiku fallback | MEDIUM | WA#39 | OPEN | AUTONOMOUS |
| H50 | Exploration/pipeline failures recorded llm_agreed=true GO — poisons LLM-accuracy splits | MEDIUM | WA#40 | FIXED-tonight (b7b8f60) | — |
| H51 | Close-path learning block 100% dead (3 signature-mismatched calls swallowed at debug); split-brain feedback instances | MEDIUM | WA#41 | OPEN | AUTONOMOUS |
| H52 | BOOST/PENALIZE confidence deltas applied 2-3x per signal, accuracy credited once | MEDIUM | WA#42 | OPEN | OWNER-GATED |
| H53 | predicted_ev/realized_rr/win dropped by trade_ledger schema; realized_rr computed on zeroed qty — the QB calibration data never landed | MEDIUM | WA#43 | OPEN | AUTONOMOUS |
| H54 | MFE force-closes flip state to CLOSED before exchange fill confirmation | MEDIUM | WA#44 | OPEN | OWNER-GATED |
| H55 | Funding-rate units clash: HL hourly funding treated as per-8h in Quant Brain (thresholds ~8x too strict) | MEDIUM | WA#45 | OPEN | OWNER-GATED |
| H56 | Graduated-rule live-accuracy recompute can never score strategy-conditioned rules (trades.csv strategy empty) | MEDIUM | WA#46 | OPEN | OWNER-GATED |
| H57 | Deep-memory 'SIDE EDGE' prompt section can never render (_BUY/_SELL lookup vs _LONG/_SHORT store) | MEDIUM | WA#47 | OPEN | OWNER-GATED |
| H58 | Absent collectors misrepresented as calm market conditions; funding staleness threshold 8x cadence, no age tag | MEDIUM | WA#48 | OPEN | OWNER-GATED |
| H59 | Thesis `symbol` field wrong on ~40 records (says BTC, text is ETH/SOL/HYPE; entry_price is wrong asset's) | MEDIUM | TG bug3 | OPEN | AUTONOMOUS |
| H60 | Duplicate thesis spam — one stub ("SOL breaking below key support…") written 63x; "trend aligns" 5x | MEDIUM | TG bug4 | OPEN | AUTONOMOUS |
| H61 | funding_oi_history.jsonl 536-hour gap (Jun 7 08:52 → Jun 29 17:10); root cause unestablished (window matches the June blackout — collector likely died with the host and has no watchdog/backfill) | MEDIUM | TG source note | OPEN | AUTONOMOUS |
| H62 | setup_type 100% "unknown", target_price/expected_hold_h 100% null on theses (root: entry_reasons never writes setup_key) | MEDIUM | TA §2.1.3 (roots in WA#21/#33) | OPEN | AUTONOMOUS |
| H63 | hype_long_veto restore under corrected dollar accounting (saved money: HYPE LONG 12% WR −$585; HYPE theses 18% right) | MEDIUM | MB decision 2 / TR#4 / TG by-symbol | OWNER-DECISION-2 | OWNER-GATED |
| H64 | High-ADX trend-continuation entries (the one survivor of missed-EV + thesis grading) — forward-test before encoding | MEDIUM | MEV survivor / TG best-10 | OPEN | OWNER-GATED (backtest-before-adding) |
| H65 | Dormant datasets: collected data written but never consumed (ungraded theses now fixed; counterfactual dollars, etc.) — RECALL layer build | MEDIUM | WI inv-7 | OPEN (scheduled after 15-20 clean closes) | AUTONOMOUS |
| H66 | Trade Agent never emits 'side' — thesis metadata always BUY (209/209) | LOW (was the visible face of H25/H59) | WA#49 / TA §2.2 / TG bug1 | FIXED-tonight (8d5cc4c, side derived truthfully at record time) | — |
| H67 | Mechanical overrides recorded as the Trade Agent's own decisions | LOW | WA#50 | OPEN | AUTONOMOUS |
| H68 | LLM_EXIT_ENGINE full closes: TradeEvent discarded, missing from _FULL_CLOSE (was latent) | LOW | WA#51 | FIXED-tonight (f601c72) | — |
| H69 | AdaptiveConfidenceFloor: two instances clobber the same state file | LOW | WA#52 | OPEN | OWNER-GATED |
| H70 | Confidence-floor bypasses overwrite risk_mult_override instead of combining | LOW | WA#53 | OPEN | OWNER-GATED |
| H71 | Override-agent volume_ratio hardcoded by broken dir() check; close-path confidence fallback mixes 0-1 and 0-100 scales | LOW | WA#54 | OPEN | AUTONOMOUS |
| H72 | CLI route zeroes all token/cost accounting — quota-burn visibility blind on the production path | LOW | WA#55 | OPEN | AUTONOMOUS |
| H73 | Regime cache stores mutable AgentOutput mutated in place by the technical fallback (30-min poisoned cache) | LOW | WA#56 | OPEN | OWNER-GATED |
| H74 | decision_engine multi-agent success marker overwritten (dormant, double-billing risk if flags enabled) | LOW | WA#57 | OPEN | AUTONOMOUS |
| H75 | Stop-width leverage caps dead code; unknown symbols get max-tier Kelly leverage by dict-miss | LOW | WA#58 | OPEN | OWNER-GATED |
| H76 | TP1 partial-close can widen pos.sl (never-widen violation; masked by trailing at current config) | LOW | WA#59 | OPEN | OWNER-GATED |
| H77 | get_trade_summary drops LLM/TIME_STOP/TP1_FULL closes; trailing WINs logged as SL_HIT; gated exits skip mark_evaluated | LOW | WA#60 | OPEN | AUTONOMOUS |
| H78 | Funding costs deducted from learning PnL but never from equity | LOW | WA#61 | OPEN | OWNER-GATED |
| H79 | record_veto_overridden dead code — LLM veto-overrides never scored | LOW | WA#62 | OPEN | AUTONOMOUS |
| H80 | Quant Brain dead wires: vol-regime confluence unreachable, RSI note overwritten, fictional 48% floor in skip reason (dormant while muted) | LOW | WA#63 | OPEN (dormant) | OWNER-GATED |
| H81 | CWD-relative data paths in prompt_enricher/deep_memory/quant_brain — enrichment silently empties from other launch dirs | LOW | WA#64 | OPEN | AUTONOMOUS |
| H82 | XRP traded 2x but has zero theses — per-symbol thesis capture gap | LOW | TA §2.1 | OPEN | AUTONOMOUS |
| H83 | EV_AND_MISSED.md headline table is a W1 artifact — annotate so it is never acted on as written | LOW | MEV action 4 | OPEN | AUTONOMOUS |
| H84 | Thesis time horizons systematically too short (37% right at +6h vs 54% at +12-24h) — prompt guidance mismatch | LOW | TG bottom line | OPEN | OWNER-GATED |

**Refuted — do not re-chase** (verified false in WA appendix): exploration risk=1/leverage premise; LLM size-mult leaking into ADVISORY/VETO_ONLY; inconsistent notional definitions between paths; critic calibration polarity inversion.

## Owner-decision map (MB's 6 decisions → holes)
1. Exploration policy (tiny-size / labels-only / suspend) → H29 (+ touches H11, H44)
2. hype_long_veto restore → H63 (under H20's corrected math)
3. Exit geometry backtest-first → H7, H8 (+ H33, H34)
4. Exploration sizing through risk_mgr.calculate_qty → H9
5. LLM-first exchange submission → H1
6. Restart book-wipe + equity reconciliation → H5, H6

## Live verification pending (next closes must show)
One trades.csv row per close on any path (H4), truthful entry_type (H10/H50), partial-close rows with equity moves (H2), `[THESIS] Graded` log lines (H25), pnl_saved/pnl_missed accruing on vetoes (H20), no more conf=0% ML records, thesis rows resuming (H26).

## Counts
Total distinct holes: **84**. FIXED-tonight: **9** (H2 H3 H4 H10 H25 H30 H50 H66 H68). PARTIAL-tonight: **2** (H19 H20). VERIFY-pending: **1** (H26). Packaged as owner decisions: **10** (H1 H5 H6 H7 H8 H9 H29 H33 H34 H63). OPEN: **62** — of which **22 AUTONOMOUS** (H21 H22 H23 H43 H48 H49 H51 H53 H59 H60 H61 H62 H65 H67 H71 H72 H74 H77 H79 H81 H82 H83) and 40 OWNER-GATED.

## Next 5 autonomous burns (top OPEN+AUTONOMOUS, ranked by learning/PnL impact)
1. **H21 (WA#17) exit_price −100% everywhere** — two one-liners: `_exit_price_close = event.price` at multi_strategy_main.py:3970 and reflection `exit_price=event.price` at :3914; unbreaks the (currently 100% fabricated) regime calibration ledger and per-close lessons.
2. **H23 (WA#19) regime 'unknown' on all current-posture trades** — at the recording seam, fall back to trade_ledger regime_1h / market_context / signal-metadata regime when entry_decision.regime is empty; verify on next trade row.
3. **H22 (WA#18) strategy never passed to graduated record_outcome** — add `strategy=event.strategy` (+setup_type) through record_outcome → matches(); makes the 5 strategy-conditioned rules measurable and the auto-retire kill-switch reachable.
4. **H43 (WA#33) LLM-first open_position attribution void** — add strategy/mode/setup_type/tp1_close_pct to the open_position call at multi_strategy_main.py:8017; unblocks regime_feedback, confidence_floor, strategy weighting for 100% of active-path trades.
5. **H53 (WA#43) predicted_ev/realized_rr/win never land in the ledger** — add the three LEDGER_COLUMNS, compute from event.qty/original_qty (not the zeroed pos.qty), fix the zeroed-qty funding calc at :4087-4089; this is the predicted-EV-vs-realized calibration dataset the Quant Brain audit needs.

Close behind: H59/H60 (thesis symbol + dedup — grading data quality), H51 (delete dead learning block / single feedback instances), H61 (funding_oi collector root-cause + watchdog).
