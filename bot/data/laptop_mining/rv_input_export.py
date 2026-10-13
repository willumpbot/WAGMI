"""RV-input export for the laptop's check D3 (exp_move definition drift).

READ-ONLY. For the 6 bot coins, right now, records for every live implementation of "expected size of
tomorrow's move (%)" the bar source, last bar used (and whether it was really complete), rv1/rv5/rv22,
the log-forecast z, smearing, stage-2 adjustment, and the final number. Then swaps one input at a time to
localise the disagreement.

Implementations instrumented (line refs are to the files as of 2026-10-13):
  A  assemble vol voice   tools/hivemind/assemble.py:288-297  -> volforecast.forecast(..., dis6, fday, btc_rv5)
                          bars: basemap._closed(basemap._daily(sym))  (basemap.py:31-49, 20h file cache)
                          stage-2: volforecast.py:26-33 / 54-61
  B  scanner exp_move     tools/hivemind/scanner.py:88-101 -> volforecast.forecast(c)  (stage-1 + 0.8 above 3.9)
                          bars: hl.candles(...,'1d', ttl=600) filtered t+1d<=now   (fresh)
                          (stop_shadow._exp_move, stop_shadow.py:54-58, is the same recipe with an entry-time end)
  C  risk voice           tools/hivemind/assemble.py:312-326 -> risk_voice.risk_read(sym, df)
                          bars: same basemap df as A (.tail(60)); risk_voice.py:81-103, no stage-2, no 0.8 cut
  D  Opus chief           data/hivemind/chief_calls.jsonl latest expected_move_pct (+ the har_move_pct it was shown)

Does not call basemap._daily (it rewrites the cache file when stale); replicates basemap.py:40-42 on the
cached JSON instead and calls the real basemap._closed. HL requests go through tools/hivemind/hl.py.
Writes only RV_INPUT_EXPORT.json / RV_INPUT_EXPORT.md next to this file.
"""
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOT = HERE.parents[1]
sys.path.insert(0, str(BOT / "tools" / "hivemind"))
import hl          # noqa: E402
import basemap     # noqa: E402
import volforecast  # noqa: E402
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("laptop_risk_voice", HERE / "risk_voice.py")
risk_voice = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(risk_voice)

import pandas as pd  # noqa: E402

SYMS = ["BTC", "ETH", "SOL", "HYPE", "NEAR", "XRP"]
DAY = 86_400_000
EPS = 1e-8
COEF = json.loads((HERE / "volatility_forecast.json").read_text(encoding="utf-8"))
VERR = json.loads((HERE / "vol_error.json").read_text(encoding="utf-8"))
B1, SM1 = COEF["y1_beta"], COEF["y1_smearing"]
S2C, S1SM, S2SM = VERR["stage2_coef"], VERR["stage1_smearing"], VERR["stage2_smearing"]


def iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M")


def rv(closes):
    """volforecast.py:41-47 exactly (percent simple returns, sample sd ddof=1)."""
    r = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))]

    def sd(x):
        m = sum(x) / len(x)
        return (sum((v - m) ** 2 for v in x) / (len(x) - 1)) ** 0.5
    return abs(r[-1]), sd(r[-5:]), sd(r[-22:])


def z_of(rv1, rv5, rv22):
    """volforecast.py:52 / risk_voice.py:100-103 (identical betas from volatility_forecast.json)."""
    return B1[0] + B1[1] * math.log(rv1 + EPS) + B1[2] * math.log(rv5 + EPS) + B1[3] * math.log(rv22 + EPS)


def stage1_cut(z):
    """volforecast.py:53,64-65 (no stage-2 inputs): exp(z)*1.7389, x0.8 if >=3.9."""
    p = math.exp(z) * SM1
    return p * 0.8 if p >= 3.9 else p


def stage1_raw(z):
    """risk_voice.py:103: exp(z)*1.7389, no haircut."""
    return math.exp(z) * SM1


