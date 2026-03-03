"""
Strategy parameter optimization using grid search or random search.

Systematically tests parameter combinations against historical backtest results
to find optimal settings for each strategy and the ensemble.

Optimizable parameters:
- ATR multipliers for SL/TP (per strategy)
- Confidence floors
- Leverage tier boundaries
- Ensemble weights and veto ratios
- Timeframe weights for trend scoring

Usage:
    optimizer = ParameterOptimizer(backtest_fn)
    result = optimizer.grid_search(param_space, metric="sharpe")
    best_params = result.best_params

    # Or use the backtest bridge:
    from optimization.param_optimizer import create_backtest_fn
    bt_fn = create_backtest_fn(symbols=["BTC","ETH"], days=30)
    optimizer = ParameterOptimizer(bt_fn)
    result = optimizer.grid_search(STRATEGY_PARAM_SPACES, metric="sharpe")
"""

import itertools
import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.optimization.param_optimizer")


@dataclass
class OptimizationResult:
    """Result of a parameter optimization run."""
    best_params: Dict[str, Any]
    best_score: float
    metric: str
    all_results: List[Dict[str, Any]]
    duration_s: float
    total_trials: int


@dataclass
class ParamRange:
    """Define a parameter search space."""
    name: str
    values: List[Any]  # Discrete values to try

    @staticmethod
    def linspace(name: str, start: float, stop: float, steps: int) -> "ParamRange":
        """Create evenly spaced parameter range."""
        if steps <= 1:
            return ParamRange(name, [start])
        step = (stop - start) / (steps - 1)
        values = [round(start + i * step, 6) for i in range(steps)]
        return ParamRange(name, values)

    @staticmethod
    def choices(name: str, *values) -> "ParamRange":
        """Create discrete choice parameter."""
        return ParamRange(name, list(values))


# ── Pre-built Search Spaces ──────────────────────────────────────────

# Common strategy parameter ranges for quick optimization
STRATEGY_PARAM_SPACES = {
    "atr_mult": ParamRange.linspace("atr_mult", 0.8, 2.5, 6),
    "rr1": ParamRange.linspace("rr1", 1.0, 3.0, 6),
    "rr2": ParamRange.linspace("rr2", 2.0, 5.0, 5),
    "confidence_floor": ParamRange.linspace("confidence_floor", 55.0, 80.0, 6),
    "veto_ratio": ParamRange.linspace("veto_ratio", 1.0, 2.0, 5),
    "min_votes": ParamRange.choices("min_votes", 2, 3),
}

TIMEFRAME_WEIGHT_SPACES = {
    "tf_weight_5m": ParamRange.linspace("tf_weight_5m", 0.0, 1.0, 3),
    "tf_weight_1h": ParamRange.linspace("tf_weight_1h", 0.5, 1.5, 3),
    "tf_weight_6h": ParamRange.linspace("tf_weight_6h", 1.0, 2.0, 3),
    "tf_weight_daily": ParamRange.linspace("tf_weight_daily", 1.5, 3.0, 3),
}


