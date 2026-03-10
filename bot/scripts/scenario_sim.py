"""
Scenario simulation: stress test the bot on synthetic price patterns.

Simulates:
1. Flash crash (sudden 10-15% drop)
2. Volatility spike (ATR triples)
3. Liquidity drought (volume drops 90%)
4. TP1->SL stress (price hits TP1 then reverses to SL)

Usage:
    python -m scripts.scenario_sim
"""

import csv
import logging
import os
import sys
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from execution.position_manager import PositionManager
from execution.risk import RiskManager, CircuitBreaker
from multi_strategy_main import get_tp1_close_pct

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("scenario_sim")


def _generate_base_candles(n: int = 200, start_price: float = 100.0) -> pd.DataFrame:
    """Generate realistic-ish OHLCV candles with random walk."""
    np.random.seed(42)
    prices = [start_price]
    for _ in range(n - 1):
        change = np.random.normal(0, 0.005) * prices[-1]
        prices.append(max(prices[-1] + change, 1.0))

    rows = []
    for i, c in enumerate(prices):
        h = c * (1 + abs(np.random.normal(0, 0.003)))
        l = c * (1 - abs(np.random.normal(0, 0.003)))
        o = prices[i - 1] if i > 0 else c
        v = abs(np.random.normal(1e6, 2e5))
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": v})

    df = pd.DataFrame(rows)
    df["time"] = pd.date_range("2025-01-01", periods=n, freq="1h", tz="UTC")
    return df


def _run_scenario(name: str, candles: pd.DataFrame, positions_setup: dict) -> dict:
    """Run a scenario and return results."""
    pos_mgr = PositionManager(taker_fee_bps=4, enable_trailing=True, trailing_atr_mult=1.5)
    risk_mgr = RiskManager(starting_equity=10000, risk_per_trade=0.015,
                           circuit_breaker=CircuitBreaker())

    # Open position
    entry = float(candles["close"].iloc[50])
    atr = float(candles["close"].rolling(14).std().iloc[50]) * 1.5
    sl_dist = atr * 1.5
    side = positions_setup.get("side", "LONG")

    if side == "LONG":
        sl = entry - sl_dist
        tp1 = entry + sl_dist * 1.5
        tp2 = entry + sl_dist * 3.0
    else:
        sl = entry + sl_dist
        tp1 = entry - sl_dist * 1.5
        tp2 = entry - sl_dist * 3.0

    qty = risk_mgr.calculate_qty(entry, sl, leverage=5.0, risk_multiplier=1.0)
    tp1_pct = get_tp1_close_pct(75.0)

    pos_mgr.open_position(
        symbol="TEST", side=side, entry=entry, qty=qty,
        sl=sl, tp1=tp1, tp2=tp2, atr=atr,
        leverage=5.0, strategy="test", confidence=75.0,
        tp1_close_pct=tp1_pct,
    )

    # Walk through candles
    events = []
    for i in range(51, len(candles)):
        price = float(candles["close"].iloc[i])
        evts = pos_mgr.update_price("TEST", price)
        for e in evts:
            risk_mgr.update_equity(e.pnl - e.fee)
            events.append(e)

    return {
        "scenario": name,
        "trades": len(events),
        "final_equity": risk_mgr.equity,
        "pnl": risk_mgr.equity - 10000,
        "events": [f"{e.action} @ {e.price:.2f} PnL={e.pnl:+.2f}" for e in events],
    }


def scenario_flash_crash():
    """Sudden 12% drop at bar 60."""
    df = _generate_base_candles()
    base = float(df["close"].iloc[59])
    for i in range(60, 65):
        drop = 0.97 ** (i - 59)
        df.loc[i, "close"] = base * drop
        df.loc[i, "low"] = base * drop * 0.99
        df.loc[i, "high"] = base * drop * 1.005
    # Partial recovery
    bottom = float(df["close"].iloc[64])
    for i in range(65, 75):
        df.loc[i, "close"] = bottom * (1 + (i - 64) * 0.003)
    return _run_scenario("flash_crash", df, {"side": "LONG"})


def scenario_volatility_spike():
    """ATR triples from bar 55-75."""
    df = _generate_base_candles()
    for i in range(55, 75):
        c = float(df["close"].iloc[i])
        swing = c * 0.015 * np.random.choice([-1, 1])
        df.loc[i, "close"] = c + swing
        df.loc[i, "high"] = c + abs(swing) * 1.5
        df.loc[i, "low"] = c - abs(swing) * 1.5
    return _run_scenario("volatility_spike", df, {"side": "LONG"})


def scenario_liquidity_drought():
    """Volume drops 90% from bar 55-80."""
    df = _generate_base_candles()
    for i in range(55, 80):
        df.loc[i, "volume"] = float(df["volume"].iloc[i]) * 0.1
    return _run_scenario("liquidity_drought", df, {"side": "LONG"})


def scenario_tp1_then_sl():
    """Price hits TP1 zone then reverses all the way to original SL."""
    df = _generate_base_candles()
    base = float(df["close"].iloc[50])
    atr = float(df["close"].rolling(14).std().iloc[50]) * 1.5
    tp1_level = base + atr * 1.5 * 1.5

    # Rise to TP1
    for i in range(51, 60):
        df.loc[i, "close"] = base + (tp1_level - base) * (i - 50) / 9
        df.loc[i, "high"] = df.loc[i, "close"] * 1.002
    # Sharp reversal
    peak = float(df["close"].iloc[59])
    for i in range(60, 80):
        df.loc[i, "close"] = peak - (peak - base) * (i - 59) / 15
        df.loc[i, "low"] = df.loc[i, "close"] * 0.998
    return _run_scenario("tp1_then_sl_stress", df, {"side": "LONG"})


def main():
    results = [
        scenario_flash_crash(),
        scenario_volatility_spike(),
        scenario_liquidity_drought(),
        scenario_tp1_then_sl(),
    ]

    out_dir = os.path.join("data", "backtest")
    os.makedirs(out_dir, exist_ok=True)

    logger.info("=" * 60)
    logger.info("SCENARIO SIMULATION RESULTS")
    logger.info("=" * 60)
    for r in results:
        logger.info(f"\n{r['scenario']}:")
        logger.info(f"  Trades: {r['trades']}")
        logger.info(f"  Final equity: ${r['final_equity']:,.2f}")
        logger.info(f"  PnL: ${r['pnl']:+,.2f}")
        for e in r["events"]:
            logger.info(f"    {e}")

    # Save metrics
    metrics = {r["scenario"]: {"pnl": r["pnl"], "trades": r["trades"],
                                "final_equity": r["final_equity"]}
               for r in results}
    import json
    with open(os.path.join(out_dir, "scenario_metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)


if __name__ == "__main__":
    main()
