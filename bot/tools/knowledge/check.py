"""Automatic discrepancy checks over the knowledge registry (HIVEMIND Phase 0, brief section 2 + laptop red-team).

Each check is one small function returning (findings, not_automated). A finding is a dict:
  {"check": "D2", "id": "...", "severity": "high|warn|info", "what": "<one plain sentence>", ...detail}
Anything a check cannot verify yet is reported under not_automated - a check never passes silently.

  D1  display > grade      surface wording stronger than its claim's wording tier
  D2  stale gate           live rule whose evidence stopped moving while trades kept happening
  D3  definition drift     one quantity, several implementations (+ numeric cross-check on live outputs)
  D4  impl != tested       live code hash differs from the hash on the card / the tested hash
  D5  grader != claim      grader measures a different metric than the claim it grades
  D6  orphan               PROVEN claim with no live consumer; live rule with no (or a dead) claim; prompt-only caps
  D7  config vs card       decision-card text contradicted by .env
  D8  count disagreement   two sources disagree on a count / date
  D9  substrate death      un-backfillable stream stopped (or its off-box copy did)
  D10 payload completeness a stream lost fields it used to write
  D11 semantic invariants  a row breaks an assertion that must hold if its labels are true (abs(net) <= gross)

Read-only on everything except the one output file.
Usage: python tools/knowledge/check.py [--data-dir PATH] [--registry bot/knowledge] [--code-root bot] [--env PATH]
                                       [--out data/knowledge/discrepancies.json] [--now EPOCH]
"""
import argparse
import ast
import hashlib
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from common import BOT, KNOWLEDGE, DATA  # noqa: E402

STRONG_WORD = re.compile(r"\b(proven|confirmed)\b", re.I)
NEGATION = re.compile(r"(\bnot\b|\bnever\b|\bno\b|n't\b|\bnothing\b|\bnor\b)[^.;:]{0,40}$", re.I)
MILESTONE_KIND = {"proven": ("claim", "proven"), "refuted": ("negation", "proven"),
                  "found": ("claim", "supported"), "open": ("claim", "hypothesis")}
CHIP_TIER = {"tested": "proven", "replicated": "replicated", "supported": "supported"}          # scanner evidence chips that assert something ("context" asserts nothing)


class Ctx:
    """Everything a check needs: the registry, where code and data live, and 'now'."""

    def __init__(self, registry_root=None, code_root=None, data_dir=None, env_path=None, now=None):
        self.registry_root = Path(registry_root or KNOWLEDGE)
        self.code_root = Path(code_root or BOT)
        self.data_dir = Path(data_dir or DATA)
        self.env = common.read_env(env_path or (self.code_root / ".env"))
        self.now = float(now if now is not None else time.time())
        self.reg = common.load_registry(self.registry_root)

    def claim(self, cid):
        return self.reg["claims"].get(cid)

    def code(self, rel):
        try:
            return (self.code_root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None


def _f(check, fid, severity, what, **kw):
    return {"check": check, "id": fid, "severity": severity, "what": what, **kw}


def _na(check, what, why):
    return {"check": check, "what": what, "why": why}


def _strong_unnegated(text):
    """Sentences fragments where 'proven'/'confirmed' is used positively (not 'not proven', 'NOT confirmed')."""
    hits = []
    for m in STRONG_WORD.finditer(text or ""):
        before = text[max(0, m.start() - 60):m.start()]
        if NEGATION.search(before):
            continue
        hits.append(text[max(0, m.start() - 80):m.end() + 40].replace("\n", " "))
    return hits


def _scanner_flags(ctx):
    """scanner.FLAGS as {flag: (label, evidence, why)} by parsing the source (no import, no network)."""
    src = ctx.code("tools/hivemind/scanner.py")
    if not src:
        return None
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "FLAGS" for t in node.targets):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                return None
    return None


