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
    "owner_plan_sims.json": BOT / "data" / "hivemind" / "owner_plan_sims.json",   # every owner plan played out on 5m, any coin
    "owner_plan_sims_resolved.jsonl": BOT / "data" / "hivemind" / "owner_plan_sims_resolved.jsonl",   # append-only, one row per finished plan
    "dissent_log.jsonl": BOT / "data" / "hivemind" / "dissent_log.jsonl",
    "cases_index.json": BOT / "data" / "hivemind" / "cases" / "index.json",
    "wallet_snapshots.jsonl": BOT / "data" / "hivemind" / "wallets" / "snapshots.jsonl",   # per-trade case index (full files on request)   # live stage-2 dissent input per coin per cycle (M3)
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
    "expmove_log.jsonl": BOT / "data" / "hivemind" / "expmove_log.jsonl",   # exp_move vs rv5 per coin-day (laptop reply 54)
    "call_snapshots.jsonl": BOT / "data" / "hivemind" / "tg" / "call_snapshots.jsonl",   # public call-time pool state (no caller/text)
    "stop_shadow.json": BOT / "data" / "hivemind" / "stop_shadow.json",   # live 5m shadow stops per bot entry (X2 follow-up)
    # board_feed.json retired 2026-10-13 (owner: hivemind core before any board surface); last copy stays in exports
    "discrepancies.json": BOT / "data" / "knowledge" / "discrepancies.json",   # HIVEMIND D1-D11 findings, hourly
    "entry_mom.jsonl": BOT / "data" / "hivemind" / "entry_mom.jsonl",   # signed_mom_24h per entry (PREREG_ENTRY_TIMING s3)
    # 10-15 angle map 5b: collected on the server but never exported
    "signal_value_tracker.jsonl": BOT / "data" / "manual" / "signal_value_tracker.jsonl",
    "trade_reflections.jsonl": BOT / "data" / "reflections" / "trade_reflections.jsonl",
    "veto_tracker.json": BOT / "data" / "llm" / "growth" / "veto_tracker.json",   # Critic veto outcomes (+18.6 bps lead)
    "calibration_observations.jsonl": BOT / "data" / "llm" / "calibration_observations.jsonl",
    "nearmiss_reversion_log.jsonl": BOT / "data" / "copilot" / "nearmiss_reversion_log.jsonl",
    "copilot_alerts.log": BOT / "data" / "copilot" / "alerts.log",   # ~11k fired alerts, never graded
    "voice_grades.json": BOT / "data" / "hivemind" / "voice_grades.json",
    "accumulation_log.jsonl": BOT / "data" / "reports" / "accumulation_log.jsonl",
    "owner_plan_reviews.jsonl": BOT / "data" / "hivemind" / "owner_plan_reviews.jsonl",
    "owner_watchlist.json": BOT / "data" / "hivemind" / "owner_watchlist.json",
    "watch_log.jsonl": BOT / "data" / "hivemind" / "watch_log.jsonl",
    "promoted_log.jsonl": BOT / "data" / "hivemind" / "promoted_log.jsonl",   # scanner movers promoted to the full read (grade them)
    "state_transitions.csv": BOT / "data" / "logs" / "state_transitions.csv",
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
    "depth_all": BOT / "data" / "hivemind" / "depth_all.jsonl",                    # L2 bands, all ~178 perps, 15 min
    "wallets": BOT / "data" / "hivemind" / "wallets" / "positions.jsonl",      # ~1,200 wallets' positions >= $5k, hourly
    "pool_trades": BOT / "data" / "hivemind" / "tg" / "pool_trades.jsonl",        # wallets trading called pools (call/h1/h6)
    "venue_funding": BOT / "data" / "hivemind" / "venue_funding.jsonl",            # HL/Binance/Bybit funding per hour + HL OI-cap list, 15 min
}
LEARNED_STATE = ["epoch_start.json", "ic_history.json", "position_state.json", "feedback/signal_quality.json",
                 "feedback/regime_feedback_state.json", "llm/agent_calibration.json", "llm/neuroplasticity_state.json",
                 "llm/network_learning.json", "llm/active_learning.json", "llm/agent_performance.json"]
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
    # The bot's learned state (<1 MB, rewritten constantly): one daily copy is enough - git history keeps every day,
    # and a dead disk no longer means every learning loop cold-starts and the epoch baseline is lost (SPOF audit #4).
    st = EXP / "state"
    st.mkdir(exist_ok=True)
    for rel in LEARNED_STATE:
        src = BOT / "data" / rel
        if src.exists():
            shutil.copy2(src, st / rel.replace("/", "__"))
    _archive_appends(today)
    ARCH_STAMP.write_text(today)


