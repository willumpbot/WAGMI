"""Seed the knowledge registry (bot/knowledge/) from the hand-kept docs - HIVEMIND Phase 0.

Sources (read-only):
  data/laptop_mining/KNOWLEDGE_MAP.md            section 3 ledger tables -> claims/<id>.json; section 4 -> threads.json
  data/laptop_mining/SERVER_AUDIT_RULES_2026-10-13.md   the 17 live rules -> rules/<id>.json
  the code itself                                definitions/<name>.json with a sha256 of each implementation

Every seeded card starts verified_by: "none" - nothing here is a laptop signature. Status comes from the map's Verdict
column through VERDICT_RULES below (first match wins); a few rows get an OVERRIDE (stable id, metric, era window...).
Rows carrying a warning sign in the map are marked needs_source: true.

After seeding, hand edits go into the cards, never into KNOWLEDGE_MAP.md (render_map.py regenerates that table).

Usage:  python tools/knowledge/seed_from_map.py [--map PATH] [--rules PATH] [--data-dir PATH] [--out bot/knowledge]
        --data-dir is only READ (stream field baselines, ledger dates); point it at the live checkout's bot/data.
"""
import argparse
import csv
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from common import BOT, KNOWLEDGE, DATA  # noqa: E402

WARN = "⚠"   # the map's "unverified or sources disagree" sign

# ---------------------------------------------------------------------------------------------------------------
# Verdict text -> status. Order matters (first match wins). The qualifier is whatever follows the keyword.
# ---------------------------------------------------------------------------------------------------------------
VERDICT_RULES = [
    (r"^RETRACTED", "RETRACTED"),
    (r"^REFUTED", "REFUTED"),
    (r"^Null as a trade", "REFUTED"),
    (r"^PROVEN", "PROVEN"),
    (r"^UNDERPOWERED|can't detect", "UNDERPOWERED"),
    (r"^NO FINDING", "UNDERPOWERED"),     # effect sat inside the no-edge spread (laptop red-team item 2)
    (r"^KEEP", "SUPPORTED"),
    (r"^FIXED", "SUPPORTED"),
    (r"prereg sealed", "PREREG_SEALED"),
    (r"^OPEN|^UNTESTED", "HYPOTHESIS"),
]

SECTION_KIND = {"Entries / direction": "direction", "Exits / stops": "exit", "Sizing / volatility": "magnitude",
                "Scanner flags": "magnitude", "Meme calls (Syndicate / DTN)": "direction"}

# Stable ids + extra structure for rows other tools refer to. Keyed by the row's first cell (exact text).
OVERRIDES = {
    "Any LLM agent predicts price?": {"id": "llm_agent_predicts_price"},
    "LLM confidence runs backwards?": {"id": "llm_confidence_backwards"},
    "Higher confidence floor helps?": {"id": "higher_conf_floor_helps"},
    "Keep the IC gate?": {"id": "ic_gate_keep", "kind": "process", "metric": "signed_return_of_dropped_signals"},
    "Long-side drain": {
        "id": "long_side_drain", "status": "STALE",
        "era_window": {"start": "2026-06-01", "end": "2026-07-31",
                       "why": "71% of the drain is June; the mechanism was deleted from position_manager.py; the last "
                              "15 longs are flat (laptop red-team 5e50f89d, answer 4: exclude Jun/Jul)."},
        "status_note": "Seeded STALE, not PROVEN: its era window has closed, so it may not bind a live rule "
                       "(laptop amendment 3: expiry by default, renewal by evidence)."},
    "Tailwind gate": {"id": "tailwind_gate"},
    "Voice agreement as direction": {"id": "voice_agreement_direction"},
    "Chief direction skill": {"id": "chief_direction_skill", "metric": "brier_p_up_24h", "horizon": "24h"},
    "Tighten the stop?": {"id": "tighten_stop_harmful", "kind": "exit"},
    "Exit-engine tightening (E2/E2b)": {
        "id": "exit_engine_tightening_e2",
        "status_note": "NO FINDING: both effects sat inside the no-edge spread (seeded as UNDERPOWERED).",
        "evidence": {"effect": 0.41, "effect_unit": "R", "no_edge_median": 0.18,
                     "note": "E2 +0.41R vs no-edge median +0.18R; E2b +0.76% vs +0.17% (laptop red-team 5e50f89d)"}},
    "Breakeven ratchet": {"id": "breakeven_ratchet"},
    "'Exit agent is the leak'": {"id": "exit_agent_is_the_leak"},
    "\"Exit agent is the leak\"": {"id": "exit_agent_is_the_leak"},
    "Trailing exit": {"id": "trailing_exit"},
    "2x stop / 0.5R / 48h": {"id": "two_x_stop_recipe"},
    "Widen the bot's stop (real trades)": {"id": "widen_bot_stop", "evidence": {"effect": 0.19, "effect_unit": "R",
                                                                               "mde": 0.81}},
    "Bot's actual stop width": {"id": "bot_stop_width", "quantity": "exp_move"},
    "Move size forecastable (HAR)?": {"id": "har_move_forecastable", "quantity": "exp_move",
                                      "metric": "abs_move_corr_vs_naive", "horizon": "1d",
                                      "live_bot_terms": ["volforecast", "next_day_move_pct", "_adaptive_stop"],
                                      "live_bot_flags": ["ADAPTIVE_STOPS"]},
    "funding_hot → bigger day": {"id": "funding_hot_bigger_day", "quantity": "funding_hot",
                                      "metric": "abs_move_over_exp_move", "horizon": "1d",
                                      "live_bot_terms": ["funding_hot"]},
    "funding_hot → more stop hits": {"id": "funding_hot_stop_hits", "quantity": "funding_hot",
                                          "metric": "stop_hit_rate", "horizon": "1d",
                                          "live_bot_terms": ["funding_hot"]},
    "volume_surge as size signal": {"id": "volume_surge_size"},
    "vol_expanding": {"id": "vol_expanding_size"},
    "Liquidation clustering (H3)": {"id": "h3_liq_clustering"},
    "Liquidation clusters as magnets": {"id": "liq_clusters_magnets", "kind": "direction"},
    "50d pullback as a trade": {"id": "ma50_pullback_trade"},
    "Counter-trend entries lose more?": {"id": "counter_trend_entries"},
    "ma50_pullback": {"id": "scanflag_ma50_pullback", "kind": "direction"},
    "momentum_small": {"id": "momentum_small_fade", "kind": "direction", "quantity": "smallcap_breakout",
                       "metric": "excess_return_vs_nonbreakout_smallcap_peers", "horizon": "72h",
                       "verdict": {"prereg_doc": "origin/laptop-mining-2026-10:bot/data/laptop_mining/"
                                                 "PREREG_SMALLCAP_FADE_2026-10-11.md",
                                   "read_not_before": "150 events across >=30 days"}},
    "Buy every call, any target": {"id": "meme_buy_every_call"},
    "Pick winners at call time": {"id": "meme_pick_winners"},
    "Moonbag vs sell-all": {"id": "meme_moonbag"},
    "Star callers (DUBI 17/18 @1.5x)": {"id": "meme_star_callers"},
}

