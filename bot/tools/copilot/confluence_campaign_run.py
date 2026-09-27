#!/usr/bin/env python
"""
confluence_campaign_run.py -- ONE-SHOT RUNNER for the CONFLUENCE_CAMPAIGN.md
hypothesis space (C1-C44), executed through confluence_harness.py's verified
engine. READ-ONLY against data/. Writes only to the scratchpad JSON dump
passed via --out (default: this dir's confluence_campaign_results.json) and
prints a summary to stdout. No Discord, no live-bot state touched.

Encodes each hypothesis from Part B as one or more HypothesisSpec objects,
using the harness's documented indicator set (INDICATOR_COLUMNS in
confluence_harness.py). Where a prose hypothesis needs an indicator the
harness does not expose (ADX-gated trend, weather.py's live breadth calc,
core/quant_regime.py's panic/consolidation regime, is_falling_knife, raw
funding_rate sign, trades.csv exit mechanics, correlation-cluster pairs
trading), a disclosed, entry-time-safe PROXY is built here from the
harness's existing columns, OR the hypothesis is marked DEFERRED with the
reason given inline -- never silently dropped, never faked.

FDR discipline: run_campaign() already applies BH-FDR once, in-process,
across whatever spec list it's given (with_liquidity_buckets=True adds the
per-bucket companion tests automatically -- this is the harness's built-in,
verified implementation of A6/C37, used as-is per the task's "run the
verified engine" instruction). Lens 3 (1h confluence, C17/C18) needs a
DIFFERENT split_date (the 1h-covered sub-window, per A2's own instruction),
so it is run via direct run_hypothesis() calls and its entries are pooled
into the SAME single BH-FDR family by re-running benjamini_hochberg() once
over the combined pooled train p-values (replicating run_campaign's own
confirm-logic exactly) -- this preserves "one family, corrected once" (A3)
while respecting the sub-window requirement.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import confluence_harness as ch  # noqa: E402

OUT_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "confluence_campaign_results.json")


# ===========================================================================
# Custom, disclosed PROXY columns (breadth/weather/dispersion) -- attached
# in-place to DataStore frames. Entry-time-safe: every column below is
# computed causally (expanding/rolling, reindexed by date, no future data).
# ===========================================================================

def attach_breadth_and_weather(store: ch.DataStore) -> None:
    """breadth_pct = cross-sectional fraction of the LOADED universe with
    ema_trend_up==True that day (proxy for weather.py's breadth20 -- not
    byte-identical, computed over whatever universe was loaded, disclosed).
    btc_above_ema50 = BTC's own ema_trend_up, joined by date (NaN/False
    outside BTC's cache coverage window, 2025-12-18 -> 2026-07-13 -- a
    ~7-month window inside the alts' ~13-month span; disclosed, not hidden).
    washed_out / stormy follow weather.py's stated cutoffs (breadth<20% &
    BTC<50dEMA / breadth>50% & BTC>50dEMA)."""
    frames = store.frames
    wide = pd.DataFrame({s: d.set_index("dt")["ema_trend_up"].astype(float) for s, d in frames.items()}).sort_index()
    breadth = wide.mean(axis=1, skipna=True)
    btc_series = frames["BTC"].set_index("dt")["ema_trend_up"] if "BTC" in frames else None
    for s, d in frames.items():
        d["breadth_pct"] = breadth.reindex(d["dt"]).reset_index(drop=True).values
        if btc_series is not None:
            d["btc_above_ema50"] = btc_series.reindex(d["dt"]).reset_index(drop=True).values
        else:
            d["btc_above_ema50"] = np.nan
        d["washed_out"] = (d["breadth_pct"] < 0.20) & (d["btc_above_ema50"] == False)  # noqa: E712
        d["stormy"] = (d["breadth_pct"] > 0.50) & (d["btc_above_ema50"] == True)  # noqa: E712


def attach_dispersion(store: ch.DataStore) -> None:
    """high_dispersion_day proxy for C27: cross-sectional spread between
    top-quintile and bottom-quintile trailing-5d return (ret5), vs its OWN
    expanding (causal, entry-time-safe) median -- no peeking at the full-
    sample median, so TRAIN's threshold never sees TEST data."""
    frames = store.frames
    wide = pd.DataFrame({s: d.set_index("dt")["ret5"] for s, d in frames.items()}).sort_index()

    def _spread(row: pd.Series) -> float:
        v = row.dropna().values
        if len(v) < 10:
            return np.nan
        v = np.sort(v)
        k = max(1, int(len(v) * 0.2))
        return float(v[-k:].mean() - v[:k].mean())

    disp = wide.apply(_spread, axis=1)
    disp_thresh = disp.expanding(min_periods=60).median()
    high_disp = disp > disp_thresh
    for s, d in frames.items():
        d["high_dispersion_day"] = high_disp.reindex(d["dt"]).reset_index(drop=True).values


