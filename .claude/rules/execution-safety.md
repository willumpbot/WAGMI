# Execution & Safety Rules

## Critical Safety Systems
These files protect real money. Modifications require extra care:

### Circuit Breakers (`bot/execution/risk.py`)
- Daily loss limit: stops trading if losses exceed % of CURRENT equity
- Consecutive loss streak: pauses after N losses in a row
- NEVER weaken these without explicit user approval
- NEVER calculate loss % against peak equity (use current)

### Position Sizing (`bot/execution/leverage.py`)
- Leverage tiers based on confidence + strategy agreement
- Liquidation price calculation uses Hyperliquid's variable maintenance margins
- NEVER allow near-zero stop widths to pass through (creates infinite leverage)
- Maximum leverage is capped in `trading_config.py`

### Risk Gating (`bot/core/signal_pipeline.py`)
- 6-stage sequential filter: validity → circuit breaker → position limits → leverage → liquidation → sizing
- A signal must pass ALL 6 gates to become a trade
- NEVER skip or reorder gates

### Ops Guard (`bot/execution/ops_guard.py`)
- Prevents dangerous operations (duplicate positions, oversized trades)
- NEVER disable in production

## Position Manager (`bot/execution/position_manager.py`)
- State machine: IDLE → OPEN → TP1_HIT → TRAILING → CLOSED
- Trade profiles: SCALP / MEDIUM / TREND / REGIME
- NEVER modify state machine transitions without understanding downstream effects
- Trailing stop logic is progressive — don't simplify to fixed trailing

## Rules
- ALWAYS test with paper trading before any execution change
- NEVER modify risk limits without user confirmation
- Signal objects must be DEEP COPIED before mutation (ensemble.py bug: in-place modification)
- Exchange API calls must have retry logic with exponential backoff
- On startup, reconcile in-memory positions with exchange state
