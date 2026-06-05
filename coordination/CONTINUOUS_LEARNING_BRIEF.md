# Continuous Learning Architecture Brief

**From:** desktop-claude (synthesized from Nunu's direction)
**To:** laptop-claude
**Date:** 2026-06-02 21:20 UTC
**Priority:** HIGH — Nunu sees this as our biggest edge

## The Vision

> "I feel like theres better ways that we can run our historical backtest walk forwards etc to scrape out data continuously... This might be our biggest edge -- the capabilities to continuously learn and understand to improve our system and knowledge."
> -- Nunu, 2026-06-02

We have:
- Years of OHLC data across multiple symbols
- A 5-agent LLM decision pipeline that produces rich reasoning
- A counterfactual + graduated rules system that codifies what works
- A CLI subscription with rolling quota windows

We do NOT have:
- A way to process all that historical data continuously without burning quota
- A way for the bot to learn over time from its own past decisions
- A way to walk-forward-validate rules before they reach production

This brief is the design space. Pick what you can build; flag what you cannot.

---

## Five Levers, Ranked By Impact

### Lever 1: Signal-fingerprint Decision Cache (BIGGEST LEVERAGE)

**Problem:** Every backtest run hits the LLM pipeline on every signal. If the same setup repeats (and it does -- markets have patterns), we pay full LLM cost every time.

**Idea:** For each signal, compute a "fingerprint" -- a hash or vector of:
- Symbol
- Regime (trending_bear, range, panic, etc.)
- Setup type (BB squeeze, MTQ, multi-agree)
- ATR percentile bucket (0-25, 25-50, 50-75, 75-100)
- Confidence bucket (20-40, 40-60, 60-80, 80-100)
- Cross-asset alignment (BTC bull/bear, etc.)

Cache the agent decision (skip / go / leverage / risk_pct / thesis_class) keyed by fingerprint. On the next backtest, lookup-first; only invoke LLM on cache MISS.

**Expected speedup:** 10-50x on backtests where setups repeat.

**Trade-off:** Cached decisions are "frozen" -- they reflect what agents thought at cache time, not now. Need:
- TTL (decisions older than 30 days expire)
- Override flag for "always-fresh" trades (e.g., during regime transitions)
- Cache invalidation when prompts change

**Implementation sketch:**
- `bot/llm/agents/decision_cache.py`: JSON store of `{fingerprint: decision}`
- Hook in `coordinator.get_entry_decision()`: check cache first, only call agents on miss
- Stats tracking: cache hit rate, age distribution, regime distribution

**What to build first:** Just the fingerprint function + cache lookup wrapper. No need to populate cache yet -- that happens on first run.

---

### Lever 2: Two-Stage Mechanical Pre-Filter

**Problem:** ~70% of backtest signals get vetoed (skip). Each veto burns one full 5-agent LLM cycle (~30-60s, multiple Opus calls).

**Idea:** Before invoking LLM, run a 1-second mechanical filter:
- Confidence < 20? skip without LLM
- Setup type in known-bad list? skip
- Symbol in known-bad regime? skip
- Win-prob model says < 30%? skip

Only pass setups that survive this pre-filter into the LLM. Existing graduated rules system can be the basis -- just hook it BEFORE the LLM, not as a context input.

**Expected speedup:** 3-5x on backtests where most signals get vetoed.

**Trade-off:** Lose nuance -- the LLM might have caught an exception. Mitigate by allowing "override" cases (e.g., user-flagged setups) to bypass the pre-filter.

**Implementation sketch:**
- `bot/backtest/cheap_filter.py`: pure-python rule-based filter
- Returns: PASS (run LLM) / VETO_OBVIOUS (skip LLM, log as veto) / ESCALATE (definitely run LLM, high-priority)
- Configurable strictness so we can A/B test

---

### Lever 3: True Walk-Forward Validation

**Problem:** We currently run isolated backtest windows (Jan 2026, Mar 2026, etc.). Each is a snapshot, not a learning loop.

**Idea:** Walk-forward methodology:
- Train on month N (build graduated rules from outcomes)
- Test on month N+1 (frozen rules, no new learning)
- Slide forward
- Aggregate test-period performance

This catches:
- Rule decay (a rule that worked in Feb may fail in April)
- Regime-dependence (rules learned in trending markets fail in range)
- Overfitting (rules with high in-sample WR but low out-of-sample)

**Expected outcome:** A "rule confidence" score -- rules with high out-of-sample WR are real edges; rules with in-sample-only WR are noise.

**Implementation sketch:**
- `bot/backtest/walk_forward.py`: orchestrator that runs train, freeze, test, slide
- Output: `analysis/walk_forward/rule_confidence_scores.json`
- Promote rules with WF score > X to production; demote rules with WF score < Y to "candidates"

**Caveat:** Needs the existing rule-graduation system to be honest about rule lineage and timestamps.

---

### Lever 4: Parallel Symbol Processing

**Problem:** Backtests run one symbol at a time. BTC, ETH, SOL, HYPE could all run simultaneously.

**Idea:** Spawn subprocesses (or threads if Python GIL allows) for each symbols backtest. Quota is per-API-call not per-process, so 4 simultaneous backtests = 4x throughput.

**Expected speedup:** ~4x wall-clock, same total quota.

**Trade-off:** Quota burn rate also goes up 4x. If you would hit a rate limit in 15 min serially, you will hit it in 4 min parallel. Need to coordinate with desktop bots quota usage.

**Implementation sketch:**
- `bot/scripts/parallel_backtest.sh` (or Python equivalent)
- 4 backtest subprocesses, separate log dirs
- Watch quota: if any subprocess hits 429, all pause for 60s

---

### Lever 5: Synthetic Skip Shortcuts

**Problem:** Many "skip" decisions are obvious -- solo signal in range regime with 36% historical WR. LLM does not add value, just burns quota.

**Idea:** Hard-code a "synthetic agent" that, when conditions match a known-bad pattern, returns a structured skip decision without invoking the LLM. Pattern examples:
- "SOL SHORT in range" -> synthetic skip (we know it is toxic from data)
- "Solo non-BB signal in low-volume hours" -> synthetic skip
- "Confidence < 25% in consolidation" -> synthetic skip

These shortcuts are the rule of last resort BEFORE the LLM, not after. Keep them visible (logged) so we can audit which patterns get bypassed.

**Expected speedup:** Reduces LLM load by ~30% on backtests, ~10% on live.

**Trade-off:** Same as pre-filter (Lever 2) -- we might miss nuance. Mitigate by reviewing skip-shortcut patterns weekly.

---

## The Meta-Vision: Self-Improving Loop

These five levers compose into a learning system:

```
OHLC data -> Pre-filter (L2) -> Cache lookup (L1) -> LLM if miss
                                                          |
                                                          v
                                                Decision + outcome
                                                          |
                                                          v
                                                Walk-forward eval (L3)
                                                          |
                                                          v
                                              Rule promotion/demotion
                                                          |
                                                          v
                                              Updated synthetic skip rules (L5)
                                                          |
                                                          v
                                              Cache invalidation as needed
```

The bot **gets smarter every time you run a backtest** -- not just because of more data, but because the rules system uses walk-forward to weed out noise.

This is what Nunu means by "alpha consistent profitable engine." It is not a single algorithm; it is a system that learns its own limits.

---

## Priority Order for You

If you can only build 2 things, build #1 and #3:
- **#1 Decision cache** is the immediate throughput win
- **#3 Walk-forward** is the long-term rule-quality win

If you can build 3, add #2 (pre-filter) -- it is a quick win.

#4 (parallel) and #5 (synthetic skip) are nice-to-haves that depend on #1/#2 being built first.

## Hard Constraints

- **No new ANTHROPIC_API_KEY.** Subscription CLI only.
- **No changes to live bot config.** All builds are in `bot/backtest/`, `bot/llm/agents/decision_cache.py`, etc.
- **Push small, push often.** Do not accumulate 1000-line uncommitted changes.
- **Log everything.** Cache hits/misses, pre-filter pass/veto rates, walk-forward scores -- all need to be measurable.

## What to Send Back

When you have built ANY of the five, push:
1. The code
2. A `analysis/continuous_learning/<lever>_results.md` doc with: what got built, what the metrics show, what is the next step
3. Update this brief with your status

I will keep monitoring the live bot. When you push something major, ping me via handshake and I will consider whether to integrate into the live path (decision cache + pre-filter would help live trading too, not just backtests).

-- desktop-claude
