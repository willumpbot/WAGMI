"""
Continuous Backtesting Engine: Periodic self-evaluation that feeds back into live trading.

Instead of backtesting once and deploying, this engine:
1. Runs rolling mini-backtests on recent data (last N hours/days)
2. Evaluates each strategy's recent predictive accuracy
3. Compares current parameters against what WOULD have been optimal
4. Produces parameter adjustment suggestions

The key insight: the system continuously validates itself against recent reality.

Schedule:
  - Quick backtest (4h window): every 30 minutes
  - Medium backtest (24h window): every 2 hours
  - Deep backtest (7d window): every 12 hours
  - All results feed into the FeedbackAggregator
"""

import json
import logging
import os
import time
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

logger = logging.getLogger("bot.feedback.continuous_backtest")


@dataclass
class BacktestResult:
    """Result of a single mini-backtest run."""
    window_hours: int
    timestamp: float
    total_signals: int = 0
    signals_that_would_win: int = 0
    signals_that_would_lose: int = 0
    optimal_floor: float = 65.0
    optimal_leverage_cap: float = 25.0
    strategy_accuracy: Dict[str, float] = field(default_factory=dict)
    regime_performance: Dict[str, float] = field(default_factory=dict)
    symbol_performance: Dict[str, float] = field(default_factory=dict)
    confidence_calibration: float = 0.0  # predicted - actual
    total_pnl_simulated: float = 0.0
    win_rate: float = 0.0
    best_confidence_bin: str = ""
    worst_confidence_bin: str = ""


@dataclass
class ParameterSuggestion:
    """A suggested parameter change from backtest analysis."""
    parameter: str
    current_value: float
    suggested_value: float
    confidence_in_suggestion: float  # 0-1, how sure we are
    evidence: str
    source: str  # which backtest window suggested this


