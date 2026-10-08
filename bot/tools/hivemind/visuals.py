"""Visual building blocks for the swing desk: one card per coin.

Colors: blue = up / supports, red = down / against (a diverging pair), gray = neutral.
Status chips always carry an icon AND a word so meaning never rides on color alone.
Every chart mark has a hover title. Theme tokens come from tools/dashboard.py CSS.
"""
import html
import re
from datetime import datetime, timezone


def e(x):
    return html.escape(str(x if x is not None else ""))


def _fmt(v):
    if v is None:
        return "-"
    v = float(v)
    return f"{v:,.0f}" if v >= 1000 else f"{v:,.2f}" if v >= 10 else f"{v:,.4f}"


def _pct(x, d=1):
    return "-" if x is None else f"{x:+.{d}f}%"


def _clusters(deep):
    out = []
    for line in deep.get("liquidation_magnets") or []:
        m = re.search(r"cluster \$([\d.,]+) \(([+-][\d.]+)%\) x(\d+)", line)
        if m:
            out.append((float(m.group(1).replace(",", "")), int(m.group(3))))
    return out


def svg_chart(chart, clusters, rng, w=440, h=190):
    """Daily candles + 20/50-day averages + shaded 20-day range + liquidation clusters + price tag."""
    if not chart or not chart.get("ohlc"):
        return ""
    o = chart["ohlc"]
    lows = [b[2] for b in o] + [c for c, _ in clusters]
    highs = [b[1] for b in o] + [c for c, _ in clusters]
    lo, hi = min(lows), max(highs)
    pad = (hi - lo) * 0.06 or 1
    lo, hi = lo - pad, hi + pad
    L, R, T, B = 6, 70, 8, 20
    n = len(o)
    step = (w - L - R) / n
    X = lambda i: L + i * step + step / 2
    Y = lambda v: T + (hi - v) / (hi - lo) * (h - T - B)
    s = [f"<svg viewBox='0 0 {w} {h}' class='pc' role='img' aria-label='Daily price chart'>"]
    if rng.get("low") and rng.get("high"):
        x0 = X(max(0, n - 20)) - step / 2
        s.append(f"<rect class='band' x='{x0:.1f}' y='{Y(rng['high']):.1f}' width='{w - R - x0:.1f}' "
                 f"height='{Y(rng['low']) - Y(rng['high']):.1f}'><title>20-day range {_fmt(rng['low'])} to "
                 f"{_fmt(rng['high'])}</title></rect>")
    for i, (op, hh, ll, cl) in enumerate(o):
        cls = "cu" if cl >= op else "cd"
        d = datetime.fromtimestamp(chart["t"][i] / 1000, timezone.utc).strftime("%b %d")
        s.append(f"<g class='{cls}'><title>{d}: open {_fmt(op)}, high {_fmt(hh)}, low {_fmt(ll)}, close {_fmt(cl)}</title>"
                 f"<line x1='{X(i):.1f}' x2='{X(i):.1f}' y1='{Y(hh):.1f}' y2='{Y(ll):.1f}'/>"
                 f"<rect x='{X(i) - step * 0.32:.1f}' y='{Y(max(op, cl)):.1f}' width='{step * 0.64:.1f}' "
                 f"height='{max(1.0, abs(Y(op) - Y(cl))):.1f}' rx='1'/></g>")
    for key, cls in (("ema50", "e50"), ("ema20", "e20")):
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(chart.get(key) or []))
        s.append(f"<polyline class='{cls}' points='{pts}'/>")
    last_y = Y(o[-1][3])
    for price, cnt in clusters[:4]:
        y = Y(price)
        label = abs(y - last_y) > 12   # don't print over the current-price tag
        s.append(f"<g class='liq'><title>Liquidation cluster {_fmt(price)}: {cnt} forced closes in 7 days</title>"
                 f"<line x1='{w - R - 34}' x2='{w - R}' y1='{y:.1f}' y2='{y:.1f}'/>"
                 + (f"<text x='{w - R + 4}' y='{y + 3.5:.1f}'>liq {_fmt(price)}</text>" if label else "") + "</g>")
    last = o[-1][3]
    s.append(f"<line class='now' x1='{L}' x2='{w - R}' y1='{Y(last):.1f}' y2='{Y(last):.1f}'/>"
             f"<rect class='nowtag' x='{w - R + 2}' y='{Y(last) - 8:.1f}' width='{R - 4}' height='16' rx='3'/>"
             f"<text class='nowtxt' x='{w - R + 6}' y='{Y(last) + 4:.1f}'>{_fmt(last)}</text>")
    for i in range(4, n, 14):
        d = datetime.fromtimestamp(chart["t"][i] / 1000, timezone.utc).strftime("%b %d")
        s.append(f"<text x='{X(i):.1f}' y='{h - 5}' text-anchor='middle'>{d}</text>")
    s.append("</svg>")
    return "".join(s)


