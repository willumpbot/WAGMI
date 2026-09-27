#!/usr/bin/env python
"""
meanrev_rule_test.py -- TRADEABLE-RULE TEST for the 3-day mean-reversion lead
from `MEANREV_STRUCTURE_RESULTS.md`. READ-ONLY, standalone, no Discord, no
live/paper-bot state touched. Uses the VERIFIED `confluence_harness.py`
engine (its OOS train/test split, era split, FDR, per-liquidity-bucket cost,
dedup, permutation-p-value machinery) -- this file adds no new statistical
method, only the RULE SPECS and the refute-yourself reporting on top.

WHY THIS EXISTS: the structure study found unconditional 3d-return
autocorrelation is negative in both eras for 72% of alts, and that the
*amplitude* of that autocorrelation clears realistic cost. That is NOT the
same claim as "a trading rule that buys after an N-day drop and holds N days
is net-profitable OOS" -- autocorrelation is a population-level statistical
property; a rule has to survive an actual OOS train/test split, real
liquidity-keyed cost on ITS OWN trigger bars, FDR across the grid actually
swept, and the specific refutations below. Deep-oversold (BB+RSI) triggers
already died OOS in the CONFLUENCE campaign (CONFLUENCE_RESULTS.md: 0/133
confirmed) -- this is the same discipline applied to the one lead that
looked different (unconditional trailing-return drop, not an
indicator-threshold trigger).

THE RULE (exactly what would be traded): for coin X on day t, if the
trailing N-day return c[t]/c[t-N]-1 is <= a drop threshold, BUY at t's close,
HOLD EXACTLY N DAYS, SELL at t+N's close. Unlevered 1x spot. Two threshold
families, swept per N:
  - FIXED:      trailing N-day return <= {-5%, -10%, -15%}
  - PERCENTILE: trailing N-day return <= that COIN'S OWN trailing (expanding,
    entry-time-safe: uses only bars strictly BEFORE t, via .shift(1)) 10th
    percentile of its trailing-N-day-return distribution. This adapts the
    threshold to each coin's own volatility instead of one flat cut for a
    calm alt and a wild one alike.
N in {2, 3, 5} (the horizon the structure study flagged as the one with
genuine era-stable structure, plus its immediate neighbors for robustness).

Every (N, threshold) cell is ALSO broken into pooled + thin/mid/liquid
liquidity buckets by confluence_harness's own built-in bucketing
(`with_liquidity_buckets=True`) -- each bucket-conditioned test counts as its
own FDR-family member, never a free extra look. Trades are deduplicated to
NON-OVERLAPPING episodes: `dedup_gap_days=N` per spec, matching the "enter,
hold N days, exit, THEN can enter again" discipline of the actual rule (a
coin that stays under threshold for several consecutive days would otherwise
manufacture many pseudo-independent, heavily-overlapping "trades" out of one
underlying drawdown).

REFUTE-YOURSELF CHECKS on any FDR-confirmed, economically-positive candidate:
  (a) pre-Feb-2026-only?      -- era_split (built into the harness, cutoff
                                  2026-02-01, same as the structure study)
  (b) single-coin dominance?  -- dominance_flag (>=50% of a split's events
                                  from one symbol), built into the harness
  (c) net vs gross            -- both reported; net (cost-adjusted) is what
                                  gates the p-value/FDR/confirmation, per the
                                  harness's own convention
  (d) crash-window dependence -- rerun with 2026-01-26..2026-02-15 (+/-10
                                  calendar days around the -14% BTC day
                                  2026-02-05 flagged in corr_stress_test.py/
                                  beta_stress_test.py) excluded from triggers;
                                  does the effect survive?
  (e) crowding sanity         -- pre-era vs post-era magnitude comparison
                                  (is the edge shrinking over time?)
  (f) pseudoreplication       -- dedup_gap_days=N enforces non-overlapping
                                  episodes; collapse_ratio (raw triggers /
                                  deduped episodes) reported as a diagnostic

CLI:
    python tools/copilot/meanrev_rule_test.py                # full grid, default iters
    python tools/copilot/meanrev_rule_test.py --smoke         # fast, low perm_iters, sanity only
    python tools/copilot/meanrev_rule_test.py --alpha 0.10    # looser FDR (still disclosed)
    python tools/copilot/meanrev_rule_test.py --out FILE.json # dump full machine-readable results
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import confluence_harness as ch  # noqa: E402

OUT_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "meanrev_rule_test_output.json")

N_GRID = [2, 3, 5]
FIXED_THRESHOLDS = [-0.05, -0.10, -0.15]
PCT_THRESHOLDS = [0.10]          # bottom decile of the coin's OWN trailing-return distribution
PCT_MIN_PERIODS = 100            # min prior obs before a percentile threshold is trusted (else NaN -> no trigger)

# -14% BTC day flagged in corr_stress_test.py / beta_stress_test.py as the
# single worst day in this corpus -- +/-10 calendar days around it, same
# window convention those two scripts already used for their own
# "does it survive excluding the crash window" checks.
CRASH_WINDOW_START = "2026-01-26"
CRASH_WINDOW_END = "2026-02-15"


# ===========================================================================
# Condition builders (entry-time-safe: pct_change(N) at bar t uses c[t] and
# c[t-N] only; the percentile threshold at t uses ret_N[0..t-1] only, via
# .shift(1) AFTER the expanding quantile -- t's own trailing return never
# contributes to its own trigger threshold).
# ===========================================================================

def make_fixed_drop_condition(n_days: int, thr: float) -> Callable[[pd.DataFrame], pd.Series]:
    def _cond(df: pd.DataFrame) -> pd.Series:
        ret = df["c"].pct_change(n_days)
        return (ret <= thr).fillna(False)
    return _cond


def make_pctile_drop_condition(n_days: int, q: float) -> Callable[[pd.DataFrame], pd.Series]:
    def _cond(df: pd.DataFrame) -> pd.Series:
        ret = df["c"].pct_change(n_days)
        thresh = ret.expanding(min_periods=PCT_MIN_PERIODS).quantile(q).shift(1)
        return (ret <= thresh).fillna(False)
    return _cond


def wrap_exclude_window(base_cond: Callable[[pd.DataFrame], pd.Series], start: str, end: str
                         ) -> Callable[[pd.DataFrame], pd.Series]:
    start_ts, end_ts = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")

    def _cond(df: pd.DataFrame) -> pd.Series:
        m = base_cond(df)
        excl = (df["dt"] >= start_ts) & (df["dt"] <= end_ts)
        return m & (~excl)
    return _cond


def attach_missing_fwd_raw(store: ch.DataStore, n_days_needed: List[int]) -> None:
    """confluence_harness.compute_price_indicators() only precomputes
    fwd_raw_{1,3,5,10} (its own hardcoded list). N=2 (in our grid) has no
    fwd_raw_2 column -- without this, event/baseline extraction silently
    returns n=0 for every N=2 spec (confirmed by direct inspection: the mask
    itself fires ~76/399 bars on AAVE alone, but `col not in df.columns`
    short-circuits to empty). Rather than edit the verified engine file,
    attach any missing fwd_raw_N columns here, in place, using the IDENTICAL
    formula confluence_harness.py uses (`c.shift(-bars) / c - 1`, same
    entry-time-safe convention: forward from bar t's close to bar t+N's
    close) -- same pattern confluence_campaign_run.py uses for its own
    breadth/dispersion proxy columns."""
    for n_days in n_days_needed:
        col = f"fwd_raw_{n_days}"
        for df in store.frames.values():
            if col not in df.columns:
                bars = n_days * ch.BARS_PER_DAY[store.timeframe]
                df[col] = df["c"].shift(-bars) / df["c"] - 1.0


def build_specs() -> List[ch.HypothesisSpec]:
    specs = []
    for n_days in N_GRID:
        for thr in FIXED_THRESHOLDS:
            name = f"drop{n_days}d_fixed{int(round(abs(thr) * 100))}pct"
            specs.append(ch.HypothesisSpec(
                name=name, side="long", timeframe="1d", universe="all",
                condition_fn=make_fixed_drop_condition(n_days, thr),
                horizons=(n_days,), dedup_gap_days=float(n_days),
            ))
        for q in PCT_THRESHOLDS:
            name = f"drop{n_days}d_pctile{int(round(q * 100))}"
            specs.append(ch.HypothesisSpec(
                name=name, side="long", timeframe="1d", universe="all",
                condition_fn=make_pctile_drop_condition(n_days, q),
                horizons=(n_days,), dedup_gap_days=float(n_days),
            ))
    return specs


# ===========================================================================
# Reporting
# ===========================================================================

def _fmt_pct(x: Optional[float]) -> str:
    return f"{x * 100:+.2f}%" if x is not None else "n/a"


def _fmt_p(x: Optional[float]) -> str:
    return f"{x:.4f}" if x is not None else "n/a"


def print_campaign_table(campaign: ch.CampaignResult) -> None:
    print(f"\n{'=' * 100}")
    print("FDR-FAMILY TABLE (pooled entries only -- bucket entries in the JSON dump / bucket section below)")
    print(f"{'=' * 100}")
    header = (f"{'test_id':<28s} {'h':>2s} {'train_n':>7s} {'train_p':>8s} {'train_net':>10s} "
              f"{'test_n':>7s} {'test_p':>8s} {'test_net':>10s} {'FDR':>5s} {'CONFIRM':>8s} {'DOM':>4s}")
    print(header)
    print("-" * len(header))
    for e in campaign.entries:
        if e.bucket is not None:
            continue
        print(f"{e.test_id:<28s} {e.horizon:>2d} {e.train_n:>7d} {_fmt_p(e.train_p):>8s} "
              f"{_fmt_pct(e.train_mean_net):>10s} {e.test_n:>7d} {_fmt_p(e.test_p):>8s} "
              f"{_fmt_pct(e.test_mean_net):>10s} {'Y' if e.fdr_survivor else '.':>5s} "
              f"{'YES' if e.confirmed else '.':>8s} {'!' if e.dominance_flag else '.':>4s}")


def print_bucket_table(campaign: ch.CampaignResult) -> None:
    print(f"\n{'=' * 100}")
    print("FDR-FAMILY TABLE -- LIQUIDITY-BUCKET ENTRIES (each counted in the SAME FDR family, own comparison)")
    print(f"{'=' * 100}")
    header = (f"{'test_id':<36s} {'h':>2s} {'train_n':>7s} {'train_p':>8s} {'train_net':>10s} "
              f"{'test_n':>7s} {'test_p':>8s} {'test_net':>10s} {'FDR':>5s} {'CONFIRM':>8s}")
    print(header)
    print("-" * len(header))
    for e in campaign.entries:
        if e.bucket is None:
            continue
        print(f"{e.test_id:<36s} {e.horizon:>2d} {e.train_n:>7d} {_fmt_p(e.train_p):>8s} "
              f"{_fmt_pct(e.train_mean_net):>10s} {e.test_n:>7d} {_fmt_p(e.test_p):>8s} "
              f"{_fmt_pct(e.test_mean_net):>10s} {'Y' if e.fdr_survivor else '.':>5s} "
              f"{'YES' if e.confirmed else '.':>8s}")


def era_and_gross_detail(spec_name: str, campaign: ch.CampaignResult) -> Dict[str, Any]:
    res = campaign.results_by_spec[spec_name]
    h = None
    for e in campaign.entries:
        if e.spec_name == spec_name and e.bucket is None:
            h = e.horizon
            break
    pre_hs = res.pre_era.per_horizon.get(h)
    post_hs = res.post_era.per_horizon.get(h)
    full_hs = res.full.per_horizon.get(h)
    return {
        "horizon": h,
        "n_raw_triggers": res.n_events_total_raw,
        "n_full_episodes": res.full.n_events,
        "collapse_ratio": res.diagnostics.get("collapse_ratio"),
        "pre_era": None if pre_hs is None else {
            "n": pre_hs.n, "mean_net": pre_hs.mean_net, "mean_gross": pre_hs.mean_gross,
            "p": pre_hs.p_value, "dominance_flag": res.pre_era.dominance_flag,
        },
        "post_era": None if post_hs is None else {
            "n": post_hs.n, "mean_net": post_hs.mean_net, "mean_gross": post_hs.mean_gross,
            "p": post_hs.p_value, "dominance_flag": res.post_era.dominance_flag,
        },
        "full_gross": None if full_hs is None else full_hs.mean_gross,
        "full_net": None if full_hs is None else full_hs.mean_net,
    }


def economically_positive_confirmed(campaign: ch.CampaignResult) -> List[ch.CampaignEntry]:
    """Stricter than the harness's own `confirmed` flag: `confirmed` only
    requires TRAIN/TEST to agree in SIGN (a confirmed persistent LOSS would
    pass it too). For "is this a genuine buy-the-dip edge" we additionally
    require both folds' NET mean return to be POSITIVE."""
    out = []
    for e in campaign.entries:
        if e.confirmed and e.train_mean_net is not None and e.test_mean_net is not None:
            if e.train_mean_net > 0 and e.test_mean_net > 0:
                out.append(e)
    return out


