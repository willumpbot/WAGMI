"""Learning Analyzer - W3-C integration layer.

Orchestrates closed trade analysis and memory enrichment
before Learning Agent execution.

Pipeline:
  Position closes → extract_lessons() → enrich_memory() → pass context to Learning Agent
"""

from typing import Dict, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def analyze_and_enrich_closed_trade(
    trade_data: Dict[str, Any],
    decisions_log_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Analyze closed trade and enrich memory with lessons.

    Args:
        trade_data: Closed trade data with entry/exit prices, times, PnL, etc.
                    Expected keys: symbol, side, entry_price, exit_price,
                                   entry_time, exit_time, position_size,
                                   regime, confidence_predicted, n_agree, pnl_usd
        decisions_log_path: Optional path to decisions.jsonl (for testing)

    Returns:
        Dict with enrichment results + extracted lessons for Learning Agent context
    """
    result = {
        "lessons_extracted": 0,
        "memory_enriched": 0,
        "lessons": [],
        "enrichment_notes": [],
        "error": None,
    }

    try:
        # 1. Analyze closed trade with closed_trade_analyzer
        lesson = _extract_lesson(trade_data, decisions_log_path)
        if lesson:
            result["lessons_extracted"] = 1
            result["lessons"].append(lesson)

            # 2. Enrich memory with extracted lesson
            enrichment_result = _enrich_memory(lesson, trade_data)
            result["memory_enriched"] = enrichment_result.get("total_enrichments", 0)
            result["enrichment_notes"] = enrichment_result.get("notes", [])

            # 3. Log for observability
            logger.info(
                f"[LEARNING-ANALYZER] {trade_data.get('symbol', 'N/A')}: "
                f"extracted={result['lessons_extracted']}, "
                f"enriched={result['memory_enriched']}"
            )

    except Exception as e:
        logger.error(f"[LEARNING-ANALYZER] Failed to analyze closed trade: {e}", exc_info=True)
        result["error"] = str(e)

    return result


def _extract_lesson(
    trade_data: Dict[str, Any],
    decisions_log_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Extract lesson from closed trade using closed_trade_analyzer.

    Args:
        trade_data: Trade execution data
        decisions_log_path: Optional path to decisions.jsonl

    Returns:
        TradeLesson dict or None if extraction fails
    """
    try:
        from llm.learning.closed_trade_analyzer import ClosedTradeAnalyzer

        if decisions_log_path:
            analyzer = ClosedTradeAnalyzer(decisions_log_path=decisions_log_path)
        else:
            analyzer = ClosedTradeAnalyzer()

        # Map trade_data to analyzer parameters
        symbol = trade_data.get("symbol", "")
        side = trade_data.get("side", "BUY")
        entry_price = trade_data.get("entry_price", 0.0)
        exit_price = trade_data.get("exit_price", 0.0)
        position_size = trade_data.get("position_size", 0.0)
        entry_risk_pct = trade_data.get("entry_risk_pct", 0.02)
        regime = trade_data.get("regime", "unknown")
        confidence_predicted = (trade_data.get("confidence_predicted", 0.0) or 0.0) / 100.0
        n_agree = trade_data.get("n_agree", 1)

        # Timestamps
        entry_time = trade_data.get("entry_time")
        exit_time = trade_data.get("exit_time")
        if isinstance(entry_time, str):
            entry_time = datetime.fromisoformat(entry_time)
        if isinstance(exit_time, str):
            exit_time = datetime.fromisoformat(exit_time)
        if not entry_time:
            entry_time = datetime.utcnow()
        if not exit_time:
            exit_time = datetime.utcnow()

        # Trade ID
        trade_id = trade_data.get("trade_id", f"trade_{symbol}_{int(entry_time.timestamp())}")

        # Call analyzer
        lesson = analyzer.analyze(
            trade_id=trade_id,
            symbol=symbol,
            entry_price=entry_price,
            exit_price=exit_price,
            entry_time=entry_time,
            exit_time=exit_time,
            position_size=position_size,
            entry_risk_pct=entry_risk_pct,
            regime=regime,
            side=side,
        )

        if lesson:
            return {
                "trade_id": lesson.trade_id,
                "symbol": lesson.symbol,
                "setup_type": lesson.setup_type,
                "confidence_correct": lesson.confidence_correct,
                "pnl_usd": lesson.pnl_usd,
                "pnl_pct": lesson.pnl_pct,
                "r_multiple": lesson.r_multiple,
                "hold_duration_minutes": lesson.hold_duration_minutes,
                "lessons": lesson.lessons,
                "risk_flags": lesson.risk_flags,
                "entry_thesis": lesson.entry_thesis,
                "outcome_thesis": lesson.outcome_thesis,
            }

    except Exception as e:
        logger.debug(f"[LEARNING-ANALYZER] Lesson extraction failed: {e}")

    return None


def _enrich_memory(
    lesson: Dict[str, Any],
    trade_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Enrich memory with extracted lesson.

    Args:
        lesson: Extracted lesson from analyzer
        trade_data: Original trade data for context

    Returns:
        Dict with enrichment results
    """
    result = {
        "total_enrichments": 0,
        "notes": [],
    }

    try:
        from llm.learning.memory_enrichment import MemoryEnricher

        enricher = MemoryEnricher()

        # Convert lesson dict back to TradeLesson dataclass for enrichment
        from llm.learning.closed_trade_analyzer import TradeLesson

        trade_lesson = TradeLesson(
            trade_id=lesson.get("trade_id", ""),
            symbol=lesson.get("symbol", ""),
            entry_time=datetime.utcnow(),
            exit_time=datetime.utcnow(),
            entry_thesis=lesson.get("entry_thesis", ""),
            outcome_thesis=lesson.get("outcome_thesis", ""),
            setup_type=lesson.get("setup_type", ""),
            confidence_correct=lesson.get("confidence_correct", False),
            pnl_usd=lesson.get("pnl_usd", 0.0),
            pnl_pct=lesson.get("pnl_pct", 0.0),
            r_multiple=lesson.get("r_multiple", 0.0),
            hold_duration_minutes=lesson.get("hold_duration_minutes", 0),
            lessons=lesson.get("lessons", []),
            risk_flags=lesson.get("risk_flags", []),
        )

        # Enrich memory
        enrichment_result = enricher.enrich_memory(trade_lesson)
        result["total_enrichments"] = (
            enrichment_result.get("notes_added", 0)
            + enrichment_result.get("patterns_updated", 0)
            + enrichment_result.get("rules_graduated", 0)
        )
        result["notes"] = [
            f"notes_added={enrichment_result.get('notes_added', 0)}",
            f"patterns_updated={enrichment_result.get('patterns_updated', 0)}",
            f"rules_graduated={enrichment_result.get('rules_graduated', 0)}",
        ]

    except Exception as e:
        logger.debug(f"[LEARNING-ANALYZER] Memory enrichment failed: {e}")

    return result


def build_learning_context(
    analysis_result: Dict[str, Any],
    trade_data: Dict[str, Any],
) -> str:
    """Build context string for Learning Agent prompt.

    Args:
        analysis_result: Result from analyze_and_enrich_closed_trade()
        trade_data: Original trade data

    Returns:
        Context string to inject into Learning Agent prompt
    """
    context_lines = []

    # Trade summary
    context_lines.append(
        f"Trade: {trade_data.get('symbol', 'N/A')} "
        f"{trade_data.get('side', 'BUY')} "
        f"PnL: {trade_data.get('pnl_usd', 0):+.2f} USD "
        f"({trade_data.get('pnl_pct', 0):+.1%})"
    )

    # Extracted lessons
    if analysis_result.get("lessons"):
        context_lines.append("Extracted lessons:")
        for lesson in analysis_result["lessons"]:
            context_lines.append(f"  - Setup: {lesson.get('setup_type', 'unknown')}")
            context_lines.append(f"  - Thesis correct: {lesson.get('confidence_correct', False)}")
            for lesson_item in lesson.get("lessons", []):
                context_lines.append(f"  - {lesson_item}")

    # Memory enrichment notes
    if analysis_result.get("enrichment_notes"):
        context_lines.append("Memory enriched:")
        for note in analysis_result["enrichment_notes"]:
            context_lines.append(f"  - {note}")

    return "\n".join(context_lines)
