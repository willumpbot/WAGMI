"""
Oversold Alpha Study — Research analysis for extreme oversold conditions.

Answers:
1. When BTC RSI < 20, what happens to HYPE in next 1h/3h/6h/12h/24h?
2. When HYPE shows >1% alpha vs BTC over 3h, does it continue or mean-revert?
3. When BTC RSI < 20 AND HYPE has >0.5% alpha, what's the optimal HYPE trade?
"""
import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from data.fetcher import DataFetcher

COIN_IDS = {"HYPE": "hyperliquid", "SOL": "solana", "BTC": "bitcoin"}


def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def fetch_data():
    """Fetch 500 1h candles for each symbol."""
    fetcher = DataFetcher()
    data = {}
    for sym in ["HYPE", "BTC", "SOL"]:
        df = fetcher.fetch_ohlcv(sym, COIN_IDS[sym], "1h")
        if df is not None and not df.empty:
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.sort_values("time").reset_index(drop=True)
            df["rsi"] = compute_rsi(df["close"])
            df["returns"] = df["close"].pct_change() * 100  # percent
            data[sym] = df
            print(f"  {sym}: {len(df)} candles, range {df['time'].iloc[0]} to {df['time'].iloc[-1]}")
            print(f"    Current RSI: {df['rsi'].iloc[-1]:.1f}, Price: {df['close'].iloc[-1]:.4f}")
    return data


def forward_returns(df, idx, horizons=[1, 3, 6, 12, 24]):
    """Calculate forward returns at various horizons from index."""
    results = {}
    for h in horizons:
        if idx + h < len(df):
            ret = (df["close"].iloc[idx + h] - df["close"].iloc[idx]) / df["close"].iloc[idx] * 100
            high_max = df["high"].iloc[idx+1:idx+h+1].max()
            low_min = df["low"].iloc[idx+1:idx+h+1].min()
            mfe = (high_max - df["close"].iloc[idx]) / df["close"].iloc[idx] * 100
            mae = (df["close"].iloc[idx] - low_min) / df["close"].iloc[idx] * 100
            results[f"{h}h_ret"] = ret
            results[f"{h}h_mfe"] = mfe  # max favorable (for long)
            results[f"{h}h_mae"] = mae  # max adverse (for long)
        else:
            results[f"{h}h_ret"] = np.nan
            results[f"{h}h_mfe"] = np.nan
            results[f"{h}h_mae"] = np.nan
    return results


