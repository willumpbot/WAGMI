"""
Easy backtest runner for ensemble strategy validation.

Usage:
    # Test all symbols for 30 days
    python backtest_runner.py --days 30

    # Test specific symbols
    python backtest_runner.py --symbols BTC ETH SOL --days 60

    # Change starting equity
    python backtest_runner.py --equity 50000 --days 30
"""

import sys
import logging
import json
from pathlib import Path
from typing import Optional

import pandas as pd

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.engine import BacktestEngine
from trading_config import TradingConfig, DEFAULT_SYMBOLS

logger = logging.getLogger("bot.backtest.runner")


class BacktestRunner:
    """
    Wrapper around BacktestEngine to make it easy to run backtests
    and compare results to paper trading.
    """

    def __init__(self, output_dir: str = "backtest_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def run(
        self,
        symbols: Optional[list] = None,
        days: int = 30,
        starting_equity: float = 50000,
        risk_per_trade: float = 0.015,
        strategies: Optional[list] = None,
        learn: bool = False,
    ) -> dict:
        """
        Run a backtest.

        Args:
            symbols: List of symbols to test (default: all). E.g., ["BTC", "ETH", "SOL"]
            days: Number of days of historical data to backtest on
            starting_equity: Starting account size in USD
            risk_per_trade: Risk per trade as % of equity (default 1.5%)
            strategies: Which strategies to include (default: all 4)
            learn: If True, feed results into all learning systems

        Returns:
            Dictionary with backtest results
        """

        if symbols is None:
            symbols = list(DEFAULT_SYMBOLS.keys())

        # Validate symbols
        symbols = [s for s in symbols if s in DEFAULT_SYMBOLS]
        if not symbols:
            print(f"❌ No valid symbols provided. Available: {list(DEFAULT_SYMBOLS.keys())}")
            return {}

        logger.info("=" * 60)
        logger.info(f"Starting Backtest")
        logger.info(f"  Symbols: {symbols}")
        logger.info(f"  Days: {days}")
        logger.info(f"  Starting Equity: ${starting_equity:,.2f}")
        logger.info(f"  Risk/Trade: {risk_per_trade*100:.1f}%")
        if learn:
            logger.info(f"  Learning: ENABLED (feeding all learning systems)")
        logger.info("=" * 60)

        # Build config
        config = TradingConfig()
        config.starting_equity = starting_equity
        config.risk_per_trade = risk_per_trade

        # Run backtest
        engine = BacktestEngine(config)
        results = engine.run(symbols=symbols, days=days, strategies=strategies, learn=learn)

        # Save results
        self._save_results(results, symbols, days)

        # Print Quant Intelligence Summary
        self._print_quant_summary(results)

        # Run Deployment Gate
        self._run_deployment_gate(results)

        return results

    def _save_results(self, results: dict, symbols: list, days: int):
        """Save backtest results to JSON and CSV."""
        timestamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
        results_file = self.output_dir / f"backtest_{timestamp}.json"

        # Add metadata
        results["metadata"] = {
            "symbols": symbols,
            "days": days,
            "timestamp": timestamp,
        }

        with open(results_file, "w") as f:
            json.dump(results, f, indent=2, default=str)

        logger.info(f"✅ Results saved to {results_file}")

        # Also save equity curve as CSV
        if "equity_curve" in results:
            equity_file = self.output_dir / f"equity_{timestamp}.csv"
            df = pd.DataFrame(results["equity_curve"])
            df.to_csv(equity_file, index=False)
            logger.info(f"✅ Equity curve saved to {equity_file}")

    def _print_quant_summary(self, results: dict):
        """Print Quant Intelligence Summary from backtest results."""
        try:
            q = results.get("quant_analytics", {})
            if not q or q.get("error"):
                return

            lines = []
            lines.append("")
            lines.append("=" * 58)
            lines.append("           QUANT INTELLIGENCE SUMMARY")
            lines.append("=" * 58)

            # Win rate with CI
            wr = q.get("win_rate", 0)
            ci = q.get("win_rate_ci_95", [0, 0])
            if isinstance(ci, list) and len(ci) >= 2:
                lines.append(f"  Win Rate:       {wr:.1%} [{ci[0]:.1%} - {ci[1]:.1%}] (95% CI)")
            else:
                lines.append(f"  Win Rate:       {wr:.1%}")

            # Expectancy & Kelly
            exp = q.get("expectancy_per_trade", 0)
            kelly = q.get("kelly_fraction", 0)
            hk = q.get("half_kelly", 0)
            lines.append(f"  Expectancy:     ${exp:+.2f}/trade {'(+)' if exp > 0 else '(-)'}")
            lines.append(f"  Kelly:          {kelly:.1%} (half-Kelly: {hk:.1%})")

            # Sharpe significance
            p_val = q.get("sharpe_p_value", 1.0)
            sig = "significant" if p_val < 0.05 else "marginal" if p_val < 0.10 else "not significant"
            lines.append(f"  Sharpe p-value: {p_val:.3f} ({sig})")

            # Tail risk
            var = q.get("var_95_daily")
            cvar = q.get("cvar_95_daily")
            if var is not None:
                lines.append(f"  VaR (95%):      {var:.4%} daily")
            if cvar is not None:
                lines.append(f"  CVaR (ES):      {cvar:.4%} daily")

            # Distribution
            dist = q.get("distribution", {})
            if dist:
                lines.append(f"  Skewness:       {dist.get('skewness', 0):.3f}")
                lines.append(f"  Kurtosis:       {dist.get('kurtosis', 0):.3f}")

            # Streaks
            streaks = q.get("streaks", {})
            if streaks:
                lines.append(
                    f"  Streaks:        max win={streaks.get('max_consecutive_wins', 0)}, "
                    f"max loss={streaks.get('max_consecutive_losses', 0)}"
                )

            # Strategy correlation
            corr = q.get("strategy_correlation", {})
            if corr:
                ind = corr.get("independent_count", 0)
                total = corr.get("total_strategies", 0)
                lines.append(f"  Independence:   {ind}/{total} truly independent (|r| < 0.3)")
                for pair in corr.get("redundant_pairs", []):
                    p = pair.get("pair", [])
                    r = pair.get("correlation", 0)
                    if len(p) >= 2:
                        lines.append(f"    Redundant: {p[0]} <> {p[1]} (r={r:.2f})")

            # Monte Carlo
            mc = q.get("monte_carlo", {})
            if mc and not mc.get("insufficient_data"):
                pp = mc.get("p_profitable", 0)
                verdict = mc.get("verdict", "?")
                lines.append(f"  Monte Carlo:    {pp:.0%} profitable ({verdict})")
                lines.append(
                    f"    Median DD: {mc.get('median_max_drawdown', 0):.1%}, "
                    f"95th DD: {mc.get('dd_95th_percentile', 0):.1%}"
                )

            # Best/worst regime
            by_regime = q.get("by_regime", {})
            if by_regime:
                lines.append("")
                lines.append("  Regime Breakdown:")
                for regime, metrics in sorted(by_regime.items()):
                    if isinstance(metrics, dict) and not metrics.get("insufficient_data"):
                        e = metrics.get("expectancy", 0)
                        w = metrics.get("win_rate", 0)
                        n = metrics.get("n", 0)
                        lines.append(
                            f"    {regime:<20} WR={w:.0%}, E=${e:+.1f}, n={n}"
                        )

            # Signal digest summary
            digest = results.get("signal_digest_summary", {})
            if digest and digest.get("total_evaluations", 0) > 0:
                lines.append("")
                near = digest.get("near_misses", {}).get("count", 0)
                lines.append(f"  Near-Misses:    {near} signals missed by 1 vote")
                fire_rates = digest.get("strategy_fire_rates", {})
                if fire_rates:
                    lines.append("  Strategy Fire Rates:")
                    for strat, data in sorted(fire_rates.items(), key=lambda x: -x[1].get("fire_rate", 0)):
                        fr = data.get("fire_rate", 0)
                        ac = data.get("avg_confidence", 0)
                        lines.append(f"    {strat:<24} {fr:.1%} (avg conf: {ac:.0f})")

            lines.append("=" * 58)
            print("\n".join(lines))

        except Exception as e:
            logger.debug(f"Quant summary print failed: {e}")

    def _run_deployment_gate(self, results: dict):
        """Run the 10-gate deployment readiness check."""
        try:
            from backtest.deployment_gate import check_deployment_readiness, format_gate_report
            verdict = check_deployment_readiness(results)
            print(format_gate_report(verdict))
        except Exception as e:
            logger.debug(f"Deployment gate failed: {e}")

    def compare_paper_vs_backtest(
        self,
        paper_trades_dir: str = "paper_trades",
        backtest_results_dir: str = "backtest_results",
    ):
        """
        Compare paper trading results vs backtest results.
        Shows if live signals match historical performance.
        """
        paper_dir = Path(paper_trades_dir)
        backtest_dir = Path(backtest_results_dir)

        if not paper_dir.exists():
            print(f"❌ Paper trades directory not found: {paper_dir}")
            return

        if not backtest_dir.exists():
            print(f"❌ Backtest results directory not found: {backtest_dir}")
            return

        print("\n" + "=" * 60)
        print("PAPER TRADING vs BACKTEST COMPARISON")
        print("=" * 60)

        # Find latest files
        paper_trades = sorted(paper_dir.glob("trades_*.csv"))
        if not paper_trades:
            print("❌ No paper trades found")
            return

        backtest_results = sorted(backtest_dir.glob("backtest_*.json"))
        if not backtest_results:
            print("❌ No backtest results found")
            return

        latest_paper = paper_trades[-1]
        latest_backtest = backtest_results[-1]

        print(f"\nPaper Trades: {latest_paper.name}")
        print(f"Backtest Results: {latest_backtest.name}")

        # Load paper trades
        df_paper = pd.read_csv(latest_paper)
        paper_trades = df_paper[df_paper["action"].isin(["TP1", "TP2", "SL"])].copy()

        # Load backtest results
        with open(latest_backtest, "r") as f:
            backtest = json.load(f)

        # Compare statistics
        print("\n" + "-" * 60)
        print("STATISTICS COMPARISON")
        print("-" * 60)

        if paper_trades.empty:
            print("⚠️  Not enough paper trades yet for comparison")
            return

        # Calculate paper metrics
        paper_wins = len(paper_trades[paper_trades["pnl"] > 0])
        paper_total = len(paper_trades)
        paper_wr = paper_wins / paper_total * 100 if paper_total > 0 else 0
        paper_pnl = paper_trades["pnl"].sum()
        paper_fees = paper_trades["fee"].sum()

        # Calculate backtest metrics
        backtest_summary = backtest.get("summary", {})
        bt_wr = backtest_summary.get("win_rate_pct", 0)
        bt_pnl = backtest.get("pnl", {}).get("net_pnl", 0)

        print(f"\nPaper Trading:")
        print(f"  Closed Trades: {paper_total}")
        print(f"  Win Rate: {paper_wr:.1f}%")
        print(f"  Net P&L: ${paper_pnl:+.2f} (after ${paper_fees:.2f} fees)")

        print(f"\nBacktest (Historical):")
        print(f"  Win Rate: {bt_wr:.1f}%")
        print(f"  Net P&L: ${bt_pnl:+.2f}")

        print(f"\nComparison:")
        wr_diff = paper_wr - bt_wr
        print(f"  Win Rate Difference: {wr_diff:+.1f}% {'✅' if abs(wr_diff) < 5 else '⚠️'}")
        print(f"    (Paper trades performing {'better' if wr_diff > 0 else 'worse'} than backtest)")

        print("\n" + "=" * 60)
        print("INTERPRETATION:")
        print("-" * 60)

        if abs(wr_diff) < 5:
            print("✅ Paper trading matches backtest - signals are validated!")
        elif paper_wr > bt_wr:
            print("✅ Paper trading beating backtest - live signals are sharper!")
        else:
            print("⚠️  Paper trading underperforming backtest")
            print("   Consider reviewing recent signal quality or market conditions")

        print("=" * 60 + "\n")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run backtest for ensemble strategy")
    parser.add_argument("--symbols", nargs="+", default=None, help="Symbols to test (default: all)")
    parser.add_argument("--days", type=int, default=30, help="Days of historical data (default: 30)")
    parser.add_argument("--equity", type=float, default=50000, help="Starting equity (default: $50k)")
    parser.add_argument("--risk", type=float, default=1.5, help="Risk per trade %% (default: 1.5%%)")
    parser.add_argument("--compare", action="store_true", help="Compare paper vs backtest results")
    parser.add_argument("--learn", action="store_true", help="Feed results into learning systems")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
    )

    runner = BacktestRunner()

    if args.compare:
        runner.compare_paper_vs_backtest()
    else:
        results = runner.run(
            symbols=args.symbols,
            days=args.days,
            starting_equity=args.equity,
            risk_per_trade=args.risk / 100,
            learn=args.learn,
        )
        _print_backtest_summary(results)


