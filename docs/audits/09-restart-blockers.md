# Restart Blockers and Immediate Gates

*Agent ID: `a7cd34b9d6102f31c`*

---

## Original Task

```
The WAGMI trading bot at /home/user/WAGMI has been offline 92 hours. Equity is $497 (90% drawdown from $5000). The user wants to restart safely. Your job: produce the definitive "what's actually blocking restart" assessment.

**Context**: 
- 4 consecutive losses preceded the offline state
- 100% VETO when last running
- Phase 1 validation mode (SOFT_FILTER_LOG_ONLY=true) was active
- Multiple silent failure risks unaddressed (peak equity reset, deep memory unbounded, slippage warning-only, SL vs liquidation)
- The CLI network has the Regime → Haiku → JSON-failure → unknown-regime → Critic-veto bug

**Mission Part 1: Pre-restart blockers, ranked by severity**

Identify every reason the bot SHOULDN'T restart yet. For each:
- What it is
- Where the evidence is (file:line, log file, or state file)
- Severity: BLOCKER (don't restart) / HIGH (restart with mitigation) / MEDIUM (acceptable risk) / LOW (operational hygiene)
- Specific fix or mitigation
- Time to fix

Specifically check:
1. Is the position state file at `bot/data/position_state.json` consistent? Could there be untracked exchange positions?
2. Is the equity figure in `bot/api_server.py` (or wherever stored) correct? Has peak equity been reset?
3. Is the consecutive_losses counter at threshold? Does it survive restart? File: `bot/feedback/auto_optimizer.py:78,146-148`
4. Is `claude_cli_client._claude_path()` returning a valid path? Run `which claude` to verify.
5. Are the kill-list symbols (SOL_SHORT, HYPE_LONG) actually blocked, or just identified?
6. Is `decisions.jsonl` going to be writable when bot starts? (It currently doesn't exist on disk — code references it)
7. Are graduated rules from April 15 still valid given current market regime?
8. Is the watchdog at `bot/monitoring/watchdog.py` configured with correct thresholds?
9. Will the bot trip its own circuit breaker on first loss? File: `bot/execution/risk.py:295`
10. Are reconciliation routines mandatory or optional? `bot/execution/reconciliation.py`

For each: read the actual file, confirm the state, report specifics.

**Mission Part 2: Smoke-test commands to run pre-restart**

Produce the exact bash commands to run, in order, before `python run.py paper`:
```bash
# Command 1: ...
#   Expected: ...
#   On failure: ...
# Command 2: ...
```
Each command must be safe to run (no state mutation). Each must produce go/no-go output.

**Mission Part 3: First-hour-online checklist**

Once bot is online, what's the user watching for in the first 60 minutes?
- What logs to tail
- What heartbeat to verify
- What signals to expect
- What anomalies = panic-stop
- When is it safe to walk away

**Mission Part 4: The "minimum bot-online" definition**

Define "bot is functioning" precisely with measurable criteria:
- Regime classifier returning non-unknown for >X% of cycles
- Veto rate <Y%
- At least Z signals processed without crash
- Heartbeat within N seconds
- No CRITICAL/ERROR logs for M minutes

What thresholds are reasonable? Cite live data fr
```

---

## Full Report

I have all I need. Now let me write the comprehensive assessment.

# WAGMI Pre-Restart Assessment: Definitive Go/No-Go

Status: **DO NOT RESTART YET.** Fix four BLOCKERs first (estimated 2-4 hours of work), then proceed with a heavily de-risked canary.

---

## Mission Part 1: Pre-restart blockers, ranked by severity

### BLOCKER 1: Circuit breaker WILL trip on first loss (4 of 5 consecutive losses)
**What:** `consecutive_losses` is at 4. The configured threshold is `MAX_CONSECUTIVE_LOSSES=5` (`/home/user/WAGMI/bot/trading_config.py:103-104`). The CB trip logic at `/home/user/WAGMI/bot/execution/risk.py:231-232` reads `if self.consecutive_losses >= self.max_consecutive_losses`. One more loss = lockout.

But there are TWO independent loss counters:
- `CircuitBreaker.consecutive_losses` (in-memory only, reset on every restart at `risk.py:64`).
- `auto_optimizer._state["consecutive_losses"]` (persisted to `auto_optimizer_state.json` at `feedback/auto_optimizer.py:78,148,157`, threshold = 4 at `:185`).

