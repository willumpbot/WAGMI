"""Can we reconstruct signal -> decision -> thought process on the legacy data?

The owner's framing: the money numbers are warped, but the CHAIN is valuable.
So probe, for each layer, (a) what join keys exist and (b) whether reasoning
text is present.
"""
import json, collections, io

BASE = "C:/Users/vince/WAGMI PROJECT/WAGMI/bot/data/"
LAYERS = {
    "signal  : manual/sniper_signals.jsonl": BASE + "manual/sniper_signals.jsonl",
    "decision: logs/signal_outcomes_regime_backfilled.jsonl": BASE + "logs/signal_outcomes_regime_backfilled.jsonl",
    "decision: manual/trade_scorecards.jsonl": BASE + "manual/trade_scorecards.jsonl",
    "thought : agent_evals/consensus.jsonl": BASE + "agent_evals/consensus.jsonl",
}

JOINKEYS = ("signal_id", "pipeline_id", "cycle_id", "setup_key", "id", "trade_id",
            "position_id", "run_id", "decision_id", "uuid")
TEXTKEYS = ("reasoning", "rationale", "thesis", "analysis", "explanation",
            "signal_context", "context", "notes", "commentary", "thought")


def probe(label, path, limit=4000):
    print(f"\n{'='*78}\n{label}\n{'='*78}")
    n = 0
    keys = collections.Counter()
    joins = collections.Counter()
    texts = collections.Counter()
    textlen = collections.defaultdict(list)
    first = None
    try:
        with io.open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
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
                for k in JOINKEYS:
                    if k in d and d[k] not in (None, "", 0):
                        joins[k] += 1
                for k in TEXTKEYS:
                    v = d.get(k)
                    if isinstance(v, str) and v.strip():
                        texts[k] += 1
                        textlen[k].append(len(v))
                    elif isinstance(v, dict) and v:
                        texts[k + " (dict)"] += 1
                if n >= limit:
                    break
    except FileNotFoundError:
        print("  FILE NOT FOUND")
        return
    print(f"  rows sampled: {n}")
    print(f"  join keys present: {dict(joins) or 'NONE'}")
    print(f"  reasoning/text fields: {dict(texts) or 'NONE'}")
    for k, v in textlen.items():
        print(f"    {k}: mean len {sum(v)//len(v)} chars, max {max(v)}")
    print(f"  all keys: {sorted(keys)[:26]}")
    if first:
        for k in TEXTKEYS:
            if k in first and first[k]:
                s = json.dumps(first[k])[:600]
                print(f"\n  --- sample {k} ---\n  {s}")
                break


for label, path in LAYERS.items():
    probe(label, path)
