"""PAPER_STOP_INTRABAR: paper stops fill where a resting exchange stop would have (2026-10-16 ETH incident).

Owner ETH SHORT, entry 2419.41, stop 2472. HL 5m bars: 11:05Z high 2469.7, 11:10Z high 2492.9. The bot's price
was stuck at 2469.25 from ~11:07 to ~11:22 (latest_price served a 900s-old cache entry) and the stop only fired at
11:24:31 "SL @ 2483.45" -> -1.26R. With the flag on, the 11:11 check sees the 11:10 bar cross 2472 and fills AT
2472, timestamped 11:10. Flag off: byte-identical to today. Also: the stale-price root cause (fetcher price ttl).
"""
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

BOT = Path(__file__).resolve().parent.parent
if str(BOT) not in sys.path:
    sys.path.insert(0, str(BOT))

from core import owner_plan_exec as ope  # noqa: E402
from execution import paper_stop_fidelity as psf  # noqa: E402
from execution.position_manager import PositionManager, Position  # noqa: E402


def T(hhmm: str, sec: int = 0) -> float:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(2026, 10, 16, h, m, sec, tzinfo=timezone.utc).timestamp()


class Bars:
    """Fake 5m-bar provider. `bars` maps bar start -> (o, h, l, c) AS KNOWN NOW (a test edits the forming bar
    between ticks). Records every call."""

    def __init__(self):
        self.bars = {}
        self.calls = []
        self.fail = False

    def __call__(self, symbol, start_s, end_s=None):
        self.calls.append((symbol, start_s, end_s))
        if self.fail:
            return None
        return [(t, *v) for t, v in sorted(self.bars.items()) if t + psf.BAR_S > start_s and t <= (end_s or 1e18)]


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "hivemind").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    import core.paths as paths
    monkeypatch.setattr(paths, "DATA_DIR", data)
    monkeypatch.setattr(ope, "HM_DIR", data / "hivemind")
    monkeypatch.setenv("PNL_LEVERAGE_FIX", "true")
    for k in ("OWNER_PLAN_EXIT_MODE_DEFAULT", "OWNER_PLAN_EXIT_MODE_FORCE", "BREAKEVEN_RATCHET", "OWNER_RUNNER_STYLE",
              "OWNER_LADDER_STYLE", "SL_FILL_FIDELITY_FIX", "PAPER_STOP_INTRABAR", "PAPER_STOP_INTRABAR_MAX_LOOKBACK_S"):
        monkeypatch.delenv(k, raising=False)
    return data


@pytest.fixture
def clock(monkeypatch):
    c = {"now": T("11:07", 16)}
    monkeypatch.setattr(psf, "now_s", lambda: c["now"])
    return c


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("PAPER_STOP_INTRABAR", "true")


def _eth_short(owner=True, exit_style=None):
    er = {}
    if owner:
        er = {"owner_plan_id": "eth1", "owner_trade": True, "exit_mode": "profits_only", "plan_max_hold_h": 48}
        if exit_style:
            er["exit_style"] = exit_style
    p = Position(symbol="ETH", side="SHORT", entry=2419.41, qty=0.191, sl=2472.0, tp1=2366.82, tp2=2300.0,
                 strategy=ope.OWNER_STRATEGY if owner else "llm_first", entry_reasons=er)
    p._transition("OPEN")
    p.highest_price = p.lowest_price = 2419.41
    p.open_time = datetime(2026, 10, 15, 15, 20, tzinfo=timezone.utc)
    return p


def _pm(pos, bars=None):
    pm = PositionManager()
    pm.positions[pos.symbol] = pos
    pm.intrabar_bars_provider = bars
    return pm


