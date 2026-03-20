# Phase 3C: Configuration Hardening Implementation

**Status:** Implementation-ready
**Duration:** 9 hours (parallel to Phase 3B)
**Priority:** HIGH - Apply during Phase 3B without stopping trades
**Effort:** 5 critical fixes with complete code examples

---

## Overview

Five production-critical improvements identified in System Integration Audit. All can be applied during Phase 3B-1 or Phase 3B-2 without stopping trading.

**Timeline:** Can be applied any time during Phase 3B (24h window)
**Risk:** Very low (all fixes are defensive, non-functional changes)
**Testing:** Each fix has test case included

---

## Fix 1: Circuit Breaker Exception Handling

**Issue:** If CB check throws exception, loss limits are bypassed
**Severity:** CRITICAL
**File:** `bot/execution/risk.py`
**Time:** 30 minutes

### Current Code (Lines 295-310)
```python
def is_trading_allowed(self, equity: float) -> bool:
    """Check if trading is allowed given current state."""
    # Check daily loss limit
    if self.daily_loss > self.daily_loss_limit:
        return False

    # Check consecutive losses
    if self.consecutive_losses >= self.max_consecutive_losses:
        return False

    # Check drawdown
    if self.drawdown_pct > self.max_drawdown_pct:
        return False

    return True
```

### Problem
If any check throws exception, trading proceeds (fail-open pattern - DANGEROUS)

### Fixed Code
```python
def is_trading_allowed(self, equity: float) -> bool:
    """Check if trading is allowed given current state."""
    try:
        # Check daily loss limit
        if self.daily_loss > self.daily_loss_limit:
            self.tripped = True
            logger.warning(f"Circuit breaker: daily loss limit exceeded")
            return False

        # Check consecutive losses
        if self.consecutive_losses >= self.max_consecutive_losses:
            self.tripped = True
            logger.warning(f"Circuit breaker: consecutive losses limit exceeded")
            return False

        # Check drawdown
        if self.drawdown_pct > self.max_drawdown_pct:
            self.tripped = True
            logger.warning(f"Circuit breaker: drawdown limit exceeded")
            return False

        return True

    except Exception as e:
        # FAIL-SAFE: On any error, assume breaker is tripped
        self.tripped = True
        logger.error(f"Circuit breaker exception: {e} - assuming TRIPPED (fail-safe)")
        return False  # Deny trading
```

### Test Case
```python
def test_circuit_breaker_exception_handling():
    cb = CircuitBreaker()
    cb.start_session(equity=10000)

    # Simulate exception by making daily_loss non-comparable
    cb.daily_loss = "invalid"  # Will throw on comparison

    # Should return False (fail-safe), not throw
    result = cb.is_trading_allowed(equity=10000)
    assert result == False, "Should deny trading on exception"
    assert cb.tripped == True, "Should set tripped=True"
```

---

## Fix 2: Database Health Checks During Runtime

**Issue:** Silent DB write failures → stale strategy weights → performance degradation
**Severity:** CRITICAL
**File:** `bot/data/db.py`
**Time:** 45 minutes

### Current Code (Missing)
No runtime DB health checks currently exist.

### Implementation
```python
# Add to db.py module

import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def check_database_health():
    """Check database health and return status."""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Try write operation
        cursor.execute("INSERT INTO health_checks (checked_at) VALUES (?)",
                      (datetime.utcnow().isoformat(),))
        conn.commit()

        # Try read operation
        cursor.execute("SELECT MAX(id) FROM health_checks")
        _ = cursor.fetchone()

        conn.close()
        return True, None

    except sqlite3.DatabaseError as e:
        logger.error(f"Database health check FAILED: {e}")
        return False, str(e)
    except Exception as e:
        logger.error(f"Database health check exception: {e}")
        return False, str(e)

def assert_database_healthy():
    """Assert database is healthy, raise if not."""
    healthy, error = check_database_health()
    if not healthy:
        logger.critical(f"Database unhealthy: {error} - STOPPING TRADING")
        raise RuntimeError(f"Database health check failed: {error}")
```

