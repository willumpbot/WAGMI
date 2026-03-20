# 4-Day Implementation Sprint Plan

**Objective**: Complete wiring, testing, optimization, and validation of TIER 4 & 5 systems
**Timeline**: 4 days
**Success Criteria**: Full paper trading with comprehensive instrumentation and reporting

---

## DAY 1: Complete Wiring & Integration (8 hours)

### Task 1.1: Wire Signal Generation Hook (1.5 hours)

**Location**: multi_strategy_main.py, Line 2708

**Current Code**:
```python
signal_result = self.ensemble.evaluate(symbol, data)
```

**Required Action**: Add instrumentation after ensemble evaluation

**Implementation**:
```python
# File: bot/multi_strategy_main.py

# Add imports at top
from llm.mechanical_bot_instrumentation import get_mechanical_bot_instrumentation
from llm.mechanical_bot_data_stream import get_mechanical_data_stream_capture

# In the main loop after signal_result = self.ensemble.evaluate(symbol, data):

# Capture mechanical bot instrumentation
try:
    instr = get_mechanical_bot_instrumentation()
    data_capture = get_mechanical_data_stream_capture()

    if signal_result is not None:
        signal_id = f"{symbol}_{int(time.time() * 1000) % 100000}"

        # Extract market context
        regime = snapshot.get("regime", "unknown") if snapshot else "unknown"
        vol_pct = snapshot.get("volatility_percentile", 0.0) if snapshot else 0.0
        alignment = snapshot.get("alignment_score", 0.0) if snapshot else 0.0
        btc_corr = snapshot.get("btc_correlation", 0.0) if snapshot else 0.0

        # Record signal generation
        instr.on_signal_generated(
            signal_id=signal_id,
            symbol=symbol,
            regime=regime,
            volatility_percentile=vol_pct,
            alignment_score=alignment,
            btc_correlation=btc_corr,
            time_of_day=datetime.now().hour,
            side=signal_result.side,
            confidence=signal_result.confidence,
            num_strategies=len(signal_result.strategy_names),
            strategy_names=signal_result.strategy_names,
            entry_price=signal_result.entry,
            leverage=1.0,  # Get from position_size if available
        )

        # Store signal ID for later reference
        signal_result.metadata["mech_signal_id"] = signal_id

    # Capture market snapshot periodically (every 10 signals)
    if self.signal_count % 10 == 0:
        data_capture.capture_snapshot(
            symbol=symbol,
            current_price=snapshot.get("current_price", 0.0) if snapshot else 0.0,
            price_change_1h_pct=snapshot.get("price_change_1h_pct", 0.0) if snapshot else 0.0,
            price_change_24h_pct=snapshot.get("price_change_24h_pct", 0.0) if snapshot else 0.0,
            atr=snapshot.get("atr", 0.0) if snapshot else 0.0,
            volatility_percentile=vol_pct,
            regime=regime,
            regime_confidence=snapshot.get("regime_confidence", 0.0) if snapshot else 0.0,
            regime_momentum=snapshot.get("regime_momentum", None) if snapshot else None,
            alignment_5m_1h=snapshot.get("alignment_5m_1h", 0.0) if snapshot else 0.0,
            alignment_1h_6h=snapshot.get("alignment_1h_6h", 0.0) if snapshot else 0.0,
            alignment_6h_1d=snapshot.get("alignment_6h_1d", 0.0) if snapshot else 0.0,
            support_level=snapshot.get("support_level", None) if snapshot else None,
            resistance_level=snapshot.get("resistance_level", None) if snapshot else None,
            btc_price=snapshot.get("btc_price", None) if snapshot else None,
            btc_change_1h_pct=snapshot.get("btc_change_1h_pct", 0.0) if snapshot else 0.0,
            correlation_with_btc_1h=btc_corr,
            correlation_with_btc_6h=snapshot.get("btc_correlation_6h", 0.0) if snapshot else 0.0,
            time_of_day=datetime.now().hour,
            day_of_week=datetime.now().weekday(),
            trading_session=get_trading_session(datetime.now().hour),
            rsi_14=snapshot.get("rsi_14", None) if snapshot else None,
            macd_histogram=snapshot.get("macd_histogram", None) if snapshot else None,
            momentum_direction=snapshot.get("momentum_direction", None) if snapshot else None,
            volume_profile=snapshot.get("volume_profile", None) if snapshot else None,
            liquidity_rating=snapshot.get("liquidity_rating", 0.0) if snapshot else 0.0,
        )

except Exception as e:
    logger.error(f"Mechanical bot instrumentation error: {e}")
```

