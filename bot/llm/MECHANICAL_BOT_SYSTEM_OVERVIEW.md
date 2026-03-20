# Mechanical Bot Understanding & Augmentation System

Complete overview of the comprehensive mechanical bot instrumentation, analysis, and synthesis system.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    MECHANICAL BOT SYSTEM                            │
│                  (Existing - No Changes)                            │
│  - Multi-strategy ensemble voting                                   │
│  - Risk gate filtering                                              │
│  - Position management                                              │
│  - Trade execution                                                  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ (Transparent Observation)
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│              INSTRUMENTATION LAYER (Non-invasive)                   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │ mechanical_bot_instrumentation.py                           │  │
│  │ ─────────────────────────────────────────────────────────── │  │
│  │ Integration hooks (no behavior change):                     │  │
│  │ • on_signal_generated()                                    │  │
│  │ • on_position_opened()                                     │  │
│  │ • on_position_state_change()                               │  │
│  │ • on_position_closed()                                     │  │
│  │ • on_signal_rejected()                                     │  │
│  │ • capture_market_snapshot()                                │  │
│  └──────────────────────────────────────────────────────────────┘  │
└────┬────────────────┬────────────────┬────────────────────────────┘
     │                │                │
     ▼                ▼                ▼
  DATA STREAM      MEMORY UNIT      STATE TRACKER

     │                │                │
     └────────────────┼────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  MEMORY & ANALYSIS LAYER                            │
