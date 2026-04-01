"""Cross-asset alpha analysis: BTC/SOL/HYPE divergence opportunities."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import numpy as np
import pandas as pd
from data.fetcher import DataFetcher


def rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period, min_periods=1).mean()
    rs = gain / loss.replace(0, 1e-12)
    return 100.0 - (100.0 / (1.0 + rs))


def main():
    fetcher = DataFetcher()

    symbols = {"HYPE": "hyperliquid", "BTC": "bitcoin", "SOL": "solana"}
    dfs = {}
    for sym, cid in symbols.items():
        df = fetcher.fetch_ohlcv(sym, cid, "1h")
        if df is not None and not df.empty:
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df = df.sort_values("time").reset_index(drop=True)
            for c in ["close", "high", "low", "volume"]:
                df[c] = df[c].astype(float)
            dfs[sym] = df
            print(f"{sym}: {len(df)} candles, last={df['close'].iloc[-1]:.2f}, time={df['time'].iloc[-1]}")

    for sym in dfs:
        dfs[sym]["ret"] = dfs[sym]["close"].pct_change() * 100
        dfs[sym]["rsi"] = rsi(dfs[sym]["close"])

    # Align by time
    merged = dfs["BTC"][["time", "close", "ret", "rsi"]].rename(
        columns={"close": "btc_close", "ret": "btc_ret", "rsi": "btc_rsi"}
    )
    for sym in ["SOL", "HYPE"]:
        tmp = dfs[sym][["time", "close", "ret", "rsi"]].rename(
            columns={"close": f"{sym.lower()}_close", "ret": f"{sym.lower()}_ret", "rsi": f"{sym.lower()}_rsi"}
        )
        merged = pd.merge(merged, tmp, on="time", how="inner")

    merged = merged.sort_values("time").reset_index(drop=True)
    print(f"\nAligned: {len(merged)} candles")
    print(f"Current prices: BTC={merged['btc_close'].iloc[-1]:.0f} SOL={merged['sol_close'].iloc[-1]:.2f} HYPE={merged['hype_close'].iloc[-1]:.4f}")
    print(f"Current RSI: BTC={merged['btc_rsi'].iloc[-1]:.1f} SOL={merged['sol_rsi'].iloc[-1]:.1f} HYPE={merged['hype_rsi'].iloc[-1]:.1f}")

    # ===== ANALYSIS 1: BTC RSI < 20 Events =====
    print("\n" + "=" * 70)
    print("ANALYSIS 1: BTC RSI < 20 Events - What happens to SOL & HYPE next 6h?")
    print("=" * 70)

    for threshold in [15, 20, 25, 30]:
        btc_os = merged[merged["btc_rsi"] < threshold]
        results = []
        for idx in btc_os.index:
            if idx + 6 < len(merged):
                r = {}
                for sym, col in [("btc", "btc_close"), ("sol", "sol_close"), ("hype", "hype_close")]:
                    for h in [3, 6, 12]:
                        if idx + h < len(merged):
                            r[f"{sym}_{h}h"] = (merged[col].iloc[idx + h] - merged[col].iloc[idx]) / merged[col].iloc[idx] * 100
                results.append(r)

        if results:
            rdf = pd.DataFrame(results)
            print(f"\n  BTC RSI < {threshold} (n={len(rdf)}):")
            for h in [3, 6, 12]:
                sc, bc, hc = f"sol_{h}h", f"btc_{h}h", f"hype_{h}h"
                if sc in rdf.columns and bc in rdf.columns:
                    print(f"    {h}h: BTC={rdf[bc].mean():+.2f}% SOL={rdf[sc].mean():+.2f}% HYPE={rdf[hc].mean():+.2f}% | SOL up%={(rdf[sc]>0).mean()*100:.0f}% | SOL excess over BTC={rdf[sc].mean()-rdf[bc].mean():+.2f}%")
        else:
            print(f"\n  BTC RSI < {threshold}: {len(btc_os)} events (none with 6h forward data)")

    # ===== ANALYSIS 2: HYPE Decoupling =====
    print("\n" + "=" * 70)
    print("ANALYSIS 2: HYPE Decouples from BTC (HYPE alpha >1% while BTC drops >1%)")
    print("=" * 70)

    merged["btc_4h_ret"] = merged["btc_close"].pct_change(4) * 100
    merged["hype_4h_ret"] = merged["hype_close"].pct_change(4) * 100
    merged["sol_4h_ret"] = merged["sol_close"].pct_change(4) * 100
    merged["hype_alpha"] = merged["hype_4h_ret"] - merged["btc_4h_ret"]

    decouple = merged[(merged["btc_4h_ret"] < -1) & (merged["hype_alpha"] > 1)]
    print(f"Decoupling events: {len(decouple)}")

    if len(decouple) > 0:
        dec_results = []
        for idx in decouple.index:
            for fwd in [3, 6, 12]:
                if idx + fwd < len(merged):
                    dec_results.append({
                        "time": merged["time"].iloc[idx],
                        "fwd_h": fwd,
                        "btc_4h": merged["btc_4h_ret"].iloc[idx],
                        "hype_alpha_at_entry": merged["hype_alpha"].iloc[idx],
                        "hype_fwd": (merged["hype_close"].iloc[idx + fwd] - merged["hype_close"].iloc[idx]) / merged["hype_close"].iloc[idx] * 100,
                        "sol_fwd": (merged["sol_close"].iloc[idx + fwd] - merged["sol_close"].iloc[idx]) / merged["sol_close"].iloc[idx] * 100,
                        "btc_fwd": (merged["btc_close"].iloc[idx + fwd] - merged["btc_close"].iloc[idx]) / merged["btc_close"].iloc[idx] * 100,
                    })

        ddf = pd.DataFrame(dec_results)
        for fwd_h in [3, 6, 12]:
            sub = ddf[ddf["fwd_h"] == fwd_h]
            if len(sub) > 0:
                print(f"\n  {fwd_h}h forward (n={len(sub)}):")
                print(f"    HYPE: mean={sub['hype_fwd'].mean():+.2f}%, up%={(sub['hype_fwd']>0).mean()*100:.0f}%")
                print(f"    SOL:  mean={sub['sol_fwd'].mean():+.2f}%, up%={(sub['sol_fwd']>0).mean()*100:.0f}%")
                print(f"    BTC:  mean={sub['btc_fwd'].mean():+.2f}%, up%={(sub['btc_fwd']>0).mean()*100:.0f}%")
                print(f"    Pairs (HYPE - SOL): mean={(sub['hype_fwd'] - sub['sol_fwd']).mean():+.2f}%")

        uniq = ddf[ddf["fwd_h"] == 6][["time", "btc_4h", "hype_alpha_at_entry", "hype_fwd", "sol_fwd", "btc_fwd"]].head(20)
        print("\n  Individual decoupling events (6h forward):")
        for _, r in uniq.iterrows():
            t = r["time"]
            ts = t.strftime("%m-%d %H:%M") if hasattr(t, "strftime") else str(t)
            print(f"    {ts} BTC4h={r['btc_4h']:+.1f}% HYPEalpha={r['hype_alpha_at_entry']:+.1f}% -> HYPE6h={r['hype_fwd']:+.1f}% SOL6h={r['sol_fwd']:+.1f}% BTC6h={r['btc_fwd']:+.1f}%")

    # ===== ANALYSIS 3: SOL Extreme Oversold =====
    print("\n" + "=" * 70)
    print("ANALYSIS 3: SOL Extreme Oversold - Forward Returns")
    print("=" * 70)

    for threshold in [10, 15, 20, 25, 30]:
        subset = merged[merged["sol_rsi"] < threshold]
        if len(subset) == 0:
            print(f"\n  SOL RSI < {threshold}: 0 events")
            continue

        fwd_results = []
        for idx in subset.index:
            r = {"rsi": merged["sol_rsi"].iloc[idx], "time": merged["time"].iloc[idx]}
            for h in [1, 3, 6, 12, 24]:
                if idx + h < len(merged):
                    r[f"sol_{h}h"] = (merged["sol_close"].iloc[idx + h] - merged["sol_close"].iloc[idx]) / merged["sol_close"].iloc[idx] * 100
                    r[f"btc_{h}h"] = (merged["btc_close"].iloc[idx + h] - merged["btc_close"].iloc[idx]) / merged["btc_close"].iloc[idx] * 100
            fwd_results.append(r)

        fdf = pd.DataFrame(fwd_results)
        print(f"\n  SOL RSI < {threshold} (n={len(fdf)}):")
        for h in [1, 3, 6, 12, 24]:
            sc, bc = f"sol_{h}h", f"btc_{h}h"
            if sc in fdf.columns and bc in fdf.columns:
                sol_up = (fdf[sc] > 0).mean() * 100
                excess = fdf[sc].mean() - fdf[bc].mean()
                print(f"    {h}h: SOL={fdf[sc].mean():+.2f}% (up {sol_up:.0f}%) | BTC={fdf[bc].mean():+.2f}% | SOL excess={excess:+.2f}%")

        # Show individual events for extreme ones
        if threshold <= 15 and len(fdf) > 0:
            print(f"    Events:")
            for _, r in fdf.iterrows():
                t = r["time"]
                ts = t.strftime("%m-%d %H:%M") if hasattr(t, "strftime") else str(t)
                s6 = r.get("sol_6h", float("nan"))
                b6 = r.get("btc_6h", float("nan"))
                print(f"      {ts} RSI={r['rsi']:.1f} -> SOL6h={s6:+.2f}% BTC6h={b6:+.2f}%")

    # ===== ANALYSIS 4: BTC-SOL Panic Correlation =====
    print("\n" + "=" * 70)
    print("ANALYSIS 4: BTC-SOL Panic Correlation - Does SOL Bounce Harder?")
    print("=" * 70)

    btc_panic = merged[merged["btc_4h_ret"] < -2]
    print(f"BTC panic events (4h drop > 2%): {len(btc_panic)}")

    if len(btc_panic) > 0:
        panic_results = []
        for idx in btc_panic.index:
            r = {"time": merged["time"].iloc[idx], "btc_drop": merged["btc_4h_ret"].iloc[idx],
                 "sol_drop": merged["sol_4h_ret"].iloc[idx]}
            for h in [3, 6, 12, 24]:
                if idx + h < len(merged):
                    for sym, col in [("btc", "btc_close"), ("sol", "sol_close"), ("hype", "hype_close")]:
                        r[f"{sym}_{h}h"] = (merged[col].iloc[idx + h] - merged[col].iloc[idx]) / merged[col].iloc[idx] * 100
            panic_results.append(r)

        pdf = pd.DataFrame(panic_results)
        print(f"\nRecovery after BTC panic (n={len(pdf)}):")
        for h in [3, 6, 12, 24]:
            sc, bc, hc = f"sol_{h}h", f"btc_{h}h", f"hype_{h}h"
            if sc in pdf.columns:
                sol_beta = pdf[sc].mean() / max(abs(pdf[bc].mean()), 0.01)
                print(f"  {h}h: BTC={pdf[bc].mean():+.2f}% SOL={pdf[sc].mean():+.2f}% HYPE={pdf[hc].mean():+.2f}% | SOL/BTC beta={sol_beta:.2f}x | SOL up%={(pdf[sc]>0).mean()*100:.0f}%")

        # SOL bounce magnitude vs BTC bounce magnitude
        if "sol_12h" in pdf.columns and "btc_12h" in pdf.columns:
            pdf["sol_excess_12h"] = pdf["sol_12h"] - pdf["btc_12h"]
            print(f"\n  SOL 12h excess over BTC after panic: mean={pdf['sol_excess_12h'].mean():+.2f}%, {(pdf['sol_excess_12h']>0).mean()*100:.0f}% of time SOL outperforms")

        print("\n  Individual panic events:")
        for _, r in pdf.iterrows():
            t = r["time"]
            ts = t.strftime("%m-%d %H:%M") if hasattr(t, "strftime") else str(t)
            s6 = r.get("sol_6h", float("nan"))
            b6 = r.get("btc_6h", float("nan"))
            h6 = r.get("hype_6h", float("nan"))
            print(f"    {ts} BTC4h={r['btc_drop']:+.1f}% SOL4h={r.get('sol_drop',0):+.1f}% -> BTC6h={b6:+.1f}% SOL6h={s6:+.1f}% HYPE6h={h6:+.1f}%")

    # ===== ANALYSIS 5: Pairs Trade =====
    print("\n" + "=" * 70)
    print("ANALYSIS 5: Pairs Trade - Long HYPE / Short SOL")
    print("=" * 70)

    merged["hype_sol_ratio"] = merged["hype_close"] / merged["sol_close"]
    ratio = merged["hype_sol_ratio"]
    ratio_mean = ratio.rolling(50).mean()
    ratio_std = ratio.rolling(50).std()
    merged["ratio_zscore"] = (ratio - ratio_mean) / ratio_std.replace(0, 1e-12)

    current_z = merged["ratio_zscore"].iloc[-1]
    current_ratio = merged["hype_sol_ratio"].iloc[-1]
    print(f"HYPE/SOL ratio: {current_ratio:.6f}")
    print(f"Z-score: {current_z:.2f} (>2 = HYPE expensive vs SOL, <-2 = SOL expensive)")
    print(f"50-bar mean ratio: {ratio_mean.iloc[-1]:.6f}")

    for z_thresh in [2.0, 1.5, 1.0, -1.0, -1.5, -2.0]:
        if z_thresh > 0:
            events = merged[merged["ratio_zscore"] > z_thresh]
            label = f"Z > {z_thresh}"
        else:
            events = merged[merged["ratio_zscore"] < z_thresh]
            label = f"Z < {z_thresh}"

        if len(events) == 0:
            print(f"\n  {label}: 0 events")
            continue

        fwd_ratios = []
        for idx in events.index:
            for h in [6, 12, 24]:
                if idx + h < len(merged):
                    fwd_ratio_chg = (merged["hype_sol_ratio"].iloc[idx + h] - merged["hype_sol_ratio"].iloc[idx]) / merged["hype_sol_ratio"].iloc[idx] * 100
                    hype_fwd = (merged["hype_close"].iloc[idx + h] - merged["hype_close"].iloc[idx]) / merged["hype_close"].iloc[idx] * 100
                    sol_fwd = (merged["sol_close"].iloc[idx + h] - merged["sol_close"].iloc[idx]) / merged["sol_close"].iloc[idx] * 100
                    fwd_ratios.append({"h": h, "ratio_chg": fwd_ratio_chg, "hype": hype_fwd, "sol": sol_fwd})

        frdf = pd.DataFrame(fwd_ratios)
        print(f"\n  {label} ({len(events)} events):")
        for h in [6, 12, 24]:
            sub = frdf[frdf["h"] == h]
            if len(sub) > 0:
                print(f"    {h}h: ratio chg={sub['ratio_chg'].mean():+.2f}% | HYPE={sub['hype'].mean():+.2f}% SOL={sub['sol'].mean():+.2f}%")

    # ===== ANALYSIS 6: Rolling Correlation =====
    print("\n" + "=" * 70)
    print("ANALYSIS 6: Rolling Correlation & Current State")
    print("=" * 70)

    merged["btc_sol_corr"] = merged["btc_ret"].rolling(24).corr(merged["sol_ret"])
    merged["btc_hype_corr"] = merged["btc_ret"].rolling(24).corr(merged["hype_ret"])
    merged["sol_hype_corr"] = merged["sol_ret"].rolling(24).corr(merged["hype_ret"])

    print(f"24h rolling correlations (current / 7d avg):")
    print(f"  BTC-SOL:  {merged['btc_sol_corr'].iloc[-1]:.3f} / {merged['btc_sol_corr'].tail(168).mean():.3f}")
    print(f"  BTC-HYPE: {merged['btc_hype_corr'].iloc[-1]:.3f} / {merged['btc_hype_corr'].tail(168).mean():.3f}")
    print(f"  SOL-HYPE: {merged['sol_hype_corr'].iloc[-1]:.3f} / {merged['sol_hype_corr'].tail(168).mean():.3f}")

    # ===== CURRENT SITUATION SUMMARY =====
    print("\n" + "=" * 70)
    print("CURRENT SITUATION SUMMARY")
    print("=" * 70)

    for sym in ["btc", "sol", "hype"]:
        last6 = merged[f"{sym}_ret"].tail(6)
        cum = last6.sum()
        bars = " ".join([f"{x:+.1f}" for x in last6.values])
        print(f"  {sym.upper()} last 6h: {cum:+.2f}% (bars: {bars})")

    print(f"\n  RSI: BTC={merged['btc_rsi'].iloc[-1]:.1f} SOL={merged['sol_rsi'].iloc[-1]:.1f} HYPE={merged['hype_rsi'].iloc[-1]:.1f}")
    print(f"  HYPE 4h alpha vs BTC: {merged['hype_alpha'].iloc[-1]:+.2f}%")
    print(f"  HYPE/SOL z-score: {current_z:.2f}")

    for sym_name, col in [("BTC", "btc_close"), ("SOL", "sol_close"), ("HYPE", "hype_close")]:
        high_24 = merged[col].tail(24).max()
        current = merged[col].iloc[-1]
        dd = (current - high_24) / high_24 * 100
        print(f"  {sym_name} 24h drawdown from high: {dd:+.2f}% (price={current:.2f}, 24h high={high_24:.2f})")

    # MFE analysis for SOL bounce trade
    print("\n" + "=" * 70)
    print("ANALYSIS 7: SOL Bounce Trade MFE/MAE (If you bought SOL at RSI < 20)")
    print("=" * 70)

    sol_os = merged[merged["sol_rsi"] < 20]
    if len(sol_os) > 0:
        mfe_mae = []
        for idx in sol_os.index:
            entry = merged["sol_close"].iloc[idx]
            # Look 24h forward
            end = min(idx + 24, len(merged))
            if end <= idx:
                continue
            fwd_prices = merged["sol_close"].iloc[idx + 1 : end]
            if len(fwd_prices) == 0:
                continue
            mfe = (fwd_prices.max() - entry) / entry * 100
            mae = (fwd_prices.min() - entry) / entry * 100
            final = (fwd_prices.iloc[-1] - entry) / entry * 100
            mfe_mae.append({"mfe": mfe, "mae": mae, "final": final, "rsi": merged["sol_rsi"].iloc[idx]})

        if mfe_mae:
            mdf = pd.DataFrame(mfe_mae)
            print(f"  SOL RSI < 20 entries (n={len(mdf)}):")
            print(f"    MFE (max favorable): mean={mdf['mfe'].mean():+.2f}%, median={mdf['mfe'].median():+.2f}%")
            print(f"    MAE (max adverse):   mean={mdf['mae'].mean():+.2f}%, median={mdf['mae'].median():+.2f}%")
            print(f"    Final 24h return:    mean={mdf['final'].mean():+.2f}%, up%={(mdf['final']>0).mean()*100:.0f}%")
            print(f"    Best MFE: {mdf['mfe'].max():+.2f}%, Worst MAE: {mdf['mae'].min():+.2f}%")
            print(f"    Suggested SL: {abs(mdf['mae'].quantile(0.75)):.2f}% below entry (75th pctl MAE)")
            print(f"    Suggested TP: {mdf['mfe'].quantile(0.50):.2f}% above entry (50th pctl MFE)")

    # ===== ACTIONABLE TRADE IDEAS =====
    print("\n" + "=" * 70)
    print("ACTIONABLE TRADE IDEAS")
    print("=" * 70)

    btc_price = merged["btc_close"].iloc[-1]
    sol_price = merged["sol_close"].iloc[-1]
    hype_price = merged["hype_close"].iloc[-1]

    print(f"\nCurrent: BTC={btc_price:.0f} SOL={sol_price:.2f} HYPE={hype_price:.4f}")
    print(f"BTC RSI={merged['btc_rsi'].iloc[-1]:.1f} SOL RSI={merged['sol_rsi'].iloc[-1]:.1f} HYPE RSI={merged['hype_rsi'].iloc[-1]:.1f}")


if __name__ == "__main__":
    main()
