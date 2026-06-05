# Agent Audit: Dormant Agent Investigation

**Date:** 2026-06-02  
**Author:** laptop-claude  
**Branch:** historical-import-2026-05-30

---

## Status Summary

| Agent | Status | Notes |
|-------|--------|-------|
| Regime | ACTIVE | Required, always runs, 30-min regime cache, feeds all downstream |
| Trade | ACTIVE | Core decision maker, full recording + brain wiring |
| Risk | ACTIVE | Sizing, default enabled, recorded |
| Critic | ACTIVE | Veto power functional, mechanical fallback solid |
| Learning | ACTIVE | Post-trade async, feeds deep_memory/KB/hypothesis |
| Exit | ACTIVE | Independent position monitor, runs on open positions |
| Scout | ACTIVE | Idle-time watchlist + thesis cache, injects into entry pipeline |
| Overseer | ACTIVE | Periodic meta-optimizer, cold-start guard prevents hallucination |
| **Quant** | **PARTIAL** | Runs but 2 tracking gaps; see below |

---

## Per-Agent Detail

### 1. Regime — ACTIVE
- **Invoked:** `get_trading_decision()` line ~772, via `_call_agent(AgentRole.REGIME, ...)`
- **Output consumed:** Scratchpad writes (regime, conf, bias, outlook); passed to all downstream agents
- **Tracking:** `record_agent_decision("regime", ...)` + performance_tracker pipeline record
- **Skip conditions:** `LLM_MULTI_AGENT=false`; 30-min cache (returns cached on repeat calls)
- **Assessment:** Fully wired. Cache TTL is 30 min — regime shifts inside 30 min window get stale context.

### 2. Trade — ACTIVE
- **Invoked:** `get_trading_decision()` line ~959
- **Output consumed:** Drives final LLMDecision action; thesis tracked via `record_thesis()`
- **Tracking:** `record_agent_decision("trade", ...)` + performance tracker + brain wiring
- **Skip conditions:** `LLM_MULTI_AGENT=false`; budget exhaustion
- **Assessment:** Fully wired. Most data-rich agent in the pipeline.

### 3. Risk — ACTIVE
- **Invoked:** `get_trading_decision()` line ~985; `configs[RISK].enabled` guard
- **Output consumed:** Leverage + sizing merged into EntryDecision at lines ~1547-1564
- **Tracking:** `record_agent_decision("risk", ...)` (only if ok)
- **Skip conditions:** `AGENT_RISK_ENABLED=false`; budget exhaustion
- **Assessment:** Fully wired.

### 4. Critic — ACTIVE
- **Invoked:** `get_trading_decision()` line ~1018; high-stakes debate escalation at ~1005
- **Output consumed:** Veto overrides Trade action; confidence consensus line ~1243
- **Tracking:** `record_agent_decision("critic", ...)` + performance tracker; veto counterfactuals tracked
- **Skip conditions:** `AGENT_CRITIC_ENABLED=false`; budget exhaustion; mechanical fallback exists
- **Assessment:** Fully wired. Veto tracking is solid for calibration feedback.

### 5. Learning — ACTIVE
- **Invoked:** `get_post_trade_lesson()` line ~1835 — called externally on trade close
- **Output consumed:** `process_agent_lesson()` in learning_integration.py → deep_memory, hypothesis tracker, knowledge base
- **Tracking:** `performance_tracker.record_pipeline_run("learning_...")` + brain `close_thesis()`
- **Skip conditions:** `AGENT_LEARNING_ENABLED=false`; budget exhaustion
- **Assessment:** Fully wired. Post-trade async design means ~5-10 min lag before lessons appear in KB. Not a bug — by design.

### 6. Exit — ACTIVE
- **Invoked:** `get_exit_intelligence()` line ~2091 — called externally on open positions
- **Output consumed:** Returned directly to caller; `process_exit_feedback()` line ~2120 feeds learning
- **Tracking:** `performance_tracker.record_pipeline_run("exit_...")`
- **Skip conditions:** `AGENT_EXIT_ENABLED=false`; budget exhaustion
- **Note:** Exit output is NOT merged into core entry pipeline scratchpad — intentional isolation. Exit conclusions about open positions don't influence entry decisions on new signals (could be improved later).
- **Assessment:** Active and correctly isolated. Connection to learning is intact.

