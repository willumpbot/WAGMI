"""Shared helpers for the knowledge registry (HIVEMIND Phase 0).

The registry lives in bot/knowledge/ (one small JSON card per claim / definition / rule, plus bindings.json and
threads.json). This module holds the bits every tool needs: where things are, the status -> wording-tier table, how
to load cards, and how to hash a piece of code so a card can say "this is the exact code that was tested".

Read-only on everything outside bot/knowledge/ (the seeder writes cards, check.py writes one report file).
"""
import ast
import hashlib
import json
import re
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
KNOWLEDGE = BOT / "knowledge"
DATA = BOT / "data"

# ---------------------------------------------------------------------------------------------------------------
# Status set (brief section 2) and the strongest wording any surface may use for each.
#   rank: how strong a statement the status allows. A display that asserts more than its claim's rank is a D1 hit.
# ---------------------------------------------------------------------------------------------------------------
STATUSES = ["HYPOTHESIS", "PREREG_SEALED", "POSITIVE_UNDERPOWERED", "SUPPORTED", "REPLICATED", "PROVEN",
            "UNDERPOWERED", "REFUTED", "RETRACTED", "STALE", "RETIRED"]

WORDING_TIER = {            # status -> wording tier (the label surfaces must not exceed)
    "PROVEN": "proven",          # "shown", "tested", "proven" allowed
    "POSITIVE_UNDERPOWERED": "leaning",  # "leans positive, not enough data yet" - CI excludes 0 but effect < its MDE
    "SUPPORTED": "supported",    # "evidence suggests", "so far"
    "REPLICATED": "replicated",  # "held up on data it was never fitted on" - one out-of-sample replication, not PROVEN
    "PREREG_SEALED": "sealed",   # "being tested; sealed, reads at N" (no running tally - laptop answer 10)
    "HYPOTHESIS": "hypothesis",  # "idea, untested"
    "UNDERPOWERED": "unknown",   # "can't tell yet"
    "REFUTED": "refuted",        # "doesn't work"
    "RETRACTED": "refuted",      # "withdrawn; the earlier result was an error"
    "STALE": "stale",            # "was true in <era>; not current" - may not bind (laptop amendment 3)
    "RETIRED": "stale",
}
TIER_RANK = {"refuted": 0, "stale": 1, "hypothesis": 2, "unknown": 2, "sealed": 2, "leaning": 2.5, "supported": 3, "replicated": 3.5, "proven": 4}

# Statuses a live rule may never bind to (laptop amendment 3: expiry by default, renewal by evidence).
DEAD_STATUSES = {"STALE", "RETIRED", "REFUTED", "RETRACTED"}


def tier_for(status):
    return WORDING_TIER.get(status, "hypothesis")


def negation_tier(status):
    """Tier of the statement 'this claim is FALSE'. A REFUTED claim makes its negation proven-grade; anything that
    merely failed to show an effect (UNDERPOWERED) does not."""
    if status in ("REFUTED", "RETRACTED"):
        return "proven"
    if status == "UNDERPOWERED":
        return "unknown"
    return "hypothesis"


# ---------------------------------------------------------------------------------------------------------------
# Card IO
# ---------------------------------------------------------------------------------------------------------------
def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path, obj):
    """Stable, diff-friendly JSON (sorted keys off: cards keep their authored field order)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_cards(kind, root=None):
    """All cards of one kind ('claims' / 'definitions' / 'rules') as {id: card}."""
    root = Path(root or KNOWLEDGE)
    out = {}
    for p in sorted((root / kind).glob("*.json")):
        c = load_json(p)
        if isinstance(c, dict):
            out[c.get("id") or c.get("name") or p.stem] = c
    return out


def load_registry(root=None):
    root = Path(root or KNOWLEDGE)
    return {"claims": load_cards("claims", root), "definitions": load_cards("definitions", root),
            "rules": load_cards("rules", root), "bindings": load_json(root / "bindings.json", {}) or {},
            "threads": load_json(root / "threads.json", {}) or {}}


def slug(text, maxlen=48):
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s[:maxlen].rstrip("_") or "x"


# ---------------------------------------------------------------------------------------------------------------
# Code hashing (impl_hash). An impl spec says WHICH code a definition means:
#   {"path": "tools/hivemind/volforecast.py", "function": "forecast"}           a def (or "Class.method")
#   {"path": "...", "start": "<regex>", "end": "<regex>"}                       first start-line .. next end-line
#   {"path": "...", "pattern": "<regex>"}                                        the first matching line
# Paths are relative to bot/. The hash is sha256 of the exact source text (line endings normalised), so ANY edit
# to that code changes it - that is the point (D4: live code != tested code).
# ---------------------------------------------------------------------------------------------------------------
def _read_src(path, root=None):
    p = Path(root or BOT) / path
    return p.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")


def function_source(src, qualname):
    """Source of a top-level function or Class.method, via ast (None if not found)."""
    tree = ast.parse(src)
    parts = qualname.split(".")
    nodes = tree.body
    found = None
    for i, name in enumerate(parts):
        found = None
        for n in nodes:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name:
                found = n
                break
        if found is None:
            return None
        nodes = getattr(found, "body", [])
    return ast.get_source_segment(src, found)


def impl_source(spec, root=None):
    """The code text an impl spec points at, or None when it can't be found (the card is then out of date)."""
    try:
        src = _read_src(spec["path"], root)
    except OSError:
        return None
    if spec.get("function"):
        try:
            return function_source(src, spec["function"])
        except SyntaxError:
            return None
    lines = src.split("\n")
    if spec.get("start"):
        s_re, e_re = re.compile(spec["start"]), re.compile(spec.get("end") or spec["start"])
        for i, ln in enumerate(lines):
            if s_re.search(ln):
                for j in range(i, len(lines)):
                    if e_re.search(lines[j]) and (j > i or not spec.get("end")):
                        return "\n".join(lines[i:j + 1])
                return None
        return None
    if spec.get("pattern"):
        p_re = re.compile(spec["pattern"])
        for ln in lines:
            if p_re.search(ln):
                return ln.strip()
    return None


