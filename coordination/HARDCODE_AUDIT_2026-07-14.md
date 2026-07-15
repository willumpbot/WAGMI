# WAGMI Hardcode / Stale-Stat / Static-Gate Audit — 2026-07-14

3 parallel scans (fictional-stats, directional-biases, gates/blocks). Ranked by: LIVE (not shadow) ×
drives trades/prompts × directionally-wrong vs the live edge. **Live edge truth (complete ledger):
SHORTS win / LONGS lose across all majors; ETH_SELL best (+$14.90/tr n37); HYPE_BUY worst (-$47.81/tr n19).**

## TIER 1 — LIVE + DIRECTIONALLY WRONG (actively hurting the edge) — fix first
1. **`trading_config.py:886` SYMBOL_SIDE_RISK_MULTIPLIERS** — the smoking gun. The ONLY multiplier table
   with NO live blend (`get_symbol_side_risk_mult` :973-983 is pure hardcode). Cuts ETH_SELL (best edge)
   to 0.70; leaves HYPE_BUY (worst) at 0.70. From a 2026-03-30 backtest. → replace w/ data-driven PnL/tr
   (n>=13, ledger). FIX PROTOTYPED.
2. **`signal_pipeline.py:743-754` anti-short leverage caps** — shorts capped 8/12/15x, longs 10/15/20x.
   Structurally UNDER-levers the winning side (shorts), OVER-levers the losing side (longs). No data
   citation. → make leverage cap data-driven by side edge, or neutralize the asymmetry.
3. **`graduated_rules.json btc_short_conf70_80_penalize_v1` (active)** — −20 conf on BTC SELL 70-80%
   (the winning direction, modal conf band). era:"" (pre-standard). → retire (fails n>=13/provenance).
4. **`ensemble.py:694-718` pro-HYPE-BUY magnitude bypass (LIVE)** — un-blocks below-floor HYPE_BUY
   (worst setup) past the confidence floor on a stale "15-22% moves" claim. → remove.
5. **Enforcement asymmetry** — `sol_long_veto_v1` active (722 firings) but `hype_long_veto_v1` RETIRED,
   so the WORST live setup (HYPE_BUY) has no veto while SOL_BUY does; HYPE_BUY even keeps shadow boosts +
   "elite" labels (manual path). → align vetoes to live edge (data-learned, not hand-picked).

## TIER 2 — FICTIONAL STATS poisoning the LLM / human (remove the fiction; zero trade risk)
6. **`telegram_bot.py:2223`** — literal *"GROUND TRUTH: ETH=47% WR, trending=56% WR..."* fed to the LLM
   as fact every /copilot call. Undated, never computed. → delete / compute live.
7. **`dashboard/server.py:2868`** — UI shows fictional **"65% Win Rate"** (real ~30%). → compute from ledger.
8. **`manual/alerts.py:139` + `dip_detector.py:109`** — asserts **"88.5% WR"** to the human for a setup the
   bot's own audit measured at **23% (n=35)**. → delete / compute live.
9. **`premium_filter.py:62-92`** — ZOMBIE: "ETH BUY 100% WR — can execute alone" survived the 2026-06-05
   poison purge; `_SHADOW_BLOCKS` even blocks ALERTING on ETH_SELL (the best edge). → empty it like the others.
10. **`quant_brain.py:190-201` _SETUP_WIN_PROBS** — ETH_SELL prior capped 0.55 despite 90.9% live WR;
    stale prior pinned at **permanent 40% weight** (never decays) → feeds win_prob→EV→veto. Suppresses best
    edge by construction. → decay stale prior to 0 as live n grows.

## TIER 3 — STATIC PRE-LLM GATES (drop signals before the brain sees them)
11. **`ensemble.py:694-754` conf floor** — chop escalation ramps to hardcoded **77.0** over static
    breakpoints 0.35/0.65/0.85. Most aggressive static block still live.
12. **`probability_engine.py:81,354-374`** — MIN_PROB_TP1=0.35 / MIN_EV=0.10 + regime tables → `return None`
    at signal generation (pre-ensemble, pre-LLM).
13. **`ensemble.py:2601` negative-EV block (H4) — TIME BOMB** — only disarmed by `LLM_MODE>=4`; silently
    re-arms if mode ever drops. No dedicated flag. → add explicit shadow flag.
14. **`consistency_checker.py:212` + `coordinator.py:1300`** — post-LLM override forces "go"→"skip" on a
    confidence floor with **3 conflicting defaults** (40 vs 55 vs 20 across files). → single source of truth.

## TIER 4 — stale sizing fallbacks / metadata (MED; blended at n>=15 so decays, but stale below)
- `trading_config.py:845` REGIME_RISK_MULTIPLIERS (2026-04, self-contradicting "consolidation 78% AND 0% WR")
- `trading_config.py:868` SYMBOL_RISK_MULTIPLIERS (2026-04)
- `sizing_optimizer.py:108` _DEFAULT_PRIORS (2026-03; HYPE_SELL 0.07 "toxic" kills a short; bull>bear mult backwards)
- `momentum_tracker.py:4-29` MOMENTUM_MULTIPLIERS (undated); `multi_strategy_main.py:8002` _quant_backtest_2026_03_26 fingerprint verdicts injected into LLM context + exploration gate
- `LEAD_LAG_SYMBOL_CONFIG` beta/lag never measured live; whole `manual/` sniper stack (2026-03) labels HYPE_BUY "elite"

## CONTRADICTION PAIRS (same stat, both truths — proof it's fiction)
- trending_bear: "worst 10-20% WR" (ensemble gate) vs "GOLDEN 75% WR" (config sizing) vs "56%" (LLM prompt)
- consolidation: "78% WR +$3.2k" vs "0% WR DISASTER" — 12 lines apart, same file
- HYPE dip: "88.5% WR" (human alert) vs "23% n=35" (bot's own audit)
- BTC_BUY: 0.56 vs 0.35 vs "15% WR" (3 files)
- ETH BUY regime_trend: "100% WR premium" (premium_filter) vs purged as fee-bug poison everywhere else

## GOOD NEWS (discipline that held)
Most older gates already demoted to SHADOW + kill-switch + n>=13 restore rule (time_sizing, quant_rules,
HYPE bypass shadow copy, _SHADOW_EDGES/_GOLDEN emptied, graduated_rules §2b n>=13). Live-risk surface is
concentrated in Tier 1-3 above. No regime is hard-blocked (min mult 0.30, never <=0).

## FIX APPROACH (living values)
- Tier 2 (fiction in prompts/UI): DELETE or compute-live — zero trade risk, do first.
- Tier 1 (directional sizing/vetoes): replace w/ live ledger-computed values (n>=13, PnL-driven), flag-gated,
  validated — the data-driven side-mult prototype is the template.
- Tier 3 (static gates): add shadow flags / single-source the conflicting defaults; do NOT rip out protective
  gates without validation (could unleash bad trades).
- NEVER weaken exits/risk/CB. Each fix flag-gated + reversible + shows new-vs-old.
