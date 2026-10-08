"""Swing desk: renders the hivemind into one page the owner reads while trading.

Writes C:/Users/vince/WAGMI/desk.html (rebuilt after every assemble run).
Order per coin is fixed so the eye always finds things in the same place:
  1 chief analyst's read (lean, conviction, levels, invalidation)
  2 where price is (structure, range bar, history of today's combination)
  3 conditions right now (order book, funding, session, BTC) and rules that apply
  4 the bot (position, latest AI round with report cards)
  5 detail (liquidation clusters, funding/OI), collapsed
"""
import html
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BOT / "tools"))
HM = BOT / "data" / "hivemind"
OUT = BOT.parent / "desk.html"
TERMINAL_OUT = BOT.parent / "terminal.html"


def e(x):
    return html.escape(str(x if x is not None else ""))


def _load(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return d


def _age(iso):
    try:
        s = time.time() - datetime.fromisoformat(iso).timestamp()
    except Exception:
        return "?"
    return f"{int(s // 60)}m ago" if s < 3600 else f"{s / 3600:.1f}h ago"


def _pct(x, d=1):
    return "-" if x is None else f"{x:+.{d}f}%"


def _range_bar(pos):
    if pos is None:
        return ""
    p = max(0.0, min(1.0, pos)) * 100
    return (f"<div class='rbar' title='Position in the 20-day range: {p:.0f}%'>"
            f"<div class='rfill' style='left:{p:.1f}%'></div></div>")


def _hist_line(h):
    if not h or not h.get("next_5d"):
        return "No history for today's combination."
    a, c = h["next_5d"], h.get("next_5d_this_coin") or {}
    s = (f"Historically, on all six coins, this combination went <b>up {a['up_pct']:.0f}%</b> of the time over the "
         f"next 5 days (median {_pct(a['median_pct'])}, middle half {_pct(a['p25_pct'])} to {_pct(a['p75_pct'])}; "
         f"{a['n']} days, about {a['n_eff']} independent)")
    if c.get("n"):
        s += f". This coin alone: up {c['up_pct']:.0f}% (about {c['n_eff']} independent)"
    return s + "."


WORD = {"supports": "order book leans with it", "against": "order book leans against it", "balanced": "order book balanced",
        "side_pays": "this side pays funding", "side_paid": "this side gets paid funding", "neutral": "funding neutral",
        "with": "BTC moving its way", "flat": "BTC flat", "against_btc": "BTC moving against it",
        "asia": "Asia session", "eu": "EU session", "us": "US session", "late": "late US session"}


def _ctx_line(c):
    if not c:
        return ""
    out = []
    for k in ("book", "funding", "btc4h"):
        v = c.get(k)
        if v:
            out.append(WORD.get("against_btc" if k == "btc4h" and v == "against" else v, v))
    return ", ".join(out)


def card(sym, st, chief):
    m = st.get("market") or {}
    h = st.get("history") or {}
    ctx = st.get("context") or {}
    rules = st.get("rules") or {}
    ag = st.get("agents") or {}
    bot = (st.get("bot") or {}).get("position")
    deep = st.get("deep") or {}
    c = chief or {}
    lean = c.get("lean", "-")
    cls = {"LONG": "long", "SHORT": "short"}.get(lean, "neutral")
    o = [f"<section class='coin'><header><h2>{e(sym)}</h2>"
         f"<span class='px'>{e(m.get('price'))}</span>"
         f"<span class='chg'>{_pct(m.get('ret_1d_pct'))} today · {_pct(m.get('ret_7d_pct'))} 7d</span>"
         f"<span class='lean {cls}'>{e(lean)}{(' · conviction ' + str(c.get('conviction'))) if c.get('conviction') else ''}</span></header>"]
    if c:
        o.append(f"<p class='read'>{e(c.get('read'))}</p>"
                 f"<p class='kv'><b>Levels</b> {e(c.get('key_levels'))}</p>"
                 f"<p class='kv'><b>View changes if</b> {e(c.get('invalidation'))}</p>")
    o.append("<h3>Where price is</h3>")
    o.append(f"<p>{e(m.get('structure'))}</p>")
    rng = m.get("range_20d") or {}
    o.append(f"<div class='rrow'><span>{e(rng.get('low'))}</span>{_range_bar(rng.get('position'))}<span>{e(rng.get('high'))}</span></div>"
             f"<p class='muted'>20-day range. A typical day moves about {e(m.get('atr_pct_1d'))}%.</p>")
    o.append(f"<p>{_hist_line(h)}</p><p class='muted'>Today reads as: {e(h.get('state_words'))}. "
             f"History is a base rate, not a forecast.</p>")
    o.append("<h3>Conditions right now</h3><ul>")
    for side in ("LONG", "SHORT"):
        hits = rules.get(side) or []
        rtxt = "; ".join(f"{r['id']} {r['action']} ({'EARNED' if r['status'] == 'earned' else 'testing'})"
                         + (f", only if {'/'.join(r['conditional_on'])} matches" if r.get("conditional_on") else "")
                         for r in hits) if isinstance(hits, list) else ""
        o.append(f"<li><b>For a {side.lower()}:</b> {e(_ctx_line(ctx.get(side)))}"
                 + (f"<br><span class='muted'>Rules: {e(rtxt)}</span>" if rtxt else "") + "</li>")
    o.append("</ul>")
    o.append("<h3>The bot</h3>")
    if bot:
        o.append(f"<p>Holding a <b>{e(bot.get('side'))}</b> from {e(bot.get('entry'))}, stop {e(bot.get('sl'))}, "
                 f"state {e(bot.get('state'))}, banked ${(bot.get('realized_pnl') or 0):.2f}.</p>")
    else:
        o.append("<p class='muted'>No position.</p>")
    roles = (ag.get("roles") or {})
    if roles:
        bits = []
        for r in ("regime", "trade", "risk", "critic"):
            if r in roles:
                v = roles[r]
                bits.append(f"{r}: {e(v['decision'])} <span class='muted'>(track record: "
                            f"{e(v['report_card']['verdict'])})</span>")
        o.append(f"<p>Latest AI round ({ag.get('age_min')} min ago): " + " · ".join(bits) + "</p>")
    else:
        o.append(f"<p class='muted'>{e(ag.get('note', 'No recent AI round on this coin.'))}</p>")
    o.append("<details><summary>Liquidation clusters and funding/OI</summary><pre>"
             + e("\n".join((deep.get("liquidation_magnets") or []) + [""] + (deep.get("funding_oi") or [])))
             + "</pre></details></section>")
    return "".join(o)


CSS_EXTRA = """
.coins{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,430px),1fr));gap:16px}
.coin{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.coin header{display:flex;flex-wrap:wrap;gap:10px;align-items:baseline;margin-bottom:6px}
.coin h2{font-size:22px;margin:0;letter-spacing:0;text-transform:none;color:var(--ink)}
.coin .px{font-size:18px;font-weight:600;font-variant-numeric:tabular-nums}
.coin .chg{color:var(--soft);font-size:13.5px}
.lean{margin-left:auto;font-size:12.5px;font-weight:700;letter-spacing:.06em;padding:3px 9px;border-radius:999px;border:1px solid var(--line)}
.lean.long{color:var(--pos);border-color:var(--pos)} .lean.short{color:var(--neg);border-color:var(--neg)}
.lean.neutral{color:var(--soft)}
.coin h3{font-size:12px;letter-spacing:.09em;text-transform:uppercase;color:var(--soft);margin:14px 0 4px}
.coin p,.coin li{font-size:14.5px;margin:4px 0}
.coin ul{margin:4px 0;padding-left:18px}
.read{font-size:15px!important}
.kv b{color:var(--soft);font-weight:600;margin-right:6px}
.muted{color:var(--soft);font-size:13.5px!important}
.rrow{display:flex;align-items:center;gap:10px;font-size:12.5px;color:var(--soft);font-variant-numeric:tabular-nums}
.rbar{position:relative;flex:1;height:8px;border-radius:4px;background:var(--line)}
.rfill{position:absolute;top:-3px;width:4px;height:14px;border-radius:2px;background:var(--ink);transform:translateX(-2px)}
pre{white-space:pre-wrap;font-size:12.5px;color:var(--soft)}
.top{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin-bottom:18px}
.top p{margin:4px 0}
"""


def build():
    import importlib.util
    spec = importlib.util.spec_from_file_location("wagmi_status_dashboard", BOT / "tools" / "dashboard.py")
    dash = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dash)   # by path: bot/dashboard/ (a package) shadows the name
    allst = _load(HM / "state" / "_all.json", {}) or {}
    chief = _load(HM / "chief_latest.json", {}) or {}
    card_ = _load(HM / "chief_scorecard.json", {}) or {}
    w = (allst.get("shared") or {}).get("weather") or {}
    strat = (allst.get("shared") or {}).get("strategies") or {}
    muted = [k for k, v in strat.items() if isinstance(v, dict) and v.get("weight") == 0]
    h5 = (card_.get("horizons") or {}).get("5d") or {}
    p = ["<div class='wrap' style='max-width:1180px'><h1>WAGMI — swing desk</h1>",
         "<div class='top'>",
         f"<p><b>Chief analyst ({e(chief.get('ts', '?'))}):</b> {e(chief.get('market_note', 'no read yet'))}</p>",
         f"<p class='muted'>Market weather: <b>{e(w.get('regime', '?'))}</b>"
         + (f" ({w['breadth_pct']:.0f}% of coins are above their 20-day average)" if w.get('breadth_pct') is not None else "")
         + ". Context only, not a buy or sell signal.</p>",
         f"<p class='muted'>Chief's track record: {h5.get('n_calls', 0)} calls graded at 5 days"
         + (f", directional calls right {h5['directional_hit'] * 100:.0f}% of the time" if h5.get("directional_hit") is not None else ", still collecting")
         + f". Bot strategies currently muted for a backwards record: {e(', '.join(muted) or 'none')}.</p>",
         f"<p class='muted'>Everything here is measured context plus graded opinions. Nothing in the system has a proven "
         f"directional edge yet; your read decides. Data refreshed {e(_age(allst.get('updated', '')))}.</p>",
         "</div>"]
    import visuals
    import voices as vz
    import web
    p.append("<div class='sec'>Signal web: every voice on every coin</div>"
             "<p class='muted'>▲ blue = favors up, ▼ red = favors down, ● gray = neutral. Faded = context only; "
             "striped = track record is backwards (shown so you see it, not to follow). Hover any cell for the "
             "detail. The grade next to each voice comes from checking it against what price did afterwards.</p>")
    p.append(web.signal_web(allst))
    p.append("<div class='sec'>Coins</div><div class='coins'>")
    for sym, st in (allst.get("coins") or {}).items():
        p.append(visuals.card(sym, st, (chief.get("coins") or {}).get(sym)))
    p.append("</div>")
    p.append("<div class='sec'>Voice guide: what each one is and how to read it</div>")
    p.append(web.voice_guide(vz.INFO, _load(HM / "voice_grades.json", {})))
    p.append("</div>")
    page = ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta http-equiv='refresh' content='300'><title>Swing Desk</title>"
            f"<style>{dash.CSS}{visuals.CSS}{web.CSS}</style></head><body>{''.join(p)}</body></html>")
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(OUT)
    return OUT