# ---------------------------------------------------------------------------------------------------------------
def check_d1_display_vs_grade(ctx):
    """D1: every bound display (milestone kind, scanner chip, prompt sentence) may not assert more than its claim's
    wording tier allows; unbound positive 'proven'/'confirmed' wording on a surface is reported as a warning."""
    out, na = [], []
    b = ctx.reg["bindings"]

    def compare(bid, surface, claim_id, polarity, asserted, text):
        c = ctx.claim(claim_id) if claim_id else None
        if c is None:
            out.append(_f("D1", bid, "warn", f"{surface}: asserts '{asserted}' but is bound to no claim card",
                          surface=surface, text=text))
            return
        allowed = common.negation_tier(c["status"]) if polarity == "negation" else c["wording_tier"]
        if common.TIER_RANK[asserted] > common.TIER_RANK[allowed]:
            out.append(_f("D1", bid, "high",
                          f"{surface} says '{asserted}' ({polarity}) but claim {claim_id} is {c['status']} "
                          f"(allowed: '{allowed}')", surface=surface, claim_id=claim_id, text=text))

    # milestones.json (also the source of history.json / board_feed.json)
    ms = common.load_json(ctx.code_root / "tools/hivemind/milestones.json", []) or []
    by_title = {m.get("title"): m for m in ms}
    bound_titles = set()
    for d in b.get("displays", []):
        if d.get("surface") != "tools/hivemind/milestones.json":
            continue
        title = d["locator"]["title"]
        m = by_title.get(title)
        if m is None:
            out.append(_f("D1", d["id"], "info", f"binding points at a milestone that no longer exists: {title!r}"))
            continue
        bound_titles.add(title)
        pol, tier = MILESTONE_KIND.get(m.get("kind"), (None, None))
        if tier is None:
            continue
        compare(d["id"], f"milestones.json '{title}'", d.get("claim_id"), d.get("polarity", pol),
                d.get("asserted_tier", tier), m.get("what"))
    for m in ms:
        if m.get("kind") == "proven" and m.get("title") not in bound_titles:
            out.append(_f("D1", "milestone_unbound_" + common.slug(m.get("title", ""), 40), "warn",
                          f"milestones.json '{m.get('title')}' is kind 'proven' with no claim binding",
                          text=m.get("what")))

    # scanner chips
    flags = _scanner_flags(ctx)
    if flags is None:
        na.append(_na("D1", "scanner FLAGS chips", "tools/hivemind/scanner.py FLAGS could not be parsed"))
    else:
        chip_bind = {d["locator"]["flag"]: d for d in b.get("displays", []) if "flag" in d.get("locator", {})}
        for flag, (label, evidence, why) in flags.items():
            asserted = CHIP_TIER.get(evidence)
            d = chip_bind.get(flag)
            if asserted:
                compare(d["id"] if d else "scanner_flag_" + flag, f"scanner chip '{flag}' ({evidence})",
                        d.get("claim_id") if d else None, "claim", asserted, why)
            for hit in _strong_unnegated(why):
                out.append(_f("D1", f"scanner_text_{flag}", "warn", f"scanner '{flag}' text uses strong wording",
                              text=hit))

    # prompt sentences
    for p in b.get("prompts", []):
        src = ctx.code(p["surface"])
        if src is None or not re.search(p["pattern"], src):
            out.append(_f("D1", p["id"], "info", f"prompt binding no longer matches {p['surface']}"))
            continue
        compare(p["id"], f"{p['surface']} prompt", p.get("claim_id"), p.get("polarity", "claim"),
                p.get("asserted_tier", "proven"), p["pattern"])

    # free text on live surfaces with no binding yet (strict mode lite)
    for rel in ("tools/hivemind/lessons.json",):
        txt = ctx.code(rel) or ""
        for hit in _strong_unnegated(txt):
            out.append(_f("D1", "text_" + common.slug(rel, 30), "warn", f"{rel} uses strong wording", text=hit))
    for rel in ("hivemind/decisions.json", "hivemind/geometry_shadow.json"):
        p = ctx.data_dir / rel
        if p.exists():
            for hit in _strong_unnegated(p.read_text(encoding="utf-8", errors="replace")):
                out.append(_f("D1", "text_" + common.slug(rel, 30), "warn", f"{rel} uses strong wording", text=hit))
    na.append(_na("D1", "terminal.html / desk.py rendered strings",
                  "surfaces carry no claim_id yet (phase 3 render.py); only milestones, scanner chips and bound "
                  "prompt sentences are graded"))
    return out, na


# ---------------------------------------------------------------------------------------------------------------
def _ledger_evidence(ctx, spec):
    """Re-run the gate's own row filter on the ledger (read-only) and find where its evidence stopped."""
    p = ctx.data_dir / spec["file"]
    if not p.exists():
        return None
    floor_on = str(ctx.env.get(spec.get("fee_floor_env", ""), "false")).lower() in ("1", "true", "yes")
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
            rows.append((t, (not floor_on) or fees >= spec["fee_floor"], pnl))
    if not rows:
        return None
    q = [t for t, ok, _ in rows if ok]
    last_q = max(q) if q else None
    newer = [(t, pnl) for t, ok, pnl in rows if not ok and (last_q is None or t > last_q)]
    return {"last_qualifying_ts": last_q, "newest_ts": max(t for t, _, _ in rows), "n_rows": len(rows),
            "n_qualifying": len(q), "n_ignored_newer": len(newer), "ignored_net_usd": round(sum(p for _, p in newer), 2),
            "fee_floor_on": floor_on}


