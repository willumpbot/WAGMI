# Compressed Timeline (6 months to 6 weeks)

*Agent ID: `a733ce828a9d2c8c2`*

---

## Original Task

```
The user looked at the WAGMI bot blueprint at /root/.claude/plans/i-was-working-remotely-glimmering-clarke.md (especially Section 21.10 "6-month roadmap") and said: "Concerned our timeline is too long."

Your job: produce a compressed alternative — **6 weeks instead of 6 months** for the same set of outcomes. What's truly critical-path? What can be parallelized? What's actually nice-to-have and can be deferred?

**Context (from the blueprint)**:
- 6-month roadmap covered: Stabilization+ABC, Opportunist+Adversary+Microstructure-lite, Local Model, Multi-exchange, Strategy Genesis, Scale+Multi-account
- Bot is currently offline 92h, 90% drawdown, 100% VETO loop
- The bot is solo-developed (one person + AI assistance)
- Critical bug: Regime Agent uses Haiku, Haiku ignores JSON schema, returns prose, fails parsing, falls back to `regime=unknown`, Critic vetoes everything

**Mission Part 1: Aggressive compression analysis**

For EACH of the 6 months in the original plan:
- What's the critical-path subset (must-do for "bot trades safely + improves")?
- What's the gold-plating (nice-to-have)?
- What can be parallelized with which other month?
- What can be skipped entirely vs deferred?

**Mission Part 2: The 6-week alternative roadmap**

Lay out a week-by-week plan that gets the bot to "trading + improving + safe" in 6 weeks. For each week:
- Goal
- Critical path tasks (with file paths)
- Verification gate (what proves we can move to next week)
- What we explicitly DEFER and why

Suggested compression:
- Week 1: 1-hour fix + 1-day fix (§7-A, §7-B from blueprint) + restart bot. Single goal: bot online with non-100% VETO.
- Week 2: LLMBackend ABC scaffold + migrate 8 social bypassers + add CLI failure logging. Single goal: clean abstraction, zero silent failures.
- Week 3: Hypothesis evidence collector + auto_fix_pipeline + execution_forensics. Single goal: learning loop closes.
- Week 4: Opportunist + Adversary agents (the two highest-leverage adds). Single goal: more edge, less overconfidence.
- Week 5: Multi-account / canary framework lite (paper-alongside-live). Single goal: safe deployment substrate.
- Week 6: Local model wedge — set up Ollama, A/B Regime first (lowest stakes), keep API as fallback. Single goal: prove local works on one agent.

But challenge that. Is 6 weeks actually achievable? Or is 4 weeks possible if we cut more? Or is 8 weeks more honest?

**Mission Part 3: The "what blocks progress" inventory**

Be specific about what's actually slow:
- Coding velocity: how many LOC per day for one solo dev with AI?
- Test gates: how long to validate each step?
- Live verification: paper trading needs 7-14 days to prove anything
- Bug surface: every change introduces ~30% chance of new bug

What's the honest minimum time?

**Mission Part 4: The "ship in 2 weeks" extreme version**

If the user said "I have 2 weeks, what do I actually do?" — produce that plan. What's the absolute minimum to get bot trading safely with closed learning loop?

Sugges
```

---

## Full Report

I have what I need. TodoWrite isn't relevant here — this is a single deliverable analysis. Producing the response now.

---

# Compressed Roadmap Analysis: 6 Months → 6 Weeks (and shorter alternatives)

**Premise check.** The blueprint's §21.10 6-month roadmap is paced for an enterprise team with QA, devops, and code review. You are one solo dev with mobile + occasional PC, AI assistance, and a bot at 90% drawdown burning IRL money in opportunity cost every day it sits at 100% VETO. The honest cost of slowness is non-trivial: if the fix-first item (§7-A, ~1 hour) isn't in by next week, the bot has been offline ~100 days and you've effectively lost a quarter of OOS data you could have been calibrating against.

