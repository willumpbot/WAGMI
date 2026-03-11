"""
Signal processing pipeline — extracted from multi_strategy_main._process_symbol().

Provides the RiskFilterChain that validates signals through a sequence of gates:
1. Signal validity (R:R, stop width, side correctness)
2. Circuit breaker check
3. Leverage decision
4. Liquidation safety check
5. Portfolio risk check

Usage:
    chain = RiskFilterChain(risk_mgr, leverage_mgr, config)
    result = chain.evaluate(signal, equity, current_positions)
    if result.approved:
        # proceed to trade
"""

import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any

from strategies.base import Signal

logger = logging.getLogger("bot.core.signal_pipeline")


@dataclass
class FilterResult:
    """Result of running a signal through the risk filter chain."""
    approved: bool
    signal: Signal
    leverage: float = 1.0
    risk_multiplier: float = 1.0
    position_qty: float = 0.0
    rejection_reason: str = ""
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class RiskFilterChain:
    """Sequential risk filter chain for signal validation.

    Extracts the 200+ lines of risk checks from _process_symbol() into
    a clean, testable pipeline.
    """

    def __init__(self, risk_mgr, leverage_mgr, config):
        self.risk_mgr = risk_mgr
        self.leverage_mgr = leverage_mgr
        self.config = config

    def evaluate(
        self,
        signal: Signal,
        equity: float,
        num_strategies_agree: int,
        total_strategies: int,
        current_open_count: int = 0,
        current_extreme_count: int = 0,
        risk_tier: str = "medium",
        cb_conf_override_pct: float = 0.92,
        open_positions: Optional[Dict[str, Any]] = None,
        portfolio_risk_engine=None,
    ) -> FilterResult:
        """Run a signal through all risk gates.

        Returns FilterResult with approved=True if signal passes all checks.
        """
        meta = {}

        # Gate 1: Signal validity (R:R, stop width, side)
        if not signal.is_valid:
            return FilterResult(
                approved=False, signal=signal,
                rejection_reason=f"Invalid signal: stop_width_pct={signal.stop_width_pct:.4f}, "
                                 f"rr={signal.risk_reward_tp1:.2f}"
            )
        # Gate 1b: Minimum R:R from config (stricter than is_valid's 1.0 floor)
        min_rr = getattr(self.config, "min_signal_rr", 1.0)
        if signal.risk_reward_tp1 < min_rr:
            return FilterResult(
                approved=False, signal=signal,
                rejection_reason=f"R:R {signal.risk_reward_tp1:.2f} < min {min_rr:.1f}"
            )
        meta["rr_tp1"] = round(signal.risk_reward_tp1, 2)
        meta["rr_tp2"] = round(signal.risk_reward_tp2, 2)

        # Gate 1c: Fee-drag filter
        # Reject trades where round-trip fees consume too much of the stop width.
        # A stop width of 0.3% with 0.10% round-trip fees = 33% fee drag — barely viable.
        fee_bps = getattr(self.config, "taker_fee_bps", 4)
        round_trip_fee_pct = fee_bps * 2 / 10000.0  # Entry + exit fee as fraction
        stop_pct = signal.stop_width_pct
        if stop_pct > 0:
            fee_drag_pct = round_trip_fee_pct / stop_pct
            meta["fee_drag_pct"] = round(fee_drag_pct * 100, 1)
            max_fee_drag = 0.30  # Fees must be < 30% of stop distance (tightened from 40%)
            if fee_drag_pct > max_fee_drag:
                return FilterResult(
                    approved=False, signal=signal,
                    rejection_reason=f"Fee drag {fee_drag_pct:.0%} > {max_fee_drag:.0%} "
                                     f"(fees={round_trip_fee_pct:.4f}, stop={stop_pct:.4f})",
                    metadata=meta,
                )

        # Gate 1d: Minimum Expected Value filter (stop-width aware)
        # Tight stops have higher fee drag, requiring higher EV to be viable.
        ev = signal.metadata.get("ev_per_dollar") if signal.metadata else None
        min_ev = getattr(self.config, "min_signal_ev", 0.10)
        if stop_pct > 0 and stop_pct < 0.004:
            min_ev = max(min_ev, 0.25)  # Tight stops: fees eat most of the risk
        elif stop_pct > 0 and stop_pct < 0.006:
            min_ev = max(min_ev, 0.22)  # Medium-tight stops: still need higher EV
        if ev is not None and ev < min_ev:
            return FilterResult(
                approved=False, signal=signal,
                rejection_reason=f"EV {ev:.3f} < min {min_ev:.2f} (low expected value)"
            )
        if ev is not None:
            meta["ev_per_dollar"] = ev

        # Gate 2: Circuit breaker
        if not self.risk_mgr.is_trading_allowed(
            confidence=signal.confidence,
            cb_conf_override_pct=cb_conf_override_pct,
        ):
            return FilterResult(
                approved=False, signal=signal,
                rejection_reason="Circuit breaker active"
            )

        # Gate 3: Max open positions
        if current_open_count >= self.config.max_open_positions:
            return FilterResult(
                approved=False, signal=signal,
                rejection_reason=f"Max positions ({self.config.max_open_positions}) reached"
            )

        # Gate 4: Correlation guard — prevent clustered directional risk
        # If we already hold positions, check that adding this trade doesn't
        # create excessive correlated exposure (e.g., 3 long alts all 0.8+ corr)
        if portfolio_risk_engine and open_positions and current_open_count >= 2:
            try:
                corr_matrix = portfolio_risk_engine.compute_correlation_matrix()
                if corr_matrix:
                    # Build positions map including the proposed new trade
                    positions_map = {}
                    for sym, pos in open_positions.items():
                        side = getattr(pos, 'side', 'LONG').lower()
                        positions_map[sym] = side
                    proposed_side = "long" if signal.side == "BUY" else "short"
                    positions_map[signal.symbol] = proposed_side

                    cluster_risk = corr_matrix.get_cluster_risk(positions_map)
                    meta["cluster_risk"] = round(cluster_risk, 3)

                    # High correlation cluster → reduce size or reject
                    # Lowered from 0.90 to 0.85 — 3 correlated longs at 0.85+ all
                    # stop out in a dump, creating compounded drawdown.
                    if cluster_risk >= 0.85:
                        return FilterResult(
                            approved=False, signal=signal,
                            rejection_reason=f"Correlation cluster risk {cluster_risk:.2f} >= 0.85 "
                                             f"(too many correlated positions in same direction)",
                            metadata=meta,
                        )
                    elif cluster_risk >= 0.70:
                        # Don't reject, but reduce risk multiplier by 30%
                        meta["correlation_size_reduction"] = 0.7
                        logger.info(
                            f"[CORR-GUARD] {signal.symbol} cluster_risk={cluster_risk:.2f} >= 0.70 "
                            f"— reducing position size by 30%"
                        )
            except Exception as e:
                logger.debug(f"[CORR-GUARD] Error: {e}")

        # Gate 5: Leverage decision
        lev_decision = self.leverage_mgr.decide(
            confidence=signal.confidence,
            num_strategies_agree=num_strategies_agree,
            total_strategies=total_strategies,
            risk_tier=risk_tier,
            current_extreme_count=current_extreme_count,
        )

        if lev_decision.leverage <= 0:
            return FilterResult(
                approved=False, signal=signal,
                rejection_reason=f"Leverage denied: {lev_decision.reason}"
            )

        # CB override constraints: if CB tripped, cap leverage
        override_constraints = self.risk_mgr.get_override_constraints(signal.confidence)
        leverage = min(lev_decision.leverage, override_constraints["max_leverage"])
        risk_mult = lev_decision.risk_multiplier * override_constraints["size_multiplier"]

        # Apply correlation-based size reduction if flagged
        corr_reduction = meta.get("correlation_size_reduction", 1.0)
        if corr_reduction < 1.0:
            risk_mult *= corr_reduction

        meta["leverage"] = leverage
        meta["leverage_tier"] = lev_decision.tier
        meta["risk_multiplier"] = round(risk_mult, 2)
        meta["num_agree"] = num_strategies_agree

        # Gate 5b: Leverage-scaled EV floor
        # Higher leverage amplifies both wins and losses — require higher EV.
        ev = meta.get("ev_per_dollar")
        if ev is not None and leverage > 2.0:
            n_agree = meta.get("num_agree", 0)
            if leverage > 4.0:
                # 3-agree EV estimates are better calibrated (20% deflation vs 45%)
                lev_ev_floor = 0.22 if n_agree >= 3 else 0.28
            else:
                lev_ev_floor = 0.20
            if ev < lev_ev_floor:
                return FilterResult(
                    approved=False, signal=signal,
                    rejection_reason=f"EV {ev:.3f} < {lev_ev_floor:.2f} "
                                     f"(required for {leverage:.1f}x leverage)",
                    metadata=meta,
                )

        # Gate 6: Liquidation safety
        side_str = "BUY" if signal.side == "BUY" else "SELL"
        notional_est = equity * leverage * 0.5  # rough estimate
        liq_check = self.leverage_mgr.validate_stop_vs_liquidation(
            entry=signal.entry,
            stop_loss=signal.sl,
            side=side_str,
            leverage=leverage,
            notional_usd=notional_est,
        )
        if not liq_check["safe"]:
            return FilterResult(
                approved=False, signal=signal,
                rejection_reason=f"SL ({signal.sl}) beyond liquidation ({liq_check['liquidation_price']:.2f})"
            )
        meta["liq_gap_pct"] = round(liq_check.get("gap_pct", 0), 4)

        # Gate 6: Position sizing
        qty = self.risk_mgr.calculate_qty(
            entry=signal.entry,
            stop_loss=signal.sl,
            leverage=leverage,
            risk_multiplier=risk_mult,
            symbol=signal.symbol,
        )
        if qty <= 0:
            return FilterResult(
                approved=False, signal=signal,
                rejection_reason="Position size zero (stop width too narrow or equity too low)"
            )

        return FilterResult(
            approved=True,
            signal=signal,
            leverage=leverage,
            risk_multiplier=risk_mult,
            position_qty=qty,
            metadata=meta,
        )