def _print_backtest_summary(results: dict):
    """Pretty print backtest results."""
    if not results:
        print("❌ Backtest failed - no results")
        return

    # Trade data lives in results["results"] (engine spreads trade_summary there)
    res = results.get("results", {})
    config = results.get("config", {})

    total_trades = res.get("total_trades", 0)
    wins = res.get("wins", 0)
    losses = res.get("losses", 0)
    win_rate = res.get("win_rate", 0) * 100  # win_rate is decimal 0-1, convert to pct
    net_pnl = res.get("net_pnl", 0)
    gross_pnl = res.get("gross_pnl", 0)
    pf = res.get("profit_factor", 0)
    final_eq = res.get("final_equity", config.get("starting_equity", 50000))
    start_eq = config.get("starting_equity", 50000)
    max_dd = res.get("max_drawdown_pct", 0)
    total_return = res.get("total_return_pct", 0)

    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)

    print(f"\n  Period: {config.get('days', '?')} days | Symbols: {config.get('symbols', [])}")
    print(f"  Starting Equity: ${start_eq:,.2f}")

    print("\n  TRADES:")
    print(f"  Total: {total_trades} | Wins: {wins} | Losses: {losses}")
    print(f"  Win Rate: {win_rate:.1f}%")

    print("\n  PNL:")
    print(f"  Net P&L: ${net_pnl:+,.2f}")
    print(f"  Gross P&L: ${gross_pnl:+,.2f}")
    print(f"  Profit Factor: {pf:.2f}x")
    print(f"  Final Equity: ${final_eq:,.2f} ({total_return:+.1f}%)")
    print(f"  Max Drawdown: {max_dd:.1f}%")

    # Per-symbol breakdown
    by_sym = results.get("by_symbol", {})
    if by_sym:
        print("\n  BY SYMBOL:")
        for sym, data in by_sym.items():
            sym_trades = data.get("total_trades", data.get("trades", 0))
            sym_pnl = data.get("net_pnl", data.get("pnl", 0))
            sym_wr = data.get("win_rate", 0) * 100  # decimal to pct
            if sym_trades > 0:
                print(f"    {sym:>10}: {sym_trades} trades | WR {sym_wr:.0f}% | PnL ${sym_pnl:+,.2f}")

    # Per-agreement breakdown
    by_agree = results.get("by_agreement", {})
    if by_agree:
        print("\n  BY AGREEMENT:")
        for level, data in sorted(by_agree.items()):
            a_trades = data.get("trades", 0)
            a_wr = data.get("win_rate", 0) * 100  # decimal to pct
            a_pf = data.get("profit_factor", 0)
            if a_trades > 0:
                print(f"    {level}_agree: {a_trades} trades | WR {a_wr:.0f}% | PF {a_pf:.2f}x")

    # Exit types
    exit_types = results.get("exit_types", {})
    if exit_types:
        print("\n  EXIT TYPES:")
        for etype, stats in sorted(exit_types.items(), key=lambda x: -x[1].get("trades", 0) if isinstance(x[1], dict) else -x[1]):
            if isinstance(stats, dict):
                trades = stats.get("trades", 0)
                if trades > 0:
                    wr = stats.get("win_rate", 0)
                    pnl = stats.get("pnl", 0)
                    print(f"    {etype}: {trades} trades | WR {wr:.0%} | PnL ${pnl:+,.2f}")
            elif stats > 0:
                print(f"    {etype}: {stats}")

    # Quant risk metrics (Sharpe, Sortino, Calmar, etc.)
    risk = results.get("risk_metrics", {})
    if risk:
        print("\n  RISK METRICS:")
        print(f"    Sharpe Ratio:    {risk.get('sharpe', 0):+.2f}")
        print(f"    Sortino Ratio:   {risk.get('sortino', 0):+.2f}")
        print(f"    Calmar Ratio:    {risk.get('calmar', 0):+.2f}")
        print(f"    Recovery Factor: {risk.get('recovery_factor', 0):+.2f}")
        print(f"    Time in Market:  {risk.get('time_in_market_pct', 0):.1f}%%")
        ann_ret = risk.get("annualized_return_pct", 0)
        print(f"    Ann. Return:     {ann_ret:+.1f}%%")

    # Signal funnel (shows where signals get filtered)
    funnel = results.get("signal_funnel", {})
    if funnel:
        print("\n  SIGNAL FUNNEL:")
        for key in ("total", "signal", "no_signal", "cb_blocked", "regime_blocked",
                     "llm_approved", "llm_vetoed"):
            val = funnel.get(key, 0)
            if val > 0:
                print(f"    {key:>16}: {val}")

    # By-regime performance
    by_regime = results.get("by_regime", {})
    if by_regime:
        print("\n  BY REGIME:")
        for regime, data in sorted(by_regime.items()):
            r_trades = data.get("trades", 0)
            r_wr = data.get("win_rate", 0)
            r_pnl = data.get("net_pnl", data.get("pnl", 0))
            if r_trades > 0:
                print(f"    {regime:>16}: {r_trades} trades | WR {r_wr:.0f}%% | PnL ${r_pnl:+,.2f}")

    # Costs breakdown
    costs = results.get("costs", {})
    if costs:
        total_fees = costs.get("total_fees", 0)
        total_funding = costs.get("total_funding", 0)
        total_slippage = costs.get("total_slippage", 0)
        if total_fees or total_funding or total_slippage:
            print(f"\n  COSTS:")
            print(f"    Fees:     ${total_fees:,.2f}")
            print(f"    Funding:  ${total_funding:,.2f}")
            print(f"    Slippage: ${total_slippage:,.2f}")

    # Leverage stats
    lev = results.get("leverage_stats", {})
    if lev:
        avg_lev = lev.get("avg_leverage", 0)
        max_lev = lev.get("max_leverage", 0)
        if avg_lev:
            print(f"\n  LEVERAGE: avg {avg_lev:.1f}x | max {max_lev:.1f}x")

    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    main()
