# Skills Audit — 2026-04-29

**Question:** `.claude/skills/` has 41 markdown files (slash commands). Are they all live and useful, or has the directory accumulated dead skills?

**Headline:** **Skills are in clean shape — 41 files, all documented in CLAUDE.md, all referenced commands valid.** The opposite pattern from `bot/tools/` (where 70 of 75 are unused). Skills appear to be actively curated.

The one gap is **CLI modes underrepresented in skills**: 7 of 9 `cli.py` modes have no skill wrapping them.

---

## Inventory

- **41 skill markdown files** in `.claude/skills/`
- **Total: 4,979 lines** of skill prose
- **Average: 121 lines per skill**
- **Smallest:** `babysit.md` (39 lines)
- **Largest:** `system-map.md` (201 lines)

The size distribution suggests skills are right-sized — small enough to scan, big enough to capture multi-step flows. No 500-line monsters, no 5-line stubs.

---

## All 41 Skills (alphabetized)

```
add-agent              agent-consistency      agent-debug           agent-replay
alert-config           babysit                babysit-sniper        backtest
bug-triage             confidence-calibrate   config-audit          cost-audit
curriculum-advance     deploy-paper           edge-finder           evolution
exit-review            growth-report          health-check          knowledge-distill
loss-autopsy           memory-optimize        model-route-tune      optimize
paper-status           pnl-maximize           prompt-calibrate      refactor
roadmap-status         safety-audit           setup-edge            signal-check
sniper-setup           strategy-discover      stress-test           system-map
telegram-signals       thesis-track           trade-postmortem      veto-review
web-dashboard
```

---

## Cross-Check 1: Skills ↔ CLAUDE.md Documentation

CLAUDE.md lists every skill in its "Custom Skills" section.

**Result:** **100% coverage.** Every skill file exists; every file is documented in CLAUDE.md. No orphaned skills, no documentation drift.

(The grep showed two `/missed` and `/trigger` matches in CLAUDE.md but those are inline references to trade outcomes ("missed trades") and triggers — not skill links. False positives.)

---

## Cross-Check 2: Skills ↔ Bot Commands

Skills reference these bot commands:

| Command | Skills using it | Validity |
|---|---|---|
| `python run.py paper` | deploy-paper, paper-status, etc. | ✅ valid |
| `python run.py signals` | signal-check | ✅ valid |
| `python run.py backtest --symbols X --days N` | backtest | ✅ valid |
| `python cli.py --mode evolve` | evolution | ✅ valid |
| `python cli.py --mode optimize ...` | optimize | ✅ valid |
| `python tools/intel_collector.py` | babysit | ✅ exists |
| `python tools/overwatch_analyzer.py` | babysit | ✅ exists |

**Result:** every bot command referenced by a skill exists in the codebase.

---

## Cross-Check 3: CLI Modes Not Surfaced by Skills

`cli.py` supports modes: `paper, replay, live, evolve, tiers, optimize, compare, walkforward, gate`.

| Mode | Has dedicated skill? | Notes |
|---|---|---|
| paper | ⚠️ indirect (deploy-paper, paper-status) | covered |
| replay | ❌ NO | gap |
| live | ❌ NO | intentional? live trading is high-stakes |
| evolve | ✅ evolution.md | |
| tiers | ❌ NO | gap |
| optimize | ✅ optimize.md | |
| compare | ❌ NO | gap |
| walkforward | ❌ NO | gap |
| gate | ❌ NO | gap |

**5-7 CLI modes are operator-runnable but have no skill convenience wrapper.** Replay, walkforward, and gate are particularly notable — they're advanced validation modes that would benefit from a guided skill flow.

---

## Topical Coverage

Skills cluster around themes:

