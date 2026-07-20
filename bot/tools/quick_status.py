"""30-second status dashboard. Run: python tools/quick_status.py"""
import csv, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

os.chdir(Path(__file__).parent.parent)
sys.path.insert(0, str(Path(__file__).parent.parent))

# EPOCH_FENCE headline (measurement-integrity, Phase 0): canonical epoch-
# fenced run stats + derived equity, replacing the old "Lifetime" sum (which
# had no TEST-row filter at all) and the peak_equity+daily_pnl equity guess
# below (a THIRD, independently-drifting equity derivation).
try:
    from data.trade_source import get_run_stats
    _rs = get_run_stats(epoch=True)
    if _rs["epoch_id"] or _rs["epoch_start"]:
        print(f"Epoch:        {_rs['epoch_id'] or _rs['epoch_start'][:19]}")
    if _rs["derived_equity"] is not None:
        print(f"Equity (derived): ${_rs['derived_equity']:.2f}")
    print(f"Run trades:   {_rs['n']}")
    if _rs["n"]:
        print(f"Run WR:       {_rs['wr']:.1f}%")
    print(f"Run net PnL:  ${_rs['net']:+.2f}")
except Exception as e:
    print(f"Epoch stats unavailable: {e}")

print()

# Equity + CB state (accumulator cross-check — see Equity (derived) above)
try:
    cb = json.load(open("data/circuit_breaker_state.json"))
    print(f"Equity (CB accumulator): ${cb.get('peak_equity', 0) + cb.get('daily_pnl', 0):.2f}")
    print(f"Daily PnL:   ${cb.get('daily_pnl', 0):+.2f}")
    print(f"CB tripped:  {'YES' if cb.get('tripped') else 'no'}")
    print(f"Consec loss: {cb.get('consecutive_losses', 0)}")
    print(f"Last saved:  {cb.get('saved_at', '?')[:19]}")
except: print("CB state unavailable")

print()

# Trade count (lifetime, all-time — distinct from the epoch-fenced Run
# numbers above; kept for continuity but no longer the headline).
try:
    trades = list(csv.DictReader(open("data/trade_ledger.csv")))
    print(f"Total trades (lifetime, unfiltered): {len(trades)}")

    # Last 5 trades
    print(f"\nLast 5 trades:")
    for t in trades[-5:]:
        sym = t['symbol']
        pnl = float(t.get('net_pnl', 0))
        w = 'W' if pnl > 0 else 'L'
        print(f"  {w} {sym:5s} ${pnl:+.2f}")
except: print("Trade ledger unavailable")

print()

# LLM status
try:
    cost = json.load(open("data/llm/cost_tracker.json"))
    print(f"LLM calls today: {cost.get('calls', 0)}")
    print(f"LLM spend today: ${cost.get('spend', 0):.2f}")
except: print("LLM: offline (no credits)")

print()
print("Bot: check if python.exe is running in task manager")
