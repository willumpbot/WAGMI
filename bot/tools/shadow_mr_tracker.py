#!/usr/bin/env python3
"""Shadow Mean-Reversion Signal Tracker — forward validation without trading.

Strategy: RSI(14) < 30 + 3 red candles = BUY, RSI(14) > 70 + 3 green candles = SELL
Tracks 1h/2h/4h outcomes for each signal. Logs to data/shadow_mr_signals.jsonl.
"""

import ccxt
import json
import time
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- Config ---
SYMBOLS = ["BTC/USDC:USDC", "ETH/USDC:USDC", "SOL/USDC:USDC", "HYPE/USDC:USDC"]
CHECK_INTERVAL = 300  # 5 minutes
RSI_PERIOD = 14
RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
CONSEC_BARS = 3
OUTCOME_HOURS = [1, 2, 4]

# --- Paths ---
BOT_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BOT_DIR / "data" / "shadow_mr_signals.jsonl"
LOG_FILE = BOT_DIR / "logs" / "shadow_mr.log"

# --- Logging ---
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("shadow_mr")


def calc_rsi(closes: list[float], period: int = 14) -> float:
    """RSI from close prices. Returns 50 if insufficient data."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    recent = deltas[-(period):]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def count_consecutive_direction(candles: list) -> tuple[int, str]:
    """Count consecutive same-direction candles from most recent back.
    Returns (count, 'red'|'green')."""
    if not candles:
        return 0, "none"
    direction = "green" if candles[-1][4] >= candles[-1][1] else "red"
    count = 0
    for c in reversed(candles):
        c_dir = "green" if c[4] >= c[1] else "red"
        if c_dir == direction:
            count += 1
        else:
            break
    return count, direction


def fetch_candles(exchange, symbol: str, limit: int = 30) -> list | None:
    """Fetch 1h OHLCV. Returns list or None on error."""
    try:
        return exchange.fetch_ohlcv(symbol, "1h", limit=limit)
    except Exception as e:
        log.warning(f"Fetch failed {symbol}: {e}")
        return None


def check_signals(exchange, active_signals: list[dict]) -> list[dict]:
    """Check all symbols for new MR signals. Returns new signals."""
    new_signals = []
    for symbol in SYMBOLS:
        candles = fetch_candles(exchange, symbol)
        if not candles or len(candles) < RSI_PERIOD + 2:
            continue

        closes = [c[4] for c in candles]
        rsi = calc_rsi(closes, RSI_PERIOD)
        consec, direction = count_consecutive_direction(candles)
        price = closes[-1]
        ts = datetime.now(timezone.utc).isoformat()
        short_sym = symbol.split("/")[0]

        # Check for duplicate — don't re-signal same bar
        last_bar_ts = candles[-1][0]
        already = any(
            s["symbol"] == symbol and s.get("bar_ts") == last_bar_ts
            for s in active_signals
        )
        if already:
            continue

        sig = None
        if rsi < RSI_OVERSOLD and consec >= CONSEC_BARS and direction == "red":
            sig = "BUY"
            log.info(f"SHADOW BUY  {short_sym} @ {price:.2f}  RSI={rsi:.1f}  red_bars={consec}")
        elif rsi > RSI_OVERBOUGHT and consec >= CONSEC_BARS and direction == "green":
            sig = "SELL"
            log.info(f"SHADOW SELL {short_sym} @ {price:.2f}  RSI={rsi:.1f}  green_bars={consec}")

        if sig:
            entry = {
                "signal": sig,
                "symbol": symbol,
                "short_sym": short_sym,
                "price": price,
                "rsi": round(rsi, 2),
                "consec_bars": consec,
                "direction": direction,
                "timestamp": ts,
                "bar_ts": last_bar_ts,
                "entry_time": time.time(),
                "outcomes": {},
            }
            new_signals.append(entry)
            save_signal(entry)
    return new_signals


def check_outcomes(exchange, active_signals: list[dict]) -> list[dict]:
    """Check if any active signals have reached outcome checkpoints."""
    still_active = []
    for sig in active_signals:
        elapsed_h = (time.time() - sig["entry_time"]) / 3600
        all_done = True

        for h in OUTCOME_HOURS:
            key = f"{h}h"
            if key in sig["outcomes"]:
                continue
            if elapsed_h >= h:
                # Fetch current price
                candles = fetch_candles(exchange, sig["symbol"], limit=2)
                if candles and candles[-1]:
                    current = candles[-1][4]
                    pnl_pct = ((current - sig["price"]) / sig["price"]) * 100
                    if sig["signal"] == "SELL":
                        pnl_pct = -pnl_pct
                    sig["outcomes"][key] = {
                        "price": current,
                        "pnl_pct": round(pnl_pct, 3),
                        "checked_at": datetime.now(timezone.utc).isoformat(),
                    }
                    result = "WIN" if pnl_pct > 0 else "LOSS"
                    log.info(
                        f"  {key} outcome {sig['short_sym']} {sig['signal']}: "
                        f"{pnl_pct:+.2f}% ({result})  entry={sig['price']:.2f} now={current:.2f}"
                    )
                    update_signal(sig)
                else:
                    all_done = False
            else:
                all_done = False

        if not all_done:
            still_active.append(sig)
    return still_active


def save_signal(sig: dict):
    """Append signal to JSONL file."""
    with open(DATA_FILE, "a") as f:
        f.write(json.dumps(sig) + "\n")


def update_signal(sig: dict):
    """Rewrite the signal's line in JSONL (match by bar_ts + symbol)."""
    if not DATA_FILE.exists():
        return
    lines = DATA_FILE.read_text().strip().split("\n")
    with open(DATA_FILE, "w") as f:
        for line in lines:
            try:
                obj = json.loads(line)
                if obj["symbol"] == sig["symbol"] and obj["bar_ts"] == sig["bar_ts"]:
                    f.write(json.dumps(sig) + "\n")
                else:
                    f.write(line + "\n")
            except json.JSONDecodeError:
                f.write(line + "\n")