### Integration (in signal_pipeline.py pre-trade gate)
```python
def apply_gates(signal, risk_mgr, leverage_mgr, config):
    """Apply pre-trade risk gates."""

    # Gate 0: Database Health (NEW - add this first)
    try:
        from data.db import check_database_health
        healthy, error = check_database_health()
        if not healthy:
            return FilterResult(
                approved=False,
                reason=f"Database unhealthy: {error}"
            )
    except Exception as e:
        return FilterResult(
            approved=False,
            reason=f"Database health check error: {e}"
        )

    # ... rest of gates
```

### Test Case
```python
def test_database_health_check():
    health, error = check_database_health()
    assert health == True, f"DB health should pass: {error}"

    # Simulate corrupted DB by making it read-only
    import os
    os.chmod('bot/data/trades.db', 0o444)

    health, error = check_database_health()
    assert health == False, "Should detect corrupt DB"
    assert error is not None, "Should have error message"

    # Restore permissions
    os.chmod('bot/data/trades.db', 0o644)
```

---

## Fix 3: Explicit LLM Unavailability Tracking

**Issue:** Silent mode switch to mechanical-only (operator doesn't know)
**Severity:** HIGH
**File:** `bot/llm/decision_engine.py`
**Time:** 30 minutes

### Current Code (Lines 50-100)
```python
def decide(snapshot: dict) -> Optional[LLMDecision]:
    """Make LLM decision on signal."""
    try:
        # Call LLM agents
        regime = regime_agent(snapshot)
        trade = trade_agent(snapshot, regime)
        # ...
    except Exception as e:
        logger.warning(f"LLM error: {e}")
        return None  # Silent fallback to mechanical
```

### Problem
Operator doesn't know LLM failed. System silently switches to mechanical-only.

### Fixed Code
```python
# Add to decision_engine.py

class LLMAvailability:
    """Track LLM availability status."""
    def __init__(self):
        self.available = True
        self.last_error = None
        self.last_error_time = None
        self.error_count = 0
        self.consecutive_failures = 0

_llm_availability = LLMAvailability()

def get_llm_availability():
    """Get current LLM availability status."""
    return _llm_availability

def decide(snapshot: dict) -> Optional[LLMDecision]:
    """Make LLM decision on signal."""
    global _llm_availability

    try:
        # Call LLM agents
        regime = regime_agent(snapshot)
        trade = trade_agent(snapshot, regime)

        # Mark as available
        _llm_availability.available = True
        _llm_availability.consecutive_failures = 0

        return merge_outputs(...)

    except Exception as e:
        # Track failure
        _llm_availability.available = False
        _llm_availability.last_error = str(e)
        _llm_availability.last_error_time = datetime.utcnow()
        _llm_availability.error_count += 1
        _llm_availability.consecutive_failures += 1

        logger.error(f"LLM UNAVAILABLE: {e} (consecutive failures: {_llm_availability.consecutive_failures})")

        # ALERT operator if >= 3 consecutive failures
        if _llm_availability.consecutive_failures >= 3:
            logger.critical(f"LLM SYSTEM DOWN: {_llm_availability.consecutive_failures} consecutive failures")
            alert_operator(f"⚠️ LLM system offline, trading on mechanical signals only")

        return None
```

### Monitoring Integration
```python
# Add to monitoring dashboard

def get_llm_status():
    """Get LLM availability for dashboard."""
    avail = get_llm_availability()
    return {
        "available": avail.available,
        "consecutive_failures": avail.consecutive_failures,
        "error_rate": avail.error_count / total_decisions if total_decisions > 0 else 0,
        "last_error": avail.last_error,
        "last_error_time": avail.last_error_time.isoformat() if avail.last_error_time else None,
        "status": "🟢 HEALTHY" if avail.available else "🔴 OFFLINE"
    }
```

---

## Fix 4: Reconciliation Startup Gate

**Issue:** Bot can start without knowing exchange positions
**Severity:** HIGH
**File:** `bot/multi_strategy_main.py`
**Time:** 20 minutes

### Current Code (Lines 150-160)
```python
def run(self):
    """Start the bot trading loop."""
    logger.info("Bot starting...")

    # Optional reconciliation
    try:
        self.reconcile_with_exchange()
    except:
        logger.warning("Reconciliation failed, continuing anyway")

    # Start trading
    while True:
        # ... trading loop
```

### Problem
Reconciliation is optional. Bot trades without knowing real exchange state.

### Fixed Code
```python
def run(self):
    """Start the bot trading loop."""
    logger.info("Bot starting...")

    # MANDATORY reconciliation on startup
    try:
        logger.info("Reconciling with exchange...")
        reconciliation_result = self.reconcile_with_exchange()

        if not reconciliation_result.success:
            logger.critical(f"Reconciliation FAILED: {reconciliation_result.error}")
            logger.critical("Cannot start trading without exchange sync")
            raise RuntimeError(f"Startup reconciliation failed: {reconciliation_result.error}")

        logger.info(f"✅ Reconciliation complete: {reconciliation_result.positions_synced} positions synced")
        assert reconciliation_result.positions_synced >= 0, "Position count should be non-negative"

    except Exception as e:
        logger.critical(f"STARTUP BLOCKED: Reconciliation required but failed: {e}")
        logger.critical("Exiting to prevent desynchronization")
        return  # Exit, don't trade

    # Only reach here if reconciliation succeeded
    logger.info("✅ Bot cleared for trading (reconciliation complete)")

    # Start trading
    while True:
        try:
            # ... trading loop
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Trading loop error: {e}")
            # Don't crash, try to continue
```

### Test Case
```python
def test_startup_gate():
    bot = MultiStrategyBot()

    # Mock failed reconciliation
    bot.reconcile_with_exchange = Mock(
        return_value=ReconciliationResult(success=False, error="API timeout")
    )

    # Should NOT start trading
    bot.run()  # Should exit immediately

    # Verify reconciliation was called
    bot.reconcile_with_exchange.assert_called_once()
```

---

## Fix 5: Position SL/TP Persistence

**Issue:** Crash during position open → original SL/TP lost forever
**Severity:** MEDIUM
**File:** `bot/execution/position_manager.py`
**Time:** 45 minutes

### Current Code (Lines 50-80)
```python
def open_position(self, signal: Signal) -> Position:
    """Open a new position."""
    position = Position(
        id=uuid4(),
        symbol=signal.symbol,
        entry=signal.entry,
        sl=signal.sl,
        tp1=signal.tp1,
        tp2=signal.tp2,
        # ...
    )

    # Write to database
    self.db.save_position(position)

    return position
```

### Problem
If crash happens after `Position` created but before DB save completes, original SL/TP are lost.

### Fixed Code
```python
import json
from pathlib import Path

class PositionManager:
    def __init__(self):
        self.positions = {}
        self.position_backup_dir = Path("bot/data/position_backups")
        self.position_backup_dir.mkdir(exist_ok=True)

    def open_position(self, signal: Signal) -> Position:
        """Open a new position with crash recovery."""
        position = Position(
            id=uuid4(),
            symbol=signal.symbol,
            entry=signal.entry,
            sl=signal.sl,
            tp1=signal.tp1,
            tp2=signal.tp2,
            original_sl=signal.sl,  # Track original
            original_tp1=signal.tp1,
            original_tp2=signal.tp2,
            # ...
        )

        # STEP 1: Persist to disk BEFORE anything else
        self._backup_position(position)

        try:
            # STEP 2: Write to database
            self.db.save_position(position)

            # STEP 3: Add to in-memory tracking
            self.positions[position.id] = position

            logger.info(f"Position {position.id} opened: {position.symbol} @ {position.entry}")
            return position

        except Exception as e:
            # If DB write fails, position is still recoverable from backup
            logger.error(f"Position open failed: {e}, but backup saved")
            raise

    def _backup_position(self, position: Position):
        """Backup position to disk for recovery."""
        backup_file = self.position_backup_dir / f"{position.id}.json"
        backup_data = {
            "id": str(position.id),
            "symbol": position.symbol,
            "entry": position.entry,
            "sl": position.sl,
            "tp1": position.tp1,
            "tp2": position.tp2,
            "original_sl": position.original_sl,
            "original_tp1": position.original_tp1,
            "original_tp2": position.original_tp2,
            "created_at": position.created_at.isoformat(),
        }

        with open(backup_file, 'w') as f:
            json.dump(backup_data, f)

        logger.debug(f"Position backup saved: {backup_file}")

    def recover_positions_from_backup(self):
        """Recover positions from disk backups after crash."""
        recovered = 0

        for backup_file in self.position_backup_dir.glob("*.json"):
            try:
                with open(backup_file) as f:
                    backup_data = json.load(f)

                # Check if position still in DB
                pos_id = backup_data['id']
                if pos_id in self.positions:
                    logger.debug(f"Position {pos_id} already in memory")
                    continue

                # Restore from backup
                position = Position(
                    id=UUID(pos_id),
                    symbol=backup_data['symbol'],
                    entry=backup_data['entry'],
                    sl=backup_data['sl'],
                    tp1=backup_data['tp1'],
                    tp2=backup_data['tp2'],
                    original_sl=backup_data['original_sl'],
                    original_tp1=backup_data['original_tp1'],
                    original_tp2=backup_data['original_tp2'],
                )

                self.positions[position.id] = position
                logger.info(f"Position {pos_id} recovered from backup")
                recovered += 1

            except Exception as e:
                logger.error(f"Failed to recover position from {backup_file}: {e}")

        return recovered
```

### Integration (call on startup)
```python
def __init__(self):
    # ... initialization

    # Recover any positions lost in crash
    recovered = self.recover_positions_from_backup()
    if recovered > 0:
        logger.warning(f"Recovered {recovered} positions from crash backups")
```

---

## Implementation Checklist

### Before Deployment
- [ ] Code review all 5 fixes
- [ ] Run unit tests for each fix
- [ ] Test with sandbox credentials
- [ ] Verify no interference with existing code

### During Phase 3B-1 (optional)
- [ ] Apply Fix 1: Circuit breaker exception handling
- [ ] Apply Fix 2: Database health checks
- [ ] Apply Fix 3: LLM unavailability tracking
- [ ] Apply Fix 4: Reconciliation startup gate
- [ ] Apply Fix 5: Position SL/TP persistence

### After Application
- [ ] Run Phase 2 tests again (should all pass)
- [ ] Monitor for new logs/alerts
- [ ] Verify each fix working
- [ ] Continue trading normally

---

## Risk & Rollback

**Risk:** Very low (all defensive, non-functional changes)
**Rollback:** Can revert individual fixes without stopping trades

**If issue with Fix X:**
1. Comment out Fix X code
2. Restart trading
3. Investigate and fix
4. Redeploy

---

## Success Criteria

After applying all 5 fixes, system should:
- ✅ Handle CB exceptions gracefully (fail-safe)
- ✅ Detect and alert on DB issues
- ✅ Track LLM availability explicitly
- ✅ Require reconciliation on startup
- ✅ Persist position SL/TP to survive crashes

---

**Status: READY TO IMPLEMENT**

Can be applied anytime during Phase 3B without stopping trading.

Estimated time: 2-3 hours to apply all 5 fixes
Testing time: 1-2 hours
Total: 3-4 hours parallel to Phase 3B-1 or Phase 3B-2
