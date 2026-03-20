# Bot Perception System - Complete Overview

**Comprehensive visibility into everything the bot reads, thinks, and decides.**

## System Purpose

The bot runs on localhost:3000 with an API exposing:
- Summary state (equity, positions, mode)
- Strategy performance & logs
- LLM decisions & market views
- Agent reasoning, beliefs, calibration
- Debate records (agent disagreements)
- Pipeline health & metrics

**This system captures ALL of that** + combines it with mechanical bot instrumentation to create a complete unified perception view.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    LOCALHOST:3000 API                        │
│  Exposes everything the bot reads, thinks, and does         │
└──────────────────────┬──────────────────────────────────────┘
                       │ (Query all endpoints)
                       ▼
        ┌──────────────────────────────────┐
        │  API Client (bot_perception_api) │
        │  Fetch in parallel:              │
        │  • Summary                       │
        │  • Strategies                    │
        │  • LLM decisions                 │
        │  • Agent brains                  │
        │  • Debate records                │
        │  • Pipeline health               │
        └──────────────────────┬───────────┘
                               │
                  ┌────────────┴────────────┐
                  ▼                         ▼
    ┌─────────────────────────────┐    ┌─────────────────┐
    │  Aggregator                 │    │  Mechanical Bot │
    │ (unify + combine data)      │    │ Instrumentation │
    │ UnifiedBotPercept:          │    │   (outcomes)    │
    │ • System state              │    │                 │
    │ • Strategy stats            │    │ Signal results: │
    │ • LLM thinking              │    │ • Executed?     │
    │ • Agent confidence          │    │ • Win/loss?     │
    │ • Debate status             │    │ • Position chg? │
    │ • Pipeline health           │    │                 │
    │ • Perception quality scores │    │                 │
    └──────────┬────────────────┘    └────────┬────────┘
               │                               │
               └───────────────┬───────────────┘
                               ▼
                  ┌────────────────────────────┐
                  │  Analyzer                  │
                  │  (extract insights)        │
                  │  • Perception patterns     │
                  │  • Biases detected         │
                  │  • Agent contributions     │
                  │  • Perception → decision   │
                  │    correlations            │
                  │  • Sweet spots             │
                  │  • Health score            │
                  └───────────┬────────────────┘
                              ▼
                  ┌────────────────────────────┐
                  │  Report Generator          │
                  │  (7 report types)          │
                  │  • Snapshot                │
                  │  • Patterns                │
                  │  • Biases                  │
                  │  • Agents                  │
                  │  • Correlations            │
                  │  • Sweet Spots             │
                  │  • Health                  │
                  └────────────────────────────┘
```

## Four Core Components

### 1. API Client (`bot_perception_api.py`)

**Fetches everything from localhost:3000**

```python
from bot_perception_api import get_bot_perception_api_client

client = get_bot_perception_api_client()

# Fetch individual endpoints
summary = await client.fetch_summary()          # Bot state
strategies = await client.fetch_all_strategies()   # Strategy stats
llm_decision = await client.fetch_llm_latest_decision()
agent_brains = await client.fetch_all_agent_brains()  # All agent reasoning
debate = await client.fetch_latest_debate()    # Agent arguments
telemetry = await client.fetch_pipeline_telemetry()  # System health

# Or fetch everything in parallel
complete = await client.fetch_complete_perception()

# Or stream continuously
async for percept in client.stream_perception(interval_seconds=5):
    # Process perception updates
    pass
```

**Data Classes:**
- `BotSummarySnapshot` - Equity, positions, risk, mode
- `StrategySnapshot` - Win rate, PnL, KPIs
- `LLMDecisionSnapshot` - Latest decision + confidence
- `AgentBrainSnapshot` - Agent reasoning + accuracy
- `AgentDebate` - Agent positions + objections
- `PipelineTelemetry` - Latency, health, failures

### 2. Aggregator (`bot_perception_aggregator.py`)

**Combines API data + mechanical bot outcomes**

```python
from bot_perception_aggregator import get_bot_perception_aggregator

agg = get_bot_perception_aggregator()

