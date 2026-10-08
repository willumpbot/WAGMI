"""Mission 2 fallback source: the surviving distilled project memory.

The handoff points at ~/.claude/projects/*/*.jsonl (full transcripts). Those are
GONE -- 0 files survive except today's session. What survives is the memory
layer: 160 .md files written at the time by past sessions, each with a name,
a one-line description and body text, plus ~/.claude/history.jsonl (prompts).

This extracts a structured index: date, source silo, description, and any
verdict-bearing lines (confirmed / refuted / reversed / deployed / live).
"""
import os, re, io, json, collections, datetime

SILOS = {
    "wagmi-archive": "C:/Users/vince/.claude/projects/C--Users-vince-WAGMI-PROJECT-WAGMI/memory",
    "main": "C:/Users/vince/.claude/projects/C--Users-vince/memory",
    "ig-bot": "C:/Users/vince/.claude/projects/C--Users-vince-wagmi-project/memory",
}
HISTORY = "C:/Users/vince/.claude/history.jsonl"
OUT = "C:/Users/vince/WAGMI/bot/data/laptop_mining/"

POS = re.compile(r"\b(confirmed|validated|verified|deployed|shipped|live|works|working|"
                 r"breakthrough|fixed|resolved|survived)\b", re.I)
NEG = re.compile(r"\b(refuted|reversed|wrong|failed|abandoned|reverted|bug|broken|"
                 r"overfit|invalid|noise|no edge|didn'?t work|rolled back|regress)\b", re.I)
NUM = re.compile(r"[-+]?\d+(?:\.\d+)?\s*(?:%|bps|R\b|WR|\$)")

records = []
for silo, path in SILOS.items():
    if not os.path.isdir(path):
        continue
    for fn in sorted(os.listdir(path)):
        if not fn.endswith(".md") or fn == "MEMORY.md":
            continue
        full = os.path.join(path, fn)
        try:
            txt = io.open(full, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        desc = ""
        m = re.search(r"^description:\s*(.+)$", txt, re.M)
        if m:
            desc = m.group(1).strip().strip('"')
        mtype = ""
        m = re.search(r"^\s*type:\s*(\w+)", txt, re.M)
        if m:
            mtype = m.group(1)
        # date: prefer one in the filename, else mtime
        dm = re.search(r"(20\d{2})[_-]?(\d{2})[_-]?(\d{2})", fn)
        if dm:
            date = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"
        else:
            date = datetime.datetime.fromtimestamp(os.path.getmtime(full)).strftime("%Y-%m-%d")
        body = re.sub(r"^---.*?^---", "", txt, flags=re.S | re.M)
        lines = [l.strip(" -*\t") for l in body.splitlines() if l.strip()]
        pos = [l for l in lines if POS.search(l)]
        neg = [l for l in lines if NEG.search(l)]
        nums = [l for l in lines if NUM.search(l)]
        records.append({
            "silo": silo, "file": fn, "date": date, "type": mtype,
            "desc": desc[:200], "bytes": len(txt),
            "pos": len(pos), "neg": len(neg),
            "claim_lines": [l[:230] for l in (nums or pos or lines)[:3]],
            "neg_lines": [l[:230] for l in neg[:2]],
        })

records.sort(key=lambda r: r["date"])
print(f"memory files indexed: {len(records)}")
print(f"  by silo: {dict(collections.Counter(r['silo'] for r in records))}")
print(f"  by type: {dict(collections.Counter(r['type'] or '(none)' for r in records))}")
print(f"  date range: {records[0]['date']} -> {records[-1]['date']}")
print(f"  files containing refutation language: {sum(1 for r in records if r['neg'])}")

print("\n=== by month ===")
for k, v in sorted(collections.Counter(r["date"][:7] for r in records).items()):
    print(f"  {k}: {v:>4}")

with io.open(OUT + "memory_index.json", "w", encoding="utf-8") as fh:
    json.dump(records, fh, indent=1)
print(f"\nwrote memory_index.json ({len(records)} records)")

# --- history.jsonl: what the owner actually asked for, over time ---
print("\n=== ~/.claude/history.jsonl ===")
prompts = []
if os.path.exists(HISTORY):
    with io.open(HISTORY, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            p = d.get("display") or d.get("prompt") or d.get("text") or ""
            ts = d.get("timestamp") or d.get("ts")
            if p:
                prompts.append({"ts": ts, "p": p[:300],
                                "proj": (d.get("project") or "")[-40:]})
print(f"  prompts: {len(prompts)}")
if prompts:
    def norm(t):
        if isinstance(t, (int, float)):
            return datetime.datetime.fromtimestamp(t / 1000 if t > 1e11 else t).strftime("%Y-%m-%d")
        return str(t)[:10]
    months = collections.Counter(norm(p["ts"]) [:7] for p in prompts if p["ts"])
    for k, v in sorted(months.items()):
        print(f"  {k}: {v:>5}")
    with io.open(OUT + "prompt_history.json", "w", encoding="utf-8") as fh:
        json.dump(prompts, fh, indent=0)
    print(f"  wrote prompt_history.json")