def gauge_trend(m):
    note = m.get("structure") or ""
    up = "structure UP" in note
    sub = ("pulling back" if "pullback" in note else "bouncing" if "bounce" in note
           else "pushing higher" if up else "pushing lower")
    return (f"<div class='g'><div class='gl'>Trend</div><div class='tr {'up' if up else 'dn'}'>"
            f"{'▲ Uptrend' if up else '▼ Downtrend'}</div><div class='gv'>{sub}</div></div>")


def gauge_control(di):
    if not di:
        return "<div class='g'><div class='gl'>Who's in control</div><div class='gv'>n/a</div></div>"
    tot = (di["plus"] + di["minus"]) or 1
    b = di["plus"] / tot * 100
    who = "Buyers" if di["plus"] > di["minus"] else "Sellers"
    return (f"<div class='g'><div class='gl'>Who's in control</div>"
            f"<div class='split' title='Buyers {di['plus']} vs sellers {di['minus']} (+DI / -DI)'>"
            f"<div class='sb' style='width:{b:.0f}%'></div><div class='ss' style='width:{100 - b:.0f}%'></div></div>"
            f"<div class='gv'>{who} {max(b, 100 - b):.0f}%</div></div>")


def gauge_range(rng):
    pos = rng.get("position")
    if pos is None:
        return "<div class='g'><div class='gl'>20-day range</div><div class='gv'>n/a</div></div>"
    p = max(0.0, min(1.0, pos)) * 100
    where = ("below the low" if pos < 0 else "above the high" if pos > 1 else "near the low" if p < 20
             else "near the high" if p > 80 else "lower half" if p < 50 else "upper half")
    return (f"<div class='g'><div class='gl'>20-day range</div><div class='rbar' title='{p:.0f}% of the way from low to high'>"
            f"<div class='rfill' style='left:{p:.1f}%'></div></div><div class='gv'>{where} ({pos * 100:.0f}%)</div></div>")


def history_viz(h):
    a = (h or {}).get("next_5d")
    if not a or not a.get("n"):
        return ""
    up = a["up_pct"]
    lo, hi = -15.0, 15.0
    X = lambda v: (max(lo, min(hi, v)) - lo) / (hi - lo) * 100
    return (f"<div class='hist'><div class='hl'>When the chart looked like this before, the next 5 days "
            f"<span class='muted'>({a['n']} times since {e((h.get('history_since') or '')[:4])}, about "
            f"{a['n_eff']} independent)</span></div>"
            f"<div class='updn' title='Went up {up:.0f}% of the time, down {100 - up:.0f}%'>"
            f"<div class='u' style='width:{up:.0f}%'>▲ up {up:.0f}%</div>"
            f"<div class='d' style='width:{100 - up:.0f}%'>▼ {100 - up:.0f}%</div></div>"
            f"<div class='box' title='Middle half of outcomes {a['p25_pct']:+.1f}% to {a['p75_pct']:+.1f}%, "
            f"median {a['median_pct']:+.1f}%'><div class='axis'></div><div class='zero' style='left:{X(0):.1f}%'></div>"
            f"<div class='iqr' style='left:{X(a['p25_pct']):.1f}%;width:{X(a['p75_pct']) - X(a['p25_pct']):.1f}%'></div>"
            f"<div class='med' style='left:{X(a['median_pct']):.1f}%'></div>"
            f"<span class='bl'>-15%</span><span class='bz' style='left:{X(0):.1f}%'>0</span><span class='br'>+15%</span></div>"
            f"<div class='muted'>Shaded bar = the middle half of outcomes ({a['p25_pct']:+.1f}% to {a['p75_pct']:+.1f}%); "
            f"dark tick = median ({a['median_pct']:+.1f}%). The past, not a forecast.</div></div>")


GOOD, BAD, MEH = "good", "bad", "meh"
ICON = {GOOD: "✔", BAD: "✖", MEH: "•"}


