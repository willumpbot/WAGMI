"""M25/M26 - first read of the 1,200-HL-wallet cohort stream (server_exports/today/wallets.jsonl.gz +
archive/wallets/*.jsonl.gz). Rows {ts,addr,cohort skilled|control,coin,szi,entry,value,upnl,lev,liq,acct},
hourly. DESCRIPTIVE positioning read on the LATEST snapshot - NOT a skill claim. Hard caveats:
(1) 'skilled' is a PAST-PERFORMANCE-SELECTED cohort -> any return/upnl edge is selection-biased
    (winner's curse); a real skill test needs FORWARD realised P&L on the cohorts, which accrues.
(2) upnl is UNREALISED and regime-driven (if BTC dumped today, every short shows green).
So the only honest NOW-read is WHAT they hold (net positioning) + composition; skill is a forward study.
"""
import io, os, gzip, json, collections
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
STREAMS = [os.path.join(HERE, "server_exports", "today", "wallets.jsonl.gz"),
           os.path.join(HERE, "server_exports", "archive", "wallets", "2026-10-15.jsonl.gz")]


def load():
    rows = []
    for p in STREAMS:
        if not os.path.exists(p):
            continue
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for l in f:
                if l.strip():
                    rows.append(json.loads(l))
    return rows


def main():
    rows = load()
    if not rows:
        print("no wallet stream present"); return
    ts_all = sorted(set(r["ts"] for r in rows))
    latest = ts_all[-1]
    snap = [r for r in rows if r["ts"] == latest]          # latest snapshot = current positioning
    print("M25/M26 first read. total rows %d | snapshots %d (%s..%s) | LATEST snapshot %d positions"
          % (len(rows), len(ts_all), ts_all[0], ts_all[-1], len(snap)))

    def cohort(c):
        return [r for r in snap if r.get("cohort") == c]
    sk, ct = cohort("skilled"), cohort("control")
    print("\n=== COMPOSITION (latest snapshot) ===")
    for lab, g in (("skilled", sk), ("control", ct)):
        addrs = set(r["addr"] for r in g)
        lev = np.array([float(r.get("lev") or 0) for r in g])
        val = np.array([abs(float(r.get("value") or 0)) for r in g])
        print("  %-8s positions %5d | wallets %4d | median lev %.1f | median pos $%.0f | total notional $%.1fM"
              % (lab, len(g), len(addrs), np.median(lev) if len(lev) else 0, np.median(val) if len(val) else 0, val.sum() / 1e6))

    def net_by_coin(g):
        # net signed notional per coin = sum(sign(szi)*|value|); + = net long
        d = collections.defaultdict(float); n = collections.Counter()
        for r in g:
            s = 1 if float(r.get("szi") or 0) > 0 else -1
            d[r["coin"]] += s * abs(float(r.get("value") or 0)); n[r["coin"]] += 1
        return d, n
    sd, sn = net_by_coin(sk); cd, cn = net_by_coin(ct)
    print("\n=== NET POSITIONING by coin (latest; + net LONG, - net SHORT; % of cohort notional) ===")
    sk_tot = sum(abs(v) for v in sd.values()) or 1; ct_tot = sum(abs(v) for v in cd.values()) or 1
    top = sorted(sd, key=lambda c: -abs(sd[c]))[:10]
    print("  coin   skilled_net$   (%cohort, n)   | control_net$   (%cohort,n)   | agree?")
    out_pos = {}
    for c in top:
        sv = sd.get(c, 0); cv = cd.get(c, 0)
        agree = "same side" if (sv > 0) == (cv > 0) and cv != 0 else ("OPP" if cv != 0 else "ctrl~0")
        print("  %-6s %+12.0f  (%4.1f%%, %3d) | %+12.0f  (%4.1f%%, %2d) | %s"
              % (c, sv, 100 * abs(sv) / sk_tot, sn[c], cv, 100 * abs(cv) / ct_tot, cn[c], agree))
        out_pos[c] = {"skilled_net": sv, "skilled_pct": 100 * abs(sv) / sk_tot, "skilled_n": sn[c],
                      "control_net": cv, "control_n": cn[c], "agree": agree}
    # upnl snapshot (FLAGGED - unrealised, regime, selection-biased)
    def upnl_stats(g):
        u = np.array([float(r.get("upnl") or 0) for r in g])
        return float(u.sum()), float(np.median(u)) if len(u) else 0, float((u > 0).mean()) if len(u) else 0
    su = upnl_stats(sk); cu = upnl_stats(ct)
    print("\n=== upnl SNAPSHOT (unrealised; regime + selection confounded - NOT a skill measure) ===")
    print("  skilled: sum $%.0f | median $%.0f | %% green %.0f%%" % (su[0], su[1], 100 * su[2]))
    print("  control: sum $%.0f | median $%.0f | %% green %.0f%%" % (cu[0], cu[1], 100 * cu[2]))
    print("\nFIRST READ = positioning + composition only. SKILL requires a FORWARD realised-P&L test on the")
    print("cohorts (snapshot upnl is selection-biased + regime-driven). Design: track each cohort's realised")
    print("close P&L forward from here; compare skilled vs control with day-block CI; the cohort definition's")
    print("selection must be pre-this-window so it isn't circular.")
    out = {"total_rows": len(rows), "snapshots": len(ts_all), "latest_ts": latest,
           "skilled_wallets": len(set(r["addr"] for r in sk)), "control_wallets": len(set(r["addr"] for r in ct)),
           "net_positioning_top": out_pos,
           "upnl_snapshot": {"skilled": su, "control": cu, "caveat": "unrealised/regime/selection - not skill"}}
    io.open(os.path.join(HERE, "m25_wallets_result.json"), "w", encoding="utf-8").write(json.dumps(out, indent=1, default=float))
    print("wrote m25_wallets_result.json")


if __name__ == "__main__":
    main()
