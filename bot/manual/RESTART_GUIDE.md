# Paper Trading Bot Restart Guide

## Quick Restart (30 seconds)

In the terminal running the paper trading bot:

1. Press `Ctrl+C` to stop the bot
2. Wait for "Graceful shutdown" message (positions save to disk automatically)
3. Run:
```bash
cd bot && python run.py paper
```

That's it. The manual sniper system activates automatically on startup.

## What Happens on Restart

### Nothing Changes for the $10k Paper Trading:
- Same strategies, same ensemble, same risk gates, same everything
- Open positions restored from `data/position_backups/`
- Circuit breaker state restored
- Equity unchanged ($10,009.05 as of last heartbeat)
- Trade history preserved in `data/trades.csv`

### New Things That Activate (read-only, never touches trades):
- **Manual Sniper Filter**: Evaluates every signal for manual scalp quality
- **Telegram Alerts**: Sends sniper signals to your Telegram when conditions are met
- **Simulator**: Paper-trades every sniper signal on a virtual $100 account
- **New Telegram Commands**: `/sniper`, `/sim`, `/trade`, `/exit`, `/journal`, `/equity`, `/optimize`

### Data That Persists Across Restarts:
- `data/manual/sniper_signals.jsonl` — All generated sniper signals (266 so far)
- `data/manual/sim_status.json` — Simulator state (equity, trades, etc.)
- `data/manual/sim_trades.jsonl` — Simulated trade history
- `data/manual/trade_journal.jsonl` — Your real manual trades (when you log them)
- `data/position_backups/` — Bot's open positions
- `data/alert_state.json` — Alert rate limiting state

## Environment Variables (Optional)

These are all optional — defaults work out of the box:

```bash
# Manual Sniper System (all have defaults, no config needed)
MANUAL_SNIPER_ENABLED=true        # Default: true
MANUAL_MODE=aggressive            # Default: aggressive ($100 account)
MANUAL_EQUITY=100                 # Default: 100
MANUAL_DAILY_TARGET=20            # Default: 20
MANUAL_MAX_LEVERAGE=25            # Default: 25
MANUAL_MIN_CONFIDENCE=78          # Default: 78
MANUAL_MIN_AGREE=2                # Default: 2
MANUAL_MAX_DAILY_SIGNALS=5        # Default: 5
MANUAL_ALERT_GAP_S=300            # Default: 300 (5 min cooldown per symbol)

# Telegram (uses same bot token as paper trading alerts)
# If TELEGRAM_TOKEN and TELEGRAM_CHAT_ID are already set, sniper alerts
# go to the same chat. To use a separate chat:
MANUAL_TELEGRAM_CHAT_ID=your_chat_id
```

## Verification After Restart

Check the bot log for these lines (confirms sniper system loaded):
```
[INIT] Manual Sniper System enabled — target=$20/day max_lev=25.0x
```

Then in Telegram, send:
- `/sniper` — Should show "0 signals today" (until market produces a setup)
- `/sim` — Should show "$100 starting equity"
- `/status` — Normal bot status (equity, positions, etc.)

## If Something Goes Wrong

The sniper system is 100% wrapped in try/except. If it fails to load:
- Bot logs `[INIT] Manual Sniper System not available: <reason>`
- Paper trading continues exactly as before, zero impact
- Fix the issue and restart again

## Manual Sniper Standalone Mode (Alternative)

If you don't want to restart the bot, the sniper system also runs independently:
```bash
cd bot && python -m manual.runner              # Continuous scanning
cd bot && python -m manual.runner --once       # Single scan
cd bot && python -m manual.runner --status     # Check sim status
```
Note: Standalone mode uses its own API calls (may hit rate limits alongside the bot).

## Files Changed in the Bot (for reference)

Only `multi_strategy_main.py` was modified — 3 small additions:
1. **Init** (~line 488): Loads ManualSniperFilter + Simulator (wrapped in try/except)
2. **Signal hook** (~line 2978): After ensemble evaluation, passes signal to sniper filter
3. **Scan loop** (~line 1164): Checks simulator positions against live prices

All additions are:
- Wrapped in `if self._manual_sniper is not None:` guards
- Wrapped in `try/except` with silent fallback
- Read-only (never modifies signals, never affects trade decisions)
- Default to None/disabled if imports fail

## What the Sniper System Does

Every scan cycle (~60s):
1. Bot generates an ensemble signal (same as always)
2. Sniper filter evaluates: is this 78%+ confidence, 2+ strategies agree?
3. If YES and it's PREMIUM or SNIPER tier:
   - Calculates dynamic leverage (10-25x based on stop width)
   - Calculates position sizing for $100 account
   - Sends Telegram alert with exact entry/SL/TP/leverage/qty
   - Simulator opens a virtual position
4. Simulator checks open positions: did price hit TP or SL?
5. Logs everything to `data/manual/`

The bot's own trading decisions are completely unaffected.
