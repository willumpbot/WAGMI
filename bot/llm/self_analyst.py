"""
Self-Analyst: WAGMI's meta-brain writes to its own brain.

Uses the Claude CLI to analyze recent trade history, current knowledge base,
and meta-learning data, then synthesizes NEW KB entries — rules the bot
discovered itself that no human wrote.

This is the outside-the-box item: Claude Code analyzes Claude Code's trading
bot's trades and writes new rules back into the bot's prompt injection layer.

Runs:
  - Triggered by Overseer when total_resolved_counterfactuals crosses a threshold
  - Daily at startup via run_daily_analysis()
  - Manually via python -m llm.self_analyst

Output: new entries appended to data/llm/teaching/knowledge_base.json
"""
from __future__ import annotations

import csv
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.llm.self_analyst")

_KB_PATH = os.path.join("data", "llm", "teaching", "knowledge_base.json")
_TRADES_CSV = os.path.join("data", "trades.csv")
_LAST_RUN_PATH = os.path.join("data", "llm", "self_analyst_last_run.json")
_MIN_TRADES_FOR_ANALYSIS = 15   # don't run with fewer trades
_MAX_DAILY_RUNS = 3             # rate limit: 3 per day max
_MIN_INTERVAL_H = 8             # at least 8h between runs


def _load_recent_trades(n: int = 50) -> List[Dict[str, str]]:
    if not os.path.exists(_TRADES_CSV):
        return []
    try:
        rows = []
        with open(_TRADES_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        return rows[-n:]
    except Exception:
        return []


def _load_kb_summary() -> str:
    """Compact summary of current KB for context injection."""
    try:
        with open(_KB_PATH, "r") as f:
            kb = json.load(f)
        entries = kb.get("entries", [])
        if not entries:
            return "Knowledge base: empty"
        lines = [f"Current KB: {len(entries)} entries"]
        for e in entries[:10]:
            lines.append(f"  • {str(e.get('content', ''))[:120]}")
        return "\n".join(lines)
    except Exception:
        return "Knowledge base: unavailable"


def _check_rate_limit() -> bool:
    """Return True if we're allowed to run now."""
    try:
        if os.path.exists(_LAST_RUN_PATH):
            with open(_LAST_RUN_PATH, "r") as f:
                state = json.load(f)
            last_run = state.get("last_run", 0)
            runs_today = state.get("runs_today", 0)
            today_start = state.get("today_start", 0)
            now = time.time()
            # Reset daily counter if new day
            if now - today_start > 86400:
                runs_today = 0
                today_start = now
            if runs_today >= _MAX_DAILY_RUNS:
                logger.debug("[SELF-ANALYST] Daily run limit reached")
                return False
            if (now - last_run) < (_MIN_INTERVAL_H * 3600):
                logger.debug("[SELF-ANALYST] Too soon since last run")
                return False
    except Exception:
        pass
    return True


def _record_run() -> None:
    try:
        state = {}
        if os.path.exists(_LAST_RUN_PATH):
            with open(_LAST_RUN_PATH, "r") as f:
                state = json.load(f)
        now = time.time()
        today_start = state.get("today_start", now)
        if now - today_start > 86400:
            state["runs_today"] = 0
            state["today_start"] = now
        state["last_run"] = now
        state["runs_today"] = state.get("runs_today", 0) + 1
        os.makedirs(os.path.dirname(_LAST_RUN_PATH), exist_ok=True)
        with open(_LAST_RUN_PATH, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


def _build_analysis_prompt(trades: List[Dict[str, str]], kb_summary: str) -> str:
    """Build the prompt for self-analysis."""
    # Format trades compactly
    trade_lines = []
    for t in trades:
        sym = t.get("symbol", "?")
        side = t.get("side", "?")
        pnl = t.get("pnl", "?")
        regime = t.get("regime", "?")
        strat = t.get("primary_driver", t.get("strategy", "?"))
        lev = t.get("leverage", "?")
        outcome = "W" if str(pnl).startswith("+") or (float(pnl) > 0 if pnl not in ("?", "") else False) else "L"
        try:
            outcome = "W" if float(pnl) > 0 else "L"
        except Exception:
            pass
        trade_lines.append(f"{outcome} {sym} {side} pnl={pnl} regime={regime} strat={strat} lev={lev}x")

    trades_text = "\n".join(trade_lines[-30:]) if trade_lines else "no trades yet"

    return f"""You are the WAGMI trading bot's self-analyst. Your job: analyze recent trade history and generate NEW trading rules that aren't already in the knowledge base.

{kb_summary}

RECENT TRADES (last {len(trades)}):
{trades_text}

TASK:
1. Find 2-4 patterns in the trade history that are NOT already covered by existing KB entries
2. Each pattern needs at least 3+ supporting trades to count
3. Focus on: regime-specific edges, symbol-specific edges, time-of-day patterns, leverage sizing patterns, strategy combination patterns

OUTPUT FORMAT (JSON only, no prose):
{{
  "new_rules": [
    {{
      "content": "Concise rule statement under 200 chars",
      "confidence": 0.60-0.85,
      "evidence_count": N,
      "category": "regime|strategy|execution|risk|timing|symbol",
      "tags": ["tag1", "tag2"],
      "evidence": "1-sentence explanation of what you observed in the trades"
    }}
  ]
}}

CRITICAL: Only include rules with genuine evidence (3+ trades supporting). Do not invent rules. If you find no new patterns, return {{"new_rules": []}}."""


def run_analysis() -> List[Dict[str, Any]]:
    """Run self-analysis and write new KB entries. Returns list of added entries."""
    if not _check_rate_limit():
        return []

    trades = _load_recent_trades(50)
    if len(trades) < _MIN_TRADES_FOR_ANALYSIS:
        logger.debug(f"[SELF-ANALYST] Only {len(trades)} trades — need {_MIN_TRADES_FOR_ANALYSIS} to analyze")
        return []

    kb_summary = _load_kb_summary()
    prompt = _build_analysis_prompt(trades, kb_summary)

    logger.info(f"[SELF-ANALYST] Running self-analysis on {len(trades)} trades")

    try:
        from llm.claude_cli_client import call_agent, available
        if not available():
            logger.debug("[SELF-ANALYST] Claude CLI not available")
            return []

        resp = call_agent(
            user_prompt=prompt,
            model="haiku",  # Haiku is fast + cheap, sufficient for pattern recognition
            timeout=120,
        )

        if not resp.ok or not resp.parsed:
            logger.debug(f"[SELF-ANALYST] CLI response not parseable: {resp.error}")
            return []

        new_rules = resp.parsed.get("new_rules", [])
        if not new_rules:
            logger.info("[SELF-ANALYST] No new patterns found")
            _record_run()
            return []

        # Write to KB
        try:
            os.makedirs(os.path.dirname(_KB_PATH), exist_ok=True)
            if os.path.exists(_KB_PATH):
                with open(_KB_PATH, "r") as f:
                    kb = json.load(f)
            else:
                kb = {"entries": []}

            added = []
            for rule in new_rules:
                content = str(rule.get("content", "")).strip()
                if not content:
                    continue
                # Dedup check
                existing = [e.get("content", "") for e in kb.get("entries", [])]
                if any(content[:60] in e for e in existing):
                    continue

                entry = {
                    "knowledge_type": "self_discovered",
                    "content": content,
                    "confidence": max(0.5, min(0.9, float(rule.get("confidence", 0.6)))),
                    "evidence_count": int(rule.get("evidence_count", 3)),
                    "category": str(rule.get("category", "general")),
                    "tags": list(rule.get("tags", [])),
                    "source": "self_analyst_cli",
                    "evidence": str(rule.get("evidence", ""))[:300],
                    "created_at": time.time(),
                    "last_validated": time.time(),
                    "validation_count": int(rule.get("evidence_count", 3)),
                    "invalidation_count": 0,
                }
                kb.setdefault("entries", []).append(entry)
                added.append(entry)
                logger.info(f"[SELF-ANALYST] New rule: {content[:80]}")

            if added:
                with open(_KB_PATH, "w") as f:
                    json.dump(kb, f, indent=2, default=str)
                # Invalidate enricher cache so agents see new rules immediately
                try:
                    from llm.agents.prompt_enricher import invalidate_cache
                    invalidate_cache()
                except Exception:
                    pass
                logger.info(f"[SELF-ANALYST] Wrote {len(added)} new rules to KB")

            _record_run()
            return added

        except Exception as e:
            logger.warning(f"[SELF-ANALYST] KB write error: {e}")
            return []

    except Exception as e:
        logger.warning(f"[SELF-ANALYST] Analysis error: {e}")
        return []


def run_daily_analysis() -> None:
    """Entry point for daily scheduled analysis. Logs result."""
    added = run_analysis()
    if added:
        logger.info(f"[SELF-ANALYST] Daily analysis: {len(added)} new rules added to KB")
    else:
        logger.debug("[SELF-ANALYST] Daily analysis: no new rules")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    logging.basicConfig(level=logging.INFO)
    added = run_analysis()
    print(f"Added {len(added)} new KB rules:")
    for r in added:
        print(f"  • {r['content']}")
