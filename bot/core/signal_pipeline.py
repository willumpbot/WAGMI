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
from typing import Optional, Dict, Any, List

from strategies.base import Signal
from core.filter_annotations import FilterAnnotation, AnnotatedSignal
from execution.leverage import LeverageDecision

logger = logging.getLogger("bot.core.signal_pipeline")

# Optional db logging — disabled in backtest to avoid writes
_rejection_log_enabled: bool = False


def enable_rejection_logging(enabled: bool = True):
    """Enable/disable signal rejection logging to SQLite (paper/live mode only)."""
    global _rejection_log_enabled
    _rejection_log_enabled = enabled


def _log_rejection(signal, gate: str, reason: str):
    """Best-effort rejection log — never raises."""
    if not _rejection_log_enabled:
        return
    try:
        from data import db
        db.log_signal_rejection(
            symbol=signal.symbol,
            strategy=signal.strategy,
            side=signal.side,
            confidence=signal.confidence,
            gate=gate,
            reason=reason,
            entry=getattr(signal, "entry", 0.0),
            sl=getattr(signal, "sl", 0.0),
        )
    except Exception:
        pass


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
        self._missed_trade_tracker = None  # Optional: set via set_missed_trade_tracker()
        self.quality_tracker = None  # Optional: set via set_quality_tracker() for Kelly sizing

    def set_missed_trade_tracker(self, tracker):
        """Inject MissedTradeTracker for rejection tracking."""
        self._missed_trade_tracker = tracker

    def set_quality_tracker(self, tracker):
        """Inject SignalQualityScorer for Kelly-calibrated regime sizing.

        When set, the pipeline uses rolling per-regime win-rates to compute
        fractional Kelly position sizes instead of static REGIME_RISK_MULTIPLIERS.
        Falls back to static multipliers if a regime has fewer than 15 trades.
        """
        self.quality_tracker = tracker

    def _track_pipeline_rejection(self, signal: Signal, reason: str):
        """Record a pipeline rejection in the missed trade tracker."""
        if self._missed_trade_tracker is None:
            return
        try:
            self._missed_trade_tracker.record_rejection(
                signal=signal, reason=reason, gate="pipeline",
            )
        except Exception:
            pass

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
            _reason = (f"Invalid signal: stop_width_pct={signal.stop_width_pct:.4f}, "
                       f"rr={signal.risk_reward_tp1:.2f}")
            _log_rejection(signal, "validity", _reason)
            return FilterResult(approved=False, signal=signal, rejection_reason=_reason)
        # Gate 1b: Minimum R:R from config (stricter than is_valid's 1.0 floor)
        min_rr = getattr(self.config, "min_signal_rr", 1.0)
        if signal.risk_reward_tp1 < min_rr:
            _reason = f"R:R {signal.risk_reward_tp1:.2f} < min {min_rr:.1f}"
            _log_rejection(signal, "rr_floor", _reason)
            return FilterResult(approved=False, signal=signal, rejection_reason=_reason)
        meta["rr_tp1"] = round(signal.risk_reward_tp1, 2)
        meta["rr_tp2"] = round(signal.risk_reward_tp2, 2)

        # Gate 1c: Fee-drag filter
        # Reject trades where round-trip fees + slippage consume too much of stop width.
        # A stop width of 0.3% with 0.10% round-trip fees = 33% fee drag — barely viable.
        fee_bps = getattr(self.config, "taker_fee_bps", 4)
        slippage_bps = getattr(self.config, "slippage_bps", 3)
        # Regime-specific slippage: high-vol/panic have wider spreads
        _regime_slippage = {
            "trending_bull": 1, "trending_bear": 2, "trend": 1,
            "consolidation": 1, "range": 1,
            "high_volatility": 4, "panic": 6,
            "low_liquidity": 5, "news_dislocation": 5,
        }
        _sig_regime = (signal.metadata or {}).get("regime", "unknown")
        _extra_slip = _regime_slippage.get(_sig_regime, 2)
        round_trip_fee_pct = (fee_bps * 2 + _extra_slip) / 10000.0
        stop_pct = signal.stop_width_pct
        if stop_pct > 0:
            fee_drag_pct = round_trip_fee_pct / stop_pct
            meta["fee_drag_pct"] = round(fee_drag_pct * 100, 1)
            # 3+ agree can tolerate more fee drag (higher WR compensates)
            _n_agree = signal.metadata.get("num_agree", 1) if signal.metadata else 1
            max_fee_drag = 0.25 if _n_agree >= 3 else 0.20
            if fee_drag_pct > max_fee_drag:
                _reason = (f"Fee drag {fee_drag_pct:.0%} > {max_fee_drag:.0%} "
                           f"(fees={round_trip_fee_pct:.4f}, stop={stop_pct:.4f})")
                _log_rejection(signal, "fee_drag", _reason)
                return FilterResult(
                    approved=False, signal=signal,
                    rejection_reason=_reason,
                    metadata=meta,
                )

        # Gate 1d: Minimum Expected Value filter (stop-width aware)
        # Tight stops have higher fee drag, requiring higher EV to be viable.
        ev = signal.metadata.get("ev_per_dollar") if signal.metadata else None
        min_ev = getattr(self.config, "min_signal_ev", 0.10)
        if stop_pct > 0 and stop_pct < 0.004:
            min_ev = max(min_ev, 0.06)  # Tight stops: fees eat into risk; fee-drag gate handles worst cases
        elif stop_pct > 0 and stop_pct < 0.006:
            min_ev = max(min_ev, 0.04)  # Medium-tight stops: small bump for fee drag
        # 2-agree trades: add a small buffer above 0. The _WP_DEFLATION table in
        # ensemble.py already applies a regime-calibrated deflation for weak consensus
        # (e.g. 2-agree trending_bull uses 0.40x deflator → win_prob ≈ 28%). Any
        # signal that survived the ensemble EV<0 check is already mathematically positive.
        # A tiny margin here guards against rounding noise.
        _ev_n_agree = signal.metadata.get("num_agree", 3) if signal.metadata else 3
        if _ev_n_agree <= 2:
            min_ev = max(min_ev, 0.03)  # Small buffer; deflation in ensemble handles the heavy lifting
        # Regime-conditional EV floors: calibrated to the deflated EV scale produced by
        # ensemble._WP_DEFLATION. Previous values (0.25/0.28) were for non-deflated EVs
        # and blocked 100% of signals. Deflated EVs for valid signals run 0.02–0.15;
        # floors are now a small positive buffer to confirm genuine edge, not a hard gate.
        _REGIME_EV_FLOORS = {
            "trending_bull":   0.02,  # Deflation already prices in 38% historical WR
            "trending_bear":   0.02,  # Deflation already prices in 33% historical WR
            "consolidation":   0.02,  # Deflation applied; modest bar
            "ranging":         0.02,  # Deflation applied
            "high_volatility": 0.02,  # Best regime; deflation gives higher EVs naturally
        }
        _ev_regime = signal.metadata.get("regime", "unknown") if signal.metadata else "unknown"
        _regime_ev_floor = _REGIME_EV_FLOORS.get(_ev_regime, 0.0)
        if _regime_ev_floor > 0:
            min_ev = max(min_ev, _regime_ev_floor)
        if ev is not None and ev < min_ev:
            _ev_reason = (f"regime floor {_ev_regime}" if _regime_ev_floor > 0 and min_ev <= _regime_ev_floor
                          else "low expected value")
            _reason = f"EV {ev:.3f} < min {min_ev:.2f} ({_ev_reason})"
            _log_rejection(signal, "ev_floor", _reason)
            return FilterResult(
                approved=False, signal=signal,
                rejection_reason=_reason,
            )
        if ev is not None:
            meta["ev_per_dollar"] = ev

        # Gate 2: Circuit breaker
        if not self.risk_mgr.is_trading_allowed(
            confidence=signal.confidence,
            cb_conf_override_pct=cb_conf_override_pct,
        ):
            _log_rejection(signal, "circuit_breaker", "Circuit breaker active")
            return FilterResult(
                approved=False, signal=signal,
                rejection_reason="Circuit breaker active"
            )

        # Gate 3: Max open positions
        if current_open_count >= self.config.max_open_positions:
            _reason = f"Max positions ({self.config.max_open_positions}) reached"
            _log_rejection(signal, "max_positions", _reason)
            return FilterResult(
                approved=False, signal=signal,
                rejection_reason=_reason,
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
                        _reason = (f"Correlation cluster risk {cluster_risk:.2f} >= 0.85 "
                                   f"(too many correlated positions in same direction)")
                        _log_rejection(signal, "correlation", _reason)
                        return FilterResult(
                            approved=False, signal=signal,
                            rejection_reason=_reason,
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
            _reason = f"Leverage denied: {lev_decision.reason}"
            _log_rejection(signal, "leverage", _reason)
            return FilterResult(
                approved=False, signal=signal,
                rejection_reason=_reason,
            )

        # Gate 5a: Graduated leverage eligibility gate (D2)
        # Hard floor at 1.2x (zero-conviction), graduated sizing 1.2x–1.8x,
        # full size above 1.8x. Replaces binary 2.0x gate that blocked all
        # signals in bearish/wide-stop conditions.
        min_leverage_gate = getattr(self.config, "min_leverage_entry_gate", 1.2)
        LEVERAGE_FULL_SIZE = 1.8
        if lev_decision.leverage < min_leverage_gate:
            _reason = f"Below leverage gate: {lev_decision.leverage:.1f}x < {min_leverage_gate:.1f}x minimum"
            _log_rejection(signal, "leverage_gate", _reason)
            return FilterResult(
                approved=False, signal=signal,
                rejection_reason=_reason,
                metadata=meta,
            )

        # Graduated size reduction for sub-optimal leverage (1.2x→0.6 rm, 1.8x→1.0 rm)
        if lev_decision.leverage < LEVERAGE_FULL_SIZE:
            lev_scalar = 0.6 + (lev_decision.leverage - min_leverage_gate) / (LEVERAGE_FULL_SIZE - min_leverage_gate) * 0.4
            lev_decision = LeverageDecision(
                leverage=lev_decision.leverage,
                mode=lev_decision.mode,
                tier=lev_decision.tier,
                reason=lev_decision.reason,
                risk_multiplier=lev_decision.risk_multiplier * lev_scalar,
            )
            logger.info(f"[{signal.symbol}] Leverage gate graduated: {lev_decision.leverage:.1f}x → "
                        f"size scalar {lev_scalar:.2f} (rm={lev_decision.risk_multiplier:.2f})")

        # CB override constraints: if CB tripped, cap leverage
        override_constraints = self.risk_mgr.get_override_constraints(signal.confidence)
        leverage = min(lev_decision.leverage, override_constraints["max_leverage"])
        risk_mult = lev_decision.risk_multiplier * override_constraints["size_multiplier"]

        # Stop-width-dependent leverage cap: tight stops + high leverage = fragile
        # Data: 87.3% conf / 4.73x lev / tight stop = largest loss (-$1,967)
        # SHORT trades get tighter caps: bounces spike faster, liquidation is closer.
        stop_width_pct = abs(signal.entry - signal.sl) / signal.entry if signal.entry > 0 else 1.0
        is_short = signal.side == "SELL"
        if stop_width_pct < 0.005:  # < 0.5% stop
            stop_lev_cap = 2.0 if is_short else 2.5
        elif stop_width_pct < 0.010:  # < 1.0% stop
            stop_lev_cap = 3.0 if is_short else 4.0
        else:
            stop_lev_cap = 4.0 if is_short else 5.0
        if leverage > stop_lev_cap:
            logger.info(f"[{signal.symbol}] Leverage capped {leverage:.1f}x → {stop_lev_cap:.1f}x "
                        f"(stop width {stop_width_pct:.2%} too tight for {leverage:.1f}x, side={signal.side})")
            leverage = stop_lev_cap

        # Apply correlation-based size reduction if flagged
        corr_reduction = meta.get("correlation_size_reduction", 1.0)
        if corr_reduction < 1.0:
            risk_mult *= corr_reduction

        # Apply regime-based risk sizing — Kelly criterion when data is available,
        # fall back to static REGIME_RISK_MULTIPLIERS until enough trades accumulate.
        try:
            from trading_config import get_regime_risk_mult, get_regime_kelly_mult
            _regime = signal.metadata.get("regime", "unknown")
            # Try Kelly sizing first (requires min_trades=15 per regime)
            _quality_tracker = getattr(self, "quality_tracker", None)
            _regime_wr = (
                _quality_tracker.get_regime_win_rate(_regime)
                if _quality_tracker is not None else None
            )
            if _regime_wr is not None:
                _rr = signal.metadata.get("rr_tp1", 1.5) if signal.metadata else 1.5
                _regime_rm = get_regime_kelly_mult(_regime, _regime_wr, float(_rr))
                meta["regime_sizing_method"] = "kelly"
                meta["regime_kelly_wr"] = round(_regime_wr, 3)
            else:
                # Not enough regime data yet — use static multipliers
                _regime_rm = get_regime_risk_mult(_regime)
                meta["regime_sizing_method"] = "static"
            if _regime_rm != 1.0:
                risk_mult *= _regime_rm
                meta["regime_risk_mult"] = round(_regime_rm, 3)
        except Exception:
            pass

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
                lev_ev_floor = 0.20 if n_agree >= 3 else 0.25
            else:
                lev_ev_floor = 0.18
            if ev < lev_ev_floor:
                _reason = (f"EV {ev:.3f} < {lev_ev_floor:.2f} "
                           f"(required for {leverage:.1f}x leverage)")
                _log_rejection(signal, "lev_ev_floor", _reason)
                return FilterResult(
                    approved=False, signal=signal,
                    rejection_reason=_reason,
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
            _reason = f"SL ({signal.sl}) beyond liquidation ({liq_check['liquidation_price']:.2f})"
            _log_rejection(signal, "liquidation", _reason)
            return FilterResult(
                approved=False, signal=signal,
                rejection_reason=_reason,
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
            _log_rejection(signal, "sizing", "Position size zero (stop width too narrow or equity too low)")
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

    def evaluate_annotated(
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
    ) -> AnnotatedSignal:
        """Run a signal through all gates, converting soft gates to annotations.

        Hard gates (safety-critical) still reject immediately:
          - Signal.is_valid (structurally broken)
          - Circuit breaker
          - Max open positions
          - Liquidation safety

        Soft gates produce annotations instead of rejecting:
          - R:R floor, fee-drag, EV floor, correlation, leverage-scaled EV
        """
        annotations: List[FilterAnnotation] = []
        meta: Dict[str, Any] = {}

        # ── Hard Gate: Signal validity ──
        if not signal.is_valid:
            return AnnotatedSignal(
                signal=signal,
                hard_rejected=True,
                hard_rejection_reason=f"Invalid: sw={signal.stop_width_pct:.4f} rr={signal.risk_reward_tp1:.2f}",
            )

        # ── Soft Gate: R:R floor ──
        min_rr = getattr(self.config, "min_signal_rr", 1.0)
        rr = signal.risk_reward_tp1
        meta["rr_tp1"] = round(rr, 2)
        meta["rr_tp2"] = round(signal.risk_reward_tp2, 2)
        annotations.append(FilterAnnotation(
            gate="rr_floor",
            passed=rr >= min_rr,
            severity="reject" if rr < min_rr else ("warning" if rr < min_rr * 1.15 else "ok"),
            value=round(rr, 2),
            threshold=min_rr,
            detail=f"rr={rr:.2f} vs {min_rr:.1f}",
        ))

        # ── Soft Gate: Fee-drag (regime-aware slippage) ──
        fee_bps = getattr(self.config, "taker_fee_bps", 4)
        _regime_slip_ann = {
            "trending_bull": 1, "trending_bear": 2, "trend": 1,
            "consolidation": 1, "range": 1,
            "high_volatility": 4, "panic": 6,
            "low_liquidity": 5, "news_dislocation": 5,
        }
        _sig_regime_ann = (signal.metadata or {}).get("regime", "unknown")
        _extra_slip_ann = _regime_slip_ann.get(_sig_regime_ann, 2)
        round_trip_fee_pct = (fee_bps * 2 + _extra_slip_ann) / 10000.0
        stop_pct = signal.stop_width_pct
        if stop_pct > 0:
            fee_drag_pct = round_trip_fee_pct / stop_pct
            meta["fee_drag_pct"] = round(fee_drag_pct * 100, 1)
            _n_agree_ann = signal.metadata.get("num_agree", 1) if signal.metadata else 1
            max_fee_drag = 0.25 if _n_agree_ann >= 3 else 0.20
            annotations.append(FilterAnnotation(
                gate="fee_drag",
                passed=fee_drag_pct <= max_fee_drag,
                severity="reject" if fee_drag_pct > max_fee_drag else (
                    "warning" if fee_drag_pct > max_fee_drag * 0.8 else "ok"),
                value=round(fee_drag_pct * 100, 1),
                threshold=round(max_fee_drag * 100, 0),
                detail=f"fd={fee_drag_pct:.0%} vs {max_fee_drag:.0%}",
            ))

        # ── Soft Gate: EV floor ──
        ev = signal.metadata.get("ev_per_dollar") if signal.metadata else None
        min_ev = getattr(self.config, "min_signal_ev", 0.10)
        if stop_pct > 0 and stop_pct < 0.004:
            min_ev = max(min_ev, 0.25)
        elif stop_pct > 0 and stop_pct < 0.006:
            min_ev = max(min_ev, 0.22)
        if ev is not None:
            meta["ev_per_dollar"] = ev
            annotations.append(FilterAnnotation(
                gate="ev_floor",
                passed=ev >= min_ev,
                severity="reject" if ev < min_ev else ("warning" if ev < min_ev * 1.2 else "ok"),
                value=round(ev, 3),
                threshold=min_ev,
                detail=f"ev={ev:.3f} vs {min_ev:.2f}",
            ))

        # ── Hard Gate: Circuit breaker ──
        if not self.risk_mgr.is_trading_allowed(
            confidence=signal.confidence,
            cb_conf_override_pct=cb_conf_override_pct,
        ):
            return AnnotatedSignal(
                signal=signal,
                annotations=annotations,
                hard_rejected=True,
                hard_rejection_reason="Circuit breaker active",
                filter_metadata=meta,
            )

        # ── Hard Gate: Max open positions ──
        if current_open_count >= self.config.max_open_positions:
            return AnnotatedSignal(
                signal=signal,
                annotations=annotations,
                hard_rejected=True,
                hard_rejection_reason=f"Max positions ({self.config.max_open_positions}) reached",
                filter_metadata=meta,
            )

        # ── Soft Gate: Correlation guard ──
        if portfolio_risk_engine and open_positions and current_open_count >= 2:
            try:
                corr_matrix = portfolio_risk_engine.compute_correlation_matrix()
                if corr_matrix:
                    positions_map = {}
                    for sym, pos in open_positions.items():
                        side = getattr(pos, 'side', 'LONG').lower()
                        positions_map[sym] = side
                    proposed_side = "long" if signal.side == "BUY" else "short"
                    positions_map[signal.symbol] = proposed_side

                    cluster_risk = corr_matrix.get_cluster_risk(positions_map)
                    meta["cluster_risk"] = round(cluster_risk, 3)

                    annotations.append(FilterAnnotation(
                        gate="correlation",
                        passed=cluster_risk < 0.85,
                        severity="reject" if cluster_risk >= 0.85 else (
                            "warning" if cluster_risk >= 0.70 else "ok"),
                        value=round(cluster_risk, 3),
                        threshold=0.85,
                        detail=f"corr={cluster_risk:.2f}",
                    ))

                    if cluster_risk >= 0.70:
                        meta["correlation_size_reduction"] = 0.7
            except Exception as e:
                logger.debug(f"[CORR-GUARD] Error: {e}")

        # ── Leverage decision (needed for sizing + lev-EV gate) ──
        lev_decision = self.leverage_mgr.decide(
            confidence=signal.confidence,
            num_strategies_agree=num_strategies_agree,
            total_strategies=total_strategies,
            risk_tier=risk_tier,
            current_extreme_count=current_extreme_count,
        )

        if lev_decision.leverage <= 0:
            return AnnotatedSignal(
                signal=signal,
                annotations=annotations,
                hard_rejected=True,
                hard_rejection_reason=f"Leverage denied: {lev_decision.reason}",
                filter_metadata=meta,
            )

        override_constraints = self.risk_mgr.get_override_constraints(signal.confidence)
        leverage = min(lev_decision.leverage, override_constraints["max_leverage"])
        risk_mult = lev_decision.risk_multiplier * override_constraints["size_multiplier"]

        # Stop-width-dependent leverage cap (annotated path)
        stop_width_pct = abs(signal.entry - signal.sl) / signal.entry if signal.entry > 0 else 1.0
        if stop_width_pct < 0.005:
            stop_lev_cap = 2.5
        elif stop_width_pct < 0.010:
            stop_lev_cap = 4.0
        else:
            stop_lev_cap = 5.0
        if leverage > stop_lev_cap:
            logger.info(f"[{signal.symbol}] Leverage capped {leverage:.1f}x → {stop_lev_cap:.1f}x "
                        f"(stop width {stop_width_pct:.2%} too tight)")
            leverage = stop_lev_cap

        corr_reduction = meta.get("correlation_size_reduction", 1.0)
        if corr_reduction < 1.0:
            risk_mult *= corr_reduction

        # Apply regime-based risk sizing (annotated path)
        try:
            from trading_config import get_regime_risk_mult
            _regime = signal.metadata.get("regime", "unknown")
            _regime_rm = get_regime_risk_mult(_regime)
            if _regime_rm != 1.0:
                risk_mult *= _regime_rm
                meta["regime_risk_mult"] = _regime_rm
        except ImportError:
            pass

        meta["leverage"] = leverage
        meta["leverage_tier"] = lev_decision.tier
        meta["risk_multiplier"] = round(risk_mult, 2)
        meta["num_agree"] = num_strategies_agree

        # ── Soft Gate: Leverage-scaled EV floor ──
        ev = meta.get("ev_per_dollar")
        if ev is not None and leverage > 2.0:
            n_agree = meta.get("num_agree", 0)
            if leverage > 4.0:
                lev_ev_floor = 0.22 if n_agree >= 3 else 0.28
            else:
                lev_ev_floor = 0.20
            annotations.append(FilterAnnotation(
                gate="lev_ev_floor",
                passed=ev >= lev_ev_floor,
                severity="reject" if ev < lev_ev_floor else "ok",
                value=round(ev, 3),
                threshold=lev_ev_floor,
                detail=f"ev={ev:.3f} vs {lev_ev_floor:.2f} (at {leverage:.1f}x)",
            ))

        # ── Hard Gate: Liquidation safety ──
        side_str = "BUY" if signal.side == "BUY" else "SELL"
        notional_est = equity * leverage * 0.5
        liq_check = self.leverage_mgr.validate_stop_vs_liquidation(
            entry=signal.entry,
            stop_loss=signal.sl,
            side=side_str,
            leverage=leverage,
            notional_usd=notional_est,
        )
        if not liq_check["safe"]:
            return AnnotatedSignal(
                signal=signal,
                annotations=annotations,
                hard_rejected=True,
                hard_rejection_reason=f"SL beyond liquidation ({liq_check['liquidation_price']:.2f})",
                filter_metadata=meta,
            )
        meta["liq_gap_pct"] = round(liq_check.get("gap_pct", 0), 4)

        # ── Position sizing ──
        qty = self.risk_mgr.calculate_qty(
            entry=signal.entry,
            stop_loss=signal.sl,
            leverage=leverage,
            risk_multiplier=risk_mult,
            symbol=signal.symbol,
        )
        if qty <= 0:
            return AnnotatedSignal(
                signal=signal,
                annotations=annotations,
                hard_rejected=True,
                hard_rejection_reason="Position size zero",
                filter_metadata=meta,
            )

        return AnnotatedSignal(
            signal=signal,
            annotations=annotations,
            hard_rejected=False,
            filter_metadata=meta,
            leverage=leverage,
            risk_multiplier=risk_mult,
            position_qty=qty,
        )