# Claims the brief's day-1 list needs but the map has no row for. Kept tiny and labelled with where they came from.
EXTRA_CLAIMS = [
    {"id": "voice_agreement_size", "section": "Sizing / volatility", "kind": "magnitude",
     "question": "Voice disagreement -> bigger moves (size gauge)?",
     "statement_plain": "When many voices dissent, the next day's move is bigger (~5% vs ~3%).",
     "status": "HYPOTHESIS",
     "verdict_text": "OPEN - 'its link to bigger moves is small and unproven' (terminal tooltip); no laptop test row",
     "key_number": "~5% vs ~3% (chief prompt, unsourced)", "sources": ["[S:terminal.html consensus tooltip]"],
     "changed": "Chief prompt states it as fact", "seeded_from": "brief section 2 (day-1 D1 instance: chief prompt)"},
]


def parse_tables(md_text, section_title):
    """{subsection: [row dict]} for every markdown table under '## <section_title>' (stops at the next '## ')."""
    out, sub, header, inside = {}, None, None, False
    for raw in md_text.splitlines():
        ln = raw.rstrip()
        if ln.startswith("## "):
            inside = ln[3:].strip().startswith(section_title)
            continue
        if not inside:
            continue
        if ln.startswith("### "):
            sub, header = ln[4:].strip(), None
            out.setdefault(sub, [])
            continue
        if not ln.startswith("|"):
            header = None if not ln.strip() else header
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
            continue
        if header is None:
            header = cells
            continue
        row = dict(zip(header, cells + [""] * (len(header) - len(cells))))
        row["_raw"] = ln
        out.setdefault(sub or section_title, []).append(row)
    return out


def map_status(verdict):
    for pat, status in VERDICT_RULES:
        m = re.search(pat, verdict, flags=re.I)
        if m:
            qual = verdict[m.end():].strip(" ,;:/()") if m.start() == 0 else ""
            return status, qual or None, True
    return "HYPOTHESIS", "unmapped verdict: " + verdict[:80], False


def claim_from_row(section, row, today):
    q = row.get("Question") or row.get("Flag") or ""
    verdict = row.get("Verdict", "")
    ov = OVERRIDES.get(q, {})
    status, qual, mapped = map_status(verdict)
    status = ov.get("status", status)
    sources = re.findall(r"\[[^\]]+\]", row.get("Source", ""))
    key = row.get("Key number", "")
    n = None
    m = re.search(r"\bn\s*=\s*([\d,]+)", key + " " + verdict)
    if m:
        n = int(m.group(1).replace(",", ""))
    ev = {"source": sources[0] if sources else None, "sources": sources, "doc_sha": None, "key_number": key or None,
          "n": n, "clustering_unit": None, "mde": None, "effect": None, "effect_unit": None, "ci": None,
          "era_window": ov.get("era_window"), "data_through": None, "impl_hash": None,
          # laptop red-team item 2: the placebo is a NUMBER (no-edge spread on the claim's own metric), not a bool
          "no_edge_median": None, "no_edge_ci": None}
    ev.update(ov.get("evidence", {}))
    card = {
        "id": ov.get("id") or common.slug(q),
        "statement_plain": q,
        "question": q,
        "section": section,
        "kind": ov.get("kind") or SECTION_KIND.get(section, "process"),
        "quantity": ov.get("quantity"),
        "metric": ov.get("metric"),
        "horizon": ov.get("horizon"),
        "status": status,
        "status_qualifier": qual,
        "verdict_text": verdict,
        "wording_tier": common.tier_for(status),
        "revalidate": None,
        "consumers": [],
        "live_bot_terms": ov.get("live_bot_terms", []),   # D6: names a live consumer would have to mention
        "live_bot_flags": ov.get("live_bot_flags", []),   # D6: env flags that gate that consumer
        "supersedes": None,
        "needs_source": (WARN in row.get("_raw", "")) or not sources,
        "needs_review": not mapped,
        "evidence": ev,
        "verdict": {"by": None, "at": None, "prereg_sha": None, "reviewers": [], **ov.get("verdict", {})},
        "amendments": [],     # laptop answer 1: [{date, text, before_any_read: bool}]
        "idea_source": None,
        "changed": row.get("Changed") or None,
        "verified_by": "none",
        "seeded_from": f"KNOWLEDGE_MAP.md section 3 / {section}",
        "seeded_at": today,
    }
    if ov.get("status_note"):
        card["status_note"] = ov["status_note"]
    return card


