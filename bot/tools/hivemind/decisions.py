import os
"""Decisions that change live trading and therefore belong to the owner.

Each decision states the evidence so far and an explicit readiness test. When the test passes, the System
Status headline and the terminal show it as READY. Nothing here changes the bot.
"""
import json
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
HM = BOT / "data" / "hivemind"


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _env_has(key):
    try:
        for ln in (BOT / ".env").read_text(encoding="utf-8").splitlines():
            if ln.strip().startswith(key + "=") and ln.split("=", 1)[1].split("#")[0].strip() not in ("", "0", "false"):
                return True
    except OSError:
        pass
    return False


def build():
    out = []
    g = _load(HM / "geometry_shadow.json", {}) or {}
    ad = g.get("adaptive") or {}
    ready_g = bool(ad.get("ci95") and ad["ci95"][0] > 0 and ad.get("n", 0) >= 60) or \
        bool(g.get("ci95") and g["ci95"][0] > 0 and g.get("n", 0) >= 60)
    out.append({
        "id": "bot-stops",
        "title": "Widen the bot's stops",
        "ask": "Wider stops, STOP ONLY: stop 2x the forecast daily move, smaller position so dollar risk is unchanged, the bot's own targets and 8h limit kept.",
        "why": ("You said yes on Oct 10. The live test says wider stops lose much less; the laptop's last word was HOLD (the gain "
                "is mostly lower fees per unit of risk). Per your rule, it stays OFF until the laptop corroborates (its mission A)."),
        "live": (f"Live paired test, {g.get('n', 0)} signals: current {g.get('mean_r_current')}R, wider {g.get('mean_r_proposal')}R, "
                 f"forecast-sized {ad.get('mean_r', '-')}R (gain {ad.get('paired_diff_vs_current', '-')}R, "
                 f"range {ad.get('ci95', ['-', '-'])[0]} to {ad.get('ci95', ['-', '-'])[1]})."),
        "ready_when": "the laptop's red-teamed verdict on mission A is SUPPORT",
        "ready": (BOT / "data" / "laptop_mining" / "STOPS_VERDICT_SUPPORT").exists(),
        "note": ("Merged and tested, switched OFF (ADAPTIVE_STOPS=false). Turning it on = one line in .env + restart."),
    })
    sc = _load(BOT / "data" / "agent_grades" / "live" / "live_scorecard.json", {}) or {}
    d = sc.get("ic_muted_drops") or {}
    flip = _load(BOT / "data" / "laptop_mining" / "muted_flip.json", None)
    if flip is not None and not flip.get("verdict"):
        flip["verdict"] = ("keep the gate: no muted strategy works inverted; bollinger_squeeze's proxy looked positive "
                           "but the bot's real BB signals flip sign between halves (server check, n=664)")
    out.append({
        "id": "ic-gate",
        "title": "The silent strategy gate",
        "ask": "Keep dropping signals from the five muted strategies, or let a small share through to keep learning?",
        "why": "Since early October about 99.8% of strategy votes are dropped before the AI sees them, because all five busiest strategies have a backwards record.",
        "live": (f"{d.get('n', 0)} dropped signals graded" + (f", average {d.get('mean_bps', 0) / 100:+.2f}% each if taken" if d.get("n") else "")
                 + ("; laptop's flip test: " + str((flip or {}).get("verdict", "in")) if flip else "; laptop's flip test (mission 13) pending.")),
        "ready_when": "30+ dropped signals graded and the laptop's flip test is in",
        "ready": False,   # settled 2026-10-10/11: KEEP (owner deferred to the laptop; laptop verdict: keep, stay flat)
        "note": ("Recommendation: KEEP the gate. The dropped signals would have lost money; letting some through only buys "
                 "losing trades. Doing nothing = keeping it." if d.get("n", 0) >= 30 and (d.get("mean_bps") or 0) < 0 else ""),
    })
    out.append({
        "id": "exit-credit-saver",
        "title": "Exit-agent credit saver",
        "ask": "Once a bot trade's stop already locks in profit, ask the AI exit agent at most once an hour instead of every ~10 minutes?",
        "why": "On Oct 8-9 the exit agent was asked 61 times about a ~$4 NEAR leftover whose stop already locked profit. Mechanical stops still run every tick either way.",
        "live": "Built and tested (EXIT_AGENT_LOCKED_COOLDOWN_S, default off; 4 tests).",
        "ready_when": "you say yes",
        "ready": not (os.getenv("EXIT_AGENT_LOCKED_COOLDOWN_S") or _env_has("EXIT_AGENT_LOCKED_COOLDOWN_S")),   # ON since 2026-10-10
        "note": "Saying yes = set EXIT_AGENT_LOCKED_COOLDOWN_S=3600 in .env and restart the bot. Fully reversible.",
    })
    rules = _load(BOT / "data" / "managers" / "rules.json", []) or []
    earned = [r for r in rules if r.get("status") == "earned"]
    out.append({
        "id": "rules",
        "title": "Rules that have earned their keep",
        "ask": ("Switch these on in the bot: " + ", ".join(f"{r['id']} {r['action']} {r['slice']}" for r in earned)) if earned
               else "None yet.",
        "why": "The Opus rules manager proposes avoid/favor rules; each is scored only on what happens after it was written.",
        "live": f"{sum(r.get('status') == 'shadow' for r in rules)} testing, {len(earned)} earned, {sum(r.get('status') == 'retired' for r in rules)} retired.",
        "ready_when": "a rule earns it on future data",
        "ready": bool(earned),
        "note": "",
    })
    (HM / "decisions.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


if __name__ == "__main__":
    for d in build():
        print(("READY  " if d["ready"] else "waiting ") + d["title"], "|", d["live"])
