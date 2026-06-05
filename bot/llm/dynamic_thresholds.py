"""
Dynamic Threshold Engine — Regime-adaptive confidence floors from live trade data.

Replaces hardcoded confidence_floor=69.0 / ranging_confidence_floor=68.0 with
floors computed from actual per-regime win rates in trade_dna.json.

Floor logic (requires n >= 10 trades per regime):
  WR < 25%  → floor 76  (illiquid/ranging are here — only accept elite conviction)
  WR < 35%  → floor 71  (poor — above-average conviction required)
  WR < 45%  → floor 66  (below average)
  WR < 55%  → floor 62  (average — trending sits here at 52% WR)
  WR >= 55% → floor 58  (strong edge — relax filter)
  n < 10    → floor 64  (insufficient data, conservative default)

Cache refreshes every 30 minutes. Thread-safe reads.
"""

import json
import logging
import os
import time
from typing import Dict, Optional, Tuple

logger = logging.getLogger("bot.llm.dynamic_thresholds")

_TRADE_DNA_PATH = os.path.join("data", "llm", "deep_memory", "trade_dna.json")
_CACHE_TTL_S = 1800  # 30 minutes

# Minimum trades needed to trust a regime's WR estimate
_MIN_TRADES = 10

# Default floor when regime has insufficient data
_DEFAULT_FLOOR = 64.0

# Absolute caps
_FLOOR_MIN = 55.0
_FLOOR_MAX = 82.0


def _wr_to_floor(wr: float, n: int) -> float:
    """Map a live win rate to a confidence floor."""
    if n < _MIN_TRADES:
        return _DEFAULT_FLOOR
    if wr < 0.25:
        return 76.0
    if wr < 0.35:
        return 71.0
    if wr < 0.45:
        return 66.0
    if wr < 0.55:
        return 62.0
    return 58.0