def stage2_parts(z, dis6, fday, brv):
    """volforecast.py:57 + 26-33, returned decomposed."""
    raw1 = math.exp(z) * S1SM
    t_int, t_dis, t_fund, t_btc = S2C[0], S2C[1] * dis6, S2C[2] * fday, S2C[3] * math.log(brv + EPS)
    adj = math.exp(t_int + t_dis + t_fund + t_btc)
    pred2 = raw1 * adj * S2SM
    hair = pred2 >= volforecast.TOP20_CUT
    return {"stage1_smearing_used": S1SM, "raw1": raw1, "log_terms": {"intercept": t_int, "disagree": t_dis,
            "funding": t_fund, "btc_rv5": t_btc}, "adj": adj, "stage2_smearing": S2SM, "pred2_pre_haircut": pred2,
            "top20_haircut_0.8_applied": hair, "final": pred2 * 0.8 if hair else pred2}


def basemap_df(sym):
    """basemap.py:40-42 on the cached file (no rewrite), then the real basemap._closed (basemap.py:45-49)."""
    path = basemap.CACHE / f"{sym}_1d.json"
    raw = json.loads(path.read_text())
    df = pd.DataFrame([{"t": int(b["t"]), "o": float(b["o"]), "h": float(b["h"]), "l": float(b["l"]),
                        "c": float(b["c"]), "n": int(b.get("n", -1))} for b in raw]).sort_values("t").reset_index(drop=True)
    return df, path.stat().st_mtime, raw


