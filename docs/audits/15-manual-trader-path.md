# Manual Trader's Path to Greatness

*Agent ID: `acd1d1fd36c7cc768`*

---

## Original Task

```
You are designing the **manual trader's path to greatness** for the WAGMI trading bot at /home/user/WAGMI. The user emphasized this is a critical missing piece. The bot has an autonomous trading layer, but ALSO has a manual trading layer (`bot/manual/` — 36 files, allegedly "abandoned" but the user says it matters).

**Mission**: produce a definitive blueprint for what the manual trader's tooling should be, audit what exists today, identify gaps, propose the upgrade roadmap.

### A. Inventory the manual layer
Read `/home/user/WAGMI/bot/manual/` — all 36 files.
For each file:
- One-line purpose
- Status: actively used / referenced but unused / abandoned / unclear
- Last meaningful change (git log)
- Imports from where? Imported by what?
- Key functions exposed
- Dependencies on rest of bot (position_manager, risk, exchange?)

Categorize:
- Trade entry tools (anticipatory_entries, manual_entry, etc.)
- Position management (manual_close, position_adjust, trade_journal)
- Analysis tools (deep_analysis, post_trade_review)
- Educational / training (paper trading helpers, replay)
- Other

### B. Inventory the manual-trading skills
The `.claude/skills/` directory likely has manual-relevant skills:
- `/babysit` — manual monitoring loop
- `/babysit-sniper` — sniper-signal monitoring
- `/sniper-setup`, `/setup-edge`, `/loss-autopsy`, `/edge-finder`
- `/trade-postmortem`, `/pnl-maximize`

For each: what does it do? Working or stale? Inputs/outputs. Use cases for a manual trader.

### C. The Telegram interface for manual control
- File: `bot/alerts/telegram_bot.py:62-2200`
- All commands inventoried for manual use:
  - `/status`, `/positions`, `/equity`
  - `/signal SYMBOL SIDE ENTRY SL TP` — manual signal injection
  - `/close SYMBOL`, `/closeall`
  - `/pause`, `/resume`
  - `/mode 0..5`
  - Any others?
- Which are "view-only" (safe) vs "money-moving" (dangerous)?
- What's missing for a manual trader who wants to:
  - Override LLM veto on a setup they believe in
  - Adjust SL/TP mid-position
  - Scale into / out of positions partially
  - Get LLM analysis on demand for any symbol
  - Log thesis BEFORE entering and verify post-trade

### D. The sniper system (`bot/llm/sniper.py`)
- Independent from main pipeline
- Trades what bot sits out on
- Can a human user invoke sniper analysis on a symbol they're considering?
- Manual sniper vs autonomous sniper modes
- The "manual sniper signal monitoring loop" (/babysit-sniper)

### E. The trade journal layer
Look for: `trade_journal`, `trade_diary`, `trade_review`, `postmortem`
- Is there a structured place for the human to log thesis BEFORE entry?
- Is there post-trade review tooling (auto-comparison of thesis vs outcome)?
- Lessons-learned aggregation (what patterns am I personally good/bad at?)
- Calibration: am I overconfident as a human?

### F. The "human + AI co-pilot" model
The original design intent (per CLAUDE.md and skills) is human + AI working together. But the bot can autopilot. What's the IDEAL co-pilo
```

---

## Full Report

I have enough. Delivering the full blueprint now.

---

# WAGMI Manual Trader's Path to Greatness — Definitive Blueprint

The user is correct: the manual layer is NOT abandoned. It is one of the most actively developed and battle-tested parts of WAGMI (308 tests pass against it; `multi_strategy_main.py` lines 542–4387 wire it into the live signal pipeline; `bot/manual/CONTEXT.md` documents it as a first-class system targeting "$100 → $1000 in 45 days"). What is missing is not the substrate — it is the **integrated user-experience around it**. This blueprint inventories what exists, identifies the seams, and proposes a concrete recovery + greatness roadmap.

---

## A. Inventory of `/home/user/WAGMI/bot/manual/` (41 files, ~20.3K lines)

`__init__.py` is empty namespace. The other 40 files split into five categories. Last meaningful changes are recent: most recent `git log --all -- bot/manual` activity is `2026-04-21 12:27` ("liquidation safety info") and `2026-04-20 14:24` ("profit-lock fix"). The directory is being actively shipped.

