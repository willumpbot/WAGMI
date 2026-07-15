#!/usr/bin/env python
"""WAGMI external daily digest — read-only, LLM-FREE, ZERO trading-path contact.

Sends the owner ONE Telegram summary/day from source data files, so being "away"
doesn't mean being blind. Runs OUTSIDE the bot process (Task Scheduler
WAGMI-DailyDigest), so it also doubles as a tripwire: if the bot is down, the
digest still fires and says "heartbeat STALE — bot may be down". Complements the
in-process 08:00 briefing (which omits call volume / degrade / collector / CB
state and is silent if the bot is down).

Reads only: heartbeat.json, data/llm/agent_costs.json, circuit_breaker_state.json,
position_state.json, trades.csv, and the two collector jsonl tails. Writes nothing
except stdout. Plain-text Telegram (no Markdown) so no message can fail on a stray
character.

Register:  Task Scheduler WAGMI-DailyDigest (daily ~20:00 UTC).
Revert:    schtasks /delete /tn WAGMI-DailyDigest /f   (and delete this file).
"""
import os
import csv
import json
import datetime
import urllib.request

BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # -> bot/
DATA = os.path.join(BOT_DIR, "data")


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _last_ts_age_min(path, keys, now_ts):
    """Age (min) of the last record in a jsonl file, or None. Tail-read only."""
    try:
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            f.seek(0, 2)
            sz = f.tell()
            f.seek(max(0, sz - 8192))
            tail = f.read().decode("utf-8", "ignore")
        rec = None
        for line in reversed([x for x in tail.splitlines() if x.strip()]):
            try:
                rec = json.loads(line)
                break
            except Exception:
                continue
        if not isinstance(rec, dict):
            return None
        ts = next((rec[k] for k in keys if k in rec), None)
        if ts is None:
            return None
        d = datetime.datetime.fromisoformat(str(ts).strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return (now_ts - d.timestamp()) / 60.0
    except Exception:
        return None


def _today_trades(today):
    """(n, wins, losses, total_pnl) from trades.csv for UTC date string `today`."""
    n = w = l = 0
    pnl = 0.0
    try:
        with open(os.path.join(DATA, "trades.csv"), newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not str(row.get("timestamp", "")).startswith(today):
                    continue
                n += 1
                try:
                    p = float(row.get("pnl") or 0)
                except Exception:
                    p = 0.0
                pnl += p
                if p > 0:
                    w += 1
                elif p < 0:
                    l += 1
    except Exception:
        pass
    return n, w, l, pnl


def _load_env_from_file():
    """Load TELEGRAM_* from bot/.env WITHOUT python-dotenv (not installed here).
    The bot gets these via the supervisor injecting env at launch; a bare Task
    Scheduler process does not, so parse the file directly."""
    try:
        with open(os.path.join(BOT_DIR, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                if k.startswith(("TELEGRAM_", "DISCORD_")) and not os.getenv(k):
                    os.environ[k] = v.strip().strip('"').strip("'")
    except Exception:
        pass


def _write_report(msg, now):
    """Always persist the digest to disk — the reliable channel when no push
    channel is configured (owner reads via the ops log / a phone Claude session)."""
    try:
        rdir = os.path.join(DATA, "reports")
        os.makedirs(rdir, exist_ok=True)
        with open(os.path.join(rdir, "daily_digest_latest.txt"), "w", encoding="utf-8") as f:
            f.write(msg + "\n")
        with open(os.path.join(rdir, "daily_digest_log.txt"), "a", encoding="utf-8") as f:
            f.write("\n" + "=" * 60 + "\n" + msg + "\n")
        return True
    except Exception:
        return False


def send_discord(msg):
    hook = os.getenv("DISCORD_WEBHOOK", "")
    if not hook:
        _load_env_from_file()
        hook = os.getenv("DISCORD_WEBHOOK", "")
    if not hook:
        return False
    try:
        data = json.dumps({"content": msg[:1900]}).encode("utf-8")
        req = urllib.request.Request(hook, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"[digest] discord send failed: {e}")
        return False


def send_telegram(msg):
    token = os.getenv("TELEGRAM_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        _load_env_from_file()
        token = os.getenv("TELEGRAM_TOKEN", "")
        chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("[digest] Telegram not configured (TELEGRAM_TOKEN/CHAT_ID)")
        return False
    try:
        data = json.dumps({"chat_id": chat, "text": msg}).encode("utf-8")  # plain text
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data, headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"[digest] send failed: {e}")
        return False


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.strftime("%Y-%m-%d")
    hb = _read_json(os.path.join(DATA, "heartbeat.json"))
    costs = _read_json(os.path.join(DATA, "llm", "agent_costs.json"))
    cb = _read_json(os.path.join(DATA, "circuit_breaker_state.json"))
    pos = _read_json(os.path.join(DATA, "position_state.json"))

    hb_age = "n/a"
    hb_flag = ""
    try:
        la = hb.get("last_alive")
        if la:
            d = datetime.datetime.fromisoformat(str(la).replace("Z", "+00:00"))
            am = (now - d).total_seconds() / 60.0
            hb_age = f"{am:.0f}m"
            if am > 10:
                hb_flag = "  !! STALE — BOT MAY BE DOWN"
    except Exception:
        pass

    n, w, l, pnl = _today_trades(today)
    depth_age = _last_ts_age_min(os.path.join(DATA, "market_depth_history.jsonl"), ("ts", "timestamp"), now.timestamp())
    fund_age = _last_ts_age_min(os.path.join(DATA, "funding_oi_history.jsonl"), ("timestamp", "ts"), now.timestamp())

    def fmt_age(a):
        return "n/a" if a is None else (f"{a:.0f}m" + (" !!STALE" if a > 45 else ""))

    pdict = pos.get("positions", pos) if isinstance(pos, dict) else {}
    plines = []
    if isinstance(pdict, dict):
        for s, v in pdict.items():
            try:
                if isinstance(v, dict) and float(v.get("qty", 0) or 0) != 0:
                    plines.append(f"{s} {v.get('side', '')}")
            except Exception:
                continue

    try:
        eq = f"${float(hb.get('equity', 0)):.2f}"
    except Exception:
        eq = str(hb.get("equity", "?"))
    up = hb.get("uptime_s", 0) or 0
    degraded = bool(hb.get("llm_first_degraded", False))

    lines = [
        f"WAGMI Daily Digest — {now.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"Equity: {eq}   Uptime: {up/3600:.1f}h   Scans: {hb.get('scan_count', '?')}",
        f"Heartbeat: {hb_age} old{hb_flag}",
        f"Errors: {hb.get('errors', '?')}   LLM degraded: {'YES !!' if degraded else 'no'}",
        f"Trades today: {n} ({w}W/{l}L)   PnL today: ${pnl:+.2f}",
        f"Circuit breaker: {'TRIPPED !! ' + str(cb.get('trip_reason', '')) if cb.get('tripped') else 'ok'}"
        f"   Consec losses: {cb.get('consecutive_losses', '?')}",
        f"LLM calls today: {costs.get('today_calls', '?')} (${costs.get('today_spend', 0):.3f} tracked;"
        f" CLI/subscription usage undercounted)",
        f"Collectors: depth {fmt_age(depth_age)}, funding {fmt_age(fund_age)}",
        f"Open positions ({len(plines)}): {', '.join(plines) if plines else 'none'}",
    ]
    msg = "\n".join(lines)
    written = _write_report(msg, now)
    tg = send_telegram(msg)
    dc = send_discord(msg)
    print(msg)
    print(f"[digest] written_to_file={written} telegram_sent={tg} discord_sent={dc}")
    if not (tg or dc):
        print("[digest] NOTE: no push channel configured (TELEGRAM_*/DISCORD_* empty in .env). "
              "Digest saved to data/reports/daily_digest_latest.txt only. "
              "Add a Discord webhook or Telegram token+chat_id to .env to receive pushes.")


if __name__ == "__main__":
    main()
