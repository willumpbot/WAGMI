#!/usr/bin/env python3
"""
Builds a calm, plain-language status page answering one question:
"What is my system doing right now, and does anything need me?"

Design rules (deliberate, do not "tidy" these away):
  - The headline answers the question. Everything else is detail you may ignore.
  - Never show an error code without translating it into plain English.
  - Section order is FIXED. Items never reorder between refreshes, so your eye
    can learn where things live and stop re-scanning.
  - No animation, no flashing, no alarm-red. Calm at 3am and at noon.
  - "Nothing is wrong" is stated explicitly, never implied by blank space.
  - Anything wrong comes with the exact next action, not a diagnosis.
"""
import json
import subprocess
import time
import html
from datetime import datetime, timezone
from pathlib import Path

BOT = Path(r"C:\Users\vince\WAGMI\bot")
OUT = Path(r"C:\Users\vince\WAGMI\dashboard.html")

# Windows task exit codes, translated. status: ok | running | attn
RC = {
    0x0: ("ok", "Finished cleanly."),
    0x41301: ("running", "Running right now."),
    0x41303: ("ok", "Scheduled; it hasn't had its first run yet."),
    0x41300: ("ok", "Ready, waiting for its next scheduled time."),
    0x41306: ("ok", "Was stopped normally."),
    0xC000013A: ("attn", "Its console window got closed. This is the one that keeps "
                         "biting you - run cleanup_admin.ps1 and it can't happen again."),
    0x80070002: ("attn", "Couldn't find the program it was told to run. Usually a task "
                         "calling bare 'python' instead of the full path."),
    0x800710E0: ("attn", "Windows refused it because of a power setting. Should be fixed "
                         "now - tell me if you see it again."),
    0x1: ("attn", "The script it ran reported a problem."),
    0x2: ("attn", "A file it needed is missing."),
}

