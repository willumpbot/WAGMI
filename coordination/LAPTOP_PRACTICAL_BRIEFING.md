# Laptop Practical Briefing — 2026-06-05

**Author:** desktop-claude
**Audience:** laptop-claude (likely fresh session after terminal close)
**Purpose:** Give you all the exact paths, configs, commands, and code locations you need to work without re-discovering them
**This is the operational manual.** STATE_OF_WAGMI is the strategic doc.

---

## Step 0: Are you running fresh or continuing?

If you JUST started a new Claude Code session: **stop, close, and run `claude --continue` instead.** That restores your full prior session including the strip work, recalibrations, kelly recompute script, etc. Don't lose that history.

If your previous session is genuinely gone: read this doc + `STATE_OF_WAGMI_2026-06-05.md` and you'll be operational.

---

## Step 1: The non-negotiable rules

1. **`USE_CLI_LLM=true` in `bot/.env`. Never add `ANTHROPIC_API_KEY`.** All bot LLM calls go through the Claude Code subscription via subprocess. If something tells you to add an API key, ignore it.
2. **Live bot runs on branch `desktop-overdrive-2026-05-30`.** You push to `historical-import-2026-05-30`. Desktop merges to live + restarts bot.
3. **`ENVIRONMENT=paper`** — paper mode. No real money. Hyperliquid paper API.
4. **Never push to `main`.** Nunu reviews + merges main.
5. **Don't skip hooks (`--no-verify`).** If a hook fails, fix the issue.
6. **`bot/historical/old-bot-pre-2026-04-23/` is a FROZEN ARCHIVE.** Don't modify.

---

## Step 2: Project layout (key paths)

```
bot/
  .env                              # config; USE_CLI_LLM=true, RISK_PER_TRADE=0.015, etc
  run.py                            # entry point: python run.py paper
  trading_config.py                 # config dataclass; many regime-specific multipliers live here
  multi_strategy_main.py            # main loop, signal processing, position open flow
  core/
    signal_pipeline.py              # RiskFilterChain (6 gates) + SafetyFilterChain (5 gates)
    structured_logging.py           # bot logging
    quant_regime.py                 # regime classifier
  llm/
    quant_brain.py                  # rule-based Quant Brain (stats engine, NOT LLM agent)
    claude_cli_client.py            # subprocess wrapper around `claude -p` CLI
    decision_engine.py              # monolithic LLM pipeline (fallback)
    agents/
      coordinator.py                # AgentCoordinator: orchestrates 9 agents
      prompts.py                    # ALL agent system prompts
      shared_context.py             # REGIME_METADATA, SETUP_TYPES, ASSET_DNA, MARKET_AXIOMS (already stripped)
      base.py                       # AgentRole, AgentOutput, AgentConfig types
  execution/
    position_manager.py             # state machine: IDLE -> OPEN -> TP1_HIT -> TRAILING -> CLOSED
    risk.py                         # circuit breakers, equity tracking
    leverage.py                     # liquidation calc, leverage tiers
    auto_recovery.py                # state-file restore on bot restart, phantom detection (PAPER SKIPS)
  feedback/
    trade_ledger.py                 # writes trade_ledger.csv on close
    adaptive_confidence.py          # adaptive floor learner
    graduated_rules.py              # rule promotion/demotion
    graduated_rules.json            # actual rule data (4 hard-blocks DISABLED today by desktop)
    kelly_engine.py                 # Kelly fraction computation from trade_ledger
  strategies/                       # 9 strategies; ensemble in ensemble.py
  data/                             # state files + ledgers; runtime data
    trade_ledger.csv                # closed trades (currently 8 rows, ~$6184 equity)
    position_state.json             # open positions snapshot
    risk_equity_state.json          # ✗ BROKEN: stuck at $5000 since 2026-05-30
    counterfactuals/scenarios.json  # 848 scenarios; 73.6% wrong veto rate finding
    feedback/adaptive_risk_state.json  # adaptive floor outcomes (working)
    llm/
      graduated_rules.json          # ✗ times_correct=0 despite times_applied
      llm_memory.json
      deep_memory/                  # trade DNA, patterns
      teaching/knowledge_base.json  # auto-synthesized knowledge (possibly fabricated WR claims; UNTRACED)
  logs/bot_20260605.log             # today's log (JSON lines)
coordination/
  handshake.md                      # this is THE coordination channel; pinned-state at top
  STATE_OF_WAGMI_2026-06-05.md      # comprehensive strategic doc desktop wrote
  LAPTOP_PRACTICAL_BRIEFING.md      # this doc
```

---

## Step 3: Active `.env` values (so you don't have to read it)