**Checklist**:
- [ ] Add imports
- [ ] Add signal generation hook
- [ ] Add data stream capture (periodic)
- [ ] Handle exceptions gracefully
- [ ] Test with paper trading
- [ ] Verify signal_id stored in metadata

---

### Task 1.2: Wire Position Opening Hook (1.5 hours)

**Location**: execution/position_manager.py (find open position method)

**Required Action**: Add instrumentation when position opens

**Implementation**:
```python
# In position_manager.py, when position successfully opens:

instr = get_mechanical_bot_instrumentation()
signal_id = position.metadata.get("mech_signal_id")
current_price = get_current_price(symbol)

instr.on_position_opened(
    trade_id=position.trade_id,
    signal_id=signal_id,
    symbol=symbol,
    side=position.side,
    entry_price=position.entry_price,
    current_price=current_price,
    regime=snapshot.get("regime", "unknown"),
    volatility=snapshot.get("volatility_percentile", 0.0),
    alignment_score=snapshot.get("alignment_score", 0.0),
    initial_confidence=position.confidence,
    strategy_votes=position.num_strategy_votes,
)
```

**Checklist**:
- [ ] Find position opening location
- [ ] Add hook call
- [ ] Verify data is available
- [ ] Test with paper trading

---

### Task 1.3: Wire Position State Changes Hook (2 hours)

**Location**: execution/position_manager.py (state transitions)

**Required Action**: Add instrumentation for each state change

**Key States**:
- `tp1_approached` - Price within 50% of TP1
- `tp1_hit` - TP1 reached
- `sl_approached` - Price within 50% of SL
- `sl_hit` - SL hit
- `trailing` - In trailing stop mode
- Position open (normal state)

**Implementation**: Add hook for each significant price/state change

**Checklist**:
- [ ] Identify state transition points
- [ ] Add hooks for each state
- [ ] Calculate distance to TP/SL
- [ ] Calculate PnL
- [ ] Test all transitions

---

### Task 1.4: Wire Position Closing Hook (1.5 hours)

**Location**: execution/position_manager.py (close position)

**Required Action**: Record trade outcome and close state

**Implementation**:
```python
# When position closes:

instr.on_position_closed(
    trade_id=position.trade_id,
    signal_id=signal_result.metadata.get("mech_signal_id"),
    exit_price=position.exit_price,
    exit_reason="tp1_hit" | "sl_hit" | "manual" | "trailing",
    pnl=position.realized_pnl,
    pnl_pct=(position.realized_pnl / position.risk_amount) * 100,
)
```

**Checklist**:
- [ ] Find position close location
- [ ] Calculate exit reason
- [ ] Calculate PnL
- [ ] Store in memory/report

---

### Task 1.5: Create Async Perception Capture (2 hours)

**Location**: bot/llm/ (new module or bot/run.py)

**Required Action**: Create continuous async task to fetch perception

