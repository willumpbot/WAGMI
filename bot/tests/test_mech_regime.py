"""Tests for the RQ10 mechanical regime overlay (llm/agents/mech_regime.py).

The overlay is additive INPUT for the Regime agent: it must classify
deterministically from candles, degrade gracefully on short/garbage data,
and appear in the Regime agent's input only when the snapshot carries it.
"""
import math
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llm.agents.mech_regime import (  # noqa: E402
    compute_mech_regime,
    format_mech_regime,
)


def _bar(ts, o, h, l, c, v=100.0):
    return [ts, o, h, l, c, v]


def _make_trend(n=500, start=100.0, step=0.5):
    """Monotonic uptrend: every bar makes a higher high/low — ADX pins high."""
    bars = []
    px = start
    for i in range(n):
        o = px
        c = px + step
        bars.append(_bar(i, o, max(o, c) + 0.05, min(o, c) - 0.05, c))
        px = c
    return bars


def _make_range(n=500, base=100.0):
    """Alternating up/down bars, no net direction, slowly contracting range.

    Amplitude decays over time so the final bar's ATR%-percentile is LOW
    (constant amplitude would tie at ptile 1.0 by the <= estimator).
    """
    bars = []
    for i in range(n):
        up = i % 2 == 0
        amp = 0.6 - 0.4 * (i / max(n - 1, 1))  # 0.6 -> 0.2
        o = base
        c = base + (amp if up else -amp)
        bars.append(_bar(i, o, max(o, c) + 0.1, min(o, c) - 0.1, c))
    return bars


def _make_vol_spike(n=500, base=100.0):
    """Quiet range then a violent final stretch — ATR ptile must hit >= 0.90."""
    bars = _make_range(n - 20, base)
    px = base
    for i in range(20):
        o = px
        c = px + (8.0 if i % 2 == 0 else -8.0)
        bars.append(_bar(n - 20 + i, o, max(o, c) + 4.0, min(o, c) - 4.0, c))
        px = c
    return bars


class TestComputeMechRegime:
    def test_uptrend_classifies_trending_bull(self):
        out = compute_mech_regime(_make_trend())
        assert out is not None
        assert out["label"] == "trending_bull"
        assert out["adx"] >= 25.0
        assert out["di_plus"] > out["di_minus"]

    def test_downtrend_classifies_trending_bear(self):
        # Decaying-amplitude decline: ADX pins high (all bear bars) while
        # ATR% falls, so the ptile stays low and ADX decides -> trending_bear.
        # (A constant-step crash correctly reads high_volatility instead:
        # ATR% percentile climbs as price falls — that is the RQ10 method.)
        bars = []
        px = 1000.0
        n = 500
        for i in range(n):
            o = px
            c = px - (1.0 - 0.6 * i / (n - 1))  # step decays 1.0 -> 0.4
            bars.append(_bar(i, o, max(o, c) + 0.05, min(o, c) - 0.05, c))
            px = c
        out = compute_mech_regime(bars)
        assert out is not None
        assert out["label"] == "trending_bear"
        assert out["adx"] >= 25.0
        assert out["di_minus"] > out["di_plus"]

    def test_flat_range_classifies_ranging(self):
        out = compute_mech_regime(_make_range())
        assert out is not None
        assert out["label"] == "ranging"
        assert out["adx"] < 25.0

    def test_vol_spike_classifies_high_volatility(self):
        out = compute_mech_regime(_make_vol_spike())
        assert out is not None
        assert out["label"] == "high_volatility"
        assert out["atr_ptile"] is not None and out["atr_ptile"] >= 0.90

    def test_short_history_returns_none(self):
        assert compute_mech_regime(_make_trend(n=10)) is None

    def test_garbage_input_returns_none(self):
        assert compute_mech_regime(None) is None
        assert compute_mech_regime([]) is None
        assert compute_mech_regime([[1, 2]]) is None
        assert compute_mech_regime("not candles") is None

    def test_short_ptile_history_omits_high_vol(self):
        # Enough bars for ADX but < 100 trailing atr_pct samples:
        # ptile must be None (no fake high_vol claims on thin history).
        out = compute_mech_regime(_make_trend(n=60))
        assert out is not None
        assert out["atr_ptile"] is None

    def test_all_values_finite(self):
        out = compute_mech_regime(_make_vol_spike())
        for key in ("adx", "di_plus", "di_minus", "atr_pct"):
            assert math.isfinite(out[key])


class TestFormatMechRegime:
    def test_format_contains_label_and_disclaimer(self):
        out = compute_mech_regime(_make_trend())
        text = format_mech_regime(out)
        assert "mechanical classifier reads: trending_bull" in text
        assert "ADX=" in text and "ATR ptile=" in text
        assert "not an override" in text

    def test_format_handles_missing_ptile(self):
        text = format_mech_regime({"label": "ranging", "adx": 12.0,
                                   "di_plus": 10, "di_minus": 11,
                                   "atr_pct": 0.4, "atr_ptile": None,
                                   "n_bars": 60})
        assert "n/a(short history)" in text


class TestRegimeInputInjection:
    def test_build_regime_input_includes_mech_when_present(self):
        from llm.agents.coordinator import AgentCoordinator
        mech = compute_mech_regime(_make_trend())
        snapshot = {"m": [{"s": "BTC", "p": 60000}], "g": {"eq": 500},
                    "mech_regime": mech}
        dummy = SimpleNamespace(_perf_tracker_ref=None)
        out = AgentCoordinator._build_regime_input(dummy, snapshot)
        assert "mechanical_classifier" in out
        assert "trending_bull" in out

    def test_build_regime_input_omits_mech_when_absent(self):
        from llm.agents.coordinator import AgentCoordinator
        snapshot = {"m": [{"s": "BTC", "p": 60000}], "g": {"eq": 500}}
        dummy = SimpleNamespace(_perf_tracker_ref=None)
        out = AgentCoordinator._build_regime_input(dummy, snapshot)
        assert "mechanical_classifier" not in out
