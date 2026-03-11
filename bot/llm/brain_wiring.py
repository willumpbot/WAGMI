"""
Brain Wiring: connects all LLM brain upgrades to the trading pipeline.

This module provides lazy-initialized singletons for:
1. ThesisTracker — records and measures directional predictions
2. ConfidenceCalibrator — deflates overconfident LLM predictions
3. CounterfactualLearner — tracks skipped trades for missed opportunity detection
4. RegimeFeedbackManager — per-regime adaptive parameters
5. GraduatedRiskManager — progressive drawdown risk reduction

Each component is initialized once and shared across the pipeline.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("bot.llm.brain_wiring")

# ── Lazy singletons ──────────────────────────────────────────────

_thesis_tracker = None
_confidence_calibrator = None
_counterfactual_learner = None
_regime_feedback = None
_graduated_risk = None


def get_thesis_tracker():
    """Get or create the ThesisTracker singleton."""
    global _thesis_tracker
    if _thesis_tracker is None:
        try:
            from llm.thesis_tracker import ThesisTracker
            _thesis_tracker = ThesisTracker()
            logger.info("[BRAIN] ThesisTracker initialized")
        except Exception as e:
            logger.warning(f"[BRAIN] ThesisTracker init failed: {e}")
            return None
    return _thesis_tracker


def get_confidence_calibrator():
    """Get or create the ConfidenceCalibrator singleton."""
    global _confidence_calibrator
    if _confidence_calibrator is None:
        try:
            from llm.confidence_calibrator import ConfidenceCalibrator
            _confidence_calibrator = ConfidenceCalibrator()
            logger.info("[BRAIN] ConfidenceCalibrator initialized")
        except Exception as e:
            logger.warning(f"[BRAIN] ConfidenceCalibrator init failed: {e}")
            return None
    return _confidence_calibrator


def get_counterfactual_learner():
    """Get or create the CounterfactualLearner singleton."""
    global _counterfactual_learner
    if _counterfactual_learner is None:
        try:
            from llm.counterfactual_learner import CounterfactualLearner
            _counterfactual_learner = CounterfactualLearner()
            logger.info("[BRAIN] CounterfactualLearner initialized")
        except Exception as e:
            logger.warning(f"[BRAIN] CounterfactualLearner init failed: {e}")
            return None
    return _counterfactual_learner


def get_regime_feedback():
    """Get or create the RegimeFeedbackManager singleton."""
    global _regime_feedback
    if _regime_feedback is None:
        try:
            from feedback.regime_feedback import RegimeFeedbackManager
            _regime_feedback = RegimeFeedbackManager()
            logger.info("[BRAIN] RegimeFeedbackManager initialized")
        except Exception as e:
            logger.warning(f"[BRAIN] RegimeFeedbackManager init failed: {e}")
            return None
    return _regime_feedback


def get_graduated_risk():
    """Get or create the GraduatedRiskManager singleton."""
    global _graduated_risk
    if _graduated_risk is None:
        try:
            from execution.graduated_risk import GraduatedRiskManager
            _graduated_risk = GraduatedRiskManager()
            logger.info("[BRAIN] GraduatedRiskManager initialized")
        except Exception as e:
            logger.warning(f"[BRAIN] GraduatedRiskManager init failed: {e}")
            return None
    return _graduated_risk


# ── Pipeline Integration Functions ────────────────────────────────

def calibrate_confidence(raw_confidence: float, agent: str = "system") -> float:
    """Apply confidence calibration to a raw confidence value.

    Returns calibrated confidence (0-100 scale), or raw value if calibrator unavailable.
    """
    cal = get_confidence_calibrator()
    if cal is None:
        return raw_confidence
    try:
        return cal.calibrate(raw_confidence, agent=agent)
    except Exception as e:
        logger.debug(f"[BRAIN] Calibration error: {e}")
        return raw_confidence


def record_thesis(symbol: str, side: str, thesis: str, confidence: float,
                  regime: str, entry_price: float, target_price: Optional[float] = None,
                  expected_hold_h: Optional[float] = None,
                  setup_type: Optional[str] = None) -> Optional[str]:
    """Record a new directional thesis. Returns thesis_id or None."""
    tracker = get_thesis_tracker()
    if tracker is None:
        return None
    try:
        return tracker.record_thesis(
            symbol=symbol, side=side, thesis=thesis, confidence=confidence,
            regime=regime, entry_price=entry_price, target_price=target_price,
            expected_hold_h=expected_hold_h, setup_type=setup_type,
        )
    except Exception as e:
        logger.debug(f"[BRAIN] Thesis record error: {e}")
        return None


def close_thesis(thesis_id: str, exit_price: float, pnl_pct: float,
                 max_favorable: Optional[float] = None,
                 max_adverse: Optional[float] = None,
                 actual_hold_h: Optional[float] = None):
    """Close a thesis with its outcome and record calibration observation."""
    tracker = get_thesis_tracker()
    if tracker is None:
        return
    try:
        tracker.close_thesis(
            thesis_id=thesis_id, exit_price=exit_price, pnl_pct=pnl_pct,
            max_favorable=max_favorable, max_adverse=max_adverse,
            actual_hold_h=actual_hold_h,
        )
    except Exception as e:
        logger.debug(f"[BRAIN] Thesis close error: {e}")

    # Also record observation for calibration
    cal = get_confidence_calibrator()
    if cal is not None:
        try:
            # Look up the thesis to get its confidence
            rec = None
            for r in tracker._history:
                if r.thesis_id == thesis_id:
                    rec = r
                    break
            if rec:
                cal.record_observation(
                    claimed_confidence=rec.confidence,
                    was_correct=(pnl_pct > 0),
                    agent="trade_agent",
                    symbol=rec.symbol,
                    regime=rec.regime,
                    pnl_pct=pnl_pct,
                )
        except Exception as e:
            logger.debug(f"[BRAIN] Calibration observation error: {e}")


def record_skipped_trade(symbol: str, side: str, entry_price: float,
                         sl: float, tp1: float, tp2: float,
                         confidence: float, skip_reason: str,
                         strategy: str = "", regime: str = "",
                         metadata: Optional[Dict] = None) -> Optional[str]:
    """Record a skipped trade for counterfactual analysis. Returns record_id."""
    cf = get_counterfactual_learner()
    if cf is None:
        return None
    try:
        return cf.record_skip(
            symbol=symbol, side=side, entry_price=entry_price,
            sl=sl, tp1=tp1, tp2=tp2, confidence=confidence,
            skip_reason=skip_reason, strategy=strategy,
            regime=regime, metadata=metadata,
        )
    except Exception as e:
        logger.debug(f"[BRAIN] Counterfactual record error: {e}")
        return None


def update_counterfactuals_with_price(symbol: str, high: float, low: float, close: float):
    """Update pending counterfactuals with new price data."""
    cf = get_counterfactual_learner()
    if cf is None:
        return
    try:
        cf.update_with_price(symbol, high, low, close)
    except Exception as e:
        logger.debug(f"[BRAIN] Counterfactual update error: {e}")


def record_regime_trade(regime: str, pnl: float, confidence: float,
                        strategy: str, hold_hours: float = 0.0):
    """Record a trade outcome under its regime for feedback tracking."""
    rf = get_regime_feedback()
    if rf is None:
        return
    try:
        rf.record_trade(regime, pnl, confidence, strategy, hold_hours)
    except Exception as e:
        logger.debug(f"[BRAIN] Regime feedback record error: {e}")


def get_brain_context_for_trade(symbol: str, regime: str) -> Dict[str, Any]:
    """Build brain intelligence context for injection into Trade Agent input.

    Returns a dict with all available brain upgrade context.
    """
    ctx = {}

    # 1. Thesis accuracy stats
    tracker = get_thesis_tracker()
    if tracker:
        try:
            thesis_ctx = tracker.get_prompt_context(symbol=symbol, regime=regime)
            if thesis_ctx:
                ctx["thesis_accuracy"] = thesis_ctx
        except Exception:
            pass

    # 2. Confidence calibration info
    cal = get_confidence_calibrator()
    if cal:
        try:
            cal_ctx = cal.get_prompt_context()
            if cal_ctx:
                ctx["calibration"] = cal_ctx
        except Exception:
            pass

    # 3. Counterfactual learning (are we being too conservative?)
    cf = get_counterfactual_learner()
    if cf:
        try:
            cf_ctx = cf.get_prompt_context()
            if cf_ctx:
                ctx["counterfactual"] = cf_ctx
        except Exception:
            pass

    # 4. Regime-specific feedback
    rf = get_regime_feedback()
    if rf:
        try:
            regime_ctx = rf.get_prompt_context(regime)
            if regime_ctx:
                ctx["regime_feedback"] = regime_ctx
        except Exception:
            pass

    # 5. Graduated risk drawdown context
    grm = get_graduated_risk()
    if grm:
        try:
            dd_ctx = grm.get_llm_context()
            if dd_ctx:
                ctx["drawdown_alert"] = dd_ctx
        except Exception:
            pass

    return ctx


def get_brain_context_for_risk(regime: str) -> Dict[str, Any]:
    """Build brain intelligence context for injection into Risk Agent input."""
    ctx = {}

    # 1. Regime recommendation (confidence floor + risk multiplier)
    rf = get_regime_feedback()
    if rf:
        try:
            rec = rf.get_regime_recommendation(regime)
            ctx["regime_rec"] = rec
        except Exception:
            pass

    # 2. Graduated risk status
    grm = get_graduated_risk()
    if grm:
        try:
            status = grm.get_status()
            if status.get("drawdown_pct", 0) > 1.0:
                ctx["drawdown"] = status
        except Exception:
            pass

    return ctx
