#!/bin/bash
# Quick state check script — run on either machine to get oriented fast
# Usage: bash coordination/check_state.sh

cd "$(dirname "$0")/.." || exit 1

echo "=============================================="
echo "  WAGMI State Check — $(date -u +"%Y-%m-%d %H:%M UTC")"
echo "=============================================="
echo

echo "--- BRANCH + REMOTE ---"
git rev-parse --abbrev-ref HEAD
git fetch origin historical-import-2026-05-30 2>&1 | tail -1
echo

echo "--- LATEST COMMITS (origin/historical-import) ---"
git log --oneline origin/historical-import-2026-05-30 -10
echo

echo "--- BOT PROCESS ---"
if command -v tasklist >/dev/null 2>&1; then
    tasklist 2>&1 | grep -i python.exe
else
    ps -ef | grep -E "python.*run.py" | grep -v grep
fi
echo

echo "--- EQUITY ---"
cat bot/data/risk_equity_state.json 2>/dev/null
echo

echo "--- POSITIONS ---"
python -c "
import json
try:
    d = json.load(open('bot/data/position_state.json'))
    print(f'count={d.get(\"position_count\")} saved={d.get(\"saved_at\")}')
    for s, p in d.get('positions', {}).items():
        print(f'  {s} {p.get(\"side\")} entry={p.get(\"entry\")} qty={p.get(\"qty\")} SL={p.get(\"sl\")} TP1={p.get(\"tp1\")} state={p.get(\"state\")}')
except Exception as e:
    print(f'(could not read position_state: {e})')
"
echo

echo "--- LEDGER ---"
echo "Total rows: $(wc -l < bot/data/trade_ledger.csv)"
echo "Last 3 trades:"
tail -3 bot/data/trade_ledger.csv | awk -F',' '{printf "  %s %s exit=%s pnl=%s eq=%s\n", $3, $4, $14, $21, $22}'
echo

echo "--- LATEST LOG ENTRY ---"
ls -t bot/logs/bot_2026*.log 2>/dev/null | head -1 | xargs tail -1
echo

echo "--- COLLECTOR DATA (alpha ops freshness) ---"
if [ -f bot/data/funding_oi_history.jsonl ]; then
    echo "Records: $(wc -l < bot/data/funding_oi_history.jsonl)"
    echo "Last tick: $(tail -1 bot/data/funding_oi_history.jsonl | python -c "import json,sys; r=json.loads(sys.stdin.read()); print(f'{r[\"symbol\"]} @ {r[\"price\"]} ts={r[\"timestamp\"]}')")"
else
    echo "(no collector data yet — start with: cd bot && python tools/funding_oi_collector.py &)"
fi
echo

echo "--- WATCHDOG STALLS LAST HOUR ---"
HOUR=$(date -u +"%H")
grep "WATCHDOG.*STALL" bot/logs/bot_$(date -u +"%Y%m%d").log 2>/dev/null | grep "T${HOUR}:" | tail -3
echo

echo "--- RECENT HANDSHAKE TAIL (40 lines) ---"
tail -40 coordination/handshake.md
echo

echo "=============================================="
echo "  Done. See LAPTOP_BRIEFING.md for full context."
echo "=============================================="