# ===========================================================================
# Lens 1 -- multi-signal confluence (C1-C8)
# ===========================================================================

BASE_RULES = {
    "S1": ch.Rule("rsi14", "<=", 35.0),
    "S2": ch.Rule("bb_pctb", "<=", 0.25),
    "S3": ch.Rule("support_dist", "<=", 0.06),
    "S5": ch.Rule("vol_ratio", ">=", 3.0),
    "S6": ch.Rule("breakout", "==", 1.0),
    "S7": ch.Rule("rel_strength_rank", ">=", 0.8),
}


def _cond_c1(df: pd.DataFrame) -> pd.Series:
    return ((df["rsi14"] <= 35.0) | (df["bb_pctb"] <= 0.25)) & (df["ema_trend_up"] == True)  # noqa: E712


def _cond_c8(df: pd.DataFrame) -> pd.Series:
    return ((df["rsi14"] >= 65.0) | (df["bb_pctb"] >= 0.75)) & (df["ema_trend_up"] == False)  # noqa: E712


def build_lens1() -> list:
    specs = []
    specs.append(ch.HypothesisSpec(name="C1_dip_OR_uptrend_AND", side="long", condition_fn=_cond_c1))
    specs.append(ch.HypothesisSpec(name="C2_triple_dip_uptrend", side="long",
                                    rules=[BASE_RULES["S1"], BASE_RULES["S2"], ch.Rule("ema_trend_up", "==", 1.0)]))
    specs.append(ch.HypothesisSpec(name="C3_breakout_volsurge", side="long", rules=[BASE_RULES["S6"], BASE_RULES["S5"]]))
    specs.append(ch.HypothesisSpec(name="C4_relstrength_oversold", side="long", rules=[BASE_RULES["S7"], BASE_RULES["S1"]]))
    specs.append(ch.HypothesisSpec(name="C5_relstrength_breakout", side="long", rules=[BASE_RULES["S7"], BASE_RULES["S6"]]))
    specs.append(ch.HypothesisSpec(name="C6_support_volsurge", side="long", rules=[BASE_RULES["S3"], BASE_RULES["S5"]]))
    specs.append(ch.HypothesisSpec(name="C8_short_mirror_dip_downtrend", side="short", condition_fn=_cond_c8))

    covered_pairs = {frozenset(p) for p in [("S5", "S6"), ("S1", "S7"), ("S6", "S7"), ("S3", "S5")]}
    keys = list(BASE_RULES.keys())
    for combo in itertools.combinations(keys, 2):
        if frozenset(combo) in covered_pairs:
            continue
        specs.append(ch.HypothesisSpec(name=f"C7_pair_{'_'.join(combo)}", side="long",
                                        rules=[BASE_RULES[c] for c in combo]))
    for combo in itertools.combinations(keys, 3):
        specs.append(ch.HypothesisSpec(name=f"C7_triple_{'_'.join(combo)}", side="long",
                                        rules=[BASE_RULES[c] for c in combo]))
    return specs