**Category 1 — Signal generation & filtering (the "manual sniper engine"):**
- `/home/user/WAGMI/bot/manual/sniper_filter.py` (1287 lines): `ManualSniperFilter`, `SniperSignal`. THE core. Six gates (confidence ≥ 78%, ≥2 agree, R:R ≥ 1.2, regime allow, dedup, cooldown). Tier classifier (STANDARD/PREMIUM/SNIPER). Dynamic leverage by stop-width. Imported by `multi_strategy_main.py:542`. **Status: actively used.**
- `/home/user/WAGMI/bot/manual/config.py` (166 lines): `ManualSniperConfig` (env-driven). `MANUAL_DAILY_TARGET=$20`, conviction floors, regime allowlists. **Actively used.**
- `/home/user/WAGMI/bot/manual/anticipatory_entries.py` (2039 lines): pre-emptive entry detection — anticipates setups before full strategy agreement. `get_anticipation_engine`, `_compute_indicators`. Imported by `multi_strategy_main.py:586,1866`. **Actively used.**
- `/home/user/WAGMI/bot/manual/expanded_setups.py` (306 lines): catalogue of new setup definitions from research. **Reference data, used by sniper_filter.**
- `/home/user/WAGMI/bot/manual/dip_detector.py` (181 lines), `dip_buy_analysis.py` (415 lines): dip-buy entry research + live detector.
- `/home/user/WAGMI/bot/manual/signal_scorer.py` (288 lines): scoring used by sniper.
- `/home/user/WAGMI/bot/manual/conviction_sizer.py` (573 lines): translates sniper tier + confidence + stop-width → leverage + size. **Critical — this is the bot's "how big to bet" brain.**

**Category 2 — Position management & journaling:**
- `/home/user/WAGMI/bot/manual/position_rules.py` (818 lines): `ManualPositionManager`, `Phase`, `Action`, `RuleParams`, `PositionUpdate`. Per-tier rules for partial close (`partial_close_pct=0.50`), breakeven moves, trailing logic. Tested in `test_hardening_edge_cases.py:433`. **Actively used.**
- `/home/user/WAGMI/bot/manual/trade_journal.py` (500 lines): `TradeJournal`, `JournalEntry`. Append-only `data/manual/trade_journal.jsonl`, equity tracker starting from $100, compounding report. Methods: `log_entry`, `log_exit`, `get_open_trades`, `get_stats`, `get_compounding_report`. Wired into `/trade` and `/exit` Telegram commands. **Actively used.**
- `/home/user/WAGMI/bot/manual/execution_helper.py` (256 lines): `HyperliquidOrderBuilder`, limit-offset logic. **Actively used.**
- `/home/user/WAGMI/bot/manual/alerts.py` (309 lines): `ManualSniperAlerter` — Telegram formatting for sniper signals. Imported by `multi_strategy_main.py:543`. **Actively used.**

**Category 3 — Simulation & paper:**
- `/home/user/WAGMI/bot/manual/simulator.py` (1021 lines): `SniperSimulator` — paper-trades every signal on virtual $100, logs `data/manual/sim_trades.jsonl`. **Actively used.**
- `/home/user/WAGMI/bot/manual/pa_simulator.py` (1233 lines): price-action simulator (more realistic than `simulator.py`). **Status: parallel implementation, both live.**
- `/home/user/WAGMI/bot/manual/signal_tracker.py` (360 lines): `SignalValueTracker` for outcome resolution. Imported by `multi_strategy_main.py:559`. **Actively used.**
- `/home/user/WAGMI/bot/manual/backtest_sniper.py` (702 lines), `backtest_threshold.py` (945 lines): historical validation harnesses.

**Category 4 — Analysis, optimization, learning:**
- `/home/user/WAGMI/bot/manual/edge_analysis.py` (792 lines): Kelly, Monte Carlo, edge confidence intervals.
- `/home/user/WAGMI/bot/manual/edge_discovery.py` (414 lines): scans for new edges from outcome data.
- `/home/user/WAGMI/bot/manual/optimizer.py` (818 lines): `SniperOptimizer` — weekly parameter recommendations. Tested.
- `/home/user/WAGMI/bot/manual/risk_optimization.py` (373 lines): Monte Carlo for risk sizing.
- `/home/user/WAGMI/bot/manual/filter_validation.py` (691 lines): out-of-sample validation of filter changes.
- `/home/user/WAGMI/bot/manual/deep_analysis.py` (1319 lines): deep counterfactual & signal-outcome forensics.
- `/home/user/WAGMI/bot/manual/time_edge_analysis.py` (352 lines): time-of-day edge.
- `/home/user/WAGMI/bot/manual/mean_reversion_research.py` (318 lines): mean-reversion specific.
- `/home/user/WAGMI/bot/manual/trade_learner.py` (674 lines), `trade_scorecard.py` (456 lines): post-trade learner per setup.
- `/home/user/WAGMI/bot/manual/sniper_filter.py` shares responsibilities with `signal_scorer.py` — slight duplication.

**Category 5 — Reporting & ops:**
- `/home/user/WAGMI/bot/manual/runner.py` (315 lines): standalone `python -m manual.runner --once|--status` — exists but rarely run; dashboard subsumes it. **Underused.**
- `/home/user/WAGMI/bot/manual/health_check.py` (380 lines): system diagnostic.
- `/home/user/WAGMI/bot/manual/generate_playbook.py` (572 lines): produces `data/manual/TRADING_PLAYBOOK.md`. **Underused but high-value.**
- `/home/user/WAGMI/bot/manual/generate_report.py` (103 lines): weekly report.
- `/home/user/WAGMI/bot/manual/overnight_report.py` (330 lines): overnight summary.
- `/home/user/WAGMI/bot/manual/daily_tracker.py` (433 lines): per-day P&L vs $20 daily target.
- `/home/user/WAGMI/bot/manual/executive_dashboard.py` (153 lines): single-page status. Worth lifting into Telegram `/briefing`.
- `/home/user/WAGMI/bot/manual/performance.py` (404 lines): actual-vs-signal compare.
- Markdown: `CONTEXT.md`, `MORNING_KICKOFF.md`, `MORNING_PROMPT.md`, `RESTART_GUIDE.md`, `TROUBLESHOOTING.md` — operator runbooks.

