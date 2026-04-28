# PC Claude Handoff — Read This First

You are continuing work that was done in a separate web Claude session over a full day of audit and planning. **Do not rely on any "memory context" you may think you have from prior sessions** — that was hallucinated. Everything you need is in this repository on disk.

## Bot status (as of handoff)

- **Offline 92+ hours** (last attempted restart hit 100% VETO loop)
- **Equity: $497.05 / $5,000 starting** (90.1% drawdown)
- **Last 4 trades: all losses** (`adaptive_risk_state.json` outcomes [F,F,F,F])
- **Branch you're on**: `claude/debug-neural-queue-Nye7v`
- **DO NOT restart the bot yet** — 4 BLOCKERs must clear first (see §24 of BLUEPRINT.md)

## What was found across 10 audit passes

- **110+ specific bugs** catalogued
- **21 BLOCKER/CRITICAL** items
- **2 confirmed smoking guns**:
  1. `bot/llm/claude_cli_client.py:139` reads wrong envelope field — causes 100% VETO (BLUEPRINT §22)
  2. `bot/llm/graduated_rules.py:21` reads non-existent file — kill-list rules NOT enforced (BLUEPRINT §24.2)
- **Estimated $3,350-$5,350 of identifiable money-path bugs** that may account for half the drawdown
- **The cultural root cause behind 93% of all bugs**: silent-fallback anti-pattern (BLUEPRINT §34)

## Files to read in order

### 1. The distilled action plan
`BLUEPRINT.md` — 35 sections, 4,000 lines, 232KB

Read at minimum:
- **Table of Contents** (lines 1-80) — full index + "Highest-leverage actions in order"
- **§22** (line 2176) — THE smoking gun, 4-line CLI fix
- **§24** (line 2529) — 4 BLOCKERs that must clear before restart
- **§25** (line 2650) — money-path bugs, 4-fix bundle
- **§34** (line 3619) — silent-fallback anti-pattern (the cultural fix)

### 2. The audit corpus (when you want more detail)
`docs/audits/` — 19 unsummarized agent reports, 720KB total
- See `docs/audits/README.md` for index + map of which report backs which BLUEPRINT section

## Highest-leverage Week-1 actions (do these in order)

### Step 1 — Verify the bug exists (5 min)
```bash
which claude && claude --version  # Expect 2.1.119+
echo '{"x":1}' | claude --print --output-format json --model haiku --no-session-persistence \
  --json-schema '{"type":"object","properties":{"x":{"type":"number"}},"required":["x"]}' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('has structured_output:', 'structured_output' in d)"
# Expect: has structured_output: True

grep -n 'envelope.get("result"' /home/user/WAGMI/bot/llm/claude_cli_client.py | head -2
# Expect: line 139 only reads "result", never "structured_output" — that's the bug
```

### Step 2 — Apply §22.4 fix (10 min)
Edit `bot/llm/claude_cli_client.py` line 139.

**CURRENT** (broken — reads prose, ignores actual JSON):
```python
text = envelope.get("result", "") or envelope.get("text", "") or ""
```

**REPLACE WITH**:
```python
structured = envelope.get("structured_output")
if isinstance(structured, dict):
    text = json.dumps(structured)        # serialize structured JSON to string
else:
    text = envelope.get("result", "") or envelope.get("text", "") or ""
```

That's it. No model swap, no prompt rewrite, no fallback logic.

