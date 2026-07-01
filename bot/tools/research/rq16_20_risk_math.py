"""RQ16+RQ20 — Drawdown/streak structure + Monte Carlo ruin math.

Part A: losing-streak structure from trades.csv (actual live outcomes, incl. LLM
        exits) vs random permutation given measured WR; loss clustering by
        regime/session/symbol.
Part B: Monte Carlo ruin/halving/growth at leverage 1x-5x, $2k equity, using
        per-trade R distributions extracted from the exit-geometry backtest
        engine (S3 restored-lock geometry = forward assumption; V0 current
        geometry = pessimistic; V0 Jun7+ only = stress).

READ-ONLY on bot code: imports bot/tools/backtest_exit_geometry.py as a module.
Output: JSON to bot/data/cache/exit_geometry_bt/rq16_20_risk_math.json + stdout.
"""
from __future__ import annotations

import csv
import json
import random
import statistics as st
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve()
TOOLS = HERE.parents[1]                      # bot/tools
sys.path.insert(0, str(TOOLS))
import backtest_exit_geometry as bt          # noqa: E402

DATA = TOOLS.parent / "data"
OUT = DATA / "cache" / "exit_geometry_bt" / "rq16_20_risk_math.json"
random.seed(1620)

# ────────────────────────────────────────────────────────────────────────
# PART A — streaks from trades.csv (live outcomes, LLM exits included)
# ────────────────────────────────────────────────────────────────────────

