"""Hourly server -> laptop data sync, so the laptop never waits on a human (or on Claude being prompted) for data.

Copies the agreed exports into bot/data/laptop_mining/server_exports/, commits ONLY that directory and pushes the
server branch. The laptop pulls server_exports/ at the start of every session (DATA_REQUEST.md). Never includes
Telegram data (other people's messages). Skips quietly if git is busy (index.lock) or nothing changed.
"""
import shutil
import subprocess
import time
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
EXP = BOT / "data" / "laptop_mining" / "server_exports"
STAMP = EXP / ".last_sync"
EVERY_S = 3600
FILES = {
    "trade_ledger.csv": BOT / "data" / "trade_ledger.csv",
    "trades.csv": BOT / "data" / "trades.csv",
    "position_journal.jsonl": BOT / "data" / "position_journal.jsonl",
    "confidence_state.json": BOT / "data" / "feedback" / "confidence_state.json",
    "execution_analytics.csv": BOT / "data" / "execution_analytics.csv",
    "owner_plans.jsonl": BOT / "data" / "hivemind" / "owner_plans.jsonl",
    "owner_fills.jsonl": BOT / "data" / "hivemind" / "owner_fills.jsonl",
    "plans.json": BOT / "data" / "hivemind" / "plans.json",
    "ai_plans.json": BOT / "data" / "hivemind" / "ai_plans.json",
    "scan_grades.json": BOT / "data" / "hivemind" / "scan_grades.json",
    "scan_log.jsonl": BOT / "data" / "hivemind" / "scan_log.jsonl",
    "chief_calls.jsonl": BOT / "data" / "hivemind" / "chief_calls.jsonl",
    "chief_scorecard.json": BOT / "data" / "hivemind" / "chief_scorecard.json",
    "geometry_shadow.json": BOT / "data" / "hivemind" / "geometry_shadow.json",
    "geometry_shadow_results.jsonl": BOT / "data" / "hivemind" / "geometry_shadow_results.jsonl",
    "uptime.jsonl": BOT / "data" / "hivemind" / "uptime.jsonl",
    "live_scorecard.json": BOT / "data" / "agent_grades" / "live" / "live_scorecard.json",
    "agent_grades_resolved.jsonl": BOT / "data" / "agent_grades" / "live" / "resolved.jsonl",
    "exit_decisions.jsonl": BOT / "data" / "logs" / "exit_decisions.jsonl",
    "llm_exits_resolved.jsonl": BOT / "data" / "llm_exits_resolved.jsonl",
    "position_manager.py": BOT / "execution" / "position_manager.py",
    "scanner.py": BOT / "tools" / "hivemind" / "scanner.py",   # flag definitions, so reviewers can audit them
    "chief.py": BOT / "tools" / "hivemind" / "chief.py",       # chief Brier definition (scorecard())
    "board_decisions.jsonl": BOT / "data" / "hivemind" / "board_decisions.jsonl",   # phone taps on the laptop's board, read by server Claude
    "copilot_call_ledger.jsonl": BOT / "data" / "copilot" / "call_ledger.jsonl",   # forward-proof ledger: timestamps ARE the evidence
    "copilot_call_ledger_resolved.jsonl": BOT / "data" / "copilot" / "call_ledger_resolved.jsonl",
    "entry_mom.jsonl": BOT / "data" / "hivemind" / "entry_mom.jsonl",   # signed_mom_24h per entry (PREREG_ENTRY_TIMING s3)
}


def _gz(path):
    """Write-only gzip with a fixed header timestamp, so unchanged content produces byte-identical files."""
    import gzip
    return gzip.GzipFile(str(path), "wb", mtime=0)   # owns (and closes) its file


# Streams that no API can ever re-serve (audit SERVER_AUDIT_SPOF_2026-10-11): one gz per COMPLETED UTC day, written once.
STREAMS = {
    "liq_events": BOT / "data" / "copilot" / "liquidations" / "liq_events.jsonl",   # Bybit websocket: H3's substrate
    "market_depth": BOT / "data" / "market_depth_history.jsonl",                   # L2 depth/imbalance snapshots
    "whales": BOT / "data" / "hivemind" / "whales_log.jsonl",                      # HL whale net positions
    "voices": BOT / "data" / "hivemind" / "voice_log.jsonl",                       # every voice reading, 15 min
}
ARCH_STAMP = BOT / "data" / "hivemind" / ".stream_archive_day"


def _day(line):
    """UTC date of a stream row from its ts/ts_utc field (epoch seconds or ISO string)."""
    import json as _json
    from datetime import datetime, timezone
    o = _json.loads(line)
    t = o.get("ts_utc") or o.get("ts") or o.get("timestamp")
    if isinstance(t, (int, float)):
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
    return str(t)[:10]


def _archive_streams():
    """Once per UTC day: shard each stream into EXP/archive/<name>/<day>.jsonl.gz for days that are complete and not
    yet written. Past days never change, so each shard is committed exactly once."""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        if ARCH_STAMP.read_text().strip() == today:
            return
    except OSError:
        pass
    for name, src in STREAMS.items():
        if not src.exists():
            continue
        dst = EXP / "archive" / name
        dst.mkdir(parents=True, exist_ok=True)
        have = {f.name[:10] for f in dst.glob("*.jsonl.gz")}
        cur, fo = None, None
        with open(src, encoding="utf-8", errors="replace") as fi:
            for ln in fi:
                if not ln.strip():
                    continue
                try:
                    d = _day(ln)
                except Exception:
                    continue
                if d >= today or d in have:
                    continue
                if d != cur:
                    if fo:
                        fo.close()
                    # rows are appended in time order; a day seen again later (rare) goes to its own .partN shard
                    n, path = 0, dst / f"{d}.jsonl.gz"
                    while path.exists():
                        n += 1
                        path = dst / f"{d}.part{n}.jsonl.gz"
                    cur, fo = d, _gz(path)
                fo.write(ln.encode("utf-8") if ln.endswith(chr(10)) else (ln + chr(10)).encode("utf-8"))
        if fo:
            fo.close()
    ARCH_STAMP.write_text(today)


