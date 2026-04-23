"""
Prompt Enricher: injects latest quant intelligence into agent prompts at runtime.

Reads from:
  - insight_journal.json — validated quant findings
  - strategy_fingerprints.json — per-setup WR data
  - sim_status.json — current sim equity and open positions
  - trades.csv — recent trade outcomes
  - teaching/knowledge_base.json — graduated rules (written never read until now)
  - meta_learning/insights.json — cross-trade pattern analysis
  - overseer_memo.json — latest Overseer recommendations (written by run_overseer)
  - feedback/adaptive_risk_state.json — real-time streak + regime WR

Each agent gets a tailored "QUANT INTELLIGENCE BRIEFING" appended to its prompt,
plus validated rules, meta-patterns, overseer memo, and recent performance.

Results are cached for 30 min to balance freshness vs disk I/O.
"""

import csv
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.llm.agents.prompt_enricher")

# ── Paths ───────────────────────────────────────────────────────
_DATA_DIR = os.path.join("data")
_DEEP_MEMORY_DIR = os.path.join(_DATA_DIR, "llm", "deep_memory")
_INSIGHT_PATH = os.path.join(_DEEP_MEMORY_DIR, "insight_journal.json")
_FINGERPRINTS_PATH = os.path.join(_DEEP_MEMORY_DIR, "strategy_fingerprints.json")
_SIM_STATUS_PATH = os.path.join(_DATA_DIR, "manual", "sim_status.json")
_TRADES_CSV_PATH = os.path.join(_DATA_DIR, "trades.csv")
_KB_PATH = os.path.join(_DATA_DIR, "llm", "teaching", "knowledge_base.json")
_META_PATH = os.path.join(_DATA_DIR, "meta_learning", "insights.json")
_OVERSEER_MEMO_PATH = os.path.join(_DATA_DIR, "llm", "overseer_memo.json")
_ADAPTIVE_RISK_PATH = os.path.join(_DATA_DIR, "feedback", "adaptive_risk_state.json")
_CIRCUIT_BREAKER_PATH = os.path.join(_DATA_DIR, "circuit_breaker_state.json")
_PERFORMANCE_PATH = os.path.join(_DATA_DIR, "analysis", "performance.json")

# ── Cache ───────────────────────────────────────────────────────
_CACHE_TTL_S = 1800  # 30 min — balance freshness vs I/O
_cache: Dict[str, Any] = {}
_cache_ts: float = 0.0

# ── Category → Agent Relevance Mapping ──────────────────────────
# Which insight categories are most relevant to which agent roles.
# Each agent gets insights from its primary categories first, then general ones.
_AGENT_CATEGORY_MAP: Dict[str, List[str]] = {
    "regime": [
        "regime_insight", "correlation_insight", "timing_insight", "meta_insight",
    ],
    "trade": [
        "strategy_insight", "symbol_insight", "timing_insight",
        "execution_insight", "correlation_insight", "meta_insight",
    ],
    "risk": [
        "risk_insight", "execution_insight", "symbol_insight", "meta_insight",
    ],
    "critic": [
        "strategy_insight", "risk_insight", "meta_insight",
        "execution_insight", "regime_insight",
    ],
    "exit": [
        "execution_insight", "risk_insight", "timing_insight",
        "symbol_insight", "meta_insight",
    ],
    "scout": [
        "correlation_insight", "regime_insight", "strategy_insight",
        "symbol_insight", "timing_insight",
    ],
    "learning": [
        "meta_insight", "strategy_insight", "risk_insight",
        "execution_insight",
    ],
    "overseer": [
        "meta_insight", "strategy_insight", "risk_insight",
        "execution_insight", "regime_insight",
    ],
    "quant": [
        "strategy_insight", "execution_insight", "risk_insight",
        "correlation_insight", "timing_insight", "symbol_insight",
    ],
}

# Max insights per agent to keep token budget tight
_MAX_INSIGHTS_PER_AGENT = 5
# Max token budget per agent briefing (approximate via char count: ~4 chars/token)
_MAX_BRIEFING_CHARS = 2000  # ~500 tokens


def _load_json_safe(path: str, default: Any = None) -> Any:
    """Load JSON file safely, returning default on any error."""
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError, OSError) as e:
        logger.debug(f"[ENRICHER] Failed to load {path}: {e}")
        return default if default is not None else {}