def _incident_bars(b: Bars, upto: str):
    """HL 5m ETH bars around the incident, as known at `upto` (the forming bar is partial)."""
    b.bars = {T("11:00"): (2458.0, 2462.5, 2455.0, 2461.0)}
    if upto == "11:07":
        b.bars[T("11:05")] = (2461.0, 2469.7, 2460.0, 2469.25)          # forming
    else:
        b.bars[T("11:05")] = (2461.0, 2469.7, 2460.0, 2469.4)
        b.bars[T("11:10")] = (2469.4, 2492.9, 2468.0, 2486.0)          # crosses 2472


# ── the incident ───────────────────────────────────────────────────────────

def test_eth_incident_replay_fills_2472_at_the_1110_bar(sandbox, on, clock):
    pos = _eth_short()
    bars = Bars()
    pm = _pm(pos, bars)
    _incident_bars(bars, "11:07")
    assert pm.update_price("ETH", 2469.25) == []                       # 11:07: below the stop, anchors
    clock["now"] = T("11:11", 41)
    _incident_bars(bars, "11:11")
    ev = pm.update_price("ETH", 2469.25)                               # the STALE price the bot saw
    assert [e.action for e in ev] == ["SL"]
    e = ev[0]
    assert e.price == pytest.approx(2472.0) and e.is_position_close
    assert e.timestamp == datetime(2026, 10, 16, 11, 10, tzinfo=timezone.utc)
    assert e.metadata["intrabar_fill"] and e.metadata["intrabar_bar_ts"].startswith("2026-10-16T11:10")
    assert pos.close_time == datetime(2026, 10, 16, 11, 10, tzinfo=timezone.utc)
    risk = (2472.0 - 2419.41) * 0.191
    r = (pos.realized_pnl) / risk
    assert -1.06 < r < -1.0, r                                         # ~-1R (fees), not -1.26R
    # the record the owner sees: exit at the stop, fill_ts at the bar
    row = ope.record_owner_close(e, pos, pm)
    assert row["exit"] == pytest.approx(2472.0) and row["reason"] == "SL" and row["kind"] == "final"
    assert row["intrabar_fill"] is True and row["fill_ts"].startswith("2026-10-16T11:10")
    assert row["total_r"] > -1.06


def test_eth_incident_flag_off_is_todays_behaviour(sandbox, clock):
    """Flag off (provider even wired): no bars call, nothing closes on the stale price, the 11:24 scan books 2483.45."""
    pos = _eth_short()
    bars = Bars()
    pm = _pm(pos, bars)
    _incident_bars(bars, "11:11")
    assert pm.update_price("ETH", 2469.25) == []
    assert pm.update_price("ETH", 2469.25) == []
    ev = pm.update_price("ETH", 2483.45)
    assert [e.action for e in ev] == ["SL"] and ev[0].price == pytest.approx(2483.45)
    assert "intrabar_fill" not in ev[0].metadata
    assert bars.calls == []


def _replay(flag_on, monkeypatch, provider):
    monkeypatch.setenv("PAPER_STOP_INTRABAR", "true" if flag_on else "false")
    pos = _eth_short(owner=False)
    pm = PositionManager()
    pm.positions["ETH"] = pos
    pm.intrabar_bars_provider = provider
    out = []
    for px in (2440.0, 2455.0, 2469.25, 2469.25, 2483.45):
        evs = pm.update_price("ETH", px)
        out.append([(e.action, round(e.price, 6), round(e.pnl, 6), round(e.fee, 6)) for e in evs])
    return out, round(pos.realized_pnl, 8), pos.state, pos.sl, round(pos.highest_price, 6), round(pos.lowest_price, 6)


def test_flag_off_byte_identical_with_or_without_provider(sandbox, monkeypatch):
    bars = Bars()
    _incident_bars(bars, "11:11")
    a = _replay(False, monkeypatch, None)
    b = _replay(False, monkeypatch, bars)
    assert a == b and bars.calls == []
    # and on, with NO provider wired (backtests / tests / live accounts): identical too
    c = _replay(True, monkeypatch, None)
    assert c == a


