"""
Strategy 2: Confidence Scoring Bot
Ported from the user's original profitable bot (Bot 2).

Core logic:
- Same zone system as Monte Carlo bot
- Tracks historical signal accuracy per (symbol, signal_type)
- Adjusts confidence based on observed win rates
- Evaluates signals after the fact to build confidence scores
"""

import json
import os
import statistics
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path

import pandas as pd

from .base import BaseStrategy, Signal
from trading_config import RISK_MULTIPLIERS

logger = logging.getLogger("bot.strategy.confidence_scorer")


class ConfidenceScorerStrategy(BaseStrategy):
    """
    Zone-based strategy that tracks its own accuracy and adjusts
    confidence based on historical performance per (symbol, signal_type).
    """

    def __init__(self, symbols: Dict[str, Any], data_dir: str = "ml_data"):
        super().__init__("confidence_scorer", symbols)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.signal_log_path = self.data_dir / "confidence_signal_log.json"
        self.signal_log = self._load_signal_log()

    def get_required_timeframes(self) -> List[str]:
        return ["daily"]

    def _load_signal_log(self) -> Dict:
        if self.signal_log_path.exists():
            try:
                with open(self.signal_log_path) as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_signal_log(self):
        try:
            with open(self.signal_log_path, "w") as f:
                json.dump(self.signal_log, f, indent=2, default=str)
        except Exception as e:
            logger.warning(f"Failed to save signal log: {e}")

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
        stdev = statistics.pstdev(df["close"].iloc[-20:].tolist())
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

    def _detect_bounce_short(self, df: pd.DataFrame, zones: Dict) -> bool:
        """Detect bounce-to-resistance in downtrend (short setup).
        Returns True if price is bouncing toward SMA20 in a confirmed downtrend."""
        if len(df) < 20:
            return False

        current = zones["current"]
        sma20 = zones["sma20"]
        stdev = zones["stdev"]

        sma50 = df["SMA50"].iloc[-1] if "SMA50" in df.columns else None
        if sma50 is None or pd.isna(sma50):
            return False

        # Downtrend: SMA20 < SMA50
        if not (sma20 < sma50):
            return False

        # Price bounced from recent low
        recent_low = float(df["close"].iloc[-5:].min())
        bounce = current - recent_low
        if bounce < 0.3 * stdev:
            return False

        # Price near or above SMA20 (resistance)
        if current > sma20 - 0.5 * stdev:
            return True

        return False

    def _log_signal(self, symbol: str, action: str, price: float):
        """Record a signal for later evaluation."""
        if symbol not in self.signal_log:
            self.signal_log[symbol] = []
        self.signal_log[symbol].append({
            "signal": action,
            "price": price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evaluated": False,
        })
        # Keep last 200 signals per symbol
        self.signal_log[symbol] = self.signal_log[symbol][-200:]
        self._save_signal_log()

    def _get_historical_confidence(self, symbol: str, action: str) -> Optional[float]:
        """
        Calculate win rate for this (symbol, action) pair from historical data.
        Returns None if insufficient data.
        """
        entries = self.signal_log.get(symbol, [])
        evaluated = [e for e in entries if e.get("evaluated") and e["signal"] == action and "success" in e]
        if len(evaluated) < 5:
            return None
        wins = sum(1 for e in evaluated if e["success"])
        return wins / len(evaluated)

    def evaluate_past_signals(self, symbol: str, current_price: float):
        """
        Look back at unresolved signals and mark them as success/failure
        based on price movement since signal.
        """
        entries = self.signal_log.get(symbol, [])
        changed = False
        for e in entries:
            if e["evaluated"]:
                continue
            # Only evaluate if signal is at least a few data points old
            price_at_signal = e["price"]
            pct_move = (current_price - price_at_signal) / price_at_signal * 100

            success = False
            if e["signal"] == "DEEP_BUY" and pct_move > 1.0:
                success = True
            elif e["signal"] == "BUY" and pct_move > 0.5:
                success = True
            elif e["signal"] == "SELL" and pct_move < -0.5:
                success = True
            elif e["signal"] == "SAFE_SELL" and pct_move < -1.0:
                success = True

            e["evaluated"] = True
            e["success"] = success
            e["exit_price"] = current_price
            e["pct_move"] = pct_move
            changed = True

        if changed:
            self._save_signal_log()

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

        current = zones["current"]
        stdev = zones["stdev"]

        # Evaluate past signals with current price
        self.evaluate_past_signals(symbol, current)

        action = self._zone_action(zones)

        rsi = df["RSI14"].iloc[-1] if "RSI14" in df.columns else 50
        vol_spike = bool(df["vol_spike"].iloc[-1]) if "vol_spike" in df.columns else False

        # Bounce-short in HOLD zone: detect downtrend bounces to resistance
        if action == "HOLD":
            if self._detect_bounce_short(df, zones):
                action = "BOUNCE_SHORT"
            else:
                return None

        # Base confidence from zone position
        confidence = 50.0
        if action in ("DEEP_BUY", "SAFE_SELL"):
            confidence += 20
        elif action == "BOUNCE_SHORT":
            confidence += 12
        else:
            confidence += 10

        # RSI boost
        if action in ("DEEP_BUY", "BUY") and rsi < 35:
            confidence += 10
        elif action in ("SELL", "SAFE_SELL") and rsi > 65:
            confidence += 10
        elif action == "BOUNCE_SHORT" and rsi > 45:
            confidence += 8  # not oversold = room to drop

        # Volume spike boost
        if vol_spike:
            confidence += 5

        # Historical accuracy adjustment (the key differentiator of this strategy)
        hist_action = action if action != "BOUNCE_SHORT" else "SELL"
        hist_conf = self._get_historical_confidence(symbol, hist_action)
        if hist_conf is not None:
            adjustment = (hist_conf - 0.5) * 30  # -15 to +15
            confidence += adjustment
            logger.info(
                f"[{symbol}] {action} historical confidence={hist_conf:.0%}, "
                f"adjustment={adjustment:+.1f}, final={confidence:.1f}"
            )

        # If BUY action has terrible historical win rate, consider flipping to short
        if action in ("DEEP_BUY", "BUY") and hist_conf is not None and hist_conf < 0.15:
            if self._detect_bounce_short(df, zones):
                logger.info(
                    f"[{symbol}] {action} win rate {hist_conf:.0%} too low + bounce detected -> flipping to SHORT"
                )
                action = "BOUNCE_SHORT"
                confidence = 55.0  # reset base
                if rsi > 45:
                    confidence += 8
                if vol_spike:
                    confidence += 5

        confidence = max(0, min(100, confidence))

        # Log this signal
        self._log_signal(symbol, action, current)

        if confidence < 60:
            return None

        # Determine side and levels
        if action in ("DEEP_BUY", "BUY"):
            side = "BUY"
            sl = zones["deep_buy"] - stdev if action == "BUY" else current - 2.5 * stdev
            tp1 = zones["sma20"]
            tp2 = zones["regular_sell"]
        elif action == "BOUNCE_SHORT":
            side = "SELL"
            sl = zones["sma20"] + 0.8 * stdev  # stop above SMA20 resistance
            tp1 = zones["regular_buy"]
            tp2 = zones["deep_buy"]
        else:
            side = "SELL"
            sl = zones["safe_sell"] + stdev if action == "SELL" else current + 2.5 * stdev
            tp1 = zones["sma20"]
            tp2 = zones["regular_buy"]

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
                "rsi": float(rsi),
                "vol_spike": vol_spike,
                "historical_confidence": hist_conf,
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
        action = self._zone_action(zones) if zones else "UNKNOWN"

        # Get all historical confidence scores
        conf_scores = {}
        for act in ["DEEP_BUY", "BUY", "SELL", "SAFE_SELL"]:
            hc = self._get_historical_confidence(symbol, act)
            if hc is not None:
                conf_scores[act] = hc

        return {
            "symbol": symbol,
            "strategy": self.name,
            "action": action,
            "zones": zones,
            "rsi": float(df["RSI14"].iloc[-1]) if "RSI14" in df.columns else None,
            "vol_spike": bool(df["vol_spike"].iloc[-1]) if "vol_spike" in df.columns else None,
            "historical_confidence": conf_scores,
            "total_signals_logged": sum(
                len(v) for v in self.signal_log.values()
            ),
            "price": float(df["close"].iloc[-1]),
        }

    def get_performance_report(self) -> Dict[str, Any]:
        """Generate a performance report from signal history."""
        report = {}
        for symbol, entries in self.signal_log.items():
            evaluated = [e for e in entries if e.get("evaluated") and "success" in e]
            if not evaluated:
                continue

            by_type = {}
            for sig_type in ["DEEP_BUY", "BUY", "SELL", "SAFE_SELL"]:
                sigs = [e for e in evaluated if e["signal"] == sig_type]
                if sigs:
                    wins = sum(1 for s in sigs if s["success"])
                    by_type[sig_type] = {
                        "total": len(sigs),
                        "wins": wins,
                        "win_rate": wins / len(sigs),
                    }

            total = len(evaluated)
            total_wins = sum(1 for e in evaluated if e["success"])
            report[symbol] = {
                "total_signals": total,
                "overall_win_rate": total_wins / total if total else 0,
                "by_type": by_type,
            }
        return report
