# Mechanical Bot Integration Guide

Complete guide for wiring mechanical bot instrumentation into multi_strategy_main.py trading loop.

## Overview

The mechanical bot instrumentation system captures comprehensive data about the mechanical system's decision-making without modifying its behavior. All integration points are **additive** (observation only, no behavior changes).

## Integration Points

### 1. Signal Generation (After Ensemble Voting)

**Location**: `multi_strategy_main.py`, after ensemble evaluation

**What happens**: Ensemble generates a signal from multiple strategy votes

**Integration**:
```python
from llm.mechanical_bot_instrumentation import get_mechanical_bot_instrumentation

# After ensemble.evaluate(symbol) returns a signal
if signal_result is not None:
    instr = get_mechanical_bot_instrumentation()

    # Generate unique signal ID
    signal_id = f"{symbol}_{int(time.time() * 1000) % 100000}"

    # Get market context
    regime = snapshot.get("regime", "unknown")
    volatility_pct = snapshot.get("volatility_percentile", 0.0)
    alignment = snapshot.get("alignment_score", 0.0)
    btc_corr = snapshot.get("btc_correlation_1h", 0.0)
    hour = datetime.now().hour

    # Record signal generation
    instr.on_signal_generated(
        signal_id=signal_id,
        symbol=symbol,
        regime=regime,
        volatility_percentile=volatility_pct,
        alignment_score=alignment,
        btc_correlation=btc_corr,
        time_of_day=hour,
        side=signal_result.side,
        confidence=signal_result.confidence,
        num_strategies=len(signal_result.strategy_names),
        strategy_names=signal_result.strategy_names,
        entry_price=signal_result.entry,
        leverage=position_size.leverage if position_size else 1.0,
    )

    # Store signal_id in signal_result for later reference
    signal_result.metadata["mechanical_signal_id"] = signal_id
```

### 2. Market Snapshot Capture

**Location**: `multi_strategy_main.py`, evaluation loop (periodic or on-demand)

**What happens**: Capture complete market intelligence that mechanical bot sees

**Integration**:
```python
# Call this periodically (e.g., every evaluation cycle) or on-demand
def capture_market_context(symbol, snapshot_data):
    from llm.mechanical_bot_instrumentation import get_mechanical_bot_instrumentation
    instr = get_mechanical_bot_instrumentation()

    instr.capture_market_snapshot(
        symbol=symbol,
        current_price=snapshot_data.get("current_price"),
        price_change_1h_pct=snapshot_data.get("price_change_1h_pct", 0.0),
        price_change_24h_pct=snapshot_data.get("price_change_24h_pct", 0.0),
        atr=snapshot_data.get("atr", 0.0),
        volatility_percentile=snapshot_data.get("volatility_percentile", 0.0),
        regime=snapshot_data.get("regime", "unknown"),
        regime_confidence=snapshot_data.get("regime_confidence", 0.0),
        regime_momentum=snapshot_data.get("regime_momentum", None),
        alignment_5m_1h=snapshot_data.get("alignment_5m_1h", 0.0),
        alignment_1h_6h=snapshot_data.get("alignment_1h_6h", 0.0),
        alignment_6h_1d=snapshot_data.get("alignment_6h_1d", 0.0),
        support_level=snapshot_data.get("support_level", None),
        resistance_level=snapshot_data.get("resistance_level", None),
        btc_price=snapshot_data.get("btc_price", None),
        btc_change_1h_pct=snapshot_data.get("btc_change_1h_pct", 0.0),
        correlation_with_btc_1h=snapshot_data.get("btc_correlation_1h", 0.0),
        correlation_with_btc_6h=snapshot_data.get("btc_correlation_6h", 0.0),
        time_of_day=datetime.now().hour,
        day_of_week=datetime.now().weekday(),
        trading_session=get_trading_session(datetime.now().hour),
        rsi_14=snapshot_data.get("rsi_14", None),
        macd_histogram=snapshot_data.get("macd_histogram", None),
        momentum_direction=snapshot_data.get("momentum_direction", None),
        volume_profile=snapshot_data.get("volume_profile", None),
        liquidity_rating=snapshot_data.get("liquidity_rating", 0.0),
    )
```

