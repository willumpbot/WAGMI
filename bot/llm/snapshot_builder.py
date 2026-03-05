"""
Snapshot builder: converts bot state into the compact JSON the LLM receives.

Design principles:
  - Only send markets with active signals (reduces tokens ~60%)
  - Cap at top N markets by signal strength (5-8 markets, not 18)
  - Compress: short keys, strip nulls/zeros, aggressive rounding
  - Include active positions for context
  - Throttle: skip LLM call if market hasn't changed meaningfully

The LLM sees ONLY what this module produces. Nothing else.
"""

import json
import logging
import os
import time
from typing import Dict, List, Optional, Any

from llm.decision_types import (
    StrategySignal,
    MarketSnapshot,
    GlobalContext,
    LLMInputSnapshot,
)

logger = logging.getLogger("bot.llm.snapshot")

# ── Throttling state ─────────────────────────────────────────────

_last_call_ts: float = 0.0
_last_snapshot_hash: str = ""
_MIN_CALL_INTERVAL_S = 300  # 5 minutes between LLM calls
_FORCE_CALL_INTERVAL_S = 900  # Force a call every 15 minutes regardless


def should_call_llm(snapshot: LLMInputSnapshot) -> bool:
    """Determine if we should call the LLM based on throttling rules.

    Returns True when:
      - At least 5 minutes since last call AND something changed
      - OR at least 15 minutes since last call (forced periodic update)
      - OR circuit breaker just activated/deactivated
      - High volatility reduces minimum interval to 120s for faster reaction
    """
    global _last_call_ts, _last_snapshot_hash

    now = time.time()
    elapsed = now - _last_call_ts

    # Force call every 15 minutes
    if elapsed >= _FORCE_CALL_INTERVAL_S:
        return True

    # Volatility-aware minimum interval: faster in volatile markets
    min_interval = _MIN_CALL_INTERVAL_S
    g = snapshot.global_context
    if g and g.extra:
        # Check if any volatility indicator suggests fast markets
        regime = g.extra.get("dominant_regime", "")
        if regime in ("panic", "high_volatility", "news_dislocation"):
            min_interval = 120  # 2 min in volatile regimes
        elif g.circuit_breaker_active:
            min_interval = 120  # faster during circuit breaker

    # Minimum interval
    if elapsed < min_interval:
        return False

    # Check if market state changed meaningfully
    current_hash = _compute_snapshot_hash(snapshot)
    if current_hash != _last_snapshot_hash:
        return True

    return False


def mark_called(snapshot: LLMInputSnapshot):
    """Mark that we just called the LLM."""
    global _last_call_ts, _last_snapshot_hash
    _last_call_ts = time.time()
    _last_snapshot_hash = _compute_snapshot_hash(snapshot)


def _compute_snapshot_hash(snapshot: LLMInputSnapshot) -> str:
    """Quick hash of the market state to detect meaningful changes.

    We don't need cryptographic hashing -- just detect if the top signal
    directions or regime indicators shifted.
    """
    parts = []
    for m in snapshot.markets:
        for s in m.signals:
            # Round confidence to nearest 0.1 so tiny jitter doesn't trigger
            parts.append(f"{s.symbol}:{s.side}:{round(s.confidence, 1)}")
    parts.append(f"cb:{snapshot.global_context.circuit_breaker_active}")
    parts.append(f"pos:{snapshot.global_context.total_open_positions}")
    return "|".join(sorted(parts))


# ── Snapshot building ────────────────────────────────────────────

# Default 8 markets max (was 10). Env-overridable.
MAX_MARKETS_IN_SNAPSHOT = int(os.getenv("LLM_MAX_MARKETS", "8"))

# Minimum signal confidence to include a market (was 0.4, now 0.3 to catch more)
MIN_SIGNAL_CONFIDENCE = float(os.getenv("LLM_MIN_SIGNAL_CONF", "0.3"))


