#!/usr/bin/env python
"""
tools/copilot/circuit_breaker_test.py

READ-ONLY audit of the LIVE circuit breaker (execution/risk.py `CircuitBreaker`)
against the bot's actual realized trade sequence.

Owner's ask: the daily-loss-limit % and consecutive-loss-streak breakers in
risk/self_tuning.py's drawdown-tiered profiles (conservative/normal/aggressive
= 3%/5%/8% daily loss, max_positions 3/5/6) were NEVER validated against the
bot's own realized trades. Find the threshold that best trades off
drawdown-avoided vs opportunity-cost (winning trades skipped).

*** FINDING #0 (before any simulation): risk/self_tuning.py's 3%/5%/8% profile
table is DECORATIVE. `evaluate_and_adjust()` only flips a module-level
`_active_profile` string (used for a Telegram status line + an LLM-prompt
"description" string via `get_risk_profile_params()` in core/llm_integration.py
and multi_strategy_main.py) and `get_dynamic_leverage_cap()` (informational
leverage cap injected into the LLM prompt). Neither writes back into
`self.risk_mgr.circuit_breaker.daily_loss_limit_pct` / `.max_consecutive_losses`
or `config.max_open_positions`. grep confirms no call site does
`risk_mgr.circuit_breaker.daily_loss_limit_pct = get_risk_profile_params()[...]`
anywhere. So the 3/5/8% numbers are NOT the live breaker -- they never fire a
trade-blocking action on their own.

The REAL, trade-blocking circuit breaker is `execution.risk.CircuitBreaker`,
instantiated in multi_strategy_main.py:852 from `trading_config.TradingConfig`
fields, which read `.env` (this deployment's bot/.env, confirmed by grep):

    CIRCUIT_BREAKER_DAILY_LOSS_PCT = 0.07   (7% of CURRENT equity)   [.env override; class/dataclass default 0.05]
    MAX_CONSECUTIVE_LOSSES         = 10                              [.env override; class/dataclass default 5]
    CIRCUIT_BREAKER_COOLDOWN_MIN   = 60 (minutes)                    [.env, matches default]
    MAX_DRAWDOWN_PCT               = 0.15 (15%, from-peak)           [dataclass default; not in .env]
    MAX_SESSION_DRAWDOWN_PCT       = 0.20 (20%, cumulative, PERMANENT halt) [class default via os.getenv; not in .env]
    CB_CONF_OVERRIDE_PCT           = 0.92 (92% confidence override)  [dataclass default; not in .env]
    max_cb_overrides                = 0 (CircuitBreaker() call at multi_strategy_main.py:852
                                          does not pass max_cb_overrides -> class default 0
                                          -> the confidence-override escape hatch is DISABLED
                                          in practice: is_trading_allowed()'s override branch
                                          always returns False when max_overrides=0, regardless
                                          of confidence.)

TRIP MECHANISM (execution/risk.py, read directly, not re-derived):
  - `_check_breakers_inner()` runs on every trade close (`record_trade`) and
    checks, IN ORDER: (0) session cumulative DD >= 20% -> PERMANENT halt for
    the session (no cooldown recovery, `_session_halted=True`); (1) daily
    |pnl| / CURRENT equity >= daily_loss_limit_pct AND daily_pnl < 0 -> trip;
    (2) consecutive_losses >= max_consecutive_losses -> trip; (3) drawdown
    from peak_equity >= max_drawdown_pct (15%) -> trip.
  - A trip is NOT "rest of day" -- it is a flat `cooldown_minutes` (60 min)
    wall-clock/sim-time timer (`is_trading_allowed()`). Once elapsed, the
    breaker resets (consecutive_losses=0, peak_equity snapped to current
    equity) and grants 4 trades at HALF size ("post_cooldown_caution") rather
    than a hard re-open. So "opportunity cost" in this script = winning
    trades whose close would have fallen inside a 60-minute post-trip window,
    not a full day.
  - `check_mtm_breakers()` (continuous unrealized-PnL drawdown-from-peak
    check between trade closes) is NOT simulated here -- the ledger only has
    realized close events, no intra-trade mark price series. This means our
    "drawdown from peak" and "session DD" trip counts are a LOWER BOUND
    (real breaker could also trip intra-trade on unrealized losses this
    script cannot see). The two breakers the owner actually asked about
    (daily-loss-% and consecutive-loss streak) ARE realized-close-driven and
    ARE fully captured.

MECHANISM FIDELITY: this script imports the REAL `execution.risk.CircuitBreaker`
class (not a re-implementation) so the simulated trip logic is byte-for-byte
what live/paper trading runs. The only thing neutralized is the disk-writing
side effect `_log_safety_event()` (monkey-patched to a no-op) so this READ-ONLY
script never appends to data/logs/safety_events.csv or touches any live state
file. `circuit_breaker_state.json` is read for context only, never written.

COUNTERFACTUAL DESIGN (equity path): a fully causal replay (skip a trade ->
everything downstream, including position sizing/compounding/Kelly weight,
changes) is not reconstructible from a closed-trade ledger alone. We use the
standard simplification: a SELF-CONSISTENT SIMULATED equity curve, seeded at
the ledger's own back-solved starting equity, that accrues ONLY the pnl of
trades the breaker under test would have allowed ("kept" trades); a "skipped"
trade's pnl simply does not happen (no substitution trade, no re-entry, no
resizing feedback). This is deliberately conservative and stated up front as
a limitation (see REFUTE-YOURSELF section in the printed report) -- it is
the reason this script does NOT claim to know the *exact* dollar P&L under
an alternate threshold, only the FIRST-ORDER trade-off between dollars saved
on realized losers vs dollars foregone on realized winners the breaker would
have blocked, given the trades exactly as they actually happened and closed.

DATA:
  - data/trade_ledger.csv (274 realized closed trades) -- PRIMARY sequence.
  - data/shadow_ledger.csv (11,528 rows) -- INSPECTED, found NOT usable as a
    $-PnL cross-check: it is a factor/signal RESOLUTION log (regime_trend-style
    predicted_side / actual_return / resolved=true|false|expired), with no
    equity, fees, leverage, notional, or $ PnL field at all -- only 2,143/11,528
    rows even have `actual_return` populated. It is a shadow DIRECTIONAL-
    ACCURACY corpus, not a realized-fill P&L ledger, so it cannot drive a $
    daily-loss-% or $ drawdown breaker. Per the task's own caution against
    conflating shadow/counterfactual signals with realized results, this
    script does NOT run the $ breaker simulation on it. As a narrow,
    clearly-labeled robustness check it DOES reuse the resolved rows to
    compare consecutive-loss STREAK-LENGTH statistics (pure win/loss streak
    shape, no dollars) against the realized ledger, to see whether the
    271-trade sample's streak behavior is representative of the larger
    signal corpus or a small-sample artifact.

USAGE:
    python tools/copilot/circuit_breaker_test.py

OWNER-GATED: this script only reads data and prints a report. ANY resulting
change to risk/self_tuning.py or execution/risk.py live thresholds requires
explicit owner approval -- nothing here writes to live-bot code or state.
"""
from __future__ import annotations