def check_d2_stale_gate(ctx, max_lag_days=14):
    """D2: a ledger-fed gate whose last usable row is > max_lag_days older than the newest trade it could have seen
    (i.e. trades kept happening but its filter throws them away). Also warns on dollar-unit gates (brief section 3)."""
    out, na = [], []
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d") if t else None  # noqa: E731
    for rid, r in sorted(ctx.reg["rules"].items()):
        spec = r.get("evidence_source")
        if not spec:
            if r.get("claim_id") not in ("owner_policy",) and not r.get("exempt_reason"):
                na.append(_na("D2", f"rule {rid}", "evidence source not machine-readable yet"))
            continue
        if spec.get("kind") != "ledger":
            na.append(_na("D2", f"rule {rid}", f"evidence kind {spec.get('kind')} not automated"))
            continue
        ev = _ledger_evidence(ctx, spec)
        if ev is None:
            na.append(_na("D2", f"rule {rid}", f"ledger {spec['file']} missing in {ctx.data_dir}"))
            continue
        lag = (ev["newest_ts"] - (ev["last_qualifying_ts"] or 0)) / 86400
        if ev["n_ignored_newer"] > 0 and lag > max_lag_days:
            out.append(_f("D2", rid, "high",
                          f"{rid}: evidence frozen at {iso(ev['last_qualifying_ts'])} while {ev['n_ignored_newer']} "
                          f"newer trades (net ${ev['ignored_net_usd']}) were ignored by the ${spec['fee_floor']} "
                          f"fee filter (newest trade {iso(ev['newest_ts'])})",
                          evidence_through=iso(ev["last_qualifying_ts"]), **{k: v for k, v in ev.items()
                                                                            if k.startswith(("n_", "ignored"))}))
        unit = str(r.get("unit") or "").lower()
        if "dollar" in unit and r.get("claim_id") != "owner_policy":
            out.append(_f("D2", rid + "_unit", "warn", f"{rid}: learning gate in dollars ({r['unit']}); target unit "
                          "is bps of notional", unit=r.get("unit")))
    return out, na


# ---------------------------------------------------------------------------------------------------------------
def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _exp_move_live(ctx):
    """Per-coin exp_move from each live output that carries one: {coin: {source: value}} (read-only)."""
    vals = {}
    hm = ctx.data_dir / "hivemind"
    for p in sorted((hm / "state").glob("*.json")) if (hm / "state").exists() else []:
        if p.stem.startswith("_"):
            continue
        s = common.load_json(p, {}) or {}
        v = _num((s.get("vol") or {}).get("next_day_move_pct"))
        if v is not None:
            vals.setdefault(p.stem, {})["state.vol.next_day_move_pct"] = v
    scan = common.load_json(hm / "scan.json", {}) or {}
    for r in scan.get("coins", []):
        if r.get("coin") in vals:
            v = _num(r.get("exp_move"))
            if v is not None:
                vals[r["coin"]]["scan.exp_move"] = v
    chief = common.load_json(hm / "chief_latest.json", {}) or {}
    for coin, c in (chief.get("coins") or {}).items():
        v = _num((c or {}).get("expected_move_pct")) if isinstance(c, dict) else None
        if v is not None and coin in vals:
            vals[coin]["chief.expected_move_pct"] = v
    return vals


def check_d3_definition_drift(ctx):
    """D3: a quantity/flag with more than one distinct implementation; for exp_move, also compare the live numbers
    each implementation produced for the same coin (alarm above the card's alarm_rel_diff)."""
    out, na = [], []
    for name, d in sorted(ctx.reg["definitions"].items()):
        if d.get("kind") == "stream":
            continue
        impls = [i for i in d.get("implementations", []) if i.get("role") not in ("display", "helper")]
        hashes = {i.get("impl_hash") for i in impls}
        if len(impls) > 1 and len(hashes) > 1:
            out.append(_f("D3", name, "high", f"'{name}' has {len(impls)} different implementations: "
                          + "; ".join(i["label"] for i in impls),
                          implementations=[{"label": i["label"], "where": f"{i.get('path') or i.get('doc')}"
                                            f":{i.get('line') or ''}", "impl_hash": i.get("impl_hash")}
                                           for i in impls]))
    exp = ctx.reg["definitions"].get("exp_move")
    if exp:
        alarm = (exp.get("cross_check") or {}).get("alarm_rel_diff", 0.10)
        vals = _exp_move_live(ctx)
        if not vals:
            na.append(_na("D3", "exp_move numeric cross-check", "no live state/scan/chief outputs in data dir"))
        for coin, v in sorted(vals.items()):
            if len(v) < 2:
                continue
            lo, hi = min(v.values()), max(v.values())
            rel = (hi - lo) / lo if lo > 0 else None
            if rel is not None and rel > alarm:
                out.append(_f("D3", f"exp_move_{coin}", "warn",
                              f"exp_move for {coin} disagrees by {rel:.0%} across live outputs", values=v))
    return out, na


