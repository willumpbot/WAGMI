"""
LLM Signal Analyzer: Full-depth analysis of incoming trading signals.

This is the brain that evaluates every ingested signal with a
DIGESTIBLE THOUGHT PROCESS. Instead of a black-box "take/skip",
the LLM produces a structured analysis that shows:

  1. SIGNAL COMPREHENSION - "What is this signal telling me?"
  2. CHART READING       - "What does the chart actually show?"
  3. CONTEXT CHECK       - "Does this fit the current market?"
  4. HISTORICAL MATCH    - "Have I seen this setup before?"
  5. RISK ASSESSMENT     - "What's the R:R and can I afford this?"
  6. VERDICT            - "TAKE / SKIP / MODIFY + why"

The analysis is:
  - Logged to disk for review
  - Sent to Telegram so you can read the thought process
  - Fed back into the learning system so the LLM improves
  - Tracked for accuracy (was the verdict correct?)

This is NOT the same as the decision_engine.py veto system.
That system runs on internally-generated signals from the ensemble.
THIS system analyzes EXTERNAL signals from Telegram channels.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

logger = logging.getLogger("bot.signals.llm_analyzer")

_ANALYSIS_DIR = os.path.join("data", "signals", "analyses")
_ANALYSIS_LOG = os.path.join(_ANALYSIS_DIR, "signal_analyses.jsonl")


@dataclass
class SignalAnalysis:
    """Complete LLM analysis of a trading signal."""
    analysis_id: str = ""
    signal_id: str = ""
    timestamp: float = 0.0

    # Input
    symbol: str = ""
    side: str = ""
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    source: str = ""

    # Analysis sections (digestible thought process)
    signal_comprehension: str = ""    # What the signal is saying
    chart_reading: str = ""           # What the chart shows at this moment
    context_check: str = ""           # Current market context alignment
    historical_match: str = ""        # Similar past setups and outcomes
    risk_assessment: str = ""         # R:R ratio, position sizing, risk
    knowledge_applied: str = ""       # What learned knowledge influenced this

    # Verdict
    verdict: str = ""                 # TAKE, SKIP, MODIFY
    verdict_confidence: float = 0.0   # 0-1
    verdict_reasoning: str = ""       # One-paragraph summary
    modifications: Dict[str, Any] = field(default_factory=dict)  # If MODIFY

    # Meta
    llm_model: str = ""
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    llm_latency_ms: int = 0
    curriculum_level: int = 0
    learning_phase: str = ""

    # Outcome tracking (filled later)
    outcome_tracked: bool = False
    actual_outcome: str = ""          # WIN, LOSS, MISSED
    actual_pnl: float = 0.0
    verdict_was_correct: bool = False


def _build_analysis_prompt(
    signal_data: Dict[str, Any],
    market_data: Dict[str, Any],
    knowledge_context: str,
    curriculum_level: int,
    learning_phase: str,
) -> str:
    """Build the analysis prompt for the LLM.

    The prompt structure enforces the digestible thought process.
    """
    # Build signal description
    signal_desc = (
        f"INCOMING SIGNAL:\n"
        f"  Symbol: {signal_data.get('symbol', '?')}\n"
        f"  Side: {signal_data.get('side', '?')}\n"
        f"  Entry: {signal_data.get('entry_price', 0)}\n"
        f"  Stop Loss: {signal_data.get('stop_loss', 0)}\n"
        f"  Take Profit 1: {signal_data.get('take_profit_1', 0)}\n"
        f"  Take Profit 2: {signal_data.get('take_profit_2', 0)}\n"
        f"  Leverage: {signal_data.get('leverage', 1)}x\n"
        f"  Source: {signal_data.get('source', 'external')}\n"
        f"  Raw message: {signal_data.get('raw_message', '')[:300]}\n"
    )

    # Build market context
    market_desc = "CURRENT MARKET DATA:\n"
    if market_data:
        for key, val in market_data.items():
            if isinstance(val, float):
                market_desc += f"  {key}: {val:.4f}\n"
            else:
                market_desc += f"  {key}: {val}\n"
    else:
        market_desc += "  (No live market data available - analyze based on signal alone)\n"

    # Knowledge injection
    knowledge_section = ""
    if knowledge_context:
        knowledge_section = f"\nYOUR ACCUMULATED KNOWLEDGE:\n{knowledge_context}\n"

    prompt = f"""You are analyzing an external trading signal. Your job is to produce a CLEAR,
