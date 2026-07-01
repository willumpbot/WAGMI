# MASTER PLAN — WAGMI + Louis Lane (Fable 5, 2026-07-01)
Plan produced by Fable 5 with in-code verification (not just audit docs). Full agent output preserved below in condensed form.

## New evidence verified in code
1. **Capture leak is LIVE, not legacy** — 4 of last 12 closes unlabeled (conf=0, blank driver/regime/thesis); regime="unknown" dominates since 6/26; `strategy` blank on all 89 rows. Likely cause: exit-agent/time-stop close branches bypass the labeled path (the conf=0 rows share sl=False, tp1=False).
2. **Profit-taking asymmetry signature** — recent wins exited sl_hit=True, tp1_hit=False (stop moved to ~BE, tagged before TP1); losses ran full stop. Only 1 of last 10 reached TP1→TRAILING. Geometry problem: BE-move too early or TP1 too far.
3. **Sizing inversion is mechanical** — leverage.py:254 `qty = risk_usd/(stop_width × leverage)`: notional inversely proportional to stop width → tight-stop longs get 2.5x notional automatically. Risk-parity per trade, dollar exposure concentrates wherever stops are tightest.
4. **Veto retire PnL-blind** — graduated_rules.py:456 retires on `times_applied>=10 and accuracy<0.35` (hit-rate only). A dollar-positive veto can retire.
5. **Long-side machinery already exists** — feedback A/B has SIDE_BIAS_LONG_filter / SIDE_BIAS_LONG_SUSPENSION; no hardcoding needed.
6. **Louis Lane has a Blob-free write channel** — lib/util.js notify() (Discord/Telegram webhooks), api/track.js proves the pattern; likes/reviews/analytics can work today without Blob.

## Ranked plan (top 10)
- **[P1] ★ Plug the live capture leak** (thesis/conf/driver/regime/strategy on EVERY close) — AUTONOMOUS. Prerequisite for all regime/calibration learning. Fix close-path writers to pull metadata captured at entry; wire `strategy` col; test that no close can be unlabeled.
- **[P2] ★ PnL-weight the veto retire** — AUTONOMOUS (logic+backfill); flag hype_long_veto restore to owner. Add pnl_saved/pnl_missed to record_veto_outcome; retire only if acc<0.35 AND net_pnl_saved<=0; backfill from 36.5k counterfactuals; re-score retired vetoes.
- **[P3] ★ Confidence-calibrated sizing ladder** — OWNER-GATED (prep autonomous). Measured: 60–69=18% WR, 70–79=0% WR, 80+=only profitable band; yet leverage.py:164-173 gives 60–79 rm=0.8–1.0. Build counterfactual replay of all 89 trades with data-derived rm ladder; implement behind A/B flag; owner approves.
- **[P4] Sizing-inversion cap** — OWNER-GATED (analysis autonomous). Per-trade notional band (cap at k× median) so stop-width can't create 2.5x dispersion. No "shorts get more" hardcode — side bias emerges from A/B rules + calibrated sizing.
- **[P5] Exit geometry (BE-stop/TP1)** — OWNER-GATED (analysis autonomous). Measure MFE vs TP1 distance vs when stop moved; propose flag-gated param change (don't move SL to BE until X% of TP1 distance, or pull TP1 in by vol band); counterfactual first.
- **[P6] LL owner photos** — OWNER (5 min): 2-3 photos each of RSO Syringe, RSO Gummies, Bubba Kush, Permanent Marker + eyeball hash-rosin/v1. Integration autonomous.
- **[P7] LL Blob-free writes** — AUTONOMOUS. Analytics beacon → /api/track (batched, rate-limited); reviews/likes POST → notify() so owner sees real reviews instantly; optimistic client render; keep logBlob for self-heal.
- **[P8] Leverage-chain instrumentation + ramp policy** — instrumentation AUTONOMOUS; ramp OWNER-GATED. Log every sizing stage (tier→agree→WR-scale→cap→LLM sizer→final). Ramp policy: Kelly tiers only for calibrated 80+ trades, only after P1+P3 produce 15-20 cleanly-labeled closes confirming the band (current n=7).
- **[P9] Validate regime-skip missed-EV** — AUTONOMOUS analysis, blocked on P1 labels. Split 36.5k counterfactuals by fortnight + realized regime; confirm skip-EV persists outside the melt-up window; if it survives, propose graduated-rule loosening via A/B (never touch confidence floors — they save money).
- **[P10] LL QR/business-card pack** — AUTONOMOUS design (louis-lane-qr.png exists); owner prints.

## Top 3 outcome-changers
P1 (measurement first — everything learns from corrupted labels until fixed), P3 (stop full-sizing the 18%/0% WR bands), P2 (repair the learning system's referee).

## Sequence
- **Tonight (autonomous):** P1 → P2 → P8a instrumentation → P4a/P5a analyses → LL P7 (+P10). pytest after each; never touch gates/CBs.
- **Morning brief (owner ~10 min):** approve P3 rm ladder, P4 cap, P5 exit tweak, hype_long_veto restore; send P6 photos.
- **Rest of week:** accumulate 15-20 cleanly-labeled closes → P9 regime-split validation → only then the P8 leverage-ramp discussion. Leverage returns as a consequence of proven calibration.

## Key files
- bot/multi_strategy_main.py (close path, P1)
- bot/llm/graduated_rules.py (retire criterion, P2; state in bot/data/llm/graduated_rules.json)
- bot/execution/leverage.py (rm ladder 164-173, sizing formula 254, P3/P4/P8)
- bot/execution/position_manager.py (exit state machine, P5)
- C:\Projects\louis-lane\lib\util.js (notify() Blob-free channel, P7)

## Cross-check
A 6-seam wiring-audit Workflow (adversarially verified) is in flight → WIRING_AUDIT_2026-07-01.md. Implementation of P1/P2 starts after it lands (use its confirmed file:line findings; refuted claims get skipped).
