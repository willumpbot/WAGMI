# Laptop Claude Briefing — Resume Context

**Generated:** 2026-06-06 22:45 UTC by desktop-claude
**Purpose:** Get the fresh laptop Claude session up to speed without re-asking Nunu

---

## Quick state check — run this first

```bash
cd C:/Users/vince/WAGMI && git fetch origin historical-import-2026-05-30
git log --oneline origin/historical-import-2026-05-30 -15
tail -100 coordination/handshake.md
cat bot/data/risk_equity_state.json
cat bot/data/position_state.json
wc -l bot/data/trade_ledger.csv
tasklist 2>&1 | grep python.exe
tail -10 bot/logs/bot_20260606.log
```

---

## Right-now snapshot (2026-06-06 22:45 UTC)

- **Branch (desktop live):** `desktop-overdrive-2026-05-30`
- **Branch (coordination):** `historical-import-2026-05-30` (where we push handshakes)
- **Bot PID:** 40064 (started 22:31:12 UTC on patched code)
- **Equity:** $4,966.36 (peak today $5,055.95)
- **Open positions:** 0
- **Ledger rows:** 14 (some closes still missing — see P1 history below)
- **Daily PnL:** -$36.94 (small conservative-leverage trades, mostly closed by Exit Agent)

---

## Who's who

- **Desktop Claude (me):** Runs on Nunu's desktop, manages the live trading bot, ships fixes, monitors via 45-min autonomous loops
- **Laptop Claude (you, after restart):** Runs on Nunu's laptop, does deep analysis, ships code fixes, coordinates via git
- **Live bot:** Python process on desktop, single source of truth, runs `bot/run.py paper` via Task Scheduler

We coordinate via `coordination/handshake.md` (append-only). Every cycle pushes a tagged entry.

---

## Critical Nunu rules (preserve VERBATIM)

1. **USE_CLI_LLM=true** in `bot/.env`. NEVER ask for ANTHROPIC_API_KEY. All LLM calls route through `claude -p` subscription.
2. **Push ONLY to `historical-import-2026-05-30`** branch. Never push to main.
3. **Don't restart bot unless** code change is material AND positions are 0.
4. **Don't run a second bot.** Desktop bot is the only one — laptop bot would create state divergence.
5. **Don't write to gitignored** `bot/data/*` in commits.
6. **Don't skip hooks** (--no-verify) unless explicitly requested.

---

## Today's work — what's been shipped (in chronological order)

1. **cycle 19 audits** — desktop found Quant Brain WR baseline poisoning, edge-finder showed SHORT bias structural, alpha ops collector was dead. Started `bot/tools/funding_oi_collector.py` in background — now feeding live funding/OI/premium data.
2. **P1 (CSV write bug)** — desktop shipped initial fix at `multi_strategy_main.py:3211` (use `_captured_pos`). Later found to be incomplete.
3. **P2 (WR baseline poisoning)** — laptop's `7146864` added `get_system_baseline()` to `dynamic_stats.py`. Removed hardcoded "35% WR" / "31% WR" / "48% WR" from `prompts.py`. Desktop cherry-picked into local branch around 20:35 UTC.
4. **P3 (counterfactual scaling)** — same root cause as P1 (pos becomes None → entry_price=0 → safety floor 0.01 → -35,868% amplification). Same fix.
5. **Critic veto** — laptop's `abd9c93` strengthened veto requirements (ALL 3 fields: price + timeframe + falsifiable). Cherry-picked to desktop.
6. **Claude CLI Windows path** — laptop's `bc22d60` prioritized `claude.cmd` over shell wrapper. Cherry-picked.
7. **Strategy weights rebalance** — laptop disabled `omniscient_integrated` (0% WR -$1534), boosted `confidence_scorer` (only profit center +$338). Applied to runtime file — may need verification.
8. **P1 v2 (real fix shipped 22:32 UTC)** — desktop found the actual root cause: stale-position cleanup at `multi_strategy_main.py:4126` was deleting closed positions BEFORE the pending Exit Agent event was processed. Added a guard: skip cleanup if symbol has pending exit event. Bot restarted on PID 40064.

---

## What you (laptop) shipped today (incredible work)

Per your `SESSION_2026_06_06_FINAL_REPORT.md`:
- 7 improvements shipped autonomously
- 633 multi-agent decisions extracted from live logs
- 231 historical trades analyzed
- $22K forgone-profit opportunity identified (confidence floor)
- omniscient_integrated killer disabled
- Phase 1 trade archaeology complete

---

## Open issues for next cycle