# ===========================================================================
# Lens 2 -- regime/vol conditioning (C9-C16; C15 deferred -- see report)
# ===========================================================================

def _mk(name, side, fn):
    return ch.HypothesisSpec(name=name, side=side, condition_fn=fn)


def build_lens2() -> list:
    specs = []
    specs.append(_mk("C9_oversold_washedout", "long",
                      lambda d: (d["rsi14"] <= 35.0) & (d["washed_out"] == True)))  # noqa: E712
    specs.append(_mk("C10_oversold_stormy", "long",
                      lambda d: (d["rsi14"] <= 35.0) & (d["stormy"] == True)))  # noqa: E712
    specs.append(_mk("C11_lowerbb_btcabove50", "long",
                      lambda d: (d["bb_pctb"] <= 0.25) & (d["btc_above_ema50"] == True)))  # noqa: E712
    specs.append(_mk("C11_lowerbb_btcbelow50", "long",
                      lambda d: (d["bb_pctb"] <= 0.25) & (d["btc_above_ema50"] == False)))  # noqa: E712
    specs.append(_mk("C12_breakout_highvol", "long",
                      lambda d: (d["breakout"] == True) & (d["high_vol_regime"] == True)))  # noqa: E712
    specs.append(_mk("C13_volsurge_out_of_consolidation", "long",
                      lambda d: (d["vol_ratio"] >= 3.0) & (d["high_vol_regime"].shift(1) == False)))  # noqa: E712
    specs.append(_mk("C14_relstrength_breadth_gt50", "long",
                      lambda d: (d["rel_strength_rank"] >= 0.8) & (d["breadth_pct"] > 0.50)))
    specs.append(_mk("C14_relstrength_breadth_lt50", "long",
                      lambda d: (d["rel_strength_rank"] >= 0.8) & (d["breadth_pct"] <= 0.50)))
    specs.append(_mk("C16_support_uptrend", "long",
                      lambda d: (d["support_dist"] <= 0.06) & (d["ema_trend_up"] == True)))  # noqa: E712
    return specs


# ===========================================================================
# Lens 3 -- multi-timeframe (C17, C18). Run separately (own split_date).
# C19/C20 DEFERRED -- see report.
# ===========================================================================

def build_lens3_masks(store1d: ch.DataStore, store1h: ch.DataStore) -> dict:
    """Returns {spec_name: {symbol: bool ndarray aligned to store1d frame}}."""
    out = {"C17_daily_oversold_1h_rsi_cross": {}, "C18_lowerbb_1h_ema_bull_flip": {}}
    for sym in store1d.symbols():
        d1 = store1d.get(sym)
        d1h = store1h.get(sym)
        n = len(d1)
        m17 = np.zeros(n, dtype=bool)
        m18 = np.zeros(n, dtype=bool)
        if d1h is not None and len(d1h) > 30:
            dt1h = d1h["dt"].values
            rsi1h = d1h["rsi14"].values
            ema_up_1h = (d1h["ema20"] > d1h["ema50"]).values
            for i in range(n):
                dt = d1["dt"].iloc[i]
                if pd.isna(d1["rsi14"].iloc[i]) or pd.isna(d1["bb_pctb"].iloc[i]):
                    continue
                w_start = np.datetime64(dt - pd.Timedelta(hours=12))
                w_end = np.datetime64(dt)
                idx = np.where((dt1h >= w_start) & (dt1h < w_end))[0]
                if len(idx) < 2:
                    continue
                r = rsi1h[idx]
                crossed = False
                for k in range(1, len(r)):
                    if not np.isnan(r[k - 1]) and not np.isnan(r[k]) and r[k - 1] < 30.0 and r[k] >= 30.0:
                        crossed = True
                        break
                if crossed and d1["rsi14"].iloc[i] <= 35.0:
                    m17[i] = True
                e = ema_up_1h[idx]
                flip = False
                if len(e) >= 2:
                    was_bear_ever = (~e[:-1]).any()
                    if was_bear_ever and e[-1]:
                        flip = True
                if flip and d1["bb_pctb"].iloc[i] <= 0.25:
                    m18[i] = True
        out["C17_daily_oversold_1h_rsi_cross"][sym] = m17
        out["C18_lowerbb_1h_ema_bull_flip"][sym] = m18
    return out


