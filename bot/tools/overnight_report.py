"""
Overnight Report Generator

Produces a concise summary of what happened since a given timestamp.
Shows: new trades, signals generated/blocked, regime changes, equity changes.

Usage: cd bot && python tools/overnight_report.py [hours_back]
"""

import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

# trade_events.jsonl is ~93-95% fabricated PnL mass unless filtered (pytest
# fixtures, backtest-in-process runs, dormant symbol trials) — see
# core.structured_logging.is_fake_trade_event for the full explanation.
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from core.structured_logging import is_fake_trade_event
except Exception:
    def is_fake_trade_event(evt):  # fail open rather than crash the report
        return False


def generate_report(hours_back=12):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    cutoff_str = cutoff.isoformat()[:19]

    print(f"OVERNIGHT REPORT — Last {hours_back}h")
    print(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    # 1. Trades
    with open("data/trades.csv") as f:
        all_trades = list(csv.DictReader(f))

    new_trades = [t for t in all_trades if t.get("timestamp", "") > cutoff_str]
    total_pnl = sum(float(t.get("pnl", 0) or 0) for t in all_trades)
    new_pnl = sum(float(t.get("pnl", 0) or 0) for t in new_trades)

    print(f"\nTRADES:")
    print(f"  Total: {len(all_trades)} | New: {len(new_trades)} | Equity: ${500 + total_pnl:.2f}")
    if new_trades:
        print(f"  New PnL: ${new_pnl:+.2f}")
        for t in new_trades:
            sym = t.get("symbol", "?")
            side = t.get("side", "?")
            pnl = float(t.get("pnl", 0) or 0)
            regime = t.get("regime", "?")
            conf = float(t.get("confidence", 0) or 0)
            print(f"    {sym:5s} {side:5s} regime={regime:15s} conf={conf:5.1f} pnl=${pnl:+.2f}")
    else:
        print("  No new trades taken.")

    # 2. Signals from trade_events
    events = []
    try:
        with open("data/trade_events.jsonl") as f:
            for line in f.readlines()[-5000:]:
                try:
                    e = json.loads(line.strip())
                    if not is_fake_trade_event(e):
                        events.append(e)
                except:
                    pass
    except:
        pass

    recent_events = [e for e in events if str(e.get("timestamp", "")) > cutoff_str]
    signals = [e for e in recent_events if e.get("event") == "SIGNAL_GENERATED"]
    filtered = [e for e in recent_events if e.get("event") == "SIGNAL_FILTERED"]

    print(f"\nSIGNALS:")
    print(f"  Generated: {len(signals)} | Filtered: {len(filtered)}")

    if signals:
        # Group by symbol+side
        sig_groups = Counter(f"{e.get('symbol', '?')}_{e.get('side', '?')}" for e in signals)
        print("  Signal distribution:")
        for key, count in sig_groups.most_common():
            print(f"    {key}: {count}")

    if filtered:
        # Group by reason
        reasons = Counter()
        for e in filtered:
            reason = str(e.get("reason", ""))
            gate = reason.split("]")[0].replace("[", "") if "]" in reason else reason[:30]
            reasons[gate] += 1
        print("  Rejection reasons:")
        for reason, count in reasons.most_common(8):
            print(f"    {reason}: {count}")

    # 3. Regimes observed
    print(f"\nREGIMES (from log):")
    try:
        regime_log = []
        log_file = f"logs/bot_{datetime.now(timezone.utc).strftime('%Y%m%d')}.log"
        if os.path.exists(log_file):
            with open(log_file, encoding="utf-8", errors="replace") as f:
                for line in f.readlines()[-2000:]:
                    try:
                        e = json.loads(line.strip())
                        if "REGIME" in e.get("msg", "") and e.get("ts", "") > cutoff_str:
                            regime_log.append(e)
                    except:
                        pass

        regime_counts = Counter()
        for e in regime_log:
            msg = e.get("msg", "")
            # Extract symbol and regime
            parts = msg.split("|")
            if len(parts) >= 1:
                sym_regime = parts[0].replace("[REGIME]", "").strip()
                regime_counts[sym_regime] += 1

        for key, count in regime_counts.most_common(12):
            print(f"  {key}: {count}x")
    except:
        print("  (log not available)")

    # 4. CB state
    try:
        with open("data/circuit_breaker_state.json") as f:
            cb = json.load(f)
        print(f"\nCIRCUIT BREAKER:")
        print(f"  Tripped: {cb.get('tripped', False)}")
        print(f"  Daily PnL: ${cb.get('daily_pnl', 0):.2f}")
        print(f"  Consecutive losses: {cb.get('consecutive_losses', 0)}")
        print(f"  Peak equity: ${cb.get('peak_equity', 0):.2f}")
    except:
        pass

    # 5. Current prices
    try:
        import ccxt
        exchange = ccxt.hyperliquid()
        print(f"\nCURRENT PRICES:")
        for sym, base in [("BTC/USDC:USDC", "BTC"), ("SOL/USDC:USDC", "SOL"),
                          ("ETH/USDC:USDC", "ETH"), ("HYPE/USDC:USDC", "HYPE")]:
            t = exchange.fetch_ticker(sym)
            print(f"  {base}: ${t['last']:,.2f}")
    except:
        print("\n  (price fetch failed)")

    print(f"\n{'=' * 60}")
    print("END REPORT")


if __name__ == "__main__":
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    generate_report(hours)