def extra_claim(spec, today):
    c = claim_from_row(spec["section"], {"Question": spec["question"], "Verdict": spec["verdict_text"],
                                         "Key number": spec["key_number"], "Source": " ".join(spec["sources"]),
                                         "Changed": spec["changed"], "_raw": ""}, today)
    c.update({"id": spec["id"], "kind": spec["kind"], "statement_plain": spec["statement_plain"],
              "status": spec["status"], "wording_tier": common.tier_for(spec["status"]),
              "status_qualifier": None, "needs_review": False, "seeded_from": spec["seeded_from"]})
    return c


# ---------------------------------------------------------------------------------------------------------------
# Definitions: the quantities several places compute. Each implementation gets an impl_hash of its exact code.
# ---------------------------------------------------------------------------------------------------------------
LAPTOP_SMALLCAP_DEF = ("Universe: HL perps outside the top 15 by trailing 20-day dollar volume at that hour (prior bars "
                       "only), >=25 eligible coins. Signal: close / max(close over the prior 480h) - 1 >= 0.04, "
                       "strictly above. Benchmark: same-hour eligible coins NOT above their 20-day high.")

DEFINITIONS = [
    {"name": "exp_move", "kind": "quantity",
     "plain": "Expected size of tomorrow's move, in % (absolute, no direction).",
     "canonical": "volforecast.forecast",
     "implementations": [
         {"label": "volforecast.forecast", "path": "tools/hivemind/volforecast.py", "function": "forecast",
          "output": "next_day_move_pct", "note": "HAR + stage-2 error model; production (laptop answer 2). "
                                                 "Consumers: scanner.scan_coin, stop_shadow._exp_move, assemble vol."},
         {"label": "risk_voice.risk_read (via assemble.voice_risk)", "path": "data/laptop_mining/risk_voice.py",
          "function": "risk_read", "output": "expected_move_1d_pct",
          "note": "Own HAR recompute (no stage-2); surfaced by tools/hivemind/assemble.py voice_risk (~:326)."},
         {"label": "chief expected_move_pct", "path": "tools/hivemind/chief.py",
          "pattern": r"ALSO REQUIRED on every coin: \"expected_move_pct\"", "output": "expected_move_pct",
          "note": "The Opus chief's own number (an LLM forecast, not code)."},
     ],
     "cross_check": {"tolerance_same_function": 0.0, "alarm_rel_diff": 0.10,
                     "sources": ["state.vol.next_day_move_pct", "scan.exp_move", "chief.expected_move_pct"]},
     "invariants": [{"expr": "g('x') is None or g('x') >= 0", "why": "a move size is never negative"}]},
    {"name": "funding_hot", "kind": "flag",
     "plain": "Coin's funding is strictly above the interpolated 80th percentile of the scanned coins' funding.",
     "canonical": "scanner.run funding_hot block",
     "implementations": [
         {"label": "scanner.run funding_hot block", "path": "tools/hivemind/scanner.py",
          "start": r"fs = sorted\(r\[\"funding_h\"\]", "end": r"r\[\"flags\"\]\.append\(\"funding_hot\"\)",
          "note": "Strictly ABOVE the cut (HL default-funding ties; '>=' flagged ~85% of coins). Tested by laptop "
                  "SIZE_FLAGS / FUNDING_STOP_AUDIT with exactly this definition (definition-sensitive)."},
         {"label": "scanner.FLAGS text", "path": "tools/hivemind/scanner.py",
          "start": r"\"funding_hot\": \(\"Longs paying a lot\"", "end": r"Size down a little",
          "role": "display"},
     ],
     "tested_impl_hash": None,
     "invariants": [{"expr": "g('share_flagged') <= 0.25", "why": "top quintile: ~20% of scanned coins at most"}]},
    {"name": "smallcap_breakout", "kind": "flag",
     "plain": "A small cap trading above its 20-day high.",
     "canonical": "laptop prereg (PREREG_SMALLCAP_FADE)",
     "implementations": [
         {"label": "scanner momentum_small flag", "path": "tools/hivemind/scanner.py",
          "start": r"big15 = \{r\[\"coin\"\]", "end": r"r\[\"flags\"\]\.append\(\"momentum_small\"\)",
          "note": "Ranks 16-60 of the top-60 by 24h volume, px > hi20 AND (vol_ratio > 2 OR up-day > 1.5x exp_move)."},
         {"label": "terminal.html planner warning", "path": "tools/hivemind/terminal.html",
          "pattern": r"side===\"LONG\" && \(sr\.vol_rank\|\|0\) > 15 && sr\.hi20 && sr\.px > sr\.hi20",
          "note": "vol_rank > 15 and px > hi20 only (no volume/up-day condition), LONG side."},
         {"label": "laptop prereg (PREREG_SMALLCAP_FADE)", "doc":
             "origin/laptop-mining-2026-10:bot/data/laptop_mining/PREREG_SMALLCAP_FADE_2026-10-11.md",
          "doc_commit": "7f98169e0806223ebc80a2b4a902ac8fb317b2f8", "text": LAPTOP_SMALLCAP_DEF,
          "note": "Outside top 15 by TRAILING 20d $ volume; >= 4% above the prior 480h max close."},
     ]},
    {"name": "R", "kind": "quantity",
     "plain": "Whole-trade R multiple: net pnl / (|entry - initial stop| x original qty x pnl leverage).",
     "canonical": "feedback.trade_ledger.compute_realized_rr",
     "implementations": [
         {"label": "feedback.trade_ledger.compute_realized_rr", "path": "feedback/trade_ledger.py",
          "function": "compute_realized_rr"},
         {"label": "feedback.trade_ledger.rr_pnl_leverage", "path": "feedback/trade_ledger.py",
          "function": "rr_pnl_leverage", "role": "helper",
          "note": "Must mirror PositionManager._pnl_lev (PNL_LEVERAGE_FIX)."},
     ],
     "invariants": [{"expr": "g('realized_rr') is None or abs(g('realized_rr')) < 50",
                     "why": "|R| beyond 50 means a broken denominator (the old leverage double-count)"}],
     "notes": "Laptop answer 3: R is NOT scale-free when the treatment touches the stop; gates use bps of notional."},
    {"name": "notional", "kind": "quantity",
     "plain": "Position size in USD.",
     "canonical": None,
     "implementations": [
         {"label": "PositionManager.get_total_open_notional", "path": "execution/position_manager.py",
          "function": "PositionManager.get_total_open_notional", "note": "qty * entry * leverage"},
         {"label": "LLM-first notional cap", "path": "multi_strategy_main.py",
          "pattern": r"_notional = qty \* raw_signal\.entry \* leverage", "note": "qty * entry * leverage"},
         {"label": "coordinator sizing (base exposure)", "path": "llm/agents/coordinator.py",
          "pattern": r"_remaining_pct = max\(0\.0, 500\.0 - _exposure_pct\)",
          "note": "Coordinator sizes qty as FULL base exposure ('do NOT multiply by leverage'), so qty*entry is "
                  "already the notional; the caps above multiply by leverage again (audit rule 9 unit mismatch)."},
     ]},
]

