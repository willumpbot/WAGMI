"""
Few-Shot Learning: inject similar past trades as examples for LLM decisions.

Pulls from deep memory's trade DNA to find the most relevant historical
trades matching the current signal's characteristics. Formats them as
compact examples the LLM can learn from in-context.

Output format (injected into snapshot under "examples" key):
  SIMILAR TRADES:
  WIN: SOL LONG in trend, conf=82%, +$45, exit=TP2, hold=48min
  LOSS: ETH SHORT in range, conf=68%, -$22, exit=SL, hold=12min
"""

import logging
from typing import List, Dict, Any

logger = logging.getLogger("bot.llm.few_shot")


def build_few_shot_examples(
    symbol: str,
    side: str,
    regime: str = "",
    strategy: str = "",
    confidence: float = 0.0,
    max_examples: int = 3,
    max_chars: int = 600,
) -> str:
    """Build few-shot examples from deep memory for LLM prompt injection.

    Returns a compact string of similar past trades, or empty string.
    Selects at least 1 winner and 1 loser for calibration when available.
    """
    try:
        from llm.deep_memory import get_deep_memory
        dm = get_deep_memory()
    except Exception:
        return ""

    candidates: List[Dict[str, Any]] = []

    # 1. Same symbol + same side trades (highest relevance)
    try:
        sym_trades = dm.trade_dna.get_by_symbol(symbol, limit=30)
        for t in sym_trades:
            t_side = t.get("side", "").upper()
            if t_side == side.upper() or side == "":
                t["_relevance"] = 3
                candidates.append(t)
    except Exception:
        pass

    # 2. Same regime trades (any symbol, medium relevance)
    if regime:
        try:
            reg_trades = dm.trade_dna.get_by_regime(regime, limit=20)
            _seen = {id(c) for c in candidates}
            for t in reg_trades:
                if id(t) not in _seen:
                    t["_relevance"] = 2
                    candidates.append(t)
                    _seen.add(id(t))
        except Exception:
            pass

    # 3. Sniper trades as positive exemplars (always valuable)
    try:
        snipers = dm.trade_dna.get_sniper_trades(5)
        _seen = {id(c) for c in candidates}
        for t in snipers:
            if id(t) not in _seen:
                t["_relevance"] = 1
                candidates.append(t)
                _seen.add(id(t))
    except Exception:
        pass

    if not candidates:
        return ""

    # Score and sort candidates by relevance
    for c in candidates:
        score = c.get("_relevance", 0) * 10
        if c.get("symbol") == symbol:
            score += 5
        if c.get("regime") == regime and regime:
            score += 3
        if c.get("side", "").upper() == side.upper() and side:
            score += 2
        c["_score"] = score

    candidates.sort(key=lambda x: x.get("_score", 0), reverse=True)

    # Select: at least 1 winner and 1 loser for calibration
    winners = [c for c in candidates if c.get("outcome") == "WIN"]
    losers = [c for c in candidates if c.get("outcome") == "LOSS"]

    selected: List[Dict] = []
    if winners:
        selected.append(winners[0])
    if losers:
        selected.append(losers[0])
    # Fill remaining with highest-scored
    for c in candidates:
        if len(selected) >= max_examples:
            break
        if c not in selected:
            selected.append(c)

    # Format compactly
    lines = []
    for t in selected[:max_examples]:
        outcome = t.get("outcome", "?")
        hold_s = t.get("hold_time_s", 0)
        hold_str = f"{hold_s / 60:.0f}min" if hold_s else "?"
        setup = t.get("setup_type", "")
        setup_str = f" setup={setup}" if setup else ""
        thesis_ok = t.get("thesis_correct")
        thesis_str = ""
        if thesis_ok is True:
            thesis_str = " thesis=correct"
        elif thesis_ok is False:
            thesis_str = " thesis=wrong"
        line = (
            f"{outcome}: {t.get('symbol', '?')} {t.get('side', '?')} "
            f"in {t.get('regime', '?')}, "
            f"conf={t.get('confidence', 0):.0f}%, "
            f"${t.get('pnl', 0):+.0f}, "
            f"exit={t.get('exit_reason', t.get('exit_action', '?'))}, "
            f"hold={hold_str}{setup_str}{thesis_str}"
        )
        lines.append(line)

    if not lines:
        return ""

    result = "SIMILAR TRADES:\n" + "\n".join(lines)
    return result[:max_chars]