**Implementation**:
```python
# bot/llm/perception_monitor.py

import asyncio
from bot_perception_api import get_bot_perception_api_client
from bot_perception_aggregator import get_bot_perception_aggregator
from bot_perception_report import get_bot_perception_report_generator

async def continuous_perception_capture():
    """Run in background to continuously capture bot perception"""
    client = get_bot_perception_api_client()
    agg = get_bot_perception_aggregator()
    gen = get_bot_perception_report_generator()

    while True:
        try:
            # Fetch complete perception from API
            perception_data = await client.fetch_complete_perception()

            # Capture unified percept
            percept = agg.capture_unified_perception(
                system_summary=perception_data['summary'],
                strategy_summaries=perception_data['strategies'],
                llm_decision=perception_data['llm']['latest_decision'],
                llm_market_view=perception_data['llm']['market_view'],
                agent_brains=perception_data['agents'],
                agent_debate=perception_data['debate'],
                pipeline_health=perception_data['pipeline'],
            )

            # Every 100 percepts, generate report
            if agg.stats['total_percepts_captured'] % 100 == 0:
                report = gen.generate_comprehensive_report()
                gen.save_report(report)
                logger.info(f"Perception report saved: {agg.stats['total_percepts_captured']} percepts")

            await asyncio.sleep(5)  # Capture every 5 seconds

        except Exception as e:
            logger.error(f"Perception capture error: {e}")
            await asyncio.sleep(5)

# Wire into bot/run.py:
import asyncio
asyncio.create_task(continuous_perception_capture())
```

**Checklist**:
- [ ] Create perception monitor module
- [ ] Wire into run.py
- [ ] Test with localhost:3000 running
- [ ] Verify data capturing

---

## DAY 2: Integration Testing & Validation (8 hours)

### Task 2.1: Unit Tests for Each Module (2 hours)

**Create**: bot/tests/test_mechanical_bot_*.py

```bash
# Run all unit tests
cd bot && pytest tests/test_mechanical_bot_memory.py -v
cd bot && pytest tests/test_mechanical_bot_analyzer.py -v
cd bot && pytest tests/test_bot_perception_*.py -v
```

**Checklist**:
- [ ] Write unit tests for memory module
- [ ] Write unit tests for analyzer
- [ ] Write unit tests for state tracker
- [ ] Write unit tests for synthesis
- [ ] Write unit tests for perception API
- [ ] All tests pass

---

### Task 2.2: Integration Test Suite (2 hours)

**Create**: bot/tests/test_integration_*.py

```python
# test_integration_mechanical_instrumentation.py
async def test_signal_to_outcome_pipeline():
    """Test complete signal → outcome flow"""
    instr = get_mechanical_bot_instrumentation()

    # Simulate signal generation
    instr.on_signal_generated(...)

    # Simulate position opening
    instr.on_position_opened(...)

    # Simulate position closing
    instr.on_position_closed(...)

    # Verify all data captured
    assert instr.memory.stats['total_signals'] > 0
    assert instr.memory.stats['signals_executed'] > 0

# test_integration_perception_pipeline.py
async def test_api_to_report_pipeline():
    """Test complete perception capture → report flow"""
    client = get_bot_perception_api_client()
    agg = get_bot_perception_aggregator()
    gen = get_bot_perception_report_generator()

    # Fetch perception
    data = await client.fetch_complete_perception()
    assert data is not None

    # Aggregate
    percept = agg.capture_unified_perception(**data)
    assert percept is not None

    # Generate report
    report = gen.generate_comprehensive_report()
    assert report is not None
```

**Checklist**:
- [ ] Write integration tests
- [ ] Test mechanical bot → memory flow
- [ ] Test API → aggregator → analyzer flow
- [ ] Test report generation
- [ ] All tests pass

---

### Task 2.3: Paper Trading Validation (2 hours)

**Run**: 2-hour paper trading session with full instrumentation

```bash
cd bot && python run.py paper
# Monitor:
# - Check data/llm/mechanical_bot_memory/ has files
# - Check data/llm/bot_perception/ has files
# - Check for errors in logs
```

**Validation Checklist**:
- [ ] Mechanical signals captured
- [ ] Positions tracked
- [ ] Market snapshots saved
- [ ] Perception data flowing
- [ ] No errors in logs
- [ ] Reports generating

---

### Task 2.4: Performance Profiling (1.5 hours)

**Measure**:
- Memory usage of instrumentation
- CPU overhead per signal
- Disk I/O frequency
- API latency

**Create**: bot/llm/performance_profile.py