# ---------------------------------------------------------------------------------------------------------------
def check_d4_impl_vs_tested(ctx):
    """D4: re-hash each implementation; flag code that changed since the card was hashed, or that differs from the
    tested hash when the laptop has recorded one. Implementations with no tested hash are listed as not_automated."""
    out, na = [], []
    for name, d in sorted(ctx.reg["definitions"].items()):
        for im in d.get("implementations", []):
            if not im.get("path"):
                continue
            now_h = common.impl_hash(im, ctx.code_root)
            if now_h is None:
                out.append(_f("D4", f"{name}:{im['label']}", "high",
                              f"{name}: implementation '{im['label']}' not found in {im['path']} (card out of date)"))
            elif im.get("impl_hash") and now_h != im["impl_hash"]:
                out.append(_f("D4", f"{name}:{im['label']}", "warn",
                              f"{name}: '{im['label']}' code changed since the card was hashed - re-test or re-sign",
                              card_hash=im["impl_hash"], live_hash=now_h))
        tested = d.get("tested_impl_hash")
        if tested:
            canon = next((i for i in d.get("implementations", []) if i.get("label") == d.get("canonical")), None)
            if canon and common.impl_hash(canon, ctx.code_root) != tested:
                out.append(_f("D4", name, "high", f"{name}: live code is not the code that was tested"))
        elif d.get("kind") != "stream":
            na.append(_na("D4", name, "no tested_impl_hash on the card yet (laptop to record the hash it tested)"))
    return out, na


# ---------------------------------------------------------------------------------------------------------------
def _scan_grader_metric(ctx, flag):
    """What tools/hivemind/scan_grader.py actually measures for a flag (parsed from its SIGN table)."""
    src = ctx.code("tools/hivemind/scan_grader.py")
    if not src:
        return None
    sign = {}
    for node in ast.parse(src).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "SIGN" for t in node.targets):
            sign = ast.literal_eval(node.value)
    if flag in sign:
        return "signed_excess_return_vs_universe_median"
    return "abs_excess_return_vs_universe_median"


def check_d5_grader_vs_claim(ctx):
    """D5: the grader bound to a claim must measure the claim's own metric (and sign)."""
    out, na = [], []
    for g in ctx.reg["bindings"].get("graders", []):
        c = ctx.claim(g["claim_id"])
        if c is None:
            out.append(_f("D5", g["id"], "warn", f"grader {g['id']} bound to missing claim {g['claim_id']}"))
            continue
        if not c.get("metric"):
            na.append(_na("D5", g["id"], f"claim {c['id']} has no metric field"))
            continue
        if g["grader"].endswith("scan_grader.py"):
            gm = _scan_grader_metric(ctx, g["flag"])
        else:
            na.append(_na("D5", g["id"], f"grader {g['grader']} not parsed"))
            continue
        if gm != c["metric"]:
            out.append(_f("D5", g["id"], "high", f"{g['grader']} grades '{g['flag']}' on {gm}, but claim {c['id']} "
                          f"is about {c['metric']} - its forward grade cannot confirm or refute the claim",
                          grader_metric=gm, claim_metric=c["metric"]))
    return out, na


# ---------------------------------------------------------------------------------------------------------------
LIVE_BOT_PATHS = ("core", "execution", "multi_strategy_main.py")
STRING_LIT = re.compile(r"""[fFrRbB]*("([^"\\]|\\.)*"|'([^'\\]|\\.)*'|"[^"]*$|'[^']*$)""")


