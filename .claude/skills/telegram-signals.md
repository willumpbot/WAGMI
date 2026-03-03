# /telegram-signals — Manage Telegram Signal Ingestion Pipeline

## Description
Configure, test, debug, and analyze the Telegram signal ingestion pipeline. Covers channel monitoring, signal parsing, LLM analysis, and outcome tracking for external trading signals.

## Arguments
- `$ARGUMENTS` — Optional: "setup" (configure channels), "test" (parse test), "analyze" (review ingested signals), "debug" (fix parsing issues)

## Workflow

### 1. Pipeline Status Check
Read and assess current state:

**Configuration:**
- Read `.env` for: `TELEGRAM_SIGNAL_TOKEN`, `TELEGRAM_SIGNAL_CHANNELS`
- Are channels configured? Is the token valid?
- Which channels are being monitored?

**Code Health:**
- Read `bot/signals/telegram_ingest.py` — TelegramSignalMonitor class
- Check signal parsing formats supported (structured, inline, markdown)
- Check symbol aliases map (BTC, ETH, SOL, DOGE, PEPE, HYPE, FARTCOIN)
- Check confidence keyword detection
- Known bug: decimal parsing for "97,500.50" format (ROADMAP section 8)

**Data:**
- Read `bot/data/signals/ingested_signals.jsonl` — how many signals ingested?
- Last ingestion time — is monitoring active?
- Parse quality scores — distribution

### 2. Setup Mode (if "setup")
Guide through Telegram signal channel configuration:

1. **Create signal bot** (if needed):
   - Instructions for @BotFather: create bot, get token
   - Set `TELEGRAM_SIGNAL_TOKEN` in `.env`

2. **Configure channels**:
   - How to get channel IDs (forward message to @userinfobot)
   - Set `TELEGRAM_SIGNAL_CHANNELS` in `.env` (comma-separated)
   - Add bot to each channel as member

3. **Verify connection**:
   ```bash
   cd bot && python -c "
   from signals.telegram_ingest import TelegramSignalMonitor
   monitor = TelegramSignalMonitor()
   print('Connected:', monitor.is_connected())
   "
   ```

4. **Test ingestion**:
   - Send a test message to monitored channel
   - Verify it appears in ingested_signals.jsonl

### 3. Test Mode (if "test")
Test the signal parser with various formats:

**Test Cases:**
```python
# Structured format
"🔔 BTC LONG\nEntry: 97,500\nSL: 96,200\nTP1: 99,800\nTP2: 102,000\nConfidence: High"

# Inline format
"Going long BTC at 97500, stop 96200, target 99800"

# Markdown format
"**BTC** | LONG | Entry 97.5k | SL 96.2k | TP 99.8k"

# Edge cases
"PEPE long 0.00001234 sl 0.00001100 tp 0.00001500"
"SOL short from 145.20 targeting 139.80 stop at 148.50"
```

For each test:
- Does the parser extract: symbol, side, entry, SL, TP1, TP2?
- What's the parse quality score?
- What confidence level is detected?
- Any parsing failures?

### 4. Analyze Mode (if "analyze")
Read `bot/data/signals/ingested_signals.jsonl` and analyze:

**Signal Volume:**
```
INGESTED SIGNALS — <date range>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Total Signals:    N
By Source Channel: {channel_id: count}
By Symbol:        {BTC: N, ETH: N, SOL: N}
By Side:          {LONG: N, SHORT: N}
Parse Quality:    avg X.XX (min X.XX, max X.XX)
```

**LLM Analysis Results:**
- How many signals got LLM analysis? (TAKE/SKIP/MODIFY verdicts)
- TAKE rate: what % of external signals pass LLM filter?
- SKIP reasons: most common (low quality, wrong regime, etc.)
- MODIFY actions: what adjustments were made?

**Outcome Tracking:**
- Of signals marked TAKE: what was the win rate?
- Of signals marked SKIP: were they correct to skip? (price validation)
- Signal quality vs outcome correlation
- Best/worst signal sources (by channel)

### 5. Debug Mode (if "debug")
Investigate parsing failures:

- Read recent entries from ingested_signals.jsonl with low parse quality
- Identify common failure patterns:
  - Decimal/comma formatting issues (known bug)
  - Unrecognized symbol aliases
  - Non-standard signal formats
  - Missing required fields (no SL, no entry)
- Propose parser fixes with code changes to `telegram_ingest.py`
- Test fixes against historical failures

### 6. Integration Health
Check how ingested signals flow into the trading pipeline:
- Signal → LLM Analyzer → Decision → Position Manager
- Is the LLM analyzer callback connected?
- Are ingested signals reaching the decision engine?
- Are they subject to the same risk gates as internal signals?

### 7. Report
```
TELEGRAM SIGNAL PIPELINE — <timestamp>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STATUS: [ACTIVE / CONFIGURED / NOT SET UP]
Channels Monitored: N
Signals Ingested (7d): N

PARSE QUALITY:
  High (>0.8): XX% of signals
  Medium (0.5-0.8): XX% of signals
  Low (<0.5): XX% of signals — need parser fixes

LLM FILTER:
  TAKE: XX% | SKIP: XX% | MODIFY: XX%

OUTCOMES (of TAKE signals):
  Win Rate: XX%
  Avg PnL: $XX
  Best Source: channel_XXXX (XX% WR)

ISSUES:
  [List parser bugs, missing channels, connectivity issues]

RECOMMENDATIONS:
  1. [Fix/improvement]
  2. [Fix/improvement]
```
