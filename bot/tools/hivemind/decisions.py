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


def build():
    out = []
    g = _load(HM / "geometry_shadow.json", {}) or {}
    ad = g.get("adaptive") or {}
    ready_g = bool(ad.get("ci95") and ad["ci95"][0] > 0 and ad.get("n", 0) >= 60) or \
        bool(g.get("ci95") and g["ci95"][0] > 0 and g.get("n", 0) >= 60)
    out.append({
        "id": "bot-stops",
        "title": "Widen the bot's stops",
        "ask": "Switch the bot from its tight stops to stops sized at 2x the forecast daily move, 0.5R target, 48h time limit.",
        "why": ("Tight stops lose about 0.4R per trade even on random entries. Laptop: +0.54R better when wider on held-out "
                "data, and it won in 4 of 4 walk-forward periods (+0.50R average). It reduces losses; it does not make bad periods good."),
        "live": (f"Live paired test, {g.get('n', 0)} signals: current {g.get('mean_r_current')}R, wider {g.get('mean_r_proposal')}R, "
                 f"forecast-sized {ad.get('mean_r', '-')}R (gain {ad.get('paired_diff_vs_current', '-')}R, "
                 f"range {ad.get('ci95', ['-', '-'])[0]} to {ad.get('ci95', ['-', '-'])[1]})."),
        "ready_when": "the live gain's whole range is above zero with 60+ signals",
        "ready": ready_g,
        "note": ("This removes a loss; it does not create a profit edge. Already built and tested, switched off, on branch "
                 "claude/adaptive-stops (ADAPTIVE_STOPS=true, with TIME_STOP_HOURS 8 -> 48): saying yes = merge, set both, restart when flat."),
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
        "ready": d.get("n", 0) >= 30 and flip is not None,
        "note": ("Recommendation: KEEP the gate. The dropped signals would have lost money; letting some through only buys "
                 "losing trades. Doing nothing = keeping it." if d.get("n", 0) >= 30 and (d.get("mean_bps") or 0) < 0 else ""),
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
