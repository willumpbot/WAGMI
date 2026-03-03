# /stress-test — Scenario and Stress Testing

## Description
Run the bot's logic through extreme market scenarios to find failure modes before they happen in production. Tests flash crashes, volatility spikes, liquidity drains, and edge cases.

## Arguments
- `$ARGUMENTS` — Optional: specific scenario ("flash-crash", "vol-spike", "chop", "gap", "all") or "custom"

## Workflow

### 1. Select Scenarios
Parse `$ARGUMENTS` or default to all scenarios:

**Built-in Scenarios:**
1. **Flash Crash** — Price drops 15% in 5 minutes, recovers 50% in next 10 minutes
2. **Volatility Spike** — ATR triples within 1 hour (e.g., news event)
3. **Extended Chop** — 24 hours of ±0.5% range-bound action with many false breakouts
4. **Gap Up/Down** — Price gaps 5% between candles (exchange maintenance, overnight)
5. **Liquidity Drain** — Spread widens 10x, fills at much worse prices
6. **Cascade Losses** — 5 consecutive losing trades to test circuit breakers
7. **Max Positions** — All symbols signal simultaneously, test position limit gates
8. **Stale Data** — Data feed pauses for 10 minutes during active position

### 2. Run Scenario Simulation
```bash
cd bot && python -m scripts.scenario_sim --scenario <SCENARIO>
```

If the script doesn't support the scenario, construct it manually:
- Generate synthetic OHLCV data matching the scenario
- Feed through strategy evaluation pipeline
- Simulate position manager response
- Check all risk gates fire correctly

### 3. Per-Scenario Analysis

**For each scenario, verify:**

**Signal Behavior:**
- Do strategies produce sensible signals (or correctly abstain)?
- Does the ensemble handle conflicting signals during stress?
- Does the chop detector activate during choppy scenarios?

**Risk Gate Behavior:**
- Do circuit breakers activate at the right thresholds?
- Does position sizing reduce during high volatility?
- Does the leverage cap prevent over-exposure?
- Are liquidation distance checks catching dangerous positions?

**Position Manager Behavior:**
- Does the state machine handle rapid transitions?
- Do trailing stops behave correctly during flash crashes?
- Are partial fills handled? (TP1 hit but TP2 never reached)

**LLM Agent Behavior (if enabled):**
- Does the Regime Agent correctly identify the stress regime?
- Does the Risk Agent flag elevated risk?
- Does the Critic Agent veto dangerous trades during panic?

### 4. Edge Case Specific Tests

**Zero/Near-Zero Stop Width:**
- What happens if ATR drops to near-zero? (low liquidity coins)
- Does the 0.3% minimum stop width hold?

**Max Leverage Scenario:**
- What's the actual maximum leverage the system can reach?
- Is it capped correctly?

**Simultaneous Signals:**
- All symbols fire BUY at 90% confidence — what happens?
- Position limits should prevent over-allocation

**Data Unavailability:**
- 1h data available but 6h missing — do strategies degrade gracefully?
- All data unavailable — does the bot wait or crash?

**Rapid State Transitions:**
- Signal → Open → TP1 → Reversal → SL in 3 candles
- Does the position manager handle this without state corruption?

### 5. Failure Mode Catalog
Document every failure found:

```
FAILURE MODE CATALOG
━━━━━━━━━━━━━━━━━━━━
ID   Scenario        Failure                          Severity   Status
001  Flash Crash      Trailing stop set too tight       MEDIUM    NEW
002  Vol Spike        Leverage not reduced fast enough  HIGH      NEW
003  Stale Data       Bot continues trading on old data CRITICAL  NEW
004  Max Positions    4th position bypasses limit       HIGH      NEW
```

### 6. Run Programmatic Tests
After scenario analysis, run existing stress tests:
```bash
cd bot && pytest tests/test_stress.py -v
cd bot && pytest tests/test_execution_safety.py -v
cd bot && pytest tests/test_ops_guard.py -v
```

Report results and any new gaps found.

### 7. Stress Test Report
```
STRESS TEST REPORT — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCENARIOS TESTED: X/8
PASSED: X
FAILED: X
NEW FAILURE MODES: X

RESULTS BY SCENARIO:
  Flash Crash:     PASS ✓ (circuit breaker activated correctly)
  Vol Spike:       WARN ⚠ (leverage reduced but slowly)
  Extended Chop:   PASS ✓ (chop detector blocked signals)
  Gap Up/Down:     FAIL ✗ (trailing stop triggered at gap price)
  Liquidity Drain: PASS ✓ (spread check prevented entry)
  Cascade Losses:  PASS ✓ (paused after 5th loss)
  Max Positions:   PASS ✓ (4th position correctly rejected)
  Stale Data:      FAIL ✗ (bot traded on 12-min-old data)

CRITICAL FIXES NEEDED:
1. Add stale data check before EVERY trade execution
2. Handle price gaps in trailing stop logic

RECOMMENDED FOLLOW-UP:
- Add regression tests for each failure mode found
- Re-run after fixes to verify
```

### 8. Regression Test Generation
For every new failure mode found, draft a test case:
- Add to `bot/tests/test_stress.py` or `test_execution_safety.py`
- Include the exact scenario data that triggered the failure
- Assert the expected behavior after the fix