**Evidence:** `paper_trading_2026-04-27_1800.md` line 41-44; `adaptive_risk_state.json` shows `recent_outcomes: [false, false, true, false, false]` — last 4 starting from index 0 are F, F, T(broken), F, F. The "4 consecutive losses" comes from `[false, false, false, false]` at indices 16-19.

**Severity:** BLOCKER. The CB counter resets on restart (good), but auto-optimizer state persists. However, more importantly, the bot has 4 confirmed real losses in the last session — empirically, this is a streak. Restarting on a streak with 90% drawdown is reckless.

**Fix/mitigation:** (a) Set `MAX_CONSECUTIVE_LOSSES=3` (lower, not higher — fail fast); (b) Acknowledge the streak by manually pausing on first new entry until you can confirm the regime; (c) Reset `auto_optimizer_state.json` if it exists (it currently does NOT — `find` returned nothing), so the auto-optimizer will start fresh, which is fine.

**Time:** 5 min.

---

### BLOCKER 2: Graduated kill-list rules are NOT being enforced
**What:** The code at `/home/user/WAGMI/bot/llm/graduated_rules.py:21` reads from `data/llm/graduated_rules.json`. The actual evolved rules document with kill-list signals (HYPE_LONG_near_block, SOL_SHORT_LIVE_CONTRADICTION, HYPE_LONG_DEDUP, etc.) lives at `/home/user/WAGMI/bot/feedback/graduated_rules.json` AND uses a totally different schema.

**Evidence:**
- Engine schema: `GraduatedRule` dataclass with `hypothesis_statement`, `conditions`, `adjustment`, `action` (`graduated_rules.py:24-38`).
- File schema: `rules[].rule_id, description, problem, fix_applied, status, gate_percentage, baseline_wr` (`feedback/graduated_rules.json` lines 4-30).
- The path `bot/data/llm/graduated_rules.json` does NOT exist on disk (`ls` returned no such file).
- That means the engine loads ZERO rules into `_rules` (`graduated_rules.py:86-90`), evaluates every signal against an empty rule list, and returns `_vetoed=False` for everything.
- Confirmed by `coordinator.py:4409` — when `evaluate_signal` is called, no rules will match because none are loaded.

**Implication:** The "kill list" (SOL_SHORT lost $154, HYPE_LONG lost $77) is documentation-only. The bot will happily reopen those exact same losing patterns on restart.

**Severity:** BLOCKER. The single biggest reason equity went from $5000 → $497. Restarting without enforcement = repeating the exact failure mode.

**Fix:** Either (a) hardcode a kill-list in `multi_strategy_main.py` _process_symbol() that returns early on `(SOL, SHORT)` and `(HYPE, LONG)`, OR (b) write a converter script that translates the human-curated `feedback/graduated_rules.json` rules with `status=APPLIED` and `gate_percentage=100` into the engine's `data/llm/graduated_rules.json` schema.

**Time:** 30-60 min for the hardcoded block; 2 hrs for proper conversion.

---

### BLOCKER 3: SOFT_FILTER_LOG_ONLY=true means signals ARE NOT being blocked, only logged
**What:** Phase 1 validation mode. `/home/user/WAGMI/bot/trading_config.py:593-594` defaults `SOFT_FILTER_LOG_ONLY=true`. Also `enable_soft_filters` defaults `False` at line 590-591. At `multi_strategy_main.py:4471` the log-only branch fires; the annotated-ensemble result is stored but its `hard_rejected` field is observational only — execution proceeds via the original (non-annotated) signal.

**Evidence:** `multi_strategy_main.py:4471-4500`. The signal tracker records the data but returns from the soft-filter block without re-routing. The actual go/no-go is decided downstream by mechanical gates + LLM, both of which clearly produced the losing trades.

**Severity:** BLOCKER (operationally) — every "improvement" filter you've designed in the last week is currently nonbinding. You're flying with the same filter set that produced 13.4% all-time WR.

**Fix:** Either flip `SOFT_FILTER_LOG_ONLY=false` and `ENABLE_SOFT_FILTERS=true` in `.env` (current `.env` does not exist — `ls /home/user/WAGMI/bot/.env` empty, `ls /home/user/WAGMI/.env` empty — so you need to write one), OR keep log-only but recognize that restart will not behave differently from pre-offline.

