# Tools Audit — 2026-04-29

**Question:** `bot/tools/` has 75 Python scripts totaling ~29,200 lines. Which are production-relevant, which are useful manual scripts, which are dead?

**Headline:** **Only ~5 of 75 tools are programmatically called.** The other ~70 are standalone scripts. Some are still useful as manual analysis tools; many are duplicates or stale experiments. The directory has accumulated significant "research debris."

This isn't the same kind of dead code as §08/§09 — these are scripts, not subsystems. They don't degrade the running bot. But they obscure which tools are current vs deprecated, and the directory's signal-to-noise ratio is poor.

---

## Inventory

- **75 Python files** in `bot/tools/`
- **29,199 lines** of code
- **~50 with `__main__` blocks** (intended as runnable scripts)
- **4 imported by other code** in the project (production-relevant)
- **3 referenced by user-facing skills** in `.claude/skills/`

---

## The 4 Production-Relevant Tools (imported elsewhere)

| Tool | Imported by | Purpose |
|---|---|---|
| `thesis_tracker.py` | `api_server.py` (2 routes) | Live thesis accuracy tracking |
| `sniper_counterfactual.py` | (1 caller) | Sniper trade counterfactuals |
| `regime_detector.py` | (1 caller) | Note: there's also `strategies/regime_detector.py` — possible name clash |
| `level_tracker.py` | (1 caller) | Price level tracking |

These are programmatically used — keep, document, treat as part of the production surface.

## Tools Referenced by Skills (3)

From `.claude/skills/babysit.md`:
- `tools/intel_collector.py` — intel collection loop
- `tools/overwatch_analyzer.py` — overwatch analysis
- `tools/thesis_tracker.py` — thesis tracking (also production-relevant)

These are intentional manual tools. Keep, document.

## Everything Else (~68 scripts)

Run-only, no imports, no skill references. Distributed roughly:

- **Backtests** (~5): `ab_backtest`, `broad_backtest`, `full_stack_backtest`, `backtest_48h_comparison`, `backfill_trade_features`
- **Analysis / studies** (~18): `alpha_72h_study`, `alpha_hunter`, `analyze_stop_hunting`, `comprehensive_edge_study`, `deep_edge_analysis`, `cross_asset_analysis`, `cross_asset_correlation`, `ic_factor_study`, `leverage_analysis`, `leverage_precision_analysis`, `multi_edge_sim`, `multilayer_sim`, `multi_path_compare`, `oversold_alpha_study`, `regime_prediction_deep`, `regime_prediction_research`, `seasonality_analysis`, `signal_decay_halflife`
- **Monitors / status** (~13): `bot_status`, `quick_status`, `live_analyst`, `live_edge_monitor`, `live_sizing_monitor`, `liquidation_tracker`, `level_analysis`, `level_tracker`, `edge_tracker`, `funding_oi_collector`, `shadow_mr_tracker`, `terminal_status`, `watchdog`-adjacent
- **Debug / research** (~11): `continuous_audit`, `llm_integration_test`, `llm_pipeline_test`, `pnl_reconcile`, `preflight_check`, `orderbook_proxy_research`, `signal_replay`, `signal_funnel`, `signal_scan`, `volume_profile`, `entry_map_generator`
- **Reporting / charts** (~5): `cost_report`, `chart_thread`, `btc_chart_gen`, `btc_thread_gen`, `overnight_report`, `overwatch_analyzer`
- **One-off / ad-hoc** (~16): `restart_bot`, `clean_replay`, `manual_trade_helper`, `per_trade_forensic`, `sl_microstructure_analysis`, `stop_hunt_analyze`, `stop_hunt_detect`, `sol_direction_filter`, `sol_direction_filter_v2`, `sniper_setup_scan`, `winner_amplify`, `agent_performance`, `conviction_stacking`, `counterfactual_resolver`, `regime_detector` (duplicate name!), and others

---

## Suspect Duplicates / Versioned Scripts

These name patterns suggest superseded versions:

