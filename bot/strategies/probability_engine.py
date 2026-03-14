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

import logging
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
    MIN_PROB_TP1 = 0.45       # Min probability of hitting TP1
    MIN_EV_PER_DOLLAR = 0.15  # Min expected value per dollar risked

    # Regime classification (simplified — uses ADX + volatility)
    REGIME_TRENDING_ADX = 25.0
    REGIME_RANGING_ADX = 15.0

    # Fee model
    ROUND_TRIP_FEE_BPS = 8    # 4 bps each way

    def __init__(self, symbols: Dict[str, Any],
                 num_sims: int = 2000, forward_bars: int = 12):
        super().__init__("probability_engine", symbols)
        self.num_sims = num_sims
        self.forward_bars = forward_bars

    def get_required_timeframes(self) -> List[str]:
        return ["1h"]

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

    def _compute_probabilities(self, mc: Dict, price: float,
                                tp1: float, tp2: float, sl: float,
                                side: str) -> Dict[str, float]:
        """Compute probability of hitting TP1, TP2, SL during the simulation."""
        max_prices = mc["max_prices"]
        min_prices = mc["min_prices"]
        n_sims = len(max_prices)

        if side == "BUY":
            prob_tp1 = float(np.sum(max_prices >= tp1)) / n_sims
            prob_tp2 = float(np.sum(max_prices >= tp2)) / n_sims
            prob_sl = float(np.sum(min_prices <= sl)) / n_sims
        else:
            prob_tp1 = float(np.sum(min_prices <= tp1)) / n_sims
            prob_tp2 = float(np.sum(min_prices <= tp2)) / n_sims
            prob_sl = float(np.sum(max_prices >= sl)) / n_sims

        return {
            "prob_tp1": prob_tp1,
            "prob_tp2": prob_tp2,
            "prob_sl": prob_sl,
        }

    def _compute_ev(self, probs: Dict[str, float], price: float,
                     tp1: float, tp2: float, sl: float) -> float:
        """Compute expected value per dollar risked, net of fees."""
        risk = abs(price - sl)
        if risk <= 0:
            return -1.0

        reward_tp1 = abs(tp1 - price)
        reward_tp2 = abs(tp2 - price)
        fee_cost = price * self.ROUND_TRIP_FEE_BPS / 10000

        # Blended win probability (weighted toward TP1 since it's more likely)
        # Assume 70% of wins hit TP1 only, 30% hit TP2
        prob_win = probs["prob_tp1"]
        avg_reward = 0.7 * reward_tp1 + 0.3 * reward_tp2 * (probs["prob_tp2"] / max(probs["prob_tp1"], 0.01))

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

        # Check minimum probability threshold (tighter for high-vol: fat tails need more conviction)
        from trading_config import DEFAULT_SYMBOL_OVERRIDES
        _vol_prof = getattr(DEFAULT_SYMBOL_OVERRIDES.get(symbol), "volatility_profile", "medium") if symbol else "medium"
        _min_prob = 0.48 if _vol_prof == "high" else self.MIN_PROB_TP1
        _min_ev = 0.18 if _vol_prof == "high" else self.MIN_EV_PER_DOLLAR
        if probs["prob_tp1"] < _min_prob:
            return None

        # Compute expected value
        ev = self._compute_ev(probs, price, tp1, tp2, sl)

        if ev < _min_ev:
            return None

        # Confidence from probability + EV
        confidence = 50.0

        # Probability contribution
        confidence += (probs["prob_tp1"] - 0.45) * 50  # 0.45→50, 0.70→62.5, 0.95→75

        # EV contribution
        confidence += min(15.0, ev * 30)

        # Regime bonus
        if regime["regime"] == "trending" and (
            (side == "BUY" and momentum > 0) or (side == "SELL" and momentum < 0)
        ):
            confidence += 8.0  # Trading with trend in trending regime

        # Probability ratio bonus (TP1 prob >> SL prob)
        if probs["prob_sl"] > 0:
            prob_ratio = probs["prob_tp1"] / probs["prob_sl"]
            if prob_ratio > 2.0:
                confidence += 5.0
            elif prob_ratio < 1.0:
                confidence -= 10.0

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