**Time:** 5 min for env flip; 30 min to validate which soft filters are actually trustworthy enough to enforce.

---

### BLOCKER 4: 100% VETO rate from CLI Regime → Haiku → JSON-failure → unknown → Critic-veto bug
**What:** When CLI Haiku regime call returns malformed JSON, the regime defaults to `unknown` (`coordinator.py:721-726`). There IS a fallback `_compute_regime_fallback` at `:728-738` which can return `trend`/`range`/`high_volatility`/`panic`/`consolidation`. However, the tier-1 router at `coordinator.py:1843` has:
```
if regime in ("low_liquidity", "unknown") and signal_conf < 60 and n_agree < 2:
    return 1   # Skip entirely
```
And the fallback technical regime returns `consolidation` as default — which is NOT a regime any downstream code recognizes as bullish/bearish, leading the Trade/Critic agents to default-veto.

**Evidence:** `coordinator.py:3166-3218` — the `_compute_regime_fallback` returns string literals (`trend`, `consolidation`, `range`, `high_volatility`, `panic`) that don't match the schema enum (`trending_bull|trending_bear|range|high_volatility|low_liquidity|news_dislocation|unknown`) at `claude_cli_client.py:204`. Downstream agents will treat unknown-string regimes conservatively → veto.

**Severity:** BLOCKER. This is the same bug that produced 100% VETO before going offline. Until either Haiku reliably returns JSON or the fallback string aligns with the downstream enum, every signal will be skipped or vetoed — and you'll burn CLI credits doing it.

**Fix:** (a) Pin regime model to Sonnet (already the default at `claude_cli_client.py:277` `def regime(... model="sonnet")`) and verify coordinator.py uses the same default. The comment at line 275-276 explicitly says "Sonnet reliably follows JSON-only; Haiku tends to return markdown prose." (b) Patch `_compute_regime_fallback` to return canonical enum strings (`trending_bull`/`range`/`high_volatility`).

**Time:** 30 min.

---

### HIGH 1: `decisions.jsonl` directory does not exist; first write may race
**What:** `/home/user/WAGMI/bot/llm/decision_engine.py:101-110` writes to `data/llm/decisions.jsonl`. The directory `bot/data/llm/` exists, but the file does not. `os.makedirs(_AUDIT_DIR, exist_ok=True)` is called inside `_log_audit` so it self-creates, but the API server (`api_server.py:190,1205,1257,1547`) reads it eagerly. If API server starts before first decision is logged, calls return empty.

**Severity:** HIGH (cosmetic for bot, breaks dashboard).
**Fix:** `touch /home/user/WAGMI/bot/data/llm/decisions.jsonl` before launch (you cannot do this — but the user can).
**Time:** 1 sec.

---

### HIGH 2: `start_session()` is never explicitly called → `session_peak_equity` is auto-init from current equity, NOT from a true peak
**What:** `risk.py:86-96` sets `session_peak_equity` only if `<= 0`. The auto-init path at `risk.py:130-132` sets it equal to current equity ($497). That means the 20% session DD limit is measured from $497, not from $508 peak or $5000 start. A drop from $497 to $397 (-20%) trips the session-halt; a drop from $508 to $397 was already worse but invisible.

**Severity:** HIGH. The "peak equity reset" risk you flagged is real — it means session-DD protection floors at the worst-case equity, not the cumulative peak. After 90% drawdown, this is actually conservative (good), but it confirms you have lost the ability to use peak-DD as a circuit breaker reference.

**Fix:** Call `cb.start_session(session_peak_equity=508.06)` at startup using the saved `risk_equity_state.json` peak. Add 1 line in `multi_strategy_main.py` after the risk_mgr init.

**Time:** 5 min.

---

### HIGH 3: Watchdog stall threshold = 300s default but scan_interval is 60s
**What:** `monitoring/watchdog.py:25` sets `STALL_THRESHOLD_S = 300` (5 min). Scan interval is 60s (`trading_config.py:72`). On a single LLM-call hang of ~90s + processing, you'd be at ~150s — still OK. But CLI calls to Sonnet routinely hit 30-60s; with 8 markets × multi-agent, a slow tick can blow past 300s.

