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
  - llm/growth/hypotheses.json — validated/testing hypotheses from growth tracker

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
_COUNTERFACTUAL_PATH = os.path.join(_DATA_DIR, "counterfactuals", "scenarios.json")
_HYPOTHESES_PATH = os.path.join(_DATA_DIR, "llm", "growth", "hypotheses.json")
_CONFIDENCE_STATE_PATH = os.path.join(_DATA_DIR, "feedback", "confidence_state.json")
_TRADE_DNA_PATH = os.path.join(_DATA_DIR, "llm", "deep_memory", "trade_dna.json")

# ── Staleness / dedup config ────────────────────────────────────
_RULE_MIN_TRADES_FOR_RECOMPUTE = 5   # need >=5 matching trades to trust live accuracy
_RULE_STALE_ACC_FLOOR = 0.40         # graduated rule with live acc < this is dropped
_ALL_TRADES_FOR_RECOMPUTE = 400      # cap rows scanned for rule recompute


def _side_to_buysell(side: str) -> str:
    """trades.csv uses LONG/SHORT; rule conditions use BUY/SELL. Normalize."""
    s = (side or "").strip().upper()
    if s in ("LONG", "BUY"):
        return "BUY"
    if s in ("SHORT", "SELL"):
        return "SELL"
    return s