STRUCTURED analysis that shows your complete thought process. You are currently at
curriculum level {curriculum_level} ({learning_phase}).

{signal_desc}

{market_desc}

{knowledge_section}

Respond with a JSON object containing these REQUIRED fields:

{{
  "signal_comprehension": "What is this signal telling me? Explain what the signal provider is seeing. What setup are they trading? Is this a breakout, reversal, trend continuation, range trade? (2-3 sentences)",

  "chart_reading": "Based on the entry, SL, and TP levels, what does the chart structure look like? Where are key support/resistance levels relative to this trade? Is price near a significant zone? (2-3 sentences)",

  "context_check": "Does this signal align with the current market environment? Consider: overall market trend (BTC direction), volatility regime, time of day/week, any major events. Flag conflicts. (2-3 sentences)",

  "historical_match": "Have I seen similar setups before? What happened? If I have knowledge of past trades in this symbol/regime/setup, reference them. If no history yet, say so honestly. (1-3 sentences)",

  "risk_assessment": "Calculate the risk-reward ratio. Entry-to-SL distance vs Entry-to-TP distance. Is the R:R acceptable (minimum 1.5:1)? What position size would be appropriate given current equity and risk rules? Flag if leverage is too high. (2-3 sentences)",

  "knowledge_applied": "What specific pieces of learned knowledge influenced this analysis? List any axioms, principles, or past patterns that apply. If still in early learning, say what you're watching for. (1-2 sentences)",

  "verdict": "TAKE or SKIP or MODIFY",

  "verdict_confidence": 0.0 to 1.0,

  "verdict_reasoning": "A clear 2-3 sentence explanation of why you chose this verdict. Be specific - reference the analysis above. A human should read this and immediately understand your logic.",

  "modifications": {{}}
}}

If verdict is MODIFY, populate modifications with suggested changes:
{{"entry_price": ..., "stop_loss": ..., "take_profit_1": ..., "leverage": ...}}

