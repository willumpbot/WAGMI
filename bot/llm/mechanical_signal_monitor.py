"""
TIER 4.1a: Mechanical Signal Monitoring

Creates a "shadow log" of every signal the mechanical system generates.

Why: To understand what the mechanical bot sees and how it thinks.

We monitor:
1. Raw signal generation (before ensemble)
2. Ensemble voting
3. Risk gate filtering
4. Execution decisions
5. Actual outcomes

This enables us to:
- Understand the mechanical system's edge
- Identify patterns it relies on
- Find gaps (signals it misses)
- Learn from its successes and failures
- Synthesize complementary LLM signals

Data model: Signal lifecycle from generation to outcome
"""

import json
import logging
import os
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field
from datetime import datetime
import time

logger = logging.getLogger("bot.llm.mechanical_signal_monitor")


@dataclass
class StrategyVote:
    """One strategy's signal for a symbol."""
    strategy_name: str
    side: str  # BUY or SELL
    confidence: float  # 0-100
    entry: float
    sl: float
    tp1: float
    tp2: float
    atr: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EnsembleResult:
    """Result of ensemble voting on a symbol."""
    symbol: str
    timestamp: float

    # Input
    votes: List[StrategyVote] = field(default_factory=list)
    num_agree: int = 0

    # Ensemble decision
    passed_ensemble: bool = False
    final_side: Optional[str] = None
    final_confidence: float = 0.0
    ensemble_reasoning: str = ""

    # Voting details
    buy_votes: int = 0
    sell_votes: int = 0
    veto_applied: bool = False
    min_votes_requirement: int = 2


@dataclass
class RiskGateResult:
    """Result of passing through risk gates."""
    symbol: str
    timestamp: float
    ensemble_signal: Optional[EnsembleResult] = None

    # Gate results
    gate_validity: bool = True
    gate_validity_reason: str = ""

    gate_circuit_breaker: bool = True
    gate_cb_reason: str = ""

    gate_position_limits: bool = True
    gate_pos_reason: str = ""

    gate_leverage: bool = True
    gate_lev_reason: str = ""

    gate_liquidation: bool = True
    gate_liq_reason: str = ""

    gate_portfolio_risk: bool = True
    gate_port_reason: str = ""

    # Final result
    passed_all_gates: bool = False
    rejection_reason: Optional[str] = None


@dataclass
class SignalLifecycle:
    """Complete lifecycle of a signal."""
    signal_id: str
    symbol: str
    timestamp: float

    # Generation phase
    ensemble_result: Optional[EnsembleResult] = None

    # Risk gating phase
    risk_result: Optional[RiskGateResult] = None

    # Execution phase
    execution_attempted: bool = False
    execution_timestamp: Optional[float] = None
    actual_entry: Optional[float] = None
    actual_exit: Optional[float] = None

    # Outcome
    pnl: Optional[float] = None
    outcome: Optional[str] = None  # WIN, LOSS, OPEN

    # Analysis
    notes: str = ""