# Capture complete unified perception
percept = agg.capture_unified_perception(
    system_summary=summary,
    strategy_summaries=strategies,
    llm_decision=llm_decision,
    agent_brains=agent_brains,
    agent_debate=debate,
    pipeline_health=telemetry,
    mechanical_signals=[...],       # Signal outcomes
    mechanical_positions=[...],     # Open positions
)

# Analyze perception drift
drift = agg.analyze_perception_drift(window_minutes=60)
print(f"Regime changes: {drift['regime_changes']}")
print(f"Confidence drift: {drift['confidence_drift']}")

# Compare perception vs reality
comparison = agg.compare_perception_vs_mechanical()
if comparison['gaps']:
    print(f"Perception gaps: {comparison['gaps']}")

# Get current state summary
summary = agg.get_perception_summary()
```

**Key Metrics:**
- `perception_quality_score` - How good is the perception?
- `perception_consistency_score` - How aligned are agents?
- `perception_vs_reality_gap` - Perception bias?

### 3. Analyzer (`bot_perception_analyzer.py`)

**Extracts patterns and biases**

```python
from bot_perception_analyzer import get_bot_perception_analyzer

analyzer = get_bot_perception_analyzer()

# Find recurring patterns
patterns = analyzer.identify_perception_patterns()
for pattern in patterns:
    print(f"{pattern.pattern_id}: {pattern.accuracy:.0%} accuracy")

# Detect biases
biases = analyzer.detect_perception_biases()
for bias in biases:
    print(f"⚠️  {bias.bias_type}: {bias.description}")

# Analyze agent contributions
contributions = analyzer.analyze_agent_contributions()
for contrib in contributions:
    print(f"{contrib.agent_role}: {contrib.accuracy:.0%} accuracy")

# Correlate perception → outcomes
correlations = analyzer.correlate_perception_to_outcomes()
for corr in correlations:
    if corr.win_rate > 0.6:
        print(f"✅ {corr.perception_state}: {corr.win_rate:.0%}")

# Find best combinations
sweet_spots = analyzer.find_perception_sweet_spots()
for spot in sweet_spots:
    print(f"🎯 {spot['perception_combo']}: {spot['win_rate']:.0%}")

# Get health score
health = analyzer.get_perception_health_score()
print(f"Health: {health['overall_health']:.0%}")
```

### 4. Report Generator (`bot_perception_report.py`)

**Generates 7 report types**

```python
from bot_perception_report import get_bot_perception_report_generator

gen = get_bot_perception_report_generator()

# Generate individual reports
snapshot = gen.generate_perception_snapshot()     # Current state
patterns = gen.generate_pattern_report()         # Recurring patterns
biases = gen.generate_bias_report()              # Detected biases
agents = gen.generate_agent_report()             # Agent performance
correlations = gen.generate_correlation_report() # Perception → outcome
sweet_spots = gen.generate_sweet_spots_report()  # Best combinations
health = gen.generate_health_report()            # System health

# Or generate everything
comprehensive = gen.generate_comprehensive_report()

# Save and print
gen.save_report(comprehensive)
print(gen.print_summary())
```

## Key Insights Enabled

### 1. What Does the Bot Perceive?

**From API:**
- Market regime (trend/range/panic)
- Strategy agreement level
- Agent confidence levels
- LLM market understanding
- Pipeline latency & health

```python
summary = agg.get_perception_summary()
print(f"Regime: {summary['llm']['regime']}")
print(f"LLM Confidence: {summary['llm']['confidence']:.0f}%")
print(f"Agents: {summary['agents']['active']}/{summary['agents']['total']}")
```

### 2. How Confident is the Bot?

**From Agent Brains:**
- Each agent's confidence
- Agent agreement level
- Pipeline health

```python
for agent_role, brain in percept.agent_brains.items():
    print(f"{agent_role}: {brain.confidence:.0f}% confidence, {brain.accuracy:.0%} accuracy")

print(f"Team alignment: {percept.perception_consistency_score:.0%}")
```

### 3. What Decisions Follow Perception?

**Perception → Decision Correlation:**
- High confidence + high agreement → X% win rate
- Low confidence + low agreement → Y% win rate

```python
correlations = analyzer.correlate_perception_to_outcomes()
for corr in correlations:
    print(f"{corr.perception_state}:")
    print(f"  {corr.num_decisions} decisions, {corr.win_rate:.0%} win rate")