def study_1_btc_oversold(data):
    """When BTC RSI < 20, what happens to HYPE?"""
    print("\n" + "=" * 70)
    print("  STUDY 1: BTC Extreme Oversold (RSI < 20) -> HYPE Forward Returns")
    print("=" * 70)

    btc = data["BTC"]
    hype = data["HYPE"]

    # Align timestamps
    btc_times = set(btc["time"])
    hype_time_to_idx = {t: i for i, t in enumerate(hype["time"])}

    events = []
    last_event_idx = -6  # cooldown

    for i in range(20, len(btc)):
        rsi = btc["rsi"].iloc[i]
        if pd.isna(rsi) or rsi >= 20:
            continue
        if i - last_event_idx < 6:  # 6h cooldown between events
            continue
        last_event_idx = i

        t = btc["time"].iloc[i]
        if t not in hype_time_to_idx:
            continue

        hype_idx = hype_time_to_idx[t]
        fwd = forward_returns(hype, hype_idx)
        btc_fwd = forward_returns(btc, i)

        event = {
            "time": str(t)[:16],
            "btc_rsi": rsi,
            "btc_price": btc["close"].iloc[i],
            "hype_price": hype["close"].iloc[hype_idx],
            "hype_rsi": hype["rsi"].iloc[hype_idx],
        }
        for k, v in fwd.items():
            event[f"hype_{k}"] = v
        for k, v in btc_fwd.items():
            event[f"btc_{k}"] = v

        events.append(event)

    print(f"\n  Found {len(events)} instances of BTC RSI < 20 in 500h window")

    if not events:
        # Try RSI < 25 as fallback
        print("  Trying RSI < 25...")
        last_event_idx = -6
        for i in range(20, len(btc)):
            rsi = btc["rsi"].iloc[i]
            if pd.isna(rsi) or rsi >= 25:
                continue
            if i - last_event_idx < 6:
                continue
            last_event_idx = i
            t = btc["time"].iloc[i]
            if t not in hype_time_to_idx:
                continue
            hype_idx = hype_time_to_idx[t]
            fwd = forward_returns(hype, hype_idx)
            btc_fwd = forward_returns(btc, i)
            event = {
                "time": str(t)[:16],
                "btc_rsi": rsi,
                "btc_price": btc["close"].iloc[i],
                "hype_price": hype["close"].iloc[hype_idx],
                "hype_rsi": hype["rsi"].iloc[hype_idx],
            }
            for k, v in fwd.items():
                event[f"hype_{k}"] = v
            for k, v in btc_fwd.items():
                event[f"btc_{k}"] = v
            events.append(event)
        print(f"  Found {len(events)} instances of BTC RSI < 25")

    if not events:
        # Try RSI < 30
        print("  Trying RSI < 30...")
        last_event_idx = -6
        for i in range(20, len(btc)):
            rsi = btc["rsi"].iloc[i]
            if pd.isna(rsi) or rsi >= 30:
                continue
            if i - last_event_idx < 6:
                continue
            last_event_idx = i
            t = btc["time"].iloc[i]
            if t not in hype_time_to_idx:
                continue
            hype_idx = hype_time_to_idx[t]
            fwd = forward_returns(hype, hype_idx)
            btc_fwd = forward_returns(btc, i)
            event = {
                "time": str(t)[:16],
                "btc_rsi": rsi,
                "btc_price": btc["close"].iloc[i],
                "hype_price": hype["close"].iloc[hype_idx],
                "hype_rsi": hype["rsi"].iloc[hype_idx],
            }
            for k, v in fwd.items():
                event[f"hype_{k}"] = v
            for k, v in btc_fwd.items():
                event[f"btc_{k}"] = v
            events.append(event)
        print(f"  Found {len(events)} instances of BTC RSI < 30")

    if events:
        print(f"\n  {'Time':<20} {'BTC RSI':>8} {'HYPE RSI':>9} | {'1h':>6} {'3h':>6} {'6h':>6} {'12h':>6} {'24h':>6} | {'HYPE alpha vs BTC (24h)':>24}")
        print("  " + "-" * 110)
        for e in events:
            alpha_24h = e.get("hype_24h_ret", 0) - e.get("btc_24h_ret", 0) if not pd.isna(e.get("hype_24h_ret", np.nan)) and not pd.isna(e.get("btc_24h_ret", np.nan)) else np.nan
            alpha_str = f"{alpha_24h:+.2f}%" if not pd.isna(alpha_24h) else "N/A"
            h1 = f"{e.get('hype_1h_ret', 0):+.2f}%" if not pd.isna(e.get('hype_1h_ret', np.nan)) else "N/A"
            h3 = f"{e.get('hype_3h_ret', 0):+.2f}%" if not pd.isna(e.get('hype_3h_ret', np.nan)) else "N/A"
            h6 = f"{e.get('hype_6h_ret', 0):+.2f}%" if not pd.isna(e.get('hype_6h_ret', np.nan)) else "N/A"
            h12 = f"{e.get('hype_12h_ret', 0):+.2f}%" if not pd.isna(e.get('hype_12h_ret', np.nan)) else "N/A"
            h24 = f"{e.get('hype_24h_ret', 0):+.2f}%" if not pd.isna(e.get('hype_24h_ret', np.nan)) else "N/A"
            print(f"  {e['time']:<20} {e['btc_rsi']:>7.1f} {e['hype_rsi']:>9.1f} | {h1:>6} {h3:>6} {h6:>6} {h12:>6} {h24:>6} | {alpha_str:>24}")

        # Summary stats
        print("\n  --- SUMMARY: HYPE forward returns when BTC is oversold ---")
        for h in [1, 3, 6, 12, 24]:
            rets = [e[f"hype_{h}h_ret"] for e in events if not pd.isna(e.get(f"hype_{h}h_ret", np.nan))]
            mfes = [e[f"hype_{h}h_mfe"] for e in events if not pd.isna(e.get(f"hype_{h}h_mfe", np.nan))]
            maes = [e[f"hype_{h}h_mae"] for e in events if not pd.isna(e.get(f"hype_{h}h_mae", np.nan))]
            if rets:
                win_rate = sum(1 for r in rets if r > 0) / len(rets) * 100
                print(f"  {h:2d}h: avg={np.mean(rets):+.2f}%, median={np.median(rets):+.2f}%, "
                      f"WR={win_rate:.0f}% ({sum(1 for r in rets if r > 0)}/{len(rets)}), "
                      f"MFE={np.mean(mfes):.2f}%, MAE={np.mean(maes):.2f}%")

        # HYPE alpha vs BTC
        print("\n  --- HYPE ALPHA vs BTC when BTC is oversold ---")
        for h in [1, 3, 6, 12, 24]:
            alphas = []
            for e in events:
                hr = e.get(f"hype_{h}h_ret", np.nan)
                br = e.get(f"btc_{h}h_ret", np.nan)
                if not pd.isna(hr) and not pd.isna(br):
                    alphas.append(hr - br)
            if alphas:
                print(f"  {h:2d}h alpha: avg={np.mean(alphas):+.2f}%, "
                      f"median={np.median(alphas):+.2f}%, "
                      f"HYPE outperforms {sum(1 for a in alphas if a > 0)}/{len(alphas)} times "
                      f"({sum(1 for a in alphas if a > 0)/len(alphas)*100:.0f}%)")

    return events


