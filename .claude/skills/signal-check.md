# /signal-check — Live Signal Analysis

## Description
Run a one-shot signal check across all configured symbols, showing detailed per-strategy breakdowns, ensemble voting results, and risk gate status.

## Arguments
- `$ARGUMENTS` — Optional: specific symbols (e.g., "BTC,ETH") or "all"

## Workflow

### 1. Run Signal Generation
```bash
cd bot && python run.py signals --symbols <SYMBOLS>
```
Capture the full output.

### 2. Deep Analysis
For each symbol that generated a signal, investigate:

**Signal Details:**
- Side (BUY/SELL), confidence (0-100), entry price
- Stop loss, TP1, TP2, ATR value
- R:R ratio (calculated from entry/SL/TP1)

**Per-Strategy Votes:**
- Which strategies voted for this signal?
- Which abstained (returned None)?
- Which vetoed?
- What was the ensemble voting mode (weighted_veto)?
- What are the current strategy weights?

**Risk Gate Status:**
- Would this signal pass all 6 gates in `signal_pipeline.py`?
  1. Signal validity (is_valid check)
  2. Circuit breaker (loss streak, daily drawdown)
  3. Position limits (max concurrent positions)
  4. Leverage calculation (confidence-based tier)
  5. Liquidation distance check
  6. Position sizing

### 3. Market Context
- Current regime classification (from regime_trend strategy)
- Recent price action: last 24h high/low/close
- Volatility: ATR as % of price (is it normal, elevated, or extreme?)
- Any chop detection flags?

### 4. For Symbols with NO Signal
Explain why:
- No strategy agreement (show individual strategy opinions)
- Below confidence threshold
- Chop detector blocked
- Data unavailability

### 5. Summary Table
```
SIGNAL CHECK — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Symbol  Signal  Conf  Entry     SL        TP1       R:R   Regime
──────────────────────────────────────────────────────────────────
BTC     BUY     78    97,500    96,200    99,800    1.8   trend
ETH     —       —     —         —         —         —     range
SOL     SELL    65    145.20    148.50    139.80    1.6   panic
```

### 6. Actionability Assessment
For each active signal:
- **Strong** (conf >75, 3+ strategies agree, regime supports direction): "High-conviction setup"
- **Moderate** (conf 60-75, 2 strategies agree): "Valid but watch for confirmation"
- **Weak** (conf <60, min_votes barely met): "Marginal — consider skip"
