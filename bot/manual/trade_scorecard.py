"""
Pre-Trade Quality Scorecard.

Scores every potential trade 0-100 on 7 dimensions to prevent junk entries.
Data-driven: calibrated from the 3 HYPE losses (1-agree, 60-62% conf, bad regimes)
which all score <30 here, while the SOL SELL winner scores 70+.

Minimum threshold: 50 to enter. 70+ = full size. 50-69 = half size.

Dimensions:
1. CONFIDENCE (25 pts) - Raw signal confidence from strategies
2. CONSENSUS  (25 pts) - Number of strategies agreeing
3. EDGE TREND (15 pts) - Is this setup's edge improving or decaying?
4. REGIME QUALITY (15 pts) - Is the regime aligned with trade direction?
5. VOL REGIME (10 pts) - Are we in the optimal volatility band?
6. TIME OF DAY (15 pts) - Granular intraday seasonality (hour + day-of-week)
7. VOLUME CONFIRMATION (10 pts) - Is volume confirming the move? (+10 if >1.2x, -5 if <0.5x)
"""

import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger("bot.manual.trade_scorecard")

# ── Edge trend classification per setup ──
# Updated from comprehensive edge study data.
# "strengthening" = WR improving over trailing window
# "stable"        = WR flat
# "weakening"     = WR declining
EDGE_TRENDS: Dict[str, str] = {
    "HYPE_BUY":  "weakening",      # 64% -> 40% WR over 500h study
    "HYPE_SELL": "weakening",      # Toxic, 0-7% WR
    "SOL_SELL":  "strengthening",  # 35% -> 68% WR over 500h study
    "SOL_BUY":   "stable",         # No validated edge, flat
    "BTC_BUY":   "stable",         # 56% WR, PF 1.40 — not enough data
    "BTC_SELL":  "weakening",      # Confirmed negative EV overall
}

# ── Regime alignment mapping ──
# Maps regime name to quality category.
REGIME_QUALITY: Dict[str, str] = {
    "trend":          "aligned",
    "trending_bull":  "aligned",
    "trending_bear":  "aligned",
    "consolidation":  "neutral",
    "range":          "neutral",
    "low_liquidity":  "neutral",
    "high_volatility": "dangerous",
    "panic":          "dangerous",
    "unknown":        "dangerous",
    "news_dislocation": "dangerous",
}

# Minimum score to enter any trade
SCORECARD_MIN_SCORE = 50

# Score thresholds for sizing
SCORECARD_FULL_SIZE_SCORE = 70
SCORECARD_HALF_SIZE_SCORE = 50