# ===========================================================================
# Lens 4 -- derivatives-intertwined (C21, C22, C23a/b). C24/C25 DEFERRED.
# ===========================================================================

def build_lens4() -> list:
    specs = []
    specs.append(ch.HypothesisSpec(name="C21_oversold_funding_extreme_negative", side="long",
                                    rules=[BASE_RULES["S1"], ch.Rule("funding_z", "<=", -2.5)]))
    specs.append(ch.HypothesisSpec(name="C22_oversold_liq_cascade", side="long",
                                    rules=[BASE_RULES["S1"], ch.Rule("liq_cascade_flag", "==", 1.0)]))
    specs.append(ch.HypothesisSpec(name="C23_oversold_OI_unwind", side="long",
                                    rules=[BASE_RULES["S1"], ch.Rule("oi_roc", "<=", -0.10)]))
    specs.append(ch.HypothesisSpec(name="C23_oversold_OI_buildup", side="long",
                                    rules=[BASE_RULES["S1"], ch.Rule("oi_roc", ">=", 0.10)]))
    return specs


# ===========================================================================
# Lens 5 -- cross-sectional (C26, C27proxy, C29, C30). C28 DEFERRED.
# ===========================================================================

def build_lens5() -> list:
    specs = []
    specs.append(_mk("C26_topquintile_momentum_dip", "long",
                      lambda d: (d["rel_strength_rank"] >= 0.8) & ((d["rsi14"] <= 35.0) | (d["bb_pctb"] <= 0.25))))
    specs.append(_mk("C27proxy_topquintile_momentum_highdispersion", "long",
                      lambda d: (d["rel_strength_rank"] >= 0.8) & (d["high_dispersion_day"] == True)))  # noqa: E712
    specs.append(ch.HypothesisSpec(name="C29_marketwide_breadth_lt10", side="long",
                                    rules=[ch.Rule("breadth_pct", "<", 0.10)]))
    specs.append(_mk("C30_laggard_rotation_breadth_gt70", "long",
                      lambda d: (d["rel_strength_rank"] <= 0.2) & (d["breadth_pct"] > 0.70)))
    return specs


# ===========================================================================
# Lens 7 -- dedicated liquidity hypotheses (C38/39/40 via base-signal bucket
# breakdown, C41 alt-only-universe re-slice, C42a/b funding-extreme mirror).
# C44 DEFERRED (needs core/quant_regime.py is_falling_knife -- out of this
# standalone harness's scope, same reason as C15).
# ===========================================================================

def build_lens7_dedicated() -> list:
    specs = []
    specs.append(ch.HypothesisSpec(name="BASE_S1_oversold_for_C38", side="long", rules=[BASE_RULES["S1"]]))
    specs.append(ch.HypothesisSpec(name="BASE_S2_lowerbb_for_C39", side="long", rules=[BASE_RULES["S2"]]))
    specs.append(ch.HypothesisSpec(name="BASE_S6_breakout_for_C40", side="long", rules=[BASE_RULES["S6"]]))
    specs.append(ch.HypothesisSpec(name="C42a_funding_crowded_long_short", side="short",
                                    rules=[ch.Rule("funding_z", ">=", 2.5)]))
    specs.append(ch.HypothesisSpec(name="C42b_funding_crowded_short_long", side="long",
                                    rules=[ch.Rule("funding_z", "<=", -2.5)]))
    return specs