**Severity:** HIGH for false alerts; LOW for missed real stalls.
**Fix:** Set `WATCHDOG_STALL_THRESHOLD_S=600` in env for the first day (more tolerant), tighten later.
**Time:** 1 min.

---

### HIGH 4: Slippage is warning-only with no rejection
**What:** `order_executor.py:666-670`. When fill slippage exceeds `max_slippage_pct` (default 1.5% from `MAX_ENTRY_SLIPPAGE_PCT`), it logs WARNING and proceeds. No reject, no abort, no size reduction.

**Severity:** HIGH for live; MEDIUM for paper (paper fills are synthetic so this rarely fires anyway).
**Fix:** Add a config flag `REJECT_ON_SLIPPAGE=true` and an early-return on the slippage check.
**Time:** 15 min. **Acceptable to defer if running paper-only on restart.**

---

### HIGH 5: SL-vs-liquidation gate IS wired (in `core/signal_pipeline.py:853`) but the multi-strategy execution path may bypass it
**What:** `validate_stop_vs_liquidation` exists in `leverage.py:316-343` and is called from `signal_pipeline.py:853`. But `multi_strategy_main.py` doesn't grep-match this function call. Confirm by reading the multi-strategy entry path.

**Severity:** HIGH. If any path produces a leveraged trade where SL is past liquidation, it's silently catastrophic. Paper mode is safe; live mode is not.

**Fix:** Audit `_process_symbol` -> `_open_position` chain in `multi_strategy_main.py`. Confirm leverage.validate_stop_vs_liquidation is called pre-execution. If not, add it. **Acceptable on paper restart.**

**Time:** 1 hr.

---

### MEDIUM 1: Position state file at `bot/data/position_state.json` does not exist
**What:** `find /home/user/WAGMI -name "position_state.json"` returned nothing. `auto_recovery.py:29` looks for `data/position_state.json`. On startup, the bot will log "No position state file found (first run?)" (`auto_recovery.py:237`) and then call `_reconcile_exchange_positions` (`multi_strategy_main.py:1351`).