**Verdict on the "abandoned" claim:** false. The runner CLI is rarely invoked, the markdown runbooks are static, and several research files (`mean_reversion_research`, `dip_buy_analysis`) are one-shot scripts that produced their report and froze — but the *engine* (sniper_filter + alerts + simulator + journal + position_rules + conviction_sizer + anticipatory_entries) is wired live and tested. The user's instinct is right: this layer matters and deserves a deliberate UX wrap.

---

## B. Manual-Trading Skills in `/home/user/WAGMI/.claude/skills/`

42 skills total. The manual-relevant ones:
- `/home/user/WAGMI/.claude/skills/babysit.md` — every-cycle paper-trading overwatch loop, runs `tools/intel_collector.py` + `tools/overwatch_analyzer.py`, updates `bot/data/PAPER_TRADING_LEARNINGS.md`. **Working.**
- `/home/user/WAGMI/.claude/skills/babysit-sniper.md` — manual sniper system overwatch (signal quality, sim performance, optimization opportunities). **Working — heavy diagnostic command in step 1, well-defined.**
- `/home/user/WAGMI/.claude/skills/sniper-setup.md` — reverse-engineers top R-multiple wins into a sniper template. **High value, matches user's request N.**
- `/home/user/WAGMI/.claude/skills/setup-edge.md` — per-setup-type WR/PF table from `decisions.jsonl` × `trades.csv`. **Working.**
- `/home/user/WAGMI/.claude/skills/loss-autopsy.md` — categorizes losses (BAD ENTRY / BAD EXIT / BAD SIZING / EXTERNAL). **Working.**
- `/home/user/WAGMI/.claude/skills/edge-finder.md` — by-regime/strategy/symbol/time/setup edge mapping. **Working.**
- `/home/user/WAGMI/.claude/skills/trade-postmortem.md` — per-trade execution + decision quality review. **Working.**
- `/home/user/WAGMI/.claude/skills/pnl-maximize.md` — meta-skill that orchestrates the others. **Working.**
- `/home/user/WAGMI/.claude/skills/thesis-track.md` — thesis vs outcome accuracy.
- `/home/user/WAGMI/.claude/skills/confidence-calibrate.md` — calibration drift detection (currently agent-targeted, not human-targeted — gap).
- `/home/user/WAGMI/.claude/skills/exit-review.md` — exit decision quality.
- `/home/user/WAGMI/.claude/skills/health-check.md`, `evolution.md`, `growth-report.md`, `roadmap-status.md` — operator views.

**Gaps:** every skill above is *bot-centric* (analyzes the bot's outputs). None is *trader-centric* (analyzes the human's outputs). There is no `/my-calibration`, `/my-rules`, `/my-postmortem`, `/coach-me`. That asymmetry is the single biggest UX hole.

---

## C. Telegram Interface for Manual Control (`/home/user/WAGMI/bot/alerts/telegram_bot.py`, 2716 lines)

The command surface is much richer than the file's docstring (lines 5–13) lets on. The actual handler dispatch (lines 186–262) registers 60+ commands. Categorized by safety:

**View-only / safe:**
`/status`, `/positions`, `/equity`, `/journal`, `/sniper`, `/sim`, `/simstatus`, `/perf`, `/performance`, `/ml`, `/llm`, `/health`, `/syshealth`, `/uplift`, `/progression`, `/proposals`, `/ops`, `/roadmap`, `/curriculum`, `/knowledge`, `/signals`, `/accuracy`, `/growth`, `/risk`, `/rl`, `/survival`, `/learn`, `/edge`, `/edges`, `/thesis`, `/copytrades`, `/telemetry`, `/briefing`, `/digest`, `/live`, `/quiet`, `/loud`, `/snapshot`, `/costs`, `/tracker`, `/intel`, `/pnl`, `/missed`, `/tier`, `/silence`, `/menu`, `/commands`, `/help`.

**Money-moving / dangerous:**
`/close <SYM>` (line 509), `/closeall` (526), `/pause`, `/resume`, `/mode <0-5>` (558 — flips LLM autonomy), `/kill <SYM>`, `/unkill`, `/promote`, `/demote`, `/approve <id>` (proposal sandbox), `/reject <id>`, `/signal SYM SIDE ENTRY SL X TP Y` (1577 — queues to `data/manual_signals.json` for next scan), `/trade SYM SIDE PRICE Nx QTY` (1706 — logs to journal), `/exit SYM PRICE REASON` (1773), `/manage SYM ENTRY` (1972 — position-management advice), `/siminject` (1002), `/optimize`, `/replay`.

**AI-collaboration:**
`/ask <question>` (2057), `/copilot <idea>` (2181 — full play with entry/SL/TP/leverage/thesis/risk/confidence), `/analyze <SYM>`, `/watch`, `/alerts`.