### Step 3 — Verify §22.4 fix worked (5 min)
Save as `/tmp/test_cli_bug.py`:
```python
#!/usr/bin/env python3
import json, sys
sys.path.insert(0, '/home/user/WAGMI')
from bot.llm.claude_cli_client import call_agent, REGIME_SCHEMA, REGIME_SYSTEM
REGIME_INPUT = """BTC at $75,888. Daily UP, RSI 61, above EMA20 +3.8%, vol 1.5×, funding +0.015%, OI flat. 4h ADX 28. Classify."""
def test_model(model):
    print(f"\n=== {model.upper()} ===")
    r = call_agent(REGIME_INPUT, REGIME_SYSTEM, model=model, json_schema=REGIME_SCHEMA, timeout=60)
    print(f"ok={r.ok} latency={r.latency_s:.2f}s cost=${r.cost_usd:.4f}")
    if r.parsed:
        required = {"regime","confidence","bias","vol_band","narrative"}
        missing = required - set(r.parsed.keys())
        print(f"parsed: {json.dumps(r.parsed, indent=2)}")
        if missing: print(f"MISSING fields: {missing}"); return False
        return True
    print("parsed: None — FAIL"); return False
if __name__ == "__main__":
    h = test_model("haiku"); s = test_model("sonnet")
    print(f"\nHaiku: {'PASS' if h else 'FAIL'}\nSonnet: {'PASS' if s else 'FAIL'}")
    sys.exit(0 if (h and s) else 1)
```
Run: `python3 /tmp/test_cli_bug.py`. **Both Haiku and Sonnet must PASS.** Stop and ask user if either fails.

### Step 4 — Apply §25.11 money-path bundle (50 min)
Four edits, ~$2,000-$3,300 capital recovery:

**4a. `bot/execution/order_executor.py` line 599 (and same pattern at line 713)**
Hyperliquid taker fee is 45 bps not 2.5 bps (18× under-estimate).
```diff
- fees = notional * 0.00025
+ fees = notional * 0.0045  # 45 bps Hyperliquid Tier-0
```

**4b. `bot/execution/order_executor.py` line 593**
Paper slippage was hardcoded 1bp; real avg is 2-5bps in volatility.
```diff
- slippage = price * 0.0001
+ regime = signal.metadata.get("regime", "unknown")
+ slip_mult = {"high_volatility": 5, "panic": 8, "consolidation": 1.5}.get(regime, 2)
+ slippage = price * 0.0003 * slip_mult / 2  # 3bps × regime mult, half each side
```

**4c. `bot/execution/position_manager.py` line 1064**
TP1 partial close was rounding to full close on small qty positions.
```diff
+ if close_qty >= pos.qty * 0.95:
+     logger.warning(f"TP1 would close {close_qty} ≈ full qty {pos.qty}, skipping partial")
+     return None
```

**4d. `bot/core/signal_pipeline.py` line 291**
Fee-drag gate was passing trades using wrong fee default.
```diff
+ assert fee_bps >= 40, f"taker_fee_bps={fee_bps} below safety floor; check config"
```

### Step 5 — Clear all 4 BLOCKERs (~3 hours)