class ParameterOptimizer:
    """Optimize strategy parameters via grid or random search.

    The backtest_fn should accept a dict of parameters and return a dict
    with at least {"sharpe": float, "total_pnl": float, "win_rate": float}.
    """

    def __init__(self, backtest_fn: Callable[[Dict[str, Any]], Dict[str, float]]):
        """
        Args:
            backtest_fn: Function(params: dict) -> dict with metric scores.
                         Must be deterministic for grid search to be valid.
        """
        self.backtest_fn = backtest_fn

    def grid_search(
        self,
        param_spaces: Dict[str, ParamRange],
        metric: str = "sharpe",
        max_trials: int = 500,
    ) -> OptimizationResult:
        """Exhaustive grid search over parameter combinations.

        If the total grid exceeds max_trials, falls back to random sampling.
        """
        spaces = list(param_spaces.values())
        names = [s.name for s in spaces]
        value_lists = [s.values for s in spaces]

        total_combos = 1
        for v in value_lists:
            total_combos *= len(v)

        if total_combos > max_trials:
            logger.info(
                f"Grid has {total_combos} combos (> {max_trials}), using random search"
            )
            return self.random_search(param_spaces, metric=metric, n_trials=max_trials)

        logger.info(f"Grid search: {total_combos} combinations for metric={metric}")
        start = time.time()

        all_results = []
        best_score = float("-inf")
        best_params = {}

        for combo in itertools.product(*value_lists):
            params = dict(zip(names, combo))
            try:
                scores = self.backtest_fn(params)
                score = scores.get(metric, float("-inf"))
                result_entry = {"params": params, "scores": scores, "score": score}
                all_results.append(result_entry)

                if score > best_score:
                    best_score = score
                    best_params = params.copy()
            except Exception as e:
                logger.warning(f"Trial failed for {params}: {e}")

        duration = time.time() - start
        logger.info(
            f"Grid search complete: {len(all_results)} trials in {duration:.1f}s, "
            f"best {metric}={best_score:.4f}"
        )

        return OptimizationResult(
            best_params=best_params,
            best_score=best_score,
            metric=metric,
            all_results=sorted(all_results, key=lambda x: x["score"], reverse=True),
            duration_s=duration,
            total_trials=len(all_results),
        )

    def random_search(
        self,
        param_spaces: Dict[str, ParamRange],
        metric: str = "sharpe",
        n_trials: int = 100,
    ) -> OptimizationResult:
        """Random sampling from parameter space."""
        spaces = list(param_spaces.values())
        logger.info(f"Random search: {n_trials} trials for metric={metric}")
        start = time.time()

        all_results = []
        best_score = float("-inf")
        best_params = {}

        for i in range(n_trials):
            params = {s.name: random.choice(s.values) for s in spaces}
            try:
                scores = self.backtest_fn(params)
                score = scores.get(metric, float("-inf"))
                all_results.append({"params": params, "scores": scores, "score": score})

                if score > best_score:
                    best_score = score
                    best_params = params.copy()
            except Exception as e:
                logger.warning(f"Trial {i} failed: {e}")

        duration = time.time() - start
        logger.info(
            f"Random search complete: {len(all_results)} trials in {duration:.1f}s, "
            f"best {metric}={best_score:.4f}"
        )

        return OptimizationResult(
            best_params=best_params,
            best_score=best_score,
            metric=metric,
            all_results=sorted(all_results, key=lambda x: x["score"], reverse=True),
            duration_s=duration,
            total_trials=len(all_results),
        )

    def sensitivity_analysis(
        self,
        base_params: Dict[str, Any],
        param_spaces: Dict[str, ParamRange],
        metric: str = "sharpe",
    ) -> Dict[str, List[Tuple[Any, float]]]:
        """Test each parameter independently while holding others at base values.

        Returns a dict of param_name -> [(value, score), ...] showing
        how each parameter affects the metric in isolation.
        """
        results = {}
        base_score_dict = self.backtest_fn(base_params)
        base_score = base_score_dict.get(metric, 0)

        for space in param_spaces.values():
            param_results = []
            for value in space.values:
                test_params = {**base_params, space.name: value}
                try:
                    scores = self.backtest_fn(test_params)
                    score = scores.get(metric, float("-inf"))
                    param_results.append((value, score))
                except Exception:
                    param_results.append((value, float("-inf")))

            results[space.name] = param_results
            # Log sensitivity
            if param_results:
                scores_only = [s for _, s in param_results if s > float("-inf")]
                if scores_only:
                    spread = max(scores_only) - min(scores_only)
                    logger.info(
                        f"Sensitivity {space.name}: spread={spread:.4f}, "
                        f"base={base_score:.4f}"
                    )

        return results


# ── Sharpe Ratio Calculation ────────────────────────────────────────