**What exists but is underused — the inline-button approve/reject flow:**
- `build_alert_buttons` at line 2626 emits a 3-button keyboard (Log trade / Ask brain / Dismiss).
- `_handle_callback` at line 2641 dispatches presses with LRU `_pending_alerts` cache.
- The docstring at line 2630 says: "*Not used yet by default — will be wired after the next bot restart.*"

This is a one-line change away from being live. **Critical missing wire-up.**

**What's still missing for a manual trader who wants to:**

| Need | Today | Gap |
|---|---|---|
| Override LLM veto | No path — `/signal` queues a fresh signal but the same risk gate evaluates it; no force-flag | Add `/force-signal` requiring 2-step confirm + thesis text, logs to `manual_overrides.jsonl` |
| Adjust SL/TP mid-position | No command | Add `/setsl SYM PRICE`, `/settp SYM PRICE` |
| Scale in/out partially | No command (position_rules.py:73 has `partial_close_pct` but no Telegram surface) | Add `/scaleout SYM PCT`, `/scalein SYM USD` |
| LLM analysis on demand | `/ask` and `/copilot` exist | Working — possibly add `/why SYM` for a quick "why did the bot skip this?" |
| Pre-trade thesis logging | None — `bot/llm/thesis_tracker.py` exists for the LLM but no manual entry path | Add `/pre SYM SIDE "thesis text" CONF` writing to `data/manual/pre_trade_theses.jsonl` |
| Verify thesis post-trade | None | Add `/postmortem SYM` cross-referencing the pre-trade thesis with outcome |

---

## D. The Sniper System (`/home/user/WAGMI/bot/llm/sniper.py`)

Two distinct sniper systems live in the codebase, and they are easily confused:
1. **`bot/manual/sniper_filter.py`** — *deterministic filter* on ensemble signals. No LLM. Tier classifier. This is what runs every scan and feeds Telegram alerts.
2. **`bot/llm/sniper.py`** — *LLM-only sniper engine* for **ensemble-rejected** single-strategy signals. Lifecycle (lines 14–22): ensemble rejects with `insufficient_votes` → callback fires → LLM evaluates proceed/skip → if proceed + conf ≥ 0.65 → `SniperProposal` saved to a queue → dashboard renders pending proposals → operator approves/rejects. Gated by `LLM_SNIPER_ENABLED`. Default model `claude-haiku-4-5`. Tight stops (0.5× ATR), conservative size (0.5×), aggressive leverage (5–12× by confidence tier).

**Can a human invoke sniper analysis on a symbol of their choosing?** Not directly. There is no `/sniper-eval BTC LONG` command. The user can ask `/copilot` for an opinion, but it does not flow through the same `LLMSniperEngine` prompt template (`_build_prompt`, line 109). **Gap.**

The `/babysit-sniper` skill (`.claude/skills/babysit-sniper.md`) is the closest thing to a human-driven sniper monitoring loop and works well — but it is a Claude Code session, not a real-time alert.

---

## E. Trade Journal Layer

What exists:
- `/home/user/WAGMI/bot/manual/trade_journal.py` (500 lines): structured `JournalEntry` (entry/exit/PnL/notes) with `log_entry`/`log_exit`/`get_compounding_report`. Storage: `data/manual/trade_journal.jsonl`. Connected to Telegram via `/trade` (1706), `/exit` (1773), `/journal` (1832), `/equity`. **Solid.**
- `/home/user/WAGMI/bot/llm/thesis_tracker.py` (`ThesisRecord`, `ThesisTracker`, lines 26/109): the **bot's** thesis records, not the human's. Methods include `record_thesis`, `close_thesis`, `get_accuracy_stats`, `_compute_calibration`, `get_pending_theses`. Storage: `data/llm/`.
- `/home/user/WAGMI/bot/llm/post_trade_learner.py`, `trade_autopsy.py`, `reflection_engine.py`: bot-side post-trade analysis.

**What is missing for the human:**
1. **Pre-trade thesis logging.** Nowhere can the user write *before* entering: "I'm taking this because X, expected outcome Y by time Z, confidence W%." `JournalEntry.notes` exists (line 52) but is set on entry only, has no `confidence` field, and no expected-outcome/time-bound contract.
2. **Auto-comparison thesis vs outcome for the human.** `thesis_tracker.py:_compute_calibration` does exactly this for the LLM. There is no equivalent that reads a `manual_pre_trade_theses.jsonl` and computes the **human's** Brier score / calibration curve / setup-by-setup edge.
3. **Personal lessons-learned aggregation.** `MORNING_KICKOFF.md` mentions `bot/data/manual/SNIPER_LEARNINGS.md` — that is bot-system learnings. There is no `MY_LESSONS.md` for human-side patterns ("I'm bad at HYPE_LONG on Fridays").
4. **Personal calibration tracking.** `confidence-calibrate.md` skill targets agents only.

These four gaps are the heart of the "post-trade learning loop FOR THE HUMAN" (request L).

---

## F. Human + AI Co-Pilot — Workflow Coverage Today

