"""How much of agent_evals/consensus.jsonl is usable (real agent output vs pipeline failure)?

This decides whether the laptop's April window can extend the server's grading.
"""
import json, collections, io

SRC = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/data/agent_evals/consensus.jsonl"

n = parse_fail = 0
usable, failed = [], 0
recs = collections.Counter()
theses = collections.Counter()
days = collections.Counter()
syms = collections.Counter()
nonempty_text = collections.Counter()

with io.open(SRC, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        line = line.replace("\x00", "").strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            parse_fail += 1
            continue
        if not isinstance(d, dict):
            continue
        n += 1
        cons = d.get("consensus") or {}
        recs[cons.get("recommendation")] += 1
        ao = (d.get("all_outputs") or {}).get("entry_decision") or {}
        thesis = (ao.get("thesis") or "").strip()
        theses[thesis[:46]] += 1
        votes = (cons.get("go_votes") or 0) + (cons.get("skip_votes") or 0)
        is_fail = (thesis == "LLM pipeline failure") or votes == 0
        if is_fail:
            failed += 1
            continue
        for k in ("thesis", "sizing_rationale", "debate_summary", "notes"):
            v = (ao.get(k) or "").strip()
            if v and v != "LLM pipeline failure":
                nonempty_text[k] += 1
        ts = str(d.get("timestamp", ""))
        days[ts[:10]] += 1
        syms[d.get("symbol")] += 1
        usable.append({
            "signal_id": d.get("signal_id"),
            "ts": ts,
            "sym": d.get("symbol"),
            "side": d.get("side"),
            "entry": d.get("entry"),
            "rec": cons.get("recommendation"),
            "conf": cons.get("confidence"),
            "go": cons.get("go_votes"),
            "skip": cons.get("skip_votes"),
            "action": ao.get("action"),
            "thesis": thesis,
            "risk_flags": ao.get("risk_flags"),
            "debate": (ao.get("debate_summary") or "")[:400],
        })

print(f"rows parsed      : {n}   (unparseable {parse_fail})")
print(f"pipeline failures: {failed}  ({100*failed/max(n,1):.1f}%)")
print(f"USABLE rows      : {len(usable)}  ({100*len(usable)/max(n,1):.1f}%)")

print("\n=== consensus recommendation distribution ===")
for k, v in recs.most_common(8):
    print(f"  {v:>6}  {k}")

print("\n=== top theses ===")
for k, v in theses.most_common(8):
    print(f"  {v:>6}  {k!r}")

if usable:
    print("\n=== usable rows detail ===")
    ts = sorted(u["ts"] for u in usable if u["ts"])
    print(f"  span: {ts[0][:19]} -> {ts[-1][:19]}")
    print(f"  distinct days: {len(days)}")
    print(f"  symbols: {dict(syms.most_common(8))}")
    print(f"  non-empty text fields: {dict(nonempty_text)}")
    print(f"  actions: {dict(collections.Counter(u['action'] for u in usable))}")
    with io.open("C:/Users/vince/WAGMI/bot/data/laptop_mining/consensus_usable.json",
                 "w", encoding="utf-8") as fh:
        json.dump(usable, fh, indent=0)
    print(f"  wrote consensus_usable.json ({len(usable)} rows)")
    print("\n=== sample usable thesis ===")
    for u in usable[:3]:
        print(f"  [{u['ts'][:19]}] {u['sym']} {u['side']} rec={u['rec']} action={u['action']}")
        print(f"      thesis: {u['thesis'][:220]}")
