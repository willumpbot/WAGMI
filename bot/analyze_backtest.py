#!/usr/bin/env python3
"""
Backtest Data Analyzer — Digestible summaries of all LLM learning data.

Reads and summarizes:
1. backtest_decisions.jsonl — Every LLM decision during backtest
2. deep_memory/insight_journal.json — Insights the LLM accumulated
3. teaching/knowledge_base.json — Trading axioms and their validation status
4. learning_state.json — Learning phase and counterfactual tracking
5. trade_candidates.csv — Per-trade details with outcomes
6. safety_events.csv — Circuit breaker and safety events
7. llm_memory.json — Short-term memory notes

Usage:
    cd bot && python analyze_backtest.py
    cd bot && python analyze_backtest.py --section decisions
    cd bot && python analyze_backtest.py --section knowledge
    cd bot && python analyze_backtest.py --section trades
    cd bot && python analyze_backtest.py --section safety
    cd bot && python analyze_backtest.py --section learning
    cd bot && python analyze_backtest.py --section all
"""

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


# ── File Paths ────────────────────────────────────────────

DATA_DIR = Path("data")
LLM_DIR = DATA_DIR / "llm"
DECISIONS_FILE = LLM_DIR / "backtest_decisions.jsonl"
INSIGHT_FILE = LLM_DIR / "deep_memory" / "insight_journal.json"
KNOWLEDGE_FILE = LLM_DIR / "teaching" / "knowledge_base.json"
LEARNING_FILE = LLM_DIR / "learning_state.json"
MEMORY_FILE = LLM_DIR / "llm_memory.json"
TRADE_CANDIDATES = DATA_DIR / "analysis" / "trade_candidates.csv"
TRADE_OUTCOMES = DATA_DIR / "analysis" / "trade_outcomes.csv"
PERFORMANCE_FILE = DATA_DIR / "analysis" / "performance.json"
SAFETY_FILE = DATA_DIR / "logs" / "safety_events.csv"
STATE_FILE = DATA_DIR / "logs" / "state_transitions.csv"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception) as e:
        print(f"  [!] Failed to read {path}: {e}")
        return {}


def _load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return entries


