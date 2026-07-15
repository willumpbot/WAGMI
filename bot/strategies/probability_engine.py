"""
Strategy 11: Probability Engine — Regime-Conditional Monte Carlo

An evolution of the disabled monte_carlo_zones strategy. Key improvements:
1. Regime-conditional return distributions (not one-size-fits-all)
2. Bayesian probability weighting (prior + observed data)
3. Multiple probability models: historical, parametric, tail-aware
4. Forward probability cones for entry timing
5. Expected value calculation with fee-awareness

Instead of just "price might go here", this engine answers:
- "Given the current regime, what's the probability of reaching TP1/TP2?"
- "What's the expected value of this trade after fees?"
- "Is the risk/reward justified by the probability distribution?"

Data requirements:
- 1h OHLCV (primary)
- 6h OHLCV (regime context)
"""

import glob
import logging
import os
import time
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd
import numpy as np

from .base import BaseStrategy, Signal

logger = logging.getLogger("bot.strategy.probability_engine")


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev).abs(),
        (df["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n, min_periods=1).mean()


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=max(2, span), adjust=False).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return 25.0
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr_vals = _atr(df, period).replace(0, 1e-12)
    plus_di = 100 * _ema(plus_dm, period) / atr_vals
    minus_di = 100 * _ema(minus_dm, period) / atr_vals
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-12)
    adx_series = _ema(dx, period)
    return float(adx_series.iloc[-1]) if len(adx_series) > 0 else 25.0


