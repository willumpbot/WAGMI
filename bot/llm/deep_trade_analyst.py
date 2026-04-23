"""
Deep Trade Analyst: LLM-powered statistical analysis of all historical trades.

Feeds the full trade_dna dataset (164+ records) to Claude CLI Sonnet for
institutional-grade quant analysis. Discovers regime edges, symbol-side
win patterns, optimal hold times, leverage impact, and more.

Unlike self_analyst.py (incremental, 50-trade window), this module performs
a full historical sweep and writes findings to insight_journal.json with
high confidence — making them the TOP priority injections for all agents.

Run manually:
  cd bot && python -m llm.deep_trade_analyst

Triggered automatically:
  - When trade_count crosses 50/100/150/200 milestones (from Overseer)
  - Daily at market open (if >20 new trades since last run)
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.llm.deep_trade_analyst")

_TRADE_DNA_PATH = os.path.join("data", "llm", "deep_memory", "trade_dna.json")
_INSIGHT_JOURNAL_PATH = os.path.join("data", "llm", "deep_memory", "insight_journal.json")
_KB_PATH = os.path.join("data", "llm", "teaching", "knowledge_base.json")
_STATE_PATH = os.path.join("data", "llm", "deep_analyst_state.json")

_MIN_TRADES = 30
_MIN_TRADES_PER_CELL = 5   # minimum trades per cell for statistical significance
_MILESTONE_GAPS = [50, 100, 150, 200, 300, 500]


# ── Statistics ─────────────────────────────────────────────────────────────

def _compute_statistics(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute all statistical patterns from trade_dna records."""

    def is_win(t: Dict) -> bool:
        return t.get("outcome") == "WIN"

    def stats_for_group(group: List[Dict]) -> Dict:
        if not group:
            return {}
        wins = sum(1 for t in group if is_win(t))
        pnls = [float(t.get("pnl") or 0) for t in group]
        return {
            "n": len(group),
            "wins": wins,
            "wr": round(wins / len(group), 3),
            "avg_pnl": round(sum(pnls) / len(group), 2),
            "total_pnl": round(sum(pnls), 2),
        }

    stats: Dict[str, Any] = {}

    # 1. By regime
    by_regime: Dict[str, List] = defaultdict(list)
    for t in trades:
        r = (t.get("regime") or "").strip() or "unknown"
        by_regime[r].append(t)
    stats["by_regime"] = {
        r: stats_for_group(ts) for r, ts in by_regime.items()
        if len(ts) >= _MIN_TRADES_PER_CELL
    }

    # 2. By symbol + side
    by_ss: Dict[str, List] = defaultdict(list)
    for t in trades:
        k = f"{t.get('symbol','?')}.{t.get('side','?')}"
        by_ss[k].append(t)
    stats["by_symbol_side"] = {
        k: stats_for_group(ts) for k, ts in by_ss.items()
        if len(ts) >= _MIN_TRADES_PER_CELL
    }

    # 3. By n_agree (strategy consensus)
    by_agree: Dict[int, List] = defaultdict(list)
    for t in trades:
        n = int(t.get("num_agree") or 0)
        by_agree[n].append(t)
    stats["by_n_agree"] = {
        str(n): stats_for_group(ts) for n, ts in by_agree.items()
        if len(ts) >= _MIN_TRADES_PER_CELL
    }

    # 4. By leverage bucket
    by_lev: Dict[str, List] = defaultdict(list)
    for t in trades:
        lev = float(t.get("leverage") or 1.0)
        if lev <= 2: k = "low(1-2x)"
        elif lev <= 5: k = "medium(3-5x)"
        elif lev <= 10: k = "high(6-10x)"
        else: k = "extreme(10x+)"
        by_lev[k].append(t)
    stats["by_leverage"] = {
        k: stats_for_group(ts) for k, ts in by_lev.items()
        if len(ts) >= _MIN_TRADES_PER_CELL
    }

    # 5. By hold time
    by_hold: Dict[str, List] = defaultdict(list)
    for t in trades:
        h = float(t.get("hold_time_s") or 0) / 3600  # hours
        if h < 0.25: k = "<15min"
        elif h < 1: k = "15min-1h"
        elif h < 4: k = "1h-4h"
        elif h < 12: k = "4h-12h"
        else: k = "12h+"
        by_hold[k].append(t)
    stats["by_hold_time"] = {
        k: stats_for_group(ts) for k, ts in by_hold.items()
        if len(ts) >= _MIN_TRADES_PER_CELL
    }

    # 6. By confidence bucket
    by_conf: Dict[str, List] = defaultdict(list)
    for t in trades:
        c = float(t.get("confidence") or 0)
        if c < 60: k = "low(50-60)"
        elif c < 70: k = "med(60-70)"
        elif c < 80: k = "good(70-80)"
        elif c < 90: k = "high(80-90)"
        else: k = "extreme(90+)"
        by_conf[k].append(t)
    stats["by_confidence"] = {
        k: stats_for_group(ts) for k, ts in by_conf.items()
        if len(ts) >= _MIN_TRADES_PER_CELL
    }

    # 7. By BTC trend at entry
    by_btc: Dict[str, List] = defaultdict(list)
    for t in trades:
        btc = str(t.get("btc_trend") or "unknown").lower()
        by_btc[btc].append(t)
    stats["by_btc_trend"] = {
        k: stats_for_group(ts) for k, ts in by_btc.items()
        if len(ts) >= _MIN_TRADES_PER_CELL
    }

    # 8. By regime × symbol (cross-cell)
    by_regime_sym: Dict[str, List] = defaultdict(list)
    for t in trades:
        r = (t.get("regime") or "").strip() or "unknown"
        s = t.get("symbol", "?")
        k = f"{r}×{s}"
        by_regime_sym[k].append(t)
    stats["by_regime_symbol"] = {
        k: stats_for_group(ts) for k, ts in by_regime_sym.items()
        if len(ts) >= _MIN_TRADES_PER_CELL
    }

    # 9. Overall summary
    stats["overall"] = stats_for_group(trades)

    return stats


