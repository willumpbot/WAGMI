# REPLAY CAMPAIGN PLAN — post-VAL1 tuning (PLAN ONLY, not launched)
Date: 2026-07-02 | Author: engine session | Governs: THE_STANDARD v1.3 | Prereq reading: coordination/REPLAY_RUN_VAL1.md

## 1. VAL1 zero-trade diagnosis (evidence-backed)

### (a) What the 62 real LLM calls decided
62 calls = **15 full pipelines** (~4.13 calls each: regime, quant, trade, risk, critic), journaled in
`bot/data/replay/VAL1/sandbox/data/replay_llm_journal.jsonl` + `.../data/llm/agent_performance.jsonl`.
- **All 15 on BTC, hours 03:00–17:00 of Jun 20** — the first 15 raw signals of the walk. ETH/SOL got zero LLM attention.
- **15/15 = regime "consolidation" → trade "skip" (conf 0.25–0.30) → critic "approve" (approving the skip)**. Veto rate 1.0, zero critic vetoes.
- Skip reasons (consistent, correct): solo ensemble signal (confluence count = 1) not in the tradeable-solo whitelist, raw conf ~0.52,
  quant negative conditional edge (−2 to −17pp), Kelly ≈ 0, noise_probability 0.56–0.97, consolidation regime, two direction-vs-regime conflicts.
- Verdict: the evaluated slice was genuinely skip-worthy; the LLM behaved exactly like live selectivity. **No agent-caution pathology.**

### (b) What "Fallback: 394" is
`BacktestLLMIntegration.evaluate_entry` (bot/backtest/llm_integration.py:481) short-circuits once `call_cap_reached` —
every later signal increments `candles_fallback` and returns `None`. In REPLAY_MODE the engine converts a None decision into a
**forced skip** (bot/backtest/engine.py:1505–1512, "llm_required_missing_replay") so mechanical-fallback trades can't pollute the
clean-close sample. So the Fallback path decides **nothing — it is a hard skip by design**. 427 total fallbacks (394 shown at the
last progress print) = every post-cap signal across all 3 symbols. It "never entered" because it is forbidden to, correctly.

### (c) Skip-worthy window or entry starvation? → **HARNESS STARVATION, not a dead window**
- In LLM mode the engine calls `ensemble.evaluate_raw()` (engine.py:896) — no EV gate, no confidence floor → signal on
  **442/504 candles (88%)**. The pipeline is triggered on raw candle order, so the 60-call cap burned on the first 15
  consecutive BTC hours — all solo confidence_scorer 52–70 conf, the weakest slice in the whole window.
- What the cap starved (from `sandbox/data/analysis/trade_candidates.csv`): **80 multi-agree signals**
  (confidence_scorer+bollinger_squeeze clusters at 55–77 conf; regime_trend+confidence_scorer 76.7),
  **7+ solo signals at conf ≥ 82 incl. four regime_trend conf-95 SHORTs** (Jun 20 18:00, Jun 24 08:00, Jun 24 10:00 ETH, Jun 25 11:00)
  during a −5.4% ER-0.49 down-leg. The exact setups the Trade agent's own skip reasoning says it wants
  ("bollinger_squeeze/multi-agree" confluence) never reached it.
- Window itself: Jun 20–27 was a drifting bear week (BTC −5.4%, ER 0.49) — not trend-rich, but clearly not signal-dead.
- Exploration: the backtest engine has **no epsilon/exploration path at all** (grep: zero hits in engine.py) — a live-vs-replay
  divergence, acceptable for a clean-close sample but worth stating: replay measures the selective policy only.

Root cause in one line: **first-come-first-served LLM triggering on an 88%-density raw-signal firehose + global (not per-symbol) call cap.**

## 2. Campaign design