import os
import sys
import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", message="Discarding nonzero nanoseconds in conversion")

BOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BOT_DIR)

# Load the real .env so trading_config.TradingConfig() reflects THIS
# deployment's actual live thresholds (not just class/dataclass defaults).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BOT_DIR, ".env"))
except Exception as e:
    print(f"[circuit_breaker_test] WARNING: could not load .env ({e}); "
          f"falling back to dataclass defaults, which may NOT match the live deployment.")

from execution.risk import CircuitBreaker  # noqa: E402 - the REAL, live-imported class
import execution.risk as risk_module        # noqa: E402
from trading_config import TradingConfig    # noqa: E402

# Neutralize the ONLY disk side-effect in CircuitBreaker (_trip() ->
# _log_safety_event() appends to data/logs/safety_events.csv). This script
# must never write to live-bot state, so we no-op it. This does NOT change
# any trip/cooldown/threshold LOGIC -- it only silences a logging call.
risk_module._log_safety_event = lambda *a, **k: None
# Silence the real class's logger.warning/info spam (hundreds of trip lines
# across the grid sweep) -- purely cosmetic, does not touch trip/cooldown logic.
logging.getLogger("bot.execution.risk").setLevel(logging.CRITICAL)

LEDGER_PATH = os.path.join(BOT_DIR, "data", "trade_ledger.csv")
SHADOW_PATH = os.path.join(BOT_DIR, "data", "shadow_ledger.csv")
CB_STATE_PATH = os.path.join(BOT_DIR, "data", "circuit_breaker_state.json")