def compute_sharpe(equity_curve: List[Dict], annual_risk_free: float = 0.0) -> float:
    """Calculate annualized Sharpe ratio from an equity curve.

    Args:
        equity_curve: List of {"equity": float, ...} dicts (hourly or daily).
        annual_risk_free: Annual risk-free rate (e.g. 0.05 for 5%).

    Returns:
        Annualized Sharpe ratio, or 0.0 if insufficient data.
    """
    if len(equity_curve) < 2:
        return 0.0

    equities = [e["equity"] for e in equity_curve]
    returns = []
    for i in range(1, len(equities)):
        if equities[i - 1] > 0:
            returns.append((equities[i] - equities[i - 1]) / equities[i - 1])

    if len(returns) < 2:
        return 0.0

    mean_ret = sum(returns) / len(returns)
    variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
    std_ret = math.sqrt(variance) if variance > 0 else 0.0

    if std_ret == 0:
        return 0.0

    # Assume hourly data → ~8760 periods/year; daily → ~365
    # Heuristic: if >500 data points for 30 days, it's hourly
    periods_per_year = 8760 if len(returns) > 500 else 365
    rf_per_period = annual_risk_free / periods_per_year

    sharpe = (mean_ret - rf_per_period) / std_ret * math.sqrt(periods_per_year)
    return round(sharpe, 4)


# ── Backtest Bridge ─────────────────────────────────────────────────

# Maps optimizer param names → TradingConfig attributes
_PARAM_CONFIG_MAP = {
    "atr_mult": "tp_sl_atr_mult",
    "rr1": "tp_sl_rr1",
    "rr2": "tp_sl_rr2",
    "confidence_floor": "ensemble_confidence_floor",
    "veto_ratio": "veto_ratio",
    "min_votes": "min_votes_required",
    "tf_weight_5m": "tf_weight_5m",
    "tf_weight_1h": "tf_weight_1h",
    "tf_weight_6h": "tf_weight_6h",
    "tf_weight_daily": "tf_weight_daily",
    "risk_per_trade": "risk_per_trade",
    "max_leverage": "max_leverage",
    "trailing_stop_atr_mult": "trailing_stop_atr_mult",
    "min_signal_rr": "min_signal_rr",
    "mc_num_sims": "mc_num_sims",
}


def create_backtest_fn(
    symbols: List[str],
    days: int = 30,
    strategies: Optional[List[str]] = None,
    starting_equity: float = 10000.0,
) -> Callable[[Dict[str, Any]], Dict[str, float]]:
    """Create a backtest function compatible with ParameterOptimizer.

    Returns a callable that accepts a dict of parameters, runs a full
    backtest with those params applied to TradingConfig, and returns
    metric scores including sharpe, total_pnl, win_rate, etc.

    Usage:
        bt_fn = create_backtest_fn(["BTC", "ETH"], days=30)
        optimizer = ParameterOptimizer(bt_fn)
        result = optimizer.grid_search(STRATEGY_PARAM_SPACES)
    """
    def backtest_fn(params: Dict[str, Any]) -> Dict[str, float]:
        # Lazy import to avoid circular deps and allow use without backtest deps
        from backtest.engine import BacktestEngine
        from trading_config import TradingConfig

        config = TradingConfig()
        config.starting_equity = starting_equity

        # Apply optimizer params to config
        for param_name, value in params.items():
            config_attr = _PARAM_CONFIG_MAP.get(param_name, param_name)
            if hasattr(config, config_attr):
                setattr(config, config_attr, value)
            else:
                logger.debug(f"Unknown param {param_name} (mapped to {config_attr}), skipping")

        engine = BacktestEngine(config)
        report = engine.run(symbols, days, strategies)

        results = report.get("results", {})
        sharpe = compute_sharpe(engine.equity_curve)

        return {
            "sharpe": sharpe,
            "total_pnl": results.get("net_pnl", 0.0),
            "total_return_pct": results.get("total_return_pct", 0.0),
            "win_rate": results.get("win_rate", 0.0),
            "max_drawdown_pct": results.get("max_drawdown_pct", 0.0),
            "total_trades": results.get("total_trades", 0),
        }

    return backtest_fn