def test_sim_now_never_uses_intrabar(sandbox, on, clock):
    pos = _eth_short()
    bars = Bars()
    pm = _pm(pos, bars)
    _incident_bars(bars, "11:11")
    pm.update_price("ETH", 2469.25, sim_now=datetime(2026, 10, 16, 11, 7, tzinfo=timezone.utc))
    pm.update_price("ETH", 2469.25, sim_now=datetime(2026, 10, 16, 11, 11, tzinfo=timezone.utc))
    assert bars.calls == [] and pos.state != "CLOSED"


# ── fill rules ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("side", ["SHORT", "LONG"])
def test_gap_through_stop_fills_at_open_never_better(sandbox, on, clock, side):
    sg = 1 if side == "SHORT" else -1
    stop = 2472.0 if side == "SHORT" else 2366.82
    pos = Position(symbol="ETH", side=side, entry=2419.41, qty=0.191, sl=stop,
                   tp1=2419.41 - sg * 52.59, tp2=2419.41 - sg * 120, strategy="llm_first")
    pos._transition("OPEN")
    pos.highest_price = pos.lowest_price = 2419.41
    bars = Bars()
    pm = _pm(pos, bars)
    bars.bars = {T("11:05"): (2419.0, 2419.0 + 5, 2419.0 - 5, 2419.0)}
    assert pm.update_price("ETH", 2419.0) == []
    clock["now"] = T("11:16")
    gap_open = stop + sg * 9.0                                      # opened THROUGH the stop
    bars.bars[T("11:10")] = (2419.0, 2419.0 + 4, 2419.0 - 4, 2419.0)
    bars.bars[T("11:15")] = (gap_open, max(gap_open, stop) + 3, min(gap_open, stop) - 3, gap_open)
    ev = pm.update_price("ETH", 2419.0)
    assert [e.action for e in ev] == ["SL"]
    assert ev[0].price == pytest.approx(gap_open)                   # worse of stop and open
    assert sg * (ev[0].price - stop) >= 0                           # never better than the stop
    assert ev[0].timestamp == datetime(2026, 10, 16, 11, 15, tzinfo=timezone.utc)


@pytest.mark.parametrize("side", ["SHORT", "LONG"])
def test_long_and_short_cross_inside_bar_fills_at_stop(sandbox, on, clock, side):
    sg = 1 if side == "SHORT" else -1
    entry, stop = 100.0, 100.0 + sg * 2.0
    pos = Position(symbol="SOL", side=side, entry=entry, qty=10.0, sl=stop, tp1=entry - sg * 2,
                   tp2=entry - sg * 6, strategy="llm_first")
    pos._transition("OPEN")
    pos.highest_price = pos.lowest_price = entry
    bars = Bars()
    pm = _pm(pos, bars)
    bars.bars = {T("11:05"): (100.0, 100.5, 99.5, 100.2)}
    assert pm.update_price("SOL", 100.2) == []
    clock["now"] = T("11:13")
    bars.bars[T("11:10")] = (100.2, 100.2 + max(0, sg) * 3 + 0.3, 100.2 - max(0, -sg) * 3 - 0.3, 100.1)
    ev = pm.update_price("SOL", 100.1)                               # back on the safe side at the scan
    assert [e.action for e in ev] == ["SL"] and ev[0].price == pytest.approx(stop)
    pnl_r = pos.realized_pnl / (2.0 * 10.0)
    assert -1.06 < pnl_r < -1.0                                       # -1R plus round-trip fees


