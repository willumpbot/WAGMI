# /paper-status — Paper Trading Session Status

## Description
Comprehensive real-time status of the current paper trading session. Shows signal activity, gate rejection breakdown, win rate, drawdown, and how close the system is to passing all go-live gates. Use this to decide whether to keep running, tune parameters, or stop.

## Arguments
- `$ARGUMENTS` — Optional: "quick" (summary only), "gates" (go-live gate status), "rejections" (gate rejection deep-dive), "signals" (near-miss signal analysis)

## Workflow

### 1. Session Overview
Read `bot/data/heartbeat.json`:
- Is the bot currently running? Last heartbeat age?
- Session uptime, tick count, loop duration

Query SQLite (`bot/ml_data/bot.db`):
```python
import sys; sys.path.insert(0, 'bot')
from data import db
summary = db.get_daily_summary()
equity = db.get_equity_curve(days=1)
```
- Closed trades today: count, wins, losses, win rate, net PnL
- Open positions: count, unrealized PnL
- Session start equity vs current equity

### 2. Signal Activity (Last 1 Hour)
Query recent signals and rejections:
```python
from data import db
signals_1h = db.get_signal_rejections(hours=1)
rejection_summary = db.get_rejection_summary(hours=1)
signals_generated = db.get_signals_today()
```
Show:
- Signals generated in last 1h vs rejected
- **Gate rejection breakdown** (sorted by count):
  - `validity`: structurally invalid signals (bad R:R, stop width)
  - `rr_floor`: R:R too low
  - `fee_drag`: fees too high relative to stop width
  - `ev_floor`: expected value too low
  - `circuit_breaker`: trading halted
  - `max_positions`: portfolio full
  - `correlation`: correlated positions
  - `leverage` / `leverage_gate`: below leverage floor
  - `lev_ev_floor`: EV too low for the leverage level
  - `liquidation`: SL beyond liquidation price
  - `sizing`: position size rounds to zero

- **Near-miss signals** (high confidence ≥ 65% that were rejected):
  - Top 3 most recent, with: symbol, strategy, confidence, gate blocked, reason
  - These are the most actionable — if you see many high-conf signals blocked by the same gate, that gate may be too tight

### 3. Win Rate & Drawdown
```python
perf = db.get_signal_performance(days=7)
```
Show:
- Last 7d: total trades, win rate, avg PnL, best/worst strategy
- Today: trades, win rate, PnL
- Session max drawdown vs circuit breaker limit
- Consecutive loss streak (from heartbeat or risk_mgr state)
- Strategy breakdown: which strategies are contributing to wins vs losses

### 4. Go-Live Gate Status
Read `bot/validation/go_live_gate.py` — evaluate all 5 gates against current data:
```python
from validation.go_live_gate import GoLiveGate
gate = GoLiveGate()
result = gate.evaluate()
```
Show each gate:
```
Go-Live Readiness: 2/5 gates passing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Gate 1 — Walk-forward ratio > 0.7:  0.65 ❌ (need +0.05)
Gate 2 — Net PnL > $0 (30d):       +$234 ✅
Gate 3 — Max drawdown < 15%:        8.2% ✅
Gate 4 — All factor ICs > 0 (30d):  IC=-0.02 ❌ (momentum factor negative)
Gate 5 — Sharpe ratio > 1.0:        0.8 ❌ (need +0.2)
```
For each failing gate, show what it would take to pass.

### 5. Regime & Strategy Alignment
Show:
- Current detected regime (from last tick's regime cache or heartbeat.json)
- Strategies enabled in current regime (from STRATEGY_REGIME_FIT)
- Which strategies are generating signals vs staying quiet
- Regime history (last 24h): is the bot stuck in one regime or rotating?

### 6. Paper Trading Checkpoint History
If `bot/monitoring/paper_validator.py` has run checkpoints, show:
- Last N checkpoints (from health_events table or log)
- Any warnings that were fired
- Trend: are things improving or degrading?

### 7. Recommendation
Based on all the above, give one of:

**CONTINUE** — Everything looks healthy, keep running
- Win rate trending up or stable
- No gates overly restrictive
- Drawdown under control

**TUNE** — Running but needs attention
- Specify which parameter to adjust:
  - If `fee_drag` gate dominant: `min_signal_rr` or `taker_fee_bps` tuning
  - If `ev_floor` gate dominant: `min_signal_ev` may be too high
  - If `leverage_gate` dominant: `min_leverage_entry_gate` threshold
  - If `circuit_breaker` dominant: check daily loss limit vs volatility
- Explain expected impact of each adjustment

**STOP & REVIEW** — Issues requiring investigation
- Win rate < 40% over 15+ trades → potential signal quality issue
- Drawdown > 12% → approaching circuit breaker threshold
- 0 signals in last 2h → data feed or strategy issue
- Go-live gates trending worse → don't proceed to live

## Output Format
```
PAPER TRADING STATUS — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Session:   Running 6h 42m | Tick #892 | Loop: 38s avg
Equity:    $10,234 (+2.3%) | DD: 1.8% | CB: OK
Trades:    12 total | 8W/4L (66.7%) | Net PnL: +$234

SIGNAL ACTIVITY (Last 1h)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Generated: 47 | Passed gates: 3 | Rejected: 44 (93.6%)
Rejection breakdown:
  fee_drag:      22 (50%)  ← HIGH — stops may be too tight
  ev_floor:       8 (18%)
  rr_floor:       7 (16%)
  circuit_breaker: 7 (16%)

Near-miss (high-conf rejected):
  BTC BUY 78.2% — blocked by fee_drag (fd=24%, stop=0.31%)
  SOL BUY 71.4% — blocked by ev_floor (ev=0.08 < 0.10)
  HYPE BUY 67.1% — blocked by fee_drag (fd=22%, stop=0.33%)

GO-LIVE GATES: 3/5 passing
  WF ratio: 0.78 ✅  |  PnL: +$234 ✅  |  DD: 1.8% ✅
  Factor IC: -0.01 ❌  |  Sharpe: 0.92 ❌

RECOMMENDATION: TUNE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
fee_drag gate is dominant (50% of rejections). Consider:
  → Many near-misses are high-confidence BTC/SOL longs with tight stops
  → Current min_leverage_entry_gate=1.2x may be too aggressive for low-vol regimes
  → Consider: reduce min_signal_ev to 0.08, or use /config-audit to review fee settings
```