| Workflow | Coverage Today | Where |
|---|---|---|
| Bot identifies setup → human reviews → human approves | **Partial.** Sniper alerts arrive in Telegram with inline approve/reject buttons defined (`build_alert_buttons` line 2626) but **NOT WIRED** to outgoing alert messages by default. `_send_alert` does not pass `reply_markup`. | `bot/alerts/telegram_bot.py:2626`, `multi_strategy_main.py:4277` (`send_sniper_alert`) |
| Human spots setup → queries bot's analysis → human decides | **Working.** `/copilot <idea>` (line 2181) returns full play. `/ask` (2057) for free-form. | `bot/alerts/telegram_bot.py:2057,2181` |
| Human logs intent → Critic stress-tests → human enters | **Missing.** `bot/llm/agents/pre_trade_simulator.py` (`PreTradeSimulator.simulate`, line 51) exists and runs in `multi_strategy_main.py:6393` for *bot-generated* signals only. Needs a `/preflight SYM SIDE ENTRY SL TP` command that routes through `PreTradeSimulator` + a Critic agent and returns risk profile **before** the human commits. |
| Mid-position: human gut says exit → Exit Agent validates | **Partial.** `bot/llm/exit_engine.py:39` (`ExitEngine`) exists; not exposed via Telegram. Needs `/exit-check SYM` returning the Exit Agent's recommendation. |

The infrastructure exists for all four; only one (free-form copilot) is fully wired.

---

## G. Mobile Experience

The user is on Claude Code mobile. Mobile-relevant surfaces today:
- **Telegram (works):** primary control. Strong.
- **Dashboard (`bot/api_server.py` + `bot/dashboard/server.py`):** REST API at `/v1/*` (40+ endpoints visible: `/v1/positions`, `/v1/account`, `/v1/sniper/recent`, `/v1/agents/overview`, `/v1/forensics/analysis`, `/v1/copy/status`, `/v1/portfolio/allocation`). HTML index files do not appear in `bot/dashboard/`. The **security audit's XSS risk** is a known unresolved concern — do not expose public until patched.
- **Voice → Telegram:** not implemented.
- **Push notifications:** Telegram messages serve as push. Quality is mixed — `/quiet`/`/loud`/`/digest` modes (lines 2242–2260) help, but alert content density varies.
- **Inline buttons on alerts:** **wired in code, not in default send path.** This is the highest-leverage mobile fix.

---

## H. Manual → Autonomous Promotion Path

The five LLM modes (`/home/user/WAGMI/bot/llm/autonomy.py:30`):
- `LLMMode.OFF (0)` — pure strategy.
- `LLMMode.ADVISORY (1)` — observes, logs, no influence.
- `LLMMode.VETO_ONLY (2)` — can reject.
- `LLMMode.SIZING (3)` — scales position size.
- `LLMMode.DIRECTION (4)` — picks direction.
- `LLMMode.FULL (5)` — full autonomy.

These map onto the **knowledge roadmap** (`bot/llm/knowledge_roadmap.py:155` `PHASE_CONFIGS`). Gates per phase are explicit:
- Phase 1 → 2: 50 signals observed, 20 trades, 10 patterns, 4 strategies fingerprinted, ≥48h.
- Phase 2 → 3: 10 hypotheses tested, ≥55% counterfactual accuracy, ≥55% veto accuracy, ≥55% signal-analysis accuracy, 5 validated principles, ≥168h.
- Phase 3 → 4: 30 predictions at ≥55%, sizing-uplift positive, win-rate stable, ≥60% signal-analysis accuracy, 3 sniper profiles built, ≥504h, max stake $200.
- Phase 4 → 5: direction-uplift positive, profit-factor OK, no error bursts, ≥65% signal-analysis accuracy, error rate <5%, ≥1080h, max stake $1000.

Demotion triggers (lines 129–131): WR <45% over 50 trades → drop to phase 4; 3+ error bursts → phase 3; daily loss >8% → phase 2 emergency.

**Enforcement:** `get_llm_mode` (autonomy.py:39) reads `LLM_MODE` env var and clamps it to `get_recommended_llm_mode()` from the roadmap. Real enforcement. The user CAN override (`manual_override` field, line 254), and `/promote`/`/demote` commands are wired.

**What is NOT enforced:** these gates are about the *bot's* readiness, not the *human's*. There are no human-side gates ("you must have logged 20 manual trades with calibration error <10% before increasing real-money stake"). That is a major missing concept and the centerpiece of request Q below.

---

## I. Educational / Curriculum for the Human

The bot has its own self-teaching curriculum (`bot/llm/self_teaching.py`, 5 levels). The human has:
- Skills as ad-hoc curriculum (`/edge-finder`, `/loss-autopsy` weekly; `/health-check` daily).
- Markdown runbooks (`MORNING_KICKOFF.md`, `MORNING_PROMPT.md`, `LIVE_THIS_WEEK.md`, `LLM_RAMP_UP_SCHEDULE.md`).
- No explicit progression. No tutorial. No reading list. No graded checkpoints.

This is a clear opportunity (request Q below).

---

## J. Manual Trader's Dashboard — Today vs Needed

