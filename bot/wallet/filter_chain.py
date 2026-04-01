"""
Wallet Filter Chain — per-wallet signal filtering with wallet-specific gates.

Adds wallet-specific pre-filters (source, scorecard, R:R, leverage cap)
on top of the existing RiskFilterChain from core/signal_pipeline.py.
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from wallet.profile import WalletProfile

logger = logging.getLogger("bot.wallet.filter_chain")


@dataclass
class WalletFilterResult:
    """Result of running a signal through a wallet's filter chain."""
    approved: bool
    wallet_id: str
    leverage: float = 1.0
    risk_multiplier: float = 1.0
    position_qty: float = 0.0
    rejection_reason: str = ""
    rejection_gate: str = ""
    scorecard_score: int = 0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


def _reject(wallet_id: str, gate: str, reason: str) -> WalletFilterResult:
    """Helper to create a rejection result."""
    logger.debug(f"[W{wallet_id}] REJECTED at {gate}: {reason}")
    return WalletFilterResult(
        approved=False,
        wallet_id=wallet_id,
        rejection_reason=reason,
        rejection_gate=gate,
    )


class WalletFilterChain:
    """Per-wallet filter chain that wraps signal evaluation.

    Gates (in order):
    1. Signal source check — does this wallet accept this signal type?
    2. Scorecard gate — minimum quality score
    3. R:R gate — minimum reward:risk ratio
    4. Position limit — wallet has room?
    5. Circuit breaker — wallet CB not tripped?
    6. Leverage cap — apply wallet-specific leverage limits

    After these pass, the signal proceeds to the shared RiskFilterChain
    for the standard 7-gate validation.
    """

    def __init__(self, profile: WalletProfile):
        self.profile = profile

    def evaluate(
        self,
        signal: Any,
        signal_source: str,
        scorecard_score: int,
        rr_ratio: float,
        open_count: int,
        circuit_breaker_tripped: bool,
        proposed_leverage: float,
        equity: float,
    ) -> WalletFilterResult:
        """Run signal through this wallet's filter chain.

        Args:
            signal: The Signal object from the ensemble
            signal_source: Signal source type (anticipatory, candle_pattern, etc.)
            scorecard_score: Pre-trade quality score (0-100)
            rr_ratio: Reward:risk ratio of the signal
            open_count: Number of open positions in this wallet
            circuit_breaker_tripped: Whether this wallet's CB is active
            proposed_leverage: Leverage proposed for this trade
            equity: This wallet's equity allocation

        Returns:
            WalletFilterResult with approval status and trade parameters
        """
        wid = self.profile.wallet_id
        p = self.profile

        # Gate 1: Signal source
        if not p.accepts_source(signal_source):
            return _reject(wid, "source", f"Source '{signal_source}' not in {p.allowed_sources}")

        # Gate 2: Scorecard
        if scorecard_score < p.min_scorecard:
            return _reject(wid, "scorecard", f"Score {scorecard_score} < min {p.min_scorecard}")

        # Gate 3: R:R ratio
        if rr_ratio < p.min_rr_ratio:
            return _reject(wid, "rr_ratio", f"R:R {rr_ratio:.2f} < min {p.min_rr_ratio:.1f}")

        # Gate 4: Position limit
        if open_count >= p.max_open_positions:
            return _reject(wid, "position_limit", f"Open {open_count} >= max {p.max_open_positions}")

        # Gate 5: Circuit breaker
        if circuit_breaker_tripped:
            conf = getattr(signal, 'confidence', 0)
            if conf < 92:  # Only override with extremely high confidence
                return _reject(wid, "circuit_breaker", "CB tripped, confidence too low to override")

        # Gate 6: Leverage cap
        capped_leverage = min(proposed_leverage, p.max_leverage)

        # Calculate position size based on wallet equity and risk
        stop_distance_pct = 0.0
        entry = getattr(signal, 'entry', 0)
        sl = getattr(signal, 'sl', 0)
        if entry > 0 and sl > 0:
            stop_distance_pct = abs(entry - sl) / entry

        qty = 0.0
        if stop_distance_pct > 0 and entry > 0:
            risk_amount = equity * p.risk_per_trade
            position_notional = risk_amount / stop_distance_pct
            qty = position_notional / entry

        logger.info(
            f"[W{wid}] APPROVED: {getattr(signal, 'symbol', '?')} "
            f"{getattr(signal, 'side', '?')} lev={capped_leverage:.1f}x "
            f"score={scorecard_score} rr={rr_ratio:.2f} qty={qty:.4f}"
        )

        return WalletFilterResult(
            approved=True,
            wallet_id=wid,
            leverage=capped_leverage,
            risk_multiplier=1.0,
            position_qty=qty,
            scorecard_score=scorecard_score,
            metadata={
                "signal_source": signal_source,
                "rr_ratio": rr_ratio,
                "wallet_equity": equity,
                "risk_per_trade": p.risk_per_trade,
                "leverage_mode": p.leverage_mode,
            },
        )
