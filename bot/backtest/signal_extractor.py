"""
Signal Extractor: captures ALL strategy signals from a backtest run.

Hooks into the backtest engine's ensemble to capture:
1. Every individual strategy signal (before consensus)
2. Every ensemble consensus signal (after voting)
3. Every rejection reason
4. What WOULD have happened (counterfactual)

Output: JSON file with full signal + outcome data for analysis.
"""

import json
import logging
import os
from copy import deepcopy
from datetime import datetime, timezone
from typing import Dict, List, Any

import pandas as pd

from backtest.engine import BacktestEngine
from trading_config import TradingConfig, DEFAULT_SYMBOLS

logger = logging.getLogger("bot.backtest.signal_extractor")


def extract_all_signals(
    symbols: List[str],
    days: int = 60,
    equity: float = 500.0,
    output_path: str = "data/extracted_signals.json",
) -> Dict[str, Any]:
    """Run backtest and extract every signal with full context + outcome.

    Returns dict with raw signals, ensemble signals, executed trades, and outcomes.
    """
    config = TradingConfig()
    config.starting_equity = equity

    engine = BacktestEngine(config)

    # We'll collect data by hooking into _execute_signal
    executed_signals = []
    original_execute = engine._execute_signal

    def capture_execute(signal, current_price, sim_dt=None):
        meta = signal.metadata or {}
        sig_data = {
            "symbol": signal.symbol,
            "side": signal.side,
            "confidence": round(signal.confidence, 1),
            "entry": round(signal.entry, 4),
            "sl": round(signal.sl, 4),
            "tp1": round(signal.tp1, 4),
            "tp2": round(signal.tp2, 4),
            "atr": round(signal.atr, 4),
            "strategy": signal.strategy or "",
            "rr_tp1": round(signal.risk_reward_tp1, 2),
            "stop_width_pct": round(signal.stop_width_pct * 100, 3),
            "num_agree": meta.get("num_agree", 1),
            "strategies_agree": meta.get("strategies_agree", []),
            "regime": meta.get("regime", "unknown"),
            "chop_score": round(meta.get("chop_score", 0), 3),
            "ev_per_dollar": round(meta.get("ev_per_dollar", 0) or 0, 4),
            "win_prob": meta.get("win_prob", meta.get("win_prob_deflated")),
            "fee_drag_pct": round(meta.get("fee_drag_pct", 0), 1),
            "sim_time": str(sim_dt)[:19] if sim_dt else "",
            "current_price": round(current_price, 4),
        }
        executed_signals.append(sig_data)
        return original_execute(signal, current_price, sim_dt=sim_dt)

    engine._execute_signal = capture_execute

    # Run the backtest
    report = engine.run(symbols, days)

    # Extract trade events with outcomes from trade_timeline
    events = []
    for e in report.get("trade_timeline", []):
        events.append({
            "symbol": e.get("symbol", ""),
            "side": e.get("side", ""),
            "close_reason": e.get("close_reason", ""),
            "entry": round(e.get("entry", 0), 4),
            "exit": round(e.get("exit", 0), 4),
            "sl": round(e.get("sl", 0), 4),
            "tp1": round(e.get("tp1", 0), 4),
            "pnl": round(e.get("pnl", 0), 2),
            "fee": round(e.get("fee", 0), 2),
            "leverage": e.get("leverage", 1),
            "confidence": round(e.get("confidence", 0), 1),
            "rr_achieved": round(e.get("rr_achieved", 0), 2),
            "duration_h": round(e.get("duration_h", 0), 1),
            "outcome": e.get("outcome", ""),
        })

    # Extract missed trades
    missed = report.get("missed_trades", {})

    result = {
        "config": {
            "symbols": symbols,
            "days": days,
            "equity": equity,
            "risk_per_trade": config.risk_per_trade,
            "time_stop_hours": getattr(config, "time_stop_hours", 12),
            "confidence_floor": getattr(config, "ensemble_confidence_floor", 65),
            "min_votes": config.min_votes_required,
        },
        "summary": {
            "equity_start": equity,
            "equity_end": round(report.get("results", {}).get("equity_final", equity), 2),
            "net_pnl": round(report.get("results", {}).get("net_pnl", 0), 2),
            "positions_opened": report.get("positions", {}).get("opened", 0),
            "win_rate_event": round(report.get("results", {}).get("win_rate_by_event", 0), 1),
            "profit_factor": round(report.get("results", {}).get("profit_factor", 0), 2),
            "sharpe": round(report.get("risk_metrics", {}).get("sharpe", 0), 2),
            "max_drawdown_pct": round(report.get("results", {}).get("max_drawdown_pct", 0), 1),
        },
        "executed_signals": executed_signals,
        "trade_events": events,
        "missed_trade_summary": {
            "total": missed.get("total_missed", 0),
            "would_have_won": missed.get("would_have_won", 0),
            "would_have_lost": missed.get("would_have_lost", 0),
            "gate_accuracy": round(missed.get("overall_gate_accuracy_pct", 0), 1),
            "by_strategy_solo": missed.get("by_strategy_solo", {}),
        },
        "signal_funnel": report.get("signal_funnel", {}),
    }

    # Save to file
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"SIGNAL EXTRACTION COMPLETE")
    print(f"{'='*60}")
    print(f"  Executed signals: {len(executed_signals)}")
    print(f"  Trade events:     {len(events)}")
    print(f"  Net PnL:          ${result['summary']['net_pnl']}")
    print(f"  Win rate:         {result['summary']['win_rate_event']}%")
    print(f"  Profit factor:    {result['summary']['profit_factor']}")
    print(f"  Saved to:         {output_path}")
    print(f"{'='*60}")

    return result


if __name__ == "__main__":
    import sys
    symbols = sys.argv[1].split(",") if len(sys.argv) > 1 else ["BTC", "ETH", "SOL", "HYPE"]
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    extract_all_signals(symbols, days)
