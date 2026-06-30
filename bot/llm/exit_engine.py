"""
Exit Engine: LLM-driven exit logic for open positions.

Evaluates open positions periodically and suggests exit modifications.
All suggestions pass through safety gating before execution.

Integration:
  Called from multi_strategy_main._tick_once() after position update_price().
  Only active when LLM mode >= SIZING (mode 3+).

Safety rules (non-negotiable):
  1. SL can only be tightened (moved closer to price), never widened beyond original
  2. TP can only be widened (let winner run), not tightened below breakeven
  3. Early close requires confidence >= 0.60
  4. Partial close requires remaining qty > min_qty * 2
  5. All modifications logged to exit_decisions.jsonl
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from llm.exit_types import ExitDecision, VALID_EXIT_ACTIONS
from execution.position_manager import Position
from execution.precision import round_price, get_min_qty

logger = logging.getLogger("bot.llm.exit_engine")

_EXIT_LOG_DIR = os.path.join("data", "logs")
_EXIT_LOG_FILE = os.path.join(_EXIT_LOG_DIR, "exit_decisions.jsonl")

# Minimum seconds between exit evaluations per symbol
EXIT_EVAL_COOLDOWN_S = int(os.getenv("EXIT_EVAL_COOLDOWN_S", "120"))


class ExitEngine:
    """Evaluates and applies LLM exit suggestions to open positions."""

    def __init__(self):
        self._last_eval: Dict[str, float] = {}  # symbol -> timestamp of last eval
        os.makedirs(_EXIT_LOG_DIR, exist_ok=True)

    def should_evaluate(self, symbol: str) -> bool:
        """Check if enough time has passed since last exit evaluation."""
        last = self._last_eval.get(symbol, 0)
        return (time.time() - last) >= EXIT_EVAL_COOLDOWN_S

    def mark_evaluated(self, symbol: str):
        """Mark a symbol as recently evaluated."""
        self._last_eval[symbol] = time.time()

    def apply_exit_decision(
        self,
        decision: ExitDecision,
        position: Position,
        current_price: float,
    ) -> Dict[str, Any]:
        """Apply an exit decision to a position with safety gating.

        Returns a dict describing what was done:
          {"applied": bool, "action": str, "details": str}
        """
        # Validate decision
        ok, err = decision.validate()
        if not ok:
            logger.warning(f"[EXIT-ENGINE] Invalid decision for {decision.symbol}: {err}")
            return {"applied": False, "action": "rejected", "details": err}

        # Safety gate
        ok, reason = self._safety_gate(decision, position, current_price)
        if not ok:
            logger.info(f"[EXIT-ENGINE] {decision.symbol} safety gate: {reason}")
            self._log_decision(decision, position, False, reason)
            return {"applied": False, "action": "safety_gated", "details": reason}

        # Apply the decision
        result = self._execute(decision, position, current_price)
        self._log_decision(decision, position, result["applied"], result["details"])
        self.mark_evaluated(decision.symbol)
        return result

    def _safety_gate(
        self,
        decision: ExitDecision,
        position: Position,
        current_price: float,
    ) -> tuple:
        """Apply safety rules. Returns (ok, reason)."""
        is_long = position.side == "LONG"

        if decision.exit_action == "hold":
            return True, ""

        # Rule 1: SL can only be tightened (moved closer to price)
        if decision.exit_action == "tighten_sl" and decision.new_sl is not None:
            if is_long:
                # For longs, tightening = moving SL UP (closer to price)
                if decision.new_sl < position.sl:
                    return False, f"Cannot widen SL (long): {decision.new_sl} < current {position.sl}"
                if decision.new_sl >= current_price:
                    return False, f"SL above current price: {decision.new_sl} >= {current_price}"
            else:
                # For shorts, tightening = moving SL DOWN (closer to price)
                if decision.new_sl > position.sl:
                    return False, f"Cannot widen SL (short): {decision.new_sl} > current {position.sl}"
                if decision.new_sl <= current_price:
                    return False, f"SL below current price: {decision.new_sl} <= {current_price}"

        # Rule 2: TP can only be widened (extended further from entry)
        if decision.exit_action == "widen_tp" and decision.new_tp is not None:
            if is_long:
                if decision.new_tp < position.tp2:
                    return False, f"Cannot tighten TP (long): {decision.new_tp} < current TP2 {position.tp2}"
                # Don't allow widening TP below breakeven
                if decision.new_tp <= position.entry and decision.exit_confidence < 0.7:
                    return False, "TP below entry requires confidence >= 0.7"
            else:
                if decision.new_tp > position.tp2:
                    return False, f"Cannot tighten TP (short): {decision.new_tp} > current TP2 {position.tp2}"
                if decision.new_tp >= position.entry and decision.exit_confidence < 0.7:
                    return False, "TP above entry requires confidence >= 0.7"

        # Rule 3: Early close confidence threshold
        # Profitable positions need MUCH higher bar to close — let trailing stop handle exits.
        # Only close a winner if thesis is truly dead (regime shift, not normal pullback).
        if decision.exit_action == "close":
            # EVIDENCE GATE (2026-06-23): LLM exit-agent FULL-CLOSE authority is OFF by default.
            # Measured 0 wins / 71 closes (-$1,502.92); it produced ZERO of the 19 winners while
            # mechanical SL/TP/trailing produce 100% of profit. The agent keeps tighten_sl / partial /
            # hold authority; mechanical exits handle full closes. Re-enable per-regime once it
            # demonstrates positive exit edge on counterfactual scoring. Reversible: EXIT_AGENT_FULL_CLOSE=true.
            is_profitable = (current_price > position.entry) if is_long else (current_price < position.entry)
            _gate_open = os.getenv("EXIT_AGENT_FULL_CLOSE", "false").lower() == "true"
            _reason_l = (decision.reason or "").lower()
            _dead_capital = any(k in _reason_l for k in (
                "dead capital", "no-progress", "no progress", "no progres",
                "thesis invalidated", "thesis invalid", "invalidated", "toxic"))
            # CONDITIONAL RE-ENABLE (2026-06-30, owner-approved): the blanket OFF was right for the
            # agent CUTTING WINNERS (measured 0/71). But it also blocked legitimate dead-capital /
            # thesis-invalidated exits on NON-winners, so flat/losing positions piled up forever
            # (5 stuck ~11h, 0 closes). Allow full_close ONLY when the reason is dead-capital/
            # thesis-invalid AND the position is not a winner; still block discretionary closes and
            # all winner-cutting (those still need EXIT_AGENT_FULL_CLOSE=true or >=0.90 conf below).
            if not _gate_open and not (_dead_capital and not is_profitable):
                return False, ("Exit-agent full-close disabled except dead-capital/thesis-invalid losers "
                               "(measured 0/71 on discretionary closes); mechanical SL/TP/trailing handle the rest.")
            if is_profitable:
                # Winning trade: require 0.90 confidence to override trailing stop
                if decision.exit_confidence < 0.90:
                    return False, f"Closing WINNER requires confidence >= 0.90 (got {decision.exit_confidence:.2f}). Let trailing stop handle it."
            else:
                # Losing trade: normal threshold
                if decision.exit_confidence < 0.60:
                    return False, f"Close requires confidence >= 0.60 (got {decision.exit_confidence:.2f})"

        # Rule 4: Partial close requires sufficient remaining qty
        if decision.exit_action == "partial":
            if decision.exit_confidence < 0.50:
                return False, f"Partial requires confidence >= 0.50 (got {decision.exit_confidence:.2f})"
            min_qty = get_min_qty(position.symbol)
            remaining_after = position.qty * (1 - decision.partial_pct)
            if remaining_after < min_qty:
                return False, f"Partial would leave {remaining_after} < min_qty {min_qty}"

        return True, ""

    def _execute(
        self,
        decision: ExitDecision,
        position: Position,
        current_price: float,
    ) -> Dict[str, Any]:
        """Execute the exit decision on the position.

        NOTE: This modifies the Position object directly for SL/TP changes.
        For close/partial, the caller (multi_strategy_main) must handle
        the actual exchange order.
        """
        if decision.exit_action == "hold":
            return {"applied": True, "action": "hold", "details": "No change"}

        if decision.exit_action == "tighten_sl":
            old_sl = position.sl
            position.sl = round_price(position.symbol, decision.new_sl)
            logger.info(
                f"[EXIT-ENGINE] {position.symbol} SL tightened: "
                f"{old_sl} -> {position.sl} (reason: {decision.reason})"
            )
            return {
                "applied": True,
                "action": "tighten_sl",
                "details": f"SL {old_sl} -> {position.sl}",
                "old_sl": old_sl,
                "new_sl": position.sl,
            }

        if decision.exit_action == "widen_tp":
            old_tp = position.tp2
            position.tp2 = round_price(position.symbol, decision.new_tp)
            logger.info(
                f"[EXIT-ENGINE] {position.symbol} TP2 widened: "
                f"{old_tp} -> {position.tp2} (reason: {decision.reason})"
            )
            return {
                "applied": True,
                "action": "widen_tp",
                "details": f"TP2 {old_tp} -> {position.tp2}",
                "old_tp": old_tp,
                "new_tp": position.tp2,
            }

        if decision.exit_action == "close":
            logger.info(
                f"[EXIT-ENGINE] {position.symbol} EARLY CLOSE recommended "
                f"(conf={decision.exit_confidence:.2f}, reason: {decision.reason})"
            )
            return {
                "applied": True,
                "action": "close",
                "details": f"Early close (conf={decision.exit_confidence:.2f})",
                "close_price": current_price,
            }

        if decision.exit_action == "partial":
            logger.info(
                f"[EXIT-ENGINE] {position.symbol} PARTIAL CLOSE recommended "
                f"{decision.partial_pct:.0%} (conf={decision.exit_confidence:.2f})"
            )
            return {
                "applied": True,
                "action": "partial",
                "details": f"Partial {decision.partial_pct:.0%}",
                "partial_pct": decision.partial_pct,
                "close_price": current_price,
            }

        return {"applied": False, "action": "unknown", "details": decision.exit_action}

    def _log_decision(
        self,
        decision: ExitDecision,
        position: Position,
        applied: bool,
        details: str,
    ):
        """Log exit decision to exit_decisions.jsonl."""
        try:
            import uuid as _uuid
            entry = {
                "decision_id": _uuid.uuid4().hex,
                "ts": datetime.now(timezone.utc).isoformat(),
                "symbol": decision.symbol,
                "exit_action": decision.exit_action,
                "exit_confidence": decision.exit_confidence,
                "applied": applied,
                "details": details,
                "reason": decision.reason,
                "position_side": position.side,
                "position_state": position.state,
                "position_entry": position.entry,
                "position_sl": position.sl,
                "position_tp2": position.tp2,
                "new_sl": decision.new_sl,
                "new_tp": decision.new_tp,
            }
            with open(_EXIT_LOG_FILE, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.debug(f"Failed to log exit decision: {e}")
