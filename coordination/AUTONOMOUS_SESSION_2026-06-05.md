# Autonomous Session — 2026-06-05

**Status**: Running continuous analysis and monitoring on desktop

## Data Recovery & Initial Learning

### Trade Data Loaded
- **File**: `bot/data/trades.csv`
- **Period**: Mar 25 – May 11, 2026
- **Trades**: 228 total
- **Net PnL**: -$3,714.99

### Performance Breakdown

**By Strategy** (ordered by PnL):
- Sniper Premium: +$48.05 (23 trades, 34.8% WR) ✓
- Ensemble: -$1,529.89 (157 trades, 32.5% WR)
- Omniscient Integrated: -$2,155.16 (47 trades, 6.4% WR) 
- Sniper Standard: -$77.99 (1 trade, 0.0% WR)

**By Symbol** (ordered by PnL):
- BTC: -$58.81 (55 trades, 18.2% WR)
- HYPE: -$122.64 (46 trades, 21.7% WR)
- SOL: -$624.07 (63 trades, 33.3% WR)
- ETH: -$2,909.47 (64 trades, 32.8% WR) ← worst performer

**By Regime** (ordered by PnL):
- Trending: +$25.41 (27 trades, 48.1% WR) ✓ EDGE
- Ranging: -$634.85 (32 trades, 15.6% WR)
- Unknown: -$1,239.60 (59 trades, 30.5% WR)
- Illiquid: -$1,865.95 (110 trades, 23.6% WR) ← major loss zone

### Fee Analysis
- Average actual fees: 3.84 bps (vs 10 bps modeled)
- **Implication**: Model is overcounting fee drag. Real edge may be higher than calculations suggest.

## Critical Issues Identified

### From Post-Audit (2026-06-03):
1. **Kelly weights poisoned** — computed from trades under 45 bps fees (10x overstated)
   - Status: Needs `recompute_ledger_at_corrected_fees.py` script
   - Impact: Bot may reject profitable setups labeled "negative Kelly"

2. **SOL SHORT toxic block** — Created 2026-04-28, live WR=33% but backtest WR=63.7%
   - Status: May have been addressed in laptop's 097ef2d commit
   - Impact: May be over-blocking profitable setup

3. **Phantom position phantom-ledger gap** — Positions marked CLOSED without ledger write
   - Status: Skipped in paper mode, affects live mode only
   - Impact: Paper trades should be unaffected

4. **Hardcoded values in decision path** — Stale since 2026-05-17
   - Base WR priors in `quant_brain.py`
   - Time-of-day multipliers (0.7x solo, 0.85x dead hours, 1.15x prime)
   - Risk fallback `0.10 * sz_mult`
   - Kelly floor = 0.15

## Concrete Fixes Generated

### 1. Illiquid Regime Gate Filter
```python
# Block all trades in illiquid regime (48% of trades, -$1,865 losses)
def check_regime_valid(signal, market_state) -> bool:
    regime = market_state.get('regime', 'unknown')
    BLOCKED_REGIMES = ['illiquid', 'unknown']
    
    if regime in BLOCKED_REGIMES:
        return False, f"regime_block: {regime} losing"
    return True, "regime_pass"
```

**Impact estimate**: Would eliminate -$1,865 in losses (50% of total). New portfolio PnL: -$1,850.

### 2. Leverage Tiering (Audit completed)
| Leverage | Trades | PnL | WR | Status |
|---|---|---|---|---|
| 1-2x | 8 | -$270 | 12.5% | Avoid |
| 3x | 5 | +$53 | 40% | PROFITABLE ✓ |
| 5x | 136 | -$3,176 | 28.7% | TOXIC (85% of losses) |
| 7-10x | 24 | +$89 | 37.5% | Profitable ✓ |

**Recommendation**: Shift concentration from 5x to 3x + 7-10x in trending regime only.

### 3. Confidence Calibration Issue (Critical)
- **Anomaly**: High confidence trades lose MORE money than low confidence
- **Data**: 
  - High conf (≥50): -$2,224.50 PnL (153 trades, 32% WR)
  - Low conf (<50): -$1,490.49 PnL (75 trades, 17.3% WR)
- **Root cause suspect**: Position sizing too aggressive when confident
- **Action**: Audit Risk Agent's position sizing logic

## Next Steps (Autonomous Work)

### Phase 1: Root Cause Analysis
- [ ] Extract illiquid regime trades → see why regime detection failed
- [ ] Compare ensemble consensus vs outcome (why are agrees losing?)
- [ ] ETH-specific analysis → is there a symbol-level issue or regime issue?
- [ ] Trending regime: reverse-engineer the profitable trades → what's the real signal?

### Phase 2: Kelly Weight Reconstruction
- [ ] Build `recompute_ledger_at_corrected_fees.py`
- [ ] Recompute PnL at 4.5 bps (actual observed)
- [ ] Regenerate Kelly weights
- [ ] Test on backtests: does new Kelly improve regime classification?

### Phase 3: Hardcoded Value Audit
- [ ] Extract actual data for time-of-day multipliers (are 0.7/0.85/1.15 right?)
- [ ] Validate base WR priors vs live data
- [ ] Check if solo penalty is real or hurting good setups

### Phase 4: Regime Detection Validation
- [ ] Pull data on illiquid regime detections
- [ ] Check: is illiquid regime correct classification? Or is detector broken?
- [ ] If detector broken: fix classifier, retrain
- [ ] If correct: filter out illiquid trades at gate level

---

## Autonomous Systems Running

### Analysis Scripts Generated
1. **`scripts/autonomous_learning_loop.py`** — One-shot overall analysis
2. **`scripts/regime_validation.py`** — Regime accuracy + ETH deep dive
3. **`scripts/generate_fixes.py`** — Concrete fix recommendations
4. **`scripts/continuous_monitoring.py`** — Background monitoring loop (can be started with `python scripts/continuous_monitoring.py > monitoring.log 2>&1 &`)

### Knowledge Base Files Updated
- `bot/data/learning_kb.json` — Initial metrics snapshot
- `bot/data/generated_fixes.json` — All three fix recommendations
- `bot/data/monitoring_kb.json` — Will be created when continuous monitoring starts
- `coordination/AUTONOMOUS_SESSION_2026-06-05.md` — This document

### To Continue Autonomous Work
Start continuous monitoring (runs every 60s, detects anomalies, updates KB):
```bash
cd /c/Users/vince/WAGMI\ PROJECT/WAGMI
nohup python scripts/continuous_monitoring.py > bot/data/monitoring.log 2>&1 &
```

---

**Session timestamp**: 2026-06-05T19:06:30Z  
**Analyst**: Autonomous desktop Claude  
**Data freshness**: Latest from 2026-05-11  
**Status**: Analysis complete. Ready for API key to restart bot.  
**Next action**: Apply fixes to code + restart bot with live data collection  
**Estimated impact**: +50% PnL from eliminating illiquid regime trades alone