def test_old_extreme_in_the_checked_bar_does_not_count(sandbox, on, clock):
    """The forming bar at the last check already had its high; a stop tightened AFTER that (same bar) must not be
    filled from the pre-check high - only a NEW extreme counts."""
    pos = _eth_short(owner=False)
    pos.sl = 2472.0
    bars = Bars()
    pm = _pm(pos, bars)
    bars.bars = {T("11:05"): (2461.0, 2469.7, 2460.0, 2465.0)}
    assert pm.update_price("ETH", 2465.0) == []
    pos.sl = 2468.0                                                # moved between checks -> re-anchor only
    clock["now"] = T("11:09")
    assert pm.update_price("ETH", 2465.0) == []                    # pre-move high 2469.7 >= 2468: NOT a fill
    assert pos.state != "CLOSED" and pos._intrabar_anchor["sl"] == 2468.0
    clock["now"] = T("11:09", 30)
    bars.bars[T("11:05")] = (2461.0, 2469.7, 2460.0, 2466.0)       # same bar, no new high
    assert pm.update_price("ETH", 2466.0) == []
    clock["now"] = T("11:09", 50)
    bars.bars[T("11:05")] = (2461.0, 2470.5, 2460.0, 2466.0)       # NEW high after the check, through 2468
    ev = pm.update_price("ETH", 2466.0)
    assert [e.action for e in ev] == ["SL"] and ev[0].price == pytest.approx(2468.0)


def test_first_check_only_anchors_and_bars_down_falls_back(sandbox, on, clock):
    pos = _eth_short(owner=False)
    bars = Bars()
    pm = _pm(pos, bars)
    _incident_bars(bars, "11:11")
    clock["now"] = T("11:11", 41)
    assert pm.update_price("ETH", 2469.25) == []                   # no anchor yet: never fills from history
    bars.fail = True
    clock["now"] = T("11:15")
    assert pm.update_price("ETH", 2469.25) == []                   # bars unavailable: point check only
    ev = pm.update_price("ETH", 2483.45)
    assert [e.action for e in ev] == ["SL"] and ev[0].price == pytest.approx(2483.45)
    assert "intrabar_fill" not in ev[0].metadata


def test_target_touched_before_stop_bar_is_not_a_stop_fill(sandbox, on, clock):
    pos = _eth_short(owner=False)
    bars = Bars()
    pm = _pm(pos, bars)
    bars.bars = {T("11:05"): (2420.0, 2425.0, 2415.0, 2420.0)}
    assert pm.update_price("ETH", 2420.0) == []
    clock["now"] = T("11:16")
    bars.bars[T("11:10")] = (2420.0, 2421.0, 2299.0, 2350.0)       # tp2 2300 first
    bars.bars[T("11:15")] = (2350.0, 2480.0, 2340.0, 2400.0)       # then the stop
    assert pm.update_price("ETH", 2400.0) == []


# ── trails ─────────────────────────────────────────────────────────────────

def test_bot_trailing_stop_filled_intrabar(sandbox, on, clock):
    pos = Position(symbol="ETH", side="LONG", entry=3000.0, qty=1.0, sl=3040.0, tp1=3050.0, tp2=3150.0,
                   strategy="llm_first")
    pos._transition("OPEN")
    pos._transition("TP1_HIT")
    pos._transition("TRAILING")
    pos.original_sl = 2950.0
    pos.highest_price = pos.peak_price = 3080.0
    pos.lowest_price = 3000.0
    bars = Bars()
    pm = _pm(pos, bars)
    pm.enable_trailing = False                                     # keep the trail level fixed for the replay
    bars.bars = {T("11:05"): (3070.0, 3075.0, 3065.0, 3070.0)}
    assert pm.update_price("ETH", 3070.0) == []
    clock["now"] = T("11:13")
    bars.bars[T("11:10")] = (3070.0, 3071.0, 3031.0, 3060.0)
    ev = pm.update_price("ETH", 3060.0)
    assert [e.action for e in ev] == ["TRAILING_STOP"] and ev[0].price == pytest.approx(3040.0)