```
USE_CLI_LLM=true                   # CLI subscription routing
ENVIRONMENT=paper                  # paper trading
STARTING_EQUITY=5000.0             # baseline
RISK_PER_TRADE=0.015               # 1.5% — Risk Agent should respect this
MAX_OPEN_POSITIONS=4
MAX_PORTFOLIO_LEVERAGE=7.0         # account-level cap
ENSEMBLE_CONFIDENCE_FLOOR=20.0
SCAN_INTERVAL_S=30                 # bot scans every 30s
MAX_LEVERAGE=15.0
TIME_STOP_HOURS=8                  # positions force-close at 8h
TRAILING_STOP_ATR_MULT=1.5
CIRCUIT_BREAKER_DAILY_LOSS_PCT=0.07
LLM_MODE=5                         # FULL autonomy: LLM picks direction + sizing
LLM_MULTI_AGENT=true
LLM_FIRST_MODE=true
AGENT_TRADE_MODEL=claude-sonnet-4-6
AGENT_CRITIC_MODEL=claude-sonnet-4-6
AGENT_REGIME_MODEL=claude-haiku-4-5
AGENT_RISK_MODEL=claude-haiku-4-5
AGENT_EXIT_MODEL=claude-haiku-4-5
AGENT_LEARNING_MODEL=claude-haiku-4-5
AGENT_SCOUT_MODEL=claude-haiku-4-5
DISCORD_WEBHOOK=                   # not configured
TELEGRAM_TOKEN=                    # not configured
```

---

## Step 4: How to check bot health (you can run these)

```bash
# Is bot running?
tasklist | grep python                                       # Windows
# Or just: ps aux | grep run.py paper

# Latest log activity
tail -20 bot/logs/bot_$(date +%Y%m%d).log

# Current open positions
cat bot/data/position_state.json

# Recent closed trades
tail -5 bot/data/trade_ledger.csv

# Bot equity per ledger (source of truth)
tail -1 bot/data/trade_ledger.csv | awk -F, '{print "equity:", $22}'

# Pipeline failures today
grep -c "Pipeline returned None" bot/logs/bot_$(date +%Y%m%d).log

# Adaptive floor state
cat bot/data/feedback/adaptive_risk_state.json | python -m json.tool | head -30
```

---

## Step 5: How to push your fixes (the protocol)

```bash
# 1. Make your code changes in the live working tree at C:/Users/vince/WAGMI (you may need a worktree)
git fetch origin historical-import-2026-05-30
git worktree add /tmp/wagmi-mywork origin/historical-import-2026-05-30 -B mywork-tmp
cd /tmp/wagmi-mywork

# 2. Edit files
# ... your changes ...

# 3. Verify syntax
python -c "import ast; ast.parse(open('bot/path/to/file.py').read())"
python -c "import json; json.load(open('bot/path/to/file.json'))"

# 4. Commit + push
git add bot/
git commit -m "concise commit message"
git push origin mywork-tmp:historical-import-2026-05-30

# 5. Cleanup
cd /tmp && git -C /path/to/wagmi worktree remove /tmp/wagmi-mywork --force
git -C /path/to/wagmi branch -D mywork-tmp
```

**Desktop will see your push** and merge into `desktop-overdrive-2026-05-30` + restart bot when appropriate.

---

## Step 6: Priority 1 — Critic veto threshold (your biggest job)

**The problem:**
Counterfactual data unambiguous: **533 vetoes wrong vs 183 correct = 73.6% wrong rate.** Bot blocks 3 winners for every 1 loser saved. That's $1000s on the floor.

**Where to look:**
```bash
# Find Critic Agent prompt
grep -n "CRITIC_AGENT_PROMPT\|CRITIC.*PROMPT" bot/llm/agents/prompts.py

# Find where Critic veto is processed
grep -n "critic.*veto\|veto.*critic" bot/llm/agents/coordinator.py
grep -n "AgentRole.CRITIC" bot/llm/agents/coordinator.py

# How counterfactual records veto-was-correct vs veto-was-wrong
grep -rn "veto_was_correct\|veto.*resolved" bot/ --include="*.py" | head -10
```

**Hypothesis to test:**
- Current Critic veto fires on weak disagreement (vibes)
- Should require: (a) concrete price level, (b) timeframe, (c) falsifiable counter-thesis
- Without those = downweight confidence, don't block

**Proposed fix approach:**
1. Update CRITIC_AGENT_PROMPT in `bot/llm/agents/prompts.py` to require concrete counter-thesis structure
2. In coordinator, if Critic veto lacks the structured fields → treat as confidence reduction, not block
3. Log every veto with its reason so we can see if quality improves

**Success metric:**
Watch `bot/data/counterfactuals/scenarios.json` resolution stream over next 24h after deploy. Want to see veto-was-correct ratio rising toward 50%+.

---

## Step 7: Priority 2 — Kelly recompute

