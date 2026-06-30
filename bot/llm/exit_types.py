"""
Exit decision types for LLM-driven exit logic.

The LLM can suggest modifications to open positions:
- hold: do nothing, let existing SL/TP work
- tighten_sl: move SL closer to current price (more protective)
- widen_tp: extend TP target (let winner run)
- close: full early exit at market
- partial: partial close at market

Safety rules (enforced in exit_engine.py):
- SL cannot be widened beyond original baseline SL
- TP cannot be tightened below breakeven unless confidence > 0.7
- Early exit requires confidence > 0.6
- Partial exit requires remaining qty > min_qty * 2
"""

from dataclasses import dataclass
from typing import Optional


VALID_EXIT_ACTIONS = {"hold", "tighten_sl", "widen_tp", "close", "partial"}


@dataclass
class ExitDecision:
    """LLM's recommendation for an open position."""
    symbol: str
    exit_action: str      # "hold", "tighten_sl", "widen_tp", "close", "partial"
    exit_confidence: float  # 0.0-1.0
    new_sl: Optional[float] = None    # For tighten_sl
    new_tp: Optional[float] = None    # For widen_tp
    partial_pct: float = 0.5          # For partial exit (0.0-1.0 of remaining qty)
    reason: str = ""

    def __post_init__(self):
        # The exit agent sometimes emits partial_pct as a PERCENT (e.g. 50) instead of a
        # fraction (0.5), which made every such partial-close fail validation ("out of range: 50")
        # — a hidden cause of dead-capital positions never being trimmed. Normalize it.
        try:
            if self.partial_pct is not None and 1.0 < float(self.partial_pct) <= 100.0:
                self.partial_pct = float(self.partial_pct) / 100.0
        except (TypeError, ValueError):
            pass

    def validate(self) -> tuple:
        """Basic validation. Returns (ok, error_msg)."""
        if self.exit_action not in VALID_EXIT_ACTIONS:
            return False, f"Invalid exit_action: {self.exit_action}"
        if not 0.0 <= self.exit_confidence <= 1.0:
            return False, f"exit_confidence out of range: {self.exit_confidence}"
        if self.exit_action == "tighten_sl" and self.new_sl is None:
            return False, "tighten_sl requires new_sl"
        if self.exit_action == "widen_tp" and self.new_tp is None:
            return False, "widen_tp requires new_tp"
        if self.exit_action == "partial":
            if not 0.0 < self.partial_pct <= 1.0:
                return False, f"partial_pct out of range: {self.partial_pct}"
        return True, ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "exit_action": self.exit_action,
            "exit_confidence": self.exit_confidence,
            "new_sl": self.new_sl,
            "new_tp": self.new_tp,
            "partial_pct": self.partial_pct,
            "reason": self.reason,
        }