**Severity:** MEDIUM. This is fine for paper mode (no real exchange positions). For live mode, the reconciliation routine queries Hyperliquid directly — if there ARE untracked positions on the exchange (you've been offline 92 hrs), it WILL recover them with **estimated** SL/TP from ATR (per `reconciliation.py:7-13`), losing your actual exit levels.

**Fix:** Run `python run.py positions` first (read-only, prints any open exchange positions). If any exist, manually close them on Hyperliquid before restart. **For paper-only, no concern.**

**Time:** 5 min.

---

### MEDIUM 2: Equity is correct ($497.05) and consistent
**What:** `bot/data/risk_equity_state.json` reads `{"equity": 497.0523, "saved_at": "2026-04-23T22:17:05", "peak_equity": 508.0609}`. This is the correct value matching the report.

**Severity:** N/A (resolved). The starting_equity default in `trading_config.py:76` is 10000 from env `STARTING_EQUITY`, but the risk manager will load $497 from persisted state at `risk.py:428-433`. Confirmed by the 10x-ratio safety guard at `risk.py:489-495`.

---

### MEDIUM 3: trades.csv has only the header
**What:** `wc -l trades.csv = 1`. The file at `/home/user/WAGMI/bot/trades.csv` contains only the schema row. The 352 resolved trades referenced in the report come from elsewhere (likely `data/db.py` SQLite). On restart, equity reconstruction at `risk.py:504-529` (the fallback path) would compute `fallback + sum(trades.csv) = $5000 + 0 = $5000` if `risk_equity_state.json` were ever deleted. As long as that JSON file exists, you're safe.

**Severity:** LOW (booby trap). Don't delete `risk_equity_state.json`.

---

### MEDIUM 4: Deep memory unbounded
**What:** `deep_memory.py:519,598,673` cap at 1000/500/500 entries respectively, `:140` caps trades at 500. The BIG one is `insight_journal.json` already at 97 KB with no visible cap. After 92 hrs offline, this is fine; at 6 months online, it could OOM the LLM context.

**Severity:** MEDIUM. Not a restart blocker.

---

### LOW 1: `claude` CLI is at `/opt/node22/bin/claude`, version 2.1.119
**What:** `which claude` returned `/opt/node22/bin/claude` — `_claude_path()` at `claude_cli_client.py:40-53` will find it via `shutil.which`. Confirmed working.

**Severity:** N/A. **Resolved.**

---

### LOW 2: No `.env` file exists at root or in bot/
**What:** Both `/home/user/WAGMI/.env` and `/home/user/WAGMI/bot/.env` do not exist. `run.py:393-403` calls `load_dotenv` but silently no-ops if missing. `.env.example` exists at root with template values.

**Severity:** LOW. All config will be defaults from `trading_config.py`. **Discord/Telegram alerts will not fire** unless env is created.

---

## Mission Part 2: Smoke-test commands to run pre-restart

```bash
# 1. Confirm claude CLI binary works
which claude && claude --version
#   Expected: /opt/node22/bin/claude on first line, "2.1.119 (Claude Code)" on second
#   On failure: install/repair node22 + claude package; do not proceed

# 2. Confirm equity state file is intact and matches reports
cat /home/user/WAGMI/bot/data/risk_equity_state.json
#   Expected: {"equity": 497.05..., "peak_equity": 508.06...}
#   On failure: do NOT restart with starting_equity=10000 — the bot will think it has $10K

# 3. Check there are no exchange positions to reconcile (live mode only)
cd /home/user/WAGMI/bot && python run.py positions
#   Expected: "No open positions."
#   On failure: manually close on Hyperliquid before restart

# 4. Confirm graduated_rules engine has rules to load
test -f /home/user/WAGMI/bot/data/llm/graduated_rules.json && echo OK || echo MISSING
#   Expected (after fix): OK
#   On MISSING: kill-list is not enforced — see Blocker 2

# 5. Confirm decisions.jsonl exists (or at least its directory is writable)
test -d /home/user/WAGMI/bot/data/llm && touch -ac /home/user/WAGMI/bot/data/llm/.permcheck && echo WRITABLE || echo READONLY
#   Expected: WRITABLE
#   On READONLY: chmod the directory

# 6. Verify auto_optimizer state is fresh (no stale 4-loss counter)
test -f /home/user/WAGMI/bot/data/auto_optimizer_state.json && cat /home/user/WAGMI/bot/data/auto_optimizer_state.json | grep consecutive_losses || echo "fresh-start"
#   Expected: "fresh-start"
#   On stale: confirm the value is < 4

# 7. Dry-run the regime classifier to confirm Haiku/Sonnet returns valid JSON
cd /home/user/WAGMI/bot && python -c "from llm.claude_cli_client import regime; r = regime('BTC at 75000, ETH 3500, SOL 180. 24h chg: BTC +2.1%, ETH +1.8%, SOL -0.5%.'); print('OK', r.parsed) if r.parsed else print('FAIL', r.text[:200])"
#   Expected: "OK {'regime': '...', 'confidence': ..., 'bias': '...', ...}"
#   On FAIL: regime classifier broken — DO NOT RESTART (would 100% veto)

# 8. Verify SOFT_FILTER_LOG_ONLY current setting
cd /home/user/WAGMI/bot && python -c "from trading_config import TradingConfig; c = TradingConfig(); print(f'soft_filter_log_only={c.soft_filter_log_only} enable_soft_filters={c.enable_soft_filters}')"
#   Expected (Phase 1): "soft_filter_log_only=True enable_soft_filters=False"
#   This is informational — confirms you're still in observation mode

# 9. Confirm watchdog stall threshold env override is set
echo "WATCHDOG_STALL_THRESHOLD_S=${WATCHDOG_STALL_THRESHOLD_S:-300}"
#   Expected (after recommended fix): 600

# 10. Sanity-check the python imports
cd /home/user/WAGMI/bot && python -c "from multi_strategy_main import MultiStrategyBot; from trading_config import TradingConfig; print('OK')"
#   Expected: "OK"
#   On import error: dependency broken
```

If all 10 say OK, proceed. If any fail, fix before launch.

---

## Mission Part 3: First-hour-online checklist

**What to tail:**
```bash
tail -f /home/user/WAGMI/bot/logs/paper_trading.log
tail -f /home/user/WAGMI/bot/data/llm/decisions.jsonl
```

**Heartbeat verification (T+2 min):**
- `cat /home/user/WAGMI/bot/data/heartbeat.json` should show `last_alive` within last 90s and a valid `pid`.
- If still missing at T+5 min, the bot crashed silently — `kill -SIGTERM` and check stderr.

**Signals to expect (T+5 min):**
- At least one log line `[INIT] Loaded persisted equity: $497.05`.
- Watchdog start: `Watchdog started: stall_threshold=600s`.
- First scan: `[ROUTER] Tier X` appears for at least 1 symbol.
- Regime line: `[MULTI-AGENT] Regime: <some-non-unknown-string>` — if every line says `unknown`, BLOCKER 4 still bites.

**Anomalies = panic-stop (Ctrl-C):**
- 3+ consecutive `[CIRCUIT BREAKER TRIPPED]` lines in first 10 min — config too tight, restart not safe.
- Any `[RECOVERY] Loaded N positions from state file` where N > 0 (you didn't expect carryover).
- `[ORDER] HIGH SLIPPAGE` followed by an actual fill (live mode only).
- `[LLM-AVAILABILITY] SYSTEM DEGRADED: 3 consecutive failures` — CLI broken.
- 100% veto on first 5 signals (this is the regime bug recurring).
- Any line containing "Session DD" or "session_halt" — your session-peak guard fired = stop immediately.

**Safe to walk away when:**
- T+60 min with at least 5 successful tick cycles, no CRITICAL/ERROR logs in last 10 min, watchdog status clean (`stalled: false`, `consecutive_stalls: 0`), and at least 1 non-veto LLM decision logged to decisions.jsonl.

---

## Mission Part 4: "Minimum bot-online" definition

The bot is functioning when ALL of these hold for 30 continuous minutes:

| Metric | Threshold | Source |
|---|---|---|
| Regime non-unknown rate | ≥ 70% of cycles | `decisions.jsonl` field `regime` |
| LLM veto rate | < 60% (down from 100%) | `is_veto` field count / total |
| Heartbeat freshness | last_alive within 90s | `data/heartbeat.json` |
| Signals processed without crash | ≥ 8 ticks | scan_count in heartbeat |
| CRITICAL/ERROR lines | 0 in last 10 min | log grep |
| Equity drift | within ±2% of $497 | `risk_equity_state.json` |

The 70/60% thresholds are deliberately lenient because the report cited "100% VETO when last running." Anything materially better than 100% veto is progress. Tighten weekly: target 40% veto rate, 80% non-unknown regime by week-2.

Live data anchor: from `paper_trading_2026-04-27_1800.md`, recent-20 WR is 35%, all-time 13.4%, trending regime 51.9% WR. So a "healthy" bot should bias trades toward trending and avoid illiquid/ranging — we'd expect to see fewer trades overall (good).

---

## Mission Part 5: Rollback plan

**Panic button (single command):**
```bash
pkill -f multi_strategy_main && echo "STOPPED at $(date -u +%H:%M:%S)"
```

**Restore prior config:** There is no formal version-controlled rollback for runtime config. Your authoritative state is the env file (none exists yet), `risk_equity_state.json`, and `position_state.json`. To "rollback" to the pre-restart state:
1. Stop bot.
2. `cp /home/user/WAGMI/bot/data/risk_equity_state.json /tmp/equity.bak` (snapshot before restart so you can restore).
3. If equity got worse, restore from /tmp.

**Recover from bad position state:** Delete `/home/user/WAGMI/bot/data/position_state.json` to force a clean reconciliation against the exchange on next start. Only do this if you've manually verified Hyperliquid has zero open positions.

**One-command "panic safe":**
```bash
pkill -f multi_strategy_main; pkill -f run.py; cp /home/user/WAGMI/bot/data/risk_equity_state.json{,.panic.$(date +%s)}; echo "Bot stopped, equity snapshotted"
```

---

## Mission Part 6: Things that can ONLY be verified post-restart

These are unknowable until the bot runs:

1. **Live regime classification accuracy** — the static smoke test calls regime once on a synthetic prompt; under real market data with 8 symbols and full snapshot, JSON-malformedness is more common.
2. **Live agent latency** — full pipeline (Regime → Quant → Trade → Critic → Risk) under real load may exceed the 300s watchdog default and trigger false stalls.
3. **CLI subscription rate-limit** — `--max-budget-usd 0.10` per call × 5 agents × 8 symbols × 60s scan = 40 calls/min sustained. Whether the Max plan tolerates this is not knowable from grep.
4. **Real fill quality** (paper executor uses last-price approximations, not orderbook-aware fills).
5. **Cross-symbol race conditions** in `_executing_symbols` lock at `multi_strategy_main.py:681-682`.
6. **Veto rate under real conditions** — the structural bug fix can be checked, but actual rate emerges only from production traffic.

**De-risk plan:**
- **Canary:** Restrict to 1 symbol (BTC only) for first 2 hours. Edit env: `DEFAULT_SYMBOLS=BTC` (verify in `trading_config.py`).
- **Time-box:** First 4 hours = "observation only." Set `MAX_OPEN_POSITIONS=0` so the bot logs decisions but cannot open. Then flip to 1 for the next 4 hrs.
- **Capital cap:** Override `risk_per_trade=0.005` (0.5% of $497 = $2.50 per trade) for week 1.
- **Session DD:** Set `MAX_SESSION_DRAWDOWN_PCT=0.10` (10%, half the default) so it auto-halts at $447.

---

## Mission Part 7: Restart-vs-fix-first decision tree

**Recommendation: WAIT 24-48 HOURS. Fix the 4 BLOCKERs first.**

**Reasoning:**
- 90% drawdown = $497 cushion. One full ATR move on a leveraged position = -10% to -20% in minutes. There is no margin for the bugs to re-manifest.
- 4 consecutive losses just preceded the offline state. Statistically, 4-in-a-row on a 35% recent-20 WR is borderline (probability ≈ 18%). Not necessarily regime-broken, but absolutely consistent with continued bleeding.
- Three of the four BLOCKERs are 30-min-each fixes. The kill-list one is the most valuable: it directly addresses the patterns that took $231 of the $4503 lost ($154 SOL_SHORT + $77 HYPE_LONG = 5% of cumulative DD attributable to two known-bad patterns).
- Restart-now's only positive is "stop opportunity cost," but with 35% recent-20 WR and negative-edge symbol concentration, the cost of staying offline is approximately $0/hour — possibly positive (avoiding losses).

**The rebuttal "empirical data > theoretical analysis" applies at higher equity levels.** At $497 and a structural kill-list-not-enforced bug, you are not collecting data — you are losing capital to known issues for the second time.

**Timing recommendation:**
- **Today (next 4 hrs):** Fix BLOCKERs 1, 2, 4 (CB threshold lower, kill-list enforced, Sonnet pinned for regime).
- **Tomorrow:** Fix BLOCKER 3 (flip soft filters live with audit), then run smoke-test suite.
- **48 hrs from now:** Restart in canary mode (BTC-only, observation only — `MAX_OPEN_POSITIONS=0`).
- **72 hrs:** If canary clean, allow 1 position with 0.5% risk per trade.
- **Week 2:** Restore normal symbol set if veto rate < 60% and at least one win realized.

**Do NOT restart now** because: empirical losses preceded the outage, the documented kill-list is not enforced in code (Blocker 2 is the smoking gun), and the regime bug (Blocker 4) caused the 100% veto symptom that is functionally identical to "bot offline" except more expensive.

---

## Critical Files for Implementation

- `/home/user/WAGMI/bot/llm/graduated_rules.py` (engine reads non-existent rules file — rewire kill-list)
- `/home/user/WAGMI/bot/llm/agents/coordinator.py` (regime fallback, JSON enforcement, kill-list call site at :4393, fallback enum mismatch at :3166-3218)
- `/home/user/WAGMI/bot/multi_strategy_main.py` (soft-filter wiring at :4471, CB call at :4994, `start_session()` not invoked, position reconciliation at :1351)
- `/home/user/WAGMI/bot/execution/risk.py` (CB threshold at :231, peak_equity reset at :316, equity persistence at :478-572)
- `/home/user/WAGMI/bot/trading_config.py` (defaults: `MAX_CONSECUTIVE_LOSSES`, `SOFT_FILTER_LOG_ONLY`, `STARTING_EQUITY`, `WATCHDOG_STALL_THRESHOLD_S`)