```python
import time
import psutil

class PerformanceMonitor:
    def __init__(self):
        self.process = psutil.Process()
        self.samples = []

    def record(self, operation_name):
        sample = {
            'operation': operation_name,
            'memory_mb': self.process.memory_info().rss / 1024 / 1024,
            'cpu_percent': self.process.cpu_percent(interval=0.1),
            'timestamp': time.time(),
        }
        self.samples.append(sample)

    def report(self):
        avg_memory = sum(s['memory_mb'] for s in self.samples) / len(self.samples)
        max_memory = max(s['memory_mb'] for s in self.samples)
        avg_cpu = sum(s['cpu_percent'] for s in self.samples) / len(self.samples)

        return {
            'avg_memory_mb': avg_memory,
            'max_memory_mb': max_memory,
            'avg_cpu_percent': avg_cpu,
        }
```

**Checklist**:
- [ ] Profile memory usage
- [ ] Profile CPU usage
- [ ] Check disk I/O
- [ ] Identify bottlenecks
- [ ] Document results

---

### Task 2.5: Error Handling Stress Test (1 hour)

**Simulate**:
- localhost:3000 down
- Network timeouts
- Invalid data
- Concurrent operations

**Validation**:
- System handles gracefully
- Retry logic works
- No data loss
- Errors logged properly

---

## DAY 3: Optimization & Fine-Tuning (8 hours)

### Task 3.1: Database Optimization (2 hours)

**Optimize**:
- Jsonl file structures (append efficiency)
- In-memory cache sizes
- Data retention policies

**Implementation**:
```python
# Limit in-memory cache to prevent memory leaks
MAX_PERCEPTS_IN_MEMORY = 1000  # Keep last 1000 only
MAX_SIGNALS_IN_MEMORY = 500

# Implement sliding window
if len(self.percepts) > MAX_PERCEPTS_IN_MEMORY:
    # Keep only newest
    self.percepts = dict(sorted(
        self.percepts.items(),
        key=lambda x: x[1].timestamp,
        reverse=True
    )[:MAX_PERCEPTS_IN_MEMORY])
```

**Checklist**:
- [ ] Implement memory limits
- [ ] Test with 1000+ percepts
- [ ] Verify no memory leaks
- [ ] Profile before/after

---

### Task 3.2: API Query Optimization (2 hours)

**Optimize**:
- Parallel endpoint fetching
- Request batching
- Cache warm-up

**Current**: Already using asyncio.gather for parallel requests

**Improvements**:
- Add response caching (5 second TTL)
- Implement conditional requests (if-modified-since)

```python
# Add response caching
class BotPerceptionAPIClient:
    def __init__(self):
        self.cache = {}
        self.cache_ttl = 5  # 5 seconds

    async def fetch_summary_cached(self):
        cache_key = 'summary'
        if cache_key in self.cache:
            age = time.time() - self.cache[cache_key]['age']
            if age < self.cache_ttl:
                return self.cache[cache_key]['data']

        data = await self.fetch_summary()
        self.cache[cache_key] = {
            'data': data,
            'age': time.time(),
        }
        return data
```

**Checklist**:
- [ ] Implement caching
- [ ] Profile API latency
- [ ] Reduce requests by X%
- [ ] Verify accuracy

---

### Task 3.3: Instrumentation Hook Optimization (2 hours)

**Optimize**:
- Reduce hook invocation overhead
- Batch writes to disk
- Lazy initialization

```python
# Batch writes instead of line-by-line
class BatchedFileWriter:
    def __init__(self, filepath, batch_size=100):
        self.filepath = filepath
        self.batch = []
        self.batch_size = batch_size

    def write(self, data):
        self.batch.append(json.dumps(data))
        if len(self.batch) >= self.batch_size:
            self.flush()

    def flush(self):
        if self.batch:
            with open(self.filepath, 'a') as f:
                f.write('\n'.join(self.batch) + '\n')
            self.batch = []
```

**Checklist**:
- [ ] Implement batching
- [ ] Profile disk I/O
- [ ] Reduce I/O by X%
- [ ] Verify data integrity