def chips(c):
    out = []
    book = c.get("book")
    if book:
        out.append((GOOD if book == "supports" else BAD if book == "against" else MEH,
                    {"supports": "Order book helps", "against": "Order book fights", "balanced": "Order book even"}[book]))
    f = c.get("funding")
    if f:
        out.append((GOOD if f == "side_paid" else BAD if f == "side_pays" else MEH,
                    {"side_paid": "Paid to hold", "side_pays": "Pays to hold", "neutral": "Funding neutral"}[f]))
    b = c.get("btc4h")
    if b:
        out.append((GOOD if b == "with" else BAD if b == "against" else MEH,
                    {"with": "BTC helping", "against": "BTC against", "flat": "BTC flat"}[b]))
    return "".join(f"<span class='chip {k}'>{ICON[k]} {e(t)}</span>" for k, t in out)


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
    conv = int(c.get("conviction") or 0)
    dots = "".join(f"<i class='{'on' if i < conv else ''}'></i>" for i in range(5))
    chg = m.get("ret_1d_pct")
    o = [f"<section class='coin'><header><h2>{e(sym)}</h2><span class='px'>{_fmt(m.get('price'))}</span>"
         f"<span class='chgc {'pos' if (chg or 0) >= 0 else 'neg'}'>{'▲' if (chg or 0) >= 0 else '▼'} {_pct(chg)} today</span>"
         f"<span class='lean {cls}' title='Chief analyst: {e(lean)}, conviction {conv} of 5'>{e(lean)}"
         f"<span class='dots'>{dots}</span></span></header>"]
    o.append(svg_chart(st.get("chart"), _clusters(deep), m.get("range_20d") or {}))
    o.append("<div class='legend'><span><i class='lg e20'></i>20-day avg</span><span><i class='lg e50'></i>50-day avg</span>"
             "<span><i class='lg band'></i>20-day range</span><span><i class='lg liq'></i>liquidation cluster</span></div>")
    o.append(f"<div class='gauges'>{gauge_trend(m)}{gauge_control(m.get('di'))}{gauge_range(m.get('range_20d') or {})}</div>")
    o.append(history_viz(h))
    from web import contradictions_html
    o.append(contradictions_html(st))
    o.append("<div class='cond'>")
    for side in ("LONG", "SHORT"):
        hits = rules.get(side) or []
        rch = "".join(f"<span class='chip rule' title='{e(r.get('thesis'))}'>{e(r['id'])} "
                      f"{'avoid' if r['action'] == 'avoid' else 'favor'}{' ✓ earned' if r['status'] == 'earned' else ' · testing'}</span>"
                      for r in hits) if isinstance(hits, list) else ""
        o.append(f"<div class='crow'><span class='cs {side.lower()}'>If {side.lower()}</span>{chips(ctx.get(side) or {})}{rch}</div>")
    o.append("</div>")
    if bot:
        o.append(f"<div class='botpos {'short' if bot.get('side') == 'SHORT' else 'long'}'>Bot is <b>{e(bot.get('side'))}</b> "
                 f"from {_fmt(bot.get('entry'))} · stop {_fmt(bot.get('sl'))} · banked ${(bot.get('realized_pnl') or 0):.2f}</div>")
    if c:
        o.append(f"<details class='why'><summary>Chief analyst's read</summary><p>{e(c.get('read'))}</p>"
                 f"<p><b>Levels:</b> {e(c.get('key_levels'))}</p><p><b>View changes if:</b> {e(c.get('invalidation'))}</p></details>")
    roles = ag.get("roles") or {}
    if roles:
        bits = " · ".join(f"{r}: {e(roles[r]['decision'])} ({e(roles[r]['report_card']['verdict'])})"
                          for r in ("regime", "trade", "risk", "critic") if r in roles)
        o.append(f"<details class='why'><summary>Bot's AI ({ag.get('age_min')} min ago)</summary><p>{bits}</p></details>")
    o.append("</section>")
    return "".join(o)