def _format_stats_for_prompt(stats: Dict[str, Any]) -> str:
    """Render statistics as a compact text table for Claude."""
    lines = []

    overall = stats.get("overall", {})
    lines.append(f"TOTAL TRADES: {overall.get('n', 0)} | WR: {overall.get('wr', 0):.0%} | AvgPnL: ${overall.get('avg_pnl', 0):.2f}")
    lines.append("")

    sections = [
        ("BY REGIME", "by_regime"),
        ("BY SYMBOL+SIDE", "by_symbol_side"),
        ("BY STRATEGIES AGREEING", "by_n_agree"),
        ("BY LEVERAGE", "by_leverage"),
        ("BY HOLD TIME", "by_hold_time"),
        ("BY CONFIDENCE", "by_confidence"),
        ("BY BTC TREND", "by_btc_trend"),
        ("BY REGIME×SYMBOL", "by_regime_symbol"),
    ]

    for header, key in sections:
        cell_data = stats.get(key, {})
        if not cell_data:
            continue
        lines.append(f"--- {header} ---")
        sorted_cells = sorted(cell_data.items(), key=lambda x: x[1].get("avg_pnl", 0), reverse=True)
        for name, s in sorted_cells:
            flag = "+" if s.get("avg_pnl", 0) > 1 else ("-" if s.get("avg_pnl", 0) < -1 else " ")
            lines.append(f"  {flag} {name}: n={s['n']} WR={s['wr']:.0%} avg=${s['avg_pnl']:.2f} total=${s['total_pnl']:.1f}")
        lines.append("")

    return "\n".join(lines)


# ── Prompt Builder ─────────────────────────────────────────────────────────

def _build_analysis_prompt(stats_text: str, existing_insights_summary: str) -> str:
    return f"""You are an institutional quant analyst. Your task: analyze trading statistics and generate 5-8 HIGH-CONFIDENCE actionable insights.

PERFORMANCE STATISTICS (computed from {stats_text.split()[2] if stats_text else '?'} live trades):

{stats_text}

EXISTING INSIGHTS (do NOT duplicate these):
{existing_insights_summary}

ANALYSIS INSTRUCTIONS:
1. Find patterns where n>=5, avg_pnl differs significantly from baseline
2. Focus on: regime edges, symbol-direction edges, optimal hold times, confidence thresholds, leverage sweet spots
3. Identify which cells to MAXIMIZE and which to AVOID
4. Look for interaction effects (regime×symbol, hold_time×regime, etc.)
5. Only report patterns with statistical significance (at least 5 trades, clear directional effect)

OUTPUT FORMAT (JSON only, no prose, no markdown):
{{
  "insights": [
    {{
      "category": "regime_insight|strategy_insight|symbol_insight|timing_insight|risk_insight|execution_insight|correlation_insight|meta_insight",
      "insight": "Specific actionable statement (under 200 chars)",
      "confidence": 0.70-0.90,
      "evidence": "Which cells support this + the n and WR numbers",
      "validated": true,
      "validation_count": N
    }}
  ]
}}

CRITICAL: Be a hard-nosed quant. Only report what the data actually shows. If a cell has negative avg_pnl, say AVOID. If positive, say FAVOR. Include the specific numbers."""


# ── Main Analysis ──────────────────────────────────────────────────────────

