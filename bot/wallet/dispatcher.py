"""
Wallet Dispatcher — routes signals to both wallets and collects approvals.

Receives a signal once from the shared analytical engine, evaluates it
against both wallet profiles, and returns which wallets (if any) approve.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from wallet.profile import (
    WalletProfile, SOURCE_ANTICIPATORY, SOURCE_CANDLE_PATTERN,
    SOURCE_REGIME_PREDICTION, SOURCE_ENSEMBLE,
)
from wallet.filter_chain import WalletFilterChain, WalletFilterResult
from wallet.context import WalletContext
from wallet.guardian import AccountGuardian

logger = logging.getLogger("bot.wallet.dispatcher")


def classify_signal_source(signal: Any) -> str:
    """Determine the source type of a signal for wallet filtering.

    Checks signal metadata to classify it as anticipatory, candle_pattern,
    regime_prediction, or ensemble (default).
    """
    # Check metadata dict (set by anticipatory engine, candle patterns, etc.)
    meta = getattr(signal, 'metadata', None) or {}
    if isinstance(meta, dict):
        source = meta.get('signal_source', '')
        if source:
            return source

    # Check entry_reasons (set during signal generation)
    reasons = getattr(signal, 'entry_reasons', None) or {}
    if isinstance(reasons, dict):
        source = reasons.get('signal_source', '')
        if source:
            return source

    # Heuristic: check strategy name for candle/regime patterns
    strategy = getattr(signal, 'strategy', '') or ''
    strategy_lower = strategy.lower()

    if 'anticipatory' in strategy_lower or 'pending' in strategy_lower:
        return SOURCE_ANTICIPATORY
    if any(p in strategy_lower for p in ('candle', 'exhaustion', 'shooting_star', 'institutional')):
        return SOURCE_CANDLE_PATTERN
    if any(p in strategy_lower for p in ('regime_pred', 'lead_lag', 'btc_lead')):
        return SOURCE_REGIME_PREDICTION

    return SOURCE_ENSEMBLE


def _compute_rr_ratio(signal: Any) -> float:
    """Calculate reward:risk ratio from signal TP1 and SL."""
    entry = getattr(signal, 'entry', 0)
    sl = getattr(signal, 'sl', 0)
    tp1 = getattr(signal, 'tp1', 0)

    if entry <= 0 or sl <= 0 or tp1 <= 0:
        return 0.0

    risk = abs(entry - sl)
    reward = abs(tp1 - entry)

    if risk <= 0:
        return 0.0

    return reward / risk


class WalletDispatcher:
    """Dispatches signals to both wallets and collects approvals."""

    def __init__(
        self,
        wallet_a: WalletContext,
        wallet_b: WalletContext,
        guardian: AccountGuardian,
    ):
        self.wallet_a = wallet_a
        self.wallet_b = wallet_b
        self.guardian = guardian
        self._filter_a = WalletFilterChain(wallet_a.profile)
        self._filter_b = WalletFilterChain(wallet_b.profile)

    def dispatch(
        self,
        signal: Any,
        scorecard_score: int,
        proposed_leverage: float,
        total_equity: float,
        signal_source: Optional[str] = None,
    ) -> List[Tuple[WalletContext, WalletFilterResult]]:
        """Evaluate a signal against both wallets.

        Args:
            signal: The Signal from the ensemble/anticipatory engine
            scorecard_score: Pre-trade quality score (0-100)
            proposed_leverage: Base leverage proposal (before wallet caps)
            total_equity: Total account equity (wallets split this)
            signal_source: Override signal source classification

        Returns:
            List of (WalletContext, WalletFilterResult) for wallets that approve
        """
        if signal_source is None:
            signal_source = classify_signal_source(signal)

        rr_ratio = _compute_rr_ratio(signal)
        symbol = getattr(signal, 'symbol', '')
        side = getattr(signal, 'side', '')

        logger.info(
            f"Dispatching {symbol} {side} (source={signal_source}, "
            f"score={scorecard_score}, rr={rr_ratio:.2f}, lev={proposed_leverage:.1f}x)"
        )

        approvals: List[Tuple[WalletContext, WalletFilterResult]] = []

        for ctx, fchain in [
            (self.wallet_a, self._filter_a),
            (self.wallet_b, self._filter_b),
        ]:
            equity = ctx.wallet_equity(total_equity)
            cb_tripped = False
            if ctx.circuit_breaker is not None:
                cb_tripped = getattr(ctx.circuit_breaker, 'tripped', False)

            result = fchain.evaluate(
                signal=signal,
                signal_source=signal_source,
                scorecard_score=scorecard_score,
                rr_ratio=rr_ratio,
                open_count=ctx.get_open_count(),
                circuit_breaker_tripped=cb_tripped,
                proposed_leverage=proposed_leverage,
                equity=equity,
            )

            if not result.approved:
                continue

            # Cross-wallet guardian check
            proposed_notional = result.position_qty * getattr(signal, 'entry', 0)
            guardian_ok, guardian_reason = self.guardian.can_open(
                wallet_a=self.wallet_a,
                wallet_b=self.wallet_b,
                proposed_symbol=symbol,
                proposed_side=side,
                proposed_notional=proposed_notional,
                proposed_wallet_id=ctx.wallet_id,
            )

            if not guardian_ok:
                logger.warning(
                    f"[W{ctx.wallet_id}] Guardian blocked: {guardian_reason}"
                )
                continue

            approvals.append((ctx, result))

        logger.info(
            f"Dispatch result: {len(approvals)} wallet(s) approved "
            f"({', '.join(f'W{ctx.wallet_id}' for ctx, _ in approvals) or 'none'})"
        )

        return approvals