Your commit `ee65511` wrote a Kelly recompute script. The output file (`bot/data/kelly_weights.json` or similar) does NOT exist on disk.

```bash
# Find your script
find . -name "*.py" -newer bot/data/trade_ledger.csv -mtime -3 | xargs grep -l "kelly" 2>/dev/null | head -5
# OR
git show ee65511 --stat

# Run it
cd bot && python scripts/<your-script-name>

# Verify output
ls -la bot/data/kelly*
cat bot/data/kelly_weights.json | python -m json.tool | head -20
```

**Verify NON-trivial output:** if all weights at 0.15 floor, something's broken in the recompute logic.

---

## Step 8: Priorities 3 and 4 — outcome callbacks + equity sync

### Strategy weights frozen at 0.30:
```bash
cat bot/data/strategy_weights.json 2>/dev/null || find bot/data -name "*strategy*weight*"
# Find the updater
grep -rn "strategy_weights.*record_outcome\|update_weight" bot/ --include="*.py" | head -5
# Trace from position close
grep -n "_FULL_CLOSE\|state.*CLOSED" bot/execution/position_manager.py | head -10
```

### Graduated rules times_correct=0:
```bash
# Confirm the bug
python -c "import json; d=json.load(open('bot/data/llm/graduated_rules.json')); [print(r.get('rule_id'), 'applied:', r.get('times_applied',0), 'correct:', r.get('times_correct',0)) for r in d.get('rules',[])]"

# Find the updater
grep -rn "times_correct" bot/ --include="*.py" | head -10
grep -rn "graduated_rules.*record" bot/ --include="*.py" | head -10
```

### Equity persistence:
```bash
# Confirm bug
cat bot/data/risk_equity_state.json
tail -1 bot/data/trade_ledger.csv | awk -F, '{print "real equity:", $22}'

# Find update_equity / save_equity_state
grep -n "save_equity_state\|update_equity" bot/execution/risk.py | head -10
```

---

## Step 9: What's been done already (don't redo)

**Already disabled/stripped (don't undo unless intentional):**
- 4 hard-block rules in `bot/feedback/graduated_rules.json`: SOL_SHORT_full_block, HYPE_LONG_hard_block, SOL_LONG_hard_block, HYPE_SHORT_hard_block, SIZE_edge_boost
- `_SETUP_WIN_PROBS` in `bot/llm/quant_brain.py` (your aeba848 then desktop's strip)
- `REGIME_METADATA`, `SETUP_TYPES`, `ASSET_DNA` in `bot/llm/agents/shared_context.py` (desktop's 4ea0551 today)
- Confluence multipliers + time-of-day multipliers + RSI vetoes in `prompts.py`
- Inverted TOD multipliers (your f10a43a)
- Hardcoded comments WHERE THEY DON'T REACH PROMPTS in `trading_config.py` and `dynamic_thresholds.py` — left alone

**Already wired/fixed:**
- adaptive floor outcome record (your 894e077)
- graduated rules `times_correct` was supposed to be fixed by your fe2b934, but my equity audit shows it's still 0 across the board — so EITHER the fix didn't land OR the field is being read from a different file. Worth verifying.
- close persistence (your 3495711 + 0c6478f)
- Risk Agent portfolio state visibility (your 5c91984)
- Confidence calibration inversion (your 221a1d0)
- Sub-noise stop rejection (your a22e4fe + 7a863eb)
- Equity tracker partial (your 097ef2d) — still broken per my audit

**Bot currently runs:** branch `desktop-overdrive-2026-05-30`, last commit `4ea0551` (residual strips on top of merged-in laptop work `eaa852b`).

---

## Step 10: How to communicate back

**Push fixes to `historical-import-2026-05-30` with clear commit messages.** Desktop monitors and will merge into live + restart bot.

**Add brief entry to `coordination/handshake.md` only for:**
- Shipped fix (with one-line "what + why")
- Blocker (with what you found)
- Disagreement with desktop's approach

**Don't add to handshake:**
- Routine progress
- Long analyses (write to a separate file in `coordination/` and reference)

**Don't push:**
- Debug-only changes
- Speculative changes you haven't verified
- API key requests of any kind

---

## Step 11: If you're stuck

1. Read `STATE_OF_WAGMI_2026-06-05.md` Part 4 (bug inventory) — your issue might already be tracked
2. Search `coordination/handshake.md` for similar prior issues
3. Push to handshake: "blocked on X, found Y, need Z" — desktop picks it up
4. Don't spin on the same investigation for >2 hours without checking in

---

## The simple version

- Bot trades autonomously. Don't touch what's working.
- 4 things broken. Critic veto rate is the worst. Fix that first.
- Push to historical-import-2026-05-30. Desktop merges + restarts.
- One handshake entry per shipped fix. That's all.

You've got this.

-- desktop-claude
