"""
Quick sim dashboard — run anytime to see current sim performance.

Usage:
    cd bot && python -m tools.sim_dashboard
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main():
    status_path = os.path.join("data", "manual", "sim_status.json")
    trades_path = os.path.join("data", "manual", "sim_trades.jsonl")

    print("=" * 50)
    print("  SNIPER SIM DASHBOARD")
    print("=" * 50)

    # Load status
    if not os.path.exists(status_path):
        print("  No sim data yet. Bot needs to run and accumulate trades.")
        return

    with open(status_path, encoding="utf-8") as f:
        status = json.load(f)

    equity = status.get("current_equity", 100)
    starting = status.get("starting_equity", 100)
    total = status.get("total_trades", 0)
    wins = status.get("wins", 0)
    losses = status.get("losses", 0)
    wr = status.get("win_rate", 0)
    pf = status.get("profit_factor", 0)
    max_dd = status.get("max_drawdown", 0)

    print(f"\n  Equity: ${equity:.2f} (started ${starting:.2f})")
    pnl_pct = (equity - starting) / starting * 100
    print(f"  PnL: ${equity - starting:+.2f} ({pnl_pct:+.1f}%)")
    print(f"  Trades: {total} ({wins}W / {losses}L)")
    print(f"  Win Rate: {wr:.1f}%")
    print(f"  Profit Factor: {pf:.2f}")
    print(f"  Max Drawdown: {max_dd:.1f}%")

    # Open positions
    open_pos = status.get("open_positions", [])
    if open_pos:
        print(f"\n  Open Positions ({len(open_pos)}):")
        for p in open_pos:
            age_min = 0
            if p.get("opened_at"):
                try:
                    opened = datetime.fromisoformat(p["opened_at_iso"]) if "opened_at_iso" in p else datetime.fromtimestamp(p["opened_at"], tz=timezone.utc)
                    age_min = (datetime.now(timezone.utc) - opened).total_seconds() / 60
                except Exception:
                    pass
            print(f"    {p.get('trade_id','?')} {p.get('symbol','?')} {p.get('side','?')} "
                  f"@ ${p.get('entry',0):.2f} {p.get('leverage',0):.0f}x "
                  f"({age_min:.0f}min)")

    # By symbol breakdown
    by_sym = status.get("by_symbol", {})
    if by_sym:
        print(f"\n  By Symbol:")
        for sym, data in by_sym.items():
            print(f"    {sym}: {data.get('trades',0)} trades, "
                  f"WR={data.get('win_rate',0):.0f}%, "
                  f"PnL=${data.get('pnl',0):.2f}")

    # Recent trades
    if os.path.exists(trades_path):
        trades = []
        with open(trades_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    trades.append(json.loads(line))
                except Exception:
                    pass

        if trades:
            print(f"\n  Recent Trades (last 5):")
            for t in trades[-5:]:
                result = t.get("result", "?")
                emoji = "W" if result == "WIN" else "L" if result == "LOSS" else "TS"
                print(f"    {emoji} {t.get('symbol','?')} {t.get('side','?')} "
                      f"PnL=${t.get('pnl_usd',0):+.2f} "
                      f"({t.get('hold_time_hours',0):.1f}h)")

    # Go-live readiness
    print(f"\n{'=' * 50}")
    print("  GO-LIVE READINESS")
    print(f"{'=' * 50}")

    if total >= 10 and wr >= 55:
        print("  STATUS: READY FOR MANUAL TRADING")
        print(f"  {total} trades at {wr:.0f}% WR exceeds minimum threshold")
    elif total >= 5 and wr >= 50:
        print("  STATUS: PROMISING — keep accumulating")
        print(f"  {total} trades at {wr:.0f}% WR, need 10+ for confidence")
    elif total > 0:
        print(f"  STATUS: EARLY — only {total} trades, need more data")
    else:
        print("  STATUS: WAITING — no closed trades yet")
        print("  Bot is running, sim is tracking. Check back in a few hours.")

    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
