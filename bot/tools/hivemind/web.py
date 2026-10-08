"""Signal web, contradictions and the voice guide for the swing desk."""
from visuals import e

TRUST_WORD = {"earned": "earned", "promising": "promising", "unproven": "unproven", "context": "context only",
              "backwards": "backwards"}

ORDER = ["structure", "stretch", "driver", "structure_4h", "stretch_4h", "driver_4h", "momentum_7d", "rsi", "history_5d", "range", "funding", "oi",
         "liq_skew", "book", "btc", "top_traders", "weather", "copilot", "strategies", "trade_agent", "rules", "chief", "bot_position"]


def _cell(v):
    if v is None:
        return "<td class='wc none'>·</td>"
    r = v["reading"]
    cls = "up" if r == 1 else "dn" if r == -1 else "nt"
    sym = "▲" if r == 1 else "▼" if r == -1 else "●"
    return (f"<td class='wc {cls} t-{v['trust']}' title='{e(v['label'])}: {e(v['detail'])} (track record: "
            f"{e(TRUST_WORD.get(v['trust'], v['trust']))})'>{sym}</td>")


def signal_web(allst):
    coins = list((allst.get("coins") or {}).keys())
    by = {c: {v["voice"]: v for v in (allst["coins"][c].get("voices") or [])} for c in coins}
    labels, trusts = {}, {}
    for c in coins:
        for k, v in by[c].items():
            labels[k], trusts[k] = v["label"], v["trust"]
    h = ["<div class='web'><table><thead><tr><th class='wv'>Voice <span class='muted'>(track record)</span></th>"]
    h += [f"<th>{e(c)}</th>" for c in coins] + ["</tr></thead><tbody>"]
    for k in [k for k in ORDER if k in labels]:
        h.append(f"<tr><th class='wv'>{e(labels[k])} <span class='tb t-{trusts[k]}'>"
                 f"{e(TRUST_WORD.get(trusts[k], trusts[k]))}</span></th>")
        h += [_cell(by[c].get(k)) for c in coins]
        h.append("</tr>")
    h.append("<tr class='sum'><th class='wv'>Agreement <span class='muted'>(bullish vs bearish voices)</span></th>")
    for c in coins:
        cs = allst["coins"][c].get("consensus") or {}
        b, s = cs.get("bull", 0), cs.get("bear", 0)
        tot = (b + s) or 1
        h.append(f"<td title='{b} bullish voices from {cs.get('bull_families', 0)} families, {s} bearish from "
                 f"{cs.get('bear_families', 0)}; trust-weighted score {cs.get('trust_weighted', 0):+.2f}'>"
                 f"<div class='ag'><div class='agb' style='width:{b / tot * 100:.0f}%'></div>"
                 f"<div class='ags' style='width:{s / tot * 100:.0f}%'></div></div><div class='agt'>{b}▲ {s}▼</div></td>")
    h.append("</tr></tbody></table></div>")
    return "".join(h)


def contradictions_html(st):
    cs = st.get("contradictions") or []
    if not cs:
        return ""
    items = "".join(f"<li><span class='cu2'>▲ {e(c['bull'])}</span> <span class='muted'>({e(c['bull_detail'])})</span> vs "
                    f"<span class='cd2'>▼ {e(c['bear'])}</span> <span class='muted'>({e(c['bear_detail'])})</span></li>"
                    for c in cs[:3])
    return f"<div class='contra'><div class='gl'>Where the voices disagree</div><ul>{items}</ul></div>"


def voice_guide(info, grades):
    g = (grades or {}).get("voices") or {}
    out = ["<div class='guide'>"]
    for k in ORDER:
        if k not in info:
            continue
        what, read = info[k]
        gr = g.get(k) or {}
        rec = ""
        if gr.get("mean_bps_5d") is not None and gr.get("ci95"):
            ci = gr["ci95"]
            rec = (f"<div class='rec t-{e(gr.get('trust'))}'>Track record ({e(gr.get('source'))}, since 2024): "
                   f"{gr['mean_bps_5d'] / 100:+.2f}% per 5 days when followed, likely range {ci[0] / 100:+.2f}% to "
                   f"{ci[1] / 100:+.2f}%, about {gr.get('n_eff')} independent periods. "
                   f"<b>{e(TRUST_WORD.get(gr.get('trust'), gr.get('trust')))}</b></div>")
        out.append(f"<details class='gi'><summary>{e(k.replace('_', ' '))}</summary><p><b>What it is:</b> {e(what)}</p>"
                   f"<p><b>How to read it:</b> {e(read)}</p>{rec}</details>")
    out.append("</div>")
    return "".join(out)


CSS = """
.web{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:10px 12px;margin-bottom:18px;overflow-x:auto}
.web table{border-collapse:separate;border-spacing:3px;width:100%;font-size:13px}
.web th{font-weight:600;text-align:center;color:var(--ink);padding:4px 6px}
.web th.wv{text-align:left;font-weight:500;white-space:nowrap}
.wc{text-align:center;border-radius:6px;padding:5px 0;font-size:13px;min-width:44px;cursor:default}
.wc.up{background:var(--pos);color:#fff} .wc.dn{background:var(--neg);color:#fff} .wc.nt{background:var(--mehbg);color:var(--soft)}
.wc.none{color:var(--line)}
.wc.t-context{opacity:.5}
.wc.t-backwards{opacity:.4;background-image:repeating-linear-gradient(45deg,transparent 0 4px,rgba(255,255,255,.4) 4px 6px)}
.wc.t-earned{box-shadow:inset 0 0 0 2px var(--ink)}
.tb{font-size:10.5px;padding:1px 6px;border-radius:999px;margin-left:4px;background:var(--mehbg);color:var(--soft)}
.tb.t-earned{background:var(--goodbg);color:var(--good)} .tb.t-promising{color:var(--pos)} .tb.t-backwards{background:var(--badbg);color:var(--bad)}
.sum td{padding-top:6px}
.ag{display:flex;height:9px;border-radius:5px;overflow:hidden;gap:2px} .agb{background:var(--pos)} .ags{background:var(--neg)}
.agt{font-size:11.5px;color:var(--soft);text-align:center;margin-top:2px}
.contra{background:var(--bg);border-radius:10px;padding:8px 11px;margin:0 0 10px}
.contra ul{margin:4px 0 0;padding-left:16px;font-size:13px} .contra li{margin:3px 0}
.cu2{color:var(--pos);font-weight:600} .cd2{color:var(--neg);font-weight:600}
.guide{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:8px;margin-top:10px}
.gi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 12px;font-size:13.5px}
.gi summary{cursor:pointer;font-weight:600;text-transform:capitalize}
.gi p{margin:5px 0;color:var(--ink)} .rec{font-size:12.5px;color:var(--soft);margin-top:4px}
.rec.t-backwards b{color:var(--bad)} .rec.t-earned b{color:var(--good)} .rec.t-promising b{color:var(--pos)}
.sec{font-size:13px;font-weight:600;letter-spacing:.09em;text-transform:uppercase;color:var(--soft);margin:22px 0 8px}
"""