def study_2_hype_alpha(data):
    """When HYPE shows >1% alpha vs BTC over 3h, what happens next?"""
    print("\n" + "=" * 70)
    print("  STUDY 2: HYPE Relative Strength (>1% alpha vs BTC over 3h)")
    print("=" * 70)

    btc = data["BTC"]
    hype = data["HYPE"]

    # Build aligned series
    btc_dict = {t: i for i, t in enumerate(btc["time"])}
    hype_dict = {t: i for i, t in enumerate(hype["time"])}
    common_times = sorted(set(btc["time"]) & set(hype["time"]))

    events = []
    last_event_idx = -6

    for ci, t in enumerate(common_times):
        if ci < 3:
            continue
        bi = btc_dict[t]
        hi = hype_dict[t]

        if bi < 3 or hi < 3:
            continue

        # 3h lookback alpha
        t_minus_3 = common_times[ci - 3] if ci >= 3 else None
        if t_minus_3 is None:
            continue
        if t_minus_3 not in btc_dict or t_minus_3 not in hype_dict:
            continue

        bi_3 = btc_dict[t_minus_3]
        hi_3 = hype_dict[t_minus_3]

        btc_3h_ret = (btc["close"].iloc[bi] - btc["close"].iloc[bi_3]) / btc["close"].iloc[bi_3] * 100
        hype_3h_ret = (hype["close"].iloc[hi] - hype["close"].iloc[hi_3]) / hype["close"].iloc[hi_3] * 100
        alpha_3h = hype_3h_ret - btc_3h_ret

        if alpha_3h <= 1.0:
            continue

        if ci - last_event_idx < 6:
            continue
        last_event_idx = ci

        fwd = forward_returns(hype, hi)
        btc_fwd = forward_returns(btc, bi)

        event = {
            "time": str(t)[:16],
            "alpha_3h": alpha_3h,
            "hype_3h_ret": hype_3h_ret,
            "btc_3h_ret": btc_3h_ret,
            "hype_rsi": hype["rsi"].iloc[hi],
            "btc_rsi": btc["rsi"].iloc[bi],
        }
        for k, v in fwd.items():
            event[f"hype_{k}"] = v
        for k, v in btc_fwd.items():
            event[f"btc_{k}"] = v
        events.append(event)

    print(f"\n  Found {len(events)} instances of HYPE >1% alpha vs BTC (3h)")

    if not events:
        # Try >0.5%
        print("  Trying >0.5% alpha...")
        last_event_idx = -6
        for ci, t in enumerate(common_times):
            if ci < 3:
                continue
            bi = btc_dict[t]
            hi = hype_dict[t]
            if bi < 3 or hi < 3:
                continue
            t_minus_3 = common_times[ci - 3] if ci >= 3 else None
            if t_minus_3 is None or t_minus_3 not in btc_dict or t_minus_3 not in hype_dict:
                continue
            bi_3 = btc_dict[t_minus_3]
            hi_3 = hype_dict[t_minus_3]
            btc_3h_ret = (btc["close"].iloc[bi] - btc["close"].iloc[bi_3]) / btc["close"].iloc[bi_3] * 100
            hype_3h_ret = (hype["close"].iloc[hi] - hype["close"].iloc[hi_3]) / hype["close"].iloc[hi_3] * 100
            alpha_3h = hype_3h_ret - btc_3h_ret
            if alpha_3h <= 0.5:
                continue
            if ci - last_event_idx < 6:
                continue
            last_event_idx = ci
            fwd = forward_returns(hype, hi)
            btc_fwd = forward_returns(btc, bi)
            event = {
                "time": str(t)[:16],
                "alpha_3h": alpha_3h,
                "hype_3h_ret": hype_3h_ret,
                "btc_3h_ret": btc_3h_ret,
                "hype_rsi": hype["rsi"].iloc[hi],
                "btc_rsi": btc["rsi"].iloc[bi],
            }
            for k, v in fwd.items():
                event[f"hype_{k}"] = v
            for k, v in btc_fwd.items():
                event[f"btc_{k}"] = v
            events.append(event)
        print(f"  Found {len(events)} instances of HYPE >0.5% alpha vs BTC (3h)")

    if events:
        print(f"\n  {'Time':<20} {'Alpha 3h':>9} {'HYPE RSI':>9} {'BTC RSI':>8} | HYPE forward: {'1h':>6} {'3h':>6} {'6h':>6} {'12h':>6} {'24h':>6}")
        print("  " + "-" * 110)
        for e in events:
            h1 = f"{e.get('hype_1h_ret', 0):+.2f}%" if not pd.isna(e.get('hype_1h_ret', np.nan)) else "N/A"
            h3 = f"{e.get('hype_3h_ret_fwd', e.get('hype_3h_ret', 0)):+.2f}%" if True else "N/A"
            # Use the forward returns
            vals = []
            for h in [1, 3, 6, 12, 24]:
                v = e.get(f"hype_{h}h_ret", np.nan)
                vals.append(f"{v:+.2f}%" if not pd.isna(v) else "N/A")
            print(f"  {e['time']:<20} {e['alpha_3h']:+8.2f}% {e['hype_rsi']:>8.1f} {e['btc_rsi']:>7.1f} | {vals[0]:>13} {vals[1]:>6} {vals[2]:>6} {vals[3]:>6} {vals[4]:>6}")

        # Continuation vs mean-reversion
        print("\n  --- Does HYPE alpha CONTINUE or MEAN-REVERT? ---")
        for h in [1, 3, 6, 12, 24]:
            fwd_alphas = []
            for e in events:
                hr = e.get(f"hype_{h}h_ret", np.nan)
                br = e.get(f"btc_{h}h_ret", np.nan)
                if not pd.isna(hr) and not pd.isna(br):
                    fwd_alphas.append(hr - br)
            if fwd_alphas:
                continues = sum(1 for a in fwd_alphas if a > 0)
                print(f"  {h:2d}h: HYPE continues outperforming {continues}/{len(fwd_alphas)} times "
                      f"({continues/len(fwd_alphas)*100:.0f}%), "
                      f"avg fwd alpha={np.mean(fwd_alphas):+.2f}%")

        # HYPE absolute forward returns
        print("\n  --- HYPE absolute forward returns after alpha event ---")
        for h in [1, 3, 6, 12, 24]:
            rets = [e[f"hype_{h}h_ret"] for e in events if not pd.isna(e.get(f"hype_{h}h_ret", np.nan))]
            mfes = [e[f"hype_{h}h_mfe"] for e in events if not pd.isna(e.get(f"hype_{h}h_mfe", np.nan))]
            maes = [e[f"hype_{h}h_mae"] for e in events if not pd.isna(e.get(f"hype_{h}h_mae", np.nan))]
            if rets:
                wr = sum(1 for r in rets if r > 0) / len(rets) * 100
                print(f"  {h:2d}h: avg={np.mean(rets):+.2f}%, WR={wr:.0f}%, "
                      f"MFE={np.mean(mfes):.2f}%, MAE={np.mean(maes):.2f}%")

    return events