API endpoints that already exist (`bot/api_server.py`):
- `/v1/positions` (line 196), `/v1/account` (219), `/v1/trades/history` (115), `/v1/trades/equity-curve` (134).
- `/v1/llm/market-view` (173), `/v1/llm/feed` (188), `/v1/agents/overview` (230), `/v1/agents/team/calibration` (247), `/v1/agents/debate/history` (252).
- `/v1/signals/funnel` (259), `/v1/signals` (844), `/v1/sniper/recent` (282), `/v1/summary` (292).
- `/v1/forensics/analysis` (479), `/v1/portfolio/allocation` (607), `/v1/performance/metrics` (678).
- `/v1/activity/feed` (906), `/v1/reasoning/feed` (1198), `/v1/reasoning/pipeline/{id}` (1254), `/v1/counterfactuals/resolved` (1290).
- `/v1/backtest/results/*` (1100, 1113, 1122).

**The frontend is missing.** `bot/dashboard/` only has `__init__.py`, `__main__.py`, `server.py` — no `index.html`, no React/Vue/Svelte build. The API is rich, the consumer is empty. Combined with the XSS audit finding, the dashboard is essentially "API-ready, UI-absent."

What a manual trader needs at a glance is exactly what the API provides — the build is the gap.

---

## K. Unfair-Advantage Toolkit — what's in the bot today vs what could be

What the human brings: narrative intuition, cross-asset awareness, news speed, network info. What the bot can offer to *amplify* these:
- **Counter-thesis check.** Already exists for the bot (`thesis-track.md` skill); not exposed to the human pre-trade.
- **Historical pattern memory.** `bot/llm/deep_memory/` stores trade DNA. A `/recall SYM SIDE` could surface "your last 5 trades on this exact setup."
- **Stop-distance reality check.** ATR + historical SL-hit rate is in `bot/manual/edge_analysis.py` and `bot/manual/risk_optimization.py`. A `/sl-check SYM ENTRY SL` command would deliver the user's request K verbatim.
- **Day-of-week / time-of-day edge.** `bot/manual/time_edge_analysis.py` (352 lines) already computes this. Surface as `/time-edge SYM SIDE`.

The data is all there. The **plumbing into Telegram** is the missing piece.

---

## L. The Post-Trade Learning Loop FOR THE HUMAN

Today: nothing for the human. `bot/llm/post_trade_learner.py` learns the bot's lessons.

Needed: pair each manual trade with (a) pre-trade thesis, (b) post-trade auto-review comparing thesis to outcome, (c) personal-lesson aggregation, (d) calibration ledger.

A minimal implementation would extend `JournalEntry` (`trade_journal.py:28`) to include `pre_thesis: str`, `pre_confidence: float`, `pre_target_time: str`, then add a `review()` method that runs at exit, plus a `data/manual/my_lessons.jsonl` writer. A weekly `/my-calibration` Telegram command would render the calibration curve.

---

## M. Recovery Roadmap from $497 Drawdown

The reports in `bot/data/reports/paper_trading_2026-04-25_*` show the actual state: **$497.05 (90.1% drawdown from $5000), 13.4% all-time WR, 36.8% last 7 days, 4 consecutive losses on 2026-04-23, ranging/illiquid regimes bleeding hardest, but ETH_SHORT 80% / BTC_SHORT 57% pattern edges holding.**

The user is on mobile and cannot run the bot autonomously. The recovery path:

**Phase 1 — Re-anchor (Week 1, paper only).**
- Set `LLM_MODE=1` (ADVISORY). Keep `KILL_SWITCH=true` if real money is exposed; verify in `/status`.
- Use `/sniper`, `/sim`, `/briefing` daily. Goal: log every signal the bot generates with your own gut call (BUY/SELL/SKIP) **before** seeing the bot's tier. Track in `data/manual/calibration_log.jsonl`.
- Tooling needed: a `/predict SYM` command that lets the user lock in a prediction before the bot's verdict appears.
- Gate to phase 2: 30 paper trades logged, calibration error <15%, no rule violations.

**Phase 2 — Small live, sniper-tier only (Weeks 2–3).**
- Real money but **only SNIPER tier** signals (per `CONTEXT.md`: SNIPER = ≥85% conf + 3 agree, OR ≥90% + 2 agree). Hard cap stake at $20/trade.
- Use the existing `/trade` and `/exit` to log every entry/exit. Restrict to ETH_SHORT and BTC_SHORT until the data shows other patterns recovering (per the report, those are the only positive-PnL patterns).
- Gate to phase 3: 10 real trades, equity recovers to $600+, max DD <15%.

**Phase 3 — Scale tier inclusion (Weeks 4–6).**
- Allow PREMIUM tier. Bump per-trade cap to $40. Add `setup-edge` skill weekly review.
- Begin `/preflight` thesis logging. Begin `/my-calibration` weekly check.
- Gate to phase 4: 30 trades, WR ≥45% rolling 20, calibration error <10%.

**Phase 4 — Re-enable autonomous, supervised (Week 7+).**
- `LLM_MODE=2` (VETO_ONLY). Bot can reject only. Human still initiates. Continue manual journal.
- Then `LLM_MODE=3` only after the knowledge roadmap also passes its phase-3 gates (line 197 of `knowledge_roadmap.py`).

---

## N. "Trade Like the Bot's Best Self" Template