# The bot's own big logs (owner 10-12: "send everything to the laptop"). Shards by what was APPENDED since the last
# run, not by row date: several files append rows long after the date stamped on them (resolutions), so date-sharding
# would silently drop those. State = byte offset per file; a file that shrinks (rewritten/rotated) restarts at 0
# and its shard is marked .rewrite so the laptop can dedupe.
APPENDS = {n: BOT / "data" / r for n, r in {
    "decisions": "llm/decisions.jsonl", "counterfactual_resolved": "llm/counterfactual_resolved.jsonl",
    "agent_performance": "llm/agent_performance.jsonl", "thesis_history": "llm/thesis_history.jsonl",
    "trade_events": "trade_events.jsonl", "sniper_rejections": "manual/sniper_rejections.jsonl",
    "missed_trades": "missed_trades.jsonl", "missed_trades_resolved": "missed_trades_resolved.jsonl",
    "graded_decisions": "agent_grades/graded_decisions.jsonl", "microcap_wash": "microcap/wash_signal.jsonl",
    "microcap_flow": "microcap/flow_signal.jsonl", "microcap_liquidity": "microcap/liquidity_snapshots.jsonl",
    "microcap_discovery": "microcap/discovery_log.jsonl", "exit_closes": "logs/exit_closes.jsonl",
    "signal_outcomes": "logs/signal_outcomes.jsonl", "exit_regret": "logs/exit_regret_scores.jsonl",
    "safety_events": "logs/safety_events.jsonl"}.items()}
APPEND_STATE = BOT / "data" / "hivemind" / ".append_offsets.json"


def _archive_appends(today):
    import json as _json
    try:
        st = _json.loads(APPEND_STATE.read_text(encoding="utf-8"))
    except Exception:
        st = {}
    for name, src in APPENDS.items():
        if not src.exists():
            continue
        size, off = src.stat().st_size, int(st.get(name, 0))
        tag = ""
        if size < off:
            off, tag = 0, ".rewrite"
        if size == off:
            continue
        # copy only up to the LAST complete line, so a row being written right now goes into tomorrow's shard whole
        with open(src, "rb") as fi:
            fi.seek(max(off, size - 65536))
            tail = fi.read(size - max(off, size - 65536))
        cut = tail.rfind(b"\n")
        if cut < 0:
            continue
        end = max(off, size - 65536) + cut + 1
        dst = EXP / "bulk" / name
        dst.mkdir(parents=True, exist_ok=True)
        with open(src, "rb") as fi, _gz(dst / f"{today}{tag}.jsonl.gz") as fo:
            fi.seek(off)
            left = end - off
            while left > 0:
                chunk = fi.read(min(1 << 20, left))
                if not chunk:
                    break
                fo.write(chunk)
                left -= len(chunk)
        st[name] = end
    APPEND_STATE.write_text(_json.dumps(st), encoding="utf-8")


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
            # APPEND-ONLY: keep every row already exported (earlier one-off exports used broader filters, and old logs
            # may rotate away) and add only new matches. Never rebuild from a re-grep alone: that destroyed 95% of
            # floor_decisions_log for 14 syncs on 10-11 (laptop 482ed65b).
            import gzip as _gz_mod
            rows, seen = [], set()
            if (EXP / out).exists():
                with _gz_mod.open(EXP / out, "rt", encoding="utf-8", errors="replace") as fi:
                    for ln in fi:
                        if ln not in seen:
                            seen.add(ln)
                            rows.append(ln)
            for lf in logs:
                with open(lf, encoding="utf-8", errors="replace") as fi:
                    for ln in fi:
                        if any(k in ln for k in keep):
                            ln = ln if ln.endswith(chr(10)) else ln + chr(10)
                            if ln not in seen:
                                seen.add(ln)
                                rows.append(ln)
            rows.sort(key=lambda l: l[:40])   # lines start with {"ts": "<iso>": sorts chronologically
            with _gz(EXP / out) as fo:
                for ln in rows:
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
        # APPEND-ONLY by ca: calls that age out of the 30-day window stay in the export (laptop j4 flagged the drop)
        path, rows = EXP / "syndicate_calls_anon.jsonl", {}
        if path.exists():
            for ln in path.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    o = _json.loads(ln)
                    rows[o["ca"]] = o
        for c in _ss.first_calls(30):
            rows[c["ca"]] = {"ca": c["ca"], "call_ts": int(c["ts"]),
                             "caller_hash": hashlib.sha256((c["caller"] or "bot").encode()).hexdigest()[:10],
                             "starred": bool((rec.get(c["caller"]) or {}).get("watch")),
                             "first_seen_via_bot_alert": c["bot_first"]}
        with open(path, "w", encoding="utf-8") as f:
            for o in sorted(rows.values(), key=lambda o: o["call_ts"]):
                f.write(_json.dumps(o) + chr(10))
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
