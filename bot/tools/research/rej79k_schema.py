import json, collections
path = r"C:\Users\vince\WAGMI\bot\data\manual\sniper_rejections.jsonl"
keys = collections.Counter(); reasons = collections.Counter(); n = 0
first = None; last = None
days = collections.Counter(); syms = collections.Counter()
sample = []
bad = 0
for i, line in enumerate(open(path, encoding="utf-8")):
    line = line.strip()
    if not line:
        continue
    try:
        r = json.loads(line)
    except Exception:
        bad += 1
        continue
    n += 1
    for k in r:
        keys[k] += 1
    reasons[r.get("reason", "?")] += 1
    ts = r.get("timestamp", "")
    if first is None:
        first = ts
    last = ts
    days[ts[:10]] += 1
    syms[r.get("symbol", "?")] += 1
    if n % 1600 == 1 and len(sample) < 50:
        sample.append(r)
print("n =", n, "bad_lines =", bad)
print("keys:", dict(keys))
print("first:", first, "last:", last)
print("reasons:")
for k, v in reasons.most_common():
    print("  %-40s %d" % (k, v))
print("symbols:", dict(syms.most_common(20)))
print("num_days:", len(days))
for d, v in sorted(days.items()):
    print(" ", d, v)
print("--- 5 raw sample records ---")
for r in sample[:5]:
    print(json.dumps(r))