| Group | Scripts | Likely status |
|---|---|---|
| **Stop hunt** | `analyze_stop_hunting.py`, `stop_hunt_analyze.py`, `stop_hunt_detect.py` | 3 separate scripts on the same topic — pick one, archive others |
| **SOL direction** | `sol_direction_filter.py`, `sol_direction_filter_v2.py` | v2 likely supersedes v1 |
| **Backtest** | `ab_backtest.py`, `broad_backtest.py`, `full_stack_backtest.py`, `backtest_48h_comparison.py` | 4 backtest tools — overlap with `python run.py backtest`. Pick canonical |
| **Edge** | `edge_tracker.py`, `deep_edge_analysis.py`, `comprehensive_edge_study.py`, `multi_edge_sim.py`, `live_edge_monitor.py` | 5 "edge" tools — likely overlap, esp. live_edge_monitor vs edge_tracker |
| **Regime** | `regime_detector.py`, `regime_prediction_deep.py`, `regime_prediction_research.py` | 3 regime tools; collision with `strategies/regime_detector.py` |
| **Live sims** | `live_analyst.py`, `live_edge_monitor.py`, `live_sizing_monitor.py` | 3 "live" monitors — likely overlap |
| **Alpha** | `alpha_72h_study.py`, `alpha_hunter.py`, `oversold_alpha_study.py`, `comprehensive_edge_study.py` | 4 alpha-related; pick best, archive |

That's at least **15-20 likely-duplicate scripts** that could be consolidated.

---

## Recommendation

Don't bulk-delete — these scripts represent real research effort and may be referenced in personal notes / Slack history I can't see. But the directory needs hygiene.

### Step 1 — Manifest pass (~2h)

Create `bot/tools/MANIFEST.md`:

```markdown
# bot/tools/ — Manifest

## Production (imported by bot or api_server)
- thesis_tracker.py — live thesis accuracy ✅ KEEP
- sniper_counterfactual.py — sniper counterfactuals ✅ KEEP
- ...

## Skill-invoked
- intel_collector.py — used by /babysit ✅ KEEP
- ...

## Manual analysis (operator runs ad-hoc)
- alpha_hunter.py — last good run YYYY-MM-DD — KEEP/ARCHIVE
- ...

## Deprecated / superseded
- sol_direction_filter.py — superseded by v2 — ARCHIVE
- ...
```

For each script: 1-line purpose + last-known-good run + status.

### Step 2 — Move stale scripts to `bot/tools/_archive/` (~1h)

Anything tagged ARCHIVE in the manifest moves to `_archive/`. Same pattern as `web/_archive/`. Preserves history; cleans the working directory.

After this pass, `bot/tools/` has maybe 20-25 active scripts. Easier to maintain, easier to find what you need.

### Step 3 — Group surviving scripts (~30min)

Optional but worth doing:

```
bot/tools/
  backtest/    — backtest runners
  analysis/    — one-shot analysis scripts
  monitors/    — long-running watchers
  reports/     — report generators (overnight, cost, etc.)
  research/    — experimental / Phase-N research
```

Reduces noise per category.

---

## Tools That Should Probably Move OUT of `bot/tools/`

- **`thesis_tracker.py`** is imported by `api_server.py` — it's runtime code, not a tool. Move to `bot/llm/thesis_tracker.py` or similar.
- **`regime_detector.py` (in tools/)** name-collides with `strategies/regime_detector.py`. Pick one location, delete the other. Likely the strategies/ one is canonical (it's wired into the live pipeline).

---

## Comparison to Other Directories

| Dir | Files | Audit-equivalent finding |
|---|---|---|
| `bot/llm/agents/` | 23 roles | 13 of 23 unwired (§09) — **57% dead** |
| `bot/feedback/` | ~20 modules | 16 of 18 wired correctly (§08) — **89% wired** |
| `bot/strategies/` | 22 files | 13 of 22 active in ensemble (§10) — **59% wired**; 3 orphan-alt-implementations |
| `bot/tools/` | 75 files | 4 imported, 3 skill-referenced — **~93% script-only** |

The tools directory follows a fundamentally different pattern (scripts not subsystems), so the "wired vs unwired" framing doesn't apply directly. But the signal of "75 scripts in a working tree" is itself a smell — it makes finding the production-relevant ones harder.

---

## Bottom Line

**Time investment to clean up:** ~3.5 hours total (manifest + archive + grouping).
**Operational impact when bot is running:** none directly.
**Maintenance impact:** large — every future audit / debugging session benefits from a clean tools/ directory.

This is lower priority than §02 (rule compiler) or §09 (Forecaster wiring), but it's the kind of debt that compounds. Worth scheduling within the next few sessions.