def test_owner_runner_trail_filled_intrabar(sandbox, on, clock, monkeypatch):
    monkeypatch.setenv("OWNER_RUNNER_STYLE", "true")
    er = {"owner_plan_id": "p1", "owner_trade": True, "exit_mode": "profits_only", "atr_at_fill": 100.0,
          "plan_max_hold_h": 48, "exit_style": "runner"}
    pos = Position(symbol="ETH", side="SHORT", entry=3000.0, qty=1.0, sl=3050.0, tp1=2950.0, tp2=2850.0,
                   strategy=ope.OWNER_STRATEGY, entry_reasons=er)
    pos._transition("OPEN")
    pos.highest_price = pos.lowest_price = 3000.0
    pos.open_time = datetime(2026, 10, 16, 10, 0, tzinfo=timezone.utc)
    bars = Bars()
    pm = _pm(pos, bars)
    bars.bars = {T("11:05"): (2960.0, 2965.0, 2945.0, 2950.0)}
    ev = pm.update_price("ETH", 2950.0)                            # +1R: the half
    assert [e.action for e in ev] == ["OWNER_RUNNER_HALF"]
    for i, px in enumerate((2900.0, 2800.0)):                      # trail ratchets to 2800 + 100 = 2900
        clock["now"] = T("11:07", 30 + i * 10)
        bars.bars[T("11:05")] = (2960.0, 2965.0, px - 1, px)
        assert pm.update_price("ETH", px) == []
    assert pos.sl == pytest.approx(2900.0)
    clock["now"] = T("11:14")
    bars.bars[T("11:10")] = (2800.0, 2915.0, 2795.0, 2850.0)       # spikes through the trail, back by the scan
    ev = pm.update_price("ETH", 2850.0)
    assert [e.action for e in ev] == ["OWNER_RUNNER_TRAIL"] and ev[0].price == pytest.approx(2900.0)
    assert ev[0].metadata["intrabar_fill"] and ev[0].is_position_close
    row = ope.record_owner_close(ev[0], pos, pm)
    assert row["exit"] == pytest.approx(2900.0) and row["intrabar_fill"]


# ── extra-coin (OWNER_PLAN_ANY_COIN) path ──────────────────────────────────

def test_extra_coin_owner_stop_filled_intrabar_and_recorded(sandbox, on, clock, monkeypatch):
    from core import owner_any_coin as oac
    from tests.test_owner_plans_any_coin import HL, AnyBot, _sui, _tick
    from tests.test_owner_plan_exec import _write_rows, _fills
    h = HL()
    oac._reset_for_tests()
    monkeypatch.setattr(oac, "_post", h)
    monkeypatch.setattr(oac, "MIDS_TTL_S", 0.0)
    monkeypatch.setenv("OWNER_PLAN_EXEC", "true")
    monkeypatch.setenv("OWNER_PLAN_ANY_COIN", "true")
    try:
        _write_rows(sandbox, _sui("st", etype="market", entry=3.05, price_at_plan=3.05, stop=2.95, target=3.4))
        pm = PositionManager()
        bars = Bars()
        pm.intrabar_bars_provider = bars
        bot = AnyBot(pm, {})
        bars.bars = {T("11:05"): (3.05, 3.06, 3.04, 3.05)}
        _tick(bot, h, 3.05)                                        # opens + first check (anchor)
        assert "SUI" in pm.positions
        clock["now"] = T("11:08")
        _tick(bot, h, 3.04)                                        # anchored
        assert pm.positions["SUI"].state != "CLOSED"
        clock["now"] = T("11:13")
        bars.bars[T("11:10")] = (3.03, 3.04, 2.91, 3.0)            # wick through 2.95, back to 3.00 by the scan
        _tick(bot, h, 3.00)
        rows = _fills(sandbox)
        assert [r["kind"] for r in rows] == ["open", "final"]
        fin = rows[-1]
        assert fin["reason"] == "SL" and fin["exit"] == pytest.approx(2.95)
        assert fin["intrabar_fill"] and fin["fill_ts"].startswith("2026-10-16T11:10")
        assert fin["total_r"] == pytest.approx(-1, abs=0.15)
        assert "SUI" not in pm.positions and pm.trade_log == []
        assert any(c[0] == "SUI" for c in bars.calls)
    finally:
        oac._reset_for_tests()


# ── the stale-price root cause (fetcher) ──────────────────────────────────