def _grep_code(ctx, paths, pattern):
    """[(relpath, line_no, line)] for regex matches in *.py under the given bot-relative paths."""
    rx = re.compile(pattern)
    hits = []
    for rel in paths:
        p = ctx.code_root / rel
        files = [p] if p.is_file() else (sorted(p.rglob("*.py")) if p.is_dir() else [])
        for fp in files:
            try:
                for i, ln in enumerate(fp.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if rx.search(ln):
                        hits.append((str(fp.relative_to(ctx.code_root)).replace("\\", "/"), i, ln.strip()))
            except OSError:
                continue
    return hits


def check_d6_orphans(ctx):
    """D6: (a) PROVEN claim with live_bot_terms that appear nowhere in the live bot (core/, execution/,
    multi_strategy_main.py); (b) live rule with no claim, or bound to a dead (STALE/REFUTED/...) claim, or in conflict
    with a decided claim; (c) a cap the rule card says is enforced but that only reaches a prompt."""
    out, na = [], []
    for cid, c in sorted(ctx.reg["claims"].items()):
        if c.get("status") != "PROVEN":
            continue
        terms = c.get("live_bot_terms") or []
        if not terms:
            na.append(_na("D6", f"claim {cid}", "no live_bot_terms: consumer search not automated"))
            continue
        hits = [h for h in _grep_code(ctx, LIVE_BOT_PATHS, "|".join(re.escape(t) for t in terms))
                if not h[2].startswith("#")]
        flags = c.get("live_bot_flags") or []
        off = [k for k in flags if str(ctx.env.get(k, "false")).lower() in ("", "0", "false", "off", "no")]
        if not hits:
            out.append(_f("D6", f"claim_{cid}", "high", f"PROVEN claim {cid} reaches no live bot code "
                          f"({', '.join(terms)} not in {', '.join(LIVE_BOT_PATHS)})", claim_id=cid))
        elif flags and len(off) == len(flags):
            out.append(_f("D6", f"claim_{cid}_flag_off", "warn", f"PROVEN claim {cid} reaches the bot only behind "
                          f"{', '.join(flags)}, which is OFF in .env", claim_id=cid,
                          where=[f"{h[0]}:{h[1]}" for h in hits[:5]]))
    for rid, r in sorted(ctx.reg["rules"].items()):
        cid = r.get("claim_id")
        if cid is None:
            if r.get("exempt_reason"):
                continue
            out.append(_f("D6", f"rule_{rid}", "warn", f"live rule {rid} has no claim behind it",
                          rule=r.get("description", "")[:160]))
        elif cid != "owner_policy":
            c = ctx.claim(cid)
            if c is None:
                out.append(_f("D6", f"rule_{rid}", "warn", f"rule {rid} cites missing claim {cid}"))
            elif c["status"] in common.DEAD_STATUSES:
                out.append(_f("D6", f"rule_{rid}", "high", f"live rule {rid} binds claim {cid}, which is "
                              f"{c['status']} - a dead claim may not bind", claim_id=cid))
        for other in r.get("conflicts_with") or []:
            c = ctx.claim(other)
            if c and c["status"] in ("REFUTED", "PROVEN"):
                out.append(_f("D6", f"rule_{rid}_vs_{other}", "warn",
                              f"live rule {rid} conflicts with {other} ({c['status']})"))
        ec = r.get("enforcement_check")
        if ec:
            prompt_hit = any(_grep_code(ctx, [m["path"]], m["pattern"]) for m in ec.get("prompt_markers", []))
            # comments and string literals (log / prompt text) are not enforcement: strip them, then re-match
            clamp = re.compile(ec["clamp_pattern"])
            code_hit = [h for h in _grep_code(ctx, ec["code_paths"], ec["clamp_pattern"])
                        if clamp.search(STRING_LIT.sub("", h[2].split("#")[0]))]
            if prompt_hit and not code_hit:
                out.append(_f("D6", f"rule_{rid}_prompt_only", "high",
                              f"{rid}: the cap ({', '.join(r.get('flags') or [])}) only reaches the agent's prompt - "
                              "no code clamps the risk the agent returns", env_value={k: ctx.env.get(k)
                                                                                      for k in r.get("flags") or []}))
    return out, na


# ---------------------------------------------------------------------------------------------------------------
ENV_PAIR = re.compile(r"\b([A-Z][A-Z0-9_]{3,})=([A-Za-z0-9_.\-]+)")
ENV_DEFAULT_OFF = re.compile(r"\b([A-Z][A-Z0-9_]{3,}),?\s*default off", re.I)


def check_d7_config_vs_card(ctx):
    """D7: decision cards (data/hivemind/decisions.json) that quote an env setting the .env contradicts: a pending
    'set X=v' that is already live, a stated 'X=v' that is not, or 'X, default off' while .env turns it on."""
    out, na = [], []
    cards = common.load_json(ctx.data_dir / "hivemind" / "decisions.json", None)
    if cards is None:
        return out, [_na("D7", "decision cards", "data/hivemind/decisions.json missing")]
    if not ctx.env:
        return out, [_na("D7", "decision cards", ".env not readable")]
    offish = {"", "0", "false", "off", "no"}
    for card in cards:
        text = " ".join(str(card.get(k) or "") for k in ("ask", "why", "live", "note", "ready_when"))
        for m in ENV_PAIR.finditer(text):
            k, v = m.group(1), m.group(2).rstrip(".")
            if k not in ctx.env:
                continue
            live = ctx.env[k]
            proposal = re.search(r"\bset\s*$", text[max(0, m.start() - 8):m.start()], re.I)
            if proposal and live == v and not card.get("ready"):
                out.append(_f("D7", f"{card.get('id')}:{k}", "high",
                              f"decision card '{card.get('id')}' still asks to set {k}={v}, but .env already has it",
                              env_value=live))
            elif not proposal and live != v:
                out.append(_f("D7", f"{card.get('id')}:{k}", "high",
                              f"decision card '{card.get('id')}' says {k}={v}, .env says {k}={live}"))
        for m in ENV_DEFAULT_OFF.finditer(text):
            k = m.group(1)
            if k in ctx.env and ctx.env[k].lower() not in offish:
                out.append(_f("D7", f"{card.get('id')}:{k}:default", "warn",
                              f"decision card '{card.get('id')}' describes {k} as default off; .env has {k}="
                              f"{ctx.env[k]}"))
    na.append(_na("D7", "free-text claims about behaviour ('confirmed live')", "only KEY=value quotes are checked"))
    return out, na


# ---------------------------------------------------------------------------------------------------------------
def check_d8_count_disagreement(ctx):
    """D8: threads.json rows where two sources give different counts/dates for the same thing."""
    out = []
    for t in (ctx.reg["threads"] or {}).get("threads", []):
        for d in t.get("disagreements", []):
            if d["a"]["value"] != d["b"]["value"]:
                out.append(_f("D8", f"{t['id']}:{d['field']}", "warn",
                              f"{t['thread']}: {d['field']} is {d['a']['value']} per {d['a']['source']} but "
                              f"{d['b']['value']} per {d['b']['source']}"))
    na = [_na("D8", "live recount of prereg trackers", "laptop crunch TRACKERS is not readable from the server yet; "
                                                       "only disagreements recorded on threads are checked")]
    return out, na


# ---------------------------------------------------------------------------------------------------------------
def _streams(ctx):
    return {n: d for n, d in sorted(ctx.reg["definitions"].items()) if d.get("kind") == "stream"}


def _last_rows(path, n):
    rows = []
    for ln in common.tail_lines(path, n):
        try:
            rows.append(json.loads(ln))
        except ValueError:
            continue
    return rows


def check_d9_substrate_death(ctx):
    """D9: an un-backfillable stream whose newest row (or newest off-box archive shard) is older than max_age_days."""
    out, na = [], []
    arch_root = ctx.data_dir / "laptop_mining" / "server_exports" / "archive"
    for name, d in _streams(ctx).items():
        s = d["stream"]
        p = ctx.data_dir / s["path"]
        max_age = s.get("max_age_days", 2)
        if not p.exists():
            out.append(_f("D9", name, "high", f"stream {name} file is missing ({s['path']})"))
            continue
        rows = _last_rows(p, 3)
        t = max((common.row_epoch(r) or 0 for r in rows), default=0)
        age = (ctx.now - t) / 86400 if t else None
        if age is None or age > max_age:
            out.append(_f("D9", name, "high", f"stream {name} stopped: newest row "
                          f"{'unreadable' if age is None else f'{age:.1f} days old'} (limit {max_age})",
                          path=s["path"]))
        adir = arch_root / s.get("archive", "")
        if s.get("archive") and adir.exists():
            days = sorted(f.name[:10] for f in adir.glob("*.jsonl.gz"))
            if days:
                last = datetime.strptime(days[-1], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() + 86400
                a_age = (ctx.now - last) / 86400
                if a_age > max_age:
                    out.append(_f("D9", name + "_offbox", "high", f"off-box archive of {name} stalled: last shard "
                                  f"{days[-1]} ({a_age:.1f} days)"))
        elif s.get("archive"):
            na.append(_na("D9", f"{name} off-box copy", f"no archive dir {adir}"))
    na.append(_na("D9", "copy actually on the laptop", "checks the export staging dir, not the laptop's disk"))
    return out, na


def check_d10_payload_completeness(ctx):
    """D10: fields a stream card expects (baseline) that the newest rows no longer write, and fields the oldest rows
    had that the newest rows dropped (stream thinning, laptop red-team item 1)."""
    out, na = [], []
    for name, d in _streams(ctx).items():
        p = ctx.data_dir / d["stream"]["path"]
        if not p.exists():
            continue
        mk = tuple(d["stream"].get("map_keys") or ())
        new = set()
        for r in _last_rows(p, 20):
            new |= common.flatten_fields(r, map_keys=mk)
        expected = set(d.get("expected_fields") or [])
        if not expected:
            na.append(_na("D10", name, "no expected_fields baseline on the card"))
        missing = sorted(expected - new)
        if missing:
            out.append(_f("D10", name, "high", f"stream {name} stopped writing {len(missing)} of {len(expected)} "
                          "expected fields", missing=missing))
        old = set()
        for ln in common.head_lines(p, 5):
            try:
                old |= common.flatten_fields(json.loads(ln), map_keys=mk)
            except ValueError:
                continue
        dropped = sorted(old - new - set(missing))
        if dropped:
            out.append(_f("D10", name + "_history", "warn", f"stream {name}: fields present in its oldest rows are "
                          "gone from the newest", dropped=dropped))
    na.append(_na("D10", "source API field set", "the collectors' raw API payloads are not captured; only the "
                                                  "written schema over time is compared"))
    return out, na


def _eval_invariant(expr, row):
    """Evaluate one invariant on one row. g('a.b') reads a dotted field (None if absent). Expressions come from our
    own definition cards (repo-controlled), evaluated with no builtins beyond abs/min/max/all/any/len."""
    def g(path):
        cur = row
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur[part]
        return cur
    env = {"__builtins__": {}, "abs": abs, "min": min, "max": max, "all": all, "any": any, "len": len, "g": g}
    try:
        return bool(eval(expr, env))  # noqa: S307
    except (TypeError, KeyError, AttributeError, ValueError, ZeroDivisionError):
        return None          # a missing / non-numeric field: not evaluable on this row


def check_d11_semantic_invariants(ctx, sample=200):
    """D11: every invariant on a stream definition card, checked over the last `sample` rows; plus funding_hot's
    share-flagged invariant on the live scan.json."""
    out, na = [], []
    for name, d in _streams(ctx).items():
        p = ctx.data_dir / d["stream"]["path"]
        if not p.exists() or not d.get("invariants"):
            continue
        rows = _last_rows(p, sample)
        for inv in d["invariants"]:
            res = [_eval_invariant(inv["expr"], r) for r in rows]
            bad = [r for r, ok in zip(rows, res) if ok is False]
            n_eval = sum(ok is not None for ok in res)
            if bad:
                out.append(_f("D11", f"{name}:{inv['why']}", "high",
                              f"stream {name}: {len(bad)}/{n_eval} recent rows break '{inv['why']}'",
                              expr=inv["expr"], example=json.dumps(bad[0])[:300]))
            elif n_eval == 0:
                na.append(_na("D11", f"{name}:{inv['why']}", "invariant not evaluable on any recent row"))
    fh = ctx.reg["definitions"].get("funding_hot")
    scan = common.load_json(ctx.data_dir / "hivemind" / "scan.json", None)
    if fh and scan and scan.get("coins"):
        share = sum("funding_hot" in (r.get("flags") or []) for r in scan["coins"]) / len(scan["coins"])
        for inv in fh.get("invariants", []):
            ok = _eval_invariant(inv["expr"], {"share_flagged": share})
            if ok is False:
                out.append(_f("D11", "funding_hot:share", "high", f"funding_hot flags {share:.0%} of scanned coins "
                              f"({inv['why']})", share=round(share, 3)))
    na.append(_na("D11", "definition invariants on quantities (R, exp_move)", "evaluated on streams + scan.json only"))
    return out, na


def _load_pure_fn(ctx, spec):
    """'path:func' -> the function, compiled from its own source only (no module import, no network, no side effects).
    The function must be pure Python with no module-level dependencies."""
    path, name = spec.split(":")
    tree = ast.parse(ctx.code(path))
    node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), None)
    if node is None:
        return None
    ns = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), ns)
    return ns[name]