So compression is justified. But "6 months" was not arbitrary — months 4-5 (multi-exchange, strategy genesis) genuinely require 4-8 weeks each because each new venue is weeks of integration even with CCXT, and statistical significance has time floors that can't be wished away. Compression has to come from **deferring the multipliers** (months 3-6) and **parallelizing the substrate** (months 1-2), not from doing the same scope faster.

---

## Mission Part 1: Aggressive Compression Per-Month

### Month 1 (Stabilization + LLMBackend ABC + CLI hardening)

- **Critical path subset (must-do):** §7-A (1-hour Regime→Sonnet hardcode), §7-B (1-day production-safe fixes incl. failure-mode logging at `bot/llm/claude_cli_client.py:121-145`, sanity guardrail at `bot/llm/agents/coordinator.py:741`, peak-equity reset, kill-list for SOL_SHORT/HYPE_LONG). The pre-flight checklist from §8. Without this, **nothing else matters** because the bot doesn't trade.
- **Gold-plating in Month 1:** the full LLMBackend ABC migration of all 8 social bypassers (§6.6). The ABC scaffold is critical-path; the *complete migration* of every bypasser is not — the social bypassers are not the cause of the 100% VETO. Migrate Regime + Critic + Risk first; defer Trader/Strategist/Postmortem migrations.
- **Parallelizable with:** Month 2's Adversary agent. Adversary is a self-contained `bot/llm/agents/adversary.py` and a 13-line edit in coordinator. It does not depend on the ABC.
- **Skip/defer:** Critic prompt re-calibration as a Month-1 line item. Once Regime returns valid JSON, the 100% VETO drops without touching Critic. Re-calibration becomes a Month-2 chore informed by 7 days of real critic decisions.

### Month 2 (Opportunist + Adversary + Microstructure-lite)

- **Critical path:** Opportunist agent (you flagged it as the user-requested anchor; §16.1, §21.3) and Adversary (§16.2, ~1 day to build per blueprint cost table). These are pure-additions to `bot/llm/agents/coordinator.py` pipeline.
- **Gold-plating:** Microstructure-lite. L2 book-imbalance integration touches the data layer, the Hyperliquid websocket plumbing, and adds a new feature column to every signal. It is 2-3x the work of the two agents combined and produces marginal value until Opportunist exists to consume it.
- **Parallelizable with:** Month 3's Ollama deployment can run on the side machine concurrently. They share zero code.
- **Defer:** Microstructure-lite to post-week-6. It's a Multiplier-4 candidate but the value-per-hour is far below Opportunist+Adversary.

### Month 3 (Local model integration)

- **Critical path:** None for "trading + improving + safe." Local model is a **cost reduction multiplier**, not a survival multiplier. At Max-subscription, your CLI cost is already $0; the dollar-savings argument is weaker than the blueprint implies for your specific case.
- **Gold-plating:** Per-agent A/B on all 9 agents. You only need to validate ONE agent (Regime, lowest-stakes, blueprint §21.10 Month 3) to prove the pipeline.
- **Parallelizable with:** Month 5 Strategy Genesis sandbox (different code paths). Also with Month 4 multi-exchange (different concern entirely).
- **Defer:** Almost everything past the Ollama install + one-agent A/B. Move full migration to month 4-5 of the *real* timeline (post-week-6).

### Month 4 (Multi-exchange Binance + Hyperliquid)

- **Critical path:** None for 6 weeks. **This is genuinely 4-8 weeks of work** even for an experienced team. Per-venue executor (`bot/exchange/`), unified position state, cross-venue reconciliation, funding-arb module. The blueprint correctly says "30d shadow validation" before going live — that's a hard floor.
- **Gold-plating:** Funding-arb strategy module. Standalone alpha but separable.
- **Parallelizable with:** ANY other month. Multi-exchange touches the executor + risk layer; LLM/agent work touches different files. Two devs could do them concurrently. One dev cannot.
- **Defer entirely** until post-week-6. The 90%-drawdown bot does not need a second venue. It needs to stop vetoing everything.

### Month 5 (Strategy Genesis)