def _load_csv(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


# ── Section: LLM Decisions ────────────────────────────────

def analyze_decisions():
    print("\n" + "=" * 60)
    print("  LLM DECISIONS (backtest_decisions.jsonl)")
    print("=" * 60)

    decisions = _load_jsonl(DECISIONS_FILE)
    if not decisions:
        print("  No decisions found. File may not exist from this backtest run.")
        print(f"  Expected at: {DECISIONS_FILE}")
        return

    print(f"  Total decisions: {len(decisions)}")

    # Action breakdown
    actions = Counter(d.get("action", "unknown") for d in decisions)
    print(f"\n  Action Breakdown:")
    for action, count in actions.most_common():
        pct = count / len(decisions) * 100
        print(f"    {action:15s} {count:4d} ({pct:.1f}%)")

    # Confidence distribution
    confs = [d.get("confidence", 0) for d in decisions if "confidence" in d]
    if confs:
        print(f"\n  Confidence Distribution:")
        buckets = {"<0.3": 0, "0.3-0.5": 0, "0.5-0.7": 0, "0.7-0.85": 0, "0.85+": 0}
        for c in confs:
            if c < 0.3:
                buckets["<0.3"] += 1
            elif c < 0.5:
                buckets["0.3-0.5"] += 1
            elif c < 0.7:
                buckets["0.5-0.7"] += 1
            elif c < 0.85:
                buckets["0.7-0.85"] += 1
            else:
                buckets["0.85+"] += 1
        for bucket, count in buckets.items():
            bar = "#" * (count * 2)
            print(f"    {bucket:10s} {count:3d} {bar}")

    # Regime breakdown
    regimes = Counter(d.get("regime", "unknown") for d in decisions)
    print(f"\n  Regime Breakdown:")
    for regime, count in regimes.most_common():
        print(f"    {regime:20s} {count:4d}")

    # Per-agent costs (if available)
    cost_data = [d for d in decisions if "cost" in d or "agent_costs" in d]
    if cost_data:
        total_cost = sum(d.get("cost", 0) for d in decisions)
        print(f"\n  Total LLM Cost: ${total_cost:.4f}")

    # Veto reasons (from notes)
    vetoed = [d for d in decisions if d.get("action") in ("flat", "skip")]
    if vetoed:
        print(f"\n  Top Veto Reasons (from {len(vetoed)} vetoes):")
        reasons = Counter()
        for d in vetoed:
            notes = d.get("notes", "") or ""
            if "consistency_override" in notes:
                reasons["consistency_override"] += 1
            elif "QUANT_NOISE" in notes:
                reasons["quant_noise"] += 1
            elif "critic" in notes.lower():
                reasons["critic_veto"] += 1
            elif notes:
                # Take first 50 chars as reason
                reasons[notes[:50]] += 1
            else:
                reasons["(no reason given)"] += 1
        for reason, count in reasons.most_common(10):
            print(f"    {count:3d}x  {reason}")

    # Show last 5 decisions
    print(f"\n  Last 5 Decisions:")
    for d in decisions[-5:]:
        action = d.get("action", "?")
        conf = d.get("confidence", 0)
        regime = d.get("regime", "?")
        notes = (d.get("notes", "") or "")[:60]
        print(f"    [{action:6s}] conf={conf:.2f} regime={regime:15s} {notes}")


# ── Section: Knowledge Base ───────────────────────────────

def analyze_knowledge():
    print("\n" + "=" * 60)
    print("  KNOWLEDGE BASE (teaching/knowledge_base.json)")
    print("=" * 60)

    data = _load_json(KNOWLEDGE_FILE)
    entries = data.get("entries", [])
    if not entries:
        print("  Empty knowledge base.")
        return

    print(f"  Total entries: {len(entries)}")

    # By source
    sources = Counter(e.get("source", "unknown") for e in entries)
    print(f"\n  By Source:")
    for source, count in sources.most_common():
        print(f"    {source:20s} {count:4d}")

    # By type
    types = Counter(e.get("knowledge_type", "unknown") for e in entries)
    print(f"\n  By Type:")
    for ktype, count in types.most_common():
        print(f"    {ktype:20s} {count:4d}")

    # By category
    categories = Counter(e.get("category", "unknown") for e in entries)
    print(f"\n  By Category:")
    for cat, count in categories.most_common():
        print(f"    {cat:20s} {count:4d}")

    # Validation status
    validated = [e for e in entries if e.get("validation_count", 0) > 0]
    invalidated = [e for e in entries if e.get("invalidation_count", 0) > 0]
    with_evidence = [e for e in entries if e.get("evidence_count", 0) > 0]
    print(f"\n  Validation Status:")
    print(f"    Validated (1+ confirmations):   {len(validated)}")
    print(f"    Invalidated (1+ contradictions): {len(invalidated)}")
    print(f"    With evidence:                   {len(with_evidence)}")
    print(f"    Untested (no real-world data):   {len(entries) - len(validated) - len(invalidated)}")

    if validated:
        print(f"\n  Validated Axioms:")
        for e in sorted(validated, key=lambda x: x.get("validation_count", 0), reverse=True)[:5]:
            print(f"    [{e.get('validation_count', 0)}x] {e['content'][:80]}")

    if invalidated:
        print(f"\n  Invalidated (may need revision):")
        for e in sorted(invalidated, key=lambda x: x.get("invalidation_count", 0), reverse=True)[:5]:
            print(f"    [{e.get('invalidation_count', 0)}x] {e['content'][:80]}")

    # Show high-confidence axioms
    axioms = [e for e in entries if e.get("knowledge_type") == "axiom"]
    if axioms:
        print(f"\n  Top Axioms (confidence >= 0.9):")
        for e in sorted(axioms, key=lambda x: x.get("confidence", 0), reverse=True)[:10]:
            conf = e.get("confidence", 0)
            print(f"    [{conf:.2f}] {e['content'][:80]}")


# ── Section: Insight Journal ──────────────────────────────

def analyze_insights():
    print("\n" + "=" * 60)
    print("  INSIGHT JOURNAL (deep_memory/insight_journal.json)")
    print("=" * 60)

    data = _load_json(INSIGHT_FILE)
    insights = data.get("insights", [])
    if not insights:
        print("  No insights recorded.")
        return

    print(f"  Total insights: {len(insights)}")

    # By category
    categories = Counter(i.get("category", "unknown") for i in insights)
    print(f"\n  By Category:")
    for cat, count in categories.most_common():
        print(f"    {cat:25s} {count:4d}")

    # By source
    sources = Counter(i.get("source", "unknown") for i in insights)
    print(f"\n  By Source:")
    for source, count in sources.most_common():
        print(f"    {source:25s} {count:4d}")

    # Validation status
    validated = [i for i in insights if i.get("validated")]
    print(f"\n  Validated: {len(validated)} / {len(insights)}")

    # List all insights
    print(f"\n  All Insights:")
    for i, ins in enumerate(insights, 1):
        conf = ins.get("confidence", 0)
        val = "Y" if ins.get("validated") else "N"
        vc = ins.get("validation_count", 0)
        print(f"    {i:2d}. [{conf:.2f}|val={val}|n={vc}] {ins['insight'][:75]}")


# ── Section: Learning State ───────────────────────────────

def analyze_learning():
    print("\n" + "=" * 60)
    print("  LEARNING STATE (learning_state.json)")
    print("=" * 60)

    data = _load_json(LEARNING_FILE)
    if not data:
        print("  No learning state found.")
        return

    print(f"  Current Phase:        {data.get('phase', '?')}")
    print(f"  Trades Observed:      {data.get('trades_observed', 0)}")
    print(f"  Signals Observed:     {data.get('signals_observed', 0)}")
    print(f"  Graduated:            {data.get('graduated', False)}")
    print(f"  Graduation Reason:    {data.get('graduation_reason', '(none)')}")

    # Counterfactuals
    cfs = data.get("counterfactuals", [])
    cf_correct = data.get("counterfactual_correct", 0)
    cf_total = data.get("counterfactual_total", 0)
    print(f"\n  Counterfactual Analysis:")
    print(f"    Total:   {cf_total}")
    print(f"    Correct: {cf_correct}")
    if cf_total > 0:
        print(f"    Accuracy: {cf_correct / cf_total:.1%}")

    if cfs:
        print(f"\n  Counterfactual Details:")
        for cf in cfs:
            veto = "VETO" if cf.get("would_veto") else "ALLOW"
            actual = cf.get("actual", "?")
            pnl = cf.get("pnl", 0)
            correct = "CORRECT" if cf.get("correct") else "WRONG"
            symbol = cf.get("symbol", "?")
            print(f"    {symbol:6s} Would {veto:5s} -> Actual {actual:4s} (${pnl:+.2f}) = {correct}")

    # Phase transitions
    transitions = data.get("phase_transitions", [])
    if transitions:
        print(f"\n  Phase Transitions:")
        for t in transitions:
            print(f"    {t}")


# ── Section: Short-Term Memory ────────────────────────────

def analyze_memory():
    print("\n" + "=" * 60)
    print("  SHORT-TERM MEMORY (llm_memory.json)")
    print("=" * 60)

    data = _load_json(MEMORY_FILE)
    notes = data.get("notes", [])
    if not notes:
        print("  Memory is empty. The LLM stored no observations.")
        print("  This means the Trade Agent's 'mu' field was null for all decisions.")
        return

    print(f"  Total notes: {len(notes)}")
    print(f"  Last updated: {data.get('last_updated', 0)}")
    for i, note in enumerate(notes[-20:], 1):
        if isinstance(note, dict):
            text = note.get("text", note.get("content", str(note)))
            ts = note.get("ts", note.get("timestamp", ""))
            print(f"    {i:2d}. [{ts}] {text[:80]}")
        else:
            print(f"    {i:2d}. {str(note)[:80]}")


# ── Section: Trade Candidates ─────────────────────────────

def analyze_trades():
    print("\n" + "=" * 60)
    print("  TRADE CANDIDATES (analysis/trade_candidates.csv)")
    print("=" * 60)

    trades = _load_csv(TRADE_CANDIDATES)
    if not trades:
        print("  No trade candidates found.")
        return

    print(f"  Total trades: {len(trades)}")

    # By outcome
    outcomes = Counter(t.get("outcome", "unknown") for t in trades)
    print(f"\n  By Outcome:")
    for outcome, count in outcomes.most_common():
        print(f"    {outcome:15s} {count:4d}")

    # By symbol
    symbols = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        sym = t.get("symbol", "?")
        pnl = float(t.get("realized_pnl", 0) or 0)
        symbols[sym]["count"] += 1
        symbols[sym]["pnl"] += pnl
        if pnl > 0:
            symbols[sym]["wins"] += 1

    print(f"\n  By Symbol:")
    print(f"    {'Symbol':8s} {'Trades':>7s} {'WR':>6s} {'PnL':>12s}")
    for sym, data in sorted(symbols.items(), key=lambda x: x[1]["pnl"]):
        wr = data["wins"] / data["count"] * 100 if data["count"] > 0 else 0
        print(f"    {sym:8s} {data['count']:7d} {wr:5.1f}% ${data['pnl']:>10.2f}")

    # By entry type
    entry_types = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        et = t.get("entry_type", "unknown")
        pnl = float(t.get("realized_pnl", 0) or 0)
        entry_types[et]["count"] += 1
        entry_types[et]["pnl"] += pnl
        if pnl > 0:
            entry_types[et]["wins"] += 1

    print(f"\n  By Entry Type:")
    print(f"    {'Type':12s} {'Trades':>7s} {'WR':>6s} {'PnL':>12s}")
    for et, data in sorted(entry_types.items(), key=lambda x: x[1]["pnl"]):
        wr = data["wins"] / data["count"] * 100 if data["count"] > 0 else 0
        print(f"    {et:12s} {data['count']:7d} {wr:5.1f}% ${data['pnl']:>10.2f}")

    # By regime
    regimes = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        rg = t.get("regime", "unknown")
        pnl = float(t.get("realized_pnl", 0) or 0)
        regimes[rg]["count"] += 1
        regimes[rg]["pnl"] += pnl
        if pnl > 0:
            regimes[rg]["wins"] += 1

    print(f"\n  By Regime:")
    print(f"    {'Regime':20s} {'Trades':>7s} {'WR':>6s} {'PnL':>12s}")
    for rg, data in sorted(regimes.items(), key=lambda x: x[1]["pnl"]):
        wr = data["wins"] / data["count"] * 100 if data["count"] > 0 else 0
        print(f"    {rg:20s} {data['count']:7d} {wr:5.1f}% ${data['pnl']:>10.2f}")

    # LLM vs strategy-only
    llm_trades = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0})
    for t in trades:
        llm_action = t.get("llm_action", "none")
        pnl = float(t.get("realized_pnl", 0) or 0)
        llm_trades[llm_action]["count"] += 1
        llm_trades[llm_action]["pnl"] += pnl
        if pnl > 0:
            llm_trades[llm_action]["wins"] += 1

    if llm_trades:
        print(f"\n  LLM Action Breakdown:")
        print(f"    {'LLM Action':15s} {'Trades':>7s} {'WR':>6s} {'PnL':>12s}")
        for action, data in sorted(llm_trades.items(), key=lambda x: x[1]["pnl"]):
            wr = data["wins"] / data["count"] * 100 if data["count"] > 0 else 0
            print(f"    {action:15s} {data['count']:7d} {wr:5.1f}% ${data['pnl']:>10.2f}")

    # Top winners and losers
    sorted_by_pnl = sorted(trades, key=lambda t: float(t.get("realized_pnl", 0) or 0))
    print(f"\n  Top 5 Losers:")
    for t in sorted_by_pnl[:5]:
        pnl = float(t.get("realized_pnl", 0) or 0)
        sym = t.get("symbol", "?")
        side = t.get("side", "?")
        lev = t.get("leverage_used", "?")
        reason = t.get("close_reason", "?")
        regime = t.get("regime", "?")
        print(f"    {sym:6s} {side:5s} ${pnl:>9.2f}  lev={lev}x  {reason:15s} [{regime}]")

    print(f"\n  Top 5 Winners:")
    for t in sorted_by_pnl[-5:]:
        pnl = float(t.get("realized_pnl", 0) or 0)
        sym = t.get("symbol", "?")
        side = t.get("side", "?")
        lev = t.get("leverage_used", "?")
        reason = t.get("close_reason", "?")
        regime = t.get("regime", "?")
        print(f"    {sym:6s} {side:5s} ${pnl:>9.2f}  lev={lev}x  {reason:15s} [{regime}]")

    # Leverage distribution
    levs = []
    for t in trades:
        try:
            levs.append(float(t.get("leverage_used", 0) or 0))
        except (ValueError, TypeError):
            pass
    if levs:
        avg_lev = sum(levs) / len(levs)
        max_lev = max(levs)
        print(f"\n  Leverage Distribution:")
        print(f"    Average: {avg_lev:.1f}x  Max: {max_lev:.1f}x")
        buckets = {"1-2x": 0, "2-3x": 0, "3-5x": 0, "5-8x": 0, "8x+": 0}
        for l in levs:
            if l <= 2:
                buckets["1-2x"] += 1
            elif l <= 3:
                buckets["2-3x"] += 1
            elif l <= 5:
                buckets["3-5x"] += 1
            elif l <= 8:
                buckets["5-8x"] += 1
            else:
                buckets["8x+"] += 1
        for bucket, count in buckets.items():
            bar = "#" * (count * 2)
            print(f"    {bucket:6s} {count:3d} {bar}")

    # Leverage vs outcome correlation
    lev_outcomes = {"1-2x": {"trades": 0, "wins": 0, "pnl": 0.0},
                    "2-3x": {"trades": 0, "wins": 0, "pnl": 0.0},
                    "3-5x": {"trades": 0, "wins": 0, "pnl": 0.0},
                    "5-8x": {"trades": 0, "wins": 0, "pnl": 0.0},
                    "8x+":  {"trades": 0, "wins": 0, "pnl": 0.0}}
    for t in trades:
        try:
            lev = float(t.get("leverage_used", 0) or 0)
            pnl = float(t.get("realized_pnl", 0) or 0)
        except (ValueError, TypeError):
            continue
        if lev <= 0:
            continue
        if lev <= 2:
            bucket = "1-2x"
        elif lev <= 3:
            bucket = "2-3x"
        elif lev <= 5:
            bucket = "3-5x"
        elif lev <= 8:
            bucket = "5-8x"
        else:
            bucket = "8x+"
        lev_outcomes[bucket]["trades"] += 1
        lev_outcomes[bucket]["pnl"] += pnl
        if pnl > 0:
            lev_outcomes[bucket]["wins"] += 1

    has_lev_data = any(v["trades"] > 0 for v in lev_outcomes.values())
    if has_lev_data:
        print(f"\n  Leverage vs Outcome:")
        print(f"    {'Bucket':8s} {'Trades':>7s} {'WR':>6s} {'Total PnL':>12s} {'Avg PnL':>10s}")
        for bucket, data in lev_outcomes.items():
            if data["trades"] == 0:
                continue
            wr = data["wins"] / data["trades"] * 100
            avg_pnl = data["pnl"] / data["trades"]
            print(f"    {bucket:8s} {data['trades']:7d} {wr:5.1f}% ${data['pnl']:>10.2f} ${avg_pnl:>8.2f}")