def study_3_combo_signal(data):
    """BTC RSI < 20 (or <25/<30) AND HYPE alpha > 0.5% = optimal trade?"""
    print("\n" + "=" * 70)
    print("  STUDY 3: COMBO — BTC Oversold + HYPE Relative Strength")
    print("=" * 70)

    btc = data["BTC"]
    hype = data["HYPE"]

    btc_dict = {t: i for i, t in enumerate(btc["time"])}
    hype_dict = {t: i for i, t in enumerate(hype["time"])}
    common_times = sorted(set(btc["time"]) & set(hype["time"]))

    # Try multiple RSI thresholds
    for rsi_thresh in [20, 25, 30, 35]:
        for alpha_thresh in [0.5, 1.0]:
            events = []
            last_event_idx = -6

            for ci, t in enumerate(common_times):
                if ci < 3:
                    continue
                bi = btc_dict[t]
                hi = hype_dict[t]
                if bi < 14 or hi < 3:
                    continue

                btc_rsi = btc["rsi"].iloc[bi]
                if pd.isna(btc_rsi) or btc_rsi >= rsi_thresh:
                    continue

                # Check HYPE alpha over 3h
                t_minus_3 = common_times[ci - 3] if ci >= 3 else None
                if t_minus_3 is None or t_minus_3 not in btc_dict or t_minus_3 not in hype_dict:
                    continue
                bi_3 = btc_dict[t_minus_3]
                hi_3 = hype_dict[t_minus_3]
                btc_3h = (btc["close"].iloc[bi] - btc["close"].iloc[bi_3]) / btc["close"].iloc[bi_3] * 100
                hype_3h = (hype["close"].iloc[hi] - hype["close"].iloc[hi_3]) / hype["close"].iloc[hi_3] * 100
                alpha = hype_3h - btc_3h

                if alpha < alpha_thresh:
                    continue
                if ci - last_event_idx < 6:
                    continue
                last_event_idx = ci

                fwd = forward_returns(hype, hi)
                event = {
                    "time": str(t)[:16],
                    "btc_rsi": btc_rsi,
                    "hype_rsi": hype["rsi"].iloc[hi],
                    "alpha_3h": alpha,
                    "hype_price": hype["close"].iloc[hi],
                }
                for k, v in fwd.items():
                    event[f"hype_{k}"] = v
                events.append(event)

            if events:
                print(f"\n  BTC RSI < {rsi_thresh} + HYPE alpha > {alpha_thresh}%: {len(events)} events")
                for e in events:
                    vals = []
                    for h in [1, 3, 6, 12, 24]:
                        v = e.get(f"hype_{h}h_ret", np.nan)
                        vals.append(f"{v:+.2f}%" if not pd.isna(v) else "N/A")
                    print(f"    {e['time']} | BTC RSI={e['btc_rsi']:.1f} | HYPE RSI={e['hype_rsi']:.1f} | "
                          f"Alpha={e['alpha_3h']:+.2f}% | Fwd: {' '.join(vals)}")

                # Stats
                for h in [1, 3, 6, 12, 24]:
                    rets = [e[f"hype_{h}h_ret"] for e in events if not pd.isna(e.get(f"hype_{h}h_ret", np.nan))]
                    mfes = [e[f"hype_{h}h_mfe"] for e in events if not pd.isna(e.get(f"hype_{h}h_mfe", np.nan))]
                    maes = [e[f"hype_{h}h_mae"] for e in events if not pd.isna(e.get(f"hype_{h}h_mae", np.nan))]
                    if rets:
                        wr = sum(1 for r in rets if r > 0) / len(rets) * 100
                        print(f"    {h:2d}h: avg={np.mean(rets):+.2f}%, WR={wr:.0f}% ({sum(1 for r in rets if r>0)}/{len(rets)}), "
                              f"MFE={np.mean(mfes):.2f}%, MAE={np.mean(maes):.2f}%")

    return events


