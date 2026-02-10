"""
Strategy 1: Monte Carlo Zone Bot
Ported from the user's original profitable bot (Bot 1).

Core logic:
- SMA20/SMA50/RSI14 indicators
- Zone computation using risk multipliers x stdev
- Monte Carlo simulation (1000 sims, 12h forward) for price prediction
- Generates BUY/SELL signals based on zone position + MC probability
"""

import random
import statistics
import logging
from typing import Optional, Dict, Any, List

import pandas as pd

from .base import BaseStrategy, Signal
from trading_config import RISK_MULTIPLIERS

logger = logging.getLogger("bot.strategy.monte_carlo")


class MonteCarloZonesStrategy(BaseStrategy):
    """
    Zone-based strategy with Monte Carlo probabilistic predictions.
    Uses SMA20 +/- k*stdev zones to define buy/sell regions,
    then Monte Carlo sims to estimate 12h forward probability.
    """

    def __init__(self, symbols: Dict[str, Any], mc_sims: int = 1000, mc_hours: int = 12):
        super().__init__("monte_carlo_zones", symbols)
        self.mc_sims = mc_sims
        self.mc_hours = mc_hours

    def get_required_timeframes(self) -> List[str]:
        return ["daily"]  # uses CoinGecko daily data

    def _calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) < 50:
            return df
        df = df.copy()
        df["SMA20"] = df["close"].rolling(20).mean()
        df["SMA50"] = df["close"].rolling(50).mean()

        delta = df["close"].diff()
        up = delta.clip(lower=0)
        down = -delta.clip(upper=0)
        roll_up = up.rolling(14).mean()
        roll_down = down.rolling(14).mean()
        df["RSI14"] = 100 - (100 / (1 + roll_up / roll_down.replace(0, 1e-12)))

        df["vol_spike"] = df["volume"] > 2 * df["volume"].rolling(20).mean()
        return df

    def _compute_zones(self, df: pd.DataFrame, risk_tier: str) -> Optional[Dict]:
        if len(df) < 20 or risk_tier not in RISK_MULTIPLIERS:
            return None
        sma20 = df["SMA20"].iloc[-1]
        if pd.isna(sma20):
            return None
        stdev = statistics.stdev(df["close"].iloc[-20:].tolist())
        if stdev == 0:
            return None
        reg_k, deep_k = RISK_MULTIPLIERS[risk_tier]
        return {
            "deep_buy": max(0, sma20 - deep_k * stdev),
            "regular_buy": max(0, sma20 - reg_k * stdev),
            "regular_sell": sma20 + reg_k * stdev,
            "safe_sell": sma20 + deep_k * stdev,
            "current": df["close"].iloc[-1],
            "sma20": sma20,
            "stdev": stdev,
        }

    def _monte_carlo(self, df: pd.DataFrame) -> Dict[str, float]:
        if len(df) < 2:
            return {"future_price": df["close"].iloc[-1], "up_prob": 0.5, "down_prob": 0.5}

        returns = df["close"].pct_change().dropna().tolist()
        if not returns:
            return {"future_price": df["close"].iloc[-1], "up_prob": 0.5, "down_prob": 0.5}

        current = df["close"].iloc[-1]
        final_prices = []
        for _ in range(self.mc_sims):
            price = current
            for _ in range(self.mc_hours):
                shock = random.choice(returns)
                price *= 1 + shock
            final_prices.append(price)

        future_price = statistics.mean(final_prices)
        up_prob = sum(1 for p in final_prices if p > current) / self.mc_sims
        return {
            "future_price": future_price,
            "up_prob": up_prob,
            "down_prob": 1 - up_prob,
        }

    def _zone_action(self, zones: Dict) -> str:
        c = zones["current"]
        if c <= zones["deep_buy"]:
            return "DEEP_BUY"
        if c <= zones["regular_buy"]:
            return "BUY"
        if c >= zones["safe_sell"]:
            return "SAFE_SELL"
        if c >= zones["regular_sell"]:
            return "SELL"
        return "HOLD"

    def evaluate(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Optional[Signal]:
        df = data.get("daily")
        if df is None or len(df) < 50:
            return None

        sym_config = self.symbols.get(symbol)
        if sym_config is None:
            return None

        df = self._calculate_indicators(df)
        risk_tier = sym_config.risk_tier if hasattr(sym_config, "risk_tier") else sym_config.get("risk", "medium")
        zones = self._compute_zones(df, risk_tier)
        if zones is None:
            return None

        mc = self._monte_carlo(df)
        action = self._zone_action(zones)
        rsi = df["RSI14"].iloc[-1] if "RSI14" in df.columns else 50
        vol_spike = bool(df["vol_spike"].iloc[-1]) if "vol_spike" in df.columns else False
        current = zones["current"]
        stdev = zones["stdev"]

        # Build confidence score
        confidence = 50.0  # base

        if action == "DEEP_BUY":
            confidence += 20
            if mc["up_prob"] > 0.6:
                confidence += 15
            if rsi < 30:
                confidence += 10
            if vol_spike and mc["up_prob"] > 0.55:
                confidence += 5
            side = "BUY"
            sl = current - 2.0 * stdev
            tp1 = zones["regular_buy"]
            tp2 = zones["sma20"]

        elif action == "BUY":
            confidence += 10
            if mc["up_prob"] > 0.55:
                confidence += 10
            if rsi < 40:
                confidence += 5
            if vol_spike and mc["up_prob"] > 0.5:
                confidence += 5
            side = "BUY"
            sl = zones["deep_buy"] - 0.5 * stdev
            tp1 = zones["sma20"]
            tp2 = zones["regular_sell"]

        elif action == "SAFE_SELL":
            confidence += 20
            if mc["down_prob"] > 0.6:
                confidence += 15
            if rsi > 70:
                confidence += 10
            if vol_spike and mc["down_prob"] > 0.55:
                confidence += 5
            side = "SELL"
            sl = current + 2.0 * stdev
            tp1 = zones["regular_sell"]
            tp2 = zones["sma20"]

        elif action == "SELL":
            confidence += 10
            if mc["down_prob"] > 0.55:
                confidence += 10
            if rsi > 60:
                confidence += 5
            if vol_spike and mc["down_prob"] > 0.5:
                confidence += 5
            side = "SELL"
            sl = zones["safe_sell"] + 0.5 * stdev
            tp1 = zones["sma20"]
            tp2 = zones["regular_buy"]

        else:
            return None  # HOLD

        confidence = min(confidence, 100)

        if confidence < 60:
            return None

        return Signal(
            strategy=self.name,
            symbol=symbol,
            side=side,
            confidence=confidence,
            entry=current,
            sl=sl,
            tp1=tp1,
            tp2=tp2,
            metadata={
                "action": action,
                "zones": zones,
                "mc": mc,
                "rsi": float(rsi),
                "vol_spike": vol_spike,
            },
        )

    def get_status(self, symbol: str, data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        df = data.get("daily")
        if df is None or len(df) < 50:
            return {"symbol": symbol, "strategy": self.name, "status": "insufficient_data"}

        sym_config = self.symbols.get(symbol)
        if sym_config is None:
            return {"symbol": symbol, "strategy": self.name, "status": "no_config"}

        df = self._calculate_indicators(df)
        risk_tier = sym_config.risk_tier if hasattr(sym_config, "risk_tier") else sym_config.get("risk", "medium")
        zones = self._compute_zones(df, risk_tier)
        mc = self._monte_carlo(df)
        action = self._zone_action(zones) if zones else "UNKNOWN"

        return {
            "symbol": symbol,
            "strategy": self.name,
            "action": action,
            "zones": zones,
            "mc_prediction": mc,
            "rsi": float(df["RSI14"].iloc[-1]) if "RSI14" in df.columns else None,
            "vol_spike": bool(df["vol_spike"].iloc[-1]) if "vol_spike" in df.columns else None,
            "price": float(df["close"].iloc[-1]),
        }