def run_crash_window_check(n_days: int, base_cond: Callable[[pd.DataFrame], pd.Series],
                            store: ch.DataStore, name: str) -> ch.HypothesisResult:
    excl_cond = wrap_exclude_window(base_cond, CRASH_WINDOW_START, CRASH_WINDOW_END)
    spec = ch.HypothesisSpec(name=f"{name}__exclcrash", side="long", timeframe="1d", universe="all",
                              condition_fn=excl_cond, horizons=(n_days,), dedup_gap_days=float(n_days))
    return ch.run_hypothesis(spec, store, compute_liquidity=False)


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--alpha", type=float, default=0.05, help="BH-FDR alpha (default 0.05)")
    ap.add_argument("--perm-iters", type=int, default=5000,
                     help="permutation-test iterations (default 5000 -- resolves finer than this "
                          "family's strictest BH critical value; see confluence_harness's own warning)")
    ap.add_argument("--smoke", action="store_true", help="fast run, perm_iters=300, for sanity only")
    ap.add_argument("--out", default=OUT_DEFAULT, help="JSON dump path (default: this dir)")
    args = ap.parse_args()

    perm_iters = 300 if args.smoke else args.perm_iters

    print("Loading DataStore (universe='all', timeframe='1d') ...")
    store = ch.DataStore(universe="all", timeframe="1d")
    print(f"  loaded {len(store.frames)} symbols, {store.global_start.date()} -> {store.global_end.date()}")
    print(f"  skipped (insufficient history): {store.skipped}")
    missing_fwd = [n for n in N_GRID if n not in (1, 3, 5, 10)]
    if missing_fwd:
        print(f"  attaching missing fwd_raw_N columns for N={missing_fwd} "
              f"(confluence_harness only precomputes fwd_raw_{{1,3,5,10}})")
        attach_missing_fwd_raw(store, missing_fwd)

    specs = build_specs()
    print(f"\nGrid: N in {N_GRID}, fixed thresholds {FIXED_THRESHOLDS}, "
          f"percentile thresholds (bottom decile) {PCT_THRESHOLDS} -> {len(specs)} base hypotheses "
          f"x 4 (pooled+thin+mid+liquid) = up to {len(specs) * 4} FDR-family entries.")
    print(f"alpha={args.alpha}, perm_iters={perm_iters}, dedup_gap_days=N per spec (non-overlapping episodes)")

    campaign = ch.run_campaign(specs, store, alpha=args.alpha, with_liquidity_buckets=True,
                                perm_iters=perm_iters, batch_size=6, verbose=True)

    print(f"\n{'=' * 100}")
    print("HEADLINE")
    print(f"{'=' * 100}")
    print(f"FDR family size (n_tested, computable p-values): {campaign.n_tested}")
    print(f"Expected false positives at raw p<{args.alpha}: {campaign.expected_false_positives:.2f}")
    print(f"Train-fold BH-FDR survivors: {campaign.n_surviving_fdr}")
    print(f"CONFIRMED (train-FDR + test p<0.05 + same sign + test n>=20 + no dominance): {campaign.n_confirmed}")

    print_campaign_table(campaign)
    print_bucket_table(campaign)

    econ_positive = economically_positive_confirmed(campaign)
    print(f"\n{'=' * 100}")
    print(f"ECONOMICALLY-POSITIVE CONFIRMED CANDIDATES (confirmed AND train_net>0 AND test_net>0): "
          f"{len(econ_positive)}")
    print(f"{'=' * 100}")
    for e in econ_positive:
        print(f"  {e.test_id}: train n={e.train_n} net={_fmt_pct(e.train_mean_net)} p={_fmt_p(e.train_p)} | "
              f"test n={e.test_n} net={_fmt_pct(e.test_mean_net)} p={_fmt_p(e.test_p)}")

    # ---- Refute-yourself pass on every economically-positive confirmed candidate ----
    refute_results: Dict[str, Any] = {}
    cond_lookup: Dict[str, Any] = {s.name: (s.condition_fn, s.horizons[0]) for s in specs}

    if econ_positive:
        print(f"\n{'=' * 100}")
        print("REFUTE-YOURSELF PASS (only run on economically-positive confirmed candidates)")
        print(f"{'=' * 100}")
        seen_spec_names = set()
        for e in econ_positive:
            base_spec_name = e.spec_name
            if base_spec_name in seen_spec_names:
                continue
            seen_spec_names.add(base_spec_name)
            cond_fn, n_days = cond_lookup[base_spec_name]
            detail = era_and_gross_detail(base_spec_name, campaign)
            pre = detail["pre_era"]
            post = detail["post_era"]
            same_sign_eras = (pre is not None and post is not None and pre["n"] >= ch.MIN_N and
                               post["n"] >= ch.MIN_N and pre["mean_net"] is not None and
                               post["mean_net"] is not None and
                               np.sign(pre["mean_net"]) == np.sign(post["mean_net"]) and
                               pre["mean_net"] > 0)
            print(f"\n-- {base_spec_name} (h={detail['horizon']}d) --")
            print(f"   n_raw_triggers={detail['n_raw_triggers']} n_deduped_episodes={detail['n_full_episodes']} "
                  f"collapse_ratio={detail['collapse_ratio']}")
            print(f"   (c) gross vs net -- full sample: gross={_fmt_pct(detail['full_gross'])} "
                  f"net={_fmt_pct(detail['full_net'])} (cost = gross - net)")
            if pre and post:
                print(f"   (a) era split -- pre-Feb-2026: n={pre['n']} net={_fmt_pct(pre['mean_net'])} "
                      f"gross={_fmt_pct(pre['mean_gross'])} dominance={pre['dominance_flag']} | "
                      f"post-Feb-2026: n={post['n']} net={_fmt_pct(post['mean_net'])} "
                      f"gross={_fmt_pct(post['mean_gross'])} dominance={post['dominance_flag']}")
                print(f"       same-sign-and-positive-both-eras: {same_sign_eras}")
            else:
                print("   (a) era split -- insufficient data in one era to evaluate")
            print(f"   (b) dominance (train or test) flagged: {e.dominance_flag}")
            crash_res = run_crash_window_check(n_days, cond_fn, store, base_spec_name)
            h = n_days
            cr_train = crash_res.train.per_horizon.get(h)
            cr_test = crash_res.test.per_horizon.get(h)
            print(f"   (d) excluding crash window {CRASH_WINDOW_START}..{CRASH_WINDOW_END}: "
                  f"train n={cr_train.n if cr_train else 0} net={_fmt_pct(cr_train.mean_net if cr_train else None)} "
                  f"p={_fmt_p(cr_train.p_value if cr_train else None)} | "
                  f"test n={cr_test.n if cr_test else 0} net={_fmt_pct(cr_test.mean_net if cr_test else None)} "
                  f"p={_fmt_p(cr_test.p_value if cr_test else None)}")
            survives_excl_crash = (cr_train is not None and cr_test is not None and
                                    cr_train.mean_net is not None and cr_test.mean_net is not None and
                                    cr_train.mean_net > 0 and cr_test.mean_net > 0)
            print(f"       survives crash-window exclusion (both folds still net-positive): {survives_excl_crash}")
            if pre and post and pre["mean_net"] is not None and post["mean_net"] is not None:
                weakening = abs(post["mean_net"]) < abs(pre["mean_net"])
                print(f"   (e) crowding sanity -- |post-era net| {'<' if weakening else '>='} |pre-era net| "
                      f"({_fmt_pct(post['mean_net'])} vs {_fmt_pct(pre['mean_net'])}): "
                      f"{'weakening (consistent w/ crowding or decay)' if weakening else 'not weakening'}")
            fully_clears = (same_sign_eras and not e.dominance_flag and survives_excl_crash)
            print(f"   ==> FULLY CLEARS ALL REFUTE-YOURSELF CHECKS: {fully_clears}")
            refute_results[base_spec_name] = {
                "same_sign_eras": bool(same_sign_eras), "dominance_flag": bool(e.dominance_flag),
                "survives_excl_crash": bool(survives_excl_crash), "fully_clears": bool(fully_clears),
            }
    else:
        print("\nNo economically-positive confirmed candidates -- refute-yourself pass skipped (nothing to refute).")

    final_survivors = [name for name, r in refute_results.items() if r["fully_clears"]]

    print(f"\n{'=' * 100}")
    print("VERDICT")
    print(f"{'=' * 100}")
    if final_survivors:
        print(f"{len(final_survivors)} cell(s) clear EVERY bar (FDR + OOS test + same-sign-positive both eras + "
              f"no dominance + survives crash-window exclusion): {final_survivors}")
        print("-> genuine, harvestable, unlevered 3d-mean-reversion RULE candidate(s). Pre-register in "
              "PREREGISTRATION.md as an H-series forward-validation hypothesis before treating as a finding.")
    else:
        print("0 cells clear every bar.")
        if campaign.n_confirmed > 0 and not econ_positive:
            print("-> some cells FDR-confirmed but the confirmed direction was NOT net-positive (a confirmed "
                  "persistent LOSS or a sign flip counted by the harness's bare same-sign check) -- not an edge.")
        elif econ_positive and not final_survivors:
            print("-> some cells were economically-positive AND OOS-confirmed on the train/test split, but "
                  "failed the era-split / dominance / crash-window refutation -- structure is present but not "
                  "cleanly harvestable as a standing rule; log honestly, do not pre-register.")
        else:
            print("-> no cell was even OOS-confirmed net-of-cost on the train/test split. The 3-day-drop RULE, "
                  "as an actual buy-hold-N-days-and-sell trade, is not shown to be a tradeable edge on this data "
                  "-- distinct from (and does not contradict) the structure study's population-level "
                  "autocorrelation finding, which measured something else (see docstring).")

    # ---- JSON dump ----
    dump = {
        "alpha": args.alpha, "perm_iters": perm_iters, "n_tested": campaign.n_tested,
        "expected_false_positives": campaign.expected_false_positives,
        "n_surviving_fdr": campaign.n_surviving_fdr, "n_confirmed": campaign.n_confirmed,
        "n_economically_positive_confirmed": len(econ_positive),
        "final_survivors": final_survivors,
        "entries": [
            {"test_id": e.test_id, "spec_name": e.spec_name, "bucket": e.bucket, "horizon": e.horizon,
             "train_n": e.train_n, "train_p": e.train_p, "train_mean_net": e.train_mean_net,
             "train_mean_gross": e.train_mean_gross, "test_n": e.test_n, "test_p": e.test_p,
             "test_mean_net": e.test_mean_net, "test_mean_gross": e.test_mean_gross,
             "fdr_survivor": e.fdr_survivor, "confirmed": e.confirmed, "dominance_flag": e.dominance_flag}
            for e in campaign.entries
        ],
        "era_gross_detail": {name: era_and_gross_detail(name, campaign) for name in
                              {e.spec_name for e in campaign.entries}},
        "refute_results": refute_results,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(dump, f, indent=2, default=str)
    print(f"\nFull machine-readable dump written to {args.out}")


if __name__ == "__main__":
    main()