@dataclass
class ScorecardResult:
    """Result of a pre-trade quality scorecard evaluation."""
    total_score: int
    passed: bool
    size_factor: float          # 1.0 = full, 0.5 = half, 0.0 = reject
    components: Dict[str, int]  # dimension -> points awarded
    max_components: Dict[str, int]  # dimension -> max possible points
    reason: str                 # Human-readable summary

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TradeScorecard:
    """
    Pre-trade quality gate that scores each potential trade 0-100.

    Prevents junk entries by requiring a minimum composite score
    across 6 orthogonal quality dimensions.
    """

    def __init__(
        self,
        min_score: int = SCORECARD_MIN_SCORE,
        full_size_score: int = SCORECARD_FULL_SIZE_SCORE,
        half_size_score: int = SCORECARD_HALF_SIZE_SCORE,
        log_path: Optional[str] = None,
    ):
        self.min_score = min_score
        self.full_size_score = full_size_score
        self.half_size_score = half_size_score
        self._log_path = log_path or os.path.join(
            "data", "manual", "trade_scorecards.jsonl"
        )
        os.makedirs(os.path.dirname(self._log_path), exist_ok=True)

    # ──────────────────────────────────────────────
    # 1. CONFIDENCE (25 pts max)
    # ──────────────────────────────────────────────
    @staticmethod
    def _score_confidence(confidence: float) -> int:
        if confidence >= 85:
            return 25
        elif confidence >= 80:
            return 20
        elif confidence >= 75:
            return 15
        elif confidence >= 70:
            return 8
        elif confidence >= 60:
            return 3
        else:
            return 0

    # ──────────────────────────────────────────────
    # 2. CONSENSUS (25 pts max)
    # Solo signals from proven setups (SOL_SELL, BTC_BUY) get partial
    # credit — they were being blocked at 0pts despite positive edge.
    # ──────────────────────────────────────────────
    @staticmethod
    def _score_consensus(num_agree: int) -> int:
        if num_agree >= 3:
            return 25
        elif num_agree >= 2:
            return 15
        elif num_agree == 1:
            return 5
        else:
            return 0

    # ──────────────────────────────────────────────
    # 3. EDGE TREND (15 pts max)
    # ──────────────────────────────────────────────
    @staticmethod
    def _score_edge_trend(setup_key: str) -> int:
        trend = EDGE_TRENDS.get(setup_key, "stable")
        if trend == "strengthening":
            return 15
        elif trend == "stable":
            return 10
        else:  # weakening
            return 0

    # ──────────────────────────────────────────────
    # 4. REGIME QUALITY (15 pts max, can go negative)
    # ──────────────────────────────────────────────
    @staticmethod
    def _score_regime(regime: str, side: str) -> int:
        regime_lower = regime.lower() if regime else "unknown"
        quality = REGIME_QUALITY.get(regime_lower, "neutral")

        if quality == "dangerous":
            return -10
        elif quality == "neutral":
            return 10
        else:
            # "aligned" — check if regime direction matches trade side
            # Trending bull + BUY = aligned. Trending bear + SELL = aligned.
            # Otherwise counter-trend (still better than dangerous).
            bull_regimes = {"trending_bull"}
            bear_regimes = {"trending_bear"}
            if regime_lower in bull_regimes and side == "BUY":
                return 15
            elif regime_lower in bear_regimes and side == "SELL":
                return 15
            elif regime_lower in bull_regimes and side == "SELL":
                return 0  # Counter-trend
            elif regime_lower in bear_regimes and side == "BUY":
                return 0  # Counter-trend
            else:
                # Generic "trend" or "aligned" — give full points
                return 15

    # ──────────────────────────────────────────────
    # 5. VOL REGIME (10 pts max, can go negative)
    # ──────────────────────────────────────────────
    @staticmethod
    def _score_vol_regime(
        setup_key: str, atr: Optional[float], entry_price: Optional[float]
    ) -> int:
        if atr is None or entry_price is None or entry_price <= 0:
            return 5  # Unknown vol = neutral

        try:
            atr_pct = (float(atr) / float(entry_price)) * 100.0
        except (ValueError, TypeError, ZeroDivisionError):
            return 5

        # Setup-specific optimal vol bands (from edge study)
        if setup_key == "HYPE_BUY":
            if 1.40 <= atr_pct <= 1.69:
                return 10  # Optimal: PF 3.51
            elif 1.15 <= atr_pct <= 1.90:
                return 5   # Normal range
            else:
                return -5  # Extreme (too low or too high)
        elif setup_key == "SOL_SELL":
            if 0.80 <= atr_pct <= 0.98:
                return 10  # Optimal: PF 1.75
            elif 0.60 <= atr_pct <= 1.20:
                return 5   # Normal range
            else:
                return -5  # Extreme
        elif setup_key == "BTC_BUY":
            if 0.92 <= atr_pct <= 1.03:
                return 10  # Optimal: PF 3.13
            elif 0.77 <= atr_pct <= 1.10:
                return 5   # Normal
            else:
                return -5
        else:
            # Unknown setup — use generic bands
            if 0.50 <= atr_pct <= 2.00:
                return 5   # Normal
            else:
                return -5  # Extreme

    # ──────────────────────────────────────────────
    # 6. TIME OF DAY (12 pts max, can go negative)
    #    Granular intraday seasonality from backtest:
    #    - 18-20 UTC: peak alpha (76% WR BTC, 62% SOL)
    #    - 09-11 UTC: HYPE sweet spot
    #    - 14-15 UTC: US open dip (bearish, bad for BUY)
    #    - 04-06 UTC: dead zone, low liquidity
    #    Day-of-week: Monday +3, Thursday -3
    # ──────────────────────────────────────────────
    @staticmethod
    def _score_time_of_day(
        utc_hour: Optional[int] = None,
        side: Optional[str] = None,
        weekday: Optional[int] = None,
    ) -> int:
        if utc_hour is None:
            utc_hour = datetime.now(timezone.utc).hour
        if weekday is None:
            weekday = datetime.now(timezone.utc).weekday()  # 0=Monday

        score = 0

        # Hour-based scoring
        if 18 <= utc_hour <= 20:
            score = 12   # Peak alpha window
        elif 9 <= utc_hour <= 11:
            score = 8    # HYPE sweet spot
        elif 14 <= utc_hour <= 15:
            # US open dip: bad for BUY, good for SELL
            if side == "SELL":
                score = 5
            else:
                score = -5
        elif 4 <= utc_hour <= 6:
            score = -3   # Dead zone, low liquidity
        elif utc_hour >= 21 or utc_hour < 4:
            score = 5    # Decent overnight hours
        else:
            score = 0    # Neutral (7-8, 12-13, 16-17)

        # Day-of-week adjustment
        if weekday == 0:    # Monday
            score += 3
        elif weekday == 3:  # Thursday
            score -= 3

        return score

    # ──────────────────────────────────────────────
    # 7. VOLUME CONFIRMATION (10 pts max, can go negative)
    # ──────────────────────────────────────────────
    @staticmethod
    def _score_volume_confirmation(vol_ratio: Optional[float]) -> int:
        """Score based on volume ratio vs 20-period average.

        > 1.2x avg = confirmed move (+10)
        0.8-1.2x   = normal (0)
        0.5-0.8x   = low volume (-0, neutral)
        < 0.5x     = dead market, likely fake move (-5)
        """
        if vol_ratio is None or vol_ratio <= 0:
            return 0  # No volume data = neutral
        if vol_ratio >= 1.2:
            return 10
        elif vol_ratio >= 0.8:
            return 0
        elif vol_ratio >= 0.5:
            return 0
        else:
            return -5

    # ──────────────────────────────────────────────
    # Main scoring entry point
    # ──────────────────────────────────────────────
    def score(
        self,
        symbol: str,
        side: str,
        confidence: float,
        num_agree: int,
        regime: str,
        atr: Optional[float] = None,
        entry_price: Optional[float] = None,
        utc_hour: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ScorecardResult:
        """
        Score a potential trade on 7 quality dimensions.

        Args:
            symbol: Trading pair (e.g., "HYPE", "SOL", "BTC")
            side: "BUY" or "SELL"
            confidence: Signal confidence 0-100
            num_agree: Number of strategies in agreement
            regime: Current market regime string
            atr: Current ATR value (optional, for vol scoring)
            entry_price: Entry price (optional, for vol scoring)
            utc_hour: Override UTC hour for testing (optional)
            metadata: Additional signal metadata (optional)
                      - vol_ratio: current volume / 20-period avg volume

        Returns:
            ScorecardResult with score, pass/fail, and size factor
        """
        setup_key = f"{symbol}_{side}"
        meta = metadata or {}

        # Allow ATR/entry from metadata if not passed directly
        if atr is None:
            atr = meta.get("atr")
        if entry_price is None:
            entry_price = meta.get("entry", meta.get("price"))

        # Volume ratio from metadata (set by anticipatory engine or caller)
        vol_ratio = meta.get("vol_ratio")

        # Score each dimension
        c_confidence = self._score_confidence(confidence)
        c_consensus = self._score_consensus(num_agree)
        c_edge = self._score_edge_trend(setup_key)
        c_regime = self._score_regime(regime, side)
        c_vol = self._score_vol_regime(setup_key, atr, entry_price)
        # Extract weekday from metadata or use current
        weekday = meta.get("weekday")
        c_time = self._score_time_of_day(utc_hour, side=side, weekday=weekday)
        c_volume_conf = self._score_volume_confirmation(vol_ratio)

        components = {
            "confidence": c_confidence,
            "consensus": c_consensus,
            "edge_trend": c_edge,
            "regime_quality": c_regime,
            "vol_regime": c_vol,
            "time_of_day": c_time,
            "volume_confirmation": c_volume_conf,
        }

        max_components = {
            "confidence": 25,
            "consensus": 25,
            "edge_trend": 15,
            "regime_quality": 15,
            "vol_regime": 10,
            "time_of_day": 15,
            "volume_confirmation": 10,
        }

        total = sum(components.values())
        # Clamp to 0-100
        total = max(0, min(100, total))

        # Determine pass/fail and sizing
        if total >= self.full_size_score:
            passed = True
            size_factor = 1.0
            reason = f"PASS (score {total}/100) - full size"
        elif total >= self.half_size_score:
            passed = True
            size_factor = 0.5
            reason = f"PASS (score {total}/100) - half size"
        else:
            passed = False
            size_factor = 0.0
            reason = f"REJECT (score {total}/100 < min {self.min_score})"

        result = ScorecardResult(
            total_score=total,
            passed=passed,
            size_factor=size_factor,
            components=components,
            max_components=max_components,
            reason=reason,
        )

        # Log every evaluation
        self._log_evaluation(
            symbol=symbol,
            side=side,
            confidence=confidence,
            num_agree=num_agree,
            regime=regime,
            setup_key=setup_key,
            result=result,
        )

        return result

    def _log_evaluation(
        self,
        symbol: str,
        side: str,
        confidence: float,
        num_agree: int,
        regime: str,
        setup_key: str,
        result: ScorecardResult,
    ) -> None:
        """Log scorecard evaluation to JSONL for learning."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "side": side,
            "setup_key": setup_key,
            "confidence": confidence,
            "num_agree": num_agree,
            "regime": regime,
            "total_score": result.total_score,
            "passed": result.passed,
            "size_factor": result.size_factor,
            "components": result.components,
            "reason": result.reason,
        }
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.warning(f"[SCORECARD] Failed to log: {e}")

    def format_scorecard(self, result: ScorecardResult) -> str:
        """Format scorecard as a compact multi-line string for alerts."""
        lines = [
            f"{'PASS' if result.passed else 'REJECT'} {result.total_score}/100",
        ]
        for dim, pts in result.components.items():
            max_pts = result.max_components.get(dim, 0)
            bar = "+" * max(0, pts) + "-" * max(0, max_pts - max(0, pts))
            label = dim.replace("_", " ").title()
            lines.append(f"  {label}: {pts}/{max_pts} [{bar}]")
        if result.passed:
            lines.append(f"  Size: {'FULL' if result.size_factor >= 1.0 else 'HALF'}")
        else:
            lines.append(f"  BLOCKED (min={self.min_score})")
        return "\n".join(lines)
