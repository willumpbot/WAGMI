# /exit-review — LLM Exit Intelligence Review

## Description
Review open positions using the Exit Intelligence Agent's thesis-continuity framework. Answers: "Is my thesis still valid? Should I adjust stops, take profit, or close?"

## Arguments
- `$ARGUMENTS` — Optional: "all" (all positions), specific symbol (e.g., "SOL"), "urgent" (only positions with thesis concerns)

## Workflow

### 1. Load Open Positions
- Read position state from `bot/execution/position_manager.py` data
- For each open position, extract: symbol, side, entry, current price, SL, TP1, TP2, unrealized PnL, hold time, state, leverage
- Read `bot/data/llm/decisions.jsonl` for the original entry decision to find: thesis, setup_type, confluence quality, regime at entry

### 2. Current Market Context
For each position's symbol:
- Current regime (has it shifted since entry?)
- BTC direction (aligned with thesis?)
- Funding rate (accumulating cost?)
- Volume ratio (is the market active or dead?)
- Current signals from all 4 strategies (do they still agree?)

### 3. Thesis Continuity Assessment
For each position, evaluate:

**Thesis Validity Check:**
- Original thesis: what was predicted?
- Current evidence: does the prediction still hold?
- Regime shift: did the regime change since entry? (e.g., trend → range)
- BTC alignment: is BTC still supporting the thesis?
- Time decay: has the thesis timeframe expired?

**Position Health:**
- Unrealized PnL vs risk (how many R are we up/down?)
- Hold time vs typical hold for this setup type
- Funding cost accumulated so far
- Distance to SL, TP1, TP2 (where are we in the trade?)

**Exit Intelligence Recommendation:**
Based on thesis validity + position health, recommend one of:
- HOLD: Thesis valid, position behaving as expected
- TIGHTEN_SL: Thesis weakening, protect capital
- WIDEN_TP: Thesis strong and winning, let it run
- PARTIAL_CLOSE: Thesis uncertain, de-risk
- FULL_CLOSE: Thesis dead, exit immediately

### 4. Output Format
For each position, display:

```
═══ SOL/USDT LONG ═══
Entry: $23.45 | Current: $24.12 (+2.9%) | Hold: 2h 15m
SL: $22.80 | TP1: $24.50 | TP2: $25.20
Unrealized: +$67.30 (1.8R) | Funding cost: -$2.10

ORIGINAL THESIS: "SOL likely +4% in 6h, RT 4/4 align + MC 68% up"
SETUP: trend_at_zone (convergent, quality=85%)
REGIME AT ENTRY: trend | CURRENT REGIME: trend ✓

THESIS STATUS: ✓ VALID
- BTC still trending (+1.2% since entry)
- Volume sustained above average
- Regime unchanged
- TP1 approaching — let runner portion trail

RECOMMENDATION: HOLD (widen TP2 to $25.80 if TP1 hits)
URGENCY: low
```

### 5. Summary Table
After individual reviews, show summary:
| Symbol | Side | PnL | Thesis | Urgency | Action |
|--------|------|-----|--------|---------|--------|
| SOL | LONG | +2.9% | Valid | Low | Hold |
| ETH | SHORT | -1.2% | Weakening | Medium | Tighten SL |

### 6. Alert on Critical Positions
Flag any position where:
- Thesis is INVALID and still holding → CRITICAL
- Regime shifted adversely → HIGH
- Funding eating >30% of unrealized gain → MEDIUM
- Hold time exceeded setup type average by 2x → MEDIUM
