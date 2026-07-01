"""Confidence-calibrated sizing ladder backtest (master-plan P3).

Replays all closed trades in bot/data/trades.csv under sizing variants.
Method: trades.csv `pnl` is NET of fees (multi_strategy_main.py:3805-3808,
gross_pnl = pnl + fees). Both gross PnL and fees scale linearly with position
notional, so variant PnL per trade = actual net pnl * multiplier(conf_band).
This is exact for the 1x-leverage era and a linear approximation for the
early 1.5x-5.6x leverage trades (multiplier scales notional; liquidation /
margin effects ignored -- none of the actual trades were liquidated).

Variants (multiplier applied ON TOP of actual sizing; V0 = actual = 1.0x):
  V1 data-derived ladder: <60 -> 0.3x (assumption: lowest band), 60-69 -> 0.3x,
     70-79 -> 0.3x, 80-89 -> 1.1x, 90+ -> 1.3x
  V2 harsher: <80 -> 0.15x, 80-89 -> 1.1x, 90+ -> 1.3x
  V3 80+-only: <80 -> 0x, 80-89 -> 1.1x, 90+ -> 1.3x

Unknown-confidence trades (conf==0, empty entry_reasons -- pre-fix metadata
gap): ladder cannot be applied. Two scenarios reported:
  scenario KEEP: unknown trades kept at 1.0x in every variant
  scenario DROP: unknown trades excluded from every variant incl. V0
"""
import csv
import json
from datetime import datetime, timezone

TRADES = "bot/data/trades.csv"
ERA_SPLIT = datetime(2026, 6, 7, tzinfo=timezone.utc)


def band(conf):
    if conf <= 0:
        return "UNK"
    if conf < 60:
        return "<60"
    if conf < 70:
        return "60-69"
    if conf < 80:
        return "70-79"
    if conf < 90:
        return "80-89"
    return "90+"


VARIANTS = {
    "V0_actual": {"<60": 1.0, "60-69": 1.0, "70-79": 1.0, "80-89": 1.0, "90+": 1.0},
    "V1_ladder": {"<60": 0.3, "60-69": 0.3, "70-79": 0.3, "80-89": 1.1, "90+": 1.3},
    "V2_harsher": {"<60": 0.15, "60-69": 0.15, "70-79": 0.15, "80-89": 1.1, "90+": 1.3},
    # V2b: harsh cut on <80 but NO upweight of 80+ (n=8 there is too thin to trust)
    "V2b_no_up": {"<60": 0.15, "60-69": 0.15, "70-79": 0.15, "80-89": 1.0, "90+": 1.0},
    "V3_80plus": {"<60": 0.0, "60-69": 0.0, "70-79": 0.0, "80-89": 1.1, "90+": 1.3},
}


def load():
    rows = list(csv.DictReader(open(TRADES, encoding="utf-8")))
    trades = []
    for r in rows:
        conf = float(r["confidence"] or 0)
        ts = datetime.fromisoformat(r["timestamp"])
        trades.append({
            "ts": ts,
            "symbol": r["symbol"],
            "side": r["side"],
            "pnl": float(r["pnl"]),
            "conf": conf,
            "band": band(conf),
            "era": "pre_jun7" if ts < ERA_SPLIT else "post_jun7",
            "lev": float(r["leverage"] or 1),
        })
    trades.sort(key=lambda t: t["ts"])
    return trades


def max_dd(equity):
    peak, dd = 0.0, 0.0
    for e in equity:
        peak = max(peak, e)
        dd = max(dd, peak - e)
    return dd


