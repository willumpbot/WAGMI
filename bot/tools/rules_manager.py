"""Rules manager: an Opus overseer that proposes falsifiable slice rules and
is graded on what happens AFTER each rule is written.

Why this shape (data/manager_audit/FINDINGS.md, 2026-10-07): per-trade LLM
opinions (critic/quant vetoes) showed no skill, while the old Overseer's
recurring slice-level "avoid X" themes were 8/11 right -- but 63% of its output
was too vague to grade and 0/410 recommendations were ever consumed. So this
manager may ONLY emit rules over a fixed slice grammar, every rule is scored
forward-only, and nothing acts on a rule until it has earned it.

Slice grammar (all optional, AND-ed):
  symbol  BTC|ETH|SOL|HYPE|XRP|NEAR
  side    LONG|SHORT
  agree   1|2|3+          number of strategies agreeing on the signal
  regime  any regime label (trades: ledger regime_1h/regime_4h; signals: the
          signal's own regime -- the two vocabularies overlap but differ)
Actions: avoid | favor

Forward scoring, per rule, only on data timestamped after rule["created"]:
  signals  live graded rounds (data/agent_grades/live/resolved.jsonl): mean
           edge of taking the signal inside the slice vs outside it
  trades   real closed trades (data/trade_ledger.csv): mean net P&L in vs out
An "avoid" rule is right when its slice does WORSE than the rest; "favor" when
better. Status: shadow -> earned (signals: n>=30 in-slice and the bootstrap
interval excludes 0 in the rule's direction, or trades: n>=13 in-slice with the
right sign and in-slice total on the right side of 0) -> retired (wrong with
the same evidence bar, or the manager withdraws it).

Usage:
  python tools/rules_manager.py            # score rules, ask Opus for new ones
  python tools/rules_manager.py --score    # score only (no LLM call)
Writes only under data/managers/. Never changes trading behaviour.
"""
import collections
import csv
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT))
DATA = BOT / "data"
OUT = DATA / "managers"
RULES = OUT / "rules.json"
RUNS = OUT / "runs.jsonl"
LEDGER = DATA / "trade_ledger.csv"
LIVE_RESOLVED = DATA / "agent_grades" / "live" / "resolved.jsonl"
HIST_GRADED = DATA / "agent_grades" / "graded_decisions.jsonl"

SYMS = ["BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR"]
FEE = 9.0
MAX_ACTIVE = 12
MAX_NEW_PER_RUN = 4


def _now():
    return time.time()


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="minutes")