# Un-backfillable streams (D9 freshness, D10 payload completeness, D11 semantic invariants).
STREAM_DEFS = [
    {"name": "stream_liq_events", "path": "copilot/liquidations/liq_events.jsonl", "archive": "liq_events",
     "plain": "Bybit liquidation events (H3's substrate).",
     "invariants": [
         {"expr": "abs(g('notional_usd') - g('price') * g('qty_base')) <= 0.01 * g('notional_usd') + 0.01",
          "why": "notional = price x qty"},
         {"expr": "g('side') in ('long', 'short')", "why": "side label"}]},
    {"name": "stream_market_depth", "path": "market_depth_history.jsonl", "archive": "market_depth",
     "plain": "L2 depth / trade flow / OKX futures context, 6 coins.",
     "invariants": [
         {"expr": "-1 <= g('l2.imbalance_1pct') <= 1", "why": "imbalance is a share difference"},
         {"expr": "0 <= g('trades.buy_ratio') <= 1", "why": "a ratio of volumes"},
         {"expr": "g('l2.bid_depth_1pct') >= g('l2.bid_depth_0_5pct') >= g('l2.bid_depth_0_1pct')",
          "why": "depth bands are cumulative"}]},
    {"name": "stream_depth_all", "path": "hivemind/depth_all.jsonl", "archive": "depth_all",
     "plain": "L2 bands for all ~178 perps every 15 min.",
     "invariants": [
         {"expr": "-1 <= g('imb_0.5') <= 1", "why": "imbalance is a share difference"},
         {"expr": "g('spread_bps') >= 0", "why": "spread"},
         {"expr": "g('bid_usd_0.5') >= 0 and g('ask_usd_0.5') >= 0", "why": "depth is non-negative"}]},
    {"name": "stream_whales", "path": "hivemind/whales_log.jsonl", "archive": "whales", "map_keys": ["coins"],
     "plain": "Net position of ~60 profitable HL accounts per coin: coins.<SYM> = [net, gross, n_long, n_short].",
     "invariants": [
         {"expr": "all(abs(v[0]) <= v[1] for v in g('coins').values())", "why": "abs(net) <= gross (laptop D11)"},
         {"expr": "all(v[0] <= 0 for v in g('coins').values() if v[2] == 0)", "why": "no longs -> net not long"},
         {"expr": "all(v[0] >= 0 for v in g('coins').values() if v[3] == 0)", "why": "no shorts -> net not short"}]},
    {"name": "stream_voices", "path": "hivemind/voice_log.jsonl", "archive": "voices",
     "plain": "Every voice reading per coin, 15 min.",
     "invariants": [{"expr": "g('r') in (-1, 0, 1)", "why": "a voice reads -1/0/+1"}]},
]