def run_variant(trades, mults, keep_unknown):
    out = []
    for t in trades:
        if t["band"] == "UNK":
            if not keep_unknown:
                continue
            m = 1.0
        else:
            m = mults[t["band"]]
        out.append({**t, "mult": m, "vpnl": t["pnl"] * m})
    eq, curve = 0.0, []
    for t in out:
        eq += t["vpnl"]
        curve.append(eq)
    wins = [t["vpnl"] for t in out if t["vpnl"] > 0]
    wins_sorted = sorted(wins, reverse=True)
    gross_win = sum(wins) or 1e-9
    traded = [t for t in out if t["mult"] > 0]
    res = {
        "total_pnl": eq,
        "max_dd": max_dd(curve),
        "n_traded": len(traded),
        "n_wins": len([t for t in traded if t["vpnl"] > 0]),
        "top1_win_share": (wins_sorted[0] / gross_win) if wins_sorted else 0,
        "top3_win_share": (sum(wins_sorted[:3]) / gross_win) if wins_sorted else 0,
        "pre_jun7": sum(t["vpnl"] for t in out if t["era"] == "pre_jun7"),
        "post_jun7": sum(t["vpnl"] for t in out if t["era"] == "post_jun7"),
        "curve": curve,
    }
    return res, out


def main():
    trades = load()
    print(f"n trades: {len(trades)}")
    # band summary
    print("\n== Band summary (actual PnL, honest denominators) ==")
    for b in ["UNK", "<60", "60-69", "70-79", "80-89", "90+"]:
        sub = [t for t in trades if t["band"] == b]
        if not sub:
            continue
        w = [t for t in sub if t["pnl"] > 0]
        print(f"{b:6} n={len(sub):3} wins={len(w):3} WR={len(w)/len(sub)*100:5.1f}% "
              f"pnl_sum={sum(t['pnl'] for t in sub):9.2f} avg={sum(t['pnl'] for t in sub)/len(sub):8.2f}")
    for era in ["pre_jun7", "post_jun7"]:
        sub = [t for t in trades if t["era"] == era]
        print(f"{era}: n={len(sub)} pnl={sum(t['pnl'] for t in sub):.2f}")

    for keep in [True, False]:
        tag = "KEEP unknown @1.0x" if keep else "DROP unknown"
        print(f"\n== Scenario: {tag} ==")
        print(f"{'variant':12} {'totalPnL':>9} {'maxDD':>8} {'nTraded':>8} {'wins':>5} "
              f"{'top1win%':>9} {'top3win%':>9} {'preJun7':>9} {'postJun7':>9}")
        for name, mults in VARIANTS.items():
            r, _ = run_variant(trades, mults, keep)
            print(f"{name:12} {r['total_pnl']:9.2f} {r['max_dd']:8.2f} {r['n_traded']:8} "
                  f"{r['n_wins']:5} {r['top1_win_share']*100:8.1f}% {r['top3_win_share']*100:8.1f}% "
                  f"{r['pre_jun7']:9.2f} {r['post_jun7']:9.2f}")

    # fragility: 80+ band detail
    print("\n== 80+ band detail (fragility) ==")
    hi = [t for t in trades if t["band"] in ("80-89", "90+")]
    for t in hi:
        print(f"{t['ts'].isoformat()[:16]} {t['symbol']:5} {t['side']:5} conf={t['conf']:6.2f} "
              f"lev={t['lev']:4.1f} pnl={t['pnl']:8.2f}")
    hw = sorted([t["pnl"] for t in hi if t["pnl"] > 0], reverse=True)
    print(f"80+ n={len(hi)} wins={len(hw)} gross_win={sum(hw):.2f} "
          f"top1_share={hw[0]/sum(hw)*100 if hw else 0:.1f}%")

    # unknown-band detail
    print("\n== UNK band detail ==")
    unk = [t for t in trades if t["band"] == "UNK"]
    for t in sorted(unk, key=lambda x: -abs(x["pnl"]))[:8]:
        print(f"{t['ts'].isoformat()[:16]} {t['symbol']:5} pnl={t['pnl']:8.2f} era={t['era']}")
    print(f"UNK n={len(unk)} pnl_sum={sum(t['pnl'] for t in unk):.2f} "
          f"pre_jun7_share={sum(t['pnl'] for t in unk if t['era']=='pre_jun7'):.2f}")


if __name__ == "__main__":
    main()