# ── Section: Exit Type Analysis ──────────────────────────

def _lev_bucket(lev: float) -> str:
    if lev <= 2:
        return "1-2x"
    elif lev <= 3:
        return "2-3x"
    elif lev <= 5:
        return "3-5x"
    elif lev <= 8:
        return "5-8x"
    return "8x+"


def analyze_exits():
    print("\n" + "=" * 60)
    print("  EXIT TYPE ANALYSIS (trade_outcomes.csv + trade_candidates.csv)")
    print("=" * 60)

    outcomes = _load_csv(TRADE_OUTCOMES)
    candidates = _load_csv(TRADE_CANDIDATES)

    # Prefer outcomes (has state_path, tp1_hit, sl_after_tp1)
    # Fall back to candidates (has close_reason)
    if not outcomes and not candidates:
        print("  No trade data found. Run a backtest with outcome recording enabled.")
        return

    # ── From trade_outcomes.csv ──
    if outcomes:
        print(f"\n  Trade Outcomes: {len(outcomes)} trades")

        # Exit type distribution from state_path
        exit_types = Counter()
        exit_pnl = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
        tp1_hit_count = 0
        sl_after_tp1_count = 0
        total_with_tp1_data = 0

        for row in outcomes:
            state_path = row.get("state_path", "unknown")
            # state_path can be complex like "OPEN→TP1_HIT→TRAILING→CLOSED"
            # Extract the final exit action
            exit_action = state_path.split("→")[-1] if "→" in state_path else state_path
            # Normalize common exit types
            if exit_action in ("SL", "TP1", "TP2", "TRAILING_STOP", "BACKTEST_END",
                               "CIRCUIT_BREAKER", "LLM_EXIT", "EARLY_EXIT",
                               "HOLD_LIMIT", "EMERGENCY"):
                exit_type = exit_action
            elif exit_action == "CLOSED":
                # Look back in path for the trigger
                if "TRAILING" in state_path:
                    exit_type = "TRAILING_STOP"
                elif "TP1" in state_path:
                    exit_type = "TP1"
                else:
                    exit_type = "CLOSED"
            else:
                exit_type = exit_action

            exit_types[exit_type] += 1

            try:
                pnl = float(row.get("pnl", 0) or 0)
            except (ValueError, TypeError):
                pnl = 0.0
            exit_pnl[exit_type]["trades"] += 1
            exit_pnl[exit_type]["pnl"] += pnl
            if pnl > 0:
                exit_pnl[exit_type]["wins"] += 1

            # TP1 hit rate
            tp1_hit_val = row.get("tp1_hit", "").lower()
            if tp1_hit_val in ("true", "1", "yes"):
                tp1_hit_count += 1
                total_with_tp1_data += 1
            elif tp1_hit_val in ("false", "0", "no"):
                total_with_tp1_data += 1

            # SL after TP1
            sl_tp1_val = row.get("sl_after_tp1", "").lower()
            if sl_tp1_val in ("true", "1", "yes"):
                sl_after_tp1_count += 1

        # Exit type distribution
        print(f"\n  Exit Type Distribution:")
        total = sum(exit_types.values())
        for etype, count in exit_types.most_common():
            pct = count / total * 100 if total else 0
            bar = "#" * max(1, int(count / max(1, total) * 40))
            print(f"    {etype:18s} {count:4d} ({pct:5.1f}%) {bar}")

        # Win rate and PnL by exit type
        print(f"\n  Performance by Exit Type:")
        print(f"    {'Exit Type':18s} {'Trades':>7s} {'WR':>6s} {'Total PnL':>12s} {'Avg PnL':>10s}")
        for etype, data in sorted(exit_pnl.items(), key=lambda x: x[1]["pnl"]):
            if data["trades"] == 0:
                continue
            wr = data["wins"] / data["trades"] * 100
            avg_pnl = data["pnl"] / data["trades"]
            print(f"    {etype:18s} {data['trades']:7d} {wr:5.1f}% ${data['pnl']:>10.2f} ${avg_pnl:>8.2f}")

        # TP1 hit rate
        if total_with_tp1_data > 0:
            tp1_rate = tp1_hit_count / total_with_tp1_data * 100
            print(f"\n  TP1 Hit Rate: {tp1_hit_count}/{total_with_tp1_data} ({tp1_rate:.1f}%)")
            if sl_after_tp1_count > 0:
                giveback_rate = sl_after_tp1_count / total_with_tp1_data * 100
                print(f"  SL After TP1 (profit give-back): {sl_after_tp1_count} ({giveback_rate:.1f}%)")

        # Exit type by strategy
        strat_exits = defaultdict(lambda: Counter())
        for row in outcomes:
            strat = row.get("strategy", "unknown")
            state_path = row.get("state_path", "unknown")
            exit_action = state_path.split("→")[-1] if "→" in state_path else state_path
            if exit_action == "CLOSED" and "TRAILING" in state_path:
                exit_action = "TRAILING_STOP"
            elif exit_action == "CLOSED" and "TP1" in state_path:
                exit_action = "TP1"
            strat_exits[strat][exit_action] += 1

        if strat_exits:
            # Collect all exit types for column headers
            all_exits = sorted(set(e for counts in strat_exits.values() for e in counts))
            print(f"\n  Exit Type by Strategy:")
            header = f"    {'Strategy':22s}" + "".join(f" {e:>8s}" for e in all_exits)
            print(header)
            for strat in sorted(strat_exits.keys()):
                row_str = f"    {strat:22s}"
                for e in all_exits:
                    row_str += f" {strat_exits[strat].get(e, 0):>8d}"
                print(row_str)

    # ── From trade_candidates.csv (close_reason) ──
    if candidates and not outcomes:
        print(f"\n  Trade Candidates Exit Reasons: {len(candidates)} candidates")
        close_reasons = Counter()
        reason_pnl = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
        for t in candidates:
            reason = t.get("close_reason", "unknown") or "unknown"
            pnl = float(t.get("realized_pnl", 0) or 0)
            close_reasons[reason] += 1
            reason_pnl[reason]["trades"] += 1
            reason_pnl[reason]["pnl"] += pnl
            if pnl > 0:
                reason_pnl[reason]["wins"] += 1

        print(f"\n  Close Reason Distribution:")
        for reason, count in close_reasons.most_common():
            print(f"    {reason:18s} {count:4d}")

        print(f"\n  Performance by Close Reason:")
        print(f"    {'Reason':18s} {'Trades':>7s} {'WR':>6s} {'Total PnL':>12s}")
        for reason, data in sorted(reason_pnl.items(), key=lambda x: x[1]["pnl"]):
            if data["trades"] == 0:
                continue
            wr = data["wins"] / data["trades"] * 100
            print(f"    {reason:18s} {data['trades']:7d} {wr:5.1f}% ${data['pnl']:>10.2f}")

    # ── Cross-reference: exit type by trade profile (entry_type) ──
    if outcomes:
        profile_exits = defaultdict(lambda: Counter())
        for row in outcomes:
            entry_type = row.get("entry_type", "unknown") or "unknown"
            state_path = row.get("state_path", "unknown")
            exit_action = state_path.split("→")[-1] if "→" in state_path else state_path
            if exit_action == "CLOSED" and "TRAILING" in state_path:
                exit_action = "TRAILING_STOP"
            elif exit_action == "CLOSED" and "TP1" in state_path:
                exit_action = "TP1"
            profile_exits[entry_type][exit_action] += 1

        if profile_exits and any(k != "unknown" for k in profile_exits):
            all_exits = sorted(set(e for counts in profile_exits.values() for e in counts))
            print(f"\n  Exit Type by Trade Profile:")
            header = f"    {'Profile':14s}" + "".join(f" {e:>8s}" for e in all_exits)
            print(header)
            for profile in sorted(profile_exits.keys()):
                row_str = f"    {profile:14s}"
                for e in all_exits:
                    row_str += f" {profile_exits[profile].get(e, 0):>8d}"
                print(row_str)


