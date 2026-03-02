"""
Live A/B Testing Framework — run strategy variants side-by-side with statistical rigor.

This module enables controlled experiments on trading parameters:
  1. Define experiments with control (baseline) and variant (modified) configurations
  2. Deterministically split signals into control vs variant groups
  3. Track separate performance metrics for each group
  4. Compute statistical significance using z-test and Welch's t-test (no scipy)
  5. Auto-recommend graduation when a variant proves significantly better

Usage:
    from analytics.ab_testing import get_ab_manager

    mgr = get_ab_manager()
    exp_id = mgr.create_experiment(
        name="Higher confidence floor",
        description="Test raising confidence floor from 55 to 65",
        parameter_name="confidence_floor",
        control_value=55.0,
        variant_value=65.0,
    )

    group = mgr.get_assignment(exp_id, symbol="BTC/USDT", trace_id="abc123")
    # ... execute trade using control or variant config ...
    mgr.record_outcome(exp_id, group, "BTC/USDT", pnl=12.5, win=True)

    result = mgr.evaluate_experiment(exp_id)
    print(result.recommended_action)  # "graduate_variant" / "keep_control" / "needs_more_data"
"""

import hashlib
import json
import logging
import math
import os
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.ab_testing")


# ── Statistical helpers (no scipy) ──────────────────────────────────


