"""
LLM autonomy modes: controls how much influence the meta-brain has.

Progression:
  OFF       -> LLM not called at all. Pure strategy-driven.
  ADVISORY  -> LLM called, decision logged, but bot uses its own logic.
               Use this to validate LLM quality before trusting it.
  VETO_ONLY -> LLM called synchronously before trade entry.
               Can only output "proceed" or "flat" (no sizing, no flips).
               Vetoed trades are logged for dual-world comparison.
  SIZING    -> LLM confidence + size_multiplier scale position size.
               Bot still picks direction from ensemble.
  DIRECTION -> LLM picks proceed/flat/flip. Bot handles sizing + execution.
  FULL      -> LLM drives direction + sizing. Bot handles execution + risk.
               Still gated by RiskManager + CircuitBreaker.

In ALL modes, the Python bot's risk engine has final veto power.
The LLM can never bypass CircuitBreaker, max positions, or daily loss limits.

Set via env: LLM_MODE=0|1|2|3|4|5
"""

import os
import logging
from enum import IntEnum

logger = logging.getLogger("bot.llm.autonomy")


class LLMMode(IntEnum):
    OFF = 0
    ADVISORY = 1
    VETO_ONLY = 2
    SIZING = 3
    DIRECTION = 4
    FULL = 5


def get_llm_mode() -> LLMMode:
    """Read LLM mode from environment. Defaults to OFF."""
    raw = os.getenv("LLM_MODE", "0")
    try:
        mode = LLMMode(int(raw))
    except (ValueError, KeyError):
        logger.warning(f"Invalid LLM_MODE={raw!r}, defaulting to OFF")
        mode = LLMMode.OFF

    return mode


def should_call_llm(mode: LLMMode) -> bool:
    """Whether the LLM should be called at all in this mode."""
    return mode != LLMMode.OFF


def llm_has_veto(mode: LLMMode) -> bool:
    """Whether the LLM can veto (block) trades before entry."""
    return mode >= LLMMode.VETO_ONLY


def llm_controls_direction(mode: LLMMode) -> bool:
    """Whether the LLM output overrides ensemble direction."""
    return mode in (LLMMode.DIRECTION, LLMMode.FULL)


def llm_controls_sizing(mode: LLMMode) -> bool:
    """Whether the LLM output influences position sizing."""
    return mode in (LLMMode.SIZING, LLMMode.FULL)


def describe_mode(mode: LLMMode) -> str:
    """Human-readable description of what the mode does."""
    descriptions = {
        LLMMode.OFF: "LLM disabled. Pure strategy-driven trading.",
        LLMMode.ADVISORY: "LLM runs but does not influence trades. Decisions logged for comparison.",
        LLMMode.VETO_ONLY: "LLM can veto trades (proceed/flat). No sizing or direction changes.",
        LLMMode.SIZING: "LLM confidence + size_multiplier scale position size. Direction from ensemble.",
        LLMMode.DIRECTION: "LLM picks proceed/flat/flip direction. Bot handles sizing.",
        LLMMode.FULL: "LLM drives direction + sizing. Bot handles execution + risk.",
    }
    return descriptions.get(mode, "Unknown mode")