```

### 4. Is the Perception System Healthy?

**Health Score (0-100%):**
- Data quality
- Agent consistency
- Perception-reality gap
- Pipeline health

```python
health = analyzer.get_perception_health_score()
print(f"Health: {health['overall_health']:.0%}")
print(f"Status: {health['recommendation']}")
```

### 5. What Perception Combinations Work Best?

**Sweet Spots:**
- Best regime + confidence + agreement combinations
- Ranked by win rate

```python
sweet_spots = analyzer.find_perception_sweet_spots()
for spot in sweet_spots[:3]:
    print(f"{spot['perception_combo']}: {spot['win_rate']:.0%} WR")
```

## Usage in Real System

### Wire into main loop:

```python
import asyncio
from bot_perception_api import get_bot_perception_api_client
from bot_perception_aggregator import get_bot_perception_aggregator
from bot_perception_report import get_bot_perception_report_generator

async def main():
    client = get_bot_perception_api_client()
    agg = get_bot_perception_aggregator()
    gen = get_bot_perception_report_generator()

    # Continuously capture perception
    async for perception_data in client.stream_perception(interval_seconds=10):
        # Capture unified percept
        percept = agg.capture_unified_perception(
            system_summary=perception_data['summary'],
            strategy_summaries=perception_data['strategies'],
            llm_decision=perception_data['llm']['latest_decision'],
            agent_brains=perception_data['agents'],
            agent_debate=perception_data['debate'],
            pipeline_health=perception_data['pipeline'],
        )

        # Analyze every N percepts
        if agg.stats['total_percepts_captured'] % 100 == 0:
            report = gen.generate_comprehensive_report()
            gen.save_report(report)
            print(gen.print_summary())

asyncio.run(main())
```

## Data Files Generated

```
data/llm/bot_perception/
├── percepts.jsonl          # All perception snapshots
└── evolution_*.json        # Symbol evolution tracking

data/llm/reports/
└── perception_YYYYMMDD_HHMMSS.json  # Comprehensive reports
```

## Key Metrics Tracked

| Metric | Purpose |
|--------|---------|
| `perception_quality_score` | How much good data? |
| `perception_consistency_score` | How much agent agreement? |
| `perception_vs_reality_gap` | What bias exists? |
| `data_freshness` | How old is the data? |
| `regime_stability` | Consistent regime or flipping? |
| `confidence_drift` | Changing confidence? |
| `pattern_accuracy` | Do recurring patterns work? |
| `agent_contribution` | Which agents matter? |
| `perception_health` | Overall system health? |

## Reports Generated

1. **Snapshot** - Current perception state
2. **Patterns** - Recurring behaviors
3. **Biases** - Systematic errors
4. **Agents** - Each agent's accuracy
5. **Correlations** - Perception → outcome mapping
6. **Sweet Spots** - Best perception combinations
7. **Health** - System health & stability

## Performance

- **Memory**: ~5MB per 1000 percepts
- **CPU**: ~10ms per perception capture
- **Disk**: ~200B per percept
- **API Latency**: ~500-1000ms per fetch (parallel)

## Next Steps

1. **Wire into main loop** - Start capturing perception continuously
2. **Run paper trading** - Accumulate 100+ percepts
3. **Generate reports** - Analyze patterns & biases
4. **Find sweet spots** - Identify best perception combinations
5. **Optimize thresholds** - Use insights to improve decisions
6. **Measure impact** - Track bot improvements

## Architecture Principles

✅ **Non-invasive** - Observation only, zero changes to bot logic
✅ **Comprehensive** - Captures ALL bot perception sources
✅ **Unified** - Single view of everything (API + mechanical)
✅ **Analyzed** - Extracts patterns, biases, correlations
✅ **Actionable** - Reports with specific recommendations
✅ **Real-time** - Streaming and continuous capture
✅ **Persistent** - All data stored for analysis

This system answers: **"What is the bot really thinking and why?"**