def build_definition(spec, root):
    d = {k: v for k, v in spec.items() if k != "implementations"}
    d["id"] = spec["name"]
    impls = []
    for im in spec["implementations"]:
        im = dict(im)
        if im.get("path"):
            im["impl_hash"] = common.impl_hash(im, root)
            im["line"] = common.impl_line(im, root)
            if im["impl_hash"] is None:
                im["missing"] = True
        elif im.get("text"):
            im["impl_hash"] = hashlib.sha256(im["text"].encode("utf-8")).hexdigest()
        impls.append(im)
    d["implementations"] = impls
    d.setdefault("tested_impl_hash", None)
    d.setdefault("invariants", [])
    d["verified_by"] = "none"
    return d


def build_stream(spec, data_dir):
    d = {"id": spec["name"], "name": spec["name"], "kind": "stream", "plain": spec["plain"],
         "stream": {"path": spec["path"], "archive": spec["archive"], "max_age_days": 2,
                    "map_keys": spec.get("map_keys", [])},
         "expected_fields": [], "invariants": spec["invariants"], "verified_by": "none"}
    p = Path(data_dir) / spec["path"]
    if p.exists():
        import json as _j
        fields = set()
        for ln in common.tail_lines(p, 20):
            try:
                fields |= common.flatten_fields(_j.loads(ln), map_keys=tuple(spec.get("map_keys", [])))
            except ValueError:
                continue
        d["expected_fields"] = sorted(fields)
        d["expected_fields_note"] = ("Baseline = union of fields in the last 20 rows at seed time. D10 flags any "
                                     "field that disappears. The source API's own field set is not captured yet.")
    return d


# ---------------------------------------------------------------------------------------------------------------
# Rules (SERVER_AUDIT_RULES_2026-10-13). The audit text is parsed for each rule's raw description; the structured
# fields below are hand-entered from that audit (claim link, unit, window, flag/env names, evidence source).
# ---------------------------------------------------------------------------------------------------------------
LEDGER_LONG = {"kind": "ledger", "file": "trade_ledger.csv", "side": "LONG", "fee_floor": 0.5,
               "fee_floor_env": "LEARNING_INPUT_FLOOR"}
LEDGER_ALL = {"kind": "ledger", "file": "trade_ledger.csv", "side": None, "fee_floor": 0.5,
              "fee_floor_env": "LEARNING_INPUT_FLOOR"}