### 2.1 Entry-event-only LLM triggering (the fix)
Call the pipeline ONLY when the ensemble emits an *entry event*, defined as:
- `num_agree >= 2` (multi-strategy confluence), OR
- solo signal with conf ≥ 75 from {regime_trend, bollinger_squeeze, vmc_cipher, mean_reversion} (the whitelist the Trade agent already respects);
- PLUS a **per-symbol 4h same-direction cooldown** (squeeze/trend signals persist across consecutive hours — VAL1 shows 2–4-bar clusters; only the first bar of a cluster should spend calls);
- PLUS a **per-symbol call budget = cap/3** so BTC cannot starve ETH/SOL.
Implementation locus: extend `_should_skip_llm()` in bot/backtest/llm_integration.py (REPLAY-gated so normal backtests are untouched) + pass `num_agree`/strategy into the snapshot signal block (already carried in signal.metadata). ~30 lines, no live-path change.

### 2.2 Cap sizing math
- VAL1 measured: 4.13 calls/pipeline, ~3 min wall/pipeline at sleep 15s.
- VAL1 window event density after gating: 80 multi-agree + ~20 solo≥75 = ~100 raw events → ~40 distinct events after 4h cooldown (3 symbols, 7 days).
- Calls needed: 40 events x 4.2 calls ≈ **168 → set cap 180/window** (VAL1's 60 was 3x too small for even one week).
- Wall time: ~40 pipelines x ~3 min ≈ **2h/window** at sleep 15s (sleep 10s → ~1.6h). Schedule per window in the token-limit gaps; never run two windows concurrently with the live bot's quota.
- Expected closes: at live-like approval rates on gated-quality signals (15–30%), 6–12 entries/window → **~5–10 closes/window** (end-of-walk force-close guarantees entry→close).

### 2.3 Window selection (BTC daily candles 2025-01→2026-07, HL API; ret/ER/avg daily range measured)
| # | Window (7d walk) | Regime | Evidence |
|---|---|---|---|
| W1 | 2025-07-07 → 2025-07-14 | trend-UP, clean | +10.8%, ER 0.98, range 2.9% |
| W2 | 2026-04-04 → 2026-04-11 | trend-UP, current era | +8.5%, ER 0.73, range 3.3% |
| W3 | 2025-11-10 → 2025-11-17 | trend-DOWN, clean | −13.0%, ER 0.88, range 4.4% |
| W4 | 2025-06-07 → 2025-06-14 | pure CHOP, low vol | −0.1%, ER 0.01, range 2.6% |
| W5 | 2026-02-01 → 2026-02-08 | HIGH-VOL panic | −8.6%, ER 0.24, range 9.0% |
| W6 | 2026-06-20 → 2026-06-27 | bear drift (VAL1 rerun) | −5.4%, ER 0.49 — like-for-like A/B vs VAL1 |
Symbols: BTC,ETH,SOL each window. Equity $500. Same fee model as VAL1.

### 2.4 Expected totals
- ~240 events → **~1,000 LLM calls** (~6 x 180 cap), ~12h wall spread over multiple days/limit windows.
- **~30–60 closes** across 6 windows — enough to read WR/EV per regime with small-n humility; chop window W4 expected near-zero entries (that is itself the test: selectivity should go quiet in chop).
- Success criteria: (i) >0 closes in W1–W3/W5; (ii) skip rate in W4 > W1–W3; (iii) per-regime WR/PF vs the −$1,001 ranging-entry pathology (RQ10 F6); (iv) zero production-data writes (isolation diff clean).

### 2.5 Fidelity caveats to carry into every report
- HL 5m history is shallow: 2025 windows will likely run 1h-touch fills only (conservative). Verify 5m depth per window pre-launch; disclose per window.
- Empty-memory brain; candle-only prompts (no funding/OI reconstruction); LLM non-determinism — one sample of policy per window.
- No exploration path in replay: measures the selective policy, not the live epsilon mix.

## 3. Status
**NOT LAUNCHED.** Owner review requested: (1) approve the ~1,000-call quota spend + scheduling in limit-window gaps; (2) approve the `_should_skip_llm` REPLAY-gated event filter (~30 lines); (3) confirm window set W1–W6.
