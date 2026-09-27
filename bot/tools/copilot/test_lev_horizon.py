#!/usr/bin/env python
"""
test_lev_horizon.py - focused tests for the HORIZON-AWARE, side-specific
leverage-guidance fix in copilot.py (v2.5 - see that module's docstring
"HORIZON-AWARE LEVERAGE" and tools/copilot/lev_band_horizon_test.py, whose
already-OOS-validated sliding-window adverse-excursion logic this
implements). Deterministic, synthetic OHLC only - no network calls, no
live-bot imports (matches copilot.py's own read-only/standalone contract).

Run: pytest tools/copilot/test_lev_horizon.py -v
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

from copilot import (  # noqa: E402
    HORIZON_TAIL_MIN_SAMPLE,
    compute_liquidation,
    compute_realized_vol,
)


def _make_df(n: int, seed: int, daily_vol: float = 0.03, drift: float = 0.0, start: float = 100.0) -> pd.DataFrame:
    """Synthetic daily OHLC: a random walk with real intrabar high/low (wider
    than the close-to-close move) so the max-adverse-excursion logic has
    something real to bite on, independent of the close-only single-day
    stat."""
    rng = np.random.RandomState(seed)
    rets = rng.normal(drift, daily_vol, size=n)
    close = start * np.cumprod(1.0 + rets)
    open_ = np.concatenate([[start], close[:-1]])
    intrabar = np.abs(rng.normal(0.0, daily_vol * 1.5, size=n))
    high = np.maximum(open_, close) + intrabar
    low = np.minimum(open_, close) - intrabar
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"t": dates, "o": open_, "h": high, "l": low, "c": close})


VOLATILE_N = 260  # comfortably clears HORIZON_TAIL_MIN_SAMPLE (20) for H in (3, 5)
THIN_N = 22       # too thin for ANY horizon calibration, but enough for pct95_daily_drop_pct (n>=20 close returns)


def test_hold_days_5_lowers_safe_leverage_vs_none():
    """(a) For a volatile coin, calling compute_liquidation with hold_days=5
    must yield a safe_max_leverage <= the hold_days=None (single-day) call -
    the whole point of the fix is that a multi-day hold faces a bigger
    adverse-excursion tail than a single day, so the honest safe leverage is
    lower, not higher."""
    df = _make_df(VOLATILE_N, seed=1, daily_vol=0.05)
    vol = compute_realized_vol(df)
    assert vol.pct95_daily_drop_pct is not None
    assert (5, "LONG") in vol.horizon_tail_pct, "calibration should exist for this sample size"

    entry = float(df["c"].iloc[-1])
    lr_1d = compute_liquidation(entry, "LONG", 1.0, vol, hl_max_leverage=None, symbol="TESTVOL")
    lr_5d = compute_liquidation(entry, "LONG", 1.0, vol, hl_max_leverage=None, symbol="TESTVOL", hold_days=5.0)

    assert lr_5d.horizon_used == 5.0
    assert lr_1d.horizon_used is None
    assert lr_5d.safe_max_leverage <= lr_1d.safe_max_leverage
    # single_day_safe_max_leverage on the horizon-aware read should equal the
    # plain single-day read's safe_max_leverage (same formula, same inputs).
    assert lr_5d.single_day_safe_max_leverage == pytest.approx(lr_1d.safe_max_leverage)


def test_fail_soft_missing_calibration_falls_back_to_single_day():
    """(b) With too little history for ANY horizon calibration (but enough
    for the pre-existing single-day pct95 stat), passing hold_days must not
    crash and must reproduce the EXACT single-day number - no regression for
    thin-history symbols."""
    df = _make_df(THIN_N, seed=2, daily_vol=0.04)
    vol = compute_realized_vol(df)
    assert vol.pct95_daily_drop_pct is not None, "sanity: single-day stat should still be available"
    assert vol.horizon_tail_pct == {}, "sanity: this sample size should be too thin for any (H, side) calibration"

    entry = float(df["c"].iloc[-1])
    lr_none = compute_liquidation(entry, "LONG", 1.0, vol, hl_max_leverage=None, symbol="THIN")
    lr_5d = compute_liquidation(entry, "LONG", 1.0, vol, hl_max_leverage=None, symbol="THIN", hold_days=5.0)

    assert lr_5d.horizon_used is None
    assert lr_5d.single_day_safe_max_leverage is None
    assert lr_5d.safe_max_leverage == pytest.approx(lr_none.safe_max_leverage)
    assert lr_5d.risk_reason == lr_none.risk_reason or "SINGLE-DAY" in lr_5d.risk_reason


def test_long_and_short_horizon_tails_can_differ():
    """(c) In a strong, real downtrend, LONG's H-day drawdown tail should be
    materially worse than SHORT's H-day run-up tail (a downtrend rarely
    spikes hard against a short), so the horizon-aware safe leverage must
    differ by side - the whole point of making the fix side-specific instead
    of reusing one "worst day" number for both sides."""
    df = _make_df(VOLATILE_N, seed=3, daily_vol=0.04, drift=-0.01)
    vol = compute_realized_vol(df)
    assert (5, "LONG") in vol.horizon_tail_pct
    assert (5, "SHORT") in vol.horizon_tail_pct

    long_tail = vol.horizon_tail_pct[(5, "LONG")]
    short_tail = vol.horizon_tail_pct[(5, "SHORT")]
    assert long_tail != pytest.approx(short_tail)
    assert long_tail > short_tail, "in a real downtrend, LONG's drawdown tail should exceed SHORT's run-up tail"

    entry = float(df["c"].iloc[-1])
    lr_long = compute_liquidation(entry, "LONG", 1.0, vol, hl_max_leverage=None, symbol="ASYM", hold_days=5.0)
    lr_short = compute_liquidation(entry, "SHORT", 1.0, vol, hl_max_leverage=None, symbol="ASYM", hold_days=5.0)
    assert lr_long.horizon_used == 5.0
    assert lr_short.horizon_used == 5.0
    assert lr_long.safe_max_leverage < lr_short.safe_max_leverage


def test_horizon_used_snaps_to_nearest_calibrated_h():
    """(d) horizon_used must snap hold_days to the nearest calibrated
    horizon (3 or 5 today), not silently interpolate or error."""
    df = _make_df(VOLATILE_N, seed=4, daily_vol=0.05)
    vol = compute_realized_vol(df)
    assert (3, "LONG") in vol.horizon_tail_pct
    assert (5, "LONG") in vol.horizon_tail_pct
    entry = float(df["c"].iloc[-1])

    lr_3 = compute_liquidation(entry, "LONG", 1.0, vol, None, "SNAP", hold_days=3.0)
    lr_5 = compute_liquidation(entry, "LONG", 1.0, vol, None, "SNAP", hold_days=5.0)
    lr_near3 = compute_liquidation(entry, "LONG", 1.0, vol, None, "SNAP", hold_days=3.4)
    lr_near5 = compute_liquidation(entry, "LONG", 1.0, vol, None, "SNAP", hold_days=4.9)

    assert lr_3.horizon_used == 3.0
    assert lr_5.horizon_used == 5.0
    assert lr_near3.horizon_used == 3.0
    assert lr_near5.horizon_used == 5.0


def test_horizon_aware_risk_reason_mentions_4pct_not_old_disclaimer():
    """Moat check: when a horizon override actually applies, the printed
    risk_reason must carry the OOS-validated ~4% figure as THIS band's own
    risk (not a repeat of the old blanket '~25-40%' claim about itself,
    though it may honestly CONTRAST against that old number for context) -
    and it must differ from the plain single-day-only disclaimer text."""
    df = _make_df(VOLATILE_N, seed=5, daily_vol=0.04)
    vol = compute_realized_vol(df)
    entry = float(df["c"].iloc[-1])
    # Use the horizon-aware safe leverage itself so the SAFE branch fires.
    probe = compute_liquidation(entry, "LONG", 1.0, vol, None, "MOAT", hold_days=5.0)
    lr = compute_liquidation(entry, "LONG", probe.safe_max_leverage, vol, None, "MOAT", hold_days=5.0)
    assert lr.risk_label == "SAFE"
    assert lr.horizon_used == 5.0
    assert "OOS-measured liquidation risk at this horizon is ~4%" in lr.risk_reason
    assert "HORIZON-AWARE" in lr.risk_reason

    # The single-day-only fallback path (no hold_days) must still honestly
    # disclose the multi-day risk: it frames the number as a SINGLE-DAY ceiling
    # and warns that holding it 3-5d liquidated ~25-40% OOS (exact wording is
    # consolidated to read consistently beside the dual-number RANGE line;
    # assert the concept, not a brittle substring).
    probe_1d = compute_liquidation(entry, "LONG", 1.0, vol, None, "MOAT")
    lr_1d = compute_liquidation(entry, "LONG", probe_1d.safe_max_leverage, vol, None, "MOAT")
    if lr_1d.risk_label == "SAFE":
        assert "25-40%" in lr_1d.risk_reason
        assert "SINGLE-DAY" in lr_1d.risk_reason
        assert "HORIZON-AWARE" not in lr_1d.risk_reason  # this is the 1-day path
        assert "~4%" not in lr_1d.risk_reason
        assert lr_1d.risk_reason != lr.risk_reason


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