CSS = """
:root{--good:#0ca30c;--bad:#d03b3b;--goodbg:#e7f5e7;--badbg:#fbeaea;--mehbg:#efeeea;--liq:#c98500}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--good:#4cc24c;--bad:#e66767;--goodbg:#1c2b1c;--badbg:#2e1c1c;--mehbg:#26282b;--liq:#eda100}}
:root[data-theme="dark"]{--good:#4cc24c;--bad:#e66767;--goodbg:#1c2b1c;--badbg:#2e1c1c;--mehbg:#26282b;--liq:#eda100}
.coins{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:16px}
.coin{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px}
.coin header{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:4px}
.coin h2{font-size:22px;margin:0;letter-spacing:0;text-transform:none;color:var(--ink)}
.px{font-size:18px;font-weight:600;font-variant-numeric:tabular-nums}
.chgc{font-size:13px;font-weight:600;padding:2px 8px;border-radius:999px;background:var(--mehbg)}
.chgc.pos{color:var(--pos)} .chgc.neg{color:var(--neg)}
.lean{margin-left:auto;display:flex;align-items:center;gap:8px;font-size:13px;font-weight:700;letter-spacing:.06em;
      padding:4px 10px;border-radius:999px;border:1.5px solid var(--line)}
.lean.long{color:var(--pos);border-color:var(--pos)} .lean.short{color:var(--neg);border-color:var(--neg)} .lean.neutral{color:var(--soft)}
.dots{display:inline-flex;gap:3px} .dots i{width:7px;height:7px;border-radius:50%;background:var(--line);display:block}
.dots i.on{background:currentColor}
.pc{width:100%;height:auto;display:block;margin:4px 0 0}
.pc text{fill:var(--soft);font-size:10.5px;font-variant-numeric:tabular-nums}
.pc .cu line,.pc .cu rect{stroke:var(--pos);fill:var(--pos)} .pc .cd line,.pc .cd rect{stroke:var(--neg);fill:var(--neg)}
.pc g:hover{opacity:.65}
.pc .e20{fill:none;stroke:var(--ink);stroke-width:1.6;opacity:.7}
.pc .e50{fill:none;stroke:var(--soft);stroke-width:1.6;stroke-dasharray:4 3}
.pc .band{fill:var(--soft);opacity:.12}
.pc .liq line{stroke:var(--liq);stroke-width:3;stroke-linecap:round} .pc .liq text{fill:var(--liq)}
.pc .now{stroke:var(--ink);stroke-width:1;stroke-dasharray:2 3;opacity:.55}
.pc .nowtag{fill:var(--ink)} .pc .nowtxt{fill:var(--panel);font-weight:700}
.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:11.5px;color:var(--soft);margin:2px 0 8px}
.legend i.lg{display:inline-block;width:14px;height:3px;vertical-align:middle;margin-right:5px}
.lg.e20{background:var(--ink);opacity:.7} .lg.e50{border-top:2px dashed var(--soft);height:0!important}
.lg.band{background:var(--soft);opacity:.3;height:9px!important} .lg.liq{background:var(--liq)}
.gauges{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:6px 0 10px}
.g{background:var(--bg);border-radius:10px;padding:8px 10px}
.gl{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--soft)}
.gv{font-size:12.5px;color:var(--soft);margin-top:3px}
.tr{font-size:17px;font-weight:700;margin-top:2px} .tr.up{color:var(--pos)} .tr.dn{color:var(--neg)}
.split{display:flex;height:10px;border-radius:5px;overflow:hidden;margin-top:8px;gap:2px}
.sb{background:var(--pos)} .ss{background:var(--neg)}
.rbar{position:relative;height:10px;border-radius:5px;margin-top:8px;background:var(--line)}
.rfill{position:absolute;top:-4px;width:5px;height:18px;border-radius:2px;background:var(--ink);transform:translateX(-2.5px)}
.hist{background:var(--bg);border-radius:10px;padding:9px 11px;margin:0 0 10px}
.hl{font-size:13px;margin-bottom:6px}
.updn{display:flex;height:22px;border-radius:6px;overflow:hidden;gap:2px;font-size:12px;font-weight:700;color:#fff}
.updn .u{background:var(--pos);display:flex;align-items:center;padding-left:8px;white-space:nowrap}
.updn .d{background:var(--neg);display:flex;align-items:center;justify-content:flex-end;padding-right:8px;white-space:nowrap}
.box{position:relative;height:30px;margin:8px 0 2px}
.box .axis{position:absolute;top:16px;left:0;right:0;height:2px;background:var(--line)}
.box .zero{position:absolute;top:8px;width:1px;height:18px;background:var(--soft)}
.box .iqr{position:absolute;top:10px;height:14px;border-radius:4px;background:var(--accent);opacity:.35}
.box .med{position:absolute;top:7px;width:3px;height:20px;border-radius:2px;background:var(--ink);transform:translateX(-1.5px)}
.box .bl,.box .br,.box .bz{position:absolute;top:-4px;font-size:10px;color:var(--soft)}
.box .bl{left:0} .box .br{right:0} .box .bz{transform:translateX(-3px)}
.cond{display:flex;flex-direction:column;gap:6px;margin-bottom:8px}
.crow{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.cs{font-size:12px;font-weight:700;width:64px} .cs.long{color:var(--pos)} .cs.short{color:var(--neg)}
.chip{font-size:12px;padding:3px 8px;border-radius:999px;background:var(--mehbg);color:var(--ink)}
.chip.good{background:var(--goodbg);color:var(--good)} .chip.bad{background:var(--badbg);color:var(--bad)}
.chip.rule{border:1px dashed var(--soft);background:transparent;color:var(--soft)}
.botpos{font-size:13.5px;padding:7px 10px;border-radius:8px;background:var(--bg);border-left:3px solid var(--soft);margin-bottom:6px}
.botpos.short{border-left-color:var(--neg)} .botpos.long{border-left-color:var(--pos)}
.why{font-size:13.5px;color:var(--soft);margin-top:4px} .why p{margin:4px 0}
.why summary{cursor:pointer;color:var(--ink)}
.top{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px 20px;margin-bottom:18px}
.top p{margin:4px 0}
.muted{color:var(--soft);font-size:12.5px}
@media (max-width:520px){.gauges{grid-template-columns:1fr}}
"""