def test_price_cache_ttl_is_short_not_the_ohlcv_ttl(monkeypatch):
    """Live bot: DataFetcher(cache_ttl=max(90, SCAN_INTERVAL_S*3)) = 900s. The 'price:' entry must not live that
    long - that is what froze ETH at 2469.25 for ~15 min."""
    from data.fetcher import DataFetcher
    monkeypatch.delenv("PRICE_CACHE_TTL_S", raising=False)
    f = DataFetcher.__new__(DataFetcher)
    import threading
    f._lock = threading.Lock()
    f._cache = {}
    f.cache_ttl = 900
    f.price_cache_ttl = 15.0
    f.price_max_age_s = 120.0
    f._price_info = {}
    quotes = iter([2469.25, 2483.45])
    monkeypatch.setattr(f, "_fetch_ccxt_ticker", lambda s: next(quotes), raising=False)
    now = {"t": 1000.0}
    monkeypatch.setattr(time, "time", lambda: now["t"])
    assert f.latest_price("ETH", "ethereum") == 2469.25
    now["t"] += 10
    assert f.latest_price("ETH", "ethereum") == 2469.25            # within 15s: cached
    now["t"] += 30
    assert f.latest_price("ETH", "ethereum") == 2483.45            # 40s later: refetched (old code: 900s)


def test_stale_coingecko_fallback_refused(monkeypatch):
    from data.fetcher import DataFetcher
    import threading
    f = DataFetcher.__new__(DataFetcher)
    f._lock = threading.Lock()
    f._cache = {}
    f.cache_ttl = 900
    f.price_cache_ttl = 15.0
    f.price_max_age_s = 120.0
    f._price_info = {}
    monkeypatch.setattr(f, "_fetch_ccxt_ticker", lambda s: None, raising=False)
    old = pd.DataFrame({"time": [pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=9)], "close": [2469.25]})
    monkeypatch.setattr(f, "_fetch_cg_market_chart", lambda c, days=1: old, raising=False)
    assert f.latest_price("ETH", "ethereum") is None
    fresh = pd.DataFrame({"time": [pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=20)], "close": [2480.0]})
    monkeypatch.setattr(f, "_fetch_cg_market_chart", lambda c, days=1: fresh, raising=False)
    assert f.latest_price("ETH", "ethereum") == 2480.0
    info = f.price_info("ETH")
    assert info["source"] == "coingecko" and info["fallback"] and info["age_s"] < 60


def test_stale_exchange_ticker_skipped_for_next_venue(monkeypatch):
    from data.fetcher import DataFetcher
    import threading

    class Ex:
        def __init__(self, px, age_s):
            self.px, self.age_s = px, age_s

        def fetch_ticker(self, pair):
            return {"last": self.px, "timestamp": (time.time() - self.age_s) * 1000}

    f = DataFetcher.__new__(DataFetcher)
    f._lock = threading.Lock()
    f._ccxt_available = True
    f._symbol_exchanges = {"ETH": [("hyperliquid", "ETH/USDC:USDC"), ("kraken", "ETH/USDT")]}
    f._exchanges = {"hyperliquid": Ex(2469.25, 600), "kraken": Ex(2483.0, 2)}
    f._exchange_rate_limits = {}
    f._last_exchange_request_ts = {}
    f._ccxt_requests = f._ccxt_failures = 0
    f.price_max_age_s = 120.0
    f._price_info = {}
    assert f._fetch_ccxt_ticker("ETH") == 2483.0
    assert f.price_info("ETH")["source"] == "ccxt:kraken" and f.price_info("ETH")["fallback"]


def test_live_bot_wires_provider_for_paper_only():
    src = (BOT / "multi_strategy_main.py").read_text(encoding="utf-8")
    i = src.index("self.pos_mgr = PositionManager(")
    seg = src[i:i + 1500]
    assert "if config.is_paper:" in seg and "intrabar_bars_provider = _hl_5m_bars" in seg
    assert "PRICE PROVENANCE" in src