# What is running and WHY, in plain words. Substring match, first hit wins.
WHY = [
    ("run.py", "bot", "Your trading bot", "This is the bot itself, watching the market."),
    ("api_server", "bot", "Bot's data server", "Feeds your website and this dashboard the bot's numbers."),
    ("watchdog", "bot", "Bot's watchdog", "Watches the bot and shouts if it dies."),
    ("tunnel_manager", "bot", "Website tunnel keeper", "Keeps your website connected to this computer."),
    ("cloudflared", "bot", "The tunnel itself", "The actual pipe your website talks through."),
    ("collector", "bot", "Data collector", "Quietly saving market data you can't get back later."),
    ("copilot", "bot", "Co-pilot tool", "One of your analyst tools doing a scheduled run."),
    ("research", "bot", "Research job", "A scheduled research script crunching your trade history."),
    ("claude", "yours", "Claude Code", "Me. This is the session you talk to."),
    ("windowsterminal", "yours", "Your terminal window", "The window Claude runs inside."),
    ("openconsole", "yours", "Terminal plumbing", "Part of your terminal window."),
    ("powershell", "yours", "PowerShell", "A command runner - yours, or one of the bot's tasks."),
    ("python", "yours", "Python", "A Python script, probably one of the bot's scheduled tasks."),
    ("msmpeng", "windows", "Windows Defender", "Your antivirus. Leave it alone."),
    ("nissrv", "windows", "Defender network check", "Part of your antivirus."),
    ("mpdefender", "windows", "Defender core", "Part of your antivirus."),
    ("explorer", "windows", "Your desktop", "The taskbar, desktop and file windows."),
    ("dwm", "windows", "Window drawing", "Draws every window on screen. Essential."),
    ("csrss", "windows", "Windows core", "Core Windows. Cannot be closed."),
    ("wininit", "windows", "Windows core", "Core Windows. Cannot be closed."),
    ("winlogon", "windows", "Windows login", "Core Windows. Cannot be closed."),
    ("services.exe", "windows", "Service manager", "Starts and stops Windows services."),
    ("svchost", "windows", "Windows background service", "Windows runs dozens of these. Normal."),
    ("searchhost", "windows", "Start menu search", "The search box in your Start menu."),
    ("startmenu", "windows", "Start menu", "Your Start menu."),
    ("shellexperience", "windows", "Taskbar bits", "Tray and notification area."),
    ("runtimebroker", "windows", "Permission checker", "Checks what apps are allowed to do. Normal."),
    ("sihost", "windows", "Shell host", "Part of your desktop."),
    ("taskhostw", "windows", "Task host", "Runs small Windows background jobs."),
    ("ctfmon", "windows", "Keyboard service", "Handles typing and input."),
    ("textinputhost", "windows", "Text input", "Handles typing and emoji."),
    ("fontdrvhost", "windows", "Font service", "Draws fonts."),
    ("lsass", "windows", "Security service", "Handles logins. Essential."),
    ("memory compression", "windows", "Memory compression", "Windows squeezing RAM because you're low. Expected on this machine."),
    ("searchindexer", "windows", "File indexer", "Indexes files so search is fast."),
    ("searchprotocol", "windows", "File indexer helper", "Part of the file indexer."),
    ("searchfilter", "windows", "File indexer helper", "Part of the file indexer."),
    ("tiworker", "windows", "Windows Update worker", "Windows Update doing background work."),
    ("trustedinstaller", "windows", "Windows Update installer", "Windows Update installing something."),
    ("spoolsv", "windows", "Print service", "Printer support."),
    ("wmiprvse", "windows", "System info service", "Answers questions about your system - including mine."),
    ("audiodg", "windows", "Audio engine", "Sound processing."),
    ("applicationframehost", "windows", "App window frame", "Draws frames around Store apps."),
    ("systemsettings", "windows", "Settings app", "The Windows Settings window."),
    ("backgroundtaskhost", "windows", "Background task host", "Runs small Store-app jobs."),
    ("smartscreen", "windows", "SmartScreen", "Checks downloads for malware."),
    ("rtkaud", "hardware", "Realtek audio driver", "Your sound card driver."),
    ("nvcontainer", "hardware", "NVIDIA driver service", "Your graphics card driver."),
    ("nvdisplay", "hardware", "NVIDIA display driver", "Your graphics card driver."),
    ("intelgraphics", "hardware", "Intel graphics driver", "Your built-in graphics driver."),
    ("gameinput", "hardware", "Controller support", "Gamepad support. Harmless."),
    ("nahimic", "junk", "Nahimic audio bloat", "Motherboard audio extra. Not needed - cleanup_admin.ps1 removes it."),
    ("gamingservices", "junk", "Xbox store service", "Xbox / Game Pass plumbing. Not needed - cleanup_admin.ps1 removes it."),
    ("officeclicktorun", "junk", "Office updater", "Sits waiting to update Office. Not needed - cleanup_admin.ps1 removes it."),
    ("msi.central", "junk", "MSI motherboard bloat", "Motherboard vendor extra. Not needed - cleanup_admin.ps1 removes it."),
    ("sendevsvc", "junk", "Vendor helper", "Manufacturer background helper. Not needed."),
    ("msedgewebview", "junk", "Edge web panel", "Windows Search's Bing panel. cleanup_admin.ps1 stops it coming back."),
    ("onedrive", "junk", "OneDrive", "Cloud sync. Its autostart is already removed."),
    ("chrome", "junk", "Chrome", "A browser you left open."),
    ("opera", "junk", "Opera", "A browser you left open."),
    ("msedge", "junk", "Edge", "A browser you left open."),
    ("widget", "junk", "Windows widgets", "The news and weather panel. Being removed."),
    ("crossdevice", "junk", "Phone Link", "Phone syncing. Not needed."),
    ("windowspackagemanager", "junk", "App installer service", "Windows package manager sitting idle."),
    ("memcompression", "windows", "Memory compression", "Windows squeezing RAM because you're low. Expected on this machine."),
    ("smss", "windows", "Windows session starter", "Core Windows. Cannot be closed."),
    ("lsaiso", "windows", "Credential guard", "Protects your login secrets. Essential."),
    ("ngciso", "windows", "Windows Hello guard", "Protects your PIN/face login. Essential."),
    ("conhost", "windows", "Console helper", "Invisible helper behind each background command, including the bot's jobs. Normal."),
    ("dashost", "windows", "Device pairing", "Windows talking to connected devices. Normal."),
    ("wudfhost", "windows", "Driver host", "Runs device drivers safely. Normal."),
    ("shellhost", "windows", "Shell host", "Part of your desktop."),
    ("defender", "windows", "Defender helper", "Part of your antivirus."),
    ("securityhealth", "windows", "Windows Security", "The Windows Security status service."),
    ("msdtc", "windows", "Transaction service", "Windows plumbing. Idle and harmless."),
    ("unsecapp", "windows", "System info helper", "Windows plumbing. Harmless."),
    ("aggregatorhost", "windows", "Windows telemetry", "Windows background reporting. Harmless."),
    ("presentationfontcache", "windows", "Font cache", "Speeds up fonts. Harmless."),
    ("wmiregistration", "windows", "System info registration", "Windows plumbing. Harmless."),
    ("appvshnotify", "windows", "App virtualisation helper", "Windows/Office plumbing. Harmless."),
    ("monotificationux", "windows", "Update notifier", "Windows Update's reminder pop-ups."),
    ("appactions", "windows", "App actions", "Windows feature for app shortcuts. Harmless."),
    ("wslservice", "windows", "Linux subsystem (WSL)", "Lets Windows run Linux tools. Harmless; not used by the bot."),
    ("igfx", "hardware", "Intel graphics helper", "Your built-in graphics driver."),
    ("intelaudio", "hardware", "Intel audio driver", "Sound driver."),
    ("intelcphdcp", "hardware", "Intel video protection", "Graphics driver part (for streaming video)."),
    ("jhi_service", "hardware", "Intel security chip", "Intel firmware helper. Harmless."),
    ("wlanext", "hardware", "Wi-Fi driver", "Your wireless driver."),
    ("presentmon", "hardware", "Frame-rate monitor", "Graphics performance helper. Harmless."),
    ("corsair", "hardware", "Corsair hardware helper", "For Corsair RAM/peripheral lighting. Harmless but optional."),
    ("start_hdr", "hardware", "HDR helper", "Display HDR helper. Harmless."),
    ("msi", "junk", "MSI vendor helper", "Motherboard maker's extras. Not needed."),
    ("omapsvcbroker", "junk", "HP vendor helper", "HP software plumbing. Not needed."),
    ("hpprintscandoctor", "junk", "HP Print Doctor", "Printer troubleshooting app. Not needed."),
    ("discord", "junk", "Discord", "The Discord app. The bot's alerts don't need it open."),
    ("xboxpcapp", "junk", "Xbox app", "Xbox app helper. Not needed."),
    ("phoneexperiencehost", "junk", "Phone Link", "Phone syncing. Not needed."),
    ("microsoftstartfeed", "junk", "News feed", "Windows news/weather feed. Not needed."),
    ("voicecontrol", "junk", "Voice control", "Voice-control utility. Optional."),
    ("sdxhelper", "junk", "Office helper", "Office background helper. Not needed."),
]

CAT_ORDER = ["bot", "yours", "windows", "hardware", "junk", "unknown"]
CAT_TITLE = {
    "bot": "Your bot",
    "yours": "Things you opened",
    "windows": "Windows itself",
    "hardware": "Hardware drivers",
    "junk": "Leftovers you don't need",
    "unknown": "I don't recognise these",
}
CAT_NOTE = {
    "bot": "This is the work. All of it should be here.",
    "yours": "You started these, directly or indirectly.",
    "windows": "Windows needs these. Nothing to do.",
    "hardware": "Your graphics, sound and input drivers.",
    "junk": "Safe to remove. cleanup_admin.ps1 handles most of it.",
    "unknown": "Worth asking me about next time we talk.",
}