# ── Section: Safety Events ────────────────────────────────

def analyze_safety():
    print("\n" + "=" * 60)
    print("  SAFETY EVENTS (logs/safety_events.csv)")
    print("=" * 60)

    events = _load_csv(SAFETY_FILE)
    if not events:
        print("  No safety events found.")
        return

    print(f"  Total events: {len(events)}")

    # By event type
    types = Counter(e.get("event_type", "unknown") for e in events)
    print(f"\n  By Type:")
    for etype, count in types.most_common():
        print(f"    {etype:25s} {count:4d}")

    # CB trip reasons
    cb_events = [e for e in events if e.get("event_type") == "circuit_breaker"]
    if cb_events:
        reasons = Counter()
        for e in cb_events:
            reason = e.get("reason", "unknown")
            # Normalize: "Daily loss 5.1% >= 5.0% limit" -> "Daily loss"
            if "Daily loss" in reason:
                reasons["Daily loss limit"] += 1
            elif "Drawdown" in reason:
                reasons["Drawdown limit"] += 1
            elif "consecutive" in reason:
                reasons["Consecutive losses"] += 1
            else:
                reasons[reason[:40]] += 1

        print(f"\n  Circuit Breaker Trips ({len(cb_events)} total):")
        for reason, count in reasons.most_common():
            print(f"    {reason:25s} {count:4d}")