From `bot/data/reports/paper_trading_2026-04-27_1500.md` and `bot/manual/CONTEXT.md`:

**Manual checklist (paste into your phone notes):**
1. **Setup must be:** ETH_SHORT (80% WR, 5 trades) or BTC_SHORT at conf ≥90% (57% WR, 7 trades). HYPE_LONG, SOL_SHORT, SOL_LONG are AVOID.
2. **Regime must be:** trending (51.9% WR) or strongly trending. NEVER trade ranging (25%) or illiquid (28.1%).
3. **Confidence floor:** sniper alert tier = SNIPER (≥85% conf + 3 strategies agree, OR ≥90% + 2 agree). Skip STANDARD tier outright.
4. **R:R floor:** ≥1.2 (sniper filter gate 3). Prefer ≥1.5.
5. **Stop width:** prefer ≤2.5% (any wider triggers leverage cut).
6. **Leverage:** 15–25× only on SNIPER tier. PREMIUM = 15–20×. NEVER >25×.
7. **Time-of-day:** prefer London/NY overlap (14:00 UTC ish per `sniper-setup.md`).
8. **Position sizing:** 10% of equity on SNIPER, 8% on PREMIUM. **Hard floor: never risk >$20/trade until equity >$1000.**
9. **No averaging down. No revenge trades.** If 2 losses in a row, stop for the day. (Hard rule — your last data shows 4 consecutive losses caused the latest drawdown leg.)
10. **Pre-trade contract:** write thesis + expected hold time + invalidation level **before** entering.

---

## O. Risk Discipline for Manual Traders

Today, every trade goes through `bot/risk/self_tuning.py` regardless of source. The manual `/signal` command queues to `data/manual_signals.json` and the next scan picks it up — same risk filter chain. Daily-loss limits are 3%/5%/8% by mode (lines 34/42/50 of `self_tuning.py`); consecutive-loss tracking exists (line 70).