def classify(name, cmdline):
    exact = {"system": ("windows", "Windows kernel", "The core of Windows. Cannot be closed."),
             "registry": ("windows", "Windows registry", "Windows' settings store. Cannot be closed."),
             "system idle process": ("windows", "Idle time", "Not a real program: spare CPU time. 0 MB."),
             "?": ("windows", "Protected Windows process", "Windows hides this one's name. Normal.")}
    if (name or "").strip().lower() in exact:
        return exact[name.strip().lower()]
    hay = (name + " " + (cmdline or "")).lower()
    for key, cat, label, expl in WHY:
        if key in hay:
            return cat, label, expl
    return "unknown", name, "Not something I recognise. Worth asking me about."


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def get_tasks():
    ps = (
        "Get-ScheduledTask -TaskPath '\\' | "
        "Where-Object {$_.TaskName -like 'WAGMI*'} | "
        "ForEach-Object { $i = $_ | Get-ScheduledTaskInfo; "
        "[PSCustomObject]@{ name=$_.TaskName; state=[string]$_.State; "
        "rc=$i.LastTaskResult; last=[string]$i.LastRunTime; next=[string]$i.NextRunTime } } | "
        "ConvertTo-Json -Compress"
    )
    # CREATE_NO_WINDOW: this runs every minute. A console flashing on screen 60
    # times an hour is exactly the kind of interruption this page exists to stop.
    no_window = 0x08000000
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=90, creationflags=no_window,
        )
        data = json.loads(r.stdout.strip() or "[]")
        if isinstance(data, dict):
            data = [data]
    except Exception:
        return []

    out = []
    for t in data:
        rc = int(t.get("rc") or 0) & 0xFFFFFFFF
        if t.get("state") == "Running":
            status, msg = "running", "Running right now."
        else:
            status, msg = RC.get(
                rc, ("attn", "Finished with code 0x%X, which I haven't taught this page "
                             "to translate yet. Ask me about it." % rc))
        out.append({
            "name": t.get("name", "?"),
            "status": status,
            "msg": msg,
            "last": (t.get("last") or "").strip(),
            "next": (t.get("next") or "").strip(),
        })
    out.sort(key=lambda x: x["name"])
    return out


def get_bot():
    hb = read_json(BOT / "data" / "heartbeat.json", {}) or {}
    pos = read_json(BOT / "data" / "position_state.json", {}) or {}
    age = None
    if hb.get("epoch"):
        age = time.time() - float(hb["epoch"])
    return {
        "alive": age is not None and age < 300,
        "age": age,
        "scans": hb.get("scan_count"),
        "uptime": hb.get("uptime_s"),
        "equity": hb.get("equity"),
        "errors": hb.get("errors"),
        "positions": pos.get("position_count", hb.get("positions")),
        "llm_degraded": bool(hb.get("llm_first_degraded")),
        "last_ai_decision_age": last_ai_decision_age(),
    }


def last_ai_decision_age():
    """Seconds since the newest LLM agent decision, from the tail of
    agent_performance.jsonl. None if unreadable. The 2026-10-05..07 outage
    sat at 79% failed calls for ~3 days while every other signal was green."""
    path = BOT / "data" / "llm" / "agent_performance.jsonl"
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 200_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except Exception:
        return None
    for line in reversed(lines):
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if rec.get("type") == "decision" and rec.get("timestamp"):
            return time.time() - float(rec["timestamp"])
    return None


def get_procs():
    try:
        import psutil
    except Exception:
        return {}, {}
    groups = {}
    for p in psutil.process_iter(["name", "memory_info", "cmdline"]):
        try:
            nm = p.info["name"] or "?"
            mi = p.info["memory_info"]
            mb = (mi.rss / 1048576.0) if mi else 0.0
            cmd = " ".join(p.info["cmdline"] or [])[:300]
        except Exception:
            continue
        cat, label, expl = classify(nm, cmd)
        g = groups.setdefault((cat, label), {"cat": cat, "label": label,
                                             "expl": expl, "mb": 0.0, "n": 0})
        g["mb"] += mb
        g["n"] += 1
    by_cat = {}
    for g in groups.values():
        by_cat.setdefault(g["cat"], []).append(g)
    for c in by_cat:
        by_cat[c].sort(key=lambda g: -g["mb"])
    totals = {c: sum(g["mb"] for g in rows) for c, rows in by_cat.items()}
    return by_cat, totals


def get_mem():
    try:
        import psutil
        v = psutil.virtual_memory()
        return {"total": v.total / 1073741824.0,
                "avail": v.available / 1073741824.0,
                "pct": v.percent}
    except Exception:
        return {}