CRITICAL RULES:
- Be honest about what you DON'T know yet (early learning phases)
- Never fabricate chart data or market conditions
- The R:R calculation is math, not opinion - show the numbers
- If the signal source is unknown/untrusted, factor that into confidence
- Your verdict_reasoning must be readable by a non-technical person
- Keep each section concise but substantive (not one-word answers)"""

    return prompt


def analyze_signal(
    signal_data: Dict[str, Any],
    market_data: Dict[str, Any] = None,
    knowledge_context: str = "",
    curriculum_level: int = 1,
    learning_phase: str = "ABSORB",
) -> Optional[SignalAnalysis]:
    """Run full LLM analysis on a trading signal.

    Args:
        signal_data: Parsed signal dict (from IngestedSignal)
        market_data: Current market data for the symbol
        knowledge_context: Knowledge base summary for LLM context
        curriculum_level: Current curriculum level (1-5)
        learning_phase: Current learning phase name

    Returns:
        SignalAnalysis with full thought process, or None on failure
    """
    from llm.client import call_llm

    analysis_id = f"analysis-{int(time.time()*1000)}"

    prompt = _build_analysis_prompt(
        signal_data=signal_data,
        market_data=market_data or {},
        knowledge_context=knowledge_context,
        curriculum_level=curriculum_level,
        learning_phase=learning_phase,
    )

    system_prompt = (
        "You are a professional crypto trading analyst. You analyze external trading signals "
        "with rigorous methodology. You produce structured JSON analyses that show your "
        "complete thought process. You are learning and improving with every signal you see. "
        "Always respond with valid JSON only - no markdown, no code blocks, just the JSON object."
    )

    raw_text, usage = call_llm(
        system_prompt=system_prompt,
        snapshot_json=prompt,
        max_tokens=1200,
        max_retries=2,
    )

    if raw_text is None:
        logger.warning(f"[SIGNAL-ANALYZER] LLM call failed: {usage.get('error', 'unknown')}")
        return None

    # Parse the JSON response
    try:
        # Strip any markdown code block wrappers
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()

        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.warning(f"[SIGNAL-ANALYZER] Failed to parse LLM response: {e}")
        logger.debug(f"[SIGNAL-ANALYZER] Raw: {raw_text[:500]}")
        return None

    analysis = SignalAnalysis(
        analysis_id=analysis_id,
        signal_id=signal_data.get("signal_id", ""),
        timestamp=time.time(),
        symbol=signal_data.get("symbol", ""),
        side=signal_data.get("side", ""),
        entry_price=signal_data.get("entry_price", 0),
        stop_loss=signal_data.get("stop_loss", 0),
        take_profit_1=signal_data.get("take_profit_1", 0),
        source=signal_data.get("source_channel_name", "external"),
        signal_comprehension=data.get("signal_comprehension", ""),
        chart_reading=data.get("chart_reading", ""),
        context_check=data.get("context_check", ""),
        historical_match=data.get("historical_match", ""),
        risk_assessment=data.get("risk_assessment", ""),
        knowledge_applied=data.get("knowledge_applied", ""),
        verdict=data.get("verdict", "SKIP").upper(),
        verdict_confidence=float(data.get("verdict_confidence", 0.0)),
        verdict_reasoning=data.get("verdict_reasoning", ""),
        modifications=data.get("modifications", {}),
        llm_model="claude-sonnet-4-5-20250929",
        llm_tokens_in=usage.get("input_tokens", 0),
        llm_tokens_out=usage.get("output_tokens", 0),
        llm_latency_ms=usage.get("latency_ms", 0),
        curriculum_level=curriculum_level,
        learning_phase=learning_phase,
    )

    # Validate verdict
    if analysis.verdict not in ("TAKE", "SKIP", "MODIFY"):
        analysis.verdict = "SKIP"
        analysis.verdict_reasoning += " (Invalid verdict normalized to SKIP)"

    # Log analysis
    _log_analysis(analysis)

    logger.info(
        f"[SIGNAL-ANALYZER] {analysis.symbol} {analysis.side}: "
        f"{analysis.verdict} (conf={analysis.verdict_confidence:.0%}) "
        f"- {analysis.verdict_reasoning[:80]}"
    )

    return analysis


def _log_analysis(analysis: SignalAnalysis):
    """Log analysis to JSONL file."""
    os.makedirs(_ANALYSIS_DIR, exist_ok=True)
    try:
        with open(_ANALYSIS_LOG, "a") as f:
            f.write(json.dumps(asdict(analysis), default=str) + "\n")
    except IOError as e:
        logger.warning(f"[SIGNAL-ANALYZER] Failed to log: {e}")


def record_analysis_outcome(
    analysis_id: str,
    actual_outcome: str,
    actual_pnl: float,
):
    """Record what actually happened after the analysis.

    This is called later when we know whether the signal would have
    been profitable or not. Essential for the LLM's self-improvement.
    """
    if not os.path.exists(_ANALYSIS_LOG):
        return

    try:
        lines = []
        updated = False
        with open(_ANALYSIS_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("analysis_id") == analysis_id:
                        entry["outcome_tracked"] = True
                        entry["actual_outcome"] = actual_outcome
                        entry["actual_pnl"] = actual_pnl
                        # Was the verdict correct?
                        verdict = entry.get("verdict", "")
                        if verdict == "TAKE" and actual_outcome == "WIN":
                            entry["verdict_was_correct"] = True
                        elif verdict == "SKIP" and actual_outcome == "LOSS":
                            entry["verdict_was_correct"] = True
                        elif verdict == "TAKE" and actual_outcome == "LOSS":
                            entry["verdict_was_correct"] = False
                        elif verdict == "SKIP" and actual_outcome == "WIN":
                            entry["verdict_was_correct"] = False
                        else:
                            entry["verdict_was_correct"] = None
                        updated = True
                    lines.append(json.dumps(entry, default=str))
                except json.JSONDecodeError:
                    lines.append(line)

        if updated:
            with open(_ANALYSIS_LOG, "w") as f:
                f.write("\n".join(lines) + "\n")
            logger.info(f"[SIGNAL-ANALYZER] Outcome recorded for {analysis_id}: {actual_outcome}")
    except IOError as e:
        logger.warning(f"[SIGNAL-ANALYZER] Failed to record outcome: {e}")


def get_analysis_accuracy() -> Dict[str, Any]:
    """Calculate the LLM's signal analysis accuracy over time."""
    if not os.path.exists(_ANALYSIS_LOG):
        return {"total": 0, "tracked": 0, "accuracy": 0.0}

    total = 0
    tracked = 0
    correct = 0
    take_correct = 0
    take_total = 0
    skip_correct = 0
    skip_total = 0

    try:
        with open(_ANALYSIS_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    total += 1
                    if entry.get("outcome_tracked"):
                        tracked += 1
                        was_correct = entry.get("verdict_was_correct")
                        if was_correct is True:
                            correct += 1
                        verdict = entry.get("verdict", "")
                        if verdict == "TAKE":
                            take_total += 1
                            if was_correct:
                                take_correct += 1
                        elif verdict == "SKIP":
                            skip_total += 1
                            if was_correct:
                                skip_correct += 1
                except json.JSONDecodeError:
                    pass
    except IOError:
        pass

    return {
        "total_analyses": total,
        "outcomes_tracked": tracked,
        "overall_accuracy": correct / tracked if tracked > 0 else 0.0,
        "take_accuracy": take_correct / take_total if take_total > 0 else 0.0,
        "take_total": take_total,
        "skip_accuracy": skip_correct / skip_total if skip_total > 0 else 0.0,
        "skip_total": skip_total,
    }


def format_analysis_for_telegram(analysis: SignalAnalysis) -> str:
    """Format a signal analysis into a readable Telegram message.

    This is the DIGESTIBLE THOUGHT PROCESS the user reads.
    """
    verdict_icon = {
        "TAKE": "TAKE",
        "SKIP": "SKIP",
        "MODIFY": "MODIFY",
    }.get(analysis.verdict, "?")

    conf_bar = int(analysis.verdict_confidence * 10)
    conf_display = "#" * conf_bar + "-" * (10 - conf_bar)

    lines = [
        f"*Signal Analysis: {analysis.symbol} {analysis.side}*",
        f"Source: {analysis.source}",
        "",
        f"*1. Signal Comprehension*",
        analysis.signal_comprehension or "(pending)",
        "",
        f"*2. Chart Reading*",
        analysis.chart_reading or "(pending)",
        "",
        f"*3. Context Check*",
        analysis.context_check or "(pending)",
        "",
        f"*4. Historical Match*",
        analysis.historical_match or "(no history yet)",
        "",
        f"*5. Risk Assessment*",
        analysis.risk_assessment or "(pending)",
        "",
        f"*6. Knowledge Applied*",
        analysis.knowledge_applied or "(still learning)",
        "",
        f"━━━━━━━━━━━━━━━━━━━━━━━",
        f"*VERDICT: [{verdict_icon}]* ({analysis.verdict_confidence:.0%})",
        f"[{conf_display}]",
        "",
        analysis.verdict_reasoning,
    ]

    if analysis.modifications:
        lines.append("")
        lines.append("*Suggested Modifications:*")
        for key, val in analysis.modifications.items():
            lines.append(f"  {key}: {val}")

    lines.extend([
        "",
        f"_Level {analysis.curriculum_level} | {analysis.learning_phase} | "
        f"{analysis.llm_tokens_in + analysis.llm_tokens_out} tokens_",
    ])

    return "\n".join(lines)


def get_recent_analyses(limit: int = 20) -> List[Dict]:
    """Load recent analyses."""
    if not os.path.exists(_ANALYSIS_LOG):
        return []
    try:
        entries = []
        with open(_ANALYSIS_LOG) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries[-limit:]
    except IOError:
        return []
