"""
Cross-sectional momentum backtest — Long-Tail Alpha program, KEY TEST.

Question: does cross-sectional (XS) momentum on 25 alt perps produce
net-of-cost, out-of-sample edge?

Standalone research script. READ-ONLY with respect to the live bot:
  - does NOT import anything from backtest/engine.py or any bot/ module
  - does NOT touch live/, .env, data/replay/, or any bot state
  - only reads data/longtail/{ohlc,funding,universe.json} and
    data/cache/BTC_daily_420d.csv (a static, already-fetched cache file)

Methodology
-----------
Universe: 25 coins in data/longtail/universe.json (excludes majors: BTC,
ETH, SOL, XRP, DOGE, BNB, HYPE, NEAR). Per-coin round-trip cost estimate
(cost_bps_est) comes from that same file (live spread/depth snapshot).

Signal (momentum): at the close of day t, mom[t] = close[t-1]/close[t-1-L] - 1
i.e. the L-day return ending YESTERDAY's close. This skips the most recent
daily bar (the requested "12h / half-day skip", generalized to whole days
since the data is daily) to avoid 1-day microstructure reversal.

Portfolio: rank the coins with valid signal by mom. Go long the top quintile,
short the bottom quintile, weight each leg inverse to its 20-day realized vol
of daily returns, normalize so each leg sums to 0.5 (gross book = 1.0 unit).

REBALANCE CADENCE (this is the knob the coordinator asked to test):
  - DAILY  (rebalance_period=1): re-rank + rebuild the book every day.
  - WEEKLY (rebalance_period=7): re-rank + rebuild the book once every 7 days,
    then HOLD those target weights for the week. Portfolio returns are STILL
    computed daily (Sigma held_w_i * daily_ret_i each day) so the statistics use
    the same daily return series (n ~ 380). Turnover cost is charged only on the
    rebalance days, which is the whole point: it should cut the cost drag ~7x if
    turnover was the killer. (Simplification: target weights are held flat across
    the week rather than left to drift with price; standard, and conservative
    w.r.t. cost since it ignores tiny intra-week drift-rebalancing.)

Costs: on every rebalance, charge cost_bps_est[coin] (round-trip, in bps) on
|change in that coin's book weight| (turnover). This captures entries, exits and
flips organically. No terminal unwind cost on the very last day (immaterial).

SURVIVORSHIP BIAS WARNING: the 25-coin universe is TODAY's liquid survivors
(min volume/OI/depth filters). Backtesting them over the trailing ~13 months
is inherently survivorship-biased — coins that failed, got delisted, or fell
below the liquidity bar during the window are excluded from the "universe of
consideration" a real-time strategy would have faced. Any positive result
here is therefore an OPTIMISTIC UPPER BOUND on live edge, not proof of edge.
The only real test is a forward paper/shadow run.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "longtail"
OHLC_DIR = DATA_DIR / "ohlc"
FUNDING_DIR = DATA_DIR / "funding"
UNIVERSE_PATH = DATA_DIR / "universe.json"
BTC_PROXY_PATH = ROOT / "data" / "cache" / "BTC_daily_420d.csv"

QUINTILE_FRAC = 0.20
VOL_LOOKBACK = 20
MIN_VALID_FOR_TRADE = 10  # need at least this many coins with a valid signal to rebalance
MIN_PER_LEG = 2
T_STAT_BAR = 2.5          # haircut for testing multiple lookbacks (in-sample bar)
OOS_T_BAR = 2.0           # OOS decider bar (coordinator's threshold)
IC_T_BAR = 2.0
IC_BAR = 0.03
WALKFORWARD_SPLIT = 0.60
CARRY_MOM_LOOKBACK = 7     # momentum filter lookback for the carry signal

pd.set_option("display.width", 160)


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def load_universe() -> tuple[list[str], dict[str, float]]:
    u = json.loads(UNIVERSE_PATH.read_text())
    coins = [n["coin"] for n in u["names"]]
    cost_bps = {n["coin"]: float(n["cost_bps_est"]) for n in u["names"]}
    return coins, cost_bps


def load_close_panel(coins: list[str]) -> pd.DataFrame:
    series = {}
    for c in coins:
        df = pd.read_csv(OHLC_DIR / f"{c}_1d.csv")
        dt = pd.to_datetime(df["dt_utc_iso"], utc=True, format="ISO8601").dt.normalize()
        s = pd.Series(df["c"].values, index=dt, name=c)
        s = s[~s.index.duplicated(keep="last")]
        series[c] = s
    return pd.DataFrame(series).sort_index()


def load_funding_panel(coins: list[str]) -> pd.DataFrame:
    series = {}
    for c in coins:
        fp = FUNDING_DIR / f"{c}.csv"
        if not fp.exists():
            continue
        df = pd.read_csv(fp)
        dt = pd.to_datetime(df["dt_utc_iso"], utc=True, format="ISO8601").dt.normalize()
        s = pd.Series(df["fundingRate"].values, index=dt).groupby(level=0).mean()
        s.name = c
        series[c] = s
    return pd.DataFrame(series).sort_index()


def load_market_proxy(close_panel: pd.DataFrame) -> tuple[pd.Series, bool]:
    if BTC_PROXY_PATH.exists():
        btc = pd.read_csv(BTC_PROXY_PATH)
        btc_dt = pd.to_datetime(btc["time"], utc=True).dt.normalize()
        btc_close = pd.Series(btc["close"].values, index=btc_dt).sort_index()
        btc_close = btc_close[~btc_close.index.duplicated(keep="last")]
        overlap = btc_close.index.intersection(close_panel.index)
        if len(overlap) >= 0.7 * len(close_panel.index):
            return btc_close.reindex(close_panel.index), True
    ew_ret = close_panel.pct_change().mean(axis=1)
    ew_level = (1 + ew_ret.fillna(0)).cumprod()
    return ew_level, False


# --------------------------------------------------------------------------
# Core cross-sectional engine (rebalance-period aware)
# --------------------------------------------------------------------------

def build_signals(close: pd.DataFrame, lookback: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ret = close.pct_change()
    mom = close.shift(1) / close.shift(1 + lookback) - 1.0        # skip most-recent bar
    sigma = ret.rolling(VOL_LOOKBACK, min_periods=VOL_LOOKBACK).std()
    next_ret = close.shift(-1) / close - 1.0                       # 1-day fwd return
    return mom, sigma, next_ret


def _form_book(m_t, s_t, all_coins) -> pd.Series:
    """Inverse-vol-weighted top/bottom-quintile long-short book. Returns weights or zeros."""
    valid = m_t.notna() & s_t.notna() & (s_t > 1e-9)
    n_valid = int(valid.sum())
    w = pd.Series(0.0, index=all_coins)
    if n_valid < MIN_VALID_FOR_TRADE:
        return w, n_valid
    v_coins = m_t[valid].index
    qsize = max(MIN_PER_LEG, round(n_valid * QUINTILE_FRAC))
    qsize = min(qsize, n_valid // 2)
    ranked = m_t[v_coins].sort_values(ascending=False)
    longs, shorts = ranked.index[:qsize], ranked.index[-qsize:]
    inv_vol_l, inv_vol_s = 1.0 / s_t[longs], 1.0 / s_t[shorts]
    w.loc[longs] = (inv_vol_l / inv_vol_l.sum()) * 0.5
    w.loc[shorts] = -(inv_vol_s / inv_vol_s.sum()) * 0.5
    return w, n_valid


def run_xs_momentum(
    close: pd.DataFrame,
    lookback: int,
    cost_bps: dict[str, float],
    coins: list[str] | None = None,
    dates: pd.DatetimeIndex | None = None,
    rebalance_period: int = 1,
    with_weights: bool = False,
):
    """
    Cross-sectional momentum simulator with configurable rebalance cadence.
    Returns a per-day DataFrame (gross_ret, cost, net_ret, n_valid, ic, traded,
    rebalanced). If with_weights, also returns a per-coin daily net-P&L panel.

    Weekly mode: the book is rebuilt every `rebalance_period` days and held flat
    between rebuilds; daily portfolio returns are computed every day using the
    held weights. IC is measured on rebalance days as Spearman(signal, forward
    period return) — the return the freshly-formed book will actually earn.
    """
    if coins is not None:
        close = close[coins]
    if dates is not None:
        close = close.loc[close.index.intersection(dates)]

    mom, sigma, next_ret = build_signals(close, lookback)
    all_coins = close.columns.tolist()
    cost_vec = pd.Series({c: cost_bps.get(c, 15.0) / 10000.0 for c in all_coins}).reindex(all_coins).fillna(0.15)
    fwd_period_ret = close.shift(-rebalance_period) / close - 1.0   # for IC under this hold

    idx = close.index
    prev_w = pd.Series(0.0, index=all_coins)
    held_w = pd.Series(0.0, index=all_coins)
    rows, weight_rows = [], []

    for i, t in enumerate(idx):
        r_t = next_ret.loc[t].fillna(0.0)
        rebalanced = (i % rebalance_period == 0)
        ic = np.nan
        if rebalanced:
            w, n_valid = _form_book(mom.loc[t], sigma.loc[t], all_coins)
            held_w = w
            # IC on rebalance days: signal vs forward-period return over the hold
            valid = mom.loc[t].notna() & sigma.loc[t].notna() & (sigma.loc[t] > 1e-9)
            f_t = fwd_period_ret.loc[t]
            icv = valid & f_t.notna()
            if int(icv.sum()) >= 5:
                ic = stats.spearmanr(mom.loc[t][icv].values, f_t[icv].values).correlation
        else:
            w = held_w
            n_valid = int((held_w != 0).sum())

        turnover = (w - prev_w).abs()
        cost = float((turnover * cost_vec).sum())
        gross = float((w * r_t).sum())
        net = gross - cost
        traded = bool((w != 0).any())

        rows.append({"date": t, "gross_ret": gross, "cost": cost, "net_ret": net,
                     "n_valid": n_valid, "ic": ic, "traded": traded, "rebalanced": rebalanced})
        if with_weights:
            weight_rows.append((w * r_t - turnover * cost_vec).rename(t))
        prev_w = w

    out = pd.DataFrame(rows).set_index("date")
    if with_weights:
        return out, pd.DataFrame(weight_rows)
    return out


# --------------------------------------------------------------------------
# Stats helpers
# --------------------------------------------------------------------------

def perf_stats(results: pd.DataFrame, col: str = "net_ret") -> dict:
    r = results.loc[results["traded"], col] if "traded" in results.columns else results[col]
    r = r.dropna()
    n = len(r)
    if n < 2:
        return {"n": n, "mean": np.nan, "ann_ret": np.nan, "sharpe": np.nan, "t_stat": np.nan, "sd": np.nan}
    mean, sd = r.mean(), r.std(ddof=1)
    t_stat = mean / (sd / np.sqrt(n)) if sd > 0 else np.nan
    return {"n": n, "mean": mean, "sd": sd, "ann_ret": mean * 365.0,
            "sharpe": (mean / sd) * np.sqrt(365.0) if sd > 0 else np.nan, "t_stat": t_stat}


def cost_drag_pct(results: pd.DataFrame) -> float:
    sub = results.loc[results["traded"]] if "traded" in results.columns else results
    g = sub["gross_ret"].sum()
    c = sub["cost"].sum()
    return (c / g * 100.0) if g != 0 else np.nan


def ic_stats(results: pd.DataFrame) -> dict:
    ic = results["ic"].dropna()
    n = len(ic)
    if n < 2:
        return {"n": n, "mean_ic": np.nan, "t_stat": np.nan}
    mean_ic, sd = ic.mean(), ic.std(ddof=1)
    return {"n": n, "mean_ic": mean_ic, "t_stat": mean_ic / (sd / np.sqrt(n)) if sd > 0 else np.nan}


def regime_buckets(market: pd.Series, idx: pd.DatetimeIndex) -> pd.Series:
    s = market.reindex(idx)
    trend7 = s.pct_change(7)
    q1, q2 = trend7.quantile([1 / 3, 2 / 3])
    bucket = pd.Series("chop", index=trend7.index)
    bucket[trend7 <= q1] = "down"
    bucket[trend7 >= q2] = "up"
    bucket[trend7.isna()] = np.nan
    return bucket


def fmt_pct(x, dp=3):
    return f"{x*100:.{dp}f}%" if pd.notna(x) else "n/a"


# --------------------------------------------------------------------------
# Full gauntlet for a given rebalance cadence
# --------------------------------------------------------------------------

def run_gauntlet(close, cost_bps, coins, lookbacks, rebalance_period, label, market, used_btc):
    print("\n" + "#" * 92)
    print(f"# {label}  (rebalance every {rebalance_period} day(s), lookbacks {lookbacks})")
    print("#" * 92)

    # ---- Step 1-2: per-lookback full-sample ----
    print("\n-- STEP 1-2: per-lookback (FULL SAMPLE, net-of-cost) --")
    print(f"{'L':>4} {'n_days':>7} {'#rebal':>7} {'gross/day':>11} {'net/day':>11} {'net ann':>10} "
          f"{'Sharpe':>7} {'net t':>7} {'costDrag%':>9} {'IC':>7} {'IC t':>7}")
    full = {}
    for L in lookbacks:
        res = run_xs_momentum(close, L, cost_bps, rebalance_period=rebalance_period)
        full[L] = res
        ps_n, ps_g, ics = perf_stats(res, "net_ret"), perf_stats(res, "gross_ret"), ic_stats(res)
        nreb = int(res["rebalanced"].sum())
        print(f"{L:>4} {ps_n['n']:>7} {nreb:>7} {fmt_pct(ps_g['mean']):>11} {fmt_pct(ps_n['mean']):>11} "
              f"{fmt_pct(ps_n['ann_ret']):>10} {ps_n['sharpe']:>7.2f} {ps_n['t_stat']:>7.2f} "
              f"{cost_drag_pct(res):>8.1f}% {ics['mean_ic']:>7.3f} {ics['t_stat']:>7.2f}")

    # ---- Step 3: walk-forward OOS ----
    print("\n-- STEP 3: walk-forward OOS (best L by IS net t-stat, tested on unseen last 40%) --")
    dates = close.index
    split_i = int(len(dates) * WALKFORWARD_SPLIT)
    is_dates, oos_dates = dates[:split_i], dates[split_i:]
    is_scores = {}
    for L in lookbacks:
        ps = perf_stats(run_xs_momentum(close, L, cost_bps, dates=is_dates, rebalance_period=rebalance_period), "net_ret")
        is_scores[L] = ps["t_stat"] if pd.notna(ps["t_stat"]) else -999
        print(f"  IS L={L}: net t={ps['t_stat']:.2f}  Sharpe={ps['sharpe']:.2f}  mean/day={fmt_pct(ps['mean'])}")
    best_L = max(is_scores, key=is_scores.get)
    print(f"  -> best IS L={best_L}")
    res_oos = run_xs_momentum(close, best_L, cost_bps, dates=oos_dates, rebalance_period=rebalance_period)
    ps_o, psg_o, ics_o = perf_stats(res_oos, "net_ret"), perf_stats(res_oos, "gross_ret"), ic_stats(res_oos)
    print(f"  OOS L={best_L}: n={ps_o['n']}  gross/day={fmt_pct(psg_o['mean'])}  net/day={fmt_pct(ps_o['mean'])}  "
          f"net ann={fmt_pct(ps_o['ann_ret'])}")
    print(f"    OOS net Sharpe={ps_o['sharpe']:.2f}  OOS net t={ps_o['t_stat']:.2f}  IC={ics_o['mean_ic']:.3f}  "
          f"IC t={ics_o['t_stat']:.2f}  costDrag={cost_drag_pct(res_oos):.1f}%")
    oos_pass = pd.notna(ps_o["t_stat"]) and ps_o["t_stat"] > OOS_T_BAR
    print(f"    OOS net t > {OOS_T_BAR}? -> {'PASS' if oos_pass else 'FAIL'}")

    # ---- Step 4: jackknife (top-3 drop + drop-one) on the OOS-selected winner, full sample ----
    print(f"\n-- STEP 4: jackknife (L={best_L}, full sample) --")
    base_res, base_pnl = run_xs_momentum(close, best_L, cost_bps, rebalance_period=rebalance_period, with_weights=True)
    base_res["traded"] = base_res["n_valid"] >= MIN_VALID_FOR_TRADE
    base_ps = perf_stats(base_res, "net_ret")
    contrib = base_pnl.sum(axis=0).sort_values(ascending=False)
    top3 = contrib.head(3).index.tolist()
    print(f"  baseline net mean/day={fmt_pct(base_ps['mean'])} t={base_ps['t_stat']:.2f}; "
          f"top-3 P&L coins={top3} ({(contrib.head(3)*10000).round(0).to_dict()})")
    jk = []
    for c in coins:
        ps = perf_stats(run_xs_momentum(close, best_L, cost_bps, coins=[x for x in coins if x != c],
                                        rebalance_period=rebalance_period), "net_ret")
        jk.append({"c": c, "mean": ps["mean"], "t": ps["t_stat"]})
    jk = pd.DataFrame(jk).set_index("c")
    n_flip = int((np.sign(jk["mean"]) != np.sign(base_ps["mean"])).sum())
    ps_d3 = perf_stats(run_xs_momentum(close, best_L, cost_bps, coins=[x for x in coins if x not in top3],
                                       rebalance_period=rebalance_period), "net_ret")
    print(f"  drop-one: {n_flip}/{len(coins)} sign flips; worst net mean/day={fmt_pct(jk['mean'].min())} "
          f"(drop {jk['mean'].idxmin()})")
    print(f"  DROP TOP-3 ({top3}): net mean/day={fmt_pct(ps_d3['mean'])} t={ps_d3['t_stat']:.2f} -> "
          f"{'survives (>0)' if ps_d3['mean'] > 0 else 'FLIPS NEGATIVE'}")

    # ---- Step 5: regime ----
    print(f"\n-- STEP 5: regime breakdown (L={best_L}, full sample; proxy={'BTC' if used_btc else 'EW-basket'}) --")
    bucket = regime_buckets(market, close.index)
    reg_df = base_res.copy()
    reg_df["regime"] = bucket
    regime_ok = 0
    for reg in ["up", "chop", "down"]:
        sub = reg_df[reg_df["regime"] == reg]
        ps = perf_stats(sub.assign(traded=sub["n_valid"] >= MIN_VALID_FOR_TRADE), "net_ret")
        nn = pd.notna(ps["mean"]) and ps["mean"] >= 0
        regime_ok += int(nn)
        print(f"  {reg:>5}: n={ps['n']:>3} net mean/day={fmt_pct(ps['mean']):>10} ann={fmt_pct(ps['ann_ret']):>9} "
              f"{'OK' if nn else 'NEG'}")
    print(f"  non-negative in {regime_ok}/3 (need >=2): {'PASS' if regime_ok >= 2 else 'FAIL'}")

    return {"best_L": best_L, "oos_net_sharpe": ps_o["sharpe"], "oos_net_t": ps_o["t_stat"],
            "oos_ic": ics_o["mean_ic"], "oos_net_mean": ps_o["mean"], "oos_pass": oos_pass,
            "n_flip": n_flip, "drop3_mean": ps_d3["mean"], "regime_ok": regime_ok,
            "full_best_costdrag": cost_drag_pct(full[best_L])}


# --------------------------------------------------------------------------
# Carry signal (funding), configurable cadence
# --------------------------------------------------------------------------

def run_carry(close, funding, cost_bps, coins, rebalance_period, label):
    print("\n" + "#" * 92)
    print(f"# CARRY ({label}): short high-funding quintile / long low-funding quintile, momentum-filtered")
    print("#" * 92)

    funding = funding.reindex(close.index)
    start = funding.dropna(how="all").index.min()
    cclose = close.loc[close.index >= start]
    cfund = funding.loc[cclose.index]
    momf, sig, nret = build_signals(cclose, CARRY_MOM_LOOKBACK)
    all_coins = cclose.columns.tolist()
    cost_vec = pd.Series({c: cost_bps.get(c, 15.0) / 10000.0 for c in all_coins}).reindex(all_coins).fillna(0.15)
    fwd_period_ret = cclose.shift(-rebalance_period) / cclose - 1.0

    prev_w = pd.Series(0.0, index=all_coins)
    held_w = pd.Series(0.0, index=all_coins)
    rows = []
    for i, t in enumerate(cclose.index):
        r_t = nret.loc[t].fillna(0.0)
        ic = np.nan
        if i % rebalance_period == 0:
            f_t, s_t, m_t = cfund.loc[t], sig.loc[t], momf.loc[t]
            valid = f_t.notna() & s_t.notna() & (s_t > 1e-9) & m_t.notna()
            n_valid = int(valid.sum())
            w = pd.Series(0.0, index=all_coins)
            if n_valid >= MIN_VALID_FOR_TRADE:
                v = f_t[valid].index
                q = min(max(MIN_PER_LEG, round(n_valid * QUINTILE_FRAC)), n_valid // 2)
                fr = f_t[v].sort_values(ascending=False)
                short_c, long_c = fr.index[:q], fr.index[-q:]
                mr = m_t[v].sort_values(ascending=False)
                mq = max(1, round(n_valid * QUINTILE_FRAC))
                top_m, bot_m = set(mr.index[:mq]), set(mr.index[-mq:])
                shorts = [c for c in short_c if c not in top_m]
                longs = [c for c in long_c if c not in bot_m]
                if shorts and longs:
                    ivs, ivl = 1.0 / s_t[shorts], 1.0 / s_t[longs]
                    w.loc[shorts] = -(ivs / ivs.sum()) * 0.5
                    w.loc[longs] = (ivl / ivl.sum()) * 0.5
                    fwd = fwd_period_ret.loc[t]
                    icv = valid & fwd.notna()
                    if int(icv.sum()) >= 5:
                        ic = stats.spearmanr(-f_t[icv].values, fwd[icv].values).correlation
            held_w = w
        else:
            w = held_w
        turnover = (w - prev_w).abs()
        cost = float((turnover * cost_vec).sum())
        gross = float((w * r_t).sum())
        rows.append({"date": t, "gross_ret": gross, "cost": cost, "net_ret": gross - cost,
                     "ic": ic, "traded": bool((w != 0).any())})
        prev_w = w

    res = pd.DataFrame(rows).set_index("date")
    ps_n, ps_g, ics = perf_stats(res, "net_ret"), perf_stats(res, "gross_ret"), ic_stats(res)
    print(f"  coverage {start.date()}->{res.index.max().date()}  n_days={ps_n['n']}")
    print(f"  gross/day={fmt_pct(ps_g['mean'])}  net/day={fmt_pct(ps_n['mean'])}  net ann={fmt_pct(ps_n['ann_ret'])}  "
          f"Sharpe={ps_n['sharpe']:.2f}  net t={ps_n['t_stat']:.2f}  costDrag={cost_drag_pct(res):.1f}%")
    print(f"  IC={ics['mean_ic']:.3f}  IC t={ics['t_stat']:.2f}  "
          f"-> {'PASS' if (pd.notna(ps_n['t_stat']) and ps_n['t_stat']>T_STAT_BAR and ics['mean_ic']>IC_BAR and ics['t_stat']>IC_T_BAR) else 'FAIL'}")
    split = int(len(res) * WALKFORWARD_SPLIT)
    ps_oos = perf_stats(res.iloc[split:], "net_ret")
    print(f"  OOS (last 40%, n={ps_oos['n']}): net/day={fmt_pct(ps_oos['mean'])} net t={ps_oos['t_stat']:.2f}")
    return {"net_mean": ps_n["mean"], "net_t": ps_n["t_stat"], "oos_t": ps_oos["t_stat"]}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    print("=" * 92)
    print("LONG-TAIL ALPHA: cross-sectional momentum backtest — DAILY vs WEEKLY rebalance")
    print("=" * 92)
    coins, cost_bps = load_universe()
    close = load_close_panel(coins)
    funding = load_funding_panel(coins)
    market, used_btc = load_market_proxy(close)
    print(f"Universe {len(coins)} coins; cost_bps {min(cost_bps.values()):.1f}-{max(cost_bps.values()):.1f}. "
          f"Close panel {close.shape[0]}d x {close.shape[1]} ({close.index.min().date()}->{close.index.max().date()}).")
    print(f"Regime proxy: {'BTC daily (data/cache/BTC_daily_420d.csv)' if used_btc else 'EW basket of universe'}.")

    # DAILY (baseline, for contrast) then WEEKLY (the retry)
    daily = run_gauntlet(close, cost_bps, coins, [3, 7, 14], 1, "DAILY REBALANCE", market, used_btc)
    weekly = run_gauntlet(close, cost_bps, coins, [7, 14, 28], 7, "WEEKLY REBALANCE", market, used_btc)

    run_carry(close, funding, cost_bps, coins, 1, "daily")
    carry_w = run_carry(close, funding, cost_bps, coins, 7, "weekly")

    # SURVIVORSHIP reminder
    print("\n" + "#" * 92)
    print("# SURVIVORSHIP BIAS — the 25 coins are TODAY's liquid survivors. Any positive result is an")
    print("# OPTIMISTIC UPPER BOUND (failed/delisted/churned alts never entered the ranking pool). Not")
    print("# proof of live edge; the only real test is a forward shadow run with the point-in-time")
    print("# universe screener. If it fails net/OOS/jackknife even here, it is dead.")
    print("#" * 92)

    # HEADLINE
    print("\n" + "=" * 92)
    print("HEADLINE — did WEEKLY rebalance rescue XS-momentum?")
    print("=" * 92)
    print(f"Cost drag on best lookback:  DAILY={daily['full_best_costdrag']:.1f}%  ->  "
          f"WEEKLY={weekly['full_best_costdrag']:.1f}%   (turnover-cost lever)")
    print(f"OOS decider (best L, unseen 40%):")
    print(f"  DAILY  L={daily['best_L']}: OOS net Sharpe={daily['oos_net_sharpe']:.2f}  OOS net t={daily['oos_net_t']:.2f}")
    print(f"  WEEKLY L={weekly['best_L']}: OOS net Sharpe={weekly['oos_net_sharpe']:.2f}  OOS net t={weekly['oos_net_t']:.2f}  "
          f"IC={weekly['oos_ic']:.3f}")
    print(f"  bar: OOS net t>{OOS_T_BAR} and IC>{IC_BAR}")
    weekly_ok = weekly["oos_net_t"] > OOS_T_BAR and weekly["oos_ic"] > IC_BAR
    print(f"WEEKLY jackknife: {weekly['n_flip']}/{len(coins)} sign flips, drop-top-3 net mean/day={fmt_pct(weekly['drop3_mean'])}; "
          f"regime {weekly['regime_ok']}/3")
    if weekly_ok and weekly["n_flip"] == 0 and weekly["drop3_mean"] > 0 and weekly["regime_ok"] >= 2:
        verdict = "YES-PROMISING (shadow-worthy) — weekly clears OOS+jackknife+regime"
    elif weekly["oos_net_mean"] > 0 and weekly["full_best_costdrag"] < 15:
        verdict = ("NO — cost drag DID drop sharply but OOS is still noise. That means the SIGNAL is weak, "
                   "not just costly: XS-momentum on this universe is DEAD.")
    else:
        verdict = "NO — weekly does not clear the OOS bar. Null."
    print(f"\n>>> {verdict} <<<")
    print(f"Carry (weekly): net/day={fmt_pct(carry_w['net_mean'])} t={carry_w['net_t']:.2f} OOS t={carry_w['oos_t']:.2f} — "
          f"{'still null/negative' if not (pd.notna(carry_w['net_t']) and carry_w['net_t']>T_STAT_BAR) else 'passes'}")
    print("(Survivorship-biased upper bound — see note above.)")


if __name__ == "__main__":
    main()
