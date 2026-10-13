"""Caller-form join (laptop handoff "STEP 2"): attach each call's caller ROLLING FORM without exporting identity.

Input A (public facts, from the laptop): call_outcomes.jsonl - one row per call {ca, call_ts (s), chat in
  dtn / syndicate / dtn_hitters, hit2x_7d, hit15_24h, resolved_7d_at, resolved_24h_at, ...}. Read by default
  straight from git (origin/laptop-mining-2026-10:bot/data/laptop_mining/call_outcomes.jsonl); --ref / --outcomes
  override.
Input B (LOCAL ONLY, has identity): data/hivemind/tg/history_calls.jsonl (tg_history.py) + calls.jsonl
  (tg_listener.py live). Both rows carry {ts, chat_id, chat, sender_id, sender, ca}. The caller of a call is the
  sender of the FIRST mention of that ca in that chat (same definition as tg_calls_history_anon).

Identity lives only in memory here; the output carries only ca / call_ts / chat and anonymous numbers.

Output: data/laptop_mining/server_exports/call_caller_form_anon.jsonl, one row per input row, fields
  ca, call_ts, chat, caller_is_bot, form_n_prior_calls, form_n_known_7d, form_hit2x_7d, form_n_known_24h,
  form_hit15_24h, form_decile_2x7d
Rules (contract as delivered 2026-10-12, SERVER_REPLY "STEP 2"):
  - bot first-poster (sender ends with "bot", case-insensitive, or is not an @handle) -> caller_is_bot=true,
    all form fields null (the 2026-10-12 file omitted them; null keeps the laptop's non-null coverage counts).
  - caller not found in B -> caller_is_bot null, all form fields null (counted and printed).
  - form uses ONLY the same caller's EARLIER calls (call_ts strictly less) inside this corpus, pooled across chats
    (caller = Telegram sender_id); a prior call's hit2x_7d counts only if it is non-null and resolved_7d_at <
    call_ts, hit15_24h only if non-null and resolved_24h_at < call_ts (null = the laptop could not resolve it; it
    is NOT a miss). Dead calls use the laptop's stamps as given.
  - form_decile_2x7d = decile 0..9 of form_hit2x_7d among calls with form_n_known_7d >= 3 (null otherwise);
    0-based to match the shipped file and the laptop's prereg. Rates rounded to 3 dp (as shipped).

Re-runnable: python tools/hivemind/caller_form_join.py [--ref REF | --outcomes FILE] [--out FILE] [--check OLDFILE]
"""
import argparse
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
TG = BOT / "data" / "hivemind" / "tg"
SOURCES = [TG / "history_calls.jsonl", TG / "calls.jsonl"]
OUT = BOT / "data" / "laptop_mining" / "server_exports" / "call_caller_form_anon.jsonl"
DEFAULT_REF = "origin/laptop-mining-2026-10"
OUTCOMES_PATH = "bot/data/laptop_mining/call_outcomes.jsonl"
CHAT_LABEL = {-1002296469254: "dtn", -1002590870121: "dtn_hitters", -1003904703116: "syndicate"}
FIELDS = ["ca", "call_ts", "chat", "caller_is_bot", "form_n_prior_calls", "form_n_known_7d", "form_hit2x_7d",
          "form_n_known_24h", "form_hit15_24h", "form_decile_2x7d"]
MIN_KNOWN_DECILE = 3


def _label(chat_id, title):
    if chat_id in CHAT_LABEL:
        return CHAT_LABEL[chat_id]
    t = (title or "").lower()
    if "syndicate" in t:
        return "syndicate"
    if "hitters" in t:
        return "dtn_hitters"
    if "diamond trencher" in t:
        return "dtn"
    return None


def load_outcomes(ref=None, path=None):
    if path:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = subprocess.run(["git", "-C", str(BOT.parent), "show", f"{ref}:{OUTCOMES_PATH}"], check=True,
                              capture_output=True, text=True, encoding="utf-8").stdout
    return [json.loads(l) for l in text.splitlines() if l.strip()]