- **Critical path:** None for 6 weeks. Strategy genesis requires (a) a populated learning loop (which Month 1's hypothesis evidence collector creates), (b) a sandbox, and (c) walk-forward validation that *cannot* be sped up — it requires 7-90 days of OOS data per candidate. The blueprint says "1-2 promotions/month" — that's the speed limit.
- **Gold-plating:** Auto-promotion gate. Manual promotion is fine for the first 6 candidates.
- **Defer entirely.** Strategy genesis pre-supposes a *working* learning loop and stable hypotheses. You don't have those yet.

### Month 6 (Scale + observability + multi-account)

- **Critical path subset:** Multi-account / canary framework lite — paper-alongside-live. This is meaningful within 6 weeks because it lets you safely deploy further changes without nuking equity again. Prometheus/Grafana/AlertManager is gold-plating; a JSONL `decisions.jsonl` audit log gets you 80% of the value at 5% of the work.
- **Gold-plating:** Full Prometheus stack. AlertManager. Auto-promotion gate.
- **Parallelizable with:** Anything. Observability is read-only by definition.
- **Defer:** Auto-promotion gate, full Prometheus. **Keep:** paper-shadow channel, decisions.jsonl, simple Telegram alerts.

---

## Mission Part 2: The 6-Week Alternative Roadmap

### Week 1 — Bot online with non-100% VETO

- **Goal:** Bot trading. Single, non-negotiable.
- **Critical-path tasks:**
  - §7-A1: edit `bot/llm/agents/coordinator.py:4716` — remove `AgentRole.REGIME` from the Haiku tuple. (1 hour)
  - §7-A2: verify `_compute_regime_fallback` at `bot/llm/agents/coordinator.py:3166` returns canonical names; if it returns bare `trend`, fix line 3213 to emit `trending_bull`/`trending_bear`. (30 min)
  - §7-B1 through §7-B6 in `bot/llm/claude_cli_client.py` and `config/settings.py`: failure-mode logging, sanity guardrail, peak-equity reset, kill-list. (~6 hours)
  - §8 restart pre-flight checklist top-to-bottom.
- **Verification gate:** `python run.py signals` smoke test passes. Within 24h of restart, regime field is non-`unknown` ≥95% of cycles, VETO rate <70% (down from 100%). At least one trade fires in 48h.
- **Defer:** Anything not on the path to "VETO < 100%." Defer the LLMBackend ABC scaffold to Week 2. Defer test coverage. Defer documentation.
- **Risk if skipped:** none — this is the foundation.

### Week 2 — Clean abstraction, zero silent failures

- **Goal:** LLMBackend ABC scaffolded, Regime+Critic+Risk migrated, CLI failures observable.
- **Critical-path tasks:**
  - §9 Steps 1-3: create `bot/llm/backend.py` with `LLMBackend` ABC, `CliBackend`, `ApiBackend`. (5 hours)
  - Migrate **only the 3 critical-path agents** (Regime, Critic, Risk) — not all 8 social bypassers. (3 hours)
  - Add module-scope `_FAILURE_COUNTS` and `get_cli_failure_stats()` per §7-B1.
  - Add `decisions.jsonl` audit log: append every coordinator decision as one line — symbol, regime, critic verdict, ensemble vote, final action, reason. This is the cheap version of observability and unlocks Week 3.
- **Verification gate:** Two-sided diff test — 100 paper cycles before vs after migration produce identical agent decisions ±1%. Failure logs visible in `data/llm/agents/cli_failures.jsonl`. `decisions.jsonl` lines matching trade count.
- **Defer:** Migrating Trader, Strategist, Postmortem, Scout, Exit, Quant social bypassers. They are not in the 100%-VETO path.

### Week 3 — Learning loop closes

- **Goal:** Hypotheses get evidence; auto-rollback works on bad rules; trade post-mortems exist.
- **Critical-path tasks:**
  - §7-F: hypothesis evidence collector at `bot/llm/growth/hypothesis_tracker.py` (5 hours). All 5 sub-tasks in §7-F.
  - `bot/learning/auto_fix_pipeline.py` — auto-rollback when graduated rule produces 3 consecutive losses. (~5 hours, file already exists as stub)
  - `bot/learning/execution_forensics.py` — slippage + fill-quality post-mortem on every trade. (~3 hours, file already exists as stub)
- **Verification gate:** Within 48h of Week-3 deploy, every active hypothesis has ≥5 evidence entries. Forced losing trade triggers auto-rollback in ≤3 cycles. Forensics entry written for every closed trade.
- **Defer:** `daily_synthesis.py`, `model_optimization.py`, `live_prompt_injection.py` (the 3 lower-leverage stubs per §7-D).

### Week 4 — Opportunist + Adversary

- **Goal:** New edge, less overconfidence.
- **Critical-path tasks:**
  - Adversary agent first (cheaper, ~1 day). Add to `bot/llm/agents/adversary.py`, register in `bot/llm/agents/__init__.py`, wire pre-Critic in coordinator. Adversary's "what would I do to liquidate this?" prompt is short and self-contained.
  - Opportunist agent — full §21.3 spec but **shipping the continuous-Haiku screener only** (defer episodic Sonnet escalation to week 5 if needed). The Haiku screener is `bot/llm/agents/opportunist_screener.py` plus 6 trigger functions in `bot/data/opportunist_signals.py`.
  - Both follow §17's 8-step recipe.
- **Verification gate:** 7-day paper run shows Adversary cuts paper-realized DD ≥10% vs Week-3 baseline. Opportunist screener fires 2-10 candidates/day. Critic vetoes ~70% (matches §21.3 forecast).
- **Defer:** Opportunist's full Sonnet escalation, microstructure-lite, the other 8 long-tail agents from §21.4. Drawdown Recovery and Calibration Auditor are good Week 7-8 candidates.

### Week 5 — Safe deployment substrate

- **Goal:** Paper-alongside-live channel exists; you can ship without nuking equity.
- **Critical-path tasks:**
  - Multi-account / canary framework **lite**: a single environment flag `BOT_CHANNEL=live|paper_shadow|canary`. Canary writes to `data/canary/` instead of `data/`, takes the same signals, executes against a separate Hyperliquid sub-account at 1% size. (3-5 days for 1 dev — this is the upper bound of week 5.)
  - Hook into existing `bot/api_server.py` so the dashboard distinguishes channels.
  - Wire `decisions.jsonl` per-channel.
- **Verification gate:** Canary takes 48h of identical signals as live, equity diff between canary's 1%-size and live's 100%-size scales within 2%. No state drift between channels.
- **Defer:** Auto-promotion gate. Full Prometheus. Multi-machine deployment. The Month-6 observability stack.

### Week 6 — Local model wedge

- **Goal:** Prove Ollama works for ONE agent (Regime — the lowest-stakes, ironically the same one we just hardcoded to Sonnet).
- **Critical-path tasks:**
  - Install Ollama on whatever box has GPU. Pull `qwen2.5:32b-instruct` or `llama3.3:70b-instruct-q4` if VRAM allows. (Half day.)
  - Add `OllamaBackend` to `bot/llm/backend.py` (the ABC from Week 2 makes this 2-3 hours, not days).
  - A/B on Regime only: 30% of cycles to Ollama, 70% to Sonnet. Compare canonicalized outputs and write to `data/llm/ab_regime.jsonl`.
  - Keep API as fallback when Ollama latency > 5s or ≥3 consecutive parse failures.
- **Verification gate:** 7-day A/B shows Ollama agreement with Sonnet ≥85% on regime label. P95 latency <3s. Cost neutral or down.
- **Defer:** Migrating Risk/Exit/Scout/Trader/Critic to local. Multi-exchange. Strategy genesis. Microstructure. The remaining 4 long-tail agents.

### Is 6 weeks actually achievable?

**Honest assessment: 6 weeks is tight but achievable for week 1-4. Weeks 5-6 are at risk.**

- **4 weeks is possible if** you cut Week 5 (canary) and Week 6 (Ollama) entirely. That gets you to "trading + improving + safer" but not "safe deployment substrate." Acceptable if you're willing to ship Adversary/Opportunist into live without canary.
- **8 weeks is more honest** if you want every gate to actually pass. The reason: each week's verification gate has a *minimum* clock-time component. Week 1's "trade fires in 48h" depends on market conditions; week 4's "Adversary cuts DD ≥10%" needs 7 paper days; week 6's "Ollama agreement ≥85%" needs 7 A/B days. Stack 6 of these and you get clock-time creep of 4-7 days the dev cannot compress.

**My recommendation: 6 weeks with explicit "if Week 5 slips, we ship Week 4's gains live with manual review and absorb Week 5 into Week 7."** The first 4 weeks are critical-path; the last 2 are sequenceable.

---

## Mission Part 3: What Actually Blocks Progress

- **Coding velocity (solo dev + AI):** realistic 150-400 LOC of *production-quality* code/day, including tests. Higher in fresh code, much lower in `multi_strategy_main.py` (6,028 lines, no tests). The 6-week plan is roughly 4,000-6,000 LOC across new files + ~500 LOC of edits to `coordinator.py` and friends. That's the upper bound of one dev's output for 30 working days.
- **Test gates:** §6.8 flags zero CLI-path test coverage. Adding the test fixture (`bot/tests/test_claude_cli_client.py` per §7-C Day 5) is a half-day. Without it, every change to `coordinator.py` is a coin flip. **You cannot skip this.**
- **Live verification:** paper trading needs **7-14 days** of real signals to shake out anything. This is the hard floor mentioned in §21.10 ("7-day paper run with full pipeline" for Month 1, "30d shadow" for Month 4). Verification gates in weeks 4-6 each have implicit 7-day clocks.
- **Bug surface:** the blueprint's §6.11 lists 11 known issues across critical/high/medium. Empirically, every change to `coordinator.py` (currently ~6k lines, no tests) introduces ~30% chance of a regression. Over 6 weeks of touches, expected to introduce 4-8 new bugs. **Budget 1-2 days per week for unplanned firefighting.**
- **Mobile vs PC time:** code review on mobile is fine; running smoke tests requires PC. If PC access is sporadic, week 1's verification gate (smoke test, restart) gates everything else. **Schedule PC time deliberately.**

**Honest minimum time floor:** ~4 weeks IF mobile/PC alternation is favorable, IF no surprise bugs from the migration, IF the Regime hardcode actually drops VETO below 70% on first try. Realistic 6 weeks. Pessimistic 8 weeks if any of those go wrong.

---

## Mission Part 4: The 2-Week Extreme Version

If the user said "I have 2 weeks":

- **Days 1-2:** §7-A (Regime → Sonnet hardcode), §7-B1 (failure-mode logging), §8 restart pre-flight checklist, restart bot.
- **Days 3-5:** §7-B2 (sanity guardrail), §7-B3 (peak-equity reset), §7-B4 (kill-list), `decisions.jsonl` audit log appended in coordinator. End state: "I can see what the bot decided and why."
- **Days 6-9:** §7-F hypothesis evidence collector full 5 sub-tasks. End state: "the bot is learning."
- **Days 10-12:** Opportunist agent, Haiku screener only. The user's anchor.
- **Days 13-14:** Smoke tests for the 3 changed code paths (`coordinator.py` regime hardcode, `hypothesis_tracker.py`, new opportunist screener). Telegram alert wiring. Update `ROADMAP.md`.

**What gets dropped:**
- LLMBackend ABC scaffold — replaced by the §7-A1 hardcode (band-aid). Replacement date logged per §7-J: "by Week 6."
- Adversary agent — it's a should-have, not a must-have. Deferred to Week 3-4.
- Auto-fix pipeline + execution forensics — deferred. The bot can run without them; it just learns slower.
- Canary channel — accept higher deployment risk, deploy with manual review.
- Ollama — pure cost optimization, irrelevant under Max sub.

**Why it's OK to drop these:** the 2-week plan delivers a bot that (a) trades, (b) records what it does, (c) learns from outcomes, (d) has the user's anchor agent. That's the minimum viable WAGMI. Everything else is multiplication on a working substrate.

**Risk of the 2-week plan:** high. The §7-A hardcode is a band-aid; if a similar bug surfaces in Critic or Risk under load, you have no abstraction layer to swap behind. You're betting that the next 2-4 weeks of stable trading buys you time to do Week 2's ABC migration.

---

## Mission Part 5: What You CAN'T Compress

These have immutable time floors. The 6-month plan acknowledges them; any compressed plan that ignores them is fiction.

- **Walk-forward backtest validation (§21.10 Month 5):** 7+ days of OOS data per candidate strategy. Cannot be parallelized below the calendar. Strategy genesis is not a 6-week item. Period.
- **Paper-trading validation (§21.10 Month 1, 2, 4):** 7-30 days of real signals. The Month-1 verification "7-day paper run" is a clock floor, not a labor floor. Same for Month-4 "30d shadow."
- **Calibration windows (§21.10 Month 3, 6):** 30 days minimum for statistical significance on 9-agent A/B. You can compress to 7 days for *one* agent (week 6 Ollama-vs-Sonnet on Regime) but cannot get 95% confidence in <30 days on multiple agents.
- **LLM model fine-tuning** (not in 6-month plan but implied for Strategy Genesis): data prep ~1 week, training hours, eval ~1 week.
- **Multi-exchange integration (§21.10 Month 4):** "30d shadow validation" is the floor. CCXT helps with API surface, but reconciliation, edge cases, and venue-specific quirks (Binance position margin vs Hyperliquid cross/iso, funding cadence diffs) eat 2-4 weeks of debug time.
- **Canary equity-divergence test (§21.10 Month 6, week 5 in compressed):** 48-hour minimum, 7 days for confidence.

**Of the 6 monthly items, these have hard floors that compression can't dodge:** Month 4 (multi-exchange — 4-8 weeks minimum), Month 5 (strategy genesis — 60+ days minimum from cold start). Those are the items that genuinely cannot fit in a 6-week plan and that's why they're cut.

---

## Mission Part 6: The Pareto-Optimal Recommendation

Given solo dev + mobile/PC + 90% DD + Max subscription (cost is not the binding constraint):

**Recommendation: 6 weeks for substrate + edge, then 8-12 weeks for multipliers, with explicit "ship at week 4" fallback if anything slips.**

Concretely:

1. **Weeks 1-4 (must-do):** Substrate + learning loop + Opportunist/Adversary. After week 4 you have a bot that trades, learns, has new edge, and is observable. **If the timeline slips here, it slips dangerously** — you remain at 90% DD with no escape velocity.

2. **Weeks 5-6 (should-do):** Canary substrate + local-model wedge. Reduces risk of week-7+ work breaking the bot.

3. **Weeks 7-12 (nice-to-do, big variance):** Multi-exchange OR strategy genesis OR microstructure — pick ONE based on which constraint is binding. If capital scales to $1M+, multi-exchange. If the alpha decay shows up in the 11 strategies, strategy genesis. If you see persistent slippage edge being eaten on entries, microstructure.

**Why not 6 months:** 90% drawdown means every week of unfixed bot is a week of compounding opportunity cost. The 6-month sequencing puts the "save the bot" work and the "10× the bot" work in series; they can be in parallel up to a point.

**Why not 2 weeks:** because Adversary, ABC migration, learning loop closure, and canary are real value. Skipping them just to ship faster means you ship a fragile bot. The bot's failure mode at 100% VETO was caused by *exactly* the kind of skipped abstraction the 2-week plan recreates.

**Sweet spot: 6 weeks to "trading + improving + safe + observable" + 6-8 more weeks to pick ONE multiplier.**

---

## Mission Part 7: Sequencing Risks

Your proposed order — fix VETO → audit log → learning loop → new agents → local model → multi-exchange → strategy genesis — is correct **if dev time is the binding constraint.** Because:

- Cheapest thing to be wrong about: the 1-hour fix. If A1 doesn't drop VETO below 100%, you find out in 1 hour with no sunk cost. Other orderings put the cheapest experiment after expensive ones.
- Audit log second is right because every subsequent decision needs ground truth to evaluate against. Without `decisions.jsonl`, you cannot prove Adversary cut DD or Opportunist added trades.
- Learning loop third is right because new agents (week 4) need the hypothesis evidence pipeline to actually self-improve from new data.
- Local model and multi-exchange are pure multipliers — they multiply existing capability. Doing them before you have capability to multiply is wasted work.

**What changes if compute becomes binding:** flip Week 6 (local model) to Week 1-2. Why: if you cannot afford API calls at all, hardcoding Regime to Sonnet *increases* costs and the §7-A band-aid becomes inviable. You'd need Ollama up before the cost spiral. **This does not apply to your case** because Max subscription = $0 marginal CLI cost.

**What changes if capital becomes binding:** flip multi-exchange (currently deferred) up. Why: if you have $5M to deploy and Hyperliquid has $1M position cap on your account, you're capacity-constrained, and another venue is the bottleneck breaker. **Does not apply at $497 equity.**

**What changes if liquidity / edge decay becomes binding:** flip strategy genesis up. Why: if the 11 strategies' Sharpe is tanking week-over-week, you need new alpha to replace them. **Does not apply yet** because the bot isn't even trading; we have no signal that current strategies are decayed vs just untested under live conditions.

So your stated ordering is right for the actual binding constraint (dev time). The sequence that would dominate IS the one you proposed: fix VETO → audit → learn → augment → multiply (cost) → multiply (capital) → multiply (alpha).

**One sequencing nit:** I'd put Adversary in Week 3 alongside the learning loop work, not Week 4. Adversary is ~1 day per blueprint table; it's high-leverage drawdown reduction; and it's parallelizable with the hypothesis-evidence work because they touch different files. Moving it forward gives you DD protection earlier, which matters at 90% DD.

---

## Closing Opinion

The 6-month plan is well-architected for its assumed environment (a small team building toward a $1-3M deployable system over a year). It's overkill for "solo dev needs to fix the bot that's been offline for 92h." The compressed 6-week plan delivers **the survival half** of the original plan (months 1-2 + the safest slice of month 6) while explicitly deferring **the multiplier half** (months 3-5) until the substrate is proven.

Cite the blueprint's own §21.11 closing thought to justify the cut: *"infrastructure first (months 1-2), capability multipliers next (months 3-4), generative engines last (months 5-6)."* Compression preserves that order; it just executes the first phase in 6 weeks instead of 8, and pushes phases 2-3 out by the months they take to do honestly. The blueprint is right that the multipliers compound. That's exactly why you don't rush them — but it's also why you don't let the substrate slip.

Ship Weeks 1-4. Re-evaluate at end of Week 4. Decide canary vs. straight-to-multiplier based on what the bot's behavior looks like with Adversary + Opportunist live for 7 paper days. That's the pareto-optimal call.

---

### Critical Files for Implementation

- /home/user/WAGMI/bot/llm/agents/coordinator.py (the §7-A hardcode at line 4716, sanity guardrail at 741, regime fallback at 3166/3213, kill-list pre-check at 1843 — week 1 changes all live here)
- /home/user/WAGMI/bot/llm/claude_cli_client.py (failure-mode logging at lines 121-145, circuit breaker scaffold for week 2-3)
- /home/user/WAGMI/bot/llm/growth/hypothesis_tracker.py (§7-F evidence collector unblock — week 3 work, lines 96-98, 156, 233, 282, 454)
- /home/user/WAGMI/bot/learning/auto_fix_pipeline.py and /home/user/WAGMI/bot/learning/execution_forensics.py (week 3 stubs to flesh out — files exist; need real implementations)
- /home/user/WAGMI/bot/llm/backend.py (does not yet exist — week 2 creation; the LLMBackend ABC scaffold per §9 Steps 1-3 and §5.1-5.4)