def study_4_optimal_trade(data):
    """Given the combo signal, what's the optimal SL/TP?"""
    print("\n" + "=" * 70)
    print("  STUDY 4: OPTIMAL TRADE PARAMETERS for Oversold+Alpha Setup")
    print("=" * 70)

    btc = data["BTC"]
    hype = data["HYPE"]

    btc_dict = {t: i for i, t in enumerate(btc["time"])}
    hype_dict = {t: i for i, t in enumerate(hype["time"])}
    common_times = sorted(set(btc["time"]) & set(hype["time"]))

    # Use widest filter to get enough events for statistics
    # BTC RSI < 35 (moderately oversold) + any positive alpha
    entry_indices = []
    last_event_idx = -6

    for ci, t in enumerate(common_times):
        if ci < 3:
            continue
        bi = btc_dict[t]
        hi = hype_dict[t]
        if bi < 20 or hi < 20:
            continue

        btc_rsi = btc["rsi"].iloc[bi]
        if pd.isna(btc_rsi) or btc_rsi >= 35:
            continue

        # Any positive alpha
        t_minus_3 = common_times[ci - 3] if ci >= 3 else None
        if t_minus_3 is None or t_minus_3 not in btc_dict or t_minus_3 not in hype_dict:
            continue
        bi_3 = btc_dict[t_minus_3]
        hi_3 = hype_dict[t_minus_3]
        btc_3h = (btc["close"].iloc[bi] - btc["close"].iloc[bi_3]) / btc["close"].iloc[bi_3] * 100
        hype_3h = (hype["close"].iloc[hi] - hype["close"].iloc[hi_3]) / hype["close"].iloc[hi_3] * 100
        alpha = hype_3h - btc_3h

        if alpha < 0:
            continue
        if ci - last_event_idx < 6:
            continue
        last_event_idx = ci
        entry_indices.append(hi)

    print(f"\n  Found {len(entry_indices)} entry points (BTC RSI<35 + HYPE alpha>0)")

    if not entry_indices:
        # Fallback: just use BTC oversold
        last_event_idx = -6
        for ci, t in enumerate(common_times):
            if ci < 3:
                continue
            bi = btc_dict[t]
            hi = hype_dict[t]
            if bi < 20 or hi < 20:
                continue
            btc_rsi = btc["rsi"].iloc[bi]
            if pd.isna(btc_rsi) or btc_rsi >= 40:
                continue
            if ci - last_event_idx < 6:
                continue
            last_event_idx = ci
            entry_indices.append(hi)
        print(f"  Fallback: {len(entry_indices)} entries with BTC RSI<40")

    if not entry_indices:
        print("  Not enough data for optimal trade analysis")
        return

    # Walk forward with different SL/TP combos
    configs = [
        ("Tight 1.0/1.5", 1.0, 1.5, 12),
        ("Tight 1.5/2.2", 1.5, 2.2, 12),
        ("Med 2.0/3.0", 2.0, 3.0, 12),
        ("Med 2.5/3.75", 2.5, 3.75, 12),
        ("Wide 3.0/4.5", 3.0, 4.5, 12),
        ("Wide 3.0/6.0", 3.0, 6.0, 24),
        ("Asymmetric 1.5/4.0", 1.5, 4.0, 12),
        ("Asymmetric 2.0/5.0", 2.0, 5.0, 12),
        ("Sniper 1.0/3.0", 1.0, 3.0, 8),
        ("Fat 3.0/8.0", 3.0, 8.0, 24),
    ]

    print(f"\n  {'Config':<22} {'Trades':>6} {'Wins':>5} {'WR':>5} {'PF':>6} {'Net%':>7} {'Avg MFE':>8} {'Avg MAE':>8}")
    print("  " + "-" * 80)

    for name, sl, tp, ts in configs:
        wins = 0
        losses = 0
        gross_profit = 0
        gross_loss = 0
        mfes = []
        maes = []

        for idx in entry_indices:
            if idx + ts + 1 >= len(hype):
                continue
            entry = hype["close"].iloc[idx]
            sl_price = entry * (1 - sl / 100)
            tp_price = entry * (1 + tp / 100)

            mfe = 0
            mae = 0
            outcome = None

            for b in range(1, min(ts + 1, len(hype) - idx)):
                c = hype.iloc[idx + b]
                fav = (c["high"] - entry) / entry * 100
                adv = (entry - c["low"]) / entry * 100
                mfe = max(mfe, fav)
                mae = max(mae, adv)

                sl_hit = c["low"] <= sl_price
                tp_hit = c["high"] >= tp_price

                if sl_hit and tp_hit:
                    if c["open"] < entry:
                        tp_hit = False
                    else:
                        sl_hit = False

                if sl_hit:
                    outcome = "LOSS"
                    break
                if tp_hit:
                    outcome = "WIN"
                    break

            if outcome is None:
                last = hype["close"].iloc[min(idx + ts, len(hype) - 1)]
                move = (last - entry) / entry * 100
                outcome = "TS_WIN" if move > 0 else "TS_LOSS"

            mfes.append(mfe)
            maes.append(mae)

            if outcome in ("WIN",):
                wins += 1
                gross_profit += tp
            elif outcome == "TS_WIN":
                wins += 1
                gross_profit += mfe * 0.5  # estimate
            elif outcome in ("LOSS",):
                losses += 1
                gross_loss += sl
            elif outcome == "TS_LOSS":
                losses += 1
                gross_loss += mae * 0.5

        total = wins + losses
        if total == 0:
            continue
        wr = wins / total * 100
        pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
        net = gross_profit - gross_loss
        pf_str = f"{pf:.2f}" if pf < 100 else "INF"

        print(f"  {name:<22} {total:>6} {wins:>5} {wr:>4.0f}% {pf_str:>6} {net:>+6.1f}% {np.mean(mfes):>7.2f}% {np.mean(maes):>7.2f}%")