def build_snapshot(
    markets: List[MarketSnapshot],
    global_context: GlobalContext,
    memory_summary: Optional[str] = None,
    active_positions: Optional[List[Dict[str, Any]]] = None,
    trigger_reason: str = "",
    trigger_context: str = "",
) -> LLMInputSnapshot:
    """Build a token-efficient snapshot for the LLM.

    Filtering:
      1. Only include markets where at least one strategy has confidence > MIN_SIGNAL_CONFIDENCE
      2. Sort by max signal confidence (strongest signals first)
      3. Cap at MAX_MARKETS_IN_SNAPSHOT
      4. Always include markets with active positions (the LLM needs context)
    """
    # Separate markets with positions (always include)
    position_symbols = set()
    if active_positions:
        position_symbols = {p.get("symbol", "") for p in active_positions}

    # Filter to markets with meaningful signals
    active_markets = []
    position_markets = []

    for m in markets:
        has_signal = any(s.confidence > MIN_SIGNAL_CONFIDENCE for s in m.signals)
        in_position = m.symbol in position_symbols

        if in_position:
            position_markets.append(m)
        elif has_signal:
            active_markets.append(m)

    # Sort by strongest signal
    active_markets.sort(
        key=lambda m: max((s.confidence for s in m.signals), default=0),
        reverse=True,
    )

    # Cap: position markets always included, fill remainder with top signals
    remaining_slots = MAX_MARKETS_IN_SNAPSHOT - len(position_markets)
    selected = position_markets + active_markets[:max(remaining_slots, 0)]

    # Truncate memory (increased from 500 to 1500 for richer context)
    trimmed_memory = None
    if memory_summary:
        trimmed_memory = memory_summary[:1500]

    return LLMInputSnapshot(
        markets=selected,
        global_context=global_context,
        memory_summary=trimmed_memory,
        active_positions=active_positions or [],
        trigger_reason=trigger_reason,
        trigger_context=trigger_context,
    )


def snapshot_to_json(snapshot: LLMInputSnapshot, compact: bool = True) -> str:
    """Serialize snapshot to JSON for the LLM.

    compact=True: Uses short keys, strips nulls/zeros, aggressive rounding.
                  Saves ~30-40% tokens vs verbose mode.
    compact=False: Full verbose format (for debugging).
    """
    if compact:
        return json.dumps(_to_compact_dict(snapshot), separators=(",", ":"))
    return json.dumps(snapshot.to_dict(), separators=(",", ":"))