def check_d12_behavior_vs_tested(ctx):
    """D12 (laptop reply 119): the LIVE definition must behave exactly like the TESTED one on a frozen fixture.
    Semantics, not source text - a refactor cannot false-alarm, a semantic drift (0.80 -> 0.90, a floor) cannot hide."""
    out, na = [], []
    for name, d in sorted(ctx.reg["definitions"].items()):
        fx = d.get("behavior_fixture")
        if not fx:
            if d.get("kind") != "stream":
                na.append(_na("D12", name, "no behaviour fixture on the card yet"))
            continue
        sem, sh = d.get("tested_semantics"), d.get("tested_semantics_hash")
        if sem and sh and hashlib.sha256(sem.encode()).hexdigest()[:16] != sh:     # laptop 0947ef0c: a stale hash
            out.append(_f("D12", f"{name}:semantics_hash", "warn", f"{name}: tested_semantics_hash does not match the "
                          "tested_semantics string (string edited without re-hashing)"))
        fn = _load_pure_fn(ctx, fx["fn"])
        if fn is None:
            out.append(_f("D12", name, "high", f"{name}: {fx['fn']} not found - live code moved, card out of date"))
            continue
        bad = []
        for i, c in enumerate(fx["cases"]):
            got = [j for j, h in enumerate(fn(c["x"])) if h]
            if got != c["hot"]:
                bad.append(i)
        if bad:
            kd = d.get("known_drift")      # a recorded, owned drift stays visible but is not an unexplained alarm
            out.append(_f("D12", name, "warn" if kd else "high", f"{name}: live code disagrees with the tested definition "
                          f"on {len(bad)}/{len(fx['cases'])} fixture cases"
                          + (f" (known: {kd['what']}; resolves via {kd['resolution']})" if kd else ""), cases=bad[:10]))
    return out, na