class DynamicThresholds:
    """Computes regime-aware confidence floors from live trade_dna.

    Singleton via get_dynamic_thresholds(); direct instantiation fine for tests.
    """

    def __init__(self, trade_dna_path: str = _TRADE_DNA_PATH):
        self._path = trade_dna_path
        self._loaded_at: float = 0.0
        # {regime: {"wr": float, "n": int, "floor": float, "pnl": float}}
        self._regime_data: Dict[str, dict] = {}
        # {symbol: {"wr": float, "n": int, "pnl": float}}
        self._symbol_data: Dict[str, dict] = {}
        # {symbol.side.regime: {"wr": float, "n": int, "pnl": float}}
        self._combo_data: Dict[str, dict] = {}
        # {regime: {"avg_sl_width_pct": float, "sl_hit_rate": float, "n": int}}
        self._regime_sl_data: Dict[str, dict] = {}
        # {hour_0_23: {"wr": float, "n": int}} — UTC hour win rates
        self._hour_data: Dict[int, dict] = {}
        # {entry_type: {"wr": float, "n": int, "avg_hold_s": float, "pnl": float}}
        self._entry_type_data: Dict[str, dict] = {}
        # {"<1h": ..., "1-2h": ..., ...} — hold time bucket performance
        self._hold_bucket_data: Dict[str, dict] = {}

    # ── Refresh ─────────────────────────────────────────────────────────────

    def _maybe_refresh(self):
        if time.time() - self._loaded_at < _CACHE_TTL_S:
            return
        self._load()

    def _load(self):
        try:
            if not os.path.exists(self._path):
                return
            with open(self._path, "r") as f:
                data = json.load(f)
            trades = data.get("trades", [])
            if not trades:
                return

            regime_agg: Dict[str, dict] = {}
            symbol_agg: Dict[str, dict] = {}
            combo_agg: Dict[str, dict] = {}
            # For SL analysis: {regime: {"sl_widths": [], "sl_hit_count": 0}}
            regime_sl_agg: Dict[str, dict] = {}
            # For time-of-day: {hour: {"wins": int, "total": int}}
            hour_agg: Dict[int, dict] = {}
            # For entry type / trade profile
            entry_agg: Dict[str, dict] = {}
            # For hold time buckets
            hold_agg: Dict[str, dict] = {}

            for t in trades:
                regime = (t.get("regime") or "unknown").lower()
                symbol = (t.get("symbol") or "unknown").upper()
                side = (t.get("side") or "").upper()
                pnl = float(t.get("pnl") or 0)
                won = t.get("outcome") == "WIN"

                # SL width analysis
                entry = float(t.get("entry_price") or 0)
                sl = float(t.get("sl") or 0)
                exit_reason = (t.get("exit_reason") or "").upper()
                if regime not in regime_sl_agg:
                    regime_sl_agg[regime] = {"sl_widths": [], "sl_hits": 0, "total": 0}
                regime_sl_agg[regime]["total"] += 1
                if entry > 0 and sl > 0:
                    regime_sl_agg[regime]["sl_widths"].append(abs(entry - sl) / entry)
                if exit_reason == "SL":
                    regime_sl_agg[regime]["sl_hits"] += 1

                # Time-of-day from timestamp
                ts = t.get("timestamp", 0)
                if ts:
                    try:
                        import datetime as _dt
                        _hour = _dt.datetime.fromtimestamp(float(ts), tz=_dt.timezone.utc).hour
                        if _hour not in hour_agg:
                            hour_agg[_hour] = {"wins": 0, "total": 0}
                        hour_agg[_hour]["total"] += 1
                        if won:
                            hour_agg[_hour]["wins"] += 1
                    except Exception:
                        pass

                for agg, key in [
                    (regime_agg, regime),
                    (symbol_agg, symbol),
                    (combo_agg, f"{symbol}.{side}.{regime}"),
                ]:
                    if key not in agg:
                        agg[key] = {"wins": 0, "total": 0, "pnl": 0.0}
                    agg[key]["total"] += 1
                    agg[key]["pnl"] += pnl
                    if won:
                        agg[key]["wins"] += 1

                # Entry type / trade profile
                entry_type = (t.get("entry_type") or "").upper()
                if entry_type:
                    if entry_type not in entry_agg:
                        entry_agg[entry_type] = {"wins": 0, "total": 0, "pnl": 0.0, "hold_sum": 0.0}
                    entry_agg[entry_type]["total"] += 1
                    entry_agg[entry_type]["pnl"] += pnl
                    entry_agg[entry_type]["hold_sum"] += float(t.get("hold_time_s") or 0)
                    if won:
                        entry_agg[entry_type]["wins"] += 1

                # Hold time buckets
                hold_s = float(t.get("hold_time_s") or 0)
                if hold_s < 3600: _hbucket = "<1h"
                elif hold_s < 7200: _hbucket = "1-2h"
                elif hold_s < 21600: _hbucket = "2-6h"
                elif hold_s < 43200: _hbucket = "6-12h"
                else: _hbucket = ">12h"
                if _hbucket not in hold_agg:
                    hold_agg[_hbucket] = {"wins": 0, "total": 0, "pnl": 0.0}
                hold_agg[_hbucket]["total"] += 1
                hold_agg[_hbucket]["pnl"] += pnl
                if won:
                    hold_agg[_hbucket]["wins"] += 1

            self._regime_data = {
                r: {
                    "wr": v["wins"] / v["total"],
                    "n": v["total"],
                    "pnl": round(v["pnl"], 2),
                    "floor": _wr_to_floor(v["wins"] / v["total"], v["total"]),
                }
                for r, v in regime_agg.items()
            }
            self._symbol_data = {
                s: {
                    "wr": v["wins"] / v["total"],
                    "n": v["total"],
                    "pnl": round(v["pnl"], 2),
                }
                for s, v in symbol_agg.items()
            }
            self._combo_data = {
                k: {
                    "wr": v["wins"] / v["total"],
                    "n": v["total"],
                    "pnl": round(v["pnl"], 2),
                    "floor": _wr_to_floor(v["wins"] / v["total"], v["total"]),
                }
                for k, v in combo_agg.items()
            }
            # SL analysis: avg_sl_width and sl_hit_rate per regime
            self._regime_sl_data = {}
            for r, v in regime_sl_agg.items():
                widths = v["sl_widths"]
                self._regime_sl_data[r] = {
                    "avg_sl_width_pct": round(sum(widths) / len(widths) * 100, 2) if widths else 0,
                    "sl_hit_rate": round(v["sl_hits"] / v["total"], 3) if v["total"] else 0,
                    "n": v["total"],
                }
            # Time-of-day hourly win rates
            self._hour_data = {
                h: {"wr": round(v["wins"] / v["total"], 3), "n": v["total"]}
                for h, v in hour_agg.items()
                if v["total"] > 0
            }
            # Entry type / trade profile performance
            self._entry_type_data = {
                et: {
                    "wr": round(v["wins"] / v["total"], 3),
                    "n": v["total"],
                    "pnl": round(v["pnl"], 2),
                    "avg_hold_s": round(v["hold_sum"] / v["total"], 0) if v["total"] else 0,
                }
                for et, v in entry_agg.items()
                if v["total"] >= 5
            }
            # Hold time bucket performance
            self._hold_bucket_data = {
                b: {
                    "wr": round(v["wins"] / v["total"], 3),
                    "n": v["total"],
                    "pnl": round(v["pnl"], 2),
                }
                for b, v in hold_agg.items()
                if v["total"] > 0
            }
            self._loaded_at = time.time()
            logger.info(
                f"[DYN-THRESH] Loaded: {len(trades)} trades, "
                f"{len(self._regime_data)} regimes, {len(self._symbol_data)} symbols"
            )
        except Exception as e:
            logger.warning(f"[DYN-THRESH] Load error: {e}")

    # ── Public API ───────────────────────────────────────────────────────────

    def get_confidence_floor(
        self,
        regime: str = "",
        symbol: str = "",
        side: str = "",
        fallback: float = _DEFAULT_FLOOR,
    ) -> float:
        """Return the dynamic confidence floor for a given regime/symbol/side context.

        Lookup priority:
          1. symbol.side.regime combo (most specific, requires n >= 10)
          2. regime-level floor (requires n >= 10)
          3. fallback (default 64.0)

        In BACKTEST_CLEAN_FLOOR mode the live trade_dna floors are ignored and
        only the caller's fallback is returned. This prevents paper-trading
        outcomes from contaminating historical backtests.
        """
        if os.getenv("BACKTEST_CLEAN_FLOOR"):
            return fallback
        self._maybe_refresh()
        regime_key = (regime or "unknown").lower()
        symbol_key = (symbol or "").upper()
        side_key = (side or "").upper()
        combo_key = f"{symbol_key}.{side_key}.{regime_key}"

        # Most specific: combo floor
        combo = self._combo_data.get(combo_key)
        if combo and combo["n"] >= _MIN_TRADES:
            return max(_FLOOR_MIN, min(_FLOOR_MAX, combo["floor"]))

        # Regime-level floor
        reg = self._regime_data.get(regime_key)
        if reg and reg["n"] >= _MIN_TRADES:
            return max(_FLOOR_MIN, min(_FLOOR_MAX, reg["floor"]))

        return fallback

    def get_regime_stats(self, regime: str) -> Optional[dict]:
        """Return {'wr': float, 'n': int, 'pnl': float, 'floor': float} or None."""
        self._maybe_refresh()
        return self._regime_data.get((regime or "unknown").lower())

    def get_all_regime_floors(self) -> Dict[str, float]:
        """Return {regime: floor} for all regimes with sufficient data."""
        self._maybe_refresh()
        return {
            r: d["floor"]
            for r, d in self._regime_data.items()
            if d["n"] >= _MIN_TRADES
        }

    def get_hour_stats(self, hour: int) -> Optional[dict]:
        """Return {'wr': float, 'n': int} for the given UTC hour (0-23), or None."""
        self._maybe_refresh()
        return self._hour_data.get(int(hour))

    def get_time_of_day_floor_adj(self, hour: int) -> float:
        """Return a confidence floor adjustment based on UTC hour performance.

        Requires >= 8 trades in that hour. Blends in as n grows.
          WR >= 0.50  → -4 (strong hour — relax floor slightly)
          WR >= 0.40  → -2
          WR <= 0.20  → +6 (terrible hour — raise floor)
          WR <= 0.30  → +3
          else        → 0
        """
        self._maybe_refresh()
        stats = self._hour_data.get(int(hour))
        if not stats or stats["n"] < 8:
            return 0.0
        wr = stats["wr"]
        blend = min(1.0, (stats["n"] - 8) / 22)  # full effect at 30 trades
        if wr >= 0.50:
            return round(-4.0 * blend, 1)
        if wr >= 0.40:
            return round(-2.0 * blend, 1)
        if wr <= 0.20:
            return round(6.0 * blend, 1)
        if wr <= 0.30:
            return round(3.0 * blend, 1)
        return 0.0

    def get_entry_type_stats(self, entry_type: str) -> Optional[dict]:
        """Return {'wr', 'n', 'pnl', 'avg_hold_s'} for a trade profile, or None."""
        self._maybe_refresh()
        return self._entry_type_data.get((entry_type or "").upper())

    def get_entry_type_floor_adj(self, entry_type: str) -> float:
        """Confidence floor adjustment based on live win rate for a trade profile.

        TREND at 14% WR → +8 (require stronger signals)
        SCALP at ~30% WR → +4
        MEDIUM at ~36% WR → 0
        hype_buy at ~53% WR → -4 (relax for proven setup)
        """
        self._maybe_refresh()
        stats = self._entry_type_data.get((entry_type or "").upper())
        if not stats or stats["n"] < 5:
            return 0.0
        wr = stats["wr"]
        blend = min(1.0, (stats["n"] - 5) / 20)
        if wr >= 0.50:
            return round(-4.0 * blend, 1)
        if wr >= 0.42:
            return 0.0
        if wr <= 0.20:
            return round(8.0 * blend, 1)
        if wr <= 0.30:
            return round(5.0 * blend, 1)
        if wr <= 0.38:
            return round(2.0 * blend, 1)
        return 0.0

    def get_hold_bucket_stats(self) -> Dict[str, dict]:
        """Return all hold-time bucket stats: {'<1h': {'wr', 'n', 'pnl'}, ...}."""
        self._maybe_refresh()
        return self._hold_bucket_data.copy()

    def get_regime_sl_stats(self, regime: str) -> Optional[dict]:
        """Return {'avg_sl_width_pct': float, 'sl_hit_rate': float, 'n': int} or None."""
        self._maybe_refresh()
        return self._regime_sl_data.get((regime or "unknown").lower())

    def get_dynamic_sl_boost(self, regime: str, static_sl_scalar: float) -> float:
        """Compute a data-driven additive boost to the static SL scalar.

        System runs at ~35% WR so optimal SL hit rate ≈ 65% (stops absorb 65% of exits).
        When a regime's live SL hit rate significantly exceeds this, stops are too tight
        and need widening. Returns an additive boost to add to the static sl_scalar.

        Returns: float in [0.0, 0.30]
        """
        self._maybe_refresh()
        stats = self._regime_sl_data.get((regime or "unknown").lower())
        if not stats or stats["n"] < 10:
            return 0.0

        sl_hit_rate = stats["sl_hit_rate"]
        n = stats["n"]

        # Only boost when SL hit rate is meaningfully above the 72% ceiling
        if sl_hit_rate <= 0.72:
            return 0.0

        # Blend factor: grows from 0→1 between n=10 and n=30 trades
        blend = min(1.0, (n - 10) / 20.0)

        # Each percent above target (65%) contributes to widening
        # (0.825 - 0.65) * 0.6 = +0.105 for illiquid; capped at +0.30
        boost = (sl_hit_rate - 0.65) * 0.6 * blend
        boost = max(0.0, min(0.30, boost))

        return round(boost, 3)

    def get_summary(self) -> str:
        """Human-readable summary for logging/enricher."""
        self._maybe_refresh()
        if not self._regime_data:
            return ""
        lines = ["DYNAMIC FLOORS (live data):"]
        for r, d in sorted(self._regime_data.items(), key=lambda x: -x[1]["n"]):
            sl = self._regime_sl_data.get(r, {})
            sl_info = ""
            if sl:
                sl_info = f" SL_hit={sl['sl_hit_rate']:.0%} avg_SL={sl['avg_sl_width_pct']:.1f}%"
            lines.append(
                f"  {r}: WR={d['wr']:.0%} n={d['n']} "
                f"floor={d['floor']:.0f}{sl_info} PnL=${d['pnl']:+.0f}"
            )
        # Hold time summary
        if self._hold_bucket_data:
            lines.append("HOLD TIME PERFORMANCE:")
            for b in ["<1h", "1-2h", "2-6h", "6-12h", ">12h"]:
                d = self._hold_bucket_data.get(b)
                if d:
                    lines.append(f"  {b}: WR={d['wr']:.0%} n={d['n']} PnL=${d['pnl']:+.0f}")
        # Entry type summary
        if self._entry_type_data:
            lines.append("TRADE PROFILE PERFORMANCE:")
            for et, d in sorted(self._entry_type_data.items(), key=lambda x: -x[1]["n"]):
                lines.append(f"  {et}: WR={d['wr']:.0%} n={d['n']} PnL=${d['pnl']:+.0f}")
        return "\n".join(lines)

    def invalidate(self):
        self._loaded_at = 0.0


# ── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[DynamicThresholds] = None


def get_dynamic_thresholds() -> DynamicThresholds:
    global _instance
    if _instance is None:
        _instance = DynamicThresholds()
    return _instance