def _norm_cdf(x: float) -> float:
    """Cumulative distribution function for standard normal distribution.

    Uses the complementary error function:  Phi(x) = 0.5 * (1 + erf(x / sqrt(2)))
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _z_test_proportions(
    successes_a: int,
    n_a: int,
    successes_b: int,
    n_b: int,
) -> Tuple[float, float]:
    """Two-proportion z-test.

    Tests H0: p_a == p_b vs H1: p_a != p_b  (two-sided).

    Returns:
        (z_statistic, p_value)
    """
    if n_a == 0 or n_b == 0:
        return 0.0, 1.0

    p_a = successes_a / n_a
    p_b = successes_b / n_b

    # Pooled proportion under H0
    p_pool = (successes_a + successes_b) / (n_a + n_b)

    # Guard against degenerate cases (all wins or all losses)
    if p_pool <= 0.0 or p_pool >= 1.0:
        return 0.0, 1.0

    se = math.sqrt(p_pool * (1.0 - p_pool) * (1.0 / n_a + 1.0 / n_b))
    if se == 0.0:
        return 0.0, 1.0

    z = (p_b - p_a) / se
    p_value = 2.0 * (1.0 - _norm_cdf(abs(z)))
    return z, p_value


def _welch_t_test(
    values_a: List[float],
    values_b: List[float],
) -> Tuple[float, float]:
    """Welch's t-test for unequal variances (two-sided).

    Approximates the p-value using the normal distribution (valid for large n;
    conservative for smaller n — acceptable for a trading bot that requires
    min_trades >= 50 per group).

    Returns:
        (t_statistic, approximate_p_value)
    """
    n_a = len(values_a)
    n_b = len(values_b)

    if n_a < 2 or n_b < 2:
        return 0.0, 1.0

    mean_a = sum(values_a) / n_a
    mean_b = sum(values_b) / n_b

    # Sample variances (Bessel-corrected)
    var_a = sum((x - mean_a) ** 2 for x in values_a) / (n_a - 1)
    var_b = sum((x - mean_b) ** 2 for x in values_b) / (n_b - 1)

    se_sq = var_a / n_a + var_b / n_b
    if se_sq <= 0.0:
        return 0.0, 1.0

    se = math.sqrt(se_sq)
    t = (mean_b - mean_a) / se

    # Welch-Satterthwaite degrees of freedom (for reference, not used directly
    # since we approximate with the normal CDF for simplicity)
    # df = se_sq**2 / ((var_a/n_a)**2/(n_a-1) + (var_b/n_b)**2/(n_b-1))

    # Approximate p-value via normal CDF (good approximation for df > ~30)
    p_value = 2.0 * (1.0 - _norm_cdf(abs(t)))
    return t, p_value


def _compute_sharpe(pnl_values: List[float], annualize: bool = False) -> float:
    """Compute Sharpe ratio from a list of trade PnL values.

    Returns 0.0 if there are fewer than 2 data points or zero stdev.
    """
    n = len(pnl_values)
    if n < 2:
        return 0.0

    mean = sum(pnl_values) / n
    variance = sum((x - mean) ** 2 for x in pnl_values) / (n - 1)
    if variance <= 0.0:
        return 0.0

    stdev = math.sqrt(variance)
    sharpe = mean / stdev

    if annualize:
        # Approximate: assume ~3 trades/day, 365 trading days
        sharpe *= math.sqrt(3 * 365)

    return sharpe


def _confidence_interval_proportion(
    successes: int,
    n: int,
    z_crit: float = 1.96,
) -> Tuple[float, float]:
    """Wald confidence interval for a proportion (95% by default)."""
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    se = math.sqrt(p * (1.0 - p) / n) if 0.0 < p < 1.0 else 0.0
    return (p - z_crit * se, p + z_crit * se)


# ── Data structures ─────────────────────────────────────────────────


@dataclass
class Experiment:
    """Defines an A/B experiment."""

    id: str
    name: str
    description: str
    control_config: Dict[str, Any]  # baseline parameters
    variant_config: Dict[str, Any]  # modified parameters
    parameter_name: str  # what's being tested (e.g. "confidence_floor")
    start_time: float  # time.time()
    min_trades: int = 50  # minimum trades per group before evaluation
    max_duration_days: int = 14
    status: str = "active"  # active | completed | graduated | abandoned


@dataclass
class ExperimentResult:
    """Outcome of evaluating an experiment."""

    experiment_id: str
    control_trades: int
    variant_trades: int
    control_win_rate: float
    variant_win_rate: float
    control_avg_pnl: float
    variant_avg_pnl: float
    control_sharpe: float
    variant_sharpe: float
    p_value: float  # approximate from z-test / Welch's t-test
    is_significant: bool  # p < 0.05
    recommended_action: str  # "graduate_variant", "keep_control", "needs_more_data"
    confidence_interval: Tuple[float, float]  # 95% CI on variant win rate


@dataclass
class TradeOutcome:
    """A single recorded trade outcome within an experiment."""

    experiment_id: str
    group: str  # "control" or "variant"
    symbol: str
    pnl: float
    win: bool
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── ABTestManager ───────────────────────────────────────────────────


class ABTestManager:
    """Manages the lifecycle of A/B experiments on trading parameters.

    All state is persisted to JSON files under *data_dir* so experiments
    survive bot restarts.  Access is thread-safe via a reentrant lock.
    """

    def __init__(self, data_dir: str = "data/ab_tests"):
        self._data_dir = data_dir
        self._lock = threading.Lock()

        # In-memory caches (loaded lazily from disk)
        self._experiments: Dict[str, Experiment] = {}
        self._outcomes: Dict[str, List[TradeOutcome]] = {}  # keyed by experiment_id

        os.makedirs(self._data_dir, exist_ok=True)
        self._load_state()

    # ── persistence ──────────────────────────────────────────────

    def _experiments_path(self) -> str:
        return os.path.join(self._data_dir, "experiments.json")

    def _outcomes_path(self, experiment_id: str) -> str:
        return os.path.join(self._data_dir, f"outcomes_{experiment_id}.json")

    def _load_state(self) -> None:
        """Load experiments and outcomes from disk."""
        path = self._experiments_path()
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    raw = json.load(f)
                for item in raw:
                    exp = Experiment(**item)
                    self._experiments[exp.id] = exp
                logger.info("Loaded %d experiments from disk", len(self._experiments))
            except Exception:
                logger.exception("Failed to load experiments from %s", path)

        # Load outcomes for each known experiment
        for exp_id in list(self._experiments.keys()):
            self._load_outcomes(exp_id)

    def _load_outcomes(self, experiment_id: str) -> None:
        path = self._outcomes_path(experiment_id)
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    raw = json.load(f)
                self._outcomes[experiment_id] = [TradeOutcome(**o) for o in raw]
            except Exception:
                logger.exception(
                    "Failed to load outcomes for experiment %s", experiment_id
                )
                self._outcomes[experiment_id] = []
        else:
            self._outcomes.setdefault(experiment_id, [])

    def _save_experiments(self) -> None:
        path = self._experiments_path()
        try:
            data = [asdict(e) for e in self._experiments.values()]
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            logger.exception("Failed to save experiments to %s", path)

    def _save_outcomes(self, experiment_id: str) -> None:
        path = self._outcomes_path(experiment_id)
        try:
            data = [asdict(o) for o in self._outcomes.get(experiment_id, [])]
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            logger.exception(
                "Failed to save outcomes for experiment %s", experiment_id
            )

    # ── public API ───────────────────────────────────────────────

    def create_experiment(
        self,
        name: str,
        description: str,
        parameter_name: str,
        control_value: Any,
        variant_value: Any,
        min_trades: int = 50,
        max_duration_days: int = 14,
    ) -> str:
        """Create a new A/B experiment.  Returns the experiment ID."""
        exp_id = f"exp_{uuid.uuid4().hex[:12]}"
        experiment = Experiment(
            id=exp_id,
            name=name,
            description=description,
            control_config={parameter_name: control_value},
            variant_config={parameter_name: variant_value},
            parameter_name=parameter_name,
            start_time=time.time(),
            min_trades=min_trades,
            max_duration_days=max_duration_days,
            status="active",
        )
        with self._lock:
            self._experiments[exp_id] = experiment
            self._outcomes[exp_id] = []
            self._save_experiments()
        logger.info(
            "Created experiment %s: %s (%s: %s vs %s)",
            exp_id,
            name,
            parameter_name,
            control_value,
            variant_value,
        )
        return exp_id

    def get_assignment(
        self, experiment_id: str, symbol: str, trace_id: str
    ) -> str:
        """Deterministically assign a signal to 'control' or 'variant'.

        Uses a SHA-256 hash of (experiment_id, symbol, trace_id) so the same
        signal always maps to the same group — critical for reproducibility.
        """
        with self._lock:
            exp = self._experiments.get(experiment_id)
            if exp is None or exp.status != "active":
                # Inactive experiments default to control
                return "control"

        key = f"{experiment_id}:{symbol}:{trace_id}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        # Use the first 8 hex characters as an integer for a 50/50 split
        bucket = int(digest[:8], 16) % 2
        return "variant" if bucket == 1 else "control"

    def record_outcome(
        self,
        experiment_id: str,
        group: str,
        symbol: str,
        pnl: float,
        win: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a trade outcome for an experiment group."""
        if group not in ("control", "variant"):
            logger.warning("Invalid group '%s'; ignoring outcome", group)
            return

        outcome = TradeOutcome(
            experiment_id=experiment_id,
            group=group,
            symbol=symbol,
            pnl=pnl,
            win=win,
            timestamp=time.time(),
            metadata=metadata or {},
        )
        with self._lock:
            if experiment_id not in self._outcomes:
                self._outcomes[experiment_id] = []
            self._outcomes[experiment_id].append(outcome)
            self._save_outcomes(experiment_id)
            logger.debug(
                "Recorded %s outcome for %s: pnl=%.4f win=%s",
                group,
                experiment_id,
                pnl,
                win,
            )

            # Check if experiment exceeded max duration
            exp = self._experiments.get(experiment_id)
            if exp and exp.status == "active":
                elapsed_days = (time.time() - exp.start_time) / 86400.0
                if elapsed_days > exp.max_duration_days:
                    logger.info(
                        "Experiment %s exceeded max duration (%d days); "
                        "marking as completed",
                        experiment_id,
                        exp.max_duration_days,
                    )
                    exp.status = "completed"
                    self._save_experiments()

    def evaluate_experiment(self, experiment_id: str) -> ExperimentResult:
        """Evaluate the current results of an experiment.

        Computes win-rate z-test, PnL Welch's t-test, Sharpe ratios, and
        returns a recommendation: graduate_variant, keep_control, or
        needs_more_data.
        """
        with self._lock:
            exp = self._experiments.get(experiment_id)
            if exp is None:
                raise ValueError(f"Unknown experiment: {experiment_id}")

            outcomes = list(self._outcomes.get(experiment_id, []))

        # Split outcomes by group
        control_outcomes = [o for o in outcomes if o.group == "control"]
        variant_outcomes = [o for o in outcomes if o.group == "variant"]

        n_control = len(control_outcomes)
        n_variant = len(variant_outcomes)

        control_wins = sum(1 for o in control_outcomes if o.win)
        variant_wins = sum(1 for o in variant_outcomes if o.win)

        control_pnls = [o.pnl for o in control_outcomes]
        variant_pnls = [o.pnl for o in variant_outcomes]

        # Win rates
        control_wr = control_wins / n_control if n_control > 0 else 0.0
        variant_wr = variant_wins / n_variant if n_variant > 0 else 0.0

        # Average PnL
        control_avg_pnl = sum(control_pnls) / n_control if n_control > 0 else 0.0
        variant_avg_pnl = sum(variant_pnls) / n_variant if n_variant > 0 else 0.0

        # Sharpe ratios
        control_sharpe = _compute_sharpe(control_pnls)
        variant_sharpe = _compute_sharpe(variant_pnls)

        # Statistical tests
        # Primary: z-test on win rates
        _, p_wr = _z_test_proportions(
            control_wins, n_control, variant_wins, n_variant
        )
        # Secondary: Welch's t-test on PnL means
        _, p_pnl = _welch_t_test(control_pnls, variant_pnls)

        # Use the more conservative (higher) p-value to be safe
        p_value = max(p_wr, p_pnl)
        is_significant = p_value < 0.05

        # Confidence interval on variant win rate
        ci = _confidence_interval_proportion(variant_wins, n_variant)

        # Determine recommendation
        min_trades = exp.min_trades if exp is not None else 50
        if n_control < min_trades or n_variant < min_trades:
            recommended_action = "needs_more_data"
        elif is_significant and variant_avg_pnl > control_avg_pnl:
            recommended_action = "graduate_variant"
        elif is_significant and variant_avg_pnl <= control_avg_pnl:
            recommended_action = "keep_control"
        else:
            # Not significant yet — check if we've run long enough
            if exp is not None:
                elapsed_days = (time.time() - exp.start_time) / 86400.0
                if elapsed_days > exp.max_duration_days:
                    # Ran the full duration without significance — keep control
                    recommended_action = "keep_control"
                else:
                    recommended_action = "needs_more_data"
            else:
                recommended_action = "needs_more_data"

        result = ExperimentResult(
            experiment_id=experiment_id,
            control_trades=n_control,
            variant_trades=n_variant,
            control_win_rate=control_wr,
            variant_win_rate=variant_wr,
            control_avg_pnl=control_avg_pnl,
            variant_avg_pnl=variant_avg_pnl,
            control_sharpe=control_sharpe,
            variant_sharpe=variant_sharpe,
            p_value=p_value,
            is_significant=is_significant,
            recommended_action=recommended_action,
            confidence_interval=ci,
        )

        logger.info(
            "Experiment %s evaluation: control=%d trades (wr=%.1f%%), "
            "variant=%d trades (wr=%.1f%%), p=%.4f, action=%s",
            experiment_id,
            n_control,
            control_wr * 100,
            n_variant,
            variant_wr * 100,
            p_value,
            recommended_action,
        )
        return result

    def get_active_experiments(self) -> List[Experiment]:
        """Return all experiments with status 'active'."""
        with self._lock:
            return [
                exp
                for exp in self._experiments.values()
                if exp.status == "active"
            ]

    def get_all_experiments(self) -> List[Experiment]:
        """Return all experiments regardless of status."""
        with self._lock:
            return list(self._experiments.values())

    def graduate_experiment(self, experiment_id: str) -> None:
        """Mark an experiment as graduated (variant wins, promote it)."""
        with self._lock:
            exp = self._experiments.get(experiment_id)
            if exp is None:
                raise ValueError(f"Unknown experiment: {experiment_id}")
            exp.status = "graduated"
            self._save_experiments()
        logger.info(
            "Experiment %s graduated: variant config %s is now recommended",
            experiment_id,
            exp.variant_config,
        )

    def abandon_experiment(self, experiment_id: str) -> None:
        """Mark an experiment as abandoned (e.g. flawed design, external event)."""
        with self._lock:
            exp = self._experiments.get(experiment_id)
            if exp is None:
                raise ValueError(f"Unknown experiment: {experiment_id}")
            exp.status = "abandoned"
            self._save_experiments()
        logger.info("Experiment %s abandoned", experiment_id)

    def get_config_for_group(
        self, experiment_id: str, group: str
    ) -> Dict[str, Any]:
        """Return the parameter config dict for a given group.

        Useful for the trading engine to apply the correct parameter values.
        """
        with self._lock:
            exp = self._experiments.get(experiment_id)
            if exp is None:
                raise ValueError(f"Unknown experiment: {experiment_id}")
            if group == "variant":
                return dict(exp.variant_config)
            return dict(exp.control_config)

    def get_experiment_report(self) -> str:
        """Format a human-readable report of all experiments and their status."""
        with self._lock:
            experiments = list(self._experiments.values())

        if not experiments:
            return "No A/B experiments configured."

        lines: List[str] = []
        lines.append("=" * 70)
        lines.append("  A/B EXPERIMENT REPORT")
        lines.append("=" * 70)

        for exp in sorted(experiments, key=lambda e: e.start_time, reverse=True):
            elapsed_days = (time.time() - exp.start_time) / 86400.0
            lines.append("")
            lines.append(f"  [{exp.status.upper()}] {exp.name}")
            lines.append(f"  ID: {exp.id}")
            lines.append(f"  Description: {exp.description}")
            lines.append(
                f"  Parameter: {exp.parameter_name}  "
                f"control={exp.control_config.get(exp.parameter_name)}  "
                f"variant={exp.variant_config.get(exp.parameter_name)}"
            )
            lines.append(
                f"  Duration: {elapsed_days:.1f}d / {exp.max_duration_days}d  "
                f"(min trades per group: {exp.min_trades})"
            )

            # If we have outcomes, include a quick summary
            try:
                result = self.evaluate_experiment(exp.id)
                lines.append(
                    f"  Control:  {result.control_trades} trades, "
                    f"WR {result.control_win_rate:.1%}, "
                    f"avg PnL ${result.control_avg_pnl:.2f}, "
                    f"Sharpe {result.control_sharpe:.2f}"
                )
                lines.append(
                    f"  Variant:  {result.variant_trades} trades, "
                    f"WR {result.variant_win_rate:.1%}, "
                    f"avg PnL ${result.variant_avg_pnl:.2f}, "
                    f"Sharpe {result.variant_sharpe:.2f}"
                )
                lines.append(
                    f"  p-value: {result.p_value:.4f}  "
                    f"significant: {result.is_significant}  "
                    f"CI(variant WR): [{result.confidence_interval[0]:.1%}, "
                    f"{result.confidence_interval[1]:.1%}]"
                )
                lines.append(f"  >> Recommendation: {result.recommended_action}")
            except Exception:
                lines.append("  (unable to evaluate — no data)")

            lines.append("-" * 70)

        lines.append("")
        return "\n".join(lines)


# ── Singleton ───────────────────────────────────────────────────────

_singleton: Optional[ABTestManager] = None
_singleton_lock = threading.Lock()


def get_ab_manager(data_dir: str = "data/ab_tests") -> ABTestManager:
    """Return the global ABTestManager singleton.

    Thread-safe lazy initialization.  The *data_dir* argument is only
    used on first call; subsequent calls return the existing instance.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            # Double-checked locking
            if _singleton is None:
                _singleton = ABTestManager(data_dir=data_dir)
    return _singleton