---

### Task 3.4: Analysis Engine Optimization (1.5 hours)

**Optimize**:
- Pattern detection (incremental vs batch)
- Correlation calculations
- Report generation

**Current**: Analyzer recalculates everything each time

**Improvement**: Incremental updates

```python
# Incremental pattern updates
def update_pattern_incrementally(self, signal):
    pattern_key = self._get_pattern_key(signal)

    if pattern_key in self.patterns:
        pattern = self.patterns[pattern_key]
        # Update only what changed
        pattern.occurrences += 1
        if signal.outcome == "WIN":
            pattern.wins += 1
        # Recalculate metrics
        pattern.win_rate = pattern.wins / pattern.occurrences
    else:
        # Create new pattern
        self._create_pattern(pattern_key, signal)
```

**Checklist**:
- [ ] Implement incremental updates
- [ ] Profile analysis time
- [ ] Reduce computation by X%
- [ ] Verify accuracy

---

### Task 3.5: Reporting Optimization (0.5 hours)

**Optimize**:
- Report generation time
- Report file size
- Cache expensive calculations

**Checklist**:
- [ ] Profile report generation
- [ ] Identify slow operations
- [ ] Cache results where appropriate

---

## DAY 4: Comprehensive Validation & Documentation (8 hours)

### Task 4.1: 8-Hour Continuous Paper Trading (4 hours)

**Run**: Full paper trading with all instrumentation active

```bash
cd bot && timeout 8h python run.py paper 2>&1 | tee paper_trading_day4.log
```

**Monitor**:
- Signal generation rate
- Position success rate
- Perception data quality
- System stability
- No crashes or errors

**Collect Statistics**:
- Total signals generated
- Total trades executed
- Win rate
- Total PnL
- Total percepts captured
- Memory usage (min/avg/max)
- CPU usage (min/avg/max)

---

### Task 4.2: Comprehensive Analysis & Report (2 hours)

**Generate**:
```python
from llm.mechanical_bot_report import get_mechanical_bot_report_generator
from llm.bot_perception_report import get_bot_perception_report_generator

mech_gen = get_mechanical_bot_report_generator()
perc_gen = get_bot_perception_report_generator()

mech_report = mech_gen.generate_comprehensive_report()
perc_report = perc_gen.generate_comprehensive_report()

print(mech_gen.print_report_summary(mech_report))
print(perc_gen.print_summary(perc_report))

mech_gen.save_report(mech_report, "mechanical_bot_final.json")
perc_gen.save_report(perc_report, "perception_final.json")
```

**Analyze**:
- Mechanical edges identified
- Gaps found
- Perception quality
- Agent accuracy
- System health

---

### Task 4.3: Validation Checklist & Sign-Off (1.5 hours)

**Verify All Systems**:
- [ ] Mechanical bot memory: ✅ Storing signals
- [ ] Analyzer: ✅ Finding edges & gaps
- [ ] State tracker: ✅ Recording lifecycles
- [ ] Data stream: ✅ Capturing market data
- [ ] Instrumentation: ✅ Hooks wired
- [ ] Perception API: ✅ Fetching data with retry logic
- [ ] Aggregator: ✅ Combining data
- [ ] Perception analyzer: ✅ Extracting insights
- [ ] Report generation: ✅ Producing reports
- [ ] Performance: ✅ Within acceptable bounds
- [ ] Error handling: ✅ Graceful degradation
- [ ] Data integrity: ✅ All signals tracked
- [ ] No memory leaks: ✅ Stable usage
- [ ] No crashes: ✅ 8-hour stable run

---

### Task 4.4: Final Documentation & Deployment Guide (1 hour)

**Create**: DEPLOYMENT_CHECKLIST.md

