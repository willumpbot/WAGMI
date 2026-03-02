"""
Post-Trade Learner: generates immediate, actionable lessons after every trade close.

No LLM calls — purely deterministic pattern matching on trade data.
Lessons are injected into the memory store immediately so the LLM sees them
on the very next call. Also exposes recent lessons for snapshot injection.

This closes the feedback loop from ~1 hour (periodic learning cycle) to < 1 minute.
"""

import logging
import time
from collections import deque
from typing import Optional, Dict, Any, List

logger = logging.getLogger("bot.llm.post_trade_learner")

# Ring buffer of recent lessons (last 10)
_recent_lessons: deque = deque(maxlen=10)


def generate_immediate_lesson(trade_data: Dict[str, Any]) -> Optional[str]:
    """Generate an immediate lesson from a closed trade.

    Returns a compact, actionable memory note (< 200 chars) or None.
    Pattern-matches on trade outcome to produce specific, useful insights.
    """
    symbol = trade_data.get("symbol", "")
    side = trade_data.get("side", "")
    outcome = trade_data.get("outcome", "")
    pnl = trade_data.get("pnl", 0)
    regime = trade_data.get("regime", "") or "unknown"
    strategy = trade_data.get("strategy", "")
    confidence = trade_data.get("confidence", 0)
    hold_time_s = trade_data.get("hold_time_s", 0)
    exit_action = trade_data.get("exit_action", "")
    llm_action = trade_data.get("llm_action", "")
    llm_confidence = trade_data.get("llm_confidence", 0)
    funding_rate = trade_data.get("funding_rate", 0)

    is_win = outcome == "WIN" or pnl > 0
    is_loss = not is_win and pnl != 0
    hold_min = hold_time_s / 60 if hold_time_s else 0

    lesson = None

    # Pattern 1: Quick stop-loss hit (< 5 min hold = bad entry timing)
    if is_loss and hold_time_s < 300 and exit_action in ("SL", "STOP_LOSS"):
        lesson = (
            f"{symbol} {side} SL in {hold_min:.0f}min in {regime}"
            f"—entry timing poor, consider 'wait for pullback'"
        )

    # Pattern 2: High-confidence loss — overconfidence signal
    elif is_loss and confidence >= 75:
        lesson = (
            f"{symbol} {side} LOSS despite {confidence:.0f}% conf in {regime}, "
            f"{exit_action}—reduce confidence for similar setups"
        )

    # Pattern 3: Long hold + high funding ate the edge
    elif is_loss and hold_time_s > 3600 and abs(funding_rate) > 0.0003:
        lesson = (
            f"{symbol} {side} LOSS after {hold_min / 60:.1f}h hold, "
            f"funding {funding_rate * 100:.3f}% in {regime}—exit earlier or flip side"
        )

    # Pattern 4: LLM said go but trade lost
    elif is_loss and llm_action in ("go", "proceed") and abs(pnl) > 3:
        lesson = (
            f"{symbol} {side} lost ${abs(pnl):.0f} in {regime}, "
            f"LLM conf={llm_confidence:.2f}—be cautious on similar {regime} {side}s"
        )

    # Pattern 5: LLM vetoed but would have been a loss — good veto (reinforcement)
    # (This is inferred: LLM action was flat/skip, the trade went through anyway via ensemble)
    # Handled separately via veto_tracker, not here

    # Pattern 6: Big win — reinforcement learning
    elif is_win and pnl > 8:
        lesson = (
            f"{symbol} {side} WIN +${pnl:.0f} in {regime}, "
            f"conf={confidence:.0f}%, held {hold_min:.0f}min—replicate this setup"
        )

    # Pattern 7: Modest win — note what worked
    elif is_win and pnl > 2:
        lesson = (
            f"{symbol} {side} win +${pnl:.1f} in {regime}, "
            f"{exit_action}, {hold_min:.0f}min hold—setup works"
        )

    # Pattern 8: Breakeven / tiny outcome — don't clutter memory
    # (return None, not worth storing)

    if lesson:
        lesson = lesson[:200]  # Hard cap
        _recent_lessons.append({
            "ts": time.time(),
            "lesson": lesson,
            "symbol": symbol,
            "outcome": outcome,
        })
        logger.info(f"[POST-TRADE] Lesson: {lesson[:100]}")

    return lesson


def get_recent_lessons(n: int = 3) -> List[str]:
    """Get the N most recent lessons for snapshot injection."""
    return [entry["lesson"] for entry in list(_recent_lessons)[-n:]]


def get_lesson_stats() -> Dict[str, Any]:
    """Return stats about lessons generated (for monitoring)."""
    lessons = list(_recent_lessons)
    if not lessons:
        return {"total": 0}

    wins = sum(1 for l in lessons if l.get("outcome") == "WIN")
    losses = len(lessons) - wins

    return {
        "total": len(lessons),
        "wins": wins,
        "losses": losses,
        "latest_ts": lessons[-1].get("ts", 0) if lessons else 0,
    }
