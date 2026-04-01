"""
Prompt Enricher: injects latest quant intelligence into agent prompts at runtime.

Reads from:
  - insight_journal.json — validated quant findings
  - strategy_fingerprints.json — per-setup WR data
  - sim_status.json — current sim equity and open positions
  - trades.csv — recent trade outcomes

Each agent gets a tailored "QUANT INTELLIGENCE BRIEFING" appended to its prompt,
plus a "RECENT PERFORMANCE" section with last 10 trade outcomes.

Results are cached for 1 hour to avoid re-reading files every LLM call.
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

# ── Cache ───────────────────────────────────────────────────────
_CACHE_TTL_S = 3600  # 1 hour
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

    _cache = {
        "insights": insights,
        "fingerprints": fingerprints,
        "sim_status": sim_status,
        "recent_trades": recent_trades,
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


def enrich_prompt(agent_role: str, base_prompt: str) -> str:
    """Enrich an agent's base prompt with the latest quant intelligence.

    Appends:
      1. QUANT INTELLIGENCE BRIEFING — top 5 relevant insights by confidence
      2. SETUP EDGE DATA — per-setup WR from strategy_fingerprints
      3. SIM STATUS — current sim equity and performance
      4. RECENT PERFORMANCE — last 10 trade outcomes from trades.csv

    Args:
        agent_role: Agent role string (e.g., "regime", "trade", "risk")
        base_prompt: The static agent prompt from prompts.py

    Returns:
        Enriched prompt with appended intelligence sections.
        Total appended section is capped at ~500 tokens (~2000 chars).
    """
    _refresh_cache()

    sections = []

    # 1. Quant intelligence briefing
    briefing = _build_quant_briefing(agent_role)
    if briefing:
        sections.append(briefing)

    # 2. Setup edge data (fingerprints)
    fingerprint_summary = _build_fingerprint_summary(agent_role)
    if fingerprint_summary:
        sections.append(fingerprint_summary)

    # 3. Sim status (for trade-facing agents)
    if agent_role in ("trade", "risk", "critic", "exit", "overseer"):
        sim_summary = _build_sim_status_summary()
        if sim_summary:
            sections.append(sim_summary)

    # 4. Recent performance (for decision-making agents)
    if agent_role in ("trade", "risk", "critic", "exit", "learning", "overseer"):
        perf = _build_recent_performance()
        if perf:
            sections.append(perf)

    if not sections:
        return base_prompt

    # Join all sections and enforce token budget
    enrichment = "\n\n".join(sections)
    if len(enrichment) > _MAX_BRIEFING_CHARS:
        enrichment = enrichment[:_MAX_BRIEFING_CHARS - 3] + "..."

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

    return {
        "total_insights": len(insights),
        "validated_insights": validated,
        "insights_by_category": cats,
        "recent_trades_loaded": len(trades),
        "fingerprints_setups": list(fps.keys()),
        "sim_equity": sim.get("current_equity"),
        "cache_age_s": round(get_cache_age_seconds(), 0),
    }