def _load_recent_trades(path: str, max_trades: int = 10) -> List[Dict[str, str]]:
    """Load the last N trades from trades.csv."""
    if not os.path.exists(path):
        return []
    try:
        trades = []
        with open(path, "r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                trades.append(row)
        # Return last N trades
        return trades[-max_trades:]
    except (IOError, OSError, csv.Error) as e:
        logger.debug(f"[ENRICHER] Failed to load trades CSV: {e}")
        return []


def _refresh_cache() -> None:
    """Reload all data sources if cache is stale."""
    global _cache, _cache_ts

    now = time.time()
    if now - _cache_ts < _CACHE_TTL_S and _cache:
        return  # Cache still fresh

    logger.info("[ENRICHER] Refreshing quant intelligence cache")

    insights_data = _load_json_safe(_INSIGHT_PATH, {"insights": []})
    insights = insights_data.get("insights", [])

    fingerprints = _load_json_safe(_FINGERPRINTS_PATH, {})
    sim_status = _load_json_safe(_SIM_STATUS_PATH, {})
    recent_trades = _load_recent_trades(_TRADES_CSV_PATH, max_trades=10)

    kb_data = _load_json_safe(_KB_PATH, {"entries": []})
    kb_entries = kb_data.get("entries", [])

    meta_data = _load_json_safe(_META_PATH, {"insights": []})
    meta_insights = meta_data.get("insights", [])

    overseer_memo = _load_json_safe(_OVERSEER_MEMO_PATH, {})
    adaptive_risk = _load_json_safe(_ADAPTIVE_RISK_PATH, {})
    circuit_breaker = _load_json_safe(_CIRCUIT_BREAKER_PATH, {})
    performance = _load_json_safe(_PERFORMANCE_PATH, {})

    _cache = {
        "insights": insights,
        "fingerprints": fingerprints,
        "sim_status": sim_status,
        "recent_trades": recent_trades,
        "kb_entries": kb_entries,
        "meta_insights": meta_insights,
        "overseer_memo": overseer_memo,
        "adaptive_risk": adaptive_risk,
        "circuit_breaker": circuit_breaker,
        "performance": performance,
    }
    _cache_ts = now


def _select_insights_for_agent(
    agent_role: str,
    insights: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Select the top N most relevant insights for an agent.

    Strategy:
      1. Filter to categories relevant to this agent
      2. Sort by confidence (desc), then by validation_count (desc), then recency (desc)
      3. Take top N
    """
    relevant_categories = _AGENT_CATEGORY_MAP.get(agent_role, [])
    if not relevant_categories:
        # Fallback: all categories
        relevant_categories = list(set(
            cat for cats in _AGENT_CATEGORY_MAP.values() for cat in cats
        ))

    # Filter to relevant categories
    relevant = [
        ins for ins in insights
        if ins.get("category", "") in relevant_categories
    ]

    # Sort: validated first, then by confidence desc, then by validation_count desc, then recency
    def sort_key(ins: Dict[str, Any]) -> Tuple:
        return (
            1 if ins.get("validated", False) else 0,
            ins.get("confidence", 0),
            ins.get("validation_count", 0),
            ins.get("ts", 0),
        )

    relevant.sort(key=sort_key, reverse=True)
    return relevant[:_MAX_INSIGHTS_PER_AGENT]


def _format_insight(ins: Dict[str, Any], idx: int) -> str:
    """Format a single insight into a compact line."""
    conf = ins.get("confidence", 0)
    validated = ins.get("validated", False)
    val_count = ins.get("validation_count", 0)
    tag = "VALIDATED" if validated else "UNVALIDATED"
    source = ins.get("source", "unknown")
    text = ins.get("insight", "")
    # Truncate long insights
    if len(text) > 200:
        text = text[:197] + "..."
    return f"  {idx}. [{tag} conf={conf:.0%} n={val_count}] {text}"


def _build_quant_briefing(agent_role: str) -> str:
    """Build the QUANT INTELLIGENCE BRIEFING section for an agent."""
    insights = _cache.get("insights", [])
    if not insights:
        return ""

    selected = _select_insights_for_agent(agent_role, insights)
    if not selected:
        return ""

    lines = ["=== QUANT INTELLIGENCE BRIEFING ==="]
    for i, ins in enumerate(selected, 1):
        lines.append(_format_insight(ins, i))

    return "\n".join(lines)


def _build_fingerprint_summary(agent_role: str) -> str:
    """Build a compact setup-edge summary from strategy_fingerprints.json."""
    fps = _cache.get("fingerprints", {})
    if not fps:
        return ""

    # Only include for trade-relevant agents
    if agent_role not in ("trade", "risk", "critic", "exit", "quant", "overseer", "scout"):
        return ""

    lines = []
    # Ensemble-level stats
    ensemble = fps.get("ensemble", {})
    if ensemble.get("total", 0) > 0:
        total = ensemble["total"]
        wins = ensemble.get("wins", 0)
        pnl = ensemble.get("pnl", 0)
        wr = (wins / total * 100) if total > 0 else 0
        lines.append(f"  Ensemble: {wins}W/{total - wins}L ({wr:.0f}% WR) PnL=${pnl:.2f}")

    # Per-symbol breakdown
    by_symbol = ensemble.get("by_symbol", {})
    for sym, data in sorted(by_symbol.items()):
        if data.get("total", 0) > 0:
            t = data["total"]
            w = data.get("wins", 0)
            p = data.get("pnl", 0)
            wr = (w / t * 100) if t > 0 else 0
            lines.append(f"  {sym}: {w}W/{t - w}L ({wr:.0f}% WR) PnL=${p:.2f}")

    # Per-regime breakdown
    by_regime = ensemble.get("by_regime", {})
    for regime, data in sorted(by_regime.items()):
        if data.get("total", 0) > 0:
            t = data["total"]
            w = data.get("wins", 0)
            wr = (w / t * 100) if t > 0 else 0
            lines.append(f"  Regime={regime}: {w}W/{t - w}L ({wr:.0f}% WR)")

    if not lines:
        return ""

    return "=== SETUP EDGE DATA ===\n" + "\n".join(lines)


def _build_sim_status_summary() -> str:
    """Build a compact sim status summary."""
    sim = _cache.get("sim_status", {})
    if not sim or not sim.get("total_trades"):
        return ""

    equity = sim.get("current_equity", 0)
    start = sim.get("starting_equity", 100)
    total = sim.get("total_trades", 0)
    wr = sim.get("win_rate", 0)
    pf = sim.get("profit_factor", 0)
    dd = sim.get("max_drawdown", 0)
    streak = sim.get("current_streak", 0)
    daily = sim.get("daily_pnl", 0)
    weekly = sim.get("weekly_pnl", 0)

    return (
        f"=== SIM STATUS ===\n"
        f"  Equity: ${equity:.1f} (start ${start:.0f}) | "
        f"Trades: {total} ({wr:.0f}% WR, PF {pf:.2f}) | "
        f"DD: {dd:.1f}% | Streak: {streak:+d} | "
        f"Day: ${daily:+.2f} Week: ${weekly:+.2f}"
    )


def _build_recent_performance() -> str:
    """Build RECENT PERFORMANCE section from trades.csv."""
    trades = _cache.get("recent_trades", [])
    if not trades:
        return ""

    lines = ["=== RECENT PERFORMANCE (last trades) ==="]
    total_pnl = 0.0
    wins = 0
    count = 0

    for t in trades:
        try:
            sym = t.get("symbol", "?")
            side = t.get("side", "?")
            pnl = float(t.get("pnl", 0))
            outcome = t.get("outcome", "?")
            strategy = t.get("primary_driver", t.get("strategy", "?"))
            regime = t.get("regime", "?")
            lev = t.get("leverage", "?")

            total_pnl += pnl
            count += 1
            if pnl > 0:
                wins += 1

            result = "W" if pnl > 0 else "L"
            lines.append(
                f"  {result} {sym} {side} ${pnl:+.2f} "
                f"(strat={strategy} regime={regime} lev={lev}x)"
            )
        except (ValueError, TypeError):
            continue

    if count > 0:
        wr = wins / count * 100
        lines.append(f"  Summary: {wins}W/{count - wins}L ({wr:.0f}% WR) Total=${total_pnl:+.2f}")

    return "\n".join(lines)


_KB_CATEGORY_MAP: Dict[str, List[str]] = {
    "regime": ["general", "regime", "correlation"],
    "trade": ["general", "strategy", "execution", "timing"],
    "risk": ["general", "risk", "execution"],
    "critic": ["general", "strategy", "risk"],
    "exit": ["general", "execution", "risk", "timing"],
    "scout": ["general", "strategy", "regime"],
    "overseer": ["general", "strategy", "risk", "regime"],
    "quant": ["general", "strategy", "execution", "risk"],
    "learning": ["general", "strategy", "risk"],
}


def _build_knowledge_base_rules(agent_role: str) -> str:
    """Inject validated rules from knowledge_base.json into agent prompt.

    Filters to high-confidence entries with evidence (evidence_count > 0 OR
    source == 'seed' with confidence >= 0.9) relevant to the agent's role.
    Returns empty string if no entries available.
    """
    entries = _cache.get("kb_entries", [])
    if not entries:
        return ""

    relevant_cats = _KB_CATEGORY_MAP.get(agent_role, ["general"])
    relevant = [
        e for e in entries
        if e.get("category", "general") in relevant_cats
        and (
            e.get("evidence_count", 0) > 0
            or (e.get("source") == "seed" and e.get("confidence", 0) >= 0.9)
        )
        and e.get("confidence", 0) >= 0.7
    ]
    if not relevant:
        return ""

    # Sort: most evidence first, then confidence
    relevant.sort(
        key=lambda e: (e.get("evidence_count", 0), e.get("confidence", 0)),
        reverse=True,
    )
    top = relevant[:5]

    lines = ["=== VALIDATED TRADING RULES ==="]
    for e in top:
        conf = e.get("confidence", 0)
        n = e.get("evidence_count", 0)
        text = str(e.get("content", e.get("rule", "")) or "")[:180]
        lines.append(f"  • [conf={conf:.0%} n={n}] {text}")

    return "\n".join(lines)


def _build_meta_patterns() -> str:
    """Surface top cross-trade patterns from meta_learning/insights.json.

    Filters to high-confidence, evidence-backed entries. Returns empty if none.
    """
    meta = _cache.get("meta_insights", [])
    if not meta:
        return ""

    qualified = [
        m for m in meta
        if m.get("confidence", 0) >= 0.60
        and m.get("evidence_count", 0) >= 3
    ]
    if not qualified:
        return ""

    qualified.sort(key=lambda m: (m.get("confidence", 0), m.get("evidence_count", 0)), reverse=True)
    top = qualified[:3]

    lines = ["=== META-LEARNING PATTERNS ==="]
    for m in top:
        conf = m.get("confidence", 0)
        n = m.get("evidence_count", 0)
        desc = str(m.get("description", m.get("insight", "")) or "")[:160]
        suggestion = str(m.get("actionable_suggestion", "") or "")[:80]
        line = f"  • [conf={conf:.0%} n={n}] {desc}"
        if suggestion:
            line += f" → {suggestion}"
        lines.append(line)

    return "\n".join(lines)


def _build_overseer_memo(agent_role: str) -> str:
    """Inject latest Overseer recommendations into downstream agent prompts.

    Overseer runs ~hourly and writes to overseer_memo.json. Trade/Risk/Critic/Exit
    agents read this so system-level insights from the last portfolio review
    persist between pipeline runs (scratchpad is cleared each run; this isn't).
    """
    memo = _cache.get("overseer_memo", {})
    if not memo:
        return ""

    # Only inject for decision-making agents, not regime/scout/learning
    if agent_role not in ("trade", "risk", "critic", "exit", "quant"):
        return ""

    recs = memo.get("recommendations", [])
    health = memo.get("health", "")
    strategy_adj = memo.get("strategy_adjustments", "")
    ts = memo.get("timestamp", 0)

    # Only use if memo is less than 2 hours old
    if ts and (time.time() - ts) > 7200:
        return ""

    lines = ["=== OVERSEER PORTFOLIO MEMO ==="]
    if health:
        lines.append(f"  Health: {str(health)[:100]}")
    if strategy_adj:
        lines.append(f"  Strategy: {str(strategy_adj)[:120]}")
    for r in recs[:3]:
        lines.append(f"  Rec: {str(r)[:120]}")

    if len(lines) <= 1:
        return ""

    return "\n".join(lines)


def _build_system_health_context() -> str:
    """Inject circuit breaker state + rolling performance for all decision agents.

    Critical: if the CB is tripped or close, agents must know to be defensive.
    Rolling WR (last 20/50 trades) + avg R:R gives agents live performance context.
    """
    lines = []

    # Circuit breaker state
    cb = _cache.get("circuit_breaker", {})
    if cb:
        tripped = cb.get("tripped", False)
        daily_pnl = cb.get("daily_pnl", 0)
        consec = cb.get("consecutive_losses", 0)
        peak = cb.get("peak_equity", 0)
        reason = cb.get("trip_reason", "")

        if tripped:
            lines.append(f"  ⚠ CB TRIPPED: {reason} (daily_pnl=${daily_pnl:.1f})")
        else:
            # Warn if approaching limits
            if consec >= 3:
                lines.append(f"  ⚠ CB WARNING: {consec} consecutive losses")
            elif daily_pnl < 0 and peak > 0:
                dd_pct = abs(daily_pnl) / peak * 100
                if dd_pct > 4:
                    lines.append(f"  CB PROXIMITY: daily DD={dd_pct:.1f}% (limit=8%) — be defensive")

    # Rolling performance stats
    perf = _cache.get("performance", {})
    if perf:
        wr20 = perf.get("win_rate_20")
        wr50 = perf.get("win_rate_50")
        avg_rr = perf.get("avg_rr")
        total = perf.get("total_trades", 0)
        parts = []
        if wr20 is not None:
            parts.append(f"WR_20={wr20:.0%}")
        if wr50 is not None:
            parts.append(f"WR_50={wr50:.0%}")
        if avg_rr is not None:
            parts.append(f"avg_RR={avg_rr:.2f}")
        if total:
            parts.append(f"n={total}")
        if parts:
            lines.append(f"  System: {' | '.join(parts)}")

    if not lines:
        return ""

    return "=== SYSTEM HEALTH ===\n" + "\n".join(lines)


def _build_adaptive_risk_context() -> str:
    """Inject hot/cold streak + live regime WR from adaptive_risk_state.json.

    This is the single most actionable real-time signal: consecutive losses
    mean the system is in a bad regime and should reduce risk. Consecutive wins
    mean the edge is alive. Regime WR shows which regimes are currently paying.
    """
    ar = _cache.get("adaptive_risk", {})
    if not ar:
        return ""

    lines = []

    # Recent streak
    outcomes = ar.get("recent_outcomes", [])
    if outcomes:
        recent = outcomes[-10:]  # last 10
        wins = sum(1 for o in recent if o)
        total = len(recent)
        streak = 0
        last = outcomes[-1] if outcomes else None
        for o in reversed(outcomes):
            if o == last:
                streak += 1
            else:
                break

        streak_desc = f"{'WIN' if last else 'LOSS'} streak={streak}"
        lines.append(f"  Recent: {wins}/{total} WR={wins/total:.0%} | {streak_desc}")
        if streak >= 3 and not last:
            lines.append(f"  ⚠ COLD STREAK: {streak} consecutive losses — reduce sizing")
        elif streak >= 3 and last:
            lines.append(f"  ✓ HOT STREAK: {streak} consecutive wins — edge alive")

    # Live regime WR
    regime_wr = ar.get("regime_wr", {})
    if regime_wr:
        rlines = []
        for rg, stats in regime_wr.items():
            w = stats.get("wins", 0)
            t = stats.get("total", 0)
            if t >= 3:
                rlines.append(f"{rg}: {w}/{t}={w/t:.0%}")
        if rlines:
            lines.append(f"  Live regime WR: {' | '.join(rlines)}")

    if not lines:
        return ""

    return "=== REAL-TIME RISK STATE ===\n" + "\n".join(lines)


def enrich_prompt(agent_role: str, base_prompt: str) -> str:
    """Enrich an agent's base prompt with the latest quant intelligence.

    Appends:
      1. QUANT INTELLIGENCE BRIEFING — top 5 relevant insights by confidence
      2. VALIDATED TRADING RULES — graduated rules from knowledge_base
      3. META-LEARNING PATTERNS — cross-trade statistical patterns
      4. OVERSEER PORTFOLIO MEMO — latest system-level recommendations
      5. SETUP EDGE DATA — per-setup WR from strategy_fingerprints
      6. SIM STATUS — current sim equity and performance
      7. RECENT PERFORMANCE — last 10 trade outcomes from trades.csv
      8. REAL-TIME RISK STATE — hot/cold streak + live regime WR
      9. SYSTEM HEALTH — circuit breaker state, rolling WR, avg R:R

    Args:
        agent_role: Agent role string (e.g., "regime", "trade", "risk")
        base_prompt: The static agent prompt from prompts.py

    Returns:
        Enriched prompt with appended intelligence sections.
        Total appended section is capped at ~500 tokens (~2000 chars).
    """
    _refresh_cache()

    sections = []

    # 1. Quant intelligence briefing (insight_journal — validated live findings)
    briefing = _build_quant_briefing(agent_role)
    if briefing:
        sections.append(briefing)

    # 2. Validated trading rules (knowledge_base — graduated axioms + live evidence)
    kb_rules = _build_knowledge_base_rules(agent_role)
    if kb_rules:
        sections.append(kb_rules)

    # 3. Meta-learning patterns (cross-trade statistical patterns)
    meta = _build_meta_patterns()
    if meta:
        sections.append(meta)

    # 4. Overseer portfolio memo (system-level recommendations, persists between runs)
    overseer = _build_overseer_memo(agent_role)
    if overseer:
        sections.append(overseer)

    # 5. Setup edge data (fingerprints)
    fingerprint_summary = _build_fingerprint_summary(agent_role)
    if fingerprint_summary:
        sections.append(fingerprint_summary)

    # 6. Sim status (for trade-facing agents)
    if agent_role in ("trade", "risk", "critic", "exit", "overseer"):
        sim_summary = _build_sim_status_summary()
        if sim_summary:
            sections.append(sim_summary)

    # 7. Recent performance (for decision-making agents)
    if agent_role in ("trade", "risk", "critic", "exit", "learning", "overseer"):
        perf = _build_recent_performance()
        if perf:
            sections.append(perf)

    # 8. Adaptive risk state (hot/cold streak + live regime WR)
    if agent_role in ("trade", "risk", "critic", "regime", "overseer"):
        adaptive = _build_adaptive_risk_context()
        if adaptive:
            sections.append(adaptive)

    # 9. System health — CB state, rolling WR, R:R (injected into ALL decision agents)
    system_health = _build_system_health_context()
    if system_health:
        sections.append(system_health)

    if not sections:
        return base_prompt

    # Join all sections and enforce token budget (raised to 4000 chars — CLI is $0/call)
    enrichment = "\n\n".join(sections)
    if len(enrichment) > 4000:
        enrichment = enrichment[:3997] + "..."

    return f"{base_prompt}\n\n{enrichment}"


def invalidate_cache() -> None:
    """Force cache refresh on next call. Use after new trades or insights."""
    global _cache_ts
    _cache_ts = 0.0
    logger.info("[ENRICHER] Cache invalidated")


def get_cache_age_seconds() -> float:
    """Return how old the current cache is, in seconds."""
    if _cache_ts == 0.0:
        return float("inf")
    return time.time() - _cache_ts


def get_enrichment_stats() -> Dict[str, Any]:
    """Return stats about the enrichment data for debugging."""
    _refresh_cache()
    insights = _cache.get("insights", [])
    trades = _cache.get("recent_trades", [])
    fps = _cache.get("fingerprints", {})
    sim = _cache.get("sim_status", {})

    # Count by category
    cats: Dict[str, int] = {}
    validated = 0
    for ins in insights:
        cat = ins.get("category", "unknown")
        cats[cat] = cats.get(cat, 0) + 1
        if ins.get("validated"):
            validated += 1

    kb_entries = _cache.get("kb_entries", [])
    meta_insights = _cache.get("meta_insights", [])
    overseer_memo = _cache.get("overseer_memo", {})

    return {
        "total_insights": len(insights),
        "validated_insights": validated,
        "insights_by_category": cats,
        "recent_trades_loaded": len(trades),
        "fingerprints_setups": list(fps.keys()),
        "sim_equity": sim.get("current_equity"),
        "kb_entries": len(kb_entries),
        "meta_insights": len(meta_insights),
        "overseer_memo_age_s": round(time.time() - overseer_memo.get("timestamp", time.time())),
        "cache_age_s": round(get_cache_age_seconds(), 0),
    }
