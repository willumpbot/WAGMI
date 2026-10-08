"""Probe the three largest unexamined legacy files for usable reasoning/outcomes.

percepts / omniscient_state / counterfactual_resolved are 180-340 MB each, so
sample the head rather than streaming all of it.
"""
import json, collections, io

BASE = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/data/"
FILES = [
    ("nlm_omniscient_state.jsonl", BASE + "nlm_omniscient_state.jsonl"),
    ("llm/bot_perception/percepts.jsonl", BASE + "llm/bot_perception/percepts.jsonl"),
    ("llm/counterfactual_resolved.jsonl", BASE + "llm/counterfactual_resolved.jsonl"),
]

TEXTKEYS = ("reasoning", "rationale", "thesis", "analysis", "narrative",
            "explanation", "summary", "commentary", "perception", "thought",
            "debate_summary", "notes")
OUTCOMEKEYS = ("outcome", "resolved", "r1h", "r4h", "r12h", "forward_return",
               "pnl", "realized", "result", "hit", "mfe", "mae")


def probe(label, path, limit=1500):
    print(f"\n{'='*78}\n{label}\n{'='*78}")
    n = 0
    keys = collections.Counter()
    texts = collections.Counter()
    textlen = collections.defaultdict(list)
    outs = collections.Counter()
    tss = []
    first = None
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.replace("\x00", "").strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                if not isinstance(d, dict):
                    continue
                n += 1
                if first is None:
                    first = d
                for k in d:
                    keys[k] += 1
                for k in TEXTKEYS:
                    v = d.get(k)
                    if isinstance(v, str) and len(v.strip()) > 10:
                        texts[k] += 1
                        textlen[k].append(len(v))
                for k in OUTCOMEKEYS:
                    if k in d and d[k] not in (None, ""):
                        outs[k] += 1
                for tk in ("timestamp", "ts", "time"):
                    if d.get(tk):
                        tss.append(str(d[tk]))
                        break
                if n >= limit:
                    break
    except FileNotFoundError:
        print("  FILE NOT FOUND")
        return
    print(f"  rows sampled     : {n}")
    print(f"  top-level keys   : {sorted(keys)[:22]}")
    print(f"  reasoning fields : {dict(texts) or 'NONE'}")
    for k, v in textlen.items():
        print(f"      {k}: mean {sum(v)//len(v)} chars, max {max(v)}")
    print(f"  outcome fields   : {dict(outs) or 'NONE'}")
    if tss:
        print(f"  ts span (sample) : {min(tss)[:19]} -> {max(tss)[:19]}")
    if first:
        print(f"  --- first row (trimmed) ---\n  {json.dumps(first)[:700]}")


for label, path in FILES:
    probe(label, path)