def _git(*args):
    return subprocess.run(["git", *args], cwd=BOT, capture_output=True, text=True, timeout=120)


def run(force=False):
    try:
        if not force and time.time() - float(STAMP.read_text()) < EVERY_S:
            return "not due"
    except (OSError, ValueError):
        pass
    if (BOT.parent / ".git" / "index.lock").exists():
        return "git busy"
    _git("fetch", "-q", "origin", "laptop-mining-2026-10")   # so the Brief sees the laptop's latest files
    EXP.mkdir(parents=True, exist_ok=True)
    for name, src in FILES.items():
        if src.exists():
            shutil.copy2(src, EXP / name)
    snap_src, snap_dst = BOT / "data" / "ctx_snapshots", EXP / "ctx_snapshots"   # OI/premium/impact, all perps (30 days)
    if snap_src.exists():
        snap_dst.mkdir(exist_ok=True)
        keep = sorted(snap_src.glob("*.jsonl.gz"))[-30:]
        for f in keep:
            shutil.copy2(f, snap_dst / f.name)
        for f in snap_dst.glob("*.jsonl.gz"):
            if f.name not in {k.name for k in keep}:
                f.unlink()
    c5_src, c5_dst = BOT / "data" / "candles_5m", EXP / "candles_5m"   # 5m HL candles archived since 2026-10-09
    if c5_src.exists():
        c5_dst.mkdir(exist_ok=True)
        for f in c5_src.glob("*.jsonl"):
            shutil.copy2(f, c5_dst / f.name)
    try:   # gate/floor lines from the bot logs + funding history. Rebuilt only when a source changed, and written
        # with mtime=0 so identical content gives identical bytes (otherwise git recommits ~4 MB of the same data hourly)
        logs = sorted((BOT / "logs").glob("bot_2026*.log"))
        newest = max((f.stat().st_mtime for f in logs), default=0)
        for out, keep in (("floor_decisions_log.jsonl.gz", ("Feedback floor PASSED", "Feedback floor BLOCKED")),
                          # the gates that actually decide entries in LLM-first mode (floor bypassed there since June)
                          ("entry_gate_log.jsonl.gz", ("[ENTRY-GATE]", "[PROBE-CHECK]", "LLM-FIRST SKIP",
                                                       "EXPLORATION ENTRY", "EXPLORATION DECLINED"))):
            if (EXP / out).exists() and (EXP / out).stat().st_mtime >= newest:
                continue
            with _gz(EXP / out) as fo:
                for lf in logs:
                    with open(lf, encoding="utf-8", errors="replace") as fi:
                        for ln in fi:
                            if any(k in ln for k in keep):
                                fo.write(ln.encode("utf-8"))
        # funding/OI/premium snapshots the bot has collected since 2026-06-06 (31 coins), for the fade-funding question
        src = BOT / "data" / "funding_oi_history.jsonl"
        if not (EXP / "funding_oi_history.jsonl.gz").exists() or (EXP / "funding_oi_history.jsonl.gz").stat().st_mtime < src.stat().st_mtime:
            with open(src, "rb") as fi, _gz(EXP / "funding_oi_history.jsonl.gz") as fo:
                shutil.copyfileobj(fi, fo)
    except Exception:
        pass
    try:
        _archive_streams()
    except Exception:
        pass
    try:   # anonymised Syndicate call list (public CAs + times + hashed caller) for the laptop's M3 / crunch layer
        import hashlib
        import json as _json
        import sys as _sys
        _sys.path.insert(0, str(BOT / "tools" / "hivemind"))
        import syndicate_study as _ss
        rec = (_json.loads((BOT / "data" / "hivemind" / "tg" / "track.json").read_text(encoding="utf-8")).get("callers") or {})
        with open(EXP / "syndicate_calls_anon.jsonl", "w", encoding="utf-8") as f:
            for c in _ss.first_calls(30):
                f.write(_json.dumps({"ca": c["ca"], "call_ts": int(c["ts"]),
                                     "caller_hash": hashlib.sha256((c["caller"] or "bot").encode()).hexdigest()[:10],
                                     "starred": bool((rec.get(c["caller"]) or {}).get("watch")),
                                     "first_seen_via_bot_alert": c["bot_first"]}) + chr(10))
    except Exception:
        pass
    STAMP.write_text(str(time.time()))
    rel = str(EXP.relative_to(BOT))
    _git("add", "-f", "--", rel)
    if not _git("diff", "--cached", "--quiet", "--", rel).returncode:
        return "no changes"
    c = _git("commit", "-m", "Hourly server exports for the laptop (auto)", "--", rel)
    if c.returncode:
        return "commit failed: " + c.stderr[-200:]
    p = _git("push", "-q", "origin", "HEAD")
    return "pushed" if not p.returncode else "push failed: " + p.stderr[-200:]


if __name__ == "__main__":
    import sys
    print(run(force="--force" in sys.argv))
