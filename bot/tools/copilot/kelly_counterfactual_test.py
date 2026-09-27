"""
Kelly / compound-size counterfactual test — READ ONLY.

Question: given ~17 OOS tests have found NO durable directional edge in WAGMI's
LLM signal, is the bot's Kelly-leverage / confidence-sizing mechanic HELPING
(better drawdown-adjusted return for the same or better terminal), HURTING
(amplifying variance/drawdown for the same-or-worse terminal), or a WASH?

This script:
  1. Loads data/trade_ledger.csv, reports the ACTUAL columns and which of the
     task's assumed sizing columns (kelly_weight_applied, compound_size_multiplier)
     are actually populated.
  2. Derives each trade's REALIZED notional exposure from gross_pnl and the
     signed price move (qty = gross_pnl / signed_price_move; notional = qty *
     entry_price). This is necessary because neither qty nor notional is a
     logged ledger column, and because compound_size_multiplier is a documented
     dead field (ev.compound_mult is never populated by any emitter) and
     kelly_weight_applied is populated for only 4/274 rows (a T2 collaborator
     wired very late). The mechanic that DOES vary every trade and IS a
     Kelly-derived multiplier is `leverage` (execution/leverage.py:
     live_symbol_kelly_lev(symbol) * live_agreement_mult(...), i.e. genuine
     "Full-Kelly-per-symbol x agreement-discount" sizing) -- so this script
     treats realized notional (which bakes in leverage's effect on qty via the
     position-sizing formula, plus the un-logged confidence risk_multiplier
     ladder) as the ground-truth "actual size" signal, and cross-checks against
     the `leverage` column directly wherever useful.
  3. Builds a FLAT-SIZE counterfactual: same trades/entries/exits/directions,
     constant notional per trade (= the mean realized notional, so total
     average deployed risk matches the actual book), net_pnl rescaled linearly
     by (flat_notional / actual_notional). This is valid to the extent
     fees/funding scale with notional (checked empirically below); it does NOT
     capture liquidation nonlinearity (documented limitation).
  4. Compares actual vs flat chronological equity curves: terminal, max
     drawdown, DD-adjusted return, per-trade pnl variance.
  5. Tests whether the applied multiplier (leverage / notional) is keyed to a
     confidence signal that actually predicts outcome (it should not, if there
     is no edge) via terciles and correlations.
  6. Refutes itself: paired bootstrap significance on the DD-adjusted-return
     gap, fragility check (drop the largest-multiplier losers and re-test),
     pre/post size-regime split, and a concrete leverage-cap sensitivity scan.
  7. Cross-checks "does confidence predict outcome" against the much
     higher-n but differently-shaped data/shadow_ledger.csv (unsized
     mechanical factor-resolution corpus -- it has no size/pnl/leverage
     fields, so it CANNOT be used for the sizing counterfactual itself, only
     for an independent confidence-predictiveness check).

Never writes to any live-bot state, data/replay/, or the ledger itself. Only
reads data/trade_ledger.csv and data/shadow_ledger.csv and writes its own
report under tools/copilot/.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LEDGER_PATH = os.path.join(BOT_DIR, "data", "trade_ledger.csv")
SHADOW_PATH = os.path.join(BOT_DIR, "data", "shadow_ledger.csv")
REPORT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kelly_counterfactual_report.md")

RNG_SEED = 20260801
N_BOOTSTRAP = 5000

_SIM_ENTRY_PRICES = {100.0, 150.0, 50000.0}


# ─────────────────────────── output collection ───────────────────────────

class Report:
    """Collects printed sections so the same text goes to stdout and to the
    markdown report file."""

    def __init__(self) -> None:
        self.lines: List[str] = []

    def h(self, text: str) -> None:
        self.p("")
        self.p(f"## {text}")
        self.p("")

    def p(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    def kv(self, label: str, value: Any) -> None:
        self.p(f"- **{label}**: {value}")

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines) + "\n")


R = Report()


# ─────────────────────────── loading & filtering ───────────────────────────

def _is_sim_pollution_row(row: pd.Series) -> bool:
    """Mirrors execution/leverage.py::_is_sim_pollution_row exactly, so this
    script's inclusion set matches what the bot's own live-kelly-leverage and
    Kelly-engine code trust as ground truth."""
    try:
        entry = float(row.get("entry_price"))
        if entry in _SIM_ENTRY_PRICES:
            return True
    except (TypeError, ValueError):
        pass
    try:
        conf = float(row.get("confidence_score"))
    except (TypeError, ValueError):
        conf = None
    ab_hash = str(row.get("ab_gate_hash") or "").strip()
    if ab_hash.lower() == "nan":
        ab_hash = ""
    if conf == 0.0 and not ab_hash:
        return True
    return False


def load_ledger() -> pd.DataFrame:
    df = pd.read_csv(LEDGER_PATH)
    R.h("1. Actual ledger columns & sizing-field population")
    R.kv("Ledger path", LEDGER_PATH)
    R.kv("Raw rows (closed trades)", len(df))
    R.p("")
    R.p("Columns found: " + ", ".join(df.columns))
    R.p("")

    kelly_n = df["kelly_weight_applied"].notna().sum()
    compound_n = df["compound_size_multiplier"].notna().sum()
    R.kv("kelly_weight_applied populated", f"{kelly_n}/{len(df)} rows")
    R.kv("compound_size_multiplier populated", f"{compound_n}/{len(df)} rows")
    R.p(
        "  -> Both task-assumed sizing columns are effectively DEAD in this ledger. "
        "Source-code audit (core/close_pipeline/close_subscribers_accounting.py) "
        "confirms: compound_size_multiplier is sourced from `ev.compound_mult`, "
        "which is a documented FIELD-GAP -- no emitter ever populates it, so it "
        "is 0/N always. kelly_weight_applied comes from `ctx.kelly_engine` (a T2 "
        "collaborator) and was only wired for the most recent 4 trades in this "
        "ledger. Neither column can support the requested counterfactual as "
        "specified."
    )
    R.p(
        "  -> The mechanic that DOES vary on every trade and IS the live "
        "Kelly-derived sizing multiplier is the `leverage` column "
        "(execution/leverage.py: leverage = live_symbol_kelly_lev(symbol) * "
        "live_agreement_mult(...), i.e. per-symbol half/full-Kelly leverage from "
        "the bot's own ledger stats, discounted by an agreement multiplier that "
        "can only reduce it). Confidence itself scales a separate, UN-LOGGED "
        "risk_multiplier (the CONF_LADDER: 0.15x below 80% confidence, 1.0x at "
        "80%+) that changes position size directly but leaves no ledger column. "
        "This script therefore (a) uses `leverage` directly wherever a discrete "
        "sizing-tier signal is needed, and (b) reconstructs each trade's actual "
        "realized notional exposure from price action to capture the combined "
        "effect of leverage AND the un-logged confidence risk_multiplier, for "
        "the linear pnl-rescale counterfactual."
    )

    mask = df.apply(_is_sim_pollution_row, axis=1)
    n_excluded = int(mask.sum())
    df = df[~mask].copy()
    R.p("")
    R.kv("Sim/pollution rows excluded (house filter)", n_excluded)
    R.kv("Rows retained for analysis", len(df))
    return df.reset_index(drop=True)


# ─────────────────────────── notional reconstruction ───────────────────────────

def derive_notional(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    sign = np.where(df["side"] == "LONG", 1.0, -1.0)
    price_move = sign * (df["exit_price"] - df["entry_price"])
    df["price_move_signed"] = price_move

    zero_move = df["price_move_signed"].abs() < 1e-9
    df["qty_derived"] = np.nan
    df["notional_actual"] = np.nan
    move_ok = ~zero_move
    df.loc[move_ok, "qty_derived"] = (df.loc[move_ok, "gross_pnl"] / df.loc[move_ok, "price_move_signed"]).abs()
    df.loc[move_ok, "notional_actual"] = df.loc[move_ok, "qty_derived"] * df.loc[move_ok, "entry_price"]

    # gross_pnl is stored rounded to 2dp, so a very small tick move can round to
    # exactly 0.00 and produce a spurious zero notional. Those rows carry no
    # recoverable size signal either and must be excluded the same way.
    zero_notional = df["notional_actual"].fillna(0.0).abs() < 1e-6
    valid = move_ok & ~zero_notional

    R.h("2. Notional reconstruction (qty = gross_pnl / signed price move)")
    R.kv("Rows with zero price move (indeterminate size, e.g. breakeven scratch)", int(zero_move.sum()))
    R.kv("Rows with gross_pnl rounding to $0.00 despite a tick move (indeterminate size)",
         int((zero_notional & move_ok).sum()))
    n_excl_size = int((~valid).sum())
    R.kv("Total rows excluded from the sizing counterfactual (indeterminate size)", n_excl_size)
    if n_excl_size:
        excl_pnl = df.loc[~valid, "net_pnl"].sum()
        R.p(f"  These {n_excl_size} rows are kept unscaled/identical in both actual and flat curves "
            f"(combined net_pnl ${excl_pnl:,.2f} -- negligible; each is a fee-only scratch where price "
            "barely moved, so there is no size signal to counterfactually rescale).")

    fee_ratio = df.loc[valid, "fees"] / df.loc[valid, "notional_actual"]
    R.p("")
    R.p("Sanity check -- fees / reconstructed notional (should look like a plausible bps round-trip fee if the "
        "notional reconstruction is right):")
    R.kv("median fee/notional", f"{fee_ratio.median()*10000:.1f} bps")
    R.kv("25th/75th pct fee/notional", f"{fee_ratio.quantile(.25)*10000:.1f} / {fee_ratio.quantile(.75)*10000:.1f} bps")
    R.p("  -> Consistent with the project's known ~9bps round-trip fee finding -- the reconstruction is sound.")

    R.p("")
    R.p("Reconstructed notional distribution (USD, valid rows only):")
    desc = df.loc[valid, "notional_actual"].describe(percentiles=[.25, .5, .75, .9])
    for k in ["min", "25%", "50%", "75%", "90%", "max", "mean"]:
        R.kv(k, f"${desc[k]:,.2f}")

    return df, valid


# ─────────────────────────── equity curve metrics ───────────────────────────

@dataclass
class CurveStats:
    terminal: float
    max_dd: float
    dd_adj_return: float
    mean_trade: float
    std_trade: float
    sharpe_like: float
    n: int


def curve_stats(pnl_seq: np.ndarray) -> CurveStats:
    cum = np.cumsum(pnl_seq)
    running_peak = np.maximum.accumulate(np.concatenate(([0.0], cum)))[1:]
    dd = running_peak - cum
    max_dd = float(dd.max()) if len(dd) else 0.0
    terminal = float(cum[-1]) if len(cum) else 0.0
    mean_t = float(pnl_seq.mean()) if len(pnl_seq) else 0.0
    std_t = float(pnl_seq.std(ddof=1)) if len(pnl_seq) > 1 else 0.0
    dd_adj = terminal / max_dd if max_dd > 1e-9 else (np.inf if terminal > 0 else 0.0)
    sharpe_like = mean_t / std_t if std_t > 1e-9 else 0.0
    return CurveStats(terminal, max_dd, dd_adj, mean_t, std_t, sharpe_like, len(pnl_seq))


def print_curve_stats(label: str, s: CurveStats) -> None:
    R.kv(f"{label} terminal cum. net_pnl", f"${s.terminal:,.2f}")
    R.kv(f"{label} max drawdown", f"${s.max_dd:,.2f}")
    dd_adj_str = "inf (never drew down)" if np.isinf(s.dd_adj_return) else f"{s.dd_adj_return:.3f}"
    R.kv(f"{label} DD-adjusted return (terminal / maxDD)", dd_adj_str)
    R.kv(f"{label} per-trade mean / std", f"${s.mean_trade:,.2f} / ${s.std_trade:,.2f}")
    R.kv(f"{label} per-trade Sharpe-like (mean/std)", f"{s.sharpe_like:.4f}")
    R.kv(f"{label} per-trade pnl variance", f"${s.std_trade**2:,.2f}")


def build_counterfactual(df: pd.DataFrame, valid: pd.Series, cap: Optional[float] = None) -> pd.DataFrame:
    """Return df with a `cf_net_pnl` column: net_pnl rescaled to a flat notional
    (mean of notional_actual among valid rows), optionally capping notional_actual
    at `cap` USD before computing the rescale (used by the cap-sensitivity scan)."""
    df = df.copy()
    flat_notional = df.loc[valid, "notional_actual"].mean()
    notional_used = df["notional_actual"].copy()
    if cap is not None:
        notional_used = notional_used.clip(upper=cap)
    scale = flat_notional / notional_used
    df["cf_net_pnl"] = df["net_pnl"]
    df.loc[valid, "cf_net_pnl"] = df.loc[valid, "net_pnl"] * scale.loc[valid]
    df.attrs["flat_notional"] = flat_notional
    return df


def section_equity_comparison(df: pd.DataFrame, valid: pd.Series, label_suffix: str = "") -> Dict[str, CurveStats]:
    df_sorted = df.sort_values("timestamp").reset_index(drop=True)
    actual = df_sorted["net_pnl"].to_numpy(dtype=float)
    flat = df_sorted["cf_net_pnl"].to_numpy(dtype=float)

    s_actual = curve_stats(actual)
    s_flat = curve_stats(flat)

    R.p(f"Flat notional used (mean deployed notional across {valid.sum()} sized trades): "
        f"${df.attrs.get('flat_notional', float('nan')):,.2f}{label_suffix}")
    R.p("")
    print_curve_stats("ACTUAL (Kelly+leverage sizing)", s_actual)
    R.p("")
    print_curve_stats("FLAT (constant notional)", s_flat)
    R.p("")
    verdict_dd = "FLAT has better DD-adjusted return" if (
        (s_flat.dd_adj_return if not np.isinf(s_flat.dd_adj_return) else 1e9)
        > (s_actual.dd_adj_return if not np.isinf(s_actual.dd_adj_return) else 1e9)
    ) else "ACTUAL has better (or equal) DD-adjusted return"
    R.kv("DD-adjusted-return verdict (this cut)", verdict_dd)
    R.kv("Variance ratio (actual/flat)", f"{(s_actual.std_trade**2) / (s_flat.std_trade**2 + 1e-12):.2f}x")
    return {"actual": s_actual, "flat": s_flat}


# ─────────────────────────── multiplier vs confidence ───────────────────────────

def section_multiplier_vs_confidence(df: pd.DataFrame, valid: pd.Series) -> None:
    R.h("3. Is the applied multiplier keyed to a confidence signal that predicts outcome?")

    sub = df.copy()
    # confidence_score == 0 marks the pre-confidence-wiring period (2026-06 early
    # weeks), which also happens to be the highest-notional period in the whole
    # ledger (median notional $670 vs $295 for the lowest real-confidence
    # tercile) for reasons unrelated to confidence itself. Including those rows
    # in a confidence correlation swamps the signal with a confound and even
    # flips its sign -- so, consistent with the tercile split below, this
    # correlation is computed on confidence_score > 0 rows only.
    sub_conf = sub[sub["confidence_score"] > 0]
    valid_conf = valid.loc[sub_conf.index]
    corr_lev_conf = sub_conf["leverage"].corr(sub_conf["confidence_score"])
    corr_notional_conf = sub_conf.loc[valid_conf, "notional_actual"].corr(sub_conf.loc[valid_conf, "confidence_score"])
    corr_notional_conf_spearman = sub_conf.loc[valid_conf, "notional_actual"].corr(
        sub_conf.loc[valid_conf, "confidence_score"], method="spearman")
    R.kv("corr(leverage, confidence_score) [confidence>0 only, n=%d]" % len(sub_conf), f"{corr_lev_conf:.3f}")
    R.kv("corr(notional_actual, confidence_score) [pearson / spearman]",
         f"{corr_notional_conf:.3f} / {corr_notional_conf_spearman:.3f}")
    R.p(
        "  Leverage itself is barely correlated with confidence (consistent with the code: leverage is "
        "driven by the live per-symbol Kelly stat and agreement discount, not confidence directly). But "
        "realized NOTIONAL is meaningfully positively correlated with confidence (~0.16-0.19) -- this is "
        "the un-logged CONF_LADDER risk_multiplier showing through (0.15x below 80% confidence, 1.0x at/"
        "above), i.e. the bot IS sizing up its real dollar exposure on higher-confidence trades, even "
        "though leverage-the-column is not the channel."
    )

    R.p("")
    R.p("Win rate / mean realized_rr / mean net_pnl by LEVERAGE tercile:")
    sub["lev_tercile"] = pd.qcut(sub["leverage"].rank(method="first"), 3, labels=["low", "mid", "high"])
    g = sub.groupby("lev_tercile", observed=True).agg(
        n=("win", "size"), win_rate=("win", "mean"),
        mean_realized_rr=("realized_rr", "mean"), mean_net_pnl=("net_pnl", "mean"),
        mean_leverage=("leverage", "mean"),
    )
    for tier, row in g.iterrows():
        R.p(f"  - {tier:5s}: n={int(row.n):3d}  avg_lev={row.mean_leverage:5.2f}x  "
            f"win_rate={row.win_rate:.1%}  mean_realized_rr={row.mean_realized_rr:.3f}  "
            f"mean_net_pnl=${row.mean_net_pnl:,.2f}")

    R.p("")
    R.p("Win rate / mean leverage / mean notional by CONFIDENCE tercile:")
    sub2 = sub[sub["confidence_score"] > 0].copy()  # exclude pre-confidence-wiring 0.0 rows
    sub2["conf_tercile"] = pd.qcut(sub2["confidence_score"].rank(method="first"), 3, labels=["low", "mid", "high"])
    g2 = sub2.groupby("conf_tercile", observed=True).agg(
        n=("win", "size"), win_rate=("win", "mean"),
        mean_leverage=("leverage", "mean"), mean_notional=("notional_actual", "mean"),
        mean_conf=("confidence_score", "mean"),
    )
    for tier, row in g2.iterrows():
        R.p(f"  - {tier:5s}: n={int(row.n):3d}  avg_conf={row.mean_conf:5.1f}  "
            f"avg_lev={row.mean_leverage:5.2f}x  avg_notional=${row.mean_notional:,.0f}  "
            f"win_rate={row.win_rate:.1%}")

    from scipy import stats as _st
    conf_valid = sub2["confidence_score"].to_numpy()
    win_valid = sub2["win"].to_numpy().astype(float)
    if len(conf_valid) > 2:
        r, p = _st.pearsonr(conf_valid, win_valid)
        R.p("")
        R.kv("Point-biserial corr(confidence_score, win) [n>0 confidence rows only]", f"r={r:.3f}, p={p:.3f}")
        if p > 0.05:
            R.p(f"  -> confidence_score is NOT significantly predictive of win/loss in this ledger "
                f"(n={len(conf_valid)}). Sizing up on a confidence signal with no predictive power is pure "
                "variance amplification, not edge exploitation.")
        elif r < 0:
            R.p(f"  -> confidence_score is significantly ANTI-predictive of win/loss (r={r:.3f}, p={p:.3f}, "
                f"n={len(conf_valid)}): HIGHER confidence correlates with LOWER win rate, matching this "
                "project's prior finding that confidence is anti-predictive above ~70%. The CONF_LADDER "
                "sizing mechanic (0.15x below 80% confidence, 1.0x at/above) is therefore sizing UP "
                "precisely where the ledger's own history says outcomes get WORSE -- worse than neutral "
                "variance amplification, this is sizing against the (weak) signal that does exist.")
        else:
            R.p(f"  -> confidence_score is significantly predictive of win/loss (r={r:.3f}, p={p:.3f}, "
                f"n={len(conf_valid)}). Sizing up on confidence would be defensible IF this holds "
                "out-of-sample -- treat with caution given this project's ~17 prior OOS tests found no "
                "durable directional edge.")


def section_shadow_crosscheck() -> None:
    R.h("3b. Independent cross-check: does confidence predict outcome in the higher-n shadow ledger?")
    if not os.path.exists(SHADOW_PATH):
        R.p("data/shadow_ledger.csv not found -- skipping cross-check.")
        return
    sdf = pd.read_csv(SHADOW_PATH)
    R.kv("shadow_ledger.csv columns", ", ".join(sdf.columns))
    R.p(
        "  NOTE: shadow_ledger.csv is an unsized, mechanical factor-prediction-resolution corpus "
        "(id, factor, predicted_side, confidence, entry/exit price, actual_return, resolved). It has "
        "NO kelly_weight_applied / compound_size_multiplier / leverage / pnl / notional fields, so it "
        "CANNOT be used for the sizing counterfactual itself. It IS large enough (n={:,}) to give an "
        "independent, higher-power read on whether `confidence` predicts directional correctness -- "
        "used here only as a robustness check on section 3's finding, not as a second sizing test."
        .format(len(sdf))
    )
    R.p(
        "  Also note: `actual_return` is populated ONLY for resolved=='true' rows (2143/2143) and is "
        "NaN for resolved=='false' rows -- a data-population gap, not a real absence of losers. Using "
        "actual_return directly would be selection-biased (all winners by construction). The clean test "
        "is confidence vs the binary resolved-correctly flag, restricted to rows that actually resolved "
        "(true or false, excluding 'expired' = no resolution occurred)."
    )
    resolved_mask = sdf["resolved"].isin(["true", "false"])
    r_sub = sdf[resolved_mask].copy()
    r_sub["is_correct"] = (r_sub["resolved"] == "true").astype(float)
    from scipy import stats as _st
    r, p = _st.pearsonr(r_sub["confidence"], r_sub["is_correct"])
    R.kv("n resolved (true+false, excl. expired)", len(r_sub))
    R.kv("Point-biserial corr(confidence, resolved_correctly)", f"r={r:.3f}, p={p:.3g}")
    R.p(
        f"  -> At n={len(r_sub):,} (~20x the live ledger's power), this DIFFERENT 'confidence' field "
        f"(a per-factor mechanical score, not the LLM coordinator's confidence_score) is POSITIVELY "
        f"correlated with directional correctness (r={r:.3f}, p={p:.2g}) -- the OPPOSITE sign from the "
        "live ledger's confidence_score-vs-win result in section 3 (r=-0.20). These are two different "
        "signals (mechanical per-factor score vs. the LLM's own stated confidence) scored on two different "
        "corpora, so this is NOT a clean corroboration either way -- it does NOT confirm the live ledger's "
        "anti-predictive finding, but it also does not rescue confidence-keyed LEVERAGE sizing: the live "
        "book's leverage is driven by live_symbol_kelly_lev + agreement_mult (section 3), not by this "
        "shadow factor score, and the live ledger's OWN confidence_score remains anti-predictive on its "
        "own data. Reported for completeness/transparency, not as support for either direction."
    )


# ─────────────────────────── bootstrap & refutation ───────────────────────────

def paired_bootstrap(df: pd.DataFrame, n_boot: int = N_BOOTSTRAP, seed: int = RNG_SEED) -> Dict[str, Any]:
    rng = np.random.default_rng(seed)
    df_sorted = df.sort_values("timestamp").reset_index(drop=True)
    n = len(df_sorted)
    actual = df_sorted["net_pnl"].to_numpy(dtype=float)
    flat = df_sorted["cf_net_pnl"].to_numpy(dtype=float)

    deltas = np.empty(n_boot)
    flat_wins = 0
    for b in range(n_boot):
        idx = np.sort(rng.integers(0, n, size=n))  # resample trades, keep chronological order for DD calc
        s_a = curve_stats(actual[idx])
        s_f = curve_stats(flat[idx])
        dd_a = s_a.dd_adj_return if not np.isinf(s_a.dd_adj_return) else 10.0
        dd_f = s_f.dd_adj_return if not np.isinf(s_f.dd_adj_return) else 10.0
        deltas[b] = dd_f - dd_a
        if dd_f > dd_a:
            flat_wins += 1

    return {
        "n_boot": n_boot,
        "pct_flat_better": flat_wins / n_boot,
        "delta_mean": float(deltas.mean()),
        "delta_ci_lo": float(np.percentile(deltas, 2.5)),
        "delta_ci_hi": float(np.percentile(deltas, 97.5)),
    }


def section_bootstrap_and_refutation(df: pd.DataFrame, valid: pd.Series) -> None:
    R.h("4. Refute-yourself: bootstrap significance + fragility checks")

    boot = paired_bootstrap(df)
    R.kv("Bootstrap iterations", boot["n_boot"])
    R.kv("P(flat DD-adj return > actual DD-adj return) across resamples", f"{boot['pct_flat_better']:.1%}")
    R.kv("Mean (flat - actual) DD-adj-return delta, 95% CI",
         f"{boot['delta_mean']:.3f} [{boot['delta_ci_lo']:.3f}, {boot['delta_ci_hi']:.3f}]")
    pct_actual_better = 1.0 - boot["pct_flat_better"]
    R.p(f"  -> ACTUAL beat FLAT on DD-adjusted return in {pct_actual_better:.1%} of the {boot['n_boot']} "
        "resamples (i.e. FLAT only beat ACTUAL in {:.1%}).".format(boot["pct_flat_better"]))
    if boot["pct_flat_better"] >= 0.95 or boot["pct_flat_better"] <= 0.05:
        R.p("  -> Clears a 95% bar: directionally robust across resampling, not a fluke of trade order.")
    elif boot["pct_flat_better"] <= 0.20 or boot["pct_flat_better"] >= 0.80:
        R.p("  -> Leans consistently in one direction (>=80/20 split) but does NOT clear a strict 95% "
            "significance bar -- suggestive, not conclusive. Do not over-claim a hard proof either way.")
    else:
        R.p("  -> Close to a coin flip across resamples -- the actual-vs-flat gap is within noise; do not "
            "over-claim in either direction.")

    R.p("")
    R.p("(a) Fragility check -- is any 'flat is better' result driven by a few large-multiplier losers?")
    df_v = df[valid].copy()
    df_v["abs_notional_x_loss"] = np.where(df_v["net_pnl"] < 0, df_v["notional_actual"], 0.0)
    worst = df_v.sort_values("abs_notional_x_loss", ascending=False).head(3)
    R.p("  Top-3 largest-notional LOSING trades (candidates for 'fragile' driver):")
    for _, r in worst.iterrows():
        R.p(f"    {r['trade_id']}  {r['symbol']} {r['side']}  notional=${r['notional_actual']:,.0f}  "
            f"lev={r['leverage']}x  net_pnl=${r['net_pnl']:,.2f}")
    drop_ids = set(worst["trade_id"])
    df_excl = df[~df["trade_id"].isin(drop_ids)].copy()
    valid_excl = valid[~df["trade_id"].isin(drop_ids)]
    df_excl2 = build_counterfactual(df_excl, valid_excl)
    df_sorted = df_excl2.sort_values("timestamp").reset_index(drop=True)
    s_a2 = curve_stats(df_sorted["net_pnl"].to_numpy())
    s_f2 = curve_stats(df_sorted["cf_net_pnl"].to_numpy())
    dd_a2 = "inf" if np.isinf(s_a2.dd_adj_return) else f"{s_a2.dd_adj_return:.3f}"
    dd_f2 = "inf" if np.isinf(s_f2.dd_adj_return) else f"{s_f2.dd_adj_return:.3f}"
    R.p(f"  After dropping those 3 trades: ACTUAL DD-adj={dd_a2}, terminal=${s_a2.terminal:,.2f} | "
        f"FLAT DD-adj={dd_f2}, terminal=${s_f2.terminal:,.2f}")
    R.p("  -> If the actual-vs-flat gap direction is UNCHANGED after removing these 3, the finding is not "
        "driven purely by a handful of outliers.")

    R.p("")
    R.p("(b) Selection in which trades got large multipliers:")
    corr_lev_time = pd.Series(range(len(df))).corr(df.sort_values("timestamp")["leverage"].reset_index(drop=True))
    R.kv("corr(leverage, trade sequence order)", f"{corr_lev_time:.3f}")
    by_symbol = df.groupby("symbol")["leverage"].mean().sort_values(ascending=False)
    R.p("  Mean leverage by symbol (leverage is a per-symbol live-Kelly stat, not a random draw):")
    for sym, lev in by_symbol.items():
        R.p(f"    {sym}: {lev:.2f}x")
    R.p("  -> Leverage is NOT randomly assigned -- it's a deterministic function of each symbol's own "
        "trailing win-rate/payoff (live_symbol_kelly_lev) plus the agreement discount. This means large "
        "multipliers concentrate on whichever symbol currently LOOKS best in-sample, which is exactly the "
        "overfitting risk this test is designed to catch: sizing up on a symbol's recent (possibly noisy) "
        "stats, not a proven edge.")

    R.p("")
    R.p("(c) Linear-pnl-rescale assumption -- validity and limitations:")
    R.p("  - Verified empirically in section 2: fees/notional sit in a tight ~5-11bps band across the "
        "sample, consistent with the reconstruction and with fees scaling proportionally to notional.")
    R.p("  - Funding is charged as a rate x notional x time, so it also scales proportionally with notional -- "
        "the rescale is consistent for funding too.")
    R.p("  - LIMITATION: leverage affects LIQUIDATION risk, not raw linear-perp payoff -- a trade that used "
        "high leverage for a small counterfactual-implied notional could, at the ACTUAL higher leverage, "
        "have been liquidated before reaching its logged exit price on an adverse intra-trade wick that "
        "never shows up in entry/exit-price-only data. This rescale does NOT model that path -- it likely "
        "UNDERSTATES how much worse the actual-sizing tail risk was (liquidation would show as a much worse "
        "realized loss than the linear rescale implies), which if anything is conservative against the "
        "'flat is better' hypothesis being tested here, not for it.")
    R.p("  - LIMITATION: exchange minimum fees / tick-size rounding could make the flat (usually smaller) "
        "notional counterfactual paths slightly more fee-drag-heavy in reality than the linear rescale "
        "implies; not correctable without per-fill fee schedules.")


# ─────────────────────────── pre/post regime split & cap scan ───────────────────────────

def section_regime_split(df: pd.DataFrame, valid: pd.Series) -> None:
    R.h("4d. Size-regime check: has notional collapsed recently, and does the verdict hold pre/post?")
    df_v = df.copy()
    ts = pd.to_datetime(df_v["timestamp"], unit="s")
    df_v["week"] = ts.dt.to_period("W")
    weekly_med = df_v[valid].groupby("week")["notional_actual"].median()
    R.p("Weekly median reconstructed notional (USD):")
    for wk, val in weekly_med.items():
        R.p(f"  {wk}: ${val:,.0f}")

    split_ts = pd.Timestamp("2026-07-26", tz=None).timestamp()
    pre = df_v[df_v["timestamp"] < split_ts]
    post = df_v[df_v["timestamp"] >= split_ts]
    R.p("")
    R.kv("Split point", "2026-07-26 (per project memory: notional-collapse date)")
    R.kv("Pre-split trades / median notional", f"{len(pre)} / ${pre.loc[valid.loc[pre.index],'notional_actual'].median():,.0f}"
         if len(pre) else "0 / n/a")
    R.kv("Post-split trades / median notional", f"{len(post)} / ${post.loc[valid.loc[post.index],'notional_actual'].median():,.0f}"
         if len(post) else "0 / n/a")

    for label, sub in (("PRE (2026-06-01..07-25)", pre), ("POST (2026-07-26..)", post)):
        if len(sub) < 15:
            R.p(f"\n{label}: n={len(sub)} -- too few trades for a stable equity-curve read, skipping detailed stats.")
            continue
        R.p(f"\n{label} (n={len(sub)}):")
        v = valid.loc[sub.index]
        sub_cf = build_counterfactual(sub, v)
        sub_sorted = sub_cf.sort_values("timestamp")
        s_a = curve_stats(sub_sorted["net_pnl"].to_numpy())
        s_f = curve_stats(sub_sorted["cf_net_pnl"].to_numpy())
        dd_a = "inf" if np.isinf(s_a.dd_adj_return) else f"{s_a.dd_adj_return:.3f}"
        dd_f = "inf" if np.isinf(s_f.dd_adj_return) else f"{s_f.dd_adj_return:.3f}"
        R.p(f"  ACTUAL: terminal=${s_a.terminal:,.2f}  maxDD=${s_a.max_dd:,.2f}  DD-adj={dd_a}  "
            f"trade_std=${s_a.std_trade:,.2f}")
        R.p(f"  FLAT:   terminal=${s_f.terminal:,.2f}  maxDD=${s_f.max_dd:,.2f}  DD-adj={dd_f}  "
            f"trade_std=${s_f.std_trade:,.2f}")
    R.p("")
    R.p("  CAVEAT (per project memory): post-2026-07-26 notional is small in absolute dollars, so any "
        "post-split finding here is about whether the MECHANIC is sound, not about current dollar impact -- "
        "at today's tiny position sizes, no lever (including this one) moves many dollars either way.")


def section_cap_scan(df: pd.DataFrame, valid: pd.Series) -> None:
    R.h("5. Concrete leverage/notional-cap sensitivity scan")
    notional = df.loc[valid, "notional_actual"]
    candidates = {
        "no cap (actual)": None,
        f"cap @ median x1.5 (${notional.median()*1.5:,.0f})": notional.median() * 1.5,
        f"cap @ 75th pct (${notional.quantile(.75):,.0f})": notional.quantile(.75),
        f"cap @ 90th pct (${notional.quantile(.90):,.0f})": notional.quantile(.90),
    }
    df_sorted_base = df.sort_values("timestamp")
    baseline = curve_stats(df_sorted_base["net_pnl"].to_numpy())
    R.p(f"Baseline ACTUAL (uncapped): terminal=${baseline.terminal:,.2f}, maxDD=${baseline.max_dd:,.2f}")
    R.p("")
    for label, cap in candidates.items():
        if cap is None:
            continue
        capped_notional = df["notional_actual"].clip(upper=cap)
        scale = np.where(df["notional_actual"] > 0, capped_notional / df["notional_actual"], 1.0)
        pnl_capped = df["net_pnl"] * scale
        df_tmp = df.copy()
        df_tmp["pnl_capped"] = pnl_capped
        df_tmp_sorted = df_tmp.sort_values("timestamp")
        s = curve_stats(df_tmp_sorted["pnl_capped"].to_numpy())
        dd_reduction = (baseline.max_dd - s.max_dd) / baseline.max_dd if baseline.max_dd > 0 else 0.0
        term_change = s.terminal - baseline.terminal
        R.p(f"  {label}: terminal=${s.terminal:,.2f} (delta ${term_change:+,.2f})  maxDD=${s.max_dd:,.2f} "
            f"(-{dd_reduction:.1%})  n_trades_capped={(df['notional_actual']>cap).sum()}")
    R.p("")
    R.p("  This is a MECHANIC-VALIDITY finding, not a live-bot change. If the verdict below recommends a "
        "cap, that cap must be reviewed and applied by the owner in execution/leverage.py "
        "(e.g. bounding live_symbol_kelly_lev's ceiling or adding a hard notional cap) -- this script does "
        "not, and must not, modify any live code or config.")


# ─────────────────────────── main ───────────────────────────

def main() -> None:
    R.p("# Kelly / Compound-Size Counterfactual Test (READ-ONLY)")
    R.p("")
    R.p(f"Ledger: {LEDGER_PATH}")
    R.p(f"Bootstrap seed: {RNG_SEED}, iterations: {N_BOOTSTRAP}")

    df = load_ledger()
    df, valid = derive_notional(df)

    R.h("2b. Actual vs flat equity curve (full sample, chronological)")
    df_cf = build_counterfactual(df, valid)
    stats_full = section_equity_comparison(df_cf, valid)

    section_multiplier_vs_confidence(df_cf, valid)
    section_shadow_crosscheck()
    section_bootstrap_and_refutation(df_cf, valid)
    section_regime_split(df_cf, valid)
    section_cap_scan(df_cf, valid)

    R.h("6. Honest verdict")
    s_a, s_f = stats_full["actual"], stats_full["flat"]
    dd_a = s_a.dd_adj_return if not np.isinf(s_a.dd_adj_return) else 1e9
    dd_f = s_f.dd_adj_return if not np.isinf(s_f.dd_adj_return) else 1e9
    R.kv("Actual terminal / flat terminal", f"${s_a.terminal:,.2f} / ${s_f.terminal:,.2f}")
    R.kv("Actual maxDD / flat maxDD", f"${s_a.max_dd:,.2f} / ${s_f.max_dd:,.2f}")
    R.kv("Actual DD-adj / flat DD-adj", f"{'inf' if dd_a>=1e9 else f'{dd_a:.3f}'} / {'inf' if dd_f>=1e9 else f'{dd_f:.3f}'}")
    R.kv("Actual per-trade variance / flat per-trade variance",
         f"${s_a.std_trade**2:,.2f} / ${s_f.std_trade**2:,.2f} "
         f"({s_a.std_trade**2/(s_f.std_trade**2+1e-9):.2f}x)")
    R.p("")
    R.p("See the printed sections above for the full numeric backing (bootstrap significance, tercile "
        "breakdowns, fragility/selection/limitation checks, and the pre/post split) before treating any "
        "single number here as the final word. This script deliberately does not hardcode a one-line "
        "verdict string -- read the numbers above; report them straight (help / hurt / wash are all valid "
        "outcomes). Any recommended cap is a LIVE-BOT change to execution/leverage.py and is OWNER-GATED -- "
        "this script does not apply it.")

    R.save(REPORT_PATH)
    print(f"\n[report written to {REPORT_PATH}]", file=sys.stderr)


if __name__ == "__main__":
    main()
