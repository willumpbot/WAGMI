"""
Walk-Forward Validation: prevents overfitting by testing on unseen data.

Runs the backtest engine window-by-window (train then test), saving results
incrementally so crashes don't lose progress.

This reveals overfitting: if the strategy's parameters were tuned to the
training data, test-window performance will be significantly worse.

Usage:
    runner = WalkForwardRunner(symbols=["SOL", "BTC"], total_days=120)
    report = runner.run()
    print(runner.format_report(report))

CLI:
    python cli.py --mode walkforward --days 120 --symbols SOL,BTC
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any

logger = logging.getLogger("bot.backtest.walk_forward")


@dataclass
class WindowResult:
    """Result from a single train or test window."""
    window_type: str  # "train" or "test"
    window_idx: int
    days: int
    total_trades: int = 0
    wins: int = 0
    total_pnl: float = 0.0
    avg_pnl: float = 0.0
    profit_factor: float = 0.0
    # Quant metrics (populated by enhanced validation)
    expectancy: float = 0.0
    sharpe: float = 0.0
    var_95: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.0


@dataclass
class WalkForwardReport:
    """Full walk-forward validation report."""
    symbols: List[str]
    total_days: int
    train_days: int
    test_days: int
    n_windows: int
    total_trades: int = 0
    windows: List[WindowResult] = field(default_factory=list)
    full_run_metrics: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @property
    def train_results(self) -> List[WindowResult]:
        return [w for w in self.windows if w.window_type == "train"]

    @property
    def test_results(self) -> List[WindowResult]:
        return [w for w in self.windows if w.window_type == "test"]

    @property
    def avg_train_wr(self) -> float:
        results = self.train_results
        if not results:
            return 0.0
        total_trades = sum(r.total_trades for r in results)
        total_wins = sum(r.wins for r in results)
        return total_wins / total_trades if total_trades > 0 else 0.0

    @property
    def avg_test_wr(self) -> float:
        results = self.test_results
        if not results:
            return 0.0
        total_trades = sum(r.total_trades for r in results)
        total_wins = sum(r.wins for r in results)
        return total_wins / total_trades if total_trades > 0 else 0.0

    @property
    def overfit_ratio(self) -> float:
        """Ratio of test/train per-trade PnL. >0.8 = good, <0.5 = overfit."""
        train_trades = sum(r.total_trades for r in self.train_results)
        test_trades = sum(r.total_trades for r in self.test_results)
        if train_trades == 0 or test_trades == 0:
            return 0.0
        train_avg = sum(r.total_pnl for r in self.train_results) / train_trades
        test_avg = sum(r.total_pnl for r in self.test_results) / test_trades
        if train_avg <= 0:
            return 1.0 if test_avg >= 0 else 0.0
        return test_avg / train_avg

    @property
    def test_profitable(self) -> bool:
        """Whether out-of-sample data was net profitable."""
        return sum(r.total_pnl for r in self.test_results) > 0


class WalkForwardRunner:
    """Run walk-forward validation with sliding train/test windows.

    Runs the full period as a single backtest, then partitions the
    trade log by timestamp into alternating train/test segments.
    """

    def __init__(
        self,
        symbols: Optional[List[str]] = None,
        total_days: int = 120,
        train_days: int = 60,
        test_days: int = 20,
    ):
        self.symbols = symbols or ["SOL", "BTC", "ETH"]
        self.total_days = total_days
        self.train_days = train_days
        self.test_days = test_days

    def run(self, symbols=None, days=None, output_path=None) -> WalkForwardReport:
        """Run walk-forward validation window by window.

        Each window runs the backtest engine separately on the train period then
        the test period, so the full dataset is never loaded into memory at once.
        Per-window results are saved to a JSON checkpoint file after each window
        so a crash only loses the current in-progress window.
        """
        from trading_config import TradingConfig
        from backtest.engine import BacktestEngine

        symbols = symbols or self.symbols
        total_days = days or self.total_days
        window_size = self.train_days + self.test_days
        n_windows = max(1, total_days // window_size)

        config = TradingConfig()
        engine = BacktestEngine(config=config)

        # Output file for incremental saves
        if output_path is None:
            os.makedirs("data/backtest_checkpoints", exist_ok=True)
            output_path = (
                f"data/backtest_checkpoints/walkforward_{total_days}d_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )

        logger.info(
            f"[WF] Walk-forward: {n_windows} windows × "
            f"({self.train_days}d train + {self.test_days}d test) = {total_days}d total"
        )

        report = WalkForwardReport(
            symbols=symbols,
            total_days=total_days,
            train_days=self.train_days,
            test_days=self.test_days,
            n_windows=n_windows,
        )

        checkpoint_windows: List[Dict] = []

        for window_idx in range(n_windows):
            logger.info(
                f"[WF] Window {window_idx + 1}/{n_windows}: "
                f"train={self.train_days}d, test={self.test_days}d"
            )

            try:
                # --- Train window ---
                train_raw = engine.run(symbols=symbols, days=self.train_days)
                train_trades = train_raw.get("trade_timeline", [])
                train_result = self._compute_window_stats(
                    train_trades, "train", window_idx, self.train_days
                )
                report.windows.append(train_result)
                train_metrics = self._extract_metrics(train_raw, "train", window_idx)

                # --- Test window (out-of-sample) ---
                test_raw = engine.run(symbols=symbols, days=self.test_days)
                test_trades = test_raw.get("trade_timeline", [])
                test_result = self._compute_window_stats(
                    test_trades, "test", window_idx, self.test_days
                )
                report.windows.append(test_result)
                test_metrics = self._extract_metrics(test_raw, "test", window_idx)

                window_checkpoint = {
                    "window": window_idx + 1,
                    "train_days": self.train_days,
                    "test_days": self.test_days,
                    "train": train_metrics,
                    "test": test_metrics,
                    "degradation": self._calculate_degradation(train_metrics, test_metrics),
                }
                checkpoint_windows.append(window_checkpoint)

                logger.info(
                    f"[WF] Window {window_idx}: "
                    f"Train({train_result.total_trades} trades, WR={train_result.win_rate:.0%}, "
                    f"PnL=${train_result.total_pnl:+.0f}) | "
                    f"Test({test_result.total_trades} trades, WR={test_result.win_rate:.0%}, "
                    f"PnL=${test_result.total_pnl:+.0f})"
                )

                # Save progress after each window (crash recovery)
                with open(output_path, "w") as f:
                    json.dump(
                        {"windows": checkpoint_windows, "complete": False},
                        f, indent=2, default=str,
                    )
                logger.info(f"[WF] Window {window_idx + 1} checkpoint saved to {output_path}")

            except Exception as e:
                logger.error(f"[WF] Window {window_idx + 1} failed: {e}")
                # Save what we have so far before giving up
                with open(output_path, "w") as f:
                    json.dump(
                        {"windows": checkpoint_windows, "complete": False, "error": str(e)},
                        f, indent=2, default=str,
                    )
                break

        # Build full_run_metrics summary aggregated across all windows
        all_trades = report.windows
        total_trade_count = sum(w.total_trades for w in all_trades)
        report.total_trades = total_trade_count
        total_pnl = sum(w.total_pnl for w in all_trades)
        total_wins = sum(w.wins for w in all_trades)
        report.full_run_metrics = {
            "total_trades": total_trade_count,
            "win_rate": total_wins / total_trade_count if total_trade_count > 0 else 0.0,
            "total_pnl": total_pnl,
            "n_windows": n_windows,
        }

        # Final checkpoint with complete flag
        summary = {
            "total_trades": total_trade_count,
            "total_pnl": total_pnl,
            "n_windows": len(checkpoint_windows),
        }
        with open(output_path, "w") as f:
            json.dump(
                {"windows": checkpoint_windows, "summary": summary, "complete": True},
                f, indent=2, default=str,
            )
        logger.info(f"[WF] Walk-forward complete. Results saved to {output_path}")

        return report

    def _extract_metrics(self, report: dict, phase: str, window_idx: int) -> dict:
        """Extract key metrics from a backtest engine report dict."""
        results = report.get("results", {})
        risk_metrics = report.get("risk_metrics", {})

        # Results may be keyed by symbol or be a flat dict — handle both shapes
        if results and isinstance(next(iter(results.values()), None), dict):
            # Keyed by symbol
            total_trades = sum(r.get("total_trades", 0) for r in results.values())
            total_pnl = sum(r.get("total_pnl", 0.0) for r in results.values())
            wins = sum(r.get("wins", 0) for r in results.values())
        else:
            total_trades = results.get("closed_trades", results.get("total_trades", 0))
            total_pnl = results.get("total_pnl", 0.0)
            wins = results.get("wins", 0)

        wr = (wins / total_trades * 100) if total_trades > 0 else 0.0
        return {
            "phase": phase,
            "window": window_idx + 1,
            "total_trades": total_trades,
            "total_pnl": total_pnl,
            "win_rate": wr,
            "sharpe": risk_metrics.get("sharpe_ratio", 0.0),
            "max_drawdown": risk_metrics.get("max_drawdown_pct", 0.0),
        }

    def _calculate_degradation(self, train: dict, test: dict) -> dict:
        """How much does performance degrade from train to test?"""
        return {
            "pnl_ratio": (
                test["total_pnl"] / train["total_pnl"]
                if train["total_pnl"] != 0 else 0.0
            ),
            "wr_delta": test["win_rate"] - train["win_rate"],
            "trade_count_ratio": (
                test["total_trades"] / train["total_trades"]
                if train["total_trades"] > 0 else 0.0
            ),
        }

    def _compute_window_stats(
        self, trades: List[Dict], window_type: str, window_idx: int, days: int
    ) -> WindowResult:
        """Compute aggregate stats for a list of trades."""
        total_pnl = 0.0
        wins = 0
        gross_wins = 0.0
        gross_losses = 0.0

        for t in trades:
            # trade_timeline has net pnl (fee already subtracted in the engine)
            pnl = t.get("pnl", 0.0)
            fee = t.get("fee", 0.0)
            net_pnl = pnl - fee
            total_pnl += net_pnl
            if net_pnl > 0:
                wins += 1
                gross_wins += net_pnl
            elif net_pnl < 0:
                gross_losses += abs(net_pnl)

        pf = gross_wins / gross_losses if gross_losses > 0 else (999.0 if gross_wins > 0 else 0.0)
        avg_pnl = total_pnl / len(trades) if trades else 0.0

        # Compute quant metrics for this window
        expectancy = 0.0
        sharpe = 0.0
        var_95 = 0.0
        try:
            from backtest.quant_analytics import compute_expectancy, compute_var
            wr = wins / len(trades) if trades else 0
            avg_win = gross_wins / wins if wins > 0 else 0
            avg_loss_val = gross_losses / (len(trades) - wins) if (len(trades) - wins) > 0 else 0
            expectancy = round(compute_expectancy(wr, avg_win, avg_loss_val), 2)

            if trades:
                import numpy as np
                pnls = [t.get("pnl", 0) - t.get("fee", 0) for t in trades]
                daily_rets = np.array(pnls) / 10000  # Approx % returns
                mean_r = float(np.mean(daily_rets))
                std_r = float(np.std(daily_rets, ddof=1)) if len(daily_rets) > 1 else 0
                sharpe = round(mean_r / std_r * (365 ** 0.5), 3) if std_r > 0 else 0
                var_95 = round(compute_var(daily_rets.tolist()), 6)
        except Exception:
            pass

        return WindowResult(
            window_type=window_type,
            window_idx=window_idx,
            days=days,
            total_trades=len(trades),
            wins=wins,
            total_pnl=round(total_pnl, 2),
            avg_pnl=round(avg_pnl, 2),
            profit_factor=round(pf, 2),
            expectancy=expectancy,
            sharpe=sharpe,
            var_95=var_95,
        )

    def format_report(self, report: WalkForwardReport) -> str:
        """Format walk-forward report as readable text."""
        lines = []
        lines.append("=" * 70)
        split_note = ""
        orig_window = self.train_days + self.test_days
        if report.total_days < orig_window:
            split_note = f" [adaptive: was {self.train_days}/{self.test_days}]"
        lines.append(
            f"WALK-FORWARD VALIDATION: {', '.join(report.symbols)} | "
            f"{report.total_days}d ({report.train_days}d train / {report.test_days}d test{split_note})"
        )
        lines.append("=" * 70)

        # Full run summary
        fm = report.full_run_metrics
        lines.append(
            f"Full run: {fm.get('total_trades', 0)} trades, "
            f"WR={fm.get('win_rate', 0):.0%}, PnL=${fm.get('total_pnl', 0):+.0f}, "
            f"Sharpe={fm.get('sharpe', 0):.2f}, PF={fm.get('profit_factor', 0):.2f}"
        )
        lines.append("")

        # Per-window results
        for i in range(report.n_windows):
            train = next(
                (w for w in report.windows if w.window_idx == i and w.window_type == "train"),
                None,
            )
            test = next(
                (w for w in report.windows if w.window_idx == i and w.window_type == "test"),
                None,
            )
            lines.append(f"--- Window {i} ---")
            if train:
                lines.append(
                    f"  Train: {train.total_trades} trades, WR={train.win_rate:.0%}, "
                    f"PnL=${train.total_pnl:+.0f}, PF={train.profit_factor:.2f}, "
                    f"E=${train.expectancy:+.1f}, Sharpe={train.sharpe:.2f}, "
                    f"Avg=${train.avg_pnl:+.1f}"
                )
            if test:
                lines.append(
                    f"  Test:  {test.total_trades} trades, WR={test.win_rate:.0%}, "
                    f"PnL=${test.total_pnl:+.0f}, PF={test.profit_factor:.2f}, "
                    f"E=${test.expectancy:+.1f}, Sharpe={test.sharpe:.2f}, "
                    f"Avg=${test.avg_pnl:+.1f}"
                )
            lines.append("")

        # Aggregate
        lines.append("-" * 70)
        train_pnl = sum(r.total_pnl for r in report.train_results)
        test_pnl = sum(r.total_pnl for r in report.test_results)
        lines.append(f"AGGREGATE:")
        lines.append(
            f"  Train WR: {report.avg_train_wr:.0%}  |  Test WR: {report.avg_test_wr:.0%}"
        )
        lines.append(f"  Train PnL: ${train_pnl:+.0f}  |  Test PnL: ${test_pnl:+.0f}")
        lines.append(
            f"  Overfit Ratio: {report.overfit_ratio:.2f} "
            f"(>0.8 = good, <0.5 = overfit)"
        )
        lines.append(f"  Test Profitable: {'YES' if report.test_profitable else 'NO'}")

        # Verdict
        lines.append("")
        lines.append("=" * 70)
        if report.test_profitable and report.overfit_ratio > 0.5:
            lines.append("VERDICT: PASS — Strategy shows real edge on unseen data")
        elif report.test_profitable:
            lines.append(
                "VERDICT: CAUTION — Profitable OOS but significant overfit detected"
            )
        else:
            lines.append("VERDICT: FAIL — Strategy is not profitable on unseen data")
        lines.append("=" * 70)

        return "\n".join(lines)