def check_d13_decision_estimator(ctx):
    """D13 (laptop 0947ef0c): a claim's DECISION NUMBER must come from the same estimator as its EVIDENCE. K*=1.698 was
    marginal while the test that justified it was matched - half the size, and for '>' on the naive em the wrong sign."""
    out, na = [], []
    for cid, c in sorted(ctx.reg["claims"].items()):
        for dn in c.get("decision_numbers") or []:
            ev = (c.get("evidence") or {}).get("estimator")
            if not ev or not dn.get("estimator"):
                na.append(_na("D13", f"{cid}:{dn.get('name')}", "estimator not recorded on the evidence or the number"))
            elif dn["estimator"].split("(")[0].strip().lower() != ev.split("(")[0].strip().lower():
                out.append(_f("D13", f"{cid}:{dn.get('name')}", "high", f"{cid}: decision number '{dn.get('name')}' uses "
                              f"estimator '{dn['estimator']}' but the evidence used '{ev}'"))
    return out, na


CHECKS = [("D1", check_d1_display_vs_grade), ("D2", check_d2_stale_gate), ("D3", check_d3_definition_drift),
          ("D4", check_d4_impl_vs_tested), ("D5", check_d5_grader_vs_claim), ("D6", check_d6_orphans),
          ("D7", check_d7_config_vs_card), ("D8", check_d8_count_disagreement), ("D9", check_d9_substrate_death),
          ("D10", check_d10_payload_completeness), ("D11", check_d11_semantic_invariants),
          ("D12", check_d12_behavior_vs_tested),
          ("D13", check_d13_decision_estimator)]


