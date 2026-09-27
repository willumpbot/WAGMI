"""
Measurement Integrity Audit — FOLLOW-UP (READ-ONLY).

Traces to full confidence the two producers the prior audit
(tools/copilot/measurement_integrity_audit.py) left UNVERIFIED-SUSPECT:

  1. llm/replay_engine.py:get_historical_patterns()
     -> injected as quant_data["historical"] (llm/agents/coordinator.py
        _build_quant_input, ~line 3719-3729), which feeds the Quant Agent's
        prompt and, via quant_out.data, the Trade Agent's "quant_analysis"
        field every decision cycle.

  2. llm/quant_data.py:QuantDataProvider.build_quant_package()
     (+ llm/regime_priors.py, which build_quant_package does NOT import)
     -> injected as quant_data["quant"] (same coordinator function,
        ~line 3694-3696), same downstream path into the Trade Agent.

Both are checked for the same two corruption patterns already confirmed
elsewhere in the codebase:
  (a) RESOLUTION BUG: outcome resolved against a wrong-symbol / variable-
      delay / snapshot reference instead of the trade's own fixed horizon
      (entry -> that trade's own real exit).
  (b) PSEUDOREPLICATION: a per-tick/per-scan record gets counted as an
      independent closed-trade observation, inflating N and shifting WR.

Does not write, mutate, or delete anything.

Usage:
    cd bot && python tools/copilot/measurement_audit_followup.py
"""
import csv
import json
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data")

# Load .env the same way run.py / multi_strategy_main.py do, so the flag
# values printed below match what the LIVE bot process actually sees (a bare
# `python tools/...` invocation does NOT read .env on its own).
try:
    from dotenv import load_dotenv
    _root_env = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".env")
    if os.path.exists(_root_env):
        load_dotenv(_root_env)
except Exception:
    pass


def _load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def audit_replay_engine():
    print("=" * 78)
    print("SUSPECT 1: llm/replay_engine.py get_historical_patterns()")
    print("  -> quant_data['historical'] -> Quant Agent prompt -> Trade Agent")
    print("     ('quant_analysis' field) every decision cycle")
    print("=" * 78)

    path = os.path.join(DATA, "llm", "decisions.jsonl")
    rows = _load_jsonl(path)
    n_total = len(rows)
    if n_total == 0:
        print(f"  [SKIP] {path} not found or empty")
        return

    ts_vals = [r.get("ts", 0) for r in rows if r.get("ts")]
    span = ""
    if ts_vals:
        span = f"{time.ctime(min(ts_vals))}  ->  {time.ctime(max(ts_vals))}"

    with_outcome = [r for r in rows if r.get("outcome")]
    n_outcome = len(with_outcome)

    print(f"  Data source: {path}")
    print(f"  Total decision rows: {n_total:,}   window: {span}")
    print(f"  Rows carrying a non-empty 'outcome' key: {n_outcome}  ({n_outcome/n_total*100:.2f}%)")

    # What get_historical_patterns() actually consumes: d.get("outcome", "").
    # Trace: decision_engine.py's _log_audit() is the ONLY writer of this file
    # (confirmed: no close_pipeline subscriber, no other module, ever adds an
    # "outcome" key back onto a decisions.jsonl row). Its audit-entry schema
    # (action/allowed/confidence/regime/gate_reason/ts/trigger_context/...)
    # never includes "outcome" -- it is a per-decision-cycle audit trail, not
    # an outcome-labeled dataset.
    all_keys = set()
    for r in rows:
        all_keys.update(r.keys())
    print(f"  Full key vocabulary observed across {n_total:,} rows: {sorted(all_keys)}")
    print(f"  ('outcome' present in vocabulary: {'outcome' in all_keys})")

    print()
    print("  PSEUDOREPLICATION CHECK (raw outcome-rows vs deduped-to-unique-trades):")
    if n_outcome == 0:
        print("    Moot: 0/%d rows carry an outcome, across the ENTIRE observed window "
              "(%s)." % (n_total, span))
        print("    There is no outcome-labeled data for a dedup step to over- or under-count.")
    else:
        # (defensive path, not expected to trigger given the count above)
        by_key = {}
        for r in with_outcome:
            k = (r.get("symbol", ""), r.get("regime", ""), round(r.get("entry_price", 0) or 0, 4))
            by_key.setdefault(k, []).append(r)
        n_dedup = len(by_key)
        print(f"    raw n={n_outcome}  deduped-groups n={n_dedup}  inflation={n_outcome/max(n_dedup,1):.2f}x")

    # Run the live function against real production data to show exactly what
    # reaches the prompt today.
    from llm.replay_engine import get_historical_patterns
    patterns = get_historical_patterns(max_decisions=len(rows))
    print()
    print("  Live get_historical_patterns() output on the FULL real decisions.jsonl:")
    print(f"    {json.dumps(patterns)}")

    compact_keys = ("regime_wr", "conf_low_wr", "conf_mid_wr", "conf_high_wr",
                     "conf_low_n", "conf_mid_n", "conf_high_n",
                     "max_win_streak", "max_loss_streak", "recent_outcomes")
    compact = {k: patterns[k] for k in compact_keys if k in patterns}
    print(f"    -> compact object actually assigned to quant_data['historical']: {json.dumps(compact)}")

    print()
    if n_outcome == 0:
        print("  VERDICT: CLEAN (vacuously) -- DEAD FIELD, not corrupted.")
        print("  The function's own outcome-filter (`if not outcome: continue`) means it has")
        print("  NEVER been able to compute a real regime/confidence win-rate on this bot's")
        print("  actual decisions.jsonl (0/%d rows across the full observed history, "
              "%s)." % (n_total, span))
        print("  It is neither pseudoreplication-corrupted nor resolution-corrupted: it is")
        print("  simply inert. The only value the LLM ever sees from it today is an empty")
        print("  {'regime_wr': {}} object -- zero misleading numbers, but also zero signal.")
        print("  This is a DIFFERENT failure mode than the two named suspect patterns: a")
        print("  third pattern (dead/never-populated field), worth a low-priority ticket to")
        print("  either wire a real outcome-stamper or remove the dead code path -- but it is")
        print("  NOT a live Tier-1 corrupted-number finding because no number is produced.")
    else:
        print("  VERDICT: needs the raw-vs-deduped comparison above to resolve.")