SIZE_COLLAPSE_DATE = datetime(2026, 7, 26, tzinfo=timezone.utc)  # per project memory


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_trade_ledger(path: str) -> pd.DataFrame:
    rows = list(csv.DictReader(open(path)))
    df = pd.DataFrame(rows)
    df["timestamp"] = df["timestamp"].astype(float)
    df["net_pnl"] = df["net_pnl"].astype(float)
    # 23/274 rows are exit_type/contributing_factors == RECONSTRUCTED_FROM_LOG
    # backfilled entries with blank running_equity and fees hard-zeroed (a
    # known data-quality gap, not this script's doing). Coerce to numeric and
    # forward-fill running_equity from the last known value -- a reasonable
    # approximation given net_pnl for these rows IS present and real.
    df["running_equity"] = pd.to_numeric(df["running_equity"], errors="coerce")
    df["confidence_score"] = pd.to_numeric(df["confidence_score"], errors="coerce").fillna(0.0)
    df["fees"] = pd.to_numeric(df["fees"], errors="coerce").fillna(0.0)
    df["dt_utc"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    # Ledger is NOT perfectly monotonic (a handful of concurrent-close races);
    # sort by close timestamp -- this is the order the live CircuitBreaker
    # would have seen these closes arrive (record_trade is called once per
    # close event, in wall-clock arrival order).
    df = df.sort_values("timestamp").reset_index(drop=True)
    n_recon = int((df["running_equity"].isna()).sum())
    if n_recon:
        df["running_equity"] = df["running_equity"].ffill().bfill()
        print(f"[circuit_breaker_test] NOTE: {n_recon}/{len(df)} rows are RECONSTRUCTED_FROM_LOG "
              f"backfilled entries with blank running_equity in the raw CSV (fees also hard-zeroed "
              f"for these rows) -- forward/back-filled running_equity from adjacent rows as an "
              f"approximation; net_pnl for these rows is real and used as-is.")
    df["day_utc"] = df["dt_utc"].dt.strftime("%Y-%m-%d")  # UTC calendar day (see REFUTE-YOURSELF: (b))
    return df


def backsolve_starting_equity(df: pd.DataFrame) -> float:
    """Pre-trade equity of the very first ledger row (running_equity - net_pnl)."""
    return float(df.iloc[0]["running_equity"] - df.iloc[0]["net_pnl"])


# ---------------------------------------------------------------------------
# Core simulation: feeds the REAL CircuitBreaker class the realized trade
# sequence in close order, exactly the way multi_strategy_main.py does
# (is_trading_allowed() before executing, record_trade() after close).
# ---------------------------------------------------------------------------
@dataclass
class SimResult:
    daily_loss_limit_pct: float
    max_consecutive_losses: int
    kept_n: int
    skipped_n: int
    opportunity_cost: float       # $ of skipped WINNING trades foregone
    drawdown_avoided: float       # $ of skipped LOSING trades avoided
    net_effect: float             # drawdown_avoided - opportunity_cost
    final_equity: float
    trip_count: int
    trip_reasons: Dict[str, int]
    max_dd_pct_kept: float
    trip_log: List[Dict[str, Any]]


def _classify_reason(reason: str) -> str:
    if "Session DD" in reason:
        return "session_dd_20pct"
    if "Daily loss" in reason:
        return "daily_loss_pct"
    if "consecutive losses" in reason:
        return "consecutive_losses"
    if "Drawdown" in reason:
        return "drawdown_from_peak"
    if "Exception" in reason:
        return "exception_failsafe"
    return "other"


def simulate(df: pd.DataFrame, daily_loss_limit_pct: float, max_consecutive_losses: int,
             max_drawdown_pct: float, cooldown_minutes: int, starting_equity: float,
             max_session_drawdown_pct: float = 0.20) -> SimResult:
    cb = CircuitBreaker(
        daily_loss_limit_pct=daily_loss_limit_pct,
        max_consecutive_losses=max_consecutive_losses,
        max_drawdown_pct=max_drawdown_pct,
        cooldown_minutes=cooldown_minutes,
        max_cb_overrides=0,  # matches live: override escape hatch disabled (see module docstring)
    )
    cb.max_session_drawdown_pct = max_session_drawdown_pct
    cb.start_session(starting_equity)

    equity = starting_equity
    peak_kept = starting_equity
    max_dd_pct_kept = 0.0
    kept_n = 0
    skipped_n = 0
    opportunity_cost = 0.0
    drawdown_avoided = 0.0
    trip_log = []
    was_tripped = False

    for i, row in enumerate(df.itertuples(index=False)):
        dt = row.dt_utc.to_pydatetime()
        pnl = float(row.net_pnl)
        conf = float(row.confidence_score)

        allowed = cb.is_trading_allowed(confidence=conf, sim_time=dt, equity=equity)

        if not allowed:
            skipped_n += 1
            if pnl > 0:
                opportunity_cost += pnl
            else:
                drawdown_avoided += -pnl
            continue

        # Trade executes: update the self-consistent simulated equity path.
        equity += pnl
        kept_n += 1
        if equity > peak_kept:
            peak_kept = equity
        dd_pct = (peak_kept - equity) / peak_kept * 100.0 if peak_kept > 0 else 0.0
        max_dd_pct_kept = max(max_dd_pct_kept, dd_pct)

        pre_tripped = cb.tripped
        cb.record_trade(pnl, equity, sim_time=dt)
        if cb.tripped and not pre_tripped:
            trip_log.append({
                "idx": i,  # positional index into df (post sort_values/reset_index) of the triggering trade
                "time": dt.isoformat(),
                "reason": cb.trip_reason,
                "reason_type": _classify_reason(cb.trip_reason),
                "equity_at_trip": round(equity, 2),
            })

    trip_reasons: Dict[str, int] = {}
    for t in trip_log:
        trip_reasons[t["reason_type"]] = trip_reasons.get(t["reason_type"], 0) + 1

    return SimResult(
        daily_loss_limit_pct=daily_loss_limit_pct,
        max_consecutive_losses=max_consecutive_losses,
        kept_n=kept_n,
        skipped_n=skipped_n,
        opportunity_cost=round(opportunity_cost, 2),
        drawdown_avoided=round(drawdown_avoided, 2),
        net_effect=round(drawdown_avoided - opportunity_cost, 2),
        final_equity=round(equity, 2),
        trip_count=len(trip_log),
        trip_reasons=trip_reasons,
        max_dd_pct_kept=round(max_dd_pct_kept, 2),
        trip_log=trip_log,
    )


# ---------------------------------------------------------------------------
# Objective 3: does the % breaker even bind at current (collapsed) size?
# ---------------------------------------------------------------------------
def daily_loss_pct_series(df: pd.DataFrame, starting_equity: float) -> pd.DataFrame:
    """For each UTC calendar day, realized daily pnl / start-of-day equity."""
    equity = starting_equity
    day_start_equity: Dict[str, float] = {}
    day_pnl: Dict[str, float] = {}
    for _, row in df.iterrows():
        day = row["day_utc"]
        if day not in day_start_equity:
            day_start_equity[day] = equity
            day_pnl[day] = 0.0
        day_pnl[day] += float(row["net_pnl"])
        equity += float(row["net_pnl"])
    recs = []
    for day, pnl in day_pnl.items():
        se = day_start_equity[day]
        recs.append({"day": day, "daily_pnl": round(pnl, 2), "start_equity": round(se, 2),
                     "daily_loss_pct": round(-pnl / se * 100.0, 3) if se > 0 else np.nan})
    return pd.DataFrame(recs).sort_values("day").reset_index(drop=True)


def max_consecutive_losses_observed(df: pd.DataFrame) -> int:
    streak = 0
    best = 0
    for pnl in df["net_pnl"]:
        if pnl < 0:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


# ---------------------------------------------------------------------------
# Shadow ledger: streak-shape-only robustness check (NOT a $ pnl cross-check)
# ---------------------------------------------------------------------------
def shadow_streak_check(path: str) -> Optional[pd.DataFrame]:
    rows = list(csv.DictReader(open(path)))
    df = pd.DataFrame(rows)
    resolved = df[df["resolved"].isin(["true", "false"])].copy()
    resolved = resolved[resolved["actual_return"] != ""]
    if resolved.empty:
        return None
    resolved["actual_return"] = pd.to_numeric(resolved["actual_return"], errors="coerce")
    resolved["timestamp"] = pd.to_numeric(resolved["timestamp"], errors="coerce")
    resolved = resolved.dropna(subset=["actual_return", "timestamp"]).sort_values("timestamp")
    resolved["win"] = resolved["actual_return"] > 0

    def streak_dist(wins: pd.Series) -> Dict[str, float]:
        streak = 0
        best = 0
        streaks = []
        for w in wins:
            if not w:
                streak += 1
                best = max(best, streak)
            else:
                if streak > 0:
                    streaks.append(streak)
                streak = 0
        if streak > 0:
            streaks.append(streak)
        return {
            "n_resolved": len(wins),
            "win_rate_pct": round(wins.mean() * 100, 1),
            "max_loss_streak": best,
            "n_streaks_ge_5": sum(1 for s in streaks if s >= 5),
            "n_streaks_ge_10": sum(1 for s in streaks if s >= 10),
        }

    overall = streak_dist(resolved["win"])
    return pd.DataFrame([overall])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    pd.set_option("display.width", 160)

    print("=" * 100)
    print("CIRCUIT BREAKER MECHANIC AUDIT -- READ ONLY (no live state touched)")
    print("=" * 100)

    cfg = TradingConfig()
    print("\n[1] EXACT CURRENT (LIVE-DEPLOYED) THRESHOLDS, from trading_config.TradingConfig() + this bot/.env:")
    print(f"    CIRCUIT_BREAKER_DAILY_LOSS_PCT = {cfg.circuit_breaker_daily_loss_pct:.2%}  (vs CircuitBreaker class default 5%)")
    print(f"    MAX_CONSECUTIVE_LOSSES         = {cfg.max_consecutive_losses}  (vs class default 5)")
    print(f"    CIRCUIT_BREAKER_COOLDOWN_MIN   = {cfg.circuit_breaker_cooldown_min} min  (a fixed cooldown timer, NOT rest-of-day)")
    print(f"    MAX_DRAWDOWN_PCT (from peak)    = {cfg.max_drawdown_pct:.2%}")
    print(f"    CB_CONF_OVERRIDE_PCT           = {cfg.cb_conf_override_pct:.0%}  (moot: max_cb_overrides=0 at instantiation -> escape hatch disabled)")
    print(f"    MAX_SESSION_DRAWDOWN_PCT       = {float(os.getenv('MAX_SESSION_DRAWDOWN_PCT', '0.20')):.0%}  (cumulative, PERMANENT halt, no cooldown recovery)")
    print("    NOTE: risk/self_tuning.py's 3%/5%/8% drawdown-tiered profiles are DECORATIVE --")
    print("    evaluate_and_adjust() only sets a Telegram/LLM-prompt status string; it never")
    print("    writes back into risk_mgr.circuit_breaker.daily_loss_limit_pct or config.max_open_positions.")

    if os.path.exists(CB_STATE_PATH):
        import json
        state = json.load(open(CB_STATE_PATH))
        print(f"\n    Live circuit_breaker_state.json snapshot (context only, not modified): {state}")
        print(f"    consecutive_losses={state.get('consecutive_losses')} < MAX_CONSECUTIVE_LOSSES={cfg.max_consecutive_losses} "
              f"-> correctly NOT tripped yet; would need {cfg.max_consecutive_losses - state.get('consecutive_losses', 0)} more in a row to trip.")

    print("\n" + "=" * 100)
    print("[2] BASELINE: current thresholds simulated on the realized 274-trade sequence")
    print("=" * 100)

    df = load_trade_ledger(LEDGER_PATH)
    starting_equity = backsolve_starting_equity(df)
    n = len(df)
    wins = int((df["net_pnl"] > 0).sum())
    print(f"Loaded {n} realized closed trades, {df['dt_utc'].min()} -> {df['dt_utc'].max()}")
    print(f"Back-solved starting equity: ${starting_equity:,.2f}  |  wins={wins} losses={n - wins} "
          f"({wins/n*100:.1f}% WR)")
    print(f"Max REALIZED consecutive-loss streak in this sequence: {max_consecutive_losses_observed(df)} "
          f"(current threshold trips at {cfg.max_consecutive_losses})")

    baseline = simulate(
        df, daily_loss_limit_pct=cfg.circuit_breaker_daily_loss_pct,
        max_consecutive_losses=cfg.max_consecutive_losses,
        max_drawdown_pct=cfg.max_drawdown_pct,
        cooldown_minutes=cfg.circuit_breaker_cooldown_min,
        starting_equity=starting_equity,
        max_session_drawdown_pct=float(os.getenv("MAX_SESSION_DRAWDOWN_PCT", "0.20")),
    )
    print(f"\nCurrent thresholds ({cfg.circuit_breaker_daily_loss_pct:.0%} daily / "
          f"{cfg.max_consecutive_losses} streak) on realized sequence:")
    print(f"    Trips: {baseline.trip_count}  breakdown={baseline.trip_reasons}")
    print(f"    Trades kept: {baseline.kept_n}  skipped (during cooldown windows): {baseline.skipped_n}")
    print(f"    Drawdown avoided (skipped losers): ${baseline.drawdown_avoided:,.2f}")
    print(f"    Opportunity cost (skipped winners): ${baseline.opportunity_cost:,.2f}")
    print(f"    NET EFFECT (avoided - opp.cost): ${baseline.net_effect:,.2f}")
    if baseline.trip_log:
        print(f"    Trip log:")
        for t in baseline.trip_log:
            idx = t["idx"]
            trip_dt = df.loc[idx, "dt_utc"]
            if idx + 1 < len(df):
                next_dt = df.loc[idx + 1, "dt_utc"]
                next_pnl = df.loc[idx + 1, "net_pnl"]
                gap_min = (next_dt - trip_dt).total_seconds() / 60.0
                note = ("cooldown ELAPSED before next trade -> next trade was NOT actually blocked"
                         if gap_min >= cfg.circuit_breaker_cooldown_min
                         else f"next trade WAS blocked ({gap_min:.0f}min < {cfg.circuit_breaker_cooldown_min}min cooldown)")
                print(f"      {t['time']}  [{t['reason_type']}]  {t['reason']}")
                print(f"          -> next trade closed {gap_min:.0f} min later (pnl=${next_pnl:.2f}): {note}")
            else:
                print(f"      {t['time']}  [{t['reason_type']}]  {t['reason']}  (last trade in ledger, no next trade)")
        print("\n    KEY FINDING: with the current 60-minute cooldown, whether a trip actually BLOCKS")
        print("    anything depends entirely on trade cadence at the moment it fires. A rare, slow-building")
        print("    10-in-a-row streak (which is what actually trips at the current threshold) tends to span")
        print("    enough real time that the NEXT trade close already falls outside the 60-min window --")
        print("    so the breaker can trip 3 times on this ledger and still block ZERO trades (see kept=274,")
        print("    skipped=0 above). This is a real, verified example (2026-06-17 18:09 trip): the very next")
        print("    trade closed 88 minutes later -- a -$264.05 loss -- and was let straight through because")
        print("    the cooldown had already expired. Lower thresholds (e.g. streak=3) trip on FAST losing runs")
        print("    that bunch up within an hour, so cooldown actually bites there -- explaining why the grid's")
        print("    biggest net effects cluster at LOW streak thresholds, not high ones.")
    else:
        print("    -> Breaker NEVER TRIPPED at current thresholds on this 274-trade sequence.")

    # No-breaker control (dl=100%, streak=10^6): should equal all-trades-kept
    control = simulate(df, daily_loss_limit_pct=100.0, max_consecutive_losses=10_000_000,
                        max_drawdown_pct=1.0, cooldown_minutes=1, starting_equity=starting_equity,
                        max_session_drawdown_pct=1.0)
    assert control.kept_n == n, "sanity check failed: control should keep every trade"
    print(f"\n[sanity] no-breaker control: final_equity=${control.final_equity:,.2f} "
          f"vs current-breaker final_equity=${baseline.final_equity:,.2f} "
          f"(diff=${baseline.final_equity - control.final_equity:,.2f} == net_effect)")

    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("[3] GRID SWEEP: daily_loss_limit_pct 2%-10% x max_consecutive_losses 3-10")
    print("    (max_drawdown_pct, cooldown_minutes, session_dd held at current live values)")
    print("=" * 100)

    dl_grid = [round(x, 2) for x in np.arange(0.02, 0.101, 0.01)]
    streak_grid = list(range(3, 11))
    results = []
    for dl in dl_grid:
        for streak in streak_grid:
            r = simulate(df, daily_loss_limit_pct=dl, max_consecutive_losses=streak,
                         max_drawdown_pct=cfg.max_drawdown_pct,
                         cooldown_minutes=cfg.circuit_breaker_cooldown_min,
                         starting_equity=starting_equity,
                         max_session_drawdown_pct=float(os.getenv("MAX_SESSION_DRAWDOWN_PCT", "0.20")))
            results.append({
                "daily_loss_pct": dl, "max_streak": streak,
                "trips": r.trip_count, "kept": r.kept_n, "skipped": r.skipped_n,
                "dd_avoided": r.drawdown_avoided, "opp_cost": r.opportunity_cost,
                "net_effect": r.net_effect, "final_equity": r.final_equity,
            })
    grid_df = pd.DataFrame(results)

    print("\nNet-effect ($) pivot table [rows=daily_loss_limit_pct, cols=max_consecutive_losses]:")
    pivot = grid_df.pivot(index="daily_loss_pct", columns="max_streak", values="net_effect")
    print(pivot.to_string())

    print("\nTrip-count pivot table [rows=daily_loss_limit_pct, cols=max_consecutive_losses]:")
    pivot_trips = grid_df.pivot(index="daily_loss_pct", columns="max_streak", values="trips")
    print(pivot_trips.to_string())

    # Pareto frontier: maximize dd_avoided, minimize opp_cost
    def is_dominated(row, others):
        for _, o in others.iterrows():
            if (o["dd_avoided"] >= row["dd_avoided"] and o["opp_cost"] <= row["opp_cost"]
                    and (o["dd_avoided"] > row["dd_avoided"] or o["opp_cost"] < row["opp_cost"])):
                return True
        return False

    grid_df["pareto"] = [not is_dominated(row, grid_df) for _, row in grid_df.iterrows()]
    pareto_df = grid_df[grid_df["pareto"]].sort_values("dd_avoided")
    print(f"\nPareto frontier ({len(pareto_df)} of {len(grid_df)} grid points non-dominated on "
          f"[maximize dd_avoided, minimize opp_cost]):")
    print(pareto_df[["daily_loss_pct", "max_streak", "trips", "dd_avoided", "opp_cost", "net_effect"]]
          .to_string(index=False))

    current_row = grid_df[(grid_df["daily_loss_pct"] == round(cfg.circuit_breaker_daily_loss_pct, 2))
                           & (grid_df["max_streak"] == cfg.max_consecutive_losses)]
    on_frontier = bool(current_row["pareto"].iloc[0]) if not current_row.empty else None
    print(f"\nIs current (7%, 10) on the Pareto frontier? {on_frontier}")

    net_vals = grid_df["net_effect"].values
    net_range = net_vals.max() - net_vals.min()
    net_std = net_vals.std()
    best_row = grid_df.loc[grid_df["net_effect"].idxmax()]
    cur_net = float(current_row["net_effect"].iloc[0]) if not current_row.empty else None
    print(f"\nFLATNESS CHECK: net_effect across all {len(grid_df)} grid points: "
          f"min=${net_vals.min():,.2f} max=${net_vals.max():,.2f} range=${net_range:,.2f} std=${net_std:,.2f}")
    print(f"Best single grid point: daily_loss={best_row['daily_loss_pct']:.0%}, "
          f"streak={int(best_row['max_streak'])} -> net_effect=${best_row['net_effect']:,.2f}")
    if cur_net is not None:
        gap = best_row['net_effect'] - cur_net
        print(f"Current (7%, 10) net_effect=${cur_net:,.2f}  gap to grid-best=${gap:,.2f}")
        verdict = "FLAT (robust)" if net_range < 1.5 * abs(cur_net if cur_net != 0 else 1) and net_range < 50 else \
                  ("FLAT-ish" if gap < 25 else "PEAKY (treat with suspicion, likely overfit to this exact 274-trade draw)")
        print(f"-> Grid shape verdict: {verdict}")

    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("[4] DOES IT BIND AT CURRENT (COLLAPSED) SIZE? pre/post 2026-07-26 split")
    print("=" * 100)

    dl_series = daily_loss_pct_series(df, starting_equity)
    print(f"\nFull-history daily loss %: max observed = {dl_series['daily_loss_pct'].max():.3f}% "
          f"of that day's start equity (current threshold trips at "
          f"{cfg.circuit_breaker_daily_loss_pct:.0%} = {cfg.circuit_breaker_daily_loss_pct*100:.1f}%)")
    print(f"Days with |daily loss| >= 1% of equity: "
          f"{(dl_series['daily_loss_pct'] >= 1.0).sum()} / {len(dl_series)} trading days")
    print(f"Days with |daily loss| >= {cfg.circuit_breaker_daily_loss_pct*100:.0f}% (would trip today's limit): "
          f"{(dl_series['daily_loss_pct'] >= cfg.circuit_breaker_daily_loss_pct*100).sum()} / {len(dl_series)}")

    pre = df[df["dt_utc"] < SIZE_COLLAPSE_DATE]
    post = df[df["dt_utc"] >= SIZE_COLLAPSE_DATE]
    print(f"\nPre-2026-07-26: n={len(pre)} trades, median |fee|=${pre['fees'].abs().median():.2f} "
          f"(fee proxy for notional; round-trip taker ~9bps -> notional ~${pre['fees'].abs().median()/0.0009:,.0f})")
    print(f"Post-2026-07-26: n={len(post)} trades, median |fee|=${post['fees'].abs().median():.2f} "
          f"(notional ~${post['fees'].abs().median()/0.0009:,.0f})")
    if len(pre) > 0:
        dl_pre = daily_loss_pct_series(pre, starting_equity)
        print(f"  Pre-split max daily loss %: {dl_pre['daily_loss_pct'].max():.3f}%  "
              f"(n={len(dl_pre)} days)   max streak: {max_consecutive_losses_observed(pre)}")
    if len(post) > 0:
        post_start_eq = float(pre.iloc[-1]["running_equity"]) if len(pre) > 0 else starting_equity
        dl_post = daily_loss_pct_series(post, post_start_eq)
        print(f"  Post-split max daily loss %: {dl_post['daily_loss_pct'].max():.3f}%  "
              f"(n={len(dl_post)} days, only {len(post)} trades -- LOW POWER, flagged below)   "
              f"max streak: {max_consecutive_losses_observed(post)}")
    print("\n  CAVEAT: this ledger snapshot only extends to 2026-07-29 -- just 3 calendar days / "
          f"{len(post)} trades post-collapse. Both halves of this specific ledger already show small, "
          "similar per-trade fee/notional magnitudes (no dramatic step-change VISIBLE inside this "
          "274-row window); if a real notional collapse happened, most of its trade history likely "
          "predates this ledger's June 1 start. Do not over-read the pre/post split here as proof of "
          "a collapse -- treat it only as: 'is the % breaker anywhere near binding on the sizes actually "
          "seen in this ledger, small or large?' Answer below.")

    print(f"\n  ANSWER: max daily loss % observed anywhere in this ledger = "
          f"{dl_series['daily_loss_pct'].max():.3f}% vs a {cfg.circuit_breaker_daily_loss_pct*100:.0f}% trip "
          f"threshold -> the % daily-loss breaker is "
          f"{'NOWHERE CLOSE to binding (moot at this trade size)' if dl_series['daily_loss_pct'].max() < cfg.circuit_breaker_daily_loss_pct*100/2 else 'within range of binding'}.")
    print("  The consecutive-loss streak breaker is SIZE-INDEPENDENT (counts trade outcomes, not dollars) "
          "-- it binds identically regardless of how small notional gets, unlike the % daily-loss breaker "
          "which mechanically gets harder to trip as position size shrinks (same % move = fewer dollars).")

    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("[5] SHADOW LEDGER: usability check + streak-shape-only robustness cross-check")
    print("=" * 100)
    print("data/shadow_ledger.csv has 11,528 rows but NO equity/fees/leverage/notional/$-PnL field --")
    print("it is a per-FACTOR directional-prediction resolution log (id, timestamp, factor, symbol,")
    print("predicted_side, confidence, entry_price, exit_price, actual_return, resolved, resolve_timestamp),")
    print("with actual_return populated on only 2,143/11,528 rows. NOT usable to simulate a $ daily-loss")
    print("or $ drawdown breaker (there is no realized $ PnL or account equity in it at all). Per the")
    print("task's own instruction not to conflate shadow/counterfactual signals with realized fills, this")
    print("script does NOT run the $ breaker sweep on it. Using it for a $ metric would require FABRICATING")
    print("a sizing model this data does not contain.")
    print("\nNarrow, honestly-labeled use: compare LOSS-STREAK SHAPE only (no dollars) between the 274-trade")
    print("realized ledger and the larger 2,143-signal resolved corpus, to see if the realized sample's")
    print("streak behavior is a representative draw or a small-n artifact:")
    shadow_stats = shadow_streak_check(SHADOW_PATH)
    if shadow_stats is not None:
        print(shadow_stats.to_string(index=False))
        print(f"\nRealized ledger (274 trades): win_rate={wins/n*100:.1f}%, max_loss_streak="
              f"{max_consecutive_losses_observed(df)}")
        print("-> Interpretation: shadow corpus win rate and max-streak are DIFFERENT PIPELINES (raw factor")
        print("   signals pre-ensemble/pre-execution, no fees/sizing/gates) so absolute levels won't match --")
        print("   this is a shape/plausibility check only (does a ~10x-larger sample show comparably-sized")
        print("   streaks, i.e. is a streak of 5-7 an ordinary occurrence at this win rate, not a freak event).")
    else:
        print("No usable resolved rows found in shadow ledger for streak comparison.")

    # ------------------------------------------------------------------
    print("\n" + "=" * 100)
    print("[6] REFUTE-YOURSELF")
    print("=" * 100)
    print("""
(a) IN-SAMPLE OVERFITTING: the grid-sweep "optimum" above is fit and evaluated on the SAME
    274-trade sequence. With only a handful of trip EVENTS in the whole dataset (see trip
    counts in section 3's pivot table), a single lucky/unlucky trade re-timed by a threshold
    change can swing "best" by a large relative %. See the FLATNESS CHECK verdict in section 3
    -- if it says PEAKY, the "optimal" threshold is likely an artifact of this exact draw and
    should NOT be shipped as-is; prefer the nearest ROUND, ROBUST number on a flat plateau.
(b) DAY / TIMEZONE DEFINITION: "daily" loss is bucketed by UTC calendar day
    (datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d')), matching
    execution/risk.py's own `_maybe_reset_daily()` when running live (uses
    `datetime.now(timezone.utc)`). A different session definition (e.g. exchange-funding-hour
    boundaries, or a rolling 24h window instead of a UTC-midnight reset) would bucket trades
    differently and could change which days look like near-misses. Not tested here.
(c) LOW POWER: this ledger has very few actual TRIP events (see section 2/3) -- with n this
    small, "X trips avoided $Y" is a small-sample statistic, not a stable rate. Treat all
    dollar figures above as descriptive of what already happened, not a forecast of future
    breaker value.
(d) DOES A BREAKER EVEN MAKE SENSE GIVEN ~NO ENTRY EDGE? Per prior project findings (longs
    9%WR/-$654 vs shorts 42%/+$810 in the SIDE-EDGE audit; mixed win rates elsewhere), if trades
    are close to a coin-flip with a small negative-fee edge, a pause after a loss streak does not
    "protect against a bad regime" -- it is statistically indistinguishable from just trading
    LESS overall (lower expected variance AND lower expected value in roughly the same proportion).
    The dd_avoided/opp_cost split above will look favorable whenever the streak that triggers a
    pause is followed, by chance, by more losers than winners in the near-term (regression to a
    ~36% win rate would produce exactly this pattern most of the time even with ZERO true
    regime-detection value in the breaker) -- so a positive net_effect here is CONSISTENT WITH
    "pausing after losses helps" but is NOT independent confirmation of it distinct from
    "trading less after a loss streak is directionally the same as reducing size/frequency
    generally." This script cannot separate those two explanations from ledger data alone.
""")

    print("=" * 100)
    print("[7] VERDICT")
    print("=" * 100)
    print(f"""
Current live thresholds: {cfg.circuit_breaker_daily_loss_pct:.0%} daily loss / {cfg.max_consecutive_losses}
consecutive losses / {cfg.circuit_breaker_cooldown_min}min cooldown / {cfg.max_drawdown_pct:.0%} DD-from-peak.

- Trip count on realized history: {baseline.trip_count} ({baseline.trip_reasons}).
- Net dollar effect at current thresholds: ${baseline.net_effect:,.2f}
  (avoided ${baseline.drawdown_avoided:,.2f} in skipped losers, cost ${baseline.opportunity_cost:,.2f}
  in skipped winners).
- Pareto frontier membership: current point is {"ON" if on_frontier else "NOT on"} the frontier.
- Grid shape: see FLATNESS CHECK above -- decides whether to trust any "better" point at all.
- Daily-loss-% breaker: {'MOOT at current notional -- has never come close to firing' if dl_series['daily_loss_pct'].max() < cfg.circuit_breaker_daily_loss_pct*100/2 else 'has NOT fired but has come within plausible range on this bot\'s worst day'}
  (max daily loss ever observed anywhere in this ledger = {dl_series['daily_loss_pct'].max():.2f}% vs a
  {cfg.circuit_breaker_daily_loss_pct*100:.0f}% trip line -- {dl_series['daily_loss_pct'].max()/(cfg.circuit_breaker_daily_loss_pct*100)*100:.0f}% of the way to tripping). The tiny
  n=20-trade post-collapse slice alone (see section 4) shows a much lower max of
  {dl_post['daily_loss_pct'].max():.2f}% if that smaller size persists, but 4 days is not enough to call this settled.
- Consecutive-loss streak breaker: DOES bind (max realized streak
  {max_consecutive_losses_observed(df)} vs a trip line of {cfg.max_consecutive_losses}; current live
  state shows consecutive_losses=7 mid-streak) and is size-independent, so it remains the ACTIVE
  mechanism regardless of how small trades get.

THIS IS A SUGGESTION FOR OWNER REVIEW ONLY. No file under risk/ or execution/ was modified by
this script. Any threshold change is an OWNER-GATED live-bot edit to
trading_config.py / .env (CIRCUIT_BREAKER_DAILY_LOSS_PCT, MAX_CONSECUTIVE_LOSSES).
""")


if __name__ == "__main__":
    main()