1. **Verify P1 v2 fix works** — next LLM_EXIT_AGENT close should grow `trade_ledger.csv`. Without this, learning loop misses outcomes.
2. **Sonnet timeout / Haiku fallback for Trade Agent** — bot has hard-frozen twice today on Sonnet calls (52min + 2hr). Desktop flagged this as the highest reliability priority. Not yet shipped. Code suggestion in handshake cycle 34.5.
3. **Strategy weights file sync** — your runtime tweaks to `ml_data/strategy_weights.json` may not be committed. Verify desktop has them.
4. **Confidence floor lowering** — your $22K analysis suggested 65% → 60%. Not yet applied to running code.
5. **Counterfactual store purge** — historical entries with `|delta| > 100%` are data errors from the pre-P3-fix era. May still be skewing learning.
6. **HL reconcile param** — bot logs `[RECONCILE] Failed to fetch positions from Hyperliquid: requires user parameter` on startup. Cosmetic but worth a one-line fix.

---

## Coordination protocol (45-min autonomous cycles)

### Desktop's cycle (we run this every 45min via ScheduleWakeup)
```
1. git fetch origin historical-import-2026-05-30
2. git log --oneline origin/historical-import-2026-05-30 -10
3. tail -60 of coordination/handshake.md
4. Check: tasklist | grep python  (verify bot PID)
5. Check: tail -5 bot/logs/bot_$(date +%Y%m%d).log  (freshness)
6. Check: wc -l bot/data/trade_ledger.csv  (any new closes)
7. Check: cat bot/data/position_state.json  (current positions)
8. Check: cat bot/data/risk_equity_state.json  (equity)
9. Push handshake entry (only if something material)
10. ScheduleWakeup with same prompt to continue loop
```

### Tags we use in handshake
- `[CYCLE-N]` — coordination cycle number
- `[SHIPPED]` — code change deployed
- `[BUG-FOUND]` — new bug discovered
- `[VALIDATED]` — fix proven to work
- `[FOR-DESKTOP]` / `[FOR-LAPTOP]` — direct ask
- `[BLOCKED]` — waiting on something
- `[STEADY-STATE]` — nothing material to report

### When to push vs skip
- Push if: shipped code, found bug, observed close, completed audit
- Skip if: 3+ quiet cycles in a row with no new data

---

## Key files to know

```
bot/multi_strategy_main.py       # main trading loop (P1 fixes live here)
bot/llm/agents/dynamic_stats.py  # P2 fix here (get_system_baseline)
bot/llm/agents/prompts.py        # agent prompts (Critic veto fix here)
bot/llm/agents/coordinator.py    # multi-agent pipeline
bot/llm/claude_cli_client.py     # Windows CLI fix here
bot/core/position_wiring.py      # _check_llm_exit_suggestions lives here
bot/tools/funding_oi_collector.py  # alpha ops collector (must be running)
coordination/handshake.md         # our async message bus
coordination/COORDINATION_PROTOCOL.md  # rules for cycles
bot/data/trade_ledger.csv         # canonical trade history
bot/data/risk_equity_state.json   # current equity
bot/data/position_state.json      # current positions
bot/logs/bot_YYYYMMDD.log         # daily log
```

---

## What to do FIRST after reading this

1. `git pull origin historical-import-2026-05-30` (get latest commits)
2. Run the quick state check at top
3. Grep `bot/logs/bot_20260606.log` for `[TRADE_CLOSED]` to see today's activity
4. Read the last 200 lines of `coordination/handshake.md`
5. Push an ACK to handshake confirming you're back online and aware

---

## Don't make these mistakes

- **Don't claim a fix is "VERIFIED LIVE" without checking it's actually loaded.** Branches diverge. The live bot reads from `desktop-overdrive-2026-05-30` branch's local files, NOT from origin. (Desktop made this mistake at cycle 25 — claimed P2 was live when it wasn't on the desktop branch yet.)
- **Don't ask Nunu for ANTHROPIC_API_KEY.** It's CLI_LLM only.
- **Don't run a backtest as the primary validation tool.** The live logs ARE the validation data. We've been trading on multi-agent decisions for days.
- **Don't be too verbose in handshake.** Each entry should be terse, tagged, action-oriented.
- **Don't push without re-fetching.** Origin moves fast when both of us are working.

---

## Nunu's mood as of last conversation

- Worried about how equity dropped (it didn't drop much today; the bigger losses were historical from omniscient_integrated)
- Confused about regression of hardcoded values (turns out they were never actually removed earlier — they were added April 12)
- Restarted both his computer AND his Claude session
- Wants the loop autonomous so he can sleep
- Trusts the trading approach but needs honest reporting

---

## Contact

If you need to ping desktop synchronously, push handshake entry with tag `[FOR-DESKTOP]` and your priority. I check every 45 min via my autonomous wakeup loop.

**Welcome back. The bot is running. We're a team.**
