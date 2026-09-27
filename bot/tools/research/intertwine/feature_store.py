"""
Frontier-2 feature store (READ-ONLY research tool).

Builds one row per deduped signal-surface event (see PREREGISTRATION.md) with
leak-free AS-OF joined funding/OI, depth/crowd, and price-label columns.

Reads only from:
  - data/llm/decisions.jsonl   (signal surface substitute, see prereg §0)
  - data/funding_oi_history.jsonl
  - data/market_depth_history.jsonl
  - freshly-fetched HL 1h candles (scratchpad, fetched read-only over public API)

Writes only to tools/research/intertwine/ (this directory). Never imports any
bot module, never writes to data/, .env, or data/replay/.
"""
import json
import math
import os
import bisect
from datetime import datetime, timezone

import pandas as pd
import numpy as np

BOT_ROOT = r"C:\Users\vince\WAGMI\bot"
DECISIONS_PATH = os.path.join(BOT_ROOT, "data", "llm", "decisions.jsonl")
FUNDING_OI_PATH = os.path.join(BOT_ROOT, "data", "funding_oi_history.jsonl")
DEPTH_PATH = os.path.join(BOT_ROOT, "data", "market_depth_history.jsonl")
CANDLE_DIR = r"C:\Users\vince\AppData\Local\Temp\claude\C--Users-vince\6fad1965-9726-4e6a-b6d6-9dcf0b9f2c97\scratchpad\hl_candles"
OUT_DIR = os.path.join(BOT_ROOT, "tools", "research", "intertwine")

SYMBOLS = ["BTC", "ETH", "SOL", "XRP", "HYPE"]
ROUND_TRIP_FEE = 0.0009  # 9 bps


def iso_to_epoch(s):
    if s is None:
        return None
    s2 = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s2)
    except ValueError:
        # some funding_oi timestamps lack tz info -> treat as UTC
        dt = datetime.fromisoformat(s2)
        dt = dt.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


# ---------------------------------------------------------------------------
# 1. Load raw sources
# ---------------------------------------------------------------------------

def load_decisions():
    rows = []
    with open(DECISIONS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "snapshot" not in d:
                continue
            snap = d["snapshot"]
            ts = d.get("ts")
            if ts is None:
                continue
            regime = d.get("regime")
            m_by_sym = {m.get("s"): m for m in snap.get("m", []) if m.get("s") in SYMBOLS}
            # trigger/primary symbol proxy for regime bias direction (hyp 4):
            # use the symbol with largest |d1h| in this cycle's m-block as the
            # "driving" read, a documented approximation (regime is cycle-global).
            drive_sym, drive_d1h = None, 0.0
            for s, m in m_by_sym.items():
                if abs(m.get("d1h", 0) or 0) >= abs(drive_d1h):
                    drive_sym, drive_d1h = s, (m.get("d1h", 0) or 0)
            sd = snap.get("sd", {})
            for sym in SYMBOLS:
                sdv = sd.get(sym)
                if not sdv:
                    continue
                side = sdv.get("side")
                if side not in ("BUY", "SELL"):
                    continue
                agree = sdv.get("agree", 0)
                if agree is None or agree < 1:
                    continue
                mrow = m_by_sym.get(sym, {})
                rows.append({
                    "record_ts": ts,
                    "symbol": sym,
                    "side": side,
                    "side_sign": 1 if side == "BUY" else -1,
                    "agree": agree,
                    "dissent": sdv.get("dissent", 0),
                    "avg_conf": sdv.get("avg_conf"),
                    "pass_votes": sdv.get("pass_votes"),
                    "price": mrow.get("p"),
                    "d1h": mrow.get("d1h"),
                    "d24h": mrow.get("d24h"),
                    "vr": mrow.get("vr"),
                    "regime": regime,
                    "regime_drive_d1h": drive_d1h,
                })
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["price"]).reset_index(drop=True)
    return df