RULE_META = {
    1: {"id": "r01_ic_mute", "claim_id": "ic_gate_keep", "unit": "IC (signal vs forward return)",
        "window": "last 30 signals per strategy", "min_n": 30, "flags": [], "fires_37h": 765},
    2: {"id": "r02_solo_gate", "claim_id": None, "unit": "win-rate vs fee-adjusted breakeven ($ payoff)",
        "window": "whole ledger", "min_n": 13, "flags": ["ENTRY_SELECTIVITY"], "fires_37h": 0,
        "evidence_source": LEDGER_ALL,
        "claim_note": "Evidence n=32 (drought diagnosis 2026-09-12, memory note) has no claim card."},
    3: {"id": "r03_long_block", "claim_id": "long_side_drain", "unit": "win-rate vs breakeven ($ payoff)",
        "window": "whole ledger (LIVE_EDGE_WINDOW_DAYS=0)", "min_n": 13,
        "flags": ["LONG_REGIME_VETO", "UPTREND_REGIMES"], "fires_37h": 1, "evidence_source": LEDGER_LONG},
    4: {"id": "r04_probe_valve", "claim_id": "owner_policy", "unit": "share of blocked entries, size mult",
        "window": None, "min_n": None,
        "flags": ["BLOCKED_GO_PROBE", "BLOCKED_GO_PROBE_RATE", "BLOCKED_GO_PROBE_SIZE_MULT"], "fires_37h": 1},
    5: {"id": "r05_side_size_mult", "claim_id": "long_side_drain", "unit": "dollars (1 + avg$/20, clip 0.25-1.5)",
        "window": "whole ledger (LIVE_EDGE_WINDOW_DAYS=0)", "min_n": 13,
        "flags": ["SIDE_LEVEL_EDGE", "DATA_DRIVEN_SIDE_MULT"], "fires_37h": 1, "evidence_source": LEDGER_ALL},
    6: {"id": "r06_dust_filter", "claim_id": None, "unit": "dollars of fees (< $0.50 ignored)",
        "window": "whole ledger", "min_n": None, "flags": ["LEARNING_INPUT_FLOOR"], "fires_37h": None,
        "evidence_source": LEDGER_ALL, "claim_note": "Set 2026-07-24 when median notional was ~$278."},
    7: {"id": "r07_risk_cap_0_5pct", "claim_id": "owner_policy", "unit": "fraction of equity at risk",
        "window": None, "min_n": None, "flags": ["MAX_RISK_PCT_CEILING", "SIZING_CONSTRAINT_UNITS_FIX"],
        "fires_37h": 193,
        "enforcement_check": {
            "prompt_markers": [{"path": "llm/agents/prompts.py", "pattern": r"sizing_constraint\.max_risk_pct"}],
            "code_paths": ["llm/agents/coordinator.py", "core", "execution", "multi_strategy_main.py"],
            # a line touching the agent's risk_pct AND the coordinator's ceiling (not sizing_optimizer's own,
            # unrelated max_risk_pct = 30%)
            "clamp_pattern": r"(?<![\w.])(risk_pct|risk_frac)\b[^\n]*(sizing_constraint|MAX_RISK_PCT_CEILING|"
                             r"_ceiling_cap|_max_risk_pct)|(sizing_constraint|MAX_RISK_PCT_CEILING|_ceiling_cap|"
                             r"_max_risk_pct)[^\n]*(?<![\w.])(risk_pct|risk_frac)\b",
            "why": "The ceiling is computed into risk_data['sizing_constraint'] for the Risk Agent's prompt; a code "
                   "enforcement would clamp the agent's returned risk_pct against it."}},
    8: {"id": "r08_fallback_risk", "claim_id": None, "unit": "fraction of equity (10% x size mult)",
        "window": None, "min_n": None, "flags": [], "fires_37h": None},
    9: {"id": "r09_post_ai_caps", "claim_id": "owner_policy", "unit": "multiples of equity (leverage-unit mismatch)",
        "window": None, "min_n": None, "flags": [], "fires_37h": None},
    10: {"id": "r10_profit_lock", "claim_id": None, "unit": "R", "window": "2026-07-02 in-sample n=90",
         "min_n": None, "flags": [], "fires_37h": None,
         "conflicts_with": ["breakeven_ratchet", "tighten_stop_harmful"]},
    11: {"id": "r11_sl_fill_slip", "claim_id": None, "unit": "bps", "window": None, "min_n": None, "flags": [],
         "fires_37h": None, "exempt_reason": "paper fill model (simulation assumption, not a market belief)"},
    12: {"id": "r12_exit_keyword_thresholds", "claim_id": None, "unit": "confidence 0.60/0.80/0.90", "window": None,
         "min_n": None, "flags": [], "fires_37h": 10},
    13: {"id": "r13_min_exit_hold_2h", "claim_id": None, "unit": "hours", "window": None, "min_n": None,
         "flags": [], "fires_37h": 10},
    14: {"id": "r14_time_stop_handoff", "claim_id": None, "unit": "x max hold", "window": None, "min_n": None,
         "flags": [], "fires_37h": None},
    15: {"id": "r15_regime_stickiness", "claim_id": None, "unit": "share (>60%)", "window": None, "min_n": None,
         "flags": [], "fires_37h": 590},
    16: {"id": "r16_trigger_conf_floor", "claim_id": "higher_conf_floor_helps", "unit": "confidence (P90 ~0.38)",
         "window": None, "min_n": None, "flags": [], "fires_37h": 52},
    17: {"id": "r17_daily_loss_limit", "claim_id": "owner_policy", "unit": "dollars per symbol per day",
         "window": "UTC day", "min_n": None, "flags": [], "fires_37h": None},
}


def parse_rules(text):
    """{n: raw text} for the numbered rules in the audit (continuation lines are indented)."""
    rules, cur = {}, None
    for ln in text.splitlines():
        m = re.match(r"^(\d{1,2}) (.+)$", ln)
        if m and 1 <= int(m.group(1)) <= 30:
            cur = int(m.group(1))
            rules[cur] = m.group(2).strip()
        elif cur and ln.startswith("  ") and ln.strip():
            rules[cur] += " " + ln.strip()
        elif ln.startswith("Conflicts:"):
            cur = None
    return rules


def ledger_evidence_through(spec, data_dir, env):
    """Last ledger row the gate can still SEE (after the dust filter) and how many newer rows it ignores."""
    p = Path(data_dir) / spec["file"]
    if not p.exists():
        return None
    floor_on = str(env.get(spec.get("fee_floor_env", ""), "false")).lower() in ("1", "true", "yes")
    last_q, last_any, newer = None, None, []
    rows = []
    with open(p, newline="", encoding="utf-8", errors="ignore") as f:
        for r in csv.DictReader(f):
            sym = str(r.get("symbol") or "").upper()
            if "TEST" in sym or "SIM" in sym:
                continue
            if spec.get("side") == "LONG" and str(r.get("side") or "").upper() not in ("LONG", "BUY"):
                continue
            t = common.row_epoch(r, "timestamp")
            if t is None:
                continue
            try:
                fees = float(r.get("fees") or 0)
            except ValueError:
                fees = 0.0
            try:
                pnl = float(r.get("net_pnl") or 0)
            except ValueError:
                pnl = 0.0
            rows.append((t, fees, pnl))
    for t, fees, pnl in rows:
        q = (not floor_on) or fees >= spec["fee_floor"]
        last_any = t if last_any is None or t > last_any else last_any
        if q:
            last_q = t if last_q is None or t > last_q else last_q
    for t, fees, pnl in rows:
        if last_q is not None and t > last_q:
            newer.append(pnl)

    def iso(t):
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d") if t else None
    return {"evidence_through": iso(last_q), "newest_row": iso(last_any), "n_rows": len(rows),
            "n_ignored_newer": len(newer), "ignored_net_usd": round(sum(newer), 2), "fee_floor_on": floor_on}