def _load_existing_insights_summary() -> str:
    """Compact summary of existing insight_journal entries."""
    try:
        with open(_INSIGHT_JOURNAL_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        insights = data.get("insights", [])
        if not insights:
            return "No existing insights."
        lines = [f"Existing {len(insights)} insights (do not duplicate):"]
        for ins in insights[-20:]:
            lines.append(f"  • {str(ins.get('insight', ''))[:100]}")
        return "\n".join(lines)
    except Exception:
        return "No existing insights."


def _write_insights_to_journal(new_insights: List[Dict]) -> int:
    """Append new insights to insight_journal.json. Returns count added."""
    try:
        if os.path.exists(_INSIGHT_JOURNAL_PATH):
            with open(_INSIGHT_JOURNAL_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {"insights": []}

        existing_texts = {str(ins.get("insight", ""))[:80] for ins in data.get("insights", [])}
        added = 0

        for ins in new_insights:
            text = str(ins.get("insight", "")).strip()
            if not text or text[:80] in existing_texts:
                continue
            entry = {
                "ts": time.time(),
                "category": ins.get("category", "meta_insight"),
                "insight": text[:250],
                "confidence": float(ins.get("confidence", 0.7)),
                "evidence": str(ins.get("evidence", ""))[:300],
                "source": "deep_trade_analyst",
                "validated": bool(ins.get("validated", True)),
                "validation_count": int(ins.get("validation_count", 5)),
            }
            data.setdefault("insights", []).append(entry)
            existing_texts.add(text[:80])
            added += 1
            logger.info(f"[DEEP-ANALYST] New insight: {text[:80]}")

        if added:
            with open(_INSIGHT_JOURNAL_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            try:
                from llm.agents.prompt_enricher import invalidate_cache
                invalidate_cache()
            except Exception:
                pass

        return added
    except Exception as e:
        logger.warning(f"[DEEP-ANALYST] Insight journal write error: {e}")
        return 0


def _check_milestone(n_trades: int) -> bool:
    """Return True if this trade count is at a milestone and we haven't analyzed it yet."""
    try:
        state = {}
        if os.path.exists(_STATE_PATH):
            with open(_STATE_PATH, "r") as f:
                state = json.load(f)
        last_analyzed_at = state.get("last_analyzed_at_n", 0)
        # Find the highest milestone below n_trades
        applicable = [m for m in _MILESTONE_GAPS if m <= n_trades]
        if not applicable:
            return False
        target_milestone = max(applicable)
        return target_milestone > last_analyzed_at
    except Exception:
        return False


def _record_state(n_trades: int) -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_PATH), exist_ok=True)
        state = {}
        if os.path.exists(_STATE_PATH):
            with open(_STATE_PATH, "r") as f:
                state = json.load(f)
        state["last_analyzed_at_n"] = n_trades
        state["last_run_ts"] = time.time()
        with open(_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass


def run_deep_analysis(force: bool = False) -> List[Dict[str, Any]]:
    """Run deep historical analysis. Returns list of new insights added."""
    try:
        with open(_TRADE_DNA_PATH, "r") as f:
            trade_dna = json.load(f)
    except Exception as e:
        logger.debug(f"[DEEP-ANALYST] trade_dna load error: {e}")
        return []

    trades = trade_dna.get("trades", [])
    n = len(trades)

    if n < _MIN_TRADES:
        logger.debug(f"[DEEP-ANALYST] Only {n} trades — need {_MIN_TRADES}")
        return []

    if not force and not _check_milestone(n):
        logger.debug(f"[DEEP-ANALYST] No new milestone at n={n}")
        return []

    logger.info(f"[DEEP-ANALYST] Running deep analysis on {n} trades")

    stats = _compute_statistics(trades)
    stats_text = _format_stats_for_prompt(stats)
    existing = _load_existing_insights_summary()
    prompt = _build_analysis_prompt(stats_text, existing)

    try:
        from llm.claude_cli_client import call_agent, available
        if not available():
            logger.debug("[DEEP-ANALYST] Claude CLI not available")
            return []

        resp = call_agent(
            user_prompt=prompt,
            model="sonnet",  # Sonnet for quant-grade analysis quality
            timeout=180,
        )

        if not resp.ok or not resp.parsed:
            logger.debug(f"[DEEP-ANALYST] CLI response not parseable: {resp.error}")
            return []

        new_insights = resp.parsed.get("insights", [])
        if not new_insights:
            logger.info("[DEEP-ANALYST] No new insights found")
            _record_state(n)
            return []

        added_count = _write_insights_to_journal(new_insights)
        _record_state(n)

        logger.info(f"[DEEP-ANALYST] Added {added_count} insights from {n}-trade analysis")
        return new_insights[:added_count]

    except Exception as e:
        logger.warning(f"[DEEP-ANALYST] Analysis error: {e}")
        return []


def run_milestone_check() -> None:
    """Called by Overseer on each cycle — runs analysis if at a milestone."""
    run_deep_analysis(force=False)


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    force = "--force" in sys.argv
    print(f"Running deep trade analysis (force={force})...")
    insights = run_deep_analysis(force=force)
    print(f"\nAdded {len(insights)} new insights:")
    for ins in insights:
        print(f"  [{ins.get('category','?')} conf={ins.get('confidence',0):.0%}] {ins.get('insight','')[:100]}")