│                                                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐  │
│  │ Memory Unit      │  │ Analyzer         │  │ Report Gen     │  │
│  │ ──────────────── │  │ ──────────────── │  │ ──────────────│  │
│  │ Stores:          │  │ Identifies:      │  │ Generates:   │  │
│  │ • Signals        │  │ • Edges (alpha)  │  │ • Signal Rep │  │
│  │ • Patterns       │  │ • Gaps (missed)  │  │ • Edge Rep   │  │
│  │ • Failures       │  │ • Regime perf    │  │ • Gap Rep    │  │
│  │ • Successes      │  │ • Time perf      │  │ • Regime Rep │  │
│  └──────────────────┘  └──────────────────┘  └────────────────┘  │
│           │                     │                     │            │
│           └─────────────────────┼─────────────────────┘            │
│                                 │                                  │
└─────────────────────────────────┼──────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   SYNTHESIS LAYER                                   │
│                                                                     │
│  mechanical_bot_synthesis.py                                       │
│  ─────────────────────────────────────────────────────────────── │
│  Generates complementary LLM signals:                              │
│  • Gap-filling signals (trade where bot doesn't)                  │
│  • Edge-boosting signals (amplify bot's edges)                    │
│  • Time-based signals (underexploited hours)                      │
│  • Diversification signals (uncorrelated positions)                │
│  • Regime-specific signals (different approach per regime)         │
└────────────┬──────────────────────────────────────────────────────┘
             │
             ▼
     [Executable LLM Signals]
     Sent to ensemble for voting/execution
```

## Core Components

### 1. Data Stream & Capture

**File**: `mechanical_bot_data_stream.py`

Captures complete market intelligence snapshots that mechanical bot sees:

```python
MarketSnapshot captures:
  • Price metrics: current_price, price_change_1h/24h_pct, atr, volatility
  • Regime: regime, regime_confidence, regime_momentum
  • Alignment: alignment_5m_1h, alignment_1h_6h, alignment_6h_1d
  • Support/Resistance: levels, distances
  • Correlation: BTC correlation, lead-lag
  • Time: hour, day_of_week, trading_session
  • Momentum: RSI, MACD, volume profile
```

**Methods**:
- `capture_snapshot()` - Log market state
- `get_latest_snapshot()` - Current state
- `get_snapshot_history()` - Time-series data
- `identify_high_quality_moments()` - Best trading conditions

### 2. Memory Unit

**File**: `mechanical_bot_memory.py`

Stores and recalls mechanical bot patterns:

```python
Stores:
  • MechanicalBotSignal - Every signal with entry conditions and outcome
  • MechanicalBotPattern - Recurring patterns grouped by regime/vol/alignment
  • MechanicalBotFailure - Loss records with failure modes
  • MechanicalBotSuccess - Win records with success factors
```

**Methods**:
- `record_signal()` - Log signal generation
- `record_signal_outcome()` - Log execution and result
- `get_signals_by_setup()` - Find signals of type
- `get_signals_by_regime()` - Find regime-specific signals
- `get_top_patterns()` - Rank patterns by win_rate × frequency
- `get_memory_report()` - Summary of all patterns

**Statistics**:
- Win rate, execution rate, total PnL
- Patterns discovered, failures/successes logged
- Top patterns ranked by edge (frequency × win_rate × pnl)

### 3. State Tracker

**File**: `mechanical_bot_state_tracker.py`

Tracks mechanical bot's thinking throughout trade lifecycle:

```python
TradePhase lifecycle:
  SIGNAL_GENERATION → ENTRY_EVALUATION → POSITION_OPEN
  → TP1_APPROACHED → TP1_HIT → TRAILING → CLOSED
  or SL_APPROACHED → SL_HIT
```

**Captures**:
- Initial confidence and strategy voting
- State transitions (TP1 near, SL near, etc)
- Real-time confidence evolution
- When bot changes mind
- Decision reasoning at each phase
- PnL and hold time

**Methods**:
- `start_tracking_trade()` - Begin tracking
- `record_state_change()` - Log phase transitions
- `close_trade()` - Finalize history
- `analyze_state_evolution()` - Track confidence trajectory
- `get_phase_statistics()` - Which phases matter most

### 4. Analyzer

**File**: `mechanical_bot_analyzer.py`

Extracts insights from memory:

```python
Identifies:
  • PatternQualityScore - Quality of each pattern
  • MechanicalBotEdge - Genuine alpha sources (WR > 65%)
  • MechanicalBotGap - Market opportunities bot misses
```

**Analysis**:
- Regime performance breakdown
- Time-of-day performance
- Failure mode analysis
- Failure prevention insights
- Recommendations

**Methods**:
- `analyze_all_patterns()` - Quality assessment
- `identify_mechanical_bot_edges()` - Find genuine alpha
- `identify_gaps()` - Find missed opportunities
- `get_regime_performance()` - Regime breakdown
- `get_time_of_day_performance()` - Hourly breakdown
- `get_failure_analysis()` - Failure modes
- `get_comprehensive_analysis()` - Full analysis

### 5. Report Generator

**File**: `mechanical_bot_report.py`

Generates human/machine-readable reports:

```python
Reports:
  • Signal Report - Overall metrics
  • Edge Report - Top alpha sources
  • Gap Report - Identified opportunities
  • Regime Report - Performance by regime
  • Time Report - Performance by hour
  • Failure Report - Failure analysis
  • Comprehensive Report - All sections
```

**Methods**:
- `generate_signal_report()` - Signal metrics
- `generate_edge_report()` - Bot's edges
- `generate_gap_report()` - Missed opportunities
- `generate_regime_report()` - Regime analysis
- `generate_time_report()` - Time analysis
- `generate_failure_report()` - Failure analysis
- `generate_comprehensive_report()` - Full report
- `print_report_summary()` - Console output
- `save_report()` - Persist to JSON

### 6. Instrumentation Integration

**File**: `mechanical_bot_instrumentation.py`

Wires hooks into trading pipeline:

```python
Hooks (call from multi_strategy_main.py):
  • on_signal_generated() - After ensemble voting
  • on_position_opened() - Position execution
  • on_position_state_change() - Phase transitions
  • on_position_closed() - Trade completion
  • on_signal_rejected() - Risk gate rejection
  • capture_market_snapshot() - Market context
```

All integration is **non-invasive** (observation only).

See `MECHANICAL_BOT_INTEGRATION.md` for detailed wiring instructions.

### 7. Synthesizer

**File**: `mechanical_bot_synthesis.py`

Generates complementary LLM signals based on analysis:

```python
Signal Types:
  • Gap-filling - Trade where bot doesn't
  • Edge-boosting - Amplify bot's edges
  • Time-based - Underexploited hours
  • Diversification - Uncorrelated positions
  • Regime-specific - Different approach per regime
```

**Methods**:
- `generate_gap_filling_signals()` - Fill identified gaps
- `generate_edge_boosting_signals()` - Amplify edges
- `generate_time_based_signals()` - Time windows
- `generate_diversification_signals()` - Uncorrelated trades
- `generate_regime_specific_signals()` - Regime alternatives
- `convert_idea_to_signal()` - Make executable
- `get_synthesis_plan()` - Comprehensive plan
- `get_synthesis_report()` - Generation summary

## Data Flow

```
Mechanical Bot              Instrumentation         Analysis         Synthesis
─────────────────────────────────────────────────────────────────────────────

Generate Signal    ───────► on_signal_generated()  ──► Memory stores  ──► Analyzer finds
                                                        signal & context   edges & gaps

Position Opens     ───────► on_position_opened()   ──► State tracker  ──► Synthesizer
                                                        starts tracking    generates
                                                                          complementary
Position Changes   ───────► on_position_state_     ──► State tracker   signals
                              change()                   records phases

Position Closes    ───────► on_position_closed()   ──► State tracker  ──► Report generator
                                                        finalizes        creates reports
                                                        outcome

Market Conditions  ───────► capture_market_        ──► Data stream    ──► Analyzer
                              snapshot()                stores context    refines analysis

                                   │                         │                │
                                   └─────────────────────────┴────────────────┘
                                        Used for correlation & context
```

## Usage Examples

### Complete Analysis Pipeline

```python
from llm.mechanical_bot_report import get_mechanical_bot_report_generator

# Generate comprehensive report
gen = get_mechanical_bot_report_generator()
report = gen.generate_comprehensive_report()

# Print summary
print(gen.print_report_summary(report))

# Save for later
gen.save_report(report, "analysis.json")
```

### Generate Synthetic Signals

```python
from llm.mechanical_bot_synthesis import get_mechanical_bot_synthesizer

# Create synthesis engine
synth = get_mechanical_bot_synthesizer()

# Generate gap-filling signals
gap_signals = synth.generate_gap_filling_signals(symbol="BTC")

# Generate edge-boosting signals
boost_signals = synth.generate_edge_boosting_signals(symbol="BTC")

# Convert to executable signals
for idea in gap_signals + boost_signals:
    signal = synth.convert_idea_to_signal(idea, current_price=42000)
    if signal:
        # Send to ensemble for voting
        result = ensemble.evaluate_llm_signal(signal)
```

### Track Trade Progression

```python
from llm.mechanical_bot_state_tracker import get_mechanical_bot_state_tracker

tracker = get_mechanical_bot_state_tracker()

# Start tracking
tracker.start_tracking_trade(
    trade_id="trade_123",
    symbol="BTC",
    side="BUY",
    entry_price=42000,
    ...
)

# Record state changes as trade progresses
tracker.record_state_change(
    trade_id="trade_123",
    phase="tp1_approached",
    current_price=42500,
    ...
)

# Analyze evolution
analysis = tracker.analyze_state_evolution("trade_123")
print(f"Confidence trend: {analysis['confidence_trend']}")
print(f"Major drops: {analysis['major_confidence_drops']}")
```

### Access Analysis Components

```python
from llm.mechanical_bot_analyzer import get_mechanical_bot_analyzer

analyzer = get_mechanical_bot_analyzer()

# Get edges (bot's genuine alpha)
edges = analyzer.identify_mechanical_bot_edges(top_n=5)
for edge in edges:
    print(f"Edge: {edge.edge_name}")
    print(f"  Condition: {edge.condition}")
    print(f"  Win Rate: {edge.win_rate:.0%}")
    print(f"  Consistency: {edge.consistency_score:.0%}")

# Get gaps (missed opportunities)
gaps = analyzer.identify_gaps(top_n=5)
for gap in gaps:
    print(f"Gap: {gap.description}")
    print(f"  Potential: ${gap.potential_pnl:.2f}")
    print(f"  Frequency: {gap.expected_frequency}")

# Get comprehensive analysis
analysis = analyzer.get_comprehensive_analysis()
print(f"Total signals: {analysis.total_signals}")
print(f"Win rate: {analysis.win_rate:.0%}")
print(f"Top edges: {[e.edge_name for e in analysis.top_edges]}")
```

## Key Metrics & Reports

### Signal Metrics
- Total signals generated
- Execution rate (% of signals that become trades)
- Win rate (% of executed signals that win)
- Total PnL
- Average winner/loser

### Edge Analysis
- Win rate per pattern
- Consistency score
- Sample size
- Time-dependency
- Regime-dependency
- Profitability ranking

### Gap Analysis
- Gap description
- Expected frequency
- Potential PnL if traded
- Similarity to bot patterns
- Diversification value

### Performance Breakdown
- By regime (trend/range/panic)
- By time of day (hourly)
- By setup type
- By strategy voting agreement

### Failure Analysis
- Failure modes (whipsaw, black swan, wrong direction)
- Prevention strategies
- Most expensive losses
- Failure frequency

## Integration Checklist

- [ ] Wire `on_signal_generated()` hook after ensemble
- [ ] Wire `on_position_opened()` hook when position opens
- [ ] Wire `on_position_state_change()` hook on phase transitions
- [ ] Wire `on_position_closed()` hook when position closes
- [ ] Wire `capture_market_snapshot()` hook (periodic or on-demand)
- [ ] Run paper trading for 50+ trades to accumulate data
- [ ] Generate reports and review edge/gap analysis
- [ ] Generate synthetic signals for top gaps
- [ ] Test synthetic signals in paper trading
- [ ] Measure LLM value-add vs mechanical alone

## Expected Outcomes

After 100 hours of paper trading with full instrumentation:

### Data Collected
- 200-500 mechanical bot trades (2-5/day)
- 1000+ signal evaluations
- Complete state history for each trade
- Market snapshots for every evaluation
- Failure/success records

### Analysis Available
- Top 3-5 edges (genuine alpha patterns)
- Top 5-10 gaps (missed opportunities)
- Regime-specific performance profile
- Time-of-day trading preferences
- Failure mode prevention strategies

### Synthetic Signals Generated
- 5-15 gap-filling signal ideas
- 3-5 edge-boosting ideas
- 3-5 time-based ideas
- 2-3 diversification ideas

### Metrics to Track
- LLM signal accuracy
- LLM win rate vs mechanical
- LLM cost vs profit
- Incremental PnL added
- Portfolio correlation reduction

## Next Steps

1. **Wire integration** - Add hooks to multi_strategy_main.py
2. **Run paper trading** - Accumulate 50+ trades minimum
3. **Generate analysis** - Create comprehensive report
4. **Generate signals** - Synthesize ideas based on gaps
5. **Test signals** - Paper trade synthetic signals
6. **Measure impact** - Track LLM value-add
7. **Iterate** - Refine signal synthesis based on results

## File Manifest

```
bot/llm/
├── mechanical_bot_memory.py              # Signal/pattern storage
├── mechanical_bot_analyzer.py            # Edge/gap analysis
├── mechanical_bot_state_tracker.py       # Trade lifecycle tracking
├── mechanical_bot_data_stream.py         # Market snapshot capture
├── mechanical_bot_instrumentation.py     # Integration hooks
├── mechanical_bot_report.py              # Report generation
├── mechanical_bot_synthesis.py           # Synthetic signal generation
├── MECHANICAL_BOT_INTEGRATION.md         # Wiring instructions
└── MECHANICAL_BOT_SYSTEM_OVERVIEW.md     # This file
```

## Architecture Principles

1. **Non-invasive**: All changes are observation-only, no behavior changes to mechanical bot
2. **Comprehensive**: Capture every dimension of mechanical bot's decision-making
3. **Analyzable**: Extract patterns and insights from captured data
4. **Actionable**: Generate executable signals based on analysis
5. **Measurable**: Track and report on all metrics
6. **Iterative**: Refine based on paper trading results

This system enables truly understanding what the mechanical bot sees, thinks, and does—then building complementary LLM signals that augment rather than replace.