| Theme | Skills | Count |
|---|---|---|
| **Daily ops** | signal-check, health-check, paper-status, evolution, trade-postmortem | 5 |
| **Development** | backtest, optimize, stress-test, deploy-paper, refactor | 5 |
| **Code quality** | safety-audit, cost-audit, config-audit, bug-triage | 4 |
| **Agent dev** | add-agent, agent-debug, agent-consistency, agent-replay, prompt-calibrate, model-route-tune | 6 |
| **Memory/learning** | memory-optimize, knowledge-distill, curriculum-advance, growth-report | 4 |
| **Profitability** | pnl-maximize, edge-finder, loss-autopsy, sniper-setup, strategy-discover, setup-edge | 6 |
| **Predictions** | thesis-track, exit-review, veto-review, confidence-calibrate | 4 |
| **System** | system-map, roadmap-status, telegram-signals, alert-config, web-dashboard | 5 |
| **Continuous** | babysit, babysit-sniper | 2 |

**6 skills are profitability-focused** — that's a healthy weighting for what the project is trying to do.

---

## Skills That May Be Stale (worth verifying)

These skills mention features that I have reason to suspect are dormant:

### `babysit.md`

Wraps `tools/intel_collector.py` and `tools/overwatch_analyzer.py`. Both exist, but the wider tools audit (§11) flagged that 70 of 75 tools are unused. Does babysit work end-to-end if those tools haven't been recently maintained?

**Verification:** read both tools, confirm they don't reference deleted modules, run a dry pass.

### `add-agent.md`

Per §09, 13 of 23 agent roles are already fully implemented but unwired. So `/add-agent` may be encouraging the very pattern that produced the dead-code problem (build the agent, never wire it). The skill should be updated to **end with a wiring checklist**: "Add to `multi_strategy_main.py:_tick_once` or `coordinator.py.tick()` at line N."

**Recommendation:** §09's wiring plan would update this skill to prevent future drift.

### `web-dashboard.md`

Per §03/§04, the web dashboard story is fragmented — three backends, 18 pages. This skill probably needs updating once the §05 HL-style reshape stabilizes. Right now it points users at infrastructure that's mid-rebuild.

### `curriculum-advance.md`

Per CLAUDE.md, this drives self-teaching curriculum levels. Per §12, growth subsystem is wired. So this skill should work — but worth running once after §02 fixes to confirm proposals are now actually applying.

---

## Skill Quality Score (subjective spot-check)

I read 3 skills end-to-end:

- **`/pnl-maximize`** (140 lines) — well-structured, clear inputs/outputs/thresholds. Good template.
- **`/system-map`** (201 lines) — comprehensive inventory directive. Useful for new contributors / Claude sessions.
- **`/babysit`** (39 lines) — terse but functional. Could grow with more guard rails.

No major quality issues found in samples. Skills directory is in noticeably better health than tools directory.

---

## Recommended Skill Additions (5 small wins)

Wrappers for the orphan CLI modes:

1. **`/replay`** — wraps `python cli.py --mode replay`. Replay engine against trade logs with anomaly report. Useful for "did we make the right call on 2026-03-15?"
2. **`/walkforward`** — wraps `--mode walkforward`. Walk-forward validation. Critical for "is the edge stable across time periods?"
3. **`/gate`** — wraps `--mode gate`. Gate effectiveness analysis. Tied to §02 directly.
4. **`/compare`** — wraps `--mode compare`. Side-by-side run comparison. Pairs with `/backtest`.
5. **`/tiers`** — wraps `--mode tiers`. LLM tier comparison report.

Each is ~80 lines (template-able from `/optimize` or `/evolution`). ~4 hours total.

---

## Recommended Skill Updates (3)

1. **`/add-agent`** — add explicit wiring checklist at end (per §09 finding).
2. **`/web-dashboard`** — update once §05 reshape lands.
3. **`/babysit`** — verify both referenced tools still work end-to-end; add error-handling guidance.

---

## Bottom Line

Skills are the **best-curated directory in the project**. Stark contrast to:

- `bot/tools/` (75 files, 70 unused) — needs hygiene
- `bot/llm/agents/` strategic+phase4+phase4a (~1,100 lines, 13 unwired) — needs wiring (§09)
- `bot/feedback/swarm/` overrides — needs reading (§08)

Given how many other directories have rot, the curation here is impressive and worth maintaining. The only material gap is the 5 orphan CLI modes — cheap to fix.

**Time investment:** ~4-6 hours total to add 5 missing skills + update 3 stale ones.
**Operational impact:** moderate — skills are how the operator interacts with the bot's diagnostic surface. More skill coverage = more leverage from a phone session.
