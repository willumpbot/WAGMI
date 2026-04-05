"""
Pipeline Telemetry: Captures every gate decision and multiplier value
as a signal flows through the pipeline. This structured data feeds
the LLM agent network so agents can reason about WHY signals pass or die.
"""

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone


@dataclass
class GateDecision:
    """One gate's decision on a signal."""
    gate_name: str
    passed: bool
    value: float  # the value that was checked
    threshold: float  # the threshold it was checked against
    reason: str  # human-readable explanation


@dataclass
class MultiplierStep:
    """One step in the sizing multiplier chain."""
    name: str
    value: float  # the multiplier applied at this step
    cumulative: float  # running product after this step
    source: str  # where this multiplier comes from


@dataclass
class SignalJourney:
    """Complete record of one signal's journey through the pipeline."""
    symbol: str
    side: str
    timestamp: str

    # Strategy layer
    strategies_fired: Dict[str, Dict] = field(default_factory=dict)
    # {strategy_name: {confidence: X, side: Y, fired: True/False}}

    ensemble_result: Optional[Dict] = field(default=None)
    # {confidence: X, side: Y, num_agree: N, strategies: [...]}

    # Gate decisions (in order)
    gates: List[GateDecision] = field(default_factory=list)

    # Multiplier chain (in order)
    multipliers: List[MultiplierStep] = field(default_factory=list)

    # Final outcome
    outcome: str = "pending"  # "traded", "rejected_gate_X", "rejected_sizing"
    final_qty: float = 0.0
    final_notional: float = 0.0
    final_leverage: float = 0.0


class PipelineTelemetry:
    """Thread-safe telemetry collector for signal pipeline decisions."""

    def __init__(self, max_history: int = 100):
        self._current: Dict[str, SignalJourney] = {}  # symbol -> current journey
        self._history: List[SignalJourney] = []
        self._max_history = max_history
        self._lock = threading.Lock()

    def start_journey(self, symbol: str, side: str):
        """Begin tracking a new signal's journey."""
        with self._lock:
            self._current[symbol] = SignalJourney(
                symbol=symbol,
                side=side,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

    def record_strategy(self, symbol: str, strategy_name: str,
                       fired: bool, confidence: float = 0, side: str = ""):
        """Record one strategy's evaluation result."""
        with self._lock:
            j = self._current.get(symbol)
            if j:
                j.strategies_fired[strategy_name] = {
                    "fired": fired, "confidence": confidence, "side": side
                }

    def record_ensemble(self, symbol: str, result: Dict):
        """Record the ensemble's consensus result."""
        with self._lock:
            j = self._current.get(symbol)
            if j:
                j.ensemble_result = result

    def record_gate(self, symbol: str, gate_name: str, passed: bool,
                   value: float = 0, threshold: float = 0, reason: str = ""):
        """Record one gate's decision."""
        with self._lock:
            j = self._current.get(symbol)
            if j:
                j.gates.append(GateDecision(
                    gate_name=gate_name, passed=passed,
                    value=value, threshold=threshold, reason=reason
                ))
                if not passed:
                    j.outcome = f"rejected_{gate_name}"

    def record_multiplier(self, symbol: str, name: str, value: float, source: str = ""):
        """Record one step in the multiplier chain."""
        with self._lock:
            j = self._current.get(symbol)
            if j:
                prev = j.multipliers[-1].cumulative if j.multipliers else 1.0
                j.multipliers.append(MultiplierStep(
                    name=name, value=value,
                    cumulative=round(prev * value, 6), source=source
                ))

    def finish_journey(self, symbol: str, traded: bool,
                      qty: float = 0, notional: float = 0, leverage: float = 0):
        """Complete the signal's journey."""
        with self._lock:
            j = self._current.pop(symbol, None)
            if j:
                if traded:
                    j.outcome = "traded"
                    j.final_qty = qty
                    j.final_notional = notional
                    j.final_leverage = leverage
                self._history.append(j)
                if len(self._history) > self._max_history:
                    self._history.pop(0)

    def get_current(self, symbol: str) -> Optional[SignalJourney]:
        """Get the in-progress journey for a symbol."""
        with self._lock:
            return self._current.get(symbol)

    def get_recent(self, n: int = 10) -> List[SignalJourney]:
        """Get the N most recent completed journeys."""
        with self._lock:
            return list(self._history[-n:])

    def get_rejection_summary(self, last_n: int = 50) -> Dict[str, int]:
        """Count rejections by gate for the last N journeys."""
        with self._lock:
            recent = self._history[-last_n:]
        counts: Dict[str, int] = {}
        for j in recent:
            if j.outcome.startswith("rejected_"):
                gate = j.outcome.replace("rejected_", "")
                counts[gate] = counts.get(gate, 0) + 1
        return counts

    def get_pass_rate(self, last_n: int = 50) -> float:
        """Calculate signal pass rate over last N journeys."""
        with self._lock:
            recent = self._history[-last_n:]
        if not recent:
            return 0.0
        traded = sum(1 for j in recent if j.outcome == "traded")
        return traded / len(recent)

    def format_for_llm(self, symbol: str = None, last_n: int = 5) -> str:
        """Format recent journeys as compact text for LLM context."""
        with self._lock:
            if symbol:
                recent = [j for j in self._history[-20:] if j.symbol == symbol][-last_n:]
            else:
                recent = self._history[-last_n:]

        lines = []
        for j in recent:
            strats = [f"{k}({'O' if v['fired'] else 'X'})"
                     for k, v in j.strategies_fired.items() if v.get('fired')]
            gates_failed = [g.gate_name for g in j.gates if not g.passed]

            if j.outcome == "traded":
                lines.append(f"{j.symbol} {j.side} TRADED qty={j.final_qty} lev={j.final_leverage}x strats=[{','.join(strats)}]")
            else:
                lines.append(f"{j.symbol} {j.side} BLOCKED@{gates_failed[0] if gates_failed else '?'} strats=[{','.join(strats)}]")

        summary = self.get_rejection_summary(last_n=50)
        pass_rate = self.get_pass_rate(last_n=50)
        lines.append(f"Pass rate: {pass_rate:.0%} | Top blocks: {dict(sorted(summary.items(), key=lambda x: -x[1])[:3])}")

        return "\n".join(lines)


# Global singleton
_telemetry = PipelineTelemetry()

def get_telemetry() -> PipelineTelemetry:
    return _telemetry