def impl_hash(spec, root=None):
    text = impl_source(spec, root)
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def impl_line(spec, root=None):
    """1-based line where the spec's code starts (for file:line in reports)."""
    text = impl_source(spec, root)
    if not text:
        return None
    try:
        src = _read_src(spec["path"], root)
    except OSError:
        return None
    idx = src.find(text.split("\n")[0])
    return src[:idx].count("\n") + 1 if idx >= 0 else None


# ---------------------------------------------------------------------------------------------------------------
# Small file readers for big append-only streams (never load a 50 MB jsonl just to see its last row).
# ---------------------------------------------------------------------------------------------------------------
def tail_lines(path, n=50, block=65536):
    """Last n non-empty lines of a text file, reading backwards from the end."""
    path = Path(path)
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        data, pos = b"", size
        while pos > 0 and data.count(b"\n") <= n:
            step = min(block, pos)
            pos -= step
            f.seek(pos)
            data = f.read(step) + data
    lines = [ln for ln in data.decode("utf-8", errors="replace").split("\n") if ln.strip()]
    if pos > 0 and lines:
        lines = lines[1:]          # first line may be cut mid-row
    return lines[-n:]


def head_lines(path, n=5):
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            if ln.strip():
                out.append(ln)
                if len(out) >= n:
                    break
    return out


def row_epoch(row, ts_field=None):
    """Epoch seconds of a stream row from ts / ts_utc / timestamp (epoch s, epoch ms or ISO string)."""
    from datetime import datetime, timezone
    t = row.get(ts_field) if ts_field else None
    if t is None:
        for k in ("ts_utc", "ts", "timestamp", "time"):
            if row.get(k) is not None:
                t = row[k]
                break
    if t is None:
        return None
    if isinstance(t, (int, float)) or (isinstance(t, str) and re.fullmatch(r"\d+(\.\d+)?", t)):
        t = float(t)
        return t / 1000.0 if t > 1e11 else t
    try:
        d = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d.timestamp()
    except ValueError:
        return None


def flatten_fields(obj, prefix="", map_keys=()):
    """Dotted field names of a JSON row. Keys listed in map_keys are maps keyed by data (e.g. coin names), so their
    children collapse to '<key>.*'; lists become '[i]' positions (whales rows are positional)."""
    out = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            name = f"{prefix}{k}"
            if k in map_keys and isinstance(v, dict):
                sub = set()
                for vv in v.values():
                    sub |= flatten_fields(vv, name + ".*", map_keys)
                out |= sub or {name + ".*"}
            else:
                out |= flatten_fields(v, name + ".", map_keys) if isinstance(v, (dict, list)) else {name}
    elif isinstance(obj, list):
        base = prefix[:-1] if prefix.endswith(".") else prefix
        for i, v in enumerate(obj[:8]):
            out |= flatten_fields(v, f"{base}[{i}].", map_keys) if isinstance(v, (dict, list)) else {f"{base}[{i}]"}
        if not obj:
            out.add(base)
    return out


def read_env(path):
    """KEY=value pairs from a .env file (inline '# comments' stripped). Read-only."""
    out = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        v = re.split(r"\s+#", v, maxsplit=1)[0].strip().strip('"').strip("'")
        out[k.strip()] = v
    return out