def load_live_trades():
    rows = []
    with open(DATA / "trades.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            try:
                pnl = float(r["pnl"])
                ts = bt.parse_ts(r["timestamp"])
            except (ValueError, KeyError):
                continue
            rows.append({
                "ts": ts, "symbol": r["symbol"], "pnl": pnl,
                "win": pnl > 0,
                "regime": (r.get("regime") or "unknown").strip() or "unknown",
                "session": ("asia" if ts.hour < 8 else
                            "eu" if ts.hour < 16 else "us"),
                "era": "pre-Jun7" if ts < bt.ERA_SPLIT else "Jun7+",
            })
    rows.sort(key=lambda x: x["ts"])
    return rows


def streaks(seq):
    """Return list of (is_win, length) runs."""
    out = []
    for v in seq:
        if out and out[-1][0] == v:
            out[-1][1] += 1
        else:
            out.append([v, 1])
    return out


def streak_stats(wins):
    runs = streaks(wins)
    lose = [r[1] for r in runs if not r[0]]
    win = [r[1] for r in runs if r[0]]
    return {
        "n": len(wins), "wr": sum(wins) / len(wins),
        "n_runs": len(runs),
        "max_lose_streak": max(lose) if lose else 0,
        "mean_lose_streak": round(st.mean(lose), 2) if lose else 0,
        "lose_streak_hist": {str(k): sum(1 for x in lose if x == k)
                             for k in sorted(set(lose))},
        "max_win_streak": max(win) if win else 0,
    }


def permutation_test(wins, n_iter=10000):
    """Shuffle outcomes; compare observed max losing streak and run count."""
    obs = streak_stats(wins)
    seq = list(wins)
    ge_max, runs_le = 0, 0
    max_dist = []
    for _ in range(n_iter):
        random.shuffle(seq)
        s = streaks(seq)
        m = max((r[1] for r in s if not r[0]), default=0)
        max_dist.append(m)
        if m >= obs["max_lose_streak"]:
            ge_max += 1
        if len(s) <= obs["n_runs"]:
            runs_le += 1
    max_dist.sort()
    return {
        "observed_max_lose_streak": obs["max_lose_streak"],
        "p_max_streak_ge_observed": ge_max / n_iter,
        "shuffled_median_max_lose_streak": max_dist[n_iter // 2],
        "shuffled_p95_max_lose_streak": max_dist[int(n_iter * 0.95)],
        "observed_n_runs": obs["n_runs"],
        "p_runs_le_observed": runs_le / n_iter,   # small => clustered
    }


def cluster_table(rows, key):
    out = {}
    for v in sorted({r[key] for r in rows}):
        sub = [r for r in rows if r[key] == v]
        out[v] = {"n": len(sub),
                  "wr": round(sum(r["win"] for r in sub) / len(sub), 3),
                  "pnl": round(sum(r["pnl"] for r in sub), 2)}
    return out


def conditional_wr(rows):
    after_loss = [rows[i]["win"] for i in range(1, len(rows))
                  if not rows[i - 1]["win"]]
    after_win = [rows[i]["win"] for i in range(1, len(rows))
                 if rows[i - 1]["win"]]
    return {
        "wr_after_loss": {"n": len(after_loss),
                          "wr": round(sum(after_loss) / len(after_loss), 3)},
        "wr_after_win": {"n": len(after_win),
                         "wr": round(sum(after_win) / len(after_win), 3)},
    }


def part_a():
    rows = load_live_trades()
    wins = [r["win"] for r in rows]
    res = {"all": {**streak_stats(wins), "perm": permutation_test(wins)}}
    for era in ("pre-Jun7", "Jun7+"):
        sub = [r["win"] for r in rows if r["era"] == era]
        if len(sub) >= 10:
            res[era] = {**streak_stats(sub), "perm": permutation_test(sub)}
    res["by_regime"] = cluster_table(rows, "regime")
    res["by_session"] = cluster_table(rows, "session")
    res["by_symbol"] = cluster_table(rows, "symbol")
    res["conditional"] = conditional_wr(rows)
    # losses inside losing streaks >=3 — where do they live?
    runs = streaks(wins)
    idx, streak_members = 0, []
    for is_win, ln in runs:
        if not is_win and ln >= 3:
            streak_members.extend(range(idx, idx + ln))
        idx += ln
    ins = [rows[i] for i in streak_members]
    res["streak3_losses"] = {
        "n": len(ins),
        "by_regime": cluster_table(ins, "regime") if ins else {},
        "by_session": cluster_table(ins, "session") if ins else {},
        "by_symbol": cluster_table(ins, "symbol") if ins else {},
    }
    return res, rows


# ────────────────────────────────────────────────────────────────────────
# PART B — per-trade R distributions from the backtest engine
# ────────────────────────────────────────────────────────────────────────

def build_rows():
    """Replicates row assembly from backtest_exit_geometry.main()."""
    trades = bt.load_trades()
    opens = bt.load_open_events()
    rows = []
    for t in trades:
        ev = bt.match_open(t, opens)
        if ev is None:
            continue
        try:
            row = {
                "symbol": t["symbol"], "side": t["side"],
                "entry": float(t["entry"]), "actual_exit": float(t["exit"]),
                "actual_pnl": float(t["pnl"]),
                "sl": float(ev["sl"]), "tp1": float(ev["tp1"]),
                "tp2": float(ev["tp2"]), "atr": float(ev.get("atr", 0)),
                "qty": float(ev.get("position_size", 0)),
                "leverage": float(ev.get("leverage", 1.0)) or 1.0,
                "open_time": bt.parse_ts(ev["timestamp"]),
                "close_time": bt.parse_ts(t["timestamp"]),
                "state_path": t.get("state_path", ""),
                "outcome": t.get("outcome", ""),
            }
        except (KeyError, TypeError, ValueError):
            continue
        if row["atr"] <= 0 or row["qty"] <= 0 or abs(row["entry"] - row["sl"]) <= 0:
            continue
        row["era"] = "pre-Jun7" if row["open_time"] < bt.ERA_SPLIT else "Jun7+"
        row["risk_usd"] = abs(row["entry"] - row["sl"]) * row["qty"] * row["leverage"]
        rows.append(row)
    return rows


def r_distributions(rows):
    syms = sorted({r["symbol"] for r in rows})
    t_min = min(r["open_time"] for r in rows) - timedelta(hours=2)
    t_max = min(max(r["close_time"] for r in rows)
                + timedelta(hours=bt.MAX_HOLD_HOURS + 2),
                datetime.now(timezone.utc))
    start_ms = int(t_min.timestamp() // 3600 * 3600 * 1000)
    end_ms = int(t_max.timestamp() * 1000)
    candles = {s: bt.fetch_candles(s, start_ms, end_ms) for s in syms}
    cfgs = {c.name: c for c in bt.VARIANTS}
    dists = {}
    for name in ("S3", "V0"):
        rs, rs_b = [], []
        for r in rows:
            sim = bt.simulate(r, cfgs[name], candles[r["symbol"]])
            if sim is None:
                continue
            rm = sim.pnl / (r["risk_usd"] or 1.0)
            rs.append(round(rm, 4))
            if r["era"] == "Jun7+":
                rs_b.append(round(rm, 4))
        dists[name] = rs
        dists[name + "_jun7plus"] = rs_b
    return dists


# ────────────────────────────────────────────────────────────────────────
# Monte Carlo
# ────────────────────────────────────────────────────────────────────────

def mc(r_dist, risk_frac, n_trades=250, n_paths=10000, start_eq=2000.0,
       block=1):
    """Bootstrap paths; risk_frac = fraction of current equity risked/trade.
    block>1 = block bootstrap (preserves streak clustering)."""
    ruin = halve = dd25 = 0
    finals = []
    n_src = len(r_dist)
    for _ in range(n_paths):
        eq, peak = start_eq, start_eq
        hit_ruin = hit_half = hit_dd25 = False
        t = 0
        while t < n_trades:
            i = random.randrange(n_src)
            for j in range(block):
                if t >= n_trades:
                    break
                r = r_dist[(i + j) % n_src]
                eq *= max(1.0 + risk_frac * r, 0.0)
                peak = max(peak, eq)
                if eq <= peak * 0.5:
                    hit_ruin = True
                if eq <= peak * 0.75:
                    hit_dd25 = True
                if eq <= start_eq * 0.5:
                    hit_half = True
                t += 1
            if eq <= 1.0:
                break
        ruin += hit_ruin
        halve += hit_half
        dd25 += hit_dd25
        finals.append(eq)
    finals.sort()
    return {
        "p_ruin_50dd": round(ruin / n_paths, 4),
        "p_halving": round(halve / n_paths, 4),
        "p_dd25": round(dd25 / n_paths, 4),
        "median_final": round(finals[n_paths // 2], 0),
        "p5_final": round(finals[int(n_paths * 0.05)], 0),
        "p95_final": round(finals[int(n_paths * 0.95)], 0),
    }


def part_b(dists):
    base_risk_per_1x = 0.01          # 1% of equity risked per 1x leverage
    out = {"base_risk_per_1x": base_risk_per_1x, "n_trades_horizon": 250,
           "start_equity": 2000, "tables": {}}
    for dname, dist in dists.items():
        if not dist:
            continue
        stats = {
            "n": len(dist), "mean_R": round(st.mean(dist), 3),
            "median_R": round(st.median(dist), 3),
            "wr": round(sum(1 for x in dist if x > 0) / len(dist), 3),
            "min_R": min(dist), "max_R": max(dist),
            "stdev_R": round(st.pstdev(dist), 3),
        }
        table = {}
        for lev in (1, 2, 3, 4, 5):
            rf = base_risk_per_1x * lev
            table[f"{lev}x_iid"] = mc(dist, rf)
            table[f"{lev}x_block5"] = mc(dist, rf, block=5)
        # fragility: drop the single best R observation
        frag = sorted(dist)[:-1]
        table["frag_2x_iid_dropbest"] = mc(frag, base_risk_per_1x * 2)
        table["frag_3x_iid_dropbest"] = mc(frag, base_risk_per_1x * 3)
        out["tables"][dname] = {"dist_stats": stats, "mc": table}
    return out


def main():
    part_a_res, live_rows = part_a()
    rows = build_rows()
    # empirical risk-fraction calibration (denominator honesty)
    pre = [r for r in rows if r["era"] == "pre-Jun7"]
    post = [r for r in rows if r["era"] == "Jun7+"]
    calib = {
        "pre_jun7_median_risk_usd": round(st.median(
            [r["risk_usd"] for r in pre]), 2) if pre else None,
        "pre_jun7_median_leverage": st.median(
            [r["leverage"] for r in pre]) if pre else None,
        "jun7plus_median_risk_usd": round(st.median(
            [r["risk_usd"] for r in post]), 2) if post else None,
        "jun7plus_median_leverage": st.median(
            [r["leverage"] for r in post]) if post else None,
    }
    dists = r_distributions(rows)
    part_b_res = part_b(dists)
    result = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "part_a_streaks": part_a_res,
        "risk_calibration": calib,
        "r_distributions": dists,
        "part_b_monte_carlo": part_b_res,
    }
    OUT.write_text(json.dumps(result, indent=1))
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