```markdown
# Deployment Checklist

## Pre-Deployment
- [ ] All tests passing
- [ ] Performance benchmarks met
- [ ] 8-hour stability verified
- [ ] Memory/CPU within limits
- [ ] All gaps documented
- [ ] All hooks wired

## Deployment Steps
1. Merge to main branch
2. Deploy to production
3. Monitor first 24 hours closely
4. Review perception reports
5. Verify signal capture
6. Monitor PnL impact

## Rollback Plan
- If system crashes: Revert commit
- If PnL negative: Disable perception synthesis (keep instrumentation)
- If memory bloat: Restart bot
```

---

### Task 4.5: Create Handoff Documentation (1.5 hours)

**Create**: SYSTEM_OPERATIONS.md

```markdown
# System Operations Guide

## Daily Monitoring
- Check perception reports: data/llm/reports/
- Check mechanical signals: data/llm/mechanical_bot_memory/
- Monitor memory usage
- Verify no errors in logs

## Weekly Maintenance
- Review pattern analysis
- Check for memory leaks
- Optimize database files
- Archive old reports

## Troubleshooting
- API connection: Check localhost:3000
- Memory issues: Clear old percepts
- Signal capture: Check hooks wired
- Report generation: Check analyzer state
```

---

## SUCCESS CRITERIA

### Code Quality ✅
- [ ] All 11 modules compile
- [ ] No circular imports
- [ ] All tests pass
- [ ] Code reviewed

### Functional ✅
- [ ] Signals captured and stored
- [ ] Positions tracked through lifecycle
- [ ] Perception data collected continuously
- [ ] Reports generated without errors
- [ ] All hooks fire correctly

### Performance ✅
- [ ] Memory: < 500MB at any time
- [ ] CPU: < 10% average overhead
- [ ] Disk I/O: < 10MB per hour
- [ ] API latency: < 2 seconds with retry
- [ ] No memory leaks over 8 hours

### Stability ✅
- [ ] 8-hour continuous run without crashes
- [ ] Graceful handling of API timeouts
- [ ] All data persisted correctly
- [ ] No data loss on restart

### Documentation ✅
- [ ] Integration guide complete
- [ ] System architecture documented
- [ ] Troubleshooting guide provided
- [ ] Deployment checklist ready

---

## Resources Needed

### Tools
- pytest (testing)
- psutil (performance profiling)
- httpx (already added)

### Knowledge
- Python asyncio
- Git/version control
- Linux command line

### Access
- localhost:3000 (bot API)
- Paper trading mode
- Logs and data directories

---

## Contingency Plans

### If Tests Fail
1. Debug specific test
2. Add logging
3. Isolate issue
4. Fix root cause
5. Re-run all tests

### If Performance Poor
1. Profile to identify bottleneck
2. Optimize that component
3. Re-measure
4. Document changes

### If 8-Hour Run Crashes
1. Check logs for error
2. Add error handling if missing
3. Test crash scenario
4. Re-run until stable

---

## Timeline

```
Day 1 (8h): Wiring all integration points
  ✓ Signal generation hook (1.5h)
  ✓ Position opening hook (1.5h)
  ✓ Position state changes (2h)
  ✓ Position closing hook (1.5h)
  ✓ Async perception (2h)

Day 2 (8h): Testing & validation
  ✓ Unit tests (2h)
  ✓ Integration tests (2h)
  ✓ Paper trading validation (2h)
  ✓ Performance profiling (1.5h)
  ✓ Stress testing (0.5h)

Day 3 (8h): Optimization
  ✓ Database optimization (2h)
  ✓ API optimization (2h)
  ✓ Hook optimization (2h)
  ✓ Analysis optimization (1.5h)
  ✓ Report optimization (0.5h)

Day 4 (8h): Final validation
  ✓ 8-hour continuous run (4h)
  ✓ Report generation & analysis (2h)
  ✓ Validation & sign-off (1.5h)
  ✓ Documentation (1.5h)
```

Total: 32 hours (4 days × 8 hours/day)

---

## Go/No-Go Criteria

**GO if**:
- All tests pass
- 8-hour run stable
- Performance acceptable
- All hooks firing
- Reports generating

**NO-GO if**:
- Any test failing
- Crashes during run
- Memory bloat
- Hooks not firing
- Reports incomplete