# ── Section: Performance Summary ──────────────────────────

def analyze_performance():
    print("\n" + "=" * 60)
    print("  PERFORMANCE SUMMARY (analysis/performance.json)")
    print("=" * 60)

    data = _load_json(PERFORMANCE_FILE)
    if not data:
        print("  No performance data found.")
        return

    print(f"  Total Trades:  {data.get('total_trades', '?')}")
    print(f"  Win Rate:      {data.get('win_rate', '?')}")
    print(f"  Average R:R:   {data.get('avg_rr', '?')}")
    print(f"  Total PnL:     ${data.get('total_pnl', 0):.2f}")

    # Breakdowns
    for key in ("by_entry_type", "by_regime", "by_strategy"):
        breakdown = data.get(key, {})
        if breakdown:
            print(f"\n  {key.replace('_', ' ').title()}:")
            for name, stats in breakdown.items():
                if isinstance(stats, dict):
                    print(f"    {name:20s} trades={stats.get('count', '?')} "
                          f"wr={stats.get('win_rate', '?')} pnl=${stats.get('pnl', 0):.2f}")


# ── Main ──────────────────────────────────────────────────

SECTIONS = {
    "decisions": analyze_decisions,
    "knowledge": analyze_knowledge,
    "insights": analyze_insights,
    "learning": analyze_learning,
    "memory": analyze_memory,
    "trades": analyze_trades,
    "exits": analyze_exits,
    "safety": analyze_safety,
    "performance": analyze_performance,
}


def main():
    parser = argparse.ArgumentParser(description="Analyze backtest LLM data")
    parser.add_argument(
        "--section", "-s",
        choices=list(SECTIONS.keys()) + ["all"],
        default="all",
        help="Which section to analyze (default: all)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  BACKTEST DATA ANALYZER")
    print("=" * 60)

    if args.section == "all":
        for name, func in SECTIONS.items():
            try:
                func()
            except Exception as e:
                print(f"\n  [!] Error in {name}: {e}")
    else:
        try:
            SECTIONS[args.section]()
        except Exception as e:
            print(f"\n  [!] Error: {e}")

    print("\n" + "=" * 60)
    print("  DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
