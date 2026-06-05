# WAGMI Overnight Autonomous Operations Handbook

**Created:** 2026-05-31 by desktop-claude
**Purpose:** Both Claudes work autonomously while Nunu sleeps. This handbook governs roles, boundaries, and corroboration. Read at start of every action.

---

## TL;DR for each Claude

**Desktop-Claude:** monitor live bot every 30-60 min, audit code for hidden bugs (no quota burn), apply small surgical fixes with high confidence, document everything in `analysis/desktop-session/`, push to `desktop-overdrive-2026-05-30`.

**Laptop-Claude:** run focused backtests on volatile windows now that subscription has reset, push results to `analysis/historical/`, watch quota carefully, stop if 429 errors hit, push to `historical-import-2026-05-30`.

**Both:** corroborate via `coordination/handshake.md`. Tag findings with confidence levels. Wake Nunu only for true emergencies. Make incremental progress, document everything.

---

## 1. Operating Principles

1. **Quota is the constraint.** Subscription reset just now. Don't burn it carelessly.
2. **Make incremental progress.** Small commits, document each one.
3. **Trust the trust hierarchy.** Wired live data > mechanical math > historical baselines > caution.
4. **Boundaries matter.** Don't touch each other's work. Don't make destructive changes.
5. **Document for the morning Nunu.** Every decision point captured in handshake.md.
6. **When in doubt, do nothing material and document the question.** Tag `[READY-FOR-NUNU]`.

---

## 2. Roles & Boundaries

### Desktop-Claude (this PC, where live bot runs)

**Mission:** Make sure the live bot is on the right path. Monitor, audit, document, apply surgical fixes.

**Allowed actions:**
- Read live bot logs, decisions.jsonl, counterfactuals
- Audit code files for bugs (Python `read`, `grep`, no execution that burns quota)
- Apply small fixes to non-running code paths (snapshot wiring, parser bugs, etc.)
- Edit `.env` configuration (with documentation)
- Edit `graduated_rules.json` (rare, with documentation)
- Restart bot if necessary (max 2x overnight to preserve quota — each restart burns startup cycles)
- Document findings in `analysis/desktop-session/journal-2026-05-30.md`
- Push to `desktop-overdrive-2026-05-30` branch
- Append to `coordination/handshake.md` (this branch via worktree)

**NOT allowed:**
- Burn LLM quota for testing (no synthetic `python -m claude_cli_client` smoke tests unless verifying a critical bug)
- Make changes to laptop's branch (`historical-import-2026-05-30`)
- Modify `historical/old-bot-pre-2026-04-23/*` (frozen archive)
- Push to `main`
- Disable safety circuit breakers (daily-loss CB, consecutive-loss cap)
- Restart bot more than 2x overnight without explicit reason

### Laptop-Claude (other PC, runs backtests)

**Mission:** Collect data via focused backtests. Analyze results. Generate evidence the desktop bot can use.

**Allowed actions:**
- Run `python run.py backtest --symbols X --days N --llm --budget Y --raw` on focused windows
- Use `--start-date` flag (recently added) to target specific windows
- Push results to `analysis/historical/layer{N}-results.md`
- Read desktop's journal and apply findings to backtests
- Append to `coordination/handshake.md`

**NOT allowed:**
- Multi-day backtests > 30 days (too expensive in quota)
- Backtests without `--budget` cap (always cap at $3-5)
- Changes to live bot code paths
- Make changes to desktop's branch
- Push to `main`
- Run sequential backtests without pause — wait between runs to check 429 errors

---

## 3. Quota Management

**The subscription has rolling limits, typically ~5 hour windows.**

**Live bot consumption:** ~4 LLM calls per 30s scan = ~480/hour. Mostly Haiku (Scout) + some Sonnet (Trade) + Opus (Regime/Risk/Critic).

**Laptop backtest consumption:** ~4 calls per signal × signal density. Pilot 3 hit limit at candle ~48 of 82 in one window.

**Rules:**
1. **Watch for 429 errors** in your output. If you see them, stop immediately and document.
2. **Don't both hammer Sonnet/Opus simultaneously.** If laptop is running a backtest, desktop should NOT trigger pipeline restarts.
3. **If quota burn becomes concerning** (e.g., 60%+ used in 1 hour), pause new operations.
4. **Live bot has priority.** It must keep running to demonstrate the architecture.

---

## 4. Communication Protocol

### handshake.md tagging system

| Tag | Meaning | When to use |
|---|---|---|
| `[DESKTOP-IMPACT]` | Finding affects live bot config/code | Laptop discovers something live bot should know |
| `[LAPTOP-IMPACT]` | Finding affects how backtests should run | Desktop discovers something laptop should change |
| `[READY-FOR-NUNU]` | Decision needed, pausing material work | Either Claude hits a judgment call |
| `[PROVEN]` | Finding has n≥30 with consistent pattern | High confidence finding |
| `[SUGGESTIVE]` | Finding has n=10-30 | Moderate confidence, worth pursuing |
| `[SPECULATIVE]` | Finding has n<10 or relies on assumptions | Low confidence, mention as hypothesis |
| `[FIXED]` | Bug fix applied, what + where + when | Document every fix |
| `[QUOTA-WARNING]` | Approaching rate limits | Pause material work, log usage |