def study_5_sol_oversold(data):
    """Bonus: When SOL RSI < 15 (like now), what happens?"""
    print("\n" + "=" * 70)
    print("  STUDY 5: SOL Extreme Oversold (RSI < 15) Forward Returns")
    print("=" * 70)

    sol = data.get("SOL")
    if sol is None:
        print("  No SOL data")
        return

    for rsi_thresh in [15, 20, 25, 30]:
        events = []
        last_idx = -6
        for i in range(20, len(sol)):
            rsi = sol["rsi"].iloc[i]
            if pd.isna(rsi) or rsi >= rsi_thresh:
                continue
            if i - last_idx < 6:
                continue
            last_idx = i
            fwd = forward_returns(sol, i)
            event = {"time": str(sol["time"].iloc[i])[:16], "rsi": rsi, "price": sol["close"].iloc[i]}
            event.update(fwd)
            events.append(event)

        if events:
            print(f"\n  SOL RSI < {rsi_thresh}: {len(events)} events")
            for h in [1, 3, 6, 12, 24]:
                rets = [e[f"{h}h_ret"] for e in events if not pd.isna(e.get(f"{h}h_ret", np.nan))]
                mfes = [e[f"{h}h_mfe"] for e in events if not pd.isna(e.get(f"{h}h_mfe", np.nan))]
                maes = [e[f"{h}h_mae"] for e in events if not pd.isna(e.get(f"{h}h_mae", np.nan))]
                if rets:
                    wr = sum(1 for r in rets if r > 0) / len(rets) * 100
                    print(f"    {h:2d}h: avg={np.mean(rets):+.2f}%, WR={wr:.0f}%, "
                          f"MFE={np.mean(mfes):.2f}%, MAE={np.mean(maes):.2f}%")
            # Show individual events
            for e in events:
                vals = []
                for h in [1, 3, 6, 12, 24]:
                    v = e.get(f"{h}h_ret", np.nan)
                    vals.append(f"{v:+.2f}%" if not pd.isna(v) else "N/A")
                print(f"    {e['time']} RSI={e['rsi']:.1f} Price={e['price']:.4f} | {' '.join(vals)}")


def main():
    print("=" * 70)
    print("  OVERSOLD + ALPHA STUDY")
    print("  BTC RSI ~14-15, SOL RSI ~9, HYPE relative strength +1.3%")
    print("  What does history say about this setup?")
    print("=" * 70)

    data = fetch_data()

    if len(data) < 2:
        print("ERROR: Could not fetch enough data")
        return

    study_1_btc_oversold(data)
    study_2_hype_alpha(data)
    study_3_combo_signal(data)
    study_4_optimal_trade(data)
    study_5_sol_oversold(data)

    print("\n" + "=" * 70)
    print("  ANALYSIS COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