def build_c41(store_altsonly: ch.DataStore) -> ch.HypothesisSpec:
    return ch.HypothesisSpec(name="C41_XSmomentum_altsonly_universe", side="long",
                              universe="all", rules=[BASE_RULES["S7"]], horizons=(3,))


# ===========================================================================
# Manual entry construction (mirrors run_campaign's internal _mk_entry /
# confirm logic) -- used for Lens-3 (different split_date) and C41
# (different DataStore/universe) so they join the SAME single FDR family.
# ===========================================================================

def entries_from_result(spec_name: str, res: ch.HypothesisResult, horizon: int,
                         with_liquidity: bool = True) -> list:
    out = []

    def _mk_entry(test_id, bucket, train_hs, test_hs, dominance):
        return ch.CampaignEntry(
            test_id=test_id, spec_name=spec_name, bucket=bucket, horizon=horizon,
            train_n=train_hs.n if train_hs else 0, train_p=train_hs.p_value if train_hs else None,
            train_mean_net=train_hs.mean_net if train_hs else None,
            train_mean_gross=train_hs.mean_gross if train_hs else None,
            test_n=test_hs.n if test_hs else 0, test_p=test_hs.p_value if test_hs else None,
            test_mean_net=test_hs.mean_net if test_hs else None,
            test_mean_gross=test_hs.mean_gross if test_hs else None, dominance_flag=dominance,
        )

    out.append(_mk_entry(spec_name, None, res.train.per_horizon.get(horizon), res.test.per_horizon.get(horizon),
                          res.train.dominance_flag or res.test.dominance_flag))
    if with_liquidity:
        for b in ("thin", "mid", "liquid"):
            th = res.train.by_liquidity.get(b, {}).get(horizon)
            te = res.test.by_liquidity.get(b, {}).get(horizon)
            out.append(_mk_entry(f"{spec_name}::{b}", b, th, te, False))
    return out


def finalize_family(entries: list, alpha: float = ch.FDR_ALPHA_DEFAULT) -> dict:
    train_p = [e.train_p for e in entries]
    reject = ch.benjamini_hochberg(train_p, alpha=alpha)
    n_tested = sum(1 for p in train_p if p is not None)
    for e, r in zip(entries, reject):
        e.fdr_survivor = r
        same_sign = (e.train_mean_net is not None and e.test_mean_net is not None and
                     np.sign(e.train_mean_net) == np.sign(e.test_mean_net) and e.train_mean_net != 0)
        e.confirmed = bool(r and e.test_p is not None and e.test_p < 0.05 and
                            e.test_n >= ch.MIN_N and same_sign and not e.dominance_flag)
    n_surv = sum(1 for e in entries if e.fdr_survivor)
    n_conf = sum(1 for e in entries if e.confirmed)
    return {"alpha": alpha, "n_tested": n_tested, "expected_false_positives": n_tested * alpha,
            "n_surviving_fdr": n_surv, "n_confirmed": n_conf}


def entry_to_dict(e: ch.CampaignEntry) -> dict:
    return {"test_id": e.test_id, "spec_name": e.spec_name, "bucket": e.bucket, "horizon": e.horizon,
            "train_n": e.train_n, "train_p": e.train_p, "train_mean_net": e.train_mean_net,
            "train_mean_gross": e.train_mean_gross, "test_n": e.test_n, "test_p": e.test_p,
            "test_mean_net": e.test_mean_net, "test_mean_gross": e.test_mean_gross,
            "fdr_survivor": e.fdr_survivor, "confirmed": e.confirmed, "dominance_flag": e.dominance_flag}