def print_summary(active_signals: list[dict], total_generated: int):
    """Hourly summary."""
    outcomes_1h = [s for s in active_signals if "1h" in s.get("outcomes", {})]
    # Also count from file
    wins, losses = 0, 0
    if DATA_FILE.exists():
        for line in DATA_FILE.read_text().strip().split("\n"):
            try:
                s = json.loads(line)
                for h in OUTCOME_HOURS:
                    o = s.get("outcomes", {}).get(f"{h}h", {})
                    if o.get("pnl_pct", 0) > 0:
                        wins += 1
                    elif "pnl_pct" in o:
                        losses += 1
            except (json.JSONDecodeError, KeyError):
                pass

    total_outcomes = wins + losses
    wr = (wins / total_outcomes * 100) if total_outcomes > 0 else 0
    log.info(
        f"=== HOURLY SUMMARY === signals_total={total_generated} "
        f"active={len(active_signals)} outcomes={total_outcomes} "
        f"W={wins} L={losses} WR={wr:.0f}%"
    )


def main():
    log.info("Shadow MR Tracker starting — symbols: " + ", ".join(s.split("/")[0] for s in SYMBOLS))
    log.info(f"Strategy: RSI({RSI_PERIOD}) <{RSI_OVERSOLD}/{CONSEC_BARS} red = BUY | "
             f">{RSI_OVERBOUGHT}/{CONSEC_BARS} green = SELL")
    log.info(f"Outcome tracking: {OUTCOME_HOURS}h | Check interval: {CHECK_INTERVAL}s")
    log.info(f"Data file: {DATA_FILE}")

    exchange = ccxt.hyperliquid({"enableRateLimit": True})
    active_signals: list[dict] = []
    total_generated = 0
    last_summary = time.time()

    while True:
        try:
            new = check_signals(exchange, active_signals)
            active_signals.extend(new)
            total_generated += len(new)

            active_signals = check_outcomes(exchange, active_signals)

            # Hourly summary
            if time.time() - last_summary >= 3600:
                print_summary(active_signals, total_generated)
                last_summary = time.time()

        except KeyboardInterrupt:
            log.info("Shutting down — final summary:")
            print_summary(active_signals, total_generated)
            break
        except Exception as e:
            log.error(f"Loop error: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