def run(ctx, out_path=None):
    """Run every check; never let one broken check hide the others. Writes the report if out_path is given."""
    findings, not_auto, summary = [], [], {}
    for name, fn in CHECKS:
        try:
            f, na = fn(ctx)
        except Exception as e:      # a crashed check is itself a finding, never a silent pass
            f, na = [_f(name, "check_crashed", "high", f"{name} crashed: {type(e).__name__}: {e}")], []
        findings += f
        not_auto += na
        summary[name] = {"flagged": len(f), "high": sum(x["severity"] == "high" for x in f),
                         "not_automated": len(na)}
    rep = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "now": datetime.fromtimestamp(ctx.now, timezone.utc).isoformat(timespec="seconds"),
           "registry": str(ctx.registry_root), "data_dir": str(ctx.data_dir), "summary": summary,
           "discrepancies": findings, "not_automated": not_auto}
    if out_path:
        common.write_json(out_path, rep)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description="HIVEMIND discrepancy checks D1-D11")
    ap.add_argument("--registry", default=str(KNOWLEDGE))
    ap.add_argument("--code-root", default=str(BOT))
    ap.add_argument("--data-dir", default=str(DATA), help="read-only")
    ap.add_argument("--env", default=None, help="read-only .env (default <code-root>/.env)")
    ap.add_argument("--out", default=str(DATA / "knowledge" / "discrepancies.json"))
    ap.add_argument("--now", type=float, default=None)
    a = ap.parse_args(argv)
    ctx = Ctx(a.registry, a.code_root, a.data_dir, a.env, a.now)
    rep = run(ctx, a.out)
    for name, s in rep["summary"].items():
        print(f"{name:4} flagged={s['flagged']:3} high={s['high']:3} not_automated={s['not_automated']}")
    for f in rep["discrepancies"]:
        print(f"  [{f['check']}/{f['severity']}] {f['what']}")
    print("wrote", a.out)


if __name__ == "__main__":
    main()