### 3. Signal Rejection/Filtering

**Location**: `multi_strategy_main.py`, risk gate evaluation

**What happens**: Signal gets rejected at a risk gate

**Integration**:
```python
# After risk gate evaluation, if signal doesn't pass
if not risk_result.passed_all_gates:
    from llm.mechanical_bot_instrumentation import get_mechanical_bot_instrumentation
    instr = get_mechanical_bot_instrumentation()

    signal_id = signal_result.metadata.get("mechanical_signal_id")
    if signal_id:
        instr.on_signal_rejected(
            signal_id=signal_id,
            rejection_reason=risk_result.rejection_reason or "Risk gates",
        )
```

### 4. Position Opening

**Location**: `bot/execution/position_manager.py`, when position transitions from IDLE to OPEN

**What happens**: Mechanical bot opens a position based on signal

**Integration**:
```python
# In position_manager.py, when executing trade
from llm.mechanical_bot_instrumentation import get_mechanical_bot_instrumentation

# After position is successfully opened
instr = get_mechanical_bot_instrumentation()
signal_id = position.metadata.get("mechanical_signal_id")
current_price = get_current_price(symbol)
regime = get_current_regime(symbol)
volatility = get_volatility(symbol)

instr.on_position_opened(
    trade_id=position.trade_id,
    signal_id=signal_id,
    symbol=symbol,
    side=position.side,
    entry_price=position.entry_price,
    current_price=current_price,
    regime=regime,
    volatility=volatility,
    alignment_score=get_alignment_score(symbol),
    initial_confidence=position.confidence,
    strategy_votes=position.num_strategy_votes,
)
```

### 5. Position State Changes

**Location**: `bot/execution/position_manager.py`, state machine transitions

**What happens**: Position moves through phases (TP1 approached, SL hit, etc)

**Integration**:
```python
# In position_manager.py, on every significant price/state change
from llm.mechanical_bot_instrumentation import get_mechanical_bot_instrumentation

instr = get_mechanical_bot_instrumentation()
current_price = get_current_price(symbol)

# Determine current phase
if distance_to_tp1 < 50:  # Within 50% of TP1
    phase = "tp1_approached"
elif distance_to_tp1 < 5:  # Very close to TP1
    phase = "tp1_hit"
elif distance_to_sl < 50:  # Within 50% of SL
    phase = "sl_approached"
elif distance_to_sl < 5:  # Very close to SL
    phase = "sl_hit"
elif in_trailing_mode:
    phase = "trailing"
else:
    phase = "position_open"

# Calculate PnL
position_pnl = calculate_pnl(entry_price, current_price, position.side, position.size)
position_pnl_pct = (position_pnl / initial_risk) * 100

instr.on_position_state_change(
    trade_id=position.trade_id,
    phase=phase,
    current_price=current_price,
    entry_price=position.entry_price,
    regime=get_current_regime(symbol),
    volatility=get_volatility(symbol),
    alignment_score=get_alignment_score(symbol),
    position_pnl=position_pnl,
    position_pnl_pct=position_pnl_pct,
    distance_to_tp1_pct=distance_to_tp1,
    distance_to_sl_pct=distance_to_sl,
    bot_confidence=get_bot_confidence(position),
    reasoning=get_decision_reason(position),
    signals_still_agreeing=check_signals_still_agree(symbol),
    num_strategies_voting=count_voting_strategies(symbol),
    events=[f"price_at_{current_price:.2f}", f"pnl_{position_pnl_pct:.1f}%"],
)
```

### 6. Position Closing

**Location**: `bot/execution/position_manager.py`, when position closes

**What happens**: Position transitions to CLOSED state

**Integration**:
```python
# In position_manager.py, when position closes
from llm.mechanical_bot_instrumentation import get_mechanical_bot_instrumentation

instr = get_mechanical_bot_instrumentation()
signal_id = position.metadata.get("mechanical_signal_id")
exit_price = position.exit_price
final_pnl = position.realized_pnl
final_pnl_pct = (final_pnl / position.risk_amount) * 100

# Determine exit reason
exit_reason = "unknown"
if position_closed_at_tp1:
    exit_reason = "tp1_hit"
elif position_closed_at_sl:
    exit_reason = "sl_hit"
elif manual_close:
    exit_reason = "manual"
elif trailing_exit:
    exit_reason = "trailing"

instr.on_position_closed(
    trade_id=position.trade_id,
    signal_id=signal_id,
    exit_price=exit_price,
    exit_reason=exit_reason,
    pnl=final_pnl,
    pnl_pct=final_pnl_pct,
)
```