def load_funding_oi():
    rows = []
    with open(FUNDING_OI_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            ts = iso_to_epoch(d["timestamp"])
            rows.append({
                "ts": ts,
                "symbol": d["symbol"],
                "funding_rate": d.get("funding_rate"),
                "open_interest": d.get("open_interest"),
                "premium": d.get("premium"),
                "oi_volume_ratio": d.get("oi_volume_ratio"),
            })
    df = pd.DataFrame(rows).sort_values(["symbol", "ts"]).reset_index(drop=True)
    return df


def load_depth():
    rows = []
    with open(DEPTH_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            ts = iso_to_epoch(d["ts"])
            l2 = d.get("l2") or {}
            trades = d.get("trades") or {}
            fctx = d.get("futures_ctx") or {}
            rows.append({
                "ts": ts,
                "symbol": d["symbol"],
                "spread_bps": l2.get("spread_bps"),
                "imbalance_0_1pct": l2.get("imbalance_0_1pct"),
                "imbalance_0_5pct": l2.get("imbalance_0_5pct"),
                "imbalance_1pct": l2.get("imbalance_1pct"),
                "buy_ratio": trades.get("buy_ratio"),
                "basis_bps": fctx.get("basis_bps"),
                "funding_rate_depth": fctx.get("funding_rate"),
                "long_short_account_ratio": fctx.get("long_short_account_ratio"),
                "taker_buy_sell_ratio": fctx.get("taker_buy_sell_ratio"),
            })
    df = pd.DataFrame(rows).sort_values(["symbol", "ts"]).reset_index(drop=True)
    return df


def load_candles():
    out = {}
    for sym in SYMBOLS:
        path = os.path.join(CANDLE_DIR, f"{sym}_1h.json")
        with open(path, encoding="utf-8") as f:
            candles = json.load(f)
        ts = [c["t"] / 1000.0 for c in candles]
        close = [float(c["c"]) for c in candles]
        out[sym] = (ts, close)  # both sorted ascending (API returns in order)
    return out


# ---------------------------------------------------------------------------
# 2. As-of join helpers (leak-free: only source rows with ts <= event_ts,
#    within tolerance; else NaN). Also expose the matched source ts so the
#    leak test can assert max(source_ts) <= event_ts directly.
# ---------------------------------------------------------------------------

def asof_join_group(events, source_df, tol_seconds, prefix):
    """events: DataFrame with record_ts, symbol. source_df: sorted by symbol, ts.
    Returns a DataFrame aligned to events.index with joined columns + '{prefix}_src_ts'.
    """
    out_cols = [c for c in source_df.columns if c not in ("ts", "symbol")]
    result = {f"{prefix}_{c}": [np.nan] * len(events) for c in out_cols}
    result[f"{prefix}_src_ts"] = [np.nan] * len(events)

    for sym, grp in source_df.groupby("symbol"):
        ts_arr = grp["ts"].to_numpy()
        idx_positions = np.where(events["symbol"].to_numpy() == sym)[0]
        if len(idx_positions) == 0:
            continue
        ev_ts = events["record_ts"].to_numpy()[idx_positions]
        # for each event ts, find rightmost source ts <= event_ts
        pos = np.searchsorted(ts_arr, ev_ts, side="right") - 1
        for k, p in zip(idx_positions, pos):
            if p < 0:
                continue
            src_ts = ts_arr[p]
            if ev_ts[list(idx_positions).index(k)] - src_ts > tol_seconds:
                continue
            row = grp.iloc[p]
            for c in out_cols:
                result[f"{prefix}_{c}"][k] = row[c]
            result[f"{prefix}_src_ts"][k] = src_ts
    return pd.DataFrame(result, index=events.index)


def rolling_trailing_pctile(source_df, value_col, window_days=30):
    """Per-symbol trailing percentile of value_col, computed strictly on prior
    rows only (expanding/rolling window ending before the current row's own ts,
    i.e. shift(1) semantics). Returns a Series aligned to source_df index."""
    out = pd.Series(index=source_df.index, dtype=float)
    for sym, grp in source_df.groupby("symbol"):
        grp = grp.sort_values("ts")
        vals = grp[value_col].to_numpy()
        tss = grp["ts"].to_numpy()
        window_s = window_days * 86400
        pctiles = np.full(len(vals), np.nan)
        for i in range(1, len(vals)):
            lo_ts = tss[i] - window_s
            # prior rows only: indices < i, within window
            j0 = np.searchsorted(tss[:i], lo_ts, side="left")
            hist = vals[j0:i]
            hist = hist[~np.isnan(hist)]
            if len(hist) < 10:
                continue
            pctiles[i] = (hist < vals[i]).mean() * 100
        out.loc[grp.index] = pctiles
    return out


def event_time_pctile_lookup(events, source_df, pctile_col, tol_seconds, prefix):
    """As-of join a precomputed trailing-percentile column onto events."""
    tmp = source_df[["ts", "symbol", pctile_col]].rename(columns={pctile_col: "_val"})
    j = asof_join_group(events, tmp, tol_seconds, prefix)
    return j[f"{prefix}__val"], j[f"{prefix}_src_ts"]


def forward_label(events, candles, horizon_hours, shift_periods=0):
    """Forward net return in signal direction. shift_periods used only for the
    future-shift leak canary (shifts the ENTRY reference forward, not used in
    the real pipeline; kept separate, see leak_tests.py)."""
    rets = np.full(len(events), np.nan)
    for sym, grp in events.groupby("symbol"):
        if sym not in candles:
            continue
        ts_arr, close_arr = candles[sym]
        ts_arr = np.array(ts_arr)
        close_arr = np.array(close_arr)
        idxs = grp.index.to_numpy()
        ev_ts = grp["record_ts"].to_numpy()
        entry_px = grp["price"].to_numpy()
        side_sign = grp["side_sign"].to_numpy()
        target_ts = ev_ts + horizon_hours * 3600
        pos = np.searchsorted(ts_arr, target_ts, side="left")
        for k in range(len(idxs)):
            p = pos[k]
            if p >= len(ts_arr):
                continue
            # nearest candle within 30 min tolerance
            candidates = []
            if p < len(ts_arr):
                candidates.append(p)
            if p > 0:
                candidates.append(p - 1)
            best = min(candidates, key=lambda pp: abs(ts_arr[pp] - target_ts[k]))
            if abs(ts_arr[best] - target_ts[k]) > 1800:
                continue
            fwd_px = close_arr[best]
            if entry_px[k] is None or entry_px[k] <= 0:
                continue
            raw_ret = side_sign[k] * (fwd_px / entry_px[k] - 1)
            rets[idxs[k]] = raw_ret
    return rets


# ---------------------------------------------------------------------------
# 3. Dedupe
# ---------------------------------------------------------------------------

def dedupe(events):
    events = events.sort_values("record_ts").copy()
    events["bucket4h"] = (events["record_ts"] // (4 * 3600)).astype(int)
    events["dedup_key"] = list(zip(events["symbol"], events["side"], events["bucket4h"]))
    before = len(events)
    events = events.drop_duplicates(subset="dedup_key", keep="first").reset_index(drop=True)
    after = len(events)
    print(f"[dedupe] {before} raw events -> {after} deduped (factor {before/max(after,1):.2f}x)")
    return events


# ---------------------------------------------------------------------------
# main build
# ---------------------------------------------------------------------------

def build(future_shift=False):
    print("Loading decisions.jsonl signal surface...")
    events = load_decisions()
    print(f"  raw (record,symbol) events with side+agree>=1: {len(events)}")

    events = dedupe(events)

    print("Loading funding/OI and depth history...")
    fo = load_funding_oi()
    depth = load_depth()

    fo_tol = 1800  # 30 min
    depth_tol = 600  # 10 min
    if future_shift:
        # leak canary: shift source timestamps forward so the join can see
        # data that was not yet available at event_ts (deliberately broken)
        fo = fo.copy(); fo["ts"] = fo["ts"] + 26 * 60
        depth = depth.copy(); depth["ts"] = depth["ts"] + 15 * 60
        fo_tol += 26 * 60
        depth_tol += 15 * 60

    fo_j = asof_join_group(events, fo, fo_tol, "fo")
    depth_j = asof_join_group(events, depth, depth_tol, "depth")

    events = pd.concat([events, fo_j, depth_j], axis=1)

    # rolling trailing percentiles (computed on the source history itself,
    # strictly prior rows, THEN as-of joined onto events using the same
    # matched source row index -> no additional leak)
    print("Computing trailing percentiles (funding, long_short_ratio, oi_volume_ratio)...")
    fo = fo.sort_values(["symbol", "ts"]).reset_index(drop=True)
    fo["funding_pctile"] = rolling_trailing_pctile(fo, "funding_rate")
    fo["oi_vol_ratio_pctile"] = rolling_trailing_pctile(fo, "oi_volume_ratio")
    depth = depth.sort_values(["symbol", "ts"]).reset_index(drop=True)
    depth["ls_ratio_pctile"] = rolling_trailing_pctile(depth, "long_short_account_ratio")
    depth["spread_bps_median_trail"] = np.nan
    for sym, grp in depth.groupby("symbol"):
        med = grp["spread_bps"].expanding().median().shift(1)
        depth.loc[grp.index, "spread_bps_median_trail"] = med

    fo_pctile_j = asof_join_group(events, fo[["ts", "symbol", "funding_pctile", "oi_volume_ratio"]].rename(
        columns={"oi_volume_ratio": "oivr_dup"}), fo_tol, "fop")
    events["funding_pctile"] = fo_pctile_j["fop_funding_pctile"]

    oivr_pctile_only = asof_join_group(
        events, fo[["ts", "symbol"]].assign(**{"oi_vol_ratio_pctile": fo["oi_vol_ratio_pctile"]}),
        fo_tol, "oivrpc")
    events["oi_vol_ratio_pctile"] = oivr_pctile_only["oivrpc_oi_vol_ratio_pctile"]

    ls_pctile_j = asof_join_group(
        events, depth[["ts", "symbol"]].assign(ls_ratio_pctile=depth["ls_ratio_pctile"]),
        depth_tol, "lsp")
    events["ls_ratio_pctile"] = ls_pctile_j["lsp_ls_ratio_pctile"]

    spread_med_j = asof_join_group(
        events, depth[["ts", "symbol"]].assign(spread_bps_median_trail=depth["spread_bps_median_trail"]),
        depth_tol, "smed")
    events["spread_bps_median_trail"] = spread_med_j["smed_spread_bps_median_trail"]

    # OI deltas: 1h and 24h, computed from the funding_oi series itself
    print("Computing OI deltas (1h, 24h)...")
    events["oi_delta_1h"] = np.nan
    events["oi_delta_24h"] = np.nan
    for sym, grp in fo.groupby("symbol"):
        grp = grp.sort_values("ts")
        tss = grp["ts"].to_numpy()
        ois = grp["open_interest"].to_numpy()
        idxs = events.index[events["symbol"] == sym]
        for i in idxs:
            src_ts = events.at[i, "fo_src_ts"]
            if pd.isna(src_ts):
                continue
            # find position of the as-of matched row
            p = np.searchsorted(tss, src_ts, side="right") - 1
            if p < 0:
                continue
            cur_oi = ois[p]
            for h, col in ((1, "oi_delta_1h"), (24, "oi_delta_24h")):
                target = tss[p] - h * 3600
                q = np.searchsorted(tss[:p + 1], target, side="right") - 1
                if q < 0:
                    continue
                if tss[p] - tss[q] > (h * 3600 + fo_tol):
                    continue
                past_oi = ois[q]
                if past_oi and not np.isnan(past_oi) and past_oi != 0:
                    events.at[i, col] = (cur_oi - past_oi) / abs(past_oi)

    print("Loading HL candles and computing forward labels...")
    candles = load_candles()
    events["fwd_ret_2h"] = forward_label(events, candles, 2)
    events["fwd_ret_6h"] = forward_label(events, candles, 6)
    events["net_ret_2h"] = events["fwd_ret_2h"] - (ROUND_TRIP_FEE + events["depth_spread_bps"].fillna(0) / 10000)
    events["net_ret_6h"] = events["fwd_ret_6h"] - (ROUND_TRIP_FEE + events["depth_spread_bps"].fillna(0) / 10000)
    # where spread unavailable, cost falls back to flat 9bps (spread term is 0 via fillna(0)) -> already handled

    return events


if __name__ == "__main__":
    ev = build(future_shift=False)
    out_path = os.path.join(OUT_DIR, "feature_store.csv")
    ev.to_csv(out_path, index=False)
    print(f"Saved {len(ev)} rows -> {out_path}")
    print(ev.dtypes)
    print(ev[["record_ts", "symbol", "side", "fwd_ret_2h", "net_ret_2h"]].describe())

    ev_shift = build(future_shift=True)
    out_path2 = os.path.join(OUT_DIR, "feature_store_futureshift.csv")
    ev_shift.to_csv(out_path2, index=False)
    print(f"Saved future-shift canary store -> {out_path2}")