def lab_data():
    """What the research has proven, compacted for the terminal's Lab section."""
    LM = BOT / "data" / "laptop_mining"
    coop = _load(LM / "cooperation.json", {}) or {}
    vol = _load(LM / "volatility_forecast.json", {}) or {}
    wf = _load(LM / "walkforward_vol.json", {}) or {}
    geo = _load(LM / "geometry_sweep.json", {}) or {}
    geo2 = _load(LM / "geometry_sweep_pass2.json", {}) or {}
    cells = {c["stop_mult"]: round(c["mean_R"], 3) for c in geo.get("cells", []) + geo2.get("cells", [])
             if c.get("tp_mult") == 1.0}
    curve = sorted(cells.items())
    grades = (_load(HM / "voice_grades.json", {}) or {}).get("voices", {})
    return {
        "agreement": {k: {"e5": v.get("e5"), "e5_ci": v.get("e5_ci"), "n": v.get("n")}
                      for k, v in ((coop.get("agreement") or {}).get("by_k") or {}).items()},
        "bottom_line": coop.get("bottom_line"),
        "vol_calibration": vol.get("y1_calibration_test"),
        "vol_walkforward": {"folds": wf.get("n_folds"), "wins": wf.get("har_beats_naive_folds"),
                            "har_qlike": wf.get("mean_har_qlike"), "naive_qlike": wf.get("mean_naive_qlike")},
        "geometry_curve": curve,
        "geometry_default": (geo.get("bot_default") or {}).get("mean_R"),
        "geometry_live": _load(HM / "geometry_shadow.json", {}) or {},
        "voices": {k: {"trust": v.get("trust"), "mean": v.get("mean_bps_5d"), "ci": v.get("ci95"),
                       "horizon": v.get("horizon", "5d")} for k, v in grades.items()},
        "ic_drops": ((_load(BOT / "data" / "agent_grades" / "live" / "live_scorecard.json", {}) or {})
                     .get("ic_muted_drops")),
    }