### Handshake entry format

```markdown
## YYYY-MM-DD HH:MM UTC — [machine]-claude

**from:** desktop-claude OR laptop-claude
**tag:** [PROVEN] / [SUGGESTIVE] / [DESKTOP-IMPACT] / etc
**what:** one-line summary
**details:**

what I observed (numbers, file paths, specific evidence)
what I concluded (with confidence level)
what I did (commit SHA if applicable)

**needs-from-other-side:** explicit asks, or "none"
```

### Push frequency

- After every meaningful action (fix, finding, decision)
- At least once every 60 min if active
- "I'm pausing" entry if you're stopping work
- "I'm resuming" entry if you re-start

---

## 5. Live Bot Health Criteria

### Healthy (no action)
- Heartbeat < 90s
- Bot completed at least one full multi-agent pipeline in last hour
- No 429/error spam in last 100 log lines
- Equity within $4,800 - $5,200

### Concerning (investigate, document)
- 0 trades AND no fresh agent decisions in last 2 hours
- Same skip reason repeated 5+ times in a row (after our trust-hierarchy fixes)
- New error type appearing in logs
- Heartbeat 90s-300s

### Critical (wake Nunu — handshake `[READY-FOR-NUNU]` tag + add to STATE.md)
- Heartbeat > 5 minutes
- Bot completely down for >30 min
- Account equity drop >5% (>$250 loss)
- Subscription completely blocked (all model calls failing)
- Disk full or system resource error

---

## 6. Desktop-Claude — Specific Overnight Tasks

In priority order, do these IF you have spare cycles between health checks.

### Tier 1 (highest value, no quota burn)
1. **Audit `position_manager.py`** for hidden gates between agent decision and order placement.
2. **Audit `execution/order_executor.py`** for execution gates.
3. **Audit `execution/leverage.py`** — leverage calculation might cap to 0 in some edge cases.
4. **Find all `return None` / `return False` paths** between trade decision and position open. List them.
5. **Map exact data flow** from `coordinator.py` output → `multi_strategy_main.py` → `signal_pipeline.py` → `position_manager.py`. Document any silent drops.
6. **Look at the LLM agents' actual JSON outputs** in `agent_performance.jsonl` — are they emitting the fields the parser expects? Where are mismatches?

### Tier 2 (analysis, no quota burn)
7. **Re-run `missed_opportunities.py`** on the 584 counterfactuals (was 235 yesterday). Check if ETH all-miss pattern holds at higher N.
8. **Look at the recent Scout watchlist entries** — are predictions panning out?
9. **Build per-symbol confidence distribution** — what's the distribution of confidence the agents are emitting?
10. **Cross-reference graduated_rules.matching_rules data** flowing into agents — verify the wiring is producing what we think.

### Tier 3 (only if confident, surgical fixes)
11. **Lower additional gates** if you find them (Tier 1 work surfaces these).
12. **Fix any new parser bugs** discovered in agent output analysis.
13. **Apply additional shadow-edge or rule-disable** changes if data supports.

### What NOT to do
- Don't restart bot unless required for a fix
- Don't tune prompts further (we've already done aggressive surgery)
- Don't add new agents
- Don't run synthetic LLM calls
- Don't touch `bot/llm/agents/coordinator.py` orchestration logic without [READY-FOR-NUNU]

---

## 7. Laptop-Claude — Specific Overnight Tasks

In priority order. **Always use `--budget` cap. Always pause between runs to check 429.**

### Tier 1 (validate the new live-bot config)
1. **Re-run Pilot 3** (April 23-28 cascade window) with the new permissive gates. Specifically:
   - The conf_floor_70_v1 rule is now disabled
   - ENSEMBLE_CONFIDENCE_FLOOR is now 20
   - MIN_SIGNAL_EV is now -3.0
   - Trade Agent + Critic Agent have new TRUST HIERARCHY prompts
   - Quant parser is fixed
   - Use: `python run.py backtest --symbols BTC --days 5 --start-date 2026-04-23 --llm --budget 3 --raw`
2. **Compare new Pilot 3 results to old Pilot 3.** Specifically:
   - How many of the 47 cascade trades does new LLM SKIP?
   - For the trades it takes, what's the WR?
   - Did Trade Agent stop saying "skip" after the trust hierarchy?
3. **Push results to `analysis/historical/layer2-pilot3-v2-results.md`**.

### Tier 2 (broader validation)
4. **Run pilot on a different volatile window** — e.g., a known trending window where current bot's setup should profit.
   - Use `--start-date` to target a specific known-good window
   - Cap at 5 days max
5. **Test ETH BUY specifically** since we found the ETH boost rule was broken:
   - `python run.py backtest --symbols ETH --days 10 --llm --budget 3 --raw`