def get_attention():
    """Cached market-attention snapshot written by tools/copilot/attention_snapshot.py.

    This page rebuilds every minute, so it must never fetch anything itself - the
    snapshot job runs on its own slower schedule and leaves this file behind. A
    missing or stale file degrades to "not available" rather than an empty table,
    because a blank market section reads as "nothing to see", which is a lie.
    """
    d = read_json(BOT / "data" / "copilot" / "attention.json", None)
    if not isinstance(d, dict) or not d.get("rows"):
        return None
    age = None
    try:
        ts = datetime.strptime(d["generated_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
    except Exception:
        pass
    d["_age"] = age
    return d


def human_age(s):
    if s is None:
        return "unknown"
    s = int(s)
    if s < 60:
        return "%ds ago" % s
    if s < 3600:
        return "%dm ago" % (s // 60)
    if s < 86400:
        return "%dh %dm ago" % (s // 3600, (s % 3600) // 60)
    return "%dd ago" % (s // 86400)


def human_dur(s):
    if s is None:
        return "unknown"
    s = int(s)
    if s < 3600:
        return "%d min" % (s // 60)
    if s < 86400:
        return "%dh %dm" % (s // 3600, (s % 3600) // 60)
    return "%dd %dh" % (s // 86400, (s % 86400) // 3600)


def e(x):
    return html.escape(str(x), quote=True)


# ── page ────────────────────────────────────────────────────────────────
CSS = """
:root{
  --bg:#f7f6f3; --panel:#fffefb; --line:#e5e2da; --ink:#2f2c28; --soft:#6f6a62;
  --ok:#3f7d5e; --okbg:#eaf3ee; --attn:#8a6a2f; --attnbg:#f7f0e0;
  --run:#3d6584; --runbg:#e9f0f5; --accent:#4a6fa5;
  --pos:#2a78d6; --neg:#e34948; --mid:#c9c6bf;
}
:root:not([data-theme="light"]){ }
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#16181b; --panel:#1d2024; --line:#2c3035; --ink:#e4e1db; --soft:#9a948b;
    --ok:#7fb99a; --okbg:#1d2a24; --attn:#d0ab6a; --attnbg:#2b2519;
    --run:#8fb4d0; --runbg:#1b262e; --accent:#8ba9d4;
    --pos:#3987e5; --neg:#e66767; --mid:#4a4a46;
  }
}
:root[data-theme="dark"]{
  --bg:#16181b; --panel:#1d2024; --line:#2c3035; --ink:#e4e1db; --soft:#9a948b;
  --ok:#7fb99a; --okbg:#1d2a24; --attn:#d0ab6a; --attnbg:#2b2519;
  --run:#8fb4d0; --runbg:#1b262e; --accent:#8ba9d4;
  --pos:#3987e5; --neg:#e66767; --mid:#4a4a46;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.65 "Segoe UI",system-ui,-apple-system,sans-serif;
  padding:32px 24px 64px;
}
.wrap{max-width:920px;margin:0 auto}
h1{font-size:15px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
   color:var(--soft);margin:0 0 24px}
.head{
  background:var(--panel);border:1px solid var(--line);border-radius:14px;
  padding:28px 30px;margin-bottom:28px;
}
.verdict{font-size:30px;line-height:1.25;font-weight:650;margin:0 0 8px;letter-spacing:-.01em}
.verdict.ok{color:var(--ok)}
.verdict.attn{color:var(--attn)}
.sub{color:var(--soft);font-size:15px;margin:0}
.todo{margin:20px 0 0;padding:0;list-style:none}
.todo li{
  background:var(--attnbg);border-left:3px solid var(--attn);border-radius:0 8px 8px 0;
  padding:12px 16px;margin:8px 0;font-size:15px;
}
.todo li b{display:block;font-weight:600;margin-bottom:2px}
.todo li span{color:var(--soft);font-size:14px}
h2{font-size:13px;font-weight:600;letter-spacing:.09em;text-transform:uppercase;
   color:var(--soft);margin:32px 0 4px}
.note{color:var(--soft);font-size:14px;margin:0 0 12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;
      padding:6px 4px;overflow:hidden}
.row{display:flex;gap:14px;align-items:baseline;padding:11px 22px;border-bottom:1px solid var(--line)}
.row:last-child{border-bottom:none}
.dot{flex:0 0 auto;width:9px;height:9px;border-radius:50%;margin-top:7px}
.dot.ok{background:var(--ok)} .dot.attn{background:var(--attn)} .dot.running{background:var(--run)}
.nm{flex:0 0 208px;font-weight:600;font-size:15px}
.ms{flex:1;color:var(--soft);font-size:14.5px;min-width:190px}
.mb{flex:0 0 auto;color:var(--soft);font-size:13.5px;font-variant-numeric:tabular-nums}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;
       background:var(--line);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.stat{background:var(--panel);padding:18px 20px}
.chart{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px 10px;margin:0 0 14px}
.chart h3{font-size:15px;font-weight:600;margin:0 0 2px}
.chart p{color:var(--soft);font-size:13.5px;margin:0 0 8px}
.chart svg{width:100%;height:auto;display:block;overflow:visible}
.chart svg text{fill:var(--soft);font-size:11px;font-variant-numeric:tabular-nums}
.chart .grid{stroke:var(--line);stroke-width:1}
.chart .zero{stroke:var(--soft);stroke-width:1}
.chart .ln{fill:none;stroke:var(--pos);stroke-width:2;stroke-linejoin:round}
.chart .hit{fill:transparent}
.chart .hit:hover{fill:var(--pos);fill-opacity:.25}
.chart .bp{fill:var(--pos)} .chart .bn{fill:var(--neg)} .chart .bx{fill:var(--mid)}
.chart rect:hover{opacity:.75}
.chart details{font-size:13px;color:var(--soft);margin-top:6px}
.chart table{border-collapse:collapse;margin-top:6px;font-variant-numeric:tabular-nums}
.chart td,.chart th{padding:2px 10px 2px 0;text-align:left}
.think{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:4px 0;margin-bottom:14px}
.think .r{padding:12px 20px;border-bottom:1px solid var(--line)}
.think .r:last-child{border-bottom:none}
.think .h{font-weight:600;font-size:15px}
.think .t{color:var(--soft);font-size:14px;margin-top:2px}
.stat .k{font-size:12px;letter-spacing:.07em;text-transform:uppercase;color:var(--soft);margin-bottom:5px}
.stat .v{font-size:24px;font-weight:650;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.bar{height:7px;background:var(--line);border-radius:4px;overflow:hidden;margin:14px 0 6px}
.bar i{display:block;height:100%;background:var(--accent)}
footer{color:var(--soft);font-size:13px;margin-top:40px;text-align:center;line-height:1.9}
kbd{background:var(--bg);border:1px solid var(--line);border-radius:5px;padding:1px 6px;
    font:13px ui-monospace,Consolas,monospace}
@media(max-width:680px){
  body{padding:20px 14px 48px} .verdict{font-size:24px}
  .row{flex-wrap:wrap;gap:5px} .nm{flex-basis:100%}
}
"""


def recent_thinking(n_rounds=4):
    """Last few complete decision rounds from agent_performance.jsonl, newest first."""
    path = BOT / "data" / "llm" / "agent_performance.jsonl"
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 400_000))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except Exception:
        return []
    rounds = {}
    for line in lines:
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("type") != "decision" or r.get("agent_role") not in ("regime", "trade", "risk", "critic", "exit"):
            continue
        rounds.setdefault(r.get("pipeline_id"), {})[r["agent_role"]] = r
    out = sorted(rounds.values(), key=lambda m: max(x["timestamp"] for x in m.values()), reverse=True)
    return out[:n_rounds]


def _first_sentence(txt, limit=230):
    txt = (txt or "").strip()
    if txt.startswith("{"):
        return ""
    cut = min([i for i in (txt.find(". "), len(txt)) if i >= 0]) + 1
    txt = txt[:cut].rstrip(". ") + "."
    return txt if len(txt) <= limit else txt[:limit - 1].rstrip() + "…"


def _svg_line(points, w=860, h=170, pad_l=46, pad_b=22):
    """points: [(ts, value)]. Single series, so no legend: the chart title names it."""
    if len(points) < 2:
        return ""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    x0, x1 = min(xs), max(xs)
    lo, hi = min(min(ys), 0), max(max(ys), 0)
    span = (hi - lo) or 1
    lo, hi = lo - span * 0.08, hi + span * 0.08
    X = lambda t: pad_l + (t - x0) / ((x1 - x0) or 1) * (w - pad_l - 8)
    Y = lambda v: 8 + (hi - v) / (hi - lo) * (h - 8 - pad_b)
    o = ["<svg viewBox='0 0 %d %d' role='img'>" % (w, h)]
    for v in (lo + (hi - lo) * k / 4 for k in range(5)):
        o.append("<line class='grid' x1='%d' x2='%d' y1='%.1f' y2='%.1f'/>" % (pad_l, w - 8, Y(v), Y(v)))
        o.append("<text x='%d' y='%.1f' text-anchor='end'>%s$%.0f</text>" % (pad_l - 6, Y(v) + 4, "-" if v < 0 else "+", abs(v)))
    o.append("<line class='zero' x1='%d' x2='%d' y1='%.1f' y2='%.1f'/>" % (pad_l, w - 8, Y(0), Y(0)))
    seen_month = set()
    for t in xs:
        m = datetime.fromtimestamp(t, timezone.utc).strftime("%b")
        if m not in seen_month:
            seen_month.add(m)
            o.append("<text x='%.1f' y='%d'>%s</text>" % (X(t), h - 4, m))
    o.append("<polyline class='ln' points='%s'/>" % " ".join("%.1f,%.1f" % (X(t), Y(v)) for t, v in points))
    for t, v in points:
        o.append("<circle class='hit' cx='%.1f' cy='%.1f' r='6'><title>%s: %s$%.2f total</title></circle>" % (
            X(t), Y(v), datetime.fromtimestamp(t, timezone.utc).strftime("%b %d"), "-" if v < 0 else "+", abs(v)))
    o.append("</svg>")
    return "".join(o)


def _svg_bars(series, w=860, h=170, pad_l=46, pad_b=22):
    """series: [(label, value or None, tooltip)]. Diverging: blue above zero, red below."""
    if not series:
        return ""
    vals = [v for _, v, _ in series if v is not None]
    lim = max([abs(v) for v in vals] + [10]) * 1.1
    Y = lambda v: 8 + (lim - v) / (2 * lim) * (h - 8 - pad_b)
    n = len(series)
    slot = (w - pad_l - 8) / n
    bw = max(4, slot - 4)
    o = ["<svg viewBox='0 0 %d %d' role='img'>" % (w, h)]
    for v in (-lim, -lim / 2, 0, lim / 2, lim):
        o.append("<line class='%s' x1='%d' x2='%d' y1='%.1f' y2='%.1f'/>" % (
            "zero" if v == 0 else "grid", pad_l, w - 8, Y(v), Y(v)))
        o.append("<text x='%d' y='%.1f' text-anchor='end'>%+.2f%%</text>" % (pad_l - 6, Y(v) + 4, v / 100))
    for i, (lab, v, tip) in enumerate(series):
        x = pad_l + i * slot + 2
        if v is None:
            o.append("<rect class='bx' x='%.1f' y='%.1f' width='%.1f' height='2' rx='1'><title>%s</title></rect>" % (
                x, Y(0) - 1, bw, e(tip)))
        else:
            top, bot = (Y(v), Y(0)) if v >= 0 else (Y(0), Y(v))
            o.append("<rect class='%s' x='%.1f' y='%.1f' width='%.1f' height='%.1f' rx='2'><title>%s</title></rect>" % (
                "bp" if v >= 0 else "bn", x, top, bw, max(bot - top, 1), e(tip)))
        if i % 2 == 0:
            o.append("<text x='%.1f' y='%d' text-anchor='middle'>%s</text>" % (x + bw / 2, h - 4, e(lab)))
    o.append("</svg>")
    return "".join(o)


def _week_label(wk):
    try:
        d = datetime.strptime(wk + "-1", "%G-W%V-%u")
        return d.strftime("%b %d")
    except Exception:
        return wk


def build():
    bot = get_bot()
    tasks = get_tasks()
    by_cat, cat_tot = get_procs()
    mem = get_mem()

    # ── what actually needs the human ────────────────────────────────
    todo = []
    if not bot["alive"]:
        todo.append(("Your bot is not responding.",
                     "Last sign of life %s. Tell Claude \"the bot is down\" and it will "
                     "restart it." % human_age(bot["age"])))
    if bot["alive"] and bot.get("llm_degraded"):
        todo.append(("The bot's AI brain is offline.",
                     "Its AI calls are failing, so it has fallen back to a mode that "
                     "won't open trades. Often the Claude login expired. Tell Claude "
                     "\"the AI is down\"."))
    elif bot["alive"] and (bot.get("last_ai_decision_age") or 0) > 3 * 3600:
        todo.append(("The bot's AI hasn't made a decision in %s." % human_dur(bot["last_ai_decision_age"]),
                     "It normally decides a few times an hour. Its calls may be failing "
                     "quietly. Tell Claude \"the AI is quiet\"."))
    for t in tasks:
        if t["status"] == "attn":
            todo.append((t["name"] + " needs attention.", t["msg"]))
    if mem and mem.get("avail", 99) < 0.8:
        todo.append(("Memory is tight.",
                     "Only %.1f GB free of %.1f GB. Closing a browser usually fixes it."
                     % (mem["avail"], mem["total"])))
    if bot.get("errors"):
        todo.append(("The bot logged %s error(s)." % bot["errors"],
                     "Not necessarily serious. Ask Claude to read the log."))

    if todo:
        vclass = "attn"
        n = len(todo)
        verdict = "%d thing%s needs you." % (n, "" if n == 1 else "s")
        sub = "Everything not listed below is running normally. You can ignore the rest of this page."
    else:
        vclass = "ok"
        verdict = "Everything is running. Nothing needs you."
        sub = "Your bot is alive, every scheduled job is healthy, and there is nothing to fix. The detail below is only if you're curious."

    p = []
    p.append("<div class='wrap'>")
    p.append("<h1>WAGMI &mdash; system status</h1>")

    p.append("<div class='head'>")
    p.append("<p class='verdict %s'>%s</p>" % (vclass, e(verdict)))
    p.append("<p class='sub'>%s</p>" % e(sub))
    if todo:
        p.append("<ul class='todo'>")
        for title, detail in todo:
            p.append("<li><b>%s</b><span>%s</span></li>" % (e(title), e(detail)))
        p.append("</ul>")
    p.append("</div>")

    # ── market attention ─────────────────────────────────────────────
    # Deliberately FIRST content section. Everything else on this page answers
    # "is the machine healthy"; this answers "is anything worth looking at",
    # which is the question that actually costs money when nobody asks it.
    # Measurement only - where price sits in its 90d window. Never a prediction.
    attn = get_attention()
    p.append("<h2>Worth a look</h2>")
    if attn is None:
        p.append("<p class='note'>%s</p>" % e(
            "Market snapshot not available yet. It is written by a separate job "
            "(tools/copilot/attention_snapshot.py); nothing is wrong with the bot."))
    else:
        edge = [r for r in attn["rows"] if r.get("zone") != "mid-range"]
        lo = [r for r in edge if (r.get("range_pos") or 50) <= attn.get("low_edge_pct", 15)]
        hi = [r for r in edge if (r.get("range_pos") or 50) >= attn.get("high_edge_pct", 85)]
        if not edge:
            headline = ("Nothing is at a range extreme. Every coin tracked is "
                        "mid-range in its 90-day window.")
        else:
            bits = []
            if lo:
                bits.append("%d at the BOTTOM of its 90-day range (%s)"
                            % (len(lo), ", ".join(r["symbol"] for r in lo)))
            if hi:
                bits.append("%d at the TOP of its 90-day range (%s)"
                            % (len(hi), ", ".join(r["symbol"] for r in hi)))
            headline = "; ".join(bits) + "."
        p.append("<p class='note'>%s</p>" % e(headline))
        p.append("<div class='stats'>")
        for r in attn["rows"]:
            rp = r.get("range_pos")
            val = ("%.0f%%" % rp) if rp is not None else "unknown"
            px = r.get("price")
            # Adaptive precision: a meme at $0.0044 must not render as "$0.00".
            if px:
                dp = 2 if px >= 100 else 4 if px >= 1 else 6 if px >= 0.01 else 8
                sub = " &middot; $" + format(px, ",.%df" % dp).rstrip("0").rstrip(".")
            else:
                sub = ""
            p.append("<div class='stat'><div class='k'>%s%s</div>"
                     "<div class='v'>%s</div></div>"
                     % (e(r["symbol"]), sub, e(val)))
        p.append("</div>")
        p.append("<p class='note'>%s</p>" % e(
            "Numbers are position in the 90-day range: 0%% = range low, 100%% = "
            "range high. This is a MEASUREMENT of where price sits, not a "
            "prediction - nothing here says which way anything goes. "
            "Snapshot age: %s." % human_age(attn.get("_age"))))

    # ── the bot ──────────────────────────────────────────────────────
    p.append("<h2>Your bot</h2>")
    p.append("<p class='note'>%s</p>" % (
        "Alive and scanning the market." if bot["alive"]
        else "Not responding. See the note at the top of the page."))
    eq = bot.get("equity")
    eq_txt = ("$" + format(eq, ",.2f")) if eq else "unknown"
    p.append("<div class='stats'>")
    for k, v in [
        ("Account", eq_txt),
        ("Open positions", bot.get("positions") if bot.get("positions") is not None else "unknown"),
        ("Market scans", bot.get("scans") if bot.get("scans") is not None else "unknown"),
        ("Running for", human_dur(bot.get("uptime"))),
        ("Last heartbeat", human_age(bot.get("age"))),
        ("Errors", bot.get("errors") if bot.get("errors") is not None else "unknown"),
    ]:
        p.append("<div class='stat'><div class='k'>%s</div><div class='v'>%s</div></div>" % (e(k), e(v)))
    p.append("</div>")

    # ── what the AI is thinking ──────────────────────────────────────
    rounds = recent_thinking()
    if rounds:
        p.append("<h2>What the AI is thinking</h2>")
        p.append("<p class='note'>%s</p>" % e(
            "The bot's latest decision rounds, newest first, in each agent's own words. "
            "A 'go' here still has to clear the confidence bar before it becomes a trade."))
        p.append("<div class='think'>")
        for m in rounds:
            ts = max(x["timestamp"] for x in m.values())
            sym = next(iter(m.values())).get("symbol", "?")
            bits = []
            if "regime" in m:
                bits.append("market: %s" % m["regime"]["decision"].replace("_", " "))
            if "trade" in m:
                bits.append("trade agent: %s (confidence %.0f%%)" % (
                    m["trade"]["decision"].upper(), 100 * float(m["trade"].get("confidence") or 0)))
            if "critic" in m:
                bits.append("critic: %s" % m["critic"]["decision"])
            if "exit" in m:
                bits.append("exit agent: %s" % m["exit"]["decision"].replace("_", " "))
            why = _first_sentence((m.get("trade") or m.get("exit") or m.get("regime") or {}).get("reasoning_summary"))
            p.append("<div class='r'><div class='h'>%s · %s · %s</div><div class='t'>%s</div></div>" % (
                e(sym), e(human_age(time.time() - ts)), e(" · ".join(bits)), e(why)))
        runs = []
        try:
            with open(BOT / "data" / "managers" / "runs.jsonl", encoding="utf-8") as f:
                runs = [json.loads(l) for l in f if l.strip()]
        except Exception:
            pass
        notes = [r for r in runs if r.get("note")]
        if notes:
            p.append("<div class='r'><div class='h'>Opus manager's latest note (%s)</div><div class='t'>%s</div></div>" % (
                e(notes[-1]["ts"][:10]), e(notes[-1]["note"])))
        p.append("</div>")

    # ── how it's improving ───────────────────────────────────────────
    prog = read_json(BOT / "data" / "agent_grades" / "live" / "progress.json", None)
    if prog:
        p.append("<h2>How it's improving</h2>")
        pnl = prog.get("cum_pnl") or []
        if len(pnl) >= 2:
            last = pnl[-1][1]
            p.append("<div class='chart'><h3>Total trading profit since May: %s$%.2f</h3>"
                     "<p>Every closed trade added up, after fees. Flat stretches are when it wasn't trading. "
                     "Hover a point for the date.</p>%s</div>" % ("-" if last < 0 else "+", abs(last), _svg_line(pnl)))
        wk = prog.get("pick_quality_weekly") or {}
        if wk:
            from datetime import timedelta
            keys = sorted(wk)
            d = datetime.strptime(keys[0] + "-1", "%G-W%V-%u")
            end = datetime.strptime(keys[-1] + "-1", "%G-W%V-%u")
            full = {}
            while d <= end:
                k = d.strftime("%G-W%V")
                full[k] = wk.get(k, {"n_go": 0, "n_skip": 0, "go_minus_skip": None})
                d += timedelta(days=7)
            wk = full
            ser = []
            for k, v in wk.items():
                g = v.get("go_minus_skip")
                tip = ("%s: GO picks did %+.2f%% vs SKIPs (%d go, %d skip)" % (_week_label(k), g / 100, v["n_go"], v["n_skip"])
                       if g is not None else "%s: too few graded decisions (%d go, %d skip)" % (
                           _week_label(k), v["n_go"], v["n_skip"]))
                ser.append((_week_label(k), g, tip))
            p.append("<div class='chart'><h3>Is the AI picking better trades than it skips?</h3>"
                     "<p>Each bar is one week: how the setups the trade agent said GO to did over the next "
                     "4 hours, minus the ones it skipped. Blue above the line means its picks were better; "
                     "red means its skips did better. Steady blue is what learning looks like. "
                     "Gray means too few graded decisions that week. August is missing (the PC was moving).</p>%s"
                     % _svg_bars(ser))
            p.append("<details><summary>Show as a table</summary><table><tr><th>Week of</th><th>GO minus SKIP</th>"
                     "<th>GO</th><th>SKIP</th></tr>%s</table></details></div>" % "".join(
                         "<tr><td>%s</td><td>%s</td><td>%d</td><td>%d</td></tr>" % (
                             e(_week_label(k)), ("%+.2f%%" % (v["go_minus_skip"] / 100)) if v.get("go_minus_skip") is not None else "-",
                             v["n_go"], v["n_skip"]) for k, v in wk.items()))

    # ── agent report cards (tools/live_grader.py) ────────────────────
    sc = read_json(BOT / "data" / "agent_grades" / "live" / "live_scorecard.json", None)
    if sc:
        p.append("<h2>AI agent report cards</h2>")
        p.append("<p class='note'>%s</p>" % e(
            "Every AI decision is checked 4 hours later against what the price "
            "actually did. %d decisions graded since %s. An agent is 'earning' only "
            "when its good calls beat its bad calls by a clear margin over 100+ cases. "
            "Updated %s." % (sc.get("resolved_rows", 0), (sc.get("since") or "")[:10],
                             human_age(time.time() - datetime.fromisoformat(sc["updated"]).timestamp()))))
        words = {"collecting": "still collecting", "promising": "promising",
                 "earning": "EARNING its keep", "no edge yet": "no edge yet",
                 "backwards": "doing worse than chance"}
        p.append("<div class='think'>")
        for name, a in (sc.get("agents") or {}).items():
            n = min(a.get("nA", 0), a.get("nB", 0))
            if "diff_bps" in a:
                detail = "%+.2f%% per call (range %+.2f%% to %+.2f%%), %d cases" % (
                    a["diff_bps"] / 100, a["ci95"][0] / 100, a["ci95"][1] / 100, n)
            else:
                detail = "%d vs %d cases so far" % (a.get("nA", 0), a.get("nB", 0))
            if a.get("historical_diff_bps") is not None:
                detail += "; before the upgrade: %+.2f%%" % (a["historical_diff_bps"] / 100)
            p.append("<div class='r'><div class='h'>%s%s: %s</div><div class='t'>%s %s</div></div>" % (
                e(name.capitalize()), "" if " " in name else " agent", e(words.get(a.get("verdict"), a.get("verdict"))),
                e(a.get("question", "")), e(detail)))
        dr = sc.get("ic_muted_drops") or {}
        p.append("<div class='r'><div class='h'>Silenced-strategy gate: %s</div><div class='t'>%s %s</div></div>" % (
            e("still collecting" if dr.get("n", 0) < 30 else ("right to drop them" if dr.get("mean_bps", 0) < 0
                                                              else "dropping signals that would have made money")),
            e("All five strategies that fire most are currently muted for a backwards track record, so most "
              "signals are dropped before the AI sees them. This checks whether that's right."),
            e("%d dropped signals graded%s." % (dr.get("n", 0), "" if not dr.get("n") else
                                               ", average %+.2f%% each if taken" % (dr["mean_bps"] / 100)))))
        p.append("</div>")

    # ── rules manager (tools/rules_manager.py) ───────────────────────
    rules = read_json(BOT / "data" / "managers" / "rules.json", None)
    if rules:
        live = [r for r in rules if r.get("status") != "retired"]
        p.append("<h2>Rules the AI manager is testing</h2>")
        p.append("<p class='note'>%s</p>" % e(
            "Once a day an Opus 'manager' proposes specific rules about which kinds of "
            "trades to avoid or favor. Each rule is scored ONLY on what happens after it "
            "was written, so it can't pass by fitting the past. Nothing acts on a rule yet; "
            "'earned' means it has proven itself and is ready for you to switch on. "
            "%d testing, %d earned, %d retired." % (
                sum(r["status"] == "shadow" for r in rules), sum(r["status"] == "earned" for r in rules),
                sum(r["status"] == "retired" for r in rules))))
        p.append("<div class='think'>")
        for r in live:
            sl = ", ".join("%s %s" % (k, v) for k, v in r["slice"].items())
            fw = (r.get("forward") or {})
            fs, ft = fw.get("signals_bps") or {}, fw.get("trades_usd") or {}
            prog = "since %s: %d signals, %d trades in this slice" % (
                r.get("created_iso", "")[:10], fs.get("n_in", 0), ft.get("n_in", 0))
            if "diff" in fs:
                prog += "; signals here did %+.2f%% vs the rest" % (fs["diff"] / 100)
            if ft.get("n_in"):
                prog += "; trades here made $%+.2f total" % ft.get("total_in", 0)
            p.append("<div class='r'><div class='h'>%s %s: %s [%s]</div><div class='t'>%s. %s</div></div>" % (
                e(r["id"]), e(r["action"].upper()), e(sl), e("EARNED" if r["status"] == "earned" else "testing"),
                e(r.get("thesis", "").rstrip(".")), e(prog)))
        p.append("</div>")

    # ── scheduled jobs ───────────────────────────────────────────────
    p.append("<h2>Scheduled jobs</h2>")
    nattn = sum(1 for t in tasks if t["status"] == "attn")
    p.append("<p class='note'>%s</p>" % e(
        "All %d healthy." % len(tasks) if nattn == 0
        else "%d of %d need attention (marked below)." % (nattn, len(tasks))))
    p.append("<div class='card'>")
    for t in tasks:
        p.append("<div class='row'><span class='dot %s'></span>"
                 "<span class='nm'>%s</span><span class='ms'>%s</span></div>"
                 % (t["status"], e(t["name"].replace("WAGMI-", "")), e(t["msg"])))
    p.append("</div>")

    # ── why is my system doing this ──────────────────────────────────
    p.append("<h2>What's running, and why</h2>")
    p.append("<p class='note'>Every process on this machine, grouped and explained. "
             "This is the answer to &ldquo;why is my system doing this right now?&rdquo;</p>")
    for cat in CAT_ORDER:
        rows = by_cat.get(cat)
        if not rows:
            continue
        p.append("<h2 style='margin-top:22px'>%s &nbsp;<span style='text-transform:none;"
                 "letter-spacing:0;font-weight:400'>%s MB</span></h2>"
                 % (e(CAT_TITLE[cat]), format(int(cat_tot.get(cat, 0)), ",")))
        p.append("<p class='note'>%s</p>" % e(CAT_NOTE[cat]))
        p.append("<div class='card'>")
        for g in rows:
            cnt = "" if g["n"] == 1 else " &times;%d" % g["n"]
            p.append("<div class='row'><span class='nm'>%s%s</span>"
                     "<span class='ms'>%s</span><span class='mb'>%s MB</span></div>"
                     % (e(g["label"]), cnt, e(g["expl"]), format(int(g["mb"]), ",")))
        p.append("</div>")

    # ── memory ───────────────────────────────────────────────────────
    if mem:
        p.append("<h2>Memory</h2>")
        p.append("<p class='note'>This machine has %.1f GB total, which is tight. "
                 "Free memory below about 0.8 GB is when things start to struggle.</p>" % mem["total"])
        p.append("<div class='card'><div class='row' style='display:block;padding:20px 22px'>")
        p.append("<div class='bar'><i style='width:%.0f%%'></i></div>" % mem["pct"])
        p.append("<div class='ms'>%.1f GB free of %.1f GB &nbsp;&middot;&nbsp; %.0f%% in use</div>"
                 % (mem["avail"], mem["total"], mem["pct"]))
        p.append("</div></div>")

    p.append("<footer>Rebuilt every minute &nbsp;&middot;&nbsp; page refreshes itself every 30 seconds"
             "<br>Last built %s"
             "<br>Nothing here changes anything. It only looks."
             "<br>Press <kbd>F5</kbd> to refresh now, <kbd>F11</kbd> for fullscreen.</footer>"
             % time.strftime("%A %d %B, %H:%M:%S"))
    p.append("</div>")

    doc = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta http-equiv='refresh' content='30'>"
        "<title>WAGMI - system status</title><style>%s</style></head><body>%s</body></html>"
        % (CSS, "".join(p))
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(doc, encoding="utf-8")
    tmp.replace(OUT)
    return len(todo), len(tasks)


def text_report():
    """Same answer, for the terminal. Deliberately short."""
    bot = get_bot()
    tasks = get_tasks()
    mem = get_mem()

    todo = []
    if not bot["alive"]:
        todo.append("Bot is not responding (last seen %s)." % human_age(bot["age"]))
    for t in tasks:
        if t["status"] == "attn":
            todo.append("%s: %s" % (t["name"], t["msg"]))
    if mem and mem.get("avail", 99) < 0.8:
        todo.append("Memory tight: %.1f GB free of %.1f GB." % (mem["avail"], mem["total"]))

    out = []
    if todo:
        out.append("%d thing%s needs you:" % (len(todo), "" if len(todo) == 1 else "s"))
        for t in todo:
            out.append("  - " + t)
    else:
        out.append("Everything is running. Nothing needs you.")
    out.append("")
    eq = bot.get("equity")
    out.append("  Bot        %s | $%s | %s open | %s scans | %s errors" % (
        "alive" if bot["alive"] else "DOWN",
        format(eq, ",.2f") if eq else "?",
        bot.get("positions"), bot.get("scans"), bot.get("errors")))
    running = sum(1 for t in tasks if t["status"] == "running")
    healthy = sum(1 for t in tasks if t["status"] in ("ok", "running"))
    out.append("  Jobs       %d/%d healthy, %d running now" % (healthy, len(tasks), running))
    if mem:
        out.append("  Memory     %.1f GB free of %.1f GB" % (mem["avail"], mem["total"]))
    out.append("  Full page  C:\\Users\\vince\\WAGMI\\dashboard.html")
    return "\n".join(out)


if __name__ == "__main__":
    import sys
    if "--text" in sys.argv:
        print(text_report())
    else:
        n_todo, n_tasks = build()
        print("dashboard -> %s" % OUT)
        print("%d task(s) checked, %d item(s) need attention" % (n_tasks, n_todo))