def build_terminal():
    """The trading terminal: one self-contained page, data embedded, live prices fetched in the browser."""
    import voices as vz
    allst = _load(HM / "state" / "_all.json", {}) or {}
    chief = _load(HM / "chief_latest.json", {}) or {}
    card_ = (_load(HM / "chief_scorecard.json", {}) or {}).get("horizons", {}).get("5d", {})
    card_txt = (f"{card_.get('n_calls', 0)} calls graded at 5d"
                + (f", directional right {card_['directional_hit'] * 100:.0f}%" if card_.get("directional_hit") is not None
                   else ", still collecting"))
    try:
        token = (HM / "owner_token.txt").read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    data = {"state": allst, "chief": chief, "chiefCard": card_txt, "info": vz.INFO, "ownerToken": token,
            "ownerCard": _load(HM / "owner_scorecard.json", {}) or {}, "lab": lab_data(),
            "decisions": _load(HM / "decisions.json", []) or [],
            "journal": _load(HM / "journal.json", {}) or {},
            "scan": _load(HM / "scan.json", {}) or {}, "plans": _load(HM / "plans.json", {}) or {},
            "tgTrack": _load(HM / "tg" / "track.json", {}) or {},
            "levelStats": ((_load(BOT / "data" / "laptop_mining" / "levels.json", {}) or {}).get("levels") or {}),
            "safeLev": ((_load(BOT / "data" / "laptop_mining" / "safe_leverage.json", {}) or {}).get("table") or {})}
    tpl = (Path(__file__).parent / "terminal.html").read_text(encoding="utf-8")
    page = tpl.replace("__DATA__", json.dumps(data, default=str).replace("</", "<\\/"))
    tmp = TERMINAL_OUT.with_suffix(".tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(TERMINAL_OUT)
    return TERMINAL_OUT


if __name__ == "__main__":
    print(build())
    print(build_terminal())