class ContinuousBacktester:
    """
    Runs periodic mini-backtests and produces parameter adjustment suggestions.

    Uses recent market data + signal history to validate current trading parameters
    against what would have been optimal in the recent window.
    """

    def __init__(self, data_dir: str = "data/feedback"):
        self.data_dir = data_dir
        self._state_file = os.path.join(data_dir, "backtest_state.json")
        os.makedirs(data_dir, exist_ok=True)

        # Recent backtest results
        self.results: Dict[str, List[BacktestResult]] = {
            "quick": [],    # 4h windows
            "medium": [],   # 24h windows
            "deep": [],     # 7d windows
        }

        # Last run timestamps
        self.last_run: Dict[str, float] = {
            "quick": 0,
            "medium": 0,
            "deep": 0,
        }

        # Run intervals (seconds)
        self.intervals: Dict[str, int] = {
            "quick": 1800,    # 30 minutes
            "medium": 7200,   # 2 hours
            "deep": 43200,    # 12 hours
        }

        # Window sizes (hours)
        self.windows: Dict[str, int] = {
            "quick": 4,
            "medium": 24,
            "deep": 168,  # 7 days
        }

        # Accumulated suggestions
        self.suggestions: List[ParameterSuggestion] = []

        # Signal/outcome history for backtesting (fed by main loop)
        self._signal_history: List[Dict] = []
        self._outcome_history: List[Dict] = []

        self._lock = threading.Lock()
        self._load_state()

    def record_signal(
        self,
        symbol: str,
        side: str,
        confidence: float,
        strategy: str,
        entry: float,
        sl: float,
        tp1: float,
        regime: str = "",
        num_agree: int = 1,
        leverage: float = 1.0,
    ):
        """Record a signal for later backtest evaluation."""
        with self._lock:
            self._signal_history.append({
                "ts": time.time(),
                "symbol": symbol,
                "side": side,
                "confidence": confidence,
                "strategy": strategy,
                "entry": entry,
                "sl": sl,
                "tp1": tp1,
                "regime": regime,
                "num_agree": num_agree,
                "leverage": leverage,
            })
            # Keep last 2000 signals
            if len(self._signal_history) > 2000:
                self._signal_history = self._signal_history[-2000:]

    def record_outcome(
        self,
        symbol: str,
        win: bool,
        pnl: float,
        confidence_at_entry: float,
        strategy: str,
        regime: str = "",
        hold_time_s: float = 0,
        exit_action: str = "",
        leverage: float = 1.0,
    ):
        """Record a trade outcome for backtest validation."""
        with self._lock:
            self._outcome_history.append({
                "ts": time.time(),
                "symbol": symbol,
                "win": win,
                "pnl": pnl,
                "confidence": confidence_at_entry,
                "strategy": strategy,
                "regime": regime,
                "hold_time_s": hold_time_s,
                "exit_action": exit_action,
                "leverage": leverage,
            })
            if len(self._outcome_history) > 2000:
                self._outcome_history = self._outcome_history[-2000:]

    def tick(self) -> Optional[List[ParameterSuggestion]]:
        """Called from main loop. Runs any due backtests and returns suggestions."""
        now = time.time()
        new_suggestions = []

        for level in ("quick", "medium", "deep"):
            if now - self.last_run[level] >= self.intervals[level]:
                try:
                    result = self._run_backtest(level)
                    if result:
                        suggestions = self._analyze_result(result, level)
                        new_suggestions.extend(suggestions)
                        self.last_run[level] = now
                except Exception as e:
                    logger.warning(f"[BACKTEST] {level} backtest failed: {e}")

        if new_suggestions:
            self.suggestions = new_suggestions
            self._save_state()

        return new_suggestions if new_suggestions else None

    def _run_backtest(self, level: str) -> Optional[BacktestResult]:
        """Run a mini-backtest on the specified window."""
        window_hours = self.windows[level]
        cutoff = time.time() - window_hours * 3600

        with self._lock:
            window_signals = [s for s in self._signal_history if s["ts"] >= cutoff]
            window_outcomes = [o for o in self._outcome_history if o["ts"] >= cutoff]

        if len(window_outcomes) < 3:
            return None  # Not enough data

        result = BacktestResult(
            window_hours=window_hours,
            timestamp=time.time(),
            total_signals=len(window_signals),
        )

        # Compute win/loss from outcomes
        wins = [o for o in window_outcomes if o["win"]]
        losses = [o for o in window_outcomes if not o["win"]]
        result.signals_that_would_win = len(wins)
        result.signals_that_would_lose = len(losses)
        result.win_rate = len(wins) / len(window_outcomes) if window_outcomes else 0
        result.total_pnl_simulated = sum(o["pnl"] for o in window_outcomes)

        # Strategy accuracy
        by_strategy = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
        for o in window_outcomes:
            s = by_strategy[o["strategy"]]
            s["total"] += 1
            if o["win"]:
                s["wins"] += 1
            s["pnl"] += o["pnl"]

        result.strategy_accuracy = {
            name: stats["wins"] / stats["total"] if stats["total"] > 0 else 0
            for name, stats in by_strategy.items()
        }

        # Regime performance
        by_regime = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
        for o in window_outcomes:
            r = by_regime[o.get("regime", "unknown")]
            r["total"] += 1
            if o["win"]:
                r["wins"] += 1
            r["pnl"] += o["pnl"]

        result.regime_performance = {
            name: stats["pnl"] / stats["total"] if stats["total"] > 0 else 0
            for name, stats in by_regime.items()
        }

        # Symbol performance
        by_symbol = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
        for o in window_outcomes:
            s = by_symbol[o["symbol"]]
            s["total"] += 1
            if o["win"]:
                s["wins"] += 1
            s["pnl"] += o["pnl"]

        result.symbol_performance = {
            name: stats["pnl"] / stats["total"] if stats["total"] > 0 else 0
            for name, stats in by_symbol.items()
        }

        # Confidence calibration: how well does confidence predict wins?
        if window_outcomes:
            predicted = sum(o["confidence"] / 100.0 for o in window_outcomes) / len(window_outcomes)
            actual = len(wins) / len(window_outcomes)
            result.confidence_calibration = predicted - actual

        # Find optimal confidence floor from this window
        result.optimal_floor = self._find_optimal_floor(window_outcomes)

        # Find optimal leverage cap
        result.optimal_leverage_cap = self._find_optimal_leverage_cap(window_outcomes)

        # Confidence bin analysis
        bins = self._bin_by_confidence(window_outcomes)
        if bins:
            best = max(bins.items(), key=lambda x: x[1]["ev"])
            worst = min(bins.items(), key=lambda x: x[1]["ev"])
            result.best_confidence_bin = best[0]
            result.worst_confidence_bin = worst[0]

        # Store result
        self.results[level].append(result)
        if len(self.results[level]) > 50:
            self.results[level] = self.results[level][-50:]

        logger.info(
            f"[BACKTEST] {level} ({window_hours}h): "
            f"{len(window_outcomes)} trades, WR={result.win_rate:.0%}, "
            f"PnL=${result.total_pnl_simulated:+.2f}, "
            f"optimal_floor={result.optimal_floor:.0f}%"
        )

        # Deep cycle: run walk-forward validation for OOS generalization check
        if level == "deep" and len(window_outcomes) >= 10:
            try:
                from validation.walk_forward import run_rolling_walk_forward, avg_wf_ratio
                wf_trades = [
                    {"pnl": o["pnl"], "timestamp": o["ts"]}
                    for o in window_outcomes
                ]
                wf_results = run_rolling_walk_forward(wf_trades)
                # Don't fire CRITICAL on empty walk-forward results — that's a
                # cold-start false positive (empty list defaults to 0.0 and
                # trips the < 0.3 threshold). Only alert when we have real data.
                if not wf_results:
                    logger.debug(
                        "[BACKTEST] Walk-forward skipped — insufficient completed cycles"
                    )
                else:
                    wf_ratio = avg_wf_ratio(wf_results)
                    self._last_wf_ratio = wf_ratio
                    if wf_ratio < 0.3:
                        logger.critical(
                            f"[BACKTEST] Walk-forward ratio CRITICAL: {wf_ratio:.3f} — "
                            f"possible overfitting detected"
                        )
                    elif wf_ratio < 0.5:
                        logger.warning(
                            f"[BACKTEST] Walk-forward ratio degraded: {wf_ratio:.3f}"
                        )
                    else:
                        logger.info(f"[BACKTEST] Walk-forward ratio: {wf_ratio:.3f}")
            except Exception as e:
                logger.debug(f"[BACKTEST] Walk-forward check error: {e}")

        return result

    def _find_optimal_floor(self, outcomes: List[Dict]) -> float:
        """Find the confidence floor that maximizes EV in this window."""
        if not outcomes:
            return 65.0

        best_floor = 65.0
        best_ev = -999

        for floor in range(50, 85, 5):
            above = [o for o in outcomes if o["confidence"] >= floor]
            if len(above) < 3:
                continue
            ev = sum(o["pnl"] for o in above) / len(above)
            if ev > best_ev:
                best_ev = ev
                best_floor = float(floor)

        return best_floor

    def _find_optimal_leverage_cap(self, outcomes: List[Dict]) -> float:
        """Find the leverage cap that maximizes risk-adjusted returns."""
        if not outcomes:
            return 25.0

        leveraged = [o for o in outcomes if o.get("leverage", 1) > 1]
        if len(leveraged) < 3:
            return 25.0

        best_cap = 25.0
        best_sharpe = -999

        for cap in [5, 10, 15, 20, 25]:
            capped = [o for o in outcomes if o.get("leverage", 1) <= cap]
            if len(capped) < 3:
                continue
            pnls = [o["pnl"] for o in capped]
            avg = sum(pnls) / len(pnls)
            if len(pnls) > 1:
                variance = sum((p - avg) ** 2 for p in pnls) / (len(pnls) - 1)
                std = variance ** 0.5
                sharpe = avg / std if std > 0 else 0
            else:
                sharpe = avg
            if sharpe > best_sharpe:
                best_sharpe = sharpe
                best_cap = float(cap)

        return best_cap

    def _bin_by_confidence(self, outcomes: List[Dict]) -> Dict[str, Dict]:
        """Bin outcomes by confidence level and compute EV per bin."""
        bins = {}
        for low in range(50, 100, 10):
            high = low + 10
            label = f"{low}-{high}%"
            in_bin = [o for o in outcomes if low <= o["confidence"] < high]
            if in_bin:
                wins = sum(1 for o in in_bin if o["win"])
                total_pnl = sum(o["pnl"] for o in in_bin)
                bins[label] = {
                    "count": len(in_bin),
                    "win_rate": wins / len(in_bin),
                    "ev": total_pnl / len(in_bin),
                    "total_pnl": total_pnl,
                }
        return bins

    def _analyze_result(
        self, result: BacktestResult, level: str
    ) -> List[ParameterSuggestion]:
        """Analyze a backtest result and produce parameter suggestions."""
        suggestions = []

        # Weight by level: deep results are more trustworthy
        # Trust weights: quick backtests were too conservative at 0.3 —
        # suggestions never reached the tuner's 0.7 high-confidence bypass.
        # Raised quick to 0.5 so a 60% WR quick backtest produces 0.30 confidence,
        # which the gradual-move tuner can act on.
        trust_weight = {"quick": 0.5, "medium": 0.7, "deep": 1.0}[level]

        # 1. Confidence floor suggestion
        if result.optimal_floor != 65.0 and result.total_signals >= 5:
            suggestions.append(ParameterSuggestion(
                parameter="confidence_floor",
                current_value=65.0,
                suggested_value=result.optimal_floor,
                confidence_in_suggestion=min(0.9, trust_weight * result.win_rate),
                evidence=(
                    f"{level} backtest ({result.window_hours}h): "
                    f"optimal floor={result.optimal_floor:.0f}%, "
                    f"WR={result.win_rate:.0%}, "
                    f"PnL=${result.total_pnl_simulated:+.2f}"
                ),
                source=level,
            ))

        # 2. Leverage cap suggestion
        if result.optimal_leverage_cap < 25.0:
            suggestions.append(ParameterSuggestion(
                parameter="max_leverage",
                current_value=25.0,
                suggested_value=result.optimal_leverage_cap,
                confidence_in_suggestion=trust_weight * 0.7,
                evidence=(
                    f"{level} backtest: optimal leverage cap={result.optimal_leverage_cap:.0f}x "
                    f"(risk-adjusted returns improve)"
                ),
                source=level,
            ))

        # 3. Per-strategy weight suggestions
        for strategy, accuracy in result.strategy_accuracy.items():
            if accuracy < 0.35:
                suggestions.append(ParameterSuggestion(
                    parameter=f"strategy_weight_{strategy}",
                    current_value=1.0,
                    suggested_value=max(0.3, accuracy),
                    confidence_in_suggestion=trust_weight * 0.5,
                    evidence=(
                        f"{strategy} accuracy={accuracy:.0%} in {level} window — "
                        f"consider reducing weight"
                    ),
                    source=level,
                ))
            elif accuracy > 0.65:
                suggestions.append(ParameterSuggestion(
                    parameter=f"strategy_weight_{strategy}",
                    current_value=1.0,
                    suggested_value=min(1.5, 0.5 + accuracy),
                    confidence_in_suggestion=trust_weight * 0.5,
                    evidence=(
                        f"{strategy} accuracy={accuracy:.0%} in {level} window — "
                        f"consider increasing weight"
                    ),
                    source=level,
                ))

        # 4. Calibration suggestion
        if abs(result.confidence_calibration) > 0.1:
            direction = "overconfident" if result.confidence_calibration > 0 else "underconfident"
            suggestions.append(ParameterSuggestion(
                parameter="calibration_offset",
                current_value=0.0,
                suggested_value=-result.confidence_calibration * 50,
                confidence_in_suggestion=trust_weight * 0.6,
                evidence=(
                    f"System is {direction} by {abs(result.confidence_calibration):.0%} — "
                    f"adjust ML weight or floor"
                ),
                source=level,
            ))

        return suggestions

    def get_aggregated_suggestions(self) -> Dict[str, ParameterSuggestion]:
        """Aggregate suggestions across all backtest levels.

        When multiple levels suggest the same parameter change,
        weight by their trust level and agreement.
        """
        by_param: Dict[str, List[ParameterSuggestion]] = defaultdict(list)
        for s in self.suggestions:
            by_param[s.parameter].append(s)

        aggregated = {}
        for param, sug_list in by_param.items():
            if len(sug_list) == 1:
                aggregated[param] = sug_list[0]
            else:
                # Weighted average of suggested values
                total_weight = sum(s.confidence_in_suggestion for s in sug_list)
                if total_weight > 0:
                    avg_value = sum(
                        s.suggested_value * s.confidence_in_suggestion
                        for s in sug_list
                    ) / total_weight
                    # Agreement bonus: if all levels agree, higher confidence
                    agreement = len(sug_list) / 3.0
                    avg_conf = min(
                        0.95,
                        (sum(s.confidence_in_suggestion for s in sug_list) / len(sug_list))
                        * (1 + agreement * 0.2)
                    )
                    aggregated[param] = ParameterSuggestion(
                        parameter=param,
                        current_value=sug_list[0].current_value,
                        suggested_value=avg_value,
                        confidence_in_suggestion=avg_conf,
                        evidence=f"Agreed by {len(sug_list)} backtest levels",
                        source="aggregated",
                    )

        return aggregated

    def get_report(self) -> Dict[str, Any]:
        """Get human-readable report of backtest state."""
        report = {}
        for level in ("quick", "medium", "deep"):
            results = self.results[level]
            if results:
                latest = results[-1]
                report[level] = {
                    "last_run": latest.timestamp,
                    "window_hours": latest.window_hours,
                    "total_signals": latest.total_signals,
                    "win_rate": round(latest.win_rate, 3),
                    "total_pnl": round(latest.total_pnl_simulated, 2),
                    "optimal_floor": latest.optimal_floor,
                    "optimal_leverage_cap": latest.optimal_leverage_cap,
                    "strategy_accuracy": {
                        k: round(v, 3) for k, v in latest.strategy_accuracy.items()
                    },
                    "calibration": round(latest.confidence_calibration, 3),
                }

        # Walk-forward ratio from last deep cycle
        if hasattr(self, '_last_wf_ratio'):
            report["walk_forward_ratio"] = round(self._last_wf_ratio, 3)

        suggestions = self.get_aggregated_suggestions()
        if suggestions:
            report["suggestions"] = {
                param: {
                    "current": s.current_value,
                    "suggested": round(s.suggested_value, 2),
                    "confidence": round(s.confidence_in_suggestion, 2),
                    "evidence": s.evidence,
                }
                for param, s in suggestions.items()
            }

        return report

    def _save_state(self):
        try:
            state = {
                "last_run": self.last_run,
                "results": {
                    level: [
                        {
                            "window_hours": r.window_hours,
                            "timestamp": r.timestamp,
                            "total_signals": r.total_signals,
                            "win_rate": r.win_rate,
                            "total_pnl": r.total_pnl_simulated,
                            "optimal_floor": r.optimal_floor,
                            "strategy_accuracy": r.strategy_accuracy,
                            "calibration": r.confidence_calibration,
                        }
                        for r in results[-10:]
                    ]
                    for level, results in self.results.items()
                },
                # Persist signal/outcome history so it survives restarts
                "signal_history": self._signal_history[-2000:],
                "outcome_history": self._outcome_history[-2000:],
            }
            os.makedirs(os.path.dirname(self._state_file), exist_ok=True)
            with open(self._state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save backtest state: {e}")

    def _load_state(self):
        if not os.path.exists(self._state_file):
            return
        try:
            with open(self._state_file) as f:
                state = json.load(f)
            self.last_run = state.get("last_run", self.last_run)
            # Restore signal/outcome history from disk
            self._signal_history = state.get("signal_history", [])[-2000:]
            self._outcome_history = state.get("outcome_history", [])[-2000:]
            if self._signal_history or self._outcome_history:
                logger.info(
                    f"[CB] Restored {len(self._signal_history)} signals, "
                    f"{len(self._outcome_history)} outcomes from disk"
                )
        except Exception as e:
            logger.warning(f"Failed to load backtest state: {e}")