## Accessing Analysis Results

After data has been collected, access analysis via:

```python
from llm.mechanical_bot_report import get_mechanical_bot_report_generator

gen = get_mechanical_bot_report_generator()

# Get full comprehensive report
report = gen.generate_comprehensive_report()

# Print human-readable summary
summary = gen.print_report_summary()
print(summary)

# Save to JSON
gen.save_report(report, "mechanical_bot_analysis.json")

# Get specific analysis sections
signal_report = gen.generate_signal_report()
edge_report = gen.generate_edge_report()
gap_report = gen.generate_gap_report()
```

## Data Flow Summary

```
┌─────────────────────┐
│  Market Data        │
│  (OHLCV, Regimes)   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────────┐
│ Ensemble Voting                 │
│ (Multi-strategy signal gen)     │◄──── on_signal_generated()
└──────────┬──────────────────────┘
           │
           ├─ Rejected?──────────────────► on_signal_rejected()
           │
           ▼
┌─────────────────────────────────┐
│ Risk Gate Evaluation            │
│ (Circuit breaker, size check)   │
└──────────┬──────────────────────┘
           │
           ├─ Rejected?──────────────────► on_signal_rejected()
           │
           ▼
┌─────────────────────────────────┐
│ Position Execution              │
│ (Opening trade)                 │◄──── on_position_opened()
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│ Trade Lifecycle                 │
│ (Open, TP1 near, SL near, etc) │◄──── on_position_state_change()
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│ Position Close                  │
│ (Exit at TP/SL/manual)          │◄──── on_position_closed()
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│ Mechanical Bot Memory           │
│ (Store signals, patterns, wins) │
└──────────┬──────────────────────┘
           │
           ▼
┌─────────────────────────────────┐
│ Analysis & Reporting            │
│ (Edges, gaps, failures)         │
└─────────────────────────────────┘
```

## Testing Integration

Add test hooks to verify data is flowing correctly:

```python
from llm.mechanical_bot_instrumentation import get_mechanical_bot_instrumentation

# After running some trades
instr = get_mechanical_bot_instrumentation()

# Check memory
print(instr.get_memory_report())

# Check open trades
print(instr.get_current_open_trades())

# Check analysis
print(instr.get_bot_edge_analysis())
```

## Environment Variables

No special environment variables needed. System works with default settings.

Optional: Set logging level to DEBUG for detailed trace
```bash
export DEBUG_INSTRUMENTATION=true
```

## Performance Considerations

- **Memory overhead**: Minimal (<1MB for 1000 signals)
- **CPU overhead**: Negligible (<0.1ms per hook call)
- **Storage**: ~500 bytes per signal + 100 bytes per state snapshot
- **All I/O is append-only** (efficient for continuous appending)

## Troubleshooting

### Signals not being recorded?
- Check `on_signal_generated()` is called after ensemble
- Verify signal_id is unique
- Check data directory exists: `data/llm/mechanical_bot_memory/`

### State tracking not working?
- Ensure `on_position_opened()` is called before `on_position_state_change()`
- Verify trade_id matches between position_opened and position_closed
- Check state files exist in `data/llm/mechanical_bot_state/`

### Reports showing no data?
- Ensure at least 1 complete trade cycle (open → close)
- Check minimum sample requirements (5+ trades for patterns)
- Run `gen.generate_comprehensive_report()` to see full analysis

## Next Steps

Once integration is complete:

1. **Run paper trading** - Accumulate 50+ trades for pattern analysis
2. **Generate reports** - Get comprehensive mechanical bot analysis
3. **Identify edges** - Find bot's genuine alpha sources
4. **Identify gaps** - Find market opportunities bot misses
5. **Build LLM synthesis** - Generate complementary signals in gaps
6. **Measure impact** - Track LLM value-add vs mechanical system alone