**BLOCKER 1**: Lower `MAX_CONSECUTIVE_LOSSES=3` in `bot/trading_config.py:103` (was 5; we're already at 4).

**BLOCKER 2**: Kill-list rules NOT enforced. The 16 curated rules at `bot/feedback/graduated_rules.json` use a different schema than what `bot/llm/graduated_rules.py:21` expects. Quick fix: in `bot/multi_strategy_main.py:_process_symbol()`, hardcode an early-return on `(SOL, SHORT)` and `(HYPE, LONG)` until the schema converter is built. **This is the second smoking gun — bot will reopen the exact patterns that caused $231 of losses on restart.**

**BLOCKER 3**: Set `SOFT_FILTER_LOG_ONLY=false` and `ENABLE_SOFT_FILTERS=true` in `.env` (must create `.env` if missing — currently doesn't exist).

**BLOCKER 4**: `_compute_regime_fallback` at `bot/llm/agents/coordinator.py:3166-3218` returns non-canonical regime names (`trend`, `consolidation`) that downstream agents don't recognize. Patch to return `trending_bull`/`trending_bear` based on momentum sign.

### Step 6 — Run §24.7 pre-restart smoke test (5 min)
```bash
which claude && claude --version  # 2.1.119+
cat /home/user/WAGMI/bot/data/risk_equity_state.json  # equity:497.05, peak_equity:508.06
cd /home/user/WAGMI/bot && python run.py positions  # No open positions
test -f /home/user/WAGMI/bot/data/llm/graduated_rules.json && echo OK || echo MISSING
test -d /home/user/WAGMI/bot/data/llm && touch -ac /home/user/WAGMI/bot/data/llm/.permcheck && echo WRITABLE || echo READONLY
test -f /home/user/WAGMI/bot/data/auto_optimizer_state.json && cat /home/user/WAGMI/bot/data/auto_optimizer_state.json | grep consecutive_losses || echo "fresh-start"
cd /home/user/WAGMI/bot && python -c "from llm.claude_cli_client import regime; r=regime('BTC at 75k, ETH 3500'); print('OK',r.parsed) if r.parsed else print('FAIL',r.text[:200])"
cd /home/user/WAGMI/bot && python -c "from trading_config import TradingConfig; c=TradingConfig(); print(f'soft_filter_log_only={c.soft_filter_log_only} enable_soft_filters={c.enable_soft_filters}')"
echo "WATCHDOG_STALL_THRESHOLD_S=${WATCHDOG_STALL_THRESHOLD_S:-300}"  # Want 600 after fix
cd /home/user/WAGMI/bot && python -c "from multi_strategy_main import MultiStrategyBot; from trading_config import TradingConfig; print('OK')"
```

### Step 7 — Restart in canary mode (BLUEPRINT §24.11)
- `DEFAULT_SYMBOLS=BTC` (one symbol, first 2h)
- `MAX_OPEN_POSITIONS=0` for first 4h (observation only — bot logs decisions but cannot open)
- `risk_per_trade=0.005` (0.5% of $497 = $2.50/trade) for week 1
- `MAX_SESSION_DRAWDOWN_PCT=0.10` (auto-halts at $447)

## Things you MUST NOT do

1. **Do not restart the bot** until all 4 BLOCKERs in §24 are cleared and §24.7 smoke test passes.
2. **Do not commit fixes that bypass safety gates** (circuit breaker, slippage check, soft filters).
3. **Do not delete or rename `risk_equity_state.json`** — equity will reset to $5000 default and you'll lose the actual peak/current state.
4. **Do not push to `main`** — this branch is `claude/debug-neural-queue-Nye7v`. Stay on it.
5. **Do not skip §22.7 smoke test** after applying §22.4. Verifying the fix before committing it is mandatory.
6. **Do not hardcode Sonnet for Regime Agent** — that was the OLD plan from §7-A. The §22.4 fix supersedes it. Hardcoding Sonnet is unnecessary; Haiku works fine once envelope parsing is fixed.
7. **Do not "remember" details from a prior session** — read everything from disk.

## What to do AFTER Week-1 fixes are deployed

1. **Watch for first-hour signals** (BLUEPRINT §24.8): regime non-`unknown` ≥70%, VETO rate <60%, ≥1 trade fires in 48h.
2. **If 24h clean, expand from BTC-only** to normal symbol set.
3. **Begin Week-2 work** — silent-fallback fix-loud discipline (§34). This is the highest-leverage cultural change. It prevents the next 67 bugs.
4. **Review `docs/audits/` reports** for areas you want to dig into — strategy mechanics, memory architecture, the manual trader's cockpit, etc.

## The recovery roadmap from $497 (BLUEPRINT §24.12)

- **Today (4h)**: BLOCKERs 1, 2, 4
- **Tomorrow**: BLOCKER 3, smoke test suite
- **48h**: Restart canary mode (BTC-only, observation only)
- **72h**: If clean, allow 1 position with 0.5% risk
- **Week 2**: Restore normal symbols if VETO <60% and ≥1 win realized

## Reporting back

After each step, report:
- What you changed (file:line, before/after)
- What the smoke test showed (paste output)
- Any errors or unexpected behavior
- Whether you're proceeding to next step or pausing

**If anything is unexpected, stop and ask before proceeding.** This is a 90%-drawdown system. There's no margin for new bugs.

## TL;DR

Read `BLUEPRINT.md`. Apply §22.4 (10 min). Verify with §22.7. Apply §25.11 (50 min). Clear §24's 4 BLOCKERs (~3 hours). Run §24.7 smoke test. Restart canary mode. Report after each step.

Total time to safe restart: ~4 hours. Total capital potentially recovered: $2,000-$3,300.

The audit corpus in `docs/audits/` is there if you want deeper detail on anything.