def result_diag(spec_name: str, res: ch.HypothesisResult, horizon: int) -> dict:
    mono_full = ch.liquidity_monotonicity(res.full, horizon)
    pre = res.pre_era.per_horizon.get(horizon)
    post = res.post_era.per_horizon.get(horizon)
    return {
        "spec_name": spec_name, "side": res.side, "n_universe_symbols": res.n_universe_symbols,
        "n_raw_triggers": res.n_events_total_raw, "collapse_ratio": res.diagnostics.get("collapse_ratio"),
        "full_n": res.full.per_horizon.get(horizon).n if res.full.per_horizon.get(horizon) else 0,
        "full_dominance_frac": res.full.dominance_frac,
        "pre_era_n": pre.n if pre else 0, "pre_era_mean_net": pre.mean_net if pre else None,
        "post_era_n": post.n if post else 0, "post_era_mean_net": post.mean_net if post else None,
        "liquidity_monotonicity_full": mono_full,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=str, default=OUT_DEFAULT)
    ap.add_argument("--perm-iters", type=int, default=1000)
    ap.add_argument("--batch", type=int, default=10)
    args = ap.parse_args()

    t0 = time.time()
    print("Loading main DataStore (universe=all, timeframe=1d)...")
    store = ch.DataStore(universe="all", timeframe="1d", verbose=False)
    print(f"  loaded {len(store.frames)} symbols, skipped {store.skipped}")
    attach_breadth_and_weather(store)
    attach_dispersion(store)

    specs = []
    specs += build_lens1()
    specs += build_lens2()
    specs += build_lens4()
    specs += build_lens5()
    specs += build_lens7_dedicated()
    # Pre-committed primary horizon = 3d (matches PREREGISTRATION.md's own
    # fwd_3d_pct primary-horizon convention and the campaign's dominant
    # "short-horizon 1-3d bounce" framing) -- fixed BEFORE any result is
    # read, uniformly, never re-tuned per-hypothesis after peeking (A2).
    for s in specs:
        s.horizons = (3,)
    print(f"Main-family spec count (pre-liquidity-expansion): {len(specs)}")

    print("Running main campaign via run_campaign()...")
    campaign = ch.run_campaign(specs, store, batch_size=args.batch, with_liquidity_buckets=True,
                                perm_iters=args.perm_iters, verbose=True)
    print(f"  main campaign done in {time.time()-t0:.1f}s: n_tested={campaign.n_tested} "
          f"surviving_fdr={campaign.n_surviving_fdr} confirmed={campaign.n_confirmed}")

    all_entries = list(campaign.entries)
    all_results = dict(campaign.results_by_spec)

    # --- Lens 3: separate split_date (1h-covered sub-window only) ---
    print("Loading 1h DataStore for Lens 3 (C17/C18)...")
    store1h = ch.DataStore(universe="all", timeframe="1h", verbose=False)
    masks = build_lens3_masks(store, store1h)
    lens3_split_start = max(f["dt"].iloc[0] for f in store1h.frames.values() if len(f) > 0)
    lens3_split_end = store.global_end
    lens3_split_date = lens3_split_start + (lens3_split_end - lens3_split_start) * ch.TRAIN_FRACTION_DEFAULT
    print(f"  Lens-3 1h-covered window: {lens3_split_start} -> {lens3_split_end}, "
          f"split_date={lens3_split_date}")
    for name, per_sym_mask in masks.items():
        spec = ch.HypothesisSpec(name=name, side="long", precomputed_mask=per_sym_mask, horizons=(3,))
        res = ch.run_hypothesis(spec, store, split_date=lens3_split_date, perm_iters=args.perm_iters,
                                 compute_liquidity=True)
        all_results[name] = res
        all_entries += entries_from_result(name, res, spec.primary_horizon())
    del store1h, masks
    import gc
    gc.collect()

    # --- C41: alt-only universe (excludes majors), internal re-slice ---
    print("Loading alts-only DataStore for C41...")
    alts = ch.discover_longtail_symbols()
    store_alts = ch.DataStore(universe=alts, timeframe="1d", verbose=False)
    c41_spec = build_c41(store_alts)
    c41_res = ch.run_hypothesis(c41_spec, store_alts, perm_iters=args.perm_iters, compute_liquidity=True)
    all_results[c41_spec.name] = c41_res
    all_entries += entries_from_result(c41_spec.name, c41_res, c41_spec.primary_horizon())
    del store_alts
    gc.collect()

    # --- Recompute BH-FDR ONCE across the pooled, combined family ---
    family = finalize_family(all_entries)
    print(f"\nCOMBINED FAMILY (main + Lens3 + C41): n_tested={family['n_tested']} "
          f"expected_false_positives={family['expected_false_positives']:.2f} "
          f"n_surviving_fdr={family['n_surviving_fdr']} n_confirmed={family['n_confirmed']}")

    confirmed = [e for e in all_entries if e.confirmed]
    print(f"\nCONFIRMED entries ({len(confirmed)}):")
    for e in confirmed:
        print(f"  {e.test_id}: train(n={e.train_n},p={e.train_p:.4f},net={e.train_mean_net:.5f}) "
              f"test(n={e.test_n},p={e.test_p:.4f},net={e.test_mean_net:.5f})")

    # --- Serialize everything for report-writing ---
    out = {
        "family_summary": family,
        "entries": [entry_to_dict(e) for e in all_entries],
        "per_spec_diagnostics": {name: result_diag(name, res, 3) for name, res in all_results.items()},
        "elapsed_sec": time.time() - t0,
        "deferred": {
            "C15": "needs core/quant_regime.py::is_falling_knife (already-validated live gate) -- standalone price-only harness deliberately does not import core/ or trades.csv; faithful proxy would test a DIFFERENT rule, not the validated gate. DEFERRED, not faked.",
            "C19": "1h HH/HL structure sustained >=4h AFTER the breakout bar makes the true decision timestamp 4h later than the daily breakout close; naive same-bar entry would violate A1 entry-time-safety. DEFERRED pending a re-anchored (shifted-entry) implementation.",
            "C20": "[POWER-LIMITED] per campaign's own text -- 3-way conjunction across 2 timeframes on a 7mo 1h window; campaign explicitly says do not spend budget unless C17-C19 show something. DEFERRED by design.",
            "C24": "funding-rate SIGN FLIP needs the raw signed funding_rate; harness only exposes funding_z (a z-score), not the raw rate, so a sign-flip event cannot be reconstructed without re-deriving from funding_oi_history.jsonl outside the harness's documented indicator set. DEFERRED.",
            "C25": "explicitly cross-referenced to liq_hypothesis_harness.py H3 in the campaign doc, not independently scored.",
            "C28": "correlation-cluster pairs trading needs a 25x25 rolling correlation matrix + cluster-boundary definition (Tier C, campaign's own highest-implementation-risk flag). DEFERRED given time budget; not built to avoid a rushed, unaudited cluster definition.",
            "C31": "canonical home is C23 (cross-referenced only per campaign doc).",
            "C32-C36 (Lens 6 exit/risk-mechanics)": "require data/trades.csv / paper-trade history (per campaign's own Batch 6 spec: 'different underlying data... keep separate from Batches 1-5'). confluence_harness.py is explicitly standalone/price-only (data/longtail, data/cache, funding_oi_history.jsonl, liq_events.jsonl only) and does not import trades.csv. OUT OF SCOPE for this harness/run; needs a separate trades-ledger-based tool.",
            "C43": "build-time ALTERNATIVE to C37; C37's built-in per-bucket companion protocol (with_liquidity_buckets=True) was used instead, per the campaign doc's own instruction not to run both.",
            "C44": "same reason as C15 -- needs the real is_falling_knife/forward-drawdown-risk machinery from core/, out of this standalone harness's scope. DEFERRED.",
        },
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nWrote {args.out} ({os.path.getsize(args.out)/1024:.0f} KB)")
    print(f"Total elapsed: {time.time()-t0:.1f}s")
    return 0


def _primary_h(res: ch.HypothesisResult) -> int:
    for h in res.full.per_horizon.keys():
        return h
    return 3


if __name__ == "__main__":
    sys.exit(main())