def stale_bar_sensitivity(fresh, now_ms, days=20, hours=(2, 6, 12, 18, 23)):
    """How wrong the stage-1 forecast gets when the last 'closed' daily bar is really a partial snapshot taken
    h hours into its day (what basemap's 20h cache + _closed produces between 00:00 UTC and the next rebuild).
    For each of the last `days` completed days: replace that day's close by the 1h close at hour h, recompute
    rv1/rv5/rv22 -> stage-1 forecast, compare with the true close. Reports |log ratio| median / p90 per h."""
    res = {}
    for s, daily in fresh.items():
        closed = [b for b in daily if b["t"] + DAY <= now_ms]
        c = [float(b["c"]) for b in closed]
        ts = [int(b["t"]) for b in closed]
        h1 = hl.candles(s, "1h", ts[-days] - DAY, now_ms, ttl=3600) or []
        hc = {int(b["t"]): float(b["c"]) for b in h1}
        per_h = {h: [] for h in hours}
        for k in range(len(c) - days, len(c)):
            base = c[:k + 1]
            if len(base) < 23:
                continue
            ftrue = math.exp(z_of(*rv(base))) * SM1
            for h in hours:
                ph = hc.get(ts[k] + (h - 1) * 3_600_000)     # close of the h-th hour of day k
                if ph is None:
                    continue
                fpart = math.exp(z_of(*rv(base[:-1] + [ph]))) * SM1
                per_h[h].append(abs(math.log(fpart / ftrue)))
        res[s] = {}
        for h, xs in per_h.items():
            if xs:
                xs.sort()
                res[s][f"h{h}"] = {"n": len(xs), "median_abs_logpts": xs[len(xs) // 2],
                                   "p90_abs_logpts": xs[min(len(xs) - 1, int(0.9 * len(xs)))], "max_abs_logpts": xs[-1]}
    return res


def main():
    now = time.time()
    now_ms = int(now * 1000)
    today0 = now_ms - now_ms % DAY
    out = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "coins": {},
           "coefficients": {"y1_beta": B1, "y1_smearing": SM1, "stage1_smearing(vol_error.json)": S1SM,
                            "stage2_coef[int,disagree,funding_day_pct,log_btc_rv5]": S2C, "stage2_smearing": S2SM,
                            "TOP20_CUT": volforecast.TOP20_CUT, "stage1_fallback_cut": 3.9}}
    # BTC rv5 the way assemble._btc_rv5 does it (assemble.py:280-285): basemap closed, last 6 closes
    bdf, _, _ = basemap_df("BTC")
    bc = basemap._closed(bdf)["c"].tolist()[-6:]
    br = [(bc[i] / bc[i - 1] - 1) * 100 for i in range(1, len(bc))]
    m = sum(br) / len(br)
    btc_rv5_basemap = (sum((x - m) ** 2 for x in br) / (len(br) - 1)) ** 0.5
    fresh = {s: hl.candles(s, "1d", now_ms - 400 * DAY, now_ms, ttl=600) for s in SYMS}
    fb = [float(b["c"]) for b in fresh["BTC"] if b["t"] + DAY <= now_ms][-6:]
    fr = [(fb[i] / fb[i - 1] - 1) * 100 for i in range(1, len(fb))]
    m = sum(fr) / len(fr)
    btc_rv5_fresh = (sum((x - m) ** 2 for x in fr) / (len(fr) - 1)) ** 0.5

    chief = {}
    try:
        with open(BOT / "data" / "hivemind" / "chief_calls.jsonl", encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("symbol") in SYMS and r.get("expected_move_pct") is not None:
                    chief[r["symbol"]] = r
    except OSError:
        pass

    for s in SYMS:
        rec = {}
        st = json.loads((BOT / "data" / "hivemind" / "state" / f"{s}.json").read_text(encoding="utf-8"))
        cs = st.get("consensus") or {}
        n_f = (cs.get("bull_families") or 0) + (cs.get("bear_families") or 0)
        dis6 = (cs.get("dissent_families") or 0) / n_f * 6.0 if n_f else None      # assemble.py:412
        fh_ = (st.get("market") or {}).get("funding_hourly")
        fday = fh_ * 24 * 100 if fh_ is not None else None                          # assemble.py:292

        # ---------- basemap path (A and C share it) ----------
        df, mtime, raw = basemap_df(s)
        dfc = basemap._closed(df)
        last = dfc.iloc[-1]
        last_t = int(last["t"])
        complete = mtime * 1000 >= last_t + DAY
        cl_A = dfc["c"].tolist()[-40:]                    # assemble.py:297
        rvA = rv(cl_A)
        zA = z_of(*rvA)
        s2A = stage2_parts(zA, dis6, fday, btc_rv5_basemap) if None not in (dis6, fday) else None
        fA_real = volforecast.forecast(cl_A, dis6, fday, btc_rv5_basemap)   # the real function
        cl_C = dfc.tail(60)                                                  # assemble.py:322
        rC = risk_voice.risk_read(s, cl_C, "long")                           # the real function
        rvC = risk_voice._rv(risk_voice._series(cl_C))
        zC = z_of(rvC["rv1"], rvC["rv5"], rvC["rv22"])
        zero_n_used = int((dfc.tail(23)["n"] == 0).sum())
        zero_n_all = int((df["n"] == 0).sum())

        # ---------- fresh HL path (B) ----------
        fr_ = fresh[s]
        closed = [b for b in fr_ if b["t"] + DAY <= now_ms]                  # scanner.py:92
        cl_B = [float(b["c"]) for b in closed]
        rvB = rv(cl_B)
        zB = z_of(*rvB)
        fB_real = volforecast.forecast(cl_B) or {}                           # scanner.py:100
        zero_n_B = sum(1 for b in closed[-23:] if int(b.get("n", -1)) == 0)
        forming = [b for b in fr_ if b["t"] + DAY > now_ms]

        # the bar the basemap path treats as closed, vs the true final close of that bar
        true_last = next((float(b["c"]) for b in fr_ if int(b["t"]) == last_t), None)

        rec["inputs_shared"] = {"dis6": dis6, "dissent_families": cs.get("dissent_families"), "n_families": n_f,
                                "funding_hourly": fh_, "funding_day_pct": fday,
                                "btc_rv5_basemap": btc_rv5_basemap, "btc_rv5_fresh": btc_rv5_fresh}
        rec["A_assemble_vol_voice"] = {
            "where": "assemble.py:288-297 -> volforecast.forecast with stage-2 (volforecast.py:54-61, 26-33)",
            "bar_source": "HL candleSnapshot 1d via basemap file cache (REBUILD_S=20h, basemap.py:28,31-39)",
            "cache_written_utc": iso(mtime * 1000), "last_bar_t_utc": iso(last_t),
            "last_bar_complete": complete,
            "last_bar_close_used": float(last["c"]), "last_bar_true_close": true_last,
            "rv1": rvA[0], "rv5": rvA[1], "rv22": rvA[2], "units": "percent (simple returns x100)",
            "z": zA, "stage2": s2A, "final": s2A["final"] if s2A else None,
            "real_function_output": fA_real, "state_file_value": (st.get("vol") or {}).get("next_day_move_pct"),
            "zero_volume_bars_in_last23": zero_n_used, "zero_volume_bars_in_full_cache": zero_n_all}
        rec["B_scanner_exp_move"] = {
            "where": "scanner.py:88-101 -> volforecast.forecast(c) stage-1, x0.8 if >=3.9 (volforecast.py:64-65)",
            "bar_source": "HL candleSnapshot 1d fresh (ttl 600s), closed = t+1d<=now",
            "last_bar_t_utc": iso(closed[-1]["t"]), "last_bar_complete": True,
            "forming_bar_excluded": bool(forming),
            "rv1": rvB[0], "rv5": rvB[1], "rv22": rvB[2], "units": "percent",
            "z": zB, "smearing": SM1, "pre_haircut": math.exp(zB) * SM1, "haircut_0.8_applied": math.exp(zB) * SM1 >= 3.9,
            "final": stage1_cut(zB), "real_function_output": fB_real.get("next_day_move_pct"),
            "zero_volume_bars_in_last23": zero_n_B}
        rec["C_risk_voice"] = {
            "where": "assemble.py:312-326 -> risk_voice.risk_read (risk_voice.py:81-103)",
            "bar_source": "same basemap df as A (.tail(60))",
            "last_bar_t_utc": iso(last_t), "last_bar_complete": complete,
            "rv1": rvC["rv1"], "rv5": rvC["rv5"], "rv22": rvC["rv22"], "units": "percent",
            "z": zC, "smearing": SM1, "stage2": None, "haircut": None,
            "final": stage1_raw(zC), "real_function_output": rC.get("expected_move_1d_pct"),
            "state_file_stop_long": ((st.get("risk") or {}).get("long") or {}).get("stop_pct")}
        ch = chief.get(s)
        rec["D_chief"] = ({"ts_utc": iso(ch["ts"] * 1000), "expected_move_pct": ch.get("expected_move_pct"),
                           "har_move_pct_shown": ch.get("har_move_pct"), "atr_pct_1d_shown": ch.get("atr_pct_1d"),
                           "rv": "n/a (LLM; reads har_move_pct + atr from the state file)"} if ch else None)

        # ---------- decomposition (log points; ratios multiply) ----------
        A, C, B = rec["A_assemble_vol_voice"]["final"], rec["C_risk_voice"]["final"], rec["B_scanner_exp_move"]["final"]
        dec = {}
        if A and C and s2A:
            dec["A_vs_C_total_logpts"] = math.log(A / C)
            dec["A_vs_C_parts_logpts"] = {
                "rv_inputs (zA-zC)": zA - zC,
                "smearing swap 1.7017 vs 1.7389": math.log(S1SM / SM1),
                "stage2 intercept": s2A["log_terms"]["intercept"],
                "stage2 disagree term": s2A["log_terms"]["disagree"],
                "stage2 funding term": s2A["log_terms"]["funding"],
                "stage2 btc_rv5 term": s2A["log_terms"]["btc_rv5"],
                "stage2_smearing 1.6959": math.log(S2SM),
                "top20 haircut x0.8": math.log(0.8) if s2A["top20_haircut_0.8_applied"] else 0.0}
        if B and C:
            # stale/partial basemap bar vs fresh closed bars, holding the formula fixed (risk_voice formula)
            dec["C_on_fresh_bars"] = stage1_raw(zB)
            dec["C_bar_source_effect_logpts"] = zB - zC
            dec["B_vs_C_total_logpts"] = math.log(B / C)
            dec["B_vs_C_parts_logpts"] = {"bar source (zB-zC)": zB - zC,
                                         "0.8 haircut >=3.9": math.log(0.8) if math.exp(zB) * SM1 >= 3.9 else 0.0}
        if A and s2A:
            s2_fresh = stage2_parts(zB, dis6, fday, btc_rv5_fresh)
            dec["A_on_fresh_bars"] = s2_fresh["final"]
            dec["A_bar_source_effect_logpts"] = math.log(s2_fresh["final"] / A)
        rec["decomposition"] = dec
        out["coins"][s] = rec

    out["stale_bar_sensitivity"] = stale_bar_sensitivity(fresh, now_ms)
    (HERE / "RV_INPUT_EXPORT.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    return out


if __name__ == "__main__":
    o = main()
    for s, r in o["coins"].items():
        a, b, c = r["A_assemble_vol_voice"], r["B_scanner_exp_move"], r["C_risk_voice"]
        print(s, "A", round(a["final"], 3), a["real_function_output"]["next_day_move_pct"], a["state_file_value"],
              "| B", round(b["final"], 3), b["real_function_output"], "| C", round(c["final"], 3), c["real_function_output"],
              "| D", (r["D_chief"] or {}).get("expected_move_pct"), "| last", a["last_bar_t_utc"], a["last_bar_complete"])
