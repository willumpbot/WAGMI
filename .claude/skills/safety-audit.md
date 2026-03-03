# /safety-audit — Review All Safety Systems

## Description
Comprehensive audit of every safety mechanism in the trading bot. Verifies circuit breakers, risk gates, position limits, and ops guards are all functioning correctly. Critical before going live or after any code changes.

## Arguments
- `$ARGUMENTS` — Optional: "quick" (config check only) or "deep" (full code audit)

## Workflow

### 1. Circuit Breaker Verification
Read `bot/execution/risk.py` and verify:

**Daily Loss Limit:**
- What % of CURRENT equity triggers the stop? (not peak equity — this is a known gotcha)
- Is the threshold reasonable? (typically 2-5%)
- Is it active (not commented out or bypassed)?

**Consecutive Loss Streak:**
- How many consecutive losses trigger a pause?
- What's the cooldown period?
- Is the counter being reset correctly on wins?

**Test:** Manually trace the circuit breaker logic with a scenario:
- "If we lost 3% today, would trading stop?"
- "If we had 5 losses in a row, would we pause?"

### 2. Risk Gate Pipeline Verification
Read `bot/core/signal_pipeline.py` and verify all 6 gates in order:

```
Gate 1: Signal Validity (is_valid) — SL distance, side checks, R:R
Gate 2: Circuit Breaker — daily loss, streak checks
Gate 3: Position Limits — max concurrent positions
Gate 4: Leverage Calculation — confidence-based tiers
Gate 5: Liquidation Distance — safe distance from liquidation price
Gate 6: Position Sizing — risk-per-trade limits
```

For each gate:
- Is it present and active?
- Are there any bypass conditions?
- Are the thresholds hardcoded or from config?
- Can any edge case skip this gate?

**CRITICAL:** Gates MUST be sequential. A failure at Gate 2 should prevent Gates 3-6 from running.

### 3. Position Sizing Safety
Read `bot/execution/leverage.py` and verify:
- Maximum leverage cap exists and is reasonable
- Near-zero stop widths are rejected (prevents infinite leverage)
- Confidence-to-leverage mapping is monotonic (higher confidence = can use more leverage, not less)
- Liquidation price calculation uses correct maintenance margin rates

### 4. Ops Guard Verification
Read `bot/execution/ops_guard.py` and verify:
- Duplicate position prevention (can't open same symbol twice)
- Oversized trade prevention (can't exceed max position size)
- Environment check (paper vs production behavior is correct)
- Is the guard active in all code paths? (not just the main loop)

### 5. Signal Integrity
Read `bot/strategies/base.py` — Signal dataclass:
- `is_valid` method checks: stop width >= 0.3%, SL on correct side, TP on correct side, R:R >= 1.0
- Are these checks called before every trade execution?
- Is the Signal deep-copied before mutation in ensemble? (known bug in ensemble.py)

Read `bot/strategies/ensemble.py`:
- Verify deep copy of signals before modification
- Verify MIN_VOTES and VETO_RATIO come from config (not hardcoded)

### 6. LLM Safety (if multi-agent enabled)
- Critic Agent's veto power: is it always respected? Can it be overridden?
- Learning Agent: verify it only writes to memory, never modifies trading behavior directly
- Agent pipeline: verify risk gating still applies even when LLM says "go"
- API key handling: verify no keys in prompts, logs, or error messages

### 7. Data Safety
- `decisions.jsonl`: verify append-only (no truncation in production)
- Memory files: verify write error handling (don't crash on disk full)
- Trades CSV: verify PnL math consistency
- No secrets in any data files

### 8. Configuration Safety
Read `bot/trading_config.py`:
- All safety-critical values have sane defaults
- Environment variable overrides are validated (can't set max_leverage=1000 via env)
- Paper vs production configs are correctly differentiated

### 9. Audit Report
```
SAFETY AUDIT — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━

CIRCUIT BREAKERS
  Daily loss limit:     3% of current equity ✓
  Consecutive losses:   5 before pause ✓
  Loss calc method:     Current equity (not peak) ✓

RISK GATES (6/6 active)
  1. Signal validity:   Active ✓
  2. Circuit breaker:   Active ✓
  3. Position limits:   Active, max=3 ✓
  4. Leverage calc:     Active, max=5x ✓
  5. Liquidation dist:  Active ✓
  6. Position sizing:   Active, max 2% risk ✓

POSITION SAFETY
  Leverage cap:         5x ✓
  Zero-stop rejection:  Active ✓
  Liquidation buffer:   10% minimum ✓

OPS GUARD
  Duplicate prevention: Active ✓
  Oversize prevention:  Active ✓
  Environment check:    paper mode ✓

SIGNAL INTEGRITY
  Deep copy in ensemble: [✓/✗]
  is_valid checks:       Active ✓

LLM SAFETY
  Critic veto respected: ✓
  Learning write-only:   ✓
  No keys in prompts:    ✓

ISSUES FOUND: [N]
[List any issues with severity and recommended fix]

OVERALL: [SAFE / NEEDS ATTENTION / UNSAFE]
```

### 10. Severity Guide
- **CRITICAL**: Missing or bypassed safety gate → STOP trading immediately
- **HIGH**: Weakened threshold, hardcoded bypass → Fix before next trade
- **MEDIUM**: Configuration drift, missing validation → Fix this session
- **LOW**: Documentation gap, test coverage gap → Fix this sprint