class ProbabilityEngineStrategy(BaseStrategy):
    """
    Regime-conditional Monte Carlo probability engine.

    Uses observed return distributions conditioned on the current market regime
    to estimate probabilities of price reaching specific levels.
    Generates signals when probability-weighted EV is strongly positive.
    """

    # Simulation parameters
    NUM_SIMS = 2000           # Number of Monte Carlo paths
    FORWARD_BARS = 12         # 12h forward projection
    # 2026-06-06: MIN_PROB_TP1 + MIN_EV_PER_DOLLAR were hardcoded magic numbers
    # (0.45 / 0.15) optimized for a specific regime distribution. Range/chop regimes
    # operate on smaller moves with acceptable lower-probability setups; trending
    # regimes warrant higher conviction. Defaults now made regime-conditional in
    # the check below — see _min_prob/_min_ev computation. Keep these constants as
    # SAFETY floors only (overall minimum even in best regime).
    MIN_PROB_TP1 = 0.35       # SAFETY floor — never accept signals below this
    MIN_EV_PER_DOLLAR = 0.10  # SAFETY floor — never accept signals below this

    # Regime classification (simplified — uses ADX + volatility)
    REGIME_TRENDING_ADX = 25.0
    REGIME_RANGING_ADX = 15.0

    # Fee model
    ROUND_TRIP_FEE_BPS = 8    # 4 bps each way

    # 2026-07-15 LIVING VALUES: shared refresh cadence / trust threshold for
    # every ledger-derived live table below (regime gate, TP2 continuation,
    # regime+side confidence bonus). n>=13 matches the project-wide floor for
    # trusting a self-updating slice; below it we fall back to a neutral
    # constant, never to an inverted or stale one.
    _LIVE_STATS_TTL_S = 1800   # 30 min
    _LIVE_STATS_MIN_N = 13

    def __init__(self, symbols: Dict[str, Any],
                 num_sims: int = 2000, forward_bars: int = 12):
        super().__init__("probability_engine", symbols)
        self.num_sims = num_sims
        self.forward_bars = forward_bars
        # Live regime->(min_prob, min_ev) gate table (fix: 2026-06-06 static
        # table was inverted vs the realized ledger). See _get_regime_gate().
        self._regime_gate_cache: Dict[str, Tuple[float, float]] = {}
        self._regime_gate_loaded_at: float = 0.0
        # Live TP1->TP2 continuation weight, from paper_trades/trades_*.csv.
        # See _get_tp2_weight().
        self._tp_cont_cache: Dict[str, Any] = {}
        self._tp_cont_loaded_at: float = 0.0
        # Live (canonical regime, side) -> avg net pnl bonus, from the ledger.
        # See _get_regime_side_bonus().
        self._regime_side_cache: Dict[Tuple[str, str], Tuple[float, int]] = {}
        self._regime_side_loaded_at: float = 0.0

    def get_required_timeframes(self) -> List[str]:
        return ["1h"]

    # ── Live regime gate table (2026-07-15) ─────────────────────────────────
    # Replaces the 2026-06-06 static regime->(min_prob,min_ev) table, which
    # was inverted vs the realized ledger: range/consolidation (worst
    # realized edge, avg -$6.19/tr n=122) got the LOOSEST gate (0.42/0.12)
    # while trending (best realized edge, avg +$20.44/tr n=42) got the
    # TIGHTEST (0.50/0.20). Now computed from data/trade_ledger.csv, keyed on
    # canonical regime names (llm/regime_canonical.py) so both the ledger's
    # regime_1h vocabulary and this engine's internal regime labels
    # (trending/ranging/volatile/normal) resolve to the same bucket.
    _REGIME_GATE_NEUTRAL = (0.45, 0.15)
    _REGIME_GATE_TIGHT = (0.50, 0.20)
    _REGIME_GATE_PROB_CAP = 0.60
    _REGIME_GATE_EV_CAP = 0.30

    def _get_regime_gate_table(self) -> Dict[str, Tuple[float, float]]:
        """Build/refresh canonical-regime -> (min_prob, min_ev) from the ledger.

        For each canonical regime with n>=13 resolved trades: realized avg
        net pnl <= 0 -> TIGHT gate (0.50/0.20, same bar the old table
        reserved for trending only); realized avg net pnl > 0 -> the NEUTRAL
        base (0.45/0.15). Regimes with n<13 are simply absent from the table
        (caller falls back to NEUTRAL, never the old 0.35/0.10 floor).
        """
        now = time.time()
        if (now - self._regime_gate_loaded_at < self._LIVE_STATS_TTL_S
                and self._regime_gate_cache):
            return self._regime_gate_cache

        table: Dict[str, Tuple[float, float]] = {}
        try:
            from llm.regime_canonical import canonicalize_regime
            ledger_path = os.path.join(os.path.dirname(__file__), "..", "data", "trade_ledger.csv")
            if os.path.exists(ledger_path):
                df = pd.read_csv(ledger_path)
                if {"regime_1h", "net_pnl", "exit_type"}.issubset(df.columns):
                    df = df[df["exit_type"].notna() & df["net_pnl"].notna()]
                    canon = df["regime_1h"].apply(canonicalize_regime)
                    for c, grp in df.groupby(canon):
                        n = len(grp)
                        if n < self._LIVE_STATS_MIN_N:
                            continue
                        avg_pnl = float(grp["net_pnl"].mean())
                        table[c] = self._REGIME_GATE_TIGHT if avg_pnl <= 0 else self._REGIME_GATE_NEUTRAL
        except Exception as e:
            logger.debug(f"[PROB_ENGINE] regime gate table refresh failed: {e}")

        self._regime_gate_cache = table
        self._regime_gate_loaded_at = now
        return table

    def _get_regime_gate(self, regime_label: str) -> Tuple[float, float]:
        """Live (min_prob, min_ev) for this regime label.

        Falls back to the NEUTRAL base for regimes absent from the live
        table (n<13). MIN_PROB_TP1/MIN_EV_PER_DOLLAR remain hard safety
        clamps applied here — no live-derived value can fall below them.
        """
        table = self._get_regime_gate_table()
        try:
            from llm.regime_canonical import canonicalize_regime
            canon = canonicalize_regime(regime_label)
        except Exception:
            canon = regime_label
        min_prob, min_ev = table.get(canon, self._REGIME_GATE_NEUTRAL)
        return (
            max(self.MIN_PROB_TP1, min(self._REGIME_GATE_PROB_CAP, min_prob)),
            max(self.MIN_EV_PER_DOLLAR, min(self._REGIME_GATE_EV_CAP, min_ev)),
        )

    # ── Live TP1->TP2 continuation weight (2026-07-15) ──────────────────────
    # Replaces the static 70/30 blend in _compute_ev, which assumed a 30%
    # TP1->TP2 continuation rate vs the realized 16.7% (5 TP2 / 30 TP1 exits
    # in paper_trades/trades_*.csv), overstating EV on every signal.
    _TP_CONT_PRIOR_CAP = 0.30  # legacy static prior — ceiling for the n<13 MC fallback only

    def _get_tp_continuation_stats(self) -> Dict[str, Any]:
        now = time.time()
        if (now - self._tp_cont_loaded_at < self._LIVE_STATS_TTL_S
                and self._tp_cont_cache):
            return self._tp_cont_cache

        stats: Dict[str, Any] = {"global": None, "by_symbol_side": {}}
        try:
            pattern = os.path.join(os.path.dirname(__file__), "..", "paper_trades", "trades_*.csv")
            frames = []
            for fp in glob.glob(pattern):
                try:
                    d = pd.read_csv(fp)
                    if len(d):
                        frames.append(d)
                except Exception:
                    continue
            if frames:
                df = pd.concat(frames, ignore_index=True)
                if {"symbol", "action", "price"}.issubset(df.columns):
                    df = df[~df["symbol"].astype(str).str.upper().str.contains("TEST", na=False)]
                    df = df[~df["price"].isin([100, 150, 50000])]
                    tp1_total = int((df["action"] == "TP1").sum())
                    tp2_total = int((df["action"] == "TP2").sum())
                    if tp1_total >= self._LIVE_STATS_MIN_N:
                        stats["global"] = tp2_total / tp1_total
                    if "side" in df.columns:
                        for (sym, side), grp in df.groupby(["symbol", "side"]):
                            n1 = int((grp["action"] == "TP1").sum())
                            if n1 >= self._LIVE_STATS_MIN_N:
                                n2 = int((grp["action"] == "TP2").sum())
                                stats["by_symbol_side"][(str(sym).upper(), str(side).upper())] = n2 / n1
        except Exception as e:
            logger.debug(f"[PROB_ENGINE] TP continuation stats refresh failed: {e}")

        self._tp_cont_cache = stats
        self._tp_cont_loaded_at = now
        return stats

    def _get_tp2_weight(self, symbol: str, side: str, probs: Dict[str, float]) -> float:
        """Live TP1->TP2 continuation weight for the EV blend.

        Priority: per-(symbol, side) slice (n>=13 TP1 hits) -> global
        (n>=13) -> per-signal Monte Carlo conditional capped at the old
        static prior (0.30) so a cold cache can never exceed the legacy
        assumption.
        """
        stats = self._get_tp_continuation_stats()
        key = ((symbol or "").upper(), (side or "").upper())
        w2 = stats["by_symbol_side"].get(key)
        if w2 is None:
            w2 = stats["global"]
        if w2 is None:
            w2 = min(probs.get("prob_tp2", 0.0) / max(probs.get("prob_tp1", 0.01), 0.01),
                      self._TP_CONT_PRIOR_CAP)
        return max(0.0, min(1.0, w2))

    # ── Live (regime, side) confidence bonus (2026-07-15) ───────────────────
    # Replaces the flat +8.0 "trend-aligned" bonus, which boosted LONG and
    # SHORT identically despite the ledger showing them as opposite-sign
    # edges in the trend family (LONG avg -$3.68/tr vs SHORT avg +$8.03/tr).
    _CONFIDENCE_BONUS_CAP = 8.0

    def _get_regime_side_table(self) -> Dict[Tuple[str, str], Tuple[float, int]]:
        now = time.time()
        if (now - self._regime_side_loaded_at < self._LIVE_STATS_TTL_S
                and self._regime_side_cache):
            return self._regime_side_cache

        table: Dict[Tuple[str, str], Tuple[float, int]] = {}
        try:
            from llm.regime_canonical import canonicalize_regime
            ledger_path = os.path.join(os.path.dirname(__file__), "..", "data", "trade_ledger.csv")
            if os.path.exists(ledger_path):
                df = pd.read_csv(ledger_path)
                if {"regime_1h", "net_pnl", "side", "exit_type"}.issubset(df.columns):
                    df = df[df["exit_type"].notna() & df["net_pnl"].notna()]
                    canon = df["regime_1h"].apply(canonicalize_regime)
                    side_u = df["side"].astype(str).str.upper()
                    for (c, s), grp in df.groupby([canon, side_u]):
                        n = len(grp)
                        if n < self._LIVE_STATS_MIN_N:
                            continue
                        avg_pnl = float(grp["net_pnl"].mean())
                        bonus = max(-self._CONFIDENCE_BONUS_CAP, min(self._CONFIDENCE_BONUS_CAP, avg_pnl))
                        table[(c, s)] = (bonus, n)
        except Exception as e:
            logger.debug(f"[PROB_ENGINE] regime/side bonus table refresh failed: {e}")

        self._regime_side_cache = table
        self._regime_side_loaded_at = now
        return table

    def _get_regime_side_bonus(self, regime_label: str, side: str) -> Tuple[float, int]:
        """Live (bonus, n) for a (canonical regime, side) slice.

        bonus = clamp(avg_net_pnl_per_trade, -8.0, +8.0) when n>=13, else
        (0.0, 0) — neutral fallback, never a hardcoded directional block.
        """
        table = self._get_regime_side_table()
        try:
            from llm.regime_canonical import canonicalize_regime
            canon = canonicalize_regime(regime_label)
        except Exception:
            canon = regime_label
        norm_side = {"BUY": "LONG", "SELL": "SHORT"}.get((side or "").upper(), (side or "").upper())
        return table.get((canon, norm_side), (0.0, 0))

    def _classify_regime(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Classify current regime for conditional simulation."""
        adx_val = _adx(df)
        close = df["close"].astype(float)
        returns = close.pct_change().dropna()

        if len(returns) < 10:
            return {"regime": "unknown", "adx": adx_val, "vol": 0.01}

        vol = float(returns.std())
        vol_avg = float(returns.rolling(50, min_periods=10).std().iloc[-1])
        vol_ratio = vol / max(vol_avg, 1e-12)

        # Mean return (momentum)
        mean_ret = float(returns.iloc[-5:].mean())

        # Skewness (tail risk)
        skew = float(returns.iloc[-50:].skew()) if len(returns) >= 50 else 0.0

        if adx_val >= self.REGIME_TRENDING_ADX:
            regime = "trending"
        elif adx_val <= self.REGIME_RANGING_ADX:
            regime = "ranging"
        elif vol_ratio > 1.5:
            regime = "volatile"
        else:
            regime = "normal"

        return {
            "regime": regime,
            "adx": adx_val,
            "vol": vol,
            "vol_avg": vol_avg,
            "vol_ratio": vol_ratio,
            "mean_return": mean_ret,
            "skewness": skew,
        }

    def _get_regime_returns(self, returns: pd.Series, regime: Dict[str, Any]) -> np.ndarray:
        """Get return distribution conditioned on regime."""
        all_returns = returns.dropna().values

        if len(all_returns) < 20:
            return all_returns

        # For trending regime: use returns from trending periods (positive autocorrelation)
        if regime["regime"] == "trending":
            # Weight recent returns more heavily (momentum persistence)
            weights = np.exp(np.linspace(-1, 0, len(all_returns)))
            weights /= weights.sum()
            # Resample with momentum bias
            indices = np.random.choice(len(all_returns), size=len(all_returns), p=weights)
            return all_returns[indices]

        elif regime["regime"] == "ranging":
            # Mean-reverting: dampen extremes
            mean = np.mean(all_returns)
            dampened = mean + 0.7 * (all_returns - mean)  # 30% mean-reversion
            return dampened

        elif regime["regime"] == "volatile":
            # Fat tails: scale up variance
            return all_returns * regime["vol_ratio"]

        return all_returns

    def _run_monte_carlo(self, price: float, regime_returns: np.ndarray,
                          num_sims: int, forward_bars: int) -> Dict[str, Any]:
        """Run Monte Carlo simulation with antithetic variates."""
        n_returns = len(regime_returns)
        if n_returns < 5:
            return {"paths": np.full((num_sims, forward_bars), price)}

        # Half normal paths, half antithetic (variance reduction)
        half_sims = num_sims // 2

        # Sample returns for normal paths
        sampled_indices = np.random.randint(0, n_returns, size=(half_sims, forward_bars))
        sampled_returns = regime_returns[sampled_indices]

        # Antithetic variates: mirror the returns
        anti_returns = -sampled_returns

        # Combine
        all_returns = np.vstack([sampled_returns, anti_returns])

        # Generate price paths
        cumulative = np.cumprod(1.0 + all_returns, axis=1)
        paths = price * cumulative

        # Terminal prices
        terminal = paths[:, -1]

        # Probability cones
        percentiles = np.percentile(terminal, [5, 25, 50, 75, 95])

        # Max excursion (best and worst price reached during path)
        max_prices = np.max(paths, axis=1)
        min_prices = np.min(paths, axis=1)

        return {
            "paths": paths,
            "terminal": terminal,
            "percentiles": {
                "p5": percentiles[0],
                "p25": percentiles[1],
                "p50": percentiles[2],
                "p75": percentiles[3],
                "p95": percentiles[4],
            },
            "max_prices": max_prices,
            "min_prices": min_prices,
            "mean_terminal": float(np.mean(terminal)),
            "std_terminal": float(np.std(terminal)),
        }

    @staticmethod
    def _first_touch_idx(mask: np.ndarray) -> np.ndarray:
        """Index of first True per row; rows with no touch get a sentinel
        beyond the horizon so comparisons treat them as 'never'."""
        any_hit = mask.any(axis=1)
        idx = np.argmax(mask, axis=1).astype(np.int64)
        idx[~any_hit] = mask.shape[1] + 1
        return idx

    def _compute_probabilities(self, mc: Dict, price: float,
                                tp1: float, tp2: float, sl: float,
                                side: str) -> Dict[str, float]:
        """First-passage probabilities of TP1/TP2/SL over simulated paths.

        FALLACY_AUDIT M3 (2026-07-02): the old accounting used whole-path
        max/min excursion — a path that hit SL first and THEN rallied through
        TP1 counted as a TP1 win. Order of hit now decides: a target only
        counts if it is touched strictly BEFORE the stop (same-bar ties go to
        the stop, conservatively — intra-bar order is unknowable here).
        Realized check that motivated this: 53% WR / -0.04% avg vs the
        engine's internal +0.10-0.20 EV gate.
        """
        paths = mc["paths"]
        n_sims = paths.shape[0]

        if side == "BUY":
            tp1_mask = paths >= tp1
            tp2_mask = paths >= tp2
            sl_mask = paths <= sl
        else:
            tp1_mask = paths <= tp1
            tp2_mask = paths <= tp2
            sl_mask = paths >= sl

        first_tp1 = self._first_touch_idx(tp1_mask)
        first_tp2 = self._first_touch_idx(tp2_mask)
        first_sl = self._first_touch_idx(sl_mask)
        never = paths.shape[1] + 1

        prob_tp1 = float(np.sum((first_tp1 < first_sl) & (first_tp1 < never))) / n_sims
        prob_tp2 = float(np.sum((first_tp2 < first_sl) & (first_tp2 < never))) / n_sims
        # SL-first (ties included) — the loss mass the old math truncated
        prob_sl = float(np.sum((first_sl <= first_tp1) & (first_sl < never))) / n_sims

        return {
            "prob_tp1": prob_tp1,
            "prob_tp2": prob_tp2,
            "prob_sl": prob_sl,
        }

    def _compute_ev(self, probs: Dict[str, float], price: float,
                     tp1: float, tp2: float, sl: float,
                     symbol: str = "", side: str = "") -> float:
        """Compute expected value per dollar risked, net of fees."""
        risk = abs(price - sl)
        if risk <= 0:
            return -1.0

        reward_tp1 = abs(tp1 - price)
        reward_tp2 = abs(tp2 - price)
        fee_cost = price * self.ROUND_TRIP_FEE_BPS / 10000

        # Blended win probability (weighted toward TP1 since it's more likely).
        # w2 = live TP1->TP2 continuation weight (2026-07-15; was a static 30%
        # that overstated the realized 16.7% continuation rate by ~1.8x,
        # inflating EV on every signal). See _get_tp2_weight().
        w2 = self._get_tp2_weight(symbol, side, probs)
        prob_win = probs["prob_tp1"]
        avg_reward = (1 - w2) * reward_tp1 + w2 * reward_tp2

        ev = prob_win * (avg_reward - fee_cost) - (1 - prob_win) * (risk + fee_cost)
        ev_per_dollar = ev / risk if risk > 0 else -1.0

        return ev_per_dollar

    def evaluate(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df_1h = data.get("1h")
        if df_1h is None or len(df_1h) < 50:
            return None

        close = df_1h["close"].astype(float)
        price = float(close.iloc[-1])
        atr = float(_atr(df_1h).iloc[-1])

        if atr <= 0 or price <= 0:
            return None

        # Classify regime
        regime = self._classify_regime(df_1h)

        # Get regime-conditional returns
        returns = close.pct_change().dropna()
        regime_returns = self._get_regime_returns(returns, regime)

        if len(regime_returns) < 10:
            return None

        # Determine directional bias
        ema20 = float(_ema(close, 20).iloc[-1])
        ema50 = float(_ema(close, 50).iloc[-1])
        momentum = regime["mean_return"]

        # Strong directional bias needed
        if abs(momentum) < 0.001 and abs(ema20 - ema50) / price < 0.005:
            return None  # No clear direction

        side = "BUY" if momentum > 0 or ema20 > ema50 else "SELL"

        # TP/SL levels
        sl_mult = 1.5
        tp1_mult = 2.0
        tp2_mult = 3.5

        if regime["regime"] == "trending":
            tp2_mult = 4.0  # Trends run further
        elif regime["regime"] == "ranging":
            tp1_mult = 1.5  # Range = smaller targets
            tp2_mult = 2.5

        if side == "BUY":
            sl = price - atr * sl_mult
            tp1 = price + atr * tp1_mult
            tp2 = price + atr * tp2_mult
        else:
            sl = price + atr * sl_mult
            tp1 = price - atr * tp1_mult
            tp2 = price - atr * tp2_mult

        # Run Monte Carlo
        mc = self._run_monte_carlo(price, regime_returns, self.num_sims, self.forward_bars)

        # Compute probabilities
        probs = self._compute_probabilities(mc, price, tp1, tp2, sl, side)

        # Regime-conditional probability + EV thresholds — LIVE (2026-07-15).
        # 2026-06-06 froze this as a static table (trending 0.50/0.20, range
        # 0.42/0.12, else 0.35/0.10) that turned out inverted vs the realized
        # ledger: range/consolidation (worst realized edge) got the LOOSEST
        # gate while trending (best realized edge) got the TIGHTEST. Now
        # computed from data/trade_ledger.csv, self-updating. See
        # _get_regime_gate(). MIN_PROB_TP1/MIN_EV_PER_DOLLAR remain hard
        # safety floors — clamped inside _get_regime_gate().
        from trading_config import DEFAULT_SYMBOL_OVERRIDES
        _vol_prof = getattr(DEFAULT_SYMBOL_OVERRIDES.get(symbol), "volatility_profile", "medium") if symbol else "medium"
        _regime = regime.get("regime", "unknown")
        _min_prob, _min_ev = self._get_regime_gate(_regime)
        # Symbol-specific volatility profile adds further tightening for "high" vol
        if _vol_prof == "high":
            _min_prob = max(_min_prob, 0.48)
            _min_ev = max(_min_ev, 0.18)
        if probs["prob_tp1"] < _min_prob:
            return None

        # Compute expected value
        ev = self._compute_ev(probs, price, tp1, tp2, sl, symbol, side)

        if ev < _min_ev:
            return None

        # Confidence from probability + EV
        confidence = 50.0

        # Probability contribution — scale nonlinearly to reward high probabilities more
        # Old: linear (0.45→50, 0.70→62.5). New: steeper above 0.60 to reflect edge quality.
        prob_excess = probs["prob_tp1"] - 0.45
        confidence += prob_excess * 55 + max(0, prob_excess - 0.15) * 20  # bonus for >0.60

        # EV contribution — slightly higher weight (EV is the true edge metric)
        confidence += min(18.0, ev * 35)

        # Regime bonus — LIVE per-(regime, side) shift from the realized
        # ledger (2026-07-15; was a flat +8.0 "trend-aligned" bonus that
        # boosted LONG and SHORT identically despite the ledger showing them
        # as opposite-sign edges — trend-family LONG avg -$3.68/tr vs SHORT
        # avg +$8.03/tr). bonus = clamp(avg_net_pnl_per_trade, -8, +8) at
        # n>=13, else 0.0 (neutral — never a hardcoded directional block).
        _regime_side_bonus, _regime_side_n = self._get_regime_side_bonus(regime["regime"], side)
        if regime["regime"] == "trending" and (
            (side == "BUY" and momentum > 0) or (side == "SELL" and momentum < 0)
        ):
            confidence += _regime_side_bonus  # was flat +8.0

        # Probability ratio bonus (TP1 prob >> SL prob) — only rewarded when
        # the same live (regime, side) slice has realized positive edge at
        # n>=13; otherwise this is unproven and shouldn't be boosted.
        if probs["prob_sl"] > 0:
            prob_ratio = probs["prob_tp1"] / probs["prob_sl"]
            if prob_ratio > 2.0:
                if _regime_side_n >= self._LIVE_STATS_MIN_N and _regime_side_bonus > 0:
                    confidence += 5.0
            elif prob_ratio < 1.0:
                confidence -= 10.0  # safety penalty — unchanged, never weakened

        confidence = max(50.0, min(95.0, confidence))

        p = mc["percentiles"]
        context_parts = [
            f"MC Probability: P(TP1)={probs['prob_tp1']*100:.0f}% P(TP2)={probs['prob_tp2']*100:.0f}% P(SL)={probs['prob_sl']*100:.0f}%",
            f"EV={ev:+.3f}/$ risked ({self.num_sims} sims, {self.forward_bars}h fwd)",
            f"Regime: {regime['regime']} (ADX={regime['adx']:.1f}, vol_ratio={regime['vol_ratio']:.2f})",
            f"Price cone [5-95%]: ${p['p5']:.2f} - ${p['p95']:.2f}",
        ]

        sig = Signal(
            strategy="probability_engine",
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=price,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            atr=atr,
            metadata={
                "prob_tp1": probs["prob_tp1"],
                "prob_tp2": probs["prob_tp2"],
                "prob_sl": probs["prob_sl"],
                "expected_value": ev,
                "regime": regime["regime"],
                "regime_adx": regime["adx"],
                "regime_vol_ratio": regime["vol_ratio"],
                "mc_median": mc["percentiles"]["p50"],
                "mc_p5": mc["percentiles"]["p5"],
                "mc_p95": mc["percentiles"]["p95"],
                "num_sims": self.num_sims,
                "forward_bars": self.forward_bars,
                # 2026-07-15: shaped confidence vs the live inputs that
                # produced it, so /confidence-calibrate can later fit the
                # base scaling against realized outcomes too.
                "confidence_shaped": confidence,
                "regime_side_bonus": _regime_side_bonus,
                "regime_side_bonus_n": _regime_side_n,
            },
            signal_context=" | ".join(context_parts),
        )

        if not sig.is_valid:
            return None

        logger.info(f"[{symbol}] Probability Engine signal: {side} conf={confidence:.0f}% "
                     f"P(TP1)={probs['prob_tp1']*100:.0f}% EV={ev:+.3f} "
                     f"regime={regime['regime']}")
        return sig

    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        df_1h = data.get("1h")
        if df_1h is None or len(df_1h) < 50:
            return {"strategy": self.name, "symbol": symbol, "state": "insufficient_data"}

        regime = self._classify_regime(df_1h)
        return {
            "strategy": self.name,
            "symbol": symbol,
            "regime": regime["regime"],
            "adx": regime["adx"],
            "vol_ratio": regime.get("vol_ratio", 0),
        }