def _load_all_trades_for_recompute(path: str, cap: int = _ALL_TRADES_FOR_RECOMPUTE) -> List[Dict[str, str]]:
    """Load up to the last `cap` trades from trades.csv for rule-accuracy recompute."""
    if not os.path.exists(path):
        return []
    try:
        rows: List[Dict[str, str]] = []
        with open(path, "r", newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(row)
        return rows[-cap:]
    except (IOError, OSError, csv.Error) as e:
        logger.debug(f"[ENRICHER] Failed to load trades for recompute: {e}")
        return []


def _trade_matches_conditions(trade: Dict[str, str], conditions: Dict[str, Any]) -> bool:
    """Does one trades.csv row satisfy a graduated rule's conditions?

    Only the condition keys present in trades.csv are evaluated (symbol, regime,
    side, strategy). Other condition keys (hour_utc, min_agree, etc.) are not in
    trades.csv, so a rule carrying ONLY those is treated as unrecomputable (caller
    handles via match count == 0).
    """
    c = conditions or {}
    if c.get("symbol") and (trade.get("symbol", "") or "").upper() != str(c["symbol"]).upper():
        return False
    if c.get("side") and _side_to_buysell(trade.get("side", "")) != _side_to_buysell(str(c["side"])):
        return False
    if c.get("strategy"):
        t_strat = (trade.get("primary_driver") or trade.get("strategy") or "")
        if str(c["strategy"]) not in t_strat:
            return False
    if c.get("regime"):
        t_reg = (trade.get("regime", "") or "").lower()
        rule_reg = str(c["regime"]).lower()
        try:
            from llm.regime_canonical import canonicalize_regime
            if canonicalize_regime(t_reg) != canonicalize_regime(rule_reg) and t_reg != rule_reg:
                return False
        except Exception:
            if t_reg != rule_reg:
                return False
    return True


def _recompute_rule_accuracy(conditions: Dict[str, Any], action: str,
                             all_trades: List[Dict[str, str]]) -> Tuple[int, float]:
    """Recompute a graduated rule's live accuracy from trades.csv (recompute-on-read).

    Returns (n_matching_trades, accuracy). accuracy is the fraction of matching
    trades on which the rule's directional advice was CORRECT:
      boost  -> correct when the trade won (pnl>0)
      penalize/veto -> correct when the trade lost (pnl<=0)
    Returns (0, 0.5) when no trades match (unmeasured).
    """
    # A rule with no trades.csv-evaluable condition cannot be scored.
    if not any(k in (conditions or {}) for k in ("symbol", "regime", "side", "strategy")):
        return 0, 0.5
    n = 0
    correct = 0
    act = (action or "").lower()
    for t in all_trades:
        if not _trade_matches_conditions(t, conditions):
            continue
        try:
            pnl = float(t.get("pnl", 0) or 0)
        except (ValueError, TypeError):
            continue
        won = pnl > 0
        n += 1
        if act == "boost" and won:
            correct += 1
        elif act in ("penalize", "veto") and not won:
            correct += 1
    if n == 0:
        return 0, 0.5
    return n, correct / n


def _dedup_and_resolve_graduated(entries: List[Dict[str, Any]],
                                 all_trades: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Collapse graduated-rule entries by canonical (action, conditions) and resolve
    contradictory actions on identical conditions.

    Steps:
      1. Recompute live (n, accuracy) per entry against trades.csv. Drop entries
         that are stale==True, invalidation_count>=3, or empirically stale
         (n>=_RULE_MIN_TRADES_FOR_RECOMPUTE and acc<_RULE_STALE_ACC_FLOOR).
      2. Merge exact (action, frozenset(conditions)) duplicates: keep one, take
         max live n and max live accuracy.
      3. Resolve contradictions on the SAME conditions-set but different actions:
         keep the action with the strongest live evidence (acc * sqrt(n)); when
         no action has evidence (all n==0) or there is a tie, keep the protective
         action (veto > penalize > boost) so a stale 'edge' can never win.
    Non-graduated entries (no conditions+action) pass through unchanged.
    """
    import math
    passthrough: List[Dict[str, Any]] = []
    canon: Dict[Tuple, Dict[str, Any]] = {}  # (action, cond_fs) -> merged entry

    for e in entries:
        conds = e.get("conditions")
        action = e.get("action")
        if not isinstance(conds, dict) or not action:
            passthrough.append(e)
            continue
        # (1) drop explicitly/empirically stale
        if e.get("stale") is True or e.get("invalidation_count", 0) >= 3:
            continue
        n, acc = _recompute_rule_accuracy(conds, action, all_trades)
        if n >= _RULE_MIN_TRADES_FOR_RECOMPUTE and acc < _RULE_STALE_ACC_FLOOR:
            logger.info(
                f"[ENRICHER] Dropping empirically-stale rule {e.get('rule_id','?')} "
                f"({action} {conds}) live_acc={acc:.0%} n={n}"
            )
            continue
        cond_fs = frozenset((str(k), str(v)) for k, v in conds.items())
        merged = dict(e)
        merged["_live_n"] = n
        merged["_live_acc"] = acc
        key = (action, cond_fs)
        if key in canon:
            prev = canon[key]
            merged["_live_n"] = max(prev.get("_live_n", 0), n)
            merged["_live_acc"] = max(prev.get("_live_acc", 0.0), acc)
            merged["evidence_count"] = max(prev.get("evidence_count", 0), e.get("evidence_count", 0))
        canon[key] = merged

    # (3) resolve contradictions: group surviving entries by conditions-set
    by_conds: Dict[frozenset, List[Dict[str, Any]]] = {}
    for (action, cond_fs), merged in canon.items():
        by_conds.setdefault(cond_fs, []).append(merged)

    _protect_rank = {"veto": 2, "penalize": 1, "boost": 0}

    def _evidence_strength(m: Dict[str, Any]) -> float:
        return m.get("_live_acc", 0.5) * math.sqrt(m.get("_live_n", 0))

    resolved: List[Dict[str, Any]] = list(passthrough)
    for cond_fs, group in by_conds.items():
        if len(group) == 1:
            resolved.append(group[0])
            continue
        have_evidence = [m for m in group if m.get("_live_n", 0) > 0]
        if have_evidence:
            best = max(have_evidence, key=_evidence_strength)
            # tie on strength -> prefer protective action
            top = max(_evidence_strength(m) for m in have_evidence)
            tied = [m for m in have_evidence if abs(_evidence_strength(m) - top) < 1e-9]
            best = max(tied, key=lambda m: _protect_rank.get((m.get("action") or "").lower(), 0))
        else:
            # no live evidence anywhere -> keep most protective action
            best = max(group, key=lambda m: _protect_rank.get((m.get("action") or "").lower(), 0))
        logger.info(
            f"[ENRICHER] Contradiction on {dict(cond_fs)} -> kept {best.get('action')} "
            f"(live_acc={best.get('_live_acc'):.0%} n={best.get('_live_n')})"
        )
        resolved.append(best)
    return resolved

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
        with open(path, "r", encoding="utf-8", errors="replace") as f:
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
    counterfactuals = _load_json_safe(_COUNTERFACTUAL_PATH, {"scenarios": []})
    hypotheses_data = _load_json_safe(_HYPOTHESES_PATH, {"hypotheses": []})

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
        "counterfactuals": counterfactuals.get("scenarios", []),
        "hypotheses": hypotheses_data.get("hypotheses", []),
        "confidence_state": _load_json_safe(_CONFIDENCE_STATE_PATH, {}),
        "trade_dna": _load_json_safe(_TRADE_DNA_PATH, {"trades": []}).get("trades", []),
        "all_trades_recompute": _load_all_trades_for_recompute(_TRADES_CSV_PATH),
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

    # Sort: validated first, then confidence bucket (rounded to 0.1 so 0.88 ties with 0.90),
    # then recency (newer > older — live trades beat historical backtest within same tier),
    # then capped vc (cap=100 so live n=164 competes equally with backtest n=2172).
    _now = time.time()

    def sort_key(ins: Dict[str, Any]) -> Tuple:
        conf_bucket = round(ins.get("confidence", 0) / 0.1) * 0.1  # e.g. 0.88 → 0.9, 0.72 → 0.7
        return (
            1 if ins.get("validated", False) else 0,
            conf_bucket,
            ins.get("ts", 0) / (_now or 1),              # recency: newer ranks higher within tier
            min(ins.get("validation_count", 0), 100),
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
    all_trades = _cache.get("all_trades_recompute", [])

    # Resolve staleness, exact dups, and contradictions on graduated rules
    # BEFORE relevance filtering so a dropped/merged rule can't sneak back in.
    cleaned = _dedup_and_resolve_graduated(entries, all_trades)

    relevant = [
        e for e in cleaned
        if e.get("category", "general") in relevant_cats
        and (
            e.get("evidence_count", 0) > 0
            or (e.get("source") == "seed" and e.get("confidence", 0) >= 0.9)
        )
        and e.get("confidence", 0) >= 0.7
    ]
    # Graduated entries whose confidence was frozen low but live accuracy is solid
    # should still qualify: re-admit graduated rules with live evidence.
    for e in cleaned:
        if e in relevant:
            continue
        if (
            e.get("category", "general") in relevant_cats
            and e.get("conditions") and e.get("action")
            and e.get("_live_n", 0) >= _RULE_MIN_TRADES_FOR_RECOMPUTE
            and e.get("_live_acc", 0.0) >= 0.55
        ):
            relevant.append(e)
    if not relevant:
        return ""

    # Sort: live evidence first (n then acc), then frozen evidence/confidence as fallback.
    relevant.sort(
        key=lambda e: (
            e.get("_live_n", 0),
            e.get("_live_acc", 0.0),
            e.get("evidence_count", 0),
            e.get("confidence", 0),
        ),
        reverse=True,
    )
    top = relevant[:5]

    lines = ["=== VALIDATED TRADING RULES ==="]
    for e in top:
        text = str(e.get("content", e.get("rule", "")) or "")[:180]
        live_n = e.get("_live_n", 0)
        if live_n > 0:
            # Show LIVE recomputed numbers, not frozen creation-time ones.
            acc = e.get("_live_acc", 0.0)
            lines.append(f"  • [live_acc={acc:.0%} n={live_n}] {text}")
        else:
            conf = e.get("confidence", 0)
            n = e.get("evidence_count", 0)
            lines.append(f"  • [conf={conf:.0%} n={n} unverified] {text}")

    return "\n".join(lines)


def _build_meta_patterns() -> str:
    """Surface top cross-trade patterns from meta_learning/insights.json.

    De-duplicates by description prefix, separates edges from weaknesses.
    Returns top 2 edges + top 2 weaknesses/biases.
    """
    meta = _cache.get("meta_insights", [])
    if not meta:
        return ""

    qualified = [
        m for m in meta
        if m.get("confidence", 0) >= 0.70
        and m.get("evidence_count", 0) >= 15
    ]
    if not qualified:
        return ""

    # De-duplicate by first 55 chars of description (catches repeated pattern variants)
    seen: dict = {}
    for m in sorted(qualified, key=lambda x: (x.get("confidence", 0), x.get("evidence_count", 0)), reverse=True):
        key = str(m.get("description", "") or "")[:55]
        if key and key not in seen:
            seen[key] = m

    unique = list(seen.values())
    edges = [m for m in unique if m.get("category") in ("pattern", "edge")][:2]
    risks = [m for m in unique if m.get("category") in ("weakness", "bias")][:2]
    top = edges + risks
    if not top:
        return ""

    lines = ["=== META-LEARNING PATTERNS ==="]
    for m in top:
        conf = m.get("confidence", 0)
        n = m.get("evidence_count", 0)
        cat = m.get("category", "")
        desc = str(m.get("description", m.get("insight", "")) or "")[:140]
        suggestion = str(m.get("actionable_suggestion", "") or "")[:70]
        prefix = "EDGE" if cat in ("pattern", "edge") else "WARN"
        line = f"  [{prefix} conf={conf:.0%} n={n}] {desc}"
        if suggestion:
            line += f"\n    => {suggestion}"
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


def _build_counterfactual_exit_patterns() -> str:
    """Summarize what better exit timing would have earned — feeds Exit Agent.

    Groups resolved counterfactuals by scenario_type and computes avg delta
    (counterfactual_pnl - actual_pnl). A positive avg_delta for "exit_at_tp1"
    means taking TP1 earlier would have been better on average.

    Only injects patterns with n>=5 and avg_delta > $1 to avoid noise.
    """
    scenarios = _cache.get("counterfactuals", [])
    if not scenarios:
        return ""

    resolved = [s for s in scenarios if s.get("resolved", False)]
    if len(resolved) < 5:
        return ""

    from collections import defaultdict
    by_type: dict = defaultdict(list)
    for s in resolved[-100:]:  # last 100 resolved
        stype = s.get("scenario_type", "unknown")
        delta = float(s.get("delta", 0))
        sym = s.get("symbol", "")
        by_type[stype].append({"delta": delta, "sym": sym})

    lines = []
    for stype, items in by_type.items():
        if len(items) < 5:
            continue
        avg_delta = sum(i["delta"] for i in items) / len(items)
        if abs(avg_delta) < 1.0:
            continue
        direction = "BETTER" if avg_delta > 0 else "WORSE"
        lines.append(
            f"  {stype}: n={len(items)} avg_delta=${avg_delta:+.2f} "
            f"({direction} than actual exit)"
        )

    if not lines:
        return ""

    return "=== COUNTERFACTUAL EXIT PATTERNS ===\n" + "\n".join(lines)


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


def _build_trade_dna_summary() -> str:
    """Compute live WR statistics from trade_dna.json by regime and symbol+side.

    Returns the top winners and worst losers as actionable lines. Only includes
    cells with >=5 trades so the signal is statistically meaningful.
    """
    trades = _cache.get("trade_dna", [])
    if not trades:
        return ""

    from collections import defaultdict

    reg: Dict[str, Dict] = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
    cell: Dict[str, Dict] = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})

    for t in trades:
        regime = (t.get("regime") or "").strip()
        sym = t.get("symbol", "?")
        side = t.get("side", "?")
        win = t.get("outcome") == "WIN"
        pnl = float(t.get("pnl") or 0)

        if regime:
            reg[regime]["total"] += 1
            reg[regime]["pnl"] += pnl
            if win:
                reg[regime]["wins"] += 1

        k = f"{sym}.{side}"
        cell[k]["total"] += 1
        cell[k]["pnl"] += pnl
        if win:
            cell[k]["wins"] += 1

    lines = ["=== TRADE DNA (live WR from past trades) ==="]

    # Top regimes by total
    qualified_reg = {r: s for r, s in reg.items() if s["total"] >= 5}
    if qualified_reg:
        best = sorted(qualified_reg.items(), key=lambda x: x[1]["pnl"], reverse=True)
        lines.append("  Regime edge:")
        for r, s in best[:4]:
            wr = s["wins"] / s["total"]
            avg = s["pnl"] / s["total"]
            lines.append(f"    {r}: {wr:.0%} WR avg_pnl=${avg:.1f} (n={s['total']})")

    # Top/bottom symbol+side cells
    qualified_cell = {k: s for k, s in cell.items() if s["total"] >= 5}
    if qualified_cell:
        sorted_cells = sorted(qualified_cell.items(), key=lambda x: x[1]["pnl"] / x[1]["total"], reverse=True)
        lines.append("  Symbol edge (by avg PnL):")
        for k, s in sorted_cells[:3]:
            wr = s["wins"] / s["total"]
            avg = s["pnl"] / s["total"]
            lines.append(f"    {k}: {wr:.0%} WR avg_pnl=${avg:.1f} (n={s['total']})")
        # Also show worst
        for k, s in sorted_cells[-2:]:
            wr = s["wins"] / s["total"]
            avg = s["pnl"] / s["total"]
            if avg < 0:
                lines.append(f"    {k}: {wr:.0%} WR avg_pnl=${avg:.1f} AVOID")

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _build_confidence_calibration() -> str:
    """Surface calibrated confidence floors and per-symbol/regime adjustments.

    Shows the Trade/Risk Agent the live confidence thresholds so it knows
    when a signal's confidence is below the empirically-calibrated floor.
    """
    cs = _cache.get("confidence_state", {})
    if not cs:
        return ""

    lines = ["=== CONFIDENCE CALIBRATION ==="]
    floor = cs.get("current_floor")
    if floor:
        lines.append(f"  Min confidence threshold: {floor:.0f}%")

    strat_floors = cs.get("strategy_floors", {})
    if strat_floors:
        sf_parts = [f"{k}={v:.0f}%" for k, v in strat_floors.items() if v]
        if sf_parts:
            lines.append(f"  Strategy floors: {', '.join(sf_parts)}")

    sym_adj = cs.get("symbol_adjustments", {})
    if sym_adj:
        top_sym = sorted(sym_adj.items(), key=lambda x: abs(x[1]), reverse=True)[:4]
        adj_parts = [f"{s}={'+' if v > 0 else ''}{v:.2f}" for s, v in top_sym]
        lines.append(f"  Symbol edge adj: {', '.join(adj_parts)}")

    reg_adj = cs.get("regime_adjustments", {})
    if reg_adj:
        top_reg = sorted(reg_adj.items(), key=lambda x: abs(x[1]), reverse=True)[:3]
        adj_parts = [f"{r}={'+' if v > 0 else ''}{v:.2f}" for r, v in top_reg]
        lines.append(f"  Regime edge adj: {', '.join(adj_parts)}")

    if len(lines) == 1:
        return ""

    return "\n".join(lines)


def _build_validated_hypotheses(agent_role: str) -> str:
    """Surface validated + high-confidence hypotheses from growth/hypotheses.json.

    Only includes hypotheses in 'validated' stage or 'testing' with confidence>=0.7.
    Skips invalidated ones. Returns empty string if none qualify.
    """
    hyps = _cache.get("hypotheses", [])
    if not hyps:
        return ""

    qualified = [
        h for h in hyps
        if (
            h.get("stage") in ("validated",) or
            (h.get("stage") == "testing" and h.get("confidence", 0) >= 0.7)
        )
        and h.get("statement", "")
    ]
    if not qualified:
        return ""

    # Sort: validated first, then confidence
    qualified.sort(
        key=lambda h: (1 if h.get("stage") == "validated" else 0, h.get("confidence", 0)),
        reverse=True,
    )
    top = qualified[:3]

    lines = ["=== ACTIVE HYPOTHESES (empirically tested) ==="]
    for h in top:
        stage = h.get("stage", "?")
        conf = h.get("confidence", 0)
        stmt = str(h.get("statement", ""))[:150]
        lines.append(f"  [{stage.upper()} conf={conf:.0%}] {stmt}")

    return "\n".join(lines)


def _build_hold_time_mechanism() -> str:
    """Regime-conditional hold-time intelligence from 164 live trades.

    Gives exit/trade/risk agents the CAUSAL mechanism — not just a rule.
    Computed from trade_dna.json so it updates as new trades come in.
    """
    trades = _cache.get("trade_dna", [])
    if len(trades) < 30:
        return ""

    from collections import defaultdict

    # Hold-time buckets
    hold_data: Dict[str, Dict] = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
    # Early losses by regime
    early_loss_regimes: Dict[str, int] = defaultdict(int)
    total_early_losses = 0
    win_holds = []
    loss_holds = []

    for t in trades:
        h = float(t.get("hold_time_s") or 0) / 3600
        outcome = t.get("outcome", "")
        pnl = float(t.get("pnl") or 0)
        regime = (t.get("regime") or "unknown").strip() or "unknown"

        if h < 1: bucket = "<1h"
        elif h < 2: bucket = "1h-2h"
        elif h < 4: bucket = "2h-4h"
        elif h < 8: bucket = "4h-8h"
        elif h < 12: bucket = "8h-12h"
        else: bucket = "12h+"

        hold_data[bucket]["total"] += 1
        hold_data[bucket]["pnl"] += pnl
        if outcome == "WIN":
            hold_data[bucket]["wins"] += 1
            win_holds.append(h)
        elif outcome == "LOSS":
            loss_holds.append(h)
            if h < 2:
                total_early_losses += 1
                early_loss_regimes[regime] += 1

    if not win_holds or not loss_holds:
        return ""

    sorted_wins = sorted(win_holds)
    sorted_losses = sorted(loss_holds)
    win_median = sorted_wins[len(sorted_wins) // 2]
    loss_median = sorted_losses[len(sorted_losses) // 2]

    noise_regimes = {"illiquid", "ranging", "unknown", "consolidation", "low_liquidity", "range"}
    noise_early = sum(v for k, v in early_loss_regimes.items() if k in noise_regimes)
    noise_pct = noise_early / total_early_losses if total_early_losses > 0 else 0

    lines = ["=== HOLD TIME MECHANISM (live data) ==="]
    lines.append(f"  WIN median hold={win_median:.1f}h | LOSS median hold={loss_median:.1f}h")
    if noise_pct >= 0.7:
        lines.append(f"  {noise_pct:.0%} of early SL hits (<2h) are in noise regimes (illiquid/ranging/unknown)")
        lines.append("  TRENDING regime: early hold risk is LOW — stay patient through microstructure noise")
        lines.append("  ILLIQUID/RANGING: early losses are regime failures — consider closing sooner")

    # Show hold-time table (only non-empty buckets)
    order = ["<1h", "1h-2h", "2h-4h", "4h-8h", "8h-12h", "12h+"]
    for b in order:
        if b in hold_data and hold_data[b]["total"] >= 3:
            s = hold_data[b]
            wr = s["wins"] / s["total"]
            avg = s["pnl"] / s["total"]
            flag = "+" if avg > 1 else ("-" if avg < -1 else " ")
            lines.append(f"  {flag} {b}: {wr:.0%} WR avg=${avg:.1f} (n={s['total']})")

    return "\n".join(lines)


def _build_dynamic_floors_section() -> str:
    """Show the system's live dynamic confidence floors computed from the enricher's cached trade_dna."""
    try:
        from llm.dynamic_thresholds import DynamicThresholds
        trades = _cache.get("trade_dna", [])
        if len(trades) < 15:
            return ""
        # Build a fresh (non-singleton) instance pointing at the cached data via a temp file approach
        # We compute inline to avoid path conflicts in tests
        from collections import defaultdict

        def _wr_to_floor(wr: float, n: int) -> float:
            if n < 10:
                return 64.0
            if wr < 0.25:
                return 76.0
            if wr < 0.35:
                return 71.0
            if wr < 0.45:
                return 66.0
            if wr < 0.55:
                return 62.0
            return 58.0

        regime_agg: dict = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0, "sl_hits": 0, "sl_widths": []})
        for t in trades:
            r = (t.get("regime") or "unknown").lower()
            pnl = float(t.get("pnl") or 0)
            won = t.get("outcome") == "WIN"
            entry = float(t.get("entry_price") or 0)
            sl = float(t.get("sl") or 0)
            exit_reason = (t.get("exit_reason") or "").upper()
            regime_agg[r]["total"] += 1
            regime_agg[r]["pnl"] += pnl
            if won:
                regime_agg[r]["wins"] += 1
            if exit_reason == "SL":
                regime_agg[r]["sl_hits"] += 1
            if entry > 0 and sl > 0:
                regime_agg[r]["sl_widths"].append(abs(entry - sl) / entry)

        lines = []
        for r, v in sorted(regime_agg.items(), key=lambda x: -x[1]["total"]):
            n = v["total"]
            wr = v["wins"] / n if n else 0
            floor = _wr_to_floor(wr, n)
            sl_hit = v["sl_hits"] / n if n else 0
            widths = v["sl_widths"]
            avg_sl = sum(widths) / len(widths) * 100 if widths else 0
            lines.append(f"  {r}: WR={wr:.0%} n={n} floor={floor:.0f} SL_hit={sl_hit:.0%} avg_SL={avg_sl:.1f}%")

        if not lines:
            return ""

        # Hold time performance (computed inline from same cache)
        hold_agg: dict = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
        entry_agg: dict = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
        for t in trades:
            won = t.get("outcome") == "WIN"
            pnl = float(t.get("pnl") or 0)
            hold_s = float(t.get("hold_time_s") or 0)
            if hold_s < 3600: hb = "<1h"
            elif hold_s < 7200: hb = "1-2h"
            elif hold_s < 21600: hb = "2-6h"
            elif hold_s < 43200: hb = "6-12h"
            else: hb = ">12h"
            hold_agg[hb]["total"] += 1
            hold_agg[hb]["pnl"] += pnl
            if won: hold_agg[hb]["wins"] += 1
            et = (t.get("entry_type") or "").upper()
            if et:
                entry_agg[et]["total"] += 1
                entry_agg[et]["pnl"] += pnl
                if won: entry_agg[et]["wins"] += 1

        hold_lines = []
        for b in ["<1h", "1-2h", "2-6h", "6-12h", ">12h"]:
            d = hold_agg.get(b)
            if d and d["total"] >= 5:
                wr = d["wins"] / d["total"]
                hold_lines.append(f"  {b}: WR={wr:.0%} n={d['total']} PnL=${d['pnl']:+.0f}")

        profile_lines = []
        for et, d in sorted(entry_agg.items(), key=lambda x: -x[1]["total"]):
            if d["total"] >= 5:
                wr = d["wins"] / d["total"]
                profile_lines.append(f"  {et}: WR={wr:.0%} n={d['total']} PnL=${d['pnl']:+.0f}")

        result = (
            "LIVE CONFIDENCE FLOORS (dynamic from trade_dna):\n"
            + "\n".join(lines)
            + "\nNote: mechanical gate uses these floors. Your conviction score should EXCEED the floor "
            "for your current regime to pass the quality filter."
        )
        if hold_lines:
            result += "\nHOLD TIME PERFORMANCE (key: 6-12h trades = profitable):\n" + "\n".join(hold_lines)
        if profile_lines:
            result += "\nTRADE PROFILE PERFORMANCE:\n" + "\n".join(profile_lines)
        return result
    except Exception:
        return ""


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
      9. COUNTERFACTUAL EXIT PATTERNS — what better timing would have earned
      10. SYSTEM HEALTH — circuit breaker state, rolling WR, avg R:R

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

    # 9. Counterfactual exit patterns (Exit Agent only — what exit timing cost/saved)
    if agent_role in ("exit", "trade", "overseer"):
        cf_patterns = _build_counterfactual_exit_patterns()
        if cf_patterns:
            sections.append(cf_patterns)

    # 10. System health — CB state, rolling WR, R:R (injected into ALL decision agents)
    system_health = _build_system_health_context()
    if system_health:
        sections.append(system_health)

    # 11. Validated hypotheses (for decision agents — empirically tested edge claims)
    if agent_role in ("trade", "risk", "critic", "regime", "quant", "overseer"):
        hyp_section = _build_validated_hypotheses(agent_role)
        if hyp_section:
            sections.append(hyp_section)

    # 12. Confidence calibration (floors + symbol/regime adjustments)
    if agent_role in ("trade", "risk", "critic"):
        conf_cal = _build_confidence_calibration()
        if conf_cal:
            sections.append(conf_cal)

    # 13. Trade DNA — live WR by regime and symbol+side (50+ trades = reliable signal)
    if agent_role in ("trade", "risk", "critic", "regime", "overseer"):
        dna = _build_trade_dna_summary()
        if dna:
            sections.append(dna)

    # 14. Hold-time causal mechanism — regime-conditional exit intelligence
    if agent_role in ("exit", "trade", "risk"):
        hold = _build_hold_time_mechanism()
        if hold:
            sections.append(hold)

    # 15. Dynamic confidence floors — live per-regime WR floors
    if agent_role in ("trade", "regime", "critic"):
        dyn_floor = _build_dynamic_floors_section()
        if dyn_floor:
            sections.append(dyn_floor)

    if not sections:
        return base_prompt

    # Join all sections and enforce token budget (raised to 5000 chars — CLI is $0/call)
    enrichment = "\n\n".join(sections)
    if len(enrichment) > 5000:
        enrichment = enrichment[:4997] + "..."

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