**Recommendation:** add an env-driven manual-risk profile in `bot/manual/config.py`:
- `MANUAL_DAILY_LOSS_PCT` (default 3%, tighter than auto)
- `MANUAL_CONSECUTIVE_LOSS_HALT` (default 2, tighter than auto's 5)
- `MANUAL_MAX_PER_TRADE_USD` (default $20 until equity > $1000)

Then add a `ManualRiskGate` class that pre-filters before the standard chain. This protects the human from themselves during recovery without weakening the bot's own discipline.

---

## P. What to Build — 10 Concrete Additions

| # | Addition | File path(s) | Effort | Value | Depends on |
|---|---|---|---|---|---|
| 1 | Wire inline approve/reject buttons into all sniper/premium alerts (currently defined but not attached to outgoing messages) | `bot/alerts/telegram_bot.py:2626` (build_alert_buttons), `bot/manual/alerts.py:send_sniper_alert` | 0.5 day | Highest mobile UX win | None |
| 2 | Pre-trade thesis logger | New: `bot/manual/pre_trade_journal.py`; extend `bot/manual/trade_journal.py:JournalEntry` with `pre_thesis`, `pre_confidence`, `pre_invalidation`, `pre_horizon`; new Telegram `/pre` command | 1 day | Foundation for L, N, Q | Trade journal |
| 3 | Pre-trade validator routing through `PreTradeSimulator` + Critic | New: `_cmd_preflight` in `telegram_bot.py`; reuse `bot/llm/agents/pre_trade_simulator.py:PreTradeSimulator.simulate` | 1 day | Stress-test before risk | (2) |
| 4 | Daily morning brief auto-pushed at 08:00 user-local | Extend `bot/alerts/telegram_bot.py:_cmd_briefing`; add scheduler in `multi_strategy_main.py` | 0.5 day | Routine | None |
| 5 | Manual calibration ledger + `/my-calibration` | New: `bot/manual/my_calibration.py`; reads `pre_trade_theses.jsonl` × `trade_journal.jsonl`; mirrors `bot/llm/thesis_tracker.py:_compute_calibration` | 1.5 days | Self-knowledge | (2) |
| 6 | Mid-position commands `/setsl`, `/settp`, `/scaleout`, `/scalein` | `bot/alerts/telegram_bot.py` (new handlers); use `bot/manual/position_rules.py:partial_close_pct` | 1 day | Power-user gap | Position manager wiring |
| 7 | `/sniper-eval SYM SIDE` — invoke `bot/llm/sniper.py:LLMSniperEngine` on demand for any symbol | `bot/alerts/telegram_bot.py` + small refactor in `bot/llm/sniper.py` to add a public `evaluate_on_demand` | 0.5 day | Direct human → sniper LLM | None |
| 8 | Personal trading rules engine — user-defined rules + bot-enforced | New: `bot/manual/personal_rules.py` (YAML config, e.g. `data/manual/my_rules.yml`); pre-flight check before `/trade` | 1.5 days | Self-discipline | (3) |
| 9 | `/coach SYM` — bot explains why it would/wouldn't take a trade now | `bot/alerts/telegram_bot.py` calling `bot/llm/agents/agent_brain.py` with a teaching prompt | 1 day | Educational | None |
| 10 | Manual override audit ledger + weekly review skill | New: `bot/manual/override_ledger.py` + `.claude/skills/override-review.md` | 1 day | Track when human beat / was beaten by bot | (8) |

Total: ~10 dev-days for the entire manual trader's first-class UX layer. Most additions are wiring, not new logic.

---

## Q. Manual Trader's 5-Level Curriculum (mirroring `bot/llm/self_teaching.py`)

| Level | Name | Success metrics | Tooling | Time to advance | Money allowed |
|---|---|---|---|---|---|
| 1 | OBSERVE | 30 logged predictions in `pre_trade_theses.jsonl`; outcome resolution >90%; zero rule violations | `/pre`, `/journal`, `/sniper`, `/sim` | ≥7 days | Paper only |
| 2 | ANALYZE | Run `/loss-autopsy` and `/edge-finder` weekly; identify your top 3 losing patterns; identify your top 2 winning patterns; calibration error <15% | `/my-calibration`, `loss-autopsy.md`, `edge-finder.md` | ≥14 days | Paper only |
| 3 | PREDICT | 30 predictions at ≥55% (your top patterns only); calibration error <10%; positive expectancy on declared edges | `/preflight`, `/coach`, `/setup-edge` | ≥21 days | Live, $20/trade cap |
| 4 | REPLICATE | 3 documented playbook setups in `data/manual/MY_PLAYBOOK.md` with WR ≥55% n≥10 each; <5% rule violations | `generate_playbook.py` adapted for human, `sniper-setup.md`, `/my-calibration` | ≥45 days | Live, $100/trade cap |
| 5 | SYNTHESIZE | Propose ≥1 strategy hypothesis tested via `bot/manual/filter_validation.py`; mentor capacity (could write a runbook a beginner could follow); Sharpe >1.5 personal | `filter_validation.py`, `edge_discovery.py`, `strategy-discover.md` | ongoing | Live, no cap (within risk) |

These map directly onto the bot's `PHASE_CONFIGS`. **Promotion gate enforcement:** add a `bot/manual/curriculum.py` module that reads `data/manual/curriculum_state.json` and refuses `/trade` above the level's per-trade cap. Same enforcement pattern as `knowledge_roadmap.py:get_recommended_llm_mode`.

---

## R. Path to Greatness — 12-Month Vision

A "great" manual WAGMI trader 12 months out:
- **Sharpe ≥2.0** on personal trades (ledger in `trade_journal.jsonl`).
- **3+ identified high-edge setups** documented in `data/manual/MY_PLAYBOOK.md`, each with n≥30 trades and WR ≥60%.
- **Calibration error <5%** rolling 90-day (per `my_calibration.py`).
- **Personal kill-list** of bad-for-you setups in `data/manual/MY_AVOID.md` (think: HYPE_LONG-on-Friday-after-pump).
- **A documented edge the bot doesn't have** — most likely cross-asset (equities, macro) or social (network alpha) — with the workflow to capture it.
- **Mentor capacity.** Writes the next iteration of `MORNING_KICKOFF.md`.

**Roadmap by quarter:**
- **Q1 (months 1–3):** complete curriculum levels 1–3. Focus: paper, calibration, recovery to $1k equity.
- **Q2 (months 4–6):** curriculum level 4. Build playbook. Equity to $5k. First override audit.
- **Q3 (months 7–9):** level 5 entry. Begin testing personal edge hypotheses via `filter_validation.py`. Equity to $15k.
- **Q4 (months 10–12):** validated personal edge in production alongside the bot. Mentor write-up. Equity to $50k+.

The non-negotiables: weekly `/loss-autopsy`, monthly `/edge-finder`, quarterly `/my-calibration` deep-dive. These already exist; the discipline is the addition.

---

## Synthesis — The Single Most Important Insight

The manual layer is not abandoned, it is *unfinished at the seams*. The compute (sniper_filter, conviction_sizer, position_rules, trade_journal, anticipatory_entries) is sophisticated, tested (308 tests passing), and live. The **AI** is sophisticated (sniper LLM, pre-trade simulator, exit engine, thesis tracker, calibration ledger). What does not yet exist is the **integration mat** between (a) the human via Telegram/mobile, (b) the manual compute, and (c) the AI. Inline buttons are coded but not attached. PreTradeSimulator runs for the bot but not for the human. ThesisTracker tracks the bot's predictions but not the human's. Calibration metrics exist for agents but not for the operator. Curriculum gates exist for the bot but not for the trader.

Closing those four gaps — alert buttons, pre-trade thesis, human calibration, manual curriculum — is roughly 10 dev-days of plumbing and turns the manual layer from "an engine without a cockpit" into "the cockpit the user has been operating without for 41 files of substrate."

The user said this matters. The bones say so too. Build the cockpit.

### Critical Files for Implementation
- /home/user/WAGMI/bot/alerts/telegram_bot.py
- /home/user/WAGMI/bot/manual/trade_journal.py
- /home/user/WAGMI/bot/manual/sniper_filter.py
- /home/user/WAGMI/bot/llm/thesis_tracker.py
- /home/user/WAGMI/bot/llm/knowledge_roadmap.py