### 7. Scout — ACTIVE
- **Invoked:** `run_scout()` line ~2201 — called externally during idle time
- **Output consumed:** Scratchpad writes (watchlist, regime_forecast, lead_lag_alerts, risk_budget); thesis cache injected into `get_entry_decision()` line ~1751 when age < 20 min
- **Tracking:** `performance_tracker.record_pipeline_run("scout_...")`
- **Skip conditions:** `AGENT_SCOUT_ENABLED=false`; budget exhaustion
- **Assessment:** Active. Scout thesis cache injection is a real forward-looking capability. TTL is 20 min — reasonable.

### 8. Overseer — ACTIVE
- **Invoked:** `run_overseer()` line ~2306 — called externally periodically
- **Output consumed:** Scratchpad writes (strategy_adjustments, agent_feedback, health); feeds growth orchestrator, hypothesis tracker, self_analyst
- **Tracking:** `performance_tracker.record_pipeline_run("overseer_...")`
- **Skip conditions:** `AGENT_OVERSEER_ENABLED=false`; input size < 1500 chars (cold-start guard line ~2297)
- **Note:** Cold-start guard is intentional — prevents hallucination when no history exists. First ~100 trades have no Overseer feedback.
- **Assessment:** Active. Cold-start guard is correct design.

### 9. Quant — PARTIAL
- **Invoked:** `get_trading_decision()` line ~854; `configs[QUANT].enabled` guard at ~847
- **Output consumed:** Scratchpad writes (ev, conditional_edge, probability, kelly_fraction, signal_quality, risk_profile); confidence adjustment applied at ~1102; noise_probability > 0.6 forces skip at ~1127-1152
- **Tracking:** Only via `performance_tracker.record_pipeline_run()` (all agents). BUT:
  - `record_agent_decision("quant", ...)` is NOT called (regime/trade/risk/critic all get this call at lines 1175-1180; quant omitted)
  - `_extract_decision()` in performance_tracker.py had no quant case — always returned "unknown" ← **FIXED this session**
- **Skip conditions:**
  1. `AGENT_QUANT_ENABLED=false` 
  2. `AGENT_TIERED_ROUTING=true` AND tier==2 → silent disable (no log emitted)
  3. Budget exhaustion
- **Gaps fixed this session:**
  - `_extract_decision` now returns `ev=<direction>,quality=<clean|marginal|noise>` for quant
  - Added `record_agent_decision("quant", ...)` call (see fix below)
  - Added `logger.debug` when tier-2 skip occurs

---

## Fixes Applied This Session

### Fix 1: `_extract_decision` quant case
**File:** `bot/llm/agents/performance_tracker.py`  
Added specific quant case to `_extract_decision()`:
```python
elif role_val == "quant":
    ev_dir = d.get("ev", {}).get("direction", "neutral")
    sq = d.get("signal_quality", {})
    noise = sq.get("noise_probability", 0.5)
    quality = "noise" if noise > 0.6 else ("clean" if noise < 0.3 else "marginal")
    return f"ev={ev_dir},quality={quality}"
```

### Fix 2: `record_agent_decision` for quant
**File:** `bot/llm/agents/coordinator.py`  
Added at lines ~1181-1183:
```python
if quant_out and quant_out.ok:
    record_agent_decision("quant", quant_out.data, regime=_regime)
```

---

## Remaining Non-Urgent Improvements

| Item | Impact | Effort |
|------|--------|--------|
| Exit insights → entry scratchpad | Regime-shift signal if existing position struggling | Medium (by design to be isolated; change carefully) |
| Learning lag reduction | Faster lesson propagation | Low — async design is intentional |
| Quant tier-2 visible in logs | Better observability | Done (added debug log) |
| Overseer cold-start visible in logs | Better observability | Low |

---

## Key Finding: All 9 Agents Are ACTIVE

No agent is dead code. The "only 3 quant records" on the desktop was:
1. A tracking bug (`_extract_decision` returned "unknown" for quant) ← fixed
2. Possibly session limits reducing total pipeline runs
3. NOT a wiring issue — quant was running and feeding the pipeline correctly

The Quant agent's `noise_probability` and `confidence_adjustment` outputs are consumed by the confidence calculation. Kelly fraction and EV feed the trade agent via scratchpad. All connections exist.