# ---------------------------------------------------------------------------------------------------------------
# Bindings: claim -> display string / prompt / grader. Milestones are matched by title.
# ---------------------------------------------------------------------------------------------------------------
MILESTONE_BINDINGS = {
    "Liquidation clustering is real (BTC/SOL)": ("h3_liq_clustering", "claim"),
    "No AI agent predicts price": ("llm_agent_predicts_price", "negation"),
    "Move SIZE is forecastable": ("har_move_forecastable", "claim"),
    "The bot's hidden filter is right": ("ic_gate_keep", "claim"),
    "Crowded longs = bigger days (survived red team)": ("funding_hot_bigger_day", "claim"),
    "Crowded longs: stops hit a bit more often": ("funding_hot_stop_hits", "claim"),
    "Tailwind gate": ("tailwind_gate", "negation"),
    "2x stop / 0.5R target / 48h recipe": ("two_x_stop_recipe", "negation"),
    "50-day pullback as a trade": ("ma50_pullback_trade", "negation"),
    "Liquidation clusters as magnets": ("liq_clusters_magnets", "negation"),
    "Trailing exit beats a fixed target": ("trailing_exit", "negation"),
    "'Exit agent is the leak'": ("exit_agent_is_the_leak", "negation"),
    "Confidence floors pick better trades": ("higher_conf_floor_helps", "negation"),
    "Counter-trend entries lose more (RETRACTED)": ("counter_trend_entries", "negation"),
    "Picking Syndicate winners at call time": ("meme_pick_winners", "negation"),
    "Buying every meme call, any exit rule": ("meme_buy_every_call", "negation"),
    "Following every Syndicate call loses": ("meme_buy_every_call", "negation"),
    "Don't chase small-cap breakouts (in history; forward test running)": ("momentum_small_fade", "claim"),
    "Some Syndicate callers stand out at 1.5x": ("meme_star_callers", "claim"),
    "Syndicate moonbags: can't tell yet": ("meme_moonbag", "claim"),
    "Long-side losses were June-July": ("long_side_drain", "claim", "stale"),
}

PROMPT_BINDINGS = [
    {"id": "chief_prompt_dissent_move", "surface": "tools/hivemind/chief.py", "pattern": r"~5% vs ~3% when many dissent",
     "claim_id": "voice_agreement_size", "polarity": "claim", "asserted_tier": "proven",
     "why": "Stated to the chief as a fact, with no qualifier."},
]

GRADER_BINDINGS = [
    {"id": "scan_grader_funding_hot_day", "grader": "tools/hivemind/scan_grader.py", "flag": "funding_hot",
     "claim_id": "funding_hot_bigger_day"},
    {"id": "scan_grader_funding_hot_stop", "grader": "tools/hivemind/scan_grader.py", "flag": "funding_hot",
     "claim_id": "funding_hot_stop_hits"},
    {"id": "scan_grader_momentum_small", "grader": "tools/hivemind/scan_grader.py", "flag": "momentum_small",
     "claim_id": "momentum_small_fade"},
]

SCANNER_FLAG_CLAIMS = {"funding_hot": "funding_hot_stop_hits", "vol_expanding": "vol_expanding_size",
                       "volume_surge": "volume_surge_size", "ma50_pullback": "scanflag_ma50_pullback",
                       "momentum_small": "momentum_small_fade", "on_20d_low": "on_20d_low",
                       "squeeze": "squeeze"}


def parse_threads(md_text, today):
    rows = parse_tables(md_text, "4. Open threads")
    out = []
    for sub, rs in rows.items():
        for r in rs:
            name = r.get("Thread", "")
            t = {"id": common.slug(name), "thread": name, "reads_out": r.get("Reads out") or None,
                 "now": r.get("Now") or None, "source": r.get("Source") or None, "next_action": None,
                 "owner": None, "unblock_condition": r.get("Reads out") or None, "disagreements": [],
                 "needs_source": WARN in r.get("_raw", ""), "seeded_at": today}
            # "4 ⚠ server stats say 1"  -> two counts that disagree (D8)
            m = re.search(r"(\d+)\s*" + WARN + r"\s*(.+?)\s+says?\s+(\d+)", t["now"] or "")
            if m:
                t["disagreements"].append({"field": "n", "a": {"source": t["source"], "value": int(m.group(1))},
                                           "b": {"source": m.group(2).strip(), "value": int(m.group(3))}})
            m = re.search(r"(~?\d{4}-\d{2}(?:-\d{2})?)\s*" + WARN + r"\s*(\S+)\s+says\s+(~?\d{4}-\d{2}(?:-\d{2})?)",
                          t["reads_out"] or "")
            if m:
                t["disagreements"].append({"field": "reads_out_date", "a": {"source": t["source"],
                                                                             "value": m.group(1)},
                                           "b": {"source": m.group(2), "value": m.group(3)}})
            out.append(t)
    return out