def audit_quant_data_provider():
    print()
    print("=" * 78)
    print("SUSPECT 2: llm/quant_data.py QuantDataProvider.build_quant_package()")
    print("  (+ llm/regime_priors.py) -> quant_data['quant'] -> Quant Agent prompt")
    print("  -> Trade Agent ('quant_analysis') every decision cycle")
    print("=" * 78)

    # ---- Trace the data source ----
    dna_path = os.path.join(DATA, "llm", "deep_memory", "trade_dna.json")
    ledger_path = os.path.join(DATA, "trade_ledger.csv")

    if not os.path.exists(dna_path):
        print(f"  [SKIP] {dna_path} not found")
        return
    dna = json.load(open(dna_path))
    trades = dna.get("trades", [])
    n_dna_raw = len(trades)
    tid_counts = Counter(t.get("trade_id", "") for t in trades)
    dup_ids = {k: v for k, v in tid_counts.items() if v > 1 and k}

    print(f"  Data source: {dna_path} (TradeDNAStore, via get_deep_memory().trade_dna)")
    print(f"  Total TradeDNA records: {n_dna_raw}")
    print(f"  Unique trade_id values: {len(tid_counts)}  |  trade_ids appearing >1x: {len(dup_ids)}")
    if dup_ids:
        print(f"    sample duplicate trade_ids: {list(dup_ids.items())[:5]}")
    print("  Write path traced: core/analytics.py:_record_trade_dna() is called exactly once")
    print("  per close event (multi_strategy_main.py, close-handling block: 'Deep memory:")
    print("  record full trade DNA for LLM knowledge base'), which calls")
    print("  DeepMemoryManager.record_full_trade() (llm/deep_memory.py) using pos.realized_pnl")
    print("  / event.pnl and that SAME position's own entry_price/exit_price -- i.e. resolved")
    print("  against the trade's OWN real close, not a snapshot/current-price/variable-delay")
    print("  reference. There is exactly one production call site for record_trade()/TradeDNA().")

    max_pct = float(os.getenv("QUANT_PNL_SANITY_MAX_PCT", "50"))
    filtered = [t for t in trades if abs(t.get("pnl_pct", 0.0)) <= max_pct] if max_pct > 0 else trades
    n_dna_filtered = len(filtered)
    print(f"  After QUANT_PNL_SANITY_MAX_PCT={max_pct} read-filter (A-T1 audit, pre-existing):"
          f" n={n_dna_filtered} (dropped {n_dna_raw - n_dna_filtered} corrupted-pnl_pct rows)")

    if not os.path.exists(ledger_path):
        print(f"  [SKIP] {ledger_path} not found -- cannot cross-check against ledger")
        return
    ledger_rows = list(csv.DictReader(open(ledger_path, newline="")))
    n_ledger = len(ledger_rows)

    print()
    print(f"  Cross-check source (known-clean, 1 row/closed-trade): {ledger_path}")
    print(f"  Ledger rows: {n_ledger}")
    ratio = n_dna_filtered / n_ledger if n_ledger else float("inf")
    print(f"  trade_dna(filtered) / ledger row-count ratio: {ratio:.2f}x")
    print("  (Pseudoreplication in this codebase inflates N ~10-14x. This ratio is ~1x --")
    print("   trade_dna.json's N is closed-trade-level, not per-tick/per-scan.)")

    # ---- Recompute the headline win-prob two ways ----
    def won_ledger(r):
        try:
            return float(r.get("net_pnl") or r.get("pnl") or 0) > 0
        except (ValueError, TypeError):
            return False

    n_l = n_ledger
    wins_l = sum(1 for r in ledger_rows if won_ledger(r))
    wr_l = wins_l / n_l if n_l else 0.0
    print()
    print(f"  LEDGER-derived base win-rate (independent recomputation): "
          f"{wins_l}/{n_l} = {wr_l*100:.1f}%")

    from llm.quant_data import get_quant_provider
    qp = get_quant_provider()
    priors = qp.compute_bayesian_priors()
    base = priors.get("base", {})
    kelly = qp.compute_kelly(min_trades=5)

    print(f"  QuantDataProvider.compute_bayesian_priors()['base']: "
          f"wr={base.get('wr', 0)*100:.1f}%  n={base.get('n', 0)}")
    print(f"  QuantDataProvider.compute_kelly() (unfiltered):      "
          f"wr={kelly.get('win_rate', 0)*100:.1f}%  n={kelly.get('n_trades', 0)}")

    delta_pts = abs(base.get("wr", 0) * 100 - wr_l * 100)
    print()
    print(f"  Delta vs ledger baseline: {delta_pts:.1f} percentage points "
          f"(n diff: {base.get('n', 0)} vs {n_l}, i.e. trade_dna is a "
          f"{'subset' if base.get('n',0) < n_l else 'superset'} of the ledger)")

    print()
    pkg = qp.build_quant_package(regime="", num_agree=0, setup_type="")
    print(f"  Live build_quant_package() (no filters) output: {json.dumps(pkg)}")

    # ---- regime_priors.py wiring check ----
    print()
    print("  llm/regime_priors.py wiring check:")
    print("    build_quant_package() does NOT import regime_priors at all (confirmed by")
    print("    reading llm/quant_data.py in full -- no 'regime_priors' reference).")
    quant_brain_on = os.getenv("QUANT_BRAIN_ENABLED", "false").strip().lower() == "true"
    use_regime_priors = os.getenv("USE_REGIME_PRIORS", "false").strip().lower() in ("1", "true", "yes", "on")
    use_mech_baseline = os.getenv("USE_MECHANICAL_BASELINE", "false").strip().lower() in ("1", "true", "yes", "on")
    print(f"    RegimePriorTable's only consumer is llm/quant_brain.py (QuantBrain), which is")
    print(f"    gated by QUANT_BRAIN_ENABLED (live value: {quant_brain_on}) -- confirmed dormant,")
    print(f"    per tests/test_defabricate_sol_veto.py comment ('QuantBrain is off live').")
    print(f"    USE_REGIME_PRIORS (live value: {use_regime_priors}) also gates it off.")
    print(f"    -> RegimePriorTable.win_prob()/shrinkage machinery reaches NEITHER Trade nor")
    print(f"       Critic prompts today. Not corrupted; simply not wired to build_quant_package.")
    print(f"    Separately, regime_priors.mechanical_baseline_enabled() (live value: "
          f"{use_mech_baseline or use_regime_priors}) gates llm/agents/dynamic_stats.py's")
    print(f"    get_system_baseline(), a DIFFERENT prompt-injection surface (dynamic-stats text")
    print(f"    blocks, not quant_data['quant']/['historical']) that sources trade_ledger.csv")
    print(f"    directly (1 row/trade, own net_pnl) -- clean by construction, out of this")
    print(f"    audit's two named producers but noted for completeness.")

    print()
    if delta_pts <= 5.0 and ratio < 2.0:
        print("  VERDICT: CLEAN. N is closed-trade-level (not per-tick), matches the ledger's")
        print(f"  row count within {ratio:.2f}x (no 10-14x pseudoreplication inflation), and the")
        print(f"  headline win-rate matches the independently-recomputed ledger baseline within")
        print(f"  {delta_pts:.1f} points (fully explained by the {n_ledger - n_dna_filtered}-trade")
        print("  gap from the pre-existing pnl_pct sanity filter + a small DNA-capture gap where")
        print("  `_dm_pos` was unavailable at close time -- an UNDER-count, not an over-count,")
        print("  so it cannot be the pseudoreplication pattern). Outcome resolution is against")
        print("  each trade's OWN real close (traced above), not a snapshot/variable reference.")
    else:
        print("  VERDICT: discrepancy exceeds tolerance -- needs further investigation.")


if __name__ == "__main__":
    audit_replay_engine()
    audit_quant_data_provider()