def first_posters(wanted):
    """{(chat_label, ca): (ts, sender_id, sender)} for the earliest mention, only for wanted keys. Streams."""
    first = {}
    for fn in SOURCES:
        if not fn.exists():
            continue
        with open(fn, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                ca = r.get("ca")
                if not ca:
                    continue
                k = (_label(r.get("chat_id"), r.get("chat")), ca)
                if k not in wanted:
                    continue
                ts = float(r.get("ts") or 0)
                if k not in first or ts < first[k][0]:
                    first[k] = (ts, r.get("sender_id"), str(r.get("sender") or ""))
    return first


def is_bot(sender):
    return sender.lower().endswith("bot") or not sender.startswith("@")


def decile_of(value, sorted_vals):
    """Decile 0..9 = floor(10 * (number of eligible values strictly below this one) / n_eligible).
    This is the 0-based scale the 384-row file of 2026-10-12 shipped and the laptop's sealed prereg quotes
    ({0:23, 1:3, ...}); ties share the lowest decile of their block. Descriptive only in that prereg."""
    import bisect
    return int(10 * bisect.bisect_left(sorted_vals, value) / len(sorted_vals))


def compute(rows, first):
    stats = Counter()
    callers = {}  # row index -> caller key (in memory only)
    out = []
    for i, r in enumerate(rows):
        f = first.get((r["chat"], r["ca"]))
        if f is None:
            stats["unknown"] += 1
            callers[i] = None
        elif is_bot(f[2]):
            stats["bot"] += 1
            callers[i] = "BOT"
        else:
            stats["found"] += 1
            callers[i] = f[1] if f[1] is not None else f[2]
    by_caller = defaultdict(list)
    for i, c in callers.items():
        if c not in (None, "BOT"):
            by_caller[c].append(i)
    for i, r in enumerate(rows):
        c = callers[i]
        o = {"ca": r["ca"], "call_ts": r["call_ts"], "chat": r["chat"]}
        if c is None:
            o.update(caller_is_bot=None, form_n_prior_calls=None, form_n_known_7d=None, form_hit2x_7d=None,
                     form_n_known_24h=None, form_hit15_24h=None, form_decile_2x7d=None)
        elif c == "BOT":
            o.update(caller_is_bot=True, form_n_prior_calls=None, form_n_known_7d=None, form_hit2x_7d=None,
                     form_n_known_24h=None, form_hit15_24h=None, form_decile_2x7d=None)
        else:
            t = r["call_ts"]
            prior = [rows[j] for j in by_caller[c] if rows[j]["call_ts"] < t]
            k7 = [p for p in prior if p.get("hit2x_7d") is not None
                  and p.get("resolved_7d_at") is not None and p["resolved_7d_at"] < t]
            k24 = [p for p in prior if p.get("hit15_24h") is not None
                   and p.get("resolved_24h_at") is not None and p["resolved_24h_at"] < t]
            o.update(caller_is_bot=False, form_n_prior_calls=len(prior), form_n_known_7d=len(k7),
                     form_hit2x_7d=(sum(bool(p.get("hit2x_7d")) for p in k7) / len(k7)) if k7 else None,
                     form_n_known_24h=len(k24),
                     form_hit15_24h=(sum(bool(p.get("hit15_24h")) for p in k24) / len(k24)) if k24 else None,
                     form_decile_2x7d=None)
        out.append(o)
    elig = sorted(o["form_hit2x_7d"] for o in out if (o["form_n_known_7d"] or 0) >= MIN_KNOWN_DECILE)
    for o in out:
        if (o["form_n_known_7d"] or 0) >= MIN_KNOWN_DECILE:
            o["form_decile_2x7d"] = decile_of(o["form_hit2x_7d"], elig)
    for o in out:
        for k in ("form_hit2x_7d", "form_hit15_24h"):
            if o[k] is not None:
                o[k] = round(o[k], 3)  # 3 dp, as shipped 2026-10-12
    stats["decile_eligible"] = len(elig)
    return out, stats


def check(new, old_path):
    old = {(o["chat"], o["ca"], o["call_ts"]): o for o in map(json.loads, open(old_path, encoding="utf-8"))}
    newk = {(o["chat"], o["ca"], o["call_ts"]): o for o in new}
    common = [k for k in old if k in newk]
    diff = Counter()
    for k in common:
        for f in FIELDS[3:]:
            a, b = old[k].get(f), newk[k].get(f)
            if (a != b) and not (isinstance(a, float) and isinstance(b, float) and abs(a - b) < 1e-9):
                diff[f] += 1
    print(f"check vs {Path(old_path).name}: old {len(old)}, common {len(common)}, missing from new "
          f"{len(old) - len(common)}; field diffs {dict(diff) or 'none'}")
    return diff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default=DEFAULT_REF)
    ap.add_argument("--outcomes")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", help="old anon output to compare against (field diffs on common calls)")
    a = ap.parse_args()
    rows = load_outcomes(a.ref, a.outcomes)
    first = first_posters({(r["chat"], r["ca"]) for r in rows})
    out, st = compute(rows, first)
    del first
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        for o in out:
            f.write(json.dumps({k: o[k] for k in FIELDS}) + "\n")
    print(f"rows {len(out)} | caller found {st['found']} | bot {st['bot']} | unknown {st['unknown']} | "
          f"form_n_known_7d>=3 {st['decile_eligible']} -> {a.out}")
    if a.check:
        check(out, a.check)


if __name__ == "__main__":
    sys.exit(main())