def seed(map_path, rules_path, data_dir, out_root, code_root=None, env_path=None):
    """Write every card. Returns counts. Existing card files with the same id are overwritten (seeding is idempotent;
    once the laptop has signed cards, re-seed into a scratch dir and diff instead)."""
    code_root = Path(code_root or BOT)
    out_root = Path(out_root)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    md = Path(map_path).read_text(encoding="utf-8")
    env = common.read_env(env_path or (code_root / ".env"))

    # claims
    claims = {}
    for section, rows in parse_tables(md, "3. Knowledge ledger").items():
        for r in rows:
            if not (r.get("Question") or r.get("Flag")):
                continue
            c = claim_from_row(section, r, today)
            c["map_order"] = len(claims)          # row position in the map, so render_map.py can rebuild it
            base, k = c["id"], 2
            while c["id"] in claims:
                c["id"] = f"{base}_{k}"
                k += 1
            claims[c["id"]] = c
    for spec in EXTRA_CLAIMS:
        claims[spec["id"]] = extra_claim(spec, today)

    # definitions (code + streams)
    defs = [build_definition(s, code_root) for s in DEFINITIONS]
    defs += [build_stream(s, data_dir) for s in STREAM_DEFS]

    # rules
    raw = parse_rules(Path(rules_path).read_text(encoding="utf-8"))
    rules = []
    for n in sorted(raw):
        meta = dict(RULE_META.get(n, {"id": f"r{n:02d}", "claim_id": None}))
        card = {"id": meta.pop("id"), "n": n, "description": raw[n], **meta,
                "unit_target": "bps of notional (laptop answer 3); never dollars, never a fee floor",
                "window_target": "rolling + era cut (Jun/Jul excluded); whole-ledger forbidden",
                "shadow_twin": None, "exploration_floor": None, "staleness_alarm": "D2",
                "source": f"SERVER_AUDIT_RULES_2026-10-13 #{n}", "verified_by": "none", "seeded_at": today}
        if card.get("evidence_source"):
            card["evidence_through"] = ledger_evidence_through(card["evidence_source"], data_dir, env)
        else:
            card["evidence_through"] = None
        rules.append(card)

    # bindings
    displays = []
    for title, b in MILESTONE_BINDINGS.items():
        d = {"id": "milestone_" + common.slug(title, 40), "surface": "tools/hivemind/milestones.json",
             "locator": {"title": title}, "claim_id": b[0], "polarity": b[1]}
        if len(b) > 2:
            d["asserted_tier"] = b[2]
        displays.append(d)
    for flag, cid in SCANNER_FLAG_CLAIMS.items():
        displays.append({"id": "scanner_flag_" + flag, "surface": "tools/hivemind/scanner.py:FLAGS",
                         "locator": {"flag": flag}, "claim_id": cid if cid in claims else None, "polarity": "claim"})
    bindings = {"displays": displays, "prompts": PROMPT_BINDINGS, "graders": GRADER_BINDINGS,
                "rules": [{"rule_id": r["id"], "claim_id": r.get("claim_id")} for r in rules],
                "note": "Generated by seed_from_map.py; edit here once seeded. Every surface string should carry a "
                        "claim_id (D1 strict mode, phase 3)."}

    # consumers back-filled onto claims (generated from the bindings, never typed by hand)
    for r in rules:
        if r.get("claim_id") in claims:
            claims[r["claim_id"]]["consumers"].append("rule:" + r["id"])
    for d in displays + PROMPT_BINDINGS:
        if d.get("claim_id") in claims:
            claims[d["claim_id"]]["consumers"].append("display:" + d["id"])
    for g in GRADER_BINDINGS:
        if g["claim_id"] in claims:
            claims[g["claim_id"]]["consumers"].append("grader:" + g["id"])

    threads = {"threads": parse_threads(md, today), "seeded_from": "KNOWLEDGE_MAP.md section 4"}

    for kind in ("claims", "definitions", "rules"):
        (out_root / kind).mkdir(parents=True, exist_ok=True)
    for c in claims.values():
        common.write_json(out_root / "claims" / f"{c['id']}.json", c)
    for d in defs:
        common.write_json(out_root / "definitions" / f"{d['id']}.json", d)
    for r in rules:
        common.write_json(out_root / "rules" / f"{r['id']}.json", r)
    common.write_json(out_root / "bindings.json", bindings)
    common.write_json(out_root / "threads.json", threads)
    return {"claims": len(claims), "definitions": len(defs), "rules": len(rules),
            "threads": len(threads["threads"]),
            "needs_source": sum(c["needs_source"] for c in claims.values()),
            "needs_review": sum(c["needs_review"] for c in claims.values())}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--map", default=str(DATA / "laptop_mining" / "KNOWLEDGE_MAP.md"))
    ap.add_argument("--rules", default=str(DATA / "laptop_mining" / "SERVER_AUDIT_RULES_2026-10-13.md"))
    ap.add_argument("--data-dir", default=str(DATA), help="read-only: live bot/data for stream baselines + ledger")
    ap.add_argument("--env", default=None, help="read-only .env (default bot/.env)")
    ap.add_argument("--out", default=str(KNOWLEDGE))
    a = ap.parse_args(argv)
    counts = seed(a.map, a.rules, a.data_dir, a.out, env_path=a.env)
    print(counts)


if __name__ == "__main__":
    main()