6. **Document agent decision distribution** in pilot — how often go vs skip vs flip per agent.

### Tier 3 (if quota allows)
7. **Layer 3 prep** — extended-range backtest to validate the architecture before Nunu wakes up.
8. **Cross-reference desktop findings** — if desktop documents any new bugs, validate in next backtest.

### What NOT to do
- Don't run multi-day backtests > 30 days
- Don't run without `--budget`
- Don't run sequential backtests back-to-back — pause and check quota
- Don't modify live bot code
- Don't push to main
- Don't claim a finding without sample size context

---

## 8. Corroboration Patterns

### Pattern 1: Desktop finds bug
1. Desktop documents in journal + commits + pushes to `desktop-overdrive-2026-05-30`
2. Desktop appends `[DESKTOP-IMPACT]` handshake entry on `historical-import-2026-05-30`
3. Laptop reads handshake on next push cycle
4. Laptop validates in next backtest (if quota allows)
5. Laptop pushes `[VALIDATED]` or `[CONTRADICTED]` handshake response

### Pattern 2: Laptop finds pattern
1. Laptop documents in pilot results + commits + pushes
2. Laptop appends handshake entry with tag (`[PROVEN]` / `[SUGGESTIVE]` / `[SPECULATIVE]`)
3. Desktop reads handshake on next health-check cycle
4. If `[PROVEN]` and has `[DESKTOP-IMPACT]`: desktop applies to live bot
5. If `[SUGGESTIVE]` or `[SPECULATIVE]`: desktop documents but waits for more evidence

### Pattern 3: Either hits emergency
1. Stop material work
2. Append `[READY-FOR-NUNU]` handshake entry with full context
3. Update `coordination/STATE.md` with current critical issue
4. Wait — don't make material decisions until Nunu wakes

---

## 9. End-of-Shift Protocol (When Nunu Wakes Up)

Each Claude should have a `[MORNING-BRIEFING]` handshake entry ready containing:

**Top 3 findings tonight** (with tags):
- Each finding: what, evidence, [PROVEN/SUGGESTIVE/SPECULATIVE]

**Top 3 actions taken**:
- Each action: what was done, commit SHA, expected effect

**Top 3 questions / decision points**:
- Each: what's the question, why we paused for Nunu, what we'd recommend

**Quota burn estimate**:
- Approximate LLM calls used this session
- Subscription headroom remaining

**Bot status snapshot** (desktop only):
- Trades taken (count + brief summary)
- Equity
- Notable agent decisions

---

## 10. Decision Tree When Unsure

```
Is this a surgical fix with high confidence?
├── YES → Do it, document, commit, push
└── NO → Continue:
    Will this affect the live bot's behavior significantly?
    ├── YES → [READY-FOR-NUNU] entry, pause, wait
    └── NO → Continue:
        Will this burn significant quota?
        ├── YES → Document the proposed action, pause for now
        └── NO → Proceed with most conservative interpretation
```

---

## 11. Reference: Current State (as of handbook creation)

**Live bot:**
- PID 18592, restarted ~22 min ago (was 08:21 UTC)
- ENSEMBLE_CONFIDENCE_FLOOR=20, MIN_SIGNAL_EV=-3.0, MIN_SIGNAL_RR=1.0
- Trade + Risk + Critic prompts have TRUST HIERARCHY
- Shadow edges, skip patterns, graduated rules wired into snapshot
- Disabled rules: night_session_block_v1, conf_floor_70_v1
- ETH boost rule condition fixed: trending_bull
- Quant parser fixed
- 0 trades, 584 counterfactuals
- Full pipeline hasn't run since 03:54 UTC (rate-limited, just reset)

**Laptop:**
- Pilot 3 completed (3 trades on April 23-28 window, -$73 net)
- Quota just reset
- Ready to run more backtests

**Commits to read:**
- Desktop: `3481de6` (journal), `089940a` (Critic + Quant), `06007cc` (Trust Hierarchy)
- Laptop: `d56edc0` ([READY-FOR-NUNU-REVIEW]), `8ea7d30` (Pilot 3 complete)

---

## 12. Things NOT to Do — A Final Reminder

1. Don't add `ANTHROPIC_API_KEY` to `.env` — CLI/subscription routing is the architecture.
2. Don't push to `main` — Nunu reviews and merges.
3. Don't make destructive changes without explicit Nunu authorization.
4. Don't claim numbers without sample size + date range context.
5. Don't run synthetic LLM calls to "test" agents — production traffic is enough signal.
6. Don't burn through quota without pause-and-check.
7. Don't override Nunu's stated preferences from earlier in the session (overdrive mode, no OneDrive, no API key, "Nunu" identity).
8. Don't restart the live bot more than 2x overnight unless critical.
9. Don't tune prompts further beyond the current state — we've done aggressive surgery.
10. Don't speculate; tag uncertainty honestly.

---

**End of Handbook.**

This document is durable. Update only when an architectural decision changes. Append a `[HANDBOOK-UPDATE]` handshake entry if you modify it.
