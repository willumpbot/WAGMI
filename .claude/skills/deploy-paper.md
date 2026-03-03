# /deploy-paper — Safe Paper Trading Deployment

## Description
Guided deployment workflow that validates everything before starting paper trading. Catches configuration errors, stale data, and code issues before they cause problems.

## Arguments
- `$ARGUMENTS` — Optional: specific symbols or "full" for all configured

## Workflow

### 1. Environment Validation
Check `.env` file exists and has required values:
- `ANTHROPIC_API_KEY` — set and non-empty (never print the actual key)
- `ENVIRONMENT` — must be "paper" (REFUSE to proceed if "production")
- `LLM_MODE` — show current mode (0-5), explain what it means
- `LLM_MULTI_AGENT` — show if agent pipeline is enabled
- `LLM_USAGE_TIER` — show current tier and estimated cost/decision

If any critical env var is missing, STOP and tell the user what to fix.

### 2. Dependency Check
```bash
cd bot && python -c "import ccxt; import anthropic; import pandas; import numpy; print('All deps OK')"
```
If any import fails, show what to install.

### 3. Code Health
Run the full test suite:
```bash
cd bot && pytest tests/ -x --tb=short -q
```
ALL tests must pass. If any fail:
- Show which tests failed
- Diagnose the root cause
- STOP deployment until fixed

### 4. Configuration Audit
Read and validate `bot/trading_config.py`:
- Max leverage is capped at a reasonable value
- Position size limits are set
- Circuit breaker thresholds are configured
- Risk gates are all enabled (not bypassed)
- Symbols list is correct

Flag any suspicious values:
- Max leverage > 10x without explicit justification
- Position size > 20% of account
- Circuit breakers disabled

### 5. Data Freshness Check
```bash
cd bot && python run.py signals --dry-run
```
Verify:
- Exchange API connection works
- OHLCV data is being fetched successfully
- Data is fresh (last candle < 5 minutes old)
- All required timeframes are available (5m, 1h, 6h, daily)

### 6. Signal Smoke Test
Run one signal evaluation cycle:
```bash
cd bot && python run.py signals
```
Verify:
- No crashes during signal generation
- Strategies produce reasonable output (or graceful None)
- Ensemble voting works
- Signal pipeline processes signals through all 6 gates

### 7. LLM Connection Test (if enabled)
If `LLM_MODE > 0`:
- Make one test call to the configured model
- Verify API key works
- Check response parsing succeeds
- Estimate cost per decision cycle

### 8. Pre-Launch Summary
```
PAPER TRADING DEPLOYMENT CHECK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Environment:    paper ✓
Tests:          848/848 passed ✓
Config:         Validated ✓
Data:           Fresh (< 2min old) ✓
Signals:        Generating correctly ✓
LLM:            Connected (Sonnet, $0.007/cycle) ✓
Symbols:        BTC, ETH, SOL

Ready to launch paper trading.
```

### 9. Launch
If all checks pass:
```bash
cd bot && python run.py paper
```

If any check failed, show exactly what needs to be fixed and DO NOT launch.

### 10. Post-Launch Verification
After 2-3 minutes of running:
- Check logs for errors
- Verify heartbeat is active
- Confirm first signal cycle completed successfully