class MechanicalSignalMonitor:
    """
    Monitors the mechanical system's signal generation and decision-making.
    """

    def __init__(self, output_dir: str = "data/llm"):
        self.output_dir = output_dir
        self.lifecycle_file = os.path.join(output_dir, "mechanical_signals.jsonl")
        self.ensemble_file = os.path.join(output_dir, "mechanical_ensemble.jsonl")
        self.risk_file = os.path.join(output_dir, "mechanical_risk_gates.jsonl")

        os.makedirs(output_dir, exist_ok=True)

        # In-memory cache
        self.lifecycles: Dict[str, SignalLifecycle] = {}
        self.ensemble_log: List[EnsembleResult] = []
        self.risk_log: List[RiskGateResult] = []

        self.stats = {
            "total_signals_generated": 0,
            "signals_passed_ensemble": 0,
            "signals_passed_risk_gates": 0,
            "signals_executed": 0,
            "signal_outcomes": {"wins": 0, "losses": 0, "open": 0},
        }

    def log_ensemble_vote(
        self,
        symbol: str,
        votes: List[Dict],  # [{"strategy": "regime_trend", "side": "BUY", "confidence": 75, ...}]
        num_agree: int,
        passed_ensemble: bool,
        final_side: Optional[str],
        final_confidence: float,
        ensemble_reasoning: str = "",
        min_votes_requirement: int = 2,
    ) -> EnsembleResult:
        """
        Log ensemble voting for a symbol.
        """
        self.stats["total_signals_generated"] += 1

        strategy_votes = [
            StrategyVote(
                strategy_name=v["strategy"],
                side=v.get("side", ""),
                confidence=v.get("confidence", 0),
                entry=v.get("entry", 0),
                sl=v.get("sl", 0),
                tp1=v.get("tp1", 0),
                tp2=v.get("tp2", 0),
                atr=v.get("atr", 0),
                metadata=v.get("metadata", {}),
            )
            for v in votes
        ]

        ensemble = EnsembleResult(
            symbol=symbol,
            timestamp=time.time(),
            votes=strategy_votes,
            num_agree=num_agree,
            passed_ensemble=passed_ensemble,
            final_side=final_side,
            final_confidence=final_confidence,
            ensemble_reasoning=ensemble_reasoning,
            buy_votes=sum(1 for v in strategy_votes if v.side == "BUY"),
            sell_votes=sum(1 for v in strategy_votes if v.side == "SELL"),
            min_votes_requirement=min_votes_requirement,
        )

        self.ensemble_log.append(ensemble)
        if len(self.ensemble_log) > 1000:
            self.ensemble_log = self.ensemble_log[-1000:]

        if passed_ensemble:
            self.stats["signals_passed_ensemble"] += 1

        # Start lifecycle for this signal
        signal_id = f"{symbol}_{int(time.time() * 1000) % 100000}"
        if signal_id not in self.lifecycles:
            self.lifecycles[signal_id] = SignalLifecycle(
                signal_id=signal_id,
                symbol=symbol,
                timestamp=time.time(),
            )
        self.lifecycles[signal_id].ensemble_result = ensemble

        # Persist
        self._save_ensemble(ensemble)

        return ensemble

    def log_risk_gates(
        self,
        symbol: str,
        ensemble_result: EnsembleResult,
        gate_results: Dict[str, Tuple[bool, str]],  # {gate_name: (passed, reason)}
        passed_all_gates: bool,
        rejection_reason: Optional[str] = None,
    ) -> RiskGateResult:
        """
        Log risk gate evaluation for a signal.
        """
        risk = RiskGateResult(
            symbol=symbol,
            timestamp=time.time(),
            ensemble_signal=ensemble_result,

            gate_validity=gate_results.get("validity", (True, ""))[0],
            gate_validity_reason=gate_results.get("validity", (True, ""))[1],

            gate_circuit_breaker=gate_results.get("circuit_breaker", (True, ""))[0],
            gate_cb_reason=gate_results.get("circuit_breaker", (True, ""))[1],

            gate_position_limits=gate_results.get("position_limits", (True, ""))[0],
            gate_pos_reason=gate_results.get("position_limits", (True, ""))[1],

            gate_leverage=gate_results.get("leverage", (True, ""))[0],
            gate_lev_reason=gate_results.get("leverage", (True, ""))[1],

            gate_liquidation=gate_results.get("liquidation", (True, ""))[0],
            gate_liq_reason=gate_results.get("liquidation", (True, ""))[1],

            gate_portfolio_risk=gate_results.get("portfolio_risk", (True, ""))[0],
            gate_port_reason=gate_results.get("portfolio_risk", (True, ""))[1],

            passed_all_gates=passed_all_gates,
            rejection_reason=rejection_reason,
        )

        self.risk_log.append(risk)
        if len(self.risk_log) > 1000:
            self.risk_log = self.risk_log[-1000:]

        if passed_all_gates:
            self.stats["signals_passed_risk_gates"] += 1

        # Update lifecycle
        signal_id = f"{symbol}_{int(risk.timestamp * 1000) % 100000}"
        if signal_id not in self.lifecycles:
            self.lifecycles[signal_id] = SignalLifecycle(
                signal_id=signal_id,
                symbol=symbol,
                timestamp=time.time(),
            )
        self.lifecycles[signal_id].risk_result = risk

        # Persist
        self._save_risk(risk)

        return risk

    def log_execution(
        self,
        signal_id: str,
        symbol: str,
        actual_entry: float,
        actual_exit: float,
        pnl: float,
    ) -> None:
        """Log actual execution of a signal."""
        self.stats["signals_executed"] += 1

        if signal_id not in self.lifecycles:
            self.lifecycles[signal_id] = SignalLifecycle(
                signal_id=signal_id,
                symbol=symbol,
                timestamp=time.time(),
            )

        lifecycle = self.lifecycles[signal_id]
        lifecycle.execution_attempted = True
        lifecycle.execution_timestamp = time.time()
        lifecycle.actual_entry = actual_entry
        lifecycle.actual_exit = actual_exit
        lifecycle.pnl = pnl

        # Determine outcome
        if pnl > 0:
            lifecycle.outcome = "WIN"
            self.stats["signal_outcomes"]["wins"] += 1
        elif pnl < 0:
            lifecycle.outcome = "LOSS"
            self.stats["signal_outcomes"]["losses"] += 1
        else:
            lifecycle.outcome = "BREAK_EVEN"

        # Persist
        self._save_lifecycle(lifecycle)

    def get_signal_report(self) -> Dict[str, Any]:
        """Get comprehensive signal monitoring report."""
        if not self.ensemble_log:
            return {"status": "no_data"}

        recent_ensemble = self.ensemble_log[-100:]
        recent_risk = self.risk_log[-100:]

        # Ensemble stats
        ensemble_pass_rate = sum(1 for e in recent_ensemble if e.passed_ensemble) / len(recent_ensemble) if recent_ensemble else 0

        # Risk gate stats
        risk_pass_rate = sum(1 for r in recent_risk if r.passed_all_gates) / len(recent_risk) if recent_risk else 0

        # Gate breakdown
        gate_failures = {
            "validity": sum(1 for r in recent_risk if not r.gate_validity),
            "circuit_breaker": sum(1 for r in recent_risk if not r.gate_circuit_breaker),
            "position_limits": sum(1 for r in recent_risk if not r.gate_position_limits),
            "leverage": sum(1 for r in recent_risk if not r.gate_leverage),
            "liquidation": sum(1 for r in recent_risk if not r.gate_liquidation),
            "portfolio_risk": sum(1 for r in recent_risk if not r.gate_portfolio_risk),
        }

        # Execution stats
        total_outcomes = sum(self.stats["signal_outcomes"].values())
        win_rate = self.stats["signal_outcomes"]["wins"] / total_outcomes if total_outcomes > 0 else 0

        return {
            "signals_generated": self.stats["total_signals_generated"],
            "ensemble_pass_rate": f"{ensemble_pass_rate:.0%}",
            "risk_gate_pass_rate": f"{risk_pass_rate:.0%}",
            "execution_rate": f"{self.stats['signals_executed'] / max(1, self.stats['signals_passed_risk_gates']):.0%}",
            "win_rate": f"{win_rate:.0%}",
            "gate_failure_breakdown": gate_failures,
            "outcomes": {
                "wins": self.stats["signal_outcomes"]["wins"],
                "losses": self.stats["signal_outcomes"]["losses"],
                "open": self.stats["signal_outcomes"]["open"],
            },
        }

    def get_strategy_performance(self) -> Dict[str, Dict]:
        """
        Analyze each strategy's voting performance.

        Returns performance metrics per strategy.
        """
        by_strategy = {}

        for ensemble in self.ensemble_log[-500:]:
            for vote in ensemble.votes:
                strategy = vote.strategy_name
                if strategy not in by_strategy:
                    by_strategy[strategy] = {
                        "votes": 0,
                        "votes_in_winning_ensemble": 0,
                        "votes_in_passing_gates": 0,
                    }

                by_strategy[strategy]["votes"] += 1

                if ensemble.passed_ensemble:
                    by_strategy[strategy]["votes_in_winning_ensemble"] += 1

        # Convert to percentages
        for strategy, stats in by_strategy.items():
            total_votes = stats["votes"]
            if total_votes > 0:
                stats["ensemble_participation"] = f"{stats['votes_in_winning_ensemble'] / total_votes:.0%}"
            else:
                stats["ensemble_participation"] = "0%"

        return by_strategy

    def _save_ensemble(self, ensemble: EnsembleResult) -> None:
        """Persist ensemble vote to disk."""
        try:
            with open(self.ensemble_file, "a") as f:
                data = {
                    "symbol": ensemble.symbol,
                    "timestamp": ensemble.timestamp,
                    "num_strategies": len(ensemble.votes),
                    "buy_votes": ensemble.buy_votes,
                    "sell_votes": ensemble.sell_votes,
                    "passed_ensemble": ensemble.passed_ensemble,
                    "final_side": ensemble.final_side,
                    "final_confidence": ensemble.final_confidence,
                    "num_agree": ensemble.num_agree,
                }
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to save ensemble vote: {e}")

    def _save_risk(self, risk: RiskGateResult) -> None:
        """Persist risk gate result to disk."""
        try:
            with open(self.risk_file, "a") as f:
                data = {
                    "symbol": risk.symbol,
                    "timestamp": risk.timestamp,
                    "gate_validity": risk.gate_validity,
                    "gate_circuit_breaker": risk.gate_circuit_breaker,
                    "gate_position_limits": risk.gate_position_limits,
                    "gate_leverage": risk.gate_leverage,
                    "gate_liquidation": risk.gate_liquidation,
                    "gate_portfolio_risk": risk.gate_portfolio_risk,
                    "passed_all_gates": risk.passed_all_gates,
                }
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to save risk gate result: {e}")

    def _save_lifecycle(self, lifecycle: SignalLifecycle) -> None:
        """Persist full signal lifecycle to disk."""
        try:
            with open(self.lifecycle_file, "a") as f:
                data = {
                    "signal_id": lifecycle.signal_id,
                    "symbol": lifecycle.symbol,
                    "timestamp": lifecycle.timestamp,
                    "execution_attempted": lifecycle.execution_attempted,
                    "pnl": lifecycle.pnl,
                    "outcome": lifecycle.outcome,
                }
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to save lifecycle: {e}")


# Global monitor
_global_monitor: Optional[MechanicalSignalMonitor] = None


def get_mechanical_signal_monitor() -> MechanicalSignalMonitor:
    """Get or create global monitor."""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = MechanicalSignalMonitor()
    return _global_monitor