def _load_rules():
    try:
        return json.loads(RULES.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_rules(rules):
    tmp = RULES.with_suffix(".tmp")
    tmp.write_text(json.dumps(rules, indent=1), encoding="utf-8")
    os.replace(tmp, RULES)


# ── evidence rows ─────────────────────────────────────────────────────

def _agree_bucket(v):
    try:
        n = int(float(v))
    except Exception:
        return None
    return "3+" if n >= 3 else str(n)


def trades():
    """Closed trades: dicts with ts, symbol, side, agree, regimes, pnl."""
    out = []
    with open(LEDGER, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                out.append({
                    "ts": float(r["timestamp"]), "symbol": r["symbol"], "side": r["side"],
                    "agree": _agree_bucket(r.get("agreement_level")),
                    "regimes": {x for x in (r.get("regime_1h"), r.get("regime_4h")) if x},
                    "pnl": float(r["net_pnl"] or 0), "exit": r.get("exit_type"),
                })
            except Exception:
                continue
    return out


def signals(path, since=0.0):
    """Graded signal rounds: ts, symbol, side, agree, regimes, e (bps, net)."""
    out, seen = [], set()
    try:
        f = open(path, encoding="utf-8")
    except FileNotFoundError:
        return out
    with f:
        for ln in f:
            try:
                r = json.loads(ln)
            except Exception:
                continue
            if r.get("kind") != "pipeline" or not r.get("prop_side") or r.get("r4h") is None:
                continue
            if r["ts"] < since:
                continue
            key = (r["sym"], r["prop_side"], int(r["ts"] // 3600))
            if key in seen:
                continue
            seen.add(key)
            sgn = 1 if r["prop_side"] in ("LONG", "BUY") else -1
            out.append({"ts": r["ts"], "symbol": r["sym"], "side": "LONG" if sgn > 0 else "SHORT",
                        "agree": _agree_bucket(r.get("sig_agree")),
                        "regimes": {x for x in (r.get("sig_regime"),) if x},
                        "feat": r.get("feat") or {},
                        "e": sgn * r["r4h"] - FEE})
    return out


def matches(rule, row):
    s = rule["slice"]
    if s.get("symbol") and row["symbol"] != s["symbol"]:
        return False
    if s.get("side") and row["side"] != s["side"]:
        return False
    if s.get("agree") and row["agree"] != s["agree"]:
        return False
    if s.get("regime") and s["regime"] not in row["regimes"]:
        return False
    feat = row.get("feat") or {}
    for k in FEAT_KEYS:
        if s.get(k) and feat.get(k) != s[k]:
            return False   # rows without the feature (e.g. ledger trades) never match
    return True


# ── scoring ───────────────────────────────────────────────────────────

def _boot_ci(a, b, n=1000):
    rnd = random.Random(11)
    ds = sorted(sum(rnd.choice(a) for _ in a) / len(a) - sum(rnd.choice(b) for _ in b) / len(b)
                for _ in range(n))
    return [round(ds[int(0.025 * n)], 2), round(ds[int(0.975 * n)], 2)]


def _compare(rows, rule, key):
    inn = [r[key] for r in rows if matches(rule, r)]
    out = [r[key] for r in rows if not matches(rule, r)]
    res = {"n_in": len(inn), "n_out": len(out)}
    if inn:
        res["mean_in"] = round(sum(inn) / len(inn), 2)
        res["total_in"] = round(sum(inn), 2)
    if out:
        res["mean_out"] = round(sum(out) / len(out), 2)
    if len(inn) >= 2 and len(out) >= 2:
        res["diff"] = round(res["mean_in"] - res["mean_out"], 2)
        res["ci95"] = _boot_ci(inn, out)
    return res


def score(rules, tr, sg):
    for rule in rules:
        if rule["status"] == "retired":
            continue
        t0 = rule["created"]
        want = -1 if rule["action"] == "avoid" else 1
        fs = _compare([r for r in sg if r["ts"] > t0], rule, "e")
        ft = _compare([r for r in tr if r["ts"] > t0], rule, "pnl")
        rule["forward"] = {"signals_bps": fs, "trades_usd": ft, "scored_at": _iso(_now())}
        right = wrong = False
        if fs.get("n_in", 0) >= 30 and "ci95" in fs:
            lo, hi = fs["ci95"]
            right |= (lo > 0) if want > 0 else (hi < 0)
            wrong |= (hi < 0) if want > 0 else (lo > 0)
        if ft.get("n_in", 0) >= 13 and "diff" in ft:
            right |= ft["diff"] * want > 0 and ft["total_in"] * want > 0
            wrong |= ft["diff"] * want < 0 and ft["total_in"] * want < 0
        if right and not wrong:
            rule["status"] = "earned"
        elif wrong and not right:
            rule["status"] = "retired"
            rule["retired_reason"] = "forward evidence went the other way"
        elif rule["status"] == "earned" and not right:
            rule["status"] = "shadow"   # earned status must keep being re-earned
    return rules


# ── evidence brief for the manager ────────────────────────────────────

def _slice_table(rows, key, since=0.0):
    agg = collections.defaultdict(list)
    for r in rows:
        if r["ts"] < since:
            continue
        regs = r["regimes"] or {"(none)"}
        for reg in regs:
            agg[("side=" + r["side"], "regime=" + reg)].append(r[key])
        agg[("symbol=" + r["symbol"], "side=" + r["side"])].append(r[key])
        if r["agree"]:
            agg[("agree=" + r["agree"], "side=" + r["side"])].append(r[key])
    lines = []
    for k, v in sorted(agg.items(), key=lambda kv: sum(kv[1])):
        if len(v) < 5:
            continue
        wins = sum(x > 0 for x in v)
        lines.append(f"{' & '.join(k):45s} n={len(v):4d} win={wins / len(v):.0%} "
                     f"mean={sum(v) / len(v):+.2f} total={sum(v):+.1f}")
    return lines


def _waves_lines():
    try:
        d = json.loads((DATA / "data_waves" / "data_waves.json").read_text(encoding="utf-8"))
    except Exception:
        return ["(unavailable)"]
    lines = []
    for dim in d.get("slice_dimensions", []):
        for b, st in (dim.get("bucket_stats") or {}).items():
            if not isinstance(st, dict) or st.get("n", 0) < 30:
                continue
            lines.append(f"{dim['name'][:34]:34s} {b[:34]:34s} n={st.get('n'):4d} mean={st.get('mean_bps', 0):+.1f}bps"
                         f" (all-signal baseline -14.6)")
    return lines or ["(none)"]


def brief(rules, tr, sg_hist, sg_live):
    now = _now()
    active = [r for r in rules if r["status"] != "retired"]
    retired = [r for r in rules if r["status"] == "retired"][-8:]
    act_lines = [json.dumps({k: r.get(k) for k in ("id", "action", "slice", "status", "forward", "created_iso")})
                 for r in active]
    ret_lines = [json.dumps({k: r.get(k) for k in ("id", "action", "slice", "retired_reason", "thesis")})
                 for r in retired]
    parts = [
        f"NOW {_iso(now)}. Paper account; 291 closed trades since May. Net trade P&L "
        f"${sum(t['pnl'] for t in tr):+.0f}; {sum(t['pnl'] < 0 for t in tr) / max(len(tr), 1):.0%} of trades lose.",
        "",
        "## A. Real closed trades by slice (net $ per trade). ALL TIME:",
        *_slice_table(tr, "pnl"),
        "",
        "## B. Real closed trades by slice, LAST 45 DAYS:",
        *_slice_table(tr, "pnl", since=now - 45 * 86400),
        "",
        "## C. Every signal the bot evaluated, forward-graded (edge of TAKING it, bps per 4h, net of 9bps fees;"
        " one row per symbol/side/hour). May 30 - Oct 5:",
        *_slice_table(sg_hist, "e"),
        "",
        "## D. Same grading, live since the 2026-10-07 model upgrade:",
        *(_slice_table(sg_live, "e") or ["(too few rows yet)"]),
        "",
        "## G. EXPLORATORY context slices (2026-10-08 data-waves study, May-Oct signals, ~36 tests run, so ~2 would"
        " pass |t|>2 by chance; treat as hypotheses only):",
        *_waves_lines(),
        "",
        "## E. Your active rules and their FORWARD scores (only data after each rule was written):",
        *(act_lines or ["(none yet)"]),
        "",
        "## F. Recently retired rules (learn from these):",
        *(ret_lines or ["(none)"]),
    ]
    return "\n".join(parts)


SYSTEM = """You are the Rules Manager for a crypto perpetuals trading bot (Hyperliquid; BTC ETH SOL HYPE XRP NEAR).
Your ONLY output is falsifiable slice rules that will be graded on data that does not exist yet.

Facts established by audit (do not re-litigate):
- No LLM agent predicts direction; taking every signal loses ~14bps per 4h after fees.
- Value has come from AVOIDING bad slices and from exits, not from picking direction.
- Rules that fit the past can still fail going forward; each rule is scored only on future data.
- Past mistakes by a previous overseer: it said "block ETH/SOL shorts" (forgone +$499, the best edge) and
  "focus on HYPE longs" (lost $459), then reversed within days. Do not chase the last few trades.

Rule grammar - a slice is any combination of:
  symbol: BTC|ETH|SOL|HYPE|XRP|NEAR   side: LONG|SHORT   agree: "1"|"2"|"3+"   regime: a regime label seen in the evidence
  Decision-time context (signal-level only; real-trade rows don't carry it, so these rules are graded on signals):
  book: supports|balanced|against   (L2 order-book imbalance within 1% of mid, relative to the signal's side)
  funding: side_pays|neutral|side_paid   (does the signal's side pay funding right now)
  session: asia (00-08 UTC)|eu (08-13)|us (13-20)|late (20-24)
  btc4h: with|flat|against   (BTC's last-4h move relative to the signal's side, +/-0.5%)
action: "avoid" (slice will do worse than the rest) or "favor" (better than the rest).

Guidance:
- Prefer slices with enough traffic to be graded within weeks (check n in the tables, especially section C/D).
- Require agreement between independent evidence (trades AND signals) before proposing; say which sections support it.
- Do not duplicate an active rule. You may withdraw an active rule if the evidence now contradicts it.
- Propose at most 4 new rules. Zero is a valid answer.

Output ONLY a JSON object:
{"new_rules":[{"action":"avoid|favor","slice":{...},"thesis":"<=200 chars, the mechanism","evidence":"which sections, which numbers","expected_n_per_week":<int>}],
 "withdraw":[{"id":"<rule id>","reason":"<=120 chars"}],
 "note":"<=400 chars, what you noticed overall"}"""


def ask_manager(text):
    from llm.claude_cli_client import call_agent
    resp = call_agent(user_prompt=text, system_prompt=SYSTEM, model="opus",
                      max_budget_usd=float(os.getenv("CLI_MAX_BUDGET_USD", "5.00")),
                      timeout=600, allow_tools=False)
    if not resp.ok:
        raise RuntimeError(f"manager call failed: {resp.error}")
    raw = getattr(resp, "text", None) or getattr(resp, "content", "")
    raw = raw.strip()
    i, j = raw.find("{"), raw.rfind("}")
    return json.loads(raw[i:j + 1])


FEAT_KEYS = ("book", "funding", "session", "btc4h")
VALID = {"symbol": set(SYMS), "side": {"LONG", "SHORT"}, "agree": {"1", "2", "3+"},
         "book": {"supports", "balanced", "against"}, "funding": {"side_pays", "neutral", "side_paid"},
         "session": {"asia", "eu", "us", "late"}, "btc4h": {"with", "flat", "against"}}


def _clean_slice(s):
    out = {}
    for k, v in (s or {}).items():
        if k not in ("symbol", "side", "agree", "regime") + FEAT_KEYS or v in (None, ""):
            continue
        v = str(v)
        if k in VALID and v not in VALID[k]:
            return None
        out[k] = v
    return out or None


def apply_proposal(rules, prop):
    now = _now()
    active = [r for r in rules if r["status"] != "retired"]
    for w in prop.get("withdraw") or []:
        for r in active:
            if r["id"] == w.get("id"):
                r["status"] = "retired"
                r["retired_reason"] = "withdrawn by manager: " + str(w.get("reason", ""))[:120]
    taken = {json.dumps((r["action"], r["slice"]), sort_keys=True) for r in active if r["status"] != "retired"}
    added = []
    for nr in (prop.get("new_rules") or [])[:MAX_NEW_PER_RUN]:
        sl = _clean_slice(nr.get("slice"))
        act = nr.get("action")
        if not sl or act not in ("avoid", "favor"):
            continue
        k = json.dumps((act, sl), sort_keys=True)
        if k in taken:
            continue
        if sum(r["status"] != "retired" for r in rules) >= MAX_ACTIVE:
            break
        rule = {"id": f"R{len(rules) + 1:03d}", "action": act, "slice": sl, "status": "shadow",
                "created": now, "created_iso": _iso(now),
                "thesis": str(nr.get("thesis", ""))[:200], "evidence": str(nr.get("evidence", ""))[:300],
                "expected_n_per_week": nr.get("expected_n_per_week")}
        rules.append(rule)
        taken.add(k)
        added.append(rule["id"])
    return added


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rules = _load_rules()
    tr = trades()
    sg_live = signals(LIVE_RESOLVED)
    rules = score(rules, tr, sg_live)
    run = {"ts": _iso(_now()), "scored": len(rules)}
    if "--score" not in sys.argv:
        sg_hist = signals(HIST_GRADED)
        text = brief(rules, tr, sg_hist, sg_live)
        (OUT / "last_brief.txt").write_text(text, encoding="utf-8")
        try:
            prop = ask_manager(text)
            run["added"] = apply_proposal(rules, prop)
            run["withdrawn"] = [w.get("id") for w in prop.get("withdraw") or []]
            run["note"] = str(prop.get("note", ""))[:700]
        except Exception as e:
            run["error"] = str(e)[:300]
    _save_rules(rules)
    with open(RUNS, "a", encoding="utf-8") as f:
        f.write(json.dumps(run) + "\n")
    print(json.dumps(run, indent=1))


if __name__ == "__main__":
    main()
