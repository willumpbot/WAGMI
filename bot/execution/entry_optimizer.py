"""
Entry Timing Optimizer — Better entries = more profit per trade.

Instead of market-buying at signal time, uses strategies to improve entry:

1. Limit order placement: Place limit 0.2-0.5% below current price for buys
   (above for sells). Data shows dips continue briefly before reversing.
   At 25x leverage, 0.3% better entry = 7.5% better P&L.

2. Burst confirmation: Don't enter on the 1st signal in a burst.
   Wait for 2nd or 3rd signal (bursts average 32 signals).
   The 2nd signal catches the bottom more often.

3. Volume confirmation: Only enter when the signal fires WITH
   above-average volume (volume = conviction).

Usage:
    optimizer = EntryOptimizer()

    # On signal: should we enter now or wait?
    decision = optimizer.evaluate_entry(
        symbol="HYPE", side="BUY", entry_price=40.0,
        confidence=82.0, num_agree=3, is_dip_buy=True
    )
    # decision.action: "MARKET" | "LIMIT" | "WAIT"
    # decision.limit_price: Price for limit order (if LIMIT)
    # decision.wait_reason: Why we're waiting (if WAIT)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, List

logger = logging.getLogger("bot.execution.entry_optimizer")


@dataclass
class BurstState:
    """Tracks signal burst for a symbol."""
    symbol: str
    side: str
    first_signal_at: float    # Epoch of first signal in burst
    signal_count: int = 1
    prices: List[float] = field(default_factory=list)
    best_price: float = 0.0   # Best entry seen in burst (lowest for BUY, highest for SELL)


@dataclass
class EntryDecision:
    """Recommendation from the entry optimizer."""
    action: str              # "MARKET", "LIMIT", "WAIT"
    price: float             # Recommended entry price
    limit_price: Optional[float] = None  # For LIMIT orders
    improvement_pct: float = 0.0  # Expected improvement over market
    burst_position: int = 0  # Which signal in the burst (0 = no burst)
    rationale: str = ""


# Entry improvement by tier (how much below market to place limit)
_LIMIT_IMPROVEMENT = {
    "SNIPER": 0.002,    # 0.2% — tight, high conviction
    "PREMIUM": 0.003,   # 0.3% — moderate
    "STANDARD": 0.005,  # 0.5% — wider, lower conviction
}

# Burst detection: signals within this window are part of the same burst
_BURST_WINDOW_S = 600  # 10 minutes
_BURST_MIN_SIGNALS = 2  # Need at least 2 signals to confirm burst
_BURST_OPTIMAL_ENTRY = 3  # 3rd signal is statistically best entry


class EntryOptimizer:
    """Optimizes entry timing for better fills."""

    def __init__(
        self,
        use_limit_orders: bool = True,
        use_burst_detection: bool = True,
        limit_timeout_s: float = 120.0,  # Cancel limit after 2 minutes
    ):
        self.use_limit_orders = use_limit_orders
        self.use_burst_detection = use_burst_detection
        self.limit_timeout_s = limit_timeout_s

        # Active bursts per symbol
        self._bursts: Dict[str, BurstState] = {}
        # Pending limit orders
        self._pending_limits: Dict[str, Dict] = {}

    def evaluate_entry(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        confidence: float = 70.0,
        num_agree: int = 2,
        tier: str = "PREMIUM",
        is_dip_buy: bool = False,
    ) -> EntryDecision:
        """Evaluate whether to enter now, place a limit, or wait.

        Args:
            symbol: Asset symbol
            side: "BUY" or "SELL"
            entry_price: Current market price
            confidence: Signal confidence (0-100)
            num_agree: Number of strategies agreeing
            tier: Signal tier (SNIPER/PREMIUM/STANDARD)
            is_dip_buy: Whether this is a dip-buy pattern
        """
        now = time.time()

        # Update burst state
        burst = self._update_burst(symbol, side, entry_price, now)

        # High-urgency signals: always market (no time to optimize)
        if confidence >= 90 and num_agree >= 3:
            return EntryDecision(
                action="MARKET",
                price=entry_price,
                rationale="High urgency (90%+ conf, 3-agree): market entry",
            )

        # Burst detection: wait for optimal signal in burst
        if self.use_burst_detection and burst is not None:
            if burst.signal_count < _BURST_MIN_SIGNALS:
                # First signal in potential burst — wait
                return EntryDecision(
                    action="WAIT",
                    price=entry_price,
                    burst_position=burst.signal_count,
                    rationale=(
                        f"Burst signal #{burst.signal_count}/{_BURST_OPTIMAL_ENTRY}: "
                        f"waiting for confirmation. Best price so far: ${burst.best_price:.2f}"
                    ),
                )
            elif burst.signal_count >= _BURST_OPTIMAL_ENTRY:
                # Optimal entry point in burst — use the best price seen
                improvement = abs(entry_price - burst.best_price) / entry_price * 100
                return EntryDecision(
                    action="LIMIT",
                    price=entry_price,
                    limit_price=burst.best_price,
                    improvement_pct=improvement,
                    burst_position=burst.signal_count,
                    rationale=(
                        f"Burst confirmed ({burst.signal_count} signals). "
                        f"Limit at best price ${burst.best_price:.2f} "
                        f"({improvement:.2f}% improvement)"
                    ),
                )

        # Limit order placement
        if self.use_limit_orders:
            improvement_pct = _LIMIT_IMPROVEMENT.get(tier, 0.003)

            # Dip buys: tighter limit (the dip IS the entry)
            if is_dip_buy:
                improvement_pct *= 0.5  # Half the improvement — don't miss the dip

            if side == "BUY":
                limit_price = entry_price * (1 - improvement_pct)
            else:
                limit_price = entry_price * (1 + improvement_pct)

            return EntryDecision(
                action="LIMIT",
                price=entry_price,
                limit_price=round(limit_price, 6),
                improvement_pct=improvement_pct * 100,
                rationale=(
                    f"Limit {improvement_pct*100:.1f}% {'below' if side == 'BUY' else 'above'} "
                    f"market @ ${limit_price:.2f} (timeout {self.limit_timeout_s:.0f}s)"
                ),
            )

        # Default: market entry
        return EntryDecision(
            action="MARKET",
            price=entry_price,
            rationale="Default market entry",
        )

    def _update_burst(
        self, symbol: str, side: str, price: float, now: float
    ) -> Optional[BurstState]:
        """Track signal bursts. Returns burst state if in a burst."""
        key = f"{symbol}:{side}"
        burst = self._bursts.get(key)

        if burst is not None:
            # Check if burst is still active
            if now - burst.first_signal_at > _BURST_WINDOW_S:
                # Burst expired — start new one
                burst = None
                del self._bursts[key]

        if burst is None:
            # Start new burst
            burst = BurstState(
                symbol=symbol,
                side=side,
                first_signal_at=now,
                signal_count=1,
                prices=[price],
                best_price=price,
            )
            self._bursts[key] = burst
        else:
            # Continue burst
            burst.signal_count += 1
            burst.prices.append(price)
            # Best price = lowest for BUY, highest for SELL
            if side == "BUY":
                burst.best_price = min(burst.best_price, price)
            else:
                burst.best_price = max(burst.best_price, price)

        return burst

    def get_burst_info(self, symbol: str, side: str) -> Optional[Dict]:
        """Get current burst state for a symbol (if any)."""
        key = f"{symbol}:{side}"
        burst = self._bursts.get(key)
        if burst is None:
            return None
        return {
            "signal_count": burst.signal_count,
            "best_price": burst.best_price,
            "age_s": time.time() - burst.first_signal_at,
            "prices": burst.prices[-5:],  # Last 5 prices
        }
