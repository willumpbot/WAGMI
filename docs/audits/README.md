# WAGMI Audit Reports — Full Agent Output Archive

This directory contains the **complete, unsummarized output** from every audit agent that ran during the 2026-04-27/28 deep audit. The top-level [`BLUEPRINT.md`](../../BLUEPRINT.md) is the distilled actionable plan. **These files are the raw evidence behind it.**

If you find anything in `BLUEPRINT.md` that you want more detail on — code samples, full reasoning, every grep, every line of analysis — open the corresponding audit file here.

## Contents

| # | File | Topic | Size |
|---|---|---|---|
| 1 | [`01-quantification-audit.md`](01-quantification-audit.md) | Every threshold, parameter, and constant | 31K |
| 2 | [`02-cli-system-deep-dive.md`](02-cli-system-deep-dive.md) | CLI flags, envelope schema, subprocess paths | 36K |
| 3 | [`03-agent-inventory-and-new-agents.md`](03-agent-inventory-and-new-agents.md) | All 23 agents inventoried + new agent designs (incl. Opportunist) | 55K |
| 4 | [`04-strategy-ensemble-mechanics.md`](04-strategy-ensemble-mechanics.md) | Signal contract, all 11 strategies, ensemble voting | 48K |
| 5 | [`05-memory-learning-architecture.md`](05-memory-learning-architecture.md) | 14 memory stores, hypothesis bug, 5 stub modules | 60K |
| 6 | [`06-upper-bound-vision.md`](06-upper-bound-vision.md) | 5 architectural multipliers, Sharpe ceiling, 6-month roadmap | 37K |
| 7 | [`07-cli-network-verification.md`](07-cli-network-verification.md) | **THE smoking gun** — `structured_output` field bug verified | 19K |
| 8 | [`08-compressed-timeline.md`](08-compressed-timeline.md) | Compressing 6-month roadmap to 6 weeks | 24K |
| 9 | [`09-restart-blockers.md`](09-restart-blockers.md) | 4 BLOCKERs, smoke tests, canary mode design | 25K |
| 10 | [`10-cli-subprocess-lifecycle.md`](10-cli-subprocess-lifecycle.md) | 12 more CLI bugs (deadlock, dual prompt source, etc.) | 18K |
| 11 | [`11-cli-hardening-blueprint.md`](11-cli-hardening-blueprint.md) | Long-term: LLMBackend ABC, 8-step migration, file structure | 47K |
| 12 | [`12-silent-fallback-antipattern.md`](12-silent-fallback-antipattern.md) | **The root cause of 93% of bugs** — cultural fix | 80K |
| 13 | [`13-concurrency-and-dead-code.md`](13-concurrency-and-dead-code.md) | 13 bugs incl. heartbeat non-atomic, exec lock race | 23K |
| 14 | [`14-schema-mismatch-hunt.md`](14-schema-mismatch-hunt.md) | 5 silent failures across writer↔reader boundaries | 16K |
| 15 | [`15-manual-trader-path.md`](15-manual-trader-path.md) | bot/manual/ cockpit, 5-level human curriculum, 12-month vision | 33K |
| 16 | [`16-database-backtest-fidelity.md`](16-database-backtest-fidelity.md) | 13 incl. **CRITICAL look-ahead bias** in `searchsorted` | 17K |
| 17 | [`17-security-audit.md`](17-security-audit.md) | 15 vulns (4 CRITICAL: auth, restart injection, Telegram, env leak) | 20K |
| 18 | [`18-cli-integration-audit.md`](18-cli-integration-audit.md) | 16 bugs between CLI client and rest of system | 20K |
| 19 | [`19-money-path-silent-failures.md`](19-money-path-silent-failures.md) | 11 bugs, $3,350-$5,350 of identifiable loss, 4-fix bundle | 17K |

**Total: ~666KB / 19 reports / 110+ specific bugs / 21 BLOCKER/CRITICAL.**

## Reading Order

If you want **action immediately**: read [`BLUEPRINT.md`](../../BLUEPRINT.md) `§22.4` and `§25.11` only. Everything else can wait.

If you want **the whole story**: read in this order:
1. `07-cli-network-verification.md` — the smoking gun, then
2. `19-money-path-silent-failures.md` — the second smoking gun cluster, then
3. `09-restart-blockers.md` — what to do before restart, then
4. `12-silent-fallback-antipattern.md` — the cultural root cause, then
5. Browse the rest by interest.

## Map to BLUEPRINT.md sections

Every BLUEPRINT.md section traces back to one or more agent reports:

| BLUEPRINT § | Source agents |
|---|---|
| §15 (agent inventory) | 03 |
| §16 (new agents) | 03, 06 |
| §18 (by-the-numbers) | 01 |
| §19 (memory architecture) | 05 |
| §20 (strategy reference) | 04 |
| §21 (upper-bound vision) | 06 |
| §22 (the actual smoking gun) | 07 |
| §23 (compressed timeline) | 08 |
| §24 (restart blockers) | 09 |
| §25 (money-path) | 19 |
| §26 (schema mismatches) | 14 |
| §27 (CLI integration) | 18 |
| §28 (concurrency) | 13 |
| §29 (subprocess lifecycle) | 10 |
| §30 (CLI hardening) | 11, 02 |
| §32 (security) | 17 |
| §33 (database/backtest) | 16 |
| §34 (silent fallback) | 12 |
| §35 (manual trader) | 15 |

## Provenance

These reports were produced by Anthropic Sonnet/Haiku agents running in parallel during a multi-hour audit session on 2026-04-27/28. Each agent was given a focused mission and ran independently with read-only access to the codebase. The bot was offline during the audit. The audit ran in two waves with multiple parallel agents per wave.

Each file includes the original task prompt at the top so you can see exactly what the agent was asked to find.