def _to_compact_dict(snapshot: LLMInputSnapshot) -> dict:
    """Compact snapshot serialization.

    Short keys, stripped nulls/zeros, aggressive rounding.
    Saves ~30-40% tokens compared to verbose to_dict().

    Key mapping:
      markets -> m, symbol -> s, price -> p, signals -> sg
      price_change_1h_pct -> d1h, price_change_24h_pct -> d24h
      volume_ratio -> vr, volatility -> vol
      funding_rate -> fr, oi_change_pct -> oi
      strategy -> st, side -> sd, confidence -> c, regime -> rg
      global -> g, trigger -> t, memory -> mem
      positions -> pos, equity -> eq, daily_pnl -> pnl
    """
    result = {}

    # Markets (compact)
    compact_markets = []
    for m in snapshot.markets:
        cm = {"s": m.symbol, "p": _round_price(m.price)}

        # Only include non-zero changes
        if abs(m.price_change_1h_pct) >= 0.01:
            cm["d1h"] = round(m.price_change_1h_pct, 1)
        if abs(m.price_change_24h_pct) >= 0.01:
            cm["d24h"] = round(m.price_change_24h_pct, 1)
        if abs(m.volume_ratio - 1.0) >= 0.05:
            cm["vr"] = round(m.volume_ratio, 1)
        if m.volatility >= 0.01:
            cm["vol"] = round(m.volatility, 2)
        if m.funding_rate is not None and abs(m.funding_rate) >= 0.0001:
            cm["fr"] = round(m.funding_rate, 4)
        if m.open_interest_change_pct is not None and abs(m.open_interest_change_pct) >= 0.1:
            cm["oi"] = round(m.open_interest_change_pct, 1)

        # Signals (compact, skip neutral/low-confidence)
        # Inject regime fitness per strategy so LLM knows signal reliability
        from llm.agents.shared_context import STRATEGY_REGIME_FIT
        _gc = snapshot.global_context
        _dominant_regime = _gc.extra.get("dominant_regime", "unknown") if _gc and _gc.extra else "unknown"
        _regime_fit_map = STRATEGY_REGIME_FIT.get(_dominant_regime, {})

        sigs = []
        for s in m.signals:
            if s.confidence < 0.2 and s.side == "neutral":
                continue  # Skip noise
            sig = {"st": s.strategy, "sd": s.side, "c": round(s.confidence, 2)}
            if s.regime_score and s.regime_score >= 0.1:
                sig["rg"] = round(s.regime_score, 2)
            # Add regime fitness: strong/moderate/weak/avoid
            _fit = _regime_fit_map.get(s.strategy)
            if _fit and _fit != "moderate":  # Only flag non-neutral fitness
                sig["rf"] = _fit  # regime_fit: strong/weak/avoid
            if s.meta:
                sig["meta"] = s.meta
            sigs.append(sig)
        if sigs:
            cm["sg"] = sigs

        compact_markets.append(cm)

    result["m"] = compact_markets

    # Global context (compact)
    g = snapshot.global_context
    result["g"] = {
        "btc": _round_price(g.btc_price),
        "b1h": round(g.btc_change_1h_pct, 1),
        "b24h": round(g.btc_change_24h_pct, 1),
        "eb": round(g.eth_btc_ratio, 4),
        "pos": g.total_open_positions,
        "pnl": round(g.daily_pnl, 1),
        "eq": round(g.equity, 0),
    }
    if g.circuit_breaker_active:
        result["g"]["cb"] = True

    # Loss streak context: recent outcomes and consecutive losses
    # Source from extra dict (populated by main bot from risk manager state)
    if g.extra:
        if g.extra.get("consecutive_losses", 0) > 0:
            result["g"]["closs"] = g.extra["consecutive_losses"]
        if g.extra.get("recent_outcomes"):
            result["g"]["rout"] = g.extra["recent_outcomes"]  # e.g., "WWLLL"
        if g.extra.get("daily_win_rate") is not None:
            result["g"]["dwr"] = round(g.extra["daily_win_rate"], 2)

    # Global Brain context (bias, funding, sectors)
    if g.extra:
        if g.extra.get("global_bias") and g.extra["global_bias"] != "neutral":
            result["g"]["gbias"] = g.extra["global_bias"]
        if g.extra.get("net_funding") and abs(g.extra["net_funding"]) >= 0.0001:
            result["g"]["nfr"] = round(g.extra["net_funding"], 5)
        # Portfolio snapshot (compact)
        _ps = g.extra.get("portfolio_snapshot")
        if _ps and _ps.get("total_positions", 0) > 0:
            result["g"]["pf"] = {
                "n": _ps["total_positions"],
                "lv": _ps.get("total_leverage", 0),
                "net": _ps.get("net_exposure_pct", 0),
                "conc": _ps.get("concentration_pct", 0),
            }
        # Risk profile
        if g.extra.get("risk_profile"):
            result["g"]["rprof"] = g.extra["risk_profile"][:40]
        if g.extra.get("dynamic_leverage_cap"):
            result["g"]["dlcap"] = round(g.extra["dynamic_leverage_cap"], 0)
        # Deep memory edge map: setup type win rates for Trade/Critic
        if g.extra.get("setup_edge_map"):
            result["g"]["edge"] = g.extra["setup_edge_map"]
        if g.extra.get("strategy_performance"):
            result["g"]["stperf"] = g.extra["strategy_performance"]
        if g.extra.get("confluence_wr"):
            result["g"]["confl_wr"] = g.extra["confluence_wr"]
        # Scout Agent preparation (pre-formed theses, watchlist priority)
        if g.extra.get("scout_preparation"):
            result["g"]["scout"] = g.extra["scout_preparation"]
        # LLM self-performance stats for calibration
        if g.extra.get("llm_self_performance"):
            result["g"]["selfperf"] = g.extra["llm_self_performance"]
        # Counterfactual stats (veto accuracy for Critic calibration)
        if g.extra.get("counterfactual_stats"):
            _cf = g.extra["counterfactual_stats"]
            result["g"]["cf"] = {
                k: v for k, v in _cf.items()
                if k in ("veto_accuracy", "vetoes_saved_pnl", "vetoes_missed_pnl", "total_vetoes")
            } if isinstance(_cf, dict) else _cf
        # Adaptive risk (streak + recent WR for sizing awareness)
        if g.extra.get("adaptive_risk"):
            result["g"]["arisk"] = g.extra["adaptive_risk"]
        # Portfolio risk budget utilization
        if g.extra.get("portfolio_risk_budget"):
            result["g"]["rbudget"] = g.extra["portfolio_risk_budget"]
        # Survival accountability context
        if g.extra.get("survival_status"):
            _ss = g.extra["survival_status"]
            if isinstance(_ss, str):
                result["g"]["surv"] = _ss[:100]
            elif isinstance(_ss, dict):
                result["g"]["surv"] = _ss

    # Trigger
    if snapshot.trigger_reason:
        result["t"] = snapshot.trigger_reason
        if snapshot.trigger_context:
            result["tc"] = snapshot.trigger_context[:200]

    # Memory (compact)
    if snapshot.memory_summary:
        result["mem"] = snapshot.memory_summary

    # Active positions (compact)
    if snapshot.active_positions:
        result["pos"] = [
            {
                "s": p.get("symbol", ""),
                "sd": p.get("side", ""),
                "e": p.get("entry", 0),
                "lv": p.get("leverage", 1),
                "pnl": round(p.get("unrealized_pnl", 0), 1),
            }
            for p in snapshot.active_positions
        ]

    # Growth intelligence context (knowledge, hypotheses, recent outcomes)
    try:
        from llm.growth.orchestrator import get_growth_orchestrator
        growth_ctx = get_growth_orchestrator().get_llm_context()
        if growth_ctx:
            # Truncate to save tokens (max ~400 chars)
            result["growth"] = growth_ctx[:400]
    except Exception as e:
        logger.warning(f"[SNAPSHOT] Growth context unavailable: {e}")

    # Survival pressure context — constant accountability awareness
    try:
        from llm.survival_pressure import get_survival_context_for_llm
        survival_ctx = get_survival_context_for_llm()
        if survival_ctx:
            result["survival"] = survival_ctx[:500]
    except Exception as e:
        logger.warning(f"[SNAPSHOT] Survival context unavailable: {e}")

    # ── Shared symbol/regime extraction for knowledge modules ──
    _known_symbols = {"BTC", "ETH", "SOL", "HYPE", "DOGE", "PEPE", "FARTCOIN"}
    _known_regimes = {"trend", "trending", "range", "ranging", "volatile", "panic", "consolidation"}
    _ctx_symbol = ""
    _ctx_regime = ""
    if snapshot.trigger_context:
        for _word in snapshot.trigger_context.split():
            if _word.upper() in _known_symbols and not _ctx_symbol:
                _ctx_symbol = _word.upper()
            if _word.lower() in _known_regimes and not _ctx_regime:
                _ctx_regime = _word.lower()

    # Dynamic token budget: more for high-value triggers
    _trigger = snapshot.trigger_reason or ""
    _high_value_trigger = _trigger in (
        "pre_trade_veto", "regime_shift", "high_confidence_signal",
    )

    # Knowledge base injection — axioms, principles, anti-patterns
    try:
        from llm.self_teaching import get_teaching_engine
        engine = get_teaching_engine()
        knowledge_ctx = engine.get_knowledge_for_prompt(
            symbol=_ctx_symbol, regime=_ctx_regime
        )
        if knowledge_ctx:
            _teach_limit = 800 if _high_value_trigger else 600
            result["knowledge"] = knowledge_ctx[:_teach_limit]
    except Exception as e:
        logger.warning(f"[SNAPSHOT] Teaching engine unavailable: {e}")
        result["knowledge"] = "Teaching engine unavailable — rely on memory notes and market data."

    # Deep memory: full knowledge summary (trade DNA, strategy fingerprints,
    # pattern library, regime history, insights) via singleton manager
    try:
        from llm.deep_memory import get_deep_memory
        dm = get_deep_memory()
        _dm_limit = 1200 if _high_value_trigger else 800
        knowledge = dm.build_llm_knowledge_summary(
            symbol=_ctx_symbol, regime=_ctx_regime
        )
        if knowledge:
            result["deep_memory"] = knowledge[:_dm_limit]
    except Exception as e:
        logger.debug(f"[SNAPSHOT] Deep memory unavailable: {e}")

    # Few-shot examples: similar past trades from deep memory
    try:
        from llm.few_shot import build_few_shot_examples
        if _ctx_symbol:
            _fs_side = ""
            if snapshot.trigger_context:
                for _word in snapshot.trigger_context.split():
                    if _word.upper() in ("LONG", "SHORT", "BUY", "SELL"):
                        _fs_side = _word.upper()
                        break
            few_shot = build_few_shot_examples(
                symbol=_ctx_symbol,
                side=_fs_side,
                regime=_ctx_regime,
                max_examples=3,
                max_chars=500,
            )
            if few_shot:
                result["examples"] = few_shot
    except Exception as e:
        logger.debug(f"[SNAPSHOT] Few-shot examples unavailable: {e}")

    # Self-performance stats — the LLM's mirror for self-calibration
    try:
        from llm.self_performance import get_compact_stats
        self_perf = get_compact_stats()
        if self_perf:
            result["self_perf"] = self_perf
    except Exception as e:
        logger.debug(f"[SNAPSHOT] Self-performance unavailable: {e}")

    # Recent decisions: the LLM's own decision trail for consistency
    try:
        from llm.decision_engine import get_recent_decisions
        recent = get_recent_decisions(5)
        if recent:
            now = time.time()
            lines = []
            for d in reversed(recent[-3:]):  # Last 3 only for token efficiency
                age_m = int((now - d.get("ts", 0)) / 60)
                action = d.get("a", "?")
                sym = d.get("sym", "")
                conf = d.get("c", 0)
                regime = d.get("rg", "")
                gate = d.get("gate", "")
                line = f"{age_m}m: {action} {sym} c={conf:.2f} {regime}"
                if gate:
                    line += f" ({gate})"
                lines.append(line)
            result["recent_dec"] = " | ".join(lines)
    except Exception as e:
        logger.debug(f"[SNAPSHOT] Recent decisions unavailable: {e}")

    # Recent post-trade lessons: immediate feedback from closed trades
    try:
        from llm.post_trade_learner import get_recent_lessons
        lessons = get_recent_lessons(3)
        if lessons:
            result["recent_lessons"] = " | ".join(lessons)
    except Exception:
        pass

    # Trade autopsy: structured analysis of recent trade batch
    try:
        from llm.trade_autopsy import get_cached_autopsy
        autopsy = get_cached_autopsy()
        if autopsy:
            result["autopsy"] = autopsy
    except Exception:
        pass

    # Portfolio-level risk indicators (injected by main bot via global_ctx.extra)
    if g and g.extra:
        corr_risk = g.extra.get("correlation_risk")
        if corr_risk and corr_risk != "low":
            result["corr_risk"] = corr_risk
        port_lev = g.extra.get("portfolio_leverage", 0)
        if port_lev > 0:
            result["port_lev"] = port_lev
        daily_funding = g.extra.get("estimated_daily_funding_cost", 0)
        if daily_funding > 0.01:
            result["funding_cost_pct"] = round(daily_funding, 2)
        # D5: Session performance (win rates by trading session)
        session_perf = g.extra.get("session_performance")
        if session_perf:
            result["session_perf"] = session_perf
        # E2: Regime transitions in progress
        transitions = g.extra.get("regime_transitions")
        if transitions:
            result["regime_shifts"] = transitions

        # Cross-symbol lead-lag signals: active signals where a leader moved
        # and a follower is expected to follow (e.g., BTC dropped, SOL expected to drop)
        cs_signals = g.extra.get("cross_symbol_signals")
        if cs_signals:
            result["cross_sym"] = cs_signals

        # Cross-symbol confirmed patterns: historically validated lead-lag relationships
        cs_patterns = g.extra.get("cross_symbol_patterns")
        if cs_patterns:
            result["cross_pat"] = cs_patterns

    # Funding cost reminder — injected when positions are open
    if snapshot.active_positions:
        funding_notes = []
        for p in snapshot.active_positions:
            fr = p.get("funding_rate", 0)
            side = p.get("side", "").lower()
            sym = p.get("symbol", "")
            lev = p.get("leverage", 1)
            if fr and abs(fr) >= 0.0001:
                daily_cost = abs(fr) * 3 * lev * 100  # 3 payments/day, as % of position
                if (side in ("long", "buy") and fr > 0) or (side in ("short", "sell") and fr < 0):
                    funding_notes.append(
                        f"{sym}: PAYING {abs(fr)*100:.3f}%/8h funding ({daily_cost:.2f}%/day at {lev}x)"
                    )
                else:
                    funding_notes.append(
                        f"{sym}: EARNING {abs(fr)*100:.3f}%/8h funding"
                    )
        if funding_notes:
            result["funding_alert"] = " | ".join(funding_notes)

    return result


def _round_price(price: float) -> float:
    """Round price to appropriate precision based on magnitude."""
    if price == 0:
        return 0
    if price >= 1000:
        return round(price, 1)
    if price >= 1:
        return round(price, 2)
    if price >= 0.001:
        return round(price, 4)
    return round(price, 8)
