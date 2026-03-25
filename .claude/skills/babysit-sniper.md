# /babysit-sniper — Manual Sniper System Overwatch

## Description
Continuous monitoring loop for the manual sniper signal system. Each cycle: checks signal generation, analyzes quality, monitors simulator performance, looks for optimization opportunities, and logs learnings.

## Workflow

### Step 1: System Health Check
```bash
cd bot && python -c "
import json, time, os
from datetime import datetime

h = json.load(open('data/heartbeat.json'))
age = time.time() - h['epoch']
print(f'Bot: {h[\"uptime_s\"]/3600:.1f}h uptime | {h[\"scan_count\"]} scans | \${h[\"equity\"]:,.2f} | {h[\"positions\"]} pos | {h[\"errors\"]} errors | heartbeat {age:.0f}s ago')

sig_path = 'data/manual/sniper_signals.jsonl'
if os.path.exists(sig_path):
    sigs = [json.loads(l) for l in open(sig_path) if l.strip()]
    recent = [s for s in sigs if time.time() - time.mktime(time.strptime(s['timestamp'][:19], '%Y-%m-%dT%H:%M:%S')) < 600]
    print(f'Sniper: {len(sigs)} total | {len(recent)} in last 10min')
    if recent:
        last = recent[-1]
        print(f'  Last: {last[\"tier\"]} {last[\"symbol\"]} {last[\"side\"]} conf={last[\"confidence\"]:.0f}% lev={last[\"leverage\"]}x +\${last[\"pnl_scalp\"]:.2f}')
    tiers = {}
    for s in sigs[-50:]:
        tiers[s['tier']] = tiers.get(s['tier'], 0) + 1
    print(f'  Recent 50 tier mix: {tiers}')

sim_path = 'data/manual/sim_status.json'
if os.path.exists(sim_path):
    sim = json.load(open(sim_path))
    eq = sim.get('current_equity', 100)
    trades = sim.get('total_trades', 0)
    wr = sim.get('win_rate', 0)
    pnl = sim.get('total_pnl', 0)
    dd = sim.get('max_drawdown_pct', 0)
    print(f'Sim: \${eq:.2f} ({trades} trades, {wr:.0f}% WR, \${pnl:+.2f} PnL, {dd:.1f}% max DD)')
else:
    print('Sim: No closed trades yet')
"
```

### Step 2: Signal Quality Analysis
```bash
cd bot && python -c "
import json, os, time
from collections import Counter

path = 'data/logs/signal_outcomes.jsonl'
if not os.path.exists(path):
    print('No signal outcomes yet')
    exit()

lines = open(path).readlines()
recent = [json.loads(l) for l in lines[-50:]]

# Confidence distribution
confs = [s['conf'] for s in recent]
high = sum(1 for c in confs if c >= 80)
sniper = sum(1 for c in confs if c >= 85)
agrees_3 = sum(1 for s in recent if s.get('n_agree', 1) >= 3)
print(f'Last 50 signals: avg conf={sum(confs)/len(confs):.1f}% | {high} above 80% | {sniper} above 85% | {agrees_3} with 3+ agree')

combos = Counter(f'{s[\"sym\"]}_{s[\"side\"]}' for s in recent)
for combo, count in combos.most_common(5):
    avg_c = sum(s['conf'] for s in recent if f'{s[\"sym\"]}_{s[\"side\"]}' == combo) / count
    print(f'  {combo}: {count} signals, avg conf={avg_c:.0f}%')
"
```

### Step 3: Check for Missed Opportunities
Look at signals that were close to sniper threshold but filtered out. If many cluster at 78-80% confidence, consider whether threshold should adjust.

### Step 4: Simulator Performance Review
```bash
cd bot && python -c "
import json, os
sim_trades = 'data/manual/sim_trades.jsonl'
if os.path.exists(sim_trades):
    trades = [json.loads(l) for l in open(sim_trades) if l.strip()]
    closed = [t for t in trades if t.get('status') == 'closed']
    if closed:
        wins = [t for t in closed if t.get('pnl', 0) > 0]
        losses = [t for t in closed if t.get('pnl', 0) <= 0]
        total_pnl = sum(t.get('pnl', 0) for t in closed)
        print(f'Sim trades: {len(closed)} closed (W:{len(wins)} L:{len(losses)})')
        print(f'Total PnL: \${total_pnl:+.2f}')
        if wins:
            print(f'Avg win: \${sum(t[\"pnl\"] for t in wins)/len(wins):.2f}')
        if losses:
            print(f'Avg loss: \${sum(t[\"pnl\"] for t in losses)/len(losses):.2f}')
    else:
        open_trades = [t for t in trades if t.get('status') != 'closed']
        print(f'Sim: {len(open_trades)} open positions, 0 closed yet')
else:
    print('No sim trades yet')
"
```

### Step 5: Run Optimizer Check
```bash
cd bot && python -c "
try:
    from manual.optimizer import SniperOptimizer
    opt = SniperOptimizer()
    quality = opt.analyze_signal_quality()
    print(f'Signal quality: {quality.get(\"signals_per_day\", 0):.1f}/day | noise_ratio={quality.get(\"noise_ratio\", 0):.2f}')
    suggestions = opt.suggest_parameter_changes()
    if suggestions:
        print('Suggestions:')
        for s in suggestions[:3]:
            print(f'  {s.get(\"param\", \"?\")}: {s.get(\"current\", \"?\")} -> {s.get(\"suggested\", \"?\")} ({s.get(\"confidence\", 0):.0f}% confidence)')
    else:
        print('No parameter changes suggested (insufficient data or current config is optimal)')
except Exception as e:
    print(f'Optimizer: {e}')
"
```

### Step 6: Analyze & Act
Based on the data collected:
- If signal quality is degrading: investigate why (market regime change? strategy weight shifts?)
- If simulator is losing: check which setups are failing, consider tightening filters
- If simulator is winning: note the pattern, consider if we should be more aggressive
- If new patterns emerge: update bot/data/manual/TRADING_PLAYBOOK.md
- If optimizer suggests changes: evaluate them against the data, note in findings
- If dedup issues (signal spam): check cooldown settings

### Step 7: Log Findings
If you observe something NEW and actionable, append to `bot/data/manual/SNIPER_LEARNINGS.md`. Categories:
- **Signal quality patterns** (e.g., "HYPE BUY signals cluster at 87% conf during Asian session")
- **Simulator observations** (e.g., "Scalp TP hit 80% of the time within 2 hours")
- **Market regime effects** (e.g., "Low volume periods produce more false signals")
- **Parameter sensitivity** (e.g., "2-agree at 80%+ captures 5x more signals with same WR")
- **Execution insights** (e.g., "Tight stops on HYPE get better leverage but higher SL hit rate")

DO NOT repeat findings already logged. Only add genuinely new observations.
